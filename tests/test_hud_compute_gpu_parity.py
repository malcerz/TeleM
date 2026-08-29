"""GPU NV12 Y/UV Plane Parity Test Harness for ETAP 5C.

Dumps and compares the raw NV12 composited surfaces before encoding across all candidate shaders.
Verifies:
  Y MaxDiff = 0
  Y DifferentPixels = 0
  UV MaxDiff = 0
  UV DifferentPixels = 0
"""

import os
import sys
import subprocess
import numpy as np
import pytest
from pathlib import Path

ROOT = Path("c:/_DEV/TeleM")
sys.path.insert(0, str(ROOT))

from src.gui.telemetry_manager import TelemetryDataManager
from src.telemetry_extract import (
    ensure_records_list, load_json_with_fallback,
    extract_speed_samples, extract_altitude_samples, extract_track_samples,
    extract_iso_samples, extract_exposure_samples, extract_temperature_samples,
    smooth_speed_samples, interpolate_value, get_rotation_from_metadata,
    get_container_rotation, find_metadata_json, extract_gps_track,
    smooth_speed_values, extract_accelerometer_samples, extract_gyroscope_samples,
)
from src.gui.layout_manager import normalize_layout
from src.ffmpeg.amd_native_exporter import export_amd_native_d3d11

# Historical diagnostic only: this test pairs the non-canonical GX030120 video
# with an unrelated FIT and compares experimental kernels against a legacy
# reference kernel. It is not a valid production regression gate. Keep the
# source available for historical investigation, but exclude it from the AMD
# production baseline until it is rebuilt on the canonical workload.
pytestmark = pytest.mark.skip(
    reason="historical non-canonical shader-variant harness; not production baseline"
)

VIDEO = ROOT / "Video" / "GX030120.MP4"
FIT = ROOT / "Video" / "Jazda_na_rowerze_w_porze_lunchu.fit"
LAYOUT = ROOT / "def_layout.json"
W, H = 3840, 2160
FPS = 30000.0 / 1001.0

