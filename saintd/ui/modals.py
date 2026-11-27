"""Dialogs: help & glossary, the day's Scripture readings, confirmations."""

from __future__ import annotations

import datetime as dt

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, MarkdownViewer, Static

from .common import MONTHS, WEEKDAYS, glyphs, keys

HELP = """\
# Saint Directory — keys and words

## Everywhere

| Key | What it does |
|---|---|
| **F1** | Home: the Church calendar, the day's saints and readings |
| **F2** | Search the directory |
| **F3** | Focus: the saint you opened |
| **F4** | Settings |
| **/** | Jump to the search box |
| **?** | This help (press again or Esc to close) |
| **Esc** | Put the cursor on the tabs (Tab, Shift+Tab, {updown} move, or ← → when the tabs run along the top; Enter or {right} opens the tab, or ↓ along the top) |
| **Ctrl+B** | Build or update the directory |
| **Ctrl+Q** | Quit |
| **P** | Listen: read aloud what the page offers — press again to pause or resume (see below) |

Letter keys work in either case (with Shift or Caps Lock too).
The mouse works as well: click tabs, buttons, days and saints; scroll with the wheel.

## Home

| Key | What it does |
|---|---|
| **{arrows}** | Move the chosen day on the calendar (when the calendar has the cursor) |
| **PgUp / PgDn** | Previous / next month (on the calendar) |
| **[  ]** | Previous / next day, from anywhere on Home |
| **T** (or **Home** on the calendar) | Back to today |
| **S** | The day's Scripture readings |
| **N** | A random saint |
| **P** | Listen to the day: its feasts and fast, the saints, the saint of the day and the readings |
| **C** | Put the cursor on the calendar |
| **L** | Put the cursor on the list of the day's saints |
| **G** | Put the cursor on the Gospel and Epistle ({updown} scroll them) |
| **Enter** | Open the highlighted saint (on the calendar: go to the day's list) |
| **F** | Save or unsave the highlighted saint {saved} (or the Saint of the Day) |

Click a day to choose it (double-click opens its list); click {prev} or {next} to change the month.
The Home keys also work while the cursor is on the tab column.

## Search

| Key | What it does |
|---|---|
| **/** or **Ctrl+F** | Put the cursor in the search box |
| **Enter** | In the box: go to the results. On a result: open it in Focus |
| **↓** | From the search box down to the results |
| **F** | Save or unsave the highlighted saint {saved} (on the results) |
| **P** | Listen to the highlighted saint (on the results) |
| **Ctrl+R** | Clear the search and all filters |

In the search box every letter and sign is typed into the search (so **P**, **F**, **?** and the
reading keys are letters there): press **↓** or **Enter** to reach the results, or **Esc** for the tab
column, and the keys work again. On wide terminals a preview of the highlighted saint is shown beside
the results.

## Focus

| Key | What it does |
|---|---|
| **{updown} PgUp PgDn Home End** | Scroll the article |
| **Space** | One page down |
| **[  ]** | Previous / next saint of the list you came from |
| **P** | Listen: the life, hymns and history read aloud (again: pause / resume) |
| **F** | Save or unsave the saint {saved} |
| **I** | Show or hide the header with the icon |
| **V** | View the icon as large as the window allows, with the troparion and kontakion (or click the icon) |
| **R** | Refresh from the internet |
| **T** | Table of contents |
| **O** | Open the saint's page in your web browser |
| **B** | Back to the list you came from (search results or the day's saints), on the same saint |

Click a saint under *Also Commemorated* to open them. On wide terminals the hymns, feast days,
the saints who share them and the sources stand in a column beside the life.

## Reading aloud

| Key | What it does |
|---|---|
| **P** | Start, pause or resume reading (Focus: the saint · Home: the day · Search: the highlighted saint) |
| **X** | Stop reading |
| **,**  **.** (or **<**  **>**) | Previous / next paragraph |
| **+**  **-** | Faster / slower |

The paragraph being read is highlighted and kept in view; the bar above the status line shows
what is read, how far, the voice and the speed, with buttons for the mouse. Choose the engine, the
voice and the speed in **Settings → Voice & Reading aloud**: Piper's natural voices (downloaded once,
then offline), RHVoice, SVOX Pico, eSpeak NG, Speech Dispatcher or Festival.

## Words you will meet

| Word | Meaning |
|---|---|
| **Apostle / Equal-to-the-Apostles** | One of Christ's disciples; one who, like them, brought a people to the faith (e.g. Vladimir of Kiev, Nina of Georgia) |
| **Martyr / Great-martyr** | Killed for Christ; a great-martyr endured especially terrible torments (George, Demetrius, Catherine) |
| **Hieromartyr** | A martyr who was a priest or bishop |
| **Venerable** | A monk or nun of holy life (Greek *Hosios*, Slavonic *Prepodobny*) |
| **Venerable-martyr** | A martyred monk or nun |
| **New Martyr** | A martyr of recent centuries: under Ottoman rule, or the Soviet persecution |
| **Confessor** | Suffered for the faith but was not put to death |
| **Hierarch** | A saintly bishop (Basil the Great, Nicholas of Myra) |
| **Righteous** | A holy person who lived "in the world": the Old Testament righteous, holy lay people and married priests (John of Kronstadt) |
| **Unmercenary** | A physician who healed without payment (Cosmas and Damian, Panteleimon) |
| **Fool-for-Christ** | Hid holiness behind seeming madness (Xenia of Petersburg, Basil of Moscow) |
| **Passion-bearer** | Accepted a violent death in the spirit of Christ (Boris and Gleb, the Royal Martyrs) |
| **Synaxarion** | The book of the saints' lives, read at Matins day by day |
| **Troparion / Kontakion** | The two short hymns sung for a saint or feast |
| **Tone** | One of the eight melodies of Byzantine chant; the week's tone changes every Sunday |
| **Typikon signs** | The rank of a day's service: {rank6} great feast, {rank5} vigil, {rank4} polyeleos, {rank3} doxology, {rank2} six stichera; {fast} a fast day |
| **Synaxis** | A gathering in honour of a saint or of many saints together |
| **Translation / Uncovering of relics** | Feasts of moving, or finding, a saint's relics |
| **New / Old Calendar** | Churches on the Revised Julian (New) calendar keep fixed feasts on the civil date; Old Calendar (Julian) churches keep them 13 days later |
"""


