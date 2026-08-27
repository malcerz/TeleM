# RAPORT AMD MAP ETAP 1 — Eliminacja Tile-Miss i Synchronicznego Pobierania Mapy

**Data:** 2026-08-25  
**Autor:** Gemini 3.7 Flash  
**Projekt:** TeleM (Gałąź AMD)  
**Cel:** Eliminacja synchronicznych zapytań sieciowych HTTP w pętli renderującej klatki, zapewnienie 100% pre-cachingu kafelków mapy dla pełnej trasy i docelowej rozdzielczości (4K / margin 3 / zoom 16), zagwarantowanie `HTTP REQUESTS DURING VIDEO FRAME LOOP = 0`.

---

## 1. Root Cause Poprzednich 33.982 ms i Analiza Wydajności CPU Mapy

Przed wykonaniem MAP ETAP 1 zidentyfikowano dwa główne czynniki wpływające na czas `map_cpu_upload`:

1. **Niedopasowanie marginesu pre-cache (`margin=2` vs wymagany `margin=3` dla 4K Track-Up):**
   * Przy 4K (3840×2160) rozmiar widgetu mapy wynosi ~691 px, a po powiększeniu do kwadratu obrotu Track-Up (`math.ceil(691 * sqrt(2))`) working image wynosi **978×978 px**.
   * Wycięcie takiego kadru wymaga promienia $\lceil 978 / 512 \rceil + 1 = 3$ kafelków wokół punktu GPS (siatka $7 \times 7$ kafelków, czyli `margin=3`).
   * Poprzedni mechanizm `background_precache` pobierał wyłącznie `margin=2` (siatka $5 \times 5$). W efekcie kafelki na obrzeżach siatki były notorycznie pomijane przy preloadzie i wywoływały synchroniczne zapytania HTTP w trakcie renderowania klatek wideo.
2. **Koszt operacji CPU przy obrocie i rasteryzacji (Pillow BICUBIC + Track-Up):**
   * Po wyeliminowaniu sieci do zera (`network_requests = 0`), stały koszt CPU `map_cpu_upload` wynosi stabilne ~34 ms.
   * Składa się na niego:
     * Pillow `rotate(BICUBIC)` na buforze 978×978 RGBA: ~20–25 ms,
     * Kadrowanie (crop do 691×691) i rysowanie markera: ~2–4 ms,
     * Kształt mapy (`apply_map_shape`) i serializacja do surowych bajtów (`tobytes("raw", "RGBA")`): ~2–3 ms,
     * Rysowanie polilinii trasy z antyaliasingiem przy zmianie kafelka siatki: ~5–10 ms.

---

## 2. Tile Accounting (Bilans Kafelków podczas Renderowania 1131 Klatek)

Dla testowego eksportu 1131 klatek 4K (`GX010115.MP4` + `Jazda_na_rowerze_w_porze_lunchu.fit`):

```text
required (cała trasa, zoom 16, margin 3): 334 kafelki
memory hits (w RAM LRU):                   72 - 78
disk hits (z SQLite):                     305 - 311
network downloads during preload:         55 (zimny cache) / 0 (ciepły cache)
missing at render start:                  0
network requests during video frame loop: 0
network misses during video frame loop:   0
```

---

## 3. Wprowadzone Zmiany w Kodzie

### 1. `src/moving_map.py`
* **`MapTileStats`**: Dodano wątkowo bezpieczną klasę zliczającą `tiles_requested`, `memory_hits`, `disk_hits`, `network_misses`, `network_requests`.
* **`is_map_network_allowed() / set_map_network_allowed(bool)`**: Dodano globalną bramkę sieciową. Podczas pętli renderującej klatki wideo sieć jest bezwzględnie blokowana (`set_map_network_allowed(False)`). Jeśli jakikolwiek kafelek nie zostałby znaleziony, logowane jest zdarzenie `[MAP CACHE MISS DURING RENDER]` bez blokowania procesu na zapytaniu HTTP.
* **`TileCache.has(z, x, y, style)`**: Dodano szybką metodę sprawdzania obecności kafelka w SQLite bez konieczności kosztownego dekodowania obrazu PNG do pamięci.

### 2. `src/indicators/moving_map.py`
* **`map_required_tile_margin(canvas_w, map_w, track_up)`**: Dynamiczne wyliczanie wymaganego marginesu siatki w zależności od rozdzielczości wyjściowej (np. `margin=3` dla 4K Track-Up, `margin=2` dla 1080p).
* **`ensure_map_tiles_cached(canvas_w, canvas_h, layout, key, gps_track, ...)`**: Uniwersalna funkcja weryfikująca i pobierająca 100% brakujących kafelków dla całej trasy przed rozpoczęciem pętli generowania klatek.
* **`render_map_working_image`**: Wykorzystanie dynamicznego marginesu oraz zablokowanie synchronicznego downloadu przy renderowaniu klatek.

### 3. `src/ffmpeg/amd_native_exporter.py`
* Przed rozpoczęciem pętli klatek (przed `PRECOMPUTE_BEGIN`) wywoływane jest `ensure_map_tiles_cached`.
* Pętla renderująca klatki jest otoczona blokiem `set_map_network_allowed(False)` / `finally: set_map_network_allowed(True)`.
* Po zakończeniu renderowania raportowane są dokładne statystyki `[AMD Map Tile Stats]`.

