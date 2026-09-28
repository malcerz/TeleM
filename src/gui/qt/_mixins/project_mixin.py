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
from typing import Any

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
from src.telemetry_file_validation import (
    TelemetryFileValidationResult,
    TelemetryValidationRequest,
    ValidationState,
    inspect_gpx_structure,
    log_validation,
    normalize_utc,
    sample_time_range,
    validate_telemetry_range,
)
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

_PROCESSED_TELEMETRY_FIELDS = (
    "speed_samples", "alt_samples", "track_samples", "gps_track",
    "accelerometer_samples", "gyroscope_samples", "iso_samples",
    "exposure_samples", "temperature_samples",
)


def _processed_cache_has_payload(processed: dict | None) -> bool:
    """Return true when any useful telemetry stream is present in the cache."""
    return bool(
        processed
        and any(bool(processed.get(field)) for field in _PROCESSED_TELEMETRY_FIELDS)
    )


def _print_gpmf_load_diagnostic(
    source_path: Path,
    *,
    cache_hit: bool,
    native_module_available: bool,
    native_parse_ok: bool,
    channel_data: dict | None,
    native_channels: tuple[str, ...] = (),
    python_fallback_channels: tuple[str, ...] = (),
    native_result_accepted: bool = False,
    fallback_reason: str = "",
    parse_ms: float = 0.0,
    cache_load_ms: float = 0.0,
) -> None:
    """Emit one compact diagnostic block per telemetry source load."""
    data = channel_data or {}
    print(
        "[GPMF LOAD]\n"
        f"SOURCE={source_path}\n"
        f"CACHE_HIT={bool(cache_hit)}\n"
        f"NATIVE_MODULE_AVAILABLE={bool(native_module_available)}\n"
        f"NATIVE_PARSE_OK={bool(native_parse_ok)}\n"
        f"GPS_SAMPLES={len(data.get('gps_track') or [])}\n"
        f"ACC_SAMPLES={len(data.get('accelerometer_samples') or [])}\n"
        f"GYRO_SAMPLES={len(data.get('gyroscope_samples') or [])}\n"
        f"ISO_SAMPLES={len(data.get('iso_samples') or [])}\n"
        f"TEMP_SAMPLES={len(data.get('temperature_samples') or [])}\n"
        f"NATIVE_CHANNELS_USED={','.join(native_channels) or '-'}\n"
        f"PYTHON_FALLBACK_CHANNELS={','.join(python_fallback_channels) or '-'}\n"
        f"NATIVE_RESULT_ACCEPTED={bool(native_result_accepted)}\n"
        f"FALLBACK_REASON={fallback_reason or '-'}\n"
        f"PARSE_MS={parse_ms:.2f}\n"
        f"CACHE_LOAD_MS={cache_load_ms:.2f}",
        flush=True,
    )


def _gpmf_cache_metadata_path(cache_path: Path) -> Path:
    """Return the sidecar path kept separate from telemetry JSON consumers."""
    return cache_path.with_name(f"{cache_path.stem}.meta.json")


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
) -> Path:
    """Atomically write telemetry JSON and its source/version contract to central AppData cache."""
    from src.telemetry_cache_manager import (
        get_gpmf_json_path,
        get_gpmf_metadata_path,
        update_source_metadata,
        log_cache_event,
    )
    target_cache_path = get_gpmf_json_path(source_path)
    target_meta_path = get_gpmf_metadata_path(source_path)
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
    _atomic_write_json(target_cache_path, data)
    _atomic_write_json(target_meta_path, metadata)
    try:
        update_source_metadata(source_path, "gpmf_json", target_cache_path.stat().st_size)
    except Exception:
        pass
    log_cache_event(source_path, "STORED", target_cache_path, extra="gpmf_json")
    return target_cache_path


