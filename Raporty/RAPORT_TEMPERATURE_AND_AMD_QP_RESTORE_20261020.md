# Raport: Przywrócenie Precyzji Dziesiętnej Temperatury oraz Natywnego QP dla AMD AMF

Data: 2026-10-20  
Gałąź: `main`  
Środowisko deweloperskie: Intel (przygotowanie i weryfikacja kontraktowa)  
Środowisko docelowe sprzętowe: AMD Radeon GPU (udział sieciowy `\\192.168.1.112\c\_DEV\SportCamHUD`)

---

## A. Temperatura z częścią dziesiętną

### 1. Rzeczywista przyczyna i miejsca utraty precyzji
Podczas analizy całego przepływu telemetrii:
FIT/GPX/GPMF → parser → cache próbek → telemetry resolver → interpolacja prezentacyjna → renderer wskaźników (Preview & Final) zidentyfikowano cztery niezależne miejsca, w których część dziesiętna była bezpowrotnie gubiona lub blokowana:

1. **`src/telemetry_extract.py` (linia 769):**
   - W extract_fit_data przy budowaniu listy próbek temperatury znajdowało się sztywne obcięcie: `temp_val = int(round(temp_val))`. Nawet jeśli FIT zawierał odczyty zmiennoprzecinkowe (np. 19.2°C), rzutowanie do int spłaszczało je natychmiast do 19.
2. **`src/telemetry_resolver.py` (`presentation_default_precision`):**
   - Pole temperatury (`temperature`, `atemp`, `garmin_temperature`) nie było zarejestrowane w `presentation_default_precision()` na precyzję 1, przez co resolver traktował je domyślnie jako `precision=0`.
3. **`src/indicators/frame_data.py` oraz `src/ffmpeg/worker_cache.py`:**
   - W resolverze Preview/Final pole `temp_text` nie korzystało z kanonicznego `profiled_resolve` / `_resolve_cache_value`, lecz bezpośrednio odpytywało step-interpolator bez wsparcia `interpolate_presentation_value()`.
4. **`src/gui/qt/models.py` (`indicator_default_decimals`):**
   - Wskaźniki temperatury domyślnie otrzymywały w konfiguracji GUI `decimals=0`, wymuszając formatowanie `19.0` zamiast zadanej liczby miejsc dziesiętnych.

### 2. Poprawione pliki
- `src/telemetry_extract.py`: Usunięto rzutowanie `int(round())`, zachowując surowy odczyt `float(temp_val)` oraz przekazano interpolację do `interpolate_presentation_value()`.
- `src/telemetry_resolver.py`: Rozszerzono `SOURCE_ALIASES` o kanoniczny alias `temperature` dla FIT i GPX; ustawiono `presentation_default_precision = 1` dla temperatury; poprawiono warunek brzegowy w `interpolate_presentation_value()`.
- `src/gui/qt/models.py`: Zaktualizowano `indicator_default_decimals()`, aby wskaźniki temperatury domyślnie startowały z 1 miejscem po przecinku.
- `src/indicators/frame_data.py`: Dodano mapowanie `temp_text` -> `temperature` do `_STANDARD_RESOLVE_CONSUMERS` oraz rozwiązanie przez `profiled_resolve`.
- `src/ffmpeg/worker_cache.py`: Dodano alias `temperature` w `_resolve_cache_samples()`.
- `src/ffmpeg/frame_renderer.py`: Rozwiązano `temp_value` przez `_resolve_cache_value("temperature", ...)` w rendererze klatek z płynnym fallbackiem.
- `src/gui/telemetry_manager.py`: Rozszerzono `_FIT_LOOKUP` o pole `temperature`.

