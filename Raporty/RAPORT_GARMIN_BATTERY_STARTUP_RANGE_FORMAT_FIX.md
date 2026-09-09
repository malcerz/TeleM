# Garmin Battery startup + range label format fix

## Zakres i stan początkowy

Audyt dotyczył wyłącznie `fit_garmin_battery_percent_text` /
`garmin_battery_percent` oraz generycznej precyzji etykiet BAR. Nie zmieniano
GoPro Battery, matematyki `NumericPresentationPlan`, parserów FIT/GPMF, Lean ani
backendów.

W aktualnym `main` wspólny startup/warm-up contract z poprzedniego etapu już
obejmuje oba pola (`garmin_battery_percent` i `gopro_battery`): plan jest
rozgrzewany po załadowaniu FIT, a preview jest blokowany do zakończenia tego
ładowania. Nie było potrzeby tworzenia drugiej implementacji ani zmiany tego
kontraktu.

## Frame-0 root cause / dowód

Materiał: `D:/GoPro/2026-09-02/GX010246.MP4` +
`D:/GoPro/2026-09-02/Poranna_jazda_na_rowerze.fit`.

- video start: `2026-09-02T04:22:38.224128Z`;
- pierwszy surowy rekord Garmin Battery: `2026-09-02T04:22:27Z`, `96.0`;
- frame-0 target: `2026-09-02T04:22:38.224128Z`;
- resolver/frame_data/compositor: `95.95092365714285`;
- visible HUD przy `decimals=2`: `95.95%`.

Realny GUI (`QApplication → AppController → MainWindow`) nie reprodukuje już
`--%`; dokładny seek do `0.0` również zwraca wartość natychmiast, bez play,
drugiego ticka i ponownego ładowania FIT. Ślad i zrzuty są w
`D:/TeleM_live_acceptance/garmin_battery_startup_range/trace.json`.

## Root cause zakresu

`_render_ruler`, `_render_ruler_vertical` i `_render_segments` używały jednego
`decimals` jednocześnie dla current value i min/max/tick labels. Przy
`decimals=2` dawało to `0.00` / `100.00`. Dodano generyczny resolver
`_resolve_range_decimals()`:

- jawne `range_decimals` ma pierwszeństwo;
- skala procentowa 0–100 dostaje integer range `0` / `100`;
- pozostałe skale zachowują dotychczasową precyzję current value.

Current value nadal korzysta wyłącznie z `decimals`; geometryczna wartość i
interpolacja nie zostały zmienione.

## Real GUI i final smoke

Normalny GUI na realnym pliku, po ustawieniu segment BAR `decimals=2`, pokazał
`95.95%`; trace formatowania zawierał current `(95.950923..., 2)` oraz zakresy
`(0, 0)` i `(100, 0)`. Zrzuty:

`D:/TeleM_live_acceptance/garmin_battery_startup_range/frame0.png` i
`frame1.png`.

Krótki final AMD/AMF smoke zakończył się poprawnie:

`D:/TeleM_live_acceptance/garmin_battery_startup_range/final_smoke_30f.mp4`

FFprobe potwierdził 30 klatek; render użył AMD native/AMF i audio source copy.

## Regresje i testy

Nowe testy obejmują frame-0/seek-start Garmin, current decimals 0–3, integer
range 0–100 oraz zachowanie precyzji dla nieprocentowych BAR-ów. Dodatkowo
przeszły testy Distance, Altitude, Battery/Solar i istniejące testy FIT,
presentation oraz resolver:

**44 passed**, a osobny zestaw FIT/presentation: **48 passed, 1 skipped**.

Distance/Altitude zachowują swoje dotychczasowe zakresy dziesiętne; Solar nie
otrzymał globalnego wymuszenia integer poza semantyczną skalą procentową 0–100.

## Zmienione pliki

- `src/indicators/bar.py` — niezależne `range_decimals` z bezpiecznym fallbackiem;
- `tests/test_gopro_battery_iso_decimal_ui.py` — testy startup/range;
- skrypty audytowe `tests/manual_garmin_startup_range.py` i
  `tests/manual_garmin_battery_final_smoke.py`;
- ten raport.

## Final gate

| Kryterium | Status |
|---|---|
| Garmin Battery frame 0 numeric | PASS |
| No startup `--%` | PASS |
| Exact seek-to-start immediate | PASS |
| Current value decimals preserved | PASS |
| Battery range `0 / 100` | PASS |
| No `0.00 / 100.00` range | PASS |
| Distance BAR regression | PASS |
| Altitude BAR regression | PASS |
| Solar BAR regression | PASS |
| Short final smoke | PASS |

**STATUS = READY**

Nie wykonano commit ani push.
