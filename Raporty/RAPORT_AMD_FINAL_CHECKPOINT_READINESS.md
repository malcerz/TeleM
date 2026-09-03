# RAPORT: AMD FINAL CLEANUP / CPU-DECODE VERDICT / CHECKPOINT READINESS
**Data:** 2026-09-03  
**Repo:** `C:\_DEV\TeleM-integration`  
**Branch:** `integration/intel-amd` (Commit bazowy: `c80ba07`)  
**Platforma testowa:** AMD Ryzen 7 7730U with Radeon Graphics (8C/16T, Zen 3 Barcelo-R, APU iGPU `1002:15E7`, sterownik `31.0.21925.1001`)  

---

## 1. AKTUALNA ARCHITEKTURA AMD

Produkcyjny potok renderujący dla platformy AMD (`AMD_NATIVE_D3D11`):
```text
Video Source (GoPro 4K HEVC Main 10 HLG/BT.2020)
       ↓
D3D11VA Hardware Decode (Media Foundation Source Reader via VCN)
       ↓
P010 GPU Native Surface (DXGI_FORMAT_P010 w VRAM)
       ↓
D3D11 Video Processor Hardware Blit (180° GoPro matrix rotation + Range normalization)
       ↓
GPU-Resident Compositor (Persistent NV12 canvas)
  ├── GPU Track-Up Map (Bicubic rotation + marker w GPU)
  ├── CPU ABOVE HUD (Pillow text / transparent overlay upload)
  ├── GPU AFTER-MAP Charts (Cadence & Heart Rate split-upload)
  ├── GPU AFTER-MAP Speed Gauge (Dynamic AUTO dirty-region transfer)
  └── GPU Lean Indicator (Wektorowa interpolacja kąta przechyłu + bike art)
       ↓
Hardware AMF HEVC Encoder (Direct GPU surface consumption, ASYNC Queue Depth = 2)
       ↓
Direct Live MP4 Muxer (Pipelined stream writing do .part, zerowy remux po zakończeniu)
       ↓
Finalny plik MP4 (Bit-depth 10-bit, HDR / HLG / BT.2020)
```

---

## 2. AKTUALNY PRODUKCYJNY BASELINE (CANONICAL)

Pomiar referencyjny całego pliku (`Video/GX010115.MP4` + `Video/GX010114_116.fit`, 17 760 klatek, 4K UHD):
- **Liczba klatek:** 17 760 (100% materiału źródłowego)
- **Czas przygotowania HUD (HUD prepare):** **1.345 s**
- **Czas kodowania wideo (Video encode):** **427.824 s**
- **Czas finalizacji (Finalize Direct Mux):** **5.215 s**
- **Czas łączny (Total wall-clock):** **434.887 s**
- **RENDER FPS:** **41.512**
- **EFFECTIVE FPS:** **40.838**
- **AMF Queue Diagnostics:**
  * `submitted_frames`: 17 760
  * `received_frames`: 17 760
  * `input_full_count`: 0
  * `retry_count`: 0
  * `max_in_flight`: 2
  * `consumer_wait_ms`: 0.000 ms

---

## 3. WERDYKT DOTYCZĄCY CPU DECODE

Pomiary eksperymentalne:
- **CPU DECODE ONLY (16 wątków, 3000f):** **57.97 FPS** (17.25 ms/k)
- **CPU DECODE + P010 UPLOAD (3000f):** **38.05 FPS** (26.27 ms/k: decode 14.26 ms + upload 12.00 ms, CPU 78.9%)
- **GPU DECODE + AMF MINIMAL (3000f):** **42.759 FPS**
- **CPU DECODE + AMF MINIMAL (3000f):** **33.190 FPS** (-22.38% względem GPU decode)
- **CPU DECODE + FULL HUD (300f):** **22.669 FPS** (-33.99% względem GPU decode, CPU 94.8% nasycenia)

