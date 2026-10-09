import hashlib
import os

files = [
    'src/ffmpeg/amd_config.py',
    'src/indicators/widget_cache.py',
    'def_layout.json',
    'src/gui/qt/signals.py',
    'src/render_preparation.py',
    'src/render_telemetry_cache.py',
    'src/telemetry_precompute.py',
    'src/ffmpeg/amd_child_process.py',
    'src/ffmpeg/streaming.py',
    'src/ffmpeg/amd_native_exporter.py',
    'src/gui/qt/_mixins/render_mixin.py',
    'src/gui/qt/controller.py',
    'src/gui/qt/tabs/render_tab.py',
    'src/startup_timeline.py',
    'src/runtime_paths.py',
    'src/gui/map_prefetch.py',
    'src/indicators/moving_map.py',
    'tests/test_common_render_preparation.py',
    'tests/test_amd_benchmark_governance.py',
    'tests/test_real_gui_startup_and_child_hash.py',
    'src/indicators/gauge.py',
    'src/indicators/__init__.py',
    'src/indicators/dispatcher.py',
    'src/indicators/compositor.py',
    'src/ffmpeg/nvidia_native_exporter.py',
    'tests/test_gauge_needle_width_parity.py',
    'Raporty/RAPORT_GAUGE_NEEDLE_WIDTH_PREVIEW_FINAL_PARITY.md',
    'src/gui/export_queue.py',
    'tests/test_youtube_upload_ui_disabled.py',
    'Raporty/RAPORT_YOUTUBE_UPLOAD_UI_DISABLED.md',
    'src/indicators/helpers.py',
    'src/indicators/lean.py',
    'src/indicators/bar.py',
    'src/indicators/text.py',
    'src/indicators/custom_text.py',
    'src/gui/qt/main_window.py',
    'src/gui/qt/_mixins/preset_mixin.py',
    'src/gui/qt/_mixins/preview_mixin.py',
    'src/gui/qt/_mixins/project_mixin.py',
    'src/gui/qt/tabs/load_tab.py',
    'src/gui/qt/tabs/settings_tab.py',
    'tests/test_gui_logic_degree_export_settings_cleanup.py',
    'Raporty/RAPORT_GUI_LOGIC_DEGREE_EXPORT_SETTINGS_CLEANUP.md',
    'src/telemetry_cache_manager.py',
    'tests/test_audio_cache.py',
    'AGENTS.md',
    'Raporty/RAPORT_LEGACY_AUDIO_CACHE_PERMANENT_REMOVAL.md',
    'src/gui/layout_manager.py',
    'tests/test_default_export_dir_settings.py',
    'Raporty/RAPORT_DEFAULT_EXPORT_DIR_SETTINGS.md',
    'src/integrations/auto_telemetry_preflight.py',
    'tests/test_auto_telemetry_preflight_suite.py',
    'tests/test_auto_telemetry_source_order.py',
    'tests/test_autofit_pre_load.py',
    'Raporty/RAPORT_AUTO_FIT_SELECTION_ASYNC.md',
    'Raporty/RAPORT_NVIDIA_AUDIO_LIVE_MUX_AND_AUTOFIT_PORTABLE_PARITY.md',
    'native/d3d11_amf_pipeline/src/d3d11_amf_encoder.h',
    'native/d3d11_amf_pipeline/src/d3d11_amf_encoder.cpp',
    'native/d3d11_amf_pipeline/src/d3d11_vp_pipeline.h',
    'native/d3d11_amf_pipeline/src/d3d11_vp_pipeline.cpp',
    'native/d3d11_amf_pipeline/src/telem_amd_native.cpp',
    'src/telemetry_resolver.py',
    'src/telemetry_extract.py',
    'tests/test_amd_qp_governance.py',
    'tests/test_video_orientation_governance.py',
    'scripts/test_orientation_real_hardware.py',
    'runtime/runtime_manifest.json',
    'Raporty/RAPORT_LIVE_QP_STATS_RESTORE.md',
    'Raporty/RAPORT_AMD_VIDEO_ORIENTATION_REGRESSION_FIX.md',
    'src/telemetry_dji.py',
    'tests/test_dji_action2_none_fix.py',
    'Raporty/RAPORT_DJI_ACTION2_TELEMETRY_NONE_MANAGER_FIX.md',
    'src/telemetry_active_time.py',
    'src/gui/telemetry_manager.py',
    'tests/test_load_tab_layout_action2.py',
    'Raporty/RAPORT_DJI_ACTION2_FULL_REGRESSION_FIX.md',
    'telemetry_fit.py',
    'src/indicators/frame_data.py',
    'src/ffmpeg/worker_cache.py',
    'tests/test_dji_action2_capability_probe.py',
    'tests/test_skip_pauses_parity.py',
    'Raporty/RAPORT_ACTION2_TELEMETRY_AND_SKIP_PAUSES_FINAL_PARITY.md',
]

autofit_files = [
    'src/integrations/auto_telemetry_preflight.py',
    'src/gui/qt/_mixins/project_mixin.py',
    'src/gui/qt/tabs/load_tab.py',
    'src/gui/qt/main_window.py',
    'src/gui/qt/tabs/settings_tab.py',
    'tests/test_auto_telemetry_source_order.py',
    'tests/test_auto_telemetry_preflight_suite.py',
    'tests/test_autofit_pre_load.py',
]

all_match = True
for f in files:
    p1 = os.path.join(r'C:\_DEV\BikeRideHUD-main-new', f)
    p2 = os.path.join(r'C:\_DEV\BikeRideHUD-portable', f)
    h1 = hashlib.sha256(open(p1, 'rb').read()).hexdigest()
    h2 = hashlib.sha256(open(p2, 'rb').read()).hexdigest()
    match = (h1 == h2)
    status = "MATCH" if match else "DIFF"
    print(f"{f}: {status} ({h1})")
    if not match:
        all_match = False

autofit_match = True
for f in autofit_files:
    p1 = os.path.join(r'C:\_DEV\BikeRideHUD-main-new', f)
    p2 = os.path.join(r'C:\_DEV\BikeRideHUD-portable', f)
    h1 = hashlib.sha256(open(p1, 'rb').read()).hexdigest()
    h2 = hashlib.sha256(open(p2, 'rb').read()).hexdigest()
    if h1 != h2:
        autofit_match = False

# AMD DLL Parity
dll_rel = r'runtime\amd\bin\telem_amd_native.dll'
dll1 = os.path.join(r'C:\_DEV\BikeRideHUD-main-new', dll_rel)
dll2 = os.path.join(r'C:\_DEV\BikeRideHUD-portable', dll_rel)
h_dll1 = hashlib.sha256(open(dll1, 'rb').read()).hexdigest()
h_dll2 = hashlib.sha256(open(dll2, 'rb').read()).hexdigest()
dll_match = (h_dll1 == h_dll2)
print(f"{dll_rel}: {'MATCH' if dll_match else 'DIFF'} ({h_dll1})")

print(f"AUTO_FIT_HASH_PARITY={'YES' if autofit_match else 'NO'}")
print(f"SOURCE_HASH_PARITY={'YES' if all_match else 'NO'}")
print(f"AMD_NATIVE_DLL_HASH_PARITY={'YES' if dll_match else 'NO'}")

