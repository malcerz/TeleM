"""Map tile downloader and overlay renderer for HUD GPS track visualization.

Uses CartoCDN Light tiles (no API key required):
    https://a.basemaps.cartocdn.com/light_all/{z}/{x}/{y}.png
"""

from __future__ import annotations

import io
import math
import os
import time
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Optional

try:
    from PIL import Image, ImageDraw
except ImportError:
    Image = None  # type: ignore[assignment]

# ── Tile server config ──────────────────────────────────────────────────────

# CartoCDN basemap styles (free, no API key required)
MAP_STYLES: dict[str, str] = {
    "light_all":       "https://a.basemaps.cartocdn.com/light_all/{z}/{x}/{y}.png",
    "light_nolabels":  "https://a.basemaps.cartocdn.com/light_nolabels/{z}/{x}/{y}.png",
    "dark_all":        "https://a.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png",
    "dark_nolabels":   "https://a.basemaps.cartocdn.com/dark_nolabels/{z}/{x}/{y}.png",
    "voyager_all":     "https://a.basemaps.cartocdn.com/voyager_all/{z}/{x}/{y}.png",
    "voyager_nolabels":"https://a.basemaps.cartocdn.com/voyager_nolabels/{z}/{x}/{y}.png",
    "satellite":       "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
}
DEFAULT_MAP_STYLE = "light_all"

TILE_URL = MAP_STYLES[DEFAULT_MAP_STYLE]
TILE_SIZE = 256
USER_AGENT = "TeleMHUD/1.0"
REQUEST_DELAY = 0.15  # seconds between tile requests (fair use)
CACHE_DIR = Path.home() / ".telem_map_tiles"
_MAX_TILES_PER_RENDER = 20  # prevent runaway downloads


# ── Coordinate conversion (Web Mercator) ────────────────────────────────────


def lat_lon_to_tile_coords(
    lat: float, lon: float, zoom: int
) -> tuple[int, int, float, float]:
    """Convert latitude/longitude to tile x/y and pixel offset within the tile.

    Returns:
        (tile_x, tile_y, pixel_x_offset, pixel_y_offset) at the given zoom level.
    """
    n = 2 ** zoom
    x_tile = (lon + 180.0) / 360.0 * n
    lat_rad = math.radians(lat)
    y_tile = (1.0 - math.log(math.tan(lat_rad) + 1.0 / math.cos(lat_rad)) / math.pi) / 2.0 * n
    tile_x = int(x_tile)
    tile_y = int(y_tile)
    px = (x_tile - tile_x) * TILE_SIZE
    py = (y_tile - tile_y) * TILE_SIZE
    return tile_x, tile_y, px, py


def lon_to_tile_x(lon: float, zoom: int) -> float:
    n = 2 ** zoom
    return (lon + 180.0) / 360.0 * n


def lat_to_tile_y(lat: float, zoom: int) -> float:
    n = 2 ** zoom
    lat_rad = math.radians(lat)
    return (1.0 - math.log(math.tan(lat_rad) + 1.0 / math.cos(lat_rad)) / math.pi) / 2.0 * n


# ── Tile download with local cache ──────────────────────────────────────────


def _cache_path(z: int, x: int, y: int, style: str = DEFAULT_MAP_STYLE) -> Path:
    """Disk cache path for a tile (style is part of the path).

    Without the style component, switching e.g. ``light_all`` → ``satellite``
    would serve the previously cached style from disk and the satellite
    switch would appear to do nothing (ETAP MAP PRELOAD — Satellite fix).
    """
    return CACHE_DIR / str(style) / str(z) / str(x) / f"{y}.png"


_last_request_time: float = 0.0


def _shared_sqlite_cache_tile(z: int, x: int, y: int, style: str):
    """Read a tile from the shared moving_map SQLite cache, if present.

    Lets static_map benefit from overview tiles prepared by MapPreload (which
    writes to the shared SQLite cache) without re-downloading them.
    """
    try:
        from src.moving_map import get_shared_tile_cache
        return get_shared_tile_cache().get(z, x, y, style)
    except Exception:
        return None


