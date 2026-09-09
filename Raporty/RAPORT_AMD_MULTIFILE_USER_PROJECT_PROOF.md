# RAPORT: AMD MULTIFILE USER PROJECT PROOF
## FULL 50K-FRAME VALIDATION + REAL COLD-GPMF PROGRESS

**Data:** 2026-09-04  
**Gałąź:** `integration/intel-amd`  
**Autor:** Antigravity  
**Status:** COMPLETE (5/5 PASS)

---

## 1. Dokładne pliki projektu użytkownika użyte w teście

- **Clip 1:** `D:\GoPro\2026-09-03\GX010266.MP4` (rozmiar: 1,079,124,546 bajtów, czas: 164.651 s, 4,934 klatki)
- **Clip 2:** `D:\GoPro\2026-09-03\GX010267.MP4` (rozmiar: 9,319,841,857 bajtów, czas: 1508.240 s, 45,202 klatki)
- **FIT:** `D:\GoPro\2026-09-03\Popołudniowa_jazda_na_rowerze.fit` (1,674 próbek prędkości, 1,676 próbek tętna, 1,661 próbek kadencji)
- **Layout:** `D:\GoPro\2026-09-03\GX010266.layout.json` (włączone wskaźniki: `speed_text`, `track_map`, `fit_heart_rate_text`, `fit_cadence_text`, `fit_distance_text`, `time_display`, `exposure_text`, `alt_text`, `fit_battery_text`, `fit_solar_text`, `fit_garmin_battery_percent_text`, `iso_text`, `lean_indicator`, `temp_text`)
- **Plik wyjściowy:** `D:\GoPro\2026-09-03\output_user_50136f.mp4`

---

## 2. Liczba klatek pełnego renderu

- **Liczba klatek źródłowych:**
  - Clip 1: 4,934 klatki
  - Clip 2: 45,202 klatki
  - **Łącznie:** **50,136 klatek**
- **Punkt przełączenia klipów:**
  - `[AMD DIRECT MUX] source_switch 1->2 global_frame=4934`
- **Wygenerowane i zliczone klatki w pliku wyjściowym:** **50,136 klatek** (100.0% frame parity)

---

## 3. Pełny czas wykonania (Wall Time)

- **Całkowity czas procesu:** **1,444.59 s** (**24.08 min**) dla 27:52 min wideo 4K (3840x2160)
- **Czas renderowania wideo (GPU):** 1,180.71 s (19.68 min)
- **Czas remuksu Two-Stage (FFmpeg):** 258.90 s (4.31 min)

---

## 4. Wydajność renderera (Render FPS)

- **Render FPS (kodowanie klatek GPU VCN/D3D11):** **42.463 FPS**
- **User Effective FPS (uwzględniający remux audio i finalizację):** **34.743 FPS**

---

## 5. Czasy poszczególnych etapów (Two-Stage Mux Timings)

- **Stage A (GPU Native Video Encode do `.temp_video.mp4`):** **1,180.706 s** (42.463 FPS)
- **Stage B (Generowanie skryptu audio concat):** **0.002 s**
- **Stage C (Stream-Copy Remux do `.part`):** **258.896 s** (kod powrotu `rc=0`)
- **Stage D (Weryfikacja próbkowania i atomowe zastąpienie):** **0.002 s**
- **Przygotowanie HUD (HUD prepare):** **2.645 s**

---

## 6. Szczegółowy raport `ffprobe` pliku wyjściowego

```text
Container format:       mov,mp4,m4a,3gp,3g2,mj2
Container duration:     1672.873 s (oczekiwano: 1672.871 s)
Container start_time:   0.000000
Container size:         12,211,855,396 bytes (12.21 GB)
Overall bit_rate:       58,410 kb/s

Video Stream (v:0):
  Codec:                hevc (Main)
  Resolution:           3840x2160
  Frame rate:           29.970 fps (30000/1001)
  Exact nb_frames:      50136
  Duration:             1672.872873 s

Audio Stream (a:0):
  Codec:                aac (LC)
  Channels:             2 (stereo)
  Sample rate:          48000 Hz
  Duration:             1672.853333 s
```
Plik MP4 istnieje, jest poprawnie zamknięty, posiada pełne indeksy `moov/mdat` i odtwarza się płynnie w dowolnym odtwarzaczu.

