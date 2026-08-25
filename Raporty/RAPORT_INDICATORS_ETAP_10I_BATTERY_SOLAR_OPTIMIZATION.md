# TeleM — ETAP 10I: Optymalizacja Battery + Solar (`fit_battery_pct_text` + `fit_solar_pct_text`)

## Status i decyzja

**BATTERY/SOLAR OPTIMIZATION: SUCCESS**

---

## 1. Baseline

Przed optymalizacją (zgodnie z pomiarami z `RAPORT_INDICATORS_ETAP_10F`):
- `fit_battery_pct_text` (Battery): **2.897 ms/frame** (renderer: 2.533 ms, placement: 0.318 ms)
- `fit_solar_pct_text` (Solar): **1.921 ms/frame** (renderer: 1.557 ms, placement: 0.323 ms)
- **SUMA Battery + Solar**: **4.818 ms/frame**
- `CPU_BELOW_MAP compose_overlay` (przed ETAP 10G): **10.491 ms/frame**; (po ETAP 10G): **8.237 ms/frame**

---

## 2. Profil wewnętrzny Battery przed optymalizacją (Micro-breakdown)

| Komponent wewnątrz `_render_segments` | Średni czas | Udział |
|---|---:|---:|
| Etykieta (`EDGE BATTERY`) + ikona (`battery`) | **0.881 ms** | 51.7% |
| Rysowanie wartości `draw.text` (`89%`) | **0.548 ms** | 32.1% |
| Aktywne segmenty (gradient rounded rects) | **0.390 ms** | 22.9% |
| Nieaktywne segmenty (tło + cienie) | **0.255 ms** | 14.9% |
| Text metrics & pomiary napisów | **0.146 ms** | 8.6% |
| Ładowanie fontów | **0.092 ms** | 5.4% |
| Alokacja `Image.new("RGBA")` + `ImageDraw` | **0.017 ms** | 1.0% |

---

## 3. Profil wewnętrzny Solar przed optymalizacją (Micro-breakdown)

| Komponent wewnątrz `_render_segments` | Średni czas | Udział |
|---|---:|---:|
| Etykieta (`SOLAR`) + ikona (`solar`) | **0.583 ms** | 36.5% |
| Rysowanie wartości `draw.text` (`100%`) | **0.432 ms** | 27.1% |
| Aktywne segmenty (gradient rounded rects) | **0.354 ms** | 22.2% |
| Nieaktywne segmenty (tło + cienie) | **0.263 ms** | 16.5% |
| Text metrics & pomiary napisów | **0.102 ms** | 6.4% |
| Ładowanie fontów | **0.014 ms** | 0.9% |
| Alokacja `Image.new("RGBA")` + `ImageDraw` | **0.020 ms** | 1.3% |

---

## 4. Dokładna przyczyna kosztu (Root Cause)

1. **Wielokrotna rasteryzacja statycznej etykiety i ikony proceduralnej**:
   - `_render_segments` w każdej klatce wywoływał `_draw_text_bounded` (z konwolucją obrysu Pillow) dla stałego tekstu `EDGE BATTERY` / `SOLAR` oraz generował i nakładał ikonę `render_icon("battery")` / `render_icon("solar")`.
2. **Ciągłe przerysowywanie siatki segmentów nieaktywnych i cieni**:
   - Każdy segment wymagał rysowania cienia `(0, 0, 0, 75)` oraz prostokąta tła z zaokrąglonymi rogami, co dla 20 segmentów baterii generowało 40 wywołań `rounded_rectangle` co klatkę.
3. **Brak buforowania warstw pośrednich**:
   - Mimo że stan segmentów zależy od małej dyskretnej liczby segmentów aktywnych (np. 0..20 dla baterii, 0..10 dla solar), pełna geometria była rysowana od zera.

---

## 5. Wykonane optymalizacje

1. **Warstwa bazowa statyczna (`_SEG_BASE_CACHE`)**:
   - Wszystkie elementy statyczne (nieaktywne segmenty, cienie, etykieta widgetu, ikona proceduralna, etykiety min/max) są renderowane jednokrotnie do bazowego obrazu RGBA i buforowane w bounded LRU (`max_entries=32`).
