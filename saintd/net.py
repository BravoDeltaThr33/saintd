"""Polite HTTP client: per-host rate limits, retries with Retry-After,
optional response caching in SQLite."""

from __future__ import annotations

import json
import threading
import time
from typing import Any, Callable
from urllib.parse import urlencode, urlsplit

import httpx

from . import __version__


class NetError(Exception):
    """A request failed after retries (message is user-presentable)."""


class Cancelled(Exception):
    """The operation was cancelled by the user."""


# minimum seconds between requests, per host
DEFAULT_INTERVALS = {
    "orthocal.info": 0.34,
    "azbyka.ru": 1.0,
    "www.johnsanidopoulos.com": 0.5,
    "www.holytrinityorthodox.com": 2.0,     # a parish server: go gently
    "orthodoxwiki.org": 1.0,
    "upload.wikimedia.org": 0.5,
    "www.wikidata.org": 1.0,
    "api.mymemory.translated.net": 1.0,
}


class Http:
    # Shared across instances so the background sync and the foreground UI
    # together never exceed a host's polite request rate.
    _state_lock = threading.Lock()
    _next_slot: dict[str, float] = {}
    _cooldown: dict[str, float] = {}
    _backoff: dict[str, float] = {}     # adaptive slow-down after "too many requests"
    _streak: dict[str, int] = {}
    _fg_waiting: dict[str, int] = {}    # foreground requests queued per host

    def __init__(self, timeout: float = 25, contact: str = "", wiki_rps: float | None = None,
                 cache: "Any | None" = None, foreground: bool = False) -> None:
        self.foreground = foreground    # foreground (what the user is reading) goes first
        self.client = httpx.Client(
            timeout=httpx.Timeout(timeout, connect=min(10.0, timeout)),
            headers={"Accept": "application/json"},
            follow_redirects=True,
        )
        self.timeout = timeout
        self.intervals = dict(DEFAULT_INTERVALS)
        self.contact = ""
        self.set_identity(contact)
        self.cache = cache          # object with cache_get(url, ttl) / cache_put(url, body)
        self.stop = threading.Event()
        self.on_wait: Callable[[str, float], None] | None = None   # (host, seconds) notifications
        self.requests = 0

    # ------------------------------------------------------------ config
    def set_identity(self, contact: str) -> None:
        """Set the User-Agent. Wikimedia allows ~200 requests/min to clients whose
        User-Agent carries contact details (an e-mail or URL) and only 10/min to
        anonymous ones, so the request rate follows from this."""
        contact = (contact or "").strip()
        self.contact = contact
        lib = f"python-httpx/{httpx.__version__}"
        if contact:
            ua = f"saintd/{__version__} ({contact}; Saint Directory terminal app) {lib}"
        else:
            ua = f"saintd/{__version__} (Saint Directory terminal app; no contact set) {lib}"
        self.client.headers["User-Agent"] = ua
        self.set_wiki_rps(self.wiki_rate())

    def wiki_rate(self) -> float:
        """Requests per second we allow ourselves against Wikimedia."""
        return 2.5 if self.contact else 0.15

    def set_wiki_rps(self, rps: float) -> None:
        rps = max(0.1, min(float(rps or 1.0), 10.0))
        for h in ("www.wikidata.org", "en.wikipedia.org", "ru.wikipedia.org", "el.wikipedia.org",
                  "sr.wikipedia.org", "uk.wikipedia.org", "bg.wikipedia.org", "ro.wikipedia.org",
                  "ka.wikipedia.org"):
            self.intervals[h] = 1.0 / rps

    def close(self) -> None:
        try:
            self.client.close()
        except Exception:
            pass

    # ------------------------------------------------------------ helpers
    def _interval(self, host: str) -> float:
        if host.endswith(".wikipedia.org"):
            base = self.intervals.get(host, self.intervals["www.wikidata.org"])
        else:
            base = self.intervals.get(host, 0.5)
        return base * Http._backoff.get(host, 1.0)

    def _good(self, host: str) -> None:
        with Http._state_lock:
            n = Http._streak.get(host, 0) + 1
            if n >= 30 and Http._backoff.get(host, 1.0) > 1.0:
                Http._backoff[host] = max(1.0, Http._backoff[host] * 0.75)
                n = 0
            Http._streak[host] = n

    def _bad(self, host: str) -> None:
        with Http._state_lock:
            Http._backoff[host] = min(Http._backoff.get(host, 1.0) * 2.0, 16.0)
            Http._streak[host] = 0

    def _sleep(self, seconds: float) -> None:
        end = time.monotonic() + seconds
        while True:
            if self.stop.is_set():
                raise Cancelled()
            left = end - time.monotonic()
            if left <= 0:
                return
            time.sleep(min(left, 0.25))

    def _throttle(self, host: str) -> None:
        gap = self._interval(host)
        if not self.foreground:
            while Http._fg_waiting.get(host, 0) > 0:     # let the reader's request go first
                self._sleep(0.2)
        with Http._state_lock:
            now = time.monotonic()
            slot = max(now, Http._next_slot.get(host, 0.0), Http._cooldown.get(host, 0.0))
            Http._next_slot[host] = slot + gap
        if slot > now:
            self._sleep(slot - now)

    def _cool(self, host: str, seconds: float) -> None:
        with Http._state_lock:
            Http._cooldown[host] = max(Http._cooldown.get(host, 0.0), time.monotonic() + seconds)

    # ------------------------------------------------------------ core
    def request(self, method: str, url: str, *, params: dict | None = None, json_body: Any = None,
                timeout: float | None = None, retries: int = 4, headers: dict | None = None) -> httpx.Response:
        host = urlsplit(url).hostname or ""
        if self.foreground:
            with Http._state_lock:
                Http._fg_waiting[host] = Http._fg_waiting.get(host, 0) + 1
        try:
            return self._request(method, url, host, params, json_body, timeout, retries, headers)
        finally:
            if self.foreground:
                with Http._state_lock:
                    Http._fg_waiting[host] = max(0, Http._fg_waiting.get(host, 1) - 1)

    def _request(self, method, url, host, params, json_body, timeout, retries, headers) -> httpx.Response:
        attempt = 0
        while True:
            if self.stop.is_set():
                raise Cancelled()
            self._throttle(host)
            try:
                self.requests += 1
                r = self.client.request(method, url, params=params, json=json_body,
                                        timeout=timeout or self.timeout, headers=headers)
            except httpx.TimeoutException:
                err = f"{host} timed out"
                r = None
            except httpx.HTTPError as e:
                err = f"{host}: {e.__class__.__name__}"
                r = None
            if r is not None:
                if r.status_code in (429, 503, 502, 504):
                    ra = r.headers.get("Retry-After", "")
                    try:
                        delay = float(ra)
                    except ValueError:
                        delay = 5.0 * (2 ** attempt)
                    err = f"{host} is busy (HTTP {r.status_code})"
                    if attempt >= retries:
                        raise NetError(err)
                    delay = min(max(delay, 1.0), 120.0)
                    self._cool(host, delay)
                    if r.status_code == 429:
                        self._bad(host)
                    if self.on_wait:
                        self.on_wait(host, delay)
                    attempt += 1
                    continue
                if r.status_code >= 400:
                    raise NetError(f"{host} returned HTTP {r.status_code}")
                self._good(host)
                return r
            if attempt >= min(retries, 2):
                raise NetError(err)
            self._sleep(2.0 * (2 ** attempt))
            attempt += 1

    def get_json(self, url: str, params: dict | None = None, *, ttl: float | None = None,
                 timeout: float | None = None, retries: int = 4) -> Any:
        key = url + ("?" + urlencode(sorted(params.items())) if params else "")
        if ttl and self.cache is not None:
            hit = self.cache.cache_get(key, ttl)
            if hit is not None:
                try:
                    return json.loads(hit)
                except ValueError:
                    pass
        r = self.request("GET", url, params=params, timeout=timeout, retries=retries)
        try:
            data = r.json()
        except ValueError as e:
            raise NetError(f"{urlsplit(url).hostname} sent an unreadable response") from e
        if ttl and self.cache is not None:
            self.cache.cache_put(key, r.text)
        return data

    def get_text(self, url: str, params: dict | None = None, *, ttl: float | None = None,
                 timeout: float | None = None, retries: int = 3, encoding: str | None = None) -> str:
        """A web page (HTML), optionally cached like get_json. `encoding` forces
        the character set for old pages that don't declare it in the headers."""
        key = url + ("?" + urlencode(sorted(params.items())) if params else "")
        if ttl and self.cache is not None:
            hit = self.cache.cache_get(key, ttl)
            if hit is not None:
                return hit
        r = self.request("GET", url, params=params, timeout=timeout, retries=retries,
                         headers={"Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.5"})
        text = r.content.decode(encoding, "replace") if encoding else r.text
        if ttl and self.cache is not None:
            self.cache.cache_put(key, text)
        return text

    def get_bytes(self, url: str, *, timeout: float | None = None, retries: int = 2,
                  max_bytes: int = 4_000_000) -> bytes:
        """A binary file such as an icon (not cached here: callers keep files)."""
        r = self.request("GET", url, timeout=timeout, retries=retries,
                         headers={"Accept": "image/avif,image/webp,image/png,image/jpeg,image/*;q=0.8,*/*;q=0.5"})
        data = r.content
        if len(data) > max_bytes:
            raise NetError(f"{urlsplit(url).hostname} sent a file that is too large")
        return data

    def post_json(self, url: str, body: Any, *, timeout: float | None = None, retries: int = 2) -> Any:
        r = self.request("POST", url, json_body=body, timeout=timeout, retries=retries)
        try:
            return r.json()
        except ValueError as e:
            raise NetError(f"{urlsplit(url).hostname} sent an unreadable response") from e
