# RAPORT: AMD REBUILD — NAPRAWA 3 REGRESJI FUNKCJONALNYCH (CONFIG CACHE-ONLY, NATIVE GPMF, STATUS QP)

## 1. Zadanie

Naprawa trzech regresji funkcjonalnych po odtworzeniu pełnego aktualnego GUI na szybkim backendzie AMD (`0ef407e`):
1. **Konfiguracja per-file (Cache-only):** Wyłączenie wszelkiego wyszukiwania/ładowania legacy sidecar configów obok plików MP4/FIT/GPX. Wszystkie odczyty i zapisy konfiguracji/telemetrii muszą odbywać się WYŁĄCZNIE przez centralny katalog AppData cache (`src/telemetry_cache_manager.py`).
2. **Natywny parser GPMF jako domyślny:** Przywrócenie natywnego parsera C/C++ GPMF (`src/telemetry_native_gpmf.py` i `src/telemetry_extract.py`) z logiem `[GPMF] parser=NATIVE`. Wyeliminowanie wywołań ExifTool ze ścieżki normalnej (ExifTool pozostaje wyłącznie jako logowany awaryjny fallback: `[GPMF] native parser failed -> ExifTool fallback`).
3. **Prezentacja QP w pasku postępu renderowania:** Przywrócenie wyświetlania metryki QP w statusie postępu (`RenderTab.lbl_stats` i `RenderProgressState`, format: `Frame: ... | ...% | FPS: ... | QP: 28.1 | Czas: ... | ETA: ... | Renderowanie...`), zasilanej bezpośrednio z real-time odczytu AMF `telem_amd_get_encoder_qp_stats`.

---

## 2. Stan początkowy

- Gałąź: `amd-rebuild-from-known-good`
- Baza renderera: `0ef407e` (~41-43 FPS, <20% CPU)
- Stan po restore GUI:
  - Odczyty konfiguracyjne próbowały wczytywać pliki `.layout.json` i legacy JSON-y z katalogów wideo.
  - Ekstrakcja GPMF przy próbie importu nowszych funkcji pomocniczych rzucała `ImportError` w `project_mixin.py` i przełączała się na wolny parser ExifTool.
  - Pasek postępu renderowania pomijał segment `| QP: ... |`, a odczyt telemetryczny QP z enkodera AMF nie był podłączony w pętli postępu `amd_native_exporter.py`.

---

## 3. Zaimplementowane zmiany

### A. Fix 1: Config cache only (`d3d8d46`)
- `src/gui/qt/_mixins/project_mixin.py`:
  - Usunięto automatyczne wykrywanie i ładowanie legacy `.layout.json` oraz legacy plików JSON obok wideo/FIT.
- `src/multifile.py`:
  - Skierowano `_telem_time_cache_paths` do centralnego AppData cache (`get_telemetry_cache_path`).
  - Usunięto sidecar search obok plików MP4.
- `src/telemetry_processed_cache.py`:
  - Skierowano `processed_cache_path` na `get_telemetry_npz_path` z `telemetry_cache_manager.py`.
  - Usunięto czytanie i tworzenie sidecarów `.processed.npz` w katalogach źródłowych.
- `tests/test_config_cache_only.py`:
  - Dodano dedykowany zestaw testów jednostkowych weryfikujący:
    - Wykrywanie i ignorowanie legacy configów obok MP4/FIT.
    - Wczytywanie wyłącznie z cache centralnego.
    - Brak automatycznego używania sidecaru przy braku wpisu w cache.

### B. Fix 2: Native GPMF parser (`5b19bd6`)
- `src/telemetry_native_gpmf.py` i `src/telemetry_extract.py`:
  - Przywrócono pełne wersje modułów natywnego parsera GPMF z gałęzi referencyjnej (`backup-current-20260925-with-all-fixes`), w tym `missing_native_channels`, `native_channels_used`, `native_result_usable`, akcelerowane transformacje NumPy oraz projekcję wektorową.
- `src/gui/qt/_mixins/project_mixin.py`:
  - Dodano jawne logowanie kanałów i wyboru parsera: `[GPMF] parser=NATIVE` przy sukcesie parsera C/C++ oraz `[GPMF] native parser failed -> ExifTool fallback` w przypadku realnego błędu.

### C. Fix 3: Render Progress QP (`62b09a4`)
- `src/render_progress.py`:
  - Dodano pola `qp: float | None = None` oraz `avg_qp: float | None = None` do dataclass `RenderProgressState`.
  - Zaktualizowano `format_render_progress_status`, aby formatował `| QP: {qp_str} |` (`"--"` gdy wartość jest niedostępna lub w fazie przygotowania).
- `src/gui/qt/_mixins/render_mixin.py`:
  - W `emit_render_progress` dodano ekstrakcję wartości QP ze słownika `hud_state` (`mean_qp`, `avg_qp`, `qp_avg`, `qp`, `current_qp`) i przekazanie do snapshotu stanu renderowania.
- `src/gui/qt/tabs/render_tab.py`:
  - Zaktualizowano metodę `_set_stats`, aby przyjmowała parametr `qp: float | None = None` i formatowała jednolity wiersz statusu:
    `{item_label}: {frame_txt}   |   {pct_txt}   |   FPS: {fps_txt}   |   QP: {qp_str}   |   Czas: {elapsed_txt}   |   ETA: {eta_txt}   |   {status}`.
  - Zaktualizowano `_on_render_state`, `_on_render_progress` oraz `_on_finished` w `RenderTab`.
