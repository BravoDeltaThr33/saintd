"""Home tab: the Church calendar and the chosen day — its feasts, fast and
readings, the saints commemorated, the saint of the day with an icon, hymn and
life, the Gospel and Epistle, and the feasts and fasts ahead."""

from __future__ import annotations

import datetime as dt
import time

from rich.table import Table
from rich.text import Text
from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Button, OptionList, Static
from textual.widgets.option_list import Option

from .. import narration as N
from .. import paschalion
from .. import sources as S
from ..db import LIFE_SOURCES
from ..graphics import SaintIcon
from ..heuristics import century_label
from ..text import html_to_text
from ..themes import liturgical_colour
from .banner import banner_width, render_banner
from .calendar import ChurchCalendar
from .common import (MONTH_ABBR, MONTHS, RANK_NAMES, WEEKDAYS, OpenSaint, glyphs, keys, pack, set_content,
                     short_century, short_name)
from .modals import ReadingsScreen
from .widgets import FitText

WD = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def church_date(civil: dt.date, calendar: str) -> tuple[int, int]:
    """The church (feast) date kept on a civil date."""
    if calendar == "old":
        return S.civil_to_church(civil)
    return civil.month, civil.day


class HomePane(VerticalScroll):
    BINDINGS = [
        Binding("left_square_bracket", "day(-1)", "Previous day", show=False),
        Binding("right_square_bracket", "day(1)", "Next day", show=False),
        Binding(keys("t"), "today", "Today", show=False),
        Binding(keys("s"), "readings", "Scripture", show=False),
        Binding(keys("n"), "random", "Random saint", show=False),
        Binding(keys("c"), "focus_calendar", "Calendar", show=False),
        Binding(keys("l"), "focus_list", "Day's saints", show=False),
        Binding(keys("f"), "toggle_saved", "Save", show=False),
        Binding(keys("g"), "focus_gospel", "Gospel", show=False),
    ]

    def compose(self) -> ComposeResult:
        yield Static(id="banner")
        yield Static(id="tagline")
        yield Static(id="home-sync")
        with Horizontal(id="home-main"):
            with Vertical(id="home-left"):
                with Vertical(id="cal-panel", classes="panel"):
                    yield ChurchCalendar(id="cal")
                    yield Static(id="cal-legend")
                    yield Static(id="day-info")
                    with Horizontal(classes="btn-row"):
                        yield Button("Today", id="go-today", compact=True)
                        yield Button("Scripture", id="readings", compact=True)
                with Vertical(id="ahead-panel", classes="panel"):
                    yield FitText(id="ahead")
            with Vertical(id="day-panel", classes="panel"):
                yield Static(id="day-head")
                yield Static(id="day-cols")
                yield OptionList(id="day-list")
            with Vertical(id="home-right"):
                with Vertical(id="spot-panel", classes="panel"):
                    with Horizontal(id="spot-top"):
                        yield SaintIcon(id="spot-icon")
                        yield Static(id="spot-name")
                    yield FitText(id="spot-text")
                    yield Static(id="spot-hymn")
                    with Horizontal(classes="btn-row", id="spot-buttons"):
                        yield Button("Read the full life", id="spot-open", variant="primary", compact=True)
                        yield Button("Listen", id="spot-listen", compact=True)
                        yield Button("Random saint", id="random", compact=True)
                with VerticalScroll(id="gospel-panel", classes="panel"):
                    yield Static(id="gospel")
        yield Static(id="home-keys")

    def on_mount(self) -> None:
        self.query_one("#cal-panel").border_title = "THE CHURCH CALENDAR"
        self.query_one("#day-panel").border_title = "COMMEMORATED"
        self.query_one("#spot-panel").border_title = "SAINT OF THE DAY"
        self.query_one("#ahead-panel").border_title = "THE DAYS AHEAD"
        self.query_one("#gospel-panel").border_title = "SCRIPTURE"
        self._spot_id: int | None = None
        self._day_ids: list[int] = []
        self._day_saints: list[dict] = []
        self._day_data: dict[dt.date, dict] = {}          # orthocal's answer for each day shown
        self._day_failed: dict[dt.date, float] = {}       # when a day could not be loaded (tried again later)
        self._day_loading: set[dt.date] = set()
        self._months_loaded: set[tuple[int, int, str]] = set()
        self._day_timer = None
        self._extras_timer = None
        self._list_shown: tuple | None = None
        self.query_one("#home-sync", Static).display = False
        self.refresh_all()

    # ----------------------------------------------------------- state
    @property
    def day(self) -> dt.date:
        return self.query_one("#cal", ChurchCalendar).selected

    def refresh_all(self) -> None:
        self.render_banner()
        self.refresh_today()

    def on_resize(self) -> None:
        self.render_banner()
        self.show_day_info(self.day)
        self.fill_day_list()
        self.show_ahead()

    def layout_changed(self) -> None:
        """The terminal crossed a size class (the panels were rearranged)."""
        self.call_after_refresh(self.on_resize)

    # ----------------------------------------------------------- banner
    def render_banner(self) -> None:
        g = glyphs(self.app)
        ascii_only = self.app.ctx.cfg["glyphs"] == "ascii"
        theme = self.app.current_theme
        colors = [theme.variables.get("banner-a", theme.primary), theme.variables.get("banner-b", theme.secondary),
                  theme.variables.get("banner-c", theme.accent)]
        width = self.size.width or 100
        text = "SAINT DIRECTORY" if width >= banner_width("SAINT DIRECTORY") + 4 else "SAINTD"
        set_content(self.query_one("#banner", Static), render_banner(text, colors, ascii_only))
        tag = Text(justify="center")
        tag.append(f"{g['orn']}  ", style="dim")
        tag.append("A DIRECTORY OF THE SAINTS OF THE EASTERN ORTHODOX CHURCH", style="bold")
        tag.append(f"  {g['orn']}", style="dim")
        set_content(self.query_one("#tagline", Static), tag)
        keys_t = Text(justify="center")
        for i, (k, what) in enumerate(((g["arrows"], "days"), ("PgUp PgDn", "months"), ("[ ]", "prev/next day"),
                                       ("T", "today"), ("S", "Scripture"), ("P", "listen"), ("N", "random saint"),
                                       (g["enter"], "open"), ("F", "save"), ("?", "help"))):
            keys_t.append("   " if i else "")
            keys_t.append(k, style="bold")
            keys_t.append(f" {what}", style="dim")
        set_content(self.query_one("#home-keys", Static), keys_t)
        set_content(self.query_one("#cal-legend", Static), self.query_one("#cal", ChurchCalendar).legend(), layout=False)

    # ----------------------------------------------------------- the day
    def refresh_today(self) -> None:
        """Re-read the chosen day (after a build, a calendar change...)."""
        self.show_day(self.day)

    def show_day(self, day: dt.date) -> None:
        ctx = self.app.ctx
        g = glyphs(self.app)
        cal = ctx.cfg["calendar"]
        cm, cd = church_date(day, cal)
        head = Text(no_wrap=True, overflow="ellipsis")
        if day == dt.date.today():
            head.append("TODAY ", style="bold")
        head.append(f"{WEEKDAYS[day.weekday()]}, {day.day} {MONTHS[day.month - 1]}", style="bold")
        if cal == "old":
            head.append(f"  {g['sep']}  church date {cd} {MONTHS[cm - 1]}", style="dim")
        saints = ctx.db.saints_on(cm, cd)
        if saints:
            head.append(f"  {g['sep']}  {len(saints)} commemorated", style="dim")
        set_content(self.query_one("#day-head", Static), head, layout=False)
        title = "COMMEMORATED TODAY" if day == dt.date.today() else f"COMMEMORATED {g['sep']} {day.day} {MONTHS[day.month - 1][:3].upper()}"
        self.query_one("#day-panel").border_title = title
        self._day_ids = [s["id"] for s in saints]
        self._day_saints = saints
        self.fill_day_list()
        self.pick_spotlight(saints, day)
        self.show_day_info(day)
        self.show_gospel(day)
        self.show_ahead()
        self.load_month(day.year, day.month)
        nxt = day + dt.timedelta(days=7)
        if (nxt.year, nxt.month) != (day.year, day.month):
            self.load_month(nxt.year, nxt.month)              # the days ahead run into next month
        self.ensure_day(day)

    # -- the commemorated saints, as a table
    def _columns(self, width: int) -> dict[str, int]:
        return {"cent": 9 if width >= 40 else 0, "place": 18 if width >= 78 else 14 if width >= 60 else 0,
                "marks": 3 if width >= 46 else 0}

    def _row(self, cells: list, width: int, cols: dict[str, int], header: bool = False) -> Table:
        t = Table.grid(expand=True, padding=(0, 1, 0, 0))
        t.add_column(width=2, no_wrap=True)
        t.add_column(ratio=1, overflow="fold")
        if cols["cent"]:
            t.add_column(width=cols["cent"] - 1, no_wrap=True, overflow="ellipsis")
        if cols["place"]:
            t.add_column(width=cols["place"] - 1, no_wrap=True, overflow="ellipsis")
        if cols["marks"]:
            t.add_column(width=cols["marks"] - 1, no_wrap=True)
        keep = [cells[0], cells[1]] + ([cells[2]] if cols["cent"] else []) + ([cells[3]] if cols["place"] else []) + \
               ([cells[4]] if cols["marks"] else [])
        t.add_row(*keep)
        return t

    def fill_day_list(self) -> None:
        """The day's saints as a table: name, century, place, and what is stored about them."""
        ctx = self.app.ctx
        g = glyphs(self.app)
        saints = self._day_saints
        ol = self.query_one("#day-list", OptionList)
        width = ol.scrollable_content_region.width or 60
        favs = ctx.db.favorite_ids()
        ids = [s["id"] for s in saints]
        marks = ctx.db.marks(ids)
        cols = self._columns(width)
        key = (ids, width, g["item"], sorted(set(ids) & set(favs)), sorted((k, tuple(sorted(v))) for k, v in marks.items()),
               ctx.directory_built(), getattr(self.app, "_sync_kind", ""))
        if self._list_shown == key and ol.option_count == max(1, len(saints)):
            return                                   # the same list at the same width
        keep = ol.highlighted
        ol.clear_options()
        if not saints:
            if ctx.directory_built():
                msg = "No commemorations found for this day."
            elif getattr(self.app, "_sync_kind", "") == "build":
                msg = "The directory is being built…"
            else:
                msg = "The directory is empty. Press Ctrl+B to build it."
            ol.add_options([Option(Text(msg, style="dim"), disabled=True)])
            set_content(self.query_one("#day-cols", Static), "", layout=False)
        else:
            head = [Text(""), Text("SAINT", style="bold"), Text("CENTURY", style="bold"), Text("PLACE", style="bold"),
                    Text("", style="bold")]
            set_content(self.query_one("#day-cols", Static), self._row(head, width, cols, header=True), layout=False)
            opts = []
            for s in saints:
                m = marks.get(s["id"], set())
                tail = (g["life"] if "life" in m else " ") + (g["hymn"] if "hymns" in m else "")
                place = s["country"] if s["country"] and s["country"] != "Unknown" else ""
                cent = f"{short_century(s['century'])} c." if s["century"] is not None else ""
                cells = [Text(g["saved"] if s["id"] in favs else g["item"], style="bold"), Text(s["name"]),
                         Text(cent, style="dim"), Text(place, style="dim italic"), Text(tail, style="dim")]
                opts.append(Option(self._row(cells, width, cols), id=str(s["id"])))
            ol.add_options(opts)
            if keep is not None and keep < len(opts) and self.app.focused is ol:
                ol.highlighted = keep
        self._list_shown = key

    DAY_INFO_LINES = 10            # #day-info has a fixed height: no re-layout, no jumping panels

    def show_day_info(self, day: dt.date) -> None:
        g = glyphs(self.app)
        data = self._day_data.get(day)
        cal = self.app.ctx.cfg["calendar"]
        w = self.query_one("#day-info", Static)
        width = max(20, w.content_size.width or 30)
        lines: list[tuple[str, str]] = [(f"{WEEKDAYS[day.weekday()]}, {day.day} {MONTHS[day.month - 1]} {day.year}",
                                         "bold")]
        cm, cd = church_date(day, cal)
        if cal == "old":
            lines.append((f"Church date {cd} {MONTHS[cm - 1]} (Old Cal.)", "dim"))
        else:
            oc_m, oc_d = S.civil_to_church(day)
            lines.append((f"Old Calendar: {oc_d} {MONTHS[oc_m - 1]}", "dim"))
        season = paschalion.season(day, cal)
        if data is None and day in self._day_failed and day not in self._day_loading:
            if season:
                lines.append((season[:1].upper() + season[1:], "italic"))
            lines += [("Feasts, fast and readings", "dim italic"), ("are shown when online.", "dim italic")]
        elif data is None:
            lines.append(("Loading feasts and readings…", "dim italic"))
        else:
            titles = N.day_titles(data)
            feasts = N.day_feasts(data)
            rank = int(data.get("feast_level") or 0)
            sign = g.get(f"rank{rank}", g["item"]) if rank >= 2 else g["item"]
            for i, f in enumerate(feasts[:2]):
                lines.append((f"{sign if i == 0 else ' '} {f}", "bold"))
            if not feasts and rank >= 2:
                lines.append((f"{sign} {RANK_NAMES.get(rank, '')} service", "bold"))
            if titles:
                lines.append((titles[0], "italic"))
            bits = []
            if data.get("tone"):
                bits.append(f"Tone {data['tone']}")
            fast = data.get("fast_level_desc") or ""
            exc = data.get("fast_exception_desc") or ""
            if fast:
                bits.append(fast + (f" ({exc.lower()})" if exc and fast != "No Fast" else ""))
            if season and season.lower() not in " ".join(titles).lower():
                bits.append(season[:1].upper() + season[1:])
            colour, _ = liturgical_colour(day, cal)
            bits.append(f"{colour} vestments")
            lines += [(x, "") for x in pack(bits, width, sep=f" {g['sep']} ")]
            readings = [r.get("display", "") for r in (data.get("readings") or []) if r.get("display")]
            if readings:
                packed = pack(readings, width - 2, sep=f" {g['sep']} ")
                room = max(1, self.DAY_INFO_LINES - len(lines) - 1)
                if len(packed) > room:
                    packed = packed[:room]
                    packed[-1] = packed[-1].rstrip() + " …"
                for i, x in enumerate(packed):
                    lines.append((f"{g['book']} {x.strip()}" if i == 0 else f"  {x.strip()}", ""))
                lines.append((f"S opens them {g['sep']} P listens", "dim"))
        t = Text(no_wrap=True, overflow="ellipsis")
        for i, (txt, st) in enumerate(lines[:self.DAY_INFO_LINES]):
            if i:
                t.append("\n")
            t.append(txt, style=st)
        set_content(w, t, layout=False)

    # -- the days ahead
    def show_ahead(self) -> None:
        """The coming week (each day's chief commemoration) and the next feasts and fasts."""
        g = glyphs(self.app)
        ctx = self.app.ctx
        widget = self.query_one("#ahead", FitText)
        width = max(20, widget.content_size.width or 30)
        rows = widget.content_size.height or 16
        day = self.day
        cal = ctx.cfg["calendar"]
        info = self.query_one("#cal", ChurchCalendar).info
        t = Text()
        week_rows = max(0, min(7, rows - 6 if rows >= 12 else rows - 1))
        if week_rows:
            t.append("THE WEEK AHEAD\n", style="bold")
            for i in range(1, week_rows + 1):
                d = day + dt.timedelta(days=i)
                di = info.get(d, {})
                rank = di.get("rank", 0)
                title = (di.get("title") or "").split(";")[0].strip()
                if not title:
                    cm, cd = church_date(d, cal)
                    first = ctx.db.saints_on(cm, cd)[:1]
                    title = first[0]["name"] if first else ""
                sign = g.get(f"rank{rank}", " ") if rank >= 2 else (g["fast"] if di.get("fast") else " ")
                label = f"{WD[d.weekday()]} {d.day:>2} "
                style = "bold" if d.weekday() == 6 else ""
                t.append(label, style=f"dim {style}".strip())
                t.append(f"{sign} ", style="bold")
                room = width - len(label) - 2
                t.append(title[:room - 1] + "…" if len(title) > room else title, style=style)
                t.append("\n")
        left = rows - (week_rows + 1 if week_rows else 0)
        events = paschalion.upcoming(day, cal, count=max(1, (left - (2 if week_rows else 1)) // 2),
                                     include_today=False)
        if left >= 3 and events:
            t.append("\n" if week_rows else "")
            t.append("FEASTS & FASTS AHEAD\n", style="bold")
            for e in events:
                sign = {"pascha": g["cross"], "great": g["rank6"], "feast": g["rank5"]}.get(e.kind, g["fast"])
                name = e.name if len(e.name) <= width - 2 else e.name[:width - 3] + "…"
                t.append(f"{sign} ", style="bold")
                t.append(name + "\n", style="bold" if e.kind in ("pascha", "great") else "")
                n = (e.day - dt.date.today()).days
                when = "today" if n == 0 else "tomorrow" if n == 1 else f"in {n} days" if n > 1 else f"{-n} days ago"
                t.append(f"  {WD[e.day.weekday()]} {e.day.day} {MONTH_ABBR[e.day.month - 1]} {g['sep']} {when}\n",
                         style="dim")
        t.rstrip()
        widget.set_text(t)

    # -- the readings, in full
    def show_gospel(self, day: dt.date) -> None:
        panel = self.query_one("#gospel-panel")
        w = self.query_one("#gospel", Static)
        data = self._day_data.get(day)
        g = glyphs(self.app)
        if data is None:
            loading = day not in self._day_failed or day in self._day_loading
            set_content(w, Text("Loading the day's readings…" if loading else
                                "The readings are shown when online. Press S to try again.", style="dim italic"))
            panel.border_title = "SCRIPTURE"
            return
        readings = list(data.get("readings") or [])
        if not readings:
            set_content(w, Text("No Scripture readings are appointed for this day.", style="dim italic"))
            panel.border_title = "SCRIPTURE"
            return
        order = {"gospel": 0, "epistle": 1}
        readings.sort(key=lambda r: order.get((r.get("source") or "").lower(), 2))
        t = Text()
        for n, r in enumerate(readings):
            if n:
                t.append("\n\n")
            t.append(f"{(r.get('source') or 'Reading').upper()} {g['sep']} {r.get('display', '')}", style="bold")
            if r.get("description"):
                t.append(f"  ({r['description']})", style="dim")
            t.append("\n")
            first = True
            for v in r.get("passage") or []:
                txt = (v.get("content") or "").strip()
                if not txt:
                    continue
                if v.get("paragraph_start") and not first:
                    t.append("\n")
                t.append(f"{v.get('verse', '')} ", style="dim")
                t.append(txt + " ")
                first = False
            if first:
                t.append("(the calendar gives no text for this reading)", style="dim italic")
        main = readings[0]
        panel.border_title = f"{(main.get('source') or 'Scripture').upper()} {g['sep']} {main.get('display', '').upper()}"
        set_content(w, t)

    def _orthocal_calendar(self) -> str:
        return "julian" if self.app.ctx.cfg["calendar"] == "old" else "gregorian"

    def ensure_day(self, day: dt.date, retry_after: float = 20.0) -> bool:
        """Load the day's feasts and readings unless they are here or on their way;
        a day that failed is tried again after `retry_after` seconds. True if a load started."""
        if day in self._day_data or day in self._day_loading:
            return False
        failed = self._day_failed.get(day)
        if failed is not None and time.monotonic() - failed < retry_after:
            return False
        self._day_loading.add(day)
        self.load_day(day, self._orthocal_calendar())
        return True

    @work(thread=True, exclusive=False, group="home-day", exit_on_error=False)
    def load_day(self, day: dt.date, cal: str) -> None:
        try:
            data = S.orthocal_on(self.app.ctx.http_fg, day, cal)
        except Exception:
            data = None
        self.app.call_from_thread(self._day_loaded, day, cal, data if isinstance(data, dict) and data else None)

    def _day_loaded(self, day: dt.date, cal: str, data: dict | None) -> None:
        self._day_loading.discard(day)
        if cal != self._orthocal_calendar():
            return                                  # asked before the calendar was switched
        if data:
            self._day_data[day] = data
            self._day_failed.pop(day, None)
        else:
            self._day_failed[day] = time.monotonic()
        if day == self.day:
            self.show_day_info(day)
            self.show_gospel(day)
        if getattr(self, "_readings_wanted", None) == day:
            self._readings_wanted = None
            if not data:
                self.app.notify("The readings could not be loaded. Check the internet connection.",
                                severity="warning", timeout=4)
            elif self.app.screen is self.app.w_screen and self.app.w_pages.current == "home":
                self.app.push_screen(ReadingsScreen(day, data))

    @work(thread=True, exclusive=False, group="home-month", exit_on_error=False)
    def load_month(self, year: int, month: int) -> None:
        cal = self._orthocal_calendar()
        key = (year, month, cal)
        if key in self._months_loaded:
            return
        self._months_loaded.add(key)
        try:
            info = S.orthocal_month_days(self.app.ctx.http_fg, year, month, cal)
        except Exception:
            self._months_loaded.discard(key)
            return
        self.app.call_from_thread(self._month_loaded, cal, info)

    def _month_loaded(self, cal: str, info: dict) -> None:
        if cal == self._orthocal_calendar():         # not a month of the calendar used before a switch
            self.query_one("#cal", ChurchCalendar).set_info(info)
            self.show_ahead()

    def calendar_changed(self) -> None:
        """New/Old Calendar switched in Settings."""
        self._day_data.clear()
        self._day_failed.clear()
        self._day_loading.clear()
        self._months_loaded.clear()
        self.query_one("#cal", ChurchCalendar).info.clear()
        self.refresh_today()

    # ----------------------------------------------------------- saint of the day
    def pick_spotlight(self, saints: list[dict], day: dt.date) -> None:
        ctx = self.app.ctx
        best = None
        for s in saints:
            if s["kind"] != "saint":
                continue
            st = [x for x in ctx.db.stories(s["id"]) if x["source"] in LIFE_SOURCES]
            if st:
                best = (s, st[0])
                break
        if best is None:                       # fall back to a saint with a calendar note
            for s in saints:
                notes = [x for x in ctx.db.stories(s["id"]) if x["source"] == "wikical"]
                if s["kind"] == "saint" and notes:
                    best = (s, notes[0])
                    break
        if best is None and saints:
            best = (saints[0], None)
        panel = self.query_one("#spot-panel")
        panel.border_title = "SAINT OF THE DAY" if day == dt.date.today() else \
            f"SAINT OF {day.day} {MONTHS[day.month - 1][:3].upper()}"
        icon = self.query_one("#spot-icon", SaintIcon)
        if not best:
            self._spot_id = None
            set_content(self.query_one("#spot-name", Static), Text("—", style="dim"))
            self.query_one("#spot-text", FitText).set_text("")
            self.query_one("#spot-hymn", Static).display = False
            icon.show(None, mode=self.app.graphics_mode)
            return
        s, story = best
        changed = self._spot_id != s["id"]
        self._spot_id = s["id"]
        self.render_spot(s, story)
        initial = (short_name(s) or s["name"])[:1].upper()
        show = ctx.cfg["show_icons"] and self.app.graphics_mode != "off"
        icon.display = show
        icon.show(ctx.articles.icon_path(s) if show else None, initial=initial, mode=self.app.graphics_mode,
                  label=short_name(s))
        if show and not ctx.articles.icon_path(s):
            self.load_spot_icon(s["id"])
        if changed:
            if self._extras_timer is not None:
                self._extras_timer.stop()
            sid = s["id"]
            self._extras_timer = self.set_timer(1.2, lambda: self.load_spot_extras(sid))

    def render_spot(self, s: dict, story: dict | None = None) -> None:
        """The saint of the day: name, facts and marks beside the icon; the life; the troparion."""
        ctx = self.app.ctx
        g = glyphs(self.app)
        info = ctx.articles.summary(s)
        stories = ctx.db.stories(s["id"])
        if story is None:
            lives = [x for x in stories if x["source"] in LIFE_SOURCES] or \
                    [x for x in stories if x["source"] == "wikical"]
            story = lives[0] if lives else None
        t = Text()
        t.append(info["name"], style=f"bold {self.app.current_theme.primary}")
        if ctx.db.is_favorite(s["id"]):
            t.append(f" {g['saved']}", style="bold")
        if info["subtitle"]:
            t.append("\n" + info["subtitle"], style="italic dim")
        t.append("\n")
        facts = []
        if info["feasts"]:
            (m, d), label = info["feasts"][0]
            facts.append((g["cross"], "Feast", f"{MONTH_ABBR[m - 1]} {d}" + (f" ({label.lower()})" if label else "")))
        if info["lived"]:
            facts.append((g["dot"], "Lived", info["lived"]))
        if info["where"]:
            facts.append((g["dot"], "From", info["where"]))
        if info["kinds"]:
            facts.append((g["dot"], "Kind", ", ".join(info["kinds"][:2])))
        for sign, k, v in facts:
            t.append(f"\n{sign} ", style="bold")
            t.append(f"{k:<6}", style="bold dim")
            t.append(v)
        badges = []
        if any(x["source"] in LIFE_SOURCES for x in stories):
            badges.append(f"{g['life']} life")
        if any(x["source"] == "htc-hymn" for x in stories):
            badges.append(f"{g['hymn']} hymns")
        if ctx.db.article(s["id"]):
            badges.append(f"{g['book']} history")
        if badges:
            t.append("\n\n" + "  ".join(badges), style="dim")
        set_content(self.query_one("#spot-name", Static), t)
        body = self.query_one("#spot-text", FitText)
        if story:
            paras = [p.strip() for p in html_to_text(story["html"]).split("\n\n") if p.strip()]
            body.set_text(Text("\n\n".join(paras[:8])))
        else:
            body.set_text(Text("Open the Focus tab for everything the sources record about this saint.", style="dim"))
        hymns = sorted((x for x in stories if x["source"] == "htc-hymn"), key=lambda x: x["title"])
        hw = self.query_one("#spot-hymn", Static)
        if hymns:
            h = hymns[0]
            ht = Text()
            ht.append(f"{g['hymn']} {N.hymn_heading(h).upper()}\n", style="bold")
            lines = [p.strip() for p in h["html"].replace("//", "/").split("/") if p.strip()]
            ht.append("\n".join(lines), style="italic")
            set_content(hw, ht)
            hw.display = True
        else:
            hw.display = False

    @work(thread=True, exclusive=True, group="home-icon", exit_on_error=False)
    def load_spot_icon(self, sid: int) -> None:
        ctx = self.app.ctx
        try:
            path = ctx.articles.fetch_icon(sid)
        except Exception:
            path = None
        if path and self._spot_id == sid:
            self.app.call_from_thread(self.query_one("#spot-icon", SaintIcon).show, path)

    @work(thread=True, exclusive=True, group="home-extras", exit_on_error=False)
    def load_spot_extras(self, sid: int) -> None:
        """The troparion and kontakion of the saint of the day (Holy Trinity calendar), once."""
        ctx = self.app.ctx
        if self._spot_id != sid or not ctx.cfg["use_htc"] or ctx.db.looked(sid, "htc"):
            return
        s = ctx.db.get_saint(sid)
        if not s:
            return
        try:
            added = ctx.articles._htc(s, False, lambda m: None)
        except Exception:
            added = False
        if added and self._spot_id == sid:
            self.app.call_from_thread(self._spot_extras_loaded, sid)

    def _spot_extras_loaded(self, sid: int) -> None:
        s = self.app.ctx.db.get_saint(sid)
        if s and self._spot_id == sid:
            self.render_spot(s)
            self._list_shown = None
            self.fill_day_list()                       # the ♪ mark

    def set_graphics(self, mode: str) -> None:
        self.query_one("#spot-icon", SaintIcon).set_mode(mode)
        self.pick_spotlight(self._day_saints, self.day)     # icons may have been switched off

    # ----------------------------------------------------------- reading aloud
    def reader_changed(self) -> None:
        """The Listen button of the saint of the day says Pause / Resume while it reads."""
        try:
            b = self.query_one("#spot-listen", Button)
        except Exception:
            return
        r = self.app.reader
        if r.active and self._spot_id is not None and r.owner == ("spot", self._spot_id):
            label = "Resume" if r.state == "paused" else "Pause"
        else:
            label = "Listen"
        if str(b.label) != label:
            b.label = label

    def listen(self) -> bool:
        """P on Home: hear the day — its feasts and fast, the saints, the saint of the
        day's life and hymn, and the readings."""
        reader = self.app.reader
        owner = ("day", self.day)
        if reader.active and reader.owner == owner:
            reader.toggle()
            return True
        self.app.start_reading(self.day_title(), self.reading_script(), owner)
        return True

    def day_title(self) -> str:
        d = self.day
        return f"{WEEKDAYS[d.weekday()]}, {d.day} {MONTHS[d.month - 1]} {d.year}"

    def reading_script(self) -> list:
        ctx = self.app.ctx
        day = self.day
        cal = ctx.cfg["calendar"]
        data = self._day_data.get(day) or {}
        out: list = []
        cal_panel = self.query_one("#cal-panel")
        intro = N.spoken_date(day) + "."
        oc_m, oc_d = S.civil_to_church(day)
        if cal != "old":
            intro += f" On the Old Calendar, the {N.ordinal(oc_d)} of {MONTHS[oc_m - 1]}."
        N.add(out, intro, cal_panel, "day")
        if data:
            bits = N.day_titles(data)[:1] + [f"The feast of {f}" for f in N.day_feasts(data)[:2]]
            if data.get("tone"):
                bits.append(f"Tone {data['tone']}")
            text = ". ".join(bits)
            fast = N.fast_sentence(data)
            N.add(out, (text + ". " if text else "") + fast, cal_panel, "day")
        names = [s["name"] for s in self._day_saints]
        if names:
            shown = names[:12]
            more = len(names) - len(shown)
            N.add(out, "Today the Church commemorates " + "; ".join(shown) +
                  (f"; and {more} more." if more else "."), self.query_one("#day-panel"), "saints")
        if self._spot_id:
            s = ctx.db.get_saint(self._spot_id)
            if s:
                spot = self.query_one("#spot-panel")
                N.add(out, "The saint of the day.", spot, "spot")
                out += N.saint_script(ctx, s, hymns=ctx.cfg["tts_hymns"], target=spot)
        if data:
            out += N.readings_script(data, self.query_one("#gospel-panel"))
        return out

    # ----------------------------------------------------------- sync status line
    def set_stage(self, text: str) -> None:
        w = self.query_one("#home-sync", Static)
        if w.display != bool(text):
            w.display = bool(text)
        set_content(w, Text(text, style="italic", justify="center", no_wrap=True, overflow="ellipsis"), layout=False)

    def refresh_status(self) -> None:
        pass

    # ----------------------------------------------------------- events & actions
    def on_church_calendar_selected(self, ev: ChurchCalendar.Selected) -> None:
        # the calendar moves at once; the day's list follows when the keys pause (smooth key repeat)
        if self._day_timer is not None:
            self._day_timer.stop()
            self._day_timer = None
        if ev.chosen:
            self.show_day(ev.day)
            self.action_focus_list()
        else:
            self._day_timer = self.set_timer(0.12, lambda: self.show_day(self.day))

    def on_option_list_option_selected(self, ev: OptionList.OptionSelected) -> None:
        if ev.option.id:
            self.post_message(OpenSaint(int(ev.option.id), context=self._day_ids, origin="home"))

    def on_button_pressed(self, ev: Button.Pressed) -> None:
        bid = ev.button.id
        if bid == "spot-open" and self._spot_id:
            self.post_message(OpenSaint(self._spot_id, context=self._day_ids, origin="home"))
        elif bid == "spot-listen":
            self.listen_spot()
        elif bid == "random":
            self.action_random()
        elif bid == "go-today":
            self.action_today()
            self.action_focus_calendar()              # the arrow keys move the day again
        elif bid == "readings":
            self.action_readings()

    def listen_spot(self) -> None:
        """The Listen button: just the saint of the day."""
        if not self._spot_id:
            return
        reader = self.app.reader
        owner = ("spot", self._spot_id)
        if reader.active and reader.owner == owner:
            reader.toggle()
            return
        s = self.app.ctx.db.get_saint(self._spot_id)
        if s:
            spot = self.query_one("#spot-panel")
            self.app.start_reading(s["name"], N.saint_script(self.app.ctx, s, hymns=self.app.ctx.cfg["tts_hymns"],
                                                             target=spot), owner)

    def action_day(self, step: int) -> None:
        cal = self.query_one("#cal", ChurchCalendar)
        cal.selected = cal.selected + dt.timedelta(days=step)

    def action_today(self) -> None:
        self.query_one("#cal", ChurchCalendar).selected = dt.date.today()

    def action_random(self) -> None:
        s = self.app.ctx.db.random_saint()
        if s:
            self.post_message(OpenSaint(s["id"], origin="home"))

    def action_readings(self) -> None:
        day = self.day
        data = self._day_data.get(day)
        if data is None:
            if day in self._day_loading:
                self.app.notify("Still loading the day's readings… try again in a moment.", timeout=3)
            else:
                self.ensure_day(day, retry_after=0)          # S tries again at once
                self.show_day_info(day)
                self.show_gospel(day)
                self.app.notify("Loading the day's readings…", timeout=3)
            self._readings_wanted = day                      # open them as soon as they arrive
            return
        self.app.push_screen(ReadingsScreen(day, data))

    def action_focus_calendar(self) -> None:
        self.query_one("#cal", ChurchCalendar).focus()

    def action_focus_list(self) -> None:
        ol = self.query_one("#day-list", OptionList)
        ol.focus()
        if ol.option_count and ol.highlighted is None:
            ol.highlighted = 0

    def action_focus_gospel(self) -> None:
        gp = self.query_one("#gospel-panel")
        if gp.display:
            gp.focus()

    def focus_saint(self, sid: int | None) -> None:
        """The day's list with the cursor on a saint (B in Focus comes back here)."""
        self.fill_day_list()
        ol = self.query_one("#day-list", OptionList)
        ol.focus()
        if sid in self._day_ids:
            ol.highlighted = self._day_ids.index(sid)
        elif ol.option_count and ol.highlighted is None:
            ol.highlighted = 0

    def action_toggle_saved(self) -> None:
        """F: save or unsave the highlighted saint of the list, else the Saint of the Day."""
        ol = self.query_one("#day-list", OptionList)
        sid = None
        if self.app.focused is ol and ol.highlighted is not None and ol.highlighted < len(self._day_ids):
            sid = self._day_ids[ol.highlighted]
        elif self._spot_id:
            sid = self._spot_id
        db = self.app.ctx.db
        s = db.get_saint(sid) if sid else None
        if not s:
            self.app.notify("Choose a saint in the day's list first (L).", timeout=3)
            return
        on = not db.is_favorite(sid)
        db.set_favorite(sid, on)
        g = glyphs(self.app)
        self.app.notify(f"Saved {s['name']} {g['saved']}" if on else f"Removed {s['name']} from your saved saints",
                        timeout=3)
        self.app.favorites_changed()

    def focus_first(self) -> None:
        self.query_one("#cal", ChurchCalendar).focus()


__all__ = ["HomePane", "century_label", "church_date"]
