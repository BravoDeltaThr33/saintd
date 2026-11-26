"""Saints from Wikidata, for the directory build: the Eastern Orthodox saints Wikidata
gives a feast day, so that the build can add those no calendar has.

Wikidata marks a saint with a title (P411: "passion-bearer", "The Venerable"...) and the
day with a feast day (P841). Which church keeps the saint is said in several ways, none
of them always, so any one of these counts:

* a title only the Orthodox use (passion-bearer, great-martyr, equal-to-the-apostles...);
* an Orthodox church named on the title or the feast day, or as the saint's religion;
* "Orthodox" in a description (English, Russian, Greek, Serbian, Romanian, Bulgarian or
  Ukrainian);
* an entry in OrthodoxWiki or Drevo.

Titles that East and West share ("The Venerable", "thaumaturge", and "hieromartyr", which
Wikidata gives Italian and French martyr bishops too), and the Russian Orthodox
Encyclopedia (which has Western saints too), count only for people of the East with
nothing Western or Catholic about them, or with the Orthodox faith as their religion. A
Western saint counts with the Western Orthodox Wiki, from before the Schism. Saints the
Catholic Church canonized after the Schism are left out unless an Orthodox church keeps
them too; so are the Oriental churches (Coptic, Armenian, Syriac, Ethiopian), the Old
Believers and Old Calendarists, and anything that is not a person or a group of people
(icons and feasts have feast days too).

Wikidata mostly gives the church date of a feast. For a saint of an Old Calendar church
it sometimes gives the civil date as well, 13 days later; that one is dropped."""

from __future__ import annotations

import datetime as dt
import re
from typing import Callable

from . import ru
from . import sources as S
from .net import Http
from .text import fold, has_cyrillic, translit

# ---------------------------------------------------------------- what is asked of Wikidata

_PREFIXES = """PREFIX wd: <http://www.wikidata.org/entity/>
PREFIX wdt: <http://www.wikidata.org/prop/direct/>
PREFIX p: <http://www.wikidata.org/prop/>
PREFIX pq: <http://www.wikidata.org/prop/qualifier/>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX skos: <http://www.w3.org/2004/02/skos/core#>
PREFIX schema: <http://schema.org/>
"""
# Six small queries rather than one large one: the query service stops any query after 60
# seconds and gives each client about a minute of work a minute. Each part starts from the feast
# day, so that only the items that have one (about ten thousand) are looked at.

FEASTS = _PREFIXES + """SELECT ?item ?kind ?v ?vl WHERE {
  ?item wdt:P841 ?v . BIND("feast" AS ?kind)
  OPTIONAL { ?v rdfs:label ?vl . FILTER(LANG(?vl) = "en") }
}"""

# Titles, what the item is, gender, a pope's canonization, and entries in Orthodox reference works.
TRAITS = _PREFIXES + """SELECT DISTINCT ?item ?kind ?v WHERE {
  { ?item wdt:P841 ?f ; wdt:P411 ?v . BIND("title" AS ?kind) }
  UNION { ?item wdt:P841 ?f ; wdt:P31 ?v . BIND("type" AS ?kind) }
  UNION { ?item wdt:P841 ?f ; wdt:P21 ?v . BIND("gender" AS ?kind) }
  UNION { ?item wdt:P841 ?f ; p:P411 ?cs . ?cs pq:P1027 ?v .
          FILTER(?v IN (wd:Q9592, wd:Q1063490) || EXISTS { ?v wdt:P39 wd:Q19546 })
          BIND("canonized by" AS ?kind) }
  UNION { VALUES ?idp { wdt:P5002 wdt:P7819 wdt:P14946 wdt:P10473 wdt:P14653 }
          ?item wdt:P841 ?f ; ?idp ?x . BIND(STR(?idp) AS ?v) BIND("id" AS ?kind) }
}"""

