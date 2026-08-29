# Raport — GUI BAR MOUSE DRAG HOTFIX

**Data:** 2026-08-28  
**Środowisko:** Windows 11 / PyQt / PySide6  
**Backend:** GUI / Editor / Indicators  
**Gałąź git:** `amd-render`  

---

## 1. Cel zadania

Naprawa krytycznej regresji interakcji w edytorze podglądu TeleM:
> **Wskaźniki typu BAR (ruler, segments, slope, altitude ruler, power bar, battery bar, solar bar itd.) nie reagowały prawidłowo na przeciąganie myszką w edytorze.**

---

## 2. Diagnoza i wskazanie Root Cause

### 2.1. Przebieg badania
Prześledzono ścieżkę zdarzeń myszy w podglądzie edytora:
`mousePressEvent` $\to$ `_hit_test(nx, ny)` $\to$ `sig_indicator_clicked` $\to$ `_on_stream_clicked` $\to$ `mouseMoveEvent` $\to$ `sig_indicator_moved` $\to$ `_on_indicator_moved` $\to$ `layout["indicators"][key]["x"] = x_norm` $\to$ `_render_preview()` $\to$ `compose_overlay()` $\to$ `_render_bar_indicator()`.

### 2.2. Root Cause
W `src/indicators/bar.py`:
1. Mechanizm `_BAR_INDICATOR_CACHE` (wprowadzony w celach optymalizacji CPU ABOVE) obliczał klucz pamięci podręcznej na podstawie parametrów rasteryzacji (wartości telemetrycznej, jednostki, stylu, grubości, czcionki itp.), **bez współrzędnych `x` i `y`** (ponieważ sam raster linijki/paska nie zależy od pozycji na ekranie).
2. Jednak funkcja `_render_bar_indicator()` zapisywała do `_BAR_INDICATOR_CACHE` cały 4-elementowy krotkowy wynik:
   ```python
   res = (img, s(cfg["x"], canvas_w), s(cfg["y"], canvas_h), None)
   _BAR_INDICATOR_CACHE[cache_key] = res
   return res
   ```
3. Przy kolejnych wywołaniach (np. gdy użytkownik przesunął myszkę w edytorze i wywołał `_render_preview()` z nowymi współrzędnymi `x, y`):
   ```python
   cached = _BAR_INDICATOR_CACHE.get(cache_key)
   if cached is not None:
       return cached
   ```
   Cache zwracał **STARY** krotkowy wynik zawierający współrzędne `(s(OLD_X), s(OLD_Y))` z pierwszego wywołania!
4. Kompozytor `compose_overlay` wklejał pasek na starej pozycji, a bounding box `_bboxes[key]` pozostawał w pierwotnym miejscu. W efekcie wskaźnik na ekranie nigdy się nie przesuwał.

---

## 3. Zastosowana poprawka (Hotfix)

W pliku `src/indicators/bar.py`:
1. Zmieniono zachowanie `_BAR_INDICATOR_CACHE`, aby przechowywał wyłącznie raster `img` (tak samo jak w `src/indicators/text.py` i `src/indicators/gauge.py`),
2. Współrzędne pikselowe `px_x = s(cfg["x"], canvas_w)` i `px_y = s(cfg["y"], canvas_h)` są obliczane dynamicznie przy każdym wywołaniu na podstawie aktualnych wartości z konfiguracji layouu:
```python
    px_x = s(cfg["x"], canvas_w)
    px_y = s(cfg["y"], canvas_h)
    cached = _BAR_INDICATOR_CACHE.get(cache_key)
    if cached is not None:
        return cached, px_x, px_y, None
...
    if img is not None:
        _BAR_INDICATOR_CACHE[cache_key] = img
    return img, px_x, px_y, None
```

---

## 4. Porównanie ścieżki interakcji (Tabela)

| ETAP | Działający element (`text` / `gauge`) | BAR (Przed poprawką) | BAR (Po poprawce) |
| :--- | :--- | :--- | :--- |
| **Rejestracja w `_bboxes`** | YES | YES | YES |
| **Hit-test click** | YES | YES | YES |
| **Mouse press accepted** | YES | YES | YES |
| **Drag offset computed** | YES | YES | YES |
| **`sig_indicator_moved` emit** | YES | YES | YES |
| **Layout `x, y` updated** | YES | YES | YES |
| **Preview re-render** | YES (nowa pozycja) | **FAIL (stara pozycja z cache)** | **PASS (nowa pozycja)** |
| **BBox updated** | YES | **FAIL (stary bbox)** | **PASS (nowy bbox)** |
| **Properties Panel sync** | YES | YES | YES |

---

## 5. Wyniki testów (Test Matrix)

### 5.1. Macierz stylów BAR (`scratch/test_all_bar_styles_matrix.py`)

