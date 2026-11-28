"""What differs between Linux, macOS and Windows, kept in one place."""

from __future__ import annotations

import subprocess
import sys

WINDOWS = sys.platform == "win32"
MACOS = sys.platform == "darwin"
LINUX = not (WINDOWS or MACOS)          # and the other Unix systems, which follow Linux

NAME = "Windows" if WINDOWS else "macOS" if MACOS else "Linux"
PROGRAM = bool(getattr(sys, "frozen", False))   # saintd.exe, the Windows program (Python and saintd in one file)


def pick(linux: str, macos: str, windows: str) -> str:
    """The text (a hint, a command) for this kind of computer."""
    return windows if WINDOWS else macos if MACOS else linux


def detached(low_priority: bool = False) -> dict:
    """Keyword arguments for subprocess.Popen/run that keep a helper program (a voice,
    an audio player) away from the terminal the interface draws on: its own session on
    Linux and macOS (Ctrl+C and the terminal's signals stay with saintd), no console on
    Windows (it cannot print over the screen or open a window)."""
    if WINDOWS:
        flags = subprocess.CREATE_NO_WINDOW
        if low_priority:
            flags |= subprocess.BELOW_NORMAL_PRIORITY_CLASS
        return {"creationflags": flags}
    return {"start_new_session": True}