**Decyzja produkcyjna:**
- **GPU D3D11VA** pozostaje jedynym domyślnym mechanizmem dekodowania dla AMD.
- Ścieżka CPU decode **NIE trafia do interfejsu użytkownika (GUI)**.
- **NIE** dodaje się opcji wyboru (Auto / GPU / CPU) w ustawieniach programu.

---

## 4. POPRAWIONA INTERPRETACJA WSPÓŁDZIELENIA VCN

- **Status hipotezy:** `CPU DECODE OFFLOAD IS NOT BENEFICIAL`.
- Usunięcie dekodowania sprzętowego z VCN obniża utylizację silnika `Video Codec 0` z ~99% do ~58%, co dowodzi, że dekoder D3D11VA rzeczywiście rywalizuje o zasoby wspólnego bloku VCN.
- Jednakże przeniesienie dekodowania na CPU wraz z koniecznością transferu surowych klatek 4K P010 (24.88 MB/klatkę $\approx$ 1 GB/s na szynie RAM) jest wolniejsze niż sprzętowy silnik VCN.
- Dodatkowo obciążenie CPU rzędu 80–95% prowadzi do zjawiska CPU starvation (głodzenia kodera AMF przez opóźnienia w przygotowaniu klatek). W rezultacie zwolniona przepustowość enkodera nie może zostać skonsumowana.

---

## 5. WYJAŚNIENIE WYNIKU 34.344 FPS DLA 300f FULL HUD

Wynik 34.344 FPS uzyskany w teście 300-klatkowym Full HUD nie jest reprezentatywnym baseline'em wydajnościowym dla produkcji. Różnica względem 42.434 FPS (3000f) oraz 41.512 FPS (17760f) wynika z:
1. **Amortyzacji stałych kosztów startowych na krótkim odcinku (300 klatek = zaledwie 10 sekund wideo):**
   - Inicjalizacja urządzenia D3D11, fabryki AMF, czytnika Media Foundation, resolvera fontów Arial oraz potoku potokowego Direct Mux zabiera ~1.5–2.0 s. Przy 10-sekundowym teście stanowi to niemal 20% całego czasu, sztucznie zaniżając FPS o ~8 FPS.
2. **Aktywnej instrumentacji pomiarowej:**
   - Testy 300-klatkowe uruchamiano z flagami `TELEM_AMD_BOTTLENECK_PROOF=1` oraz `AMD_FRAME_TRACE=1`, które zapisują szczegółowy ślad CSV dla każdej klatki i synchronizują wątki na operacjach dyskowych.
3. **Efektu zimnej pamięci podręcznej (Cold Cache):**
   - Pierwsze kilkadziesiąt klatek wymaga wygenerowania bazowych tekstur Pillow, kafelków dynamicznych wykresów oraz mapy.

Reprezentatywne pomiary ustabilizowanego potoku dla platformy Ryzen 7 7730U:
- **Minimal HUD ASYNC2 (3000f):** **42.759 FPS**
- **Full HUD ASYNC2 (3000f):** **42.434 FPS** (różnica: **0.325 FPS = 0.76%**)
- **Full HUD Production (17 760f):** **41.512 FPS**

**Wniosek:** Dalsza optymalizacja warstwy CPU ABOVE/HUD na maszynie 7730U przyniosłaby jedynie **marginalny zysk (marginal expected FPS gain < 1%)**, ponieważ pełny potok Full HUD osiąga już 99.2% fizycznego sufitu enkodera/dekodera VCN. Nie jest to priorytet P0.

---

## 6. STATUS EKSPERYMENTALNEGO KODU CPU DECODE

Kod obsługi CPU decode:
- Został zachowany w repozytorium jako **DIAGNOSTIC / EXPERIMENTAL ONLY (KEEP)**.
- Jest w pełni odizolowany: aktywuje się wyłącznie po jawnym ustawieniu zmiennej środowiskowej `AMD_DECODE_MODE=CPU`.
- Domyślna wartość w kodzie produkcyjnym: `AMD_DECODE_MODE=GPU`. Zwykły użytkownik nigdy nie trafia w ścieżkę CPU.
- Zapewnia precyzyjną, 10-bitową implementację P010 HDR (zastępując starą, stratną konwersję do 8-bit NV12), stanowiąc bezpieczne narzędzie diagnostyczne do testów pamięci RAM i IPC.