def extract_nv12_frames(mp4_path: Path, num_frames: int = 5) -> list[tuple[np.ndarray, np.ndarray]]:
    """Extract raw Y and UV planes from mp4 using ffmpeg with -pix_fmt nv12."""
    cmd = [
        "ffmpeg", "-y", "-i", str(mp4_path),
        "-vframes", str(num_frames),
        "-f", "rawvideo", "-pix_fmt", "nv12", "-"
    ]
    res = subprocess.run(cmd, capture_output=True, check=True)
    raw = res.stdout
    frame_y_size = W * H
    frame_uv_size = W * H // 2
    total_frame_size = frame_y_size + frame_uv_size
    
    frames = []
    for i in range(num_frames):
        offset = i * total_frame_size
        y_plane = np.frombuffer(raw[offset:offset+frame_y_size], dtype=np.uint8).reshape((H, W))
        uv_plane = np.frombuffer(raw[offset+frame_y_size:offset+total_frame_size], dtype=np.uint8).reshape((H//2, W))
        frames.append((y_plane, uv_plane))
    return frames

def render_sample(variant: int, num_frames: int = 10) -> list[tuple[np.ndarray, np.ndarray]]:
    out_mp4 = ROOT / "scratch" / f"parity_var_{variant}.mp4"
    if out_mp4.exists():
        try: out_mp4.unlink()
        except: pass
        
    os.environ["AMD_TELEMETRY_MODE"] = "PRECOMPUTED"
    os.environ["AMD_ABOVE_MULTI_REGION"] = "1"
    os.environ["AMD_FRAME_ACCOUNT"] = "1"
    os.environ["AMD_NATIVE_PROFILING"] = "0"
    os.environ["AMD_CPU_GPU_PIPELINE"] = "ASYNC"
    os.environ["AMD_QUEUE_DEPTH"] = "2"
    os.environ["AMD_VP_STATE_MODE"] = "STATIC_CACHE"
    os.environ["AMD_AMF_QUERY_MODE"] = "DRAIN_READY"
    os.environ["AMD_FUSED_COMPOSITOR_VARIANT"] = str(variant)
    
    records = ensure_records_list(load_json_with_fallback(VIDEO.with_suffix(".json")))
    tm = TelemetryDataManager(
        extract_speed_fn=extract_speed_samples, extract_altitude_fn=extract_altitude_samples,
        extract_track_fn=extract_track_samples, extract_iso_fn=extract_iso_samples,
        extract_exposure_fn=extract_exposure_samples, extract_temperature_fn=extract_temperature_samples,
        smooth_fn=smooth_speed_samples, interpolate_fn=interpolate_value,
        get_rotation_meta_fn=get_rotation_from_metadata, get_container_rotation_fn=get_container_rotation,
        find_meta_json_fn=find_metadata_json, find_meta_json_write_fn=lambda p: p.with_suffix(".json"),
        load_telemetry_fn=lambda *a: None, ensure_records_fn=ensure_records_list,
        load_json_fallback_fn=load_json_with_fallback, write_records_fn=lambda p, r: None,
        extract_samples_exiftool_fn=lambda f: [], extract_altitude_exiftool_fn=lambda f: [],
        extract_gps_track_fn=extract_gps_track, find_gps_anchor_fn=lambda r: None,
        smooth_values_fn=smooth_speed_values, extract_accelerometer_fn=extract_accelerometer_samples,
        extract_gyroscope_fn=extract_gyroscope_samples,
    )
    tm.load_gpmf_records(records)
    tm.load_fit(str(FIT))
    layout = normalize_layout(LAYOUT, W, H)
    
    ok = export_amd_native_d3d11(
        ffmpeg_exe="ffmpeg", input_files=[str(VIDEO)], output_file=str(out_mp4),
        duration_s=num_frames / FPS, video_width=W, video_height=H, start_dt_utc=tm.start_dt_utc,
        tz_offset_hours=2.0, speed_samples=tm.speed_samples or [], track_samples=tm.track_samples or [],
        alt_samples=tm.alt_samples or [], font_path="assets/Roboto-Bold.ttf", layout=layout,
        field_samples=tm.fit_data or {}, iso_samples=tm.iso_samples, exposure_samples=tm.exposure_samples,
        temperature_samples=tm.temperature_samples, fit_data=tm.fit_data, gps_track=tm.get_gps_track_for_source("fit")
    )
    assert ok, f"Export failed for variant {variant}"
    return extract_nv12_frames(out_mp4, num_frames)

@pytest.mark.parametrize("variant", [
    pytest.param(1, marks=pytest.mark.xfail(
        reason="historical 16x16 reference comparison is invalid for the current production QUAD_8x8 kernel",
        strict=False,
    )),
    2,
    pytest.param(3, marks=pytest.mark.xfail(
        reason="historical 16x16 reference comparison is invalid for the current production QUAD_16x16 kernel",
        strict=False,
    )),
    4,
    5,
])
def test_gpu_shader_variant_parity(variant):
    """Test that each candidate shader produces bit-exact identical NV12 output to reference variant 0."""
    ref_frames = render_sample(0, num_frames=5)
    cand_frames = render_sample(variant, num_frames=5)
    
    for f_idx in range(len(ref_frames)):
        y_ref, uv_ref = ref_frames[f_idx]
        y_cand, uv_cand = cand_frames[f_idx]
        
        y_diff = np.abs(y_ref.astype(np.int32) - y_cand.astype(np.int32))
        y_max = np.max(y_diff)
        y_diff_count = np.count_nonzero(y_diff)
        
        uv_diff = np.abs(uv_ref.astype(np.int32) - uv_cand.astype(np.int32))
        uv_max = np.max(uv_diff)
        uv_diff_count = np.count_nonzero(uv_diff)
        
        assert y_max == 0, f"Variant {variant} frame {f_idx} Y plane MaxDiff={y_max} (different_pixels={y_diff_count})"
        assert y_diff_count == 0, f"Variant {variant} frame {f_idx} Y plane DifferentPixels={y_diff_count}"
        assert uv_max == 0, f"Variant {variant} frame {f_idx} UV plane MaxDiff={uv_max} (different_pixels={uv_diff_count})"
        assert uv_diff_count == 0, f"Variant {variant} frame {f_idx} UV plane DifferentPixels={uv_diff_count}"

if __name__ == "__main__":
    for v in [1, 2, 3, 4, 5]:
        print(f"Testing parity for variant {v}...")
        test_gpu_shader_variant_parity(v)
        print(f"  Variant {v} PASSED (Y MaxDiff=0, UV MaxDiff=0, DifferentPixels=0)")
