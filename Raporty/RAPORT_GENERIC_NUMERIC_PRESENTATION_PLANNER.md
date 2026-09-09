# TELEM — Generic Numeric Presentation Planner

Data: 2026-09-09  
Branch: `integration/intel-amd`  
Zakres: pełnoseryjna preanaliza FIT i wspólny kontrakt wartości prezentacyjnej.

## Wynik

`NumericPresentationPlan` został dodany jako wspólny, backend-neutralny plan
serii. Battery plan pozostał kompatybilnym aliasem, ale jego fabryka jest
wybierana przez `FieldSemantics.presentation_strategy`, a nie przez nazwę
wskaźnika. Plan jest budowany raz dla niezmiennej serii, wyszukuje sąsiadów
binarnie i zwraca niezaokrąglony float. Formatter, BAR i GAUGE nie wykonują
drugiej interpolacji.

**STATUS = NOT READY** — kontrakt i testy regresyjne są gotowe, ale pełna
macierz realnego, widocznego GUI dla każdego wymienionego pola (temperature,
speed, power, distance oraz co najmniej jedno integer-sampled continuous poza
Battery) nie została wykonana w tej sesji. Nie oznaczam tego jako PASS na
podstawie samego testu jednostkowego.

## 1. Preanaliza pełnej serii

Źródło: `D:\GoPro\2026-09-02\Poranna_jazda_na_rowerze.fit`, świeży
`parse_fit` + `sync_fit_to_video`, bez odczytu istniejącego cache. Surowe wyniki
zapisano również w:
`D:\TeleM_live_acceptance\presentation_architecture\generic_planner\full_series_inventory.json`.

| pole | próbek | zakres czasu UTC | min–max | unique | semantyka | plan |
|---|---:|---|---:|---:|---|---|
| `garmin_battery_percent` | 27 | 04:22:27–04:55:57 | 94–96 | 3 | continuous, quantized 1.0 | monotonic depletion |
| `garmin_battery_voltage` | 27 | 04:22:27–04:55:57 | 4.184–4.228 | 19 | continuous, quantized .001 | quantized reconstruct |
| `temperature` | 2053 | 04:22:16–04:56:28 | 17–21 | 5 | continuous | linear |
| `garmin_temperature` | 27 | 04:22:27–04:55:57 | 18–21 | 4 | continuous | linear |
| `speed` / `enhanced_speed` | 2022 / 2022 | 04:22:47–04:56:28 | 0–48.2364 | 717 | continuous | linear |
| `curVpower` | 2053 | 04:22:16–04:56:28 | 0–1251 | 345 | continuous | linear |
| `distance` | 2053 | 04:22:16–04:56:28 | 0–13052.25 m | 1906 | continuous | linear, reset-aware |
| `heart_rate` | 2053 | 04:22:16–04:56:28 | 84–134 | 51 | discrete/current STEP contract | raw_step |
| `cadence` | 2018 | 04:22:51–04:56:28 | 0–94 | 56 | discrete/current STEP contract | raw_step |
| `fractional_cadence` | 2018 | 04:22:51–04:56:28 | 0 | 1 | continuous, no observed delta | linear (constant) |
| `gopro_battery` | 2034 | 04:22:35–04:56:28 | 33–53 | 21 | quantized battery strategy | monotonic depletion |
| `alt` / `enhanced_altitude` | 2053 / 2053 | 04:22:16–04:56:28 | 10.8–103.8 | 458 | continuous | linear |
| `track` | 2001 | 04:23:08–04:56:28 | 0–12736.84 m | 1902 | continuous | linear |

`heart_rate` i `cadence` pozostają STEP zgodnie z istniejącą semantyką
projektu; liczba całkowita sama w sobie nie jest podstawą do zmiany kategorii.
`fractional_cadence` jest formalnie continuous, lecz ta konkretna seria ma
stałą wartość 0, więc nie może dostarczyć widocznego dowodu interpolacji.

## 2. Kanoniczny przepływ wartości

```text
raw FIT/GPMF samples
  -> canonical_telemetry_field()
  -> field_semantics() / NumericPresentationPlan
  -> presentation_value()
  -> frame_data / extra_indicators
  -> BAR/GAUGE geometry + text formatter
  -> Preview / Final
```

`presentation_value()` jest jedyną wspólną granicą wartości bieżącej.
`resolve_current_presentation()` rozwiązuje efektywną precyzję i deleguje do
niej. `decimals` oraz legacy `decimal_places` wpływają wyłącznie na format,
z precedencją `decimals` > `decimal_places` > schema/default.

### Registry

`FieldSemantics` zawiera: `semantic_type`, `native_resolution`,
`default_interpolation`, `gap_policy`, `quantized` i
`presentation_strategy`. Dynamiczne klucze `fit_<field>_text` są mapowane
jedną funkcją do pola kanonicznego; nie ma wyjątku dla nazwy Battery.

- continuous precise: speed, altitude, distance, temperature, power, solar →
  linear plan;
- quantized battery: battery percent / GoPro battery → change-event strategy;
- quantized voltage → existing quantized/native policy;
- ISO, SHUT/exposure, GPS fix, HR, cadence, mode/status/ID/counters → STEP;
- Lean pozostaje derived-from-IMU; matematyka nie została zmieniona.