---

## 7. ASYNC DEPTH 2 — STATUS PRODUKCYJNY

Tryb `ASYNC Queue Depth = 2` (`AMD_CPU_GPU_PIPELINE=ASYNC`, `AMD_QUEUE_DEPTH=2`) pozostaje **domyślną konfiguracją produkcyjną**:
- **Błędy przepełnienia:** 0 `AMF_INPUT_FULL`, 0 retry submissions.
- **Alokacja pamięci:** Dokładnie 1 powierzchnia AMF/klatkę (brak wycieków VRAM).
- **Zysk wydajności:** Podniesienie stabilnego sufitu z ~37 FPS (SYNC) do **~41.5–42.4 FPS**.
- **Weryfikacja:** Pomyślne przejście testów single-file, multi-file boundary (014 $\rightarrow$ 015 $\rightarrow$ 016), cancel safety oraz zgodności klatek.
- Głębokość 3 (Depth 3) została zbadana i odrzucona jako nieprzynosząca żadnego zysku na platformie APU.

---

## 8. STATUS WARSTWY LAYOUT / LEAN / WIDGETÓW

W ramach ostatnich etapów prac zintegrowano i ustabilizowano:
1. **Layout Ownership:** `def_layout.json` posiada zaktualizowaną strukturę, prawa własności wskaźników i jednoznaczne identyfikatory.
2. **Kalibracja Lean:** Wprowadzono kalibrację kąta przechyłu (+6.0° offset), grafikę motocykla (`bike`) z poprawnym pivotem obrotu oraz wektorową prekomputację IMU w `telemetry_precompute.py`.
3. **Zestaw ikon i optyka tekstu:** Ujednolicono rozmiary i wyśrodkowanie ikon (zegar, ISO, bateria, stoper) oraz wprowadzono spójne metryki optyczne w `text.py` i `icons.py`.
4. **Interfejs Qt GUI:** Zaimplementowano obsługę pełnego ekranu (F11/Esc), precyzyjny krok o 1 klatkę ($\leftarrow$ / $\rightarrow$), podgląd 1:1 z antyaliasingiem oraz jawne zarządzanie zapisem ustawień bez niechcianego nadpisywania presetów.

---

## 9. WYNIKI TESTÓW REGRESYJNYCH (TEST SUITE)

1. **Testy jednostkowe i integracyjne Pytest:**
   - Polecenie: `python -m pytest tests/test_layout_ownership_and_lean_calibration.py tests/test_gui_v3_runtime_acceptance.py tests/test_gui_v4_fullscreen_and_next_frame.py tests/test_gui_v5_autosave_preview_and_aa.py tests/test_icon_font_gauge_fixes.py tests/test_indicator_config_parity.py tests/test_time_display_icon_size.py -v`
   - **Wynik:** **105 PASSED / 0 FAILED (10.92 s)**.
2. **Weryfikacja Direct MP4 Mux Hardening:**
   - Polecenie: `python scratch/verify_amd_direct_mux_hardening.py`
   - **Wynik:** Pomyślne przejście testów zakresów A, B, C, D; test 3000 klatek potwierdził 100.1s zgodności A/V, brak pliku pośredniego `.h265`, zysk +27% na czasie całkowitym dzięki eliminacji remuxu.
3. **Multi-File Boundary Proof:**
   - Polecenie: `python scratch/run_boundary_proof.py`
   - **Wynik:** 300 klatek na granicy klipów GX010114 $\rightarrow$ GX010115 (przełączenie w klatce 150), 0 błędów, 42.1 FPS.
