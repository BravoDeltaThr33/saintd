"""Works out which terminal saintd runs in and what it can draw.

Two sources of evidence are combined:

* the environment variables terminals set (TERM_PROGRAM, KITTY_WINDOW_ID,
  VTE_VERSION, KONSOLE_VERSION, WT_SESSION, ...), and
* the terminal's own answers to a few standard queries, sent once before the
  interface starts: XTVERSION (name and version), a Kitty graphics query,
  the cell size in pixels and Primary Device Attributes (whose "4" means
  Sixel graphics). On Linux and macOS they are read from the terminal device;
  on Windows from the console's input, where the answers arrive as if typed.

The result decides how saint icons are drawn:

* ``kitty``  — real images through the Kitty graphics protocol (Kitty, Ghostty)
* ``sixel``  — real images as Sixel graphics (WezTerm, foot, Konsole, xterm -ti vt340 ...)
* ``blocks`` — coloured half-block mosaics (any truecolor or 256-colour terminal)
* ``off``    — no images (the Linux console, dumb terminals)
"""

from __future__ import annotations

import os
import re
import sys
import time
from dataclasses import dataclass, field

from .system import WINDOWS

GRAPHICS_MODES = ("kitty", "sixel", "blocks", "off")
MODE_LABELS = {
    "kitty": "Kitty graphics (true images)",
    "sixel": "Sixel graphics (true images)",
    "blocks": "Colour blocks (half-block mosaic)",
    "off": "Off",
}

# terminals whose Kitty graphics support includes the Unicode placeholders saintd
# uses, and the first version that has them (kitty 0.28, Ghostty 1.0)
_KITTY_PLACEHOLDERS = {"kitty": (0, 28), "ghostty": (1, 0)}
# Konsole draws Sixel from 22.04 on
_SIXEL_SINCE = {"konsole": (22, 4)}


def version_tuple(v: str) -> tuple[int, ...]:
    """'0.39.1' -> (0, 39, 1); '1.3.1-arch2' -> (1, 3, 1); '' -> ()"""
    out = []
    for part in re.split(r"[.\-+_ ]", v.strip().lstrip("vV")):
        if not part.isdigit():
            break
        out.append(int(part))
    return tuple(out)
# terminals known to draw Sixel graphics (also detected from their device attributes)
_SIXEL_NAMES = {"wezterm", "foot", "konsole", "mlterm", "contour", "iterm2", "xterm", "mintty", "blackbox",
                "rio", "windows terminal", "warp"}
_TRUECOLOR_NAMES = {"kitty", "ghostty", "wezterm", "iterm2", "konsole", "alacritty", "foot", "windows terminal",
                    "contour", "rio", "tilix", "gnome terminal", "terminator", "vte", "warp", "vs code", "hyper",
                    "mintty", "xfce terminal", "blackbox", "terminology", "tabby", "st", "conhost"}


