# Raport: Ustanowienie AMD_CPU_WIDGET_CACHE=1 jako Produkcyjnego Defaultu (AMD D3D11 Pipeline)

Data: 2026-09-16  
Środowisko: `C:\_DEV\BikeRideHUD`  
Gałąź: `amd-bikeridehud`  
Dataset: `Video/GX020079.mp4` + `Video/GX020079.fit` (3840x2160, 300 klatek, HEVC AMF, produkcyjny `def_layout.json`)  

---

## 1. Wymagane Kluczowe Wskaźniki

```text
DEFAULT_CPU_WIDGET_CACHE=1 (segment_bar only)

ACTIVE_ENV_OVERRIDES={'AMD_CPU_GPU_PIPELINE': 'ASYNC', 'AMD_QUEUE_DEPTH': '2', 'AMD_VP_PROCESSOR_RING_SIZE': '1', 'AMD_AFTER_MAP_ALT_VISUAL_GPU': '0', 'AMD_ABOVE_BATCHED': '0'}

TRUE_FPS=37.947
ABOVE_TOTAL=9.968
ABOVE_COMPOSE=8.030
PRODUCER_PREPARE=17.363

CACHE_HITS=586
CACHE_MISSES=16
CACHE_HIT_RATIO=97.34%

EXPORT_FRAMES=300/300
EXPORT_DROPPED=0
AMF_ERRORS=0
D3D11_ERRORS=0
CHILD_EXITCODE=0

USER_VISUAL_ACCEPTANCE=PENDING

CASE=CASE A — SEGMENT_BAR CACHE PRODUCTION DEFAULT VALIDATED
```

---

## 2. Cel Zadania i Zmiany w Konfiguracji

Po pomyślnej walidacji canonical visual-state cache dla `segment_bar` (98.01% hit ratio dla danych wolnozmiennych, 92.69% dla szybkozmiennych, 0 diff pixels), flaga `AMD_CPU_WIDGET_CACHE=1` została wdrożona jako **domyślne ustawienie produkcyjne** dla backendu AMD.

### Wprowadzone Modyfikacje:
1. **`src/ffmpeg/amd_config.py`**:
   - `PRODUCTION_DEFAULTS["cpu_widget_cache"]`: zmieniono z `0` na `1`.
   - `resolve_amd_config()`: domyślna wartość dla `values.get("AMD_CPU_WIDGET_CACHE")` zmieniona z `False` na `True`.
   - Zachowano pełne wsparcie dla jawnego nadpisania `AMD_CPU_WIDGET_CACHE=0` (dla celów diagnostycznych i testów A/B).
2. **`tests/test_amd_benchmark_governance.py`**:
   - Zaktualizowano testy governance potwierdzające:
     - `resolve_amd_config({})["cpu_widget_cache"] == 1` (default bez zmiennych środowiskowych)
     - `resolve_amd_config({"AMD_CPU_WIDGET_CACHE": "0"})["cpu_widget_cache"] == 0` (override OFF)
     - `resolve_amd_config({"AMD_CPU_WIDGET_CACHE": "1"})["cpu_widget_cache"] == 1` (override ON)
   - Wynik testów pytest: **9/9 PASSED**.

---

## 3. Wyniki Produkcyjnego Eksportu Kontrolnego (Real GUI Path)

Wykonano pojedynczy kontrolny eksport produkcyjny na kanonicznym projekcie `GX020079.mp4` + `GX020079.fit` z domyślnym layoutem `def_layout.json` (3840x2160 @ 29.97 fps, 300 klatek / 10.0 s):
- **Ścieżka:** `BikeRideHUD.py` -> `MainWindow` -> `RenderTab` -> `AMD Child Process` -> `amd_native_exporter.py` -> `telem_amd_native.dll` -> `AMF HEVC`
- **Ustawienia produkcyjne:**
  - `AMD_QUEUE_DEPTH=2`
  - `AMD_CPU_GPU_PIPELINE=ASYNC`
  - `AMD_VP_PROCESSOR_RING_SIZE=1`
  - `AMD_ABOVE_BATCHED=0`
  - `AMD_AFTER_MAP_ALT_VISUAL_GPU=0`
  - `AMD_CPU_WIDGET_CACHE=1` (automatycznie aktywowane z domyślnej konfiguracji, bez wpisu w `active_env_overrides`)

### Wydajność i Statystyki Renderowania:
- **Klatki:** `300 / 300` (100.0%, 0 dropped)
- **Kod wyjścia procesu potomnego:** `0`
- **True FPS:** **37.947 FPS**
- **Render FPS:** **42.690 FPS**
- **Czas CPU `above_total`:** **9.968 ms** (spadek poniżej progu 10 ms)
- **Czas CPU `above_compose`:** **8.030 ms**
- **Czas `producer_prepare`:** **17.363 ms**

### Statystyki Generic Visual-State Cache (2 aktywne wskaźniki `segment_bar`):
- **`fit_garmin_battery_percent_text`** (bateria):
  - Raw changes: `300`
  - Visual changes: `3`
  - Hits / Misses: `298 / 3` (**99.00% hit ratio**)
  - Lookup avg: `0.0267 ms`
- **`fit_curVpower_text`** (moc):
  - Raw changes: `122`
  - Visual changes: `13`
  - Hits / Misses: `288 / 13` (**95.68% hit ratio**)
  - Lookup avg: `0.0345 ms`
- **Łącznie:** `586 hits / 16 misses` (**97.34% hit ratio**)

---

## 4. Visual Proof

Z wyeksportowanego pliku wideo wyciągnięto klatki `0, 50, 150, 250, 299` i wygenerowano arkusz `scratch/amd_segment_bar_cache_default/contact_sheet.png`:
- **Segment Bar:** Płynne, prawidłowe odświeżanie baterii Garmina oraz paska mocy.
- **Speed Gauge:** Precyzyjne wskazania prędkości bez zakłóceń kompozycji.
- **Wykresy HR / Cadence (AFTER-MAP):** Prawidłowa kolejność Z-order i brak ghostingu.
- **Moving Map (GPU Track-Up):** Prawidłowa rotacja i pozycja kursora GPS.
- **Status wizualny:** `USER_VISUAL_ACCEPTANCE=PENDING`.

---

## 5. Podsumowanie

Wdrożenie `AMD_CPU_WIDGET_CACHE=1` jako domyślnego ustawienia produkcyjnego backendu AMD zakończyło się pełnym sukcesem. Koszt warstwy CPU ABOVE spadł do **9.97 ms**, a potok osiągnął **97.34% hit ratio** przy zerowej degradacji wizualnej.
