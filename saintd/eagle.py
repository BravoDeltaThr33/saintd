"""The double-headed eagle at the head of the tab column, for terminals that
show true images (Kitty, Ghostty, Sixel terminals).

It follows the eagle of the Greek Orthodox Church (the Byzantine eagle of the
Church of Greece and Mount Athos): two heads turned outward with hooked beaks
and crests, the closed imperial crown floating above and between them, scaled
necks and breast, wings arched at the shoulders with long feathers sweeping
down, the legs held out to the sides with the sword in the eagle's right claw
and the orb with its cross in the left. It is gilded here, like the eagles
carved on church thrones and lecterns.

The eagle is drawn once per size; the light behind it comes in steps
(`frames`), from the quiet glow at rest to a bright aureole, so the tab column
can make it pulse by switching between pictures the terminal already holds.

The design is laid out on an 840 x 745 grid; the viewer's left half is drawn
and mirrored (the sword and the orb are drawn once). Everything is painted at a
few times the size and scaled down."""

from __future__ import annotations

import math
from functools import lru_cache

from . import art

try:
    from PIL import Image, ImageChops, ImageDraw, ImageFilter
except Exception:                       # pragma: no cover - Pillow comes with textual-image
    Image = None

DW = 840                                # the width of the design grid (745 high)
BOX = (14, 24, 826, 716)                # what the eagle covers of it
LEVELS = 10                             # steps of light, from rest (0) to the height of a pulse
MARGIN = 0.05

PEARL = (252, 242, 216)
STEEL = (218, 226, 236)
STEEL_LINE = (118, 128, 146)
GRIP = (120, 30, 24)


# ---------------------------------------------------------------- drawing helpers

def _bez(p0, p1, p2, p3, n: int = 18) -> list:
    """Points along a cubic Bézier curve."""
    out = []
    for i in range(n + 1):
        t = i / n
        u = 1 - t
        out.append((u * u * u * p0[0] + 3 * u * u * t * p1[0] + 3 * u * t * t * p2[0] + t * t * t * p3[0],
                    u * u * u * p0[1] + 3 * u * u * t * p1[1] + 3 * u * t * t * p2[1] + t * t * t * p3[1]))
    return out


def _path(*segs) -> list:
    """Join curves and points into one outline, dropping repeated joints."""
    out: list = []
    for s in segs:
        s = list(s)
        if out and s and abs(out[-1][0] - s[0][0]) < 1e-6 and abs(out[-1][1] - s[0][1]) < 1e-6:
            s = s[1:]
        out.extend(s)
    return out


def _gold(w: int, h: int, top: float, bottom: float):
    """Gold for the eagle: bright at the top, deeper towards the feet, a sheen down the middle."""
    small = Image.new("RGB", (32, 64))
    px = small.load()
    for y in range(64):
        t = min(1.0, max(0.0, (y * h / 63 - top) / max(1.0, bottom - top)))
        base = art._mix(art.GOLD_LIGHT, art.GOLD, min(1.0, t * 1.6)) if t < 0.62 else \
            art._mix(art.GOLD, art.GOLD_DARK, (t - 0.62) / 0.38 * 0.8)
        for x in range(32):
            s = 1 - abs(x - 15.5) / 15.5
            px[x, y] = art._mix(base, art.GOLD_LIGHT, 0.22 * s * s)
    return small.resize((w, h), Image.BICUBIC)


