"""The double-headed eagle at the head of the tab column, for terminals that
show true images (Kitty, Ghostty, Sixel terminals).

It is drawn after the eagle of the Church of Greece (the Byzantine eagle of the
Ecumenical Patriarchate and Mount Athos): the closed imperial crown floats above
and between the heads; the two heads are turned outward, with hooked beaks, a
stern eye and a crest swept back from the nape, on necks covered in small scale
feathers; the breast is scaled; the wings are raised from the shoulders, a band
of covert feathers along their leading edge and long flight feathers sweeping
down to the lower corners; the legs are held out to the sides from skirts of
pointed thigh feathers, ringed, with the sword in the eagle's right claw (the
viewer's left) and the orb with its cross in the left; the tail spreads in a fan
below. It is gilded, like the eagles carved on church thrones, lecterns and
iconostases: every feather and scale is raised and catches the light from the
upper left.

The light (`frame`, `frames`) comes from behind the eagle, as from a lamp hung
behind a carving: a soft bloom round the silhouette and shafts of light breaking
out between the wings, the heads and the crown. It is painted in steps, from the
quiet glow at rest to the height of a pulse, so the tab column can make it swell
and fade by switching between pictures the terminal already holds.

The design is laid out on a 1000 x 880 grid; the viewer's left half is drawn and
mirrored (the sword and the orb are drawn once). Everything is painted at a few
times the size and scaled down."""

from __future__ import annotations

import math
from functools import lru_cache

from . import art

try:
    from PIL import Image, ImageChops, ImageDraw, ImageFilter
except Exception:                       # pragma: no cover - Pillow comes with textual-image
    Image = None

DW, DH = 1000, 880                      # the design grid
BOX = (8, 14, 992, 864)                 # what the eagle covers of it
CENTRE = (500, 430)                     # where the light behind it is strongest (the breast)
LEVELS = 16                             # steps of light, from rest (0) to the height of a pulse
MARGIN = 0.04

GOLD_LIGHT = (255, 228, 136)            # the eagle's gilding, a little richer than the frames'
GOLD = (232, 174, 52)
GOLD_DEEP = (156, 100, 14)
INK = (52, 32, 6)                       # the outlines
SHADE = (82, 50, 8)                     # the shadowed side of a feather
ENAMEL = (34, 22, 18)                   # the dark lobes of the crown, the bands of the orb
PEARL = (250, 241, 218)
STEEL = (196, 204, 216)
STEEL_DARK = (92, 100, 116)
GRIP = (104, 30, 22)
RELIEF = [0, 1, 2, -1, 0, 1, -2, -1, 0]    # lights the upper-left side of every raised shape


# ---------------------------------------------------------------- geometry

def _bez(p0, p1, p2, p3, n: int = 14) -> list:
    """Points along a cubic Bézier curve."""
    out = []
    for i in range(n + 1):
        t = i / n
        u = 1 - t
        a, b, c, d = u * u * u, 3 * u * u * t, 3 * u * t * t, t * t * t
        out.append((a * p0[0] + b * p1[0] + c * p2[0] + d * p3[0], a * p0[1] + b * p1[1] + c * p2[1] + d * p3[1]))
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


def _mirror(pts) -> list:
    return [(DW - x, y) for x, y in pts]


def _lerp(a, b, t: float):
    return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)


def _unit(dx: float, dy: float):
    n = math.hypot(dx, dy) or 1.0
    return dx / n, dy / n


class _Quill:
    """A feather (or a toe) from base to tip, its spine bowed sideways by `bend` (a
    share of its length, positive to the feather's left as seen on screen).
    blade: full width most of the way, then drawn out to a point; lance: widest a
    third of the way along and pointed at both ends; toe: even, rounded at the end."""

    def __init__(self, base, tip, width: float, bend: float = 0.0, kind: str = "blade", n: int = 20) -> None:
        self.n = n
        length = math.hypot(tip[0] - base[0], tip[1] - base[1]) or 1.0
        dx, dy = (tip[0] - base[0]) / length, (tip[1] - base[1]) / length

        def spine(t):
            b = bend * length * 4 * t * (1 - t)
            return (base[0] + (tip[0] - base[0]) * t + dy * b, base[1] + (tip[1] - base[1]) * t - dx * b)

        self.mid, self.left, self.right = [], [], []
        for i in range(n + 1):
            t = i / n
            if kind == "lance":
                hw = (t / 0.35) ** 0.6 if t < 0.35 else ((1 - t) / 0.65) ** 0.85
            elif kind == "toe":
                hw = 1.0 if t < 0.8 else math.sqrt(max(0.0, 1 - ((t - 0.8) / 0.2) ** 2))
            else:
                hw = (min(1.0, (t / 0.06) ** 0.5)) * (1.0 if t < 0.55 else ((1 - t) / 0.45) ** 0.85)
            hw *= width / 2
            p, q, r = spine(t), spine(min(1.0, t + 0.01)), spine(max(0.0, t - 0.01))
            ux, uy = _unit(q[0] - r[0], q[1] - r[1])
            self.mid.append(p)
            self.left.append((p[0] + uy * hw, p[1] - ux * hw))
            self.right.append((p[0] - uy * hw, p[1] + ux * hw))

    @property
    def outline(self) -> list:
        return self.left + self.right[::-1][1:]

    def at(self, t: float, v: float):
        """A point t along the feather (0 base .. 1 tip), v across it (1 left edge .. -1 right edge)."""
        f = max(0.0, min(1.0, t)) * self.n
        i = min(self.n - 1, int(f))
        u = f - i

        def side(pts):
            return _lerp(pts[i], pts[i + 1], u)
        m, edge = side(self.mid), side(self.left if v >= 0 else self.right)
        return _lerp(m, edge, abs(v))

    def barbs(self, side: float = 1.0, t0: float = 0.14, t1: float = 0.97, teeth: int = 5,
              deep: float = 0.0, shallow: float = 0.55) -> list:
        """The shadowed side of the feather, its inner edge cut in teeth pointing to the tip."""
        edge = [self.at(t0 + (t1 - t0) * i / 18, side) for i in range(19)]
        inner = []
        for j in range(teeth):
            a = t0 + (t1 - t0) * j / teeth
            b = t0 + (t1 - t0) * (j + 1) / teeth
            inner.append(self.at(a, side * shallow))
            inner.append(self.at(b - (t1 - t0) * 0.02, side * deep))
        inner.append(self.at(t1, side * shallow))
        return edge + inner[::-1]


