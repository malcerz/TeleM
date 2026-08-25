# TeleM — ETAP 10G: Optymalizacja `time_display`

## Status i decyzja

**TIME_DISPLAY OPTIMIZATION: SUCCESS**

---

## 1. Baseline

Przed optymalizacją (zgodnie z pomiarami z `RAPORT_INDICATORS_ETAP_10F`):
- `time_display` renderer: **3.450 ms/frame**
- `time_display` placement: **0.385 ms/frame**
- `time_display` total: **3.834 ms/frame** (37.0% łącznego czasu `CPU_BELOW_MAP`)
- Całkowity `CPU_BELOW_MAP compose_overlay`: **10.491 ms/frame**

---

## 2. Profil wewnętrzny przed optymalizacją (Micro-breakdown)

| Komponent wewnątrz `render_time_display` | Średni czas | Udział |
|---|---:|---:|
| `draw.text` (4 linie z obrysem `stroke_width=outline`) | **2.841 ms** | 82.5% |
| Ładowanie fontów i pomiary `font.getlength()` | **0.170 ms** | 4.9% |
| Generowanie / rasteryzacja ikony Clock | **0.025 ms** | 0.7% |
| Alokacja `Image.new("RGBA")` + kompozycja ikony | **0.028 ms** | 0.8% |
| Formatowanie napisów i klucz cache | **0.008 ms** | 0.2% |
| `tmp.getbbox()` (pełny skan alpha) + `tmp.crop()` | **0.019 ms** | 0.6% |
| Pozostały narzut Pillow / alokacje | **0.359 ms** | 10.3% |

---

## 3. Dokładna przyczyna kosztu (Root Cause)

1. **Kosztowna rasteryzacja obrysu tekstu w Pillow (`draw.text(stroke_width=...)`)**:
   - Pillow wykonuje wieloprzebiegową konwolucję / dylatację glifów dla każdego wywołania `draw.text` z obrysem.
   - W `time_display` rysowane są aż 4 niezależne linie (Data, Godzina, Czas/Activity, Średnia prędkość), co sumowało się do ~2.84 ms przy każdym renderowaniu.
2. **Częste odświeżanie całościowego widgetu**:
   - Zmiana dowolnego pojedynczego pola (np. sekundy czasu lub ułamka średniej prędkości) powodowała ponowne mierzenie i rysowanie od zera wszystkich 4 linii oraz ikony zegara.
3. **Brak buforowania pośrednich kafelków linii i metryk tekstu**:
   - Rzadko zmieniające się napisy (np. Data, etykiety `Date:`, `Time:`, `Activity:`, `Avg speed:`) oraz ikona zegara były generowane na nowo na klatkach z cache miss.

---

## 4. Wykonane optymalizacje

1. **Kafelkowanie linii tekstu (`_LINE_TILE_CACHE`)**:
   - Każda linia tekstu jest renderowana do niezależnego małego kafelka RGBA i buforowana w bounded LRU cache (`max_entries=64`).
   - Gdy zmienia się tylko jedna linia (np. `Godzina` przeskakuje o sekundę), linie `Data`, `Czas` oraz `Średnia prędkość` są natychmiast pobierane z cache kafli bez ponownego rysowania fontów.
2. **Buforowanie ikony zegara (`_ICON_CACHE`)**:
   - Ikona zegara `Clock` jest renderowana raz dla danego rozmiaru i buforowana w pamięci podręcznej.
3. **Buforowanie metryk tekstu (`_TEXT_METRIC_CACHE`)**:
   - Szerokości `getlength()` i wysokości linii `lh` są buforowane pod kluczem `(font_path, fs, outline, text)`.
4. **Szybka kompozycja `alpha_composite`**:
   - Kafelki linii i ikona są nanoszone na płótno widgetu za pomocą natywnego `alpha_composite` (czas kompozycji < 0.03 ms zamiast 2.84 ms rysowania wektorowego).
5. **Zachowanie zewnętrznego cache widgetu (`_STATIC_CACHE`)**:
   - Gotowy zmontowany widget jest buforowany całościowo, co daje czas **0.006 ms** dla klatek wewnątrz tej samej sekundy.

---

## 5. Podział Static vs Dynamic

- **100% Statyczne w trakcie wideo**:
  - Ikona `Clock`
  - Linia `Date` (np. `Date: 2026.08.14`)
  - Etykiety linii (`Date:`, `Time:`, `Activity:`, `Avg speed:`)
- **Półstatyczne (zmieniające się co 60 klatek przy 60 FPS)**:
  - `Time` (np. `Time: 11:18:10`)
  - `Elapsed / Activity` (np. `Activity: 00:07`)
- **Dynamiczne**:
  - `Avg speed` (np. `Avg speed: 28.6 km/h`)

---

## 6. Klucze i limity pamięci podręcznej

