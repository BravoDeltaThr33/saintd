"""Clients for the public APIs Saint Directory draws on."""

from __future__ import annotations

import datetime as dt
import re
from typing import Any

from .net import Http

REF_YEAR = 2028          # a leap year, so Feb 29 commemorations are included
DAY = 86400
WEEK = 7 * DAY

SOURCES = [
    {
        "id": "orthocal",
        "name": "Orthocal",
        "url": "https://orthocal.info/api/",
        "lang": "English",
        "key": "None",
        "provides": "Calendar of saints (OCA/Slavic + Greek), lives of the saints, fasting",
        "terms": "Free public API (please stay under 5 req/s)",
        "probe": "https://orthocal.info/api/gregorian/",
    },
    {
        "id": "azbyka",
        "name": "Azbuka Very",
        "url": "https://azbyka.ru/days/widgets/presentations.json",
        "lang": "Russian → English",
        "key": "None",
        "provides": "Russian Church calendar: extra saints, New Martyrs, centuries; the saint's page "
                    "(azbyka.ru/days/sv-…) gives the Russian life, translated when no English one exists",
        "terms": "Public calendar widget feed and saint pages (fetched when you open a saint)",
        "probe": "https://azbyka.ru/days/widgets/presentations.json",
    },
    {
        "id": "mystagogy",
        "name": "Mystagogy Resource Center",
        "url": "https://www.johnsanidopoulos.com/feeds/posts/summary?alt=json&q=…",
        "lang": "English",
        "key": "None",
        "provides": "Lives and Synaxarion entries for thousands of saints, especially Greek saints and New "
                    "Martyrs, found through the blog's public search feed when the calendars give no Life",
        "terms": "Public Blogger feed; text © John Sanidopoulos, credited and linked on every page that uses it",
        "probe": "https://www.johnsanidopoulos.com/feeds/posts/summary?alt=json&max-results=1",
    },
    {
        "id": "wikical",
        "name": "Wikipedia Orthodox calendar",
        "url": "https://en.wikipedia.org/wiki/<Month>_<day>_(Eastern_Orthodox_liturgics)",
        "lang": "English",
        "key": "None",
        "provides": "366 day pages from the Great Synaxaristes: Greek, Russian, Georgian, Serbian and "
                    "pre-Schism Western saints, New Martyrs, short notes and article links",
        "terms": "Text CC BY-SA 4.0 \u2014 attribution shown with each entry",
        "probe": "https://en.wikipedia.org/w/api.php?action=query&titles=January_1_(Eastern_Orthodox_liturgics)"
                 "&format=json",
    },
    {
        "id": "htc",
        "name": "Holy Trinity Orthodox Calendar",
        "url": "https://www.holytrinityorthodox.com/calendar/calendar.php",
        "lang": "English",
        "key": "None",
        "provides": "Lives of the saints (translated by Fr. S. Janos) and the day's troparia and kontakia, "
                    "for the saints you open",
        "terms": "Calendar service of Holy Trinity Russian Orthodox Church, Baltimore, offered to other sites "
                 "(\u201cFor Webmasters\u201d); fetched once per day page and cached \u2014 never downloaded in bulk",
        "probe": "https://www.holytrinityorthodox.com/htc/orthodox-calendar/",
    },
    {
        "id": "orthodoxwiki",
        "name": "OrthodoxWiki",
        "url": "https://orthodoxwiki.org/api.php",
        "lang": "English",
        "key": "None",
        "provides": "Articles on about 5,000 Orthodox subjects, used for the History section when Wikipedia has "
                    "none, and icons",
        "terms": "GFDL / CC BY-SA 2.5 \u2014 credited and linked on each page that uses it",
        "probe": "https://orthodoxwiki.org/api.php?action=query&meta=siteinfo&format=json",
    },
    {
        "id": "commons",
        "name": "Icons",
        "url": "https://upload.wikimedia.org/ \u00b7 azbyka.ru \u00b7 commons.orthodoxwiki.org",
        "lang": "Images",
        "key": "None",
        "provides": "Icons of the saints: the Wikidata image on Wikimedia Commons, else the saint's icon on "
                    "OrthodoxWiki or Azbuka Very; downloaded once, kept in ~/.cache/saintd/icons",
        "terms": "Each icon's source is credited on the saint's Focus page",
        "probe": "",
    },
    {
        "id": "wikidata",
        "name": "Wikidata",
        "url": "https://www.wikidata.org/w/api.php",
        "lang": "Multilingual",
        "key": "None",
        "provides": "Gender, birth/death, birthplace & country, names, links (found by name, or through "
                    "Wikipedia's full-text search when the spelling differs); and, through its query service, "
                    "Eastern Orthodox saints with a feast day that no calendar lists",
        "terms": "CC0 public domain data",
        "probe": "https://www.wikidata.org/w/api.php?action=query&meta=siteinfo&format=json",
    },
    {
        "id": "wikipedia",
        "name": "Wikipedia",
        "url": "https://en.wikipedia.org/w/api.php",
        "lang": "English (+ others, translated)",
        "key": "None",
        "provides": "Full history articles for the Focus tab",
        "terms": "Text CC BY-SA 4.0 — attribution shown with each article",
        "probe": "https://en.wikipedia.org/w/api.php?action=query&meta=siteinfo&format=json",
    },
    {
        "id": "translator",
        "name": "Translator",
        "url": "(chosen in Settings)",
        "lang": "Any → English",
        "key": "None (optional e-mail/URL)",
        "provides": "Translates non-English names and articles",
        "terms": "See the translator's own limits",
        "probe": "",
    },
]

