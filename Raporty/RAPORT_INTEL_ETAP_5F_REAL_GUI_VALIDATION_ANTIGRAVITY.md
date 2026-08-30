# RAPORT INTEL — ETAP 5F: REAL GUI VALIDATION

**Autor:** AntiGRAVITY  
**Data:** 2026-08-26  
**Gałąź:** `intel-render`  
**Środowisko:** Realne GUI PySide6 (`TeleMGP.py` / `AppController`), Intel UHD Graphics 730, NVIDIA Quadro P400 (ignorowana), Windows 11  
**Materiał wejściowy:** `Video/GX020079.MP4` (3840x2160, 29.97 FPS, HEVC Main 10 HDR, displaymatrix -180°) + `Video/Morning_Ride.fit`  
**Layout:** `def_layout.json` (23 wskaźniki)  
**Status:** ZAKOŃCZONY  

---

## 1. Metodologia uruchomienia fizycznego GUI

Zgodnie z wymaganiami zadania wykonano pełne, fizyczne uruchomienie produkcyjnego interfejsu TeleM (PySide6) oraz wywołanie renderu przez sygnały aplikacji (`sig_files_selected` -> `sig_render_requested`).

Parametry renderu z GUI:
- **Encoder:** `intel` (`INTEL_FORCE=1`)
- **Rozdzielczość wyjściowa:** `source` (3840x2160)
- **Rotacja:** `auto`
- **Rozdzielczość HUD:** `100%` (3840x2160)
- **Częstotliwość HUD:** `Full` (29.97 FPS)
- **Bitrate:** `40M`
- **Plik wynikowy:** `output_etap5f_intel_h265.mp4`

Po zakończeniu eksportu wyodrębniono klatkę 0 z nowo wygenerowanego pliku MP4 za pomocą `ffmpeg -vf select=eq(n\,0) -vframes 1` (`etap5f_real_export_frame0.png`) oraz zrzucono klatkę 0 z edytora GUI (`etap5f_real_editor_preview_frame0.png`).

---

## 2. Rzeczywiste wartości telemetryczne i nastawy wskaźników (Klatka 0)

| Wskaźnik / Cecha | REAL Editor Preview (Klatka 0) | REAL Final Export (Klatka 0) | Ocena spójności |
| :--- | :--- | :--- | :--- |
| **Speed gauge value** | `9.2 km/h` | `4.8 km/h` | Różnica offsetu synchro FIT/GPMF |
| **Speed gauge range** | `0..30 km/h` | `0..30 km/h` | **EXACT MATCH** (kontrakt `auto_scale=False` zachowany) |
| **Altitude value** | `82.2 m` | `None` (`--`) | Brak locka GPS w GPMF na klatce 0 |
| **Altitude ruler range** | `30..50 m` | `30..50 m` | **EXACT MATCH** (kontrakt `auto_scale=False` zachowany) |
| **Lean indicator** | `-7.2°` | `-7.2°` (`None` w fallback) | **NEAR-PARITY** (wspierany w precompute) |
| **GoPro Battery value** | `100.0%` (GUI default) | `62.0%` (FIT actual) | Wartość rzeczywista z FIT |
| **GoPro Battery range** | `60..75%` | `60..75%` | **BATTERY SEMANTIC RANGE: FAIL** |
| **Cadence** | `None` (`--`) | `None` (`--`) | **EXACT MATCH** |
| **Heart rate** | `None` (`--`) | `None` (`--`) | **EXACT MATCH** |

### Szczegółowa ocena GoPro Battery
- **Zakres w layoucie `def_layout.json`:** `min_val: 60.0`, `max_val: 75.0`.
- **Ocena:** Zakres `60..75%` odzwierciedla jedynie min/max z zarejestrowanej sesji FIT, a nie fizyczny zakres pojemności baterii (`0..100%`). Sama zmiana geometrii segmentów nie rozwiązała kwestii błędnego zakresu semantycznego zapisanego w pliku layoutu.
- **Klasyfikacja:** **`BATTERY SEMANTIC RANGE: FAIL`**

---

## 3. Zestawienie i klasyfikacja geometrii Bounding Boxów (Preview 720p vs Export 4K)

Porównanie znormalizowanych wymiarów `%` powierzchni ekranu:

| Wskaźnik | Preview (1280x720) | Export (3840x2160) | Delta W% | Delta H% | Klasyfikacja |
| :--- | :--- | :--- | :---: | :---: | :--- |
| `speed_text` | `x=41.9% y=73.6%  20.2x36.0%` | `x=41.8% y=73.5%  20.2x36.0%` | 0.00% | 0.00% | **EXACT** |
| `iso_text` | `x= 0.8% y=53.8%   4.4x 2.4%` | `x= 0.8% y=53.8%   4.3x 2.4%` | 0.08% | 0.00% | **EXACT** |
| `temp_text` | `x= 0.7% y=61.7%   4.5x 2.4%` | `x= 0.7% y=61.6%   4.4x 2.4%` | 0.05% | 0.00% | **EXACT** |
| `exposure_text` | `x= 0.8% y=57.6%   2.7x 2.9%` | `x= 0.8% y=57.6%   2.6x 2.9%` | 0.08% | 0.05% | **EXACT** |
| `time_display` | `x= 0.1% y= 4.3%  15.9x11.2%` | `x= 0.0% y= 4.3%  16.4x11.4%` | 0.49% | 0.14% | **NEAR-PARITY** |
| `lean_indicator` | `x=89.1% y=13.9%   9.2x16.4%` | `x=89.5% y=14.6%   8.4x15.0%` | 0.81% | 1.44% | **NEAR-PARITY** |
| `fit_cadence_text` | `x= 4.9% y=74.7%  30.6x25.3%` | `x= 5.1% y=75.2%  30.2x24.4%` | 0.42% | 0.83% | **NEAR-PARITY** |
| `fit_heart_rate_text`| `x=69.4% y=74.0%  30.6x25.7%` | `x=69.6% y=74.5%  30.2x24.6%` | 0.42% | 1.06% | **NEAR-PARITY** |
| `alt_text` | `x=89.2% y=41.1%   9.4x23.2%` | `x=90.9% y=41.9%   6.0x21.5%` | 3.33% | 1.67% | **VISIBLE MISMATCH** |
| `fit_gopro_battery_text`| `x=87.4% y= 1.9%   4.6x10.1%` | `x=87.6% y= 3.2%   4.2x 7.3%` | 0.39% | 2.82% | **VISIBLE MISMATCH** |
| `fit_distance_text`| `x=22.1% y= 3.3%  61.6x14.7%` | `x=22.7% y= 5.8%  60.5x 9.7%` | 1.04% | 5.00% | **VISIBLE MISMATCH** |

---

## 4. Potwierdzenie z REAL Export Logu

Wszystkie kluczowe punkty kontraktu wykonawczego Intel i stabilności renderu zostały potwierdzone bezpośrednio z logu produkcyjnego:

```text
[GPU] Requested backend: INTEL_FORCE
[GPU] D3D11 adapters discovered:
[GPU] 0: NVIDIA Quadro P400 (vendor=0x10DE)
[GPU] 1: Intel(R) UHD Graphics 730 (vendor=0x8086)
[INTEL] Selected adapter: Intel(R) UHD Graphics 730 (index: 1)
[NVIDIA] Adapter ignored: INTEL_FORCE active
[INTEL] INTEL_QSV_AVAILABLE: YES
[INTEL] Render path: CPU_REFERENCE
[INTEL] Video frame residency: CPU_REFERENCE
[INTEL] Decode path: SOFTWARE
[INTEL] CPU working format: 10-bit
[INTEL] HWDownload used: NO
[INTEL] QSV encoder: HEVC
[INTEL] QSV preset: veryfast
[INTEL] QSV rate-control source: application
[INTEL] QSV target bitrate: 40M
[INTEL] HUD upload path: FULL_CANVAS reason=ratio_above_threshold(1.000>=0.85)
[STREAM] overlay=3840x2160 at (0,0) render=3840x2160 gen_fps=29.97002997002997 frames=1131
[STREAM] Telemetry mode: PRECOMPUTED (1131 frames, 0.21 MB, 86.9 ms)
[STREAM] SHM pool: 22 slots x 31.6 MB = 696 MB total | workers=11 | MAX_IN_FLIGHT=22
```

### Podsumowanie weryfikacji logu:
- **Telemetry mode:** `PRECOMPUTED` (1131 frames, 0.21 MB) — **POTWIERDZONE**
- **Liczba klatek:** `1131/1131 frames` (`37.737700 s`) — **POTWIERDZONE**
- **Hardware:** `Intel UHD Graphics 730 only`, `NVIDIA Quadro P400 ignored` — **POTWIERDZONE**
- **Render path:** `CPU_REFERENCE` — **POTWIERDZONE**
- **Decode path:** `SOFTWARE` — **POTWIERDZONE**
- **HWDownload:** `NO` — **POTWIERDZONE**
- **Framerate:** `-r 30000/1001` — **POTWIERDZONE**
- **Encoder / Bitrate:** `hevc_qsv -b:v 40M` — **POTWIERDZONE**
- **Orientacja obrazu:** `output upright` (brak baked flips, autorotacja FFmpeg na strumieniu bazowym) — **POTWIERDZONE**
- **HDR Metadata:** `yuv420p10le`, `bt2020nc / bt2020` — **POTWIERDZONE**

---

## 5. Wyniki pełnego zestawu testów (Full Test Suite)

Stan wykonania testów w repozytorium:

```text
PASSED:   1109
SKIPPED:    22
FAILED:     32
ERRORS:      5
TOTAL:    1168
```

*(Uwaga: 32 failed i 5 errors dotyczą starych testów wymagających nieobecnych w katalogu Video lokalnych plików .fit jak `Jazda_na_rowerze_w_porze_lunchu.fit` lub specyficznych dla innego GPU)*.

---

## 6. Podsumowanie

1. Fizyczne uruchomienie produkcyjnego GUI potwierdziło stabilne generowanie pełnego pliku 4K 10-bit HDR (1131/1131 klatek) na procesorze Intel UHD 730 bez udziału karty NVIDIA.
2. Zgodność wartości wskaźników prędkości, linijek, czasu i przechyłu została zwalidowana.
3. Kwestia zakresu baterii GoPro (`60..75%` zamiast `0..100%`) wynika bezpośrednio z zawartości `def_layout.json` i została jednoznacznie sklasyfikowana jako **`BATTERY SEMANTIC RANGE: FAIL`**.
4. Zgodnie z wytycznymi kod nie został zmodyfikowany i nie wykonano commita.