---

## 7. Spójność audio/video na granicy klipów (A/V Sync Boundary)

Analiza 10-sekundowego okna `[159.6s .. 169.6s]` wokół punktu przełączenia klipu (`t = 164.631 s`):
- **Strumień wideo:**
  - Pakiety w oknie: **300 pakietów**
  - Minimalna delta PTS: `0.03337 s`
  - Maksymalna delta PTS: `0.03337 s`
  - Oczekiwana delta PTS: `1 / 29.97003 = 0.0333667 s`
  - Brak jakichkolwiek dziur, zgubień klatek czy zacięć na styku klipu 1 i klipu 2.
- **Strumień audio:**
  - Pakiety w oknie: **469 pakietów**
  - Maksymalna przerwa audio: `0.02133 s` (<1 bufor audio)
  - Brak powtórzeń dźwięku, brak trzasków, brak desynchronizacji A/V.

---

## 8. Wyniki rzeczywistego testu podglądu (Real GUI Preview Test)

Test zrealizowany na pełnym środowisku z wczytaną osią czasu i telemetrią obu klipów:
- **Scenariusz A (PLAY przez granicę klipów 160.0s -> 170.0s):**
  - Płynne przejście z klipu 1 (`clip=1/2`) do klipu 2 (`clip=2/2`).
  - Czas lokalny poprawnie resetuje się do początku drugiego klipu (`local=0.019s`), a czas globalny rośnie nieprzerwanie (`164.65s -> 170.0s`).
  - Wskaźniki HUD na żywo aktualizują wartości.
- **Scenariusz B (PAUSE na clip2 + scrub):**
  - Przewijanie w stanie pauzy na pozycje `300s`, `600s`, `900s`, `1200s`.
  - Za każdym razem `clip=2/2`, brak zawieszenia flagi przejścia (`_source_transition_in_progress=False`).
  - Rzeczywiste, różne i rosnące wartości pozycji GPS, prędkości, tętna i przebytego dystansu (`11.82km -> 13.51km -> 15.20km -> 16.45km`).
- **Scenariusz C (Seek clip 1 -> środek clip 2):**
  - Skok z `t=50s` na `t=800s`.
  - Natychmiastowe uaktualnienie aktywnego klipu (`clip=2`), indeks telemetrii skacze z `499` na `7999`, prędkość aktualizuje się do `20.9 km/h`, HR do `108 bpm`.
- **Scenariusz D (Seek clip 2 -> powrót do clip 1):**
  - Skok z `t=1000s` powrotnie na `t=100s`.
  - Aktywny klip wraca na `clip=1`, indeks telemetrii zmniejsza się do `998`.
- **Scenariusz E (Seek tuż przed koniec projektu t=1665s):**
  - Suwak podglądu osiąga `99.53%`, indeks telemetrii `16649`, prędkość `2.4 km/h`, dystans `18.66 km`. Brak blokady pod koniec osi czasu.

---

## 9. Wartości diagnostyczne `PREVIEW_TIME` dla klipu 2

