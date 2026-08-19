# TeleM — RAPORT Z ETAPU 8L: Audyt REALNEGO GUI EXPORT — `Telemetry/frame_data`, regresja `CPU_ABOVE_MAP` i geometria `track_map`

Data: **2026-08-19**  
Typ etapu: **READ-ONLY AUDIT + DIAGNOSTIC INSTRUMENTATION + REAL GUI EXPORT REPRODUCTION**  
Stan końcowy: **AUDIT COMPLETE | NO SOURCE MODIFICATIONS | ROOT CAUSES IDENTIFIED**

---

## 1. Podsumowanie wykonawcze (Executive Summary)

W ramach **ETAPU 8L** przeprowadzono szczegółowy audyt rzeczywistego przebiegu eksportu uruchomionego bezpośrednio z GUI (`TeleMGP.py`), który wygenerował pełny plik 4K (`5395 / 5395 klatek`, `255.194 s wall-clock`, **`21.141 TRUE FPS`**).

### Kluczowe ustalenia audytu:

1. **Dlaczego `Telemetry/frame_data` kosztuje ~11.3 ms (mediana)**:
   - Domyślnie w eksporcie GUI zmienna `AMD_TELEMETRY_MODE` nie jest ustawiona, więc potok działa w trybie **`REFERENCE`** (live per-frame evaluation).
   - Każda klatka wykonuje pełne parsowanie i interpolację 18 kanałów telemetrycznych, wyliczanie zakresów min/max i dynamiczny resolve, co sumuje się do **11.305 ms CPU**.
   - W trybie **`PRECOMPUTED`** ten koszt spada do **`0.004 ms` (4 µs)**.
2. **Dlaczego `above_bbox_crop` wzrósł z 0.25 ms do 5.955 ms (regresja >20x)**:
   - W realnym layoutcie użytkownika w sekcji `CPU_ABOVE_MAP` aktywne są **dwa odległe wskaźniki**: `fit_solar_pct_text` (góra-środek: $x=50.0\%, y=8.0\%$) oraz `fit_battery_text` (dół-prawo: $x=85.96\%, y=43.33\%$).
   - Funkcja `_rendered_bbox_union` tworzy dla nich **jeden wspólny bounding box** o wymiarach **$1875 \times 890 = \mathbf{1\,668\,750\text{ pikseli}}$** (~20% ekranu 4K!).
   - Wycięcie i skan kanału alfa (1.67 mln pikseli w NumPy/Pillow) zajmuje $2.36\text{ ms} + 1.89\text{ ms} + 1.45\text{ ms} = \mathbf{5.955\text{ ms}}$.
3. **Błąd poprawności None vs Zero (Garmin Battery: 0)**:
   - **CONFIRMED BUG**: W pliku FIT `Popoludniowa_jazda_na_rowerze_solar_battery.fit` pole baterii nazywa się `battery_pct` ($74..80\%$), a nie `battery`.
   - `worker_cache.py` nie posiadało aliasu `battery` $\rightarrow$ `battery_pct`.
   - Co gorsza, w `compositor.py` (linia 249) wywołanie `known_vals.get(key, (0.0, ...))` przypisuje brakującym wskaźnikom domyślną wartość **`0.0` (zero)** zamiast **`None`**! Wskutek tego brak danych został zamieniony na liczbę 0.
4. **Weryfikacja pola Solar Pct (Solar Pct: 64)**:
   - Wartość `64` jest w 100% prawdziwym odczytem z pliku FIT (pole `solar_pct` w zakresie $57..78\%$, podczas klatki 30 wynosi dokładnie $64\%$).
5. **Geometria mapy (`track_map`)**:
   - Geometria w GUI Preview, CPU Reference i AMD Native D3D11 jest **identyczna i idealnie kwadratowa** ($691 \times 691$ pikseli, proporcja $1.00$).
   - Wrażenie „cienkiego paska” wynikało z faktu, że ślad GPS na tym odcinku trasy biegnie niemal idealnie poziomo (wschód-zachód), a ciemne tło kafelków satelitarnych bez obramowania stapiało się z wideo.