# The churches named for the saint or the feast, and the saint's country, by their English names.
CHURCHES = _PREFIXES + """SELECT DISTINCT ?item ?kind ?v ?vl WHERE {
  { ?item wdt:P841 ?f ; wdt:P27 ?v . BIND("country" AS ?kind) }
  UNION { ?item wdt:P841 ?f ; wdt:P140|wdt:P1049 ?v . BIND("church" AS ?kind) }
  UNION { ?item wdt:P841 ?f ; p:P411|p:P841 ?st . ?st pq:P140|pq:P3680|pq:P1049|pq:P518|pq:P642|pq:P1001|pq:P361 ?v .
          BIND("church" AS ?kind) }
  OPTIONAL { ?v rdfs:label ?vl . FILTER(LANG(?vl) = "en") }
}"""

# Names and other names, in the languages of the Orthodox world we can read.
NAMES = _PREFIXES + """SELECT DISTINCT ?item ?kind ?text WHERE {
  { ?item wdt:P841 ?f ; rdfs:label ?text . BIND("label" AS ?kind)
    FILTER(LANG(?text) IN ("en", "ru", "el", "sr", "ro", "bg", "uk")) }
  UNION { ?item wdt:P841 ?f ; skos:altLabel ?text . BIND("alias" AS ?kind) FILTER(LANG(?text) IN ("en", "ru")) }
}"""

DESCRIPTIONS = _PREFIXES + """SELECT DISTINCT ?item ?kind ?text WHERE {
  ?item wdt:P841 ?f ; schema:description ?text . BIND("desc" AS ?kind)
  FILTER(LANG(?text) IN ("en", "ru", "el", "sr", "ro", "bg", "uk"))
}"""

# Dates and the English Wikipedia article.
FACTS = _PREFIXES + """SELECT DISTINCT ?item ?born ?died ?enwiki WHERE {
  ?item wdt:P841 ?f .
  OPTIONAL { ?item wdt:P569 ?born }
  OPTIONAL { ?item wdt:P570 ?died }
  OPTIONAL { ?article schema:about ?item ; schema:isPartOf <https://en.wikipedia.org/> ; schema:name ?enwiki }
}"""

QUERIES = (FEASTS, TRAITS, CHURCHES, NAMES, DESCRIPTIONS, FACTS)

_MONTHS = {m: i + 1 for i, m in enumerate(("january", "february", "march", "april", "may", "june", "july",
                                           "august", "september", "october", "november", "december"))}


def _new(qid: str) -> dict:
    return {"qid": qid, "feasts": set(), "titles": set(), "types": set(), "gender": "", "countries": set(),
            "churches": [], "canonized_by": False, "ids": set(), "labels": {}, "aliases": [], "descs": {},
            "born": None, "died": None, "enwiki": ""}


def _day(label: str) -> tuple[int, int] | None:
    """'January 15' (the English name of a Wikidata day item) -> (1, 15)."""
    m = re.match(r"^([A-Za-z]+) (\d{1,2})$", label.strip())
    if not m or m.group(1).lower() not in _MONTHS:
        return None
    month, day = _MONTHS[m.group(1).lower()], int(m.group(2))
    try:
        dt.date(S.REF_YEAR, month, day)
    except ValueError:
        return None
    return month, day


def _year(value: str) -> int | None:
    m = re.match(r"^(-?\d{1,4})-", value or "")
    return int(m.group(1)) if m else None


def fetch(http: Http, progress: Callable[[int, int], None] = lambda d, t: None) -> dict[str, dict]:
    """Every Wikidata item with a feast day, with what tells its church, its names and dates."""
    items: dict[str, dict] = {}
    for i, query in enumerate(QUERIES):
        progress(i, len(QUERIES))
        for r in S.wdqs(http, query):
            it = items.setdefault(r["item"], _new(r["item"]))
            _take(it, r)
    progress(len(QUERIES), len(QUERIES))
    return items


