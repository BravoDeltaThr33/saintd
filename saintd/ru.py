"""Offline Russian -> English helpers for commemorations from the Russian
church calendar (Azbuka Very). These make the app fully English even when
no online translator is configured; a configured translator or a Wikidata
match replaces these rough renderings with better English."""

from __future__ import annotations

import html
import re

from .heuristics import roman_to_int, year_to_century
from .text import strip_stress, translit

# ---------------------------------------------------------------- titles
# abbreviation -> (English title, gender hint, is_plural)
TITLES: dict[str, tuple[str, str | None, bool]] = {
    "сщмч.": ("Hieromartyr", "Male", False), "сщмчч.": ("Hieromartyrs", None, True),
    "свщмч.": ("Hieromartyr", "Male", False), "свщмчч.": ("Hieromartyrs", None, True),
    "мч.": ("Martyr", "Male", False), "мчч.": ("Martyrs", None, True),
    "мц.": ("Martyr", "Female", False), "мцц.": ("Martyrs", "Female", True),
    "вмч.": ("Great-martyr", "Male", False), "вмчч.": ("Great-martyrs", None, True),
    "вмц.": ("Great-martyr", "Female", False), "вмцц.": ("Great-martyrs", "Female", True),
    "прмч.": ("Venerable-martyr", "Male", False), "прмчч.": ("Venerable-martyrs", None, True),
    "прмц.": ("Venerable-martyr", "Female", False), "прмцц.": ("Venerable-martyrs", "Female", True),
    "прп.": ("Venerable", None, False), "прпп.": ("Venerables", None, True),
    "свт.": ("St", "Male", False), "свтт.": ("Saints", None, True),
    "ап.": ("Apostle", "Male", False), "апп.": ("Apostles", None, True),
    "прор.": ("Prophet", "Male", False), "прорр.": ("Prophets", None, True),
    "пророчицы": ("Prophetess", "Female", False),
    "прав.": ("Righteous", None, False), "правв.": ("Righteous", None, True),
    "блж.": ("Blessed", None, False), "блжж.": ("Blessed", None, True),
    "блгв.": ("Right-believing", None, False), "блгвв.": ("Right-believing", None, True),
    "равноап.": ("Equal-to-the-Apostles", None, False), "равноапп.": ("Equals-to-the-Apostles", None, True),
    "исп.": ("Confessor", None, False), "испп.": ("Confessors", None, True),
    "св.": ("St", None, False), "свв.": ("Saints", None, True),
    "бессрр.": ("Unmercenaries", None, True), "бессребр.": ("Unmercenary", None, False),
    "страстотерпца": ("Passion-bearer", "Male", False), "страстотерпцев": ("Passion-bearers", None, True),
    "новомч.": ("New Martyr", "Male", False), "новосщмч.": ("New Hieromartyr", "Male", False),
    "праотец": ("Forefather", "Male", False), "праотцев": ("Forefathers", None, True),
}

ROLE_WORDS: list[tuple[str, str]] = [
    ("архиепископа", "Archbishop"), ("епископа", "Bishop"), ("еп.", "Bishop"), ("митрополита", "Metropolitan"),
    ("патриарха", "Patriarch"), ("папы", "Pope"), ("пресвитера", "Presbyter"), ("пресвитеров", "Presbyters"),
    ("диакона", "Deacon"), ("архидиакона", "Archdeacon"), ("иеромонаха", "Hieromonk"),
    ("иеросхимонаха", "Hieroschemamonk"), ("архимандрита", "Archimandrite"), ("игумена", "Abbot"),
    ("игумении", "Abbess"), ("монаха", "Monk"), ("монахини", "Nun"), ("затворника", "Recluse"),
    ("чудотворца", "Wonderworker"), ("юродивого", "Fool-for-Christ"), ("Христа ради юродивого", "Fool-for-Christ"),
    ("исповедника", "Confessor"), ("царя", "King"), ("царицы", "Queen"), ("императора", "Emperor"),
    ("императрицы", "Empress"), ("князя", "Prince"), ("княгини", "Princess"), ("девы", "Virgin"),
    ("девицы", "Virgin"), ("воина", "Soldier"), ("воинов", "Soldiers"), ("отшельника", "Hermit"),
    ("постника", "Faster"), ("просветителя", "Enlightener"), ("просветительницы", "Enlightener"),
    ("врача", "Physician"), ("чтеца", "Reader"), ("канонарха", "Canonarch"), ("черноризца", "Monk"),
]

FEAST_RX = re.compile(
    r"^(Предпразднство|Попразднство|Отдание|Рождество|Введение|Богоявление|Крещение|Сретение|Благовещение|"
    r"Успение|Преображение|Воздвижение|Покров Пресвятой|Обрезание|Память святых отцов|Праздник|"
    r"Происхождение|Положение (?:честн|ризы|пояса)|Перенесение (?:нерукотворного|честн)|Обновление|"
    r"Неделя|Суббота|Собор Пресвятой|Собор Иоанна Предтечи|Собор Архистратига)",
)
ICON_RX = re.compile(r"\b[Ии]кон[аыуе]")
SYNAXIS_RX = re.compile(r"^Собор|^Память всех|^преподобных отец|^святых отцов", re.I)

