"""Drawing saint icons in the terminal.

* Kitty graphics (Kitty, Ghostty): the picture is sent to the terminal once and
  shown through Unicode placeholder cells, so it scrolls and clips like text.
* Sixel (WezTerm, foot, Konsole, xterm ...): through textual-image's Sixel widget.
* Colour blocks: two pixels per cell with the upper-half block, in truecolor.
* Off: an ornamental frame with the saint's initial.
"""

from __future__ import annotations

import base64
import io
import itertools
import random
import sys
import threading
import time
from pathlib import Path

from rich.console import Console, ConsoleOptions, RenderResult
from rich.segment import Segment
from rich.style import Style
from rich.text import Text
from textual.widget import Widget

from . import art, eagle, term

try:                                    # Pillow comes with textual-image
    from PIL import Image as PILImage
except Exception:                       # pragma: no cover - images are optional
    PILImage = None

_SixelWidget = None                     # textual_image.widget.sixel.Image, when usable


def prepare(mode: str) -> str:
    """Call before the interface starts. Sixel needs textual-image to measure
    the terminal while it can still be asked; returns the mode that will work."""
    global _SixelWidget
    if mode == "sixel":
        try:
            from textual_image.widget.sixel import Image as SixelImage   # queries the terminal on import
            _SixelWidget = SixelImage
        except Exception:
            return "blocks"
    if mode in ("kitty", "sixel", "blocks") and PILImage is None:
        return "off"
    return mode


def sixel_ready() -> bool:
    return _SixelWidget is not None


# ---------------------------------------------------------------- image loading

_cache: dict[tuple[str, float], "PILImage.Image"] = {}


def load(path: Path | str | None):
    """A Pillow image in RGB(A), or None."""
    if not path or PILImage is None:
        return None
    p = Path(path)
    try:
        key = (str(p), p.stat().st_mtime)
    except OSError:
        return None
    if key in _cache:
        return _cache[key]
    try:
        im = PILImage.open(p)
        im.load()
        if im.mode not in ("RGB", "RGBA"):
            im = im.convert("RGBA" if "transparency" in im.info or im.mode in ("LA", "P") else "RGB")
    except Exception:
        return None
    if len(_cache) > 64:
        _cache.clear()
    _cache[key] = im
    return im


def fit_cells(img_w: int, img_h: int, max_cols: int, max_rows: int, cell_px: tuple[int, int]) -> tuple[int, int]:
    """Columns and rows that show the picture as large as possible inside the
    box without distorting it."""
    cw, ch = cell_px if cell_px[0] and cell_px[1] else (10, 20)
    if img_w <= 0 or img_h <= 0 or max_cols <= 0 or max_rows <= 0:
        return 0, 0
    scale = min(max_cols * cw / img_w, max_rows * ch / img_h)
    cols = max(1, min(max_cols, round(img_w * scale / cw)))
    rows = max(1, min(max_rows, round(img_h * scale / ch)))
    return cols, rows


def _flatten(im, bg: tuple[int, int, int]):
    if im.mode == "RGBA":
        base = PILImage.new("RGB", im.size, bg)
        base.paste(im, mask=im.split()[3])
        return base
    return im.convert("RGB") if im.mode != "RGB" else im


# ---------------------------------------------------------------- colour blocks

class HalfBlocks:
    """Rich renderable: the picture as upper-half blocks, two pixels per cell."""

    def __init__(self, im, cols: int, rows: int, bg: tuple[int, int, int] = (0, 0, 0)) -> None:
        self.cols, self.rows = cols, rows
        small = _flatten(im, bg).resize((cols, rows * 2), PILImage.LANCZOS)
        px = small.load()
        self.lines: list[list[Segment]] = []
        for y in range(rows):
            line = []
            for x in range(cols):
                t, b = px[x, 2 * y], px[x, 2 * y + 1]
                line.append(Segment("▀", Style(color=f"rgb({t[0]},{t[1]},{t[2]})",
                                                    bgcolor=f"rgb({b[0]},{b[1]},{b[2]})")))
            self.lines.append(line)

    def __rich_console__(self, console: Console, options: ConsoleOptions) -> RenderResult:
        for i, line in enumerate(self.lines):
            yield from line
            if i < len(self.lines) - 1:
                yield Segment.line()


# ---------------------------------------------------------------- kitty graphics

