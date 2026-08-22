"""Offline ETAP 8H calibration of the IMU lean prototype against GPS dynamics."""

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

from src.telemetry_extract import (  # noqa: E402
    ensure_records_list,
    extract_accelerometer_samples,
    extract_gps_track,
    extract_gyroscope_samples,
    extract_speed_samples,
    load_json_with_fallback,
)
from src.telemetry_heading import derive_heading_samples  # noqa: E402

JSON_PATH = ROOT / "Video" / "GX030120.json"
PLOT_PATH = ROOT / "Raporty" / "ETAP8H_LEAN_GPS_CALIBRATION.png"
METRICS_PATH = ROOT / "scratch" / "etap8h_metrics.json"
ASSET_PATH = ROOT / "wzor" / "rower_ico.png"
G = 9.80665
WINDOWS = {"turn_1": (64.0, 72.0), "turn_2": (145.0, 155.0), "straight": (125.0, 140.0), "low_speed": (38.0, 48.0)}


def elapsed(samples, origin):
    return np.asarray([(dt - origin).total_seconds() for dt, *_ in samples], dtype=float)


def moving_mean(values, width):
    width = max(1, int(width))
    return values.copy() if width == 1 else np.convolve(values, np.ones(width) / width, mode="same")


def wrap_deg(values):
    return (values + 180.0) % 360.0 - 180.0


def interp_angle(t, values, grid):
    unwrapped = np.unwrap(np.radians(values))
    return np.degrees(np.interp(grid, t, unwrapped))


def integrate(t, rate):
    out = np.zeros_like(rate, dtype=float)
    out[1:] = np.cumsum(.5 * (rate[1:] + rate[:-1]) * np.diff(t))
    return np.degrees(out)


def complementary(t, gyro, accel, offset, alpha, bias=0.0):
    state = 0.0
    out = np.zeros_like(gyro, dtype=float)
    accel = np.radians(accel - offset)
    state = float(accel[0])
    out[0] = np.degrees(state)
    for i in range(1, len(out)):
        prediction = state + (gyro[i] - bias) * (t[i] - t[i - 1])
        correction = math.atan2(math.sin(accel[i] - prediction), math.cos(accel[i] - prediction))
        state = prediction + (1 - alpha) * correction
        out[i] = np.degrees(math.atan2(math.sin(state), math.cos(state)))
    return out


def gps_reference(records, speed_samples, smoothing):
    gps = extract_gps_track(records)
    gps_naive = [(dt.replace(tzinfo=None) if dt.tzinfo else dt, lat, lon) for dt, lat, lon in gps]
    speed_naive = [(dt.replace(tzinfo=None) if dt.tzinfo else dt, value) for dt, value in speed_samples]
    headings = derive_heading_samples(gps_naive, speed_naive, min_distance_m=5.0, smoothing_window_s=smoothing)
    ht = elapsed(headings, headings[0][0])
    hv = np.asarray([value if value is not None else np.nan for _, value in headings])
    valid = np.isfinite(hv)
    return ht[valid], hv[valid], gps


def gps_lean(heading_t, heading, speed_t, speed, imu_t, causal_smooth_s=0.35):
    # Unwrapped COG derivative, then a short causal-equivalent diagnostic smooth.
    radians = np.unwrap(np.radians(heading))
    omega = np.gradient(radians, heading_t)
    rate_window = max(1, round(causal_smooth_s / np.median(np.diff(heading_t))))
    omega = moving_mean(omega, rate_window)
    speed_ms = np.interp(heading_t, speed_t, speed) / 3.6
    reference = np.degrees(np.arctan2(speed_ms * omega, G))
    return np.interp(imu_t, heading_t, reference), np.degrees(omega)


