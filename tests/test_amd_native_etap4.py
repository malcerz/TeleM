from pathlib import Path

from src.ffmpeg.amd_native_exporter import AMD_NATIVE_ABI_VERSION, _AMD_DECODE_MODES


ROOT = Path(__file__).resolve().parents[1]
NATIVE = ROOT / "native" / "d3d11_amf_pipeline" / "src"


def test_etap4_abi_and_explicit_decode_modes():
    assert AMD_NATIVE_ABI_VERSION >= 4
    assert _AMD_DECODE_MODES["GPU_HUD_CPU_DECODE_REFERENCE"] == 0
    assert _AMD_DECODE_MODES["GPU_HUD_D3D11VA"] == 1


def test_d3d11va_path_exposes_source_reader_surface_api():
    source = (NATIVE / "telem_amd_native.cpp").read_text(encoding="utf-8")
    assert "telem_amd_read_video_sample" in source
    assert "IMFDXGIBuffer" in source
    assert "dxgiBuffer->GetResource" in source
    assert "MF_SOURCE_READERF_STREAMTICK" in source
    assert "MF_SOURCE_READERF_ENDOFSTREAM" in source


def test_d3d11va_process_path_never_uploads_cpu_nv12():
    source = (NATIVE / "telem_amd_native.cpp").read_text(encoding="utf-8")
    process = source[source.index("TELEM_EXPORT int telem_amd_process_frame"):]
    process = process[:process.index("TELEM_EXPORT int telem_amd_flush")]
    assert "ctx->pPendingDecodedTex" in process
    assert "CopySubresourceRegion" in process
    assert "telem_amd_update_video_frame" not in process


def test_vp_can_consume_decoder_subresource_directly():
    source = (NATIVE / "d3d11_vp_pipeline.cpp").read_text(encoding="utf-8")
    assert "D3D11VideoProcessorPipeline::CanUseInputSurface" in source
    assert "viewDesc.Texture2D.ArraySlice = arrayIndex" in source
    assert "VideoProcessorSetStreamRotation" in source


def test_d3d11va_range_conversion_is_explicit_and_isolated():
    source = (NATIVE / "d3d11_vp_pipeline.cpp").read_text(encoding="utf-8")
    assert "D3D11VideoProcessorPipeline::NormalizeD3D11VARangeNV12" in source
    assert "219u * yValue" in source
    assert "centered * 224" in source
    assert "for (UINT pass = 0; pass < 2; ++pass)" in source
    native = (NATIVE / "telem_amd_native.cpp").read_text(encoding="utf-8")
    process = native[native.index("TELEM_EXPORT int telem_amd_process_frame"):]
    process = process[:process.index("TELEM_EXPORT int telem_amd_flush")]
    assert "doHUD, d3d11Decode" in process


def test_python_d3d11va_branch_does_not_start_rawvideo_pipe():
    source = (ROOT / "src" / "ffmpeg" / "amd_native_exporter.py").read_text(
        encoding="utf-8"
    )
    pipe_setup = source[source.index("cmd_decode: list[str] | None = None"):]
    pipe_setup = pipe_setup[:pipe_setup.index("# Main Frame Processing Loop")]
    assert "if not use_d3d11va:" in pipe_setup
    assert '"pipe:1"' in pipe_setup
    assert "FFmpeg rawvideo decoder pipe: OFF" in pipe_setup
