# RAPORT: GAUGE NEEDLE WIDTH — PREVIEW / FINAL RENDER PARITY DLA GRUBOŚCI WSKAZÓWKI

**Data:** 2026-10-05  
**Autor:** Antigravity AI  
**Status:** ZAKOŃCZONE SUKCESEM (PASSED)  

---

## 1. Metryki Bramki Parzystości i Walidacji

```ini
ROOT_CAUSE=W src/indicators/gauge.py grubość wskazówki była wyliczana jako stała liczba pikseli: max(2, int(cfg.get("needle_width", 4) * (1.8 if pixel_profile else 1.5))) bez uwzględnienia canvas_w, canvas_h, min_dim ani rozdzielczości wyjściowej. Tarcza i geometria Gauge rosły 4x z Preview do 4K, podczas gdy wskazówka pozostawała stała, powodując 4-krotnie cieńszą igłę w 4K.
OLD_NEEDLE_WIDTH_FORMULA=needle_width_px = max(2, int(cfg.get("needle_width", 4) * (1.8 if pixel_profile else 1.5)))
NEW_NEEDLE_WIDTH_FORMULA=needle_width_px = max(2, int(round((logical_width * (1.8 if pixel_profile else 1.5)) * max(0.1, min_dim / 540.0))))

PREVIEW_CANVAS=960x540
PREVIEW_LOGICAL_WIDTH=4
PREVIEW_COMPUTED_WIDTH_PX=6
PREVIEW_GAUGE_DIAMETER=162
PREVIEW_WIDTH_RATIO=0.037037

FINAL_1080_COMPUTED_WIDTH_PX=12
FINAL_1080_GAUGE_DIAMETER=324
FINAL_1080_WIDTH_RATIO=0.037037

FINAL_4K_COMPUTED_WIDTH_PX=24
FINAL_4K_GAUGE_DIAMETER=648
FINAL_4K_WIDTH_RATIO=0.037037

PREVIEW_4K_RATIO_DIFF_PERCENT=0.00%

HUD_AUTO_PASS=YES
HUD_100_PASS=YES
HUD_75_PASS=YES
HUD_50_PASS=YES

OUTLINE_PASS=YES
SHADOW_PASS=YES
DIRTY_REGION_PASS=YES

DIRECT_PREVIEW_FINAL_PASS=YES
QUEUE_PREVIEW_FINAL_PASS=YES
QUEUE_SNAPSHOT_SEMANTICS_PRESERVED=YES

NVIDIA_HARDCODE_FOUND=YES (src/ffmpeg/nvidia_native_exporter.py:641 desc.style.gauge.needle_width = 8.0)
NVIDIA_HARDCODE_FIXED=YES (zastąpione przez resolve_gauge_needle_width_px(cfg.get('needle_width', 4), min_dim))

AMD_NATIVE_FPS=36.33
AMD_GPU_UTIL=99-100%

REAL_GUI_STARTUP_MS=1383.64
STARTUP_REGRESSION=NO

TESTS_PASSED=44
TESTS_FAILED=0
FILES_CHANGED=src/indicators/gauge.py, src/indicators/__init__.py, src/indicators/dispatcher.py, src/indicators/compositor.py, src/ffmpeg/nvidia_native_exporter.py, tests/test_gauge_needle_width_parity.py
SOURCE_HASH_PARITY=YES
COMMIT=HEAD

FINAL_STATUS=PASS
```

---

## 2. Szczegółowy Opis Problemu i Zidentyfikowana Przyczyna

Przed naprawą użytkownik zgłaszał:
- W oknie podglądu **Preview** grubość wskazówki ustawiona w kontrolce (np. `needle_width = 4` lub `10`) wyglądała na właściwie grubą i wyraźną.
- W finalnym renderze **4K (3840×2160)** wskazówka stawała się drastycznie cieńsza względem tarczy tego samego wskaźnika Gauge.

