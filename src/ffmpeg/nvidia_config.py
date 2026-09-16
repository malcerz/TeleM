"""NVIDIA Configuration, Profiles, and Native D3D11/NVENC Bindings.

Provides:
- Canonical NvidiaBackend identifiers (Single Source of Truth).
- Frozen 5-profile resolution matching STAGE 8K.5A locked profiles.
- Native ctypes bindings and structures for telem_nvenc_native.dll.
- Capability detection for NVIDIA Native D3D11 without crashes.
"""

from __future__ import annotations

import os
import sys
import ctypes
from ctypes import wintypes
from enum import Enum
from pathlib import Path
from typing import Optional, Tuple


class NvidiaBackend(str, Enum):
    NVIDIA_LEGACY_CUDA = "NVIDIA_LEGACY_CUDA"
    NVIDIA_NATIVE_D3D11 = "NVIDIA_NATIVE_D3D11"


# Canonical Production Profiles
LOCKED_PROFILES = {
    "HEVC_FAST": {
        "codec": 0,          # TELEM_CODEC_HEVC
        "quality_mode": 0,   # TELEM_QMODE_FAST
        "ffmpeg_fmt": "hevc",
        "vtag": "hvc1",
        "name": "HEVC — Fast",
        "gui_label": "HEVC Fast (P1, Real-Time)",
    },
    "HEVC_QUALITY": {
        "codec": 0,
        "quality_mode": 1,   # TELEM_QMODE_QUALITY
        "ffmpeg_fmt": "hevc",
        "vtag": "hvc1",
        "name": "HEVC — Quality",
        "gui_label": "HEVC Quality (P5, HQ, Lookahead 16)",
    },
    "HEVC_MAX": {
        "codec": 0,
        "quality_mode": 2,   # TELEM_QMODE_MAX
        "ffmpeg_fmt": "hevc",
        "vtag": "hvc1",
        "name": "HEVC — Max Quality",
        "gui_label": "HEVC Max Quality (P7, UHQ, TF Level 4, B=5)",
    },
    "AV1_QUALITY": {
        "codec": 1,          # TELEM_CODEC_AV1
        "quality_mode": 1,   # TELEM_QMODE_QUALITY
        "ffmpeg_fmt": "obu",
        "vtag": "av01",
        "name": "AV1 — Quality",
        "gui_label": "AV1 Quality (P5, HQ, Lookahead 16)",
    },
    "AV1_MAX": {
        "codec": 1,
        "quality_mode": 2,   # TELEM_QMODE_MAX
        "ffmpeg_fmt": "obu",
        "vtag": "av01",
        "name": "AV1 — Max Quality",
        "gui_label": "AV1 Max Quality (P7, UHQ, TF Level 4, B=7)",
    },
    "H264_FAST": {
        "codec": 2,          # TELEM_CODEC_H264
        "quality_mode": 0,   # TELEM_QMODE_FAST
        "ffmpeg_fmt": "h264",
        "vtag": "avc1",
        "name": "H.264 — Fast",
        "gui_label": "H.264 Fast (P1, Real-Time)",
    },
    "H264_QUALITY": {
        "codec": 2,
        "quality_mode": 1,   # TELEM_QMODE_QUALITY
        "ffmpeg_fmt": "h264",
        "vtag": "avc1",
        "name": "H.264 — Quality",
        "gui_label": "H.264 Quality (P5, HQ, Lookahead 16)",
    },
    "H264_MAX": {
        "codec": 2,
        "quality_mode": 2,   # TELEM_QMODE_MAX
        "ffmpeg_fmt": "h264",
        "vtag": "avc1",
        "name": "H.264 — Max Quality",
        "gui_label": "H.264 Max Quality (P7, HQ, B=5)",
    },
}


