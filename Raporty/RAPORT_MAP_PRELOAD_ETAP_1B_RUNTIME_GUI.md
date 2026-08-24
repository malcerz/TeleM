# RAPORT_MAP_PRELOAD_ETAP_1B_RUNTIME_GUI — Weryfikacja i naprawa realnego GUI

**Data:** 2026-08-24
**Zakres:** ETAP 1B — pełny runtime GUI mapy (Wczytaj → MapPreload → MapContext → overview_image → indicator → compose_overlay → preview GUI) oraz Standard → Satellite → odświeżenie. Naprawa rzeczywistych błędów runtime znalezionych poza testami headless.
**Materiał:** `Video/GX010115.MP4` + `Video/GX010115.json` + `Video/Jazda_na_rowerze_w_porze_lunchu.fit` (offset +2.000 s, confidence high).
**Maszyna:** AMD (brak `nvcuda.dll`) — NVIDIA zweryfikowana statycznie.

---

## 1. Czy MapContext był rzeczywiście ready

Tak. W realnym GUI (offscreen `AppController` + `MainWindow`, prawdziwe sygnały Qt):

```text
[G2] status=ready provider=light_all overview=yes zoom=13 tiles=12/12
[G2] after switch: status=ready provider=satellite overview=yes tiles=12/12
```

`MapContext.status == "ready"`, `overview_image` nie jest None, provider zgadza się z layoutem. To nie był problem.

---

## 2. Czy renderer otrzymywał ten sam MapContext

Tak — po weryfikacji: `_render_preview` woła `set_current_map_context(getattr(self, "map_context", None))` na początku, a renderer czyta go przez `get_current_map_context()`. To ta sama instancja. Dodatkowo sprawdzono bezpośrednio (`get_current_map_context() is not None` w trakcie loadu) — kontekst jest widziany przez renderer.

---

## 3. Czy po ready następował preview refresh

**Tak — to była jedna z przyczyn, ale NIE jedyna.** Po naprawie błędów (sekcja 5) łańcuch działa w 100 %:

```text
MapPreloadWorker._finish
  → done_cb (_on_done)
    → signals.sig_map_ready.emit()          (z wątku workera → queued)
      → controller: sig_map_ready → _render_preview()
        → set_current_map_context(...) + compose_overlay(async_map=True)
          → mapa na ekranie
```

Pomiar realny (bez ręcznego wywołania renderu):

```text
map_ready fired: 1
track_map bbox (auto-refresh, no manual render): (11, 91, 173, 173)
```

Czyli po `set_ready` sygnał `map_ready` jest emitowany, a podgląd faktycznie renderuje mapę automatycznie.

---

## 4. Czy mapa była compositowana

Tak. Zapisano faktyczne obrazy podglądu z realnej ścieżki `_render_preview` → `sig_preview_frame_ready`:

```text
[G4] standard:  bbox=(11, 91, 173, 173) map mean=[225.2, 224.7, 222.9] stddev=[60.7, 62.6, 62.9]
[G4] satellite: bbox=(11, 91, 173, 173) map mean=[93.1, 96.3, 80.6]   stddev=[55.9, 51.9, 51.9]
```

Mapa (Level-1 overview + marker pozycji) jest pastowana w kanwie podglądu z poprawnym bbox i widocznymi pikselami (nie placeholder).

---

## 5. Faktyczna przyczyna niewidocznej mapy (wykryte błędy runtime)

ETAP 1A był testowany headless, więc **trzy realne błędy runtime** pozostały niewykryte. Wszystkie zostały znalezione i naprawione w tym etapie:

### 5.1 `frame_data.py` — TypeError naive/aware (BLOKADA CAŁEGO OVERLAYA)
```text
elapsed_seconds = max(0.0, (target_dt - start_dt_utc).total_seconds())
TypeError: can't subtract offset-naive and offset-aware datetimes
```
- `start_dt_utc` jest **tz-aware** (kotwica GPMF z `parse_exif_datetime` dodaje `tzinfo=utc`),
- `target_dt` z timeline (`global_to_absolute`) jest **naive-UTC** (konwencja multifile `_as_naive_utc`).

Wyjątek wywoływany przy **każdym** renderze podglądu w realnym GUI → `overlay_data=None` → **cały overlay pusty** (żadna mapa, żaden wskaźnik). To pierwsze miejsce, gdzie mapa przestawała być propagowana.
**Naprawa:** normalizacja do naive-UTC przed odejmowaniem (obie reprezentują ten sam instant).