def _scale(cx: float, cy: float, w: float, h: float, ang: float = 0.0, pointed: bool = False):
    """A scale feather hanging from (cx, cy), the middle of its top edge, turned ang radians
    from straight down: (outline, the visible lower edge)."""
    if pointed:
        edge = _path(_bez((-w / 2, 0), (-w / 2, h * 0.45), (-w * 0.16, h * 0.82), (0, h), 6),
                     _bez((0, h), (w * 0.16, h * 0.82), (w / 2, h * 0.45), (w / 2, 0), 6))
    else:
        edge = _path(_bez((-w / 2, 0), (-w / 2, h * 0.62), (-w * 0.3, h), (0, h), 6),
                     _bez((0, h), (w * 0.3, h), (w / 2, h * 0.62), (w / 2, 0), 6))
    ca, sa = math.cos(ang), math.sin(ang)
    pts = [(cx + x * ca - y * sa, cy + x * sa + y * ca) for x, y in edge]
    return pts, pts


def _gold(w: int, h: int, top: float, bottom: float):
    """Gold for the eagle: bright at the top, deeper towards the feet, a sheen down the middle."""
    small = Image.new("RGB", (32, 64))
    px = small.load()
    for y in range(64):
        t = min(1.0, max(0.0, (y * h / 63 - top) / max(1.0, bottom - top)))
        base = art._mix(GOLD_LIGHT, GOLD, min(1.0, t * 1.9)) if t < 0.6 else \
            art._mix(GOLD, GOLD_DEEP, (t - 0.6) / 0.4 * 0.75)
        for x in range(32):
            s = 1 - abs(x - 15.5) / 15.5
            px[x, y] = art._mix(base, GOLD_LIGHT, 0.18 * s * s)
    return small.resize((w, h), Image.BICUBIC)


# ---------------------------------------------------------------- the pen