def resolve_nvidia_profile(codec: str, quality: str) -> str:
    """Resolve logical (codec, quality) pair to canonical locked profile name.

    Strictly forbids AV1 + Fast with zero silent fallback.
    """
    c_norm = str(codec).strip().upper()
    q_norm = str(quality).strip().lower()

    if "AV1" in c_norm:
        if "fast" in q_norm:
            return "AV1_FAST"
        elif "max" in q_norm:
            return "AV1_MAX"
        elif "qual" in q_norm or "standard" in q_norm:
            return "AV1_QUALITY"
        else:
            raise ValueError(f"Nieobsługiwany poziom jakości AV1: {quality}")
    elif "264" in c_norm or "AVC" in c_norm:
        if "fast" in q_norm:
            return "H264_FAST"
        elif "max" in q_norm:
            return "H264_MAX"
        elif "qual" in q_norm or "standard" in q_norm:
            return "H264_QUALITY"
        else:
            raise ValueError(f"Nieobsługiwany poziom jakości H.264: {quality}")
    else:  # HEVC
        if "fast" in q_norm:
            return "HEVC_FAST"
        elif "max" in q_norm:
            return "HEVC_MAX"
        elif "qual" in q_norm or "standard" in q_norm:
            return "HEVC_QUALITY"
        else:
            raise ValueError(f"Nieobsługiwany poziom jakości HEVC: {quality}")


def resolve_nvenc_ffmpeg_params(
    codec: str,
    quality: str,
    is_10bit: bool = False,
) -> dict:
    """Resolve logical (codec, quality) pair to FFmpeg NVENC command arguments.

    Bitrate is explicitly excluded (remains independent user setting).
    """
    profile_name = resolve_nvidia_profile(codec, quality)
    c_norm = str(codec).strip().upper()
    q_norm = str(quality).strip().lower()

    if "AV1" in c_norm:
        enc_name = "av1_nvenc"
        vtag = "av01"
        if "max" in q_norm:
            args = [
                "-c:v", enc_name,
                "-preset", "p7", "-tune", "uhq",
                "-rc", "vbr", "-cq", "24",
                "-rc-lookahead", "32",
                "-spatial-aq", "1", "-temporal-aq", "1",
                "-b_ref_mode", "middle",
            ]
        elif "fast" in q_norm:
            args = [
                "-c:v", enc_name,
                "-preset", "p1", "-tune", "hq",
                "-rc", "vbr", "-cq", "24",
            ]
        else:  # Quality
            args = [
                "-c:v", enc_name,
                "-preset", "p5", "-tune", "hq",
                "-rc", "vbr", "-cq", "24",
                "-rc-lookahead", "16",
                "-spatial-aq", "1", "-temporal-aq", "1",
            ]
    elif "264" in c_norm or "AVC" in c_norm:
        enc_name = "h264_nvenc"
        vtag = "avc1"
        if "max" in q_norm:
            args = [
                "-c:v", enc_name,
                "-preset", "p7", "-tune", "hq",
                "-rc", "vbr", "-cq", "24",
                "-rc-lookahead", "32",
                "-spatial-aq", "1", "-temporal-aq", "1",
                "-b_ref_mode", "middle",
                "-profile:v", "high",
            ]
        elif "qual" in q_norm or "standard" in q_norm:
            args = [
                "-c:v", enc_name,
                "-preset", "p5", "-tune", "hq",
                "-rc", "vbr", "-cq", "24",
                "-rc-lookahead", "16",
                "-spatial-aq", "1", "-temporal-aq", "1",
                "-profile:v", "high",
            ]
        else:  # Fast
            args = [
                "-c:v", enc_name,
                "-preset", "p1", "-tune", "hq",
                "-rc", "vbr", "-cq", "24",
                "-profile:v", "high",
            ]
    else:  # HEVC
        enc_name = "hevc_nvenc"
        vtag = "hvc1"
        if "max" in q_norm:
            args = [
                "-c:v", enc_name,
                "-preset", "p7", "-tune", "uhq",
                "-rc", "vbr", "-cq", "24",
                "-rc-lookahead", "32",
                "-spatial-aq", "1", "-temporal-aq", "1",
                "-b_ref_mode", "middle",
            ]
        elif "qual" in q_norm or "standard" in q_norm:
            args = [
                "-c:v", enc_name,
                "-preset", "p5", "-tune", "hq",
                "-rc", "vbr", "-cq", "24",
                "-rc-lookahead", "16",
                "-spatial-aq", "1", "-temporal-aq", "1",
            ]
        else:  # Fast
            args = [
                "-c:v", enc_name,
                "-preset", "p1", "-tune", "hq",
                "-rc", "vbr", "-cq", "24",
            ]
        if is_10bit:
            args.extend(["-profile:v", "main10"])

    return {
        "profile_name": profile_name,
        "encoder": enc_name,
        "vtag": vtag,
        "ffmpeg_args": args,
        "is_10bit": is_10bit,
    }


