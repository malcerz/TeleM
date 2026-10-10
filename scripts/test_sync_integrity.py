"""Strict real-file FIT validation and SmartSync integration harness."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
POSITIVE_VIDEO = ROOT / "Video" / "GX020079.MP4"
POSITIVE_FIT = ROOT / "Video" / "GX020079.fit"
NEGATIVE_VIDEO = Path(r"F:\GoPro\2026-09-25\GX010321.MP4")
NEGATIVE_FIT = Path(r"F:\GoPro\2026-09-25\Poranna_jazda_na_rowerze.fit")


def run_case(name: str, video: Path, fit: Path, expected: set[str], timeout: int) -> tuple[bool, dict]:
    result_path = ROOT / "scratch" / f"sync_integrity_{name}.json"
    result_path.parent.mkdir(parents=True, exist_ok=True)
    command = [
        sys.executable, "SportCamHUD.py", "--test-sync-integrity",
        "--video", str(video), "--fit", str(fit), "--result-json", str(result_path),
    ]
    print(f"\n[SYNC TEST] {name}: {' '.join(command)}", flush=True)
    try:
        process = subprocess.run(
            command, cwd=ROOT, text=True, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        print(f"[SYNC TEST] {name}=TIMEOUT\n{exc.stdout or ''}", flush=True)
        return False, {"status": "TIMEOUT"}
    print(process.stdout, flush=True)
    try:
        data = json.loads(result_path.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"[SYNC TEST] {name}: missing/invalid structural result JSON: {exc}", flush=True)
        return False, {"status": "NO_RESULT_JSON", "returncode": process.returncode}
    status = data.get("status")
    if status not in expected:
        print(f"[SYNC TEST] {name}: EXPECTED {sorted(expected)}, GOT {status}", flush=True)
        return False, data
    if status == "VALID":
        sync = data.get("smart_sync") or {}
        required = ("matched_points", "total_points", "coverage", "median_error_m", "p90_error_m", "offset_s")
        missing = [key for key in required if sync.get(key) is None]
        if (
            process.returncode != 0
            or data.get("user_override") is not False
            or missing
            or sync.get("gps_overlap") is not True
            or sync.get("matched_points", 0) <= 0
            or sync.get("coverage", 0) <= 0
        ):
            print(f"[SYNC TEST] {name}: VALID evidence incomplete (missing={missing}, override={data.get('user_override')})", flush=True)
            return False, data
        print(f"[SYNC TEST] {name}=VALID", flush=True)
        return True, data
    if process.returncode == 0:
        print(f"[SYNC TEST] {name}: rejection incorrectly returned exit 0", flush=True)
        return False, data
    print(f"[SYNC TEST] {name}=EXPECTED_REJECTION ({status})", flush=True)
    return True, data


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--positive-video", type=Path, default=POSITIVE_VIDEO)
    parser.add_argument("--positive-fit", type=Path, default=POSITIVE_FIT)
    parser.add_argument("--negative-video", type=Path, default=NEGATIVE_VIDEO)
    parser.add_argument("--negative-fit", type=Path, default=NEGATIVE_FIT)
    parser.add_argument("--timeout", type=int, default=150)
    args = parser.parse_args()

    positive_ok, positive = run_case(
        "positive", args.positive_video, args.positive_fit, {"VALID"}, args.timeout,
    )
    negative_cases = [
        ("negative_mismatch", args.negative_video, args.negative_fit, {"INVALID"}),
        ("negative_missing_video", Path("F:/GoPro/Missing.MP4"), args.negative_fit, {"MISSING_FILE"}),
        ("negative_missing_fit", args.negative_video, Path("F:/GoPro/Missing.fit"), {"MISSING_FILE"}),
    ]
    results = [positive_ok]
    for name, video, fit, expected in negative_cases:
        ok, _ = run_case(name, video, fit, expected, args.timeout)
        results.append(ok)
    print("\n[SYNC TEST] SYNC_INTEGRITY_PASS" if all(results) else "\n[SYNC TEST] SYNC_INTEGRITY_FAIL")
    return 0 if all(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
