"""Pictures for terminals that show true images (Kitty, Ghostty, Sixel
terminals): saint icons set in a gilded kiot (the arched case an icon stands
in, from a photograph in assets/), a painted "icon blank" (gold leaf, halo and
initial) for saints without a picture, and a gilded Orthodox cross set between
two rules as a headpiece (the double-headed eagle of the tab column is in
eagle.py).

What is painted is drawn at a few times the size and scaled down, which gives
smooth edges; every picture is kept so it is made once."""

from __future__ import annotations

import math
import os
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

_WINFONTS = Path(os.environ.get("SystemRoot") or "C:/Windows") / "Fonts"
FONTS = [
    # Linux
    "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSerif-Bold.ttf",
    "/usr/share/fonts/truetype/noto/NotoSerif-Bold.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSerifBold.ttf",
    "/usr/share/fonts/truetype/ubuntu/Ubuntu-B.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    # macOS
    "/System/Library/Fonts/Supplemental/Georgia Bold.ttf",
    "/System/Library/Fonts/Supplemental/Times New Roman Bold.ttf",
    "/Library/Fonts/Georgia Bold.ttf",
    # Windows
    str(_WINFONTS / "georgiab.ttf"),
    str(_WINFONTS / "timesbd.ttf"),
]


def available() -> bool:
    return Image is not None and (ASSETS / "kiot.png").is_file()


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


def _ss(w: int, h: int) -> int:
    """Supersampling for a picture of this size (big pictures need less)."""
    m = max(w, h)
    return 3 if m <= 420 else 2 if m <= 840 else 1


# ---------------------------------------------------------------- the kiot
#
# The frame is a photograph of a gilded kiot (the case an icon stands in): a round
# arch over straight sides, rows of beads and a running vine in relief, the
# three-bar cross under the arch, the head of the opening cut in two arches that
# meet in a point under the cross, a ruby at the top and silver rosettes. It is
# used as it is (assets/kiot.png, with the opening's shape in assets/kiot-opening.png);
# for an icon of another shape only the straight part of the sides is drawn out or
# pressed in, so the arch, the cross and the corners are never distorted.

ASSETS = Path(__file__).with_name("assets")
OPENING = (109, 273, 700, 1052)     # in the frame's picture: the opening's left, top (its crowns), right, foot
BAND = (470, 1040)                  # the straight part of the sides, which may be drawn out or pressed in
SQUEEZE, STRETCH = 0.35, 2.0        # how far it may be


@lru_cache(maxsize=1)
def _kiot_source():
    with Image.open(ASSETS / "kiot.png") as f, Image.open(ASSETS / "kiot-opening.png") as o:
        return f.convert("RGBA"), o.convert("L")


@lru_cache(maxsize=8)
def _kiot_shaped(a: float):
    """The frame at full size with its opening as near the shape a (width / height) as the
    frame allows: (frame, mask of the opening, the icon's place)."""
    frame, hole = _kiot_source()
    W, H = frame.size
    band = BAND[1] - BAND[0]
    want = (OPENING[2] - OPENING[0]) / a - (OPENING[3] - OPENING[1])     # how much taller the opening should be
    new = round(max(band * SQUEEZE, min(band * STRETCH, band + want)))
    if new == band:
        return frame, hole, OPENING
    out_f, out_h = Image.new("RGBA", (W, H - band + new)), Image.new("L", (W, H - band + new))
    for src, dst in ((frame, out_f), (hole, out_h)):
        dst.paste(src.crop((0, 0, W, BAND[0])), (0, 0))
        dst.paste(src.crop((0, BAND[0], W, BAND[1])).resize((W, new), Image.LANCZOS), (0, BAND[0]))
        dst.paste(src.crop((0, BAND[1], W, H)), (0, BAND[0] + new))
    return out_f, out_h, (OPENING[0], OPENING[1], OPENING[2], OPENING[3] + new - band)


