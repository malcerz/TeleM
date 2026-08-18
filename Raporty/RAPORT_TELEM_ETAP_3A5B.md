# TeleM — ETAP 3A.5B — naprawa SmartSync na realnych timestampach GPS

Data: 2026-08-18  
Zakres: wyłącznie SmartSync i testy SmartSync.

## Wynik

`PASS — SmartSync nie przesuwa już długiego FIT względem początku krótkiego filmu.`

## A. Stary algorytm

```text
GPMF start       = 04:55:50.800
FIT first record = 04:28:05.000
old baseline     = +27:45.800
old selected     = +27:45.800
```

Stary `_compute_smart_time_offset()` przekazywał do `_align_offset_by_track()` różnicę `GPMF start - FIT first record`. Po odrzuceniu trajectory alignment direct anchor zwracał tę samą różnicę, mimo że właściwy fragment FIT już pokrywał się czasowo z GPMF.

## B. Nowy decision tree

```text
GPMF/FIT absolute UTC
        ↓
sprawdzenie overlapu GPS przy offset=0
        ↓
stałe okno wspólnego czasu absolutnego
        ↓
scoring interpolowanych pozycji GPS wokół 0 s
        ↓
opcjonalny refinement tylko przy wyraźnej poprawie jakości
        ↓
confidence i wybrany offset
        ↓
timezone fallback
        ↓
align-start fallback jako ostateczność
```

Scoring nie używa nearest-neighbour ani pierwszego rekordu FIT jako baseline. Coverage jest liczony względem fragmentu GPMF pokrywającego się czasowo z FIT przy offset `0`.

## C. Konwencja znaku

Zachowano:

```text
shifted_fit_timestamp = raw_fit_timestamp + offset
```

Test regresyjny potwierdza: FIT przesunięty o `+1.2 s` otrzymuje offset `-1.2 s`.

## D. Wynik realnych danych

Pliki:

```text
GX020079.mp4
Morning_Ride.fit
```

```text
GPMF GPS range       = 04:55:50.800 – 04:56:28.500
FIT raw GPS range    = 04:28:26.000 – 04:56:23.000
baseline             = 0.000 s
score offset=0       = 108/108, coverage=1.00
selected offset      = 0.000 s
method               = absolute_time_trajectory_refine
median error         = 21.6 m
p90 error            = 90.2 m
confidence           = high
```

Wynik nie wynosi już `+1665.8 s` ani około `±27 min`.

## E. Before / after

| Metryka | OLD | NEW |
|---|---:|---:|
| selected offset | +1665.8 s | 0.0 s |
| FIT position at video t=0 | 54.3314733, 18.6013457 | 54.3655560, 18.6238172 |
| FIT `CLAMP_START` | około 21 s | 0 s |
| trajectory median | 3944.1 m | 21.6 m |
| trajectory p90 | 3968.7 m | 90.2 m |

## F. Porównanie pozycji

| video_s | GPMF position | FIT position | distance_m |
|---:|---|---|---:|
| 0 | 54.3655031, 18.6238153 | 54.3655560, 18.6238172 | 5.9 |
| 5 | 54.3654766, 18.6234719 | 54.3655418, 18.6234808 | 7.3 |
| 10 | 54.3654806, 18.6232109 | 54.3655535, 18.6231843 | 8.3 |
| 20 | 54.3653198, 18.6232376 | 54.3656178, 18.6230590 | 35.1 |
| 30 | 54.3647160, 18.6234650 | 54.3654922, 18.6227705 | 97.3 |
| end | 54.3642093, 18.6235643 | 54.3654818, 18.6227175 | 151.8 |

Różnica około 4 km została usunięta. Końcowy wzrost błędu wynika z faktu, że ostatni GPS FIT kończy się `04:56:23`, około 5.5 s przed końcem GPMF; FIT jest wtedy prawidłowo utrzymywany na ostatnim punkcie.

## G. Map sanity

### `source=gpmf`

```text
t=0    CLAMP_START na granicy pierwszej próbki
t=10   TIMESTAMP
t=20   TIMESTAMP
t=30   TIMESTAMP
t=end  CLAMP_END
```

### `source=fit`

```text
t=0    TIMESTAMP
t=10   TIMESTAMP
t=20   TIMESTAMP
t=30   TIMESTAMP
t=end  CLAMP_END na ostatnim FIT GPS
```

Wcześniejszy około 21-sekundowy `CLAMP_START` FIT zniknął.

## H. Files changed

```text
src/gui/telemetry_manager.py
  _align_offset_by_track()
  _compute_smart_time_offset()
  scoring po wspólnych timestampach UTC, search wokół 0 s,
  jawne logowanie metody i fallbacków

tests/test_telemetry_manager.py
  test braku overlapu bez sztucznego file-start offsetu
  test sign convention dla offsetu -1.2 s
```

Nie zmieniano parsera GPS9, cache GPMF, parsera FIT, map, PTS, VFR, preview seek ani source resolvera.

## I. Testy

```text
related passed = 79
related failed = 0
skipped = 17
full suite passed = 298
full suite failed = 4
```

Cztery failure’y pełnej suite są niezwiązane: AMD ABI, AMD FIT layout, QP analyzer i kolejność encoderów.

## J. Compatibility

```text
GPS9 parser unchanged = yes
GPMF cache unchanged = yes
FIT parser unchanged = yes
map renderer unchanged = yes
PTS unchanged = yes
VFR unchanged = yes
source resolver unchanged = yes
```

## K. Remaining issues

```text
MAP FOLLOW-UP REQUIRED = no, na podstawie resolvera i lookupu
CANONICAL TIME FOLLOW-UP = no dla tej ścieżki
PTS/VFR FOLLOW-UP = no
```

Pozostaje ograniczenie danych: FIT kończy GPS około 5.5 s przed końcem GPMF, więc końcowy marker FIT jest utrzymywany na ostatnim punkcie.
