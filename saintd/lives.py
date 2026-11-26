"""Lives of the saints for entries the calendars give no Life for.

* Mystagogy Resource Center (John Sanidopoulos, johnsanidopoulos.com): a large
  English collection of Synaxarion entries and lives, especially of Greek saints
  and New Martyrs. Searched through Blogger's public JSON feed (no key).
* Azbuka Very saint pages (azbyka.ru/days/sv-...): short and full Russian lives
  of the saints of the Russian calendar, translated with the chosen translator.

Both are only fetched when a saint is opened in Focus, and are cached.
"""

from __future__ import annotations

import datetime as dt
import html as _html
import re
from difflib import SequenceMatcher

from .net import Http
from .text import STOPWORDS, _ending, fold, html_to_markdown

DAY = 86400

# ---------------------------------------------------------------- names

# descriptive words that do not identify a saint well enough to search on
EPITHETS = {
    "gardener", "farmer", "hermit", "recluse", "silent", "soldier", "physician", "merciful", "younger", "elder",
    "fool", "stylite", "faster", "sinner", "just", "less", "tsar", "monk", "nun", "abbot", "abbess",
    "presbyter", "deacon", "archdeacon", "bishop", "hieromonk", "hierodeacon", "canonarch", "virgin", "child",
    "infant", "son", "daughter", "wife", "husband", "brother", "sister", "mother", "father", "disciple",
    "founder", "builder", "shepherd", "warrior", "general", "commander", "senator", "tribune", "centurion",
    "governor", "magistrate", "priest", "reader", "subdeacon", "schemamonk", "schemanun", "archimandrite",
    "hegumen", "hegumena", "protopresbyter", "archpriest", "novice", "laywoman", "layman", "martyrdom",
    "sword", "fire", "beheaded", "stoned", "drowned", "others", "companions", "children", "sons",
    "daughters", "soldiers", "unknown", "anonymous", "together", "also", "named", "called", "surnamed",
    "known", "monastery", "caves", "lavra", "skete", "hermitage", "church", "city", "island", "mount",
    "mountain", "river", "desert", "wilderness", "saint", "holy", "new", "great", "martyr", "martyrs",
    "neomartyr", "hieromartyr", "venerable", "righteous", "blessed", "confessor", "wonderworker", "abba",
    "amma", "emperor", "empress", "king", "queen", "prince", "princess", "pope", "patriarch", "archbishop",
    "metropolitan", "apostle", "prophet", "evangelist", "first", "honoured", "honored", "near",
    "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "twelve", "forty", "fifty",
    "hundred", "thousand", "many", "fathers", "mothers", "virgins", "women", "men",
}


def _words(text: str) -> list[str]:
    text = re.sub(r"\([^)]*\)", " ", text or "")
    return re.findall(r"[A-Za-zÀ-ɏ][A-Za-zÀ-ɏ'\-]*", text)


def _key(word: str) -> str:
    return _ending(fold(word).replace("'", "").replace("-", ""))


def _is_title_word(word: str) -> bool:
    """'Venerable', 'Right-believing', 'Great-martyr', 'bishop'..."""
    parts = [x for x in fold(word).strip("-").split("-") if x]
    return not parts or all(x in STOPWORDS or x in EPITHETS for x in parts)


def roles(text: str) -> set[str]:
    """Rough kinds of saint named in a name or title: martyr, monastic,
    hierarch, royal, righteous."""
    t = fold(text)
    out = set()
    if re.search(r"martyr|passion-?bearer", t):
        out.add("martyr")
    if re.search(r"\b(venerable|ven|monk|nun|ascetic|hermit|recluse|abbot|abbess|hieromonk|hegumen|stylite|"
                 r"schemamonk|anchorite)\b", t):
        out.add("monastic")
    if re.search(r"\b(bishop|archbishop|metropolitan|patriarch|pope|hierarch|catholicos)\b", t):
        out.add("hierarch")
    if re.search(r"\b(prince|princess|king|queen|emperor|empress|tsar|tsarina|tsarevich|grand duke)\b", t):
        out.add("royal")
    if re.search(r"\brighteous\b", t):
        out.add("righteous")
    return out


def name_parts(name: str) -> tuple[str, list[str]]:
    """(first name, other identifying words) of a saint's name, e.g.
    'Michael Paknanas the Gardener' -> ('Michael', ['Paknanas'])."""
    words = [w for w in _words(name) if len(w) > 2 and not _is_title_word(w)]
    if not words:
        return "", []
    first, rest = words[0], [w for w in words[1:] if w[0].isupper()]
    return first, rest


