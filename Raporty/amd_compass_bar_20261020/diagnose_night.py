"""Observe the real GUI telemetry manager during the canonical AMD harness."""
from datetime import timedelta
import json
from pathlib import Path
import runpy
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from src.render_preparation import RenderPreparationService

original = RenderPreparationService.prepare.__func__


def observe(cls, **kwargs):
    tm = kwargs["telemetry"]
    cache = original(cls, **kwargs)
    cfg = kwargs["layout"]["indicators"]["compass"]
    source = cfg.get("source", "gpmf")
    data = {"source": source, "video_paths": kwargs.get("video_paths"),
            "base_dt": tm.start_dt_utc, "cache_manifest": str(cache.manifest_path), "streams": {}}
    for src in ("gpmf", "fit", "gpx"):
        samples = tm.resolve_samples("heading", src)
        valid = [(dt, v) for dt, v in samples if v is not None]
        data["streams"][src] = {"count": len(samples), "valid_count": len(valid),
                                "first": samples[:3], "last": samples[-3:],
                                "first_valid": valid[:3], "last_valid": valid[-3:]}
    data["preview_over_clip"] = [
        {"second": t, "heading": tm.resolve_value("heading", tm.start_dt_utc + timedelta(seconds=t),
                                                  source=source, indicator_key="compass")}
        for t in range(0, 2101, 10)
    ]
    data["frames"] = []
    for i in range(cache.frames):
        frame = cache.lookup(i)
        preview = tm.resolve_value("heading", frame["target_dt"], source=source, indicator_key="compass")
        final = frame["extra_indicators"]["compass"][0]
        data["frames"].append({"i": i, "dt": frame["target_dt"], "preview": preview, "final": final})
    data["heading_samples"] = list(tm.resolve_samples("heading", source))
    target = Path(sys.argv[sys.argv.index("--result-json") + 1]).with_suffix(".telemetry.json")
    target.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    print("[NIGHT DIAGNOSTIC]", target, data["streams"], flush=True)
    return cache


RenderPreparationService.prepare = classmethod(observe)
runpy.run_path(str(ROOT / "SportCamHUD.py"), run_name="__main__")