# --------------------------------------------------------------- names
_NAMES_SRC = """
aaron=Aaron abraamij=Abraham avraamij=Abraham avramij=Abraham avraam=Abraham agafangel=Agathangelus
agapit=Agapetus agafon=Agatho agafonik=Agathonicus akakij=Acacius aleksandr=Alexander aleksij=Alexis
aleksej=Alexis alipij=Alypius amvrosij=Ambrose anastasij=Anastasius anatolij=Anatolius andrej=Andrew
andronik=Andronicus anikita=Anicetus antipa=Antipas antonij=Anthony antoniy=Anthony arkadij=Arcadius
arsenij=Arsenius artemij=Artemius afanasij=Athanasius afinogen=Athenogenes ahaz=Ahaz
varlaam=Barlaam varnava=Barnabas varfolomej=Bartholomew varsonofij=Barsanuphius vasilij=Basil
venedikt=Benedict veniamin=Benjamin viktor=Victor vikentij=Vincent vissarion=Bessarion vitalij=Vitalis
vladimir=Vladimir vlasij=Blaise vonifatij=Boniface gavriil=Gabriel galaktion=Galacteon gennadij=Gennadius
georgij=George gerasim=Gerasimus german=Herman gerontij=Gerontius gleb=Gleb gordij=Gordius
grigorij=Gregory gurij=Gurias daniil=Daniel david=David dimitrij=Demetrius dionisij=Dionysius
dometian=Dometian dosifej=Dositheus evgenij=Eugene evdokim=Eudocimus evfimij=Euthymius
evstafij=Eustathius evstratij=Eustratius evsevij=Eusebius evtihij=Eutychius evpsihij=Eupsychius
efrem=Ephraim zaharija=Zacharias zinovij=Zenobius zosima=Zosimas ilarion=Hilarion ilija=Elijah
ilia=Elijah innokentij=Innocent ioann=John ioannikij=Joannicius ioakim=Joachim iov=Job iona=Jonah
iosif=Joseph ioasaf=Joasaph iakov=James isaakij=Isaac isaak=Isaac isaija=Isaiah isidor=Isidore
iulian=Julian iulij=Julius iustin=Justin iustinian=Justinian ignatij=Ignatius irinarh=Irenarchus
irinej=Irenaeus kallinik=Callinicus kallistrat=Callistratus kassian=Cassian kesarij=Caesarius
kiprian=Cyprian kirill=Cyril kirik=Cyricus klavdij=Claudius kliment=Clement kondrat=Quadratus
konstantin=Constantine kornilij=Cornelius kosma=Cosmas kuzma=Cosmas lavrentij=Lawrence lazar=Lazarus
lev=Leo leonid=Leonidas leontij=Leontius luka=Luke lup=Lupus makarij=Macarius maksim=Maximus
mamant=Mammes mark=Mark martinian=Martinian matfej=Matthew mefodij=Methodius merkurij=Mercurius
mitrofan=Mitrophan mihail=Michael moisej=Moses mokij=Mocius nazarij=Nazarius nektarij=Nectarius
nestor=Nestor nikandr=Nicander nikita=Nicetas nikifor=Nicephorus nikodim=Nicodemus nikolaj=Nicholas
nikon=Nikon nil=Nilus onisifor=Onesiphorus onufrij=Onuphrius pavel=Paul paisij=Paisius pantelejmon=Panteleimon
parfenij=Parthenius pafnutij=Paphnutius pahomij=Pachomius petr=Peter pimen=Poemen pitirim=Pitirim
platon=Plato polikarp=Polycarp porfirij=Porphyrius prohor=Prochorus prokopij=Procopius roman=Romanus
savva=Sabbas samuil=Samuel sevastian=Sebastian serafim=Seraphim serapion=Serapion sergij=Sergius
silvestr=Sylvester silvan=Silvanus simeon=Simeon simon=Simon sisoj=Sisoes sozont=Sozon spiridon=Spyridon
stefan=Stephen tarasij=Tarasius tertij=Tertius terentij=Terence tihon=Tikhon timofej=Timothy
trifon=Tryphon urpasian=Urpasian feodor=Theodore feodosij=Theodosius feodot=Theodotus feodul=Theodulus
feognost=Theognostus feogen=Theogenes feofan=Theophanes feofil=Theophilus feofilakt=Theophylact
ferapont=Therapontus filaret=Philaret filipp=Philip filofej=Philotheus filosof=Philosophus fotij=Photius
foma=Thomas harlampij=Charalampus hristofor=Christopher erm=Hermas ermij=Hermias ermolaj=Hermolaus
evod=Evodus aviv=Abibus iperihij=Hyperechius parigorij=Paregorius archil=Archil luarsab=Luarsab
ieremij=Jeremiah ieremija=Jeremiah pavlin=Paulinus nikolaj=Nicholas antonin=Antoninus apollinarij=Apollinarius
arsenios=Arsenius vladislav=Vladislav vsevolod=Vsevolod jaroslav=Yaroslav rostislav=Rostislav boris=Boris
mstislav=Mstislav igor=Igor oleg=Oleg mihej=Micah ilija=Elijah elisej=Elisha daniil=Daniel ezekiil=Ezekiel
avdij=Obadiah naum=Nahum avvakum=Habakkuk sofonija=Zephaniah aggej=Haggai malahija=Malachi joil=Joel
amos=Amos osija=Hosea iezekiil=Ezekiel zaharija=Zechariah iisus=Joshua samson=Samson
anna=Anna marija=Mary mariia=Mary elisaveta=Elizabeth ekaterina=Catherine varvara=Barbara irina=Irene
sofija=Sophia sofia=Sophia tatiana=Tatiana tatijana=Tatiana ksenija=Xenia olga=Olga paraskeva=Paraskeva
matrona=Matrona evdokija=Eudocia evfrosinija=Euphrosyne evpraksija=Eupraxia evfimija=Euphemia
iulianija=Juliana iuliania=Juliana iulitta=Julitta pelagija=Pelagia taisija=Thais taisiya=Thais
nina=Nina feodora=Theodora feodosija=Theodosia feodotija=Theodotia serafima=Seraphima aleksandra=Alexandra
avgusta=Augusta vasilissa=Basilissa mastridija=Mastridia anastasija=Anastasia natalija=Natalia
fevronija=Febronia ljudmila=Ludmila agafija=Agatha hristina=Christina marina=Marina margarita=Margaret
lidija=Lydia fotinija=Photini tamara=Tamar vera=Faith nadezhda=Hope ljubov=Love evgenija=Eugenia
iustina=Justina kira=Kyra domnina=Domnina akilina=Aquilina glikerija=Glyceria ariadna=Ariadne
filofeja=Philothea makrina=Macrina melanija=Melania pulherija=Pulcheria zinaida=Zenaida
muza=Musa emilija=Emmelia platonida=Platonida golinduha=Golinduch hionija=Chionia elena=Helen
didim=Didymus kesarija=Caesarea feodulija=Theodulia evsevija=Eusebia
"""
NAMES: dict[str, str] = {}
for pair in _NAMES_SRC.split():
    if "=" in pair:
        k, v = pair.split("=", 1)
        NAMES[k] = v

