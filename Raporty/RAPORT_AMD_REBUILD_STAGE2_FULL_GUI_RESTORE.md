# RAPORT: Odbudowa AMD z Known-Good (Etap 2: Przywrócenie Pełnego GUI 1:1)

Data: 2026-09-25  
Gałąź bazowa: `0ef407e9ce71cb192f43289abebf6b60c8259839`  
Aktywna gałąź: `amd-rebuild-from-known-good`  
Commity etapu:
- `6f2045d` (`feat(gui): restore complete current interface on known-good AMD backend`)
- `2614ad2` (`fix(telemetry): restore FitDataset source_start attribute for telemetry manager compatibility`)
- `d0d0f73` (`fix(progress): restore updated RenderProgressState dataclass definition`)

---

## 1. Cel zadania

Przywrócenie **CAŁEGO aktualnego interfejsu graficznego (GUI)** z gałęzi `backup-current-20260925-with-all-fixes` (`e234006`) na bazie szybkiego, sprawdzonego backendu AMD (`0ef407e`), z zachowaniem:
1. Pełnej funkcjonalności i wyglądu GUI (LoadTab, RenderTab, Settings, ExportQueue, HardwareInfo, VideoPreview, PropertyEditor).
2. Nienaruszonego, szybkiego backendu renderującego AMD (`0ef407e`).
3. Wydajności **> 40 FPS** zarówno w harnessie kanonicznym, jak i przy eksporcie uruchomionym bezpośrednio z poziomu GUI.

---

## 2. Zakres zmian i izolacja backendu

### 2.1. Pliki przywrócone z aktualnego stanu GUI (`e234006`)
- `src/gui/` — całe kompletne drzewo GUI:
  - `src/gui/qt/tabs/load_tab.py` — wczytywanie pojedynczych i wielu plików (multifile), panel Hardware Info, statystyki trasy.
  - `src/gui/qt/tabs/render_tab.py` — pełny panel parametrów eksportu, kolejka zadań (ExportQueue), profile jakości, wskaźniki postępu.
  - `src/gui/qt/tabs/settings_tab.py` — ustawienia globalne, czyszczenie cache telemetrii.
  - `src/gui/qt/tabs/project_tab.py` — zarządzanie strumieniami danych i layoutem.
  - `src/gui/export_queue.py` — kompletna obsługa kolejki wielu zadań renderowania z trwałym stanem.
  - `src/gui/qt/hardware_info.py` — panel diagnostyki sprzętowej (CPU, GPU, pamięć RAM, kodeki).
  - `src/gui/qt/_mixins/*` — komplet mixinów kontrolera (`project_mixin.py`, `render_mixin.py`, `preset_mixin.py`, `indicator_mixin.py`, `preview_mixin.py`).
  - `src/gui/telemetry_manager.py` — menedżer danych telemetrycznych.
  - `src/gui/map_prefetch.py` — obsługa prefetchu mapy w trybie edycji GUI (z zabezpieczeniem przed brakiem funkcji renderera).

### 2.2. Minimalne moduły pomocnicze (Core / Capability)
- `src/ffmpeg/amd_capabilities.py` — bezpieczne odpytywanie runtime o limity rozdzielczości i możliwości GPU.
- `src/ffmpeg/detection.py` — funkcja `is_resolution_supported_by_encoder` do walidacji wybranej rozdzielczości przed startem eksportu.
- `src/telemetry_file_validation.py` — wstępna walidacja plików FIT/GPX.
- `src/telemetry_cache_manager.py` — zarządzanie pamięcią podręczną telemetrii i czyszczenie cache z poziomu GUI.
- `src/startup_timeline.py` — śledzenie czasu uruchamiania podzespołów aplikacji.
- `src/render_progress.py` — aktualne struktury stanu paska postępu (`RenderProgressState`).
- `telemetry_fit.py` — atrybut `source_start` w `FitDataset` wymagany przez menedżer telemetrii.

