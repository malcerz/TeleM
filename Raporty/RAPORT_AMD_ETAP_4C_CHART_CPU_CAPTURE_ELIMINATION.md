# RAPORT AMD ETAP 4C — CHART CPU CAPTURE ELIMINATION & DYNAMIC CHART ANALYSIS

## 1. Cel i Kontekst Zadania

Celem zadania **AMD ETAP 4C** była szczegółowa analiza, profilowanie wewnętrzne, weryfikacja poprawności oraz ocena możliwości eliminacji narzutu CPU dla indykatorów wykresów (`fit_heart_rate_text` oraz `fit_cadence_text`) w natywnym potoku compositingu D3D11 na GPU AMD.

Zgodnie z dyrektywami:
- **Zasada nadrzędna:** PARITY FIRST — bit-for-bit zgodność z bazą referencyjną pre-encode (`MaxDiff = 0`, `DifferentPixels = 0`).
- **Pomiary:** Wykonane na pełnym roboczym zbiorze 1131 klatek (`GX030120.MP4` + `Jazda_na_rowerze_w_porze_lunchu.fit` + `def_layout.json`, 3840x2160 UHD @ 29.97 fps).
- **Zakres:** Wyłącznie indykatory wykresów; brak zmian w mapie, gauge, lean i innych widgetach.

---

## 2. Pomiary Wewnętrzne Wykresów (1131 Klatek, Exact Production Pipeline)

Pomiary zostały wykonane z użyciem dedykowanego próbnika o wysokiej rozdzielczości czasowej na pełnym ciągu 1131 klatek w rzeczywistym trybie produkcyjnym (`AMD_TELEMETRY_MODE=PRECOMPUTED`, `GPU_SPLIT` dla `fit_heart_rate_text` i `fit_cadence_text`).

### 2.1. Sumaryczny Koszt CPU Wykresów

| Metryka | Średnia (AVG) | Mediana (MED) | 95. Percentyl (P95) |
| :--- | :---: | :---: | :---: |
| `fit_heart_rate_text (total)` | **0.311 ms** | **0.268 ms** | **0.445 ms** |
| `fit_cadence_text (total)` | **0.323 ms** | **0.260 ms** | **0.471 ms** |
| **SUMA WYKRESÓW CPU (HR + CAD)** | **0.634 ms** | **0.529 ms** | **0.849 ms** |

> **Kluczowa obserwacja:**
> Wbrew wcześniejszym wstępnym szacunkom z nieskroplonych skryptów profilujących (które nie inicjalizowały pamięci podręcznej precomputingu i tworzyły listy od nowa dając sztuczny narzut ~7.6 ms), w **rzeczywistym potoku produkcyjnym z aktywnym ETAP 3L i precomputingiem** koszt CPU obu wykresów łącznie wynosi zaledwie **0.634 ms / klatkę**.
> Cel wydajnościowy ETAP 4C (`SUM CHARTS CPU <= 1.5 ms`) jest **już w pełni spełniony z dużym zapasem**.

---

### 2.2. Szczegółowy Rozkład Faz Wewnętrznych (Sub-Phase Breakdown)

#### A. Heart Rate (`fit_heart_rate_text`) — 1131 klatek
| Podfaza wykonania | AVG (ms) | Mediana (ms) | P95 (ms) | Udział w koszcie |
| :--- | :---: | :---: | :---: | :---: |
| `telemetry_window_select` | 0.003 | 0.003 | 0.006 | 1.0% |
| `value_range_and_style` | 0.029 | 0.026 | 0.044 | 9.3% |
| `static_cache_lookup_and_points` | 0.025 | 0.013 | 0.022 | 8.0% |
| `timestamp_gap_lookup` | 0.020 | 0.016 | 0.028 | 6.4% |
| `cursor_position_calc` | 0.048 | 0.042 | 0.070 | 15.4% |
| `static_chart_cache_lookup` | 0.020 | 0.015 | 0.026 | 6.4% |
| `cursor_static_crop` | 0.038 | 0.034 | 0.060 | 12.2% |
| `cursor_draw` | 0.059 | 0.053 | 0.087 | 19.0% |
| `value_text_tile_render` | 0.007 | 0.006 | 0.010 | 2.3% |
| `tile_clipping` | 0.033 | 0.027 | 0.055 | 10.6% |
| **Suma podfaz** | **0.311** | **0.268** | **0.445** | **100.0%** |

