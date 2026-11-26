"""The double-headed eagle at the head of the tab column, for terminals that
show true images (Kitty, Ghostty, Sixel terminals).

It is the eagle of the flag of the Church of Greece (the Byzantine eagle of the
Ecumenical Patriarchate and Mount Athos), as it is drawn there: black lines on
the flag's yellow, the closed crown floating above the two heads, the sword in
the eagle's right claw and the orb with its cross in the left. Only the flag's
yellow ground round it is taken away (assets/eagle.png).

The light (`frame`, `frames`) comes from behind the eagle, as from a lamp hung
behind a carving: a soft bloom round the silhouette and shafts of light breaking
out between the wings, the heads and the crown. It is painted in steps, from the
quiet glow at rest to the height of a pulse, so the tab column can make it swell
and fade by switching between pictures the terminal already holds."""

from __future__ import annotations

import math
from functools import lru_cache
from pathlib import Path

from . import art

try:
    from PIL import Image, ImageChops, ImageDraw, ImageFilter
except Exception:                       # pragma: no cover - Pillow comes with textual-image
    Image = None

ASSET = Path(__file__).with_name("assets") / "eagle.png"
CENTRE = (0.5, 0.57)                    # where the light behind it is strongest (the breast), in shares of the eagle
LEVELS = 16                             # steps of light, from rest (0) to the height of a pulse
MARGIN = 0.04


@lru_cache(maxsize=1)
def _picture():
    with Image.open(ASSET) as im:
        return im.convert("RGBA")


@lru_cache(maxsize=6)
def _eagle(w: int, h: int):
    """The eagle alone, w x h pixels with a transparent ground: (RGBA picture, centre of the light)."""
    src = _picture()
    scale = min(w * (1 - 2 * MARGIN) / src.width, h * (1 - 2 * MARGIN) / src.height)
    tw, th = max(1, round(src.width * scale)), max(1, round(src.height * scale))
    x0, y0 = (w - tw) // 2, (h - th) // 2
    im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    im.paste(src.resize((tw, th), Image.LANCZOS), (x0, y0))
    return im, (x0 + tw * CENTRE[0], y0 + th * CENTRE[1])


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
    return Image is not None and ASSET.is_file()


__all__ = ["LEVELS", "available", "frame", "frames"]