4. **Wieloplikowy test SmokeA (900 klatek):**
   - Polecenie: `python scratch/run_cancel_safety.py --test smokeA`
   - **Wynik:** 900/900 klatek wyeksportowanych poprawnie, czas 21.15 s (Render FPS: 42.554).
5. **Weryfikacja procedury Cancel (Early Termination):**
   - Polecenie: `python scratch/run_cancel_safety.py --test single --cancel-time 2.0`
   - **Wynik:** Bezpieczne przerwanie w 2.12 s, czyste zwolnienie zasobów D3D11/AMF, brak zawieszonych procesów `ffmpeg.exe`.
6. **Weryfikacja Lean GPU Render:**
   - Polecenie: `python scratch/smoke_lean_render.py`
   - **Wynik:** 150 klatek wyrenderowanych bez zawieszeń, Render FPS: 39.75.

---

## 10. KOMPILACJA NATYWNEJ BIBLIOTEKI (BUILD AUDIT)

- **Polecenie:** `cmake --build native/d3d11_amf_pipeline/build-integration-make --target telem_amd_native --clean-first`
- **Wynik:** `[100%] Built target telem_amd_native (RC=0)`.
- **Weryfikacja ładowania w Pythonie:**
  * Ścieżka: `native/d3d11_amf_pipeline/bin/telem_amd_native.dll` (Rozmiar: 3 066 606 B)
  * Eksportowane symbole: `telem_amd_create`, `telem_amd_drain_amf`, `telem_amd_get_queue_stats`, `telem_amd_update_video_frame_p010` — obecne i zweryfikowane przez `ctypes`.

---

## 11. AUDIT CZYSTOŚCI KODU (`git diff --check`)

- **Polecenie:** `git diff --check`
- **Wynik:** **0 błędów, kod w 100% czysty** (usunięto nadmiarowe spacje i puste linie na końcach plików w `main_window.py`, `video_preview.py`, `icons.py`, `text.py`).

---

## 12. WSZYSTKIE ZMIENIONE PLIKI (31 PLIKÓW)

```text
 def_layout.json
 native/d3d11_amf_pipeline/src/d3d11_amf_encoder.cpp
 native/d3d11_amf_pipeline/src/d3d11_amf_encoder.h
 native/d3d11_amf_pipeline/src/d3d11_vp_pipeline.cpp
 native/d3d11_amf_pipeline/src/telem_amd_native.cpp
 src/ffmpeg/amd_native_exporter.py
 src/gui/layout_manager.py
 src/gui/qt/_mixins/indicator_mixin.py
 src/gui/qt/_mixins/playback_mixin.py
 src/gui/qt/_mixins/preset_mixin.py
 src/gui/qt/_mixins/project_mixin.py
 src/gui/qt/_mixins/render_mixin.py
 src/gui/qt/controller.py
 src/gui/qt/main_window.py
 src/gui/qt/models.py
 src/gui/qt/signals.py
 src/gui/qt/tabs/render_tab.py
 src/gui/qt/tabs/settings_tab.py
 src/gui/qt/widgets/property_editor.py
 src/gui/qt/widgets/video_preview.py
 src/indicators/compositor.py
 src/indicators/gauge.py
 src/indicators/helpers.py
 src/indicators/icons.py
 src/indicators/lean.py
 src/indicators/text.py
 src/indicators/time_display.py
 src/telemetry_imu.py
 src/telemetry_precompute.py
 tests/test_indicator_config_parity.py
 tests/test_time_display_icon_size.py
```

---

## 13. PLIKI DO COMMITU

### Zmodyfikowane pliki produkcyjne (Tracked modified):
Wszystkie 31 plików wymienionych w punkcie 12.

