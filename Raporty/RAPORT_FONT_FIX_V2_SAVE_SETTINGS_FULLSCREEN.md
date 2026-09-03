# RAPORT: Font Fix v2 + Save Settings + Fullscreen Preview + Frame Step

## TASK
Naprawienie 5 grup defektow UI/HUD.

## ROOT CAUSES

RC1: Font startup hardcoded Arial
controller.py L136: self.font_path = resolve_font_path(Arial)
_load_startup_preset nie odczytywal global.font z def_layout.json.

RC2: _STATIC_CACHE nie byl czyszczony
Przy zmianie fontu per-indicator czyszczono FONT_CACHE i GAUGE_RASTER_CACHE,
ale NIE _STATIC_CACHE (helpers.py). Klucz bg_key w gauge zawiera font_path.

## CHANGED FILES
- src/gui/qt/signals.py  (+sig_save_global_settings, +sig_global_font_restored)
- src/gui/qt/_mixins/preset_mixin.py  (font persistence, _STATIC_CACHE clearing)
- src/gui/qt/controller.py  (restore font_path from def_layout.json on startup)
- src/gui/qt/tabs/settings_tab.py  (+btn_save_settings, +_on_global_font_restored)
- src/gui/qt/widgets/video_preview.py  (+frame step buttons, +fullscreen)
- tests/test_font_persistence_v2.py  (6 tests)

## TESTS
test_save_global_settings_writes_font           PASS
test_save_global_settings_preserves_indicators  PASS
test_controller_restores_font_on_startup        PASS
test_static_cache_cleared_on_font_change        PASS
test_static_cache_cleared_on_indicator_font_change PASS
test_frame_step_calculation                     PASS
6/6 PASSED

Regression: 82/82 PASSED

## NOT TESTED (wymaga GUI runtime)
- Wizualne potwierdzenie gauge zmienia font
- Restart + przywrocony font w cmb_font
- Fullscreen ESC
- Frame step przycisk

## BACKEND ISOLATION
Nie zmieniono AMD/Intel/NVIDIA render path, FFmpeg pipeline, Direct Mux.

## STATUS: PASS (automatyczne), NOT TESTED (GUI smoke)