@dataclass
class TermInfo:
    name: str = "Unknown terminal"
    version: str = ""
    family: str = ""               # lower-case key: kitty, ghostty, wezterm, vte, ...
    term: str = ""                 # $TERM
    truecolor: bool = False
    colors: int = 16
    kitty_graphics: bool = False   # answered the Kitty graphics query
    sixel: bool = False            # device attributes include Sixel (or known to)
    multiplexer: str = ""          # "tmux 3.4", "GNU screen", ""
    cell_px: tuple[int, int] = (0, 0)
    probed: bool = False           # the terminal itself answered our queries
    xtversion: str = ""
    da1: str = ""
    notes: list[str] = field(default_factory=list)

    @property
    def label(self) -> str:
        return f"{self.name} {self.version}".strip()

    @property
    def unicode_ok(self) -> bool:
        return self.term not in ("linux", "dumb", "vt100", "vt220")

    @property
    def kitty_placeholders(self) -> bool:
        """Kitty graphics with Unicode placeholders (kitty 0.28+, Ghostty 1.0+;
        an unknown version is taken to be recent)."""
        need = _KITTY_PLACEHOLDERS.get(self.family)
        if need is None:
            return False
        have = version_tuple(self.version)
        return not have or have >= need

    def best_graphics(self) -> str:
        """The best way to draw images in this terminal."""
        if not self.unicode_ok or self.term == "dumb":
            return "off"
        if not self.multiplexer:
            if self.kitty_placeholders and (self.kitty_graphics or not self.probed) and self.truecolor:
                return "kitty"
            if self.sixel:
                return "sixel"
        if self.truecolor or self.colors >= 256:
            return "blocks"
        return "off"

    def supports(self, mode: str) -> bool:
        if mode == "kitty":
            return self.kitty_placeholders and self.truecolor and not self.multiplexer
        if mode == "sixel":
            return self.sixel and not self.multiplexer
        if mode == "blocks":
            return self.unicode_ok
        return True

    def _kitty_row(self) -> str:
        if self.kitty_placeholders and self.truecolor:
            return "yes"
        need = _KITTY_PLACEHOLDERS.get(self.family)
        if need:
            return f"needs {self.name} {'.'.join(map(str, need))} or newer (this is {self.version})"
        return "answers, without Unicode placeholders" if self.kitty_graphics else "no"

    def summary(self) -> list[tuple[str, str]]:
        rows = [("Terminal", self.label + ("" if self.probed else "  (from environment)")),
                ("Colours", "24-bit truecolor" if self.truecolor else f"{self.colors} colours"),
                ("Kitty graphics", self._kitty_row()),
                ("Sixel graphics", "yes" if self.sixel else "no")]
        if self.cell_px[0]:
            rows.append(("Cell size", f"{self.cell_px[0]}×{self.cell_px[1]} pixels"))
        if self.multiplexer:
            rows.append(("Multiplexer", f"{self.multiplexer} (images fall back to colour blocks)"))
        rows.append(("Best images", MODE_LABELS[self.best_graphics()]))
        return rows


# ---------------------------------------------------------------- environment

def _vte_version(v: str) -> str:
    """VTE_VERSION=7200 -> 0.72"""
    try:
        n = int(v)
        return f"0.{n // 100 % 100}" if n < 10000 else f"{n // 10000}.{n // 100 % 100}"
    except ValueError:
        return v


def _konsole_version(v: str) -> str:
    """KONSOLE_VERSION=230804 -> 23.08.4"""
    if v.isdigit() and len(v) >= 5:
        return f"{int(v[:-4])}.{v[-4:-2]}.{int(v[-2:])}"
    return v


