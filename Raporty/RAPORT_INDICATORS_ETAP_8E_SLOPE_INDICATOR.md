# TeleM — ETAP 8E: pionowy wskaźnik Slope / Grade

Data: 2026-08-21.

## 1. Bramka ETAP 8D

Przed zmianą renderera uruchomiono:

```text
python -m pytest -q --ignore=tests/test_fit_registration.py
610 passed, 17 skipped, 0 failed
```

Parametry produkcyjne ETAPU 8D: `distance_window=20 m`, `max_lookback=10 s`,
`smoothing=2 s`, `sanity=100%`.

Rzeczywiste wartości dla `Video/GX030120.json` i
`Video/Poranna_jazda_na_rowerze.fit`:

| Czas | GPMF slope [%] | FIT slope [%] |
|---:|---:|---:|
| 20 s | `+2.9114573591` | `None` |
| 60 s | `-3.5084010246` | `+0.5949672022` |
| 120 s | `+2.1771752420` | `+4.4076089630` |

CPU i precomputed zwróciły te same wartości na wszystkich trzech chwilach;
delta wyniósł `0.0` dla wartości liczbowych, a `None` pozostał `None`.

## 2. Architektura renderera

Wykorzystano istniejącą rodzinę `src/indicators/bar.py` i dodano lokalny styl
`bar_style="slope"`. Nie powstał nowy framework ani drugi ogólny renderer barów.
Zwykłe `ruler` i `segments` zachowały dotychczasową ścieżkę.

Wariant pionowy jest lokalnym rastrem: pionowy track, ticki, etykiety, zero,
marker i tekst wartości. Obrót działa na całym lokalnym rastrze, a nie na
poziomym tekście osobno.

Renderer otrzymuje gotowe `value`; nie zna altitude, distance, FIT, GPMF, GPS,
okna 20 m, lookbacku ani smoothingu. `src/telemetry_slope.py` nie był zmieniany.

## 3. Binding

Nowy widget używa:

```text
field=slope
form=bar
bar_style=slope
```

Źródło pozostaje konfigurowalne przez istniejącą infrastrukturę `GPMF/FIT/GPX`.
Dodano test jawnego bindingu zarówno dla FIT, jak i GPMF; resolver nie przełącza
się samoczynnie na inne źródło.

## 4. Semantyka

Dodatni slope oznacza podjazd i jest wyświetlany z jawnym znakiem `+`.
Ujemny oznacza zjazd. Zero ma wyróżniony tick. Renderer nie clampuje wartości
kanonicznej.

## 5. Range

Domyślnie użyto zakresu `-20% ... +20%`. Konfiguracja jest edytowalna przez
`min_val` i `max_val`.

## 6. Ticki

Domyślnie:

```text
major_tick=5%
minor_tick=1%
```

Etykiety główne to `+20, +15, +10, +5, 0, -5, -10, -15, -20`.
`major_tick`, `minor_tick`, kolory i długości ticków są konfigurowalne.

## 7. Value formatter

Formatter jest lokalny dla Slope i nie zmienia innych wskaźników:

```text
+6.4%
-3.1%
0.0%
```

## 8. None

Przy `slope=None` skala pozostaje widoczna, tekst to `--%`, a marker jest
ukryty. `None` nie jest traktowane jako fałszywe `0%`.

## 9. Overflow

Dla wartości `+26%` przy zakresie `-20..+20` marker jest ograniczony wizualnie
do krawędzi, ale tekst pozostaje `+26.0%`. Analogicznie działa overflow poniżej
minimum. Test obejmuje `+30%` i `-30%`.

## 10. GUI

Dodano schema dla stylu `slope` w istniejącym formularzu bar. Dostępne są m.in.
`source`, `field`, `x`, `y`, `size`, `rotation`, `opacity`, `font_size`,
`min_val`, `max_val`, `major_tick`, `minor_tick`, widoczność wartości/etykiety,
jednostka oraz kolory track/tick/zero/marker/tekstu.

Round-trip JSON po zmianie `source=FIT`, zakresu `-15..18`, `major_tick=3` i
`show_value=false` zachowuje identyczne właściwości.

## 11. Preset v5

Utworzono `presets/cycling_dashboard_v5.json` jako kopię v4. v1–v4 nie zostały
zmienione. Porównanie wykazało, że wszystkie 14 istniejących wskaźników v4 jest
identycznych w v5; dodano wyłącznie `slope_text`.