class _Pen:
    """Paints shapes given in design units: their colours on one layer and, on another,
    the height of the relief — every shape a raised plate, every outline a groove."""

    def __init__(self, w: int, h: int, scale: float, ox: float, oy: float, lw: float) -> None:
        self.size = (w, h)
        self.k, self.ox, self.oy, self.lw = scale, ox, oy, lw
        self.col = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        self.hgt = Image.new("L", (w, h), 0)
        g = _gold(w, h, oy + BOX[1] * scale, oy + BOX[3] * scale)
        self.tex = {"gold": g, "light": g.point(lambda v: int(v + (255 - v) * 0.14)),
                    "dark": g.point(lambda v: int(v * 0.84))}
        self._saved: list = []

    def place(self, pts) -> list:
        return [(self.ox + x * self.k, self.oy + y * self.k) for x, y in pts]

    def fill(self, pts, fill="gold", z: int = 200) -> None:
        q = self.place(pts)
        x0 = max(0, int(min(p[0] for p in q)) - 2)
        y0 = max(0, int(min(p[1] for p in q)) - 2)
        x1 = min(self.size[0], int(max(p[0] for p in q)) + 3)
        y1 = min(self.size[1], int(max(p[1] for p in q)) + 3)
        if x1 <= x0 or y1 <= y0:
            return
        mask = Image.new("L", (x1 - x0, y1 - y0), 0)
        ImageDraw.Draw(mask).polygon([(x - x0, y - y0) for x, y in q], fill=255)
        if isinstance(fill, str):
            self.col.paste(self.tex[fill].crop((x0, y0, x1, y1)), (x0, y0), mask)
        else:
            self.col.paste(tuple(fill) + (255,), (x0, y0, x1, y1), mask)
        self.hgt.paste(z, (x0, y0, x1, y1), mask)

    def line(self, pts, width: float | None = None, color=INK, z: int | None = 40, closed: bool = False) -> None:
        q = self.place(pts)
        if closed:
            q = q + [q[0]]
        wd = max(1, round(self.lw if width is None else width))
        ImageDraw.Draw(self.col).line(q, fill=tuple(color) + (255,), width=wd, joint="curve")
        if z is not None:
            ImageDraw.Draw(self.hgt).line(q, fill=z, width=wd, joint="curve")

    def shape(self, pts, fill="gold", z: int = 200, line: bool = True, width: float | None = None) -> None:
        self.fill(pts, fill, z)
        if line:
            self.line(pts, width, closed=True)

    def dot(self, cx: float, cy: float, r: float, fill="gold", z: int = 220, line: bool = True,
            width: float | None = None) -> None:
        n = 28
        self.shape([(cx + r * math.cos(2 * math.pi * i / n), cy + r * math.sin(2 * math.pi * i / n))
                    for i in range(n)], fill, z, line, width)

    def clip(self) -> None:
        """What is drawn from here to unclip() shows only inside the shape given there."""
        self._saved.append((self.col, self.hgt))
        self.col = Image.new("RGBA", self.size, (0, 0, 0, 0))
        self.hgt = Image.new("L", self.size, 0)

    def unclip(self, pts) -> None:
        col, hgt = self.col, self.hgt
        self.col, self.hgt = self._saved.pop()
        mask = Image.new("L", self.size, 0)
        ImageDraw.Draw(mask).polygon(self.place(pts), fill=255)
        cover = ImageChops.multiply(col.split()[3], mask)
        self.col.paste(col, (0, 0), cover)
        self.hgt.paste(hgt, (0, 0), cover)

    def finish(self, w: int, h: int):
        """Light the relief from the upper left and scale the picture down to w x h."""
        blur = max(1.0, self.lw * 0.85)
        relief = self.hgt.filter(ImageFilter.GaussianBlur(blur))
        shade = relief.filter(ImageFilter.Kernel((3, 3), RELIEF, scale=max(1.0, 6.5 / blur), offset=128))
        rgb = self.col.convert("RGB")
        lit = ImageChops.hard_light(rgb, Image.merge("RGB", (shade, shade, shade)))
        glint = shade.point(lambda v: 0 if v < 168 else min(130, (v - 168) * 3))
        lit.paste((255, 240, 196), (0, 0), glint)
        out = lit.convert("RGBA")
        out.putalpha(self.col.split()[3])
        return out.resize((w, h), Image.LANCZOS) if out.size != (w, h) else out


class _Mirror:
    """The pen, drawing the mirror image (for the right half)."""

    def __init__(self, pen: _Pen) -> None:
        self.pen, self.lw = pen, pen.lw

    def fill(self, pts, *a, **kw) -> None:
        self.pen.fill(_mirror(pts), *a, **kw)

    def line(self, pts, *a, **kw) -> None:
        self.pen.line(_mirror(pts), *a, **kw)

    def shape(self, pts, *a, **kw) -> None:
        self.pen.shape(_mirror(pts), *a, **kw)

    def dot(self, cx, cy, r, *a, **kw) -> None:
        self.pen.dot(DW - cx, cy, r, *a, **kw)

    def clip(self) -> None:
        self.pen.clip()

    def unclip(self, pts) -> None:
        self.pen.unclip(_mirror(pts))


class _Grow:
    """The pen, drawing everything f times larger about an anchor point."""

    def __init__(self, pen, anchor, f: float) -> None:
        self.pen, self.anchor, self.f, self.lw = pen, anchor, f, pen.lw

    def _t(self, pts) -> list:
        ax, ay = self.anchor
        return [(ax + (x - ax) * self.f, ay + (y - ay) * self.f) for x, y in pts]

    def fill(self, pts, *a, **kw) -> None:
        self.pen.fill(self._t(pts), *a, **kw)

    def line(self, pts, *a, **kw) -> None:
        self.pen.line(self._t(pts), *a, **kw)

    def shape(self, pts, *a, **kw) -> None:
        self.pen.shape(self._t(pts), *a, **kw)

    def dot(self, cx, cy, r, *a, **kw) -> None:
        (x, y), = self._t([(cx, cy)])
        self.pen.dot(x, y, r * self.f, *a, **kw)


# ---------------------------------------------------------------- the eagle (viewer's left half)
#
# The layout follows the eagle on the flag of the Church of Greece: the wings raised
# from the shoulders, their tips reaching the lower corners; the heads above the
# wrists; the legs held out level from skirts of thigh feathers; the tail below.

# the long flight feathers: where their tips end, from the one nearest the body to the outermost
FLIGHT_TIPS = [(374, 530), (342, 538), (309, 546), (277, 554), (245, 563), (213, 574), (180, 588),
               (146, 605), (110, 626), (70, 652), (18, 686)]
