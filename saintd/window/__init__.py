"""saintd in a window of its own: saintd.exe on Windows, and `saintd --window`
wherever Python has tkinter.

The interface is the same Textual app that runs in a terminal, unchanged. This
package is the terminal around it:

* driver.py  hands the app's output (the escape codes a terminal receives) to
* vt.py      a small terminal that keeps the grid of cells and the pictures,
* paint.py   which Pillow paints, a row at a time, with fonts from fonts.py,
* tkwin.py   into a tkinter window, which sends keys and the mouse back the
             way Kitty and Ghostty do (keys.py).

Pictures travel by the Kitty graphics protocol, so the eagle, its pulse of
light and the icons look as they do in Kitty and Ghostty.
"""

import sys


def main() -> int:
    from .tkwin import run
    return run()


def exe_main() -> int:
    """saintd.exe, the Windows program. saintd starts its sound player with its own
    Python (sys.executable -I -c ...), and in the program sys.executable is
    saintd.exe itself: such a start plays the sound instead of opening a window."""
    args = [a for a in sys.argv[1:] if a not in ("-I", "-u", "-E", "-s", "-B")]
    if args[:1] in (["-c"], ["-m"]):
        try:                        # an error ends the helper (saintd sees it fail), never a dialog
            if args[0] == "-c" and len(args) >= 3 and "winsound.PlaySound" in args[1]:
                import winsound
                winsound.PlaySound(args[2], winsound.SND_FILENAME | winsound.SND_NODEFAULT)
                return 0
            if args[:2] == ["-m", "saintd.piper_worker"]:
                from .. import piper_worker
                sys.argv = ["saintd.piper_worker", *args[2:]]
                return piper_worker.main()
        except Exception:
            return 1
        return 2
    return main()
