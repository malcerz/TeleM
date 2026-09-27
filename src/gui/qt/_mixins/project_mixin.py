"""Mixin for handling project loading, files selection, and telemetry parsing.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import threading
import time as _time
from datetime import datetime, timezone
from pathlib import Path

from PySide6.QtCore import QTimer, QUrl
from PIL import Image

from src.gui.indicator_schemas import BUILTIN_FIELDS
from src.gui.layout_manager import normalize_layout
from src.gui.qt.models import normalize_indicator_decimal_defaults
from src.multifile import build_timeline_from_paths, format_timeline_diagnostics, timeline_absolute_end
from src.telemetry_processed_cache import (
    apply_processed_cache,
    processed_cache_path,
    read_processed_cache,
    write_processed_cache,
)
from src.telemetry_extract import ensure_records_list, load_json_with_fallback
from src.video_helpers import (
    clear_capture_cache,
    extract_frame,
    ffprobe_stream_info,
    find_executable,
    parse_fps,
)


def _canonical_project_video_paths(paths: list[str | Path]) -> list[Path]:
    """Filter and return canonical project video paths preserving explicit order."""
    out: list[Path] = []
    for p in paths:
        path = Path(p)
        if path.name.lower() in ("output_h265.mp4", "output.mp4"):
            continue
        out.append(path)
    return out


def _map_provider_from_layout(layout: dict) -> str:

    """Return the saved map provider used for the initial preload job."""
    return str(
        (layout or {}).get("indicators", {})
        .get("track_map", {})
        .get("map_style", "light_all")
        or "light_all"
    )


def _profile_load_stage(
    stage: str,
    started: float,
    input_path: Path | None = None,
    records: int | None = None,
) -> None:
    """Emit one compact, ASCII-safe loading profile line per major stage."""
    try:
        thread = threading.current_thread()
        size = input_path.stat().st_size if input_path and input_path.exists() else None
        fields = [
            f"stage={stage}",
            f"elapsed_ms={(_time.perf_counter() - started) * 1000.0:.2f}",
            f"thread={thread.name}/{thread.ident}",
        ]
        if size is not None:
            fields.append(f"input_bytes={size}")
        if records is not None:
            fields.append(f"records={records}")
        print("[LoadProfile] " + " ".join(fields), flush=True)
    except Exception:
        pass


def _profile_json_stage(stage: str, elapsed: float, path: Path) -> None:
    """Adapter for ``load_json_with_fallback`` read/parse callbacks."""
    try:
        size = path.stat().st_size if path.exists() else None
        suffix = f" input_bytes={size}" if size is not None else ""
        thread = threading.current_thread()
        print(
            f"[LoadProfile] stage={stage} elapsed_ms={elapsed * 1000.0:.2f} "
            f"thread={thread.name}/{thread.ident}{suffix}",
            flush=True,
        )
    except Exception:
        pass


def _profile_gpmf_substage(
    stage: str, elapsed: float, input_count: int, output_count: int,
) -> None:
    try:
        thread = threading.current_thread()
        print(
            f"[LoadProfile:GPMF] stage={stage} elapsed_ms={elapsed * 1000.0:.2f} "
            f"input_count={input_count} output_count={output_count} "
            f"thread={thread.name}/{thread.ident}",
            flush=True,
        )
    except Exception:
        pass

try:
    from src.telemetry_gpmf_new import gpmf_to_exiftool_json
    _GPMF_AVAILABLE = True
except ImportError:
    _GPMF_AVAILABLE = False

try:
    from telemetry_gpx import find_gpx_for_video, parse_gpx as _parse_gpx, process_gpx
    _GPX_AVAILABLE = True
except ImportError:
    _GPX_AVAILABLE = False
    _parse_gpx = None

try:
    from telemetry_fit import find_fit_for_video, parse_fit as _parse_fit, process_fit
    _FIT_AVAILABLE = True
except ImportError:
    _FIT_AVAILABLE = False
    _parse_fit = None

try:
    from PySide6.QtMultimedia import QMediaPlayer
    _QT_MULTIMEDIA_AVAILABLE = True
except ImportError:
    _QT_MULTIMEDIA_AVAILABLE = False


GPMF_CACHE_VERSION = 5


def _gpmf_cache_metadata_path(cache_path: Path) -> Path:
    """Return the sidecar path kept separate from telemetry JSON consumers."""
    return cache_path.with_name(f"{cache_path.name}.meta.json")


def _atomic_write_json(path: Path, value: object) -> None:
    """Write JSON and replace the destination atomically."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent,
            prefix=f".{path.name}.", suffix=".tmp", delete=False,
        ) as handle:
            temp_path = Path(handle.name)
            json.dump(value, handle, indent=2, ensure_ascii=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
    finally:
        if temp_path is not None and temp_path.exists():
            temp_path.unlink()


def _write_gpmf_cache(
    cache_path: Path,
    source_path: Path,
    data: object,
    generator: str,
) -> None:
    """Atomically write telemetry JSON and its source/version contract."""
    source_stat = source_path.stat()
    metadata = {
        "_telem_cache": {
            "version": GPMF_CACHE_VERSION,
            "source_file": str(source_path),
            "source_size": source_stat.st_size,
            "source_mtime_ns": source_stat.st_mtime_ns,
            "generator": generator.lower(),
        }
    }
    _atomic_write_json(cache_path, data)
    _atomic_write_json(_gpmf_cache_metadata_path(cache_path), metadata)


def _load_valid_gpmf_cache(
    source_path: Path,
    cache_path: Path,
) -> tuple[object | None, str | None]:
    """Load cache only when its version and source fingerprint are proven."""
    if not cache_path.exists():
        return None, "cache_missing"

    metadata_path = _gpmf_cache_metadata_path(cache_path)
    if not metadata_path.exists():
        return None, "legacy_cache_no_version"

    try:
        metadata = load_json_with_fallback(
            metadata_path, profile_cb=_profile_json_stage,
        )
    except Exception:
        return None, "invalid_metadata"

    contract = metadata.get("_telem_cache") if isinstance(metadata, dict) else None
    required = ("version", "source_size", "source_mtime_ns", "generator")
    if not isinstance(contract, dict) or any(key not in contract for key in required):
        return None, "missing_metadata"
    if contract["version"] != GPMF_CACHE_VERSION:
        return None, "cache_version_mismatch"

    try:
        source_stat = source_path.stat()
    except OSError:
        return None, "source_missing"
    if contract["source_size"] != source_stat.st_size:
        return None, "source_size_changed"
    if contract["source_mtime_ns"] != source_stat.st_mtime_ns:
        return None, "source_mtime_changed"

    try:
        data = load_json_with_fallback(
            cache_path, profile_cb=_profile_json_stage,
        )
    except Exception:
        return None, "invalid_json"
    if not data:
        return None, "invalid_payload"
    return data, None


class ProjectMixin:
    def _on_files_selected(
        self,
        video_paths: list[str],
        gpx_path: str,
        fit_path: str,
    ) -> None:
        """Użytkownik wybrał pliki w zakładce Wczytywanie."""
        self._clear_caches()
        # Suppress decoder callbacks until an explicitly selected FIT has
        # loaded and its presentation plans have been warmed.
        self._preview_telemetry_loading = bool(fit_path)
        self.signals.sig_progress.emit(0, "Wczytywanie wideo...")

        def bg_load() -> None:
            try:
                effective_fit_path = fit_path
                effective_gpx_path = gpx_path
                self.video_paths = [Path(p) for p in video_paths]
                self.video_path = self.video_paths[0]

                # Wykryj narzędzia
                ffprobe_exe = find_executable(
                    str(self.ffprobe_path),
                    [str(self.base_dir / "ffprobe.exe"), "ffprobe.exe"],
                )
                ffmpeg_exe = find_executable(
                    "ffmpeg",
                    [str(self.base_dir / "ffmpeg.exe"), "ffmpeg.exe"],
                )
                if not ffprobe_exe or not ffmpeg_exe:
                    self.signals.sig_error.emit(
                        "Nie znaleziono ffprobe.exe / ffmpeg.exe"
                    )
                    return
                self.ffprobe_exe = ffprobe_exe
                self.ffmpeg_exe = ffmpeg_exe

                # Ustaw źródło QMediaPlayer (GPU-accelerated preview)
                if _QT_MULTIMEDIA_AVAILABLE and hasattr(self, "media_player"):
                    self.media_player.setSource(
                        QUrl.fromLocalFile(str(self.video_path))
                    )

                if self.is_using_mpv():
                    self.mpv_player.play(str(self.video_path))
                    self.mpv_player.pause = True

                # Analiza wideo
                self.signals.sig_progress.emit(15, "Analiza strumienia...")
                info = ffprobe_stream_info(ffprobe_exe, self.video_paths[0])
                streams = info.get("streams", [])
                w = int(streams[0].get("width", 1920)) if streams else 1920
                h = int(streams[0].get("height", 1080)) if streams else 1080
                self.video_width = w
                self.video_height = h
                self.video_info = {"width": w, "height": h, "fps": self.fps if hasattr(self, "fps") else 30.0}
                self.fps = parse_fps(
                    streams[0].get("avg_frame_rate")
                    or streams[0].get("r_frame_rate")
                ) if streams else 30.0
                self.video_info["fps"] = self.fps
                total_dur = sum(
                    float(
                        ffprobe_stream_info(ffprobe_exe, p)
                        .get("format", {})
                        .get("duration", 0)
                        or 0
                    )
                    for p in self.video_paths
                )
                self.video_duration_s = total_dur

                self.signals.sig_video_info_ready.emit(
                    f"{w}x{h} @ {self.fps:.1f} fps, {total_dur:.1f}s"
                )
                # FIX A: do NOT emit sig_video_duration_ready here.
                # format.duration and player.duration() are source-local/provisional
                # values.  The canonical project_duration comes from VideoTimeline
                # (video-stream frame-count based).  Emission is deferred to after
                # build_timeline_from_paths below; total_dur is only a fallback used
                # if timeline build fails.

                # Layout — priorytet:
                # 1. Istniejący layout roboczy powiązany z filmem (video.layout.json)
                # 2. Startowy preset użytkownika jeśli skonfigurowany
                # 3. Szablon bazowy def_layout.json
                proj_layout = Path(self.video_paths[0]).with_suffix(".layout.json")
                if proj_layout.exists():
                    try:
                        self.layout = json.loads(proj_layout.read_text(encoding="utf-8"))
                        normalize_indicator_decimal_defaults(self.layout)
                        print(f"[ProjectLayout] Wczytano istniejący layout filmu z {proj_layout}", flush=True)
                    except Exception as e:
                        print(f"[ProjectLayout] Błąd odczytu {proj_layout}: {e}", flush=True)
                        proj_layout = None
                if not proj_layout or not proj_layout.exists():
                    preset_path = self._startup_preset_path or self.layout.get("_startup_preset", "")
                    if preset_path and Path(preset_path).exists():
                        self.layout = json.loads(
                            Path(preset_path).read_text(encoding="utf-8")
                        )
                        normalize_indicator_decimal_defaults(self.layout)
                    else:
                        def_layout = self.base_dir / "def_layout.json"
                        self.layout = normalize_layout(def_layout, w, h)
                self._selected_stream_key = ""
                self.src_img = Image.new("RGB", (w, h), (0, 0, 0))

                # ── Map preload (ETAP MAP PRELOAD) — parallel with GPMF ──
                # Parse FIT/GPX GPS EARLY (fast) so the coarse overview map can
                # start downloading tiles while GPMF/JSON is still parsing.
                # The parsed records are REUSED later (no double parsing).
                self._map_preload_fit_records = None
                self._map_preload_gpx_points = None
                map_gps = None
                map_source = None
                if not effective_fit_path and not effective_gpx_path and self.video_paths:
                    try:
                        from src.multifile import probe_clip_time_interval
                        from telemetry_fit import find_best_fit_match
                        intervals = []
                        for vp in self.video_paths:
                            start_dt, end_dt, dur_s, conf = probe_clip_time_interval(vp)
                            if start_dt is not None and end_dt is not None:
                                intervals.append((start_dt, end_dt, dur_s, conf))
                        if intervals:
                            matched_fit, diag = find_best_fit_match(intervals, Path(self.video_paths[0]).parent)
                            if matched_fit is not None:
                                effective_fit_path = str(matched_fit)
                                self.fit_path = Path(effective_fit_path)
                    except Exception as e:
                        print(f"[AutoFIT] Error in project auto-fit: {e}", flush=True)
                if effective_fit_path and _FIT_AVAILABLE and _parse_fit is not None:
                    try:
                        records = _parse_fit(effective_fit_path)
                        if records:
                            self._map_preload_fit_records = records
                            map_gps = [
                                (r["timestamp"], r["lat"], r["lon"])
                                for r in records
                                if r.get("lat") is not None and r.get("lon") is not None
                            ]
                            map_source = "fit"
                            print(
                                f"[MapPreload] start source=FIT points={len(map_gps)}",
                                flush=True,
                            )
                    except Exception as exc:
                        print(f"[MapPreload] FIT preparse failed: {exc}", flush=True)
                if map_gps is None and effective_gpx_path and _GPX_AVAILABLE and _parse_gpx is not None:
                    try:
                        points = _parse_gpx(effective_gpx_path)
                        if points:
                            self._map_preload_gpx_points = points
                            map_gps = [
                                (p[0], p[1], p[2])
                                for p in points
                                if p[1] is not None and p[2] is not None
                            ]
                            map_source = "gpx"
                            print(
                                f"[MapPreload] start source=GPX points={len(map_gps)}",
                                flush=True,
                            )
                    except Exception as exc:
                        print(f"[MapPreload] GPX preparse failed: {exc}", flush=True)
                # The saved/default layout is authoritative for the map
                # provider.  Starting preload with the hard-coded Standard
                # provider makes a saved Satellite map fail the async
                # renderer's provider gate and remain on the placeholder.
                map_provider = _map_provider_from_layout(self.layout)
                if map_gps is not None:
                    self._start_map_preload(
                        map_gps, map_source, provider=map_provider,
                    )

                # Wczytaj/wygeneruj metadane (GPMF — heavy, runs in parallel
                # with the map preload thread started above)
                self.signals.sig_progress.emit(30, "Sprawdzanie metadanych...")
                self._load_or_generate_telemetry()

                # If no FIT/GPX GPS was available, start the map preload from
                # the GPMF GPS track once it exists (fallback contract).
                if map_gps is None and getattr(self.telemetry, "gps_track", None):
                    print(
                        f"[MapPreload] start source=GPMF points={len(self.telemetry.gps_track)}",
                        flush=True,
                    )
                    self._start_map_preload(
                        self.telemetry.gps_track, "gpmf", provider=map_provider,
                    )

                # Wczytaj GPX (jeśli podano) — reuse the preparsed points
                if effective_gpx_path and _GPX_AVAILABLE:
                    self.gpx_path = Path(effective_gpx_path)
                    self.telemetry.load_gpx(
                        self.video_path, self.telemetry.start_dt_utc,
                        manual_path=self.gpx_path,
                        preparsed=self._map_preload_gpx_points,
                    )

                # Wczytaj FIT (jeśli podano) — reuse the preparsed records
                if effective_fit_path and _FIT_AVAILABLE:
                    self.fit_path = Path(effective_fit_path)
                    self.telemetry.load_fit(
                        self.video_path, self.telemetry.start_dt_utc,
                        manual_path=self.fit_path,
                        preparsed=self._map_preload_fit_records,
                    )

                # ── Multi-file timeline (ETAP MULTIFILE) ──────────────────
                # Build the per-clip model + global timeline now that
                # telemetry.start_dt_utc (project absolute start) is final.
                # The timeline maps global_time -> clip -> local -> absolute.
                # For a single clip it reduces exactly to legacy behavior
                # (global_to_absolute(t) == start_dt_utc + t).
                try:
                    timeline = build_timeline_from_paths(
                        self.video_paths,
                        ffmpeg_exe=ffmpeg_exe,
                        ffprobe_exe=ffprobe_exe,
                        base_dt=self.telemetry.start_dt_utc,
                        default_fps=self.fps or 30.0,
                    )
                    self.video_timeline = timeline
                    self.video_clips = list(timeline.clips)
                    self.video_duration_s = timeline.project_duration_s
                    if timeline.clips and timeline.clips[0].absolute_start_dt is not None:
                        proj_start = timeline.clips[0].absolute_start_dt
                        if getattr(self, "telemetry", None) is not None:
                            self.telemetry.start_dt_utc = proj_start
                            self.telemetry._coverage_start = proj_start
                    # Warm global multi-file battery presentation plan
                    try:
                        self.telemetry.timeline = timeline
                        self.telemetry.update_battery_coverage(
                            self.telemetry.start_dt_utc,
                            timeline_absolute_end(timeline),
                            timeline=timeline,
                        )
                    except Exception:
                        pass
                    # FIX A: emit the canonical project duration (video-stream
                    # frame-count based) so the seek bar receives the correct
                    # value.  This replaces the earlier provisional emission of
                    # format.duration sum (which was architecturally wrong even
                    # though numerically only ~0.47 s off for this dataset).
                    self.signals.sig_video_duration_ready.emit(
                        timeline.project_duration_s
                    )
                    print(
                        f"[MultiFile] project_duration={timeline.project_duration_s:.6f} s"
                        f" clip_count={timeline.clip_count} (canonical, emitted to seek bar)",
                        flush=True,
                    )
                    # Full per-clip + gap diagnostics (ETAP 3).
                    for line in format_timeline_diagnostics(timeline):
                        print(line, flush=True)
                    missing = [
                        c.path.name for c in timeline.clips
                        if c.absolute_start_dt is None
                    ]
                    if missing:
                        print(
                            f"[MultiFile] WARNING: no reliable absolute start for "
                            f"{missing}; they are marked "
                            f"timestamp_source=continuous_fallback and "
                            f"FIT/GPMF synchronization may be incorrect.", flush=True,
                        )
                except Exception as exc:
                    print(
                        f"[MultiFile] Timeline build failed, keeping summed "
                        f"duration: {exc}", flush=True,
                    )
                    self.video_timeline = None
                    self.video_clips = []
                    # FIX A fallback: emit provisional total_dur when timeline
                    # build failed (better than no emit at all).
                    self.signals.sig_video_duration_ready.emit(total_dur)
                # The decoder is loaded with clip 0 (first file) at this point.
                self._active_preview_clip_index = 0
                self._pending_seek_ms = None

                # P0-FIX: cut_regions from the layout file are stale IN/OUT
                # boundaries that were incorrectly persisted by a previous
                # version of _save_project_layout.  Loading them would lock
                # scrubbing to the previously-set range and cap the render
                # duration.  Always start a fresh session with no cuts; the
                # RenderTab manages IN/OUT per-session only.
                self._cut_regions = []

                # Zarejestruj pola FIT; clear dynamic availability when the
                # newly selected file has no FIT data.
                self.fit_ext_fields = []
                if self.telemetry.fit_data:
                    fit_keys = self.telemetry.register_fit_fields(
                        self.layout, BUILTIN_FIELDS,
                    )
                    self.fit_ext_fields = list(fit_keys)

                # Odkryj strumienie danych
                self.signals.sig_progress.emit(75, "Przygotowywanie danych...")
                self.signals.sig_progress.emit(80, "Budowa interfejsu...")
                streams = self._discover_data_streams()
                self.signals.sig_data_streams_ready.emit(streams)
                self.signals.sig_progress.emit(85, "Przygotowywanie podglądu...")

                self.signals.sig_progress.emit(90, "Pobieranie klatki...")
                target_w = getattr(self, "_preview_target_w", 960)
                target_h = getattr(self, "_preview_target_h", None)
                if target_h is None or target_h <= 0:
                    target_h = max(1, int(round(target_w * h / w))) if w > 0 else 540

                if self.is_using_mpv():
                    first_frame = Image.new("RGBA", (target_w, target_h), (0, 0, 0, 0))
                elif _QT_MULTIMEDIA_AVAILABLE and hasattr(self, "media_player"):
                    # QMediaPlayer is loaded — first frame will arrive via
                    # _on_video_frame callback (hardware-accelerated).
                    # Use placeholder until then.
                    first_frame = Image.new("RGBA", (target_w, target_h), (0, 0, 0, 0))
                else:
                    clear_capture_cache()
                    first_frame = extract_frame(
                        self.video_paths, 0, ffmpeg_exe, ffprobe_exe, target_w=target_w, preferred_encoder=self.ui.render_tab.cmb_encoder.currentText() if getattr(self, "ui", None) and getattr(self.ui, "render_tab", None) else ""
                    )
                if first_frame:
                    if not self.is_using_mpv():
                        # Skaluj do rozdzielczości podglądu
                        fw, fh = first_frame.size
                        if (fw, fh) != (target_w, target_h):
                            first_frame = first_frame.resize(
                                (target_w, target_h), Image.LANCZOS,
                            )
                    self.src_img = first_frame
                    self.last_src_pil = first_frame
                    self.last_preview_ts = 0.0

                self.signals.sig_progress.emit(95, "Składanie podglądu...")
                self._preview_telemetry_loading = False
                self.refresh_preview_geometry_and_hud()

                # ── Hwdec diagnostics (deferred, needs main thread) ────

                if self.is_using_mpv():
                    # bg_load has no Qt event dispatcher. Request the timer
                    # on the controller's GUI thread through a queued signal.
                    self.signals.sig_schedule_mpv_hwdec_check.emit()

                # ── Auto export filename (CEL 6) ──────────────────────
                try:
                    start_dt = None
                    if getattr(self, "video_timeline", None) and self.video_timeline.clips:
                        start_dt = self.video_timeline.clips[0].absolute_start_dt
                    if start_dt is None and getattr(self, "telemetry", None):
                        start_dt = getattr(self.telemetry, "start_dt_utc", None)
                    if start_dt is not None:
                        from src.video_helpers import generate_auto_export_filename
                        out_dir = Path(self.video_paths[0]).parent if self.video_paths else None
                        fit_data = getattr(self.telemetry, "fit_data", None) if getattr(self, "telemetry", None) else None
                        auto_name = generate_auto_export_filename(
                            start_dt,
                            target_dir=out_dir,
                            fit_data=fit_data,
                            tz_offset_hours=getattr(self, "tz_offset_hours", None),
                        )
                        self.signals.sig_default_export_name_ready.emit(auto_name)
                except Exception as e:
                    print(f"[AutoExportName] Failed to generate default name: {e}", flush=True)

                self.signals.sig_progress.emit(100, "Gotowe")

            except Exception as e:
                import traceback
                traceback.print_exc()
                self._preview_telemetry_loading = False
                self.signals.sig_error.emit(str(e))

        threading.Thread(target=bg_load, daemon=True).start()

    def _schedule_mpv_hwdec_check(self) -> None:
        """Start the MPV diagnostic timer on the GUI thread only."""
        QTimer.singleShot(1500, self._check_mpv_hwdec)

    # ── Map preload (ETAP MAP PRELOAD) ────────────────────────────────────
    # The coarse/overview map is prepared on a background thread, parallel
    # with GPMF parsing.  GPS for the bounds comes from FIT (preferred), GPX,
    # or GPMF — never changing the user-selected source of other indicators.

    def _ensure_map_context(self):
        if getattr(self, "map_context", None) is None:
            from src.gui.map_context import MapContext
            self.map_context = MapContext()
        return self.map_context

    def _start_map_preload(self, gps_track, source: str, provider: str = "light_all") -> None:
        """Start a MapPreload worker on a background thread (non-blocking)."""
        from src.gui.map_preload import MapPreloadWorker
        ctx = self._ensure_map_context()
        if not gps_track or len(gps_track) < 2:
            return
        generation = ctx.generation_id + 1
        ctx.gps_source = source
        ctx.reset(provider=provider, generation=generation)

        def _on_progress(loaded: int, total: int) -> None:
            try:
                self.signals.sig_map_progress.emit(loaded, total)
                self.signals.sig_progress.emit(
                    32, f"Mapa: {loaded}/{total} kafelków",
                )
            except Exception:
                pass

        def _on_done(ok: bool, message: str) -> None:
            try:
                # Marshal to the GUI thread (queued signal) so the preview
                # can refresh with the ready overview map.
                self.signals.sig_map_ready.emit()
                t0 = getattr(self, "_map_preload_t0", {}).get(generation, _time.perf_counter())
                if ok:
                    print(
                        f"[MapPreload] overview ready provider={provider} "
                        f"elapsed={_time.perf_counter() - t0:.2f}s",
                        flush=True,
                    )
                else:
                    print(
                        f"[MapPreload] error provider={provider}: {message}",
                        flush=True,
                    )
            except Exception:
                pass

        # Track start time for diagnostics (keyed by generation).
        if not hasattr(self, "_map_preload_t0"):
            self._map_preload_t0 = {}
        self._map_preload_t0[generation] = _time.perf_counter()

        worker = MapPreloadWorker(
            ctx, list(gps_track), provider=provider, generation=generation,
            done_cb=_on_done, progress_cb=_on_progress,
        )
        self._map_preload_worker = worker
        worker.start()

    def _map_preload_provider_switch(self, provider: str) -> None:
        """Re-run the preload for a different provider/style (Satellite).

        Same MapContext geometry — only the tile provider/cache namespace
        changes; the GPS/FIT data is NOT re-parsed (generation bumps so a
        stale previous job can never overwrite the new result).
        """
        ctx = self._ensure_map_context()
        snap = ctx.snapshot()
        if not snap["gps_track"] or snap["status"] in ("idle", "error"):
            return
        # ASCII-safe arrow: the U+2192 glyph is not encodable on the Windows
        # cp1250 console and would crash the provider switch before it starts.
        print(
            f"[MapPreload] provider {snap.get('provider')} -> {provider} "
            f"generation={ctx.generation_id + 1}",
            flush=True,
        )
        self._start_map_preload(snap["gps_track"], snap.get("gps_source") or "gps", provider=provider)

    def _load_single_clip_telemetry(self, video_path: Path, clip_idx: int = 0, total_clips: int = 1) -> tuple[dict, list]:
        """Wczytaj cache procesowany (.telemetry.npz) lub wygeneruj metadane dla jednego klipu."""
        t0 = _time.perf_counter()
        meta = video_path.with_suffix(".json")
        processed = read_processed_cache(video_path)
        if processed is not None and (processed.get("speed_samples") or processed.get("track_samples")):
            print(
                f"[Telemetry Cache] PROCESSED HIT file="
                f"{processed_cache_path(video_path).name}",
                flush=True,
            )
            data, _ = _load_valid_gpmf_cache(video_path, meta)
            records = ensure_records_list(data) if data else []
            _profile_load_stage("gpmf_decode_ms", t0, video_path, len(records))
            return processed, records

        pct_clip_start = 30 + int(35 * (clip_idx / total_clips))
        pct_clip_end = 30 + int(35 * ((clip_idx + 1) / total_clips))
        clip_span = max(1, pct_clip_end - pct_clip_start)

        def _gpmf_subprogress(phase: str, done: int, tot: int) -> None:
            if phase == "extract":
                p = pct_clip_start + int(0.05 * clip_span)
                msg = f"Analiza GPMF ({clip_idx + 1}/{total_clips}) — ekstrakcja strumienia..."
            elif phase == "parse":
                ratio = (done / tot) if tot > 0 else 0.0
                p = pct_clip_start + int((0.10 + 0.40 * ratio) * clip_span)
                msg = f"Analiza GPMF ({clip_idx + 1}/{total_clips}) — parsowanie {done // 1024}/{tot // 1024} KB ({int(ratio * 100)}%)..."
            elif phase == "convert":
                ratio = (done / tot) if tot > 0 else 0.0
                p = pct_clip_start + int((0.50 + 0.30 * ratio) * clip_span)
                msg = f"Analiza GPMF ({clip_idx + 1}/{total_clips}) — konwersja rekordów ({int(ratio * 100)}%)..."
            else:
                p = pct_clip_start + int(0.85 * clip_span)
                msg = f"Analiza GPMF ({clip_idx + 1}/{total_clips}) — {phase}..."
            try:
                self.signals.sig_progress.emit(min(p, pct_clip_end - 1), msg)
            except Exception:
                pass

        # 1b. Szybka ekstrakcja C++ GPMF bezpośrednio z MP4 (telem_gpmf_native)
        try:
            from src.telemetry_native_gpmf import (
                is_native_gpmf_available,
                extract_gpmf_native,
                populate_telemetry_from_native,
            )
            if is_native_gpmf_available():
                t_native = _time.perf_counter()
                try:
                    self.signals.sig_progress.emit(
                        pct_clip_start + int(0.2 * clip_span),
                        f"Natywna analiza GPMF C++ ({clip_idx + 1}/{total_clips})...",
                    )
                except Exception:
                    pass

                native_data = extract_gpmf_native(video_path)
                if native_data and native_data.get("gps_track"):
                    from src.gui.telemetry_manager import TelemetryDataManager
                    from src.telemetry_extract import (
                        extract_speed_samples, extract_altitude_samples, extract_track_samples,
                        extract_iso_samples, extract_exposure_samples, extract_temperature_samples,
                        smooth_speed_samples, interpolate_value, extract_gps_track,
                        smooth_speed_values, extract_accelerometer_samples, extract_gyroscope_samples
                    )
                    temp_telem = TelemetryDataManager(
                        extract_speed_fn=getattr(self.telemetry, "_extract_speed", None) or extract_speed_samples,
                        extract_altitude_fn=getattr(self.telemetry, "_extract_altitude", None) or extract_altitude_samples,
                        extract_track_fn=getattr(self.telemetry, "_extract_track", None) or extract_track_samples,
                        extract_iso_fn=getattr(self.telemetry, "_extract_iso", None) or extract_iso_samples,
                        extract_exposure_fn=getattr(self.telemetry, "_extract_exposure", None) or extract_exposure_samples,
                        extract_temperature_fn=getattr(self.telemetry, "_extract_temperature", None) or extract_temperature_samples,
                        smooth_fn=getattr(self.telemetry, "_smooth_speed", None) or smooth_speed_samples,
                        interpolate_fn=getattr(self.telemetry, "_interpolate", None) or interpolate_value,
                        extract_gps_track_fn=getattr(self.telemetry, "_extract_gps_track", None) or extract_gps_track,
                        smooth_values_fn=getattr(self.telemetry, "_smooth_values", None) or smooth_speed_values,
                        extract_accelerometer_fn=getattr(self.telemetry, "_extract_accelerometer", None) or extract_accelerometer_samples,
                        extract_gyroscope_fn=getattr(self.telemetry, "_extract_gyroscope", None) or extract_gyroscope_samples,
                    )
                    populate_telemetry_from_native(video_path, native_data, temp_telem)
                    write_processed_cache(video_path, temp_telem)
                    processed = read_processed_cache(video_path)
                    if processed:
                        _profile_load_stage("gpmf_decode_ms", t0, video_path, len(native_data.get("gps_track", [])))
                        print(f"[Telemetry Native] Extracted {video_path.name} in {(_time.perf_counter() - t_native)*1000.0:.1f}ms", flush=True)
                        return processed, []
        except Exception as exc:
            print(f"[Telemetry Native] Fallback to legacy parser: {exc}", flush=True)

        # Sprawdź cache GPMF JSON
        data, cache_reason = _load_valid_gpmf_cache(video_path, meta)
        records = ensure_records_list(data) if data else None
        if not records:
            # Generuj bezpośrednio z GPMF (FFmpeg) lub ExifTool
            t_extract = _time.perf_counter()
            data = None
            method = ""
            if _GPMF_AVAILABLE and self.ffmpeg_exe and self.ffprobe_exe:
                try:
                    data = gpmf_to_exiftool_json(
                        str(video_path), self.ffmpeg_exe, self.ffprobe_exe,
                        progress_cb=_gpmf_subprogress
                    )
                    if data:
                        method = "GPMF"
                except Exception as exc:
                    print(f"[GPMF] Błąd czytania {video_path.name}: {exc}", flush=True)
            if not data:
                exe = find_executable(str(self.exiftool_path), [str(self.base_dir / "exiftool.exe"), "exiftool.exe"])
                if exe:
                    _gpmf_subprogress("ExifTool", 0, 1)
                    proc = subprocess.run([exe, "-ee", "-j", "-G3", str(video_path)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                    if proc.returncode == 0:
                        data = json.loads(proc.stdout)
                        method = "ExifTool"
            if data:
                flat = data[0] if isinstance(data, list) else data
                _write_gpmf_cache(meta, video_path, flat, method)
                records = ensure_records_list([flat])
            _profile_load_stage("gpmf_extract_ms", t_extract, video_path)

        if records:
            from src.gui.telemetry_manager import TelemetryDataManager
            from src.telemetry_extract import (
                extract_speed_samples, extract_altitude_samples, extract_track_samples,
                extract_iso_samples, extract_exposure_samples, extract_temperature_samples,
                smooth_speed_samples, interpolate_value, extract_gps_track,
                smooth_speed_values, extract_accelerometer_samples, extract_gyroscope_samples
            )
            temp_telem = TelemetryDataManager(
                extract_speed_fn=getattr(self.telemetry, "_extract_speed", None) or extract_speed_samples,
                extract_altitude_fn=getattr(self.telemetry, "_extract_altitude", None) or extract_altitude_samples,
                extract_track_fn=getattr(self.telemetry, "_extract_track", None) or extract_track_samples,
                extract_iso_fn=getattr(self.telemetry, "_extract_iso", None) or extract_iso_samples,
                extract_exposure_fn=getattr(self.telemetry, "_extract_exposure", None) or extract_exposure_samples,
                extract_temperature_fn=getattr(self.telemetry, "_extract_temperature", None) or extract_temperature_samples,
                smooth_fn=getattr(self.telemetry, "_smooth_speed", None) or smooth_speed_samples,
                interpolate_fn=getattr(self.telemetry, "_interpolate", None) or interpolate_value,
                extract_gps_track_fn=getattr(self.telemetry, "_extract_gps_track", None) or extract_gps_track,
                smooth_values_fn=getattr(self.telemetry, "_smooth_values", None) or smooth_speed_values,
                extract_accelerometer_fn=getattr(self.telemetry, "_extract_accelerometer", None) or extract_accelerometer_samples,
                extract_gyroscope_fn=getattr(self.telemetry, "_extract_gyroscope", None) or extract_gyroscope_samples,
            )
            temp_telem.records = records
            flat_dict = data[0] if (data and isinstance(data, list)) else (data if isinstance(data, dict) else None)
            temp_telem.load_gpmf_from_exiftool(video_path, flat=flat_dict)

            def _records_subprogress(stage, done, tot, label):
                p = pct_clip_start + int(0.80 * clip_span)
                msg = f"Analiza GPMF ({clip_idx + 1}/{total_clips}) — {label or stage}..."
                try:
                    self.signals.sig_progress.emit(min(p, pct_clip_end - 1), msg)
                except Exception:
                    pass

            temp_telem.load_gpmf_records(records, profile_cb=_profile_gpmf_substage, progress_cb=_records_subprogress)
            temp_telem.load_gps_track(records, profile_cb=_profile_gpmf_substage)

            try:
                self.signals.sig_progress.emit(pct_clip_start + int(0.95 * clip_span), f"Analiza GPMF ({clip_idx + 1}/{total_clips}) — zapis cache...")
            except Exception:
                pass

            write_processed_cache(video_path, temp_telem)
            processed = read_processed_cache(video_path)
            if processed:
                _profile_load_stage("gpmf_decode_ms", t0, video_path, len(records))
                return processed, records

        return {}, records or []

    def _merge_clip_telemetry(self, fields: dict, records: list | None) -> None:
        """Połącz próbki telemetrii kolejnego klipu z self.telemetry."""
        if not fields:
            return
        t0 = _time.perf_counter()
        # 1. Dystans kumulacyjny (track_samples)
        new_track = fields.get("track_samples") or []
        if new_track:
            last_dist = self.telemetry.track_samples[-1][1] if getattr(self.telemetry, "track_samples", None) else 0.0
            first_new = new_track[0][1] if new_track else 0.0
            offset = last_dist if first_new < last_dist - 10.0 else 0.0
            merged_track = [(t, d + offset) for t, d in new_track]
            if not self.telemetry.track_samples:
                self.telemetry.track_samples = list(merged_track)
            else:
                self.telemetry.track_samples.extend(merged_track)

        # 2. Serie próbek z czasem bezwzględnym
        sample_attrs = (
            "speed_samples", "alt_samples", "iso_samples", "exposure_samples",
            "temperature_samples", "slope_samples", "accelerometer_samples",
            "gyroscope_samples", "heading_samples", "gps_track",
        )
        for attr in sample_attrs:
            incoming = fields.get(attr) or []
            if incoming:
                curr = getattr(self.telemetry, attr, None)
                if curr is None:
                    setattr(self.telemetry, attr, list(incoming))
                else:
                    curr.extend(incoming)
                    try:
                        # Cache-backed IMU series remain NumPy-backed after
                        # concatenation.  A generic ``key=lambda`` forces
                        # LazySampleList to create every datetime/tuple just
                        # to sort an already numeric timestamp column.
                        sort_by_timestamp = getattr(curr, "sort_by_timestamp", None)
                        if callable(sort_by_timestamp):
                            sort_by_timestamp()
                        else:
                            curr.sort(key=lambda x: x[0])
                    except Exception:
                        pass

        # 3. Rekordy
        if records:
            if self.telemetry.records is None:
                self.telemetry.records = list(records)
            else:
                self.telemetry.records.extend(records)
        _profile_load_stage("telemetry_merge_ms", t0)

    def _load_or_generate_telemetry(self) -> None:
        """Wczytaj lub wygeneruj telemetrię dla wszystkich klipów projektu."""
        if not self.video_path:
            return
        load_start = _time.perf_counter()
        paths = getattr(self, "video_paths", None) or [self.video_path]
        total_clips = len(paths)
        print(f"[MultiFile Load] Rozpoczynanie wczytywania telemetrii dla {total_clips} klip(ów)...", flush=True)

        for idx, p in enumerate(paths):
            pct_clip_start = 30 + int(35 * (idx / total_clips))
            self.signals.sig_progress.emit(pct_clip_start, f"Analiza GPMF ({idx + 1}/{total_clips})...")
            t_clip_0 = _time.perf_counter()
            fields, records = self._load_single_clip_telemetry(p, clip_idx=idx, total_clips=total_clips)
            _profile_load_stage(f"clip_load_{idx + 1}_ms", t_clip_0, p, len(records) if records else 0)

            if idx == 0:
                if fields:
                    apply_processed_cache(self.telemetry, fields)
                self.telemetry.records = records or []
                self.meta_path = p.with_suffix(".json")
            else:
                self._merge_clip_telemetry(fields, records)

        if getattr(self.telemetry, "start_dt_utc", None) is None and self.ffprobe_exe and paths:
            try:
                import subprocess, json as _json
                p_ct = subprocess.run(
                    [self.ffprobe_exe, "-v", "error", "-show_format", "-of", "json",
                     str(paths[0])],
                    capture_output=True, text=True, timeout=5,
                )
                if p_ct.returncode == 0:
                    info = _json.loads(p_ct.stdout)
                    ct = info.get("format", {}).get("tags", {}).get("creation_time")
                    if ct:
                        from datetime import timezone as _tz
                        dt = datetime.fromisoformat(ct.replace("Z", "+00:00"))
                        self.telemetry.start_dt_utc = dt.astimezone(_tz.utc).replace(tzinfo=None)
                        print(f"[start_dt_utc] Fallback from video creation_time: {self.telemetry.start_dt_utc}", flush=True)
            except Exception as exc:
                print(f"[start_dt_utc] Fallback failed: {exc}", flush=True)

        self.signals.sig_progress.emit(70, "Metadane gotowe")

    def _generate_meta_json(self) -> None:
        """Generuje metadata JSON dla wideo (GPMF → ExifTool fallback)."""
        if not self.video_path:
            return

        self.signals.sig_progress.emit(45, "Generowanie metadanych...")

        def worker() -> None:
            try:
                data = None
                method = ""
                # Próbuj GPMF
                if _GPMF_AVAILABLE and self.ffmpeg_exe and self.ffprobe_exe:
                    try:
                        data = gpmf_to_exiftool_json(
                            str(self.video_paths[0]),
                            self.ffmpeg_exe, self.ffprobe_exe,
                        )
                        if data:
                            method = "GPMF"
                    except Exception:
                        pass

                # Fallback: ExifTool
                if not data:
                    exe = find_executable(
                        str(self.exiftool_path),
                        [str(self.base_dir / "exiftool.exe"), "exiftool.exe"],
                    )
                    if not exe:
                        raise RuntimeError("Nie znaleziono exiftool")
                    proc = subprocess.run(
                        [exe, "-ee", "-j", "-G3", str(self.video_paths[0])],
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                        text=True,
                    )
                    if proc.returncode != 0:
                        raise RuntimeError(proc.stderr or "ExifTool error")
                    data = json.loads(proc.stdout)
                    method = "ExifTool"

                if data:
                    flat = data[0] if isinstance(data, list) else data
                    json_path = self.video_path.with_suffix(".json")
                    _write_gpmf_cache(json_path, self.video_path, flat, method)
                    print(
                        f"[Telemetry Cache] REGENERATED file={json_path.name}",
                        flush=True,
                    )
                    self.meta_path = json_path

                    records = ensure_records_list([flat])
                    self.telemetry.records = records
                    self.telemetry.load_gpmf_from_exiftool(self.video_path)
                    self.telemetry.load_gpmf_records(records)
                    self.telemetry.load_gps_track(records)

                    # Ponownie odkryj strumienie danych i odśwież UI
                    streams = self._discover_data_streams()
                    self.signals.sig_data_streams_ready.emit(streams)

                self.signals.sig_progress.emit(70, "Metadane gotowe")

            except Exception as e:
                self.signals.sig_error.emit(f"Błąd generowania metadanych: {e}")

        threading.Thread(target=worker, daemon=True).start()
