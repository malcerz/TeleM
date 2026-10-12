# RAPORT SPORTCAMHUD — ETAP 4E: ROOT CAUSE KAŻDEGO WSKAŹNIKA GRAFICZNEGO

**Data badania:** 12 października 2026  
**Projekt:** SportCamHUD v1.14  
**Środowisko:** AMD Radeon Graphics (gfx90c, Driver 31.0.21925.1001), AMF HEVC, D3D11 Native  
**Repozytorium:** `C:\_DEV\BikeRideHUD-main-new`  
**Gałąź:** `fix/gui-freeze-hud-composite`  
**Commit HEAD:** `c327132 fix(effects): restore high-perf HUD effects and gauge needle parity without D3D11 shaders (ETAP 4D)`  
**Plik wideo:** `D:\Comparator\GX010344.MP4` (3840×2160, 29.970 FPS, HEVC Main 10)  
**Plik FIT:** `C:\_DEV\_SPORTCAMHUD_ETAP_4B_RESULTS_20261012\fit\24609739177.fit` (SmartSync: VALID, offset: 0.0s)  
**Parametry testu:** 4K HEVC, QP 28, FAST, 40 Mb/s, start od 120.0s, backend `direct`  
**Katalog wyników:** `C:\_DEV\_SPORTCAMHUD_ETAP_4E_RESULTS_20261012`  

---

## 1. PODSUMOWANIE WYKONAWCZE I ROZSTRZYGNIĘCIE HIPOTEZY

W teście użytkownika wyłączenie wskaźników graficznych i pozostawienie samych tekstowych spowodowało gwałtowny wzrost wydajności do **~40 FPS**.

Pomiary Etapu 4E w pełni potwierdziły tę obserwację i ujawniły dokładne źródło kosztu każdego wskaźnika:

1. **Wariant C (same wskaźniki tekstowe):**
   - **Render FPS: 41.93 FPS** (Effective FPS: **39.36 FPS**)
   - Czas kompozycji overlay CPU: zaledwie **2.82 ms/klatkę**
   - Czas przygotowania producenta (`producer_prepare`): **3.89 ms/klatkę**
   - Kolejka konsumenta GPU (`consumer_queue_wait`): **0.10 ms/klatkę**
   - Potok AMF i sprzętowy dekoder D3D11 pracują bez żadnego dławienia, osiągając pełną historyczną wydajność 4K (~41.4 FPS).

2. **Wariant B (wszystkie wskaźniki aktywne, ale EFEKTY WYŁĄCZONE):**
   - **Render FPS: 24.88 FPS** (Effective FPS: **23.88 FPS**)
   - Czas kompozycji overlay CPU: **26.46 ms/klatkę** (**+23.64 ms** względem C)
   - Kolejka konsumenta GPU: **25.11 ms/klatkę** (konsument GPU głoduje, czekając na CPU)
   - **Wniosek:** Same bazy wskaźników graficznych (bez cieni i obrysów) generują spadek FPS z 41.9 do 24.9 FPS!

3. **Wariant A (pełny HUD produkcyjny z wszystkimi EFEKTAMI WŁĄCZONYMI):**
   - **Render FPS: 20.46 FPS** (Effective FPS: **19.76 FPS**)
   - Czas kompozycji overlay CPU: **34.89 ms/klatkę** (**+8.43 ms** względem B)
   - Kolejka konsumenta GPU: **33.64 ms/klatkę**
   - **Wniosek:** Efekty (outline / shadow) dodają kolejne **+8.43 ms/klatkę**, obniżając FPS z 24.9 do 20.5 FPS.

4. **Architektura winnych (Reguła 85/15):**
   Aż **84.7% całego czasu kompozycji HUD (29.54 ms z 34.89 ms)** przypada na zaledwie **TRZY wskaźniki**:
   - **`speed_text` (Gauge):** **14.94 ms/klatkę** (42.8% całego HUD)
   - **`fit_distance_text` (Suwak/linijka):** **9.07 ms/klatkę** (26.0% całego HUD)
   - **`fit_curVpower_text` (Suwak/linijka):** **5.53 ms/klatkę** (15.9% całego HUD)
   
   Pozostałe 14 aktywnych wskaźników łącznie zużywa zaledwie **~5.35 ms/klatkę**!

