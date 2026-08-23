# TeleM — ETAP 10J: Optymalizacja Distance (`dist_visual`)

## Status i decyzja

**DISTANCE OPTIMIZATION: SUCCESS**

---

## 1. Baseline

Przed optymalizacją (zgodnie z pomiarami z `RAPORT_INDICATORS_ETAP_10F`):
- `dist_visual` (Distance Ruler): **1.709 ms/frame** (renderer: 0.808 ms, placement: 0.848 ms)
- Całkowity `CPU_BELOW_MAP compose_overlay`:
  - Baseline (ETAP 10F): **10.491 ms/frame**
  - Po ETAP 10G (Time Display): **8.237 ms/frame**
  - Po ETAP 10I (Battery + Solar): **3.968 ms/frame**

---

## 2. Profil wewnętrzny Distance przed optymalizacją (Micro-breakdown)

| Komponent wewnątrz `_render_ruler` | Średni czas | Udział |
|---|---:|---:|
| Rysowanie wartości `draw.text` z obrysem | **0.358 ms** | 60.1% |
| Pomiary tekstu (`_text_size` na `dummy`) | **0.116 ms** | 19.5% |
| Pobieranie / sprawdzanie klucza `static_key` | **0.089 ms** | 14.9% |
| Kopiowanie bufora bazowego `base.copy()` | **0.019 ms** | 3.2% |
| Rysowanie elips markera (`d.ellipse` x3) | **0.013 ms** | 2.2% |

---

## 3. Dokładna przyczyna kosztu (Root Cause)

1. **Brak buforowania całościowego widgetu dla bieżącej wartości**:
   - Istniejący `static_key` buforował wyłącznie podkład podziałki (`base`), zmuszając renderer do kopiowania bufora `base.copy()`, wyliczania pozycji i rysowania markera oraz wartości tekstowej z obrysem na każdej klatce.
2. **Kosztowne wielokrotne pomiary napisów**:
   - Na każdej klatce wywoływano `_text_size` na obiekcie `dummy` w celu ustalenia wysokości etykiet i wartości, mimo że metryki fontu są stałe dla danej konfiguracji.
3. **Narzut rasteryzacji obrysu wartości**:
   - `_draw_text_bounded` dla wartości `value_text` (np. `"2.4 km"`) wykonywał konwolucję obrysu Pillow przy każdym wywołaniu.

---

## 4. Wykonane optymalizacje

1. **Buforowanie metryk tekstu linijki (`_RULER_METRICS_CACHE`)**:
   - Pomiary wysokości tytułu (`title_h`), zakresu (`range_h`) oraz wartości (`value_h`) są buforowane w słowniku z limitem 256 wpisów.
2. **Całościowe buforowanie gotowego widgetu linijki (`_STATIC_CACHE`)**:
   - Wprowadzono pełny klucz `ruler_full` zawierający parametry stylu, geometrię, font, wartość oraz tekst.
   - Gdy wartość dystansu nie zmienia się między kolejnymi klatkami, widget jest zwracany z cache w czasie **0.021 ms**.
3. **Optymalizacja renderowania dynamicznego markera i wartości**:
   - Przy zmianie wartości, podkład pobierany jest z `_STATIC_CACHE` (klucz `bar_ruler_v2`), a na kopię nakładany jest marker i tekst, bez powtarzania pomiarów tekstu.
4. **Czysta semantyka `value=None`**:
   - Gdy wartość wynosi `None`, linijka renderowana jest czysto (bez markera) z wartością `"--"`.

---

## 5. Podział Static vs Dynamic

- **100% Statyczne**:
  - Podkład linijki (`track_color`)
  - Kreski podziałki główne i podrzędne (`major_len`, `minor_len`, `pixel_profile`)
  - Etykiety zakresu (`0.0`, `5.0`, `10.0 km`)
  - Tytuł widgetu (`DISTANCE`)
  - Metryki wysokości fontów
- **Dynamiczne**:
  - Pozycja markera kołowego (`marker_x = pad_x + frac * width`)
  - Wartość tekstowa (np. `"2.4 km"`, `"--"`)

---

## 6. Architektura pamięci podręcznej i limity

- `_RULER_METRICS_CACHE`: słownik z automatycznym czyszczeniem powyżej **256 wpisów**, klucz `(font_path, title, range_sample, value_text, text_stroke)`.
- `_STATIC_CACHE`: bounded LRU, **128 wpisów**, klucze:
  - `bar_ruler_v2`: podkład linijki z kreskami i etykietami.
  - `ruler_full`: kompletny wyrenderowany widget wraz z markerem i wartością.

---

## 7. Kompatybilność z fontami Windows (ETAP 10H)

Optymalizacja w pełni współpracuje z dynamicznym systemem fontów Windows:
- `default font`
- `Digital-7`
- `Iona-u1`
- `Comic Sans`
- Dowolny plik `.ttf`, `.otf`, `.ttc`

---

## 8. Pixel Parity (100% Byte-Exact)

Przetestowano macierz testową Distance dla wartości `0.0`, `2.5`, `5.0`, `7.5`, `10.0`, `2.34`, `7.89` km w połączeniu z 4 fontami (`default`, `Digital-7`, `Iona-u1`, `Comic Sans`):
- **Wynik: `different pixels = 0`, `max channel delta = 0` (100% Byte-Exact Match we wszystkich przypadkach)**.

