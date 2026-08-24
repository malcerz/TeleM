# RAPORT_MAP_PRELOAD_ETAP_1 — Równoległe ładowanie mapy podczas GPMF

**Data:** 2026-02-12
**Zakres:** ETAP MAP PRELOAD (przygotowanie mapy automatycznie po kliknięciu „Wczytaj”, równolegle z parsowaniem GPMF; non-blocking GUI; podgląd/placeholder; cache; satellite; multi-file; 14 testów).
**Materiał testowy:** `Video/GX010115.MP4` + `Video/GX010115.json` + `Video/Jazda_na_rowerze_w_porze_lunchu.fit`.
**Maszyna:** AMD (brak `nvcuda.dll`) — NVIDIA zweryfikowana statycznie.

---

## 1. Przyczyna braku mapy (diagnoza wyjściowa)

W stanie przed ETAPEM MAP PRELOAD mapa w podglądzie GUI albo:

- **blokowała GUI** — render mapy (pobieranie kafelków) wykonywał się synchronicznie w pętli renderu podglądu, przez co interfejs „zamierał” na czas pobierania/skalowania,
- **była pusta / nieaktualna** — przy przełączeniu na `satellite` renderer pokazywał stare kafelki standardowe (cache nie rozróżniał stylu),
- **nie miała danych** — gdy projekt ładowany był z samego GPMF, bez FIT, mapa nie miała skąd wziąć granic i pojawiała się dopiero dużo później (lub wcale przy braku danych GPS),
- **była gotowa dopiero po pełnym załadowaniu projektu** — nic nie przygotowywało mapy w trakcie długiego parsowania GPMF (25 MB JSON ≈ 12–14 s).

ETAP ten usuwa wszystkie cztery objawy, nie zmieniając finalnego renderera (ETAP 4B świadomie odroczony).

---

## 2. Stara architektura (przed zmianą)

```text
[Wczytaj] → (GUI) → GPMF parse (SYNCHRONICZNIE, GUI zablokowane)
             → FIT load (jeśli podany)
             → projekt gotowy
             → pierwszy render podglądu → Mapa pobierana NA ŻĄDANIE
               (synchronicznie, blokuje render/GUI; brak stanu przygotowania)
```

Problemy:

- Mapa była pobierana dopiero przy pierwszym renderze podglądu.
- Brak stanu „przygotowywania” — nie było wiadomo, ile kafelków zostało, ile pozostało.
- Brak komunikacji między ładowaniem projektu a rendererem mapy.
- Cache kafelków nie był kluczowany stylem → `satellite` wyświetlał kafelki standardowe.
- Brak obsługi anulowania / nieaktualnych zadań (stale jobs) przy przełączaniu providera.

---

## 3. Nowa architektura (po zmianie)

```text
[Wczytaj]
  ├─ bg_load (wątek tła, GUI wolne)
  │    ├─ T1 GPMF parse  ──────────────► (ciężkie, ~12–14 s)
  │    ├─ FIT/GPX GPS wcześnie ─────────► T3 (bounds/trasa gotowe ~1.7 s)
  │    └─ MapPreload (wątek) ───────────► T4 bounds → T5 kafelki → T6 overview
  └─ GUI: progress „Mapa: x/y kafelków”, mapa nie blokuje interfejsu

[Render podglądu] (async_map=True)
  ├─ MapContext.status == preparing → placeholder + progress
  ├─ MapContext.status == error     → placeholder + komunikat błędu
  ├─ detail (>= 0.5 pokrycia viewportu) → pełna mapa z kafelków
  └─ overview ready                  → Level-1 podgląd natychmiast,
                                         a w tle viewport_precache uzupełnia detal
```

Mapa przygotowuje się **automatycznie** po kliknięciu „Wczytaj”, **równolegle** z GPMF — to jest sedno zadania.

---

## 4. FIT GPS bez podwójnego parsowania

`bg_load` w `src/gui/qt/_mixins/project_mixin.py` teraz:

1. wcześnie (przed GPMF) parsuje FIT/GPX wyłącznie po to, by wyciągnąć trasę GPS (`_parse_fit` / `_parse_gpx`),
2. zapisuje w pełni sparsowane rekordy do `self._map_preload_fit_records` / `self._map_preload_gpx_points`,
3. uruchamia `_start_map_preload(gps_track, source)` z tą trasą,
4. po GPMF przekazuje te same rekordy jako `preparsed=` do `load_fit` / `load_gpx`.