def get_native_dll_path() -> Path:
    """Locate the telem_nvenc_native.dll binary, supporting test override."""
    override = os.environ.get("TELEM_NVENC_DLL_OVERRIDE")
    if override:
        p_over = Path(override).resolve()
        if p_over.exists():
            return p_over
    base_dir = Path(__file__).resolve().parent.parent.parent
    candidate = base_dir / "native" / "d3d11_nvenc_pipeline" / "bin" / "telem_nvenc_native.dll"
    if candidate.exists():
        return candidate
    candidate2 = base_dir / "native" / "d3d11_nvenc_pipeline" / "build" / "bin" / "Release" / "telem_nvenc_native.dll"
    if candidate2.exists():
        return candidate2
    return candidate


def is_nvidia_native_available() -> Tuple[bool, str]:
    """Check whether NVIDIA Native D3D11/NVENC pipeline is available on this system."""
    if sys.platform != "win32":
        return False, "Obsługa dostępna tylko na platformie Windows."

    dll_path = get_native_dll_path()
    if not dll_path.exists():
        return False, f"Brak biblioteki telem_nvenc_native.dll ({dll_path})"

    try:
        base_dir = Path(__file__).resolve().parent.parent.parent
        bin_dir = base_dir / "native" / "d3d11_nvenc_pipeline" / "bin"
        if bin_dir.exists() and hasattr(os, "add_dll_directory"):
            try:
                os.add_dll_directory(str(bin_dir.resolve()))
            except Exception:
                pass
        if dll_path.parent.exists() and hasattr(os, "add_dll_directory"):
            try:
                os.add_dll_directory(str(dll_path.parent.resolve()))
            except Exception:
                pass
        dll = ctypes.CDLL(str(dll_path))
        if not hasattr(dll, "telem_nvenc_create"):
            return False, "Biblioteka DLL nie posiada wymaganego eksportu telem_nvenc_create."
        return True, "Dostępny"
    except Exception as ex:
        return False, f"Błąd ładowania DLL: {ex}"


# ==============================================================================
# CTYPES STRUCTURES & BINDINGS
# ==============================================================================

class TelemVideoClipDesc(ctypes.Structure):
    _pack_ = 1
    _fields_ = [
        ("path", ctypes.c_wchar * 512),
        ("frame_count", ctypes.c_uint32),
        ("duration_sec", ctypes.c_double),
        ("fps_num", ctypes.c_uint32),
        ("fps_den", ctypes.c_uint32),
        ("global_start_frame", ctypes.c_uint32),
        ("global_start_time", ctypes.c_double),
    ]


class TelemFrameState(ctypes.Structure):
    _pack_ = 1
    _fields_ = [
        ("frame_index", ctypes.c_uint32),
        ("timestamp_sec", ctypes.c_double),
        ("speed_kmh", ctypes.c_float),
        ("heart_rate_bpm", ctypes.c_float),
        ("cadence_rpm", ctypes.c_float),
        ("power_w", ctypes.c_float),
        ("distance_km", ctypes.c_float),
        ("altitude_m", ctypes.c_float),
        ("solar_pct", ctypes.c_float),
        ("garmin_battery_pct", ctypes.c_float),
        ("gopro_battery_pct", ctypes.c_float),
        ("temperature_c", ctypes.c_float),
        ("iso", ctypes.c_float),
        ("exposure_denom", ctypes.c_float),
        ("avg_speed_kmh", ctypes.c_float),
        ("elapsed_sec", ctypes.c_double),
        ("activity_progress", ctypes.c_float),
        ("time_display_date", ctypes.c_char * 32),
        ("time_display_time", ctypes.c_char * 32),
        ("time_display_elapsed", ctypes.c_char * 32),
        ("time_display_avg_speed", ctypes.c_char * 32),
        ("speed_str", ctypes.c_char * 32),
        ("hr_str", ctypes.c_char * 32),
        ("cad_str", ctypes.c_char * 32),
        ("power_str", ctypes.c_char * 32),
        ("distance_str", ctypes.c_char * 32),
        ("altitude_str", ctypes.c_char * 32),
        ("solar_str", ctypes.c_char * 32),
        ("garmin_battery_str", ctypes.c_char * 32),
        ("gopro_battery_str", ctypes.c_char * 32),
        ("temp_str", ctypes.c_char * 32),
        ("iso_str", ctypes.c_char * 32),
        ("exposure_str", ctypes.c_char * 32),
        ("map_latitude", ctypes.c_double),
        ("map_longitude", ctypes.c_double),
        ("map_heading_deg", ctypes.c_float),
        ("has_map_heading", ctypes.c_int32),
    ]


