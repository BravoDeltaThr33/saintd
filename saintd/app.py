"""Saint Directory — the Textual application."""

from __future__ import annotations

import threading
import time
from pathlib import Path

from rich.text import Text
from textual import events, work
from textual.app import App, ComposeResult
from textual.screen import Screen
from textual.binding import Binding
from textual.css.query import NoMatches
from textual.containers import Horizontal
from textual.widgets import ContentSwitcher

from . import APP_NAME, graphics, term, tts
from .core import Context
from .net import Cancelled
from .sync import BUILD_VERSION, PARTIAL_BUILD, Report, church_date_today
from .themes import ALL_THEMES, theme_name
from .ui.chrome import TABS, ReaderBar, StatusBar, TabRail, TitleBar
from .ui.common import OpenSaint, SyncEvent, glyphs, keys
from .ui.focus import FocusPane
from .ui.home import HomePane
from .ui.modals import AskContact, ConfirmWipe, HelpScreen, IconView, ReadingsScreen, VoicePicker
from .ui.search import SearchPane
from .ui.settings import SettingsPane

def tab_hint(tab: str, g: dict) -> str:
    """The keys of a tab, for the status bar (shown when the terminal is wide)."""
    return {
        "home": f"[ ] day  T today  S Scripture  P listen  N random  F save {g['saved']}",
        "search": f"/ search box  {g['down']} results, then: {g['enter']} open  P listen  F save {g['saved']}  "
                  f"^R clear",
        "focus": "[ ] prev/next  P listen  V icon  F save  I header  R refresh  T contents  O browser  B back",
        "settings": "Tab / Shift+Tab move between the settings  Esc tab column",
    }.get(tab, "")