class _Pen:
    """Paints shapes given in design units onto a transparent canvas."""

    def __init__(self, w: int, h: int, scale: float, ox: float, oy: float) -> None:
        self.im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        self.k, self.ox, self.oy = scale, ox, oy
        g = _gold(w, h, oy + BOX[1] * scale, oy + BOX[3] * scale)
        self.tex = {"gold": g, "dark": g.point(lambda v: int(v * 0.8)),
                    "deep": Image.blend(g, Image.new("RGB", (w, h), (84, 42, 10)), 0.62),
                    "light": g.point(lambda v: int(v + (255 - v) * 0.16))}
        self.lw = max(3.6, scale * 6)       # the outline: at least about 1.2 pixels once scaled down
        self.draw = ImageDraw.Draw(self.im)

    def _place(self, pts) -> list:
        return [(self.ox + x * self.k, self.oy + y * self.k) for x, y in pts]

    def _box(self, q):
        x0 = max(0, int(min(p[0] for p in q)) - 2)
        y0 = max(0, int(min(p[1] for p in q)) - 2)
        x1 = min(self.im.width, int(max(p[0] for p in q)) + 3)
        y1 = min(self.im.height, int(max(p[1] for p in q)) + 3)
        return x0, y0, x1, y1

    def shape(self, pts, fill="gold", line: bool = True, lw: float | None = None, fill_alpha: int = 255) -> None:
        q = self._place(pts)
        x0, y0, x1, y1 = self._box(q)
        if x1 <= x0 or y1 <= y0:
            return
        if fill_alpha:
            mask = Image.new("L", (x1 - x0, y1 - y0), 0)
            ImageDraw.Draw(mask).polygon([(x - x0, y - y0) for x, y in q], fill=255)
            if isinstance(fill, str):
                self.im.paste(self.tex[fill].crop((x0, y0, x1, y1)), (x0, y0), mask)
            else:
                self.im.paste(tuple(fill) + (255,), (x0, y0, x1, y1), mask)
        if line:
            self.draw.line(q + [q[0]], fill=art.GOLD_EDGE + (255,),
                           width=max(1, round(lw if lw is not None else self.lw)), joint="curve")

    def pattern(self, pts, strokes) -> None:
        """Lines (points, width as a share of the outline) drawn only inside the shape."""
        q = self._place(pts)
        x0, y0, x1, y1 = self._box(q)
        if x1 <= x0 or y1 <= y0:
            return
        layer = Image.new("L", (x1 - x0, y1 - y0), 0)
        d = ImageDraw.Draw(layer)
        for line, share in strokes:
            d.line([(x - x0, y - y0) for x, y in self._place(line)], fill=255,
                   width=max(1, round(self.lw * share)), joint="curve")
        mask = Image.new("L", (x1 - x0, y1 - y0), 0)
        ImageDraw.Draw(mask).polygon([(x - x0, y - y0) for x, y in q], fill=255)
        colour = art._mix(art.GOLD_DARK, art.GOLD_EDGE, 0.45) + (255,)
        self.im.paste(colour, (x0, y0, x1, y1), ImageChops.multiply(layer, mask))

    def circle(self, cx: float, cy: float, r: float, fill="gold", line: bool = True, lw: float | None = None) -> None:
        self.shape([(cx + r * math.cos(i * math.pi / 20), cy + r * math.sin(i * math.pi / 20)) for i in range(40)],
                   fill, line, lw)

    def stroke(self, pts, width: float | None = None, color=None) -> None:
        colour = tuple(color or art._mix(art.GOLD_DARK, art.GOLD_EDGE, 0.45)) + (255,)
        self.draw.line(self._place(pts), fill=colour, width=max(1, round(width if width is not None else self.lw * 0.6)),
                       joint="curve")


class _Mirror:
    """The pen, drawing the mirror image (for the right half)."""

    def __init__(self, pen: _Pen) -> None:
        self.pen, self.lw = pen, pen.lw

    def shape(self, pts, fill="gold", line: bool = True, lw: float | None = None, fill_alpha: int = 255) -> None:
        self.pen.shape([(DW - x, y) for x, y in pts], fill, line, lw, fill_alpha)

    def pattern(self, pts, strokes) -> None:
        self.pen.pattern([(DW - x, y) for x, y in pts], [([(DW - x, y) for x, y in s], w) for s, w in strokes])

    def circle(self, cx, cy, r, fill="gold", line: bool = True, lw: float | None = None) -> None:
        self.pen.circle(DW - cx, cy, r, fill, line, lw)

    def stroke(self, pts, width=None, color=None) -> None:
        self.pen.stroke([(DW - x, y) for x, y in pts], width, color)


