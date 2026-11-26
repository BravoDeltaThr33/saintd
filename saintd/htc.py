"""The Orthodox Calendar of Holy Trinity Russian Orthodox Church (Baltimore,
Moscow Patriarchate): English lives of the saints (translated by Fr. S. Janos)
and the troparia and kontakia of the day.

The parish documents server-side use of its calendar script for embedding the
calendar in other sites ("For Webmasters"). saintd uses it only for the day of
a saint you open, caches every answer and never downloads the calendar in bulk.
"""

from __future__ import annotations

import datetime as dt
import html as _html
import re
from dataclasses import dataclass, field

from .lives import name_parts, roles, same_word
from .net import Http

CALENDAR = "https://www.holytrinityorthodox.com/calendar/calendar.php"
SITE = "https://www.holytrinityorthodox.com"
ENC = "windows-1251"
DAY = 86400
MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
          "November", "December"]


@dataclass
class Entry:
    text: str                 # "Venerable Longinus the Gate-keeper of the Kiev Caves (13th c.)."
    life_url: str = ""        # https://www.holytrinityorthodox.com/calendar/los/October/16-02.htm
    sign: str = ""            # typikon sign image code (1.gif -> "1")
    minor: bool = False


@dataclass
class Hymn:
    who: str                  # "Holy Martyr Longinus" ("" when only a role is named)
    kind: str                 # Troparion | Kontakion | ...
    tone: str                 # "IV"
    text: str
    of_role: str = ""         # "hierarch" in "Kontakion of the hierarch"


@dataclass
class Day:
    month: int
    day: int
    header: str = ""
    entries: list[Entry] = field(default_factory=list)
    hymns: list[Hymn] = field(default_factory=list)


def civil_for(month: int, day: int, year: int | None = None) -> dt.date:
    """The civil date on which the Old (Julian) Calendar keeps church date month/day;
    the Holy Trinity calendar is addressed by civil date."""
    y = year or dt.date.today().year
    for yy in (y, y + 1, y + 2, y + 3):
        try:
            return dt.date(yy, month, day) + dt.timedelta(days=13)
        except ValueError:            # 29 February
            continue
    return dt.date(2028, month, day) + dt.timedelta(days=13)


def fetch_day(http: Http, month: int, day: int, *, ttl: float | None = 30 * DAY) -> Day:
    c = civil_for(month, day)
    page = http.get_text(CALENDAR, {"month": c.month, "today": c.day, "year": c.year, "dt": 1, "header": 1,
                                    "lives": 1, "trp": 1, "scripture": 0},
                         ttl=ttl, timeout=30, encoding=ENC)
    return parse_day(page, month, day)


def _clean(fragment: str) -> str:
    t = re.sub(r"<br\s*/?>", "\n", fragment, flags=re.I)
    t = re.sub(r"<[^>]+>", "", t)
    t = _html.unescape(t).replace("\xad", "")
    t = re.sub(r"[ \t\r]+", " ", t)
    t = re.sub(r" *\n *", "\n", t)
    return t.strip()


_ENTRY = re.compile(r'<img[^>]*jcal_img/(\w+)\.gif"[^>]*>(.*?)<br\s*/?>', re.S | re.I)
_LIFE = re.compile(r'href="(https?://www\.holytrinityorthodox\.com/calendar/los/[^"]+)"', re.I)
_HYMN_P = re.compile(r"<p>\s*<b>(.*?)</b>(.*?)</p>", re.S | re.I)
_KINDS = r"Troparion|Kontakion|Ikos|Exapostilarion|Megalynarion|Prokeimenon|Sessional Hymn|Hypakoe"
_HEAD = re.compile(rf"^(?P<who>.*?)[,\s]*\b(?P<kind>{_KINDS})\b(?P<rest>.*)$", re.I | re.S)


