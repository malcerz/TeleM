# TeleM — ETAP 8A: audyt źródeł danych Compass, Slope, Bike/Lean i Track-Up Map

Data audytu: 2026-08-21. Audyt wykonano na aktualnym stanie repozytorium. W tym etapie nie dodano implementacji produkcyjnej, zmian parserów, resolvera, renderera ani presetów.

## 1. Materiał

Materiał podstawowy:

- `Video/GX030120.MP4`
- `Video/GX030120.json` — eksport GPMF/ExifTool; 1 rekord kontenera, 26 305 wpisów pól, klip GPS od `2026-08-18 04:46:25.700 UTC` do `04:49:25.800 UTC` (180,1 s).
- `Video/Popoludniowa_jazda_na_rowerze_solar_battery.fit` — 1754 rekordy, 13:00:33–14:01:04 w czasie zapisanym w FIT.

Materiały dodatkowe FIT:

- `Video/Poranna_jazda_na_rowerze.fit` — 1672 rekordy; ten plik przechodzi SmartSync z GPMF dla `GX030120`: offset 0 s, 121/121 punktów, mediana błędu 3,3 m, P90 4,5 m.
- `Video/Morning_Ride.fit` — 1704 rekordy; brak potwierdzonego dopasowania trajektorii do `GX030120`.

Nie znaleziono żadnego pliku `*.gpx` w repozytorium. Kod parsera GPX został zinwentaryzowany statycznie, ale nie było rzeczywistego GPX do pomiaru.

Ważne rozróżnienie: wskazany w briefie FIT `Popoludniowa...` po fallbacku strefy czasowej (`-9 h`) nie uzyskał potwierdzenia trajektorii z GPMF. `Poranna...` jest na tym materiale właściwym dopasowanym FIT-em referencyjnym. Wnioski poniżej rozdzielają dostępność pola od pewności skojarzenia źródła z klipem.

## 2. FIT field inventory

Parser `telemetry_fit.py` (`parse_fit`, `sync_fit_to_video`) odczytuje dynamicznie wszystkie numeryczne pola z wiadomości `record`. Pola GPS `position_lat`/`position_long` są konwertowane do `lat`/`lon`, `enhanced_speed`/`speed` do `speed` w km/h, a wysokość do `alt` w metrach. Synchronizacja dodaje również pochodny `track` — dystans kumulowany w metrach.

| Pole / grupa | Źródło | Typ | Jednostka w TeleM/FIT | Nominalne próbkowanie | Używane obecnie? |
|---|---|---|---|---:|---|
| `timestamp` | FIT | czas | UTC/naive UTC po parserze | 1 Hz | tak, oś czasu |
| `lat`, `lon` | FIT `position_lat/long` | float | stopnie dziesiętne | 1 Hz, 1707 punktów w pliku `Popoludniowa...` | tak, mapa/FIT track |
| `speed`, `enhanced_speed` | FIT `speed`, `enhanced_speed` | float | km/h po konwersji z m/s | nominalnie 1 Hz; odpowiednio 1676/1750 próbek w głównym FIT | tak |
| `alt`, `enhanced_altitude` | FIT `altitude`, `enhanced_altitude` | float | m | 1 Hz, 1754 próbek | tak |
| `track` | derived z `lat/lon` | float | m, dystans kumulowany | 1 Hz; 1707 próbek | tak |
| `distance` | FIT vendor/device field | float | FIT-native, semantyka dystansu | 1 Hz, 1754 | dynamiczne FIT, nie jako standardowy `track` |
| `heart_rate` | FIT | float | BPM | 1 Hz, 1754 | dynamiczne FIT |
| `cadence`, `fractional_cadence` | FIT | float | rpm / FIT-native | 1 Hz, po 1741 próbek | dynamiczne FIT |
| `curVpower` | FIT vendor field | float | FIT/device-native; brak jawnego mapowania jednostki w parserze | 1 Hz, 1754 | dynamiczne FIT |
| `temperature` | FIT | float | °C w materiale | 1 Hz, 1754 | dynamiczne FIT |
| `battery_pct`, `solar_pct` | FIT vendor fields | float | % | 1 Hz, 1754 | dynamiczne FIT |
| `passing_speed`, `passing_speedabs`, `radar_current` | FIT vendor fields | float | nieustalone w kodzie parsera | ok. 1 Hz, po 1752 próbek | dynamiczne FIT |
| `K1`, `K2` | FIT vendor/developer fields | float | nieustalone | ok. 1 Hz, po 1753 próbek | dynamiczne FIT |

