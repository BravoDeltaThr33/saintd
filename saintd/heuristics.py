"""Rules that turn a liturgical commemoration title into structured facts
(kind, categories, gender, century, country). These are a fallback: when a
saint is matched in Wikidata, the Wikidata facts take precedence."""

from __future__ import annotations

import re

from .text import fold

# ------------------------------------------------------------ expansion

_ABBREV: list[tuple[str, str]] = [
    (r"\bTransl?\.\s*(?:Rel\.|Relics)\s*(?:of\s+)?", "Translation of the Relics of "),
    (r"\bUnc\.\s*Rel\.\s*(?:of\s+)?", "Uncovering of the Relics of "),
    (r"^Relics\s+(?!of\b)", "Relics of "),
    (r"\bRt\.\s*Blv\.\s*", "Right-believing "),
    (r"^Rep\.\s*", "Repose of "),
    (r"^Repose\s+(?!of\b)", "Repose of "),
    (r"\bVen\.\s*", "Venerable "),
    (r"\bBl\.\s*", "Blessed "),
    (r"\bPatr\.\s*(?=of\b)", "Patriarch "),
    (r"\bPatr\.\s*", "Patriarch of "),
    (r"\bMetr\.\s*(?=of\b)", "Metropolitan "),
    (r"\bMetr\.\s*", "Metropolitan of "),
    (r"\bAbp\.\s*(?=of\b)", "Archbishop "),
    (r"\bAbp\.\s*", "Archbishop of "),
    (r"\b(?:SS|Ss|Sts)\.?\s", "Saints "),
    (r"\bSt\.?\s", "St "),
    (r"\bApostles of (?:the )?(?:70|Seventy)\b", "Apostles of the Seventy"),
    (r"\bConstantinopole\b", "Constantinople"),
    (r"\bPats\.\s*", "Patriarchs of "),
]
_ABBREV_RX = [(re.compile(a), b) for a, b in _ABBREV]


def expand(name: str) -> str:
    n = re.sub(r"\s+", " ", (name or "").strip()).strip(' ".;')
    for rx, rep in _ABBREV_RX:
        n = rx.sub(rep, n)
    n = n.replace("Metropolitan of Moscow and Apostle", "Metropolitan of Moscow, Apostle")
    return re.sub(r"\s+", " ", n).strip(" ,")


# ------------------------------------------------------------ display name

_HONORIFIC = [
    (r"^(?:Our\s+)?Father among the Saints\s+", "St "),
    (r"^Our (?:Holy|God-?bearing) (?:Father|Mother)s?\s+", "St "),
    (r"^Our (?:Venerable|Holy Venerable) (?:Father|Mother)s?\s+", "Venerable "),
    (r"^Our (?:Righteous|Holy Righteous) (?:Father|Mother)s?\s+", "Righteous "),
    (r"^Our (?:Father|Mother)\s+", "St "),
    (r"^Righteous (?:Father|Mother)\s+", "Righteous "),
    (r"^(?:The\s+)?Holy\s+(New\s+Hieromartyrs?|New\s+Martyrs?|Hieromartyrs?|Great[- ]?[Mm]artyrs?|"
     r"Virgin[- ]?[Mm]artyrs?|Martyrs?|Apostles?|Prophets?|Prophetess|Myrrh-?bearers?|Unmercenar\w+|"
     r"Confessors?|Righteous|Equal-to-the-Apostles|Prince|Princess|Hierarchs?|Fathers|Mothers|Royal)\b", r"\1"),
    (r"^The (Venerable|Righteous|Holy)\s+", r"\1 "),
    (r"^Saint\s+", "St "),
    (r"^Greatmartyr\b", "Great-martyr"), (r"^Great Martyr\b", "Great-martyr"),
    (r"^Virgin Martyr\b", "Virgin-martyr"),
]
_HONORIFIC_RX = [(re.compile(a), b) for a, b in _HONORIFIC]
_OCCASION_HEAD = re.compile(r"^(?:Repose of|Translation of the Relics of|Uncovering of the Relics of|Relics of|"
                            r"Uncovering of the relics(?: \([^)]*\))? of|Finding of the relics of)\s+", re.I)


def display_name(title: str) -> str:
    """A clean, consistent English name for lists:
    'Our Venerable Father Gall, Enlightener of Switzerland (640)' ->
    'Venerable Gall, Enlightener of Switzerland';
    'Repose of St Seraphim of Sarov' -> 'St Seraphim of Sarov';
    'Julian the Martyr' -> 'Martyr Julian'."""
    n = expand(title)
    n = n.split(";")[0]
    n = _OCCASION_HEAD.sub("", n)
    n = re.sub(r"\s*\([^()]*\d[^()]*\)", "", n)            # years and calendar notes
    n = re.sub(r"\s*\((?:[A-Z][a-z]+\.? )?OC\)", "", n)
    n = re.sub(r"\s+", " ", n).strip(" ,.")
    for rx, rep in _HONORIFIC_RX:
        n = rx.sub(rep, n)
    m = re.match(r"^(.*?)\s+the\s+(?:Holy\s+)?(New[- ]Martyrs?|Martyrs?|Hieromartyrs?|Great-?martyrs?)\b(.*)$", n)
    if m and not re.match(r"^(?:Martyr|Hieromartyr|Great-martyr|New Martyr|St|Venerable|Righteous)\b", n):
        title_word = m.group(2).replace("-", " ").title().replace("New Martyr", "New Martyr")
        n = f"{title_word} {m.group(1)}{m.group(3)}"
    n = re.sub(r"\s+,", ",", n)
    n = re.sub(r"\s+", " ", n).strip(" ,.")
    return n[:1].upper() + n[1:] if n else expand(title)