def _take(it: dict, r: dict) -> None:
    """File one row of a query's answer under its item."""
    kind, v, vl = r.get("kind"), r.get("v", ""), r.get("vl", "")
    if kind == "feast":
        d = _day(vl)
        if d:
            it["feasts"].add(d)
    elif kind == "title":
        it["titles"].add(v)
    elif kind == "type":
        it["types"].add(v)
    elif kind == "gender":
        it["gender"] = v
    elif kind == "country":
        it["countries"].add(vl or v)
    elif kind == "church":
        it["churches"].append(vl or v)
    elif kind == "canonized by":
        it["canonized_by"] = True
    elif kind == "id":
        it["ids"].add(v.rsplit("/", 1)[-1])
    elif kind == "label":
        it["labels"][r.get("text@", "")] = r.get("text", "")
    elif kind == "alias":
        it["aliases"].append((r.get("text@", ""), r.get("text", "")))
    elif kind == "desc":
        it["descs"][r.get("text@", "")] = r.get("text", "")
    if "born" in r or "died" in r or "enwiki" in r:
        for k in ("born", "died"):
            y = _year(r.get(k, ""))
            if y is not None and (it[k] is None or y < it[k]):
                it[k] = y
        if r.get("enwiki"):
            it["enwiki"] = r["enwiki"]


# ---------------------------------------------------------------- which are Eastern Orthodox saints

ORTHODOX_TITLES = {
    "Q4411339",     # hierarch ("prelate")
    "Q4377390",     # venerable-martyr ("Reverend Martyr")
    "Q3332786",     # great-martyr
    "Q108801814",   # Eastern Orthodox saint
    "Q2032316",     # passion-bearer
    "Q401642",      # stylite
    "Q4087714",     # right-believing
    "Q4291360",     # locally venerated saint
    "Q16745627",    # righteous
    "Q619869",      # equal-to-the-apostles
    "Q2389950",     # new martyr
    "Q12299587",    # fool-for-Christ
    "Q12872965",    # Agía
}
# titles East and West share: the Venerable, confessor of the faith, thaumaturge, Desert Fathers,
# and hieromartyr, stylite and recluse, which Wikidata gives Italian and French saints too
SHARED_TITLES = {"Q12774503", "Q2354129", "Q1349880", "Q1066990", "Q2993173", "Q401642", "Q2303143"}
WEST_TOO = {"Q2993173", "Q401642", "Q2303143"}
GREAT_MARTYR = "Q3332786"
# Catholic saint, Servant of God, Venerable, beatification (not "blessed": the Russian blazhennye too)
CATHOLIC_TITLES = {"Q3464126", "Q869974", "Q51619", "Q51620"}
SAINT = "Q43115"
ORTHODOX_REFERENCES = {"P7819", "P14946", "P10473"}   # OrthodoxWiki (English, French), Drevo
ENCYCLOPEDIA = "P5002"              # the Orthodox Encyclopedia: Western saints too
WESTERN_ORTHODOX_WIKI = "P14653"    # pre-Schism Western saints, and some independent bishops
PEOPLE, GROUPS = {"Q5"}, {"Q16334295", "Q14756018"}
SCHISM = 1054
# saints whose feast day Wikidata gives with nothing to say the Orthodox Church does not keep it
NOT_ORTHODOX = {
    "Q437869",      # Evagrius Ponticus, condemned with Origen in 553
    "Q942517",      # Paul of Kolomna, a saint of the Old Believers
}

ORTHODOX = re.compile(r"orthodox|православн|ορθόδοξ|pravoslav|ortodox|\bРПЦЗ?\b", re.I)
# the Oriental churches: a saint they name is theirs, whatever else Wikidata says (it gives
# "Eastern Orthodoxy" as the religion of Syriac and Ethiopian saints too)
ORIENTAL = re.compile(r"syriac|syrian orthodox|jacobite|coptic|armenian apostolic|armenian church|ethiopia|"
                      r"eritrea|malankara|indian orthodox|oriental orthodox|tewahedo|maphrian|"
                      r"коптск|армянск\w* апостольск|яковит|эфиоп|маланкар|сиро-", re.I)
