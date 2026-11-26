"""Colour schemes for Saint Directory: five earthy ones, two imperial ones
(the Byzantine and Roman Empires), four from the life of the Church (Paschal
Night, Mount Athos, Blue Domes, and Theophany — a light one), and Liturgical
Colours, which changes with the Church year like the vestments do."""

from __future__ import annotations

import datetime as dt

from textual.theme import Theme


def _theme(key: str, title: str, blurb: str, *, bg: str, surface: str, panel: str, primary: str,
           secondary: str, accent: str, fg: str, muted: str, error: str, success: str, warning: str,
           banner: tuple[str, str, str] | None = None, dark: bool = True) -> dict:
    banner = banner or (primary, secondary, accent)
    t = Theme(
        name=f"saintd-{key}",
        primary=primary,
        secondary=secondary,
        accent=accent,
        foreground=fg,
        background=bg,
        surface=surface,
        panel=panel,
        boost=panel,
        warning=warning,
        error=error,
        success=success,
        dark=dark,
        variables={
            "muted": muted,
            "rail-bg": surface,
            "banner-a": banner[0],
            "banner-b": banner[1],
            "banner-c": banner[2],
            "block-cursor-background": primary,
            "block-cursor-foreground": bg,
            "block-cursor-text-style": "bold",
            "block-hover-background": panel,
            "footer-key-foreground": primary,
            "footer-background": surface,
            "input-cursor-background": primary,
            "input-selection-background": f"{secondary} 35%",
            "scrollbar": panel,
            "scrollbar-hover": secondary,
            "scrollbar-active": primary,
            "scrollbar-background": surface,
            "border": muted,
            "border-blurred": panel,
            "markdown-h1-color": primary,
            "markdown-h2-color": secondary,
            "markdown-h3-color": accent,
        },
    )
    return {"key": key, "title": title, "blurb": blurb, "theme": t,
            "swatch": [bg, panel, primary, secondary, accent, fg]}


