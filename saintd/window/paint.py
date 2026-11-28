"""Painting the window's cells with Pillow, the way Kitty and Ghostty paint theirs.

Text comes from the monospaced font (and fallback fonts for what it lacks).
Box drawing (borders), block elements (colour-block pictures, scroll bars,
progress bars) and sextants are drawn as shapes that fill their cells exactly,
so that lines join and blocks meet without seams, as in those terminals.
Pictures sent with the Kitty graphics protocol are cut into the cells that
show them (Unicode placeholders), so the eagle and the icons look the same.
"""

from __future__ import annotations

from PIL import Image, ImageDraw, ImageFont

from ..graphics import _DIACRITICS
from .fonts import Coverage, FontFiles, read_coverage
from .vt import BOLD, CONCEAL, DIM, ITALIC, OVERLINE, PLACEHOLDER, REVERSE, STRIKE, UNDERLINE, UNDERLINE2

_DIACRITIC_INDEX = {chr(c): i for i, c in enumerate(_DIACRITICS)}
_SHADES = {0x2591: 64, 0x2592: 128, 0x2593: 192}
_S = 4                                  # supersampling for curves and diagonals


def is_drawn(cp: int) -> bool:
    """Characters drawn as shapes instead of taken from a font."""
    return 0x2500 <= cp <= 0x259F or 0x1FB00 <= cp <= 0x1FB3B


# box drawing U+2500..U+257F: (up, right, down, left), 0 none, 1 light, 2 heavy, 3 double
_BOX = {}
for _cp, _arms in zip(range(0x2500, 0x2504), [(0, 1, 0, 1), (0, 2, 0, 2), (1, 0, 1, 0), (2, 0, 2, 0)]):
    _BOX[_cp] = _arms
_CORNERS = "0110 0210 0120 0220 0011 0012 0021 0022 1100 1200 2100 2200 1001 1002 2001 2002 " \
           "1110 1210 2110 1120 2120 2210 1220 2220 1011 1012 2011 1021 2021 2012 1022 2022 " \
           "0111 0112 0211 0212 0121 0122 0221 0222 1101 1102 1201 1202 2101 2102 2201 2202 " \
           "1111 1112 1211 1212 2111 1121 2121 2112 2211 1122 1221 2212 1222 2122 2221 2222"
for _i, _code in enumerate(_CORNERS.split()):
    _BOX[0x250C + _i] = tuple(int(c) for c in _code)
_DOUBLES = "0303 3030 0310 0130 0330 0013 0031 0033 1300 3100 3300 1003 3001 3003 " \
           "1310 3130 3330 1013 3031 3033 0313 0131 0333 1303 3101 3303 1313 3131 3333"
for _i, _code in enumerate(_DOUBLES.split()):
    _BOX[0x2550 + _i] = tuple(int(c) for c in _code)
_HALVES = "0001 1000 0100 0010 0002 2000 0200 0020 0201 1020 0102 2010"
for _i, _code in enumerate(_HALVES.split()):
    _BOX[0x2574 + _i] = tuple(int(c) for c in _code)
# dashed lines: code point -> (horizontal?, weight, dashes)
_DASHES = {0x2504: (True, 1, 3), 0x2505: (True, 2, 3), 0x2506: (False, 1, 3), 0x2507: (False, 2, 3),
           0x2508: (True, 1, 4), 0x2509: (True, 2, 4), 0x250A: (False, 1, 4), 0x250B: (False, 2, 4),
           0x254C: (True, 1, 2), 0x254D: (True, 2, 2), 0x254E: (False, 1, 2), 0x254F: (False, 2, 2)}
# rounded corners: (vertical direction, horizontal direction)
_ARCS = {0x256D: ("down", "right"), 0x256E: ("down", "left"), 0x256F: ("up", "left"), 0x2570: ("up", "right")}