ORIENTAL_NAME = re.compile(r"^(?:Mor|Mar|Abune|Abuna)\s|^Ignatius \w+ [IVX]+\b")     # Ignatius Elias III
NONCANONICAL = re.compile(r"non-?canonical|неканоническ|old[- ]calendarist|старостильн|stilist", re.I)
GENERIC = re.compile(r"^(?:eastern orthodoxy|orthodoxy|orthodox christianity|eastern orthodox christianity)$", re.I)
# the Orthodox Church as a whole, not one of its churches ("Serbian Orthodox Church")
WHOLE_CHURCH = re.compile(r"^(?:the )?(?:eastern )?orthodox (?:catholic )?church$", re.I)
OLD_BELIEVERS = re.compile(r"old believer|old[- ]rite|старообряд|старовер|беглопопов|белокриниц", re.I)
WESTERN = re.compile(r"\b(?:italy|italian|spain|spanish|france|french|francia|germany|german|portugal|portuguese|"
                     r"poland|polish|belgium|belgian|netherlands|dutch|austria|austrian|hungary|hungarian|mexico|"
                     r"mexican|brazil|brazilian|argentin\w*|colombia\w*|chile\w*|peru\w*|philippine\w*|filipin\w*|"
                     r"united states|american|canada|canadian|england|english|scotland|scottish|united kingdom|"
                     r"british|ireland|irish|papal states|holy roman empire|aragon|castile|navarre|naples|sicily|"
                     r"venice|milan|tuscany|savoy|bavaria|habsburg|croatia|croatian|slovenia|slovakia|czech|"
                     r"bohemia|kingdom of the two sicilies|slovak\w*|czech\w*|czechoslovak\w*)\b", re.I)
CATHOLIC_WORDS = re.compile(r"catholic|jesuit|dominican|franciscan|capuchin|carmelite|benedictine|salesian|"
                            r"cistercian|augustinian|ursuline|oratorian|\bpope\b|cardinal|католич|иезуит|"
                            r"доминикан|францискан|капуцин|кармелит|бенедиктин|кардинал", re.I)
EASTERN = re.compile(r"russia|russian|soviet|muscovy|moscow|novgorod|pskov|vladimir|suzdal|tver|ryazan|kievan|"
                     r"\bkiev|kyiv|ukrain|belarus|byzantine|eastern roman|ottoman|greece|greek|serbia|serbian|"
                     r"montenegr|bulgaria|romania|wallachia|moldavia|georgia|cyprus|macedonia|alaska|athonite|athos|"
                     r"optina|pechersk|perm\b|polotsk|smolensk|chernigov|rostov|росси|русск|византи|греч|серб|"
                     r"болгар|грузин|румын|афон|оптин|печерск", re.I)
EAST_LETTERS = re.compile(r"[Ѐ-ӿͰ-Ͽ]")


def orthodox(it: dict) -> list[str]:
    """Why the item is an Eastern Orthodox saint (empty: it is not, or we cannot tell)."""
    churches, descs, labels = it["churches"], list(it["descs"].values()), it["labels"]
    if it["qid"] in NOT_ORTHODOX:
        return []
    if any(OLD_BELIEVERS.search(t) for t in [*churches, *descs, *labels.values()]):
        return []
    if any(ORIENTAL.search(t) for t in [*churches, *descs, *it["countries"]]) or \
            ORIENTAL_NAME.match(labels.get("en", "")):
        return []
    if any(NONCANONICAL.search(d) for d in descs):
        return []
    sainted = bool(it["titles"] & CATHOLIC_TITLES) or it["canonized_by"]      # by the Catholic Church
    catholic = sainted or any(CATHOLIC_WORDS.search(c) and not ORTHODOX.search(c) for c in churches)
    named = [c for c in churches if ORTHODOX.search(c) and not GENERIC.match(c.strip())]
    died = it["died"] if it["died"] is not None else it["born"]
    if sainted and died is not None and died > SCHISM and all(WHOLE_CHURCH.match(c.strip()) for c in named):
        return []       # a Catholic saint from after the Schism, unless an Orthodox church keeps them too
    western = (catholic or any(WESTERN.search(c) for c in it["countries"])
               or any(CATHOLIC_WORDS.search(d) for d in descs)
               or any(WESTERN.search(d) for d in descs if not EASTERN.search(d)))
    eastern = any(EASTERN.search(c) for c in it["countries"]) or any(EASTERN.search(d) for d in descs)
    why = []
    if named:
        why.append("church")
    if it["titles"] & ORTHODOX_TITLES:
        why.append("title")
    if any(ORTHODOX.search(d) for d in descs):
        why.append("description")
    if it["ids"] & ORTHODOX_REFERENCES:
        why.append("Orthodox reference")
    if why:
        return why
    # what East and West share, for a saint of the East (by country or description), or of the
    # Orthodox faith (Wikidata's religion), or named only in the Eastern alphabets
    shared = bool(it["titles"] & SHARED_TITLES)
    encyclopedia = ENCYCLOPEDIA in it["ids"]
    generic = any(GENERIC.match(c.strip()) for c in churches)
    if not western:
        if (shared or encyclopedia or generic) and eastern:
            return ["of the East"]
        if generic and (shared or SAINT in it["titles"]):
            return ["of the Orthodox faith"]
        if (it["titles"] & (SHARED_TITLES - WEST_TOO) or encyclopedia) and not labels.get("en") and \
                any(EAST_LETTERS.search(v) for v in labels.values()):
            return ["of the East"]
    if WESTERN_ORTHODOX_WIKI in it["ids"] and not catholic and died is not None and died <= SCHISM:
        return ["Western saint before the Schism"]
    return []


