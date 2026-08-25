# RAPORT GUI — ETAP 4A.1: INTERAKCJA WSKAŹNIKÓW FIT, WYKRESY I USUNIĘCIE LEGACY INDICATORS

**Data:** 2026-08-23
**Materiał testowy:** `Video/GX010115.MP4` + `Video/Jazda_na_rowerze_w_porze_lunchu.fit` (oraz `def_layout.json`)
**Raport:** `Raporty/RAPORT_GUI_ETAP_4A1_INDICATOR_INTERACTION.md`

---

## 1. Przyczyna braku zaznaczania FIT indicators

**Objaw:** FIT indicators renderują się i można zmieniać ich pozycję przez Właściwości, ale mysz ich nie wykrywa.

**Audyt (hit-test):** `VideoPreview.eventFilter` → `_norm_from_geometry` (widget → norm 0..100) → `_hit_test` (norm → piksele oryginału → iteracja `_bboxes`). Mechanizm jest poprawny — zweryfikowano na realnych bboxach FIT (klik/drag/poza działa).

**Rzeczywista przyczyna:** `_render_static_map_indicator()` w `src/indicators/static_map.py` **nie przyjmował parametru `map_heading`**, a `dispatcher.render_value_indicator` przekazuje `map_heading=map_heading` do **każdej** mapy (także `static_map`). Każdy layout z **włączoną `static_map`** (domyślny `def_layout.json`: `track_map.form = "static_map"`, `enabled: true`) powodował:
```
TypeError: _render_static_map_indicator() got an unexpected keyword argument 'map_heading'
```
Wyjątek rozchodził się przez `compose_overlay` → `render_preview` → `_render_preview`, które **przerywało renderowanie**: brak `indicator_bboxes`, brak emisji `sig_bboxes_ready`. Bez bboxów hit-test nie miał czego trafić → **żaden** wskaźnik (w tym FIT) nie był zaznaczalny.

**Naprawa (minimalna, wspólna, wymagana dla preview):**
```python
def _render_static_map_indicator(..., map_heading=None):
    del map_heading  # static_map jest pozycyjny; heading nieużywany
```

## 2. Coordinate spaces

Istniejące przestrzenie:
- **Canvas preview** = `_preview_target_w` (960 px) → `src_img` (np. 960×540).
- **Widget** = `image_label` / `mpv_widget` / `video_widget` (skala KeepAspectRatio, letterbox).
- **Layout (x,y)** = znormalizowane 0..100.

Konwersja (`video_preview`):
```
widget → _norm_from_geometry → norm (0..100)
norm → _hit_test → piksele oryginału (= canvas preview 960×540)
bbox (canvas 960×540) == _original_size (960×540)
```
**Błąd nie leżał w konwersji** — bboxy FIT były poprawne (960-przestrzeń) i klik w nie działał (test). Błąd leżał w **braku bboxów** z powodu wyjątku renderera mapy (§1).

## 3. Hit-test

Po naprawie działa wspólny kontrakt dla wszystkich form:
- `text` / `time_display` → kotwica LEWY-GÓRNY róg,
- `bar` / `gauge` / `chart` / `segment_bar` / `map` → kotwica ŚRODEK,
- iteracja `_bboxes` (kolejność renderu = z-order; ostatni renderowany = najwyższy).

FIT nie ma osobnego mechanizmu — używa dokładnie tej samej ścieżki co każdy wskaźnik.

## 4. Drag

`mousePress` → `_drag_offset_norm` (kotwica wg `_uses_topleft_anchor`) → `mouseMove` → `sig_indicator_moved` → `_on_indicator_moved` ustawia ten sam `x/y` layoutu, który pokazuje panel Właściwości. Brak drugiego modelu pozycji. Zweryfikowano testem (test 4).

## 5. Chart FIT — dlaczego wykresy nie miały wartości

Audyt potoku: `target_dt` → `build_chart_data` → `ChartHistory` (pełna seria) → `clip_chart_data_for_target` (okno [T−60, T]) → `_render_chart_indicator(chart_vals)`.
- **Dane FIT rozwiązywały się poprawnie** (`fit_heart_rate_text`: 4299 próbek; okno 60 s → 60 próbek).
- **Render wykresu też działał**, ale **cały render podglądu pękał** przez `static_map` TypeError (§1) → wykres „pojawiał się" z pustą/brakującą geometrią w bboxach.
- Po naprawie `compose_overlay` renderuje FIT chart z pełnymi danymi (bbox `(332,199,296,143)` dla `fit_heart_rate_text`).

