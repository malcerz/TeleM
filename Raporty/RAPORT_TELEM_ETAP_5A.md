# TeleM — ETAP 5A — RESULT

Zakres: **read-only audit**. W tym etapie nie zmieniono kodu, konfiguracji projektu ani testów. Raport dotyczy rzeczywistego kontraktu `size`/`font_size`; w repozytorium nie ma osobnego pola konfiguracyjnego `indicator.scale`.

## A. Scale architecture

Rzeczywisty przepływ:

```text
GUI property panel
  → layout["indicators"][key]["size"/"font_size"]
  → JSON preset (bez transformacji)
  → compose_overlay(canvas_w, canvas_h)
  → render_value_indicator()
  → renderer form-specific
  → PIL RGBA surface + (x,y)
  → rotated_paste()/compositor
  → preview albo final overlay stream
```

Konkretne punkty:

| etap | plik / funkcja | pole / znaczenie |
|---|---|---|
| GUI schema | `src/gui/qt/models.py`, `_header_fields()` | `size`, 1.0–50.0, krok 0.1 |
| GUI schema | `src/gui/qt/models.py`, `_text_tab_fields()` | `font_size`, zwykle 0.5–10.0, krok 0.1 |
| GUI mutation | `src/gui/qt/_mixins/preset_mixin.py`, `_on_property_changed()` | zapis bezpośrednio do runtime layout |
| text sync | `src/gui/qt/models.py`, `_sync_size_font_fields()` | dla `text`: `size == font_size` |
| serialization | `PresetMixin._on_save_preset()` | JSON dump layoutu, bez przeliczenia |
| dispatcher | `src/indicators/dispatcher.py`, `render_value_indicator()` | `s()`, font, `size_px`, supersample |
| compositor | `src/indicators/compositor.py`, `compose_overlay()` | bbox/anchor/paste |
| preview | `src/indicators/compositor.py`, `render_preview()` | render w wymiarach `src_img` |
| final CPU | `src/ffmpeg/worker_cache.py` → frame renderer | render na overlay canvas, późniejsze FFmpeg resize |
| final GPU/AMD | `src/ffmpeg/amd_native_exporter.py` | compose bezpośrednio w `video_width × video_height`; wybrane elementy capture/composite GPU |

## B. Coordinate systems

| space | wymiar | origin | jednostka | transform |
|---|---|---|---|---|
| indicator local | surface renderera | local `(0,0)` | px | wynik form renderera |
| project/reference layout | canvas przekazany do compositora | lewy-górny | `x/y` = procent 0–100 | `round(value/100 × canvas)` |
| preview source image | `src_img.size` | lewy-górny | px | `compose_overlay(w,h)` bez dodatkowego geometry scale |
| Qt widget | rozmiar `image_label` | lewy-górny widgetu | px | `KeepAspectRatio`, centering/letterbox |
| final overlay canvas | `overlay_w × overlay_h` | lewy-górny | px | render CPU na overlay canvas |
| final output | `render_w × render_h` | lewy-górny | px | FFmpeg skaluje overlay i bazowy video |
| GPU texture | capture surface/bbox | lewy-górny texture | px | GPU bilinear resize/blend według ścieżki |

Qt viewport transform jest niezależny od indicator geometry:

```text
preview_widget_scale = min(widget_w / original_w, widget_h / original_h)
viewport_origin = ((widget_w - original_w*scale)/2,
                   (widget_h - original_h*scale)/2)
```

`devicePixelRatio`/`devicePixelRatioF` nie występuje w aktywnej ścieżce geometrycznej wskaźników. Klasyfikacja: **NOT INVOLVED**.

## C. Scale fields inventory

| field | plik/funkcja | znaczenie | jednostka | default/range |
|---|---|---|---|---|
| `size` | `models.py`, `_header_fields()` | wymiar widgetu; dla text pośrednio font | procent canvasu przez `s()` | 1.0–50.0, default zależny od layoutu |
| `font_size` | `models.py`, `_text_tab_fields()` | rozmiar fontu względny do `min(canvas_w,canvas_h)` | procent min dimension | 0.5–10.0 |
| `x`, `y` | schema + `s()` | pozycja znormalizowana | 0–100% canvasu | krok 0.1 |
| `supersample` | runtime/layout global | raster quality, nie indicator scale | multiplier całkowity | zwykle 1/global antialiasing |
| `canvas_scale` | `moving_map._map_render_plan()` | internal map tile density | multiplier | zależny od canvas width |
| `output_resize_scale` | moving map plan / FFmpeg | raster/output transform | multiplier | wynikowy |
| `scale_x`, `scale_y` | `command_builder.py` | overlay canvas → final output | multiplier | `render_w/canvas_w`, `render_h/canvas_h` |
| `scale` in `map_renderer.py` | tile projection | map pixels → fitted tile viewport | multiplier | computed from map bounds |