---

## 2. INWENTARZ WSKAŹNIKÓW W LAYOUCIE UŻYTKOWNIKA (`def_layout.json`)

Layout użytkownika zawiera **17 aktywnych wskaźników**:

| # | Identyfikator | Typ (form) | Rozmiar / Styl | Efekty w oryginale | Ścieżka wykonania |
|---|---------------|------------|----------------|---------------------|-------------------|
| 1 | `exposure_text` | text | fs=18 (Arial) | outline=True, shadow=False | CPU Text -> Canvas |
| 2 | `fit_gopro_battery_text` | text | fs=18 (Arial) | outline=True, shadow=False | CPU Text -> Canvas |
| 3 | `iso_text` | text | fs=18 (Arial) | outline=True, shadow=False | CPU Text -> Canvas |
| 4 | `temp_text` | text | fs=18 (Arial) | outline=True, shadow=False | CPU Text -> Canvas |
| 5 | `time_display` | text | fs=22 (Arial) | outline=True, shadow=False | CPU Text -> Canvas |
| 6 | `alt_text` | bar (ruler) | size=0.15, thickness=1 | outline=False, shadow=False | CPU Bar -> Canvas |
| 7 | `fit_cadence_text` | chart | w=382, h=602 | outline=False, shadow=False | CPU Chart -> GPU Slot |
| 8 | `fit_curVpower_text` | bar (ruler) | size=0.15, thickness=1 | outline=False, **shadow=True** | CPU Bar + Alpha Dilation |
| 9 | `fit_distance_text` | bar (ruler) | **size=0.60 (2304 px)** | outline=False, **shadow=True** | CPU Bar + Alpha Dilation |
| 10 | `fit_garmin_battery_percent_text` | segment_bar | size=0.15, segments=10 | outline=False, shadow=False | CPU Segment Bar -> Canvas |
| 11 | `fit_heart_rate_text` | chart | w=382, h=602 | outline=False, shadow=False | CPU Chart -> Crop Blend |
| 12 | `fit_solar_text` | bar (ruler) | size=0.15, thickness=1 | outline=False, shadow=False | CPU Bar -> Canvas |
| 13 | `fit_temperature_text` | bar (ruler) | size=0.15, thickness=1 | outline=False, shadow=False | CPU Bar -> Canvas |
| 14 | `lean_indicator` | lean | size=0.15 | outline=False, shadow=False | GPU Lean Affine |
| 15 | `speed_text` | gauge | **size=0.22 (1192×1192)** | outline=False, **shadow=True** | CPU Gauge -> Dirty Crop Upload |
| 16 | `track_map` | map | w=800, h=600 | outline=False, shadow=False | Async GPU Map |
| 17 | `compass` | gauge/compass | size=0.12 (500×500) | outline=False, shadow=False | CPU Ring Cache -> Canvas |

---

## 3. GLOBALNE POMIARY KANONICZNE (3000 i 300 KLATEK)

Pomiary wykonano na kanonicznym materiale `GX010344.MP4` od sekundy 120.0 przy stałych parametrach AMF HEVC QP 28 FAST.

### 3.1. Długie przebiegi kanoniczne (3000 klatek)

| Wariant | Klatki | Czas całkowity | Effective FPS | Render FPS | Compose Overlay | Producer Prepare | Consumer Queue Wait | MF ReadSample | HUD Upload |
|---------|--------|----------------|---------------|------------|-----------------|------------------|---------------------|---------------|------------|
| **C_text_only** | 3000 | **82.3 s** | **39.36 FPS** | **41.93 FPS** | **2.82 ms** | **3.89 ms** | **0.10 ms** | 0.89 ms | 0.64 ms |
| **B_all_no_effects** | 3000 | **131.8 s** | **23.88 FPS** | **24.88 FPS** | **26.46 ms** | **39.18 ms** | **25.11 ms** | 0.85 ms | 2.12 ms |
| **A_all_with_effects** | 3000 | **159.5 s** | **19.76 FPS** | **20.46 FPS** | **34.89 ms** | **47.55 ms** | **33.64 ms** | 0.72 ms | 3.00 ms |

