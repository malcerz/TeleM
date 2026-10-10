# RAPORT: AMD MAP CACHE & RE-ADD FIX

Data: 2026-09-19
Autor: Antigravity AI
Worktree: `C:\_DEV\SportCamHUD-amd`
Branch: `amd-bikeridehud`

---

## 1. PODSUMOWANIE WYKONAWCZE

Zgodnie z wymaganiami zadania rozwiązano problem ponownego pojawiania się komunikatu „Ładowanie mapy…” oraz degradacji geometrii (niepożądane ciemnoszare marginesy / letterboxing, zniekształcony aspect ratio) po usunięciu i ponownym dodaniu widgetu mapy (`Delete Map Widget` → `Add Map`).

Dokonano jednoznacznego rozdzielenia:
1. **MAP DATA CACHE (Project-Level / Persistent)**:
   - Pobrane i zdekodowane kafelki (TileCache SQLite + pamięć LRU),
   - Instancje `MovingMapRenderer` (złożone siatki kafelków, wstępnie przeliczone rzutowania współrzędnych GPS, wyrenderowana trasa GPX/FIT),
   - Obiekt `MapContext` powiązany z załadowanym plikiem wideo/FIT.
2. **MAP WIDGET INSTANCE STATE (Widget-Level)**:
   - Geometria widgetu (bounding box, pozycja X/Y, rozmiar W/H),
   - Zaznaczenie w UI (selection rect, uchwyty transformacji),
   - Lokalne ustawienia prezentacji (kształt, zaokrąglenie rogów, obramowanie, pitch, przezroczystość),
   - Aktywny wpis w słowniku `indicators`.

Usunięcie widgetu mapy oraz operacja `Resetuj układ` usuwają wyłącznie instancję widgetu i stan kompozytora UI. Pamięć podręczna danych mapowych projektu pozostaje w 100% nienaruszona.

---

## 2. METRYKI I PARAMETRY OBOWIĄZKOWE

```text
ROOT_CAUSE_RELOAD=
1. Default indicator config mismatch: _create_indicator("track_map") domyślnie tworzył konfigurację source="gpmf" oraz map_style="light_all", podczas gdy projekt miał aktywny source="fit" oraz map_style="satellite". Powodowało to pusty track GPS dla GPMF oraz niezgodność dostawcy kafelków snap["provider"] != map_style, zmuszając _render_moving_map_indicator do zwrócenia placeholdera "Ładowanie mapy…" i asynchronicznego pobierania kafelków od zera.
2. Premature cache purge: _clear_caches() w controller.py wywoływał bezwarunkowo clear_moving_map_cache() przy każdej edycji dowolnej właściwości widgetu w UI.
3. Over-eager layout reset: _on_reset_layout() w indicator_mixin.py wywoływał clear_moving_map_renderers(), kasując złożone siatki kafelków i rzutowania tras GPS.
4. Unstable track cache key: Użycie id(gps_track) jako klucza pamięci podręcznej powodowało chybienia cache przy operacjach na instancjach obiektu trasy. Zastąpiono deterministycznym _track_cache_identity(gps_track).
5. Aspect ratio & margins distortion: W map_prepare.py funkcja render_overview_map skalowała obraz zastępczy za pomocą img.thumbnail((w, h)) i wklejała go w stały ciemnoszary kwadrat (30, 30, 30, 255), tworząc marginesy 75-85px po bokach/góra-dół. Zastąpiono skalowaniem proporcjonalnym z wypełnieniem (aspect-fill).

MAP_CACHE_SCOPE_BEFORE=Wiązany ze stanem instancji widgetu; niszczony przez _clear_caches() przy modyfikacji parametrów oraz _on_reset_layout().
MAP_CACHE_SCOPE_AFTER=Rozdzielony: dane źródłowe (TileCache, MovingMapRenderer, MapContext) żyją na poziomie projektu i są czyszczone wyłącznie przy zmianie mediów/plików telemetrycznych w _on_files_selected().

DELETE_INVALIDATES_SOURCE_CACHE_BEFORE=True
DELETE_INVALIDATES_SOURCE_CACHE_AFTER=False

RESET_INVALIDATES_SOURCE_CACHE_BEFORE=True
RESET_INVALIDATES_SOURCE_CACHE_AFTER=False

FIRST_MAP_LOAD_MS=84.432
DELETE_READD_MAP_MS=4.612
READD_FULL_SOURCE_LOAD_COUNT=0

SOURCE_CACHE_HIT_AFTER_READD=True

WIDGET_RECT_PARITY=PASS (1566, 124, 346, 346 == 1566, 124, 346, 346)
SOURCE_RECT_PARITY=PASS (0, 0, 346, 346 == 0, 0, 346, 346)
WORKING_SURFACE_PARITY=PASS (0, 0, 490, 490 == 0, 0, 490, 490)
DESTINATION_RECT_PARITY=PASS (1566, 124, 346, 346 == 1566, 124, 346, 346)
SHAPE_MASK_RECT_PARITY=PASS (0, 0, 346, 346 == 0, 0, 346, 346)

READD_GEOMETRY_PARITY=PASS
READD_VISUAL_PARITY=PASS (MAX_DIFF=0, MAE=0.0000)

PITCH_SHAPE_REGRESSION=PASS
RESET_LAYOUT_REGRESSION=PASS
AMD_RENDER_REGRESSION=PASS

MODIFIED_FILES=
src/indicators/map_prepare.py
src/indicators/moving_map.py
src/gui/qt/controller.py
src/gui/qt/_mixins/indicator_mixin.py
src/gui/qt/_mixins/project_mixin.py

CREATED_FILES=
tests/test_amd_map_cache_readd.py
scratch/amd_map_readd_fix/cache_lifecycle.md
scratch/amd_map_readd_fix/cache_keys.txt
scratch/amd_map_readd_fix/cache_events.csv
scratch/amd_map_readd_fix/geometry_before_delete.json
scratch/amd_map_readd_fix/geometry_after_readd.json
scratch/amd_map_readd_fix/map_before_delete.png
scratch/amd_map_readd_fix/map_after_readd.png
scratch/amd_map_readd_fix/map_readd_overlay.png
scratch/amd_map_readd_fix/performance.csv
scratch/amd_map_readd_fix/modified_files.txt
scratch/amd_map_readd_fix/created_files.txt
scratch/amd_map_readd_fix/reproduction_commands.txt
scratch/amd_map_readd_fix/artifacts_manifest.txt
scratch/amd_map_readd_fix/ntfy_result.txt
Raporty/RAPORT_AMD_MAP_CACHE_READD_FIX.md

CASE=CASE A — cache reuse + readd geometry/visual parity PASS
```

