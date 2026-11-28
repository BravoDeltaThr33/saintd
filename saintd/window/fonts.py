"""Fonts for the window: one monospaced family in up to four styles, and other
fonts for the characters it lacks (symbols, other scripts).

Box drawing, block elements and sextants are not taken from any font: paint.py
draws them, so that borders and pictures made of blocks join without seams.
"""

from __future__ import annotations

import os
import struct
import sys
from bisect import bisect_right
from dataclasses import dataclass, field
from pathlib import Path

from ..system import MACOS, WINDOWS

# monospaced families, best first: (name, regular, bold, italic, bold italic); a file is "name" or ("name", index)
MONOSPACED = [
    ("DejaVu Sans Mono", "DejaVuSansMono.ttf", "DejaVuSansMono-Bold.ttf", "DejaVuSansMono-Oblique.ttf",
     "DejaVuSansMono-BoldOblique.ttf"),
    ("Consolas", "consola.ttf", "consolab.ttf", "consolai.ttf", "consolaz.ttf"),
    ("Menlo", ("Menlo.ttc", 0), ("Menlo.ttc", 1), ("Menlo.ttc", 2), ("Menlo.ttc", 3)),
    ("Liberation Mono", "LiberationMono-Regular.ttf", "LiberationMono-Bold.ttf", "LiberationMono-Italic.ttf",
     "LiberationMono-BoldItalic.ttf"),
    ("Noto Sans Mono", "NotoSansMono-Regular.ttf", "NotoSansMono-Bold.ttf", None, None),
    ("Lucida Console", "lucon.ttf", None, None, None),
    ("Courier New", "cour.ttf", "courbd.ttf", "couri.ttf", "courbi.ttf"),
]
# where the characters the monospaced font lacks are looked for, in this order
FALLBACKS = [
    "DejaVuSans.ttf", "seguisym.ttf", "Symbola.ttf", "NotoSansSymbols2-Regular.ttf", "NotoSansSymbols-Regular.ttf",
    "Apple Symbols.ttf", "FreeSerif.ttf", "FreeMono.ttf", "segoeui.ttf", "NotoSans-Regular.ttf", "arial.ttf",
    ("cambria.ttc", 1), "Arial Unicode.ttf", "msgothic.ttc", "NotoSansCJK-Regular.ttc", "wqy-microhei.ttc",
    "malgun.ttf", "msyh.ttc", "Nirmala.ttf", "ebrima.ttf", "unifont.ttf",
]