# ---------------------------------------------------------------- the eagle (viewer's left half)
#
# The layout follows the eagle of the Church of Greece flag: wings arched at the
# shoulders with long feathers sweeping down to the lower corners, scaled necks and
# breast, the legs held out to the sides, the crown floating above the heads.

def _blade(base, tip, width: float, n: int = 16) -> list:
    """A long feather tapering to a point (the wing and tail feathers)."""
    bx, by = base
    length = math.hypot(tip[0] - bx, tip[1] - by) or 1.0
    dx, dy = (tip[0] - bx) / length, (tip[1] - by) / length
    px, py = dy, -dx
    left, right = [], []
    for i in range(n):
        u = length * i / n
        hw = width / 2 * (1 - u / length) ** 0.55
        left.append((bx + dx * u - px * hw, by + dy * u - py * hw))
        right.append((bx + dx * u + px * hw, by + dy * u + py * hw))
    return left + [tip] + right[::-1]


def _lance(base, tip, width: float, n: int = 16) -> list:
    """A feather widest a third of the way along and pointed at the tip (tail and thighs)."""
    bx, by = base
    length = math.hypot(tip[0] - bx, tip[1] - by) or 1.0
    dx, dy = (tip[0] - bx) / length, (tip[1] - by) / length
    px, py = dy, -dx
    left, right = [], []
    for i in range(n):
        u = i / n
        hw = width / 2 * (0.55 + 0.45 * math.sin(math.pi * min(1.0, u / 0.66) / 2)) * (1 - u) ** 0.8 / 0.75 ** 0.8 \
            if u > 0.25 else width / 2 * (0.55 + 0.45 * math.sin(math.pi * u / 0.5))
        left.append((bx + dx * u * length - px * hw, by + dy * u * length - py * hw))
        right.append((bx + dx * u * length + px * hw, by + dy * u * length + py * hw))
    return left + [tip] + right[::-1]


def _along(base, tip, u: float, v: float, width: float):
    """A point on a feather: u along it (0..1), v across it (-1 = outer edge .. 1)."""
    length = math.hypot(tip[0] - base[0], tip[1] - base[1]) or 1.0
    dx, dy = (tip[0] - base[0]) / length, (tip[1] - base[1]) / length
    hw = width / 2 * (1 - u) ** 0.55
    return (base[0] + dx * u * length + dy * v * hw, base[1] + dy * u * length - dx * v * hw)


PRIMARIES = [                           # (base, tip, width), from the body outward
    ((334, 300), (324, 422), 40),
    ((308, 288), (290, 450), 46),
    ((281, 274), (254, 470), 48),
    ((253, 263), (216, 484), 48),
    ((225, 257), (178, 498), 48),
    ((198, 259), (140, 512), 48),
    ((172, 271), (100, 528), 48),
    ((148, 289), (62, 548), 48),
    ((126, 314), (20, 570), 46),
]

TAIL = [(-118, 664), (-92, 683), (-66, 696), (-40, 704), (-14, 710)]    # tips, as offsets from the middle

THIGH = [((356, 520), (270, 498), 34), ((356, 530), (278, 568), 36), ((362, 540), (304, 602), 36),
         ((372, 550), (338, 610), 32)]