FEMALE_TRANSLIT = {k for k, v in NAMES.items() if k.endswith(("a", "ja", "ija", "iya"))
                   and k not in {"savva", "nikita", "iona", "luka", "foma", "kosma", "kuzma", "zosima",
                                 "ilija", "ilia", "ieremija", "zaharija", "isaija", "antipa", "varnava",
                                 "sofonija", "malahija", "osija", "anikita"}}

EPITHETS: dict[str, str] = {
    "pecherskij": "of the Kiev Caves", "radonezhskij": "of Radonezh", "sarovskij": "of Sarov",
    "optinskij": "of Optina", "valaamskij": "of Valaam", "soloveckij": "of Solovki",
    "zadonskij": "of Zadonsk", "kronshtadtskij": "of Kronstadt", "moskovskij": "of Moscow",
    "kievskij": "of Kiev", "novgorodskij": "of Novgorod", "rostovskij": "of Rostov",
    "vladimirskij": "of Vladimir", "suzdalskij": "of Suzdal", "muromskij": "of Murom",
    "pskovskij": "of Pskov", "kazanskij": "of Kazan", "tverskoj": "of Tver", "jaroslavskij": "of Yaroslavl",
    "smolenskij": "of Smolensk", "egipetskij": "of Egypt", "egipetskaja": "of Egypt",
    "aleksandrijskij": "of Alexandria", "aleksandrijskaja": "of Alexandria", "antiohijskij": "of Antioch",
    "antiohijskaja": "of Antioch", "rimskij": "of Rome", "rimskaja": "of Rome",
    "konstantinopolskij": "of Constantinople", "ierusalimskij": "of Jerusalem", "kesarijskij": "of Caesarea",
    "kappadokijskij": "of Cappadocia", "nikomidijskij": "of Nicomedia", "nikomidijskaja": "of Nicomedia",
    "sinajskij": "of Sinai", "raifskij": "of Raithu", "afonskij": "of Mount Athos",
    "svjatogorec": "the Athonite", "solunskij": "of Thessalonica", "fessalonikijskij": "of Thessalonica",
    "afinskij": "of Athens", "areopagit": "the Areopagite", "bogoslov": "the Theologian",
    "zlatoust": "Chrysostom", "chudotvorec": "the Wonderworker", "pobedonosec": "the Victory-bearer",
    "velikij": "the Great", "grek": "the Greek", "palama": "Palamas", "ispovednik": "the Confessor",
    "jurodivyj": "the Fool-for-Christ", "pravednyj": "the Righteous", "nazianzin": "of Nazianzus",
    "tarsijskij": "of Tarsus", "kilikijskij": "of Cilicia", "vifinskij": "of Bithynia",
    "halkidonskij": "of Chalcedon", "ikonijskij": "of Iconium", "gruzinskij": "of Georgia",
    "serbskij": "of Serbia", "bolgarskij": "the Bulgarian", "permskij": "of Perm",
    "velikopermskij": "of Great Perm", "sibirskij": "of Siberia", "tobolskij": "of Tobolsk",
    "irkutskij": "of Irkutsk", "chernigovskij": "of Chernigov", "pochaevskij": "of Pochaev",
    "belgorodskij": "of Belgorod", "voronezhskij": "of Voronezh", "tambovskij": "of Tambov",
    "vologodskij": "of Vologda", "beloezerskij": "of Beloozero", "svirskij": "of Svir",
    "tihvinskij": "of Tikhvin", "ladozhskij": "of Ladoga", "vjatskij": "of Vyatka",
    "dalmatskij": "of Dalmatia", "komanskij": "of Comana", "likijskij": "of Lycia",
    "mirlikijskij": "of Myra in Lycia", "mirlikijskij": "of Myra in Lycia", "iverskij": "of Iberia",
    "mchetskij": "of Mtskheta", "kartalinskij": "of Kartli", "elladskij": "of Hellas",
    "lampsakijskij": "of Lampsacus", "parijskij": "of Parium", "emesskij": "of Emesa",
    "samosatskie": "of Samosata", "drugoj": "", "i": "I", "ii": "II", "iii": "III",
    "kanonarh": "", "presviter": "", "diakon": "", "episkop": "", "imperatrica": "", "imperatritsa": "",
    "carica": "", "voin": "", "otshelnik": "", "postnik": "", "monah": "", "igumen": "", "mitropolit": "",
    "arhiepiskop": "", "apostol": "", "chernorizec": "", "vrach": "", "deva": "", "prosvetitelnica": "",
    "gruzii": "of Georgia", "muchenik": "", "muchenica": "", "carica": "", "car": "", "knjaz": "",
    "knjaginja": "", "bogonosec": "the God-bearer", "gruzija": "of Georgia", "rossija": "of Russia",
    "serbija": "of Serbia", "amerika": "of America", "japonija": "of Japan", "sibir": "of Siberia",
    "alaska": "of Alaska", "egipet": "of Egypt", "kitaj": "of China", "palestina": "of Palestine",
    "sotnik": "the Centurion", "stratilat": "Stratelates", "tiron": "Tyro", "celitel": "the Healer",
    "bessrebrenik": "the Unmercenary", "strastoterpec": "the Passion-bearer", "molchalnik": "the Silent",
    "zatvornik": "the Recluse", "stolpnik": "the Stylite", "pustynnik": "the Hermit", "novyj": "the New",
    "mladshij": "the Younger", "starshij": "the Elder", "starec": "the Elder", "ikonopisec": "the Iconographer",
    "letopisec": "the Chronicler", "mirotochivyj": "the Myrrh-streaming", "egiptjanin": "the Egyptian",
    "persjanin": "the Persian", "rimljanin": "the Roman", "serb": "the Serb", "bolgarin": "the Bulgarian",
    "gruzin": "the Georgian", "fivaidskij": "of the Thebaid", "bogoprimec": "the God-receiver",
    "bogopriimec": "the God-receiver", "predtecha": "the Forerunner", "krestitel": "the Baptist",
    "mnogostradalnyj": "the Long-suffering", "mnogoboleznennyj": "the Much-ailing", "blazhennyj": "",
    "pravednyj": "the Righteous", "prepodobnyj": "", "svjatoj": "", "kievskij": "of Kiev",
    "bliznec": "", "zevedeev": "son of Zebedee", "alfeev": "son of Alphaeus",
    "damaskin": "of Damascus", "dekapolit": "of the Decapolis", "sinait": "of Sinai", "savvait": "the Sabbaite",
    "studit": "the Studite", "svjatogorec": "the Athonite", "kipr": "of Cyprus", "kiprskij": "of Cyprus",
    "lionskij": "of Lyons", "lerinskij": "of Lerins", "sevastijskij": "of Sebaste", "tirskij": "of Tyre",
    "apamejskij": "of Apamea", "gangrskij": "of Gangra", "efesskij": "of Ephesus", "smirnskij": "of Smyrna",
    "korinfskij": "of Corinth", "persidskij": "of Persia", "italijskij": "of Italy", "indijskij": "of India",
    "rimljanynja": "the Roman", "rimljanka": "the Roman", "persjanka": "the Persian", "egiptjanka": "the Egyptian",
    "palestinskij": "of Palestine", "diveevskij": "of Diveyevo", "arhangelskaja": "of Arkhangelsk",
    "zlatoustyj": "Chrysostom", "milasskij": "of Mylasa",
    "sirskij": "of Syria", "kostromskoj": "of Kostroma", "vilenskij": "of Vilna", "eleckij": "of Yelets",
    "otrokovica": "", "peterburgskij": "of St Petersburg", "sankt-peterburgskij": "of St Petersburg",
    "efiopskij": "of Ethiopia", "frakijskij": "of Thrace", "kritskij": "of Crete", "kesarijskij": "of Caesarea", "upravda": "", "grecheskaja": "", "starorusskij": "of Staraya Russa",
}


