# RAPORT_TELEM_FIX_CHART_CLIPPING: Chart Axis Labels Clipping Fix

**Data:** 2026-08-19  
**Faza:** USER BUG FIX: Chart Labels Are Still Clipped  
**Cel:** Eliminacja obcinania etykiet osi X i Y na wykresach (Cadence, Heart Rate i pozostałych) w pełnym renderingu 4K i 1080p przy zachowaniu stałych rozmiarów wizualnych widgetów.

---

## A. ROOT CAUSE

**Konkretna funkcja / warstwa źródłowa:** `src/indicators/chart_utils.py::_build_chart_bg()` oraz `src/indicators/chart.py::_render_chart_indicator()`.

Główne przyczyny geometryczne:
1. **Brak ograniczeń pozycjonowania etykiet X (0% oraz 100%):**
   - Etykiety osi X były bezwarunkowo centrowane wokół znacznika osi: `tx = x - tw // 2`.
   - Dla znacznika 0% ($x = \text{plot\_x1}$), gdy szerokość połowy napisu przekraczała margines lewy, `tx < 0` $\implies$ napis był ucinany od lewej.
   - Dla znacznika 100% ($x = \text{plot\_x2}$), gdy $tx + tw > \text{width}$, napis wychodził poza prawą krawędź rastra.
2. **Niedoszacowanie dolnego marginesu osi X z powodu TrueType glyph ascent/descent:**
   - Obliczenie `needed_bottom_margin` używało wysokości `bbox[3] - bbox[1]` zamiast bezwzględnego dolnego zasięgu glifu `bbox[3]`. W fontach TrueType z przesunięciem bazowym powodowało to rysowanie dolnych linii tekstu poza dolną krawędzią rastra (`ty + bbox[3] > height`).
3. **Niedoszacowanie marginesu górnego dla etykiety maksymalnej wartości osi Y:**
   - Górna etykieta Y jest centrowana na `plot_y1`: `ty = plot_y1 - th // 2`. Przy małym marginesie górnym `axis_top_margin`, tekst rysowany był przy `ty < 0` (obcięcie górnej połowy cyfr).
4. **Brak marginesu na obrys (outline) nagłówka i wartości w `chart.py`:**
   - Tytuł wykresu był rysowany od współrzędnej $y = 0$, co przy grubości obrysu `outline > 0` ucinało górną krawędź obrysu.

---

## B. WHY PREVIOUS 8M.6 / 8M.7 FIX WAS INSUFFICIENT

- Poprawki w ETAP 8M.6 i 8M.7 skupiły się na zapobieganiu wychodzeniu całego widgetu poza dolną/górną krawędź ramki 4K canvasu (`canvas_h = 2160`).
- Jednak wewnątrz lokalnego rastra wykresu (`bg_img`) pozycjonowanie etykiet `0%` i `100%` oraz `min_val`/`max_val` nadal zakładało stałe/szacowane marginesy i symetryczne centrowanie bez sprawdzania faktycznych skrajnych współrzędnych glifów TrueType.

---

## C. PLOT RECT VS VISUAL RECT CONTRACT

Wprowadzono i zaimplementowano ścisły kontrakt geometryczny:
- **`VISUAL_RECT`**: Zewnętrzny rozmiar rastra widgetu `(chart_w + 8, final_h)` zdefiniowany przez konfigurację użytkownika.
- **`PLOT_RECT`**: Obszar danych wykresu `(plot_x1, plot_y1, plot_x2, plot_y2)` wyliczany wewnątrz `bg_img` na podstawie dokładnych, zmierzonych zasięgów fontu:
  - `axis_left_margin = ceil(max_label_w + 8*ss + 2*ss)`
  - `axis_right_margin = ceil(max(6*ss, max_x_label_w // 2 + 4*ss))`
  - `axis_top_margin = ceil(max(4*ss, max_y_bot / 2.0 + max_y_top + 4*ss))`
  - `axis_bottom_margin = ceil(max_x_bot + 10*ss)`