_PLACEHOLDER = "\U0010EEEE"
# row/column diacritics from the Kitty graphics protocol (all 297 of rowcolumn-diacritics.txt)
_DIACRITICS = [
    0x0305, 0x030D, 0x030E, 0x0310, 0x0312, 0x033D, 0x033E, 0x033F, 0x0346, 0x034A, 0x034B, 0x034C,
    0x0350, 0x0351, 0x0352, 0x0357, 0x035B, 0x0363, 0x0364, 0x0365, 0x0366, 0x0367, 0x0368, 0x0369,
    0x036A, 0x036B, 0x036C, 0x036D, 0x036E, 0x036F, 0x0483, 0x0484, 0x0485, 0x0486, 0x0487, 0x0592,
    0x0593, 0x0594, 0x0595, 0x0597, 0x0598, 0x0599, 0x059C, 0x059D, 0x059E, 0x059F, 0x05A0, 0x05A1,
    0x05A8, 0x05A9, 0x05AB, 0x05AC, 0x05AF, 0x05C4, 0x0610, 0x0611, 0x0612, 0x0613, 0x0614, 0x0615,
    0x0616, 0x0617, 0x0657, 0x0658, 0x0659, 0x065A, 0x065B, 0x065D, 0x065E, 0x06D6, 0x06D7, 0x06D8,
    0x06D9, 0x06DA, 0x06DB, 0x06DC, 0x06DF, 0x06E0, 0x06E1, 0x06E2, 0x06E4, 0x06E7, 0x06E8, 0x06EB,
    0x06EC, 0x0730, 0x0732, 0x0733, 0x0735, 0x0736, 0x073A, 0x073D, 0x073F, 0x0740, 0x0741, 0x0743,
    0x0745, 0x0747, 0x0749, 0x074A, 0x07EB, 0x07EC, 0x07ED, 0x07EE, 0x07EF, 0x07F0, 0x07F1, 0x07F3,
    0x0816, 0x0817, 0x0818, 0x0819, 0x081B, 0x081C, 0x081D, 0x081E, 0x081F, 0x0820, 0x0821, 0x0822,
    0x0823, 0x0825, 0x0826, 0x0827, 0x0829, 0x082A, 0x082B, 0x082C, 0x082D, 0x0951, 0x0953, 0x0954,
    0x0F82, 0x0F83, 0x0F86, 0x0F87, 0x135D, 0x135E, 0x135F, 0x17DD, 0x193A, 0x1A17, 0x1A75, 0x1A76,
    0x1A77, 0x1A78, 0x1A79, 0x1A7A, 0x1A7B, 0x1A7C, 0x1B6B, 0x1B6D, 0x1B6E, 0x1B6F, 0x1B70, 0x1B71,
    0x1B72, 0x1B73, 0x1CD0, 0x1CD1, 0x1CD2, 0x1CDA, 0x1CDB, 0x1CE0, 0x1DC0, 0x1DC1, 0x1DC3, 0x1DC4,
    0x1DC5, 0x1DC6, 0x1DC7, 0x1DC8, 0x1DC9, 0x1DCB, 0x1DCC, 0x1DD1, 0x1DD2, 0x1DD3, 0x1DD4, 0x1DD5,
    0x1DD6, 0x1DD7, 0x1DD8, 0x1DD9, 0x1DDA, 0x1DDB, 0x1DDC, 0x1DDD, 0x1DDE, 0x1DDF, 0x1DE0, 0x1DE1,
    0x1DE2, 0x1DE3, 0x1DE4, 0x1DE5, 0x1DE6, 0x1DFE, 0x20D0, 0x20D1, 0x20D4, 0x20D5, 0x20D6, 0x20D7,
    0x20DB, 0x20DC, 0x20E1, 0x20E7, 0x20E9, 0x20F0, 0x2CEF, 0x2CF0, 0x2CF1, 0x2DE0, 0x2DE1, 0x2DE2,
    0x2DE3, 0x2DE4, 0x2DE5, 0x2DE6, 0x2DE7, 0x2DE8, 0x2DE9, 0x2DEA, 0x2DEB, 0x2DEC, 0x2DED, 0x2DEE,
    0x2DEF, 0x2DF0, 0x2DF1, 0x2DF2, 0x2DF3, 0x2DF4, 0x2DF5, 0x2DF6, 0x2DF7, 0x2DF8, 0x2DF9, 0x2DFA,
    0x2DFB, 0x2DFC, 0x2DFD, 0x2DFE, 0x2DFF, 0xA66F, 0xA67C, 0xA67D, 0xA6F0, 0xA6F1, 0xA8E0, 0xA8E1,
    0xA8E2, 0xA8E3, 0xA8E4, 0xA8E5, 0xA8E6, 0xA8E7, 0xA8E8, 0xA8E9, 0xA8EA, 0xA8EB, 0xA8EC, 0xA8ED,
    0xA8EE, 0xA8EF, 0xA8F0, 0xA8F1, 0xAAB0, 0xAAB2, 0xAAB3, 0xAAB7, 0xAAB8, 0xAABE, 0xAABF, 0xAAC1,
    0xFE20, 0xFE21, 0xFE22, 0xFE23, 0xFE24, 0xFE25, 0xFE26, 0x10A0F, 0x10A38, 0x1D185, 0x1D186, 0x1D187,
    0x1D188, 0x1D189, 0x1D1AA, 0x1D1AB, 0x1D1AC, 0x1D1AD, 0x1D242, 0x1D243, 0x1D244,
]
MAX_CELLS = len(_DIACRITICS)            # the largest picture in rows or columns (297)
_ids = itertools.count(random.randint(1000, 0xFFFF) << 8)
_sent: dict[tuple, int] = {}            # (path, mtime, cols, rows, bg) -> image id already in the terminal