---

## 3. SZCZEGÓŁY IMPLEMENTACJI

### 3.1. `src/indicators/moving_map.py`
- Wprowadzono stabilną funkcję identyfikacji trasy `_track_cache_identity(gps_track)` tworzącą skrót krotkowy O(1) na podstawie liczby próbek, współrzędnych początkowych, końcowych i środkowych oraz znaczników czasu.
- Ujednolicono klucz pamięci podręcznej renderera:
  `cache_key = (_track_cache_identity(gps_track), effective_zoom, map_style)`
  zarówno w `render_map_working_image`, jak i w `_render_moving_map_indicator`.
- W przypadku rozbieżności dostawcy kafelków w bieżącym snapshotcie dodano bezpieczny wątek demoniczny uruchamiający precache w tle, unikając zawieszenia w stanie placeholdera.

### 3.2. `src/indicators/map_prepare.py`
- Zastąpiono skalowanie z letterboxingiem (`img.thumbnail`) mechanizmem aspect-fill:
  ```python
  scale = max(w / orig.width, h / orig.height)
  nw = int(round(orig.width * scale))
  nh = int(round(orig.height * scale))
  ```
  Dzięki temu mapa wypełnia całą dostępną przestrzeń roboczą widgetu, eliminując 75-85 pikselowe ciemnoszare pasy przy renderingu overview.

### 3.3. `src/gui/qt/controller.py`
- W metodzie `_clear_caches()` usunięto wywołanie `clear_moving_map_cache()`. Czyszczone są wyłącznie bufory klatek podglądu UI i cache masek kształtu/pitch, co pozwala na natychmiastowe rerenderowanie widgetu przy zmianie właściwości (pitch, shape, opacity, border, position, size).

### 3.4. `src/gui/qt/_mixins/indicator_mixin.py`
- W metodzie `_create_indicator("track_map")`:
  - Źródło GPS `source` jest automatycznie dziedziczone z aktywnego projektu (`ctx.gps_source` lub dostępność śladu FIT), zapobiegając błędnemu fallbackowi do pustego `"gpmf"`.
  - Styl mapy `map_style` jest dziedziczony z `ctx.provider`.
  - Domyślny zoom ustawiono na 15 (`DEFAULT_ZOOM`).
  - Domyślna orientacja: `"track_up"`.
  - Domyślny kształt: `"square"`.