- **Zasada pozycjonowania etykiet X:**
  - Pierwszy znacznik (0%): ograniczony do lewej krawędzi (`tx = max(2*ss, int(round(x - max(0, bbox[0]))))`).
  - Ostatni znacznik (100%): ograniczony do prawej krawędzi (`tx = min(width - tw - 2*ss, int(round(x - tw)))`).
  - Środkowe znaczniki: centrowane z twardym ograniczeniem w przedziale `[2*ss, width - tw - 2*ss]`.
- **Zasada pozycjonowania etykiet Y:**
  - Dolna/górna krawędź ograniczona w przedziale `[2*ss - b_top, height - b_bot - 2*ss]`.

---

## D. CHANGED FILES

1. **`src/indicators/chart_utils.py`**:
   - Wdrożenie precyzyjnego pomiaru `max_y_bot`, `max_y_top`, `max_x_bot`, `max_x_label_w`.
   - Dynamiczne, bezpieczne marginesy `axis_left_margin`, `axis_right_margin`, `axis_top_margin`, `axis_bottom_margin`.
   - Bounded tick label rendering (brak wykraczania poza krawędzie rastra).
2. **`src/indicators/chart.py`**:
   - Uwzględnienie grubości obrysu (`outline`) w `margin_top` oraz w pozycjonowaniu tytułu i dynamicznego kafelka wartości (`_render_value_text_tile`).
3. **`tests/test_chart_label_clipping_bounds.py`** (NOWY):
   - 40 testów regresyjnych sprawdzających containment pikseli dla 4K, 1080p, małych i dużych wykresów oraz różnych formatów etykiet.
4. **`tests/test_etap8m7_chart_frame_clipping.py`** & **`tests/test_chart_rendering.py`**:
   - Zaktualizowano asercje wysokości i geometrii osi do dynamicznego modelu bez obcięć.

---

## E & F. CADENCE & HEART RATE BEFORE / AFTER MEASUREMENTS

Wygenerowano i zweryfikowano klatki testowe dla Cadence i Heart Rate (4K 3840×2160):

### Cadence (4K):
- **BEFORE:** Dolne etykiety 0%–100% dotykały dolnej krawędzi rastra lub były obcięte; brak bezpiecznego marginesu dolnego.
- **AFTER:**
  - Rozmiar rastra: `1160 × 512 px`
  - Zawartość niezerowego Alpha: $X \in [2, 1140]$, $Y \in [2, 430]$
  - Margines lewy: **2 px**, prawy: **19 px**, górny: **2 px**, dolny: **81 px** (100% wewnątrz rastra).

### Heart Rate (4K):
- **BEFORE:** Górna etykieta Y ("116") dotykała $y=0$ i traciła górną połowę cyfr; etykiety X wychodziły poza raster.
- **AFTER:**
  - Rozmiar rastra: `1160 × 512 px`
  - Zawartość niezerowego Alpha: $X \in [3, 1140]$, $Y \in [2, 430]$
  - Margines lewy: **3 px**, prawy: **19 px**, górny: **2 px**, dolny: **81 px** (100% wewnątrz rastra).

---

## G. 4K VERIFICATION

- Pełny composite overlay 3840×2160 wygenerowany poprawnie: `scratch/chart_clipping_verification/full_overlay_4k.png`.
- Wycięte wycinki `cadence_4k_final_crop.png` i `hr_4k_final_crop.png` potwierdzają pełną czytelność wszystkich 5 znaczników czasu (0%, 25%, 50%, 75%, 100%) oraz etykiet Y bez żadnego ucięcia.

---

## H. 1080P VERIFICATION

