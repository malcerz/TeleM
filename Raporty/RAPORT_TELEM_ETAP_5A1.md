# TeleM — ETAP 5A.1 — RESULT

Zakres: **read-only diagnostic**. Nie zmieniono kodu, testów ani `def_layout.json`. Pomiary wykonano na aktualnym `def_layout.json`, rzeczywistym `temp_text`, stałym contencie `30.4 °C` i foncie `C:\Windows\Fonts\arial.ttf`.

## A. Real `temp_text` config

Aktualny fragment:

```json
"temp_text": {
  "enabled": true,
  "label": "TGP",
  "x": 1.65,
  "y": 49.48,
  "rotation": 0,
  "form": "text",
  "font_size": 2.5,
  "size": 10.0,
  "thickness": 3,
  "min_val": 0.1,
  "max_val": 40.0,
  "ticks": 0,
  "show_value": true,
  "source": "gpmf",
  "decimals": 1,
  "text_offset_x": 0.0,
  "text_offset_y": 0.0,
  "show_units": true
}
```

Stan BEFORE: `form=text`, `size=10.0`, `font_size=2.5`, `x=1.65`, `y=49.48`, `label=TGP`.

## B. Renderer contract

`src/indicators/dispatcher.py:render_value_indicator()` używa `cfg["font_size"]`:

```text
font_px = max(8, round((font_size / 100) × min(canvas_w, canvas_h)))
```

`src/indicators/text.py:_render_text_indicator()` używa przekazanego fontu. `size` nie jest używane przez text renderer do wyliczenia fontu.

Pozycja jest niezależna:

```text
x_px = round((x / 100) × canvas_w)
y_px = round((y / 100) × canvas_h)
```

## C. GUI synchronization contract

`src/gui/qt/models.py:_sync_size_font_fields()`:

```text
form == text, incoming field == size:
    cfg["font_size"] = cfg["size"]

form == text, incoming field == font_size:
    cfg["size"] = cfg["font_size"]
```

Property panel pokazuje oba pola: `size` w nagłówku wspólnym (`1.0–50.0`, krok `0.1`) oraz `font_size` w zakładce Text (`0.5–10.0`, krok `0.1`).

## D. Event flow

```text
QDoubleSpinBox.valueChanged
 → PropertyEditor._emit_change()
 → signals.sig_property_changed
 → AppController._on_property_changed()
 → cfg[field_name] = value
 → _sync_size_font_fields(cfg, field_name)
 → _render_preview()
 → prepare_overlay_frame_data()
 → render_preview()
 → compose_overlay()
 → render_value_indicator()
```

Dla jednej emisji `valueChanged` występuje jedno `_on_property_changed`, jedno wywołanie helpera i jeden refresh preview. Nie znaleziono połączenia `editingFinished` dla tego pola. Ręczne wpisywanie może emitować pośrednie wartości zgodnie z Qt.

## E–F. BEFORE / AFTER `size 10.0 → 10.1`

Diagnostycznie zmieniono tylko kopię runtime configu, bez zapisu pliku. Po handlerze synchronizacja ustawiła `font_size=10.1`.

Canvas preview: `960×540`, stały content: `30.4 °C`, pozycja top-left.

| property | BEFORE | AFTER |
|---|---:|---:|
| size | 10.0 | 10.1 |
| font_size | 2.5 | 10.1 |
| min canvas dim | 540 | 540 |
| computed font_px | 14 | 55 |
| surface width | 91 px | 339 px |
| surface height | 14 px | 46 px |
| bbox x | 16 px | 16 px |
| bbox y | 267 px | 267 px |
| bbox width | 91 px | 339 px |
| bbox height | 14 px | 46 px |
| anchor / position | top-left / `(16,267)` | top-left / `(16,267)` |

Formuła ręczna zgadza się z rendererem:

```text
BEFORE: max(8, round(2.5/100 × 540)) = 14 px
AFTER:  max(8, round(10.1/100 × 540)) = 55 px
```

## G. Geometry delta

Nominalna zmiana `size`: `10.1 / 10.0 = 1.01×`.

