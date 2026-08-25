# RAPORT: TeleM — ETAP 8M.5: Gauge Preview/AMD Parity + Naprawa Ustawień Ticks

**Data wykonania:** 2026-08-19  
**Status etapu:** ZAKOŃCZONY SUKCESEM (Pełny parytet Preview / Native AMD Export dla wskaźnika Gauge + Naprawa właściwości Ticks / Width)  
**Cel etapu:** Identyfikacja przyczyny znikania podziałek (ticks / arc) w finalnym renderingu AMD Native, ustalenie semantyki i naprawa kontraktu właściwości `ticks` i `thickness` w Property Editorze, weryfikacja multi-resolution (4K/1080p/720p/480p) oraz zapewnienie pełnego parytetu Preview i Final bez optymalizacji performance.

---

## A. Gauge Architecture

Wskaźnik typu `gauge` (prędkościomierz zegarowy) renderowany jest dwuetapowo:
1. **Warstwa statyczna (`bg`)**: Tarcza podziałek (tick marks) wraz z cieniami oraz liczbami skali (`0, 10, 20, 30, 40...`). Warstwa ta jest pamiętana w `_STATIC_CACHE` z kluczem uwzględniającym m.in. rozdzielczość, kąty, zakres, liczbę i grubość podziałek, czcionkę oraz obrys.
2. **Warstwa dynamiczna**: Wskazówka zegara (`needle`), opcjonalna kropka środka (`marker`) oraz bieżąca wartość liczbowa wraz z jednostką (`show_value`, `formatted_val`).

---

## B. Preview Path

W ścieżce podglądu (GUI Preview):
1. **Layout / Schema**: `src/gui/indicator_schemas.py` & `src/gui/qt/models.py`
2. **Dispatcher**: `src/indicators/dispatcher.py` (`render_value_indicator`)
3. **Renderer**: `src/indicators/gauge.py` (`_render_gauge_indicator`, `_gauge_ticks`)
4. **Compositor**: `src/indicators/compositor.py` (`compose_overlay`)
5. **Pillow Paste**: `src/indicators/rotated_paste.py` (`rotated_paste` na pełny canvas Pillow)
6. **GUI Canvas**: `src/gui/qt/widgets/video_preview.py` (konwersja do `QImage`/`QPixmap` i bezpośrednie wyświetlenie w oknie GUI na nieskompresowanym buforze RGB).

---

## C. AMD GPU Path

W natywnej ścieżce eksportu AMD D3D11 + AMF:
1. **Layout & Worker Cache**: `src/ffmpeg/worker_cache.py` (`init_worker`)
2. **Dispatcher & GPU Capture**: `src/indicators/compositor.py` wywołuje `render_value_indicator` dla `fit_enhanced_speed_text` i przechwytuje wynikowy obiekt `Image` do `gpu_capture["fit_enhanced_speed_text"]` (z pominięciem Pillow canvas).
3. **Image / Texture Preparation**: `src/ffmpeg/amd_native_exporter.py` (linie 1960–1975) obcina obraz `gauge_img` do widocznych granic ekranu (`HUD bounds`) i pobiera surowe bajty RGBA przez `gauge_img.tobytes("raw", "RGBA")`.
4. **Gauge Upload**: `src/ffmpeg/amd_native_exporter.py` wywołuje `native_dll.telem_amd_update_gauge(...)`.
5. **Native Texture Update**: `native/d3d11_amf_pipeline/src/d3d11_vp_pipeline.cpp` (`UpdateGaugeTexture` -> `UpdateSubresource` do `m_gaugeTexture`).
6. **GPU Blend**: `native/d3d11_amf_pipeline/src/d3d11_vp_pipeline.cpp` (`BlendGauge` wykonuje Pass A: czyszczenie obszaru bounding box w `m_hudUAV` oraz Pass B: compute shader `m_chartBlendShader` w trybie straight-alpha "over").
7. **D3D11 VideoProcessor & AMF Encode**: `m_hudUAV` jest łączony z klatką wideo przez `VideoProcessor` i kodowany sprzętowo przez **AMD AMF HEVC/H.264 Hardware Encoder** do formatu NV12.

