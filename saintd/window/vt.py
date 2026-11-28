"""The window's terminal: a grid of cells kept up to date from the escape codes
the app writes, the way a terminal does.

Textual (and so saintd) writes the same output here as to Kitty or Ghostty:
cursor moves, colours (SGR), synchronised updates, and pictures through the
Kitty graphics protocol, which saintd uses with Unicode placeholder cells.
Only what that output needs is understood; anything else is skipped.

A cell holds its text ("" for the second half of a wide character, a base
character plus combining marks otherwise) and a style: (fg, bg, flags), with
the colours as (r, g, b) tuples or None for the default colour.
"""

from __future__ import annotations

import base64
import io
import re
import threading
import time
import zlib

from rich.cells import get_character_cell_size

BOLD, DIM, ITALIC, UNDERLINE, BLINK, REVERSE, CONCEAL, STRIKE, UNDERLINE2, OVERLINE = (1 << i for i in range(10))
DEFAULT = (None, None, 0)
PLACEHOLDER = "\U0010EEEE"          # Kitty's Unicode placeholder for image cells

# the 256-colour palette (16 system colours, the 6x6x6 cube, 24 greys)
_SYSTEM = [(0, 0, 0), (205, 49, 49), (13, 188, 121), (229, 229, 16), (36, 114, 200), (188, 63, 188),
           (17, 168, 205), (229, 229, 229), (102, 102, 102), (241, 76, 76), (35, 209, 139), (245, 245, 67),
           (59, 142, 234), (214, 112, 214), (41, 184, 219), (255, 255, 255)]