def _translit_slug_token(tok: str) -> str:
    t = re.sub(r"(?<![csz])h", "kh", tok)
    t = t.replace("skaja", "skaya").replace("ij", "y").replace("ja", "ya").replace("ju", "yu")
    return t.capitalize()


def english_name_from_slug(slug: str) -> str:
    """'sv-marija-egipetskaja' -> 'Mary of Egypt'. Multi-saint slugs
    ('svv-...') become 'A, B and C'."""
    s = (slug or "").split("#")[0]
    s = re.sub(r"^(?:svv?|sv)-", "", s)
    s = re.sub(r"-(?:\d+|drugoj|presviter|muchenik|apostol|deva)$", "", s)
    toks = [t for t in s.split("-") if t]
    # "evfrosinija-v-miru-feodulija" (in the world Theodulia), "golinduha-vo-svjatom-kreshhenii-marija"
    alt_at: set[int] = set()
    for intro in (["v", "miru"], ["vo", "svjatom", "kreshhenii"], ["v", "kreshhenii"], ["vo", "kreshhenii"],
                  ["vo", "svjatom", "kreshchenii"], ["v", "kreshchenii"], ["vo", "kreshchenii"]):
        i = 0
        while i <= len(toks) - len(intro):
            if toks[i:i + len(intro)] == intro:
                del toks[i:i + len(intro)]
                alt_at.add(i)
            else:
                i += 1
    if not toks:
        return ""
    multi = (slug or "").startswith("svv-")
    people: list[list[str]] = []
    prev_adj = False
    for i, t in enumerate(toks):
        is_adj = epithet(t) is not None or t.endswith(("skij", "ckij", "skaja", "ckaja", "skie", "skoj"))
        if i in alt_at and people:
            people[-1].append(f"({NAMES.get(t, _translit_slug_token(t))})")
            prev_adj = False
            continue
        if not people:
            people.append([NAMES.get(t, _translit_slug_token(t))])
        elif t in NAMES and not multi and len(people[-1]) == 1:
            people[-1].append(f"({NAMES[t]})")          # alternative name
        elif (t in NAMES and multi) or (multi and prev_adj and not is_adj):
            people.append([NAMES.get(t, _translit_slug_token(t))])
        elif epithet(t) is not None:
            e = epithet(t)
            if e and e not in people[-1]:
                if e.startswith("of ") and any(x.startswith("of ") for x in people[-1]):
                    e = f"({e})"
                people[-1].append(e)
        elif is_adj:
            people[-1].append(_translit_slug_token(re.sub(r"(ij|ie|oj)$", "y", t)))
        else:
            people[-1].append(_translit_slug_token(t))
        prev_adj = is_adj
    # drop duplicated epithets on later people ("Silvan of Emesa, Luke of Emesa")
    names = [" ".join(p) for p in people]
    names = list(dict.fromkeys(names))
    if len(names) == 1:
        return names[0]
    return ", ".join(names[:-1]) + " and " + names[-1]