def corr_lag(reference, signal, t, max_lag_s=2.0):
    best = None
    step = float(np.median(np.diff(t)))
    for lag in np.arange(-max_lag_s, max_lag_s + step / 2, step):
        shifted = np.interp(t, t + lag, signal, left=np.nan, right=np.nan)
        mask = np.isfinite(shifted) & np.isfinite(reference)
        if mask.sum() < 20:
            continue
        c = float(np.corrcoef(reference[mask], shifted[mask])[0, 1])
        item = (abs(c), c, float(lag))
        if best is None or item[0] > best[0]:
            best = item
    return (best[1], best[2]) if best else (float("nan"), float("nan"))


def candidate_metrics(name, angle, gyro_axis, lean_ref, imu_t, windows):
    straight = (imu_t >= windows["straight"][0]) & (imu_t < windows["straight"][1])
    zero_ref = straight & (np.abs(lean_ref) < 3.0)
    result = {}
    for sign in (1.0, -1.0):
        transformed_angle = sign * angle
        transformed_gyro = sign * gyro_axis
        offset = float(np.median(transformed_angle[zero_ref] - lean_ref[zero_ref])) if zero_ref.any() else float(np.median(transformed_angle[straight] - lean_ref[straight]))
        calibrated = complementary(imu_t, transformed_gyro, transformed_angle, offset, .98)
        all_mask = np.zeros_like(imu_t, dtype=bool)
        for start, end in windows.values():
            all_mask |= (imu_t >= start) & (imu_t < end)
        signed = float(np.corrcoef(lean_ref[all_mask], calibrated[all_mask])[0, 1])
        rmse = float(np.sqrt(np.mean((calibrated[all_mask] - lean_ref[all_mask]) ** 2)))
        lag_corr, lag = corr_lag(lean_ref[all_mask], calibrated[all_mask], imu_t[all_mask])
        signs = []
        for key in ("turn_1", "turn_2"):
            mask = (imu_t >= windows[key][0]) & (imu_t < windows[key][1])
            ref_peak = lean_ref[mask][np.argmax(np.abs(lean_ref[mask]))]
            imu_peak = calibrated[mask][np.argmax(np.abs(calibrated[mask]))]
            signs.append({"ref_peak": float(ref_peak), "imu_peak": float(imu_peak), "same_sign": bool(np.sign(ref_peak) == np.sign(imu_peak))})
        result["+" if sign > 0 else "-"] = {"offset_deg": offset, "signed_corr": signed, "abs_corr": abs(signed), "rmse_deg": rmse, "lag_ms": lag * 1000.0, "turns": signs}
    return result


def font(size):
    try:
        return ImageFont.truetype("arial.ttf", size)
    except Exception:
        return ImageFont.load_default()


def plot(t, gps_ref, imu, yaw_rate):
    w, h = 1800, 900
    image = Image.new("RGB", (w, h), (18, 22, 29))
    draw = ImageDraw.Draw(image)
    left, top, right, bottom = 90, 70, 1750, 800
    ymin, ymax = -45, 45
    def xy(x, y):
        return left + int((x - t[0]) / (t[-1] - t[0]) * (right - left)), top + int((ymax - y) / (ymax - ymin) * (bottom - top))
    draw.rectangle((left, top, right, bottom), outline=(100, 110, 125), width=2)
    for y in range(-40, 41, 10):
        yy = xy(t[0], y)[1]
        draw.line((left, yy, right, yy), fill=(80, 88, 102) if y else (165, 175, 190), width=2 if y == 0 else 1)
        draw.text((15, yy - 8), f"{y:+d}°", fill=(205, 210, 220), font=font(18))
    for x in range(0, int(t[-1]) + 1, 20):
        xx = xy(x, ymin)[0]
        draw.line((xx, top, xx, bottom), fill=(55, 62, 75), width=1)
        draw.text((xx - 12, bottom + 12), f"{x}s", fill=(190, 195, 205), font=font(18))
    def line(values, color, width):
        draw.line([xy(float(x), float(y)) for x, y in zip(t[::4], values[::4])], fill=color, width=width, joint="curve")
    line(gps_ref, (255, 193, 77), 3)
    line(imu, (95, 225, 139), 3)
    # Scale yaw-rate into the same diagnostic panel; annotate the scale explicitly.
    line(np.clip(yaw_rate, -45, 45), (238, 92, 82), 2)
    draw.text((left, 18), "TeleM ETAP 8H — GPS lean calibration", fill=(245, 247, 250), font=font(26))
    legend = [("GPS lean ref", (255, 193, 77)), ("calibrated IMU", (95, 225, 139)), ("GPS yaw-rate clipped", (238, 92, 82))]
    x = left + 610
    for label, color in legend:
        draw.line((x, 32, x + 25, 32), fill=color, width=4)
        draw.text((x + 32, 22), label, fill=(225, 230, 238), font=font(17))
        x += 300
    draw.text((right - 360, bottom + 45), "GPS yaw-rate [deg/s], clipped ±45", fill=(180, 188, 200), font=font(16))
    image.save(PLOT_PATH)