def _wing(p) -> None:
    # the long feathers, each with its shadowed outer edge and notches, as on the flag
    for base, tip, width in PRIMARIES:
        p.shape(_blade(base, tip, width), "gold")
        shade = [_along(base, tip, i / 12, -1, width) for i in range(12)] + [tip] + \
                [_along(base, tip, i / 12, -0.1, width) for i in range(11, -1, -1)]
        p.shape(shade, "deep", line=False)
        for u in (0.36, 0.56, 0.76):
            p.shape([_along(base, tip, u, -1.05, width), _along(base, tip, u + 0.07, -1.0, width),
                     _along(base, tip, u + 0.01, 0.05, width)], art.GOLD_EDGE, line=False)
        p.shape(_blade(base, tip, width), "gold", fill_alpha=0)
    # the arch of small feathers over the shoulder, ending in points along its lower edge
    outer = _path(_bez((354, 302), (322, 276), (272, 232), (226, 224)),
                  _bez((226, 224), (194, 220), (162, 244), (138, 280)),
                  _bez((138, 280), (122, 304), (110, 326), (102, 346)))
    points = [(102, 346), (118, 330), (122, 318), (138, 306), (144, 292), (164, 282), (170, 270), (192, 266),
              (198, 258), (222, 260), (226, 254), (252, 266), (256, 260), (280, 278), (286, 272), (308, 292),
              (316, 288), (336, 306), (346, 302)]
    p.shape(outer + points[1:], "light")
    for a, b in ((226, 232), (178, 240), (290, 254)):
        p.stroke(_bez((a, b), (a - 14, b + 6), (a - 26, b + 16), (a - 34, b + 28), n=8), width=p.lw * 0.45)


def _tail(p) -> None:
    order = [(o, y) for pair in zip(TAIL, [(-o, y) for o, y in TAIL]) for o, y in pair]
    for (dx, y), shade in zip(order, ["dark", "dark", "gold", "gold"] * 3):
        base = (420 + dx * 0.25, 575)
        tip = (420 + dx, y)
        p.shape(_lance(base, tip, 40), shade)
        p.stroke([base, _along(base, tip, 0.8, 0, 40)], width=p.lw * 0.4)


def _leg(p) -> None:
    """The leg held out sideways: a ringed shank and, at the body, a skirt of pointed feathers."""
    p.shape([(304, 528), (224, 538), (224, 558), (304, 548)], "gold")
    for x in range(232, 300, 9):
        y = 538 + (x - 224) * -0.125
        p.stroke([(x, y + 1), (x, y + 19)], width=p.lw * 0.5, color=art.GOLD_EDGE)
    for base, tip, width in THIGH:
        p.shape(_lance(base, tip, width), "gold")


def _sword(p) -> None:
    """In the eagle's right claw (the viewer's left): the blade raised across the wing."""
    guard = (190, 522)
    tip = (84, 294)
    length = math.hypot(tip[0] - guard[0], tip[1] - guard[1])
    d = ((tip[0] - guard[0]) / length, (tip[1] - guard[1]) / length)
    n = (-d[1], d[0])

    def off(pt, u, v):
        return (pt[0] + d[0] * u + n[0] * v, pt[1] + d[1] * u + n[1] * v)
    bw = 7
    p.shape([off(guard, 0, bw), off(tip, -40, bw * 0.8), tip, off(tip, -40, -bw * 0.8), off(guard, 0, -bw)],
            STEEL, lw=p.lw * 0.75)
    p.shape([off(guard, 4, -bw * 0.15), off(tip, -40, -bw * 0.2), tip, off(tip, -40, -bw * 0.8),
             off(guard, 4, -bw * 0.95)], STEEL_LINE, line=False)
    # the curved crossguard with its knobbed ends
    p.shape(_path(_bez((158, 546), (172, 528), (196, 520), (222, 502)),
                  _bez((222, 502), (224, 512), (204, 528), (164, 552))), "gold", lw=p.lw * 0.8)
    p.circle(155, 545, 7, "gold", lw=p.lw * 0.7)
    p.circle(220, 503, 7, "gold", lw=p.lw * 0.7)
    grip_end = off(guard, -66, 0)
    p.shape([off(guard, -6, 6), off(grip_end, 0, 6), off(grip_end, 0, -6), off(guard, -6, -6)], GRIP,
            lw=p.lw * 0.6)
    ring = off(guard, -74, 0)
    p.circle(ring[0], ring[1], 10, "gold", lw=p.lw * 0.7)
    p.circle(ring[0], ring[1], 4, art.GOLD_EDGE, line=False)
    # the claw closed round the grip, toe over toe
    for i, y in enumerate((538, 549, 560, 571)):
        x0 = 174 + i * 2
        p.shape(_path(_bez((226, y - 3), (210, y - 5), (186, y - 5), (x0, y)),
                      _bez((x0, y), (x0 - 4, y + 6), (x0 + 2, y + 11), (x0 + 10, y + 10)),
                      _bez((x0 + 10, y + 10), (192, y + 9), (212, y + 9), (226, y + 8))), "gold", lw=p.lw * 0.65)