def shift_day(day: tuple[int, int], days: int) -> tuple[int, int]:
    d = dt.date(S.REF_YEAR, *day) + dt.timedelta(days=days)
    return d.month, d.day


def church_days(it: dict) -> list[tuple[int, int]]:
    """The feast days as church dates: a civil date given beside its church date is dropped."""
    days = it["feasts"]
    return sorted(d for d in days if shift_day(d, -S.JULIAN_OFFSET) not in days)


# ---------------------------------------------------------------- names

# the title a name is given, singular and plural, most specific first
_TITLES = [
    ("Q2993173", "Hieromartyr", "Hieromartyrs"), ("Q4377390", "Venerable-martyr", "Venerable-martyrs"),
    ("Q3332786", "Great-martyr", "Great-martyrs"), ("Q2389950", "New Martyr", "New Martyrs"),
    ("Q2032316", "Passion-bearer", "Passion-bearers"), ("Q619869", "Equal-to-the-Apostles", "Equals-to-the-Apostles"),
    ("Q4087714", "Right-believing", "Right-believing"), ("Q16745627", "Righteous", "Righteous"),
    ("Q12299587", "Blessed", "Blessed"), ("Q2354129", "Confessor", "Confessors"),
    ("Q12774503", "Venerable", "Venerables"), ("Q401642", "Venerable", "Venerables"),
    ("Q2303143", "Venerable", "Venerables"), ("Q1066990", "Venerable", "Venerables"),
]
_BY_DESCRIPTION = [
    (re.compile(r"hieromartyr|священномуч", re.I), "Hieromartyr", "Hieromartyrs"),
    (re.compile(r"new martyr|новомуч", re.I), "New Martyr", "New Martyrs"),
    (re.compile(r"martyr|мучени", re.I), "Martyr", "Martyrs"),
    (re.compile(r"\bmonk|\bnun\b|ascetic|hermit|abbot|abbess|hegumen|monastic|преподоб|монах|игумен|подвижни",
                re.I), "Venerable", "Venerables"),
]
_HAS_TITLE = re.compile(r"^(?:St\.?|Sts\.?|Saints?|Venerables?|Martyrs?|Hieromartyrs?|Great-?martyrs?|New Martyrs?|"
                        r"Blessed|Righteous|Holy|Apostles?|Prophet(?:ess)?|Equals?-to-the-Apostles|"
                        r"Right-believing|Passion-bearers?|Confessors?|Pope|Patriarch)\b", re.I)


_ROMANCE = re.compile(r"\s(?:de|di|da|du|des|del|della|dei|le|la|el|o|von|van|vom|zu)\s|\sd'")   # 'Macaire le Romain'
_PATRONYMIC = re.compile(r"^([A-Z][a-z]+) [A-Z][a-z]+(?:ovich|evich|ovna|evna|ichna) ([A-Z][\w'-]+)$")


