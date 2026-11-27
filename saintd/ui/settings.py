"""Settings tab: colour scheme, display & pictures, calendar, sources,
translation, network, directory maintenance and API information.

The controls are built the first time the tab is opened, which keeps the
app's start-up quick."""

from __future__ import annotations

import subprocess
import sys
import threading
import time

from rich.text import Text
from textual import work
from textual.css.query import NoMatches
from textual.app import ComposeResult
from textual.containers import Grid, Horizontal, Vertical, VerticalScroll
from textual.widgets import Button, Input, Label, ProgressBar, RadioButton, RadioSet, RichLog, Select, Static, Switch

from .. import icons, system, term, tts
from ..config import TRANSLATORS
from ..net import NetError
from ..sources import SOURCES
from ..themes import LITURGICAL_VARIANTS, THEMES, liturgical_colour
from ..translate import BACKEND_INFO, TranslationError
from .common import LazyPage, glyphs, set_content

SOURCE_SWITCHES = (
    ("include_greek", "Include Greek-tradition commemorations (orthocal)"),
    ("use_azbyka", "Include the Russian calendar (Azbuka Very), translated to English"),
    ("use_wikical", "Include Wikipedia's Orthodox calendar (366 Great Synaxaristes day pages)"),
    ("use_wikimedia", "Use Wikidata facts and Wikipedia articles"),
    ("use_wikidata_saints", "Add the Orthodox saints with a feast day that only Wikidata lists"),
    ("auto_enrich", "Keep linking saints to Wikidata in the background"),
    ("translate_articles", "Translate non-English Wikipedia articles when no English one exists"),
    ("use_htc", "Read lives, troparia and kontakia from the Holy Trinity Orthodox Calendar"),
    ("use_orthodoxwiki", "Use OrthodoxWiki articles when Wikipedia has none"),
    ("use_mystagogy", "Look up lives on the Mystagogy Resource Center when the calendars have none"),
    ("use_azbyka_lives", "Translate the Russian life from Azbuka Very when no English life exists"),
)


def swatch(colors: list[str]) -> Text:
    t = Text()
    for c in colors:
        t.append("██", style=c)
    return t


