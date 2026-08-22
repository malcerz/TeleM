"""Offline ETAP 8G IMU lean prototype.

This file is intentionally outside the normal TeleM runtime.  It reads the
existing GPMF extractors, performs causal experiments, writes one diagnostic
plot and prints JSON metrics for the stage report.  It must not be imported by
the telemetry resolver, frame data, GUI or renderer.
"""

from __future__ import annotations

import json
import math
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.telemetry_extract import (
    ensure_records_list,
    extract_accelerometer_samples,
    extract_gps_track,
    extract_gyroscope_samples,
    extract_speed_samples,
    flatten_record,
    load_json_with_fallback,
)
from src.telemetry_heading import derive_heading_samples


JSON_PATH = ROOT / "Video" / "GX030120.json"
PLOT_PATH = ROOT / "Raporty" / "ETAP8G_LEAN_IMU_DIAGNOSTIC.png"
METRICS_PATH = ROOT / "scratch" / "etap8g_metrics.json"
G = 9.80665


def elapsed(samples: list[tuple], origin) -> np.ndarray:
    return np.asarray([(dt - origin).total_seconds() for dt, _ in samples], dtype=float)


def moving_mean(values: np.ndarray, width: int) -> np.ndarray:
    width = max(1, int(width))
    if width == 1:
        return values.copy()
    kernel = np.ones(width, dtype=float) / width
    return np.convolve(values, kernel, mode="same")


def circular_mean_deg(values: np.ndarray) -> float:
    radians = np.radians(values)
    return float(np.degrees(np.angle(np.mean(np.exp(1j * radians)))))


def wrap_radians(value: float) -> float:
    return math.atan2(math.sin(value), math.cos(value))


def integrate_gyro(t: np.ndarray, rate: np.ndarray) -> np.ndarray:
    result = np.zeros_like(rate, dtype=float)
    if len(rate) > 1:
        result[1:] = np.cumsum(0.5 * (rate[1:] + rate[:-1]) * np.diff(t))
    return np.degrees(result)


def complementary_filter(
    t: np.ndarray,
    gyro_roll: np.ndarray,
    accel_roll: np.ndarray,
    accel_norm: np.ndarray,
    mount_offset_deg: float,
    alpha: float,
    adaptive: bool = False,
) -> tuple[np.ndarray, np.ndarray]:
    """Causal complementary filter with optional norm-based confidence gate."""
    result = np.zeros_like(gyro_roll, dtype=float)
    weights = np.full_like(gyro_roll, alpha, dtype=float)
    accel_zeroed = np.radians(accel_roll - mount_offset_deg)
    result[0] = wrap_radians(float(accel_zeroed[0]))
    for index in range(1, len(result)):
        dt = max(0.0, float(t[index] - t[index - 1]))
        prediction = result[index - 1] + float(gyro_roll[index]) * dt
        effective_alpha = alpha
        if adaptive:
            # Near |a|=g the correction is trusted.  Dynamic acceleration
            # increases alpha, making the filter rely more on gyro prediction.
            deviation = abs(float(accel_norm[index]) - G)
            confidence = math.exp(-((deviation / 1.25) ** 2))
            effective_alpha = alpha + (1.0 - alpha) * (1.0 - confidence) * 0.975
        weights[index] = effective_alpha
        correction = wrap_radians(float(accel_zeroed[index]) - prediction)
        result[index] = prediction + (1.0 - effective_alpha) * correction
    return np.degrees(result), weights


def linear_interp_error(t: np.ndarray, values: np.ndarray, hz: float) -> tuple[float, float]:
    grid = np.arange(t[0], t[-1] + 1e-9, 1.0 / hz)
    sampled = np.interp(grid, t, values)
    reconstructed = np.interp(t, grid, sampled)
    error = reconstructed - values
    return float(np.sqrt(np.mean(error * error))), float(np.max(np.abs(error)))


def _nice_font(size: int):
    try:
        return ImageFont.truetype("arial.ttf", size)
    except Exception:
        return ImageFont.load_default()


