"""Mixin for handling project loading, files selection, and telemetry parsing.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path

from PySide6.QtCore import QTimer, QUrl
from PIL import Image

from src.gui.indicator_schemas import BUILTIN_FIELDS
from src.gui.layout_manager import normalize_layout
from src.telemetry_extract import ensure_records_list, load_json_with_fallback
from src.video_helpers import (
    clear_capture_cache,
    extract_frame,
    ffprobe_stream_info,
    find_executable,
    parse_fps,
)

try:
    from src.telemetry_gpmf_new import gpmf_to_exiftool_json
    _GPMF_AVAILABLE = True
except ImportError:
    _GPMF_AVAILABLE = False

try:
    from telemetry_gpx import find_gpx_for_video, process_gpx
    _GPX_AVAILABLE = True
except ImportError:
    _GPX_AVAILABLE = False

try:
    from telemetry_fit import find_fit_for_video, process_fit
    _FIT_AVAILABLE = True
except ImportError:
    _FIT_AVAILABLE = False

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
        metadata = load_json_with_fallback(metadata_path)
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
        data = load_json_with_fallback(cache_path)
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

                # Wczytaj/wygeneruj metadane
                self.signals.sig_progress.emit(30, "Sprawdzanie metadanych...")
                self._load_or_generate_telemetry()

                # Wczytaj GPX (jeśli podano)
                if gpx_path and _GPX_AVAILABLE:
                    self.gpx_path = Path(gpx_path)
                    self.telemetry.load_gpx(
                        self.video_path, self.telemetry.start_dt_utc,
                        manual_path=self.gpx_path,
                    )

                # Wczytaj FIT (jeśli podano)
                if fit_path and _FIT_AVAILABLE:
                    self.fit_path = Path(fit_path)
                    self.telemetry.load_fit(
                        self.video_path, self.telemetry.start_dt_utc,
                        manual_path=self.fit_path,
                    )

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
                self.signals.sig_progress.emit(80, "Budowa interfejsu...")
                streams = self._discover_data_streams()
                self.signals.sig_data_streams_ready.emit(streams)

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
                self._render_preview(0)

                # ── Hwdec diagnostics (deferred, needs main thread) ────
                if self.is_using_mpv():
                    QTimer.singleShot(1500, self._check_mpv_hwdec)

                self.signals.sig_progress.emit(100, "Gotowe")

            except Exception as e:
                import traceback
                traceback.print_exc()
                self.signals.sig_error.emit(str(e))

        threading.Thread(target=bg_load, daemon=True).start()

    def _load_or_generate_telemetry(self) -> None:
        """Wczytaj istniejący JSON lub wygeneruj synchronicznie (blokada).

        Blokuje do czasu sparsowania danych, emitując postęp przez sig_progress.
        """
        if not self.video_path:
            return

        meta = self.video_path.with_suffix(".json")
        data, cache_reason = _load_valid_gpmf_cache(self.video_path, meta)
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
                self.signals.sig_progress.emit(45, "Wczytywanie JSON...")
                self.telemetry.records = records
                self.telemetry.load_gpmf_from_exiftool(self.video_path)
                self.telemetry.load_gpmf_records(records)
                self.telemetry.load_gps_track(records)
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
                data = gpmf_to_exiftool_json(
                    str(self.video_paths[0]),
                    self.ffmpeg_exe, self.ffprobe_exe,
                )
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

            self.signals.sig_progress.emit(65, f"Parsowanie danych ({method})...")
            records = ensure_records_list([flat])
            self.telemetry.records = records
            # Przekazujemy flat zamiast uruchamiać ExifTool ponownie
            self.telemetry.load_gpmf_from_exiftool(self.video_path, flat=flat)
            self.telemetry.load_gpmf_records(records)
            self.telemetry.load_gps_track(records)

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
