"""CPU P0.4 GUI probe: real MainWindow + AppController + RenderTab, offscreen.

Usage: gui_probe.py <phase> <config_dir> <out.json>
  phase 1: exercise widgets, write the session layout (restart test, part 1)
  phase 2: NEW process: read the session layout back and apply it (part 2)
  legacy : apply legacy / partial settings and check the migration rule
TELEM_CONFIG_DIR isolates the session file from the user's real configuration.
"""
import json
import os
import sys
from pathlib import Path

phase, cfg, out = sys.argv[1], sys.argv[2], sys.argv[3]
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["TELEM_CONFIG_DIR"] = cfg
Path(cfg).mkdir(parents=True, exist_ok=True)
REPO = Path(r"C:\_DEV\SportCamHUD")
sys.path.insert(0, str(REPO))
os.chdir(REPO)

from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication(sys.argv[:1])
from src.gui.qt.controller import AppController  # noqa: E402
from src.gui.qt.main_window import MainWindow  # noqa: E402

ctrl = AppController()
win = MainWindow()
win.set_controller(ctrl)
rt = win._render_tab
checks = []


def check(name, ok, detail=""):
    checks.append({"check": name, "pass": bool(ok), "detail": str(detail)})
    print(("PASS " if ok else "FAIL ") + name, detail, flush=True)


def state():
    return {"profile": rt.cmb_cpu_profile.currentData(), "rate_mode": rt.cmb_cpu_rate_mode.currentData(),
            "bitrate_text": rt.edit_bitrate.text().strip(), "bitrate_enabled": rt.edit_bitrate.isEnabled(),
            "cpu_panel_visible": rt.widget_cpu_options.isVisibleTo(rt)}


def select_encoder(name):
    rt.cmb_encoder.setCurrentText(name)
    app.processEvents()


session = Path(cfg) / "session" / "active_layout.json"

if phase == "1":
    check("fresh widget defaults (no layout applied) = balanced/abr", state()["profile"] == "balanced"
          and state()["rate_mode"] == "abr" and state()["bitrate_enabled"], state())
    select_encoder("cpu")
    check("CPU options panel visible for encoder=cpu", state()["cpu_panel_visible"], state())
    for want in ("fast", "quality", "balanced"):
        rt.cmb_cpu_profile.setCurrentIndex(rt.cmb_cpu_profile.findData(want))
        app.processEvents()
        check(f"profile change -> options cpu_profile={want}",
              rt._build_options_from_gui()["cpu_profile"] == want)
    rt.cmb_cpu_rate_mode.setCurrentIndex(rt.cmb_cpu_rate_mode.findData("crf"))
    app.processEvents()
    check("CRF locks bitrate slider (edit_bitrate disabled)", not rt.edit_bitrate.isEnabled(), state())
    check("options cpu_rate_mode=crf", rt._build_options_from_gui()["cpu_rate_mode"] == "crf")
    select_encoder("amd")
    check("other backend (amd) keeps bitrate enabled while CRF stored", rt.edit_bitrate.isEnabled(), state())
    check("CPU panel hidden for amd", not rt.widget_cpu_options.isVisibleTo(rt))
    select_encoder("cpu")
    check("back to cpu + CRF: bitrate disabled again", not rt.edit_bitrate.isEnabled(), state())
    rt.cmb_cpu_rate_mode.setCurrentIndex(rt.cmb_cpu_rate_mode.findData("abr"))
    app.processEvents()
    check("ABR unlocks bitrate slider", rt.edit_bitrate.isEnabled(), state())
    rt.edit_bitrate.setText("23M")
    check("bitrate text 23M -> options bitrate", rt._build_options_from_gui()["bitrate"] in ("23M", "23"),
          rt._build_options_from_gui()["bitrate"])
    # final choice persisted for the restart test: quality + CRF + 23M
    rt.cmb_cpu_profile.setCurrentIndex(rt.cmb_cpu_profile.findData("quality"))
    rt.cmb_cpu_rate_mode.setCurrentIndex(rt.cmb_cpu_rate_mode.findData("crf"))
    app.processEvents()
    saved_path = ctrl._save_session_layout()
    check("session layout saved", saved_path is not None and session.exists(), saved_path)
    exp = json.loads(session.read_text(encoding="utf-8")).get("export_settings", {})
    check("session export_settings carry cpu_profile/cpu_rate_mode",
          exp.get("cpu_profile") == "quality" and exp.get("cpu_rate_mode") == "crf", exp)
    # preset save / load round trip (same export_settings dict mechanism)
    rt.cmb_cpu_profile.setCurrentIndex(rt.cmb_cpu_profile.findData("fast"))
    rt.cmb_cpu_rate_mode.setCurrentIndex(rt.cmb_cpu_rate_mode.findData("abr"))
    snapshot = json.loads(json.dumps({"cpu_profile": rt.cmb_cpu_profile.currentData(),
                                      "cpu_rate_mode": rt.cmb_cpu_rate_mode.currentData()}))
    rt.cmb_cpu_profile.setCurrentIndex(rt.cmb_cpu_profile.findData("quality"))
    rt.cmb_cpu_rate_mode.setCurrentIndex(rt.cmb_cpu_rate_mode.findData("crf"))
    rt.apply_export_settings(snapshot)
    check("preset round trip restores fast/abr", state()["profile"] == "fast" and state()["rate_mode"] == "abr", state())
    # restore the persisted choice so phase 2 sees quality/crf in the saved session
    rt.cmb_cpu_profile.setCurrentIndex(rt.cmb_cpu_profile.findData("quality"))
    rt.cmb_cpu_rate_mode.setCurrentIndex(rt.cmb_cpu_rate_mode.findData("crf"))

