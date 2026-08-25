# TeleM — ETAP 8D: derived Slope / Grade

Data: 2026-08-21.

## Zakres

Dodano canonical derived field `slope`, wyrażany w procentach:

```text
slope[%] = 100 * (delta_altitude_m / delta_distance_m)
```

To etap data-only. Nie dodano wizualnego wskaźnika Slope, `fit_slope_text`, `gpmf_slope_text`, presetów ani zmian w `bar.py`, `gauge.py`, Compass, mapie, Lean lub Track-Up.

## Implementacja

- `src/telemetry_slope.py` zawiera source-local helper, causalny distance-window, reset/gap handling, hold ostatniej poprawnej wartości, odrzucanie wartości niefinitywnych i sanity rejection bez clampowania do `±20%`.
- Publiczne binding jest wyłącznie `slope`.
- GPMF: `GPSAltitude` + GPMF-derived cumulative `track`.
- FIT: własne `alt` z `enhanced_altitude` + własny FIT-derived `track`, z fallbackiem do FIT `distance`.
- GPX: istniejące `gpx_alt_samples` + `gpx_track_samples`; brak rozbudowy parsera.
- Resolver, worker cache i precompute rozpoznają `slope` tylko dla jawnego konsumenta layoutu. Renderer nie liczy slope.
- `slope` jest traktowane jako pole kanoniczne/wbudowane, więc rejestr FIT nie tworzy automatycznie `fit_slope_text`.

## Parametry produkcyjne

Wybrano:

| Parametr | Wartość |
|---|---:|
| distance window | `20 m` |
| maximum lookback | `10 s` |
| causal smoothing | `2 s` |
| sanity rejection | `abs(slope) > 100%` |

Okno 20 m jest kompromisem między szumem GPMF a opóźnieniem HUD. Lookback 10 s daje pokrycie także przy wolniejszej jeździe, ale nie pozwala użyć starego punktu po długiej przerwie. Smoothing 2 s jest causalny i wykonywany w derived streamie, nie w rendererze.

## Diagnostyka danych

Użyte materiały:

- `Video/GX030120.json`: 1802 próbek GPMF, 180,1 s, 10 Hz;
- `Video/Poranna_jazda_na_rowerze.fit`: 1672 rekordy; dopasowany FIT referencyjny;
- nie użyto `Popoludniowa_jazda_na_rowerze_solar_battery.fit` jako ground truth;
- w repozytorium nadal brak rzeczywistego GPX.

Poniżej sweep przy smoothing `2 s`; wartości to `sigma / P95(abs(slope))` w punktach procentowych. Wszystkie kombinacje `10/15/20/30 m`, `5/10/20 s` oraz smoothing `0/1/2/3 s` zostały policzone diagnostycznie.

| window | GPMF l=5 s | GPMF l=10 s | GPMF l=20 s | FIT track l=5 s | FIT track l=10 s | FIT track l=20 s |
|---:|---:|---:|---:|---:|---:|---:|
| 10 m | 3,024 / 6,155 | 10,268 / 25,153 | 8,954 / 24,881 | 3,102 / 6,116 | 2,940 / 5,442 | 2,938 / 5,442 |
| 15 m | 3,344 / 6,160 | 6,357 / 14,968 | 9,459 / 26,664 | 2,895 / 6,318 | 2,892 / 5,497 | 2,825 / 5,497 |
| 20 m | 2,728 / 6,104 | 3,197 / 6,104 | 8,477 / 21,765 | 2,563 / 6,261 | 2,852 / 5,978 | 2,758 / 5,489 |
| 30 m | 4,011 / 7,470 | 2,579 / 5,620 | 6,794 / 16,832 | 2,494 / 5,443 | 2,757 / 5,908 | 2,747 / 6,021 |

Przy wybranych parametrach valid coverage wyniosło około `98,6%` GPMF i `99,6%` dopasowanego FIT track. Dla FIT `distance` coverage wyniosło około `98,4%`, ale zgodnie z audytem 8A preferowany jest source-local derived `track` z GPS, gdy jest dostępny.

## Semantyka braków i resetów

- przed pierwszym pełnym oknem wynik to `None`;
- zatrzymanie lub zbyt mały nowy dystans utrzymuje ostatnią poprawną wartość;
- gap dłuższy niż 10 s czyści bazę i wymaga ponownego zbudowania okna;
- spadek cumulative distance czyści bazę;
- `NaN`, `Inf`, zerowy dystans i odrzucone skoki nie są emitowane;
- wartość nie jest clampowana do `±20%`; sanity threshold jest ustawiony wyżej na `±100%`.

Resolver slope używa causalnego STEP lookupu: klatka może zobaczyć wyłącznie ostatnią próbkę `slope` o czasie `<= target_dt`.

## Zmienione pliki

- `src/telemetry_slope.py`
- `src/telemetry_resolver.py`
- `src/gui/telemetry_manager.py`
- `src/gui/qt/_mixins/render_mixin.py`
- `src/ffmpeg/worker_cache.py`
- `src/indicators/frame_data.py`
- `src/telemetry_precompute.py`
- `tests/test_telemetry_slope.py`

## Zachowane

Nie zmieniano parserów/semantyki synchronizacji FIT/GPMF/GPX, rendererów wskaźników, Compass, mapy, Lean, presetów, decoderów, encoderów ani logiki AMD/NVIDIA. CPU reference, AMD split/map/chart/gauge oraz istniejący algorytm `heading` pozostają bez zmian.

## Testy

- slope helper i binding/cache: **6 passed**;
- slope + heading + source resolver + GPMF cache + precompute + Compass: **45 passed**;
- `compileall` zmienionych modułów: OK;
- diagnostyka rzeczywistych danych GPMF/FIT: OK;
- `git diff --check` dla zakresu ETAPU 8D: OK.

Nie uruchamiano jeszcze pełnego repozytoryjnego suite ani runtime exportu AMD dla tego etapu; zmiana nie wprowadza nowej ścieżki rasteryzacji. GPX nie był dostępny do runtime walidacji.

**NVIDIA path preserved statically; runtime validation was not possible on this AMD machine.**

## Ryzyka

- GPMF GPS altitude pozostaje bardziej zaszumiony niż FIT `enhanced_altitude`; 20 m + 2 s ogranicza szum, ale nie zastępuje walidacji terenowej.
- FIT slope może być `None` na początku, gdy derived GPS track nie ma jeszcze próbek; później odbudowuje się causalnie.
- GPX binding jest przygotowany, lecz brak pliku testowego uniemożliwia pomiar rzeczywistego przebiegu.