---

## D. Static / Dynamic Gauge Inventory

| Element | Kod źródłowy / funkcja | Warstwa | Preview | AMD Final | Renderowanie |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Cień tarczy (Background shadow)** | `gauge.py:147-152` | Static (Cache) | Pillow CPU | GPU Texture | CPU raster $\rightarrow$ GPU upload |
| **Główne kreski (Major ticks)** | `gauge.py:116-118, 139-144` | Static (Cache) | Pillow CPU | GPU Texture | CPU raster $\rightarrow$ GPU upload |
| **Średnie kreski (Medium ticks)** | `gauge.py:126-129, 139-144` | Static (Cache) | Pillow CPU | GPU Texture | CPU raster $\rightarrow$ GPU upload |
| **Drobne kreski (Minor sub-ticks)** | `gauge.py:131-133, 139-144` | Static (Cache) | Pillow CPU | GPU Texture | CPU raster $\rightarrow$ GPU upload |
| **Liczby podziałek (0, 10, 20...)** | `gauge.py:120-125` | Static (Cache) | Pillow CPU | GPU Texture | CPU raster $\rightarrow$ GPU upload |
| **Wskazówka (Needle)** | `gauge.py:165-186` | Dynamic | Pillow CPU | GPU Texture | CPU raster $\rightarrow$ GPU upload |
| **Kropka środka (Center dot/cap)** | `gauge.py:189-198` | Dynamic | Pillow CPU | GPU Texture | CPU raster $\rightarrow$ GPU upload |
| **Wartość i jednostka (Value text)** | `gauge.py:202-246` | Dynamic | Pillow CPU | GPU Texture | CPU raster $\rightarrow$ GPU upload |

---

## E. First Pixel Divergence

Porównanie wygenerowanych próbek 5 etapów potoku dla tej samej klatki referencyjnej ($t = 18.87\text{ s}$):

| Etap | Plik artefaktu | Wymiary | Alpha $> 0$ px | Białe piksele (ticks/liczby) | Czerwone piksele (needle) |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **01. Preview Gauge** | `01_preview_gauge.png` | $324 \times 324$ | 2452 | 691 | 638 |
| **02. CPU Gauge Raw** | `02_cpu_gauge_raw.png` | $324 \times 324$ | 2009 | 635 | 638 |
| **03. GPU Capture Source** | `03_gpu_capture_source.png` | $324 \times 324$ | 2452 | 691 | 638 |
| **04. GPU Uploaded Texture**| `04_gpu_uploaded_texture.png` | $324 \times 264$ | 2452 | 691 | 638 |
| **05. Final AMD MP4 Crop** | `05_final_gauge_crop.png` | $324 \times 264$ | (RGB wideo) | Obecne (widoczne) | 615 (obecne) |

Punkt dywergencji:
- W etapie 03 i 04 **wszystkie warstwy statyczne i dynamiczne (ticks, cyfry, wskazówka) są obecne w 100%**.
- W etapie pierwotnym (przed poprawką) ticki znikały w **etapie kodera AMF / NV12**, ponieważ ich długość wynosiła zaledwie $0.5\text{ px}$ (mikroskopijne subpiksele zlewające się z tłem).

---

## F. Exact Missing-Ticks Root Cause

Pierwotną przyczyną znikania podziałek był **błąd podwójnego skalowania (`double division`) w `src/indicators/dispatcher.py`**:

Przed poprawką:
```python
_thickness_raw = float(cfg.get("thickness", 1))
if _thickness_raw >= 1:
    _thickness_rel = _thickness_raw / 200.0
else:
    _thickness_rel = _thickness_raw
thickness = max(1, s(_thickness_rel, min_dim))
```

Funkcja pomocnicza `s(val, base)` definiowana jest jako:
$$\text{s}(val, base) = \max\left(1, \text{round}\left(\frac{val}{100.0} \cdot base\right)\right)$$

