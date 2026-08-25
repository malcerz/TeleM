# TeleM — ETAP 9A: finalny audyt wizualny dashboardu v6

Data: 2026-08-22  
Zakres: **AUDYT ONLY** — bez zmian w `src/*`, presetach i assetach.

## 1. Materiał i referencja

Audyt wykonano na:

- `Video/GX030120.MP4`;
- `Video/GX030120.json`;
- `Video/Poranna_jazda_na_rowerze.fit`;
- `presets/cycling_dashboard_v6.json`;
- klatka kontrolna: `Raporty/INDICATORS_ETAP_9A_CURRENT_V6.png`.

W `wzor/` znajduje się pełny screenshot referencyjny: `wzor/00000.png` (3840×2160). Jest to główna referencja wizualna. `wzor/rower_ico.png` również istnieje i pozostaje assetem przyszłego Lean.

## 2. Aktualny layout v6

Współrzędne `x/y` są wartościami z presetu w procentach. Bbox podano jako przybliżenie w pikselach dla 3840×2160, zgodnie z geometrią formy; dla tekstu rzeczywisty bbox zależy od długości wartości.

| Widget | x | y | size | bbox px | forma |
|---|---:|---:|---:|---:|---|
| `time_display` | 2.0 | 2.0 | — | `(77, 43)–(540, 220)` | blok tekstowy |
| `dist_visual` | 50.0 | 96.5 | 30.0 | `(1344, 2050)–(2496, 2150)` | poziomy ruler |
| `fit_battery_pct_text` | 88.0 | 6.5 | 12.0 | `(3225, 90)–(3685, 220)` | segment bar |
| `fit_solar_text` | 88.0 | 17.0 | 12.0 | `(3225, 320)–(3685, 450)` | segment bar |
| `track_map` | 86.0 | 38.0 | 20.0 | `(2918, 410)–(3686, 1178)` | kwadratowa mapa |
| `compass` | 70.65 | 20.0 | 7.8 | `(2564, 282)–(2863, 581)` | okrągły gauge |
| `slope_text` | 68.0 | 53.0 | 20.0 | `(2550, 760)–(2850, 1740)` | pionowy slope bar |
| `iso_text` | 22.0 | 7.5 | 9.0 | `(845, 145)–(1060, 205)` | tekst |
| `exposure_text` | 30.0 | 7.5 | 9.0 | `(1152, 145)–(1400, 205)` | tekst |
| `temp_text` | 38.0 | 7.5 | 9.0 | `(1459, 145)–(1710, 205)` | tekst |
| `alt_visual` | 5.5 | 52.0 | 16.0 | `(110, 810)–(300, 1430)` | pionowy ruler |
| `fit_curVpower_text` | 56.0 | 12.0 | 18.0 | `(1805, 260)–(2496, 335)` | poziomy ruler |
| `fit_cadence_text` | 24.0 | 85.0 | 27.0 | `(500, 1650)–(1537, 2150)` | chart |
| `fit_enhanced_speed_text` | 50.0 | 53.0 | 17.3 | `(1588, 775)–(2252, 1439)` | centralny gauge |
| `fit_heart_rate_text` | 59.0 | 85.0 | 27.0 | `(1843, 1650)–(2880, 2150)` | chart |

### Z-order

Kolejność wpisów presetowych, a więc kolejność audytowana: `time_display → dist_visual → battery → solar → track_map → compass → slope → ISO → shutter → temperature → altitude → virtual power → cadence chart → speed gauge → HR chart`.

## 3. Hierarchia wizualna

| Widget/grupa | Rozmiar | Siła wizualna | Ocena |
|---|---|---|---|
| Speed gauge | GOOD | TOO DOMINANT | centralny, ale za dużo pustej przestrzeni wokół |
| Track-Up Map | TOO LARGE | TOO DOMINANT | prawa krawędź i mapa przyciągają wzrok mocniej niż centralny speed |
| HR chart | GOOD | TOO DOMINANT | duża czerwona plama i wysoki kontrast |
| Cadence chart | GOOD | GOOD | para z HR, lecz oba są zbyt nisko |
| Compass | GOOD | TOO WEAK | cienki ring, odseparowany od reszty HUD |
| Slope | TOO LARGE | TOO DOMINANT | pionowy element konkuruje z mapą i gauge’em |
| Top telemetry | TOO SMALL / rozproszony | TOO WEAK | za dużo pustej przestrzeni między grupami |
| Time/date | GOOD | GOOD | czytelny, ale font nie odpowiada referencji segmentowej |
| Distance | TOO SMALL | TOO WEAK | na samym dole, daleko od głównej hierarchii |
| Altitude | TOO SMALL | TOO WEAK | cienki i mało czytelny przy lewej krawędzi |

