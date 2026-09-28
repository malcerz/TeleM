"""MapBackgroundPrefetchManager — project-level background tile prefetch for TeleM.

Ensures heavy map tile downloading happens in the background during normal
project editing/previewing, BEFORE the user clicks "Render", while maintaining
strict correctness, rate-limits, and non-blocking GUI responsiveness.
"""

from __future__ import annotations

import csv
import threading
import time
from pathlib import Path
from typing import Any, Callable, Optional

try:
    from src.indicators.moving_map import calculate_required_map_tiles
except ImportError:
    def calculate_required_map_tiles(*args: Any, **kwargs: Any) -> tuple[set[tuple[int, int, int]], str, int, int, int, tuple]:
        return set(), "", 0, 0, 0, ()

from src.moving_map import _download_tile_raw, get_shared_tile_cache


class MapPrefetchJob:
    """Worker task downloading required map tiles for a single generation."""

    def __init__(
        self,
        generation: int,
        cache_key: tuple,
        needed_tiles: list[tuple[int, int, int]],
        map_style: str,
        cancel_event: threading.Event,
        progress_cb: Optional[Callable[[int, int, str], None]] = None,
        done_cb: Optional[Callable[[bool, str, int, int, int], None]] = None,
        event_logger: Optional[Callable[[str, dict[str, Any]], None]] = None,
    ) -> None:
        self.generation = generation
        self.cache_key = cache_key
        self.needed_tiles = needed_tiles
        self.map_style = map_style
        self.cancel_event = cancel_event
        self.progress_cb = progress_cb
        self.done_cb = done_cb
        self.event_logger = event_logger

        self.thread: Optional[threading.Thread] = None
        self.t_start: float = 0.0
        self.t_end: float = 0.0
        self.downloaded_count: int = 0
        self.already_cached_count: int = 0
        self.total_required: int = len(needed_tiles)
        self.cancelled: bool = False
        self.completed: bool = False

    def start(self) -> None:
        self.thread = threading.Thread(
            target=self._run,
            name=f"TeleM-MapPrefetch-Gen{self.generation}",
            daemon=True,
        )
        self.t_start = time.perf_counter()
        self.thread.start()

    def cancel(self) -> None:
        self.cancelled = True
        self.cancel_event.set()

    def is_alive(self) -> bool:
        return self.thread is not None and self.thread.is_alive()

    def _run(self) -> None:
        t0 = time.perf_counter()
        cache = get_shared_tile_cache()
        style = self.map_style
        total = self.total_required

        if self.event_logger:
            self.event_logger("prefetch_job_start", {
                "generation": self.generation,
                "total": total,
                "style": style,
            })

        # Initial check to count how many are already present
        missing: list[tuple[int, int, int]] = []
        cached = 0
        for z, x, y in self.needed_tiles:
            if cache.has(z, x, y, style):
                cached += 1
            else:
                missing.append((z, x, y))

        self.already_cached_count = cached
        if self.progress_cb:
            self.progress_cb(cached, total, f"Mapa: przygotowywanie {cached}/{total}")

        if not missing:
            # All tiles already cached!
            self.completed = True
            self.t_end = time.perf_counter()
            if self.event_logger:
                self.event_logger("prefetch_job_complete", {
                    "generation": self.generation,
                    "total": total,
                    "downloaded": 0,
                    "duration_s": self.t_end - self.t_start,
                    "cache_hit": True,
                })
            if self.done_cb:
                self.done_cb(True, "Mapa: gotowa", total, cached, 0)
            return

        downloaded = 0
        for z, x, y in missing:
            if self.cancel_event.is_set() or self.cancelled:
                self.cancelled = True
                break

            # Check again in case preview or another thread cached it
            if cache.has(z, x, y, style):
                cached += 1
                if self.progress_cb:
                    self.progress_cb(cached + downloaded, total, f"Mapa: przygotowywanie {cached + downloaded}/{total}")
                continue

            # Download single tile with fair-use rate limiting
            data = _download_tile_raw(z, x, y, style)
            if self.cancel_event.is_set() or self.cancelled:
                self.cancelled = True
                break

            if data:
                cache.put(z, x, y, style, data)
                downloaded += 1
                self.downloaded_count = downloaded

            if self.progress_cb:
                cur = cached + downloaded
                self.progress_cb(cur, total, f"Mapa: przygotowywanie {cur}/{total}")

        self.t_end = time.perf_counter()
        dur = self.t_end - self.t_start

        if self.cancelled:
            if self.event_logger:
                self.event_logger("prefetch_job_cancelled", {
                    "generation": self.generation,
                    "downloaded": downloaded,
                    "duration_s": dur,
                })
            if self.done_cb:
                self.done_cb(False, "Anulowano", total, cached + downloaded, downloaded)
        else:
            self.completed = True
            if self.event_logger:
                self.event_logger("prefetch_job_complete", {
                    "generation": self.generation,
                    "total": total,
                    "downloaded": downloaded,
                    "duration_s": dur,
                    "cache_hit": (downloaded == 0),
                })
            if self.done_cb:
                self.done_cb(True, "Mapa: gotowa", total, cached + downloaded, downloaded)


