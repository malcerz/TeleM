import sys, os, time, json, subprocess
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
from src.ffmpeg.command_builder import get_layout_hud_bbox, get_layout_hud_regions
from src.ffmpeg.streaming import stream_overlay_to_ffmpeg

def test_decision_logic_and_geometry():
    print("=" * 70)
    print("SEKCJA 1: WERYFIKACJA LOGIKI DECYZJI I GEOMETRII ATLASU")
    print("=" * 70)

    # Wariant 1: def_layout.json (pełny zestaw)
    l1 = normalize_layout("def_layout.json", 1920, 1080)
    bx1, by1, bw1, bh1 = get_layout_hud_bbox(l1, 1920, 1080)
    aw1, ah1, regs1 = get_layout_hud_regions(l1, 1920, 1080, max_regions=3)
    print(f"\n1. def_layout.json:")
    print(f"   Global bbox: {bw1}x{bh1} ({bw1*bh1/(1920*1080)*100:.1f}%)")
    print(f"   Atlas: {aw1}x{ah1} ({aw1*ah1/(1920*1080)*100:.1f}% area, {len(regs1)} regions)")
    for i, r in enumerate(regs1):
        print(f"     Reg {i}: src=({r[0]},{r[1]},{r[4]}x{r[5]}) -> atlas=({r[2]},{r[3]})")

    # Wariant 2: Dwa klastry (Top time_block + Bottom HUD)
    l2 = normalize_layout("def_layout.json", 1920, 1080)
    for k, v in list(l2["indicators"].items()):
        if k not in ("time_block", "fit_cadence_text", "fit_enhanced_speed_text", "fit_heart_rate_text"):
            v["enabled"] = False
    bx2, by2, bw2, bh2 = get_layout_hud_bbox(l2, 1920, 1080)
    aw2, ah2, regs2 = get_layout_hud_regions(l2, 1920, 1080, max_regions=3)
    print(f"\n2. Top + Bottom HUD (2 klastry):")
    print(f"   Global bbox: {bw2}x{bh2} ({bw2*bh2/(1920*1080)*100:.1f}%)")
    print(f"   Atlas: {aw2}x{ah2} ({aw2*ah2/(1920*1080)*100:.1f}% area, {len(regs2)} regions)")
    for i, r in enumerate(regs2):
        print(f"     Reg {i}: src=({r[0]},{r[1]},{r[4]}x{r[5]}) -> atlas=({r[2]},{r[3]})")

    # Wariant 3: Dolny HUD (Single Sub-window)
    l3 = normalize_layout(None, 1920, 1080)
    for k, v in list(l3["indicators"].items()):
        if k not in ("speed_visual", "speed_text", "dist_visual", "dist_text", "alt_text"):
            v["enabled"] = False
    bx3, by3, bw3, bh3 = get_layout_hud_bbox(l3, 1920, 1080)
    aw3, ah3, regs3 = get_layout_hud_regions(l3, 1920, 1080, max_regions=3)
    print(f"\n3. Sub-window HUD (1 klaster):")
    print(f"   Global bbox: {bw3}x{bh3} ({bw3*bh3/(1920*1080)*100:.1f}%)")
    print(f"   Atlas: {aw3}x{ah3} ({aw3*ah3/(1920*1080)*100:.1f}% area, {len(regs3)} regions)")