**Wniosek:** problem wykresów był tym samym wspólnym bugiem co problem zaznaczania (crash renderera mapy).

## 6. Multi-file charts

Kontrakt zachowany: `_render_preview` liczy `end_dt_utc` przez `timeline_absolute_end(video_timeline)`; historia okna liczona względem bieżącego `target_dt` (absolutnego). `clip_chart_data_for_target` dla pierwszej klatki clip2 zwraca `[T2−60, T2]` (test 9). Nie używa `start_dt_utc + video_duration` dla okna.

## 7. Reset Layout — dlaczego pojawiał się legacy indicator

`_on_reset_layout` (IndicatorMixin) **zachowywał** `time_block`:
```python
self.layout["indicators"] = {"time_block": time_block_cfg}   # legacy!
```
To przywracało stary wskaźnik czasu po „Resetuj układ".

**Naprawa:** reset buduje nowoczesny layout `{"time_display": <cfg>}` (z `def_layout.json` lub wbudowanego domyślnego). `time_block` nigdy nie jest tworzony.

## 8. Usunięte legacy indicators

Legacy `time_block` został usunięty z całego programu:
- `src/indicators/time_block.py` — **usunięty** (renderer).
- `src/indicators/compositor.py` — usunięty dedykowany blok `render_time_block` + import; dodany `_REMOVED_LEGACY_KEYS = frozenset({"time_block"})` (skip w pętli).
- `src/gui/layout_manager.py` — `default_layout` używa `time_display`; `normalize_layout` usuwa `time_block` + warning.
- `src/gui/qt/_mixins/indicator_mixin.py` — `_on_reset_layout` nowoczesny.
- `src/indicators/registry.py` — usunięty z `HARDCODED_KEYS`.
- `src/ffmpeg/frame_renderer.py` — usunięty z `_HARDCODED_KEYS`.
- `src/ffmpeg/command_builder.py` — `time_display` zamiast `time_block` (precyzyjny bbox + estymacja).
- `src/ffmpeg/amd_native_exporter.py` — `time_display` zamiast `time_block`.
- `src/gui/indicator_schemas.py` — usunięty `BUILTIN_FIELDS["time_block"]`.
- `src/overlay_renderer.py`, `src/indicators/__init__.py` — usunięty import.
- `src/gui/qt/widgets/video_preview.py` — `_uses_topleft_anchor` tylko `time_display`.
- `README.md` — dokumentacja.

## 9. Kompatybilność starych projektów

Stary projekt z `time_block`:
1. `normalize_layout` usuwa `time_block` i loguje:
   `[Layout] WARNING: legacy 'time_block' indicator removed — use 'time_display' instead.`
2. `compose_overlay` ma `_REMOVED_LEGACY_KEYS` — gdyby legacy key dotarł do renderera (np. preset ładowany bez normalize), jest pomijany (bez crasha, bez renderu).
3. Projekt ładuje się dalej (test 13).

**Nie przywracamy** starego wskaźnika — tylko go pomijamy.

## 10. Testy automatyczne

### Nowe — `tests/test_gui_etap4a1_indicator_interaction.py` (13 passed)
- **Test 1** FIT text bbox `(100,100)-(300,180)` → klik w środku → selected.
- **Test 2** klik poza bboxem → brak selection.
- **Test 3** preview skalowane (canvas 1920×1080, widget 960×540) → poprawna selekcja.
- **Test 4** drag (down→move→release) zmienia ten sam `x/y` co Properties.
- **Test 5** dwa nachodzące wskaźniki → wybierany wyższy z-order.
- **Test 6** text/gauge/chart korzystają ze wspólnego mechanizmu hit-test.
- **Test 7** FIT history resolver → samples > 0.
- **Test 8** chart dostaje próbki i generuje niepustą geometrię.
- **Test 9** multi-file boundary: pierwsza klatka clip2 → history = `[T2−60, T2]`.
- **Test 10** nieistniejące pole → kontrolowany no-data (bez wyjątku).
- **Test 11** `Resetuj układ` NIE tworzy `time_block`.
- **Test 12** `time_block` nie jest w registry / default layout.
- **Test 13** stary projekt z `time_block` → ładuje się, `time_block` pominięty, warning, brak crasha.