def help_text(g: dict) -> str:
    """The help, drawn with the symbols in use (Unicode or Plain ASCII)."""
    keys_ = ("arrows", "updown", "right", "saved", "prev", "next", "rank6", "rank5", "rank4", "rank3", "rank2", "fast")
    return HELP.format(**{k: g[k] for k in keys_})


class HelpScreen(ModalScreen):
    BINDINGS = [Binding("escape", "dismiss", show=False), Binding("question_mark", "dismiss", show=False),
                Binding(keys("q"), "dismiss", show=False), Binding("f1", "dismiss", show=False)]

    def compose(self) -> ComposeResult:
        with Vertical(id="help-box"):
            yield MarkdownViewer(help_text(glyphs(self.app)), id="help-text", show_table_of_contents=False)
            yield Static("Esc, ? or Q closes this window", classes="hint", id="help-close")

    def on_mount(self) -> None:
        self.query_one("#help-text").document.focus()

    def action_dismiss(self, result=None) -> None:
        self.dismiss(result)


class ReadingsScreen(ModalScreen):
    """The day's Epistle and Gospel (and any other readings) with their text."""

    BINDINGS = [Binding("escape", "dismiss", show=False), Binding(keys("q", "s"), "dismiss", show=False)]

    def __init__(self, day: dt.date, data: dict) -> None:
        super().__init__()
        self.day, self.data = day, data

    def compose(self) -> ComposeResult:
        with Vertical(id="readings-box"):
            yield MarkdownViewer(self._markdown(), id="readings-text", show_table_of_contents=False)
            g = glyphs(self.app)
            yield Static(f"Esc, S or Q closes this window {g['sep']} {g['updown']} PgUp PgDn scroll",
                         classes="hint", id="readings-close")

    def on_mount(self) -> None:
        self.query_one("#readings-text").document.focus()

    def _markdown(self) -> str:
        d, data = self.day, self.data
        out = [f"# Scripture for {WEEKDAYS[d.weekday()]}, {d.day} {MONTHS[d.month - 1]} {d.year}", ""]
        titles = [t for t in (data.get("titles") or []) if t]
        if titles:
            out.append(f"*{' · '.join(titles)}*")
            out.append("")
        readings = data.get("readings") or []
        if not readings:
            out.append("The calendar gives no Scripture readings for this day.")
        for r in readings:
            label = r.get("source") or "Reading"
            desc = f" ({r['description']})" if r.get("description") else ""
            out.append(f"## {label} — {r.get('display', '')}{desc}")
            out.append("")
            verses = r.get("passage") or []
            line = []
            for v in verses:
                txt = (v.get("content") or "").strip()
                if not txt:
                    continue
                if v.get("paragraph_start") and line:
                    out.append(" ".join(line))
                    out.append("")
                    line = []
                line.append(f"**{v.get('verse', '')}** {txt}")
            if line:
                out.append(" ".join(line))
            out.append("")
        out.append("---")
        out.append("*Readings as appointed in the Orthodox Church in America's calendar, from orthocal.info "
                   "(King James Version).*")
        return "\n".join(out)

    def action_dismiss(self, result=None) -> None:
        self.dismiss(result)