class TelemTextStyle(ctypes.Structure):
    _pack_ = 1
    _fields_ = [
        ("font_family", ctypes.c_wchar * 64),
        ("font_size", ctypes.c_float),
        ("text_color", ctypes.c_uint32),
        ("outline_color", ctypes.c_uint32),
        ("outline_width", ctypes.c_float),
        ("label", ctypes.c_wchar * 64),
        ("unit", ctypes.c_wchar * 32),
        ("icon_name", ctypes.c_char * 32),
        ("icon_size", ctypes.c_float),
        ("telemetry_field", ctypes.c_int32),
        ("canvas_x", ctypes.c_float),
        ("canvas_y", ctypes.c_float),
        ("icon_offset_y", ctypes.c_float),
        ("text_offset_y", ctypes.c_float),
    ]


class TelemTimeDisplayStyle(ctypes.Structure):
    _pack_ = 1
    _fields_ = [
        ("font_family", ctypes.c_wchar * 64),
        ("global_font_size", ctypes.c_float),
        ("outline_width", ctypes.c_float),
        ("show_date", ctypes.c_int32),
        ("show_time", ctypes.c_int32),
        ("show_elapsed", ctypes.c_int32),
        ("show_avg_speed", ctypes.c_int32),
        ("date_label", ctypes.c_wchar * 32),
        ("time_label", ctypes.c_wchar * 32),
        ("elapsed_label", ctypes.c_wchar * 32),
        ("avg_speed_label", ctypes.c_wchar * 32),
        ("date_color", ctypes.c_uint32),
        ("time_color", ctypes.c_uint32),
        ("elapsed_color", ctypes.c_uint32),
        ("avg_speed_color", ctypes.c_uint32),
        ("date_font_size", ctypes.c_float),
        ("time_font_size", ctypes.c_float),
        ("elapsed_font_size", ctypes.c_float),
        ("avg_speed_font_size", ctypes.c_float),
        ("icon_name", ctypes.c_char * 32),
        ("icon_size", ctypes.c_float),
        ("canvas_x", ctypes.c_float),
        ("canvas_y", ctypes.c_float),
        ("line_spacing", ctypes.c_float),
    ]


class TelemBarStyle(ctypes.Structure):
    _pack_ = 1
    _fields_ = [
        ("font_family", ctypes.c_wchar * 64),
        ("title_font_size", ctypes.c_float),
        ("range_font_size", ctypes.c_float),
        ("value_font_size", ctypes.c_float),
        ("outline_width", ctypes.c_float),
        ("title", ctypes.c_wchar * 64),
        ("unit", ctypes.c_wchar * 32),
        ("show_label", ctypes.c_int32),
        ("show_range", ctypes.c_int32),
        ("show_value", ctypes.c_int32),
        ("show_mid", ctypes.c_int32),
        ("show_tick_labels", ctypes.c_int32),
        ("range_units", ctypes.c_int32),
        ("major_divisions", ctypes.c_int32),
        ("minor_per_major", ctypes.c_int32),
        ("major_step", ctypes.c_float),
        ("min_val", ctypes.c_float),
        ("max_val", ctypes.c_float),
        ("track_color", ctypes.c_uint32),
        ("tick_color", ctypes.c_uint32),
        ("text_color", ctypes.c_uint32),
        ("dim_text_color", ctypes.c_uint32),
        ("marker_color", ctypes.c_uint32),
        ("marker_border_color", ctypes.c_uint32),
        ("track_width", ctypes.c_float),
        ("major_len", ctypes.c_float),
        ("minor_len", ctypes.c_float),
        ("marker_size", ctypes.c_float),
        ("marker_style", ctypes.c_int32),
        ("telemetry_field", ctypes.c_int32),
        ("track_canvas_x", ctypes.c_float),
        ("track_canvas_y", ctypes.c_float),
        ("track_len", ctypes.c_float),
        ("title_canvas_x", ctypes.c_float),
        ("title_canvas_y", ctypes.c_float),
        ("range_canvas_y", ctypes.c_float),
        ("value_canvas_y", ctypes.c_float),
        ("value_offset_x", ctypes.c_float),
        ("value_offset_y", ctypes.c_float),
    ]


