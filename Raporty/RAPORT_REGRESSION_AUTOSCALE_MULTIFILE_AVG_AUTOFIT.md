# Raport: Naprawa 3 Regresji TeleM (Autoscale, Multi-file Avg Speed, AutoFIT Pre-load)

**Data:** 2026-09-06  
**Autor:** Antigravity  
**Gałąź:** `integration/intel-amd`  
**Bazowy commit:** `59277b4`  

---

## 1. Cel zadania

Naprawa 3 realnych regresji w aplikacji TeleM bez ingerencji w map perspective/tilt, natywny parser GPMF, TMPC, schemat NPZ ani dedykowane backendy GPU (Intel/AMD):

1. **Problem 1 (Universal Autoscale Min/Max):** Automatyczne wyznaczanie zakresu `[min, max]` z rzeczywistego wybranego źródła (GPMF, FIT, GPX) dla wszystkich form wskaźników operujących na przedziałach (`bar` poziomy/pionowy segments i ruler, `gauge`, `chart`), dynamiczne pola FIT, skalowanie dystansu w km (`/ 1000.0`), fallback do wartości z layoutu tylko przy braku danych.
2. **Problem 2 (Multi-file Avg Speed Preview Parity):** Przeliczanie średniej prędkości w projektach multi-file (2+ MP4 + FIT) w oparciu o absolutny znacznik czasu `target_dt` i zegar aktywności `ActiveTimeMapper` (skumulowany dystans aktywności / skumulowany aktywny czas timera). Przerwy w nagrywaniu (MP4 gap) != pauza FIT (gdy timer zatrzymany -> czas zamrożony; gdy timer biegł -> czas aktywny narasta). Pełna identyczność typu float pomiędzy Preview, Precompute i Final Render.
3. **Problem 3 (AutoFIT Visible Before Load):** Natychmiastowe uruchomienie lekkiego skanowania w tle przy wyborze plików MP4, automatyczne wypełnienie pola ścieżki FIT/GPX w GUI przed kliknięciem „Wczytaj”, ochrona przed nadpisaniem ręcznego wyboru oraz ochrona przed wyścigiem (stale request generation id).

---

## 2. Stan początkowy i diagnoza problemów

### Problem 1: Autoscale min/max
- W GUI pole `auto_scale` nie było eksponowane dla formy `gauge` oraz `chart`.
- Logika wyliczania min/max w `compositor.py` posiadała twarde nadpisania dla wybranych kluczy GPMF (`speed_visual`, `dist_visual`), ignorując konfigurację źródła (`source: fit`) oraz inne typy wskaźników (`hr`, `cad`, `power`, `temp`, dynamiczne pola FIT).
- Brakowało uniwersalnej funkcji wyznaczającej rzeczywisty zakres z całego aktywnego datasetu dla wszystkich wskaźników z włączonym `auto_scale`.

### Problem 2: Multi-file Avg Speed w Preview
- W `_render_preview()` (`preview_mixin.py`) jako `project_elapsed_s` przekazywany był skompresowany czas w osi wideo (`global_time`).
- W projektach z przerwami między klipami MP4 (`gap`), `global_time` nie uwzględniał czasu trwania aktywności FIT ani przerw między plikami.
- Gdy komputer rowerowy (FIT) rejestrował przejazd podczas przerwy w nagrywaniu kamerą, średnia prędkość w podglądzie była zniekształcona w stosunku do precompute i final render.

### Problem 3: AutoFIT po załadowaniu wideo
- Wyszukiwanie AutoFIT uruchamiało się dopiero w trakcie kliknięcia „Wczytaj” (`_on_load` / `_start_loading`), przez co użytkownik nie widział, jaki plik został dobrany przed rozpoczęciem importu.
- Przy próbie asynchronicznego uruchomienia skanowania, wywołanie `QTimer.singleShot` z poziomu wątku pythonowego `threading.Thread` nie docierało do pętli zdarzeń Qt w wątku głównym, blokując aktualizację kontrolki `btn_telemetry`.

---

## 3. Zastosowane zmiany w kodzie

### 1. `src/gui/qt/models.py`
- Dodano `FieldSchema("auto_scale", "bool", "Auto skala (zakres z danych)", tab="Ticks", default=False)` do schematu pól ticks dla kontrolek z zakresem (`with_range=True`), eksponując opcję w GUI dla wskaźników typu `gauge` i `chart`.