class ConfirmWipe(ModalScreen[bool]):
    BINDINGS = [Binding("escape", "cancel", show=False)]

    def compose(self) -> ComposeResult:
        with Vertical(id="confirm"):
            yield Static("Delete the whole local directory, lives, articles, saved saints and caches?\n"
                         "Your settings are kept. You can rebuild at any time.", id="confirm-text")
            with Horizontal(classes="btn-row"):
                yield Button("Delete everything", id="yes", variant="error")
                yield Button("Cancel", id="no", variant="primary")

    def on_mount(self) -> None:
        self.query_one("#no", Button).focus()

    def on_button_pressed(self, ev: Button.Pressed) -> None:
        self.dismiss(ev.button.id == "yes")

    def action_cancel(self) -> None:
        self.dismiss(False)


class VoicePicker(ModalScreen):
    """The first time something is read aloud with Piper installed but no voice
    yet: choose a natural voice to download (once), or use the system voice.
    Dismissed with the voice downloaded, None for the system voice, "" for Not now."""

    BINDINGS = [Binding("escape", "cancel", show=False)]
    SUGGESTED = 6

    def compose(self) -> ComposeResult:
        from rich.text import Text
        from textual.widgets import OptionList, ProgressBar
        from textual.widgets.option_list import Option

        from .. import tts
        piper = tts.ENGINES["piper"]
        voices = [v for v in piper.voices() if not v.installed][: self.SUGGESTED]
        with Vertical(id="voice-box"):
            yield Static("CHOOSE A READING VOICE", id="voice-title")
            yield Static("Saint Directory can read the lives of the saints aloud. Piper's natural voices are "
                         "downloaded once (60–115 MB) and then work without the internet. You can change the voice, "
                         "the speed or the engine any time in Settings → Voice & Reading aloud.", id="voice-text")
            opts = []
            for v in voices:
                t = Text()
                t.append(v.label.split(" — ")[0], style="bold")
                t.append(f" — {v.note}")
                t.append(f"   {v.size / 1e6:.0f} MB", style="dim")
                opts.append(Option(t, id=v.id))
            yield OptionList(*opts, id="voice-list")
            yield ProgressBar(id="voice-progress", total=100, show_eta=False)
            yield Static("", id="voice-status", classes="hint")
            with Horizontal(classes="btn-row"):
                yield Button("Download and read", id="voice-get", variant="primary")
                yield Button("Use the system voice", id="voice-system")
                yield Button("Not now", id="voice-cancel")

    def on_mount(self) -> None:
        from textual.widgets import OptionList, ProgressBar
        ol = self.query_one("#voice-list", OptionList)
        ol.highlighted = 0 if ol.option_count else None
        ol.focus()
        self.query_one("#voice-progress", ProgressBar).display = False
        self._stop = None

    def on_option_list_option_selected(self, ev) -> None:
        self._download(ev.option.id)

    def on_button_pressed(self, ev: Button.Pressed) -> None:
        from textual.widgets import OptionList
        if ev.button.id == "voice-get":
            ol = self.query_one("#voice-list", OptionList)
            if ol.highlighted is not None:
                self._download(ol.get_option_at_index(ol.highlighted).id)
        elif ev.button.id == "voice-system":
            self._cancel_download()
            self.dismiss(None)
        else:
            self.action_cancel()

    def _download(self, key: str | None) -> None:
        import threading

        from textual.widgets import ProgressBar
        if not key or self._stop is not None:
            return
        self._stop = threading.Event()
        bar = self.query_one("#voice-progress", ProgressBar)
        bar.display = True
        bar.update(total=100, progress=0)
        self.query_one("#voice-status", Static).update(f"Downloading {key}…")
        self.query_one("#voice-get", Button).disabled = True
        self._fetch(key, self._stop)

    def _fetch(self, key: str, stop) -> None:
        import threading

        from .. import tts

        def run() -> None:
            def progress(done: int, total: int) -> None:
                try:
                    self.app.call_from_thread(self._progress, done, total)
                except Exception:
                    pass
            try:
                tts.download_piper_voice(key, progress, stop, catalog=tts.piper_catalog())
                ok, msg = True, ""
            except Exception as e:
                ok, msg = False, str(e)
            try:
                self.app.call_from_thread(self._fetched, key, ok, msg)
            except Exception:
                pass
        threading.Thread(target=run, name="saintd-voice-download", daemon=True).start()

    def _progress(self, done: int, total: int) -> None:
        from textual.widgets import ProgressBar
        self.query_one("#voice-progress", ProgressBar).update(total=max(1, total), progress=done)
        self.query_one("#voice-status", Static).update(f"Downloading… {done / 1e6:.0f} of {total / 1e6:.0f} MB")

    def _fetched(self, key: str, ok: bool, msg: str) -> None:
        stop, self._stop = self._stop, None
        if stop is not None and stop.is_set():
            return
        if ok:
            self.dismiss(key)
            return
        self.query_one("#voice-get", Button).disabled = False
        self.query_one("#voice-status", Static).update(f"The download failed: {msg}. Try again, or use the "
                                                       f"system voice.")

    def _cancel_download(self) -> None:
        if self._stop is not None:
            self._stop.set()
            self._stop = None

    def action_cancel(self) -> None:
        self._cancel_download()
        self.dismiss("")