Wszystkie trzy dostępne FIT-y mają `alt`, `enhanced_altitude`, `distance`, GPS, speed, HR, cadence i temperaturę. Żaden nie ma pola o nazwie ani znaczeniu `heading`, `course`, `bearing`, `grade`, `slope`, `incline`, `roll`, `pitch`, `yaw` ani quaternionu. `Poranna_jazda_na_rowerze.fit` ma dodatkowo `passing_speed`, `passing_speedabs`, `radar_current`; `Morning_Ride.fit` ma `gopro_battery`; główny FIT ma ponadto `battery_pct` i `solar_pct`.

## 3. GPMF field inventory

W `GX030120.json` występują kanały GPS, speed, altitude, camera telemetry, ISO/exposure oraz ruchowe bloki GPMF. Dla kanałów ruchowych rzeczywista inwentaryzacja jest następująca:

| FourCC / pole | Znaczenie audytowe | Hz | Komponenty | Jednostka | Parser TeleM |
|---|---|---:|---:|---|---|
| `ACCL` | trójosiowy akcelerometr | 198,69 | 3 | `m/s` według `ACCL_Unit` | TAK: `extract_accelerometer_samples` |
| `ACCL_STMP`, `ACCL_TSMP`, `ACCL_SampleCount` | czas bloku i licznik próbek ACCL | razem z ACCL | — | GPMF stream timing | TAK, używane do rekonstrukcji czasu |
| `ACCL_Components`, `ACCL_ORIN`, `ACCL_ORIO`, `ACCL_Unit` | metadane osi/formatu ACCL | razem z ACCL | — | `ORIN=ZXY` | częściowo TAK, mapping osi jest stosowany |
| `GYRO` | trójosiowy żyroskop | 198,69 | 3 | `rad/s` według `GYRO_Unit` | TAK: `extract_gyroscope_samples` |
| `GYRO_STMP`, `GYRO_TSMP`, `GYRO_SampleCount` | czas bloku i licznik próbek GYRO | razem z GYRO | — | GPMF stream timing | TAK |
| `GYRO_Components`, `GYRO_ORIN`, `GYRO_ORIO`, `GYRO_Unit` | metadane osi/formatu GYRO | razem z GYRO | — | `ORIN=ZXY` | częściowo TAK |
| `GPSDateTime`, `GPSLatitude`, `GPSLongitude` | pozycja i czas GPS | 10,0 | — | stopnie / UTC | TAK |
| `GPSAltitude` | wysokość GPS | 10,0 | — | m w materiale | TAK |
| `GPSSpeed`, `GPSSpeed3D` | prędkość GPS | 10,0 | — | km/h według istniejącego kodu | TAK |
| `GPSDOP`, `GPSFix` | jakość/status fixa | 10,0 | — | FIT/GPMF-native | obecne w surowym JSON, nie są obecnie wystawione jako standardowe pola wskaźnika |
| `TMPC_ACCL_Value`, `TMPC_GYRO_Value` oraz timing `TMPC_*` | kanały pomocnicze temperatury/timingu powiązane ze strumieniami | 10,0 / blokowo | — | nie jest to orientacja | używane tylko w zakresie obsługi temperatury/timingu |

W `GX030120` jest 180 bloków ACCL i 180 bloków GYRO, po 198–199 próbek każdy, łącznie po 35 802 próbki. Nie znaleziono kluczy `GRAV`, `QUAT`, `CORI`, `IORI`, `ORIE`, `YAW`, `PITCH`, `ROLL`, `HEADING` ani `COMPASS`. Nie ma zatem w tym materiale surowego, nieparsowanego kanału orientacji, który można by po prostu dopiąć do resolvera.

## 4. GPX field inventory

Brak rzeczywistego `*.gpx` w repozytorium.

Statycznie parser `telemetry_gpx.py` obsługuje:

- standardowe `trkpt@lat`, `trkpt@lon`, `time`, `ele`,
- extensions: `power`, `atemp`, `hr`, `cad`,
- namespace’y `gpxtpx`, `gpxx`, `power` oraz wyszukiwanie po lokalnej nazwie taga.

Parser synchronizuje z GPX: speed derived z kolejnych pozycji, cumulative track, altitude, power, temperature, HR i cadence. Brak implementacji bezpośredniego heading/course/grade/lean. Częstotliwość i rzeczywiste extensions GPX: niezmierzalne dla repozytorium bez pliku GPX.