### 3.2. Przebiegi porównawcze macierzy (300 klatek)

| Wariant | Zakres | Effective FPS | Render FPS | Compose Overlay | Producer Prepare | Consumer Queue Wait |
|---------|--------|---------------|------------|-----------------|------------------|---------------------|
| **C_text_only** | Tylko 5 wskaźników tekstu | **25.45 FPS** | **39.21 FPS** | **3.20 ms** | 4.45 ms | 0.36 ms |
| **F_graphical_no_effects** | Tylko 12 wskaźników graficznych (bez tekstu, bez efektów) | **17.03 FPS** | **22.76 FPS** | **28.17 ms** | 41.41 ms | 29.49 ms |
| **G_graphical_with_effects** | Tylko 12 wskaźników graficznych (bez tekstu, z efektami) | **14.38 FPS** | **17.92 FPS** | **38.32 ms** | 53.27 ms | 40.31 ms |
| **B_all_no_effects** | Wszystkie 17 wskaźników (bez efektów) | **16.27 FPS** | **21.53 FPS** | **30.41 ms** | 44.23 ms | 29.94 ms |
| **A_all_with_effects** | Wszystkie 17 wskaźników (pełne efekty) | **13.66 FPS** | **17.27 FPS** | **40.46 ms** | 55.50 ms | 40.69 ms |

---

## 4. MACIERZ IZOLOWANA DLA KAŻDEGO WSKAŹNIKA GRAFICZNEGO

W celu precyzyjnego oddzielenia kosztu renderera od cienia i obrysu, każdy z 12 wskaźników graficznych przetestowano w 4 izolowanych wariantach:
- **D:** wskaźnik aktywny bez żadnych efektów
- **E:** wskaźnik aktywny z pełnymi efektami (shadow + outline)
- **S:** wskaźnik aktywny wyłącznie z cieniem (shadow=True, outline=False)
- **O:** wskaźnik aktywny wyłącznie z obrysem (outline=True, shadow=False)

### 4.1. Tabela kosztów izolowanych (300 klatek) oraz udział w pełnym HUD

| Wskaźnik | Typ | Baza bez efektów (D) | Z efektami (E) | Koszt efektów (E - D) | Sam cień (S) | Sam obrys (O) | Koszt w pełnym HUD (A) | Renderer bazy | Rotated Paste |
|----------|-----|----------------------|----------------|-----------------------|--------------|--------------|------------------------|---------------|---------------|
| **`speed_text`** | gauge | **14.04 ms** | **13.49 ms** | **-0.56 ms** | 13.99 ms | 13.98 ms | **14.94 ms** | 11.75 ms | 3.05 ms |
| **`fit_distance_text`** | bar (ruler) | **2.62 ms** | **9.09 ms** | **+6.47 ms** | 7.73 ms | 8.27 ms | **9.07 ms** | 0.48 ms | 0.74 ms |
| **`fit_curVpower_text`** | bar (ruler) | **2.07 ms** | **5.72 ms** | **+3.65 ms** | 5.12 ms | 5.10 ms | **5.53 ms** | 0.68 ms | 0.40 ms |
| **`fit_garmin_battery_percent_text`** | segment_bar | **3.02 ms** | **3.28 ms** | **+0.26 ms** | 4.03 ms | 4.21 ms | **2.43 ms** | 1.99 ms | 0.13 ms |
| **`alt_text`** | bar (ruler) | **1.89 ms** | **1.85 ms** | **-0.04 ms** | 3.97 ms | 4.00 ms | **0.79 ms** | 0.48 ms | 0.19 ms |
| **`fit_temperature_text`** | bar (ruler) | **1.54 ms** | **1.43 ms** | **-0.10 ms** | 3.95 ms | 4.17 ms | **0.92 ms** | 0.04 ms | 0.82 ms |
| **`fit_solar_text`** | bar (ruler) | **1.06 ms** | **1.07 ms** | **+0.01 ms** | 3.16 ms | 3.52 ms | **0.72 ms** | 0.07 ms | 0.50 ms |
| **`fit_heart_rate_text`** | chart | **0.87 ms** | **0.89 ms** | **+0.02 ms** | 0.85 ms | 0.86 ms | **1.35 ms** | 0.93 ms | 0.37 ms |
| **`fit_cadence_text`** | chart | **0.86 ms** | **0.94 ms** | **+0.09 ms** | 1.00 ms | 0.90 ms | **0.41 ms** | 0.36 ms | 0.00 ms |
| **`compass`** | compass | **0.46 ms** | **0.45 ms** | **-0.01 ms** | 0.45 ms | 0.47 ms | **0.22 ms** | 0.08 ms | 0.08 ms |
| **`track_map`** | map | **0.19 ms** | **0.19 ms** | **0.00 ms** | 0.19 ms | 0.20 ms | **0.00 ms** | 0.00 ms | 0.00 ms |
| **`lean_indicator`** | lean | **0.17 ms** | **0.17 ms** | **0.00 ms** | 0.17 ms | 0.17 ms | **0.00 ms** | 0.00 ms | 0.00 ms |