def _orb(p) -> None:
    """The orb with its cross in the eagle's left claw (the viewer's right)."""
    cx, cy, r = 651, 560, 45
    p.circle(cx, cy, r, "gold")
    band = _path(_bez((cx - r + 2, cy - 18), (cx - 20, cy - 26), (cx + 20, cy - 22), (cx + r - 2, cy - 8)),
                 _bez((cx + r - 2, cy - 8), (cx + r - 4, cy + 2), (cx + r - 6, cy + 4), (cx + r - 8, cy + 4)),
                 _bez((cx + r - 8, cy + 4), (cx + 20, cy - 8), (cx - 20, cy - 12), (cx - r + 4, cy - 4)))
    p.shape(band, "deep", lw=p.lw * 0.6)
    p.shape([(cx + 7, cy - r + 2), (cx + 17, cy - r + 2), (cx + 15, cy - 22), (cx + 6, cy - 24)], "deep",
            lw=p.lw * 0.6)
    p.shape([(cx + 9, cy - r - 24), (cx + 16, cy - r - 24), (cx + 16, cy - r + 4), (cx + 9, cy - r + 4)], "gold",
            lw=p.lw * 0.6)
    p.shape([(cx + 2, cy - r - 17), (cx + 23, cy - r - 17), (cx + 23, cy - r - 10), (cx + 2, cy - r - 10)], "gold",
            lw=p.lw * 0.6)
    p.circle(cx - r * 0.42, cy + r * 0.3, r * 0.12, (255, 246, 214), line=False)
    # the claw: toes curled round the underside of the orb
    for y0, y1, x1 in ((548, 572, 676), (556, 590, 660), (562, 604, 634)):
        p.shape(_path(_bez((606, y0 - 6), (624, y0 + 6), (640, y1 - 4), (x1, y1)),
                      [(x1 + 4, y1 + 6)],
                      _bez((x1 + 4, y1 + 6), (636, y1 + 6), (618, y0 + 14), (604, y0 + 6))), "gold", lw=p.lw * 0.6)


def _body(p) -> None:
    """The necks and the body in one piece, covered in scale feathers."""
    half = _path([(420, 254)],
                 _bez((420, 254), (406, 226), (388, 206), (360, 190)),
                 [(330, 206)],
                 _bez((330, 206), (342, 236), (350, 266), (352, 300)),
                 _bez((352, 300), (340, 352), (338, 420), (344, 478)),
                 _bez((344, 478), (350, 524), (366, 566), (390, 604)),
                 [(420, 614)])
    whole = half + [(DW - x, y) for x, y in half[::-1]][1:-1]
    p.shape(whole, "gold")
    scales = []
    y, row = 186, 0
    while y < 620:
        size = 22 if y < 290 else 32                # small scales up the necks, larger on the breast
        shift = size / 2 if row % 2 else 0
        for i in range(-10, 11):
            x = 420 + i * size + shift
            s = size / 2
            scales.append(([(x - s, y), (x - s * 0.85, y + s * 0.7), (x - s * 0.45, y + s * 1.25), (x, y + s * 1.55),
                            (x + s * 0.45, y + s * 1.25), (x + s * 0.85, y + s * 0.7), (x + s, y)], 0.5))
        y += size * 0.72
        row += 1
    p.pattern(whole, scales)