_LEVELS = (0, 95, 135, 175, 215, 255)
PALETTE = _SYSTEM + [(_LEVELS[i // 36], _LEVELS[i // 6 % 6], _LEVELS[i % 6]) for i in range(216)] + \
          [(8 + 10 * i,) * 3 for i in range(24)]

_CSI = re.compile(r"\x1b\[([0-?]*)([ -/]*)([@-~])")
_CSI_OPEN = re.compile(r"\x1b\[[0-?]*[ -/]*\Z")
_STRING_END = re.compile(r"\x07|\x1b\\")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


class Images:
    """Pictures sent with the Kitty graphics protocol, by image id. The PNG bytes are
    kept as they came; the window decodes each picture the first time it is shown."""

    def __init__(self) -> None:
        self.data: dict[int, tuple] = {}            # id -> (format, bytes, width, height)
        self.boxes: dict[int, tuple[int, int]] = {}  # id -> (columns, rows) of its placeholder placement
        self.version = 0                            # changes whenever a picture comes or goes
        self._chunks: list[str] | None = None
        self._first: dict[str, str] = {}

    def command(self, body: str) -> None:
        ctrl, _, payload = body.partition(";")
        keys = dict(kv.split("=", 1) for kv in ctrl.split(",") if "=" in kv)
        if self._chunks is not None:                # the rest of a picture sent in pieces
            self._chunks.append(payload)
            if keys.get("m", "0") != "1":
                first, chunks = self._first, self._chunks
                self._chunks, self._first = None, {}
                self._transmit(first, "".join(chunks))
            return
        action = keys.get("a", "t")
        if action in ("t", "T"):
            if keys.get("m") == "1":
                self._first, self._chunks = keys, [payload]
            else:
                self._transmit(keys, payload)
        elif action == "p":
            self._place(keys)
        elif action == "d":
            what = keys.get("d", "a")
            if what in ("I", "i") and keys.get("i", "").isdigit():
                i = int(keys["i"])
                self.data.pop(i, None)
                self.boxes.pop(i, None)
            elif what in ("A", "a"):
                self.boxes.clear()
            self.version += 1

    def _transmit(self, keys: dict, payload: str) -> None:
        if keys.get("t", "d") != "d" or not keys.get("i", "").isdigit():
            return                                  # only pictures sent inline, with an id
        try:
            raw = base64.standard_b64decode(payload)
            if keys.get("o") == "z":
                raw = zlib.decompress(raw)
        except Exception:
            return
        i = int(keys["i"])
        fmt = keys.get("f", "32")
        self.data[i] = (fmt, raw, int(keys.get("s", 0) or 0), int(keys.get("v", 0) or 0))
        self.version += 1
        if keys.get("a") == "T":
            self._place(keys)

    def _place(self, keys: dict) -> None:
        if keys.get("i", "").isdigit():
            self.boxes[int(keys["i"])] = (int(keys.get("c", 0) or 0), int(keys.get("r", 0) or 0))
            self.version += 1

    def decode(self, image_id: int):
        """The picture as a Pillow image (RGB or RGBA), or None."""
        item = self.data.get(image_id)
        if item is None:
            return None
        fmt, raw, w, h = item
        try:
            from PIL import Image
            if fmt == "100":
                im = Image.open(io.BytesIO(raw))
                im.load()
                return im if im.mode in ("RGB", "RGBA") else im.convert("RGBA")
            if fmt in ("24", "32") and w and h:
                return Image.frombytes("RGB" if fmt == "24" else "RGBA", (w, h), raw)
        except Exception:
            return None
        return None


class Screen:
    """The grid of cells and the cursor. feed() runs in the app's thread, the window
    reads the grid from its own thread: both hold `lock`."""

    def __init__(self, cols: int, rows: int) -> None:
        self.lock = threading.RLock()
        self.cols, self.rows = max(1, cols), max(1, rows)
        self.text = [[" "] * self.cols for _ in range(self.rows)]
        self.style = [[DEFAULT] * self.cols for _ in range(self.rows)]
        self.dirty: set[int] = set(range(self.rows))
        self.x = self.y = 0
        self.pen = DEFAULT
        self.cursor_visible = False
        self.synchronized = False       # in the middle of an update (synchronised output)
        self.sync_since = 0.0
        self.images = Images()
        self.events: list[tuple] = []   # for the window: ("clipboard", text), ("pointer", shape), ("title", t), ("bell",)
        self._pending = ""
        self._styles: dict[tuple, tuple] = {DEFAULT: DEFAULT}
        self._sgr_cache: dict[tuple, tuple] = {}

    # ------------------------------------------------------------ size
    def resize(self, cols: int, rows: int) -> None:
        with self.lock:
            cols, rows = max(1, cols), max(1, rows)
            if (cols, rows) == (self.cols, self.rows):
                return
            for r in range(min(rows, self.rows)):
                t, s = self.text[r], self.style[r]
                if cols < self.cols:
                    del t[cols:], s[cols:]
                    if self._is_wide_start(t, cols - 1):
                        t[cols - 1] = " "           # its right half was cut off
                else:
                    t.extend([" "] * (cols - self.cols))
                    s.extend([DEFAULT] * (cols - self.cols))
            if rows < self.rows:
                del self.text[rows:], self.style[rows:]
            else:
                for _ in range(rows - self.rows):
                    self.text.append([" "] * cols)
                    self.style.append([DEFAULT] * cols)
            self.cols, self.rows = cols, rows
            self.x, self.y = min(self.x, cols - 1), min(self.y, rows - 1)
            self.dirty = set(range(rows))

    @staticmethod
    def _is_wide_start(row: list[str], x: int) -> bool:
        t = row[x]
        return bool(t) and get_character_cell_size(t[0]) == 2

    # ------------------------------------------------------------ input
    def feed(self, data: str) -> None:
        """Apply output from the app."""
        with self.lock:
            if self._pending:
                data, self._pending = self._pending + data, ""
            pos, n = 0, len(data)
            search = _CONTROL.search
            while pos < n:
                m = search(data, pos)
                if m is None:
                    self._print(data[pos:])
                    break
                start = m.start()
                if start > pos:
                    self._print(data[pos:start])
                c = data[start]
                if c == "\x1b":
                    end = self._escape(data, start)
                    if end < 0:                     # cut off: wait for the rest
                        self._pending = data[start:]
                        if len(self._pending) > 64 << 20:
                            self._pending = ""      # never hold on to an endless string
                        break
                    pos = end
                else:
                    self._control(c)
                    pos = start + 1

    def _control(self, c: str) -> None:
        if c == "\r":
            self.x = 0
        elif c == "\n":
            self.y = min(self.rows - 1, self.y + 1)
        elif c == "\b":
            self.x = max(0, self.x - 1)
        elif c == "\t":
            self.x = min(self.cols - 1, (self.x // 8 + 1) * 8)
        elif c == "\x07":
            self.events.append(("bell",))

    def _escape(self, data: str, i: int) -> int:
        """Handle the escape sequence at data[i]; the index after it, or -1 if it is incomplete."""
        if i + 1 >= len(data):
            return -1
        kind = data[i + 1]
        if kind == "[":
            m = _CSI.match(data, i)
            if m is None:
                return -1 if _CSI_OPEN.match(data, i) else i + 2
            self._csi(m.group(1), m.group(2), m.group(3))
            return m.end()
        if kind in "]_P^X":                         # OSC, APC, DCS, PM, SOS: a string up to BEL or ST
            m = _STRING_END.search(data, i + 2)
            if m is None:
                return -1
            body = data[i + 2:m.start()]
            if kind == "]":
                self._osc(body)
            elif kind == "_" and body.startswith("G"):
                self.images.command(body[1:])
            return m.end()
        if kind in "()*+-./#%":                     # character set and similar: one more character
            return i + 3 if i + 2 < len(data) else -1
        if kind == "c":                             # full reset
            self.pen = DEFAULT
            self._erase_rows(0, self.rows)
            self.x = self.y = 0
        return i + 2

    # ------------------------------------------------------------ text
    def _print(self, s: str) -> None:
        y, cols = self.y, self.cols
        row_t, row_s = self.text[y], self.style[y]
        x, pen = self.x, self.pen
        if s.isascii():
            if x >= cols:
                x = cols - 1                        # no line wrap: the last column is overwritten
                s = s[-1:]
            end = min(cols, x + len(s))
            if row_t[x] == "" and x > 0:
                row_t[x - 1] = " "                  # the left half of a wide character is gone
            row_t[x:end] = s[:end - x]
            row_s[x:end] = [pen] * (end - x)
            if end < cols and row_t[end] == "":
                row_t[end] = " "
            self.x = end
            self.dirty.add(y)
            return
        for ch in s:
            w = get_character_cell_size(ch)
            if w == 0:                              # a combining mark: joins the character before it
                px = x - 1
                if px >= 0 and row_t[px] == "" and px > 0:
                    px -= 1
                if px >= 0:
                    row_t[px] += ch
                continue
            if x >= cols:
                x = cols - 1
            if w == 2 and x + 1 >= cols:
                ch, w = " ", 1
            if row_t[x] == "" and x > 0:
                row_t[x - 1] = " "
            if x + w < cols and row_t[x + w] == "":
                row_t[x + w] = " "
            row_t[x] = ch
            row_s[x] = pen
            if w == 2:
                row_t[x + 1] = ""
                row_s[x + 1] = pen
            x += w
        self.x = min(x, cols)
        self.dirty.add(y)

    def _blank(self, y: int, a: int, b: int) -> None:
        """Erase cells a..b-1 of row y, in the current background colour (as terminals do)."""
        a, b = max(0, a), min(self.cols, b)
        if a >= b or not 0 <= y < self.rows:
            return
        st = (None, self.pen[1], 0)
        st = self._styles.setdefault(st, st)
        row_t = self.text[y]
        if row_t[a] == "" and a > 0:
            row_t[a - 1] = " "
        if b < self.cols and row_t[b] == "":
            row_t[b] = " "
        row_t[a:b] = [" "] * (b - a)
        self.style[y][a:b] = [st] * (b - a)
        self.dirty.add(y)

    def _erase_rows(self, y0: int, y1: int) -> None:
        for y in range(max(0, y0), min(self.rows, y1)):
            self._blank(y, 0, self.cols)

    # ------------------------------------------------------------ control sequences
    def _csi(self, params: str, inter: str, final: str) -> None:
        if inter:
            return                                  # DECRQM and similar questions: not answered
        if params[:1] in "<=>?":
            if params[:1] == "?" and final in "hl":
                on = final == "h"
                for p in params[1:].split(";"):
                    if p == "25":
                        self.cursor_visible = on
                    elif p == "2026":
                        self.synchronized = on
                        if on:
                            self.sync_since = time.monotonic()
                    elif p in ("1049", "1047", "47") and on:
                        self._erase_rows(0, self.rows)
            return
        if final == "m":
            self._sgr(params)
            return
        args = [int(p) if p.isdigit() else 0 for p in params.split(";")] if params else []

        def arg(i: int, default: int = 1) -> int:
            return args[i] if len(args) > i and args[i] else default

        if final in "Hf":
            self.y = min(self.rows - 1, arg(0) - 1)
            self.x = min(self.cols - 1, arg(1) - 1)
        elif final == "A":
            self.y = max(0, self.y - arg(0))
        elif final in "Be":
            self.y = min(self.rows - 1, self.y + arg(0))
        elif final in "Ca":
            self.x = min(self.cols - 1, self.x + arg(0))
        elif final == "D":
            self.x = max(0, self.x - arg(0))
        elif final == "E":
            self.x, self.y = 0, min(self.rows - 1, self.y + arg(0))
        elif final == "F":
            self.x, self.y = 0, max(0, self.y - arg(0))
        elif final in "G`":
            self.x = min(self.cols - 1, arg(0) - 1)
        elif final == "d":
            self.y = min(self.rows - 1, arg(0) - 1)
        elif final == "J":
            mode = arg(0, 0)
            if mode == 0:
                self._blank(self.y, self.x, self.cols)
                self._erase_rows(self.y + 1, self.rows)
            elif mode == 1:
                self._erase_rows(0, self.y)
                self._blank(self.y, 0, self.x + 1)
            else:
                self._erase_rows(0, self.rows)
        elif final == "K":
            mode = arg(0, 0)
            a, b = {0: (self.x, self.cols), 1: (0, self.x + 1)}.get(mode, (0, self.cols))
            self._blank(self.y, a, b)
        elif final == "X":
            self._blank(self.y, self.x, self.x + arg(0))

    def _sgr(self, params: str) -> None:
        key = (params, self.pen)
        pen = self._sgr_cache.get(key)
        if pen is None:
            pen = self._sgr_apply(params, self.pen)
            pen = self._styles.setdefault(pen, pen)
            if len(self._sgr_cache) > 20000:
                self._sgr_cache.clear()
            self._sgr_cache[key] = pen
        self.pen = pen

    @staticmethod
    def _sgr_apply(params: str, pen: tuple) -> tuple:
        fg, bg, flags = pen
        parts = params.split(";") if params else ["0"]
        i = 0
        while i < len(parts):
            p = parts[i]
            if ":" in p:                            # sub-parameters: 38:2::r:g:b, 4:3 ...
                sub = p.split(":")
                code = int(sub[0] or 0) if sub[0].isdigit() else -1
                if code in (38, 48):
                    color = _color_from(sub[1:])
                    if code == 38:
                        fg = color
                    else:
                        bg = color
                elif code == 4:
                    flags &= ~(UNDERLINE | UNDERLINE2)
                    style = sub[1] if len(sub) > 1 else "1"
                    if style == "2":
                        flags |= UNDERLINE2
                    elif style not in ("0", ""):
                        flags |= UNDERLINE
                i += 1
                continue
            code = int(p) if p.isdigit() else 0
            if code == 0:
                fg, bg, flags = None, None, 0
            elif code in (38, 48):
                if i + 1 < len(parts) and parts[i + 1] == "5" and i + 2 < len(parts):
                    color = _color_from(parts[i + 1:i + 3])
                    i += 2
                elif i + 1 < len(parts) and parts[i + 1] == "2" and i + 4 < len(parts):
                    color = _color_from(parts[i + 1:i + 5])
                    i += 4
                else:
                    color = None
                    i = len(parts)
                if code == 38:
                    fg = color
                else:
                    bg = color
            elif 30 <= code <= 37:
                fg = PALETTE[code - 30]
            elif 40 <= code <= 47:
                bg = PALETTE[code - 40]
            elif 90 <= code <= 97:
                fg = PALETTE[code - 82]
            elif 100 <= code <= 107:
                bg = PALETTE[code - 92]
            elif code == 39:
                fg = None
            elif code == 49:
                bg = None
            elif code in _SET:
                flags |= _SET[code]
            elif code in _CLEAR:
                flags &= ~_CLEAR[code]
            i += 1
        return fg, bg, flags

    def _osc(self, body: str) -> None:
        code, _, rest = body.partition(";")
        if code in ("0", "2"):
            self.events.append(("title", rest))
        elif code == "22":
            self.events.append(("pointer", rest))
        elif code == "52":
            _target, _, data = rest.partition(";")
            if data and data != "?":
                try:
                    self.events.append(("clipboard", base64.standard_b64decode(data).decode("utf-8", "replace")))
                except Exception:
                    pass

    # ------------------------------------------------------------ for the window
    def take(self) -> tuple[list[tuple[int, list[str], list[tuple]]], list[tuple]]:
        """The rows changed since the last call (copies) and the events for the window."""
        with self.lock:
            rows = [(y, self.text[y][:], self.style[y][:]) for y in sorted(self.dirty) if y < self.rows]
            self.dirty.clear()
            events, self.events = self.events, []
            return rows, events

    def row(self, y: int) -> tuple[list[str], list[tuple]]:
        with self.lock:
            return self.text[y][:], self.style[y][:]


_SET = {1: BOLD, 2: DIM, 3: ITALIC, 4: UNDERLINE, 5: BLINK, 6: BLINK, 7: REVERSE, 8: CONCEAL, 9: STRIKE,
        21: UNDERLINE2, 53: OVERLINE}
_CLEAR = {22: BOLD | DIM, 23: ITALIC, 24: UNDERLINE | UNDERLINE2, 25: BLINK, 27: REVERSE, 28: CONCEAL, 29: STRIKE,
          55: OVERLINE}


def _color_from(sub: list[str]):
    """[5, n] or [2, r, g, b] or [2, colour space, r, g, b] -> (r, g, b)"""
    try:
        if sub and sub[0] == "5":
            return PALETTE[int(sub[1]) & 255]
        if sub and sub[0] == "2":
            nums = [int(v) for v in sub[1:] if v != ""][-3:]
            if len(nums) == 3:
                return tuple(max(0, min(255, v)) for v in nums)
    except (ValueError, IndexError):
        pass
    return None