# --------------------------------------------------------------- orthocal

ORTHOCAL = "https://orthocal.info/api"


def orthocal_month(http: Http, year: int, month: int, tradition: str | None = None) -> list[dict]:
    path = f"{tradition}/gregorian" if tradition else "gregorian"
    data = http.get_json(f"{ORTHOCAL}/{path}/{year}/{month}/", ttl=30 * DAY)
    return data if isinstance(data, list) else []


def orthocal_day(http: Http, year: int, month: int, day: int, tradition: str | None = None) -> dict:
    path = f"{tradition}/gregorian" if tradition else "gregorian"
    data = http.get_json(f"{ORTHOCAL}/{path}/{year}/{month}/{day}/", ttl=30 * DAY)
    return data if isinstance(data, dict) else {}


def orthocal_month_days(http: Http, year: int, month: int, calendar: str = "gregorian") -> dict[dt.date, dict]:
    """Liturgical data for each civil day of a month: typikon rank, fast level,
    title. calendar: 'gregorian' (New) or 'julian' (Old)."""
    data = http.get_json(f"{ORTHOCAL}/{calendar}/{year}/{month}/", ttl=30 * DAY)
    out: dict[dt.date, dict] = {}
    for i, d in enumerate(data if isinstance(data, list) else []):
        try:
            civil = dt.date(d["year"], d["month"], d["day"])
            if calendar == "julian":
                civil += dt.timedelta(days=JULIAN_OFFSET)
        except (KeyError, ValueError, TypeError):
            civil = dt.date(year, month, 1) + dt.timedelta(days=i)
        feasts = [f for f in (d.get("feasts") or []) if f]
        out[civil] = {"rank": int(d.get("feast_level") or 0), "fast": int(d.get("fast_level") or 0),
                      "title": feasts[0] if feasts else (d.get("summary_title") or "")}
    return out


def orthocal_on(http: Http, civil: dt.date, calendar: str = "gregorian") -> dict:
    """Everything orthocal knows about a civil date: titles, tone, fast,
    feasts, saints and the Scripture readings with their text."""
    ttl = 6 * 3600 if civil == dt.date.today() else 30 * DAY
    data = http.get_json(f"{ORTHOCAL}/{calendar}/{civil.year}/{civil.month}/{civil.day}/", ttl=ttl)
    return data if isinstance(data, dict) else {}


def orthocal_today(http: Http, calendar: str = "gregorian") -> dict:
    """Today's liturgical day. calendar: 'gregorian' (New) or 'julian' (Old)."""
    today = dt.date.today()
    data = http.get_json(f"{ORTHOCAL}/{calendar}/{today.year}/{today.month}/{today.day}/", ttl=6 * 3600)
    return data if isinstance(data, dict) else {}


# --------------------------------------------------------------- azbyka

AZBYKA_WIDGET = "https://azbyka.ru/days/widgets/presentations.json"
JULIAN_OFFSET = 13       # days between Julian and Gregorian dates (1900-2099)


def church_to_civil(month: int, day: int, year: int = REF_YEAR) -> dt.date:
    """Civil (Gregorian) date on which the Old Calendar keeps church date month/day."""
    return dt.date(year, month, day) + dt.timedelta(days=JULIAN_OFFSET)


def civil_to_church(d: dt.date) -> tuple[int, int]:
    c = d - dt.timedelta(days=JULIAN_OFFSET)
    return c.month, c.day


def azbyka_day(http: Http, month: int, day: int) -> dict:
    civil = church_to_civil(month, day)
    data = http.get_json(AZBYKA_WIDGET, {"date": civil.isoformat(), "image": 1}, ttl=30 * DAY)
    return data if isinstance(data, dict) else {}


# --------------------------------------------------------------- wikimedia

WD_API = "https://www.wikidata.org/w/api.php"
WDQS = "https://query.wikidata.org/sparql"
_ENTITY = "http://www.wikidata.org/entity/"


