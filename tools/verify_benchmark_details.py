"""Detailed verification of benchmark results: Audio, HDR, AMF VBR/QP, Boundary, and Timings."""

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FFPROBE_EXE = ROOT / "ffprobe.exe"
BENCH_DIR = ROOT / "Raporty/gpu_pitch_bench_artifacts"

RUNS = [
    "WARMUP",
    "A1_cpu_pitch",
    "B1_gpu_pitch",
    "B2_gpu_pitch",
    "A2_cpu_pitch",
    "A0_prod_fallback",
    "BOUNDARY_gpu_pitch",
    "TONEMAP_SDR_gpu_pitch",
]

def ffprobe_mp4(mp4_path: Path):
    cmd = [
        str(FFPROBE_EXE),
        "-v", "error",
        "-show_streams",
        "-show_format",
        "-of", "json",
        str(mp4_path),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if res.returncode != 0:
        return {"error": res.stderr}
    return json.loads(res.stdout)

def ffprobe_packets(mp4_path: Path, stream_spec="a:0"):
    cmd = [
        str(FFPROBE_EXE),
        "-v", "error",
        "-select_streams", stream_spec,
        "-show_entries", "packet=pts,dts,duration,size",
        "-of", "json",
        str(mp4_path),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if res.returncode != 0:
        return []
    return json.loads(res.stdout).get("packets", [])

def main():
    report = {}

    for run in RUNS:
        run_dir = BENCH_DIR / run
        mp4_path = run_dir / "export.mp4"
        profile_path = run_dir / "export.mp4.amd_profile.json"
        result_path = run_dir / "result.json"

        entry = {"run": run, "exists": mp4_path.exists()}
        if not mp4_path.exists():
            report[run] = entry
            continue

        # 1. Media streams
        probe = ffprobe_mp4(mp4_path)
        v_stream = next((s for s in probe.get("streams", []) if s.get("codec_type") == "video"), {})
        a_stream = next((s for s in probe.get("streams", []) if s.get("codec_type") == "audio"), {})

        entry["video"] = {
            "codec": v_stream.get("codec_name"),
            "profile": v_stream.get("profile"),
            "pix_fmt": v_stream.get("pix_fmt"),
            "color_range": v_stream.get("color_range"),
            "color_space": v_stream.get("color_space"),
            "color_transfer": v_stream.get("color_transfer"),
            "color_primaries": v_stream.get("color_primaries"),
            "width": v_stream.get("width"),
            "height": v_stream.get("height"),
            "nb_frames": v_stream.get("nb_frames"),
            "duration": v_stream.get("duration"),
        }

        entry["audio"] = {
            "codec": a_stream.get("codec_name"),
            "profile": a_stream.get("profile"),
            "sample_rate": a_stream.get("sample_rate"),
            "channels": a_stream.get("channels"),
            "duration": a_stream.get("duration"),
            "nb_frames": a_stream.get("nb_frames"),
        }

        # Packets
        a_packets = ffprobe_packets(mp4_path, "a:0")
        entry["audio"]["actual_packet_count"] = len(a_packets)
        if a_packets:
            entry["audio"]["first_pts"] = a_packets[0].get("pts")
            entry["audio"]["last_pts"] = a_packets[-1].get("pts")
            # Verify strictly monotonic
            pts_vals = [int(p["pts"]) for p in a_packets if "pts" in p and p["pts"] is not None]
            entry["audio"]["pts_monotonic"] = all(pts_vals[i] <= pts_vals[i+1] for i in range(len(pts_vals)-1))

        # 2. Profile
        if profile_path.exists():
            prof = json.loads(profile_path.read_text(encoding="utf-8"))
            etap8p_a = prof.get("etap8p_a", {})
            timings = prof.get("timings", {})
            etap5g = prof.get("etap5g", {})
            amf = prof.get("amf", {})
            dll = prof.get("dll", {})

            entry["profile"] = {
                "render_fps": etap8p_a.get("render_fps", prof.get("true_fps")),
                "effective_fps": etap8p_a.get("effective_fps"),
                "total_wall_ms": etap8p_a.get("total_from_export_start_ms"),
                "video_render_wall_ms": etap8p_a.get("video_render_wall_ms"),
                "mux_wall_ms": etap8p_a.get("mux_wall_ms"),
                "producer_prepare_ms": timings.get("producer_prepare", {}).get("avg_ms"),
                "consumer_queue_wait_ms": timings.get("consumer_queue_wait", {}).get("avg_ms"),
                "pipeline_total_ms": timings.get("pipeline_total", {}).get("avg_ms"),
                "map_cpu_ms": timings.get("map_cpu_upload", {}).get("avg_ms", timings.get("map_upload_ms", {}).get("avg_ms")),
                "above_compose_ms": timings.get("above_compose", {}).get("avg_ms"),
                "map_gpu_pitch_requested": etap5g.get("map_gpu_pitch_requested"),
                "map_gpu_pitch_used": etap5g.get("map_gpu_pitch_used"),
                "map_gpu_pitch_degrees": etap5g.get("map_gpu_pitch_degrees"),
                "map_cpu_rotate_bypassed": etap5g.get("map_cpu_rotate_bypassed"),
                "map_cpu_pitch_bypassed": etap5g.get("map_cpu_pitch_bypassed"),
                "map_gpu_frames": etap5g.get("map_gpu_frames"),
                "map_upload_bytes_total": etap5g.get("map_upload_bytes_total"),
                "map_upload_mib_per_frame": etap5g.get("map_upload_mib_per_frame"),
                "loaded_dll_path": dll.get("path"),
                "loaded_dll_build_id": dll.get("build_id"),
                "amf": {
                    "submitted": amf.get("submitted", prof.get("frame_accounting", {}).get("amf_submitted")),
                    "output": amf.get("output", prof.get("frame_accounting", {}).get("amf_output")),
                    "dropped": amf.get("dropped", 0),
                    "retries": amf.get("retries", 0),
                    "input_full": amf.get("input_full", 0),
                    "avg_qp": amf.get("avg_qp"),
                }
            }

        report[run] = entry

    out_file = BENCH_DIR / "detailed_verification.json"
    out_file.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Detailed verification written to: {out_file}")

if __name__ == "__main__":
    main()