# ----------------------------------------------------------- parse <li>

_HREF = re.compile(r"href=['\"]([^'\"]+)['\"]")
_TAGS = re.compile(r"<[^>]+>")
_LAST_PAREN = re.compile(r"\(([^()]*)\)\s*(?:\(Груз\.\)|\(Серб\.\)|\(Болг\.\)|\(Рум\.\)|\(Греч\.\))?\s*$")


def century_from_ru(text: str) -> int | None:
    m = _LAST_PAREN.search(text or "")
    if not m:
        return None
    inner = m.group(1)
    inner = re.sub(r"ок\.|после|около|не ранее|не позднее|конец|начало|кон\.|нач\.", "", inner).strip()
    years = re.findall(r"\b(\d{2,4})\b", inner)
    if years:
        y = int(years[-1])
        if 0 < y <= 2100:
            if "до Р. Х." in inner or "до н. э." in inner:
                y = -y
            return year_to_century(y)
    romans = re.findall(r"\b([IVXL]{1,6})\b", inner)
    if romans:
        v = roman_to_int(romans[-1])
        if v and v <= 21:
            return v
    return None


def year_from_ru(text: str) -> int | None:
    m = _LAST_PAREN.search(text or "")
    if not m:
        return None
    ys = re.findall(r"\b(\d{3,4})\b", m.group(1))
    if not ys or "до Р. Х." in m.group(1):
        return None
    y = int(ys[-1])
    return y if 30 <= y <= 2100 else None


