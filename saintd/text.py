"""Text helpers: accent folding, search normalisation, HTML -> Markdown,
Cyrillic transliteration."""

from __future__ import annotations

import html
import re
import unicodedata
from html.parser import HTMLParser

# ---------------------------------------------------------------- folding

_STRESS = dict.fromkeys(map(ord, "́̀"), None)


def strip_stress(s: str) -> str:
    """Remove Russian stress marks (combining acute/grave) only."""
    return unicodedata.normalize("NFC", unicodedata.normalize("NFD", s).translate(_STRESS))


def fold(s: str) -> str:
    """Lower-case and strip all diacritics (for comparisons and search)."""
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return s.lower()


_WORD = re.compile(r"[a-z0-9]+")


def _letters(tok: str) -> str:
    """Collapse common transliteration differences (Athanasios/Athanasius,
    Kyril/Cyril, Theophan/Feofan...)."""
    t = re.sub(r"(.)\1+", r"\1", tok)
    for a, b in (("ph", "f"), ("th", "t"), ("kh", "h"), ("ch", "h"), ("k", "c"),
                 ("y", "i"), ("ou", "u"), ("ae", "e"), ("oe", "e"), ("ei", "i"),
                 ("j", "i"), ("w", "v"), ("v", "b"), ("q", "c")):
        t = t.replace(a, b)
    t = re.sub(r"(.)\1+", r"\1", t)
    return t


def _ending(tok: str) -> str:
    t = _letters(tok)
    return re.sub(r"(ios|ius|ij|ii|os|us|ie|y)$", "us", t) if len(t) > 4 else t


def search_forms(text: str) -> str:
    """Build the space-separated search blob stored for a saint: raw folded
    tokens plus normalised variants so partial and variant spellings match."""
    toks = _WORD.findall(fold(text))
    out: list[str] = []
    seen: set[str] = set()
    for t in toks:
        for v in (t, _letters(t), _ending(t)):
            if v not in seen:
                seen.add(v)
                out.append(v)
    return " " + " ".join(out) + " "


_GREEK = {"α": "a", "β": "v", "γ": "g", "δ": "d", "ε": "e", "ζ": "z", "η": "i", "θ": "th", "ι": "i", "κ": "k",
          "λ": "l", "μ": "m", "ν": "n", "ξ": "x", "ο": "o", "π": "p", "ρ": "r", "σ": "s", "ς": "s", "τ": "t",
          "υ": "y", "φ": "f", "χ": "ch", "ψ": "ps", "ω": "o"}


def query_variants(query: str) -> list[set[str]]:
    """For each word the user typed, the set of forms that may match.
    Russian and Greek are transliterated first (Серафим, Σεραφείμ -> serafim)."""
    q = translit(query)
    q = "".join(_GREEK.get(c, c) for c in fold(q))
    toks = _WORD.findall(q)
    if not toks and query.strip():
        return [{"\uffff"}]              # letters we can't read: match nothing rather than everything
    return [{t, _letters(t), _ending(t)} for t in toks]


def sig_tokens(text: str) -> list[str]:
    """Normalised significant tokens (used for fuzzy name matching)."""
    stop = STOPWORDS
    return [_ending(t) for t in _WORD.findall(fold(text)) if t not in stop and len(t) > 1]


STOPWORDS = {
    "the", "of", "and", "in", "at", "a", "an", "with", "his", "her", "their", "to", "by",
    "from", "on", "who", "those", "him", "them", "on", "for", "our", "holy", "saint", "saints",
    "st", "sts", "ss", "ven", "venerable", "martyr", "martyrs", "hieromartyr", "hieromartyrs",
    "greatmartyr", "great", "new", "righteous", "blessed", "father", "fathers", "mother",
    "mothers", "bishop", "archbishop", "metropolitan", "patriarch", "pope", "abbot", "abbess",
    "monk", "nun", "priest", "presbyter", "deacon", "apostle", "apostles", "prophet",
    "prophetess", "confessor", "virgin", "wonderworker", "prince", "princess", "king", "queen",
    "emperor", "empress", "elder", "repose", "relics", "translation", "uncovering", "trans",
    "rel", "unc", "rep", "rt", "blv", "right", "believing", "equal", "apostles", "companions",
    "among", "god", "godbearing", "god-bearing", "most", "passion", "bearer", "passionbearer",
    "enlightener", "c", "ca", "th", "nd", "rd", "st", "bc", "ad", "century", "hierarch",
    "hieromonk", "archimandrite", "fr", "unmercenary", "unmercenaries", "pious", "first",
    "called", "evangelist", "forefather", "nun-martyr", "monk-martyr", "myrrhbearer",
    "virginmartyr", "victorybearer", "healer", "equals", "great-martyr", "great-prince",
}

