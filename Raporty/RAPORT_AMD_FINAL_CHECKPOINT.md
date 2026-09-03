# RAPORT: AMD FINAL CHECKPOINT
**Data:** 2026-09-03  
**Repo:** `C:\_DEV\TeleM-integration`  
**Branch:** `integration/intel-amd`  

---

## 1. ACTUAL HEAD BEFORE CHECKPOINT
- **Hash przed checkpointem:** `c80ba07` (`Docs: update AMD multi-file direct mux report with final safety acceptance details`)
- **Stan wyjściowy:** Potwierdzono, że Direct MP4 Mux znajdował się już w historii repozytorium (`20c62f3`, `356d45f`, `c80ba07`).

---

## 2. NOWE COMMITY I ICH HASHE

Podział na dwa spójne, logiczne checkpointy:
1. **Commit A (GUI / Layout / Indicators):**  
   Hash: `47ee0b4`  
   Tytuł: `feat(gui): finalize layout persistence, preview controls and indicator parity`
2. **Commit B (AMD Pipeline / Decode Path):**  
   Hash: `b4047ab`  
   Tytuł: `perf(amd): finalize async AMF pipeline and AMD decode path`

---

## 3. ZAWARTOŚĆ KAŻDEGO COMMITA

### Commit A (`47ee0b4`) — GUI, layout & indicators:
- **Layout persistence & ownership:** Rozdzielenie logiki szablonu aplikacji od stanu projektu i presetów użytkownika (`layout_manager.py`, `preset_mixin.py`, `project_mixin.py`, `def_layout.json`).
- **Sterowanie podglądem (Preview controls):** Obsługa pełnego ekranu (F11 / Esc), precyzyjny krok o 1 klatkę ($\leftarrow$ / $\rightarrow$), podgląd 1:1 z antyaliasingiem (`playback_mixin.py`, `video_preview.py`, `main_window.py`).
- **Parytet i właściwości wskaźników:** Rozdzielenie grubości i długości podziałek wskaźników (ticks length/thickness decoupling), utrwalanie czcionek Arial/custom, ujednolicenie metryk optycznych i wyrównania ikon (`gauge.py`, `helpers.py`, `icons.py`, `text.py`, `time_display.py`, `property_editor.py`, `models.py`).
- **Biblioteka ikon i wybierak:** Rozszerzona biblioteka wektorowych ikon SVG (`src/assets/icons/svg/`) oraz dedykowany widget `IconPicker` (`icon_picker.py`).
- **Wskaźnik Lean (przechył motocykla):** Kalibracja kąta przechyłu (+6.0°), grafika motocykla (`bike`) ze środkiem obrotu w punkcie styku opon z podłożem, wektorowa prekomputacja IMU (`lean.py`, `telemetry_imu.py`, `telemetry_precompute.py`).
- **Zestaw testów i raportów:** 10 nowych/zaktualizowanych plików testowych oraz 8 raportów etapowych.

### Commit B (`b4047ab`) — AMD Backend & Decode:
- **Kolejkowanie AMF ASYNC Depth 2:** Domyślny tryb `AMD_CPU_GPU_PIPELINE=ASYNC` oraz `AMD_QUEUE_DEPTH=2` w C++ i Pythonie; optymalny przepływ klatek, 0 przepełnień `AMF_INPUT_FULL`, brak wycieków pamięci VRAM (`d3d11_amf_encoder.cpp`, `d3d11_amf_encoder.h`, `telem_amd_native.cpp`, `amd_native_exporter.py`).
- **Obsługa natywnego uploadu 10-bit P010:** Wdrożenie `telem_amd_update_video_frame_p010` do pamięci `DXGI_FORMAT_P010`, odizolowane pod zmienną środowiskową `AMD_DECODE_MODE=CPU`.
- **Domyślna konfiguracja dekodowania:** Gwarancja, że `AMD_DECODE_MODE=GPU` (D3D11VA / VCN) jest domyślną, produkcyjną ścieżką.
- **Raporty wydajnościowe AMD:** Włączenie raportów `RAPORT_AMD_AMF_ASYNC_QUEUE_DEPTH2.md`, `RAPORT_AMD_CURRENT_41FPS_BOTTLENECK_AUDIT.md`, `RAPORT_AMD_CPU_VS_GPU_DECODE_BENCHMARK.md` oraz `RAPORT_AMD_FINAL_CHECKPOINT_READINESS.md`.

---

