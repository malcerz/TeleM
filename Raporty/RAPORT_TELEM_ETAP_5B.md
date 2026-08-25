# TeleM — ETAP 5B — RESULT

Status: **zakończony**. Zakres ograniczono do kompatybilności tekstowych wskaźników `size/font_size`. Nie zmieniano rendererów gauge/chart/bar/map, output scaling ani telemetry pipeline.

## A. Root cause

Legacy layout miał między innymi:

```text
temp_text: size=10.0, font_size=2.5, form=text
```

Renderer używa `font_size`, ale wcześniejszy helper wykonywał `size → font_size`. Zmiana `10.0→10.1` powodowała `2.5→10.1` i skok fontu.

## B. Chosen canonical contract

```text
TEXT SIZE SOURCE OF TRUTH = font_size
```

Renderer zachowuje dotychczasową formułę:

```text
font_px = max(8, round(font_size / 100 × min(canvas_w, canvas_h)))
```

## C. Legacy load policy

| config | effective text size |
|---|---:|
| `size` + `font_size` | `font_size` |
| `font_size` only | `font_size` |
| `size` only | renderer fallback: `size` |
| neither | obecny bezpieczny default renderera |

Load nie modyfikuje legacy JSON. Po świadomej edycji canonical `font_size` kompatybilnościowa kopia `size` jest ustawiana na tę samą wartość.

## D. GUI behavior

Forma `text` ma teraz jedną kontrolkę `Rozmiar`, reprezentowaną przez pole modelu `font_size` (`0.5–10.0`, krok `0.1`). Duplikat `size` został usunięty ze schematu text.

Stare eventy `field=size` są ignorowane przez synchronizację fontu, więc nie mogą wywołać legacy jump.

## E. Changes

- `src/gui/qt/models.py`
  - text header mapuje kontrolkę `Rozmiar` na `font_size`;
  - text schema nie zawiera drugiego pola `font_size` w zakładce Text;
  - `_sync_size_font_fields()` synchronizuje tylko `font_size → legacy size` dla text.
- `src/gui/qt/_mixins/indicator_mixin.py`
  - nowe text indicators startują z `size == font_size`;
  - inne formy zachowują dotychczasowe defaults.
- `tests/test_controller_properties.py`
  - aktualizacja kontraktu legacy eventu.
- `tests/test_text_size_compatibility.py`
  - nowe testy schema, legacy eventu, canonical edit, fallbacków i równych pól.

## F. Real `temp_text` BEFORE / AFTER

Pomiary: content `30.4 °C`, Arial, preview canvas `960×540`.

| stan | stored size | stored font_size | effective GUI size | font_px | bbox/surface | position |
|---|---:|---:|---:|---:|---:|---|
| initial load | 10.0 | 2.5 | 2.5 | 14 | 91×14 | `(16,267)` |
| edit `2.5→2.6` | 2.6 | 2.6 | 2.6 | 14 | 91×14 | `(16,267)` |
| save/reload | 2.6 | 2.6 | 2.6 | 14 | 91×14 | `(16,267)` |

Initial load zachowuje legacy geometrię bez zmian. Nie występuje przejście do `font_size=10.0` ani `10.1`.

## G. Other legacy text indicators

| indicator | legacy size | legacy font_size | effective after load | load geometry |
|---|---:|---:|---:|---|
| `temp_text` | 10.0 | 2.5 | 2.5 | unchanged |
| `iso_text` | 10.0 | 2.5 | 2.5 | unchanged |
| `exposure_text` | 10.0 | 2.5 | 2.5 | unchanged |
| `fit_K1_text` | 10.0 | 1.8 | 1.8 | unchanged |
| `fit_K2_text` | 10.0 | 1.8 | 1.8 | unchanged |
| `fit_curVpower_text` | 10.0 | 1.8 | 1.8 | unchanged |
| `fit_enhanced_altitude_text` | 10.0 | 1.8 | 1.8 | unchanged |
| `fit_temperature_text` | 2.5 | 2.5 | 2.5 | unchanged |
| `fit_battery_text` | 2.5 | 2.5 | 2.5 | unchanged |

## H. Edit regression

For `temp_text`, canonical sequence:

| visible size | font_size | font_px | surface |
|---:|---:|---:|---:|
| 2.5 | 2.5 | 14 | 91×14 |
| 2.6 | 2.6 | 14 | 91×14 |
| 2.7 | 2.7 | 15 | 94×15 |
| 2.8 | 2.8 | 15 | 94×15 |
| 2.9 | 2.9 | 16 | 100×16 |
| 3.0 | 3.0 | 16 | 100×16 |

Zmiany są monotoniczne i wynikają wyłącznie z naturalnego integer rounding. Nie występuje skok `14→55`.

## I. Save/reload

W teście diagnostycznym wykonano serializację kopii runtime:

```text
before save:  size=2.6, font_size=2.6
after reload: size=2.6, font_size=2.6
parity: True
```

Oryginalny `def_layout.json` nie został zapisany ani zmigrowany.

## J. New text indicator

Nowy text indicator w `_create_indicator()` startuje z:

```text
size = 2.5
font_size = 2.5
```

Nie tworzy nowego mismatchu. Dla nowych gauge/chart/bar/map dotychczasowe `size` pozostaje niezależną geometrią widgetu.

## K. Form change

Przy przejściu `other → text` canonical font korzysta z istniejącego `font_size` albo rendererowego fallbacku `size` tylko wtedy, gdy `font_size` nie istnieje. Nie skopiowano automatycznie rozmiaru widgetu do fontu w nowym default flow.

Przy `text → other` `size` pozostaje kompatybilnościową wartością ustawioną przy ostatniej edycji canonical fontu; inne formy nadal interpretują `size` jako własne wymiary.

## L. Preview/final

Preview, CPU final i GPU paths konsumują ten sam runtime layout. Po zmianie GUI wszystkie backendy otrzymują identyczne canonical `font_size`; błąd nie może już zależeć od backendu.

## M. Tests

- nowe: `tests/test_text_size_compatibility.py` — **5 passed**;
- related: `tests/test_controller_properties.py`, `test_chart_rendering.py`, `test_gauge_rendering.py` — łącznie **29 passed**;
- pełna suite: **308 passed, 4 failed, 17 skipped**.

Cztery failure’y są wcześniejsze i niezwiązane: `test_amd_native_etap4.py`, `test_amd_native_etap5b.py`, `test_qp_analyzer.py`, `test_render_tab.py`.

## N. Regressions

Potwierdzono brak zmian w testowanych ścieżkach gauge, chart i bar. Map, output resolution oraz telemetry pipeline nie były modyfikowane.

## O. Remaining issues

### CONFIRMED

Naprawiono `SIZE→FONT_SIZE SEMANTIC JUMP`; `font_size` jest jedynym edytowalnym źródłem text geometry.

### SUSPECTED

Legacy pliki nadal mogą przechowywać historyczne `size != font_size`, ale runtime load pozostaje niedestrukcyjny i używa `font_size`.

### OUT OF SCOPE

Centralny geometry contract, migracja wszystkich presetów, map/gauge/chart scaling, output/viewport scaling i niezwiązane failure’y testów.

