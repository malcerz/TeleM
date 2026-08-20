"""ETAP 5E.4: compare local-raster packed atlas with direct chart target."""

from __future__ import annotations

import json
import sys
from datetime import timedelta
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scratch.validate_etap5b6_direct import FPS, H, N, W, setup
from src.ffmpeg.frame_renderer import _direct_region_members
from src.ffmpeg.worker_cache import WORKER_CACHE
from src.indicators.compositor import compose_overlay


def _data_for(frame, histories, telemetry):
    data = dict(telemetry.lookup(frame))
    target = histories["fit_heart_rate_text"].chart_start_dt + timedelta(
        seconds=frame / FPS
    )
    data["target_dt"] = target
    data["current_position"] = frame / (N - 1)
    extra = dict(data.get("extra_indicators") or {})
    for key in ("fit_cadence_text", "fit_heart_rate_text"):
        history = histories[key]
        from bisect import bisect_right
        visible = bisect_right(history.timestamps, target) - 1
        value = history[visible] if visible >= 0 else None
        if key in extra:
            _old, unit, label = extra[key]
            extra[key] = (value, unit, label)
    data["extra_indicators"] = extra
    return data


def _pack_local(image, regions, atlas_size, rotate180=False):
    atlas_w, atlas_h = atlas_size
    atlas = Image.new("RGBA", (atlas_w, atlas_h), (0, 0, 0, 0))
    for dest_x, dest_y, atlas_x, atlas_y, rw, rh in regions:
        crop = image.crop((dest_x, dest_y, dest_x + rw, dest_y + rh))
        if rotate180:
            crop = crop.transpose(Image.Transpose.ROTATE_180)
        atlas.paste(crop, (atlas_x, atlas_y))
    return atlas


def main():
    layout, regions, _anchor, *_ = setup()
    histories = WORKER_CACHE["_precomputed_chart_data"]
    telemetry = WORKER_CACHE["_telemetry_cache"]
    owners = _direct_region_members(layout, regions)
    atlas_w, atlas_h = layout["_nvidia_atlas_size"]
    checkpoints = [0, 540, 1350, 2700, 4050, 4860, 5399]
    output = {"checkpoints": {}, "rotations": {}}
    for frame in checkpoints:
        data = _data_for(frame, histories, telemetry)
        full = compose_overlay(W, H, layout, "", _bboxes={}, reuse_canvas=False, **data)
        local_atlas = _pack_local(full, regions, (atlas_w, atlas_h))
        direct_atlas = Image.new("RGBA", (atlas_w, atlas_h), (0, 0, 0, 0))
        for region, members in zip(regions, owners):
            dest_x, dest_y, atlas_x, atlas_y, _rw, _rh = region
            compose_overlay(
                W, H, layout, "", _bboxes={}, reuse_canvas=False,
                target_image=direct_atlas,
                coordinate_origin=(dest_x - atlas_x, dest_y - atlas_y),
                render_keys=set(members),
                **data,
            )
        a = np.asarray(local_atlas)
        b = np.asarray(direct_atlas)
        diff = np.abs(a.astype(np.int16) - b.astype(np.int16))
        changed = np.any(diff != 0, axis=2)
        ys, xs = np.where(changed)
        if frame == 2700:
            local_atlas.save(ROOT / "scratch" / "etap5e4_local_atlas_2700.png")
            direct_atlas.save(ROOT / "scratch" / "etap5e4_direct_atlas_2700.png")
        output["checkpoints"][str(frame)] = {
            "max_diff": int(diff.max()),
            "different_pixels": int(changed.sum()),
            "diff_bbox": [int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())] if len(xs) else None,
            "diff_samples": [
                {"x": int(x), "y": int(y), "local": a[y, x].tolist(), "direct": b[y, x].tolist()}
                for y, x in zip(ys[:10], xs[:10])
            ],
            "shape": list(a.shape),
        }

    # The direct path is explicitly disabled for non-zero chart rotation;
    # verify that the fallback remains byte-identical to the local path for
    # all four supported indicator rotations.
    for rotation in (0, 90, 180, 270):
        test_layout = {**layout, "indicators": {
            key: dict(value) for key, value in layout.get("indicators", {}).items()
        }}
        for key in ("fit_cadence_text", "fit_heart_rate_text"):
            test_layout["indicators"][key]["rotation"] = rotation
        frame = 2700
        data = _data_for(frame, histories, telemetry)
        local = compose_overlay(W, H, test_layout, "", _bboxes={}, reuse_canvas=False, **data)
        # A target image with one complete canvas and zero origin exercises the
        # same fallback contract without changing the region planner.
        target = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        compose_overlay(
            W, H, test_layout, "", _bboxes={}, reuse_canvas=False,
            target_image=target, coordinate_origin=(0, 0),
            render_keys={"fit_cadence_text", "fit_heart_rate_text"}, **data,
        )
        # Only chart areas are compared; non-rendered indicators are omitted
        # from the target call.
        masks = np.zeros((H, W), dtype=bool)
        # Use the chart widget bboxes from a local compose call.
        bboxes = {}
        compose_overlay(W, H, test_layout, "", _bboxes=bboxes, reuse_canvas=False, **data)
        for key in ("fit_cadence_text", "fit_heart_rate_text"):
            if key in bboxes:
                x, y, w, h = bboxes[key]
                masks[max(0, y):min(H, y + h), max(0, x):min(W, x + w)] = True
        aa, bb = np.asarray(local), np.asarray(target)
        diff = np.abs(aa.astype(np.int16) - bb.astype(np.int16))
        diff[~masks] = 0
        output["rotations"][str(rotation)] = {
            "max_diff": int(diff.max()),
            "different_pixels": int(np.any(diff != 0, axis=2).sum()),
        }

    destination = ROOT / "scratch" / "etap5e4_direct_atlas_validation.json"
    destination.write_text(json.dumps(output, indent=2), encoding="utf-8")
    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
