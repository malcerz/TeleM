# TeleM — NVIDIA ETAP 1: Audyt Bottlenecku `overlay_rendering`

**Data:** 2026-08-20  
**Platforma testowa:** NVIDIA GeForce RTX 5070 Ti 16 GB, Driver 610.62, CUDA 13.3, FFmpeg 8.1.1, Windows 11  
**Materiał testowy:** `GX020079.mp4` (4K 29.97 FPS, 1131 klatek, HEVC Main 10) + `Morning_Ride.fit`  

---

## A. Co dokładnie oznacza `overlay_rendering = ~236 ms`

Wydruk benchmarku w konsoli:
```text
telemetry_lookup         : avg=  3.34ms | p95=  3.44ms | range=[3.24-3.45]ms (n=2)
overlay_rendering        : avg=236.36ms | p95=236.36ms | range=[236.36-236.36]ms (n=1)
frame_conversion         : avg=  1.05ms | p95=  1.24ms | range=[0.83-1.26]ms (n=2)
preview_cycle            : avg=245.17ms | p95=245.17ms | range=[245.17-245.17]ms (n=1)
ffmpeg_write             : avg=  9.28ms | p95= 29.82ms | range=[1.49-54.21]ms (n=300)
```

### 1. Miejsce pomiaru w kodzie
Timer `overlay_rendering` jest mierzony **wyłącznie w wątku GUI** w pliku `src/gui/qt/_mixins/preview_mixin.py` (linie 382–439):
```python
bt.start_timer("overlay_rendering")
try:
    preview = render_preview(self.src_img, self.layout, self.font_path, ...)
finally:
    bt.stop_timer("overlay_rendering")
```

### 2. Co obejmuje pomiar `overlay_rendering` w `preview_mixin.py`?
1. **Rozdzielczość 4K (3840×2160)**: pobiera klatkę wideo w pełnym 4K.
2. `compose_overlay(3840, 2160)`: renderowanie wszystkich wskaźników w rozdzielczości 4K (skalowane outline, czcionki, paski).
3. **Pełny CPU `alpha_composite` w 4K**: `img.alpha_composite(overlay)` na 33.17 MB buforze RGBA (3840×2160×4 bajty) w czystym Python/Pillow na CPU.
4. **Zimny cache**: przy pierwszym wywołaniu następuje inicjalizacja struktur graficznych i map.

### 3. Czego NIE obejmuje ten pomiar?
- Nie mierzy czasu renderowania klatki overlay w procesach workerów podczas finalnego eksportu (`render_overlay_frame`).
- W procesie eksportu workery działają w osobnych procesach `ProcessPoolExecutor`, a ich czas pojedynczej klatki 1080p wynosi **~23.6 ms**, a nie 236 ms.
- Z powodu architektury singletona `BenchmarkTracker`, raport na końcu eksportu wydrukował wartość `overlay_rendering (n=1)` zarejestrowaną przez GUI przed startem eksportu.

---

## B. Model multiprocessing i rzeczywisty throughput

W finalnym eksporcie NVIDIA:
- Rozdzielczość renderowania HUD w Pythonie: **1920×1080 RGBA** (7.91 MB / klatka).
- Pula pamięci współdzielonej: `SharedFramePool` (`MAX_IN_FLIGHT = 62`, `workers = 31`).
- Przekazywanie do FFmpeg: przez wątek `_pipe_writer_thread` piszący bezpośrednio z SHM do `stdin.buffer` (zero-copy memoryview).
- Skalowanie i compositing: FFmpeg na GPU (`scale=3840:2160` -> `hwupload_cuda` -> `overlay_cuda`).

### Rzeczywisty pomiar skalowania throughputu (150 klatek w SHM):

