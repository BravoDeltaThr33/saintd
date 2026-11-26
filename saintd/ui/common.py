"""Shared glyphs, messages and small helpers."""

from __future__ import annotations

import re

from textual.message import Message

UNICODE = {
    "cross": "☦", "home": "☦", "search": "◎", "focus": "❖", "settings": "⚙",
    "dot": "◉", "bar": "▌", "arrow": "▶", "back": "◀", "refresh": "↻",
    "out": "↗", "toc": "≡", "star": "✦", "full": "▓", "empty": "░",
    "sep": "·", "spin": "◐◓◑◒", "ok": "✓", "bad": "✗", "orn": "❦",
    "rule": "═", "saved": "★", "unsaved": "☆", "life": "✦", "prev": "‹", "next": "›",
    "hymn": "♪", "fast": "•", "book": "¶", "help": "?", "item": "◦",
    "arrows": "← → ↑ ↓", "updown": "↑ ↓", "right": "→", "down": "↓", "enter": "⏎",
    # typikon signs (orthocal feast_level): great feast, vigil, polyeleos, doxology, six stichera
    "rank6": "⊕", "rank5": "✠", "rank4": "✚", "rank3": "≈", "rank2": "∽",
}
ASCII = {
    "cross": "+", "home": "+", "search": "?", "focus": "*", "settings": "#",
    "dot": "*", "bar": "|", "arrow": ">", "back": "<", "refresh": "@",
    "out": "^", "toc": "=", "star": "*", "full": "#", "empty": ".",
    "sep": "-", "spin": "|/-\\", "ok": "OK", "bad": "X", "orn": "~", "rule": "=",
    "saved": "*", "unsaved": "o", "life": "+", "prev": "<", "next": ">",
    "hymn": "~", "fast": ".", "book": ">", "help": "?", "item": "-",
    "arrows": "arrows", "updown": "Up/Down", "right": "Right", "down": "Down", "enter": "Enter",
    "rank6": "@", "rank5": "#", "rank4": "+", "rank3": "=", "rank2": "~",
}

RANK_NAMES = {6: "Great feast", 5: "Vigil", 4: "Polyeleos", 3: "Doxology", 2: "Six stichera"}


def glyphs(app) -> dict:
    try:
        return ASCII if app.ctx.cfg["glyphs"] == "ascii" else UNICODE
    except Exception:
        return UNICODE


def keys(*names: str) -> str:
    """A key binding for both cases of each letter ('r' -> 'r,R'; 'ctrl+r' ->
    'ctrl+r,ctrl+shift+r'), so the controls work whatever the Shift / Caps
    Lock state (terminals with the kitty keyboard protocol report Shift with Ctrl)."""
    out: list[str] = []
    for n in names:
        out.append(n)
        if len(n) == 1 and n.isalpha():
            out.append(n.upper() if n.islower() else n.lower())
        elif n.startswith("ctrl+") and len(n) == 6 and n[-1].isalpha():
            out.append(f"ctrl+shift+{n[-1]}")
    return ",".join(dict.fromkeys(out))


def set_content(widget, content, layout: bool = True) -> None:
    """Static.update() that does nothing when the content has not changed.

    Pass layout=False for a widget whose size does not depend on its content
    (fixed height, or 1fr width): Textual then repaints just that widget
    instead of laying out the whole screen again."""
    last = getattr(widget, "_saintd_last", None)
    if last is not None and type(last) is type(content) and last == content:
        return
    widget._saintd_last = content
    widget.update(content, layout=layout)


def pack(items: list[str], width: int, sep: str = " · ", indent: str = "  ") -> list[str]:
    """Join items into lines no wider than width (an item is never split)."""
    lines: list[str] = []
    cur = ""
    for it in items:
        if not cur:
            cur = it
        elif len(cur) + len(sep) + len(it) <= width:
            cur += sep + it
        else:
            lines.append(cur)
            cur = indent + it
    if cur:
        lines.append(cur)
    return lines