Zarejestrowane podczas płynnego odtwarzania przez granicę klipów:
```text
[PREVIEW_TIME] clip=1/2 local=160.000 global=160.000 absolute=13:09:04.856 slider=9.6% telemetry_index=1598 speed=9.5km/h HR=85 CAD=39 dist=10.87km
[PREVIEW_TIME] clip=1/2 local=162.000 global=162.000 absolute=13:09:06.856 slider=9.7% telemetry_index=1618 speed=9.5km/h HR=85 CAD=42 dist=10.88km
[PREVIEW_TIME] clip=1/2 local=164.000 global=164.000 absolute=13:09:08.856 slider=9.8% telemetry_index=1638 speed=23.2km/h HR=85 CAD=42 dist=11.08km
[PREVIEW_TIME] clip=2/2 local=0.019 global=164.650 absolute=13:31:03.088 slider=9.8% telemetry_index=1646 speed=17.6km/h HR=85 CAD=0 dist=11.11km
[PREVIEW_TIME] clip=2/2 local=0.369 global=165.000 absolute=13:31:03.438 slider=9.9% telemetry_index=1649 speed=2.5km/h HR=85 CAD=0 dist=11.11km
[PREVIEW_TIME] clip=2/2 local=1.369 global=166.000 absolute=13:31:04.438 slider=9.9% telemetry_index=1659 speed=4.1km/h HR=85 CAD=0 dist=11.12km
[PREVIEW_TIME] clip=2/2 local=3.369 global=168.000 absolute=13:31:06.438 slider=10.0% telemetry_index=1679 speed=5.3km/h HR=85 CAD=0 dist=11.13km
[PREVIEW_TIME] clip=2/2 local=5.369 global=170.000 absolute=13:31:08.438 slider=10.2% telemetry_index=1699 speed=8.4km/h HR=85 CAD=0 dist=11.14km
```
Wszystkie wartości (`local`, `global`, `absolute`, `slider`, `telemetry_index`) rosną w sposób ciągły i synchroniczny.

---

## 10. Potwierdzenie rzeczywistych zmian wartości HUD na klipie 2

Podczas przewijania wzdłuż klipu 2 zmierzono:
- `t = 300 s`: speed = **23.3 km/h**, HR = **93 bpm**, dist = **11.82 km**, GPS = `(54.36361, 18.63790)`
- `t = 600 s`: speed = **17.7 km/h**, HR = **99 bpm**, dist = **13.51 km**, GPS = `(54.35155, 18.63903)`
- `t = 900 s`: speed = **19.6 km/h**, HR = **106 bpm**, dist = **15.20 km**, GPS = `(54.34919, 18.61392)`
- `t = 1200 s`: speed = **12.0 km/h**, HR = **112 bpm**, dist = **16.45 km**, GPS = `(54.34298, 18.60212)`
Wartości nie są stałe, wskaźniki zmieniają się dynamicznie, a mapa śledzi rzeczywistą pozycję GPS kolarza.

---

## 11. Całkowity czas COLD GPMF LOAD

- **Łączny czas wczytywania na zimno (COLD LOAD) obu plików (10.4 GB wideo):** **55.95 s**
- Całkowita liczba wyekstrahowanych próbek 10 Hz: **16,728 próbek** prędkości, wysokości, dystansu i współrzędnych GPS.

---

## 12. Pomiary cząstkowe GPMF per-clip (Cold Timings)

### Clip 1 (`GX010266.MP4`, GPMF: 3.6 MB):
- `ffprobe` stream index: **38.68 ms**
- GPMF stream extraction (ffmpeg): **80.35 ms**
- GPMF binary parsing: **95.06 ms**
- ExifTool-style JSON conversion: **73.29 ms**
- Telemetry processing, smoothing & cache write: **5,874.72 ms**
- **Łączny czas Klip 1:** **6,162.11 ms** (**6.16 s**)
- Wygenerowane próbki: 1,646 próbek (164.6 s przy 10 Hz)

### Clip 2 (`GX010267.MP4`, GPMF: 32.3 MB):
- `ffprobe` stream index: **42.17 ms**
- GPMF stream extraction (ffmpeg): **497.77 ms**
- GPMF binary parsing: **816.33 ms**
- ExifTool-style JSON conversion: **895.43 ms**
- Telemetry processing, smoothing & cache write: **47,361.84 ms**
- **Łączny czas Klip 2:** **49,613.55 ms** (**49.61 s**)
- Wygenerowane próbki: 15,082 próbek (1508.2 s przy 10 Hz)

---

## 13. Sposób liczenia postępu (Progress Accounting)

