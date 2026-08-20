# TeleM — RAPORT NVIDIA ETAP 5B.2: REGRESJA UCINANIA WYKRESÓW

**Data:** 2026-08-20  
**Środowisko:** Windows 11, NVIDIA GeForce RTX 5070 Ti 16 GB, Driver 610.62, CUDA 13.3, FFmpeg 8.1.1  
**Materiał testowy / Reproduktor:** `Video/GX030120.MP4` (5400 klatek, 29.97 FPS, 180.18 s) + `Video/GX030120.json` + `Video/Poranna_jazda_na_rowerze.fit`  
**Layout:** Produkcyjny `def_layout.json` z wykresami `fit_cadence_text` i `fit_heart_rate_text`  
**Cel ETAPU 5B.2:** Zdiagnozowanie i usunięcie regresji ucinania wykresów telemetrycznych.  
**Autor:** Antigravity AI  

---

## A. Reprodukcja problemu

Problem został odtworzony na materiale produkcyjnym `GX030120.MP4` (5400 klatek, GPS anchor `2026-08-18 04:46:25.7`) z plikiem `Poranna_jazda_na_rowerze.fit` (1672 punkty, zakres `04:29:39` – `04:57:30`).

**Objaw:**  
Wykresy telemetryczne (`fit_cadence_text`, `fit_heart_rate_text`) były generowane jako płaska linia / 2 punkty o stałej wartości lub gwałtownie ucięte pionowe ściany, zamiast pełnej krzywej historii aktywności.

---

## B. PRECOMPUTE OFF vs ON

Podczas analizy izolacyjnej porównano dane dostarczane do `compose_overlay`:

| Tryb | Liczba punktów `fit_cadence_text` | Liczba punktów `fit_heart_rate_text` | Zakres czasowy wykresu | Wizualny stan wykresu |
| :--- | :---: | :---: | :---: | :---: |
| **PRECOMPUTE OFF (Live)** | 1672 próbek | 1672 próbek | `04:29:39` – `04:57:30` | **Pełna historia aktywności** |
| **PRECOMPUTE ON (Błąd)** | **0 próbek** (`[]`) | **0 próbek** (`[]`) | `None` – `None` | **Ucięty / brak historii (fallback do 2 punktów)** |

---

## C. Chart Data Parity & Analiza Źródeł

Prześledzono przekazywanie `chart_data`:
1. `build_chart_data()` wymaga dwóch funkcji pomocniczych:
   - `get_samples_fn(src) -> (speed, track, alt)`
   - `resolve_samples_fn(field_name, source, indicator_key) -> list[tuple[datetime, float]]`
2. W `src/ffmpeg/streaming.py` (linia 637) przekazywano:
   - `_get_src_samples`, który zwracał pojedynczą listę `list` zamiast krotki 3 list `(speed, track, alt)`.
   - `_resolve_cache_samples` importowane z `worker_cache.py`, które odczytywało `WORKER_CACHE["fit_data"]`.
3. Ponieważ `streaming.py` wykonuje prekomputację w wątku głównym **przed** startem workerów, `WORKER_CACHE` na procesie głównym było puste (`{}`).
4. W efekcie `_resolve_cache_samples` zwracało `[]` dla wszystkich pól FIT, a `build_telemetry_cache` zapisało pusty słownik `chart_data = {}` do obiektu `_Static`.
5. Podczas renderowania klatek worker otrzymywał z `telemetry_cache.lookup()` pusty słownik `chart_data`.

---

## D. Cadence & Heart-Rate History Analysis

Przeanalizowano również moduł `src/indicators/chart_builder.py`:
- W `build_chart_data()` dopasowanie pól wskaźników FIT znajdowało się w bloku `else:` na samym końcu łańcucha `if/elif`.
- Wskaźnik `fit_cadence_text` był przechwytywany przez warunek `elif "cad" in ind_key:`, który wywoływał `resolve_samples_fn("cad", src, ind_key)` ze skróconym aliasem `"cad"` zamiast właściwej nazwy pola FIT `"cadence"`.
- Podobnie `fit_heart_rate_text` był wywoływany ze skrótem `"hr"` zamiast `"heart_rate"`.