Konfiguracja nowego widgetu:

| Property | Wartość |
|---|---|
| `enabled` | `true` |
| `label` / `field` | `SLOPE` / `slope` |
| `source` | `gpmf` |
| `x` / `y` | `68.0` / `53.0` |
| `form` / `bar_style` | `bar` / `slope` |
| `rotation` | `0` |
| `size` | `20.0` |
| `font_size` | `1.35` |
| `min_val` / `max_val` | `-20.0` / `20.0` |
| `major_tick` / `minor_tick` | `5.0` / `1.0` |
| `decimals` / `unit` | `1` / `%` |
| visibility | label, value, range labels, units: `true` |
| marker | `#FFD42A`, border `#FFFFFF`, size `6.0` |

## 12. CPU render

Zapisano wymagane artefakty 3840×2160:

- `Raporty/INDICATORS_ETAP_8E_SLOPE_CPU_FRAME.png`
- `Raporty/INDICATORS_ETAP_8E_SLOPE_OVERLAY.png`

CPU frame używa rzeczywistego GPMF slope z chwili około 60 s (`-3.508%`).
Overlay jest transparentny. Slope jest czytelny na prawej stronie, obok
centralnego speed gauge, bez kolizji z Compassem i wykresami.

## 13. Bbox/clipping

Rzeczywisty lokalny raster przy 3840×2160 ma około `139×796 px`; wysokość mieści
się w oczekiwanym przedziale 500–900 px i szerokość pozostaje mała względem
speed gauge.

Sprawdzono 3840×2160, 1920×1080 i 1280×720. Bbox obejmuje tytuł, etykiety,
ticki, zero, marker, wartość i outline. `get_layout_hud_bbox` zawiera cały
lokalny raster na każdej z tych rozdzielczości. Nie zmieniano globalnego dirty
marginu.

Dodano minimalny, lokalny wyjątek w `src/ffmpeg/command_builder.py`: kalkulator
HUD bbox rozpoznaje `bar_style="slope"` i używa pionowej wysokości. Był to
rzeczywisty blocker clippingu nowego rastra; pozostałe formy bar nie zmieniły
estymacji.

## 14. FIT validation

Binding FIT został sprawdzony na `Video/Poranna_jazda_na_rowerze.fit`.
Wartości runtime pochodzą z `fit_data["slope"]`, a na początku osi czasu
poprawnie występuje `None`, nie zero. Punkty 60 s i 120 s zostały wyrenderowane
przez CPU/precomputed path.

## 15. GPMF validation

Binding GPMF został sprawdzony na `Video/GX030120.json`. Wartości 20/60/120 s
pochodzą z `tm.slope_samples` i są przekazywane do renderera bez ponownego
wyliczania w warstwie wskaźnika.

## 16. AMD runtime

Wykonano rzeczywisty eksport `AMD_NATIVE_D3D11` z v5, GPMF/FIT i 10-sekundowym
wycinkiem prawdziwego `GX030120.MP4`:

```text
300/300 klatek
3840×2160
AMF encode + D3D11VA decode
AMD_TELEMETRY_MODE=PRECOMPUTED
true FPS=11.072
```

Pełny log i profil zapisano w `Raporty/AMD_ETAP8E/`.

Zebrane ścieżki:

```text
AMD_MAP_PATH: GPU
AMD_MAP_ORDER: CPU_BELOW_MAP -> GPU_MAP -> CPU_ABOVE_MAP
AMD_CHART_PATH: GPU_SPLIT
AMD_GAUGE_PATH: GPU
AMD_TELEMETRY_MODE: PRECOMPUTED
```

## 17. AMD data parity

AMD użył tej samej precomputed cache co CPU/reference. Profil potwierdza
`300` klatek cache i `300` klatek HUD. Slope znajduje się w uporządkowanej liście
`CPU_ABOVE_MAP`, więc jego wartość i semantyka są takie same jak w CPU.

## 18. AMD visual result

Zapisano:

- `Raporty/INDICATORS_ETAP_8E_SLOPE_AMD_FRAME.png`