class IconView(ModalScreen):
    """The saint's icon as large as the window allows (in its gilded frame in Kitty,
    Ghostty and Sixel terminals), with the troparion and kontakion beside it."""

    BINDINGS = [Binding("escape", "dismiss", show=False), Binding(keys("v", "q"), "dismiss", show=False)]

    def __init__(self, sid: int) -> None:
        super().__init__()
        self.sid = sid

    def compose(self) -> ComposeResult:
        from ..graphics import Headpiece, SaintIcon
        from textual.containers import VerticalScroll
        with Horizontal(id="iv-box"):
            yield SaintIcon(id="iv-icon")
            with VerticalScroll(id="iv-side"):
                yield Headpiece(id="iv-cross")            # the cross above the hymns
                yield Static(id="iv-text")
        yield Static("Esc or V closes", id="iv-close", classes="hint")

    def on_mount(self) -> None:
        from rich.text import Text

        from .. import narration as N
        from ..graphics import SaintIcon
        from .common import short_name
        ctx = self.app.ctx
        s = ctx.db.get_saint(self.sid)
        if not s:
            self.dismiss()
            return
        g = glyphs(self.app)
        info = ctx.articles.summary(s)
        theme = self.app.current_theme
        t = Text()
        t.append(info["name"] + "\n", style=f"bold {theme.primary}")
        if info["subtitle"]:
            t.append(info["subtitle"] + "\n", style="italic")
        facts = [x for x in (info["lived"], info["where"], ", ".join(info["kinds"])) if x]
        if facts:
            t.append(f" {g['sep']} ".join(facts) + "\n", style="dim")
        hymns = sorted((x for x in ctx.db.stories(self.sid) if x["source"] == "htc-hymn"), key=lambda x: x["title"])
        for h in hymns:
            t.append(f"\n{g['hymn']} {N.hymn_heading(h).upper()}\n", style=f"bold {theme.secondary}")
            for line in [p.strip() for p in h["html"].replace("//", "/").split("/") if p.strip()]:
                t.append(line + "\n", style="italic")
        if not hymns:
            t.append("\nThe troparion and kontakion appear here once the Holy Trinity calendar has them "
                     "(open the saint in Focus while online).", style="dim italic")
        if info["icon_credit"]:
            t.append(f"\n\nIcon: {info['icon_credit']}", style="dim italic")
        self.query_one("#iv-text", Static).update(t)
        icon = self.query_one("#iv-icon", SaintIcon)
        mode = self.app.graphics_mode
        icon.show(ctx.articles.icon_path(s) if ctx.cfg["show_icons"] else None,
                  initial=(short_name(s) or s["name"])[:1].upper(), mode=mode, label=short_name(s))
        self.query_one("#iv-side").focus()

    def on_click(self, event) -> None:
        if getattr(event, "widget", None) is not None and event.widget.id == "iv-icon":
            self.dismiss()

    def action_dismiss(self, result=None) -> None:
        self.dismiss(result)


