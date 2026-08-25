# RAPORT — Audyt i naprawa BAR dystansu: skala, ticki i marker pozycji

**Etap:** 10X (BAR DISTANCE SCALE CONTRACT)
**Data:** 2026-08-23
**Zakres:** kontrakt ręcznej skali BAR-a dystansu (min/max → preview → rendering), ticki, marker. **Bez zmian** pipeline'ów AMD/NVIDIA/Intel, FFmpeg, synchronizacji, telemetrii, map, GPU compositing.

---

## 1. Gdzie zapisane były ręczne min/max BAR-a

Ręczne `min_val`/`max_val` BAR-a dystansu zapisywane były w configu wskaźnika:
`layout["indicators"]["dist_visual"]` (oraz `dist_text` / `fit_distance_text`) w modelu (`self.layout`), np. `min_val=0`, `max_val=3`. W GUI edytowane przez Property Editor (`sig_property_changed` → `_on_property_changed` → `cfg[field_name] = value`).

## 2. Gdzie i dlaczego były później nadpisywane

W `src/indicators/compositor.py::compose_overlay` istniało **ukryte AUTO** — bezwarunkowe skalowanie zakresu dla wszystkich BAR-ów dystansu:

```python
is_dist_key = key in ("dist_visual","dist_text","fit_distance_text") or (
    current_cfg.get("form") in ("bar","gauge","segment_bar")
    and (current_cfg.get("unit") == "km" or "distance" in key or "dist_" in key))
if is_dist_key and max_distance_m is not None:
    current_cfg["max_val"] = max(current_cfg.get("min_val",0)+0.001, max_distance_m/1000.0)
```

Było to wprowadzone w ETAP 10N3 (raport `RAPORT_INDICATORS_ETAP_10N3_BAR_RULER_DYNAMIC_MARKER_FIX.md`) jako naprawa błędu jednostek (metry vs km), ale **zostało bezwarunkowe** — nadpisywało także ręcznie wpisany `max_val`.

## 3. W którym dokładnie miejscu 3 km zmieniało się na ~24 km

Dokładnie w wierszu `current_cfg["max_val"] = max(..., max_distance_m/1000.0)` w `compose_overlay` (przed wywołaniem `render_value_indicator`). `max_distance_m` = pełna długość trasy w metrach (np. `23926.4 m` → `/1000` → `23.926 km`). Ręczne `max_val=3` było nadpisywane do `23.926` **w każdej klatce**, dla **każdego** wskaźnika dystansu (niezależnie od `source` i tego, czy użytkownik coś ustawił).

## 4. Czy runtime mutował oryginalny config

**Nie.** `current_cfg = ind_cfg.copy()` — kopia (płytka) configu; `current_cfg["max_val"]=...` modyfikowało tylko kopię. Oryginalny `layout["indicators"][key]` pozostawał nietknięty (potwierdzone testem immutability). Problemem nie była mutacja, lecz **nadpisanie skutecznej wartości** na kopii, które trafiało do renderera.

## 5. Jak działała dotychczas logika AUTO/manual

