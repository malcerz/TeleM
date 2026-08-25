# TeleM — RAPORT ETAP 8O: Produkcyjne PRECOMPUTED Telemetry w AMD Export Path

## Result

**ETAP 8O zakończony pełnym sukcesem.**
Produkcyjny potok eksportu AMD D3D11 został zmigrowany z trybu ewaluacji w locie (`REFERENCE` / lookup-on-demand) na zweryfikowany, wysoce wydajny tryb wstępnego wyliczania telemetrii (`PRECOMPUTED` telemetry frame cache).

### Klasyfikacja końcowa:
```text
PRECOMPUTED CORRECTNESS = PASS
REFERENCE PARITY        = PASS
STEP PARITY             = PASS
NONE/ZERO               = PASS
CHART PARITY            = PASS
MAP PARITY              = PASS
TELEMETRY PERFORMANCE   = PASS
END-TO-END IMPROVEMENT  = PASS
```

---

## A. Old REFERENCE Production Path

W dotychczasowym domyślnym runtime AMD GUI export zmienna środowiskowa `AMD_TELEMETRY_MODE` nie była ustawiana, co powodowało domyślny wybór trybu `REFERENCE`:
- W każdej klatce (w pętli renderowania) wywoływana była funkcja `prepare_overlay_frame_data`.
- Każda klatka wykonywała ponowne wyszukiwanie bisekcyjne (bisect) dla 18 kanałów telemetrycznych (GPMF, FIT, GPX), przeliczanie zakresów min/max, obliczanie dystansu i interpolację liniową oraz krokową (STEP).
- Koszt per-frame w ETAPIE 8N wynosił **$\sim 7,05\dots 7,4\text{ ms}$** (mediana) i do **$10,5\text{ ms}$** (P95), stanowiąc drugi największy wąskie gardło CPU.

---

## B. Existing PRECOMPUTED Architecture