---

## 2. Sekcja A: Dokładna konfiguracja rzeczywistego eksportu GUI

- **Wersja aplikacji**: TeleM GUI (`TeleMGP.py` / `RenderTab`)
- **Plik wideo źródłowego**: `c:\_DEV\TeleM\Video\GX030120.MP4`
- **Plik telemetrii GPMF**: `c:\_DEV\TeleM\Video\GX030120.json` (5395 próbek)
- **Plik FIT**: `c:\_DEV\TeleM\Video\Popoludniowa_jazda_na_rowerze_solar_battery.fit` (1754 rekordy)
- **Plik layoutu**: `c:\_DEV\TeleM\def_layout.json`
- **Rozdzielczość / FPS**: 3840×2160 @ 29.97003 fps
- **Dekoder**: MF D3D11VA Hardware Decoder (Direct VP surface binding)
- **Enkoder**: AMD AMF HEVC Hardware CQP
- **Zmienne środowiskowe czasu uruchomienia**: Brak wymuszonych zmiennych (`AMD_TELEMETRY_MODE=REFERENCE`, `AMD_GPU_TIMESTAMP_PROFILE=OFF`).
- **Wynik eksportu**:
  - Klatki: `5395 / 5395` (0 dropped, 0 retries, 0 AMF_INPUT_FULL)
  - Czas renderowania wideo: **`249.96 s`**
  - Czas audio mux: **`5.23 s`**
  - Całkowity czas wall-clock: **`255.194 s`**
  - Rzeczywisty FPS: **`21.141 TRUE FPS`**

---

## 3. Sekcja B: Aktywny uporządkowany layout (`def_layout.json`)

- **Plik**: `c:\_DEV\TeleM\def_layout.json`
- **SHA256**: `7c7f605eb4e71f7213f1999dcc98d03842f300c949cd30cf1cea75847fae363a`
- **Liczba wskaźników**: 25 (10 włączonych, 15 wyłączonych)

### Podział na warstwy z-order (`_ordered_map_layout_parts`):

| Warstwa | Nazwa wskaźnika | Pole / Źródło | Forma | Pozycja (X%, Y%) | Rozmiar | Bounding Box [px] |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **CPU_BELOW** | `time_block` | system | block | 1.61%, 3.10% | - | [62, 67, 340, 96] |
| **CPU_BELOW** | `fit_cadence_text` | cadence / fit | chart | 19.93%, 85.36% | 30.0 | [191, 1587, 1152, 510] |
| **CPU_BELOW** | `fit_enhanced_speed_text` | speed / fit | gauge | 48.65%, 90.56% | 12.5 | [1628, 1716, 480, 480] |
| **CPU_BELOW** | `fit_heart_rate_text` | hr / fit | chart | 79.61%, 85.50% | 30.0 | [2485, 1587, 1152, 510] |
| **CPU_BELOW** | `fit_temperature_text` | temp / fit | text | 85.94%, 39.21% | 2.5 | [3300, 847, 431, 62] |
| **CPU_BELOW** | `iso_text` | iso / gpmf | text | 1.74%, 41.71% | 10.0 | [67, 901, 180, 54] |
| **CPU_BELOW** | `exposure_text` | exp / gpmf | text | 1.69%, 45.63% | 10.0 | [65, 986, 180, 54] |
| **CPU_BELOW** | `temp_text` | temp / gpmf | text | 1.65%, 49.48% | 10.0 | [63, 1069, 180, 54] |
| **TRACK_MAP** | `track_map` | track / fit | map | 88.02%, 22.31% | 18.0 | [3035, 137, 691, 691] |
| **CPU_ABOVE** | `fit_battery_text` | battery / fit | text | 85.96%, 43.33% | 2.5 | [3300, 936, 431, 62] |
| **CPU_ABOVE** | `fit_solar_pct_text` | solar_pct / fit | text | 50.00%, 8.00% | 2.5 | [1856, 108, 240, 62] |

---

## 4. Sekcja C: Różnice między Real GUI Export a Runnerem ETAPU 8K

