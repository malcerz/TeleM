"""Synthetic camera-IMU / activity generator with a known clock offset.

The ride geometry comes from a smooth path (or a supplied lat/lon track); the
camera is mounted with an arbitrary rotation, leans with the bike in turns and
is shaken by road vibration.  The activity is sampled at 1 Hz on GPS time with
position noise, like a Garmin FIT.  ``true_offset_s`` follows the TeleM
contract ``telemetry_time = video_start + video_pos + offset``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

G = 9.81
R_EARTH = 6371000.0


@dataclass
class SynthRide:
    gyro: np.ndarray        # [t_epoch, x, y, z] rad/s (camera clock)
    accel: np.ndarray       # [t_epoch, x, y, z] m/s^2 (camera clock)
    video_t0_epoch: float   # clip start on the camera clock
    duration_s: float
    fit_t: np.ndarray       # epoch (GPS time)
    fit_speed_kmh: np.ndarray
    fit_lat: np.ndarray
    fit_lon: np.ndarray
    true_offset_s: float


def _rot(rng: np.random.Generator) -> np.ndarray:
    q = rng.normal(size=4)
    q /= np.linalg.norm(q)
    w, x, y, z = q
    return np.array([
        [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
        [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
        [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
    ])


def path_from_profile(duration_s: float, rng: np.random.Generator, *, straight: bool = False,
                      constant_speed: bool = False, fs: float = 200.0):
    """Heading/speed profile with turns, braking and accelerations."""
    t = np.arange(0.0, duration_s, 1.0 / fs)
    if constant_speed:
        v = np.full(len(t), 25 / 3.6)
    else:
        knots = np.arange(0.0, duration_s + 10.0, 8.0)
        vk = np.clip(rng.normal(6.5, 2.0, len(knots)), 2.5, 11.0)
        v = np.interp(t, knots, vk)
        v = np.convolve(v, np.ones(int(fs)) / fs, mode="same")
        v[: int(fs)] = v[int(fs)]
        v[-int(fs):] = v[-int(fs) - 1]
    if straight:
        omega = np.zeros(len(t))
    else:
        omega = np.zeros(len(t))
        tt = 5.0
        while tt < duration_s - 5.0:
            dur = rng.uniform(2.0, 6.0)
            angle = math.radians(rng.uniform(30, 100)) * rng.choice([-1, 1])
            m = (t >= tt) & (t < tt + dur)
            omega[m] = angle / dur * np.sin(np.pi * (t[m] - tt) / dur) * (np.pi / 2)
            tt += dur + rng.uniform(6.0, 20.0)
    psi = np.cumsum(omega) / fs
    return t, v, psi, omega


def make_ride(*, duration_s: float = 180.0, true_offset_s: float = 1.5, seed: int = 0,
              straight: bool = False, constant_speed: bool = False, imu_hz: float = 200.0,
              gps_noise_m: float = 2.0, vibration: float = 1.5, activity_pad_s: float = 600.0,
              fit_from_other_ride: bool = False) -> SynthRide:
    rng = np.random.default_rng(seed)
    pad = activity_pad_s
    total = duration_s + 2 * pad
    t, v, psi, omega = path_from_profile(total, rng, straight=straight, constant_speed=constant_speed, fs=imu_hz)
    dv = np.gradient(v) * imu_hz
    a_lat = v * omega
    lean = np.arctan2(a_lat, G)

    gps_t0 = 1_760_000_000.0                      # GPS epoch of t = 0
    # Clip covers true times [pad, pad + duration]; the camera clock is wrong
    # by -offset: video_start_camera = true_start - offset  <=> telemetry = video + offset
    clip = (t >= pad) & (t < pad + duration_s)
    tc = t[clip]
    mount = _rot(rng)
    # Body frame (bike): x forward, y left, z up — leaned about x in turns.
    cl, sl = np.cos(lean[clip]), np.sin(lean[clip])
    w_world = np.column_stack([np.zeros(clip.sum()), np.zeros(clip.sum()), omega[clip]])
    f_world = np.column_stack([dv[clip], a_lat[clip], np.full(clip.sum(), G)])

    def to_body(vec):
        # rotate world (forward/left/up, heading-aligned) into the leaned bike frame
        # Coordinated lean: the apparent lateral force vanishes in the body frame.
        x, y, z = vec[:, 0], vec[:, 1], vec[:, 2]
        return np.column_stack([x, cl * y - sl * z, sl * y + cl * z])

    gyro_b = to_body(w_world)
    acc_b = to_body(f_world)
    n = len(tc)
    vib = vibration * rng.normal(size=(n, 3)) + 0.4 * vibration * np.sin(2 * np.pi * 9.0 * tc)[:, None]
    gyro_b = gyro_b + 0.02 * rng.normal(size=(n, 3)) + 0.05 * np.sin(2 * np.pi * 4.0 * tc)[:, None] + 0.01
    acc_b = acc_b + vib
    gyro_c = gyro_b @ mount.T
    acc_c = acc_b @ mount.T

    video_t0 = gps_t0 + pad - true_offset_s
    t_cam = video_t0 + (tc - pad)
    gyro = np.column_stack([t_cam, gyro_c])
    accel = np.column_stack([t_cam, acc_c])

    # Activity at 1 Hz on GPS time.
    if fit_from_other_ride:
        t2, v2, psi2, _ = path_from_profile(total, np.random.default_rng(seed + 1000), fs=imu_hz)
        v_use, psi_use = v2, psi2
    else:
        v_use, psi_use = v, psi
    x = np.cumsum(v_use * np.sin(psi_use)) / imu_hz
    y = np.cumsum(v_use * np.cos(psi_use)) / imu_hz
    sec = np.arange(0, int(total)) * int(imu_hz)
    lat0, lon0 = 54.36, 18.62
    # Receiver positions are Kalman-filtered: error is time-correlated (~10 s)
    # with a small white component, not independent 1 Hz jitter.
    def _corr_noise():
        k = np.ones(10) / 10.0
        slow = np.convolve(rng.normal(size=len(sec) + 20), k, mode="same")[10:-10]
        slow *= gps_noise_m / max(np.std(slow), 1e-9)
        return slow + 0.3 * rng.normal(size=len(sec))
    xs = x[sec] + _corr_noise()
    ys = y[sec] + _corr_noise()
    lat = lat0 + np.degrees(ys / R_EARTH)
    lon = lon0 + np.degrees(xs / (R_EARTH * math.cos(math.radians(lat0))))
    spd = v_use[sec] * 3.6 + 0.3 * rng.normal(size=len(sec))
    return SynthRide(gyro=gyro, accel=accel, video_t0_epoch=video_t0, duration_s=duration_s,
                     fit_t=gps_t0 + t[sec], fit_speed_kmh=spd, fit_lat=lat, fit_lon=lon,
                     true_offset_s=true_offset_s)