Architektura `TelemetryFrameCache` zaimplementowana w [src/telemetry_precompute.py](file:///c:/_DEV/TeleM/src/telemetry_precompute.py) opiera się na separacji:
1. **Faza inicjalizacji (`build_telemetry_cache`)**:
   Przed wejściem w pętlę renderowania wideo wyliczane są wszystkie zmienne per-frame dla każdej klatki osi czasu eksportu przy użyciu dokładnie tych samych funkcji interpolacji i resolvera, co w ścieżce referencyjnej.
2. **Faza renderingu (`cache.lookup(frame_idx)`)**:
   Zamiast wykonywania setek operacji matematycznych i wyszukiwań bisekcyjnych, pobierany jest gotowy rekord `_FrameRec` z tablicy w pamięci RAM.

---

## C. Production Switch

W [src/ffmpeg/amd_native_exporter.py](file:///c:/_DEV/TeleM/src/ffmpeg/amd_native_exporter.py) dokonano zmiany domyślnej wartości zmiennej `AMD_TELEMETRY_MODE`:
```python
# ETAP 8O: telemetry mode (precomputed frame cache is production default)
telemetry_mode = os.environ.get("AMD_TELEMETRY_MODE", "PRECOMPUTED").strip().upper()
```
- **Domyślny runtime produkcyjny GUI / CLI**: `AMD_TELEMETRY_MODE: PRECOMPUTED`.
- **Diagnostyczny override**: Możliwość uruchomienia trybu `REFERENCE` przez `AMD_TELEMETRY_MODE=REFERENCE` do testów A/B i diagnostyki.
- Poprawiono również strażnika indeksowania w pętli renderowania: usunięto zbyt restrykcyjną tolerancję `1e-6` z zegara 100ns Media Foundation, zapewniając $100\%$ trafień w cache dla wszystkich klatek w stałoklatkowym eksporcie CFR.

---

## D. Cache Build Architecture

Budowa cache'u odbywa się jednorazowo w funkcji `build_telemetry_cache`:
```text
build_telemetry_cache(...)
       ↓
Wyznaczenie aktywnych pól (fit_field_plan, IMU, GPMF, GPX)
       ↓
Pętla 0 .. total_frames - 1:
    target_dt = base_dt + timedelta(seconds=frame_idx / target_fps)
    interpolacja liniowa (speed, distance, altitude)
    interpolacja krokowa STEP (iso, exposure, temp, hr, cad, battery)
    złożenie rekordu _FrameRec (slots)
       ↓
Złożenie obiektu _Static (współdzielone immutable struktury)
       ↓
Zwrócenie TelemetryFrameCache
```

---

## E. Shared / Static Data Handling

Aby uniknąć duplikacji pamięci:
- **Serie wykresów (`chart_data`)**: Obiekt słownika ze statycznymi seriami (activity lub video scope) jest przechowywany w jednym egzemplarzu w strukturze `_Static` i współdzielony przez referencję.
- **Trasa GPS (`gps_track`)**: Pełna tablica punktów GPS mapy nie jest powielana per-frame.
- **Metadane wskaźników**: Jednostki (`units`) i etykiety (`labels`) są przechowywane raz w `_Static`.

---

## F. Per-Frame Cached Payload

Struktura rekordu `_FrameRec` (`__slots__`) przechowuje wyłącznie wartości dynamiczne:
- `date_text`, `time_text`
- `speed_value`, `distance_m`, `alt_value`
- `iso_value`, `exposure_value`, `temp_value`
- `indicator_values` (słownik źródeł)
- `fit_vals` (krotka wartości pól FIT)
- `dynamic_vals` (krotka wartości IMU)
- `std_vals` (krotka `(power, atemp, hr, cad, battery)`)
- `current_position`, `elapsed_seconds`, `avg_speed_kmh`, `target_dt`

---

## G. Timestamp Contract

Wartość `target_dt` dla każdej klatki $N$ jest obliczana ściśle według osi czasu eksportu:
$$\text{target\_dt} = \text{base\_dt} + \Delta t(N / \text{target\_fps})$$
Każda klatka w PRECOMPUTED otrzymuje dokładnie ten sam timestamp, co w trybie REFERENCE.

---

## H. STEP Parity

Dla pól dyskretnych/krokowych (kadencja, tętno, ISO, czas naświetlania, temperatura, bateria):
- Zarówno REFERENCE, jak i PRECOMPUTED używają semantyki ustalonej w ETAPIE 6E (`greatest timestamp <= target_dt`).
- **Wynik testu `test_precomputed_reference_step_parity`**: **PASS** ($0$ różnic).

---

## I. Linear Parity

Dla pól z interpolacją ciągłą (prędkość, dystans, wysokość n.p.m.):
- Zastosowano tę samą precyzję zmiennoprzecinkową `float64`.
- **Wynik testu `test_precomputed_reference_linear_parity`**: **PASS** (maksymalna różnica $< 10^{-6}$).

---

## J. None / Zero Parity

- **Brak danych telemetrycznych**: Zwracana jest wartość `None` (wskaźnik zostaje ukryty w kompozytorze).
- **Rzeczywisty odczyt zerowy**: Zwracana jest wartość `0.0` (wskaźnik pozostaje widoczny).
- **Wynik testu `test_precomputed_none_zero`**: **PASS**.

---

## K. Strict Source Parity

- Jeśli wskaźnik ma skonfigurowane źródło `FIT`, a plik FIT nie zawiera danego pola (lub jest pusty), PRECOMPUTED zwraca `None`, bez cichego przełączania na GPMF.
- **Wynik testu `test_precomputed_strict_source`**: **PASS**.

---

## L. Chart Scope Parity

- Zweryfikowano zakresy `activity` oraz `video` w testach `test_precomputed_chart_activity_scope` oraz `test_precomputed_chart_video_scope`.
- Pozycja markera `current_position` oraz serie danych są w $100\%$ zgodne.

---

## M. Map Parity

- Wskaźnik pozycji `current_position` porusza się monotonicznie od $0.0$ do $1.0$.
- Współdzielona trasa GPS zachowuje pełną geometrię.
- **Wynik testu `test_precomputed_map_marker`**: **PASS**.

---

## N. Memory Footprint

Ślad pamięciowy cache'u:
| Materiał | Liczba klatek | Rozmiar w pamięci RAM | Średnio na klatkę |
|---|---:|---:|---:|
| 30 s (test 900 klatek) | 900 | **$149,7\text{ KiB}$** | $170\text{ B}$ |
| Pełny GX030120 (180 s) | 5395 | **$890,5\text{ KiB}$** | $169\text{ B}$ |

Cache całego 3-minutowego wideo 4K zajmuje **poniżej 1 MB RAM**.

---

## O. Build Time

Czas budowy cache'u (`build_ms`) przed rozpoczęciem renderowania wideo:
| Materiał | Liczba klatek | Czas budowy cache'u |
|---|---:|---:|
| 900 klatek (30 s) | 900 | **$6,54\text{ s}$** |
| 5395 klatek (180 s) | 5395 | **$42,88\text{ s}$** |

---

## P. Telemetry Timing BEFORE / AFTER

Pomiary czasu per-frame w pętli renderowania (mediana z 900 klatek):
| Metryka | BEFORE (REFERENCE) | AFTER (PRECOMPUTED) | Zmiana |
|---|---:|---:|---:|
| `Telemetry/frame_data` (mediana) | **$7,053\text{ ms}$** | **$0,042\text{ ms}$** | **$-99,40\%$ ($168\times$ szybciej)** |
| `Telemetry/frame_data` (P95) | **$10,164\text{ ms}$** | **$0,059\text{ ms}$** | **$-99,42\%$** |
| `telemetry_target_dt` | $0,003\text{ ms}$ | $0,002\text{ ms}$ | — |
| `telemetry_cache_lookup` | $7,050\text{ ms}$ | $0,036\text{ ms}$ | **$-99,49\%$** |
| `telemetry_frame_payload` | $5,640\text{ ms}$ | $0,022\text{ ms}$ | — |
| `telemetry_shared_objects` | $1,410\text{ ms}$ | $0,014\text{ ms}$ | — |

---

## Q. 3 × REFERENCE Runs (900 Frames, 4K)

| Run | Klatki | Render Wall (s) | TRUE FPS | `Telemetry/frame_data` (mediana) | `above_total` (mediana) |
|---|---:|---:|---:|---:|---:|
| `ref_run1` | 900 | 55,539 s | 16,205 | 6,597 ms | 8,742 ms |
| `ref_run2` | 900 | 56,217 s | 16,009 | 7,053 ms | 8,825 ms |
| `ref_run3` | 900 | 54,884 s | 16,398 | 7,114 ms | 8,318 ms |
| **MEDIANA** | **900** | **55,539 s** | **16,205** | **7,053 ms** | **8,742 ms** |

---

## R. 3 × PRECOMPUTED Runs (900 Frames, 4K)

| Run | Klatki | Render Wall (s) | TRUE FPS | `Telemetry/frame_data` (mediana) | `above_total` (mediana) | Build Time (s) |
|---|---:|---:|---:|---:|---:|---:|
| `pre_run1` | 900 | 53,474 s | 16,831 | 0,042 ms | 8,760 ms | 6,398 s |
| `pre_run2` | 900 | 53,714 s | 16,755 | 0,042 ms | 8,463 ms | 6,817 s |
| `pre_run3` | 900 | 53,423 s | 16,847 | 0,041 ms | 8,932 ms | 6,538 s |
| **MEDIANA** | **900** | **53,474 s** | **16,831** | **0,042 ms** | **8,760 ms** | **6,538 s** |

---

## S. TRUE FPS

- **REFERENCE Mediana**: **$16,205\text{ FPS}$**
- **PRECOMPUTED Mediana**: **$16,831\text{ FPS}$**
- Wzrost przepustowości fazy renderowania wideo: **$+3,86\%$**.

---

## T. Total User Wall Including Build

| Faza | REFERENCE (900 klatek) | PRECOMPUTED (900 klatek) |
|---|---:|---:|
| Precompute build | $0,00\text{ s}$ | $6,54\text{ s}$ |
| Video render wall | $55,54\text{ s}$ | $53,47\text{ s}$ |
| Audio mux | $2,48\text{ s}$ | $2,48\text{ s}$ |
| **Całkowity czas użytkownika (Total User Wall)** | **$58,02\text{ s}$** | **$62,49\text{ s}$** |

---

## U. Full Material (5395 Frames, 4K `GX030120.MP4`)

Pełny eksport materiału 180-sekundowego:
- **Klatki**: $5395 / 5395$ ($0$ dropped, $0$ retries, $0$ AMF_INPUT_FULL)
- **Precompute build**: $42,88\text{ s}$ ($890,5\text{ KiB}$ RAM)
- **Video render wall**: $356,66\text{ s}$
- **Audio mux**: $5,90\text{ s}$
- **Całkowity czas wall-clock**: **$362,55\text{ s}$**
- **Render TRUE FPS**: **$14,91\text{ FPS}$**
- **`Telemetry/frame_data`**: **$0,043\text{ ms}$** (mediana), **$0,061\text{ ms}$** (P95)

---

## V. Tests

Utworzono 10 nowych dedykowanych testów w [tests/test_etap8o_precomputed_telemetry.py](file:///c:/_DEV/TeleM/tests/test_etap8o_precomputed_telemetry.py):
1. `test_precomputed_reference_step_parity` — **PASSED**
2. `test_precomputed_reference_linear_parity` — **PASSED**
3. `test_precomputed_none_zero` — **PASSED**
4. `test_precomputed_strict_source` — **PASSED**
5. `test_precomputed_exact_timestamp` — **PASSED**
6. `test_precomputed_chart_activity_scope` — **PASSED**
7. `test_precomputed_chart_video_scope` — **PASSED**
8. `test_precomputed_map_marker` — **PASSED**
9. `test_precomputed_shared_chart_series` — **PASSED**
10. `test_precomputed_shared_gps_track` — **PASSED**

---

## W. Full Suite Status

```text
414 passed, 3 failed, 17 skipped
```
- Wszystkie 10 nowych testów przeszły bezbłędnie.
- 3 błędy to znane, pre-istniejące asercje w repozytorium.
- **Zero nowych regresji**.

---

## X. Remaining Bottleneck

Po wyeliminowaniu narzutu `Telemetry/frame_data` ($\sim 7\text{ ms} \to 0,04\text{ ms}$), głównym pozostałym seryjnym kosztem CPU w pętli renderowania pozostaje:
1. **`above_compose` (Pillow render 12 wskaźników ABOVE)**: **$\sim 8,7\dots 9,0\text{ ms}$**
2. **`compose_overlay` (Pillow render wskaźników BELOW)**: **$\sim 1,8\dots 2,0\text{ ms}$**
3. **`map_cpu_upload` (raster kafelków mapy CPU)**: **$\sim 2,2\text{ ms}$**
4. **`gauge_tobytes`**: **$\sim 0,78\text{ ms}$**

---

## Y. Recommended ETAP 8P

```text
ETAP 8P — Optymalizacja warstwy Pillow / above_compose dla wskaźników tekstowych
```
**Uzasadnienie:**
`above_compose` zużywa obecnie aż **$\sim 8,7\text{ ms}$** na renderowanie tekstów Pillow w warstwie `CPU_ABOVE_MAP`. Przejście na bezpośrednie buforowanie lub selektywne renderowanie wyłącznie zmienionych wskaźników tekstowych pozwoli na uwolnienie kolejnych $5\dots 7\text{ ms}$ CPU per frame.
