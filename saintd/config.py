"""User settings, stored as JSON under ~/.config/saintd/."""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any


def _xdg(var: str, fallback: str) -> Path:
    return Path(os.environ.get(var) or Path.home() / fallback)


def home_override() -> Path | None:
    v = os.environ.get("SAINTD_HOME")
    return Path(v) if v else None


def config_dir() -> Path:
    o = home_override()
    p = (o / "config") if o else _xdg("XDG_CONFIG_HOME", ".config") / "saintd"
    p.mkdir(parents=True, exist_ok=True)
    return p


def data_dir() -> Path:
    o = home_override()
    p = (o / "data") if o else _xdg("XDG_DATA_HOME", ".local/share") / "saintd"
    p.mkdir(parents=True, exist_ok=True)
    return p


def cache_dir() -> Path:
    """Downloaded icons (safe to delete; they are fetched again when needed)."""
    o = home_override()
    p = (o / "cache") if o else _xdg("XDG_CACHE_HOME", ".cache") / "saintd"
    p.mkdir(parents=True, exist_ok=True)
    return p


DEFAULTS: dict[str, Any] = {
    "theme": "terracotta",
    "glyphs": "unicode",            # unicode | ascii
    "calendar": "new",              # new (Revised Julian) | old (Julian)
    "include_greek": True,          # Greek-tradition commemorations from orthocal
    "use_azbyka": True,             # Russian calendar (Azbuka Very), translated
    "use_wikical": True,            # Wikipedia's 366 Orthodox calendar day pages
    "use_wikimedia": True,          # Wikidata facts + Wikipedia articles
    "auto_enrich": True,            # keep enriching the directory in the background
    "translate_articles": True,     # translate non-English Wikipedia articles when needed
    "use_mystagogy": True,          # English lives from the Mystagogy Resource Center
    "use_azbyka_lives": True,       # Russian lives from Azbuka Very saint pages, translated
    "use_htc": True,                # Holy Trinity calendar: English lives, troparia and kontakia
    "use_orthodoxwiki": True,       # OrthodoxWiki articles when Wikipedia has none
    "show_icons": True,             # download and show icons of the saints
    "graphics": "auto",             # auto | kitty | sixel | blocks | off
    "translator": "mymemory",       # mymemory | lingva | libretranslate | ollama | off
    "mymemory_email": "",
    "lingva_url": "https://lingva.ml",
    "libre_url": "http://localhost:5000",
    "libre_key": "",
    "ollama_url": "http://localhost:11434",
    "ollama_model": "",
    "timeout": 25,                  # seconds per request
    "contact": "",                  # e-mail or URL for Wikimedia's User-Agent policy (optional)
    "asked_contact": False,         # first-run question already shown
    "article_max_age_days": 30,
    # reading aloud
    "tts_engine": "auto",           # auto | piper | rhvoice | pico | espeak | speechd | festival
    "tts_voices": {},               # engine -> chosen voice
    "tts_rate": 1.0,                # speed, 1.0 = normal
    "tts_follow": True,             # highlight the paragraph being read and keep it in view
    "tts_hymns": True,              # read the troparion and kontakion too
    "tts_history": True,            # read the history (Wikipedia / OrthodoxWiki) after the life
    "tts_asked_voice": False,       # the "choose a voice" window has been shown
}

TRANSLATORS = ["mymemory", "lingva", "libretranslate", "ollama", "off"]
_CHOICES = {"translator": TRANSLATORS, "calendar": ["new", "old"], "glyphs": ["unicode", "ascii"],
            "graphics": ["auto", "kitty", "sixel", "blocks", "off"],
            "tts_engine": ["auto", "piper", "rhvoice", "pico", "espeak", "speechd", "festival"]}


class Config:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or (config_dir() / "config.json")
        self._lock = threading.RLock()
        self.data: dict[str, Any] = dict(DEFAULTS)
        self.load()

    def load(self) -> None:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                for k, v in raw.items():
                    if k in DEFAULTS and isinstance(v, type(DEFAULTS[k])) or (
                        k in DEFAULTS and isinstance(DEFAULTS[k], float) and isinstance(v, (int, float))
                    ):
                        self.data[k] = v
        except (OSError, ValueError):
            pass
        # values a hand-edited or older config may hold that this version doesn't know
        for k, allowed in _CHOICES.items():
            if self.data.get(k) not in allowed:
                self.data[k] = DEFAULTS[k]
        tv = self.data.get("tts_voices")
        self.data["tts_voices"] = {str(k): v for k, v in tv.items() if isinstance(v, str)} if isinstance(tv, dict) else {}
        try:
            self.data["tts_rate"] = max(0.5, min(2.5, float(self.data["tts_rate"])))
        except (TypeError, ValueError):
            self.data["tts_rate"] = 1.0

    def voice_for(self, engine: str) -> str:
        return (self.data.get("tts_voices") or {}).get(engine, "")

    def set_voice(self, engine: str, voice: str) -> None:
        self.set("tts_voices", {**(self.data.get("tts_voices") or {}), engine: voice})

    def save(self) -> None:
        with self._lock:
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.data, indent=2, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, self.path)

    def __getitem__(self, k: str) -> Any:
        return self.data.get(k, DEFAULTS.get(k))

    def get(self, k: str, default: Any = None) -> Any:
        return self.data.get(k, default if default is not None else DEFAULTS.get(k))

    def set(self, k: str, v: Any, save: bool = True) -> None:
        if k in _CHOICES and v not in _CHOICES[k]:
            v = DEFAULTS[k]                      # never store a choice this version can't use
        with self._lock:
            self.data[k] = v
            if save:
                self.save()