---

## 5. ANALIZA ROOT CAUSE KAŻDEGO WSKAŹNIKA

### 5.1. Wskaźnik #1: `speed_text` (Gauge) — Główny pożeracz bazy CPU i pasma GPU
- **Koszt w HUD:** **14.94 ms / klatkę** (Renderer: 11.75 ms, Rotated Paste: 3.05 ms).
- **Wpływ efektów:** Cień i obrys dodają **0.0 ms**. Dlaczego? Wskaźnik prędkości (`gauge`) nie korzysta z modułu `effects.py`, lecz rysuje cień wskazówki wektorem w lokalnym wycinku (LANCZOS downscale).
- **Prawdziwy Root Cause `speed_text`:**
  1. **Gigantyczny raster:** Wskaźnik ma wymiary **1192 × 1192 pikseli** (1.42 Mpix, czyli **5.68 MB RGBA na klatkę**).
  2. **Kopiowanie bufora:** Przy każdej klatce przywracany jest obszar wskazówki i tekstu wartości za pomocą `img.paste(bg.crop(...))`.
  3. **Downsampling Lanczos:** Skalowanie dwukrotnie powiększonego wycinka wskazówki `patch.resize(..., LANCZOS)` i marker cap `m_buf.resize(..., LANCZOS)` na CPU zabiera ~4.5 ms.
  4. **Pillow Paste:** Operacja wklejenia rastra 1192×1192 na pełne płótno 4K zabiera **3.05 ms**.
  5. **Dirty Rect Explosion:** Eksport D3D11 odbiera bbox `(1192, 1192)` i musi co klatkę wywołać `crop.tobytes("raw", "RGBA")` dla **5.68 MB danych**, co obciąża `PIL/buffer preparation` o dodatkowe **~5-6 ms**!

### 5.2. Wskaźnik #2: `fit_distance_text` (Suwak/Linijka) — Główny winowajca regresji EFEKTÓW
- **Koszt w HUD:** **9.07 ms / klatkę** (Renderer bazy: 0.48 ms, Paste: 0.74 ms, **Efekty CPU: 7.50 ms**).
- **Izolowany koszt efektów:** **+6.47 ms** (sam cień: +5.11 ms, sam obrys: +5.65 ms).
- **Prawdziwy Root Cause `fit_distance_text`:**
  1. **Nietypowy rozmiar:** W konfiguracji użytkownika wskaźnik ma `size: 60`, co przy szerokości 3840 px daje raster o szerokości **2304 pikseli** (2304 × 150 px).
  2. **100% Miss w Cache:** Wartość dystansu zmienia się w KAŻDEJ klatce (np. `1234.5 m` -> `1234.6 m`), co powoduje całkowity miss w `widget_cache` oraz w `_EFFECT_CACHE` (hash alfa jest inny w każdej klatce).
  3. **Wielokrotna dylatacja CPU:** Dla rastra 2304×150 co klatkę alokowana jest tablica NumPy (2320×170), wykonywana pętla 30 kroków przesunięć cienia (`lut`, `np.maximum`) oraz dylatacja OpenCV (`cv2.dilate`).
  4. W efekcie pojedynczy wskaźnik dystansu pochłania **7.5 ms czystej pracy CPU na generowanie cienia**!