## 4. Speed Gauge

Średnica wynosi około `664 px` (`17.3%` szerokości), a położenie centralne jest poprawne funkcjonalnie. Wzorzec ma większy ciężar speed gauge’a i silniej organizuje cały dół ekranu; v6 ma zbyt dużo czerni między gauge’em a górnymi elementami. Wartość `14.8 km/h` jest czytelna, ale ticki i zakres są słabsze od wzorca przez cienką linię i duży rozrzut elementów.

Rekomendacja: najpierw preset-only — większy gauge, nieco niżej, z ciaśniejszym sąsiedztwem wykresów. **RENDERER CHANGE REQUIRED: nie stwierdzono.**

## 5. Map

Mapa ma około `768×768 px`, jest po prawej stronie i używa `track_up`, `light_all`, trasy czerwonej `2 px` oraz białego markera. Wzorzec ma mapę po lewej, jako element wspierający; v6 czyni mapę jednym z największych bloków i dodatkowo zestawia ją bezpośrednio ze Slope/Compass. Mapa jest wizualnie zbyt dominująca.

Rekomendacja: zmniejszyć do około `16–17%`, przesunąć w lewo względem obecnej osi prawej lub obniżyć opacity, zachowując Track-Up. **RENDERER CHANGE REQUIRED: nie.**

## 6. Compass

Średnica około `300 px` i tick co `15°` są czytelne. Ring jest jednak zbyt cienki względem mapy i Slope, a położenie nad mapą tworzy osobny „panel nawigacyjny”, zamiast jednej kompozycji HUD. Liczbowy heading w próbce nie był wyraźnie konkurencyjny dla ringa.

Rekomendacja: preset-only — odrobinę mniejszy ring, większa spójność koloru/outline z gauge’em i przesunięcie bliżej mapy bez kolizji.

## 7. Slope

Pionowy bar ma dużą wysokość względem pozostałych małych wskaźników. Skala `-20…+20%`, marker i etykiety są czytelne, ale widget zajmuje zbyt dużo prawego środka i konkuruje z mapą. Wzorzec traktuje slope jako wskaźnik pomocniczy.

Rekomendacja: zmniejszyć wysokość do około `14–16%`, zwęzić marker i odsunąć od mapy/speed gauge’a. **RENDERER CHANGE REQUIRED: nie.**

## 8. Cadence i HR

Oba wykresy mają `size=27`, `60 s` window, line width `2`, grid i fill alpha `65`. Są symetryczne szerokością, ale v6 umieszcza je zbyt nisko; dolne etykiety i ruler dystansu ściskają się przy dolnej krawędzi. HR przez czerwony fill jest znacznie cięższy niż żółty Cadence. Wzorzec ma oba wykresy jako równorzędną parę.

Rekomendacja: podnieść oba wykresy, zachować szerokość, zmniejszyć fill alpha HR do około `40–50`, ujednolicić line width i odstęp od dolnej krawędzi. 60 s jest właściwym oknem dla obecnego zadania.

## 9. Top strip

Time/date/activity znajduje się przy lewej krawędzi i jest czytelny. ISO, Shutter i Temp są ustawione w jednej linii, lecz mają zbyt duże przerwy. Virtual Power jest niżej i nie tworzy z nimi logicznej grupy. Battery/Solar są po prawej, poza naturalnym ciągiem top telemetry.

W klatce v6 wartości Battery/Solar nie tworzą pełnej wizualnej grupy, ponieważ źródło FIT nie dostarcza poprawnego solar field. To problem danych, nie geometrii.

## 10. Distance

