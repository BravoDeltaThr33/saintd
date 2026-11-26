"""OrthodoxWiki (orthodoxwiki.org): an Orthodox encyclopedia of about 5,000
articles, many of them on saints, with their hymns and icons. Used for the
History section when Wikipedia has no article, and always listed in Sources
when it has one. Text: GFDL / CC BY-SA 2.5.
"""

from __future__ import annotations

import re
from urllib.parse import quote

from .htc import _score
from .lives import name_parts
from .net import Http

API = "https://orthodoxwiki.org/api.php"
SITE = "https://orthodoxwiki.org/"
DAY = 86400

SKIP = {"external links", "external link", "source", "sources", "bibliography", "references", "notes", "see also",
        "children", "icons", "gallery", "further reading", "footnotes", "succession", "preceded by", "links"}
_TITLE_STRIP = re.compile(r"\b(St\.?|Saint|Saints|Sts\.?|Holy|Venerable|Ven\.?|Blessed|Righteous|Martyr|Hieromartyr|"
                          r"New Martyr|Great Martyr|Greatmartyr|Great-martyr|Prophet|Apostle)\b\s*", re.I)


def page_url(title: str) -> str:
    return SITE + quote(title.replace(" ", "_"), safe="()_,'-:./")


def prefix_titles(http: Http, prefix: str, *, ttl: float | None = 30 * DAY, limit: int = 20) -> list[str]:
    prefix = prefix.strip()
    if len(prefix) < 3:
        return []
    data = http.get_json(API, {"action": "query", "list": "prefixsearch", "pssearch": prefix, "pslimit": limit,
                               "psnamespace": 0, "format": "json"}, ttl=ttl, timeout=20)
    return [p["title"] for p in ((data or {}).get("query") or {}).get("prefixsearch") or [] if p.get("title")]


def find_title(http: Http, names: list[str], *, ttl: float | None = 30 * DAY) -> str | None:
    """The OrthodoxWiki article about the saint called `names[0]` (other
    names are alternatives such as the Wikidata label)."""
    tried: set[str] = set()
    best, best_score = None, 2.49
    plains: list[str] = []
    firsts: list[str] = []
    for n in names:
        plain = _TITLE_STRIP.sub("", re.sub(r"\([^)]*\)", " ", n)).strip(" ,")
        plain = re.sub(r",.*$", "", plain).strip()          # "Artemon, presbyter of Laodicea" -> "Artemon"
        if plain:
            plains.append(plain)
        first, _ = name_parts(n)
        if first:
            firsts.append(first)
    known = {w.lower() for n in names for w in re.findall(r"[A-Za-zÀ-ɏ'-]+", n)}
    for q in plains + firsts:                 # the most specific names first
        if q.lower() in tried or len(tried) >= 3:
            continue
        tried.add(q.lower())
        for title in prefix_titles(http, q, ttl=ttl):
            if re.search(r"\b(Church|Cathedral|Monastery|Diocese|Parish|disambiguation|Archdiocese|Seminary)\b", title):
                continue
            sc = max(_score(n, title) for n in names)
            if sc <= 0:
                continue
            if title.lower() in (p.lower() for p in plains):
                sc += 2.0                       # the exact name
            # names the saint doesn't have ("Ignatius III Atiyah of Antioch")
            extra = [w for w in re.findall(r"[A-Za-zÀ-ɏ'-]+", title)
                     if (w[0].isupper() or re.fullmatch(r"[IVX]+", w)) and w.lower() not in known
                     and w.lower() not in ("of", "the", "and", "st", "saint")]
            sc -= 0.75 * len(extra)
            if sc > best_score:
                best, best_score = title, sc
        if best:
            break
    return best


def fetch_article(http: Http, title: str, *, ttl: float | None = 30 * DAY) -> tuple[str, str, str] | None:
    """(title, article as HTML ready for Markdown conversion, first image URL)."""
    data = http.get_json(API, {"action": "parse", "page": title, "prop": "text", "redirects": 1,
                               "disableeditsection": 1, "disabletoc": 1, "format": "json", "formatversion": 2},
                         ttl=ttl, timeout=30)
    p = (data or {}).get("parse") or {}
    html = p.get("text") or ""
    if not html:
        return None
    img = ""
    m = re.search(r'<img[^>]+src="(https://commons\.orthodoxwiki\.org/images/[^"]+)"', html)
    if m:
        img = m.group(1)
    return p.get("title", title), clean_html(html), img


def clean_html(html: str) -> str:
    """Drop the wiki furniture: images, tables of contents, info boxes,
    references and link sections."""
    h = re.sub(r"<figure\b.*?</figure>", "", html, flags=re.S | re.I)
    h = re.sub(r'<div[^>]*class="[^"]*\b(toc|thumb|navbox|gallery|references?)\b[^"]*"[^>]*>.*?</div>\s*', "", h,
               flags=re.S | re.I)
    h = re.sub(r"<table\b.*?</table>", "", h, flags=re.S | re.I)
    h = re.sub(r'<sup[^>]*class="[^"]*reference[^"]*"[^>]*>.*?</sup>', "", h, flags=re.S | re.I)
    h = re.sub(r'<ul class="gallery.*?</ul>', "", h, flags=re.S | re.I)
    h = re.sub(r"<!--.*?-->", "", h, flags=re.S)
    # cut sections we never show
    parts = re.split(r"(<h[2-4][^>]*>.*?</h[2-4]>)", h, flags=re.S | re.I)
    out, skipping, skip_level = [], False, 9
    for part in parts:
        hm = re.match(r"<h([2-4])[^>]*>(.*?)</h[2-4]>", part, re.S | re.I)
        if hm:
            level = int(hm.group(1))
            name = re.sub(r"<[^>]+>", "", hm.group(2)).strip().lower()
            if skipping and level > skip_level:
                continue
            skipping = name in SKIP
            skip_level = level if skipping else 9
            if skipping:
                continue
        elif skipping:
            continue
        out.append(part)
    return "".join(out)