_PATRONYMIC_RU = re.compile(r"(?:ович|евич|ич|овна|евна|ична)$")
_SAINT = re.compile(r"^(?:Saints?|Sts?\.?)\s+")
# Russian names in the nominative that the renderer's table lacks, and epithets
_RU_WORDS = {
    "ilja": "Elijah", "arefa": "Arethas", "mina": "Menas", "dorofej": "Dorotheus", "faddej": "Thaddeus",
    "jakov": "James", "karp": "Carpus", "nikola": "Nicholas", "dmitrij": "Demetrius", "fedor": "Theodore",
    "tit": "Titus", "voin": "the Soldier",
    "otshelnik": "the Hermit", "trudoljubivyj": "the Lover of Labor", "postnik": "the Faster",
    "molchalnik": "the Silent", "zatvornik": "the Recluse", "chudotvorec": "the Wonderworker",
    "bogougodnik": "the God-pleaser", "volhv": "the former Magician", "plachlivyj": "the Weeper",
}

# first names as the Church's English calls the saints (the directory says "Theodore Ushakov",
# Wikidata "Fyodor Ushakov"): Russian, Ukrainian, Serbian, Romanian and Greek forms
ENGLISH_FIRST = {k: v for v, ks in {
    "Theodore": "fyodor fedor feodor fedir teodor theodoros", "John": "ivan ioann jovan ioan ioannis",
    "James": "yakov iakov yakiv iakovos", "Basil": "vasily vasiliy vasilii vasyl vasilije vasile vasileios",
    "Joseph": "iosif osip yosyp", "Eugene": "evgeny yevgeny evgeniy yevgeniy",
    "Constantine": "konstantin konstantinos", "Elijah": "ilya ilia iliya illia ilija ilie ilias",
    "George": "yegor egor georgy georgiy heorhiy heorhii djordje dorde georgije gheorghe georgios",
    "Cyril": "kirill kyrillos", "Peter": "pyotr petr petro petar petru petros",
    "Alexis": "aleksey aleksei alexey aleksiy oleksiy oleksii", "Michael": "mikhail mykhailo mihailo mihail michail",
    "Nicholas": "nikolai nikolay mykola nikolaj nicolae nikolaos", "Paul": "pavel pavlo pavle pavlos",
    "Demetrius": "dmitry dmitriy dmitrii dmytro dimitrije dimitrie dimitrios", "Gregory": "grigory grigoriy "
    "hryhoriy hryhorii grigorije grigorie grigorios", "Sergius": "sergei sergey sergiy serhiy serhii",
    "Andrew": "andrei andrey andriy andrii andreas", "Simeon": "semyon simion", "Stephen": "stepan stefan stefanos",
    "Matthew": "matvei matvey matthaios", "Philip": "filipp filippos", "Thomas": "foma", "Leo": "lev",
    "Alexander": "aleksandr oleksandr", "Vladimir": "volodymyr", "Sabbas": "savva sava savvas",
    "Nicetas": "nikita", "Luke": "luka loukas", "Jonah": "iona", "Zosimas": "zosima", "Barnabas": "varnava",
    "Cosmas": "kuzma kozma kosmas", "Dorotheus": "dorofey dorofei dorotheos", "Thaddeus": "faddey faddei",
    "Tarasius": "tarasy tarasiy", "Prochorus": "prokhor prohor", "Arsenius": "arseny arseniy arsenii arsenije "
    "arsenios", "Athanasius": "afanasy afanasiy afanasii athanasios", "Gabriel": "gavriil gavril gavrilo",
    "Seraphim": "serafim serafeim", "Macarius": "makary makariy makarii makarije makarios",
    "Euthymius": "yevfimy evfimiy efthymios", "Ignatius": "ignaty ignatiy ignatios",
    "Nicephorus": "nikifor", "Sophronius": "sofrony sofroniy sofronie", "Bessarion": "visarion",
    "Glycerius": "glicherie", "Paisius": "paisy paisiy pajsije paisie paisios", "Ephraim": "yefrem efrem jefrem",
    "Abraham": "avraamy avraamiy avraam", "Anthony": "antoniy antonie antonios", "Theodosius": "feodosy "
    "feodosiy teodosiy", "Theophanes": "feofan", "Theophilus": "feofil", "Herman": "german",
    "Gerasimus": "gerasim gerasimos", "Leontius": "leonty leontiy", "Dionysius": "dionisy dionisiy dionysios",
    "Nectarius": "nektarios", "Procopius": "prokopy prokopios", "Porphyrius": "porfyrios",
    "Aristides": "aristidis", "Daniel": "daniil", "Callinicus": "calinic", "Methodius": "mefody methodios",
    "Joachim": "ioakeim", "Anthimus": "anthimos", "Titus": "tit",
}.items() for k in ks.split()}


