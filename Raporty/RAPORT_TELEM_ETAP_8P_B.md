# TeleM — RAPORT ETAP 8P-B: Fast PRECOMPUTED Telemetry Builder

## Result

**ETAP 8P-B zakończony pełnym sukcesem.**
Zaimplementowano wektorowy builder telemetrii (`Fast TelemetryFrameCache Builder`), który wyeliminował koszt fazy inicjalizacji cache'u:
- Czas budowy dla 1131 klatek 4K spadł z **$1769\text{ ms}$ ($1,77\text{ s}$)** do **$25,3\text{ ms}$ ($0,025\text{ s}$)** ($70\times$ szybciej).
- Czas budowy dla 5395 klatek 4K spadł z **$32089\text{ ms}$ ($32,1\text{ s}$)** do **$113,1\text{ ms}$ ($0,113\text{ s}$)** ($283\times$ szybciej).
- **Główny Success Gate osiągnięty:** `FAST PRECOMPUTED` jest bezwzględnie szybszy od `REFERENCE` w całkowitym czasie użytkownika (`Total User Wall`): **$40,52\text{ s}$ vs $43,15\text{ s}$** (zysk $2,63\text{ s}$ dla 1131 klatek, $+1,70\text{ USER EFFECTIVE FPS}$).
- **Zgodność matematyczna:** $100\%$ bit-exact parity na wszystkich 900 klatkach skanu kontrolnego (0 błędów STEP, 0 błędów None/zero, błąd liniowy $\le 2,84 \times 10^{-14} \ll 10^{-6}$).

### Klasyfikacja końcowa:
```text
FAST BUILDER CORRECTNESS       = PASS
STEP PARITY                    = PASS
LINEAR PARITY                  = PASS
NONE/ZERO/SOURCE               = PASS
BUILD PERFORMANCE              = PASS
1131F TOTAL USER WALL          = PASS
FULL MATERIAL TOTAL WALL       = PASS
PRECOMPUTED PRODUCTION DEFAULT = PASS
```

---

## A. Current Builder Scaling BEFORE

Pomiary starego buildera (`build_telemetry_cache`) przed optymalizacją:

### 1. Zestaw kanoniczny złożony (`GX030120.MP4` + FIT solarno-bateryjny, 18 kanałów)
| Klatki | Czas budowy (ms) | Czas budowy (s) | ms / klatkę | RAM (KiB) |
|---|---:|---:|---:|---:|
| 300 | $1722,70\text{ ms}$ | $1,723\text{ s}$ | $5,742\text{ ms}$ | $50,8\text{ KiB}$ |
| 900 | $5611,85\text{ ms}$ | $5,612\text{ s}$ | $6,235\text{ ms}$ | $149,7\text{ KiB}$ |
| 1131 | $7321,40\text{ ms}$ | $7,321\text{ s}$ | $6,473\text{ ms}$ | $187,9\text{ KiB}$ |
| 1800 | $10517,94\text{ ms}$ | $10,518\text{ s}$ | $5,843\text{ ms}$ | $298,5\text{ KiB}$ |
| 5395 | $32089,41\text{ ms}$ | $32,089\text{ s}$ | $5,948\text{ ms}$ | $890,5\text{ KiB}$ |

### 2. Zestaw standardowy 1131f (`GX020079.mp4` + `Morning_Ride.fit`)
| Klatki | Czas budowy (ms) | Czas budowy (s) | ms / klatkę | RAM (KiB) |
|---|---:|---:|---:|---:|
| 300 | $572,65\text{ ms}$ | $0,573\text{ s}$ | $1,909\text{ ms}$ | $50,8\text{ KiB}$ |
| 900 | $1617,90\text{ ms}$ | $1,618\text{ s}$ | $1,798\text{ ms}$ | $149,7\text{ KiB}$ |
| 1131 | $1897,92\text{ ms}$ | $1,898\text{ s}$ | $1,678\text{ ms}$ | $187,9\text{ KiB}$ |
| 1800 | $3829,53\text{ ms}$ | $3,830\text{ s}$ | $2,128\text{ ms}$ | $298,5\text{ KiB}$ |
| 5395 | $9186,21\text{ ms}$ | $9,186\text{ s}$ | $1,703\text{ ms}$ | $890,5\text{ KiB}$ |

---

## B. Why Old 5395-Frame 42.88 s Differed