- W metodzie `_on_reset_layout()`:
  - Usunięto wywołanie `clear_moving_map_renderers()`. Reset układu usuwa wszystkie widgety z HUD i resetuje zaznaczenie, ale zachowuje ciężkie dane kafelkowe i wyliczoną trasę w pamięci.

### 3.5. `src/gui/qt/_mixins/project_mixin.py`
- W metodzie `_on_files_selected()` dodano jawne czyszczenie `clear_moving_map_cache()`, co gwarantuje pełną i poprawną re-inicjalizację cache wyłącznie wtedy, gdy użytkownik załaduje nowe pliki wideo lub dane telemetryczne.

---

## 4. WYNIKI TESTÓW I BENCHMARKÓW

### 4.1. Nowy zestaw testów: `tests/test_amd_map_cache_readd.py`
Uruchomienie:
```powershell
python -m unittest tests/test_amd_map_cache_readd.py
```
Wynik: **10/10 PASS** (czas wykonania: 0.40s).
- `test_delete_readd_map_uses_source_cache`: PASS
- `test_reset_then_add_map_uses_source_cache`: PASS
- `test_shape_change_does_not_reload_source`: PASS
- `test_pitch_change_does_not_reload_source`: PASS
- `test_opacity_change_does_not_reload_source`: PASS
- `test_border_change_does_not_reload_source`: PASS
- `test_resize_does_not_reload_source`: PASS
- `test_zoom_roundtrip_reuses_cached_tiles`: PASS
- `test_readd_same_properties_same_geometry`: PASS
- `test_readd_same_properties_same_visual_output`: PASS

### 4.2. Testy regresyjne wcześniejszych etapów
- `tests/test_amd_map_shape_ui_legacy_reset.py`: **13/13 PASS**
- `tests/test_multifile_hud_lifecycle.py`: **3/3 PASS**
- `tests/test_amd_benchmark_governance.py`: **5/5 PASS**

### 4.3. Porównanie wydajności
| Operacja | Czas [ms] | Uwagi |
|---|---|---|
| Pierwsze ładowanie mapy (zimny start) | **84.432 ms** | Inicjalizacja siatki kafelków, rzutowanie GPS |
| Ponowne dodanie mapy (cache hit) | **4.612 ms** | Szybka ścieżka z pamięci podręcznej |
| **Przyspieszenie (Speedup)** | **18.31x** | Brak ponownego pobierania / składania danych |
| Liczba pełnych reloadów źródła | **0** | `READD_FULL_SOURCE_LOAD_COUNT=0` |
| Różnica pikseli (Max diff) | **0** | `MAX_DIFF=0` (idealna zgodność wizualna) |
| Błąd średni bezwzględny (MAE) | **0.0000** | `MAE=0.0000` |

---

## 5. POWIADOMIENIE NTFY

Powiadomienie zostało pomyślnie wysłane do kanału `https://ntfy.sh/MalcerzPOP`:
- **Status:** `NTFY_SUCCESS=True`
- **Próba:** 1 / 3
- **Exit code:** 0
- **Treść:** `"AMD map re-add: cache=PASS, geometry=PASS, case=CASE A."`
- **Znaczniki:** `white_check_mark`
- **Szczegóły weryfikacji:** `scratch\amd_map_readd_fix\ntfy_result.txt`

---

## 6. WERYFIKACJA ARTEFAKTÓW

Wszystkie wymagane pliki zostały wygenerowane i zweryfikowane w worktree:
- `Raporty\RAPORT_AMD_MAP_CACHE_READD_FIX.md`
- `scratch\amd_map_readd_fix\cache_lifecycle.md`
- `scratch\amd_map_readd_fix\cache_keys.txt`
- `scratch\amd_map_readd_fix\cache_events.csv`
- `scratch\amd_map_readd_fix\geometry_before_delete.json`
- `scratch\amd_map_readd_fix\geometry_after_readd.json`
- `scratch\amd_map_readd_fix\map_before_delete.png`
- `scratch\amd_map_readd_fix\map_after_readd.png`
- `scratch\amd_map_readd_fix\map_readd_overlay.png`
- `scratch\amd_map_readd_fix\performance.csv`
- `scratch\amd_map_readd_fix\modified_files.txt`
- `scratch\amd_map_readd_fix\created_files.txt`
- `scratch\amd_map_readd_fix\reproduction_commands.txt`
- `scratch\amd_map_readd_fix\artifacts_manifest.txt`
- `scratch\amd_map_readd_fix\ntfy_result.txt`

Rozwiązanie w pełni spełnia kryteria: **CASE A — cache reuse + readd geometry/visual parity PASS**.
