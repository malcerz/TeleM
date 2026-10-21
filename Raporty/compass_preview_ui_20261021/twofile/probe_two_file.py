"""Compass diagnostics for the two-file project GX010389+GX010390 (+FIT)."""
import json, os, sys, time
from pathlib import Path
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from PySide6.QtWidgets import QApplication
VIDEOS = [r"F:\GoPro\2026-10-20\GX010389.MP4", r"F:\GoPro\2026-10-20\GX010390.MP4"]
FIT = r"F:\GoPro\2026-10-20\2026-10-20_15-04-03.fit"
app = QApplication([])
from src.gui.qt.controller import AppController
from src.gui.qt.main_window import MainWindow
ctl = AppController(); win = MainWindow(); win.set_controller(ctl)
ctl._on_files_selected(VIDEOS, "", FIT)
t0 = time.time()
while not ctl.project_ready and time.time() - t0 < 600:
    app.processEvents(); time.sleep(0.02)
for _ in range(100): app.processEvents(); time.sleep(0.01)
tm = ctl.telemetry
res = tm._compass_result
diag = json.loads(json.dumps(res.diagnostics if res else {}, default=str))
def slim(o):
    if isinstance(o, dict): return {k: slim(v) for k, v in o.items() if k not in ("attempts",) or True}
    if isinstance(o, list) and len(o) > 12: return o[:12] + ["..."]
    if isinstance(o, list): return [slim(x) for x in o]
    return o
tl = ctl.video_timeline
clips = [{"path": str(c.path), "global_start": c.global_start_s, "duration": c.duration_s,
          "abs_start": str(c.absolute_start_dt)} for c in tl.clips]
from src.telemetry_compass_hybrid import timestamp
samples = []
for t in [0, 30, 60, 120, 180, 240, 300, 400, 500, tl.clips[0].duration_s - 5, tl.clips[0].duration_s + 5, tl.clips[0].duration_s + 120]:
    dt = ctl._resolve_preview_time(float(t))["absolute_dt"]
    samples.append({"t": round(t, 1), "abs": str(dt), "hybrid": res.lookup(dt) if res else None,
                    "fit_heading": tm.resolve_value("heading", dt, source="fit")})
fit_track = tm.fit_gps_track or []
out = {"clips": clips, "status": tm._compass_status, "diagnostics": slim(diag), "samples": samples,
       "fit_track_first": str(fit_track[0][0]) if fit_track else None, "fit_track_last": str(fit_track[-1][0]) if fit_track else None,
       "gyro_n": len(tm.gyroscope_samples or []), "gyro_first": str((tm.gyroscope_samples or [[None]])[0][0])}
Path(sys.argv[1]).write_text(json.dumps(out, indent=1, default=str), encoding="utf-8")
print(json.dumps({k: out[k] for k in ("clips", "status", "samples", "fit_track_first", "fit_track_last", "gyro_n", "gyro_first")}, indent=1, default=str))