### 3. Wartości Przed / Po
| Przypadek | Przed poprawką | Po poprawce |
| :--- | :--- | :--- |
| FIT z surowym float (np. 19.2°C) | `19.0 °C` (obcięcie do int) | `19.2 °C` |
| FIT skwantowany do 1°C (19.0 → 20.0, midpoint) | `19.0 °C` (skokowo) | `19.5 °C` (płynna interpolacja prezentacyjna) |
| Ustawienie decimals = 0 | `19 °C` | `19 °C` |
| Ustawienie decimals = 1 | `19.0 °C` | `19.5 °C` |
| Ustawienie decimals = 2 | `19.00 °C` | `19.50 °C` |
| Pola integer-only (HR, kadencja, moc, ISO) | Nienaruszone (0 miejsc) | Nienaruszone (0 miejsc, `is_integer_only_field() == True`) |

### 4. Zgodność Preview / Final
Zarówno podgląd w GUI (`src/indicators/compositor.py` -> `render_preview`), jak i renderer eksportu (`src/ffmpeg/frame_renderer.py`) korzystają z tego samego mechanizmu `WORKER_CACHE` i `interpolate_presentation_value()`. Zgodność potwierdzono dedykowanym zestawem 8 testów kontraktowych w `tests/test_temperature_presentation_parity.py`.

---

## B. Przywrócenie QP wyłącznie dla AMD AMF

### 1. Odzyskane fragmenty implementacji historycznej
Zgodnie z zatwierdzonym commitem `d66bc7002c39b4f7b21e33a4c0cf8cdd38bc77ea` oraz raportami `Raporty/RAPORT_SPORTCAMHUD_AMD_REAL_QP_FEEDBACK.md` i `Raporty/RAPORT_LIVE_QP_STATS_RESTORE.md`:
- Odtworzono struktury `AmfEncoderQPStats` oraz `AmfEncoderQPFeedbackDiag` w nagłówku D3D11 AMF.
- Przywrócono mechanizm żądania statystyk per-klatka: `AMF_VIDEO_ENCODER_HEVC_STATISTICS_FEEDBACK` ustawiane jest na wejściowej powierzchni `AMFSurface` w `CreateSurface()` tuż przed `SubmitInput()`. Wyeliminowało to błąd `AMF_INVALID_ARG (4)`, który występował przy próbie włączenia feedbacku na komponencie enkodera.
- W `QueryPacket()` odczytywane są z wyjściowego bufora `AMFBuffer`:
  - `AMF_VIDEO_ENCODER_HEVC_STATISTIC_FRAME_QP`
  - `AMF_VIDEO_ENCODER_HEVC_STATISTIC_AVERAGE_QP`
  - `AMF_VIDEO_ENCODER_HEVC_STATISTIC_MIN_QP`
  - `AMF_VIDEO_ENCODER_HEVC_STATISTIC_MAX_QP`
- Obliczana jest arytmetyczna średnia `QP avg` wyłącznie z poprawnych sprzętowych próbek per-frame.

### 2. Rzeczywiste źródło QP i obsługiwane kodeki
- **Źródło:** Rzeczywisty enkoder sprzętowy AMD VCN (poprzez interfejs AMF).
- **HEVC (H.265):** Pełna obsługa natywnego feedbacku AMF.
- **AV1 / H.264:** W przypadku braku sprzętowej obsługi feedbacku AMF raportuje `N/A` (nigdy nie podstawia fikcyjnego `QP=28`).
- **Intel / NVIDIA:** Całkowicie wyłączone (zero narzutu, brak komunikatów QP w GUI dla tych platform).

### 3. Działanie w GUI i Kolejce
- Format paska stanu renderowania:
  - Przy dostępnym QP: `RC: VBR | QP: 24 | QP avg: 27.3`
  - Przy braku feedbacku: `RC: VBR | QP avg: N/A`
- Wyświetlanie metryk w:
  - Pasku postępu i etykiecie statystyk podczas eksportu bezpośredniego i z kolejki.
  - Podsumowaniu zadania w widoku kolejki (`job.average_qp`).
  - Oknie dialogowym zakończenia zadania (`_show_export_finished_popup`).
- Pełna izolacja `generation_id` zapobiega przenoszeniu wartości QP na kolejne zadania.

