# TeleM — ETAP 4C: audyt i naprawa timingu TMPC / Camera Temperature

Materiał: `Video/GX030120.MP4`  
Cache: `Video/GX030120.json` / `Video/GX030120.json.meta.json`  
Zakres: wyłącznie TMPC/Camera Temperature. ACCL/GYRO analizowano tylko jako źródła TMPC; nie dodano ich jako pól telemetrycznych, indicatorów ani resolver sources.

## ETAP 4C — RESULT

**ZAKOŃCZONY.** W każdym z 180 bloków TMPC występuje przy ACCL i GYRO, ale jest to jeden logiczny pomiar wspólnego sensora. Pipeline zachowuje 180 próbek z timingiem ACCL `STMP/TSMP`, a provenance obu wpisów pozostaje w cache.

## A. Raw architecture and duplicate analysis

MP4 ma 5395 klatek, GPMF ma 180 pakietów/DEVC.

| Source | STNM | FourCC | TYPE | SCAL | Parent units | Entries |
|---|---|---|---|---:|---|---:|
| ACCL | Accelerometer | `TMPC` | `f` | 417 | `m/s` | 180 |
| GYRO | Gyroscope | `TMPC` | `f` | 939 | `rad/s` | 180 |

`TMPC` ma repeat 1. `SCAL`/jednostki należą do nadrzędnych streamów, nie są jednostką temperatury. Przykład bloku 0: ACCL `30.376953125`, `STMP=1006092290`, `TSMP=200101`; GYRO `30.376953125`, `STMP=1006094068`, `TSMP=200102`.

```text
ACCL entries              = 180
GYRO entries              = 180
raw TMPC total            = 360
unique raw STMP           = 360
unique raw temperature    = 103
logical timestamps        = 180
```

W 178/180 bloków wartości są identyczne. W dwóch różnica wynosi tylko 0.01953125 °C. `TSMP` obu streamów jest sąsiedni (różnica 0 lub 1), a `STMP` należy do tego samego pakietu.

| Statistic | Value delta | STMP delta |
|---|---:|---:|
| Min | 0.0 °C | 1774 µs |
| Median | 0.0 °C | 1778 µs |
| P90 | — | 3256 µs |
| Max | 0.01953125 °C | 3260 µs |

Klasyfikacja: **SAME SENSOR SAMPLE COPIED TO TWO STREAMS**. Nie jest to exact duplicate bitowy w każdym bloku, lecz jeden fizyczny pomiar zapisany przy dwóch streamach, nie dwa niezależne sensory. Kanoniczne źródło logiczne: ACCL.

## B. Root cause

Stara `to_exiftool_json()` nadpisywała jedno `DocN:CameraTemperature` przy przejściu przez oba TMPC i nie zachowywała stream-specific `STMP/TSMP`. `extract_temperature_samples()` używał potem `DocN:GPSDateTime`, więc timing był dokumentowy/GPS. Wartość była dodatkowo zaokrąglana do `int` przed resolverem (`30.376953125 → 30`).

## C. Implementation

- `src/telemetry_gpmf_new.py`, `to_exiftool_json()` rozpoznaje `STNM`, zapisuje `TMPC_ACCL_*` i `TMPC_GYRO_*` (`Value`, `STMP`, `TSMP`) oraz wybiera ACCL jako `CameraTemperature` z `TMPC_STMP`, `TMPC_TSMP`, `TMPC_SourceStream`.
- `src/telemetry_extract.py` wyznacza czas TMPC z ACCL `STMP/TSMP` + absolutny GPS anchor, wybiera jedną próbkę na blok, zachowuje float przed resolverem i pozostawia fallback dla starych rekordów.
- `src/gui/qt/_mixins/project_mixin.py`: cache version `3 → 4`; zachowano fingerprint, generator i atomic write.
- `tests/test_gpmf_timing.py`: regresje rozpoznania ACCL/GYRO, canonical sample, równych temperatur i monotonicznego timingu.

Nie dodano żadnych pól telemetrycznych ACCL/GYRO ani obsługi GUI.

## D. New timing model

```text
ACCL TMPC STMP/TSMP per DEVC
→ relative GPMF time from first ACCL TMPC STMP
→ absolute UTC using first valid GPSDateTime only as anchor
→ one logical CameraTemperature sample per block
→ previous-value hold at target_dt
```

MP4 PTS: `0.000`, `1.001`, …, `179.179` s. ACCL TMPC `STMP` span: 179.178197 s.

## E. Counts and timing statistics

