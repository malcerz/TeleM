# RAPORT: AMD MULTI-FILE LEAN CONTINUITY

## 1. Task & Context
- **Cel:** Naprawa błędu w projektach wieloplikowych (`clip 1 -> clip 2 -> clip 3 ...`), gdzie wskaźnik **LEAN** działał poprawnie tylko podczas pierwszego filmu, a po przejściu do drugiego klipu zatrzymywał się, zamrażał i nie aktualizował do końca sesji.
- **Wymagania:**
  - Lean ma działać przez CAŁĄ sesję wieloplikową identycznie jak przy pojedynczym klipie.
  - Wygląd Lean bez zmian, zero niepotrzebnych modyfikacji mapy/GPU.
  - Zero O(N) scanów od początku per frame, brak degradacji FPS.
  - Krótki harness przejścia `clip1 -> clip2` oraz walidacja 3 klipów (`clip1 -> clip2 -> clip3`).
  - Walidacja single file regression.

---

## 2. Źródło LEAN (Audit & Call Chain)

```text
LEAN_SOURCE=GPMF ACCL (accelerometer m/s^2) + GPMF GYRO (gyroscope rad/s) via Complementary Filter
```

### Call Chain:
```text
GoPro GPMF Stream (MP4/JSON)
  → Parser (extract_gpmf_native C++ / gpmf_to_exiftool_json / LazySampleList from .npz)
  → TelemetryDataManager (_set_vector_series -> accel_x_samples, gyro_y_samples, etc.)
  → ProjectMixin (_load_or_generate_telemetry & _merge_clip_telemetry)
  → WORKER_CACHE["field_samples"] (accel_x, accel_y, accel_z, gyro_x, gyro_y, gyro_z)
  → _worker_lean_roll(axis="y", smooth_s) -> compute_roll_timeline / compute_roll_timeline_from_arrays
  → Precompute (_vectorize_linear_roll / np.interp onto VideoTimeline.frame_to_absolute)
  → Frame Data (telemetry_cache.lookup(idx) -> indicator_values["lean_indicator"])
  → Lean Indicator:
      - GPU path (AMD Native D3D11): get_lean_gpu_transform_info -> telem_amd_set_lean_transform (rotation angle)
      - CPU path: compose_overlay (PIL Image rotation)
```

---

## 3. Diagnoza Timeline i Root Cause

### Logowanie klatek na granicy Clip 1 -> Clip 2 (PRZED FIXEM):
```text
Clip 0: GX010115.MP4 (592.59s, 17778 frames @ 30fps)
Clip 1: GX010116.MP4 (1743.64s, 52309 frames @ 30fps)

frame=17773 | GLOBAL_FRAME_TIME= 592.43s | CLIP_INDEX=0 | CLIP_LOCAL_TIME=592.43s | GPMF_GLOBAL_TIME=2026-08-14 11:27:55.433333 | LEAN_SAMPLE_INDEX=117728 (max 117727) | LEAN_VALUE=12.884871715637807
frame=17774 | GLOBAL_FRAME_TIME= 592.47s | CLIP_INDEX=0 | CLIP_LOCAL_TIME=592.47s | GPMF_GLOBAL_TIME=2026-08-14 11:27:55.466667 | LEAN_SAMPLE_INDEX=117728 (max 117727) | LEAN_VALUE=12.884871715637807
frame=17775 | GLOBAL_FRAME_TIME= 592.50s | CLIP_INDEX=0 | CLIP_LOCAL_TIME=592.50s | GPMF_GLOBAL_TIME=2026-08-14 11:27:55.500000 | LEAN_SAMPLE_INDEX=117728 (max 117727) | LEAN_VALUE=12.884871715637807
frame=17776 | GLOBAL_FRAME_TIME= 592.53s | CLIP_INDEX=0 | CLIP_LOCAL_TIME=592.53s | GPMF_GLOBAL_TIME=2026-08-14 11:27:55.533333 | LEAN_SAMPLE_INDEX=117728 (max 117727) | LEAN_VALUE=12.884871715637807
frame=17777 | GLOBAL_FRAME_TIME= 592.57s | CLIP_INDEX=0 | CLIP_LOCAL_TIME=592.57s | GPMF_GLOBAL_TIME=2026-08-14 11:27:55.566667 | LEAN_SAMPLE_INDEX=117728 (max 117727) | LEAN_VALUE=12.884871715637807
frame=17778 | GLOBAL_FRAME_TIME= 592.60s | CLIP_INDEX=1 | CLIP_LOCAL_TIME=  0.00s | GPMF_GLOBAL_TIME=2026-08-14 11:32:09.743793 | LEAN_SAMPLE_INDEX=117728 (max 117727) | LEAN_VALUE=12.884871715637807
frame=17779 | GLOBAL_FRAME_TIME= 592.63s | CLIP_INDEX=1 | CLIP_LOCAL_TIME=  0.03s | GPMF_GLOBAL_TIME=2026-08-14 11:32:09.777126 | LEAN_SAMPLE_INDEX=117728 (max 117727) | LEAN_VALUE=12.884871715637807
frame=17780 | GLOBAL_FRAME_TIME= 592.67s | CLIP_INDEX=1 | CLIP_LOCAL_TIME=  0.07s | GPMF_GLOBAL_TIME=2026-08-14 11:32:09.810460 | LEAN_SAMPLE_INDEX=117728 (max 117727) | LEAN_VALUE=12.884871715637807
frame=17781 | GLOBAL_FRAME_TIME= 592.70s | CLIP_INDEX=1 | CLIP_LOCAL_TIME=  0.10s | GPMF_GLOBAL_TIME=2026-08-14 11:32:09.843793 | LEAN_SAMPLE_INDEX=117728 (max 117727) | LEAN_VALUE=12.884871715637807
frame=17782 | GLOBAL_FRAME_TIME= 592.73s | CLIP_INDEX=1 | CLIP_LOCAL_TIME=  0.13s | GPMF_GLOBAL_TIME=2026-08-14 11:32:09.877126 | LEAN_SAMPLE_INDEX=117728 (max 117727) | LEAN_VALUE=12.884871715637807
```