---

## E. Local Chart Raster & Geometria Plotu

Sprawdzono lokalny raster generowany przez `_render_chart_indicator()` oraz `generate_history_chart()`:
- `chart_w = 576 px` (30% z 1920 px), `chart_h = 230 px`
- Marginesy osi: `axis_left = 68 px`, `axis_right = 18 px`, `axis_top = 16 px`, `axis_bottom = 46 px`
- Obszar kreślenia: `plot_x1 = 68`, `plot_y1 = 16`, `plot_x2 = 558`, `plot_y2 = 184`
- Polyline i punkty mieszczą się w 100% wewnątrz `[plot_x1, plot_x2]`.
- Zamknięcie wielokąta `fill_polygon` następuje poprawnie w `(points[-1][0], plot_y2)` i `(points[0][0], plot_y2)` na linii bazowej osi X.

---

## F. Compositor Geometry

W `src/indicators/compositor.py`:
- `render_value_indicator()` zwraca `(res_image, center_x, center_y, extra)`
- Obraz jest wklejany przez `rotated_paste()` o środku `(center_x, center_y)`.
- Brak jakiegokolwiek przycinania w compositorze — cały bufor o rozmiarze `584×270` jest wklejany na canvas `1920×1080`.

---

## G. Preview vs CPU RGBA vs NVIDIA RGBA vs HEVC

| Etap potoku | Stan danych wykresu | Wynik wizualny |
| :--- | :---: | :---: |
| **GUI Preview (hud_tuner_app)** | Poprawne `chart_data` | **Pełny wykres (brak ucięcia)** |
| **CPU RGBA (prepare_overlay_frame_data)** | Poprawne `chart_data` | **Pełny wykres (brak ucięcia)** |
| **NVIDIA Precompute (Przed poprawką)** | **Puste `chart_data = {}`** | **UCIĘTY / PŁASKA LINIA (BŁĄD)** |
| **NVIDIA Precompute (Po poprawce)** | Poprawne `chart_data` (1672 pts) | **Pełny wykres (brak ucięcia)** |
| **Final Decoded HEVC (Po poprawce)** | Poprawne klatki RGBA | **Pełny wykres (brak ucięcia)** |

---

## H. Root Cause (Klasyfikacja błędu)

> **Klasyfikacja:** **`A. DATA_TRUNCATION`** oraz **`F. PRECOMPUTE_REGRESSION`**.  
> **Szczegóły:**  
> 1. Funkcja `build_chart_data` w `streaming.py` wywoływała `_resolve_cache_samples` na procesie głównym, gdzie słownik `WORKER_CACHE["fit_data"]` nie był jeszcze zainicjalizowany, co powodowało wygenerowanie pustego `chart_data = {}` dla cache'u telemetrii.  
> 2. `_get_src_samples` w `streaming.py` zwracało pojedynczą listę zamiast 3-elementowej krotki `(speed, track, alt)`.  
> 3. W `chart_builder.py` wskaźniki `fit_*_text` były przechwytywane przez reguły `cad`/`hr` przekazujące skrócone aliasy zamiast pełnej nazwy pola FIT.

---

## I. Minimalna poprawka

Wprowadzono minimalne, precyzyjne zmiany:

1. **`src/indicators/chart_builder.py`:**
   Przeniesiono priorytetowe dopasowanie wskaźników `fit_*_text` na początek łańcucha `build_chart_data`:
   ```python
   if ind_key.startswith("fit_") and ind_key.endswith("_text"):
       field_name = ind_key[4:-5]
       samples = resolve_samples_fn(field_name, "fit", ind_key)
   elif "speed" in ind_key: ...
   ```