def parse_widget(presentations_html: str, imgs: list[str] | None = None) -> list[dict]:
    """Parse the Azbuka Very 'presentations' widget into commemorations."""
    titles: dict[str, str] = {}
    for im in imgs or []:
        t = re.search(r'title="([^"]+)"', im)
        h = _HREF.search(im)
        if t and h:
            titles[h.group(1).rstrip("/").split("/")[-1]] = strip_stress(html.unescape(t.group(1))).strip()
    out = []
    used: set[str] = set()
    for li in re.findall(r"<li[^>]*>(.*?)</li>", presentations_html or "", re.S):
        h = _HREF.search(li)
        href = h.group(1) if h else ""
        slug = href.rstrip("/").split("/")[-1] if "azbyka.ru/days/" in href else ""
        if slug.startswith("p-") or "#" in slug:
            slug = ""
        text = strip_stress(html.unescape(_TAGS.sub("", li)))
        text = re.sub(r"\s+", " ", text).strip()
        if not text:
            continue
        if not slug:  # major feasts link to a legend page; recover the saint from the icon list
            for sl, nom in titles.items():
                first = nom.split()[0].strip(",") if nom else ""
                if sl in used or not sl.startswith("sv") or len(first) < 4:
                    continue
                if re.search(r"\b" + re.escape(first[:-1]), text):
                    slug, href = sl, "https://azbyka.ru/days/" + sl
                    break
        if slug:
            used.add(slug)
        out.append({
            "slug": slug,
            "href": href if slug else "",
            "ru": text,
            "ru_nominative": titles.get(slug, ""),
            "century": century_from_ru(text),
            "year": year_from_ru(text),
        })
    return out


# ------------------------------------------------------------ classify

def title_of(text: str) -> tuple[str, str | None, bool]:
    """English honorific, gender hint and plurality from the Russian text."""
    words = text.split()
    for w in words[:4]:
        key = w.lower().strip(",")
        if key in TITLES:
            return TITLES[key]
    return ("", None, False)


def kind_of(entry: dict) -> str:
    t = entry["ru"]
    if ICON_RX.search(t) or entry.get("slug", "").startswith("ikona"):
        return "icon"
    if FEAST_RX.search(t) and not re.search(r"\b(мощей|Преставление)\b", t):
        return "feast"
    _, _, plural = title_of(t)
    bare = re.sub(r"\([^)]*\)|от 70-ти|от 70", "", t)
    if plural or SYNAXIS_RX.search(t) or re.search(r"\b\d{2,}\b", bare):
        return "group"
    if entry.get("slug", "").startswith("svv-") or re.search(r"\bи с ним(и)?\b", t):
        return "group"
    if re.search(r"[А-Я][а-я]+[ая],?\s+(?:\w+,\s+)?и\s+[А-Я]", bare):
        return "group"
    if len(re.findall(r"[А-Я][а-я]+\s+[А-Я][а-я]+,", bare)) >= 2:
        return "group"
    return "saint"


def gender_of(entry: dict, kind: str) -> str:
    if kind in ("feast", "icon"):
        return "N/A"
    if kind == "group":
        return "Group"
    _, g, _ = title_of(entry["ru"])
    if g:
        return g
    if re.search(r"\b(девы|девицы|царицы|княгини|игумении|монахини|императрицы|блаженной|праведной|"
                 r"просветительницы|мученицы|преподобной|равноапостольной|пророчицы|схимонахини)\b", entry["ru"]):
        return "Female"
    slug = entry.get("slug") or ""
    first = re.sub(r"^svv?-", "", slug).split("-")[0] if slug else ""
    if first in FEMALE_TRANSLIT:
        return "Female"
    nom = entry.get("ru_nominative") or ""
    if nom:
        fn = nom.split()[0].strip(",")
        if fn.endswith(("а", "я")) and fn not in ("Савва", "Никита", "Иона", "Лука", "Фома", "Косма", "Кузьма",
                                                    "Зосима", "Илия", "Иеремия", "Захария", "Исаия", "Антипа"):
            return "Female"
    return "Male"


def offline_english(entry: dict, kind: str) -> str:
    """Readable English rendering without any online service."""
    t = entry["ru"]
    if kind == "icon":
        nm = re.sub(r"^.*?:\s*", "", t)
        nm = re.sub(r"\([^)]*\)", "", nm).strip()
        return f"Icon of the Mother of God “{translit(nm)}”" if nm else "Icon of the Mother of God"
    if kind == "feast":
        return _feast_english(t)
    title, _, _ = title_of(t)
    slug = entry.get("slug", "")
    occasion = re.match(r"(Перенесение мощей|(?:второе |первое )?[Оо]бретение мощей|Преставление)", t)
    if kind == "group" or not slug or slug.startswith("svv-") or occasion or not title:
        return ru_text_english(t)
    name = english_name_from_slug(slug)
    if title:
        name = re.sub(r"\s+the " + re.escape(title) + r"\b", "", name)
    roles = []
    low = t.lower()
    for ru_word, en in ROLE_WORDS:
        if ru_word.lower() in low and en not in roles:
            roles.append(en)
    if "отроковиц" in low:
        roles.append("Maiden")
    elif "отрок" in low:
        roles.append("Youth")
    out = f"{title} {name}".strip()
    if roles and kind != "group":
        out += ", " + roles[0]
    if kind == "group" and re.search(r"Собор\s+(\w+)\s+святых", t):
        m = re.search(r"Собор\s+(\w+)\s+святых", t)
        out = f"Synaxis of the Saints of {translit(m.group(1)).replace('skikh', '').replace('kikh', '').capitalize()}"
    return out


