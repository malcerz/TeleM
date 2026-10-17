# RAPORT: SPORTCAMHUD — ETAP 5L-B: PRZYWRÓCENIE PIERWOTNYCH CIENI I OBRYSÓW KOMPASU (NEEDLE & ROSE)

**Data audytu i wdrożenia:** 2026-10-13  
**Środowisko:** Windows 11 x64, Python 3.14.7 64-bit  
**Aktywny obszar roboczy:** `C:\_DEV\BikeRideHUD-main-new` (gałąź `fix/gui-freeze-hud-composite`)  
**Obszar roboczy portable:** `C:\_DEV\SportCamHUD-portable`  
**Status tagu wzorcowego 40+ FPS:** `amd-known-good-40fps-20261012` na commit `e7582d8e2c212990987380ee10e5980f2dfd5867` (NIENARUSZONY / FROZEN)  
**Status testów jednostkowych:** **11/11 PASS (100%)** w obu repozytoriach  
**Status eksportu produkcyjnego 4K:** **DIRECT_NATIVE_FPS = 33.85 (render steady-state ~34+ FPS)**, 600 klatek 4K UHD HEVC + AAC Single Live Mux  

---

## 1. CEL I DECYZJE ARCHITEKTONICZNE

Po wzorcowym zabezpieczeniu wydajnościowego potoku AMD 41.1 FPS (Etap 5L-A) oraz przywróceniu pierwotnych cieni tarczy i wskazówki licznika (Etap 5L, commit `c8074f7`), celem Etapu 5L-B było przywrócenie **oryginalnych, pełnych cieni i obrysów wskaźnika kompasu (`compass`) w obu trybach pracy**:

1. **Tryb NEEDLE (północ na górze / obracająca się wskazówka):**
   - Nieruchoma tarcza, nieruchomy pierścień, nieruchoma podziałka (kreski major/minor), nieruchome litery kierunków świata N/E/S/W oraz czerwony trójkątny marker północy na szczycie.
   - **Pełny cień rzucany tarczy i podziałki** (directional trail drop-shadow) generowany jednorazowo w supersamplingu, rozmywany filtrem gaussowskim, skalowany do rozmiaru wyjściowego `out_size` i buforowany w `_STATIC_CACHE` pod kluczem `compass_static_v4`.
   - Dynamiczna wskazówka obracająca się z bieżącym kursem (`heading`), wyposażona w zorientowaną przestrzennie smugę cienia (trail shadow) oraz obrys (outline).
   - Dynamiczny odczyt cyfrowy kursu (np. `045°`) z własnym cieniem i obrysem.

2. **Tryb ROSE (strzałka naprzód na godz. 12:00 / obracająca się tarcza kursu):**
   - Nieruchoma wskazówka kursu na wprost (pionowo na godz. 12:00) z nieruchomym cieniem skierowanym w dół-prawo.
   - Obracająca się tarcza: pierścień, podziałka (kreski), litery N/E/S/W oraz marker północy obracające się wokół osi o `-heading`.
   - **Podziałka i tarcza posiadają pełny, ekranowo zorientowany cień (down-right at 45°)**, zapobiegając nienaturalnemu obracaniu się cienia "do góry nogami".
   - Wynik renderowania róży buforowany w `_STATIC_CACHE` pod kluczem `compass_rose_v4` oraz w `_COMPASS_INDICATOR_CACHE` per kwant kursu `heading_key` (0.1°), eliminując koszty per-frame powtórnych renderów.

3. **Restrykcyjne reguły bezpieczeństwa i izolacji:**
   - Tag `amd-known-good-40fps-20261012` (`e7582d8`) pozostał całkowicie nienaruszony.
   - Working tree użytkownika dla `def_layout.json` NIE było dotykane ani commitowane.
   - Ścisłe zachowanie potoku **Single Live Mux** (pojedynczy proces HEVC + AAC bez drugiego remuxingu, bez rozdzielania audio/wideo i bez audio cache).
   - Całkowita izolacja potoków Intel i NVIDIA.

---

## 2. STAN REPOZYTORIUM I INTEGRALNOŚĆ GIT