2. **`src/ffmpeg/streaming.py`:**
   Zdefiniowano dedykowane, samowystarczalne resolvery próbek dla wątku głównego:
   ```python
   def _get_src_samples(src_name: str) -> tuple[list, list, list]:
       if src_name == "gpx":
           return (gpx_speed_samples or [], gpx_track_samples or [], gpx_alt_samples or [])
       if src_name == "fit":
           fit_d = fit_data or {}
           return (fit_d.get("speed", []), fit_d.get("track", []), fit_d.get("alt", []))
       return (speed_samples or [], track_samples or [], alt_samples or [])

   def _resolve_stream_samples(field_name: str, source: str = "fit", indicator_key: str | None = None) -> list:
       if source == "fit":
           fit_d = fit_data or {}
           aliases = {
               "power": ("power", "curVpower"), "hr": ("hr", "heart_rate"),
               "cad": ("cad", "cadence"), "atemp": ("atemp", "temperature"),
               "battery": ("battery", "battery_soc"),
           }.get(field_name, (field_name,))
           for name in aliases:
               if fit_d.get(name):
                   return list(fit_d[name])
           return []
       ...
   ```

---

## J. Weryfikacja i Testy Regresyjne

Uruchomiono pełny zestaw testów na obu materiałach wideo (`GX030120.MP4` oraz `GX020079.mp4`):

### 1. `GX030120.MP4` + `Poranna_jazda_na_rowerze.fit` (5400 klatek):
- `fit_cadence_text`: 1672 punkty (`04:29:39` – `04:57:30`)
- `fit_heart_rate_text`: 1672 punkty (`04:29:39` – `04:57:30`)
- Checkpoint 0% (Klatka 0): **`max_diff = 0`, `diff_pixels = 0`**
- Checkpoint 25% (Klatka 1350): **`max_diff = 0`, `diff_pixels = 0`**
- Checkpoint 50% (Klatka 2700): **`max_diff = 0`, `diff_pixels = 0`**
- Checkpoint 75% (Klatka 4050): **`max_diff = 0`, `diff_pixels = 0`**
- Checkpoint 100% (Klatka 5399): **`max_diff = 0`, `diff_pixels = 0`**

### 2. `GX020079.mp4` + `Morning_Ride.fit` (1132 klatki):
- `fit_cadence_text`: 1704 punkty
- `fit_heart_rate_text`: 1704 punkty
- Checkpoint 0%, 25%, 50%, 75%, 100%: **`max_diff = 0`, `diff_pixels = 0`**

### 3. Zautomatyzowany test jednostkowy:
Dodano stały test regresyjny `tests/test_etap5b2_chart_precompute_regression.py` (status: **PASSED**).

---

## K. FULL_FRAME vs MULTI_REGION_ATLAS Parity

Zweryfikowano zgodność renderowania wykresów pomiędzy trybem `FULL_FRAME` a `MULTI_REGION_ATLAS` (1112×668 RGBA):
- Różnica pikseli w obszarze wykresów po rekonstrukcji z atlasu: **`max_diff = 0` (Bit-exact)**.

---

## L. Odpowiedzi na 4 pytania kluczowe

### 1. Na którym dokładnie etapie powstawało ucięcie wykresów?
> Ucięcie powstawało na etapie **budowy `chart_data` przed inicjalizacją puli workerów (`build_chart_data` w `streaming.py`)**, gdzie do cache'u trafiał pusty słownik `chart_data = {}`.

### 2. Czy przyczyną były dane, renderer chart, compositor czy transport HUD?
> Przyczyną był **błąd przekazywania danych do cache (`DATA_TRUNCATION`)**. Renderer `_render_chart_indicator`, compositor `compose_overlay` oraz transport HUD działały poprawnie, lecz operowały na pustej tablicy próbek.

### 3. Czy PRECOMPUTE miało wpływ na problem?
> **TAK.** Wprowadzenie `telemetry_cache` w Etapie 5B pobierało `chart_data` z obiektu cache'u zbudowanego w procesie głównym, gdzie resolver nie miał dostępu do `WORKER_CACHE`.

### 4. Czy po poprawce cadence i heart-rate renderują pełną historię bez ucięcia?
> **TAK, W 100%.** Zarówno `fit_cadence_text`, jak i `fit_heart_rate_text` posiadają pełną historię (1672 punkty na `GX030120` oraz 1704 punkty na `GX020079`), a wygenerowane klatki wykazują **100% bit-exact parity (`max_diff = 0`, `diff_pixels = 0`)**.

---
*ETAP 5B.2 został pomyślnie zakończony. Pełna poprawność wizualna wykresów została przywrócona.*
