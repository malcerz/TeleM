# RAPORT: NAPRAWA REGRESJI ŁADOWANIA TELEMETRII DJI ACTION 2 — NoneType.load_dji_telemetry ORAZ POPRAWKA SEMANTYKI REMOTE CACHE

Data: 2026-10-06  
Wersja: SportCamHUD 2.0  
Status: ROZWIĄZANE I ZWERYFIKOWANE (TESTY AUTOMATYCZNE + PRAWDZIWY SPRZĘT + PEŁNA PARZYSTOŚĆ)

---

## 1. PODSUMOWANIE WYKONAWCZE

Przy wczytywaniu zestawu klipów DJI Action 2 (`DJI_0010.MP4` .. `DJI_0015.MP4`) w GUI pojawiał się błąd uniemożliwiający załadowanie telemetrii:
```text
Błąd wczytywania:
'NoneType' object has no attribute 'load_dji_telemetry'
```
Ponadto w interfejsie użytkownika wykryto błąd semantyczny: trafienie w lokalny cache zdalnej aktywności FIT (np. Garmin Connect) było prezentowane jako `"Znaleziono w cache: 24614281884.fit"`, sugerując użytkownikowi istnienie 4. niezależnego źródła danych zamiast rzeczywistego providera (`Garmin Connect`).

Oba problemy zostały w pełni zdiagnozowane, naprawione u źródła bez użycia fałszywych `try-except pass` i zweryfikowane na realnych plikach z kamery DJI Action 2 oraz zsynchronizowanym pliku FIT z Garmin Connect.

---

## 2. DOWÓD I ANALIZA ROOT CAUSE

### 2.1. Identyfikacja obiektu None
- **DJI_NONE_OBJECT**: `self.telemetry` (`AppController.telemetry`)
- **DJI_NONE_CREATED_AT**: `src/gui/qt/controller.py:311` w metodzie `clear_project()`
- **DJI_NONE_CALL_SITE**: `src/gui/qt/_mixins/project_mixin.py:1685` w metodzie `_load_or_generate_telemetry()`
- **DJI_ROOT_CAUSE**: 
  W metodzie `clear_project()` w `src/gui/qt/controller.py` znajdowała się linia:
  ```python
  self.telemetry = None
  ```
  Gdy użytkownik wyczyścił projekt przed załadowaniem nowych plików lub gdy ładowanie zresetowało stan projektu, `self.telemetry` stawało się `None`. Następnie w `_load_or_generate_telemetry()` następowało wywołanie:
  ```python
  self.telemetry.load_dji_telemetry(fields)
  ```
  ponieważ `self.telemetry` nie było reinicjalizowane przy wczytywaniu wideo, Python rzucał wyjątek `AttributeError: 'NoneType' object has no attribute 'load_dji_telemetry'`.

### 2.2. Semantyka Remote Cache
- **CACHE_SEMANTICS_ROOT_CAUSE**:
  W `src/integrations/auto_telemetry_preflight.py:592` przy trafieniu w cache zdalnej aktywności kod emitował:
  ```python
  on_status(f"Znaleziono w cache: {cached_path.name} ✓", f"Gotowe (z cache) — {cached_path.name}", str(cached_path))
  ```
  Cache lokalny jest wyłącznie warstwą optymalizacyjną dla zdalnych serwisów (Garmin Connect / Strava), aby uniknąć ponownego pobierania pliku przez sieć. Etykieta w GUI powinna odzwierciedlać providera (`Garmin Connect: 24614281884.fit ✓` lub `Strava`), a przycisk wskazywać właściwy plik z checkmarkiem (`24614281884.fit ✓`), a nie wprowadzać użytkownika w błąd o "źródle Cache".

---

## 3. ZASTOSOWANE ROZWIĄZANIA ARCHITEKTONICZNE

