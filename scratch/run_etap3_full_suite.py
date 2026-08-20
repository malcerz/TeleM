import sys, os, time, subprocess
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
from src.indicators.compositor import compose_overlay
from src.ffmpeg.command_builder import get_layout_hud_bbox
from src.ffmpeg.streaming import stream_overlay_to_ffmpeg

def test_alpha_bbox_verification():
    print("=" * 70)
    print("SEKCJA 1: WERYFIKACJA BBOX VS RZECZYWISTY ALPHA BBOX")
    print("=" * 70)
    
    # 1. Layout z dolnym HUDem (Sub-window HUD)
    layout = normalize_layout(None, 1920, 1080)
    for k, v in list(layout["indicators"].items()):
        if k not in ("speed_visual", "speed_text", "dist_visual", "dist_text", "alt_text"):
            v["enabled"] = False

    bx, by, bw, bh = get_layout_hud_bbox(layout, 1920, 1080)
    pred_x1, pred_y1, pred_x2, pred_y2 = bx, by, bx + bw, by + bh
    
    img = compose_overlay(
        1920, 1080, layout, "",
        "", "",
        28.5, 4500.0, 12000.0,
        145.0, 50.0, 300.0,
        100.0, 500.0, 25.0,
        indicator_values={"speed_visual": 28.5, "speed_text": 28.5, "dist_visual": 4.5, "dist_text": 4.5, "alt_text": 145.0},
    )
    arr = np.asarray(img)
    alpha = arr[..., 3]
    y_idx, x_idx = np.nonzero(alpha > 0)
    act_x1, act_y1 = int(np.min(x_idx)), int(np.min(y_idx))
    act_x2, act_y2 = int(np.max(x_idx) + 1), int(np.max(y_idx) + 1)
    
    delta_left = act_x1 - pred_x1
    delta_top = act_y1 - pred_y1
    delta_right = pred_x2 - act_x2
    delta_bottom = pred_y2 - act_y2
    
    print(f"Predicted BBox:       [{pred_x1}, {pred_y1}, {pred_x2}, {pred_y2}] ({bw}x{bh})")
    print(f"Actual Alpha BBox:    [{act_x1}, {act_y1}, {act_x2}, {act_y2}] ({act_x2-act_x1}x{act_y2-act_y1})")
    print(f"Marginesy (deltas):   left={delta_left}px, top={delta_top}px, right={delta_right}px, bottom={delta_bottom}px")
    assert delta_left >= 0, "BBox obcina lewą krawędź!"
    assert delta_top >= 0, "BBox obcina górną krawędź!"
    assert delta_right >= 0, "BBox obcina prawą krawędź!"
    assert delta_bottom >= 0, "BBox obcina dolną krawędź!"
    print("STATUS BBOX: ZERO CLIPPING! Wszystkie marginesy dodatnie.\n")
    return layout

