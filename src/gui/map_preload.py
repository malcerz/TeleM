"""MapPreload worker — prepares the coarse/overview map during project load.

Runs on a daemon background thread, in parallel with GPMF parsing.  It uses
the GPS track (FIT preferred, then GPX, then GPMF) to compute the map bounds,
picks a coarse overview zoom bounded by a tile-count limit, and downloads the
overview tiles into the shared (style-aware) tile cache with real progress.

The worker never blocks the GUI thread; it updates a ``MapContext`` under a
lock and invokes a done-callback (marshalled to the GUI thread by the caller)
when the overview is ready or fails.
"""

from __future__ import annotations

import threading
from typing import Any, Callable, Optional

from src.gui.map_context import MapContext
from src.moving_map import (
    bounds_from_track,
    bounds_center,
    build_overview_image,
    overview_tile_plan,
    overview_zoom_for,
    download_tile_shared,
)

# Reasonable cap for the first (coarse) overview so it is ready quickly and
# never fetches hundreds/thousands of tiles on the first preview.
DEFAULT_OVERVIEW_MAX_TILES = 16
DEFAULT_MIN_ZOOM = 3
DEFAULT_MAX_ZOOM = 14


def compute_map_geometry(
    gps_track,
    max_tiles: int = DEFAULT_OVERVIEW_MAX_TILES,
) -> dict:
    """Compute bounds / center / overview zoom / tile plan (pure, testable)."""
    bounds = bounds_from_track(gps_track)
    center = bounds_center(bounds) if bounds else None
    zoom = overview_zoom_for(bounds, max_tiles=max_tiles) if bounds else None
    plan = overview_tile_plan(bounds, zoom) if (bounds and zoom is not None) else []
    return {
        "bounds": bounds,
        "center": center,
        "overview_zoom": zoom,
        "tile_plan": plan,
    }


class MapPreloadWorker:
    """One-shot overview preparation for a provider/style.

    ``done_cb(success: bool, message: str)`` is invoked (on the worker thread)
    when the overview is ready or fails.  The caller is responsible for
    marshalling to the GUI thread.
    """

    def __init__(
        self,
        context: MapContext,
        gps_track,
        provider: str = "light_all",
        generation: int = 0,
        max_tiles: int = DEFAULT_OVERVIEW_MAX_TILES,
        done_cb: Optional[Callable[[bool, str], None]] = None,
        progress_cb: Optional[Callable[[int, int], None]] = None,
    ) -> None:
        self.context = context
        self.gps_track = list(gps_track or [])
        self.provider = provider
        self.generation = generation
        self.max_tiles = max_tiles
        self.done_cb = done_cb
        self.progress_cb = progress_cb
        self._thread: Optional[threading.Thread] = None
        self._cancel = threading.Event()

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def cancel(self) -> None:
        self._cancel.set()

    @property
    def is_alive(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def _run(self) -> None:
        # The caller resets the context to this job's provider/generation
        # BEFORE start().  All context mutations are generation-guarded, so a
        # stale (older) job can never overwrite a newer result.
        g = self.generation
        if not self.gps_track or len(self.gps_track) < 2:
            self.context.set_error("Brak danych GPS", generation=g)
            self._finish(False, "Brak danych GPS")
            return
        try:
            geom = compute_map_geometry(self.gps_track, self.max_tiles)
            if not geom["bounds"] or not geom["tile_plan"]:
                self.context.set_error("Nie można określić obszaru trasy", generation=g)
                self._finish(False, "Nie można określić obszaru trasy")
                return
            self.context.set_geometry(
                gps_source=self.context.gps_source or "gps",
                gps_track=self.gps_track,
                bounds=geom["bounds"],
                center=geom["center"],
                overview_zoom=geom["overview_zoom"],
                required_tiles=len(geom["tile_plan"]),
                generation=g,
            )
            plan = geom["tile_plan"]
            loaded = 0
            total = len(plan)
            for i, (z, x, y) in enumerate(plan):
                if self._cancel.is_set():
                    self.context.cancel()
                    self._finish(False, "canceled")
                    return
                if download_tile_shared(z, x, y, self.provider) is not None:
                    loaded += 1
                self.context.set_progress(loaded, total, generation=g)
                if self.progress_cb is not None:
                    try:
                        self.progress_cb(loaded, total)
                    except Exception:
                        pass
            # Level 1: coarse overview image (tiles + route) for immediate map.
            overview = build_overview_image(
                geom["bounds"], geom["overview_zoom"], plan,
                self.gps_track, style=self.provider,
            )
            self.context.set_ready(overview, generation=g)
            self._finish(True, "ready")

            # Level 2: background precache of full route detail tiles (zooms 14..16)
            try:
                from src.moving_map import _lat_lon_to_tile, get_shared_tile_cache
                detail_zooms = sorted({geom["overview_zoom"], 14, 15, 16})
                detail_needed: set[tuple[int, int, int]] = set()
                for dz in detail_zooms:
                    for _, lat, lon in self.gps_track:
                        tx, ty, _, _ = _lat_lon_to_tile(lat, lon, dz)
                        for dx in range(-3, 4):
                            for dy in range(-3, 4):
                                detail_needed.add((dz, tx + dx, ty + dy))

                cache = get_shared_tile_cache()
                for dz, dx, dy in detail_needed:
                    if self._cancel.is_set():
                        return
                    if not cache.has(dz, dx, dy, self.provider):
                        download_tile_shared(dz, dx, dy, self.provider)
            except Exception:
                pass
        except Exception as exc:  # pragma: no cover - defensive
            self.context.set_error(str(exc), generation=g)
            self._finish(False, str(exc))

    def _finish(self, ok: bool, message: str) -> None:
        if self.done_cb is not None:
            try:
                self.done_cb(ok, message)
            except Exception:
                pass
