# TeleM — ETAP 3A.4 — walidacja end-to-end po naprawie GPS9

Data walidacji: 2026-08-18  
Zakres: diagnostyka wyłącznie; bez zmian kodu.

## Wynik

`NEEDS FOLLOW-UP`

Naprawa GPS9 działa poprawnie w świeżej ekstrakcji GPMF, ale pełna ścieżka jest nadal blokowana przez stary cache JSON oraz wybór offsetu SmartSync.

## Pliki i cache

```text
MP4: C:\_DEV\TeleM\Video\GX020079.mp4
FIT: C:\_DEV\TeleM\Video\Morning_Ride.fit
Cache: C:\_DEV\TeleM\Video\GX020079.json
```

Cache zawiera stare czasy `04:28:04.000–04:28:41.700`. `_load_or_generate_telemetry()` ładuje istniejący `.json` przed ponowną ekstrakcją GPMF.

Status: `CONFIRMED CACHE ISSUE`.

## GPMF i start_dt_utc

```text
GPS count = 378
first GPS = 2026-08-05T04:55:50.800Z
last GPS  = 2026-08-05T04:56:28.500Z
TelemetryDataManager.start_dt_utc = 2026-08-05T04:55:50.800Z
```

`target_dt = start_dt_utc + seek_seconds` działa prawidłowo dla świeżych danych. Czas lokalny przy `tz_offset_hours=2` wynosi `06:55:50.800`.

## SmartSync

```text
absolute baseline = +27:45.800
trajectory candidate = rejected
matched = 32/126
coverage = 0.25
median error = 3944.1 m
p90 error = 3968.7 m
selected offset = +27:45.800
method = direct timestamp anchor
```

SmartSync przesuwa FIT względem pierwszego rekordu FIT, mimo że FIT zawiera punkty GPS w zakresie czasu GPMF.

```text
FIT first GPS raw     = 04:28:26.000
FIT first GPS shifted = 04:56:11.800
GPMF first GPS        = 04:55:50.800
```

## Porównanie przestrzenne

| video_s | GPMF | FIT po SmartSync | distance_m |
|---:|---|---|---:|
| 0 | 54.3655031, 18.6238153 | 54.3314733, 18.6013457 | 4054.5 |
| 5 | 54.3654766, 18.6234719 | 54.3314733, 18.6013457 | 4043.8 |
| 10 | 54.3654806, 18.6232109 | 54.3314733, 18.6013457 | 4038.2 |
| 20 | 54.3653198, 18.6232376 | 54.3314733, 18.6013457 | 4022.1 |
| 30 | 54.3647160, 18.6234650 | 54.3315219, 18.6010351 | 3967.0 |
| 32.738 | 54.3645138, 18.6234814 | 54.3314522, 18.6009701 | 3955.2 |
| 37.738 | 54.3642093, 18.6235643 | 54.3313013, 18.6008767 | 3943.6 |

Różnica około 4 km pozostaje po SmartSync.

## Map lookup

GPMF: `t=0 CLAMP_START` na granicy pierwszego punktu, `t=10/20/30 TIMESTAMP`, `t=end CLAMP_END` tylko na ostatnich około `0.037 s`.

FIT po SmartSync: `t=0/10/20 CLAMP_START`, `t=30/end TIMESTAMP`. Wynika z tego około 21 sekund `CLAMP_START` dla FIT.

## Koniec i ruch markera

Nie potwierdzono numerycznie „przyspieszenia końca”. Film ma `37.737700 s`, `30000/1001 fps` i `1131` klatek. PTS/frame_index nie był zmieniany.

## Klasyfikacja objawów

| Objaw | Status | Wyjaśnienie |
|---|---|---|
| Błędny start FIT | UNCHANGED | offset względem pierwszego rekordu FIT |
| Marker stojący na początku | UNCHANGED dla FIT | około 21 s `CLAMP_START` |
| Opóźniony środek | UNCHANGED | FIT nadal nie jest przestrzennie zgodny |
| Szybki koniec | IMPROVED / NIEPOTWIERDZONY | brak numerycznego skoku |
| GPMF/FIT ~4 km różnicy | UNCHANGED | 3.94–4.05 km |
| SmartSync `-27:45` | UNCHANGED | nadal wybierany offset `+27:45.800` |

## Pozostały root cause

```text
CACHE
FILE: src/gui/qt/_mixins/project_mixin.py
FUNCTION: _load_or_generate_telemetry()
ROOT CAUSE: istniejący GX020079.json jest ładowany bez walidacji świeżości

SMARTSYNC
FILE: src/gui/telemetry_manager.py
FUNCTION: _compute_smart_time_offset(), _align_offset_by_track()
ROOT CAUSE: po odrzuceniu trajectory alignment direct anchor używa pierwszego
rekordu FIT zamiast najlepszego nakładania punktów GPS
```

## Ocena końcowa

```text
MAP RENDERER BUG: UNCONFIRMED
CANONICAL TIME ISSUE: PARTIAL
ETAP 3A: NEEDS FOLLOW-UP
```

Najmniejszy następny etap: osobno zwalidować i naprawić unieważnianie `GX020079.json`, a następnie osobno skorygować wybór offsetu SmartSync. W ETAPIE 3A.4 nie wykonano zmian implementacyjnych.

## Testy

```text
88 passed
```