def same_word(a: str, b: str) -> bool:
    """Do two words name the same thing, allowing for transliteration
    (Theodosius/Theodosios, Hesychius/Hesychios, Mikhail/Michael)?"""
    ka, kb = _key(a), _key(b)
    if not ka or not kb:
        return False
    if ka == kb:
        return True
    if ka[0] != kb[0] or min(len(ka), len(kb)) < 4:
        return False
    return SequenceMatcher(None, ka, kb).ratio() >= 0.8


def greek_form(word: str) -> str:
    """Latin name ending -> the Greek form Mystagogy often uses (Dionysius -> Dionysios)."""
    for a, b in (("ius", "ios"), ("aeus", "aios"), ("us", "os")):
        if word.lower().endswith(a) and len(word) > len(a) + 2:
            return word[: -len(a)] + b
    return word


# ---------------------------------------------------------------- mystagogy

MYST = "https://www.johnsanidopoulos.com"
MYST_FEED = MYST + "/feeds/posts/summary"

# posts about a saint that are not his or her life
_NOT_A_LIFE = re.compile(
    r"\b(saints and feasts|month of|resource page|homil\w*|sermon\w*|video\w*|photo\w*|documentary|"
    r"interview|encomium|panegyric|letter|poem|akathist|paraklesis|supplicatory|service|vigil|relics?|"
    r"reliquary|icons?|chapel|festival|procession|books?|review|lecture|podcast|audio|conference|quotes?|"
    r"prayers?|troparion|kontakion|apolytikion|canon|hymns?|liturgy|news|today|celebrat\w*|"
    r"skull|tomb|grave|feast of|synaxis|study|miracles?|vision|teachings?|sayings?|words? of|art|arts|"
    r"paintings?|fresco(e?s)?|iconography|film|movie|music|literature|poetry|novel|depictions?|portrait|"
    r"statue|mosaics?|exhibition|museum|pilgrimage|visit|anniversary|conference)\b", re.I)
_LIFE_START = re.compile(r"^(the\s+)?(synaxarion|life|lives|martyrdom|holy|saint|saints|st\.?|sts\.?|venerable|"
                         r"righteous|blessed|new\s+martyr|neomartyr|hieromartyr|martyrs?|virgin|prophet|apostle)\b",
                         re.I)


_ESSAY = re.compile(r"\(\s*\d+\s+of\s+\d+\s*\)|\bpart\s+(\d+|one|two|three|four|five|i+v?)\b|\bmessages?\b|"
                    r"\blessons?\b|\bsignificance\b|\bmeaning\b|\breflections?\b|\bintroduction\b|\?", re.I)
_LIFE_TITLE = re.compile(r"^(the\s+)?(life|lives|synaxarion|martyrdom|passion)\b", re.I)
# "... and the Child Who Was Lost", "... as a Response to ..." are stories or essays, not lives;
# "... and the 150 Soldiers With Him" is still a life
_CLAUSE = re.compile(r"\b(as an?|response|who|whom|how|why|what|when|where|whose|is|was|were|are|has|had|did|"
                     r"does|protects?|protected|saves?|saved|appears?|appeared|heals?|healed|helps?|helped|"
                     r"reveals?|revealed|visits?|visited|rescues?|rescued|returns?|returned|comes?|came|"
                     r"becomes?|became|sunday|lent|week|vespers|matins)\b|\s[-\u2013\u2014]\s|"
                     r"\band (the|his|her|its|their) (?!\d|(holy|other|martyrs?|soldiers|companions|disciples|"
                     r"brothers|sisters|children|sons|daughters|others|wife|husband|mother|father)\b)", re.I)
_PLACE_WORDS = {"of", "from", "in", "at", "near", "to"}


def _strip_attribution(title: str) -> str:
    """'There is No Christianity Without the Church (St. Hilarion Troitsky)' -> without the author."""
    return re.sub(r"\s*\([^)]*\)\s*$", "", title or "").strip()


def _feed_entries(data: dict) -> list[dict]:
    out = []
    for e in (data.get("feed") or {}).get("entry") or []:
        title = _html.unescape((e.get("title") or {}).get("$t", "")).strip()
        url = next((ln.get("href", "") for ln in e.get("link") or [] if ln.get("rel") == "alternate"), "")
        published = (e.get("published") or {}).get("$t", "")
        summary = (e.get("summary") or e.get("content") or {}).get("$t", "")
        if title and url.startswith(MYST):
            out.append({"title": title, "url": url, "published": published, "summary": summary})
    return out


