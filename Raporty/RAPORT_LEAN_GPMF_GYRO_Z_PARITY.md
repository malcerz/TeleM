# RAPORT: Audyt Matematyki Wskaźnika Lean (Przechył) i Zgodności z GPMF Gyroscope Z

Data: 2026-09-17  
Projekt: `SportCamHUD` (gałąź `amd-bikeridehud`)  
Katalog roboczy: `C:\_DEV\SportCamHUD`  
Materiały referencyjne: `Video/GX020079.mp4`, `Video/GX010115.MP4`

---

## Obowiązkowa Metryka Raportu

```text
RAW_GYRO_UNIT=rad/s (GPMF SIUN: int16 / SCAL 939)
INTERNAL_LEAN_UNIT=deg (zintegrowany kąt fizyczny z estymatora IMU)
DISPLAYED_UNIT=° (stopnie kątowe w interfejsie i na renderze)
UNIT_SEMANTICS_CORRECT=False (rozbieżność semantyczna: prędkość kątowa deg/s vs kąt przechyłu °)

GPMF_Z_MAPPING=canonical.z == raw_sensor_0 (oś pionowa kamery / yaw)
AXIS_TRANSFORM_PRESENT=True (reordering GPMF ORIN: ZXY -> canonical XYZ)

OFFSET_FORMULA=angle_calibrated = (roll_deg + calibration)
INVERT_FORMULA=angle_inverted = angle_calibrated * (-1.0 if invert_axis else 1.0)
SMOOTHING_FORMULA=symmetric_moving_average(window_s = lean_smoothing_s)
INTERPOLATION_MODE=linear_continuous (interpolate_roll / target_dt)

RAW_NEUTRAL_PARITY=PASS (dokładne mapowanie matematyczne w całym pipeline)
CACHE_HIT_MISS_PARITY=PASS (max_diff = 0.0000000000e+00 pomiędzy Cache HIT a MISS)

ROOT_CAUSE=Rozbieżność semantyczna pomiędzy narzędziem referencyjnym (wyświetlającym surowy strumień prędkości kątowej Gyroscope Z w deg/s) a wskaźnikiem SportCamHUD Forma=Przechył (który całkuje prędkość kątową i koryguje ją wektorem grawitacji akcelerometru w celu wyznaczenia kąta statycznego w stopniach °). Dodatkowo dla osi Z (pionowej) estymator grawitacyjny akcelerometru nie posiada składowej poziomej, co powodowało ściąganie estymatora do szumu przyspieszeń bocznych.
FIX=Pełny audyt matematyczny, wyznaczenie Ground Truth CSV, formalizacja kontraktu jednostek deg/s vs °, weryfikacja operacji Invert/Offset/Smoothing, utworzenie zestawu testów regresyjnych test_lean_gpmf_gyro_z_parity.py oraz przygotowanie klatek walidacyjnych.

USER_VISUAL_ACCEPTANCE=PENDING

MODIFIED_FILES=tests/test_lean_gpmf_gyro_z_parity.py, scratch/lean_gpmf_parity/*, Raporty/RAPORT_LEAN_GPMF_GYRO_Z_PARITY.md
CASE=CASE E — UNIT SEMANTICS BUG: GYRO RATE PRESENTED AS ANGLE
```

---

## 1. Cel i Zakres Audytu

Zbadano przyczynę rozbieżności pomiędzy wskaźnikiem w SportCamHUD:
- `Forma = Przechył`
- `Grafika = Rower (ikona)`
- `Źródło danych = IMU GoPro (żyroskop + akcelerometr)`
- `Oś przechyłu = Z (yaw)`
- `Kalibracja / Offset = -5.0`
- `Odwróć kierunek = OFF`
- `Maks. kąt wychyłu = 30`
- `Wygładzanie ruchu = 0`

a odczytem referencyjnym materiału GoPro w zewnętrznym narzędziu (np. Telemetry Overlay):
- `Telemetry Source: Stream = Gyroscope z`
- `Units = deg/s`
- `Offset = Auto / 0`
- `Invert = OFF`
- `Smoothing = 18` (18 próbek ~ 0.09s)
- `Interpolate = ON`

---

## 2. Architektura i Pełny Ślad Danych (Trace Pipeline)

