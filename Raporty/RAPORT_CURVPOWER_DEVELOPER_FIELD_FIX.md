# RAPORT: FIX ODCZYTU MOCY Z FIT (DEVELOPER FIELD curVPower)

## METADATA
- **Data**: 2026-09-16
- **Workspace**: `C:\_DEV\SportCamHUD`
- **Gałąź**: `amd-bikeridehud`
- **Dataset referencyjny**: `Video\GX010298.MP4` + `Video\GX010298.fit` + `Video\GX010298.layout.json`
- **Status końcowy**: `CASE A — CURVPOWER DEVELOPER FIELD FULLY FIXED`

---

## 1. PODSUMOWANIE METRYK (WYMAGANE POLA)

```text
RAW_CURVPOWER_RECORDS=1400
RAW_STANDARD_POWER_RECORDS=0

FIRST_BROKEN_LAYER=TelemetryDataManager (timeline start_dt_utc anchor & layout mutation) + TelemetryResolver coverage check

ROOT_CAUSE=1. GoPro GPMF anchor znalazł pierwszy lock GPS dopiero na 49.7s (04:31:12.100 UTC), ustawiając start_dt_utc na 04:31:12.100 zamiast startu klipu wideo (04:30:22.390).
2. TelemetryDataManager.resolve_value mutował w locie słownik layoutu kluczem _presentation_video_start=04:31:12.100, co zapisywało się do pliku layoutu.
3. TelemetryResolver (NumericPresentationPlan.value_at) zwracał None dla target < coverage_start (wszystkie klatki przed 04:31:12.100 UTC / 06:31:12 lokalnie), odrzucając prawidłowe próbki FIT obecne od 04:30:21.
4. Brak jawnych aliasów wielkości liter dla curVpower/curVPower/curvpower w SOURCE_ALIASES['fit'] i fallbacku case-insensitive w resolverze.

POWER_063026=6 W
POWER_063030=14 W
POWER_063107=111 W
POWER_063112=0 W

TEXT_WIDGET_STATUS=PASS (111 W przy 06:31:07, 0 W przy 06:31:12, brak '--')
SEGMENT_BAR_STATUS=PASS (111 W przy 06:31:07, 0 W przy 06:31:12, brak '--')

CACHE_HIT_STATUS=PASS
CACHE_MISS_STATUS=PASS
TRACEBACK_COUNT=0

MODIFIED_FILES=src/telemetry_resolver.py, src/gui/telemetry_manager.py, src/gui/qt/_mixins/project_mixin.py, src/gui/layout_manager.py, tests/test_fit_curvpower_and_developer_fields.py
CASE=CASE A — CURVPOWER DEVELOPER FIELD FULLY FIXED
```

---

## 2. PROVENANCE MATRIX (PRZEPŁYW DANYCH DLA KLUCZOWYCH TIMESTAMPÓW)

| Czas lokalny (+2h) | Czas UTC | RAW Developer `curVPower` | RAW Standard `power` | FIT Parser | TelemetryDataManager | TelemetryResolver | Frame Data | Preview Overlay (Text / Bar) |
|---|---|---|---|---|---|---|---|---|
| **06:30:22** | 04:30:22 | 0 W | None | 0.0 W | 0.0 W | 0.0 W | (0.0, 'W', 'Curvpower') | **0 W** |
| **06:30:26** | 04:30:26 | 6 W | None | 6.0 W | 6.0 W | 6.0 W | (6.0, 'W', 'Curvpower') | **6 W** |
| **06:30:30** | 04:30:30 | 14 W | None | 14.0 W | 14.0 W | 14.0 W | (14.0, 'W', 'Curvpower') | **14 W** |
| **06:31:07** | 04:31:07 | 111 W | None | 111.0 W | 111.0 W | 111.0 W | (111.0, 'W', 'Curvpower') | **111 W** |
| **06:31:12** | 04:31:12 | 0 W | None | 0.0 W | 0.0 W | 0.0 W | (0.0, 'W', 'Curvpower') | **0 W** |

---

## 3. AUDYT ARCHITEKTURY FIT DEVELOPER FIELD & PRECEDENCE

1. **FIT Binary Inspection (`fitparse`)**:
   - `field_description`: `developer_data_index=0`, `field_definition_number=0`, `field_name='curVPower'`, `units='watts'`, `native_mesg_num=20` (record), `native_field_num=7` (power).
   - `record` messages: 1400 na 1400 rekordów zawiera developer field `curVPower`. Standardowy field 7 `power` występuje w 0 na 1400 rekordów.
2. **Precedens i Koegzystencja**:
   - Zapytanie o `curVpower` / `curVPower` / `curvpower`: priorytet ma pole deweloperskie, z fallbackiem do standardowego `power`.
   - Zapytanie o standardowe `power`: priorytet ma standardowy `power`, z bezpiecznym fallbackiem do pól deweloperskich (`curVpower`, `curVPower`, `curvpower`).
   - Brak kolizji i brak porzucania pól deweloperskich, gdy deklarowany jest `native_field_num`.
3. **Wartość 0 W**:
   - Wartość `0` (oraz `0.0`) jest traktowana jako prawidłowa liczba telemetryczna, nie jako `None` ani missing data.

---

## 4. WERYFIKACJA AUTOMATYCZNA (PYTEST & SMOKE)

- **Testy jednostkowe**: `tests/test_fit_curvpower_and_developer_fields.py`
  - `test_developer_field_survives_when_standard_power_absent`: **PASSED**
  - `test_developer_zero_is_valid_value`: **PASSED**
  - `test_standard_power_and_developer_curvpower_coexistence_precedence`: **PASSED**
  - `test_gx010298_ground_truth_timestamps`: **PASSED**
- **Testy renderera i preview**: `scratch/curvpower_fix/gui_test.log`
  - Renderowanie pełnej klatki kompozytora 1920x1080: **0 Tracebacks**, **PASS** dla wszystkich 5 punktów kontrolnych.

---

## 5. REJESTR ARTEFAKTÓW W `scratch/curvpower_fix/`

- `raw_fit_proof.md` — bezpośredni dowód z binarnego FIT i opisów pól
- `power_provenance.md` — macierz przepływu danych we wszystkich warstwach
- `field_mapping_audit.md` — pełny audyt logiki aliasów, normalizacji i osi czasu
- `cache_hit_test.txt` — test drugiego dostępu i cache hit
- `cache_miss_test.txt` — test czystego ładowania FIT (cache miss)
- `resolver_test.txt` — weryfikacja produkcyjnego resolwera
- `gui_test.log` — log testu generowania preview dla widgetów text i segment_bar
- `artifacts_manifest.txt` — manifest sum kontrolnych SHA256
- `ntfy_result.txt` — potwierdzenie wysyłki notyfikacji bramki
