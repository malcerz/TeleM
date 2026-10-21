"""Probe: real GUI controller + the user's real def_layout.json (read-only).

Records the heading actually used at every stage of the Preview path for
GX010380.MP4 + 2026-10-16_06-22-14.fit at the times from the task.  The
layout is NOT overridden: whatever compass mode the user's layout holds is
what is measured (that is the whole point of this probe).

Usage:  python probe_real_layout.py <out_json> [--layout PATH]
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from PySide6.QtWidgets import QApplication  # noqa: E402

VIDEO = r"F:\GoPro\2026-10-16\GX010380.MP4"
FIT = r"F:\GoPro\2026-10-16\2026-10-16_06-22-14.fit"
TIMES = [0, 10, 30, 60, 79, 120, 150, 163, 164, 165, 180]


def main() -> int:
    out = Path(sys.argv[1])
    layout_override = None
    if "--layout" in sys.argv:
        layout_override = sys.argv[sys.argv.index("--layout") + 1]
    times = TIMES
    if "--times" in sys.argv:
        a, b, step = (float(x) for x in sys.argv[sys.argv.index("--times") + 1].split(":"))
        times = [round(a + i * step, 3) for i in range(int((b - a) / step) + 1)]
    app = QApplication.instance() or QApplication(sys.argv)
    from src.gui.qt.controller import AppController
    from src.gui.qt.main_window import MainWindow
    import src.indicators.gauge as gauge

    drawn: list = []
    orig = gauge._render_compass_indicator

    def spy(*a, **kw):
        # (canvas_w, canvas_h, font_path, key, cfg, value, ...) – record value
        try:
            import inspect
            ba = inspect.signature(orig).bind_partial(*a, **kw)
            drawn.append({"value": ba.arguments.get("value"),
                          "missing": bool((ba.arguments.get("cfg") or {}).get("_compass_missing", False))})
        except Exception as exc:  # pragma: no cover - diagnostics only
            drawn.append({"error": str(exc)})
        return orig(*a, **kw)

    gauge._render_compass_indicator = spy

    ctl = AppController()
    win = MainWindow()
    win.set_controller(ctl)
    if layout_override:
        ctl._startup_preset_path = layout_override
    t0 = time.perf_counter()
    ctl._on_files_selected([VIDEO], "", FIT)
    while not getattr(ctl, "project_ready", False):
        app.processEvents()
        time.sleep(0.02)
        if time.perf_counter() - t0 > 180:
            raise TimeoutError("project_ready")
    load_s = time.perf_counter() - t0
    for _ in range(50):
        app.processEvents()
        time.sleep(0.01)

    cfg = ctl.layout.get("indicators", {}).get("compass", {})
    tm = ctl.telemetry
    res = {
        "layout_source": layout_override or str(ROOT / "def_layout.json"),
        "load_seconds": round(load_s, 2),
        "compass_cfg_mode": cfg.get("compass_heading_mode", "<missing → standard>"),
        "compass_cfg_reference": cfg.get("compass_reference_source", "<missing>"),
        "compass_cfg_source": cfg.get("source"),
        "compass_status": getattr(tm, "_compass_status", None),
        "compass_result_ready": getattr(tm, "_compass_result", None) is not None,
        "samples": [],
    }
    from src.telemetry_compass_hybrid import parameters
    hyb_cfg = dict(cfg, compass_heading_mode="gps_imu")
    from src.telemetry_compass_hybrid import hybrid_enabled
    app_hybrid = hybrid_enabled(cfg) if "gps_imu" in parameters({}).values() else cfg.get("compass_heading_mode") == "gps_imu"
    hyb = tm._compass_result if app_hybrid else tm.prepare_compass(hyb_cfg)
    # prepare_compass with a different cfg replaces the manager token; restore.
    if not app_hybrid:
        tm.invalidate_compass()
    fit_h = tm.resolve_samples("heading", "fit")
    gpmf_h = tm.resolve_samples("heading", "gpmf")
    from src.telemetry_heading import interpolate_heading
    for t in times:
        info = ctl._resolve_preview_time(float(t))
        dt = info.get("absolute_dt")
        drawn.clear()
        ctl._render_preview_sync(float(t))
        row = {
            "t": t,
            "fit_heading": interpolate_heading(fit_h, dt) if fit_h else None,
            "gpmf_heading": interpolate_heading(gpmf_h, dt) if gpmf_h else None,
            "hybrid_heading": hyb.lookup(dt) if hyb is not None else None,
            "preview_resolver": tm.resolve_value("heading", dt, indicator_key="compass"),
            "renderer_values": drawn[:],
        }
        res["samples"].append(row)
        print(json.dumps(row, default=str), flush=True)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(res, indent=2, default=str), encoding="utf-8")
    print("WROTE", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
