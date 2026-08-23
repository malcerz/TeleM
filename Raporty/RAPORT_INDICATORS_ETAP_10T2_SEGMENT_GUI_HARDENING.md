# Raport: ETAP 10T2 — Segment Bar GUI acceptance + legacy alias hardening

**Data wykonania:** 2026-08-23
**Typ zadania:** `HARDENING / ACCEPTANCE` (Segment Bar GUI na istniejącym presecie v10 + rozwiązywanie konfliktów legacy→nowe aliasy)
**Agent:** GitHub Copilot (DeepSeek V4 Flash)
**Preset bazowy:** `presets/cycling_dashboard_v10.json`
**Materiał testowy:** `Video/GX010115.MP4` + `Video/GX010115.json` + `Video/Jazda_na_rowerze_w_porze_lunchu.fit`
**Zakres:** `src/indicators/bar.py`, `src/gui/qt/models.py`, `src/gui/qt/widgets/property_editor.py` + nowe testy
**Status:** `SEGMENT BAR GUI HARDENING: PASS` / `MAP AA GUI HARDENING: PASS`

---

## 1. Audyt aliasów legacy→nowe (przed naprawą)

| Legacy key (v10) | Nowy key (GUI) | Problem przed 10T2 |
|---|---|---|
| `gradient` (lista) | `segment_color_start` / `segment_color_end` | **BUG**: legacy `gradient` miał priorytet → zmiana `segment_color_start` w GUI nie działała na presecie z `gradient` |
| `inactive_alpha` | `segment_inactive_opacity` | **BUG**: warunek `if new and legacy not in cfg` → legacy `inactive_alpha` blokował nową wartość |
| `inactive_color` | `segment_inactive_color` | OK (nowy już wygrywał) |
| `segment_radius` | `segment_corner_radius` | OK (nowy już wygrywał) |
| `segments` | `segment_count` | OK (nowy już wygrywał) |

Dodatkowo znaleziono **realny crash**: `segment_count=50..100` przy wąskich segmentach dawał `seg_w < 1 px` → `ValueError: x1 must be greater than or equal to x0` w `rounded_rectangle`.

---

## 2. Gradient precedence (krytyczny test)

Odtworzono na **prawdziwym** `fit_battery_pct_text` z v10 (posiada legacy `gradient`):

```python
# przed 10T2: _segment_gradient_stops → legacy gradient wygrywał
# po 10T2:     _resolve_segment_gradient → segment_color_start/end wygrywają
```

`_resolve_segment_gradient`:
```text
segment_color_start/end obecne      → (start, end)      # nowe wygrywa
else legacy gradient (lista ≥2)     → legacy gradient   # fallback dla nietkniętych presetów
else                                → domyślne 2-stop
```

Test `test_v10_battery_new_gui_fields_change_raster` potwierdza: `segment_color_start="#0000ff"` na v10 zmienia raster (gradient staje się `('#0000ff', '#FF9A2E')`).

---

## 3. Inactive color / opacity precedence

- **opacity**: `_resolve_segment_inactive_opacity` — `segment_inactive_opacity` wygrywa nawet gdy `inactive_alpha` obecny (v10 ma `inactive_alpha: 60`). Test: `segment_inactive_opacity=0.2` na v10 → `0.2` (nie `60/255`).
- **color**: `_resolve_segment_inactive_color` — `segment_inactive_color` wygrywa.

---

## 4. Radius precedence

`_resolve_segment_radius` — `segment_corner_radius` wygrywa nad `segment_radius`, z klampowaniem do `min(seg_w, seg_h)/2`. Test `test_v10_radius_sequence_changes_raster` (rectangle→rounded 2→rounded 8→pill, szerokie segmenty) — każda zmiana zmienia raster. Uwaga: przy 20 wąskich segmentach radius jest klampowany — to **poprawne** zachowanie renderera, nie bug.

---

## 5. Segment count precedence

`_resolve_segment_count` — `segment_count` wygrywa nad `segments`. **Naprawiono crash** dla `segment_count ≥ 50` (seg_w<1). Test liczy faktycznie wyrenderowane segmenty przez **liczbę odrębnych kolorów** (rectangle + 2-stop gradient): `5→5, 10→10, 20→20, 37→37, 50→50, 80→80, 100→100` — bez crasha.

---

## 6. Canonical resolution design

Wszystkie aliasy rozwiązane w **jednym miejscu** (sekcja `_resolve_*` w `bar.py`):

```text
_resolve_segment_count()
_resolve_segment_gradient()
_resolve_segment_inactive_color()
_resolve_segment_inactive_opacity()
_resolve_segment_radius()
```

Reguła: **nowa właściwość jawna → wygrywa; else legacy → fallback; else default** (§12). Renderer operuje na wartościach canonical. `_segment_gradient_stops`/`_segment_shape_radius` (stare helpery) usunięte/zdeprecjonowane.

