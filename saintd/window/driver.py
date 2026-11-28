"""The Textual driver of saintd's window: the app's output goes to the window's
terminal grid, and the window's keys and mouse come back as the bytes Kitty
sends, read by Textual's own parser (as in a terminal)."""

from __future__ import annotations

import asyncio
import threading

from textual import events, messages
from textual._xterm_parser import XTermParser
from textual.driver import Driver
from textual.geometry import Size


class WindowDriver(Driver):
    """Set `window` on a subclass (see tkwin.Window.driver_class)."""

    window = None

    def __init__(self, app, *, debug: bool = False, mouse: bool = True, size: tuple[int, int] | None = None) -> None:
        super().__init__(app, debug=debug, mouse=mouse, size=size or self.window.grid_size())
        self._parser = XTermParser(debug)
        self._input = threading.Lock()
        self._accepting = False

    # ------------------------------------------------------------ output
    def write(self, data: str) -> None:
        self.window.screen.feed(data)

    def flush(self) -> None:
        self.window.wake()

    # ------------------------------------------------------------ input (from the window's thread)
    def feed(self, data: str) -> None:
        """Keys, mouse and paste from the window, as terminal input."""
        with self._input:
            if not self._accepting:
                return
            for event in self._parser.feed(data):
                self.process_message(event)

    def resized(self, cols: int, rows: int, width_px: int, height_px: int) -> None:
        size = Size(cols, rows)
        self._size = (cols, rows)
        event = events.Resize(size, size, pixel_size=Size(width_px, height_px))
        self._post(event)

    def _post(self, message) -> None:
        coro = self._app._post_message(message)
        try:
            asyncio.run_coroutine_threadsafe(coro, loop=self._loop)
        except RuntimeError:                        # the app has finished
            coro.close()

    # ------------------------------------------------------------ application mode
    def start_application_mode(self) -> None:
        cols, rows = self.window.grid_size()
        self._size = (cols, rows)
        self._post(messages.TerminalSupportsSynchronizedOutput())
        self._post(events.Resize(Size(cols, rows), Size(cols, rows)))
        with self._input:
            self._accepting = True
        self.window.attach(self)

    def disable_input(self) -> None:
        with self._input:
            self._accepting = False

    def stop_application_mode(self) -> None:
        self.disable_input()
        self.window.detach(self)
