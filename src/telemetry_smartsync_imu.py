"""SmartSync IMU — camera IMU ↔ FIT/GPX time alignment without camera GPS.

Used for cameras whose clock is not GPS-disciplined (DJI Action, GoPro without
a GPS fix).  The camera records gyroscope/accelerometer samples on its own
clock; the activity file records position/speed on GPS time.  The offset is
found by correlating orientation-independent motion signals:

* yaw rate — camera gyro projected on the (low-passed) gravity direction,
  compared with the time derivative of the unwrapped GPS course.  Course is
  only trusted above ``MIN_COURSE_SPEED_MS``; slower samples are masked.
* horizontal acceleration magnitude — camera accel with gravity removed,
  compared with |dv/dt| of the activity speed.

All filters are centred (zero phase) so they do not bias the offset.  The
correlation is a masked normalised cross-correlation computed with FFTs, so
gaps (no GPS fix, standstill) never contribute.  Raw accelerometer axes are
never compared with speed directly and the camera mounting is unknown, so
the yaw sign is estimated rather than assumed.

Offset contract (shared with the rest of TeleM)::

    telemetry_time = video_start_time + video_position + offset_s

``offset_s`` is therefore the value of ``telemetry_sync_offset_s`` that makes
the activity data match the video.
"""

from __future__ import annotations

import math
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Optional, Sequence

import numpy as np

ANALYSIS_HZ = 10.0
IMU_RESAMPLE_HZ = 50.0
MIN_COURSE_SPEED_MS = 2.0          # below ~7 km/h GPS course is noise
MAX_FIT_GAP_S = 6.0                # longer recording gaps are masked
MIN_OVERLAP_S = 20.0
TURN_EVENT_RAD_S = 0.12            # ~7 deg/s sustained
ACCEL_EVENT_MS2 = 0.5
EVENT_MIN_S = 1.0
EVENT_MATCH_TOL_S = 1.5
PEAK_EXCLUSION_S = 4.0
DEFAULT_SEARCH_STAGES_S: tuple[Optional[float], ...] = (120.0, 900.0, None)  # None = whole activity

# Acceptance used to decide automatic application (all must hold).  Chosen
# from real GoPro-without-GPS-fix data: the true match scored 0.50 / ratio
# 2.36 / z 7.1 / 7 events, deliberately wrong activity segments at most
# 0.37 / 1.62 / 4.2 / 4 (see Raporty/RAPORT_SMARTSYNC_DJI_IMU_RESTORE.md).
HIGH_MIN_SCORE = 0.30
HIGH_MIN_PEAK_RATIO = 1.8
HIGH_MIN_PEAK_Z = 5.0
HIGH_MIN_EVENTS = 4
HIGH_MIN_YAW_NCC = 0.4             # when the activity has positions
MEDIUM_MIN_SCORE = 0.20
MEDIUM_MIN_PEAK_RATIO = 1.12
MEDIUM_MIN_EVENTS = 2
HALVES_MAX_DISAGREEMENT_S = 0.5
HALF_MIN_S = 120.0

CHANNEL_WEIGHTS = {"yaw": 1.0, "accel": 0.5}


class SmartSyncCancelled(Exception):
    pass


@dataclass
class SmartSyncResult:
    status: str                      # OK | AMBIGUOUS | NO_IMU | NO_FIT_MOTION | NO_OVERLAP | INSUFFICIENT_EVENTS | ERROR
    offset_s: Optional[float] = None
    confidence: float = 0.0          # 0..1
    confidence_level: str = "none"   # high | medium | low | none
    method: str = "imu_yaw_accel_xcorr"
    events: int = 0                  # matched characteristic events
    camera_events: int = 0
    fit_events: int = 0
    peak_score: float = 0.0
    second_peak_score: float = 0.0
    second_peak_offset_s: Optional[float] = None
    peak_ratio: float = 0.0
    peak_z: float = 0.0
    yaw_sign: int = 0
    channels: dict[str, float] = field(default_factory=dict)
    halves_offsets_s: list[float] = field(default_factory=list)
    halves_consistent: Optional[bool] = None
    drift_ppm: Optional[float] = None
    search_range_s: tuple[float, float] = (0.0, 0.0)
    prior_offset_s: float = 0.0
    analysed_s: float = 0.0
    elapsed_ms: float = 0.0
    message: str = ""

    @property
    def reliable(self) -> bool:
        return self.status == "OK" and self.confidence_level == "high"

    def to_dict(self) -> dict[str, Any]:
        out = asdict(self)
        out["search_range_s"] = list(self.search_range_s)
        return out