W repo nie ma `scale`, `_scale`, `size_scale`, `preview_scale`, `render_scale`, `output_scale` ani `ui_scale` jako indicator config. Występują tylko lokalne skale outputu, viewportu, mapy, tile density i GPMF `SCAL`.

### Jednostka i konwersje

`size` nie jest procentem zapisanym jako 0–100% w sensie `scale=1.0`; jest wartością procentową bezpośrednio używaną przez helper:

```python
s(value, base) = max(1, round(value / 100 * base))
```

Przykładowo `size=10` oznacza około 10% wybranego wymiaru bazowego, a nie multiplier `1.10`. Nie znaleziono `scale/100`, `scale*100`, `1+scale` dla indicator geometry.

## D. Formal scale contract

Nie jest to jeden wspólny kontrakt `indicator_scale`; każdy typ ma własną semantykę `size`.

### TEXT

```text
font_px = max(8, s(font_size, min(canvas_w, canvas_h)))
surface = measured_text(label/value, font_px, outline)
position = (s(x, canvas_w), s(y, canvas_h))
```

Text jest pozycjonowany lewym-górnym rogiem. Dla formy `text` GUI synchronizuje `size` i `font_size`, ale renderer używa `font_size`.

### GAUGE

```text
size_px = s(size, min(canvas_w, canvas_h))
radius = size_px × supersample
rendered gauge ≈ 2.4 × size_px
```

Gauge jest pozycjonowany środkiem. Tło jest rasteryzowane w supersample, potem redukowane; needle jest rysowany w output space z kompensacją `/ss`. Nie stwierdzono podwójnego zastosowania `size`.

### BAR

```text
size_px = s(size, canvas_w)
width = size_px + 40×ss
height = max(24, thickness×6) + 30×ss
```

`size` wpływa na szerokość, nie na wysokość. `thickness` i font są niezależne.

### CHART

```text
chart_w = s(size, canvas_w)
chart_h = max(40, int(chart_w × 0.4))
final_h = chart_h + (font_px + 8 if label else 0) + 4
```

Historia danych i autoscale osi wartości są niezależne od geometrycznego `size`. Supersample chartu jest ustawiany osobno.

### MAP / TRACK_MAP

```text
map_w = s(size, canvas_w)
map_h = map_w
working_size = map_plan(canvas_w, map_w, zoom)
map_img → resize(map_w, map_h) → shape mask → center anchor
```

`size` zmienia viewport rastera. `zoom` i `effective_zoom` są oddzielnymi parametrami; nie znaleziono bezpośredniego zapisu `size → geographic zoom`.

## E. Preview contract

`render_preview()` bierze `src_img.size` i wywołuje `compose_overlay(w,h)`. HUD powstaje w wymiarach obrazu źródłowego preview, a dopiero potem QImage/QPixmap jest skalowany do widgetu z `KeepAspectRatio`. Bbox przekazywany do GUI jest w pikselach oryginalnego obrazu, nie widgetu.

Wniosek: viewport/letterbox nie wpływa na zapisane `x`, `y`, `size` ani bbox; wpływa wyłącznie na prezentację i hit-test przez odwrotną transformację.

## F. Final CPU contract

W renderze CPU overlay jest budowany na `overlay_w × overlay_h`. Dla źródła szerszego niż 1920 px `render_mixin.py` ogranicza overlay do 1920 px z zachowaniem aspect ratio. Następnie `command_builder.py` oblicza:

```text
scale_x = render_w / overlay_w
scale_y = render_h / overlay_h
final_indicator_geometry = overlay_geometry × (scale_x, scale_y)
```

Pozycja i rozmiar overlayu są skalowane w FFmpeg dokładnie raz. Jest to geometrycznie zgodne z renderowaniem bezpośrednio w final dimensions, z możliwym 1 px integer rounding i różnicą interpolacji rastera.

## G. Final GPU / AMD contract

- NVIDIA CUDA: overlay CPU jest skalowany do `render_w × render_h` (`scale=...`), następnie upload/blend przez `overlay_cuda`.
- AMD OpenCL compositor: overlay również jest skalowany do final dimensions przed uploadem, potem `overlay_opencl`.
- AMD native D3D11: `compose_overlay()` otrzymuje `video_width × video_height`, więc geometry powstaje bezpośrednio w final space. Wybrane chart/gauge/map elementy są później capture/composite z bboxem ustalonym przez CPU compose.
- CPU fallback AMD: wraca do CPU overlay contract.

Wspólny kontrakt geometryczny istnieje na poziomie `compose_overlay()` i rendererów form. GPU może zmienić miejsce raster/composite, ale nie deklaruje osobnej semantyki `size`.