def draw_plot(t: np.ndarray, fused: np.ndarray, accel: np.ndarray, gyro_only: np.ndarray) -> None:
    width, height = 1800, 900
    image = Image.new("RGB", (width, height), (18, 22, 29))
    draw = ImageDraw.Draw(image)
    margin = (90, 60, 50, 100)
    left, top = margin[0], margin[1]
    right, bottom = width - margin[2], height - margin[3]
    y_min, y_max = -100.0, 100.0

    def xy(seconds: float, value: float) -> tuple[int, int]:
        x = left + int((seconds - t[0]) / (t[-1] - t[0]) * (right - left))
        y = top + int((y_max - value) / (y_max - y_min) * (bottom - top))
        return x, y

    draw.rectangle((left, top, right, bottom), outline=(100, 110, 125), width=2)
    for value in range(-100, 101, 20):
        y = xy(t[0], value)[1]
        color = (80, 88, 102) if value else (165, 175, 190)
        draw.line((left, y, right, y), fill=color, width=2 if value == 0 else 1)
        draw.text((12, y - 8), f"{value:+d}°", fill=(200, 205, 215), font=_nice_font(18))
    for seconds in range(0, int(t[-1]) + 1, 20):
        x = xy(seconds, y_min)[0]
        draw.line((x, top, x, bottom), fill=(55, 62, 75), width=1)
        draw.text((x - 12, bottom + 12), f"{seconds}s", fill=(190, 195, 205), font=_nice_font(18))

    def line(values: np.ndarray, color: tuple[int, int, int], width_px: int) -> None:
        points = [xy(float(seconds), float(value)) for seconds, value in zip(t[::4], values[::4])]
        draw.line(points, fill=color, width=width_px, joint="curve")

    line(gyro_only, (238, 92, 82), 2)
    line(accel, (81, 166, 255), 2)
    line(fused, (95, 225, 139), 3)
    draw.text((left, 18), "TeleM ETAP 8G — offline IMU lean diagnostic", fill=(245, 247, 250), font=_nice_font(26))
    legend = [("fused CF α=.98", (95, 225, 139)), ("accel estimate", (81, 166, 255)), ("gyro-only", (238, 92, 82))]
    x = left + 700
    for label, color in legend:
        draw.line((x, 32, x + 28, 32), fill=color, width=4)
        draw.text((x + 38, 22), label, fill=(225, 230, 238), font=_nice_font(18))
        x += 220
    image.save(PLOT_PATH)


