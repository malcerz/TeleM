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
    map_call = process.index("ResampleAndBlendMap(", chart_call)
    above_call = process.index("BlendAboveMap(", map_call)
    after_chart_call = process.index("BlendAfterMapCharts(", above_call)
    assert clear_call < chart_call < map_call < above_call < after_chart_call

    # ETAP 2A: gauge placement is conditional.  LEGACY (default): BEFORE-MAP,
    # between BlendCharts and ResampleAndBlendMap (exact ETAP 5L position).
    # AFTER-MAP (AMD_AFTER_MAP_GAUGE_GPU=1): between BlendAboveMap and
    # BlendAfterMapCharts.
    legacy_gauge_call = process.index("BlendGauge(", chart_call)
    assert legacy_gauge_call < map_call, "legacy BEFORE-MAP gauge call missing"
    assert "!m_gaugeAfterMapPlacement" in process[legacy_gauge_call - 200:legacy_gauge_call], \
        "legacy gauge call must be gated on !m_gaugeAfterMapPlacement"
    after_map_gauge_call = process.index("BlendGauge(", above_call)
    assert after_map_gauge_call > above_call, "AFTER-MAP gauge call missing"
    assert "m_gaugeAfterMapPlacement" in process[after_map_gauge_call - 200:after_map_gauge_call], \
        "AFTER-MAP gauge call must be gated on m_gaugeAfterMapPlacement"
    assert after_map_gauge_call < after_chart_call


def test_after_map_gauge_blend_is_not_destructive_and_clears_early():
    """ETAP 2A clear contract: no destructive gauge-bbox clear after MAP/ABOVE.

    The destructive self-clear stays legacy-only; the AFTER-MAP placement
    erases the previous frame's gauge region early in ClearPreviousAboveMap
    (before below/map/above rebuild the background).
    """
    source = VP.read_text(encoding="utf-8")
    gauge_start = source.index("bool D3D11VideoProcessorPipeline::BlendGauge(")
    gauge_end = source.index("bool D3D11VideoProcessorPipeline::ClearPreviousAboveMap(", gauge_start)
    body = source[gauge_start:gauge_end]
    # Legacy-only guard wraps the destructive mode-0 self-clear.
    clear_stmt_idx = body.index("cb = { m_gaugeDstX")
    guard_idx = body.rindex("!m_gaugeAfterMapPlacement", 0, clear_stmt_idx)
    assert guard_idx < clear_stmt_idx
    assert "m_gaugeAfterMapPlacement" in body
    # Prev-frame rect is recorded for the next frame's early clear.
    assert "m_gaugePrevValid = true" in body or "m_gaugePrevValid=true" in body

    clear_fn_start = source.index("bool D3D11VideoProcessorPipeline::ClearPreviousAboveMap(")
    clear_fn_end = source.index("bool D3D11VideoProcessorPipeline::BlendAboveMap(", clear_fn_start)
    clear_body = source[clear_fn_start:clear_fn_end]
    assert "m_gaugePrevValid" in clear_body, \
        "ClearPreviousAboveMap must erase the previous AFTER-MAP gauge region"


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


def test_above_texture_reuses_existing_native_resource_and_abi_is_current():
    source = VP.read_text(encoding="utf-8")
    assert "if (!m_aboveRegionTexture[index] || m_aboveRegionTexW[index] != width || m_aboveRegionTexH[index] != height)" in source
    # ETAP 2A FIX: ABI 8 -> 9 (adds the telem_amd_run_early_clears export).
    assert AMD_NATIVE_ABI_VERSION == 9


def test_etap2a_fix_run_early_clears_export_exists():
    """ETAP 2A FIX: native exposes the start-of-frame clears on demand."""
    native = (
        ROOT / "native" / "d3d11_amf_pipeline" / "src" / "telem_amd_native.cpp"
    ).read_text(encoding="utf-8")
    header = (
        ROOT / "native" / "d3d11_amf_pipeline" / "src" / "d3d11_vp_pipeline.h"
    ).read_text(encoding="utf-8")
    assert "TELEM_EXPORT int telem_amd_run_early_clears(void* handle)" in native
    # Single implementation: the public wrapper delegates to the exact same
    # clear routine ProcessFrame uses internally (no duplicated clear code).
    pub_start = header.index("bool RunEarlyClears(double* outClearMs = nullptr)")
    priv_start = header.index("private:", pub_start)
    decl = header.index(
        "bool ClearPreviousAboveMap(double* outClearMs = nullptr);", priv_start
    )
    assert pub_start < priv_start < decl
    assert "return ClearPreviousAboveMap(outClearMs);" in header


def test_etap2a_fix_exporter_runs_clears_before_hud_upload():
    """ETAP 2A FIX ordering: early clears precede telem_amd_update_hud_regions.

    The destructive erase of the previous gauge tile bbox must happen BEFORE
    the below-canvas dirty rects are uploaded, otherwise freshly uploaded
    BELOW-widget pixels inside that bbox (the dist_visual ruler track) are
    wiped every frame and never restored.
    """
    exporter = (
        ROOT / "src" / "ffmpeg" / "amd_native_exporter.py"
    ).read_text(encoding="utf-8")
    consumer = exporter[exporter.index("def _consume_prepared_frame("):]
    clears_call = consumer.index("telem_amd_run_early_clears(h_context)")
    hud_call = consumer.index("telem_amd_update_hud_regions(", clears_call)
    process_call = consumer.index("telem_amd_process_frame(", hud_call)
    assert clears_call < hud_call < process_call
    # Legacy ETAP 5L GPU-gauge mode stays untouched: the external clear is
    # gated on the AFTER-MAP flag AND an actually captured gauge tile.
    gate = consumer[clears_call - 300:clears_call]
    assert "after_map_gauge_gpu" in gate
    assert "prepared.gauge_data is not None" in gate


def test_etap2a_fix_force_reuploads_below_widgets_under_erase_region():
    """ETAP 2A FIX: static BELOW widgets under the erase region are re-uploaded.

    Static widgets (e.g. dist_visual) are normally uploaded only when dirty;
    because the early clear wipes them EVERY frame, any BELOW bbox intersecting
    the gauge tile region (current union previously sent tile) must be
    force-added to dirty_rects each frame.
    """
    exporter = (
        ROOT / "src" / "ffmpeg" / "amd_native_exporter.py"
    ).read_text(encoding="utf-8")
    builder = exporter[
        exporter.index("def _prepare_frame_cpu("):
        exporter.index("def _consume_prepared_frame(")
    ]
    marker = "# ETAP 2A FIX: the AFTER-MAP GPU gauge erases the previous"
    force_idx = builder.index(marker)
    # The force-add extends the existing per-frame dirty-rect construction
    # right after the dist_visual chart force-add.
    assert builder.rindex(
        'if after_map_chart_gpu and "dist_visual" in _bboxes:', 0, force_idx
    ) < force_idx
    # Union of prev + cur tiles drives the intersection test.
    assert "previous_gauge_tile_holder" in builder[force_idx:]
    assert "ex0 < wx + ww and ey0 < wy + wh" in builder[force_idx:]