### 2. `src/indicators/frame_data.py`
- Zaimplementowano uniwersalną funkcję `compute_indicator_auto_ranges(layout, ...)`:
  - Analizuje wskaźniki w layoucie z `auto_scale=True`, `auto_min=True` lub `auto_max=True`.
  - Ustala właściwe źródło danych (`fit`, `gpx`, `gpmf`) oraz właściwą serię próbek.
  - Obsługuje wszystkie strumienie: prędkość, dystans, wysokość, tętno, kadencja, moc, temperatura, nachylenie, kierunek, ISO, migawka oraz dowolne rozszerzone pola FIT.
  - Dla strumieni dystansu przelicza metry na kilometry (`/ 1000.0`), gdy jednostką jest `km`.
  - Zwraca słownik `dict[indicator_key, tuple[min_val, max_val]]`.
- Zintegrowano wyliczanie w `prepare_overlay_frame_data()` z buforowaniem w `_range_cache["auto_ranges"]`.

### 3. `src/indicators/compositor.py`
- Rozszerzono `is_range_form` o `"gauge"` i `"chart"`:
  ```python
  is_range_form = current_cfg.get("form") in ("bar", "ruler", "gauge", "segment_bar", "chart")
  ```
- Wdrożono czyste nadpisywanie zakresu: gdy włączone jest `auto_scale` i wyznaczono przedział w `auto_ranges`, aplikowane są dokładnie zmierzone `min_val` i `max_val` bez twardych ograniczeń specyficznych dla GPMF. W przypadku braku próbek zachowywane są wartości fallback skonfigurowane w layoucie.

### 4. `src/telemetry_precompute.py` & `src/ffmpeg/worker_cache.py`
- Dodano pole `auto_ranges` do struktury `_Static` oraz do `WORKER_CACHE`.
- Obliczanie zakresów odbywa się raz na początku budowy cache (`build_telemetry_cache`) i jest zwracane w słowniku `lookup()` dla każdej klatki bez narzutu na gorącą ścieżkę renderera.

### 5. `src/ffmpeg/frame_renderer.py`
- Zapewniono przekazywanie `auto_ranges` do `compose_overlay` zarówno w ścieżce głównej precompute, jak i w ścieżce fallback workera.

### 6. `src/multifile.py`
- Dodano metodę `global_to_activity_elapsed(global_time: float) -> float` do klasy `VideoTimeline`, mapującą czas globalny wideo na czas aktywności z uwzględnieniem lokalnych przesunięć i przerw.

### 7. `src/gui/qt/_mixins/preview_mixin.py`
- W `_build_prepare_cache()` dodano wywołanie `compute_indicator_auto_ranges` i zapisanie do `self._prepare_cache["auto_ranges"]`.
- W `_render_preview()` przekazywany `project_elapsed_s` jest wyliczany za pomocą `self.video_timeline.global_to_activity_elapsed(global_time)`, zapewniając pełną spójność ze stanem faktycznym aktywności.

### 8. `src/gui/qt/tabs/load_tab.py`
- Wprowadzono dedykowany sygnał Qt: `sig_autofit_matched = Signal(str, int)`.
- Sygnał jest podłączony w `_connect_local_signals()` do metody `_on_autofit_matched(fit_path, gen)`, która bezpiecznie aktualizuje `btn_telemetry` i `_fit_path` w głównym wątku GUI.
- Dodano licznik generacji `self._autofit_gen: int = 0`. Przy każdym wyborze MP4 generacja jest inkrementowana.
- Wyniki asynchronicznego skanowania z wątku tła są akceptowane wyłącznie wtedy, gdy `request_gen == self._autofit_gen` oraz użytkownik nie wybrał uprzednio pliku ręcznie (`not self._user_selected_telemetry`).
- W `_on_clear()` stan jest czyszczony, a generacja inkrementowana.

---

## 4. Testy i weryfikacja

Wszystkie scenariusze zostały zweryfikowane automatycznymi testami jednostkowymi i integracyjnymi.

