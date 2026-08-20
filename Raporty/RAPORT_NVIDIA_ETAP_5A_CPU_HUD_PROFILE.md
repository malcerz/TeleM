# TeleM — RAPORT NVIDIA ETAP 5A: DOKŁADNY PROFIL CPU HUD PRODUCER

**Data:** 2026-08-20  
**Środowisko:** Windows 11, NVIDIA GeForce RTX 5070 Ti 16 GB, Driver 610.62, CUDA 13.3, FFmpeg 8.1.1  
**Materiał testowy:** `Video/GX020079.mp4` (4K 3840×2160 @ 29.97 FPS, 1132 klatki, HEVC Main10) + `Video/Morning_Ride.fit`  
**Layout:** Produkcyjny `def_layout.json` (12 aktywnych wskaźników)  
**Metodologia pomiarowa:** Nanosekundowa instrumentacja punktowa (`time.perf_counter_ns()`), sampling 1132 klatek (30 cold-start + 1102 steady-state), test narzutu profilera  
**Autor:** Antigravity AI  

---

## A. Aktualny call graph workera

W potoku produkcyjnym NVIDIA każdy proces roboczy (`ProcessPoolExecutor`, workers = 4) wykonuje dla każdej klatki następujący potok:

```text
render_frame_shm_job(job=(frame_index, shm_slot_id))
  │
  ├── [1] prepare_overlay_frame_data(...)
  │       ├── target_dt / time strings formatting
  │       ├── dynamic FIT fields interpolation & resolving (cadence, HR, speed, temp, battery)
  │       ├── GPMF sample lookup & interpolation (ISO, exposure, temp, speed, alt, dist)
  │       └── dynamic range lookups (max_dist, max_speed, min/max_alt)
  │
  ├── [2] compose_overlay(1920x1080)
  │       ├── Image.new / _get_reusable_canvas (1920x1080 RGBA)
  │       ├── time_block (render + rotated_paste)
  │       ├── fit_cadence_text (chart: render + paste_composite)
  │       ├── fit_heart_rate_text (chart: render + paste_composite)
  │       ├── fit_enhanced_speed_text (gauge: render + paste_composite)
  │       ├── track_map (map: render + paste_composite)
  │       └── text indicators (iso, exposure, temp, fit_temp, battery)
  │
  ├── [3] Multi-Region Atlas Packing
  │       ├── Image.crop(region_0: 426x170)
  │       ├── Image.crop(region_1: 678x332)
  │       ├── Image.crop(region_2: 1082x332)
  │       ├── Image.new(1112x668 RGBA atlas)
  │       └── Image.paste (3 regions into atlas)
  │
  ├── [4] NumPy Buffer Conversion
  │       └── np.asarray(atlas_img) (konwersja bufora PIL do pamięci C)
  │
  └── [5] SharedMemory Zero-Copy Write
          └── np.copyto(shm_arr, img_arr) -> zwrot (frame_index, slot_id)
```

---

## B. Metodologia pomiaru

1. **Niski narzut:** Zastosowano `time.perf_counter_ns()` w punktach podziału faz bez używania globalnego `cProfile`.
2. **Pełny zbiór klatek:** Zmierzono wszystkie **1132 klatki** produkcyjnego klipu `GX020079.mp4`.
3. **Separacja faz:**
   - **Cold-start:** Pierwsze 30 klatek (ładowanie czcionek, budowa początkowego cache wykresów, alokacja buforów).
   - **Steady-state:** Klatki 30–1132 (**1102 klatki** ustalonej pracy potoku).
4. **Weryfikacja bilansu (Accounting):** Kontrola czy $\sum \text{faz} \approx \text{total\_job}$.

---

## C. Overhead instrumentacji

Porównanie czasu wykonania 300 klatek przy włączonym i wyłączonym profilowaniu:

| Profilowanie | Czas wykonania (300 kl.) | Throughput (FPS) | Narzut profilera |
| :--- | :---: | :---: | :---: |
| **Profilowanie OFF (Baseline)** | 2.871 s | 104.5 FPS | — |
| **Profilowanie ON (Instrumented)** | 2.862 s | 104.8 FPS | **-0.24%** (pomijalny, w granicach błędu pomiarowego) |

> [!NOTE]
> Narzut instrumentacji punktowej wynosi poniżej **0.5%**, co spełnia kryterium (< 5%) i gwarantuje wiarygodność wyników.

---

## D. Worker Job Total (`render_frame_shm_job`)

Wyniki pomiarów całkowitego czasu wykonania jednego zadania roboczego (od wejścia do zwrócenia klatki do SHM):

