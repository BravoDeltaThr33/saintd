"""Composes the Focus-tab article ("history lesson") for one saint from
every source available, and finds the saint's icon."""

from __future__ import annotations

import html as _html
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Callable
from urllib.parse import quote

from . import heuristics as H
from . import htc, icons, owiki
from . import lives as L
from . import sources as S
from .db import DB, LIFE_SOURCES, loads, str_to_cats
from .net import Cancelled, Http, NetError
from .text import has_cyrillic, html_to_markdown, md_escape, strip_foreign_script
from .translate import TranslationError, Translator

MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September",
          "October", "November", "December"]

SKIP_SECTIONS = {
    "references", "external links", "see also", "notes", "further reading", "bibliography", "sources",
    "citations", "literature", "gallery", "footnotes", "works cited", "explanatory notes", "general sources",
    "notes and references", "references and notes", "primary sources", "secondary sources", "links",
    "примечания", "литература", "ссылки", "см. также", "источники", "библиография", "галерея",
    "σημειώσεις", "παραπομπές", "βιβλιογραφία", "εξωτερικοί σύνδεσμοι", "напомене", "литература",
    "спољашње везе", "референце", "извори",
}
OTHER_WIKIS = ["ruwiki", "elwiki", "srwiki", "ukwiki", "bgwiki", "rowiki", "kawiki", "frwiki", "dewiki", "itwiki"]
DAY = 86400

LIFE_HEADINGS = {
    "orthocal": "From the Synaxarion",
    "htc": "From the Holy Trinity Calendar",
    "mystagogy": "From the Mystagogy Resource Center",
    "azbyka-life": "From the Russian Lives of the Saints",
}


def date_label(month: int, day: int) -> str:
    return f"{MONTHS[month - 1]} {day}"


def old_calendar_civil(month: int, day: int) -> str:
    d = S.church_to_civil(month, day)
    return f"{MONTHS[d.month - 1]} {d.day}"


def wiki_to_markdown(text: str, base_level: int = 3) -> str:
    """Convert a plain-text extract with '== Heading ==' lines to Markdown,
    dropping reference/link sections."""
    out: list[str] = []
    skipping = False
    skip_level = 99
    for line in text.splitlines():
        m = re.match(r"^(={2,6})\s*(.*?)\s*\1\s*$", line)
        if m:
            level = len(m.group(1))
            title = m.group(2).strip()
            if skipping and level > skip_level:
                continue
            skipping = title.lower() in SKIP_SECTIONS
            skip_level = level if skipping else 99
            if not skipping:
                out.append("")
                out.append("#" * min(6, base_level + level - 2) + " " + title)
                out.append("")
            continue
        if skipping:
            continue
        out.append(line.rstrip())
    md = "\n".join(out)
    md = re.sub(r"\n{3,}", "\n\n", md).strip()
    # drop headings left without content
    md = re.sub(r"(^|\n)(#{2,6} [^\n]+)\n+(?=#{2,6} |\Z)", lambda m: m.group(1), md)
    return md.strip()


def hymn_lines(text: str) -> str:
    """A hymn with its phrase marks (/ and //) as line breaks."""
    parts = [p.strip() for p in re.split(r"\s*/{1,2}\s*", text) if p.strip()]
    return "\\\n".join(md_line(p) for p in parts)


def md_line(text: str) -> str:
    """Text that must not be read as Markdown list/heading syntax."""
    return re.sub(r"^([#>*+-]|\d+[.)])(\s)", r"\\\1\2", text)



def lived_line(s: dict) -> str:
    """When the saint lived: birth and death as known, and the century unless the
    dates already say it (Wikidata gives some dates only as a century: "7th century"
    must not be followed by "· 7th century")."""
    born, died = (s.get("born") or "").strip(), (s.get("died") or "").strip()
    if born and died:
        lived = born if born == died else f"{born} – {died}"
    elif died or born:
        word, date = ("died", died) if died else ("born", born)
        in_the = "in the " if date.endswith(("century", "century BC")) and not date.startswith("c.") else ""
        lived = f"{word} {in_the}{date}"
    else:
        lived = ""
    cent = H.century_label(s["century"]) if s.get("century") is not None else ""
    if cent and cent.lower() in lived.lower():
        cent = ""
    return " · ".join(x for x in (lived, cent) if x)

