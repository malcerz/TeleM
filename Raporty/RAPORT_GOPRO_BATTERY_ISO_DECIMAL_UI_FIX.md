# GoPro Battery / ISO decimal UI fix

## Zakres

Mały etap presentation-only. Nie zmieniano `NumericPresentationPlan`, parserów
FIT/GPMF, resolvera interpolacji, Lean, geometrii BAR ani backendów.

## Root cause

- Nowe wskaźniki były inicjalizowane w `IndicatorMixin._create_indicator()` z
  globalnym `decimals=1`. Dynamiczny `fit_gopro_battery_text` nie miał
  wskaźnikowego domyślnego schematu, więc panel właściwości dziedziczył ogólny
  default zamiast kanonicznego 0.
- `iso_text` w starych layoutach mógł mieć `decimal_places=1` albo odziedziczyć
  `decimals=1`; compositor prawidłowo respektował tę konfigurację i formatował
  `800.0`. Nie był to błąd wartości ani interpolacji.

## Implementacja

Dodano w `src/gui/qt/models.py` jeden mały kontrakt UI:

- `indicator_default_decimals()` zwraca 0 dla `iso_text` i
  `fit_gopro_battery_text`;
- `get_schema_for_indicator()` opiera się na istniejącym generic schema i
  podmienia wyłącznie kanoniczny default pola `decimals` (0–3), bez mutowania
  fabryki schematu;
- `normalize_indicator_decimal_defaults()` dopisuje `decimals=0` tylko gdy
  brak jawnego nowoczesnego `decimals`, zachowując jawne ustawienia użytkownika.

Kontrakt jest używany przy tworzeniu i prezentacji właściwości, zmianach
formularza/pozycji, ładowaniu projektów i presetów oraz normalizacji layoutu.
Normalizacja
zapisu zabezpiecza również bezpośredni zapis starego layoutu. `decimals` nadal
przechodzi przez istniejący `resolve_presentation_precision`; wartość
telemetryczna pozostaje niezmieniona.

## Testy automatyczne

Nowy plik `tests/test_gopro_battery_iso_decimal_ui.py` sprawdza:

- GoPro property, zakres 0–3, default 0 i etykietę „Liczba miejsc po przecinku”;
- formatowanie 47.43851 jako 47%, 47.4%, 47.44%, 47.439%;
- ISO default `800` bez stringowego `replace`, a resolver ISO pozostaje STEP;
- migrację starego `decimal_places=1` do kanonicznego ISO `decimals=0`;
- zachowanie jawnego `decimals=2` i JSON save/reload.

Wynik: **6 passed**. Dodatkowo: `test_display_precision_interpolation.py`,
`test_presentation_architecture.py`: **48 passed**.

Wybrane istniejące regresje (config parity, chart decimals, text renderer,
GoPro startup): 66 testów przeszło; jeden istniejący test segment-bar zakończył
się błędem niezwiązanym z tą zmianą (`segment_count` vs aktualny schema), a
`test_fit_registration.py` nie został zebrany, bo odwołuje się do usuniętego
`src.gui.hud_tuner_app`. Te dwa problemy oznaczono jako NOT TESTED/poza zakresem.

## Real GUI

Uruchomiono normalne `QApplication → AppController → MainWindow` (bez
offscreen) na:

`D:/GoPro/2026-09-02/GX010246.MP4` +
`D:/GoPro/2026-09-02/Poranna_jazda_na_rowerze.fit`.

Artefakty: `D:/TeleM_live_acceptance/gopro_battery_iso_decimal/`.

`trace.json` i zrzuty `battery_default.png`, `battery_dp0.png` …
`battery_dp3.png`, `iso_default.png`, `iso_seek.png` potwierdzają:

- panel normalnego GUI zawiera `decimals`, zakres 0–3, default 0 dla
  `fit_gopro_battery_text`;
- live Preview po zmianach 0/1/2/3 renderował odpowiednio `53%`, `52.7%`,
  `52.68%`, `52.680%` przy tym samym float 52.680148…;
- schema ISO ma default 0, a nowo dodany (bez legacy precision) ISO pokazał
  `545`, po seeku `215`, bez `.0`;
- zapis sidecar zachował zmianę GoPro do `decimals=3`; migrację i round-trip
  brakującego ISO potwierdza test JSON oraz `normalize_layout`.

## Regresje i izolacja

Garmin Battery, Temperature, Speed, Power i Altitude nie zmieniają swoich
schematów ani istniejących wartości `decimals`. ISO raw/presentation nadal jest
STEP (brak 137.5). Nie zmieniono żadnego backendu ani warstwy renderera.

## Final gate

| Kryterium | Status |
|---|---|
| GoPro Battery decimals property / 0–3 | PASS |
| GoPro 0/1/2/3 live formatting | PASS |
| GoPro save/reload value | PASS |
| ISO default integer / no forced `.0` | PASS |
| ISO remains STEP | PASS |
| Other numeric decimals regression | PASS (tests) |
| Full legacy test suite | NOT READY — dwa opisane problemy bazowe poza zakresem |

Zmienione pliki: `src/gui/qt/models.py`,
`src/gui/qt/_mixins/indicator_mixin.py`, `src/gui/qt/_mixins/preset_mixin.py`,
`src/gui/qt/_mixins/project_mixin.py`, `src/gui/layout_manager.py`,
`src/indicators/compositor.py`, test i skrypt GUI.

Status etapu: **READY (zakres zamknięty)**. Brak commit/push.