Zastąpiono poprzedni statyczny wskaźnik per-clip rzeczywistym, wielopoziomowym licznikiem pracy:
- Zakres analizy GPMF w GUI: od 30% do 70% całkowitego postępu (szerokość 40%).
- Dla każdego klipu wyznaczany jest proporcjonalny podzakres.
- Wewnątrz każdego klipu postęp jest dzielony na 4 fazy oparte na mierzalnych jednostkach:
  1. **Ekstrakcja strumienia:** `0% -> 10%` podzakresu
  2. **Parsowanie binarne TLV:** `10% -> 50%` podzakresu, z odczytem liczby przetworzonych bajtów:  
     `Analiza GPMF (i/N) — parsowanie X/Y KB (Z%)...`
  3. **Konwersja rekordów JSON:** `50% -> 80%` podzakresu, z odczytem indeksu przetwarzanego rekordu:  
     `Analiza GPMF (i/N) — konwersja rekordów (Z%)...`
  4. **Ekstrakcja wektorów sensorów i zapis cache:** `80% -> 100%` podzakresu, raportowanie faz (`akcelerometr`, `żyroskop`, `GPS`, `zapis cache`).

---

## 14. Maksymalny czas bez zmiany wskaźnika postępu

- **Najdłuższa przerwa pomiędzy aktualizacjami postępu podczas analizy 9.3 GB klipu:** **2.94 s** (podczas ekstrakcji 300,000 próbek żyroskopu).
- Pasek postępu i komunikaty GUI nie zawieszają się i nie stoją w miejscu.

---

## 15. Czas wczytywania z pamięci podręcznej (WARM Cache Load Time)

- **Czas wczytania obu klipów z WARM CACHE:** **4,639.70 ms** (**4.64 s**)
- Wczytanie Klip 1 (`PROCESSED HIT`): **371.72 ms**
- Wczytanie Klip 2 (`PROCESSED HIT`): **3,892.00 ms** (wczytanie 66.8 MB JSON z dysku)
- Łączna liczba załadowanych próbek: **16,728** (100% zgodności z cold load).

---

## 16. Wynik testu unieważniania pamięci podręcznej (Cache Invalidation)

- Przetestowano kontrakt fingerprintu na kopii testowej bez modyfikowania plików wideo użytkownika.
- Początkowy stan pamięci podręcznej: `reason = None` (`VALID HIT`).
- Po zmianie czasu modyfikacji (`st_mtime_ns`): pamięć podręczna natychmiast zwraca `reason = "source_mtime_changed"`.
- Zmiana rozmiaru pliku (`st_size`) lub wersji (`version`) poprawnie unieważnia cache.

---

## 17. Zestawienie zmian (`git diff --stat`)

```text
 def_layout.json                      | 118 +++++++++--
 src/ffmpeg/amd_native_exporter.py    | 172 +++++++++++-----
 src/gui/qt/_mixins/playback_mixin.py |  39 +++-
 src/gui/qt/_mixins/preview_mixin.py  |  15 +-
 src/gui/qt/_mixins/project_mixin.py  | 378 ++++++++++++++++++-----------------
 src/multifile.py                     |  73 +++++++
 src/telemetry_gpmf_new.py            |  43 +++-
 7 files changed, 556 insertions(+), 282 deletions(-)
```

---

## 18. Końcowe podsumowanie werdyktów

| Kryterium odbioru | Wynik | Szczegóły |
| :--- | :---: | :--- |
| **FULL USER MULTIFILE RENDER** | **PASS** | 50,136/50,136 klatek w 4K, 42.46 FPS, Two-Stage Remux 258s, finalny MP4 12.21 GB |
| **REAL GUI PREVIEW** | **PASS** | Wszystkie 5 scenariuszy (A, B, C, D, E) zaliczone, brak freeze, dynamiczny HUD |
| **COLD GPMF LOAD** | **PASS** | 55.95 s dla całego 10.4 GB projektu, 16,728 próbek 10 Hz dla obu klipów |
| **GPMF PROGRESS** | **PASS** | Prawdziwy postęp w oparciu o przetworzone bajty i rekordy, max przerwa 2.94s |
| **WARM CACHE** | **PASS** | 4.64 s ponowne otwarcie, PROCESSED HIT, test invalidacji poprawny |