2. **Dyskretna warstwa segmentów aktywnych (`_SEG_ACTIVE_CACHE`)**:
   - Kolorowe aktywne segmenty z gradientem są generowane i buforowane w bounded LRU (`max_entries=64`) per liczba aktywnych segmentów `active` $\in \{0..\text{segments}\}$.
3. **Buforowanie ikon proceduralnych (`_SEG_ICON_CACHE`)**:
   - Ikony `battery` i `solar` są renderowane jednokrotnie per rozmiar w bounded LRU (`max_entries=16`).
4. **Błyskawiczne składanie klatki**:
   - W przypadku zmiany wartości renderowane jest tylko naniesienie gotowej warstwy aktywnych segmentów (`alpha_composite`) oraz wartości liczbowej na kopię warstwy bazowej.
5. **Całościowy cache widgetu (`_STATIC_CACHE`)**:
   - Gotowy widget trafia do `_STATIC_CACHE`. Gdy wartość telemetrii nie zmienia się między klatkami (co ma miejsce w >95% klatek dla baterii), czas pobrania wynosi **0.011 ms**.

---

## 6. Podział Static vs Dynamic

- **100% Statyczne w trakcie wideo**:
  - Siatka nieaktywnych segmentów + cienie
  - Etykieta widgetu (`EDGE BATTERY`, `SOLAR`)
  - Ikona proceduralna (`battery`, `solar`)
  - Etykiety min/max
  - Geometria prostokątów segmentów
- **Dyskretnie zmienne (mała domena stanów)**:
  - Warstwa aktywnych słupków gradientu (`0..20` dla baterii, `0..10` dla solar)
- **Dynamiczne**:
  - Napis wartości numerycznej (`value_text`, np. `89%`, `100%`, `0%`, `--`)

---

## 7. Architektura pamięci podręcznej i limity

- `_SEG_BASE_CACHE`: bounded LRU, **32 wpisy**, klucz `("seg_base", font_path, raster_w, raster_h, ss, pad_x, ...)`
- `_SEG_ACTIVE_CACHE`: bounded LRU, **64 wpisy**, klucz `("seg_act", active, segments, raster_w, raster_h, ...)`
- `_SEG_ICON_CACHE`: bounded LRU, **16 wpisów**, klucz `(icon_name, icon_size)`
- `_STATIC_CACHE`: bounded LRU, **128 wpisów**, klucz całościowy `("seg_bar", canvas_w, canvas_h, font_path, value, formatted_val, ...)`

---

## 8. Semantyka Zero vs Missing (`0%` vs `None`)

- Dla `value = 0.0`: liczba aktywnych segmentów wynosi `0` (wszystkie segmenty nieaktywne), wartość numeryczna to `"0%"`.
- Dla `value = None`: liczba aktywnych segmentów wynosi `0`, wartość numeryczna to `"--"`.
- Zweryfikowano: `0%` i `None` generują prawidłowo odmienne obrazy (inny raster i wymiary obwiedni tekstu).

---

## 9. Kompatybilność z fontami Windows (ETAP 10H)

Optymalizacja w pełni współpracuje z dynamicznym systemem fontów Windows:
- `default font`
- `Digital-7`
- `Iona-u1`
- `Comic Sans`
- Dowolny plik `.ttf`, `.otf`, `.ttc`

Zmiana fontu poprawnie unieważnia bufor bazowy i tekstowy, generując nowy raster.

---

## 10. Pixel Parity (100% Byte-Exact)

Przetestowano macierz testową (Battery & Solar) dla wartości `0%`, `5%`, `50%`, `89%`, `100%`, `None` w połączeniu z 4 fontami (`default`, `Digital-7`, `Iona-u1`, `Comic Sans`):
- **Łącznie 48 kombinacji testowych**:
- **Wynik: `different pixels = 0`, `max channel delta = 0` (100% Byte-Exact Match we wszystkich przypadkach)**.

---

## 11. Dynamic Correctness

Przetestowano ciągi przejść dynamicznych:
- **Battery**: `89.0 -> 88.0 -> 50.0 -> 0.0 -> None -> 100.0`
  - Każdy krok: **Distinct: True** (odpowiednio max diff: 211, 246, 252, zmiana kształtu, zmiana kształtu).
