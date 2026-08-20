import sys, os, time, subprocess, re
from pathlib import Path

v_file = Path("Video/GX030120.MP4")
n_frames = 5400

def run_cuda_noop_benchmark(regions_count: int, atlas_w: int, atlas_h: int, regions_list: list):
    # Construct FFmpeg command with rawvideo transparent atlas input -> split -> crop -> scale -> hwupload_cuda -> overlay_cuda -> hevc_nvenc -> null
    # Generate null rawvideo source using FFmpeg color / rawvideo input or lavfi
    # To test pure CUDA graph speed, input 1 is lavfi color=c=black@0.0:s={atlas_w}x{atlas_h}:r=29.97
    
    splits = "".join([f"[ov_raw_{i}]" for i in range(regions_count)])
    crop_scale_chain = []
    overlay_chain = []
    
    prev_step = "[base]"
    for i, r in enumerate(regions_list):
        sx, sy, ax, ay, rw, rh = r
        # 4K target coordinates (2x scaled from 1080p)
        t_x = sx * 2
        t_y = sy * 2
        t_w = rw * 2
        t_h = rh * 2
        crop_scale_chain.append(
            f"[ov_raw_{i}]crop={rw}:{rh}:{ax}:{ay},scale={t_w}:{t_h}:flags=bilinear,format=yuva420p,hwupload_cuda[ov_{i}];"
        )
        next_step = f"[v_step_{i}]" if i < regions_count - 1 else "[vtemp]"
        overlay_chain.append(
            f"{prev_step}[ov_{i}]overlay_cuda=x={t_x}:y={t_y}{next_step};"
        )
        prev_step = next_step

    filter_complex = (
        "[0:v]scale_cuda=format=yuv420p[base];"
        f"[1:v]setpts=PTS-STARTPTS,format=rgba,split={regions_count}{splits};"
        + "".join(crop_scale_chain)
        + "".join(overlay_chain)
        + "[vtemp]null[vtemp2];[vtemp2]null[vout]"
    )

    cmd = [
        "ffmpeg", "-y",
        "-hwaccel", "cuda", "-hwaccel_output_format", "cuda",
        "-i", str(v_file),
        "-f", "lavfi", "-i", f"color=c=black@0.0:s={atlas_w}x{atlas_h}:r=29.97",
        "-filter_complex", filter_complex,
        "-map", "[vout]",
        "-c:v", "hevc_nvenc", "-preset", "p1", "-tune", "hq", "-rc", "vbr", "-cq", "24", "-pix_fmt", "cuda", "-gpu", "0",
        "-f", "null", "-",
    ]

    t0 = time.perf_counter()
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    t1 = time.perf_counter()
    duration = t1 - t0
    fps = n_frames / duration if duration > 0 else 0.0

    return {
        "regions": regions_count,
        "atlas_w": atlas_w,
        "atlas_h": atlas_h,
        "duration_s": duration,
        "fps": fps,
        "stderr": proc.stderr[-300:] if proc.stderr else "",
    }

def main():
    print("=" * 80)
    print("CUDA NO-OP BENCHMARK: REGION SCALING ON RTX 5070 Ti (5400 FRAMES 4K)")
    print("=" * 80)

    # 1. Single Region (FULL FRAME 1920x1080)
    cmd_1 = [
        "ffmpeg", "-y",
        "-hwaccel", "cuda", "-hwaccel_output_format", "cuda",
        "-i", str(v_file),
        "-f", "lavfi", "-i", "color=c=black@0.0:s=1920x1080:r=29.97",
        "-filter_complex", "[0:v]scale_cuda=format=yuv420p[base];[1:v]setpts=PTS-STARTPTS,format=rgba,scale=3840:2160:flags=bilinear,format=yuva420p,hwupload_cuda[ov];[base][ov]overlay_cuda=x=0:y=0[vtemp];[vtemp]null[vtemp2];[vtemp2]null[vout]",
        "-map", "[vout]",
        "-c:v", "hevc_nvenc", "-preset", "p1", "-tune", "hq", "-rc", "vbr", "-cq", "24", "-pix_fmt", "cuda", "-gpu", "0",
        "-f", "null", "-",
    ]
    t0 = time.perf_counter()
    subprocess.run(cmd_1, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    t1 = time.perf_counter()
    fps_1 = n_frames / (t1 - t0)
    print(f"1 Region (FULL_FRAME 1920x1080):  {fps_1:.1f} FPS ({(t1-t0):.2f} s)")

    # 2. 3 Regions (Current)
    # Regions: (45,748, 0,0, 1824,332), (11,14, 0,336, 426,642), (940,66, 430,336, 980,524)
    r3 = [
        (44, 748, 0, 0, 1824, 332),
        (10, 14, 0, 336, 426, 642),
        (940, 66, 430, 336, 980, 524),
    ]
    res_3 = run_cuda_noop_benchmark(3, 1828, 978, r3)
    print(f"3 Regions (Atlas 1828x978):       {res_3['fps']:.1f} FPS ({res_3['duration_s']:.2f} s)")

    # 3. 4 Regions
    r4 = [
        (44, 748, 0, 0, 1824, 332),
        (10, 14, 0, 336, 426, 642),
        (940, 66, 430, 336, 368, 200),
        (1466, 118, 802, 336, 454, 472),
    ]
    res_4 = run_cuda_noop_benchmark(4, 1828, 978, r4)
    print(f"4 Regions (Atlas 1828x978):       {res_4['fps']:.1f} FPS ({res_4['duration_s']:.2f} s)")

    # 4. 5 Regions
    r5 = [
        (44, 748, 0, 0, 1824, 332),
        (10, 14, 0, 336, 426, 170),
        (10, 430, 430, 336, 366, 226),
        (940, 66, 800, 336, 368, 200),
        (1466, 118, 1172, 336, 454, 472),
    ]
    res_5 = run_cuda_noop_benchmark(5, 1828, 808, r5)
    print(f"5 Regions (Atlas 1828x808):       {res_5['fps']:.1f} FPS ({res_5['duration_s']:.2f} s)")

if __name__ == "__main__":
    main()