# ---------------------------------------------------------------------------
# Signal helpers
# ---------------------------------------------------------------------------

def _box(x: np.ndarray, n: int) -> np.ndarray:
    """Centred moving average along axis 0 (edge-normalised)."""
    n = int(max(1, n))
    if n <= 1 or len(x) == 0:
        return np.asarray(x, dtype=np.float64)
    if n % 2 == 0:
        n += 1
    x = np.asarray(x, dtype=np.float64)
    kernel = np.ones(n)
    if x.ndim == 1:
        num = np.convolve(x, kernel, mode="same")
        den = np.convolve(np.ones(len(x)), kernel, mode="same")
        return num / den
    return np.column_stack([_box(x[:, i], n) for i in range(x.shape[1])])


def _masked_box(x: np.ndarray, w: np.ndarray, n: int) -> tuple[np.ndarray, np.ndarray]:
    """Centred moving average that ignores masked samples."""
    n = int(max(1, n))
    if n % 2 == 0:
        n += 1
    kernel = np.ones(n)
    xw = np.where(w > 0, x, 0.0)
    num = np.convolve(xw, kernel, mode="same")
    den = np.convolve((w > 0).astype(np.float64), kernel, mode="same")
    out = np.where(den > 0, num / np.maximum(den, 1e-12), 0.0)
    return out, (den >= max(1.0, 0.5 * n)).astype(np.float64)


def _sorted_unique(arr: np.ndarray) -> np.ndarray:
    arr = np.asarray(arr, dtype=np.float64)
    arr = arr[np.all(np.isfinite(arr), axis=1)]
    if len(arr) == 0:
        return arr
    arr = arr[np.argsort(arr[:, 0], kind="stable")]
    keep = np.concatenate([[True], np.diff(arr[:, 0]) > 0])
    return arr[keep]


def _event_segments(x: np.ndarray, w: np.ndarray, thr: float, fs: float) -> list[tuple[float, int]]:
    """Return (centre_s, sign) of sustained |x| > thr segments."""
    active = (np.abs(x) > thr) & (w > 0)
    out: list[tuple[float, int]] = []
    i = 0
    n = len(active)
    min_len = int(EVENT_MIN_S * fs)
    while i < n:
        if not active[i]:
            i += 1
            continue
        j = i
        while j < n and active[j] and np.sign(x[j]) == np.sign(x[i]):
            j += 1
        if j - i >= min_len:
            seg = slice(i, j)
            k = i + int(np.argmax(np.abs(x[seg])))
            out.append((k / fs, int(np.sign(x[k]))))
        i = max(j, i + 1)
    return out


# ---------------------------------------------------------------------------
# Signal construction
# ---------------------------------------------------------------------------

@dataclass
class _Signals:
    t0: float                         # seconds (relative to video start) of sample 0
    fs: float
    channels: dict[str, tuple[np.ndarray, np.ndarray]]  # name -> (values, weights)

    @property
    def length(self) -> int:
        for v, _ in self.channels.values():
            return len(v)
        return 0


