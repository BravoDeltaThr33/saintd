"""Parser for Wikipedia's "<Month> <day> (Eastern Orthodox liturgics)" pages.

Each of the 366 pages lists that day's commemorations from the Great
Synaxaristes, the Russian calendar and the Latin saints of the undivided
Church, usually linking each saint to their own Wikipedia article."""

from __future__ import annotations

import html
import re
from dataclasses import dataclass, field

from . import heuristics as H
from .text import fold

MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September",
          "October", "November", "December"]


def page_title(month: int, day: int) -> str:
    return f"{MONTHS[month - 1]} {day} (Eastern Orthodox liturgics)"


def parse_title(title: str) -> tuple[int, int] | None:
    m = re.match(r"^(\w+) (\d{1,2}) \(Eastern Orthodox liturgics\)$", title or "")
    if not m or m.group(1) not in MONTHS:
        return None
    return MONTHS.index(m.group(1)) + 1, int(m.group(2))


@dataclass
class Entry:
    section: str            # saints | western | post | newmartyr | other
    head: str               # the name part, e.g. "Saint Florentius of Orange"
    year: str               # "(c. 526)" style parenthetical with the date, or ""
    text: str               # the whole line in plain text
    notes: list[str] = field(default_factory=list)
    link: str = ""          # Wikipedia article about this saint, if linked
    major: bool = False     # printed in bold on the page
    foreign: tuple[str, str] | None = None   # (language, title) of a non-English article

    @property
    def title(self) -> str:
        """Name plus date, the form the rest of the app's heuristics expect."""
        return f"{self.head} ({self.year})" if self.year else self.head


# ---------------------------------------------------------------- sections

_STOP_SECTIONS = re.compile(r"icon gallery|gallery|notes|references|sources|see also|external links|"
                            r"further reading|bibliography|footnotes|^links$", re.I)


def section_kind(heading: str) -> str | None:
    h = fold(heading).strip(" =")
    if _STOP_SECTIONS.search(h):
        return None
    if "new mart" in h or "confessor" in h:
        return "newmartyr"
    if "western" in h or "pre-schism" in h or "latin" in h:
        return "western"
    if "post-schism" in h or "post schism" in h:
        return "post"
    if "other" in h or "commemoration" in h or "feast" in h or h.startswith("icon"):
        return "other"
    return "saints"


# ---------------------------------------------------------------- wikitext

def _balanced(s: str, start: int, open_: str = "{{", close: str = "}}") -> int:
    """Index just past the construct opening at `start` (nesting aware), or -1."""
    depth, i = 0, start
    while i < len(s):
        if s.startswith(open_, i):
            depth += 1
            i += len(open_)
        elif s.startswith(close, i):
            depth -= 1
            i += len(close)
            if depth == 0:
                return i
        else:
            i += 1
    return -1


def _top_level_split(s: str, sep: str) -> list[str]:
    """Split on `sep` outside of {{...}} and [[...]]."""
    out, depth, cur, i = [], 0, [], 0
    while i < len(s):
        two = s[i:i + 2]
        if two in ("{{", "[["):
            depth += 1
            cur.append(two)
            i += 2
            continue
        if two in ("}}", "]]"):
            depth = max(0, depth - 1)
            cur.append(two)
            i += 2
            continue
        if depth == 0 and s.startswith(sep, i):
            out.append("".join(cur))
            cur = []
            i += len(sep)
            continue
        cur.append(s[i])
        i += 1
    out.append("".join(cur))
    return out


_REF_PAIR = re.compile(r"<ref\b[^>/]*>.*?</ref\s*>", re.S | re.I)
_REF_SELF = re.compile(r"<ref\b[^>]*/>", re.I)


_NOTE_START = re.compile(r"\{\{\s*(?:#tag:ref|efn)\s*\|", re.I)


def _note_body(template: str) -> str:
    """The text of a {{#tag:ref|...}} or {{efn|...}} footnote."""
    inner = template[2:-2]
    parts = _top_level_split(inner, "|")[1:]
    keep = [p for p in parts if not re.match(r"\s*(group|name)\s*=", p)]
    return "|".join(keep)


def extract_notes(line: str) -> tuple[str, list[str]]:
    """Remove footnotes ({{#tag:ref|...}}, {{efn|...}}) returning them as text."""
    notes = []
    while True:
        m = _NOTE_START.search(line)
        if not m:
            break
        i = m.start()
        j = _balanced(line, i)
        if j < 0:
            line = line[:i]
            break
        notes.append(_note_body(line[i:j]))
        line = line[:i] + line[j:]
    return line, notes


