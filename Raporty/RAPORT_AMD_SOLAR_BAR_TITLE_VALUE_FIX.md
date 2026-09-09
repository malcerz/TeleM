# Raport: AMD — SOLAR BAR TITLE VALUE FIX

**Data:** 2026-09-05  
**Branch:** `integration/intel-amd`  
**Commit bazowy:** `59277b4`  
**Status:** COMPLETE (PASS)

---

## 1. Root Cause

Problem wynikał ze splotu mechanizmu `title_with_unit` w rendererze linijek (ruler) oraz specyfiki renderowania glifu pionowej kreski (`|`) w cyfrowych fontach 7-segmentowych (np. `Digital-7 Mono` ustawionym globalnie w projekcie):

1. **Formatowanie nagłówka linijki z jednostką:**
   W `src/indicators/bar.py` w funkcjach `_render_ruler` (linia 384) oraz `_render_ruler_vertical` (linia 669) aktywna flaga `title_with_unit` (domyślnie `True`) doklejała jednostkę do tytułu za pomocą separatora ` | `:
   ```python
   unit_title = str(unit or "").upper() if uppercase_title else str(unit or "")
   if show_title and title_with_unit and unit_title:
       title = f"{title} | {unit_title}" if title else unit_title
   ```
   Dla wskaźnika Solar jednostka wynosi `unit = "%"`, co powodowało wygenerowanie tytułu:
   ```text
   title = "SOLAR | %"
   ```

2. **Renderowanie glifu `|` w foncie `Digital-7 Mono`:**
   W foncie `Digital-7 Mono` (7-segmentowy font zegarowy/wyświetlacza) glif separatora `|` składa się z pojedynczego pionowego segmentu, który jest **wzrokowo nieodróżnialny od cyfry `1`** (dokładnie ten sam prosty pionowy słupek w segmencie).
   Napis:
   ```text
   SOLAR | %  ──(font Digital-7)──>  SOLAR 1 %
   ```
   wyglądał na ekranie i podglądzie jak druga, błędna wartość liczbowa `SOLAR 1 %` w nagłówku, podczas gdy tuż pod nim dynamiczny marker poprawnie wskazywał bieżącą wartość (np. `5%`).

3. **Brak sensu semantycznego dla jednostki `%` w tytule:**
   O ile dla jednostek fizycznych takich jak `DISTANCE | KM` czy `ALTITUDE | M` separator ` | ` ma sens jako oznaczenie jednostki metrycznej, o tyle dla wielkości procentowych (gdzie `%` jest symbolem ilorazu przypisanym do liczb, a nie jednostką w notacji `TITLE | UNIT`) konstrukcja `SOLAR | %` jest zbędna i wprowadza mylący artefakt wizualny.

---

## 2. Miejsce generowania `SOLAR 1 %`

- **Plik:** `src/indicators/bar.py`
- **Funkcja:** `_render_ruler` (linia 381–386) oraz `_render_ruler_vertical` (linia 666–671)
- **Generowany ciąg tekstowy:** `title = f"{title} | {unit_title}"` -> `"SOLAR | %"`
- **Rysowanie na rastrze bazowym:** linia 466:
  ```python
  _draw_text_bounded(
      d, (raster_w / 2, pad_top), title,
      font=title_font, fill=text_color,
      stroke_width=text_stroke, stroke_fill=(0, 0, 0, 230),
      bounds=(raster_w, height), anchor="ma",
  )
  ```
- **Występowanie w konfiguracji layoutu:** w `def_layout.json` wskaźnik `fit_solar_text` posiadał `"title_with_unit": true`.

---

## 3. Czy źródłem było `active_segments`, normalized value czy inny field?

- **Nie.** Źródłem nie było ani `active_segments`, ani `normalized_fraction`, ani `raw_value`, ani `display_value`.
- Wartość numeryczna telemetryczna (np. `5%`, `11%`) była i jest liczona oraz przekazywana w 100% poprawnie do pływającej etykiety nad markerem.
- Rzekoma cyfra `1` w napisie `SOLAR 1 %` była w rzeczywistości **znakiem separatora `|` (pipe)** wstawianym przez formatowanie `f"{title} | %"`, który w foncie `Digital-7 Mono` tworzy pionowy segment identyczny z cyfrą `1`.

---

## 4. Sposób naprawy

Zastosowano dwupoziomową, generic oraz konfiguracyjną ochronę architektoniczną:

1. **Poziom renderera (`src/indicators/bar.py`):**
   Wprowadzono regułę ogólną (generic) dla `_render_ruler` i `_render_ruler_vertical`: jednostka `%` jest traktowana jako symbol wartości, a nie jednostka słowna w tytule linijki. Jeżeli `unit_title.strip() == "%"`, separator ` | %` nie jest doklejany do tytułu:
   ```python
   # _render_ruler (linia 384)
   if show_title and title_with_unit and unit_title and unit_title.strip() != "%":
       title = f"{title} | {unit_title}" if title else unit_title
   ```
   ```python
   # _render_ruler_vertical (linia 669)
   if show_label and title_with_unit and unit_title and unit_title.strip() != "%":
       title = f"{title} | {unit_title}" if title else unit_title
   ```
   Dzięki temu każdy wskaźnik procentowy w stylu linijki (niezależnie od presetu czy konfiguracji użytkownika) otrzymuje czysty tytuł `SOLAR`, `SLOPE` lub `BATTERY`, bez artefaktu `| %` (`1 %`).