- `src/ffmpeg/amd_native_exporter.py`:
  - Dodano deklarację ctypes dla istniejącej w DLL `telem_amd_native.dll` funkcji `telem_amd_get_encoder_qp_stats`.
  - W pętli per-frame progress reporting dodano odczyt `telem_amd_get_encoder_qp_stats` i przekazywanie `qp_avg` do `progress_tracker.frame(...)`.
  - Wzbogacono statystyki `amf_stats` o `avg_qp`.

---

## 4. Wyniki testów i weryfikacja

### A. Testy jednostkowe (Pytest)
```text
tests/test_config_cache_only.py ......................... PASSED (3/3)
tests/test_central_telemetry_cache.py ................... PASSED (13/13)
tests/test_gpmf_native_perf_and_cache_clear.py .......... PASSED (9/9)
tests/test_gpmf_temp_and_battery_timing.py .............. PASSED (1/1)
tests/test_render_progress_single_source.py ............. PASSED (10/10)
tests/test_export_finalization_lifecycle.py ............. PASSED (4/4)
Total: 40 passed, 1 skipped in 3.75s
```

### B. Test GPMF na `F:\GoPro\2026-09-24\GX010318.MP4`
- Parser: `NATIVE` (moduł C/C++ `telem_gpmf_native.pyd`)
- Wyniki ekstrakcji:
  - `GPS_SAMPLES = 18562`
  - `ACC_SAMPLES = 368991`
  - `GYRO_SAMPLES = 368991`
  - `NATIVE_CHANNELS_USED = GPS,ACC,GYRO`
  - `PYTHON_FALLBACK_CHANNELS = -`
  - `NATIVE_RESULT_ACCEPTED = True`
  - `FALLBACK_REASON = -`
  - `PARSE_MS = 14603.22 ms` (cold extraction), `1720.00 ms` (warm cache load)
- Log wyjściowy:
  ```text
  [GPMF] parser=NATIVE (GX010318.MP4)
  [GPMF LOAD]
  SOURCE=F:\GoPro\2026-09-24\GX010318.MP4
  CACHE_HIT=False
  NATIVE_MODULE_AVAILABLE=True
  NATIVE_PARSE_OK=True
  ```
- ExifTool: **0 wywołań w normalnej ścieżce**.

### C. Test QP na żywym renderze z GUI (`scratch/test_gui_qp_render_smoke.py`)
- Testowy eksport 4K 1131 klatek przez pełny stos GUI:
  ```text
  [STATUS] HUD: 0 / 1   |   0.0%   |   FPS: --   |   QP: --   |   Czas: 00:00   |   ETA: --:--   |   Przygotowanie HUD...
  [STATUS] Frame: 60 / 1131   |   5.3%   |   FPS: 36.2   |   QP: 20.5   |   Czas: 00:02   |   ETA: 00:29   |   Renderowanie...
  [STATUS] Frame: 300 / 1131  |   26.5%  |   FPS: 39.4   |   QP: 33.7   |   Czas: 00:08   |   ETA: 00:21   |   Renderowanie...
  [STATUS] Frame: 650 / 1131  |   57.5%  |   FPS: 39.8   |   QP: 28.1   |   Czas: 00:17   |   ETA: 00:12   |   Renderowanie...
  [STATUS] Frame: 1130 / 1131 |   99.9%  |   FPS: 39.8   |   QP: 26.7   |   Czas: 00:29   |   ETA: 00:00   |   Renderowanie...
  [STATUS] Frame: 1131 / 1131 |  100.0%  |   FPS: 39.8   |   QP: 26.7   |   Czas: 00:31   |   ETA: 00:00   |   Gotowe
  ```
- QP aktualizuje się w czasie rzeczywistym i wyświetla precyzyjne wartości enkodera AMF.

---

## 5. Performance Sanity Benchmark Gate

Wynik `python tools/amd_performance_gate.py --runs 1`:

```text
============================================================
AMD PERFORMANCE GATE
============================================================

Reference:
SHA:              0ef407e
FPS:              41.364
CPU:              15.1 %
producer_prepare: 19.260 ms
frame time:       24.175 ms

Current single run (HEAD 62b09a4):
FPS:              43.091
CPU:              19.1 %
producer_prepare: 17.817 ms
frame time:       23.207 ms

Differences:
FPS:               +4.18 %   PASS
CPU:                +4.0 pp   PASS
producer_prepare:  -7.49 %   PASS
frame time:        -4.00 %   PASS

------------------------------------------------------------
VERDICT: PASS
============================================================
```

Wydajność renderera AMD pozostaje na poziomie **43.1 FPS**, a obciążenie CPU wynosi **19.1%** (poniżej limitu 20%).

---

## 6. Wnioski i podsumowanie

Wszystkie trzy regresje funkcjonalne zostały rozwiązane minimalnymi, izolowanymi poprawkami bez naruszania natywnego pipeline'u D3D11/AMF:
1. Konfiguracja i telemetria są czytane i zapisywane wyłącznie w centralnym AppData cache.
2. Natywny parser C/C++ GPMF działa jako podstawowy parser produkcyjny; ExifTool pozostaje jako awaryjny fallback z odpowiednim logowaniem.
3. Wskaźnik QP został przywrócony do paska postępu GUI i aktualizuje się na bieżąco podczas renderowania.
4. Bramka wydajnościowa AMD Performance Gate raportuje pełny **PASS**.