def _load_valid_gpmf_cache(
    source_path: Path,
    cache_path: Path | None = None,
) -> tuple[object | None, str | None]:
    """Load cache only when its version and source fingerprint are proven.

    Checks central AppData cache first, with read-only fallback/migration from legacy sidecar.
    """
    from src.telemetry_cache_manager import (
        get_gpmf_json_path,
        get_gpmf_metadata_path,
        get_legacy_gpmf_json_path,
        get_legacy_gpmf_meta_paths,
        log_cache_event,
        update_source_metadata,
    )

    try:
        source_stat = source_path.stat()
    except OSError:
        return None, "source_missing"

    def _verify_and_load(c_path: Path, m_path: Path) -> tuple[object | None, str | None]:
        if not c_path.exists():
            return None, "cache_missing"
        if not m_path.exists():
            return None, "legacy_cache_no_version"
        try:
            metadata = load_json_with_fallback(m_path, profile_cb=_profile_json_stage)
        except Exception:
            return None, "invalid_metadata"
        contract = metadata.get("_telem_cache") if isinstance(metadata, dict) else None
        required = ("version", "source_size", "source_mtime_ns", "generator")
        if not isinstance(contract, dict) or any(key not in contract for key in required):
            return None, "missing_metadata"
        if contract["version"] != GPMF_CACHE_VERSION:
            return None, "cache_version_mismatch"
        if contract["source_size"] != source_stat.st_size:
            return None, "source_size_changed"
        if contract["source_mtime_ns"] != source_stat.st_mtime_ns:
            return None, "source_mtime_changed"
        try:
            data = load_json_with_fallback(c_path, profile_cb=_profile_json_stage)
        except Exception:
            return None, "invalid_json"
        if not data:
            return None, "invalid_payload"
        return data, None

    # 1. Central AppData cache
    appdata_cache = get_gpmf_json_path(source_path)
    appdata_meta = get_gpmf_metadata_path(source_path)
    data, reason = _verify_and_load(appdata_cache, appdata_meta)
    if data is not None:
        log_cache_event(source_path, "HIT", appdata_cache, extra="gpmf_json")
        return data, None

    return None, reason or "cache_missing"


