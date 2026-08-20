from __future__ import annotations

import json
import statistics
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from validate_etap5c_direct import setup
from src.ffmpeg.frame_renderer import render_overlay_frame
from src.ffmpeg.worker_cache import WORKER_CACHE
import src.indicators.compositor as compositor


def stats(values):
    values = sorted(values)
    return {"avg_us": statistics.fmean(values) * 1000, "median_us": statistics.median(values) * 1000, "p95_us": values[int((len(values)-1)*.95)] * 1000}


def main():
    layout, regions, anchor, speed, track, alt = setup()
    captured = {}
    original = compositor.rotated_paste
    def capture(base, overlay, cx, cy, rotation, prior_bboxes=None, cache_key=None):
        if cache_key and cache_key not in captured:
            captured[cache_key] = {"image": overlay.copy(), "center": (cx, cy), "rotation": rotation}
        return original(base, overlay, cx, cy, rotation, prior_bboxes, cache_key)
    compositor.rotated_paste = capture
    layout["_nvidia_direct_region"] = False
    WORKER_CACHE.pop("_prev_frame_data", None); WORKER_CACHE.pop("_prev_atlas_img", None)
    render_overlay_frame(2700, anchor, 2, speed, track, alt, 30000/1001, 1)
    compositor.rotated_paste = original
    result = {"widgets": {}, "active_alpha_overlap_pairs": []}
    keys = list(captured)
    for key, item in captured.items():
        src = item["image"]
        bbox = src.getchannel("A").getbbox()
        alpha_min = src.getchannel("A").getextrema()[0]
        methods = {}
        for name in ("alpha_composite", "paste_mask", "crop_alpha", "paste_direct"):
            values = []
            for _ in range(1000):
                dst = Image.new("RGBA", src.size, (0, 0, 0, 0))
                t0 = time.perf_counter()
                if name == "alpha_composite": dst.alpha_composite(src, (0, 0))
                elif name == "paste_mask": dst.paste(src, (0, 0), src)
                elif name == "crop_alpha" and bbox is not None:
                    crop = src.crop(bbox); small = Image.new("RGBA", crop.size, (0, 0, 0, 0)); small.alpha_composite(crop, (0, 0)); dst.paste(small, (bbox[0], bbox[1]))
                elif name == "paste_direct" and alpha_min == 255:
                    dst.paste(src, (0, 0))
                else:
                    continue
                values.append(time.perf_counter() - t0)
            if values: methods[name] = stats(values)
        ref = Image.new("RGBA", src.size, (0, 0, 0, 0)); ref.alpha_composite(src, (0, 0)); parity = {}
        for name in ("paste_mask", "crop_alpha"):
            out = Image.new("RGBA", src.size, (0, 0, 0, 0))
            if name == "paste_mask": out.paste(src, (0, 0), src)
            else:
                crop = src.crop(bbox); small = Image.new("RGBA", crop.size, (0, 0, 0, 0)); small.alpha_composite(crop, (0, 0)); out.paste(small, (bbox[0], bbox[1]))
            d = np.abs(np.asarray(ref).astype(np.int16)-np.asarray(out).astype(np.int16)); parity[name] = {"max_diff": int(d.max()), "different_pixels": int(np.any(d != 0, axis=2).sum())}
        result["widgets"][key] = {"size": list(src.size), "form": layout.get("indicators", {}).get(key, {}).get("form", "time_block"), "alpha_bbox": list(bbox) if bbox else None, "alpha_min": alpha_min, "methods": methods, "parity": parity}

    # Active alpha overlap in global coordinates, using captured legacy positions.
    boxes = {}
    for key, item in captured.items():
        src = item["image"].transpose(Image.Transpose.ROTATE_90) if item["rotation"] == 90 else item["image"].transpose(Image.Transpose.ROTATE_180) if item["rotation"] == 180 else item["image"].transpose(Image.Transpose.ROTATE_270) if item["rotation"] == 270 else item["image"]
        x = int(round(item["center"][0] - src.width/2)); y = int(round(item["center"][1] - src.height/2)); boxes[key] = (x,y,src)
    for i, a in enumerate(keys):
        for b in keys[i+1:]:
            ax, ay, ai = boxes[a]; bx, by, bi = boxes[b]
            x1,y1=max(ax,bx),max(ay,by); x2,y2=min(ax+ai.width,bx+bi.width),min(ay+ai.height,by+bi.height)
            if x2 <= x1 or y2 <= y1: continue
            aa=np.asarray(ai)[y1-ay:y2-ay,x1-ax:x2-ax,3] > 0; bb=np.asarray(bi)[y1-by:y2-by,x1-bx:x2-bx,3] > 0
            if np.any(aa & bb): result["active_alpha_overlap_pairs"].append([a,b,int(np.any(aa&bb))])
    (ROOT/"scratch/etap5d_composite_benchmark.json").write_text(json.dumps(result,indent=2),encoding="utf-8")
    print(json.dumps(result,indent=2))


if __name__ == "__main__": main()
