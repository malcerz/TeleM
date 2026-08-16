"""ETAP 5M — production baseline (RUN A/B/C/D), measurement only.

Runs the full production pipeline 4x back-to-back with a fixed env, validates
the required path in every run, collects wall-clock / TRUE FPS / stage timings,
then aggregates a stable baseline.  Does NOT modify production code.
"""
from __future__ import annotations

import json
import os
import statistics
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

PY = r"c:/_DEV/TeleM/.venv-1/Scripts/python.exe"
RUNNER = ROOT / "scratch" / "run_etap5g_export.py"
OUT = ROOT / "Raporty" / "AMD_ETAP5G"
OUT.mkdir(parents=True, exist_ok=True)

SOURCE_FPS = 29.97

# Remove any leftover diagnostic/profiling flags so every run is a clean
# production run; force the full production path.
def _clean_env() -> dict[str, str]:
    env = dict(os.environ)
    for flag in (
        "AMD_GAUGE_AB_READBACK", "AMD_MAP_AB_READBACK", "AMD_CHART_AB_READBACK",
        "AMD_CHART_STATIC_READBACK", "AMD_NATIVE_DIAGNOSTICS", "AMD_NATIVE_PROFILING",
        "AMD_OVERLAY_PROFILE", "AMD_MAP_STATS", "AMD_NATIVE_LEGACY_NO_HUD",
    ):
        env.pop(flag, None)
    env["AMD_MAP_PATH"] = "GPU"
    env["AMD_MAP_FILTER"] = "LANCZOS"
    return env


STAGE_KEYS = [
    "Telemetry/frame_data", "compose_overlay", "HUD dirty bbox", "HUD dirty extract",
    "PIL/buffer preparation", "update_hud", "Python->native bridge", "map_cpu_upload",
    "gauge_tobytes", "gauge_upload", "chart_dynamic_tobytes", "chart_dynamic_upload",
    "VideoProcessor CPU submit", "GPU chart blend submit", "GPU gauge blend submit",
    "GPU map resize+blend submit", "GPU wait/synchronization", "AMF submit/backpressure",
    "AMF QueryOutput", "Packet write", "MF ReadSample/decode availability",
]


def _run(tag: str, env: dict[str, str]) -> dict:
    mp4 = OUT / f"5m_run_{tag}.mp4"
    t0 = time.time()
    proc = subprocess.run(
        [PY, str(RUNNER), "--frames", "1131", "--chart-path", "GPU_SPLIT",
         "--gauge-path", "GPU", "--output", str(mp4)],
        cwd=str(ROOT), env=env, capture_output=True, text=True,
    )
    wall = time.time() - t0
    rc = proc.returncode
    profile = mp4.with_suffix(mp4.suffix + ".amd_profile.json")
    if rc != 0 or not profile.exists():
        tail = "\n".join(proc.stdout.splitlines()[-25:])
        print(f"[{tag}] rc={rc} wall={wall:.2f}s INVALID (run failed)\n{tail}", flush=True)
        return {"tag": tag, "rc": rc, "wall": wall, "valid": False}

    data = json.loads(profile.read_text(encoding="utf-8"))
    e4 = data.get("etap4", {})
    e5g = data.get("etap5g", {})
    e5l = data.get("etap5l", {})
    fa = data.get("frame_accounting", {})
    amf = data.get("amf", {})

    path_ok = (
        e4.get("decode_mode") == "GPU_HUD_D3D11VA"
        and e4.get("hardware_acceleration_confirmed") is True
        and e4.get("decoder_output_format") == "DXGI_FORMAT_P010"
        and e4.get("direct_decoder_surface_to_vp_frames") == 1131
        and e4.get("rawvideo_pipe") is False
        and e4.get("cpu_to_gpu_base_bytes_per_frame") == 0
        and e4.get("gpu_to_cpu_base_bytes_per_frame") == 0
        and fa.get("cadence_gpu") == 1131
        and fa.get("hr_gpu") == 1131
        and fa.get("map_gpu") == 1131
        and e5l.get("gauge_gpu_frames") == 1131
        and fa.get("amf_submitted") == 1131
        and fa.get("amf_output") == 1131
        and fa.get("muxed_frames") == 1131
        and amf.get("dropped_submissions") == 0
        and data.get("diagnostics_enabled") is False
        and data.get("profiling_enabled") is False
    )

    timings = data.get("timings", {})
    stage_med = {
        key: (timings.get(key, {}).get("median_ms") or 0.0)
        for key in STAGE_KEYS
    }

    rec = {
        "tag": tag, "rc": rc, "wall": wall,
        "true_fps": data.get("true_fps", 0.0),
        "valid": path_ok,
        "decode": e4.get("decode_mode"),
        "p010": e4.get("decoder_output_format"),
        "direct_to_vp": e4.get("direct_decoder_surface_to_vp_frames"),
        "cadence_gpu": fa.get("cadence_gpu"),
        "hr_gpu": fa.get("hr_gpu"),
        "map_gpu": fa.get("map_gpu"),
        "gauge_gpu": e5l.get("gauge_gpu_frames"),
        "cpu_to_gpu_base": e4.get("cpu_to_gpu_base_bytes_per_frame"),
        "gpu_to_cpu_base": e4.get("gpu_to_cpu_base_bytes_per_frame"),
        "amf_submitted": fa.get("amf_submitted"),
        "amf_output": fa.get("amf_output"),
        "muxed": fa.get("muxed_frames"),
        "drops": amf.get("dropped_submissions"),
        "gauge_upload_mib": e5l.get("gauge_upload_mib_per_frame"),
        "map_upload_mib": e5g.get("map_upload_mib_per_frame"),
        "stage_med": stage_med,
    }
    print(f"[{tag}] rc={rc} wall={wall:.3f}s FPS={rec['true_fps']:.3f} valid={path_ok}",
          flush=True)
    return rec


