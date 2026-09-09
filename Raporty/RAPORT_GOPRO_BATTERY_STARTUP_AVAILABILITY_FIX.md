# GoPro Battery startup availability — acceptance

## Zakres

Naprawiono wyłącznie startup dynamicznego FIT `fit_gopro_battery_text`.
Nie zmieniano parsera GPMF, anchoru czasu, matematyki Lean ani backendów.
Wszystkie artefakty runtime zapisano na `D:`.

## Dowód BEFORE i root cause

Materiał: `D:/GoPro/2026-09-02/GX010246.MP4` +
`D:/GoPro/2026-09-02/Poranna_jazda_na_rowerze.fit`.

Pierwsza rzeczywista próbka `gopro_battery`:

* `2026-09-02T04:22:35` = `53.0`
* canonical video start: `2026-09-02T04:22:38.224128Z`
* sample − video start: **−3.224128 s**

Zatem frame 0 nie jest przypadkiem `before-first-sample` i powinien mieć wartość.
W realnym GUI BEFORE pierwszy callback HUD powstał podczas asynchronicznego
ładowania FIT (target `04:22:37.224128`, global `-1.0`):
`frame_data=None`, compositor `None`, visible `--`. Następny callback po
zakończeniu ładowania miał już `53.0`. Klasyfikacja: **D — availability delayed
by startup race (plan/data late)**, nie błąd osi czasu ani parsera.

BEFORE trace: `D:/TeleM_live_acceptance/gopro_battery_startup/before/trace.json`
(47 przyjętych callbacków; pierwszy callback `None` jest uchwycony jawnie).

## Implementacja

1. `TelemetryDataManager.load_fit` rozgrzewa plany dla obu niezależnych pól:
   `garmin_battery_percent` i `gopro_battery`.
2. `worker_cache.init_worker` oraz `_resolve_cache_value` stosują ten sam plan i
   coverage contract dla GoPro oraz Garmin.
3. `presentation_value` wybiera monotoniczny plan także dla canonical
   `gopro_battery` (bez wyjątku filename i bez GPS lock).
4. Podczas jawnego ładowania FIT ustawiany jest startup guard
   `_preview_telemetry_loading`; `_on_video_frame` i `_render_preview` nie
   publikują pustego HUD. Guard jest zerowany przed pierwszym post-load refresh,
   a także w ścieżce błędu.

## AFTER — 150-frame real GUI trace

Normalny widoczny runtime `QApplication → AppController → MainWindow → MPV
(d3d11va) → Preview`:

`D:/TeleM_live_acceptance/gopro_battery_startup/after/trace.json`

151 wpisów (150 klatek + `finished`), `None` count = **0**.

| frame | global time | target value | formatted |
|---:|---:|---:|---:|
| 0 | 0.000 s | 53.000000 | 53% |
| 1 | 0.000 s | 53.000000 | 53% |
| 10 | 2.469 s | 52.650212 | 52.65% |
| 50 | 20.020 s | 52.485561 | 52.49% |
| 100 | 42.041 s | 52.281308 | 52.28% |
| 149 | 64.965 s | 52.073000 | 52.07% |

Wartość jest liczbowa od pierwszej przyjętej klatki i zmienia się pomiędzy
surowymi próbkami. Widoczny HUD capture: `quick_after/frame_0002_hud.png`;
na ekranie odczyt `BAT: 52.68%`.

## Warm-up i seek

Plan ma 2034 próbki / 21 segmentów. Pomiar budowy coverage-aware planu na
pełnej serii: **0.618 ms** (`04:22:38.224128` … `04:56:44.902`).
Seek do dokładnego początku w realnym GUI zwrócił natychmiast `53.0` (bez
play/pause i bez ręcznego refresh).

## Final

Wykonano krótki AMD final smoke na 30 klatkach (pierwszy fragment), wyłącznie
na `D:`:

`D:/TeleM_live_acceptance/gopro_battery_startup/final_smoke_30f.mp4`

Output istnieje, mux zakończony poprawnie, 30 klatek, wejście AMD native / AMF,
`Render FPS 42.592`, `Effective FPS 17.423`. Worker używa tego samego
`gopro_battery` resolver contract; pierwszy target rozwiązuje się do `53.0`.

## Garmin regression

Realny GUI regression (`tests/manual_presentation_gui.py after`) zakończony
widocznym HUD i wartościami pośrednimi:
`95.87%`, `95.86%`, seek `95.72%`, `95.48%`, `95.24%`, `95.10%`, final
`95.00%`. Artefakty: `D:/TeleM_live_acceptance/presentation_architecture/after/`.

## Testy

* `python -m pytest -q tests/test_gopro_battery_startup.py tests/test_display_precision_interpolation.py tests/test_presentation_architecture.py tests/test_gpmf_stream_first_sample_availability.py`
  → **49 passed**.
* Real GUI GoPro startup trace → **151 callbacks, 0 None**.
* Real GUI Garmin regression → **PASS**.
* Short AMD final 30f → **PASS**.

Wybrane starsze testy z `test_etap10k_fit_gui.py` wskazują brak lokalnego
fixture `Video/Jazda_na_rowerze_w_porze_lunchu.fit`; nie jest to regresja tej
zmiany i nie używano tego nieautorytatywnego parowania.

## Zmienione pliki

* `src/telemetry_resolver.py`
* `src/ffmpeg/worker_cache.py`
* `src/gui/telemetry_manager.py`
* `src/gui/qt/_mixins/project_mixin.py`
* `src/gui/qt/_mixins/preview_mixin.py`
* `tests/test_gopro_battery_startup.py`

Harnesse `tests/manual_gopro_battery_startup.py` i
`tests/manual_gopro_battery_final_smoke.py` są wyłącznie lokalnymi skryptami
audytowymi; nie zmieniają produkcyjnych presetów.

## Final gate

* FIRST SAMPLE VALUE AT FRAME 0: **PASS**
* NO STARTUP `--` VISUAL HOLE: **PASS**
* NO FUTURE SAMPLE BACKFILL: **PASS**
* PLAN WARMED BEFORE FIRST POST-LOAD PREVIEW: **PASS**
* EXACT START SEEK: **PASS**
* SHORT FINAL FIRST FRAGMENT: **PASS**
* GARMIN REGRESSION: **PASS**
* GPMF / Lean / backend isolation: **PASS** (unchanged)

**STATUS = READY — GoPro Battery startup availability fixed.**

Nie wykonano commit ani push.
