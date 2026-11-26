"""The Church year, worked out locally: the date of Pascha, the twelve great
feasts and the other great feasts, and the four fasting seasons — on the New
(Revised Julian) or the Old (Julian) calendar, as civil dates."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

JULIAN_OFFSET = 13            # days between the Julian and the civil calendar (1900-2099)


def pascha(year: int) -> dt.date:
    """Orthodox Pascha as a civil (Gregorian) date (Meeus' Julian algorithm)."""
    a, b, c = year % 4, year % 7, year % 19
    d = (19 * c + 15) % 30
    e = (2 * a + 4 * b - d + 34) % 7
    month, day = divmod(d + e + 114, 31)
    return dt.date(year, month, day + 1) + dt.timedelta(days=JULIAN_OFFSET)


@dataclass(frozen=True)
class Event:
    day: dt.date
    name: str
    kind: str                 # "pascha" | "great" | "feast" | "fast"
    end: dt.date | None = None

    @property
    def rank(self) -> int:
        """Typikon rank for the calendar's signs: 6 great feast, 5 vigil-rank feast, 0 a fast."""
        return {"pascha": 6, "great": 6, "feast": 5}.get(self.kind, 0)


# fixed great feasts: (church month, day, name, kind)
FIXED = [
    (9, 8, "Nativity of the Theotokos", "great"),
    (9, 14, "Exaltation of the Cross", "great"),
    (10, 1, "Protection of the Theotokos", "feast"),
    (11, 21, "Entry of the Theotokos", "great"),
    (12, 25, "Nativity of Christ", "great"),
    (1, 1, "Circumcision of the Lord", "feast"),
    (1, 6, "Theophany", "great"),
    (2, 2, "Meeting of the Lord", "great"),
    (3, 25, "Annunciation", "great"),
    (6, 24, "Nativity of St John the Baptist", "feast"),
    (6, 29, "Sts Peter and Paul", "feast"),
    (8, 6, "Transfiguration", "great"),
    (8, 15, "Dormition of the Theotokos", "great"),
    (8, 29, "Beheading of St John the Baptist", "feast"),
]
# feasts that move with Pascha: (days from Pascha, name, kind)
MOVEABLE = [
    (-70, "Sunday of the Publican and Pharisee", "feast"),
    (-48, "Great Lent begins", "fast"),
    (-8, "Lazarus Saturday", "feast"),
    (-7, "Entry into Jerusalem", "great"),
    (0, "Pascha", "pascha"),
    (39, "Ascension", "great"),
    (49, "Pentecost", "great"),
    (56, "All Saints", "feast"),
]


def _civil(year: int, month: int, day: int, calendar: str) -> dt.date:
    d = dt.date(year, month, day)
    return d + dt.timedelta(days=JULIAN_OFFSET) if calendar == "old" else d


def year_events(year: int, calendar: str = "new") -> list[Event]:
    """The feasts and fasts that begin in a civil year (and, for the Old
    Calendar, the feasts of late December that fall in January)."""
    out: list[Event] = []
    for y in (year - 1, year):
        for m, d, name, kind in FIXED:
            civil = _civil(y, m, d, calendar)
            if civil.year == year:
                out.append(Event(civil, name, kind))
        if calendar == "old":
            nf = _civil(y, 11, 15, calendar)
            if nf.year == year:
                out.append(Event(nf, "Nativity Fast begins", "fast", _civil(y, 12, 24, calendar)))
    p = pascha(year)
    for offset, name, kind in MOVEABLE:
        end = p - dt.timedelta(days=9) if name == "Great Lent begins" else None      # to the Friday before Lazarus Saturday
        out.append(Event(p + dt.timedelta(days=offset), name, kind, end))
    apostles = p + dt.timedelta(days=57)
    peter_paul = _civil(year, 6, 28, calendar)
    if apostles <= peter_paul:
        out.append(Event(apostles, "Apostles' Fast begins", "fast", peter_paul))
    out.append(Event(_civil(year, 8, 1, calendar), "Dormition Fast begins", "fast", _civil(year, 8, 14, calendar)))
    if calendar != "old":
        out.append(Event(_civil(year, 11, 15, calendar), "Nativity Fast begins", "fast",
                         _civil(year, 12, 24, calendar)))
    return sorted(out, key=lambda e: e.day)


def upcoming(after: dt.date, calendar: str = "new", count: int = 6, kinds: tuple[str, ...] = ("pascha", "great",
                                                                                              "feast", "fast"),
             include_today: bool = True) -> list[Event]:
    """The next feasts and fasts from a day on."""
    out: list[Event] = []
    for y in (after.year, after.year + 1):
        for e in year_events(y, calendar):
            if e.kind in kinds and (e.day > after or (include_today and e.day == after)) and e not in out:
                out.append(e)
    return sorted(out, key=lambda e: e.day)[:count]


def season(day: dt.date, calendar: str = "new") -> str:
    """The fasting season or festal period a day belongs to ("" if none)."""
    for y in (day.year - 1, day.year):
        for e in year_events(y, calendar):
            if e.kind == "fast" and e.end and e.day <= day <= e.end:
                return e.name.replace(" begins", "")
    p = pascha(day.year)
    if p - dt.timedelta(days=6) <= day < p:
        return "Holy Week"
    if p <= day < p + dt.timedelta(days=7):
        return "Bright Week"
    if p <= day < p + dt.timedelta(days=39):
        return "Paschal season"
    for y in (day.year - 1, day.year):
        nat = _civil(y, 12, 25, calendar)
        if nat <= day < nat + dt.timedelta(days=12):
            return "the Twelve Days of Christmas"
    return ""


__all__ = ["Event", "pascha", "season", "upcoming", "year_events"]