### Przyczyna źródłowa w `src/indicators/gauge.py`:
Wcześniejszy kod wyliczał szerokość wskazówki jako stałą wartość pikseli:
```python
needle_width_px = max(2, int(cfg.get("needle_width", 4) * (1.8 if pixel_profile else 1.5)))
```
Dla `needle_width = 4` dawało to:
- W Preview (`min_dim = 540`, średnica tarczy = `162 px`): szerokość igły = `6 px` $\to$ **3.70%** średnicy tarczy.
- W 4K (`min_dim = 2160`, średnica tarczy = `648 px`): szerokość igły nadal = `6 px` $\to$ **0.93%** średnicy tarczy (4-krotnie cieńsza!).

Cała pozostała geometria wskaźnika Gauge (promień, podziałki, grubość kresek, fonty) skalowała się z `min_dim` i rozmiarem `size_px`. Wskazówka pozostawała stała, co niszczyło proporcje.

---

## 3. Zastosowane Rozwiązanie Architektoniczne

1. **Wspólna funkcja skalowania `resolve_gauge_needle_width_px` (`src/indicators/gauge.py`):**
   ```python
   def resolve_gauge_needle_width_px(
       logical_width: float | int,
       min_dim: int,
       pixel_profile: bool = False,
       reference_min_dim: float = 540.0,
   ) -> int:
       try:
           w_val = float(logical_width)
       except (TypeError, ValueError):
           w_val = 4.0
       w_val = max(1.0, w_val)

       base_factor = 1.8 if pixel_profile else 1.5
       base_width = w_val * base_factor

       ref_dim = max(1.0, float(reference_min_dim))
       render_scale = max(0.1, float(min_dim) / ref_dim)

       return max(2, int(round(base_width * render_scale)))
   ```
   - Za punkt referencyjny (`reference_min_dim = 540.0`) przyjęto wymiar bazowy Preview (`960×540`).
   - W Preview dla `needle_width = 4` funkcja zwraca dokładnie `6 px` – **dotychczasowy wygląd podglądu jest w 100% zachowany jako wzorzec**.
   - W 1080p zwraca `12 px`, a w 4K zwraca `24 px`, zachowując idealny stosunek `needle_width_px / gauge_diameter_px = 0.037037` ($0.00\%$ różnicy).

2. **Diagnostyka parytetu bez narzutu per-frame (`[GAUGE NEEDLE PARITY]`):**
   Dodano log diagnostyczny wywoływany wyłącznie przy zmianie epoki / konfiguracji (nigdy co klatkę):
   ```text
   [GAUGE NEEDLE PARITY]
   indicator=speed_text
   logical_width=4
   preview_or_final=preview
   canvas=960x540
   min_dim=540
   hud_scale=1.00
   computed_width_px=6

   [GAUGE NEEDLE PARITY]
   indicator=speed_text
   logical_width=4
   preview_or_final=final
   canvas=3840x2160
   min_dim=2160
   hud_scale=1.00
   computed_width_px=24
   ```

3. **Usunięcie hardcoded wartości w `src/ffmpeg/nvidia_native_exporter.py`:**
   W linii 641 usunięto sztywne `desc.style.gauge.needle_width = 8.0` i zastąpiono dynamicznym wyliczeniem z `resolve_gauge_needle_width_px(cfg.get("needle_width", 4), min_dim, pixel_profile=pixel_profile)`.

4. **Zachowanie Outside Outline, Shadow i Dirty Region:**
   - Obrys zewnętrzny (`outline_enabled`) jest rysowany na zewnątrz, nie naruszając wewnętrznego czerwonego rdzenia wskazówki.
   - Płynny cień (`shadow_enabled`) oraz bufor supersamplingu (`mask_buf`) automatycznie dopasowują swój obszar (`bx0, by0, bx1, by1`) do powiększonej geometrii wskazówki.
   - `_needle_support` / `needle_bbox` uwzględnia pełen margines `_n_margin = 6.0 + s_reach + outline_width * 2.0`, eliminując jakiekolwiek ryzyko ucięcia, ghostingu czy artefaktów na backendzie AMF D3D11.

