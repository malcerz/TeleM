from src.ffmpeg.amd_native_exporter import _resolve_amd_decode_mode


def test_cpu_reference_hud_does_not_use_gpu_decode_surface():
    assert _resolve_amd_decode_mode(
        "CPU_REFERENCE", "GPU_HUD_D3D11VA"
    ) == ("GPU_HUD_CPU_DECODE_REFERENCE", False)


def test_gpu_hud_keeps_d3d11va_decode():
    assert _resolve_amd_decode_mode(
        "GPU_HUD", "GPU_HUD_D3D11VA"
    ) == ("GPU_HUD_D3D11VA", True)
