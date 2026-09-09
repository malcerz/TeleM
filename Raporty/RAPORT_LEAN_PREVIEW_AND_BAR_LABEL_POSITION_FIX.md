# Lean Preview + BAR label position controls

**Data:** 2026-09-09  
**Branch / HEAD:** `integration/intel-amd` / `59277b4`  
**Zakres:** wspólny resolver telemetryczny Lean oraz generyczna geometria etykiety BAR.  
**Ograniczenia:** bez zmian w `src/ffmpeg/hybrid_render.py`, schedulerze Hybrid,
PreparedVideoFrame, adaptive controller, handoff NVIDIA, backendach i domyślnej
konfiguracji produkcyjnej.

## Lean / Przechył

### Root cause

Po ścieżkach lazy/cache część konsumentów Lean traktowała brak pola `axis` albo
wartość niepoprawną jako `z`. Kontrakt GoPro dla tego layoutu jest jednak
`X = ROLL`, a canonicalnym polem jest `lean_roll_x`. Preview i worker finalny
mogły więc odwoływać się do innego kanału niż konfiguracja `source=gyro`.

Poprawiono wyłącznie fallback konfiguracji w warstwach przygotowania danych,
cache workera i `TelemetryDataManager`: brak/niepoprawna oś wybiera `x`;
jawne `y`/`z` pozostają bez zmian. Nie zmieniono matematyki complementary filter
ani kalibracji wartości.

### Data flow

```text
GPMF ACCL/GYRO
  -> processed telemetry cache / field_samples
  -> TelemetryDataManager._get_lean_roll_samples
  -> resolve_value(lean_roll_x)
  -> prepare_overlay_frame_data / telemetry precompute
  -> lean_visual_angle
  -> wspólny compositor Preview i Final
```

Preview i finalny worker korzystają z tego samego canonicalnego pola i tej samej
interpolacji timestampu; nie dodano sztucznej animacji ani logowania per-frame.
Diagnostyka istnieje wyłącznie za flagą `TELEM_LEAN_DEBUG=1`.

### Realny cache IMU — GX010115

Źródło: `Video/GX010115.telemetry.json.gz`, 117728 próbek ACCL i 117728 próbek
GYRO, zakres `2026-08-14T11:18:03Z`–`11:27:55.619560Z`. `compute_roll_timeline(...,
roll_axis="x")` dał:

| timestamp | gyro_x | accel (x,y,z) | lean_roll_x |
|---|---:|---|---:|
| 11:18:03.000000 | -0.03301 | (-1.062, 0.300, -8.894) | +1.93024° |
| 11:18:27.665707 | +0.50586 | (-2.655, 2.746, -8.501) | +28.19809° |
| 11:18:42.075189 | +0.28754 | (-2.520, -2.005, 12.381) | -15.55543° |
| 11:22:59.293343 | +0.14058 | (-1.120, 0.398, -8.398) | +7.58411° |
| 11:27:55.619560 | +0.53248 | (3.182, 0.024, -8.422) | +8.55131° |

Wartości nie są stałe i zmieniają znak.

## BAR label controls

Dodano do wspólnego renderer-a BAR (bez geometrii backendowej):

* `label_position`: `auto`, `top`, `bottom`, `left`, `right`, `inside`;
* `label_offset_x`, `label_offset_y` jako piksele widgetu, zakres GUI co najmniej
  `-500..500`;
* polskie etykiety GUI: „Pozycja etykiety”, „Przesunięcie etykiety X/Y”.

`auto` zachowuje dotychczasowe położenie. Nowe pola są częścią kluczy cache i
geometrii rastra, więc zmiana właściwości powoduje natychmiastowy raster/bbox
update przez istniejący `_clear_caches()` i ścieżkę property-change. Ruler
poziomy, pionowy, segmenty oraz rotacje 0/90/180/270 używają tego samego
resolvera; tekst pozostaje poziomy, a pozycja jest interpretowana względem
widocznego BAR-a. Preview i Final wywołują wspólny compositor.

## Tests

PASS:

* `python -m pytest -q tests/test_lean_preview_bar_label.py` — **5 passed**;
* compile check dla zmienionych modułów — PASS;
* realny cache IMU GX010115: zmienność i zmiana znaku `lean_roll_x` — PASS;
* `git diff --check` dla zmian zadania: brak błędów w zmienionych plikach zadania.

NOT A REGRESSION / EXISTING:

* `tests/test_lean_imu_contract.py::test_zero_offset_subtracts` pozostaje
  sprzeczny z istniejącym kontraktem kalibracji (+calibration), dlatego nie
  zmieniano tej semantyki w tym zadaniu.

NOT TESTED / NOT PROVEN w tej sesji:

* realny QApplication → AppController → MainWindow → RenderTab playback z
  pięcioma seekami i wizualnym obrotem ikony;
* porównanie screenshotów Preview/Final dla tych samych timestampów;
* GUI drag/save/reload na żywym projekcie.

Nie wykonano pełnego renderu ani zmian na dysku F:.

## Acceptance

| Kryterium | Status |
|---|---|
| LEAN X/ROLL DATA MOVES | PASS (real cache) |
| LEAN PREVIEW ANIMATES | NOT PROVEN (GUI playback) |
| LEAN SEEK | NOT PROVEN (GUI) |
| LEAN PREVIEW/FINAL VALUE PARITY | PASS by shared path; visual proof NOT RUN |
| BAR LABEL AUTO PRESERVES OLD LOOK | PASS (pixel equality test) |
| LABEL TOP/BOTTOM/LEFT/RIGHT/INSIDE | PASS (synthetic renderer test) |
| LABEL OFFSET X/Y | PASS (schema + renderer path) |
| VERTICAL BAR / ROTATED BAR | PASS (synthetic renderer test) |
| SAVE/RELOAD | NOT PROVEN (live GUI) |
| PREVIEW/FINAL PARITY | PASS by shared compositor path; live proof NOT RUN |
| NO BACKEND REGRESSION | PASS — forbidden backend/Hybrid files untouched by this task |

**STATUS = NOT READY FOR FULL ACCEPTANCE** until the live GUI playback/seek and
save-reload proofs are run. No commit or push was performed.

