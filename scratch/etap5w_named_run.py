"""ETAP 5W — named-handle growth diagnosis (spec 14).

Runs 2 exports and dumps named Event/Mutant/Section/Thread handles before and
after each, to identify which named objects appear per export (leak markers).
"""
from __future__ import annotations

import contextlib
import gc
import io
import json
import os
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scratch"))
OUT = ROOT / "Raporty" / "AMD_ETAP5G"
FF = r"C:\tools\ffmpeg.exe"

from etap5w_handles_named import handle_types_with_names  # noqa: E402


def _setup_env() -> None:
    amf_mode = os.environ.get("ETAP5W_AMF_MODE", "ENCODE").strip().upper()
    flags = ("AMD_GAUGE_AB_READBACK", "AMD_MAP_AB_READBACK", "AMD_CHART_AB_READBACK",
             "AMD_CHART_STATIC_READBACK", "AMD_NATIVE_DIAGNOSTICS", "AMD_NATIVE_PROFILING",
             "AMD_OVERLAY_PROFILE", "AMD_MAP_STATS", "AMD_TELEMETRY_MODE",
             "AMD_FRAME_ACCOUNTING", "AMD_AMF_DIAG", "AMD_COMPOSE_5Q",
             "AMD_NATIVE_FRAME_ACCOUNTING", "AMD_VP_STATE_MODE",
             "AMD_GPU_TIMESTAMP_PROFILE", "AMD_AMF_MODE", "AMD_AMF_QUERY_MODE",
             "AMD_VP_POOL_SIZE", "AMD_POOL_LIFECYCLE_STATS", "AMD_CHART_PATH",
             "AMD_GAUGE_PATH")
    for f in flags:
        os.environ.pop(f, None)
    os.environ.update({
        "AMD_MAP_PATH": "GPU", "AMD_MAP_FILTER": "LANCZOS",
        "AMD_COMPOSE_5Q": "OPTIMIZED", "AMD_VP_STATE_MODE": "REFERENCE",
        "AMD_VP_POOL_SIZE": "8", "AMD_CHART_PATH": "GPU_SPLIT",
        "AMD_GAUGE_PATH": "GPU", "AMD_AMF_MODE": amf_mode,
    })


def _named_by_type() -> dict:
    handles = handle_types_with_names()
    by = {}
    for t, n in handles:
        by.setdefault(t, []).append(n)
    return by


def _dump(label: str, by: dict) -> None:
    print(f"\n=== {label} ===", flush=True)
    for t in ("Event", "Mutant", "Thread", "Section", "Semaphore", "IoCompletion"):
        items = by.get(t, [])
        named = [n for n in items if n]
        print(f"  {t:16s} total={len(items)} named={len(named)}", flush=True)
        seen = Counter(named)
        for n, c in seen.most_common(8):
            print(f"      x{c} {n}", flush=True)


def main() -> int:
    _setup_env()

    from src.ffmpeg.streaming import stream_overlay_to_ffmpeg
    from src.gui.layout_manager import resolve_font_path
    from src.gui.telemetry_manager import TelemetryDataManager
    from src.telemetry_extract import (
        ensure_records_list, extract_speed_samples, extract_altitude_samples,
        extract_track_samples, extract_iso_samples, extract_exposure_samples,
        extract_temperature_samples, smooth_speed_samples, interpolate_value,
        load_json_with_fallback,
    )

    records = ensure_records_list(load_json_with_fallback(ROOT / "Video" / "GX020079.json"))
    telemetry = TelemetryDataManager(
        extract_speed_fn=extract_speed_samples,
        extract_altitude_fn=extract_altitude_samples,
        extract_track_fn=extract_track_samples,
        extract_iso_fn=extract_iso_samples,
        extract_exposure_fn=extract_exposure_samples,
        extract_temperature_fn=extract_temperature_samples,
        smooth_fn=smooth_speed_samples,
        interpolate_fn=interpolate_value,
    )
    telemetry.load_gpmf_records(records)
    telemetry.load_fit(ROOT / "Video" / "Morning_Ride.fit")
    telemetry.start_dt_utc = datetime(2026, 8, 5, 4, 28, 11)
    with (ROOT / "def_layout.json").open(encoding="utf-8") as handle:
        layout = json.load(handle)
    speed = smooth_speed_samples(telemetry.speed_samples, "moving_average", 5)
    altitude = smooth_speed_samples(telemetry.alt_samples, "moving_average", 5)
    track = telemetry.track_samples
    video = ROOT / "Video" / "GX020079.mp4"

    def _export(idx: int) -> float:
        mp4 = OUT / f"l5w_n_{idx}.mp4"
        buf = io.StringIO()
        t0 = time.time()
        with contextlib.redirect_stdout(buf):
            stream_overlay_to_ffmpeg(
                ffmpeg_exe=FF, input_files=[str(video)], output_file=str(mp4),
                duration_s=1131 * (1001.0 / 30000.0),
                start_dt_utc=telemetry.start_dt_utc, tz_offset_hours=2,
                speed_samples=speed, track_samples=track, alt_samples=altitude,
                font_path=resolve_font_path("Arial"), layout=layout,
                field_samples={"speed_samples": speed, "track_samples": track,
                               "alt_samples": altitude},
                max_distance_m=track[-1][1] if track else 0,
                target_fps=30000 / 1001, update_rate_step=1, workers=1,
                iso_samples=telemetry.iso_samples,
                exposure_samples=telemetry.exposure_samples,
                temperature_samples=telemetry.temperature_samples,
                gpx_speed_samples=telemetry.gpx_speed_samples,
                gpx_track_samples=telemetry.gpx_track_samples,
                gpx_alt_samples=telemetry.gpx_alt_samples,
                gpx_power_samples=telemetry.gpx_power_samples,
                gpx_atemp_samples=telemetry.gpx_atemp_samples,
                gpx_hr_samples=telemetry.gpx_hr_samples,
                gpx_cad_samples=telemetry.gpx_cad_samples,
                fit_data=telemetry.fit_data,
                gps_track=telemetry.get_gps_track_for_source(
                    layout.get("indicators", {}).get("track_map", {}).get("source", "fit")),
                encoder="amd", gpu=0, video_bitrate="40M", render_w=3840, render_h=2160,
                resolution_name="source", rotation_degrees=180, container_rotation=180,
                overlay_w=1920, overlay_h=1080,
            )
        return time.time() - t0

    gc.collect()
    _dump("BEFORE exports", _named_by_type())
    for idx in range(1, 3):
        wall = _export(idx)
        gc.collect()
        print(f"\nexp {idx} wall={wall:.2f}s", flush=True)
        _dump(f"AFTER export {idx}", _named_by_type())

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