def _params(inner: str) -> tuple[str, list[str], dict[str, str]]:
    parts = _top_level_split(inner, "|")
    name = parts[0].strip().lower()
    pos, named = [], {}
    for p in parts[1:]:
        m = re.match(r"\s*([\w-]+)\s*=(.*)$", p, re.S)
        if m and not re.match(r"^\s*\d", p):
            named[m.group(1).strip().lower()] = m.group(2).strip()
        else:
            pos.append(p.strip())
    return name, pos, named


def _expand(name: str, pos: list[str], named: dict[str, str]) -> str:
    if name in ("ill", "interlanguage link", "interlanguage link multi", "ill2"):
        return named.get("lt") or (pos[0] if pos else "")
    if name in ("circa", "c.", "ca"):
        return "c. " + (pos[0] if pos else "")
    if name in ("nobr", "nowrap", "midsize", "small", "nobreak", "ndash"):
        return pos[0] if pos else ("\u2013" if name == "ndash" else "")
    if name in ("nbsp",):
        return " "
    if name == "!":
        return "|"
    return ""


def strip_templates(s: str) -> str:
    """Expand the few templates that carry visible text; drop the rest."""
    out, pos = [], 0
    while True:
        i = s.find("{{", pos)
        if i < 0:
            out.append(s[pos:])
            break
        j = _balanced(s, i)
        out.append(s[pos:i])
        if j < 0:
            break
        name, args, named = _params(s[i + 2:j - 2])
        args = [strip_templates(a) for a in args]
        named = {k: strip_templates(v) for k, v in named.items()}
        out.append(_expand(name, args, named))
        pos = j
    return "".join(out)


def foreign_links(s: str) -> list[tuple[str, str, str]]:
    """(english name, language, foreign title) from {{ill|...}} links."""
    out = []
    for m in re.finditer(r"\{\{\s*(?:ill|interlanguage link)\s*\|", s, re.I):
        j = _balanced(s, m.start())
        if j < 0:
            continue
        _, pos, named = _params(s[m.start() + 2:j - 2])
        if len(pos) >= 2:
            lang = pos[1].strip().lower()
            title = pos[2].strip() if len(pos) >= 3 else pos[0].strip()
            if re.fullmatch(r"[a-z]{2,3}", lang):
                out.append((plain(named.get("lt") or pos[0]), lang, title))
    return out


_LINK = re.compile(r"\[\[([^\[\]|]+)(?:\|([^\[\]]*))?\]\]")
_EXT = re.compile(r"\[(?:https?:)?//[^\s\]]+(?:\s+([^\]]*))?\]")


def links_in(s: str) -> list[tuple[str, str]]:
    """(target, label) of each internal link, in order."""
    out = []
    for m in _LINK.finditer(s):
        target = m.group(1).strip()
        if re.match(r"(?i)(file|image|category|media):", target):
            continue
        label = (m.group(2) if m.group(2) is not None else target).strip()
        out.append((target.split("#")[0].strip(), plain(label)))
    return out


def plain(s: str) -> str:
    """Wikitext fragment -> plain text."""
    s = re.sub(r"<!--.*?-->", "", s, flags=re.S)
    s = _REF_PAIR.sub("", s)
    s = _REF_SELF.sub("", s)
    s = re.sub(r"<small>.*?</small>", "", s, flags=re.S | re.I)
    s = strip_templates(s)
    s = re.sub(r"\[\[(?:File|Image|Category|Media):[^\]]*\]\]", "", s, flags=re.I)
    s = _LINK.sub(lambda m: m.group(2) if m.group(2) is not None else m.group(1), s)
    s = _EXT.sub(lambda m: m.group(1) or "", s)
    s = re.sub(r"<br\s*/?>", " ", s, flags=re.I)
    s = re.sub(r"</?[a-z][^>]*>", "", s, flags=re.I)
    s = s.replace("'''", "").replace("''", "")
    s = html.unescape(s).replace(" ", " ")
    s = re.sub(r"\s+", " ", s)
    s = re.sub(r"\s+([,.;:)])", r"\1", s)
    s = re.sub(r"\(\s+", "(", s)
    return s.strip(" *")


# ---------------------------------------------------------------- the name