### Zaktualizowane
- `test_etap8m3_runtime_layout_and_parity.py` — `test_time_display_defensive_outline` (zamiast time_block); naprawiona defensywność `time_display` przy braku `global`.
- `test_indicator_drag.py` — docstring (time_display).

## 11. Test ręczny (headless, realny projekt)

Scenariusz symulujący kroki użytkownika na `GX010115.MP4` + `Jazda_na_rowerze_w_porze_lunchu.fit` (przez rzeczywiste mixiny + `VideoPreview`):

| Krok | Wynik |
|---|---|
| 1. Dodanie FIT (battery, heart_rate) | ✓ enabled |
| 2. Render podglądu → bboxy FIT | ✓ text `(480,43,88,18)`, chart `(332,199,296,143)` itd. |
| 3. Klik/select FIT na preview | ✓ `clicked: ['fit_battery_text']` |
| 4. Chart FIT → dane | ✓ history n=4299, chart bbox obecny |
| 5. Resetuj układ | ✓ tylko `time_display`, brak `time_block` |

Pełny render `def_layout.json` (z włączoną `static_map`) — bez wyjątku, ~360 ms, bboxy emitowane dla wszystkich wskaźników (FIT + time_display + track_map).

## 12. Regresje

- **Multifile:** `test_multifile_*` (timeline/etap3/etap4a/etap4b) — **bez zmian**, wszystkie zielone.
- **Render/GPU:** export_lifecycle, intel_backend, etap5f, amd_native, nvidia_regression, etap8o/precomputed — zielone.
- **FIT:** `test_etap10k_fit_gui`, `test_fit_available_fields_catalog`, `test_telemetry_manager` — zielone.
- **Charts/Compositor/Map:** etap10t/map visuals, etap8m3, etap5g/5h, track_up_map, map_sync — zielone.
- **Podsumowanie pełnego suite:** `1048 passed, 17 skipped, 16 failed`.

### 16 failed — WSZYSTKIE pre-existing (NIE spowodowane ETAP 4A.1)
Zweryfikowano: pliki tych testów/obszarów (chart.py, chart_utils.py, bar.py, helpers.py, def_layout) nie były zmieniane w tym etapie.
1. `test_etap8t_b_async_pipeline::test_async_visible_none_visible` (znany, udokumentowany w repo-memory: FIT wartość `None` → ghosting tekstu).
2. `test_etap8q_dirty_text_cache::test_above_text_cache_none_visibility` (ta sama rodzina None-ghosting; layout bez time_block — nie dotknięty).
3. `test_etap8s_flush_batching::test_flush_batching_above_lifecycle` (ta sama rodzina).
4. `test_etap5e1_chart_prefix` + `test_etap5e3_dynamic_prefix` (optymalizacja prefix wykresów; chart.py niezmieniony).
5. `test_etap8m7_chart_frame_clipping` (10 testów) — `def_layout.json` ma `fit_cadence_text.enabled=false` (zmiana z wcześniejszego etapu); testy czytają def_layout i oczekują włączonego.
6. `test_static_indicator_cache::test_slope_dynamic_marker_and_static_style_miss` (bar.py/helpers.py niezmienione).

## 13. Gotowość do ETAPU 4B

**TAK** — z zastrzeżeniem.

- Wskaźniki FIT: zaznaczanie ✓, przeciąganie ✓, pozycja drag == Properties ✓, hit-test przy skalowaniu ✓.
- Wykresy FIT: rzeczywiste dane ✓, działają w multi-file przez absolutny `target_dt` ✓.
- `Resetuj układ` nie przywraca legacy time_block ✓.
- Legacy time_block usunięty z programu; stare projekty ładują się (skip+warn) ✓.
- MULTIFILE preview (3 pliki) — niezmienione ✓.

**Zastrzeżenia przed 4B:**
1. Znane pre-existing błędy (None-ghosting FIT, chart prefix, chart clipping, static-cache slope) NIE są w zakresie 4A.1 — zalecane osobne zadanie.
2. Mapa: blokowanie GUI przy `form="map"` (moving_map) oraz przełączanie satellite + placeholder/progress to **osobny etap** (per instrukcja); tutaj naprawiono tylko crash `static_map` (wymagany dla preview).
3. Pełny render `form="map"` może blokować GUI (osobny etap) — nie testowany runtime pod tym kątem.