Ruler przy `y=96.5%` ma około `1152 px` szerokości, jest cienki i odseparowany od chartów. Wzorzec eksponuje dystans wyżej i centralniej, jako jeden z głównych odczytów. Obecny `label=false` osłabia semantykę; zakresy są czytelniejsze niż sama wartość.

## 11. Altitude

Pionowy ruler po lewej ma około `620 px` wysokości, ale małą szerokość i mały tekst. Jest poprawnie odsunięty od mapy, lecz wizualnie ginie na czarnym tle. Wymaga przede wszystkim zwiększenia font/value marker, nie przebudowy renderera.

## 12. Typografia

| Widget | Obecny font/scale | Ocena | Proponowana zmiana v7 |
|---|---:|---|---:|
| time/date | date 1.2, time 1.9, activity 1.5 | GOOD | bez zmiany lub +10% date |
| ISO/Shutter/Temp | 1.4 | TOO WEAK | +10% |
| virtual power | 1.2, value .9 | TOO WEAK | value +15%, label +10% |
| Compass | 1.2 | GOOD | +10% heading, ring bez zmiany |
| Slope | 1.35 | GOOD | bez zmiany, zmniejszyć geometrię |
| Speed gauge | 2.0 | GOOD | value +10% |
| Cadence/HR | 1.2 | TOO WEAK | +10% etykiet |
| Distance | range .75, value .9 | TOO WEAK | value +15% |
| Altitude | 1.2 | TOO WEAK | +15% |

Nie rekomenduję globalnej zmiany typografii. Największą różnicę dadzą: top telemetry `+10%`, wartość distance/altitude `+15%`, speed value `+10%`.

## 13. Linie, outline i opacity

W v6 mieszają się cienkie szare ticki, białe ticki Compass/gauge’a oraz mocne czerwone fill/marker. Najbardziej „z innej aplikacji” wygląda Slope: jasny pionowy bar i marker mają większą obecność niż delikatny Compass. HR fill jest cięższy niż Cadence fill. W pierwszej kolejności należy ujednolicić presetowe `line_width`, `fill_alpha`, `tick_width` i marker opacity; globalnego outline nie zmieniać.

## 14. Kolizje i marginesy

Przybliżone najmniejsze odstępy w klatce 3840×2160:

| Para | Odstęp | Ocena |
|---|---:|---|
| Compass ↔ map | około `55 px` | akceptowalny, ale wizualnie zbyt ciasny przez wspólną grupę |
| Compass ↔ virtual power | około `450 px` pionowo | za duża pusta przestrzeń |
| Slope ↔ speed gauge | około `90 px` | akceptowalny geometrycznie, słaby hierarchicznie |
| Slope ↔ HR chart | około `0–20 px` | za ciasno przy dolnym przejściu |
| speed gauge ↔ charts | około `200 px` | za duża pusta przestrzeń |
| map ↔ prawa krawędź | około `150 px` | poprawne, ale mapa jest optycznie przyklejona do krawędzi |
| charts ↔ dolna krawędź | około `10 px` | za mały margines |

Najpilniejsze są dolny margines chartów, Slope↔HR oraz optyczna grupa Compass↔map.

## 15. Elementy brakujące względem wzorca

Rzeczywiście brakujące lub niepełne:

- Bike Lean — **DEFERRED — requires controlled IMU calibration**; nie jest błędem v6;
- pełna, poprawna wartość Solar — **DATA SOURCE UNRESOLVED**;
- bardziej zwarta organizacja top strip i głównego dystansu — różnica layoutowa, nie brak danych.

`wzor/rower_ico.png` potwierdzony, ale nie powinien być używany przed zakończeniem kalibracji Lean.

## 16. Solar

Preset używa `fit_solar_text`, `source=fit`, zakresu `0–10 W`. W dostępnych polach FIT nie ma potwierdzonego poprawnego solar field. Nie mapuję arbitralnie battery ani innego pola do Solar.

Status: **DATA SOURCE UNRESOLVED**. Wizualne miejsce jest sensowne jako segment bar pod Battery, ale wartość nie jest obecnie wiarygodna.

## 17. Top 10 zmian do ETAPU 9B