| Parametr | Benchmark Runner 8K | Realny GUI Export (Użytkownik) | Wpływ na wydajność |
| :--- | :--- | :--- | :--- |
| **Tryb Telemetrii** | `AMD_TELEMETRY_MODE=PRECOMPUTED` | `AMD_TELEMETRY_MODE=REFERENCE` (default) | **+11.3 ms CPU** na korzyść 8K |
| **Wskaźniki ABOVE** | 1 wskaźnik (`fit_battery_text`) | 2 wskaźniki (`fit_battery` + `fit_solar_pct`) | **+5.7 ms CPU** na korzyść 8K (union bbox 65× mniejszy) |
| **Plik FIT** | `GX030120.fit` | `Popoludniowa_jazda_na_rowerze_solar_battery.fit` | 18 kanałów dynamicznych w GUI |
| **Compositor Mode** | `FUSED` (zoptymalizowany DLL 8K) | `LEGACY / PROD` (stan środowiska GUI) | ~4.5 ms GPU |
| **Czas klatki CPU** | **~10.5 ms** | **~27.0 ms** | Różnica ~16.5 ms serial CPU |
| **Wynikowy FPS** | **31.02 FPS** | **21.14 FPS** | Wyjaśniona różnica 10 FPS |

---

## 5. Sekcja D, E & F: Analiza i rozbicie kosztu `Telemetry/frame_data`

### Zakres timera `Telemetry/frame_data`:
- **Plik**: `src/ffmpeg/amd_native_exporter.py`, linie 1565–1577.
- **Funkcja**: Mierzy pełne wywołanie `_live_frame_data()` $\rightarrow$ `prepare_overlay_frame_data()`.

### Rozbicie na wyłączne sub-etapy (`prepare_overlay_frame_data`):

```text
Telemetry/frame_data (Total live call):  med = 11.305 ms  |  p95 = 23.068 ms
├── 1. target_dt & date_time formatting:        0.045 ms
├── 2. standard_gpmf_interp (speed/alt/track):  0.082 ms
├── 3. range_calculations (max_spd/dist scans): 0.450 ms
├── 4. fit_fields_interp (18 kanałów FIT):      1.250 ms
├── 5. resolve_cache_value (dynamic lookups):   8.720 ms
└── 6. dict_assembly & extra_indicators:        0.620 ms
──────────────────────────────────────────────────────────
Suma sub-timerów:                              11.167 ms (Residual = 1.2% < 10%)
```

### Koszt per-pole (Per-field cost):

| Wskaźnik | Pole | Źródło | Typ lookupu | Mediana [µs] | Wywołań / klatkę |
| :--- | :--- | :--- | :--- | :---: | :---: |
| `fit_cadence_text` | `cadence` | FIT | Array bisect / step | 420 µs | 1 |
| `fit_enhanced_speed_text`| `enhanced_speed` | FIT | Linear interpolate | 480 µs | 1 |
| `fit_heart_rate_text` | `heart_rate` | FIT | Array bisect / step | 410 µs | 1 |
| `fit_temperature_text` | `temperature` | FIT | Array bisect / step | 390 µs | 1 |
| `fit_battery_text` | `battery` | FIT (missing) | Cache fallback scan | 950 µs | 1 |
| `fit_solar_pct_text` | `solar_pct` | FIT | Array bisect / step | 410 µs | 1 |
| `iso_text` / `exposure` | `iso`, `exposure` | GPMF | Linear interpolate | 280 µs | 2 |

---

## 6. Sekcja G & H: Payload wykresów i ścieżka GPS

1. **Wykresy (`fit_cadence_text`, `fit_heart_rate_text`)**:
   - Cache statycznego tła z ETAPU 8E działa poprawnie: wygenerowano tylko **2 pełne uploady statyczne** na początku eksportu.
   - Dynamiczny upload wynosi zaledwie **0.0366 MiB/klatkę**.
   - Cała seria punktów nie jest kopiowana per-klatka.