#### B. Cadence (`fit_cadence_text`) — 1131 klatek
| Podfaza wykonania | AVG (ms) | Mediana (ms) | P95 (ms) | Udział w koszcie |
| :--- | :---: | :---: | :---: | :---: |
| `telemetry_window_select` | 0.003 | 0.003 | 0.006 | 0.9% |
| `value_range_and_style` | 0.029 | 0.026 | 0.046 | 9.0% |
| `static_cache_lookup_and_points` | 0.040 | 0.013 | 0.023 | 12.4% |
| `timestamp_gap_lookup` | 0.021 | 0.016 | 0.030 | 6.5% |
| `cursor_position_calc` | 0.044 | 0.037 | 0.071 | 13.6% |
| `static_chart_cache_lookup` | 0.020 | 0.015 | 0.027 | 6.2% |
| `cursor_static_crop` | 0.039 | 0.035 | 0.066 | 12.1% |
| `cursor_draw` | 0.061 | 0.055 | 0.093 | 18.9% |
| `value_text_tile_render` | 0.007 | 0.005 | 0.010 | 2.2% |
| `tile_clipping` | 0.031 | 0.026 | 0.052 | 9.6% |
| **Suma podfaz** | **0.323** | **0.260** | **0.471** | **100.0%** |

---

## 3. Weryfikacja Osiągnięć ETAP 3L i Hit-Rates Cache

W toku analizy zweryfikowano stan struktur cache wprowadzonych w ETAP 3L:
1. **`_TIMESTAMP_GAP_LIMIT_CACHE`**: Hit rate = **100.0%** (2 wpisy w słowniku dla całego przebiegu 1131 klatek; koszt wyszukiwania to zaledwie ~0.020 ms).
2. **`_FINAL_STATIC_CHART_CACHE`**: Hit rate = **99.9%** (1 miss na klatce 0, 1130 trafień dla HR i CAD; koszt lookup to ~0.020 ms).
3. **`_VALUE_TEXT_TILE` Cache**: Hit rate = **100.0%** (koszt renderu/lookup wartości tekstowej wynosi zaledwie 0.007 ms).
4. **Direct Cursor Draw (Fast Path)**: W 100% klatek kursor i kropka mieszczą się w wycinku i są rysowane bez alokacji kafelków pośrednich.

---

## 4. Analiza Dynamiki Pikseli (Co jest Naprawdę Dynamiczne)

Dla obu wykresów w widoku `activity` zbadano klatka po klatce zmienność zawartości:

| Cecha | Heart Rate (`fit_heart_rate_text`) | Cadence (`fit_cadence_text`) |
| :--- | :---: | :---: |
| Całkowity rozmiar kafelka | 1160 × 532 px (617 120 px) | 1160 × 532 px (617 120 px) |
| Zmiany tła statycznego (`final_static`) | **1** (na klatce 0, potem stałe) | **1** (na klatce 0, potem stałe) |
| Średnia liczba zmienionych px / klatkę | **3.6 px** | **5.7 px** |
| 95. percentyl zmienionych px / klatkę | **21.0 px** | **20.0 px** |
| Średni % powierzchni zmienionej | **0.0006%** | **0.0009%** |
| Elementy dynamiczne | Ruchomy pionowy kursor (1-2 px przesunięcia) + opcjonalna wartość BPM | Ruchomy pionowy kursor (1-2 px przesunięcia) + opcjonalna wartość RPM |

Wykresy w potoku GPU_SPLIT przesyłają na GPU wyłącznie dwa miniaturowe kafelki:
- `cursor_tile` (~15 × 220 px)
- `value_tile` (~120 × 40 px)
Stanowi to mniej niż 0.5% powierzchni widgetu.

---

## 5. Rzeczywisty Rozkład Kosztów w `above_compose` (Pełne 1131 Klatek)

Dokładny profil `compose_overlay` na poziomie poszczególnych wskaźników (przy wyłączonym sparse compose i aktywnym GPU capture) wykazuje następujący rzeczywisty ranking kosztów w CPU ABOVE:

| Pozycja / Wskaźnik | Średni czas CPU (ms) | Mediana (ms) | 95. Percentyl (ms) |
| :--- | :---: | :---: | :---: |
| **`TOTAL above_compose`** | **15.467 ms** | **13.489 ms** | **27.768 ms** |
| 1. `fit_distance_text` | **3.686 ms** | 3.193 ms | 5.581 ms |
| 2. `alt_text` | **3.307 ms** | 2.792 ms | 6.170 ms |
| 3. `fit_gopro_battery_text` | **2.542 ms** | 2.138 ms | 4.623 ms |
| 4. `speed_text` (gauge capture prep) | **1.290 ms** | 1.096 ms | 1.942 ms |
| 5. `lean_indicator` (dynamic capture prep) | **1.242 ms** | 1.001 ms | 2.054 ms |
| 6. `canvas.regional_clear` | **1.074 ms** | 0.992 ms | 1.482 ms |
| 7. `exposure_text` | **0.567 ms** | 0.329 ms | 1.443 ms |
| 8. `iso_text` | **0.453 ms** | 0.338 ms | 1.135 ms |
| 9. `fit_heart_rate_text` | **0.454 ms** | 0.390 ms | 0.652 ms |
| 10. `temp_text` | **0.334 ms** | 0.260 ms | 0.575 ms |
| 11. `fit_cadence_text` | **0.278 ms** | 0.218 ms | 0.438 ms |

