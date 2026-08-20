"""Frame rendering jobs for FFmpeg pipelines (running in process pool worker contexts).
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

from PIL import Image

from src.overlay_renderer import compose_overlay
from src.telemetry_extract import (
    interpolate_speed,
    interpolate_distance,
    interpolate_altitude,
    interpolate_iso,
    interpolate_exposure,
    interpolate_temperature,
)
from src.ffmpeg.worker_cache import WORKER_CACHE, _resolve_cache_value


def render_overlay_frame(
    index: int,
    start_dt_utc: Optional[datetime],
    tz_offset_hours: float,
    speed_samples: list,
    track_samples: list,
    alt_samples: list,
    target_fps: float,
    update_rate_step: int = 1,
) -> Any:
    """Render a single overlay frame – returns PIL Image RGBA. Uses WORKER_CACHE."""
    video_width = WORKER_CACHE["video_width"]
    video_height = WORKER_CACHE["video_height"]

    # ── Wczesny return: klatka w wyciętym fragmencie → pusta nakładka ──
    sample_t = (index * update_rate_step) / target_fps
    current_t = sample_t
    cut_regions = WORKER_CACHE.get("_cut_regions", [])
    for cut_start, cut_end in cut_regions:
        if cut_start <= current_t < cut_end:
            return Image.new("RGBA", (video_width, video_height), (0, 0, 0, 0))

    font_path = WORKER_CACHE["font_path"]
    layout = WORKER_CACHE["layout"]
    iso_samples = WORKER_CACHE.get("iso_samples", [])
    exposure_samples = WORKER_CACHE.get("exposure_samples", [])
    temperature_samples = WORKER_CACHE.get("temperature_samples", [])

    t0 = start_dt_utc
    if t0 is None:
        fallback_lists = [
            speed_samples, track_samples, alt_samples,
            WORKER_CACHE.get("gpx_speed_samples"),
            WORKER_CACHE.get("gpx_track_samples"),
            WORKER_CACHE.get("gpx_alt_samples"),
        ]
        fit_dict = WORKER_CACHE.get("fit_data")
        if fit_dict and isinstance(fit_dict, dict):
            fallback_lists.extend(fit_dict.values())

        for lst in fallback_lists:
            if lst and len(lst) > 0 and lst[0] and len(lst[0]) > 0:
                t0 = lst[0][0]
                break
        if t0 is None:
            from datetime import timezone
            t0 = datetime(1970, 1, 1, tzinfo=timezone.utc)

    # Upewnij się, że t0 to datetime (konwertuj float/int sekundy z epoch na datetime)
    if not isinstance(t0, datetime):
        from datetime import timezone
        try:
            t0 = datetime.fromtimestamp(float(t0), timezone.utc)
        except Exception:
            t0 = datetime(1970, 1, 1, tzinfo=timezone.utc)

    current_dt_utc = t0 + timedelta(seconds=sample_t)

    total_frames = WORKER_CACHE.get("total_overlay_frames", 1)
    chart_data = WORKER_CACHE.get("_precomputed_chart_data", {})

    telemetry_cache = WORKER_CACHE.get("_telemetry_cache")
    if telemetry_cache is not None:
        data = telemetry_cache.lookup(index)
    else:
        from src.overlay_renderer import prepare_overlay_frame_data
        data = prepare_overlay_frame_data(
            layout=layout,
            target_dt=current_dt_utc,
            tz_offset_hours=tz_offset_hours,
            start_dt_utc=start_dt_utc,
            speed_samples=speed_samples,
            track_samples=track_samples,
            alt_samples=alt_samples,
            iso_samples=iso_samples,
            exposure_samples=exposure_samples,
            temperature_samples=temperature_samples,
            gpx_speed_samples=WORKER_CACHE.get("gpx_speed_samples"),
            gpx_track_samples=WORKER_CACHE.get("gpx_track_samples"),
            gpx_alt_samples=WORKER_CACHE.get("gpx_alt_samples"),
            gpx_power_samples=WORKER_CACHE.get("gpx_power_samples"),
            gpx_atemp_samples=WORKER_CACHE.get("gpx_atemp_samples"),
            gpx_hr_samples=WORKER_CACHE.get("gpx_hr_samples"),
            gpx_cad_samples=WORKER_CACHE.get("gpx_cad_samples"),
            fit_data=WORKER_CACHE.get("fit_data"),
            gps_track=WORKER_CACHE.get("gps_track"),
            total_frames=total_frames,
            current_index=index,
            chart_data=chart_data,
            resolve_cache_value=_resolve_cache_value,
            _range_cache=WORKER_CACHE.get("_prep_cache"),
        )

    hud_regions = WORKER_CACHE.get("hud_regions")
    hud_bbox = WORKER_CACHE.get("hud_bbox")

    if hud_regions and len(hud_regions) > 1:
        atlas_w = max(r[2] + r[4] for r in hud_regions)
        atlas_h = max(r[3] + r[5] for r in hud_regions)

        # ── Dirty check: reuse atlas if formatted values unchanged ──
        prev_data = WORKER_CACHE.get("_prev_frame_data")
        prev_atlas = WORKER_CACHE.get("_prev_atlas_img")
        if prev_data is not None and prev_atlas is not None:
            is_dirty = False
            if prev_data.get("date_text") != data.get("date_text") or prev_data.get("time_text") != data.get("time_text"):
                is_dirty = True
            elif int(prev_data.get("elapsed_seconds", 0)) != int(data.get("elapsed_seconds", 0)):
                is_dirty = True
            else:
                # Compare formatted speed/alt/dist to 1 decimal place
                for k in ("speed_value", "distance_m", "alt_value", "iso_value", "exposure_value", "temp_value", "power_value", "hr_value", "cad_value", "battery_value"):
                    v1 = prev_data.get(k)
                    v2 = data.get(k)
                    if v1 is not None and v2 is not None:
                        if round(v1, 1) != round(v2, 1):
                            is_dirty = True
                            break
            if not is_dirty:
                ind_val1 = prev_data.get("indicator_values", {})
                ind_val2 = data.get("indicator_values", {})
                for k, v in ind_val2.items():
                    if round(ind_val1.get(k, -999.0), 1) != round(v, 1):
                        is_dirty = True
                        break

            if not is_dirty:
                return prev_atlas

        img = compose_overlay(
            video_width, video_height, layout, font_path,
            data["date_text"], data["time_text"],
            data["speed_value"], data["distance_m"], data["max_distance_m"],
            data["alt_value"], data["min_alt"], data["max_alt"],
            data["iso_value"], data["exposure_value"], data["temp_value"],
            indicator_values=data["indicator_values"],
            max_speed_kmh=data["max_speed_kmh"],
            power_value=data["power_value"],
            atemp_value=data["atemp_value"],
            hr_value=data["hr_value"],
            cad_value=data["cad_value"],
            battery_value=data["battery_value"],
            chart_data=data["chart_data"],
            current_position=data["current_position"],
            extra_indicators=data["extra_indicators"],
            gps_track=data["gps_track"],
            target_dt=data["target_dt"],
            start_dt_utc=data["start_dt_utc"],
            elapsed_seconds=data["elapsed_seconds"],
            avg_speed_kmh=data["avg_speed_kmh"],
        )

        atlas_img = Image.new("RGBA", (atlas_w, atlas_h), (0, 0, 0, 0))
        rot180 = WORKER_CACHE.get("hud_rotate_180", False)
        for r in hud_regions:
            dest_x, dest_y, atlas_x, atlas_y, rw, rh = r
            r_crop = img.crop((dest_x, dest_y, dest_x + rw, dest_y + rh))
            if rot180:
                r_crop = r_crop.transpose(Image.Transpose.ROTATE_180)
            atlas_img.paste(r_crop, (atlas_x, atlas_y))

        WORKER_CACHE["_prev_frame_data"] = data
        WORKER_CACHE["_prev_atlas_img"] = atlas_img
        return atlas_img
    else:
        img = compose_overlay(
            video_width, video_height, layout, font_path,
            data["date_text"], data["time_text"],
            data["speed_value"], data["distance_m"], data["max_distance_m"],
            data["alt_value"], data["min_alt"], data["max_alt"],
            data["iso_value"], data["exposure_value"], data["temp_value"],
            indicator_values=data["indicator_values"],
            max_speed_kmh=data["max_speed_kmh"],
            power_value=data["power_value"],
            atemp_value=data["atemp_value"],
            hr_value=data["hr_value"],
            cad_value=data["cad_value"],
            battery_value=data["battery_value"],
            chart_data=data["chart_data"],
            current_position=data["current_position"],
            extra_indicators=data["extra_indicators"],
            gps_track=data["gps_track"],
            target_dt=data["target_dt"],
            start_dt_utc=data["start_dt_utc"],
            elapsed_seconds=data["elapsed_seconds"],
            avg_speed_kmh=data["avg_speed_kmh"],
        )
        if hud_bbox:
            hx, hy, hw, hh = hud_bbox
            img = img.crop((hx, hy, hx + hw, hy + hh))
        # NVIDIA ROT180: rotate the whole final HUD canvas 180 deg (pixel-exact,
        # no resampling) BEFORE handing it to FFmpeg, so that after the output's
        # display-matrix rotation the HUD is displayed in its logical orientation.
        if WORKER_CACHE.get("hud_rotate_180"):
            img = img.transpose(Image.Transpose.ROTATE_180)
        return img


def render_overlay_job(job: tuple) -> int:
    """Render one overlay frame to disk (BMP). Used by ProcessPoolExecutor."""
    if len(job) == 9:
        (index, overlay_dir_text, start_dt_utc, tz_offset_hours,
         speed_samples, track_samples, alt_samples, target_fps, update_rate_step) = job
    else:
        (index, overlay_dir_text, start_dt_utc, tz_offset_hours,
         speed_samples, track_samples, alt_samples, target_fps) = job
        update_rate_step = 1
    overlay_dir = Path(overlay_dir_text)
    video_width = WORKER_CACHE["video_width"]
    video_height = WORKER_CACHE["video_height"]
    font_path = WORKER_CACHE["font_path"]
    layout = WORKER_CACHE["layout"]
    max_distance_m = WORKER_CACHE.get("max_distance_m", 1000.0)
    iso_samples = WORKER_CACHE.get("iso_samples", [])
    exposure_samples = WORKER_CACHE.get("exposure_samples", [])
    temperature_samples = WORKER_CACHE.get("temperature_samples", [])
    sample_t = (index * update_rate_step) / target_fps
    t0 = start_dt_utc if start_dt_utc is not None else speed_samples[0][0]
    current_dt_utc = t0 + timedelta(seconds=sample_t)
    current_dt_local = current_dt_utc + timedelta(hours=tz_offset_hours)

    indicator_values: dict[str, float] = {}
    for ind_key in ("speed_visual", "speed_text", "dist_visual", "dist_text", "alt_visual", "alt_text"):
        ind_cfg = layout["indicators"].get(ind_key, {})
        src = ind_cfg.get("source", "gpmf")
        gpx_spd = WORKER_CACHE.get("gpx_speed_samples", [])
        gpx_trk = WORKER_CACHE.get("gpx_track_samples", [])
        gpx_alt = WORKER_CACHE.get("gpx_alt_samples", [])
        fit_spd = WORKER_CACHE.get("fit_data", {}).get("speed", [])
        fit_trk = WORKER_CACHE.get("fit_data", {}).get("track", [])
        fit_alt = WORKER_CACHE.get("fit_data", {}).get("alt", [])
        if src == "gpx":
            spd_s, trk_s, alt_s = gpx_spd, gpx_trk, gpx_alt
        elif src == "fit":
            spd_s, trk_s, alt_s = fit_spd, fit_trk, fit_alt
        else:
            spd_s, trk_s, alt_s = speed_samples, track_samples, alt_samples
        if ind_key in ("speed_visual", "speed_text"):
            indicator_values[ind_key] = interpolate_speed(spd_s, current_dt_utc)
        elif ind_key in ("dist_visual", "dist_text"):
            indicator_values[ind_key] = interpolate_distance(trk_s, current_dt_utc)
        elif ind_key in ("alt_visual", "alt_text"):
            indicator_values[ind_key] = interpolate_altitude(alt_s, current_dt_utc)

    iso_value = interpolate_iso(iso_samples, current_dt_utc)
    exposure_value = interpolate_exposure(exposure_samples, current_dt_utc)
    temp_value = interpolate_temperature(temperature_samples, current_dt_utc)

    def _source_for(key: str) -> str:
        return layout.get("indicators", {}).get(key, {}).get("source", "gpmf")

    power_value = _resolve_cache_value("power", _source_for("power_text"), current_dt_utc, "power_text")
    atemp_value = _resolve_cache_value("atemp", _source_for("atemp_text"), current_dt_utc, "atemp_text")
    hr_value = _resolve_cache_value("hr", _source_for("hr_text"), current_dt_utc, "hr_text")
    cad_value = _resolve_cache_value("cad", _source_for("cad_text"), current_dt_utc, "cad_text")
    battery_value = _resolve_cache_value("battery", _source_for("battery_text"), current_dt_utc, "battery_text")

    speed_value = indicator_values.get("speed_visual", interpolate_speed(speed_samples, current_dt_utc))
    distance_m = indicator_values.get("dist_visual", interpolate_distance(track_samples, current_dt_utc))
    alt_value = indicator_values.get("alt_visual", interpolate_altitude(alt_samples, current_dt_utc))

    dist_src = layout["indicators"].get("dist_visual", {}).get("source", "gpmf")
    if dist_src == "gpx":
        gpx_trk = WORKER_CACHE.get("gpx_track_samples", [])
        if gpx_trk:
            max_distance_m = gpx_trk[-1][1]
    elif dist_src == "fit":
        fit_trk = WORKER_CACHE.get("fit_data", {}).get("track", [])
        if fit_trk:
            max_distance_m = fit_trk[-1][1]

    max_speed_kmh: Optional[float] = None
    spd_src = layout["indicators"].get("speed_visual", {}).get("source", "gpmf")
    if spd_src == "gpx":
        gpx_spd_w = WORKER_CACHE.get("gpx_speed_samples", [])
        spd_for_range = gpx_spd_w
    elif spd_src == "fit":
        fit_spd_w = WORKER_CACHE.get("fit_data", {}).get("speed", [])
        spd_for_range = fit_spd_w
    else:
        spd_for_range = speed_samples
    if spd_for_range:
        spd_vals = [s for _, s in spd_for_range]
        if spd_vals:
            max_speed_kmh = max(spd_vals)

    min_alt: Optional[float] = None
    max_alt: Optional[float] = None
    alt_src = layout["indicators"].get("alt_visual", {}).get("source", "gpmf")
    if alt_src == "gpx":
        gpx_alt_w = WORKER_CACHE.get("gpx_alt_samples", [])
        alt_for_range = gpx_alt_w
    elif alt_src == "fit":
        fit_alt_w = WORKER_CACHE.get("fit_data", {}).get("alt", [])
        alt_for_range = fit_alt_w
    else:
        alt_for_range = alt_samples
    if alt_for_range:
        alts = [a for _, a in alt_for_range]
        if alts:
            min_alt = min(alts)
            max_alt = max(alts)

    date_text = current_dt_local.strftime("%Y-%m-%d")
    time_text = current_dt_local.strftime("%H:%M:%S")

    total_frames = WORKER_CACHE.get("total_overlay_frames", 1)
    current_position = index / max(1, total_frames - 1) if total_frames > 1 else 0.0
    chart_data = WORKER_CACHE.get("_precomputed_chart_data", {})

    # Build extra indicators – MUST match _render_preview in controller.py
    _HARDCODED_KEYS = {
        "speed_visual", "speed_text", "dist_visual", "dist_text",
        "alt_visual", "alt_text", "iso_text", "exposure_text",
        "temp_text", "power_text", "atemp_text", "hr_text",
        "cad_text", "battery_text", "track_map", "time_block",
    }
    extra_indicators: dict[str, tuple[float, str, str]] = {}
    # 1) FIT fields – resolve real values from telemetry
    for ind_key, ind_cfg in layout.get("indicators", {}).items():
        if ind_key.startswith("fit_") and ind_key.endswith("_text"):
            field_name = ind_key[4:-5]
            fit_val = _resolve_cache_value(field_name, "fit", current_dt_utc, ind_key)
            if fit_val is None:
                fit_val = 0.0
            extra_indicators[ind_key] = (fit_val, ind_cfg.get("unit", ""), ind_cfg.get("label", field_name))
    # 2) All remaining dynamic indicators (non-hardcoded, not already captured)
    for ind_key in list(layout.get("indicators", {}).keys()):
        if ind_key in _HARDCODED_KEYS or ind_key in extra_indicators:
            continue
        ind_cfg = layout["indicators"][ind_key]
        extra_indicators[ind_key] = (0.0, ind_cfg.get("unit", ""), ind_cfg.get("label", ind_key))

    # ── Elapsed time & average speed (for time_display) ───────────────
    _elapsed = 0.0
    if start_dt_utc is not None and current_dt_utc is not None:
        _elapsed = max(0.0, (current_dt_utc - start_dt_utc).total_seconds())
    _avg_spd = 0.0
    if _elapsed > 0 and distance_m > 0:
        _avg_spd = (distance_m / _elapsed) * 3.6

    img = compose_overlay(
        video_width, video_height, layout, font_path, date_text, time_text,
        speed_value, distance_m, max_distance_m, alt_value,
        min_alt, max_alt, iso_value, exposure_value, temp_value,
        indicator_values=indicator_values, max_speed_kmh=max_speed_kmh,
        power_value=power_value, atemp_value=atemp_value,
        hr_value=hr_value, cad_value=cad_value,
        battery_value=battery_value,
        chart_data=chart_data, current_position=current_position,
        extra_indicators=extra_indicators,
        gps_track=WORKER_CACHE.get("gps_track", []),
        target_dt=current_dt_utc,
        start_dt_utc=start_dt_utc,
        elapsed_seconds=_elapsed,
        avg_speed_kmh=_avg_spd,
    )
    rot = WORKER_CACHE.get("effective_rotation", 0) % 360
    if rot == 180:
        img = img.transpose(Image.ROTATE_180)
    elif rot == 90:
        img = img.transpose(Image.ROTATE_270)
    elif rot == 270:
        img = img.transpose(Image.ROTATE_90)
    img.save(overlay_dir / f"overlay_{index:06d}.bmp", format="BMP")
    return index


def render_frame_bytes_job(job: tuple) -> tuple[int, bytes]:
    """Multiprocessing worker: render one overlay frame, return (index, raw_rgba_bytes)."""
    index = job[0]
    start_dt_utc = WORKER_CACHE.get("start_dt_utc")
    tz_offset_hours = WORKER_CACHE.get("tz_offset_hours")
    speed_samples = WORKER_CACHE.get("speed_samples")
    track_samples = WORKER_CACHE.get("track_samples")
    alt_samples = WORKER_CACHE.get("alt_samples")
    target_fps = WORKER_CACHE.get("target_fps")
    update_rate_step = WORKER_CACHE.get("update_rate_step", 1)
    img = render_overlay_frame(
        index, start_dt_utc, tz_offset_hours,
        speed_samples, track_samples, alt_samples,
        target_fps, update_rate_step,
    )
    # Raw RGBA bytes — no PNG encode/decode overhead
    return index, img.tobytes()
