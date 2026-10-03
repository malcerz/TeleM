"""Route/marker stay visible without tiles, and background work is bounded."""
from datetime import datetime, timedelta, timezone
import io
import threading
import time
import subprocess
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from src.indicators.dispatcher import render_value_indicator
from src.gui.map_viewport_prefetch import PreviewViewportPrefetch, preview_viewport_prefetch
from src.indicators.moving_map import clear_moving_map_cache
from src import moving_map, map_renderer


@pytest.fixture
def cold_cache(tmp_path, monkeypatch):
    original_init = moving_map.TileCache.__init__
    monkeypatch.setattr(moving_map.TileCache, "__init__", lambda self, cache_dir=None: original_init(self, tmp_path))
    monkeypatch.setattr(moving_map.TileCache, "_mem", {})
    monkeypatch.setattr(moving_map.TileCache, "_mem_order", [])
    monkeypatch.setattr(moving_map, "_shared_cache", moving_map.TileCache(tmp_path))
    monkeypatch.setattr(moving_map, "_download_tile_raw", lambda *args: None)
    monkeypatch.setattr(map_renderer, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(map_renderer, "_TILE_CACHE", {})
    monkeypatch.setattr(map_renderer, "_PREVIEW_TILE_CACHE", {})
    monkeypatch.setattr(preview_viewport_prefetch, "schedule", lambda *args: False)
    clear_moving_map_cache()
    yield moving_map.get_shared_tile_cache()
    clear_moving_map_cache()


def render(form="map", orientation="north_up", async_map=True):
    start = datetime(2026, 10, 2, tzinfo=timezone.utc)
    track = [(start, 54.33, 18.597), (start + timedelta(seconds=100), 54.331, 18.598)]
    cfg = dict(enabled=True, form=form, x=10, y=10, size=25, zoom=16,
               map_orientation=orientation, marker_color="#FFFFFF", track_color="#FF3C1E")
    result = render_value_indicator(800, 600, {"indicators": {"track_map": cfg}},
                                   "", "track_map", 0, "", "", gps_track=track,
                                   target_dt=start + timedelta(seconds=50), map_heading=45,
                                   async_map=async_map)
    return result


def visibility(image):
    rgb = np.asarray(image)[:, :, :3]
    return bool(((rgb[:, :, 0] > 180) & (rgb[:, :, 1] < 110) & (rgb[:, :, 2] < 100)).any()), bool((rgb.min(axis=2) > 240).any())


@pytest.mark.parametrize("coverage", [0.0, 0.25, 0.49, 1.0])
@pytest.mark.parametrize("orientation", ["north_up", "track_up"])
def test_moving_always_draws_route_and_marker(cold_cache, monkeypatch, coverage, orientation):
    monkeypatch.setattr(moving_map.MovingMapRenderer, "viewport_tile_coverage", lambda *args: coverage)
    monkeypatch.setenv("TELEM_INTEL_GPU_MAP", "1")
    image, _, _, _ = render(orientation=orientation)
    assert image is not None
    assert visibility(image) == (True, True)


@pytest.mark.parametrize("form", ["map", "static_map"])
def test_tiles_appear_at_same_position_after_cache_fill(cold_cache, form):
    before, x, y, _ = render(form)
    assert visibility(before) == (True, True)
    raw = io.BytesIO()
    Image.new("RGBA", (256, 256), (80, 150, 180, 255)).save(raw, format="PNG")
    zooms = [15, 16]  # Moving preview uses the canvas-relative detail zoom.
    for zoom in zooms:
        tx, ty, _, _ = moving_map._lat_lon_to_tile(54.3305, 18.5975, zoom)
        for xx in range(tx-3, tx+4):
            for yy in range(ty-3, ty+4):
                cold_cache.put(zoom, xx, yy, "light_all", raw.getvalue())
    after, x2, y2, _ = render(form)
    assert (x2, y2, after.size) == (x, y, before.size)
    assert visibility(after) == (True, True)
    assert np.any(np.asarray(before) != np.asarray(after))
    # Exact route/marker masks keep their geometry as only the backdrop changes.
    for mask in [lambda rgb: (rgb[:,:,0] > 180) & (rgb[:,:,1] < 110) & (rgb[:,:,2] < 100),
                 lambda rgb: rgb[:,:,:3].min(axis=2) > 240]:
        assert np.array_equal(mask(np.asarray(before)), mask(np.asarray(after)))


def test_one_worker_deduplicates_frames_and_bounds_pending_requests():
    manager = PreviewViewportPrefetch()
    entered, release = threading.Event(), threading.Event()
    calls = []
    def blocked():
        calls.append("viewport")
        entered.set()
        release.wait(2)
    assert manager.schedule("viewport", blocked)
    assert entered.wait(1)
    for _ in range(2000):
        assert not manager.schedule("viewport", blocked)
    for i in range(100):
        manager.schedule(i, lambda: None)
    assert manager.threads_started == 1 and len(manager._pending) <= 8
    release.set()
    deadline = time.monotonic()+2
    while manager.revision == 0 and time.monotonic() < deadline:
        time.sleep(.005)
    assert calls == ["viewport"]
    assert not manager.schedule("viewport", blocked)


@pytest.mark.parametrize("module_name,function_name,orientation", [
    ("src/indicators/moving_map.py", "_render_moving_map_indicator", "north_up"),
    ("src/indicators/moving_map.py", "_render_moving_map_indicator", "track_up"),
    ("src/indicators/static_map.py", "_render_static_map_indicator", "north_up"),
])
def test_export_branch_matches_git_baseline_pixels(cold_cache, monkeypatch, module_name, function_name, orientation):
    raw = io.BytesIO()
    Image.new("RGBA", (256, 256), (80, 150, 180, 255)).save(raw, format="PNG")
    for zoom in (15,16):
        tx,ty,_,_ = moving_map._lat_lon_to_tile(54.3305,18.5975,zoom)
        for xx in range(tx-3,tx+4):
            for yy in range(ty-3,ty+4):
                cold_cache.put(zoom,xx,yy,"light_all",raw.getvalue())
    # Load the committed indicator entry point as the actual before-reference.
    git_root = Path(__file__).resolve().parents[1]
    if not (git_root / ".git").exists():
        pytest.skip("Pixel baseline comparison requires the Git checkout")
    source = subprocess.check_output(["git", "-C", str(git_root), "show", "HEAD:"+module_name]).decode()
    namespace = {"__name__": "baseline_indicator", "__file__": module_name}
    exec(compile(source, module_name, "exec"), namespace)
    original = namespace[function_name]
    from src.indicators import dispatcher
    current = getattr(dispatcher, function_name)
    monkeypatch.setattr(dispatcher, function_name, original)
    before, x, y, _ = render(form="map" if "moving" in module_name else "static_map", orientation=orientation, async_map=False)
    monkeypatch.setattr(dispatcher, function_name, current)
    after, x2, y2, _ = render(form="map" if "moving" in module_name else "static_map", orientation=orientation, async_map=False)
    assert before is not None and after is not None
    assert (x2,y2,after.size) == (x,y,before.size)
    assert visibility(after) == (True,True)
    assert np.array_equal(np.asarray(before),np.asarray(after))