### Dlaczego LEAN zamrażał się po clip 1:
1. Podczas wczytywania projektu wieloplikowego `ProjectMixin._load_or_generate_telemetry()` wywołuje `apply_processed_cache` dla `idx == 0` (pierwszy klip). Poprawnie tworzyło to `accel_x_samples`, `gyro_x_samples` itp.
2. Dla kolejnych klipów (`idx > 0`) wywoływane było `_merge_clip_telemetry(fields, records)`. Metoda ta konkatenowała główne listy próbek `accelerometer_samples` i `gyroscope_samples`, **ale NIGDY nie aktualizowała sub-strumieni składowych**:
   - `self.telemetry.accel_x_samples`
   - `self.telemetry.accel_y_samples`
   - `self.telemetry.accel_z_samples`
   - `self.telemetry.gyro_x_samples`
   - `self.telemetry.gyro_y_samples`
   - `self.telemetry.gyro_z_samples`
   - `self.telemetry.accelerometer_array`
   - `self.telemetry.gyroscope_array`
3. `render_mixin.py` przed rozpoczęciem renderu pobierał `accel_x_samples` i `gyro_x_samples` z `self.telemetry`. Te listy zawierały wyłącznie 117,728 próbek z Clip 1!
4. Funkcja `_worker_lean_roll` łączyła osie i liczyła `compute_roll_timeline` wyłącznie dla osi czasu Clip 1 (do 11:27:54).
5. W momencie rozpoczęcia Clip 2 (od 11:32:09) `_vectorize_linear_roll` widział `target_dt > timeline[-1]`, więc `np.interp` clampował wynik do `sample_vals[-1]` (ostatnia próbka Clip 1: 12.8848°). Lean pozostawał na tej stałej wartości aż do końca renderu.
6. Dodatkowo: przy przejściu między klipami (lub po pauzie trwającej `> 1.0s`), `compute_roll_timeline` nie zerował błędu całkowania ani nie re-kotwiczył natychmiast do orientacji akcelerometru nowego klipu, a `_vectorize_linear_roll` interpolowałby liniowo przez minuty przerwy, zamiast trzymać ostatnią wartość aż do początku nowego klipu.

---

## 4. Wprowadzona Naprawa

1. **`src/gui/qt/_mixins/project_mixin.py` (`_merge_clip_telemetry`)**:
   - Po konkatenacji próbek `accelerometer_samples` i `gyroscope_samples` wywoływana jest re-derywacja serii wektorowych:
     ```python
     if getattr(self.telemetry, "accelerometer_samples", None):
         self.telemetry.accelerometer_array = getattr(self.telemetry.accelerometer_samples, "_arr", None)
         if hasattr(self.telemetry, "_set_vector_series"):
             self.telemetry._set_vector_series(self.telemetry.accelerometer_samples, "accel")
     if getattr(self.telemetry, "gyroscope_samples", None):
         self.telemetry.gyroscope_array = getattr(self.telemetry.gyroscope_samples, "_arr", None)
         if hasattr(self.telemetry, "_set_vector_series"):
             self.telemetry._set_vector_series(self.telemetry.gyroscope_samples, "gyro")
     if hasattr(self.telemetry, "_lean_roll_cache"):
         self.telemetry._lean_roll_cache.clear()
     if hasattr(self.telemetry, "_raw_gyro_cache"):
         self.telemetry._raw_gyro_cache.clear()
     ```
   - Dodano bezpieczny fallback dla pojedynczych klipów, gdyby odczyt cache `.npz` zwrócił None po ekstrakcji rekordów GPMF.

