# Raport: AMD — SOLAR BAR DISPLAY VALUE FIX

**Data:** 2026-09-04  
**Branch:** `integration/intel-amd`  
**Commit bazowy:** `59277b4`  
**Status:** COMPLETE (PASS)

---

## 1. Root Cause

Problem wynikał ze splotu trzech czynników w generic pipeline renderowania wskaźników BAR:

1. **Brak jawnego rozdzielenia `normalized_fraction` od `display_value` w rendererze barów:**
   W `src/indicators/bar.py` zmienna `value` była używana zarówno do obliczania geometrii (`_fraction(val_num, val_min, val_max)`), jak i tekstu. W przypadku brakującego lub nieprecyzyjnie przekazanego `formatted_val` zachodziło ryzyko użycia znormalizowanej/skrępowanej wartości (np. `0.11` lub `clamp(11, 0, 1) = 1` lub aktywnego segmentu `1`), co przy formatowaniu do liczby całkowitej dawało `1` zamiast `11`.
2. **Niespójne domyślne `show_value` dla stylu `ruler`:**
   W `src/indicators/bar.py` (`_render_ruler` linia 375) wartość domyślna wynosiła `cfg.get("show_value", False)`, podczas gdy w `_render_segments` i `_render_ruler_vertical` oraz w `compositor.py` wynosiła `True`. Gdy użytkownik miał wskaźnik Solar w stylu ruler bez jawnego `"show_value": true` w pliku layoutu, tekst wartości nad markerem nie był w ogóle wyświetlany (wyświetlały się tylko etykiety zakresu `0 %`, `50 %`, `100 %`), lub w stylu segmentowym segment active dawał 1 segment na 5.
3. **Domyślne formatowanie miejsc dziesiętnych dla pól procentowych:**
   W `_render_segments` `decimals` domyślnie przyjmowało `1`, przez co wskaźniki procentowe (np. Solar, Garmin Battery) pokazywały zakres `0.0` i `100.0` oraz `11.0 %` zamiast czytelnych liczb całkowitych `0`, `100` i `11%`. W `compositor.py` klucze niezaczynające się od `fit_` również domyślnie otrzymywały 1 miejsce po przecinku.

---

## 2. Raw Solar Value

- **Wartość źródłowa:** `raw = 11.0` (dane telemetryczne z pliku FIT Garmin / Solar).
- **Format źródłowy:** `float` (kroki 1% w próbkach FIT Garmin).

---

## 3. Normalized Solar Value

- **Wartość znormalizowana:** `normalized = (11.0 - 0.0) / (100.0 - 0.0) = 0.1100` (11.0% pełnego zakresu 0–100%).
- **Zastosowanie:** Wyłącznie położenie geometryczne markera (`marker_x = pad_x + normalized * width`) oraz liczba aktywnych segmentów (1 segment z 5).
- **Geometria markera:** Pozostawiona bez żadnych zmian – marker znajdował się i nadal znajduje się w idealnej pozycji ~11% osi.

---

## 4. Błędny dotychczas display_value

- **Dotychczasowy objaw:** Wartość liczbowa wyświetlana na barze pokazywała `1` (lub brak napisu wartości nad markerem przy `show_value=False`), podczas gdy w trybie TEXT wyświetlało się prawidłowo `SOLAR: 11%`.

---

## 5. Poprawiony display_value

- **Poprawiona wartość:** `display_value = raw_val = 11`
- **Format tekstu:** `11%` (bez spacji przed znakiem `%` dla pól procentowych, formatowanie całkowite 0 miejsc dziesiętnych).
- **Formatowanie:** `_fmt_number(display_value, decimals=0)` -> `"11"`, w całości `"11%"`.

---

## 6. Miejsce w kodzie powodujące błąd

1. `src/indicators/bar.py`:
   - `_render_bar_indicator`: Dodano ścisłe rozdzielenie `raw_val`, `normalized_fraction` (do geometrii) i `display_value` (do tekstu). Dodano diagnostykę `SOLAR_BAR_DEBUG`.
   - `_render_ruler`: Ujednolicono domyślne `show_value = bool(cfg.get("show_value", True if (formatted_val is not None and formatted_val != "") else False))`, dzięki czemu tekst wartości jest zawsze renderowany nad markerem, gdy został wyliczony przez kompozytor.
   - `_render_segments`: Wprowadzono detekcję pól procentowych (`unit == "%"` lub `solar`/`battery`), wymuszając domyślnie `decimals = 0`, co usuwa niepożądane `.0` z wartości i etykiet zakresu `0` / `100`.
