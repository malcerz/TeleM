# TeleM — ETAP 4A: audyt timestampowania i wyboru próbek GPMF dla ISO / SHUT / TMPC

Data audytu: 2026-08-18  
Materiał: `Video/GX030120.MP4`  
Cache: `Video/GX030120.json`  
Zakres: wyłącznie ISOE, SHUT, TMPC oraz ich timestampowanie i wybór próbek.  
Zmiany w kodzie/testach: **brak**.

## 1. MP4 i strumień GPMF

- MP4: 5395 klatek, 30000/1001 fps, czas około 180,18 s.
- GPMF: 180 pakietów danych, PTS `0.000`, `1.001`, …, `179.179` s; każdy pakiet ma około 1.001 s.
- Surowe `STMP` są licznikami czasu w mikrosekundach od startu urządzenia.
- `TSMP` jest licznikiem próbek/klatek; dla ISOE i SHUT rośnie po 30 na pakiet.
- Zależność surowa ISOE: 5370 jednostek TSMP w 179.178894 s, czyli 29.97005 próbek/s — zgodna z 30000/1001.

## 2. Inwentaryzacja surowych strumieni

| Pole | Strumień / jednostka | Bloki | Próbek surowych | Pierwszy blok | Ostatni blok |
|---|---|---:|---:|---|---|
| `ISOE` | `STNM=Sensor ISO`, typ `S` | 180 | 5400 (30/blok) | `STMP=1006093120`, `TSMP=30180` | `STMP=1185272014`, `TSMP=35550` |
| `SHUT` | `STNM=Exposure time (shutter speed)`, typ `f`, `SIUN=s` | 180 | 5400 (30/blok) | j.w. | j.w. |
| `TMPC` | występuje w `Accelerometer` i `Gyroscope`, typ `f` | 360 | 360 (1+1/blok) | `30.376953125 C` | `30.82421875 C` |

W każdym bloku ISOE i SHUT występuje własne, stream-specific `STMP` i `TSMP`. Nie jest to pojedynczy globalny timestamp przypisany po spłaszczeniu całego `DEVC`. `TMPC` nie ma tu osobnego sensora: jest powtórzoną temperaturą przy ACCL/GYRO; oba wpisy są praktycznie tym samym pomiarem i po deduplikacji dają 180 wartości czasowych.

Przykład pakietu 14, którego początek odpowiada MP4 PTS około 14.014 s:

- ISOE: wartości zaczynają się `69, 69, 69, 69, 69, 69, 70, ...`;
- SHUT: odpowiadające mianowniki zaczynają się około `420, 423, 423, ...`;
- `TSMP=30600`, następny pakiet ma `TSMP=30630`.

## 3. Co trafia do cache i pipeline'u TeleM

Cache ma 180 dokumentów. Dla każdego dokumentu:

- `DocN:ISO` zawiera 30 próbek;
- `DocN:ExposureTimes` zawiera 30 wartości tekstowych;
- `DocN:CameraTemperature` zawiera jedną wartość;
- `SampleTime` jest `0.000`, a `TimeStamp` jest wartością pomocniczą (np. 10069, 10079 …);
- czas używany przez ekstraktory pochodzi przede wszystkim z `DocN:GPSDateTime`, nie z surowego `STMP/TSMP`.

`extract_iso_samples()` i `extract_exposure_samples()` rozkładają wartości wewnątrz dokumentu syntetycznie jako:

```text
czas_dokumentu + i / liczba_wartości
```

Nie używają do tego ani MP4 PTS, ani stream-specific `STMP`, ani `TSMP`, ani nominalnego 29.97002997 Hz. `extract_temperature_samples()` zachowuje jedną próbkę na dokument. Wybór dla ISO/SHUT/TMPC jest schodkowy: używana jest poprzednia próbka (`bisect_left` / previous-value hold).

## 4. Liczności i jakość czasów po ekstrakcji

- Surowe ISOE/SHUT: po 5400 próbek.
- Cache: po 5400 elementów ISO i SHUT.
- Pipeline: po 5394 próbek ISO i SHUT — 6 próbek wypada w deduplikacji, ponieważ czas dokumentu z GPS ma kolizje/kwantyzację.
- Czasy ISO/SHUT mają nominalnie 33.333 ms, ale występują cztery przerwy po 133.333 ms. Są to artefakty czasu z cache/GPSDateTime, których nie ma w surowym układzie bloków GPMF.
- TMPC: 180 próbek po deduplikacji z dwóch wpisów sensorowych na blok.
- Raw `5400` vs `5395` klatek MP4 oznacza, że liczność GPMF nie jest bezpośrednio równa liczności klatek wideo; poprawne mapowanie wymaga czasu/P TS, nie samego indeksu listy.

## 5. Punkt referencyjny

Punkt: `2026-08-18 04:46:40 UTC`, czyli około 14.3 s od początku materiału.

- Najbliższy obszar surowy: blok 14, MP4 PTS około 14.014 s, klatka około 429.
- Raw ISOE w tym bloku zmienia się od 69 do 74; próbka około czasu referencyjnego ma ISO około 70.
- Raw SHUT w tym samym obszarze przechodzi około `1/431` → `1/434`; wybór zależy od tego, czy punkt odnosi się do początku, czy do najbliższej klatki.
- Obecna ścieżka TeleM daje w tym punkcie ISO 70 i SHUT około 433, czyli wartość z właściwego lokalnego bloku, ale nie jest to dowód poprawnego timestampowania per próbka — wynik jest osiągany przez syntetyczny czas dokumentu.
- TMPC jest wybierany jako poprzednia próbka 30 °C; próbka dokumentowa poprzedzająca punkt ma czas około 04:46:39.700 UTC.

## 6. Ocena

| Obszar | Ocena | Uzasadnienie |
|---|---|---|
| Raw ISOE payload | OK | 180 bloków × 30, typ `S`, stream-specific `STMP/TSMP`, częstotliwość zgodna z wideo. |
| Raw SHUT payload | OK | 180 bloków × 30, typ `f`, jednostka `s`, stream-specific `STMP/TSMP`. |
| Raw TMPC | OK/uwaga | 1 wartość na blok, powtórzona w ACCL i GYRO; brak osobnego strumienia temperatury. |
| Cache ISO/SHUT | częściowo OK | Wartości są kompletne, lecz raw timing `STMP/TSMP` nie jest zachowany. |
| Timestamp ISO/SHUT w pipeline | **BROKEN dla precyzji per frame** | Czas próbek jest syntetyzowany jako `i/n`, zamiast wynikać z PTS/TSMP; dodatkowo pojawiają się kolizje i luki 133 ms. |
| Timestamp TMPC | **UNCERTAIN** | Jedna wartość na dokument jest użyteczna jako hold, ale jest oparta na GPSDateTime dokumentu, nie na własnym raw `STMP`. |
| Lookup | OK jako hold, niewystarczający dowód timingowy | Step/previous jest spójny, lecz może wybrać sąsiednią próbkę przy granicy bloku. |

## Wniosek ETAPU 4A

Surowy materiał jest wystarczająco bogaty do poprawnego mapowania ISOE i SHUT po czasie GPMF/MP4. Problem leży w warstwie pośredniej: cache płaski oraz ekstraktory tracą stream-specific `STMP/TSMP` i zastępują go czasem dokumentu oraz syntetycznym `i/n`. Dla TMPC obecna wartość jest sensowna jako pomiar 1 Hz, ale jej dokładność czasowa pozostaje niepotwierdzona.

Nie wykonano zmian implementacyjnych ani testów. Ten raport nie obejmuje SmartSync, GPS, map, prędkości, HR ani kadencji.