def parse_day(page: str, month: int = 0, day: int = 0) -> Day:
    out = Day(month, day)
    m = re.search(r'class="headerheader">(.*?)</span>\s*</p>', page, re.S)
    if m:
        out.header = re.sub(r"\s+", " ", _clean(m.group(1)))
    tro = page.find('class="troparionheader"')
    saints_part = page[:tro] if tro > 0 else page
    for sign, body in _ENTRY.findall(saints_part):
        link = _LIFE.search(body)
        text = re.sub(r"\s+", " ", _clean(body))
        if not text:
            continue
        out.entries.append(Entry(text=text, life_url=link.group(1).replace("http://", "https://") if link else "",
                                 sign=sign, minor="minortext" in body))
    if tro > 0:
        for head, body in _HYMN_P.findall(page[tro:]):
            h = re.sub(r"\s+", " ", _clean(head)).strip(" —-:")
            text = _clean(body)
            hm = _HEAD.match(h)
            if not hm or not text:
                continue
            who = hm.group("who").strip(" ,")
            rest = hm.group("rest")
            tone = ""
            tm = re.search(r"Tone\s+([IVX]+|\d+)", rest, re.I)
            if tm:
                tone = tm.group(1).upper()
            of_role = ""
            om = re.match(r"\s*of\s+(?:the\s+)?([\w\s-]+?)(?:,|\s+Tone|$)", rest, re.I)
            if om:
                of_role = om.group(1).strip().lower()
            out.hymns.append(Hymn(who=who, kind=hm.group("kind").title(), tone=tone,
                                  text=_poetry(text), of_role=of_role))
    return out


def _poetry(text: str) -> str:
    """Hymn text: join the page's hard-wrapped lines; keep the / and // phrase marks."""
    return re.sub(r"\s*\n\s*", " ", text).strip()


# ---------------------------------------------------------------- matching

# words that describe many saints and so tell nobody apart
_COMMON = {"martyr", "martyrs", "venerable", "saint", "saints", "holy", "blessed", "righteous", "bishop",
           "archbishop", "metropolitan", "patriarch", "monk", "nun", "priest", "presbyter", "deacon",
           "confessor", "wonderworker", "abbot", "abbess", "hieromartyr", "virgin", "great", "new", "father",
           "mother", "relics", "repose", "uncovering", "translation", "finding", "second", "first", "those",
           "with", "them", "their", "who", "the", "and", "of", "in", "at", "by", "from", "his", "her"}


def _words(text: str) -> list[str]:
    return re.findall(r"[A-Za-zÀ-ɏ'-]+", re.sub(r"\([^)]*\)", " ", text))


def _score(saint_name: str, text: str) -> float:
    """How well a calendar line names the saint (below 2 = not this saint).
    Both lists are for the same day, so a shared name with one more shared
    detail is strong evidence; a difference in rank only counts against it
    (calendars disagree: Holy Trinity calls Longinus the Centurion "Venerable")."""
    first, others = name_parts(saint_name)
    if not first:
        return 0.0
    their_first, theirs = name_parts(text)
    words = _words(text)
    if not any(same_word(first, w) for w in words):
        return 0.0
    score = 1.0 + (1.0 if their_first and same_word(first, their_first) else 0.0)
    shared = sum(1 for o in others if any(same_word(o, w) for w in words))
    score += 1.5 * shared
    # descriptive words such as "Centurion" or "Gate-keeper"
    mine_desc = {w.lower() for w in _words(saint_name)
                 if len(w) > 3 and w.lower() not in _COMMON and not same_word(w, first)
                 and not any(same_word(w, o) for o in others)}
    score += 1.0 * sum(1 for d in mine_desc if any(same_word(d, w) for w in words))
    if others and theirs and not shared:
        score -= 1.5                  # names another place or family
    elif theirs and not others and not mine_desc & {w.lower() for w in words}:
        score -= 0.5                  # more specific than we are: likely a namesake
    mine_roles, their_roles = roles(saint_name), roles(text)
    if mine_roles and their_roles and not (mine_roles & their_roles):
        score -= 1.0
    return score