def mystagogy_search(http: Http, query: str, *, ttl: float | None = 30 * DAY, limit: int = 40) -> list[dict]:
    data = http.get_json(MYST_FEED, {"alt": "json", "max-results": limit, "q": query}, ttl=ttl, timeout=30)
    return _feed_entries(data if isinstance(data, dict) else {})


def _near_feast(published: str, feasts: list[tuple[int, int]], days: int = 2) -> bool:
    try:
        d = dt.date.fromisoformat(published[:10])
    except ValueError:
        return False
    for m, dd in feasts:
        for year in (d.year - 1, d.year, d.year + 1):
            try:
                f = dt.date(year, m, min(dd, 28) if m == 2 and dd == 29 else dd)
            except ValueError:
                continue
            if abs((d - f).days) <= days:
                return True
    return False


def score_post(post: dict, first: str, others: list[str], feasts: list[tuple[int, int]],
               saint_roles: set[str] | None = None) -> float | None:
    """How well a post fits the saint; None if it is not a life of this saint."""
    if _ESSAY.search(post["title"]):
        return None
    title = _strip_attribution(post["title"])
    if _NOT_A_LIFE.search(title) and not _LIFE_TITLE.match(title):
        return None
    if _CLAUSE.search(title):
        return None
    words = _words(title)
    # the name must be a person's name in the title, not a place ("Martyrs of Melitene")
    if not any(same_word(first, w) and (i == 0 or words[i - 1].lower() not in _PLACE_WORDS)
               for i, w in enumerate(words)):
        return None
    theirs_roles = roles(title)
    if saint_roles and theirs_roles and not (saint_roles & theirs_roles):
        return None                           # Venerable George of Cyprus is not New Martyr George of Cyprus
    has_other = any(same_word(o, w) for o in others for w in words)
    near = _near_feast(post.get("published", ""), feasts)
    if others and not (has_other or near):
        return None
    if not others and not near:
        return None                           # a bare first name needs the feast day to agree
    if others and not has_other:
        # found by date alone: the title must not name another place or family
        _, theirs = name_parts(title)
        if any(not any(same_word(t, o) for o in others) for t in theirs if not same_word(t, first)):
            return None
    score = 3.0 * has_other + 2.0 * near
    if re.match(r"^(the\s+)?life\b", title, re.I):
        score += 2.0
    elif re.match(r"^(the\s+)?(synaxarion|martyrdom)\b", title, re.I):
        score += 1.5
    elif _LIFE_START.match(title):
        score += 1.0
    else:
        score -= 1.0                          # an essay that only mentions the saint
    return score


def name_variants(name: str) -> list[str]:
    """The name, plus a form using each alternative given in parentheses:
    'Martyr Publius (Poplion), by the sword' -> [..., 'Martyr Poplion, by the sword']."""
    out = [re.sub(r"\s*\([^)]*\)", "", name).strip()]
    for m in re.finditer(r"([A-Z][\w'-]+)\s*\(([A-Z][\w'-]+)\)", name):
        alt = name[:m.start()] + m.group(2) + name[m.end():]
        out.append(re.sub(r"\s*\([^)]*\)", "", alt).strip())
        # 'Luke (Mukhaidze)' is a surname: keep both
        out.append(re.sub(r"\s*\([^)]*\)", "", name[:m.end(1)] + " " + m.group(2) + name[m.end():]).strip())
    return list(dict.fromkeys(x for x in out if x))


MAX_QUERIES = 5


def mystagogy_find(http: Http, names: list[str], feasts: list[tuple[int, int]], *,
                   ttl: float | None = 30 * DAY) -> list[dict]:
    """Posts that are lives of the saint, best first (may be empty)."""
    tried: set[str] = set()
    plans: list[tuple[str, str, list[str]]] = []      # (query, first, others)
    late: list[tuple[str, str, list[str]]] = []
    saint_roles = roles(names[0]) if names else set()
    for name in [v for n in names for v in name_variants(n)]:
        first, others = name_parts(name)
        if not first:
            continue
        base = [first] + others[:1]
        plans.append((" ".join(base), first, others))
        g = [greek_form(w) for w in base]
        if g != base:
            plans.append((" ".join(g), first, others))
        if others:                                     # last resort: the first name and the feast day
            late.append((first, first, others))
            if greek_form(first) != first:
                late.append((greek_form(first), first, others))
    for q, first, others in plans + late:
        if len(tried) >= MAX_QUERIES:
            break
        if q.lower() in tried:
            continue
        tried.add(q.lower())
        hits = []
        for pos, post in enumerate(mystagogy_search(http, q, ttl=ttl)):
            sc = score_post(post, first, others, feasts, saint_roles)
            if sc is not None:
                hits.append((sc - pos * 0.02, post))
        if hits:
            hits.sort(key=lambda h: -h[0])
            return [p for _, p in hits]
    return []