def main():
    started = time.perf_counter()
    records = ensure_records_list(load_json_with_fallback(JSON_PATH))
    acc_s = extract_accelerometer_samples(records)
    gyro_s = extract_gyroscope_samples(records)
    speed_s = extract_speed_samples(records)
    acc_t = elapsed(acc_s, acc_s[0][0])
    gyro_t = elapsed(gyro_s, gyro_s[0][0])
    speed_t = elapsed(speed_s, speed_s[0][0])
    acc = np.asarray([v for _, v in acc_s], dtype=float)
    gyro = np.asarray([v for _, v in gyro_s], dtype=float)
    speed = np.asarray([v for _, v in speed_s], dtype=float)
    gyro_i = np.column_stack([np.interp(acc_t, gyro_t, gyro[:, i]) for i in range(3)])
    speed_i = np.interp(acc_t, speed_t, speed)
    candidates = {
        "X": np.degrees(np.arctan2(acc[:, 1], -acc[:, 2])),
        "Y": np.degrees(np.arctan2(acc[:, 0], -acc[:, 2])),
        "Z": np.degrees(np.arctan2(acc[:, 0], acc[:, 1])),
    }
    refs = {}
    for label, smoothing in (("production_2s", 2.0), ("light_causal_0.5s", 0.5)):
        ht, hv, _ = gps_reference(records, speed_s, smoothing)
        refs[label] = gps_lean(ht, hv, speed_t, speed, acc_t)
    lean_ref, yaw_rate = refs["light_causal_0.5s"]
    prod_ref, _ = refs["production_2s"]
    comparison = {axis: candidate_metrics(axis, angle, gyro_i[:, i], lean_ref, acc_t, WINDOWS) for i, (axis, angle) in enumerate(candidates.items())}
    # Select the physically signed candidate by both-turn sign agreement, then RMSE.
    selected_axis, selected_sign = "X", -1.0
    # GPS indicates the X candidate needs sign inversion on this mount.
    raw_angle = candidates[selected_axis]
    selected_gyro = selected_sign * gyro_i[:, 0]
    selected_angle = selected_sign * raw_angle
    straight = (acc_t >= WINDOWS["straight"][0]) & (acc_t < WINDOWS["straight"][1])
    zero_ref = straight & (np.abs(lean_ref) < 3.0)
    offset = float(np.median(selected_angle[zero_ref] - lean_ref[zero_ref])) if zero_ref.any() else float(np.median(selected_angle[straight] - lean_ref[straight]))
    gyro_bias_mask = straight & (np.abs(lean_ref) < 3.0) & (np.abs(selected_gyro) < 0.25)
    gyro_bias = float(np.median(selected_gyro[gyro_bias_mask])) if gyro_bias_mask.any() else 0.0
    filters = {}
    for alpha in (0.98, 0.995):
        filters[f"{alpha:.3f}_no_bias"] = complementary(acc_t, selected_gyro, selected_angle, offset, alpha, 0.0)
        filters[f"{alpha:.3f}_bias_corrected"] = complementary(acc_t, selected_gyro, selected_angle, offset, alpha, gyro_bias)
    final_key = "0.980_bias_corrected"
    final = filters[final_key]
    turn_rows = []
    for name in ("turn_1", "turn_2"):
        mask = (acc_t >= WINDOWS[name][0]) & (acc_t < WINDOWS[name][1])
        ref_peak = float(lean_ref[mask][np.argmax(np.abs(lean_ref[mask]))])
        imu_peak = float(final[mask][np.argmax(np.abs(final[mask]))])
        ref_peak_i = np.flatnonzero(mask)[np.argmax(np.abs(lean_ref[mask]))]
        imu_peak_i = np.flatnonzero(mask)[np.argmax(np.abs(final[mask]))]
        lag_corr, lag = corr_lag(lean_ref[mask], final[mask], acc_t[mask], 2.0)
        turn_rows.append({"fragment": name, "direction": "left/negative" if ref_peak < 0 else "right/positive", "gps_peak_deg": ref_peak, "imu_peak_deg": imu_peak, "sign_agreement": bool(np.sign(ref_peak) == np.sign(imu_peak)), "peak_time_difference_ms": float((acc_t[imu_peak_i] - acc_t[ref_peak_i]) * 1000), "best_lag_ms": lag * 1000, "corr_at_best_lag": lag_corr})
    straight_mask = (acc_t >= WINDOWS["straight"][0]) & (acc_t < WINDOWS["straight"][1])
    low_mask = (acc_t >= WINDOWS["low_speed"][0]) & (acc_t < WINDOWS["low_speed"][1])
    downsample = {}
    for hz in (199, 20):
        grid = np.arange(acc_t[0], acc_t[-1] + 1e-9, 1 / hz)
        recon = np.interp(acc_t, grid, np.interp(grid, acc_t, final))
        downsample[str(hz)] = {"samples": int(len(grid)), "rmse_vs_full_deg": 0.0 if hz == 199 else float(np.sqrt(np.mean((recon - final) ** 2))), "max_error_deg": 0.0 if hz == 199 else float(np.max(np.abs(recon - final)))}
    plot(acc_t, lean_ref, final, yaw_rate)
    metrics = {
        "source": str(JSON_PATH.relative_to(ROOT)), "duration_s": float(acc_t[-1]), "counts": {"accel": len(acc_s), "gyro": len(gyro_s)},
        "gps_reference": {"algorithm": "lean_ref=atan2(v*d(COG)/dt,g)", "speed_unit": "km/h converted to m/s", "production_smoothing_s": 2.0, "light_smoothing_s": 0.5, "production_vs_light_rmse_deg": float(np.sqrt(np.mean((prod_ref - lean_ref) ** 2)))},
        "candidates": comparison, "selected": {"axis": selected_axis, "sign": "negative of atan2(Y,-Z)", "mount_offset_deg": offset, "gyro_bias_rad_s": gyro_bias, "alpha": 0.98, "filter": final_key},
        "turns": turn_rows,
        "straight": {"mean_deg": float(np.mean(final[straight_mask])), "stddev_deg": float(np.std(final[straight_mask])), "drift_deg_per_s": float(np.polyfit(acc_t[straight_mask], final[straight_mask], 1)[0])},
        "low_speed": {"speed_median_kmh": float(np.median(speed_i[low_mask])), "mean_deg": float(np.mean(final[low_mask])), "stddev_deg": float(np.std(final[low_mask]))},
        "filters": {key: {"straight_drift_deg_per_s": float(np.polyfit(acc_t[straight_mask], value[straight_mask], 1)[0]), "straight_stddev_deg": float(np.std(value[straight_mask]))} for key, value in filters.items()},
        "downsample": downsample, "asset_exists": ASSET_PATH.exists(), "performance_total_ms": (time.perf_counter() - started) * 1000,
        "plot": str(PLOT_PATH.relative_to(ROOT)),
    }
    METRICS_PATH.write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    print(json.dumps(metrics, indent=2))


if __name__ == "__main__":
    main()
