"""Serial 800-frame AMD Direct/Queue benchmark on one verified VIDEO/FIT pair."""
from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def ffprobe(path: Path) -> dict:
    probe = ROOT / "ffprobe.exe"
    if not probe.exists():
        probe = Path("ffprobe")
    data = subprocess.check_output([
        str(probe), "-v", "error", "-count_frames", "-show_streams", "-show_format", "-of", "json", str(path),
    ], text=True)
    return json.loads(data)


def audio_packet_hashes(path: Path, start: float) -> list[dict]:
    probe = ROOT / "ffprobe.exe"
    data = subprocess.check_output([
        str(probe), "-v", "error", "-select_streams", "a",
        "-read_intervals", f"{start}%+0.5", "-show_packets",
        "-show_entries", "packet=pts_time,data_hash", "-show_data_hash", "sha256",
        "-of", "json", str(path),
    ], text=True)
    return json.loads(data).get("packets", [])


def verify_sync_pair(video: Path, fit: Path) -> dict:
    result_path = ROOT / "scratch" / "amd_benchmark_sync.json"
    log_path = ROOT / "scratch" / "amd_benchmark_sync.log"
    process = subprocess.run([
        sys.executable, "SportCamHUD.py", "--test-sync-integrity",
        "--video", str(video), "--fit", str(fit), "--result-json", str(result_path),
    ], cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    log_path.write_text(process.stdout, encoding="utf-8", errors="replace")
    if process.returncode != 0 or not result_path.is_file():
        raise RuntimeError(f"FIT/GPS SmartSync preflight failed; see {log_path}\n{process.stdout[-3000:]}")
    result = json.loads(result_path.read_text(encoding="utf-8"))
    smart_sync = result.get("smart_sync") or {}
    if result.get("status") != "VALID" or result.get("user_override") is not False:
        raise RuntimeError(f"Benchmark pair was not accepted without override: {result.get('status')}")
    if smart_sync.get("status") != "VALID" or smart_sync.get("gps_overlap") is not True:
        raise RuntimeError("Benchmark pair has no successful spatial SmartSync evidence")
    return result


def source_profile(video: Path) -> dict:
    probe = ROOT / "ffprobe.exe"
    if not probe.exists():
        probe = Path("ffprobe")
    data = subprocess.check_output([
        str(probe), "-v", "error", "-show_streams", "-show_format", "-of", "json", str(video),
    ], text=True)
    streams = json.loads(data).get("streams", [])
    stream = next((item for item in streams if item.get("codec_type") == "video"), None)
    if not stream:
        raise RuntimeError("Input video has no video stream")
    if stream.get("codec_name") != "hevc" or (int(stream.get("width", 0)), int(stream.get("height", 0))) != (3840, 2160):
        raise RuntimeError("Acceptance source must be 4K HEVC")
    num, den = (int(value) for value in stream.get("r_frame_rate", "0/1").split("/"))
    return {"source_fps": num / den if den else 0.0, "source_codec": stream.get("codec_name"), "width": stream.get("width"), "height": stream.get("height")}


def run_one(mode: str, preview: bool, repetition: int, video: Path, fit: Path, frames: int, bitrate: str, start_seconds: float, output_dir: Path) -> dict:
    label = f"{mode}_preview_{'on' if preview else 'off'}_{repetition}"
    output = output_dir / f"{label}.mp4"
    result_json = output_dir / f"{label}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    command = [
        sys.executable, "SportCamHUD.py", "--test-amd-export", "--mode", mode,
        "--video", str(video), "--fit", str(fit), "--frames", str(frames),
        "--quality", "QUALITY", "--codec", "hevc", "--bitrate", bitrate, "--start-seconds", str(start_seconds),
        "--output", str(output), "--result-json", str(result_json),
    ]
    if preview:
        command.append("--preview-hud")
    started = time.perf_counter()
    process = subprocess.run(command, cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=1200, encoding="utf-8", errors="replace")
    elapsed = time.perf_counter() - started
    log_path = output_dir / f"{label}.log"
    log_path.write_text(process.stdout, encoding="utf-8", errors="replace")
    if process.returncode:
        raise RuntimeError(f"{label} failed (rc={process.returncode}); see {log_path}\n{process.stdout[-3000:]}")
    if not output.is_file() or not result_json.is_file():
        raise RuntimeError(f"{label} did not produce MP4 and result JSON")
    result = json.loads(result_json.read_text(encoding="utf-8"))
    streams = ffprobe(output).get("streams", [])
    video_stream = next((stream for stream in streams if stream.get("codec_type") == "video"), None)
    audio_stream = next((stream for stream in streams if stream.get("codec_type") == "audio"), None)
    if not video_stream or video_stream.get("codec_name") != "hevc":
        raise RuntimeError(f"{label} output is not HEVC")
    if int(video_stream.get("width", 0)) != 3840 or int(video_stream.get("height", 0)) != 2160:
        raise RuntimeError(f"{label} output is not 3840x2160")
    actual_frames = int(video_stream.get("nb_read_frames", 0))
    if actual_frames < frames:
        raise RuntimeError(f"{label} output has only {actual_frames}/{frames} frames")
    if not audio_stream:
        raise RuntimeError(f"{label} output has no audio stream")
    video_duration = float(video_stream.get("duration", 0) or 0)
    audio_duration = float(audio_stream.get("duration", 0) or 0)
    if not video_duration or not audio_duration or abs(video_duration - audio_duration) > 0.5:
        raise RuntimeError(f"{label} audio/video duration mismatch ({audio_duration:.3f}s vs {video_duration:.3f}s)")
    if result.get("total_frames", 0) < frames:
        raise RuntimeError(f"{label} app reports too few frames")
    from src.telemetry_cache_manager import get_audio_cache_path
    source_audio = get_audio_cache_path(video)
    expected_packets = audio_packet_hashes(source_audio, start_seconds)
    output_packets = audio_packet_hashes(output, 0.0)
    expected_hashes = {packet["data_hash"] for packet in expected_packets}
    if not output_packets or output_packets[0]["data_hash"] not in expected_hashes:
        raise RuntimeError(f"{label} audio is not from requested source range {start_seconds}s")
    audio_range_proof = {"source_start_seconds": start_seconds,
                         "output_first_packet": output_packets[0],
                         "source_matching_packets": [packet for packet in expected_packets
                            if packet["data_hash"] == output_packets[0]["data_hash"]]}
    output.with_suffix(".audio_range.json").write_text(json.dumps(audio_range_proof, indent=2), encoding="utf-8")
    qp_samples = result.get("live_qp_samples") or []
    if not any(isinstance(sample.get("qp"), (int, float)) and sample["qp"] > 0 for sample in qp_samples):
        raise RuntimeError(f"{label} produced no live QP telemetry")
    profile_path = Path(str(output) + ".amd_profile.json")
    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    timing = profile.get("etap8p_a") or {}
    first_packet = (profile.get("mux_pump") or {}).get("first_encoded_packet_perf_counter")
    click = result.get("click_perf_counter")
    first_ms = (first_packet - click) * 1000 if first_packet and click else None
    probe_path = output.with_suffix(".ffprobe.json")
    probe_path.write_text(json.dumps({"streams": streams}, indent=2), encoding="utf-8")
    return {
        "click_epoch": result.get("click_epoch"),
        "finish_epoch": result.get("finish_epoch"),
        "first_packet_epoch": (profile.get("mux_pump") or {}).get("first_encoded_packet_epoch"),
        "first_encoded_packet_ms": first_ms,
        "native_render_fps": timing.get("render_fps"),
        "native_effective_fps": timing.get("effective_fps"),
        "config_fingerprint": (profile.get("benchmark") or {}).get("config_fingerprint"),
        "frame_accounting": profile.get("frame_accounting"),
        "label": label, "mode": mode, "preview": preview, "frames": actual_frames,
        "process_elapsed_s": elapsed, "process_effective_fps": actual_frames / elapsed,
        "elapsed_s": result.get("elapsed_s"), "effective_fps": result.get("effective_fps"),
        "click_to_first_progress_ms": result.get("click_to_first_progress_ms"),
        "steady_render_fps": timing.get("render_fps"),
        "native_total_fps": (result.get("stats") or {}).get("true_fps"),
        "startup_ms": first_ms, "output": str(output),
        "log": str(log_path), "profile": str(output) + ".amd_profile.json",
        "result_json": str(result_json), "audio": True, "audio_range_verified": True, "qp_samples": len(qp_samples),
        "hevc": True,
        "resolution": "3840x2160", "quality": "QUALITY", "bitrate": bitrate,
        "user_override": "USER_OVERRIDE=YES" in process.stdout,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--video", type=Path, required=True)
    parser.add_argument("--fit", type=Path, required=True)
    parser.add_argument("--frames", type=int, default=800)
    parser.add_argument("--pairs", type=int, default=3)
    parser.add_argument("--preview", choices=("on", "off", "both"), default="both")
    parser.add_argument("--bitrate", default="40M")
    parser.add_argument("--start-seconds", type=float, default=120.0)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    args.output_dir = args.output_dir.resolve()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    video, fit = args.video.resolve(), args.fit.resolve()
    if not video.is_file() or not fit.is_file():
        parser.error("VIDEO and FIT must both exist")
    if video.name.casefold() == "gx010321.mp4" and fit.name.casefold() == "poranna_jazda_na_rowerze.fit":
        parser.error("This VIDEO/FIT pairing is explicitly rejected and cannot be a benchmark fixture")
    if args.pairs < 3 or args.frames < 800:
        parser.error("Acceptance requires at least 3 pairs and 800 frames per export")

    results = []
    preflight = verify_sync_pair(video, fit)
    source = source_profile(video)
    preview_states = (True, False) if args.preview == "both" else (args.preview == "on",)
    # Serial execution prevents GPU benchmark overlap. Alternate ordering across
    # repetitions so Direct/Queue do not always inherit the same thermal order.
    for preview in preview_states:
        for repetition in range(1, args.pairs + 1):
            modes = ("direct", "queue") if repetition % 2 else ("queue", "direct")
            for mode in modes:
                row = run_one(mode, preview, repetition, video, fit, args.frames, args.bitrate, args.start_seconds, args.output_dir)
                results.append(row)
                print(json.dumps(row, ensure_ascii=False), flush=True)
                (args.output_dir / "runs.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    summary = {
        "video": str(video), "fit": str(fit), "source": source,
        "sync_preflight": preflight, "runs": results,
    }
    summary_path = args.output_dir / "amd_direct_queue_acceptance.json"
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    for preview in preview_states:
        for mode in ("direct", "queue"):
            fps = [row["effective_fps"] for row in results if row["preview"] == preview and row["mode"] == mode]
            print(f"{mode.upper()}_PREVIEW_{'ON' if preview else 'OFF'}_EFFECTIVE_FPS_MEDIAN={statistics.median(fps):.2f}")
    print(f"RESULT_JSON={summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
