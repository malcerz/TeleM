"""Moving Map Renderer – GPS-track-following OSM map overlay for TeleMGP.

Generates a sequence of map images that follow the current GPS position
frame-by-frame, drawing the traversed route and a position marker.

Features:
- SQLite disk cache + in-memory LRU for tiles
- Rate-limited fetching with User-Agent (Tile Usage Policy compliant)
- Track projection pre-computed once, reused for all frames
- Offline pre-cache mode: download all tiles before rendering
- Minimal deps: PIL/Pillow + stdlib
"""

from __future__ import annotations

import io
import math
import sqlite3
import threading
import time
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Optional

try:
    from PIL import Image, ImageDraw
except ImportError:
    Image = None

# ── Constants ───────────────────────────────────────────────────────────

TILE_SIZE = 256
USER_AGENT = "TeleMHUD/1.0 (moving-map)"
REQUEST_DELAY = 0.15          # fair-use delay between tile requests
DEFAULT_ZOOM = 15
DEFAULT_STYLE = "light_all"

MAP_STYLES: dict[str, str] = {
    "light_all":       "https://a.basemaps.cartocdn.com/light_all/{z}/{x}/{y}.png",
    "light_nolabels":  "https://a.basemaps.cartocdn.com/light_nolabels/{z}/{x}/{y}.png",
    "dark_all":        "https://a.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png",
    "dark_nolabels":   "https://a.basemaps.cartocdn.com/dark_nolabels/{z}/{x}/{y}.png",
    "voyager_all":     "https://a.basemaps.cartocdn.com/voyager_all/{z}/{x}/{y}.png",
    "voyager_nolabels":"https://a.basemaps.cartocdn.com/voyager_nolabels/{z}/{x}/{y}.png",
    "osm":             "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
}


# ── Coordinates ─────────────────────────────────────────────────────────

def _lat_lon_to_tile(lat: float, lon: float, zoom: int):
    """(tile_x, tile_y, px_offset_x, px_offset_y) at zoom level."""
    n = 2 ** zoom
    x_tile = (lon + 180.0) / 360.0 * n
    lat_rad = math.radians(lat)
    y_tile = (1.0 - math.log(math.tan(lat_rad) + 1.0 / math.cos(lat_rad))
              / math.pi) / 2.0 * n
    tx, ty = int(x_tile), int(y_tile)
    px = int((x_tile - tx) * TILE_SIZE)
    py = int((y_tile - ty) * TILE_SIZE)
    return tx, ty, px, py


# ── TileCache (SQLite + in-memory LRU) ──────────────────────────────────

class TileCache:
    """Two-level cache: SQLite on disk + bounded in-memory LRU."""

    _mem: dict = {}
    _mem_order: list = []
    _max_mem = 256               # max tiles kept in RAM
    _lock = threading.Lock()

    def __init__(self, cache_dir: Path | None = None):
        d = cache_dir or Path.home() / ".telem_map_tiles"
        d.mkdir(parents=True, exist_ok=True)
        self._db = d / "tilecache.sqlite"
        with sqlite3.connect(str(self._db)) as c:
            c.execute("CREATE TABLE IF NOT EXISTS tiles(z INT,x INT,y INT,"
                      "style TEXT,data BLOB,PRIMARY KEY(z,x,y,style))")
            c.commit()

    def get(self, z, x, y, style) -> Image.Image | None:
        key = (z, x, y, style)
        with self._lock:
            if key in self._mem:
                self._mem_order.remove(key); self._mem_order.append(key)
                return self._mem[key].copy()
        try:
            with sqlite3.connect(str(self._db)) as c:
                r = c.execute("SELECT data FROM tiles WHERE z=? AND x=? "
                              "AND y=? AND style=?", key).fetchone()
            if r:
                img = Image.open(io.BytesIO(r[0])).convert("RGBA")
                self._put_mem(key, img)
                return img.copy()
        except Exception: pass
        return None

    def put(self, z, x, y, style, data: bytes):
        key = (z, x, y, style)
        try:
            img = Image.open(io.BytesIO(data)).convert("RGBA")
            self._put_mem(key, img)
        except Exception: return
        try:
            with sqlite3.connect(str(self._db)) as c:
                c.execute("INSERT OR REPLACE INTO tiles VALUES(?,?,?,?,?)",
                          (z, x, y, style, data)); c.commit()
        except Exception: pass

    def _put_mem(self, key, img):
        with self._lock:
            self._mem[key] = img; self._mem_order.append(key)
            while len(self._mem_order) > self._max_mem:
                old = self._mem_order.pop(0)
                if old in self._mem: del self._mem[old]


