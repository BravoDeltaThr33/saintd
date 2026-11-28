"""Keys and the mouse, as the window sends them to the app: the bytes Kitty and
Ghostty send (the kitty keyboard protocol, SGR mouse reports, bracketed paste),
so that Textual reads them exactly as it does in those terminals."""

from __future__ import annotations

from ..system import MACOS, WINDOWS

SHIFT, CTRL = 0x1, 0x4
if WINDOWS:
    ALT, SUPER = 0x20000, 0
elif MACOS:
    ALT, SUPER = 0x10, 0x8          # Option, Command
else:
    ALT, SUPER = 0x8, 0x40          # Mod1, Mod4

# Tk key names -> (number, final character) of the kitty keyboard protocol
FUNCTIONAL = {
    "Escape": ("27", "u"), "Return": ("13", "u"), "KP_Enter": ("13", "u"), "Tab": ("9", "u"),
    "ISO_Left_Tab": ("9", "u"), "BackSpace": ("127", "u"),
    "Insert": ("2", "~"), "Delete": ("3", "~"), "Prior": ("5", "~"), "Next": ("6", "~"),
    "Left": ("1", "D"), "Right": ("1", "C"), "Up": ("1", "A"), "Down": ("1", "B"),
    "Home": ("1", "H"), "End": ("1", "F"),
    "KP_Insert": ("2", "~"), "KP_Delete": ("3", "~"), "KP_Prior": ("5", "~"), "KP_Next": ("6", "~"),
    "KP_Left": ("1", "D"), "KP_Right": ("1", "C"), "KP_Up": ("1", "A"), "KP_Down": ("1", "B"),
    "KP_Home": ("1", "H"), "KP_End": ("1", "F"),
    "F1": ("1", "P"), "F2": ("1", "Q"), "F3": ("13", "~"), "F4": ("1", "S"), "F5": ("15", "~"),
    "F6": ("17", "~"), "F7": ("18", "~"), "F8": ("19", "~"), "F9": ("20", "~"), "F10": ("21", "~"),
    "F11": ("23", "~"), "F12": ("24", "~"),
    "Menu": ("57363", "u"), "App": ("57363", "u"), "Pause": ("57362", "u"), "Print": ("57361", "u"),
}
# the window's own keys, with Ctrl, by keysym number (Tk 8.6 and 9 name some keys differently):
# = + and the keypad's +, - _ and the keypad's -, 0 and the keypad's 0
ZOOM_IN, ZOOM_OUT, ZOOM_RESET = (0x3D, 0x2B, 0xFFAB), (0x2D, 0x5F, 0xFFAD), (0x30, 0xFFB0, 0xFF9E)
# Tk key names of keys that are only modifiers (never sent on their own)
_MODIFIER_KEYS = {"Shift_L", "Shift_R", "Control_L", "Control_R", "Alt_L", "Alt_R", "Meta_L", "Meta_R",
                  "Super_L", "Super_R", "Win_L", "Win_R", "Caps_Lock", "Num_Lock", "Scroll_Lock",
                  "ISO_Level3_Shift", "Hyper_L", "Hyper_R", "Option_L", "Option_R"}


def modifiers(state: int, char: str = "") -> tuple[bool, bool, bool, bool]:
    """(shift, ctrl, alt, super) held during a key or mouse event. On Windows, AltGr
    (reported as Ctrl+Alt) that types a character counts as neither."""
    shift, ctrl, alt = bool(state & SHIFT), bool(state & CTRL), bool(state & ALT)
    sup = bool(SUPER and state & SUPER)
    if WINDOWS and ctrl and alt and char and char.isprintable():
        ctrl = alt = False
    return shift, ctrl, alt, sup


def _codepoint(keysym_num: int) -> int | None:
    """The character of a Tk key, from its keysym number (Latin-1 or Unicode keysyms)."""
    if 0x20 <= keysym_num <= 0x7E or 0xA0 <= keysym_num <= 0xFF:
        return keysym_num
    if keysym_num & 0xFF000000 == 0x01000000:
        return keysym_num & 0xFFFFFF
    return None


def encode_key(keysym: str, keysym_num: int, char: str, state: int) -> str | None:
    """The bytes Kitty sends for a key press (report all keys, with their text), or None."""
    if keysym in _MODIFIER_KEYS:
        return None
    shift, ctrl, alt, sup = modifiers(state, char)
    mods = 1 + shift + 2 * alt + 4 * ctrl + 8 * sup
    if keysym in FUNCTIONAL:
        num, final = FUNCTIONAL[keysym]
        if keysym == "ISO_Left_Tab" and not shift:
            mods += 1                                   # Shift+Tab, as X11 names it
        if mods == 1:
            return f"\x1b[{num}{final}" if final in "~u" else f"\x1b[{final}"
        return f"\x1b[{num};{mods}{final}"
    text = char if char and char.isprintable() else ""
    if text and not (ctrl or alt or sup):
        base = text[0].lower() if len(text) == 1 else text[0]
        codes = ":".join(str(ord(c)) for c in text)
        return f"\x1b[{ord(base)};{'' if mods == 1 else mods};{codes}u"
    cp = _codepoint(keysym_num)
    if cp is None and text:
        cp = ord(text[0])
    if cp is None:
        return None
    base = chr(cp).lower()
    if len(base) != 1:
        base = chr(cp)
    return f"\x1b[{ord(base)};{mods}u" if mods != 1 else f"\x1b[{ord(base)}u"


def mouse(kind: str, button: int, col: int, row: int, state: int) -> str:
    """An SGR mouse report. kind: press, release, move, wheel; button: 1 left, 2 middle,
    3 right (move: the button held, or 0); for the wheel 4 up, 5 down, 6 left, 7 right."""
    shift, ctrl, alt, _sup = modifiers(state)
    mod = 4 * shift + 8 * alt + 16 * ctrl
    if kind == "wheel":
        code = 64 + (button - 4)
    elif kind == "move":
        code = 32 + ({1: 0, 2: 1, 3: 2}.get(button, 3))
    else:
        code = {1: 0, 2: 1, 3: 2}.get(button, 0)
    return f"\x1b[<{code + mod};{col + 1};{row + 1}{'m' if kind == 'release' else 'M'}"


def paste(text: str) -> str:
    """Text pasted from the clipboard, as a bracketed paste."""
    text = text.replace("\r\n", "\n").replace("\x1b", "")
    return f"\x1b[200~{text}\x1b[201~"


FOCUS_IN, FOCUS_OUT = "\x1b[I", "\x1b[O"