class MapBackgroundPrefetchManager:
    """Singleton managing project-level background map prefetch tasks."""

    _instance: Optional["MapBackgroundPrefetchManager"] = None
    _lock = threading.Lock()

    def __init__(self) -> None:
        self._current_generation: int = 0
        self._current_cache_key: Optional[tuple] = None
        self._active_job: Optional[MapPrefetchJob] = None
        self._job_lock = threading.Lock()

        self._status_text: str = ""
        self._required_tiles: int = 0
        self._cached_tiles: int = 0
        self._missing_tiles: int = 0
        self._is_active: bool = False

        self._duplicate_tile_requests: int = 0
        self._total_jobs_started: int = 0
        self._obsolete_tiles_skipped: int = 0

        self._log_dir = Path("scratch/amd_map_background_prefetch")
        self._log_dir.mkdir(parents=True, exist_ok=True)
        self._events_csv = self._log_dir / "prefetch_events.csv"
        self._timeline_csv = self._log_dir / "prefetch_timeline.csv"
        self._init_csvs()

        self._on_status_change: Optional[Callable[[str], None]] = None
        self._on_progress_change: Optional[Callable[[int, int], None]] = None

    @classmethod
    def get_instance(cls) -> "MapBackgroundPrefetchManager":
        with cls._lock:
            if cls._instance is None:
                cls._instance = MapBackgroundPrefetchManager()
            return cls._instance

    def _init_csvs(self) -> None:
        if not self._events_csv.exists():
            with self._events_csv.open("w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(["timestamp", "event", "generation", "cur", "total", "text", "notes"])
        if not self._timeline_csv.exists():
            with self._timeline_csv.open("w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(["stage", "t_start", "t_end", "duration_ms", "generation", "notes"])

    def set_callbacks(
        self,
        on_status: Optional[Callable[[str], None]] = None,
        on_progress: Optional[Callable[[int, int], None]] = None,
    ) -> None:
        self._on_status_change = on_status
        self._on_progress_change = on_progress

    def _log_event(self, event: str, data: dict[str, Any]) -> None:
        now = time.time()
        gen = data.get("generation", self._current_generation)
        cur = data.get("cur", data.get("cached", 0))
        tot = data.get("total", self._required_tiles)
        txt = data.get("text", self._status_text)
        notes = str({k: v for k, v in data.items() if k not in ("generation", "cur", "total", "text")})
        try:
            with self._events_csv.open("a", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow([f"{now:.4f}", event, gen, cur, tot, txt, notes])
        except Exception:
            pass

    def schedule_prefetch(
        self,
        gps_track: list | None,
        layout: dict | None,
        canvas_w: int = 3840,
        canvas_h: int = 2160,
        key: str = "track_map",
        reason: str = "",
    ) -> bool:
        """Schedule or update background map prefetch.

        Returns True if a new worker was started, False if reused/noop.
        """
        if not gps_track or len(gps_track) < 2 or not layout or not isinstance(layout, dict):
            self.cancel_current(reason="no_data")
            self._update_status("")
            return False

        cfg = layout.get("indicators", {}).get(key, {})
        if not cfg or not cfg.get("enabled", True):
            self.cancel_current(reason="map_disabled")
            self._update_status("")
            return False

        t0 = time.perf_counter()
        needed, map_style, effective_zoom, margin, render_size, cache_key = calculate_required_map_tiles(
            canvas_w, canvas_h, layout, key, gps_track
        )
        calc_ms = (time.perf_counter() - t0) * 1000.0

        if not needed:
            self.cancel_current(reason="empty_tiles")
            self._update_status("")
            return False

        needed_list = sorted(list(needed))
        total_required = len(needed_list)

        with self._job_lock:
            # If an identical cache key is already running or completed, don't duplicate!
            if self._active_job is not None and self._active_job.is_alive():
                if self._current_cache_key == cache_key:
                    print(f"[MapPrefetch] Generation {self._current_generation} already running for key (reason={reason})", flush=True)
                    return False
                else:
                    # Cancel obsolete job
                    print(f"[MapPrefetch] Superseding generation {self._current_generation} with new key (reason={reason})", flush=True)
                    self._active_job.cancel()
                    self._obsolete_tiles_skipped += max(0, self._active_job.total_required - self._active_job.downloaded_count)

            self._current_generation += 1
            gen = self._current_generation
            self._current_cache_key = cache_key
            self._required_tiles = total_required

            # Quick check if all tiles already exist in SQLite
            cache = get_shared_tile_cache()
            cached_now = sum(1 for z, x, y in needed_list if cache.has(z, x, y, map_style))
            self._cached_tiles = cached_now
            self._missing_tiles = total_required - cached_now

            self._log_event("schedule", {
                "generation": gen,
                "reason": reason,
                "required": total_required,
                "cached": cached_now,
                "missing": self._missing_tiles,
                "calc_ms": calc_ms,
            })

            if self._missing_tiles == 0:
                self._is_active = False
                self._update_status("Mapa: gotowa")
                if self._on_progress_change:
                    try:
                        self._on_progress_change(total_required, total_required)
                    except Exception:
                        pass
                print(f"[MapPrefetch] Gen {gen} 100% warm in cache ({total_required}/{total_required} tiles ready)", flush=True)
                return False

            cancel_event = threading.Event()

            def _on_job_progress(cur: int, tot: int, text: str) -> None:
                if gen != self._current_generation:
                    return
                self._cached_tiles = cur
                self._missing_tiles = tot - cur
                self._update_status(text)
                if self._on_progress_change:
                    try:
                        self._on_progress_change(cur, tot)
                    except Exception:
                        pass

            def _on_job_done(success: bool, text: str, tot: int, cached: int, downloaded: int) -> None:
                if gen != self._current_generation:
                    return
                self._is_active = False
                self._cached_tiles = cached
                self._missing_tiles = tot - cached
                if success:
                    self._update_status("Mapa: gotowa")
                    if self._on_progress_change:
                        try:
                            self._on_progress_change(tot, tot)
                        except Exception:
                            pass
                else:
                    self._update_status(text)

            job = MapPrefetchJob(
                generation=gen,
                cache_key=cache_key,
                needed_tiles=needed_list,
                map_style=map_style,
                cancel_event=cancel_event,
                progress_cb=_on_job_progress,
                done_cb=_on_job_done,
                event_logger=self._log_event,
            )
            self._active_job = job
            self._is_active = True
            self._total_jobs_started += 1
            self._update_status(f"Mapa: przygotowywanie {cached_now}/{total_required}")
            job.start()
            print(f"[MapPrefetch] Started Gen {gen} ({cached_now}/{total_required} ready, {self._missing_tiles} to download, reason={reason})", flush=True)
            return True

    def cancel_current(self, reason: str = "") -> None:
        with self._job_lock:
            if self._active_job is not None and self._active_job.is_alive():
                print(f"[MapPrefetch] Cancelling generation {self._current_generation} (reason={reason})", flush=True)
                self._active_job.cancel()
                self._active_job = None
            self._is_active = False

    def pause_or_cancel_for_render(self) -> dict[str, Any]:
        """Cancel background prefetch gracefully prior to render to ensure 0 duplicate downloads."""
        with self._job_lock:
            active_before = (self._active_job is not None and self._active_job.is_alive())
            if active_before:
                self._active_job.cancel()
                self._active_job = None
            self._is_active = False
            return {
                "active_before": active_before,
                "required": self._required_tiles,
                "cached": self._cached_tiles,
                "missing": self._missing_tiles,
                "generation": self._current_generation,
            }

    def _update_status(self, text: str) -> None:
        self._status_text = text
        if self._on_status_change:
            try:
                self._on_status_change(text)
            except Exception:
                pass

    def get_status(
        self,
        layout: dict | None = None,
        gps_track: list | None = None,
        canvas_w: int = 3840,
        canvas_h: int = 2160,
        key: str = "track_map",
    ) -> dict[str, Any]:
        """Return current status snapshot."""
        with self._job_lock:
            active = (self._active_job is not None and self._active_job.is_alive())
            # If layout/gps_track provided, compute up-to-date counts from disk cache
            req = self._required_tiles
            cached = self._cached_tiles
            missing = self._missing_tiles
            if layout and gps_track and len(gps_track) >= 2:
                needed, map_style, _, _, _, _ = calculate_required_map_tiles(
                    canvas_w, canvas_h, layout, key, gps_track
                )
                if needed:
                    req = len(needed)
                    cache = get_shared_tile_cache()
                    cached = sum(1 for z, x, y in needed if cache.has(z, x, y, map_style))
                    missing = req - cached

            return {
                "required_tiles": req,
                "cached_tiles": cached,
                "missing_tiles": missing,
                "is_active": active,
                "active_prefetch_job_count": 1 if active else 0,
                "duplicate_tile_request_count": self._duplicate_tile_requests,
                "generation": self._current_generation,
                "status_text": self._status_text,
                "obsolete_tiles_skipped": self._obsolete_tiles_skipped,
            }
