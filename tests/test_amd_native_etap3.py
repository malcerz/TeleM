from pathlib import Path

from src.ffmpeg.amd_native_exporter import (
    AMD_NATIVE_ABI_VERSION,
    _coalesce_dirty_rects,
    _dirty_rects_from_bboxes,
)


ROOT = Path(__file__).resolve().parents[1]
NATIVE = ROOT / "native" / "d3d11_amf_pipeline" / "src"


def test_etap3_abi_and_region_entrypoint():
    assert AMD_NATIVE_ABI_VERSION >= 3
    source = (NATIVE / "telem_amd_native.cpp").read_text(encoding="utf-8")
    assert "telem_amd_update_hud_regions" in source
    assert "hudNativeCopyMs = 0.0" in source
    assert "telem_amd_get_etap3_stats" in source


def test_gpu_region_path_uploads_pointer_without_vector_copy():
    source = (NATIVE / "telem_amd_native.cpp").read_text(encoding="utf-8")
    region_path = source[source.index("TELEM_EXPORT int telem_amd_update_hud_regions"):]
    region_path = region_path[:region_path.index("TELEM_EXPORT int telem_amd_update_video_frame")]
    assert "currentHUDRGBA" not in region_path
    assert "memcpy" not in region_path
    assert "UpdateHUDTexture" in region_path


def test_overlapping_dirty_rects_merge_without_global_bbox():
    rects = [(10, 10, 100, 100), (50, 50, 100, 100), (1000, 1000, 20, 20)]
    merged = _coalesce_dirty_rects(rects, max_rects=4)
    assert (10, 10, 140, 140) in merged
    assert (1000, 1000, 20, 20) in merged
    assert len(merged) == 2


def test_dirty_rects_cover_previous_clear_and_current_draw():
    previous = {"speed": (100, 100, 50, 50)}
    current = {"speed": (200, 100, 50, 50)}
    rects = _dirty_rects_from_bboxes(previous, current, 400, 300, max_rects=8)
    assert any(x <= 60 and y <= 60 and x + w >= 190 and y + h >= 190 for x, y, w, h in rects)
    assert any(x <= 160 and y <= 60 and x + w >= 290 and y + h >= 190 for x, y, w, h in rects)


def test_gpu_export_path_has_no_full_image_tobytes():
    source = (ROOT / "src" / "ffmpeg" / "amd_native_exporter.py").read_text(encoding="utf-8")
    gpu_branch = source[source.index('else:\n                assert hud_backing is not None'):]
    gpu_branch = gpu_branch[:gpu_branch.index("if not hud_update_ok")]
    assert "composed_img.tobytes" not in gpu_branch
    assert "telem_amd_update_hud_regions" in gpu_branch

