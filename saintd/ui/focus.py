"""Focus tab: everything about one saint — a header card with the icon and
the facts, the article (life, calendar notes, history) and, on wide screens,
a side column with the hymns, the feast days, the saints who share them and
the sources. P reads it all aloud, following the paragraph being read."""

from __future__ import annotations

import time
import webbrowser

from rich.console import Group
from rich.table import Table
from rich.text import Text
from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Button, Markdown, MarkdownViewer, Static
from textual.widgets import Tree
from textual.widgets.markdown import MarkdownTableOfContents

from .. import narration as N
from ..article import MONTHS, old_calendar_civil, web_url
from ..db import LIFE_SOURCES
from ..graphics import Headpiece, SaintIcon
from ..net import Cancelled
from .common import LazyPage, OpenSaint, glyphs, keys, set_content, short_name

WELCOME = """\
## The Focus tab

Choose a saint on **Home** (F1) — from the day's commemorations — or on the **Search** tab (F2),
and everything known about them opens here:

- the saint's **icon** (true pictures in Kitty, Ghostty and other graphics terminals),
- the **Life** from the Synaxarion, the Holy Trinity calendar, the Mystagogy Resource Center
  or the Russian Lives of the Saints,
- the saint's **troparion and kontakion**,
- the **history** from Wikipedia or OrthodoxWiki (translated when the only article is in another language),
- feast days on the New and Old Calendars, and the saints who share them,
- dates, birthplace and the kind of saint, and the sources it all came from.

Press **P** to have the life **read aloud** — the paragraph being read is highlighted and kept in view.

Keys here: **[ ]** previous/next saint · **P** listen · **V** the icon, large · **F** save {saved} · **I** header ·
**R** refresh · **T** contents · **O** open in your browser · **B** back · **?** all keys
"""



def welcome(g: dict) -> str:
    """The Focus tab before a saint is chosen, with the symbols in use (Unicode or Plain ASCII)."""
    return WELCOME.replace("{saved}", g["saved"])


SKIP_READING = ("at a glance", "commemorations", "also commemorated", "sources")
SOURCE_NAMES = (("orthocal", "OCA Synaxarion"), ("htc", "Holy Trinity calendar"), ("htc-hymn", "Holy Trinity hymns"),
                ("mystagogy", "Mystagogy"), ("azbyka-life", "Azbuka Very life"), ("wikical", "Wikipedia calendar"),
                ("orthodoxwiki", "OrthodoxWiki"))


class ArticleDocument(Markdown):
    """The article. When it gains or loses the focus only its own look changes,
    so restyle just this widget, not every paragraph of a long Life."""

    def watch_has_focus(self, _has_focus: bool) -> None:
        try:
            self.app.stylesheet.update_nodes([self], animate=True)
        except Exception:
            super().watch_has_focus(_has_focus)


class ArticleViewer(MarkdownViewer):
    """MarkdownViewer that leaves links to the Focus tab: MarkdownViewer itself
    would try to open every link as a local file (and fail)."""

    def compose(self) -> ComposeResult:
        doc = ArticleDocument(parser_factory=getattr(self, "_parser_factory", None), open_links=False)
        doc.can_focus = True
        yield doc
        yield MarkdownTableOfContents(doc)

    async def _on_markdown_link_clicked(self, message: Markdown.LinkClicked) -> None:
        message.prevent_default()         # skip MarkdownViewer.go(); the message still bubbles to FocusPane


def _plain(block) -> str:
    content = getattr(block, "_content", None)
    return content.plain.strip() if content is not None else ""


def doc_items(doc) -> list[tuple[str, object, str]]:
    """The readable blocks of a Markdown document, in order: (kind, widget, text)
    with kind h2/h3/h4/p/li/quote."""
    out: list[tuple[str, object, str]] = []
    for b in list(doc.children):
        name = type(b).__name__
        if name in ("MarkdownH1", "MarkdownH2", "MarkdownH3", "MarkdownH4", "MarkdownH5", "MarkdownH6"):
            out.append(("h1" if name == "MarkdownH1" else "h2" if name == "MarkdownH2" else
                        "h3" if name == "MarkdownH3" else "h4", b, _plain(b)))
        elif name == "MarkdownParagraph":
            out.append(("p", b, _plain(b)))
        elif name in ("MarkdownBulletList", "MarkdownOrderedList"):
            for item in b.query("MarkdownListItem"):
                text = " ".join(_plain(p) for p in item.query("MarkdownParagraph"))
                out.append(("li", item, text))
        elif name == "MarkdownBlockQuote":
            out.append(("quote", b, " ".join(_plain(p) for p in b.query("MarkdownParagraph"))))
    return out


