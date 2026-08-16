"""ETAP 5T — diagnostic workload-off tests (spec 20-26).

Each run disables exactly ONE GPU overlay category (diagnostic only, production
default unchanged):
  * MAP OFF    -> AMD_MAP_PATH=CPU_REFERENCE
  * GAUGE OFF  -> AMD_GAUGE_PATH=CPU_REFERENCE
  * CHARTS OFF -> AMD_CHART_PATH=CPU_REFERENCE
  * HUD OFF    -> AMD_GPU_HUD_OFF=1
Baseline = full (all GPU).  GPU timestamp profiling ON to measure GPU cadence.
Reports wall FPS + GPU frame span/cadence delta.
"""
from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY = r"c:/_DEV/TeleM/.venv-1/Scripts/python.exe"
RUNNER = ROOT / "scratch" / "run_etap5g_export.py"
OUT = ROOT / "Raporty" / "AMD_ETAP5G"


def _env(overrides: dict) -> dict:
    env = dict(os.environ)
    for flag in ("AMD_GAUGE_AB_READBACK", "AMD_MAP_AB_READBACK", "AMD_CHART_AB_READBACK",
                 "AMD_CHART_STATIC_READBACK", "AMD_NATIVE_DIAGNOSTICS", "AMD_NATIVE_PROFILING",
                 "AMD_OVERLAY_PROFILE", "AMD_MAP_STATS", "AMD_TELEMETRY_MODE",
                 "AMD_FRAME_ACCOUNTING", "AMD_AMF_DIAG", "AMD_COMPOSE_5Q",
                 "AMD_NATIVE_FRAME_ACCOUNTING", "AMD_VP_STATE_MODE",
                 "AMD_GPU_TIMESTAMP_PROFILE", "AMD_MAP_PATH", "AMD_MAP_FILTER",
                 "AMD_CHART_PATH", "AMD_GAUGE_PATH", "AMD_GPU_HUD_OFF"):
        env.pop(flag, None)
    env["AMD_MAP_PATH"] = "GPU"
    env["AMD_MAP_FILTER"] = "LANCZOS"
    env["AMD_CHART_PATH"] = "GPU_SPLIT"
    env["AMD_GAUGE_PATH"] = "GPU"
    env["AMD_COMPOSE_5Q"] = "OPTIMIZED"
    env["AMD_VP_STATE_MODE"] = "REFERENCE"
    env["AMD_GPU_TIMESTAMP_PROFILE"] = "1"
    env.update(overrides)
    return env


def _median_ms_from_csv(csv_path, col):
    if not csv_path.exists():
        return None
    import csv as _csv, statistics as _stat
    vals = []
    with csv_path.open(encoding="utf-8") as fh:
        for r in _csv.DictReader(fh):
            try:
                vals.append(float(r[col]))
            except (ValueError, KeyError):
                pass
    return _stat.median(vals) if vals else None


def _run(tag: str, overrides: dict) -> dict:
    mp4 = OUT / f"l5t_{tag}.mp4"
    t0 = time.time()
    proc = subprocess.run(
        [PY, str(RUNNER), "--frames", "1131", "--chart-path", "GPU_SPLIT",
         "--gauge-path", "GPU", "--output", str(mp4)],
        cwd=str(ROOT), env=_env(overrides), capture_output=True, text=True,
    )
    wall = time.time() - t0
    profile = mp4.with_suffix(mp4.suffix + ".amd_profile.json")
    gtl = mp4.with_suffix(mp4.suffix + ".gpu_timeline.csv")
    fps = json.loads(profile.read_text(encoding="utf-8")).get("true_fps", 0.0) if profile.exists() else 0.0
    rec = {
        "tag": tag, "overrides": overrides, "wall": wall, "true_fps": fps,
        "gpu_span_med": _median_ms_from_csv(gtl, "span_ms"),
        "gpu_cadence_med": None,
    }
    if gtl.exists():
        import csv as _csv, statistics as _stat
        b = []
        with gtl.open(encoding="utf-8") as fh:
            rows = [_r for _r in _csv.DictReader(fh)]
        for i in range(len(rows) - 1):
            try:
                b.append((float(rows[i + 1]["begin_ts"]) - float(rows[i]["begin_ts"]))
                         / float(rows[i]["freq"]) * 1000.0)
            except (ValueError, KeyError, ZeroDivisionError):
                pass
        rec["gpu_cadence_med"] = _stat.median(b) if b else None
    print(f"[{tag}] {list(overrides.keys()) or 'FULL'} wall={wall:.2f}s FPS={fps:.2f} "
          f"span_med={rec['gpu_span_med']} cadence_med={rec['gpu_cadence_med']}", flush=True)
    return rec


def main() -> int:
    runs = {}
    runs["full"] = _run("full", {})
    runs["map_off"] = _run("map_off", {"AMD_MAP_PATH": "CPU_REFERENCE"})
    runs["gauge_off"] = _run("gauge_off", {"AMD_GAUGE_PATH": "CPU_REFERENCE"})
    runs["charts_off"] = _run("charts_off", {"AMD_CHART_PATH": "CPU_REFERENCE"})
    runs["hud_off"] = _run("hud_off", {"AMD_GPU_HUD_OFF": "1"})
    report = {"runs": runs}
    base_fps = runs["full"]["true_fps"]
    base_span = runs["full"]["gpu_span_med"]
    print("\n=== WORKLOAD-OFF DELTAS (vs FULL) ===")
    for tag in ("map_off", "gauge_off", "charts_off", "hud_off"):
        r = runs[tag]
        d_fps = r["true_fps"] - base_fps
        d_span = (r["gpu_span_med"] - base_span) if (r["gpu_span_med"] and base_span) else None
        print(f"  {tag:10s} FPS {base_fps:.2f}->{r['true_fps']:.2f} ({d_fps:+.2f})  "
              f"GPU span {base_span:.2f}->{r['gpu_span_med']:.2f} "
              f"({d_span:+.2f} ms)" if d_span is not None else f"  {tag:10s} FPS {base_fps:.2f}->{r['true_fps']:.2f} ({d_fps:+.2f})", flush=True)
    (OUT / "etap5t_workload_off.json").write_text(json.dumps(report, indent=2, default=str),
                                                  encoding="utf-8")
    print(f"\nJSON: {OUT / 'etap5t_workload_off.json'}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
