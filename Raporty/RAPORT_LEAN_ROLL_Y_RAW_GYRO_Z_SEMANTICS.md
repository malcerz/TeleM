# RAPORT: POPRAWA SEMANTYKI WSKAŹNIKA LEAN (ROLL / CANONICAL Y) ORAZ WPROWADZENIE TRYBU RAW GYROSCOPE Z

## 1. Cel i Kontekst Zadania
Zgodnie z audytem GPMF (`Raporty/RAPORT_LEAN_GPMF_GYRO_Z_PARITY.md`), wskaźnik przechyłu (*Forma = Przechył*) został naprawiony pod kątem fizycznej poprawności i rozróżnienia pomiędzy kątem przechyłu roweru `[°]` a surową prędkością kątową żyroskopu `[deg/s]`.

### Kluczowe fakty matematyczne i fizyczne
1. **Układ współrzędnych GPMF**:
   - `canonical.y` = Roll (oś wzdłużna roweru / fizyczny kąt przechyłu lewo-prawo).
   - `canonical.z` = Yaw (oś pionowa / rotacja w płaszczyźnie poziomej wokół wektora grawitacji).
   - `canonical.x` = Pitch (oś poprzeczna / pochylenie przód-tył).
2. **Rozdzielenie strumieni**:
   - **Lean (Przechył)**: Estymowany fizyczny kąt przechyłu roweru w stopniach `[°]` wyliczany przez deterministyczny filtr komplementarny (`gyro integration + accelerometer gravity correction`).
   - **Raw Gyroscope Z**: Bezpośrednia prędkość kątowa obrotu pionowego w `[deg/s]` (`GPMF canonical Z * 180 / pi`) bez fuzji z grawitacją i bez całkowania do kąta, umożliwiająca 100% zgodność z zewnętrznymi narzędziami telemetrycznymi (*Telemetry Overlay* `Stream = Gyroscope z`, `Units = deg/s`).

---

## 2. Wdrożone Zmiany

### A. Schemat GUI i Modele (`src/gui/qt/models.py`, `src/gui/qt/_mixins/indicator_mixin.py`)
- `lean_indicator_fields()`:
  - `source`: dodano wybór `("raw_gyro_z", "GoPro Gyroscope Z (prędkość kątowa [deg/s])")` obok `gyro` (IMU GoPro) i `grade` (FIT).
  - `axis`: domyślna wartość zmieniona na `"y"` (`Roll (Y) — przechył wzdłużny [domyślna]`), z czytelnym opisem dla `"x"` (`Pitch (X)`) i `"z"` (`Yaw (Z) — obrót pionowy / skręt`).
  - `calibration`: domyślny offset `0.0`.
  - `max_angle`: czytelna etykieta `Maks. kąt wychyłu / zakres`.
- `indicator_mixin.py`:
  - Domyślna konfiguracja nowego wskaźnika `lean_indicator`: `field = "lean_roll_y"`, `axis = "y"`, `calibration = 0.0`, `zero_offset = 0.0`.

### B. Prekomputacja i Zarządzanie Telemetrią (`src/gui/telemetry_manager.py`, `src/ffmpeg/worker_cache.py`)
- `_get_lean_roll_samples(axis="y", smoothing_s=0.0)`: domyślny fallback na oś `y`.
- Dodano `_get_raw_gyro_samples(axis="z", smoothing_s=0.0)` oraz `_worker_raw_gyro(axis="z", smoothing_s=0.0)`:
  - Dokonuje prekomputacji surowych próbek prędkości kątowej w `deg/s` z bufora NumPy `gyroscope_array`.
  - Obsługuje wygładzanie oknem symetrycznym `lean_smoothing_s` (`smooth_roll_samples`).
  - Cache'owanie per `axis` i `smoothing_s`.
- Obsługa pól `raw_gyro_*` w `resolve_value()` oraz `_resolve_cache_value()`.

### C. Frame Data i Renderer (`src/indicators/frame_data.py`, `src/telemetry_precompute.py`, `src/indicators/lean.py`)
- `frame_data.py`:
  - Gdy `source == "raw_gyro_z"`: rozwiązuje `raw_gyro_{axis}`, jednostka `deg/s`, etykieta `Gyroscope Z`.
  - Gdy `source == "gyro"`: rozwiązuje `lean_roll_{axis}` (domyślnie `y`), jednostka `°`, etykieta `Przechył`.
- `telemetry_precompute.py`:
  - Wektoryzacja `lean_field_arrs` dla `raw_gyro_z` oraz domyślna oś `y` dla `gyro`.
- `lean.py`:
  - Formatowanie tekstu wartości uwzględnia jednostki: `{angle:+.0f} deg/s` dla `deg/s`, `{angle:+.0f}°` dla `°`, `{angle:+.0f}%` dla `%`.

---

## 3. Kompatybilność Wsteczna ze Starymi Layoutami