2. **Poziom konfiguracji layoutu (`def_layout.json`):**
   Dla wskaźnika `fit_solar_text` jawnie ustawiono:
   ```json
   "title_with_unit": false
   ```

3. **Zachowanie jednostek dla innych wskaźników:**
   Dla jednostek słownych/akronimów (np. `km`, `m`, `bpm`, `rpm`, `w`) warunek `unit_title.strip() != "%"` jest spełniony, dzięki czemu wskaźniki `DISTANCE | KM` oraz `ALTITUDE | M` zachowują swoje zamierzone tytuły w 100% bez regresji.

---

## 5. Wynik dla Solar 1 / 5 / 11 / 15

Weryfikacja wykonana skryptem `scratch/validate_solar_bar_title_fix.py` na silniku renderującym z fontem `Digital-7 Mono`:

| Wartość testowa | Title (nagłówek) | Pływająca wartość markera | Pozycja markera (x / 0-30 scale) | Etykiety zakresu (dół) | Artefakt `1 %` w tytule |
|:---:|:---:|:---:|:---:|:---:|:---:|
| **1%** | `SOLAR` | `1%` | `x = 21 px` (3.3% osi) | `0 %`, `15 %`, `30 %` | **BRAK (CZYSTO)** |
| **5%** | `SOLAR` | `5%` | `x = 59 px` (16.7% osi) | `0 %`, `15 %`, `30 %` | **BRAK (CZYSTO)** |
| **11%** | `SOLAR` | `11%` | `x = 117 px` (36.7% osi) | `0 %`, `15 %`, `30 %` | **BRAK (CZYSTO)** |
| **15%** | `SOLAR` | `15%` | `x = 155 px` (50.0% osi) | `0 %`, `15 %`, `30 %` | **BRAK (CZYSTO)** |

Wszystkie przypadki:
- Tytuł: dokładnie `SOLAR`.
- Wartość nad markerem: dokładnie `1%`, `5%`, `11%`, `15%`.
- Brak jakiejkolwiek drugiej liczby przy tytule.

---

## 6. Preview Parity

- Sprawdzono renderowanie overlay w trybie Preview (`reuse_canvas=False`, `fast_preview=False`) w `src/indicators/compositor.py`.
- Tytuł: `SOLAR`.
- Marker i wartość: poprawnie zsynchronizowane z czasem i próbkami telemetrycznymi.

---

## 7. Final Render Parity

- Przeprowadzono audyt pikselowy (pre-encode crop 360x200 px wokół wskaźnika Solar) pomiędzy trybem Preview a trybem Final AMD Render (`reuse_canvas='above'`):
  - **Max diff:** `0`
  - **MAE (Mean Absolute Error):** `0.000000`
  - **Different pixels:** `0`
- Parzystość pikselowa: **100% BIT-EXACT MATCH**.

---

## 8. Regresja innych BAR-ów

Zweryfikowano wszystkie typy wskaźników BAR:

1. **Distance BAR (`fit_distance_text` / `dist_visual`):**
   - Tytuł: `DISTANCE | KM` (jednostka `KM` w tytule w pełni zachowana).
   - Etykiety skali: `0.0 km`, `10.0 km`, `20.0 km`.
   - Wartość przy markerze: `12.4 km`.
   - Status: **PASS (Brak regresji)**.

2. **Garmin Battery % (`fit_garmin_battery_percent_text`):**
   - Styl: `segment_bar`.
   - Wartość: `85%`.
   - Status: **PASS (Brak regresji)**.

3. **Altitude BAR (`alt_text` / `alt_visual`):**
   - Styl: pionowy ruler (`orientation: vertical`).
   - Tytuł przy włączonym label: `WYS | M`.
   - Skala wysokości: `0`, `200`, `400`, `600`, `800`, `1000`.
   - Wartość przy markerze: `450 m`.
   - Status: **PASS (Brak regresji)**.

4. **Slope BAR (`slope_text`):**
   - Styl: wertykalna linijka nachylenia terenu (`unit: "%"`).
   - Tytuł: `SLOPE` (usunięto mylące `SLOPE | %`).
   - Wartość ze znakiem: `+7.0%`.
   - Status: **PASS (Brak regresji)**.

5. **Zautomatyzowane testy pytest:**
   - Nowy test: `tests/test_solar_bar_title_clean.py` -> `3 passed`.
   - Testy integracji i linijek: `tests/test_bar_integration.py`, `tests/test_bar_ruler_opt_parity_etap3b.py` -> `15 passed`.
   - Łącznie: `18 passed in 0.77s`.

---

## 9. Git diff --stat

```text
 def_layout.json                     |   2 +-
 src/indicators/bar.py               |   4 +-
 tests/test_solar_bar_title_clean.py | 100 ++++++++++++++++++++++++++++++++++++
 3 files changed, 103 insertions(+), 3 deletions(-)
```

---

## Podsumowanie i werdykt

```text
SOLAR TITLE CLEAN:      PASS
SOLAR MARKER VALUE:     PASS
SOLAR MARKER POSITION:  PASS
OTHER BARS REGRESSION:  PASS
```