# ------------------------------------------------------------ core name

_LEAD = re.compile(
    r"^(?:(?:our|holy|the|venerable|righteous|blessed|st|saint|saints|great|god-?bearing|"
    r"godbearing|most|new|hieromartyrs?|martyrs?|monk-?martyrs?|nun-?martyrs?|virgin-?martyrs?|"
    r"greatmartyrs?|great-?martyrs?|prophets?|prophetess|apostles?|evangelists?|hierarchs?|"
    r"confessors?|fathers?|mothers?|among|right-believing|great-?prince|prince|princess|pious|"
    r"passion-?bearers?|passionbearers?|equal-to-the-apostles|monk|nun|abbot|abbess|elder|"
    r"wonderworker|protomartyr|forefather|myrrh-?bearer|and|praised|unmercenar\w*|physicians?|"
    r"repose of|translation of the relics of|uncovering of the relics of|relics of|"
    r"commemoration of|synaxis of|virgin[\s-]+martyrs?)\b[\s,-]*)+",
    re.I,
)


def core_name(name: str) -> str:
    """The person's name without honorifics, years or calendar notes:
    'Our Venerable Father Gall, Enlightener of Switzerland (640)' ->
    'Gall, Enlightener of Switzerland'."""
    n = expand(name)
    n = re.sub(r"\([^)]*\)", " ", n)
    n = n.split(";")[0]
    n = re.sub(r"\s+", " ", n).strip(" ,.")
    n = _LEAD.sub("", n)
    n = re.sub(r"\s+the\s+(?:holy\s+)?(?:new\s+)?(?:martyrs?)\s*$", "", n, flags=re.I)
    n = re.sub(r",?\s+(?:the\s+)?(?:martyrs?|great-?martyr)$", "", n, flags=re.I)
    n = re.sub(r"\s+,", ",", n)
    return n.strip(" ,.") or expand(name)


RELATION_TAIL = re.compile(
    r",?\s+(?:the\s+)?(?:father|mother|brother|sister|son|daughter|disciple|wife|husband|grandson|"
    r"granddaughter|nephew|niece|teacher|mentor) of\b.*$", re.I)


def match_core(name: str) -> str:
    """core_name without relational tails ('..., father of St Gregory'), for
    comparing two titles of the same day."""
    return RELATION_TAIL.sub("", core_name(name)).strip(" ,.")


def first_name(core: str) -> str:
    for tok in re.split(r"[\s,&]+", core):
        if tok and tok[0].isupper() and fold(tok) not in {"the", "and"}:
            return tok
    return core.split(" ")[0] if core else ""


def dedupe_key(name: str) -> str:
    """Key used to merge the same person commemorated on several dates."""
    c = core_name(name)
    c = fold(c)
    c = re.sub(r"[^a-z0-9 ]+", " ", c)
    c = re.sub(r"\b(the|of|and|in|at)\b", " ", c)
    c = re.sub(r"(ios|ius|os|us)\b", "us", c)
    return re.sub(r"\s+", " ", c).strip()


# ------------------------------------------------------------ kinds

_FEAST = re.compile(
    r"\b(Theophany|Nativity of (?:Christ|Our Lord|the Most-?Holy Theotokos|the Theotokos|St John|"
    r"the Forerunner)|Annunciation|Dormition|Transfiguration|Exaltation|Elevation of|Meeting of|"
    r"Entry of|Protection|Pokrov|Circumcision|Forefeast|Afterfeast|Leave-?taking|Eve of|"
    r"Synaxis of the Most-?Holy Theotokos|Conception (?:by|of)|Church New Year|Image of Christ|"
    r"Procession of|Founding of|Finding (?:of )?the Precious Cross|Placing of|Fall of Constantinople|"
    r"Ecumenical Council|Veneration of the Magi|Flight into Egypt|Shepherds who saw|Beheading of|"
    r"Honorable Head|Head of St John|Precious Robe|Sign of the Precious Cross|Lifegiving Cross|"
    r"Holy Sepulchre|Resurrection|Pentecost|Ascension|Robe of|Sash of|Belt of|Veil of|"
    r"Great Canon|Akathist|Royal Hours|Memorial Saturday|Triodion|Great Fast|All Saints|"
    r"Holy Spirit|Life-?Giving Spring|Miracle|Apparition|Earthquake|canonization)\b",
    re.I,
)
_ICON = re.compile(r"\bIcons?\b", re.I)
_ANGEL = re.compile(r"\b(Archangels?|Bodiless Powers|Angels)\b", re.I)
_SAINTLY = re.compile(
    r"\b(St|Saint|Venerable|Blessed|Righteous|Hieromartyr|Martyr|Holy|Apostle|Prophet|Hierarch)\b", re.I
)
_MEMORIAL_HEAD = re.compile(r"^(Repose of|Commemoration of an?)\s+(.*)$", re.I)
_PLURAL = re.compile(
    r"\b(Martyrs|Fathers|Saints|Apostles|Youths|Maccabees|Hierarchs|Startsi|Monk-?martyrs|Women|"
    r"Mothers|Virgins|Infants|Children|Brothers|Brethren|Companions|Unmercenaries|Elders|Innocents|"
    r"Hieromartyrs|Confessors|Righteous Ones|Prophets|Monks|Nuns|sons|daughters|Family|those)\b"
)
_NUMBER = re.compile(
    r"\b(Two|Three|Four|Five|Six|Seven|Eight|Nine|Ten|Eleven|Twelve|Thirteen|Fourteen|Fifteen|"
    r"Twenty|Thirty|Forty|Fifty|Sixty|Seventy|Hundred|Thousand|\d{2,})\b"
)