_FEASTS_EN = [
    ("Предпразднство", "Forefeast of"), ("Попразднство", "Afterfeast of"), ("Отдание", "Leavetaking of"),
    ("Богоявления", "Theophany"), ("Рождества Христова", "the Nativity of Christ"),
    ("Рождества Пресвятой Богородицы", "the Nativity of the Theotokos"), ("Введения", "the Entry of the Theotokos"),
    ("Сретения", "the Meeting of the Lord"), ("Благовещения", "the Annunciation"), ("Успения", "the Dormition"),
    ("Преображения", "the Transfiguration"), ("Воздвижения", "the Exaltation of the Cross"),
    ("Покрова", "the Protection of the Theotokos"), ("Память святых отцов шести Вселенских Соборов",
                                                   "Fathers of the Six Ecumenical Councils"),
]


def _feast_english(t: str) -> str:
    out = []
    for ru, en in _FEASTS_EN:
        if ru in t:
            out.append(en)
    if out:
        return " ".join(out).replace("of the the", "of the")
    return "Feast: " + translit(t)


# ------------------------------------------------- text-based rendering

_SLUG_MAP = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e", "ж": "zh", "з": "z",
    "и": "i", "й": "j", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o", "п": "p", "р": "r",
    "с": "s", "т": "t", "у": "u", "ф": "f", "х": "h", "ц": "c", "ч": "ch", "ш": "sh", "щ": "shch",
    "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "ju", "я": "ja",
}


def cyr_slug(word: str) -> str:
    """Cyrillic word -> the transliteration scheme Azbuka uses in its URLs."""
    return "".join(_SLUG_MAP.get(c, c) for c in strip_stress(word).lower())


_IRREG = {"грузии": "грузия", "сибири": "сибирь", "аляски": "аляска", "японии": "япония", "америки": "америка","павла": "павел", "льва": "лев", "марка": "марк", "петра": "петр", "игоря": "игорь",
          "луки": "лука", "фомы": "фома", "саввы": "савва", "ионы": "иона", "никиты": "никита",
          "косьмы": "косма", "космы": "косма", "кузьмы": "кузьма", "зосимы": "зосима", "илии": "илия",
          "иеремии": "иеремия", "захарии": "захария", "исаии": "исаия", "антипы": "антипа",
          "любови": "любовь"}


def denom(word: str) -> str:
    """Rough genitive -> nominative for names, surnames and epithets."""
    w = word
    low = w.lower()
    if low in _IRREG:
        out = _IRREG[low]
        return out[0].upper() + out[1:] if w[:1].isupper() else out
    rules = [
        (r"(ск|цк)ого$", r"\1ий"), (r"(ск|цк)ой$", r"\1ая"), (r"(ск|цк)их$", r"\1ий"),
        (r"(ов|ев|ин|ын)а$", r"\1"), (r"(ов|ев|ин)ой$", r"\1а"),
        (r"([гкх])ого$", r"\1ий"), (r"ого$", "ый"), (r"его$", "ий"), (r"ыни$", "ыня"),
        (r"ии$", "ия"), (r"ия$", "ий"), (r"ея$", "ей"), (r"ая$", "ай"),
        (r"([бвгджзклмнпрстфхцчшщ])ы$", r"\1а"), (r"([гкхжчшщ])и$", r"\1а"),
        (r"ца$", "ец"), (r"([бвгджзклмнпрстфхчшщ])я$", r"\1ь"),
        (r"([бвгджзклмнпрстфхцчшщ])а$", r"\1"),
    ]
    for rx, rep in rules:
        if re.search(rx, w):
            return re.sub(rx, rep, w)
    return w


def epithet(key: str) -> str | None:
    """English for an epithet in Azbuka's transliteration, feminine forms
    included ('solunskaja' -> 'of Thessalonica'); None if unknown."""
    if key in EPITHETS:
        return EPITHETS[key]
    for fem, masc in (("skaja", "skij"), ("ckaja", "ckij"), ("skaja", "skoj"), ("aja", "yj"), ("aja", "ij")):
        if key.endswith(fem) and key[: -len(fem)] + masc in EPITHETS:
            return EPITHETS[key[: -len(fem)] + masc]
    return None


def ru_word_english(word: str) -> str:
    nom = denom(word)
    key = cyr_slug(nom)
    if key in NAMES:
        return NAMES[key]
    if epithet(key):
        return epithet(key)
    if key.endswith(("skij", "ckij")):
        return translit(nom[:-2] + "й").replace("skiy", "sky").replace("tskiy", "tsky")
    return translit(nom)