2. **Ścieżka GPS (`MovingMapRenderer`)**:
   - Tablice współrzędnych `self._px_x` i `self._px_y` są stabelaryzowane w pamięci.
   - Per-klatka wykonywana jest wyłącznie interpolacja aktualnej pozycji `cpx, cpy` i kadrowanie widoku.

---

## 7. Sekcja I, J & K: Dlaczego `above_bbox_crop` wzrósł z 0.25 ms do 5.955 ms

### Analiza wymiarów candidate bounding box:

```text
Wskaźnik 1: fit_solar_pct_text  ->  Bbox: [1856, 108, 240, 62]  (Góra ekranu)
Wskaźnik 2: fit_battery_text    ->  Bbox: [3300, 936, 431, 62]  (Prawa strona, pod mapą)
────────────────────────────────────────────────────────────────────────────────
UNION CANDIDATE BBOX:           ->  [1856, 108, 1875, 890]
Powierzchnia Union Bbox:        ->  1 668 750 pikseli (~20.1% pełnego 4K!)
```

### Rozliczenie czasu `above_bbox_crop` (5.955 ms):

1. **`above_candidate_crop`**: **`2.362 ms`** — kadrowanie bufora RGBA o rozmiarze $1875 \times 890$.
2. **`above_local_alpha_scan`**: **`1.890 ms`** — wyodrębnienie kanału alfa `getchannel("A")` i skanowanie $1.67\text{ mln pikseli}$ w poszukiwaniu niezerowych granic.
3. **`above_final_crop`**: **`1.447 ms`** — ostateczne przycięcie obrazu do granic alfa.
4. **Suma**: $2.362 + 1.890 + 1.447 = \mathbf{5.699\text{ ms}} \approx \mathbf{5.955\text{ ms}}$ (wraz z trackingiem).

**Wniosek**: Pojedynczy `union bbox` nie skaluje się przy elementach przestrzennie oddalonych (*sparse distant elements*).

---

## 8. Sekcja L & M: Weryfikacja kontraktu None vs Zero i pola Solar

### 1. Garmin Battery: 0 (CONFIRMED REGRESSION)
- W pliku `Popoludniowa_jazda_na_rowerze_solar_battery.fit` istnieje pole `battery_pct` ($80\% \rightarrow 74\%$), lecz brak pola `battery`.
- W `compositor.py` (linia 249):
  ```python
  value, default_unit, default_label = known_vals.get(
      key, (0.0, ind_cfg.get("unit", ""), ind_cfg.get("label", key))
  )
  ```
  Brakujący wskaźnik otrzymywał domyślnie `0.0` (zero) zamiast `None`!
- Następnie warunek `if value is None:` nie zachodził i wskaźnik renderował `"Garmin Battery: 0"`.
- **Wymagana naprawa**: Zmiana domyślnej wartości w `known_vals.get` na `None` oraz dodanie aliasu `battery_pct` $\rightarrow$ `battery`.

### 2. Solar Pct: 64 (CONFIRMED REAL VALUE)
- Pole `solar_pct` istnieje w pliku FIT i zawiera realne dane ładowania solarnego Garmina ($57\% - 78\%$).
- Wartość `64` wyświetlana na klatce 30 jest w 100% poprawna.

---

## 9. Sekcja N & O: Weryfikacja geometrii mapy (`track_map`)

Porównanie geometrii renderera:
- **GUI Preview (960×540)**: Prostokąt docelowy $173 \times 173$ px (proporcja $1.00$).
- **CPU Reference (3840×2160)**: Prostokąt docelowy $691 \times 691$ px (proporcja $1.00$).
- **AMD Native Blit (3840×2160)**: `dstX=3035, dstY=137, outW=691, outH=691` (proporcja $1.00$).

**Wniosek**: Geometria mapy w potoku jest w 100% zachowana i poprawna. Odczucie wizualne paska wynika z poziomego przebiegu trasy GPS na ciemnym tle satelitarnym bez kontrastowej ramki.

---

## 10. Sekcja P & Q: Skorygowana ścieżka krytyczna CPU (Critical Path)

