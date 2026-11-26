"""Icons of the saints: where to find them and a small file cache.

In order of preference:

1. the saint's Wikidata image (P18) on Wikimedia Commons, as a standard-size
   thumbnail (no API call needed: thumbnail URLs follow from the file name);
2. the first icon on the saint's Azbuka Very page;
3. the first picture in the saint's Mystagogy Resource Center post.

Icons are downloaded only when a saint is opened (or shown as Saint of the Day)
and kept under ~/.cache/saintd/icons.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from urllib.parse import quote

from .config import cache_dir
from .net import Http, NetError

THUMB_WIDTH = 330          # a standard Wikimedia thumbnail width (served from their cache)
_IMAGE_EXT = re.compile(r"\.(jpe?g|png|gif|webp|svg|tiff?)$", re.I)


def icon_dir() -> Path:
    d = cache_dir() / "icons"
    d.mkdir(parents=True, exist_ok=True)
    return d


def commons_thumb_url(filename: str, width: int = THUMB_WIDTH) -> str | None:
    """Thumbnail URL of a Commons file, e.g. 'Seraphim of Sarov.jpg'."""
    name = (filename or "").strip().replace(" ", "_")
    if name.lower().startswith("file:"):
        name = name[5:]
    if not name or not _IMAGE_EXT.search(name):
        return None
    h = hashlib.md5(name.encode("utf-8")).hexdigest()
    q = quote(name, safe="()_,-.!~*'")
    thumb = f"{width}px-{q}"
    low = name.lower()
    if low.endswith(".svg"):
        thumb += ".png"
    elif low.endswith((".tif", ".tiff")):
        thumb = f"lossy-page1-{width}px-{q}.jpg"
    return f"https://upload.wikimedia.org/wikipedia/commons/thumb/{h[0]}/{h[:2]}/{q}/{thumb}"


_AZ_ICON = re.compile(r"https://azbyka\.ru/days/(?:cache/\d+x\d+/)?storage/images/icons-of-saints/[\w/.-]+?\.(?:jpe?g|png|webp)",
                      re.I)


def azbyka_icon_url(page: str) -> str | None:
    """The saint's first icon on an Azbuka Very page, at the 400x320 size."""
    m = _AZ_ICON.search(page or "")
    if not m:
        return None
    url = m.group(0)
    path = re.sub(r"^https://azbyka\.ru/days/(?:cache/\d+x\d+/)?", "", url)
    return f"https://azbyka.ru/days/cache/400x320/{path}"


_BLOGGER_IMG = re.compile(r'<img[^>]+src="(https://blogger\.googleusercontent\.com/img/[^"]+)"', re.I)


def mystagogy_icon_url(post_page: str) -> str | None:
    """The first picture in a Blogger post body (usually the saint's icon)."""
    i = post_page.find("post-body entry-content") if post_page else -1
    m = _BLOGGER_IMG.search(post_page[i:] if i >= 0 else post_page or "")
    if not m:
        return None
    url = m.group(1)
    # Blogger serves any size by changing the /sNNN/ path segment
    return re.sub(r"/s\d+(-[a-z0-9-]+)?/", "/s400/", url, count=1)


def cached_path(url: str) -> Path:
    ext = ".png" if url.lower().endswith(".png") else ".jpg"
    return icon_dir() / (hashlib.sha1(url.encode("utf-8")).hexdigest()[:20] + ext)


def cached(url: str | None) -> Path | None:
    if not url:
        return None
    p = cached_path(url)
    return p if p.exists() and p.stat().st_size > 0 else None


def fetch(http: Http, url: str) -> Path | None:
    """Download an icon once; returns the local file (None if it failed)."""
    hit = cached(url)
    if hit:
        return hit
    try:
        data = http.get_bytes(url, timeout=30)
    except NetError:
        return None
    if len(data) < 200 or not (data[:3] == b"\xff\xd8\xff" or data[:8] == b"\x89PNG\r\n\x1a\n"
                               or data[:4] in (b"GIF8", b"RIFF")):
        return None                       # an error page, not a picture
    p = cached_path(url)
    tmp = p.with_suffix(p.suffix + ".part")
    tmp.write_bytes(data)
    tmp.replace(p)
    return p


def cache_size() -> tuple[int, int]:
    """(number of files, bytes) in the icon cache."""
    n = size = 0
    for f in icon_dir().glob("*"):
        if f.is_file():
            n += 1
            size += f.stat().st_size
    return n, size


def clear_cache() -> None:
    for f in icon_dir().glob("*"):
        try:
            f.unlink()
        except OSError:
            pass