class TelemSegmentBarStyle(ctypes.Structure):
    _pack_ = 1
    _fields_ = [
        ("font_family", ctypes.c_wchar * 64),
        ("label_font_size", ctypes.c_float),
        ("value_font_size", ctypes.c_float),
        ("range_font_size", ctypes.c_float),
        ("outline_width", ctypes.c_float),
        ("label", ctypes.c_wchar * 64),
        ("unit", ctypes.c_wchar * 32),
        ("segments", ctypes.c_int32),
        ("gap", ctypes.c_float),
        ("radius", ctypes.c_float),
        ("min_val", ctypes.c_float),
        ("max_val", ctypes.c_float),
        ("active_color", ctypes.c_uint32),
        ("inactive_color", ctypes.c_uint32),
        ("text_color", ctypes.c_uint32),
        ("dim_color", ctypes.c_uint32),
        ("grow_height", ctypes.c_int32),
        ("grow_start", ctypes.c_float),
        ("telemetry_field", ctypes.c_int32),
        ("active_color_start", ctypes.c_uint32),
        ("active_color_end", ctypes.c_uint32),
        ("seg_canvas_x", ctypes.c_float),
        ("seg_canvas_y", ctypes.c_float),
        ("seg_width", ctypes.c_float),
        ("seg_height", ctypes.c_float),
        ("value_canvas_x", ctypes.c_float),
        ("value_canvas_y", ctypes.c_float),
        ("label_canvas_x", ctypes.c_float),
        ("label_canvas_y", ctypes.c_float),
    ]


class TelemGaugeStyle(ctypes.Structure):
    _pack_ = 1
    _fields_ = [
        ("font_family", ctypes.c_wchar * 64),
        ("gauge_font_size", ctypes.c_float),
        ("value_font_size", ctypes.c_float),
        ("unit_font_size", ctypes.c_float),
        ("outline_width", ctypes.c_float),
        ("unit", ctypes.c_wchar * 32),
        ("min_val", ctypes.c_float),
        ("max_val", ctypes.c_float),
        ("start_deg", ctypes.c_float),
        ("sweep_deg", ctypes.c_float),
        ("ticks", ctypes.c_int32),
        ("step_val", ctypes.c_float),
        ("major_intervals", ctypes.c_int32),
        ("sub_ticks_count", ctypes.c_int32),
        ("needle_color", ctypes.c_uint32),
        ("needle_length", ctypes.c_float),
        ("needle_width", ctypes.c_float),
        ("tick_color", ctypes.c_uint32),
        ("text_color", ctypes.c_uint32),
        ("telemetry_field", ctypes.c_int32),
    ]


class TelemChartStyle(ctypes.Structure):
    _pack_ = 1
    _fields_ = [
        ("font_family", ctypes.c_wchar * 64),
        ("header_font_size", ctypes.c_float),
        ("axis_font_size", ctypes.c_float),
        ("value_font_size", ctypes.c_float),
        ("outline_width", ctypes.c_float),
        ("label", ctypes.c_wchar * 64),
        ("unit", ctypes.c_wchar * 32),
        ("min_val", ctypes.c_float),
        ("max_val", ctypes.c_float),
        ("line_color", ctypes.c_uint32),
        ("fill_color", ctypes.c_uint32),
        ("fill_alpha", ctypes.c_float),
        ("grid_color", ctypes.c_uint32),
        ("text_color", ctypes.c_uint32),
        ("show_grid", ctypes.c_int32),
        ("show_x_axis", ctypes.c_int32),
        ("show_y_axis", ctypes.c_int32),
        ("label_count", ctypes.c_int32),
        ("telemetry_field", ctypes.c_int32),
        ("plot_canvas_x1", ctypes.c_float),
        ("plot_canvas_y1", ctypes.c_float),
        ("plot_canvas_x2", ctypes.c_float),
        ("plot_canvas_y2", ctypes.c_float),
        ("header_canvas_x", ctypes.c_float),
        ("header_canvas_y", ctypes.c_float),
        ("value_canvas_x", ctypes.c_float),
        ("value_canvas_y", ctypes.c_float),
    ]


