"""ETAP Rendering GUI — BRAMKA 3: HUD Preview A/B (real GUI path, offscreen).

Uruchamia PRAWDZIWĄ ścieżkę GUI: prawdziwy `RenderTab` + `get_signals()` +
`RenderMixin._render_pipeline` w wątku roboczym (jak AppController). Warianty:
  A = HUD Preview WYŁĄCZONY (baseline)
  B = HUD Preview WŁĄCZONY  (render 1 Hz na czarnym tle, GUI thread)

Ta sama produkcja AMD (pool8, 5Q OPT, GPU map, GPU_SPLIT charts, GPU gauge,
AMF, D3D11VA, profiler OFF). Mierzy TRUE FPS (z profilu), wall (GUI) i liczbę
aktualizacji preview. Próg: drop <1% (<=2% akceptowalne), >2% -> investigate.

Użycie:  python scratch/gui_render_ab.py [off|on|both]
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scratch"))

import gui_render_headless as g  # noqa: E402  (_build_telemetry + _Stub pattern)

os.environ["QT_QPA_PLATFORM"] = "offscreen"
from PySide6.QtWidgets import QApplication  # noqa: E402
from PySide6.QtCore import QTimer  # noqa: E402

from src.gui.qt.signals import get_signals  # noqa: E402
from src.gui.qt.tabs.render_tab import RenderTab  # noqa: E402
from src.gui.qt._mixins.render_mixin import RenderMixin  # noqa: E402


class AbController:
    """Minimalny kontroler: stan jak _Stub + wątek renderujący (jak AppController)."""

    def __init__(self, out_path: Path) -> None:
        video = ROOT / "Video" / "GX020079.mp4"
        self.video_path = video
        self.video_paths = [video]
        self.base_dir = ROOT
        with (ROOT / "def_layout.json").open(encoding="utf-8") as fh:
            self.layout = json.load(fh)
        self._cut_regions = list(self.layout.get("cut_regions", []))
        self.ffmpeg_exe = r"C:\tools\ffmpeg.exe"
        self.ffprobe_exe = r"C:\tools\ffprobe.exe"
        self.signals = get_signals()
        self.render_cancel_event = threading.Event()
        self.render_threads = 1
        self.video_duration_s = 1131 * (1001.0 / 30000.0)
        self.font_path = g.resolve_font_path("Arial")
        self.telemetry = g._build_telemetry()
        self.fit_ext_fields = getattr(self.telemetry, "fit_ext_fields", None)
        self.out_path = out_path

    def _on_render_requested(self, options: dict) -> None:
        opts = dict(options)
        opts["output"] = str(self.out_path)

        def run() -> None:
            try:
                stats = RenderMixin._render_pipeline(self, opts)
                self.signals.sig_render_finished.emit(stats, opts["output"])
            except Exception as exc:  # noqa: BLE001
                import traceback
                traceback.print_exc()
                self.signals.sig_error.emit(str(exc))

        threading.Thread(target=run, daemon=True).start()

    def add_cut_region(self, a: float, b: float) -> None:
        self._cut_regions.append((a, b))

    def remove_cut_region(self, a: float, b: float) -> None:
        if (a, b) in self._cut_regions:
            self._cut_regions.remove((a, b))


def _profile_metrics(out_path: Path) -> dict:
    profile = out_path.with_suffix(out_path.suffix + ".amd_profile.json")
    if not profile.exists():
        return {}
    d = json.loads(profile.read_text(encoding="utf-8"))
    fa = d.get("frame_accounting", {})
    amf = d.get("amf", {})
    return {
        "true_fps": d.get("true_fps", 0.0),
        "muxed": fa.get("muxed_frames"),
        "amf_out": fa.get("amf_output"),
        "vp": fa.get("vp_processed"),
        "dropped": amf.get("dropped_submissions"),
        "input_full": amf.get("input_full_count"),
    }


def run_one(mode: str, tag: str) -> dict:
    app = QApplication.instance() or QApplication([])
    signals = get_signals()
    out = ROOT / "Raporty" / "AMD_ETAP5G" / f"l5_rendergui_{tag}.mp4"
    ctrl = AbController(out)
    tab = RenderTab()
    tab.set_controller(ctrl)
    signals.sig_render_requested.connect(ctrl._on_render_requested)

    preview = {"n": 0, "ts": []}
    _orig = tab._render_hud_preview

    def counting() -> None:
        preview["n"] += 1
        _orig()

    if mode == "off":
        tab._render_hud_preview = lambda: None
    else:
        tab._render_hud_preview = counting

    done = {"stats": None, "error": None}

    def on_finished(stats: dict, _output: str) -> None:
        done["stats"] = stats
        app.quit()

    def on_error(msg: str) -> None:
        done["error"] = msg
        app.quit()

    signals.sig_render_finished.connect(on_finished)
    signals.sig_error.connect(on_error)

    t0 = time.monotonic()
    tab._on_render()
    QTimer.singleShot(150000, app.quit)  # safety
    app.exec()
    wall = time.monotonic() - t0

    # odłącz, żeby nie kumulować w kolejnych runach
    try:
        signals.sig_render_requested.disconnect(ctrl._on_render_requested)
        signals.sig_render_finished.disconnect(on_finished)
        signals.sig_error.disconnect(on_error)
    except Exception:  # noqa: BLE001
        pass

    return {
        "mode": mode,
        "wall": wall,
        "error": done["error"],
        "preview_updates": preview["n"],
        **(_profile_metrics(out)),
    }


def main() -> int:
    which = sys.argv[1] if len(sys.argv) > 1 else "both"
    for k in list(os.environ.keys()):
        if k.startswith("AMD_"):
            os.environ.pop(k, None)

    results = {}
    if which in ("off", "both"):
        print("=== RUN A: HUD Preview OFF ===", flush=True)
        results["A"] = run_one("off", "a_off")
        print(results["A"], flush=True)
    if which in ("on", "both"):
        print("=== RUN B: HUD Preview ON ===", flush=True)
        results["B"] = run_one("on", "b_on")
        print(results["B"], flush=True)

    if "A" in results and "B" in results:
        a, b = results["A"], results["B"]
        d_fps = 100.0 * (b["true_fps"] - a["true_fps"]) / a["true_fps"] if a["true_fps"] else 0.0
        d_wall = 100.0 * (b["wall"] - a["wall"]) / a["wall"] if a["wall"] else 0.0
        print("\n=== BRAMKA 3: A/B SUMMARY ===", flush=True)
        print(f"A OFF:  TRUE FPS={a['true_fps']:.3f} wall={a['wall']:.3f}s", flush=True)
        print(f"B ON:   TRUE FPS={b['true_fps']:.3f} wall={b['wall']:.3f}s "
              f"preview_updates={b['preview_updates']}", flush=True)
        print(f"Δ TRUE FPS = {d_fps:+.2f} %   Δ wall = {d_wall:+.2f} %", flush=True)
        print(f"B muxed={b['muxed']} amf_out={b['amf_out']} vp={b['vp']} "
              f"dropped={b['dropped']} input_full={b['input_full']}", flush=True)
        ok = (b["muxed"] == 1131 and b["amf_out"] == 1131 and b["dropped"] == 0
              and d_fps >= -2.0)  # B nie może być wolniejszy o >2% (szum termiczny)
        print(f"BRAMKA 3 gate (B nie wolniejszy o >2% && 1131/1131 && drop=0): {ok}", flush=True)
        return 0 if ok else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