def _tgp(**kw) -> str:
    payload = kw.pop("payload", None)
    ctrl = ",".join(f"{k}={v}" for k, v in kw.items() if v is not None)
    return f"\x1b_G{ctrl}{';' + payload if payload else ''}\x1b\\"


class KittyImage:
    """Rich renderable: placeholder cells for an image held by the terminal."""

    def __init__(self, image_id: int, cols: int, rows: int) -> None:
        self.image_id, self.cols, self.rows = image_id, cols, rows
        i = image_id & 0xFFFFFF
        self.style = Style(color=f"rgb({(i >> 16) & 255},{(i >> 8) & 255},{i & 255})")

    def __rich_console__(self, console: Console, options: ConsoleOptions) -> RenderResult:
        for r in range(self.rows):
            rd = chr(_DIACRITICS[r])
            yield Segment("".join(_PLACEHOLDER + rd + chr(_DIACRITICS[c]) for c in range(self.cols)), self.style)
            if r < self.rows - 1:
                yield Segment.line()


def kitty_send(write, key: tuple, im, cols: int, rows: int, cell_px: tuple[int, int],
               bg: tuple[int, int, int]) -> int:
    """Send the picture to the terminal (once per size) and return its id."""
    if key in _sent:
        return _sent[key]
    cw, ch = cell_px if cell_px[0] else (10, 20)
    pic = _flatten(im, bg).resize((max(1, cols * cw), max(1, rows * ch)), PILImage.LANCZOS)
    buf = io.BytesIO()
    pic.save(buf, format="PNG", optimize=False)
    data = base64.standard_b64encode(buf.getvalue()).decode("ascii")
    image_id = next(_ids) & 0xFFFFFF or 1
    out = []
    first = True
    while data:
        chunk, data = data[:4096], data[4096:]
        if first:
            out.append(_tgp(a="t", i=image_id, f=100, t="d", q=2, m=1 if data else 0, payload=chunk))
            first = False
        else:
            out.append(_tgp(m=1 if data else 0, q=2, payload=chunk))
    out.append(_tgp(a="p", U=1, i=image_id, c=cols, r=rows, q=2))
    write("".join(out))
    _sent[key] = image_id
    return image_id


def kitty_forget_all(write) -> None:
    for image_id in set(_sent.values()):
        try:
            write(_tgp(a="d", d="I", i=image_id, q=2))
        except Exception:
            pass
    _sent.clear()


# ---------------------------------------------------------------- the widget