def mystagogy_body(page: str) -> str:
    """The article HTML of a Blogger post page, cleaned (no images, styles or scripts)."""
    i = page.find("class='post-body entry-content'")
    if i < 0:
        i = page.find('class="post-body entry-content"')
    if i < 0:
        return ""
    i = page.find(">", i) + 1
    j = -1
    for marker in ("<div class='post-footer'", '<div class="post-footer"', "<div class='post-share-buttons",
                   "<div class='comments'"):
        k = page.find(marker, i)
        if k > 0 and (j < 0 or k < j):
            j = k
    body = page[i:j if j > 0 else i + 200_000]
    body = re.sub(r"<(script|style|noscript)\b.*?</\1>", "", body, flags=re.S | re.I)
    body = re.sub(r"<img\b[^>]*>", "", body, flags=re.I)
    body = re.sub(r"<a\b[^>]*>\s*</a>", "", body, flags=re.I)
    body = re.sub(r"\s(style|class|id|imageanchor|data-[\w-]+|border|height|width)=(\"[^\"]*\"|'[^']*')", "",
                  body)
    body = re.sub(r"(<br\s*/?>\s*){3,}", "<br /><br />", body, flags=re.I)
    return body.strip()[:80_000]


def mystagogy_post(http: Http, url: str, *, ttl: float | None = 30 * DAY) -> str:
    return mystagogy_body(http.get_text(url, ttl=ttl, timeout=40))


# ---------------------------------------------------------------- azbuka very

AZBYKA_DAYS = "https://azbyka.ru/days/"


def azbyka_page(http: Http, slug: str, *, ttl: float | None = 30 * DAY) -> str:
    return http.get_text(AZBYKA_DAYS + slug, ttl=ttl, timeout=40)


def _paras(fragment: str) -> list[str]:
    md = html_to_markdown(fragment)
    out = []
    for p in re.split(r"\n\s*\n", md):
        p = re.sub(r"\s+", " ", p.replace("*", "")).strip()
        if p and not p.startswith("Источник:") and p not in ("Развернуть", "Свернуть"):
            out.append(p)
    return out


def azbyka_life(page: str) -> tuple[str, list[str]] | None:
    """(one-paragraph summary, paragraphs of the life) in Russian, from an
    Azbuka Very saint page; None if the page has no life. When the page has
    both a short and a full life, the short one is returned."""
    i = page.find('class="block saint-description"')
    if i < 0:
        return None
    j = page.find('<div class="block ', i + 20)
    k = page.find("Жития и книги в библиотеке", i)
    end = min(x for x in (j, k, i + 300_000) if x > 0)
    blk = page[i:end]
    blk = re.sub(r"<(script|style)\b.*?</\1>", "", blk, flags=re.S | re.I)
    blk = re.sub(r'<div class="read-more">.*?</div>', "", blk, flags=re.S)
    summary = ""
    m = re.search(r'<p class="short-description">(.*?)</p>', blk, re.S)
    if m:
        summary = " ".join(_paras(m.group(1)))
        blk = blk[:m.start()] + blk[m.end():]
    b = blk.find('class="brif')
    life_html = blk[blk.find(">", b) + 1:] if b >= 0 else ""
    heads = list(re.finditer(r"<h3[^>]*>(.*?)</h3>", life_html, re.S))
    if len(heads) >= 2 and "Кратк" in heads[0].group(1) and "Полн" in heads[1].group(1):
        life_html = life_html[heads[0].end():heads[1].start()]
    elif heads and "Кратк" in heads[0].group(1):
        life_html = life_html[heads[0].end():]
    life = _paras(re.sub(r"<h3[^>]*>.*?</h3>", "", life_html, flags=re.S))
    if not summary and not life:
        return None
    if summary and life and life[0][:80] == summary[:80]:
        summary = ""
    return summary, life


def cap_paragraphs(paras: list[str], limit: int) -> tuple[list[str], bool]:
    """Whole paragraphs up to `limit` characters; True if some were left out."""
    out, n = [], 0
    for p in paras:
        if out and n + len(p) > limit:
            return out, True
        out.append(p)
        n += len(p)
    return out, False