## 4. AUDYT def_layout.json
- **Status:** **ZATWIERDZONY**.
- **Dlaczego:** Plik `def_layout.json` zawiera wyłącznie kanoniczne, domyślne definicje szablonu (domyślny klucz `"font": ""`, schemat dla `lean_indicator` z kalibracją 6.0° i ikoną `bike`, schematy wskaźników baterii i ISO).
- **Weryfikacja wycieków:** Potwierdzono brak jakichkolwiek ścieżek bezwzględnych (`C:\`), brak odwołań do konkretnych plików wideo (`GX010115`, `.MP4`, `Video`), brak lokalnego stanu użytkownika (`_startup_preset` pusty).

---

## 5. BRAK ARTEFAKTÓW PROJEKTOWYCH / LOKALNYCH
- Żaden plik z katalogu `scratch/` nie został dodany do indeksu git.
- Usunięto tymczasowy plik roboczy `Video/output_h265.audio.concat.txt`.
- Lokalne pliki pamięci podręcznej telemetrii `Video/*.telemetry.json.gz` pozostały nieśledzone (`untracked`).
- Brak plików `Video/*.layout.json`, `Video/*.part`, `Video/*.mp4` w commicie.

---

## 6. GPU DECODE JAKO DOMYŚLNY
- Domyślna wartość w kodzie produkcyjnym: `AMD_DECODE_MODE=GPU`.
- Dekodowanie sprzętowe D3D11VA (Media Foundation Source Reader via VCN) jest jedyną aktywną ścieżką w standardowym wywołaniu.

---

## 7. CPU DECODE DIAGNOSTIC-ONLY
- Ścieżka CPU decode aktywuje się wyłącznie po jawnym ustawieniu flagi środowiskowej `AMD_DECODE_MODE=CPU`.
- Brak przełączników w interfejsie graficznym (GUI), brak trybu automatycznego (Auto), brak przypadkowego fallbacku.

---

## 8. ASYNC DEPTH 2 JAKO DOMYŚLNY
- Domyślna konfiguracja potoku: `AMD_CPU_GPU_PIPELINE=ASYNC`, `AMD_QUEUE_DEPTH=2`.
- Potwierdzone zerowe przepełnienia kolejki (`AMF_INPUT_FULL`), stabilna praca i brak potrzeby stosowania Depth 3.

---

## 9. WYNIKI TESTÓW (TEST SANITY)
- **Polecenie:** `python -m pytest tests/test_layout_ownership_and_lean_calibration.py tests/test_gui_v3_runtime_acceptance.py tests/test_gui_v4_fullscreen_and_next_frame.py tests/test_gui_v5_autosave_preview_and_aa.py tests/test_icon_font_gauge_fixes.py tests/test_indicator_config_parity.py tests/test_time_display_icon_size.py -q`
- **Wynik:** **105 PASSED / 0 FAILED (9.43 s)**.

---

## 10. REZULTAT KOMPILACJI NATYWNEJ
- **Polecenie:** `cmake --build native/d3d11_amf_pipeline/build-integration-make --target telem_amd_native`
- **Wynik:** `[100%] Built target telem_amd_native (RC=0)`.
- **Weryfikacja ctypes w Pythonie:** Pomyślne załadowanie biblioteki `telem_amd_native.dll` i weryfikacja wszystkich symboli natywnych.

---

## 11. AUDYT CZYSTOŚCI KODU (`git diff --check`)
- **Polecenie:** `git diff --check`
- **Wynik:** **0 błędów** (czyste białe znaki, brak zbędnych spacji na końcach linii i brak nadmiarowych pustych linii na końcu plików).

---

## 12. FINALNY STAN GIT (STATUS)
```text
On branch integration/intel-amd
Your branch is up to date with 'origin/integration/intel-amd'.

Untracked files:
  (wyłącznie lokalne pliki scratch i cache telemetryczny):
	Video/GX010114.telemetry.json.gz
	Video/GX010115.telemetry.json.gz
	Video/GX010116.telemetry.json.gz
	scratch/
```

---

## 13. WYNIK POLECENIA PUSH
- **Polecenie:** `git push origin integration/intel-amd`
- **Wynik:**
  ```text
  To https://github.com/malcerz/TeleM.git
     c80ba07..b4047ab  integration/intel-amd -> integration/intel-amd
  ```

---

## 14. FINALNY REMOTE BRANCH HEAD
- **Remote HEAD:** `b4047ab` (`perf(amd): finalize async AMF pipeline and AMD decode path`)

---

## FINAL VERDICT

```text
CHECKPOINT CREATED:            YES
PUSHED:                        YES
TRACKED WORKTREE CLEAN:        YES
AMD PRODUCTION BASELINE:       41.512 FPS (17 760 frames, 4K UHD)
AMD OPTIMIZATION PHASE:        CLOSED
```