def test_5point_pixel_parity():
    print("=" * 70)
    print("SEKCJA 2: PIXEL PARITY TEST (5 TIMESTAMPÓW: 0%, 25%, 50%, 75%, 100%)")
    print("=" * 70)
    
    v_file = Path('Video/GX020079.mp4')
    fit_file = Path('Video/Morning_Ride.fit')
    records = gpmf_to_exiftool_json(str(v_file))[0]
    speed_samples = extract_speed_samples(records)
    alt_samples = extract_altitude_samples(records)
    track_samples = extract_track_samples(records)
    iso_samples = extract_iso_samples(records)
    exposure_samples = extract_exposure_samples(records)
    temp_samples = extract_temperature_samples(records)
    anchor_dt = find_gps_anchor(records)
    fit_data = process_fit(str(fit_file), video_start_dt=anchor_dt)

    test_layout = normalize_layout(None, 1920, 1080)
    for k, v in list(test_layout["indicators"].items()):
        if k not in ("speed_visual", "speed_text", "dist_visual", "dist_text", "alt_text"):
            v["enabled"] = False

    # Layout for forced fallback (full 1920x1080)
    full_layout = normalize_layout(None, 1920, 1080)
    for k, v in list(full_layout["indicators"].items()):
        if k not in ("speed_visual", "speed_text", "dist_visual", "dist_text", "alt_text"):
            v["enabled"] = False
    full_layout["custom_texts"].append({"enabled": True, "text": "", "x": 0.0, "y": 0.0})
    full_layout["custom_texts"].append({"enabled": True, "text": "", "x": 99.0, "y": 99.0})

    out_bbox_video = Path('scratch/parity_5pt_bbox.mp4')
    out_full_video = Path('scratch/parity_5pt_full.mp4')

    print("Renderowanie wariantu ETAP 3 (HUD BBox)...")
    stream_overlay_to_ffmpeg(
        ffmpeg_exe="ffmpeg", input_files=[str(v_file)], output_file=str(out_bbox_video),
        duration_s=37.74, start_dt_utc=anchor_dt, tz_offset_hours=0.0,
        speed_samples=speed_samples, track_samples=track_samples, alt_samples=alt_samples,
        font_path="", layout=test_layout, field_samples={}, target_fps=29.97,
        update_rate_step=1, workers=4, encoder="nv", gpu=0, video_bitrate="40M",
        render_w=3840, render_h=2160, resolution_name="source", rotation_degrees=0,
        container_rotation=0, overlay_w=1920, overlay_h=1080,
        iso_samples=iso_samples, exposure_samples=exposure_samples, temperature_samples=temp_samples,
        fit_data=fit_data, gps_track=fit_data.get("track"),
    )

    print("Renderowanie wariantu ETAP 2 (Full Frame 1920x1080)...")
    stream_overlay_to_ffmpeg(
        ffmpeg_exe="ffmpeg", input_files=[str(v_file)], output_file=str(out_full_video),
        duration_s=37.74, start_dt_utc=anchor_dt, tz_offset_hours=0.0,
        speed_samples=speed_samples, track_samples=track_samples, alt_samples=alt_samples,
        font_path="", layout=full_layout, field_samples={}, target_fps=29.97,
        update_rate_step=1, workers=4, encoder="nv", gpu=0, video_bitrate="40M",
        render_w=3840, render_h=2160, resolution_name="source", rotation_degrees=0,
        container_rotation=0, overlay_w=1920, overlay_h=1080,
        iso_samples=iso_samples, exposure_samples=exposure_samples, temperature_samples=temp_samples,
        fit_data=fit_data, gps_track=fit_data.get("track"),
    )

    # Sprawdź 5 timestampów
    timestamps = [
        ("0% (Początek)", 0.0),
        ("25%", 9.4),
        ("50% (Środek)", 18.8),
        ("75%", 28.3),
        ("100% (Koniec)", 37.0),
    ]

    print("\n--- WYNIKI TESTU PIXEL PARITY DLA 5 TIMESTAMPÓW ---")
    for name, ts in timestamps:
        p_bbox = Path(f"scratch/frame_bbox_{ts:.1f}.png")
        p_full = Path(f"scratch/frame_full_{ts:.1f}.png")
        subprocess.run(["ffmpeg", "-y", "-ss", str(ts), "-i", str(out_bbox_video), "-vframes", "1", str(p_bbox)], check=True, capture_output=True)
        subprocess.run(["ffmpeg", "-y", "-ss", str(ts), "-i", str(out_full_video), "-vframes", "1", str(p_full)], check=True, capture_output=True)

        arr_b = np.asarray(Image.open(p_bbox))
        arr_f = np.asarray(Image.open(p_full))
        diff = np.abs(arr_b.astype(int) - arr_f.astype(int))
        max_d = int(np.max(diff))
        mean_d = float(np.mean(diff))
        diff_px = int(np.count_nonzero(diff.any(axis=-1)))
        total_px = arr_b.shape[0] * arr_b.shape[1]
        pct = diff_px / total_px * 100.0
        
        # Check non-HUD region (top 50% of frame)
        non_hud_diff = diff[:1000, :, :]
        non_hud_max = int(np.max(non_hud_diff))
        print(f"[{name:15s} t={ts:4.1f}s] Max diff: {max_d:3d} | Mean diff: {mean_d:.4f} | Diff px: {diff_px:7d}/{total_px} ({pct:5.2f}%) | Non-HUD diff: {non_hud_max}")

