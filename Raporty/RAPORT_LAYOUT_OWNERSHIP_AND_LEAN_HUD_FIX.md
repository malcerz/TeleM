# RAPORT: RESTORE LAYOUT OWNERSHIP + LEAN HUD PREP HANG + LEAN +6° CALIBRATION

Data: 2026-09-03  
Repozytorium: `C:\_DEV\TeleM-integration`  
Gałąź: `integration/intel-amd`  
Commit bazowy: `c80ba07`  

---

## 1. Cel zadania

1. **Przywrócenie właściwego modelu Persistence & Layout Ownership**:
   - Rozdzielenie niezależnego, wielokrotnego użytku **Presetu Użytkownika** (`User Preset`) od **Layoutu Roboczego Filmu** (`Project-Local Layout`, `video.layout.json`).
   - Przywrócenie kontraktu Save File Dialog (`QFileDialog.getSaveFileName`) dla zapisu presetu użytkownika; usunięcie mylącego przycisku autosave do `def_layout.json` z paska `DataStreamBar`.
   - Zagwarantowanie absolutnej niezmienności (immutability) wczytanego presetu użytkownika podczas edycji właściwości, renderingu i zamknięcia filmu (potwierdzone testem sentinela).
   - Automatyczne powiązanie stanu roboczego z filmem (`video.layout.json`), tak aby rendering i restart projektu korzystały z lokalnego stanu pracy bez dotykania szablonów bazowych czy presetów.
2. **Diagnoza i usunięcie blokady (hang/freeze) podczas przygotowywania HUD z włączonym wskaźnikiem Lean**:
   - Wyjaśnienie stanu `HUD: 4.5 / 8, 56.2%, Przygotowywanie HUD: heading`.
   - Zidentyfikowanie wąskiego gardła pamięciowego/obliczeniowego i wektoryzacja prekomputacji przechyłu IMU.
3. **Kalibracja wskaźnika Lean na +6°**:
   - Spójne wdrożenie kalibracji: `calibrated = raw + calibration` (gdzie domyślna kalibracja dla layoutu to `+6.0°`, a brak pola w starszych projektach daje `0.0°`).
   - Identyczny kąt obrotu grafiki (ikona roweru `bike`) oraz odczytu liczbowego (`value_text`) w podglądzie (Preview) i eksporcie (Render).
   - Ograniczony cache obróconych kafelków grafiki (`_BoundedStaticCache`).
4. **Weryfikacja produkcyjna**:
   - Obowiązkowy test sentinela `scratch/user_preset_sentinel.json` (byte-for-byte SHA256).
   - Testy jednostkowe matematyki kalibracji i testy regresyjne GUI.
   - Prawdziwy smoke render na `GX010115.MP4` + `GX010114_116.fit` (300 klatek 4K AMD D3D11/AMF) z włączonym Lean i obracaną ikoną roweru.

---

## 2. Diagnoza persistence i layout ownership

### Przyczyna problemu w poprzednim etapie (v5)
W etapie v5 błędnie powiązano akcję zapisu z plikiem repozytoryjnym `def_layout.json`. W efekcie:
- Kliknięcie przycisku zapisu nadpisywało globalny plik konfiguracyjny aplikacji zamiast pozwalać użytkownikowi wskazać plik presetu.
- Uruchomienie renderingu (`RenderMixin._on_render_requested`) wykonywało twardy zapis bieżącego layoutu RAM bezpośrednio do `def_layout.json`.
- Brakowało pojęcia layoutu roboczego powiązanego z konkretnym plikiem wideo, przez co edycja w jednym projekcie niszczyła bazowy szablon lub plik presetu.

---

## 3. Zmiana kontraktu zapisu/odczytu (User Preset vs Project-Local Layout)

Zaimplementowano czysty podział na dwa byty:

### A. PRESET UŻYTKOWNIKA (User Preset)
* **Zapis (`PresetMixin._on_save_preset`)**:
  - Wywoływany przyciskiem **„Zapisz preset”** w `DataStreamBar`.
  - Otwiera standardowy systemowy dialog `QFileDialog.getSaveFileName(None, "Zapisz preset układu", "", "JSON (*.json);;Wszystkie (*.*)")`.
  - Użytkownik sam wybiera folder i nazwę pliku.