class AskContact(ModalScreen):
    """First-run question: a contact for Wikimedia's User-Agent policy."""

    BINDINGS = [Binding("escape", "skip", show=False)]

    def compose(self) -> ComposeResult:
        with Vertical(id="ask"):
            yield Static("WELCOME TO SAINT DIRECTORY", id="ask-title")
            yield Static(
                "Saint Directory reads the Orthodox calendar right away, then looks each saint up on "
                "Wikidata and Wikipedia for dates, birthplaces, icons and full histories.\n\n"
                "Wikimedia asks apps to say who is using them. With a contact address the lookups can run "
                "about 15× faster (around 150 a minute instead of 10).", id="ask-text")
            yield Input(placeholder="your e-mail or web address (optional)", id="ask-input")
            yield Static("It is sent only to Wikimedia, inside the User-Agent header of each request. "
                         "You can change it any time in Settings → Network.", classes="hint")
            with Horizontal(classes="btn-row"):
                yield Button("Save", id="ask-save", variant="primary")
                yield Button("Skip", id="ask-skip")

    def on_mount(self) -> None:
        self.query_one("#ask-input", Input).focus()

    def on_input_submitted(self, ev: Input.Submitted) -> None:
        self.dismiss(ev.value.strip() or None)

    def on_button_pressed(self, ev: Button.Pressed) -> None:
        if ev.button.id == "ask-save":
            self.dismiss(self.query_one("#ask-input", Input).value.strip() or None)
        else:
            self.dismiss(None)

    def action_skip(self) -> None:
        self.dismiss(None)
