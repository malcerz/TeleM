# RAPORT — SPEED START ZERO FIX

## 1. TASK
Naprawić start wskaźnika prędkości (gauge & text) od pierwszej klatki projektu:
- Przed pojawieniem się pierwszej próbki FIT speed: wskaźnik pokazuje `0.0 km/h`, wskazówka dokładnie na `0` (brak `--`, brak braku wskazówki).
- Z chwilą pojawienia się pierwszej realnej próbki: wskaźnik i wskazówka płynnie ruszają w tej klatce.
- Brak globalnego maskowania `missing -> 0` dla pozostałych pól telemetrii (HR, Cadence, Temp, Alt, Power, Battery, ISO, Exposure zachowują swoje semantyki).
- Brak fałszowania zerem gdy całe źródło FIT zaczyna się później niż wideo (zachowano `None` przed startem źródła).
- Brak fałszowania mid-stream dropoutów w środku trasy (zachowano reguły hold/gap resolvera).

---

## 2. METRYKI RAPORTOWE

```text
FIRST_VALID_SPEED_TIME=06:30:25 (04:30:25 UTC)
RAW_SPEED_BEFORE_FIRST=None
RESOLVED_SPEED_BEFORE_FIRST=0.0 km/h
GAUGE_FRAME0=0.0 km/h (needle at 0.0 position, text 0.0, no '--')
GAUGE_FIRST_VALID_FRAME=4.7 km/h (frame 78, t=2.610s, needle moves dynamically)
TRACEBACK_COUNT=0
MODIFIED_FILES=src/telemetry_resolver.py, telemetry_fit.py, src/gui/telemetry_manager.py
CASE=CASE A — SPEED STARTS AT ZERO CORRECTLY
```

---

## 3. PROVENANCE & DIAGNOZA (GX010298.fit)

W pliku `Video/GX010298.fit`:
- Rekordy FIT zaczynają się o `06:30:21` (`04:30:21 UTC`).
- W rekordach 0, 1, 2, 3 (`06:30:21` - `06:30:24`):
  - `distance = 0.0 m` (rower stoi w miejscu).
  - `enhanced_altitude = 73.8 m`, `heart_rate = 90..91 BPM`.
  - `speed` oraz `enhanced_speed` mają wartość `None` (brak próbki w formacie Garmin).
- Pierwsza niezerowa próbka prędkości pojawia się w rekordzie 4 o `06:30:25` (`04:30:25 UTC`) z wartością `4.7376 km/h` (1.316 m/s) i `distance = 1.32 m`.
- Wideo `GX010298.MP4` zaczyna się o `06:30:22.390` (`04:30:22.390 UTC`).
- Przed naprawą:
  - W `telemetry_resolver.py` dla `target_dt < speed_samples[0][0]` binary search zwracał `idx == 0 -> None`.
  - Gauge renderował `value=None` -> brak wskazówki (`draw_needle=False`), tekst `-- KM/H`.
  - O `06:30:25` wartość nagle przeskakiwała na `4.7 km/h`.

---

## 4. IMPLEMENTACJA

1. **`src/telemetry_resolver.py`**:
   - `NumericPresentationPlan`: dodano pole `field` i `source_start`. W `value_at()` dla `idx == 0`: jeśli `field in ('speed', 'enhanced_speed', 'ground_speed')`, zwraca `0.0` (chyba że `source_start` jest znane i `target < source_start`, wówczas `None`).
   - `interpolate_presentation_value()`: dla `idx == 0` i `field_name in ('speed', 'enhanced_speed', 'ground_speed')`, zwraca `0.0` (lub `None` przed `source_start`).
   - Zachowano pełną izolację: pozostałe pola (HR, Cadence, Alt, Temp, Power) nadal zwracają `None` przed pierwszą próbką.
   - Mid-stream dropouty (`idx > 0`) zachowują dotychczasową politykę gap/hold (nie są zamieniane na 0.0).

2. **`telemetry_fit.py`**:
   - Zdefiniowano `FitSampleList(list)` z metadanymi `source_start = records[0]['timestamp']`.
   - `sync_fit_to_video()` i `FitDataset` przekazują `source_start` do strumieni próbek, co pozwala resolverowi precyzyjnie odróżnić "opóźniony start całego pliku FIT" od "brakującej próbki speed przed ruszeniem".

3. **`src/gui/telemetry_manager.py`**:
   - `load_fit()` przekazuje `source_start` do `FitDataset` oraz priorytetyzuje `source_start` przy ustalaniu `start_dt_utc`.

---

## 5. TESTY I WERYFIKACJA

1. **Testy jednostkowe (`tests/test_speed_start_zero.py`)**:
   - `test_synthetic_speed_pre_first_zero`: `t=0s, 1s, 3.9s -> 0.0`, `t=4s -> 5.0`, `t=5s -> 6.0` (PASS).
   - `test_speed_source_delayed_start_preserves_none`: przed startem FIT (`t<3s`) zwraca `None`, po starcie FIT a przed speed (`3s<=t<4s`) zwraca `0.0`, od `t=4s` zwraca `5.0` (PASS).
   - `test_other_fields_not_altered_to_zero`: HR, Cadence, Alt, Temp zwracają `None` przed pierwszą próbką (PASS).
   - `test_mid_stream_dropout_preserves_policy`: 30-sekundowa luka w środku przejazdu zachowuje hold (`22.0 km/h`), nie zeruje się (PASS).
   - `test_real_gx010298_speed_start_zero_and_gauge`: klatka 0 to `0.0 km/h`, wskazówka na `0`, płynny start od `06:30:25` (PASS).

2. **GUI Smoke Simulation (`scratch/speed_start_zero/gui_test.log`)**:
   - Frame 0 (t=0.000s, 06:30:22.390): Speed=0.0, Gauge text="0.0 km/h", needle_bbox=(26.0, 109.5, 114.0, 130.5).
   - Frame 30 (t=1.000s, 06:30:23.390): Speed=0.0, Gauge text="0.0 km/h", needle_bbox na 0.
   - Frame 60 (t=2.000s, 06:30:24.390): Speed=0.0, Gauge text="0.0 km/h", needle_bbox na 0.
   - Frame 78 (t=2.610s, 06:30:25.000): Speed=4.738 km/h, Gauge text="4.7 km/h", needle rusza dynamicznie.
   - Frame 90 (t=3.000s, 06:30:25.390): Speed=5.170 km/h, Gauge text="5.2 km/h", needle rusza dynamicznie.

---

## 6. ARTEFAKTY ZADANIA
- `scratch\speed_start_zero\raw_speed_proof.md`
- `scratch\speed_start_zero\resolver_trace.md`
- `scratch\speed_start_zero\tests.txt`
- `scratch\speed_start_zero\gui_test.log`
- `scratch\speed_start_zero\artifacts_manifest.txt`
- `scratch\speed_start_zero\ntfy_result.txt`

---

## 7. PODSUMOWANIE I STATUS
- **Status**: COMPLETE / PASS
- **Case**: CASE A — SPEED STARTS AT ZERO CORRECTLY