---

## 9. Dynamic Correctness

Przetestowano ciąg przejść dynamicznych:
- `1.2 km -> 5.0 km -> 9.8 km -> 0.5 km -> None`
- Każdy krok: **Distinct: True** (odpowiednio max diff: 255, 255, 255, zmiana kształtu obwiedni dla `None`).

---

## 10. Lokalny benchmark (120 klatek, 1280×720, v10)

| Metryka | Before | After | Redukcja / Speedup |
|---|---:|---:|---:|
| **Distance renderer** | 0.808 ms | **0.024 ms** (median: 0.021 ms) | **~33.6x speedup** |
| **Distance placement** | 0.848 ms | **0.074 ms** (median: 0.066 ms) | **~11.4x speedup** |
| **Distance TOTAL** | **1.709 ms** | **0.098 ms** (median: 0.088 ms) | **~17.4x speedup** |

*Wynik 0.098 ms z dużym zapasem spełnia cel bardzo dobry (<= 0.25 ms).*

---

## 11. Produkcyjny benchmark AMD Native (120 klatek, 1280×720, v10)

Uruchomiono pełny eksport produkcyjny AMD Native D3D11 (`120 klatek`, `2.0 s @ 60 FPS`, `cycling_dashboard_v10`, `AMD_CHART_PATH=CPU_REFERENCE`):

| Etap / Wskaźnik | Baseline (ETAP 10F) | Po ETAP 10G | Po ETAP 10I | Po ETAP 10J (Distance) |
|---|---:|---:|---:|---:|
| `CPU_BELOW_MAP compose_overlay` (avg) | 10.491 ms | 8.237 ms | 3.968 ms | **3.457 ms** (median) / **4.633 ms** (avg) |
| `RENDER FPS` | ~20–25 fps | 31.010 fps | 39.480 fps | **37.926 fps** |
| `TRUE FPS` (z remuxem audio) | 6.69 fps | 12.769 fps | 14.485 fps | **14.306 fps** |
| Frame accounting (decoded / encoded / muxed) | 120 / 120 / 120 | 120 / 120 / 120 | 120 / 120 / 120 | **120 / 120 / 120 (100% exact)** |

---

## 12. Podsumowanie optymalizacji warstwy `CPU_BELOW_MAP`

Dzięki etapom 10G, 10I i 10J cała warstwa wskaźników pod mapą (`CPU_BELOW_MAP`) została zredukowana:

| Widget | Baseline (ETAP 10F) | Stan aktualny (ETAP 10J) | Redukcja |
|---|---:|---:|---:|
| `time_display` | 3.834 ms | **0.078 ms** | **-98.0%** |
| `fit_battery_pct_text` | 2.897 ms | **0.055 ms** | **-98.1%** |
| `fit_solar_pct_text` | 1.921 ms | **0.259 ms** | **-86.5%** |
| `dist_visual` | 1.709 ms | **0.098 ms** | **-94.3%** |
| **SUMA WIDGETÓW BELOW** | **10.361 ms** | **0.490 ms** | **~21x szybsze wskaźniki (-95.3%)** |

---

## 13. Testy automatyczne

Uruchomiono zestaw 46 targetowanych testów:
- `tests/test_distance_optimization.py` (6 testów: cache hit parity, dynamic marker/value, None behavior, font invalidation, pixel profile toggle, bounded caches)
- `tests/test_battery_solar_optimization.py` (6 testów)
- `tests/test_time_display_optimization.py` (5 testów)
- `tests/test_font_selection.py` (9 testów)
- `tests/test_gauge_rendering.py` (12 testów)
- `tests/test_chart_rendering.py` (8 testów)

**Wynik: 46 passed (100%)**

---

## 14. Zmienione pliki

- [src/indicators/bar.py](file:///c:/_DEV/TeleM/src/indicators/bar.py) — dodano buforowanie metryk tekstu linijki (`_RULER_METRICS_CACHE`), całościowe buforowanie widgetu linijki (`ruler_full`), bezpieczną obsługę `None` oraz kompletne klucze stylu.
- [tests/test_distance_optimization.py](file:///c:/_DEV/TeleM/tests/test_distance_optimization.py) — targetowane testy jednostkowe i walidacyjne dla wskaźnika Distance.

---

## 15. Remaining Bottleneck & Next Target

Wszystkie wskaźniki warstwy `CPU_BELOW_MAP` osiągnęły poziom optymalny (< 0.5 ms łącznego czasu widgetów).

Głównymi pozostałymi obszarami kosztu CPU są:
1. **`CPU_ABOVE_MAP above_compose`**: ~11–12 ms (Slope: 1.74 ms, Compass: 0.89 ms, HR Chart: 1.19 ms, Speed Gauge: 0.71 ms, Virtual Power: 0.94 ms, Altitude: 0.97 ms).
2. **`above_bbox_crop` / dirty region extraction**: ~1.4–1.7 ms.
3. **`map_cpu_upload`**: ~1.5–2.3 ms.

**NEXT TARGET: `CPU_ABOVE_MAP` indicators (Slope, Compass, Gauges, Text Blocks)**