class ArticleBuilder:
    # characters of Russian text translated per saint, by translator (MyMemory's free
    # quota is small; local or self-hosted translators can take whole lives)
    LIFE_LIMITS = {"mymemory": 2500, "lingva": 9000}

    def __init__(self, cfg, db: DB, http: Http, translator: Translator, syncer) -> None:
        self.cfg = cfg
        self.db = db
        self.http = http
        self.tr = translator
        self.syncer = syncer

    # ------------------------------------------------------------ the whole article
    def build(self, sid: int, refresh: bool = False, status: Callable[[str], None] = lambda m: None,
              partial: Callable[[str], None] | None = None, title: bool = True) -> str:
        """Gather everything about a saint from the internet (each source once,
        then from the local copy) and return the article. `partial` receives
        the article again each time another source has answered."""
        s = self.db.get_saint(sid)
        if not s:
            return "# Not found\n\nThis entry is no longer in the directory."
        if s["enrich_state"] in (0, 3, 4) and self.cfg["use_wikimedia"]:
            status("Looking the saint up on Wikidata…")
            try:
                if s["enrich_state"] == 3:
                    self.db.update_saint(sid, {"enrich_state": 0})
                self.syncer.enrich_one(sid)
            except (NetError, Cancelled):
                pass
            s = self.db.get_saint(sid)
            if not s:
                # merged into another entry
                return "# Updated\n\nThis entry was merged with another record; search for it again."
            if partial:
                partial(self.compose(s, self.db.article(sid), title=title))
        if refresh:
            self.db.forget_lookups(sid)
        tasks = [self._wiki, self._mystagogy, self._htc, self._orthodoxwiki, self._azbyka]
        with ThreadPoolExecutor(max_workers=4, thread_name_prefix="saintd-source") as pool:
            futures = [pool.submit(self._guarded, t, s, refresh, status) for t in tasks]
            for f in as_completed(futures):
                if f.result() and partial:
                    cur = self.db.get_saint(sid)
                    if cur:
                        partial(self.compose(cur, self.db.article(sid), title=title))
        s = self.db.get_saint(sid) or s
        return self.compose(s, self.db.article(sid), title=title)

    @staticmethod
    def _guarded(task, s, refresh, status) -> bool:
        """Run one source; never let it break the article. True if it added something."""
        try:
            return bool(task(s, refresh, status))
        except Cancelled:
            return False
        except NetError as e:
            status(str(e))
            return False
        except Exception as e:             # a changed web page must not crash the app
            status(f"A source could not be read ({e.__class__.__name__})")
            return False

    # ------------------------------------------------------------ wikipedia
    def _wiki(self, s: dict, refresh: bool, status: Callable[[str], None]) -> bool:
        cached = self.db.article(s["id"])
        max_age = float(self.cfg["article_max_age_days"]) * DAY
        if cached and not refresh and time.time() - cached["fetched_at"] < max_age:
            return False
        links = loads(s.get("sitelinks") or "{}", {}) or {}
        if not self.cfg["use_wikimedia"]:
            return False
        try:
            if links.get("enwiki"):
                status("Reading the English Wikipedia article…")
                got = S.wiki_extract(self.http, "en", links["enwiki"])
                if got:
                    self.db.put_article(s["id"], "en", got[0], got[1])
                    return True
            if self.cfg["translate_articles"] and self.tr.available():
                for site in OTHER_WIKIS:
                    if not links.get(site):
                        continue
                    lang = site[:-4]
                    status(f"Reading the {lang.upper()} Wikipedia article…")
                    got = S.wiki_extract(self.http, lang, links[site])
                    if not got:
                        continue
                    md = wiki_to_markdown(got[1])
                    status(f"Translating from {lang.upper()} with {self.tr.backend}…")
                    try:
                        en = self.tr.translate_long(md, lang, "en",
                                                    lambda i, n: status(f"Translating… {i}/{n}"))
                    except TranslationError as e:
                        status(f"Translation failed: {e}")
                        en = None
                    if en:
                        self.db.put_article(s["id"], lang, got[0], en, self.tr.backend)
                        return True
                    break
        except NetError as e:
            status(f"Could not reach Wikipedia: {e}")
        return False

    # ------------------------------------------------------------ more lives
    def _names(self, s: dict) -> list[str]:
        names = [s["name"]]
        for alt in (s.get("wikilabel"), s.get("ru_en")):
            if alt and alt not in names and not has_cyrillic(alt):
                names.append(alt)
        return names

    def _feast_days(self, s: dict) -> list[tuple[int, int]]:
        fs = self.db.feasts(s["id"])
        main = [f for f in fs if not f["label"]] + [f for f in fs if f["label"]]
        return list(dict.fromkeys((f["month"], f["day"]) for f in main))

    def _has(self, s: dict, source: str) -> bool:
        return any(st["source"] == source for st in self.db.stories(s["id"]))

    def _mystagogy(self, s: dict, refresh: bool, status: Callable[[str], None]) -> bool:
        if not self.cfg["use_mystagogy"] or s["kind"] not in ("saint", "group"):
            return False
        if self._has(s, "orthocal") or (not refresh and (self._has(s, "mystagogy")
                                                         or self.db.looked(s["id"], "mystagogy"))):
            return False
        ttl = None if refresh else 30 * DAY
        status("Searching the Mystagogy Resource Center…")
        added = False
        posts = L.mystagogy_find(self.http, self._names(s)[:2], sorted(set(self._feast_days(s))), ttl=ttl)
        if posts:
            body = L.mystagogy_post(self.http, posts[0]["url"], ttl=ttl)
            if len(L.html_to_markdown(body)) > 120:
                self.db.drop_stories(s["id"], "mystagogy")
                self.db.drop_stories(s["id"], "mystagogy-more")
                self.db.add_story(s["id"], "mystagogy", posts[0]["title"], body, url=posts[0]["url"])
                for more in posts[1:4]:
                    self.db.add_story(s["id"], "mystagogy-more", more["title"], "", url=more["url"])
                added = True
        self.db.mark_looked(s["id"], "mystagogy")
        return added

    def _azbyka(self, s: dict, refresh: bool, status: Callable[[str], None]) -> bool:
        if not (self.cfg["use_azbyka_lives"] and s.get("az_slug") and self.tr.available()):
            return False
        if self._has(s, "orthocal") or (not refresh and self._has(s, "azbyka-life")):
            return False
        ttl = None if refresh else 30 * DAY
        status("Reading the Russian life on Azbuka Very…")
        got = L.azbyka_life(L.azbyka_page(self.http, s["az_slug"], ttl=ttl))
        if not got:
            return False
        summary, life = got
        limit = self.LIFE_LIMITS.get(self.tr.backend, 30000)
        paras, cut = L.cap_paragraphs(([summary] if summary else []) + life, limit)
        status(f"Translating the life with {self.tr.backend}…")
        try:
            en = self.tr.translate_long("\n\n".join(paras), "ru", "en",
                                        lambda i, n: status(f"Translating the life… {i}/{n}"))
        except TranslationError as e:
            status(f"Translation failed: {e}")
            en = None
        if not en:
            return False
        body = "".join(f"<p>{_html.escape(p)}</p>" for p in en.split("\n\n") if p.strip())
        self.db.drop_stories(s["id"], "azbyka-life")
        self.db.add_story(s["id"], "azbyka-life", f"{self.tr.backend}{' (shortened)' if cut else ''}",
                          body, url=L.AZBYKA_DAYS + s["az_slug"])
        return True

    def _htc(self, s: dict, refresh: bool, status: Callable[[str], None]) -> bool:
        """Hymns (and, when the OCA has none, the life) from the Holy Trinity calendar."""
        if not self.cfg["use_htc"] or s["kind"] not in ("saint", "group"):
            return False
        if not refresh and self.db.looked(s["id"], "htc"):
            return False
        days = self._feast_days(s)[:3]
        if not days:
            return False
        ttl = None if refresh else 30 * DAY
        status("Reading the Holy Trinity calendar…")
        need_life = not self._has(s, "orthocal")
        hymns: list[tuple[htc.Hymn, int, int]] = []
        life = None
        for m, d in days:
            day = htc.fetch_day(self.http, m, d, ttl=ttl)
            for name in self._names(s):
                for h in htc.hymns_for(name, day.hymns, day.entries):
                    if all(h.text != x.text for x, _, _ in hymns):
                        hymns.append((h, m, d))
                entry = htc.match_entry(name, day.entries)
                if entry and entry.life_url and need_life and life is None:
                    got = htc.fetch_life(self.http, entry.life_url, ttl=None if refresh else 90 * DAY)
                    if got:
                        life = (got, entry.life_url)
                if entry:
                    break
        added = False
        if hymns:
            self.db.drop_stories(s["id"], "htc-hymn")
            for i, (h, m, d) in enumerate(hymns):
                self.db.add_story(s["id"], "htc-hymn", f"{i:02d}|{h.kind}|{h.tone}|{h.who}", h.text,
                                  url=f"{m:02d}-{d:02d}")
            added = True
        if life:
            (title, body, credit), url = life
            self.db.drop_stories(s["id"], "htc")
            self.db.add_story(s["id"], "htc", f"{title}|{credit}", body, url=url)
            added = True
        self.db.mark_looked(s["id"], "htc")
        return added

    def _orthodoxwiki(self, s: dict, refresh: bool, status: Callable[[str], None]) -> bool:
        if not self.cfg["use_orthodoxwiki"] or s["kind"] not in ("saint", "group"):
            return False
        if not refresh and self.db.looked(s["id"], "owiki"):
            return False
        ttl = None if refresh else 30 * DAY
        status("Looking on OrthodoxWiki…")
        added = False
        title = owiki.find_title(self.http, self._names(s), ttl=ttl)
        if title:
            got = owiki.fetch_article(self.http, title, ttl=ttl)
            if got and len(html_to_markdown(got[1])) > 200:
                t, body, img = got
                self.db.drop_stories(s["id"], "orthodoxwiki")
                self.db.drop_stories(s["id"], "orthodoxwiki-image")
                self.db.add_story(s["id"], "orthodoxwiki", t, body, url=owiki.page_url(t))
                if img:
                    self.db.add_story(s["id"], "orthodoxwiki-image", t, "", url=img)
                added = True
        self.db.mark_looked(s["id"], "owiki")
        return added

    # ------------------------------------------------------------ icons
    def icon_path(self, s: dict) -> Path | None:
        """The saint's icon if it is already downloaded."""
        if not self.cfg["show_icons"]:
            return None
        return icons.cached(s.get("icon_url"))

    def icon_candidates(self, s: dict) -> list[tuple[str, str]]:
        out: list[tuple[str, str]] = []
        if s.get("image"):
            url = icons.commons_thumb_url(s["image"])
            if url:
                out.append((url, f"Wikimedia Commons — {s['image']}"))
        stories = self.db.stories(s["id"])
        for st in stories:
            if st["source"] == "orthodoxwiki-image" and st["url"]:
                out.append((st["url"], "OrthodoxWiki"))
        if s.get("az_slug"):
            try:
                page = L.azbyka_page(self.http, s["az_slug"])
                url = icons.azbyka_icon_url(page)
                if url:
                    out.append((url, "Azbuka Very"))
            except NetError:
                pass
        for st in stories:
            if st["source"] == "mystagogy" and st["url"]:
                try:
                    url = icons.mystagogy_icon_url(self.http.get_text(st["url"], ttl=30 * DAY, timeout=30))
                    if url:
                        out.append((url, "Mystagogy Resource Center"))
                except NetError:
                    pass
        return out

    def fetch_icon(self, sid: int, refresh: bool = False, status: Callable[[str], None] = lambda m: None) -> Path | None:
        """Find and download the saint's icon (once)."""
        s = self.db.get_saint(sid)
        if not s or not self.cfg["show_icons"] or s["kind"] not in ("saint", "group", "angel"):
            return None
        have = icons.cached(s.get("icon_url"))
        if have and not refresh:
            return have
        if not refresh and self.db.looked(sid, "icon", max_age=7 * DAY):
            return have
        status("Looking for an icon…")
        found = None
        for url, credit in self.icon_candidates(s):
            p = icons.fetch(self.http, url)
            if p:
                self.db.update_saint(sid, {"icon_url": url, "icon_credit": credit})
                found = p
                break
        self.db.mark_looked(sid, "icon")
        return found or have

    # ------------------------------------------------------------ the summary card
    def summary(self, s: dict) -> dict:
        """What the Focus tab's header card shows."""
        feasts = self.db.feasts(s["id"])
        days = []
        for f in sorted(feasts, key=lambda f: (bool(f["label"]), f["month"], f["day"])):
            k = (f["month"], f["day"])
            if k not in [x[0] for x in days]:
                days.append((k, f["label"]))
        where = ""
        if s["country"] and s["country"] != "Unknown":
            where = s["country"]
            if s.get("place") and s["place"] not in where:
                where = f"{s['place']}, {where}"
        sub = s.get("description") or ""
        if s.get("wikilabel") and s["wikilabel"].lower() not in s["name"].lower():
            sub = f"{s['wikilabel']} — {sub}" if sub else s["wikilabel"]
        return {"name": s["name"], "subtitle": (sub[:1].upper() + sub[1:]) if sub else "",
                "feasts": days, "lived": lived_line(s), "where": where,
                "kinds": str_to_cats(s["categories"]), "icon_credit": s.get("icon_credit") or "",
                "linked": s["enrich_state"] == 1}

    # ------------------------------------------------------------ compose
    def compose(self, s: dict, art: dict | None, title: bool = True) -> str:
        """The whole article as one Markdown text."""
        return _join(md for _, md in self.sections(s, art, title=title))

    SIDE_SECTIONS = ("hymns", "commemorations", "also", "sources")

    def compose_parts(self, s: dict, art: dict | None, split: bool = False, glance: bool = True) -> tuple[str, str]:
        """The article for the Focus tab: (main column, side column). With
        split=False everything is in the main column. glance=False leaves out
        the At a Glance facts (the header card shows them)."""
        secs = [(k, md) for k, md in self.sections(s, art, title=False) if glance or k != "glance"]
        side = set(self.SIDE_SECTIONS) if split else set()
        return _join(md for k, md in secs if k not in side), _join(md for k, md in secs if k in side)

    def sections(self, s: dict, art: dict | None, title: bool = True) -> list[tuple[str, str]]:
        """The article in named parts: title, glance, life, hymns, calendar,
        history, about, commemorations, also, sources."""
        parts: list[tuple[str, str]] = []
        cal = self.cfg["calendar"]
        feasts = self.db.feasts(s["id"])
        all_stories = self.db.stories(s["id"])
        lives = sorted((st for st in all_stories if st["source"] in LIFE_SOURCES),
                       key=lambda st: LIFE_SOURCES.index(st["source"]))
        more_posts = [st for st in all_stories if st["source"] == "mystagogy-more"]
        cal_notes = sorted((st for st in all_stories if st["source"] == "wikical"), key=lambda st: st["title"])
        hymns = sorted((st for st in all_stories if st["source"] == "htc-hymn"), key=lambda st: st["title"])
        ow = next((st for st in all_stories if st["source"] == "orthodoxwiki"), None)
        links = loads(s.get("sitelinks") or "{}", {}) or {}
        cats = str_to_cats(s["categories"])
        out: list[str] = []
        if title:
            out.append(f"# {s['name']}")
            sub = s.get("description") or ""
            if s.get("wikilabel") and s["wikilabel"].lower() not in s["name"].lower():
                sub = f"{s['wikilabel']} — {sub}" if sub else s["wikilabel"]
            if sub:
                out.append(f"*{sub[0].upper() + sub[1:]}*")
            out.append("")

        parts.append(('title', _lines(out)))
        out = []
        # ---------------------------------------------------- at a glance
        rows: list[tuple[str, str]] = []
        if feasts:
            ordered = sorted(feasts, key=lambda f: (bool(f["label"]), f["month"], f["day"]))
            days, labels = [], []                    # in the same order as the feast days
            for f in ordered:
                k = (f["month"], f["day"])
                if k in days:
                    continue
                days.append(k)
                labels.append(date_label(*k) + (f" ({f['label'].lower()})" if f["label"] else ""))
            rows.append(("Feast days" if len(labels) > 1 else "Feast day", " · ".join(labels[:5])))
            if cal == "old":
                rows.append(("Old Calendar (civil date)", " · ".join(old_calendar_civil(*k) for k in days[:5])))
        lived = lived_line(s)
        if lived:
            rows.append(("Lived", lived))
        if s["country"] and s["country"] != "Unknown":
            where = s["country"]
            if s.get("place") and s["place"] not in where:
                where = f"{s['place']} — {where}"
            label = "Born in" if s["country_src"] == "wikidata: birthplace" else "Associated with"
            rows.append((label, where))
        if s["kind"] in ("saint", "group"):
            rows.append(("Gender", s["gender"]))
        if cats:
            rows.append(("Kind of saint", ", ".join(cats)))
        if s.get("aliases"):
            rows.append(("Also known as", s["aliases"]))
        if s.get("ru_en") and s["ru_en"] != s["name"]:
            rows.append(("In the Russian calendar", s["ru_en"]))
        if rows:
            out.append("## At a Glance")
            out.append("")
            for k, v in rows:
                out.append(f"- **{k}:** {md_escape(v)}")
            out.append("")

        parts.append(('glance', _lines(out)))
        out = []
        # ---------------------------------------------------- the life
        if lives:
            out.append("## The Life of the Saint")
            out.append("")
            several = len({st["source"] for st in lives}) > 1
            done_heading: set[str] = set()
            for st in lives:
                src = st["source"]
                if several and src not in done_heading:
                    out.append(f"### {LIFE_HEADINGS[src]}")
                    out.append("")
                if src == "orthocal":
                    if src not in done_heading:
                        out.append("*From the Synaxarion (Lives of the Saints) as published for the Orthodox Church "
                                   "in America and the Greek tradition.*")
                        out.append("")
                    oca = [x for x in lives if x["source"] == "orthocal"]
                    if len(oca) > 1 or st["title"] != s["name"]:
                        out.append(f"**{H.expand(st['title'])}**")
                        out.append("")
                    out.append(strip_foreign_script(html_to_markdown(st["html"])))
                elif src == "htc":
                    life_title, _, credit = st["title"].partition("|")
                    credit = credit or "translated by Fr. S. Janos"
                    out.append(f"*“{life_title}” from the Orthodox Calendar of Holy Trinity Russian Orthodox "
                               f"Church ({credit.strip()}) — {st['url']}*")
                    out.append("")
                    out.append(html_to_markdown(st["html"]))
                elif src == "mystagogy":
                    out.append(f"*From “{st['title']}” on the Mystagogy Resource Center "
                               f"(John Sanidopoulos) — {st['url']}*")
                    out.append("")
                    out.append(strip_foreign_script(html_to_markdown(st["html"])))
                    if more_posts:
                        out.append("")
                        out.append("**More about this saint on the Mystagogy Resource Center:**")
                        out.append("")
                        for mp in more_posts:
                            out.append(f"- {mp['title']} — {mp['url']}")
                elif src == "azbyka-life":
                    backend, _, rest = st["title"].partition(" ")
                    note = (" It has been shortened; the full life is on the page linked here." if rest else "")
                    out.append(f"*Machine-translated from the Russian life on Azbuka Very using {backend}. Names may "
                               f"differ slightly from customary English forms.{note} — {st['url']}*")
                    out.append("")
                    out.append(html_to_markdown(st["html"]))
                done_heading.add(src)
                out.append("")

        parts.append(('life', _lines(out)))
        out = []
        # ---------------------------------------------------- hymns
        if hymns:
            out.append("## Hymns")
            out.append("")
            out.append("*The troparion and kontakion sung for the saint, from the Orthodox Calendar of Holy Trinity "
                       "Russian Orthodox Church. The slashes of the original mark the musical phrases; here each "
                       "phrase has its own line.*")
            out.append("")
            for st in hymns:
                _, kind, tone, who = (st["title"].split("|") + ["", "", "", ""])[:4]
                head = kind + (f" — Tone {tone}" if tone else "")
                out.append(f"### {head}")
                out.append("")
                if who:
                    out.append(f"*{who}*")
                    out.append("")
                out.append(hymn_lines(st["html"]))
                out.append("")

        parts.append(('hymns', _lines(out)))
        out = []
        # ---------------------------------------------------- calendar notes
        if cal_notes:
            out.append("## In the Calendar")
            out.append("")
            out.append("*From the Great Synaxaristes and the Orthodox calendars, as gathered on Wikipedia's "
                       "“Eastern Orthodox liturgics” day pages.*")
            out.append("")
            for st in cal_notes:
                md = strip_foreign_script(html_to_markdown(st["html"]))
                paras = [p for p in md.split("\n\n") if p.strip()]
                if paras:
                    out.append(f"- {paras[0]}")
                    for p in paras[1:]:
                        out.append(f"  > {p}")
            out.append("")

        parts.append(('calendar', _lines(out)))
        out = []
        # ---------------------------------------------------- history
        if art and art.get("text"):
            lang = art.get("lang", "en")
            out.append("## History")
            out.append("")
            if lang != "en":
                out.append(f"*Machine-translated from the {lang.upper()} Wikipedia article "
                           f"“{art['title']}” using {art.get('translated_by') or 'a translator'}. "
                           f"Names may differ slightly from customary English forms.*")
            else:
                out.append(f"*From the Wikipedia article “{art['title']}”.*")
            out.append("")
            body = art["text"] if lang != "en" else wiki_to_markdown(art["text"])
            out.append(strip_foreign_script(body))
            out.append("")
        elif ow:
            out.append("## History")
            out.append("")
            out.append(f"*From the OrthodoxWiki article “{ow['title']}” (GFDL / CC BY-SA 2.5) — {ow['url']}*")
            out.append("")
            body = strip_foreign_script(html_to_markdown(ow["html"]))
            if hymns:                       # the hymns are already shown above
                body = drop_section(body, ("hymns", "hymnography", "troparion", "kontakion"))
            out.append(body)
            out.append("")
        elif not lives and not cal_notes and not hymns:
            out.append("## About this entry")
            out.append("")
            if s["enrich_state"] in (0, 4) and self.cfg["use_wikimedia"]:
                out.append("This saint has not been looked up online yet. Press **r** to try again.")
            elif s["enrich_state"] == 2:
                out.append("No detailed biography was found in the connected sources. Many saints of the Church "
                           "are known only by their name, rank and the day of their commemoration — "
                           "the Synaxarion often records nothing more.")
            else:
                other = [k for k in links if k != "enwiki" and k in OTHER_WIKIS]
                if other and not self.tr.available():
                    out.append("A biography exists only in another language "
                               f"({', '.join(k[:-4].upper() for k in other[:4])}). Choose a translator in "
                               "**Settings** to read it here in English.")
                else:
                    out.append("No detailed biography was found in the connected sources.")
            out.append("")

        parts.append(('history', _lines(out)))
        out = []
        # ---------------------------------------------------- feast list
        if feasts:
            out.append("## Commemorations")
            out.append("")
            seen2 = set()
            for f in feasts:
                k = (f["month"], f["day"], f["label"])
                if k in seen2:
                    continue
                seen2.add(k)
                what = f["label"] or "Commemoration"
                line = f"- **{date_label(f['month'], f['day'])}** — {what}"
                if (f["month"], f["day"]) == (2, 29):
                    line += " (kept on February 28 in non-leap years)"
                line += f" · Old Calendar churches keep it on {old_calendar_civil(f['month'], f['day'])} (civil)"
                out.append(line)
            out.append("")
            # the saints who share the main feast day
            main = next((f for f in feasts if not f["label"]), feasts[0])
            same = [x for x in self.db.saints_on(main["month"], main["day"]) if x["id"] != s["id"]][:14]
            if same:
                parts.append(("commemorations", _lines(out)))
                out = []
                out.append(f"## Also Commemorated on {date_label(main['month'], main['day'])}")
                out.append("")
                for x in same:
                    out.append(f"- [{md_link_text(x['name'])}](saint:{x['id']})")
                out.append("")

        parts.append(('also', _lines(out)))
        out = []
        # ---------------------------------------------------- sources
        out.append("## Sources")
        out.append("")
        if "|orthocal|" in s["sources"]:
            out.append("- **Orthocal** (orthocal.info) — calendar and lives of the saints")
        for st in lives:
            if st["source"] == "htc":
                out.append(f"- **Holy Trinity Russian Orthodox Church, Orthodox Calendar** — life: {st['url']}")
        if hymns and not any(st["source"] == "htc" for st in lives):
            out.append(f"- **Holy Trinity Russian Orthodox Church, Orthodox Calendar** — hymns: "
                       f"{htc.SITE}/htc/orthodox-calendar/")
        for st in lives:
            if st["source"] == "mystagogy":
                out.append(f"- **Mystagogy Resource Center** “{st['title']}” — {st['url']}")
        if s.get("az_slug"):
            what = "Russian church calendar and life" if any(st["source"] == "azbyka-life" for st in lives) \
                else "Russian church calendar"
            out.append(f"- **Azbuka Very** — {what}, translated: "
                       f"https://azbyka.ru/days/{s['az_slug']}")
        elif "|azbyka|" in s["sources"]:
            out.append("- **Azbuka Very** — Russian church calendar, translated")
        if cal_notes:
            days = sorted({(int(st["title"][:2]), int(st["title"][3:5])) for st in cal_notes
                           if st["title"][:5].replace("-", "").isdigit()})
            for m, d in days[:3]:
                page = f"{MONTHS[m - 1]}_{d}_(Eastern_Orthodox_liturgics)"
                out.append(f"- **Wikipedia Orthodox calendar** “{MONTHS[m - 1]} {d}” — text CC BY-SA 4.0 "
                           f"— https://en.wikipedia.org/wiki/{quote(page, safe='()_,')}")
        if s.get("qid"):
            out.append(f"- **Wikidata** {s['qid']} (CC0) — https://www.wikidata.org/wiki/{s['qid']}")
        if art and art.get("text"):
            lang = art.get("lang", "en")
            url = f"https://{lang}.wikipedia.org/wiki/{quote(art['title'].replace(' ', '_'))}"
            out.append(f"- **Wikipedia** “{art['title']}” — text CC BY-SA 4.0 — {url}")
        if ow:
            out.append(f"- **OrthodoxWiki** “{ow['title']}” — GFDL / CC BY-SA 2.5 — {ow['url']}")
        if s.get("icon_url"):
            out.append(f"- Icon: {s.get('icon_credit') or 'image'} — {s['icon_url']}")
        elif s.get("image"):
            out.append(f"- Icon/image on Wikimedia Commons: "
                       f"https://commons.wikimedia.org/wiki/File:{quote(s['image'].replace(' ', '_'))}")
        notes = []
        if s["gender_src"] in ("name", "russian title"):
            notes.append("gender inferred from the commemoration title")
        if s["century_src"] in ("life", "calendar", "azbyka"):
            notes.append(f"century from the {'Russian calendar' if s['century_src'] == 'azbyka' else s['century_src']}")
        if s["gender_src"] == "calendar note":
            notes.append("gender inferred from the calendar note")
        if s["country_src"] in ("name", "life", "calendar"):
            notes.append(f"country inferred from the {s['country_src']}")
        if notes:
            out.append("")
            out.append(f"*Notes: {'; '.join(notes)}.*")
        parts.append(("sources", _lines(out)))
        out = []
        keyed = []
        for k, md in parts:
            if not md.strip():
                continue
            if k == "history" and md.lstrip().startswith("## About this entry"):
                k = "about"
            keyed.append((k, md))
        return keyed