def _strip_singular_plurals(n: str) -> str:
    n = re.sub(r"\bamong the Saints\b", "", n, flags=re.I)
    n = re.sub(r"\bEquals?[- ]to[- ](?:the[- ])?Apostles\b", "", n, flags=re.I)
    n = re.sub(r"\bof the Seventy\b|\bof the Twelve\b", "", n, flags=re.I)
    n = re.sub(r"\bApostles? to\b[^,]*", "", n, flags=re.I)
    n = re.sub(r"\bbrother of (?:St|the Lord|Saint)[^,]*", "", n, flags=re.I)
    return n


def classify_kind(name: str) -> str:
    n = expand(name)
    m = _MEMORIAL_HEAD.match(n)
    if m and not _SAINTLY.search(m.group(2)):
        return "memorial"
    if _ICON.search(n):
        return "icon"
    if _ANGEL.search(n) and not re.search(r"\bof\s+St\b", n):
        return "angel"
    if _FEAST.search(n) and not re.search(r"^(Repose|Translation|Uncovering)", n):
        return "feast"
    body = re.sub(r"\([^)]*\)", " ", _strip_singular_plurals(n))
    if _PLURAL.search(body) or _NUMBER.search(body) or n.lower().startswith("synaxis of"):
        return "group"
    head = _name_head(core_name(n))
    if re.search(r"(?:&|\band\b)\s*(?:his|her|their|St |Saint )?[A-Z]", head) or re.search(r",\s*[A-Z]\w+\s*,", head + ","):
        return "group"
    return "saint"


_TITLE_WORDS = (r"(?:first|the|bishop|archbishop|metropolitan|patriarch|patriarchs|pope|enlightener|founder|"
                r"abbot|abbess|wonderworker|wonderworkers|missionary|prince|princess|king|queen|emperor|"
                r"monk|nun|hermit|ascetic|presbyter|priest|deacon|apostle|equal|confessor|martyr|"
                r"protopresbyter|archpriest|hieromonk|archimandrite|elder|fool|tsar|grand|holy|"
                r"recluse|teacher|evangelist|healer|disciple|brother|sister|mother|father|son|daughter|"
                r"wife|husband|enlighteners|illuminator|abp|metr|patr|catholicos|exarch|hegumen)\b")


def _name_head(core: str) -> str:
    """The personal-name part of a core name: everything before the first
    comma that introduces a title ('Willibrord, first Bishop of ...')."""
    m = re.search(r",\s*(?=" + _TITLE_WORDS + r"|[a-z])", core, flags=re.I)
    return core[: m.start()] if m else core


# ------------------------------------------------------------ categories

_CATS: list[tuple[str, str]] = [
    ("Apostle", r"\bApostles?\b|of the Seventy|Evangelist|First[- ]Called"),
    ("Equal-to-the-Apostles", r"Equals?[- ]to[- ](?:the[- ])?Apostles|Apostles? to\b|Enlightener|Illuminator"),
    ("Prophet", r"\bProphet|Forefather|Forerunner|\bBaptist\b|Prophetess"),
    ("Hieromartyr", r"Hieromartyr|Priest-?martyr"),
    ("Great-martyr", r"Great-?\s?martyr|Greatmartyr"),
    ("New Martyr", r"New\s+(?:Hiero)?[Mm]artyr|Neomartyr|New Martyrs"),
    ("Martyr", r"[Mm]artyr|Passion"),
    ("Monastic", r"\bVen\b|Venerable|\bMonk|\bNun\b|Abbot|Abbess|Hermit|Ascetic|Hesychast|Recluse|"
                 r"Anchorite|Hieromonk|Archimandrite|\bElder|Starets|Startsi|Gerontissa|Stylite|"
                 r"Sabbaite|Studite|Caves|Kalyvites|Kavsokalybites|Desert|Monastery|Lavra"),
    ("Hierarch", r"Bishop|Archbishop|Metropolitan|Patriarch|\bPope\b|Hierarch|Catholicos|Primate|\bAbp\b"),
    ("Confessor", r"Confessor"),
    ("Righteous", r"Righteous"),
    ("Royal", r"\bPrince|Princess|\bKing\b|\bQueen|Emperor|Empress|\bTsar|Tsaritsa|Grand Duke|"
              r"Grand Duchess|Right-believing|\bDuke\b|Royal"),
    ("Passion-bearer", r"Passion-?\s?bearer|Passionbearer"),
    ("Fool-for-Christ", r"Fool[- ]for[- ]Christ|\bthe Fool\b|\bSalos\b"),
    ("Unmercenary Healer", r"Unmercenar|Healer|Physician|Anargyr"),
    ("Wonderworker", r"Wonder-?worker|Wonderworking|Thaumaturg"),
    ("Myrrh-bearer", r"Myrrh-?\s?bear"),
    ("Theologian & Hymnographer", r"Theologian|Philosopher|Hymnographer|Psalti|Melodist|Teacher of"),
    ("Virgin", r"\bVirgin\b|Virgin-?martyr"),
    ("Soldier", r"Soldier|Centurion|Warrior|Stratelates|\bTyro\b|Recruit|\bGeneral\b|Commander|Victorybearer"),
    ("Old Testament", r"Maccabees|Forefather|\bProphet\b(?! of)|Righteous (?:Job|Noah|Abraham|Joseph|Anna|Joachim)"),
]
_CATS_RX = [(c, re.compile(rx)) for c, rx in _CATS]