def english_first(name: str) -> str:
    """'Fyodor Ushakov' -> 'Theodore Ushakov' (only the first word, only Russian forms)."""
    first, _, rest = name.partition(" ")
    eng = ENGLISH_FIRST.get(fold(first))
    return f"{eng} {rest}".strip() if eng else name


def russian_name(label: str, female: bool = False) -> str:
    """Wikidata's Russian name of a person ('Surname, Name Patronymic', or 'Name Patronymic
    Surname') as saintd renders Russian names in English: 'Грудинский, Пётр Феофилович' ->
    'Peter Grudinsky'. A woman's name is transliterated (the renderer is made for calendar
    titles, where 'Александра' is 'of Alexander')."""
    label = label.strip()
    m = re.match(r"^([^,()]+),\s*(\S+)(?:\s+\S+)?\s*$", label)
    if m:
        label = f"{m.group(2)} {m.group(1).strip()}"
    words = label.split()
    if len(words) == 3 and _PATRONYMIC_RU.search(words[2]):
        label = f"{words[1]} {words[0]}"               # 'Ефимов Николай Сергеевич'
    elif len(words) == 3 and _PATRONYMIC_RU.search(words[1]):
        label = f"{words[0]} {words[2]}"
    if female:
        return translit(label)
    # the renderer reads calendar titles, in the genitive ('Саввы'): a name in the nominative
    # ('Савва') is looked up as it stands, and so are the epithets it does not know
    out = []
    for w in label.replace("-", " ").split():         # 'Тит-Воин'
        word = w.strip("()")                          # 'Тарасий (Глушицкий)'
        key = ru.cyr_slug(word)
        eng = ru.NAMES.get(key) or _RU_WORDS.get(key) or ru.ru_text_english(word)
        if eng:
            out.append(f"({eng})" if w.startswith("(") and w.endswith(")") else eng)
    return " ".join(out)


def kind_of(it: dict) -> str | None:
    """'saint', 'group', or None for an item that is neither (an icon, a feast, a church)."""
    if it["types"] & GROUPS:
        return "group"
    if it["types"] & PEOPLE:
        return "saint"
    return None


_FOREIGN_TITLE = re.compile(r"^(?:Osios|Hosios|Osia|Hosia|Agios|Hagios|Agia|Hagia|Agioi|Sveti|Sveta|Sfântul|Sfânta|"
                            r"Sfinții|Prepodobni|Prepodobna|Prepodobnyy|Prepodobnyi|Prepodobny|Prepodobnaya|Svyatoy|"
                            r"Svyatoi|Svyataya|Svyatitel|Svyashchennomuchenik|Muchenik|Muchenitsa|Blazhennyy|"
                            r"Blazhennaya|Pravednyy|Pravednaya)\s+", re.I)


def plain_name(label: str) -> str:
    """A name with no title before it: 'Osios Serafeim', 'Prepodobnyy Evfrosin', 'Saint Paul'."""
    return _SAINT.sub("", _FOREIGN_TITLE.sub("", label.strip())).strip()