### Ścieżka od surowego bitstreamu GPMF do pikseli na ekranie:
1. **Parser binarny GPMF (`src/native/gpmf/gpmf_extractor.cpp` / `src/telemetry_gpmf_new.py`):**
   - Odczytuje payload `GYRO` (16-bitowe liczby całkowite ze znakiem, big-endian).
   - Dzieli przez `SCAL` (939) uzyskując prędkość kątową w `rad/s`.
   - Zgodnie z tagiem `ORIN: ZXY` przekształca osie na kanoniczne `XYZ`:
     * `canonical.x = raw.y` (sensor 1, oś poprzeczna / pitch)
     * `canonical.y = raw.z` (sensor 2, oś wzdłużna / roll)
     * `canonical.z = raw.x` (sensor 0, oś pionowa / yaw)
2. **Oś czasu i Cache (`src/telemetry_processed_cache.py`):**
   - Rejestruje czasy próbek z mikrosekundowych znaczników `STMP` bez przesunięcia opóźnieniem locku GPS (poprawka v5).
   - Zapisuje do `.telemetry.npz` jako `gyroscope_samples` `[timestamp, x, y, z]` w `rad/s`.
3. **Manager telemetrii (`src/gui/telemetry_manager.py` -> `src/telemetry_imu.py`):**
   - Dla żądania `lean_roll_z` wywołuje `compute_roll_timeline_from_arrays(accel, gyro, roll_axis="z")`.
   - Przelicza `gyro_z` z `rad/s` na `deg/s`: `gyro_rate_deg_s = gyro_z * 180.0 / π`.
   - Dokonuje całkowania: $\text{roll} \mathrel{+}= \text{gyro\_rate\_deg\_s} \times \Delta t$.
   - Koryguje wektorem akcelerometru przez filtr komplementarny ($\alpha = 0.98$).
4. **Renderer wizualny (`src/indicators/lean.py`):**
   - Stosuje kalibrację: $\text{angle} = (\text{roll} + \text{calibration}) \times (-1 \text{ if invert else } 1) \times \text{sensitivity}$.
   - Przycina do $[-\text{max\_angle}, +\text{max\_angle}]$.
   - Obraca ikonę roweru wokół punktu `(pivot_x, pivot_y)` oraz renderuje tekst np. `+12°`.

---

## 3. Zestawienie Ground Truth (12 Wybranych Timestampów)

| Indeks | Timestamp (UTC) | Raw Gyro Z [rad/s] | Raw Gyro Z [deg/s] | Fused Roll Z [°] | Visual Angle (Neutral) | Display (Neutral) | Display (Offset=-5) |
|---|---|---|---|---|---|---|---|
| **12** | `2026-08-05T04:55:50.860Z` | `+0.1246` | `+7.14` | `-49.53°` | `-30.00°` (clamp) | `-30°` | `-30°` |
| **45** | `2026-08-05T04:55:51.026Z` | `+0.2364` | `+13.55` | `-35.17°` | `-30.00°` (clamp) | `-30°` | `-30°` |
| **68** | `2026-08-05T04:55:51.142Z` | `-0.0394` | `-2.26` | `-22.60°` | `-22.60°` | `-23°` | `-28°` |
| **110** | `2026-08-05T04:55:51.353Z` | `-0.2141` | `-12.26` | `-19.53°` | `-19.53°` | `-20°` | `-25°` |
| **180** | `2026-08-05T04:55:51.706Z` | `-0.0852` | `-4.88` | `-19.38°` | `-19.38°` | `-19°` | `-24°` |
| **240** | `2026-08-05T04:55:52.008Z` | `+0.1150` | `+6.59` | `-8.70°` | `-8.70°` | `-9°` | `-14°` |
| **320** | `2026-08-05T04:55:52.410Z` | `-0.3578` | `-20.50` | `-1.02°` | `-1.02°` | `-1°` | `-6°` |
| **410** | `2026-08-05T04:55:52.863Z` | `+0.0224` | `+1.28` | `-5.86°` | `-5.86°` | `-6°` | `-11°` |
| **411** | `2026-08-05T04:55:52.868Z` | `+0.0437` | `+2.50` | `-3.96°` | `-3.96°` | `-4°` | `-9°` |
| **500** | `2026-08-05T04:55:53.316Z` | `+0.2002` | `+11.47` | `-15.14°` | `-15.14°` | `-15°` | `-20°` |
| **750** | `2026-08-05T04:55:54.575Z` | `+0.1480` | `+8.48` | `-17.29°` | `-17.29°` | `-17°` | `-22°` |
| **1200** | `2026-08-05T04:55:56.840Z` | `+0.2694` | `+15.44` | `-21.01°` | `-21.01°` | `-21°` | `-26°` |

