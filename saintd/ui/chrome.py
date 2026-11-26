"""The window chrome: title bar, left tab rail and status bar."""

from __future__ import annotations

import datetime as dt

from rich.cells import cell_len
from rich.style import Style
from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.css.query import NoMatches
from textual.message import Message
from textual.reactive import reactive
from textual.widgets import Button, Static

from .. import __version__, art, term
from ..graphics import Emblem
from ..sources import civil_to_church
from .common import MONTH_ABBR, glyphs, set_content

TABS = [("home", "HOME"), ("search", "SEARCH"), ("focus", "FOCUS"), ("settings", "SETTINGS")]
FKEYS = {"home": "F1", "search": "F2", "focus": "F3", "settings": "F4"}


def _hex(c: str) -> tuple[int, int, int]:
    c = c.lstrip("#")
    return int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)


def _mix(a, b, t: float) -> tuple[int, int, int]:
    return tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3))     # type: ignore[return-value]


def gilded(width: int, primary: str, secondary: str) -> list[str]:
    """Background colours for a band of `width` cells: the theme's colour as burnished
    leaf — shaded at the ends, warmed by the second colour, with a sheen."""
    p, s = _hex(primary), _hex(secondary)
    stops = [(0.0, _mix(p, (0, 0, 0), 0.22)), (0.18, p), (0.38, _mix(p, s, 0.5)),
             (0.52, _mix(p, (255, 255, 255), 0.16)), (0.7, p), (0.86, _mix(p, s, 0.3)),
             (1.0, _mix(p, (0, 0, 0), 0.25))]
    out = []
    for x in range(width):
        t = x / max(1, width - 1)
        for (t0, c0), (t1, c1) in zip(stops, stops[1:]):
            if t0 <= t <= t1:
                c = _mix(c0, c1, (t - t0) / ((t1 - t0) or 1))
                break
        out.append("#%02x%02x%02x" % c)
    return out


