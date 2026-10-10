# RAPORT: AMD — MAP SHAPE UNDER PITCH, UI LEGACY CLEANUP, RESET LAYOUT CLEAN SLATE

**Data**: 2026-09-19  
**Środowisko**: AMD (`C:\_DEV\SportCamHUD-amd`), branch `amd-bikeridehud`  
**Autor**: Antigravity Assistant  
**Status**: COMPLETE (PASS)  
**CASE**: `CASE A` (wszystkie 3 zadania PASS)

---

## 1. Cel i Zakres Prac

Prace objęły dokładnie trzy zagadnienia w dedykowanym worktree AMD bez naruszania ścieżek NVIDIA i Intel:
1. **MAPA — zachowanie wybranego kształtu (shape) i obramowania (border) przy pochyleniu (pitch)**:
   - Pitch transformuje wyłącznie wewnętrzną treść mapy perspektywicznie, nie deformując obrysu widgetu ani jego obramowania.
   - Wybrany kształt (`square`, `rectangle`, `circle`/`round`, `rounded`/`rounded_rectangle`) oraz maska i ramka pozostają nienaruszoną geometrią zewnętrzną widgetu.
2. **UI — usunięcie słowa „Legacy” z widocznych dla użytkownika tekstów produkcyjnych**:
   - Usunięcie widocznego słowa „Legacy” z etykiet zakładek, selektorów, pól modelu i tooltipów.
   - Zachowanie wewnętrznych identyfikatorów kompatybilności wstecznej (np. `"legacy_cuda"`).
3. **RESETUJ UKŁAD — całkowicie pusty HUD (Clean Slate)**:
   - Kliknięcie „Resetuj układ” tworzy natychmiast czysty HUD (`INDICATOR_COUNT = 0`), zamiast przeładowywać `def_layout.json` czy przywracać predefiniowane wskaźniki.
   - Pełne wyczyszczenie zaznaczenia widgetu, panelu właściwości (`PropertyEditor`), geometrii hit-test (`bboxes`), stanu przeciągania oraz unieważnienie pamięci podręcznych HUD/compositora/mapy.
   - Zachowanie listy mediów, telemetrii FIT/GPMF, synchronizacji, punktów cięć i ustawień eksportu.

---

## 2. Podsumowanie Wymaganych Metryk

```text
MAP_ROOT_CAUSE=W moving_map.py i static_map.py funkcja apply_map_shape (maskująca kształt widgetu i rysująca border) była wywoływana PRZED apply_map_pitch. W efekcie funkcja apply_map_pitch rzutowała perspektywicznie cały wycięty obraz wraz z maską i borderem, zamieniając kwadrat/koło w zniekształcony trapez.
MAP_FIX=Odwrócono kolejność transformacji: najpierw apply_map_pitch na surowej powierzchni treści mapy, następnie apply_map_shape nakładające końcową maskę geometrii widgetu (square, rectangle, circle, rounded_rectangle) oraz rysujące obramowanie o stałej grubości, a na końcu apply_map_opacity. Rozszerzono apply_map_shape o pełną obsługę border_width i border_color oraz dodano clear_map_mask_caches().

SQUARE_PITCH_SHAPE_PRESERVED=PASS
CIRCLE_PITCH_SHAPE_PRESERVED=PASS
ROUNDED_PITCH_SHAPE_PRESERVED=PASS
MAP_BORDER_SHAPE_PRESERVED=PASS

VISIBLE_UI_LEGACY_BEFORE=4
VISIBLE_UI_LEGACY_AFTER=0

RESET_LAYOUT_ROOT_CAUSE=Metoda _on_reset_layout() wywoływała load_default_layout(), która odczytywała plik def_layout.json i przywracała zestaw domyślnych wskaźników (np. 15-20 widgetów v10), zamiast tworzyć czysty, pusty HUD. Ponadto nie czyściła stanu zaznaczenia w edytorze, panelu właściwości, ani buforów pamięci podręcznej.
RESET_LAYOUT_FIX=Zaimplementowano metodę LayoutManager.reset_to_empty(video_width, video_height), która inicjalizuje pusty słownik wskaźników {}. W _on_reset_layout() dodano pełne czyszczenie zaznaczenia (selected_indicator=None), czyszczenie bboxes i stanu przeciągania w VideoPreview (clear_editor_state()), czyszczenie PropertyEditor, unieważnienie pamięci podręcznych widoku i wskaźników, oznaczenie projektu jako zmodyfikowany (PROJECT_DIRTY=True) oraz zapis do pliku projektu .teleproject.

INDICATOR_COUNT_AFTER_RESET=0
PREVIEW_EMPTY_AFTER_RESET=True
STALE_WIDGET_COUNT_AFTER_RESET=0
PROPERTY_EDITOR_CLEARED=True
SELECTION_CLEARED=True
PROJECT_DIRTY_AFTER_RESET=True
RESET_PERSISTENCE_AFTER_REOPEN=True
MEDIA_PRESERVED=True
TELEMETRY_PRESERVED=True
EXPORT_SETTINGS_PRESERVED=True

AMD_RENDER_REGRESSION=NONE (PASS)
SAVE_LOAD_REGRESSION=NONE (PASS)

MODIFIED_FILES=src/indicators/helpers.py, src/indicators/moving_map.py, src/indicators/static_map.py, src/indicators/compositor.py, src/gui/qt/models.py, src/gui/qt/tabs/render_tab.py, src/gui/layout_manager.py, src/gui/qt/widgets/video_preview.py, src/gui/qt/_mixins/preview_mixin.py, src/gui/qt/_mixins/indicator_mixin.py, tests/test_multifile_hud_lifecycle.py
CREATED_FILES=tests/test_amd_map_shape_ui_legacy_reset.py, scratch/amd_ui_layout_cleanup/generate_artifacts.py
CASE=CASE A
```