def main() -> dict:
    parse_started = time.perf_counter()
    records = ensure_records_list(load_json_with_fallback(JSON_PATH))
    accel_samples = extract_accelerometer_samples(records)
    gyro_samples = extract_gyroscope_samples(records)
    gps_track = extract_gps_track(records)
    speed_samples = extract_speed_samples(records)
    parse_ms = (time.perf_counter() - parse_started) * 1000.0

    accel_t = elapsed(accel_samples, accel_samples[0][0])
    gyro_t = elapsed(gyro_samples, gyro_samples[0][0])
    accel = np.asarray([value for _, value in accel_samples], dtype=float)
    gyro = np.asarray([value for _, value in gyro_samples], dtype=float)
    speed_t = elapsed(speed_samples, speed_samples[0][0])
    speed = np.interp(accel_t, speed_t, np.asarray([value for _, value in speed_samples], dtype=float))
    gyro_on_accel = np.column_stack([np.interp(accel_t, gyro_t, gyro[:, axis]) for axis in range(3)])
    accel_norm = np.linalg.norm(accel, axis=1)

    # With the repository's canonical XYZ mapping, X is the candidate roll
    # rotation axis and Y/Z form the gravity plane.  Keep other candidates in
    # the metrics so this remains an experiment, not a production assertion.
    fusion_started = time.perf_counter()
    candidate_angles = {
        "roll_axis_X_atan2_Y_negZ": np.degrees(np.arctan2(accel[:, 1], -accel[:, 2])),
        "roll_axis_Y_atan2_X_negZ": np.degrees(np.arctan2(accel[:, 0], -accel[:, 2])),
        "roll_axis_Z_atan2_X_Y": np.degrees(np.arctan2(accel[:, 0], accel[:, 1])),
    }
    candidate_correlations = {}
    valid_norm = np.abs(accel_norm - G) < 1.0
    for key, angle in candidate_angles.items():
        rotation_axis = {"X": 0, "Y": 1, "Z": 2}[key.split("_")[2]]
        derivative = np.gradient(np.unwrap(np.radians(angle)), accel_t)
        candidate_correlations[key] = float(np.corrcoef(derivative[valid_norm], gyro_on_accel[valid_norm, rotation_axis])[0, 1])

    gyro_roll = gyro_on_accel[:, 0]
    accel_roll = candidate_angles["roll_axis_X_atan2_Y_negZ"]

    # GPS heading is diagnostic context only.  It is never an input to the
    # lean estimate or to the complementary filter.
    gps_naive = [(dt.replace(tzinfo=None) if dt.tzinfo else dt, lat, lon) for dt, lat, lon in gps_track]
    speed_naive = [(dt.replace(tzinfo=None) if dt.tzinfo else dt, value) for dt, value in speed_samples]
    gps_heading_samples = derive_heading_samples(
        gps_naive, speed_naive, min_distance_m=5.0, smoothing_window_s=2.0
    )
    gps_heading_t = elapsed(gps_heading_samples, gps_heading_samples[0][0])
    gps_heading = np.asarray([value if value is not None else np.nan for _, value in gps_heading_samples], dtype=float)
    finite_heading = np.isfinite(gps_heading)
    heading_on_imu = np.interp(
        accel_t,
        gps_heading_t[finite_heading],
        gps_heading[finite_heading],
    )
    smooth_abs_rate = moving_mean(np.abs(gyro_roll), max(1, round(1.0 / np.median(np.diff(accel_t)))))
    mount_mask = (speed > 8.0) & (smooth_abs_rate < 0.08) & (np.abs(accel_norm - G) < 1.0)
    mount_offset = circular_mean_deg(accel_roll[mount_mask]) if np.any(mount_mask) else 0.0

    gyro_angles = integrate_gyro(accel_t, gyro_roll)
    filters: dict[str, np.ndarray] = {}
    weights: dict[str, np.ndarray] = {}
    for alpha in (0.95, 0.98, 0.995):
        filters[f"cf_{alpha:.3f}"] , weights[f"cf_{alpha:.3f}"] = complementary_filter(
            accel_t, gyro_roll, accel_roll, accel_norm, mount_offset, alpha
        )
    adaptive, adaptive_weights = complementary_filter(
        accel_t, gyro_roll, accel_roll, accel_norm, mount_offset, 0.98, adaptive=True
    )
    filters["adaptive_cf_0.98"] = adaptive
    weights["adaptive_cf_0.98"] = adaptive_weights

    # Chosen representative windows are based on the observed gyro-X events:
    # one straight, two directionally different turns, and the low-speed stop.
    windows = {"straight": (125.0, 140.0), "turn_1": (64.0, 72.0), "turn_2": (145.0, 155.0), "low_speed": (38.0, 48.0)}
    chosen = filters["cf_0.980"]
    window_metrics = {}
    for name, (start, end) in windows.items():
        mask = (accel_t >= start) & (accel_t < end)
        peak_index = np.argmax(np.abs(chosen[mask]))
        local_indices = np.flatnonzero(mask)
        peak_global = int(local_indices[peak_index])
        rate_index = int(local_indices[np.argmax(np.abs(gyro_roll[mask]))])
        window_metrics[name] = {
            "start_s": start,
            "end_s": end,
            "speed_median_kmh": float(np.median(speed[mask])),
            "fused_min_deg": float(np.min(chosen[mask])),
            "fused_max_deg": float(np.max(chosen[mask])),
            "fused_peak_abs_deg": float(np.max(np.abs(chosen[mask]))),
            "accel_min_deg": float(np.min(accel_roll[mask] - mount_offset)),
            "accel_max_deg": float(np.max(accel_roll[mask] - mount_offset)),
            "gyro_rate_peak_rad_s": float(gyro_roll[rate_index]),
            "gyro_peak_s": float(accel_t[rate_index]),
            "fused_peak_s": float(accel_t[peak_global]),
            "peak_lag_s": float(accel_t[peak_global] - accel_t[rate_index]),
            "fused_drift_deg_per_s": float(np.polyfit(accel_t[mask], chosen[mask], 1)[0]),
        }

    fusion_ms = (time.perf_counter() - fusion_started) * 1000.0
    downsample_started = time.perf_counter()
    downsample = {}
    for hz in (20, 10):
        rmse, max_error = linear_interp_error(accel_t, chosen, hz)
        downsample[str(hz)] = {"rmse_deg": rmse, "max_error_deg": max_error}
    downsample_ms = (time.perf_counter() - downsample_started) * 1000.0
    gps_context = {}
    for name, (start, end) in windows.items():
        if name not in ("turn_1", "turn_2"):
            continue
        start_heading = float(np.interp(start, accel_t, heading_on_imu))
        end_heading = float(np.interp(end, accel_t, heading_on_imu))
        heading_delta = ((end_heading - start_heading + 180.0) % 360.0) - 180.0
        center = (start + end) / 2.0
        center_index = int(np.argmin(np.abs(accel_t - center)))
        gps_context[name] = {
            "start_heading_deg": start_heading,
            "end_heading_deg": end_heading,
            "heading_change_deg": heading_delta,
            "center_time_s": float(accel_t[center_index]),
            "center_speed_kmh": float(speed[center_index]),
            "center_gyro_roll_rate_rad_s": float(gyro_roll[center_index]),
            "center_accel_estimate_deg": float(accel_roll[center_index] - mount_offset),
            "center_fused_lean_deg": float(chosen[center_index]),
        }
    gyro_drift = {}
    for axis in range(3):
        angle = integrate_gyro(gyro_t, gyro[:, axis])
        gyro_drift[str(axis)] = {
            "range_deg": [float(np.min(angle)), float(np.max(angle))],
            "at_30_s_deg": float(np.interp(30.0, gyro_t, angle)),
            "at_60_s_deg": float(np.interp(60.0, gyro_t, angle)),
            "at_clip_end_deg": float(angle[-1]),
        }

    # Plot a short circular mean of ACCL only for readability.  The filter
    # itself above consumes the causal raw estimate; this visual smoothing is
    # not part of the experimental filter semantics.
    accel_plot_rad = np.arctan2(
        moving_mean(np.sin(np.radians(accel_roll)), max(1, round(0.5 / np.median(np.diff(accel_t))))),
        moving_mean(np.cos(np.radians(accel_roll)), max(1, round(0.5 / np.median(np.diff(accel_t))))),
    )
    accel_plot = np.degrees(accel_plot_rad) - mount_offset
    draw_plot(accel_t, chosen, accel_plot, gyro_angles)
    metrics = {
        "source": str(JSON_PATH.relative_to(ROOT)),
        "counts": {"accel": len(accel_samples), "gyro": len(gyro_samples), "gps": len(gps_track)},
        "timing": {
            "duration_s": float(accel_t[-1]),
            "accel_median_dt_s": float(np.median(np.diff(accel_t))),
            "gyro_median_dt_s": float(np.median(np.diff(gyro_t))),
            "accel_hz": float(1.0 / np.median(np.diff(accel_t))),
            "gyro_hz": float(1.0 / np.median(np.diff(gyro_t))),
        },
        "units": {"accel_metadata": "m/s", "gyro_metadata": "rad/s", "accel_physical_interpretation": "m/s^2 (norm near g)"},
        "axis_mapping": {"raw_order": "ZXY", "canonical_X": "raw[1]", "canonical_Y": "raw[2]", "canonical_Z": "raw[0]", "roll_candidate": "X"},
        "accel_norm_stats": {"median": float(np.median(accel_norm)), "p10": float(np.quantile(accel_norm, 0.1)), "p90": float(np.quantile(accel_norm, 0.9))},
        "candidate_correlations": candidate_correlations,
        "mount_offset_deg": float(mount_offset),
        "gyro_only": gyro_drift,
        "filters": {key: {"mean_alpha": float(np.mean(weights[key])), "straight_drift_deg_per_s": window_metrics["straight"]["fused_drift_deg_per_s"] if key == "cf_0.980" else float(np.polyfit(accel_t[(accel_t >= windows["straight"][0]) & (accel_t < windows["straight"][1])], values[(accel_t >= windows["straight"][0]) & (accel_t < windows["straight"][1])], 1)[0])} for key, (values, _) in {**{key: (value, weights[key]) for key, value in filters.items()}}.items()},
        "adaptive_comparison": {
            "mean_alpha": float(np.mean(adaptive_weights)),
            "rmse_vs_fixed_cf_0.98_deg": float(np.sqrt(np.mean((adaptive - filters["cf_0.980"]) ** 2))),
            "straight_drift_deg_per_s": float(np.polyfit(accel_t[(accel_t >= windows["straight"][0]) & (accel_t < windows["straight"][1])], adaptive[(accel_t >= windows["straight"][0]) & (accel_t < windows["straight"][1])], 1)[0]),
        },
        "windows": window_metrics,
        "gps_heading_context": gps_context,
        "downsample": downsample,
        "performance": {"parse_existing_samples_ms": parse_ms, "core_fusion_ms": fusion_ms, "downsample_20_10_ms": downsample_ms},
        "plot": str(PLOT_PATH.relative_to(ROOT)),
    }
    METRICS_PATH.write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    print(json.dumps(metrics, indent=2))
    return metrics


if __name__ == "__main__":
    main()