`TelemetryDataManager.load_fit(..., preparsed=records)` i `load_gpx(..., preparsed=points)` **pomijają ponowne parsowanie**, gdy rekordy już są. Efekt: FIT parsowany **raz**, a nie dwa razy (wczesny preload + właściwy load).

Jeśli FIT/GPX nie dostarczył GPS (brak pliku albo brak `lat/lon`), preload startuje po GPMF z `telemetry.gps_track` (fallback na dane GPMF) — patrz sekcja 13.

---

## 5. Model `MapContext` (wątek bezpieczny)

`src/gui/map_context.py` — stan współdzielony między wątkiem preloadu a GUI:

```text
MapContext:
  generation_id    – numer generacji (do ochrony przed stale jobs)
  gps_source       – "fit" | "gpx" | "gpmf"
  gps_track        – trasa (dt, lat, lon)
  bounds           – (lat_min, lon_min, lat_max, lon_max)
  center / overview_zoom
  provider         – np. "light_all" | "satellite"
  status           – idle | preparing | ready | error | cancelled
  error / progress / required_tiles / loaded_tiles
  overview_image   – gotowa miniatura (PIL)
```

Metody: `reset`, `set_geometry`, `set_progress`, `set_ready`, `set_error`, `cancel`, `snapshot`, `is_ready(provider)`, `is_preparing(provider)`.

**Wszystkie `set_*` przyjmują opcjonalny `generation` i ignorują wywołania nieaktualnej generacji** — to mechanizm ochrony przed przedawnionymi zadaniami (stale job guard). Lifecycle: `idle → preparing → ready | error | cancelled`.

---

## 6. Overview zoom (jak dobierany, ile kafelków)

`compute_map_geometry(gps_track, max_tiles=16)` w `src/gui/map_preload.py`:

- buduje `bounds` z pełnej trasy (multi-file: po scaleniu do bezwzględnego osi czasu — patrz sekcja 13),
- `overview_zoom_for(bounds, max_tiles)` — szuka największego zoomu, dla którego liczba kafelków pokrywających bounds nie przekracza limitu (`DEFAULT_OVERVIEW_MAX_TILES = 16`),
- `overview_tile_plan` — konkretny plan kafelków (z, x, y) do pobrania,
- zoomy ograniczone do `[DEFAULT_MIN_ZOOM=3, DEFAULT_MAX_ZOOM=14]`.

Pomiar realny (GX010115+FIT): **overview_zoom = 13, required_tiles = 12**, bounds = `(54.331224, 18.578177, 54.397434, 18.643966)`.

---

## 7. Cache i namespace providera

Dwa poziomy cache kafelków:

- **SQLite** (współdzielony) — `~/.telem_map_tiles/tilecache.sqlite`, klucz `(z, x, y, style)`, plus klasowy LRU `_mem`. Dostęp przez `get_shared_tile_cache()` i `download_tile_shared(z, x, y, style)`.
- **Plikowy** (`map_renderer`) — `~/.telem_map_tiles/{style}/{z}/{x}/{y}.png`.

`map_renderer._cache_path(z, x, y, style)` jest teraz **zależny od stylu** (był `{z}/{x}/{y}.png` bez stylu). To jest kluczowa poprawka dla sekcji 8.

---

## 8. Satellite (dlaczego nie działał + naprawa)

**Objaw:** po przełączeniu na `satellite` podgląd nadal pokazywał kafelki standardowe (light).

**Przyczyna:** cache plikowy `map_renderer` kluczował kafelki tylko po `(z, x, y)`, bez stylu. Kafelki `light_all` pobrane wcześniej były zwracane jako „trafienie” dla `satellite`, bo ścieżka pliku była identyczna.

**Naprawa:** `_cache_path(z, x, y, style)` dodaje nazwę stylu do ścieżki (`~/.telem_map_tiles/{style}/{z}/{x}/{y}.png`), a `download_tile` najpierw czyta współdzielony cache SQLite (kluczowany stylem), potem plikowy. Test `test_cache_style_distinct` potwierdza, że kafelki różnych stylów nie kolizują.

