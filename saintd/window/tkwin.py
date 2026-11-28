"""saintd's own window (tkinter).

The app runs in a thread of its own, exactly as it runs in a terminal; this
thread runs the window: it paints the cells that changed, a row at a time, and
turns keys, the mouse, resizing and the clipboard into terminal input.
"""

from __future__ import annotations

import io
import json
import os
import sys
import threading
import time
import tkinter as tk
import traceback
from pathlib import Path

from PIL import Image, ImageTk

from .. import APP_NAME, __version__, term
from ..config import Config, config_dir, data_dir
from ..system import MACOS, WINDOWS
from . import keys as K
from .fonts import font_files
from .paint import Painter
from .vt import Screen

DEFAULT_PT = 12                         # the text size, in points (zoom: Ctrl+= / Ctrl+- / Ctrl+0)
MIN_PT, MAX_PT = 7, 36
# Textual's mouse pointer names (Kitty's pointer shapes) -> Tk cursors
POINTERS = {"default": "", "pointer": "hand2", "text": "xterm", "crosshair": "crosshair", "wait": "watch",
            "progress": "watch", "move": "fleur", "grab": "hand2", "grabbing": "fleur", "help": "question_arrow",
            "not-allowed": "X_cursor", "ew-resize": "sb_h_double_arrow", "ns-resize": "sb_v_double_arrow",
            "col-resize": "sb_h_double_arrow", "row-resize": "sb_v_double_arrow"}
if WINDOWS:
    POINTERS.update({"not-allowed": "no", "progress": "starting"})


def _hex(rgb) -> str:
    return "#%02x%02x%02x" % tuple(rgb)


def _rgb(color: str, fallback) -> tuple[int, int, int]:
    try:
        c = color.lstrip("#")
        return int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)
    except (ValueError, AttributeError):
        return fallback


def _theme_colors(cfg) -> tuple[tuple, tuple]:
    """The foreground and background of the colour scheme in use (the window's colours before the app draws)."""
    try:
        from ..themes import ALL_THEMES, theme_name
        name = theme_name(cfg["theme"], cfg["calendar"])
        t = next(t for t in ALL_THEMES if t.name == name)
        return _rgb(t.foreground, (229, 229, 229)), _rgb(t.background, (24, 18, 14))
    except Exception:
        return (229, 229, 229), (24, 18, 14)


class _Capture(io.TextIOBase):
    """Keeps what is written to stderr (an error report, if the app fails) and passes it on."""

    def __init__(self, passthrough) -> None:
        super().__init__()
        self.passthrough = passthrough
        self.buffer_ = io.StringIO()

    def writable(self) -> bool:
        return True

    def write(self, s: str) -> int:
        self.buffer_.write(s)
        if self.passthrough is not None:
            try:
                self.passthrough.write(s)
            except Exception:
                pass
        return len(s)

    def flush(self) -> None:
        if self.passthrough is not None:
            try:
                self.passthrough.flush()
            except Exception:
                pass


def prepare_process() -> None:
    """Before any window exists: sharp text on Windows' scaled displays, the taskbar's
    own icon for saintd, and somewhere for output to go when there is no console."""
    if WINDOWS:
        import ctypes
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            try:
                ctypes.windll.user32.SetProcessDPIAware()
            except Exception:
                pass
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("SaintDirectory.saintd")
        except Exception:
            pass
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w", encoding="utf-8")
    sys.stderr = _Capture(sys.stderr)