```text
font_px ratio     = 55 / 14  = 3.93×
bbox width ratio  = 339 / 91 = 3.73×
bbox height ratio = 46 / 14  = 3.29×
position delta    = (0, 0)
```

Gdyby `font_size` pozostał `2.5`, renderer text nie zmieniłby fontu, ponieważ nie czyta `size`.

## H. Root cause classification

**CONFIRMED SIZE→FONT_SIZE SEMANTIC JUMP**.

Dowód: istniejący preset `size=10.0, font_size=2.5`; edycja `size→10.1`; helper ustawia `font_size=10.1`; font rośnie `14→55 px`, a bbox `91×14→339×46`. Pozycja pozostaje niezmieniona.

## I. Existing text indicators

| indicator | size | font_size | equal? |
|---|---:|---:|---|
| `temp_text` | 10.0 | 2.5 | NO |
| `iso_text` | 10.0 | 2.5 | NO |
| `exposure_text` | 10.0 | 2.5 | NO |
| `fit_K1_text` | 10.0 | 1.8 | NO |
| `fit_K2_text` | 10.0 | 1.8 | NO |
| `fit_curVpower_text` | 10.0 | 1.8 | NO |
| `fit_enhanced_altitude_text` | 10.0 | 1.8 | NO |
| `fit_temperature_text` | 2.5 | 2.5 | YES |
| `fit_battery_text` | 2.5 | 2.5 | YES |

Zakres: **MULTIPLE LEGACY TEXT INDICATORS**, nie tylko `temp_text`.

## J–K. Scope and origin

Klasyfikacja: **LEGACY PRESET COMPATIBILITY ISSUE**. Niespójność istnieje w aktualnym default/legacy `def_layout.json`; nie znaleziono migracji wyrównującej istniejące pary. Historia wskazuje, że layout z `size=10.0` i `font_size=2.5` poprzedza obecną synchronizację/refaktor GUI. Nie modyfikowano historii ani presetów.

## L. Serialization and reload

Zapis presetu serializuje runtime layout bez transformacji. Przed edycją kopia zachowuje `10.0/2.5`; po zmianie zapisany stan miałby `10.1/10.1`; reload użyłby ponownie `font_size=10.1`. To problem shared project config, nie preview-only.

## M. Preview/final impact

**PROJECT-CONFIG BUG AFFECTING PREVIEW AND FINAL.** Błędny stan powstaje przed wyborem backendu. CPU/GPU dziedziczą ten sam layout.

| canvas | BEFORE | AFTER |
|---|---:|---:|
| preview `960×540` | 91×14 | 339×46 |
| CPU overlay `1920×1080` | 173×26 | 668×86 |
| direct final `3840×2160` | 339×51 | 1332×173 |

## N. Confirmed bug

```text
SEVERITY: HIGH (visible geometry discontinuity)
CLASSIFICATION: SIZE→FONT_SIZE SEMANTIC JUMP / LEGACY COMPATIBILITY
FILE: src/gui/qt/models.py
FUNCTION: _sync_size_font_fields()
RELATED: src/gui/qt/_mixins/preset_mixin.py::_on_property_changed()
ROOT CAUSE: loaded text presets have distinct size/font_size semantics, but size edit aliases them
EVIDENCE: temp_text 10.0/2.5 → 10.1/10.1; font 14→55 px; bbox 91×14→339×46; position unchanged
```

## O. Recommended ETAP 5B

Najmniejszy fix powinien dotyczyć wyłącznie kompatybilności formy `text`: ustalić jedno źródło prawdy dla text geometry, zachować legacy `size/font_size` bez skoku przy ładowaniu oraz dodać regresję dla `10.0/2.5 → size=10.1`. Nie wykonywać jeszcze centralnego refaktoru geometrii ani masowej migracji presetów.

## Tests

Read-only test run: pełna suite **303 passed, 4 failed, 17 skipped**. Pozostały te same wcześniejsze, niezwiązane failure’y: `test_amd_native_etap4.py`, `test_amd_native_etap5b.py`, `test_qp_analyzer.py`, `test_render_tab.py`.