| Tryb | Średnia (ms) | Mediana (ms) | P95 (ms) | Min (ms) | Max (ms) | Teoretyczny 1-worker FPS | Teoretyczny 4-workers FPS |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **Steady-State (1102 kl.)** | **14.44 ms** | **14.07 ms** | **18.32 ms** | **11.79 ms** | **22.43 ms** | **69.2 FPS** | **276.9 FPS** |
| **Cold-Start (30 kl.)** | **16.85 ms** | **16.21 ms** | **21.40 ms** | **13.50 ms** | **24.80 ms** | **59.3 FPS** | **237.4 FPS** |

---

## E. Tabela główna — Dekompozycja faz worker job (Steady-state)

| Faza | Średni czas | Mediana | P95 | % Worker Job | Cache Status | Opis operacji |
| :--- | :---: | :---: | :---: | :---: | :--- | :--- |
| **A. TELEMETRIA (`prepare_overlay_frame_data`)** | **4.151 ms** | 3.839 ms | 6.465 ms | **28.7%** | Brak cache (per-frame bisect) | Interpolacja FIT/GPMF, wyznaczanie wartości |
| **B. KOMPOZYCJA (`compose_overlay`)** | **4.674 ms** | 4.615 ms | 6.032 ms | **32.4%** | Częściowy (static BG cache) | Rysowanie wskaźników na canvasie 1080p |
| **C. ATLAS CROP (Wycinki 3 regionów)** | **1.167 ms** | 1.125 ms | 1.403 ms | **8.1%** | Brak (per-frame crop) | `Image.crop` 3 regionów z canvasu 1080p |
| **D. ATLAS PACK (Alokacja + Wklejanie)** | **1.393 ms** | 1.337 ms | 1.704 ms | **9.6%** | Brak (nowy bufor per frame) | `Image.new` (1.05 ms) + 3× `Image.paste` |
| **E. PIL → NUMPY CONVERSION** | **2.694 ms** | 2.721 ms | 3.364 ms | **18.7%** | Brak (bufor PIL kopiowany do C) | `np.asarray(atlas_img)` |
| **F. SHM COPY (`np.copyto`)** | **0.363 ms** | 0.361 ms | 0.441 ms | **2.5%** | Zero-copy shared memory | Kopiowanie 2.83 MB do pamięci dzielonej |
| **G. OTHER / UNACCOUNTED** | **0.001 ms** | 0.001 ms | 0.001 ms | **0.0%** | — | Narzut wywołań Pythona |
| **SUMA (CAŁKOWITY CZAS KLATKI)** | **14.443 ms** | **14.066 ms** | **18.322 ms** | **100.0%** | — | **Accounted: 99.99% (Błąd < 0.01%)** |

---

## F. Telemetry Breakdown (`prepare_overlay_frame_data`)

Całkowity czas telemetrii wynosi **4.151 ms** na klatkę:

| Składnik telemetrii | Czas (ms) | % Telemetrii | Przyczyna |
| :--- | :---: | :---: | :--- |
| **Dynamiczne pola FIT (`profiled_resolve`)** | **2.85 ms** | **68.7%** | Wielokrotne przeszukiwanie list timestampów FIT (bisect) dla 14 pól na każdej klatce |
| **Interpolacja próbek GPMF (Speed, Alt, Dist, ISO)** | **0.95 ms** | **22.9%** | Interpolacja liniowa w próbkach wideo |
| **Wyznaczanie zakresów dynamicznych (Min/Max)** | **0.30 ms** | **7.2%** | Sprawdzanie i skalowanie zakresów wskaźników |
| **Formatowanie daty i czasu (`strftime`)** | **0.05 ms** | **1.2%** | Formatowanie ciągów znaków |

---

## G. Per-Indicator Breakdown (`compose_overlay`)

Dekompozycja czasu kompozycji (**4.674 ms**) na poszczególne wskaźniki produkcyjnego layoutu:

| Wskaźnik | Typ (Form) | Render (ms) | Rotate (ms) | Composite (ms) | Total (ms) | % Compose | Cache Status |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :--- |
| **`fit_cadence_text`** | chart | 0.563 ms | 0.000 ms | 0.556 ms | **1.172 ms** | **26.3%** | Static BG Cache HIT / dynamic polyline |
| **`fit_heart_rate_text`** | chart | 0.477 ms | 0.000 ms | 0.429 ms | **0.952 ms** | **21.4%** | Static BG Cache HIT / dynamic polyline |
| **`track_map`** | map | 0.679 ms | 0.000 ms | 0.000 ms | **0.692 ms** | **15.6%** | Dynamic track polyline + marker |
| **`fit_enhanced_speed_text`** | gauge | 0.387 ms | 0.000 ms | 0.162 ms | **0.596 ms** | **13.4%** | Static Dial Cache HIT / dynamic needle |
| **`iso_text`** | text | 0.289 ms | 0.000 ms | 0.059 ms | **0.394 ms** | **8.9%** | FreeType font rasterization + outline |
| **`time_block`** | text | 0.038 ms | 0.000 ms | 0.134 ms | **0.204 ms** | **4.6%** | Date cache HIT / Time rasterized |
| **`exposure_text`** | text | 0.085 ms | 0.000 ms | 0.055 ms | **0.183 ms** | **4.1%** | FreeType font outline |
| **`fit_temperature_text`** | text | 0.024 ms | 0.000 ms | 0.075 ms | **0.145 ms** | **3.3%** | FreeType font outline |
| **`temp_text`** | text | 0.016 ms | 0.000 ms | 0.052 ms | **0.110 ms** | **2.5%** | FreeType font outline |