def spelled(label: str) -> str:
    """A Cyrillic name in Latin letters, in the order the directory gives names:
    'Ефимов, Николай Сергеевич' -> 'Nikolai Efimov' (the calendars' English spells some so)."""
    label = label.strip()
    m = re.match(r"^([^,()]+),\s*(\S+)(?:\s+\S+)?\s*$", label)
    if m:
        label = f"{m.group(2)} {m.group(1).strip()}"
    words = label.split()
    if len(words) == 3 and _PATRONYMIC_RU.search(words[2]):
        label = f"{words[1]} {words[0]}"               # 'Ефимов Николай Сергеевич'
    elif len(words) == 3 and _PATRONYMIC_RU.search(words[1]):
        label = f"{words[0]} {words[2]}"
    return translit(label)


def wiki_title(title: str) -> str:
    """An English Wikipedia title as a name: 'Paul (bishop of Kolomna)' -> 'Paul', but
    'Hilarion (Troitsky)' stays."""
    return re.sub(r"\s*\((?=[^)]*\b[a-z])[^)]*\)$", "", (title or "").replace("_", " ")).strip()


_TRANSLIT_END = re.compile(r"(?:iy|yy|ij|yj|ec|ets)$")
ENGLISH_NAMES = set(ENGLISH_FIRST.values()) | set(ru.NAMES.values()) | {v for v in _RU_WORDS.values() if " " not in v}


def _transliterated(en: str, ru_en: str) -> bool:
    """Is Wikidata's English label only a transliteration ('Agaton Divotvorec', 'Iliya
    Pecherskiy'), so that the Russian name reads better in English?"""
    ew, rw = en.split(), ru_en.split()
    return bool(ew and rw) and rw[0] in ENGLISH_NAMES and (
        ew[0] not in ENGLISH_NAMES or any(_TRANSLIT_END.search(w) for w in ew[1:])
        or bool(re.search("[ĉĝĥĵŝŭ]", en)))         # Esperanto letters: 'Miĥail Aleksandroviĉ'


def english_name(it: dict) -> tuple[str, str] | None:
    """(name as the directory shows it, 'saint' or 'group'), or None when the item is not a
    person or a group, or has no name in English or Russian. The English Wikipedia's title
    comes first: Wikidata's English label is often the name in the saint's own language
    ('Grigorije of Gornjak', 'Osios Serafeim Domvous'), or a transliteration of the Russian."""
    kind = kind_of(it)
    if kind is None:
        return None
    female = it["gender"] == "Q6581072"
    wiki = wiki_title(it["enwiki"])
    en = plain_name(wiki or it["labels"].get("en", ""))
    ru_label = it["labels"].get("ru", "")
    ru_en = russian_name(ru_label, female=female) if ru_label else ""
    if ru_en and not female:
        ru_en = english_first(ru_en)
    if en and _ROMANCE.search(en) and not ru_label:
        return None                     # named only in Spanish, French or Italian
    if en and not has_cyrillic(en) and not (ru_label and _ROMANCE.search(en)):
        base = english_first(_PATRONYMIC.sub(r"\1 \2", en))
        if ru_en and not wiki and _transliterated(base, ru_en):
            base = ru_en
    elif ru_en:
        base = ru_en
    else:
        return None
    base = re.sub(r"\s+", " ", base).strip(" ,")
    if len(base) < 3:
        return None
    if _HAS_TITLE.match(base):
        return base, kind
    plural = kind == "group"
    title = next((pl if plural else sg for q, sg, pl in _TITLES if q in it["titles"]), "")
    if not title:
        descs = " ".join(it["descs"].get(lang, "") for lang in ("en", "ru"))
        title = next((pl if plural else sg for rx, sg, pl in _BY_DESCRIPTION if rx.search(descs)), "")
    return f"{title or ('Sts' if plural else 'St')} {base}", kind


def century(it: dict) -> int | None:
    """The century the saint died in (or, with no date of death, was born in)."""
    y = it["died"] if it["died"] is not None else it["born"]
    if y is None:
        return None
    return (y - 1) // 100 + 1 if y > 0 else -((-y - 1) // 100 + 1)


GENDERS = {"Q6581097": "Male", "Q6581072": "Female"}

__all__ = ["QUERIES", "church_days", "century", "english_first", "english_name", "fetch", "kind_of", "orthodox",
           "plain_name", "russian_name", "shift_day", "spelled", "wiki_title"]