5. **Zachowanie semantyki snapshotów kolejki (`render_tab.py`):**
   Kolejka renderowania zachowuje `layout_snap = copy.deepcopy(ctrl.layout)` z momentu kliknięcia `+ Dodaj`. Użytkownik może dodawać kolejne zadania o różnych grubościach wskazówki (np. Job 1 = 10, Job 2 = 4) i każde zadanie zachowuje swój stan.

---

## 4. Wyniki Pomiarów i Pomiary Pikselowe (Visual Acceptance)

Dla wskaźnika Gauge o rozmiarze `size = 15.0%`:

| Konfiguracja | Preview (960×540) | Final 720p (1280×720) | Final 1080p (1920×1080) | Final 4K (3840×2160) | Diff % (Preview vs 4K) |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **`needle_width = 4`** | | | | | |
| *Średnica tarczy (px)* | 162 px | 216 px | 324 px | 648 px | — |
| *Grubość igły (px)* | 6 px | 8 px | 12 px | 24 px | — |
| *Stosunek grubości do tarczy* | **0.037037** | **0.037037** | **0.037037** | **0.037037** | **0.00%** |
| **`needle_width = 10`** | | | | | |
| *Średnica tarczy (px)* | 162 px | 216 px | 324 px | 648 px | — |
| *Grubość igły (px)* | 15 px | 20 px | 30 px | 60 px | — |
| *Stosunek grubości do tarczy* | **0.092593** | **0.092593** | **0.092593** | **0.092593** | **0.00%** |

Pomiary z maski pikselowej (`arr[:, :, 0] > 150 & arr[:, :, 1] < 80`) na wyrenderowanych obrazach PNG wykazały dokładną grubość poprzeczki wskazówki:
- `needle_width=4`: Preview = 6 px, 720p = 8 px, 1080p = 12 px, 4K = 24 px.
- `needle_width=10`: Preview = 15 px, 720p = 20 px, 1080p = 30 px, 4K = 60 px.
- Różnica proporcji wynosi **0.00%** (wymóg: $\le 5\%$).

---

## 5. Testy Jednostkowe

Zestaw testów w `tests/test_gauge_needle_width_parity.py`:
1. `test_gauge_needle_width_scales_with_canvas` – **PASS**
2. `test_gauge_needle_width_preview_4k_ratio_parity` – **PASS**
3. `test_gauge_needle_width_1080_4k_ratio_parity` – **PASS**
4. `test_gauge_needle_width_change_invalidates_cache` – **PASS**
5. `test_gauge_needle_bbox_contains_scaled_needle` – **PASS**
6. `test_gauge_scaled_needle_outline_not_clipped` – **PASS**
7. `test_gauge_scaled_needle_shadow_not_clipped` – **PASS**
8. `test_queue_gauge_width_snapshot_preserved` – **PASS**
9. `test_two_queue_jobs_keep_distinct_needle_widths` – **PASS**
10. `test_nvidia_gauge_width_not_hardcoded` – **PASS**

Pełny zestaw 44 testów automatycznych zakończył się wynikiem **44 passed in 1.97s**.

---

## 6. Weryfikacja Braku Regresji Startupu GUI

Uruchomiono pełny test GUI na pliku wideo `D:\GoPro\DJI_20261002062647_0003_D.MP4` oraz pliku FIT `D:\GoPro\24574176578.fit`:
- **Czas od kliknięcia do 1. klatki:** `CLICK_TO_FIRST_FRAME_MS = 1383.64 ms (1.38 s)`
- **Szybki start:** Utrzymany poniżej 1.5 s (brak regresji 119 s).
- **AMF / GPU Throughput:** Utrzymany na poziomie ~36 FPS.
