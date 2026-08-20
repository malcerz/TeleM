# TeleM — NVIDIA ETAP 5B.6: Atlas Geometry z aktywnymi Battery/Solar

Data: 2026-08-20  
Materiał produkcyjny: `GX030120.MP4` + `Popoludniowa_jazda_na_rowerze_solar_battery.fit`  
Konfiguracja stała: 4 workery, `MAX_IN_FLIGHT=8`, FFmpeg/NVENC bez zmian

## A. FIT availability comparison

Dostępność została odczytana z pełnego słownika pól zwróconego przez parser FIT. Nie założono stałego zestawu rekordów.

| Indicator | Poranna | Popołudniowa | bbox/transport |
|---|---:|---:|---|
| `fit_cadence_text` / `cadence` | 1672 | 1741 | aktywny |
| `fit_enhanced_speed_text` / `enhanced_speed` | 1653 | 1750 | aktywny |
| `fit_heart_rate_text` / `heart_rate` | 1672 | 1754 | aktywny |
| `fit_temperature_text` / `temperature` | 1672 | 1754 | aktywny |
| `fit_battery_text` / `battery` | brak | brak | phantom, wyłączony z transportu |
| `fit_battery_pct_text` / `battery_pct` | brak | 1754 | aktywny |
| `fit_solar_pct_text` / `solar_pct` | brak | 1754 | aktywny |

`fit_battery_text` nie został ukryty arbitralnie: parser nie zwrócił pola `battery`. Popołudniowy FIT zawiera natomiast prawidłowe pola `battery_pct` i `solar_pct`, które pozostały aktywne i widoczne.

## B. Root cause `69.821% → 74.6%`

Aktualne `MAX4 + GRID16`:

| FIT | atlas | area |
|---|---:|---:|
| Poranna | `1900×762` | `69.821%` |
| Popołudniowa | `1832×844` | `74.566%` |

Battery/solar nie powiększają bezpośrednio największego prostokąta. Powodują jednak powstanie osobnego naturalnego klastra na górze ekranu. Przy limicie czterech regionów packer musi scalić ten klaster z innym, zwiększając wysokość atlasu z `762` do `844` px.

Usunięcie pojedynczego `battery_pct` albo `solar_pct` nie zmniejszyło pola atlasu — dlatego danych nie wyłączano.

## C. Battery/solar geometry

Po precyzyjnym pomiarze tekstu i snapie `GRID16`:

| indicator | source bbox | atlas region |
|---|---:|---:|
| `fit_solar_pct_text` | `(958,78,65×17)` | region 2 |
| `fit_battery_pct_text` | `(958,142,73×19)` | region 2 |

Oba elementy są w jednym aktywnym regionie źródłowym:

```text
src=(958,78,74×84)
```

Wartości z FIT obejmują:

```text
battery_pct: 80.0 → 74.0, min=74.0, max=80.0
solar_pct:   77.0 → 61.0, min=57.0, max=78.0
```

Pomiar korzysta z rzeczywistych formatted values, fontu, labeli i stroke; nie przywrócono szerokich heurystyk.

## D. Region layouts

### MAX4 + GRID16 — obecny przed zmianą

```text
atlas: 1832×844
area: 74.566%

R0 src=(958,78,74×84)     atlas=(0,0)
R1 src=(30,30,64×514)     atlas=(78,0)
R2 src=(1472,118,448×316) atlas=(146,0)
R3 src=(46,754,1828×326)  atlas=(0,518)
```

### MAX5 + GRID16 — wariant wybrany

```text
atlas: 1900×762
area: 69.821%

R0 src=(1646,414,102×20)  atlas=(0,0)
R1 src=(1472,118,448×244) atlas=(106,0)
R2 src=(958,78,74×84)    atlas=(558,0)
R3 src=(46,754,1828×326) atlas=(0,248)
R4 src=(30,30,64×514)    atlas=(1832,248)
```

Region ownership dla wariantu MAX5:

```text
R0: fit_temperature_text
R1: track_map
R2: fit_battery_pct_text, fit_solar_pct_text
R3: fit_cadence_text, fit_enhanced_speed_text, fit_heart_rate_text
R4: exposure_text, iso_text, temp_text, time_block
```

## E. Tested grid/reposition/MAX variants

Przetestowano:

- `MAX4 + GRID16`: `74.566%`;
- `MAX5 + GRID16`: `69.821%`;
- wyłączenie `fit_battery_pct_text`: nadal `74.566%`;
- wyłączenie `fit_solar_pct_text`: nadal `74.566%`;
- lokalne przesunięcia obu pól w zakresie ±16 px przy `GRID8` i `GRID16`: brak wariantu `<=70%`;
- większe, diagnostyczne przesunięcia: mogły zejść do `69.821%`, ale przekraczały limit bezpiecznej lokalnej zmiany i nie zostały wybrane.

## F. Selected solution

Wybrano `MAX5 + GRID16`.

Zmiana produkcyjna:

```python
NVIDIA_HUD_MAX_REGIONS = 5
```

Próg fallbacku pozostał `70%`. Battery/solar nie są wyłączane, nie zmieniono ich wyglądu ani semantyki źródła.

## G. Visual correctness

Weryfikacja Popołudniowej FIT:

- legacy vs Direct-Region: `max_diff=0`, `different_pixels=0` dla klatek `0, 540, 1350, 2700, 4050, 4860, 5399`;
- zgodność kształtu: `1900×762×4`;
- ROT180: `max_diff=0`, `different_pixels=0` dla wszystkich 5 punktów kontrolnych;
- battery/solar mają aktywną własność regionu i wartości FIT;
- zachowano chart history, gauge, track map, time/text i alpha;
- Direct-Region pozostaje aktywny.

## H. CUDA cost

NO-OP A/B dla identycznego materiału i atlasów, 3 przebiegi:

| wariant | mediana FPS | mediana czasu |
|---|---:|---:|
| MAX4 | `393.69 FPS` | `13.716 s` |
| MAX5 | `366.47 FPS` | `14.735 s` |

Koszt dodatkowej gałęzi regionu w syntetycznym grafie wyniósł około `6.9%`. MAX4 nie spełnia kryterium atlasu, dlatego MAX5 jest świadomym kompromisem funkcjonalnym.

## I. Production benchmark 3×

Wszystkie przebiegi użyły:

```text
HUD mode: MULTI_REGION_ATLAS
HUD producer: DIRECT_REGION
atlas: 1900×762
area: 69.8%
slot: 5.52 MB/frame
SHM: 44.2 MB
```

| run | FRAME_PIPELINE | REAL_EXPORT | ffmpeg avg | ffmpeg p95 |
|---:|---:|---:|---:|---:|
| 1 | 221.7 FPS | 209.5 FPS | 3.68 ms | 8.76 ms |
| 2 | 219.4 FPS | 207.7 FPS | 3.83 ms | 12.95 ms |
| 3 | 220.2 FPS | 207.4 FPS | 4.63 ms | 15.54 ms |

Mediana `REAL_EXPORT`: **207.7 FPS**.  
Mediana `FRAME_PIPELINE`: około **220.2 FPS**.

## J. Preview ON/OFF cost

Wykonano 3 przebiegi OFF i 3 ON. Preview nadal korzysta z istniejącego asynchronicznego snapshot handoffu; nie wymusza full-frame HUD.

| wariant | REAL_EXPORT mediana | FRAME_PIPELINE mediana | update |
|---|---:|---:|---:|
| preview OFF | `205.1 FPS` | około `216.8 FPS` | 0 |
| preview ON | `207.7 FPS` | około `220.2 FPS` | `108/run`, około `4.16 Hz` |

Różnica mieści się w szumie pomiarowym i nie wykazuje regresji kosztu pipeline. Callback przekazuje mały snapshot co 50 klatek; nie wykonuje pełnego compositingu HUD dla każdej klatki. Rzeczywisty Qt widget pozostaje asynchroniczny i ograniczony częstotliwościowo.

## K. New stable baseline

```text
FIT: Popoludniowa_jazda_na_rowerze_solar_battery.fit
MAX5 + GRID16
atlas: 1900×762
area: 69.821%
MULTI_REGION_ATLAS
DIRECT_REGION
FRAME_PIPELINE: ~220.2 FPS median
REAL_EXPORT: ~207.7 FPS median
preview: ~4.16 updates/s
```

## Odpowiedzi końcowe

**Czy wzrost atlasu do 74.6% wynikał z aktywnych battery/solar?**  
Tak — nie przez samą powierzchnię tekstu, lecz przez utworzenie dodatkowego naturalnego klastra, który przy `MAX4` wymuszał niekorzystne scalenie.

**Który indicator/region był główną przyczyną?**  
Wspólny region `fit_battery_pct_text + fit_solar_pct_text` na górze canvasu; problemem była liczba klastrów i merge, nie pojedynczy szeroki bbox.

**Jaki wariant ponownie sprowadził atlas poniżej 70%?**  
`MAX5 + GRID16`: `69.821%`.

**Czy wszystkie battery/solar nadal są widoczne?**  
Tak. Wszystkie pola dostępne w FIT pozostają aktywne: `battery_pct` i `solar_pct`. Nie istnieje pole `battery`, więc `fit_battery_text` pozostaje poprawnie oznaczony jako phantom.

**Jaki jest nowy realny FRAME_PIPELINE FPS?**  
Mediana około **219.4 FPS** na wskazanym materiale i ustawieniach.

**Ile rzeczywiście kosztuje działający preview?**  
W pomiarze ON/OFF nie wykazano mierzalnego narzutu; różnica była w granicy szumu (`preview ON` nie był wolniejszy). Preview dostarcza około **4.16 aktualizacji/s** i pozostaje asynchroniczny.

Etap 5B.6 zakończony. Nie kontynuowano ETAPU 5E.