## 5. Heading candidates

Nie znaleziono bezpośredniego heading/course/bearing:

- FIT: brak pola bezpośredniego; `track` oznacza dystans kumulowany, nie kierunek.
- GPMF: brak pola heading/course/bearing oraz brak magnetometru/orientacji absolutnej.
- GPX: parser nie ma pola heading, a rzeczywistego GPX brak.
- camera metadata: w zbadanym JSON są GPS i IMU, ale nie ma absolutnego headingu.

Najlepszy kandydat to **course over ground z kolejnych GPS lat/lon**. Jest to kierunek ruchu, nie yaw urządzenia, nie heading magnetyczny i nie heading true z kompasu. Wzrost kąta należy normalizować do `0..360°`, gdzie 0° oznacza północ geograficzną:

```text
dlon = lon2 - lon1
x = sin(dlon) * cos(lat2)
y = cos(lat1) * sin(lat2) - sin(lat1) * cos(lat2) * cos(dlon)
bearing = atan2(x, y) w stopniach, następnie (bearing + 360) mod 360
```

Przyszły derived heading powinien używać kołowego smoothingu przez średnią wektorową `sin/cos`, ignorować próbki przy prędkości bliskiej zeru oraz aktualizować się dopiero po minimalnym dystansie, np. 5–10 m. Wrap `359° → 0°` nie może być traktowany jako skok liniowy.

## 6. GPS-derived heading analysis

`GX030120` ma 1802 punkty GPS co 0,1 s, czyli nominalnie 10 Hz. GPMF jest więc dobrym źródłem headingu dla tego klipu, bo ma tę samą oś czasu co video. FIT jest nominalnie 1 Hz.

SmartSync potwierdził, że `Poranna_jazda_na_rowerze.fit` opisuje tę samą trajektorię: mediana odległości 3,3 m i P90 4,5 m w pełnym oknie porównawczym. Dla głównego `Popoludniowa...` SmartSync nie znalazł dopasowania trajektorii i użył fallbacku strefy czasowej; ten plik nie powinien być bez dodatkowej walidacji źródłem pozycji dla `GX030120`.

Typowy dystans między próbkami GPMF zależy od prędkości, ale przy 10 Hz jest wielokrotnie większy niż szum pojedynczego punktu tylko podczas jazdy. Przy małej prędkości lub postoju bearing należy zamrozić i nie wyliczać z kolejnych niemal identycznych pozycji. Stabilność rośnie przy oknie czasowym 5–10 s albo minimalnym dystansie 5–10 m.

## 7. Heading diagnostic values

Wartości poniżej liczone offline. Dla GPMF użyto centered bearing z oknem 5 s; dla dopasowanego FIT `Poranna...` również 5 s. Bezpośredni heading: brak.

| t [s] | GPMF lat | GPMF lon | GPMF speed km/h | GPMF COG 5 s | FIT `Poranna` lat | FIT `Poranna` lon | FIT speed km/h | FIT COG 5 s |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 20 | 54.347387 | 18.643310 | 11.556 | 317,93° | 54.347383 | 18.643255 | 13.281 | 315,97° |
| 60 | 54.347701 | 18.643111 | 17.424 | 16,01° | 54.347706 | 18.643057 | 14.850 | 15,58° |
| 120 | 54.351914 | 18.642460 | 16.992 | 5,23° | 54.351933 | 18.642413 | 23.063 | 6,14° |

Wynik: kierunek GPS z obu zgodnych źródeł jest zbliżony, mimo różnic prędkości i filtracji. Dla `GX030120` preferowany jest GPMF 10 Hz; FIT może służyć jako kontrola jakości, jeśli SmartSync potwierdzi trajektorię.

## 8. Slope candidates

Nie znaleziono bezpośredniego `grade`, `slope`, `incline` ani odpowiednika w FIT, GPMF lub parserze GPX. Istnieją natomiast:

- `enhanced_altitude` i `alt` w FIT,
- `distance` w FIT oraz derived `track` z GPS,
- `GPSAltitude` i derived `track` w GPMF,
- `enhanced_speed`/speed jako pomocnicza informacja o ruchu.

Najbardziej wiarygodny kandydat dla dopasowanego FIT to `enhanced_altitude` + `track`/`distance`, nie chwilowe `GPSAltitude`. Dla samego `GX030120` GPMF ma tę samą oś czasu, ale jego GPS altitude jest bardziej zaszumione i wymaga okna dystansowego oraz dodatkowej oceny znaku/offsetu wysokości.

