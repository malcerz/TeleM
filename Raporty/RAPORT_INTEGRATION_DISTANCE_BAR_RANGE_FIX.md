# TeleM — Integration — DISTANCE BAR range fix

## Zadanie

Naprawa semantyki bieżącego dystansu i zakresu `DISTANCE BAR` w
`C:\_DEV\TeleM-integration`, bez zmiany wyglądu, pozycji, fontów ani pipeline'u
AMD/Intel/NVIDIA. Zgodnie z zakresem: **bez commita i bez pushu**.

Dataset walidacyjny: `C:\_DEV\TeleM\Video\GX010115.MP4` oraz
`C:\_DEV\TeleM\Video\GX010114_116.fit`. Stary repozytorium było użyte wyłącznie
jako read-only źródło danych; nie zostało zmienione.

## Stan początkowy i root cause

Widoczny widget to `fit_distance_text` z `def_layout.json`. Przed poprawką:

- bieżąca wartość tekstowa była rozwiązywana jako pole FIT `distance` przez
  `prepare_overlay_frame_data()` / `resolve_value()` i pozostawała w metrach aż
  do normalizacji prezentacyjnej w `src/indicators/compositor.py`;
- zakres widgetu był ręcznym `min_val=0.0`, `max_val=11.0` z layoutu, ponieważ
  `auto_scale` było `false`;
- marker i tick/range labels były generowane z tego statycznego zakresu w
  `render_value_indicator()` → `_render_ruler()`;
- niezależnie istniejące `fit_data["track"]` pochodziło z GPS i było używane w
  części range/primary paths. `sync_fit_to_video()` buduje je przez sumowanie
  odcinków GPS. Nie było to to samo źródło co pole FIT `distance` używane przez
  `fit_distance_text`.

Dla FIT `GX010114_116.fit` pomiar potwierdził:

- FIT recorded `distance`: 4299 próbek, monotoniczne, `0.0 → 24231.54 m`;
- GPS-derived FIT `track`: `0.0 → 23926.395351529896 m`;
- problemowy punkt `2026-08-14 11:25:12`: `14299.07 m` = `14.29907 km`;
- stary layout: `0.0 … 11.0 km`, z etykietą środkową `5.5 km`.

Dlatego `14.3 km` przekraczało ręczne `11.0 km`; clamp markera ograniczał
pozycję do 100%, ale nie był przyczyną danych.

## Przyjęta prawda i jednostki

Wybrano FIT recorded `distance` jako canonical activity-global distance, jeśli
strumień ma co najmniej dwie próbki, wartości skończone i monotonicznie
nie maleją. GPS-derived `track` jest wyłącznie jawnym fallbackiem, gdy FIT
distance jest nieobecne lub niewiarygodne. Nie są mieszane ani sumowane dwa
źródła.

Wewnętrzna jednostka pozostaje jedna: **metry**. `distance_max_m()` wyznacza
maksimum z wybranego pełnego strumienia w metrach. Konwersja do kilometrów
odbywa się dopiero w compositorze: `max_distance_m / 1000.0`, a dla dynamicznego
FIT fielda istniejąca normalizacja wartości robi dokładnie `raw / 1000.0`.

`def_layout.json` ma teraz `fit_distance_text.auto_scale=true`; istniejące
`max_val=11` jest wartością ręczną/fallbackową i w trybie AUTO nie nadpisuje
pełnego telemetry range. Efektywny max pochodzi z tego samego strumienia, co
current value. Marker nadal używa istniejącego wzoru:

```text
(current_distance_km - min_km) / (max_distance_km - min_km)
```

z istniejącym zabezpieczeniem clamp 0..1.

## Implementacja

Dodano wspólny resolver w `src/telemetry_resolver.py`:

- `resolve_distance_samples()` wybiera FIT distance / GPS track fallback / GPMF
  / GPX zgodnie z konfiguracją źródła;
- `distance_max_m()` wyznacza zakres w metrach;
- aliasy `distance` zostały dodane do strict source resolvera.

Resolver jest używany przez:

- `src/indicators/frame_data.py` — bieżąca wartość oraz fallback range;
- `src/telemetry_precompute.py` — precomputed current/average-speed data;
- `src/ffmpeg/worker_cache.py` — worker range cache i FIT dynamic field;
- `src/ffmpeg/streaming.py` — export `_range_cache` oraz dynamic FIT resolver;
- `src/ffmpeg/frame_renderer.py` — legacy/live disk path;
- `src/gui/qt/_mixins/preview_mixin.py` oraz `src/gui/qt/tabs/render_tab.py` —
  preview/HUD prepare cache.

