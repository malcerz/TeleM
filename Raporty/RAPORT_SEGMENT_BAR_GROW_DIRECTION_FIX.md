# RAPORT: Naprawa Semantyki Wzrostu Wysokości Segmentów w Zależności od Kierunku Wypełniania (`fill_direction`)

## 1. Cel Zadania

Wskaźnik segmentowy (`Forma = bar / segment_bar, Styl = Segments`) posiadał niespójność:
Dla `grow_height = True` i `grow_start < 1.0` wysokość segmentów zawsze rosła od lewej do prawej strony (lewa niska, prawa wysoka), niezależnie od parametru `fill_direction`.

Dla kierunku `fill_direction = "reverse"` (Prawo → lewo), gdzie wypełnianie zaczyna się od prawej krawędzi, pasek na początku był szeroki/wysoki (100%), a na końcu wąski (20%), co było odwrotnością oczekiwanej semantyki.

Celem zadania było:
1. Naprawienie semantyki: `grow_start` oznacza wysokość segmentu na **początku kierunku wypełniania**.
   - Dla `Lewo → prawo` (`forward`): lewy segment to początek (`grow_start`), prawy segment to koniec (100%).
   - Dla `Prawo → lewo` (`reverse`): prawy segment to początek (`grow_start`), lewy segment to koniec (100%).
2. Zapewnienie, że dla `grow_start = 1.0` lub `grow_height = False` wszystkie segmenty mają pełną wysokość w obu kierunkach.
3. Zagwarantowanie poprawnej inwalidacji cache (`AMD_CPU_WIDGET_CACHE=1` oraz wewnętrzny cache `bar.py`) przy zmianie kierunku.
4. Pozostawienie GUI i układów w stanie nienaruszonym.

---

## 2. Implementacja w `src/indicators/bar.py`

### 2.1. Nowa Logika Obliczania Współczynnika Wysokości
W funkcjach `_build_seg_base_layer`, `_get_seg_active_layer` oraz `_draw_seg_partial_segment`:
```python
reverse = str(direction).strip().lower() == "reverse"
p = (segments - 1 - i) / max(1, segments - 1) if reverse else i / max(1, segments - 1)
h_mult = grow_start + (1.0 - grow_start) * p if grow_height else 1.0
sh = max(2 * ss, int(round(seg_area_h * h_mult)))
```

### 2.2. Izolacja Pozostałych Warstw i Prawidłowe Wypełnienie
- Kolejność aktywnych segmentów i kierunek ucinania częściowego segmentu (`_draw_seg_partial_segment`) pozostały w pełni zgodne z kierunkiem wypełniania.
- Kolorystyka, gradienty, progi, markery i etykiety min/max zachowały dotychczasową semantykę.

### 2.3. Odświeżenie Klucza Cache
- Do klucza `base_key` w `_render_bar_indicator` dodano parametr `direction`.
- Funkcja `_build_seg_base_layer` przyjmuje parametr `direction`.
- `compute_segment_bar_visual_signature` w `src/indicators/widget_cache.py` zamraża pełny słownik `cfg` (wraz z `fill_direction`), co generuje odmienny podpis i natychmiastowy `CACHE MISS` po zmianie kierunku.

---

## 3. Wyniki Testów

### 3.1. Test 1 — Left to Right (`fill_direction="forward"`, `grow_start=0.20`, `segment_height=200`)
- Segment 0 (lewy): **41 px** (~40 px, 20% pełnej wysokości).
- Segment 19 (prawy): **201 px** (~200 px, 100% pełnej wysokości).
- Wynik: **PASS** (klin rosnący w prawo, plik `ltr_020.png`).

### 3.2. Test 2 — Right to Left (`fill_direction="reverse"`, `grow_start=0.20`, `segment_height=200`)
- Segment 0 (lewy): **201 px** (~200 px, 100% pełnej wysokości).
- Segment 19 (prawy): **41 px** (~40 px, 20% pełnej wysokości).
- Wynik: **PASS** (lustrzany klin rosnący w lewo, plik `rtl_020.png`).

### 3.3. Test 3 — `grow_start=1.00`
- LTR: Segment 0 = 201 px, Segment 19 = 201 px (PASS, plik `ltr_100.png`).
- RTL: Segment 0 = 201 px, Segment 19 = 201 px (PASS, plik `rtl_100.png`).

### 3.4. Test 4 — `grow_height=False`
- LTR: Segment 0 = 201 px, Segment 19 = 201 px (PASS).
- RTL: Segment 0 = 201 px, Segment 19 = 201 px (PASS).

### 3.5. Test 5 — Cache Invalidation
- Podpis `compute_segment_bar_visual_signature` dla LTR vs RTL różni się -> `CACHE MISS` przy zmianie kierunku.
- Cache statyczny `base_key` w `bar.py` rozdziela warstwy bazowe LTR i RTL -> PASS.

### 3.6. Testy Automatyczne Pytest
- `tests/test_segment_bar_properties_cleanup.py`: 11/11 PASSED.
- `tests/test_etap10t_segment_bar_map_visuals.py`: 26/26 PASSED.

---

## 4. Podsumowanie Wymaganych Metryk

```text
FILL_DIRECTION_VALUES=forward, reverse
LTR_FIRST_HEIGHT=41 px (~40 px)
LTR_LAST_HEIGHT=201 px (~200 px)
RTL_FIRST_HEIGHT=201 px (~200 px)
RTL_LAST_HEIGHT=41 px (~40 px)
FLAT_LTR=201 px (~200 px)
FLAT_RTL=201 px (~200 px)
CACHE_INVALIDATION=PASS (signature diff on fill_direction + base_key separation)
MODIFIED_FILES=src/indicators/bar.py, tests/test_segment_bar_properties_cleanup.py, tests/test_etap10t_segment_bar_map_visuals.py
CASE=CASE A — GROW HEIGHT RESPECTS FILL DIRECTION
```