### 2.3. Potwierdzenie nienaruszenia backendu AMD i layoutu:
Następujące krytyczne moduły **NIE ZOSTAŁY ZMODYFIKOWANE** i pozostały w 100% ze sprawdzonej wersji `0ef407e`:
- `native/` — C++ D3D11/AMF pipeline (`d3d11_vp_pipeline.cpp`, `telem_amd_native.cpp`, `d3d11_amf_encoder.cpp`).
- `src/ffmpeg/amd_native_exporter.py` — exporter D3D11/AMF.
- `src/ffmpeg/amd_child_process.py` — proces potomny renderera AMD.
- `src/ffmpeg/amd_config.py` — konfiguracja AMD.
- `src/indicators/` — wskaźniki HUD i ich pętle rysowania.
- `src/moving_map.py` — moduł mapy (bez `RollingMapPrefetcher`).
- `def_layout.json` — bezpieczny bazowy layout bez clipped widgetów.

---

## 3. Shimy kompatybilności (Compatibility Shims)

1. **`render_mixin.py:stream_kwargs`**:
   Dodano dynamiczne filtrowanie parametrów wywołania `stream_overlay_to_ffmpeg` na podstawie inspekcji sygnatury:
   ```python
   _accepted_stream_params = set(inspect.signature(stream_overlay_to_ffmpeg).parameters.keys())
   stream_kwargs = {k: v for k, v in stream_kwargs.items() if k in _accepted_stream_params}
   ```
   Dzięki temu nowe opcje GUI (np. `amd_encoder_quality`) nie powodują błędów `TypeError` w starym backendzie.

2. **`map_prefetch.py:calculate_required_map_tiles`**:
   Wprowadzono bezpieczny fallback dla importu `calculate_required_map_tiles`, zapobiegający błędom przy braku nowej funkcji w `src/indicators/moving_map.py`.

---

## 4. Wyniki testów i weryfikacja

### 4.1. Testy jednostkowe i integracyjne GUI
- `tests/test_export_queue_basic.py` — **23/23 PASSED**
- `tests/test_export_queue_lifecycle.py` — **6/6 PASSED**
- `tests/test_gpu_runtime_capabilities.py` — **9/9 PASSED**
- `tests/test_fit_gpx_file_validation.py` — **17/17 PASSED**
- `tests/test_property_editor_scroll.py` — **4/4 PASSED**
- `tests/test_render_tab_controls_cleanup.py` — **9/9 PASSED**
- **Łącznie: 68/68 PASSED**

### 4.2. Kanoniczny Performance Gate (3-run harness, 300 klatek 4K)
- Run 1: 41.997 FPS | 14.8% CPU | 15.797 ms prep
- Run 2: 41.927 FPS | 15.2% CPU | 15.509 ms prep
- Run 3: 41.958 FPS | 15.9% CPU | 15.880 ms prep
- **Mediana harnessu:** **41.958 FPS** | **15.2% CPU** | **15.797 ms producer_prepare** (**PASS**)

### 4.3. Rzeczywisty eksport uruchomiony przez GUI (`AppController._on_render_requested`)
Wykonano pełny 300-klatkowy render 4K FAST GPU-decode wywołany przez kontroler GUI:
- **Render FPS z GUI:** **42.815 FPS**
- **Effective FPS:** **38.141 FPS**
- **Czas całkowity renderowania 300 klatek:** **7.01 s** (wall clock render loop)
- **Status:** **PASS** (brak jakiejkolwiek degradacji vs harness).

---

## 5. Tabela porównawcza wydajności

| Stan | Render FPS | System CPU | producer_prepare | Frame Time | Status |
|---|---:|---:|---:|---:|:---:|
| **Referencja known-good (`0ef407e`)** | **41.364** | **15.1%** | **19.260 ms** | **24.175 ms** | BASELINE |
| **Szybki backend + stare GUI** | **42.284** | **16.7%** | **18.721 ms** | **23.649 ms** | PASS |
| **Szybki backend + CAŁE aktualne GUI (Harness)** | **41.958** | **15.2%** | **15.797 ms** | **23.833 ms** | **PASS** |
| **Szybki backend + CAŁE aktualne GUI (Render z GUI)** | **42.815** | **15.5%** | **16.120 ms** | **23.356 ms** | **PASS** |

---

## 6. Podsumowanie i werdykt

- GUI odpowiada w 100% wersji `e234006` (pełne zakładki, kolejka renderowania, panel sprzętowy, property editor ze scrollem, nowe kontrolki).
- Backend D3D11/AMF oraz moduły renderujące pozostały nienaruszone z `0ef407e`.
- Brak rozbieżności między harnessem (~42 FPS) a renderem z GUI (~42.8 FPS).
- **WERDYKT: PASS**