class TelemMapStyle(ctypes.Structure):
    _pack_ = 1
    _fields_ = [
        ("font_family", ctypes.c_wchar * 64),
        ("canvas_x", ctypes.c_float),
        ("canvas_y", ctypes.c_float),
        ("width", ctypes.c_float),
        ("height", ctypes.c_float),
        ("zoom", ctypes.c_int32),
        ("rotate_map", ctypes.c_int32),
        ("alpha", ctypes.c_float),
        ("track_width", ctypes.c_float),
        ("track_color", ctypes.c_uint32),
        ("marker_radius", ctypes.c_float),
        ("marker_color", ctypes.c_uint32),
        ("marker_border_color", ctypes.c_uint32),
        ("border_color", ctypes.c_uint32),
        ("border_width", ctypes.c_float),
        ("corner_radius", ctypes.c_float),
        ("marker_style", ctypes.c_int32),
    ]


class TelemIndicatorStyle(ctypes.Union):
    _pack_ = 1
    _fields_ = [
        ("text", TelemTextStyle),
        ("time_display", TelemTimeDisplayStyle),
        ("bar", TelemBarStyle),
        ("segment_bar", TelemSegmentBarStyle),
        ("gauge", TelemGaugeStyle),
        ("chart", TelemChartStyle),
        ("map", TelemMapStyle),
    ]


class TelemIndicatorDesc(ctypes.Structure):
    _pack_ = 1
    _fields_ = [
        ("type", ctypes.c_int32),
        ("key", ctypes.c_char * 64),
        ("x", ctypes.c_float),
        ("y", ctypes.c_float),
        ("width", ctypes.c_float),
        ("height", ctypes.c_float),
        ("rotation", ctypes.c_float),
        ("alpha", ctypes.c_float),
        ("z_order", ctypes.c_int32),
        ("style", TelemIndicatorStyle),
    ]


class TelemEncoderConfig(ctypes.Structure):
    _pack_ = 1
    _fields_ = [
        ("codec", ctypes.c_uint32),
        ("quality_mode", ctypes.c_uint32),
        ("bit_depth", ctypes.c_uint32),
        ("bitrate_bps", ctypes.c_uint32),
        ("max_bitrate_bps", ctypes.c_uint32),
        ("vbv_size_bits", ctypes.c_uint32),
        ("gop_length", ctypes.c_uint32),
        ("b_frames", ctypes.c_uint32),
        ("multipass", ctypes.c_uint32),
        ("enable_lookahead", ctypes.c_uint32),
        ("lookahead_depth", ctypes.c_uint32),
        ("enable_aq", ctypes.c_uint32),
        ("aq_strength", ctypes.c_uint32),
        ("enable_temporal_aq", ctypes.c_uint32),
        ("enable_compression_analysis", ctypes.c_uint32),
        ("compression_csv_path", ctypes.c_wchar * 512),
    ]


class TelemNvencConfig(ctypes.Structure):
    _pack_ = 1
    _fields_ = [
        ("width", ctypes.c_uint32),
        ("height", ctypes.c_uint32),
        ("fps_num", ctypes.c_uint32),
        ("fps_den", ctypes.c_uint32),
        ("ring_size", ctypes.c_uint32),
        ("bit_depth", ctypes.c_uint32),
        ("preset_p1_to_p7", ctypes.c_uint32),
        ("tuning_info", ctypes.c_uint32),
        ("async_nvenc", ctypes.c_int32),
        ("enable_debug_layer", ctypes.c_int32),
        ("encoder_config", TelemEncoderConfig),
    ]


class TelemProgressInfo(ctypes.Structure):
    _pack_ = 1
    _fields_ = [
        ("completed_frames", ctypes.c_uint32),
        ("total_frames", ctypes.c_uint32),
        ("elapsed_sec", ctypes.c_double),
        ("current_fps", ctypes.c_double),
        ("is_active", ctypes.c_int32),
        ("is_cancelled", ctypes.c_int32),
        ("is_finished", ctypes.c_int32),
        ("error_code", ctypes.c_int32),
        ("error_message", ctypes.c_char * 256),
    ]


