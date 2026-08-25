# TeleM — ETAP 8H: kalibracja Bike Lean względem GPS / dynamiki zakrętu

Data: 2026-08-22  
Status końcowy: **LEAN CALIBRATION: NOT RELIABLE**

## 1. Algorytm referencji GPS

Użyto kinematycznej referencji:

```text
omega = d(COG)/dt
lean_ref = atan2((speed_kmh / 3.6) * omega, g)
```

Pochodną liczono z rozwiniętego kątowo COG. Jest to referencja diagnostyczna, nie absolutny ground truth: wpływają na nią jakość GPS, camber, nachylenie drogi i niejednostajność skrętu.

Porównano dwa źródła COG:

- production heading: istniejące `derive_heading_samples`, dystans 5 m, smoothing 2 s;
- lekko wygładzony wariant offline: ten sam helper, smoothing 0.5 s, pochodna i krótkie wygładzenie yaw-rate.

Nie zmieniano `src/telemetry_heading.py`. Różnica GPS lean między wariantami miała RMSE `2.47°`; production smoothing jest użyteczny jako stabilny kontekst, ale może tłumić i opóźniać yaw-rate, dlatego do referencji użyto wariantu 0.5 s.

## 2. Porównanie kandydatów osi

Każdy kandydat używał odpowiadającego gyro X/Y/Z oraz causal CF `.98`. Testowano `angle` i `-angle`, z offsetem estymowanym na prostym fragmencie. Amplitudy nie były arbitralnie skalowane.

| Oś / znak | signed corr | abs corr | RMSE [deg] | lag best [ms] | zgodność znaków zakrętów |
|---|---:|---:|---:|---:|---|
| X `+atan2(Y,-Z)` | `-0.036` | `0.036` | `5.79` | `+1986` | 1/2 |
| X `-atan2(Y,-Z)` | `+0.036` | `0.036` | `5.54` | `+1986` | 1/2 |
| Y `+atan2(X,-Z)` | `-0.302` | `0.302` | `6.28` | `+617` | 1/2 |
| Y `-atan2(X,-Z)` | `+0.302` | `0.302` | `4.68` | `+617` | 1/2 |
| Z `+atan2(X,Y)` | `-0.178` | `0.178` | `96.03` | `+1483` | 0/2 |
| Z `-atan2(X,Y)` | `+0.178` | `0.178` | `94.87` | `+1483` | 2/2, ale z błędną amplitudą |

Najlepszym praktycznym kandydatem amplitudowo jest Y z odwróconym znakiem, ale nie przechodzi kryterium dwóch zakrętów. X pozostaje zgodny z wcześniejszą korelacją ACCL/gyro z 8G, lecz również nie ma stabilnej zgodności GPS.

## 3. Wybrana oś, znak i offset

Do końcowej ilustracji wybrano numerycznie najlepszy wariant z rodziny X: kanoniczna oś X, kąt `-atan2(Y,-Z)`, gyro X z tym samym odwróceniem znaku, CF `.98`. To wybór diagnostyczny, nie zatwierdzony mapping fizyczny.

- wybrana oś: kanoniczna X = GPMF `raw[1]`;
- fizyczny znak Lean: **niepotwierdzony**; stały znak nie pasuje do obu zakrętów;
- mount offset: `+1.798°` dla wybranego znaku, mediana z fragmentu prostego z `|lean_ref|<3°`;
- offset nie jest stabilną kalibracją montażu, ponieważ test zakrętów nie potwierdza mappingu.

## 4. Gyro bias

Bias oceniono jako medianę gyro na prostym fragmencie przy małej referencji GPS i małej prędkości kątowej:

- wybrany, odwrócony znak gyro X: `-0.001065 rad/s`;
- korekcja biasu praktycznie nie zmieniła wyniku prostego fragmentu.

| Filtr | Drift prostej [deg/s] | Stddev prostej [deg] |
|---|---:|---:|
| CF `.98`, bez biasu | `+0.0562` | `1.338` |
| CF `.98`, z biasem | `+0.0562` | `1.338` |
| CF `.995`, bez biasu | `+0.0322` | `0.793` |
| CF `.995`, z biasem | `+0.0322` | `0.793` |

Bias jest mały względem dynamicznych błędów i nie rozwiązuje problemu znaku.

## 5. Alpha i wynik filtrów

Sprawdzono tylko wymagane `.98` i `.995`. `.995` daje spokojniejszą prostą, ale silniej polega na gyro i nie naprawia zgodności z referencją GPS. Do prototypu zachowano `.98` jako mniej agresywny filtr, bez rekomendacji produkcyjnej.