| Liczba workerów | Całkowity czas (s) | Throughput (FPS) | Efektywny czas/klatkę (ms) | Skalowanie vs 1 Worker |
| :--- | :--- | :--- | :--- | :--- |
| **1 worker** | 4.221 s | 35.5 FPS | 28.14 ms | 1.00× |
| **2 workery** | 2.653 s | 56.5 FPS | 17.69 ms | 1.59× |
| **4 workery** | **2.299 s** | **65.2 FPS** | **15.33 ms** | **1.84× (PEAK)** |
| **8 workerów** | 2.800 s | 53.6 FPS | 18.67 ms | 1.51× |
| **16 workerów** | 4.363 s | 34.4 FPS | 29.09 ms | 0.97× |
| **24 workery** | 5.879 s | 25.5 FPS | 39.20 ms | 0.72× |
| **31 workerów** | **7.272 s** | **20.6 FPS** | **48.48 ms** | **0.58× (DEGRADACJA)** |

> [!WARNING]
> Przy **31 workerach** renderer osiąga zaledwie **20.6 FPS**, podczas gdy przy **4 workerach** osiąga **65.2 FPS** (ponad 3.16× szybciej!).

---

## C. Call graph renderowania overlay

```text
render_frame_shm_job(index, slot)  [Worker Process]
  │
  ├── WORKER_CACHE lookup (layout, samples, bounds)
  │
  ├── prepare_overlay_frame_data() [~3.94 ms]
  │     ├── _normalise_samples() & bisect timestamps
  │     ├── interpolate_speed() / interpolate_distance() / interpolate_altitude()
  │     └── FIT / GPX telemetry field resolution
  │
  ├── compose_overlay(1920, 1080) [~19.6 ms]
  │     ├── _get_reusable_canvas() & regional clear [0.01 ms]
  │     │
  │     ├── render_time_block() -> rotated_paste() [0.04 ms]
  │     │
  │     ├── render_value_indicator("alt_visual") [2.24 ms]
  │     │     └── _render_bar_indicator() (ticks, lines, dot)
  │     ├── rotated_paste("alt_visual", rotation=90) [5.12 ms]
  │     │     ├── Image.transpose(ROTATE_90)
  │     │     └── composite_final() (getbbox -> crop -> alpha_composite)
  │     │
  │     ├── render_value_indicator("dist_visual") [1.51 ms]
  │     │     └── _render_bar_indicator()
  │     ├── rotated_paste("dist_visual", rotation=0) [2.57 ms]
  │     │     └── composite_final()
  │     │
  │     ├── render_value_indicator("speed_visual") [0.19 ms]
  │     │     └── _render_gauge_indicator() (cache hit bg + needle)
  │     │
  │     ├── render_value_indicator(text indicators) [~0.35 ms total]
  │     │     └── _render_text_indicator() (STATIC_CACHE hit / draw.text)
  │     │
  │     └── custom_texts loop [0.01 ms]
  │
  └── np.copyto(shm_arr, img_arr) [~0.5 ms]
```

---

## D. Breakdown czasowy pojedynczej klatki 1080p (Single Worker)

| Komponent / Faza | Średni czas (ms) | p95 (ms) | Wywołań/klatkę | % Klatki | Wykonanie |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **`alt_visual` (pionowy bar 90°)** | **7.36 ms** | 8.10 ms | 1 | **31.2%** | CPU (Pillow) |
| **Telemetry lookup & prep** | **3.94 ms** | 4.25 ms | 1 | **16.7%** | CPU (Python) |
| **`dist_visual` (poziomy bar)** | **4.08 ms** | 4.60 ms | 1 | **17.3%** | CPU (Pillow) |
| **`alt_text` (wartość wysokości)** | **0.32 ms** | 0.45 ms | 1 | **1.4%** | CPU (Pillow) |
| **`dist_text` (wartość dystansu)** | **0.23 ms** | 0.35 ms | 1 | **1.0%** | CPU (Pillow) |
| **`speed_visual` (okrągły licznik)** | **0.22 ms** | 0.30 ms | 1 | **0.9%** | CPU (Pillow) |
| **Pozostałe 10 wskaźników tekstowych** | **0.38 ms** | 0.50 ms | 10 | **1.6%** | CPU (Pillow) |
| **`time_block` (data i zegar)** | **0.04 ms** | 0.06 ms | 1 | **0.2%** | CPU (Pillow) |
| **Kopiowanie do SHM (np.copyto)** | **0.55 ms** | 0.70 ms | 1 | **2.3%** | CPU (NumPy) |
| **Canvas regional clear & zarządzenie**| **0.01 ms** | 0.02 ms | 1 | **0.1%** | CPU (Pillow) |
| **Narzut pętli i alokacji** | **6.46 ms** | 7.00 ms | - | **27.3%** | CPU (Python) |
| **SUMA (pojedyncza klatka)** | **23.59 ms** | 27.93 ms | - | **100.0%** | **CPU** |