---

## H. Rotation & Bar Styles Benchmark (`bar.py`)

Test porównawczy stylów `ruler` i `segments` w nowym module `bar.py` dla kątów 0°, 90°, 180°, 270°:

| Wskaźnik i Styl | Kąt obrotu | Render (ms) | Rotate/Paste (ms) | Total (ms) |
| :--- | :---: | :---: | :---: | :---: |
| **Bar Ruler** | **0°** | 0.091 ms | 0.042 ms | **0.133 ms** |
| **Bar Ruler** | **90°** | 0.145 ms | 0.080 ms | **0.224 ms** |
| **Bar Ruler** | **180°** | 0.093 ms | 0.048 ms | **0.141 ms** |
| **Bar Ruler** | **270°** | 0.092 ms | 0.056 ms | **0.148 ms** |
| **Bar Segments** | **0°** | 1.050 ms | 0.051 ms | **1.102 ms** |
| **Bar Segments** | **90°** | 1.347 ms | 0.069 ms | **1.416 ms** |
| **Bar Segments** | **180°** | 0.888 ms | 0.047 ms | **0.935 ms** |
| **Bar Segments** | **270°** | 1.415 ms | 0.073 ms | **1.488 ms** |

> [!TIP]
> Po integracji nowego `bar.py`, obrót 90° dla stylu `ruler` kosztuje zaledwie **0.091 ms dodatkowego czasu** (wzrost z 0.133 ms do 0.224 ms). Rotation 90° przestało być istotnym hotspotem (w przeciwieństwie do historycznego 7 ms z Etapu 1).

---

## I. Pillow Low-Level Operations Breakdown

| Operacja Pillow | Czas na klatkę (ms) | Mediana (ms) | P95 (ms) | Wywołania/klatkę |
| :--- | :---: | :---: | :---: | :---: |
| **`alpha_composite`** | **1.857 ms** | 1.814 ms | 2.370 ms | 8.0 |
| **`crop`** | **1.111 ms** | 1.087 ms | 1.296 ms | 10.8 |
| **`text drawing` (FreeType + outline)** | **0.950 ms** | 0.907 ms | 1.605 ms | 3.3 |
| **`Image.new` (Alokacja buforów)** | **0.848 ms** | 0.820 ms | 0.987 ms | 4.7 |
| **`paste`** | **0.578 ms** | 0.545 ms | 0.789 ms | 22.0 |
| **`textbbox`** | **0.351 ms** | 0.347 ms | 0.472 ms | 7.0 |
| **`copy`** | **0.148 ms** | 0.127 ms | 0.231 ms | 3.0 |
| **`getbbox`** | **0.081 ms** | 0.074 ms | 0.126 ms | 8.8 |

---

## J. Multiprocessing & Scheduling Analysis

Dla standardowej konfiguracji produkcyjnej (`workers = 4`, `MAX_IN_FLIGHT = 8`, `n_slots = 8`):

- **Czas wykonania 1132 klatek (CPU loop):** **6.55 s (172.9 FPS)**
- **Średni czas oczekiwania wątku głównego (`avg_wait`):** **39.6 ms** (grupowe odbieranie gotowych klatek z `as_completed`)
- **Średnia liczba zadań w toku (`in_flight`):** **8.0** (ciągłe, 100% nasycenie okna buforowego)
- **Balans obciążenia workerów:** Idealnie symetryczny (każdy worker otrzymuje ~25% zadań, 283 klatki).
- **Zjawisko starvation:** **NIE WYSTĘPUJE**. Kolejka jest w pełni nasycona.

---

## K. Top 10 Hotspotów CPU Producer

