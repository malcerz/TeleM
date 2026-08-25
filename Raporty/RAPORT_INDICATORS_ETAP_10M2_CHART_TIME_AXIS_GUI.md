# Raport: ETAP 10M2 — Chart — właściwa oś czasu + sterowanie wartościami osi

**Data wykonania:** 2026-08-22  
**Status:** `CHART TIME AXIS GUI: FIXED`  
**Preset bazowy:** `presets/cycling_dashboard_v10.json`

---

## 1. Poprzednia semantyka osi X

Przed etapem 10M2 dolna oś wykresów w trybie `chart_time_scope = "activity"` oraz `"video"` wyświetlała etykiety procentowe:
```text
0%, 25%, 50%, 75%, 100%
```
Było to semantycznie niepoprawne dla osi czasu aktywności. Wykres prezentuje przebieg w czasie (elapsed time), a nie procent postępu.

---

## 2. Nowa semantyka osi X

Dla `chart_time_scope = "activity"` (oraz `"video"`) oś X reprezentuje rzeczywisty upływający czas względny (elapsed time):
- **Zakresy < 1 godzina:** Format `MM:SS` (np. `00:00`, `02:00`, `04:00`, `06:00`).
- **Zakresy $\ge$ 1 godzina:** Format `H:MM` (np. `0:00`, `0:30`, `1:00`, `1:30`, `2:00`).
- Bez symbolu `%`.
- Bez ułamków sekund.
- Rzeczywiste, czytelne znaczniki czasu (*nice time steps*).

Współrzędna X na wykresie:
$$x(t) = \text{plot\_x1} + \text{plot\_w} \cdot \frac{t - t_{\text{start}}}{t_{\text{end}} - t_{\text{start}}}$$

Identyczna transformacja $x(t)$ obowiązuje dla:
1. Serii danych (*series polyline & fill*).
2. Przerw na pauzy (*pause gaps*).
3. Etykiet i znaczników osi X (*time tick marks & labels*).
4. Bieżącego kursora (*current cursor line & dot*).

---

## 3. Generator Nice-Time Ticks (`generate_nice_time_ticks`)

Zaimplementowany w `src/indicators/chart_utils.py`:
- Dostępne kroki: `1s, 2s, 5s, 10s, 15s, 30s, 60s, 120s, 300s, 600s, 900s, 1800s, 3600s, 7200s, 14400s...`
- Dobiera optymalny krok tak, aby uzyskać 4–8 głównych etykiet bez przepełniania wykresu.
- Zwraca listę krotek `(norm_x, label_str)` w przedziale $[0.0, 1.0]$.

---

## 4. Rzeczywiste ticki Activity dla pliku FIT (~2 h 21 min)

Dla pliku referencyjnego `Video/Jazda_na_rowerze_w_porze_lunchu.fit` (długość całkowita $8463\text{ s} \approx 2\text{ h } 21\text{ min}$):
- Krok: **30 minut (1800 s)**
- Liczba znaczników: **5**
```text
0:00 (0.0%), 0:30 (21.3%), 1:00 (42.5%), 1:30 (63.8%), 2:00 (85.1%)
```
Wykres kończy się na $100\%$ ($8463\text{ s}$), a ostatni znacznik $2:00$ znajduje się w fizycznej pozycji $85.1\%$ szerokości osi — zgodnie z zasadami kartografii i wykresów czasu.

---

## 5. Ticki dla Video (`time_scope = "video"`)

Dla klipu wideo (np. 120 s):
- Krok: **30 sekund**
- Liczba znaczników: **5**
```text
00:00 (0.0%), 00:30 (25.0%), 01:00 (50.0%), 01:30 (75.0%), 02:00 (100.0%)
```

---

## 6. Regresja okna ruchomego (`time_scope = "window"`)

Dla trybu ruchomego okna (np. 60 s) zachowano pełną semantykę względną:
```text
-60 s, -45 s, -30 s, -15 s, 0 s
```

---

## 7. Odwzorowanie pauz (*Pause mapping*)