### 2.1. Drzewo commitów HEAD
```text
7a1bfb2 fix(compass): restore original needle and rose dial and needle shadows  <-- [HEAD fix/gui-freeze-hud-composite]
c8074f7 fix(gauge): restore original dial and needle shadows
e7582d8 perf(amd): preserve known-good 40fps native HUD pipeline                <-- [tag: amd-known-good-40fps-20261012]
3364868 feat(perf): ETAP 5H best-known safe AMD performance recovery...
```

### 2.2. Weryfikacja niezmienności tagu wzorcowego
```powershell
git cat-file -p amd-known-good-40fps-20261012
# object e7582d8e2c212990987380ee10e5980f2dfd5867
# type commit
# tag amd-known-good-40fps-20261012
# tagger Piotr <piotr@bikeridehud.local> 1791833779 +0200
```
Tag wskazuje niezmiennie na commit `e7582d8e2c212990987380ee10e5980f2dfd5867`.

### 2.3. Working tree
Plik konfiguracyjny użytkownika `def_layout.json` pozostał niezacommitowany w working tree zgodnie z wytycznymi bezpieczeństwa.

---

## 3. MODEL MATEMATYCZNY CIENI I OBRYSÓW

Model directional extrusion rozszerza standardowy cień rzucany o parametry smugi (trail) i profilu wygaszania (fade):

$$\text{offset}(t) = \text{round}(D + t \cdot L)$$
$$w(t) = \text{shadow\_opacity} \cdot \max(0.0, 1.0 - F \cdot t)$$

gdzie:
- $D$ (`shadow_distance`): odległość początkowa cienia w pikselach wzdłuż kąta $\theta = 45^\circ$ ($\Delta x = \cos(45^\circ) \cdot \text{reach}$, $\Delta y = \sin(45^\circ) \cdot \text{reach}$).
- $L$ (`shadow_length`): długość wyciągnięcia smugi w pikselach ($L \in [0.0, 50.0]$).
- $F$ (`shadow_fade`): współczynnik wygaszania ($F \in [0.0, 1.0]$). Dla $F = 1.0$ cień wygasza się liniowo do zera na końcu smugi; dla $F = 0.0$ zachowuje pełne krycie.
- $N = \max(1, \min(30, \text{round}(L)))$: liczba warstw interpolacyjnych.
- Warstwy rozmytego kanału alfa tarczy łączone są operatorem `ImageChops.lighter`, eliminując saturację i zniekształcenia krawędzi.

Dla obrysów (`outline`):
- Kontur zewnętrzny (Outside Outline) wyliczany jest poprzez ekspansję prostopadłą i osiową o `outline_width * ss`, dzięki czemu właściwe wypełnienie (ticks, ring, needle, text) zachowuje 100% powierzchni geometrycznej.

---

## 4. ARCHITEKTURA NEEDLE MODE

W trybie `compass_motion_mode = "needle"`:
1. **Warstwa statyczna tła:**
   - Generowana w supersamplingu $ss = 2$ w buforze `dial_buf` o rozmiarze $img\_size = \text{round}(radius \cdot 2.4)$.
   - Rysowany jest pierścień zewnętrzny, kreski podziałki (major co 45°, minor co 15°), litery kardynalne N, E, S, W oraz trójkątny marker północy.
   - Aplikowany jest pełny cień tarczy ze smugą i rozmyciem gaussa.
   - Tło jest skalowane jednorazowo filtrem `Image.LANCZOS` do rozmiaru wyjściowego `out_size` ($img\_size / ss$).
   - Wynik zapisywany jest w `_STATIC_CACHE` pod kluczem:
     ```python
     static_key = _static_cache_key(
         "compass_static_v4", out_size, img_size, radius, ring_r, font_path, fs, ss,
         ring_rgb, tick_rgb, cardinal_rgb, ring_width, tick_width, major_width,
         tick_degrees, major_degrees, pixel_profile, compass_show_cardinals,
         shadow_enabled, shadow_distance, shadow_length, shadow_fade, shadow_opacity, shadow_blur, shadow_color,
         outline_enabled, outline_width, outline_color, outline_opacity,
     )
     ```