def test_pixel_parity_5points():
    print("\n" + "=" * 70)
    print("SEKCJA 2: PIXEL PARITY (5 TIMESTAMPÓW: 0%, 25%, 50%, 75%, 100%)")
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

    field_samples = {
        "speed_samples": speed_samples,
        "track_samples": track_samples,
        "alt_samples": alt_samples,
        "iso_samples": iso_samples,
        "exposure_samples": exposure_samples,
        "temperature_samples": temp_samples,
    }

    # Use 2-cluster layout (Top + Bottom) for definitive Multi-Region Atlas testing
    test_layout = normalize_layout("def_layout.json", 1920, 1080)
    for k, v in list(test_layout["indicators"].items()):
        if k not in ("time_block", "fit_cadence_text", "fit_enhanced_speed_text", "fit_heart_rate_text"):
            v["enabled"] = False

    # Layout for forced full frame
    full_layout = normalize_layout("def_layout.json", 1920, 1080)
    for k, v in list(full_layout["indicators"].items()):
        if k not in ("time_block", "fit_cadence_text", "fit_enhanced_speed_text", "fit_heart_rate_text"):
            v["enabled"] = False
    full_layout["custom_texts"].append({"enabled": True, "text": "", "x": 0.0, "y": 0.0})
    full_layout["custom_texts"].append({"enabled": True, "text": "", "x": 99.0, "y": 99.0})

    out_atlas = Path('scratch/parity_4b_atlas.mp4')
    out_full = Path('scratch/parity_4b_full.mp4')

    print("Renderowanie wariantu MULTI-REGION ATLAS...")
    stream_overlay_to_ffmpeg(
        ffmpeg_exe="ffmpeg", input_files=[str(v_file)], output_file=str(out_atlas),
        duration_s=37.74, start_dt_utc=anchor_dt, tz_offset_hours=0.0,
        speed_samples=speed_samples, track_samples=track_samples, alt_samples=alt_samples,
        font_path="", layout=test_layout, field_samples=field_samples, target_fps=29.97,
        update_rate_step=1, workers=4, encoder="nv", gpu=0, video_bitrate="40M",
        render_w=3840, render_h=2160, resolution_name="source", rotation_degrees=0,
        container_rotation=0, overlay_w=1920, overlay_h=1080,
        iso_samples=iso_samples, exposure_samples=exposure_samples, temperature_samples=temp_samples,
        fit_data=fit_data, gps_track=fit_data.get("track"),
    )

    print("Renderowanie wariantu FULL FRAME REFERENCE...")
    stream_overlay_to_ffmpeg(
        ffmpeg_exe="ffmpeg", input_files=[str(v_file)], output_file=str(out_full),
        duration_s=37.74, start_dt_utc=anchor_dt, tz_offset_hours=0.0,
        speed_samples=speed_samples, track_samples=track_samples, alt_samples=alt_samples,
        font_path="", layout=full_layout, field_samples=field_samples, target_fps=29.97,
        update_rate_step=1, workers=4, encoder="nv", gpu=0, video_bitrate="40M",
        render_w=3840, render_h=2160, resolution_name="source", rotation_degrees=0,
        container_rotation=0, overlay_w=1920, overlay_h=1080,
        iso_samples=iso_samples, exposure_samples=exposure_samples, temperature_samples=temp_samples,
        fit_data=fit_data, gps_track=fit_data.get("track"),
    )

    timestamps = [
        ("0% (Początek)", 0.0),
        ("25%", 9.4),
        ("50% (Środek)", 18.8),
        ("75%", 28.3),
        ("100% (Koniec)", 37.0),
    ]

    print("\n--- WYNIKI TESTU PIXEL PARITY DLA 5 TIMESTAMPÓW ---")
    for name, ts in timestamps:
        p_atlas = Path(f"scratch/frame_atlas_{ts:.1f}.png")
        p_full = Path(f"scratch/frame_full_ref_{ts:.1f}.png")
        subprocess.run(["ffmpeg", "-y", "-ss", str(ts), "-i", str(out_atlas), "-vframes", "1", str(p_atlas)], check=True, capture_output=True)
        subprocess.run(["ffmpeg", "-y", "-ss", str(ts), "-i", str(out_full), "-vframes", "1", str(p_full)], check=True, capture_output=True)

        arr_a = np.asarray(Image.open(p_atlas))
        arr_f = np.asarray(Image.open(p_full))
        diff = np.abs(arr_a.astype(int) - arr_f.astype(int))
        max_d = int(np.max(diff))
        mean_d = float(np.mean(diff))
        diff_px = int(np.count_nonzero(diff.any(axis=-1)))
        total_px = arr_a.shape[0] * arr_a.shape[1]
        pct = diff_px / total_px * 100.0
        print(f"[{name:15s} t={ts:4.1f}s] Max diff: {max_d:3d} | Mean diff: {mean_d:.4f} | Diff px: {diff_px:7d}/{total_px} ({pct:5.2f}%)")