---

## 7. Existing v10 test

`test_v10_untouched_preset_stays_stable`: załadowanie i dwukrotny render nietkniętego v10 → byte-identical. **Migracja nie zmienia wartości na load** (§11).

---

## 8. Battery Pct result

`test_battery_pct_real_normalisation`: `min=87, max=91, value=89` → `_fraction = 0.5` → dokładnie **5 z 10 segmentów aktywnych** (liczone po alpha≥200, nie po alpha>0 które wlicza nieaktywne). Nie `89/91`.

## 9. Solar Pct result

`test_solar_pct_real_config`: realny `fit_solar_pct_text` z v10; nowe `segment_color_start` zmienia raster. Działa.

---

## 10. Color mode switching

`test_colour_mode_switch_each_change_differs`: gradient(red→green) → gradient(blue→yellow) → solid(purple) → threshold → gradient(cyan→green) — **każda zmiana daje nowy raster** na tym samym widgetcie v10.

## 11. Cache invalidation

`test_cache_invalidation_shape_and_mode_sequence` (bez restartu, cache czyszczone tylko na starcie): sekwencja gradient→solid→threshold→rounded→pill→rectangle — każdy krok `!=` poprzedni. Wykrywa dokładnie klasę błędu „segment_radius nie działa”.

---

## 12. Font independence

`test_font_sizes_independent_bbox` + `test_font_family_independent`: zmiana `value_font_size` / `label_font_size` / `range_font_size` zmienia **tylko** odpowiedni tekst; zmiana jednego nie psuje pozostałych. Fonty rodziny (`value_font`/`label_font`/`range_font`) testowane niezależnie.

## 13. Marker acceptance

`test_marker_style_switching_no_restart`: none→triangle→line→circle→none — każda zmiana odzwierciedla konfigurację. `test_marker_props_affect_raster`: size/color/border_color/border_width/position/offset — każde wpływa na raster.

## 14. Marker movement raster

`test_marker_movement_raster`: wartości `0/25/50/75/100` → faktyczna pozycja pikseli markera rośnie monotonicznie (`x0 < x25 < x50 < x75 < x100`). Test rastrowy, nie matematyczny.

---

## 15. Threshold validation

`test_threshold_invalid_inputs_no_crash`: `""`, `"not:valid;;::"`, `"abc"`, `"["`, `"20:;50:"`, `"xx:#ff0000"`, `"20:#ff0000;50"` — **brak crasha** (fallback). `test_threshold_unsorted_duplicates_fallback`: niesortowane/duplikaty bezpieczne.

## 16. Generic FIT test

`test_generic_fit_field_via_segments`: dowolne numeryczne pole (Virtual Power 0–500 W) z gradient+marker — bez hardcodowania pola.

---

## 17. GUI schema completeness

Tabela Property / Renderer / GUI / Save-Load / Tested:

| Property | Renderer | GUI (schema) | Save/Load | Tested |
|---|---|:---:|:---:|:---:|
| `segment_count` / `segments` | ✅ | ✅ | ✅ | ✅ |
| `segment_width` / `segment_height` / `segment_gap` | ✅ | ✅ | ✅ | ✅ |
| `segment_shape` / `segment_corner_radius` / `segment_radius` | ✅ | ✅ | ✅ | ✅ |
| `segment_color_mode` / `segment_color` | ✅ | ✅ | ✅ | ✅ |
| `segment_color_start` / `segment_color_end` | ✅ | ✅ | ✅ | ✅ |
| `gradient` (multi-stop legacy) | ✅ | **usunięte z GUI** (JSON-only, uzasadnione) | ✅ | ✅ |
| `gradient_space` | ✅ | ✅ | ✅ | ✅ |
| `segment_thresholds` | ✅ | ✅ (tekst + placeholder) | ✅ | ✅ |
| `segment_inactive_color` / `segment_inactive_opacity` | ✅ | ✅ | ✅ | ✅ |
| `inactive_color` / `inactive_alpha` (legacy) | ✅ fallback | ✅ (legacy) | ✅ | ✅ |
| `marker_style/size/color/border*/position/offset` | ✅ | ✅ | ✅ | ✅ |
| `show_marker` | ✅ | ✅ | ✅ | ✅ |
| `value/label/range_font` + `_size` | ✅ | ✅ | ✅ | ✅ |
| `value_color` / `label_color` / `value_align` / `label_align` | ✅ | ✅ | ✅ | ✅ |
| `value_gap` / `label_gap` / `range_gap` | ✅ | ✅ | ✅ | ✅ |
| `segment_fill_mode` / `fill_direction` | ✅ | ✅ | ✅ | ✅ |