Klatka pochodzi z rzeczywistego eksportu AMD. Widoczne są: mapa/obraz wejściowy,
Compass, speed gauge, wykresy oraz pionowy Slope z zakresem `-20..+20`, markerem
na około `-4.8%` i tekstem `-4.8%`. Z-order Slope jest po mapie, w
`CPU_ABOVE_MAP`.

Bar/Slope nie dostał osobnego renderera GPU. Jest jawnie utrzymany na CPU
reference w warstwie above-map, co zachowuje parity i nie dodaje transferu
GPU→CPU→GPU. Log AMD odnotował też istniejący fallback wszystkich chartów do
CPU_REFERENCE z powodu `GPU_CHART_UNSAFE_LAYOUT`; nie był on wywołany przez
Slope.

## 19. Compass regression

Uruchomiono `tests/test_compass_rendering.py` i `tests/test_telemetry_heading.py`.
Compass i canonical heading pozostają bez regresji.

## 20. Map/chart regression

Uruchomiono:

```text
tests/test_map_first_render_parity.py
tests/test_amd_chart_map_split.py
tests/test_etap6_chart_window.py
```

Map order, chart split i ruchome okno wykresów przeszły. W artefakcie AMD wykresy
zachowują zakres referencyjny `-60 s ... 0 s`.

## 21. Standard bar regression

Istniejące testy barów oraz testy gauge przeszły. Zwykły ruler, segment bar,
Virtual Power i warianty altitude zachowały dotychczasową semantykę; nowy kod
jest aktywowany wyłącznie przez `bar_style="slope"`.

## 22. NVIDIA static analysis

Nie dodano renderera NVIDIA i nie zmieniano `streaming.py`, CUDA, NVENC ani
ścieżek NVIDIA. Zmiana bbox w `command_builder.py` jest neutralna backendowo i
dotyczy wyłącznie estymacji lokalnego widgetu Slope.

**NVIDIA path preserved statically; runtime validation was not possible on this AMD machine.**

## 23. Performance

Lokalny raster Slope przy 3840×2160, po rozgrzaniu cache, miał medianę około
`0.852 ms` (P95 około `0.966 ms`). AMD profil dla 300 klatek podał medianę
`compose_overlay=2.093 ms` i `above_compose=29.885 ms`; nie dodano nowego
transferu GPU ani zmiany CPU_ABOVE_MAP poza obecnością jednego lokalnego rastra.
Nie wykonano pełnego benchmarku produkcyjnego.

## 24. Full test suite

Po implementacji:

```text
python -m pytest -q --ignore=tests/test_fit_registration.py
626 passed, 17 skipped, 0 failed in 33.88s
```

`tests/test_fit_registration.py` pozostaje znanym niezależnym wyjątkiem
kolekcji (`ModuleNotFoundError: src.gui.hud_tuner_app`) i nie był naprawiany w
ETAPIE 8E.

Dedykowane testy Slope + bar: `28 passed`.
`git diff --check`: OK.

## 25. Zmienione pliki

Zakres ETAPU 8E:

- `src/indicators/bar.py` — lokalny pionowy `bar_style="slope"` i formatter;
- `src/indicators/compositor.py` — `slope_text`, `None`, formatowanie i binding;
- `src/indicators/registry.py` — registry/source map dla Slope;
- `src/gui/qt/models.py` — schema i properties GUI;
- `src/gui/qt/_mixins/indicator_mixin.py` — domyślny widget i data stream;
- `src/ffmpeg/command_builder.py` — minimalny pionowy bbox blocker fix;
- `presets/cycling_dashboard_v5.json` — v4 + jeden widget Slope;
- `tests/test_slope_rendering.py` — renderer, binding, range, overflow, rotation,
  bbox, schema i round-trip.

Artefakty zapisano w `Raporty/`, w tym PNG, log AMD, profil AMD i krótki MP4
probe.

## 26. Remaining risks

- NVIDIA runtime nie był dostępny na bieżącej maszynie AMD;
- Slope pozostaje CPU_REFERENCE w `CPU_ABOVE_MAP`, zgodnie z wymaganiem parity;
- GPU chart fallback w probe wynikał z istniejącego guarda unsafe-layout dla
  chartów HR/Cadence;
- brak rzeczywistego pliku GPX uniemożliwia runtime walidację wariantu GPX;
- Track-Up i Lean nie zostały zaimplementowane;
- nie zmieniano algorytmu ETAPU 8D ani synchronizacji telemetrycznej.