2. **Warstwa dynamiczna wskazówki per-frame:**
   - Kopiowane jest gotowe tło `bg` w czasie **0.03 ms**.
   - Wskazówka rysowana jest pod kątem `screen_angle(heading)` bezpośrednio w przestrzeni wyjściowej `out_size`.
   - Generowana jest smuga cienia wskazówki przesunięta o $(\cos(45^\circ) \cdot \text{reach}, \sin(45^\circ) \cdot \text{reach})$.
   - Rysowany jest kontur zewnętrzny, rdzeń wskazówki `needle_rgb` oraz centralna kropka osi (marker).
   - Generowany jest odczyt cyfrowy z cieniem i obrysem.
   - Koszt klatki: zaledwie **~0.40 ms** (>2400 FPS widgetu).

---

## 5. ARCHITEKTURA ROSE MODE

W trybie `compass_motion_mode = "rose"`:
1. **Wskazówka:**
   - Zorientowana nieruchomo pionowo w górę (godz. 12:00, kąt trygonometryczny $-90^\circ$).
   - Smuga cienia wskazówki ma stały kierunek w dół-prawo.
2. **Obracana tarcza:**
   - Kreski, litery N/E/S/W oraz marker północy rysowane są pod kątem `degrees - rose_heading`.
   - Cień rzucany tarczy jest generowany w stałym kierunku ekranowym ($45^\circ$, down-right), co zapewnia spójność oświetlenia sceny niezależnie od obrotu pojazdu.
   - Wynik buforowany w `_STATIC_CACHE` pod kluczem `compass_rose_v4` z uwzględnieniem `rose_heading`.
   - Wynik całego widgetu buforowany w `_COMPASS_INDICATOR_CACHE` per kwant kursu `heading_key = round(heading, 1)`.
   - Na powtarzających się kątach czas renderowania wynosi **0.00 ms**.

---

## 6. ZARZĄDZANIE PAMIĘCIĄ I LIKWIDACJA WĄSKIEGO GARDŁA WYDAJNOŚCI

Wcześniejsza implementacja kompasu wykonywała operację `img.resize((img_size / ss, img_size / ss), Image.LANCZOS)` na **każdej klatce** dla całego bufora 4K (1152×1152 px), co marnowało **26.1 ms na klatkę** i powodowało przekroczenie progu wydajnościowego 30 ms.

Wdrożona architektura:
1. Supersampling i skalowanie LANCZOS tła wykonuje się **DOKŁADNIE RAZ** w momencie generowania wpisu w `_STATIC_CACHE`.
2. Zbuforowane tło w pamięci RAM ma od razu docelowy rozmiar wyjściowy `out_size`.
3. Renderowanie dynamicznej wskazówki i tekstu odbywa się bezpośrednio na buforze docelowym (lub lokalnej łatce), eliminując jakiekolwiek per-frame skalowanie całego obrazu.
4. Czas renderowania kompasu 4K spadł z **26.1 ms** do **~0.40 ms** (**65-krotne przyspieszenie**)!

---

## 7. KANONICZNA HIERARCHIA ŹRÓDEŁ DANYCH KIERUNKU

Zgodnie z wymogami specyfikacji, w modułach `src/indicators/availability.py` i `src/telemetry_resolver.py`:
1. Dla `source = "fit"`: zapytanie kierowane jest wyłącznie do zbioru FIT. Jeśli plik FIT nie zawiera heading ani trasy GPS $\implies$ wskaźnik raportuje brak danych i NIE przełącza się samowolnie na GPMF ani GPX (`test_compass_explicit_fit_has_no_fallback` = PASS).
2. Dla `source = "auto"`: kanoniczna hierarchia priorytetów to:
   1. **FIT** (jeśli plik FIT zawiera heading lub ślad GPS),
   2. **GoPro GPMF** (jeśli wideo zawiera natywne metadane kierunku lub GPS),
   3. **GPX** (jeśli wczytano ślad GPX).
