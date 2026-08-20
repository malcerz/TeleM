"""ETAP 5F measurement runner.

The runner only selects diagnostic parameters.  It does not alter production
defaults; MAX_IN_FLIGHT overrides are accepted by the application only while
TELEM_PIPELINE_AUDIT is enabled.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scratch.benchmark_etap5b6_production import prepare
from src.ffmpeg.streaming import stream_overlay_to_ffmpeg


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--frames", type=int, default=5400)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--max-in-flight", type=int, default=None)
    parser.add_argument("--preview", choices=("on", "off"), default="on")
    parser.add_argument("--label", default="run")
    parser.add_argument("--audit", action="store_true")
    parser.add_argument("--cpu-monitor", action="store_true")
    args = parser.parse_args()

    if args.audit:
        os.environ["TELEM_PIPELINE_AUDIT"] = "1"
        os.environ["TELEM_PIPELINE_AUDIT_PATH"] = str(ROOT / "scratch" / f"etap5f_{args.label}.json")
        if args.max_in_flight is not None:
            os.environ["TELEM_AUDIT_MAX_IN_FLIGHT"] = str(args.max_in_flight)
    else:
        os.environ.pop("TELEM_PIPELINE_AUDIT", None)
        os.environ.pop("TELEM_AUDIT_MAX_IN_FLIGHT", None)

    samples, anchor, fit, layout = prepare()
    fps = 30000 / 1001
    preview_events: list[dict] = []
    last_preview = -1.0

    def on_progress(done, total, elapsed, pipeline_fps, hud_state):
        nonlocal last_preview
        if hud_state is not None and hud_state.get("ts", -1.0) - last_preview >= 0.2:
            preview_events.append(hud_state)
            last_preview = hud_state["ts"]

    output = ROOT / "scratch" / f"etap5f_{args.label}.mp4"
    if output.exists():
        output.unlink()
    cpu_samples = []
    cpu_stop = threading.Event()
    cpu_thread = None
    if args.cpu_monitor:
        import psutil
        current = psutil.Process(os.getpid())
        current.cpu_percent(None)
        child_processes = {}

        def sample_cpu():
            while not cpu_stop.wait(0.5):
                try:
                    children = current.children(recursive=True)
                    child_cpu = []
                    for child in children:
                        tracked = child_processes.setdefault(child.pid, child)
                        child_cpu.append(tracked.cpu_percent(None))
                    cpu_samples.append({
                        "main_percent": current.cpu_percent(None),
                        "worker_percent_sum": sum(child_cpu),
                        "worker_count": len(children),
                        "system_percent": psutil.cpu_percent(None),
                        "per_core_max_percent": max(psutil.cpu_percent(None, percpu=True)),
                    })
                except (psutil.Error, ValueError):
                    pass

        cpu_thread = threading.Thread(target=sample_cpu, daemon=True)
        cpu_thread.start()
    started = time.perf_counter()
    piped = stream_overlay_to_ffmpeg(
        ffmpeg_exe="ffmpeg", input_files=[str(ROOT / "Video" / "GX030120.MP4")],
        output_file=str(output), duration_s=args.frames / fps, start_dt_utc=anchor,
        tz_offset_hours=2, speed_samples=samples["speed"], track_samples=samples["track"],
        alt_samples=samples["alt"], font_path="", layout=layout,
        field_samples={"start_dt_utc": anchor, "speed_samples": samples["speed"],
                       "track_samples": samples["track"], "alt_samples": samples["alt"],
                       "iso_samples": samples["iso"], "exposure_samples": samples["exposure"],
                       "temp_samples": samples["temp"]},
        max_distance_m=samples["track"][-1][1] if samples["track"] else 0,
        target_fps=fps, update_rate_step=1, workers=args.workers,
        iso_samples=samples["iso"], exposure_samples=samples["exposure"],
        temperature_samples=samples["temp"], fit_data=fit, gps_track=fit.get("track"),
        encoder="nv", gpu=0, video_bitrate="40M", render_w=3840, render_h=2160,
        resolution_name="source", rotation_degrees=0, container_rotation=0,
        overlay_w=1920, overlay_h=1080,
        on_render_progress=on_progress if args.preview == "on" else None,
    )
    wall = time.perf_counter() - started
    if cpu_thread is not None:
        cpu_stop.set()
        cpu_thread.join(timeout=2.0)
    result = {
        "label": args.label, "frames": piped, "workers": args.workers,
        "max_in_flight": args.max_in_flight, "preview": args.preview,
        "wall_s": wall, "real_export_fps": piped / wall if wall else 0.0,
        "preview_updates": len(preview_events),
        "preview_fps": len(preview_events) / wall if wall else 0.0,
        "audit_json": str(ROOT / "scratch" / f"etap5f_{args.label}.json") if args.audit else None,
        "cpu_samples": cpu_samples,
    }
    print(json.dumps(result, indent=2), flush=True)
    (ROOT / "scratch" / f"etap5f_{args.label}_result.json").write_text(
        json.dumps(result, indent=2), encoding="utf-8"
    )


if __name__ == "__main__":
    main()
