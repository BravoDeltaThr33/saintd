"""Pictures painted for terminals that show true images (Kitty, Ghostty,
Sixel terminals): saint icons set in a gilded, arched frame like the kiot of
a church, a painted "icon blank" (gold leaf, halo and initial) for saints
without a picture, and a gilded Orthodox cross set between two rules as a
headpiece (the double-headed eagle of the tab column is in eagle.py).

Everything is drawn at three times the size and scaled down, which gives
smooth edges; every picture is kept so it is painted once."""

from __future__ import annotations

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
MAT = (70, 20, 18)                      # the dark red cloth behind an icon in its frame
CINNABAR = (150, 32, 22)
GEM = (178, 34, 30)

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


def _arched(size: tuple[int, int], box, arch: float):
    """A mask: a rectangle whose top is a half-ellipse (an arched niche)."""
    m = Image.new("L", size, 0)
    d = ImageDraw.Draw(m)
    x0, y0, x1, y1 = box
    arch = max(0.0, min(arch, (x1 - x0) / 2, (y1 - y0) / 2))
    d.rectangle([x0, y0 + arch, x1, y1], fill=255)
    if arch > 0:
        d.ellipse([x0, y0, x1, y0 + 2 * arch], fill=255)
    return m


def _edge(mask, width: int, inside: bool = True):
    """The band of a mask's border, `width` pixels wide (inside or outside the shape)."""
    k = 2 * width + 1
    if inside:
        return ImageChops.subtract(mask, mask.filter(ImageFilter.MinFilter(k)))
    return ImageChops.subtract(mask.filter(ImageFilter.MaxFilter(k)), mask)


def _ss(w: int, h: int) -> int:
    """Supersampling for a picture of this size (big pictures need less)."""
    m = max(w, h)
    return 3 if m <= 420 else 2 if m <= 840 else 1


def _geometry(w: int, h: int) -> tuple[int, int]:
    """(margin for the shadow, width of the gilding) in pixels, for a frame of w x h."""
    return max(1, round(min(w, h) * 0.03)), max(2, round(min(w, h) * 0.07))


@lru_cache(maxsize=24)
def _frame_parts(w: int, h: int, bg, arch: int | None = None, pad: int | None = None,
                 fw: int | None = None) -> tuple:
    """The frame at its final size: (picture, mask of the opening, box of the opening,
    top of the opening's rectangle) — painted once per size and colour."""
    k = _ss(w, h)
    canvas, inner, box, rect_top = _frame(w, h, bg, k, arch, pad, fw)
    small_inner = inner.resize((w, h), Image.LANCZOS) if k > 1 else inner
    x0, y0, x1, y1 = (round(v / k) for v in box)
    small = canvas.resize((w, h), Image.LANCZOS) if k > 1 else canvas
    return small, small_inner, (x0, y0, x1, y1), round(rect_top / k)