---

## E. Breakdown poszczególnych wskaźników

1. **`alt_visual` (7.36 ms / 31.2%)**:
   - `_render_bar_indicator`: 2.24 ms (kopiowanie tła `bg.copy()`, wyliczenie skali, rysowanie kropki).
   - `rotated_paste`: **5.12 ms** (rotacja `Image.transpose(ROTATE_90)` tworząca nowy bufor + `composite_final` z `getbbox()` i `crop()` + `alpha_composite`).
2. **`dist_visual` (4.08 ms / 17.3%)**:
   - `_render_bar_indicator`: 1.51 ms.
   - `rotated_paste`: 2.57 ms (`composite_final` z `getbbox()` i `alpha_composite`).
3. **Telemetry Prep (3.94 ms / 16.7%)**:
   - `_normalise_samples`, `bisect` i interpolacje liniowe dla 14 strumieni danych powtarzane w każdym procesie roboczym dla każdej klatki.
4. **Wskaźniki tekstowe (ISO, Exp, Temp, Power, HR, Cad, Bat, Speed_text)**:
   - Bardzo szybkie (0.02–0.04 ms każdy), ponieważ `_STATIC_CACHE` przechowuje wyrenderowane glify.

---

## F. Alokacje i ruch pamięci

Dla każdej klatki 1080p (1920×1080 RGBA):
- **Główny bufor klatki**: 1920 × 1080 × 4 = **7.91 MB**.
- **Alokacje per klatka w workerze**:
  - `Image.new("RGBA")` dla wskaźników bez cache hit: ~6–10 małych buforów (50–200 KB).
  - `Image.transpose(ROTATE_90)` dla `alt_visual`: ~150 KB.
  - `crop()` buforów pomocniczych: ~200 KB.
  - `np.frombuffer` i `np.copyto`: przepisanie 7.91 MB do SharedMemory.
- **Ruch pamięci**:
  - 1 klatka generuje ~16–20 MB operacji odczytu/zapisu RAM.
  - Przy 60 FPS ruch pamięci wynosi **~1.2 GB/s**.
  - Przy 31 workerach i 62 in-flight frames, bufor roboczy SHM wynosi **490 MB**, co wielokrotnie przekracza pamięć podręczną CPU L3 (32–64 MB) i powoduje ciągłe cache thrashing.

---

## G. Elementy statyczne vs dynamiczne

| Wskaźnik | Elementy STATIC (Niezmienne) | Elementy DYNAMIC (Zmienne co klatkę) | Możliwość pełnego cache |
| :--- | :--- | :--- | :--- |
| **`speed_visual`** | Tarcza, podziałka, liczby, etykieta | Wskazówka (kąt), wartość cyfrowa | **TAK** (tło już w cache) |
| **`alt_visual` / `dist_visual`** | Oś paska, ticki, etykieta skali | Pozycja wskaźnika (kropka) | **TAK** (można pre-renderować obróconą oś) |
| **`time_block`** | Ramka, ikona, etykieta | Tekst daty / godziny | Częściowo (data stała przez 86400s) |
| **Wykresy (`charts`)** | Ramka, siatka, linie min/max, krzywa profilu | Kursor pionowy, kropka, bieżąca wartość | **TAK** (`ChartSplit` dzieli tło od kursora) |
| **Mapa (`map`)** | Kafelki mapy, ślad całej trasy (czerwona linia) | Znacznik pozycji (kropka), kadr ruchomy | **TAK** (statyczna trasa w osobnym buforze) |
| **Wskaźniki tekstowe** | Etykieta, jednostka | Liczba | **TAK** (w `_STATIC_CACHE`) |

---

## H. Analiza mapy (`track_map`)

