# TeleM — korekta osi czasu chartów: fixed timeline + progressive reveal

Data: 2026-08-20.

## Zakres

Zmieniono wyłącznie wspólną logikę chartów oraz wykresy
`fit_cadence_text` i `fit_heart_rate_text`. Nie zmieniano telemetrii, FIT
discovery, preview, atlasu, Direct-Region, workerów, SHM ani FFmpeg/NVIDIA.

## Implementacja

Usunięto Model A, w którym widoczna historia była ponownie skalowana z
`activity_start -> current_time` do całej szerokości chartu.

`_build_chart_bg()` oblicza i cache'uje punkty X raz względem stałej domeny
`chart_start_dt -> chart_end_dt`. Per frame prefix renderer wykonuje tylko:

```text
bisect_right(timestamps, current_time)
-> full_points[:visible_count]
-> rysowanie już zdefiniowanych segmentów
-> marker na X odpowiadającym current_time
```

Nie ma już per-frame `x_scale = plot_width / (current-start)` ani przesuwania
markera na prawą krawędź. Future samples nie są rysowane. Average kończy się
na ostatniej widocznej próbce, dlatego prawa część chartu pozostaje pusta także
dla tej dynamicznej warstwy.

## Testy semantyki

Dodano `tests/test_chart_fixed_timeline_reveal.py` dla cadence i HR.

- checkpointy 10%, 25%, 50%, 75%, 100%: marker X jest równy pozycji procentowej
  stałej osi;
- próbka z timestampem 25% ma identyczne X na checkpointach 25–100%;
- po aktualnej próbce nie ma pikseli serii w przyszłej części osi;
- długa luka FIT zachowuje proporcjonalną pustą szerokość i nie dostaje linii.

Zachowano testy `cadence=0`, `None != 0`, `None` jako podział segmentu oraz
podział na długiej luce. Cadence i HR nadal korzystają z własnych timestampów.

Wynik:

```text
focused chart tests: 20 passed
chart/NVIDIA/ETAP5 suite: 173 passed
```

## Koszt po zmianie

Mikrobenchmark: 2000 realnych renderów na `GX030120.MP4` +
`Popoludniowa_jazda_na_rowerze_solar_battery.fit`, stała domena osi,
cache warstw dynamicznych aktywny.

| Chart | avg ms | median ms | p95 ms |
|---|---:|---:|---:|
| cadence | 0.683 | 0.705 | 0.921 |
| heart rate | 0.527 | 0.494 | 0.720 |

Artefakt pomiaru: `scratch/chart_fixed_timeline_benchmark.json`.

## Odpowiedzi końcowe

1. Dynamiczne skalowanie `start->current` zostało usunięte: **tak**.
2. X jest liczone względem `start->end`: **tak**.
3. Prawa część pozostaje pusta do czasu odkrycia danych: **tak**.
4. Długa luka zachowuje proporcjonalną szerokość i nie jest łączona: **tak**.
5. `cadence=0`, `None` oraz gap splitting pozostają poprawne: **tak**.
6. Koszt po zmianie: cadence **0.705 ms mediany**, HR **0.494 ms mediany**.

## Zmienione pliki

- `src/indicators/chart.py`
- `src/indicators/chart_utils.py`
- `tests/test_etap5e1_chart_prefix.py`
- `tests/test_etap5e3_dynamic_prefix.py`
- `tests/test_chart_fixed_timeline_reveal.py`
- `scratch/benchmark_chart_fixed_timeline.py`

Etap zakończony. Dalszych zmian nie wykonano.