2. `src/indicators/compositor.py`:
   - Dodano `unit == "%"`, `"solar" in key.lower()`, `"battery" in key.lower()` do reguły `default_decimals = 0`.
   - Poprawiono formatowanie jednostki `%` na brak zbędnej spacji (`f"{val_str}%"`).
3. `src/gui/qt/models.py`:
   - W `_bar_ruler_fields` zmieniono `default=False` na `default=True` dla pola `show_value`, zapewniając pełną spójność UI z segmentami, gauge'ami i chartami.

---

## 7. Wynik dla wartości 0 / 1 / 11 / 50 / 99 / 100

Wykonano weryfikację z zestawem testowym dla stylu `ruler` i `segments`:

```text
=== SOLAR BAR (RULER STYLE) ===
SOLAR_BAR_DEBUG: raw=0, min=0, max=100, normalized=0.0000, marker=0.0%, display_value=0, formatted_text=0%
SOLAR_BAR_DEBUG: raw=1, min=0, max=100, normalized=0.0100, marker=1.0%, display_value=1, formatted_text=1%
SOLAR_BAR_DEBUG: raw=11, min=0, max=100, normalized=0.1100, marker=11.0%, display_value=11, formatted_text=11%
SOLAR_BAR_DEBUG: raw=50, min=0, max=100, normalized=0.5000, marker=50.0%, display_value=50, formatted_text=50%
SOLAR_BAR_DEBUG: raw=99, min=0, max=100, normalized=0.9900, marker=99.0%, display_value=99, formatted_text=99%
SOLAR_BAR_DEBUG: raw=100, min=0, max=100, normalized=1.0000, marker=100.0%, display_value=100, formatted_text=100%

=== SOLAR BAR (SEGMENTS STYLE) ===
SOLAR_BAR_DEBUG: raw=0, min=0, max=100, normalized=0.0000, marker=0.0%, display_value=0, formatted_text=0%
SOLAR_BAR_DEBUG: raw=1, min=0, max=100, normalized=0.0100, marker=1.0%, display_value=1, formatted_text=1%
SOLAR_BAR_DEBUG: raw=11, min=0, max=100, normalized=0.1100, marker=11.0%, display_value=11, formatted_text=11%
SOLAR_BAR_DEBUG: raw=50, min=0, max=100, normalized=0.5000, marker=50.0%, display_value=50, formatted_text=50%
SOLAR_BAR_DEBUG: raw=99, min=0, max=100, normalized=0.9900, marker=99.0%, display_value=99, formatted_text=99%
SOLAR_BAR_DEBUG: raw=100, min=0, max=100, normalized=1.0000, marker=100.0%, display_value=100, formatted_text=100%
```

Dla kluczowego przypadku regresyjnego `raw=11`:
- `normalized = 0.1100` (pozycja markera ~11%)
- `display_value = 11` (liczba wyświetlana = 11%)

---

## 8. Preview Parity

- Weryfikacja: wywołanie kompozycji overlay dla trybu Preview (`reuse_canvas=None`, `fast_preview=False`).
- Pozycja markera: ~11% osi.
- Wartość wyświetlana: `11%`.

---

## 9. Final Render Parity

- Weryfikacja: wywołanie kompozycji overlay dla trybu Final AMD Render (`reuse_canvas="above"`).
- Porównanie pre-encode crop (900x300 px wokół bara Solar):
  - **Max Diff:** 0
  - **MAE:** 0.000000
  - **Different Pixels:** 0
- **Wynik:** 100% dokładna parzystość pikselowa (bit-exact parity) pomiędzy Preview a Final AMD Render.

---

## 10. Regresja innych BAR-ów

Zweryfikowano zachowanie pozostałych wskaźników BAR oraz trybu TEXT:
- **Garmin Battery BAR (`fit_garmin_battery_percent_text`):** renderuje poprawnie `85%`, 17/20 aktywnych segmentów, etykiety zakresu `0` i `100`.
- **Altitude BAR (`alt_text`):** renderuje poprawnie skalę wysokości w metrach z wartością nad markerem.
- **Slope BAR (`slope_text`):** renderuje poprawnie wertykalny ruler z wartością ze znakiem.
- **Distance BAR (`fit_distance_text` / `dist_visual`):** renderuje poprawnie ruler z konwersją na kilometry.
- **TEXT mode Solar (`fit_solar_text`):** nadal renderuje poprawnie `Solar: 11%`.
- **Testy jednostkowe barów (`pytest`):** 57 testów zakończonych sukcesem (`57 passed in 5.01s`).