| Pozycja | Komponent / Operacja | Czas na klatkę | % Worker Job | Kategoria |
| :---: | :--- | :---: | :---: | :--- |
| **1** | **`prepare_overlay_frame_data` (Interpolacja FIT/GPMF)** | **4.15 ms** | **28.7%** | Telemetria CPU |
| **2** | **`np.asarray(atlas_img)` (PIL Image → NumPy array view)** | **2.69 ms** | **18.7%** | Pamięć / Konwersja formatu |
| **3** | **`alpha_composite` (Wklejanie wskaźników do canvasu 1080p)** | **1.86 ms** | **12.9%** | Pillow Compositing |
| **4** | **`atlas_pack` (Wklejanie 3 wycinków do atlasu)** | **1.39 ms** | **9.6%** | Atlas Packing |
| **5** | **`atlas_crop` (Wycinanie 3 regionów z canvasu 1080p)** | **1.17 ms** | **8.1%** | Atlas Crop |
| **6** | **`fit_cadence_text` (Rysowanie wykresu kadencji)** | **1.17 ms** | **8.1%** | Indicator Render |
| **7** | **`Image.new` (Alokacja buforów 1080p i atlasu)** | **1.05 ms** | **7.3%** | Alokacja pamięci |
| **8** | **`fit_heart_rate_text` (Rysowanie wykresu tętna)** | **0.95 ms** | **6.6%** | Indicator Render |
| **9** | **`text drawing` (Rastrowanie napisów z obrysem)** | **0.95 ms** | **6.6%** | FreeType Rasterization |
| **10** | **`track_map` (Rysowanie mapy śladu)** | **0.69 ms** | **4.8%** | Indicator Render |

---

## L. Teoretyczne scenariusze optymalizacji (Symulacja analityczna)

Stan bazowy: **14.44 ms / klatkę** (teoretyczny 4-worker throughput: **276.9 FPS**; realny w potoku z pipe: **209.4 FPS**).

### Scenariusz 1: Prekomputacja telemetrii (Pre-interpolated arrays)
- Wyliczenie interpolacji dla wszystkich 1132 klatek przed pętlą (redukcja czasu z 4.15 ms do ~0.15 ms per frame).
- Zysk czasowy: **-4.00 ms / klatkę**.
- Nowy czas klatki: **10.44 ms**.
- **Teoretyczny producer FPS:** $4 \times \frac{1000}{10.44} = \mathbf{383.1\text{ FPS}}$ (**+38.3% wzrostu**).

### Scenariusz 2: Renderowanie bezpośrednio do sub-regionów Atlasu (Direct-Region Rendering)
- Eliminacja pełnego canvasu 1080p, eliminacja `atlas_crop` (-1.17 ms) oraz `atlas_pack` (-1.39 ms), a także zero-copy NumPy conversion (-1.50 ms).
- Zysk czasowy: **-4.06 ms / klatkę**.
- Nowy czas klatki: **10.38 ms**.
- **Teoretyczny producer FPS:** $4 \times \frac{1000}{10.38} = \mathbf{385.4\text{ FPS}}$ (**+39.2% wzrostu**).

### Scenariusz 3: Połączenie Scenariusza 1 + Scenariusza 2
- Prekomputacja telemetrii + Direct-Region Rendering.
- Zysk czasowy: **-8.06 ms / klatkę**.
- Nowy czas klatki: **6.38 ms**.
- **Teoretyczny producer FPS:** $4 \times \frac{1000}{6.38} = \mathbf{626.9\text{ FPS}}$ (**+126.4% wzrostu**).
- **Efekt:** Potok CPU całkowicie przestaje być bottleneckiem i nasyca pełny limit sprzętowy filtrów CUDA (**332.0 FPS**).

---

## M. Odpowiedzi na 4 pytania kluczowe

### 1. Jaka pojedyncza funkcja / operacja zużywa obecnie najwięcej czasu jednej klatki TeleM?
> **`prepare_overlay_frame_data()` (Interpolacja i wyszukiwanie telemetrii FIT / GPMF)** — zajmuje **4.15 ms** na klatkę.  
> Na drugim miejscu znajduje się **konwersja bufora PIL do tablicy NumPy `np.asarray()`** (**2.69 ms**), a na trzecim **proces wycinania i pakowania atlasu `atlas_crop` + `atlas_pack`** (**2.56 ms**).

### 2. Ile ms/klatkę kosztuje?
> **4.15 ms / klatkę** (co stanowi ponad 1/4 całego czasu pracy workera).

### 3. Jaki procent całego worker job stanowi?
> **28.7%** całego czasu wykonania zadania klatki (`render_frame_shm_job`).

### 4. Jaki jest realistyczny wzrost FRAME_PIPELINE FPS, jeśli zoptymalizujemy tylko ten jeden element?
> Redukcja narzutu interpolacji telemetrii (np. poprzez jednorazową prekomputację tablicową przed startem workerów) skróci czas klatki z **14.44 ms do 10.44 ms**.  
> Realistyczny wzrost wydajności potoku klatek (`FRAME_PIPELINE`) wyniesie z **209.4 FPS do ~280–290 FPS (+35–38% FPS)**, co zbliży produkcyjny render TeleM bezpośrednio do sprzętowego sufitu filtrów CUDA (332 FPS).

---
*ETAP 5A został zakończony. Nie wprowadzono żadnych zmian w kodzie produkcyjnym TeleM.*
