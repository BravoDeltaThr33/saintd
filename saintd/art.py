"""Pictures painted for terminals that show true images (Kitty, Ghostty,
Sixel terminals): saint icons set in a gilded kiot (the arched case an icon
stands in, cast in relief: rows of beads, a running vine, the three-bar cross
under the arch, a ruby at its head and silver rosettes), a painted "icon blank"
(gold leaf, halo and initial) for saints without a picture, and a gilded
Orthodox cross set between two rules as a headpiece (the double-headed eagle of
the tab column is in eagle.py).

Everything is drawn at a few times the size and scaled down, which gives
smooth edges; every picture is kept so it is painted once."""

from __future__ import annotations

import bisect
import math
from functools import lru_cache
from pathlib import Path

try:
    from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont
except Exception:                       # pragma: no cover - Pillow comes with textual-image
    Image = None

S = 3                                   # supersampling

GOLD_LIGHT = (250, 232, 160)
GOLD = (218, 172, 70)
GOLD_DARK = (138, 98, 22)
GOLD_EDGE = (58, 38, 8)
MAT = (70, 20, 18)                      # the dark red cloth behind an icon, should it not fill its place
CINNABAR = (150, 32, 22)

FONTS = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSerif-Bold.ttf",
    "/usr/share/fonts/truetype/noto/NotoSerif-Bold.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSerifBold.ttf",
    "/usr/share/fonts/truetype/ubuntu/Ubuntu-B.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
]


def available() -> bool:
    return Image is not None


@lru_cache(maxsize=16)
def font(size: int):
    for p in FONTS:
        if Path(p).exists():
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                continue
    try:
        return ImageFont.load_default(size=size)
    except Exception:                   # very old Pillow: a small bitmap font
        return ImageFont.load_default()


def _rgb(c) -> tuple[int, int, int]:
    if isinstance(c, str):
        c = c.lstrip("#")
        return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4))      # type: ignore[return-value]
    return tuple(int(x) for x in c[:3])                            # type: ignore[return-value]


def _mix(a, b, t: float) -> tuple[int, int, int]:
    return tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3))   # type: ignore[return-value]