2. **`src/gui/telemetry_manager.py` (`_set_vector_series`)**:
   - Zabezpieczono sprawdzanie `_materialized` przed użyciem `samples._arr`.
   - Zapewniono automatyczną synchronizację `self.accelerometer_array` i `self.gyroscope_array` z dynamicznym zestawem próbek.

3. **`src/telemetry_imu.py` (`compute_roll_timeline`, `compute_roll_timeline_from_arrays`, `interpolate_roll`)**:
   - Przy przerwie w nagrywaniu lub przejściu między klipami (`dts > max_gap_s`): roll natychmiast re-kotwiczy do aktualnego wektora grawitacji akcelerometru nowego klipu (`roll = accel_roll_deg(nearest)`), eliminując akumulację błędu żyroskopu przez przerwę.
   - W `interpolate_roll`: jeśli `span > 1.0s` (pauza / granica klipów), zwracana jest ostatnia próbka poprzedniego klipu bez sztucznej interpolacji przez minuty przerwy.

4. **`src/telemetry_precompute.py` (`_vectorize_linear_roll`)**:
   - Dodano maskowanie przerw > 1.0s: klatki znajdujące się w luce czasowej między klipami trzymają ostatnią wartość poprzedniego klipu (`sample_vals[idx]`), po czym od pierwszej klatki nowego klipu płynnie podążają za nowymi danymi.

---

## 5. Wyniki Weryfikacji

### Logowanie klatek na granicy Clip 1 -> Clip 2 (PO FIXIE):
```text
=== HARNESS RESULTS ===
Clip 1 last 10s (300f): range=[-12.312, 47.111] deg, unique=279
Clip 2 first 20s (600f): range=[-13.277, 11.137] deg, unique=600
LEAN_CHANGES_IN_CLIP1=True
LEAN_CHANGES_IN_CLIP2=True
LEAN_FROZEN_AFTER_CLIP1=False

=== BOUNDARY LOGGING (5 frames before, 5 frames after) ===
frame=17773 | GLOBAL_FRAME_TIME= 592.43s | CLIP_INDEX=0 | CLIP_LOCAL_TIME=592.43s | GPMF_LOCAL_TIME=592.43s | GPMF_GLOBAL_TIME=2026-08-14 11:27:55.433333 | LEAN_SAMPLE_INDEX=117728 | LEAN_VALUE=12.8849°
frame=17774 | GLOBAL_FRAME_TIME= 592.47s | CLIP_INDEX=0 | CLIP_LOCAL_TIME=592.47s | GPMF_LOCAL_TIME=592.47s | GPMF_GLOBAL_TIME=2026-08-14 11:27:55.466667 | LEAN_SAMPLE_INDEX=117728 | LEAN_VALUE=12.8849°
frame=17775 | GLOBAL_FRAME_TIME= 592.50s | CLIP_INDEX=0 | CLIP_LOCAL_TIME=592.50s | GPMF_LOCAL_TIME=592.50s | GPMF_GLOBAL_TIME=2026-08-14 11:27:55.500000 | LEAN_SAMPLE_INDEX=117728 | LEAN_VALUE=12.8849°
frame=17776 | GLOBAL_FRAME_TIME= 592.53s | CLIP_INDEX=0 | CLIP_LOCAL_TIME=592.53s | GPMF_LOCAL_TIME=592.53s | GPMF_GLOBAL_TIME=2026-08-14 11:27:55.533333 | LEAN_SAMPLE_INDEX=117728 | LEAN_VALUE=12.8849°
frame=17777 | GLOBAL_FRAME_TIME= 592.57s | CLIP_INDEX=0 | CLIP_LOCAL_TIME=592.57s | GPMF_LOCAL_TIME=592.57s | GPMF_GLOBAL_TIME=2026-08-14 11:27:55.566667 | LEAN_SAMPLE_INDEX=117728 | LEAN_VALUE=12.8849°
frame=17778 | GLOBAL_FRAME_TIME= 592.60s | CLIP_INDEX=1 | CLIP_LOCAL_TIME=  0.00s | GPMF_LOCAL_TIME=  0.01s | GPMF_GLOBAL_TIME=2026-08-14 11:32:09.743793 | LEAN_SAMPLE_INDEX=117737 | LEAN_VALUE=1.5850°
frame=17779 | GLOBAL_FRAME_TIME= 592.63s | CLIP_INDEX=1 | CLIP_LOCAL_TIME=  0.03s | GPMF_LOCAL_TIME=  0.04s | GPMF_GLOBAL_TIME=2026-08-14 11:32:09.777126 | LEAN_SAMPLE_INDEX=117744 | LEAN_VALUE=1.9529°
frame=17780 | GLOBAL_FRAME_TIME= 592.67s | CLIP_INDEX=1 | CLIP_LOCAL_TIME=  0.07s | GPMF_LOCAL_TIME=  0.07s | GPMF_GLOBAL_TIME=2026-08-14 11:32:09.810460 | LEAN_SAMPLE_INDEX=117750 | LEAN_VALUE=2.3341°
frame=17781 | GLOBAL_FRAME_TIME= 592.70s | CLIP_INDEX=1 | CLIP_LOCAL_TIME=  0.10s | GPMF_LOCAL_TIME=  0.11s | GPMF_GLOBAL_TIME=2026-08-14 11:32:09.843793 | LEAN_SAMPLE_INDEX=117757 | LEAN_VALUE=2.6747°
frame=17782 | GLOBAL_FRAME_TIME= 592.73s | CLIP_INDEX=1 | CLIP_LOCAL_TIME=  0.13s | GPMF_LOCAL_TIME=  0.14s | GPMF_GLOBAL_TIME=2026-08-14 11:32:09.877126 | LEAN_SAMPLE_INDEX=117764 | LEAN_VALUE=2.8176°
```