Plan nie przyjmuje `decimals`; ten parametr istnieje tylko na granicy
formatowania. Dla serii continuous precyzja nie może zamrozić floatu na
ostatniej próbce. Dla Battery pełny plan zachowuje wcześniejszy kontrakt:
back-predicted first transition, observed transitions i open tail, z hold
przy realnej luce, cut boundary albo pauzie active-time.

## 3. GUI/schema audit

`src/gui/qt/models.py` udostępnia `decimals` dla text, ruler BAR, segment BAR,
gauge i Lean. Chart zachowuje legacy `decimal_places`; resolver normalizuje je
do jednej wartości efektywnej. Dynamiczne pola FIT są odkrywane z katalogu
FIT i korzystają z tego samego mapowania kanonicznego.

BAR rozdziela: raw value → presentation float → formatted text → normalized
fraction → integer active segments. Segment count nie jest używany jako
display value; marker i gauge otrzymują pełnego floata.

## 4. Dowód Battery z realnego GUI

Istniejący realny harness `QApplication → AppController → MainWindow` dla
`GX010246`/FIT wykazał po integracji planu:

- playback w obrębie pierwszego przejścia 96→95 zwracał zmieniające się floa­ty
  około `95.87 … 95.84` w kolejnych próbkach;
- seek checkpoints zwróciły `95.95, 95.87, 95.72, 95.48, 95.24, 95.10,
  95.00%`;
- w pauzie, bez ruszenia suwaka: 0 DP=`96%`, 1 DP=`95.5%`, 2 DP=`95.48%`,
  3 DP=`95.482%`;
- dowód ekranu: `D:\TeleM_live_acceptance\presentation_architecture\battery_plan_gui\seek_3_hud.png`;
- trace: `...\battery_plan_gui\trace.json`;
- krótki Final worker użył tego samego resolvera/planu; artefakty są w
  `D:\TeleM_live_acceptance\presentation_architecture\final_worker_plan`.

FIT nie zawiera literalnego przejścia 98→97; zawiera 96→95 i 95→94.
Nie zastępowano danych syntetycznymi timestampami.

## 5. Luki, cache i czas odświeżania

Plan przechowuje median cadence i respektuje `segment_start_indices`, próg
dużej luki oraz `ActiveTimeMapper`. Lookup jest `O(log N)` bez pełnej tablicy
interpolowanej i bez modyfikacji raw samples. Manager i worker rozgrzewają
plan po inicjalizacji serii; dynamiczny frame/precompute path korzysta ze
wspólnego resolvera. Cache jest kluczowany tożsamością/końcami serii i zakresem
coverage, więc różne wnętrza serii nie kolidują.

Poprzedni pomiar resolvera (10k warm lookups) pozostaje: STEP median 7.7 µs,
p95 8.8 µs; linear median 9.5 µs, p95 9.9 µs. Po dodaniu generycznego
wrappera nie wykonano nowego benchmarku produkcyjnego; **NOT TESTED**.

## 6. Zmiany

- `src/telemetry_resolver.py` — registry, `NumericPresentationPlan`,
  `presentation_value`, wspólny resolver, gap/active-time guards;
- `src/gui/telemetry_manager.py` — warm-up planu po load FIT;
- `src/ffmpeg/worker_cache.py` — warm-up planu z video coverage;
- `tests/test_presentation_architecture.py` — plan generic, precision
  independence, gap/cut i discrete protections;
- ten raport.

Nie zmieniano parsera FIT/GPMF, raw danych, Lean mathematics, audio,
AMD/Intel/NVIDIA backendów ani Hybrid scheduler.

## 7. Testy

PASS: `python -m pytest -q tests/test_presentation_architecture.py tests/test_display_precision_interpolation.py` → **43 passed**.  
PASS: `python -m compileall -q src/telemetry_resolver.py`.  
PASS: raw full-series FIT pre-analysis and JSON artifact on D:.  
PASS: existing Battery real GUI playback/seek/property evidence and short
Final parity evidence.

NOT RUN / BLOCKED: legacy FIT GUI suites requiring deleted repository fixture
files (`Video/GX010115.json`, `Video/Jazda_na_rowerze_w_porze_lunchu.fit`),
which are unrelated to this patch.

## 8. Gate summary

| gate | wynik |
|---|---|
| one generic planner / canonical mapping | PASS |
| decimals single-source and format-only | PASS |
| Battery real GUI intermediate values | PASS (96→95 equivalent data) |
| BAR/GAUGE full float | PASS |
| discrete STEP protection | PASS |
| gap / cuts / active-time safety | PASS (unit/integration) |
| Preview/Final shared pre-backend value | PASS (Battery short proof) |
| full visible GUI matrix for temp/speed/power/distance/other continuous | NOT TESTED |
| new post-wrapper performance benchmark | NOT TESTED |
| raw FIT/GPMF and backend regression | NOT RUN in this task |

**FINAL STATUS: NOT READY** until the remaining real-GUI field matrix and
post-wrapper performance/backend regression evidence are collected. No long
render, commit, push, reset, clean or rebase was performed.