def _lines(lines: list[str]) -> str:
    """One part of the article: its lines, blank lines (paragraph breaks) kept."""
    return "\n".join(lines).strip("\n")


def _join(parts) -> str:
    """Parts of the article, a blank line between them."""
    md = "\n\n".join(x.strip("\n") for x in parts if x and x.strip())
    return (md.strip() + "\n") if md.strip() else ""


def drop_section(md: str, names: tuple[str, ...]) -> str:
    """Remove '### Name' sections (up to the next heading of the same or a higher level)."""
    out, skip_level = [], 0
    for line in md.split("\n"):
        m = re.match(r"^(#{1,6})\s+(.*)$", line)
        if m:
            level = len(m.group(1))
            if skip_level and level <= skip_level:
                skip_level = 0
            if not skip_level and m.group(2).strip().lower() in names:
                skip_level = level
                continue
        if not skip_level:
            out.append(line)
    return "\n".join(out)


def md_link_text(text: str) -> str:
    return text.replace("[", "(").replace("]", ")")


def wikipedia_url(s: dict, art: dict | None) -> str | None:
    if art and art.get("title"):
        return f"https://{art.get('lang', 'en')}.wikipedia.org/wiki/{quote(art['title'].replace(' ', '_'))}"
    links = loads(s.get("sitelinks") or "{}", {}) or {}
    if links.get("enwiki"):
        return f"https://en.wikipedia.org/wiki/{quote(links['enwiki'].replace(' ', '_'))}"
    if s.get("qid"):
        return f"https://www.wikidata.org/wiki/{s['qid']}"
    return None


def web_url(s: dict, art: dict | None, stories: list[dict]) -> str | None:
    """The best page to open in a web browser for the saint."""
    url = wikipedia_url(s, art)
    if url:
        return url
    for src in ("orthodoxwiki", "mystagogy", "htc"):
        for st in stories:
            if st["source"] == src and st["url"]:
                return st["url"]
    if s.get("az_slug"):
        return f"https://azbyka.ru/days/{s['az_slug']}"
    return None