def _head(p) -> None:
    """Turned outward: a hooked beak, a hard brow and a crest of pointed feathers."""
    outline = _path(_bez((318, 222), (312, 214), (306, 210), (300, 208)),          # the throat
                    _bez((300, 208), (284, 202), (262, 200), (248, 203)),          # the line of the mouth
                    _bez((248, 203), (240, 206), (238, 214), (242, 220)),          # into the hook
                    _bez((242, 220), (230, 220), (222, 208), (224, 194)),
                    _bez((224, 194), (226, 178), (236, 166), (248, 162)),
                    _bez((248, 162), (272, 154), (300, 149), (324, 145)),          # the top of the head
                    [(312, 160), (354, 163), (338, 174), (366, 182), (350, 192)])  # the crest
    p.shape(outline + [(332, 200), (306, 210)], "gold", line=False)
    p.stroke(outline, width=p.lw, color=art.GOLD_EDGE)
    p.stroke(_bez((248, 164), (244, 178), (244, 192), (248, 203)), width=p.lw * 0.6)    # where the beak begins
    p.shape([(245, 177), (258, 168), (278, 162), (268, 174), (257, 183), (248, 184)], art.GOLD_EDGE, line=False)


def _crown(p) -> None:
    """The closed imperial crown floating above the heads: dark lobes, arches set with
    pearls, a great pearl at the front, and the cross on top."""
    half = _path([(421, 160)], [(396, 160)],
                 _bez((396, 160), (366, 140), (350, 112), (353, 90)),
                 _bez((353, 90), (356, 72), (372, 64), (388, 66)),
                 _bez((388, 66), (398, 60), (410, 58), (421, 58)))
    p.shape(half + [(DW - x, y) for x, y in half[::-1]][1:-1], "deep")
    for side in (1, -1):
        def X(x):
            return x if side == 1 else DW - x
        arch = _path(_bez((X(369), 72), (X(380), 96), (X(390), 122), (X(394), 146)),
                     [(X(408), 146)],
                     _bez((X(408), 146), (X(404), 120), (X(394), 92), (X(385), 68)))
        p.shape(arch, "light", lw=p.lw * 0.55)
        for t in (0.1, 0.27, 0.44, 0.61, 0.78):
            x = 377 + (401 - 377) * t ** 0.85
            y = 72 + (144 - 72) * t
            p.circle(X(x), y, 4.2, art.GOLD_EDGE, line=False)
    p.shape([(413, 74), (429, 74), (428, 120), (414, 120)], "light", lw=p.lw * 0.55)
    p.shape([(397, 138), (445, 138), (445, 149), (397, 149)], "light", lw=p.lw * 0.55)
    p.circle(421, 132, 11, PEARL, lw=p.lw * 0.6)
    p.shape([(421 + 26 * math.cos(a * math.pi / 12), 155 + 6 * math.sin(a * math.pi / 12)) for a in range(24)],
            "deep", lw=p.lw * 0.6)
    p.circle(421, 66, 9, "gold", lw=p.lw * 0.6)
    p.shape([(417, 58), (425, 58), (425, 30), (417, 30)], "gold", lw=p.lw * 0.6)
    p.shape([(406, 40), (436, 40), (436, 47), (406, 47)], "gold", lw=p.lw * 0.6)


@lru_cache(maxsize=6)
def _eagle(w: int, h: int):
    """The eagle alone, w x h pixels with a transparent ground: (RGBA picture, centre of the light)."""
    k = art._ss(w, h)
    W, H = w * k, h * k
    bw, bh = BOX[2] - BOX[0], BOX[3] - BOX[1]
    scale = min(W * (1 - 2 * MARGIN) / bw, H * (1 - 2 * MARGIN) / bh)
    ox, oy = (W - bw * scale) / 2 - BOX[0] * scale, (H - bh * scale) / 2 - BOX[1] * scale
    pen = _Pen(W, H, scale, ox, oy)
    both = (pen, _Mirror(pen))
    for side in both:
        _wing(side)
    _tail(pen)
    for side in both:
        _leg(side)
    _body(pen)
    for side in both:
        _head(side)
    _sword(pen)
    _orb(pen)
    _crown(pen)
    im = pen.im.resize((w, h), Image.LANCZOS) if k > 1 else pen.im
    return im, ((ox + 420 * scale) / k, (oy + 390 * scale) / k)