THEMES: list[dict] = [
    _theme("terracotta", "Terracotta Kiln", "Fired clay, ochre glaze and sage.",
           bg="#1c1410", surface="#251a14", panel="#35251b", primary="#d4733f", secondary="#e6ac5c",
           accent="#93a76d", fg="#f2e3cc", muted="#8c6f58", error="#d0503a", success="#93a76d", warning="#e6ac5c"),
    _theme("moss", "Moss & Lichen", "Forest floor greens over damp stone.",
           bg="#12160f", surface="#1a2016", panel="#253021", primary="#8fb15f", secondary="#cdbb80",
           accent="#d48e52", fg="#e7e9d6", muted="#6f7c5e", error="#c8603f", success="#8fb15f", warning="#cdbb80"),
    _theme("ochre", "Desert Ochre", "Sun-baked sand, rust and desert sage.",
           bg="#1d1810", surface="#272015", panel="#352b1c", primary="#e3ad4d", secondary="#c46c3c",
           accent="#82a69c", fg="#f5e9d0", muted="#94805e", error="#cf5636", success="#82a69c", warning="#e3ad4d"),
    _theme("umber", "Icon Umber", "Icon gold leaf, cinnabar and verdigris on walnut.",
           bg="#17110d", surface="#211812", panel="#2f221a", primary="#d9b13f", secondary="#bb4a2f",
           accent="#58978c", fg="#f1e5c8", muted="#8a7558", error="#c94a33", success="#58978c", warning="#d9b13f"),
    _theme("cedar", "Cedar & Peat", "Smoked cedar, olive branch and parchment.",
           bg="#110e0c", surface="#1a1512", panel="#271f1a", primary="#bf6b3c", secondary="#86a24a",
           accent="#dcb887", fg="#ebe0cf", muted="#7d6a59", error="#c4533a", success="#86a24a", warning="#dcb887"),
    # ---- imperial schemes
    # Constantinople: porphyry (the imperial purple stone), the gold ground of the mosaics,
    # lapis blue of the Theotokos' robes, emerald enamel, ivory.
    _theme("byzantine", "Byzantine Empire", "Imperial porphyry, mosaic gold and lapis blue.",
           bg="#150d18", surface="#1e1322", panel="#2e1d33", primary="#e0b443", secondary="#c27cba",
           accent="#6b9ddb", fg="#f1e8d8", muted="#8f7790", error="#d9493f", success="#62ab84", warning="#e0b443"),
    # Rome: legion crimson, the gilded eagle, laurel, Carrara marble on Pompeian black.
    _theme("roman", "Roman Empire", "Legion crimson, eagle gold, laurel and marble.",
           bg="#120c0b", surface="#1b1312", panel="#2c1d1b", primary="#e0443e", secondary="#ecbd4f",
           accent="#94b061", fg="#f2eee8", muted="#8e817a", error="#f0703e", success="#94b061", warning="#ecbd4f",
           banner=("#e0443e", "#ecbd4f", "#efe9df")),
    # ---- from the life of the Church
    # The midnight procession of Pascha: candle flames, the red of the Resurrection, white lilies, night sky.
    _theme("paschal", "Paschal Night", "Candle flames, Paschal red and lilies at night.",
           bg="#0b0c14", surface="#121424", panel="#1d2036", primary="#f0b545", secondary="#e2453a",
           accent="#a9c1f5", fg="#f5f0e6", muted="#7d82a2", error="#f06a4f", success="#7fc08c", warning="#f0b545",
           banner=("#f0b545", "#e2453a", "#f5f0e6")),
    # The Holy Mountain: monastic black, beeswax candles, olive groves, the Aegean, weathered stone.
    _theme("athos", "Mount Athos", "Monastic black, beeswax, olives and the Aegean.",
           bg="#0d0e0c", surface="#151713", panel="#21241e", primary="#d8b56b", secondary="#88a660",
           accent="#62a0c4", fg="#eae7dc", muted="#7f8274", error="#c95a43", success="#88a660", warning="#d8b56b"),
    # The blue domes strewn with gold stars (the Dormition cathedral of the Trinity Lavra).
    _theme("domes", "Blue Domes", "Starry blue domes with golden stars, and brick.",
           bg="#0a1120", surface="#0f1a2e", panel="#192843", primary="#ecc75c", secondary="#7eaee8",
           accent="#e3866a", fg="#eef2f9", muted="#7489a9", error="#e5604f", success="#7cc2a0", warning="#ecc75c"),
    # Theophany: the white garments of the newly baptized, Jordan blue, gold — a light scheme.
    _theme("theophany", "Theophany (light)", "White garments, Jordan blue and gold, by daylight.",
           bg="#f6f1e5", surface="#eee7d6", panel="#ddd3bc", primary="#1f5c8e", secondary="#8f6612",
           accent="#2c7a74", fg="#29231a", muted="#857860", error="#b3392c", success="#3f7a35", warning="#8f6612",
           banner=("#1f5c8e", "#8f6612", "#2c7a74"), dark=False),
]

# ---- liturgical colours: the colour of the vestments for the day (after Russian use)
LITURGICAL_VARIANTS: dict[str, dict] = {v["key"][4:]: v for v in [
    _theme("lit-gold", "Gold", "Sundays, prophets, apostles and hierarchs — most days of the year.",
           bg="#16110a", surface="#1f1810", panel="#2e2416", primary="#e5b94a", secondary="#d0874a",
           accent="#8fae7a", fg="#f4ead2", muted="#92805e", error="#d4543b", success="#8fae7a", warning="#e5b94a"),
    _theme("lit-blue", "Blue", "Feasts of the Theotokos and the Dormition Fast.",
           bg="#0b1220", surface="#101a2d", panel="#1a2742", primary="#7fb0f0", secondary="#e6c264",
           accent="#c58fd6", fg="#eef3fb", muted="#7387a6", error="#e5604f", success="#7cc2a0", warning="#e6c264"),
    _theme("lit-purple", "Purple", "The Cross, and the Saturdays and Sundays of Great Lent.",
           bg="#130b19", surface="#1b1023", panel="#2a1a36", primary="#c08ae6", secondary="#e3c15a",
           accent="#7fb3c9", fg="#f3ebf7", muted="#8a7898", error="#e05a62", success="#8cc79a", warning="#e3c15a"),
    _theme("lit-green", "Green", "Pentecost, Palm Sunday, and the venerable monastic saints.",
           bg="#0b140e", surface="#101c14", panel="#1a2c1f", primary="#79c27f", secondary="#e3c15a",
           accent="#d98d6a", fg="#ecf3e8", muted="#728a74", error="#d9604a", success="#79c27f", warning="#e3c15a"),
    _theme("lit-white", "White", "The Nativity, Theophany, the Ascension and the Transfiguration.",
           bg="#11131a", surface="#181b24", panel="#252a37", primary="#eef1f7", secondary="#e3c15a",
           accent="#8fb5e0", fg="#f4f5f8", muted="#878ea0", error="#e0604f", success="#8cc79a", warning="#e3c15a"),
    _theme("lit-red", "Red", "Pascha and its forty days, the martyrs, and the Nativity Fast.",
           bg="#160b0b", surface="#1f1010", panel="#311919", primary="#ec5545", secondary="#f0c25a",
           accent="#e9e2d0", fg="#f7ece6", muted="#9a7b74", error="#ff7a5c", success="#9bc48a", warning="#f0c25a"),
    _theme("lit-black", "Black", "Holy Week and the weekdays of Great Lent.",
           bg="#0a0a0b", surface="#121214", panel="#1d1d21", primary="#cfc8bb", secondary="#9f86c6",
           accent="#c99a5a", fg="#ece9e3", muted="#77737a", error="#d0574a", success="#8fb08a", warning="#c99a5a"),
]}

