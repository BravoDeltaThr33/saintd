"""Builds and enriches the local directory from the public APIs."""

from __future__ import annotations

import datetime as dt
import re
import threading
import time
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Callable

from . import heuristics as H
from . import ru
from .lives import roles
from . import sources as S
from . import wikical as W
from .db import DB, cats_to_str, dumps, loads, str_to_cats
from .net import Cancelled, Http, NetError
from .text import STOPWORDS as _STOP
from .text import _letters, fold, has_cyrillic, html_to_text, sig_tokens
from .translate import TranslationError, Translator

BUILD_VERSION = "2"
PARTIAL_BUILD = "partial"              # some downloads failed: finish the build at the next start


@dataclass
class Report:
    """Callbacks the UI (or CLI) passes in to watch progress."""
    stage: Callable[[str], None] = lambda s: None
    progress: Callable[[int, int, str], None] = lambda d, t, msg: None
    log: Callable[[str], None] = lambda m: None


def occasion_of(title: str) -> str:
    t = H.expand(title)
    for rx, lab in ((r"^Repose of", "Repose"), (r"^Translation of the Relics", "Translation of relics"),
                    (r"^Uncovering of the Relics", "Uncovering of relics"), (r"^Relics of", "Relics"),
                    (r"^Finding of the relics", "Uncovering of relics"),
                    (r"^Synaxis of", "Synaxis"), (r"^Commemoration of", "Commemoration"),
                    (r"Перенесение мощей", "Translation of relics"), (r"обретение мощей", "Uncovering of relics"),
                    (r"^Преставление", "Repose")):
        if re.search(rx, t, re.I):
            return lab
    return ""


def _tokset(text: str) -> set[str]:
    return set(sig_tokens(text))


_ADJ_SUFFIX = re.compile(r"(?:skaia|skaya|skii|skiy|sky|ski|skoi|skoe|ianin|anin|enin|ian|ensis|ite)$")
_MATCH_STOP = {"fool", "christ", "for", "sake", "hermit", "recluse", "faster", "zatvornik", "abbot", "hieromonk",
               "presbyter", "deacon", "archdeacon", "reader", "wonderworking", "monastery", "church", "with",
               "and", "other", "others", "his", "her", "their", "godbearer", "god", "bearer", "theophorus",
               "theophoros", "all", "praised", "glorious"}
_EPITHETS = {"great", "new", "younger", "elder", "first", "called"}   # tell namesakes apart
_MARTYRISH = {"Martyr", "Hieromartyr", "Great-martyr", "New Martyr"}
_NOT_MARTYR = {"Monastic", "Righteous", "Fool-for-Christ", "Royal", "Prophet"}


def _norm_tok(t: str) -> str:
    t = fold(t)
    # common transliteration variants: Yelkhovsky/Elkhovsky, Tsitserov/Cicerov, Aleksander/Alexander
    t = re.sub(r"^[iy]e", "e", t).replace("ts", "c").replace("tz", "c").replace("x", "ks")
    t2 = _ADJ_SUFFIX.sub("", t)
    return _letters(t2 if len(t2) >= 3 else t)


def _name_parts(text: str) -> tuple[str, list[str]]:
    """(normalised first name, other significant tokens) of a title. Surnames
    in parentheses ('Alexander (Shchukin)') count; dates do not."""
    core = H.match_core(text) if not has_cyrillic(text) else text
    paren = " ".join(p for p in re.findall(r"\(([^()]*)\)", H.expand(text)) if not re.search(r"\d", p))
    toks = [t for t in re.findall(r"[A-Za-z][A-Za-z']+", core + " " + paren)]
    fn = H.first_name(core)
    first = _norm_tok(fn) if fn else ""
    others = []
    for t in toks:
        ft = fold(t)
        if t == fn or (ft in _STOP and ft not in _EPITHETS) or ft in _MATCH_STOP or len(t) < 3 \
                or re.fullmatch(r"[IVX]+", t):
            continue
        others.append(_norm_tok(t))
    return first, list(dict.fromkeys(others))


def _names_similar(a: str, b: str) -> bool:
    if a == b:
        return True
    a, b = a.lstrip("h") or a, b.lstrip("h") or b      # Hadrian/Adrian, Hilarion/Ilarion
    if not a or not b or a[0] != b[0]:
        return False
    if len(a) >= 5 and len(b) >= 5 and a[:5] == b[:5]:
        return True
    if SequenceMatcher(None, a, b).ratio() >= 0.75:
        return True
    # Russian renders Greek theta as "f" (Feodor/Theodore, Dosifei/Dositheus)
    a2, b2 = a.replace("f", "t"), b.replace("f", "t")
    return SequenceMatcher(None, a2, b2).ratio() >= 0.8


def _tok_eq(a: str, b: str) -> bool:
    if len(a) < 3 or len(b) < 3:
        return a == b
    p = min(4, len(a), len(b))
    if a[:p] == b[:p]:
        return True
    # transliteration drift: Diveyevo/Diveevo, Zasyedatelev/Zasedatelev
    return len(a) >= 5 and len(b) >= 5 and a[:2] == b[:2] and SequenceMatcher(None, a, b).ratio() >= 0.75


def _cat_conflict(a: set, b: set) -> bool:
    am, bm = bool(a & _MARTYRISH), bool(b & _MARTYRISH)
    if am and not bm and (b & _NOT_MARTYR):
        return True
    if bm and not am and (a & _NOT_MARTYR):
        return True
    return False


def _pronoun_gender(text: str, default: str) -> str:
    """Female when the description speaks of the saint as 'she'/'her'."""
    t = f" {fold(text)} "
    she = len(re.findall(r"\b(she|her|herself|nun|abbess|virgin|widow|wife|daughter|queen|princess|empress)\b", t))
    he = len(re.findall(r"\b(he|his|him|himself|monk|abbot|bishop|priest|husband|son|king|prince|emperor)\b", t))
    return "Female" if she > he else default


def _norm_title(t: str) -> str:
    t = (t or "").replace("_", " ").strip()
    return t[:1].upper() + t[1:]


def _first_tok(text: str) -> str:
    fn = H.first_name(H.core_name(text)) if not has_cyrillic(text) else text.split()[0]
    return _letters(fold(fn))[:4]