class SaintIcon(Widget):
    """An icon of a saint, drawn the best way the terminal allows. In terminals
    that show true images it stands in a gilded arched frame, and a saint
    without a picture gets a painted icon blank (gold leaf, halo, initial)."""

    DEFAULT_CSS = """
    SaintIcon { width: 24; height: 14; }
    SaintIcon > .sixel { width: 100%; height: 100%; }
    """

    def __init__(self, *, id: str | None = None, classes: str | None = None, framed: bool = True) -> None:
        super().__init__(id=id, classes=classes)
        self.path: Path | None = None
        self.initial = "☦"
        self.label = ""
        self.mode = "off"
        self.framed = framed
        self._sixel_child = None
        self._sixel_key = None
        self._ready: dict[tuple, object] = {}      # pictures painted in the background, waiting to be sent
        self._painting: set[tuple] = set()

    # -- state
    def show(self, path: Path | None, initial: str = "", mode: str | None = None, label: str | None = None) -> None:
        changed = (path != self.path) or (mode is not None and mode != self.mode) or \
                  (bool(initial) and initial != self.initial) or (label is not None and label != self.label)
        self.path = path
        if initial:
            self.initial = initial
        if label is not None:
            self.label = label
        if mode is not None:
            self.mode = mode
        if changed:
            self._sync_sixel()
            self.refresh(layout=True)

    def set_mode(self, mode: str) -> None:
        self.show(self.path, mode=mode)

    def fancy(self) -> bool:
        """True images with the painted frame (Kitty, Ghostty, Sixel)."""
        return self.framed and self.mode in ("kitty", "sixel") and art.available()

    def picture_key(self) -> tuple:
        im_path = str(self.path) if self.path and load(self.path) is not None else ""
        try:
            st = self.path.stat().st_mtime if im_path else 0
        except OSError:
            st = 0
        return ("kiot", im_path or f"blank:{self.initial}:{self.label}", st)

    def picture(self, wpx: int, hpx: int, bg: tuple[int, int, int]):
        """The picture to show at this pixel size: framed icon, icon blank, or the raw icon."""
        im = load(self.path) if self.path else None
        if self.fancy():
            if im is not None:
                return art.kiot(im, wpx, hpx, bg)
            return art.icon_blank(self.initial, wpx, hpx, bg, self.label)
        return im

    def _paint_later(self, key: tuple, w: int, h: int, bg) -> None:
        if key in self._painting:
            return
        self._painting.add(key)
        cw, ch = self._cell_px()

        def run() -> None:
            try:
                pic = self.picture(w * cw, h * ch, bg)
            except Exception:
                pic = None

            def done() -> None:
                self._painting.discard(key)
                if pic is not None:
                    if len(self._ready) > 6:
                        self._ready.clear()
                    self._ready[key] = pic
                    self.refresh()
            try:
                self.app.call_from_thread(done)
            except Exception:
                pass
        threading.Thread(target=run, name="saintd-paint", daemon=True).start()

    def _cell_px(self) -> tuple[int, int]:
        cw, ch = term.current().cell_px
        return (cw, ch) if cw and ch else (10, 20)

    def _sync_sixel(self) -> None:
        if not self.is_mounted:
            return                      # done in on_mount
        w, h = self.content_size.width, self.content_size.height
        want = self.mode == "sixel" and _SixelWidget is not None and w > 1 and h > 1 and (
            self.fancy() or (self.path is not None and load(self.path) is not None))
        key = (self.picture_key(), w, h, self._bg()) if want else None
        if key == self._sixel_key and (self._sixel_child is not None) == bool(want):
            return
        self._sixel_key = key
        if self._sixel_child is not None:
            self._sixel_child.remove()
            self._sixel_child = None
        if want:
            cw, ch = self._cell_px()
            pic = self.picture(w * cw, h * ch, self._bg())
            if pic is not None:
                self._sixel_child = _SixelWidget(pic, classes="sixel")
                self.mount(self._sixel_child)

    def on_mount(self) -> None:
        if self.mode == "sixel":
            self.call_after_refresh(self._sync_sixel)

    def on_resize(self) -> None:
        if self.mode == "sixel":
            self._sync_sixel()

    # -- drawing
    def _bg(self) -> tuple[int, int, int]:
        try:
            c = self.background_colors[1]
            return (c.r, c.g, c.b)
        except Exception:
            return (0, 0, 0)

    def _write(self, data: str) -> None:
        driver = getattr(self.app, "_driver", None)
        if driver is not None:
            driver.write(data)
        elif sys.__stdout__:
            sys.__stdout__.write(data)
            sys.__stdout__.flush()

    def render(self):
        w, h = self.content_size.width, self.content_size.height
        im = load(self.path) if self.path else None
        if self.mode == "sixel" and self._sixel_child is not None:
            return ""
        w, h = min(w, MAX_CELLS), min(h, MAX_CELLS)
        if self.mode == "kitty" and self.fancy() and w >= 4 and h >= 2:
            bg = self._bg()
            key = (*self.picture_key(), w, h, bg)
            image_id = _sent.get(key)
            if image_id is None:
                pic = self._ready.pop(key, None)
                if pic is None:                      # paint it in the background; the panel stays smooth
                    self._paint_later(key, w, h, bg)
                    return Text(" " * w + ("\n" + " " * w) * (h - 1))
                image_id = kitty_send(self._write, key, pic, w, h, term.current().cell_px, bg)
            return KittyImage(image_id, w, h)
        if im is None or self.mode == "off" or w < 2 or h < 1:
            return self._ornament(w, h)
        info = term.current()
        if self.mode == "kitty":
            cols, rows = fit_cells(im.width, im.height, w, h, info.cell_px or (10, 20))
            st = self.path.stat().st_mtime if self.path else 0
            bg = self._bg()                 # part of the key: a new colour scheme sends the picture again
            image_id = kitty_send(self._write, (str(self.path), st, cols, rows, bg), im, cols, rows,
                                  info.cell_px, bg)
            return _Centered(KittyImage(image_id, cols, rows), cols, rows, w, h)
        cols, rows = fit_cells(im.width, im.height, w, h, (1, 2))
        return _Centered(HalfBlocks(im, cols, rows, self._bg()), cols, rows, w, h)

    def _ornament(self, w: int, h: int):
        """A gilded frame with a cross and the saint's initial, for saints
        without an icon (or when pictures are off)."""
        try:
            theme = self.app.current_theme
            gold, accent, fg = theme.primary, theme.accent, theme.foreground or "white"
        except Exception:
            gold, accent, fg = "yellow", "cyan", "white"
        ascii_only = False
        try:
            ascii_only = self.app.ctx.cfg["glyphs"] == "ascii"
        except Exception:
            pass
        tl, tr, bl, br, hz, vt = ("+", "+", "+", "+", "-", "|") if ascii_only else ("\u2554", "\u2557", "\u255a",
                                                                                 "\u255d", "\u2550", "\u2551")
        cross = "+" if ascii_only else "\u2626"
        t = Text(no_wrap=True, overflow="crop")
        if w < 6 or h < 4:
            t.append(self.initial, style=Style(color=gold, bold=True))
            return t
        fw = min(w, max(8, int(h * 1.6)))          # keep a portrait-like board
        pad = " " * ((w - fw) // 2)
        inner = fw - 2
        mid = h // 2
        for y in range(h):
            t.append(pad)
            if y == 0:
                t.append(tl + hz * inner + tr, style=Style(color=gold))
            elif y == h - 1:
                t.append(bl + hz * inner + br, style=Style(color=gold))
            else:
                t.append(vt, style=Style(color=gold))
                if y == mid - 2 and h >= 7:
                    t.append(cross.center(inner), style=Style(color=accent, bold=True))
                elif y == mid:
                    t.append(self.initial.center(inner), style=Style(color=fg, bold=True))
                elif y == mid + 2 and h >= 7:
                    t.append(("\u00b7 \u00b7 \u00b7" if not ascii_only else ". . .").center(inner),
                             style=Style(color=gold, dim=True))
                else:
                    t.append(" " * inner)
                t.append(vt, style=Style(color=gold))
            if y < h - 1:
                t.append("\n")
        return t

    def on_unmount(self) -> None:
        pass


class Emblem(SaintIcon):
    """The double-headed eagle at the head of the tab column (true-image terminals only).

    In Kitty and Ghostty the light behind it pulses when you switch tabs (pulse()).
    Every step of the light is painted in the background and sent to the terminal
    once; a pulse then only switches between pictures the terminal holds, which
    costs nothing but a few placeholder cells. Sixel terminals show it still."""

    DEFAULT_CSS = """
    Emblem { width: 100%; height: 6; }
    """
    ATTACK = 0.14                   # seconds to the height of a pulse
    DECAY = 0.85                    # seconds back to rest
    FPS = 30

    def __init__(self, *, id: str | None = None, classes: str | None = None) -> None:
        super().__init__(id=id, classes=classes, framed=True)
        self.glow: tuple[int, int, int] | None = None
        self.level = 0                                  # the step of light shown now
        self.pulses = 0                                 # pulses asked for (the tests count them)
        self._energy = 0.0
        self._peak = 0.0
        self._rising = False
        self._last = 0.0
        self._timer = None
        self._sets: dict[tuple, list[int]] = {}        # (cols, rows, bg, glow) -> image ids, step by step
        self._preparing: set[tuple] = set()
        self._failed: set[tuple] = set()                # painting went wrong: not tried again

    # -- the pictures
    def picture_key(self) -> tuple:
        return ("eagle", self.glow)

    def picture(self, wpx: int, hpx: int, bg):
        return eagle.frame(wpx, hpx, bg, self.glow, 0)        # the eagle at rest (Sixel)

    def fancy(self) -> bool:
        return self.mode in ("kitty", "sixel") and art.available() and eagle.available()

    def _set_key(self) -> tuple | None:
        w, h = min(self.content_size.width, MAX_CELLS), min(self.content_size.height, MAX_CELLS)
        if w < 4 or h < 2:
            return None
        return (w, h, self._bg(), self.glow)

    def ready(self) -> bool:
        """Every step of light is in the terminal (a pulse can play)."""
        key = self._set_key()
        return key is not None and len(self._sets.get(key, ())) == eagle.LEVELS

    def _prepare(self, key: tuple) -> None:
        """Paint every step of light in the background, then send them from the main thread."""
        if key in self._preparing or key in self._failed:
            return
        self._preparing.add(key)
        w, h, bg, glow = key
        cw, ch = self._cell_px()

        def run() -> None:
            try:
                pics = eagle.frames(w * cw, h * ch, bg, glow)
            except Exception:
                pics = []
            try:
                self.app.call_from_thread(self._send, key, pics, 0)
            except Exception:
                pass
        threading.Thread(target=run, name="saintd-eagle", daemon=True).start()

    def _send(self, key: tuple, pics: list, i: int) -> None:
        """Send one step of light; the next follows on the next turn of the event loop,
        so the interface never stalls while they go out."""
        if not self.is_attached or not pics:
            self._preparing.discard(key)
            if not pics:
                self._failed.add(key)
            return
        w, h, bg, glow = key
        ids = self._sets.setdefault(key, [])
        if len(ids) == i:
            ids.append(kitty_send(self._write, ("eagle", glow, i, w, h, bg), pics[i], w, h,
                                  term.current().cell_px, bg))
        if i == 0:
            self.refresh()
        if i + 1 < len(pics):
            self.call_later(self._send, key, pics, i + 1)
        else:
            self._preparing.discard(key)
            if key == self._set_key():          # an older size or scheme finishing late keeps the new one
                self._forget_others(key)

    def _forget_others(self, keep: tuple) -> None:
        """Free the steps of light painted for an older colour scheme or size."""
        for key in [k for k in self._sets if k != keep]:
            for i, image_id in enumerate(self._sets.pop(key)):
                w, h, bg, glow = key
                _sent.pop(("eagle", glow, i, w, h, bg), None)
                try:
                    self._write(_tgp(a="d", d="I", i=image_id, q=2))
                except Exception:
                    pass

    def render(self):
        if not self.fancy():
            return ""
        if self.mode != "kitty":
            return super().render()
        key = self._set_key()
        if key is None or key in self._failed:
            return ""
        ids = self._sets.get(key)
        if not ids:
            self._prepare(key)
            w, h = key[0], key[1]
            return Text(" " * w + ("\n" + " " * w) * (h - 1))
        return KittyImage(ids[min(self.level, len(ids) - 1)], key[0], key[1])

    # -- the pulse
    def pulse(self, strength: float = 1.0) -> None:
        """Brighten the light behind the eagle and let it fade (Kitty, Ghostty)."""
        self.pulses += 1
        if self.mode != "kitty" or not self.fancy() or not self.display or not self.is_attached or not self.ready():
            return
        self._peak = min(1.0, max(strength, self._energy, self._peak if self._rising else 0.0))
        self._rising = True
        self._last = time.monotonic()
        if self._timer is None:
            self._timer = self.set_interval(1 / self.FPS, self._step)
        else:
            self._timer.resume()

    def _step(self) -> None:
        now = time.monotonic()
        dt, self._last = min(0.1, now - self._last), now
        if self._rising:
            self._energy = min(self._peak, self._energy + dt / self.ATTACK)
            if self._energy >= self._peak - 1e-6:
                self._rising = False
        else:
            self._energy = max(0.0, self._energy - dt / self.DECAY)
        e = self._energy
        level = round(e * e * (3 - 2 * e) * (eagle.LEVELS - 1))     # eased in and out
        if level != self.level:
            self.level = level
            self.refresh()
        if not self._rising and self._energy <= 0.0:
            self._peak = 0.0
            if self._timer is not None:
                self._timer.pause()


class Headpiece(SaintIcon):
    """The three-bar Orthodox cross between two ornamental rules, as at the head of a
    page of a service book: above the hymns and in the icon view. A picture in
    terminals that show true images, a line of text elsewhere."""

    DEFAULT_CSS = """
    Headpiece { width: 100%; height: 3; }
    """

    def __init__(self, *, id: str | None = None, classes: str | None = None) -> None:
        super().__init__(id=id, classes=classes, framed=True)
        self.glow: tuple[int, int, int] | None = None

    def on_mount(self) -> None:
        self.mode = getattr(self.app, "graphics_mode", "off")
        self._theme_glow()
        super().on_mount()

    def _theme_glow(self) -> None:
        try:
            self.glow = art._rgb(self.app.current_theme.primary)
        except Exception:
            self.glow = None

    def picture_key(self) -> tuple:
        return ("cross", self.glow)

    def picture(self, wpx: int, hpx: int, bg):
        return art.cross_headpiece(wpx, hpx, bg, self.glow)

    def fancy(self) -> bool:
        return self.mode in ("kitty", "sixel") and art.available()

    def render(self):
        if self.fancy():
            self._theme_glow()                  # follows the colour scheme
            return super().render()
        w, h = self.content_size.width, self.content_size.height
        try:
            theme = self.app.current_theme
            gold, accent = theme.primary, theme.accent or theme.primary
            ascii_only = self.app.ctx.cfg["glyphs"] == "ascii"
        except Exception:
            gold, accent, ascii_only = "yellow", "yellow", False
        cross, rule, dot = ("+", "-", "*") if ascii_only else ("\u2626", "\u2500", "\u25c6")
        side = max(0, min(14, (w - 5) // 2))
        t = Text(no_wrap=True, overflow="crop", justify="center")
        t.append("\n" * max(0, (h - 1) // 2))
        t.append(f"{dot}{rule * max(0, side - 1)} " if side else "", style=Style(color=gold))
        t.append(cross, style=Style(color=accent, bold=True))
        t.append(f" {rule * max(0, side - 1)}{dot}" if side else "", style=Style(color=gold))
        return t


def warm_frames(sizes: list[tuple[int, int]], bg: tuple[int, int, int]) -> None:
    """Paint the frames ahead of time (in a background thread) so the first icon shows at once."""
    if not art.available():
        return
    cw, ch = term.current().cell_px
    cw, ch = (cw, ch) if cw and ch else (10, 20)
    for w, h in sizes:
        try:
            art._frame_parts(w * cw, h * ch, bg)
        except Exception:
            pass


class _Centered:
    """Centre a fixed-size renderable inside the widget's box."""

    def __init__(self, inner, cols: int, rows: int, width: int, height: int) -> None:
        self.inner, self.cols, self.rows, self.width, self.height = inner, cols, rows, width, height

    def __rich_console__(self, console: Console, options: ConsoleOptions) -> RenderResult:
        left = max(0, (self.width - self.cols) // 2)
        top = max(0, (self.height - self.rows) // 2)
        right = max(0, self.width - self.cols - left)
        pad_l, pad_r = Segment(" " * left), Segment(" " * right)
        blank = Segment(" " * self.width)
        for _ in range(top):
            yield blank
            yield Segment.line()
        lines = list(Segment.split_lines(console.render(self.inner, options.update(width=self.cols, height=self.rows))))
        for i, line in enumerate(lines[: self.rows]):
            if left:
                yield pad_l
            yield from line
            if right:
                yield pad_r
            if i < self.rows - 1 or top + self.rows < self.height:
                yield Segment.line()
        for i in range(max(0, self.height - top - self.rows)):
            yield blank
            if i < self.height - top - self.rows - 1:
                yield Segment.line()


