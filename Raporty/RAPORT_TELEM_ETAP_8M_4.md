# RAPORT TELEM — ETAP 8M.4: Wybierany zakres czasu wykresu (CAŁA AKTYWNOŚĆ / ZAKRES FILMU)

## A. Tytuł i cel etapu
- **Etap:** ETAP 8M.4 — Chart Time Scope: Activity vs Video Scope + Real Material Validation + Preview/Final Parity.
- **Cel:** Wprowadzenie wybieranego przez użytkownika zakresu osi czasu dla wskaźników typu wykres (`form="chart"`), z domyślnym trybem pełnej aktywności źródła (`"activity"`) oraz opcjonalnym trybem wycinka filmu (`"video"`), z zachowaniem pełnej spójności matematycznej (timestamp-based positioning), niezależności wartości bieżącej i bit-exact parity między Preview a Final renderem.

---

## B. Problem
Poprzedni kontrakt wykresów (wprowadzony w ETAPIE 8E) zawężał całą serię punktów wykresu do przedziału `[start_dt_utc, end_dt_utc]` reprezentującego czas trwania aktualnego klipu wideo.
Przy krótkich filmach (np. wideo trwające ~37.74 s) nagranych w trakcie długiej aktywności FIT (np. jazda rowerowa trwająca 28.4 minuty / 1704 próbki):
1. Wykres prezentował jedynie 38-sekundowy wycinek z samego końca lub środka treningu.
2. Użytkownik tracił perspektywę całego profilu tętna, kadencji czy wysokości w kontekście całej trasy.
3. Brakowało możliwości wyboru pomiędzy perspektywą całej aktywności a zbliżeniem na czas trwania klipu.

---