- **Źródło**: kafelki OSM / CartoDB pobierane z dysku + rysowanie trasy GPS z punktów FIT/GPMF.
- **Czas renderowania**:
  - `static_map` (1683 punkty): **~0.59 ms** (p95: 7.93 ms).
  - `moving_map` (ruchoma mapa): **~8–15 ms** (w zależności od zoomu i cropu kafelków).
- W domyślnym układzie `def_layout.json` mapa jest **wyłączona** (`enabled: false`).

---

## I. Analiza wykresów (`charts`)

- **Czas renderowania**: **~0.28 ms** (p95: 0.67 ms) dla wykresu 400×150 z 300 punktami.
- W kodzie istnieje już optymalizacja `ChartSplit` (stworzona w ETAP 5K dla AMD), która oddziela statyczną krzywą od dynamicznego kursora.

---

## J. Analiza wskaźników zegarowych (`gauges`)

- **Czas renderowania**: **~0.14 ms** (p95: 1.09 ms).
- Tło tarczy (`_STATIC_CACHE`) jest generowane tylko raz. Co klatkę rysowana jest jedynie obrócona iglica i cyfry.

---

## K. Analiza renderowania tekstu (`text rendering`)

- **Czas renderowania**: **~0.02–0.04 ms** na wskaźnik.
- `_render_text_indicator` wykorzystuje `_STATIC_CACHE` z kluczem zawierającym sformatowany tekst.
- Czcionki (`load_font`) są ładowane raz do `FONT_CACHE`.
- Tekst nie stanowi wąskiego gardła (< 2% całkowitego czasu klatki).

---

## L. Analiza multiprocessing (31 workerów vs 4 workery)

Dlaczego **31 workerów** daje tylko **20.6 FPS** (zamiast oczekiwanych 500+ FPS)?

1. **Scheduler & Context Switching w Windows**:
   31 procesów Pythona walczących o rdzenie CPU generuje potężny narzut przełączania kontekstu i kolejkowania zadań w systemie Windows.
2. **Przekroczenie L3 Cache & Nasycenie szyny RAM**:
   31 workerów × 2 bufory = 62 aktywne klatki po 7.91 MB = **490 MB**. Pamięć podręczna L3 procesora (32–64 MB) zostaje całkowicie wypchnięta, zmuszając CPU do ciągłego transferu z wolniejszej pamięci DDR5.
3. **IPC & Synchronizacja `ProcessPoolExecutor`**:
   Jeden proces główny odbierający wyniki z 31 procesów staje się wąskim gardłem synchronizacji kolejki.
4. **Sweet Spot**:
   Testy wykazały, że **4–6 workerów** mieści swój working set (30–50 MB) blisko pamięci podręcznej i osiąga **65.2 FPS** na tym samym sprzęcie.

---

## M. TOP 10 kosztów

| Poz. | Element / Zjawisko | Koszt / Wpływ | % Wpływu | Możliwość optymalizacji |
| :--- | :--- | :--- | :--- | :--- |
| **1.** | **Przewymiarowana liczba workerów (31 workerów)** | Spadek z 65.2 do 20.6 FPS | **-68% Throughput** | Zmiana domyślnej liczby workerów na 4–8 |
| **2.** | **`alt_visual` (pionowy bar 90°)** | 7.36 ms / klatkę | 31.2% Latency | Pre-rotacja tła w cache; unikanie `transpose` |
| **3.** | **`dist_visual` (poziomy bar)** | 4.08 ms / klatkę | 17.3% Latency | Uproszczenie kompozycji paska |
| **4.** | **Telemetry lookup & prep per frame** | 3.94 ms / klatkę | 16.7% Latency | Prekalkulacja tablicy klatek przed pętlą |
| **5.** | **Transfer pełnego 1080p canvas do FFmpeg (Pipe Write)** | 9.28 ms / klatkę | I/O Bottleneck | Przesyłanie tylko HUD Bounding Box (Atlas) |
| **6.** | **4K Preview Full CPU Composite** | 96.6–236 ms / klatkę | Preview Latency | Podgląd w 1080p lub blending GPU |
| **7.** | **NumPy `copyto` do Shared Memory** | 0.55 ms / klatkę | 2.3% Latency | Bezpośredni render do bufora |
| **8.** | **`alt_text` / `dist_text` formatowanie i layout** | 0.55 ms / klatkę | 2.4% Latency | Lepsze reużycie stringów |
| **9.** | **`speed_visual` gauge needle blit** | 0.22 ms / klatkę | 0.9% Latency | Już zoptymalizowane |
| **10.** | **Kolejkowanie i synchronizacja IPC** | ~1–2 ms / klatkę | Narzut | Bounded in-flight queue |

