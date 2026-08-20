import sys, os, time, subprocess, json
from pathlib import Path
_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

import numpy as np
from PIL import Image
from telemetry_fit import process_fit
from src.gui.layout_manager import normalize_layout
from src.telemetry_gpmf_new import gpmf_to_exiftool_json
from src.telemetry_extract import (
    extract_speed_samples, extract_altitude_samples, extract_track_samples,
    extract_iso_samples, extract_exposure_samples, extract_temperature_samples,
    find_gps_anchor
)
from src.ffmpeg.streaming import stream_overlay_to_ffmpeg
from scratch.gpu_monitor import GPUMonitor

v_file = Path('Video/GX020079.mp4')
fit_file = Path('Video/Morning_Ride.fit')
n_frames = 1132
dummy_atlas_path = Path('scratch/blank_atlas.png')

# Ensure dummy atlas exists
if not dummy_atlas_path.exists():
    Image.new('RGBA', (1112, 668), (0, 0, 0, 0)).save(str(dummy_atlas_path))

def run_single_cli_test(name, cmd):
    mon = GPUMonitor(interval=0.05)
    mon.start()
    t0 = time.perf_counter()
    res = subprocess.run(cmd, capture_output=True, text=True)
    t1 = time.perf_counter()
    mon.stop()
    elapsed = t1 - t0
    fps = n_frames / elapsed if elapsed > 0 else 0
    stats = mon.get_stats()
    if res.returncode != 0:
        print(f"Error in {name}: {res.stderr[:400]}")
    return elapsed, fps, stats

def run_suite_3x(name, run_fn):
    print(f"\n=======================================================")
    print(f"RUNNING: {name} (1 warm-up + 3 measured runs)")
    print(f"=======================================================")
    # Warmup
    print("Warm-up run...")
    run_fn()
    time.sleep(0.5)

    elapsed_list = []
    fps_list = []
    stats_list = []

    for i in range(1, 4):
        print(f"Run {i}/3...")
        el, fps, st = run_fn()
        elapsed_list.append(el)
        fps_list.append(fps)
        stats_list.append(st)
        print(f"  -> Run {i}: {el:.3f} s | {fps:.1f} FPS | NVDEC: {st.get('nvdec_avg',0):.1f}% | NVENC: {st.get('nvenc_avg',0):.1f}% | CUDA: {st.get('gpu_avg',0):.1f}% | CPU: {st.get('cpu_avg',0):.1f}%")
        time.sleep(0.5)

    med_idx = int(np.argsort(fps_list)[1])
    res = {
        "name": name,
        "runs_elapsed": elapsed_list,
        "runs_fps": fps_list,
        "min_fps": float(np.min(fps_list)),
        "max_fps": float(np.max(fps_list)),
        "median_fps": float(np.median(fps_list)),
        "median_elapsed": float(np.median(elapsed_list)),
        "median_stats": stats_list[med_idx],
    }
    print(f"--> MEDIAN {name}: {res['median_fps']:.1f} FPS ({res['median_elapsed']:.3f} s)")
    return res

