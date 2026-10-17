# RAPORT: SPORTCAMHUD — NAPRAWA QP ORAZ GRAFICZNEGO SYMBOLU STOPNI

**Data:** 2026-10-14  
**Repozytorium:** `C:\_DEV\BikeRideHUD-main-new`  
**Gałąź robocza:** `fix/gui-freeze-hud-composite`  
**Baseline HEAD przed zmianami:** `a1c1522` (`fix(amd): eliminate multi-file finalization stall by removing global copyts from live mux`)  

---

## 1. PODSUMOWANIE ZMIAN I COMMITY

Zgodnie z wymaganiami zadania zostały wdrożone dwa niezależne, ściśle ukierunkowane commity:

1. **Commit 1:** `2c261914f6b2ea8ec5fd5fe4aeecbda17e074d2f`  
   **Message:** `fix(render): correct QP reporting in export status`  
   **Zakres:** Naprawa raportowania wartości QP w statusie renderingu, rozróżnienie trybu stałego (CQP) od zmiennego (VBR), wyeliminowanie wrażenia zamrożonego licznika, dodanie brakującej metody `get_last_amd_export_stats()`.

2. **Commit 2:** `6dc1eb325be1ceb041cfd7463f114c9c7bf6fe91`  
   **Message:** `fix(hud): render degree unit as font-independent graphic`  
   **Zakres:** Usunięcie fallbacku fontowego (Arial) i wdrożenie całkowicie niezależnego od fontu, wektorowego rysowania symbolu stopni (`°`) jako geometrycznego okręgu (ring/hollow circle) z pełną obsługą skalowania, pozycjonowania (cap-height), koloru, cienia oraz obrysu (stroke/outline) we wskaźnikach HUD (kompas, przechył, tekst, słupek, kompozytor, tekst własny).

---

## 2. ZADANIE 1 — DIAGNOZA I NAPRAWA WSKAŹNIKA QP

### 2.1. Przyczyna stałej wartości `28.0`
W natywnym enkoderze AMF dla kart AMD (`src/encoder/d3d11_amf_encoder.cpp`):
- Enkoder HEVC jest konfigurowany w trybie stałego parametru kwantyzacji: `AMF_VIDEO_ENCODER_HEVC_RATE_CONTROL_METHOD_CONSTANT_QP`.
- Domyślne wartości to `AMF_VIDEO_ENCODER_HEVC_QP_I = 28` oraz `AMF_VIDEO_ENCODER_HEVC_QP_P = 28`.
- Każda zakodowana klatka raportuje sprzętowo wartość feedback QP = 28.
- W konsekwencji `qp_avg` przez cały czas trwania eksportu wynosi dokładnie `28.0`.

### 2.2. Błędy w warstwie eksportera i UI
1. **Brak emisji `current_qp` oraz trybu `is_cqp`:**  
   `src/ffmpeg/amd_native_exporter.py` w callbacku postępu przekazywał wyłącznie `qp_avg=float(...)`, pomijając `current_qp` oraz informację o trybie sterowania przepływnością (`is_cqp`).
2. **Brak metody diagnostycznej:**  
   W `src/ffmpeg/amd_native_exporter.py` brakowało funkcji `get_last_amd_export_stats()`, co powodowało błędy w testach regresyjnych.
3. **Myląca etykieta w GUI:**  
   Interfejs użytkownika prezentował wartość w postaci `QP: 28.0`, co sugerowało użytkownikowi dynamiczny licznik klatkowy, który „zaciął się” na pierwszej wartości.

### 2.3. Wprowadzone rozwiązanie
- **Eksporter (`src/ffmpeg/amd_native_exporter.py`):**
  - Callback postępu emituje teraz `current_qp`, `qp_avg` oraz flagę `is_cqp`.
  - Dodano `_last_amd_export_stats` oraz publiczną funkcję `get_last_amd_export_stats()`.