def gold_leaf(w: int, h: int, squares: bool = False):
    """A diagonal gold gradient with a soft sheen; with squares=True, the
    faint grid of gold leaf laid on in small sheets."""
    small = Image.new("RGB", (64, 64))
    px = small.load()
    for y in range(64):
        for x in range(64):
            t = (x + y) / 126
            sheen = 0.5 + 0.5 * math.cos((t - 0.3) * math.pi * 2.2)
            base = _mix(GOLD_LIGHT, GOLD, min(1, t * 1.4)) if t < 0.7 else _mix(GOLD, GOLD_DARK, (t - 0.7) / 0.3)
            px[x, y] = _mix(base, GOLD_LIGHT, 0.18 * sheen)
    im = small.resize((w, h), Image.BICUBIC)
    if squares:
        d = ImageDraw.Draw(im, "RGBA")
        step = max(8, min(w, h) // 7)
        for i, y in enumerate(range(0, h, step)):
            for j, x in enumerate(range(0, w, step)):
                if (i + j) % 2:
                    d.rectangle([x, y, x + step, y + step], fill=(255, 245, 200, 14))
                else:
                    d.rectangle([x, y, x + step, y + step], fill=(90, 60, 10, 10))
    return im


def _edge(mask, width: int, inside: bool = True):
    """The band of a mask's border, `width` pixels wide (inside or outside the shape)."""
    k = 2 * width + 1
    if inside:
        return ImageChops.subtract(mask, mask.filter(ImageFilter.MinFilter(k)))
    return ImageChops.subtract(mask.filter(ImageFilter.MaxFilter(k)), mask)


def _shrink(mask, r: float):
    """The mask drawn in by about r pixels all round (quicker than a MinFilter as wide)."""
    if r < 1.5:
        return mask.filter(ImageFilter.MinFilter(3))
    return mask.filter(ImageFilter.GaussianBlur(r / 2)).point(lambda v: 255 if v >= 250 else 0)


def _ss(w: int, h: int) -> int:
    """Supersampling for a picture of this size (big pictures need less)."""
    m = max(w, h)
    return 3 if m <= 420 else 2 if m <= 840 else 1


# ---------------------------------------------------------------- the kiot
#
# The frame is a gilded kiot (the case an icon stands in), as in the ones cast in
# brass and gilt: a round arch over straight sides; all round, a rounded rim, a row
# of beads, a band of running vine in relief and another row of beads; under the
# arch a panel with the three-bar cross on a lobed plate between scrolls of vine;
# the head of the opening cut in two arches that meet in a point under the cross; a
# cabochon ruby in a beaded, pierced setting at the top of the arch; and silver
# rosettes where the arch springs from the sides and at the two lower corners.
#
# It is painted as a relief: every part has a height, the heights are lit from the
# upper left, and the colour follows the height, the hollows dark with old gilding
# and the raised work bright, the way brass is polished by the hand.

SIDE = 0.13             # the bands down the sides, as a share of the frame's width
FOOT = 0.135            # the band along the foot
CUSP = 0.12             # how far above the springing of the arch the opening's twin arches meet
HUMP = 0.055            # how high each of the twin arches rises
RELIEF = [0, 1, 2, -1, 0, 1, -2, -1, 0]     # a kernel that lights a relief from the upper left

FIELD, LIP, RIM, STEM, LEAF, CROWN = 104, 186, 214, 196, 208, 232   # heights in the relief

GOLD_RAMP = [(0, (30, 18, 6)), (70, (74, 46, 14)), (100, (124, 86, 34)), (140, (168, 122, 50)),
             (190, (214, 164, 70)), (228, (238, 200, 112)), (255, (252, 230, 164))]
SILVER_RAMP = [(0, (20, 19, 17)), (100, (54, 52, 49)), (150, (102, 100, 96)), (200, (158, 156, 151)),
               (235, (204, 202, 197)), (255, (232, 231, 226))]


def _ramp(stops) -> list:
    """A lookup table for Image.point (on a grey picture made RGB) from a few colour stops."""
    out: list = [[], [], []]
    for v in range(256):
        for (a, ca), (b, cb) in zip(stops, stops[1:]):
            if a <= v <= b:
                c = _mix(ca, cb, (v - a) / max(1, b - a))
                break
        for i in range(3):
            out[i].append(c[i])
    return out[0] + out[1] + out[2]


def _proportions(a: float) -> tuple:
    """For an icon of shape a (width / height), in shares of the frame's width: the height of
    the arch, the line where the twin arches of the opening meet, the top of the icon (the
    crowns of the twin arches) and the height of the whole frame."""
    ra = 0.5 * max(0.6, min(1.0, a ** -0.6))           # a half circle, lowered over wide icons
    s = ra / 0.5
    cusp = ra - CUSP * s
    top = cusp - HUMP * s ** 0.5
    return ra, cusp, top, top + (1 - 2 * SIDE) / a + FOOT


class _Track:
    """Walking along a line of points: the place s along it, v to its left (outward, on
    the frame's bands as they are drawn)."""

    def __init__(self, pts) -> None:
        self.pts = pts
        self.cum = [0.0]
        for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
            self.cum.append(self.cum[-1] + math.hypot(x1 - x0, y1 - y0))
        self.length = self.cum[-1]

    def at(self, s: float, v: float = 0.0):
        s = max(0.0, min(self.length, s))
        i = min(len(self.pts) - 2, max(0, bisect.bisect_right(self.cum, s) - 1))
        seg = (self.cum[i + 1] - self.cum[i]) or 1e-9
        t = (s - self.cum[i]) / seg
        (x0, y0), (x1, y1) = self.pts[i], self.pts[i + 1]
        tx, ty = (x1 - x0) / seg, (y1 - y0) / seg
        return (x0 + (x1 - x0) * t + ty * v, y0 + (y1 - y0) * t - tx * v)


def _oval(p0, p1, width: float, n: int = 14) -> list:
    """An oval whose long axis runs from p0 to p1."""
    cx, cy = (p0[0] + p1[0]) / 2, (p0[1] + p1[1]) / 2
    half = math.hypot(p1[0] - p0[0], p1[1] - p0[1]) / 2 or 1e-9
    ux, uy = (p1[0] - p0[0]) / (2 * half), (p1[1] - p0[1]) / (2 * half)
    out = []
    for i in range(n):
        a = 2 * math.pi * i / n
        c, s = math.cos(a) * half, math.sin(a) * width / 2
        out.append((cx + ux * c - uy * s, cy + uy * c + ux * s))
    return out


def _leaf(d, base, tip, z: int = LEAF) -> None:
    """A vine leaf from base to tip: five lobes, each with its vein pressed in."""
    L = math.hypot(tip[0] - base[0], tip[1] - base[1]) or 1e-9
    ux, uy = (tip[0] - base[0]) / L, (tip[1] - base[1]) / L
    px, py = -uy, ux

    def P(a, b):
        return (base[0] + ux * L * a + px * L * b, base[1] + uy * L * a + py * L * b)
    lobes = [(P(1.0, 0), 0.48)] + [(P(0.72, 0.4 * g), 0.36) for g in (1, -1)] + \
        [(P(0.3, 0.46 * g), 0.28) for g in (1, -1)]
    for t, wd in lobes:
        d.polygon(_oval(P(0.08, 0), t, L * wd), fill=z)
    vein = max(1, round(L * 0.045))
    for t, _ in lobes:
        d.line([P(0.12, 0), (base[0] + (t[0] - base[0]) * 0.8, base[1] + (t[1] - base[1]) * 0.8)],
               fill=z - 50, width=vein)


def _flower(d, c, r: float, z: int = LEAF) -> None:
    """A small five-petalled flower with a raised heart."""
    for i in range(5):
        a = 2 * math.pi * i / 5 - math.pi / 2
        x, y = c[0] + math.cos(a) * r * 0.62, c[1] + math.sin(a) * r * 0.62
        d.ellipse([x - r * 0.46, y - r * 0.46, x + r * 0.46, y + r * 0.46], fill=z)
    _dome(d, c[0], c[1], r * 0.42, z + 26)


def _dome(d, x: float, y: float, r: float, z: int) -> None:
    """A bead: rings rising to its top."""
    for j, f in enumerate((1.0, 0.8, 0.58, 0.34)):
        v = z - (3 - j) * 26
        d.ellipse([x - r * f, y - r * f, x + r * f, y + r * f], fill=v)


def _spiral(c, r_out: float, turns: float, start: float, sense: int, n: int = 40) -> list:
    """A spiral closing in on c, from radius r_out at angle start."""
    out = []
    for i in range(n + 1):
        t = i / n
        a = start + sense * 2 * math.pi * turns * t
        r = r_out * (1 - 0.72 * t)
        out.append((c[0] + r * math.cos(a), c[1] + r * math.sin(a)))
    return out


def _beads(d, pts, r: float, z: int = CROWN + 10, closed: bool = False) -> None:
    """A row of beads along a line of points."""
    tr = _Track(list(pts) + [pts[0]] if closed else list(pts))
    n = max(1, int(tr.length / (2.3 * r)))
    for i in range(n):
        x, y = tr.at((i + 0.5) * tr.length / n)
        _dome(d, x, y, r, z)


def _vine(d, tr: _Track, width: float, sense: int = 1) -> None:
    """A running vine along the track, `width` across: the stem winding from side to side,
    and in every bay of it a vine leaf on its stalk, with a curling tendril or a flower."""
    L = tr.length
    period = L / max(1, round(L / (width * 2.2)))
    amp = width * 0.24

    def at(s, v):
        return tr.at(s, v * sense)
    steps = max(8, int(L / (width * 0.08)))
    stem_w = max(1, round(width * 0.12))
    d.line([at(L * i / steps, amp * math.sin(2 * math.pi * (L * i / steps) / period)) for i in range(steps + 1)],
           fill=STEM, width=stem_w, joint="curve")
    j = 0
    while (j + 0.5) * period / 2 < L:
        g = 1 if j % 2 == 0 else -1                     # the crest is on side g, its bay on side -g
        sc = (j + 0.5) * period / 2
        stalk = [at(sc - period * 0.08 + period * 0.06 * i / 4, g * amp * (0.95 - 0.7 * i / 4)) for i in range(5)]
        d.line(stalk, fill=STEM, width=max(1, round(stem_w * 0.8)), joint="curve")
        _leaf(d, stalk[-1], at(sc + period * 0.14, -g * width * 0.42))
        if j % 2:
            _flower(d, at(sc - period * 0.2, -g * width * 0.24), width * 0.17)
        else:
            c = at(sc - period * 0.19, -g * width * 0.2)
            d.line(_spiral(c, width * 0.14, 1.25, math.atan2(at(sc, 0)[1] - c[1], at(sc, 0)[0] - c[0]), -g * sense, 24),
                   fill=STEM - 10, width=max(1, round(stem_w * 0.6)), joint="curve")
        j += 1


class _Kiot:
    """The geometry of one frame, W pixels wide, its top left corner at (ox, oy)."""

    def __init__(self, W: float, a: float, ox: float, oy: float) -> None:
        ra, cusp, top, height = _proportions(a)
        self.W, self.H, self.ox, self.oy = W, W * height, ox, oy
        self.ra, self.cusp, self.top = ra * W, cusp * W, top * W
        self.side, self.foot = SIDE * W, FOOT * W
        self.cx, self.cy = ox + W / 2, oy + self.ra       # the centre of the arch
        self.box = (ox + self.side, oy + self.top, ox + W - self.side, oy + self.H - self.foot)
        rx, ry = W / 2 - self.side, self.ra - self.side
        self.phi = math.asin(max(-1.0, min(1.0, (self.ra - self.cusp) / ry)))
        self.lx = self.cx - rx * math.cos(self.phi)       # where the twin arches meet the arch's inner edge

    def arch(self, d: float, a0: float = math.pi, a1: float = 2 * math.pi, n: int = 72) -> list:
        """The arch d inside its outer edge, from angle a0 to a1 (pi: the left springing; 1.5 pi: the top)."""
        rx, ry = self.W / 2 - d, self.ra - d
        return [(self.cx + rx * math.cos(a0 + (a1 - a0) * i / n), self.cy + ry * math.sin(a0 + (a1 - a0) * i / n))
                for i in range(n + 1)]

    def ring(self, d: float, df: float | None = None) -> list:
        """The outline d inside the outer edge (df inside it along the foot)."""
        bottom = self.oy + self.H - (d if df is None else df)
        return [(self.ox + d, bottom)] + self.arch(d) + [(self.ox + self.W - d, bottom)]

    def humps(self, lift: float = 0.0, n: int = 24) -> list:
        """The twin arches over the opening, left to right, raised by lift."""
        yk = self.oy + self.cusp - lift
        half = (self.cx - self.lx) / 2
        hh = HUMP * (self.ra / (0.5 * self.W)) ** 0.5 * self.W
        left = [(self.lx + half + half * math.cos(math.pi + math.pi * i / n),
                 yk + hh * math.sin(math.pi + math.pi * i / n)) for i in range(n + 1)]
        right = [(2 * self.cx - x, y) for x, y in left[::-1]]
        return left + right[1:]

    def arch_y(self, x: float, d: float) -> float:
        """The height of the arch, d inside its outer edge, above the point x."""
        rx, ry = self.W / 2 - d, self.ra - d
        return self.cy - ry * math.sqrt(max(0.0, 1 - ((x - self.cx) / rx) ** 2))

    def hump_y(self, x: float) -> float:
        """The height of the twin arches over the opening above the point x."""
        x = self.cx - abs(x - self.cx)
        half = (self.cx - self.lx) / 2
        hh = HUMP * (self.ra / (0.5 * self.W)) ** 0.5 * self.W
        return self.oy + self.cusp - hh * math.sqrt(max(0.0, 1 - ((x - self.lx - half) / half) ** 2))

    def opening(self) -> list:
        s = self.side
        foot = self.oy + self.H - self.foot
        side = [(self.ox + s, foot)] + self.arch(s, math.pi, math.pi + self.phi, 10)
        return side + self.humps() + [(2 * self.cx - x, y) for x, y in side[::-1]]

    def tympanum(self) -> list:
        return self.arch(self.side, math.pi + self.phi, 2 * math.pi - self.phi, 48) + self.humps()[::-1]


def _cross_plate(d, cx: float, top: float, bottom: float) -> None:
    """The three-bar cross on a plate whose arms end in trefoils, under the arch."""
    hh = (bottom - top) / 2
    cy = top + hh

    def P(x, y):
        return (cx + x * hh, cy + y * hh)
    plate = Image.new("L", d.im.size, 0)          # drawn apart, for its raised border
    pd = ImageDraw.Draw(plate)
    pd.polygon([P(-0.17, -0.8), P(0.17, -0.8), P(0.17, 0.8), P(-0.17, 0.8)], fill=255)
    pd.polygon([P(-0.56, -0.43), P(0.56, -0.43), P(0.56, -0.07), P(-0.56, -0.07)], fill=255)
    for x, y, r in ((0, -0.83, 0.17), (0.15, -0.7, 0.13), (-0.15, -0.7, 0.13), (0, 0.83, 0.17), (0.15, 0.7, 0.13),
                    (-0.15, 0.7, 0.13), (0.62, -0.25, 0.16), (0.5, -0.41, 0.12), (0.5, -0.09, 0.12),
                    (-0.62, -0.25, 0.16), (-0.5, -0.41, 0.12), (-0.5, -0.09, 0.12)):
        (px, py), rr = P(x, y), r * hh
        pd.ellipse([px - rr, py - rr, px + rr, py + rr], fill=255)
    border = max(1, round(hh * 0.085))
    d.bitmap((0, 0), plate, fill=RIM + 8)
    d.bitmap((0, 0), _shrink(plate, border), fill=FIELD + 72)
    t = max(1, hh * 0.075)                            # the cross itself, raised again
    d.polygon([P(-t / hh, -0.78), P(t / hh, -0.78), P(t / hh, 0.8), P(-t / hh, 0.8)], fill=CROWN)
    for y, half in ((-0.56, 0.17), (-0.25, 0.47)):
        d.polygon([P(-half, y - t / hh * 0.9), P(half, y - t / hh * 0.9), P(half, y + t / hh * 0.9),
                   P(-half, y + t / hh * 0.9)], fill=CROWN)
    d.polygon([P(-0.25, 0.36 - t / hh * 0.9), P(0.25, 0.5 - t / hh * 0.9), P(0.25, 0.5 + t / hh * 0.9),
               P(-0.25, 0.36 + t / hh * 0.9)], fill=CROWN)     # the footrest, raised on the left


def _rosette(d, sil, x: float, y: float, r: float) -> None:
    """A silver rosette: a plate with six small petals and six large ones, a ridge down each
    large one, and a domed heart in a ring of beads."""
    sil.ellipse([x - r * 1.03, y - r * 1.03, x + r * 1.03, y + r * 1.03], fill=255)
    d.ellipse([x - r * 0.98, y - r * 0.98, x + r * 0.98, y + r * 0.98], fill=FIELD + 48)
    for i in range(6):
        a = 2 * math.pi * i / 6 + math.pi / 6
        d.polygon(_oval((x, y), (x + math.cos(a) * r * 0.7, y + math.sin(a) * r * 0.7), r * 0.42), fill=STEM - 14)
    for i in range(6):
        a = 2 * math.pi * i / 6
        tip = (x + math.cos(a) * r * 0.97, y + math.sin(a) * r * 0.97)
        d.polygon(_oval((x + math.cos(a) * r * 0.14, y + math.sin(a) * r * 0.14), tip, r * 0.5), fill=LEAF)
        d.line([(x + math.cos(a) * r * 0.32, y + math.sin(a) * r * 0.32),
                (x + math.cos(a) * r * 0.82, y + math.sin(a) * r * 0.82)],
               fill=CROWN + 6, width=max(1, round(r * 0.07)))
    _beads(d, [(x + math.cos(2 * math.pi * i / 24) * r * 0.34, y + math.sin(2 * math.pi * i / 24) * r * 0.34)
               for i in range(24)], r * 0.06, CROWN, closed=True)
    _dome(d, x, y, r * 0.26, 252)


def _gem_setting(d, x: float, y: float, r: float) -> None:
    """The setting of the ruby: a ring of pierced loops, a row of beads, a smooth bezel."""
    loop = r * 0.27
    for i in range(14):
        a = 2 * math.pi * i / 14
        lx, ly = x + math.cos(a) * r * 1.5, y + math.sin(a) * r * 1.5
        d.ellipse([lx - loop, ly - loop, lx + loop, ly + loop], fill=RIM)
        d.ellipse([lx - loop * 0.42, ly - loop * 0.42, lx + loop * 0.42, ly + loop * 0.42], fill=64)
        bx, by = x + math.cos(a + math.pi / 14) * r * 1.62, y + math.sin(a + math.pi / 14) * r * 1.62
        _dome(d, bx, by, r * 0.1, CROWN)
    _beads(d, [(x + math.cos(2 * math.pi * i / 64) * r * 1.2, y + math.sin(2 * math.pi * i / 64) * r * 1.2)
               for i in range(64)], r * 0.12, CROWN + 10, closed=True)
    d.ellipse([x - r * 1.08, y - r * 1.08, x + r * 1.08, y + r * 1.08], fill=RIM + 10)


def _ruby(size: int):
    """A cabochon ruby, size pixels across: deep red, lit from within, a gleam at the upper left."""
    r = size / 2
    im = Image.new("RGB", (size, size), (96, 6, 22))
    glow = Image.new("L", (size, size), 0)
    ImageDraw.Draw(glow).ellipse([r * 0.55, r * 0.6, r * 1.75, r * 1.8], fill=255)
    im.paste((214, 34, 68), (0, 0), glow.filter(ImageFilter.GaussianBlur(r * 0.35)))
    rim = Image.new("L", (size, size), 255)
    ImageDraw.Draw(rim).ellipse([r * 0.18, r * 0.18, r * 1.82, r * 1.82], fill=0)
    im.paste((52, 0, 10), (0, 0), rim.filter(ImageFilter.GaussianBlur(r * 0.14)))
    shine = Image.new("L", (size, size), 0)
    ImageDraw.Draw(shine).ellipse([r * 0.42, r * 0.36, r * 0.98, r * 0.74], fill=235)
    im.paste((255, 236, 240), (0, 0), shine.filter(ImageFilter.GaussianBlur(max(0.6, r * 0.06))))
    soft = Image.new("L", (size, size), 0)
    ImageDraw.Draw(soft).ellipse([r * 1.05, r * 1.15, r * 1.55, r * 1.55], fill=90)
    im.paste((255, 150, 170), (0, 0), soft.filter(ImageFilter.GaussianBlur(r * 0.12)))
    return im


def _paint_kiot(w: int, h: int, bg, a: float, k: int):
    """The frame for an icon of shape a, as large as fits in w x h, painted k times larger:
    (picture, mask of the frame, mask of the opening, the icon's place, the shadow cast
    into the opening), all at k times the size."""
    W_, H_ = w * k, h * k
    pad = max(1, round(min(w, h) * 0.03)) * k
    height = _proportions(a)[3]
    Wf = max(8.0 * k, min(W_ - 2 * pad - k, (H_ - 2 * pad - k) / height))
    g = _Kiot(Wf, a, (W_ - Wf) / 2, (H_ - Wf * height) / 2)
    outer, inner_open = Image.new("L", (W_, H_), 0), Image.new("L", (W_, H_), 0)
    ImageDraw.Draw(outer).polygon(g.ring(0), fill=255)
    ImageDraw.Draw(inner_open).polygon(g.opening(), fill=255)
    frame_mask = ImageChops.subtract(outer, inner_open)
    hgt = Image.new("L", (W_, H_), FIELD)
    sil = Image.new("L", (W_, H_), 0)                 # where the work is silver
    d, sd = ImageDraw.Draw(hgt), ImageDraw.Draw(sil)
    u = Wf / 100                                      # a hundredth of the frame's width
    bead = max(0.9 * k, 0.85 * u)
    # the rim round the outside, the lip round the opening and along the twin arches
    rim, lip = g.ring(0), g.ring(g.side, g.foot)
    d.line(rim + rim[:1], fill=RIM, width=max(2, round(2.6 * u)), joint="curve")
    d.line(lip + lip[:1], fill=LIP, width=max(2, round(2.2 * u)), joint="curve")
    d.polygon(g.tympanum(), fill=FIELD - 6)
    d.line(g.humps(), fill=LIP, width=max(2, round(2.2 * u)), joint="curve")
    # the vine all round, the right half the mirror of the left; its own along the foot
    mid = (3.2 + 10.0) / 2 * u
    field = (10.0 - 3.2) * u
    foot_mid = g.foot - (3.2 + (FOOT * 100 - 3.0)) / 2 * u
    left = [(g.ox + mid, g.oy + g.H - g.foot * 0.5)] + g.arch(mid, math.pi, 1.5 * math.pi, 64)
    vine = Image.new("L", (W_, H_), 0)
    vd = ImageDraw.Draw(vine)
    _vine(vd, _Track(left), field, 1)
    _vine(vd, _Track([(g.cx, g.oy + g.H - foot_mid), (g.ox + g.W - g.side * 0.5, g.oy + g.H - foot_mid)]),
          (FOOT * 100 - 3.0 - 3.2) * u, -1)
    vine = ImageChops.lighter(vine, vine.transpose(Image.FLIP_LEFT_RIGHT))     # the frame is centred
    lane = Image.new("L", (W_, H_), 0)
    ImageDraw.Draw(lane).polygon(g.ring(3.4 * u), fill=255)
    ImageDraw.Draw(lane).polygon(g.ring(9.8 * u, (FOOT * 100 - 3.2) * u), fill=0)
    hgt.paste(vine, (0, 0), ImageChops.multiply(ImageChops.multiply(vine.point(lambda v: 255 if v else 0), lane),
                                                outer))
    _flower(d, (g.cx, g.oy + g.H - foot_mid), (FOOT * 100 - 6.2) * u * 0.32)
    # the rows of beads: outside, inside the band, and over the twin arches
    _beads(d, g.ring(2.2 * u), bead, closed=True)
    _beads(d, g.ring(g.side - 2.1 * u, g.foot - 2.1 * u), bead, closed=True)
    _beads(d, g.humps(lift=2.0 * u)[2:-2], bead * 0.9)
    # under the arch: the cross on its plate between scrolls of vine
    tym = Image.new("L", (W_, H_), 0)
    ImageDraw.Draw(tym).polygon(g.tympanum(), fill=255)
    tym = _shrink(tym, 1.6 * u)
    scroll = Image.new("L", (W_, H_), 0)
    sc = ImageDraw.Draw(scroll)
    t_top, t_bottom = g.oy + g.side + 0.6 * u, g.oy + g.cusp + 1.4 * u
    plate_w = (t_bottom - t_top) / 2 * 0.62               # half the width of the cross's plate
    room = g.cx - plate_w - g.lx
    xa = g.cx - plate_w - room * 0.4                       # the eye of the scroll
    ya = (g.arch_y(xa, g.side) + g.hump_y(xa)) / 2 + 0.4 * u
    ra_ = (g.hump_y(xa) - g.arch_y(xa, g.side)) * 0.33
    stem_w = max(1, round(1.05 * u))
    start = (g.cx - plate_w * 0.72, t_bottom - (t_bottom - t_top) * 0.16)
    for mirror in (False, True):
        def M(pts):
            return [(2 * g.cx - x, y) for x, y in pts] if mirror else list(pts)
        coil = _spiral((xa, ya), ra_, 1.3, math.pi / 2, 1, 40)
        stem = _bez_pts(start, (start[0] - room * 0.12, start[1] + 1.2 * u), (xa + ra_ * 1.1, ya + ra_), coil[0])
        x_end = g.lx + room * 0.12                          # a tail into the narrow corner
        tail = _bez_pts(coil[8], (xa - ra_ * 1.5, ya + ra_ * 0.2), (x_end + room * 0.12, g.hump_y(x_end) - 3.4 * u),
                        (x_end, g.hump_y(x_end) - 3.0 * u))
        bud = _bez_pts(stem[6], (stem[6][0] + 0.4 * u, stem[6][1] - ra_ * 0.6),
                       (xa + ra_ * 1.6, ya - ra_ * 0.3), (xa + ra_ * 1.25, ya - ra_ * 0.75))
        for line, wd in ((stem, stem_w), (coil, stem_w), (tail, max(1, round(stem_w * 0.8))),
                         (bud, max(1, round(stem_w * 0.7)))):
            sc.line(M(line), fill=STEM, width=wd, joint="curve")
        for base, tip, z in ((coil[-1], (xa + ra_ * 0.2, ya - ra_ * 0.62), LEAF),
                             (bud[-1], (xa + ra_ * 1.05, ya - ra_ * 1.35), LEAF - 6),
                             (tail[-1], (x_end - room * 0.1, g.hump_y(x_end) - 5.0 * u), LEAF - 6)):
            b, t = M([base, tip])
            _leaf(sc, b, t, z)
    hgt.paste(scroll, (0, 0), ImageChops.multiply(scroll.point(lambda v: 255 if v else 0), tym))
    _cross_plate(d, g.cx, t_top, t_bottom)
    # the ruby's setting at the top, the rosettes
    gem_r = 3.9 * u
    gem_c = (g.cx, g.oy + 7.4 * u)
    _gem_setting(d, gem_c[0], gem_c[1], gem_r)
    for x, y in ((g.ox + g.side / 2, g.cy), (g.ox + g.W - g.side / 2, g.cy),
                 (g.ox + g.side / 2, g.oy + g.H - g.foot / 2), (g.ox + g.W - g.side / 2, g.oy + g.H - g.foot / 2)):
        _rosette(d, sd, x, y, 6.0 * u)
    lit = _light_relief(hgt, sil, u, k)
    size = max(2, round(gem_r * 2))
    ruby = _ruby(size)
    rm = Image.new("L", (size, size), 0)
    ImageDraw.Draw(rm).ellipse([0, 0, size - 1, size - 1], fill=255)
    lit.paste(ruby, (round(gem_c[0] - size / 2), round(gem_c[1] - size / 2)), rm)
    # on the ground: the frame's shadow, then the frame
    canvas = Image.new("RGB", (W_, H_), _rgb(bg))
    drop = ImageChops.offset(outer.filter(ImageFilter.GaussianBlur(max(1, 1.6 * u))), round(0.8 * u), round(1.2 * u))
    canvas.paste((0, 0, 0), (0, 0), drop.point(lambda v: v * 150 // 255))
    canvas.paste(lit, (0, 0), frame_mask)
    # the shadow the frame casts on the icon, from the upper left
    cast = ImageChops.offset(frame_mask, round(1.0 * u), round(1.4 * u))
    cast = cast.filter(ImageFilter.GaussianBlur(max(1, 1.2 * u)))
    cast = ImageChops.multiply(cast, inner_open).point(lambda v: v * 190 // 255)
    edge = ImageChops.subtract(inner_open, _shrink(inner_open, max(1.0, 0.7 * u))).point(lambda v: v * 200 // 255)
    return canvas, frame_mask, inner_open, g.box, ImageChops.lighter(cast, edge)


def _light_relief(hgt, sil, u: float, k: int):
    """Light the relief from the upper left and colour it by its height: the hollows dark with
    old gilding (or tarnish, on the silver), the raised work bright, a gleam on the edges
    that catch the light, and shadow in the crevices beside raised work."""
    blur = max(0.6 * k, 0.3 * u)
    grain = Image.effect_noise(hgt.size, 7).filter(ImageFilter.GaussianBlur(max(0.5, 0.12 * u)))
    soft = ImageChops.add(hgt, grain, 1.0, -128).filter(ImageFilter.GaussianBlur(blur))
    shade = soft.filter(ImageFilter.Kernel((3, 3), RELIEF, scale=max(0.35, 2.2 / blur), offset=128))
    hollow = ImageChops.subtract(hgt.filter(ImageFilter.GaussianBlur(max(1.0, 1.3 * u))), soft)
    grey = soft.convert("RGB")
    metal = Image.composite(grey.point(_ramp(SILVER_RAMP)), grey.point(_ramp(GOLD_RAMP)), sil)
    lit = ImageChops.hard_light(metal, Image.merge("RGB", (shade, shade, shade)))
    dark = hollow.point(lambda v: max(150, 255 - v * 2))
    lit = ImageChops.multiply(lit, Image.merge("RGB", (dark, dark, dark)))
    lit.paste((255, 240, 200), (0, 0), shade.point(lambda v: 0 if v < 168 else min(210, (v - 168) * 4)))
    sheen = _diagonal(*hgt.size).point(lambda v: 255 - v * 56 // 255)
    return ImageChops.multiply(lit, Image.merge("RGB", (sheen, sheen, sheen)))


def _diagonal(w: int, h: int):
    """A gradient from the upper left (0) to the lower right (255)."""
    small = Image.new("L", (32, 32))
    small.putdata([round((x + y) * 255 / 62) for y in range(32) for x in range(32)])
    return small.resize((w, h), Image.BICUBIC)


def _bez_pts(p0, p1, p2, p3, n: int = 20) -> list:
    out = []
    for i in range(n + 1):
        t = i / n
        v = 1 - t
        out.append((v * v * v * p0[0] + 3 * v * v * t * p1[0] + 3 * v * t * t * p2[0] + t * t * t * p3[0],
                    v * v * v * p0[1] + 3 * v * v * t * p1[1] + 3 * v * t * t * p2[1] + t * t * t * p3[1]))
    return out


@lru_cache(maxsize=24)
def _kiot_parts(w: int, h: int, bg, a: float) -> tuple:
    """The frame for an icon of shape a, as large as fits in w x h on bg, painted once per
    size, shape and colour: (picture, mask of the opening, the icon's place, the shadow
    the frame casts into the opening)."""
    k = _ss(w, h)
    canvas, _, opening, box, cast = _paint_kiot(w, h, bg, a, k)
    if k > 1:
        canvas = canvas.resize((w, h), Image.LANCZOS)
        opening = opening.resize((w, h), Image.LANCZOS)
        cast = cast.resize((w, h), Image.LANCZOS)
    x0, y0, x1, y1 = (round(v / k) for v in box)
    return canvas, opening, (x0, y0, x1, y1), cast


def warm(w: int, h: int, bg) -> None:
    """Paint ahead of time the frame most icons take at this size."""
    _kiot_parts(w, h, _rgb(bg), 0.75)


def _blank_shape(w: int, h: int) -> float:
    """The shape of opening that makes a frame fill w x h (for a saint without a picture)."""
    target = h / max(1, w)
    a = 0.75
    for _ in range(3):
        top = _proportions(a)[2]
        a = max(0.5, min(1.6, (1 - 2 * SIDE) / max(0.2, target - top - FOOT)))
    return round(a * 20) / 20


def kiot(icon, w: int, h: int, bg):
    """An icon in a gilded frame made to its shape, centred in w x h pixels of the colour bg."""
    bg = _rgb(bg)
    src = icon.convert("RGB") if icon.mode != "RGB" else icon
    # icons of nearly the same shape share one frame (painted once): the shape in steps of 1/20
    a = max(0.4, min(2.5, round(src.width / src.height * 20) / 20))
    frame, opening, (x0, y0, x1, y1), cast = _kiot_parts(w, h, bg, a)
    framed = frame.copy()
    layer = Image.new("RGB", (w, h), MAT)
    tw, th = max(1, x1 - x0), max(1, y1 - y0)
    sc = max(tw / src.width, th / src.height)          # the icon fills its place
    pic = src.resize((max(1, round(src.width * sc)), max(1, round(src.height * sc))), Image.LANCZOS)
    layer.paste(pic, (x0 + (tw - pic.width) // 2, y0 + (th - pic.height) // 2))
    framed.paste(layer, (0, 0), opening)
    framed.paste((0, 0, 0), (0, 0), cast)
    return framed


@lru_cache(maxsize=32)
def icon_blank(initial: str, w: int, h: int, bg, label: str = ""):
    """For a saint without a picture: gold leaf, a halo and the saint's initial,
    with the name below in red letters, in the same gilded frame."""
    bg = _rgb(bg)
    frame, opening, (x0, y0, x1, y1), cast = _kiot_parts(w, h, bg, _blank_shape(w, h))
    k = _ss(w, h)
    leaf = gold_leaf(w * k, h * k, squares=True)
    d = ImageDraw.Draw(leaf)
    x0, y0, x1, y1 = x0 * k, y0 * k, x1 * k, y1 * k
    iw, ih = x1 - x0, y1 - y0
    r = min(iw, ih) * 0.3
    cx, cy = (x0 + x1) / 2, y0 + ih * (0.42 if label else 0.5)
    r = max(1.0, r)
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=_mix(GOLD_LIGHT, GOLD, 0.35), outline=GOLD_DARK,
              width=max(1, min(k * 2, round(r / 3))))
    if r > 4 * k:
        d.ellipse([cx - r + 3 * k, cy - r + 3 * k, cx + r - 3 * k, cy + r - 3 * k], outline=CINNABAR, width=max(1, k))
    letter = (initial or "☦")[:1].upper()
    f = font(max(8, int(r * 1.15)))
    try:
        d.text((cx, cy + r * 0.04), letter, font=f, fill=CINNABAR, anchor="mm")
    except Exception:
        d.text((cx - r / 3, cy - r / 2), letter, font=f, fill=CINNABAR)
    if label:
        text = label.upper()
        size = max(8, int(ih * 0.085))
        while size > 8:
            f2 = font(size)
            try:
                tw = d.textlength(text, font=f2)
            except Exception:
                tw = size * len(text) * 0.6
            if tw <= iw * 0.88:
                break
            size -= k
        try:
            d.text((cx, y1 - ih * 0.1), text, font=font(size), fill=CINNABAR, anchor="mm")
        except Exception:
            pass
    if k > 1:
        leaf = leaf.resize((w, h), Image.LANCZOS)
    canvas = frame.copy()
    canvas.paste(leaf, (0, 0), opening)
    canvas.paste((0, 0, 0), (0, 0), cast)
    return canvas


@lru_cache(maxsize=8)
def cross_headpiece(w: int, h: int, bg, glow=None):
    """A gilded three-bar Orthodox cross between two ornamental rules, like the headpiece
    of a page in a service book (above the hymns, and in the icon view)."""
    W, H = w * S, h * S
    canvas = Image.new("RGB", (W, H), _rgb(bg))
    if glow is not None:
        halo = Image.new("L", (W, H), 0)
        hd = ImageDraw.Draw(halo)
        rx, ry = H * 0.75, H * 0.32
        hd.ellipse([W / 2 - rx, H / 2 - ry, W / 2 + rx, H / 2 + ry], fill=80)
        halo = halo.filter(ImageFilter.GaussianBlur(radius=H * 0.12))
        canvas.paste(_rgb(glow), (0, 0), halo)
    ch = H * 0.9
    top = (H - ch) / 2
    cx = W / 2
    t = ch * 0.1
    m = Image.new("L", (W, H), 0)
    d = ImageDraw.Draw(m)
    d.rectangle([cx - t / 2, top, cx + t / 2, top + ch], fill=255)                       # the upright
    y1 = top + ch * 0.15
    d.rectangle([cx - ch * 0.17, y1 - t * 0.42, cx + ch * 0.17, y1 + t * 0.42], fill=255)  # the title board
    y2 = top + ch * 0.35
    d.rectangle([cx - ch * 0.31, y2 - t / 2, cx + ch * 0.31, y2 + t / 2], fill=255)      # the crossbar
    y3, half, tilt = top + ch * 0.74, ch * 0.2, ch * 0.075                              # the footrest, raised
    d.polygon([(cx - half, y3 - tilt - t * 0.42), (cx + half, y3 + tilt - t * 0.42),     # on the left
               (cx + half, y3 + tilt + t * 0.42), (cx - half, y3 - tilt + t * 0.42)], fill=255)
    # the rules on either side, ending in diamonds
    gap, rule_y = ch * 0.42, y2
    lw = max(S, round(t * 0.22))
    for sgn in (-1, 1):
        x_in, x_out = cx + sgn * gap, (W * 0.06 if sgn < 0 else W * 0.94)
        a, b = sorted((x_in, x_out))
        d.rectangle([a, rule_y - t * 0.55 - lw / 2, b, rule_y - t * 0.55 + lw / 2], fill=255)
        d.rectangle([a, rule_y + t * 0.55 - lw / 2, b, rule_y + t * 0.55 + lw / 2], fill=255)
        r = t * 0.9
        d.polygon([(x_out, rule_y - r), (x_out + r * 0.8, rule_y), (x_out, rule_y + r), (x_out - r * 0.8, rule_y)],
                  fill=255)
        mid = (x_in + x_out) / 2
        r2 = t * 0.45
        d.polygon([(mid, rule_y - r2), (mid + r2, rule_y), (mid, rule_y + r2), (mid - r2, rule_y)], fill=255)
    shadow = ImageChops.offset(m.filter(ImageFilter.GaussianBlur(radius=S * 1.5)), S, S).point(lambda v: int(v * 0.7))
    canvas.paste((0, 0, 0), (0, 0), shadow)
    canvas.paste(gold_leaf(W, H), (0, 0), m)
    canvas.paste(GOLD_LIGHT, (0, 0), _edge(ImageChops.subtract(m, _edge(m, S)), max(1, S // 2)))
    canvas.paste(GOLD_EDGE, (0, 0), _edge(m, max(1, S // 2 + 1)))
    return canvas.resize((w, h), Image.LANCZOS)


__all__ = ["available", "cross_headpiece", "font", "gold_leaf", "icon_blank", "kiot", "warm"]
