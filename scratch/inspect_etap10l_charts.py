import json
from pathlib import Path
import statistics

root = Path(__file__).resolve().parents[1]
json_file = root / "scratch" / "etap10l_detailed_measurements.json"

if json_file.exists():
    with open(json_file, "r", encoding="utf-8") as f:
        data = json.load(f)
    frames = data.get("frame_records", [])
    print(f"Total frame records: {len(frames)}")
    if frames:
        print("Keys in frame 0:", [k for k in frames[0].keys() if "heart" in k or "cad" in k or "compose" in k])
        for k in ["widget.fit_heart_rate_text.render_ms", "widget.fit_cadence_text.render_ms", "widget.fit_heart_rate_text.paste_ms", "widget.fit_cadence_text.paste_ms", "above_compose_ms"]:
            vals = [f[k] for f in frames if k in f]
            steady = vals[10:] if len(vals) > 10 else vals
            if steady:
                print(f"{k}: mean={statistics.fmean(steady):.3f} ms, median={statistics.median(steady):.3f} ms")