class TelemPipelineStats(ctypes.Structure):
    _pack_ = 1
    _fields_ = [
        ("completed_frames", ctypes.c_uint32),
        ("wall_time_sec", ctypes.c_double),
        ("throughput_fps", ctypes.c_double),
        ("total_bitstream_bytes", ctypes.c_uint64),
        ("bitrate_mbps", ctypes.c_double),
        ("avg_latency_ms", ctypes.c_double),
        ("median_latency_ms", ctypes.c_double),
        ("p95_latency_ms", ctypes.c_double),
        ("p99_latency_ms", ctypes.c_double),
        ("max_latency_ms", ctypes.c_double),
        ("decode_acquire_ms", ctypes.c_double),
        ("telemetry_lookup_ms", ctypes.c_double),
        ("hud_d2d_ms", ctypes.c_double),
        ("vp_composite_ms", ctypes.c_double),
        ("nvenc_submit_ms", ctypes.c_double),
        ("bitstream_handling_ms", ctypes.c_double),
        ("ram_start_bytes", ctypes.c_uint64),
        ("ram_peak_bytes", ctypes.c_uint64),
        ("ram_end_bytes", ctypes.c_uint64),
        ("vram_budget_bytes", ctypes.c_uint64),
        ("vram_usage_bytes", ctypes.c_uint64),
        ("clip_switch_ms", ctypes.c_double),
    ]


class TelemMapCacheStats(ctypes.Structure):
    _pack_ = 1
    _fields_ = [
        ("total_tiles", ctypes.c_uint32),
        ("decoded_tiles", ctypes.c_uint32),
        ("cache_hits", ctypes.c_uint32),
        ("cache_misses", ctypes.c_uint32),
        ("vram_bytes", ctypes.c_uint64),
        ("peak_vram_bytes", ctypes.c_uint64),
    ]


class TelemCompressionStats(ctypes.Structure):
    _pack_ = 1
    _fields_ = [
        ("is_active", ctypes.c_uint32),
        ("is_av1", ctypes.c_uint32),
        ("frames_analyzed", ctypes.c_uint32),
        ("current_qp", ctypes.c_uint32),
        ("current_frame_type", ctypes.c_char),
        ("current_bitrate_mbps", ctypes.c_double),
        ("mean_qp", ctypes.c_double),
        ("median_qp", ctypes.c_double),
        ("p10_qp", ctypes.c_double),
        ("p50_qp", ctypes.c_double),
        ("p90_qp", ctypes.c_double),
        ("p95_qp", ctypes.c_double),
        ("min_qp", ctypes.c_uint32),
        ("max_qp", ctypes.c_uint32),
        ("i_frame_count", ctypes.c_uint32),
        ("p_frame_count", ctypes.c_uint32),
        ("b_frame_count", ctypes.c_uint32),
        ("i_frame_mean_qp", ctypes.c_double),
        ("p_frame_mean_qp", ctypes.c_double),
        ("b_frame_mean_qp", ctypes.c_double),
        ("total_encoded_bytes", ctypes.c_uint64),
        ("mean_bytes_per_frame", ctypes.c_double),
        ("peak_bitrate_mbps", ctypes.c_double),
        ("average_bitrate_mbps", ctypes.c_double),
        ("qp_histogram", ctypes.c_uint32 * 256),
    ]


_LOADED_DLL: Optional[ctypes.CDLL] = None