_PHRASES = [
    (r"Собор вселенских учителей и святителей", "Synaxis of the Ecumenical Teachers and Hierarchs:"),
    (r"(?i)преподобных отец", "Venerable Fathers"), (r"убиенных|избиенных", "slain"),
    (r"в Синае и Раифе", "at Sinai and Raithu"), (r"Мир Ликийских", "of Myra in Lycia"),
    (r"(?i)правоверного", ""), (r"(?i)святых отцов", "Holy Fathers"),
    (r"и иже с (?:ним|нею|ними):?", "and those with them:"), (r"(?i)сотника", "the Centurion"),
    (r"Перенесение мощей", "Translation of the Relics of"), (r"(?:второе |первое )?[Оо]бретение мощей", "Uncovering of the Relics of"),
    (r"Преставление", "Repose of"), (r"^Память", "Commemoration of"), (r"^Собор", "Synaxis of"),
    (r"в Ближних пещерах", "in the Near Caves"), (r"в Дальних пещерах", "in the Far Caves"),
    (r"от 70-ти|от 70", "of the Seventy"), (r"и с ними", "and with them"), (r"и с ним", "and with him"),
    (r"сыновей его", "his sons"), (r"брата", "brother of"), (r"Христа ради юродивого", "Fool-for-Christ"),
    (r"(\d+)-ти мучеников", r"\1 martyrs"), (r"(?i)мучеников", "Martyrs"), (r"(?i)мучениц", "Women Martyrs"),
    (r"(?i)святых", "Saints"), (r"трех чад ее", "her three children"), (r"чад", "children"),
    (r"(?i)воинов", "soldiers"), (r"(?i)отроков", "youths"), (r"(?i)дев\b", "virgins"),
    (r"\bматери их\b", "their mother"), (r"\bматери (?:его|ее|её)\b", "and mother"),
    (r"\bматери\b", "mother of"), (r"\bдочери\b", "daughter of"), (r"\bотроковицы\b", ""),
    (r"\bв миру\b", "in the world"), (r"\bво [Сс]вятом [Кк]рещении\b", "in Holy Baptism"),
    (r"\bв [Кк]рещении\b", "in Baptism"),
]
_ROLES = {k.lower(): v for k, v in ROLE_WORDS}


def ru_text_english(text: str) -> str:
    """Word-by-word English rendering of a Russian commemoration title."""
    t = strip_stress(text)
    t = re.sub(r"\((?:[^()]*\d[^()]*|[IVXL\s–-]+|Груз\.|Серб\.|Болг\.|Рум\.|Греч\.)\)", "", t)
    for rx, rep in _PHRASES:
        t = re.sub(rx, rep, t)
    out: list[str] = []
    for tok in re.findall(r"[A-Za-z][A-Za-z\-]*|[Ѐ-ӿ][Ѐ-ӿ\-]*\.?|\d+|[,:;()]", t):
        low = tok.lower()
        if re.match(r"[A-Za-z]", tok) or tok.isdigit() or tok in ",:;()":
            out.append(tok)
        elif low in TITLES:
            out.append(TITLES[low][0])
        elif low.rstrip(".") in _ROLES or low in _ROLES:
            out.append(_ROLES.get(low, _ROLES.get(low.rstrip("."), "")))
        elif low == "и":
            out.append("and")
        elif low in ("в", "во"):
            out.append("in")
        elif low in ("его", "ее", "её", "их", "ним", "ними", "с", "со", "же", "др.", "праздника"):
            continue
        elif epithet(cyr_slug(denom(tok.rstrip(".")))):
            out.append(epithet(cyr_slug(denom(tok.rstrip(".")))))
        elif tok[0].isupper():
            out.append(ru_word_english(tok.rstrip(".")))
        else:
            continue  # unknown lower-case Russian word: omit rather than show gibberish
    s = " ".join(x for x in out if x)
    s = re.sub(r"\s+([,:;)])", r"\1", s)
    s = re.sub(r"\(\s+", "(", s)
    s = re.sub(r",\s*,", ",", s)
    s = re.sub(r"\(\s*\)", "", s)
    s = re.sub(r"\s{2,}", " ", s).strip(" ,:;")
    s = re.sub(r"Synaxis of (?:of )?(\w+?)(?:sky|skikh|kikh)? Saints", r"Synaxis of the Saints of \1", s)
    s = re.sub(r"Synaxis of of ", "Synaxis of ", s)
    s = re.sub(r"Repose of,? (?:second |first )?Uncovering of the Relics of", "Repose and Uncovering of the Relics of", s)
    s = re.sub(r"\b(Enlightener|Bishop|Archbishop|Metropolitan|Patriarch|King|Queen|Prince|Princess) (of )?(Georgia|Russia|Serbia|America|Japan|Siberia|Alaska)", r"\1 of \3", s)
    return s