class SaintDirectoryApp(App):
    TITLE = APP_NAME
    CSS_PATH = Path(__file__).with_name("saintd.tcss")
    ENABLE_COMMAND_PALETTE = False
    BINDINGS = [
        Binding("f1", "tab('home')", "Home", priority=True),
        Binding("f2", "tab('search')", "Search", priority=True),
        Binding("f3", "tab('focus')", "Focus", priority=True),
        Binding("f4", "tab('settings')", "Settings", priority=True),
        Binding(keys("ctrl+b"), "build", "Build", priority=True),
        Binding(keys("ctrl+q"), "quit", "Quit", priority=True),
        Binding("question_mark", "help", "Help"),
        Binding("slash", "search_box", "Search box"),
        Binding("escape", "focus_rail", "Tabs"),
        # reading aloud (P starts what the open page offers; the rest work while reading)
        Binding(keys("p"), "listen", "Listen", show=False),
        Binding(keys("x"), "stop_reading", "Stop reading", show=False),
        Binding("comma,less_than_sign", "read_skip(-1)", "Previous paragraph", show=False),
        Binding("full_stop,greater_than_sign", "read_skip(1)", "Next paragraph", show=False),
        Binding("plus,equals_sign", "read_speed(1)", "Faster", show=False),
        Binding("minus", "read_speed(-1)", "Slower", show=False),
    ]

    def __init__(self, ctx: Context | None = None, graphics_mode: str | None = None) -> None:
        super().__init__()
        self.ctx = ctx or Context()
        for t in ALL_THEMES:
            self.register_theme(t)
        self.theme = theme_name(self.ctx.cfg["theme"], self.ctx.cfg["calendar"])
        if graphics_mode is None:
            graphics_mode = term.effective_mode(self.ctx.cfg["graphics"])
            if graphics_mode == "sixel" and not graphics.sixel_ready():
                graphics_mode = "blocks"
        self.graphics_mode = graphics_mode
        self.sixel_ready = graphics.sixel_ready()
        self._sync_kind = ""            # "" | "build" | "enrich"
        self._sync_stage = ""
        self._sync_prog = (0, 0, "")
        self._spin = 0
        self._wait_until = 0.0
        self._wait_host = ""
        self._last_input = time.monotonic()
        self.reader = tts.Reader(self.ctx.cfg, emit=self._reader_emit)
        self._reading_target = None

    # ------------------------------------------------------------ layout
    def compose(self) -> ComposeResult:
        yield TitleBar(id="titlebar")
        with Horizontal(id="body"):
            yield TabRail(id="rail")
            with ContentSwitcher(initial="home", id="pages"):
                yield HomePane(id="home")
                yield SearchPane(id="search")
                yield FocusPane(id="focus")
                yield SettingsPane(id="settings")
        yield ReaderBar(id="readerbar")
        yield StatusBar(id="statusbar")

    SIZE_CLASSES = ("-stack", "-compact", "-narrow", "-medium", "-wide", "-xwide", "-low", "-short", "-roomy",
                    "-tall", "-xtall", "-fill", "-pile", "-strip")

    @staticmethod
    def size_classes_for(w: int, h: int) -> dict[str, bool]:
        return {"-stack": w < 72, "-compact": w < 92, "-narrow": w < 120, "-medium": 120 <= w < 150, "-wide": w >= 150,
                "-xwide": w >= 180, "-low": h < 28, "-short": h < 34, "-roomy": h >= 38, "-tall": h >= 44,
                "-xtall": h >= 60,
                # the tabs as one row under the title bar, unless the terminal is big enough
                # for the tab column and its eagle without crowding the pages
                "-strip": w < 180 or h < 44,
                # the dashboard layouts that fill the whole window (no scrolling)
                "-fill": w >= 120 and h >= 30,
                # smaller: Home's panels in a grid, the saint of the day and readings under the rest
                "-pile": 72 <= w < 150 and not (w >= 120 and h >= 30)}

    def _size_classes(self, size=None) -> None:
        """Layout classes for the terminal size (one restyle, and only when they change)."""
        scr = getattr(self, "w_screen", None) or self.screen
        w, h = (size.width, size.height) if size is not None else (self.size.width, self.size.height)
        want = self.size_classes_for(w, h)
        add = [c for c, on in want.items() if on and not scr.has_class(c)]
        remove = [c for c, on in want.items() if not on and scr.has_class(c)]
        if add or remove:
            scr.set_classes([c for c in scr.classes if c not in self.SIZE_CLASSES] +
                            [c for c, on in want.items() if on])
            if ("-strip" in add or "-strip" in remove) and getattr(self, "w_rail", None) is not None:
                # the tabs moved between the column and the strip: label them (and the status bar) again
                self.call_after_refresh(self.w_rail.refresh_tabs)
                self.call_after_refresh(lambda: self.w_status.set_keys(getattr(self.w_status, "_extra", "")))
            for page in ("w_home", "w_search", "w_focus", "w_settings"):
                p = getattr(self, page, None)
                if p is not None and hasattr(p, "layout_changed"):
                    p.layout_changed()

    def on_resize(self, event: events.Resize) -> None:
        # this handler runs before App's own one, which is where self.size changes:
        # the event carries the new size (self.size would still be the old one)
        self._size_classes(event.size)

    def on_mount(self) -> None:
        # keep direct references: query_one() searches the *active* screen,
        # which is a dialog while one is open
        self.w_screen = self.screen
        self.w_title = self.query_one(TitleBar)
        self.w_rail = self.query_one(TabRail)
        self.w_status = self.query_one(StatusBar)
        self.w_pages = self.query_one("#pages", ContentSwitcher)
        self.w_home = self.query_one(HomePane)
        self.w_search = self.query_one(SearchPane)
        self.w_focus = self.query_one(FocusPane)
        self.w_settings = self.query_one(SettingsPane)
        self.w_reader = self.query_one(ReaderBar)
        self.w_reader.display = False
        self._size_classes()

        def on_wait(host, s):
            try:
                self.call_from_thread(self._on_wait, host, s)
            except Exception:
                pass
        self.ctx.http_bg.on_wait = on_wait
        self.w_status.set_keys(tab_hint("home", glyphs(self)))
        self.w_rail.focus()                 # Tab / Shift+Tab move between tabs; Enter opens the page
        self.set_interval(0.2, self._tick)
        self.set_interval(60, self.check_liturgical_colour)
        self.set_timer(1.5, self._prebuild)
        self._warm_frames()
        self.refresh_rail_info()
        if not self.ctx.directory_built():
            self.start_build()
        elif self.ctx.db.meta("build_version") == PARTIAL_BUILD:
            # some downloads failed last time: fetch what is missing (the rest comes from the cache)
            self.notify("Completing the directory (some downloads failed last time)…", title="Saint Directory",
                        timeout=5)
            self.start_build()
        elif self.ctx.db.meta("build_version") != BUILD_VERSION:
            # a newer saintd knows more sources: bring the directory up to date (linked data is kept)
            self.notify("Adding saints from the new sources… you can keep using the app meanwhile.",
                        title="Updating the directory", timeout=6)
            self.start_build()
        elif self.ctx.cfg["auto_enrich"] and self.ctx.cfg["use_wikimedia"]:
            self.start_enrich()
        if not self.ctx.cfg["asked_contact"] and not self.ctx.cfg["contact"] and self.ctx.cfg["use_wikimedia"]:
            self.push_screen(AskContact(), self._contact_answer)

    def _contact_answer(self, contact: str | None) -> None:
        cfg = self.ctx.cfg
        cfg.set("asked_contact", True)
        if contact:
            cfg.set("contact", contact)
            self.ctx.apply_network_settings()
            self.w_settings.contact_changed(contact)
            self.notify("Thank you — Wikimedia lookups will run at full speed.", timeout=4)
        self.w_rail.focus()

    # ------------------------------------------------------------ focus glow
    # The panel that holds the focus gets a bright double border. It is done
    # with inline styles on that one panel: a :focus-within CSS rule would
    # restyle every widget inside the panel on each focus change (slow).
    def on_descendant_focus(self, event: events.DescendantFocus) -> None:
        self._set_glow(self._glow_target(event.widget))

    def _glow_target(self, widget):
        node = widget
        while node is not None and not isinstance(node, (App, Screen)):
            if node.id in ("article", "focus-side") or node.has_class("panel"):
                return node
            node = node.parent
        return None

    def _set_glow(self, target, force: bool = False) -> None:
        old = getattr(self, "_glow", None)
        if old is target and not force:
            return
        if old is not None and old is not target and old.is_attached:
            old.styles.border = None
            old.styles.border_title_color = None
        self._glow = target
        if target is not None and target.is_attached:
            color = self.current_theme.primary
            target.styles.border = ("double", color)
            target.styles.border_title_color = color

    async def on_event(self, event: events.Event) -> None:
        if isinstance(event, (events.Key, events.MouseDown, events.MouseScrollDown, events.MouseScrollUp)):
            self._last_input = time.monotonic()
        if (isinstance(event, events.Key) and event.is_printable and not event.is_forwarded
                and getattr(self, "w_pages", None) is not None and self.screen is self.w_screen
                and self.focused is None
                and self.w_pages.current == "search" and self.w_search.lazy_ready and not self.w_search.is_built):
            self.w_search.typed_early += event.character or ""     # the search box is on its way
            return
        await super().on_event(event)

    def _prebuild(self) -> None:
        """Build the Search, Focus and Settings pages while the user is idle, one
        at a time, so that their first visit is instant without slowing the start-up."""
        if not self.w_pages.is_attached:
            return
        if time.monotonic() - self._last_input < 1.0:
            self.set_timer(1.0, self._prebuild)
            return
        for page in (self.w_search, self.w_focus, self.w_settings):
            if not page.lazy_ready:
                page.build()
                self.set_timer(1.0, self._prebuild)
                return

    # ------------------------------------------------------------ the eagle's light
    # In Kitty and Ghostty the light behind the eagle at the head of the tab column
    # swells and fades when you switch tabs (Home, Search, Focus, Settings) — and
    # at nothing else.
    def pulse(self, strength: float = 1.0) -> None:
        rail = getattr(self, "w_rail", None)
        if rail is not None:
            rail.pulse(strength)

    # ------------------------------------------------------------ navigation
    def show_tab(self, tab: str, focus_page: bool = False) -> None:
        if tab not in [t for t, _ in TABS]:
            return
        if tab != self.w_pages.current:
            self.pulse()                    # a new tab: the eagle's light swells and fades
        if tab == "search":
            self.w_search.ensure_loaded()
        elif tab == "focus":
            self.w_focus.ensure_built()
        elif tab == "settings":
            self.w_settings.ensure_built()
        page = self.page(tab)
        if not getattr(page, "is_built", True) and self.focused is not None and (
                focus_page or self.focused is not self.w_rail):
            # the page is still being built: keys must not reach the page being left
            self.w_screen.set_focus(None)
        self.w_pages.current = tab
        self.w_rail.active = tab
        self.w_status.set_keys(tab_hint(tab, glyphs(self)))
        if focus_page:
            self.focus_page()

    def page(self, tab: str | None = None):
        """The page widget of a tab (the open one by default)."""
        return {"home": self.w_home, "search": self.w_search, "focus": self.w_focus,
                "settings": self.w_settings}.get(tab or self.w_rail.active)

    def focus_page(self) -> None:
        page = self.page()
        if hasattr(page, "focus_first"):
            page.focus_first()
        else:
            self.screen.focus_next()

    def _main_screen_free(self) -> bool:
        """For keys that act on the main window while a dialog is open: Help and
        the readings are simply closed; a question (contact, delete) must be
        answered first."""
        scr = self.screen
        if scr is self.w_screen:
            return True
        if isinstance(scr, (HelpScreen, ReadingsScreen, IconView)):
            scr.dismiss()
            return True
        return False

    def action_tab(self, tab: str) -> None:
        if self._main_screen_free():
            self.show_tab(tab, focus_page=True)

    def action_focus_rail(self) -> None:
        self.w_rail.focus()

    def action_help(self) -> None:
        if not isinstance(self.screen, HelpScreen):
            self.push_screen(HelpScreen())

    def action_search_box(self) -> None:
        if self._main_screen_free():
            self.show_tab("search", focus_page=True)          # Search's first control is the box

    def on_open_saint(self, msg: OpenSaint) -> None:
        self.show_tab("focus")
        self.w_focus.show_saint(msg.sid, context=msg.context or [msg.sid], origin=msg.origin or "search",
                                total=msg.total)
        self.w_focus.focus_first()

    # ------------------------------------------------------------ theme/chrome
    def apply_theme(self) -> None:
        self.theme = theme_name(self.ctx.cfg["theme"], self.ctx.cfg["calendar"])
        self._set_glow(getattr(self, "_glow", None), force=True)
        self.w_home.render_banner()
        self.w_home.query_one("#cal").refresh()
        self.w_title.refresh_bar()
        self.w_rail.update_emblem()
        self._warm_frames()

    def check_liturgical_colour(self) -> None:
        """Liturgical Colours: change with the day (checked every minute)."""
        if self.ctx.cfg["theme"] == "liturgical" and \
                theme_name("liturgical", self.ctx.cfg["calendar"]) != self.theme:
            self.apply_theme()
            if self.w_settings.is_built:
                self.w_settings.theme_changed()

    def _warm_frames(self) -> None:
        """Paint the gilded frames for the usual icon sizes in the background."""
        if self.graphics_mode not in ("kitty", "sixel"):
            return
        try:
            bg = graphics.art._rgb(self.current_theme.surface)
        except Exception:
            return
        sizes = [(20, 10), (24, 12), (26, 13), (18, 9), (22, 11), (14, 8)]
        threading.Thread(target=graphics.warm_frames, args=(sizes, bg), name="saintd-frames", daemon=True).start()

    def refresh_chrome(self) -> None:
        """Redraw everything that shows symbols (Unicode <-> Plain ASCII)."""
        self.w_title.refresh_bar()
        self.w_rail.refresh_tabs()
        self.refresh_rail_info()
        self.w_home.render_banner()
        self.w_home.query_one("#cal").refresh()
        self.w_home.refresh_today()
        self.w_search.glyphs_changed()
        self.w_focus._relabel()
        self.w_focus._render_status()
        if self.w_focus.sid:
            s = self.ctx.db.get_saint(self.w_focus.sid)
            if s:
                self.w_focus._show_hero(s)
        self.w_status.set_keys(tab_hint(self.w_rail.active, glyphs(self)))
        self._spin = 0                           # the status bar's idle line is drawn again at the next tick

    def refresh_home(self) -> None:
        self.w_home.refresh_today()

    def calendar_changed(self) -> None:
        self.w_title.refresh_bar()
        self.w_home.calendar_changed()
        self.check_liturgical_colour()

    def favorites_changed(self) -> None:
        self.refresh_rail_info()                 # "N ★ saved"
        self.w_home.refresh_today()
        self.w_search.favorites_changed()
        self.w_focus._relabel()

    def set_graphics(self, setting: str) -> None:
        mode = term.effective_mode(setting)
        if mode == "sixel" and not graphics.sixel_ready():
            self.notify("Sixel pictures need a restart of saintd; using colour blocks until then.", timeout=5)
            mode = "blocks"
        self.graphics_mode = mode
        self.w_rail.update_emblem()
        self._warm_frames()
        self.w_home.set_graphics(mode)
        self.w_focus.set_graphics(mode)
        if self.w_focus.sid:
            s = self.ctx.db.get_saint(self.w_focus.sid)
            if s:
                self.w_focus._show_hero(s)
        self.w_settings.update_term_report()

    def refresh_rail_info(self) -> None:
        st = self.ctx.db.stats()
        g = glyphs(self)
        pct = int(100 * (st["enrichable"] - st["pending"]) / st["enrichable"]) if st["enrichable"] else 0
        filled = pct // 10
        t = Text()
        t.append(f"{st['people']:,}\n", style="bold")
        t.append("saints & groups\n\n", style="dim")
        t.append(f"{st['lives']:,}\n", style="bold")
        t.append("lives\n\n", style="dim")
        favs = len(self.ctx.db.favorite_ids())
        if favs:
            t.append(f"{favs:,} {g['saved']}\n", style="bold")
            t.append("saved\n\n", style="dim")
        t.append(g["full"] * filled + g["empty"] * (10 - filled) + f"\n{pct}% linked", style="")
        self.w_rail.set_info(t)

    def notify_directory_changed(self) -> None:
        self.refresh_rail_info()
        self.w_title.refresh_bar()
        self.w_settings.refresh_summary()

    # ------------------------------------------------------------ background sync
    def _post(self, msg) -> None:
        """Deliver a message from a worker thread (quietly ignored while quitting)."""
        try:
            self.call_from_thread(self.post_message, msg)
        except Exception:
            pass

    def _report(self) -> Report:
        def stage(s):
            self._post(SyncEvent("stage", stage=s))

        last = {"t": 0.0}

        def progress(d, t, msg):
            now = time.monotonic()
            if now - last["t"] < 0.25 and d < t:
                return
            last["t"] = now
            self._post(SyncEvent("progress", done=d, total=t, detail=msg))

        def log(m):
            self._post(SyncEvent("log", text=m))

        return Report(stage=stage, progress=progress, log=log)

    def action_build(self) -> None:
        if not isinstance(self.screen, (AskContact, ConfirmWipe)):
            self.start_build()

    def start_build(self) -> None:
        if self._sync_kind == "build":
            self.notify("The directory is already being built.", timeout=3)
            return
        self.ctx.http_bg.stop.set()          # stop any enrichment first
        self._sync_kind = "build"
        self.run_build()
        if not self.ctx.directory_built():
            self.refresh_home()              # "The directory is being built…"

    @work(thread=True, exclusive=True, group="sync", exit_on_error=False)
    def run_build(self) -> None:
        ctx = self.ctx
        while not ctx.syncer.lock.acquire(timeout=0.2):
            pass
        ctx.syncer.lock.release()
        ctx.http_bg.stop.clear()
        rep = self._report()
        ok, err = True, ""
        try:
            ctx.syncer.build(rep)
        except Cancelled:
            ok, err = False, "paused"
        except Exception as e:  # keep the app alive, report the problem
            ok, err = False, str(e)
        self._post(SyncEvent("finished", stage="build", text=err, done=1 if ok else 0))
        if ok and ctx.cfg["auto_enrich"] and ctx.cfg["use_wikimedia"]:
            self._enrich_body()

    def start_enrich(self, force: bool = False) -> None:
        if self._sync_kind:
            if force:
                self.notify("Background sync is already running.", timeout=3)
            return
        if not self.ctx.cfg["use_wikimedia"]:
            if force:
                self.notify("Wikidata/Wikipedia are turned off in Settings.", timeout=4)
            return
        self._sync_kind = "enrich"
        self.run_enrich()

    @work(thread=True, exclusive=True, group="sync", exit_on_error=False)
    def run_enrich(self) -> None:
        self._enrich_body()

    def _enrich_body(self) -> None:
        ctx = self.ctx
        try:
            self.call_from_thread(setattr, self, "_sync_kind", "enrich")
        except Exception:
            return
        rep = self._report()
        ok, err = True, ""
        try:
            m, d = church_date_today(ctx.cfg["calendar"])
            prio = [s["id"] for s in ctx.db.saints_on(m, d)]
            ctx.syncer.enrich(rep, priority=prio)
        except Cancelled:
            ok, err = False, "paused"
        except Exception as e:
            ok, err = False, str(e)
        self._post(SyncEvent("finished", stage="enrich", text=err, done=1 if ok else 0))

    def pause_sync(self) -> None:
        if self._sync_kind:
            self.ctx.http_bg.stop.set()
            self.notify("Pausing… progress so far is saved.", timeout=3)
        else:
            self.notify("Nothing is running in the background.", timeout=3)

    def confirm_wipe(self) -> None:
        def done(yes: bool | None) -> None:
            if yes:
                self.ctx.http_bg.stop.set()         # stop a build or link-up first
                self.wipe_directory()
        self.push_screen(ConfirmWipe(), done)

    @work(thread=True, exclusive=True, group="wipe", exit_on_error=False)
    def wipe_directory(self) -> None:
        lock = self.ctx.syncer.lock
        got = lock.acquire(timeout=20)              # wait for the background job to let go
        try:
            self.ctx.db.wipe()
        finally:
            if got:
                lock.release()
        try:
            self.call_from_thread(self._wiped)
        except Exception:
            pass

    def _wiped(self) -> None:
        self.notify("Local directory deleted. Press Ctrl+B (or Build / update in Settings) to rebuild.", timeout=6)
        self.w_focus.reset()
        self.w_search.directory_changed()
        self.refresh_home()
        self.notify_directory_changed()

    def _on_wait(self, host: str, seconds: float) -> None:
        self._wait_host, self._wait_until = host, time.monotonic() + seconds
        self.w_settings.write_log(f"{host} asked us to slow down; waiting {int(seconds)} s")

    def on_sync_event(self, ev: SyncEvent) -> None:
        try:
            self._sync_event(ev)
        except NoMatches:
            pass                            # the window is closing: a late message from the background

    def _sync_event(self, ev: SyncEvent) -> None:
        settings = self.w_settings
        home = self.w_home
        if ev.kind == "stage":
            self._sync_stage = ev.stage
            self._sync_prog = (0, 0, "")
            settings.write_log(ev.stage)
            settings.set_stage(ev.stage)
            if self._sync_kind == "build":
                home.set_stage(f"Building the directory — {ev.stage}")
            if ev.stage.startswith(("Lives", "Russian", "Translating", "Directory ready", "Matching")):
                self._directory_grew()
        elif ev.kind == "progress":
            self._sync_prog = (ev.done, ev.total, ev.detail)
        elif ev.kind == "log":
            settings.write_log(ev.text)
        elif ev.kind == "finished":
            what = "Directory build" if ev.stage == "build" else "Wikidata linking"
            linking = self.ctx.cfg["auto_enrich"] and self.ctx.cfg["use_wikimedia"]
            if ev.done:
                settings.write_log(f"{what} finished.")
                if ev.stage == "build":
                    self.notify("The directory is ready." + (" Linking saints to Wikipedia continues in the "
                                                             "background." if linking else ""),
                                title="Saint Directory", timeout=6)
            elif ev.text == "paused":
                settings.write_log(f"{what} paused.")
            else:
                settings.write_log(f"{what} stopped: {ev.text}")
                self.notify(f"{what} stopped: {ev.text}", severity="warning", timeout=8)
            # a linking run stopped to make way for a build must not reset the build's state
            if ev.stage == self._sync_kind:
                if ev.stage == "enrich" or not ev.done or not linking:
                    self._sync_kind = ""
                self._sync_stage = ""
                home.set_stage("")
                settings.set_stage("")
            self._directory_grew()

    def _directory_grew(self) -> None:
        self.notify_directory_changed()
        self.w_search.directory_changed()
        self.refresh_home()

    def _tick(self) -> None:
        if not hasattr(self, "w_status") or not self.w_status.is_attached:
            return
        g = glyphs(self)
        sb = self.w_status
        if not self._sync_kind:
            if self._spin % 25 == 0:
                st = self.ctx.db.stats()
                t = Text()
                t.append(f"{g['dot']} ", style="bold")
                linking = self.ctx.cfg["auto_enrich"] and self.ctx.cfg["use_wikimedia"]
                t.append("PAUSED" if st["pending"] and linking else "IDLE", style="bold")
                t.append(f"  {st['matched']:,} linked ", style="dim")
                sb.set_sync(t)
            self._spin += 1
            return
        self._spin += 1
        d, tot, detail = self._sync_prog
        t = Text()
        t.append(g["spin"][self._spin % len(g["spin"])] + " ", style="bold")
        t.append("BUILD " if self._sync_kind == "build" else "LINK ", style="bold")
        if tot:
            pct = int(100 * d / tot)
            n = pct // 10
            t.append(g["full"] * n + g["empty"] * (10 - n) + f" {pct:3d}% ")
        stage = self._sync_stage.split(" (")[0]
        t.append(f"{stage[:28]} {detail[:18]} ", style="dim")
        if self._wait_until > time.monotonic():
            t.append(f"(waiting {int(self._wait_until - time.monotonic())}s) ", style="italic")
        sb.set_sync(t)
        if self._spin % 50 == 0:
            self.refresh_rail_info()
            if self._sync_kind == "enrich":
                self.w_settings.refresh_summary()

    # ------------------------------------------------------------ reading aloud
    def _reader_emit(self, ev: str) -> None:
        """From the reader (any thread) to the interface thread."""
        if threading.current_thread() is threading.main_thread():
            self.call_later(self.on_reader_event, ev)
            return
        try:
            self.call_from_thread(self.on_reader_event, ev)
        except Exception:                        # quitting
            pass

    def start_reading(self, title: str, chunks: list, owner) -> None:
        """Read chunks aloud. The first time, if Piper is installed without a voice,
        offer to download one."""
        if not chunks:
            self.notify("There is nothing to read here yet.", timeout=3)
            return
        cfg = self.ctx.cfg
        piper = tts.ENGINES["piper"]
        if (cfg["tts_engine"] in ("auto", "piper") and not cfg["tts_asked_voice"] and piper.available()
                and not any(v.installed for v in piper.voices())):
            def chosen(voice: str | None) -> None:
                cfg.set("tts_asked_voice", True)
                if voice:
                    cfg.set_voice("piper", voice)
                tts.forget_voices()
                if voice != "":                    # "" = Not now
                    self._begin_reading(title, chunks, owner)
            self.push_screen(VoicePicker(), chosen)
            return
        self._begin_reading(title, chunks, owner)

    def _begin_reading(self, title: str, chunks: list, owner) -> None:
        self._clear_highlight()
        self.reader.start(title, chunks, owner)
        self.on_reader_event("state")

    def on_reader_event(self, ev: str) -> None:
        r = self.reader
        if ev == "chunk" and r.active and r.chunks:
            self._highlight(r.chunks[min(r.index, len(r.chunks) - 1)])
        elif ev == "error":
            self.notify(r.error or "Reading stopped.", severity="warning", timeout=8, title="Reading aloud")
        elif ev == "done":
            self.notify(f"Finished reading: {r.title}", timeout=3)
        if not r.active:
            self._clear_highlight()
        if not getattr(self, "w_reader", None) or not self.w_reader.is_attached:
            return
        self.w_reader.show_reader(r, glyphs(self))
        for page in (self.w_focus, self.w_home, self.w_search, self.w_settings):
            if hasattr(page, "reader_changed"):
                page.reader_changed()

    def _owner_page(self):
        owner = self.reader.owner or ()
        kind = owner[0] if owner else ""
        return {"saint": self.w_focus, "day": self.w_home, "spot": self.w_home, "search": self.w_search,
                "test": self.w_settings}.get(kind)

    def _highlight(self, chunk) -> None:
        target = chunk.target
        if target is not None and not getattr(target, "is_attached", False):
            page = self._owner_page()
            resolve = getattr(page, "resolve_target", None)
            target = resolve(chunk) if resolve else None
        if target is self._reading_target:
            return
        self._clear_highlight()
        if target is None or not target.is_attached:
            return
        target.add_class("-reading")
        if target.has_class("panel"):
            target.border_subtitle = f"{glyphs(self)['hymn']} reading"
        self._reading_target = target
        if self.ctx.cfg["tts_follow"]:
            self._follow(target)

    def _clear_highlight(self) -> None:
        old, self._reading_target = self._reading_target, None
        if old is not None and old.is_attached:
            old.remove_class("-reading")
            if old.has_class("panel"):
                old.border_subtitle = ""

    def _follow(self, widget) -> None:
        """Keep the paragraph being read in view (in its own scrolling area)."""
        node = widget.parent
        while node is not None and not isinstance(node, (App, Screen)):
            if getattr(node, "allow_vertical_scroll", False):
                node.scroll_to_center(widget, animate=True, origin_visible=True)
                return
            node = node.parent

    def action_listen(self) -> None:
        if not self._main_screen_free():
            return
        page = self.page()
        if page is not None and hasattr(page, "listen") and page.listen():
            return
        if self.reader.active:
            self.reader.toggle()
            return
        self.notify("Open a saint in Focus (F3) — or go Home (F1) — and press P to listen.", timeout=4)

    def action_stop_reading(self) -> None:
        if self.reader.active:
            self.reader.stop()
            self.notify("Stopped reading.", timeout=2)

    def action_read_skip(self, step: int) -> None:
        if self.reader.active:
            self.reader.skip(step)

    def action_read_speed(self, step: int) -> None:
        rates = tts.RATES
        cur = self.reader.rate
        if step > 0:
            new = next((r for r in rates if r > cur + 0.01), rates[-1])
        else:
            new = next((r for r in reversed(rates) if r < cur - 0.01), rates[0])
        self.reader.set_rate(new)
        self.notify(f"Reading speed {new:g}×" + ("" if self.reader.active else " (for the next reading)"), timeout=2)
        self.on_reader_event("state")

    async def action_quit(self) -> None:
        self.reader.shutdown()
        self.ctx.http_bg.stop.set()
        self.ctx.http_fg.stop.set()
        driver = getattr(self, "_driver", None)
        if driver is not None and self.graphics_mode == "kitty":
            graphics.kitty_forget_all(driver.write)
        self.exit()

    def on_unmount(self) -> None:
        try:
            self.reader.shutdown()
        except Exception:
            pass
        try:
            self.ctx.close()
        except Exception:
            pass


def run() -> int:
    from .config import Config
    info = term.detect()                      # ask the terminal about itself before Textual takes over
    cfg = Config()
    mode = graphics.prepare(term.effective_mode(cfg["graphics"], info))
    app = SaintDirectoryApp(Context(cfg), graphics_mode=mode)
    app.run()
    return 0


__all__ = ["SaintDirectoryApp", "run"]