* **Odczyt (`PresetMixin._on_load_preset`)**:
  - Wywoływany przyciskiem **„Wczytaj preset”** w `DataStreamBar`.
  - Otwiera `QFileDialog.getOpenFileName(...)`.
  - Zapisuje ścieżkę do `self._user_preset_path` wyłącznie informacyjnie.
  - **IMMUTABILITY**: Wczytany plik presetu jest **tylko do odczytu**. Żadne późniejsze akcje użytkownika (przesunięcie wskaźnika, zmiana fontu, start renderingu) **nigdy nie zapisują** do tego pliku!
* **Pasek `DataStreamBar`**:
  - Usunięto zbędny, konfundujący przycisk `save_settings_btn` („Zapisz ustawienia”). Pozostawiono:
    `Zapisz preset`, `Wczytaj preset`, `Resetuj układ`.
  - Przycisk „Zapisz ustawienia” znajduje się wyłącznie w zakładce `Ustawienia` (`SettingsTab`) i służy celowemu zapisowi globalnych parametrów aplikacji do `def_layout.json`.

### B. LAYOUT ROBOCZY FILMU (Project-Local Layout)
* **Lokalizacja**: `video_path.with_suffix(".layout.json")` (np. `Video/GX010115.layout.json`).
* **Zapis (`PresetMixin._save_project_layout`)**:
  - Wywoływany automatycznie przy zmianie właściwości wskaźników (`_on_property_changed`) oraz przed startem renderingu (`_on_render_requested`).
  - Zapisuje aktualny stan pracy nad danym filmem do dedykowanego pliku sidecar `.layout.json`.
  - Nie dotyka ani wczytanego presetu użytkownika, ani `def_layout.json`.
* **Wczytywanie filmu (`ProjectMixin._load_video`)**:
  - Priorytet 1: Sprawdzenie, czy istnieje `video_path.with_suffix(".layout.json")`. Jeśli tak — wczytanie roboczego stanu filmu.
  - Priorytet 2: Jeśli brak layoutu lokalnego — sprawdzenie startowego presetu `_startup_preset`.
  - Priorytet 3: Fallback do szablonu bazowego `def_layout.json`.

---

## 4. Diagnoza hang HUD preparation (Lean)

Użytkownik zaobserwował zatrzymanie renderingu na etapie:
`status około: HUD: 4.5 / 8, 56.2%, Czas: 00:01, Przygotowywanie HUD: heading`

### Analiza ścieżki wykonania:
1. `build_telemetry_cache()` w `src/telemetry_precompute.py`:
   - Etap `heading` wywołuje `_progress("heading")`.
   - UI aktualizuje progress tracker do etapu 4.5/8 (56.2%) z etykietą `"heading"`.
2. Bezpośrednio po `heading` uruchamiany jest etap 7b: `lean fields`:
   - Obliczanie osi przechyłu z filtru komplementarnego `compute_roll_timeline()` dla 117 728 próbek żyroskopu i akcelerometru.
   - Wypełnianie tablicy dla klatek wideo:
     ```python
     lean_field_arrs.append([_interp_roll(timeline, dt) for dt in target_dts])
     ```
3. Wewnątrz `interpolate_roll()` w `src/telemetry_imu.py`:
   ```python
   times = [_naive(s[0]) for s in roll_samples]
   i = bisect.bisect_left(times, target_dt)
   ```

---

## 5. Dokładna przyczyna (Root Cause)

1. **Wykładnicza alokacja pamięci w pętli klatek**:
   - `timeline` zawiera 117 728 punktów pomiarowych IMU.
   - Wewnątrz `interpolate_roll()`, linijka `times = [_naive(s[0]) for s in roll_samples]` tworzyła **nową listę 117 728 obiektów Python `datetime` na KAŻDĄ klatkę wideo**!
   - Dla 1 131 klatek: 1 131 × 117 728 = **133 150 368 alokacji**.
   - Dla pełnego filmu (60 000 klatek): **ponad 7 miliardów alokacji**, co blokowało proces w alokatorze pamięci CPython na 15–25 minut!
   - Ponieważ w `telemetry_precompute.py` kolejny `_progress()` był wywoływany dopiero po pętli klatek Lean, interfejs użytkownika zamarzał dokładnie na poprzedniej etykiecie: `Przygotowywanie HUD: heading`.
2. **Próba dynamicznego przypisania atrybutu do obiektu `list`**:
   - Wbudowany typ `list` w Pythonie nie posiada słownika `__dict__`. Próba `roll_samples._naive_times = times` rzucała `AttributeError`, który był cicho ignorowany przez `try...except`, powodując ponowne budowanie listy w każdej iteracji (8.5 ms na pojedynczą klatkę).

