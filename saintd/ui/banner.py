"""Chunky half-block banner lettering with a colour gradient."""

from __future__ import annotations

from rich.color import Color
from rich.style import Style
from rich.text import Text

# 5x5 pixel glyphs; rendered two pixel-rows per text row with half blocks.
GLYPHS = {
    "S": [".####", "#....", ".###.", "....#", "####."],
    "A": [".###.", "#...#", "#####", "#...#", "#...#"],
    "I": ["###", ".#.", ".#.", ".#.", "###"],
    "N": ["#...#", "##..#", "#.#.#", "#..##", "#...#"],
    "T": ["#####", "..#..", "..#..", "..#..", "..#.."],
    "D": ["####.", "#...#", "#...#", "#...#", "####."],
    "R": ["####.", "#...#", "####.", "#..#.", "#...#"],
    "E": ["#####", "#....", "####.", "#....", "#####"],
    "C": [".####", "#....", "#....", "#....", ".####"],
    "O": [".###.", "#...#", "#...#", "#...#", ".###."],
    "Y": ["#...#", ".#.#.", "..#..", "..#..", "..#.."],
    " ": ["..", "..", "..", "..", ".."],
}


def _bitmap(text: str) -> list[str]:
    rows = ["", "", "", "", "", ""]
    for i, ch in enumerate(text.upper()):
        g = GLYPHS.get(ch, GLYPHS[" "])
        for r in range(5):
            rows[r] += g[r] + ("." if i < len(text) - 1 else "")
        rows[5] += "." * (len(g[0]) + (1 if i < len(text) - 1 else 0))
    return rows


def render_banner(text: str, colors: list[str], ascii_only: bool = False) -> Text:
    rows = _bitmap(text)
    width = len(rows[0])
    stops = [Color.parse(c).get_truecolor() for c in colors]

    def color_at(x: int) -> str:
        if len(stops) == 1 or width <= 1:
            r, g, b = stops[0]
            return f"#{r:02x}{g:02x}{b:02x}"
        pos = x / (width - 1) * (len(stops) - 1)
        i = min(int(pos), len(stops) - 2)
        f = pos - i
        a, b_ = stops[i], stops[i + 1]
        r, g, b = (int(a[k] + (b_[k] - a[k]) * f) for k in range(3))
        return f"#{r:02x}{g:02x}{b:02x}"

    out = Text(no_wrap=True, overflow="crop")
    for pair in range(3):
        top, bot = rows[pair * 2], rows[pair * 2 + 1]
        for x in range(width):
            t, b = top[x] == "#", bot[x] == "#"
            if ascii_only:
                ch = "#" if (t or b) else " "
            else:
                ch = "█" if t and b else "▀" if t else "▄" if b else " "
            out.append(ch, Style(color=color_at(x), bold=True))
        if pair < 2:
            out.append("\n")
    return out


def banner_width(text: str) -> int:
    return len(_bitmap(text)[0])
