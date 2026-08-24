"""MapContext — precomputed map geometry/plan shared between project load and the map indicator.

Heavy map preparation (GPS track, bounds, overview zoom, tile plan, tile
download) is started during project load, in parallel with GPMF parsing.  The
map indicator then consumes the already-prepared context instead of computing
everything from scratch when it is added.

``MapContext`` is deliberately source-selective ONLY for the technical map
preload.  It never changes the user-selected telemetry source of any indicator.
"""

from __future__ import annotations

import threading
from typing import Any, Optional


class MapContext:
    """Thread-safe snapshot of the project map preparation state.

    Attributes (read from the GUI thread, written by the MapPreload worker
    under ``_lock``):
      generation_id — bumped whenever the project/provider/zoom changes so
                      stale workers can never overwrite a newer result.
      gps_source    — "fit" | "gpx" | "gpmf" | None (source used for bounds).
      gps_track     — list of (datetime, lat, lon).
      bounds        — (min_lat, min_lon, max_lat, max_lon) or None.
      center        — (lat, lon) or None.
      overview_zoom — coarse zoom chosen so the tile count fits the limit.
      provider      — map style currently prepared ("light_all"/"satellite"...).
      status        — "idle" | "preparing" | "ready" | "error".
      error         — human-readable error or None.
      progress      — 0..1 (downloaded/loaded tiles / required tiles).
      required_tiles, loaded_tiles — integer progress.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.generation_id: int = 0
        self.gps_source: Optional[str] = None
        self.gps_track: list = []
        self.bounds: Optional[tuple] = None
        self.center: Optional[tuple] = None
        self.overview_zoom: int = 3
        self.provider: str = "light_all"
        self.status: str = "idle"
        self.error: Optional[str] = None
        self.progress: float = 0.0
        self.required_tiles: int = 0
        self.loaded_tiles: int = 0
        self.overview_image: Any = None

    # ── mutation (worker thread) ──────────────────────────────────────

    def reset(self, provider: str, generation: int) -> None:
        with self._lock:
            self.generation_id = generation
            self.provider = provider
            self.status = "preparing"
            self.error = None
            self.progress = 0.0
            self.required_tiles = 0
            self.loaded_tiles = 0
            self.overview_image = None

    def set_geometry(
        self, gps_source: str, gps_track: list,
        bounds, center, overview_zoom: int, required_tiles: int,
        generation: int | None = None,
    ) -> None:
        with self._lock:
            if generation is not None and generation != self.generation_id:
                return  # stale job — ignore
            self.gps_source = gps_source
            self.gps_track = gps_track
            self.bounds = bounds
            self.center = center
            self.overview_zoom = overview_zoom
            self.required_tiles = required_tiles

    def set_progress(self, loaded: int, required: int, generation: int | None = None) -> None:
        with self._lock:
            if generation is not None and generation != self.generation_id:
                return  # stale job — ignore
            self.loaded_tiles = loaded
            self.required_tiles = required if required > 0 else 0
            self.progress = (
                min(1.0, loaded / required) if required > 0 else 0.0
            )

    def set_ready(self, overview_image: Any = None, generation: int | None = None) -> None:
        with self._lock:
            if generation is not None and generation != self.generation_id:
                return  # stale job — must not overwrite the newer result
            self.status = "ready"
            self.progress = 1.0
            self.loaded_tiles = self.required_tiles
            self.overview_image = overview_image

    def set_error(self, message: str, generation: int | None = None) -> None:
        with self._lock:
            if generation is not None and generation != self.generation_id:
                return  # stale job — ignore
            self.status = "error"
            self.error = str(message)

    def cancel(self) -> None:
        with self._lock:
            self.status = "cancelled"

    # ── read (GUI thread) ─────────────────────────────────────────────

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "generation_id": self.generation_id,
                "gps_source": self.gps_source,
                "gps_track": self.gps_track,
                "bounds": self.bounds,
                "center": self.center,
                "overview_zoom": self.overview_zoom,
                "provider": self.provider,
                "status": self.status,
                "error": self.error,
                "progress": self.progress,
                "required_tiles": self.required_tiles,
                "loaded_tiles": self.loaded_tiles,
                "overview_image": self.overview_image,
            }

    def is_ready(self, provider: str) -> bool:
        with self._lock:
            return (
                self.status == "ready"
                and self.provider == provider
                and self.required_tiles > 0
            )

    def is_preparing(self, provider: str) -> bool:
        with self._lock:
            return (
                self.status in ("preparing", "idle")
                and self.provider == provider
            )