class Window:
    """The window, its grid of cells and the app's thread."""

    def __init__(self) -> None:
        self.cfg = Config()
        self.state_path = config_dir() / "window.json"
        try:
            self.state = json.loads(self.state_path.read_text(encoding="utf-8"))
            if not isinstance(self.state, dict):
                self.state = {}
        except (OSError, ValueError):
            self.state = {}
        self.root = tk.Tk(className="Saintd")
        self.root.withdraw()
        self.root.title(APP_NAME)
        self._set_icon()
        self.dpi = self.root.winfo_fpixels("1i") or 96.0
        try:
            self.pt = max(MIN_PT, min(MAX_PT, int(self.state.get("font_pt") or DEFAULT_PT)))
        except (TypeError, ValueError):
            self.pt = DEFAULT_PT
        self.files = font_files()
        self.fg, self.bg = _theme_colors(self.cfg)
        self.painter = Painter(self.files, self._px(self.pt), self.fg, self.bg)
        self.canvas = tk.Canvas(self.root, bg=_hex(self.bg), highlightthickness=0, borderwidth=0, takefocus=1,
                                cursor="")
        self.canvas.pack(fill="both", expand=True)
        self.screen = Screen(80, 24)
        self.info = term.use_window((self.painter.cw, self.painter.ch))
        self.driver = None
        self.app = None
        self.app_done = False
        self.crash = ""
        self.return_code = 0
        self._photos: list = []
        self._images: list = []
        self._size_px = (0, 0)
        self._row_w = 0
        self._margin_bg = None
        self._last_cell = None
        self._buttons: set[int] = set()
        self._wheel = 0.0
        self._activity = time.monotonic()
        self._quit_at = 0.0
        self._closed = False
        self._last_frame = 0.0
        self._snapshot = os.environ.get("SAINTD_SNAPSHOT", "")
        self._errors_seen: set[str] = set()
        self.root.report_callback_exception = self._log_error
        self._place_window()
        self._bind()

        class Driver(_driver_class()):
            window = self
        self.driver_class = Driver

    # ------------------------------------------------------------ setting up
    def _px(self, pt: int) -> int:
        return max(6, round(pt * self.dpi / 72))

    def _set_icon(self) -> None:
        try:
            eagle = Image.open(Path(__file__).resolve().parent.parent / "assets" / "eagle.png").convert("RGBA")
            side = max(eagle.size)
            square = Image.new("RGBA", (side, side), (0, 0, 0, 0))
            square.paste(eagle, ((side - eagle.width) // 2, (side - eagle.height) // 2))
            self._icons = [ImageTk.PhotoImage(square.resize((s, s), Image.LANCZOS)) for s in (256, 64, 48, 32, 16)]
            self.root.iconphoto(True, *self._icons)
        except Exception:
            pass

    def _place_window(self) -> None:
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        cw, ch = self.painter.cw, self.painter.ch
        forced = os.environ.get("SAINTD_WINDOW_SIZE", "")      # "140x40" cells (for screenshots and tests)
        w = h = 0
        if "x" in forced:
            try:
                cols, rows = (int(v) for v in forced.lower().split("x", 1))
                w, h = cols * cw, rows * ch
            except ValueError:
                pass
        if not w:
            try:
                w, h = int(self.state.get("width", 0)), int(self.state.get("height", 0))
            except (TypeError, ValueError):
                w = h = 0
        if w < 40 * cw or h < 12 * ch:
            w, h = int(sw * 0.86), int(sh * 0.84)
        if forced and w and h:
            self.root.maxsize(max(w, sw), max(h, sh))      # the size asked for, even past the screen
        else:
            w, h = min(w, sw), min(h, sh)
        try:
            x, y = int(self.state.get("x", -1)), int(self.state.get("y", -1))
        except (TypeError, ValueError):
            x = y = -1
        if forced or not (0 <= x <= sw - 100 and 0 <= y <= sh - 100):
            x, y = max(0, (sw - w) // 2), max(0, (sh - h) // 3)
        self.root.geometry(f"{w}x{h}+{x}+{y}")
        self.root.minsize(min(w, 40 * cw), min(h, 12 * ch))
        self._zoomed = bool(self.state.get("zoomed")) and not forced

    def _bind(self) -> None:
        c = self.canvas
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        c.bind("<Configure>", self._on_configure)
        c.bind("<KeyPress>", self._on_key)
        c.bind("<FocusIn>", lambda e: self._send(K.FOCUS_IN))
        c.bind("<FocusOut>", lambda e: self._send(K.FOCUS_OUT))
        for b in (1, 2, 3):
            c.bind(f"<ButtonPress-{b}>", self._on_press)
            c.bind(f"<ButtonRelease-{b}>", self._on_release)
        c.bind("<Motion>", self._on_motion)
        c.bind("<MouseWheel>", self._on_wheel)
        c.bind("<Shift-MouseWheel>", lambda e: self._on_wheel(e, horizontal=True))
        c.bind("<Button-4>", lambda e: self._wheel_steps(e, 1))
        c.bind("<Button-5>", lambda e: self._wheel_steps(e, -1))
        self.root.bind("<Map>", lambda e: c.focus_set())

    # ------------------------------------------------------------ the grid
    def grid_size(self) -> tuple[int, int]:
        return self.screen.cols, self.screen.rows

    def _layout(self, width: int, height: int) -> None:
        """Fit the grid to the window (after a resize or a change of text size)."""
        cw, ch = self.painter.cw, self.painter.ch
        cols, rows = max(20, width // cw), max(6, height // ch)
        changed = (cols, rows) != (self.screen.cols, self.screen.rows)
        self.screen.resize(cols, rows)
        self._row_w = max(width, cols * cw)
        images = [Image.new("RGB", (self._row_w, ch), self.bg) for _ in range(rows)]
        photos = [ImageTk.PhotoImage(im) for im in images]
        self._images, self._photos = images, photos
        self.canvas.delete("row")
        for y, photo in enumerate(photos):
            self.canvas.create_image(0, y * ch, anchor="nw", image=photo, tags="row")
        with self.screen.lock:
            self.screen.dirty = set(range(self.screen.rows))
        if changed and self.driver is not None:
            self.driver.resized(cols, rows, cols * cw, rows * ch)

    def _on_configure(self, event) -> None:
        if (event.width, event.height) != self._size_px and event.width > 1 and event.height > 1:
            self._size_px = (event.width, event.height)
            self._layout(event.width, event.height)

    def _zoom(self, step: int) -> None:
        pt = DEFAULT_PT if step == 0 else max(MIN_PT, min(MAX_PT, self.pt + step))
        if pt == self.pt and step:
            return
        self.pt = pt
        self.painter = Painter(self.files, self._px(pt), self.fg, self.bg)
        self.info.cell_px = (self.painter.cw, self.painter.ch)
        if self._size_px[0] > 1:
            self._layout(*self._size_px)

    # ------------------------------------------------------------ drawing
    def wake(self) -> None:
        """New output from the app (any thread)."""
        self._activity = time.monotonic()

    def _paint(self) -> bool:
        scr = self.screen
        with scr.lock:
            if scr.synchronized and time.monotonic() - scr.sync_since < 0.25:
                return False                        # in the middle of an update: wait for the rest
            rows, events = scr.take()
        for event in events:
            self._event(event)
        if not rows:
            return False
        p, images = self.painter, scr.images
        cw = p.cw
        for y, texts, styles in rows:
            if y >= len(self._images) or y >= len(self._photos):
                continue
            im = self._images[y]
            p.paint_row(im, texts, styles, images, right_pad=self._row_w - len(texts) * cw)
            self._photos[y].paste(im)
            if y == len(self._images) - 1 and styles:
                bg = p.colors(styles[0])[1]
                if bg != self._margin_bg:
                    self._margin_bg = bg
                    self.canvas.configure(bg=_hex(bg))
        self._last_frame = time.monotonic()
        return True

    def _event(self, event: tuple) -> None:
        kind = event[0]
        try:
            if kind == "bell":
                self.root.bell()
            elif kind == "title":
                self.root.title(event[1] or APP_NAME)
            elif kind == "pointer":
                self.canvas.configure(cursor=POINTERS.get(event[1], ""))
            elif kind == "clipboard":
                self.root.clipboard_clear()
                self.root.clipboard_append(event[1])
        except tk.TclError:
            pass

    def snapshot(self) -> Image.Image:
        """The window's picture as it is now (for screenshots and checks)."""
        ch = self.painter.ch
        out = Image.new("RGB", (self._row_w or 1, max(1, len(self._images) * ch)), self.bg)
        for y, im in enumerate(self._images):
            out.paste(im, (0, y * ch))
        return out

    def _tick(self) -> None:
        if self._closed:
            return
        try:
            painted = self._paint()
            if self.app_done:
                self._finish()
                return
            if self._quit_at and time.monotonic() - self._quit_at > 6:
                self._finish()                      # the app did not stop: close anyway
                return
            if self._snapshot and self.driver is not None and not painted and self._last_frame and \
                    time.monotonic() - self._last_frame > 2.5 and time.monotonic() - self._started > 4:
                self.snapshot().save(self._snapshot)
                self._snapshot = ""
                self.close()
        except Exception:
            self._log_error(*sys.exc_info())
        busy = time.monotonic() - self._activity < 1.0
        self.root.after(8 if busy else 30, self._tick)

    # ------------------------------------------------------------ input
    def attach(self, driver) -> None:
        """The app is ready for input (called from its thread)."""
        self.driver = driver

    def detach(self, driver) -> None:
        if self.driver is driver:
            self.driver = None

    def _send(self, data: str | None) -> None:
        d = self.driver
        if data and d is not None:
            d.feed(data)
            self._activity = time.monotonic()

    def _on_key(self, e):
        shift, ctrl, alt, _sup = K.modifiers(e.state, e.char)
        ks, num = e.keysym, e.keysym_num
        if ctrl and not alt:                        # the window's own keys: text size and paste
            if num in K.ZOOM_IN:
                self._zoom(+1)
                return "break"
            if num in K.ZOOM_OUT:
                self._zoom(-1)
                return "break"
            if num in K.ZOOM_RESET and not shift:
                self._zoom(0)
                return "break"
            if num in (0x56, 0x76):                 # V
                self._paste()
                return "break"
        if ks == "Insert" and shift and not ctrl:
            self._paste()
            return "break"
        if ks == "F11" and not (shift or ctrl or alt):
            self._fullscreen()
            return "break"
        self._send(K.encode_key(ks, e.keysym_num, e.char, e.state))
        return "break"

    def _paste(self) -> None:
        try:
            text = self.root.clipboard_get()
        except tk.TclError:
            return
        if text:
            self._send(K.paste(text))

    def _fullscreen(self) -> None:
        try:
            on = bool(self.root.attributes("-fullscreen"))
            self.root.attributes("-fullscreen", not on)
        except tk.TclError:
            pass

    def _cell(self, e) -> tuple[int, int]:
        cw, ch = self.painter.cw, self.painter.ch
        return (max(0, min(self.screen.cols - 1, e.x // cw)), max(0, min(self.screen.rows - 1, e.y // ch)))

    def _button(self, e) -> int:
        b = e.num
        if MACOS and self.root.tk.call("tk", "windowingsystem") == "aqua" and tk.TkVersion < 8.7:
            b = {2: 3, 3: 2}.get(b, b)             # Tk 8.6 on macOS numbers the right button 2
        return b

    def _on_press(self, e) -> None:
        self.canvas.focus_set()
        b = self._button(e)
        self._buttons.add(b)
        col, row = self._cell(e)
        self._last_cell = (col, row)
        self._send(K.mouse("press", b, col, row, e.state))

    def _on_release(self, e) -> None:
        b = self._button(e)
        self._buttons.discard(b)
        col, row = self._cell(e)
        self._send(K.mouse("release", b, col, row, e.state))

    def _on_motion(self, e) -> None:
        cell = self._cell(e)
        if cell == self._last_cell:
            return
        self._last_cell = cell
        held = min(self._buttons) if self._buttons else 0
        self._send(K.mouse("move", held, cell[0], cell[1], e.state))

    def _on_wheel(self, e, horizontal: bool = False) -> None:
        if e.state & K.CTRL:                        # Ctrl and the wheel: text size
            self._zoom(+1 if e.delta > 0 else -1)
            return
        if WINDOWS or abs(e.delta) >= 120:
            self._wheel += e.delta / 120.0
        else:
            self._wheel += e.delta                  # macOS: small steps, one per line
        steps = int(self._wheel)
        self._wheel -= steps
        if steps:
            self._wheel_steps(e, steps, horizontal)

    def _wheel_steps(self, e, steps: int, horizontal: bool = False) -> None:
        col, row = self._cell(e)
        button = (6 if steps > 0 else 7) if horizontal else (4 if steps > 0 else 5)
        for _ in range(min(abs(steps), 10)):
            self._send(K.mouse("wheel", button, col, row, e.state & ~K.SHIFT if horizontal else e.state))

    # ------------------------------------------------------------ the app
    def _run_app(self) -> None:
        try:
            import textual.constants
            textual.constants.COLOR_SYSTEM = "truecolor"    # no console to ask: the window shows 24-bit colour
            from .. import graphics
            from ..app import SaintDirectoryApp
            from ..core import Context
            mode = graphics.prepare(term.effective_mode(self.cfg["graphics"], self.info))
            app = SaintDirectoryApp(Context(self.cfg), graphics_mode=mode)
            app.driver_class = self.driver_class
            self.app = app
            app.run()
            self.return_code = app.return_code or 0
        except BaseException:
            self.crash = traceback.format_exc()
            self.return_code = 1
        finally:
            self.app_done = True
            self._activity = time.monotonic()

    def run(self) -> int:
        self.root.update_idletasks()
        self.root.deiconify()
        if self._zoomed:
            self._maximize()
        self.root.update()
        w, h = self.canvas.winfo_width(), self.canvas.winfo_height()
        if (w, h) != self._size_px and w > 1:
            self._size_px = (w, h)
            self._layout(w, h)
        self.canvas.focus_set()
        self._started = time.monotonic()
        self._thread = threading.Thread(target=self._run_app, name="saintd-app", daemon=True)
        self._thread.start()
        self.root.after(10, self._tick)
        try:
            self.root.mainloop()
        finally:
            self._closed = True
        self._thread.join(timeout=5)
        return self.return_code

    def _maximize(self) -> None:
        try:
            if WINDOWS or MACOS:
                self.root.state("zoomed")
            else:
                self.root.attributes("-zoomed", True)
        except tk.TclError:
            pass

    def _is_maximized(self) -> bool:
        try:
            if WINDOWS or MACOS:
                return self.root.state() == "zoomed"
            return bool(self.root.attributes("-zoomed"))
        except tk.TclError:
            return False

    def close(self) -> None:
        """The window's close button: quit the app the way Ctrl+Q does."""
        if self.app_done or self.driver is None:
            if self.app is None or self.app_done:
                self._finish()
                return
        if not self._quit_at:
            self._quit_at = time.monotonic()
            self._send("\x1b[113;5u")               # Ctrl+Q

    def _finish(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._save_state()
        if self.crash or (self.return_code and isinstance(sys.stderr, _Capture)):
            self._report_crash()
        try:
            self.root.destroy()
        except tk.TclError:
            pass

    def _save_state(self) -> None:
        try:
            zoomed = self._is_maximized()
            full = bool(self.root.attributes("-fullscreen"))
            state = dict(self.state)
            state["font_pt"] = self.pt
            state["zoomed"] = zoomed
            if not (zoomed or full or os.environ.get("SAINTD_WINDOW_SIZE")):
                state.update(width=self.root.winfo_width(), height=self.root.winfo_height(),
                             x=self.root.winfo_x(), y=self.root.winfo_y())
            self.state_path.write_text(json.dumps(state, indent=2), encoding="utf-8")
        except Exception:
            pass

    def _log_error(self, *exc) -> None:
        """An error in the window's own code: noted in window-error.log, and the window goes
        on (while the app runs, Textual holds stderr, so nothing printed would be seen)."""
        text = "".join(traceback.format_exception(*exc))
        if text in self._errors_seen or len(self._errors_seen) > 50:
            return
        self._errors_seen.add(text)
        try:
            path = data_dir() / "window-error.log"
            if path.is_file() and path.stat().st_size > 256 << 10:
                path.unlink()
            with path.open("a", encoding="utf-8") as f:
                f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} saintd {__version__}\n{text}\n")
        except OSError:
            pass

    def _report_crash(self) -> None:
        """The app stopped with an error: keep the details and say where they are."""
        details = self.crash or ""
        if isinstance(sys.stderr, _Capture):
            details = sys.stderr.buffer_.getvalue() + details
        if not details.strip():
            return
        path = data_dir() / "window-error.log"
        try:
            path.write_text(details, encoding="utf-8")
        except OSError:
            path = None
        try:
            from tkinter import messagebox
            messagebox.showerror(APP_NAME, "Saint Directory stopped because of an error."
                                 + (f"\n\nThe details are in:\n{path}" if path else ""), parent=self.root)
        except Exception:
            pass


def _driver_class():
    from .driver import WindowDriver
    return WindowDriver


def run() -> int:
    prepare_process()
    try:
        window = Window()
    except tk.TclError as err:              # no display (a remote session without one, say)
        print(f"saintd: cannot open a window here ({err}).", file=sys.__stderr__ or sys.stderr)
        return 1
    return window.run()