---

## 3. Szczegóły Implementacji

### Zadanie 1: MAPA — Zachowanie Kształtu i Obramowania przy Pitch
- **Plik `src/indicators/helpers.py`**:
  - `apply_map_shape(img, shape, corner_radius, border_width, border_color)`: zaktualizowano o precyzyjne maskowanie antyaliasingiem dla kształtów: `square`, `rectangle`, `circle`/`round`, `rounded`/`rounded_rectangle`.
  - Dodano rysowanie obramowania o zadanym kolorze (`border_color`) i grubości (`border_width`) na wyjściowym kształcie widgetu po nałożeniu maski.
  - Zaimplementowano funkcję `clear_map_mask_caches()` do bezpiecznego zwalniania buforowanych masek kształtów.
- **Plik `src/indicators/moving_map.py`**:
  - W `render_map_working_image`, `render_map_unrotated_working_image` oraz `_render_moving_map_indicator` kolejność została zmieniona na:
    1. `apply_map_pitch(img, pitch)` (transformacja perspektywiczna treści mapy),
    2. `apply_map_shape(pitched, shape, ...)` (nałożenie ostatecznego kształtu i obramowania),
    3. `apply_map_opacity(shaped, opacity)`.
  - Dodano `clear_moving_map_renderers = clear_moving_map_cache` dla spójnego czyszczenia zasobów.
- **Plik `src/indicators/static_map.py`**:
  - W `_render_static_map_indicator` zaktualizowano potok renderowania do kolejności: pitch -> shape -> opacity.

### Zadanie 2: UI — Usunięcie słowa „Legacy” z Widocznych Etykiet
- **Plik `src/gui/qt/tabs/render_tab.py`**:
  - Zmieniono widoczną etykietę w liście wyboru backendu NVIDIA: `"NVIDIA Legacy CUDA"` -> `"NVIDIA CUDA"`.
  - Zachowano wewnętrzną wartość identyfikatora `userData`: `"legacy_cuda"` dla zachowania pełnej kompatybilności serializacji projektu i wywołań eksportu.
  - Zmieniono tekst tooltipa: usunięto słowo „legacy”, zastępując je zwrotem „Użyj CUDA encoder (NVIDIA)...”.
- **Plik `src/gui/qt/models.py`**:
  - Usunięto przyrostki `(legacy)` z etykiet pól:
    - `"Krok główny (legacy)"` -> `"Krok główny"`
    - `"Krok drobny (legacy)"` -> `"Krok drobny"`
  - Wzbogacono definicję zakładki kształtu mapy (`_map_shape_tab_fields`) o opcje wyboru: `square`, `rectangle`, `circle`, `rounded` oraz pola grubości i koloru obramowania.

### Zadanie 3: RESETUJ UKŁAD — Prawdziwy Clean Slate
- **Plik `src/gui/layout_manager.py`**:
  - Dodano metodę `reset_to_empty(video_width, video_height)`, która tworzy czysty układ z pustym słownikiem wskaźników (`"indicators": {}`).
- **Plik `src/gui/qt/widgets/video_preview.py`**:
  - Dodano metodę `clear_editor_state()` czyszczącą `_bboxes`, `_dragging_key`, `_drag_offset_norm` oraz odświeżającą nakładkę HUD i etykietę podglądu.
- **Plik `src/gui/qt/_mixins/preview_mixin.py`**:
  - Wzbogacono unieważnianie stanu wizualnego `_invalidate_layout_visual_state()`, dodając wywołanie `clear_reusable_canvases()`, `clear_moving_map_renderers()` i `clear_map_mask_caches()`.