class SettingsPane(LazyPage, VerticalScroll):
    def __init__(self, **kw) -> None:
        super().__init__(**kw)
        self._status: dict[str, str] = {}
        self._log: list[str] = []
        self._stage = ""

    def compose(self) -> ComposeResult:
        if not self.lazy_ready:          # built on the first visit (keeps start-up quick)
            yield Static("Opening Settings…", classes="lazy-wait")
            return
        panels = {p.id: p for p in self._panels()}
        cols = Horizontal(id="set-cols")
        for cid, ids in (("set-col-a", ("set-theme", "set-display", "set-voice", "set-cal")),
                         ("set-col-b", ("set-src", "set-tr", "set-net", "set-dir"))):
            col = Vertical(id=cid)
            for pid in ids:
                col.compose_add_child(panels.pop(pid))
            cols.compose_add_child(col)
        yield cols
        yield from panels.values()                 # the data sources, full width

    # ------------------------------------------------------------ building
    def ensure_built(self) -> None:
        self.build()

    def _swatch_line(self, t: dict) -> Text:
        """The colours of a scheme and a word about it (Liturgical Colours: today's colour and why)."""
        if t["key"] == "liturgical":
            import datetime as dt
            colour, why = liturgical_colour(dt.date.today(), self.app.ctx.cfg["calendar"])
            v = LITURGICAL_VARIANTS[colour]
            return Text.assemble(swatch(v["swatch"]), "  ", (f"Today {v['title'].lower()}: {why}.", "italic"))
        return Text.assemble(swatch(t["swatch"]), "  ", (t["blurb"], "italic"))

    def theme_changed(self) -> None:
        if self.is_built:
            self.query_one("#sw-th-liturgical", Static).update(self._swatch_line(
                next(t for t in THEMES if t["key"] == "liturgical")))

    def _panels(self):
        cfg = self.app.ctx.cfg
        info = term.current()
        # ------------------------------------------------------- appearance
        theme = Vertical(id="set-theme", classes="panel")
        theme.compose_add_child(_row(
            _radio("theme-set", [(t["title"], cfg["theme"] == t["key"], f"th-{t['key']}") for t in THEMES]),
            _col("swatches", [Static(self._swatch_line(t), classes="swatch", id=f"sw-th-{t['key']}")
                              for t in THEMES])))
        theme.compose_add_child(_row(
            Label("Symbols", classes="s-label"),
            _radio("glyph-set", [("Unicode ☦ ⚙ ◎", cfg["glyphs"] != "ascii", "gl-unicode"),
                                 ("Plain ASCII", cfg["glyphs"] == "ascii", "gl-ascii")], inline=True)))
        yield theme
        # ------------------------------------------------------- display
        disp = Vertical(id="set-display", classes="panel")
        modes = [(f"Automatic — {term.MODE_LABELS[info.best_graphics()]}", "auto")]
        for m in term.GRAPHICS_MODES:
            label = term.MODE_LABELS[m]
            if m != "off" and not info.supports(m):
                label += " (not detected)"
            modes.append((label, m))
        disp.compose_add_child(_row(Label("Pictures", classes="s-label"),
                                    Select(modes, value=cfg["graphics"] if cfg["graphics"] in ("auto", *term.GRAPHICS_MODES)
                                           else "auto", allow_blank=False, id="gfx-mode", compact=True),
                                    Button("Clear icon cache", id="gfx-clear", compact=True)))
        sw = Horizontal(classes="sw-row")
        sw.compose_add_child(Switch(value=bool(cfg["show_icons"]), id="sw-show_icons", classes="mini"))
        sw.compose_add_child(Label("Download and show icons of the saints", classes="sw-label"))
        disp.compose_add_child(sw)
        disp.compose_add_child(Static(id="term-report", classes="term-report"))
        yield disp
        # ------------------------------------------------------- reading aloud
        voice = Vertical(id="set-voice", classes="panel")
        engines = [("Automatic — the best one found", "auto")] + [(tts.ENGINES[e].label, e) for e in tts.ENGINE_ORDER]
        voice.compose_add_child(_row(Label("Engine", classes="s-label"),
                                     Select(engines, value=cfg["tts_engine"], allow_blank=False, id="tts-engine",
                                            compact=True),
                                     Button("Test voice", id="tts-test", compact=True)))
        voice.compose_add_child(_row(Label("Voice", classes="s-label"),
                                     Select([], prompt="Looking for voices…", id="tts-voice", compact=True)))
        rate = round(float(cfg["tts_rate"]), 2)
        rates = sorted(set(tts.RATES) | {rate})           # a speed set in the file keeps its place
        voice.compose_add_child(_row(Label("Speed", classes="s-label"),
                                     Select([(f"{r:g}×" + (" (normal)" if r == 1.0 else ""), r) for r in rates],
                                            value=rate, allow_blank=False, id="tts-rate", compact=True)))
        switches = Vertical(id="tts-switches")
        for key, text in (("tts_follow", "Highlight the paragraph being read and keep it in view"),
                          ("tts_hymns", "Read the troparion and kontakion too"),
                          ("tts_history", "Read the history (Wikipedia, OrthodoxWiki) after the life")):
            sw = Horizontal(classes="sw-row")
            sw.compose_add_child(Switch(value=bool(cfg[key]), id=f"sw-{key}", classes="mini"))
            sw.compose_add_child(Label(text, classes="sw-label"))
            switches.compose_add_child(sw)
        voice.compose_add_child(switches)
        voice.compose_add_child(Static(id="tts-engines", classes="term-report"))
        voice.compose_add_child(_row(Label("Natural voices", classes="s-label"),
                                     Select([], prompt="Piper voices to download", id="tts-get", compact=True),
                                     Button("Download", id="tts-download", compact=True),
                                     Button("Delete voice", id="tts-delete", compact=True),
                                     Button("Install Piper", id="tts-install", compact=True), id="tts-get-row"))
        voice.compose_add_child(ProgressBar(id="tts-progress", show_eta=False))
        voice.compose_add_child(Static(id="tts-status", classes="hint"))
        yield voice
        # ------------------------------------------------------- calendar
        calp = Vertical(id="set-cal", classes="panel")
        calp.compose_add_child(_radio("cal-set", [("New Calendar (Revised Julian)", cfg["calendar"] != "old", "cal-new"),
                                                  ("Old Calendar (Julian, 13 days later)", cfg["calendar"] == "old",
                                                   "cal-old")], inline=True))
        calp.compose_add_child(Static("Feast days are church dates. On the Old Calendar each one falls 13 days later "
                                      "on the civil calendar; Home and Focus show both.", classes="hint"))
        yield calp
        # ------------------------------------------------------- sources
        src = Vertical(id="set-src", classes="panel")
        for key, text in SOURCE_SWITCHES:
            row = Horizontal(classes="sw-row")
            row.compose_add_child(Switch(value=bool(cfg[key]), id=f"sw-{key}", classes="mini"))
            row.compose_add_child(Label(text, classes="sw-label"))
            src.compose_add_child(row)
        src.compose_add_child(Static("Turning a calendar source on or off takes effect at the next Build / update; "
                                     "the life sources are used the next time you open a saint.", classes="hint"))
        yield src
        # ------------------------------------------------------- translation
        tr = Vertical(id="set-tr", classes="panel")
        tr.compose_add_child(_row(Label("Translator", classes="s-label"),
                                  Select([(BACKEND_INFO[b][0], b) for b in TRANSLATORS],
                                         value=cfg["translator"] if cfg["translator"] in TRANSLATORS else "off",
                                         allow_blank=False, id="tr-backend", compact=True),
                                  Button("Test translator", id="tr-test", compact=True)))
        tr.compose_add_child(Static(id="tr-info", classes="hint"))
        tr.compose_add_child(_row(Label("E-mail (optional)", classes="s-label"),
                                  Input(cfg["mymemory_email"], placeholder="raises MyMemory's free limit to ~50k chars/day",
                                        id="in-mymemory_email"), classes="set-row tr-opt", id="row-mymemory"))
        tr.compose_add_child(_row(Label("Lingva instance", classes="s-label"), Input(cfg["lingva_url"], id="in-lingva_url"),
                                  classes="set-row tr-opt", id="row-lingva"))
        tr.compose_add_child(_row(Label("LibreTranslate", classes="s-label"), Input(cfg["libre_url"], id="in-libre_url"),
                                  Input(cfg["libre_key"], placeholder="API key (optional)", password=True,
                                        id="in-libre_key"), classes="set-row tr-opt", id="row-libre"))
        tr.compose_add_child(_row(Label("Ollama", classes="s-label"), Input(cfg["ollama_url"], id="in-ollama_url"),
                                  Input(cfg["ollama_model"], placeholder="model, e.g. qwen3:8b", id="in-ollama_model"),
                                  Button("Detect", id="tr-detect", compact=True), classes="set-row tr-opt",
                                  id="row-ollama"))
        tr.compose_add_child(Static(id="tr-result", classes="hint"))
        yield tr
        # ------------------------------------------------------- network
        net = Vertical(id="set-net", classes="panel")
        net.compose_add_child(_row(Label("Contact", classes="s-label"),
                                   Input(cfg["contact"], placeholder="your e-mail or web address — lets Wikimedia "
                                         "allow ~15× faster lookups", id="in-contact")))
        net.compose_add_child(Static(id="net-rate", classes="hint"))
        timeout = int(cfg["timeout"])
        net.compose_add_child(_row(Label("Timeout", classes="s-label"),
                                   Select([(f"{t} s", t) for t in sorted({10, 25, 45, 90, timeout})],
                                          value=timeout, allow_blank=False, id="net-timeout", compact=True)))
        yield net
        # ------------------------------------------------------- directory
        dirp = Vertical(id="set-dir", classes="panel")
        dirp.compose_add_child(Static(id="dir-summary"))
        dirp.compose_add_child(ProgressBar(id="set-progress", show_eta=False))
        dirp.compose_add_child(Static(id="set-stage", classes="hint"))
        grid = Grid(id="dir-buttons")
        for label, bid, variant in (("Build / update", "d-build", "primary"), ("Link to Wikidata now", "d-enrich", "default"),
                                    ("Pause", "d-pause", "default"), ("Retry failed lookups", "d-retry", "default"),
                                    ("Clear caches", "d-clear", "default"),
                                    ("Delete everything", "d-wipe", "error")):
            grid.compose_add_child(Button(label, id=bid, variant=variant, compact=True))
        dirp.compose_add_child(grid)
        dirp.compose_add_child(RichLog(id="sync-log", max_lines=400, wrap=True, markup=False))
        yield dirp
        # ------------------------------------------------------- APIs
        api = Vertical(id="set-api", classes="panel")
        for s in SOURCES:
            api.compose_add_child(Static(id=f"api-{s['id']}", classes="api-card"))
        api.compose_add_child(_row(Button("Test connections", id="api-test", compact=True), classes="btn-row"))
        api.compose_add_child(Static(id="api-notes", classes="hint"))
        yield api

    def built(self) -> None:
        for wid, title in (("#set-theme", "COLOR SCHEME"), ("#set-display", "DISPLAY & PICTURES"),
                           ("#set-voice", "VOICE & READING ALOUD"),
                           ("#set-cal", "CALENDAR"), ("#set-src", "SOURCES"), ("#set-tr", "TRANSLATION"),
                           ("#set-net", "NETWORK"), ("#set-dir", "DIRECTORY"),
                           ("#set-api", "DATA SOURCES & API INFORMATION")):
            self.query_one(wid).border_title = title
        self.fill_api_table()
        self.update_translator_rows()
        self.update_rate_hint()
        self.refresh_summary()
        self.update_term_report()
        self.set_stage(self._stage)
        log = self.query_one("#sync-log", RichLog)
        for line in self._log:
            log.write(line)
        self._log.clear()
        self.query_one("#api-notes", Static).update(
            "No API keys or paid subscriptions are needed. Lives come from orthocal.info and, for saints it has no "
            "Life for, from the Holy Trinity Orthodox Calendar, the Mystagogy Resource Center (English) or the "
            "saint's Azbuka Very page (translated); hymns from the Holy Trinity calendar; most of the directory "
            "comes from Wikipedia's 366 Orthodox calendar day pages, and Orthodox saints no calendar lists from "
            "Wikidata; facts from Wikidata (CC0); articles from "
            "Wikipedia (CC BY-SA 4.0) and OrthodoxWiki (GFDL / CC BY-SA 2.5), credited on every Focus page; icons "
            "from Wikimedia Commons, OrthodoxWiki, Azbuka Very and the Mystagogy Resource Center; the day's "
            "feasts, fast and Scripture readings from orthocal.info.")
        self._highlight_choices()
        self.query_one("#tts-progress", ProgressBar).display = False
        self._voice_stop: threading.Event | None = None
        self.scan_voices()

    # ------------------------------------------------------------ reading aloud
    @work(thread=True, exclusive=True, group="tts-scan", exit_on_error=False)
    def scan_voices(self) -> None:
        """Which engines and voices this computer has (some take a moment to answer)."""
        report = []
        # these can take a few seconds to answer
        slow = [x for x in ("speechd", "festival", "sapi") if x in tts.ENGINE_ORDER]

        def count(eid: str) -> tuple[str, bool, int]:
            e = tts.ENGINES[eid]
            ok = e.available()
            have = [v for v in e.voices() if v.installed] if ok else []
            return eid, ok, len([v for v in have if v.id]) or len(have)     # "the system voice" is one of them

        for eid in tts.ENGINE_ORDER:
            if eid not in slow:
                report.append(count(eid))
        # show the quick answers at once (the slow engines as found, their voices still being counted)
        self._post_scan(report + [(x, tts.ENGINES[x].available(), 0) for x in slow])
        report += [count(x) for x in slow]
        catalog = tts.piper_catalog() if tts.ENGINES["piper"].available() else {}
        self._post_scan(report, bool(catalog))

    def _post_scan(self, report: list, have_catalog: bool = False) -> None:
        order = {e: i for i, e in enumerate(tts.ENGINE_ORDER)}
        report = sorted(report, key=lambda r: order[r[0]])
        try:
            self.app.call_from_thread(self._voices_scanned, report, have_catalog)
        except Exception:
            pass

    def _effective_engine(self) -> tts.Engine | None:
        cfg = self.app.ctx.cfg
        if cfg["tts_engine"] != "auto":
            return tts.ENGINES.get(cfg["tts_engine"])
        e, _ = tts.resolve(cfg)
        return e

    def _voices_scanned(self, report: list, have_catalog: bool) -> None:
        if not self.is_built:
            return
        g = glyphs(self.app)
        cfg = self.app.ctx.cfg
        t = Text()
        t.append("  Engines on this computer\n", style="bold")
        for eid, ok, n in report:
            e = tts.ENGINES[eid]
            t.append(f"  {g['ok'] if ok else g['bad']} ", style="bold" if ok else "dim")
            t.append(f"{e.label.split(' (')[0]:<18}", style="bold" if ok else "dim")
            if not ok:
                t.append(f" install:  {e.install}\n", style="dim")
            elif eid == "piper":
                t.append(f" {n} voice{'s' if n != 1 else ''} downloaded" + ("" if n else " — choose one below") + "\n",
                         style="" if n else "italic")
            elif e.direct:
                t.append(" speaks through the desktop's speech service\n")
            else:
                t.append(f" {n} voice{'s' if n != 1 else ''}\n")
        players = tts.players()
        t.append(f"  {g['ok'] if players else g['bad']} ", style="bold")
        t.append(f"{'Audio player':<18}", style="bold")
        t.append(f" {players[0]}" if players else f" none found:  {tts.PLAYER_INSTALL}", style="")
        e, v = tts.resolve(cfg)
        t.append("\n  Reading with  ", style="bold dim")
        t.append(f"{e.label} {g['sep']} {e.voice_label(v)}" if e else "no engine yet", style="bold")
        self.query_one("#tts-engines", Static).update(t)
        auto = self.query_one("#tts-engine", Select)
        with self.prevent(Select.Changed):
            opts = [(f"Automatic — {e.label.split(' (')[0]}" if e else "Automatic — none found yet", "auto")]
            for eid, ok, n in report:
                lab = tts.ENGINES[eid].label
                if not ok:
                    lab += " (not installed)"
                elif eid == "piper" and not n:
                    lab += " (no voice yet)"
                opts.append((lab, eid))
            _set_options(auto, opts, auto.selection or cfg["tts_engine"])     # never undo the user's choice
        self.fill_voices()
        self.fill_downloads()

    def fill_voices(self) -> None:
        cfg = self.app.ctx.cfg
        e = self._effective_engine()
        sel = self.query_one("#tts-voice", Select)
        voices = [v for v in e.voices() if v.installed] if e is not None and e.available() else []
        with self.prevent(Select.Changed):
            sel.set_options([(v.label, v.id or "-") for v in voices])
            if voices:
                want = cfg.voice_for(e.id) or e.default_voice()
                ids = [v.id or "-" for v in voices]
                sel.value = want if want in ids else ids[0]
        sel.prompt = "No voices" if not voices else "Choose a voice"
        piper = tts.ENGINES["piper"]
        self.query_one("#tts-delete", Button).display = e is piper and bool(voices)
        self.query_one("#tts-install", Button).display = not piper.available()
        self.query_one("#tts-download", Button).display = piper.available()
        self.query_one("#tts-get", Select).display = piper.available()

    def fill_downloads(self) -> None:
        piper = tts.ENGINES["piper"]
        sel = self.query_one("#tts-get", Select)
        if not piper.available():
            return
        catalog = tts.piper_catalog(http_get=lambda url: b"{}") or {}
        voices = [v for v in piper.voices() if not v.installed]
        with self.prevent(Select.Changed):
            opts = []
            for v in voices:
                size = sum(sz for _, sz, _ in tts.piper_files(v.id, catalog)) or v.size
                opts.append((f"{v.label}  ({size / 1e6:.0f} MB)", v.id))
            _set_options(sel, opts, sel.selection)      # a scan finishing must not undo the user's pick

    def listen(self) -> bool:
        return False

    def reader_changed(self) -> None:
        pass

    def _tts_select_changed(self, sid: str, val) -> None:
        cfg = self.app.ctx.cfg
        if sid == "tts-engine":
            cfg.set("tts_engine", val)
            self.fill_voices()
            self.scan_voices()
        elif sid == "tts-voice":
            e = self._effective_engine()
            if e is not None:
                cfg.set_voice(e.id, "" if val == "-" else val)
                self.scan_voices()
        elif sid == "tts-rate":
            self.app.reader.set_rate(float(val))
            self.app.on_reader_event("state")

    def test_voice(self) -> None:
        cfg = self.app.ctx.cfg
        e = self._effective_engine()
        if e is None or not tts.usable(e):
            self.query_one("#tts-status", Static).update(
                "No engine can speak yet. Install one (see the list above) or download a Piper voice.")
            return
        v = self.query_one("#tts-voice", Select).selection
        voice = "" if v in (None, "-") else v
        if not voice:
            voice = cfg.voice_for(e.id) or e.default_voice()
        self.app.reader.start("Voice test", [tts.Chunk(tts.SAMPLE)], ("test",), engine=e, voice=voice)
        self.app.on_reader_event("state")

    def download_voice(self) -> None:
        key = self.query_one("#tts-get", Select).selection
        if not key:
            self.query_one("#tts-status", Static).update("Choose a voice to download first.")
            return
        if self._voice_stop is not None:
            self.query_one("#tts-status", Static).update("A voice is already being downloaded.")
            return
        self._voice_stop = threading.Event()
        bar = self.query_one("#tts-progress", ProgressBar)
        bar.display = True
        bar.update(total=100, progress=0)
        self.query_one("#tts-status", Static).update(f"Downloading {key}…")
        stop = self._voice_stop

        def run() -> None:
            def progress(done: int, total: int) -> None:
                try:
                    self.app.call_from_thread(self._dl_progress, done, total)
                except Exception:
                    pass
            try:
                tts.download_piper_voice(key, progress, stop, catalog=tts.piper_catalog())
                ok, msg = True, ""
            except Exception as e:
                ok, msg = False, str(e)
            try:
                self.app.call_from_thread(self._dl_done, key, ok, msg)
            except Exception:
                pass
        threading.Thread(target=run, name="saintd-voice-download", daemon=True).start()

    def _dl_progress(self, done: int, total: int) -> None:
        self.query_one("#tts-progress", ProgressBar).update(total=max(1, total), progress=done)
        self.query_one("#tts-status", Static).update(f"Downloading… {done / 1e6:.0f} of {total / 1e6:.0f} MB")

    def _dl_done(self, key: str, ok: bool, msg: str) -> None:
        self._voice_stop = None
        self.query_one("#tts-progress", ProgressBar).display = False
        cfg = self.app.ctx.cfg
        if ok:
            cfg.set_voice("piper", key)
            cfg.set("tts_asked_voice", True)
            tts.forget_voices()
            self.query_one("#tts-status", Static).update(f"Downloaded {key}. Press Test voice to hear it.")
            self.app.notify(f"New voice ready: {key}", timeout=4)
        else:
            self.query_one("#tts-status", Static).update(f"The download failed: {msg}")
        self.scan_voices()

    def delete_voice(self) -> None:
        e = self._effective_engine()
        v = self.query_one("#tts-voice", Select).selection
        if e is None or e.id != "piper" or not v or v == "-":
            return
        if self.app.reader.active and self.app.reader.voice == v:
            self.app.reader.stop()
        try:
            tts.delete_piper_voice(v)
        except tts.TTSError as err:
            self.query_one("#tts-status", Static).update(f"The voice was not deleted: {err}")
            return
        tts.forget_voices()
        self.query_one("#tts-status", Static).update(f"Deleted the voice {v}.")
        self.scan_voices()

    @work(thread=True, exclusive=True, group="tts-install", exit_on_error=False)
    def install_piper(self) -> None:
        """Install the piper-tts package into saintd's own Python environment."""
        def say(msg: str) -> None:
            try:
                self.app.call_from_thread(self.query_one("#tts-status", Static).update, msg)
            except Exception:
                pass
        say("Installing Piper (about 60 MB of Python packages)… this takes a minute.")
        try:
            r = subprocess.run([sys.executable, "-m", "pip", "install", "--disable-pip-version-check", "-q",
                                "piper-tts"], capture_output=True, text=True, timeout=1200, **system.detached())
            ok = r.returncode == 0
            err = (r.stderr or r.stdout or "").strip().splitlines()[-1:] if not ok else []
        except Exception as e:
            ok, err = False, [str(e)]
        import importlib
        importlib.invalidate_caches()
        tts.forget_voices()
        if ok:
            say("Piper is installed. Choose a natural voice below and press Download.")
        else:
            say("Piper could not be installed here" + (f": {err[0][:120]}" if err else "") + ". " +
                system.pick("From a terminal:  pipx inject saint-directory piper-tts",
                            "From a terminal:  pipx inject saint-directory piper-tts",
                            "Run install.ps1 again: it adds Piper."))
        self.scan_voices()

    # ------------------------------------------------------------ helpers
    def update_term_report(self) -> None:
        if not self.is_built:
            return
        info = term.current()
        mode = self.app.graphics_mode
        t = Text()
        for k, v in info.summary():
            t.append(f"  {k:<15} ", style="bold dim")
            t.append(f"{v}\n")
        t.append(f"  {'In use':<15} ", style="bold dim")
        t.append(term.MODE_LABELS[mode], style="bold")
        if mode == "sixel" and not self.app.sixel_ready:
            t.append("  (restart saintd to switch to Sixel)", style="italic")
        n, size = icons.cache_size()
        t.append(f"\n  {'Icon cache':<15} ", style="bold dim")
        t.append(f"{n} icons, {size / 1048576:.1f} MB")
        t.append("\n  Run  saintd --terminal  for the full terminal report.", style="dim")
        self.query_one("#term-report", Static).update(t)

    def fill_api_table(self) -> None:
        if not self.is_built:
            return
        cfg = self.app.ctx.cfg
        g = glyphs(self.app)
        for s in SOURCES:
            url, name = s["url"], s["name"]
            if s["id"] == "translator":
                b = cfg["translator"]
                bname, ep, _ = BACKEND_INFO[b]
                url = {"lingva": cfg["lingva_url"], "libretranslate": cfg["libre_url"],
                       "ollama": cfg["ollama_url"]}.get(b, ep)
                prov = f"{bname} — translates names and articles into English"
                name = f"Translator: {bname}"
            else:
                prov = s["provides"]
            enabled = {"azbyka": cfg["use_azbyka"], "wikical": cfg["use_wikical"], "wikidata": cfg["use_wikimedia"],
                       "mystagogy": cfg["use_mystagogy"], "htc": cfg["use_htc"],
                       "orthodoxwiki": cfg["use_orthodoxwiki"], "commons": cfg["show_icons"],
                       "wikipedia": cfg["use_wikimedia"], "translator": cfg["translator"] != "off"}.get(s["id"], True)
            st = self._status.get(s["id"], "not tested" if enabled else "turned off")
            t = Text()
            t.append(f"{g['dot']} {name.upper()}", style="bold")
            t.append(f"   [{st}]\n", style="italic")
            for k, v in (("Endpoint", url), ("Language", s["lang"]), ("API key", s["key"]),
                         ("Provides", prov), ("Terms", s["terms"])):
                t.append(f"  {k:<9} ", style="bold dim")
                t.append(f"{v}\n")
            self.query_one(f"#api-{s['id']}", Static).update(t)

    def update_translator_rows(self) -> None:
        if not self.is_built:
            return
        b = self.query_one("#tr-backend", Select).selection or "off"
        for rid, backend in (("#row-mymemory", "mymemory"), ("#row-lingva", "lingva"),
                             ("#row-libre", "libretranslate"), ("#row-ollama", "ollama")):
            self.query_one(rid).display = (b == backend)
        name, ep, note = BACKEND_INFO[b]
        self.query_one("#tr-info", Static).update(f"{name} — {note}")

    def refresh_summary(self) -> None:
        if not self.is_built:
            return
        st = self.app.ctx.db.stats()
        built = self.app.ctx.db.meta("built_at")
        when = time.strftime("%d %b %Y %H:%M", time.localtime(float(built))) if built else "never"
        t = Text()
        t.append(f"{st['people']:,} saints & groups", style="bold")
        t.append(f" ({st['total']:,} entries with feasts/icons) · {st['lives']:,} lives · "
                 f"{st['matched']:,} linked · {st['pending']:,} awaiting lookup · last build: {when}")
        self.query_one("#dir-summary", Static).update(t)
        bar = self.query_one("#set-progress", ProgressBar)
        if st["enrichable"]:
            bar.update(total=st["enrichable"], progress=st["enrichable"] - st["pending"])

    def write_log(self, msg: str) -> None:
        line = time.strftime("%H:%M:%S ") + msg
        if not self.is_built:
            self._log.append(line)
            del self._log[:-400]
            return
        try:
            self.query_one("#sync-log", RichLog).write(line)
        except NoMatches:                   # the window is closing: a late message from a download
            pass

    def _highlight_choices(self) -> None:
        """RadioSet highlights its first row on mount; move the highlight to the saved choice."""
        for rs in self.query(RadioSet):
            if rs.pressed_index >= 0 and hasattr(rs, "_selected"):
                rs._selected = rs.pressed_index

    def set_stage(self, text: str) -> None:
        self._stage = text
        if self.is_built:
            set_content(self.query_one("#set-stage", Static), Text(text, no_wrap=True, overflow="ellipsis"),
                        layout=False)

    def contact_changed(self, contact: str) -> None:
        if self.is_built:
            self.query_one("#in-contact", Input).value = contact
            self.update_rate_hint()

    # ------------------------------------------------------------ events
    def on_radio_set_changed(self, ev: RadioSet.Changed) -> None:
        cfg = self.app.ctx.cfg
        pid = ev.pressed.id or ""
        key, _, val = pid.partition("-")
        if {"th": cfg["theme"], "gl": cfg["glyphs"], "cal": cfg["calendar"]}.get(key) == val:
            return                              # the setting as it already is (the page being built)
        if pid.startswith("th-"):
            cfg.set("theme", pid[3:])
            self.app.apply_theme()
        elif pid.startswith("gl-"):
            cfg.set("glyphs", pid[3:])
            self.app.refresh_chrome()
        elif pid.startswith("cal-"):
            cfg.set("calendar", pid[4:])
            self.app.calendar_changed()

    def on_switch_changed(self, ev: Switch.Changed) -> None:
        sid = ev.switch.id or ""
        if sid.startswith("sw-"):
            key = sid[3:]
            if bool(self.app.ctx.cfg[key]) == bool(ev.value):
                return                          # unchanged (the page being built)
            self.app.ctx.cfg.set(key, bool(ev.value))
            self.fill_api_table()
            if key == "auto_enrich" and ev.value:
                self.app.start_enrich()
            elif key in ("auto_enrich", "use_wikimedia") and not ev.value and self.app._sync_kind == "enrich":
                self.app.pause_sync()          # stop linking now, not only at the next start
            elif key == "show_icons":
                self.app.set_graphics(self.app.ctx.cfg["graphics"])

    def on_select_changed(self, ev: Select.Changed) -> None:
        cfg = self.app.ctx.cfg
        sid = ev.select.id
        val = ev.select.selection
        if val is None:
            return
        stored = {"tr-backend": cfg["translator"], "net-timeout": cfg["timeout"], "gfx-mode": cfg["graphics"],
                  "tts-engine": cfg["tts_engine"], "tts-rate": cfg["tts_rate"]}
        if sid in stored and str(stored[sid]) == str(val):
            return                              # the setting as it already is: a Select reports its value
                                                # when it is first shown, and nothing must happen then
        if sid in ("tts-engine", "tts-voice", "tts-rate"):
            self._tts_select_changed(sid, val)
        elif sid == "tr-backend":
            cfg.set("translator", val)
            self.app.ctx.tr_bg.quota_hit = self.app.ctx.tr_fg.quota_hit = False
            self.update_translator_rows()
            self.fill_api_table()
        elif sid == "net-timeout":
            cfg.set("timeout", int(val))
            self.app.ctx.apply_network_settings()
        elif sid == "gfx-mode":
            cfg.set("graphics", val)
            self.app.set_graphics(val)
            self.update_term_report()

    def on_input_changed(self, ev: Input.Changed) -> None:
        iid = ev.input.id or ""
        if iid.startswith("in-"):
            if str(self.app.ctx.cfg[iid[3:]] or "") == ev.value.strip():
                return
            self.app.ctx.cfg.set(iid[3:], ev.value.strip())
            if iid in ("in-lingva_url", "in-libre_url", "in-ollama_url"):
                self.fill_api_table()
            if iid == "in-contact":
                self.app.ctx.apply_network_settings()
                self.update_rate_hint()

    def update_rate_hint(self) -> None:
        if not self.is_built:
            return
        h = self.app.ctx.http_bg
        per_min = int(round(h.wiki_rate() * 60))
        if h.contact:
            msg = (f"Wikimedia lookups: up to {per_min}/minute. Your contact is sent only to Wikimedia, "
                   f"inside the User-Agent header their API policy asks for.")
        else:
            msg = (f"Wikimedia lookups: {per_min}/minute — Wikimedia limits anonymous apps to 10 requests a "
                   f"minute. Add an e-mail or web address above to raise it to ~150/minute.")
        self.query_one("#net-rate", Static).update(msg)

    def on_button_pressed(self, ev: Button.Pressed) -> None:
        bid = ev.button.id
        app = self.app
        if bid == "d-build":
            app.start_build()
        elif bid == "d-enrich":
            app.start_enrich(force=True)
        elif bid == "d-pause":
            app.pause_sync()
        elif bid == "d-retry":
            app.ctx.db.reset_failed_enrichment()
            app.start_enrich(force=True)
        elif bid == "d-clear":
            app.ctx.db.clear_cache()
            self.write_log("Article and download caches cleared.")
            self.refresh_summary()
        elif bid == "d-wipe":
            app.confirm_wipe()
        elif bid == "gfx-clear":
            icons.clear_cache()
            app.ctx.db.con.execute("UPDATE saints SET icon_url='', icon_credit=''")
            app.ctx.db.con.execute("DELETE FROM lookups WHERE source='icon'")
            app.ctx.db.commit()
            self.update_term_report()
            app.notify("Icon cache cleared; icons are downloaded again when you open a saint.", timeout=4)
        elif bid == "api-test":
            self.test_connections()
        elif bid == "tr-test":
            self.query_one("#tr-result", Static).update("Testing…")
            self.test_translator()
        elif bid == "tr-detect":
            self.detect_models()
        elif bid == "tts-test":
            self.test_voice()
        elif bid == "tts-download":
            self.download_voice()
        elif bid == "tts-delete":
            self.delete_voice()
        elif bid == "tts-install":
            self.install_piper()

    # ------------------------------------------------------------ workers
    @work(thread=True, exclusive=True, group="api-test", exit_on_error=False)
    def test_connections(self) -> None:
        ctx = self.app.ctx
        g = glyphs(self.app)
        for s in SOURCES:
            if not s["probe"]:
                continue
            t0 = time.monotonic()
            try:
                ctx.http_fg.request("GET", s["probe"], timeout=12, retries=0)
                self._status[s["id"]] = f"{g['ok']} {int((time.monotonic() - t0) * 1000)} ms"
            except NetError as e:
                self._status[s["id"]] = f"{g['bad']} {str(e)[:30]}"
            except Exception as e:
                self._status[s["id"]] = f"{g['bad']} {e.__class__.__name__}"
            self.app.call_from_thread(self.fill_api_table)
        if ctx.cfg["translator"] != "off":
            try:
                ctx.tr_fg.quota_hit = False
                ctx.tr_fg.test()
                self._status["translator"] = f"{g['ok']} working"
            except (TranslationError, NetError) as e:
                self._status["translator"] = f"{g['bad']} {str(e)[:30]}"
            self.app.call_from_thread(self.fill_api_table)

    @work(thread=True, exclusive=True, group="tr-test", exit_on_error=False)
    def test_translator(self) -> None:
        ctx = self.app.ctx
        ctx.tr_fg.quota_hit = False
        try:
            out = ctx.tr_fg.test()
            msg = f"Works: “{out}”"
        except (TranslationError, NetError) as e:
            msg = f"Not working: {e}"
        except Exception as e:
            msg = f"Not working: {e.__class__.__name__}"
        self.app.call_from_thread(self.query_one("#tr-result", Static).update, msg)

    @work(thread=True, exclusive=True, group="tr-detect", exit_on_error=False)
    def detect_models(self) -> None:
        ctx = self.app.ctx
        try:
            models = ctx.tr_fg.ollama_models()
            msg = ("Installed models: " + ", ".join(models)) if models else "Ollama is running but has no models."
            if models and not ctx.cfg["ollama_model"]:
                ctx.cfg.set("ollama_model", models[0])
                self.app.call_from_thread(setattr, self.query_one("#in-ollama_model", Input), "value", models[0])
        except Exception as e:
            msg = f"Could not reach Ollama at {ctx.cfg['ollama_url']}: {e}"
        self.app.call_from_thread(self.query_one("#tr-result", Static).update, msg)

    def focus_first(self) -> None:
        self.when_built(lambda: self.query_one("#theme-set", RadioSet).focus(), focus=True)


# ---------------------------------------------------------------- tiny builders

def _set_options(select: Select, options: list[tuple], value) -> None:
    """Select.set_options, keeping the value — and showing the new label for it
    (Textual keeps the old one when the value itself does not change)."""
    select.set_options(options)
    values = [v for _, v in options]
    if value in values:
        other = next((v for v in values if v != value), None)
        if other is not None:
            select.value = other
        select.value = value


def _row(*children, classes: str = "set-row", id: str | None = None) -> Horizontal:
    h = Horizontal(classes=classes, id=id)
    for c in children:
        h.compose_add_child(c)
    return h


def _col(id: str, children) -> Vertical:
    v = Vertical(id=id)
    for c in children:
        v.compose_add_child(c)
    return v


def _radio(id: str, buttons: list[tuple[str, bool, str]], inline: bool = False) -> RadioSet:
    rs = RadioSet(id=id, classes="inline" if inline else "")
    for label, value, bid in buttons:
        rs.compose_add_child(RadioButton(label, value=value, id=bid))
    return rs
