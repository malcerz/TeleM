# RAPORT: UPORZĄDKOWANIE PANELU WŁAŚCIWOŚCI DLA SEGMENT BAR (`Forma = bar, Styl = Segments`)

Data: 2026-09-16
Autor: Antigravity / TeleM Team
Gałąź: `amd-bikeridehud`
Środowisko: `C:\_DEV\SportCamHUD`

---

## 1. CEL I ZAKRES ZADANIA

Uporządkowanie panelu właściwości w edytorze GUI dla:
- `Forma = bar, Styl = Segments` (oraz kompatybilności `Forma = segment_bar`).

Zadanie miało charakter **WYŁĄCZNIE GUI**:
- Brak modyfikacji renderera `src/indicators/bar.py`.
- Brak modyfikacji semantyki i matematyki renderera segmentów.
- Brak modyfikacji formatu zapisu/odczytu layoutu JSON.
- 100% zachowanie wstecznej kompatybilności oraz pełna parzystość pikselowa (`diff_pixels == 0`).

---

## 2. AUDYT PARAMETRÓW I KLASYFIKACJA

Przeprowadzono audyt każdego z 68 pól aktualnego schematu (`_bar_segments_fields()` + `_header_fields()`):

```text
SEGMENT_PROPERTIES_TOTAL=68
SEGMENT_PROPERTIES_ACTIVE=68
SEGMENT_PROPERTIES_UNUSED=0
SEGMENT_PROPERTIES_DUPLICATE=0 (przełącznik show_marker przeniesiony do dedykowanej zakładki Marker)
SEGMENT_PROPERTIES_LEGACY=9 (klucze fallbackowe w bar.py zachowane dla starych layoutów JSON v10)
```

### Podział na grupy / zakładki (`GROUPS_CREATED`):
1. **Podstawowe** (Header nad zakładkami + Ikona): `size`, `label`, `unit`, `x`, `y`, `rotation`, `font`, `source`, `form`, `bar_style`, `icon`.
2. **Text** (Wartość, Etykieta i Zakres):
   - Wartość: `show_value`, `value_show_unit`, `value_unit`, `decimals`, `value_align`, `value_font`, `value_font_size`, `value_color`.
   - Etykieta: `show_label`, `uppercase_label`, `label_position`, `label_align`, `label_offset_x`, `label_offset_y`, `label_font`, `label_font_size`, `label_color`.
   - Zakres (Min/Max): `show_min`, `show_max`, `range_units`, `range_font`, `range_font_size`, `range_color`.
3. **Segments** (Geometria i Skala):
   - Geometria: `segments`, `segment_gap`, `segment_shape`, `segment_corner_radius`, `grow_height`, `grow_start`, `segment_fill_mode`, `fill_direction`.
   - Skala danych: `auto_scale`, `min_val`, `max_val`.
4. **Colors** (Kolory i Progi):
   - `segment_color_mode`, `segment_color`, `segment_color_start`, `segment_color_end`, `gradient_space`, `segment_thresholds`, `segment_inactive_color`, `segment_inactive_opacity`.
5. **Marker** (Wskaźnik pozycji):
   - `show_marker`, `marker_style`, `marker_position`, `marker_size`, `marker_offset`, `marker_color`, `marker_border_color`, `marker_border_width`.
6. **Zaawansowane** (Zaawansowane / Mikro-odstępy / Override wymiarów px):
   - `text_color` (domyślny fallback), `value_gap`, `label_gap`, `range_gap`, `segment_width`, `segment_height`, `segment_height_ratio`.

---

## 3. DYNAMICZNA WIDOCZNOŚĆ (`DYNAMIC_VISIBILITY`)

Wdrożono mechanizm `_update_dynamic_visibility()` w `src/gui/qt/widgets/property_editor.py` oraz śledzenie wierszy i etykiet:
- `show_marker == False` lub `marker_style == 'none'` -> wygaszenie kontrolek markera (`marker_position`, `marker_size`, `marker_offset`, `marker_color`, `marker_border_color`, `marker_border_width`).
- `show_label == False` -> wygaszenie kontrolek etykiety (`uppercase_label`, `label_position`, `label_align`, `label_offset_x`, `label_offset_y`, `label_font`, `label_font_size`, `label_color`, `label_gap`).
- `show_value == False` -> wygaszenie kontrolek wartości (`value_show_unit`, `value_unit`, `decimals`, `value_align`, `value_font`, `value_font_size`, `value_color`, `value_gap`).
- `show_min == False` i `show_max == False` -> wygaszenie kontrolek zakresu (`range_units`, `range_font`, `range_font_size`, `range_color`, `range_gap`).
- `segment_color_mode`:
  - `solid` -> aktywne `segment_color`, wygaszone gradient i progi.
  - `gradient` -> aktywne `segment_color_start/end` i `gradient_space`, wygaszone solid i progi.
  - `threshold` -> aktywne `segment_thresholds`, wygaszone solid i gradient.
- `grow_height == False` -> wygaszone `grow_start`.
- `segment_shape != 'rounded'` -> wygaszone `segment_corner_radius`.
- `auto_scale == True` -> wygaszone ręczne wprowadzanie `min_val` i `max_val`.

---

## 4. WYNIKI TESTÓW I WALIDACJI

```text
CONFIG_ROUNDTRIP=PASS (GX010298.layout.json segment bar config before == after)
RENDER_DIFF_PIXELS=0 (100% pixel parity)
GUI_CONTROLS_TESTS=ALL PASS (9/9 interaktywnych testów kontrolek)
UNIT_TESTS=11/11 PASS (test_segment_bar_properties_cleanup.py + test_property_editor_scroll.py)
```

---

## 5. KANDYDACI DO USUNIĘCIA (`CANDIDATES_FOR_REMOVAL`)

Zgodnie z zasadami dyscypliny projektowej, żadne klucze legacy nie zostały usunięte z formatu JSON ani z kodu renderera. Zostały one skatalogowane w `scratch/segment_bar_properties_cleanup/candidates_for_removal.md` do decyzji użytkownika w kolejnym etapie:
- `segment_count` (alias dla `segments`)
- `segment_radius` (alias dla `segment_corner_radius`)
- `inactive_color` (alias dla `segment_inactive_color`)
- `inactive_alpha` (alias dla `segment_inactive_opacity`)
- `gradient` (alias dla `segment_color_start` + `segment_color_end`)
- `direction` (alias dla `fill_direction`)
- `value_font_scale`, `label_font_scale`, `range_font_scale` (aliasy dla `*_font_size`)

---

## 6. ZMODYFIKOWANE PLIKI (`MODIFIED_FILES`)

- `src/gui/qt/models.py` (uporządkowanie schematu `_bar_segments_fields()`, zakładka `Zaawansowane`, ujednoznacznienie etykiet)
- `src/gui/qt/widgets/property_editor.py` (obsługa zakładki `Zaawansowane`, śledzenie wierszy i etykiet, `_update_dynamic_visibility()`)
- `tests/test_segment_bar_properties_cleanup.py` (kompletny zestaw testów schematu, izolacji i dynamicznej widoczności)

---

## 7. PODSUMOWANIE I STATUS

```text
CASE=CASE A — SEGMENT BAR PROPERTY EDITOR CLEANED UP WITHOUT RENDER CHANGES
```

---

## 8. NTFY RESULT

```text
NTFY_SUCCESS=True
```