- **Plik `src/gui/qt/_mixins/indicator_mixin.py`**:
  - Zastąpiono `_on_reset_layout`:
    1. Pobiera wymiary wideo i wywołuje `layout_mgr.reset_to_empty()`,
    2. Resetuje `selected_indicator = None`,
    3. Czyści stan edytora wideo podglądu poprzez `video_preview.clear_editor_state()`,
    4. Czyści formularz w `PropertyEditor` (`clear()` / wyłączenie edytora),
    5. Czyści listę wskaźników w drzewie/liście GUI,
    6. Unieważnia pamięć podręczną HUD i wymusza odrysowanie czystego podglądu wideo,
    7. Oznacza projekt jako zmodyfikowany (`mark_dirty()`),
    8. Zapisuje zaktualizowany pusty układ do pliku projektu `.teleproject`, gwarantując trwałość po ponownym otwarciu.

---

## 4. Wyniki Testów Automatycznych

### 4.1. Dedykowana Pętla Testowa: `tests/test_amd_map_shape_ui_legacy_reset.py`
Wszystkie 13 testów zakończyło się wynikiem **PASSED** (100%):
- `TestMapShapeAndPitch`:
  - `test_square_pitch_zero`: PASSED
  - `test_square_pitch_positive`: PASSED (kwadrat zachowany, treść pochylona)
  - `test_rectangle_pitch_positive`: PASSED (prostokąt zachowany, treść pochylona)
  - `test_circle_pitch_positive`: PASSED (koło zachowane, narożniki przezroczyste, obramowanie kołowe)
  - `test_rounded_rectangle_pitch_positive`: PASSED (zaokrąglone narożniki zachowane)
- `TestUILegacyCleanup`:
  - `test_zero_visible_legacy_strings_in_render_tab`: PASSED (0 wystąpień słowa Legacy)
  - `test_zero_visible_legacy_strings_in_models`: PASSED (0 wystąpień słowa Legacy)
  - `test_backend_id_remains_intact`: PASSED (identyfikator `"legacy_cuda"` zachowany)
- `TestResetLayoutCleanSlate`:
  - `test_a_reset_produces_empty_hud`: PASSED (`len(indicators) == 0`)
  - `test_b_reset_clears_selection_and_properties`: PASSED (brak ghost selection)
  - `test_c_add_indicator_after_reset_has_no_ghosts`: PASSED (po dodaniu dokładnie 1 wskaźnik)
  - `test_d_persistence_after_reset`: PASSED (po ponownym załadowaniu projektu 0 wskaźników)
  - `test_e_media_and_telemetry_preserved`: PASSED (media, telemetria, cięcia zachowane)

### 4.2. Testy Integracyjne Cyklu Życia HUD: `tests/test_multifile_hud_lifecycle.py`
Wszystkie 3 testy zakończyły się wynikiem **PASSED**:
- `test_multifile_input_snapshot_keeps_only_explicit_order`: PASSED
- `test_layout_visual_invalidation_preserves_telemetry_state`: PASSED
- `test_reset_replaces_full_layout_once`: PASSED

### 4.3. Testy Zarządzania Benchmarkiem AMD: `tests/test_amd_benchmark_governance.py`
Wszystkie 5 testów zakończyło się wynikiem **PASSED**:
- Brak regresji w mechanizmach governance i profilach AMD.

---

## 5. Artefakty Wygenerowane w `scratch/amd_ui_layout_cleanup/`

Zgodnie z wymogami specyfikacji, wygenerowano kompletną listę artefaktów wizualnych i tekstowych:
- `map_before_square.png` / `map_after_square.png`
- `map_before_circle.png` / `map_after_circle.png`
- `map_before_rounded.png` / `map_after_rounded.png`
- `reset_before.png` / `reset_after.png`
- `visible_legacy_strings_before.txt`
- `visible_legacy_strings_after.txt`
- `modified_files.txt`
- `created_files.txt`
- `reproduction_commands.txt`
- `artifacts_manifest.txt`
- `ntfy_result.txt`

---

## 6. Powiadomienie NTFY

Wysłano powiadomienie na adres `https://ntfy.sh/MalcerzPOP`:
- **Próba**: 1
- **Exit Code**: 0
- **Treść wiadomości**: `"AMD UI/layout: map shape=PASS, Legacy cleanup=PASS, reset=PASS, case=CASE A."`
- **Wynik**: `NTFY_SUCCESS=True` (potwierdzony w `scratch/amd_ui_layout_cleanup/ntfy_result.txt`).

---

## 7. Podsumowanie i Wnioski

Zadanie zrealizowano ściśle w wyznaczonym zakresie:
- Kształt i obramowanie widgetu mapy są w pełni zachowane przy dowolnym kącie nachylenia perspektywicznego (pitch).
- W interfejsie użytkownika nie występuje słowo „Legacy” w widocznych etykietach, a kompatybilność wewnętrzna została zachowana.
- Przycisk „Resetuj układ” tworzy całkowicie czysty HUD (`INDICATOR_COUNT = 0`), bez śladów ghost widgets i bez naruszania mediów czy telemetrii.
- Klasyfikacja końcowa: **CASE A**.