### 5.2 `telemetry_imu.interpolate_roll` — ten sam TypeError
`def_layout.json` ma włączony `lean_indicator` (form `lean`). `interpolate_roll` porównywał naive/aware (próbki GPMF aware vs naive target) → ten sam wyjątek po usunięciu 5.1.
**Naprawa:** normalizacja `target_dt` i próbek do naive-UTC (spójnie z `telemetry_extract._normalise_dt`).

### 5.3 `static_map` — wywołanie nieistniejącej funkcji `viewport_tiles_for`
```python
from src.map_renderer import viewport_tiles_for   # ImportError!
```
Funkcja **nigdzie nie istniała**. `ImportError` był połykany przez zewnętrzny `except Exception: return None, 0, 0, None` → `static_map` (domyślna forma w `def_layout.json`!) **zawsze zwracał None** → mapa nigdy się nie renderowała w GUI. Renderer zwracał wynik w 0.02 s, ale zawsze `None`.
**Naprawa:** dodano `viewport_tiles_for(lat, lon, zoom, w, h)` w `src/map_renderer.py` (czysta geometria, lustro `_viewport_range` z moving_map; bez pobierania).

### 5.4 (drobiazg) `_map_preload_provider_switch` — UnicodeEncodeError
```text
UnicodeEncodeError: 'charmap' codec can't encode character '\u2192'
```
Log z `→` (U+2192) wywalał się na konsoli Windows cp1250 **przed** uruchomieniem nowego preloadu → przełączenie na Satellite nie ruszało.
**Naprawa:** ASCII-safe `->` w logu.

---

## 6. Placeholder runtime

