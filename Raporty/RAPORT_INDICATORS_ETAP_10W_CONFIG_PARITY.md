# RAPORT — Audyt spójności właściwości nowo wstawianych wskaźników (CONFIG PARITY)

**Etap:** 10W (NEW INDICATOR CONFIG PARITY)
**Data:** 2026-08-23
**Zakres:** tworzenie wskaźników, wartości domyślne, Property Editor, serializacja, parity konfiguracji. **Bez zmian** pipeline'ów NVIDIA/AMD/Intel/FFmpeg, dekodowania, enkodowania, synchronizacji, telemetrii, map, GPU compositing.

---

## 1. Lista wszystkich typów wskaźników dostępnych w GUI

Pełna lista NIE jest zgadywana — pochodzi z `IndicatorMixin._discover_data_streams()` (jedyne miejsce tworzenia strumieni) + `get_form_for_key()` (`src/indicators/registry.py`):

| Typ (klucz) | Forma | Źródło |
|---|---|---|
| `time_display` | time_display | gpmf (zawsze) |
| `speed_text` / `speed_text_gpx` | gauge | gpmf / gpx |
| `dist_text` | bar (ruler) | gpmf |
| `alt_text` | bar (ruler) | gpmf |
| `iso_text`, `exposure_text`, `temp_text`, `atemp_text` | text | gpmf / gpx |
| `hr_text`, `cad_text`, `power_text`, `battery_text` | chart / text / bar(segments) | gpx |
| `compass` | gauge (compass) | gpmf/fit/gpx |
| `slope_text` | bar (slope) | gpmf/fit/gpx |
| `track_map` | map | fit/gpx/gpmf |
| `accel_*_text`, `gyro_*_text` (8) | chart | gpmf |
| `fit_<field>_text` (dynamiczne, np. `fit_enhanced_speed_text`, `fit_solar_pct_text`, `fit_battery_pct_text`) | wg `get_form_for_key` | fit |

Dodatkowo GUI pozwala zmienić **formę** (`form`): `text`, `gauge`, `bar` (ruler/segments/slope), `chart`, `segment_bar`, `map`, `static_map` — schemat pól dobierany jest w `get_schema_for_form()`.

## 2. Gdzie powstaje każdy nowy wskaźnik

`IndicatorMixin._on_stream_clicked(stream_key)` → `IndicatorMixin._create_indicator(key)` (jedyne miejsce tworzenia). Następnie:
- `_create_indicator` buduje `defaults` (wartości bazowe + specyficzne dla klucza + `get_form_for_key` + `_get_indicator_range`),
- zapisuje do `self.layout["indicators"][key]`,
- `_on_stream_clicked` emituje `sig_properties_ready(key, schema, dict(cfg))` (Property Editor) i `_render_preview()`.

## 3. Gdzie znajdowały się wartości domyślne (PRZED zmianą)

Istniały **cztery niezależne zestawy**:
1. `IndicatorMixin._create_indicator` — słownik `defaults` (tworzenie).
2. `models.py` (`FieldSchema`) — tylko min/max/step, **bez wartości domyślnych**.
3. Property Editor (`_create_field_widget`) — domyślne wartości widgetów: `0` (spinboxy), `False` (checkboxy), `""` (lineedity), pierwsza pozycja combo, `#FFFFFF` (kolor).
4. Renderery (`src/indicators/*.py`) — fallbacki `cfg.get("...", wartość)`.

Dodatkowo preset `presets/cycling_dashboard_v10.json` zawierał kompletne, „ręczne" wartości (np. `major_ticks`, kolory) — kolejny zestaw wzorcowy.

## 4. Tabela wykrytych konfliktów (indicator / property / creation / schema / editor / renderer)