## H. Idempotency results

Ponieważ nie ma pola `scale`, test wykonano na rzeczywistym polu `size`, z fontem Arial i stałym contentem `888.8`.

| indicator | sequence | initial bbox/surface | final bbox/surface | parity |
|---|---|---|---|---|
| text | 10 → 11 → 12 → 10 | `(63,45)` | `(63,45)` | PASS |
| gauge | 10 → 11 → 12 → 10 | `(259,259)` | `(259,259)` | PASS |
| chart | 10 → 11 → 12 → 10 | `(200,196)` | `(200,196)` | PASS |
| bar | 10 → 11 → 12 → 10 | `(232,54)` | `(232,54)` | PASS |

Pozycja we wszystkich przypadkach pozostała `(960,540)` dla canvasu 1920×1080. Powtórzenie tej samej wartości cztery razy nie zmieniło geometrii. `NON-IDEMPOTENT SCALE` i `CONFIRMED CUMULATIVE SCALE BUG`: **niepotwierdzone**.

## I. Monotonicity results

Pomiary `size = 5, 6, …, 20`, canvas 1920×1080:

| indicator | surface at 5 | surface at 10 | surface at 15 | surface at 20 | monotonic |
|---|---:|---:|---:|---:|---|
| text (`font_size=size`) | 317×45 | 627×85 | 937×124 | 1246×163 | PASS |
| gauge | 129×129 | 259×259 | 388×388 | 518×518 | PASS |
| chart | 104×106 | 200×196 | 296×289 | 392×381 | PASS |
| bar | 136×54 | 232×54 | 328×54 | 424×54 | PASS |

Nie zaobserwowano `NON-MONOTONIC SCALE BUG`. Integer quantization jest obecna, ale w badanym zakresie nie tworzy regresji rozmiaru.

## J. Preview/final parity matrix

Poniższa macierz jest kontraktem geometrycznym, nie pomiarem monitora. Dla CPU preview/final wynik jest równoważny po sprowadzeniu do tej samej logicznej przestrzeni filmu. Rzeczywisty pomiar pary GPU wymaga aktywnego backendu i realnego renderu; w środowisku audytu nie potwierdzono dostępnego runtime GPU/tiles.

| indicator | size values | preview logical | final CPU logical | final GPU |
|---|---|---|---|---|
| text | 5, 10, 12.5, 15, 20 | `font_size → text bbox`; x/y top-left | same × output factor | shared compose; backend not executed |
| gauge | 5, 10, 12.5, 15, 20 | `2.4×s(size,min_dim)`; center | same × output factor | CPU geometry capture / fallback |
| chart | 5, 10, 12.5, 15, 20 | `w=s(size,canvas_w)`, h≈0.4w + label | same × output factor | CPU chart raster, GPU blend where enabled |
| map | 5, 10, 12.5, 15, 20 | square viewport + map plan | same × output factor | CPU reference or native map path |

Nie ma podstaw do oznaczenia potwierdzonego `PREVIEW_TRANSFORM_ERROR`; istnieje natomiast naturalna różnica rastera/interpolacji i integer rounding.

## K. CPU/GPU geometry parity

| indicator | size | CPU | GPU | delta |
|---|---:|---|---|---|
| text/gauge/chart/map | 5–20 | wynik `compose_overlay` | brak aktywnego pomiaru backendu | N/A |

Kod AMD/NVIDIA używa tych samych bboxów i współrzędnych z compositora dla capture. Różnicę pikselową może wprowadzić bilinear GPU resize, ale nie znaleziono drugiego semanticznego `size`.

## L. Config mutation audit

**RENDER-TIME CONFIG MUTATION: NOT FOUND.**

Rendererzy odczytują `cfg`; nie znaleziono `cfg["width"] *= ...`, `cfg["size"] *= ...` ani zapisu przeliczonego bboxu z powrotem do layoutu. `_on_property_changed()` mutuje config wyłącznie jako normalną operację GUI.

Wyjątek diagnostyczny: obiekty map rendererów aktualizują własne kolory/szerokości markerów przy ponownym użyciu. Jest to stan cache renderera, nie mutacja projektu ani base size.

## M. GUI feedback-loop audit

**GUI FEEDBACK LOOP: NOT FOUND.**

Jedyna synchronizacja to jawne zachowanie dla formy `text`:

```text
size change → font_size = size
font_size change → size = font_size
```

To jest kontrakt formy text, a nie odczyt derived rendered width jako nowego base size. Nie znaleziono ścieżki `renderer → bbox → GUI size → renderer`.

## N. Cache invalidation audit