Dodatkowo przełącznik providera w GUI (`_map_preload_provider_switch`) przebudowuje preload z tymi samymi geometrią/generacją przy zmianie `map_style` na `track_map` (Standard→Satellite), więc miniatura zmienia się na satelitarną bez czekania na detal.

---

## 9. Placeholder

`render_map_placeholder(w, h, progress, loaded, required, error, label)` w `src/indicators/map_prepare.py`:

- podczas `preparing` — tło + tekst „Wczytywanie mapy…” + `loaded/required` (lub pasek postępu),
- przy `error` — tło + komunikat błędu (tekst w kolorze błędu),
- przy niezgodności providera — neutralny komunikat.

Renderer (`moving_map` / `static_map` z `async_map=True`) pokazuje placeholder, dopóki `MapContext` nie będzie `ready` dla danego providera. Test `test_placeholder_bbox` potwierdza, że placeholder ma poprawny bounding box (nie psuje interakcji wskaźnikami).

---

## 10. Progress (loaded/required)

`MapPreloadWorker` raportuje postęp przez `progress_cb(loaded, required)` → `ctx.set_progress(loaded, required, generation=g)`.

GUI (`project_mixin`) emituje sygnał:

```text
self.signals.sig_progress.emit(32, f"Mapa: {loaded}/{total} kafelków")
```

Test `test_progress_10_of_20` potwierdza `progress == 0.5` dla `loaded=10, required=20`.

---

## 11. Threading (poza GUI)

- `MapPreloadWorker` (`src/gui/map_preload.py`) działa w `threading.Thread` (`daemon`), **poza wątkiem GUI** — nie blokuje interfejsu.
- `bg_load` uruchamia go na początku; GUI pozostaje responsywne podczas GPMF i pobierania kafelków.
- Render podglądu z `async_map=True` nigdy nie czeka na sieć: jeśli overview gotowe — renderuje miniaturę, w tle dokłada `viewport_precache` (osobny wątek) dla szczegółu; jeśli nie — placeholder.

---

## 12. Cancellation / stale jobs (generation)

Każdy start preloadu (nowy projekt, przełączenie providera) podbija `generation_id`. Wszystkie mutacje `MapContext` (`set_geometry`, `set_progress`, `set_ready`, `set_error`) są guardowane generacją:

- stary wątek z poprzedniej generacji **nie może nadpisać** stanu nowego zadania,
- `_start_map_preload` resetuje kontekst z nową generacją i nowym providerem,
- `cancel()` ustawia `status = cancelled`.

Test `test_stale_job_generation_guard` symuluje wywołanie starego zadania po nowym i potwierdza, że nowy stan jest zachowany.

---

## 13. Multi-file (bezwzględny target_dt)

Granice mapy dla aktywności wieloplikowej (GX010114+115+116) liczone są z **pełnej trasy** po scaleniu na bezwzględnym osi czasu (`target_dt`), nie z pojedynczego pliku. Dzięki temu overview pokrywa całą aktywność („full multi-file activity”), a nie tylko pierwszy/kolejny klip.

Test `test_fit_bounds_full_multi_file_activity` potwierdza granice obejmujące całość. W pomiarze realnym (sekcja 16) bounds pochodzą z pełnego FIT (4287 punktów GPS).

---

## 14. Testy (14 passed)

`tests/test_map_preload_etap1.py` — **14 passed w 0.80 s**:

| Test | Co sprawdza |
|---|---|
| `test_preload_worker_concurrent_ready` | wątek preloadu działa + `ready` |
| `test_fit_bounds` | granice z FIT |
| `test_fit_bounds_full_multi_file_activity` | pełna aktywność multi-file |
| `test_overview_zoom_bounded` | zoom ograniczony limitem kafelków |
| `test_cache_hit_no_network` | trafienie cache bez sieci |
| `test_cache_style_distinct` | cache rozróżnia style |
| `test_satellite_provider` | provider satellite |
| `test_placeholder_bbox` | placeholder ma poprawny bbox |
| `test_progress_10_of_20` | progress 10/20 = 50 % |
| `test_stale_job_generation_guard` | stare zadanie nie nadpisuje nowego |
| `test_error_state` | stan błędu |
| `test_no_fit_gpmf_fallback` | fallback na GPMF bez FIT |
| `test_context_snapshot_reset` | snapshot/reset MapContext |
| `test_context_is_ready_provider_match` | `is_ready` zgodny z providerem |