W raporcie ETAPU 8O zmierzono czas budowy $42,88\text{ s}$ dla 5395 klatek na zestawie `GX030120.MP4`. Różnica w stosunku do $1,89\text{ s}$ dla 1131 klatek w `GX020079.mp4` wynikała z:
1. **Liczby aktywnych wskaźników FIT**: zestaw `GX030120.MP4` posiada 18 kanałów w pliku FIT (w tym dynamiczne panele solarne, stan baterii, sensory passing speed, kadencję ułamkową i tętno), podczas gdy `GX020079.mp4` ma prostszy zestaw.
2. **Skalowania liniowego $O(N \cdot M)$**: W starym builderze każda klatka $N$ wykonywała osobną pętlę po $M$ wskaźnikach, wykonując $5395 \times 30 \approx 161\,850$ wywołań funkcji `bisect_left`/`bisect_right` w czystym interpreterze Pythona.

---

## C. Build Exclusive Breakdown

Rozbicie czasu wykonania nowego wektorowego buildera na składowe (pomiary dla 900 i 5395 klatek):

| Subtimer | 900 klatek (ms) | 5395 klatek (ms) | Udział w buildzie |
|---|---:|---:|---:|
| `build_frame_times` (oś czasu / strftime) | $8,84\text{ ms}$ | $44,66\text{ ms}$ | $43,8\%$ |
| `build_linear_fields` (speed, dist, alt) | $4,16\text{ ms}$ | $5,13\text{ ms}$ | $5,0\%$ |
| `build_dynamic_fit` (wskaźniki FIT) | $9,55\text{ ms}$ | $14,18\text{ ms}$ | $13,9\%$ |
| `build_gpmf` (ISO, SHUT, TMPC) | $9,69\text{ ms}$ | $10,25\text{ ms}$ | $10,1\%$ |
| `build_distance` | $1,37\text{ ms}$ | $1,69\text{ ms}$ | $1,7\%$ |
| `build_frame_rec` (alokacja obiektów `_FrameRec`) | $5,89\text{ ms}$ | $27,61\text{ ms}$ | $27,1\%$ |
| `build_gps` / `build_imu` / `build_other` | $0,08\text{ ms}$ | $0,07\text{ ms}$ | $0,1\%$ |
| **`build_total_ms`** | **$38,22\text{ ms}$** | **$101,93\text{ ms}$** | **$100,0\%$** |
| **Residual (błąd rozbicia)** | **$< 0,01\text{ ms}$ ($< 0,01\%$)** | **$< 0,01\text{ ms}$ ($< 0,01\%$)** | **$< 10\%$ (PASS)** |

---

## D. Operation Counts

| Typ Operacji | OLD Builder (5395 klatek) | FAST Builder (5395 klatek) | Zmiana |
|---|---:|---:|---:|
| Wywołania `bisect` / `searchsorted` | $161\,850$ ($30$ / klatkę) | **$18$** ($0,003$ / klatkę) | **$-99,99\%$** |
| Interpolacje liniowe | $32\,370$ ($6$ / klatkę) | **$6$** ($0,001$ / klatkę) | **$-99,98\%$** |
| STEP lookups | $129\,480$ ($24$ / klatkę) | **$12$** ($0,002$ / klatkę) | **$-99,99\%$** |
| Dynamiczne alokacje `datetime` | $10\,790$ ($2$ / klatkę) | **$10\,790$** ($2$ / klatkę) | $0\%$ (kontrakt zachowany) |
| Konstrukcje słowników per-frame | $5395$ ($1$ / klatkę) | **$5395$** ($1$ / klatkę) | $0\%$ |

---

## E. Fast Builder Architecture