| Metric | Result |
|---|---:|
| Raw ACCL / GYRO / total | 180 / 180 / 360 |
| Logical / cache / pipeline | 180 / 180 / 180 |
| First | 2026-08-18 04:46:25.700000 UTC |
| Last | 2026-08-18 04:49:24.878197 UTC |
| Min / median / P90 / max delta | 996.462 / 1001.503 / 1001.505 / 1001.507 ms |
| Effective rate | 0.999005 Hz |
| Duplicates / backward jumps | 0 / 0 |

## F. Reference point: 04:46:40 UTC

Lookup pozostaje `previous-value hold`.

| Sample | Source | Raw °C | STMP | Derived UTC | Delta |
|---|---|---:|---:|---|---:|
| Previous | ACCL | 30.453125 | 1019106688 | 04:46:38.714398 | -1285.602 ms |
| Selected | ACCL | 30.419921875 | 1020108184 | 04:46:39.715894 | -284.106 ms |
| Next | ACCL | 30.501953125 | 1021109678 | 04:46:40.717388 | +717.388 ms |

Po zmianie selected raw value to `30.419921875 °C`, a nie `30`. Domyślne formatowanie tekstowe z jedną cyfrą po przecinku daje około `30.4 °C`.

## G. Multi-point validation

| video_s | Selected UTC | Delta ms | Raw °C |
|---:|---|---:|---:|
| 0 | 04:46:25.700000 | 0.000 | 30.376953125 |
| 10 | 04:46:34.708419 | -991.581 | 30.46484375 |
| 30 | 04:46:54.728258 | -971.742 | 30.537109375 |
| 60 | 04:47:24.758095 | -941.905 | 30.671875 |
| 90 | 04:47:54.788077 | -911.923 | 30.8359375 |
| 120 | 04:48:24.818123 | -881.877 | 30.88671875 |
| 150 | 04:48:54.848165 | -851.835 | 30.84375 |
| 175 | 04:49:19.875709 | -824.291 | 30.81640625 |
| 179.9 | 04:49:24.878197 | -721.803 | 30.82421875 |

## H. Cache parity and ISO/SHUT regression

Fresh parse i cache reload są identyczne: `TMPC=180`, timestamps/values `parity=True`, provenance ACCL/GYRO obecne. ISO i SHUT po zmianie nadal mają `raw/cache/pipeline = 5400/5400/5400`, duplicates 0, backward jumps 0.

## I. Tests

- Testy zakresowe GPMF timing/cache/telemetry manager: **38 passed**.
- Pełna suite: **301 passed, 4 failed, 17 skipped**.
- Te same, wcześniejsze failure'y: `test_amd_native_etap4.py`, `test_amd_native_etap5b.py`, `test_qp_analyzer.py`, `test_render_tab.py`.

## J. Difference vs Telemetry Overlay

```text
TIMING:  raw ACCL sample 04:46:39.715894, previous hold.
LOOKUP:  previous-value hold, bez interpolacji.
RAW:     30.419921875 °C.
ROUNDING: float zachowany przed resolverem; display 1dp ≈ 30.4 °C.
UNKNOWN: Overlay ~30.5 °C może używać innego punktu/próbki lub prezentacji.
```

## K. Remaining issues

### CONFIRMED

Jeden fizyczny pomiar jest kopiowany do ACCL/GYRO; logiczna liczba próbek to 180; timing pochodzi z ACCL `STMP/TSMP`; cache parity jest pełna; równe temperatury nie są usuwane.

### SUSPECTED

Różnica względem Overlay wymaga osobnego audytu tylko wtedy, gdy 30.4 vs 30.5 pozostanie istotne.

### OUT OF SCOPE

Dodawanie ACCL/GYRO do modelu, GUI, indicatorów i resolver sources; GPS9, ISOE, SHUT, SmartSync, FIT, track/map, HR, cadence, speed, renderer PTS/VFR, GPU.

## BEFORE / AFTER

| Property | BEFORE | AFTER |
|---|---|---|
| Raw TMPC | 360 | 360 |
| Logical samples | około 180, legacy timing | 180, raw timing |
| Timestamp source | `GPSDateTime` dokumentu | ACCL `STMP/TSMP` + anchor |
| Duplicate handling | spłaszczone/niedeterministyczne | ACCL canonical per block |
| Sample rate | około 1 Hz z GPSDateTime | 0.999005 Hz raw-derived |
| Reference value | 30 po konwersji do int | 30.419921875 raw / około 30.4 display |