def camera_signals(
    gyro: np.ndarray,
    accel: Optional[np.ndarray],
    video_t0_epoch: float,
    window_s: Optional[tuple[float, float]] = None,
    fs: float = ANALYSIS_HZ,
) -> Optional[_Signals]:
    """Orientation-independent yaw rate and horizontal accel from camera IMU.

    ``gyro``/``accel`` rows are ``[t_epoch_s, x, y, z]`` (rad/s, any accel
    unit).  Times are converted to seconds relative to ``video_t0_epoch``.
    """
    if gyro is None or len(gyro) < 50:
        return None
    gyro = _sorted_unique(gyro)
    gyro[:, 0] -= video_t0_epoch
    have_accel = accel is not None and len(accel) >= 50
    if have_accel:
        accel = _sorted_unique(accel)
        accel[:, 0] -= video_t0_epoch
    lo, hi = gyro[0, 0], gyro[-1, 0]
    if have_accel:
        lo, hi = max(lo, accel[0, 0]), min(hi, accel[-1, 0])
    if window_s is not None:
        lo, hi = max(lo, window_s[0]), min(hi, window_s[1])
    if hi - lo < MIN_OVERLAP_S:
        return None

    grid_hi = np.arange(lo, hi, 1.0 / IMU_RESAMPLE_HZ)
    G = np.column_stack([np.interp(grid_hi, gyro[:, 0], gyro[:, i]) for i in (1, 2, 3)])
    # Camera gaps (e.g. dropped IMU blocks) — mask samples far from any real sample.
    idx = np.clip(np.searchsorted(gyro[:, 0], grid_hi), 1, len(gyro) - 1)
    gap = np.minimum(np.abs(gyro[idx, 0] - grid_hi), np.abs(gyro[idx - 1, 0] - grid_hi))
    valid_hi = (gap < 0.25).astype(np.float64)

    if have_accel:
        A = np.column_stack([np.interp(grid_hi, accel[:, 0], accel[:, i]) for i in (1, 2, 3)])
        g_dir = _box(A, int(2.0 * IMU_RESAMPLE_HZ))
    else:
        # Without an accelerometer, the dominant low-frequency rotation axis is
        # the best available vertical proxy — usable, but weaker.
        A = None
        g_dir = np.tile(np.mean(np.abs(G), axis=0), (len(G), 1))
    norm = np.linalg.norm(g_dir, axis=1, keepdims=True)
    g_hat = g_dir / np.maximum(norm, 1e-9)
    yaw_hi = np.sum(G * g_hat, axis=1)

    step = int(round(IMU_RESAMPLE_HZ / fs))
    # Same centred bandwidth as the activity side (2 s trajectory smoothing
    # followed by a 1 s average) — zero phase, so no lag is introduced.
    yaw_lp = _box(_box(yaw_hi, int(1.0 * IMU_RESAMPLE_HZ)), int(2.0 * IMU_RESAMPLE_HZ))[::step]
    w = (_box(valid_hi, step)[::step] > 0.8).astype(np.float64)
    channels = {"yaw": (yaw_lp, w.copy())}

    if A is not None:
        a_s = _box(A, int(0.5 * IMU_RESAMPLE_HZ))
        g_long = _box(A, int(4.0 * IMU_RESAMPLE_HZ))
        gl_hat = g_long / np.maximum(np.linalg.norm(g_long, axis=1, keepdims=True), 1e-9)
        a_par = np.sum(a_s * gl_hat, axis=1, keepdims=True)
        a_h = np.linalg.norm(a_s - a_par * gl_hat, axis=1)
        ah_lp = _box(_box(a_h, int(1.0 * IMU_RESAMPLE_HZ)), int(2.0 * IMU_RESAMPLE_HZ))[::step]
        channels["accel"] = (ah_lp, w.copy())
    return _Signals(t0=float(grid_hi[0]), fs=fs, channels=channels)


