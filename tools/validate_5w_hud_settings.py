"""One short native AMD export + actual PreviewMixin/Qt raster, isolated layout.

Run from the project root. Controlled zero-valued telemetry, no FIT selection;
this is a HUD setting contract test, not a full-HUD performance benchmark.
"""
from pathlib import Path
import copy
import hashlib
import json
import os
import subprocess
import sys
import time
import types

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
from PIL import Image
from PySide6.QtWidgets import QApplication
from src.gui.qt._mixins.preview_mixin import PreviewMixin
from src.indicators.compositor import compose_overlay
from src.indicators.text import _render_text_indicator, clear_text_cache
from src.ffmpeg import amd_native_exporter as amd
from src.multifile import VideoClip, VideoTimeline


def main():
    out = ROOT / "Raporty/etap5w_artifacts"
    out.mkdir(exist_ok=True)
    final = out / "settings_native.mp4"
    verify_existing = "--verify-existing" in sys.argv
    if not verify_existing and (final.exists() or Path(str(final) + ".part").exists()):
        raise RuntimeError("Preserve previous evidence; refusing another export to this path")
    state_path = out / "initial_state.json"
    if not state_path.exists():
        protected = ["def_layout.json", "src/ffmpeg/amd_native_exporter.py", "src/ffmpeg/mp4_audio_feed.py",
                     "src/ffmpeg/intel_native_exporter.py", "src/ffmpeg/nvidia_native_exporter.py",
                     "runtime/amd/bin/telem_amd_native.dll"]
        state_path.write_text(json.dumps({"sha256": {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest()
                                                     for p in protected}}, indent=2), encoding="utf-8")
    initial = json.loads(state_path.read_text())
    font = r"C:\Windows\Fonts\arial.ttf"
    cfg = dict(enabled=True, form="text", source="gpmf", font_size=3.,
               font=font, text_color="#FFFFFF", show_units=True, show_value=True, icon="none")
    layout = {"global": {"text_outline": 1}, "indicators": {
        "speed_text": dict(cfg, x=5., y=12., unit="km/h", text_distance=22., unit_offset_x=.02),
        "temp_text": dict(cfg, x=5., y=32., unit="C", text_distance=8., unit_offset_y=.02),
        "iso_text": dict(enabled=True, form="bar", bar_style="segments", source="gpmf",
                         x=50., y=65., size=45., font_size=2.5, font=font,
                         label="BAR", unit="", icon="none", auto_scale=False,
                         min_val=0, max_val=100, decimals=0, show_min=True, show_max=True,
                         show_value=True, show_label=True, value_align="left",
                         value_font=r"C:\Windows\Fonts\cour.ttf",
                         label_font=r"C:\Windows\Fonts\times.ttf", range_font=font),
    }, "_indicator_availability": {"speed_text": True, "temp_text": True, "iso_text": True}}
    (out / "settings_layout.json").write_text(json.dumps(layout, indent=2), encoding="utf-8")
    app = QApplication.instance() or QApplication([])
    emitted = []
    class Emit:
        def __init__(self, callback):
            self.callback = callback
        def emit(self, *args):
            self.callback(*args)
    # Call the real preview mixin and QImage emission path. No controller is
    # started, so the application's session/def_layout cannot be auto-saved.
    preview = types.SimpleNamespace(
        video_path="controlled-original-GoPro", layout=copy.deepcopy(layout), font_path=font,
        video_info={}, video_width=3840, video_height=2160,
        _preview_target_w=3840, _preview_target_h=2160, _preview_dpr=1.,
        _playing=False, telemetry=types.SimpleNamespace(start_dt_utc=None),
        video_duration_s=5.005, indicator_bboxes={},
        is_using_mpv=lambda: True, is_in_cut_region=lambda _: False,
        _resolve_preview_time=lambda _: dict(global_time=0., local_time=0., clip_index=0,
                                             clip=None, absolute_dt=None),
        signals=types.SimpleNamespace(sig_preview_frame_ready=Emit(lambda q: emitted.append(q.copy())),
                                      sig_bboxes_ready=Emit(lambda *args: None)),
    )
    PreviewMixin._render_preview_sync(preview, 0.)
    assert len(emitted) == 1, "Actual preview failed to emit its QImage"
    preview_rgba = Image.fromqimage(emitted[0]).convert("RGBA")
    preview_rgba.save(out / "qt_preview_hud.png")
    preview._preview_dpr = 2.
    PreviewMixin._render_preview_sync(preview, 0.)
    assert len(emitted) == 2 and emitted[1].devicePixelRatio() == 2.
    assert np.array_equal(np.array(preview_rgba), np.array(Image.fromqimage(emitted[1]).convert("RGBA")))
    reference = compose_overlay(3840, 2160, layout, font, "", "", 0., 0.,
                                iso_value=0., temp_value=0., reuse_canvas=False)
    assert np.array_equal(np.array(reference), np.array(preview_rgba)), "Preview differs from reference compositor"

    # Cold/miss and hot/hit costs, ABBA order; preparation separate from export.
    old_source = subprocess.check_output(["git", "show", "cbe0dd4:src/indicators/text.py"], text=True, cwd=ROOT)
    legacy = types.ModuleType("legacy_text_5w")
    exec(compile(old_source, "legacy_text_5w", "exec"), legacy.__dict__)
    costs = {}
    for settings_name, settings in [("defaults", {}), ("unit_offset", {"text_distance": 22., "unit_offset_x": .02})]:
        legacy.clear_text_cache()
        clear_text_cache()
        samples = {"before": [], "after": []}
        for mode in ("before", "after", "after", "before"):
            fn = legacy._render_text_indicator if mode == "before" else _render_text_indicator
            c = dict(x=5., y=5., **settings)
            start = time.perf_counter()
            for n in range(300):
                fn(3840, 2160, {}, font, "speed_text", n, "km/h", "", c,
                   2160, 2, 64, None, 0, 100, 0, 1, 100, 1, formatted_val=f"{n} km/h")
            samples[mode].append((time.perf_counter() - start) * 1000 / 300)
        costs[settings_name] = samples
    (out / "text_cost_ms.json").write_text(json.dumps(costs, indent=2), encoding="utf-8")

    if verify_existing:
        # No second export: prove that the local cost fix produces the exact
        # raster already uploaded/encoded in the preserved native run.
        native = Image.open(out / "native_cpu_hud.png").convert("RGBA")
        delta = np.abs(np.array(preview_rgba).astype(int) - np.array(native).astype(int))
        parity = dict(max_diff=int(delta.max()), mae=float(delta.mean()),
                      different_pixels=int(np.any(delta, axis=2).sum()))
        assert parity["different_pixels"] == 0, parity
        (out / "current_vs_exported_parity.json").write_text(json.dumps(parity, indent=2), encoding="utf-8")
        previous = types.ModuleType("pre_cost_fix")
        exec(compile((out / "text_before_local_cost_fix.py").read_text(), "pre_cost_fix", "exec"), previous.__dict__)
        count = 0
        for path in [font, r"C:\Windows\Fonts\cour.ttf", r"C:\Windows\Fonts\times.ttf"]:
            for size in [18, 42, 84]:
                for unit in ["km/h", "%", "°C"]:
                    for rotation in [0, 90, 180, 270]:
                        cfg = dict(x=10., y=20., unit_offset_x=.03, unit_offset_y=-.02, rotation=rotation)
                        args = (1920, 1080, {}, path, "speed_text", 25.4, unit, "", cfg,
                                1080, 1, size, None, 0, 100, 0, 1, 100, 1)
                        a = previous._render_text_indicator(*args, formatted_val=f"25.4 {unit}")
                        b = _render_text_indicator(*args, formatted_val=f"25.4 {unit}")
                        assert a[1:3] == b[1:3] and np.array_equal(np.array(a[0]), np.array(b[0]))
                        count += 1
        for path, expected in initial["sha256"].items():
            assert hashlib.sha256((ROOT / path).read_bytes()).hexdigest() == expected, path
        print("5W_EXISTING_EXPORT_EQUIVALENCE=" + json.dumps(dict(cases=count, **parity)))
        return

    from datetime import datetime, timedelta
    source = Path(r"F:\GoPro\2026-10-07\GX010350.MP4")
    assert source.is_file()
    base = datetime(2026, 10, 7, 0, 0, 0)
    samples = [(base, 0.), (base + timedelta(seconds=60), 0.)]
    fps = 30000 / 1001
    timeline = VideoTimeline([VideoClip(path=source, duration_s=150 / fps, fps=fps,
                                      width=3840, height=2160, local_start_s=10.,
                                      source_duration_s=179.626667)], base_dt=base)
    original_compose = amd.compose_overlay
    captured = []
    def observe(*args, **kwargs):
        result = original_compose(*args, **kwargs)
        if not captured and result.getbbox():
            captured.append(result.copy())
            result.save(out / "native_cpu_hud.png")
        return result
    amd.compose_overlay = observe
    os.environ["TELEM_RENDER_DEBUG"] = "1"
    try:
        assert amd.export_amd_native_d3d11(
            ffmpeg_exe=str(ROOT / "runtime/common/ffmpeg/ffmpeg.exe"),
            input_files=[str(source)], output_file=str(final), duration_s=150 / fps,
            video_width=3840, video_height=2160, start_dt_utc=base, tz_offset_hours=0.,
            speed_samples=samples, track_samples=[], alt_samples=[], iso_samples=samples,
            temperature_samples=samples, font_path=font, layout=copy.deepcopy(layout), field_samples={},
            target_fps=fps, video_bitrate="65M", quality="FAST", video_timeline=timeline,
        )
    finally:
        amd.compose_overlay = original_compose
    assert captured
    diff = np.abs(np.array(preview_rgba).astype(int) - np.array(captured[0]).astype(int))
    parity = dict(max_diff=int(diff.max()), mae=float(diff.mean()), different_pixels=int(np.any(diff, axis=2).sum()))
    (out / "preview_native_raster_parity.json").write_text(json.dumps(parity, indent=2), encoding="utf-8")
    assert parity["different_pixels"] == 0, parity
    subprocess.run([str(ROOT / "runtime/common/ffmpeg/ffmpeg.exe"), "-v", "error", "-i", str(final),
                    "-frames:v", "1", str(out / "final_frame.png")], check=True)
    for path, expected in initial["sha256"].items():
        assert hashlib.sha256((ROOT / path).read_bytes()).hexdigest() == expected, path
    print("5W_PREVIEW_NATIVE_RASTER_PARITY=" + json.dumps(parity), flush=True)


if __name__ == "__main__":
    main()