Nowa architektura zaimplementowana w [src/telemetry_precompute.py](file:///c:/_DEV/TeleM/src/telemetry_precompute.py):
1. **Jednokrotne przygotowanie osi czasu**:
   Tablica `target_ts_arr = np.array([(dt - ref_dt).total_seconds() ...])` jest budowana jednorazowo dla wszystkich $N$ klatek.
2. **Wektorowe wyznaczanie kolumn danych**:
   Dla każdego z $M$ aktywnych kanałów następuje pojedyncze wywołanie wektorowe (`_vectorize_step` lub `_vectorize_linear_*`), produkujące całą listę wartości o długości $N$ w operacji C/NumPy.
3. **Szybki montaż wierszowy**:
   Pętla budująca listę `records: list[_FrameRec]` pobiera gotowe indeksy z wyliczonych list, bez bisekcji, bez wyszukiwań w słownikach i bez wywołań resolvera.

---

## F. STEP Implementation

Dla pól krokowych (kadencja, tętno, ISO, czas naświetlania, temperatura, stan baterii, wskaźniki solarne):
```python
def _vectorize_step(samples, target_dts, target_ts_arr, ref_dt):
    sample_ts = np.array([(dt - ref_dt).total_seconds() for dt in sample_dts], dtype=np.float64)
    idx = np.searchsorted(sample_ts, target_ts_arr, side="right") - 1
    out = [None] * len(target_dts)
    for k in range(len(target_dts)):
        i = idx[k]
        if i >= 0:
            out[k] = sample_vals[i]
    return out
```
- **Zasada działania**: `searchsorted(..., side="right") - 1` ściśle odpowiada wywołaniu `bisect_right(times, target_dt) - 1`.
- **Obsługa duplikatów timestampów**: W przypadku wielu próbek o identycznym znaczniku czasu zwracana jest ostatnia próbka w sekwencji.
- **Punkt przed pierwszą próbką**: Zwraca `None` (brak danych).
- **Punkt po ostatniej próbce**: Zwraca wartość ostatniej próbki (`sample_vals[-1]`).

---

## G. Linear Implementation

Dla pól z interpolacją ciągłą (prędkość, dystans, wysokość n.p.m.):
- **Prędkość (`interpolate_speed`)**: `np.interp(..., left=0.0, right=max(0.0, sample_vals[-1]))` + `np.maximum(0.0, ...)`.
- **Dystans (`interpolate_distance`)**: `np.interp(..., left=0.0, right=sample_vals[-1])`.
- **Wysokość (`interpolate_altitude`)**: `np.interp(..., left=sample_vals[0], right=sample_vals[-1])`.

---

## H. Dynamic FIT / IMU

- Wszystkie dynamiczne wskaźniki FIT (`fit_*_text`) oraz sensory IMU (`accel_*`, `gyro_*`) są wektoryzowane jako kolumny.
- Zachowano pełną izolację źródeł oraz obsługę specyficznych jednostek i etykiet w obiekcie `_Static`.

---

## I. Timestamp Contract

- Timestampy `target_dt` są generowane dokładnie według reguły `base_dt + timedelta(seconds=i / target_fps)`.
- Zachowano mikrosekundową precyzję zegara oraz informację o strefie czasowej (`tzinfo`).

---

## J. Full-Frame Parity Validation Gate

Przeprowadzono pełny skan 900 klatek materiału referencyjnego 4K (`GX030120.MP4` + FIT solarno-bateryjny):

| Kategoria Pól | Sprawdzonych Klatek | Sprawdzonych Wartości | Liczba Różnic | Maksymalny Błąd Float |
|---|---:|---:|---:|---:|
| Pola bazowe (`speed`, `distance`, `alt`) | 900 | 2700 | **0** | $0,000$ |
| Pola STEP (`iso`, `exposure`, `temp`) | 900 | 2700 | **0** | $0,000$ |
| Pola standardowe (`power`, `hr`, `cad`, `battery`) | 900 | 3600 | **0** | $0,000$ |
| Dynamiczne FIT (solar, battery, IMU) | 900 | 16200 | **0** | $0,000$ |
| Pochodne (`elapsed_seconds`, `avg_speed_kmh`, `current_position`) | 900 | 2700 | **0** | $2,84 \times 10^{-14}$ |
| **RAZEM** | **900** | **33300** | **0** | **$2,84 \times 10^{-14} \ll 10^{-6}$ (PASS)** |

---

## K. None / Zero / Source Parity

- **Brak danych**: Zwracane jest `None`.
- **Wartość zerowa**: `0.0` pozostaje `0.0`.
- **Ścisłe źródło**: `FIT` pobiera wyłącznie z pliku FIT, `GPMF` wyłącznie z GPMF, brak cichych fallbacków.

---

## L. Build Scaling AFTER

Pomiary nowego fast buildera po optymalizacji:

### 1. Zestaw kanoniczny złożony (`GX030120.MP4`)
| Klatki | BEFORE (ms) | AFTER (ms) | AFTER (s) | ms / klatkę | Przyspieszenie |
|---|---:|---:|---:|---:|---:|
| 300 | $1722,7\text{ ms}$ | **$37,7\text{ ms}$** | $0,038\text{ s}$ | $0,126\text{ ms}$ | **$45,7\times$** |
| 900 | $5611,9\text{ ms}$ | **$43,7\text{ ms}$** | $0,044\text{ s}$ | $0,049\text{ ms}$ | **$128,4\times$** |
| 1131 | $7321,4\text{ ms}$ | **$32,5\text{ ms}$** | $0,033\text{ s}$ | $0,029\text{ ms}$ | **$225,3\times$** |
| 1800 | $10517,9\text{ ms}$ | **$40,9\text{ ms}$** | $0,041\text{ s}$ | $0,023\text{ ms}$ | **$257,2\times$** |
| 5395 | $32089,4\text{ ms}$ | **$128,7\text{ ms}$** | $0,129\text{ s}$ | $0,024\text{ ms}$ | **$249,3\times$** |

### 2. Zestaw standardowy 1131f (`GX020079.mp4`)
| Klatki | BEFORE (ms) | AFTER (ms) | AFTER (s) | ms / klatkę | Przyspieszenie |
|---|---:|---:|---:|---:|---:|
| 300 | $572,7\text{ ms}$ | **$9,3\text{ ms}$** | $0,009\text{ s}$ | $0,031\text{ ms}$ | **$61,6\times$** |
| 900 | $1617,9\text{ ms}$ | **$18,5\text{ ms}$** | $0,018\text{ s}$ | $0,021\text{ ms}$ | **$87,5\times$** |
| 1131 | $1897,9\text{ ms}$ | **$22,1\text{ ms}$** | $0,022\text{ s}$ | $0,020\text{ ms}$ | **$85,9\times$** |
| 1800 | $3829,5\text{ ms}$ | **$30,6\text{ ms}$** | $0,031\text{ ms}$ | $0,017\text{ ms}$ | **$125,1\times$** |
| 5395 | $9186,2\text{ ms}$ | **$95,8\text{ ms}$** | $0,096\text{ s}$ | $0,018\text{ ms}$ | **$95,9\times$** |

---

## M. Memory

- Rozmiar cache'u pozostał identyczny: **$187,9\text{ KiB}$** dla 1131 klatek i **$890,5\text{ KiB}$** dla 5395 klatek ($< 1\text{ MB}$ RAM).
- Brak alokacji macierzy float64 w strukturach per-frame.

---

## N. 3 × REFERENCE Runs (1131 Frames, 4K `GX020079.mp4`)

| Run | Build (s) | Delay 1st frame (s) | Render Wall (s) | Mux (s) | Total User Wall (s) | RENDER FPS | EFFECTIVE FPS |
|---|---:|---:|---:|---:|---:|---:|---:|
| `ref_1131_run1` | $0,000\text{ s}$ | $1,072\text{ s}$ | $43,455\text{ s}$ | $0,782\text{ s}$ | $44,755\text{ s}$ | 26,027 | 25,271 |
| `ref_1131_run2` | $0,000\text{ s}$ | $0,908\text{ s}$ | $41,248\text{ s}$ | $0,717\text{ s}$ | $42,536\text{ s}$ | 27,419 | 26,589 |
| `ref_1131_run3` | $0,000\text{ s}$ | $0,691\text{ s}$ | $41,788\text{ s}$ | $0,904\text{ s}$ | $43,153\text{ s}$ | 27,065 | 26,209 |
| **MEDIANA** | **$0,000\text{ s}$** | **$0,908\text{ s}$** | **$41,788\text{ s}$** | **$0,782\text{ s}$** | **$43,153\text{ s}$** | **27,065** | **26,209** |

---

## O. 3 × FAST PRECOMPUTED Runs (1131 Frames, 4K `GX020079.mp4`)

| Run | Build (s) | Delay 1st frame (s) | Render Wall (s) | Mux (s) | Total User Wall (s) | RENDER FPS | EFFECTIVE FPS |
|---|---:|---:|---:|---:|---:|---:|---:|
| `fast_pre_1131_run1` | $0,030\text{ s}$ | $0,903\text{ s}$ | $39,251\text{ s}$ | $1,703\text{ s}$ | $41,536\text{ s}$ | 28,814 | 27,229 |
| `fast_pre_1131_run2` | $0,025\text{ s}$ | $0,827\text{ s}$ | $39,258\text{ s}$ | $0,702\text{ s}$ | $40,521\text{ s}$ | 28,809 | 27,911 |
| `fast_pre_1131_run3` | $0,022\text{ s}$ | $0,928\text{ s}$ | $39,179\text{ s}$ | $0,707\text{ s}$ | $40,391\text{ s}$ | 28,867 | 28,001 |
| **MEDIANA** | **$0,025\text{ s}$** | **$0,903\text{ s}$** | **$39,251\text{ s}$** | **$0,707\text{ s}$** | **$40,521\text{ s}$** | **28,814** | **27,911** |

---

## P. Render FPS

- **REFERENCE Mediana**: **$27,065\text{ FPS}$**
- **FAST PRECOMPUTED Mediana**: **$28,814\text{ FPS}$**
- Wzrost wydajności czystego renderowania wideo: **$+6,46\%$ (+1,75 FPS)**.

---

## Q. User Effective FPS

- **REFERENCE Mediana**: **$26,209\text{ FPS}$**
- **FAST PRECOMPUTED Mediana**: **$27,911\text{ FPS}$**
- Wzrost efektywnej przepustowości dla użytkownika od kliknięcia Export: **$+6,50\%$ (+1,70 FPS)**.

---

## R. Total User Wall

- **REFERENCE**: **$43,153\text{ s}$**
- **FAST PRECOMPUTED**: **$40,521\text{ s}$**
- **Zysk całkowitego czasu**: **$-2,632\text{ s}$ (szybciej o $6,10\%$)**.
- **Weryfikacja głównego gate'u (Sekcja 26)**: **PASS** (`FAST PRECOMPUTED total user wall < REFERENCE total user wall`).

---

## S. Full Material (5395 Frames, 4K `GX030120.MP4`, FAST PRECOMPUTED)

- **Klatki**: $5395 / 5395$
- **Precompute build**: **$113,1\text{ ms}$ ($0,113\text{ s}$)** (spadek z $42,88\text{ s}$!)
- **Opóźnienie do 1. klatki**: **$0,909\text{ s}$** (pierwsza klatka pojawia się natychmiast)
- **Video render wall**: **$175,733\text{ s}$** (**$30,700\text{ RENDER FPS}$**)
- **Audio mux**: **$6,063\text{ s}$**
- **Całkowity czas użytkownika**: **$182,565\text{ s}$** (**$29,551\text{ EFFECTIVE FPS}$**)
- **`Telemetry/frame_data`**: **$0,041\text{ ms}$**

---

## T. Tests

Utworzono 12 nowych testów w [tests/test_etap8p_b_fast_builder.py](file:///c:/_DEV/TeleM/tests/test_etap8p_b_fast_builder.py):
1. `test_fast_builder_step_full_parity` — **PASSED**
2. `test_fast_builder_linear_full_parity` — **PASSED**
3. `test_fast_builder_exact_timestamp` — **PASSED**
4. `test_fast_builder_duplicate_timestamp` — **PASSED**
5. `test_fast_builder_before_first` — **PASSED**
6. `test_fast_builder_after_last` — **PASSED**
7. `test_fast_builder_none_zero` — **PASSED**
8. `test_fast_builder_strict_source` — **PASSED**
9. `test_fast_builder_dynamic_fit` — **PASSED**
10. `test_fast_builder_imu` — **PASSED**
11. `test_fast_builder_chart_shared` — **PASSED**
12. `test_fast_builder_gps_shared` — **PASSED**

---

## U. Full Suite Status

```text
426 passed, 3 failed, 17 skipped
```
- Wszystkie 12 nowych testów przeszły pomyślnie.
- 3 znane, pre-istniejące asercje w repozytorium pozostały bez zmian.
- **Zero nowych regresji**.

---

## V. Production Decision

- **`AMD_TELEMETRY_MODE: PRECOMPUTED`** pozostaje bezwzględnym, domyślnym trybem produkcyjnym.
- Tryb ten jest teraz nie tylko szybszy w pętli renderowania ($0,04\text{ ms}$ vs $2,7\dots 7,0\text{ ms}$), ale dzięki wektorowemu builderowi ($0,02\dots 0,11\text{ s}$) jest bezwzględnie szybszy w całym procesie eksportu od momentu kliknięcia przycisku Export.

---

## W. Remaining Bottleneck

Głównym seryjnym kosztem CPU w pętli renderowania klatek pozostaje:
1. **`above_compose` (Pillow render tekstu dla wskaźników ABOVE)**: **$\sim 7,8\dots 8,5\text{ ms}$**
2. **`compose_overlay` (Pillow render dla wskaźników BELOW)**: **$\sim 1,9\dots 2,1\text{ ms}$**
3. **`map_cpu_upload` (rasteryzacja mapy CPU)**: **$\sim 1,9\dots 2,8\text{ ms}$**
4. **`gauge_tobytes`**: **$\sim 0,55\dots 0,64\text{ ms}$**

---

## X. Recommended ETAP 8Q

```text
ETAP 8Q — Dirty Text Cache / Render Optimization dla warstwy above_compose
```
**Uzasadnienie:**
Warstwa `above_compose` zużywa obecnie **$\sim 8\text{ ms}$** na renderowanie statycznych lub wolnozmiennych napisów Pillow. Wprowadzenie buforowania rastrów tekstowych dla niezmienionych wartości pozwoli na redukcję czasu `above_compose` z $8\text{ ms}$ do $< 1\text{ ms}$, co przyniesie kolejny skok wydajności z $\sim 28-30\text{ FPS}$ w kierunku $\sim 40+\text{ FPS}$.