def _frame(w: int, h: int, bg, k: int = S, arch: float | None = None, pad: int | None = None,
           fw: int | None = None) -> tuple:
    """Paint the gilded arched frame, k times larger than w x h; returns (canvas, mask of
    the opening, box of the opening, top of the opening's rectangle). arch is the height
    of the opening's arch in final pixels (default: a fifth of the frame)."""
    W, H = w * k, h * k
    canvas = Image.new("RGB", (W, H), _rgb(bg))
    p0, f0 = _geometry(w, h)
    pad = (pad if pad is not None else p0) * k
    fw = (fw if fw is not None else f0) * k
    box = (pad, pad, W - pad - 1 - k, H - pad - 1 - k)            # room for the shadow
    bw, bh = box[2] - box[0], box[3] - box[1]
    inner_arch = arch * k if arch is not None else max(0.0, min(bw * 0.5, bh * 0.2) - fw * 0.9)
    outer_arch = min(bw * 0.5, inner_arch + fw * 0.9)
    outer = _arched((W, H), box, outer_arch)
    inner_box = (box[0] + fw, box[1] + fw, box[2] - fw, box[3] - fw)
    inner = _arched((W, H), inner_box, inner_arch)
    # a soft shadow below and to the right
    shadow = outer.filter(ImageFilter.GaussianBlur(radius=2.5 * k))
    shadow = ImageChops.offset(shadow, k * 2, k * 2).point(lambda v: int(v * 0.65))
    canvas.paste((0, 0, 0), (0, 0), shadow)
    # the gilding, with a bright bevel outside and a dark line where it meets the picture
    frame = ImageChops.subtract(outer, inner)
    canvas.paste(gold_leaf(W, H), (0, 0), frame)
    canvas.paste(GOLD_LIGHT, (0, 0), _edge(ImageChops.subtract(outer, _edge(outer, k)), k))
    canvas.paste(GOLD_EDGE, (0, 0), _edge(outer, k))
    canvas.paste(_mix(GOLD_DARK, GOLD_EDGE, 0.5), (0, 0), _edge(inner, max(1, k), inside=False))
    # a jewel at the top of the arch
    r = fw * 0.42
    cx, cy = (box[0] + box[2]) / 2, box[1] + fw / 2
    d = ImageDraw.Draw(canvas)
    d.ellipse([cx - r - k, cy - r - k, cx + r + k, cy + r + k], fill=GOLD_EDGE)
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=GEM)
    d.ellipse([cx - r * 0.45, cy - r * 0.55, cx - r * 0.05, cy - r * 0.15], fill=(255, 190, 180))
    return canvas, inner, inner_box, inner_box[1] + inner_arch


ARCH = 0.2          # the arch above an icon, as a share of the icon's width


def kiot(icon, w: int, h: int, bg):
    """An icon in a gilded frame that fits it — the icon in the rectangle, a velvet
    arch above it — centred in w x h pixels of the colour bg."""
    bg = _rgb(bg)
    pad, fw = _geometry(w, h)
    src = icon.convert("RGB") if icon.mode != "RGB" else icon
    avail_w, avail_h = w - 2 * (pad + fw) - 2, h - 2 * (pad + fw) - 2
    # icons of nearly the same shape share one frame (painted once): the shape in steps of 1/20
    a = max(0.4, min(2.5, round(src.width / src.height * 20) / 20))
    oh = max(1, int(min(avail_w / a, avail_h / (1 + ARCH * a))))
    ow = max(1, int(a * oh))
    ai = round(ARCH * ow)
    fw_px, fh_px = ow + 2 * (pad + fw) + 2, oh + ai + 2 * (pad + fw) + 2
    frame, inner, (x0, y0, x1, y1), rect_top = _frame_parts(fw_px, fh_px, bg, ai, pad, fw)
    framed = frame.copy()
    layer = Image.new("RGB", (fw_px, fh_px), MAT)
    sc = min(ow / src.width, oh / src.height)
    tw, th = max(1, round(src.width * sc)), max(1, round(src.height * sc))
    top = max(y0, rect_top)
    layer.paste(src.resize((tw, th), Image.LANCZOS), (x0 + (x1 - x0 - tw) // 2, top + (oh - th) // 2))
    framed.paste(layer, (0, 0), inner)
    canvas = Image.new("RGB", (w, h), bg)
    canvas.paste(framed, ((w - fw_px) // 2, (h - fh_px) // 2))
    return canvas


@lru_cache(maxsize=32)
def icon_blank(initial: str, w: int, h: int, bg, label: str = ""):
    """For a saint without a picture: gold leaf, a halo and the saint's initial,
    with the name below in red letters, in the same gilded frame."""
    k = _ss(w, h)
    canvas, inner, (x0, y0, x1, y1), _ = _frame(w, h, _rgb(bg), k)
    W, H = canvas.size
    canvas.paste(gold_leaf(W, H, squares=True), (0, 0), inner)
    iw, ih = x1 - x0, y1 - y0
    d = ImageDraw.Draw(canvas)
    r = min(iw, ih) * 0.3
    cx, cy = (x0 + x1) / 2, y0 + ih * (0.42 if label else 0.5)
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=_mix(GOLD_LIGHT, GOLD, 0.35), outline=GOLD_DARK,
              width=max(2, k * 2))
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
    return canvas.resize((w, h), Image.LANCZOS) if k > 1 else canvas


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


__all__ = ["available", "cross_headpiece", "font", "gold_leaf", "icon_blank", "kiot"]