# ------------------------------------------------------------ HTML -> MD


class _MD(HTMLParser):
    BLOCK = {"p", "div", "br", "li", "h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "tr"}
    MARK = {"em": "*", "i": "*", "strong": "**", "b": "**"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self.skip = 0
        self.open: list[tuple[str, int]] = []     # emphasis tags still open: (tag, index in out)

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.skip += 1
        elif tag in ("p", "div", "blockquote", "tr"):
            self.out.append("\n\n")
        elif tag == "br":
            self.out.append(_BR)
        elif tag == "li":
            self.out.append("\n- ")
        elif tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            self.out.append("\n\n### ")
        elif tag in self.MARK:
            self.open.append((tag, len(self.out)))
            self.out.append(self.MARK[tag])

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self.skip = max(0, self.skip - 1)
        elif tag in ("p", "div", "blockquote", "h1", "h2", "h3", "h4", "h5", "h6"):
            self.out.append("\n\n")
        elif tag in self.MARK:
            if not self.open or self.open[-1][0] != tag:
                return
            _, i = self.open.pop()
            inner = "".join(self.out[i + 1:])
            if not inner.strip(_BR + " \n\t"):
                del self.out[i]                 # empty emphasis: drop the marker
                return
            # keep the marks next to the words (markdown ignores "* text *")
            lead = len(inner) - len(inner.lstrip(_BR + " \n\t"))
            trail = len(inner) - len(inner.rstrip(_BR + " \n\t"))
            core = inner[lead:len(inner) - trail]
            m = self.MARK[tag]
            self.out[i:] = [inner[:lead], m, core, m, inner[len(inner) - trail:]]

    def handle_data(self, data):
        if self.skip:
            return
        data = data.replace("\n", " ")
        before = "".join(self.out[-3:]).rstrip(" \t*")
        if (not before or before.endswith(("\n", _BR))) and re.match(r"\s*([+*-]|\d+[.)]|#+)(\s|$)", data):
            # literal text, not a list or heading (only punctuation can be escaped)
            data = re.sub(r"^(\s*)(\d+)([.)])", r"\1\2\\\3", data, count=1) if re.match(r"\s*\d", data) \
                else re.sub(r"^(\s*)", r"\1\\", data, count=1)
        self.out.append(data)


_BR = "\x01"           # a line break inside a paragraph (kept as a Markdown hard break)


def html_to_markdown(src: str) -> str:
    p = _MD()
    try:
        p.feed(src or "")
        p.close()
    except Exception:  # malformed markup: fall back to tag stripping
        return html_to_text(src)
    md = "".join(p.out)
    md = re.sub(r"[ \t]+", " ", md)
    md = re.sub(r" *\n *", "\n", md)
    md = re.sub(r"\n{3,}", "\n\n", md)
    md = re.sub(r" *\x01 *", "\x01", md)
    md = re.sub(r"\x01+(?=\n|$)", "", md)       # a break at the end of a paragraph does nothing
    md = re.sub(r"(?<=\n)\x01+|^\x01+", "", md)
    md = re.sub(r"\x01{2,}", "\n\n", md)         # <br><br> separates paragraphs
    md = md.replace("\x01", "\\\n")
    md = re.sub(r"\n{3,}", "\n\n", md)
    return md.strip()


def html_to_text(src: str) -> str:
    s = re.sub(r"<br\s*/?>", "\n", src or "", flags=re.I)
    s = re.sub(r"</p\s*>", "\n\n", s, flags=re.I)
    s = re.sub(r"<[^>]+>", "", s)
    s = html.unescape(s)
    s = re.sub(r"[ \t]+", " ", s)
    return re.sub(r"\n{3,}", "\n\n", s).strip()


def md_escape(s: str) -> str:
    """Escape characters that would be read as Markdown table syntax."""
    return (s or "").replace("|", "/").replace("\n", " ")


# -------------------------------------------------------- transliteration

_CYR = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "yo", "ж": "zh",
    "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o",
    "п": "p", "р": "r", "с": "s", "т": "t", "у": "u", "ф": "f", "х": "kh", "ц": "ts",
    "ч": "ch", "ш": "sh", "щ": "shch", "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu",
    "я": "ya", "і": "i", "ѣ": "e", "ѳ": "f", "ѵ": "i",
}


def translit(s: str) -> str:
    """Simple readable Russian -> Latin transliteration (BGN-like)."""
    s = strip_stress(s)
    out = []
    for ch in s:
        low = ch.lower()
        if low in _CYR:
            t = _CYR[low]
            out.append(t.capitalize() if ch != low and t else t)
        else:
            out.append(ch)
    res = "".join(out)
    res = re.sub(r"iy\b", "y", res)
    res = re.sub(r"skiy\b|skii\b", "sky", res)
    return res


def has_cyrillic(s: str) -> bool:
    return bool(re.search(r"[Ѐ-ӿ]", s or ""))


# ------------------------------------------------------ foreign scripts

_FOREIGN = re.compile(r"[Ͱ-Ͽἀ-῿Ѐ-ԯⷠ-ⷿꙀ-ꚟႠ-ჿ"
                      r"԰-֏֐-׿؀-ۿ܀-ݏⲀ-⳿]")


def _groups(s: str) -> list[tuple[int, int, str]]:
    """Top-level (start, end, opener) bracket groups in s, nesting aware."""
    out, stack = [], []
    pairs = {"(": ")", "[": "]"}
    for i, ch in enumerate(s):
        if ch in pairs:
            stack.append((ch, i))
        elif ch in (")", "]") and stack:
            op, start = stack.pop()
            if pairs[op] != ch:
                stack.clear()
                continue
            if not stack:
                out.append((start, i + 1, op))
    return out


def strip_foreign_script(s: str) -> str:
    """Remove non-Latin-script spellings that English articles put in brackets,
    e.g. '(Russian: Серафим Саровский; 1754 – 1833)' -> '(1754 – 1833)'."""
    if not s or not _FOREIGN.search(s):
        return s
    out, pos = [], 0
    for start, end, op in _groups(s):
        grp = s[start:end]
        if not _FOREIGN.search(grp):
            continue
        out.append(s[pos:start])
        pos = end
        inner = grp[1:-1]
        if op == "[":
            continue                       # bracketed native spelling: drop entirely
        pieces = re.split(r"([;,]\s*)", inner)        # keep the original separators
        kept: list[str] = []
        for i in range(0, len(pieces), 2):
            part = pieces[i]
            sep = pieces[i + 1] if i + 1 < len(pieces) else ""
            if not part.strip() or _FOREIGN.search(part):
                continue
            part = strip_foreign_script(part)
            if re.fullmatch(r"\s*(?:[A-Z][\w .-]*:)?\s*", part):
                continue
            kept.append(part.strip())
            kept.append(sep.strip())
        while kept and kept[-1] in (";", ",", ""):
            kept.pop()
        if kept:
            txt = ""
            for k in kept:
                txt += (k + " ") if k in (";", ",") else k
            txt = re.sub(r"\s+([;,])", r"\1", txt)
            out.append("(" + txt.strip() + ")")
    out.append(s[pos:])
    res = "".join(out)
    res = re.sub(r"\s+([,.;:])", r"\1", res)
    res = re.sub(r"\(\s*[,;]\s*", "(", res)
    res = re.sub(r"[ \t]{2,}", " ", res)
    return res
