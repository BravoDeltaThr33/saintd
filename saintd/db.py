"""SQLite storage for the directory, lives, articles and caches."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Iterable

from .text import query_variants, search_forms

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;
PRAGMA temp_store=MEMORY;
CREATE TABLE IF NOT EXISTS saints (
    id INTEGER PRIMARY KEY,
    key TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    core TEXT NOT NULL DEFAULT '',
    search TEXT NOT NULL DEFAULT '',
    kind TEXT NOT NULL DEFAULT 'saint',
    gender TEXT NOT NULL DEFAULT 'Unknown',
    gender_src TEXT NOT NULL DEFAULT '',
    century INTEGER,
    century_src TEXT NOT NULL DEFAULT '',
    year_hint INTEGER,
    qid_hint TEXT NOT NULL DEFAULT '',
    born TEXT NOT NULL DEFAULT '',
    died TEXT NOT NULL DEFAULT '',
    country TEXT NOT NULL DEFAULT 'Unknown',
    country_src TEXT NOT NULL DEFAULT '',
    place TEXT NOT NULL DEFAULT '',
    categories TEXT NOT NULL DEFAULT '|',
    description TEXT NOT NULL DEFAULT '',
    aliases TEXT NOT NULL DEFAULT '',
    qid TEXT NOT NULL DEFAULT '',
    wikilabel TEXT NOT NULL DEFAULT '',
    sitelinks TEXT NOT NULL DEFAULT '{}',
    image TEXT NOT NULL DEFAULT '',
    icon_url TEXT NOT NULL DEFAULT '',
    icon_credit TEXT NOT NULL DEFAULT '',
    ru_text TEXT NOT NULL DEFAULT '',
    ru_nominative TEXT NOT NULL DEFAULT '',
    ru_en TEXT NOT NULL DEFAULT '',
    ru_mt INTEGER NOT NULL DEFAULT 0,
    az_slug TEXT NOT NULL DEFAULT '',
    sources TEXT NOT NULL DEFAULT '|',
    enrich_state INTEGER NOT NULL DEFAULT 0,
    enriched_at REAL NOT NULL DEFAULT 0,
    updated_at REAL NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS saints_qid ON saints(qid);
CREATE INDEX IF NOT EXISTS saints_enrich ON saints(enrich_state);
CREATE TABLE IF NOT EXISTS feasts (
    saint_id INTEGER NOT NULL,
    month INTEGER NOT NULL,
    day INTEGER NOT NULL,
    label TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL DEFAULT '',
    UNIQUE(saint_id, month, day, label)
);
CREATE INDEX IF NOT EXISTS feasts_date ON feasts(month, day);
CREATE INDEX IF NOT EXISTS feasts_saint ON feasts(saint_id);
CREATE TABLE IF NOT EXISTS stories (
    saint_id INTEGER NOT NULL,
    source TEXT NOT NULL,
    title TEXT NOT NULL,
    html TEXT NOT NULL,
    url TEXT NOT NULL DEFAULT '',
    UNIQUE(saint_id, source, title)
);
CREATE TABLE IF NOT EXISTS articles (
    saint_id INTEGER PRIMARY KEY,
    lang TEXT NOT NULL DEFAULT 'en',
    title TEXT NOT NULL DEFAULT '',
    text TEXT NOT NULL DEFAULT '',
    translated_by TEXT NOT NULL DEFAULT '',
    fetched_at REAL NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS http_cache (
    url TEXT PRIMARY KEY,
    body TEXT NOT NULL,
    fetched_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS translations (
    src TEXT NOT NULL,
    tgt TEXT NOT NULL,
    hash TEXT NOT NULL,
    text TEXT NOT NULL,
    out TEXT NOT NULL,
    backend TEXT NOT NULL,
    PRIMARY KEY(src, tgt, hash)
);
CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS lookups (
    saint_id INTEGER NOT NULL,
    source TEXT NOT NULL,
    checked_at REAL NOT NULL,
    PRIMARY KEY(saint_id, source)
);
CREATE TABLE IF NOT EXISTS favorites (
    saint_id INTEGER PRIMARY KEY,
    saint_key TEXT NOT NULL DEFAULT '',
    added_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS saints_kind ON saints(kind);
CREATE INDEX IF NOT EXISTS stories_saint ON stories(saint_id, source);
CREATE TABLE IF NOT EXISTS src_titles (
    source TEXT NOT NULL,
    month INTEGER NOT NULL,
    day INTEGER NOT NULL,
    title TEXT NOT NULL,
    saint_id INTEGER NOT NULL,
    PRIMARY KEY(source, month, day, title)
);
"""

