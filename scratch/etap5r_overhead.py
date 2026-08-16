"""ETAP 5R — clean native-only instrumentation overhead (A2 off / B2 native only)."""
import json
import os
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY = r"c:/_DEV/TeleM/.venv-1/Scripts/python.exe"
RUNNER = ROOT / "scratch" / "run_etap5g_export.py"
OUT = ROOT / "Raporty" / "AMD_ETAP5G"


def _env(native_fa: bool) -> dict:
    env = dict(os.environ)
    for flag in ("AMD_GAUGE_AB_READBACK", "AMD_MAP_AB_READBACK", "AMD_CHART_AB_READBACK",
                 "AMD_CHART_STATIC_READBACK", "AMD_NATIVE_DIAGNOSTICS", "AMD_NATIVE_PROFILING",
                 "AMD_OVERLAY_PROFILE", "AMD_MAP_STATS", "AMD_TELEMETRY_MODE",
                 "AMD_FRAME_ACCOUNTING", "AMD_AMF_DIAG", "AMD_COMPOSE_5Q",
                 "AMD_NATIVE_FRAME_ACCOUNTING"):
        env.pop(flag, None)
    env["AMD_MAP_PATH"] = "GPU"
    env["AMD_MAP_FILTER"] = "LANCZOS"
    env["AMD_COMPOSE_5Q"] = "OPTIMIZED"
    if native_fa:
        env["AMD_NATIVE_FRAME_ACCOUNTING"] = "1"
    return env


def _run(tag: str, native_fa: bool) -> dict:
    mp4 = OUT / f"l5r_{tag}.mp4"
    t0 = time.time()
    subprocess.run(
        [PY, str(RUNNER), "--frames", "1131", "--chart-path", "GPU_SPLIT",
         "--gauge-path", "GPU", "--output", str(mp4)],
        cwd=str(ROOT), env=_env(native_fa), capture_output=True, text=True,
    )
    wall = time.time() - t0
    profile = mp4.with_suffix(mp4.suffix + ".amd_profile.json")
    fps = json.loads(profile.read_text(encoding="utf-8")).get("true_fps", 0.0) if profile.exists() else 0.0
    print(f"[{tag}] native_fa={native_fa} wall={wall:.2f}s FPS={fps:.2f}", flush=True)
    return {"tag": tag, "wall": wall, "fps": fps}


def main() -> int:
    A2 = _run("A2", False)
    B2 = _run("B2", True)
    ovh = (B2["wall"] - A2["wall"]) / A2["wall"] * 100.0
    print(f"\nNative-only instrumentation overhead (B2-A2)/A2: {ovh:.2f}%", flush=True)
    (OUT / "etap5r_overhead_native.json").write_text(
        json.dumps({"A2": A2, "B2": B2, "overhead_pct": ovh}, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