def wdqs(http: Http, query: str, ttl: float = WEEK) -> list[dict[str, str]]:
    """The rows of a SPARQL query on the Wikidata Query Service, each a dict of plain values:
    an item's or property's id for its URI, the text of a literal (and, under "name@",
    the language of a text that has one)."""
    data = http.get_json(WDQS, {"query": query, "format": "json"}, ttl=ttl, timeout=90)
    rows = []
    for b in ((data or {}).get("results") or {}).get("bindings") or []:
        row: dict[str, str] = {}
        for k, v in b.items():
            val = v.get("value", "")
            if v.get("type") == "uri" and val.startswith(_ENTITY):
                val = val[len(_ENTITY):]
            row[k] = val
            if v.get("xml:lang"):
                row[k + "@"] = v["xml:lang"]
        rows.append(row)
    return rows


def wd_search(http: Http, query: str, limit: int = 5) -> list[str]:
    """Wikidata items with a canonization status (P411) matching `query`."""
    q = re.sub(r"[\"'()\[\]{}:!^~*?\\/]", " ", query).strip()
    if not q:
        return []
    data = http.get_json(WD_API, {
        "action": "query", "list": "search", "format": "json", "srnamespace": 0,
        "srlimit": limit, "srprop": "", "srsearch": f"{q} haswbstatement:P411",
    })
    return [h["title"] for h in (data.get("query") or {}).get("search", []) if h.get("title", "").startswith("Q")]


def wd_entities(http: Http, ids: list[str], props: str = "labels|descriptions|aliases|claims|sitelinks",
                languages: str = "en|ru") -> dict[str, Any]:
    out: dict[str, Any] = {}
    ids = [i for i in dict.fromkeys(ids) if i]
    for i in range(0, len(ids), 50):
        chunk = ids[i:i + 50]
        data = http.get_json(WD_API, {
            "action": "wbgetentities", "ids": "|".join(chunk), "props": props, "languages": languages,
            "languagefallback": 1, "format": "json",
        })
        out.update(data.get("entities") or {})
    return out


def wiki_liturgics(http: Http, progress=lambda d, t: None) -> dict[tuple[int, int], str]:
    """Wikitext of all 366 '<Month> <day> (Eastern Orthodox liturgics)' pages,
    fetched 50 at a time."""
    from .wikical import page_title, parse_title
    days = [dt.date(REF_YEAR, 1, 1) + dt.timedelta(days=i) for i in range(366)]
    titles = [page_title(d.month, d.day) for d in days]
    out: dict[tuple[int, int], str] = {}
    for i in range(0, len(titles), 50):
        progress(i, len(titles))
        chunk = titles[i:i + 50]
        data = http.get_json("https://en.wikipedia.org/w/api.php", {
            "action": "query", "prop": "revisions", "rvprop": "content", "rvslots": "main",
            "titles": "|".join(chunk), "redirects": 1, "format": "json", "formatversion": 2,
        }, ttl=7 * DAY, timeout=90)
        for p in (data.get("query") or {}).get("pages") or []:
            md = parse_title(p.get("title", ""))
            revs = p.get("revisions") or []
            if md and revs:
                out[md] = ((revs[0].get("slots") or {}).get("main") or {}).get("content", "")
    progress(len(titles), len(titles))
    return out


def enwiki_qids(http: Http, titles: list[str], progress=lambda d, t: None) -> dict[str, str]:
    """English Wikipedia article titles -> Wikidata item ids, following redirects."""
    out: dict[str, str] = {}
    uniq = sorted({t for t in titles if t})
    for i in range(0, len(uniq), 50):
        progress(i, len(uniq))
        chunk = uniq[i:i + 50]
        data = http.get_json("https://en.wikipedia.org/w/api.php", {
            "action": "query", "titles": "|".join(chunk), "redirects": 1, "prop": "pageprops",
            "ppprop": "wikibase_item", "format": "json", "formatversion": 2,
        }, ttl=30 * DAY)
        q = data.get("query") or {}
        norm = {n["from"]: n["to"] for n in q.get("normalized") or []}
        redir = {r["from"]: r["to"] for r in q.get("redirects") or []}
        page_qid = {p.get("title"): (p.get("pageprops") or {}).get("wikibase_item", "")
                    for p in q.get("pages") or [] if not p.get("missing")}
        for t in chunk:
            n = norm.get(t, t)
            n = redir.get(n, n)
            if page_qid.get(n):
                out[t] = page_qid[n]
    progress(len(uniq), len(uniq))
    return out


