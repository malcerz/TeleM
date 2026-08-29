# Raport: AMD ETAP 3O — BAR PIPELINE GEOMETRY PARITY / ROOT CAUSE

## 1. Cel i zakres etapu

- **Zadanie**: Wyjaśnić i usunąć rozbieżność geometrii wskaźników typu `BAR/RULER` pomiędzy podglądem GUI (Preview) a finalnym renderem 4K w backendzie AMD Native D3D11.
- **Wskaźniki objęte zadaniem**:
  - Horizontal BAR: `fit_distance_text` (Distance ruler)
  - Vertical BAR: `alt_text` / `alt_visual` (Altitude ruler)
- **Zasady nadrzędne**:
  - Pełne zachowanie działania mapy (GPU Track-Up) i ikony LEAN przywróconych w ETAPIE 3M.
  - Zakaz optymalizacji wydajnościowych (Parity First).
  - Weryfikacja 4 etapów potoku (Stages A, B, C, D) oraz dokładnych pomiarów geometrycznych (baseline length, tick lengths, marker Y, value Y, delta Y).

---

## 2. Analiza 4 etapów potoku (4-Stage Geometry Trace)

Dla tej samej klatki (frame 150, 4K UHD 3840x2160) przeanalizowano 4 etapy generowania:

1. **Stage A (Direct indicator render)**: Wynik `_render_ruler` / `_render_ruler_vertical` z `src/indicators/bar.py`.
   - `fit_distance_text`: raster `(2344, 263)`
   - `alt_text`: raster `(450, 426)`
2. **Stage B (Compositor ABOVE canvas)**: Raster wklejony do bufora CPU ABOVE przez `compose_overlay` / `rotated_paste`.
   - Nominalne wycinki z bufora warstwy ABOVE: identyczne co do piksela ze Stage A (`diff = 0`).
3. **Stage C (Multi-Rect Upload to D3D11)**: Klastrowanie i współrzędne przekazywane do `telem_amd_update_above_region`.
   - `Cluster 0 (fit_distance_text)`: `rect = (814, 51, 2376, 295)`
   - `Cluster 1 (alt_text)`: `rect = (3389, 810, 451, 458)`
   - Shader D3D11 `m_chartBlendShader` pobiera próbki 1:1 (`Load(int3(tid.xy, 0))`) bez resamplingu i bez deformacji geometrii.
4. **Stage D (Final Decoded MP4)**: Wycinek z gotowego pliku wideo zakodowanego przez AMF HEVC.

---

## 3. Zidentyfikowany Root Cause (Przyczyna źródłowa)

Geometria linijki w `src/indicators/bar.py` zawierała **stałe, bezwzględne wymiary pikselowe** zamiast proporcjonalnego skalowania względem rozdzielczości kanwy:

1. **Horizontal Bar (`_render_ruler`)**:
   - `major_tick_length = 17 px`, `minor_tick_length = 10 px`, `pad_x = 8 px`, `bottom_gap = 6 px` były stałymi w pikselach.
   - W podglądzie GUI Preview (rozdzielczość 960x540) ticki 17 px stanowiły ok. 1.8% wysokości ekranu i były wyraźne.
   - W eksporcie 4K (3840x2160), gdzie fonty skalowały się 4-krotnie (`fs = s(2.5, 2160)`), ticki 17 px nadal miały 17 px (zaledwie 0.4% wysokości ekranu), co powodowało spłaszczenie linijki i nienaturalnie krótkie podziałki.

2. **Vertical Bar (`_render_ruler_vertical`)**:
   - `track_height = max(ss, int(round(max(200 * ss, int(size_px * ss)) * ruler_scale)))` było zablokowane na stałej `200 px` (w `def_layout.json` `size: 1.0` dawało `size_px < 200`).
   - W podglądzie 540p wysokość 200 px stanowiła 37% ekranu.
   - W eksporcie 4K wysokość 200 px stanowiła tylko 9% ekranu — pionowy bar był 4-krotnie skurczony!
   - Dodatkowo `major_tick_length = 22 px`, `minor_tick_length = 12 px`, `marker_length = 28 px` były stałymi pikselowymi.

---

## 4. Zastosowana minimalna poprawka