---

## N. Maksymalnie 5 QUICK WINS

### 1. Dostosowanie liczby workerów do specyfiki pamięciowej (4–8 workerów)
- **Opis:** Zmiana domyślnego limitu workerów z `min(cpu_count-1, frames)` (31) na `min(6, cpu_count)`.
- **Potencjalny zysk:** **BARDZO DUŻY** (natychmiastowy wzrost throughputu z **20.6 FPS do 65.2 FPS**, czyli **+216% FPS**).
- **Trudność:** **MAŁA** (1 linijka kodu).
- **Ryzyko:** **MAŁE** (brak zmian formatów, brak zmian w algorytmach).

### 2. HUD Sub-Window / Atlas Bounding Box dla NVIDIA
- **Opis:** Przesyłanie do FFmpeg tylko minimalnego prostokąta obejmującego aktywne wskaźniki (np. 1920×300 zamiast 1920×1080), tak jak zrobiono to dla AMD.
- **Potencjalny zysk:** **DUŻY** (zmniejszenie pamięci i pipe write o 70%, pipe write spada z 9.3 ms do < 2.5 ms).
- **Trudność:** **ŚREDNIA**.
- **Ryzyko:** **MAŁE**.

### 3. Pre-rotated caching dla `alt_visual` (bar 90°)
- **Opis:** Zapisanie w cache statycznego tła paska już w postaci obróconej o 90°, eliminując kosztowny `Image.transpose(ROTATE_90)` i `crop()` wykonywane co klatkę.
- **Potencjalny zysk:** **ŚREDNI** (oszczędność ~5 ms na klatkę, latency klatki spada z 23.6 ms do ~18.5 ms).
- **Trudność:** **MAŁA**.
- **Ryzyko:** **MAŁE**.

### 4. Prekalkulacja telemetrii (`Precomputed Telemetry Array`)
- **Opis:** Jednorazowe wyliczenie wartości wskaźników dla wszystkich klatek przed uruchomieniem workerów, przekazanie gotowych stabelaryzowanych wartości.
- **Potencjalny zysk:** **ŚREDNI** (oszczędność ~3.9 ms na klatkę, eliminacja redundancji w workerach).
- **Trudność:** **ŚREDNIA**.
- **Ryzyko:** **MAŁE**.

### 5. D3D11 / CUDA GPU Compositor dla NVIDIA
- **Opis:** Przeniesienie całego compositingu wskaźników do GPU (wykorzystanie istniejącej bazy natywnego compositingu D3D11).
- **Potencjalny zysk:** **BARDZO DUŻY** (rendering wskaźników na GPU w < 2 ms).
- **Trudność:** **DUŻA**.
- **Ryzyko:** **ŚREDNIE**.

---

## O. Rekomendacja pierwszej zmiany

### Jednoznaczna odpowiedź:

> **Jaka JEDNA zmiana ma obecnie najlepszy stosunek przewidywanego wzrostu FPS do czasu implementacji i ryzyka?**

👉 **Optymalizacja liczby workerów renderera (ustawienie domyślnej liczby workerów na 4–6 zamiast 31).**

### Uzasadnienie:
1. **Wzrost wydajności:** Natychmiastowy skok throughputu z **20.6 FPS do 65.2 FPS** (+216% wydajności / ponad 3-krotne przyspieszenie eksportu).
2. **Czas implementacji:** Kilka minut (parametr konfiguracyjny/algorytm doboru liczby workerów).
3. **Ryzyko:** **Zerowe** — wygenerowany obraz wideo jest w 100% identyczny co do piksela, nie zmienia się żaden format klatek ani potok FFmpeg.