CATEGORIES = [c for c, _ in _CATS] + ["Western (pre-Schism)", "Angel", "Feast / Event", "Icon", "Memorial"]


def categories_for(text: str, kind: str) -> list[str]:
    t = expand(text)
    out = [c for c, rx in _CATS_RX if rx.search(t)]
    if kind == "angel":
        out = ["Angel"]
    elif kind == "feast":
        out.append("Feast / Event")
    elif kind == "icon":
        out = ["Icon"]
    elif kind == "memorial":
        out.append("Memorial")
    return list(dict.fromkeys(out))


# ------------------------------------------------------------ gender

FEMALE_NAMES = set("""
agape agatha agathonica agathoclia agnes agrippina akilina alexandra anastasia anfisa anna anne
anthousa anthusa anysia apollinaria apphia ariadne athanasia audrey avdotya barbara basilissa
bathild blandina brigid candida cassia cassiane catherine cecilia charitina christina chrysanthe
claudia clotilde cyriaca domnica domnina dorothea drosida ebba edith elisabeth elizabeth elisaveta
elpis euphemia euphrosyne eupraxia eudocia eudoxia eugenia euthalia evanthia evdokia ekaterina
fausta febronia fevronia felicity frideswide galina genevieve glykeria gavrilia golinduc helen helena
hilda hripsime ia inna irene irina joanna julia juliana julitta justina kalliniki kassiani kira
kyranna larissa leonida lucia lucy ludmila lyudmila lydia macrina manefa margaret maria mariamne
marina martha mary matrona maura mavra melania melitina menodora metrodora mildred monica natalia
natalie nadezhda nina non nonna nymphodora olga olympias osyth paraskeva paraskevi pelagia perpetua
philonilla philothea philothei photini pistis poplia pulcheria radegund rimma rufina sabina salome
scholastica sebastiane seraphima solomonia sophia susanna tabitha tamar tatiana thais thekla thecla
theodora theodosia theodote theophano thomais thomaida valentina valeria vassilisa varvara vera
walburga winifred withburga xenia zenaida zenais zinaida zoe juliania iuliania matrena evpraksia
tatyana sofia anisia ksenia akulina alypia anastasiya antonina eulampia fotinia golindukha
herais irais mastridia matrona melitina mariam marianne mavra photina potamiaena raisa
thomaid tryphaina tryphosa ulyana vassa vasilissa wenna zlata elizaveta evgenia eupraksia
kseniya lyubov nadezhda angelina elena elisabeta ekaterini kyriake kyriaki domna ia julitta
""".split())

_FEMALE_WORDS = re.compile(
    r"\b(Virgin|Mother|Nun|Abbess|Empress|Queen|Princess|Tsaritsa|Duchess|Grand Duchess|Myrrh-?bearer|"
    r"Deaconess|Wife|Daughter|Prophetess|Eldress|Gerontissa|Matron|Woman|Women|Martyress|Widow|"
    r"Nun-?martyr|Virgin-?martyr|Hegumenia|Schema-?nun)\b",
    re.I,
)


def gender_guess(name: str, kind: str) -> str:
    if kind == "angel":
        return "N/A"
    if kind in ("feast", "icon"):
        return "N/A"
    if kind == "group":
        return "Group"
    n = expand(name)
    if _FEMALE_WORDS.search(re.sub(r"\bof the Most-?Holy Theotokos\b|\bMother of God\b", "", n)):
        return "Female"
    fn = fold(first_name(core_name(n)))
    if fn in FEMALE_NAMES:
        return "Female"
    return "Male"


# ------------------------------------------------------------ centuries

_ROMAN = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "M": 1000}


def roman_to_int(s: str) -> int | None:
    s = s.strip().upper()
    if not s or any(c not in _ROMAN for c in s):
        return None
    total, prev = 0, 0
    for c in reversed(s):
        v = _ROMAN[c]
        total = total - v if v < prev else total + v
        prev = max(prev, v)
    return total


def year_to_century(year: int) -> int:
    if year > 0:
        return (year - 1) // 100 + 1
    return -((-year - 1) // 100 + 1)


def century_label(c: int | None) -> str:
    if c is None:
        return "Unknown"
    n = abs(c)
    suf = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suf} century" + (" BC" if c < 0 else "")


_WORD_CENT = {
    "first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5, "sixth": 6, "seventh": 7,
    "eighth": 8, "ninth": 9, "tenth": 10, "eleventh": 11, "twelfth": 12, "thirteenth": 13,
    "fourteenth": 14, "fifteenth": 15, "sixteenth": 16, "seventeenth": 17, "eighteenth": 18,
    "nineteenth": 19, "twentieth": 20, "twenty-first": 21,
}