### 4. `src/gui/map_preload.py`
* Dwufazowy preload w `MapPreloadWorker`:
  * **Faza 1 (Level 1):** Błyskawiczny download kafelków overview (~12–16 sztuk) i natychmiastowe wyemitowanie `set_ready` dla GUI (< 1s).
  * **Faza 2 (Level 2):** Dalsze pobieranie w tle szczegółowych kafelków dla trasy (zoomy 14, 15, 16 z `margin=3`), aby w momencie kliknięcia "Renderuj" 100% kafelków było już w dyskowym cache.

---

## 4. Test COLD CACHE (Zimny Cache + Preload)

* **Warunki:** Kafelki dla zoomu 16 z marginesem 3 nie były wcześniej w całości pobrane (55 brakujących kafelków).
* **Przed startem renderera:** `[Map Preload] Pre-caching 55/334 missing tiles (provider=satellite, zoom=16, margin=3)...`
* **Czas pobierania przed pierwszą klatką:** 17.8 s
* **Czas renderowania wideo (1131 klatek 4K):** 102.343 s
* **RENDER FPS:** **11.051 FPS**
* **`map_cpu_upload` AVG:** **34.233 ms**
* **HTTP Requests podczas renderowania wideo:** **0**

---

## 5. Test WARM CACHE (Ciepły Cache)

* **Warunki:** Wszystkie 334 kafelki obecne w SQLite / RAM cache.
* **Przed startem renderera:** `cached=334, downloaded=0, missing=0`
* **Czas przed pierwszą klatką:** 0.952 s
* **Czas renderowania wideo (1131 klatek 4K):** 103.239 s
* **RENDER FPS:** **10.955 FPS**
* **USER EFFECTIVE FPS:** **10.181 FPS**
* **`map_cpu_upload` AVG:** **34.364 ms**
* **HTTP Requests podczas renderowania wideo:** **0**

---

## 6. Benchmark Porównawczy (4K / 1131 Klatek)

| Metric | BEFORE PORT | AFTER PORT | MAP ETAP 1 (COLD) | MAP ETAP 1 (WARM) |
| :--- | :---: | :---: | :---: | :---: |
| **MF ReadSample** | 0.872 ms | 0.816 ms | **0.777 ms** | **0.791 ms** |
| **compose_overlay** | 2.457 ms | 5.666 ms | **5.146 ms** | **6.017 ms** |
| **map_cpu_upload** | **73.070 ms** | **33.982 ms** | **34.233 ms** | **34.364 ms** |
| **above_compose** | 35.638 ms | 25.805 ms | **25.818 ms** | **26.077 ms** |
| **above_total** | 40.835 ms | 33.829 ms | **33.397 ms** | **33.466 ms** |
| **producer_prepare** | 122.154 ms | 79.629 ms | **78.894 ms** | **79.798 ms** |
| **consumer_native_call** | 2.694 ms | 5.079 ms | **5.615 ms** | **5.551 ms** |
| **pipeline_total** | 6.187 ms | 10.903 ms | **10.829 ms** | **10.610 ms** |
| **RENDER FPS** | **7.893** | **10.958** | **11.051** | **10.955** |
| **USER EFFECTIVE FPS** | **7.663** | **10.223** | **8.887\*** | **10.181** |
| **HTTP during frame loop** | Non-zero | Non-zero | **0** | **0** |
| **Tile misses during loop**| Unknown | Unknown | **0** | **0** |

*\*Uwaga: USER EFFECTIVE FPS dla Cold Cache zawiera jednorazowy czas wstępnego pobrania 55 kafelków z sieci przed pierwszą klatką (17.8 s). Sam proces renderowania wideo osiąga identyczne 11.051 FPS.*

---

## 7. Weryfikacja Wizualna (Visual Parity)

Wyodrębniono klatkę 0 (`scratch/map_etap1_test/frame_0000.png`) z wyrenderowanego pliku MP4:
* Kafelki satelitarne, orientacja Track-Up, wycięcie i obrót są w 100% ostre i kompletne.
* Czerwona linia śladu GPS, biały okrągły marker pozycji, wszystkie wskaźniki HUD, wykresy tętna i kadencji, wskaźniki słupkowe i cyfrowe są wyrenderowane prawidłowo i identycznie z referencją.

---

## 8. Zmodyfikowane Pliki

* `src/moving_map.py`
* `src/indicators/moving_map.py`
* `src/ffmpeg/amd_native_exporter.py`
* `src/gui/map_preload.py`
* `tests/test_map_cold_warm_preload.py` (nowy test jednostkowy)
* `scratch/test_map_cold_warm_1131.py` & `scratch/run_map_etap1_benchmarks.py`

---

## 9. Ryzyka i Zachowanie Ścieżek

* **Zachowanie ścieżek:** Wszystkie ścieżki NVIDIA CUDA oraz renderer Intel pozostały nienaruszone.
* **Zachowanie AMD ETAP 1A / 1B:** Logika klasyfikacji AFTER-MAP i native blend pozostały zachowane i przetestowane.
* **Tryb Offline:** Gdy brak połączenia z siecią, brakujące kafelki nie blokują pętli; mapa renderuje dostępne kafelki lub szare tło z zachowaniem ciągłości trasy.

---

## 10. Podsumowanie Wymagane

```text
AMD MAP ETAP 1 COMPLETE
FULL ROUTE PRELOAD: PASS
CORRECT PROVIDER PRELOAD: PASS
HTTP DURING FRAME LOOP: 0
MAP VISUAL PARITY: PASS
MAP_CPU_UPLOAD COLD: 34.233 ms
MAP_CPU_UPLOAD WARM: 34.364 ms
RENDER FPS: 10.955
AMD ETAP 1A/1B PRESERVED: YES
NVIDIA UNCHANGED: YES
INTEL RENDERER UNCHANGED: YES
```