SAINT_COLS = [
    "id", "key", "name", "core", "kind", "gender", "gender_src", "century", "century_src", "born", "died",
    "country", "country_src", "place", "categories", "description", "aliases", "qid", "wikilabel",
    "sitelinks", "image", "ru_text", "ru_nominative", "ru_en", "ru_mt", "az_slug", "sources",
    "enrich_state", "enriched_at",
]

# story sources that are lives of the saint (the others are notes, hymns and links)
LIFE_SOURCES = ("orthocal", "htc", "mystagogy", "azbyka-life")
LIFE_SQL = ",".join(f"'{x}'" for x in LIFE_SOURCES)

# kinds hidden from search unless "include feasts, icons & memorials" is on
PEOPLE_KINDS = ("saint", "group", "angel")


def _row(r: sqlite3.Row | None) -> dict | None:
    return dict(r) if r is not None else None


class DB:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.lock = threading.RLock()
        self.con = sqlite3.connect(str(path), check_same_thread=False, timeout=30)
        self.con.row_factory = sqlite3.Row
        self._stats: tuple[float, dict] | None = None
        with self.lock:
            self.con.executescript(SCHEMA)
            cols = {r[1] for r in self.con.execute("PRAGMA table_info(saints)").fetchall()}
            if "year_hint" not in cols:            # upgrade databases from earlier versions
                self.con.execute("ALTER TABLE saints ADD COLUMN year_hint INTEGER")
            if "qid_hint" not in cols:
                self.con.execute("ALTER TABLE saints ADD COLUMN qid_hint TEXT NOT NULL DEFAULT ''")
            for col in ("icon_url", "icon_credit"):
                if col not in cols:
                    self.con.execute(f"ALTER TABLE saints ADD COLUMN {col} TEXT NOT NULL DEFAULT ''")
            st_cols = {r[1] for r in self.con.execute("PRAGMA table_info(stories)").fetchall()}
            if "url" not in st_cols:
                self.con.execute("ALTER TABLE stories ADD COLUMN url TEXT NOT NULL DEFAULT ''")
            self.con.commit()

    def close(self) -> None:
        with self.lock:
            self.con.close()

    # ------------------------------------------------------------ meta
    def meta(self, k: str, default: str = "") -> str:
        with self.lock:
            r = self.con.execute("SELECT v FROM meta WHERE k=?", (k,)).fetchone()
        return r[0] if r else default

    def set_meta(self, k: str, v: Any) -> None:
        with self.lock:
            self.con.execute("INSERT OR REPLACE INTO meta(k, v) VALUES(?, ?)", (k, str(v)))
            self.con.commit()

    # ------------------------------------------------------------ cache
    def cache_get(self, url: str, ttl: float) -> str | None:
        with self.lock:
            r = self.con.execute("SELECT body, fetched_at FROM http_cache WHERE url=?", (url,)).fetchone()
        if r and time.time() - r[1] < ttl:
            return r[0]
        return None

    def cache_put(self, url: str, body: str) -> None:
        with self.lock:
            self.con.execute("INSERT OR REPLACE INTO http_cache(url, body, fetched_at) VALUES(?,?,?)",
                             (url, body, time.time()))
            self.con.commit()

    def clear_cache(self) -> None:
        with self.lock:
            self.con.execute("DELETE FROM http_cache")
            self.con.execute("DELETE FROM articles")
            self.con.commit()
            self.con.execute("VACUUM")

    # ------------------------------------------------------- translations
    @staticmethod
    def _h(text: str) -> str:
        return hashlib.sha1(text.encode("utf-8")).hexdigest()

    def tr_get(self, src: str, tgt: str, text: str) -> str | None:
        with self.lock:
            r = self.con.execute("SELECT out FROM translations WHERE src=? AND tgt=? AND hash=?",
                                 (src, tgt, self._h(text))).fetchone()
        return r[0] if r else None

    def tr_put(self, src: str, tgt: str, text: str, out: str, backend: str) -> None:
        with self.lock:
            self.con.execute("INSERT OR REPLACE INTO translations VALUES(?,?,?,?,?,?)",
                             (src, tgt, self._h(text), text, out, backend))
            self.con.commit()

    # ------------------------------------------------------------ saints
    def get_saint(self, sid: int) -> dict | None:
        with self.lock:
            return _row(self.con.execute("SELECT * FROM saints WHERE id=?", (sid,)).fetchone())

    def saint_by_key(self, key: str) -> dict | None:
        with self.lock:
            return _row(self.con.execute("SELECT * FROM saints WHERE key=?", (key,)).fetchone())

    def saint_by_qid(self, qid: str, exclude: int | None = None) -> dict | None:
        with self.lock:
            r = self.con.execute("SELECT * FROM saints WHERE qid=? AND id!=? AND kind!='group' LIMIT 1",
                                 (qid, exclude or -1)).fetchone()
        return _row(r)

    def insert_saint(self, fields: dict) -> int:
        f = dict(fields)
        f.setdefault("core", "")
        f["search"] = self._search_blob(f)
        f["updated_at"] = time.time()
        cols = ",".join(f)
        q = ",".join("?" for _ in f)
        with self.lock:
            cur = self.con.execute(f"INSERT INTO saints({cols}) VALUES({q})", list(f.values()))
            self.con.commit()
            return int(cur.lastrowid)

    def update_saint(self, sid: int, fields: dict, commit: bool = True) -> None:
        if not fields:
            return
        f = dict(fields)
        f["updated_at"] = time.time()
        with self.lock:
            sets = ",".join(f"{k}=?" for k in f)
            self.con.execute(f"UPDATE saints SET {sets} WHERE id=?", [*f.values(), sid])
            if any(k in f for k in ("name", "core", "aliases", "wikilabel", "ru_en", "description")):
                cur = _row(self.con.execute("SELECT * FROM saints WHERE id=?", (sid,)).fetchone())
                if cur:
                    self.con.execute("UPDATE saints SET search=? WHERE id=?", (self._search_blob(cur), sid))
            if commit:
                self.con.commit()

    def commit(self) -> None:
        with self.lock:
            self.con.commit()

    @staticmethod
    def _search_blob(f: dict) -> str:
        parts = [f.get("name", ""), f.get("core", ""), f.get("aliases", ""), f.get("wikilabel", ""),
                 f.get("ru_en", "")]
        return search_forms(" ".join(p for p in parts if p))

    def add_feast(self, sid: int, month: int, day: int, label: str, source: str, commit: bool = True) -> None:
        with self.lock:
            self.con.execute("INSERT OR IGNORE INTO feasts(saint_id, month, day, label, source) VALUES(?,?,?,?,?)",
                             (sid, month, day, label, source))
            if commit:
                self.con.commit()

    def feasts(self, sid: int) -> list[dict]:
        with self.lock:
            rows = self.con.execute("SELECT month, day, label, source FROM feasts WHERE saint_id=? "
                                    "ORDER BY month, day", (sid,)).fetchall()
        return [dict(r) for r in rows]

    def saints_on(self, month: int, day: int, people_only: bool = True) -> list[dict]:
        kinds = PEOPLE_KINDS if people_only else ("saint", "group", "angel", "feast", "icon", "memorial")
        q = ",".join("?" for _ in kinds)
        with self.lock:
            rows = self.con.execute(
                f"SELECT DISTINCT s.* FROM saints s JOIN feasts f ON f.saint_id=s.id "
                f"WHERE f.month=? AND f.day=? AND s.kind IN ({q}) "
                f"ORDER BY EXISTS(SELECT 1 FROM stories st WHERE st.saint_id=s.id AND st.source IN ({LIFE_SQL})) DESC, "
                f"(s.sources LIKE '%orthocal%') DESC, s.kind='group', s.name",
                (month, day, *kinds)).fetchall()
        return [dict(r) for r in rows]

    def add_story(self, sid: int, source: str, title: str, html: str, commit: bool = True, url: str = "") -> None:
        with self.lock:
            self.con.execute("INSERT OR REPLACE INTO stories(saint_id, source, title, html, url) VALUES(?,?,?,?,?)",
                             (sid, source, title, html, url))
            if commit:
                self.con.commit()

    def stories(self, sid: int) -> list[dict]:
        with self.lock:
            rows = self.con.execute("SELECT source, title, html, url FROM stories WHERE saint_id=? ORDER BY rowid",
                                    (sid,)).fetchall()
        return [dict(r) for r in rows]

    def drop_stories(self, sid: int, source: str) -> None:
        with self.lock:
            self.con.execute("DELETE FROM stories WHERE saint_id=? AND source=?", (sid, source))
            self.con.commit()

    def merge_into(self, keep: int, drop: int) -> None:
        """Move feasts/stories of `drop` onto `keep` and delete `drop`."""
        with self.lock:
            self.con.execute("UPDATE OR IGNORE feasts SET saint_id=? WHERE saint_id=?", (keep, drop))
            self.con.execute("UPDATE OR IGNORE stories SET saint_id=? WHERE saint_id=?", (keep, drop))
            self.con.execute("UPDATE src_titles SET saint_id=? WHERE saint_id=?", (keep, drop))
            self.con.execute("UPDATE OR IGNORE favorites SET saint_id=? WHERE saint_id=?", (keep, drop))
            self.con.execute("DELETE FROM favorites WHERE saint_id=?", (drop,))
            self.con.execute("DELETE FROM lookups WHERE saint_id IN (?, ?)", (keep, drop))
            a = _row(self.con.execute("SELECT * FROM saints WHERE id=?", (drop,)).fetchone()) or {}
            b = _row(self.con.execute("SELECT * FROM saints WHERE id=?", (keep,)).fetchone()) or {}
            srcs = "|" + "|".join(sorted({x for x in (a.get("sources", "") + b.get("sources", "")).split("|") if x})) + "|"
            upd = {"sources": srcs}
            for col in ("ru_text", "ru_en", "az_slug", "ru_nominative", "qid_hint", "image", "icon_url",
                        "icon_credit", "place", "born", "died", "description", "wikilabel"):
                if not b.get(col) and a.get(col):
                    upd[col] = a[col]
            # facts the kept entry lacks
            for col, src, empty in (("century", "century_src", (None,)), ("year_hint", None, (None,)),
                                    ("gender", "gender_src", ("", "Unknown")), ("country", "country_src", ("", "Unknown"))):
                if b.get(col) in empty and a.get(col) not in empty:
                    upd[col] = a[col]
                    if src:
                        upd[src] = a.get(src, "")
            if not b.get("qid") and a.get("qid"):
                upd.update(qid=a["qid"], enrich_state=a.get("enrich_state", 0), enriched_at=a.get("enriched_at", 0))
            if a.get("core") and b.get("core") and a["core"].lower() != b["core"].lower():
                known = [x.strip() for x in (b.get("aliases") or "").split("|") if x.strip()]
                if a["name"] not in known and a["name"] != b.get("name"):
                    upd["aliases"] = " | ".join([*known, a["name"]][:10])
            if b.get("sitelinks", "{}") in ("", "{}") and a.get("sitelinks", "{}") not in ("", "{}"):
                upd["sitelinks"] = a["sitelinks"]
            cats = [c for c in (b.get("categories", "") + a.get("categories", "")).split("|") if c]
            if cats:
                upd["categories"] = "|" + "|".join(dict.fromkeys(cats)) + "|"
            sets = ",".join(f"{k}=?" for k in upd)
            self.con.execute(f"UPDATE saints SET {sets} WHERE id=?", [*upd.values(), keep])
            if "aliases" in upd or "wikilabel" in upd or "ru_en" in upd:
                cur = _row(self.con.execute("SELECT * FROM saints WHERE id=?", (keep,)).fetchone())
                if cur:
                    self.con.execute("UPDATE saints SET search=? WHERE id=?", (self._search_blob(cur), keep))
            self.con.execute("DELETE FROM feasts WHERE saint_id=?", (drop,))
            self.con.execute("DELETE FROM stories WHERE saint_id=?", (drop,))
            self.con.execute("DELETE FROM articles WHERE saint_id=?", (drop,))
            self.con.execute("DELETE FROM saints WHERE id=?", (drop,))
            self.con.commit()

    # ------------------------------------------------------- source titles
    def src_title(self, source: str, month: int, day: int, title: str) -> int | None:
        """The saint a source's exact title was filed under on an earlier build."""
        with self.lock:
            r = self.con.execute("SELECT t.saint_id FROM src_titles t JOIN saints s ON s.id=t.saint_id "
                                 "WHERE t.source=? AND t.month=? AND t.day=? AND t.title=?",
                                 (source, month, day, title)).fetchone()
        return r[0] if r else None

    def put_src_title(self, source: str, month: int, day: int, title: str, sid: int) -> None:
        with self.lock:
            self.con.execute("INSERT OR REPLACE INTO src_titles VALUES(?,?,?,?,?)", (source, month, day, title, sid))

    def pending_enrichment(self, limit: int = 25) -> list[dict]:
        with self.lock:
            rows = self.con.execute(
                "SELECT * FROM saints WHERE enrich_state IN (0,4) AND kind IN ('saint','group') "
                "ORDER BY enrich_state, (kind='group'), (qid_hint=''), (sources NOT LIKE '%orthocal%'), id LIMIT ?",
                (limit,)).fetchall()
        return [dict(r) for r in rows]

    def retry_unmatched_with_text_search(self) -> None:
        with self.lock:
            self.con.execute("UPDATE saints SET enrich_state=4 WHERE enrich_state=2 AND qid='' "
                             "AND kind IN ('saint','group')")
            self.con.commit()

    def reset_failed_enrichment(self) -> None:
        with self.lock:
            self.con.execute("UPDATE saints SET enrich_state=0 WHERE enrich_state=3")
            self.con.commit()

    def all_saints_on(self, month: int, day: int) -> list[dict]:
        return self.saints_on(month, day, people_only=False)

    # ------------------------------------------------------------ lookups
    def looked(self, sid: int, source: str, max_age: float = 30 * 86400) -> bool:
        """Was this source already checked for the saint (recently)?"""
        with self.lock:
            r = self.con.execute("SELECT checked_at FROM lookups WHERE saint_id=? AND source=?",
                                 (sid, source)).fetchone()
        return bool(r) and time.time() - r[0] < max_age

    def mark_looked(self, sid: int, source: str) -> None:
        with self.lock:
            self.con.execute("INSERT OR REPLACE INTO lookups VALUES(?,?,?)", (sid, source, time.time()))
            self.con.commit()

    def forget_lookups(self, sid: int) -> None:
        with self.lock:
            self.con.execute("DELETE FROM lookups WHERE saint_id=?", (sid,))
            self.con.commit()

    # ------------------------------------------------------------ favorites
    def is_favorite(self, sid: int) -> bool:
        with self.lock:
            return self.con.execute("SELECT 1 FROM favorites WHERE saint_id=?", (sid,)).fetchone() is not None

    def set_favorite(self, sid: int, on: bool) -> None:
        with self.lock:
            if on:
                key = self.con.execute("SELECT key FROM saints WHERE id=?", (sid,)).fetchone()
                self.con.execute("INSERT OR REPLACE INTO favorites VALUES(?,?,?)",
                                 (sid, key[0] if key else "", time.time()))
            else:
                self.con.execute("DELETE FROM favorites WHERE saint_id=?", (sid,))
            self.con.commit()

    def favorite_ids(self) -> set[int]:
        with self.lock:
            return {r[0] for r in self.con.execute("SELECT saint_id FROM favorites").fetchall()}

    def favorites(self) -> list[dict]:
        """Saved saints with their feast days, newest first."""
        with self.lock:
            rows = self.con.execute(
                "SELECT s.*, (SELECT group_concat(printf('%02d-%02d', month, day)) FROM "
                "(SELECT DISTINCT month, day FROM feasts f WHERE f.saint_id=s.id ORDER BY month, day)) AS feast_days "
                "FROM favorites v JOIN saints s ON s.id=v.saint_id ORDER BY v.added_at DESC").fetchall()
        return [dict(r) for r in rows]

    def relink_favorites(self) -> None:
        """After a rebuild, find saved saints again by their key."""
        with self.lock:
            self.con.execute("UPDATE favorites SET saint_id=(SELECT id FROM saints WHERE saints.key=favorites.saint_key) "
                             "WHERE saint_key!='' AND saint_id NOT IN (SELECT id FROM saints) "
                             "AND EXISTS(SELECT 1 FROM saints WHERE saints.key=favorites.saint_key)")
            self.con.commit()

    # ------------------------------------------------------------ articles
    def article(self, sid: int) -> dict | None:
        with self.lock:
            return _row(self.con.execute("SELECT * FROM articles WHERE saint_id=?", (sid,)).fetchone())

    def put_article(self, sid: int, lang: str, title: str, text: str, translated_by: str = "") -> None:
        with self.lock:
            self.con.execute("INSERT OR REPLACE INTO articles VALUES(?,?,?,?,?,?)",
                             (sid, lang, title, text, translated_by, time.time()))
            self.con.commit()

    # ------------------------------------------------------------ stats
    def stats(self, max_age: float = 1.0) -> dict:
        now = time.monotonic()
        if self._stats and now - self._stats[0] < max_age:
            return dict(self._stats[1])
        with self.lock:
            c = self.con
            total = c.execute("SELECT COUNT(*) FROM saints").fetchone()[0]
            people = c.execute("SELECT COUNT(*) FROM saints WHERE kind IN ('saint','group','angel')").fetchone()[0]
            enriched = c.execute("SELECT COUNT(*) FROM saints WHERE enrich_state IN (1,2)").fetchone()[0]
            matched = c.execute("SELECT COUNT(*) FROM saints WHERE enrich_state=1").fetchone()[0]
            pending = c.execute("SELECT COUNT(*) FROM saints WHERE enrich_state IN (0,4) "
                                "AND kind IN ('saint','group')").fetchone()[0]
            enrichable = c.execute("SELECT COUNT(*) FROM saints WHERE kind IN ('saint','group')").fetchone()[0]
            lives = c.execute("SELECT COUNT(DISTINCT saint_id) FROM stories "
                              f"WHERE source IN ({LIFE_SQL})").fetchone()[0]
            articles = c.execute("SELECT COUNT(*) FROM articles").fetchone()[0]
        st = {"total": total, "people": people, "enriched": enriched, "matched": matched, "pending": pending,
              "enrichable": enrichable, "lives": lives, "articles": articles}
        self._stats = (now, st)
        return dict(st)

    def distinct(self, col: str) -> list:
        assert col in ("country", "century", "gender")
        with self.lock:
            rows = self.con.execute(f"SELECT DISTINCT {col} FROM saints WHERE kind IN ('saint','group','angel') "
                                    f"AND {col} IS NOT NULL").fetchall()
        return [r[0] for r in rows]

    def marks(self, ids: list[int]) -> dict[int, set[str]]:
        """Which of these saints have a life ("life") or hymns ("hymns") stored."""
        out: dict[int, set[str]] = {}
        if not ids:
            return out
        q = ",".join("?" for _ in ids)
        with self.lock:
            rows = self.con.execute(f"SELECT DISTINCT saint_id, source FROM stories WHERE saint_id IN ({q}) "
                                    f"AND source IN ({LIFE_SQL},'htc-hymn')", list(ids)).fetchall()
        for sid, src in rows:
            out.setdefault(sid, set()).add("hymns" if src == "htc-hymn" else "life")
        return out

    def random_saint(self) -> dict | None:
        with self.lock:
            return _row(self.con.execute(
                "SELECT * FROM saints WHERE kind='saint' ORDER BY RANDOM() LIMIT 1").fetchone())

    # ------------------------------------------------------------ search
    def search(self, text: str = "", *, month: int | None = None, day: int | None = None,
               gender: str | None = None, country: str | None = None, century: Any = None,
               category: str | None = None, include_other: bool = False, saved_only: bool = False,
               limit: int = 1000, offset: int = 0, count: bool = True) -> tuple[list[dict], int]:
        where, args = [], []
        for variants in query_variants(text):
            ors = " OR ".join("s.search LIKE ?" for _ in variants)
            where.append(f"({ors})")
            args.extend(f"%{v}%" for v in variants)
        if month or day:
            sub = "SELECT saint_id FROM feasts WHERE 1=1"
            if month:
                sub += " AND month=?"
                args.append(month)
            if day:
                sub += " AND day=?"
                args.append(day)
            where.append(f"s.id IN ({sub})")
        if gender:
            where.append("s.gender=?")
            args.append(gender)
        if country:
            where.append("s.country=?")
            args.append(country)
        if century == "unknown":
            where.append("s.century IS NULL")
        elif century is not None:
            where.append("s.century=?")
            args.append(int(century))
        if category:
            where.append("s.categories LIKE ?")
            args.append(f"%|{category}|%")
        if not include_other:
            where.append("s.kind IN ('saint','group','angel')")
        if saved_only:
            where.append("s.id IN (SELECT saint_id FROM favorites)")
        w = (" WHERE " + " AND ".join(where)) if where else ""
        # relevance: names that start with what was typed, then well-documented saints
        qv = query_variants(text)
        rank_sql, rank_args = "", []
        if qv:
            forms = sorted(qv[0], key=len)
            starts = " OR ".join("s.core LIKE ?" for _ in forms)
            words = " OR ".join("s.search LIKE ?" for _ in forms)
            rank_sql = f"(CASE WHEN {starts} THEN 0 WHEN {words} THEN 1 ELSE 2 END), "
            rank_args = [f"{f}%" for f in forms] + [f"% {f}%" for f in forms]
        with self.lock:
            n = self.con.execute(f"SELECT COUNT(*) FROM saints s{w}", args).fetchone()[0] if count else -1
            rows = self.con.execute(
                f"SELECT s.*, "
                f"(EXISTS(SELECT 1 FROM stories st WHERE st.saint_id=s.id AND st.source IN ({LIFE_SQL})) "
                f"OR EXISTS(SELECT 1 FROM articles a WHERE a.saint_id=s.id)) AS has_life, "
                f"(SELECT printf('%02d-%02d', month, day) FROM feasts f "
                f"WHERE f.saint_id=s.id ORDER BY month, day LIMIT 1) AS first_feast FROM saints s{w} "
                f"ORDER BY {rank_sql}(s.kind='group'), has_life DESC, (s.sources LIKE '%orthocal%') DESC, "
                f"(s.enrich_state=1) DESC, s.core COLLATE NOCASE, s.name COLLATE NOCASE LIMIT ? OFFSET ?",
                [*args, *rank_args, limit, offset]).fetchall()
        return [dict(r) for r in rows], n

    def wipe_directory(self) -> None:
        """Forget the directory but keep downloaded responses and translations,
        so a rebuild is quick."""
        with self.lock:
            for t in ("saints", "feasts", "stories", "articles", "meta", "src_titles", "lookups"):
                self.con.execute(f"DELETE FROM {t}")
            self.con.commit()
            self._stats = None

    def wipe(self) -> None:
        self._stats = None
        with self.lock:
            for t in ("saints", "feasts", "stories", "articles", "http_cache", "meta", "src_titles", "lookups",
                      "favorites"):
                self.con.execute(f"DELETE FROM {t}")
            self.con.commit()
            self.con.execute("VACUUM")


def dumps(o: Any) -> str:
    return json.dumps(o, ensure_ascii=False, separators=(",", ":"))


def loads(s: str, default: Any = None) -> Any:
    try:
        return json.loads(s)
    except (TypeError, ValueError):
        return default


def cats_to_str(cats: Iterable[str]) -> str:
    c = [x for x in dict.fromkeys(cats) if x]
    return "|" + "|".join(c) + "|" if c else "|"


def str_to_cats(s: str) -> list[str]:
    return [x for x in (s or "").split("|") if x]
