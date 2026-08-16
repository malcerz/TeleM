"""ETAP 5V — golden correctness: pool4 (reference) vs pool8 (candidate).

31 frames: pool4 vs pool8 -> framemd5 identical.
1131 frames: pool4 vs pool8 -> framemd5 identical, 1131/1131, drops=0.

Each run is a separate process (fresh native context).  profiling OFF,
diagnostics OFF, readbacks OFF.  Also captures [VP POOL] lifecycle stats
(AMD_POOL_LIFECYCLE_STATS=1) to confirm live=0 after destroy.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY = r"c:/_DEV/TeleM/.venv-1/Scripts/python.exe"
RUNNER = ROOT / "scratch" / "run_etap5g_export.py"
OUT = ROOT / "Raporty" / "AMD_ETAP5G"
FF = r"C:\tools\ffmpeg.exe"


def _env(pool: int, lifecycle: bool) -> dict:
    env = dict(os.environ)
    for flag in ("AMD_GAUGE_AB_READBACK", "AMD_MAP_AB_READBACK", "AMD_CHART_AB_READBACK",
                 "AMD_CHART_STATIC_READBACK", "AMD_NATIVE_DIAGNOSTICS", "AMD_NATIVE_PROFILING",
                 "AMD_OVERLAY_PROFILE", "AMD_MAP_STATS", "AMD_TELEMETRY_MODE",
                 "AMD_FRAME_ACCOUNTING", "AMD_AMF_DIAG", "AMD_COMPOSE_5Q",
                 "AMD_NATIVE_FRAME_ACCOUNTING", "AMD_VP_STATE_MODE",
                 "AMD_GPU_TIMESTAMP_PROFILE", "AMD_AMF_MODE", "AMD_AMF_QUERY_MODE",
                 "AMD_VP_POOL_SIZE", "AMD_POOL_LIFECYCLE_STATS"):
        env.pop(flag, None)
    env["AMD_MAP_PATH"] = "GPU"
    env["AMD_MAP_FILTER"] = "LANCZOS"
    env["AMD_COMPOSE_5Q"] = "OPTIMIZED"
    env["AMD_VP_STATE_MODE"] = "REFERENCE"
    env["AMD_VP_POOL_SIZE"] = str(pool)
    if lifecycle:
        env["AMD_POOL_LIFECYCLE_STATS"] = "1"
    return env


def _run(tag: str, frames: int, pool: int) -> dict:
    mp4 = OUT / f"l5v_{tag}.mp4"
    proc = subprocess.run(
        [PY, str(RUNNER), "--frames", str(frames), "--chart-path", "GPU_SPLIT",
         "--gauge-path", "GPU", "--output", str(mp4)],
        cwd=str(ROOT), env=_env(pool, lifecycle=True), capture_output=True, text=True,
    )
    profile = mp4.with_suffix(mp4.suffix + ".amd_profile.json")
    if proc.returncode != 0 or not profile.exists():
        print(f"[{tag}] FAIL rc={proc.returncode} profile={profile.exists()}\n"
              f"{proc.stdout.splitlines()[-8:]}", flush=True)
        return {"tag": tag, "pool": pool, "frames": frames, "valid": False}
    d = json.loads(profile.read_text(encoding="utf-8"))
    fa = d.get("frame_accounting", {})
    amf = d.get("amf", {})
    # lifecycle line from native stdout
    lifecycle = None
    m = re.search(r"\[VP POOL\] lifecycle: ([^\n]+)", proc.stdout)
    if m:
        lifecycle = m.group(1)
    rec = {
        "tag": tag, "pool": pool, "frames": frames, "valid": False,
        "vp_processed": fa.get("vp_processed", 0),
        "amf_submitted": fa.get("amf_submitted", 0),
        "amf_output": fa.get("amf_output", 0),
        "muxed": fa.get("muxed_frames", 0),
        "cadence_gpu": fa.get("cadence_gpu", 0),
        "hr_gpu": fa.get("hr_gpu", 0),
        "map_gpu": fa.get("map_gpu", 0),
        "dropped": amf.get("dropped_submissions", 0),
        "input_full": amf.get("input_full_count", 0),
        "lifecycle": lifecycle,
    }
    rec["valid"] = (fa.get("muxed_frames") == frames
                    and fa.get("amf_submitted") == frames
                    and fa.get("amf_output") == frames
                    and fa.get("vp_processed") == frames
                    and amf.get("dropped_submissions") == 0)
    print(f"[{tag}] pool={pool} frames={frames} muxed={rec['muxed']} "
          f"sub={rec['amf_submitted']} out={rec['amf_output']} "
          f"dropped={rec['dropped']} valid={rec['valid']}", flush=True)
    if lifecycle:
        print(f"  lifecycle: {lifecycle}", flush=True)
    return rec


def _hashes(mp4: Path) -> list:
    md5f = mp4.with_suffix(mp4.suffix + ".md5")
    subprocess.run([FF, "-y", "-hide_banner", "-loglevel", "error", "-i", str(mp4),
                    "-map", "0:v:0", "-f", "framemd5", str(md5f)], check=True)
    return [l.split()[-1] for l in md5f.read_text(encoding="utf-8").splitlines()
            if l and l[0].isdigit()]


def _compare(a: str, b: str) -> dict:
    ha = _hashes(OUT / f"l5v_{a}.mp4")
    hb = _hashes(OUT / f"l5v_{b}.mp4")
    same = sum(1 for x, y in zip(ha, hb) if x == y)
    return {"frames": len(ha), "identical": same, "total": len(hb),
            "pass": same == len(ha) == len(hb)}


def main() -> int:
    report = {}
    report["short"] = {
        "p4": _run("s31_p4", 31, 4),
        "p8": _run("s31_p8", 31, 8),
    }
    report["full"] = {
        "p4": _run("f1131_p4", 1131, 4),
        "p8": _run("f1131_p8", 1131, 8),
    }
    report["compare_31"] = _compare("s31_p4", "s31_p8")
    report["compare_1131"] = _compare("f1131_p4", "f1131_p8")
    ok31 = report["compare_31"]["pass"]
    ok1131 = report["compare_1131"]["pass"]
    valid = (report["full"]["p4"]["valid"] and report["full"]["p8"]["valid"])
    print("\n=== ETAP 5V golden ===", flush=True)
    print(f"  31  pool4 vs pool8: identical {report['compare_31']['identical']}/"
          f"{report['compare_31']['total']} pass={ok31}", flush=True)
    print(f"  1131 pool4 vs pool8: identical {report['compare_1131']['identical']}/"
          f"{report['compare_1131']['total']} pass={ok1131}", flush=True)
    print(f"  full accounting valid: {valid}", flush=True)
    print(f"  GOLDEN PASS = {ok31 and ok1131 and valid}", flush=True)
    (OUT / "etap5v_golden.json").write_text(json.dumps(report, indent=2, default=str),
                                            encoding="utf-8")
    return 0 if (ok31 and ok1131 and valid) else 1


if __name__ == "__main__":
    raise SystemExit(main())