_THEOTOKOS = [((9, 8), (9, 12)), ((11, 21), (11, 25)), ((3, 25), (3, 26)), ((8, 15), (8, 23)), ((10, 1), (10, 1)),
              ((2, 2), (2, 9))]


def _in(md: tuple[int, int], a: tuple[int, int], b: tuple[int, int]) -> bool:
    return a <= md <= b if a <= b else (md >= a or md <= b)


def liturgical_colour(day: dt.date, calendar: str = "new") -> tuple[str, str]:
    """The colour of the vestments on a day, and why — after Russian use (customs differ
    from place to place): the season of Pascha and the great feasts first, then the fasts."""
    from .paschalion import pascha
    from .sources import civil_to_church
    off = (day - pascha(day.year)).days
    if -6 <= off <= -1:
        return "black", "Holy Week"
    if off in (-7, -8):
        return "green", "Lazarus Saturday and Palm Sunday"
    if -48 <= off <= -9:
        return ("purple", "a Lenten Saturday or Sunday") if day.weekday() >= 5 else ("black", "a weekday of Great Lent")
    if 0 <= off <= 38:
        return "red", "the season of Pascha"
    if off == 39:
        return "white", "the Ascension"
    if off in (49, 50):
        return "green", "Pentecost"
    md = civil_to_church(day) if calendar == "old" else (day.month, day.day)
    if _in(md, (12, 25), (1, 14)):
        return "white", "the Nativity and Theophany"
    if _in(md, (8, 6), (8, 13)):
        return "white", "the Transfiguration"
    if _in(md, (9, 14), (9, 21)) or md == (8, 1):
        return "purple", "the Precious Cross"
    for a, b in _THEOTOKOS:
        if _in(md, a, b):
            return "blue", "a feast of the Theotokos"
    if md == (8, 29):
        return "red", "the Beheading of St John the Baptist"
    if _in(md, (8, 1), (8, 14)):
        return "blue", "the Dormition Fast"
    if _in(md, (11, 15), (12, 24)):
        return "red", "the Nativity Fast"
    return "gold", "an ordinary day"


THEMES.append({"key": "liturgical", "title": "Liturgical Colours",
               "blurb": "Follows the Church year, like the vestments.",
               "theme": LITURGICAL_VARIANTS["gold"]["theme"], "swatch": LITURGICAL_VARIANTS["gold"]["swatch"]})

BY_KEY = {t["key"]: t for t in THEMES}
ALL_THEMES = [t["theme"] for t in THEMES if t["key"] != "liturgical"] + \
             [v["theme"] for v in LITURGICAL_VARIANTS.values()]


def resolve(key: str, calendar: str = "new", day: dt.date | None = None) -> dict:
    """The scheme to show for a setting (Liturgical Colours: today's colour)."""
    if key == "liturgical":
        colour, _ = liturgical_colour(day or dt.date.today(), calendar)
        return LITURGICAL_VARIANTS[colour]
    return BY_KEY.get(key, THEMES[0])


def theme_name(key: str, calendar: str = "new") -> str:
    return resolve(key, calendar)["theme"].name
