"""Instrument the existing --test-amd-export harness, without replacing it."""
from pathlib import Path
import json
import runpy
import sys
import threading
import time

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from src import telemetry_compass_hybrid as hybrid
from src.render_preparation import RenderPreparationService

OUT = Path(sys.argv[sys.argv.index("--result-json")+1]).resolve()
ORIGINAL_BUILD = hybrid.prepare_manager_compass
ORIGINAL_PREPARE = RenderPreparationService.prepare.__func__


def measured_build(manager, cfg, **kwargs):
    import psutil
    process = psutil.Process()
    baseline = process.memory_info().rss
    peak = [baseline]
    stop = threading.Event()
    def monitor():
        while not stop.wait(.02):
            peak[0] = max(peak[0], process.memory_info().rss)
    thread = threading.Thread(target=monitor, daemon=True)
    thread.start()
    cpu = time.process_time()
    started = time.perf_counter()
    try:
        result = ORIGINAL_BUILD(manager, cfg, **kwargs)
    finally:
        stop.set()
        thread.join()
    result.diagnostics.update(measured_cpu_seconds=time.process_time()-cpu,
                              measured_wall_seconds=time.perf_counter()-started,
                              process_rss_increase_bytes=max(0, peak[0]-baseline),
                              process_rss_peak_bytes=peak[0])
    np.savez_compressed(OUT.with_suffix(".axis.npz"), axis=result.axis)
    OUT.with_suffix(".diagnostics.json").write_text(json.dumps(result.diagnostics, indent=2), encoding="utf-8")
    inputs = OUT.parent / "real_inputs.npz"
    if not inputs.exists():
        fit_speed = manager.fit_data.get("speed")
        np.savez_compressed(inputs,
                            gyro=hybrid.sample_array(manager.gyroscope_samples, True),
                            accel=hybrid.sample_array(manager.accelerometer_samples, True),
                            gpmf_track=hybrid.track_array(manager.gps_track),
                            fit_track=hybrid.track_array(manager.fit_gps_track),
                            gpmf_speed=hybrid.sample_array(manager.speed_samples),
                            fit_speed=hybrid.sample_array(fit_speed))
    return result


def parity_prepare(cls, **kwargs):
    cache = ORIGINAL_PREPARE(cls, **kwargs)
    cfg = kwargs["layout"]["indicators"].get("compass", {})
    if not hybrid.hybrid_enabled(cfg):
        return cache
    tm = kwargs["telemetry"]
    results = []
    missing_mismatch = 0
    max_error = 0.
    for i in range(cache.frames):
        frame = cache.lookup(i)
        preview = tm.resolve_value("heading", frame["target_dt"], indicator_key="compass", indicator_config=cfg)
        final = frame["extra_indicators"]["compass"][0]
        if (preview is None) != (final is None):
            missing_mismatch += 1
        elif preview is not None:
            max_error = max(max_error, abs(float(hybrid.wrap180(preview-final))))
        results.append({"frame": i, "time": frame["target_dt"].isoformat(), "preview": preview, "final": final})
    # Compare pre-encode compass surfaces at beginning, middle and end. Only
    # the resolved compass value differs between these two actual code paths.
    from src.indicators.compositor import compose_overlay
    from PIL import Image
    image_stats = []
    for i in sorted({0, min(300, cache.frames-1), cache.frames//2, cache.frames-1}):
        frame = cache.lookup(i)
        image = compose_overlay(3840, 2160, kwargs["layout"], "", **frame,
                                render_keys={"compass"}, reuse_canvas=False)
        frame["extra_indicators"] = dict(frame["extra_indicators"], compass=(results[i]["preview"], "°", "COMPASS"))
        reference = compose_overlay(3840, 2160, kwargs["layout"], "", **frame,
                                    render_keys={"compass"}, reuse_canvas=False)
        error = abs(np.asarray(image, dtype=np.int16)-np.asarray(reference, dtype=np.int16))
        image_stats.append({"frame": i, "max_diff": int(error.max()), "MAE": float(error.mean()),
                            "different_pixels": int(np.count_nonzero(np.any(error != 0, axis=2)))})
        image.crop((int(3840*.8), int(2160*.18), 3840, int(2160*.48))).save(OUT.with_suffix(f".hud_f{i}.png"))
    OUT.with_suffix(".parity.json").write_text(json.dumps({"frames": results, "missing_mismatches": missing_mismatch,
                                                         "max_heading_error_degrees": max_error, "images": image_stats,
                                                         "cache_manifest": str(cache.manifest_path)}, indent=2), encoding="utf-8")
    return cache


hybrid.prepare_manager_compass = measured_build
RenderPreparationService.prepare = classmethod(parity_prepare)
runpy.run_path(str(ROOT / "SportCamHUD.py"), run_name="__main__")