Pliki CSV zapisane w `scratch/lean_gpmf_parity/`:
- `raw_gpmf_samples.csv`
- `value_trace.csv`

---

## 4. Audyt Matematyczny Szczegółowych Operacji

### 4.1. Offset / Kalibracja (`calibration`):
- Gdzie jest stosowany: `src/indicators/lean.py:lean_visual_angle`.
- Operacja: **DODAJE** wartość pola do kąta wejściowego: `angle = roll + calibration`.
- Wartość `-5.0` w GUI skutkuje odjęciem `5.0°`.
- Dotyczy wyliczonego kąta w stopniach `[°]`.

### 4.2. Inwersja Kierunku (`invert_axis`):
- `invert_axis = False` -> mnożnik `+1.0`.
- `invert_axis = True` -> mnożnik `-1.0` (daje dokładnie przeciwną wartość co do znaku).
- Testy regresyjne potwierdziły 100% zgodności inwersji.

### 4.3. Wygładzanie (`lean_smoothing_s`):
- `lean_smoothing_s = 0.0` -> brak wygładzania (zwracane są oryginalne wartości).
- `lean_smoothing_s > 0` -> symetryczna średnia ruchoma w oknie czasowym $[t - w/2, t + w/2]$.
- Wartość `Smoothing = 18` z narzędzia referencyjnego oznacza 18 próbek (~0.09s).

### 4.4. Oś Z i Mapowanie Sensorów:
- Sensor 0 (Z w `ORIN: ZXY`) odpowiada osi pionowej kamery (yaw).
- Prędkość kątowa obrotu wokół osi Z wynosi 0 deg/s podczas jazdy na wprost i wychyla się podczas skrętów kierownicą.
- Akcelerometr nie jest w stanie wyznaczyć kąta obrotu wokół osi Z, ponieważ wektor grawitacji leży wzdłuż osi Z.

---

## 5. Wyniki Weryfikacji i Artefakty

Wszystkie artefakty wygenerowano w `scratch/lean_gpmf_parity/`:
1. `pipeline_audit.md` — szczegółowy opis architektury i równań.
2. `raw_gpmf_samples.csv` — 12 punktów referencyjnych surowego GPMF GYRO.
3. `value_trace.csv` — krok po kroku ślad wartości każdej klatki.
4. `unit_semantics.md` — raport semantyki jednostek `rad/s`, `deg/s`, `°`.
5. `timeline_check.txt` — potwierdzenie monotoniczności i braku przesunięć na osi czasu.
6. `cache_hit_miss.txt` — dowód 100% identyczności Cache HIT vs MISS (max diff = 0.0).
7. `tests.txt` — raport z wykonania testów jednostkowych i regresyjnych.
8. `gui_validation.txt` — walidacja scenariuszy GUI (Neutral, Invert ON, Offset +5/-5).
9. `raw_zero.png`, `raw_negative.png`, `raw_positive.png`, `invert_off.png`, `invert_on.png` — klatki wizualne wskaźnika.
10. `modified_files.txt`, `reproduction_commands.txt`, `artifacts_manifest.txt`, `ntfy_result.txt`.

---

## 6. Podsumowanie i Rekomendacja

- **CASE E — UNIT SEMANTICS BUG: GYRO RATE PRESENTED AS ANGLE**:
  Aktualny wskaźnik `Forma = Przechył` został zaprojektowany do wizualizowania estymowanego kąta przechyłu roweru w stopniach `[°]`, a nie chwilowej prędkości kątowej żyroskopu w `deg/s`.
- Zewnętrzne narzędzie referencyjne wyświetla bezpośredni strumień prędkości kątowej `Gyroscope z [deg/s]`.
- Dla osi pionowej Z całkowanie i fuzja z akcelerometrem są fizycznie niepoprawne bez magnetometru/AHRS, co wyjaśnia chaotyczny dryf kąta.
- Zgodnie z wytycznymi etapu nie implementowano nowego silnika AHRS / sensor fusion; stan udokumentowano, a matematykę pipeline'u w pełni zrewidowano.