class TitleBar(Horizontal):
    def compose(self) -> ComposeResult:
        yield Static(id="tb")

    def on_mount(self) -> None:
        self.refresh_bar()
        self.set_interval(30, self.refresh_bar)

    def on_resize(self) -> None:
        self.refresh_bar()

    def refresh_bar(self) -> None:
        """Name, today's date (civil and church) and the size of the directory,
        shortened to fit narrow terminals."""
        if not self.is_attached:
            return
        g = glyphs(self.app)
        width = self.app.size.width
        today = dt.date.today()
        cm, cd = civil_to_church(today)
        left = Text()
        left.append(f" {g['cross']} ", style="bold")
        left.append("SAINT DIRECTORY" if width >= 70 else "SAINTD", style="bold")
        if width >= 110:
            left.append(f" {g['bar']} v{__version__}", style="dim")
        cal = self.app.ctx.cfg["calendar"]
        day = f"{today.day} {MONTH_ABBR[today.month - 1].upper()}"
        church = f"{cd} {MONTH_ABBR[cm - 1].upper()}"
        if width >= 110:
            mid = f"{today.strftime('%a').upper()} {day} {today.year}  {g['sep']}  " + (
                f"CHURCH DATE {church} (OLD CAL.)" if cal == "old" else f"OLD CAL. {church}")
        elif width >= 80:
            mid = f"{today.strftime('%a').upper()} {day}  {g['sep']}  " + (
                f"CHURCH {church}" if cal == "old" else f"OLD {church}")
        else:
            mid = f"{today.strftime('%a').upper()} {day}"
        try:
            st = self.app.ctx.db.stats()
            right = f"{g['dot']} {st['people']:,} SAINTS " if width >= 80 else f"{st['people']:,} "
        except Exception:
            right = ""
        # one line: name on the left, the date in the middle, the count on the right
        lw, mw, rw = cell_len(left.plain), cell_len(mid), cell_len(right)
        start = max(lw + 2, (width - mw) // 2)
        if start + mw + rw + 1 > width:
            mid, mw = "", 0
            start = lw
        line = Text(no_wrap=True, overflow="crop")
        line.append_text(left)
        line.append(" " * (start - lw))
        line.append(mid, style="bold")
        line.append(" " * max(1, width - start - mw - rw))
        line.append(right, style="bold")
        theme = self.app.current_theme
        if term.current().truecolor and theme.primary and theme.secondary:
            for x, c in enumerate(gilded(width, theme.primary, theme.secondary)):
                line.stylize(Style(bgcolor=c), x, x + 1)          # a band of burnished gold leaf
        set_content(self.query_one("#tb", Static), line, layout=False)


class RailTab(Static):
    def __init__(self, tab_id: str, label: str) -> None:
        super().__init__(id=f"tab-{tab_id}", classes="rail-tab")
        self.tab_id = tab_id
        self.label = label

    def render_label(self, active: bool) -> None:
        g = glyphs(self.app)
        cw = self.content_size.width or 16
        t = Text(no_wrap=True, overflow="crop")
        if cw < 10:                                   # icon-only tab column on small terminals
            t.append(g[self.tab_id], style="bold" if active else "")
            set_content(self, t, layout=False)
            return
        mark = g["arrow"] if active else " "
        base = f"{mark} {g[self.tab_id]}  "
        t.append(base + self.label)
        longest = max(len(label) for _, label in TABS)
        if cw - len(base) - longest - 3 >= 0:          # room for the F-key hint on every tab
            t.append(" " * max(1, cw - len(t.plain) - 2) + FKEYS[self.tab_id], style="dim")
        set_content(self, t, layout=False)

    def on_resize(self) -> None:
        self.render_label(self.has_class("-active"))

    def on_click(self) -> None:
        self.app.show_tab(self.tab_id, focus_page=True)


class TabRail(Vertical, can_focus=True):
    """Column of tabs. While focused: Tab/Shift+Tab or Up/Down move between
    tabs; Enter or Right steps into the page."""

    BINDINGS = [
        Binding("tab", "move(1)", "Next tab", show=False),
        Binding("shift+tab", "move(-1)", "Previous tab", show=False),
        Binding("down", "move(1)", show=False),
        Binding("up", "move(-1)", show=False),
        Binding("enter", "enter_page", "Open", show=False),
        Binding("right", "enter_page", show=False),
    ]

    active: reactive[str] = reactive("home")

    class Moved(Message):
        def __init__(self, tab: str) -> None:
            super().__init__()
            self.tab = tab

    def compose(self) -> ComposeResult:
        yield Static("", id="rail-head")
        yield Emblem(id="rail-emblem")
        for tid, label in TABS:
            yield RailTab(tid, label)
        yield Static("", id="rail-spacer")
        yield Static("", id="rail-info")

    def on_mount(self) -> None:
        self.refresh_tabs()
        self.update_emblem()

    def update_emblem(self) -> None:
        """The gilded double-headed eagle in terminals that show true images, the text head elsewhere."""
        mode = getattr(self.app, "graphics_mode", "off")
        fancy = mode in ("kitty", "sixel") and art.available()
        self.set_class(fancy, "-fancy")
        em = self.query_one(Emblem)
        try:
            em.glow = _hex(self.app.current_theme.primary)
        except Exception:
            em.glow = None
        em.show(None, mode=mode)
        em._sync_sixel()                    # Sixel: paint it again in the new colours
        em.refresh()

    def pulse(self, strength: float = 1.0) -> None:
        """The light behind the eagle swells and fades (Kitty, Ghostty): a new tab is open."""
        try:
            self.query_one(Emblem).pulse(strength)
        except NoMatches:
            pass

    def watch_active(self, _old: str, _new: str) -> None:
        self.refresh_tabs()

    def refresh_tabs(self) -> None:
        g = glyphs(self.app)
        set_content(self.query_one("#rail-head", Static), f"{g['rule'] * 3} TABS {g['rule'] * 3}", layout=False)
        for tab in self.query(RailTab):
            on = tab.tab_id == self.active
            tab.set_class(on, "-active")
            tab.render_label(on)

    async def on_key(self, event: events.Key) -> None:
        """While the tab column has the cursor, the open page's own keys still
        work: T (today), N (a random saint), [ ] (previous / next), F (save)..."""
        if event.key in _keys_of(self) or event.key in _keys_of(self.app):
            return
        page = self.app.page()
        if page is None or not getattr(page, "is_built", True):
            return
        for b in getattr(page, "BINDINGS", ()):
            key, action = (b.key, b.action) if isinstance(b, Binding) else (b[0], b[1])
            if event.key in [k.strip() for k in key.split(",")]:
                event.stop()
                event.prevent_default()
                await page.run_action(action)
                return

    def action_move(self, step: int) -> None:
        ids = [t for t, _ in TABS]
        i = (ids.index(self.active) + step) % len(ids)
        self.app.show_tab(ids[i], focus_page=False)

    def action_enter_page(self) -> None:
        self.app.focus_page()

    def set_info(self, text: str) -> None:
        set_content(self.query_one("#rail-info", Static), text)


def _keys_of(node) -> set[str]:
    out: set[str] = set()
    for b in getattr(node, "BINDINGS", ()):
        key = b.key if isinstance(b, Binding) else b[0]
        out.update(k.strip() for k in key.split(","))
    return out


class ReaderBar(Horizontal):
    """Shown while something is being read aloud: what, how far, with which
    voice, and buttons for the mouse (the keys are P, X, , . and + -)."""

    def compose(self) -> ComposeResult:
        yield Static(id="rb-info")
        for bid, label in (("rb-prev", "<<"), ("rb-play", "Pause"), ("rb-stop", "Stop"), ("rb-next", ">>"),
                           ("rb-slower", "-"), ("rb-faster", "+")):
            b = Button(label, id=bid, compact=True)
            b.can_focus = False                   # the bar never takes the cursor from the page
            yield b

    def show_reader(self, reader, g: dict) -> None:
        on = reader.active
        if self.display != on:
            self.display = on
        if not on:
            return
        t = Text(no_wrap=True, overflow="ellipsis")
        state = {"loading": "PREPARING", "playing": "READING", "paused": "PAUSED"}.get(reader.state, "")
        t.append(f" {g['hymn']} {state} ", style="reverse bold")
        t.append(f"  {reader.title}", style="bold")
        n = len(reader.chunks)
        if n:
            i = min(reader.index + 1, n)
            filled = int(10 * i / n)
            t.append(f"   {g['full'] * filled}{g['empty'] * (10 - filled)} {i}/{n}", style="")
        eng = reader.engine
        if eng is not None:
            voice = eng.voice_label(reader.voice).split(" — ")[0] if reader.voice else ""
            short = eng.label.split(" (")[0]
            t.append(f"   {short}{' ' + g['sep'] + ' ' + voice if voice else ''} {g['sep']} {reader.rate:g}×",
                     style="dim")
        set_content(self.query_one("#rb-info", Static), t, layout=False)
        play = self.query_one("#rb-play", Button)
        label = "Resume" if reader.state == "paused" else "Pause"
        if str(play.label) != label:
            play.label = label

    def on_button_pressed(self, ev: Button.Pressed) -> None:
        ev.stop()
        app = self.app
        {"rb-prev": lambda: app.action_read_skip(-1), "rb-next": lambda: app.action_read_skip(1),
         "rb-play": app.reader.toggle, "rb-stop": app.action_stop_reading,
         "rb-slower": lambda: app.action_read_speed(-1),
         "rb-faster": lambda: app.action_read_speed(1)}.get(ev.button.id, lambda: None)()


class StatusBar(Horizontal):
    def compose(self) -> ComposeResult:
        yield Static(id="sb-keys")
        yield Static(id="sb-sync")

    def on_mount(self) -> None:
        self.set_keys("")

    def set_keys(self, extra: str) -> None:
        self._extra = extra
        width = self.app.size.width
        t = Text()
        keys = (("F1", "Home"), ("F2", "Search"), ("F3", "Focus"), ("F4", "Settings"), ("?", "Help"),
                ("^B", "Build"), ("Esc", "Tabs"), ("^Q", "Quit"))
        if width < 110:
            keys = (("F1", "Home"), ("F2", "Find"), ("F3", "Focus"), ("F4", "Set"), ("?", "Help"), ("^Q", "Quit"))
        for k, v in keys:
            t.append(f" {k} ", style="reverse bold")
            t.append(f" {v} ")
        if extra and width >= 170:
            t.append("  " + extra, style="dim")
        try:
            set_content(self.query_one("#sb-keys", Static), t)
        except NoMatches:
            pass

    def on_resize(self) -> None:
        self.set_keys(getattr(self, "_extra", ""))

    def set_sync(self, text: Text | str) -> None:
        try:
            set_content(self.query_one("#sb-sync", Static), text, layout=False)
        except NoMatches:          # shutting down
            pass