- `_LINE_TILE_CACHE`: bounded LRU, limit **64 wpisy**, klucz `("td_line", font_path, fs, text, fill, outline, tw, lh)`.
- `_ICON_CACHE`: bounded LRU, limit **16 wpisów**, klucz `(icon_name, icon_size)`.
- `_TEXT_METRIC_CACHE`: słownik z limitem **256 wpisów**, klucz `(font_path, fs, outline, text)`.
- `_STATIC_CACHE`: bounded LRU, limit **128 wpisów**, klucz całościowy widgetu.

---

## 7. Pixel Parity (100% Byte-Exact)

Przetestowano zestaw reprezentatywnych momentów i stylów:
- `t = 60.0 s` (standard v10): **max diff = 0**
- `t = 180.0 s` (standard v10): **max diff = 0**
- `t = 300.0 s` (standard v10): **max diff = 0**
- Font `Comic Sans`: **max diff = 0**
- Font `Digital-7`: **max diff = 0**
- Font `Iona-u1`: **max diff = 0**
- Czas trwania > 1h (`3725 s` -> format `HH:MM:SS`): **max diff = 0**

---

## 8. Dynamic Correctness

Zweryfikowano poprawność dynamicznych zmian parametrów:
- Zmiana `time` ($t_1 \neq t_2$): **Distinct: True** (max diff = 255)
- Zmiana `date` ($d_1 \neq d_2$): **Distinct: True** (max diff = 255)
- Zmiana `elapsed` ($e_1 \neq e_2$): **Distinct: True** (max diff = 255)
- Zmiana `avg_speed` ($s_1 \neq s_2$): **Distinct: True** (max diff = 252)
- Zmiana `font` (Default -> Digital-7): **Distinct: True**
- Wyłączenie linii `show_avg_speed: false`: wysokość zmniejszona z 58 px do 43 px

---

## 9. Lokalny benchmark (120 klatek, 1280×720, v10)

| Metryka | Before | After | Redukcja / Speedup |
|---|---:|---:|---:|
| `time_display` renderer | 3.450 ms | **0.039 ms** (median 0.006 ms) | **~88x speedup** |
| `time_display` placement | 0.385 ms | **0.039 ms** | ~10x speedup |
| `time_display` TOTAL | **3.834 ms** | **0.078 ms** (median 0.042 ms) | **~49x speedup** |

---

## 10. Produkcyjny benchmark AMD Native (120 klatek, 1280×720, v10)

Uruchomiono pełny eksport AMD Native D3D11 (`120 klatek`, `2.0 s @ 60 FPS`, `cycling_dashboard_v10`, `AMD_CHART_PATH=CPU_REFERENCE`):

| Etap / Wskaźnik | Before (ETAP 10F) | After (ETAP 10G) |
|---|---:|---:|
| `CPU_BELOW_MAP compose_overlay` (avg) | 10.491 ms | **8.237 ms** |
| `CPU_BELOW_MAP compose_overlay` (median) | 8.470 ms | **6.381 ms** |
| `RENDER FPS` | ~20–25 fps | **31.010 fps** |
| `TRUE FPS` (z remuxem audio) | 6.69 fps | **12.769 fps** |
| Frame accounting (decoded / encoded / muxed) | 120 / 120 / 120 | **120 / 120 / 120 (100% exact)** |

---

## 11. Testy automatyczne

Uruchomiono zestaw 34 targetowanych testów:
- `tests/test_time_display_optimization.py` (5 testów: cache hit parity, dynamic changes, font invalidation, bounded cache limits, disabled/empty fields)
- `tests/test_font_selection.py` (9 testów)
- `tests/test_gauge_rendering.py` (12 testów)
- `tests/test_chart_rendering.py` (8 testów)

**Wynik: 34 passed (100%)**

---

## 12. Zmienione pliki

- [src/indicators/time_display.py](file:///c:/_DEV/TeleM/src/indicators/time_display.py) — kafelkowanie linii tekstu, buforowanie ikony zegara i metryk tekstu, szybka kompozycja `alpha_composite`.
- [tests/test_time_display_optimization.py](file:///c:/_DEV/TeleM/tests/test_time_display_optimization.py) — zestaw testów jednostkowych i walidacyjnych optymalizacji Time Display.

---

## 13. Remaining Bottleneck & Next Target

Po zoptymalizowaniu `time_display` (z 3.834 ms do 0.078 ms) kolejnymi największymi wskaźnikami w warstwie `CPU_BELOW_MAP` są:
1. **`fit_battery_pct_text`** (Battery): ~2.897 ms
2. **`fit_solar_pct_text`** (Solar): ~1.921 ms
3. **`dist_visual`** (Distance Ruler): ~1.709 ms

**NEXT TARGET: Battery (`fit_battery_pct_text`) & Solar (`fit_solar_pct_text`)**
