"""Search tab: name search plus filters, results table."""

from __future__ import annotations

from rich.text import Text
from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Grid, Horizontal, Vertical
from textual.widgets import Button, DataTable, Input, Label, Select, Static, Switch

from .. import narration as N
from ..db import LIFE_SOURCES
from ..graphics import SaintIcon
from ..heuristics import CATEGORIES, century_label
from ..sync import church_date_today
from ..text import html_to_text
from .common import (MONTH_ABBR, MONTHS, LazyPage, OpenSaint, fmt_feast, glyphs, keys, set_content, short_century,
                     short_name)
from .widgets import FitText

PAGE = 200


class ResultsTable(DataTable):
    """The results; fits its columns again whenever its own width changes
    (the preview column comes and goes with the terminal's width)."""

    def on_resize(self) -> None:
        pane = next((a for a in self.ancestors if isinstance(a, SearchPane)), None)
        if pane is not None and pane.is_built:
            pane.schedule_columns()


class SearchPane(LazyPage, Vertical):
    BINDINGS = [
        Binding(keys("ctrl+f"), "focus_query", "Search box", show=False),
        Binding("slash", "focus_query", show=False),
        Binding(keys("ctrl+r"), "reset", "Clear", show=False),
        Binding(keys("f"), "toggle_saved", "Save", show=False),
        Binding("down", "to_results", show=False),
    ]

    def compose(self) -> ComposeResult:
        if not self.lazy_ready:          # built on the first visit (keeps start-up quick)
            yield Static("Opening Search…", classes="lazy-wait")
            return
        with Vertical(id="query-panel", classes="panel"):
            with Horizontal(id="q-row"):
                yield Input(placeholder="Type a name or part of one — e.g. seraph, john, myra, xenia", id="q")
                yield Button("Today", id="f-today", compact=True)
                yield Button("Reset", id="f-reset", compact=True)
            with Grid(id="filters"):
                with Horizontal(classes="f-cell"):
                    yield Label("Month", classes="f-label")
                    yield Select([(m, i + 1) for i, m in enumerate(MONTHS)], prompt="Any month", id="f-month",
                                 compact=True)
                with Horizontal(classes="f-cell"):
                    yield Label("Day", classes="f-label")
                    yield Select([(str(d), d) for d in range(1, 32)], prompt="Any day", id="f-day", compact=True)
                with Horizontal(classes="f-cell"):
                    yield Label("Gender", classes="f-label")
                    yield Select([(g, g) for g in ("Male", "Female", "Group", "N/A")], prompt="Any", id="f-gender",
                                 compact=True)
                with Horizontal(classes="f-cell"):
                    yield Label("Century", classes="f-label")
                    yield Select([], prompt="Any century", id="f-century", compact=True)
                with Horizontal(classes="f-cell"):
                    yield Label("Country", classes="f-label")
                    yield Select([], prompt="Any country", id="f-country", compact=True)
                with Horizontal(classes="f-cell"):
                    yield Label("Kind", classes="f-label")
                    yield Select([(c, c) for c in CATEGORIES], prompt="Any kind of saint", id="f-cat", compact=True)
                with Horizontal(classes="f-cell"):
                    yield Switch(value=False, id="f-saved", classes="mini")
                    yield Label("saved only", classes="f-label f-switch-label")
                with Horizontal(classes="f-cell"):
                    yield Switch(value=False, id="f-other", classes="mini")
                    yield Label("feasts, icons & memorials", classes="f-label f-switch-label")
        yield Static(id="result-count")
        with Horizontal(id="search-body"):
            yield ResultsTable(id="results", cursor_type="row", zebra_stripes=True)
            with Vertical(id="preview", classes="panel"):
                with Horizontal(id="pv-top"):
                    yield SaintIcon(id="pv-icon")
                    yield Static(id="pv-head")
                yield FitText(id="pv-text")
                yield Static(id="pv-hymn")
                yield Static(id="pv-keys")

    typed_early = ""                       # filled by the app while the page is being built

    def on_mount(self) -> None:
        self._narrow: bool | None = None
        self._cols_width = 0
        self._resize_timer = None
        self._timer = None
        self._loaded = False           # widgets built and the first search run
        self._dirty = False
        self._ids: list[int] = []
        self._total = 0
        self._filters_cache: dict | None = None
        self._pv_sid: int | None = None
        self._pv_timer = None
        self._pv_icon_timer = None

    # ------------------------------------------------------------- lifecycle
    def ensure_loaded(self) -> None:
        if not self.is_built:
            self.build()
        elif self._dirty:
            self._dirty = False
            self.refresh_filters()
            self.run_search()

    def built(self) -> None:
        if not self.is_current_page:
            self.typed_early = ""
        self.query_one("#query-panel").border_title = "SEARCH THE DIRECTORY"
        self.query_one("#preview").border_title = "PREVIEW"
        self._fit_query()
        self.setup_columns()
        t = self.query_one("#results", DataTable)
        self.watch(t, "scroll_y", self._scrolled, init=False)      # the wheel loads more rows too
        self._loaded = True
        self._dirty = False
        self.refresh_filters()
        self.run_search()

    def directory_changed(self) -> None:
        """The directory grew or changed; refresh now if visible, else on the next visit."""
        if not self._loaded:
            return
        if self.app.w_pages.current == "search":
            self.refresh_filters()
            self.run_search(keep_cursor=True)
        else:
            self._dirty = True

    # ------------------------------------------------------------- data
    def refresh_filters(self) -> None:
        db = self.app.ctx.db
        cs = sorted(c for c in db.distinct("country") if c and c != "Unknown")
        sel = self.query_one("#f-country", Select)
        cur = sel.selection
        with self.prevent(Select.Changed):
            sel.set_options([(c, c) for c in cs] + [("Unknown", "Unknown")])
            if cur in cs or cur == "Unknown":
                sel.value = cur
        cents = sorted(c for c in db.distinct("century") if c is not None)
        sel2 = self.query_one("#f-century", Select)
        cur2 = sel2.selection
        with self.prevent(Select.Changed):
            sel2.set_options([(century_label(c), c) for c in cents] + [("Unknown", "unknown")])
            if cur2 is not None and (cur2 in cents or cur2 == "unknown"):
                sel2.value = cur2

    def _filters(self) -> dict:
        def v(sid):
            return self.query_one(sid, Select).selection
        return {
            "text": self.query_one("#q", Input).value,
            "month": v("#f-month"), "day": v("#f-day"), "gender": v("#f-gender"),
            "country": v("#f-country"), "century": v("#f-century"), "category": v("#f-cat"),
            "include_other": self.query_one("#f-other", Switch).value,
            "saved_only": self.query_one("#f-saved", Switch).value,
        }

    WIDE_COLUMNS = [("Feast", "feast", 6), ("Cent.", "century", 5), ("Gender", "gender", 7),
                    ("Country", "country", 16), ("Kind", "kind", 24)]
    MID_COLUMNS = [("Feast", "feast", 6), ("Cent.", "century", 5), ("Country", "country", 13), ("Kind", "kind", 18)]
    NARROW_COLUMNS = [("Feast", "feast", 6), ("Cent.", "century", 5), ("Country", "country", 11)]

    def _table_width(self) -> int:
        t = self.query_one("#results", DataTable)
        width = t.scrollable_content_region.width
        if not width:                    # not laid out yet: the page minus its padding and the table's border
            width = (self.size.width or max(40, self.app.size.width - 24)) - 2
        return max(30, width)

    def setup_columns(self) -> None:
        """Lay out the result columns to fit the table (fewer columns when narrow)."""
        width = self._table_width()
        if width == self._cols_width:
            return
        self._cols_width = width
        t = self.query_one("#results", DataTable)
        pad = 2 * t.cell_padding
        room = width - 2                 # leave space for the scroll bar
        cols = self.WIDE_COLUMNS
        for cand in (self.WIDE_COLUMNS, self.MID_COLUMNS, self.NARROW_COLUMNS):
            cols = cand
            if room - sum(w + pad for _, _, w in cand) - pad >= 44:      # room for most names
                break
        if room - sum(w + pad for _, _, w in cols) - pad < 20:
            cols = self.NARROW_COLUMNS
        self._narrow = cols is self.NARROW_COLUMNS
        self._col_keys = [k for _, k, _ in cols]
        name_w = max(16, room - sum(w + pad for _, _, w in cols) - pad)
        t.clear(columns=True)
        t.add_column("Name", key="name", width=name_w)
        for label, key, w in cols:
            t.add_column(label, key=key, width=w)
        if self.is_mounted and self._loaded:
            self.run_search(keep_cursor=True)
            self.show_preview(self._highlighted_sid(), force=True)

    def on_resize(self) -> None:
        if self.is_built:
            self._fit_query()
            self.schedule_columns()

    def schedule_columns(self) -> None:
        if self._resize_timer is not None:
            self._resize_timer.stop()
        self._resize_timer = self.set_timer(0.12, self.setup_columns)

    def _fit_query(self) -> None:
        q = self.query_one("#q", Input)
        short = self.app.size.height < 34
        if q.compact != short:
            q.compact = short

    def _add_rows(self, rows: list[dict]) -> None:
        t = self.query_one("#results", DataTable)
        g = glyphs(self.app)
        favs = self.app.ctx.db.favorite_ids()
        for r in rows:
            cats = [c for c in r["categories"].split("|") if c]
            kind = ", ".join(cats[:2]) if cats else r["kind"].title()
            name = Text(r["name"])
            if r["id"] in favs:
                name.append(f" {g['saved']}", style="bold")
            if r.get("has_life"):
                name.append(f" {g['life']}", style="dim")
            cells = {"feast": fmt_feast(r.get("first_feast")), "century": short_century(r["century"]),
                     "gender": r["gender"], "country": r["country"], "kind": kind}
            t.add_row(name, *[cells[k] for k in getattr(self, "_col_keys", ["feast", "century", "country"])],
                      key=str(r["id"]))
            self._ids.append(r["id"])

    def run_search(self, keep_cursor: bool = False) -> None:
        if not self._loaded:
            return
        f = self._filters()
        self._filters_cache = f
        t = self.query_one("#results", DataTable)
        old_row = t.cursor_row if keep_cursor else 0
        rows, n = self.app.ctx.db.search(**f, limit=PAGE)
        self._total = n
        self._ids = []
        t.clear()
        self._add_rows(rows)
        if keep_cursor and t.row_count:
            t.move_cursor(row=min(old_row, t.row_count - 1), animate=False)
        self._update_count()
        self.show_preview(self._highlighted_sid())

    def _load_more(self) -> None:
        if self._filters_cache is None or len(self._ids) >= self._total:
            return
        rows, _ = self.app.ctx.db.search(**self._filters_cache, limit=PAGE, offset=len(self._ids), count=False)
        if rows:
            self._add_rows(rows)
            self._update_count()

    def _scrolled(self, _old: float, new: float) -> None:
        t = self.query_one("#results", DataTable)
        if new >= t.max_scroll_y - max(8, t.size.height):      # within a page of the end
            self._load_more()

    def glyphs_changed(self) -> None:
        """Unicode <-> Plain ASCII symbols: draw the marks again."""
        if self._loaded:
            self.run_search(keep_cursor=True)

    def more_ids(self) -> list[int]:
        """Load the next page of results (Focus stepping past the loaded ones)."""
        if self.is_built:
            self._load_more()
        return list(self._ids)

    def focus_result(self, sid: int | None) -> None:
        """The results with the cursor on a saint (B in Focus comes back here)."""
        def go() -> None:
            t = self.query_one("#results", DataTable)
            if not t.row_count:
                self.query_one("#q", Input).focus()
                return
            t.focus()
            if sid is not None and str(sid) in t.rows:
                t.move_cursor(row=t.get_row_index(str(sid)), animate=False)
        self.when_built(go, focus=True)

    def _update_count(self) -> None:
        g = glyphs(self.app)
        n = self._total
        c = Text()
        c.append(f" {n:,} ", style="reverse bold")
        c.append(" match" + ("" if n == 1 else "es"))
        if n > len(self._ids):
            c.append(f"  (showing {len(self._ids):,} — scroll for more)", style="dim")
        c.append(f"   {g['saved']} saved  {g['life']} has a life or article    {g['enter']} open {g['sep']} F save",
                 style="dim")
        set_content(self.query_one("#result-count", Static), c, layout=False)

    def schedule_search(self) -> None:
        if self._timer is not None:
            self._timer.stop()
        self._timer = self.set_timer(0.18, self.run_search)

    # ------------------------------------------------------------- events
    def on_input_changed(self, ev: Input.Changed) -> None:
        if ev.input.id == "q":
            self.schedule_search()

    def on_input_submitted(self, ev: Input.Submitted) -> None:
        if ev.input.id == "q":
            if self._timer is not None:
                self._timer.stop()
            self.run_search()
            t = self.query_one("#results", DataTable)
            if t.row_count:
                t.focus()

    def on_select_changed(self, ev: Select.Changed) -> None:
        self.schedule_search()

    def on_switch_changed(self, ev: Switch.Changed) -> None:
        self.schedule_search()

    def on_button_pressed(self, ev: Button.Pressed) -> None:
        if ev.button.id == "f-today":
            m, d = church_date_today(self.app.ctx.cfg["calendar"])
            self.query_one("#f-month", Select).value = m
            self.query_one("#f-day", Select).value = d
            self.schedule_search()
        elif ev.button.id == "f-reset":
            self.action_reset()

    def on_data_table_row_highlighted(self, ev: DataTable.RowHighlighted) -> None:
        t = self.query_one("#results", DataTable)
        if ev.cursor_row >= t.row_count - 8:
            self._load_more()
        sid = int(ev.row_key.value) if ev.row_key is not None and ev.row_key.value else None
        if self._pv_timer is not None:
            self._pv_timer.stop()
        self._pv_timer = self.set_timer(0.08, lambda: self.show_preview(sid))

    # ------------------------------------------------------------- the preview (wide screens)
    def _highlighted_sid(self) -> int | None:
        t = self.query_one("#results", DataTable)
        if not t.row_count:
            return None
        try:
            return int(t.coordinate_to_cell_key(t.cursor_coordinate).row_key.value)
        except Exception:
            return None

    def layout_changed(self) -> None:
        if self.is_built:
            self.show_preview(self._highlighted_sid(), force=True)

    def show_preview(self, sid: int | None, force: bool = False) -> None:
        """The highlighted saint at a glance: icon, facts, the start of the life, the troparion."""
        if not self.is_built:
            return
        panel = self.query_one("#preview")
        if not panel.display or (sid == self._pv_sid and not force):
            self._pv_sid = sid if panel.display else None
            return
        self._pv_sid = sid
        ctx = self.app.ctx
        g = glyphs(self.app)
        s = ctx.db.get_saint(sid) if sid else None
        icon = self.query_one("#pv-icon", SaintIcon)
        head = self.query_one("#pv-head", Static)
        body = self.query_one("#pv-text", FitText)
        hymn = self.query_one("#pv-hymn", Static)
        if not s:
            set_content(head, Text("No saint highlighted.", style="dim italic"))
            body.set_text("")
            hymn.display = False
            icon.show(None, initial=g["cross"], mode=self.app.graphics_mode)
            set_content(self.query_one("#pv-keys", Static), "")
            return
        info = ctx.articles.summary(s)
        t = Text()
        t.append(info["name"], style=f"bold {self.app.current_theme.primary}")
        if ctx.db.is_favorite(s["id"]):
            t.append(f" {g['saved']}", style="bold")
        if info["subtitle"]:
            t.append("\n" + info["subtitle"], style="italic dim")
        t.append("\n")
        if info["feasts"]:
            days = [f"{MONTH_ABBR[m - 1]} {d}" for (m, d), _ in info["feasts"][:3]]
            t.append(f"\n{g['cross']} ", style="bold")
            t.append("Feast ", style="bold dim")
            t.append(" · ".join(days))
        for k, v in (("Lived", info["lived"]), ("From ", info["where"]), ("Kind ", ", ".join(info["kinds"][:2]))):
            if v:
                t.append(f"\n{g['dot']} ", style="bold")
                t.append(f"{k} ", style="bold dim")
                t.append(v)
        set_content(head, t)
        stories = ctx.db.stories(s["id"])
        lives = [x for x in stories if x["source"] in LIFE_SOURCES] or [x for x in stories if x["source"] == "wikical"]
        if lives:
            paras = [p.strip() for p in html_to_text(lives[0]["html"]).split("\n\n") if p.strip()]
            body.set_text(Text("\n\n".join(paras[:6])))
        elif s.get("description"):
            body.set_text(Text(s["description"][:1].upper() + s["description"][1:], style="italic"))
        else:
            body.set_text(Text("The sources record little more than the name and the day. Press Enter to look "
                               "the saint up online.", style="dim italic"))
        hymns = sorted((x for x in stories if x["source"] == "htc-hymn"), key=lambda x: x["title"])
        if hymns:
            ht = Text()
            ht.append(f"{g['hymn']} {N.hymn_heading(hymns[0]).upper()}\n", style="bold")
            ht.append(" ".join(x.strip() for x in hymns[0]["html"].replace("//", "/").split("/") if x.strip()),
                      style="italic")
            set_content(hymn, ht)
        hymn.display = bool(hymns)
        keys_t = Text()
        keys_t.append("on the results: ", style="dim italic")
        for k, what in ((g["enter"], "open"), ("F", "save"), ("P", "listen")):
            keys_t.append(f"{k}", style="bold")
            keys_t.append(f" {what}   ", style="dim")
        set_content(self.query_one("#pv-keys", Static), keys_t)
        show = ctx.cfg["show_icons"] and self.app.graphics_mode != "off"
        icon.display = show
        path = ctx.articles.icon_path(s) if show else None
        icon.show(path, initial=(short_name(s) or s["name"])[:1].upper(), mode=self.app.graphics_mode,
                  label=short_name(s))
        if self._pv_icon_timer is not None:
            self._pv_icon_timer.stop()
            self._pv_icon_timer = None
        if show and not path and s["kind"] in ("saint", "group", "angel"):
            sid0 = s["id"]
            self._pv_icon_timer = self.set_timer(0.7, lambda: self.load_preview_icon(sid0))   # once the cursor rests

    @work(thread=True, exclusive=True, group="preview-icon", exit_on_error=False)
    def load_preview_icon(self, sid: int) -> None:
        try:
            path = self.app.ctx.articles.fetch_icon(sid)
        except Exception:
            path = None
        if path and self._pv_sid == sid:
            self.app.call_from_thread(self.query_one("#pv-icon", SaintIcon).show, path)

    def listen(self) -> bool:
        """P on Search: hear the highlighted saint (what the directory holds)."""
        if not self.is_built:
            return False
        sid = self._highlighted_sid()
        reader = self.app.reader
        if sid is None:
            return False
        owner = ("search", sid)
        if reader.active and reader.owner == owner:
            reader.toggle()
            return True
        s = self.app.ctx.db.get_saint(sid)
        if not s:
            return False
        panel = self.query_one("#preview")
        self.app.start_reading(s["name"], N.saint_script(self.app.ctx, s, hymns=self.app.ctx.cfg["tts_hymns"],
                                                         target=panel if panel.display else None), owner)
        return True

    def on_data_table_row_selected(self, ev: DataTable.RowSelected) -> None:
        if ev.row_key and ev.row_key.value:
            self.post_message(OpenSaint(int(ev.row_key.value), context=list(self._ids), origin="search",
                                        total=self._total))

    # ------------------------------------------------------------- actions
    def action_focus_query(self) -> None:
        def go() -> None:
            q = self.query_one("#q", Input)
            q.focus()
            if self.typed_early:                  # keys typed while the page was being built
                q.insert_text_at_cursor(self.typed_early)
                self.typed_early = ""
        self.when_built(go, focus=True)

    def action_to_results(self) -> None:
        t = self.query_one("#results", DataTable)
        if t.row_count:
            t.focus()

    def action_reset(self) -> None:
        self.query_one("#q", Input).value = ""
        for sid in ("#f-month", "#f-day", "#f-gender", "#f-country", "#f-century", "#f-cat"):
            self.query_one(sid, Select).clear()
        self.query_one("#f-other", Switch).value = False
        self.query_one("#f-saved", Switch).value = False
        self.schedule_search()

    def action_toggle_saved(self) -> None:
        t = self.query_one("#results", DataTable)
        if not t.row_count:
            return
        try:
            key = t.coordinate_to_cell_key(t.cursor_coordinate).row_key.value
        except Exception:
            return
        sid = int(key)
        db = self.app.ctx.db
        on = not db.is_favorite(sid)
        db.set_favorite(sid, on)
        s = db.get_saint(sid)
        if s:
            self.app.notify(f"Saved {s['name']}" if on else f"Removed {s['name']} from your saved saints", timeout=3)
        self.app.favorites_changed()

    def favorites_changed(self) -> None:
        if self._loaded:
            if self._filters_cache and self._filters_cache.get("saved_only"):
                self.run_search(keep_cursor=True)
            else:
                self._refresh_names()
            self.show_preview(self._pv_sid, force=True)

    def _refresh_names(self) -> None:
        """Update the ★ marks without searching again."""
        t = self.query_one("#results", DataTable)
        g = glyphs(self.app)
        favs = self.app.ctx.db.favorite_ids()
        for sid in self._ids:
            try:
                cell = t.get_cell(str(sid), "name")
            except Exception:
                continue
            plain = cell.plain if isinstance(cell, Text) else str(cell)
            base = plain.replace(f" {g['saved']}", "")
            has_life = base.endswith(f" {g['life']}")
            if has_life:
                base = base[: -len(f" {g['life']}")]
            name = Text(base)
            if sid in favs:
                name.append(f" {g['saved']}", style="bold")
            if has_life:
                name.append(f" {g['life']}", style="dim")
            t.update_cell(str(sid), "name", name)

    def focus_first(self) -> None:
        self.action_focus_query()
