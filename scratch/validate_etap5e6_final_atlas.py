"""ETAP 5E.6: final Direct-Region atlas parity for dynamic-layer cache."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scratch.validate_etap5b6_direct import H, N, W, setup
from scratch.validate_etap5e4_direct_atlas import _data_for
from src.ffmpeg.frame_renderer import _direct_region_members
from src.ffmpeg.worker_cache import WORKER_CACHE
from src.indicators.chart import set_dynamic_layer_cache_enabled
from src.indicators.compositor import compose_overlay


def _render(layout, regions, owners, data):
    atlas = Image.new("RGBA", layout["_nvidia_atlas_size"], (0, 0, 0, 0))
    for region, members in zip(regions, owners):
        dest_x, dest_y, atlas_x, atlas_y, _rw, _rh = region
        compose_overlay(
            W, H, layout, "", _bboxes={}, reuse_canvas=False,
            target_image=atlas,
            coordinate_origin=(dest_x - atlas_x, dest_y - atlas_y),
            render_keys=set(members),
            destination_proven_empty=True,
            **data,
        )
    return atlas


def main():
    layout, regions, _anchor, *_ = setup()
    histories = WORKER_CACHE["_precomputed_chart_data"]
    telemetry = WORKER_CACHE["_telemetry_cache"]
    owners = _direct_region_members(layout, regions)
    result = {}
    for frame in (0, 540, 1350, 2700, 4050, 4860, 5399):
        data = _data_for(frame, histories, telemetry)
        set_dynamic_layer_cache_enabled(False)
        reference = _render(layout, regions, owners, data)
        set_dynamic_layer_cache_enabled(True)
        candidate = _render(layout, regions, owners, data)
        delta = np.abs(np.asarray(reference, dtype=np.int16) - np.asarray(candidate, dtype=np.int16))
        result[str(frame)] = {
            "max_diff": int(delta.max()),
            "different_pixels": int(np.any(delta != 0, axis=2).sum()),
        }
    set_dynamic_layer_cache_enabled(True)
    destination = ROOT / "scratch" / "etap5e6_final_atlas_validation.json"
    destination.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