class Syncer:
    def __init__(self, cfg, db: DB, http: Http, translator: Translator) -> None:
        self.cfg = cfg
        self.db = db
        self.http = http
        self.tr = translator
        self.lock = threading.Lock()      # one build/enrich at a time
        self._failures = 0
        self._labels: dict[str, str] = {}
        self._day_names: dict[tuple[int, int], dict[str, int]] = {}

    # ============================================================ helpers
    def _day_index(self) -> dict[tuple[int, int], list[dict]]:
        idx: dict[tuple[int, int], list[dict]] = {}
        with self.db.lock:
            rows = self.db.con.execute(
                "SELECT s.id, s.key, s.name, s.core, s.kind, s.az_slug, f.month, f.day "
                "FROM saints s JOIN feasts f ON f.saint_id=s.id").fetchall()
        for r in rows:
            idx.setdefault((r["month"], r["day"]), []).append(dict(r))
        return idx

    def _find_same_person(self, key: str, kind: str, keys: dict[str, int], by_first: dict[str, list]) -> int | None:
        if key in keys:
            return keys[key]
        if kind != "saint":
            return None
        toks = key.split()
        if len(toks) < 2:
            return None
        ts = set(toks)
        for other_ts, sid in by_first.get(toks[0], []):
            small, big = (ts, other_ts) if len(ts) <= len(other_ts) else (other_ts, ts)
            if len(small) >= 2 and small <= big:
                return sid
        return None

    def upsert(self, month: int, day: int, title: str, source: str, keys: dict, by_first: dict,
               extra: dict | None = None) -> int:
        name = H.display_name(title)
        kind = H.classify_kind(title)
        key = H.dedupe_key(title) or name.lower()
        if kind in ("feast", "icon", "memorial"):
            key = f"{kind}:{key}"
        occ = occasion_of(title)
        sid = self.db.src_title(source, month, day, title)
        if sid is None:
            sid = self._find_same_person(key, kind, keys, by_first)
        if sid is None:                     # same name already filed on this day (earlier build)
            sid = self._day_names.get((month, day), {}).get(name)
        if sid is None:
            cnt = H.country_from_name(title)
            cent = H.century_from_title(title) if occ in ("", "Repose") else None
            fields = {
                "key": key, "name": name, "core": H.core_name(title), "kind": kind,
                "gender": H.gender_guess(title, kind), "gender_src": "name",
                "century": cent, "century_src": "calendar" if cent is not None else "",
                "year_hint": None if occ and occ != "Repose" else H.year_from_title(title),
                "country": cnt[0] if cnt else "Unknown", "country_src": "name" if cnt else "",
                "place": cnt[1] if cnt else "",
                "categories": cats_to_str(H.categories_for(title, kind)),
                "sources": f"|{source}|",
            }
            if extra:
                fields.update(extra)
            if self.db.saint_by_key(key):
                key = f"{key}#{month}-{day}"
                fields["key"] = key
            sid = self.db.insert_saint(fields)
            keys[key] = sid
            toks = key.split("#")[0].split()
            if toks:
                by_first.setdefault(toks[0], []).append((set(toks), sid))
        else:
            cur = self.db.get_saint(sid) or {}
            upd: dict = {}
            if not occ:
                labels = [f["label"] for f in self.db.feasts(sid)]
                if labels and all(labels):          # so far only known from relics/repose feasts
                    upd["name"] = name
                    upd["core"] = H.core_name(title)
                if cur.get("year_hint") is None:
                    yh = H.year_from_title(title)
                    if yh:
                        upd["year_hint"] = yh
            if cur.get("century") is None and occ in ("", "Repose"):
                c = H.century_from_title(title)
                if c is not None:
                    upd["century"], upd["century_src"] = c, "calendar"
            cats = str_to_cats(cur.get("categories", "")) + H.categories_for(title, kind)
            upd["categories"] = cats_to_str(cats)
            if f"|{source}|" not in cur.get("sources", "|"):
                upd["sources"] = cur.get("sources", "|") + f"{source}|"
            self.db.update_saint(sid, upd, commit=False)
        self.db.add_feast(sid, month, day, occ, source, commit=False)
        self.db.put_src_title(source, month, day, title, sid)
        self._day_names.setdefault((month, day), {}).setdefault(name, sid)
        return sid

    def _indexes(self) -> tuple[dict, dict]:
        keys: dict[str, int] = {}
        by_first: dict[str, list] = {}
        self._day_names = {}
        with self.db.lock:
            for r in self.db.con.execute("SELECT s.id, s.name, f.month, f.day FROM saints s "
                                         "JOIN feasts f ON f.saint_id=s.id").fetchall():
                self._day_names.setdefault((r["month"], r["day"]), {}).setdefault(r["name"], r["id"])
            for r in self.db.con.execute("SELECT id, key, kind FROM saints").fetchall():
                keys[r["key"]] = r["id"]
                if r["kind"] == "saint":
                    toks = r["key"].split("#")[0].split()
                    if toks:
                        by_first.setdefault(toks[0], []).append((set(toks), r["id"]))
        return keys, by_first

    # ============================================================ build
    def build(self, rep: Report) -> None:
        with self.lock:
            self.http.stop.clear()
            self._failures = 0                       # downloads that failed (counted by the stages)
            trads: list[str | None] = [None] + (["greek"] if self.cfg["include_greek"] else [])
            self._stage_calendar(rep, trads)
            pre = None
            if self.cfg["use_azbyka"]:
                # fetch the Russian calendar in parallel (different host) while lives download
                pre = threading.Thread(target=self._prefetch_azbyka, daemon=True)
                pre.start()
            self._stage_lives(rep, trads)
            if self.cfg["use_azbyka"]:
                if pre:
                    pre.join()
                self._stage_azbyka(rep)
            if self.cfg["use_wikical"]:
                self._stage_wikical(rep)
            self._stage_merge_same_day(rep)
            with self.db.lock:
                people = self.db.con.execute("SELECT COUNT(*) FROM saints").fetchone()[0]
            if not people:
                raise NetError("no calendar could be downloaded. Check the internet connection; the build "
                               "starts again the next time you open saintd (or press Ctrl+B).")
            # a build with failed downloads is completed at the next start
            self.db.set_meta("build_version", BUILD_VERSION if not self._failures else PARTIAL_BUILD)
            self.db.set_meta("built_at", time.time())
            self.db.relink_favorites()              # saved saints survive a rebuild
            if self._failures:
                rep.log(f"{self._failures} downloads failed; they are tried again the next time saintd starts "
                        f"(or press Ctrl+B).")
            rep.stage("Directory ready")

    def _stage_merge_same_day(self, rep: Report) -> int:
        """One saint in three calendars: entries kept on the same day under the
        same name once the titles are set aside ("Martyr", "Venerable-martyr"
        and "Virgin-martyr Anastasia the Roman") become one entry. Only names
        of two words or more, and never two different Wikidata items or genders."""
        rep.stage("Merging duplicates")
        with self.db.lock:
            rows = [dict(r) for r in self.db.con.execute(
                "SELECT s.id, s.name, s.gender, s.qid, s.sources, f.month, f.day FROM saints s "
                "JOIN feasts f ON f.saint_id=s.id WHERE s.kind='saint'").fetchall()]
        groups: dict[tuple, dict[int, dict]] = {}
        for r in rows:
            core = " ".join(re.sub(r"[^\w\s]", " ", H.match_core(r["name"]).lower()).split())
            if len(core.split()) >= 2:
                groups.setdefault((r["month"], r["day"], core), {})[r["id"]] = r
        gone: set[int] = set()
        merged = 0
        for g in groups.values():
            items = [x for i, x in g.items() if i not in gone]
            if len(items) < 2:
                continue
            if len({x["qid"] for x in items if x["qid"]}) > 1:
                continue
            if len({x["gender"] for x in items if x["gender"] in ("Male", "Female")}) > 1:
                continue
            keep = min(items, key=lambda x: (not x["qid"], "|orthocal|" not in x["sources"], x["id"]))
            for x in items:
                if x["id"] != keep["id"]:
                    self.db.merge_into(keep["id"], x["id"])
                    gone.add(x["id"])
                    merged += 1
        if merged:
            rep.log(f"Merged {merged} entries kept twice under the same name.")
        return merged

    def _stage_calendar(self, rep: Report, trads) -> None:
        rep.stage("Calendar of saints (orthocal)")
        months: dict[tuple, list] = {}
        jobs = [(t, y, m) for t in trads for y in (S.REF_YEAR, S.REF_YEAR + 1) for m in range(1, 13)]
        for i, (t, y, m) in enumerate(jobs):
            rep.progress(i, len(jobs), f"{t or 'slavic'} {y}-{m:02d}")
            try:
                months[(t, y, m)] = S.orthocal_month(self.http, y, m, t)
            except NetError as e:
                rep.log(f"orthocal month {y}-{m:02d} ({t or 'slavic'}): {e}")
                months[(t, y, m)] = []
                self._failures += 1
        rep.progress(len(jobs), len(jobs), "")
        keys, by_first = self._indexes()
        n = 0
        for t in trads:
            for m in range(1, 13):
                cur = {(d.get("month"), d.get("day")): d for d in months.get((t, S.REF_YEAR, m), [])}
                nxt = {(d.get("month"), d.get("day")): d for d in months.get((t, S.REF_YEAR + 1, m), [])}
                for (mm, dd), d in cur.items():
                    if not mm or not dd:
                        continue
                    for title in d.get("saints") or []:
                        self.upsert(mm, dd, title, "orthocal", keys, by_first)
                        n += 1
                    fixed = set((nxt.get((mm, dd)) or {}).get("feasts") or [])
                    for title in d.get("feasts") or []:
                        if title in fixed:          # same date next year => fixed feast, not movable
                            self.upsert(mm, dd, title, "orthocal", keys, by_first)
                            n += 1
        self.db.commit()
        rep.log(f"Calendar: {n} commemorations read from orthocal")

    def _match_on_day(self, title: str, cands: list[dict]) -> int | None:
        """Find the entry among `cands` (same church date) that names the same
        saint as `title`, tolerating transliteration and wording differences."""
        names = {H.expand(title), H.display_name(title)}
        key = H.dedupe_key(title)
        for c in cands:
            if c["name"] in names or c["key"].split("#")[0] == key:
                return c["id"]
        fx, ox = _name_parts(title)
        if not fx:
            return None
        cats_x = set(H.categories_for(title, "saint"))
        best, best_score = None, 0
        for c in cands:
            fc, oc = _name_parts(c["core"] or c["name"])
            if not fc or not _names_similar(fx, fc):
                continue
            if _cat_conflict(cats_x, set(H.categories_for(c["name"], "saint"))):
                continue
            overlap = sum(1 for t in ox if any(_tok_eq(t, u) for u in oc))
            if ox and oc and overlap == 0:
                continue
            if bool(ox) != bool(oc):           # one name says more: only if no other namesake that day
                same_first = [c2 for c2 in cands if _names_similar(fx, _name_parts(c2["core"] or c2["name"])[0])]
                if len(same_first) > 1:
                    continue
            score = 1 + overlap
            if score > best_score:
                best, best_score = c["id"], score
        return best

    def _stage_lives(self, rep: Report, trads) -> None:
        rep.stage("Lives of the saints (orthocal)")
        dates = [dt.date(S.REF_YEAR, 1, 1) + dt.timedelta(days=i) for i in range(366)]
        jobs = [(t, d) for t in trads for d in dates]
        keys, by_first = self._indexes()
        idx = self._day_index()
        added = 0
        for i, (t, d) in enumerate(jobs):
            rep.progress(i, len(jobs), f"{d.strftime('%b %d')} {t or ''}".strip())
            try:
                day = S.orthocal_day(self.http, d.year, d.month, d.day, t)
            except NetError as e:
                rep.log(f"orthocal {d.isoformat()}: {e}")
                self._failures += 1
                continue
            for st in day.get("stories") or []:
                title, body = st.get("title") or "", st.get("story") or ""
                if not title or not body:
                    continue
                cands = idx.get((d.month, d.day), [])
                sid = self.db.src_title("orthocal-life", d.month, d.day, title)
                if sid is None:
                    sid = self._match_on_day(title, cands)
                if sid is None:
                    sid = self.upsert(d.month, d.day, title, "orthocal", keys, by_first)
                    s = self.db.get_saint(sid)
                    if s:
                        idx.setdefault((d.month, d.day), []).append(
                            {"id": sid, "key": s["key"], "name": s["name"], "core": s["core"], "kind": s["kind"],
                             "az_slug": ""})
                self.db.add_story(sid, "orthocal", title, body, commit=False)
                self.db.put_src_title("orthocal-life", d.month, d.day, title, sid)
                added += 1
                self._facts_from_text(sid, title, html_to_text(body))
            if i % 20 == 0:
                self.db.commit()
        self.db.commit()
        rep.progress(len(jobs), len(jobs), "")
        rep.log(f"Lives: {added} lives stored")

    def _facts_from_text(self, sid: int, title: str, text: str) -> None:
        s = self.db.get_saint(sid)
        if not s:
            return
        upd = {}
        if s["century"] is None and occasion_of(title) in ("", "Repose"):
            # (a relics translation's date is not the saint's own)
            c, src = H.century_from_title(title), "calendar"
            if c is None:
                c, src = H.century_from_text(text), "life"
            if c is not None:
                upd["century"], upd["century_src"] = c, src
        if s["country"] == "Unknown":
            got = H.country_from_text(text)
            if got:
                upd["country"], upd["place"], upd["country_src"] = got[0], got[1], "life"
        if upd:
            self.db.update_saint(sid, upd, commit=False)

    # ------------------------------------------------------------ azbyka
    def _prefetch_azbyka(self) -> None:
        for i in range(366):
            if self.http.stop.is_set():
                return
            d = dt.date(S.REF_YEAR, 1, 1) + dt.timedelta(days=i)
            try:
                S.azbyka_day(self.http, d.month, d.day)
            except (NetError, Cancelled):
                if self.http.stop.is_set():
                    return
            except Exception:
                pass

    def _stage_azbyka(self, rep: Report) -> None:
        rep.stage("Russian calendar (Azbuka Very)")
        dates = [dt.date(S.REF_YEAR, 1, 1) + dt.timedelta(days=i) for i in range(366)]
        keys, by_first = self._indexes()
        idx = self._day_index()
        by_slug: dict[str, int] = {}
        with self.db.lock:
            for r in self.db.con.execute("SELECT id, az_slug FROM saints WHERE az_slug!=''").fetchall():
                by_slug[r["az_slug"]] = r["id"]
        matched = added = 0
        for i, d in enumerate(dates):
            rep.progress(i, len(dates), d.strftime("%b %d"))
            try:
                data = S.azbyka_day(self.http, d.month, d.day)
            except NetError as e:
                rep.log(f"Azbuka {d.isoformat()}: {e}")
                self._failures += 1
                continue
            for e in ru.parse_widget(data.get("presentations", ""), data.get("imgs") or []):
                kind = ru.kind_of(e)
                english = ru.offline_english(e, kind)
                if not english:
                    continue
                ru_fields = {"ru_text": e["ru"], "ru_nominative": e.get("ru_nominative", ""),
                             "az_slug": e.get("slug", ""), "ru_en": english}
                occ = occasion_of(e["ru"])
                # filed on an earlier build, or known by its Azbuka page (another feast date)?
                sid = self.db.src_title("azbyka", d.month, d.day, e["ru"])
                if sid is None and e.get("slug"):
                    sid = by_slug.get(e["slug"])
                if sid is None and kind in ("saint", "group"):
                    cands = [c for c in idx.get((d.month, d.day), []) if c["kind"] == kind]
                    sid = self._match_on_day(english, cands)
                if sid is not None:
                    s = self.db.get_saint(sid) or {}
                    upd = {k: v for k, v in ru_fields.items() if v and not s.get(k)}
                    if s.get("ru_en") and s["ru_en"] != english and not s.get("ru_mt"):
                        upd["ru_en"] = english          # the glossary improves from version to version
                        if s.get("sources") == "|azbyka|" and s.get("name") == s["ru_en"]:
                            upd["name"], upd["core"] = english, H.core_name(english)   # named by the glossary
                    if s.get("century") is None and e["century"] is not None:
                        upd["century"], upd["century_src"] = e["century"], "azbyka"
                    if s.get("year_hint") is None and e.get("year") and kind == "saint" and not occ:
                        upd["year_hint"] = e["year"]
                    if "|azbyka|" not in s.get("sources", "|"):
                        upd["sources"] = s.get("sources", "|") + "azbyka|"
                    self.db.update_saint(sid, upd, commit=False)
                    self.db.add_feast(sid, d.month, d.day, occ, "azbyka", commit=False)
                    matched += 1
                else:
                    cnt = H.country_from_name(english)
                    gender = ru.gender_of(e, kind)
                    title = ru.title_of(e["ru"])[0]
                    key = ("az:" + e["slug"]) if e.get("slug") else ("az:" + (H.dedupe_key(english) or english.lower()))
                    if key in keys:
                        sid = keys[key]
                    else:
                        fields = {
                            "key": key, "name": english, "core": H.core_name(english), "kind": kind,
                            "gender": gender, "gender_src": "russian title",
                            "century": e["century"], "century_src": "azbyka" if e["century"] is not None else "",
                            "year_hint": e.get("year") if kind == "saint" and not occ else None,
                            "country": cnt[0] if cnt else "Unknown", "country_src": "name" if cnt else "",
                            "place": cnt[1] if cnt else "",
                            "categories": cats_to_str(H.categories_for(f"{title} {english}", kind)),
                            "sources": "|azbyka|", **ru_fields,
                        }
                        sid = self.db.insert_saint(fields)
                        keys[key] = sid
                        added += 1
                    self.db.add_feast(sid, d.month, d.day, occ, "azbyka", commit=False)
                    idx.setdefault((d.month, d.day), []).append(
                        {"id": sid, "key": key, "name": english, "core": H.core_name(english), "kind": kind,
                         "az_slug": e.get("slug", "")})
                if e.get("slug"):
                    by_slug[e["slug"]] = sid
                self.db.put_src_title("azbyka", d.month, d.day, e["ru"], sid)
            if i % 10 == 0:
                self.db.commit()
        self.db.commit()
        rep.progress(len(dates), len(dates), "")
        rep.log(f"Azbuka Very: {matched} matched to known saints, {added} new saints added")

    # ------------------------------------------------------------ wikipedia calendar
    def _stage_wikical(self, rep: Report) -> None:
        rep.stage("Orthodox calendar on Wikipedia")
        try:
            pages = S.wiki_liturgics(self.http, lambda d, t: rep.progress(d, t, "day pages"))
        except NetError as e:
            rep.log(f"Wikipedia calendar pages: {e}")
            self._failures += 1
            return
        entries = [(m, d, e) for (m, d), w in sorted(pages.items()) for e in W.parse_page(w)]
        qids: dict[str, str] = {}
        links = [e.link for _, _, e in entries if e.link]
        if links and self.cfg["use_wikimedia"]:
            try:
                qids = S.enwiki_qids(self.http, links, lambda d, t: rep.progress(d, t, "article links"))
            except NetError as e:
                rep.log(f"Could not resolve all Wikipedia links: {e}")
        keys, by_first = self._indexes()
        idx = self._day_index()
        by_qid: dict[str, int] = {}
        by_link: dict[str, int] = {}
        with self.db.lock:
            for r in self.db.con.execute("SELECT id, qid, qid_hint, sitelinks FROM saints").fetchall():
                for q in (r["qid"], r["qid_hint"]):
                    if q:
                        by_qid.setdefault(q, r["id"])
                en = (loads(r["sitelinks"] or "{}", {}) or {}).get("enwiki")
                if en:
                    by_link.setdefault(_norm_title(en), r["id"])
        matched = added = 0
        for i, (m, d, e) in enumerate(entries):
            if i % 100 == 0:
                if self.http.stop.is_set():
                    raise Cancelled()
                rep.progress(i, len(entries), f"{W.MONTHS[m - 1][:3]} {d}")
            title = e.title
            kind = H.classify_kind(title)
            occ = occasion_of(title)
            qid = qids.get(e.link, "") if e.link else ""
            sid = self.db.src_title("wikical", m, d, e.text)
            if sid is None:
                linked = (by_qid.get(qid) if qid else None) or (by_link.get(_norm_title(e.link)) if e.link else None)
                if linked and not self._same_first_name(title, linked):
                    linked = None                  # an article about several saints (e.g. Cyril and Methodius)
                same_day = None
                if kind in ("saint", "group"):
                    cands = [c for c in idx.get((m, d), []) if c["kind"] == kind]
                    same_day = self._match_on_day(title, cands)
                # the name on this day wins over a link; true duplicates are joined later by Wikidata id
                sid = same_day or linked
            if sid is None and kind in ("saint", "group") and occ:
                key = H.dedupe_key(title)           # relics/repose of a saint kept on another day
                if len(key.split()) >= 2:
                    sid = self._find_same_person(key, kind, keys, by_first)
            if sid is None and kind not in ("saint", "group"):
                want = f"{kind}:{H.dedupe_key(title)}"
                names = {H.display_name(title)}
                for c in idx.get((m, d), []):
                    if c["kind"] == kind and (c["key"].split("#")[0] == want or c["name"] in names):
                        sid = c["id"]
                        break
            if sid is None:
                sid = self._insert_wikical(m, d, e, kind, occ, qid, keys)
                added += 1
                s = self.db.get_saint(sid) or {}
                idx.setdefault((m, d), []).append({"id": sid, "key": s.get("key", ""), "name": s.get("name", ""),
                                                   "core": s.get("core", ""), "kind": kind, "az_slug": ""})
            else:
                self._merge_wikical(sid, e, kind, qid)
                matched += 1
            if qid:
                by_qid.setdefault(qid, sid)
            if e.link:
                by_link.setdefault(_norm_title(e.link), sid)
            self.db.add_feast(sid, m, d, occ, "wikical", commit=False)
            self.db.add_story(sid, "wikical", f"{m:02d}-{d:02d} {e.text[:160]}", self._wikical_html(m, d, e),
                              commit=False)
            self.db.put_src_title("wikical", m, d, e.text, sid)
            self._facts_from_text(sid, title, " ".join([e.text, *e.notes]))
            if i % 300 == 0:
                self.db.commit()
        self.db.commit()
        rep.progress(len(entries), len(entries), "")
        rep.log(f"Wikipedia calendar: {len(entries):,} commemorations \u2014 {matched:,} matched to known "
                f"entries, {added:,} new")

    def _same_first_name(self, title: str, sid: int) -> bool:
        s = self.db.get_saint(sid)
        if not s:
            return False
        a = _name_parts(title)[0]
        b = _name_parts(s["core"] or s["name"])[0]
        return bool(a and b and _names_similar(a, b))

    def _insert_wikical(self, m: int, d: int, e, kind: str, occ: str, qid: str, keys: dict) -> int:
        title = e.title
        name = H.display_name(title)
        key0 = H.dedupe_key(title) or name.lower()
        if kind in ("feast", "icon", "memorial"):
            key0 = f"{kind}:{key0}"
        key = f"wc:{key0}"
        if key in keys or len(key0.split()) < 2:     # a bare single name: keep namesakes apart
            key = f"{key}#{m}-{d}"
        while key in keys or self.db.saint_by_key(key):
            key += "+"
        everything = " ".join([e.text, *e.notes])
        cnt = H.country_from_name(e.text)
        cent = H.century_from_title(title) if occ in ("", "Repose") else None
        gender = H.gender_guess(title, kind)
        if kind == "saint" and gender == "Male":
            gender = _pronoun_gender(everything, gender)
        cats = H.categories_for(f"{title} {e.text}", kind)
        sec = W.CATEGORY_FOR_SECTION.get(e.section)
        if sec and kind in ("saint", "group"):
            cats.append(sec)
        fields = {
            "key": key, "name": name, "core": H.core_name(title), "kind": kind,
            "gender": gender, "gender_src": "name",
            "century": cent, "century_src": "calendar" if cent is not None else "",
            "year_hint": None if occ and occ != "Repose" else H.year_from_title(title),
            "country": cnt[0] if cnt else "Unknown", "country_src": "calendar" if cnt else "",
            "place": cnt[1] if cnt else "",
            "categories": cats_to_str(cats), "sources": "|wikical|",
            "sitelinks": self._wc_links(e),
            "qid_hint": qid,
        }
        sid = self.db.insert_saint(fields)
        keys[key] = sid
        return sid

    def _merge_wikical(self, sid: int, e, kind: str, qid: str) -> None:
        s = self.db.get_saint(sid)
        if not s:
            return
        upd: dict = {}
        if "|wikical|" not in s["sources"]:
            upd["sources"] = s["sources"] + "wikical|"
        if (e.link or e.foreign) and s["sitelinks"] in ("", "{}"):
            upd["sitelinks"] = self._wc_links(e)
        if qid and not s["qid"] and not s["qid_hint"]:
            upd["qid_hint"] = qid
            if s["enrich_state"] == 2:      # not found by name before: try again with the link
                upd["enrich_state"] = 0
        sec = W.CATEGORY_FOR_SECTION.get(e.section)
        if sec and kind in ("saint", "group"):
            cats = str_to_cats(s["categories"])
            if sec not in cats:
                upd["categories"] = cats_to_str(cats + [sec])
        if kind == "saint" and s["gender"] == "Male" and s["gender_src"] != "wikidata":
            g = _pronoun_gender(" ".join([e.text, *e.notes]), "Male")
            if g == "Female":
                upd["gender"], upd["gender_src"] = g, "calendar note"
        if upd:
            self.db.update_saint(sid, upd, commit=False)

    @staticmethod
    def _wc_links(e) -> str:
        if e.link:
            return dumps({"enwiki": e.link})
        if e.foreign:
            return dumps({f"{e.foreign[0]}wiki": e.foreign[1]})
        return "{}"

    @staticmethod
    def _wikical_html(m: int, d: int, e) -> str:
        import html as _h
        parts = [f"<p><b>{W.MONTHS[m - 1]} {d}.</b> {_h.escape(e.text)}</p>"]
        parts += [f"<p>{_h.escape(n)}</p>" for n in e.notes if n]
        return "".join(parts)

    def polish_names(self, rep: Report) -> int:
        """Background step: machine-translate the Russian titles of entries that
        only Azbuka Very knows and Wikidata could not name in English."""
        if not (self.cfg["use_azbyka"] and self.tr.available()):
            return 0
        with self.db.lock:
            rows = [dict(r) for r in self.db.con.execute(
                "SELECT id, name, ru_text, sources, kind FROM saints WHERE ru_text!='' AND ru_mt=0 "
                "AND sources='|azbyka|' AND enrich_state=2 AND kind IN ('saint','group')").fetchall()]
        if not rows:
            return 0
        rep.stage(f"Translating Russian names ({self.tr.backend})")
        done = 0
        for i, r in enumerate(rows):
            rep.progress(i, len(rows), "")
            try:
                out = self.tr.translate(r["ru_text"], "ru", "en")
            except TranslationError as e:
                rep.log(f"Translation stopped: {e}. Remaining names keep the built-in English rendering.")
                break
            if self.http.stop.is_set():
                raise Cancelled()
            if not out or has_cyrillic(out):
                self.db.update_saint(r["id"], {"ru_mt": 2}, commit=False)
                continue
            clean = re.sub(r"\s*\([^)]*\d[^)]*\)\s*$", "", out).strip()
            clean = re.sub(r"\b(st|pr|prp|sv|sschmch|mch|ven)\.\s",
                           lambda m: {"st": "St ", "ven": "Venerable "}.get(m.group(1).lower(), ""), clean, flags=re.I)
            clean = clean[:1].upper() + clean[1:]
            upd = {"ru_en": clean, "ru_mt": 1, "name": clean, "core": H.core_name(clean)}
            self.db.update_saint(r["id"], upd, commit=False)
            done += 1
            if i % 25 == 0:
                self.db.commit()
        self.db.commit()
        rep.progress(len(rows), len(rows), "")
        rep.log(f"Translated {done} Russian names")
        return done

    # ============================================================ enrich
    def enrich(self, rep: Report, limit: int | None = None, priority: list[int] | None = None) -> int:
        """Match pending saints to Wikidata. Returns how many were processed."""
        if not self.cfg["use_wikimedia"]:
            return 0
        if not self.lock.acquire(blocking=False):
            return 0
        try:
            self.http.stop.clear()
            st = self.db.stats()
            total = st["enrichable"]
            processed = 0
            rep.stage("Matching saints to Wikidata")
            if not self.db.meta("text_search_retry"):
                # saints not found by name before 1.3 get one Wikipedia text search
                self.db.retry_unmatched_with_text_search()
                self.db.set_meta("text_search_retry", 1)
            if priority:
                todo = [s for s in (self.db.get_saint(i) for i in priority) if s and s["enrich_state"] in (0, 4)
                        and s["kind"] in ("saint", "group")]
                if todo:
                    self._enrich_batch(todo, rep)
                    processed += len(todo)
            while True:
                if self.http.stop.is_set():
                    raise Cancelled()
                batch = self.db.pending_enrichment(20)
                if not batch:
                    break
                self._enrich_batch(batch, rep)
                processed += len(batch)
                st = self.db.stats()
                rep.progress(st["enriched"], total, f"{st['matched']} matched")
                if limit and processed >= limit:
                    break
            if not limit:
                self.polish_names(rep)
            return processed
        finally:
            self.lock.release()

    def enrich_one(self, sid: int, rep: Report | None = None) -> None:
        s = self.db.get_saint(sid)
        if not s or s["enrich_state"] not in (0, 4) or not self.cfg["use_wikimedia"]:
            return
        self._enrich_batch([s], rep or Report())

    def _queries(self, s: dict) -> list[str]:
        qs: list[str] = []
        core = re.sub(r"\([^)]*\)", " ", H.RELATION_TAIL.sub("", s["core"] or s["name"])).strip(" ,")
        if s.get("ru_nominative") and "|orthocal|" not in s["sources"]:
            qs.append(re.sub(r"\([^)]*\)", " ", s["ru_nominative"]).strip())
        if core:
            qs.append(core)
        head = H._name_head(core)
        if head and head != core and s["kind"] != "group":
            place = H.country_from_name(s["name"])
            qs.append(f"{head} {place[1]}" if place else head)
        if s.get("ru_en") and "|orthocal|" not in s["sources"]:
            qs.append(H.core_name(s["ru_en"]))
        return list(dict.fromkeys(q for q in qs if q and len(q) > 2))

    _SAINTLY = re.compile(r"saint|martyr|monk|\bnun\b|bishop|hermit|abbot|abbess|ascetic|priest|venerable|"
                          r"confessor|hierarch|patriarch|святой|святая|мученик|мученица|преподоб|священ|"
                          r"епископ|монах|монахиня|исповедни|праведн", re.I)

    def _choose(self, s: dict, ents: list[dict], strict: bool = False) -> dict | None:
        """The candidate that is this saint, or None. `strict` is for candidates
        found by a full-text search, which can be anyone mentioning the name."""
        core = s["core"] or s["name"]
        want = _tokset(core) | _tokset(s.get("ru_en") or "")
        f_en = _first_tok(core)
        f_ru = fold(s["ru_nominative"].split()[0])[:4] if s.get("ru_nominative") else ""
        best, best_score = None, -1.0
        for rank, ent in enumerate(ents):
            names = [S.label(ent, "en"), S.label(ent, "ru"), *S.aliases(ent, "en"), *S.aliases(ent, "ru")]
            blob = " ".join(n for n in names if n)
            toks_lat = {_letters(fold(t))[:4] for t in re.findall(r"[A-Za-z]+", blob)}
            toks_cyr = {fold(t)[:4] for t in re.findall(r"[Ѐ-ӿ]+", blob)}
            if not ((f_en and f_en in toks_lat) or (f_ru and f_ru in toks_cyr)):
                continue
            have = _tokset(blob + " " + S.description(ent, "en"))
            score = len(want & have) - rank * 0.25
            died = S.claim_time(ent, "P570") or S.claim_time(ent, "P569")
            year_close = False
            if s.get("year_hint") and died and died[1] >= 9:
                gap = abs(died[0] - s["year_hint"])
                if gap > 12:
                    continue                    # a different saint of the same name
                if gap <= 3:
                    score += 2
                    year_close = True
            elif died and s.get("century") is not None and s.get("century_src") in ("calendar", "azbyka"):
                if abs(H.year_to_century(died[0]) - s["century"]) >= 2:
                    continue
            if strict:
                desc = f"{S.description(ent, 'en')} {S.description(ent, 'ru')}"
                if not (S.claim_ids(ent, "P411") or self._SAINTLY.search(desc)):
                    continue                    # an article that only mentions the saint
                ru_want = {fold(t)[:5] for t in re.findall(r"[Ѐ-ӿ]{3,}", s.get("ru_nominative") or "")}
                ru_have = {fold(t)[:5] for t in re.findall(r"[Ѐ-ӿ]{3,}", f"{blob} {S.description(ent, 'ru')}")}
                if len(want & have) + len(ru_want & ru_have) < 2 and not year_close:
                    continue                    # one shared name is not enough
                mine, theirs = roles(s["name"]), roles(f"{blob} {desc}")
                if mine and theirs and not (mine & theirs):
                    continue                    # a monk is not the martyr of the same name
            is_group = "Q16334295" in S.claim_ids(ent, "P31")
            if s["kind"] == "group":
                if not is_group and len(want & have) < 2:
                    continue
            elif is_group:
                score -= 2
            if score > best_score:
                best, best_score = ent, score
        return best

    def _label_for(self, qids: list[str]) -> dict[str, str]:
        need = [q for q in dict.fromkeys(qids) if q and q not in self._labels]
        if need:
            ents = S.wd_entities(self.http, need, props="labels", languages="en")
            for q in need:
                self._labels[q] = S.label(ents.get(q, {}), "en") or ""
        return {q: self._labels.get(q, "") for q in qids}

    _OCC_CATS = [
        (r"bishop|archbishop|patriarch|metropolitan|pope|catholicos|hierarch", "Hierarch"),
        (r"\bmonk|\bnun\b|hermit|abbot|abbess|hegumen|ascetic|anchorite|hieromonk|archimandrite|stylite", "Monastic"),
        (r"theologian|hymnographer|hymnwriter|poet|writer|philosopher", "Theologian & Hymnographer"),
        (r"soldier|military|warrior|general", "Soldier"),
        (r"monarch|\bking\b|queen|prince|princess|emperor|empress|tsar|grand duke|ruler", "Royal"),
        (r"physician|healer", "Unmercenary Healer"),
        (r"prophet", "Prophet"),
        (r"apostle|evangelist", "Apostle"),
        (r"missionary", "Equal-to-the-Apostles"),
    ]

    def _search_ids(self, s: dict, rep: Report) -> list[str] | None:
        """Wikidata candidates for a saint by name; None if the search failed."""
        if self.http.stop.is_set():
            raise Cancelled()
        try:
            for q in self._queries(s):
                ids = S.wd_search(self.http, q)
                if ids:
                    return ids
            return []
        except NetError as e:
            rep.log(f"Wikidata search failed for {s['name'][:40]}: {e}")
            self.db.update_saint(s["id"], {"enrich_state": 3}, commit=False)
            return None

    def _text_search(self, s: dict, rep: Report) -> dict | None:
        """Last resort when Wikidata's name search found no match: Wikipedia's
        full-text search, in Russian for names from the Russian calendar."""
        if s["kind"] not in ("saint", "group"):
            return None
        tried: set[tuple[str, str]] = set()
        for q in self._queries(s):
            lang = "ru" if has_cyrillic(q) else "en"
            if (lang, q.lower()) in tried:
                continue
            if len(tried) >= 2:
                break
            tried.add((lang, q.lower()))
            if self.http.stop.is_set():
                raise Cancelled()
            try:
                ids = S.wiki_search_qids(self.http, lang, q)
                ents = S.wd_entities(self.http, ids) if ids else {}
            except NetError as e:
                rep.log(f"Wikipedia search failed for {s['name'][:40]}: {e}")
                return None
            best = self._choose(s, [ents[i] for i in ids if i in ents], strict=True)
            if best:
                return best
        return None

    def _hint_ok(self, s: dict, ent: dict) -> bool:
        """Is the item a calendar entry's Wikipedia link points to really this saint?"""
        types = set(S.claim_ids(ent, "P31"))
        if not (types & {"Q5", "Q16334295", "Q14756018"} or S.claim_ids(ent, "P411")):
            return False                      # a place, a title, an event...
        died = S.claim_time(ent, "P570") or S.claim_time(ent, "P569")
        if s.get("year_hint") and died and died[1] >= 9 and abs(died[0] - s["year_hint"]) > 15:
            return False
        if s["kind"] == "saint" and "Q5" not in types:
            return False                      # e.g. an article about a pair of saints
        return True

    def _enrich_batch(self, batch: list[dict], rep: Report) -> None:
        cands: dict[int, list[str]] = {}
        unresolved: list[dict] = []
        for s in batch:
            if s.get("qid_hint"):
                cands[s["id"]] = [s["qid_hint"]]
                continue
            if s["enrich_state"] == 4:          # searched by name before: only the text search is new
                unresolved.append(s)
                continue
            ids = self._search_ids(s, rep)
            if ids is not None:
                cands[s["id"]] = ids
        try:
            all_ids = [q for ids in cands.values() for q in ids]
            ents = S.wd_entities(self.http, all_ids) if all_ids else {}
        except NetError as e:
            rep.log(f"Wikidata fetch failed: {e}")
            for sid in cands:
                self.db.update_saint(sid, {"enrich_state": 3}, commit=False)
            self.db.commit()
            return
        chosen: dict[int, dict] = {}
        retry: list[dict] = []
        for s in batch:
            if s["id"] not in cands:
                continue
            if s.get("qid_hint"):
                ent = ents.get(s["qid_hint"])
                if ent and self._hint_ok(s, ent):
                    chosen[s["id"]] = ent
                else:
                    retry.append(s)
                continue
            best = self._choose(s, [ents[q] for q in cands[s["id"]] if q in ents])
            if best:
                chosen[s["id"]] = best
            else:
                unresolved.append(s)
        for s in retry:                        # the link was no good: fall back to a name search
            self.db.update_saint(s["id"], {"qid_hint": ""}, commit=False)
            ids = self._search_ids(s, rep)
            if ids is None:
                continue
            try:
                more = S.wd_entities(self.http, ids) if ids else {}
            except NetError as e:
                rep.log(f"Wikidata fetch failed: {e}")
                self.db.update_saint(s["id"], {"enrich_state": 3}, commit=False)
                continue
            best = self._choose(s, [more[q] for q in ids if q in more])
            if best:
                chosen[s["id"]] = best
            else:
                unresolved.append(s)
        for s in unresolved:                   # Wikidata knows no such name: try Wikipedia's text search
            best = self._text_search(s, rep)
            if best:
                chosen[s["id"]] = best
            else:
                self.db.update_saint(s["id"], {"enrich_state": 2, "enriched_at": time.time()}, commit=False)
        # resolve birthplaces -> countries, citizenship and occupation labels
        place_ids = [q for e in chosen.values() for q in S.claim_ids(e, "P19")[:1]]
        try:
            places = S.wd_entities(self.http, place_ids, props="labels|claims", languages="en") if place_ids else {}
            country_ids = [q for p in places.values() for q in S.claim_ids(p, "P17")[:1]]
            extra = [q for e in chosen.values() for q in S.claim_ids(e, "P27")[:1] + S.claim_ids(e, "P106")[:4]
                     + S.claim_ids(e, "P39")[:3]]
            labels = self._label_for(country_ids + extra)
        except NetError as e:
            rep.log(f"Wikidata label lookup failed: {e}")
            places, labels = {}, {}
        for sid, ent in chosen.items():
            self._apply(sid, ent, places, labels)
        self.db.commit()

    def _apply(self, sid: int, ent: dict, places: dict, labels: dict) -> None:
        s = self.db.get_saint(sid)
        if not s:
            return
        qid = ent.get("id", "")
        other = self.db.saint_by_qid(qid, exclude=sid) if s["kind"] != "group" else None
        if other:
            keep, drop = (other["id"], sid) if ("|orthocal|" in other["sources"] or other["id"] < sid) else (sid, other["id"])
            self.db.merge_into(keep, drop)
            s = self.db.get_saint(keep)
            sid = keep
            if not s:
                return
        upd: dict = {"qid": qid, "enrich_state": 1, "enriched_at": time.time()}
        en_label = S.label(ent, "en")
        if en_label and not has_cyrillic(en_label):
            upd["wikilabel"] = en_label
        desc = S.description(ent, "en")
        if desc and not has_cyrillic(desc):
            upd["description"] = desc[:300]
        al = [a for a in S.aliases(ent, "en") if not has_cyrillic(a)][:8]
        if al:
            upd["aliases"] = " | ".join(al)
        if s["kind"] != "group":
            g = next((S.GENDERS[q] for q in S.claim_ids(ent, "P21") if q in S.GENDERS), None)
            if g:
                upd["gender"], upd["gender_src"] = g, "wikidata"
        born, died = S.claim_time(ent, "P569"), S.claim_time(ent, "P570")
        if born:
            upd["born"] = born[2]
        if died:
            upd["died"] = died[2]
        ref = died or born
        if ref and s["kind"] != "group":
            upd["century"], upd["century_src"] = H.year_to_century(ref[0]), "wikidata"
        pl = S.claim_ids(ent, "P19")[:1]
        country = None
        if pl and pl[0] in places:
            p = places[pl[0]]
            plabel = S.label(p, "en")
            cq = S.claim_ids(p, "P17")[:1]
            country = H.normalize_country(labels.get(cq[0], "")) if cq else None
            if plabel:
                upd["place"] = plabel
            if country:
                upd["country"], upd["country_src"] = country, "wikidata: birthplace"
        if not country:
            cz = S.claim_ids(ent, "P27")[:1]
            c2 = H.normalize_country(labels.get(cz[0], "")) if cz else None
            if c2 and s["country"] == "Unknown":
                upd["country"], upd["country_src"] = c2, "wikidata: citizenship"
        occ = " ".join(labels.get(q, "") for q in S.claim_ids(ent, "P106")[:4] + S.claim_ids(ent, "P39")[:3])
        occ += " " + (desc or "")
        cats = str_to_cats(s["categories"])
        for rx, cat in self._OCC_CATS:
            if re.search(rx, occ, re.I) and cat not in cats:
                cats.append(cat)
        upd["categories"] = cats_to_str(cats)
        img = S.claim_string(ent, "P18")
        if img:
            upd["image"] = img
        upd["sitelinks"] = dumps(S.sitelinks(ent))
        # Russian-only entries: replace the rough rendering with Wikidata's English name
        if s["sources"] == "|azbyka|" and en_label and not has_cyrillic(en_label) and not s["ru_mt"]:
            title = ru.title_of(s["ru_text"])[0]
            if s["kind"] != "group":
                upd["name"] = f"{title} {en_label}".strip()
                upd["core"] = en_label
        self.db.update_saint(sid, upd, commit=False)


def church_date_today(calendar: str) -> tuple[int, int]:
    today = dt.date.today()
    if calendar == "old":
        return S.civil_to_church(today)
    return today.month, today.day