def from_environment(env: dict | None = None) -> TermInfo:
    e = dict(os.environ if env is None else env)
    term = e.get("TERM", "")
    prog = e.get("TERM_PROGRAM", "")
    pver = e.get("TERM_PROGRAM_VERSION", "")
    info = TermInfo(term=term)
    if e.get("TMUX"):
        info.multiplexer = "tmux" + (f" {pver}" if prog == "tmux" and pver else "")
    elif e.get("STY") or term.startswith("screen") and not e.get("TMUX"):
        info.multiplexer = "GNU screen" if e.get("STY") else ""

    def setn(name, family, version=""):
        info.name, info.family, info.version = name, family, version

    if e.get("KITTY_WINDOW_ID") or term == "xterm-kitty":
        setn("kitty", "kitty", pver if prog == "kitty" else "")
    elif prog.lower() == "ghostty" or term == "xterm-ghostty" or e.get("GHOSTTY_RESOURCES_DIR"):
        setn("Ghostty", "ghostty", pver if prog.lower() == "ghostty" else "")
    elif prog == "WezTerm" or e.get("WEZTERM_EXECUTABLE"):
        setn("WezTerm", "wezterm", pver)
    elif prog == "iTerm.app" or e.get("LC_TERMINAL") == "iTerm2":
        setn("iTerm2", "iterm2", pver or e.get("LC_TERMINAL_VERSION", ""))
    elif prog == "Apple_Terminal":
        setn("Terminal.app", "apple", pver)
    elif prog == "vscode":
        setn("VS Code terminal", "vs code", pver)
    elif prog == "WarpTerminal":
        setn("Warp", "warp", pver)
    elif prog == "rio":
        setn("Rio", "rio", pver)
    elif prog == "Hyper":
        setn("Hyper", "hyper", pver)
    elif prog == "Tabby":
        setn("Tabby", "tabby", pver)
    elif e.get("KONSOLE_VERSION"):
        setn("Konsole", "konsole", _konsole_version(e["KONSOLE_VERSION"]))
    elif e.get("TILIX_ID"):
        setn("Tilix", "tilix", f"(VTE {_vte_version(e['VTE_VERSION'])})" if e.get("VTE_VERSION") else "")
    elif e.get("TERMINATOR_UUID"):
        setn("Terminator", "terminator", "")
    elif e.get("GNOME_TERMINAL_SCREEN") or e.get("GNOME_TERMINAL_SERVICE"):
        setn("GNOME Terminal", "gnome terminal",
             f"(VTE {_vte_version(e['VTE_VERSION'])})" if e.get("VTE_VERSION") else "")
    elif e.get("ALACRITTY_SOCKET") or e.get("ALACRITTY_LOG") or e.get("ALACRITTY_WINDOW_ID") or term == "alacritty":
        setn("Alacritty", "alacritty", "")
    elif term.startswith("foot"):
        setn("foot", "foot", "")
    elif e.get("TERMINOLOGY"):
        setn("Terminology", "terminology", "")
    elif e.get("WT_SESSION"):
        setn("Windows Terminal", "windows terminal", "")
    elif term.startswith("contour") or e.get("TERMINAL_NAME") == "contour":
        setn("Contour", "contour", e.get("TERMINAL_VERSION_STRING", ""))
    elif term.startswith("mlterm"):
        setn("mlterm", "mlterm", "")
    elif e.get("VTE_VERSION"):
        setn("VTE terminal", "vte", _vte_version(e["VTE_VERSION"]))
    elif e.get("XTERM_VERSION"):
        m = re.match(r"XTerm\((\d+)\)", e["XTERM_VERSION"])
        setn("xterm", "xterm", m.group(1) if m else "")
    elif term == "linux":
        setn("Linux console", "linux", "")
    elif term.startswith("st-") or term == "st":
        setn("st", "st", "")
    elif prog == "tmux" and info.multiplexer:
        setn("Terminal inside tmux", "", "")
    elif term:
        setn(f"Unknown terminal ({term})", "", "")
    elif WINDOWS:
        # the console window of Windows 10 and 11 (cmd, PowerShell): 24-bit colour, no images
        setn("Windows console", "conhost", "")

    ct = e.get("COLORTERM", "").lower()
    info.truecolor = ct in ("truecolor", "24bit") or info.family in _TRUECOLOR_NAMES
    if info.truecolor:
        info.colors = 1 << 24
    elif "256" in term:
        info.colors = 256
    elif term in ("linux", "dumb"):
        info.colors = 8
    else:
        info.colors = 16
    if info.family in ("wezterm", "foot", "konsole", "mlterm", "contour"):
        # confirmed or corrected by the device attributes when probed
        since = _SIXEL_SINCE.get(info.family)
        have = version_tuple(info.version)
        info.sixel = not since or not have or have >= since
    return info


# ---------------------------------------------------------------- probing

_XTVERSION = re.compile(r"\x1bP>\|(.*?)(?:\x1b\\|\x07)", re.S)
_KITTY_OK = re.compile(r"\x1b_Gi=4242[^;]*;OK\x1b\\")
_DA1 = re.compile(r"\x1b\[\?([\d;]*)c")
_CELL = re.compile(r"\x1b\[6;(\d+);(\d+)t")


def parse_xtversion(text: str) -> tuple[str, str]:
    """'kitty(0.39.1)' -> ('kitty', '0.39.1'); 'ghostty 1.1.3' -> ('ghostty', '1.1.3')"""
    text = text.strip()
    m = re.match(r"^(.*?)[\s(]+v?(\d[\w.+-]*)\)?\s*$", text)
    if m:
        return m.group(1).strip(), m.group(2)
    return text, ""


_FAMILY_FROM_XT = [("kitty", "kitty", "kitty"), ("ghostty", "ghostty", "Ghostty"), ("wezterm", "wezterm", "WezTerm"),
                   ("foot", "foot", "foot"), ("xterm", "xterm", "xterm"), ("konsole", "konsole", "Konsole"),
                   ("iterm2", "iterm2", "iTerm2"), ("contour", "contour", "Contour"), ("mintty", "mintty", "mintty"),
                   ("mlterm", "mlterm", "mlterm"), ("alacritty", "alacritty", "Alacritty"),
                   ("rio", "rio", "Rio"), ("tmux", "tmux", "tmux"), ("warp", "warp", "Warp")]