### A. Testy Auto-scale (`tests/test_indicator_auto_scale.py`)
- `test_autoscale_synthetic_samples_min_max`: weryfikacja wyznaczenia min=12.0, max=44.0 z próbek.
- `test_autoscale_source_switch_gpmf_to_fit`: weryfikacja zmiany zakresu po przełączeniu źródła z GPMF na FIT.
- `test_autoscale_all_indicator_forms`: parametryczny test dla form:
  - `bar` segments poziomy,
  - `bar` segments pionowy,
  - `bar` ruler poziomy,
  - `bar` ruler pionowy,
  - `gauge`,
  - `chart`.
- `test_autoscale_distance_scaling_to_km`: weryfikacja przeliczenia 0..24000 m na 0..24.0 km.
- `test_autoscale_fallback_when_no_data`: weryfikacja bezpiecznego zachowania wartości z layoutu w przypadku braku danych.
**Wynik: 10/10 PASSED**

### B. Testy Multi-file Avg Speed & Parity (`tests/test_multifile_avg_speed.py`)
- `test_multifile_preview_avg_respects_fit_pause`:
  - Klip 1: 10:00-10:10 (600s). Pauza FIT w luce: 10:10-10:20 (600s). Klip 2: 10:20-10:30 (600s).
  - Aktywny czas timera: 1200s (20 min).
  - Średnia prędkość (10 km / 1200 s) = 30.0 km/h.
- `test_multifile_preview_avg_keeps_running_without_fit_pause`:
  - Klip 1: 10:00-10:10 (600s). Brak pauzy FIT w luce 10:10-10:20 (komputer rejestrował). Klip 2: 10:20-10:30 (600s).
  - Aktywny czas timera: 1800s (30 min).
  - Średnia prędkość (10 km / 1800 s) = 20.0 km/h.
- `test_multifile_preview_precompute_real_dataset_parity`:
  - Test na kanonicznym zestawie benchmarkowym `Video/GX010114.MP4`, `Video/GX010115.MP4`, `Video/GX010114_116.fit`.
  - Punkt w Klipie 2 (10s po rozpoczęciu klipu 2):
    - `preview active_elapsed`: 1969.262303 s
    - `precompute elapsed_seconds`: 1969.262303 s
    - Różnica czasu aktywnego: `< 1e-9 s`
    - Różnica `avg_speed_kmh`: `< 1e-9 km/h` (**Ścisła identyczność typu float**)
**Wynik: 3/3 PASSED**

### C. Testy AutoFIT Pre-load (`tests/test_autofit_pre_load.py`)
- `test_autofit_pre_load_auto_populates_ui`: weryfikacja natychmiastowego wypełnienia pola `btn_telemetry` i `_fit_path` przez wątek tła przed kliknięciem „Wczytaj”.
- `test_autofit_stale_generation_rejected`: weryfikacja odrzucenia wyników dla starego zapytania po szybkiej zmianie pliku przez użytkownika.
- `test_autofit_user_manual_selection_preserved`: weryfikacja nienaruszalności ręcznie wybranego pliku FIT przy późniejszym wskazaniu MP4.
- `test_autofit_clear_resets_state`: weryfikacja czyszczenia stanu po kliknięciu „Wyczyść”.
**Wynik: 4/4 PASSED**

### D. Zbiorczy pakiet regresyjny
Uruchomiono pełny pakiet 43 testów (`tests/test_indicator_auto_scale.py`, `tests/test_multifile_avg_speed.py`, `tests/test_autofit_pre_load.py`, `tests/test_activity_ux_timeline.py`):
```text
============================= 43 passed in 15.65s =============================
```

---

## 5. Izolacja backendów i bezpieczeństwo

- Żadne zmiany nie dotknęły potoków Intel, AMD D3D11/AMF ani NVIDIA NVENC.
- Brak modyfikacji schematu NPZ, formatu klatek ani operacji na bazie gita.
- Zachowano pełną zgodność wsteczną presetów i layoutów.

---

## 6. Podsumowanie werdyktów (PASS / FAIL)

```text
GLOBAL AUTOSCALE: PASS
MULTIFILE AVG FIT PAUSES: PASS
MULTIFILE PREVIEW FINAL PARITY: PASS
AUTOFIT BEFORE LOAD: PASS
FIT FIELD AUTO-POPULATE: PASS
```