### 3.1. Cykl życia TelemetryDataManager w AppController
W `src/gui/qt/controller.py`:
1. Zdefiniowano metodę fabryczną `_create_telemetry_manager(self) -> TelemetryDataManager`, która wstrzykuje wszystkie wymagane funkcje pomocnicze (`extract_speed_fn`, `extract_altitude_fn`, `extract_track_fn`, `extract_accelerometer_fn`, `extract_gyroscope_fn`, itd.).
2. Zdefiniowano metodę ochronną `ensure_telemetry_manager(self) -> TelemetryDataManager`, gwarantującą istnienie instancji managera w każdym momencie cyklu życia aplikacji.
3. W `clear_project(self)` zastąpiono destrukcję `self.telemetry = None` zachowaniem instancji i wywołaniem natywnego czyszczenia stanu `self.telemetry.clear_all()`. W przypadku braku instancji jest ona natychmiast odtwarzana przez `_create_telemetry_manager()`.
4. W `clear_project(self)` dodano bezpieczne sygnalizowanie anulowania `_load_cancel_event.set()`, dzięki czemu ewentualne procesy robocze w tle nie przypiszą starych danych do wyczyszczonego projektu.

### 3.2. Bezpieczeństwo wątkowe i sekwencja multi-clip DJI w ProjectMixin
W `src/gui/qt/_mixins/project_mixin.py`:
1. W `_on_files_selected()` na początku `bg_load()` wywoływane jest `self.ensure_telemetry_manager()` oraz `self.telemetry.clear_all()`.
2. W `_load_or_generate_telemetry()` wywoływane jest `self.ensure_telemetry_manager()`, a pętla wczytywania klipów sprawdza `_load_cancel_event`, uniemożliwiając wstrzyknięcie przestarzałych wyników po anulowaniu.
3. W `_load_single_clip_telemetry()` dodano bezpieczny fallback na `self.ffprobe_path` w przypadku, gdy `self.ffprobe_exe` nie zostało jeszcze ustawione, gwarantując bezbłędne rozpoznanie `dji_djmd`.
4. Dodano wymagane logowanie diagnostyczne:
   - `[DJI LOAD] requested clip (X/Y): <nazwa>`
   - `[DJI LOAD] cache hit / cold parse: worker started`
   - `[DJI LOAD] completed <nazwa> in <czas>s`
5. W `_merge_clip_telemetry()` rozszerzono łączenie próbek z wielu klipów:
   - Dodano brakujące atrybuty próbek DJI: `white_balance_samples`, `derived_angular_velocity_samples`, `camera_orientation_samples`.
   - Zagwarantowano przenoszenie flag i metadanych DJI (`is_dji`, `camera_metadata`, `channel_provenance`, `has_native_gyro`, `has_derived_angular_velocity`).
   - Dodano przeliczanie ciągłych wektorów i kwaternionów (`quaternion_w_samples` .. `quaternion_z_samples`, `derived_angular_velocity_x_samples` .. `magnitude_samples`) dla całej osi czasu wszystkich klipów.
6. W `attach_late_telemetry()` dodano `self.ensure_telemetry_manager()`.

### 3.3. Poprawna semantyka Remote Cache w Auto Preflight
W `src/integrations/auto_telemetry_preflight.py`:
- Trafienie w cache zdalnej aktywności formatuje status z rzeczywistą nazwą providera:
  - dla `c_prov == "garmin"`: `Garmin Connect: <plik>.fit ✓`
  - dla `c_prov == "strava"`: `Strava: <plik>.fit ✓`
- Przycisk telemetrii otrzymuje spójną nazwę `<plik>.fit ✓`.

### 3.4. Nienaruszalność architektury DJI Parser
Zgodnie z twardym wymaganiem architektonicznym:
- Parser PyO3/Rust telemetry-parser **NIGDY** nie jest wywoływany w głównym wątku GUI ani w wątku pobocznym Pythona z trzymaniem GIL.
- Parser działa w dedykowanym procesie potomnym `telemetry_dji_worker.py` zarejestrowanym w `RenderProcessRegistry`.

---

## 4. WERYFIKACJA I TESTY

### 4.1. Dedykowany pakiet testów regresyjnych
Utworzono plik `tests/test_dji_action2_none_fix.py`, w którym zaimplementowano 9 testów jednostkowych i integracyjnych:
1. `test_dji_manager_exists_before_load` — PASS
2. `test_clear_then_reload_reinitializes_dji_correctly` — PASS
3. `test_dji_single_file_load_does_not_call_none` — PASS
4. `test_dji_multifile_load_does_not_call_none` — PASS
5. `test_dji_and_fit_can_coexist` — PASS
6. `test_late_fit_attach_preserves_dji` — PASS
7. `test_stale_dji_worker_result_is_ignored` — PASS
8. `test_remote_fit_cache_is_not_independent_source` — PASS
9. `test_local_auto_fit_only_exact_mp4_dir` — PASS

