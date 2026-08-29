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
from src.multifile import build_timeline_from_paths, format_timeline_diagnostics
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
        self.signals.sig_progress.emit(0, "Wczytywanie wideo...")

        def bg_load() -> None:
            try:
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
                self.fps = parse_fps(
                    streams[0].get("avg_frame_rate")
                    or streams[0].get("r_frame_rate")
                ) if streams else 30.0
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
                self.signals.sig_video_duration_ready.emit(total_dur)

                # Layout — użyj startowego preseta jeśli ustawiony
                preset_path = self._startup_preset_path or self.layout.get("_startup_preset", "")
                if preset_path and Path(preset_path).exists():
                    # Wczytaj preset bezpośrednio (bez scalania z domyślnym)
                    self.layout = json.loads(
                        Path(preset_path).read_text(encoding="utf-8")
                    )
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
                if fit_path and _FIT_AVAILABLE and _parse_fit is not None:
                    try:
                        records = _parse_fit(fit_path)
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
                if map_gps is None and gpx_path and _GPX_AVAILABLE and _parse_gpx is not None:
                    try:
                        points = _parse_gpx(gpx_path)
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
                if gpx_path and _GPX_AVAILABLE:
                    self.gpx_path = Path(gpx_path)
                    self.telemetry.load_gpx(
                        self.video_path, self.telemetry.start_dt_utc,
                        manual_path=self.gpx_path,
                        preparsed=self._map_preload_gpx_points,
                    )

                # Wczytaj FIT (jeśli podano) — reuse the preparsed records
                if fit_path and _FIT_AVAILABLE:
                    self.fit_path = Path(fit_path)
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
                # The decoder is loaded with clip 0 (first file) at this point.
                self._active_preview_clip_index = 0
                self._pending_seek_ms = None

                # Odczytaj cut_regions z layoutu
                self._cut_regions = self.layout.get("cut_regions", [])
                if isinstance(self._cut_regions, list):
                    self._cut_regions = [
                        (float(a), float(b)) for a, b in self._cut_regions
                        if isinstance(a, (int, float)) and isinstance(b, (int, float))
                    ]
                else:
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
                if self.is_using_mpv():
                    target_h = int(self._preview_target_w * h / w) if w > 0 else 540
                    first_frame = Image.new("RGBA", (self._preview_target_w, target_h), (0, 0, 0, 0))
                elif _QT_MULTIMEDIA_AVAILABLE and hasattr(self, "media_player"):
                    # QMediaPlayer is loaded — first frame will arrive via
                    # _on_video_frame callback (hardware-accelerated).
                    # Use placeholder until then.
                    target_h = int(self._preview_target_w * h / w) if w > 0 else 540
                    first_frame = Image.new("RGBA", (self._preview_target_w, target_h), (0, 0, 0, 0))
                else:
                    clear_capture_cache()
                    first_frame = extract_frame(
                        self.video_paths, 0, ffmpeg_exe, ffprobe_exe, target_w=self._preview_target_w, preferred_encoder=self.ui.render_tab.cmb_encoder.currentText() if getattr(self, "ui", None) and getattr(self.ui, "render_tab", None) else ""
                    )
                if first_frame:
                    if not self.is_using_mpv():
                        # Skaluj do rozdzielczości podglądu
                        w, h = first_frame.size
                        if w > self._preview_target_w:
                            ratio = self._preview_target_w / w
                            new_h = max(1, int(h * ratio))
                            first_frame = first_frame.resize(
                                (self._preview_target_w, new_h), Image.LANCZOS,
                            )
                    self.src_img = first_frame
                    self.last_src_pil = first_frame
                    self.last_preview_ts = 0.0
                self.signals.sig_progress.emit(95, "Składanie podglądu...")
                self._render_preview(0)

                # ── Hwdec diagnostics (deferred, needs main thread) ────
                if self.is_using_mpv():
                    # bg_load has no Qt event dispatcher. Request the timer
                    # on the controller's GUI thread through a queued signal.
                    self.signals.sig_schedule_mpv_hwdec_check.emit()

                self.signals.sig_progress.emit(100, "Gotowe")

            except Exception as e:
                import traceback
                traceback.print_exc()
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
        if snap.get("provider") == provider and snap.get("status") == "ready":
            return
        gps_track = snap.get("gps_track")
        gps_source = snap.get("gps_source") or "fit"
        if not gps_track and getattr(self, "telemetry", None):
            source = (self.layout or {}).get("indicators", {}).get("track_map", {}).get("source", "fit")
            gps_track = self.telemetry.get_gps_track_for_source(source)
            gps_source = source
        if not gps_track:
            return
        # ASCII-safe arrow: the U+2192 glyph is not encodable on the Windows
        # cp1250 console and would crash the provider switch before it starts.
        print(
            f"[MapPreload] provider {snap.get('provider')} -> {provider} "
            f"generation={ctx.generation_id + 1}",
            flush=True,
        )
        self._start_map_preload(gps_track, gps_source, provider=provider)

    def _load_or_generate_telemetry(self) -> None:
        """Wczytaj istniejący JSON lub wygeneruj synchronicznie (blokada).

        Blokuje do czasu sparsowania danych, emitując postęp przez sig_progress.
        """
        if not self.video_path:
            return

        meta = self.video_path.with_suffix(".json")
        self.signals.sig_progress.emit(45, "Odczyt JSON...")
        cache_t0 = _time.perf_counter()
        data, cache_reason = _load_valid_gpmf_cache(self.video_path, meta)
        _profile_load_stage("json_cache_validation", cache_t0, meta)
        if data is not None:
            try:
                records = ensure_records_list(data)
            except Exception:
                records = None
                cache_reason = "invalid_payload"
            if records:
                print(
                    f"[Telemetry Cache] HIT file={meta.name} "
                    f"version={GPMF_CACHE_VERSION}", flush=True,
                )
                self.telemetry.records = records
                processed_t0 = _time.perf_counter()
                processed = read_processed_cache(self.video_path)
                _profile_load_stage(
                    "processed_cache_read_decode", processed_t0,
                    processed_cache_path(self.video_path),
                    len(records),
                )
                if processed is not None:
                    print(
                        f"[Telemetry Cache] PROCESSED HIT file="
                        f"{processed_cache_path(self.video_path).name}",
                        flush=True,
                    )
                    self.signals.sig_progress.emit(
                        65, "Wczytywanie cache telemetrycznego...",
                    )
                    apply_processed_cache(self.telemetry, processed)
                    self.meta_path = meta
                    return
                print(
                    f"[Telemetry Cache] PROCESSED MISS file="
                    f"{processed_cache_path(self.video_path).name}",
                    flush=True,
                )
                self.signals.sig_progress.emit(55, "Analiza GPMF...")
                extract_t0 = _time.perf_counter()
                # The sidecar already contains the flat ExifTool-compatible
                # dictionary.  Passing it avoids launching ExifTool again on
                # every warm load.
                self.telemetry.load_gpmf_from_exiftool(
                    self.video_path, flat=data if isinstance(data, dict) else None,
                )
                _profile_load_stage(
                    "gpmf_exiftool_extract", extract_t0, meta, len(records),
                )
                records_t0 = _time.perf_counter()
                self.telemetry.load_gpmf_records(
                    records, profile_cb=_profile_gpmf_substage,
                )
                _profile_load_stage(
                    "gpmf_records_extract", records_t0, meta, len(records),
                )
                gps_t0 = _time.perf_counter()
                self.telemetry.load_gps_track(
                    records, profile_cb=_profile_gpmf_substage,
                )
                _profile_load_stage("gps_extract", gps_t0, meta, len(records))
                write_processed_t0 = _time.perf_counter()
                processed_path = write_processed_cache(self.video_path, self.telemetry)
                _profile_load_stage(
                    "processed_cache_write", write_processed_t0,
                    processed_path,
                )
                self.meta_path = meta
                return
        print(
            f"[Telemetry Cache] MISS reason={cache_reason or 'invalid_cache'}",
            flush=True,
        )
        # ── JSON nie istnieje → generuj synchronicznie (blokada) ──────
        self.signals.sig_progress.emit(45, "Generowanie metadanych...")

        data = None
        method = ""
        # Próbuj GPMF (bezpośrednio z ffmpeg — dużo szybszy niż ExifTool)
        if _GPMF_AVAILABLE and self.ffmpeg_exe and self.ffprobe_exe:
            try:
                self.signals.sig_progress.emit(50, "GPMF: czytanie strumienia...")
                gpmf_t0 = _time.perf_counter()
                data = gpmf_to_exiftool_json(
                    str(self.video_paths[0]),
                    self.ffmpeg_exe, self.ffprobe_exe,
                )
                _profile_load_stage("gpmf_convert", gpmf_t0, self.video_path)
                if data:
                    method = "GPMF"
                    print(f"[GPMF] Succeeded — extracted {len(data[0]) if isinstance(data, list) and data else 0} keys", flush=True)
                else:
                    print("[GPMF] Returned empty data", flush=True)
            except Exception as exc:
                print(f"[GPMF] Failed: {exc} — falling back to ExifTool", flush=True)

        # Fallback: ExifTool
        if not data:
            self.signals.sig_progress.emit(55, "ExifTool: odczyt metadanych...")
            exe = find_executable(
                str(self.exiftool_path),
                [str(self.base_dir / "exiftool.exe"), "exiftool.exe"],
            )
            if not exe:
                raise RuntimeError("Nie znaleziono exiftool")
            exiftool_t0 = _time.perf_counter()
            proc = subprocess.run(
                [exe, "-ee", "-j", "-G3", str(self.video_paths[0])],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True,
            )
            _profile_load_stage("exiftool_process", exiftool_t0, self.video_path)
            if proc.returncode != 0:
                raise RuntimeError(proc.stderr or "ExifTool error")
            exiftool_t0 = _time.perf_counter()
            data = json.loads(proc.stdout)
            _profile_load_stage("exiftool_json_parse", exiftool_t0, self.video_path)
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

            self.signals.sig_progress.emit(65, f"Parsowanie danych ({method})...")
            records_t0 = _time.perf_counter()
            records = ensure_records_list([flat])
            _profile_load_stage(
                "records_conversion", records_t0, json_path, len(records),
            )
            self.telemetry.records = records
            # Przekazujemy flat zamiast uruchamiać ExifTool ponownie
            extract_t0 = _time.perf_counter()
            self.telemetry.load_gpmf_from_exiftool(self.video_path, flat=flat)
            self.telemetry.load_gpmf_records(
                records, profile_cb=_profile_gpmf_substage,
            )
            _profile_load_stage(
                "gpmf_records_extract", extract_t0, json_path, len(records),
            )
            gps_t0 = _time.perf_counter()
            self.telemetry.load_gps_track(
                records, profile_cb=_profile_gpmf_substage,
            )
            _profile_load_stage("gps_extract", gps_t0, json_path, len(records))

            write_processed_t0 = _time.perf_counter()
            processed_path = write_processed_cache(self.video_path, self.telemetry)
            _profile_load_stage(
                "processed_cache_write", write_processed_t0, processed_path,
            )

            # Jeśli start_dt_utc wciąż None (brak GPSDateTime w GPMF),
            # użyj daty z metadanych wideo
            if self.telemetry.start_dt_utc is None and self.ffprobe_exe:
                try:
                    import subprocess, json as _json
                    p = subprocess.run(
                        [self.ffprobe_exe, "-v", "error", "-show_format", "-of", "json",
                         str(self.video_path)],
                        capture_output=True, text=True, timeout=5,
                    )
                    if p.returncode == 0:
                        info = _json.loads(p.stdout)
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