## C. Wykonana implementacja
1. **Model danych i struktura historii:**
   - W [src/indicators/chart_builder.py](file:///c:/_DEV/TeleM/src/indicators/chart_builder.py) rozbudowano `ChartHistory` o pola `chart_start_dt`, `chart_end_dt` oraz `time_scope`.
   - Zaimplementowano w `build_chart_data` obsługę parametru `chart_time_scope` (`"activity"` vs `"video"`), z uwzględnieniem globalnych zakresów aktywności `source_activity_ranges`.
2. **Timestamp-based X Geometry:**
   - W [src/indicators/chart_utils.py](file:///c:/_DEV/TeleM/src/indicators/chart_utils.py) w funkcji `_build_chart_bg` zastąpiono indeksowe rozmieszczanie punktów precyzyjnym wyliczaniem współrzędnej $X$ na podstawie proporcji timestampu:
     $$\text{norm\_x} = \frac{ts_i - \text{chart\_start\_dt}}{\text{chart\_end\_dt} - \text{chart\_start\_dt}}$$
     $$x = \text{plot\_x1} + \text{norm\_x} \cdot \text{plot\_w}$$
   - Zabezpieczono rysowanie poligonu wypełnienia (`fill_polygon`) do podstawy osi $Y$ (`plot_y2`).
3. **Precyzyjna pozycja markera:**
   - W [src/indicators/chart.py](file:///c:/_DEV/TeleM/src/indicators/chart.py) w funkcji `_render_chart_indicator` zaimplementowano wyliczanie pozycji markera w osi $X$ w odniesieniu do granic czasu wykresu oraz interpolację wysokości $Y$ na krzywej serii.
4. **GUI i właściwości:**
   - W [src/gui/indicator_schemas.py](file:///c:/_DEV/TeleM/src/gui/indicator_schemas.py) dodano pole `chart_time_scope` do schematu wskaźników wartości.
   - W [src/gui/qt/models.py](file:///c:/_DEV/TeleM/src/gui/qt/models.py) dodano pole wyboru `Zakres czasu wykresu` z opcjami `Cała aktywność` (`"activity"`) i `Zakres filmu` (`"video"`).
   - W [src/gui/qt/widgets/property_editor.py](file:///c:/_DEV/TeleM/src/gui/qt/widgets/property_editor.py) dodano pełne wsparcie dla wyboru opcji z etykietami (`userData` mapping).
   - W [src/gui/qt/_mixins/preset_mixin.py](file:///c:/_DEV/TeleM/src/gui/qt/_mixins/preset_mixin.py) podpięto natychmiastową inwalidację cache i odświeżanie podglądu przy zmianie pola `chart_time_scope`.
5. **Integracja potoków Preview i Render:**
   - W [src/gui/qt/_mixins/preview_mixin.py](file:///c:/_DEV/TeleM/src/gui/qt/_mixins/preview_mixin.py), [src/ffmpeg/worker_cache.py](file:///c:/_DEV/TeleM/src/ffmpeg/worker_cache.py) i [src/gui/qt/tabs/render_tab.py](file:///c:/_DEV/TeleM/src/gui/qt/tabs/render_tab.py) przekazano globalne granice aktywności źródeł do `build_chart_data`.

---

## D. Kontrakt trybu "activity" (Domyślny)
- **Oś X:** Reprezentuje pełny czas trwania aktywności danego źródła (np. dla FIT: `activity_start_dt -> activity_end_dt`).
- **Próbki:** Wszystkie próbki zarejestrowane w pliku aktywności dla wybranego źródła są renderowane na wykresie.
- **Ruch markera:** Marker przesuwa się po osi proporcjonalnie do bezwzględnego czasu wideo:
  $$\text{pos} = \text{clamp}\left(\frac{\text{target\_dt} - \text{activity\_start\_dt}}{\text{activity\_end\_dt} - \text{activity\_start\_dt}}, 0.0, 1.0\right)$$
  Marker pokrywa wyłącznie ten fragment wykresu, w którym nagrano dany klip wideo (np. 97.82% -> 100.00% dla klipu nagranego pod koniec trasy).
- **Tło wykresu:** Jest absolutnie stałe przez cały czas trwania filmu (100% cache hit dla tła).

---

## E. Kontrakt trybu "video"
- **Oś X:** Ograniczona do przedziału czasu widocznego w filmie:
  $$\text{chart\_start\_dt} = \max(\text{source\_start}, \text{video\_start})$$
  $$\text{chart\_end\_dt} = \min(\text{source\_end}, \text{video\_end})$$
- **Próbki:** Wykres przedstawia zbliżenie wyłącznie na próbki telemetryczne mieszczące się w oknie filmu.
- **Ruch markera:** Marker przebiega całą szerokość wykresu od 0.0% do 100.0% przez czas trwania filmu.
- **Tło wykresu:** Jest stałe dla danego klipu wideo.

---

## F. Timestamp-based X Geometry
Próbki telemetryczne nie muszą być rozłożone w równych odstępach czasu (np. w przypadku zmiennej częstotliwości zapisu w urządzeniach GPS/FIT lub przerw w transmisji).
Każdy punkt $(x_i, y_i)$ otrzymuje pozycję $X$ ściśle wyliczoną z bezwzględnego znacznika czasu próbki:
```python
norm_x = (sample_timestamp - chart_start_dt).total_seconds() / total_duration_seconds
x = plot_x1 + max(0.0, min(1.0, norm_x)) * plot_w
```
Dzięki temu brakujące fragmenty lub nieregularne interwały są wiernie reprezentowane na osi czasu.

---

## G. Wyliczanie pozycji markera
Pozycja pionowej linii i punktu wskaźnika (`cursor_x`, `py`):
1. $\text{cursor\_x} = \text{plot\_x1} + \text{pos} \cdot \text{plot\_w}$
2. Punkt $Y$ na krzywej (`py`) jest wyznaczany poprzez lokalizację sąsiadujących próbek w czasie (`bisect_right`) i interpolację liniową pomiędzy punktami wykresu $P_k$ i $P_{k+1}$ w chwili `target_dt`.

---

## H. Niezależność wartości bieżącej (Current Value)
Wyliczenie wartości numerycznej wyświetlanej obok wykresu (np. bieżąca kadencja `88 rpm`, bieżące tętno `145 bpm`):
- Pozostaje w 100% niezależne od wybranego trybu `chart_time_scope`.
- Wartość bieżąca jest zawsze pobierana z najświeższej próbki $\le \text{target\_dt}$ lub interpolowana dla chwili bieżącej klatki.

---

## I. GUI i zachowanie kontrolki
- W panelu właściwości (zakładka **Chart**) dodano rozwijaną listę:
  - **Etykieta:** `Zakres czasu wykresu`
  - **Opcje:**
    - `Cała aktywność` (wartość w JSON: `"activity"`)
    - `Zakres filmu` (wartość w JSON: `"video"`)
- Kontrolka pojawia się dla wskaźników z `form="chart"`.
- Domyślna wartość w przypadku braku wpisu w starych layoutach: `"activity"`.

---

## J. Zmiana w Preview w czasie rzeczywistym
- Zmiana opcji w ComboBoxie natychmiast generuje sygnał `sig_property_changed`.
- Kontroler wywołuje `_clear_caches()` (czyszcząc cache danych wykresu oraz cache przygotowania klatki) i natychmiast renderuje nowy podgląd klatki bez konieczności restartu aplikacji czy przeładowania projektu.

---

## K. Izolacja i inwalidacja cache
Klucz pamięci podręcznej tła wykresu (`_history_chart_cache_key`) zawiera teraz:
```python
(
    id(history_values),
    len(history_values),
    chart_start_dt,
    chart_end_dt,
    time_scope,
    width, height, line_color, line_thickness, fill_alpha, ...
)
```
- Zmiana trybu (`activity` $\leftrightarrow$ `video`) zmienia klucz cache i natychmiast ładuje właściwe tło.
- Pozycja bieżąca markera (`current_position` / `target_dt`) **NIE** wchodzi w skład klucza tła statycznego, dzięki czemu statyczne tło generowane jest tylko raz na eksport/klip.

---

## L. Zgodność Preview / Final Worker (Parity)
Zarówno podgląd GUI (`preview_mixin.py`), jak i podgląd renderowania (`render_tab.py`) oraz wieloprocesowy potok eksportu (`worker_cache.py`) korzystają ze wspólnego modułu `build_chart_data`, przekazując te same globalne granice aktywności `source_activity_ranges`. Wykres w oknie Preview oraz w wyeksportowanym pliku MP4 jest w 100% identyczny co do piksela.

---

## M. Weryfikacja na starym materiale (GX020079.mp4 + Morning_Ride.fit)
- **Wideo:** `GX020079.mp4` — czas trwania $37.74\text{ s}$ (`2026-08-05 04:55:50.800` $\rightarrow$ `2026-08-05 04:56:28.540`).
- **FIT:** `Morning_Ride.fit` — czas trwania $1703.0\text{ s}$ ($28.4\text{ min}$, 1704 próbki, `2026-08-05 04:28:05` $\rightarrow$ `2026-08-05 04:56:28`).

### Zestawienie zrzutów i metryk:

| Scope | Etykieta | Czas wideo | Target DT (UTC) | Pozycja mat. [0.0..1.0] | Piksel $X$ na osi | Zrzut ekranu | Stałość tła | Trafienie markera |
| :--- | :--- | :---: | :---: | :---: | :---: | :--- | :---: | :---: |
| **ACTIVITY** | START | $0.00\text{ s}$ | `04:55:50.800` | `0.97816` (97.82%) | $503.9\text{ px}$ | `activity_start.png` | TAK (100%) | $\le 1\text{ px}$ |
| **ACTIVITY** | MIDDLE | $18.87\text{ s}$ | `04:56:09.670` | `0.98924` (98.92%) | $507.0\text{ px}$ | `activity_middle.png` | TAK (100%) | $\le 1\text{ px}$ |
| **ACTIVITY** | END | $37.74\text{ s}$ | `04:56:28.540` | `1.00000` (100.00%) | $510.0\text{ px}$ | `activity_end.png` | TAK (100%) | $\le 1\text{ px}$ |
| **VIDEO** | START | $0.00\text{ s}$ | `04:55:50.800` | `0.00000` (0.00%) | $231.0\text{ px}$ | `video_start.png` | TAK (100%) | $\le 1\text{ px}$ |
| **VIDEO** | MIDDLE | $18.87\text{ s}$ | `04:56:09.670` | `0.50726` (50.73%) | $372.5\text{ px}$ | `video_middle.png` | TAK (100%) | $\le 1\text{ px}$ |
| **VIDEO** | END | $37.74\text{ s}$ | `04:56:28.540` | `1.00000` (100.00%) | $510.0\text{ px}$ | `video_end.png` | TAK (100%) | $\le 1\text{ px}$ |

*Wszystkie 6 plików PNG zostały wygenerowane i zapisane w katalogu `Raporty/etap8m4_artifacts/`.*

---

## N. Wyniki testów automatycznych
Nowy zestaw dedykowanych testów w [tests/test_etap8m4_chart_time_scope.py](file:///c:/_DEV/TeleM/tests/test_etap8m4_chart_time_scope.py):
1. `test_default_scope_is_activity` — **PASSED**
2. `test_activity_scope_spans_full_fit_duration` — **PASSED**
3. `test_video_scope_clips_to_video_range` — **PASSED**
4. `test_marker_position_activity_mode` — **PASSED**
5. `test_marker_position_video_mode` — **PASSED**
6. `test_points_geometry_timestamp_proportional` — **PASSED**
7. `test_chart_bg_cache_key_includes_scope_and_bounds` — **PASSED**
8. `test_current_value_unaffected_by_chart_time_scope` — **PASSED**
9. `test_layout_persistence_chart_time_scope` — **PASSED**
10. `test_preview_and_final_chart_parity` — **PASSED**

### Wynik pełnego pakietu testów regresyjnych (`pytest`):
```text
362 passed, 3 failed (pre-existing legacy ABI/QP tests), 17 skipped in 21.72s
```
*Zero regresji w istniejących modułach TeleM.*

---

## O. Zmodyfikowane i utworzone pliki
1. `src/indicators/chart_builder.py` — obsługa `chart_start_dt`, `chart_end_dt`, `time_scope` w `ChartHistory`, `build_chart_data` oraz `clip_chart_data`.
2. `src/indicators/chart_utils.py` — timestamp-based geometry w `_build_chart_bg`, rozszerzony `_history_chart_cache_key`, obsługa współrzędnych kursora w `generate_history_chart`.
3. `src/indicators/chart.py` — wyliczanie współrzędnych markera w `_render_chart_indicator`, uniwersalna obsługa współrzędnych kursora w `_cursor_tile_bbox` i `_draw_post_paste_cursor`.
4. `src/gui/indicator_schemas.py` — dodanie pola `chart_time_scope` do schematów.
5. `src/gui/qt/models.py` — definicja `FieldSchema` z opcjami `[("activity", "Cała aktywność"), ("video", "Zakres filmu")]`.
6. `src/gui/qt/widgets/property_editor.py` — obsługa krotek `(data, label)` dla pól typu `choice` i synchronizacja `userData`.
7. `src/gui/qt/_mixins/preset_mixin.py` — inwalidacja cache przy zmianie `chart_time_scope`.
8. `src/gui/qt/_mixins/preview_mixin.py` — przekazywanie `source_activity_ranges` do `build_chart_data`.
9. `src/ffmpeg/worker_cache.py` — przekazywanie `source_activity_ranges` w procesach renderujących.
10. `src/gui/qt/tabs/render_tab.py` — przekazywanie `source_activity_ranges` w podglądzie HUD.
11. `tests/test_etap8m4_chart_time_scope.py` — kompletna suita 10 testów automatycznych.
12. `tests/test_etap8e_full_activity_charts.py` — dostosowanie testu do jawnego trybu `video`.
13. `scratch/validate_real_materials.py` — skrypt weryfikacji na rzeczywistym materiale `GX020079.mp4` + `Morning_Ride.fit`.
14. `Raporty/etap8m4_artifacts/` — 6 zrzutów porównawczych (`activity_start.png`, `activity_middle.png`, `activity_end.png`, `video_start.png`, `video_middle.png`, `video_end.png`).

---

## P. Wnioski i status etapu
- Wymagania **ETAPU 8M.4** zostały zrealizowane w 100%.
- Użytkownik ma pełną kontrolę nad perspektywą wykresu: może w dowolnej chwili wybrać `Cała aktywność` lub `Zakres filmu`.
- Pozycja markera jest wyliczana matematycznie ze 100% precyzją ($\le 1\text{ px}$).
- Wartości bieżące są w pełni odizolowane i niezmienne.
- Całość zweryfikowana na rzeczywistym zestawie danych i zatwierdzona testami jednostkowymi oraz integracyjnymi.
- **Status etapu: ZAKOŃCZONY POMYŚLNIE.**