def match_entry(saint_name: str, entries: list[Entry]) -> Entry | None:
    scored = [(_score(saint_name, e.text), e) for e in entries]
    scored = [(sc, e) for sc, e in scored if sc > 0]
    if not scored:
        return None
    sc, best = max(scored, key=lambda x: x[0])
    if sc >= 2.0:
        return best
    # a short name ("Venerable Gall") is enough when nobody else that day shares it
    if sc >= 1.5 and len(scored) == 1:
        return best
    return None


_SIGN_RANK = {"7": 7, "6": 6, "5": 5, "4": 4, "3": 3, "2": 2, "1": 1, "0": 0, "o": -1}


def principal(entries: list[Entry]) -> Entry | None:
    """The day's chief commemoration (highest typikon sign)."""
    ranked = [e for e in entries if not e.text.lower().startswith(("forefeast", "afterfeast"))]
    if not ranked:
        return None
    return max(ranked, key=lambda e: (_SIGN_RANK.get(e.sign, -1), -entries.index(e)))


def hymns_for(saint_name: str, hymns: list[Hymn], entries: list[Entry] | None = None) -> list[Hymn]:
    """The troparion/kontakion of this saint among the day's hymns. A hymn
    that names nobody belongs to the saint of the hymn before it, or the one
    whose rank it names ("Kontakion of the hierarch"), or else to the day's
    chief saint."""
    chief = principal(entries or [])
    owners: list[str] = []
    named: list[str] = []
    for h in hymns:
        if h.who:
            owners.append(h.who)
            named.append(h.who)
            continue
        owner = ""
        if h.of_role:
            want = _role_word(h.of_role)
            for w in reversed(named):
                if h.of_role in w.lower() or (want and want & roles(w)):
                    owner = w
                    break
        if not owner and named:
            owner = named[-1]
        if not owner and chief:
            owner = chief.text
        owners.append(owner)
    return [h for h, owner in zip(hymns, owners) if owner and _score(saint_name, owner) >= 2.0]


def _role_word(word: str) -> set[str]:
    w = word.lower()
    if w.startswith("hierarch") or "bishop" in w:
        return {"hierarch"}
    if "martyr" in w:
        return {"martyr"}
    if w.startswith(("venerable", "monk", "nun")):
        return {"monastic"}
    if w.startswith("righteous"):
        return {"righteous"}
    return set()


# ---------------------------------------------------------------- lives

def fetch_life(http: Http, url: str, *, ttl: float | None = 90 * DAY) -> tuple[str, str, str] | None:
    """(title, life as HTML paragraphs, translator credit) from a life page."""
    page = http.get_text(url, ttl=ttl, timeout=30, encoding=ENC)
    return parse_life(page)


def parse_life(page: str) -> tuple[str, str, str] | None:
    m = re.search(r'<p class="header12">(.*?)</p>', page, re.S | re.I)
    title = re.sub(r"\s+", " ", _clean(m.group(1))) if m else ""
    paras: list[str] = []
    credit = ""
    for body in re.findall(r'<p class="body10">(.*?)</p>', page, re.S | re.I):
        # the source is hard-wrapped: only <br> separates paragraphs
        body = re.sub(r"[\r\n]+", " ", body)
        text = _clean(re.sub(r"&nbsp;", " ", body, flags=re.I))
        if not text or re.match(r"^Commemorated on\b", text):
            continue
        for part in text.split("\n"):
            part = re.sub(r"\s+", " ", part).strip()
            if not part or part.lower() in ("close window",):
                continue
            if part.startswith("©") or part.lower().startswith("(c)"):
                credit = part
                continue
            paras.append(part)
    if not paras:
        return None
    html = "".join(f"<p>{_html.escape(p)}</p>" for p in paras)
    return title, html, credit