- **Stan postępu (`src/render_progress.py`):**
  - Rozszerzono `RenderProgressState` oraz `RenderProgressSnapshot` o pola `current_qp`, `qp_avg`, `is_cqp`.
  - W `format_render_progress_status`:
    - W trybie stałym (CQP): wyświetla jednoznaczną informację: `QP avg: 28.0` (lub `QP (target): 28`), nie udając dynamicznego licznika.
    - W trybie dynamicznym (VBR): wyświetla `QP: {cur:.0f} (avg: {avg:.1f})`.
    - Gdy dostępna jest tylko średnia: wyświetla `QP avg: {avg:.1f}`.
- **Widok GUI (`src/gui/qt/_mixins/render_mixin.py` oraz `src/gui/qt/tabs/render_tab.py`):**
  - Etykieta `lbl_stats` formatuje odczyt QP zgodnie z rzeczywistym stanem potoku.

---

## 3. ZADANIE 2 — GRAFICZNY SYMBOL STOPNI (FONT-INDEPENDENT GRAPHIC)

### 3.1. Przyczyna problemu z fontami
- W fontach cyfrowych (np. Digital-7, IONA-U1) oraz wielu fontach dekoracyjnych znak `°` (`\u00b0`) nie istnieje w tabeli glifów (powstaje tofu / pusty prostokąt) lub ma zniekształcone metryki.
- Poprzedni fallback fontowy do systemowego `Arial` w `src/indicators/helpers.py` był półśrodkiem: nadal polegał na obecności fontu Arial w systemie i odrębnym rasteryzatorze tekstu Pillow, co mogło powodować przesunięcia linii bazowej i artefakty.

### 3.2. Wdrożona architektura wektorowego rysowania stopnia
1. **Geometria wektorowa (`get_graphic_degree_metrics`):**
   - Pomiar wysokości wersalików/cyfr aktywnego fontu wskaźnika (`cap_h = cap_bottom - cap_top` z `probe.textbbox((0, 0), "0", anchor="la")`).
   - Średnica zewnętrzna kółka stopnia: `diameter = max(3.0, round(cap_h * 0.28))`.
   - Grubość pierścienia: `thickness = max(1, int(round(diameter * 0.22)))`.
   - Odstęp przed i po kółku: `gap_before = max(1.0, round(cap_h * 0.08))`, `gap_after = max(1.0, round(cap_h * 0.06))`.
   - Pozycja pionowa w indeksie górnym: `deg_top = cap_top + round(cap_h * 0.04)`.

2. **Dwuprzebiegowe rysowanie z obrysem (`draw_graphic_degree_symbol`):**
   - Rysowanie otwartego pierścienia (hollow circle) z przezroczystym środkiem za pomocą `draw.ellipse(..., fill=None, outline=...)`.
   - Obsługa `stroke_width` i `stroke_fill`:
     - Przebieg obrysu: zewnętrzny pierścień o powiększonym prostokącie `[x0 - sw, y0 - sw, x1 + sw, y1 + sw]` i grubości `thickness + 2 * sw`.
     - Przebieg wewnętrzny: właściwy pierścień w kolorze tekstu o grubości `thickness`.
     - Daje to idealnie jednolity obrys zewnętrzny i wewnętrzny bez zniekształceń.

3. **Segmentacja bez fontu (`split_text_degree_chunks`):**
   - Każde wystąpienie `'°'` w tekście jest dzielone na segment `('°', None)` — brak referencji do jakiegokolwiek fontu fallback.
   - Pozostałe segmenty zachowują wybrany font wskaźnika.

4. **Uniwersalny pomiar i renderowanie:**
   - `measure_text_with_graphic_degree`: zwraca łączną szerokość advance, wysokość oraz bounding box z uwzględnieniem kotwicy (anchor: `la`, `mm`, `ma`, `ra`, `lt`).
   - `draw_text_with_graphic_degree`: renderuje tekst i graficzne kółka stopnia w jednym spójnym wywołaniu.
   - Poprzednie nazwy `measure_text_with_degree_fallback` i `draw_text_with_degree_fallback` zachowano jako aliasy zgodności wstecznej.

