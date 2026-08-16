"""ETAP 5W — fresh-process control (spec 19).

Runs the SAME export 10 times, each as a SEPARATE fresh process (subprocess),
and records each process's peak Working Set.  If fresh processes are stable
(similar peak) while a long-lived process grew linearly, the problem was
lifecycle/cache/allocator in the long-lived process — not a per-export leak.
"""
from __future__ import annotations

import json
import os
import statistics
import subprocess
import time
from pathlib import Path

import psutil

ROOT = Path(__file__).resolve().parents[1]
PY = r"c:/_DEV/TeleM/.venv-1/Scripts/python.exe"
RUNNER = ROOT / "scratch" / "run_etap5g_export.py"
OUT = ROOT / "Raporty" / "AMD_ETAP5G"
N = int(os.environ.get("ETAP5W_FRESH", "10"))


def _env() -> dict:
    env = dict(os.environ)
    for flag in ("AMD_GAUGE_AB_READBACK", "AMD_MAP_AB_READBACK", "AMD_CHART_AB_READBACK",
                 "AMD_CHART_STATIC_READBACK", "AMD_NATIVE_DIAGNOSTICS", "AMD_NATIVE_PROFILING",
                 "AMD_OVERLAY_PROFILE", "AMD_MAP_STATS", "AMD_TELEMETRY_MODE",
                 "AMD_FRAME_ACCOUNTING", "AMD_AMF_DIAG", "AMD_COMPOSE_5Q",
                 "AMD_NATIVE_FRAME_ACCOUNTING", "AMD_VP_STATE_MODE",
                 "AMD_GPU_TIMESTAMP_PROFILE", "AMD_AMF_MODE", "AMD_AMF_QUERY_MODE",
                 "AMD_VP_POOL_SIZE", "AMD_POOL_LIFECYCLE_STATS", "AMD_CHART_PATH",
                 "AMD_GAUGE_PATH"):
        env.pop(flag, None)
    env["AMD_MAP_PATH"] = "GPU"
    env["AMD_MAP_FILTER"] = "LANCZOS"
    env["AMD_COMPOSE_5Q"] = "OPTIMIZED"
    env["AMD_VP_STATE_MODE"] = "REFERENCE"
    env["AMD_VP_POOL_SIZE"] = "8"
    return env


def _run_fresh(idx: int) -> dict:
    mp4 = OUT / f"l5w_fresh_{idx:02d}.mp4"
    t0 = time.time()
    proc = subprocess.Popen(
        [PY, str(RUNNER), "--frames", "1131", "--chart-path", "GPU_SPLIT",
         "--gauge-path", "GPU", "--output", str(mp4)],
        cwd=str(ROOT), env=_env(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    peak = 0
    try:
        p = psutil.Process(proc.pid)
        while proc.poll() is None:
            try:
                mem = p.memory_info().rss
                if mem > peak:
                    peak = mem
            except Exception:
                pass
            time.sleep(0.05)
    except Exception:
        pass
    wall = time.time() - t0
    rec = {"idx": idx, "wall": wall, "peak_ws_mb": peak / 1e6,
           "rc": proc.returncode}
    print(f"fresh {idx:02d} wall={wall:.2f}s peak_ws={peak/1e6:.0f}MB rc={proc.returncode}",
          flush=True)
    return rec


def main() -> int:
    runs = [_run_fresh(i) for i in range(1, N + 1)]
    peaks = [r["peak_ws_mb"] for r in runs]
    report = {
        "runs": runs,
        "peak_ws_mb": {"med": statistics.median(peaks), "min": min(peaks),
                       "max": max(peaks), "spread_pct": (max(peaks) - min(peaks)) / max(peaks) * 100},
    }
    (OUT / "etap5w_freshproc.json").write_text(json.dumps(report, indent=2, default=str),
                                               encoding="utf-8")
    print(f"\nfresh-process peak WS: med {report['peak_ws_mb']['med']:.0f}MB "
          f"min {report['peak_ws_mb']['min']:.0f} max {report['peak_ws_mb']['max']:.0f} "
          f"spread {report['peak_ws_mb']['spread_pct']:.1f}%", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
