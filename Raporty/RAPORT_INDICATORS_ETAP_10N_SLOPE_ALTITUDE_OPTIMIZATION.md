# Raport: ETAP 10N — Optymalizacja Slope + Altitude w `bar.py`

**Data wykonania:** 2026-08-22  
**Status:** `SLOPE + ALTITUDE OPTIMIZATION: SUCCESS`  
**Preset bazowy:** `presets/cycling_dashboard_v10.json`

---

## 1. Fresh Baseline: Slope (`slope_text`)

Świeży pomiar przed zmianami (120 klatek produkcyjnych w 1280×720):
- **Renderer:** `0.657 ms` (mediana: `0.530 ms`)
- **Placement / Blend:** `0.145 ms` (mediana: `0.103 ms`)
- **TOTAL Baseline:** `0.803 ms` (mediana: `0.633 ms`, P95: `1.677 ms`)

---

## 2. Fresh Baseline: Altitude (`alt_visual`)

Świeży pomiar przed zmianami (120 klatek produkcyjnych w 1280×720, `rotation = 90`):
- **Renderer:** `0.443 ms` (mediana: `0.367 ms`)
- **Placement / Rotated Paste:** `0.608 ms` (mediana: `0.489 ms`)
- **TOTAL Baseline:** `1.051 ms` (mediana: `0.856 ms`, P95: `2.358 ms`)

**Łączny koszt bazowy (SUM):** `1.853 ms/frame`

---

## 3. Micro-Profile: Slope

Rozbicie wewnętrznych operacji `_render_slope`:
```text
config/key preparation          : 0.0005 ms
font lookup                     : 0.0039 ms
text metrics / dummy allocation : 0.0126 ms
static ruler/background lookup  : 0.0018 ms
copy/allocation                 : 0.0085 ms
dynamic marker                  : 0.0071 ms
current value text              : 0.2867 ms (85.2% kosztu renderera)
```

---

## 4. Micro-Profile: Altitude

Rozbicie wewnętrznych operacji `_render_ruler` (dla Altitude):
```text
font lookup                     : 0.0042 ms
metrics cache lookup            : 0.0031 ms
static ruler/background lookup  : 0.0020 ms
copy/allocation                 : 0.0116 ms
dynamic marker                  : 0.0062 ms
current value text              : 0.2893 ms (87.4% kosztu renderera)
```

---

## 5. Root Cause każdego widgetu

1. **Rasteryzacja tekstu bieżącej wartości w każdej klatce:**
   - Wywołanie `_draw_text_bounded` wywoływało `draw.textbbox` oraz generowanie konturu (*TrueType stroke*) w Pillow per-frame (`~0.287 ms` dla Slope i `~0.289 ms` dla Altitude).
2. **Dynamiczne alokacje w Slope:**
   - `_render_slope` przy każdej klatce tworzyło obiekt `dummy = Image.new("RGBA", (16, 16))` i przeliczało podziałki oraz szerokości etykiet przed wyszukaniem tła.
3. **Nieoptymalny klucz cache'a w Ruler:**
   - `ruler_full` zawierał dynamiczny `val_num` typu float, co powodowało unieważnianie kluczy w ogólnym `_STATIC_CACHE` bez potrzeby.

---

## 6. Wykonane Zmiany