| # | Priorytet | Zmiana | Klasyfikacja |
|---:|---|---|---|
| 1 | HIGH | przenieść/zmniejszyć mapę, aby nie dominowała prawej strony | PRESET ONLY |
| 2 | HIGH | podnieść i odsunąć od krawędzi oba wykresy | PRESET ONLY |
| 3 | HIGH | zwiększyć wizualny priorytet dystansu i przenieść go nad wykresy | PRESET ONLY |
| 4 | HIGH | zmniejszyć Slope i odseparować go od HR/mapy | PRESET ONLY |
| 5 | MEDIUM | zgrupować Battery/Solar/top telemetry | PRESET ONLY |
| 6 | MEDIUM | ujednolicić fill alpha HR/Cadence | PRESET ONLY |
| 7 | MEDIUM | zwiększyć font ISO/Shutter/Temp o 10% | PRESET ONLY |
| 8 | MEDIUM | zwiększyć wartość Altitude/Distance o 15% | PRESET ONLY |
| 9 | LOW | zmniejszyć pustą przestrzeń między Compass, Power i speed gauge | PRESET ONLY |
| 10 | LOW | dopracować tick/marker opacity bez zmiany renderera | PRESET ONLY |

Liczba zmian `PRESET ONLY`: **10**. Liczba zmian wymagających renderera: **0**.

## 18. Dokładny plan v6 → v7

| Widget | Property | v6 | Proponowane v7 |
|---|---|---:|---:|
| `track_map` | `x` | 86.0 | 82.0 |
| `track_map` | `y` | 38.0 | 34.0 |
| `track_map` | `size` | 20.0 | 16.5 |
| `track_map` | `opacity` | brak | 0.88, jeśli obsługiwane presetowo |
| `slope_text` | `x` | 68.0 | 70.0 |
| `slope_text` | `y` | 53.0 | 58.0 |
| `slope_text` | `size` | 20.0 | 15.0 |
| `fit_cadence_text` | `y` | 85.0 | 82.0 |
| `fit_heart_rate_text` | `y` | 85.0 | 82.0 |
| `fit_heart_rate_text` | `fill_alpha` | 65 | 45 |
| `dist_visual` | `y` | 96.5 | 78.0 |
| `dist_visual` | `size` | 30.0 | 28.0 |
| `dist_visual` | `value_font_scale` | .9 | 1.05 |
| `alt_visual` | `font_size` | 1.2 | 1.38 |
| `fit_enhanced_speed_text` | `size` | 17.3 | 18.5 |
| `fit_enhanced_speed_text` | `font_size` | 2.0 | 2.2 |
| `iso_text` | `font_size` | 1.4 | 1.54 |
| `exposure_text` | `font_size` | 1.4 | 1.54 |
| `temp_text` | `font_size` | 1.4 | 1.54 |
| `fit_curVpower_text` | `value_font_scale` | .9 | 1.04 |
| `compass` | `size` | 7.8 | 7.2 |

Wartości `opacity` należy zastosować tylko jeżeli dana właściwość jest już obsługiwana przez preset; nie dodawać nowej semantyki danych w tym etapie.

## 19. Zmiany preset-only vs renderer/data

Wszystkie 10 pozycji rankingu można najpierw wykonać jako `PRESET ONLY`. Audyt nie wykazał konieczności `SMALL RENDERER CHANGE`. Solar jest `DATA CHANGE`, ale pozostaje poza zakresem 9A i nie powinien być rozwiązywany przez zmianę layoutu. Lean również pozostaje poza zakresem.

## 20. Walidacja i kontrola repo

Wykonano:

- load JSON v6 i normalizację layoutu dla 3840×2160;
- load istniejącego materiału GPMF/FIT;
- jedną klatkę CPU przy `video_time≈60 s`;
- kontrolę obecności `wzor/00000.png` i `wzor/rower_ico.png`;
- `git diff --check`.

Nie uruchamiano pełnego suite 600+ testów. Nie zmieniano produkcyjnego kodu, `presets/cycling_dashboard_v6.json` ani `wzor/rower_ico.png`. NVIDIA path preserved statically; runtime validation was not relevant to this audit and was not performed on this AMD machine.
