"""Capture GX010389 calibration inputs and evaluate every window to clip end."""
import json, os, sys, time, tempfile
from pathlib import Path
import numpy as np
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from PySide6.QtWidgets import QApplication
app = QApplication([])
from src.gui.qt.controller import AppController
from src.gui.qt.main_window import MainWindow
import src.telemetry_compass_hybrid as H
ctl = AppController(); win = MainWindow(); win.set_controller(ctl)
ctl._on_files_selected([r"F:\GoPro\2026-10-20\GX010389.MP4", r"F:\GoPro\2026-10-20\GX010390.MP4"], "", r"F:\GoPro\2026-10-20\2026-10-20_15-04-03.fit")
t0 = time.time()
while not ctl.project_ready and time.time() - t0 < 600:
    app.processEvents(); time.sleep(0.02)
captured = []
orig = H.calibrate_segment
def spy(imu, obs, cfg):
    captured.append((imu.copy(), obs.copy()))
    return orig(imu, obs, cfg)
H.calibrate_segment = spy
cfg = H.parameters(ctl.layout["indicators"]["compass"])
H.prepare_manager_compass(H.snapshot_manager(ctl.telemetry), cfg, cache_dir=tempfile.mkdtemp())
imu, obs = captured[0]
clip_start = imu[0, 0]
rel = np.rad2deg(np.unwrap(np.deg2rad(imu[:, 1])))
good = obs[(obs[:, 0] >= imu[0, 0]) & (obs[:, 0] <= imu[-1, 0])]
moving = good[(good[:, 3] > 0) & np.isfinite(good[:, 1]) & (good[:, 2] >= 8.0)]
print("clip span s", round(imu[-1, 0] - imu[0, 0], 1), "obs", len(good), "moving>=8", len(moving),
      "first good obs at s", round(good[good[:, 3] > 0][0, 0] - clip_start, 1) if len(good) else None)
res = {"windows": []}
for start_off in (35, 40, 45, 50, 60, 75):   # seconds after the first good fix
    first = good[good[:, 3] > 0][0, 0]
    for end in ("clip_end",):
        sel = moving[(moving[:, 0] >= first + start_off)]
        if len(sel) < 20:
            continue
        r = np.interp(sel[:, 0], imu[:, 0], rel)
        for drift in (True, False):
            model, reason = H._fit_anchor(sel[:, 0], r, sel[:, 1], drift_enabled=drift, target_start=clip_start)
            delta = H.wrap180(sel[:, 1] - r)
            c = np.rad2deg(np.angle(np.mean(np.exp(1j * np.deg2rad(delta)))))
            p95_raw = float(np.percentile(abs(H.wrap180(delta - c)), 95))
            row = {"start_after_fix_s": start_off, "drift": drift, "samples": len(sel), "span_s": round(sel[-1, 0] - sel[0, 0], 1),
                   "raw_offset_p95": round(p95_raw, 2), "status": reason,
                   "p95": model and round(model["error_p95_deg"], 2), "median": model and round(model["error_median_deg"], 2),
                   "back_unc": model and round(model["backward_uncertainty_deg"], 2), "turn_corr": model and model["turn_correlation"]}
            res["windows"].append(row); print(row)
# residual timeline at default anchor (stab 30)
sel = moving[moving[:, 0] >= good[good[:, 3] > 0][0, 0] + 35]
r = np.interp(sel[:, 0], imu[:, 0], rel)
delta = H.wrap180(sel[:, 1] - r); c = np.rad2deg(np.angle(np.mean(np.exp(1j * np.deg2rad(delta)))))
res["residual_timeline"] = [(round(t - clip_start, 1), round(float(e), 1), round(float(s), 1)) for t, e, s in zip(sel[:, 0], H.wrap180(delta - c), sel[:, 2])]
print("residuals (t_in_clip, err_deg, speed):", res["residual_timeline"])
Path(sys.argv[1]).write_text(json.dumps(res, indent=1, default=str), encoding="utf-8")