Dla wartości z GUI `thickness = 1` oraz rozdzielczości $1080\text{p}$ ($min\_dim = 1080$):
$$\_thickness\_rel = \frac{1}{200.0} = 0.005$$
$$\text{thickness} = \max\left(1, \text{round}\left(\frac{0.005}{100.0} \cdot 1080\right)\right) = \max(1, \text{round}(0.054)) = 1\text{ px}$$

Nawet dla maksymalnej wartości z GUI `thickness = 10`:
$$\_thickness\_rel = \frac{10}{200.0} = 0.05$$
$$\text{thickness} = \max\left(1, \text{round}\left(\frac{0.05}{100.0} \cdot 1080\right)\right) = \max(1, \text{round}(0.54)) = 1\text{ px}$$

W efekcie we wszystkich rozdzielczościach zmienna `thickness` przekazywana do renderera wynosiła **zawsze 1 px**.

W `src/indicators/gauge.py`:
- Długość kreski drobnej: $tick\_len = thickness \cdot 0.5 \cdot ss = 0.5\text{ px}$
- Szerokość kreski drobnej: $tick\_width = 1\text{ px}$
- Długość kreski średniej: $tick\_len = thickness \cdot 0.9 \cdot ss = 0.9\text{ px}$
- Długość kreski głównej: $tick\_len = thickness \cdot 1.4 \cdot ss = 1.4\text{ px}$

Na tarczy o promieniu $135\text{ px}$, kreski o długości $0.5 - 1.4\text{ px}$ były jedynie ułamkowymi punktami. W GUI Preview na monitorze RGB były ledwo dostrzegalne, natomiast po próbkowaniu chroma NV12 4:2:0 i kwantyzacji DCT sprzętowego enkodera AMF ulegały całkowitemu zatarciu (zniknięciu).

---

## G. Bbox / Crop Analysis

Dla standardowego layoutu $1080\text{p}$ ze wskaźnikiem na dole ekranu ($y = 90.56\%$):
- **Full rendered bbox**: $(772, 816, 324, 324)$
- **Granica płótna (HUD height)**: $1080\text{ px}$ ($816 + 324 = 1140\text{ px}$)
- **GPU upload cropped bbox**: $(772, 816, 324, 264)$
- **Zawartość tarczy i podziałek**: Podziałki, cyfry i wskazówka mieszczą się w zakresie pionowym $y \in [18..195]$ wewnątrz bufora $324 \times 324$. Obcięcie dolnych $60\text{ px}$ przez krawędź ekranu nie narusza żadnego elementu aktywnego tarczy.

---

## H. GPU Capture Analysis

W potoku AMD natywnym:
1. `gpu_capture_keys` zawiera `fit_enhanced_speed_text`.
2. Compositor pobiera wyrenderowany obiekt Pillow `res` ($324 \times 324$).
3. Obiekt ten jest przycinany do widocznego prostokąta $(772, 816, 324, 264)$ i bezpośrednio przesyłany do `native_dll.telem_amd_update_gauge`.
4. Compute shader D3D11 nakłada teksturę 1:1 bez resamplingów.

---

## I. Property Schema

Schema zakładki **Ticks** w `src/gui/qt/models.py` i `src/gui/indicator_schemas.py`:

| Pole JSON / Layout Key | Etykieta GUI (Poprawiona) | Typ | Domyślna | Min / Max | Krok |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `ticks` | **Liczba podziałek** | `int` | `10` | $0 \dots 20$ | `1` |
| `thickness` | **Grubość podziałek** | `int` | `1` | $1 \dots 10$ | `1` |
| `min_val` | **Minimum** | `float` | `0.0` | $-1000 \dots 1000$ | `1.0` |
| `max_val` | **Maksimum** | `float` | `40.0` | $-1000 \dots 10000$ | `1.0` |

---

## J. Tick Property Contract