elif phase == "2":
    check("session file from previous process exists", session.exists(), session)
    settings = json.loads(session.read_text(encoding="utf-8")).get("export_settings", {})
    select_encoder("cpu")
    rt.apply_export_settings(settings)
    app.processEvents()
    s = state()
    check("after restart: profile=quality restored", s["profile"] == "quality", s)
    check("after restart: rate_mode=crf restored", s["rate_mode"] == "crf", s)
    check("after restart: bitrate slider locked in CRF", not s["bitrate_enabled"], s)

elif phase == "legacy":
    select_encoder("cpu")
    cases = {
        "empty settings (project saved before P0.3)": ({}, ("quality", "crf")),
        "legacy keys only (encoder_profile/bitrate)": ({"encoder_profile": "fast", "bitrate": "40M"}, ("quality", "crf")),
        "only cpu_profile stored": ({"cpu_profile": "fast"}, ("fast", "crf")),
        "only cpu_rate_mode=abr stored": ({"cpu_rate_mode": "abr"}, ("quality", "abr")),
        "new keys": ({"cpu_profile": "balanced", "cpu_rate_mode": "abr"}, ("balanced", "abr")),
    }
    for name, (settings, want) in cases.items():
        # start from the opposite of the expectation so a no-op cannot pass
        rt.cmb_cpu_profile.setCurrentIndex(rt.cmb_cpu_profile.findData("fast" if want[0] != "fast" else "quality"))
        rt.cmb_cpu_rate_mode.setCurrentIndex(rt.cmb_cpu_rate_mode.findData("abr" if want[1] != "abr" else "crf"))
        rt.apply_export_settings(settings)
        s = state()
        check(f"migration: {name} -> {want}", (s["profile"], s["rate_mode"]) == want, s)
    # effective encoder command for a legacy project == previous behaviour
    from src.ffmpeg.command_builder import _build_stream_ffmpeg_cmd
    rt.apply_export_settings({})
    o = rt._build_options_from_gui()
    cmd, _ = _build_stream_ffmpeg_cmd("ffmpeg", ["-i", "in.mp4"], "out.mp4", encoder="cpu",
                                      video_bitrate=o["bitrate"] or "40M", is_10bit=True,
                                      intel_encoder_profile=o["cpu_profile"], cpu_rate_mode=o["cpu_rate_mode"],
                                      container_rotation=180, cpu_color_range="pc")
    preset = cmd[cmd.index("-preset") + 1]
    check("legacy project encodes with preset medium + CRF 24, no -b:v",
          preset == "medium" and cmd[cmd.index("-crf") + 1] == "24" and "-b:v" not in cmd,
          f"preset={preset} crf={'-crf' in cmd} bv={'-b:v' in cmd}")

json.dump({"phase": phase, "checks": checks}, open(out, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
failed = [c for c in checks if not c["pass"]]
print(f"RESULT phase={phase} checks={len(checks)} failed={len(failed)}", flush=True)
os._exit(1 if failed else 0)