class ProjectMixin:
    def _probe_candidate_video_state(
        self,
        video_path: str | Path,
        ffprobe_exe: str,
        *,
        default_fps: float = 30.0,
    ) -> dict[str, Any]:
        """Probe the complete video metadata contract before project commit."""
        from src.telemetry_extract import get_container_rotation

        info = ffprobe_stream_info(ffprobe_exe, Path(video_path))
        streams = info.get("streams", [])
        stream = streams[0] if streams else {}
        width = int(stream.get("width", 1920) or 1920)
        height = int(stream.get("height", 1080) or 1080)
        fps = parse_fps(
            stream.get("avg_frame_rate") or stream.get("r_frame_rate")
        ) if stream else default_fps
        rotation = get_container_rotation(ffprobe_exe, Path(video_path))
        return {
            "path": Path(video_path),
            "width": width,
            "height": height,
            "fps": fps,
            "rotation": rotation,
            "video_info": {
                "width": width,
                "height": height,
                "fps": fps,
                "rotation": rotation,
            },
        }

    def _project_video_time_range(
        self,
        video_paths: list[str | Path] | None = None,
        *,
        ffmpeg_exe: str | None = None,
        ffprobe_exe: str | None = None,
    ) -> tuple[object | None, object | None]:
        """Return the absolute UTC range for the current or candidate video set.

        An explicit ``video_paths`` value is a candidate transaction.  It must
        never fall back to the already committed timeline, otherwise selecting
        a new MP4 while an old project is open validates FIT/GPX against the
        old video's timestamps.
        """
        if video_paths is not None:
            paths = [Path(path) for path in video_paths]
            if not paths:
                return None, None
            try:
                from src.multifile import probe_clip_time_interval
                intervals = [
                    probe_clip_time_interval(
                        path,
                        ffmpeg_exe=ffmpeg_exe or "ffmpeg",
                        ffprobe_exe=ffprobe_exe or "ffprobe",
                    )
                    for path in paths
                ]
                known = [
                    (normalize_utc(item[0]), normalize_utc(item[1]))
                    for item in intervals
                    if item[0] is not None and item[1] is not None
                ]
                if known:
                    result = min(item[0] for item in known), max(item[1] for item in known)
                    print(
                        "[TELEMETRY VALIDATION] "
                        f"VALIDATION_VIDEO_TIME_OBJECT=candidate_video_probe "
                        f"VALIDATION_VIDEO_TIME_SOURCE=gpmf_candidate_paths "
                        f"paths={len(paths)} range={result[0]}..{result[1]}",
                        flush=True,
                    )
                    return result
            except Exception as exc:
                print(f"[TELEMETRY VALIDATION] candidate video probe failed: {exc}", flush=True)
            print(
                "[TELEMETRY VALIDATION] VALIDATION_VIDEO_TIME_OBJECT=candidate_video_probe "
                "VALIDATION_VIDEO_TIME_SOURCE=unavailable",
                flush=True,
            )
            return None, None

        """Return the absolute UTC range for the complete current video set."""
        timeline = getattr(self, "video_timeline", None)
        clips = list(getattr(timeline, "clips", []) or []) if timeline else []
        starts = [normalize_utc(getattr(clip, "absolute_start_dt", None)) for clip in clips]
        ends = [normalize_utc(getattr(clip, "absolute_end_dt", None)) for clip in clips]
        starts = [value for value in starts if value is not None]
        ends = [value for value in ends if value is not None]
        if starts and ends:
            return min(starts), max(ends)
        paths = list(getattr(self, "video_paths", []) or [])
        if paths:
            try:
                from src.multifile import probe_clip_time_interval
                intervals = [probe_clip_time_interval(path) for path in paths]
                known = [
                    (normalize_utc(item[0]), normalize_utc(item[1]))
                    for item in intervals
                    if item[0] is not None and item[1] is not None
                ]
                if known:
                    return min(item[0] for item in known), max(item[1] for item in known)
            except Exception as exc:
                print(f"[TELEMETRY VALIDATION] video range probe failed: {exc}", flush=True)
        start = normalize_utc(getattr(getattr(self, "telemetry", None), "start_dt_utc", None))
        duration = getattr(self, "video_duration_s", None)
        if start is not None and duration is not None:
            from datetime import timedelta
            return start, start + timedelta(seconds=float(duration))
        return None, None

    def _request_telemetry_validation(self, result: TelemetryFileValidationResult) -> bool:
        """Synchronously ask the GUI thread for a mismatch/unknown decision."""
        if result.state is ValidationState.VALID:
            log_validation(result, user_override=False)
            return True
        request = TelemetryValidationRequest(result)
        try:
            self.signals.sig_telemetry_validation_request.emit(request)
            if not request.completed.wait(timeout=120.0):
                print("[TELEMETRY VALIDATION] GUI decision timeout; rejecting candidate", flush=True)
                return False
        except Exception as exc:
            print(f"[TELEMETRY VALIDATION] GUI request failed: {exc}", flush=True)
            return False
        log_validation(result, user_override=request.user_override)
        return bool(request.accepted)

    def _validate_external_telemetry_candidate(
        self,
        file_type: str,
        file_path: str | Path,
        parsed: Any = None,
        video_time_range: tuple[object | None, object | None] | None = None,
    ) -> tuple[bool, Any]:
        """Parse/validate a candidate without mutating project telemetry state."""
        path = Path(file_path)
        if video_time_range is None:
            video_start, video_end = self._project_video_time_range()
        else:
            video_start, video_end = video_time_range
        kind = str(file_type).upper()
        parse_error = None
        point_count = 0
        telemetry_range = None

        if not path.is_file():
            parse_error = "missing_file"
        elif kind == "FIT":
            try:
                if parsed is None:
                    from telemetry_fit import parse_fit
                    parsed = parse_fit(path)
                point_count = len(parsed or [])
                telemetry_range = sample_time_range(
                    (record.get("timestamp"),) for record in (parsed or [])
                    if record.get("timestamp") is not None
                )
                if not parsed:
                    parse_error = "empty_or_corrupt_fit"
            except Exception as exc:
                import traceback
                traceback.print_exc()
                parse_error = str(exc)
                parsed = None
        elif kind == "GPX":
            point_count, timed_count, telemetry_range, structure_error = inspect_gpx_structure(path)
            if structure_error:
                parse_error = structure_error
            elif parsed is None and timed_count > 0:
                try:
                    from telemetry_gpx import parse_gpx
                    parsed = parse_gpx(path)
                except Exception as exc:
                    import traceback
                    traceback.print_exc()
                    parse_error = str(exc)
                    parsed = None
            if timed_count > 0 and not parsed and not parse_error:
                parse_error = "empty_or_corrupt_gpx"
        else:
            parse_error = "unsupported_file_type"

        result = validate_telemetry_range(
            file_type=kind,
            file_path=path,
            video_start=video_start,
            video_end=video_end,
            telemetry_start=telemetry_range[0] if telemetry_range else None,
            telemetry_end=telemetry_range[1] if telemetry_range else None,
            point_count=point_count,
            parse_error=parse_error,
        )
        accepted = self._request_telemetry_validation(result)
        return accepted, parsed

    def _on_files_selected(
        self,
        video_paths: list[str],
        gpx_path: str,
        fit_path: str,
    ) -> None:
        """Użytkownik wybrał pliki w zakładce Wczytywanie."""
        # Suppress decoder callbacks until an explicitly selected FIT has
        # loaded and its presentation plans have been warmed.
        self._preview_telemetry_loading = bool(fit_path)
        self.signals.sig_progress.emit(0, "Wczytywanie wideo...")

        def bg_load() -> None:
            try:
                effective_fit_path = fit_path
                effective_gpx_path = gpx_path
                candidate_video_paths = [Path(p) for p in video_paths]
                candidate_video_path = candidate_video_paths[0]

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
                    self._preview_telemetry_loading = False
                    self.signals.sig_progress.emit(100, "Gotowe")
                    return
                # Candidate preflight must happen before any committed project
                # state is replaced.  In particular, do not let the previous
                # self.video_timeline win over this candidate's GPMF range.
                candidate_video_range = self._project_video_time_range(
                    candidate_video_paths,
                    ffmpeg_exe=ffmpeg_exe,
                    ffprobe_exe=ffprobe_exe,
                )
                if not effective_fit_path and not effective_gpx_path:
                    try:
                        from src.multifile import probe_clip_time_interval
                        from telemetry_fit import find_best_fit_match
                        candidate_intervals = []
                        for candidate_path in candidate_video_paths:
                            start_dt, end_dt, duration_s, confidence = probe_clip_time_interval(
                                candidate_path,
                                ffmpeg_exe=ffmpeg_exe,
                                ffprobe_exe=ffprobe_exe,
                            )
                            if start_dt is not None and end_dt is not None:
                                candidate_intervals.append(
                                    (start_dt, end_dt, duration_s, confidence)
                                )
                        if candidate_intervals:
                            matched_fit, _diag = find_best_fit_match(
                                candidate_intervals, candidate_video_paths[0].parent,
                            )
                            if matched_fit is not None:
                                effective_fit_path = str(matched_fit)
                    except Exception as exc:
                        print(f"[AutoFIT] Candidate preflight failed: {exc}", flush=True)
                validated_fit_records = None
                validated_gpx_points = None
                if effective_fit_path:
                    fit_ok, validated_fit_records = self._validate_external_telemetry_candidate(
                        "FIT", effective_fit_path, video_time_range=candidate_video_range,
                    )
                    if not fit_ok:
                        self._preview_telemetry_loading = False
                        self.signals.sig_progress.emit(100, "Gotowe")
                        return
                if effective_gpx_path:
                    gpx_ok, validated_gpx_points = self._validate_external_telemetry_candidate(
                        "GPX", effective_gpx_path, video_time_range=candidate_video_range,
                    )
                    if not gpx_ok:
                        self._preview_telemetry_loading = False
                        self.signals.sig_progress.emit(100, "Gotowe")
                        return

                # Atomic project-state commit starts only after candidate
                # telemetry has passed validation or the user explicitly
                # selected the override action.
                self.video_paths = candidate_video_paths
                self.video_path = candidate_video_path
                self.ffprobe_exe = ffprobe_exe
                self.ffmpeg_exe = ffmpeg_exe
                self._clear_caches()
                try:
                    from src.indicators.moving_map import clear_moving_map_cache
                    clear_moving_map_cache()
                except Exception:
                    pass

                # Ustaw źródło QMediaPlayer (GPU-accelerated preview)
                if _QT_MULTIMEDIA_AVAILABLE and hasattr(self, "media_player"):
                    self.media_player.setSource(
                        QUrl.fromLocalFile(str(candidate_video_path))
                    )

                if self.is_using_mpv():
                    self.mpv_player.play(str(candidate_video_path))
                    self.mpv_player.pause = True

                # Analiza wideo
                self.signals.sig_progress.emit(15, "Analiza strumienia...")
                candidate_state = self._probe_candidate_video_state(
                    candidate_video_path, ffprobe_exe,
                    default_fps=self.fps if hasattr(self, "fps") else 30.0,
                )
                w = candidate_state["width"]
                h = candidate_state["height"]
                self.video_width = w
                self.video_height = h
                self.video_info = dict(candidate_state["video_info"])
                self.video_rotation_degrees = candidate_state["rotation"]
                self.fps = float(candidate_state["fps"])
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
                    preset_path = self._startup_preset_path or (self.layout.get("_startup_preset", "") if isinstance(self.layout, dict) else "")
                    if preset_path and Path(preset_path).exists():
                        self.layout = json.loads(
                            Path(preset_path).read_text(encoding="utf-8")
                        )
                        normalize_indicator_decimal_defaults(self.layout)
                    else:
                        def_layout = self.base_dir / "def_layout.json"
                        self.layout = normalize_layout(def_layout, w, h)
                render_tab = getattr(getattr(self, "ui", None), "render_tab", None)
                if render_tab is not None and hasattr(render_tab, "apply_export_settings"):
                    render_tab.apply_export_settings(self.layout.get("export_settings", {}))
                self._selected_stream_key = ""
                self.src_img = Image.new("RGB", (w, h), (0, 0, 0))

                # ── Map preload (ETAP MAP PRELOAD) — parallel with GPMF ──
                # Parse FIT/GPX GPS EARLY (fast) so the coarse overview map can
                # start downloading tiles while GPMF/JSON is still parsing.
                # The parsed records are REUSED later (no double parsing).
                self._map_preload_fit_records = validated_fit_records
                self._map_preload_gpx_points = validated_gpx_points
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
                    except Exception as e:
                        print(f"[AutoFIT] Error in project auto-fit: {e}", flush=True)
                configured_gps_src = (self.layout or {}).get("indicators", {}).get("track_map", {}).get("gps_source", "auto")
                if (
                    self._map_preload_fit_records is None
                    and configured_gps_src != "gpmf"
                    and effective_fit_path
                    and _FIT_AVAILABLE
                    and _parse_fit is not None
                ):
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
                if (
                    self._map_preload_gpx_points is None
                    and map_gps is None
                    and effective_gpx_path
                    and _GPX_AVAILABLE
                    and _parse_gpx is not None
                ):
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
                if map_gps is not None and not (effective_fit_path or effective_gpx_path):
                    self._start_map_preload(
                        map_gps, map_source, provider=map_provider,
                    )

                # Wczytaj/wygeneruj metadane (GPMF — heavy, runs in parallel
                # with the map preload thread started above)
                self.signals.sig_progress.emit(30, "Sprawdzanie metadanych...")
                self._load_or_generate_telemetry()

                # Candidate validation/decision was completed before commit;
                # only reuse the accepted temporary data here.
                map_gps = None
                map_source = None
                if effective_fit_path and validated_fit_records:
                    map_gps = [
                        (r["timestamp"], r["lat"], r["lon"])
                        for r in validated_fit_records
                        if r.get("lat") is not None and r.get("lon") is not None
                    ]
                    map_source = "fit"
                elif effective_gpx_path and validated_gpx_points:
                    map_gps = [
                        (p[0], p[1], p[2])
                        for p in validated_gpx_points
                        if p[1] is not None and p[2] is not None
                    ]
                    map_source = "gpx"
                if map_gps is not None:
                    self._start_map_preload(
                        map_gps, map_source, provider=map_provider,
                    )

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
                    gpx_loaded = self.telemetry.load_gpx(
                        self.video_path, self.telemetry.start_dt_utc,
                        manual_path=Path(effective_gpx_path),
                        preparsed=validated_gpx_points,
                    )
                    if gpx_loaded:
                        self.gpx_path = Path(effective_gpx_path)

                # Wczytaj FIT (jeśli podano) — reuse the preparsed records
                if effective_fit_path and _FIT_AVAILABLE:
                    fit_loaded = self.telemetry.load_fit(
                        self.video_path, self.telemetry.start_dt_utc,
                        manual_path=Path(effective_fit_path),
                        preparsed=validated_fit_records,
                    )
                    if fit_loaded:
                        self.fit_path = Path(effective_fit_path)

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
                try:
                    self._trigger_map_background_prefetch(reason="telemetry_loaded")
                except Exception:
                    pass

            except Exception as e:
                import traceback
                traceback.print_exc()
                self._preview_telemetry_loading = False
                self.signals.sig_error.emit(str(e))
                self.signals.sig_progress.emit(100, "Gotowe")

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
        # Trigger full route tile prefetch in background (non-blocking)
        self._trigger_map_background_prefetch(reason="map_preload_start")

    def _trigger_map_background_prefetch(self, reason: str = "") -> None:
        """Trigger project-level background prefetch of moving map tiles."""
        try:
            layout = getattr(self, "layout", None)
            if not layout or not isinstance(layout, dict):
                return
            map_source = layout.get("indicators", {}).get("track_map", {}).get("gps_source", "auto")

            gps_track = None
            if hasattr(self, "telemetry") and self.telemetry:
                if hasattr(self.telemetry, "resolve_gps_track"):
                    gps_track = self.telemetry.resolve_gps_track(map_source)[0]
                elif hasattr(self.telemetry, "get_gps_track_for_source"):
                    gps_track = self.telemetry.get_gps_track_for_source(map_source)
                else:
                    gps_track = getattr(self.telemetry, "gps_track", None)
            if not gps_track and getattr(self, "map_context", None):
                snap = self.map_context.snapshot()
                gps_track = snap.get("gps_track")
            if not gps_track or len(gps_track) < 2:
                return

            canvas_w = 3840
            canvas_h = 2160
            if hasattr(self, "video_metadata") and self.video_metadata:
                w = getattr(self.video_metadata, "width", 0)
                h = getattr(self.video_metadata, "height", 0)
                if w and h:
                    canvas_w, canvas_h = int(w), int(h)

            from src.gui.map_prefetch import MapBackgroundPrefetchManager
            mgr = MapBackgroundPrefetchManager.get_instance()
            mgr.schedule_prefetch(
                gps_track=gps_track,
                layout=layout,
                canvas_w=canvas_w,
                canvas_h=canvas_h,
                key="track_map",
                reason=reason,
            )
        except Exception as exc:
            print(f"[MapPrefetch] Failed to trigger background prefetch: {exc}", flush=True)

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
        self._trigger_map_background_prefetch(reason="provider_switch")

    def _load_single_clip_telemetry(self, video_path: Path, clip_idx: int = 0, total_clips: int = 1) -> tuple[dict, list]:
        """Wczytaj cache procesowany (.telemetry.npz) lub wygeneruj metadane dla jednego klipu."""
        t0 = _time.perf_counter()
        from src.telemetry_cache_manager import get_gpmf_json_path
        meta = get_gpmf_json_path(video_path)
        processed = read_processed_cache(video_path)
        if _processed_cache_has_payload(processed):
            print(
                f"[Telemetry Cache] PROCESSED HIT file="
                f"{processed_cache_path(video_path).name}",
                flush=True,
            )
            data, _ = _load_valid_gpmf_cache(video_path, meta)
            records = ensure_records_list(data) if data else []
            try:
                from src.telemetry_native_gpmf import is_native_gpmf_available
                cached_native_available = is_native_gpmf_available()
            except Exception:
                cached_native_available = False
            _print_gpmf_load_diagnostic(
                video_path,
                cache_hit=True,
                native_module_available=cached_native_available,
                native_parse_ok=False,
                channel_data=processed,
                fallback_reason="processed_cache",
                cache_load_ms=(_time.perf_counter() - t0) * 1000.0,
            )
            _profile_load_stage("gpmf_decode_ms", t0, video_path, len(records))
            return processed, records

        pct_clip_start = 30 + int(35 * (clip_idx / total_clips))
        pct_clip_end = 30 + int(35 * ((clip_idx + 1) / total_clips))
        clip_span = max(1, pct_clip_end - pct_clip_start)
        native_data = None
        native_module_available = False
        native_parse_ok = False

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
                missing_native_channels,
                native_channels_used,
                native_result_usable,
                extract_missing_gpmf_channels,
                merge_native_channel_data,
            )
            native_module_available = is_native_gpmf_available()
            if native_module_available:
                t_native = _time.perf_counter()
                try:
                    self.signals.sig_progress.emit(
                        pct_clip_start + int(0.2 * clip_span),
                        f"Natywna analiza GPMF C++ ({clip_idx + 1}/{total_clips})...",
                    )
                except Exception:
                    pass

                native_data = extract_gpmf_native(video_path)
                native_parse_ok = bool(native_data and native_data.get("success"))
                if native_result_usable(native_data) and not missing_native_channels(native_data):
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
                        print(f"[GPMF] parser=NATIVE file={video_path.name}", flush=True)
                        print(f"[Telemetry Native] Extracted {video_path.name} in {(_time.perf_counter() - t_native)*1000.0:.1f}ms", flush=True)
                        _print_gpmf_load_diagnostic(
                            video_path,
                            cache_hit=False,
                            native_module_available=True,
                            native_parse_ok=True,
                            channel_data=processed,
                            native_channels=native_channels_used(native_data),
                            native_result_accepted=True,
                            fallback_reason="none",
                            parse_ms=(_time.perf_counter() - t_native) * 1000.0,
                        )
                        return processed, []
        except Exception as exc:
            print(f"[Telemetry Native] Fallback to legacy parser: {exc}", flush=True)
            # Keep the legacy path functional if the optional helper module
            # itself cannot be imported.
            native_result_usable = lambda _data: False
            native_channels_used = lambda _data: ()
            missing_native_channels = lambda _data: ()
            extract_missing_gpmf_channels = lambda _records, _missing: {}
            merge_native_channel_data = lambda data, _fallback: data

        # Sprawdź cache GPMF JSON
        data, cache_reason = _load_valid_gpmf_cache(video_path, meta)
        records = ensure_records_list(data) if data else None

        # Accept native data per channel. A single legacy pass supplies only
        # missing families; valid native ACC/GYRO/etc. are never re-parsed.
        if native_result_usable(native_data):
            missing = missing_native_channels(native_data)
            if missing and records:
                fallback_native = extract_missing_gpmf_channels(records, missing)
                native_data = merge_native_channel_data(native_data, fallback_native)
                print(
                    "[GPMF partial fallback] "
                    f"native={','.join(native_channels_used(native_data)) or '-'} "
                    f"fallback={','.join(k for k in missing if fallback_native.get(k)) or '-'}",
                    flush=True,
                )
            if not missing or native_channels_used(native_data):
                from src.gui.telemetry_manager import TelemetryDataManager
                temp_telem = TelemetryDataManager()
                populate_telemetry_from_native(video_path, native_data, temp_telem)
                temp_telem.records = records or []
                write_processed_cache(video_path, temp_telem)
                processed = read_processed_cache(video_path)
                if processed:
                    _profile_load_stage(
                        "gpmf_decode_ms", t0, video_path,
                        len(native_data.get("gps_track") or []),
                    )
                    _print_gpmf_load_diagnostic(
                        video_path,
                        cache_hit=False,
                        native_module_available=True,
                        native_parse_ok=True,
                        channel_data=processed,
                        native_channels=native_channels_used(native_data),
                        python_fallback_channels=tuple(
                            k for k in missing if k not in native_channels_used(native_data)
                        ),
                        native_result_accepted=True,
                        fallback_reason="partial_channels_only",
                        parse_ms=(_time.perf_counter() - t0) * 1000.0,
                    )
                    return processed, []
        if not records:
            # Generuj bezpośrednio z GPMF (FFmpeg) lub ExifTool (emergency fallback only)
            print(f"[GPMF] native parser failed -> ExifTool fallback ({video_path.name})", flush=True)
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
                _print_gpmf_load_diagnostic(
                    video_path,
                    cache_hit=False,
                    native_module_available=native_module_available,
                    native_parse_ok=native_parse_ok,
                    channel_data=processed,
                    python_fallback_channels=_PROCESSED_TELEMETRY_FIELDS,
                    fallback_reason="native_unavailable_or_rejected",
                    parse_ms=(_time.perf_counter() - t0) * 1000.0,
                )
                return processed, records
            # Fallback when processed cache read failed but records were extracted
            fallback_fields = {
                "speed_samples": getattr(temp_telem, "speed_samples", []),
                "alt_samples": getattr(temp_telem, "alt_samples", []),
                "track_samples": getattr(temp_telem, "track_samples", []),
                "iso_samples": getattr(temp_telem, "iso_samples", []),
                "exposure_samples": getattr(temp_telem, "exposure_samples", []),
                "temperature_samples": getattr(temp_telem, "temperature_samples", []),
                "slope_samples": getattr(temp_telem, "slope_samples", []),
                "heading_samples": getattr(temp_telem, "heading_samples", []),
                "gps_track": getattr(temp_telem, "gps_track", []),
                "accelerometer_samples": getattr(temp_telem, "accelerometer_samples", []),
                "gyroscope_samples": getattr(temp_telem, "gyroscope_samples", []),
                "start_dt_utc": getattr(temp_telem, "start_dt_utc", None),
            }
            return fallback_fields, records

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

        # 4. Re-derive vector series (accel, gyro) after concatenation so
        # that scalar streams (accel_x_samples, gyro_x_samples, etc.), NumPy arrays,
        # and lean timelines cover all clips rather than freezing at clip 1.
        if getattr(self.telemetry, "accelerometer_samples", None):
            self.telemetry.accelerometer_array = getattr(self.telemetry.accelerometer_samples, "_arr", None)
            if hasattr(self.telemetry, "_set_vector_series"):
                self.telemetry._set_vector_series(self.telemetry.accelerometer_samples, "accel")
        if getattr(self.telemetry, "gyroscope_samples", None):
            self.telemetry.gyroscope_array = getattr(self.telemetry.gyroscope_samples, "_arr", None)
            if hasattr(self.telemetry, "_set_vector_series"):
                self.telemetry._set_vector_series(self.telemetry.gyroscope_samples, "gyro")
        if hasattr(self.telemetry, "_lean_roll_cache"):
            self.telemetry._lean_roll_cache.clear()
        if hasattr(self.telemetry, "_raw_gyro_cache"):
            self.telemetry._raw_gyro_cache.clear()
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
                from src.telemetry_cache_manager import get_gpmf_json_path
                self.meta_path = get_gpmf_json_path(p)
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
                    from src.telemetry_cache_manager import get_gpmf_json_path
                    json_path = get_gpmf_json_path(self.video_path)
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
