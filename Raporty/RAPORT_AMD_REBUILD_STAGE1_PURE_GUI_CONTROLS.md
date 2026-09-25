# RAPORT: Odbudowa AMD z Known-Good (Etap 1: Bezpieczna Paczka Pure GUI)

Data: 2026-09-25  
Gałąź bazowa: `0ef407e9ce71cb192f43289abebf6b60c8259839`  
Nowa gałąź produkcyjna: `amd-rebuild-from-known-good`  
Autor wdrożenia: Antigravity  

---

## 1. Cel zadania

Odbudowa funkcjonalności projektu na bazie szybkiego, sprawdzonego backendu AMD (`0ef407e` / wersja z `F:\_DEV\BikeRideHUD-amd`), który osiąga stabilne **40+ FPS**, traktując aktualny stan jako źródło późniejszych funkcji, a nie bazę renderera.

Priorytet bezwzględny: **Utrzymanie wydajności > 40 FPS oraz izolacja backendu D3D11/AMF**.

---

## 2. Weryfikacja bazy i fizycznej kopii z dysku F:

### 2.1. Pomiary na `F:\_DEV\BikeRideHUD-amd` (wersja reference known-good)
Wykonano 3-krotny kanoniczny Performance Gate (`tools/amd_performance_gate.py --runs 3`):
- Run 1: 41.958 FPS | 14.9% CPU | 17.299 ms prep
- Run 2: 42.692 FPS | 17.6% CPU | 17.448 ms prep
- Run 3: 42.511 FPS | 16.6% CPU | 16.805 ms prep
- **Mediana F:** **42.511 FPS** | **16.6% CPU** | **17.299 ms producer_prepare** (**PASS**)

### 2.2. Weryfikacja tożsamości i build-info DLL na dysku C: i F:
Sprawdzono funkcję `telem_amd_get_build_info()` w aktywnej bibliotece `native/d3d11_amf_pipeline/bin/telem_amd_native.dll`:
```text
version=1.0.0
build_id=telem-amd-native/1.0.0+0ef407e9ce71.srcd68d02b422a0
build_timestamp=2026-09-22T19:02:05+02:00
git_commit=0ef407e9ce71cb192f43289abebf6b60c8259839
source_hash=d68d02b422a031f9ccd4ab2f83f9ca14188958a3d035984650ae43259feaebc3
```
DLL jest w 100% tożsama z punktem `0ef407e`.

### 2.3. Weryfikacja czystej gałęzi na dysku C: (`amd-rebuild-from-known-good` @ `0ef407e`)
Wykonano 3-krotny kanoniczny Performance Gate:
- Run 1: 42.085 FPS | 14.9% CPU | 18.721 ms prep
- Run 2: 42.284 FPS | 16.7% CPU | 18.389 ms prep
- Run 3: 42.511 FPS | 16.7% CPU | 19.143 ms prep
- **Mediana C: (czysty known-good):** **42.284 FPS** | **16.7% CPU** | **18.721 ms producer_prepare** (**PASS**)

---

## 3. Pełna analiza różnic: stan bazowy vs aktualny

Poniższa tabela przedstawia całościowy inwentarz funkcji wprowadzonych po commicie `0ef407e`, z ich klasyfikacją pod kątem wpływu na renderer oraz bezpieczeństwa migracji.

| Funkcja | Pliki | GUI only | Renderer impact | Potrzebna do przeniesienia |
|---|---|---|---|---|
| **UI: Reusable widgets (`DiscreteSlider`, `BitrateControl`)** | `src/gui/qt/widgets/discrete_slider.py`, `src/gui/qt/widgets/__init__.py` | **TAK** | BRAK (0.0 ms) | **TAK (Wdrożono w Etapie 1)** |
| **UI: Dynamiczne właściwości i scroll w `PropertyEditor`** | `src/gui/qt/widgets/property_editor.py`, `src/gui/qt/models.py` | **TAK** | BRAK (0.0 ms) | **TAK (Wdrożono w Etapie 1)** |
| **UI: Obsługa ikon SVG i fallback w `IconPicker`** | `src/gui/qt/widgets/icon_picker.py` | **TAK** | BRAK (0.0 ms) | **TAK (Wdrożono w Etapie 1)** |
| **UI: Czyszczenie stanu edytora w `VideoPreview`** | `src/gui/qt/widgets/video_preview.py` | **TAK** | BRAK (0.0 ms) | **TAK (Wdrożono w Etapie 1)** |
| **UI: Wykrywanie i panel sprzętowy (`HardwareInfo`)** | `src/gui/qt/hardware_info.py`, `src/ffmpeg/amd_capabilities.py` | **TAK** | BRAK (0.0 ms) | **TAK (Kolejka: Etap 2)** |
| **Core: Walidacja plików FIT / GPX** | `src/telemetry_file_validation.py` | **TAK** (I/O na wejściu) | BRAK (0.0 ms) | **TAK (Kolejka: Etap 3)** |
| **Core: Zarządzanie i czyszczenie cache telemetrii** | `src/telemetry_cache_manager.py`, `src/gui/qt/tabs/settings_tab.py` | **TAK** (I/O) | BRAK na klatki (0.0 ms) | **TAK (Kolejka: Etap 4)** |
| **UI: Wczytywanie projektów i lista multifile (`LoadTab`)** | `src/gui/qt/tabs/load_tab.py`, `src/gui/qt/_mixins/project_mixin.py` | **TAK** | BRAK na klatki (0.0 ms) | **TAK (Kolejka: Etap 5)** |
| **UI: Kolejka renderowania (`ExportQueue`)** | `src/gui/export_queue.py`, `src/gui/qt/tabs/render_tab.py`, `src/gui/qt/_mixins/render_mixin.py` | **TAK** | BRAK na klatki (0.0 ms) | **TAK (Kolejka: Etap 6)** |
| **Core: Śledzenie postępu finalizacji eksportu (live mux)** | `src/render_progress.py`, `src/ffmpeg/amd_native_exporter.py` | **NIE** | Niewielki (muxer MP4) | **TAK (Kolejka: Etap 7)** |
| **Core: Natywny parser GPMF C++** | `src/native/gpmf/gpmf_extractor.cpp`, `src/telemetry_native_gpmf.py` | **NIE** | BRAK na klatki (tylko faza extract) | **TAK (Kolejka: Etap 8)** |
| **Renderer: Wskaźniki mapy / Markery kierunkowe** | `src/indicators/moving_map.py`, `src/moving_map.py`, `src/gui/map_prefetch.py` | **NIE** | **BARDZO DUŻY** (źródło regresji C) | **WARUNKOWO** (tylko bezpieczny kod bez wątkowego prefetchera) |
| **Renderer: Layout v10 i geometrie wskaźników** | `def_layout.json`, `src/indicators/compositor.py`, `src/indicators/chart.py`, `src/indicators/bar.py` | **NIE** | **BARDZO DUŻY** (źródło regresji A) | **WARUNKOWO** (wyłącznie zweryfikowany wariant Fix A z GPU_SPLIT) |
| **Native D3D11/AMF C++ modyfikacje eksperymentalne** | `native/d3d11_amf_pipeline/src/*` | **NIE** | **KRYTYCZNY** | **NIE (ZABLOKOWANE - baza 0ef407e pozostaje nienaruszona)** |