---

## 6. Zastosowana naprawa i optymalizacja

1. **Wektoryzacja w `src/telemetry_precompute.py`**:
   - Dodano funkcję `_vectorize_linear_roll()` opartą na `np.interp` (analogicznie do sprawdzonych `_vectorize_linear_speed` i `_vectorize_linear_altitude`).
   - Wektorowe próbkowanie 117 728 punktów dla 1 131 klatek trwa teraz **poniżej 1 milisekundy** (zamiast 26 sekund).
   - Dodano pomiar czasu i log diagnostyczny:
     `[HUD PREP LEAN] stage=lean_vectorize keys=('lean_indicator',) frames=300 elapsed_ms=1.05`
   - Dodano jawny krok postępu `_progress("lean fields")`.
2. **Modułowy cache w `src/telemetry_imu.py`**:
   - Utworzono `_ROLL_TIMES_CACHE: dict[int, tuple[int, Any, Any, list]]` indeksowany po `id(roll_samples)` z weryfikacją długości oraz znaczników czasowych początku i końca.
   - `interpolate_roll()` konwertuje daty do `naive UTC` dokładnie **raz** na cały strumień.
   - Czas 1 131 wywołań spadł z 9 635 ms do **9.31 ms** (ponad 1000x szybciej).
3. **Optymalizacja kafelka rotacji w `src/indicators/lean.py`**:
   - Dodano `_LEAN_ROTATED_PATCH_CACHE = _BoundedStaticCache(max_entries=360)` z kwantyzacją kąta do 0.1°.
   - Zapobiega to powtarzaniu kosztownych transformacji afinicznych `Image.Transform.AFFINE` dla zbliżonych kątów.
   - Zabezpieczono `lean_visual_angle()` przed wartościami `NaN` i `Inf`.

---

## 7. Lean Calibration +6° — architektura i spójność

### Zasada działania
Zgodnie z wymaganiem użytkownika oraz testami akceptacyjnymi:
- Przy `raw = 0.0°` oraz `calibration = +6.0°` kąt wynosi **`+6.0°`**.
- Przy `raw = -6.0°` oraz `calibration = +6.0°` kąt wynosi **`0.0°`**.
- Wzór:
  `calibrated = float(roll) + calibration`
  `angle = calibrated * (-1.0 if invert_axis else 1.0) * sensitivity`
  `angle = _clamp(angle, -max_angle, max_angle)`

### Spójność (Parity)
1. **Wyświetlana wartość liczbowa (`value_text`)**: używa sformatowanego `angle`.
2. **Obrót grafiki (ikona roweru `bike`)**: transformacja afiniczna obraca grafikę o dokładnie ten sam kąt `angle`.
3. **Podgląd (Preview) i Render (Export)**: obie ścieżki wywołują identyczną funkcję `lean_angle(value, cfg)`, co gwarantuje 100% spójność wizualną.
4. **Kompatybilność wsteczna**:
   - Jeśli pole `calibration` nie istnieje w konfiguracji: odczytywane jest starsze pole `zero_offset`.
   - Jeśli brak obu: domyślna wartość to `0.0°`.
   - Dla nowo tworzonych wskaźników Lean oraz domyślnego layoutu użytkownika: ustawiono domyślnie `6.0°`.
   - W `PropertyEditor` (`models.py`) dodano pole: `FieldSchema("calibration", "float", "Kalibracja / Offset [°]", tab="Data", min_val=-90.0, max_val=90.0, step=0.5, default=6.0)`.

---

## 8. Wyniki testów

### A. Obowiązkowy Test Sentinela (`test_sentinel_user_preset_immutability`)
- Utworzono plik: `scratch/user_preset_sentinel.json`.
- Wyliczono SHA256: `9fa733d07ec5e171b32b8fa2f567406a13d8d6f082e6ef2f1cb7ce6ec88f9a26`.
- Wczytano preset do kontrolera aplikacji.
- Wykonano modyfikacje w RAM: zmiana fontu gauge, zmiana pozycji, dodanie wskaźnika Lean z kalibracją +6°.
- Wywołano procedurę renderu i zapis projektu.
- **Wynik**:
  - `scratch/user_preset_sentinel.json` po operacjach: **byte-for-byte identyczny** (SHA256 bez zmian). **PASS**.
  - Zmiany zostały zapisane wyłącznie do pliku roboczego projektu: `test_video.layout.json`. **PASS**.