# Rulers often named in the lives -> the century of their persecution/reign.
_RULERS: list[tuple[str, int]] = [
    (r"Nero\b", 1), (r"Domitian", 1), (r"Vespasian", 1), (r"Herod\b", 1), (r"Pontius Pilate", 1),
    (r"Trajan", 2), (r"Hadrian", 2), (r"Antoninus Pius", 2), (r"Marcus Aurelius", 2),
    (r"Septimius Severus", 3), (r"Decius", 3), (r"Valerian\b", 3), (r"Aurelian", 3),
    (r"Diocletian", 4), (r"Maximian", 4), (r"Galerius", 4), (r"Licinius", 4), (r"Maximinus", 4),
    (r"Julian the Apostate", 4), (r"Constantine the Great", 4), (r"Valens\b", 4),
    (r"Theodosius the Younger", 5), (r"Attila", 5), (r"Justinian", 6), (r"Heraclius", 7),
    (r"Leo the Isaurian", 8), (r"Constantine Copronymus", 8), (r"Copronymus", 8),
    (r"Leo the Armenian", 9), (r"Theophilus the Iconoclast", 9), (r"Mongol", 13), (r"Batu\b", 13),
    (r"Ottoman|the Turks", 16), (r"Bolshevik|Soviet", 20),
]
_RULERS_RX = [(re.compile(rx), c) for rx, c in _RULERS]

_YEAR_PAREN = re.compile(
    r"\((?:[^()]*?\b)?(?:c\.|ca\.|ok\.|about|†)?\s*(\d{2,4})(?:\s*[-–]\s*(\d{2,4}))?\s*(BC|B\.C\.)?\s*\)"
)
_CENT_PAREN = re.compile(
    r"\(\s*(?:c\.|ca\.)?\s*(\d{1,2})(?:st|nd|rd|th)\s*(?:[-–]\s*(\d{1,2})(?:st|nd|rd|th))?\s*c(?:entury|\.)?",
    re.I,
)
_ROMAN_PAREN = re.compile(r"\(\s*(?:ок\.\s*)?([IVXL]{1,6})(?:\s*[-–]\s*([IVXL]{1,6}))?\s*\)")


def year_from_title(title: str) -> int | None:
    """The last plain year in a title's parentheses (usually the repose)."""
    best = None
    for m in _YEAR_PAREN.finditer(title or ""):
        y = int(m.group(2) or m.group(1))
        if m.group(3):
            y = -y
        if -2000 < y <= 2100 and y != 0 and abs(y) >= 30:
            best = y
    return best


def century_from_title(title: str) -> int | None:
    """Century from a calendar title's parentheses: '(640)', '(6th c.)',
    '(168 BC)', '(XV)', '(ок. 320)'."""
    t = title or ""
    m = _CENT_PAREN.search(t)
    if m:
        return int(m.group(2) or m.group(1))
    best = None
    for m in _YEAR_PAREN.finditer(t):
        y = int(m.group(2) or m.group(1))
        if m.group(3):
            y = -y
        if -2000 < y <= 2100 and y != 0:
            best = y  # last parenthesised year is usually the repose
    if best is not None:
        return year_to_century(best)
    m = _ROMAN_PAREN.search(t)
    if m:
        v = roman_to_int(m.group(2) or m.group(1))
        if v and v <= 21:
            return v
    return None


_DEATH_YEAR = re.compile(
    r"\b(?:died|reposed|repose|martyred|suffered|beheaded|fell asleep|slain|killed|executed|shot|"
    r"departed|was crucified|was burned|was drowned)\b[^.]{0,40}?\b(?:in|about|around|c\.)\s+"
    r"(?:the year\s+)?(\d{3,4})\b",
    re.I,
)
_IN_YEAR = re.compile(r"\b(?:in|by|around|about|until|from)\s+(?:the year\s+)?(\d{3,4})\b")
_NUM_CENT = re.compile(r"\b(\d{1,2})(?:st|nd|rd|th)[- ]century\b(?:\s+(BC|B\.C\.))?", re.I)
_WORD_CENT_RX = re.compile(r"\b(" + "|".join(_WORD_CENT) + r")[- ]century\b(?:\s+(BC|B\.C\.))?", re.I)


def century_from_text(text: str) -> int | None:
    """Best-effort century from a narrative life."""
    if not text:
        return None
    m = _DEATH_YEAR.search(text)
    if m:
        y = int(m.group(1))
        if 30 <= y <= 2100:
            return year_to_century(y)
    m = _NUM_CENT.search(text)
    if m:
        c = int(m.group(1))
        return -c if m.group(2) else c
    m = _WORD_CENT_RX.search(text)
    if m:
        c = _WORD_CENT[m.group(1).lower()]
        return -c if m.group(2) else c
    for rx, c in _RULERS_RX:
        if rx.search(text):
            return c
    for m in _IN_YEAR.finditer(text):
        y = int(m.group(1))
        if 30 <= y <= 2100:
            return year_to_century(y)
    return None


# ------------------------------------------------------------ countries

HOLY_LAND = "Israel/Palestine"

_GAZ: dict[str, str] = {}


def _g(country: str, places: str) -> None:
    for p in places.replace("\n", "").split("|"):
        p = p.strip()
        if p:
            _GAZ[p] = country