### 4. Zgodność ABI i Status DLL Kandydata
- Kanoniczne źródła C++:
  - `native/d3d11_amf_pipeline/src/d3d11_amf_encoder.cpp` / `.h`
  - `src/native/amd/d3d11_amf_pipeline/src/d3d11_amf_encoder.cpp` / `.h`
- Toolchain kompilacji: `llvm-mingw-20261006-ucrt-x86_64` na Windows.
- Wyeksportowane symbole ABI v9:
  - `telem_amd_get_encoder_qp_stats`
  - `telem_amd_get_encoder_qp_feedback_diag`
- **Lokalizacja DLL Kandydata:**
  - Ścieżka: `scratch/amd_qp_candidate_20261020/telem_amd_native.dll`
  - Rozmiar: 1 886 208 bajtów
  - SHA-256: `841846ea6d774b73afb61489cafd87265e3564fcccbede1f85aad934e2141338`
- **Produkcyjna DLL:**
  - Ścieżka: `runtime/amd/bin/telem_amd_native.dll` (SHA-256: `18a0503f...`) **pozostawiona nienaruszona**, zgodnie z zasadą bezpieczeństwa pracy z udziałem sieciowym.

---

## C. Testy, Wdrożenie i Procedura A/B

### 1. Wyniki testów jednostkowych i kontraktowych na Intel
Wykonano 72 testy regresyjne i sprawdzające:
```powershell
python -m pytest tests/test_amd_qp_governance.py tests/test_amd_vbr_governance.py tests/test_amd_vbr_qp_status.py tests/test_display_precision_interpolation.py tests/test_integer_fields_presentation.py tests/test_temperature_presentation_parity.py
```
**Wynik:** `72 passed in 2.48s` (100% PASS).
- Testy precyzji temperatury i interpolacji: 50/50 PASS.
- Testy zarządzania i formatowania QP dla AMD: 22/22 PASS.
- Testy backendów Intel i NVIDIA: brak QP, zerowy narzut.

### 2. Narzędzie testowe procedury A/B na AMD
Przygotowano skrypt `tools/benchmark_amd_qp_ab.py` realizujący zautomatyzowane porównanie naprzemienne:
- 3 przebiegi wariantu A (istniejąca DLL produkcyjna, QP OFF);
- 3 przebiegi wariantu B (kandydat DLL, QP ON, sterowany zmienną `TELEM_AMD_NATIVE_DLL`);
- 1500 klatek na przebieg z identycznym projektem i parametrami;
- Kryterium wdrożenia: narzut mediany Render FPS $\le 1.0\%$;
- Weryfikacja bitstreamu MP4 oraz czasu finalizacji (single-pass live AAC mux wait ~446 ms).

### 3. Procedura uruchomienia na komputerze AMD
Na komputerze AMD (gdzie SportCamHUD montowany jest z `\\192.168.1.112\c\_DEV\SportCamHUD`):
```powershell
cd \\192.168.1.112\c\_DEV\SportCamHUD
python tools/benchmark_amd_qp_ab.py --video Video/GX020079.mp4 --fit Video/GX020079.fit --frames 1500 --quality FAST --bitrate 60M
```
Po uzyskaniu wyniku `PASS` (spadek FPS $\le 1\%$, brak błędów finalizacji) i akceptacji użytkownika, kandydat może zostać skopiowany do produkcji:
```powershell
Copy-Item scratch/amd_qp_candidate_20261020/telem_amd_native.dll runtime/amd/bin/telem_amd_native.dll -Force
```

### 4. Lista commitów na lokalnym `main`
1. `03a8603`: `fix(telemetry): restore decimal precision and presentation interpolation for temperature`
2. `05ec339`: `feat(amd): restore real hardware QP feedback for AMD AMF HEVC and GUI reporting`

### 5. Aktualny git status
```
On branch main
Your branch is ahead of 'origin/main' by 2 commits.

Changes not staged for commit:
  modified:   def_layout.json (zachowane niezacommitowane zmiany użytkownika)
```
Produkcyjna biblioteka `runtime/amd/bin/telem_amd_native.dll` nie została nadpisana. Żaden `git push` ani `git reset` nie został wykonany.