## 9. Derived slope analysis

Offline stosowano:

```text
grade[%] = 100 * (height2 - height1) / (distance2 - distance1)
```

Na rowerze sensowny jest filtr po dystansie, ponieważ tempo próbkowania i prędkość zmieniają się, a filtr czasowy daje różną długość odcinka. Kandydaci 5 m, 10 m i 20 m pokazują kompromis:

- 5 m: szybka reakcja, ale duża wrażliwość na wysokość i GPS;
- 10 m: dobry kompromis dla jazdy ciągłej;
- 20–30 m: stabilniejszy odczyt do HUD, większe opóźnienie i wygładzenie.

Dla pierwszego wdrożenia rekomendowane jest okno 10–20 m, z ochroną przed zbyt małym dystansem i z osobnym warunkiem braku danych. Nie należy liczyć slope w rendererze; derived stream powinien powstać przed frame data.

## 10. Slope diagnostic values

Poniżej porównano matched FIT `Poranna...` (bardziej wiarygodna wysokość, 1 Hz) z GPMF (ta sama oś czasu video, ale GPS altitude). Wartości to procenty; `raw` dla GPMF oznacza sąsiednią próbkę, a pozostałe kolumny są filtrem dystansowym.

| t [s] | FIT 5 m | FIT 10 m | FIT 20 m | GPMF raw | GPMF 5 m | GPMF 10 m | GPMF 20 m |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 20 | +8,50 | +9,39 | +7,67 | -17,52 | -0,95 | -0,66 | -4,87 |
| 60 | -0,74 | -1,70 | -2,00 | -7,50 | -1,88 | -2,69 | -2,86 |
| 120 | 0,00 | +0,91 | +0,50 | -9,81 | +4,36 | +3,22 | +2,76 |

Wniosek: raw GPMF slope jest wyraźnie zbyt szumny. Nawet 20 m nie daje jeszcze zgodności z matched FIT, więc przed implementacją trzeba ustalić politykę źródła wysokości, filtr, minimalną prędkość/dystans i obsługę zmian źródła. Dane bazowe wystarczają do prototypu derived slope, ale nie do uznania go za gotowy bez walidacji wizualnej i terenowej.

## 11. Motion/orientation channels

W `GX030120` istnieją wyłącznie dwa właściwe kanały motion: `ACCL` i `GYRO`. Oba mają 3 komponenty i `ORIN=ZXY`. Nie ma `GRAV`, quaternionu, `CORI`, `IORI`, `ORIE`, yaw/pitch/roll ani headingu.

TeleM już rekonstruuje czas próbek z `STMP`, `TSMP` i liczby próbek bloku. Następnie `_set_vector_series` wystawia osie oraz magnitude jako `accel_x/y/z`, `accel_magnitude`, `gyro_x/y/z`, `gyro_magnitude`. Są one dostępne w resolverze GPMF.

## 12. Quaternion / gyro / accelerometer analysis

Quaternion/orientation: brak w badanym źródle; nie ma podstaw do ustalenia kolejności quaternionu, handedness ani mappingu osi. Gdyby przyszły materiał zawierał taki kanał, jego interpretacja wymagałaby weryfikacji specyfikacji GPMF — nie należy zgadywać.

Gyro-only nie jest trwałym rozwiązaniem dla lean: integracja `rad/s` dryfuje przez bias, wymaga stanu początkowego i resetu. `ACCL + GYRO` daje drogę do filtra complementary/Kalmana, ale accelerometer mierzy sumę grawitacji i przyspieszeń liniowych. W zakręcie boczne przyspieszenie może wyglądać jak zmiana przechyłu. Roll kamery nie może zostać automatycznie utożsamiony z lean roweru.

Do przyszłej fuzji trzeba uwzględnić stały kąt montażu, osie `ZXY`, stabilizację/Horizon Lock/HyperSmooth, możliwy obrót obudowy i różnicę między przechyłem kamery a przechyłem roweru. To jest plan przyszłego etapu, nie implementacja ETAP 8A.

## 13. Bike lean feasibility

**DATA:** dostępne są surowe `ACCL` i `GYRO`, już wystawione przez TeleM, około 198,69 Hz.

**Brakujące dane:** brak bezpośredniej grawitacji, quaternionu i absolutnego roll. Zatem nie ma gotowego źródła `lean_angle`.

**Ocena:** lean jest potencjalnie wyliczalny, lecz wymaga jednorazowego precompute IMU, fuzji, kalibracji montażu i walidacji dynamicznego zachowania. Sam gyro nie wystarczy. Trudność: HIGH.