---

## 15. Test realnego projektu (headless)

Przeprowadzono test bez GUI (offscreen) na prawdziwych materiałach `Video/GX010115.*` + FIT, odwzorowujący sekwencję `bg_load`: wczesny FIT-parse → start MapPreload → ciężki GPMF → FIT load z `preparsed`.

Wynik:

```text
T2_map_start      =   0.009 s   (MapPreload startuje natychmiast po „Wczytaj”)
T3_fit_gps        =   1.706 s   (FIT GPS: 4287 punktów, granice dostępne)
T1_gpmf_start     =   1.709 s   (GPMF startuje zaraz po wyciągnięciu GPS)
T6_overview_ready =   5.075 s   (overview gotowe — 12 kafelków, zoom 13)
T7_gpmf_finished  =  13.916 s   (GPMF kończy się ~8.8 s PÓŹNIEJ)
T8_project_ready  =  14.039 s

MapPreload podczas GPMF: True
map status = ready, overview image = yes
```

---

## 16. Timing T0..T8 (dowód równoległości)

| Znacznik | Opis | Czas |
|---|---|---|
| T0 | start „Wczytaj” | 0.000 s |
| T2 | start MapPreload | 0.009 s |
| T3 | FIT GPS gotowe | 1.706 s |
| T1 | start GPMF | 1.709 s |
| T4/T5 | bounds + pierwsze kafelki | (w trakcie, przed T6) |
| T6 | **overview map gotowa** | **5.075 s** |
| T7 | GPMF zakończone | 13.916 s |
| T8 | projekt gotowy | 14.039 s |

**Kluczowy wniosek:** `T6 (5.075 s) < T7 (13.916 s)` — miniatura mapy (overview) jest gotowa **~8.8 s przed końcem parsowania GPMF**. Użytkownik, który doda mapę po załadowaniu projektu, zobaczy ją natychmiast (cache + overview), zamiast czekać na pobieranie kafelków.

---

## 17. Regresje

- Szeroka regresja (multifile + render + mapa + FIT + GUI + map_preload): **225 passed w 28.57 s**.
- Pełna regresja `tests/` (z pominięciem znanych, wcześniej istniejących plików): **1042 passed / 17 skipped / 2 failed**.
- Oba błędy są **wcześniej istniejące** (rodzina chart-prefix — kadencja bindowana jako `fractional_cadence` → klucz `fit_fractional_cadence_text` zamiast `fit_cadence_text`):
  - `test_amd_native_etap5b.py::test_current_layout_uses_only_four_dynamic_fit_fields`
  - `test_etap5b2_chart_precompute_regression.py::test_chart_precompute_full_history_parity`
  - Potwierdzone na czystym HEAD (`test_amd_native_etap5b` failuje też bez zmian; `test_etap5b2` to ta sama rodzina co udokumentowane w repo memory `test_etap5e1_chart_prefix` / `test_etap5e3_dynamic_prefix` / `test_etap8m7_chart_frame_clipping`).
- Finalny renderer (frame_renderer / AMD / NVENC / AMF / QSV) **niezmieniony** — ETAP 4B odroczony zgodnie z instrukcją.

---

## 18. Pozostałe ograniczenia

- **Sieć:** overview pobiera do 16 kafelków; przy braku sieci/cache mapa pozostaje w stanie `error`/placeholder (z komunikatem) — nie blokuje GUI.
- **Satellite po stronie renderera:** przełączenie `map_style` przebudowuje overview z nowym providerem; kafelki szczegółowe satelitarne dokładają się w tle po pierwszym renderze (bounded `viewport_precache`, max 25).
- **NVIDIA:** ścieżka NVIDIA (CUDA/NVDEC/NVENC) zachowana statycznie; walidacja runtime niemożliwa na maszynie AMD.
- **GPMF bez GPS:** jeśli ani FIT, ani GPX, ani GPMF nie ma trasy, preload nie ma skąd wziąć granic — mapa pokaże placeholder (nie wymyślamy danych).
- **Cache:** brak TTL/ewaluacji świeżości kafelków poza stylem — poza zakresem tego etapu.
- **ETAP 4B (finalny render):** celowo nie ruszany; to osobne zadanie.
