"""ETAP 5E.5: compare direct atlas transfer with fast path disabled."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scratch.validate_etap5e4_direct_atlas import _data_for
from scratch.validate_etap5b6_direct import FPS, H, N, W, setup
from src.ffmpeg.frame_renderer import _direct_region_members
from src.ffmpeg.worker_cache import WORKER_CACHE
from src.indicators.compositor import compose_overlay


def _render(layout, regions, owners, data, proven):
    atlas_size = layout["_nvidia_atlas_size"]
    atlas = Image.new("RGBA", atlas_size, (0, 0, 0, 0))
    for region, members in zip(regions, owners):
        dest_x, dest_y, atlas_x, atlas_y, _rw, _rh = region
        compose_overlay(
            W, H, layout, "", _bboxes={}, reuse_canvas=False,
            target_image=atlas,
            coordinate_origin=(dest_x - atlas_x, dest_y - atlas_y),
            render_keys=set(members),
            destination_proven_empty=proven,
            **data,
        )
    return atlas


def main():
    layout, regions, _anchor, *_ = setup()
    histories = WORKER_CACHE["_precomputed_chart_data"]
    telemetry = WORKER_CACHE["_telemetry_cache"]
    owners = _direct_region_members(layout, regions)
    output = {"checkpoints": {}, "rotations": {}}
    for frame in (0, 540, 1350, 2700, 4050, 4860, 5399):
        data = _data_for(frame, histories, telemetry)
        reference = _render(layout, regions, owners, data, False)
        fast = _render(layout, regions, owners, data, True)
        a, b = np.asarray(reference), np.asarray(fast)
        diff = np.abs(a.astype(np.int16) - b.astype(np.int16))
        output["checkpoints"][str(frame)] = {
            "max_diff": int(diff.max()),
            "different_pixels": int(np.any(diff != 0, axis=2).sum()),
        }

    for rotation in (0, 90, 180, 270):
        test_layout = {**layout, "indicators": {
            key: dict(value) for key, value in layout.get("indicators", {}).items()
        }}
        for key in ("fit_cadence_text", "fit_heart_rate_text"):
            test_layout["indicators"][key]["rotation"] = rotation
        data = _data_for(2700, histories, telemetry)
        reference = _render(test_layout, regions, owners, data, False)
        fast = _render(test_layout, regions, owners, data, True)
        a, b = np.asarray(reference), np.asarray(fast)
        diff = np.abs(a.astype(np.int16) - b.astype(np.int16))
        output["rotations"][str(rotation)] = {
            "max_diff": int(diff.max()),
            "different_pixels": int(np.any(diff != 0, axis=2).sum()),
        }

    destination = ROOT / "scratch" / "etap5e5_atlas_fast_validation.json"
    destination.write_text(json.dumps(output, indent=2), encoding="utf-8")
    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