def main() -> int:
    env = _clean_env()
    runs: dict[str, dict] = {}
    for tag in ("A", "B", "C", "D"):
        runs[tag] = _run(tag, env)

    valid = [r for r in runs.values() if r["valid"]]
    report = {
        "status": "PASS" if len(valid) == 4 else "INVALID",
        "source_fps": SOURCE_FPS,
        "runs": runs,
        "aggregate": None,
        "realtime": None,
    }

    if valid:
        fps = [r["true_fps"] for r in valid]
        walls = [r["wall"] for r in valid]
        med = statistics.median(fps)
        stddev = statistics.stdev(fps) if len(fps) > 1 else 0.0
        spread = (max(fps) - min(fps)) / med * 100.0
        report["aggregate"] = {
            "median_fps": med, "min_fps": min(fps), "max_fps": max(fps),
            "stddev": stddev, "spread_pct": spread,
            "median_wall": statistics.median(walls),
            "min_wall": min(walls), "max_wall": max(walls),
        }
        factor = med / SOURCE_FPS
        report["realtime"] = {
            "factor": factor,
            "margin_pct": (med - SOURCE_FPS) / SOURCE_FPS * 100.0,
        }

    out = OUT / "etap5m_baseline.json"
    out.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print("\n" + "=" * 60, flush=True)
    print("ETAP 5M BASELINE", flush=True)
    print(f"  STATUS: {report['status']}", flush=True)
    for tag in ("A", "B", "C", "D"):
        r = runs[tag]
        print(f"  {tag}: wall={r['wall']:.3f}s FPS={r['true_fps']:.3f} valid={r['valid']}",
              flush=True)
    if report["aggregate"]:
        agg = report["aggregate"]
        rt = report["realtime"]
        print(f"  MEDIAN FPS: {agg['median_fps']:.3f}", flush=True)
        print(f"  MIN: {agg['min_fps']:.3f}  MAX: {agg['max_fps']:.3f}", flush=True)
        print(f"  STDDEV: {agg['stddev']:.4f}  SPREAD: {agg['spread_pct']:.2f} %",
              flush=True)
        print(f"  MEDIAN WALL: {agg['median_wall']:.3f} s", flush=True)
        print(f"  REALTIME factor: {rt['factor']:.3f}x  margin: {rt['margin_pct']:.2f} %",
              flush=True)
    print(f"  JSON: {out}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
