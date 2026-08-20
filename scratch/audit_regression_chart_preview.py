from __future__ import annotations

import json
import sys
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from telemetry_fit import process_fit
from src.gui.layout_manager import normalize_layout
from src.telemetry_extract import ensure_records_list, find_gps_anchor, load_json_with_fallback
from src.indicators.chart_builder import build_chart_data
from src.telemetry_precompute import build_telemetry_cache
from src.indicators.chart_utils import get_history_chart_background


def semantic(history):
    return [(ts, value, value is None) for ts, value in zip(history.timestamps, history)]


def main():
    video_json = ROOT / "Video" / "GX030120.json"
    fit_path = ROOT / "Video" / "Popoludniowa_jazda_na_rowerze_solar_battery.fit"
    records = ensure_records_list(load_json_with_fallback(video_json))
    anchor = find_gps_anchor(records)
    fit = process_fit(str(fit_path), video_start_dt=anchor)
    layout = normalize_layout(str(ROOT / "def_layout.json"), 1920, 1080)
    fps = 29.97
    frames = 5400
    end_dt = anchor + timedelta(seconds=frames / fps)
    all_fit = [s for s in fit.values() if s]
    ranges = {"fit": (min(s[0][0] for s in all_fit), max(s[-1][0] for s in all_fit))}

    def get_samples(source):
        if source == "fit":
            return fit.get("speed", []), fit.get("track", []), fit.get("alt", [])
        return [], [], []

    def resolve(field, source="fit", indicator_key=None):
        if source != "fit":
            return []
        aliases = {"power": ("power", "curVpower"), "hr": ("hr", "heart_rate"), "cad": ("cad", "cadence")}
        for name in aliases.get(field, (field,)):
            if fit.get(name):
                return list(fit[name])
        return []

    chart_off = build_chart_data(layout, get_samples, resolve, anchor, end_dt, ranges)
    cache = build_telemetry_cache(
        layout=layout, base_dt=anchor, tz_offset_hours=0, start_dt_utc=anchor,
        speed_samples=[], track_samples=[], alt_samples=[], fit_data=fit,
        gps_track=fit.get("track", []), chart_data=chart_off,
        total_frames=frames, target_fps=fps,
    )
    result = {"anchor": str(anchor), "fields": {}}
    checkpoints = []
    for frame in (0, 1350, 2700, 4050, 5399):
        rec = cache.lookup(frame)
        history = cache.static.chart_data["fit_heart_rate_text"]
        checkpoints.append({
            "frame": frame,
            "activity_elapsed_s": round(frame / fps, 3),
            "first_chart_sample_timestamp": str(history.timestamps[0]),
            "last_chart_sample_timestamp": str(history.timestamps[-1]),
            "chart_samples": len(history),
            "current_position": rec["current_position"],
            "first_equals_activity_start": history.timestamps[0] == fit["heart_rate"][0][0],
        })
    result["timeline_checkpoints"] = checkpoints
    for key in ("fit_cadence_text", "fit_heart_rate_text"):
        raw = fit["cadence" if "cadence" in key else "heart_rate"]
        off = semantic(chart_off[key])
        on = semantic(cache.static.chart_data[key])
        result["fields"][key] = {
            "raw_count": len(raw), "off_count": len(off), "on_count": len(on),
            "raw_none": sum(v is None for _, v in raw),
            "raw_zero": sum(v == 0 for _, v in raw),
            "off_none": sum(m for _, _, m in off),
            "off_zero": sum(v == 0 for _, v, _ in off),
            "on_none": sum(m for _, _, m in on),
            "on_zero": sum(v == 0 for _, v, _ in on),
            "off_on_equal": off == on,
            "raw_off_equal": [(t, v, v is None) for t, v in raw] == off,
            "order_ok": all(off[i][0] < off[i + 1][0] for i in range(len(off) - 1)),
        }
        _, points, _, _, _, _ = get_history_chart_background(chart_off[key], 600, 240)
        result["fields"][key]["geometry_transitions"] = [
            {
                "index": i, "timestamp": str(off[i][0]), "value": off[i][1],
                "x": round(points[i][0], 2), "y": round(points[i][1], 2),
                "previous_x": round(points[i - 1][0], 2), "previous_y": round(points[i - 1][1], 2),
                "gap_seconds": (off[i][0] - off[i - 1][0]).total_seconds(),
            }
            for i in range(1, len(off))
            if (off[i][0] - off[i - 1][0]).total_seconds() > 5
            or abs(float(off[i][1]) - float(off[i - 1][1])) >= 25
        ][:30]
        for label, seq in (("raw", raw), ("off", off), ("on", on)):
            result["fields"][key][label + "_transitions"] = [
                {"index": i, "before": seq[i - 1][1], "after": seq[i][1], "timestamp": str(seq[i][0])}
                for i in range(1, len(seq))
                if float(seq[i - 1][1]) != float(seq[i][1]) and abs(float(seq[i - 1][1]) - float(seq[i][1])) >= 25
            ][:20]
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