def run_benchmarks():
    print("\n" + "=" * 70)
    print("SEKCJA 3: BENCHMARK WYDAJNOŚCI (1132 KLATKI 4K NVENC)")
    print("=" * 70)

    v_file = Path('Video/GX020079.mp4')
    fit_file = Path('Video/Morning_Ride.fit')
    records = gpmf_to_exiftool_json(str(v_file))[0]
    speed_samples = extract_speed_samples(records)
    alt_samples = extract_altitude_samples(records)
    track_samples = extract_track_samples(records)
    iso_samples = extract_iso_samples(records)
    exposure_samples = extract_exposure_samples(records)
    temp_samples = extract_temperature_samples(records)
    anchor_dt = find_gps_anchor(records)
    fit_data = process_fit(str(fit_file), video_start_dt=anchor_dt)

    test_layout = normalize_layout(None, 1920, 1080)
    for k, v in list(test_layout["indicators"].items()):
        if k not in ("speed_visual", "speed_text", "dist_visual", "dist_text", "alt_text"):
            v["enabled"] = False

    full_layout = normalize_layout(None, 1920, 1080)
    for k, v in list(full_layout["indicators"].items()):
        if k not in ("speed_visual", "speed_text", "dist_visual", "dist_text", "alt_text"):
            v["enabled"] = False
    full_layout["custom_texts"].append({"enabled": True, "text": "", "x": 0.0, "y": 0.0})
    full_layout["custom_texts"].append({"enabled": True, "text": "", "x": 99.0, "y": 99.0})

    # Benchmark 1: ETAP 2 (Full Frame Baseline)
    print("\n--- 3.A ETAP 2 Full Frame Baseline (1920x1080) ---")
    t0 = time.perf_counter()
    n_full = stream_overlay_to_ffmpeg(
        ffmpeg_exe="ffmpeg", input_files=[str(v_file)], output_file=str(Path('scratch/bench_full.mp4')),
        duration_s=37.74, start_dt_utc=anchor_dt, tz_offset_hours=0.0,
        speed_samples=speed_samples, track_samples=track_samples, alt_samples=alt_samples,
        font_path="", layout=full_layout, field_samples={}, target_fps=29.97,
        update_rate_step=1, workers=4, encoder="nv", gpu=0, video_bitrate="40M",
        render_w=3840, render_h=2160, resolution_name="source", rotation_degrees=0,
        container_rotation=0, overlay_w=1920, overlay_h=1080,
        iso_samples=iso_samples, exposure_samples=exposure_samples, temperature_samples=temp_samples,
        fit_data=fit_data, gps_track=fit_data.get("track"),
    )
    t1 = time.perf_counter()
    time_full = t1 - t0
    fps_full = n_full / time_full
    print(f"ETAP 2 Full Frame: {n_full} frames in {time_full:.2f} s -> {fps_full:.2f} FPS")

    # Benchmark 2: ETAP 3 (HUD BBox)
    print("\n--- 3.B ETAP 3 HUD BBox (1712x488) ---")
    t0 = time.perf_counter()
    n_bbox = stream_overlay_to_ffmpeg(
        ffmpeg_exe="ffmpeg", input_files=[str(v_file)], output_file=str(Path('scratch/bench_bbox.mp4')),
        duration_s=37.74, start_dt_utc=anchor_dt, tz_offset_hours=0.0,
        speed_samples=speed_samples, track_samples=track_samples, alt_samples=alt_samples,
        font_path="", layout=test_layout, field_samples={}, target_fps=29.97,
        update_rate_step=1, workers=4, encoder="nv", gpu=0, video_bitrate="40M",
        render_w=3840, render_h=2160, resolution_name="source", rotation_degrees=0,
        container_rotation=0, overlay_w=1920, overlay_h=1080,
        iso_samples=iso_samples, exposure_samples=exposure_samples, temperature_samples=temp_samples,
        fit_data=fit_data, gps_track=fit_data.get("track"),
    )
    t1 = time.perf_counter()
    time_bbox = t1 - t0
    fps_bbox = n_bbox / time_bbox
    print(f"ETAP 3 HUD BBox: {n_bbox} frames in {time_bbox:.2f} s -> {fps_bbox:.2f} FPS")
    print(f"Zysk throughputu: +{((fps_bbox / fps_full) - 1.0)*100.0:.1f}%")

if __name__ == "__main__":
    test_alpha_bbox_verification()
    test_5point_pixel_parity()
    run_benchmarks()