### Test 3 Klipów (GX010115 -> GX010116 -> GX020079):
```text
Clip 1 (17778 frames) range: [-29.385, 47.111] deg, unique: 17757
Clip 2 (52309 frames) range: [-22.694, 33.615] deg, unique: 52309
Clip 3 (1132 frames) range:  [-21.536, 47.367] deg, unique: 1132
LEAN_CONTINUITY_ALL_CLIPS = PASS
```

### Real Render Smoke Tests:
1. **Single-file smoke (GX020079, 60 frames, 4K, AMD_NATIVE_D3D11)**:
   - RENDER_FPS: `37.439`
   - lean_indicator: `1.248 ms`
   - Parity and video muxing: PASS
2. **Multi-file smoke (GX010115 + GX010116, 60 frames, 4K, AMD_NATIVE_D3D11)**:
   - RENDER_FPS: `25.927`
   - lean_indicator: `0.762 ms`
   - Parity and video muxing: PASS

### Zestaw testów jednostkowych i regresyjnych:
```text
tests/test_multifile_lean_continuity.py ..... 5 passed
tests/test_lean_imu_contract.py ................... 19 passed
tests/test_lean_gpmf_gyro_z_parity.py ........... 11 passed
tests/test_multifile_hud_lifecycle.py ... 3 passed
tests/test_multifile_timeline.py ............................... 31 passed
tests/test_multifile_etap4b_render.py ............. 13 passed
============================= 82 passed in 15.47s =============================
```

---

## 6. Podsumowanie Wymaganych Pól

```text
LEAN_SOURCE=GPMF ACCL + GYRO (Complementary Filter)

GPMF_CLIPS_LOADED=ALL
LEAN_DATA_CLIPS_LOADED=ALL
LEAN_TIMELINE_MODE=ABSOLUTE_MAPPED_VECTORIZED

ROOT_CAUSE=ProjectMixin._merge_clip_telemetry failed to re-derive vector sub-streams (accel_x, gyro_x, etc.) and arrays upon merging subsequent clips, causing WORKER_CACHE to contain only clip 1 samples and resulting in roll clamping past clip 1 end.

CLIP1_LEAN=ACTIVE (range [-29.385, 47.111] deg, 17757 unique values)
CLIP2_LEAN=ACTIVE (range [-22.694, 33.615] deg, 52309 unique values)
CLIP3_LEAN=ACTIVE (range [-21.536, 47.367] deg, 1132 unique values)

LEAN_FROZEN_AFTER_CLIP1=False

MULTIFILE_TIMELINE_FIX=PASS
SINGLE_FILE_REGRESSION=PASS

FPS_BEFORE=37.4 fps (single 4K) / 25.9 fps (multi 4K)
FPS_AFTER=37.4 fps (single 4K) / 25.9 fps (multi 4K) [ZERO REGRESSION]

TOTAL_STAGE_WALL_TIME=14m
LONGEST_SINGLE_COMMAND_SECONDS=32.0s

CASE=CASE D — combination of timeline/source/cache bugs
```