def main():
    records = gpmf_to_exiftool_json(str(v_file))[0]
    speed_samples = extract_speed_samples(records)
    alt_samples = extract_altitude_samples(records)
    track_samples = extract_track_samples(records)
    iso_samples = extract_iso_samples(records)
    exposure_samples = extract_exposure_samples(records)
    temp_samples = extract_temperature_samples(records)
    anchor_dt = find_gps_anchor(records)
    fit_data = process_fit(str(fit_file), video_start_dt=anchor_dt)

    field_samples = {
        "speed_samples": speed_samples,
        "track_samples": track_samples,
        "alt_samples": alt_samples,
        "iso_samples": iso_samples,
        "exposure_samples": exposure_samples,
        "temperature_samples": temp_samples,
    }

    results = {}

    # -------------------------------------------------------------
    # TEST A: NVDEC ONLY
    # -------------------------------------------------------------
    cmd_a = [
        "ffmpeg", "-y", "-hwaccel", "cuda", "-hwaccel_output_format", "cuda",
        "-i", str(v_file), "-f", "null", "-"
    ]
    results["TEST_A"] = run_suite_3x("TEST A (NVDEC ONLY)", lambda: run_single_cli_test("TEST A", cmd_a))

    # -------------------------------------------------------------
    # TEST B: NVDEC + TeleM conversion (scale_cuda=format=yuv420p) + NVENC
    # -------------------------------------------------------------
    cmd_b = [
        "ffmpeg", "-y", "-hwaccel", "cuda", "-hwaccel_output_format", "cuda",
        "-i", str(v_file),
        "-filter_complex", "[0:v]scale_cuda=format=yuv420p[base];[base]null[vout]",
        "-map", "[vout]", "-map_metadata", "-1", "-metadata:s:v:0", "rotate=0",
        "-c:v", "hevc_nvenc", "-preset", "p1", "-tune", "hq", "-rc", "vbr",
        "-cq", "24", "-pix_fmt", "cuda", "-gpu", "0",
        "-b:v", "40M", "-maxrate", "40M", "-bufsize", "80M",
        "-f", "null", "-"
    ]
    results["TEST_B"] = run_suite_3x("TEST B (BARE TRANSCODE NVDEC -> NVENC)", lambda: run_single_cli_test("TEST B", cmd_b))

    # -------------------------------------------------------------
    # TEST C: NVDEC + SCALE/FORMAT + NVENC + 3-Region overlay_cuda NO-OP
    # -------------------------------------------------------------
    cmd_c = [
        "ffmpeg", "-y", "-hwaccel", "cuda", "-hwaccel_output_format", "cuda",
        "-i", str(v_file),
        "-loop", "1", "-framerate", "29.97", "-t", "37.74", "-i", str(dummy_atlas_path),
        "-filter_complex", (
            "[0:v]scale_cuda=format=yuv420p[base];"
            "[1:v]setpts=PTS-STARTPTS,format=rgba,split=3[ov_raw_0][ov_raw_1][ov_raw_2];"
            "[ov_raw_0]crop=426:170:0:0,scale=852:340:flags=bilinear,format=yuva420p,hwupload_cuda[ov_0];"
            "[ov_raw_1]crop=678:332:430:0,scale=1356:664:flags=bilinear,format=yuva420p,hwupload_cuda[ov_1];"
            "[ov_raw_2]crop=1082:332:0:336,scale=2164:664:flags=bilinear,format=yuva420p,hwupload_cuda[ov_2];"
            "[base][ov_0]overlay_cuda=x=20:y=28[v_step_0];"
            "[v_step_0][ov_1]overlay_cuda=x=2380:y=1496[v_step_1];"
            "[v_step_1][ov_2]overlay_cuda=x=88:y=1496[vout]"
        ),
        "-map", "[vout]", "-map_metadata", "-1", "-metadata:s:v:0", "rotate=0",
        "-c:v", "hevc_nvenc", "-preset", "p1", "-tune", "hq", "-rc", "vbr",
        "-cq", "24", "-pix_fmt", "cuda", "-gpu", "0",
        "-b:v", "40M", "-maxrate", "40M", "-bufsize", "80M",
        "-f", "null", "-"
    ]
    results["TEST_C"] = run_suite_3x("TEST C (CUDA FILTER GRAPH NO-OP)", lambda: run_single_cli_test("TEST C", cmd_c))

    # -------------------------------------------------------------
    # TEST D: FULL TELEM ATLAS (Stage 4B actual production pipeline)
    # -------------------------------------------------------------
    def run_telem_d():
        mon = GPUMonitor(interval=0.05)
        mon.start()
        t0 = time.perf_counter()
        # Normal production layout
        prod_layout = normalize_layout("def_layout.json", 1920, 1080)
        out_f = Path("scratch/etap4c_telem_out.mp4")
        stream_overlay_to_ffmpeg(
            ffmpeg_exe="ffmpeg", input_files=[str(v_file)], output_file=str(out_f),
            duration_s=37.74, start_dt_utc=anchor_dt, tz_offset_hours=0.0,
            speed_samples=speed_samples, track_samples=track_samples, alt_samples=alt_samples,
            font_path="", layout=prod_layout, field_samples=field_samples, target_fps=29.97,
            update_rate_step=1, workers=4, encoder="nv", gpu=0, video_bitrate="40M",
            render_w=3840, render_h=2160, resolution_name="source", rotation_degrees=0,
            container_rotation=0, overlay_w=1920, overlay_h=1080,
            iso_samples=iso_samples, exposure_samples=exposure_samples, temperature_samples=temp_samples,
            fit_data=fit_data, gps_track=fit_data.get("track"),
        )
        t1 = time.perf_counter()
        mon.stop()
        elapsed = t1 - t0
        fps = n_frames / elapsed
        stats = mon.get_stats()
        return elapsed, fps, stats

    results["TEST_D"] = run_suite_3x("TEST D (FULL TELEM ATLAS STAGE 4B)", run_telem_d)

    # -------------------------------------------------------------
    # TEST E: NVENC ONLY (Synthetic frames)
    # -------------------------------------------------------------
    cmd_e = [
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", f"nullsrc=s=3840x2160:r=29.97:d=37.74",
        "-filter_complex", "[0:v]format=yuv420p,hwupload_cuda[vout]",
        "-map", "[vout]",
        "-c:v", "hevc_nvenc", "-preset", "p1", "-tune", "hq", "-rc", "vbr",
        "-cq", "24", "-pix_fmt", "cuda", "-gpu", "0",
        "-b:v", "40M", "-maxrate", "40M", "-bufsize", "80M",
        "-f", "null", "-"
    ]
    results["TEST_E"] = run_suite_3x("TEST E (NVENC ONLY)", lambda: run_single_cli_test("TEST E", cmd_e))

    # Save results to JSON
    with open("scratch/etap4c_benchmark_results.json", "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)

    print("\n" + "=" * 70)
    print("ALL TESTS COMPLETED SUCCESSFULLY!")
    print("=" * 70)

if __name__ == "__main__":
    main()