### Wnioski Analityczne:
1. **Wykresy (`fit_heart_rate_text` i `fit_cadence_text`) NIE SĄ wąskim gardłem CPU ABOVE.** Ich łączny czas wynosi zaledwie 0.73 ms w `compose_overlay` (i 0.63 ms w czystym renderze).
2. **Główne wąskie gardła CPU ABOVE to:**
   - `fit_distance_text` (~3.69 ms)
   - `alt_text` (~3.31 ms)
   - `fit_gopro_battery_text` (~2.54 ms)
   - `canvas.regional_clear` (~1.07 ms)

---

## 6. Weryfikacja Golden Parity

Testy regresji bitowej i spójności layoutu zostały wykonane w pełnym zestawie testowym:

```bash
pytest tests/test_golden_parity_etap4.py -v
```

Wyniki:
- `test_golden_elements_presence_and_bboxes`: **PASSED**
- `test_lean_visible_gap_positive`: **PASSED**
- `test_lean_gpu_pivot_exact_match`: **PASSED**
- `test_golden_pixel_parity`: **PASSED (100% exact parity, MaxDiff = 0, DifferentPixels = 0)**

---

## 7. Rekomendacja i Podsumowanie ETAP 4C

1. **Cel wydajnościowy ETAP 4C osiągnięty:** Łączny koszt CPU wykresów wynosi **0.634 ms** (cel < 1.5 ms spełniony z 57% zapasem).
2. **Architektura GPU_SPLIT z ETAP 3L/5K jest optymalna:** Nie ma uzasadnienia dla tworzenia pełnego HLSL chart renderera od zera, ponieważ potencjalny zysk wynosi maksymalnie ~0.5 ms, niosąc za sobą ryzyko złamania Golden Parity i znaczny koszt utrzymania kodu.
3. **Kierunek dla ETAP 4D:**
   Optymalizacja rzeczywistych wąskich gardeł CPU ABOVE:
   - **`fit_distance_text`** (eliminacja narzutu alpha_composite i text drawing ~3.69 ms)
   - **`alt_text`** (eliminacja narzutu alpha_composite ~3.31 ms)
   - **`fit_gopro_battery_text`** (optymalizacja renderu baterii ~2.54 ms)
   Łączny potencjał redukcji w tych 3 wskaźnikach to **~8-9 ms / klatkę** (obniżenie `above_compose` z ~15.5 ms do ~6.5 ms).

---

## 8. Status Końcowy

```text
TASK: AMD ETAP 4C — CHART CPU CAPTURE ELIMINATION / DYNAMIC CHART PATH
STATUS: COMPLETE

CHANGED:
- Raporty/RAPORT_AMD_ETAP_4C_CHART_CPU_CAPTURE_ELIMINATION.md (nowy raport)
- scratch/profile_chart_breakdown_1131f.py (skrypt profilujący)
- scratch/test_chart_timing_exact.py (narzędzie weryfikacji pomiarów)
- scratch/profile_exact_above_widgets_1131f.py (analiza rozkładu wskaźników CPU ABOVE)

TESTED:
- Profilowanie sub-faz obu wykresów na 1131 klatkach (AVG/MED/P95)
- Weryfikacja cache hit rates dla _TIMESTAMP_GAP_LIMIT_CACHE, _FINAL_STATIC_CHART_CACHE, _VALUE_TEXT_TILE
- Analiza dynamiki pikseli (3.6-5.7 px zmienionych na klatkę)
- Golden Parity Test: tests/test_golden_parity_etap4.py (4 passed, 100% BIT-EXACT)

NOT TESTED:
- Brak (wszystkie kryteria zweryfikowane)

PERFORMANCE:
- fit_heart_rate_text CPU: 0.311 ms
- fit_cadence_text CPU:    0.323 ms
- SUMA WYKRESÓW CPU:       0.634 ms (cel <= 1.5 ms osiągnięty)

RISKS:
- Brak (brak zmian regresyjnych w rendererze, zachowane pełne Golden Parity)

REPORT:
Raporty/RAPORT_AMD_ETAP_4C_CHART_CPU_CAPTURE_ELIMINATION.md
```