class Painter:
    """Paints rows of cells into Pillow images, at one font size."""

    def __init__(self, files: FontFiles | None, size_px: int, default_fg=(229, 229, 229), default_bg=(0, 0, 0)) -> None:
        self.size_px = size_px
        self.default_fg, self.default_bg = default_fg, default_bg
        self.files = files
        if files is not None:
            regular = self._load(files.faces[0], size_px)
            faces = [regular] + [self._load(f, size_px) if f else None for f in files.faces[1:]]
            self.coverage = files.coverage
        else:                                       # no monospaced font at all: Pillow's own
            regular = ImageFont.load_default(size=size_px)
            faces = [regular, None, None, None]
            self.coverage = Coverage([(32, 126)])
        self.faces = faces
        self.fake_bold = faces[1] is None
        ascent, descent = regular.getmetrics()
        self.cw = max(1, round(regular.getlength("M")))
        self.ch = max(2, ascent + descent)
        self.baseline = ascent
        self.descent = descent
        self.light = max(1, round(size_px / 15))
        self.heavy = max(self.light + 1, round(self.light * 2))
        self.underline_y = min(self.ch - self.light, ascent + max(1, round(descent * 0.4)))
        self.strike_y = max(0, ascent - round(ascent * 0.32))
        self._advance_ok: dict[str, bool] = {}
        self._glyphs: dict[tuple, Image.Image | None] = {}
        self._shapes: dict[int, Image.Image | None] = {}
        self._fallbacks: list[tuple] = []          # (Coverage, FreeTypeFont | None, spec), read when first needed
        self._fallbacks_read = False
        self._colors: dict[tuple, tuple] = {}
        self._tiles: dict[int, tuple] = {}         # image id -> (key, picture at its placement size)

    @staticmethod
    def _load(spec, size_px):
        path, index = spec
        try:
            return ImageFont.truetype(str(path), size_px, index=index, layout_engine=ImageFont.Layout.BASIC)
        except OSError:
            return None

    # ------------------------------------------------------------ colours
    def colors(self, st: tuple) -> tuple:
        """(foreground, background) of a style, with reverse video and faint text applied."""
        c = self._colors.get(st)
        if c is None:
            fg, bg, flags = st
            fg = fg or self.default_fg
            bg = bg or self.default_bg
            if flags & REVERSE:
                fg, bg = bg, fg
            if flags & DIM:
                fg = tuple((a + b) // 2 for a, b in zip(fg, bg))
            c = self._colors[st] = (fg, bg)
        return c

    # ------------------------------------------------------------ glyphs
    def _face(self, flags: int):
        i = (1 if flags & BOLD else 0) + (2 if flags & ITALIC else 0)
        f = self.faces[i]
        if f is None and i == 3:
            f = self.faces[2] or self.faces[1]
        return f or self.faces[0]

    def _fallback_for(self, cp: int):
        if not self._fallbacks_read:
            self._fallbacks_read = True
            for spec in (self.files.fallbacks if self.files else []):
                cov = read_coverage(*spec)
                if cov:
                    self._fallbacks.append([cov, None, spec])
        for item in self._fallbacks:
            if cp in item[0]:
                if item[1] is None:
                    item[1] = self._load(item[2], self.size_px) or False
                if item[1]:
                    return item[1]
        return None

    def runs_with(self, ch: str) -> bool:
        """Can this character be drawn as part of a line of text in the main font
        (one cell wide there, so that it stays on the grid)?"""
        ok = self._advance_ok.get(ch)
        if ok is None:
            cp = ord(ch)
            ok = (cp in self.coverage and not is_drawn(cp) and cp != 0x10EEEE
                  and self.faces[0].getlength(ch) == self.cw)
            self._advance_ok[ch] = ok
        return ok

    def glyph(self, text: str, flags: int, cells: int):
        """The mask of a cell's text (cells wide), or None if nothing shows."""
        key = (text, flags & (BOLD | ITALIC), cells)
        if key in self._glyphs:
            return self._glyphs[key]
        w, h = self.cw * cells, self.ch
        mask = Image.new("L", (w, h), 0)
        d = ImageDraw.Draw(mask)
        cp = ord(text[0])
        font = self._face(flags) if cp in self.coverage else self._fallback_for(cp)
        if font is None:
            font = self._face(flags)                    # shows the font's "missing" box
        if font in self.faces:
            d.text((0, self.baseline), text, font=font, fill=255, anchor="ls")
            if flags & BOLD and self.fake_bold:
                d.text((1, self.baseline), text, font=font, fill=255, anchor="ls")
        else:                                           # another font: fitted into the cell(s), centred
            left, top, right, bottom = font.getbbox(text, anchor="ls")
            iw, ih = right - left, bottom - top
            if iw > 0 and ih > 0:
                ink = Image.new("L", (iw, ih), 0)
                ImageDraw.Draw(ink).text((-left, -top), text, font=font, fill=255, anchor="ls")
                scale = min(1.0, (w - 1) / iw, h / ih)
                if scale < 1.0:
                    ink = ink.resize((max(1, round(iw * scale)), max(1, round(ih * scale))), Image.LANCZOS)
                    top = round(top * scale)
                x = (w - ink.width) // 2
                y = min(max(0, self.baseline + top), h - ink.height)
                mask.paste(ink, (x, y))
        g = mask if mask.getbbox() else None
        if len(self._glyphs) > 8000:
            self._glyphs.clear()
        self._glyphs[key] = g
        return g

    # ------------------------------------------------------------ shapes
    def shape(self, cp: int):
        """The mask of a box-drawing character, block element or sextant."""
        if cp in self._shapes:
            return self._shapes[cp]
        try:
            m = self._draw_shape(cp)
        except Exception:
            m = None
        self._shapes[cp] = m
        return m

    def _draw_shape(self, cp: int):
        cw, ch = self.cw, self.ch
        m = Image.new("L", (cw, ch), 0)

        def fill(x0, y0, x1, y1, v=255):
            if x1 > x0 and y1 > y0:
                m.paste(v, (int(x0), int(y0), int(x1), int(y1)))

        if 0x2580 <= cp <= 0x259F:
            self._block(cp, fill)
        elif 0x1FB00 <= cp <= 0x1FB3B:
            bits = cp - 0x1FB00 + 1
            if bits >= 21:
                bits += 1
            if bits >= 42:
                bits += 1
            xs, ys = (0, cw // 2, cw), (0, round(ch / 3), round(2 * ch / 3), ch)
            for i in range(6):
                if bits & (1 << i):
                    fill(xs[i % 2], ys[i // 2], xs[i % 2 + 1], ys[i // 2 + 1])
        elif cp in _BOX:
            self._box(_BOX[cp], fill)
        elif cp in _DASHES:
            horizontal, weight, n = _DASHES[cp]
            t = self.light if weight == 1 else self.heavy
            length = cw if horizontal else ch
            gap = max(1, round(length / n * 0.35))
            for i in range(n):
                a, b = round(i * length / n + gap / 2), round((i + 1) * length / n - gap / 2)
                if horizontal:
                    y = (ch - t) // 2
                    fill(a, y, b, y + t)
                else:
                    x = (cw - t) // 2
                    fill(x, a, x + t, b)
        elif cp in _ARCS:
            m = self._arc(*_ARCS[cp])
        elif cp in (0x2571, 0x2572, 0x2573):
            big = Image.new("L", (cw * _S, ch * _S), 0)
            d = ImageDraw.Draw(big)
            w = self.light * _S
            if cp in (0x2571, 0x2573):
                d.line([(cw * _S, 0), (0, ch * _S)], fill=255, width=w)
            if cp in (0x2572, 0x2573):
                d.line([(0, 0), (cw * _S, ch * _S)], fill=255, width=w)
            m = big.resize((cw, ch), Image.BOX)
        else:
            return None
        return m if m.getbbox() else None

    def _block(self, cp: int, fill) -> None:
        cw, ch = self.cw, self.ch
        if cp == 0x2580:
            fill(0, 0, cw, ch // 2)
        elif 0x2581 <= cp <= 0x2588:                    # lower eighths .. full block
            fill(0, ch - round(ch * (cp - 0x2580) / 8), cw, ch)
        elif 0x2589 <= cp <= 0x258F:                    # left seven eighths .. left eighth
            fill(0, 0, round(cw * (0x2590 - cp) / 8), ch)
        elif cp == 0x2590:
            fill(cw // 2, 0, cw, ch)
        elif cp in _SHADES:
            fill(0, 0, cw, ch, _SHADES[cp])
        elif cp == 0x2594:
            fill(0, 0, cw, round(ch / 8))
        elif cp == 0x2595:
            fill(cw - round(cw / 8), 0, cw, ch)
        else:                                           # quadrants: bit 1 upper left, 2 upper right, 4 lower left, 8 lower right
            quads = {0x2596: 4, 0x2597: 8, 0x2598: 1, 0x2599: 13, 0x259A: 9, 0x259B: 7, 0x259C: 11, 0x259D: 2,
                     0x259E: 6, 0x259F: 14}[cp]
            hx, hy = cw // 2, ch // 2
            for bit, box in ((1, (0, 0, hx, hy)), (2, (hx, 0, cw, hy)), (4, (0, hy, hx, ch)), (8, (hx, hy, cw, ch))):
                if quads & bit:
                    fill(*box)

    def _box(self, arms: tuple, fill) -> None:
        """Lines from the middle of the cell to its edges, joined; double lines as two rails."""
        up, right, down, left = arms
        cw, ch, t1 = self.cw, self.ch, self.light

        def thick(w):
            return self.heavy if w == 2 else t1

        gap_v = max(t1 + 1, round(cw * 0.2))
        gap_h = max(t1 + 1, round(ch * 0.12))
        va = (cw - (2 * t1 + gap_v)) // 2                # the two vertical rails of a double line
        vb = va + t1 + gap_v
        ha = (ch - (2 * t1 + gap_h)) // 2                # the two horizontal rails
        hb = ha + t1 + gap_h

        def vx(w):                                      # x of a single vertical line of weight w
            return (cw - thick(w)) // 2

        def hy(w):
            return (ch - thick(w)) // 2

        # left and right edges of the vertical arms, top and bottom edges of the horizontal ones
        def v_edges(w):
            return (va, vb + t1) if w == 3 else (vx(w), vx(w) + thick(w))

        def h_edges(w):
            return (ha, hb + t1) if w == 3 else (hy(w), hy(w) + thick(w))

        verticals = [w for w in (up, down) if w]
        horizontals = [w for w in (left, right) if w]
        x_lo = min((v_edges(w)[0] for w in verticals), default=None)
        x_hi = max((v_edges(w)[1] for w in verticals), default=None)
        y_lo = min((h_edges(w)[0] for w in horizontals), default=None)
        y_hi = max((h_edges(w)[1] for w in horizontals), default=None)

        # single and heavy arms: from the edge to across the lines they meet
        if left in (1, 2):
            y = hy(left)
            fill(0, y, x_hi if x_hi is not None else vx(left) + thick(left), y + thick(left))
        if right in (1, 2):
            y = hy(right)
            fill(x_lo if x_lo is not None else vx(right), y, cw, y + thick(right))
        if up in (1, 2):
            x = vx(up)
            fill(x, 0, x + thick(up), y_hi if y_hi is not None else hy(up) + thick(up))
        if down in (1, 2):
            x = vx(down)
            fill(x, y_lo if y_lo is not None else hy(down), x + thick(down), ch)

        # double arms: two rails, turning into the rails (or line) they meet
        def up_left(w):                                 # left edge of the up arm's left line, etc.
            return va if w == 3 else vx(w)

        def up_right(w):
            return vb if w == 3 else vx(w)

        if left == 3 or right == 3:
            mid = cw // 2
            for rail, y in (("top", ha), ("bottom", hb)):
                if left == 3:
                    if rail == "top":
                        stop = (up_left(up) + t1 if up == 3 else vx(up) + thick(up)) if up else \
                               (up_right(down) + t1 if down == 3 else vx(down) + thick(down)) if down else \
                               (cw if right == 3 else mid + t1)
                    else:
                        stop = (up_left(down) + t1 if down == 3 else vx(down) + thick(down)) if down else \
                               (up_right(up) + t1 if up == 3 else vx(up) + thick(up)) if up else \
                               (cw if right == 3 else mid + t1)
                    fill(0, y, stop, y + t1)
                if right == 3:
                    if rail == "top":
                        start = up_right(up) if up else up_left(down) if down else (0 if left == 3 else mid)
                    else:
                        start = up_right(down) if down else up_left(up) if up else (0 if left == 3 else mid)
                    fill(start, y, cw, y + t1)

        def h_top(w):
            return ha if w == 3 else hy(w)

        def h_bottom(w):
            return hb if w == 3 else hy(w)

        if up == 3 or down == 3:
            mid = ch // 2
            for rail, x in (("left", va), ("right", vb)):
                if up == 3:
                    if rail == "left":
                        stop = (h_top(left) + t1 if left == 3 else hy(left) + thick(left)) if left else \
                               (h_bottom(right) + t1 if right == 3 else hy(right) + thick(right)) if right else \
                               (ch if down == 3 else mid + t1)
                    else:
                        stop = (h_top(right) + t1 if right == 3 else hy(right) + thick(right)) if right else \
                               (h_bottom(left) + t1 if left == 3 else hy(left) + thick(left)) if left else \
                               (ch if down == 3 else mid + t1)
                    fill(x, 0, x + t1, stop)
                if down == 3:
                    if rail == "left":
                        start = h_bottom(left) if left else h_top(right) if right else (0 if up == 3 else mid)
                    else:
                        start = h_bottom(right) if right else h_top(left) if left else (0 if up == 3 else mid)
                    fill(x, start, x + t1, ch)

    def _arc(self, vertical: str, horizontal: str):
        """A rounded corner (╭ ╮ ╯ ╰), drawn four times larger and scaled down for smooth edges."""
        cw, ch, t1 = self.cw, self.ch, self.light
        big = Image.new("L", (cw * _S, ch * _S), 0)
        d = ImageDraw.Draw(big)
        t = t1 * _S
        lx = ((cw - t1) // 2) * _S + t / 2              # the middle of the vertical and the horizontal line
        ly = ((ch - t1) // 2) * _S + t / 2
        rx = (cw * _S - lx) if horizontal == "right" else lx
        ry = (ch * _S - ly) if vertical == "down" else ly
        r = max(t, min(rx, ry))
        cx = lx + r if horizontal == "right" else lx - r
        cy = ly + r if vertical == "down" else ly - r
        start = {("down", "right"): 180, ("down", "left"): 270, ("up", "left"): 0, ("up", "right"): 90}[
            (vertical, horizontal)]
        outer = r + t / 2
        d.arc([cx - outer, cy - outer, cx + outer, cy + outer], start, start + 90, fill=255, width=int(t))
        if vertical == "down":
            d.rectangle([lx - t / 2, cy, lx + t / 2 - 1, ch * _S], fill=255)
        else:
            d.rectangle([lx - t / 2, 0, lx + t / 2 - 1, cy], fill=255)
        if horizontal == "right":
            d.rectangle([cx, ly - t / 2, cw * _S, ly + t / 2 - 1], fill=255)
        else:
            d.rectangle([0, ly - t / 2, cx, ly + t / 2 - 1], fill=255)
        return big.resize((cw, ch), Image.BOX)

    # ------------------------------------------------------------ pictures
    def _tile(self, images, image_id: int):
        """The picture at the size of its placement (columns x rows of cells), or None."""
        box = images.boxes.get(image_id)
        item = images.data.get(image_id)
        if item is None:
            return None
        key = (id(item), box, self.cw, self.ch)
        cached = self._tiles.get(image_id)
        if cached is not None and cached[0] == key:
            return cached[1]
        im = images.decode(image_id)
        if im is None:
            self._tiles[image_id] = (key, None)
            return None
        cols, rows = box if box and box[0] and box[1] else (-(-im.width // self.cw), -(-im.height // self.ch))
        w, h = cols * self.cw, rows * self.ch
        if (im.width, im.height) != (w, h):
            # fitted into the box without distortion and centred, as Kitty does
            scale = min(w / im.width, h / im.height)
            sw, sh = max(1, round(im.width * scale)), max(1, round(im.height * scale))
            fitted = im.resize((sw, sh), Image.LANCZOS)
            canvas = Image.new("RGBA", (w, h), (0, 0, 0, 0))
            canvas.paste(fitted.convert("RGBA"), ((w - sw) // 2, (h - sh) // 2))
            im = canvas
        if len(self._tiles) > 96:
            self._tiles = {k: v for k, v in self._tiles.items() if k in images.data}
        self._tiles[image_id] = (key, im)
        return im

    def _picture_run(self, img, texts, styles, x: int, images) -> int:
        """Paint the placeholder cells from x that show one row of one picture; the index after them."""
        n = len(texts)

        def decode(i, prev):
            t, fg = texts[i], styles[i][0]
            image_id = (fg[0] << 16 | fg[1] << 8 | fg[2]) if fg else 0
            row = _DIACRITIC_INDEX.get(t[1]) if len(t) > 1 else None
            col = _DIACRITIC_INDEX.get(t[2]) if len(t) > 2 else None
            if len(t) > 3 and t[3] in _DIACRITIC_INDEX:
                image_id |= _DIACRITIC_INDEX[t[3]] << 24
            if prev is not None and prev[0] == image_id:       # left out: continue the cell before
                if row is None:
                    row = prev[1]
                if col is None and row == prev[1]:
                    col = prev[2] + 1
            return image_id, row or 0, col or 0

        first = decode(x, None)
        image_id, row, col = first
        end, last = x + 1, first
        while end < n and texts[end][:1] == PLACEHOLDER:
            nxt = decode(end, last)
            if nxt[0] != image_id or nxt[1] != row or nxt[2] != last[2] + 1:
                break
            last = nxt
            end += 1
        pic = self._tile(images, image_id)
        if pic is not None:
            cw, ch = self.cw, self.ch
            piece = pic.crop((col * cw, row * ch, (col + end - x) * cw, (row + 1) * ch))
            if piece.mode == "RGBA":
                img.paste(piece, (x * cw, 0), piece)
            else:
                img.paste(piece, (x * cw, 0))
        return end

    # ------------------------------------------------------------ a row of cells
    def paint_row(self, img, texts: list[str], styles: list[tuple], images, right_pad: int = 0) -> None:
        """Paint one row of cells into img (its height is one cell; cells start at x = 0).
        The right_pad pixels after the last cell take its background (no seam at the edge)."""
        cw, ch = self.cw, self.ch
        n = len(texts)
        colors = self.colors
        pal = [colors(st) for st in styles]
        x = 0
        while x < n:                                    # backgrounds, in runs of one colour
            bg = pal[x][1]
            x2 = x + 1
            while x2 < n and pal[x2][1] == bg:
                x2 += 1
            img.paste(bg, (x * cw, 0, x2 * cw + (right_pad if x2 == n else 0), ch))
            x = x2
        draw = None
        x = 0
        while x < n:
            t = texts[x]
            if t == " " or not t:
                x += 1
                continue
            flags = styles[x][2]
            if flags & CONCEAL:
                x += 1
                continue
            c0 = t[0]
            cp = ord(c0)
            fg = pal[x][0]
            if c0 == PLACEHOLDER:
                x = self._picture_run(img, texts, styles, x, images)
                continue
            if len(t) == 1 and is_drawn(cp):
                m = self.shape(cp)
                if m is not None:
                    img.paste(fg, (x * cw, 0), m)
                x += 1
                continue
            wide = x + 1 < n and texts[x + 1] == ""
            if len(t) == 1 and not wide and self.runs_with(c0):
                # a run of plain text in one colour and style: drawn in one go
                x2 = x + 1
                while x2 < n:
                    t2 = texts[x2]
                    if len(t2) != 1 or styles[x2][2] & (BOLD | ITALIC | CONCEAL) != flags & (BOLD | ITALIC | CONCEAL):
                        break
                    if t2 != " " and (pal[x2][0] != fg or not self.runs_with(t2)):
                        break
                    if x2 + 1 < n and texts[x2 + 1] == "":
                        break
                    x2 += 1
                if draw is None:
                    draw = ImageDraw.Draw(img)
                run = "".join(texts[x:x2]).rstrip(" ")
                font = self._face(flags)
                draw.text((x * cw, self.baseline), run, font=font, fill=fg, anchor="ls")
                if flags & BOLD and self.fake_bold:
                    draw.text((x * cw + 1, self.baseline), run, font=font, fill=fg, anchor="ls")
                x = x2
                continue
            g = self.glyph(t, flags, 2 if wide else 1)
            if g is not None:
                img.paste(fg, (x * cw, 0), g)
            x += 2 if wide else 1
        # lines: underline, double underline, strike-through, overline
        for x in range(n):
            flags = styles[x][2]
            if flags & (UNDERLINE | UNDERLINE2 | STRIKE | OVERLINE) and texts[x] != "":
                fg = pal[x][0]
                w = cw * (2 if x + 1 < n and texts[x + 1] == "" else 1)
                t = self.light
                if flags & (UNDERLINE | UNDERLINE2):
                    img.paste(fg, (x * cw, self.underline_y, x * cw + w, self.underline_y + t))
                if flags & UNDERLINE2:
                    y2 = min(ch - t, self.underline_y + 2 * t)
                    if y2 > self.underline_y + t:
                        img.paste(fg, (x * cw, y2, x * cw + w, y2 + t))
                if flags & STRIKE:
                    img.paste(fg, (x * cw, self.strike_y, x * cw + w, self.strike_y + t))
                if flags & OVERLINE:
                    img.paste(fg, (x * cw, 0, x * cw + w, t))
