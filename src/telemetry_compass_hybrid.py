"""Offline, opt-in GPS/FIT anchored relative attitude reconstruction.

No magnetic-north estimate is obtained from acceleration. A rigid camera mount
is required. Independent IMU segments are calibrated independently; a missing
anchor leaves them unavailable. Rendering only interpolates the prepared axis.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import time

import numpy as np

ALGORITHM_VERSION = 2  # 2: end-of-data calibration windows for short files
DEFAULTS = {
    "compass_heading_mode": "gps_imu",
    "compass_reference_source": "fit",
    "gps_stabilization_seconds": 30.0,
    "min_calibration_seconds": 30.0,
    "max_calibration_seconds": 300.0,
    "min_calibration_speed_kmh": 8.0,
    "compass_drift_correction": True,
    "compass_mount_offset_deg": 0.0,
    "compass_imu_method": "auto",
}
# GPS/FIT + IMU reconstruction is the only compass mode. The IMU policy is
# fixed to "auto" (CORI only when its gravity-frame check passes, else
# GYRO+ACCL) and the camera offset to 0; values stored by older layouts
# (standard mode, forced CORI/GYRO, offset) are ignored.
FIXED = {"compass_heading_mode": "gps_imu", "compass_imu_method": "auto", "compass_mount_offset_deg": 0.0}


def hybrid_enabled(cfg):
    """True for every configured compass (the reconstruction is the only mode)."""
    return isinstance(cfg, dict) and bool(cfg)


def parameters(cfg):
    return {key: FIXED.get(key, cfg.get(key, value)) for key, value in DEFAULTS.items()}


def timestamp(value):
    if isinstance(value, datetime):
        return (value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value).timestamp()
    return float(value)


def sample_array(samples, vector=False):
    backing = getattr(samples, "_arr", None)
    if backing is not None:
        return np.asarray(backing, dtype=np.float64)
    if isinstance(samples, np.ndarray):
        return np.asarray(samples, dtype=np.float64)
    width = 4 if vector else 2
    if not samples:
        return np.empty((0, width), dtype=np.float64)
    return np.asarray([(timestamp(dt), *(value if vector else (np.nan if value is None else value,)))
                       for dt, value in samples], dtype=np.float64)


def track_array(track):
    backing = getattr(track, "_arr", None)
    if backing is not None:
        return np.asarray(backing, dtype=np.float64)
    if isinstance(track, np.ndarray):
        return np.asarray(track, dtype=np.float64)
    return np.asarray([(timestamp(t), lat, lon) for t, lat, lon in (track or [])], dtype=float).reshape(-1, 3)


def wrap180(value):
    return (np.asarray(value) + 180.0) % 360.0 - 180.0


def rotate(q, vectors):
    q = np.asarray(q)
    v = np.asarray(vectors)
    u = q[..., 1:]
    return v + 2 * (q[..., :1] * np.cross(u, v) + np.cross(u, np.cross(u, v)))


def multiply(a, b):
    aw, ax, ay, az = a
    bw, bx, by, bz = b
    return np.array((aw*bw-ax*bx-ay*by-az*bz, aw*bx+ax*bw+ay*bz-az*by,
                     aw*by-ax*bz+ay*bw+az*bx, aw*bz+ax*by-ay*bx+az*bw))


def align_vectors(source, target):
    a = np.array(source, dtype=float, copy=True)
    b = np.array(target, dtype=float, copy=True)
    a /= np.linalg.norm(a)
    b /= np.linalg.norm(b)
    dot = float(a @ b)
    if dot < -0.999999:
        axis = np.cross(a, [1., 0., 0.])
        if np.linalg.norm(axis) < .1:
            axis = np.cross(a, [0., 1., 0.])
        return np.r_[0., axis / np.linalg.norm(axis)]
    q = np.r_[1.0 + dot, np.cross(a, b)]
    return q / np.linalg.norm(q)


def _yaw(q, up, forward):
    """Compass clockwise azimuth of the optical axis, independent of roll."""
    f = rotate(q, np.broadcast_to(forward, (len(q), 3)))
    projected = f-(f @ up)[:, None]*up
    horizontal = np.linalg.norm(projected, axis=1)
    valid = np.flatnonzero(horizontal >= .15)
    if not len(valid):
        return None
    north = projected[valid[0]].copy()
    north /= np.linalg.norm(north)
    east = np.cross(north, up)
    angles = np.arctan2(f @ east, f @ north)
    angles[horizontal < .15] = np.nan  # lens points near vertical: yaw undefined
    return np.rad2deg(angles)


def cori_attitude(cori, gravity):
    """Accept CORI only with a consistent gravity frame, never by norm alone."""
    if len(cori) < 3 or len(gravity) < 3:
        return None, {"reason": "CORI/GRAV missing"}
    q = np.asarray(cori[:, 1:], dtype=float)
    norms = np.linalg.norm(q, axis=1)
    if np.any(~np.isfinite(norms)) or np.any(abs(norms-1) > .05):
        return None, {"reason": "CORI invalid quaternion norm"}
    q = q / norms[:, None]
    g = np.column_stack([np.interp(cori[:, 0], gravity[:, 0], gravity[:, i]) for i in (1, 2, 3)])
    gnorm = np.linalg.norm(g, axis=1)
    if np.any(gnorm < .5) or np.any(gnorm > 1.5):
        return None, {"reason": "GRAV invalid norm"}
    # GoPro GRAV follows the camera accelerometer's up/specific-force sign.
    wg = rotate(q, g / gnorm[:, None])
    up = np.median(wg, axis=0)
    up /= np.linalg.norm(up)
    errors = np.rad2deg(np.arccos(np.clip(wg @ up, -1, 1)))
    p95 = float(np.percentile(errors, 95))
    if p95 > 5.0:
        return None, {"reason": "CORI gravity-frame consistency failed", "gravity_p95_deg": p95}
    yaw = _yaw(q, up, np.array([0., 0., 1.]))
    if yaw is None:
        return None, {"reason": "CORI optical axis vertical"}
    return np.column_stack((cori[:, 0], yaw)), {"method": "CORI+GRAV", "gravity_p95_deg": p95}


def gyro_attitude(gyro, accel, *, max_gap=.15, forward=(0., 1., 0.)):
    """Full body->world quaternion integration with gated gravity correction.

    Input is the existing parser's canonical XYZ, rad/s and m/s² (ZXY raw).
    GoPro optical axis is canonical Y; image rotation around that axis does
    not change the lens direction. No raw-Z-only integration is used.
    """
    if len(gyro) < 3 or len(accel) < 3:
        return np.empty((0, 2)), {"reason": "GYRO+ACCL missing"}
    if np.any(np.diff(gyro[:, 0]) <= 0) or np.any(np.diff(accel[:, 0]) <= 0):
        return np.empty((0, 2)), {"reason": "IMU timestamps not strictly increasing"}
    # Retain native timestamps at ~100 Hz; trapezoid-mean rates preserve turns.
    edges = np.r_[0, np.flatnonzero(np.diff(np.floor((gyro[:, 0]-gyro[0, 0])*100)))+1, len(gyro)]
    sums = np.add.reduceat(gyro[:, 1:], edges[:-1], axis=0)
    rates = sums / np.diff(edges)[:, None]
    ts = gyro[edges[:-1], 0].copy()
    av = np.column_stack([np.interp(ts, accel[:, 0], accel[:, k]) for k in (1, 2, 3)])
    nearest = np.searchsorted(accel[:, 0], ts)
    nearest = np.clip(nearest, 1, len(accel)-1)
    distance = np.minimum(abs(ts-accel[nearest, 0]), abs(ts-accel[nearest-1, 0]))
    good = np.isfinite(rates).all(axis=1) & np.isfinite(av).all(axis=1) & (distance <= max_gap)
    good &= (np.linalg.norm(rates, axis=1) < 20)
    up = np.array([0., 0., 1.])
    result = np.full((len(ts), 2), np.nan)
    result[:, 0] = ts
    start = 0
    segments = 0
    while start < len(ts):
        if not good[start] or not (5 < np.linalg.norm(av[start]) < 15):
            start += 1
            continue
        end = start+1
        while end < len(ts) and good[end] and ts[end]-ts[end-1] <= max_gap:
            end += 1
        q = align_vectors(av[start], up)
        quats = np.empty((end-start, 4))
        quats[0] = q
        qw, qx, qy, qz = q
        r_x = rates[start:end, 0]
        r_y = rates[start:end, 1]
        r_z = rates[start:end, 2]
        ax = av[start:end, 0]
        ay = av[start:end, 1]
        az = av[start:end, 2]
        ts_seg = ts[start:end]
        for i in range(1, end-start):
            dt = ts_seg[i]-ts_seg[i-1]
            om_x = 0.5 * (r_x[i-1] + r_x[i])
            om_y = 0.5 * (r_y[i-1] + r_y[i])
            om_z = 0.5 * (r_z[i-1] + r_z[i])
            angle = math.sqrt(om_x*om_x + om_y*om_y + om_z*om_z) * dt
            half_ang = angle * 0.5
            cos_half = math.cos(half_ang)
            s = math.sin(half_ang) * dt / angle if angle > 1e-12 else dt * 0.5
            dqw = cos_half
            dqx = om_x * s
            dqy = om_y * s
            dqz = om_z * s

            nw = qw*dqw - qx*dqx - qy*dqy - qz*dqz
            nx = qw*dqx + qx*dqw + qy*dqz - qz*dqy
            ny = qw*dqy - qx*dqz + qy*dqw + qz*dqx
            nz = qw*dqz + qx*dqy - qy*dqx + qz*dqw

            inv_norm = 1.0 / math.sqrt(nw*nw + nx*nx + ny*ny + nz*nz)
            qw = nw * inv_norm
            qx = nx * inv_norm
            qy = ny * inv_norm
            qz = nz * inv_norm

            an = math.sqrt(ax[i]*ax[i] + ay[i]*ay[i] + az[i]*az[i])
            if 8.3 <= an <= 11.3:
                # Expected gravity direction in body frame: rotate(q_conj, [0, 0, 1])
                exp_x = 2.0 * (-qw*qy + qz*qx)
                exp_y = 2.0 * (qw*qx + qz*qy)
                exp_z = 1.0 - 2.0 * (qx*qx + qy*qy)

                inv_an = 1.0 / an
                c_ax = ax[i] * inv_an
                c_ay = ay[i] * inv_an
                c_az = az[i] * inv_an

                corr_x = c_ay * exp_z - c_az * exp_y
                corr_y = c_az * exp_x - c_ax * exp_z
                corr_z = c_ax * exp_y - c_ay * exp_x

                k = 0.25 * dt
                dqw = 1.0
                dqx = corr_x * k
                dqy = corr_y * k
                dqz = corr_z * k

                nw = qw*dqw - qx*dqx - qy*dqy - qz*dqz
                nx = qw*dqx + qx*dqw + qy*dqz - qz*dqy
                ny = qw*dqy - qx*dqz + qy*dqw + qz*dqx
                nz = qw*dqz + qx*dqy - qy*dqx + qz*dqw

                inv_norm = 1.0 / math.sqrt(nw*nw + nx*nx + ny*ny + nz*nz)
                qw = nw * inv_norm
                qx = nx * inv_norm
                qy = ny * inv_norm
                qz = nz * inv_norm

            quats[i, 0] = qw
            quats[i, 1] = qx
            quats[i, 2] = qy
            quats[i, 3] = qz
        yaw = _yaw(quats, up, np.asarray(forward))
        if yaw is not None:
            result[start:end, 1] = yaw
            # Explicit separator prevents interpolation across segment resets.
            if start:
                result[start-1, 1] = np.nan
        segments += 1
        start = end
    return result, {"method": "GYRO+ACCL quaternion", "imu_segments": segments, "integration_hz": 100}


@dataclass
class HybridResult:
    axis: np.ndarray = field(default_factory=lambda: np.empty((0, 2)))
    diagnostics: dict = field(default_factory=dict)

    @property
    def samples(self):
        from src.telemetry_processed_cache import LazySampleList
        return LazySampleList(self.axis, tz_aware=False)

    def lookup(self, when):
        value = sample_hybrid_axis(self.axis, np.asarray([timestamp(when)]))[0]
        return float(value) if np.isfinite(value) else None


def sample_hybrid_axis(axis, targets):
    """One canonical microsecond time grid and float32 presentation contract."""
    targets = np.round(np.asarray(targets, dtype=float), 6)
    output = np.full(len(targets), np.nan, dtype=np.float32)
    if not len(axis):
        return output
    indices = np.searchsorted(axis[:, 0], targets, side="right")-1
    good = (indices >= 0) & (targets <= axis[-1, 0]+1e-6)
    indices = np.clip(indices, 0, len(axis)-1)
    good &= np.isfinite(axis[indices, 1])
    nxt = np.minimum(indices+1, len(axis)-1)
    interpolate = good & np.isfinite(axis[nxt, 1]) & (nxt != indices)
    values = axis[indices, 1].copy()
    span = axis[nxt[interpolate], 0]-axis[indices[interpolate], 0]
    frac = (targets[interpolate]-axis[indices[interpolate], 0])/span
    values[interpolate] += wrap180(axis[nxt[interpolate], 1]-values[interpolate])*frac
    output[good] = values[good] % 360
    return output


def reference_observations(track, speed=None, quality=None):
    """Independent ~1 Hz position evidence, with centred course timestamps.

    High-rate duplicates cannot multiply the calibration's effective sample
    count. A fix flag alone never overrides impossible displacement or gaps.
    """
    track = np.asarray(track, dtype=float)
    if len(track) < 4:
        return np.empty((0, 4)), {"gps_rejected": len(track)}
    valid = np.isfinite(track).all(axis=1) & (abs(track[:, 1]) <= 90) & (abs(track[:, 2]) <= 180)
    valid &= ~((track[:, 1] == 0) & (track[:, 2] == 0))
    if np.any(np.diff(track[:, 0]) <= 0):
        return np.empty((0, 4)), {"reason": "GPS timestamps not strictly increasing"}
    bins = np.floor(track[:, 0]-track[0, 0]).astype(np.int64)
    indices = np.r_[0, np.flatnonzero(np.diff(bins))+1]
    points = track[indices]
    good = valid[indices].copy()
    lat = np.deg2rad(points[:, 1])
    lon = np.deg2rad(points[:, 2])
    dt = np.diff(points[:, 0])
    dlat = np.diff(lat)
    dlon = np.diff(lon)
    h = np.sin(dlat/2)**2 + np.cos(lat[:-1])*np.cos(lat[1:])*np.sin(dlon/2)**2
    distance = 6371000*2*np.arcsin(np.sqrt(np.clip(h, 0, 1)))
    velocity = distance / np.maximum(dt, 1e-6) * 3.6
    link_good = (dt > 0) & (dt <= 2.5) & (velocity <= 100)
    good[1:] &= link_good
    good[:-1] &= link_good
    # An isolated point can have plausible speed but implausible acceleration.
    if len(velocity) > 1:
        acceleration_ok = abs(np.diff(velocity))/np.maximum(dt[1:], .1) <= 25
        good[1:-1] &= acceleration_ok
    if quality is not None and len(quality):
        quality = quality[np.isfinite(quality).all(axis=1)]
        if len(quality):
            qi = np.searchsorted(quality[:, 0], points[:, 0], side="right")-1
            qi = np.clip(qi, 0, len(quality)-1)
            good &= abs(quality[qi, 0]-points[:, 0]) <= 1.5
            good &= (quality[qi, 2] >= 3) & (quality[qi, 1] <= 5.0)
    # Central displacement gives course at the actual midpoint, rather than
    # assigning the heading of a trailing multi-second baseline to its end.
    a, b = np.arange(len(points)-2), np.arange(2, len(points))
    x = np.sin(lon[b]-lon[a])*np.cos(lat[b])
    y = np.cos(lat[a])*np.sin(lat[b])-np.sin(lat[a])*np.cos(lat[b])*np.cos(lon[b]-lon[a])
    heading = np.rad2deg(np.arctan2(x, y)) % 360
    span = points[b, 0]-points[a, 0]
    hh = np.sin((lat[b]-lat[a])/2)**2 + np.cos(lat[a])*np.cos(lat[b])*np.sin((lon[b]-lon[a])/2)**2
    displacement = 6371000*2*np.arcsin(np.sqrt(np.clip(hh, 0, 1)))
    measured_speed = displacement/np.maximum(span, 1e-6)*3.6
    consistent = good[a] & good[a+1] & good[b] & (span <= 4.0)
    if speed is not None and len(speed):
        si = np.searchsorted(speed[:, 0], points[a+1, 0], side="right")-1
        si = np.clip(si, 0, len(speed)-1)
        reported = speed[si, 1]
        consistent &= np.isfinite(reported) & (abs(speed[si, 0]-points[a+1, 0]) <= 2.5)
        consistent &= abs(measured_speed-reported) <= np.maximum(15., reported*.6)
    observations = np.column_stack(((points[a, 0]+points[b, 0])/2, heading, measured_speed, consistent))
    # Stationary coordinates can confirm a fix, but never anchor a heading.
    observations[displacement < 2., 1] = np.nan
    return observations, {"independent_gps_samples": len(observations),
                          "gps_rejected": int(np.count_nonzero(~consistent))}


def _fit_anchor(times, relative, heading, *, drift_enabled, target_start):
    """Robust circular offset and a statistically gated linear drift model."""
    delta = wrap180(heading-relative)
    center = float(np.rad2deg(np.angle(np.mean(np.exp(1j*np.deg2rad(delta))))))
    center += float(np.median(wrap180(delta-center)))
    residual = wrap180(delta-center)
    keep = abs(residual) <= max(6., min(25., 4.5*float(np.median(abs(residual)))))
    if np.count_nonzero(keep) < 20 or np.mean(keep) < .75:
        return None, "too many angular outliers"
    t0 = float(np.mean(times[keep]))
    x = times-t0
    # Unwrap *differences around a robust circular centre*, never azimuths by
    # an arithmetic average. Huber trimming removes outlier GPS fixes.
    slope = 0.
    intercept = center
    for _ in range(4):
        xx = x[keep]
        yy = residual[keep]
        slope = float(np.sum(xx*(yy-np.mean(yy))) / max(np.sum(xx*xx), 1e-9))
        intercept = center+float(np.mean(yy))
        errors = wrap180(delta-intercept-slope*x)
        sigma = max(.05, float(1.4826*np.median(abs(errors[keep]-np.median(errors[keep])))))
        new_keep = abs(errors) <= max(5., min(20., 3*sigma))
        if np.count_nonzero(new_keep) < 20:
            break
        keep = new_keep
    if np.mean(keep) < .75:
        return None, "too many angular outliers"
    linear_error = wrap180(delta-intercept-slope*x)
    offset = center+float(np.median(wrap180(delta[keep]-center)))
    offset_error = wrap180(delta-offset)
    stderr = sigma/math.sqrt(max(float(np.sum(x[keep]**2)), 1e-9))
    linear_p95 = float(np.percentile(abs(linear_error[keep]), 95))
    offset_p95 = float(np.percentile(abs(offset_error[keep]), 95))
    use_drift = bool(drift_enabled and np.ptp(times[keep]) >= 25 and abs(slope) > 2.5*stderr
                     and abs(slope) <= .5 and linear_p95 < offset_p95*.8)
    errors = linear_error if use_drift else offset_error
    p95 = float(np.percentile(abs(errors[keep]), 95))
    if p95 > 10.:
        return None, "angular dispersion exceeds 10 degrees"
    # Independent turn agreement catches the wrong yaw/gyro sign, even if a
    # linear trend could superficially absorb part of a short steady turn.
    gps_turn = wrap180(np.diff(heading))
    imu_turn = wrap180(np.diff(relative))
    turn_mask = keep[1:] & keep[:-1] & (np.diff(times) <= 2.5)
    turn_corr = None
    if np.count_nonzero(turn_mask) >= 15 and np.std(gps_turn[turn_mask]) > 1.5:
        aa, bb = gps_turn[turn_mask], imu_turn[turn_mask]
        turn_corr = float(np.corrcoef(aa, bb)[0, 1]) if np.std(bb) > .01 else -1.
        gain = float(np.sum(aa*bb)/max(np.sum(bb*bb), 1e-9))
        if turn_corr < .45 or not .45 <= gain <= 1.8:
            return None, "GPS/IMU turn sign or scale mismatch"
    # The bound is an estimate, not an absolute guarantee. It is checked again
    # against masked GPS/FIT holdouts in the real-data validation harness.
    rate_bound = max(.02, 2.5*stderr) if use_drift else max(.02, abs(slope)+2.5*stderr)
    back_uncertainty = math.hypot(p95, (t0-target_start)*rate_bound)
    if drift_enabled and back_uncertainty > 20:
        return None, "backward drift uncertainty requires a longer calibration"
    return {"offset_deg": float(intercept if use_drift else offset),
            "drift_deg_s": slope if use_drift else 0., "drift_applied": use_drift,
            "drift_standard_error": stderr, "drift_rate_bound_deg_s": rate_bound,
            "origin_ts": t0, "error_median_deg": float(np.median(abs(errors[keep]))),
            "error_p95_deg": p95, "error_max_deg": float(np.max(abs(errors[keep]))),
            "accepted_samples": int(np.count_nonzero(keep)), "rejected_samples": int(np.count_nonzero(~keep)),
            "backward_uncertainty_deg": back_uncertainty, "turn_correlation": turn_corr}, "ok"


def calibrate_segment(imu, observations, cfg):
    minimum = float(cfg["min_calibration_seconds"])
    maximum = float(cfg["max_calibration_seconds"])
    stabilization = float(cfg["gps_stabilization_seconds"])
    if not (30 <= minimum <= maximum <= 300) or stabilization < 30:
        return None, {"status": "invalid_parameters", "reason": "Require stabilization>=30 and 30<=min<=max<=300"}
    selected = observations[(observations[:, 0] >= imu[0, 0]) & (observations[:, 0] <= imu[-1, 0])]
    stable_start = None
    detected = None
    calibration_start = None
    candidate = []
    attempts = []
    checkpoints = sorted(set([minimum, maximum]+[v for v in (60, 120, 180, 240, 300) if minimum < v < maximum]))
    checkpoint = 0
    last_ts = None
    relative = np.rad2deg(np.unwrap(np.deg2rad(imu[:, 1])))
    for row in selected:
        ts, heading, speed, good = row
        if not good or (last_ts is not None and ts-last_ts > 2.5):
            stable_start = detected = calibration_start = None
            candidate = []
            checkpoint = 0
        last_ts = ts
        if not good:
            continue
        if stable_start is None:
            stable_start = ts
        # A stable fix needs a continuous five-second *segment*, then the
        # separate stabilization timer starts. Not 30 s from the first fix.
        if detected is None and ts-stable_start >= 5.:
            detected = ts
        if detected is None or ts-detected < stabilization:
            continue
        if calibration_start is None:
            calibration_start = ts
        elapsed = ts-calibration_start
        if np.isfinite(heading) and speed >= float(cfg["min_calibration_speed_kmh"]):
            candidate.append((ts, np.interp(ts, imu[:, 0], relative), heading))
        if checkpoint >= len(checkpoints) or elapsed < checkpoints[checkpoint]-1e-4:
            continue
        window = checkpoints[checkpoint]
        checkpoint += 1
        model = None
        reason = "insufficient independent moving samples or temporal coverage"
        if len(candidate) >= max(20, int(window*.65)) and candidate[-1][0]-candidate[0][0] >= window*.8:
            vals = np.asarray(candidate)
            model, reason = _fit_anchor(vals[:, 0], vals[:, 1], vals[:, 2]+float(cfg["compass_mount_offset_deg"]),
                                        drift_enabled=bool(cfg["compass_drift_correction"]), target_start=imu[0, 0])
        attempts.append({"window_seconds": window, "status": reason, "samples": len(candidate)})
        if model is not None:
            model.update(stable_fix_ts=float(detected), calibration_start_ts=float(calibration_start),
                         calibration_end_ts=float(ts), window_seconds=float(elapsed))
            return model, {"status": "ok", "attempts": attempts}
        if checkpoint == len(checkpoints):
            return None, {"status": "insufficient_quality", "attempts": attempts, "reason": reason}
    # The data ended before the next checkpoint (short file). Calibration may
    # use any later stretch: try windows that start later and run to the end
    # of the data, under the same acceptance criteria as above.
    if calibration_start is not None and len(candidate) >= 20:
        vals = np.asarray(candidate)
        end_ts = float(vals[-1, 0])
        shift = 0.
        while end_ts-(calibration_start+shift) >= minimum:
            sub = vals[vals[:, 0] >= calibration_start+shift]
            span = end_ts-(calibration_start+shift)
            model = None
            reason = "insufficient independent moving samples or temporal coverage"
            if len(sub) >= max(20, int(span*.65)) and sub[-1, 0]-sub[0, 0] >= span*.8:
                model, reason = _fit_anchor(sub[:, 0], sub[:, 1], sub[:, 2]+float(cfg["compass_mount_offset_deg"]),
                                            drift_enabled=bool(cfg["compass_drift_correction"]), target_start=imu[0, 0])
            attempts.append({"window_seconds": round(span, 3), "start_offset_s": shift, "to_end_of_data": True,
                             "status": reason, "samples": len(sub)})
            if model is not None:
                model.update(stable_fix_ts=float(detected), calibration_start_ts=float(calibration_start+shift),
                             calibration_end_ts=end_ts, window_seconds=float(span))
                return model, {"status": "ok", "attempts": attempts}
            shift += 15.
    return None, {"status": "insufficient_data", "attempts": attempts,
                  "reason": "No stable fix followed by a sufficiently long calibration"}


def reconstruct(relative_axis, observations, cfg, imu_diagnostics=None):
    """Reconstruct within each contiguous IMU segment, never across a hole."""
    cfg = parameters(cfg)
    out = np.array(relative_axis, copy=True, dtype=float)
    if not len(out):
        return HybridResult(out, {"status": "unavailable", **(imu_diagnostics or {})})
    out[:, 1] = np.nan
    segments = []
    i = 0
    reconstructed_count = 0
    for_start = np.isfinite(relative_axis[:, 1])
    while i < len(out):
        if not for_start[i]:
            i += 1
            continue
        end = i+1
        while end < len(out) and for_start[end] and 0 < out[end, 0]-out[end-1, 0] <= .15:
            end += 1
        segment = relative_axis[i:end]
        model, diag = calibrate_segment(segment, observations, cfg)
        if model is not None:
            ts = segment[:, 0]
            yaw = np.rad2deg(np.unwrap(np.deg2rad(segment[:, 1])))
            predicted = yaw+model["offset_deg"]+model["drift_deg_s"]*(ts-model["origin_ts"])
            uncertainty = np.hypot(model["error_p95_deg"], abs(ts-model["origin_ts"])*model["drift_rate_bound_deg_s"])
            permitted = uncertainty <= 20
            # Anchor trustworthy post-calibration GPS with a short correction
            # time constant; the IMU retains actual rapid turns. Outliers are
            # gated, and long GPS gaps explicitly expire the estimate.
            oi = np.searchsorted(observations[:, 0], ts, side="right")-1
            correction = 0.
            target_correction = 0.
            last_good = model["calibration_end_ts"]
            previous_obs = -1
            for k, t in enumerate(ts):
                if t < model["calibration_end_ts"]:
                    continue
                j = int(oi[k])
                if j >= 0 and j != previous_obs:
                    previous_obs = j
                    row = observations[j]
                    if row[3] and np.isfinite(row[1]) and row[2] >= float(cfg["min_calibration_speed_kmh"]):
                        desired = row[1]+float(cfg["compass_mount_offset_deg"])
                        innovation = float(wrap180(desired-predicted[k]-correction))
                        if abs(innovation) <= 25:
                            target_correction = correction+innovation
                            last_good = t
                dt = ts[k]-ts[k-1] if k else 0.
                correction += (1-math.exp(-dt/2.))*(target_correction-correction)
                predicted[k] += correction
                permitted[k] = t-last_good <= 10.
            out[i:end, 1] = np.where(permitted, predicted % 360, np.nan)
            reconstructed_count += int(np.count_nonzero(permitted & (ts < model["calibration_end_ts"])))
            diag["model"] = model
            diag["reconstructed_start_ts"] = float(ts[np.flatnonzero(permitted)[0]]) if np.any(permitted) else None
        segments.append(diag)
        # The sample just before a reset must not interpolate into the new one.
        if i and end-i:
            out[i-1, 1] = np.nan
        i = end
    out[:, 0] = np.round(out[:, 0], 6)
    out[:, 1] = out[:, 1].astype(np.float32)
    valid = int(np.count_nonzero(np.isfinite(out[:, 1])))
    return HybridResult(out, {"status": "ok" if valid else "unavailable", "segments": segments,
                              "valid_percent": valid/max(1, len(out))*100,
                              "reconstructed_percent": reconstructed_count/max(1, len(out))*100,
                              **(imu_diagnostics or {})})


def _array_hash(arr):
    a = np.ascontiguousarray(arr, dtype=np.float64)
    return hashlib.sha256(a.view(np.uint8)).hexdigest()


def _save_result(path, result):
    import tempfile
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(suffix=".npz", dir=path.parent, delete=False) as temp:
        temp_path = Path(temp.name)
    try:
        np.savez_compressed(temp_path, axis=result.axis, diagnostics=json.dumps(result.diagnostics))
        temp_path.replace(path)
    finally:
        temp_path.unlink(missing_ok=True)


def _load_result(path):
    if path.exists():
        try:
            with np.load(path, allow_pickle=False) as data:
                return HybridResult(data["axis"], json.loads(str(data["diagnostics"])))
        except (OSError, ValueError, KeyError):
            pass
    return None


def prepare_manager_compass(manager, cfg, *, cache_dir=None):
    """Prepare once from original full source clips, not an export In/Out cut."""
    from src.telemetry_compass_orientation import read_orientation, source_fingerprint, READER_VERSION

    started = time.perf_counter()
    cfg = parameters(cfg)
    source = cfg["compass_reference_source"]
    if source not in ("gpmf", "fit"):
        return HybridResult(diagnostics={"status": "unavailable", "reason": "Invalid reference source; no fallback"})
    timeline = getattr(manager, "timeline", None)
    clips = getattr(timeline, "clips", [])
    if not clips:
        return HybridResult(diagnostics={"status": "unavailable", "reason": "No original source VideoTimeline"})
    track = track_array(manager.fit_gps_track if source == "fit" else manager.gps_track)
    if len(track) < 4:
        return HybridResult(diagnostics={"status": "unavailable", "reference_source": source,
                                         "reason": "Selected source has no position track; no fallback"})
    fit_speed = manager.fit_data.get("speed")
    if fit_speed is None or not len(fit_speed):
        fit_speed = manager.fit_data.get("enhanced_speed", [])
    speed = sample_array(fit_speed if source == "fit" else manager.speed_samples)
    gyro = sample_array(manager.gyroscope_samples, vector=True)
    accel = sample_array(manager.accelerometer_samples, vector=True)
    cache_dir = Path(cache_dir or Path(__file__).resolve().parents[1] / "cache/compass_hybrid")
    axes = []
    details = []
    for clip in clips:
        if getattr(clip, "absolute_start_dt", None) is None:
            details.append({"status": "unavailable", "reason": "Unknown absolute clip time"})
            continue
        local_start = float(getattr(clip, "local_start_s", 0.) or 0.)
        base = timestamp(clip.absolute_start_dt)-local_start
        duration = float(getattr(clip, "source_duration_s", 0.) or (local_start+clip.duration_s))
        own_track = track[(track[:, 0] >= base) & (track[:, 0] <= base+duration)]
        own_speed = speed[(speed[:, 0] >= base) & (speed[:, 0] <= base+duration)]
        own_gyro = gyro[(gyro[:, 0] >= base-1e-6) & (gyro[:, 0] <= base+duration)]
        own_accel = accel[(accel[:, 0] >= base-1e-6) & (accel[:, 0] <= base+duration)]
        try:
            fingerprint = source_fingerprint(clip.path)
        except OSError as exc:
            details.append({"status": "unavailable", "reason": str(exc)})
            continue
        signature = {"algorithm": ALGORITHM_VERSION, "reader": READER_VERSION, "source": fingerprint,
                     "base_ts": base, "parameters": cfg,
                     "track": _array_hash(own_track), "speed": _array_hash(own_speed),
                     "gyro": _array_hash(own_gyro), "accel": _array_hash(own_accel),
                     "fit_path": str(getattr(manager, "fit_path", "")) if source == "fit" else "",
                     "sync": getattr(manager, "telemetry_sync_offset_s", 0.),
                     "clip_sync": getattr(manager, "telemetry_sync_clip_offsets_s", {})}
        key = hashlib.sha256(json.dumps(signature, sort_keys=True).encode()).hexdigest()
        final_path = cache_dir / f"{key}.npz"
        result = _load_result(final_path)
        cache_hit = result is not None
        if result is None:
            try:
                imu_signature = {k: signature[k] for k in ("algorithm", "reader", "source", "base_ts", "gyro", "accel")}
                imu_signature["method"] = cfg["compass_imu_method"]
                imu_key = hashlib.sha256(json.dumps(imu_signature, sort_keys=True).encode()).hexdigest()
                attitude_path = cache_dir / "attitude" / f"{imu_key}.npz"
                attitude = _load_result(attitude_path)
                orientation_reader_cache_hit = False
                orientation = {}
                if attitude is None:
                    axis, imu_diag = None, {"reason": "CORI disabled by selection"}
                    orientation_meta = {"cache_hit": False}
                    if cfg["compass_imu_method"] in ("auto", "cori"):
                        orientation, orientation_meta = read_orientation(clip.path, base)
                        orientation_reader_cache_hit = orientation_meta.get("cache_hit", False)
                        axis, imu_diag = cori_attitude(orientation.get("CORI", np.empty((0, 5))),
                                                      orientation.get("GRAV", np.empty((0, 4))))
                    if axis is None and cfg["compass_imu_method"] in ("auto", "gyro"):
                        reason = imu_diag
                        gyro_meta = orientation_meta.get("streams", {}).get("GYRO", {})
                        accel_meta = orientation_meta.get("streams", {}).get("ACCL", {})
                        if not gyro_meta or (gyro_meta.get("ORIN") == "ZXY" and gyro_meta.get("SIUN") == "rad/s" and accel_meta.get("ORIN") == "ZXY"):
                            axis, imu_diag = gyro_attitude(own_gyro, own_accel)
                            imu_diag["CORI_rejection"] = reason
                        else:
                            axis = np.empty((0, 2))
                            imu_diag = {"reason": "Unsupported/unverified GPMF IMU axes or units", "CORI_rejection": reason}
                    if axis is None:
                        axis = np.empty((0, 2))
                    attitude = HybridResult(axis, imu_diag)
                    _save_result(attitude_path, attitude)
                quality = orientation.get("GPS_QUALITY") if (source == "gpmf" and orientation) else None
                observations, gps_diag = reference_observations(own_track, own_speed, quality)
                result = reconstruct(attitude.axis, observations, cfg, attitude.diagnostics)
                result.diagnostics.update(gps_diag, orientation_reader_cache_hit=orientation_reader_cache_hit,
                                          memory_bytes=int(attitude.axis.nbytes+result.axis.nbytes),
                                          rigid_mount_assumption=True)
                _save_result(final_path, result)
            except (OSError, ValueError, RuntimeError) as exc:
                result = HybridResult(diagnostics={"status": "unavailable", "reason": str(exc)})
        diag = dict(result.diagnostics, file=str(clip.path), cache_key=key, cache_hit=cache_hit, reference_source=source)
        details.append(diag)
        if len(result.axis):
            axes.append(result.axis)
    # Each file was independently anchored; NaNs mark file boundaries even for
    # adjacent timestamps. No assumption that CORI origins match across files.
    if axes:
        combined = np.concatenate([np.vstack((a, [a[-1, 0]+1e-6, np.nan])) for a in axes])
        order = np.argsort(combined[:, 0], kind="stable")
        combined = combined[order]
        if np.any(np.diff(combined[:, 0]) <= 0):
            return HybridResult(diagnostics={"status": "unavailable", "reason": "Overlapping independent clip clocks"})
    else:
        combined = np.empty((0, 2))
    diag = {"status": "ok" if len(combined) and np.any(np.isfinite(combined[:, 1])) else "unavailable",
            "reference_source": source, "clips": details, "prepare_seconds": time.perf_counter()-started,
            "axis_memory_bytes": int(combined.nbytes), "algorithm_version": ALGORITHM_VERSION}
    print("[COMPASS HYBRID] "+json.dumps(diag, ensure_ascii=False), flush=True)
    return HybridResult(combined, diag)


def snapshot_manager(manager):
    """Detach worker inputs so a different project cannot mutate a running job."""
    from types import SimpleNamespace
    from copy import deepcopy
    fit_speed = manager.fit_data.get("speed")
    if fit_speed is None or not len(fit_speed):
        fit_speed = manager.fit_data.get("enhanced_speed", [])
    return SimpleNamespace(
        timeline=deepcopy(getattr(manager, "timeline", None)),
        gps_track=track_array(manager.gps_track).copy(),
        fit_gps_track=track_array(manager.fit_gps_track).copy(),
        speed_samples=sample_array(manager.speed_samples).copy(),
        fit_data={"speed": sample_array(fit_speed).copy()},
        gyroscope_samples=sample_array(manager.gyroscope_samples, vector=True).copy(),
        accelerometer_samples=sample_array(manager.accelerometer_samples, vector=True).copy(),
        fit_path=getattr(manager, "fit_path", None),
        telemetry_sync_offset_s=getattr(manager, "telemetry_sync_offset_s", 0.),
        telemetry_sync_clip_offsets_s=dict(getattr(manager, "telemetry_sync_clip_offsets_s", {})),
    )