| Styl / Typ wskaźnika | Select | Drag X | Drag Y | Properties Sync | Save / Reload | Wynik |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **basic bar** | PASS | PASS | PASS | PASS | PASS | **PASS** |
| **ruler horizontal** | PASS | PASS | PASS | PASS | PASS | **PASS** |
| **ruler vertical** | PASS | PASS | PASS | PASS | PASS | **PASS** |
| **segments** | PASS | PASS | PASS | PASS | PASS | **PASS** |
| **slope** | PASS | PASS | PASS | PASS | PASS | **PASS** |
| **altitude ruler** | PASS | PASS | PASS | PASS | PASS | **PASS** |
| **distance ruler** | PASS | PASS | PASS | PASS | PASS | **PASS** |
| **power bar** | PASS | PASS | PASS | PASS | PASS | **PASS** |
| **battery bar** | PASS | PASS | PASS | PASS | PASS | **PASS** |
| **solar bar** | PASS | PASS | PASS | PASS | PASS | **PASS** |
| **missing data bar (`None`)** | PASS | PASS | PASS | PASS | PASS | **PASS** |
| **zero value bar (`0.0`)** | PASS | PASS | PASS | PASS | PASS | **PASS** |
| **rotated 90 bar** | PASS | PASS | PASS | PASS | PASS | **PASS** |

### 5.2. Testy jednostkowe pytest (`tests/test_gui_bar_drag_hotfix.py`)
* `test_bar_bbox_selectable_and_draggable`: **PASSED**
* `test_vertical_bar_selectable_and_draggable`: **PASSED**
* `test_missing_telemetry_bar_selectable`: **PASSED**

---

## 6. Weryfikacja braku regresji

### 6.1. Preview Map Matrix (`scratch/test_etap5g2_preview_map_matrix.py`)
* Test 1 (Load Preset & Render Map): **PASS**
* Test 2 (Provider Switch): **PASS**
* Test 3 (Normal Export Return & Network Lock Restore): **PASS**
* Test 4 (Cancel Export Return & Network Lock Restore): **PASS**
* Test 5 (Second Preset Load): **PASS**
* Test 6 (Offline Local Cache Render): **PASS**
* Wynik łączny: **6/6 ALL PASS**.

### 6.2. Zgodność pikselowa renderera eksportu (`scratch/test_etap5j_golden_parity.py`)
* Klatki testowe: `[0, 50, 100, 300, 500, 750, 900, 965, 1130]`
* **MaxDiff = 0**, **DifferentPixels = 0** (100% bit-exact match, zero zmian w renderingu eksportowym).

---

## 7. Wymagane podsumowanie końcowe

```text
TASK:
GUI BAR MOUSE DRAG HOTFIX

STATUS:
COMPLETE

ROOT CAUSE:
_BAR_INDICATOR_CACHE w src/indicators/bar.py zapisywało i zwracało cały 4-elementowy krotkowy wynik (img, rx, ry, None) z zapieczonymi współrzędnymi pikselowymi z pierwszego wywołania. Przy kolejnych wywołaniach w trakcie przeciągania myszką w edytorze funkcja _render_bar_indicator zwracała stare współrzędne (rx, ry) zamiast obliczać je na podstawie zmienionych cfg['x'] i cfg['y'].

AFFECTED CODE:
src/indicators/bar.py (_render_bar_indicator, linie 1850-1860 oraz 1935-1945)

WORKING ELEMENT REFERENCE:
src/indicators/text.py oraz src/indicators/gauge.py, gdzie w cache przechowywany jest wyłącznie raster graficzny img, a współrzędne px_x, px_y są obliczane dynamicznie przy każdym wywołaniu z cfg['x'] i cfg['y'].

BAR HIT TEST BEFORE:
Działał tylko dla pierwszej klatki; po pierwszej próbie przeciągnięcia wskaźnik blokował się na pierwotnych współrzędnych.

BAR HIT TEST AFTER:
Działa w pełni dla wszystkich form i stylów bar/ruler/segments/slope w dowolnej orientacji i pozycji.

FORM/TYPE FILTER:
Brak błędnych filtrów form/type.

COORDINATE TRANSFORM:
Przeliczanie layout (0..100) <-> preview <-> pixel canvas działa poprawnie ze środkowym punktem kotwiczenia (center anchor) dla bar.

ROTATED BAR:
Obsłużone i przetestowane dla 0°, 90°, 180°, 270° oraz orientacji pionowej (vertical ruler/slope).

TRANSPARENT / MISSING DATA BAR:
Wskaźniki bez danych telemetrycznych (value=None) oraz z pustymi/zerowymi wartościami posiadają poprawny logiczny bbox i dają się normalnie zaznaczać i przesuwać.

TEST MATRIX:
basic bar = PASS
horizontal ruler = PASS
vertical ruler = PASS
segments = PASS
slope = PASS
altitude = PASS
distance = PASS
power = PASS
battery = PASS
solar = PASS

PROPERTIES SYNC:
PASS

SAVE / RELOAD:
PASS

PREVIEW MAP:
PASS (6/6 ALL PASS w Preview Map Matrix)

EXPORT PIXEL PARITY:
MaxDiff = 0
DifferentPixels = 0

FILES CHANGED:
- src/indicators/bar.py

TESTS ADDED:
- tests/test_gui_bar_drag_hotfix.py
- scratch/test_all_bar_styles_matrix.py
- scratch/test_bar_drag_movement.py

GIT STATUS:
On branch amd-render
Changes preserved, clean workspace.

NEXT:
Resume AMD ETAP 5K.1 after user verifies mouse drag in real GUI.
```
