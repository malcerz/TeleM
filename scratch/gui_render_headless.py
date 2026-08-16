"""ETAP GUI integration — headless REAL GUI render test.

Runs the EXACT GUI render code path: `RenderMixin._render_pipeline` (the same
function the PySide6 GUI calls on "Renderuj"), with a minimal stub of the
window state.  No AMD_* environment variables are set -> the new production
defaults must kick in (GPU map / GPU_SPLIT charts / GPU gauge / OPTIMIZED
compose / D3D11VA / pool8).
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.gui.layout_manager import resolve_font_path  # noqa: E402


class _Signals:
    class _Sig:
        def emit(self, *a, **k):
            pass

    sig_progress = _Sig()
    sig_error = _Sig()
    sig_render_finished = _Sig()


class _Stub:
    """Minimal window-state stand-in for RenderMixin._render_pipeline."""

    def __init__(self) -> None:
        video = ROOT / "Video" / "GX020079.mp4"
        self.video_path = video
        self.video_paths = [video]
        self.base_dir = ROOT
        with (ROOT / "def_layout.json").open(encoding="utf-8") as fh:
            self.layout = json.load(fh)
        self._cut_regions = self.layout.get("cut_regions", [])
        self.ffmpeg_exe = r"C:\tools\ffmpeg.exe"
        self.ffprobe_exe = r"C:\tools\ffprobe.exe"
        self.signals = _Signals()
        self.render_cancel_event = threading.Event()
        self.render_threads = 1
        self.video_duration_s = 1131 * (1001.0 / 30000.0)
        self.font_path = resolve_font_path("Arial")
        self.telemetry = _build_telemetry()


def _build_telemetry():
    from src.gui.telemetry_manager import TelemetryDataManager
    from src.telemetry_extract import (
        ensure_records_list, extract_speed_samples, extract_altitude_samples,
        extract_track_samples, extract_iso_samples, extract_exposure_samples,
        extract_temperature_samples, smooth_speed_samples, interpolate_value,
        load_json_with_fallback,
    )
    records = ensure_records_list(load_json_with_fallback(ROOT / "Video" / "GX020079.json"))
    tm = TelemetryDataManager(
        extract_speed_fn=extract_speed_samples,
        extract_altitude_fn=extract_altitude_samples,
        extract_track_fn=extract_track_samples,
        extract_iso_fn=extract_iso_samples,
        extract_exposure_fn=extract_exposure_samples,
        extract_temperature_fn=extract_temperature_samples,
        smooth_fn=smooth_speed_samples,
        interpolate_fn=interpolate_value,
    )
    tm.load_gpmf_records(records)
    tm.load_fit(ROOT / "Video" / "Morning_Ride.fit")
    tm.start_dt_utc = datetime(2026, 8, 5, 4, 28, 11)
    return tm


def main() -> int:
    # Clean ALL AMD_* env so the REAL production defaults are exercised.
    for k in list(os.environ.keys()):
        if k.startswith("AMD_"):
            os.environ.pop(k, None)
    os.environ["QT_QPA_PLATFORM"] = "offscreen"

    from src.gui.qt._mixins.render_mixin import RenderMixin

    stub = _Stub()
    out = ROOT / "Raporty" / "AMD_ETAP5G" / "l5gui_real.mp4"
    options = {"encoder": "amd", "output": str(out),
               "resolution": "source", "bitrate": "40M"}
    t0 = time.time()
    stats = RenderMixin._render_pipeline(stub, options)
    wall = time.time() - t0
    print(f"\nREAL GUI render wall = {wall:.3f} s", flush=True)

    profile = out.with_suffix(out.suffix + ".amd_profile.json")
    if not profile.exists():
        print("NO profile — native export did not run!", flush=True)
        return 1
    d = json.loads(profile.read_text(encoding="utf-8"))
    fa = d.get("frame_accounting", {})
    amf = d.get("amf", {})
    e5l = d.get("etap5l", {})
    print("TRUE FPS:", d.get("true_fps", 0.0), flush=True)
    print("muxed:", fa.get("muxed_frames"), "amf_sub:", fa.get("amf_submitted"),
          "amf_out:", fa.get("amf_output"), "vp:", fa.get("vp_processed"), flush=True)
    print("cadence_gpu:", fa.get("cadence_gpu"), "hr_gpu:", fa.get("hr_gpu"),
          "map_gpu:", fa.get("map_gpu"), "gauge_gpu:", e5l.get("gauge_gpu_frames"), flush=True)
    print("dropped:", amf.get("dropped_submissions"), "input_full:",
          amf.get("input_full_count"), flush=True)
    print("native_decode_mode:", d.get("frame_accounting", {}).get("mf_d3d11_surfaces"),
          flush=True)
    return 0 if fa.get("muxed_frames") == 1131 and amf.get("dropped_submissions") == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