**Nie istniała.** Nie było pola `auto_scale`/`dynamic_scale`/`auto_range`. Skalowanie dynamiczne dla dystansu było **zawsze aktywne** (ukryte AUTO). Speed (`max_speed_kmh`) i alt (`min_alt/max_alt`) mają ten sam wzorzec ukrytego AUTO (nie były przedmiotem tego zadania — odnotowane w pkt. „Risks").

## 6. Skąd pochodziło max_distance_m

Z pełnej trasy (metry) **wg źródła wskaźnika dystansu**:
- `frame_data.prepare_overlay_frame_data`: dla `dist_visual`/`dist_text`/`fit_distance_text` bierze `source` i używa `gpx_track_samples[-1][1]` (gpx) / `fit_data["track"][-1][1]` (fit) / `track_samples[-1][1]` (gpmf).
- `preview_mixin._prepare_cache` — analogicznie.
- `frame_renderer` (final) — `WORKER_CACHE["max_distance_m"]`.
`max_distance_m` pozostaje potrzebny dla AUTO, wykresów i innych funkcji — **nie usunięto**.

## 7. Czy source FIT/GPMF wpływało niespójnie na current/max

**Nie.** `distance_m` (wartość bieżąca, interp. per-source) i `max_distance_m` (auto) pochodzą z tego samego źródła wskazanego w configu wskaźnika (`frame_data`, `preview_mixin`). Zgodność potwierdzona testem TEST 7 (fit → max z fit track, gpmf → z gpmf track, gpx → z gpx track). Problemu „current z FIT / max z GPMF" nie było.

## 8. Jak generowane są major/minor ticks

`_render_ruler` (bar.py):
- `major_divisions` = z `major_step` (jeśli >0), inaczej `cfg.get("major_ticks", ticks if ticks>0 else 8)`.
- `minor_per_major` = `cfg.get("minor_ticks", 5)`.
- Pozycje ticków liczone w obrębie `val_min..val_max` (ułamek `(v-min)/(max-min)` → piksel).

Ticki **zależą od skali** (`val_min/val_max`). Ponieważ skala była nadpisywana (0–3 → 0–24), ticki też powstawały dla skali 0–24 — stąd „inna liczba/rozstaw ticków".

## 9. Jak dokładnie liczona jest pozycja markera

`_render_ruler`:
```python
frac = _fraction(value, val_min, val_max)      # clamp 0..1
marker_x = int(round(pad_x + frac * width))
# rysowanie elipsy wyśrodkowanej na (marker_x, track_y) — środek kropki, nie lewa krawędź
```
`_fraction` = `clamp01((value - lo)/(hi - lo))`. Marker jest **wyśrodkowany** (rysowany od `marker_x - radius`), nie przesunięty o promień.

## 10. Dlaczego kropka znajdowała się w złym miejscu

Matematyka markera była poprawna — ale **względem nadpisanej skali**. Dla ręcznego `max_val=3` i wartości `1.5 km` użytkownik oczekiwał 50%. Ponieważ `max_val` zostało nadpisane na `23.926`, marker liczony był jako `1.5/23.926 = 6.3%` zamiast `50%` (w opisie zadania ~12 km, bo `1.5/12 ≈ 12%` lub wg konkretnej wartości bieżącej). To samo dotyczyło 0% i 100% — skala była inna, więc marker „nie pasował" do ręcznych ustawień.

## 11. Jak została naprawiona ręczna skala

Dodano **jawny parametr `auto_scale`** (bool, default **False** = manual) do schematów BAR-a (ruler/segments/slope) w `models.py` (widoczny w Property Editor, wypełniany przy tworzeniu wskaźnika przez `canonical_defaults`). W `compositor.py` nadpisywanie dystansu jest teraz warunkowe:

```python
if (is_dist_key and current_cfg.get("auto_scale", False) and max_distance_m is not None):
    current_cfg["max_val"] = ...
```

Domyślnie (manual / brak pola) renderer **szanuje ręczne `min_val/max_val`**. AUTO działa tylko po jawnym włączeniu `auto_scale=True`.

## 12. Jak została naprawiona pozycja markera

Naprawa skali (pkt. 11) automatycznie naprawiła marker — ten sam wzór `frac = (value-min)/(max-min)` działa teraz względem **ręcznej** skali. Dla `min=0, max=3, current=1.5` marker = 50%; dla `current=3` = 100%; clamp `_fraction` trzyma marker w zakresie dla wartości spoza skali. Konwersja metrów→km (`raw/1000`) dla wartości bieżącej pozostała bez zmian.

## 13. Zmienione pliki i funkcje

| Plik | Funkcja / miejsce | Zmiana |
|---|---|---|
| `src/indicators/compositor.py` | `compose_overlay` | Nadpisywanie `max_val` dystansu objęte warunkiem `auto_scale`. |
| `src/gui/qt/models.py` | `_bar_ruler_fields`, `_bar_segments_fields`, `_bar_slope_fields` | Nowe pole `auto_scale` (bool, default False). |
| `tests/test_etap10n3_distance_marker.py` | `test_compositor_distance_scaling` | Podzielony na: manual-respected + auto_scale. |
| `tests/test_distance_bar_scale_contract.py` | nowy plik | Testy 1–8 (11 testów). |

## 14. Dodane testy

`tests/test_distance_bar_scale_contract.py`:
- **TEST 1** manual range: `min=0,max=3` → przez compositor effective 0–3; marker 1.5 km = 50% mimo `max_distance_m=24 km`; + `auto_scale=True` używa pełnego dystansu.
- **TEST 2** immutability: `deepcopy(config)` przed/po `compose_overlay` → config bez zmian.
- **TEST 3/4/5** marker 0%/50%/100% (matematyka renderera).
- **TEST 6** clamp: `current<min` → start, `current>max` → koniec.
- **TEST 7** source: `max_distance_m` z tego samego źródła co current (fit/gpmf/gpx).
- **TEST 8** preview/render parity: wspólny `compose_overlay` respektuje ręczny config.

Dodatkowo zaktualizowano `test_compositor_distance_scaling` (10N3) na dwie osobne asercje manual/auto.

## 15. Wyniki testów

- `test_distance_bar_scale_contract.py` → **11 passed**.
- `test_etap10n3_distance_marker.py` → **6 passed**.
- Szerszy zestaw (parity, segment, pixel, slope, render_tab, font, fit_gui, k2/k3, gauge, compass, track_up, drag, mp4_inspector, qp_analyzer) → **164 + 128 passed**.
- Pre-existing (niezwiązane, potwierdzone przez stash — failują też bez zmian): `test_etap8m3_runtime_layout_and_parity.py::test_canvas_isolation_between_below_and_above_map`, `test_etap8m7_chart_frame_clipping.py::test_chart_outer_geometry_stable_after_padding` (off-by-one 123 vs 124 — wrażliwość fontów/geometrii wykresu).

## 16. Czy preview i final rendering mają teraz ten sam effective config

**Tak.** Zarówno preview (`preview_mixin`), jak i final render (CPU/AMD/NVIDIA/Intel przez `frame_renderer` / `amd_native_exporter`) wywołują **ten sam** `compose_overlay` z identycznym `max_distance_m` i configiem z modelu. Naprawa (gate `auto_scale`) działa na wspólnej ścieżce, więc **effective config = model** dla obu ścieżek. Weryfikacja: TEST 1 i TEST 8 (ten sam config → ten sam marker) + brak zmian w żadnym pipeline GPU.

## 17. Czy dotknięto AMD/NVIDIA/Intel

**Nie w pipeline'ach.** Zmiana dotyczy wyłącznie wspólnego `src/indicators/compositor.py` (logika przygotowania configu przed rendererem) oraz schematu GUI. Wszystkie backendy (AMD native D3D11/AMF, NVIDIA NVENC, Intel QSV, CPU) konsumują ten sam `compose_overlay`, więc poprawka obowiązuje dla każdego z nich bez dotykania ich kodu. NVIDIA path preserved statically; runtime validation nie była możliwa na tej maszynie (AMD).

---

## Podsumowanie (AGENTS.md)

### Changed
`src/indicators/compositor.py` (gate `auto_scale` dla dystansu), `src/gui/qt/models.py` (pole `auto_scale` w schematach BAR), `tests/test_etap10n3_distance_marker.py`, nowy `tests/test_distance_bar_scale_contract.py`.

### Preserved
- Pipeline'y AMD/NVIDIA/Intel, FFmpeg, synchronizacja, telemetria, mapy, GPU compositing — bez zmian.
- Renderer `bar.py` (marker/ticki) — bez zmian (matematyka była poprawna).
- `max_distance_m` — zachowane (AUTO, wykresy, inne funkcje).
- `raw/1000` konwersja jednostek — bez zmian.
- Stare projekty: brak silent-write; brak pola `auto_scale` = manual (ręczne min/max respektowane).

### Tested
11 (nowe kontrakty) + 6 (10N3) + 164 + 128 passed; immutability i parity potwierdzone testami.

### Not tested
- Pełny eksport GPU (AMD/NVIDIA/Intel) na sprzęcie — config wspólny dla wszystkich backendów, ale runtime GPU nie był uruchamiany. NVIDIA path preserved statically.

### Risks / Remaining issues
- Speed/alt mają ten sam wzorzec ukrytego AUTO (`max_speed_kmh`, `min_alt/max_alt`) w `compose_overlay` — **niezmienione** (poza zakresem zadania). Jeśli ma obowiązywać ten sam kontrakt manual/auto, wymaga osobnego zadania.
- Stare presety z `max_val` zapisanym w **metrach** (sprzed ETAP 10N3) przy `auto_scale=False` pokażą złą skalę (metry traktowane jako km). Dla takich configów należy włączyć `auto_scale=True` albo poprawić `max_val`. Dotyczy to tylko bardzo starych, ręcznie zapisanych presetów (v10 ma poprawne km).
- Pre-existing failures: `test_etap8m3_runtime_layout_and_parity.py` i `test_etap8m7_chart_frame_clipping.py` (niezależne od tego etapu).