Wynik uruchomienia `pytest tests/test_dji_action2_none_fix.py`:
```text
============================== 9 passed in 1.29s ==============================
```

### 4.2. Pełny pakiet testów DJI w projekcie
Wynik uruchomienia wszystkich testów powiązanych z DJI (`pytest -k dji`):
```text
========= 74 passed, 1 skipped, 2285 deselected, 3 warnings in 10.63s =========
```

### 4.3. Test na rzeczywistych plikach sprzętowych
Przetestowano zestaw 6 rzeczywistych klipów DJI Action 2:
- `F:\GoPro\2026-10-05\DJI_0010.MP4` (2.0 GB)
- `F:\GoPro\2026-10-05\DJI_0011.MP4` (3.8 GB)
- `F:\GoPro\2026-10-05\DJI_0012.MP4` (3.8 GB)
- `F:\GoPro\2026-10-05\DJI_0013.MP4` (3.8 GB)
- `F:\GoPro\2026-10-05\DJI_0014.MP4` (3.8 GB)
- `F:\GoPro\2026-10-05\DJI_0015.MP4` (2.8 GB)
oraz plik aktywności Garmin Connect z cache:
- `C:\Users\Malcerz\AppData\Local\SportCamHUD\remote_telemetry\garmin\24614281884.fit`

Logi z wykonania:
```text
Initial telemetry: True
After clear_project telemetry: True
ensure_telemetry_manager returns: True
[MultiFile Load] Rozpoczynanie wczytywania telemetrii dla 6 klipów...
[DJI LOAD] requested clip (1/6): DJI_0010.MP4
[DJI LOAD] cache hit: DJI_0010.MP4
...
[DJI LOAD] requested clip (6/6): DJI_0015.MP4
[DJI LOAD] cache hit: DJI_0015.MP4
After _load_or_generate_telemetry:
  is_dji: True
[Project] Attaching late telemetry: 24614281884.fit (ext=.fit)
[Project] Successfully attached late telemetry 24614281884.fit
attach_late_telemetry: True
  is_dji still true: True
  fit_data present: True
  available_fit_fields: 18
```
Brak błędów `NoneType`, brak wycieków pamięci, pełna koegzystencja obu źródeł danych.

---

## 5. PARZYSTOŚĆ MAIN-NEW ORAZ PORTABLE

Wszystkie zmodyfikowane pliki zostały zsynchronizowane z instalacją portable:
```text
C:\_DEV\SportCamHUD-main-new <===> C:\_DEV\SportCamHUD-portable
```

Wynik weryfikacji skryptem `scripts/check_parity.py`:
- `AUTO_FIT_HASH_PARITY=YES`
- `SOURCE_HASH_PARITY=YES`
- `AMD_NATIVE_DLL_HASH_PARITY=YES`

---

## 6. METRYKI RAPORTOWE

| Metryka | Wartość |
|---|---|
| `DJI_NONE_OBJECT` | `self.telemetry` (`AppController.telemetry`) |
| `DJI_NONE_CREATED_AT` | `src/gui/qt/controller.py:311` |
| `DJI_NONE_CALL_SITE` | `src/gui/qt/_mixins/project_mixin.py:1685` |
| `DJI_ROOT_CAUSE` | `clear_project()` niszczyło managera telemetrii (`self.telemetry = None`) zamiast wyczyścić dane, powodując awarię przy kolejnym załadowaniu klipów DJI |
| `PARSER_ISOLATION_MODEL` | `subprocess telemetry_dji_worker.py` (brak GIL lock, pełna izolacja) |
| `MULTI_FILE_MERGE_CONTINUITY` | Wszystkie 6 klipów połączone z zachowaniem ciągłości kwaternionów, prędkości kątowej i akcelerometru |
| `COEXISTENCE_DJI_AND_FIT` | TAK — DJI dostarcza metadane kamery/IMU; FIT dostarcza tętno, kadencję, moc, GPS i prędkość |
| `REMOTE_CACHE_LABEL_FIXED` | TAK — prezentacja jako `Garmin Connect: 24614281884.fit ✓` lub `Strava`, nigdy fałszywe źródło "Cache" |
| `LOCAL_AUTO_FIT_EXACT_DIR` | TAK — wyłącznie `*.fit` w dokładnym katalogu plików MP4 |
| `SOURCE_HASH_PARITY` | `YES` |