### B. Testy matematyki kalibracji Lean (`test_lean_calibration_math`)
- `raw 0.0° + calib 6.0° -> 6.0°`: **PASS**.
- `raw -6.0° + calib 6.0° -> 0.0°`: **PASS**.
- `raw 0.0° bez kalibracji -> 0.0°`: **PASS**.
- `legacy zero_offset fallback -> 6.0°`: **PASS**.

### C. Zestaw testów automatycznych
```text
tests/test_layout_ownership_and_lean_calibration.py::test_lean_calibration_math PASSED [ 25%]
tests/test_layout_ownership_and_lean_calibration.py::test_lean_rotation_cache_and_parity PASSED [ 50%]
tests/test_layout_ownership_and_lean_calibration.py::test_lean_hud_prep_vectorized_no_hang PASSED [ 75%]
tests/test_layout_ownership_and_lean_calibration.py::test_sentinel_user_preset_immutability PASSED [100%]
============================== 4 passed in 1.00s ==============================
```
Wszystkie 19 testów z poprzednich zestawów regresyjnych GUI (`test_gui_v5_autosave_preview_and_aa.py`, `test_gui_v4_fullscreen_and_next_frame.py`, `test_gui_v3_runtime_acceptance.py`) przeszło bez błędów.

---

## 9. Benchmark HUD prep before/after

### Przygotowanie HUD (HUD Preparation) na `GX010115.MP4` z włączonym Lean (117 728 próbek IMU):

| Parametr | Przed optymalizacją | Po optymalizacji | Poprawa |
|---|---|---|---|
| **Pętla klatek Lean (1 131 klatek)** | 26 523 ms (~26.5 s) | **0.96 ms** | **27 600x szybciej** |
| **Kroki dla 60 000 klatek (pełny film)** | ~1 400 s (~23.5 minuty hang) | **~50 ms** | **Eliminacja zawieszenia** |
| **Pojedyncza interpolacja roll** | 8.519 ms / call | **0.0082 ms / call** | **1 038x szybciej** |
| **Czas przygotowania całego HUD (300f)** | Hang / Freeze | **0.866 s** | **Płynne przejście** |

---

## 10. Prawdziwy Smoke Test Produkcyjny (300 klatek, GX010115 + GX010114_116.fit)

Wykonano rzeczywisty render produkcyjny na natywnej ścieżce AMD D3D11/AMF:
- Materiał wideo: `Video/GX010115.MP4` (3840×2160 @ 59.94 fps).
- FIT: `Video/GX010114_116.fit` (autorytatywny plik z `BENCHMARKS.md`).
- Preset: `presets/cycling_dashboard_v10.json` + `lean_indicator` (graphic: bike, calibration: +6.0°).

### Log z przebiegu:
```text
================================================================================
SMOKE TEST: 300 frames AMD_NATIVE_D3D11 with LEAN ON
Video: Video\GX010115.MP4
FIT:   Video\GX010114_116.fit
Preset:presets\cycling_dashboard_v10.json
================================================================================
[1/3] Loading GPMF telemetry from video...
[2/3] Loading FIT telemetry...
[3/3] Starting export_amd_native_d3d11 for 300 frames...
[AMD DIRECT MUX] mode=single clips=1 video=pipe audio=source output=.part
[HUD PREP LEAN] stage=lean_vectorize keys=('lean_indicator',) frames=300 elapsed_ms=1.05
[FONT RESOLVER] requested='arial.ttf' -> resolved='C:\Windows\Fonts\arial.ttf'
...
=== RENDER COMPLETE ===
Frames: 300
HUD prepare: 0.866 s
Video encode: 7.028 s
Finalize: 0.008 s
Total: 8.421 s
Render FPS: 42.687
Effective FPS: 35.627
COMPLETED 300 FRAMES IN 8.43 s, result = True
```
- Wygenerowano poprawny plik MP4 (300 klatek w 4K, 35.6 FPS).
- Wyekstrahowano klatkę testową `scratch/smoke_lean_out/frame_150.png` — ikona roweru jest wyrenderowana z poprawnym obrotem i odczytem stopni.

---

## 11. Bezpieczeństwo backendów (Backend Isolation)

- **AMD (`AMD_NATIVE_D3D11`)**: Wszystkie domyślne ścieżki produkcyjne (`AMD_GPU_MAP_ROTATE`, `AMD_AFTER_MAP_CHART_GPU`, `AMD_AFTER_MAP_GAUGE_GPU`) pozostały nienaruszone.
- **Intel / NVIDIA**: Żadne pliki specyficzne dla Intela (QSV) ani NVIDIA (NVENC/CUDA) nie były modyfikowane. Wprowadzone zmiany dotyczą wyłącznie modułów telemetrycznych (`telemetry_imu.py`, `telemetry_precompute.py`, `indicators/lean.py`) oraz warstwy GUI/presetów.