def wiki_search_qids(http: Http, lang: str, query: str, limit: int = 5) -> list[str]:
    """Wikidata ids of the Wikipedia articles a full-text search finds, best
    first. Unlike Wikidata's own search this also finds other spellings that
    appear in the article or its redirects (Paknanas -> Michael Baknanas)."""
    q = re.sub(r"[\"'()\[\]{}:!^~*?\\/]", " ", query).strip()
    if not q:
        return []
    data = http.get_json(f"https://{lang}.wikipedia.org/w/api.php", {
        "action": "query", "generator": "search", "gsrsearch": q, "gsrlimit": limit, "gsrnamespace": 0,
        "prop": "pageprops", "ppprop": "wikibase_item", "redirects": 1, "format": "json", "formatversion": 2,
    }, ttl=30 * DAY)
    pages = sorted((data.get("query") or {}).get("pages") or [], key=lambda p: p.get("index", 99))
    return [p["pageprops"]["wikibase_item"] for p in pages if (p.get("pageprops") or {}).get("wikibase_item")]


def wiki_extract(http: Http, lang: str, title: str) -> tuple[str, str] | None:
    """(resolved title, plain-text article with '== headings ==')."""
    data = http.get_json(f"https://{lang}.wikipedia.org/w/api.php", {
        "action": "query", "prop": "extracts", "explaintext": 1, "exsectionformat": "wiki",
        "titles": title, "redirects": 1, "format": "json", "formatversion": 2,
    }, timeout=40)
    pages = (data.get("query") or {}).get("pages") or []
    for p in pages:
        if p.get("missing") or not p.get("extract"):
            continue
        return p.get("title", title), p["extract"]
    return None


# --------------------------------------------------------------- claims

GENDERS = {"Q6581097": "Male", "Q6581072": "Female", "Q2449503": "Male", "Q1052281": "Female",
           "Q16334295": "Group"}


def claim_ids(ent: dict, prop: str) -> list[str]:
    out = []
    for c in (ent.get("claims") or {}).get(prop, []):
        v = ((c.get("mainsnak") or {}).get("datavalue") or {}).get("value")
        if isinstance(v, dict) and v.get("id"):
            out.append(v["id"])
    return out


def claim_string(ent: dict, prop: str) -> str:
    for c in (ent.get("claims") or {}).get(prop, []):
        v = ((c.get("mainsnak") or {}).get("datavalue") or {}).get("value")
        if isinstance(v, str):
            return v
    return ""


_MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September",
           "October", "November", "December"]


def claim_time(ent: dict, prop: str) -> tuple[int, int, str] | None:
    """(year, precision, display) of the best-ranked time claim."""
    claims = (ent.get("claims") or {}).get(prop, [])
    claims = sorted(claims, key=lambda c: {"preferred": 0, "normal": 1}.get(c.get("rank"), 2))
    for c in claims:
        v = ((c.get("mainsnak") or {}).get("datavalue") or {}).get("value")
        if not isinstance(v, dict) or "time" not in v:
            continue
        m = re.match(r"([+-])(\d+)-(\d\d)-(\d\d)", v["time"])
        if not m:
            continue
        year = int(m.group(2)) * (-1 if m.group(1) == "-" else 1)
        if year == 0:
            continue
        prec = int(v.get("precision", 9))
        circa = any(q.get("datavalue", {}).get("value", {}).get("id") == "Q5727902"
                    for q in (c.get("qualifiers") or {}).get("P1480", []))
        mon, day = int(m.group(3)), int(m.group(4))
        era = " BC" if year < 0 else ""
        y = abs(year)
        if prec >= 11 and mon and day:
            disp = f"{day} {_MONTHS[mon - 1]} {y}{era}"
        elif prec == 10 and mon:
            disp = f"{_MONTHS[mon - 1]} {y}{era}"
        elif prec == 9:
            disp = f"{y}{era}"
        elif prec == 8:
            disp = f"{y // 10 * 10}s{era}"
        elif prec == 7:
            from .heuristics import century_label
            c_ = (y - 1) // 100 + 1
            disp = century_label(-c_ if year < 0 else c_)
        else:
            continue
        if circa:
            disp = "c. " + disp
        if prec >= 10 and str(v.get("calendarmodel", "")).endswith("Q1985786"):
            disp += " (O.S.)"        # Wikidata recorded the date on the Julian calendar
        return year, prec, disp
    return None


def label(ent: dict, lang: str = "en") -> str:
    return ((ent.get("labels") or {}).get(lang) or {}).get("value", "")


def description(ent: dict, lang: str = "en") -> str:
    return ((ent.get("descriptions") or {}).get(lang) or {}).get("value", "")


def aliases(ent: dict, lang: str = "en") -> list[str]:
    return [a.get("value", "") for a in (ent.get("aliases") or {}).get(lang, []) if a.get("value")]


def sitelinks(ent: dict) -> dict[str, str]:
    return {k: v.get("title", "") for k, v in (ent.get("sitelinks") or {}).items()
            if k.endswith("wiki") and not k.startswith(("commons", "species")) and "wikiquote" not in k}
