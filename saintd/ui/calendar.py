"""A month of the Church calendar: typikon signs for the feasts, fast days,
today and the chosen day. Arrow keys move the day, PgUp/PgDn the month."""

from __future__ import annotations

import calendar as _cal
import datetime as dt

from rich.style import Style
from rich.text import Text
from textual.binding import Binding
from textual.events import Click
from textual.message import Message
from textual.reactive import reactive
from textual.widget import Widget

from .common import MONTHS, RANK_NAMES, glyphs, keys

CELL = 4          # characters per day: sign, two digits, space
WEEK_START = 6    # Sunday


class ChurchCalendar(Widget, can_focus=True):
    DEFAULT_CSS = """
    ChurchCalendar { width: 30; height: 8; }
    """

    BINDINGS = [
        Binding("left", "move(-1)", "Previous day", show=False),
        Binding("right", "move(1)", "Next day", show=False),
        Binding("up", "move(-7)", "Week before", show=False),
        Binding("down", "move(7)", "Week after", show=False),
        Binding("pageup", "month(-1)", "Previous month", show=False),
        Binding("pagedown", "month(1)", "Next month", show=False),
        Binding("home", "today", "Today", show=False),
        Binding("enter", "choose", "Open the day", show=False),
    ]

    selected: reactive[dt.date] = reactive(dt.date.today)

    class Selected(Message):
        def __init__(self, calendar: "ChurchCalendar", day: dt.date, chosen: bool = False) -> None:
            super().__init__()
            self.calendar = calendar
            self.day = day
            self.chosen = chosen        # Enter: the user wants the day's list

    def __init__(self, *, id: str | None = None, classes: str | None = None) -> None:
        super().__init__(id=id, classes=classes)
        self.info: dict[dt.date, dict] = {}      # date -> {"rank": int, "fast": int, "title": str}

    # ---------------------------------------------------------------- data
    def set_info(self, info: dict[dt.date, dict]) -> None:
        self.info.update(info)
        self.refresh()

    def _weeks(self) -> list[list[dt.date]]:
        c = _cal.Calendar(firstweekday=WEEK_START)
        return c.monthdatescalendar(self.selected.year, self.selected.month)

    # ---------------------------------------------------------------- drawing
    def watch_selected(self, old: dt.date, new: dt.date) -> None:
        self.refresh()
        if old != new:
            self.post_message(self.Selected(self, new))

    def render(self) -> Text:
        g = glyphs(self.app)
        theme = self.app.current_theme
        fg, primary, secondary = theme.foreground, theme.primary, theme.secondary
        accent, error, bg = theme.accent, theme.error, theme.background
        muted = theme.variables.get("muted", "grey50")
        sel, today = self.selected, dt.date.today()
        width = CELL * 7
        t = Text(no_wrap=True, overflow="crop")
        head = f"{g['prev']} {MONTHS[sel.month - 1]} {sel.year} {g['next']}"
        left = (width - len(head)) // 2
        self._arrows = (left, left + len(head) - 1)          # where ‹ and › are, for mouse clicks
        t.append(head.center(width) + "\n", style=Style(color=secondary, bold=True))
        days = ["Su", "Mo", "Tu", "We", "Th", "Fr", "Sa"]
        for i, d in enumerate(days):
            t.append(f" {d} ", style=Style(color=error if i == 0 else muted, bold=i == 0))
        t.append("\n")
        weeks = self._weeks()
        for wi, week in enumerate(weeks):
            for day in week:
                info = self.info.get(day, {})
                rank = info.get("rank", 0)
                fast = info.get("fast", 0)
                sign = g.get(f"rank{rank}", " ") if rank >= 2 else (g["fast"] if fast else " ")
                if day.month != sel.month:
                    t.append(f"{' '}{day.day:>2} ", style=Style(color=muted, dim=True))
                    continue
                st = Style(color=fg)
                sign_st = Style(color=error if rank >= 5 else accent if rank >= 3 else muted, bold=rank >= 4)
                if day.weekday() == 6:
                    st += Style(bold=True, color=error)
                elif rank >= 5:
                    st += Style(bold=True, color=error)
                elif fast:
                    st += Style(color=secondary, italic=True)
                if day == today:
                    st += Style(underline=True, bold=True)
                if day == sel:
                    st = Style(color=bg, bgcolor=primary if self.has_focus else secondary, bold=True)
                    sign_st = st
                t.append(sign, style=sign_st)
                t.append(f"{day.day:>2}", style=st)
                t.append(" ")
            if wi < len(weeks) - 1:
                t.append("\n")
        return t

    def legend(self) -> Text:
        g = glyphs(self.app)
        t = Text(no_wrap=True, overflow="crop")
        rows = [(6, 5), (4, 3), (2, "fast")]            # fits the 30 columns of the calendar
        for i, row in enumerate(rows):
            for j, item in enumerate(row):
                sign, name = (g["fast"], "fast day") if item == "fast" else (g[f"rank{item}"], RANK_NAMES[item].lower())
                t.append(sign, style="bold")
                t.append(f" {name}".ljust(15) if j == 0 else f" {name}", style="dim")
            if i < len(rows) - 1:
                t.append("\n")
        return t

    # ---------------------------------------------------------------- input
    def action_move(self, days: int) -> None:
        self.selected = self.selected + dt.timedelta(days=days)

    def action_month(self, step: int) -> None:
        y, m = self.selected.year, self.selected.month + step
        while m < 1:
            y, m = y - 1, m + 12
        while m > 12:
            y, m = y + 1, m - 12
        last = _cal.monthrange(y, m)[1]
        self.selected = dt.date(y, m, min(self.selected.day, last))

    def action_today(self) -> None:
        self.selected = dt.date.today()

    def action_choose(self) -> None:
        self.post_message(self.Selected(self, self.selected, chosen=True))

    def on_click(self, event: Click) -> None:
        x, y = event.x, event.y
        if y == 0:                                  # the month line: ‹ and › change month
            prev_x, next_x = getattr(self, "_arrows", (0, CELL * 7 - 1))
            if x <= prev_x + 1:
                self.action_month(-1)
            elif x >= next_x - 1:
                self.action_month(1)
            return
        row, col = y - 2, x // CELL
        weeks = self._weeks()
        if 0 <= row < len(weeks) and 0 <= col < 7:
            self.selected = weeks[row][col]
            if event.chain >= 2:
                self.action_choose()

    def on_focus(self) -> None:
        self.refresh()

    def on_blur(self) -> None:
        self.refresh()


__all__ = ["ChurchCalendar", "keys"]