@lru_cache(maxsize=6)
def _masks(w: int, h: int):
    """What every step of light shares: the eagle, a fade towards the edges (so the light
    never shows the picture's border), the rays, and the rim round the eagle."""
    eagle, (cx, cy) = _eagle(w, h)
    edge = max(2, int(min(w, h) * 0.1))
    fade = Image.new("L", (w, h), 0)
    ImageDraw.Draw(fade).rounded_rectangle([edge, edge, w - 1 - edge, h - 1 - edge], radius=edge * 2, fill=255)
    fade = fade.filter(ImageFilter.GaussianBlur(radius=edge * 0.55))
    rays = Image.new("L", (w, h), 0)
    rd = ImageDraw.Draw(rays)
    reach = max(w, h)
    for i in range(28):                     # an aureole, as round a saint in glory
        a = 2 * math.pi * i / 28 + math.pi / 28
        half = 0.018 if i % 2 else 0.03
        rd.polygon([(cx, cy), (cx + reach * math.cos(a - half), cy + reach * math.sin(a - half)),
                    (cx + reach * math.cos(a + half), cy + reach * math.sin(a + half))], fill=255)
    rays = rays.filter(ImageFilter.GaussianBlur(radius=max(0.6, h * 0.012)))
    alpha = eagle.split()[3]
    rim = alpha.filter(ImageFilter.MaxFilter(2 * max(1, int(h * 0.012)) + 1))
    rim = rim.filter(ImageFilter.GaussianBlur(radius=max(1.0, h * 0.028)))
    return eagle, alpha, (cx, cy), fade, rays, rim


def _light(colour, share: float) -> tuple[int, int, int]:
    return tuple(min(255, int(c + (255 - c) * share)) for c in colour)     # type: ignore[return-value]


@lru_cache(maxsize=48)
def frame(w: int, h: int, bg, glow, level: int = 0, levels: int = LEVELS):
    """The eagle on bg with the light behind it at step `level` of `levels` (0 = at rest)."""
    bg = art._rgb(bg)
    glow = art._rgb(glow) if glow is not None else art.GOLD
    t = max(0.0, min(1.0, level / max(1, levels - 1)))
    eagle, alpha, (cx, cy), fade, rays, rim = _masks(w, h)
    canvas = Image.new("RGB", (w, h), bg)
    halo = Image.new("L", (w, h), 0)
    grow = 0.82 + 0.3 * t
    rx, ry = w * 0.5 * grow, h * 0.5 * grow
    ImageDraw.Draw(halo).ellipse([cx - rx, cy - ry, cx + rx, cy + ry], fill=int(64 + 136 * t))
    halo = ImageChops.multiply(halo.filter(ImageFilter.GaussianBlur(radius=h * 0.13)), fade)
    canvas.paste(glow, (0, 0), halo)
    if t > 0:
        reach = Image.new("L", (w, h), 0)
        ImageDraw.Draw(reach).ellipse([cx - rx * 1.05, cy - ry * 1.05, cx + rx * 1.05, cy + ry * 1.05], fill=255)
        reach = ImageChops.multiply(reach.filter(ImageFilter.GaussianBlur(radius=h * 0.12)), fade)
        glory = ImageChops.multiply(rays.point(lambda v: int(v * 0.43 * t)), reach)
        canvas.paste(_light(glow, 0.5), (0, 0), glory)
    canvas.paste(_light(glow, 0.45), (0, 0), rim.point(lambda v: int(v * (0.12 + 0.8 * t))))
    if t > 0:
        lit = eagle.convert("RGB").point(lambda v: int(v + (255 - v) * 0.1 * t))
        canvas.paste(lit, (0, 0), alpha)
    else:
        canvas.paste(eagle, (0, 0), alpha)
    return canvas


def frames(w: int, h: int, bg, glow, levels: int = LEVELS) -> list:
    """Every step of light, from rest to the height of a pulse."""
    return [frame(w, h, bg, glow, i, levels) for i in range(levels)]


def available() -> bool:
    return Image is not None


__all__ = ["LEVELS", "available", "frame", "frames"]
