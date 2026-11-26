"""Small widgets shared by the pages."""

from __future__ import annotations

from rich.console import RenderableType
from rich.text import Text
from textual.widget import Widget


class FitText(Widget):
    """Text cut to the widget's size, ending in "…" when there is more: a panel
    can give it whatever room is left and it fills exactly that."""

    DEFAULT_CSS = "FitText { height: 1fr; }"

    def __init__(self, *, id: str | None = None, classes: str | None = None) -> None:
        super().__init__(id=id, classes=classes)
        self._text = Text("")

    def set_text(self, text: Text | str) -> None:
        t = text if isinstance(text, Text) else Text(text)
        if t == self._text and t.plain == self._text.plain:
            return
        self._text = t
        self.refresh()

    @property
    def text(self) -> Text:
        return self._text

    def render(self) -> RenderableType:
        w, h = self.content_size.width, self.content_size.height
        if w <= 0 or h <= 0:
            return Text("")
        lines = self._text.wrap(self.app.console, w)
        if len(lines) > h:
            lines = lines[:h]
            last = lines[-1]
            last.rstrip()
            if last.cell_len >= w:
                last.truncate(max(0, w - 1))
            last.rstrip()
            last.append("…", style="dim")
        return Text("\n").join(lines)


def fit_lines(text: str, width: int, rows: int) -> list[str]:
    """Plain text wrapped to `width`, at most `rows` lines (the last ends in … when cut)."""
    import textwrap
    lines: list[str] = []
    for para in text.split("\n"):
        lines += textwrap.wrap(para, width) or [""]
    if len(lines) > rows:
        lines = lines[:rows]
        lines[-1] = lines[-1][: max(0, width - 1)].rstrip() + "…"
    return lines