W pliku [src/indicators/bar.py](file:///c:/_DEV/TeleM/src/indicators/bar.py):
1. **Wdrożono `_draw_text_bounded_cached`:**
   - Dedykowany, ograniczony cache kafelków tekstu `_TEXT_TILE_CACHE = _BoundedStaticCache(max_entries=256)`.
   - Zamiast pełnej rasteryzacji TrueType w pętli renderowania, kafelek tekstu z konturem i poprawnym punktem zaczepienia (*anchor*) jest pobierany z cache i nakładany przez `alpha_composite` w czasie $< 0.005\text{ ms}$ (ponad 50x szybciej).
2. **Optymalizacja `_render_slope`:**
   - Dodano `_SLOPE_BASE_CACHE = _BoundedStaticCache(max_entries=32)`.
   - Wszystkie podziałki, geometria linijki i tytuł są budowane raz w statycznym kafelku tła.
   - Per-frame: wyłącznie kopia bufora, kursor i `_draw_text_bounded_cached`.
3. **Optymalizacja `_render_ruler` (Altitude & Distance):**
   - Dodano `_RULER_BASE_CACHE = _BoundedStaticCache(max_entries=64)`.
   - Usunięto nieefektywne zanieczyszczanie `_STATIC_CACHE` unikalnymi kluczami zmiennoprzecinkowymi.
   - Per-frame: kopia bufora bazowego, kursor i `_draw_text_bounded_cached`.

---

## 7. Podział Statyczne / Dynamiczne (*Static/Dynamic Split*)

- **Statyczne (Cache'owane w LRU):**
  - Tło, ramki, prowadnica (*track*), cienie podziałek.
  - Tytuł widgetu, jednostka, etykiety zakresu min/max/mid, linia zerowa.
  - Geometria znaczników podziałek głównych i pomocniczych.
- **Dynamiczne (Rysowane per-frame):**
  - Kursor / wskaźnik bieżącej wartości (znacznik pozycji na linijce).
  - Wartość bieżąca (tekst z bufora kafli).

---

## 8. Cache Keys

- **`_SLOPE_BASE_CACHE`:**
  `("bar_slope_base_v2", font_path, title, title_fs, tick_fs, value_fs, text_stroke, show_label, show_range, show_value, lo, hi, major_tick, minor_tick, track_color, tick_color, zero_color, text_color, dim_color, track_width, tick_width, major_len, minor_len, marker_width, marker_len, marker_radius, marker_color, marker_border, shadow_alpha, pixel_profile, ss, opacity, size_px, value_width)`
- **`_RULER_BASE_CACHE`:**
  `("bar_ruler_v3", raster_w, height, width, track_y, pad_x, pad_top, title, font_path, title_fs, label_fs, value_fs, text_stroke, show_title, show_range, show_mid, show_value, range_units, decimals, val_min, val_max, unit, major_divisions, minor_per_major, major_step, track_color, tick_color, text_color, dim_text, marker_color, marker_border, marker_radius, marker_border_w, line_w, tick_w, major_len, minor_len, pixel_profile, ss, title_h, title_gap, value_h, value_gap)`
- **`_TEXT_TILE_CACHE`:**
  `(text_str, font_path, f_size, fill, stroke_width, stroke_fill, anchor)`

---

## 9. Limity Cache (*Bounded LRU*)

- `_TEXT_TILE_CACHE`: max 256 wpisów.
- `_SLOPE_BASE_CACHE`: max 32 wpisy.
- `_RULER_BASE_CACHE`: max 64 wpisy.
Wszystkie bufory korzystają z `_BoundedStaticCache` (Least Recently Used) bez ryzyka wycieku pamięci.

---

## 10. Zachowanie przy braku danych (`value = None`)

- **Slope:** linijka pozostaje widoczna, wyświetlany jest tekst `"--%"`, brak zawieszonego kursora, brak błędów.
- **Altitude:** linijka pozostaje widoczna, wyświetlany jest tekst `"-- m"`, brak kursora, 100% poprawności.

---

## 11. Zachowanie `major_step`

- Zgodnie z wytycznymi, `major_step = 1.0` (lub inna podana wartość liczbowa) precyzyjnie definiuje interwał jednostek telemetrycznych (np. co 1 km lub co 5%), a nie liczbę podziałów.

---

## 12. Pixel Parity: Slope

Przetestowano metodą `ImageChops.difference`:
- `-12.0%`: `diff bbox = None` (0 px delta)
- `-5.0%`: `diff bbox = None` (0 px delta)
- `0.0%`: `diff bbox = None` (0 px delta)
- `+3.7%`: `diff bbox = None` (0 px delta)
- `+10.0%`: `diff bbox = None` (0 px delta)
- `None`: `diff bbox = None` (0 px delta)
**Wynik: 100% BYTE-EXACT.**

---

## 13. Pixel Parity: Altitude

- `0.0 m`: `diff bbox = None` (0 px delta)
- `250.0 m`: `diff bbox = None` (0 px delta)
- `500.0 m`: `diff bbox = None` (0 px delta)
- `750.0 m`: `diff bbox = None` (0 px delta)
- `1000.0 m`: `diff bbox = None` (0 px delta)
- `None`: `diff bbox = None` (0 px delta)
**Wynik: 100% BYTE-EXACT.**

---

## 14. Regresja: Distance (`dist_visual`)

Przetestowano dla wartości: `0.0, 1.0, 2.5, 5.0, 7.8, 10.0, None`:
- `diff bbox = None` dla wszystkich wartości.
- Czas wykonania: `0.130 ms` total.

---

## 15. Regresja: Battery & Solar

Przetestowano `fit_battery_pct_text` oraz `fit_solar_pct_text`:
- `0 != None` zachowane.
- Czas wykonania łączny Battery + Solar: `0.323 ms` total.

---

## 16. Kompatybilność Fontów

Przetestowano dynamiczną zmianę fontu dla `default`, `Comic Sans`, `Digital-7`, `Iona-u1`:
- Każdy font generuje poprawne kafelki i poprawnie unieważnia cache.
- Wszystkie testy porównawcze: `diff bbox = None`.

---

## 17. Lokalny Benchmark (120 klatek, 1280×720, v10)

| Widget | Before (Render / Paste / Total) | After (Render / Paste / Total) | Zysk (Render) | Zysk (Total) |
|---|---:|---:|---:|---:|
| **Slope** | 0.657 / 0.145 / **0.803 ms** | 0.161 / 0.113 / **0.274 ms** (med: 0.235) | **2.9x szybciej** | **2.9x szybciej** |
| **Altitude** | 0.443 / 0.608 / **1.051 ms** | 0.140 / 0.499 / **0.640 ms** (med: 0.522) | **3.2x szybciej** | **1.6x szybciej** |
| **SUMA (Slope + Alt)** | 1.100 / 0.753 / **1.853 ms** | 0.301 / 0.612 / **0.913 ms** (med: 0.757) | **3.6x szybciej** | **2.0x szybciej** |

> Cel etapu $\le 1.0\text{ ms/frame}$ został osiągnięty (**`0.913 ms` średnia / `0.757 ms` mediana**).
> Czysty koszt samego renderowania obu widgetów wynosi zaledwie **`0.301 ms/frame`**.

---

## 18. Wyniki AMD Production Benchmark (120 klatek @ 60 FPS, 1280×720)

- `AMD_MAP_PATH`: `GPU`
- `AMD_CHART_PATH`: `CPU_REFERENCE`
- `above_compose` (mediana): **`10.606 ms`**
- `above_total` (mediana): **`12.896 ms`**
- `RENDER FPS`: **`35.021 FPS`**
- `TRUE FPS`: **`11.703 FPS`**
- 120/120 klatek zakodowanych i zsynchronizowanych w 3.426 s (wideo).
- Zero błędów w frame accounting.

---

## 19. CPU_ABOVE przed i po

| Faza | ETAP 10L Baseline | ETAP 10N |
|---|---:|---:|
| **Slope (Total)** | ~1.74 ms | **0.27 ms** |
| **Altitude (Total)** | ~0.97 ms | **0.64 ms** |
| **SUMA Slope + Alt** | ~2.71 ms | **0.91 ms** |

---

## 20. Targetowane Testy

```bash
python -m pytest tests/test_etap10n_slope_altitude.py tests/test_etap10m2_chart_time_axis.py tests/test_etap10m_chart_dynamic.py tests/test_chart_axis_cache.py tests/test_chart_rendering.py tests/test_chart_seek_history.py
```
**Wynik: `25 passed in 7.82s` (100% PASS)**.

---

## 21. Zmodyfikowane Pliki Produkcyjne

- [src/indicators/bar.py](file:///c:/_DEV/TeleM/src/indicators/bar.py):
  - Dodano `_TEXT_TILE_CACHE`, `_SLOPE_BASE_CACHE`, `_RULER_BASE_CACHE`.
  - Wdrożono `_draw_text_bounded_cached`.
  - Zoptymalizowano `_render_slope` oraz `_render_ruler`.
- [tests/test_etap10n_slope_altitude.py](file:///c:/_DEV/TeleM/tests/test_etap10n_slope_altitude.py):
  - Pakiet testów jednostkowych i regresyjnych dla Slope i Altitude.

---

## 22. Pozostałe Wąskie Gardła (*Remaining Bottleneck*)

W `Altitude` głównym kosztem pozostał `rotated_paste` (`0.499 ms`) wynikający z rotacji całego rastra o 90 stopni (`rotation = 90`) w compositorze. Sam renderer działa w `0.140 ms`.

---

## 23. Rekomendowany Następny Cel

- **Kolejny cel:** Optymalizacja kompozycji i rotated_paste w warstwie `CPU_ABOVE_MAP` / `compositor.py` (lub `Virtual Power` / `Compass`).

---

## Status Końcowy

```text
SLOPE + ALTITUDE OPTIMIZATION: SUCCESS
```