## 14. Track-up feasibility

Obecny `src/moving_map.py` projektuje GPS do stałych współrzędnych kafelków Web Mercator, centruje crop na pozycji i rysuje nierotowany marker. Nie ma argumentu bearing/heading ani transformacji rastera. To jest north-up.

Technicznie najprościej w przyszłości obracać gotowy raster wokół aktualnej pozycji i wykonać powiększony crop po rotacji. Konsekwencje: większy bounding box, konieczny margines, ryzyko pustych narożników i koszt resamplingu. Obracanie samych tile’i komplikuje cache; obracanie route/marker nie obraca tła, więc nie daje pełnego track-up.

Rekomendowany model to `current course at top`: heading po smoothingu kołowym, deadband, zamrożenie ostatniego headingu poniżej minimalnej prędkości i fallback north-up, gdy nie ma wystarczającego dystansu GPS. DATA jest dostępne jako derived COG; RENDERER wymaga osobnego etapu. Trudność: MEDIUM/HIGH.

## 15. Sampling rates

| Kanał | Materiał | Liczba | Mediana interwału | Min/max interwał | Przybliżone Hz |
|---|---|---:|---:|---:|---:|
| GPMF GPS/lat/lon/speed/alt | `GX030120` | 1802 | 0,100 s | 0,100 / 0,100 s | 10,0 |
| GPMF ACCL | `GX030120` | 35 802 | 0,005033 s | 0,005032 / 0,005033 s | 198,69 |
| GPMF GYRO | `GX030120` | 35 802 | 0,005033 s | 0,005032 / 0,005033 s | 198,69 |
| FIT GPS | `Popoludniowa...` | 1707 | 1 s | 1 / 1879 s | nominalnie 1,0 |
| FIT altitude | `Popoludniowa...` | 1754 | 1 s | 1 / 1879 s | nominalnie 1,0 |
| FIT GPS/altitude | `Poranna...` | odpowiednio 1635 / 1672 rekordów wejściowych | 1 s | nominalnie 1 s | nominalnie 1,0 |
| FIT direct grade | wszystkie | 0 | — | — | brak |
| GPMF orientation/quaternion | `GX030120` | 0 | — | — | brak |

Duże maksimum interwału FIT wynika z przerwy w danym pliku; nie należy opisywać tego strumienia jako ciągłego 1 Hz bez sprawdzenia pokrycia.

## 16. Synchronization requirements

GPMF GPS, ACCL i GYRO używają wspólnego czasu bloków GPMF. Extractor rekonstruuje próbki IMU od pierwszego absolutnego GPS anchoru, rozkładając blok na `STMP`/liczbę próbek. ACCL i GYRO zaczynają się z różnicą około 1,8 ms w surowym `STMP`, ale należą do tej samej osi czasu.

SmartSync:

- `Poranna_jazda_na_rowerze.fit`: absolute-time trajectory refine, offset 0 s, dopasowanie wysokiej pewności, median 3,3 m / P90 4,5 m.
- `Popoludniowa_jazda_na_rowerze_solar_battery.fit`: `absolute_overlap=no`, timezone fallback `-9 h`, bez potwierdzenia trajektorii.
- `GX030120` nie wymaga osobnego zegara dla motion; wymagane jest tylko zachowanie obecnej rekonstrukcji batch timestamps.

Derived heading i slope powinny być policzone jednorazowo na zsynchronizowanych próbkach, a potem interpolowane do osi klatek. Nie należy wykonywać ponownej integracji IMU lub wyznaczania kursu od początku pliku dla każdej klatki.

## 17. Resolver/data-flow integration

Obecny przepływ został prześledzony:

```text
GPMF JSON / FIT
  → extractors / parse_fit
  → TelemetryDataManager
  → source-aware resolver
  → interpolation
  → frame_data / precompute
  → renderer
```

`src/telemetry_resolver.py` ma jawne mapowania GPMF dla speed, alt, track, IMU oraz aliasy FIT dla power/HR/cadence/temperature/battery. Nie ma logicznych pól `heading`, `grade`, `slope`, `lean` ani `orientation`. Dynamiczne pola FIT mogą być wystawiane jako `fit_*_text`, ale tylko wtedy, gdy takie pole rzeczywiście istnieje; brak bezpośredniego FIT heading/grade powoduje brak gotowego bindingu.