def font_dirs() -> list[Path]:
    """Folders to look in: fonts shipped with the program first, then the computer's own."""
    dirs: list[Path] = []
    bundle = getattr(sys, "_MEIPASS", None)                 # the Windows program (saintd.exe)
    if bundle:
        dirs.append(Path(bundle) / "fonts")
    if WINDOWS:
        dirs.append(Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts")
        local = os.environ.get("LOCALAPPDATA")
        if local:
            dirs.append(Path(local) / "Microsoft" / "Windows" / "Fonts")
    elif MACOS:
        dirs += [Path("/System/Library/Fonts"), Path("/System/Library/Fonts/Supplemental"), Path("/Library/Fonts"),
                 Path.home() / "Library" / "Fonts"]
    else:
        data = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
        dirs += [Path(data) / "fonts", Path.home() / ".fonts"]
        for d in (os.environ.get("XDG_DATA_DIRS") or "/usr/local/share:/usr/share").split(":"):
            if d:
                dirs.append(Path(d) / "fonts")
    return dirs


_INDEX: dict[str, Path] | None = None


def _index() -> dict[str, Path]:
    """Every font file found, by its lower-case file name (the first one found wins)."""
    global _INDEX
    if _INDEX is None:
        found: dict[str, Path] = {}
        for d in font_dirs():
            try:
                if not d.is_dir():
                    continue
                walker = os.walk(d) if not WINDOWS else [(str(d), [], os.listdir(d))]
                for root, _dirs, files in walker:
                    for f in files:
                        if f.lower().endswith((".ttf", ".ttc", ".otf")):
                            found.setdefault(f.lower(), Path(root) / f)
            except OSError:
                continue
        _INDEX = found
    return _INDEX


def find(spec) -> tuple[Path, int] | None:
    """A font file ("name.ttf" or ("name.ttc", index)) on this computer, or None."""
    if spec is None:
        return None
    name, index = (spec, 0) if isinstance(spec, str) else spec
    p = _index().get(name.lower())
    return (p, index) if p else None


# ---------------------------------------------------------------- which characters a font has

class Coverage:
    """The characters a font has a glyph for (read from its cmap table)."""

    def __init__(self, ranges: list[tuple[int, int]]) -> None:
        ranges.sort()
        merged: list[list[int]] = []
        for a, b in ranges:
            if merged and a <= merged[-1][1] + 1:
                merged[-1][1] = max(merged[-1][1], b)
            else:
                merged.append([a, b])
        self.starts = [a for a, _ in merged]
        self.ends = [b for _, b in merged]

    def __contains__(self, cp: int) -> bool:
        i = bisect_right(self.starts, cp) - 1
        return i >= 0 and cp <= self.ends[i]

    def __bool__(self) -> bool:
        return bool(self.starts)


def read_coverage(path: Path, index: int = 0) -> Coverage:
    """Read the Unicode cmap of a TrueType/OpenType font (or of one font in a collection)."""
    try:
        data = path.read_bytes()
        base = 0
        if data[:4] == b"ttcf":
            count = struct.unpack(">I", data[8:12])[0]
            base = struct.unpack(">I", data[12 + 4 * min(index, count - 1):16 + 4 * min(index, count - 1)])[0]
        num = struct.unpack(">H", data[base + 4:base + 6])[0]
        cmap = None
        for i in range(num):
            rec = base + 12 + 16 * i
            if data[rec:rec + 4] == b"cmap":
                cmap = struct.unpack(">I", data[rec + 8:rec + 12])[0]
                break
        if cmap is None:
            return Coverage([])
        n = struct.unpack(">H", data[cmap + 2:cmap + 4])[0]
        tables = {}
        for i in range(n):
            plat, enc, off = struct.unpack(">HHI", data[cmap + 4 + 8 * i:cmap + 12 + 8 * i])
            tables[(plat, enc)] = cmap + off
        for key in ((3, 10), (0, 6), (0, 4), (0, 3), (3, 1), (0, 1), (0, 0)):
            off = tables.get(key)
            if off is None:
                continue
            fmt = struct.unpack(">H", data[off:off + 2])[0]
            if fmt == 12:
                return Coverage(_format12(data, off))
            if fmt == 4:
                return Coverage(_format4(data, off))
    except (OSError, struct.error, IndexError, ValueError):
        pass
    return Coverage([])


def _format12(data: bytes, off: int) -> list[tuple[int, int]]:
    groups = struct.unpack(">I", data[off + 12:off + 16])[0]
    out = []
    for g in range(groups):
        start, end, glyph = struct.unpack(">III", data[off + 16 + 12 * g:off + 28 + 12 * g])
        if glyph == 0:
            start += 1
        if start <= end:
            out.append((start, end))
    return out


def _format4(data: bytes, off: int) -> list[tuple[int, int]]:
    segs = struct.unpack(">H", data[off + 6:off + 8])[0] // 2
    ends = struct.unpack(f">{segs}H", data[off + 14:off + 14 + 2 * segs])
    p = off + 16 + 2 * segs
    starts = struct.unpack(f">{segs}H", data[p:p + 2 * segs])
    ro_at = p + 4 * segs                        # past the deltas, which do not tell whether a glyph exists
    range_offsets = struct.unpack(f">{segs}H", data[ro_at:ro_at + 2 * segs])
    out = []
    for i in range(segs):
        a, b = starts[i], ends[i]
        if a == 0xFFFF:
            continue
        if range_offsets[i] == 0:
            out.append((a, b))
            continue
        for c in range(a, b + 1):              # glyphs listed one by one: keep those that exist
            at = ro_at + 2 * i + range_offsets[i] + 2 * (c - a)
            if at + 2 <= len(data) and struct.unpack(">H", data[at:at + 2])[0]:
                out.append((c, c))
    return out


# ---------------------------------------------------------------- the fonts in use

@dataclass
class FontFiles:
    family: str
    faces: list[tuple[Path, int] | None]                 # regular, bold, italic, bold italic
    coverage: Coverage
    fallbacks: list[tuple[Path, int]] = field(default_factory=list)


_FILES: FontFiles | None = None


def font_files() -> FontFiles | None:
    """The monospaced family and the fallback fonts this computer has (looked up once)."""
    global _FILES
    if _FILES is None:
        for family, *faces in MONOSPACED:
            regular = find(faces[0])
            if regular is None:
                continue
            found = [regular] + [find(f) for f in faces[1:]]
            fallbacks = []
            for spec in FALLBACKS:
                f = find(spec)
                if f is not None and f not in found and f not in fallbacks:
                    fallbacks.append(f)
            _FILES = FontFiles(family, found, read_coverage(*regular), fallbacks)
            break
    return _FILES
