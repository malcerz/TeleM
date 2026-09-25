# RAPORT: KRYTYCZNA NAPRAWA NORMALIZACJI DATETIME I FALLBACKU W PREVIEW TELEMETRII

Data: 2026-09-16  
Gałąź: `amd-bikeridehud`  
Status: **CASE A — PREVIEW TELEMETRY FULLY FIXED**

---

## 1. Podsumowanie zadania

Rozwiązano dwa powiązane błędy krytyczne uniemożliwiające działanie podglądu (preview) przy wczytaniu projektu `Video/GX010298.MP4` + `GX010298.fit` + `Video/GX010298.layout.json`:

1. **Błąd źródłowy (Root Error):** `TypeError: '<' not supported between instances of 'datetime.datetime' and 'str'` w `src/telemetry_resolver.py` wynikający z braku normalizacji granic czasu (`coverage_start`, `coverage_end`, sample timestamps) z formatu ISO string do obiektów `datetime.datetime`.
2. **Błąd maskujący (Masking Fallback):** W `src/indicators/frame_data.py` blok `try: ... except TypeError:` w `direct_resolve()` i `profiled_resolve()` przechwytywał wewnętrzny `TypeError` z resolvera i błędnie uruchamiał fallback ze starą 2-argumentową sygnaturą, generując wtórny `TypeError: resolve_cache_value() missing 1 required positional argument: 'dt'`.

---

## 2. Diagnoza Provenance i Root Cause

- **Provenance `coverage_start` / `coverage_end`:** Granice czasowe oraz znaczniki próbek są serializowane w pamięci podręcznej telemetrycznej (pliki `.telemetry.npz`, `.json.gz`, metadata) w formacie napisowym ISO-8601 (np. `"2026-09-16T04:30:22.000000Z"`). Po deserializacji w `TelemetryDataManager` / `telemetry_resolver`, `NumericPresentationPlan` oraz `BatteryPlanSegment` otrzymywały wartości typu `str`. Funkcja pomocnicza `_naive_dt()` zwracała stringi bez parsowania. Gdy `_resolve_preview_time()` wyliczał `target_dt` jako obiekt `datetime`, operacja `target < self.coverage_start` powodowała natychmiastowy `TypeError`.
- **Masking Fallback:** Funkcja `prepare_overlay_frame_data()` używała niebezpiecznego wzorca `except TypeError` do wsparcia przestarzałych callbacków. Każdy błąd typu ze środka resolvera był maskowany przez błąd argumentów fallbacku.

---

## 3. Zastosowane rozwiązania architektoniczne

1. **Jednoznaczna normalizacja kanoniczna (`_normalize_datetime`):**
   - Wprowadzono w `src/telemetry_resolver.py` kanoniczną funkcję `_normalize_datetime(value: Any) -> datetime | None`.
   - Obsługuje: `datetime` (naive lub aware -> UTC naive), ISO stringi (z strefą czasową lub bez), numeryczne znaczniki czasu (timestamp float/int) oraz `None`.
   - Odrzuca niepoprawne typy i uszkodzone stringi jawnym błędem.
   - Wprowadzono `__post_init__` w `NumericPresentationPlan` i `BatteryPlanSegment` wymuszające typ `datetime` na granicach.
   - Zaktualizowano `telemetry_slope.py`, `telemetry_heading.py` oraz `frame_data.py` (`_to_naive_dt`).

2. **Bezpieczny adapter sygnatur (`inspect.signature`):**
   - Usunięto bloki `try ... except TypeError` wokół wywołań callbacku `resolve_cache_value` w `frame_data.py`.
   - Analiza sygnatury callbacku odbywa się jednorazowo przy wejściu do `prepare_overlay_frame_data()` za pomocą `inspect.signature()`.
   - Starsze callbacki (2 argumenty) są automatycznie adaptowane przez dedykowany adapter bez łapania wyjątków wykonania.
   - Wszelkie błędy wewnętrzne resolvera propagują się z pełnym, nienaruszonym tracebackiem.

---

## 4. Wyniki testów i weryfikacji

### 4.1 Testy regresyjne pytest (`tests/test_preview_datetime_and_callback.py`)
- `test_normalize_datetime_types`: **PASS** (datetime naive/aware, ISO string, timestamp, None, błędy typów)
- `test_presentation_plan_with_datetime_objects`: **PASS**
- `test_presentation_plan_with_iso_strings`: **PASS**
- `test_presentation_plan_with_string_sample_timestamps`: **PASS**
- `test_callback_internal_typeerror_not_masked`: **PASS** (wewnętrzny błąd typu nie jest maskowany)
- `test_legacy_2_arg_callback_supported`: **PASS** (kompatybilność wsteczna 2-arg działa poprawnie)

### 4.2 Testy GUI Preview (`scratch/preview_datetime_fix/gui_smoke_test.py`)
- Testowano z projektem: `Video/GX010298.MP4`, `Video/GX010298.fit`, `Video/GX010298.layout.json`.
- **Cache HIT (`GX010298.telemetry.npz`):**
  - Wyrenderowano 12 klatek (seek: 0.0s, 1.0s, 5.0s, 50.0s, 60.0s, 100.0s, 200.0s + 5 kroków klatek).
  - Wskaźniki aktywnie aktualizują wartości: prędkość, tętno, kadencja, dystans, nachylenie.
  - Traceback count: **0**.
- **Cache MISS (świeży parse GPMF/FIT):**
  - Pełny proces parsowania i budowy osi czasu.
  - Wyrenderowano 12 klatek podglądu z krokami i seekami.
  - Traceback count: **0**.

---

## 5. Metryki i Status Raportu

```text
ROOT_CAUSE_DATETIME=NumericPresentationPlan and boundaries held ISO strings without datetime normalization
ROOT_CAUSE_FALLBACK=try/except TypeError around resolve_cache_value masked internal resolver exceptions

DATETIME_NORMALIZATION_LOCATION=src/telemetry_resolver.py, src/telemetry_slope.py, src/telemetry_heading.py, src/indicators/frame_data.py
LEGACY_FALLBACK_STATUS=Replaced with upfront inspect.signature adapter in prepare_overlay_frame_data

TESTS_PASSED=6/6 unit regression + 15/15 targeted suite
GUI_TRACEBACK_COUNT=0
PREVIEW_STATUS=OK
FRAME_STEP_STATUS=OK
CACHE_HIT_STATUS=OK
CACHE_MISS_STATUS=OK

MODIFIED_FILES=src/telemetry_resolver.py, src/telemetry_slope.py, src/telemetry_heading.py, src/indicators/frame_data.py, src/gui/qt/_mixins/preview_mixin.py, tests/test_preview_datetime_and_callback.py
CASE=CASE A — PREVIEW TELEMETRY FULLY FIXED
```