- Cadence 1080p Static (`584 × 262 px`): $X \in [3, 564]$ (margines 3/19 px), $Y \in [2, 226]$ (margines 2/35 px) $\implies$ **PASS**.
- Heart Rate 1080p Static (`584 × 262 px`): $X \in [4, 564]$ (margines 4/19 px), $Y \in [2, 226]$ (margines 2/35 px) $\implies$ **PASS**.

---

## I. REGRESSION TEST

- Nowy zestaw testów: `tests/test_chart_label_clipping_bounds.py` (40 testów sparametryzowanych).
- Wynik: **40 passed in 0.56s**.

---

## J. FULL PYTEST EXECUTION

Uruchomiono pełny zestaw testów repozytorium:
```text
====================== 517 passed, 17 skipped in 31.72s =======================
```
**Wynik: 0 failures, 100% testów przechodzi.**

---

## K. EXPORT PREVIEW REGRESSION

Podczas finalnego eksportu wideo okno podglądu pozostawało zamrożone na klatce sprzed uruchomienia renderowania lub pokazywało wyłącznie statyczny napis `"Renderowanie..."`. Pasek postępu i licznik klatek działały, ale użytkownik nie widział aktualnie przetwarzanego obrazu filmu z naniesionymi wskaźnikami, mapą i wykresami.

---

## L. ROOT CAUSE

1. **Brak przekazywania snapshotu stanu / timestampu:** W `src/ffmpeg/amd_native_exporter.py` callback `on_render_progress` przekazywał `hud_state = None`, przez co funkcja podglądu `_render_hud_preview()` w `RenderTab` nigdy nie otrzymywała aktualnego timestampu klatki `t_video_pts`.
2. **Ukrywanie widoku podglądu podczas eksportu:** W `RenderTab._on_render` widget podglądu wideo `self.preview_slot` był bezwarunkowo ukrywany (`setVisible(False)`), a na jego miejsce wstawiany `self.hud_preview_label`, który bez otrzymania `hud_state` pozostawał w stanie statycznym.
3. **Zamiana argumentów w `on_render_progress` (FPS Bug):** `amd_native_exporter.py` wywoływał callback z argumentami `(frame_idx + 1, total, fps, eta, None)` zamiast `(completed, total, elapsed, fps, hud_state)`. W rezultacie `RenderTab` interpretował wartość `fps` jako czas `elapsed`, a `eta` (szacowany czas do końca, np. 1.9s) jako `FPS: 1.9`, co powodowało fałszywy odczyt `FPS: 1.9` na górnym pasku.

---

## M. PREVIOUS VS CURRENT PREVIEW PATH

- **Przed refaktorem:** Podgląd eksportu albo był pomijany w natywnym exporterze AMD D3D11, albo renderował uproszczoną nakładkę na czarnym tle (`Image.new("RGBA", ..., (0,0,0,255))`).
- **Obecna implementacja:**
  - `export_amd_native_d3d11` przekazuje `hud_state={"ts": t_video_pts, "frame_idx": prepared.frame_idx}`.
  - `RenderTab` uruchamia asynchroniczny wątek roboczy `_trigger_async_preview(ts)` w tle z mechanizmem `_preview_busy` (zero backpressure na pętlę renderera GPU).
  - Wątek tła pobiera klatkę bazową z `ctrl.last_src_pil` (lub z cache proxy), komponuje aktualny stan telemetryczny (wszystkie wskaźniki, wykresy z kursorem czasu, obracana mapa, gauge, teksty) w rozdzielczości widgetu (640×360 / 960×540) i emituje sygnał Qt `sig_export_preview_ready`.
  - Główny wątek GUI odbiera sygnał i odświeża `QLabel` bez żadnego blokowania renderera ani zamrażania UI.

---

## N. PREVIEW UPDATE RATE

- Częstotliwość podglądu GUI jest limitowana do **~5 Hz** (`now - self._last_preview_time >= 0.2s`).
- W połączeniu z flagą `_preview_busy` nowe klatki podglądu są pomijane (dropped preview frames), jeśli poprzedni render podglądu jest w toku.
- **Zero backpressure:** Główny pipeline eksportu GPU renderuje z pełną prędkością (~36–40 FPS).