def activity_signals(
    t_rel_s: np.ndarray,
    speed_kmh: Optional[np.ndarray],
    lat: Optional[np.ndarray],
    lon: Optional[np.ndarray],
    fs: float = ANALYSIS_HZ,
) -> Optional[_Signals]:
    """GPS-course yaw rate and |dv/dt| from FIT/GPX samples.

    ``t_rel_s`` are activity sample times relative to the video start under
    the current (pre-correction) alignment.
    """
    t = np.asarray(t_rel_s, dtype=np.float64)
    if len(t) < 10:
        return None
    order = np.argsort(t, kind="stable")
    t = t[order]
    keep = np.concatenate([[True], np.diff(t) > 0])
    t = t[keep]

    def _col(a):
        if a is None:
            return np.full(len(t), np.nan)
        return np.asarray(a, dtype=np.float64)[order][keep]

    spd = _col(speed_kmh) / 3.6
    la, lo = _col(lat), _col(lon)
    grid = np.arange(t[0], t[-1], 1.0 / fs)
    if len(grid) < fs * MIN_OVERLAP_S:
        return None

    def _interp_masked(values: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        ok = np.isfinite(values)
        if ok.sum() < 5:
            return np.zeros(len(grid)), np.zeros(len(grid))
        tv, vv = t[ok], values[ok]
        out = np.interp(grid, tv, vv)
        idx = np.clip(np.searchsorted(tv, grid), 1, len(tv) - 1)
        span = tv[idx] - tv[idx - 1]
        inside = (grid >= tv[0]) & (grid <= tv[-1]) & (span <= MAX_FIT_GAP_S)
        return out, inside.astype(np.float64)

    channels: dict[str, tuple[np.ndarray, np.ndarray]] = {}
    pos_ok = np.isfinite(la) & np.isfinite(lo)
    v_pos = None
    if pos_ok.sum() >= 10:
        lat0 = float(np.nanmedian(la[pos_ok]))
        lon0 = float(np.nanmedian(lo[pos_ok]))
        R = 6371000.0
        x = np.radians(lo - lon0) * math.cos(math.radians(lat0)) * R
        y = np.radians(la - lat0) * R
        xg, wx = _interp_masked(x)
        yg, wy = _interp_masked(y)
        wpos = wx * wy
        # Centred 2 s smoothing of the trajectory before differentiating.
        n2 = int(2.0 * fs)
        xs, wpos_s = _masked_box(xg, wpos, n2)
        ys, _ = _masked_box(yg, wpos, n2)
        vx = np.gradient(xs) * fs
        vy = np.gradient(ys) * fs
        v_pos = np.hypot(vx, vy)
        course = np.unwrap(np.arctan2(vx, vy))
        yaw = np.gradient(course) * fs
        w_yaw = wpos_s * (v_pos > MIN_COURSE_SPEED_MS)
        yaw, w_yaw = _masked_box(np.where(w_yaw > 0, yaw, 0.0), w_yaw, int(1.0 * fs))
        # The derivative of course is meaningless across masked holes.
        w_yaw = w_yaw * (np.abs(yaw) < 2.0)
        channels["yaw"] = (yaw, w_yaw)

    speed_src = spd if np.isfinite(spd).sum() >= 10 else None
    if speed_src is not None:
        vg, wv = _interp_masked(speed_src)
    elif v_pos is not None:
        vg, wv = v_pos, channels["yaw"][1]
    else:
        vg, wv = None, None
    if vg is not None:
        vs, wvs = _masked_box(vg, wv, int(2.0 * fs))
        acc = np.abs(np.gradient(vs) * fs)
        acc, wacc = _masked_box(acc, wvs, int(1.0 * fs))
        channels["accel"] = (acc, wacc)
    if not channels:
        return None
    return _Signals(t0=float(grid[0]), fs=fs, channels=channels)


# ---------------------------------------------------------------------------
# Masked normalised cross-correlation
# ---------------------------------------------------------------------------

def _xcorr_full(a: np.ndarray, b: np.ndarray, nfft: int) -> np.ndarray:
    """r[k] = sum_j a[j] * b[k + j] for k in [-(len(a)-1), len(b)-1]."""
    fa = np.fft.rfft(a[::-1], nfft)
    fb = np.fft.rfft(b, nfft)
    full = np.fft.irfft(fa * fb, nfft)[: len(a) + len(b) - 1]
    return full  # index i corresponds to k = i - (len(a) - 1)


def masked_ncc(
    c: np.ndarray, wc: np.ndarray, f: np.ndarray, wf: np.ndarray, min_overlap: int,
) -> tuple[np.ndarray, np.ndarray]:
    """Return (ncc[k], overlap_count[k]) for k = i - (len(c)-1)."""
    nfft = 1
    while nfft < len(c) + len(f):
        nfft *= 2
    wc = (wc > 0).astype(np.float64)
    wf = (wf > 0).astype(np.float64)
    c0 = np.where(wc > 0, c, 0.0)
    f0 = np.where(wf > 0, f, 0.0)
    n = np.rint(_xcorr_full(wc, wf, nfft))
    sc = _xcorr_full(c0, wf, nfft)
    sf = _xcorr_full(wc, f0, nfft)
    scc = _xcorr_full(c0 * c0, wf, nfft)
    sff = _xcorr_full(wc, f0 * f0, nfft)
    scf = _xcorr_full(c0, f0, nfft)
    with np.errstate(invalid="ignore", divide="ignore"):
        num = scf - sc * sf / n
        vc = scc - sc * sc / n
        vf = sff - sf * sf / n
        ncc = num / np.sqrt(np.maximum(vc, 0) * np.maximum(vf, 0))
    bad = (n < min_overlap) | (vc <= 1e-12) | (vf <= 1e-12) | ~np.isfinite(ncc)
    ncc = np.where(bad, np.nan, np.clip(ncc, -1.0, 1.0))
    return ncc, n


# ---------------------------------------------------------------------------
# Estimation
# ---------------------------------------------------------------------------

def _combined_scores(cam: _Signals, act: _Signals, min_overlap: int):
    """Per-lag combined score for both yaw signs; offsets for each lag."""
    per: dict[str, np.ndarray] = {}
    for name in CHANNEL_WEIGHTS:
        if name in cam.channels and name in act.channels:
            c, wc = cam.channels[name]
            f, wf = act.channels[name]
            per[name], _ = masked_ncc(c, wc, f, wf, min_overlap)
    if not per:
        return None
    nc = cam.length
    some = next(iter(per.values()))
    k = np.arange(len(some)) - (nc - 1)
    # Camera sample j at video time cam.t0 + j/fs matches activity sample k+j
    # at telemetry time act.t0 + (k+j)/fs  =>  offset = act.t0 - cam.t0 + k/fs
    offsets = (act.t0 - cam.t0) + k / cam.fs
    # A channel missing at a lag contributes zero instead of being dropped
    # from the denominator, so lags supported by fewer signals cannot win
    # merely because a weaker single-channel correlation looks high.
    total_w = sum(CHANNEL_WEIGHTS[name] for name, ncc in per.items() if np.isfinite(ncc).any())
    combos = {}
    for sign in (1, -1):
        num = np.zeros(len(offsets))
        any_ok = np.zeros(len(offsets), dtype=bool)
        for name, ncc in per.items():
            s = sign if name == "yaw" else 1
            ok = np.isfinite(ncc)
            num[ok] += CHANNEL_WEIGHTS[name] * s * ncc[ok]
            any_ok |= ok
        combos[sign] = np.where(any_ok, num / max(total_w, 1e-9), np.nan)
    return offsets, combos, per


def _peak_stats(offsets: np.ndarray, score: np.ndarray, sel: np.ndarray, fs: float):
    s = np.where(sel, score, np.nan)
    if not np.isfinite(s).any():
        return None
    i = int(np.nanargmax(s))
    best = float(s[i])
    # Sub-sample parabolic refinement.
    delta = 0.0
    if 0 < i < len(s) - 1 and np.isfinite(s[i - 1]) and np.isfinite(s[i + 1]):
        den = s[i - 1] - 2 * s[i] + s[i + 1]
        if den < 0:
            delta = float(np.clip(0.5 * (s[i - 1] - s[i + 1]) / den, -0.5, 0.5))
    best_off = float(offsets[i] + delta / fs)
    # Second-best local maximum outside the exclusion window.
    far = np.abs(offsets - offsets[i]) > PEAK_EXCLUSION_S
    cand = np.where(far & np.isfinite(s), s, -np.inf)
    local = np.zeros(len(s), dtype=bool)
    local[1:-1] = (cand[1:-1] >= cand[:-2]) & (cand[1:-1] >= cand[2:]) & np.isfinite(cand[1:-1])
    second = float(np.max(cand[local])) if local.any() else float("nan")
    second_off = float(offsets[local][np.argmax(cand[local])]) if local.any() else None
    vals = s[np.isfinite(s)]
    med = float(np.median(vals))
    mad = float(np.median(np.abs(vals - med))) * 1.4826
    z = (best - med) / mad if mad > 1e-9 else float("inf")
    return i, best, best_off, second, second_off, z


def _matched_events(cam: _Signals, act: _Signals, offset: float, yaw_sign: int):
    """Count characteristic events present in both streams after alignment."""
    fs = cam.fs
    cam_ev: list[tuple[float, int, str]] = []
    act_ev: list[tuple[float, int, str]] = []
    if "yaw" in cam.channels and "yaw" in act.channels:
        cy, cw = cam.channels["yaw"]
        for tc, sg in _event_segments(cy, cw, TURN_EVENT_RAD_S, fs):
            cam_ev.append((cam.t0 + tc, sg * yaw_sign, "turn"))
        ay, aw = act.channels["yaw"]
        for ta, sg in _event_segments(ay, aw, TURN_EVENT_RAD_S, fs):
            act_ev.append((act.t0 + ta - offset, sg, "turn"))
    if "accel" in act.channels:
        aa, aw = act.channels["accel"]
        for ta, _sg in _event_segments(aa, aw, ACCEL_EVENT_MS2, fs):
            act_ev.append((act.t0 + ta - offset, 1, "accel"))
        if "accel" in cam.channels:
            ca, cw = cam.channels["accel"]
            valid = ca[cw > 0]
            if len(valid):
                med = float(np.median(valid))
                mad = float(np.median(np.abs(valid - med))) * 1.4826
                thr_dev = max(2.5 * mad, 1e-6)
                for tc, _sg in _event_segments(ca - med, cw, thr_dev, fs):
                    cam_ev.append((cam.t0 + tc, 1, "accel"))
    cam_lo = cam.t0
    cam_hi = cam.t0 + cam.length / fs
    act_in = [e for e in act_ev if cam_lo <= e[0] <= cam_hi]
    used: set[int] = set()
    matched = 0
    for tc, sg, kind in cam_ev:
        for j, (ta, sa, ka) in enumerate(act_in):
            if j in used or ka != kind:
                continue
            if abs(ta - tc) <= EVENT_MATCH_TOL_S and (kind != "turn" or sa == sg):
                used.add(j)
                matched += 1
                break
    return matched, len(cam_ev), len(act_in)


def _slice_signals(sig: _Signals, lo_idx: int, hi_idx: int) -> _Signals:
    return _Signals(
        t0=sig.t0 + lo_idx / sig.fs, fs=sig.fs,
        channels={k: (v[lo_idx:hi_idx], w[lo_idx:hi_idx]) for k, (v, w) in sig.channels.items()},
    )


def _halves(cam: _Signals, act: _Signals, around: float, yaw_sign: int, min_overlap: int):
    n = cam.length
    # Each half needs enough events for its own estimate; shorter halves are
    # dominated by estimation noise rather than clock drift.
    if n < int(2 * HALF_MIN_S * cam.fs):
        return [], None
    out = []
    for lo, hi in ((0, n // 2), (n // 2, n)):
        sub = _slice_signals(cam, lo, hi)
        res = _combined_scores(sub, act, min(min_overlap, int(0.6 * (hi - lo))))
        if res is None:
            return [], None
        offsets, combos, _ = res
        sel = np.abs(offsets - around) <= 5.0
        _, _, per = res
        score = per["yaw"] * yaw_sign if "yaw" in per else combos[yaw_sign]
        st = _peak_stats(offsets, score, sel, cam.fs)
        if st is None or st[1] < 0.3:
            return out, False if out else None
        out.append(st[2])
    return out, abs(out[0] - out[1]) <= HALVES_MAX_DISAGREEMENT_S


def estimate_offset_from_signals(
    cam: _Signals,
    act: _Signals,
    *,
    prior_offset_s: float = 0.0,
    search_stages_s: Sequence[Optional[float]] = DEFAULT_SEARCH_STAGES_S,
    cancel: Optional[Callable[[], bool]] = None,
    progress: Optional[Callable[[str], None]] = None,
) -> SmartSyncResult:
    t_start = time.perf_counter()
    min_overlap = int(max(MIN_OVERLAP_S, 0.5 * cam.length / cam.fs) * cam.fs)
    res = _combined_scores(cam, act, min_overlap)
    if res is None:
        return SmartSyncResult(status="NO_FIT_MOTION", message="Brak wspólnych sygnałów ruchu (kurs/prędkość) w FIT/GPX.")
    offsets, combos, per = res
    if not any(np.isfinite(c).any() for c in combos.values()):
        return SmartSyncResult(status="NO_OVERLAP", prior_offset_s=prior_offset_s,
                               message="Nagranie nie nakłada się z ruchem w aktywności w żadnym badanym przesunięciu.")

    full_lo = float(np.nanmin(offsets[np.isfinite(combos[1])])) if np.isfinite(combos[1]).any() else float(offsets[0])
    full_hi = float(np.nanmax(offsets[np.isfinite(combos[1])])) if np.isfinite(combos[1]).any() else float(offsets[-1])
    result: Optional[SmartSyncResult] = None
    rank = {"high": 3, "medium": 2, "low": 1, "none": 0}
    for stage in search_stages_s:
        if cancel is not None and cancel():
            raise SmartSyncCancelled()
        lo, hi = (full_lo, full_hi) if stage is None else (prior_offset_s - stage, prior_offset_s + stage)
        sel = (offsets >= lo) & (offsets <= hi)
        if progress is not None:
            progress(f"zakres ±{stage:.0f} s" if stage is not None else "cała aktywność")
        best = None
        for sign in (1, -1):
            st = _peak_stats(offsets, combos[sign], sel, cam.fs)
            if st is not None and (best is None or st[1] > best[1][1]):
                best = (sign, st)
        if best is None:
            continue
        sign, (i, score, off, second, second_off, z) = best
        # The combined score disambiguates the peak; its exact position is
        # taken from the yaw channel alone, since the accel-magnitude channel
        # is broader and can pull the maximum by a few tenths of a second.
        if "yaw" in per:
            near = np.abs(offsets - off) <= 2.0
            yst = _peak_stats(offsets, per["yaw"] * sign, near, cam.fs)
            if yst is not None and yst[1] >= 0.3:
                off = yst[2]
                i = yst[0]
        matched, cam_n, act_n = _matched_events(cam, act, off, sign)
        halves, consistent = _halves(cam, act, off, sign, min_overlap)
        drift = None
        if len(halves) == 2:
            dt_mid = 0.5 * cam.length / cam.fs
            drift = (halves[1] - halves[0]) / dt_mid * 1e6
        ratio = score / second if np.isfinite(second) and second > 1e-6 else float("inf")
        yaw_at_peak = per["yaw"][i] * sign if "yaw" in per else float("nan")
        # Course-based yaw is the primary, event-rich signal; an accel-only
        # peak is never trusted for automatic application.
        yaw_ok = "yaw" in per and np.isfinite(yaw_at_peak) and yaw_at_peak >= HIGH_MIN_YAW_NCC
        level = "low"
        if (score >= HIGH_MIN_SCORE and ratio >= HIGH_MIN_PEAK_RATIO and z >= HIGH_MIN_PEAK_Z
                and matched >= HIGH_MIN_EVENTS and consistent is not False and yaw_ok):
            level = "high"
        elif score >= MEDIUM_MIN_SCORE and ratio >= MEDIUM_MIN_PEAK_RATIO and matched >= MEDIUM_MIN_EVENTS:
            level = "medium"
        conf = float(np.clip(min(
            (score - 0.2) / 0.5,
            (min(ratio, 3.0) - 1.0) / 0.6,
            matched / 5.0,
        ), 0.0, 1.0))
        if consistent is False:
            conf *= 0.5
        channels = {}
        for name, ncc in per.items():
            v = ncc[i]
            channels[name] = float(v * (sign if name == "yaw" else 1)) if np.isfinite(v) else float("nan")
        status = "OK" if level == "high" else ("INSUFFICIENT_EVENTS" if matched < MEDIUM_MIN_EVENTS else "AMBIGUOUS")
        if result is not None and (
            rank[level] < rank[result.confidence_level]
            or (rank[level] == rank[result.confidence_level] and score <= result.peak_score + 0.05)
        ):
            # A wider range replaces a narrower result only when it is more
            # certain, or equally certain with a clearly better peak.
            continue
        result = SmartSyncResult(
            status=status, offset_s=round(off, 3), confidence=round(conf, 3), confidence_level=level,
            events=matched, camera_events=cam_n, fit_events=act_n,
            peak_score=round(score, 4), second_peak_score=round(second, 4) if np.isfinite(second) else float("nan"),
            second_peak_offset_s=second_off, peak_ratio=round(ratio, 3) if np.isfinite(ratio) else float("inf"),
            peak_z=round(z, 2) if np.isfinite(z) else float("inf"), yaw_sign=sign, channels=channels,
            halves_offsets_s=[round(h, 3) for h in halves], halves_consistent=consistent,
            drift_ppm=round(drift, 1) if drift is not None else None,
            search_range_s=(round(max(lo, full_lo), 1), round(min(hi, full_hi), 1)),
            prior_offset_s=prior_offset_s, analysed_s=round(cam.length / cam.fs, 1),
        )
        if level == "high":
            break
    if result is None:
        result = SmartSyncResult(status="NO_OVERLAP", prior_offset_s=prior_offset_s,
                                 message="Brak nakładania się nagrania z aktywnością.")
    result.elapsed_ms = round((time.perf_counter() - t_start) * 1000.0, 1)
    if not result.message:
        result.message = describe(result)
    return result


def describe(r: SmartSyncResult) -> str:
    if r.status == "OK":
        return (f"Dopasowano: {r.offset_s:+.2f} s (pewność {r.confidence:.0%}, "
                f"zdarzenia {r.events}, korelacja {r.peak_score:.2f}, jednoznaczność ×{r.peak_ratio:.2f}).")
    if r.status in ("AMBIGUOUS", "INSUFFICIENT_EVENTS") and r.offset_s is not None:
        why = "za mało charakterystycznych zdarzeń" if r.status == "INSUFFICIENT_EVENTS" else "dopasowanie niejednoznaczne"
        return (f"Propozycja {r.offset_s:+.2f} s NIE została zastosowana — {why} "
                f"(pewność {r.confidence:.0%}, zdarzenia {r.events}, korelacja {r.peak_score:.2f}, "
                f"jednoznaczność ×{r.peak_ratio:.2f}). Użyj regulacji ręcznej.")
    return r.message or r.status


def estimate_imu_offset(
    *,
    gyro: Optional[np.ndarray],
    accel: Optional[np.ndarray],
    video_t0_epoch: float,
    fit_t_epoch: np.ndarray,
    fit_speed_kmh: Optional[np.ndarray],
    fit_lat: Optional[np.ndarray],
    fit_lon: Optional[np.ndarray],
    window_s: Optional[tuple[float, float]] = None,
    prior_offset_s: float = 0.0,
    search_stages_s: Sequence[Optional[float]] = DEFAULT_SEARCH_STAGES_S,
    cancel: Optional[Callable[[], bool]] = None,
    progress: Optional[Callable[[str], None]] = None,
) -> SmartSyncResult:
    """Estimate ``telemetry_sync_offset_s`` from camera IMU and activity data.

    Activity times must already include any base alignment (timezone etc.);
    the returned offset is relative to that alignment.
    """
    t_start = time.perf_counter()
    if gyro is None or len(gyro) < 50:
        return SmartSyncResult(status="NO_IMU", message="Nagranie nie zawiera danych żyroskopu (IMU) — SmartSync IMU niedostępny.")
    if fit_t_epoch is None or len(fit_t_epoch) < 10:
        return SmartSyncResult(status="NO_FIT_MOTION", message="Brak wczytanej aktywności FIT/GPX z danymi ruchu.")
    if progress is not None:
        progress("przygotowanie sygnałów IMU")
    cam = camera_signals(gyro, accel, video_t0_epoch, window_s=window_s)
    if cam is None:
        return SmartSyncResult(status="NO_IMU", message="Zbyt krótki lub niepełny zapis IMU w nagraniu.")
    if cancel is not None and cancel():
        raise SmartSyncCancelled()
    if progress is not None:
        progress("przygotowanie sygnałów FIT/GPX")
    act = activity_signals(np.asarray(fit_t_epoch, dtype=np.float64) - video_t0_epoch,
                           fit_speed_kmh, fit_lat, fit_lon, fs=cam.fs)
    if act is None:
        return SmartSyncResult(status="NO_FIT_MOTION", message="FIT/GPX nie zawiera pozycji ani prędkości potrzebnych do SmartSync.")
    result = estimate_offset_from_signals(
        cam, act, prior_offset_s=prior_offset_s, search_stages_s=search_stages_s,
        cancel=cancel, progress=progress,
    )
    result.elapsed_ms = round((time.perf_counter() - t_start) * 1000.0, 1)
    return result