---

## 12. Zmienione pliki

1. `src/gui/qt/_mixins/preset_mixin.py`:
   - Przywrócono Save File Dialog w `_on_save_preset`.
   - Zabezpieczono wczytany `_user_preset_path` jako read-only.
   - Dodano `get_project_layout_path()` oraz `_save_project_layout()` dla roboczego stanu filmu (`video.layout.json`).
   - W `_on_property_changed()` zapis kierowany jest wyłącznie do pliku roboczego projektu.
2. `src/gui/qt/_mixins/project_mixin.py`:
   - Wczytywanie filmu sprawdza w pierwszej kolejności `video_path.with_suffix(".layout.json")`.
3. `src/gui/qt/_mixins/render_mixin.py`:
   - Usunięto zapis do `def_layout.json` przy starcie renderu; zastąpiono wywołaniem `self._save_project_layout()`.
4. `src/gui/qt/widgets/data_stream_bar.py`:
   - Usunięto zbędny przycisk `save_settings_btn` („Zapisz ustawienia”) powodujący konfuzję persistence.
5. `src/telemetry_imu.py`:
   - Zoptymalizowano `interpolate_roll()` — dodano buforowanie znormalizowanych czasów `_ROLL_TIMES_CACHE`, eliminując 100 000+ alokacji na klatkę.
6. `src/telemetry_precompute.py`:
   - Dodano wektorową interpolację `_vectorize_linear_roll()` z użyciem `np.interp`.
   - Dodano log diagnostyczny `[HUD PREP LEAN]` i krok `_progress("lean fields")`.
   - Zabezpieczono `_vectorize_linear_distance` przed nie-skalarnymi współrzędnymi trasy.
7. `src/indicators/lean.py`:
   - Zaktualizowano `lean_visual_angle()` do formuły `(roll + calibration) * invert * sensitivity` z obsługą `calibration` (fallback `zero_offset`).
   - Dodano `_LEAN_ROTATED_PATCH_CACHE` dla transformacji afinicznych grafiki.
   - Zabezpieczono przed wartościami `NaN` i `Inf`.
8. `src/gui/qt/models.py`:
   - Zaktualizowano schemat wskaźnika Lean o `FieldSchema("calibration", ... default=6.0)`.
9. `src/gui/qt/_mixins/indicator_mixin.py`:
   - Ustawiono domyślną kalibrację `6.0°` dla nowo tworzonych wskaźników Lean.
10. `tests/test_layout_ownership_and_lean_calibration.py`:
    - Nowy zestaw testów weryfikujący niezmienność presetu użytkownika (sentinel), matematykę kalibracji i szybkość HUD prep.

---

## 13. Podsumowanie PASS/FAIL

| Wymaganie | Stan | Dowód / Komentarz |
|---|---|---|
| **User Preset Save As contract** | **PASS** | `QFileDialog.getSaveFileName` pyta o miejsce i nazwę |
| **User Preset Immutability** | **PASS** | Potwierdzone testem sentinela (hash SHA256 identyczny po edycji i renderze) |
| **Project-local layout (.layout.json)** | **PASS** | Tworzony automatycznie przy wideo, przywracany przy ponownym otwarciu |
| **Usunięcie autosave do def_layout z renderu** | **PASS** | `render_mixin.py` zapisuje wyłącznie do `.layout.json` |
| **Diagnoza i usunięcie hang HUD prep** | **PASS** | Wektoryzacja `_vectorize_linear_roll` skróciła czas z 26 s / hang do 1.05 ms |
| **Lean calibration +6° math** | **PASS** | `0° -> 6°`, `-6° -> 0°`, backward compat: brak pola `-> 0.0°` |
| **Spójność kąta i obrotu ikony roweru** | **PASS** | Odczyt tekstu i kąt ikony roweru używają tego samego `calibrated angle` |
| **Prawdziwy smoke render 300f 4K AMD** | **PASS** | `GX010115.MP4` + `GX010114_116.fit` ukończone w 8.42 s (42.7 FPS) |
| **Brak regresji pozostałych ścieżek** | **PASS** | Wszystkie testy regresyjne v3, v4, v5 przeszły pomyślnie |