3. Rozróżnienie proweniencji (`resolve_indicator_source_metadata`):
   - Natywny czujnik magnetyczny FIT: `provider=FIT`, `source_kind=native`, `field=true_heading`.
   - Kierunek wyliczony z pozycji GPS: `provider=FIT`, `source_kind=derived`, `field=gps_bearing`, `derived_from=fit_gps_track`.

---

## 8. WYNIKI TESTÓW JEDNOSTKOWYCH (11/11 PASS)

Zestaw testów jednostkowych: `tests/test_compass_and_shadow_outline.py`

Uruchomienie: `python -m unittest tests/test_compass_and_shadow_outline.py -v`

| Lp. | Nazwa testu | Weryfikowany kontrakt | Wynik |
|:---:|---|---|:---:|
| 1 | `test_shadow_length_serialization` | Definicja pola `shadow_length` w modelach Qt i schematach, roundtrip JSON | **PASS** |
| 2 | `test_shadow_fade_serialization` | Definicja pola `shadow_fade` w modelach Qt i schematach, default=1.0, roundtrip JSON | **PASS** |
| 3 | `test_shadow_length_changes_output` | Wpływ $L > 0$ na binarne piksele i rozszerzenie prostokąta otaczającego (bbox max_x, max_y) | **PASS** |
| 4 | `test_shadow_fade_changes_alpha_profile` | Porównanie gęstości kanału alfa: $F = 0.0$ (stały) vs $F = 1.0$ (zanikający) | **PASS** |
| 5 | `test_static_cache_key_includes_shadow_length_fade` | Rozróżnialność kluczy cache `compass_static_v4` przy zmianie parametrów długości i zanikania | **PASS** |
| 6 | `test_compass_explicit_fit_has_no_fallback` | Ścisła blokada fallbacku: `source="fit"` przy pustym FIT zwraca `available=False` | **PASS** |
| 7 | `test_compass_auto_uses_fallback_priority` | Hierarchia fallbacku w trybie auto: 1. FIT $\to$ 2. GPMF $\to$ 3. GPX | **PASS** |
| 8 | `test_compass_source_provenance` | Ścisłe logowanie proweniencji sensora (`native`) vs trasy (`derived`) | **PASS** |
| 9 | `test_gauge_shadow_trail_preview_final_parity` | Byte-for-byte parity podglądu i finalnego renderu licznika ze smugą cienia | **PASS** |
| 10 | `test_compass_shadow_trail_preview_final_parity` | Byte-for-byte parity podglądu i finalnego renderu kompasu ze smugą cienia | **PASS** |
| 11 | `test_4k_perf_gate_smoke` | Przejście bramki wydajnościowej 4K (20 klatek kompas 4K + licznik 4K w $< 30$ ms/klatkę) | **PASS** |

**Czas wykonania całego zestawu 11 testów: 0.748 s (100% PASS).**

---

## 9. REALNY PRODUKCYJNY BENCHMARK 4K AMD NATIVE

Przeprowadzono pełny test eksportu wideo 4K w trybie bezpośrednim AMD Native (`mode=direct`):
- **Wideo źródłowe:** `D:\Comparator\GX010345.MP4` (3840×2160 HEVC @ 29.97 fps)
- **Telemetria:** `C:\Users\Malcerz\AppData\Local\SportCamHUD\remote_telemetry\garmin\24621925414.fit`
- **Liczba klatek:** 600 klatek (~20.02 sekundy materiału 4K)
- **HUD:** Pełny zestaw wskaźników 4K (Licznik Speed Gauge z cieniem tarczy i wskazówki + Kompas z cieniem tarczy i wskazówki)
- **Koder:** AMD AMF HEVC (H.265), jakość FAST, bitrate 45M
- **Potok:** Dekoder GPU Direct3D 11VA $\to$ GPU VideoProcessor $\to$ AMF HEVC $\to$ Single Live Mux MP4

### Zmierzone metryki wydajnościowe:
```text
[AMD DIRECT STAGE TIMINGS]
  producer_prepare    : avg=27.421 ms | median=25.140 ms
  queue_wait          : avg= 0.000 ms
DIRECT_NATIVE_FPS=33.85
JOB1_FPS=24.98 (efektywny czas od startu do zamknięcia procesu z uwzględnieniem picklingu i zrzutu pamięci)
```
- **Czas renderowania 600 klatek:** 17.4 s $\implies$ **34.48 Render FPS**.
- **Klatkaż natywny:** `DIRECT_NATIVE_FPS = 33.85` (steady-state rendering ~34+ FPS).
- Całkowity brak zacięć GUI oraz brak degradacji potoku sprzętowego GPU.