Najlepsza przyszła warstwa dla heading/slope to derived telemetry po synchronizacji źródła i przed `frame_data`, z cache/precompute. Lean powinien mieć osobny etap precompute IMU i dopiero potem source binding. Renderer nie powinien rozwiązywać źródeł ani liczyć geometrii telemetrycznej.

## 18. Performance implications

- GPS heading: koszt praktycznie zerowy po precompute; 10 Hz GPMF można zredukować do stabilizowanego streamu headingu.
- Slope: koszt niski; wystarczy przejście po wysokości/dystansie z oknem 10–20 m i cache.
- Lean: koszt istotny tylko podczas jednorazowego precompute około 200 Hz. Potrzebne są downsample/cache i przechowywanie gotowego roll streamu; fuzji nie wolno wykonywać od początku aktywności dla każdej klatki.
- Brak potrzeby zmian AMD/NVIDIA/GPU. Derived telemetry może być wspólna dla CPU, AMD i NVIDIA i nie powoduje GPU↔CPU round-trip w renderingu.

## 19. Decision table

| Funkcja | Dane dostępne? | Najlepsze źródło | Derived? | Renderer istnieje? | Trudność |
|---|---|---|---|---|---|
| Compass | tak, jako pozycja GPS; brak direct heading | GPMF GPS 10 Hz, FIT jako kontrola przy potwierdzonym SmartSync | TAK, COG | brak dedykowanego compass bindingu | LOW/MEDIUM |
| Slope | wysokość i dystans istnieją; direct grade brak | matched FIT `enhanced_altitude` + `track`; dla samego klipu GPMF jako fallback po filtracji | TAK | można użyć istniejącej rodziny gauge, ale brak data bindingu | MEDIUM |
| Bike Lean | ACCL/GYRO istnieją; brak gravity/quaternion/roll | GPMF ACCL + GYRO 198,69 Hz | TAK, fusion/calibration | brak | HIGH |
| Track-Up Map | heading derivable z GPS; obecna mapa north-up | ten sam derived GPMF COG | TAK | moving map istnieje, ale bez rotacji | MEDIUM/HIGH |

## 20. Recommended next stages

1. **ETAP 8B — GPS-derived Heading/Compass data contract.** Najpierw zdefiniować źródło, minimalny dystans, próg prędkości, smoothing kołowy, wrap i test zgodności GPMF ↔ dopasowany FIT. To ma najwyższą wartość i najniższe ryzyko.
2. **ETAP 8C — derived Slope/Grade.** Ustalić preferencję `enhanced_altitude + track`, okno 10–20 m, znaki, obsługę braków i walidację na matched FIT oraz GPMF.
3. **ETAP 8D — Track-Up Map.** Dopiero po stabilnym headingu; dodać plan rotacji rastera, margines/crop, deadband i zachowanie przy postoju.
4. **ETAP 8E — Bike Lean feasibility prototype.** Osobny audyt/specyfikacja osi i montażu, następnie offline fusion ACCL+GYRO na próbkach, bez włączania do renderera przed walidacją.

### Klasyfikacja końcowa

```text
COMPASS: DERIVABLE
SLOPE: DERIVABLE
LEAN: DERIVABLE
TRACK_UP: DERIVABLE
```

- **COMPASS: DERIVABLE** — GPS lat/lon i timestamp są dostępne, lecz brak direct headingu; trzeba zbudować stabilizowany course over ground.
- **SLOPE: DERIVABLE** — istnieją wysokość i dystans, ale brak direct grade, a źródła wysokości mają różną jakość i wymagają okna dystansowego.
- **LEAN: DERIVABLE** — ACCL i GYRO są dostępne i wystawione, ale brak absolutnej orientacji; konieczna jest fuzja, kalibracja i walidacja fizyczna.
- **TRACK_UP: DERIVABLE** — heading można uzyskać z GPS, ale obecny moving map jest north-up i nie przyjmuje/nie stosuje bearingu.

### Testy i zakres zmian

Uruchomiono istniejące testy parserów, resolvera, interpolacji, IMU, cache GPMF oraz synchronizacji/mapy:

```text
88 passed, 17 skipped in 7.06s
```

W ETAPIE 8A nie dodano nowych testów produkcyjnych ani nowych zmian produkcyjnych. Tymczasowy skrypt audytowy został usunięty po pomiarach. Nie zmieniano `presets/cycling_dashboard_v3.json` ani `def_layout.json`, a ścieżki CPU_REFERENCE, AMD i NVIDIA pozostawiono poza zakresem audytu.