def download_tile(z: int, x: int, y: int, style: str = DEFAULT_MAP_STYLE, download: bool = True) -> Optional[Image.Image]:
    """Download a single map tile, using local disk cache. Respects fair-use delay.

    Args:
        download: If False, only return already-cached tiles (skip network).
    """
    if Image is None:
        return None

    cp = _cache_path(z, x, y, style)
    if cp.exists():
        try:
            return Image.open(cp).convert("RGBA")
        except Exception:
            pass  # corrupted — re-download

    # Overview tiles prepared by MapPreload live in the shared SQLite cache.
    shared = _shared_sqlite_cache_tile(z, x, y, style)
    if shared is not None:
        return shared

    if not download:
        return None  # tylko cache, bez sieci

    global _last_request_time
    elapsed = time.time() - _last_request_time
    if elapsed < REQUEST_DELAY:
        time.sleep(REQUEST_DELAY - elapsed)

    url_template = MAP_STYLES.get(style, MAP_STYLES[DEFAULT_MAP_STYLE])
    url = url_template.format(z=z, x=x, y=y)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = resp.read()
    except Exception:
        return None
    finally:
        _last_request_time = time.time()

    try:
        img = Image.open(io.BytesIO(data)).convert("RGBA")
    except Exception:
        return None

    cp.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(cp, "wb") as f:
            f.write(data)
    except Exception:
        pass

    return img


# ── In-memory caches ───────────────────────────────────────────────────────

# Cache: (zoom, tx1, tx2, ty1, ty2, style) -> (stitched_img, scale, draw_w, draw_h, off_x, off_y)
_TILE_CACHE: dict[str, tuple] = {}

# Cache: (zoom, track_fingerprint) -> (abs_tx_list, abs_ty_list)  — no trig per frame
_TRACK_CACHE: dict[str, tuple] = {}


def _tile_cache_key(zoom: int, tx1: int, tx2: int, ty1: int, ty2: int, style: str) -> str:
    return f"{zoom}_{tx1}_{tx2}_{ty1}_{ty2}_{style}"