_GENERIC_LINK = re.compile(
    r"(?i)^(saints?|martyrs?|martyrdom|hieromartyrs?|great ?martyrs?|new ?martyrs?.*|neomartyrs?|venerable|"
    r"righteous|blessed|prophets?|prophetess|apostles?|evangelists?|confessors?|wonder-?workers?|"
    r"fool[- ]for[- ]christ|holy fool|unmercenar.*|holy unmercenaries|anargyr.*|equal[- ]to[- ](the[- ])?apostles|"
    r"hierarchs?|bishops?|archbishops?|metropolitans?|patriarchs?|pope|catholicos|abbots?|abbess|hegumen|"
    r"archimandrite|hieromonks?|monks?|nuns?|monasticism|deacons?|deaconess|archdeacon|priests?|presbyters?|"
    r"protopresbyter|elders?|starets|startsy|stylites?|hermits?|recluses?|anchorites?|ascetics?|"
    r"queen( consort)?|kings?|princes?|princess(es)?|emperors?|empress|tsar(ina)?|tsaritsa|grand prince|"
    r"translation.*|relics?|synaxis|synaxarium|synaxarion|icons?|theotokos|virgin mary|myrrh.*|"
    r"passion-?bearers?|holy fathers|desert fathers|church fathers|christian monasticism|lavra|"
    r"repose|dormition|canonization|glorification|iconoclasm|iconoclasts?|orthodoxy|pentarchy|"
    r"exarch|eparchy|diocese|archdiocese|metropolis|skete|hesychasm|hesychast|"
    r"martyrs of .*|new martyrs and confessors.*|.* \(eastern orthodox liturgics\)|eastern orthodox.*|"
    r"list of .*|.* \(country\)|bishop of .*|archbishop of .*|metropolitan of .*|patriarch of .*|"
    r"patriarchate of .*|.* monastery|monastery of .*|.* lavra|church of .*|cathedral of .*|"
    r"roman emperor|byzantine empire|roman empire|ottoman empire|great persecution|"
    r"persecution of christians.*|.*persecution.*|soviet union|bolsheviks?|red army)$")


def _is_generic(target: str, label: str) -> bool:
    t = target.replace("_", " ").strip()
    if _GENERIC_LINK.match(t) or _GENERIC_LINK.match(label):
        return True
    lab = label.strip()
    if lab in H._GAZ or t in H._GAZ:          # a place
        return True
    if re.fullmatch(r"\d{1,4}( BC| AD)?|\d+(st|nd|rd|th) century", lab):
        return True
    return False


def _clauses(text: str) -> list[str]:
    """Split on ", " outside parentheses and quotation marks."""
    parts, cur, depth, quote = [], [], 0, False
    i = 0
    while i < len(text):
        ch = text[i]
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth = max(0, depth - 1)
        elif ch in "\"\u201c\u201d":
            quote = not quote if ch == '"' else (ch == "\u201c")
        if ch == "," and depth == 0 and not quote and text[i + 1:i + 2] == " ":
            parts.append("".join(cur))
            cur = []
            i += 2
            continue
        cur.append(ch)
        i += 1
    parts.append("".join(cur))
    return [p.strip() for p in parts if p.strip()]


def _single_name(head: str) -> bool:
    core = re.sub(r"\([^)]*\)", "", H.core_name(head)).strip()
    return bool(core) and len(core.split()) == 1


def split_head(text: str) -> str:
    """The name part of an entry's plain text: the first clause plus following
    clauses that are themselves names or titles (start with a capital). A bare
    single name keeps its first description so namesakes stay apart."""
    parts = _clauses(text)
    if not parts:
        return ""
    head = re.split(r"\s+(?:who|which|whose|whom)\s+", parts[0])[0]
    if head != parts[0]:
        return head.strip(" .;:")
    for p in parts[1:4]:
        if not p[0].isupper() or re.match(r"(?:The|He|She|They|It|Who|Born|Called|One|A|An|In|At|On)\b", p):
            break
        if len(head) + len(p) > 140:
            break
        head = f"{head}, {p}"
    if _single_name(head) and len(parts) > len(_clauses(head)):
        nxt = parts[len(_clauses(head))]
        nxt = re.split(r"\s+(?:and|who|which|where|whose)\s+|;", nxt)[0]
        if len(nxt) > 60:
            nxt = nxt[:60].rsplit(" ", 1)[0]
        if nxt and not re.match(r"(?:he|she|they|it|who)\b", nxt):
            head = f"{head}, {nxt}"
    return head.strip(" .;:")