def run_ab_benchmarks():
    print("\n" + "=" * 70)
    print("SEKCJA 3: BENCHMARK A/B (3× POWTÓRZENIA)")
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

    field_samples = {
        "speed_samples": speed_samples,
        "track_samples": track_samples,
        "alt_samples": alt_samples,
        "iso_samples": iso_samples,
        "exposure_samples": exposure_samples,
        "temperature_samples": temp_samples,
    }

    # Test layout: Top + Bottom 2-cluster layout (time_block + bottom HUD)
    atlas_layout = normalize_layout("def_layout.json", 1920, 1080)
    for k, v in list(atlas_layout["indicators"].items()):
        if k not in ("time_block", "fit_cadence_text", "fit_enhanced_speed_text", "fit_heart_rate_text"):
            v["enabled"] = False

    full_layout = normalize_layout("def_layout.json", 1920, 1080)
    for k, v in list(full_layout["indicators"].items()):
        if k not in ("time_block", "fit_cadence_text", "fit_enhanced_speed_text", "fit_heart_rate_text"):
            v["enabled"] = False
    full_layout["custom_texts"].append({"enabled": True, "text": "", "x": 0.0, "y": 0.0})
    full_layout["custom_texts"].append({"enabled": True, "text": "", "x": 99.0, "y": 99.0})

    results_full = []
    results_atlas = []

    print("\n--- TEST A: FULL FRAME (3 POWTÓRZENIA) ---")
    for run_id in (1, 2, 3):
        t0 = time.perf_counter()
        stream_overlay_to_ffmpeg(
            ffmpeg_exe="ffmpeg", input_files=[str(v_file)], output_file=str(Path(f'scratch/bench_full_run{run_id}.mp4')),
            duration_s=37.74, start_dt_utc=anchor_dt, tz_offset_hours=0.0,
            speed_samples=speed_samples, track_samples=track_samples, alt_samples=alt_samples,
            font_path="", layout=full_layout, field_samples=field_samples, target_fps=29.97,
            update_rate_step=1, workers=4, encoder="nv", gpu=0, video_bitrate="40M",
            render_w=3840, render_h=2160, resolution_name="source", rotation_degrees=0,
            container_rotation=0, overlay_w=1920, overlay_h=1080,
            iso_samples=iso_samples, exposure_samples=exposure_samples, temperature_samples=temp_samples,
            fit_data=fit_data, gps_track=fit_data.get("track"),
        )
        t1 = time.perf_counter()
        results_full.append(t1 - t0)

    print("\n--- TEST B: MULTI-REGION ATLAS (3 POWTÓRZENIA) ---")
    for run_id in (1, 2, 3):
        t0 = time.perf_counter()
        stream_overlay_to_ffmpeg(
            ffmpeg_exe="ffmpeg", input_files=[str(v_file)], output_file=str(Path(f'scratch/bench_atlas_run{run_id}.mp4')),
            duration_s=37.74, start_dt_utc=anchor_dt, tz_offset_hours=0.0,
            speed_samples=speed_samples, track_samples=track_samples, alt_samples=alt_samples,
            font_path="", layout=atlas_layout, field_samples=field_samples, target_fps=29.97,
            update_rate_step=1, workers=4, encoder="nv", gpu=0, video_bitrate="40M",
            render_w=3840, render_h=2160, resolution_name="source", rotation_degrees=0,
            container_rotation=0, overlay_w=1920, overlay_h=1080,
            iso_samples=iso_samples, exposure_samples=exposure_samples, temperature_samples=temp_samples,
            fit_data=fit_data, gps_track=fit_data.get("track"),
        )
        t1 = time.perf_counter()
        results_atlas.append(t1 - t0)

    print("\n" + "=" * 70)
    print("PODSUMOWANIE BENCHMARKU A/B (1132 klatki 4K NVENC):")
    print("=" * 70)
    med_full = float(np.median(results_full))
    med_atlas = float(np.median(results_atlas))
    print(f"FULL FRAME (A) Median: {med_full:.3f} s -> {1132/med_full:.2f} FPS (Runs: {results_full[0]:.2f}s, {results_full[1]:.2f}s, {results_full[2]:.2f}s)")
    print(f"HUD ATLAS  (B) Median: {med_atlas:.3f} s -> {1132/med_atlas:.2f} FPS (Runs: {results_atlas[0]:.2f}s, {results_atlas[1]:.2f}s, {results_atlas[2]:.2f}s)")
    print(f"ZYSK WYDAJNOŚCI: +{((1132/med_atlas) / (1132/med_full) - 1.0)*100.0:.1f}% FPS (czas -{(med_full - med_atlas):.2f} s)")

if __name__ == "__main__":
    test_decision_logic_and_geometry()
    test_pixel_parity_5points()
    run_ab_benchmarks()