_g("Turkey", """Cappadocia|Cappadocian|Constantinople|Constantinopolitan|Byzantium|Nicomedia|Nicaea|Ephesus|Smyrna|
Antioch|Pergamus|Pergamum|Pergamon|Cyzicus|Myra|Lycia|Galatia|Ancyra|Pontus|Trebizond|Trapezund|Sebaste|
Iconium|Amasea|Amaseia|Chalcedon|Bithynia|Phrygia|Cilicia|Tarsus|Isauria|Pisidia|Pamphylia|Melitene|
Edessa|Nisibis|Amorium|Ammoria|Caesarea in Cappadocia|Caesarea of Cappadocia|Nyssa|Nazianzus|Sinope|
Comana|Hierapolis|Laodicea|Philadelphia|Sardis|Thyatira|Colossae|Miletus|Halicarnassus|Prusa|Bursa|
Olympus|Mount Olympus in Bithynia|Germia|Synnada|Lystra|Derbe|Attalia|Perge|Side|Anazarbus|Aegae|
Seleucia|Sozopolis|Mysia|Lydia|Caria|Paphlagonia|Asia Minor|Dorostolum|Adrianople|Galatians|
Lampsacus|Kyzikos|Proconnesus|Prinkipo|Princes Islands|Chalcedonian|Hellespont|Thrace|Heraclea|Perinthus""")
_g("Greece", """Athens|Athenian|Thessalonica|Thessaloniki|Thessalonian|Corinth|Patras|Larissa|Ioannina|Athos|
Mount Athos|Holy Mountain|Chios|Lesbos|Mytilene|Aegina|Euboea|Philippi|Macedonia|Iveron|Vatopedi|
Lemnos|Rhodes|Corfu|Kerkyra|Zakynthos|Kefalonia|Cephalonia|Patmos|Peloponnese|Hydra|Naxos|Crete|Cretan|
Gortyna|Knossos|Cyzikos|Andros|Methymna|Androusa|Messenia|Thebes in Boeotia|Thera|Santorini|Kalymnos|Paros|
Mani|Epirus|Arta|Kastoria|Veroia|Berea|Berrhoea|Meteora|Pelagonia|Megara|Sparta|Elassona|Thessaly|
Aetolia|Mesolongion|Missolonghi|Agathonos|Pegas|Raithu of Greece|Lesvos|Sporades|Samos|Skiathos|Kos|
Hellas|Greek""")
_g("Egypt", """Alexandria|Alexandrian|Egypt|Egyptian|Thebaid|Nitria|Scetis|Scete|Sinai|Mount Sinai|Raithu|
Pelusium|Memphis|Oxyrhynchus|Tabennisi|Pachomian|Antinoe|Hermopolis|Lycopolis|Canopus|Babylon of Egypt|
Arsinoe|Panopolis|Cellia|Pispir|Clysma|Faiyum|Nile""")
_g(HOLY_LAND, """Jerusalem|Palestine|Palestinian|Gaza|Bethlehem|Judea|Judaea|Galilee|Nazareth|Jordan River|
Jericho|Caesarea of Palestine|Caesarea in Palestine|Caesarea Maritima|Samaria|Lydda|Joppa|Jaffa|Emmaus|
Mount Tabor|Hebron|Sebastia|Ascalon|Eleutheropolis|Jamnia|Lavra of St Sabbas|Mar Saba|Choziba|Hozeva|
Sabbaite|Holy Land|Ptolemais|Acre|Bethany|Capernaum|Cana|Tiberias|Diospolis|Scythopolis|Bethsaida""")
_g("Syria", """Damascus|Syria|Syrian|Emesa|Homs|Apamea|Hierapolis in Syria|Aleppo|Beroea in Syria|
Antaradus|Bostra|Hauran|Palmyra|Chalcis|Cyrrhus|Zeugma|Laodicea in Syria|Maarrat|Qinnasrin|Telanissos""")
_g("Lebanon", "Lebanon|Tyre|Sidon|Berytus|Beirut|Heliopolis|Baalbek|Byblos|Tripoli of Syria|Hamatoura|Phoenicia")
_g("Iraq", "Mesopotamia|Babylon|Babylonian|Nineveh|Seleucia-Ctesiphon|Ctesiphon|Mosul|Arbela|Kirkuk|Assyria")
_g("Iran", "Persia|Persian|Susa|Ecbatana|Hamadan|Media")
_g("Armenia", "Armenia|Armenian|Etchmiadzin|Vagharshapat")
_g("Georgia", "Georgia|Georgian|Iberia|Iberian|Tbilisi|Tiflis|Mtskheta|Kartli|Kakheti|Gelati|Svaneti|Imereti")
_g("Cyprus", "Cyprus|Cypriot|Salamis|Kition|Citium|Nicosia|Leucosia|Tamassos|Cyrenia|Kyrenia|Paphos|Trimythous|Trimythus|Larnaca|Kykkos")
_g("Italy", """Rome|Roman|Milan|Ravenna|Sicily|Sicilian|Lombardy|Italy|Italian|Nola|Naples|Aquileia|Catania|
Syracuse|Taormina|Calabria|Bari|Lentini|Tauromenium|Verona|Turin|Brescia|Capua|Benevento|Spoleto|Ostia|Sardinia""")
_g("France", """Gaul|Gallic|Lyons|Lyon|Lugdunum|Vienne|Tours|Marseilles|Marseille|Paris|Parisian|Arles|France|French|
Poitiers|Auxerre|Lerins|Orleans|Autun|Reims|Rouen|Brittany|Sark""")
_g("Spain", "Spain|Hispania|Seville|Cordoba|Toledo|Saragossa|Zaragoza|Tarragona|Spanish|Iberian Peninsula|Merida")
_g("Portugal", "Portugal|Braga|Lusitania")
_g("Ireland", "Ireland|Irish|Glendalough|Armagh|Kildare|Clonmacnoise|Aghaboe|Bangor|Clonard|Derry|Down")
_g("United Kingdom", """Britain|British|England|English|Canterbury|Lindisfarne|Northumbria|Wales|Welsh|Iona|Scotland|
Scottish|York|Hexham|Durham|Whitby|Ely|Mercia|Kent|Wessex|East Anglia|Glastonbury|Cornwall|Winchester|
Ripon|Jarrow|Wearmouth|Crowland|St Albans|Coldingham|Melrose|Glasgow|Strathclyde|Isle of Man|Lichfield""")
_g("Germany", "Germany|German|Trier|Cologne|Mainz|Augsburg|Bavaria|Saxony|Fulda|Regensburg|Rhine")
_g("Netherlands", "Utrecht|Frisia|Netherlands|Holland")
_g("Switzerland", "Switzerland|Swiss|Lake Constance|St Gallen|Zurich|Geneva")
_g("Austria", "Austria|Noricum|Vienna|Salzburg|Lorch")
_g("Tunisia", "Carthage|Carthaginian|Tunis|Utica")
_g("Algeria", "Numidia|Hippo|Cirta|Algeria|Lambaesis|Mauretania")
_g("Libya", "Cyrene|Cyrenaica|Pentapolis|Libya")
_g("Ethiopia", "Ethiopia|Ethiopian|Abyssinia|Axum|Aksum")
_g("Ukraine", """Kiev|Kyiv|Kievan|Kiev Caves|Pechersk|Pechersky|Chernigov|Chernihiv|Pochaev|Pochayiv|Volhynia|
Vladimir-Volynsky|Odessa|Odesa|Kharkov|Kharkiv|Poltava|Zhitomir|Crimea|Chersonesus|Kherson|Perekop|
Uman|Galicia|Lvov|Lviv|Svyatogorsk|Sviatohirsk|Pereyaslavl""")
_g("Russia", """Moscow|Muscovite|Novgorod|Radonezh|Sarov|Optina|Valaam|Rostov|Vladimir|Suzdal|Kazan|Tver|Pskov|
Yaroslavl|Smolensk|Murom|Solovki|Solovetsky|Sora|Zadonsk|Kronstadt|Petersburg|St Petersburg|Petrograd|
Leningrad|Irkutsk|Tobolsk|Siberia|Siberian|Russia|Russian|Perm|Ustiug|Ustyug|Stolbensk|Kostroma|Belgorod|
Voronezh|Tambov|Ryazan|Nizhny Novgorod|Vologda|Belozersk|Beloozero|Kirillov|Ferapontov|Tikhvin|Ladoga|
Svir|Pereslavl|Uglich|Kaluga|Tula|Orel|Kursk|Penza|Saratov|Samara|Simbirsk|Astrakhan|Ekaterinburg|
Yekaterinburg|Alapaevsk|Verkhoturye|Tsarskoye Selo|Lazarevskoye|Diveyevo|Glinsk|Kolomna|Zvenigorod|
Komi|Chukotka|Kamchatka|Yakutsk|Butovo|Mozhaisk|Borovsk|Volokolamsk|Kirzhach|
Arzamas|Ostrovno|Vyritsa|Valdai|Kiy|Svir|Obnora|Velikoperm|Ustvym|Galich|Tobolsk|Kozelsk|Shamordino""")
_g("Belarus", "Belarus|Polotsk|Minsk|Turov|Grodno|Brest|Zhirovichi|Mogilev|Vitebsk")
_g("United States", """Alaska|Alaskan|America|American|Americas|Chicago|Platina|San Francisco|Sitka|Kodiak|
Spruce Island|Brooklyn|New York|Pennsylvania|Minneapolis|Wilkes-Barre|Libertyville|Netsvetov|Aleutian""")
_g("Canada", "Canada|Canadian|Winnipeg|Alberta|Montreal")
_g("Japan", "Japan|Japanese|Tokyo")
_g("China", "China|Chinese|Beijing|Peking")
_g("Serbia", """Serbia|Serbian|Zhicha|Zica|Žiča|Studenica|Belgrade|Raška|Raska|Pec|Peć|Decani|Dečani|Hilandar|Chilandar|
Kosovo|Morava|Nish|Naissus|Sremski|Fruska Gora|Lelić|Lelic|Ohrid of Serbia""")
_g("North Macedonia", "Ochrid|Ochrida|Ohrid|Skopje|Prilep|Bitola|Strumica|Bregalnica")
_g("Montenegro", "Montenegro|Cetinje|Ostrog")
_g("Bosnia and Herzegovina", "Bosnia|Herzegovina|Tvrdoš|Zitomislic")
_g("Bulgaria", "Bulgaria|Bulgarian|Rila|Tarnovo|Tirnovo|Sofia|Serdica|Plovdiv|Philippopolis|Vratsa|Bachkovo|Preslav")
_g("Romania", "Romania|Romanian|Wallachia|Wallachian|Moldavia|Moldavian|Iasi|Iași|Neamt|Neamț|Dacia|Tomis|Scythia Minor|Putna|Sihastria|Transylvania")
_g("Moldova", "Moldova|Chisinau|Kishinev|Bessarabia")
_g("Poland", "Poland|Polish|Chelm|Kholm|Podlasie|Grabarka|Krakow")
_g("Finland", "Finland|Finnish|Karelia")
_g("Estonia", "Estonia|Tallinn|Revel|Tartu|Yuriev|Pskovo-Pechersky")
_g("Latvia", "Latvia|Riga")
_g("Lithuania", "Lithuania|Lithuanian|Vilnius|Vilna")
_g("Czech Republic", "Moravia|Moravian|Bohemia|Prague|Velehrad")
_g("Slovakia", "Slovakia|Nitra")
_g("Albania", "Albania|Albanian|Berat|Durres|Dyrrachium|Epidamnus|Illyria|Illyricum")
_g("Croatia", "Dalmatia|Sirmium|Salona|Split|Croatia")
_g("Hungary", "Hungary|Pannonia|Hungarian")
_g("India", "India|Indian|Malabar")
_g("Arabia", "Arabia|Arabian|Najran|Himyar|Yemen")
_g("Jordan", "Petra|Philadelphia of Arabia|Gadara|Gerasa|Jerash|Transjordan")