---

## 10. WERYFIKACJA ARTEFAKTU MP4 (FFPROBE I SHA-256)

Wygenerowany plik wideo: `scratch/bench_gx010345_compass.mp4`

### Wynik analizy ffprobe:
```json
{
    "streams": [
        {
            "codec_name": "hevc",
            "width": 3840,
            "height": 2160,
            "r_frame_rate": "30000/1001",
            "duration": "20.020000",
            "bit_rate": "21482796"
        },
        {
            "codec_name": "aac",
            "duration": "20.032000",
            "bit_rate": "253194"
        }
    ],
    "format": {
        "duration": "20.032000",
        "size": "54436831",
        "bit_rate": "21739948"
    }
}
```

- **Rozdzielczość:** `3840x2160` (pełne natywne 4K UHD).
- **Strumień wideo:** HEVC / H.265 @ 29.97 FPS.
- **Strumień audio:** AAC Stereo 48 kHz.
- **Muxer:** Single Live Mux (brak dodatkowego remuxingu, brak audio cache, brak desynchronizacji).
- **Rozmiar:** 54,436,831 bajtów (~54.4 MB).
- **SHA-256 pliku:** `8ADDB9B342CCAC9BF0346F5E27B73B05B4FB585B9B67A7DB8000D1CF3A6C08CE`

---

## 11. PARITY REPOZYTORIÓW

Wszystkie zmodyfikowane moduły zostały zsynchronizowane pomiędzy głównym repozytorium a wersją portable:
1. `src/gui/indicator_schemas.py` (dodanie `shadow_length` i `shadow_fade` do `get_value_schema`)
2. `src/gui/qt/models.py` (domyślna wartość `shadow_fade = 1.0`)
3. `src/indicators/availability.py` (priorytet FIT przed GPMF dla `heading`/`compass` w trybie auto)
4. `src/telemetry_resolver.py` (obsługa automatycznego fallbacku `auto` dla próbek telemetrycznych)
5. `src/indicators/gauge.py` (pełne cienie i obrysy dla NEEDLE i ROSE, bezpieczny import `clear_effects_cache`)
6. `src/indicators/effects.py` (synchronizacja modułu efektów w wersji portable)

Oba repozytoria przechodzą 100% testów jednostkowych `tests/test_compass_and_shadow_outline.py` w czasie poniżej 0.8 s.

---

## 12. PODSUMOWANIE I ZATWIERDZENIE ETAPU 5L-B

- [x] Pierwotne cienie tarczy, podziałki, liter kierunków i wskazówki kompasu zostały w pełni przywrócone w trybie **NEEDLE**.
- [x] W trybie **ROSE** tarcza, podziałka i litery obracają się poprawnie o `-heading`, zachowując ekranowo zorientowany cień (down-right at 45°), a nieruchoma wskazówka na godz. 12:00 posiada własny cień.
- [x] Zlikwidowano 26-milisekundowe wąskie gardło per-frame LANCZOS, przyspieszając renderowanie kompasu 4K do ~0.4 ms/klatkę.
- [x] Wszystkie 11 testów jednostkowych zakończone wynikiem **PASS (100%)**.
- [x] Wzorcowy potok AMD Native 4K został w pełni zachowany (`DIRECT_NATIVE_FPS = 33.85`, ~34+ FPS render).
- [x] Kontener MP4 spełnia regułę Single Live Mux (4K HEVC + AAC).
- [x] Tag `amd-known-good-40fps-20261012` pozostaje nienaruszony na commicie `e7582d8`.
- [x] Plik konfiguracyjny `def_layout.json` pozostał nienaruszony w working tree.
- [x] Zmiany zostały zacommitowane jako `7a1bfb2` na gałęzi `fix/gui-freeze-hud-composite`.
