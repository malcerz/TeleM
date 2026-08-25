# Raport: ETAP 10N3 — Real Bugfix: Marker Bar/Ruler Nie Aktualizuje Się

**Data:** 2026-08-22  
**Wydanie:** ETAP 10N3  
**Preset bazowy:** `presets/cycling_dashboard_v10.json`  
**Materiał testowy:** `Video/GX010115.MP4` + `Video/GX010115.json` + `Video/Jazda_na_rowerze_w_porze_lunchu.fit`

---

## 1. Manual Reproduction: PASS

- **Konfiguracja:** GUI z aktywnym plikiem FIT `Jazda_na_rowerze_w_porze_lunchu.fit`.
- **Wskaźnik:** Distance Bar (`Forma: bar`, `Styl: ruler`).
- **Objaw przed poprawką:**
  - Tekst wartości pokazywał `11.9 km` (oraz rósł w miarę odtwarzania).
  - Marker na linijce stał zamrożony przy lewej krawędzi ($X \approx 10\text{ px}$, $0\%$ szerokości).
- **Status reprodukcji:** `MANUAL REPRO: PASS`

---

## 2. Real Runtime Bar Config

Dla instancji wskaźnika dystansu:
- `key`: `dist_visual` / `dist_text` / `fit_distance_text`
- `form`: `"bar"`, `bar_style`: `"ruler"`
- `unit`: `"km"`
- `source`: `"fit"` lub `"gpmf"`
- `val_min`: `0.0`
- `val_max`: `23.926 km` (pełna trasa FIT) / `2.955 km` (trasa GPMF)

---

## 3. 5-Frame Runtime Trace (FIT Telemetry, ~11.9 km)

Pomiary dla pełnej aktywności FIT (`23.926 km` total, video start at `11.887 km`):

| Timestamp / Zdarzenie | Raw FIT Distance | Canonical `val_num` | `val_min` | `val_max` | Fraction | Calc `marker_x` | Raster BEFORE Comp | Raster AFTER Comp |
|:---|---:|---:|---:|---:|---:|---:|---:|---:|
| **FIT Start (0%)** | 0.00 m | 0.000 km | 0.0 km | 23.926 km | 0.00% | **10.0 px** | 10.0 px | **10.1 px** |
| **FIT 25%** | 11876.18 m | 11.876 km | 0.0 km | 23.926 km | 49.64% | **187.7 px** | 187.7 px | **188.0 px** |
| **Video Start (49.7%)** | 11886.64 m | 11.887 km | 0.0 km | 23.926 km | 49.68% | **187.9 px** | 187.9 px | **188.0 px** |
| **FIT 75%** | 14360.68 m | 14.361 km | 0.0 km | 23.926 km | 60.02% | **224.9 px** | 224.9 px | **225.0 px** |
| **FIT End (100%)** | 23926.40 m | 23.926 km | 0.0 km | 23.926 km | 100.00% | **368.0 px** | 368.0 px | **368.0 px** |

---

## 4. Porównanie 3 Poziomów Markera

- **A. Wartość wyliczona (`expected marker_x`):** $187.9\text{ px}$ (dla $11.887\text{ km}$ na linijce $358\text{ px}$ o zakresie $0 .. 23.926\text{ km}$).
- **B. Raster przed compositorem (`_render_ruler`):** środek markera żółtego `#FFD42A` = $187.9\text{ px}$.
- **C. Raster po compositorze (`compose_overlay`):** środek markera żółtego `#FFD42A` = $188.0\text{ px}$ wewnątrz wykadrowanego bounding box wskaźnika.

---

## 5. Audyt Cache i Kolejności Rysowania

1. **`_RULER_BASE_CACHE`:**
   - Przechowuje wyłącznie statyczne tło (oś, podziałki, etykiety zakresu `0 km .. 24 km`).
   - Nie przechowuje markera ani tekstu wartości bieżącej.
2. **Kolejność rysowania w `_render_ruler`:**
   ```python
   img = base.copy()
   d = ImageDraw.Draw(img)
   if value is not None:
       frac = _fraction(val_num, val_min, val_max)
       marker_x = int(round(pad_x + frac * width))
       # Rysowanie cienia, obramowania i wypełnienia markera
       d.ellipse(...)
       # Rysowanie tekstu wartości nad marker_x
       _draw_text_bounded_cached(...)
   return img
   ```
   Brak jakichkolwiek operacji po narysowaniu markera zakrywających go tłem.

---

## 6. Root Cause