Najważniejsze rozbieżności (przed naprawą; „editor" = wartość widgetu przy braku pola w modelu):

| Indicator | Property | creation | schema | editor (fallback) | renderer (fallback) | Zgodność |
|---|---|---|---|---|---|---|
| dist_text (bar ruler) | `major_ticks` | brak | brak | `0` | `ticks>0?ticks:8` → **8** | ✗ |
| dist_text | `minor_ticks` | brak | brak | `0` | **5** | ✗ |
| dist_text | `show_mid_label` | brak | brak | `False` | **True** | ✗ |
| dist_text | `range_units`, `title_with_unit` | brak | brak | `False` | **True** | ✗ |
| dist_text | `track_color`, `tick_color`, `text_color`, `marker_border_color` | brak | brak | `#FFFFFF` | `#F4F4F4`/`#F6F6F6`/`#F4F4F4`/`#D8D8D8` | ✗ |
| dist_text | `bar_style` | brak | brak | pierwsza combo | `ruler` | ✗ |
| hr_text (chart) | `label_count`, `show_x_axis_values`, `show_y_axis_values`, `chart_time_scope` | brak | brak | `0`/`False`/`activity?` | `2`/`True`/`True`/`activity` | ✗ |
| battery_text (segments) | `segment_inactive_color`, `segment_inactive_opacity` | brak (ale `inactive_color="#333333"`, `inactive_alpha=60`) | brak | `#FFFFFF`/`0.0` | **preferuje nowe pola** → `#333333`/`60/255` | ✗ |
| battery_text | `segment_corner_radius` | brak (ale `segment_radius=4`) | brak | `0.0` | `4` (przez `segment_radius`) | ✗ |
| battery_text | `segment_count` | brak (ale `segments=20`) | brak | `0` | `20` (przez `segments`) | ✗ |
| slope_text | `tick_profile`, `text_color`, `range_color` | brak | brak | `default`/`#FFFFFF` | `default`/`#FFFFFF`/`#DDE7F2` | częściowo |
| compass | `tick_profile`, `text_color`, `show_units` | brak | brak | widget | renderer | ✗ |
| **compass** | **wszystkie pola zakładki „Compass"** | – | – | **nie renderowane** (brak zakładki w `tab_order`) | – | ✗ (osobny błąd) |
| wszystkie | `font`, `icon`, `unit`, `show_units` | zwykle brak | brak | `""`/`none`/`""`/`False` | `""`/`none`/`""`/`True` | ✗ |

## 5. Które właściwości były brakujące w configu nowo utworzonego wskaźnika

Skrypt audytowy pokazał, że **każdy** nowy wskaźnik miał niekompletną konfigurację względem swojego schematu. Przykłady (liczby pól brakujących):
- `dist_text`/`alt_text` (bar ruler): **16** pól (m.in. `bar_style`, `major_ticks`, `minor_ticks`, `show_mid_label`, `range_units`, `title_with_unit`, `track_color`, `tick_color`, `marker_border_color`, `text_color`, `range_color`, `tick_profile`, `unit`…).
- `battery_text` (segments): **41** pól (m.in. `segment_count`, `segment_corner_radius`, `segment_inactive_color`, `segment_inactive_opacity`, `marker_*`, `value_*`, `label_*`, `segment_color_mode`, `fill_direction`…).
- `hr_text`/`cad_text`/`power_text` (chart): **13** pól.
- `track_map`: **24** pola. `compass`: **6** pól. `time_display`: **5** pól.

Renderer „ratował" wygląd własnymi fallbackami, ale **tych wartości nie było w modelu** → Property Editor pokazywał widgetowe `0/False/""`, czyli niezgodnie z rendererem.

## 6. Dlaczego poruszenie kontrolką powodowało „przeskok"

Mechanizm „przeskoku":
1. Nowy wskaźnik miał niekompletny config (brak np. `major_ticks`).
2. Renderer używał własnego fallbacku (np. `major_ticks` → 8), a Editor pokazywał `0`.
3. Użytkownik zmieniał **dowolną** wartość, np. `ticks` 0→5; renderer dla pola `major_ticks` liczony jako `ticks if ticks>0 else 8` nagle przechodził z **8 na 5** — mimo że `major_ticks` w Właściwościach wciąż pokazywało `0`. Efekt: nagła zmiana wyglądu bez jawnej zmiany tej właściwości.
4. Analogicznie dla aliasów segments (`inactive_alpha` vs `segment_inactive_opacity`, `segment_radius` vs `segment_corner_radius`) — renderer **preferuje nowe pola**, więc ich pojawienie się w configu (przy zapisie) natychmiast zmieniało wynik względem legacy.

Samo otwarcie Właściwości **nie mutowało** modelu (Property Editor emituje `sig_property_changed` tylko przy zmianie użytkownika, `_suppress_emit` przy inicjalizacji), więc to nie był problem „setValue→signal→zapis".

## 7. Jakie zostało ustanowione canonical source of defaults

**Jedno źródło prawdy: `FieldSchema.default` w `src/gui/qt/models.py`.** Każde pole każdego schematu (wszystkie formy: text/gauge/bar-ruler/bar-segments/bar-slope/chart/compass/map/time_display) dostało kanoniczną wartość domyślną. Nowa funkcja:

```python
canonical_defaults(schema) -> {name: default for f in schema if f.default is not None}
```

Architektura po zmianie:
```
INDICATOR SCHEMA / CANONICAL DEFAULTS (FieldSchema.default)
        ↓
_create_indicator → KOMPLETNY config
        ↙                     ↘
Property Editor            Preview / Renderer
   (fallback: field.default)   (fallbacki = te same wartości)
```

Canonical defaulty dobrano tak, by **były równoważne fallbackom rendererów** (weryfikacja piksel po pikselu — sekcja 12) oraz wartościom legacy ustawianym przez `_create_indicator` (dla aliasów segments).

## 8. Jak teraz tworzony jest kompletny config

`_create_indicator` po ustaleniu `form`/`bar_style`/`chart_time_scope` uzupełnia brakujące pola:

```python
_schema = compass_indicator_fields() if key == "compass" else get_schema_for_form(...)
for name, default in canonical_defaults(_schema).items():
    if name not in defaults:
        defaults[name] = default
```

Wartości specyficzne dla klucza (bazowe, `get_form_for_key`, telemetryczne min/max) mają pierwszeństwo — uzupełniane są **tylko** pola, których wcześniej brakowało. Weryfikacja: **0 brakujących pól** dla wszystkich badanych typów.

## 9. Jak rozwiązano Property Editor parity

- `_create_field_widget(field, value)` — gdy `value is None` (stary/niepełny projekt), używa `field.default` zamiast widgetowych `0/False/""`.
- Kolory: canonical default = konkretny kolor fallbacku renderera (np. `text_color="#F4F4F4"` dla bar-ruler, `date_color="#D2D2D2"` dla time_display) — Editor pokazuje dokładnie to, co renderuje (nie biały swatch dla „pustego" koloru).
- Naprawiono **osobny błąd**: w `PropertyEditor._build_form` lista `tab_order` nie zawierała zakładki **„Compass"** — wszystkie pola compass (ticki, kolory, format, kardynalne) w ogóle nie były wyświetlane. Dodano `"Compass"` do `tab_order`.

Dzięki temu test „ZERO TOUCH" (model == wartość każdej kontrolki) przechodzi dla wszystkich typów.

## 10. Jak zachowano kompatybilność ze starymi projektami

- Stare/niepełne configi **nie są zapisywane** przy otwarciu (brak silent-write).
- Przy odczycie (Property Editor) brakujące pola dostają canonical default = fallback renderera → Editor pokazuje to samo, co renderuje.
- Renderery zachowały swoje fallbacki (niezmienione) — one teraz pokrywają się z canonical defaultami, więc:
  - nowy kompletny config renderuje się **identycznie** jak wcześniejszy niekompletny (weryfikacja pikselowa),
  - stary config bez nowych pól renderuje się tak samo jak dotychczas.
- Legacy aliasy (np. `gradient`, `inactive_alpha`, `segment_radius`, `segments`) nadal działają — mechanizm rozwiązywania aliasów w `bar.py` nie był ruszany.

## 11. Dodatkowe różnice preview/rendering niezwiązane z defaultami

- **Compass**: brak zakładki „Compass" w Property Editor (naprawiony — sekcja 9).
- **`marker_size`** ma różne fallbacki w zależności od renderera: gauge `0`, bar-ruler `7`, bar-segments-marker `8`, slope `6`; `_create_indicator` ustawia bazowo `6` (gauge) / `7` (map) — per-forma canonical default uwzględnia kontekst, ale pozostaje świadoma rozbieżność „creation vs renderer" dla marker_size w gauge (`6` w configu vs fallback `0`). Nie zmieniano, bo nie powoduje „przeskoku" (pole jest w modelu).
- **`segment_count` vs `segments`**: dla typowego segment bara (battery/solar) canonical `segment_count=20` = creation `segments=20` — spójne. Dla ręcznie przełączonego bara na styl segments z innym `segments` renderer preferuje `segment_count` (ETAP 10T). Odnotowano jako świadome zachowanie nowego pola.
- Pre-existing broken test: `tests/test_fit_registration.py` (import `src.gui.hud_tuner_app`, moduł nie istnieje) oraz `tests/test_static_indicator_cache.py::test_slope_dynamic_marker_and_static_style_miss` — **oba zawodziły PRZED zmianami** (zweryfikowane przez stash). Niezwiązane z tym etapem.

## 12. Zmienione pliki

| Plik | Zmiana |
|---|---|
| `src/gui/qt/models.py` | `FieldSchema.default`, `canonical_defaults()`, canonical defaulty we wszystkich fabrykach schematów. |
| `src/gui/qt/_mixins/indicator_mixin.py` | `_create_indicator` uzupełnia brakujące pola z `canonical_defaults(schema)`. |
| `src/gui/qt/widgets/property_editor.py` | fallback `field.default` przy braku pola; dodanie zakładki „Compass" do `tab_order`. |
| `tests/test_indicator_config_parity.py` | nowe testy A–F. |

## 13. Dodane testy (`tests/test_indicator_config_parity.py`)

- **TEST A** — canonical defaults: dla każdego typu nowy config jest kompletny względem schematu; każde pole ma `default`.
- **TEST B** — Properties parity: dla każdego typu model == wartość każdej kontrolki Property Editor (1:1).
- **TEST C** — no mutation on open: otwarcie/zamknięcie Właściwości nie zmienia configu (`before == after`).
- **TEST D** — one-property change: zmiana jednego pola nie modyfikuje innych (poza dozwolonym sync `size↔font_size` dla formy „text").
- **TEST E** — save/reload: JSON round-trip zachowuje konfigurację (identyczna liczba pól i wartości).
- **TEST F** — old/incomplete config: niepełny stary bar/segment pokazuje w Właściwościach canonical defaults zgodne z fallbackiem renderera.

Dodatkowo weryfikacja braku regresji wizualnej (skrypt tymczasowy): render nowego wskaźnika **przed** (config bez nowych pól) vs **po** (config kompletny) — **piksel po pikselu identyczny** dla: gauge, text, bar-ruler, bar-segments (battery), bar-slope, compass.

## 14. Wyniki testów

- `tests/test_indicator_config_parity.py` → **52 passed**.
- `test_indicator_drag`, `test_etap10k_fit_gui`, `test_etap10k3_fit_speed`, `test_etap10m2_chart_time_axis`, `test_etap10t2_segment_gui_hardening`, `test_etap8m5_gauge_parity`, `test_font_selection`, `test_slope_rendering`, `test_text_size_compatibility`, `test_track_up_map` → **102 passed** (razem z parity: **154 passed**).
- `test_render_tab`, `test_mp4_inspector`, `test_qp_analyzer`, `test_nvidia_regression_chart_preview`, `test_export_lifecycle_p1_fixes`, `test_intel_backend`, `test_gpmf_cache`, `test_pixel_indicator_style`, `test_static_indicator_cache` → **88 passed, 1 deselected** (pre-existing `test_slope_dynamic_marker_and_static_style_miss`, failuje też bez moich zmian).
- `get_errors` na zmienionych plikach → brak błędów.

## 15. Co sprawdzić ręcznie w GUI

1. Dodaj każdy typ (Prędkość, Dystans, Wysokość, Tętno, Moc, Temp., ISO, Compass, Slope, Mapa, czas) → **Właściwości** powinny od pierwszej chwili pokazywać dokładnie te wartości, które widać na podglądzie (m.in. `major_ticks=8`, `minor_ticks=5`, kolory, `show_mid_label=✓`).
2. Compass → zakładka **„Compass"** teraz widoczna (ticki, kolory, format, N/E/S/W).
3. Segment bar (Battery/Solar) → zakładki Text/Segments/Colors/Marker/Range pokazują spójne wartości (m.in. `segment_count=20`, `segment_inactive_opacity≈0.235`).
4. „ZERO TOUCH": dodaj wskaźnik, nic nie zmieniaj, otwórz Właściwości → wartości zgodne z modelem; podgląd bez zmiany.
5. „ONE STEP": zmień dokładnie jedną wartość (np. `major_ticks` 8→7) → zmienia się tylko to (podgląd bez innych niespodzianek).
6. Zapisz preset → zamknij/otwórz projekt → wygląd i właściwości identyczne.
7. Załaduj stary `def_layout.json`/preset v10 → nadal działa, bez nadpisywania pliku przy samym otwarciu.

---

## Podsumowanie (AGENTS.md)

### Changed
`models.py` (canonical defaults + `canonical_defaults()`), `indicator_mixin.py` (`_create_indicator` — kompletny config), `property_editor.py` (fallback `field.default` + zakładka Compass), nowy plik testów `test_indicator_config_parity.py`.

### Preserved
- Pipeline'y NVIDIA/AMD/Intel/FFmpeg, dekodowanie, enkodowanie, synchronizacja, telemetria, mapy, GPU compositing — **bez zmian**.
- Renderery (`src/indicators/*.py`) — bez zmian (fallbacki pozostają, teraz zgodne z canonical defaultami).
- Stare projekty / preset v10 — brak regresji wizualnej (weryfikacja pikselowa), brak silent-write.
- AGENTS.md, Raporty, testy pozostałych etapów — nietknięte.

### Tested
Patrz sekcja 14 (52 + 154 + 88 passed; weryfikacja pikselowa braku regresji dla 6 form).

### Not tested
- Eksport GPU (AMD native / NVIDIA / Intel) na sprzęcie — konfiguracja przekazywana do rendererów jest identyczna (config przed wejściem do pipeline'ów), ale nie wykonywano pełnego eksportu GPU. NVIDIA path preserved statically; runtime validation was not possible on this machine (AMD).

### Risks / Remaining issues
- Pre-existing broken tests (`test_fit_registration.py`, `test_static_indicator_cache.py::test_slope_dynamic_marker_and_static_style_miss`) — niezwiązane z tym etapem, do osobnego zadania.
- Świadome rozbieżności per-renderer dla `marker_size` i aliasów `segment_count`/`segments` (sekcja 11) — nie powodują „przeskoku" po zmianie, bo pola są w modelu.
- `chart_color`/`fill_color`: canonical default `#00AAFF` (spójne z nowym creation); dla bardzo starych configów bez tych pól renderer używa reguły koloru per-klucz — drobna rozbieżność wyświetlania w Editorze dla takich legacy configów (v10 ma jawne kolory).