# ── Tile download ───────────────────────────────────────────────────────

_last_fetch = 0.0
_fetch_lock = threading.Lock()

def _download_tile_raw(z, x, y, style) -> bytes | None:
    global _last_fetch
    url = MAP_STYLES.get(style, MAP_STYLES[DEFAULT_STYLE]).format(z=z, x=x, y=y)
    with _fetch_lock:
        e = time.time() - _last_fetch
        if e < REQUEST_DELAY: time.sleep(REQUEST_DELAY - e)
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=2) as r:
                data = r.read()
        except Exception: return None
        finally: _last_fetch = time.time()
    return data


# ── MovingMapRenderer ───────────────────────────────────────────────────

class MovingMapRenderer:
    """Renders map frames following GPS track frame-by-frame."""

    def __init__(
        self,
        gps_track: list[tuple[datetime, float, float]],
        zoom: int = DEFAULT_ZOOM,
        style: str = DEFAULT_STYLE,
        cache_dir: Path | None = None,
        track_color=(255, 60, 30, 220),
        track_width=3,
        marker_color=(255, 255, 255, 255),
        marker_radius=7,
    ):
        if Image is None: raise ImportError("Pillow required")
        self._gps = gps_track
        self._zoom = zoom
        self._style = style
        self._trk_color = track_color
        self._trk_width = track_width
        self._mkr_color = marker_color
        self._mkr_radius = marker_radius
        self._cache = TileCache(cache_dir)

        # Pre-compute tile coords & pixel positions for all GPS points
        self._px_x: list[float] = []
        self._px_y: list[float] = []
        self._tiles: list[tuple[int, int]] = []
        for _, lat, lon in gps_track:
            tx, ty, px, py = _lat_lon_to_tile(lat, lon, zoom)
            self._tiles.append((tx, ty))
            self._px_x.append(tx * TILE_SIZE + px)
            self._px_y.append(ty * TILE_SIZE + py)
        if gps_track:
            self._ts0 = gps_track[0][0].timestamp()
            self._tsN = gps_track[-1][0].timestamp()
        else:
            self._ts0, self._tsN = 0.0, 1.0
        self._dur = self._tsN - self._ts0

    # ── Offline pre-cache ───────────────────────────────────────────

    def precache_tiles(self, margin=2) -> int:
        """Download ALL tiles needed for the entire track. Returns count."""
        needed: set[tuple] = set()
        for tx, ty in self._tiles:
            for dx in range(-margin, margin + 1):
                for dy in range(-margin, margin + 1):
                    needed.add((self._zoom, tx + dx, ty + dy))
        cnt = 0
        for z, x, y in needed:
            if self._cache.get(z, x, y, self._style): continue
            d = _download_tile_raw(z, x, y, self._style)
            if d: self._cache.put(z, x, y, self._style, d); cnt += 1
        return cnt

    def background_precache(self, margin=2, done_callback=None) -> threading.Thread:
        """Uruchamia w tle pobieranie wszystkich kafelków dla całej trasy.

        Args:
            margin: Liczba dodatkowych kafelków wokół każdego punktu GPS.
            done_callback: Opcjonalna funkcja wołana po zakończeniu cache'owania.
        Returns:
            Wątek wykonujący precache (daemon, można go ignorować).
        """
        def _run():
            self.precache_tiles(margin=margin)
            if done_callback:
                try:
                    done_callback()
                except Exception:
                    pass
        t = threading.Thread(target=_run, daemon=True)
        t.start()
        return t

    def missing_tiles(self) -> int:
        """Return # of tiles not yet cached."""
        needed: set[tuple] = set()
        for tx, ty in self._tiles:
            for dx in range(-2, 3):
                for dy in range(-2, 3):
                    needed.add((self._zoom, tx + dx, ty + dy))
        return sum(1 for z, x, y in needed
                   if not self._cache.get(z, x, y, self._style))

    # ── Render one frame ────────────────────────────────────────────

    def render(self, ts: float, w: int, h: int, *, draw_track=True,
               draw_marker=True,
               download_missing=True) -> Image.Image:
        """Map image centred on GPS position at timestamp *ts* (seconds).

        Args:
            ts: Timestamp in seconds (relative to track start).
            w, h: Output image size in pixels.
            draw_track, draw_marker: Whether to draw track line/position marker.
            download_missing: If True, download missing tiles on demand (may block).
                If False, only cached tiles are used – uncached areas stay grey.
        """
        idx = self._idx(ts)
        cx, cy = self._tiles[idx]
        cpx, cpy = self._px_x[idx], self._px_y[idx]

        # Tile range covering output size
        half_w = int(math.ceil(w / 2 / TILE_SIZE)) + 1
        half_h = int(math.ceil(h / 2 / TILE_SIZE)) + 1
        tx1, tx2 = cx - half_w, cx + half_w + 1
        ty1, ty2 = cy - half_h, cy + half_h + 1

        tw = (tx2 - tx1) * TILE_SIZE
        th = (ty2 - ty1) * TILE_SIZE
        img = Image.new("RGBA", (tw, th), (30, 30, 30, 255))

        # Fetch & paste tiles
        for ty in range(ty1, ty2):
            for tx in range(tx1, tx2):
                tile = self._cache.get(self._zoom, tx, ty, self._style)
                if tile is None and download_missing:
                    d = _download_tile_raw(self._zoom, tx, ty, self._style)
                    if d:
                        self._cache.put(self._zoom, tx, ty, self._style, d)
                        tile = self._cache.get(self._zoom, tx, ty, self._style)
                if tile:
                    dx, dy = (tx - tx1) * TILE_SIZE, (ty - ty1) * TILE_SIZE
                    img.paste(tile, (dx, dy))

        # Draw track + marker
        if draw_track or draw_marker:
            d = ImageDraw.Draw(img)
            ox, oy = tx1 * TILE_SIZE, ty1 * TILE_SIZE
            if draw_track and idx >= 1:
                pts = [(x - ox, y - oy) for i in range(idx + 1)
                       for x, y in [(self._px_x[i], self._px_y[i])]]
                if len(pts) >= 2:
                    d.line(pts, fill=self._trk_color, width=self._trk_width,
                           joint="round")
            if draw_marker:
                mx, my = cpx - ox, cpy - oy
                r = self._mkr_radius
                d.ellipse((mx - r, my - r, mx + r, my + r),
                          fill=self._mkr_color, outline=(0, 0, 0, 220), width=2)

        # Crop to output size centred on current position
        scx, scy = cpx - tx1 * TILE_SIZE, cpy - ty1 * TILE_SIZE
        x1 = max(0, int(scx - w / 2))
        y1 = max(0, int(scy - h / 2))
        x2, y2 = x1 + w, y1 + h
        if x2 > tw: x2 = tw; x1 = max(0, x2 - w)
        if y2 > th: y2 = th; y1 = max(0, y2 - h)
        cropped = img.crop((x1, y1, x2, y2))
        if cropped.size != (w, h):
            pad = Image.new("RGBA", (w, h), (30, 30, 30, 255))
            pad.paste(cropped, ((w - cropped.width) // 2,
                                (h - cropped.height) // 2))
            return pad
        return cropped

    def _idx(self, ts: float) -> int:
        """Find GPS index closest to timestamp."""
        target = self._ts0 + min(max(ts, 0), self._dur)
        for i, (dt, _, _) in enumerate(self._gps):
            if dt.timestamp() >= target: return i
        return len(self._gps) - 1