---

## 11. MPV Tick Error Fix

### Dokładny Root Cause
W module `src/gui/qt/_mixins/playback_mixin.py` w metodzie `_on_mpv_playback_tick()` dodano w poprzednich zmianach rate-limited diagnostykę `[PREVIEW_TIME]` wywołującą `now_mono = _time.monotonic()`. Plik `playback_mixin.py` nie importował jednak modułu `time` ani aliasu `_time` (alias `import time as _time` znajdował się tylko w `project_mixin.py`).

W efekcie na każdym ticku MPV rzucany był wyjątek:
```text
NameError: name '_time' is not defined
```
Przechwytywany przez ogólny blok obsługi błędów ticka:
```python
except Exception as e:
    print(f"[MPV Tick Error] {e}", flush=True)
```
Co krytyczne, wywołania:
```python
self.signals.sig_seek_position.emit(global_pos)
self._render_preview(global_pos)
```
znajdowały się PO linii z błędem, przez co `NameError` nie tylko spamował konsolę komunikatami `[MPV Tick Error] name '_time' is not defined`, ale również **całkowicie blokował aktualizację pozycji suwaka i odświeżanie klatek podglądu/HUD podczas ticków MPV**.

### Zastosowana Poprawka
1. **Import symbolu:** Dodano `import time as _time` na początku `src/gui/qt/_mixins/playback_mixin.py`.
2. **Kolejność operacji:** Przeniesiono krytyczne aktualizacje suwaka i renderera (`self.signals.sig_seek_position.emit(global_pos)` oraz `self._render_preview(global_pos)`) przed blok diagnostyczny.
3. **Odporność na błędy diagnostyki:** Cały pomocniczy blok diagnostyczny `[PREVIEW_TIME]` zaizolowano w osobnym bloku `try...except Exception: pass`, co daje 100% gwarancję, że żaden problem z pomocniczym logowaniem diagnostycznym nie przerwie cyklu odświeżania podglądu.

### Wynik Testu Odtwarzania i Scrubowania
Przetestowano pełną ścieżkę wieloplikową (`Video/GX010114.MP4` + `Video/GX010115.MP4` + `Video/GX010114_116.fit`) z rzeczywistą instancją libmpv:
- **A. PLAY:** płynne odtwarzanie klatek.
- **B. PAUSE:** natychmiastowe zatrzymanie tickera.
- **C. Scrub w Clip 1 (60.0s):** natychmiastowy seek i render klatki.
- **D. Scrub w Clip 2 (2016.588s):** automatyczne przełączenie aktywnego klipu (`Switch clip 2/2`) i seek.
- **E. Szybkie naprzemienne scrubowanie Clip 1 <-> Clip 2:** seria skoków (10s -> 1986s -> 50s -> 2056s -> 80s -> 1976s) – płynne przejścia bez zawieszeń flagi `_source_transition_in_progress`.
- **F. PLAY po scrubowaniu:** wznowienie odtwarzania z nowej pozycji.

### Statystyka Błędów:
```text
Total [MPV Tick Error] count: 0
Total [PREVIEW_TIME] diagnostic logs emitted: 3 (rate-limited ~1 raz/s)
Total preview rendered calls: 23
Total signal seek emissions: 26
```
**Potwierdzenie:** Dokładnie **0 × `[MPV Tick Error]`**.

---

## 12. Git Diff Stat

```text
 src/gui/qt/_mixins/playback_mixin.py | 46 ++++++++++++++++++------
 src/gui/qt/models.py                 |  2 +-
 src/indicators/bar.py                | 69 ++++++++++++++++++++++++++++++------
 src/indicators/compositor.py         | 10 ++++--
 4 files changed, 103 insertions(+), 24 deletions(-)
```

---

## Podsumowanie

```text
SOLAR RAW VALUE: PASS
SOLAR MARKER POSITION: PASS
SOLAR BAR DISPLAY VALUE: PASS
SOLAR TEXT MODE: PASS
OTHER BARS REGRESSION: PASS
MPV SCRUB TICK ERROR: PASS
MULTIFILE SCRUB REGRESSION: PASS
```