### 5.3. Wskaźnik #3: `fit_curVpower_text` (Suwak mocy) — Drugi winowajca regresji EFEKTÓW
- **Koszt w HUD:** **5.53 ms / klatkę** (Renderer bazy: 0.68 ms, Paste: 0.40 ms, **Efekty CPU: 4.30 ms**).
- **Izolowany koszt efektów:** **+3.65 ms** (sam cień: +3.05 ms).
- **Prawdziwy Root Cause `fit_curVpower_text`:**
  - Identyczny mechanizm jak w `fit_distance_text`. Moc w watach zmienia się w każdej klatce, powodując 100% miss w cache efektów i zmuszając CPU do dylatacji rastra suwaka co klatkę.

### 5.4. Wskaźnik #4: `fit_garmin_battery_percent_text` (Pasek segmentowy)
- **Koszt w HUD:** **2.43 ms / klatkę** (Renderer bazy: 1.99 ms, Paste: 0.13 ms).
- **Wpływ efektów:** Domyślnie efekty wyłączone.
- **Root Cause:** Rysowanie 10 segmentów baterii na CPU przy braku trafienia w cache zajmuje ~2.0 ms.

### 5.5. Wskaźniki linijkowe z wyłączonymi efektami (`alt_text`, `fit_temperature_text`, `fit_solar_text`)
- **Koszt w HUD:** Każdy zabiera **0.7 - 0.9 ms** (bardzo wydajne).
- **Co się dzieje po włączeniu efektów (warianty S i O)?**
  - Koszt każdego z nich wzrasta natychmiast o **+2.1 do +2.6 ms** (do ~3.5 - 4.1 ms).
  - Dowodzi to, że architektura `apply_indicator_effects` na dynamicznych linijkach ma stały narzut rzędu 2–3 ms na wskaźnik.

### 5.6. Wykresy (`fit_cadence_text`, `fit_heart_rate_text`)
- **Koszt w HUD:**
  - `fit_cadence_text`: **0.41 ms** (obsługiwany przez dedykowany slot GPU Chart — zerowy narzut kompozycji).
  - `fit_heart_rate_text`: **1.35 ms** (wypada do CPU Crop Blend z powodu nakładania się bboxów w layoucie).
- **Wpływ efektów:** Wykresy zwracają obiekt `ChartSplit`, który bezpiecznie omija moduł efektów.