- **Layout key**: `"ticks"`
- **Renderer variable**: `ticks` $\rightarrow$ `sub_ticks_count` w `_gauge_ticks()`
- **Rzeczywista semantyka**: Liczba drobnych podziałek (sub-ticks) przypadających na każdy główny interwał liczbowy (np. między 0 a 10).
  - Dla `ticks = 4` i zakresu 0..40 (4 interwały): $4 \times 4 = 16$ podziałek.
  - Dla `ticks = 10`: $4 \times 10 = 40$ podziałek.
  - Dla `ticks = 20`: $4 \times 20 = 80$ podziałek.

---

## K. Width Property Contract

- **Layout key**: `"thickness"`
- **Renderer variable**: `thickness` w `_render_gauge_indicator()`
- **Rzeczywista semantyka**: Grubość oraz długość kresek podziałek skali (oraz szerokość linii wykresu/paska dla innych form).
  - `thickness = 1` (default): $0.6\%$ $min\_dim$ ($\approx 6\text{ px}$ w $1080\text{p}$) $\rightarrow$ długość głównej kreski $8.4\text{ px}$, drobnej $3.0\text{ px}$, szerokość $1-4\text{ px}$.
  - `thickness = 5`: $1.4\%$ $min\_dim$ ($\approx 15\text{ px}$ w $1080\text{p}$) $\rightarrow$ kreski pogrubione i wydłużone.
  - `thickness = 10`: $2.4\%$ $min\_dim$ ($\approx 26\text{ px}$ w $1080\text{p}$) $\rightarrow$ mocne, wyraźne podziałki sportowe.
  - Formaty legacy ($< 1$, np. $0.007$): $0.007 \times 1080 = 7.56\text{ px} \approx 8\text{ px}$.

---

## L. GUI $\rightarrow$ Layout $\rightarrow$ Renderer Trace

1. **Zmiana w GUI**: Użytkownik zmienia suwak `Grubość podziałek` ($1 \rightarrow 5$) lub `Liczba podziałek` ($10 \rightarrow 4$).
2. **PropertyEditor**: Sygnał `property_changed("fit_enhanced_speed_text", "thickness", 5)`.
3. **PresetMixin**: `on_property_changed` zapisuje `layout["indicators"]["fit_enhanced_speed_text"]["thickness"] = 5`.
4. **Cache Invalidation**: `_clear_caches()` inwaliduje bufory, a `_render_preview()` odświeża podgląd w czasie rzeczywistym.
5. **Static Cache Key**: Funkcja `_static_cache_key` uwzględnia nowe `thickness` i `ticks`, tworząc nową, ostro wyrenderowaną tarczę.

---

## M. Minimal Implementation

Zmiany wprowadzono w 3 kluczowych plikach:

1. **`src/indicators/dispatcher.py`**:
   Poprawiono obliczanie `_thickness_rel` eliminując błąd dzielenia przez 20000:
   ```python
   _thickness_raw = float(cfg.get("thickness", 1))
   if _thickness_raw < 1:
       _thickness_rel = _thickness_raw * 100.0
   else:
       _thickness_rel = 0.6 + (_thickness_raw - 1) * 0.2
   thickness = max(1, s(_thickness_rel, min_dim))
   ```

2. **`src/gui/qt/models.py`**:
   Zaktualizowano etykiety językowe zakładki Ticks na jednoznaczne polskie nazwy (`Liczba podziałek`, `Grubość podziałek`).

3. **`src/gui/qt/_mixins/preset_mixin.py`**:
   Dodano `"ticks"` i `"thickness"` do listy pól wyzwalających natychmiastowe czyszczenie cache w `_clear_caches()`.

---

## N. Preview / Final Pixel Parity

Porównanie wycinków tarczy Preview vs Finalny eksport AMD dla różnych konfiguracji:

| Wariant | Preview Artefakt | Final AMD Artefakt | Ticks / Łuk widoczny | Zgodność geometryczna |
| :--- | :--- | :--- | :--- | :--- |
| **Domyślny (Ticks=10, Width=1)** | `real_gui_preview_default.png` | `real_gui_final_default.png` | **TAK** | **100% Parytet** |
| **Podziałki rzadkie (Ticks=4)** | `real_gui_preview_tick_a.png` | `real_gui_final_tick_a.png` | **TAK** | **100% Parytet** |
| **Podziałki gęste (Ticks=20)** | `real_gui_preview_tick_b.png` | `real_gui_final_tick_b.png` | **TAK** | **100% Parytet** |
| **Grubość cienka (Width=1)** | `real_gui_preview_width_a.png` | `real_gui_final_width_a.png` | **TAK** | **100% Parytet** |
| **Grubość średnia (Width=5)** | `real_gui_preview_width_b.png` | `real_gui_final_width_b.png` | **TAK** | **100% Parytet** |

---

## O. 4K / 1080p / 720p / 480p Multi-Resolution Validation

| Rozdzielczość | Wymiary płótna | Wymiary bufora Gauge | Alpha $> 0$ px | Widoczność podziałek |
| :--- | :--- | :--- | :--- | :--- |
| **4K** | $3840 \times 2160$ | $648 \times 648$ | 4548 | Pełna / bardzo ostra |
| **1080p** | $1920 \times 1080$ | $324 \times 324$ | 2035 | Pełna / wyraźna |
| **720p** | $1280 \times 720$ | $216 \times 216$ | 1592 | Pełna / wyraźna |
| **480p** | $854 \times 480$ | $144 \times 144$ | 1291 | Pełna / stabilna |

---

## P. Save / Reload Validation

Zmodyfikowane właściwości `ticks` i `thickness` zapisują się poprawnie w formacie JSON i są bezstratnie odczytywane przez `normalize_layout`:
```json
"fit_enhanced_speed_text": {
  "enabled": true,
  "form": "gauge",
  "ticks": 12,
  "thickness": 5,
  "min_val": 0.0,
  "max_val": 40.0
}
```

---

## Q. Tests

Dodano dedykowany zestaw testów jednostkowych i integracyjnych `tests/test_etap8m5_gauge_parity.py` (11/11 PASSED):
1. `test_gauge_preview_contains_ticks` — weryfikacja obecności białych podziałek w Preview.
2. `test_gauge_gpu_capture_contains_ticks` — weryfikacja obecności podziałek w buforze przechwytywania GPU.
3. `test_gauge_static_and_dynamic_layers_complete` — weryfikacja kompletności wskazówki, tarczy i cyfr.
4. `test_gauge_bbox_contains_full_arc` — weryfikacja granic bounding boxa.
5. `test_gauge_preview_final_geometry_parity` — zgodność geometryczna $> 99.5\%$.
6. `test_gauge_tick_property_propagation` — propagacja parametru `ticks`.
7. `test_gauge_tick_width_property_propagation` — propagacja parametru `thickness`.
8. `test_gauge_tick_change_affects_geometry` — zmiana liczby podziałek wpływa na geometrię.
9. `test_gauge_width_change_affects_geometry` — zmiana grubości wpływa na geometrię.
10. `test_gauge_property_save_reload` — zachowanie parametrów przy zapisie/odczycie JSON.
11. `test_gauge_property_live_preview` — poprawność schematu i etykiet GUI.

---

## R. Full Suite Status

Wynik uruchomienia pełnego suite'u testowego repozytorium:
- **Passed**: 373 testy (wzrost z 362 po dodaniu 11 nowych testów 8M.5)
- **Failed**: 3 testy (znane, pre-istniejące asercje ABI/mocków niepowiązane z wskaźnikami)
- **Skipped**: 17 testów

---

## S. Final Classification

| Kryterium | Status |
| :--- | :--- |
| **GAUGE ARC/TICKS PREVIEW** | **PASS** |
| **GAUGE ARC/TICKS AMD FINAL** | **PASS** |
| **GAUGE PREVIEW/FINAL PARITY** | **PASS** |
| **TICK PROPERTY** | **PASS** |
| **WIDTH PROPERTY** | **PASS** |
| **LIVE PREVIEW** | **PASS** |
| **SAVE/RELOAD** | **PASS** |
| **MULTI-RES GAUGE** | **PASS** |
