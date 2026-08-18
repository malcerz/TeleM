# TeleM — ETAP 3A.6 — walidacja synchronizacji na drugim materiale

Data: 2026-08-18. Diagnostyka read-only; bez zmian kodu.

## Pliki i cache

```text
MP4: C:\_DEV\TeleM\Video\GX030120.MP4
FIT: C:\_DEV\TeleM\Video\Poranna_jazda_na_rowerze.fit
JSON: C:\_DEV\TeleM\Video\GX030120.json
metadata: C:\_DEV\TeleM\Video\GX030120.json.meta.json
size = 1221261824 bytes
duration = 180.180 s
FPS = 30000/1001
frames = 5395
GPMF = present
```

```text
first validation = CACHE HIT
second validation = CACHE HIT
cache version = 2
source_size = 1221261824
source_mtime_ns = 1787035148691942900
```

## GPMF GPS9

```text
count = 1802
first = 2026-08-18 04:46:25.700 UTC
last = 2026-08-18 04:49:25.800 UTC
duration = 180.1 s
interval min/median/max = 0.1 / 0.1 / 0.1 s
source = GPS9 days/secs
```

Sample counts: `GPS9=1802`, `ISOE=5394`, `SHUT=5394`, `TMPC=180`, video frames `5395`.

## FIT

```text
first record = 2026-08-18 04:29:39.000 UTC
last record = 2026-08-18 04:57:30.000 UTC
first GPS = 2026-08-18 04:30:10.000 UTC
last GPS = 2026-08-18 04:57:25.000 UTC
GPS count = 1635
```

## SmartSync i overlap

```text
baseline = 0.000 s
score offset=0 = 121/121, coverage=1.00
selected offset = 0.000 s
method = absolute_time_trajectory_refine
matched = 121/121
coverage = 1.00
median error = 3.3 m
p90 error = 4.5 m
confidence = high
overlap = 04:46:25.700 – 04:49:25.800 UTC
overlap duration = 180.1 s
```

Nie wystąpił file-start alignment ani duży offset.

## Spatial parity

| video_s | target UTC | GPMF | FIT | distance_m |
|---:|---|---|---|---:|
| 0 | 04:46:25.700 | 54.3462681, 18.6438066 | 54.3462640, 18.6437824 | 1.63 |
| 30 | 04:46:55.700 | 54.3474675, 18.6430845 | 54.3474638, 18.6430257 | 3.83 |
| 60 | 04:47:25.700 | 54.3477011, 18.6431106 | 54.3477059, 18.6430570 | 3.51 |
| 90 | 04:47:55.700 | 54.3493391, 18.6423919 | 54.3493308, 18.6422994 | 6.06 |
| 120 | 04:48:25.700 | 54.3519143, 18.6424602 | 54.3519327, 18.6424130 | 3.68 |
| 150 | 04:48:55.700 | 54.3533728, 18.6425647 | 54.3533489, 18.6425410 | 3.08 |
| 175 | 04:49:20.700 | 54.3547063, 18.6433308 | 54.3547143, 18.6433191 | 1.17 |
| 180.180 | 04:49:25.880 | 54.3549977, 18.6433702 | 54.3550061, 18.6433671 | 0.96 |

Statystyki całego overlapu: minimum `0.49 m`, median `3.30 m`, p90 `4.48 m`, maximum `6.39 m`. Klasyfikacja: zasadniczo `<10 m`.

## Map lookup

`source=gpmf`: `t=0 CLAMP_START` boundary, `30/60/90/120/150/175 TIMESTAMP`, koniec `CLAMP_END` boundary.

`source=fit`: `0/30/60/90/120/150/175/end TIMESTAMP`. Nie ma długiego `CLAMP_START`. `target_dt` ma pierwszeństwo przed `current_position`.

## Wartości przy absolutnym 06:46:40 lokalnie

Target UTC: `2026-08-18 04:46:40`, video elapsed `14.3 s`.

| Field | TeleM | Source | Overlay | Delta |
|---|---:|---|---:|---:|
| HR | 102 | FIT | 102 | 0 |
| cadence | 63 | FIT | ~61 | +2 |
| speed | 18.48 km/h | GPMF smoothed 3D | ~18.7 | -0.22 |
| ISO | 70 | GPMF | ~74 | -4 |
| shutter | 1/431 | GPMF | ~1/455 | -24 denominator |
| camera temp | 30 °C | GPMF/TMPC | ~30.5 | -0.5 |
| ambient temp | 17 °C | FIT | ~17 | 0 |

Speed candidates: GPMF 2D `17.438`, GPMF 3D `18.252`, derived GPS `17.084`, FIT speed `20.020`, FIT enhanced speed `20.020`, selected TeleM `18.482 km/h` (smoothed GPMF 3D).

## Ocena

```text
ETAP 3A.3 GPS9 = VALID
ETAP 3A.5A CACHE = VALID
ETAP 3A.5B SMARTSYNC = VALID
wrong start = ABSENT
delayed middle = ABSENT
fast end = ABSENT
large spatial mismatch = ABSENT
long CLAMP_START = ABSENT
```

Nie potwierdzono pozostałego błędu synchronizacji, mapy, czasu kanonicznego ani PTS/VFR. Różnice speed/ISO/shutter są lokalnymi różnicami źródła lub próbek.

## Testy i następny krok

`79 passed, 17 skipped` dla testów powiązanych. Pełna suite: `298 passed, 4 failed, 17 skipped`; cztery failure’y są wcześniejsze i niezwiązane z tym etapem.

Nie ma potrzeby kolejnego etapu SmartSync/map timing. Ewentualny następny etap powinien dotyczyć wyłącznie różnic `speed`, `ISO` i `shutter` względem Telemetry Overlay.
