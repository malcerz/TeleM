# TeleM — ETAP 8B: derived GPS Heading / Course Over Ground

Data raportu: 2026-08-21.

## 1. Zakres zmian

Dodano wspólne, kanoniczne pole telemetryczne `heading`, oznaczające GPS-derived Course Over Ground. Etap nie implementuje Compass, Track-Up Map, Slope ani Lean.

## 2. Miejsce implementacji

Matematyka i derived stream znajdują się w `src/telemetry_heading.py`. Podpięcie do źródeł wykonuje `TelemetryDataManager`; source-aware resolver jest w `src/telemetry_resolver.py`. Interpolacja CPU i worker cache korzysta ze specjalnej semantyki tylko dla `heading`. Precompute zapisuje gotową wartość w rekordzie klatki i wystawia ją przez istniejący `extra_indicators`.

## 3. Kontrakt pola `heading`

- GPS course over ground, względem geograficznej północy true/geographic north;
- 0° = North, 90° = East, 180° = South, 270° = West;
- zakres `[0, 360)`; wartość 360° jest normalizowana do 0°;
- nie jest to heading magnetyczny, yaw kamery, yaw roweru ani orientacja urządzenia;
- jednostka logiczna: stopnie.

## 4. Algorytm bearingu

Użyto geodezyjnego wzoru `atan2` z różnicą długości geograficznej w radianach, a następnie normalizacji modulo 360. Nie użyto płaskiego `atan2(delta_lon, delta_lat)`.

Derived heading jest causalny: dla punktu `t` używa tylko GPS `<= t`. Przyrosty są akumulowane wstecz do baseline oddalonego o minimalny dystans. Obsługiwane są brakujące współrzędne, nieciągłość czasu i nienaturalny skok pozycji; duży skok resetuje bieżący baseline.

## 5. Wybrany minimalny dystans

Wybrano **5 m**. Jest to najszybsza reakcja HUD, a baseline dystansowy usuwa jitter 10 Hz. Diagnostyka na GPMF `GX030120`, przy wybranym smoothingu 2 s:

| minimum | GPMF heading 20 s | 60 s | 120 s | valid próbek |
|---:|---:|---:|---:|---:|
| 5 m | 324,17° | 27,04° | 0,54° | 1795 |
| 7,5 m | 329,31° | 20,75° | 1,81° | 1792 |
| 10 m | 332,69° | 17,17° | 3,03° | 1788 |

5 m najlepiej zachowuje responsywność; większe wartości zwiększają opóźnienie baseline.

## 6. Wybrany max lookback

Wybrano **5 s**. Na ciągłym materiale `GX030120` warianty 3/5/10 s dały identyczne wartości i 1795 valid próbek. 5 s jest środkowym limitem i nie pozwala używać bardzo starego punktu przy wolnej jeździe.

## 7. Wybrany próg prędkości

Wybrano **1 km/h**. Warianty 1/2/3 km/h miały na tym klipie 1795 valid próbek, ponieważ materiał jest niemal cały czas w ruchu. Poniżej progu nie powstaje nowy losowy kierunek: jest utrzymywany ostatni valid heading, a przed pierwszym valid headingiem zwracane jest `None`.

## 8. Smoothing

Wybrano **circular smoothing 2 s**. Smoothing wykonuje średnią wektorową `cos/sin` z próbek przeszłych, więc nie ma błędu 359°/1° → 180°.

Porównanie GPMF dla 5 m / 5 s / 1 km/h:

| smoothing | 20 s | 60 s | 120 s |
|---:|---:|---:|---:|
| 0 s | 306,15° | 44,54° | 352,56° |
| 1 s | 315,19° | 40,88° | 357,07° |
| 2 s | 324,17° | 27,04° | 0,54° |
| 5 s | 335,72° | 18,44° | 9,47° |

2 s stabilizuje prostą i nadal reaguje na zakręt; 5 s jest wyraźnie bardziej opóźnione.

## 9. Circular interpolation

Dodano `interpolate_heading` oraz wektorową wersję w precompute. Interpolacja 359° → 1° idzie przez 0°, nie przez 180°. Test midpoint 50% zwraca 0°; analogicznie działa 1° → 359°.

## 10. GPMF integration

`TelemetryDataManager` tworzy `heading_samples` z własnego GPMF GPS tracku. Dla `GX030120` użyto 1802 punktów GPS, nominalnie 10 Hz. Heading nie korzysta z ACCL ani GYRO.

## 11. FIT integration

`load_fit` tworzy analogiczny stream z własnego `fit_gps_track` i zapisuje go jako `fit_data["heading"]`. Źródłem kontrolnym był wyłącznie `Video/Poranna_jazda_na_rowerze.fit`; nie użyto niedopasowanego `Popoludniowa_jazda_na_rowerze_solar_battery.fit`.

## 12. GPX status

Parser GPX został podpięty do tego samego helpera przez `gpx_heading_samples`, bez zmiany parsera. W repozytorium nie ma rzeczywistego pliku GPX, więc GPX nie ma runtime validation.

## 13. Diagnostyka 20/60/120 s

Wartości produkcyjne: 5 m, 5 s, 1 km/h, smoothing 2 s.

| t | GPMF heading |
|---:|---:|
| 20 s | 324,17° |
| 60 s | 27,04° |
| 120 s | 0,54° |