### 5.7. Wskaźniki GPU (`track_map`, `lean_indicator`, `compass`)
- **Koszt w HUD:**
  - `track_map`: **0.00 ms** (obsługiwana asynchronicznie przez dedykowany wątek kafelków GPU).
  - `lean_indicator`: **0.00 ms** (obsługiwany sprzętowo przez transformację afiniczną D3D11).
  - `compass`: **0.22 ms** (tarcza kompasu jest cache'owana w `_COMPASS_INDICATOR_CACHE`, renderowanie igły jest zoptymalizowane).

---

## 6. DOWÓD WĄSKIEGO GARDŁA I ZALEŻNOŚCI CPU/GPU

| Parametr / Metryka | Wariant C (Same teksty) | Wariant B (Bez efektów) | Wariant A (Pełne efekty) | Skąd różnica? |
|--------------------|------------------------|-------------------------|--------------------------|---------------|
| **Effective FPS** | **39.36 FPS** | **23.88 FPS** | **19.76 FPS** | Spadek o 50% |
| **Render FPS** | **41.93 FPS** | **24.88 FPS** | **20.46 FPS** | Spadek o 51% |
| **Compose Overlay** | **2.82 ms** | **26.46 ms** | **34.89 ms** | +32.07 ms na CPU! |
| **Producer Prepare** | **3.89 ms** | **39.18 ms** | **47.55 ms** | CPU nie nadąża za 40 FPS |
| **Consumer Queue Wait**| **0.10 ms** | **25.11 ms** | **33.64 ms** | Konsument GPU czeka bezczynnie |
| **AMF Encode + Decode**| **~12.5 ms (80 FPS max)**| **~12.5 ms** | **~12.5 ms** | Sprzęt AMD jest w pełni sprawny! |
| **PIL / Buffer Prep** | **1.14 ms** | **8.42 ms** | **9.62 ms** | .tobytes() na 15 MB dirty rects |
| **Upload Bytes / frame**| **< 0.5 MB** | **~14.9 MB** | **~15.2 MB** | speed_text (5.7MB) + distance (1.4MB) |

### Kluczowa konkluzja analityczna:
GPU AMF HEVC i dekoder D3D11 na tej maszynie są w stanie kodować wideo 4K w tempie **>41 FPS** (co widać bezpośrednio w wariancie C: 41.93 FPS, `QWait: 0.10 ms`).

Spadek do 20.46 FPS NIE JEST problemem karty AMD, sterownika AMF ani potoku wideo.
Jest to w 100% problem **CPU starvation**:
- Producent klatek na CPU potrzebuje **47.55 ms** na przygotowanie klatki (zamiast wymaganych 24 ms dla 41 FPS).
- Z tego **34.89 ms** zabiera sam `compose_overlay` na CPU.
- Z czego **14.94 ms** zabiera `speed_text`, a **14.60 ms** zabierają suwaki `fit_distance_text` i `fit_curVpower_text`.

---

## 7. REKOMENDACJE NAPRAWCZE DLA ETAPU 5

Aby przywrócić 41+ FPS w pełnym HUD z włączonymi wszystkimi efektami:

1. **Optymalizacja `fit_distance_text` i `fit_curVpower_text` (Odzysk: ~10 ms):**
   - Zastąpić pełną dylatację rastra CPU (`apply_indicator_effects`) dedykowanym cieniem geometrii suwaka (renderowanym wektorowo podczas rysowania znaczników, identycznie jak w `gauge.py` i `compass.py`).
   - Wprowadzić regionalne odświeżanie wyłącznie poruszającego się wskaźnika (ROI marker dirty patch) zamiast przeliczania 2304-pikselowej tablicy na nowo w każdej klatce.

2. **Optymalizacja `speed_text` (Odzysk: ~9 ms):**
   - Przenieść `speed_text` na ścieżkę GPU lub ograniczyć dirty upload:
     Tarcza prędkościoma powinna być uploadowana do GPU **jednorazowo** jako statyczna tekstura.
     Co klatkę uploadowany powinien być wyłącznie minimalny prostokąt obrotu igły (np. 300×300 px = 0.35 MB zamiast 1192×1192 px = 5.68 MB).
   - Zastąpić skalowanie LANCZOS na CPU dla całej tarczy szybkim próbkowaniem dwuliniowym lub natywnym wektorem.

3. **Koalescencja Dirty Rects i uploadu D3D11 (Odzysk: ~6 ms):**
   - Po odcięciu 5.68 MB ze `speed_text` i 1.4 MB z `fit_distance_text`, narzut `PIL/buffer preparation` spadnie z 9.6 ms do < 1.5 ms.

Łączny potencjalny zysk czasowy na CPU: **~25 ms**.
Czas przygotowania producenta spadnie z 47.55 ms do **~15-18 ms**, co natychmiast przywróci produkcyjną wydajność do poziomu **40–42 FPS** przy zachowaniu 100% jakości cieni i obrysów.