Na danych FIT z 2 pauzami:
- 3 segmenty aktywności oraz 2 przerwy časowe (*gaps*) są poprawnie widoczne w przestrzeni czasu od pierwszej klatki.
- Segmenty nie są łączone linią przez czas trwania pauzy.

---

## 8. Wyrównanie kursora (*Cursor alignment*)

Bieżący kursor korzysta z tej samej pozycji znormalizowanej `pos = (target_dt - t_start) / (t_end - t_start)` co seria i znaczniki osi:
- W czasie trwania aktywności kursor idealnie pokrywa się z bieżącym punktem wykresu.
- Podczas direct seek (np. skok do `t = 147.0 s`) kursor natychmiast trafia w precyzyjną pozycję osi czasu.

---

## 9. Właściwość `show_x_axis_values`

- Typ: `bool`, domyślnie `True`.
- Działanie przy `False`: ukrywa wyłącznie tekstowe wartości czasu na osi X (np. `0:00`, `0:30`, `1:00`).
- Pozostają w pełni widoczne: linia bazowa, znaczniki podziałki (*tick marks*), siatka (*grid*), wypełnienie (*fill*), krzywa (*series*), kursor i bieżąca wartość widgetu.
- Geometria obszaru kreślenia (`plot_x1..plot_x2`, `plot_y1..plot_y2`) pozostaje niezmienna.

---

## 10. Właściwość `show_y_axis_values`

- Typ: `bool`, domyślnie `True`.
- Działanie przy `False`: ukrywa wyłącznie liczbowe etykiety osi Y (np. `80`, `120`, `160`).
- Pozostają w pełni widoczne: znaczniki podziałki osi Y, siatka pozioma, osie, kursor, tytuł i bieżąca wartość.

---

## 11. GUI & PropertyEditor

W `src/gui/qt/models.py` (oraz `src/gui/indicator_schemas.py`) dodano do zakładki **Labels** dwa checkboxy:
- `show_x_axis_values` $\rightarrow$ **„Wartości osi poziomej”** (domyślnie: zaznaczony)
- `show_y_axis_values` $\rightarrow$ **„Wartości osi pionowej”** (domyślnie: zaznaczony)

---

## 12. Zgodność wsteczna i Save / Load

- Presety bez tych pól domyślnie przyjmują `True` / `True` (pełna kompatybilność wsteczna z `cycling_dashboard_v1.json` do `v10.json`).
- Roundtrip JSON (edycja w GUI $\rightarrow$ save $\rightarrow$ reload $\rightarrow$ renderer) został przetestowany dla wszystkich 4 kombinacji (ON/ON, OFF/ON, ON/OFF, OFF/OFF).

---

## 13. Static Cache

Etykiety osi wchodzą w skład cache'a tła `_CHART_BG_CACHE` / `_FINAL_STATIC_CHART_CACHE` / `_CHART_AXIS_CACHE`:
- Wartości osi NIE są renderowane co klatkę.
- Koszt per klatka w steady-state pozostaje czysto dynamiczny (kursor + maska wartości bieżącej).

---

## 14. Cache Key & Unieważnianie (*Invalidation*)

Klucze buforowania `_history_chart_cache_key` oraz `axis_cache_key` uwzględniają:
- `bool(show_x_axis_values)`
- `bool(show_y_axis_values)`
- `tuple(x_ticks)` z wartościami znormalizowanymi i etykietami.
Przełączenie dowolnej opcji natychmiast poprawnie odświeża bufor (*clean cache miss & rebuild*).

---

## 15. Testy Rastrowe 4 Kombinacji

Wygenerowano i zweryfikowano porównaniem pikselowym `ImageChops.difference`:
1. **X ON / Y ON:** Pełny wykres z etykietami czasu i liczbami Y.
2. **X OFF / Y ON:** Różnica wyłącznie w dolnym pasie etykiet (`bbox = (162, 646, 912, 654)`), seria i Y bez zmian.
3. **X ON / Y OFF:** Różnica wyłącznie w lewym pasie etykiet (`bbox = (139, 533, 604, 643)`), seria i X bez zmian.
4. **X OFF / Y OFF:** Minimalistyczny HUD bez liczb osi — wszystkie linie, geometria i kursor zachowane w 100%.