def apply_answers(info: TermInfo, answers: str) -> TermInfo:
    """Fold the terminal's answers to our queries into `info`."""
    m = _XTVERSION.search(answers)
    if m:
        info.xtversion = m.group(1)
        name, ver = parse_xtversion(m.group(1))
        low = name.lower()
        for key, family, pretty in _FAMILY_FROM_XT:
            if low.startswith(key):
                if family == "tmux":
                    info.multiplexer = f"tmux {ver}".strip()
                else:
                    info.name, info.family, info.version = pretty, family, ver
                break
        else:
            if name:
                info.name, info.family, info.version = name, low, ver
    if _KITTY_OK.search(answers):
        info.kitty_graphics = True
    m = _DA1.search(answers)
    if m:
        info.da1 = m.group(1)
        info.sixel = "4" in m.group(1).split(";")
    m = _CELL.search(answers)
    if m and not info.cell_px[0]:
        info.cell_px = (int(m.group(2)), int(m.group(1)))
    if info.family in _TRUECOLOR_NAMES:
        info.truecolor, info.colors = True, 1 << 24
    info.probed = bool(info.da1)
    return info


def _cell_px_ioctl() -> tuple[int, int]:
    try:
        import fcntl
        import struct
        import termios
        buf = fcntl.ioctl(sys.__stdout__.fileno(), termios.TIOCGWINSZ, b"\0" * 8)
        rows, cols, xpix, ypix = struct.unpack("HHHH", buf)
        if rows and cols and xpix and ypix:
            return xpix // cols, ypix // rows
    except Exception:
        pass
    return (0, 0)


def _queries(info: TermInfo) -> str:
    queries = "\x1b[>0q"                                            # XTVERSION
    if not WINDOWS and info.family in ("", "kitty", "ghostty", "wezterm", "konsole", "xterm", "foot", "contour",
                                       "iterm2", "rio"):
        queries += "\x1b_Gi=4242,s=1,v=1,a=q,t=d,f=24;AAAA\x1b\\"  # Kitty graphics
    if not info.cell_px[0]:
        queries += "\x1b[16t"                                       # cell size in pixels
    return queries + "\x1b[c"                                       # DA1: every terminal answers this


def probe(info: TermInfo, timeout: float = 0.35) -> TermInfo:
    """Ask the terminal about itself. Only call this before the interface
    starts (afterwards Textual owns the input)."""
    if os.environ.get("SAINTD_NO_PROBE") or info.term in ("linux", "dumb") or (info.term == "" and not WINDOWS):
        return info
    try:
        if not (sys.__stdin__ and sys.__stdout__ and sys.__stdin__.isatty() and sys.__stdout__.isatty()):
            return info
    except Exception:
        return info
    if WINDOWS:
        try:
            return apply_answers(info, _ask_windows_console(_queries(info), timeout))
        except Exception:
            return info
    try:
        import select
        import termios
        import tty
    except Exception:
        return info
    info.cell_px = _cell_px_ioctl()
    fd = sys.__stdin__.fileno()
    queries = _queries(info)
    try:
        old = termios.tcgetattr(fd)
    except Exception:
        return info
    got = ""
    try:
        tty.setcbreak(fd, termios.TCSANOW)
        sys.__stdout__.write(queries)
        sys.__stdout__.flush()
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            r, _, _ = select.select([fd], [], [], max(0.0, end - time.monotonic()))
            if not r:
                break
            chunk = os.read(fd, 4096).decode("utf-8", "replace")
            if not chunk:
                break
            got += chunk
            if _DA1.search(got):
                # the DA1 answer comes last; give a straggler a moment, then stop
                r, _, _ = select.select([fd], [], [], 0.01)
                if r:
                    got += os.read(fd, 4096).decode("utf-8", "replace")
                break
    except Exception:
        pass
    finally:
        try:
            termios.tcsetattr(fd, termios.TCSANOW, old)
        except Exception:
            pass
    return apply_answers(info, got)


