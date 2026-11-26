"""Service container shared by the TUI and the command line."""

from __future__ import annotations

from .article import ArticleBuilder
from .config import Config, data_dir
from .db import DB
from .net import Http
from .sync import Syncer
from .translate import Translator


class Context:
    def __init__(self, cfg: Config | None = None) -> None:
        self.cfg = cfg or Config()
        self.db = DB(data_dir() / "saints.db")
        # Separate clients so pausing the background sync never cancels what the user is reading.
        self.http_bg = self._http()
        self.http_fg = self._http(foreground=True)
        self.tr_bg = Translator(self.cfg, self.db, self.http_bg)
        self.tr_fg = Translator(self.cfg, self.db, self.http_fg)
        self.syncer = Syncer(self.cfg, self.db, self.http_bg, self.tr_bg)
        fg_syncer = Syncer(self.cfg, self.db, self.http_fg, self.tr_fg)
        self.articles = ArticleBuilder(self.cfg, self.db, self.http_fg, self.tr_fg, fg_syncer)

    def _http(self, foreground: bool = False) -> Http:
        return Http(timeout=float(self.cfg["timeout"]), contact=self.cfg["contact"], cache=self.db,
                    foreground=foreground)

    def apply_network_settings(self) -> None:
        for h in (self.http_bg, self.http_fg):
            h.set_identity(self.cfg["contact"])
            h.timeout = float(self.cfg["timeout"])

    def directory_built(self) -> bool:
        return bool(self.db.meta("built_at"))

    def close(self) -> None:
        self.http_bg.stop.set()
        self.http_fg.stop.set()
        # give a running build/link step a moment to notice and release the database
        if self.syncer.lock.acquire(timeout=3):
            self.syncer.lock.release()
        self.http_bg.close()
        self.http_fg.close()
        self.db.close()