1. **Rozjazd Jednostek w `_get_indicator_range`:**
   - Próbki dystansu w telemetrii (`track_samples`, `fit_data["track"]`, `fit_data["distance"]`) przechowywane są w **metrach** (`0 .. 24231 m`).
   - W `src/gui/qt/_mixins/indicator_mixin.py` funkcja `_get_indicator_range` pobierała min/max bezpośrednio z próbek bez konwersji do kilometrów, zwracając `max_val = 24240.0` (lub `2960.0`).
   - Gdy użytkownik edytował wskaźnik dystansu w GUI (lub dodawał dynamiczne pole FIT), do layoutu zapisywany był `max_val = 24240.0` (metry), podczas gdy jednostką było `"km"`, a wartość bieżąca wynosiła `11.9 km`.
   - Na linijce o zakresie `0 .. 24240` wartość `11.9` dawała ułamek:
     $$\text{frac} = \frac{11.9 - 0}{24240} = 0.00049 = 0.049\%$$
     co umieszczało marker na $10.17\text{ px}$ (początek skali), sprawiając, że stał on w miejscu przez cały czas trwania wideo.
2. **Brak Obsługi Innych Kluczy Dystansu w Compositorze:**
   - W `src/indicators/compositor.py` automatyczne dynamiczne skalowanie zakresu `max_val = max_distance_m / 1000.0` oraz konwersja `raw / 1000.0` były ograniczone wyłącznie do hardcoded klucza `"dist_visual"`, pomijając `dist_text`, `fit_distance_text` czy customowe wskaźniki dystansu w formie `bar`.
3. **Brak Ustalania Źródła Dystansu w `frame_data.py` i `preview_mixin.py`:**
   - Gdy w layoucie znajdował się `dist_text` lub `fit_distance_text`, `max_distance_m` domyślnie korzystał z próbek GPMF zamiast FIT.

---

## 7. Wdrożona Poprawka Produkcyjna

1. **`src/indicators/compositor.py`:**
   - Wszystkie wskaźniki dystansu (`dist_visual`, `dist_text`, `fit_distance_text`, oraz wskaźniki `form in ("bar", "gauge", "segment_bar")` o jednostce `"km"`) otrzymują spójną konwersję jednostek `raw / 1000.0` oraz dynamiczne skalowanie `max_val = max_distance_m / 1000.0`.
2. **`src/gui/qt/_mixins/indicator_mixin.py`:**
   - `_get_indicator_range` dla wskaźników dystansu automatycznie przelicza próbki z metrów na kilometry (`/ 1000.0`), ustawiając właściwy zakres w kilometrach (np. `0.0 .. 25.0 km` zamiast `0 .. 24240 m`).
3. **`src/indicators/frame_data.py` & `src/gui/qt/_mixins/preview_mixin.py`:**
   - Poprawiono detekcję źródła dystansu (`dist_visual`, `dist_text`, `fit_distance_text`), gwarantując poprawne wyznaczenie `max_distance_m` dla FIT, GPX i GPMF.

---

## 8. Testy Rastrowe i Weryfikacja

1. **Wykrywanie Markera na Pikselach (0, 2.5, 5.0, 7.5, 10.0 km):**
   - Wszystkie kroki trafiają w piksel z dokładnością $\pm 0.5\text{ px}$ — `PASS`.
2. **Przypadek Realny ~11.9 km:**
   - $11.887\text{ km}$ na skali $0 .. 23.926\text{ km}$ daje marker na $188.0\text{ px}$ ($49.7\%$) — `PASS`.
3. **Sekwencja Cache (`0 -> 5 -> 10 -> 2.5 -> 7.5 -> 0`):**
   - Marker podąża za każdą zmianą wartości, brak zamrożenia stanu — `PASS`.
4. **Weryfikacja GPMF i FIT:**
   - GPMF Distance (`0 .. 2.955 km`): marker przesuwa się monotonicznie `10.0 px -> 69.0 px` — `PASS`.
   - FIT Distance (`0 .. 23.926 km`): marker przesuwa się monotonicznie `188.0 px -> 195.0 px` — `PASS`.
5. **Regresje Altitude i Slope:**
   - Wszystkie testy `alt_visual` i `slope_text` przechodzą w 100% — `PASS`.

---

## 9. Wyniki Testów Pytest

```text
============================= test session starts =============================
tests/test_etap10n3_distance_marker.py .....                             [ 22%]
tests/test_etap10n2_distance_marker.py ......                            [ 50%]
tests/test_distance_optimization.py ......                               [ 77%]
tests/test_etap10n_slope_altitude.py .....                               [100%]
============================= 22 passed in 0.49s ==============================
```

---

## 10. Zmienione Pliki Produkcyjne

- `src/indicators/compositor.py`
- `src/indicators/frame_data.py`
- `src/gui/qt/_mixins/preview_mixin.py`
- `src/gui/qt/_mixins/indicator_mixin.py`
- `tests/test_etap10n3_distance_marker.py`

---

## 11. Final Status

```text
BAR/RULER DYNAMIC MARKER: FIXED
```