**Uzasadniony wyjątek** (§23): legacy `gradient` (multi-stop JSON) usunięty z GUI — pole tekstowe pokazywało Python-repr listy i przypadkowa edycja psuła gradient; GUI używa `segment_color_start/end`. Renderer nadal obsługuje `gradient` dla kompatybilności presetów.

## 18. GUI→renderer integration

`test_gui_to_renderer_integration`: dla każdego pola (`segment_color_start`, `segment_color_end`, `segment_inactive_opacity`, `segment_corner_radius`, `value_font_size`, `marker_style`, `marker_color`, `segment_count`, `fill_direction`, `segment_fill_mode`): zmiana FieldSchema → config (jak kontroler) → JSON roundtrip → renderer → raster się zmienia.

## 19. Save/load

`test_save_load_new_wins_after_reload`: preset v10 + nowe pola → zapis (JSON trzyma legacy+new z konfliktem) → reload → **nowa wartość działa** (`gradient=(start,end)`, `opacity=0.2`, `count=7`).

---

## 20. Map AA acceptance

`test_map_aa_config_renders` (AA 1/2/4), `test_map_aa_geometry_preserved_and_edges` (geometria zachowana, raster zmieniony, szerokość nie rośnie), `test_map_outline_does_not_shift_track` (obrys nie przesuwa trasy).

## 21. Map cache invalidation

`test_map_cache_invalidation_aa_and_outline`: mutacja renderera jak w `_render_moving_map_indicator` (AA 1→2→4→1, outline 0→2→4→0) — **każda zmiana odświeża raster** (grid_key uwzględnia AA/outline).

## 22. Moving/static map

Moving map w normalnym playback (pozycja markera nie zmieniona przez AA — markery rysowane po downsample w finalnej rozdzielczości). `test_map_static_aa` — static map respektuje te same properties (z zaszczepionym kafelkiem).

---

## 23. Manual GUI status

```
MANUAL GUI: NOT AVAILABLE
```
Środowisko automatyzacji nie uruchamia interaktywnego GUI (brak ekranu/GPU). Weryfikacja opiera się na testach PropertyEditor→config→renderer (§18) + renderer + schema. Wymagana ręczna akceptacja na maszynie z GUI.

---

## 24. Performance (§37)

```text
v10 legacy               mean=0.518  med=0.502  p95=0.674 ms
v10 + nowe opcje GUI     mean=0.554  med=0.552  p95=0.666 ms
v10 threshold+partial    mean=0.551  med=0.546  p95=0.730 ms
```

Pozostaje w zakresie ~0.5–0.6 ms — **bez regresji** po canonical alias resolution.

## 25. Full suite

```text
806 passed, 17 skipped, 12 failed   (baseline 10T: 773/17/12)
```

Wszystkie **12** porażek to identyczny pre-existing zestaw z 10T (dryf planu pól FIT `def_layout.json`, refaktory chartów, dirty text cache, GPU-eksportowe). **0 nowych porażek** z 10T2. `TypeError float(NoneType)` w slope branch (`bar.py:1556`) — ten sam pre-existing bug (§35), linia przesunięta przez dodane helpery; kod brancha **niezmieniony**.

## 26. Changed files

| Plik | Zmiana |
|---|---|
| `src/indicators/bar.py` | canonical `_resolve_*` helpery (count/gradient/inactive color/opacity/radius) z regułą „nowe wygrywa”; naprawa crashu `seg_w<1` dla `segment_count` 50–100; usunięcie zdeprecjonowanych `_segment_gradient_stops`/`_segment_shape_radius`. |
| `src/gui/qt/models.py` | usunięcie `gradient` z GUI (uzasadniony JSON-only wyjątek); `placeholder` w `FieldSchema`; etykieta progów; zakresy GUI potwierdzone (2..100 itd.). |
| `src/gui/qt/widgets/property_editor.py` | obsługa `FieldSchema.placeholder` dla pól tekstowych. |
| `tests/test_etap10t2_segment_gui_hardening.py` | nowy zestaw 33 testów. |

## 27. Remaining issues

- **Manual GUI acceptance** wymaga maszyny z ekranem/GPU.
- Pre-existing slope `float(None)` bug — osobny bugfix (nie pogłębiony przez 10T2).
- 12 pre-existing porażek suite — odrębne zobowiązania.
- Legacy `gradient` (multi-stop) edytowalny tylko w JSON (uzasadnione).

---

## 41. Final statuses

```text
SEGMENT BAR GUI HARDENING: PASS
MAP AA GUI HARDENING: PASS
```

---

## 42. Repo safety

- `git diff --check` → PASS (tylko pre-existing LF/CRLF warnings).
- Brak tymczasowych plików (0 `*10t*` w scratch).
- Zmienione pliki wyłącznie: `bar.py`, `models.py`, `property_editor.py`, nowy test.