## 6. Zakręty

| Fragment | Turn direction | GPS lean peak | IMU lean peak | znak zgodny? | lag |
|---|---|---:|---:|---|---:|
| `64–72 s` | ujemny / lewy | `-11.54°` | `+20.54°` | NIE | best search `+2001 ms`, granica zakresu |
| `145–155 s` | dodatni / prawy | `+3.91°` | `+11.40°` | TAK | best search `+849 ms` |

Peak timing również nie jest wiarygodny: różnica czasu pików wyniosła odpowiednio około `+5279 ms` i `-4066 ms`. Korelacja przy najlepszym przesunięciu była słaba/ujemna (`-0.487` i `-0.288`). Przesunięcie wymagane przez optymalizację dochodzi do granicy poszukiwania ±2 s, więc nie ma podstaw do dodawania ręcznego offsetu czasowego.

Wniosek kryterium fizycznego: pierwszego zakrętu nie przechodzi nawet znak. Nie można uznać, że CF `.98` mierzy przechył roweru.

## 7. Prosta i low-speed

| Fragment | Mean lean | Stddev | Drift |
|---|---:|---:|---:|
| Prosty `125–140 s` | `-0.666°` | `1.338°` | `+0.056°/s` |
| Low-speed `38–48 s` | `-8.092°` | `1.502°` | — |

Prosta jest względnie blisko zera, ale low-speed ma duży offset mimo małej prędkości (`0.502 km/h`). To dodatkowo ogranicza wiarygodność offsetu montażu.

## 8. 199 Hz vs 20 Hz

| Nominalna częstotliwość | Próbki | RMSE względem pełnego przebiegu | Maks. błąd |
|---:|---:|---:|---:|
| `199 Hz` | `35 855` | `0°` | `0°` |
| `20 Hz` | `3 604` | `1.18°` | `15.91°` |

20 Hz pozostaje preferowanym wariantem prototypowym, ale maksymalny błąd pokazuje, że krótkie transienty mogą zostać utracone.

## 9. Jednostka ACCL

Ponowna kontrola extractora potwierdza: GPMF ma raw order `ZXY`, a TeleM wystawia kanoniczne `X=raw[1]`, `Y=raw[2]`, `Z=raw[0]`. Metadata ACCL deklaruje `m/s`, natomiast obserwowana mediana normy wynosi około `10.415`, czyli zachowuje się jak fizyczne `m/s²` przy `g=9.80665`.

**Runtime interpretation: `m/s²`; metadata label inconsistent.** Parsera nie zmieniano.

## 10. Asset przyszłego widgetu

Plik `wzor/rower_ico.png` istnieje. Nie był modyfikowany ani używany w tym etapie. Pozostaje referencyjnym assetem dla przyszłego widgetu Bike Lean.

## 11. Performance

Cały offline helper wraz z ekstrakcją, dwoma referencjami GPS, porównaniem osi, filtrami i wykresem: około `3.57 s` na tej próbce. To koszt diagnostyki jednorazowej, nie benchmark runtime renderowania.

## 12. Testy

Uruchomiono wyłącznie:

```text
python -m py_compile scratch/etap8h_lean_calibration.py
python -m pytest -q tests/test_etap4d_imu.py tests/test_gpmf_timing.py
9 passed
```

Nie uruchamiano pełnego suite. NVIDIA path preserved statically; runtime validation was not possible on this AMD machine.

## 13. Zmienione pliki i zachowane ścieżki

Dodano tylko:

- `scratch/etap8h_lean_calibration.py` — izolowany helper offline;
- `Raporty/ETAP8H_LEAN_GPS_CALIBRATION.png` — jeden wykres diagnostyczny;
- ten raport.

Nie zmieniano `src/*`, `presets/*`, `wzor/rower_ico.png`, resolvera, `frame_data`, precompute, GUI, rendererów, ścieżek AMD/NVIDIA, Compass, Slope ani Track-Up Map.

## 14. Final decision

**LEAN CALIBRATION: NOT RELIABLE**

Nie ma jednoznacznej osi/konwencji znaku spełniającej oba zakręty. Nie wdrażać Lean do produkcji i nie implementować jeszcze widgetu. Następny krok powinien być kontrolowanym testem z ustalonym montażem kamery/IMU, znanym lewo/prawo oraz niezależną referencją przechyłu.