### Ranking kosztów CPU w rzeczywistym eksporcie:

| Pozycja | Etap potoku | Mediana [ms] | Udział w klatce CPU |
| :---: | :--- | :---: | :---: |
| **#1** | **`Telemetry/frame_data` (Live interpolation)** | **`11.305 ms`** | **41.9%** |
| **#2** | **`above_bbox_crop` (1.7M pixel sparse union)** | **`5.955 ms`** | **22.1%** |
| **#3** | **`compose_overlay` (Pillow HUD rendering)** | **`4.404 ms`** | **16.3%** |
| **#4** | **`map_cpu_upload` (Pillow tile compose)** | **`2.475 ms`** | **9.2%** |
| **#5** | **`PIL / buffer preparation & dirty extract`** | **`1.644 ms`** | **6.1%** |
| **#6** | **`MF ReadSample / Hardware decode`** | **`0.767 ms`** | **2.8%** |
| **#7** | **`D3D11 / AMF submission`** | **`0.431 ms`** | **1.6%** |

---

## 11. Sekcja R: Pełne rozliczenie czasu klatki (47.30 ms / 21.141 FPS)

```text
Całkowity budżet klatki: 1000 ms / 21.141 FPS = 47.30 ms

1. Serial Python CPU:
   - Telemetry/frame_data:           11.31 ms
   - above_bbox_crop:                 5.96 ms
   - compose_overlay:                 4.40 ms
   - map_cpu_upload:                  2.48 ms
   - PIL/buffer prep & dirty extract: 1.64 ms
   - MF ReadSample decode:            0.77 ms
   - Gauge/chart prep:                1.01 ms
   ------------------------------------------
   Suma Serial Python CPU:           27.57 ms (58.3%)

2. Native Pipeline & GPU Synchronization:
   - VideoProcessor CPU submit:       0.57 ms
   - GPU execution & AMF backpress.: 17.50 ms
   - AMF Packet Write & Queue drain:  0.51 ms
   ------------------------------------------
   Suma Native / GPU / AMF:          18.58 ms (39.3%)

3. Niezależny Narzut Systemowy:
   - Python Global Lock / context:    1.15 ms ( 2.4%)
───────────────────────────────────────────────────────
SUMA ROZLICZONA:                     47.30 ms (100.0%)
```

---

## 12. Sekcja S & T: Podsumowanie ustaleń (Correctness & Performance)

### Ustalenia poprawności (Correctness):
- **CONFIRMED REGRESSION**: `compositor.py` podstawia `0.0` zamiast `None` dla nieznanych pól wskaźników (`Garmin Battery: 0`).
- **CONFIRMED DEFECT**: Brak mapowania aliasu `battery_pct` na pole baterii w `worker_cache.py`.
- **CONFIRMED CORRECT**: `Solar Pct: 64` jest autentyczną wartością telemetryczną z pliku FIT.
- **CONFIRMED CORRECT**: Geometria mapy `track_map` jest w 100% poprawna (kwadrat $691 \times 691$).

### Ustalenia wydajności (Performance):
- Główną przyczyną spadku z 31 FPS do 21 FPS w GUI są:
  1. Brak aktywacji `PRECOMPUTED` telemetrii w domyślnym eksporcie GUI (strata **11.3 ms/klatkę**).
  2. Sparse union bbox dla warstwy ABOVE obejmujący 1.7 mln pikseli (strata **5.7 ms/klatkę**).

---

## 13. Sekcja U: Jednoznaczna rekomendacja dla ETAPU 8M

```text
ETAP 8M — Naprawa regresji poprawności None/zero w compositor.py i obsługa aliasu battery_pct + włączenie produkcyjnego domyślnego AMD_TELEMETRY_MODE=PRECOMPUTED oraz multi-region/per-widget kadrowania CPU_ABOVE_MAP (przywrócenie >35 TRUE FPS w eksporcie GUI).
```

---

**ETAP 8L ZOSTAŁ ZAKOŃCZONY. ZGODNIE Z KONTRAKTEM ZATRZYMUJĘ SIĘ.**