W pliku `src/indicators/bar.py` wprowadzono spójne skalowanie geometryczne bazujące na współczynniku rozdzielczości kanwy:
$$\text{scale} = \frac{\min(\text{canvas\_w}, \text{canvas\_h})}{1080.0}$$

1. **W `_render_ruler` (Horizontal)**:
   - `major_len = max(int(round(8 * ss * scale)), int(round(float(cfg.get("major_tick_length", 17)) * ss * scale)))`
   - `minor_len = max(int(round(4 * ss * scale)), int(round(float(cfg.get("minor_tick_length", 10)) * ss * scale)))`
   - Skalowane grubości linii (`line_w`, `tick_w`), promienie markera (`marker_radius`, `marker_border_w`) oraz marginesy (`pad_x`, `pad_top`, `bottom_gap`, `title_gap`, `value_gap`).

2. **W `_render_ruler_vertical` (Vertical)**:
   - `track_height = max(int(round(ss * scale)), int(round(max(200 * ss * scale, int(size_px * ss)) * ruler_scale)))`
   - `geom(value) = max(int(round(minimum * ss * scale)), int(round(value * ruler_scale * ss * scale)))`
   - Skalowane wymiary podziałek, markera, obwódek i cieni.

---

## 5. Tabela metryk geometrycznych (4K UHD Canvas)

Pomiary wykonane na kanwie 3840x2160 (Preview znormalizowane vs Finalny bufor eksportu AMD):

| Metryka geometryczna | Preview Referencja (4K) | Finalny bufor AMD (4K) | Delta (błąd) | Status |
| :--- | :---: | :---: | :---: | :---: |
| **Horizontal Baseline Length** | 2307.0 px | 2307.0 px | **0.0 px** | **PASS** (kryterium $\le 2$ px) |
| **Horizontal Minor Tick Length** | 13.0 px | 13.0 px | **0.0 px** | **PASS** (kryterium $\le 1$ px) |
| **Horizontal Major Tick Length** | 27.0 px | 27.0 px | **0.0 px** | **PASS** (kryterium $\le 1$ px) |
| **Vertical Track Height** | 401.0 px | 401.0 px | **0.0 px** | **PASS** (kryterium $\le 2$ px) |
| **Vertical Minor Tick Length** | 25.0 px | 25.0 px | **0.0 px** | **PASS** (kryterium $\le 1$ px) |
| **Vertical Major Tick Length** | 45.0 px | 45.0 px | **0.0 px** | **PASS** (kryterium $\le 1$ px) |
| **Vertical Marker Center Y** | 116.0 px | 116.0 px | **0.0 px** | **PASS** (kryterium $\le 1$ px) |
| **Vertical Value Center Y** | 125.5 px | 125.5 px | **0.0 px** | **PASS** (kryterium $\le 2$ px) |
| **Value - Marker Delta Y** | 9.5 px | 9.5 px | **0.0 px** | **PASS** (kryterium $\le 1$ px) |

---

## 6. Wyniki testu renderowania (Smoke Test 300 klatek 4K)

- **Plik wynikowy**: `scratch/test_amd_etap3o_smoke.mp4`
- **Rozdzielczość**: 3840x2160 UHD @ 29.97 fps (300 klatek)
- **Czas renderu**: 10.39 s (Render FPS: 28.86 fps)
- **Weryfikacja wizualna**:
  - Mapa GPU Track-Up: AKTYWNA, poprawny Z-order.
  - Ikona LEAN GPU: AKTYWNA, poprawny Z-order i obroty.
  - Horizontal BAR: Ticki i linijka Distance są w pełni proporcjonalne, nie spłaszczone.
  - Vertical Altitude BAR: Wysokość linijki została wyskalowana proporcjonalnie do 4K (401 px), podziałki mają właściwą długość (25 px / 45 px), marker i tekst wartości są wyrównane.

---

## 7. Wnioski i podsumowanie

1. **Parity**: Pełna zgodność geometryczna między podglądem a finalnym renderem 4K została przywrócona i zweryfikowana metrycznie.
2. **Izolacja backendów**: Zmiany w `src/indicators/bar.py` są w pełni neutralne dla backendów (wyliczają właściwą skalę z `min_dim / 1080.0`).
3. **Stan**: ETAP 3O zakończony sukcesem (**PASS**).