@lru_cache(maxsize=24)
def _kiot_parts(w: int, h: int, bg, a: float) -> tuple:
    """The frame for an icon of shape a, as large as fits in w x h on bg, made once per size,
    shape and colour: (the ground with the frame's shadow on it, the frame, the mask of its
    opening, the icon's place, the shadow the frame casts into the opening)."""
    frame, hole, (ox0, oy0, ox1, oy1) = _kiot_shaped(a)
    pad = max(1, round(min(w, h) * 0.03))
    scale = min((w - 2 * pad) / frame.width, (h - 2 * pad) / frame.height)
    fw, fh = max(1, round(frame.width * scale)), max(1, round(frame.height * scale))
    x0, y0 = (w - fw) // 2, (h - fh) // 2
    small = frame.resize((fw, fh), Image.LANCZOS)
    pic = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    pic.paste(small, (x0, y0))
    opening = Image.new("L", (w, h), 0)
    opening.paste(hole.resize((fw, fh), Image.LANCZOS), (x0, y0))
    alpha = pic.split()[3]
    # the frame's shadow on the ground, below and to the right
    ground = Image.new("RGB", (w, h), _rgb(bg))
    u = max(1.0, fw / 100)
    whole = ImageChops.lighter(alpha, opening).filter(ImageFilter.GaussianBlur(max(1.0, 1.4 * u)))
    ground.paste((0, 0, 0), (0, 0), ImageChops.offset(whole, round(0.7 * u), round(1.0 * u)).point(lambda v: v * 140 // 255))
    # and the shadow it casts on the icon, deepest along the top and the left
    cast = ImageChops.offset(alpha, round(0.5 * u), round(0.7 * u)).filter(ImageFilter.GaussianBlur(max(0.8, 1.1 * u)))
    cast = ImageChops.multiply(cast, opening).point(lambda v: v * 170 // 255)
    box = (x0 + ox0 * scale, y0 + oy0 * scale, x0 + ox1 * scale, y0 + oy1 * scale)
    return ground, pic, opening, tuple(round(v) for v in box), cast


def warm(w: int, h: int, bg) -> None:
    """Make ahead of time the frame most icons take at this size."""
    _kiot_parts(w, h, _rgb(bg), 0.75)


def _framed(layer, w: int, h: int, bg, a: float):
    """layer (w x h, the icon or the icon blank in the opening's place) set in the frame."""
    ground, pic, opening, _, cast = _kiot_parts(w, h, bg, a)
    out = ground.copy()
    out.paste(layer, (0, 0), opening)
    out.paste(pic, (0, 0), pic)
    out.paste((0, 0, 0), (0, 0), cast)
    return out


def kiot(icon, w: int, h: int, bg):
    """An icon in the gilded frame, made to its shape, centred in w x h pixels of the colour bg."""
    bg = _rgb(bg)
    src = icon.convert("RGB") if icon.mode != "RGB" else icon
    # icons of nearly the same shape share one frame (made once): the shape in steps of 1/20
    a = max(0.4, min(2.5, round(src.width / src.height * 20) / 20))
    x0, y0, x1, y1 = _kiot_parts(w, h, bg, a)[3]
    tw, th = max(1, x1 - x0), max(1, y1 - y0)
    fill = max(tw / src.width, th / src.height)          # the icon fills its place ...
    fit = min(tw / src.width, th / src.height)
    sc = fill if fill / fit <= 1.12 else fit             # ... unless its shape is far from the frame's
    pic = src.resize((max(1, round(src.width * sc)), max(1, round(src.height * sc))), Image.LANCZOS)
    layer = Image.new("RGB", (w, h), MAT)
    layer.paste(pic, (x0 + (tw - pic.width) // 2, y0 + (th - pic.height) // 2))
    return _framed(layer, w, h, bg, a)


def _blank_shape(w: int, h: int) -> float:
    """The shape of opening that makes the frame fill w x h (for a saint without a picture)."""
    frame, _ = _kiot_source()
    ow, oh = OPENING[2] - OPENING[0], OPENING[3] - OPENING[1]
    rest = frame.height - oh                              # the frame's height besides its opening
    target = frame.width * h / max(1, w)                  # the frame's height that fills w x h
    return max(0.5, min(1.6, round(ow / max(1.0, target - rest) * 20) / 20))


@lru_cache(maxsize=32)
def icon_blank(initial: str, w: int, h: int, bg, label: str = ""):
    """For a saint without a picture: gold leaf, a halo and the saint's initial,
    with the name below in red letters, in the same gilded frame."""
    bg = _rgb(bg)
    a = _blank_shape(w, h)
    x0, y0, x1, y1 = _kiot_parts(w, h, bg, a)[3]
    k = _ss(w, h)
    leaf = gold_leaf(w * k, h * k, squares=True)
    d = ImageDraw.Draw(leaf)
    x0, y0, x1, y1 = x0 * k, y0 * k, x1 * k, y1 * k
    iw, ih = x1 - x0, y1 - y0
    r = max(1.0, min(iw, ih) * 0.3)
    cx, cy = (x0 + x1) / 2, y0 + ih * (0.46 if label else 0.52)
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
    return _framed(leaf, w, h, bg, a)


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