Nie zmieniano `src/indicators/bar.py`, geometrii, kolorów, fontów, grubości,
pozycji ani kodu backendów GPU.

## Wyniki realnego testu

| Punkt | current FIT distance | canonical max | marker fraction |
|---|---:|---:|---:|
| GX010115 start, 11:18:03 | 12.07652 km | 24.23154 km | 0.49837 |
| problem point, 11:25:12 | 14.29907 km | 24.23154 km | 0.59010 |
| GX010115 end, 11:27:54 | 15.01519 km | 24.23154 km | 0.61967 |
| activity end, 12:01:13 | 24.23154 km | 24.23154 km | 1.00000 |

Dla problem pointu efektywny plan AUTO to `major step=5.0 km`, 5 głównych
działów i 10 minor ticks per division. Efektywne range labels są wyliczane z
`0.0 … 24.23154 km` (prezentacyjnie `0.0`, `12.1`, `24.2`), a nie z `0.0 …
11.0 km`.

Sprawdzono wszystkie próbki FIT: żadna bieżąca wartość nie przekracza
canonical max.

## Preview ↔ render parity

Ten sam timestamp, layout i dane zostały przepuszczone przez wspólny
`compose_overlay()` oraz `render_preview()` na transparentnej bazie:

- `preview_render_same = true`;
- `diff_bbox = None` — exact pixel equality;
- wynikowy render bar został zapisany pomocniczo jako
  `scratch/distance_bar_after_real.png`.

Precomputed final path również zwrócił dla standardowego `dist_visual`:
`distance_m=14299.07`, `max_distance_m=24231.54`.

Przejście multi-file na granicy pierwszego/`GX010115` klipu zachowuje
activity-global clock: `global 1956.955 s → 11:18:03`, bez resetu dystansu do
zera. Wartość na początku `GX010115` wynosi `12.07652 km`.

## Testy

PASS:

- distance source/range tests: `4 passed`;
- `tests/test_etap8o_precomputed_telemetry.py` +
  `tests/test_etap8p_b_fast_builder.py`: `22 passed`;
- `tests/test_etap1_source_resolver.py`: włączone w grupie, łącznie `28 passed`;
- `python -m compileall` dla zmienionych modułów: PASS;
- real FIT current/max/start/middle/end + multi-file boundary: PASS;
- preview/render exact parity: PASS.

Szerszy zestaw barów miał 8 istniejących, poza zakresem porażek dotyczących
marker geometry (`pad_x`) oraz testów różnicowania tick-profile/minor-ticks.
Żaden z tych testów nie dotyczy wyboru źródła dystansu ani range fix; `bar.py`
nie był zmieniany. Nie naprawiano ich oportunistycznie.

Benchmark wydajności: **NOT RUN** — zadanie zmienia wyłącznie przygotowanie
danych/range i nie wymagało benchmarku render pipeline.

## Zmienione pliki w tym zadaniu

- `def_layout.json` — `fit_distance_text.auto_scale=true`;
- `src/telemetry_resolver.py` — canonical distance resolver/range;
- `src/indicators/frame_data.py`;
- `src/telemetry_precompute.py`;
- `src/ffmpeg/worker_cache.py`;
- `src/ffmpeg/streaming.py`;
- `src/ffmpeg/frame_renderer.py`;
- `src/gui/qt/_mixins/preview_mixin.py`;
- `src/gui/qt/tabs/render_tab.py`;
- `tests/test_distance_bar_scale_contract.py`.

Worktree zawiera również wcześniejsze, niezależne niezatwierdzone zmiany
użytkownika. Zostały zachowane; nie resetowano merge ani nie nadpisywano
plików referencyjnych.

## Diff stat

Pełny `git diff --stat` worktree (zawiera również wcześniejsze zmiany):

```text
22 files changed, 497 insertions(+), 148 deletions(-)
```

Ten etap dodał tylko zakresową zmianę DISTANCE BAR oraz jej testy; liczba above
obejmuje wcześniejszy dirty worktree.

## Verdict

**PASS — DISTANCE BAR RANGE/CURRENT SOURCE CONSISTENT**

Brak commita. Brak pushu.