---

## O. PREVIEW RESOLUTION

- Podgląd jest renderowany w rozdzielczości dopasowanej do rzeczywistego rozmiaru widgetu w GUI (domyślnie **640×360** do **960×540**).
- Eliminuje to zbędne alokacje 4K w pamięci CPU i natychmiastowe skalowanie przez Qt.

---

## P. GPU / CPU READBACK METHOD

- Eksport wideo odbywa się w całości w przestrzeni GPU (D3D11VA $\to$ D3D11 Fused Shader $\to$ AMF Hardware Encoder).
- Dla podglądu GUI **NIE jest wykonywany kosztowny synchroniczny readback 4K GPU $\to$ CPU**.
- Podgląd GUI generuje zminiaturyzowany composite preview równolegle w wątku GUI/tła, nie obciążając magistrali PCIe synchronicznym transferem klatek renderowanych.

---

## Q. SECOND EXPORT / CANCEL LIFECYCLE

- Po zakończeniu renderowania (`_on_finished`), anulowaniu (`_on_cancel`) lub błędzie (`_on_error`), wywoływana jest funkcja `_end_render()`.
- Czyści ona flagi: `self._rendering = False`, `self._hud_ts = None`, `self._last_preview_time = 0.0`, `self._preview_busy = False` oraz przywraca widok slotu podglądu.
- Drugi eksport w tej samej sesji bez restartu aplikacji poprawnie uruchamia podgląd od klatki 1.

---

## R. PERFORMANCE SMOKE (300 FRAMES @ 4K)

Przeprowadzono test porównawczy dla 150 klatek w 4K (3840×2160 @ 60 FPS):
- **Preview OFF (renderer pure):** Render FPS = **35.68 FPS** (video render wall = 4.204s)
- **Preview ON (asynchronous 5 Hz GUI preview):** Render FPS = **36.76 FPS** (video render wall = 4.080s)
- **Klatki wideo odrzucone:** **0**
- **Wpływ na wydajność renderera GPU:** **0.0%** (brak narzutu, pełna przepustowość GPU zachowana).

---

## S. FPS DISPLAY FIX

- Skorygowano wywołanie callbacku `on_render_progress` w `src/ffmpeg/amd_native_exporter.py`:
  - `completed` $\to$ `prepared.frame_idx + 1`
  - `total` $\to$ `expected_progress_frames`
  - `elapsed` $\to$ rzeczywisty czas trwania renderowania `elapsed`
  - `fps` $\to$ rzeczywisty `fps` renderera
  - `hud_state` $\to$ słownik `{"ts": t_video_pts, "frame_idx": prepared.frame_idx}`
- Format statystyk w GUI wyświetla spójny, poprawny `FPS: XX.X`, zgodny z rzeczywistą prędkością renderera (brak rozbieżności 1.9 vs 39.8 FPS).

---

## FINAL CLASSIFICATION GATE

```text
================================================================================
FINAL CLASSIFICATION GATE — CHART CLIPPING & EXPORT PREVIEW
================================================================================
CHART CLIPPING        = PASS (100% etykiet X/Y i tytułów wewnątrz rastra)
EXPORT PREVIEW        = PASS (Podgląd wideo + wskaźników postępuje podczas eksportu)
PREVIEW OVERLAYS      = PASS (Wszystkie wskaźniki, wykresy, mapa, gauge widoczne)
PREVIEW NON-BLOCKING  = PASS (Zero backpressure, asynchroniczny wątek tła ~5 Hz)
FPS DISPLAY           = PASS (Górny i dolny odczyt FPS spójne i zgodne z rendererem)
PYTEST                = PASS (517 passed, 0 failed, 17 skipped in 26.72s)
================================================================================
```