_GAZ_KEYS = sorted(_GAZ, key=len, reverse=True)
_GAZ_RX = re.compile(r"\b(" + "|".join(re.escape(k.strip()) for k in _GAZ_KEYS if k.strip()) + r")\b")

_COUNTRY_ALIASES = {
    "Türkiye": "Turkey", "Republic of Turkey": "Turkey", "State of Palestine": HOLY_LAND,
    "Israel": HOLY_LAND, "Palestine": HOLY_LAND, "People's Republic of China": "China",
    "United States of America": "United States", "Kingdom of Great Britain": "United Kingdom",
    "England": "United Kingdom", "Scotland": "United Kingdom", "Wales": "United Kingdom",
    "Czechia": "Czech Republic", "Republic of Ireland": "Ireland", "Kingdom of Greece": "Greece",
    "Second Hellenic Republic": "Greece", "Kingdom of Italy": "Italy",
    "Russian Empire": "Russia", "Tsardom of Russia": "Russia", "Grand Duchy of Moscow": "Russia",
    "Russian Soviet Federative Socialist Republic": "Russia", "Soviet Union": "Russia",
    "Russian SFSR": "Russia", "Ukrainian Soviet Socialist Republic": "Ukraine",
    "Byelorussian Soviet Socialist Republic": "Belarus", "Kingdom of Serbia": "Serbia",
    "Serbian Empire": "Serbia", "Grand Principality of Serbia": "Serbia", "Kingdom of Georgia": "Georgia",
    "Kingdom of Iberia": "Georgia", "Ptolemaic Kingdom": "Egypt", "Sasanian Empire": "Iran",
    "Achaemenid Empire": "Iran", "Kingdom of Armenia": "Armenia", "Kingdom of Kartli": "Georgia",
    "Kingdom of Kakheti": "Georgia", "Kingdom of Imereti": "Georgia", "Wallachia": "Romania",
    "Moldavia": "Romania", "Principality of Moldavia": "Romania", "Kingdom of Romania": "Romania",
    "Second Bulgarian Empire": "Bulgaria", "First Bulgarian Empire": "Bulgaria",
    "Kingdom of Bulgaria": "Bulgaria", "Polish–Lithuanian Commonwealth": "Poland",
    "Grand Duchy of Lithuania": "Lithuania", "Kingdom of Poland": "Poland",
    "Novgorod Republic": "Russia", "Vladimir-Suzdal": "Russia", "Principality of Vladimir-Suzdal": "Russia",
    "Grand Duchy of Vladimir": "Russia", "Pskov Republic": "Russia", "Principality of Tver": "Russia",
    "Principality of Ryazan": "Russia", "Principality of Rostov": "Russia",
    "Principality of Smolensk": "Russia", "Principality of Chernigov": "Ukraine",
    "Kingdom of Galicia–Volhynia": "Ukraine", "Kingdom of Ruthenia": "Ukraine",
    "Russian Republic": "Russia", "Empire of Japan": "Japan", "Kingdom of England": "United Kingdom",
    "Kingdom of Scotland": "United Kingdom", "Kingdom of Northumbria": "United Kingdom",
    "Kingdom of Mercia": "United Kingdom", "Kingdom of Kent": "United Kingdom",
    "Kingdom of Wessex": "United Kingdom", "Kingdom of East Anglia": "United Kingdom",
    "Kingdom of the Franks": "France", "Francia": "France", "Merovingian dynasty": "France",
    "Visigothic Kingdom": "Spain", "Roman Egypt": "Egypt", "Aksumite Empire": "Ethiopia",
}
# States that cover too much ground to tell a modern country.
_TOO_BROAD = {"Roman Empire", "Byzantine Empire", "Eastern Roman Empire", "Ottoman Empire",
              "Kievan Rus'", "Roman Republic", "Western Roman Empire", "Golden Horde", "Seleucid Empire",
              "Holy Roman Empire", "Austria-Hungary", "Austrian Empire", "Kingdom of Yugoslavia",
              "Socialist Federal Republic of Yugoslavia", "Yugoslavia", "Sasanian Empire (Persia)",
              "Rashidun Caliphate", "Umayyad Caliphate", "Abbasid Caliphate", "Fatimid Caliphate",
              "Mamluk Sultanate", "Herodian Kingdom of Judea", "Kingdom of Israel", "Kingdom of Judah"}


def normalize_country(label: str | None) -> str | None:
    if not label:
        return None
    label = label.strip()
    if label in _TOO_BROAD:
        return None
    return _COUNTRY_ALIASES.get(label, label)


def country_from_name(name: str) -> tuple[str, str] | None:
    """Like country_from_text, but ignores the saint's own given name
    (so 'Vladimir' the prince is not read as the city of Vladimir)."""
    n = expand(name)
    fn = first_name(core_name(n))
    if fn:
        n = re.sub(r"\b" + re.escape(fn) + r"\b", " ", n)
    return country_from_text(n)


def country_from_text(text: str) -> tuple[str, str] | None:
    """(modern country, place name) from the first recognised place."""
    if not text:
        return None
    t = re.sub(r"\bGeorge the Georgian\b", "George, Georgian", text)
    m = _GAZ_RX.search(t)
    if not m:
        return None
    place = m.group(1)
    return _GAZ.get(place) or _GAZ.get(place.strip()), place


def is_unknown(v) -> bool:
    return v in (None, "", "Unknown")