| cache | wynik |
|---|---|
| `_STATIC_CACHE` | klucze zawierają wymiary/font/supersample i parametry geometryczne dla text/gauge/bar/chart |
| chart background cache | klucz zawiera history identity, width/height, line thickness, supersample, ranges, fonts i style |
| worker precompute | przechowuje chart data, nie gotową geometrię zależną od `size`; render korzysta z bieżącego layoutu |
| moving-map renderer | cache track/zoom/style; grid cache rozróżnia plan/wymiary; output resize jest wykonywany po renderze |
| GPU capture | bbox, dimensions i image/split surfaces są tworzone przy bieżącym compose; brak dowodu na stale-size reuse |

`CACHE INVALIDATION BUG`: **niepotwierdzony**. Dalszy test produkcyjny powinien sprawdzić zmianę `size` przy jednym długim procesie renderera GPU.

## O. Confirmed bugs

Brak potwierdzonego błędu klasy cumulative/double/output/anchor/config/cache na podstawie kodu i pomiarów ETAPU 5A.

## P. Suspected issues

1. TeleM nie posiada centralnego `indicator_scale`; semantyka jest rozproszona między `size`, `font_size`, `supersample`, canvas scale i output resize. To jest **centralny risk kontraktowy**, ale nie dowód konkretnego bug.
2. Forma `text` ma clamp `font_px >= 8`, więc małe zmiany `font_size` mogą nie dawać zmiany pikselowej. To może wyglądać jak skok po przekroczeniu progu i należy sklasyfikować jako `INTEGER_QUANTIZATION`/clamp, nie cumulative scale.
3. Final CPU i GPU mogą różnić się o 1 px przez niezależne `round()` oraz jakością resize (`bilinear` vs `LANCZOS`).
4. Map geometry ma dodatkowy `effective_zoom`/tile-density path; nie jest to indicator scale i wymaga osobnej macierzy z realnymi kafelkami.

## Q. Expected behavior / not bugs

- text może zmieniać bbox zależnie od contentu i clampować font do minimum;
- bar zachowuje stałą wysokość przy zmianie `size`, bo `size` definiuje szerokość;
- chart height wynika z width oraz label/font;
- gauge/bar/chart/map są center-anchored, text top-left-anchored;
- Qt preview ma letterbox/pillarbox, ale bbox pozostaje w source-image coordinates;
- `round()` i minimalne rozmiary powodują naturalne schodki integer geometry;
- różnica `LANCZOS`/`bilinear` dotyczy rastera, nie kontraktu geometry.

## R. Shared vs indicator-specific causes

### CENTRAL CONTRACT RISK

- brak jednego nazwanego helpera `resolve_indicator_geometry()`/`apply_scale()`;
- rozdzielenie `size`, `font_size`, output scale i viewport scale;
- różne canvas dimensions w preview, CPU final i AMD native.

### INDICATOR-SPECIFIC

- text: content-dependent bbox i font clamp;
- bar: width-only `size`;
- chart: width-derived height/labels/history autoscale;
- map: tile density/effective zoom/working-size plan;
- gauge: supersampled background i output-space needle.

## S. Existing tests

Uruchomiono bez zmian:

- `tests/test_controller_properties.py`
- `tests/test_chart_rendering.py`
- `tests/test_gauge_rendering.py`

Wynik: **24 passed**.

Pełna suite: **303 passed, 4 failed, 17 skipped**. Cztery failure’y są wcześniejsze i niezwiązane: `test_amd_native_etap4.py`, `test_amd_native_etap5b.py`, `test_qp_analyzer.py`, `test_render_tab.py`.

Coverage gap: brak testu kontraktu `size/font_size` w identycznej logicznej przestrzeni preview → final dla wszystkich form oraz brak aktywnego CPU-vs-GPU bbox gate dla mapy.

## T. Recommended ETAP 5B

Najmniejszy poprawny etap implementacyjny powinien wprowadzić jeden centralny, niemutujący plan geometrii:

```text
resolve_indicator_geometry(cfg, form, canvas_w, canvas_h, supersample)
  → immutable base dimensions
  → form geometry
  → anchor/position
  → bbox
```

Następnie preview, CPU final i GPU capture powinny konsumować ten sam plan. ETAP 5B powinien dodać testy idempotencji, monotoniczności, output-resolution parity i bbox parity; nie powinien zmieniać semantyki map zoom ani naprawiać niezwiązanych failure’ów.

## Conclusion

Nie potwierdzono kumulowania `scale`, podwójnego indicator scale, mutacji configu ani GUI feedback loop. Najważniejsze ustalenie audytu brzmi: **problem nie ma obecnie jednego pola `scale`; należy rozdzielić istniejące `size`/`font_size` od canvas/output/viewport scaling i dopiero wtedy implementować centralny kontrakt geometryczny.**

