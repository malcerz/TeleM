from pathlib import Path

from src.ffmpeg.amd_native_exporter import AMD_NATIVE_ABI_VERSION, _AMD_HUD_MODES


ROOT = Path(__file__).resolve().parents[1]
NATIVE = ROOT / "native" / "d3d11_amf_pipeline" / "src"


def test_etap2_uses_new_abi_and_explicit_modes():
    assert AMD_NATIVE_ABI_VERSION >= 2
    assert _AMD_HUD_MODES == {"CPU_REFERENCE": 0, "GPU_HUD": 1}


def test_gpu_hud_uses_complete_direct_nv12_compositor():
    source = (NATIVE / "d3d11_vp_pipeline.cpp").read_text(encoding="utf-8")
    assert "bool D3D11VideoProcessorPipeline::ComposeHUDDirectNV12" in source
    assert "VideoProcessor has already produced the normal base NV12 output" in source
    assert "RWTexture2D<float> OutputY" in source
    assert "RWTexture2D<float2> OutputUV" in source
    assert "m_context->Dispatch" in source


def test_gpu_hud_keeps_cpu_reference_but_does_not_call_it():
    source = (NATIVE / "telem_amd_native.cpp").read_text(encoding="utf-8")
    assert "static void BlendRGBAToNV12" in source
    assert "ctx->hudMode == 0" in source
    assert "ctx->hudMode == 1" in source


def test_hud_upload_is_rgba_without_native_swizzle_or_premultiply():
    source = (NATIVE / "d3d11_vp_pipeline.cpp").read_text(encoding="utf-8")
    create_hud = source[source.index("bool D3D11VideoProcessorPipeline::UpdateHUDTexture"):]
    create_hud = create_hud[:create_hud.index("bool D3D11VideoProcessorPipeline::ProcessFrame")]
    assert "DXGI_FORMAT_R8G8B8A8_UNORM" in create_hud
    assert "UpdateSubresource" in create_hud
    assert "std::vector<uint8_t> hudBytes" not in create_hud
    assert "std::swap" not in create_hud