---

## 4. Wdrożenie Paczki 1: PURE GUI Controls

### 4.1. Zakres commita `5bacdaa`
Do nowej gałęzi produkcyjnej `amd-rebuild-from-known-good` przeniesiono wyłącznie czyste komponenty interfejsu użytkownika, które nie mają żadnego połączenia z pętlą renderowania klatek:
1. `src/gui/qt/widgets/discrete_slider.py` — dyskretny suwak z etykietami dla presetów, bitrate i rozdzielczości (`DiscreteSlider`, `BitrateControl`).
2. `src/gui/qt/widgets/__init__.py` — eksport nowych kontrolek wielokrotnego użytku.
3. `src/gui/qt/widgets/property_editor.py` — integracja `QScrollArea`, zapobiegająca ucinaniu pól właściwości wskaźników, oraz dynamiczna widoczność podrzędnych kontrolek w zależności od trybu (marker, etykieta, gradient segmentów, min/max).
4. `src/gui/qt/widgets/icon_picker.py` — obsługa wektorowych ikon SVG ze skalowaniem `SmoothTransformation` oraz bezpieczny fallback zamiast pustych komórek.
5. `src/gui/qt/widgets/video_preview.py` — metoda `clear_editor_state()` i reset stanu przeciągania przy pustych bounding boxach.
6. `src/gui/qt/models.py` — definicja `section` w `FieldSchema` i rozszerzone definicje pól dla edytora właściwości.
7. `tests/test_property_editor_scroll.py` — zestaw 4 testów automatycznych weryfikujący strukturę `QScrollArea`, scrollowanie i brak ucinania parametrów.

### 4.2. Wyniki testów jednostkowych
```text
tests/test_property_editor_scroll.py .... [100%]
4 passed in 0.75s
```

---

## 5. Kanoniczny Performance Gate po Paczce 1

Wykonano 3-krotny test referencyjny na klatkach 4K (300 klatek, GX020079):
- **Run 1:** 43.042 FPS | 18.3% CPU | 19.718 ms prep
- **Run 2:** 43.133 FPS | 18.5% CPU | 19.647 ms prep
- **Run 3:** 42.492 FPS | 19.3% CPU | 19.783 ms prep

### Porównanie z referencją:

| Parametr | Referencja (`0ef407e`) | Stan przed paczką (C: 0ef407e) | Stan po Paczce 1 (`5bacdaa`) | Zmiana vs Ref | Status |
|---|---|---|---|---|---|
| **RENDER FPS** | **41.364** | **42.284** | **43.042** | **+4.06 %** | **PASS** |
| **System CPU** | **15.1 %** | **16.7 %** | **18.5 %** | **+3.4 pp** | **PASS** |
| **producer_prepare** | **19.260 ms** | **18.721 ms** | **19.718 ms** | **+2.38 %** | **PASS** |
| **Frame Time** | **24.175 ms** | **23.649 ms** | **23.233 ms** | **-3.90 %** | **PASS** |

**VERDICT: PASS**

Wydajność >40 FPS została w pełni zachowana i potwierdzona.

---

## 6. Podsumowanie i status kolejnych kroków

- **Czysty known-good FPS:** **42.284 FPS** (C:) / **42.511 FPS** (F:)
- **FPS po Paczce 1 (Pure GUI):** **43.042 FPS**
- **System CPU:** **18.5 %**
- **Zatwierdzony commit:** `5bacdaa` (`feat(gui): restore reusable widgets and property editor dynamic controls`)
- **Kolejna funkcja oczekująca na migrację:** Etap 2 — `HardwareInfo` panel i detekcja możliwości GPU (`src/gui/qt/hardware_info.py`, `src/ffmpeg/amd_capabilities.py`).
