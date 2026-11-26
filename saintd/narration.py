"""What the reader says: a saint, a day of the Church year, the readings —
turned into speakable chunks (see tts.py)."""

from __future__ import annotations

import datetime as dt
import re
from typing import Any

from .db import LIFE_SOURCES, str_to_cats
from .text import html_to_text, strip_foreign_script
from .tts import Chunk, chunks_of, speakable

MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September",
          "October", "November", "December"]
WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def ordinal(n: int) -> str:
    suf = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suf}"


def spoken_date(d: dt.date, weekday: bool = True, year: bool = True) -> str:
    out = f"the {ordinal(d.day)} of {MONTHS[d.month - 1]}"
    if weekday:
        out = f"{WEEKDAYS[d.weekday()]}, {out}"
    return out + (f", {d.year}" if year else "")


def join_and(items: list[str]) -> str:
    items = [x for x in items if x]
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " and " + items[-1]


def add(chunks: list[Chunk], text: str, target: Any = None, section: str = "", anchor: str = "") -> None:
    """Append text as speakable chunks (all with the same highlight target)."""
    for piece in chunks_of(speakable(text)):
        chunks.append(Chunk(piece, target, section, anchor))


def facts_sentence(info: dict) -> str:
    """The header card's facts, as sentences."""
    out = []
    if info.get("feasts"):
        days = []
        for (m, d), label in info["feasts"][:3]:
            days.append(f"{MONTHS[m - 1]} {ordinal(d)}" + (f" ({label.lower()})" if label else ""))
        out.append("Commemorated on " + join_and(days) + ".")
    lived = info.get("lived") or ""
    if lived:
        first, _, cent = lived.partition(" · ")
        if first.startswith(("born ", "died ")):
            sentence = first[:1].upper() + first[1:]
        elif first.endswith("century") or first.endswith("century BC"):
            sentence = f"Lived in the {first}"
        else:
            sentence = f"Lived {first}"
        out.append(sentence + (f", in the {cent}." if cent else "."))
    if info.get("where"):
        out.append(f"From {info['where']}.")
    return " ".join(out)


def hymn_parts(st: dict) -> tuple[str, str, str]:
    """(kind, tone, who) of a stored hymn (source htc-hymn)."""
    _, kind, tone, who = (st["title"].split("|") + ["", "", "", ""])[:4]
    return kind, tone, who


def hymn_heading(st: dict) -> str:
    kind, tone, _ = hymn_parts(st)
    return kind + (f", tone {tone}" if tone else "")


def life_paragraphs(stories: list[dict]) -> list[str]:
    """The paragraphs of the best life of the saint (as plain text)."""
    lives = sorted((st for st in stories if st["source"] in LIFE_SOURCES),
                   key=lambda st: LIFE_SOURCES.index(st["source"]))
    if not lives:
        notes = [st for st in stories if st["source"] == "wikical"]
        lives = notes[:1]
    if not lives:
        return []
    text = strip_foreign_script(html_to_text(lives[0]["html"]))
    return [re.sub(r"\s+", " ", p).strip() for p in text.split("\n\n") if p.strip()]


def saint_script(ctx, s: dict, hymns: bool = True, target: Any = None) -> list[Chunk]:
    """A saint read from the directory alone: name, facts, life and hymns."""
    info = ctx.articles.summary(s)
    out: list[Chunk] = []
    add(out, info["name"] + "." + (f" {info['subtitle']}." if info["subtitle"] else ""), target, "header")
    add(out, facts_sentence(info), target, "header")
    stories = ctx.db.stories(s["id"])
    for p in life_paragraphs(stories):
        add(out, p, target, "life")
    if hymns:
        for st in sorted((x for x in stories if x["source"] == "htc-hymn"), key=lambda x: x["title"]):
            add(out, f"{hymn_heading(st)}. {st['html']}", target, "hymns")
    return out


def readings_script(data: dict, target: Any = None) -> list[Chunk]:
    """The day's Scripture readings, each announced and then read."""
    out: list[Chunk] = []
    for r in data.get("readings") or []:
        what = r.get("source") or "reading"
        display = r.get("display") or ""
        verses = [(v.get("content") or "").strip() for v in (r.get("passage") or [])]
        verses = [v for v in verses if v]
        if not display:
            continue
        add(out, f"The {what.lower()} reading, from {display}.", target, "readings")
        if verses:
            add(out, " ".join(verses), target, "readings")
    return out


def fast_sentence(data: dict) -> str:
    fast = data.get("fast_level_desc") or ""
    if not fast or fast.lower() == "no fast":
        return "There is no fast today." if fast else ""
    exc = (data.get("fast_exception_desc") or "").strip()
    absts = [a for a in (data.get("fast_abstentions") or []) if a]
    out = f"A day of fasting: {fast.lower()}"
    if absts:
        out += ", without " + join_and(absts)
    if exc:
        out += f"; {exc.lower()}"
    return out + "."


def day_titles(data: dict) -> list[str]:
    return [t for t in (data.get("titles") or []) if t]


def day_feasts(data: dict) -> list[str]:
    return [f for f in (data.get("feasts") or []) if f]


def kinds(s: dict) -> list[str]:
    return str_to_cats(s.get("categories") or "")


__all__ = ["add", "day_feasts", "day_titles", "facts_sentence", "fast_sentence", "hymn_heading", "hymn_parts",
           "join_and", "life_paragraphs", "ordinal", "readings_script", "saint_script", "spoken_date"]