# the curve they spring from, under the coverts (from the shoulder to the wrist)
FLIGHT_ROOTS = ((452, 420), (396, 366), (306, 318), (214, 304))
# the leading edge of the wing, from the shoulder over the wrist and down the outer edge
LEADING = ((460, 392), (410, 330), (330, 262), (252, 262), (206, 260), (168, 296), (150, 354))
# the lower edge of the band along the leading edge, from its outer end back to the shoulder
UNDER = ((150, 354), (168, 328), (198, 320), (234, 324), (298, 330), (364, 366), (436, 442))


def _wing(p) -> None:
    n = len(FLIGHT_TIPS)
    roots = _bez(*FLIGHT_ROOTS, n=n - 1)
    quills = [_Quill(base, tip, 62 - 8 * i / (n - 1), bend=-0.03)
              for i, (base, tip) in enumerate(zip(roots, FLIGHT_TIPS))]
    edge = _path(_bez(*LEADING[:4]), _bez(*LEADING[3:]))
    # the shadow between the feathers: the whole wing, short of the jagged tips
    p.fill(edge + [quills[-1].at(0.84, -1)] + [q.at(0.8, 0) for q in quills[::-1]] + [(414, 500), (448, 440)],
           SHADE, z=110)
    for i, q in enumerate(quills):
        p.fill(q.outline, "gold", z=165)
        p.fill(q.barbs(1.0, teeth=4 + i // 3), SHADE, z=125)
        p.line(q.mid[2:int(q.n * 0.82)], width=p.lw * 0.5, color=GOLD_DEEP, z=None)
        p.line(q.outline, closed=True)
    # the greater coverts: a row of broad feathers over the roots of the flight feathers
    inner = _path(_bez(*UNDER[:4]), _bez(*UNDER[3:]))
    m = 10
    for i in reversed(range(m)):
        u = i / (m - 1)                                  # 0 at the outer end .. 1 at the shoulder
        c = inner[round(u * (len(inner) - 1))]
        tip = FLIGHT_TIPS[round((1 - u) * (n - 1))]
        dx, dy = _unit(tip[0] - c[0], tip[1] - c[1])
        q = _Quill((c[0] - dx * 34, c[1] - dy * 34), (c[0] + dx * 72, c[1] + dy * 72), 52, kind="lance")
        p.fill(q.outline, "gold", z=185)
        p.fill(q.barbs(1.0, t0=0.4, t1=0.95, teeth=2, shallow=0.5, deep=0.05), SHADE, z=150)
        p.line(q.outline, closed=True)
    # the band of small coverts along the leading edge
    band = edge + inner
    p.fill(band, "gold", z=205)
    p.clip()
    back = inner[::-1]
    for share in (0.7, 0.3):
        for j in range(16):
            u = (j + (0.5 if share > 0.5 else 0.0)) / 16
            a = edge[min(len(edge) - 1, round(u * (len(edge) - 1)))]
            b = back[min(len(back) - 1, round(u * (len(back) - 1)))]
            c = _lerp(a, b, share)
            t = FLIGHT_TIPS[min(n - 1, round(u * (n - 1)))]
            pts, rim = _scale(c[0], c[1], 26, 31, math.atan2(-(t[0] - c[0]), t[1] - c[1]), pointed=True)
            p.fill(pts, "gold", z=212)
            p.line(rim, width=p.lw * 0.6, z=100)
    p.unclip(band)
    p.line(band, closed=True)


TAIL_TIPS = [(352, 790), (648, 790), (378, 822), (622, 822), (410, 844), (590, 844), (446, 856),
             (554, 856), (500, 862)]


def _tail(p) -> None:
    for tip in TAIL_TIPS:
        base = (500 + (tip[0] - 500) * 0.28, 688)
        bend = 0.035 if tip[0] < 500 else -0.035 if tip[0] > 500 else 0.0
        q = _Quill(base, tip, 52, kind="lance", bend=bend)
        p.fill(q.outline, "gold", z=175)
        p.fill(q.barbs(1.0 if tip[0] <= 500 else -1.0, t0=0.45, t1=0.96, teeth=2, shallow=0.45, deep=0.05),
               SHADE, z=140)
        p.line(q.mid[int(q.n * 0.35):int(q.n * 0.85)], width=p.lw * 0.55, z=90)
        p.line(q.outline, closed=True)


def _body_outline() -> list:
    half = _path([(500, 288)],
                 _bez((500, 288), (484, 272), (470, 254), (462, 238)),
                 _bez((462, 238), (452, 216), (428, 196), (400, 192)),
                 _bez((400, 192), (370, 192), (346, 214), (348, 242)),
                 _bez((348, 242), (366, 276), (390, 312), (408, 348)),
                 _bez((408, 348), (390, 400), (376, 470), (380, 540)),
                 _bez((380, 540), (386, 612), (416, 676), (452, 712)),
                 _bez((452, 712), (468, 726), (486, 732), (500, 734)))
    return half + _mirror(half[::-1])[1:-1]


def _body(p) -> None:
    """The necks and the body in one piece, covered in scale feathers: small up the
    necks and turned along them, larger on the breast, long and pointed below."""
    outline = _body_outline()
    p.fill(outline, "gold", z=190)
    p.clip()
    scales = []
    y, row = 196.0, 0
    while y < 740:
        size = 26 if y < 300 else min(46, 26 + (y - 300) * 0.08)
        pointed = y > 600
        step = size * 0.9
        shift = step / 2 if row % 2 else 0.0
        x = 500 - shift - step * math.ceil(170 / step)
        while x <= 670:
            k = max(0.0, min(1.0, (370 - y) / 80)) * max(0.0, min(1.0, abs(x - 500) / 30))
            scales.append((y, x, size, size * (1.5 if pointed else 1.05), -0.5 * k if x < 500 else 0.5 * k, pointed))
            x += step
        y += size * (0.62 if pointed else 0.55)
        row += 1
    for y, x, size, h, ang, pointed in sorted(scales, reverse=True):
        pts, rim = _scale(x, y, size, h, ang, pointed)
        p.fill(pts, "gold", z=212)
        p.line(rim, width=p.lw * 0.72, z=70)
    p.unclip(outline)
    p.line(outline, closed=True)


# the skirt of thigh feathers, each from where it springs to its tip, from the lowest
# (hanging down) to the highest (swept out over the leg)
THIGH = [((452, 690), (424, 742)), ((446, 680), (390, 742)), ((440, 668), (354, 732)),
         ((436, 656), (322, 714)), ((434, 644), (300, 688)), ((434, 632), (292, 656)),
         ((436, 620), (300, 626)), ((440, 608), (322, 598))]


def _thigh(p) -> None:
    for base, tip in THIGH:
        q = _Quill(base, tip, 46, kind="lance", bend=0.05)
        p.fill(q.outline, "gold", z=215)
        p.fill(q.barbs(1.0, t0=0.45, t1=0.96, teeth=2, shallow=0.45, deep=0.0), SHADE, z=170)
        p.line(q.mid[int(q.n * 0.35):int(q.n * 0.82)], width=p.lw * 0.5, z=110)
        p.line(q.outline, closed=True)


def _leg(p, x_end: float) -> None:
    """The bare leg held out to the side, ringed like a column of beads."""
    y0, y1 = 638, 672
    p.shape([(412, y0 + 3), (x_end, y0 + 1), (x_end, y1 - 1), (412, y1 - 3)], "gold", z=200)
    x = x_end + 12
    while x < 404:
        p.line([(x, y0 + 2), (x, y1 - 2)], width=p.lw * 0.7, z=50)
        x += 14


def _head(p) -> None:
    """Turned outward: a hooked beak, a stern eye under a heavy brow, and a crest swept back."""
    head = _path([(306, 184)],
                 _bez((306, 184), (324, 172), (346, 168), (366, 170)),   # the crown of the head
                 [(394, 160)],                                           # the crest, swept back
                 _bez((394, 160), (390, 170), (392, 178), (398, 182)),
                 [(428, 178)],
                 _bez((428, 178), (422, 190), (428, 200), (440, 206)),
                 _bez((440, 206), (452, 216), (460, 230), (466, 244)),   # the nape, into the neck
                 _bez((466, 244), (436, 256), (392, 258), (362, 252)),   # under the head
                 _bez((362, 252), (346, 248), (330, 242), (318, 238)),
                 _bez((318, 238), (310, 222), (308, 204), (306, 184)))
    p.shape(head, "gold", z=228)
    for cx, cy in ((378, 210), (404, 216), (430, 222), (364, 230), (390, 236), (416, 240), (442, 236)):
        _, rim = _scale(cx, cy, 22, 18, -0.9)
        p.line(rim, width=p.lw * 0.55, z=120)                               # small feathers on the cheek
    beak = _path([(306, 182)],
                 _bez((306, 182), (284, 180), (264, 196), (260, 218)),     # the curve of the beak
                 _bez((260, 218), (256, 236), (264, 250), (280, 256)),     # the hook, curled under
                 _bez((280, 256), (282, 246), (292, 238), (306, 236)),     # the cutting edge
                 [(320, 238)],                                             # the gape
                 _bez((320, 238), (312, 220), (308, 202), (306, 182)))
    p.shape(beak, "light", z=236)
    p.line(_bez((300, 186), (296, 200), (298, 214), (306, 222), 6), width=p.lw * 0.55, z=150)   # the cere
    p.dot(290, 202, 3.6, INK, z=150, line=False)                           # the nostril
    # the eye, and the brow drawn down over it
    p.shape([(318, 204), (328, 196), (342, 196), (348, 202), (338, 208), (326, 209)], ENAMEL, z=150,
            width=p.lw * 0.6)
    p.dot(331, 200, 2.4, PEARL, z=160, line=False)
    p.shape([(306, 196), (322, 186), (352, 184), (360, 190), (348, 194), (326, 196)], INK, z=120, line=False)


def _crown(p) -> None:
    """The closed imperial crown floating above the heads: two dark lobes, a pearled arch
    framing each, a gilded band down the middle with a great pearl, the rim, and the cross."""
    half = _path([(500, 70)],
                 _bez((500, 70), (488, 66), (472, 66), (462, 70)),
                 [(456, 82)],
                 _bez((456, 82), (446, 72), (430, 74), (422, 88)),
                 _bez((422, 88), (414, 104), (416, 124), (430, 138)),
                 [(436, 142), (436, 158), (500, 158)])
    p.shape(half + _mirror(half[::-1])[1:-1], ENAMEL, z=200)
    for side in (p, _Mirror(p)):
        arch = _path(_bez((462, 76), (436, 90), (434, 124), (458, 142)), [(470, 142)],
                     _bez((470, 142), (448, 124), (450, 92), (472, 80)))
        side.shape(arch, "light", z=232, width=p.lw * 0.6)
        pearls = _bez((466, 79), (442, 92), (441, 124), (464, 142), 20)
        for t in (0.18, 0.38, 0.6, 0.82):
            side.dot(*pearls[round(t * 20)], 4.2, ENAMEL, z=200, line=False)
    p.shape([(490, 72), (510, 72), (510, 140), (490, 140)], "light", z=232, width=p.lw * 0.6)
    for y in (88, 104):
        p.dot(500, y, 4, ENAMEL, z=200, line=False)
    p.dot(500, 124, 10, PEARL, z=244, width=p.lw * 0.6)
    p.shape([(432, 140), (568, 140), (568, 160), (432, 160)], "light", z=236, width=p.lw * 0.7)
    for i in range(7):
        p.dot(446 + i * 18, 150, 4, PEARL if i % 2 else ENAMEL, z=246, line=False)
    p.dot(500, 62, 9, "light", z=236, width=p.lw * 0.6)
    p.shape([(494, 20), (506, 20), (506, 56), (494, 56)], "light", z=240, width=p.lw * 0.6)
    p.shape([(482, 30), (518, 30), (518, 41), (482, 41)], "light", z=240, width=p.lw * 0.6)


SWORD_POMMEL, SWORD_TIP = (238, 716), (90, 352)


def _sword(p) -> None:
    """In the eagle's right claw (the viewer's left): the blade raised across the wing."""
    P, T = SWORD_POMMEL, SWORD_TIP
    d = _unit(T[0] - P[0], T[1] - P[1])
    n = (-d[1], d[0])
    length = math.hypot(T[0] - P[0], T[1] - P[1])

    def at(u, v):
        return (P[0] + d[0] * u + n[0] * v, P[1] + d[1] * u + n[1] * v)
    g = 104                                                     # where the guard crosses
    p.shape([at(g, 9.5), at(length - 46, 7.5), T, at(length - 46, -7.5), at(g, -9.5)], STEEL, z=238,
            width=p.lw * 0.8)
    p.fill([at(g + 4, 0), at(length - 48, 0), T, at(length - 48, -7), at(g + 4, -9)], STEEL_DARK, z=226)
    p.line([at(g + 10, 1), at(length - 60, 1)], width=p.lw * 0.45, color=(240, 244, 250), z=None)
    p.shape([at(4, 7.5), at(g, 7.5), at(g, -7.5), at(4, -7.5)], GRIP, z=230, width=p.lw * 0.7)
    guard = _path(_bez(at(g + 6, 46), at(g - 4, 30), at(g - 6, 12), at(g - 6, 0), 6),
                  _bez(at(g - 6, 0), at(g - 6, -12), at(g - 4, -30), at(g + 6, -46), 6),
                  _bez(at(g + 6, -46), at(g + 12, -30), at(g + 8, -12), at(g + 8, 0), 6),
                  _bez(at(g + 8, 0), at(g + 8, 12), at(g + 12, 30), at(g + 6, 46), 6))
    p.shape(guard, "gold", z=242, width=p.lw * 0.8)
    p.dot(*at(g + 7, 47), 8, "gold", z=244, width=p.lw * 0.7)
    p.dot(*at(g + 7, -47), 8, "gold", z=244, width=p.lw * 0.7)
    p.dot(*at(-2, 0), 13, "gold", z=244, width=p.lw * 0.8)              # the pommel
    # the claw closed round the grip: the back of the foot, three toes curled over, the talons beneath
    p.shape([at(94, 26), at(12, 30), at(8, 54), at(98, 50)], "gold", z=240, width=p.lw * 0.75)
    for u in (78, 52, 26):
        toe = _Quill(at(u, 40), at(u - 4, -16), 26, kind="toe", bend=0.18)
        p.shape(toe.outline, "gold", z=246, width=p.lw * 0.75)
        tip = toe.at(1.0, 0)
        p.shape([toe.at(0.86, 0.9), (tip[0] - n[0] * 10 - d[0] * 6, tip[1] - n[1] * 10 - d[1] * 6),
                 toe.at(0.86, -0.9)], INK, z=200, line=False)


def _orb(p) -> None:
    """The orb with its cross in the eagle's left claw (the viewer's right)."""
    cx, cy, r = 796, 672, 58
    p.shape([(790, 566), (802, 566), (802, 620), (790, 620)], "light", z=236, width=p.lw * 0.7)
    p.shape([(776, 580), (816, 580), (816, 591), (776, 591)], "light", z=236, width=p.lw * 0.7)
    disc = [(cx + r * math.cos(2 * math.pi * i / 48), cy + r * math.sin(2 * math.pi * i / 48)) for i in range(48)]
    p.fill(disc, "gold", z=225)
    p.clip()
    p.fill(_path(_bez((cx - r - 4, cy - 8), (cx - 20, cy + 2), (cx + 20, cy + 2), (cx + r + 4, cy - 8)),
                 _bez((cx + r + 4, cy + 4), (cx + 20, cy + 14), (cx - 20, cy + 14), (cx - r - 4, cy + 4))),
           ENAMEL, z=205)
    p.fill([(cx - 6, cy - r - 4), (cx + 6, cy - r - 4), (cx + 6, cy - 2), (cx - 6, cy - 2)], ENAMEL, z=205)
    p.unclip(disc)
    p.line(disc, closed=True)
    p.dot(cx - r * 0.42, cy - r * 0.4, r * 0.12, PEARL, z=245, line=False)
    # the claw: toes curled round the side of the orb, the talons dark
    for base, tip, bend in (((734, 646), (774, 624), -0.22), ((736, 658), (760, 688), 0.05),
                            ((732, 668), (772, 722), 0.25)):
        toe = _Quill(base, tip, 20, kind="toe", bend=bend)
        p.shape(toe.outline, "gold", z=246, width=p.lw * 0.75)
        e, f = toe.at(1.0, 0), toe.at(0.8, 0)
        dx, dy = _unit(e[0] - f[0], e[1] - f[1])
        p.shape([toe.at(0.82, 0.9), (e[0] + dx * 12, e[1] + dy * 12), toe.at(0.82, -0.9)], INK, z=200, line=False)


@lru_cache(maxsize=6)
def _eagle(w: int, h: int):
    """The eagle alone, w x h pixels with a transparent ground: (RGBA picture, centre of the light)."""
    k = art._ss(w, h)
    W, H = w * k, h * k
    bw, bh = BOX[2] - BOX[0], BOX[3] - BOX[1]
    scale = min(W * (1 - 2 * MARGIN) / bw, H * (1 - 2 * MARGIN) / bh)
    ox, oy = (W - bw * scale) / 2 - BOX[0] * scale, (H - bh * scale) / 2 - BOX[1] * scale
    pen = _Pen(W, H, scale, ox, oy, lw=max(1.05 * k, scale * 4.6))
    both = (pen, _Mirror(pen))
    _tail(pen)
    for side in both:
        _wing(side)
    _body(pen)
    for side in both:
        _leg(side, 262)
        _thigh(side)
    for side in both:
        _head(_Grow(side, (446, 250), 1.07))
    _sword(pen)
    _orb(pen)
    _crown(pen)
    return pen.finish(w, h), ((ox + CENTRE[0] * scale) / k, (oy + CENTRE[1] * scale) / k)


# ---------------------------------------------------------------- the light behind it
#
# As from a lamp hung behind a carving: the light is seen only round the eagle and
# through the gaps in it, brightest close to its breast and falling away with the
# distance; shafts of it stream out between the wings, the heads and the crown.

def _falloff(w: int, h: int, cx: float, cy: float, r0: float):
    """How light falls away with the distance from (cx, cy): 1 / (1 + (r / r0)²)."""
    n = 48
    sw, sh = (n, max(2, round(n * h / w))) if w >= h else (max(2, round(n * w / h)), n)
    small = Image.new("L", (sw, sh))
    px = small.load()
    for j in range(sh):
        y = (j + 0.5) * h / sh
        for i in range(sw):
            x = (i + 0.5) * w / sw
            px[i, j] = round(255 / (1 + ((x - cx) ** 2 + (y - cy) ** 2) / (r0 * r0)))
    return small.resize((w, h), Image.BICUBIC)


def _zoom(im, cx: float, cy: float, z: float):
    """im magnified z times about (cx, cy)."""
    return im.transform(im.size, Image.AFFINE, (1 / z, 0, cx - cx / z, 0, 1 / z, cy - cy / z),
                        resample=Image.BILINEAR)


def _shafts(im, cx: float, cy: float, reach: float, passes: int = 6):
    """im drawn out along the rays from (cx, cy), as light streams out past an edge."""
    out = im
    for i in range(passes):
        out = ImageChops.add(out, _zoom(out, cx, cy, reach ** (1 / 2 ** (passes - 1 - i))), scale=2.0)
    return out


@lru_cache(maxsize=6)
def _light(w: int, h: int):
    """What every step of light shares: the eagle, and the light behind it taken apart —
    a glow hugging the silhouette at three widths (the light is brightest right at the
    edges, as round a carving hung before a lamp), the shafts streaming out from it, the
    line of light along the eagle's own edge, a fade so the light never reaches the
    picture's border, and a fine grain that keeps the dark gradients from banding."""
    eagle, (cx, cy) = _eagle(w, h)
    alpha = eagle.split()[3]
    m = min(w, h)
    # stronger behind the breast and the necks than out at the wing tips
    core = _falloff(w, h, cx, cy, h * 0.38).point(lambda v: 90 + v * 165 // 255)
    glows = tuple(ImageChops.multiply(alpha.filter(ImageFilter.GaussianBlur(max(0.7, h * r))), core)
                  for r in (0.014, 0.045, 0.14))
    # the shafts: the light at the edges drawn out from the centre, a little stronger in
    # some directions than in others, as through dust in the air
    comb = Image.new("L", (w, h), 0)
    cd = ImageDraw.Draw(comb)
    reach = 2 * (w + h)
    for i in range(64):
        a0, a1 = 2 * math.pi * i / 64, 2 * math.pi * (i + 1) / 64
        strength = 0.35 + 0.65 * abs(math.sin(i * 2.399 + 0.7)) ** 2      # irregular, the same every time
        cd.polygon([(cx, cy), (cx + reach * math.cos(a0), cy + reach * math.sin(a0)),
                    (cx + reach * math.cos(a1), cy + reach * math.sin(a1))], fill=round(255 * strength))
    comb = comb.filter(ImageFilter.GaussianBlur(max(0.8, m * 0.01)))
    source = ImageChops.multiply(ImageChops.add(glows[0], glows[1]), comb)
    shafts = ImageChops.multiply(_shafts(source, cx, cy, 2.6), _falloff(w, h, cx, cy, h * 0.6))
    edge = ImageChops.subtract(alpha, alpha.filter(ImageFilter.MinFilter(3)))
    edge = edge.filter(ImageFilter.GaussianBlur(max(0.6, m * 0.005)))
    pad = max(2, int(m * 0.05))
    fade = Image.new("L", (w, h), 0)
    ImageDraw.Draw(fade).rounded_rectangle([pad, pad, w - 1 - pad, h - 1 - pad], radius=pad * 2, fill=255)
    fade = fade.filter(ImageFilter.GaussianBlur(pad * 0.8))
    grain = Image.effect_noise((w, h), 1.6)
    return eagle, alpha, glows, shafts, edge, fade, grain


def _weigh(im, share: float):
    return im.point(lambda v: min(255, int(v * share + 0.5)))


def _colour_ramp(glow) -> list:
    """Lookup tables turning the strength of the light into its colour: the scheme's colour
    brought up to full brightness where the light is faint, warming towards white where
    it is strongest."""
    top = max(glow) or 1
    pure = tuple(min(255, c * 255 // top) for c in glow)
    hot = art._mix(pure, (255, 248, 232), 0.8)
    luts: list = [[], [], []]
    for v in range(256):
        x = v / 255
        f = max(0.0, (x - 0.45) / 0.55) ** 1.4
        for c in range(3):
            luts[c].append(min(255, round((pure[c] * (1 - f) + hot[c] * f) * x)))
    return luts[0] + luts[1] + luts[2]


@lru_cache(maxsize=64)
def frame(w: int, h: int, bg, glow, level: int = 0, levels: int = LEVELS):
    """The eagle on bg with the light behind it at step `level` of `levels` (0 = at rest)."""
    bg = art._rgb(bg)
    glow = art._rgb(glow) if glow is not None else art.GOLD
    t = max(0.0, min(1.0, level / max(1, levels - 1)))
    eagle, alpha, (tight, mid, wide), shafts, edge, fade, grain = _light(w, h)
    light = ImageChops.add(_weigh(tight, 0.34 + 0.54 * t), _weigh(mid, 0.26 + 0.42 * t))
    light = ImageChops.add(light, _weigh(wide, 0.22 + 0.36 * t))
    if t > 0:
        light = ImageChops.add(light, _weigh(shafts, 1.0 * t))
    light = ImageChops.multiply(ImageChops.add(light, grain, 1.0, -128), fade)
    canvas = Image.new("RGB", (w, h), bg)
    if sum(bg) / 3 < 128:                           # light on a dark ground adds to it
        canvas = ImageChops.screen(canvas, light.convert("RGB").point(_colour_ramp(glow)))
    else:                                           # on a light scheme it is a tint
        canvas.paste(glow, (0, 0), _weigh(light, 0.6))
    lit = eagle
    if t > 0:                                       # the light catches the eagle's edges
        lit = eagle.copy()
        lit.paste(art._mix(glow, (255, 250, 236), 0.65), (0, 0), _weigh(edge, 0.75 * t))
        lit = Image.blend(lit, Image.new("RGBA", (w, h), (255, 248, 230, 255)), 0.05 * t)
    canvas.paste(lit.convert("RGB"), (0, 0), alpha)
    return canvas


def frames(w: int, h: int, bg, glow, levels: int = LEVELS) -> list:
    """Every step of light, from rest to the height of a pulse."""
    return [frame(w, h, bg, glow, i, levels) for i in range(levels)]


def available() -> bool:
    return Image is not None


__all__ = ["LEVELS", "available", "frame", "frames"]