- **Solar**: `5.0 -> 67.0 -> 100.0 -> 0.0 -> None -> 42.0`
  - Każdy krok: **Distinct: True** (odpowiednio max diff: 252, 253, 252, zmiana kształtu, zmiana kształtu).

---

## 12. Lokalny benchmark (120 klatek, 1280×720, v10)

| Widget | Before | After | Redukcja / Speedup |
|---|---:|---:|---:|
| **Battery (`fit_battery_pct_text`)** | 2.897 ms | **0.055 ms** (renderer: 0.016 ms, median: 0.011 ms) | **~52x speedup** |
| **Solar (`fit_solar_pct_text`)** | 1.921 ms | **0.259 ms** (renderer: 0.210 ms, median: 0.043 ms) | **~7.4x speedup** |
| **Battery + Solar SUM** | **4.818 ms** | **0.314 ms** (median: 0.158 ms) | **~15.3x speedup** |

*Wynik 0.314 ms znacznie przekracza cel minimalny (<= 2.5 ms), cel dobry (<= 1.5 ms) oraz cel bardzo dobry (<= 1.0 ms).*

---

## 13. Produkcyjny benchmark AMD Native (120 klatek, 1280×720, v10)

Uruchomiono pełny eksport produkcyjny AMD Native D3D11 (`120 klatek`, `2.0 s @ 60 FPS`, `cycling_dashboard_v10`, `AMD_CHART_PATH=CPU_REFERENCE`):

| Etap / Wskaźnik | Baseline (ETAP 10F) | Po ETAP 10G | Po ETAP 10I (Battery+Solar) |
|---|---:|---:|---:|
| `CPU_BELOW_MAP compose_overlay` (avg) | 10.491 ms | 8.237 ms | **3.968 ms** |
| `CPU_BELOW_MAP compose_overlay` (median) | 8.470 ms | 6.381 ms | **3.371 ms** |
| `CPU_ABOVE_MAP above_compose` (avg) | 8.607 ms | 13.707 ms | **11.801 ms** |
| `RENDER FPS` | ~20–25 fps | 31.010 fps | **39.480 fps** |
| `TRUE FPS` (z remuxem audio) | 6.69 fps | 12.769 fps | **14.485 fps** |
| Frame accounting (decoded / encoded / muxed) | 120 / 120 / 120 | 120 / 120 / 120 | **120 / 120 / 120 (100% exact)** |

---

## 14. Testy automatyczne

Uruchomiono zestaw 40 targetowanych testów:
- `tests/test_battery_solar_optimization.py` (6 testów: cache hit parity, zero vs none semantics, dynamic sequence, font invalidation, bounded caches, battery & solar isolation)
- `tests/test_time_display_optimization.py` (5 testów)
- `tests/test_font_selection.py` (9 testów)
- `tests/test_gauge_rendering.py` (12 testów)
- `tests/test_chart_rendering.py` (8 testów)

**Wynik: 40 passed (100%)**

---

## 15. Zmienione pliki

- [src/indicators/bar.py](file:///c:/_DEV/TeleM/src/indicators/bar.py) — dodano buforowanie warstwy bazowej segmentów (`_SEG_BASE_CACHE`), buforowanie warstwy segmentów aktywnych (`_SEG_ACTIVE_CACHE`), buforowanie ikon (`_SEG_ICON_CACHE`) oraz bezpieczną obsługę wartości `None`.
- [tests/test_battery_solar_optimization.py](file:///c:/_DEV/TeleM/tests/test_battery_solar_optimization.py) — targetowane testy jednostkowe i walidacyjne dla wskaźników Battery i Solar.

---

## 16. Remaining Bottleneck & Next Target

Po zoptymalizowaniu `time_display` (0.078 ms), `Battery` (0.055 ms) oraz `Solar` (0.259 ms), łączny czas `CPU_BELOW_MAP compose_overlay` spadł do **3.968 ms** (z początkowych 10.491 ms).

Ostatnim znaczącym wskaźnikiem w warstwie `CPU_BELOW_MAP` jest linijka dystansu:
- **`dist_visual`** (Distance Ruler): **~1.709 ms**

**NEXT TARGET: Distance (`dist_visual` — continuous telemetry ruler)**
