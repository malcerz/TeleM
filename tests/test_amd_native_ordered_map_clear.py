from pathlib import Path

from PIL import Image

from src.ffmpeg.amd_native_exporter import AMD_NATIVE_ABI_VERSION


ROOT = Path(__file__).resolve().parents[1]
VP = ROOT / "native" / "d3d11_amf_pipeline" / "src" / "d3d11_vp_pipeline.cpp"


def test_clear_previous_above_is_before_current_gpu_layers():
    source = VP.read_text(encoding="utf-8")
    process = source[source.index("bool D3D11VideoProcessorPipeline::ProcessFrame("):]
    clear_call = process.index("ClearPreviousAboveMap(")
    chart_call = process.index("BlendCharts(", clear_call)
    gauge_call = process.index("BlendGauge(", chart_call)
    map_call = process.index("ResampleAndBlendMap(", gauge_call)
    above_call = process.index("BlendAboveMap(", map_call)
    assert clear_call < chart_call < gauge_call < map_call < above_call


def test_blend_above_has_no_destructive_previous_bbox_clear():
    source = VP.read_text(encoding="utf-8")
    start = source.index("bool D3D11VideoProcessorPipeline::BlendAboveMap(")
    end = source.index("void D3D11VideoProcessorPipeline::ReleaseGaugeResources()", start)
    body = source[start:end]
    assert "dispatch(m_aboveMapPrev" not in body
    assert "m_aboveRegions" in body and "m_aboveRegionSRV" in body


def test_clear_order_preserves_underlying_map_and_below_oracle():
    """Small RGBA oracle for the corrected lifecycle order.

    This models the native shared HUD target: clear old above before current
    below/map, then blend current above.  It explicitly checks the old bbox
    after None and movement transitions.
    """
    base = Image.new("RGBA", (32, 24), (0, 0, 0, 0))
    below = Image.new("RGBA", (32, 24), (30, 40, 50, 255))
    map_layer = Image.new("RGBA", (32, 24), (70, 100, 140, 180))
    text_a = Image.new("RGBA", (8, 5), (240, 240, 240, 220))
    text_b = Image.new("RGBA", (5, 8), (240, 240, 240, 220))
    old = (4, 5, 8, 5)
    new = (18, 10, 5, 8)

    # Frame A.
    frame = Image.alpha_composite(base, below)
    frame = Image.alpha_composite(frame, map_layer)
    frame.alpha_composite(text_a, old[:2])
    oracle_after_a = frame.copy()

    # Frame B: clear old above first, rebuild under-layers, draw moved text.
    frame = Image.alpha_composite(base, below)
    frame = Image.alpha_composite(frame, map_layer)
    frame.alpha_composite(text_b, new[:2])
    oracle_after_b = frame.copy()

    old_box = (old[0], old[1], old[0] + old[2], old[1] + old[3])
    new_box = (new[0], new[1], new[0] + new[2], new[1] + new[3])
    assert frame.crop(old_box) == oracle_after_b.crop(old_box)
    assert frame.crop(new_box) == oracle_after_b.crop(new_box)
    assert frame != oracle_after_a


def test_above_texture_reuses_existing_native_resource_and_abi_is_unchanged():
    source = VP.read_text(encoding="utf-8")
    assert "if (!m_aboveRegionTexture[index] || m_aboveRegionTexW[index] != width || m_aboveRegionTexH[index] != height)" in source
    assert AMD_NATIVE_ABI_VERSION == 8