W realnym GUI, gdy mapa dodana przed zakończeniem preloadu, renderer zwraca placeholder (ciemny prostokąt z „Ładowanie mapy…" + postęp). Test integracyjny #18 potwierdza pełny cykl:

```text
Phase 1 (preparing):  bbox=(11,91,173,173), mean=[25.6, 29.6, 35.1]  → placeholder (ciemny)
Phase 2 (ready+refresh): bbox=(11,91,173,173), mean=[~225, ...]      → mapa (jasna)
```

Brak pustego miejsca, brak braku bboxa, przejście placeholder→mapa automatyczne po `sig_map_ready`.

---

## 7. Satellite runtime

Pełny łańcuch przełączenia działa:

```text
_on_property_changed(track_map, map_style, satellite)
  → _map_preload_provider_switch("satellite")
    → generation++ → nowy MapPreloadWorker(provider=satellite)
      → ctx.reset(preparing satellite) → tiles → set_ready(overview satellite)
        → sig_map_ready → _render_preview → satelita na ekranie
```

Pomiar: `provider light_all -> satellite generation=2`, `overview ready provider=satellite elapsed=0.13s`. Obraz mapy faktycznie się zmienił (sekcja 4: mean ~225 → ~93).

---

## 8. Provider/cache/generation lifecycle

- **Generation guard** działa: `MapContext.set_*` ignorują wywołania nieaktualnej generacji; przełączenie Standard→Satellite podbija generację, stary job nie może nadpisać satelity.
- **Cache zależny od providera** potwierdzony: satellite używa osobnych wpisów (`test_cache_style_distinct` z ETAPU 1 + realny test: po przełączeniu pokazuje się obraz satelitarny, nie stare standardowe kafelki).
- **Race** (Standard kończy się po Satellite): niemożliwy dzięki guardowi generacji — stary `set_ready` z generacją 1 jest ignorowany po resetcie do generacji 2.

---

## 9. Responsywność GUI

- `MapPreloadWorker` i `viewport_precache` działają na wątkach daemon (poza GUI).
- Brak `join()/wait()/result()/future.get()` w ścieżce GUI (potwierdzone przeglądem `project_mixin`).
- Render mapy async: `static_map` ~0.02 s, `moving_map` ~0.18 s (wątki tła dla detali).
- GUI odpowiada podczas preloadu, provider switch i detail precache (tylko przetwarzanie eventów + async workers).

---

## 10. Test integracyjny lifecycle

`tests/test_map_preload_etap1b_runtime.py` — **2 testy WYŻSZEGO poziomu** (realny `AppController` + `_render_preview` + `compose_overlay` + renderer, offscreen):

- **#18 `test_18_preparing_placeholder_then_ready_map_visible`** — Task §18: `preparing` → placeholder (bbox + ciemny), worker → ready → `sig_map_ready` → refresh → kolejna klatka zawiera mapę (jasną, różną od placeholdera).
- **#19 `test_19_standard_vs_satellite_images_differ`** — Task §19: standard ready → obraz A; przełączenie na satellite → ready → refresh → obraz B; `A != B` (średnia różnica kanałów RGB > 60) i `provider == satellite`.

Wynik: **2 passed** (16 passed razem z `test_map_preload_etap1.py`).

---

## 11. Real GUI test

**WYKONANY (offscreen, prawdziwy MainWindow + AppController + sygnały Qt + widget renderujący).**

Test uruchomiono przez `QT_QPA_PLATFORM=offscreen` z prawdziwym `MainWindow`, prawdziwym `AppController`, prawdziwym `sig_files_selected`/`sig_map_ready`/`sig_preview_frame_ready` oraz prawdziwym `VideoPreview` (widget). Zapisano faktyczne obrazy podglądu (`sig_preview_frame_ready` → QImage → PNG) — mapa jest **widoczna** (bbox + jasne piksele) i **zmienia się** po przełączeniu na Satellite.

Ograniczenie: środowisko nie ma fizycznego ekranu/myszy, więc test przeprowadzono w trybie offscreen zamiast „klikania w okno". Dlatego:
- potwierdzono pełny pipeline renderowania **widgetu podglądu** (tak samo jak przy wyświetlaniu),
- NIE potwierdzono ręcznie fizycznego okna/myszy (brak dostępu).

### Test użytkownika do wykonania na realnym ekranie
1. Wczytaj `GX010114/115/116` + FIT.
2. Poczekaj na zakończenie Wczytywania.
3. Dodaj mapę (przycisk „Mapa" w pasku strumieni).
4. Potwierdź, że mapa jest widoczna (Level-1 overview natychmiast).
5. Przełącz `Standard → Satellite` (właściwość map_style).
6. Potwierdź, że obraz faktycznie się zmienił (bez przesuwania timeline/resize).
7. Przesuń timeline — potwierdź, że mapa/marker odpowiadają aktualnej pozycji.

---

## 12. Regresja

- Pełna regresja `tests/` (bez znanych, wcześniej istniejących plików): **1044 passed / 17 skipped / 2 failed**.
- Oba błędy są **wcześniej istniejące** (rodzina chart-prefix, potwierdzona na czystym HEAD):
  - `test_amd_native_etap5b::test_current_layout_uses_only_four_dynamic_fit_fields`
  - `test_etap5b2_chart_precompute_regression::test_chart_precompute_full_history_parity`
  - (niezwiązane z mapą; dotyczą `fit_cadence_text` vs `fit_fractional_cadence_text`)
- Szeroka regresja map/GUI/FIT/render/multifile: **225 passed**.
- Finalny renderer (frame_renderer / AMD / NVENC / AMF / QSV) **niezmieniony** — ETAP 4B odroczony.

---

## Podsumowanie zmian produkcyjnych

| Plik | Zmiana |
|---|---|
| `src/indicators/frame_data.py` | normalizacja tz przed `elapsed_seconds` (naprawa TypeError blokującego cały overlay) |
| `src/telemetry_imu.py` | normalizacja tz w `interpolate_roll` (spójnie z resztą) |
| `src/map_renderer.py` | dodano brakującą `viewport_tiles_for` (naprawa ImportError w `static_map`) |
| `src/gui/qt/_mixins/project_mixin.py` | ASCII-safe `->` w logu provider switch (naprawa UnicodeEncodeError cp1250) |
| `tests/test_map_preload_etap1b_runtime.py` | 2 testy lifecycle (placeholder→ready→mapa; standard A != satellite B) |

## Niezmienione (zachowane)
- Ścieżka NVIDIA (CUDA/NVDEC/NVENC) — zachowana statycznie; walidacja runtime niemożliwa na AMD.
- Finalny renderer i ETAP 4B — nietknięte.
- Cache/provider namespace, generation guard, placeholder/progress, async threading — z ETAPU 1, bez regresji.