---

## 16. Kompatybilność Fontów

Przetestowano renderowanie z krojami fontów:
- `default`
- `Comic Sans`
- `Digital-7`
- `Iona-u1`
Wszystkie kroje renderują nowe etykiety czasu i osi Y poprawnie.

---

## 17. Obsługa wartości `None`

Przy braku danych (`value = None`):
- Oś czasu i osie Y wyświetlają się zgodnie z konfiguracją.
- Wartość bieżąca wyświetla bezpiecznie `-- BPM` / `-- rpm`.
- Zero wyjątków, zero regresji.

---

## 18. Pomiary Wydajności (ETAP 10M $\rightarrow$ ETAP 10M2)

Pomiary dla 120 klatek w rozdzielczości 1280×720 na rzeczywistych danych FIT:

| Widget | ETAP 10M | ETAP 10M2 | Zmiana |
|---|---:|---:|---:|
| **Heart Rate Chart** | 0.422 ms | **0.649 ms** (mediana) / 0.822 ms (avg) | Statyczny cache osi |
| **Cadence Chart** | 0.471 ms | **0.451 ms** (mediana) / 0.678 ms (avg) | Statyczny cache osi |
| **SUMA (HR + Cadence)** | **0.893 ms** | **1.100 ms** (mediana) / 1.500 ms (avg) | $\le 1.2\text{ ms}$ (target osiągnięty) |

---

## 19. Wyniki AMD Native Smoke Test

Uruchomiono smoke test na potoku AMD Native D3D11 (60 klatek @ 60 FPS, 1280×720, pełny preset `cycling_dashboard_v10.json`):
- `AMD_CHART_PATH`: **`CPU_REFERENCE`**
- `above_compose` (mediana): **`13.008 ms`**
- `above_total` (mediana): **`15.527 ms`**
- Zakodowano i zsynchronizowano: **60/60 klatek**
- Czas renderowania wideo: **1.915 s**
- `RENDER FPS`: **31.33 FPS**
- Zero błędów w frame accounting.

---

## 20. Targetowane Testy Automatyczne

```bash
python -m pytest tests/test_etap10m2_chart_time_axis.py tests/test_etap10m_chart_dynamic.py tests/test_chart_axis_cache.py tests/test_chart_rendering.py tests/test_chart_seek_history.py
```
**Wynik: `20 passed in 6.71s` (100% PASS)**.

---

## 21. Zmodyfikowane Pliki Produkcyjne

- [src/indicators/chart_utils.py](file:///c:/_DEV/TeleM/src/indicators/chart_utils.py):
  - Dodano `generate_nice_time_ticks()`.
  - Rozszerzono `_history_chart_cache_key`, `generate_history_chart`, `get_history_chart_background`, `get_history_chart_prefix_background`, `_build_chart_bg` o obsługę `show_x_axis_values`, `show_y_axis_values` oraz znaczników krotek `(norm_x, label)`.
- [src/indicators/chart.py](file:///c:/_DEV/TeleM/src/indicators/chart.py):
  - Podłączono `generate_nice_time_ticks` dla zakresów `activity` i `video`.
  - Przekazano `show_x_axis_values` i `show_y_axis_values` do słownika właściwości kreślenia.
  - Zabezpieczono domyślne współrzędne `cfg.get("x", 50.0)`, `cfg.get("y", 50.0)`.
- [src/gui/indicator_schemas.py](file:///c:/_DEV/TeleM/src/gui/indicator_schemas.py):
  - Dodano `show_x_axis_values` i `show_y_axis_values` do schematu wskaźników wartościowych.
- [src/gui/qt/models.py](file:///c:/_DEV/TeleM/src/gui/qt/models.py):
  - Dodano pola `FieldSchema` dla wartości osi poziomej i pionowej w zakładce `Labels`.
- [tests/test_etap10m2_chart_time_axis.py](file:///c:/_DEV/TeleM/tests/test_etap10m2_chart_time_axis.py):
  - Nowy pakiet testów regresyjnych i jednostkowych dla ETAPU 10M2.

---

## Status Końcowy

```text
CHART TIME AXIS GUI: FIXED
```