_YEAR = re.compile(r"\((?:[^()]*?)(?:\d{2,4}|\d+(?:st|nd|rd|th) c(?:entury|\.)?)[^()]*\)")


def year_part(text: str) -> str:
    """The last parenthetical holding a date, e.g. 'c. 526' or '4th century'."""
    found = ""
    for m in _YEAR.finditer(text):
        inner = m.group(0)[1:-1].strip()
        if re.search(r"\b(see also|OS|NS|O\.S\.|N\.S\.)\b", inner):
            continue
        found = inner
    return found


def choose_link(head: str, links: list[tuple[str, str]]) -> str:
    """The link that names the saint: inside the name part, not a title or a
    place, and containing the saint's first name."""
    cand = [(t, lab) for t, lab in links if lab and lab in head and not _is_generic(t, lab)]
    if not cand:
        return ""
    core = H.core_name(head)
    fn = fold(H.first_name(core))[:4]
    for t, lab in cand:
        if fn and (fn in fold(lab) or fn in fold(t)):
            return t
    lead = fold(core)[:6]
    for t, lab in cand:
        if lead and fold(lab).startswith(lead[:5]):
            return t
    return ""


def _lift_notes(text: str) -> tuple[str, list[str]]:
    """Replace every {{#tag:ref|...}} footnote (which may span lines) with a
    one-character placeholder, returning the note bodies."""
    notes: list[str] = []
    out, pos = [], 0
    while True:
        m = _NOTE_START.search(text, pos)
        if not m:
            out.append(text[pos:])
            break
        i = m.start()
        j = _balanced(text, i)
        if j < 0:
            out.append(text[pos:i])
            break
        out.append(text[pos:i])
        out.append(f"\x00{len(notes)}\x00")
        notes.append(_note_body(text[i:j]))
        pos = j
    return "".join(out), notes


_PLACEHOLDER = re.compile(r"\x00(\d+)\x00")


def parse_page(wikitext: str) -> list[Entry]:
    out: list[Entry] = []
    section: str | None = None
    started = False
    text = re.sub(r"<!--.*?-->", "", wikitext or "", flags=re.S)
    text, all_notes = _lift_notes(text)
    text = _REF_PAIR.sub("", text)
    text = _REF_SELF.sub("", text)
    for raw in text.splitlines():
        line = raw.rstrip()
        hm = re.match(r"^(={2,6})\s*(.*?)\s*\1\s*$", line)
        if hm:
            level = len(hm.group(1))
            kind = section_kind(hm.group(2))
            if level == 2 or kind in ("newmartyr", None):
                section = kind
            elif section is not None and kind not in ("saints",):
                section = kind
            started = True
            continue
        if not started or section is None:
            continue
        bm = re.match(r"^(\*+)\s*(.*)$", line)
        if not bm:
            continue
        body = bm.group(2)
        notes = [all_notes[int(n)] for n in _PLACEHOLDER.findall(body)]
        body = _PLACEHOLDER.sub("", body)
        if (len(bm.group(1)) > 1 or body.startswith(":")) and out:
            # a sub-bullet lists members or details of the entry above
            extra = plain(body.lstrip(":"))
            if extra:
                out[-1].text += " — " + extra
            out[-1].notes.extend(n for n in (plain(x) for x in notes) if n)
            continue
        major = body.lstrip().startswith("'''")
        links = links_in(body)
        txt = plain(body)
        if not txt or len(txt) < 3:
            continue
        yr = year_part(txt)
        head_src = re.sub(r"\s*\((?:[^()]*?)(?:\d{2,4}|\d+(?:st|nd|rd|th) c(?:entury|\.)?)[^()]*\)", "", txt)
        head = split_head(head_src)
        if not head:
            continue
        clean_notes = [n for n in (plain(n) for n in notes) if n]
        foreign = None
        for name, lang, ftitle in foreign_links(body):
            if name and name in head:
                foreign = (lang, ftitle)
                break
        out.append(Entry(section=section, head=head, year=yr, text=txt.rstrip(" ."), notes=clean_notes,
                         link=choose_link(head, links), major=major, foreign=foreign))
    return out


CATEGORY_FOR_SECTION = {"western": "Western (pre-Schism)", "newmartyr": "New Martyr"}