### Nowe pliki produkcyjne i raporty (Untracked to add):
- `src/assets/` (katalog z zasobami ikon SVG)
- `src/gui/qt/widgets/icon_picker.py`
- `tests/test_font_persistence_v2.py`
- `tests/test_gui_v3_runtime_acceptance.py`
- `tests/test_gui_v4_fullscreen_and_next_frame.py`
- `tests/test_gui_v5_autosave_preview_and_aa.py`
- `tests/test_icon_font_gauge_fixes.py`
- `tests/test_icon_library_expanded.py`
- `tests/test_icon_picker_widget.py`
- `tests/test_layout_ownership_and_lean_calibration.py`
- `Raporty/RAPORT_AMD_AMF_ASYNC_QUEUE_DEPTH2.md`
- `Raporty/RAPORT_AMD_CPU_VS_GPU_DECODE_BENCHMARK.md`
- `Raporty/RAPORT_AMD_CURRENT_41FPS_BOTTLENECK_AUDIT.md`
- `Raporty/RAPORT_FONT_FIX_V2_SAVE_SETTINGS_FULLSCREEN.md`
- `Raporty/RAPORT_GUI_FIX_V3_REAL_RUNTIME_ACCEPTANCE.md`
- `Raporty/RAPORT_GUI_V4_FULLSCREEN_LIFECYCLE_NEXT_FRAME.md`
- `Raporty/RAPORT_GUI_V5_AUTOSAVE_PREVIEW_1TO1_AA.md`
- `Raporty/RAPORT_INTEGRATION_ICON_ALIGNMENT_AND_PICKER_UI.md`
- `Raporty/RAPORT_INTEGRATION_ICON_FONT_GAUGE_PROPERTY_FIXES.md`
- `Raporty/RAPORT_INTEGRATION_ICON_SET_UNIFICATION.md`
- `Raporty/RAPORT_LAYOUT_OWNERSHIP_AND_LEAN_HUD_FIX.md`
- `Raporty/RAPORT_AMD_FINAL_CHECKPOINT_READINESS.md`

---

## 14. PLIKI, KTÓRYCH NIE WOLNO COMMITOWAĆ (SCRATCH / RUNTIME ARTIFACTS)

Kategoryczny zakaz dodawania do git:
- `scratch/*` (wszystkie pliki tymczasowe, logi, wygenerowane pliki MP4, zrzuty klatek, skrypty robocze benchmarków)
- `Video/*.telemetry.json.gz` (lokalna pamięć podręczna telemetrii GPMF)
- `Video/output_h265.audio.concat.txt` (plik roboczy łączenia ścieżek audio)

---

## 15. PROPONOWANY KOMUNIKAT COMMITU

```text
feat(amd,gui): AMF ASYNC depth 2, Direct MP4 Mux, Lean calibration, UI enhancements & decode audit

- AMD Pipeline: Production-enable AMF HEVC ASYNC Queue Depth 2 and Direct MP4 Mux
  (eliminates post-render remux overhead, boosts 4K throughput to ~41.5-42.5 FPS).
- Decode Path: Audited CPU decode vs GPU VCN decode on Ryzen 7 7730U. Proven that
  GPU D3D11VA remains superior (VCN offload is not beneficial due to RAM bandwidth
  and CPU starvation). CPU decode preserved as isolated diagnostic-only mode.
- Lean Indicator: Added +6.0 deg pitch calibration, bike icon graphics, centered
  pivot and vectorized telemetry precomputation.
- GUI / Editor: Added fullscreen (F11/Esc), frame stepping, 1:1 preview with antialiasing,
  explicit settings save, icon picker, and decoupled tick thickness/length properties.
- Tests & Validation: 105 pytest regression tests passing; multi-file boundary,
  cancel safety, and range contract tests verified.
```

---

## FINAL VERDICT

```text
AMD GPU DECODE DEFAULT:        YES
CPU DECODE GUI:                NO
CPU DECODE EXPERIMENT:         KEEP (DIAGNOSTIC ONLY)
ASYNC DEPTH2 DEFAULT:          YES
HUD P0:                        NO (MARGINAL EXPECTED FPS GAIN < 1%)
WORKTREE READY FOR CHECKPOINT: YES
```
