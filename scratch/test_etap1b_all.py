import os
import sys
import json
import time
import shutil
import numpy as np
from PIL import Image

sys.path.insert(0, r"c:\_DEV\TeleM")

def run_tests():
    print("=" * 70)
    print("ETAP 1B VALIDATION & TESTS SUITE")
    print("=" * 70)
    
    out_dir = r"c:\_DEV\TeleM\scratch\etap1b_test"
    os.makedirs(out_dir, exist_ok=True)
    
    # 1. Test unit imports and DLL symbol loading
    print("\n--- 1. Testing DLL Symbol Loading ---")
    import ctypes
    if hasattr(os, "add_dll_directory"):
        os.add_dll_directory(r"C:\tools\mingw64\bin")
        os.add_dll_directory(r"c:\_DEV\TeleM\native\d3d11_amf_pipeline\bin")
    dll_path = r"c:\_DEV\TeleM\native\d3d11_amf_pipeline\bin\telem_amd_native.dll"
    dll = ctypes.CDLL(dll_path)
    
    assert hasattr(dll, "telem_amd_set_after_map_chart_mode"), "Missing telem_amd_set_after_map_chart_mode"
    assert hasattr(dll, "telem_amd_update_after_map_chart_static"), "Missing telem_amd_update_after_map_chart_static"
    assert hasattr(dll, "telem_amd_update_after_map_chart_dynamic"), "Missing telem_amd_update_after_map_chart_dynamic"
    assert hasattr(dll, "telem_amd_get_after_map_chart_stats"), "Missing telem_amd_get_after_map_chart_stats"
    print("[PASS] All ETAP 1B DLL symbols exported and loaded correctly.")

    # 2. Test short render with AMD_AFTER_MAP_CHART_GPU=1
    print("\n--- 2. Running 30-frame Smoke Test with AMD_AFTER_MAP_CHART_GPU=1 ---")
    from src.ffmpeg.amd_native_exporter import export_amd_d3d11va_native_stream
    
    video_path = r"c:\_DEV\TeleM\Video\GX010115.MP4"
    fit_path = r"c:\_DEV\TeleM\Video\Jazda_na_rowerze_w_porze_lunchu.fit"
    preset_path = r"c:\_DEV\TeleM\presets\cycling_dashboard_v10.json"
    
    with open(preset_path, "r", encoding="utf-8") as f:
        preset_data = json.load(f)
        
    os.environ["AMD_AFTER_MAP_CHART_GPU"] = "1"
    os.environ["AMD_AFTER_MAP_CHART_CAPTURE_DIAG"] = "1"
    
    out_mp4 = os.path.join(out_dir, "test_smoke_30f.mp4")
    if os.path.exists(out_mp4):
        os.remove(out_mp4)
        
    t0 = time.perf_counter()
    success = export_amd_d3d11va_native_stream(
        video_path=video_path,
        fit_path=fit_path,
        output_path=out_mp4,
        preset=preset_data,
        total_frames=30,
        sync_offset=2.0,
    )
    t1 = time.perf_counter()
    assert success, "export_amd_d3d11va_native_stream failed!"
    print(f"[PASS] 30 frames rendered successfully in {t1-t0:.2f}s ({(30/(t1-t0)):.1f} FPS)")

if __name__ == "__main__":
    run_tests()
