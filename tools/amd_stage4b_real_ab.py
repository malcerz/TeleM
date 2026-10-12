"""Repeatable real-file AMD A/B adapter around SportCamHUD's export harness.

This is a diagnostic adapter for explicitly selected non-canonical material. It
does not clear caches, prepare/extract audio, change AMD flags, or rewrite the
source layout. Generated layouts, exports, logs, and isolated caches live under
the required output directory.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


def probe_video(ffprobe: Path, path: Path) -> dict[str, Any]:
    completed = subprocess.run(
        [str(ffprobe), "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return json.loads(completed.stdout)


def make_layout_variants(source: Path, layout_dir: Path) -> dict[str, Path]:
    raw = source.read_bytes()
    user_layout = json.loads(raw.decode("utf-8-sig"))
    off_layout = json.loads(raw.decode("utf-8-sig"))
    disabled: list[str] = []
    for name, config in off_layout.get("indicators", {}).items():
        if not isinstance(config, dict):
            continue
        for key in ("outline_enabled", "shadow_enabled"):
            if config.get(key):
                config[key] = False
                disabled.append(f"indicators.{name}.{key}")
    global_config = off_layout.setdefault("global", {})
    if isinstance(global_config, dict) and global_config.get("text_outline", 0):
        global_config["text_outline"] = 0
        disabled.append("global.text_outline")

    paths = {
        "A_effects_off": layout_dir / "A_effects_off.json",
        "B_effects_on": layout_dir / "B_effects_on.json",
        "C_user_full_hud": layout_dir / "C_user_full_hud.json",
    }
    paths["A_effects_off"].write_text(
        json.dumps(off_layout, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    for label in ("B_effects_on", "C_user_full_hud"):
        shutil.copyfile(source, paths[label])
    manifest = {
        "source_layout": str(source.resolve()),
        "source_sha256": hashlib.sha256(raw).hexdigest(),
        "variant_sha256": {label: sha256(path) for label, path in paths.items()},
        "A_only_changes": disabled,
        "B_and_C_identical": paths["B_effects_on"].read_bytes() == paths["C_user_full_hud"].read_bytes(),
        "B_vs_C": "Both are byte-identical copies of the current user layout; C is the full-HUD production control.",
    }
    write_json(layout_dir / "manifest.json", manifest)
    return paths


def run_sync_preflight(
    repo: Path, python: Path, video: Path, fit: Path, out_dir: Path, env: dict[str, str]
) -> dict[str, Any]:
    result_path = out_dir / "smart_sync.json"
    log_path = out_dir / "smart_sync.log"
    command = [
        str(python), str(repo / "SportCamHUD.py"), "--test-sync-integrity",
        "--video", str(video), "--fit", str(fit), "--result-json", str(result_path),
    ]
    with log_path.open("w", encoding="utf-8", errors="replace") as log:
        process = subprocess.run(command, cwd=repo, env=env, stdout=log, stderr=subprocess.STDOUT, timeout=900)
    if not result_path.is_file():
        raise RuntimeError(f"SmartSync harness wrote no result JSON (exit={process.returncode}); see {log_path}")
    result = json.loads(result_path.read_text(encoding="utf-8"))
    sync = result.get("smart_sync") or {}
    # The strict CLI also asks for a separate explicit file-validation object.
    # Keep its overall status visible, but gate pairing on spatial SmartSync
    # evidence rather than timestamp proximity.
    spatial_valid = (
        sync.get("status") == "VALID"
        and sync.get("gps_overlap") is True
        and int(sync.get("matched_points") or 0) > 0
        and float(sync.get("coverage") or 0) > 0
        and sync.get("offset_s") is not None
        and sync.get("median_error_m") is not None
        and sync.get("p90_error_m") is not None
    )
    summary = {
        "command_exit_code": process.returncode,
        "overall_cli_status": result.get("status"),
        "explicit_file_validation": result.get("validation"),
        "spatial_smart_sync": sync,
        "pairing_gate": "PASS_SPATIAL" if spatial_valid else "BLOCKED",
        "note": (
            "An overall INVALID caused by missing explicit file validation does not erase "
            "a separately returned spatial result; exports still require app validation."
        ),
    }
    write_json(out_dir / "smart_sync_summary.json", summary)
    if not spatial_valid:
        raise RuntimeError(f"Pair failed spatial SmartSync gate; see {log_path} and {result_path}")
    return summary


def run_one(
    *, repo: Path, python: Path, ffprobe: Path, video: Path, fit: Path, layout: Path,
    label: str, repeat: int, frames: int, start_seconds: float, quality: str, bitrate: str,
    run_dir: Path, env: dict[str, str], monitor_script: Path,
) -> dict[str, Any]:
    stem = f"{label}_{repeat:02d}"
    output = run_dir / f"{stem}.mp4"
    result_path = run_dir / f"{stem}.json"
    log_path = run_dir / f"{stem}.log"
    if output.exists() or result_path.exists() or log_path.exists():
        raise FileExistsError(f"Refusing to overwrite prior run artifacts for {stem}")
    command = [
        str(python), str(repo / "SportCamHUD.py"), "--test-amd-export", "--mode", "direct",
        "--video", str(video), "--fit", str(fit), "--frames", str(frames),
        "--quality", quality, "--codec", "hevc", "--bitrate", bitrate,
        "--start-seconds", str(start_seconds), "--output", str(output),
        "--result-json", str(result_path), "--layout", str(layout),
    ]
    monitor_base = run_dir / stem
    monitor_out = run_dir / f"{stem}_monitor_stdout.log"
    monitor_err = run_dir / f"{stem}_monitor_stderr.log"
    started_utc = datetime.now(timezone.utc).isoformat()
    started = time.perf_counter()
    with log_path.open("w", encoding="utf-8", errors="replace") as log:
        process = subprocess.Popen(command, cwd=repo, env=env, stdout=log, stderr=subprocess.STDOUT)
        monitor_log = monitor_out.open("w", encoding="utf-8", errors="replace")
        monitor_error = monitor_err.open("w", encoding="utf-8", errors="replace")
        monitor = subprocess.Popen(
            [
                "powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(monitor_script),
                "-RootPid", str(process.pid), "-OutputPrefix", str(monitor_base),
            ],
            cwd=repo,
            env=env,
            stdout=monitor_log,
            stderr=monitor_error,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        try:
            return_code = process.wait(timeout=7200)
        except subprocess.TimeoutExpired:
            # Preserve outputs and partial MP4 for diagnosis; do not remove them.
            process.terminate()
            process.wait(timeout=30)
            return_code = process.returncode if process.returncode is not None else 124
            raise TimeoutError(f"{stem} exceeded the 2-hour run limit; partial artifacts were preserved")
        finally:
            try:
                monitor.wait(timeout=30)
            except subprocess.TimeoutExpired:
                monitor.terminate()
                monitor.wait(timeout=10)
            monitor_log.close()
            monitor_error.close()
    elapsed_s = time.perf_counter() - started
    finished_utc = datetime.now(timezone.utc).isoformat()
    if return_code != 0 or not result_path.is_file():
        raise RuntimeError(f"{stem} failed (exit={return_code}); inspect {log_path}")

    result = json.loads(result_path.read_text(encoding="utf-8"))
    profile_path = Path(str(output) + ".amd_profile.json")
    if not profile_path.is_file():
        raise RuntimeError(f"{stem} did not emit AMD profile: {profile_path}")
    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    probe = probe_video(ffprobe, output)
    video_stream = next((stream for stream in probe.get("streams", []) if stream.get("codec_type") == "video"), None)
    audio_stream = next((stream for stream in probe.get("streams", []) if stream.get("codec_type") == "audio"), None)
    if (
        not video_stream
        or video_stream.get("codec_name") != "hevc"
        or (video_stream.get("width"), video_stream.get("height")) != (3840, 2160)
    ):
        raise RuntimeError(f"{stem} output is not 4K HEVC")
    source_probe = probe_video(ffprobe, video)
    source_video = next(stream for stream in source_probe["streams"] if stream.get("codec_type") == "video")
    if video_stream.get("avg_frame_rate") != source_video.get("avg_frame_rate"):
        raise RuntimeError(f"{stem} output FPS differs from source")
    expected_frames = frames
    actual_frames = int(video_stream.get("nb_frames") or 0)
    if actual_frames != expected_frames:
        raise RuntimeError(f"{stem} frame count {actual_frames} != requested {expected_frames}")
    if not audio_stream:
        raise RuntimeError(f"{stem} muxed output has no audio stream")
    if not str(profile.get("backend", "")).startswith("AMD_NATIVE_D3D11"):
        raise RuntimeError(f"{stem} profile is not AMD_NATIVE_D3D11: {profile.get('backend')}")
    if not profile.get("etap4", {}).get("hardware_acceleration_confirmed"):
        raise RuntimeError(f"{stem} does not confirm D3D11 hardware decode")
    if int(profile.get("frame_accounting", {}).get("amf_submitted", 0)) < expected_frames:
        raise RuntimeError(f"{stem} AMF submitted fewer frames than requested")
    average_qp = (result.get("stats") or {}).get("avg_qp")
    if average_qp is None or abs(float(average_qp) - 28.0) > 0.5:
        raise RuntimeError(f"{stem} did not report QP 28 (reported {average_qp})")

    timings = profile.get("timings") or {}
    etap = profile.get("etap8p_a") or {}
    config = (profile.get("benchmark") or {}).get("config") or {}
    row = {
        "label": label,
        "repeat": repeat,
        "layout_path": str(layout),
        "layout_sha256": sha256(layout),
        "frames": actual_frames,
        "source_fps": source_video.get("avg_frame_rate"),
        "resolution": f"{video_stream.get('width')}x{video_stream.get('height')}",
        "backend": profile.get("backend"),
        "average_qp": average_qp,
        "render_fps": etap.get("render_fps"),
        "effective_fps": etap.get("effective_fps", result.get("effective_fps")),
        "process_effective_fps": actual_frames / elapsed_s if elapsed_s else 0,
        "application_wall_s": result.get("elapsed_s"),
        "process_wall_s": elapsed_s,
        "startup_first_progress_ms": result.get("click_to_first_progress_ms"),
        "native_wall_ms": etap.get("video_render_wall_ms"),
        "mux_wall_ms": etap.get("mux_wall_ms"),
        "finalization": profile.get("finalization"),
        "producer_prepare_ms": (timings.get("producer_prepare") or {}).get("avg_ms"),
        "above_compose_ms": (timings.get("above_compose") or {}).get("avg_ms"),
        "above_total_ms": (timings.get("above_total") or {}).get("avg_ms"),
        "consumer_queue_wait_ms": (timings.get("consumer_queue_wait") or {}).get("avg_ms"),
        "decode_wait_ms": (timings.get("Decode/pipe wait") or {}).get("avg_ms"),
        "mf_readsample_ms": (timings.get("MF ReadSample/decode availability") or {}).get("avg_ms"),
        "decoder_copy_ms": (timings.get("Decoder surface GPU copy") or {}).get("avg_ms"),
        "hud_upload_ms": (timings.get("HUD texture upload") or {}).get("avg_ms"),
        "amf_submit_ms": (timings.get("AMF submit/backpressure") or {}).get("avg_ms"),
        "amf_query_ms": (timings.get("AMF QueryOutput") or {}).get("avg_ms"),
        "mux_packet_write_ms": (timings.get("Packet write") or {}).get("avg_ms"),
        "audio_mux_ms": (timings.get("Audio mux") or {}).get("avg_ms"),
        "profile_config": config,
        "config_fingerprint": (profile.get("benchmark") or {}).get("config_fingerprint"),
        "output": str(output),
        "output_size_bytes": output.stat().st_size,
        "result_json": str(result_path),
        "profile_json": str(profile_path),
        "stdout_log": str(log_path),
        "gpu_counter_csv": str(monitor_base) + "_gpu.csv",
        "system_counter_csv": str(monitor_base) + "_system.csv",
        "started_utc": started_utc,
        "finished_utc": finished_utc,
        "app_success": result.get("success"),
        "output_has_audio": audio_stream is not None,
    }
    write_json(run_dir / f"{stem}_summary.json", row)
    return row


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--video", type=Path, required=True)
    parser.add_argument(
        "--fit",
        type=Path,
        required=True,
        help="FIT explicitly associated by existing project/cache index and spatial validation",
    )
    parser.add_argument("--layout", type=Path, required=True, help="Current user layout; read only")
    parser.add_argument("--output-dir", type=Path, required=True, help="Must be a new isolated results directory")
    parser.add_argument("--frames", type=int, default=3000)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument(
        "--profile-effects",
        action="store_true",
        help="run one isolated full-HUD export with effect/cache and compositor profiling enabled",
    )
    parser.add_argument("--start-seconds", type=float, default=120.0)
    parser.add_argument("--quality", choices=("FAST", "BALANCED", "QUALITY"), default="FAST")
    parser.add_argument("--bitrate", default="40M")
    args = parser.parse_args()

    repo = Path(__file__).resolve().parents[1]
    python = Path(sys.executable).resolve()
    ffprobe = repo / "ffprobe.exe"
    monitor_script = Path(__file__).with_name("amd_stage4b_gpu_monitor.ps1")
    video, fit, source_layout, out_dir = (
        value.expanduser().resolve()
        for value in (args.video, args.fit, args.layout, args.output_dir)
    )
    if not video.is_file() or not fit.is_file() or not source_layout.is_file() or not ffprobe.is_file():
        parser.error("VIDEO, FIT, layout, and repo ffprobe.exe must exist")
    if out_dir.exists():
        parser.error(f"output directory must be new; refusing to overwrite: {out_dir}")
    if args.frames < 3000:
        parser.error("ETAP 4B diagnostic requires at least 3000 frames")
    if args.profile_effects and args.repeats != 1:
        parser.error("--profile-effects is a separate single profiled run; pass --repeats 1")
    if not args.profile_effects and args.repeats < 3:
        parser.error("ETAP 4B A/B/C matrix requires at least 3 repeats")
    if not monitor_script.is_file():
        parser.error(f"GPU monitor script missing: {monitor_script}")
    source_probe = probe_video(ffprobe, video)
    source_stream = next(
        (stream for stream in source_probe.get("streams", []) if stream.get("codec_type") == "video"),
        None,
    )
    if (
        not source_stream
        or source_stream.get("codec_name") != "hevc"
        or (source_stream.get("width"), source_stream.get("height")) != (3840, 2160)
    ):
        parser.error("selected real source must be 3840x2160 HEVC")
    fps_num, fps_den = source_stream.get("avg_frame_rate", "0/1").split("/")
    if int(round(float(fps_num) / float(fps_den))) <= 0:
        parser.error("source FPS is unavailable")

    out_dir.mkdir(parents=True, exist_ok=False)
    layout_dir = out_dir / "layouts"
    run_dir = out_dir / "runs"
    isolation_dir = out_dir / "isolation"
    for directory in (
        layout_dir,
        run_dir,
        isolation_dir / "appdata",
        isolation_dir / "localappdata",
        isolation_dir / "telemetry_cache",
    ):
        directory.mkdir(parents=True, exist_ok=True)
    variants = make_layout_variants(source_layout, layout_dir)
    env = os.environ.copy()
    env["APPDATA"] = str(isolation_dir / "appdata")
    env["LOCALAPPDATA"] = str(isolation_dir / "localappdata")
    env["TELEM_CACHE_ROOT"] = str(isolation_dir / "telemetry_cache")
    env["PYTHONUTF8"] = "1"
    if args.profile_effects:
        env["TELEM_EFFECTS_CACHE_PROFILE"] = "1"
        env["AMD_OVERLAY_PROFILE"] = "1"
        env["AMD_PRODUCTION_ACCOUNTING"] = "1"

    initial_user_layout = source_layout.read_bytes()
    if hashlib.sha256(initial_user_layout).hexdigest() != sha256(source_layout):
        raise RuntimeError("source layout changed while being read")
    manifest = {
        "label": (
            "DIAGNOSTIC_EFFECT_CACHE_PROFILE_NONCOMPARABLE"
            if args.profile_effects
            else "DIAGNOSTIC_A_B_REAL_FILES_NONCANONICAL"
        ),
        "started_utc": datetime.now(timezone.utc).isoformat(),
        "repo": str(repo),
        "head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip(),
        "branch": subprocess.check_output(["git", "branch", "--show-current"], cwd=repo, text=True).strip(),
        "video": {
            "path": str(video),
            "size_bytes": video.stat().st_size,
            "modified_utc": datetime.fromtimestamp(video.stat().st_mtime, timezone.utc).isoformat(),
            "probe": source_probe,
        },
        "fit": {"path": str(fit), "size_bytes": fit.stat().st_size, "sha256": sha256(fit)},
        "layout_variants": str(layout_dir),
        "frames": args.frames,
        "start_seconds": args.start_seconds,
        "quality_preset": args.quality,
        "qp_expected": 28,
        "bitrate_argument": args.bitrate,
        "amd_environment_inherited_without_overrides": {
            key: value for key, value in env.items() if key.startswith("AMD_")
        },
        "isolated_cache_roots": {key: env[key] for key in ("APPDATA", "LOCALAPPDATA", "TELEM_CACHE_ROOT")},
        "source_layout_sha256": sha256(source_layout),
        "outputs_audio_policy": "Live mux from original MP4 only; no extraction/cache/remux pre-pass.",
    }
    write_json(out_dir / "manifest.json", manifest)

    smart_sync = run_sync_preflight(repo, python, video, fit, out_dir, env)
    manifest["smart_sync_preflight"] = smart_sync
    write_json(out_dir / "manifest.json", manifest)

    # Interleave A/B/C order to reduce systematic thermal/order bias. B and C
    # are deliberately repeated as separate labels although their layouts are
    # identical, so each requested condition has three observed runs.
    order = (("C_user_full_hud",),) if args.profile_effects else (
        ("A_effects_off", "B_effects_on", "C_user_full_hud"),
        ("C_user_full_hud", "A_effects_off", "B_effects_on"),
        ("B_effects_on", "C_user_full_hud", "A_effects_off"),
    )
    runs: list[dict[str, Any]] = []
    for repeat, labels in enumerate(order, start=1):
        for label in labels:
            row = run_one(
                repo=repo, python=python, ffprobe=ffprobe, video=video, fit=fit,
                layout=variants[label], label=label, repeat=repeat, frames=args.frames,
                start_seconds=args.start_seconds, quality=args.quality, bitrate=args.bitrate,
                run_dir=run_dir, env=env, monitor_script=monitor_script,
            )
            runs.append(row)
            write_json(out_dir / "runs.json", runs)
            with (out_dir / "runs.csv").open("w", newline="", encoding="utf-8-sig") as stream:
                columns = [key for key, value in row.items() if not isinstance(value, (dict, list))]
                writer = csv.DictWriter(stream, fieldnames=columns)
                writer.writeheader()
                writer.writerows({key: item.get(key) for key in columns} for item in runs)
            print(json.dumps(row, ensure_ascii=False, default=str), flush=True)

    manifest["finished_utc"] = datetime.now(timezone.utc).isoformat()
    manifest["run_count"] = len(runs)
    manifest["summary"] = {}
    for label in variants:
        label_runs = [row for row in runs if row["label"] == label]
        if not label_runs:
            continue
        render_values = sorted(float(row["render_fps"] or 0) for row in label_runs)
        effective_values = sorted(float(row["effective_fps"] or 0) for row in label_runs)
        middle = len(label_runs) // 2
        manifest["summary"][label] = {
            "render_fps_median": render_values[middle],
            "effective_fps_median": effective_values[middle],
        }
    write_json(out_dir / "manifest.json", manifest)
    print(f"RESULTS={out_dir}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
