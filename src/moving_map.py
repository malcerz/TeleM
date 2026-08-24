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

from src.indicators.profiling import get_overlay_profiler

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


def track_up_working_size(output_size: int) -> int:
    """Return the square working size required before a Track-Up rotation."""
    output = max(1, int(output_size))
    return max(output, int(math.ceil(output * math.sqrt(2.0))))


def track_up_rotation_degrees(heading: float | None) -> float:
    """Return the image rotation that puts geographic heading at the top.

    Pillow's positive image rotation moves a vector pointing east (right) to
    the top at +90 degrees, so the map is rotated by the canonical heading
    itself.  ``None`` is deliberately represented as zero only for the visual
    fallback; callers retain the original missing telemetry state.
    """
    if heading is None:
        return 0.0
    return float(heading) % 360.0

MAP_STYLES: dict[str, str] = {
    "light_all":       "https://a.basemaps.cartocdn.com/light_all/{z}/{x}/{y}.png",
    "light_nolabels":  "https://a.basemaps.cartocdn.com/light_nolabels/{z}/{x}/{y}.png",
    "dark_all":        "https://a.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png",
    "dark_nolabels":   "https://a.basemaps.cartocdn.com/dark_nolabels/{z}/{x}/{y}.png",
    "voyager_all":     "https://a.basemaps.cartocdn.com/voyager_all/{z}/{x}/{y}.png",
    "voyager_nolabels":"https://a.basemaps.cartocdn.com/voyager_nolabels/{z}/{x}/{y}.png",
    "osm":             "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
    "satellite":       "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
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


# ── Shared tile cache + map geometry helpers (MapPreload) ──────────────

_shared_cache: Optional["TileCache"] = None


def get_shared_tile_cache() -> "TileCache":
    """Return the process-wide shared TileCache (SQLite, style-aware).

    The MapPreload worker and every MovingMapRenderer write to the same
    SQLite file + shared in-memory LRU, so overview tiles prepared during
    project load are immediately visible to the map indicator.
    """
    global _shared_cache
    if _shared_cache is None:
        _shared_cache = TileCache()
    return _shared_cache


def download_tile_shared(z: int, x: int, y: int, style: str) -> Image.Image | None:
    """Download (or load from the shared cache) one tile.

    Runs synchronously — call on a worker thread.  Returns the decoded
    RGBA image (also cached), or None on network/cache failure.
    """
    cache = get_shared_tile_cache()
    cached = cache.get(z, x, y, style)
    if cached is not None:
        return cached
    data = _download_tile_raw(z, x, y, style)
    if data is None:
        return None
    try:
        img = Image.open(io.BytesIO(data)).convert("RGBA")
    except Exception:
        return None
    cache.put(z, x, y, style, data)
    return img


def bounds_from_track(gps_track) -> tuple[float, float, float, float] | None:
    """Return (min_lat, min_lon, max_lat, max_lon) for a GPS track."""
    lats = []
    lons = []
    for _, lat, lon in gps_track:
        if lat is None or lon is None:
            continue
        lats.append(float(lat))
        lons.append(float(lon))
    if not lats:
        return None
    return min(lats), min(lons), max(lats), max(lons)


def bounds_center(bounds) -> tuple[float, float] | None:
    if not bounds:
        return None
    return (bounds[0] + bounds[2]) / 2.0, (bounds[1] + bounds[3]) / 2.0


def _tile_count_for_bounds(bounds, zoom: int) -> int:
    """Approximate number of tiles covering *bounds* at *zoom*."""
    min_lat, min_lon, max_lat, max_lon = bounds
    n = 2 ** zoom
    tx0 = int((min_lon + 180.0) / 360.0 * n)
    tx1 = int((max_lon + 180.0) / 360.0 * n)
    lat_rad0 = math.radians(max_lat)
    lat_rad1 = math.radians(min_lat)
    ty0 = int((1.0 - math.log(math.tan(lat_rad0) + 1.0 / math.cos(lat_rad0)) / math.pi) / 2.0 * n)
    ty1 = int((1.0 - math.log(math.tan(lat_rad1) + 1.0 / math.cos(lat_rad1)) / math.pi) / 2.0 * n)
    return max(1, abs(tx1 - tx0) + 1) * max(1, abs(ty1 - ty0) + 1)


def overview_zoom_for(
    bounds,
    max_tiles: int = 16,
    min_zoom: int = 3,
    max_zoom: int = 14,
) -> int:
    """Pick the highest zoom whose tile count for *bounds* fits in *max_tiles*.

    Used for the fast coarse/overview map prepared during project load.
    """
    if not bounds:
        return min_zoom
    best = min_zoom
    for z in range(min_zoom, max_zoom + 1):
        if _tile_count_for_bounds(bounds, z) <= max_tiles:
            best = z
        else:
            break
    return best


def overview_tile_plan(bounds, zoom: int) -> list[tuple[int, int, int]]:
    """Return the list of (z, x, y) tiles covering *bounds* at *zoom*."""
    if not bounds:
        return []
    min_lat, min_lon, max_lat, max_lon = bounds
    n = 2 ** zoom
    tx0 = int((min_lon + 180.0) / 360.0 * n)
    tx1 = int((max_lon + 180.0) / 360.0 * n)
    lat_rad0 = math.radians(max_lat)
    lat_rad1 = math.radians(min_lat)
    ty0 = int((1.0 - math.log(math.tan(lat_rad0) + 1.0 / math.cos(lat_rad0)) / math.pi) / 2.0 * n)
    ty1 = int((1.0 - math.log(math.tan(lat_rad1) + 1.0 / math.cos(lat_rad1)) / math.pi) / 2.0 * n)
    return [
        (zoom, tx, ty)
        for ty in range(min(ty0, ty1), max(ty0, ty1) + 1)
        for tx in range(min(tx0, tx1), max(tx0, tx1) + 1)
    ]


def build_overview_image(
    bounds,
    zoom: int,
    plan: list[tuple[int, int, int]],
    gps_track,
    style: str = DEFAULT_STYLE,
) -> Image.Image | None:
    """Stitch the overview tiles + draw the GPS route into one coarse image.

    Returns ``None`` when no tile could be loaded.  Used by MapPreload as the
    immediate "Level 1" map image (scaled to the widget by the renderer).
    """
    if Image is None or not plan:
        return None
    cache = get_shared_tile_cache()
    tiles = {}
    for z, x, y in plan:
        t = cache.get(z, x, y, style)
        if t is not None:
            tiles[(x, y)] = t
    if not tiles:
        return None
    xs = [x for (x, _) in tiles]
    ys = [y for (_, y) in tiles]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    cols = max_x - min_x + 1
    rows = max_y - min_y + 1
    img = Image.new("RGBA", (cols * TILE_SIZE, rows * TILE_SIZE), (30, 30, 30, 255))
    for (x, y), t in tiles.items():
        img.paste(t, ((x - min_x) * TILE_SIZE, (y - min_y) * TILE_SIZE), t)
    # Draw the GPS route projected to the stitched overview pixels.
    if gps_track and len(gps_track) >= 2:
        d = ImageDraw.Draw(img)
        n = 2 ** zoom
        pts = []
        for _, lat, lon in gps_track:
            if lat is None or lon is None:
                continue
            tx_f = (lon + 180.0) / 360.0 * n - min_x
            lat_rad = math.radians(lat)
            ty_f = (1.0 - math.log(math.tan(lat_rad) + 1.0 / math.cos(lat_rad)) / math.pi) / 2.0 * n - min_y
            pts.append((tx_f * TILE_SIZE, ty_f * TILE_SIZE))
        if len(pts) >= 2:
            d.line(pts, fill=(255, 60, 30, 220), width=max(2, TILE_SIZE // 64), joint="curve")
    return img


# ── MovingMapRenderer ───────────────────────────────────────────────────

def draw_position_marker(image, center, radius, *, style="dot", heading=None):
    """Draw the position marker in output coordinates.

    Direction is clockwise degrees from screen-up; missing direction keeps the
    legacy dot behaviour.
    """
    d = ImageDraw.Draw(image)
    mx, my = center
    r = max(1, float(radius))
    if str(style).strip().lower() == "directional" and heading is not None:
        a = math.radians(float(heading))
        tip = (mx + math.sin(a) * r * 1.8, my - math.cos(a) * r * 1.8)
        left = (mx + math.sin(a + 2.45) * r, my - math.cos(a + 2.45) * r)
        right = (mx + math.sin(a - 2.45) * r, my - math.cos(a - 2.45) * r)
        d.polygon((tip, left, right), fill=(255, 255, 255, 255), outline=(0, 0, 0, 220))
    else:
        d.ellipse((mx-r, my-r, mx+r, my+r), fill=(255, 255, 255, 255), outline=(0, 0, 0, 220), width=2)
    return image


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
        marker_style="dot",
        track_antialiasing=1,
        track_outline_width=0,
        track_outline_color=(0, 0, 0, 220),
    ):
        if Image is None: raise ImportError("Pillow required")
        self._gps = gps_track
        self._zoom = zoom
        self._style = style
        self._trk_color = track_color
        self._trk_width = track_width
        self._mkr_color = marker_color
        self._mkr_radius = marker_radius
        self._mkr_style = str(marker_style or "dot").strip().lower()
        # ETAP 10T: track-line antialiasing + outline (default preserves legacy).
        self._track_aa = max(1, min(8, int(track_antialiasing or 1)))
        self._track_outline_w = max(0, int(track_outline_width or 0))
        self._track_outline_color = tuple(track_outline_color or (0, 0, 0, 220))
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

    def precache_tiles(self, margin=2, zooms=None) -> int:
        """Download ALL tiles needed for the entire track for given zooms. Returns count."""
        if zooms is None:
            zooms = [self._zoom]
            
        needed: set[tuple] = set()
        for z in zooms:
            # We must recalculate tile coords for each zoom level!
            for _, lat, lon in self._gps:
                from src.moving_map import _lat_lon_to_tile
                tx, ty, _, _ = _lat_lon_to_tile(lat, lon, z)
                for dx in range(-margin, margin + 1):
                    for dy in range(-margin, margin + 1):
                        needed.add((z, tx + dx, ty + dy))
        cnt = 0
        for z, x, y in needed:
            if self._cache.get(z, x, y, self._style): continue
            d = _download_tile_raw(z, x, y, self._style)
            if d: self._cache.put(z, x, y, self._style, d); cnt += 1
        return cnt

    def background_precache(self, margin=2, done_callback=None, zooms=None) -> threading.Thread:
        """Uruchamia w tle pobieranie kafelków dla zadanych zoomów i całej trasy.

        Args:
            margin: Liczba dodatkowych kafelków wokół każdego punktu GPS.
            done_callback: Opcjonalna funkcja wołana po zakończeniu cache'owania.
            zooms: Lista poziomów zoom do zbuforowania. Domyślnie tylko aktualny.
        Returns:
            Wątek wykonujący precache (daemon, można go ignorować).
        """
        def _run():
            self.precache_tiles(margin=margin, zooms=zooms)
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
               download_missing=True, heading=None) -> Image.Image:
        """Map image centred on GPS position at timestamp *ts* (seconds).

        Args:
            ts: Timestamp in seconds (relative to track start).
            w, h: Output image size in pixels.
            draw_track, draw_marker: Whether to draw track line/position marker.
            download_missing: If True, download missing tiles on demand (may block).
                If False, only cached tiles are used – uncached areas stay grey.
        """
        # Interpolowana pozycja → płynny ruch co klatkę (nie skok co ~1 s)
        profiler = get_overlay_profiler()
        position_started = time.perf_counter()
        cpx, cpy = self._interp_pos(ts)
        cx, cy = int(cpx // TILE_SIZE), int(cpy // TILE_SIZE)

        # Tile range covering output size
        half_w = int(math.ceil(w / 2 / TILE_SIZE)) + 1
        half_h = int(math.ceil(h / 2 / TILE_SIZE)) + 1
        tx1, tx2 = cx - half_w, cx + half_w + 1
        ty1, ty2 = cy - half_h, cy + half_h + 1
        profiler.record(
            "map.position_lookup",
            (time.perf_counter() - position_started) * 1000.0,
        )

        background_started = time.perf_counter()
        grid_key = (tx1, tx2, ty1, ty2, self._zoom, self._style, draw_track,
                    self._trk_color, self._trk_width,
                    self._track_aa, self._track_outline_w, self._track_outline_color)
        if getattr(self, "_grid_cache_key", None) == grid_key and hasattr(self, "_grid_cache_img"):
            # The cached grid is immutable: it contains tiles and the route,
            # but never the dynamic marker.  Keep it shared and crop the small
            # working viewport below instead of copying the whole grid.
            img = self._grid_cache_img
        else:
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

            if draw_track and len(self._gps) >= 2:
                route_started = time.perf_counter()
                ox, oy = tx1 * TILE_SIZE, ty1 * TILE_SIZE
                pts = [(self._px_x[i] - ox, self._px_y[i] - oy) for i in range(len(self._gps))]
                aa = self._track_aa
                if aa > 1:
                    # ETAP 10T: supersampled transparent route overlay -> LANCZOS
                    # downsample -> alpha composite.  Preserves the visual line
                    # width (width scaled by aa, then downsampled back) and keeps
                    # the centre coordinates identical (only edges get AA).
                    overlay = Image.new("RGBA", (tw * aa, th * aa), (0, 0, 0, 0))
                    d_ov = ImageDraw.Draw(overlay)
                    aa_pts = [(x * aa, y * aa) for x, y in pts]
                    if self._track_outline_w > 0:
                        outline_w = max(1, int(round(
                            (self._trk_width + 2 * self._track_outline_w) * aa
                        )))
                        d_ov.line(aa_pts, fill=self._track_outline_color,
                                  width=outline_w, joint="round")
                    d_ov.line(aa_pts, fill=self._trk_color,
                              width=max(1, int(round(self._trk_width * aa))),
                              joint="round")
                    resampling = getattr(Image, "Resampling", Image)
                    overlay = overlay.resize((tw, th), resampling.LANCZOS)
                    img = Image.alpha_composite(img, overlay)
                else:
                    d_grid = ImageDraw.Draw(img)
                    if self._track_outline_w > 0:
                        d_grid.line(pts, fill=self._track_outline_color,
                                    width=max(1, self._trk_width + 2 * self._track_outline_w),
                                    joint="round")
                    d_grid.line(pts, fill=self._trk_color,
                                width=max(1, self._trk_width), joint="round")
                profiler.record(
                    "map.route_polyline",
                    (time.perf_counter() - route_started) * 1000.0,
                )

            self._grid_cache_key = grid_key
            self._grid_cache_img = img
        profiler.record(
            "map.background_tiles",
            (time.perf_counter() - background_started) * 1000.0,
        )

        tw = (tx2 - tx1) * TILE_SIZE
        th = (ty2 - ty1) * TILE_SIZE

        # Crop to output size centred on current (interpolated) position
        crop_started = time.perf_counter()
        scx, scy = cpx - tx1 * TILE_SIZE, cpy - ty1 * TILE_SIZE
        x1 = max(0, int(scx - w / 2))
        y1 = max(0, int(scy - h / 2))
        x2, y2 = x1 + w, y1 + h
        if x2 > tw: x2 = tw; x1 = max(0, x2 - w)
        if y2 > th: y2 = th; y1 = max(0, y2 - h)
        cropped = img.crop((x1, y1, x2, y2))

        # Draw the dynamic marker only on the cropped working image.  The
        # integer crop translation preserves the exact raster coordinates of
        # the previous full-grid draw-then-crop path.
        if draw_marker:
            marker_started = time.perf_counter()
            mx, my = scx - x1, scy - y1
            r = self._mkr_radius
            d = ImageDraw.Draw(cropped)
            if self._mkr_style == "directional" and heading is not None:
                # North-up: canonical heading points clockwise from screen-up.
                # Track-up calls this renderer with heading=None and draws an
                # upright marker after map rotation below.
                angle = float(heading)
                a = math.radians(angle)
                tip = (mx + math.sin(a) * r * 1.8, my - math.cos(a) * r * 1.8)
                left = (mx + math.sin(a + 2.45) * r, my - math.cos(a + 2.45) * r)
                right = (mx + math.sin(a - 2.45) * r, my - math.cos(a - 2.45) * r)
                d.polygon((tip, left, right), fill=self._mkr_color, outline=(0, 0, 0, 220))
            else:
                d.ellipse((mx - r, my - r, mx + r, my + r),
                          fill=self._mkr_color, outline=(0, 0, 0, 220), width=2)
            profiler.record(
                "map.current_marker",
                (time.perf_counter() - marker_started) * 1000.0,
            )

        if cropped.size != (w, h):
            pad = Image.new("RGBA", (w, h), (30, 30, 30, 255))
            pad.paste(cropped, ((w - cropped.width) // 2,
                                (h - cropped.height) // 2))
            profiler.record(
                "map.crop_resize",
                (time.perf_counter() - crop_started) * 1000.0,
            )
            return pad
        profiler.record(
            "map.crop_resize",
            (time.perf_counter() - crop_started) * 1000.0,
        )
        return cropped

    def render_track_up(
        self,
        ts: float,
        output_size: int,
        *,
        heading: float | None,
        draw_track: bool = True,
        draw_marker: bool = True,
        download_missing: bool = True,
    ) -> Image.Image:
        """Render one final-size map with the canonical heading at the top.

        The existing north-up renderer creates the complete tiles+route+marker
        raster first.  Track-Up only adds an internal overscan, rotates that
        finished raster around its center and crops back to the requested
        destination size.  Heading never enters tile selection or cache keys.
        """
        output = max(1, int(output_size))
        angle = track_up_rotation_degrees(heading)

        # Preserve the exact north-up fast path for missing/zero heading.
        if angle == 0.0:
            return self.render(
                ts, output, output,
                draw_track=draw_track,
                draw_marker=draw_marker,
                download_missing=download_missing,
                heading=(0.0 if heading is not None else None),
            )

        working = track_up_working_size(output)
        north_up = self.render(
            ts, working, working,
            draw_track=draw_track,
            # A directional marker is painted once in final Track-Up space;
            # suppress the north-up dot to avoid two position markers.
            draw_marker=(draw_marker and not (
                self._mkr_style == "directional" and heading is not None
            )),
            download_missing=download_missing,
            heading=None,
        )
        resampling = getattr(Image, "Resampling", Image)
        rotated = north_up.rotate(
            angle,
            resample=resampling.BICUBIC,
            expand=False,
            fillcolor=(30, 30, 30, 255),
        )
        # Repaint the marker in output space so it remains directional-up.
        if draw_marker and self._mkr_style == "directional" and heading is not None:
            d = ImageDraw.Draw(rotated)
            c = working / 2.0
            r = self._mkr_radius
            tip = (c, c - r * 1.8)
            left = (c - r * 0.65, c + r * 0.75)
            right = (c + r * 0.65, c + r * 0.75)
            d.polygon((tip, left, right), fill=self._mkr_color, outline=(0, 0, 0, 220))
        offset = (working - output) // 2
        return rotated.crop((offset, offset, offset + output, offset + output))

    def _interp_pos(self, ts: float) -> tuple[float, float]:
        """Return interpolated (px_x, px_y) at timestamp *ts* (seconds from track start).

        Linear interpolation between the two GPS points bracketing the target
        time → smooth per-frame movement instead of jumping between the 1 Hz
        samples.
        """
        n = len(self._gps)
        if n == 0:
            return 0.0, 0.0
        target = self._ts0 + min(max(ts, 0), self._dur)
        idx = self._idx(ts)
        if idx <= 0:
            return self._px_x[0], self._px_y[0]
        if idx >= n:
            return self._px_x[-1], self._px_y[-1]
        t0 = self._gps[idx - 1][0].timestamp()
        t1 = self._gps[idx][0].timestamp()
        span = t1 - t0
        if span <= 0:
            return self._px_x[idx], self._px_y[idx]
        frac = max(0.0, min(1.0, (target - t0) / span))
        x = self._px_x[idx - 1] + (self._px_x[idx] - self._px_x[idx - 1]) * frac
        y = self._px_y[idx - 1] + (self._px_y[idx] - self._px_y[idx - 1]) * frac
        return x, y

    def _idx(self, ts: float) -> int:
        """Find GPS index closest to timestamp."""
        target = self._ts0 + min(max(ts, 0), self._dur)
        for i, (dt, _, _) in enumerate(self._gps):
            if dt.timestamp() >= target: return i
        return len(self._gps) - 1

    # ── Viewport detail support (async GUI path) ───────────────────────

    def _viewport_range(self, ts: float, w: int, h: int):
        cpx, cpy = self._interp_pos(ts)
        cx = int(cpx // TILE_SIZE)
        cy = int(cpy // TILE_SIZE)
        half_w = int(math.ceil(int(w) / 2 / TILE_SIZE)) + 1
        half_h = int(math.ceil(int(h) / 2 / TILE_SIZE)) + 1
        return cx, cy, half_w, half_h

    def viewport_tile_coverage(self, ts: float, w: int, h: int) -> float:
        """Fraction of the current-viewport tiles present in the cache (0..1)."""
        cx, cy, half_w, half_h = self._viewport_range(ts, w, h)
        total = 0
        cached = 0
        for ty in range(cy - half_h, cy + half_h + 1):
            for tx in range(cx - half_w, cx + half_w + 1):
                total += 1
                if self._cache.get(self._zoom, tx, ty, self._style) is not None:
                    cached += 1
        return (cached / total) if total else 0.0

    def viewport_precache(
        self,
        ts: float,
        w: int,
        h: int,
        max_tiles: int = 25,
    ) -> int:
        """Download the current-viewport detail tiles (worker thread, bounded)."""
        cx, cy, half_w, half_h = self._viewport_range(ts, w, h)
        needed = [
            (self._zoom, tx, ty)
            for ty in range(cy - half_h, cy + half_h + 1)
            for tx in range(cx - half_w, cx + half_w + 1)
        ]
        if len(needed) > max_tiles:
            needed = needed[:max_tiles]
        downloaded = 0
        for z, x, y in needed:
            if not self._cache.get(z, x, y, self._style):
                d = _download_tile_raw(z, x, y, self._style)
                if d:
                    self._cache.put(z, x, y, self._style, d)
                    downloaded += 1
        return downloaded
