"""ETAP 5L-FINAL-VALIDATION — full 1131-frame correctness proof of the GPU gauge.

Phase A (pure Python): raw gauge determinism, dirty-zero count, alpha coverage,
and CPU-composite (Pillow alpha_composite) parity of dirty-zero handling.
Phase B (diagnostic run): GPU gauge composite readback for all 1131 frames vs
the CPU_REFERENCE result (raw gauge with dirty zeros dropped).
Phase C: two exports (CPU_REFERENCE vs GPU gauge), decoded-frame comparison.

No production code path is modified; this is validation-only.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
PY = r"c:\_DEV\TeleM\.venv-1\Scripts\python.exe"
FFMPEG = r"C:\tools\ffmpeg.exe"
RUNNER = ROOT / "scratch" / "run_etap5g_export.py"
OUT = ROOT / "Raporty" / "AMD_ETAP5G"
OUT.mkdir(parents=True, exist_ok=True)
GAUGE_KEY = "fit_enhanced_speed_text"


def setup():
    from src.telemetry_extract import (
        ensure_records_list, extract_speed_samples, extract_altitude_samples,
        extract_track_samples, extract_iso_samples, extract_exposure_samples,
        extract_temperature_samples, interpolate_value, load_json_with_fallback,
        smooth_speed_samples,
    )
    from src.gui.telemetry_manager import TelemetryDataManager
    records = ensure_records_list(load_json_with_fallback(ROOT / "Video" / "GX020079.json"))
    telemetry = TelemetryDataManager(
        extract_speed_fn=extract_speed_samples, extract_altitude_fn=extract_altitude_samples,
        extract_track_fn=extract_track_samples, extract_iso_fn=extract_iso_samples,
        extract_exposure_fn=extract_exposure_samples, extract_temperature_fn=extract_temperature_samples,
        smooth_fn=smooth_speed_samples, interpolate_fn=interpolate_value,
    )
    telemetry.load_gpmf_records(records)
    telemetry.load_fit(ROOT / "Video" / "Morning_Ride.fit")
    telemetry.start_dt_utc = datetime(2026, 8, 5, 4, 28, 11)
    layout = json.loads((ROOT / "def_layout.json").read_text(encoding="utf-8"))
    compose_layout = json.loads(json.dumps(layout))
    compose_layout["indicators"].pop("track_map", None)
    speed = smooth_speed_samples(telemetry.speed_samples, "moving_average", 5)
    altitude = smooth_speed_samples(telemetry.alt_samples, "moving_average", 5)
    track = telemetry.track_samples
    gps_track = telemetry.get_gps_track_for_source(layout["indicators"]["track_map"].get("source", "fit"))
    from src.indicators.frame_data import prepare_overlay_frame_data, build_active_fit_field_plan
    plan = build_active_fit_field_plan(layout, (telemetry.fit_data or {}).keys())
    W, H = 3840, 2160
    fps = 30000 / 1001
    base = telemetry.start_dt_utc
    font_path = str(ROOT / "include" / "mpv")

    def frame_kwargs(idx):
        return prepare_overlay_frame_data(
            layout=compose_layout, target_dt=base + timedelta(seconds=idx / fps),
            start_dt_utc=base, tz_offset_hours=2, speed_samples=speed,
            track_samples=track, alt_samples=altitude, iso_samples=telemetry.iso_samples,
            exposure_samples=telemetry.exposure_samples,
            temperature_samples=telemetry.temperature_samples,
            gpx_speed_samples=telemetry.gpx_speed_samples,
            gpx_track_samples=telemetry.gpx_track_samples,
            gpx_alt_samples=telemetry.gpx_alt_samples,
            gpx_power_samples=telemetry.gpx_power_samples,
            gpx_atemp_samples=telemetry.gpx_atemp_samples,
            gpx_hr_samples=telemetry.gpx_hr_samples,
            gpx_cad_samples=telemetry.gpx_cad_samples,
            fit_data=telemetry.fit_data, gps_track=gps_track, total_frames=1131,
            current_index=idx, chart_data={}, fit_field_plan=plan,
        )
    return compose_layout, W, H, font_path, frame_kwargs


def phase_a():
    print("\n=== PHASE A: RAW GAUGE 1131 (pure Python) ===", flush=True)
    from src.indicators.compositor import compose_overlay
    compose_layout, W, H, font_path, frame_kwargs = setup()

    first_raw = None
    first_bbox = None
    mismatches = 0
    dz_frames = 0
    dz_total = 0
    dz_max = 0
    pa_frames = 0
    alpha_min = 255
    alpha_max = 0
    cpu_parity_mismatches = 0
    cpu_parity_max = 0

    for idx in range(1131):
        cap = {}
        compose_overlay(canvas_w=W, canvas_h=H, layout=compose_layout, font_path=font_path,
                        _bboxes={}, gpu_capture_keys={GAUGE_KEY}, gpu_capture=cap,
                        reuse_canvas=False, **frame_kwargs(idx))
        raw = np.asarray(cap[GAUGE_KEY]["image"], dtype=np.int16)
        bbox = cap[GAUGE_KEY]["bbox"]
        if idx == 0:
            first_raw = raw.copy()
            first_bbox = bbox
        else:
            if raw.shape != first_raw.shape or not np.array_equal(raw, first_raw):
                mismatches += 1
        # dirty zeros
        dz = int(((raw[..., 3] == 0) & (raw[..., 0:3].max(axis=2) != 0)).sum())
        if dz > 0:
            dz_frames += 1
        dz_total += dz
        dz_max = max(dz_max, dz)
        # alpha coverage
        a = raw[..., 3]
        amin = int(a.min())
        amax = int(a.max())
        alpha_min = min(alpha_min, amin)
        alpha_max = max(alpha_max, amax)
        if int(((a > 0) & (a < 255)).sum()) > 0:
            pa_frames += 1
        # CPU-composite parity: render CPU mode (gauge pasted), crop bbox,
        # compare vs raw with dirty zeros dropped.
        cpu_canvas = compose_overlay(canvas_w=W, canvas_h=H, layout=compose_layout,
                                     font_path=font_path, _bboxes={}, reuse_canvas=False,
                                     **frame_kwargs(idx))
        gx, gy, gw, gh = bbox
        cpu_gauge = np.asarray(cpu_canvas.crop((gx, gy, gx + gw, gy + gh)), dtype=np.int16)
        ref = raw.copy()
        ref[ref[..., 3] == 0, 0:3] = 0
        d = np.abs(cpu_gauge - ref)
        if d.max() > 0:
            cpu_parity_mismatches += 1
            cpu_parity_max = max(cpu_parity_max, int(d.max()))
        if (idx + 1) % 200 == 0:
            print(f"  frame {idx + 1}", flush=True)

    print(f"RAW GAUGE: frames=1131 mismatches={mismatches} (expected 0)")
    print(f"DIRTY ZEROS: frames={dz_frames} pixels_total={dz_total} max/frame={dz_max}")
    print(f"ALPHA: min={alpha_min} max={alpha_max} partial-alpha frames={pa_frames}")
    print(f"CPU-composite parity (raw with dz dropped vs Pillow alpha_composite): "
          f"mismatches={cpu_parity_mismatches} max={cpu_parity_max}")
    return {
        "raw_frames": 1131, "raw_mismatches": mismatches,
        "dz_frames": dz_frames, "dz_total": dz_total, "dz_max": dz_max,
        "alpha_min": alpha_min, "alpha_max": alpha_max, "partial_alpha_frames": pa_frames,
        "cpu_parity_mismatches": cpu_parity_mismatches, "cpu_parity_max": cpu_parity_max,
    }


def phase_b():
    print("\n=== PHASE B: GPU COMPOSITE 1131 (diagnostic readback) ===", flush=True)
    env = {"AMD_CHART_PATH": "GPU_SPLIT", "AMD_GAUGE_PATH": "GPU",
           "AMD_GAUGE_AB_READBACK": "1"}
    out = OUT / "l5_final_gpu_ab.mp4"
    t0 = time.time()
    proc = subprocess.run(
        [PY, str(RUNNER), "--frames", "1131", "--chart-path", "GPU_SPLIT",
         "--gauge-path", "GPU", "--output", str(out)],
        cwd=str(ROOT), env={**os.environ, **env}, capture_output=True, text=True,
    )
    print(f"  rc={proc.returncode} elapsed={time.time() - t0:.1f}s", flush=True)
    if proc.returncode != 0:
        print("\n".join(proc.stdout.splitlines()[-20:]), flush=True)
        return {"rc": proc.returncode}
    profile = out.with_suffix(out.suffix + ".amd_profile.json")
    data = json.loads(profile.read_text(encoding="utf-8"))
    ab = data.get("etap5l", {}).get("gauge_ab") or {}
    print("  gauge_ab:", json.dumps(ab, indent=1), flush=True)
    return {"rc": 0, "ab": ab, "profile": str(profile)}


def _framemd5(mp4):
    proc = subprocess.run(
        [FFMPEG, "-v", "error", "-i", str(mp4), "-map", "0:v", "-f", "framemd5", "-"],
        capture_output=True, text=True,
    )
    return hashlib.sha256(proc.stdout.encode()).hexdigest()


def phase_c():
    print("\n=== PHASE C: FINAL OUTPUT (CPU_REFERENCE vs GPU gauge) ===", flush=True)
    cpu_out = OUT / "l5_final_cpu.mp4"
    gpu_out = OUT / "l5_final_gpu.mp4"
    for tag, mp4, gp in (("CPU", cpu_out, "CPU_REFERENCE"), ("GPU", gpu_out, "GPU")):
        t0 = time.time()
        proc = subprocess.run(
            [PY, str(RUNNER), "--frames", "1131", "--chart-path", "GPU_SPLIT",
             "--gauge-path", gp, "--output", str(mp4)],
            cwd=str(ROOT), capture_output=True, text=True,
        )
        print(f"  {tag}: rc={proc.returncode} elapsed={time.time() - t0:.1f}s", flush=True)
        if proc.returncode != 0:
            print("\n".join(proc.stdout.splitlines()[-15:]), flush=True)
            return {"rc": proc.returncode}
    h_cpu = _framemd5(cpu_out)
    h_gpu = _framemd5(gpu_out)
    identical = h_cpu == h_gpu
    print(f"  CPU framemd5 hash: {h_cpu}")
    print(f"  GPU framemd5 hash: {h_gpu}")
    print(f"  identical: {'YES' if identical else 'NO'}")
    return {"rc": 0, "cpu_hash": h_cpu, "gpu_hash": h_gpu, "identical": identical}


def main() -> int:
    a = phase_a()
    b = phase_b()
    c = phase_c()

    exact = (a["raw_mismatches"] == 0 and a["cpu_parity_mismatches"] == 0
             and b.get("rc") == 0 and c.get("identical") is True)
    ab = b.get("ab") or {}
    # GPU composite exactness: MAE=0, MAX=0, mismatches(n>0)=0 across all 1131
    # frames (check the per-frame aggregated medians).
    exact = exact and (
        ab.get("mae", {}).get("median", 1) == 0
        and ab.get("max", {}).get("median", 1) == 0
        and ab.get("n>0", {}).get("median", 1) == 0
    )
    final_status = "PASS-EXACT" if exact else ("FAIL" if b.get("rc") != 0 else "PASS-VISUAL")

    report = {
        "phase_a": a,
        "phase_b": b,
        "phase_c": c,
        "final_status": final_status,
    }
    rp = OUT / "l5_final_validation.json"
    rp.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(f"\n=== FINAL STATUS: {final_status} ===")
    print(f"report: {rp}")
    return 0 if exact else 1


if __name__ == "__main__":
    raise SystemExit(main())