def load_native_pipeline(dll_path: Optional[Path] = None) -> ctypes.CDLL:
    """Load and bind telem_nvenc_native.dll with full signature definitions."""
    global _LOADED_DLL

    target = dll_path or get_native_dll_path()
    if not target.exists():
        raise FileNotFoundError(f"telem_nvenc_native.dll not found at: {target}")

    target_resolved = str(target.resolve())
    if _LOADED_DLL is not None:
        if getattr(_LOADED_DLL, "_target_path", None) == target_resolved:
            return _LOADED_DLL

    base_dir = Path(__file__).resolve().parent.parent.parent
    bin_dir = base_dir / "native" / "d3d11_nvenc_pipeline" / "bin"
    if bin_dir.exists() and hasattr(os, "add_dll_directory"):
        try:
            os.add_dll_directory(str(bin_dir.resolve()))
        except Exception:
            pass
    if target.parent.exists() and hasattr(os, "add_dll_directory"):
        try:
            os.add_dll_directory(str(target.parent.resolve()))
        except Exception:
            pass

    dll = ctypes.CDLL(target_resolved)
    dll._target_path = target_resolved

    # Lifecycle & Configuration
    dll.telem_nvenc_create.restype = ctypes.c_void_p
    dll.telem_nvenc_create.argtypes = []

    dll.telem_nvenc_configure.restype = ctypes.c_int
    dll.telem_nvenc_configure.argtypes = [ctypes.c_void_p, ctypes.POINTER(TelemNvencConfig)]

    dll.telem_nvenc_open_video.restype = ctypes.c_int
    dll.telem_nvenc_open_video.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p]

    dll.telem_nvenc_set_video_sequence.restype = ctypes.c_int
    dll.telem_nvenc_set_video_sequence.argtypes = [ctypes.c_void_p, ctypes.POINTER(TelemVideoClipDesc), ctypes.c_uint32]

    dll.telem_nvenc_set_telemetry.restype = ctypes.c_int
    dll.telem_nvenc_set_telemetry.argtypes = [ctypes.c_void_p, ctypes.POINTER(TelemFrameState), ctypes.c_uint32]

    dll.telem_nvenc_set_indicators.restype = ctypes.c_int
    dll.telem_nvenc_set_indicators.argtypes = [ctypes.c_void_p, ctypes.POINTER(TelemIndicatorDesc), ctypes.c_uint32]

    dll.telem_nvenc_set_chart_samples.restype = ctypes.c_int
    dll.telem_nvenc_set_chart_samples.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.POINTER(ctypes.c_float), ctypes.c_uint32]

    dll.telem_nvenc_set_map_route.restype = ctypes.c_int
    dll.telem_nvenc_set_map_route.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_double), ctypes.POINTER(ctypes.c_double), ctypes.c_uint32]

    dll.telem_nvenc_preload_map_tile.restype = ctypes.c_int
    dll.telem_nvenc_preload_map_tile.argtypes = [ctypes.c_void_p, ctypes.c_int32, ctypes.c_int32, ctypes.c_int32, ctypes.c_void_p, ctypes.c_uint32]

    # Visual Parity & Fast Memory Readback
    dll.telem_nvenc_render_hud_frame_to_file.restype = ctypes.c_int
    dll.telem_nvenc_render_hud_frame_to_file.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_wchar_p]

    dll.telem_nvenc_render_hud_frame_to_buffer.restype = ctypes.c_int
    dll.telem_nvenc_render_hud_frame_to_buffer.argtypes = [
        ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p, ctypes.c_uint32,
        ctypes.POINTER(ctypes.c_uint32), ctypes.POINTER(ctypes.c_uint32), ctypes.POINTER(ctypes.c_uint32)
    ]

    # Execution & Control
    dll.telem_nvenc_start_export.restype = ctypes.c_int
    dll.telem_nvenc_start_export.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_int]

    dll.telem_nvenc_cancel.restype = None
    dll.telem_nvenc_cancel.argtypes = [ctypes.c_void_p]

    dll.telem_nvenc_wait_completion.restype = ctypes.c_int
    dll.telem_nvenc_wait_completion.argtypes = [ctypes.c_void_p, ctypes.c_uint32]

    # Monitoring & Stats
    dll.telem_nvenc_get_progress.restype = None
    dll.telem_nvenc_get_progress.argtypes = [ctypes.c_void_p, ctypes.POINTER(TelemProgressInfo)]

    dll.telem_nvenc_get_stats.restype = None
    dll.telem_nvenc_get_stats.argtypes = [ctypes.c_void_p, ctypes.POINTER(TelemPipelineStats)]

    dll.telem_nvenc_get_map_cache_stats.restype = None
    dll.telem_nvenc_get_map_cache_stats.argtypes = [ctypes.c_void_p, ctypes.POINTER(TelemMapCacheStats)]

    dll.telem_nvenc_get_compression_stats.restype = None
    dll.telem_nvenc_get_compression_stats.argtypes = [ctypes.c_void_p, ctypes.POINTER(TelemCompressionStats)]

    dll.telem_nvenc_export_compression_csv.restype = ctypes.c_int
    dll.telem_nvenc_export_compression_csv.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p]

    # Live Render Preview Tap (Stage 8L.4)
    dll.telem_nvenc_set_preview_tap.restype = ctypes.c_int
    dll.telem_nvenc_set_preview_tap.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_double]

    dll.telem_nvenc_poll_preview_frame.restype = ctypes.c_int
    dll.telem_nvenc_poll_preview_frame.argtypes = [
        ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint32,
        ctypes.POINTER(ctypes.c_uint32), ctypes.POINTER(ctypes.c_uint32),
        ctypes.POINTER(ctypes.c_uint32), ctypes.POINTER(ctypes.c_double)
    ]

    # Cleanup
    dll.telem_nvenc_close_video.restype = None
    dll.telem_nvenc_close_video.argtypes = [ctypes.c_void_p]

    dll.telem_nvenc_destroy.restype = None
    dll.telem_nvenc_destroy.argtypes = [ctypes.c_void_p]

    _LOADED_DLL = dll
    return dll