Są logicznie zgodne z trajektorią, ale nie muszą być identyczne z centered diagnostic z ETAPU 8A, ponieważ produkcja jest causalna.

## 14. GPMF vs matched FIT

Porównanie wykonano na wspólnych timestampach z dopasowanym `Poranna_jazda_na_rowerze.fit`; różnica jest shortest circular angle.

| t | GPMF | FIT | różnica circular |
|---:|---:|---:|---:|
| 20 s | 324,17° | 324,34° | 0,17° |
| 60 s | 27,04° | 24,68° | 2,36° |
| 120 s | 0,54° | 2,02° | 1,48° |

## 15. Zakręt / responsywność

W okolicy 58,5–61,2 s finalny heading zmienił się z 4,58° do 42,45°; raw causal bearing w tym samym fragmencie wynosił odpowiednio 12,84°, 28,52°, 39,65°, 44,45°, 44,01°, 43,68°, 41,76°, 39,31°. Smoothing 2 s nie zamraża zakrętu: zmiana 58,9–60,9 s wyniosła około 35,8°.

W materiale występuje również przejście przez okolice 360°; poprawność wrap jest dodatkowo zabezpieczona testem jednostkowym.

## 16. Low-speed behavior

Najniższa dostępna prędkość GPMF wyniosła około 0,108 km/h przy 42,9 s. Heading pozostawał wtedy stabilny na około 350,49° w sąsiednich próbkach. Fixture jednostkowy potwierdza `None` przed pierwszym valid headingiem i utrzymanie ostatniej wartości po zejściu poniżej progu.

## 17. Source isolation

Resolver korzysta z dokładnie wybranego źródła: GPMF → `heading_samples`, FIT → `fit_data["heading"]`, GPX → `gpx_heading_samples`. Test kontrolowany potwierdza, że wartości 90°/270°/180° nie mieszają się między źródłami.

## 18. CPU vs AMD data parity

CPU `prepare_overlay_frame_data` i wspólny precomputed path zwróciły identyczne headingi dla czterech sprawdzonych klatek; różnica numeryczna wyniosła 0. AMD nie dostał specjalnego kodu headingu — korzysta z tego samego field-sample/resolver/cache path.

## 19. NVIDIA static analysis

Nie zmieniono `streaming.py`, `command_builder.py`, CUDA/NVENC ani ścieżki NVIDIA. **NVIDIA path preserved statically; runtime validation was not possible on this AMD machine.**

## 20. Performance

- derived stream: około 76 ms dla GPMF 1802 punktów i około 15 ms dla FIT 1635 punktów w pomiarze helpera;
- precompute 5400 klatek z headingiem: median około 67,2 ms;
- cache lookup: około 2,36 µs na klatkę w pomiarze 10 000 lookupów;
- bearing nie jest liczony przez skanowanie całego tracku na każdą klatkę;
- `interpolate_heading` używa indeksu czasowego `bisect`, a precompute używa jednego wektorowego indeksowania `numpy`.

## 21. Testy

- `python -m pytest -q --ignore=tests/test_fit_registration.py` → **595 passed, 17 skipped**;
- `python -m pytest -q tests/test_telemetry_heading.py` → **11 passed**;
- kompilacja `py_compile` wszystkich zmienionych modułów → OK;
- testy obejmują bearing North/East/South/West, wrap, min-distance, low-speed, no-future, gap/invalid point, source isolation i precomputed circular interpolation;
- `tests/test_fit_registration.py` nie zostało uruchomione w pełnym pakiecie, ponieważ jego kolekcja kończy się istniejącym `ModuleNotFoundError: src.gui.hud_tuner_app`; nie jest to zmiana ETAPU 8B.

## 22. Lista zmienionych plików

Zmiany ETAPU 8B:

- `src/telemetry_heading.py` — nowy wspólny helper derived heading;
- `src/gui/telemetry_manager.py` — osobne streamy GPMF/FIT/GPX i interpolacja headingu;
- `src/telemetry_resolver.py` — exact source-aware binding `heading`;
- `src/indicators/frame_data.py` — heading dependency i przekazanie przez `extra_indicators`;
- `src/telemetry_precompute.py` — cache i circular vectorized interpolation;
- `src/ffmpeg/worker_cache.py` — common worker resolution dla GPMF/GPX/FIT;
- `src/gui/qt/_mixins/render_mixin.py` — przekazanie derived streamów do wspólnego render path;
- `tests/test_telemetry_heading.py` — testy ETAPU 8B;
- `Raporty/RAPORT_INDICATORS_ETAP_8B_DERIVED_HEADING.md` — ten raport.

## 23. Remaining risks

- brak rzeczywistego pliku GPX uniemożliwia runtime validation GPX;
- runtime NVIDIA nie był dostępny na tej maszynie;
- actual GPU pixel render nie był zmieniany ani ponownie benchmarkowany, ponieważ heading jest tylko wspólną telemetrią przed rendererem;
- wartości GPS-derived COG pozostają zależne od jakości fixa i mogą być nieokreślone po dużej luce — wtedy stream wymaga ponownego baseline.

Nie zmieniono `gauge.py`, `moving_map.py`, `src/moving_map.py`, rendererów Compass/Track-Up, Slope/Lean, map parity ani ścieżek AMD/NVIDIA renderingu. Istniejące, niezwiązane zmiany w dirty worktree zostały zachowane.