### 3.3. Integracja we wskaźnikach HUD
- **Kompas (`src/indicators/gauge.py`):**
  - Dynamiczny napis kursu (np. `042°` lub `--°`) w `_render_compass_indicator` rysuje cień i główny tekst za pomocą `draw_text_with_graphic_degree` z `anchor="mm"`.
  - Wartość centralna tarczy zegara (`txt_main` w `_render_gauge_indicator`) mierzy i kasetuje kafelki za pomocą `measure_text_with_graphic_degree` i `draw_text_with_graphic_degree`.
- **Wskaźnik przechyłu (`src/indicators/lean.py`):**
  - `_text_size`, `_draw_text_bounded` oraz `_draw_text_bounded_cached` mierzą i rysują wartości kąta przechyłu (np. `+18.5°`) graficznym kółkiem stopnia, zarówno na podglądzie, jak i w buforze kafli.
- **Wskaźnik tekstowy (`src/indicators/text.py`):**
  - Pomiary szerokości i rasteryzacja etykiet z jednostką `°` lub `°C` (np. temperatura) korzystają z `measure_text_with_graphic_degree` oraz `draw_text_with_graphic_degree`.
- **Słupek / linijka (`src/indicators/bar.py`):**
  - Funkcje pomocnicze `_text_size`, `_draw_text_bounded` i `_draw_text_bounded_cached` w pełni wspierają stopnie.
- **Kompozytor i tekst własny (`compositor.py`, `custom_text.py`):**
  - Rysowanie dodatkowych adnotacji tekstowych oraz nakładek Custom Text obsługuje graficzny symbol stopnia.

---

## 4. WYNIKI TESTÓW I WERYFIKACJA

Uruchomiono ukierunkowane testy jednostkowe:
`python -m pytest tests/test_amd_qp_governance.py tests/test_graphic_degree_unit.py`

```text
============================= test session starts =============================
platform win32 -- Python 3.14.7, pytest-9.1.1, pluggy-1.6.0
rootdir: C:\_DEV\BikeRideHUD-main-new
configfile: pyproject.toml
collected 20 items

tests\test_amd_qp_governance.py ..........                               [ 50%]
tests\test_graphic_degree_unit.py ..........                             [100%]

============================= 20 passed in 0.41s ==============================
```

### Pokrycie testowe:
1. `tests/test_amd_qp_governance.py`:
   - Poprawność formatowania statusu w trybie CQP (`QP avg: 28.0`).
   - Poprawność formatowania w trybie VBR (`QP: 24 (avg: 26.2)`).
   - Przekazywanie `current_qp`, `qp_avg`, `is_cqp` przez `RenderProgressState` i `RenderProgressSnapshot`.
   - Poprawne działanie `get_last_amd_export_stats()`.
2. `tests/test_graphic_degree_unit.py`:
   - Rozbicie tekstu: brak fontu dla symbolu stopnia (`('°', None)`).
   - Skalowanie wymiarów geometrii kółka proporcjonalnie do wielkości fontu.
   - Inspekcja pikseli: weryfikacja przezroczystego środka (hollow ring) oraz obecności obrysu (stroke) i pierścienia (fill).
   - Niezależność od fontu: poprawne renderowanie z różnymi fontami (Arial, Segoe UI, PIL DefaultFont).
   - Poprawność wyrównania dla różnych kotwic (`la`, `mm`, `ma`, `ra`, `lt`).
   - Poprawność renderowania wskaźnika kompasu (`_render_compass_indicator`).
   - Poprawność renderowania wskaźnika przechyłu (`_render_lean_indicator`).
   - Poprawność renderowania wskaźnika tekstowego temperatury (`_render_text_indicator`).
   - Poprawność wskaźnika słupkowego (`bar.py`) i tekstu własnego (`custom_text.py`).

---

## 5. ZACHOWANIE BEZPIECZEŃSTWA REPOZYTORIUM
- Nie modyfikowano pliku `def_layout.json` (pozostawiono w stanie roboczym).
- Nie wykonywano `git reset`, `git clean`, `git stash`, `git rebase`, `merge` ani `push`.
- Nie modyfikowano Single Live Mux, finalizacji 5R-F, logowania 5S ani backendów Intel/NVIDIA.
- Zmiany zatwierdzono w dokładnie dwóch commitach zgodnie ze specyfikacją.