def _ask_windows_console(queries: str, timeout: float) -> str:
    """Windows: send the queries and read the answers, which the console hands
    over as typed characters once virtual-terminal input is on. Never blocks:
    only the events already waiting are read."""
    import ctypes
    import msvcrt
    from ctypes import wintypes

    class KEY_EVENT_RECORD(ctypes.Structure):
        _fields_ = [("bKeyDown", wintypes.BOOL), ("wRepeatCount", wintypes.WORD),
                    ("wVirtualKeyCode", wintypes.WORD), ("wVirtualScanCode", wintypes.WORD),
                    ("UnicodeChar", wintypes.WCHAR), ("dwControlKeyState", wintypes.DWORD)]

    class EVENT(ctypes.Union):
        _fields_ = [("KeyEvent", KEY_EVENT_RECORD), ("raw", ctypes.c_byte * 16)]

    class INPUT_RECORD(ctypes.Structure):
        _fields_ = [("EventType", wintypes.WORD), ("Event", EVENT)]

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.GetConsoleMode.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    k32.SetConsoleMode.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    k32.FlushConsoleInputBuffer.argtypes = [wintypes.HANDLE]
    k32.GetNumberOfConsoleInputEvents.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    k32.ReadConsoleInputW.argtypes = [wintypes.HANDLE, ctypes.POINTER(INPUT_RECORD), wintypes.DWORD,
                                      ctypes.POINTER(wintypes.DWORD)]
    hin = wintypes.HANDLE(msvcrt.get_osfhandle(sys.__stdin__.fileno()))
    hout = wintypes.HANDLE(msvcrt.get_osfhandle(sys.__stdout__.fileno()))
    in_mode, out_mode = wintypes.DWORD(), wintypes.DWORD()
    if not k32.GetConsoleMode(hin, ctypes.byref(in_mode)) or not k32.GetConsoleMode(hout, ctypes.byref(out_mode)):
        return ""                                       # not a console
    ENABLE_VIRTUAL_TERMINAL_INPUT, ENABLE_PROCESSED_OUTPUT, ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x200, 0x1, 0x4
    got = ""
    try:
        k32.SetConsoleMode(hin, ENABLE_VIRTUAL_TERMINAL_INPUT)       # no echo, no line editing
        k32.SetConsoleMode(hout, out_mode.value | ENABLE_PROCESSED_OUTPUT | ENABLE_VIRTUAL_TERMINAL_PROCESSING)
        k32.FlushConsoleInputBuffer(hin)
        sys.__stdout__.write(queries)
        sys.__stdout__.flush()
        records = (INPUT_RECORD * 64)()
        n = wintypes.DWORD()
        end = time.monotonic() + timeout
        while time.monotonic() < end and not _DA1.search(got):       # the DA1 answer comes last
            if not k32.GetNumberOfConsoleInputEvents(hin, ctypes.byref(n)):
                break
            if not n.value:
                time.sleep(0.005)
                continue
            if not k32.ReadConsoleInputW(hin, records, len(records), ctypes.byref(n)):
                break
            for r in records[:n.value]:
                key = r.Event.KeyEvent
                if r.EventType == 1 and key.bKeyDown and key.UnicodeChar not in ("", "\0"):
                    got += key.UnicodeChar
    finally:
        k32.FlushConsoleInputBuffer(hin)                            # nothing of it reaches the interface
        k32.SetConsoleMode(hin, in_mode.value)
        k32.SetConsoleMode(hout, out_mode.value)
    return got


_INFO: TermInfo | None = None


def detect(probe_terminal: bool = True) -> TermInfo:
    """The terminal saintd runs in (computed once)."""
    global _INFO
    if _INFO is None:
        info = from_environment()
        if probe_terminal:
            info = probe(info)
        if not info.cell_px[0]:
            info.cell_px = _cell_px_ioctl()
        _INFO = info
    return _INFO


def current() -> TermInfo:
    return _INFO if _INFO is not None else detect(probe_terminal=False)


def effective_mode(setting: str, info: TermInfo | None = None) -> str:
    """The graphics mode to use for a Settings choice ('auto' or a mode)."""
    info = info or current()
    forced = os.environ.get("SAINTD_GRAPHICS", "").lower()
    if forced in GRAPHICS_MODES:
        return forced
    if setting in GRAPHICS_MODES:
        return setting
    return info.best_graphics()


def report(info: TermInfo) -> str:
    lines = ["Saint Directory — terminal report", ""]
    for k, v in info.summary():
        lines.append(f"  {k:<15} {v}")
    lines.append("")
    lines.append(f"  $TERM           {info.term or '(not set)'}")
    if info.xtversion:
        lines.append(f"  XTVERSION       {info.xtversion}")
    if info.da1:
        lines.append(f"  Device attrs    {info.da1}")
    return "\n".join(lines)