def _track_fingerprint(gps_track: list) -> int:
    """Return a stable hash for a GPS track (length + first/mid/last)."""
    if not gps_track:
        return 0
    n = len(gps_track)
    return hash((n, gps_track[0], gps_track[n // 2], gps_track[-1]))


def clear_map_cache() -> None:
    """Clear all cached tiles and track projections.
    Call this when zoom, map_style, or the GPS track changes."""
    _TILE_CACHE.clear()
    _TRACK_CACHE.clear()


# ── Map overlay renderer ────────────────────────────────────────────────────


def precache_map_tiles(
    gps_track: list[tuple[datetime, float, float]],
    zoom: int = 16,
    map_style: str = DEFAULT_MAP_STYLE,
    margin: int = 2,
    zooms: list[int] | None = None,
) -> int:
    """Download all unique map tiles needed for the entire GPS track.

    Runs synchronously — call in a background thread for non-blocking pre-cache.
    Returns the number of tiles downloaded.
    """
    if Image is None or not gps_track:
        return 0

    if zooms is None:
        zooms = [zoom]

    needed: set[tuple[int, int, int]] = set()
    for z in zooms:
        for _, lat, lon in gps_track:
            cx = lon_to_tile_x(lon, z)
            cy = lat_to_tile_y(lat, z)
            tx = int(cx)
            ty = int(cy)
            for dx in range(-margin, margin + 1):
                for dy in range(-margin, margin + 1):
                    needed.add((z, tx + dx, ty + dy))

    cnt = 0
    for z, x, y in needed:
        if download_tile(z, x, y, style=map_style, download=True) is not None:
            cnt += 1
    return cnt


def render_map_overlay(
    gps_track: list[tuple[datetime, float, float]],
    current_index: int,
    width: int,
    height: int,
    zoom: int = 16,
    map_style: str = DEFAULT_MAP_STYLE,
    track_color: tuple[int, int, int, int] = (255, 60, 30, 220),
    track_width: int = 3,
    marker_color: tuple[int, int, int, int] = (255, 255, 255, 255),
    marker_radius: int = 7,
    hide_marker: bool = False,
    hide_track: bool = False,
    margin: int = 4,
    download_missing: bool = True,
    track_antialiasing: int = 1,
    track_outline_width: int = 0,
    track_outline_color: tuple[int, int, int, int] = (0, 0, 0, 220),
) -> Image.Image:
    """Render a map with GPS track and current-position marker.

    The map is **centred on the current position** and follows it as the
    playback progresses.  Higher zoom = tighter view around the rider.

    Args:
        gps_track: List of (timestamp, lat, lon) points — full route.
        current_index: Index into *gps_track* for the current position.
        width: Output image width in pixels.
        height: Output image height in pixels.
        zoom: OSM zoom level (10–20).  10 = continent, 16 = street, 20 = building.
        track_color: RGBA tuple for the track line.
        track_width: Line width for the track.
        marker_color: RGBA tuple for the position marker.
        marker_radius: Radius of the position marker in pixels.
        margin: Padding around the map in pixels.
        download_missing: If True (default), download tiles not yet cached.
            If False, only use tiles already on disk — uncached areas stay dark.
        track_antialiasing (ETAP 10T): 1/2/4 route supersampling factor (1=off).
        track_outline_width (ETAP 10T): outline halo width in px (0 = none).
        track_outline_color (ETAP 10T): outline colour (RGBA).

    Returns:
        RGBA PIL.Image containing the rendered map or a placeholder.
    """
    if Image is None or not gps_track or len(gps_track) < 2:
        return _placeholder(width, height, "Brak danych GPS")

    ci = max(0, min(len(gps_track) - 1, current_index))
    _, center_lat, center_lon = gps_track[ci]

    # ── Determine tile range centred on current position ─────────────────
    target_w = width - 2 * margin
    target_h = height - 2 * margin

    tiles_across = target_w / TILE_SIZE
    tiles_down = target_h / TILE_SIZE

    ct_x = lon_to_tile_x(center_lon, zoom)
    ct_y = lat_to_tile_y(center_lat, zoom)
    cx_tile = int(ct_x)
    cy_tile = int(ct_y)

    half_tiles_x = int(math.ceil(tiles_across / 2))
    half_tiles_y = int(math.ceil(tiles_down / 2))
    tx1 = cx_tile - half_tiles_x
    tx2 = cx_tile + half_tiles_x
    ty1 = cy_tile - half_tiles_y
    ty2 = cy_tile + half_tiles_y

    ntiles = (tx2 - tx1 + 1) * (ty2 - ty1 + 1)
    if ntiles > _MAX_TILES_PER_RENDER:
        return _placeholder(width, height, f"Zbyt duży obszar (zoom {zoom})")

    # ── Check tile cache ─────────────────────────────────────────────────
    tkey = _tile_cache_key(zoom, tx1, tx2, ty1, ty2, map_style)
    cached_base = _TILE_CACHE.get(tkey)
    if cached_base is not None:
        tile_base_img, scale, draw_w, draw_h, off_x, off_y = cached_base
    else:
        # ── Download tiles ───────────────────────────────────────────────
        tile_images: dict[tuple[int, int], Image.Image] = {}
        for tx in range(tx1, tx2 + 1):
            for ty in range(ty1, ty2 + 1):
                tile = download_tile(zoom, tx, ty, style=map_style, download=download_missing)
                if tile is not None:
                    tile_images[(tx, ty)] = tile

        if not tile_images:
            return _placeholder(width, height, "Nie można pobrać mapy")

        # ── Stitch tiles ─────────────────────────────────────────────────
        cols = tx2 - tx1 + 1
        rows = ty2 - ty1 + 1
        map_w = cols * TILE_SIZE
        map_h = rows * TILE_SIZE
        tile_base_img = Image.new("RGBA", (map_w, map_h), (0, 0, 0, 0))

        for (tx, ty), tile in tile_images.items():
            px = (tx - tx1) * TILE_SIZE
            py = (ty - ty1) * TILE_SIZE
            tile_base_img.paste(tile, (px, py), tile)

        scale = min(target_w / map_w, target_h / map_h)
        draw_w = int(map_w * scale)
        draw_h = int(map_h * scale)
        tile_base_img = tile_base_img.resize((draw_w, draw_h), Image.BILINEAR)

        off_x = (width - draw_w) // 2
        off_y = (height - draw_h) // 2

        _TILE_CACHE[tkey] = (tile_base_img, scale, draw_w, draw_h, off_x, off_y)

    # ── Output canvas ───────────────────────────────────────────────────
    canvas = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)
    draw.rectangle(
        (off_x - 1, off_y - 1, off_x + draw_w, off_y + draw_h),
        outline=(255, 255, 255, 80), width=1,
    )
    canvas.paste(tile_base_img, (off_x, off_y), tile_base_img)

    # ── Get cached absolute tile coords for track points ────────────────
    fingerprint = _track_fingerprint(gps_track)
    tcache_key = f"{zoom}_{fingerprint}"
    cached_track = _TRACK_CACHE.get(tcache_key)
    if cached_track is not None:
        abs_tx_list, abs_ty_list = cached_track
    else:
        abs_tx_list = [lon_to_tile_x(lon, zoom) for _, _, lon in gps_track]
        abs_ty_list = [lat_to_tile_y(lat, zoom) for _, lat, _ in gps_track]
        _TRACK_CACHE[tcache_key] = (abs_tx_list, abs_ty_list)

    # ── Project cached coords to canvas pixels (fast: no trig) ─────────
    origin_tx_f = float(tx1)
    origin_ty_f = float(ty1)
    aa = max(1, min(8, int(track_antialiasing or 1)))
    outline_w = max(0, int(track_outline_width or 0))
    track_draw = Image.new("RGBA", (width * aa, height * aa), (0, 0, 0, 0))
    td = ImageDraw.Draw(track_draw)
    points_px: list[tuple[int, int] | None] = []

    for tx_f, ty_f in zip(abs_tx_list, abs_ty_list):
        raw_px = off_x + (tx_f - origin_tx_f) * TILE_SIZE * scale
        raw_py = off_y + (ty_f - origin_ty_f) * TILE_SIZE * scale
        if aa == 1:
            # Legacy path: int() truncation preserved exactly for byte-parity.
            px_i = int(raw_px)
            py_i = int(raw_py)
        else:
            px_i = int(round(raw_px * aa))
            py_i = int(round(raw_py * aa))
        if -100 * aa <= px_i <= width * aa + 100 * aa and -100 * aa <= py_i <= height * aa + 100 * aa:
            points_px.append((px_i, py_i))
        else:
            points_px.append(None)

    segments: list[tuple[int, int]] = []
    if not hide_track:
        for pt in points_px:
            if pt is None:
                if len(segments) >= 2:
                    if outline_w > 0:
                        td.line(segments, fill=track_outline_color,
                                width=max(1, (track_width + 2 * outline_w) * aa), joint="curve")
                    td.line(segments, fill=track_color,
                            width=max(1, track_width * aa), joint="curve")
                segments = []
            else:
                segments.append(pt)
        if len(segments) >= 2:
            if outline_w > 0:
                td.line(segments, fill=track_outline_color,
                        width=max(1, (track_width + 2 * outline_w) * aa), joint="curve")
            td.line(segments, fill=track_color,
                    width=max(1, track_width * aa), joint="curve")

    if aa > 1:
        # ETAP 10T: downsample the supersampled track overlay back to output
        # size.  Keeps the visual line width and centre coordinates identical;
        # only the edges become antialiased.
        resampling = getattr(Image, "Resampling", Image)
        track_draw = track_draw.resize((width, height), resampling.LANCZOS)
        td = ImageDraw.Draw(track_draw)

    # ── Position marker (drawn at final resolution so it never blurs) ──
    if not hide_marker and 0 <= ci < len(points_px) and points_px[ci] is not None:
        mx_f = (points_px[ci][0] + 0.0) / aa
        my_f = (points_px[ci][1] + 0.0) / aa
        mx, my = int(round(mx_f)), int(round(my_f))
        for r in range(marker_radius + 4, marker_radius - 1, -1):
            alpha = 80 if r > marker_radius + 1 else 200
            td.ellipse(
                (mx - r, my - r, mx + r, my + r),
                fill=(*marker_color[:3], alpha),
            )
        td.ellipse((mx - 3, my - 3, mx + 3, my + 3), fill=marker_color)

    canvas = Image.alpha_composite(canvas, track_draw)
    return canvas


def _placeholder(width: int, height: int, text: str = "Mapa") -> Image.Image:
    """Return a placeholder image when no GPS data or tiles are available."""
    if Image is None:
        img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    else:
        img = Image.new("RGBA", (width, height), (20, 20, 30, 200))
        draw = ImageDraw.Draw(img)
        bbox = draw.textbbox((0, 0), text)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]
        draw.text(
            ((width - tw) // 2, (height - th) // 2),
            text,
            fill=(180, 180, 180, 255),
        )
    return img