class FocusPane(LazyPage, Vertical):
    BINDINGS = [
        Binding(keys("r"), "refresh_article", "Refresh", show=False),
        Binding(keys("t"), "toggle_toc", "Contents", show=False),
        Binding(keys("o"), "open_browser", "Open in browser", show=False),
        Binding(keys("b"), "back", "Back", show=False),
        Binding(keys("f"), "toggle_saved", "Save", show=False),
        Binding(keys("i"), "toggle_header", "Header", show=False),
        Binding(keys("v"), "view_icon", "View the icon", show=False),
        Binding("left_square_bracket", "step(-1)", "Previous saint", show=False),
        Binding("right_square_bracket", "step(1)", "Next saint", show=False),
        Binding("space", "page(1)", "Page down", show=False),
        Binding("shift+space", "page(-1)", "Page up", show=False),
    ]

    def __init__(self, **kw) -> None:
        super().__init__(**kw)
        self.sid: int | None = None
        self.context: list[int] = []
        self.context_total: int | None = None    # all the matches, when only some are loaded (Search)
        self.origin = "search"
        self._last_show = 0.0
        self._pending_show = None
        self._spin = 0
        self._busy = False
        self._hero_wanted = True
        self._split = False
        self._docs_shown: tuple[str, str] | None = None
        self._status_text = "Pick a saint on Home (F1) or Search (F2)."

    def compose(self) -> ComposeResult:
        if not self.lazy_ready:          # built when first needed (keeps start-up quick)
            yield Static("Opening Focus…", classes="lazy-wait")
            return
        with Horizontal(id="focus-bar"):
            yield Button("Back", id="fx-back", compact=True)
            yield Button("Prev", id="fx-prev", compact=True)
            yield Button("Next", id="fx-next", compact=True)
            yield Button("Save", id="fx-save", compact=True)
            yield Button("Listen", id="fx-listen", compact=True)
            yield Button("Refresh", id="fx-refresh", compact=True)
            yield Button("Contents", id="fx-toc", compact=True)
            yield Button("Browser", id="fx-browser", compact=True)
            yield Static(id="focus-status")
        with Horizontal(id="focus-hero"):
            yield SaintIcon(id="hero-icon")
            yield Static(id="hero-card")
        with Horizontal(id="focus-body"):
            yield ArticleViewer(welcome(glyphs(self.app)), id="article", show_table_of_contents=False)
            with VerticalScroll(id="focus-side"):
                yield Headpiece(id="side-cross")          # the cross above the hymns
                yield Markdown("", id="side-doc", open_links=False)

    def ensure_built(self) -> None:
        self.build()

    def built(self) -> None:
        self.query_one("#focus-hero").display = False
        self.query_one("#focus-side").display = False
        self.query_one("#focus-side").border_title = "HYMNS · FEASTS · SOURCES"
        self._split = self._want_split()
        self.set_interval(0.15, self._tick)
        self._relabel()
        self._render_status()

    def _want_split(self) -> bool:
        try:
            return self.app.w_screen.has_class("-wide")
        except Exception:
            return False

    def layout_changed(self) -> None:
        """The terminal crossed a size class: one column or two."""
        if not self.is_built:
            return
        split = self._want_split()
        if split != self._split:
            self._split = split
            self._render_article()
        if self.sid:
            s = self.app.ctx.db.get_saint(self.sid)
            if s:
                self._show_hero(s)

    # ------------------------------------------------------------ chrome
    def _relabel(self) -> None:
        if not self.is_built:
            return
        g = glyphs(self.app)
        saved = bool(self.sid) and self.app.ctx.db.is_favorite(self.sid)
        back_to = {"home": "Day", "search": "Results"}.get(self.origin, "Back")
        labels = {"#fx-back": f"{g['back']} {back_to}", "#fx-prev": f"{g['prev']} Prev", "#fx-next": f"Next {g['next']}",
                  "#fx-save": f"{g['saved']} Saved" if saved else f"{g['unsaved']} Save",
                  "#fx-listen": self._listen_label(g),
                  "#fx-refresh": f"{g['refresh']} Refresh", "#fx-toc": f"{g['toc']} Contents",
                  "#fx-browser": f"{g['out']} Browser"}
        for wid, label in labels.items():
            b = self.query_one(wid, Button)
            if str(b.label) != label:
                b.label = label
        pos = self._pos()
        self.query_one("#fx-prev", Button).disabled = pos is None or pos <= 0
        self.query_one("#fx-next", Button).disabled = pos is None or pos >= self._count() - 1
        self.query_one("#fx-listen", Button).disabled = self.sid is None

    def _listen_label(self, g: dict) -> str:
        r = getattr(self.app, "reader", None)
        if r is not None and r.active and self.sid is not None and r.owner == ("saint", self.sid):
            return f"{g['arrow']} Resume" if r.state == "paused" else f"{g['hymn']} Pause"
        return f"{g['hymn']} Listen"

    def reader_changed(self) -> None:
        if self.is_built:
            b = self.query_one("#fx-listen", Button)
            label = self._listen_label(glyphs(self.app))
            if str(b.label) != label:
                b.label = label

    def _count(self) -> int:
        return max(len(self.context), self.context_total or 0)

    def _pos(self) -> int | None:
        try:
            return self.context.index(self.sid) if self.sid is not None else None
        except ValueError:
            return None

    def _tick(self) -> None:
        if self._busy:
            self._spin += 1
            self._render_status()

    def _render_status(self) -> None:
        if not self.is_built:
            return
        g = glyphs(self.app)
        t = Text(no_wrap=True, overflow="ellipsis")
        if self._busy:
            t.append(g["spin"][self._spin % len(g["spin"])] + " ", style="bold")
        pos = self._pos()
        if pos is not None and self._count() > 1:
            t.append(f"{pos + 1}/{self._count():,}  ", style="bold")
        t.append(self._status_text, style="italic")
        set_content(self.query_one("#focus-status", Static), t, layout=False)

    def set_status(self, text: str) -> None:
        self._status_text = text
        self._render_status()

    # ------------------------------------------------------------ the header card
    def facts(self, s: dict) -> list[tuple[str, str]]:
        """What the header card lists about the saint."""
        ctx = self.app.ctx
        info = ctx.articles.summary(s)
        cal = ctx.cfg["calendar"]
        out: list[tuple[str, str]] = []
        if info["feasts"]:
            days = []
            for (m, d), label in info["feasts"][:4]:
                days.append(f"{MONTHS[m - 1]} {d}" + (f" ({label.lower()})" if label else ""))
            (m0, d0), _ = info["feasts"][0]
            civil = old_calendar_civil(m0, d0)
            out.append(("Feast", " · ".join(days)))
            out.append(("Old Calendar" if cal != "old" else "Civil date", f"{civil} (civil)"))
        if info["lived"]:
            out.append(("Lived", info["lived"]))
        if info["where"]:
            out.append(("Born in" if s["country_src"] == "wikidata: birthplace" else "From", info["where"]))
        if info["kinds"]:
            out.append(("Kind", ", ".join(info["kinds"])))
        if s["kind"] in ("saint", "group") and s["gender"] and s["gender"] != "N/A":
            out.append(("Gender", s["gender"]))
        if s.get("aliases"):
            out.append(("Also known as", s["aliases"]))
        if s.get("ru_en") and s["ru_en"] != s["name"]:
            out.append(("Russian calendar", s["ru_en"]))
        stories = {st["source"] for st in ctx.db.stories(s["id"])}
        srcs = [name for key, name in SOURCE_NAMES if key in stories or (key == "orthocal" and "|orthocal|" in s["sources"])]
        if "|azbyka|" in s["sources"] and "azbyka-life" not in stories:
            srcs.append("Azbuka Very")
        if ctx.db.article(s["id"]):
            srcs.append("Wikipedia")
        if s.get("qid"):
            srcs.append(f"Wikidata {s['qid']}")
        if srcs:
            out.append(("Sources", " · ".join(dict.fromkeys(srcs))))
        return out

    def _show_hero(self, s: dict) -> None:
        if not self.is_built:
            return
        ctx = self.app.ctx
        g = glyphs(self.app)
        info = ctx.articles.summary(s)
        theme = self.app.current_theme
        head = Text()
        head.append(info["name"], style=f"bold {theme.primary}")
        if ctx.db.is_favorite(s["id"]):
            head.append(f"  {g['saved']}", style="bold")
        if info["subtitle"]:
            head.append("\n" + info["subtitle"], style="italic")
        card = self.query_one("#hero-card", Static)
        width = card.content_size.width or 80
        facts = self.facts(s)
        two = width >= 96 and len(facts) > 3
        grid = Table.grid(padding=(0, 2, 0, 0), expand=True)
        for _ in range(2 if two else 1):
            grid.add_column(no_wrap=True, style="bold dim", min_width=12)
            grid.add_column(ratio=1, overflow="fold")
        rows = [facts[i:i + 2] for i in range(0, len(facts), 2)] if two else [[f] for f in facts]
        for row in rows:
            cells: list = []
            for k, v in row:
                cells += [k, v]
            while len(cells) < (4 if two else 2):
                cells.append("")
            grid.add_row(*cells)
        stories = ctx.db.stories(s["id"])
        badges = []
        if any(st["source"] in LIFE_SOURCES for st in stories):
            badges.append(f"{g['life']} life")
        n_h = sum(1 for st in stories if st["source"] == "htc-hymn")
        if n_h:
            badges.append(f"{g['hymn']} {n_h} hymn{'s' if n_h > 1 else ''}")
        if ctx.db.article(s["id"]):
            badges.append(f"{g['book']} history")
        if info["linked"]:
            badges.append(f"{g['ok']} linked to Wikidata")
        foot = Text("  ".join(badges), style="dim")
        if info["icon_credit"]:
            foot.append(f"{'   ' if badges else ''}Icon: {info['icon_credit']}", style="dim italic")
        card.update(Group(head, Text(""), grid, Text(""), foot))
        icon = self.query_one("#hero-icon", SaintIcon)
        icon.display = self.app.graphics_mode != "off" and ctx.cfg["show_icons"]
        icon.show(ctx.articles.icon_path(s), initial=(short_name(s) or s["name"])[:1].upper(),
                  mode=self.app.graphics_mode, label=short_name(s))
        self.query_one("#focus-hero").display = self._hero_wanted

    def set_graphics(self, mode: str) -> None:
        if not self.is_built:
            return
        icon = self.query_one("#hero-icon", SaintIcon)
        icon.display = mode != "off" and self.app.ctx.cfg["show_icons"]
        icon.set_mode(mode)
        self.query_one("#side-cross", Headpiece).set_mode(mode)

    # ------------------------------------------------------------ loading
    def show_saint(self, sid: int, refresh: bool = False, context: list[int] | None = None,
                   origin: str | None = None, total: int | None = None) -> None:
        if not self.is_built:
            self.when_built(lambda: self.show_saint(sid, refresh, context, origin, total))
            return
        if context is not None:
            self.context = list(context)
            self.context_total = total
        if origin:
            self.origin = origin
        self.sid = sid
        ctx = self.app.ctx
        s = ctx.db.get_saint(sid)
        if s:
            self._show_hero(s)                  # what we already know, at once
        self._relabel()
        self._busy = True
        self.set_status("Gathering sources…")
        now = time.monotonic()
        quick = now - self._last_show < 0.35
        self._last_show = now
        if self._pending_show is not None:
            self._pending_show.stop()
            self._pending_show = None

        def article() -> None:
            self._pending_show = None
            if self.sid != sid:
                return
            self._render_article(home=True)
            self.load(sid, refresh)             # then fill in from the internet

        if quick:                               # stepping fast: wait until the keys pause
            self._pending_show = self.set_timer(0.25, article)
        else:
            article()

    def reset(self) -> None:
        """Back to the welcome page (after the directory was deleted)."""
        self.sid, self.context, self.context_total = None, [], None
        self._busy = False
        if not self.is_built:
            return
        self.query_one("#focus-hero").display = False
        self._set_docs(welcome(glyphs(self.app)), "", home=True)
        self.set_status("Pick a saint on Home (F1) or Search (F2).")
        self._relabel()

    @work(thread=True, exclusive=True, group="article", exit_on_error=False)
    def load(self, sid: int, refresh: bool) -> None:
        ctx = self.app.ctx

        def status(msg: str) -> None:
            if self.sid == sid:
                self.app.call_from_thread(self.set_status, msg)

        def partial(md: str) -> None:
            if self.sid == sid:
                self.app.call_from_thread(self._update_partial, sid, md)

        md = None
        try:
            md = ctx.articles.build(sid, refresh=refresh, status=status, partial=partial, title=False)
        except Cancelled:
            md = None
        except Exception as e:  # never crash the UI over one article
            status(f"Something went wrong: {e}")
        if self.sid != sid:
            return
        self.app.call_from_thread(self._loaded, md)
        if ctx.cfg["show_icons"] and self.app.graphics_mode != "off":
            try:
                path = ctx.articles.fetch_icon(sid, refresh=refresh, status=status)
            except Exception:
                path = None
            if self.sid == sid:
                self.app.call_from_thread(self._icon_loaded, sid, path)

    def _update_partial(self, sid: int, md: str) -> None:
        if self.sid != sid:
            return
        s = self.app.ctx.db.get_saint(sid)
        if s:
            self._show_hero(s)
        self._render_article(fallback=md)

    def _loaded(self, md: str | None) -> None:
        self._busy = False
        if md:
            self._render_article(fallback=md)
            s = self.app.ctx.db.get_saint(self.sid) if self.sid else None
            if s:
                self._show_hero(s)
        self.set_status("Ready — P listens, ? shows every key")
        self._relabel()
        self.app.notify_directory_changed()

    def _icon_loaded(self, sid: int, path) -> None:
        if self.sid != sid:
            return
        s = self.app.ctx.db.get_saint(sid)
        if s:
            self._show_hero(s)
        if path is None and self._status_text.startswith("Looking for an icon"):
            self.set_status("Ready")

    def _render_article(self, home: bool = False, fallback: str | None = None) -> None:
        """Compose the article from the directory: one column, or two on wide screens."""
        if not self.is_built or not self.sid:
            return
        ctx = self.app.ctx
        s = ctx.db.get_saint(self.sid)
        if not s:
            self._set_docs(fallback or "# Not found\n\nThis entry is no longer in the directory.", "", home=home)
            return
        main, side = ctx.articles.compose_parts(s, ctx.db.article(self.sid), split=self._split,
                                                glance=not self._hero_wanted)
        self._set_docs(main, side, home=home)

    def _set_docs(self, main: str, side: str, home: bool) -> None:
        side_on = bool(side.strip()) and self._split and self.sid is not None
        panel = self.query_one("#focus-side", VerticalScroll)
        if panel.display != side_on:
            panel.display = side_on
        if (main, side) == self._docs_shown:
            return                          # unchanged: keep the widgets (re-mounting a long Life is slow)
        old_main, old_side = self._docs_shown or ("", "")
        self._docs_shown = (main, side)
        viewer = self.query_one("#article", MarkdownViewer)
        if main != old_main:
            y = viewer.scroll_y
            viewer.document.update(main)
            if home:
                viewer.scroll_home(animate=False)
            else:
                viewer.call_after_refresh(viewer.scroll_to, y=y, animate=False)
        if side != old_side:
            self.query_one("#side-doc", Markdown).update(side)
            if home:
                panel.scroll_home(animate=False)

    # ------------------------------------------------------------ reading aloud
    def listen(self) -> bool:
        """P: read this saint aloud (or pause / resume the reading)."""
        if not self.is_built or not self.sid:
            return False
        reader = self.app.reader
        owner = ("saint", self.sid)
        if reader.active and reader.owner == owner:
            reader.toggle()
            return True
        s = self.app.ctx.db.get_saint(self.sid)
        if not s:
            return False
        if self._busy:
            self.app.notify("Still gathering sources — reading what is here so far.", timeout=3)
        self.app.start_reading(s["name"], self.reading_script(), owner)
        return True

    def reading_script(self) -> list:
        """The header, then the article block by block (each chunk highlights its block)."""
        ctx = self.app.ctx
        cfg = ctx.cfg
        s = ctx.db.get_saint(self.sid)
        info = ctx.articles.summary(s)
        hero = self.query_one("#focus-hero")
        target = hero if hero.display else None
        out: list = []
        N.add(out, info["name"] + "." + (f" {info['subtitle']}." if info["subtitle"] else ""), target, "header")
        N.add(out, N.facts_sentence(info), target, "header")
        main = doc_items(self.query_one("#article", MarkdownViewer).document)
        side = doc_items(self.query_one("#side-doc", Markdown)) if self.query_one("#focus-side").display else []

        def sections(items):
            secs: list[tuple[str, list]] = [("", [])]
            for kind, block, text in items:
                if kind in ("h1", "h2"):
                    secs.append((text, [(kind, block, text)]))
                else:
                    secs[-1][1].append((kind, block, text))
            return [x for x in secs if x[1]]

        main_secs, side_secs = sections(main), sections(side)
        hymns = [x for x in main_secs + side_secs if x[0].lower().startswith("hymns")]
        rest = [x for x in main_secs if not x[0].lower().startswith("hymns")]
        order: list[tuple[str, list]] = []
        placed = False
        for sec in rest:
            order.append(sec)
            if sec[0].lower().startswith("the life") and not placed:
                order += hymns
                placed = True
        if not placed:
            order = order[:1] + hymns + order[1:] if order and not order[0][0] else hymns + order
        for title, items in order:
            low = title.lower()
            if low.startswith(SKIP_READING) or (low.startswith("hymns") and not cfg["tts_hymns"]) or \
                    (low.startswith("history") and not cfg["tts_history"]):
                continue
            for kind, block, text in items:
                if not text:
                    continue
                if kind in ("h3", "h4") and text.startswith("From the "):
                    continue                    # which source a life came from
                src = (getattr(block, "source", None) or "").strip()
                if kind in ("p", "quote") and src.startswith("*") and src.endswith("*") and not src.startswith("**"):
                    continue                    # notes and credits in italics
                if kind in ("h1", "h2", "h3", "h4"):
                    text = text.rstrip(".") + "."
                N.add(out, text, block, title, anchor=text[:60])
        return out

    def resolve_target(self, chunk):
        """The block a chunk belongs to, after the article was drawn again."""
        if not self.is_built or not chunk.anchor:
            return None
        docs = [self.query_one("#article", MarkdownViewer).document, self.query_one("#side-doc", Markdown)]
        for doc in docs:
            for _, block, text in doc_items(doc):
                if text[:60] == chunk.anchor:
                    return block
        return None

    # ------------------------------------------------------------ actions
    def action_refresh_article(self) -> None:
        if self.sid:
            self.show_saint(self.sid, refresh=True)

    def action_page(self, step: int) -> None:
        viewer = self.query_one("#article", MarkdownViewer)
        if step > 0:
            viewer.scroll_page_down()
        else:
            viewer.scroll_page_up()

    def action_toggle_toc(self) -> None:
        v = self.query_one("#article", MarkdownViewer)
        show = not v.show_table_of_contents
        toc = v.table_of_contents
        if not show and self.app.focused is not None and toc in self.app.focused.ancestors_with_self:
            v.document.focus()                  # don't leave the cursor in a list that disappears
        v.show_table_of_contents = show
        if show:
            tree = toc.query(Tree)
            (tree.first() if tree else toc).focus()

    def action_toggle_header(self) -> None:
        self._hero_wanted = not self._hero_wanted
        self.query_one("#focus-hero").display = self._hero_wanted and self.sid is not None
        self._render_article()                  # the facts move into the article while the header is hidden

    def action_view_icon(self) -> None:
        """V: the icon as large as the window allows, with the hymns beside it."""
        if not self.sid:
            self.set_status("Open a saint first.")
            return
        from .modals import IconView
        self.app.push_screen(IconView(self.sid))

    def on_click(self, event) -> None:
        if getattr(event, "widget", None) is not None and event.widget.id == "hero-icon":
            self.action_view_icon()

    def action_open_browser(self) -> None:
        if not self.sid:
            self.set_status("Open a saint first.")
            return
        ctx = self.app.ctx
        s = ctx.db.get_saint(self.sid)
        url = web_url(s, ctx.db.article(self.sid), ctx.db.stories(self.sid)) if s else None
        if url:
            try:
                webbrowser.open(url)
                self.set_status(f"Opened {url}")
            except Exception:
                self.set_status(url)
        else:
            self.set_status("No web page is linked for this saint yet.")

    def action_back(self) -> None:
        """Back to the list the saint came from, with the cursor on the saint."""
        if self.origin == "home":
            self.app.show_tab("home")
            self.app.w_home.focus_saint(self.sid)
        else:
            self.app.show_tab("search")
            self.app.w_search.focus_result(self.sid)

    def action_toggle_saved(self) -> None:
        if not self.sid:
            self.set_status("Open a saint first.")
            return
        db = self.app.ctx.db
        s = db.get_saint(self.sid)
        if not s:
            self.set_status("This saint is no longer in the directory.")
            return
        on = not db.is_favorite(self.sid)
        db.set_favorite(self.sid, on)
        self.set_status(f"Saved {s['name']} {glyphs(self.app)['saved']}" if on else "Removed from your saved saints")
        self._show_hero(s)
        self._relabel()
        self.app.favorites_changed()

    def action_step(self, step: int) -> None:
        pos = self._pos()
        if pos is None:
            self.set_status("Open a saint from Home or Search to step through the list.")
            return
        nxt = pos + step
        if nxt >= len(self.context) and self.origin == "search" and len(self.context) < (self.context_total or 0):
            self.context = self.app.w_search.more_ids()        # load the next page of results
        if 0 <= nxt < len(self.context):
            self.show_saint(self.context[nxt])
        else:
            self.set_status("That was the " + ("first" if step < 0 else "last") + " saint of the list.")

    def on_button_pressed(self, ev: Button.Pressed) -> None:
        {"fx-back": self.action_back, "fx-refresh": self.action_refresh_article,
         "fx-toc": self.action_toggle_toc, "fx-browser": self.action_open_browser,
         "fx-save": self.action_toggle_saved, "fx-prev": lambda: self.action_step(-1),
         "fx-next": lambda: self.action_step(1), "fx-listen": self.listen}.get(ev.button.id, lambda: None)()
        viewer = self.query_one("#article", MarkdownViewer)
        if ev.button.id != "fx-back" and not (ev.button.id == "fx-toc" and viewer.show_table_of_contents):
            viewer.document.focus()             # ↑ ↓ PgUp PgDn scroll again (also when Contents closes)

    def on_markdown_link_clicked(self, ev) -> None:
        href = getattr(ev, "href", "") or ""
        if href.startswith("saint:"):
            ev.prevent_default()
            try:
                sid = int(href.split(":", 1)[1])
            except ValueError:
                return
            ctx = self.app.ctx
            s = ctx.db.get_saint(self.sid) if self.sid else None
            same = []
            if s:
                fs = ctx.db.feasts(s["id"])
                if fs:
                    main = next((f for f in fs if not f["label"]), fs[0])
                    same = [x["id"] for x in ctx.db.saints_on(main["month"], main["day"])]
            self.post_message(OpenSaint(sid, context=same or [sid], origin=self.origin))
        elif href.startswith("http"):
            ev.prevent_default()
            try:
                webbrowser.open(href)
            except Exception:
                pass

    def focus_first(self) -> None:
        self.when_built(lambda: self.query_one("#article", MarkdownViewer).document.focus(), focus=True)