| Aspekt | Zasada Kompatybilności | Status |
|---|---|---|
| **Istniejące layouty z `axis = "x"`** | Zachowują ewaluację osi `x` bez błędów i bez nadpisywania | **PASS** |
| **Istniejące layouty z `axis = "z"`** | Zachowują ewaluację osi `z` bez błędów i bez nadpisywania | **PASS** |
| **Pliki JSON użytkownika** | Brak cichych migracji, brak nadpisywania plików layoutów na dysku | **PASS** |
| **Nowo dodawane wskaźniki** | Domyślnie tworzone z osią `y` (Roll) i kalibracją `0.0°` | **PASS** |

---

## 4. Wyniki Weryfikacji i Ground Truth (`Video/GX010115.MP4`)

### A. Ground Truth dla Osi Roll (Y) vs Yaw (Z)
Na podstawie 12 punktów kontrolnych w materiale `Video/GX010115.MP4`:
- **Roll Y (`fused_roll_y_deg`)**: Stabilny kąt przechyłu w zakresie od `-6.60°` do `+16.18°`, wracający deterministycznie w okolice zera przy jeździe na wprost (`+2.04°`, `+1.05°`, `-0.39°`, `-0.34°`).
- **Yaw Z (`fused_z_yaw_drift_deg`)**: Wykazuje ciągły dryf całkowania (od `+18.53°` do `+117.81°`), dowodząc że Z nie może być używane jako kąt przechyłu.

### B. Ground Truth dla Raw Gyroscope Z (`deg/s`)
- Porównanie interpolowanej prędkości kątowej z bezpośrednimi próbkami GPMF wykazuje pełną zgodność (`RAW_GYRO_Z_PARITY = PASS`, różnica w granicach interpolacji liniowej `< 0.3 deg/s`).

### C. Weryfikacja Cache HIT vs MISS
- Sprawdzono spójność rozdzielczości klatkowej dla obu trybów (`lean_roll_y` oraz `raw_gyro_z`):
  - `Max difference (Hit vs Miss) = 0.000000000000e+00` (dokładne 0.0).

### D. Weryfikacja Odwrócenia (Invert) i Kalibracji (Offset)
- `invert_axis = True` daje dokładnie przeciwny znak: `v_on == -v_off`.
- W trybie Lean: offset `calibration` operuje w `[°]`.
- W trybie Raw Gyro: offset `calibration` operuje w `[deg/s]`.

---

## 5. Wygenerowane Artefakty

Wszystkie wymagane pliki zostały fizycznie zapisane w `scratch/lean_roll_semantics_fix/`:
- `audit_before.md`: Audyt stanu początkowego i założeń.
- `roll_ground_truth.csv`: 12 punktów pomiarowych Roll Y z danymi żyroskopu, akcelerometru i fuzji.
- `raw_gyro_z_ground_truth.csv`: 12 punktów pomiarowych Raw Gyro Z z porównaniem do GPMF.
- `lean_trace.csv`: 100-punktowy ślad czasowy Lean Roll Y.
- `raw_trace.csv`: 100-punktowy ślad czasowy Raw Gyro Z.
- `cache_parity.txt`: Raport dokładności Cache Hit vs Miss (`diff = 0.0`).
- `tests.txt`: Wyniki 120 testów regresyjnych (119 passed, 1 skipped).
- `gui_validation.txt`: Log walidacji modeli i kompozytora GUI.
- `lean_roll_neutral.png`: Render neutralnego przechyłu roweru.
- `lean_roll_left.png`: Render przechyłu roweru w lewo.
- `lean_roll_right.png`: Render przechyłu roweru w prawo.
- `raw_gyro_z_positive.png`: Render wskaźnika dla dodatniej prędkości kątowej Gyro Z (+76 deg/s).
- `raw_gyro_z_negative.png`: Render wskaźnika dla ujemnej prędkości kątowej Gyro Z (-50 deg/s).
- `modified_files.txt`: Lista zmienionych plików.
- `reproduction_commands.txt`: Komendy odtworzenia wyników.
- `artifacts_manifest.txt`: Pełny manifest artefaktów.
- `ntfy_result.txt`: Wynik notyfikacji NTFY.

---

## 6. Zestawienie Metryk i Status

```text
LEAN_PHYSICAL_AXIS=Roll (Y / oś wzdłużna)
LEAN_UNIT=°
RAW_GYRO_Z_UNIT=deg/s

NEW_LEAN_DEFAULT=axis="y", calibration=0.0, zero_offset=0.0
OLD_LAYOUT_COMPATIBILITY=PASS (brak cichej migracji, pełna obsługa starych osi x/z)

RAW_GYRO_Z_PARITY=PASS
LEAN_ROLL_STABILITY=PASS (brak dryfu, stabilny poziom)
INVERT_PARITY=PASS (dokładne odwrócenie znaku)
OFFSET_UNITS_CORRECT=PASS (Lean w °, Raw Gyro w deg/s)
CACHE_HIT_MISS_PARITY=PASS (max diff = 0.0)

GUI_SEMANTICS_CLEAR=PASS (jednoznaczne etykiety osi i źródeł)

MODIFIED_FILES=10
USER_VISUAL_ACCEPTANCE=PENDING
CASE=CASE A — LEAN ROLL/Y + RAW GYRO Z SEMANTICS FULL PASS
```