class LazyPage:
    """Mixin for a tab page that builds its widgets on first use, so the app
    starts quickly. compose() checks `lazy_ready` and yields a small
    placeholder until build() is called; build() recomposes the page and then
    calls built(). when_built(fn) runs fn now, or as soon as the page exists."""

    _lazy_state = "new"                 # new -> building -> built
    _lazy_pending: list | None = None

    @property
    def lazy_ready(self) -> bool:
        """True once build() has been asked for (compose() then yields the real page)."""
        return self._lazy_state != "new"

    @property
    def is_built(self) -> bool:
        return self._lazy_state == "built"

    def built(self) -> None:            # override: finish setting the page up
        pass

    def build(self) -> None:
        if self._lazy_state != "new" or not self.is_attached:
            return
        self._lazy_state = "building"

        async def finish() -> None:
            await self.recompose()
            self._lazy_state = "built"
            self.built()
            pending, self._lazy_pending = self._lazy_pending or [], None
            for fn, focus in pending:
                # a cursor move is dropped if the user has gone to another tab meanwhile
                if focus and not self.is_current_page:
                    continue
                fn()
        self.call_later(finish)

    @property
    def is_current_page(self) -> bool:
        try:
            return self.app.w_pages.current == self.id
        except Exception:
            return True

    def when_built(self, fn, focus: bool = False) -> None:
        """Run fn now, or once the page is built. focus=True marks a cursor
        move, which is skipped if the page is no longer the open tab by then."""
        if self._lazy_state == "built":
            fn()
            return
        self._lazy_pending = [*(self._lazy_pending or []), (fn, focus)]
        self.build()


class OpenSaint(Message):
    def __init__(self, sid: int, context: list[int] | None = None, origin: str = "",
                 total: int | None = None) -> None:
        super().__init__()
        self.sid = sid
        self.context = context or []      # the list the saint was opened from ([ and ] step through it)
        self.origin = origin              # "search" | "home" | "focus" | ...
        self.total = total                # the whole list's length, when only part of it is loaded


class SyncEvent(Message):
    """Progress from the background sync, delivered on the UI thread."""

    def __init__(self, kind: str, stage: str = "", done: int = 0, total: int = 0, detail: str = "",
                 text: str = "") -> None:
        super().__init__()
        self.kind = kind          # stage | progress | log | finished | wait
        self.stage = stage
        self.done = done
        self.total = total
        self.detail = detail
        self.text = text


class DirectoryChanged(Message):
    pass


class FavoritesChanged(Message):
    pass


MONTH_ABBR = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September",
          "October", "November", "December"]
WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def fmt_feast(mmdd: str | None) -> str:
    if not mmdd:
        return ""
    try:
        m, d = mmdd.split("-")
        return f"{MONTH_ABBR[int(m) - 1]} {int(d):2d}"
    except (ValueError, IndexError):
        return ""


_RANKS = re.compile(r"^(?:(?:holy|great|new|venerable|righteous|blessed|hieromartyrs?|martyrs?|virgin-martyrs?|"
                    r"great-martyrs?|venerable-martyrs?|apostles?|prophet(?:ess)?|hierarch|saints?|sts?\.?|"
                    r"st\.?|elder|confessor|hiero-confessor|passion-bearers?|equal-to-the-apostles)\s+)+", re.I)


def short_name(s: dict) -> str:
    """A saint's own name, for the inscription on a painted icon ("Seraphim", "Xenia")."""
    core = (s.get("core") or s.get("name") or "").strip()
    core = _RANKS.sub("", core)
    word = re.split(r",| of | and | the |\(", core)[0].strip()
    first = word.split()[0] if word.split() else ""
    return first[:14]


def short_century(c) -> str:
    if c is None:
        return "?"
    n = abs(int(c))
    suf = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suf}" + (" BC" if c < 0 else "")
