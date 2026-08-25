# TeleM — NVIDIA ETAP 4A: Rzeczywisty Wall-Clock Produkcyjnego Eksportu

**Data:** 2026-08-20  
**Platforma testowa:** NVIDIA GeForce RTX 5070 Ti 16 GB, Driver 610.62, CUDA 13.3, FFmpeg 8.1.1, Windows 11 (32 logiczne rdzenie CPU)  
**Materiał testowy:** `Video/GX020079.mp4` (4K 3840×2160 @ 29.97 FPS, 1132 klatki, HEVC Main 10) + `Video/Morning_Ride.fit`  
**Layout testowy:** Pełny produkcyjny layout domyślny (`def_layout.json`) — dokładnie taki sam jak po uruchomieniu TeleM i kliknięciu *Eksport* w GUI.

---

## A. Skąd pochodziło 266.68 FPS

Raportowany w ETAPIE 3 wynik **266.68 FPS (4.24 s)** pochodził z testu syntetycznego sub-window HUD, w którym:
1. Aktywny był wyłącznie dolny pasek wskaźników (`1712×396 px`, 32.7% powierzchni ekranu) — wyłączono w nim górny zegar (`time_block`) oraz pionowe paski.
2. Transport pamięci SHM i pipe wynosił **2.59 MB / klatkę** (zamiast 7.91 MB).
3. Liczba rysowanych elementów Pillow w workerach była ograniczona do kilku wskaźników tekstowo-liczbowych.

---

## B. Zakres starego timera

Stary timer w benchmarkach syntetycznych:
- Mierzył czas od wywołania `stream_overlay_to_ffmpeg` do jego zakończenia.
- **NIE obejmował**:
  1. Przygotowania telemetrii w GUI (ekstrakcji GPMF z kontenera MP4 i parsowania/synchronizacji pliku FIT: **~0.95 s**).
  2. Pełnego zestawu wskaźników z domyślnego profilu GUI.
  3. Zachowania mechanizmu BBox Fallback przy layoutach pełnoekranowych.

---

## C. Produkcyjny lifecycle eksportu

Pełny lifecycle od kliknięcia przycisku **Eksport** w GUI do gotowego pliku na dysku:

```text
[Kliknięcie Eksport w GUI]
  │
  ▼ (1) PREPARE GUI: telemetry extraction (GPMF + FIT sync) [~0.95 s]
  │
  ▼ (2) stream_overlay_to_ffmpeg entry
  │       ├─ BBox calculation & layout analysis [~0.001 s]
  │       ├─ SharedFramePool allocation (63.3 MB) [~0.002 s]
  │       ├─ subprocess.Popen(FFmpeg) [~0.005 s]
  │       └─ Worker pool launch & first frame render [FIRST_FRAME_LATENCY: ~0.84 s]
  │
  ▼ (3) FRAME_PIPELINE: streaming 1132 frames do FFmpeg pipe [~8.63 s @ 131.2 FPS]
  │
  ▼ (4) FFMPEG_DRAIN_FINALIZE: pipe_done, stdin.close(), ffmpeg.wait() [~0.08 s]
  │
  ▼ (5) POSTPROCESS: rotation displaymatrix verification [~0.000 s]
  │
[Plik MP4 gotowy na dysku] (Łączny czas wall-clock: ~10.54 s @ 107.4 FPS)
```

---

## D. Punkty pomiarowe

Wszystkie pomiary wykonano za pomocą `time.perf_counter()` z rozdzielczością nanosekundową:

- **PREPARE**: Obliczenie BBox, layoutu, komendy FFmpeg (`0.000 s`).
- **WORKER_INIT**: Alokacja pamięci `SharedFramePool` i konfiguracja struktur (`0.002 s`).
- **FFMPEG_STARTUP**: Od `subprocess.Popen` do uruchomienia wątku pipe writer (`0.005 s`).
- **FIRST_FRAME_LATENCY**: Od startu `stream_overlay_to_ffmpeg` do faktycznego zapisania pierwszej klatki do pipe FFmpeg (`0.839 s`).
- **FRAME_PIPELINE**: Od zapisu pierwszej klatki do zapisu ostatniej (1132.) klatki do pipe (`8.627 s`).
- **FFMPEG_DRAIN_FINALIZE**: Od zakończenia podawania klatek do zamknięcia `stdin`, zakończenia kodowania przez NVENC i `process.wait()` (`0.079 s`).
- **POSTPROCESS**: Ewentualne operacje metadanych / displaymatrix po zakończeniu FFmpeg (`0.000 s`).
- **PRODUCTION_TOTAL (stream)**: Całkowity czas od wejścia do `stream_overlay_to_ffmpeg` do zakończenia procesu (`9.594 s`).
- **GUI Telemetry Prep**: Ekstrakcja GPMF + FIT sync przed wejściem do streamingu (`0.949 s`).
- **REAL END-TO-END WALL-CLOCK**: Od kliknięcia Eksport do gotowego pliku (`10.543 s`).

---

## E. Wyniki 3 uruchomień produkcyjnych

| Metryka | Run 1 | Run 2 | Run 3 | Mediana |
| :--- | :--- | :--- | :--- | :--- |
| **Klatki** | 1132 | 1132 | 1132 | **1132** |
| **PREPARE** | 0.000 s | 0.000 s | 0.000 s | **0.000 s** |
| **WORKER_INIT** | 0.102 s (cold) | 0.001 s | 0.002 s | **0.002 s** |
| **FFMPEG_STARTUP** | 0.005 s | 0.005 s | 0.005 s | **0.005 s** |
| **FIRST_FRAME_LATENCY** | 0.916 s | 0.833 s | 0.839 s | **0.839 s** |
| **FRAME_PIPELINE** | 8.720 s | 8.627 s | 8.523 s | **8.627 s** |
| **FFMPEG_DRAIN_FINALIZE**| 0.082 s | 0.079 s | 0.078 s | **0.079 s** |
| **POSTPROCESS** | 0.000 s | 0.000 s | 0.000 s | **0.000 s** |
| **PRODUCTION_TOTAL (stream)**| 9.773 s | 9.594 s | 9.490 s | **9.594 s** |
| **PIPELINE_FPS** | 129.8 | 131.2 | 132.8 | **131.2 FPS** |
| **REAL_EXPORT_FPS (stream)** | 115.8 | 118.0 | 119.3 | **118.0 FPS** |
| **TOTAL_OVERHEAD (stream)** | 1.052 s | 0.967 s | 0.967 s | **0.967 s** |
| **OVERHEAD %** | 10.8 % | 10.1 % | 10.2 % | **10.1 %** |
| **ffmpeg_write avg** | 3.33 ms | 4.09 ms | 3.12 ms | **3.33 ms** |
| **ffmpeg_write p95** | 7.02 ms | 11.31 ms | 5.56 ms | **7.02 ms** |
| **GUI Telemetry Prep** | 0.954 s | 0.949 s | 0.942 s | **0.949 s** |
| **REAL END-TO-END WALL-CLOCK**| 10.727 s | 10.543 s | 10.432 s | **10.543 s** |
| **REAL END-TO-END FPS** | 105.52 | 107.37 | 108.51 | **107.37 FPS** |

---

## F. Breakdown Wall-Clock

Rozbicie 10.54 s całkowitego czasu trwania eksportu:

```text
┌──────────────────────────────┬────────────┬─────────────┐
│ Faza eksportu                │ Czas (s)   │ Udział (%)  │
├──────────────────────────────┼────────────┼─────────────┤
│ 1. Telemetria (GPMF + FIT)   │  0.949 s   │    9.0 %    │
│ 2. First-frame startup delay │  0.839 s   │    8.0 %    │
│ 3. Płynny Frame Pipeline     │  8.627 s   │   81.8 %    │
│ 4. FFmpeg drain & finalize   │  0.079 s   │    0.7 %    │
│ 5. Postprocess               │  0.000 s   │    0.0 %    │
├──────────────────────────────┼────────────┼─────────────┤
│ SUMA (Wall-Clock Total)      │ 10.543 s   │  100.0 %    │
└──────────────────────────────┴────────────┴─────────────┘
```

---

## G. Semantyka `ffmpeg_write`

- Pomiar `ffmpeg_write` w `_pipe_writer_thread` mierzy czas wykonania `stdin_buffer.write(memview)` oraz zwolnienia slotu `shm_pool.release(slot)`.
- Przy buforze rury OS wynoszącym 64 KB i klatkach 7.91 MB, wywołanie `write()` natychmiast blokuje się, oczekując aż proces FFmpeg odczyta dane z rury `pipe:0`.
- **Wartości zmierzone**:
  - `avg = 3.33 ms` (co odpowiada przepustowości zapisu do rury ~300 FPS).
  - `p95 = 7.02 ms`.
- Oznacza to, że wątek zapisu nie ma przestojów i natychmiast karmi FFmpeg, gdy tylko klatki są gotowe w buforze SHM.

---

## H. First-Frame Latency

- `FIRST_FRAME_LATENCY` wynosi **~0.84 s**.
- Składa się z:
  1. Spawnowania 4 procesów `ProcessPoolExecutor` w systemie Windows (`spawn` mode) i załadowania w nich modułów Pythona (`~0.45 s`).
  2. Wyrenderowania pierwszych klatek przez workerów Pillow (`~0.35 s`).
  3. Przekazania pierwszego bufora SHM do rury FFmpeg (`~0.04 s`).

---

## I. FFmpeg Drain / Finalize

- `FFMPEG_DRAIN_FINALIZE` trwa zaledwie **0.079 s (79 ms)**.
- Wynika to z faktu, że sprzętowy dekoder NVDEC i enkoder NVENC na karcie RTX 5070 Ti przetwarzają klatki niemal natychmiastowo i w momencie zakończenia podawania klatek do rury bufor enkodera jest opróżniany w ułamku sekundy, po czym FFmpeg zapisuje atom `moov` i zamyka plik MP4.

---

## J. Startup overhead krótkiego filmu (Short-Film Effect)

- Testowany plik wideo ma długość **37.7 sekundy (1132 klatki)**.
- Stały narzut początkowy (ekstrakcja telemetrii ~0.95 s + start workerów ~0.84 s = **~1.79 s**) stanowi aż **17.0% całkowitego czasu** eksportu dla 38-sekundowego materiału, obniżając obserwowany `REAL_EXPORT_FPS` z 131.2 FPS do **107.4 FPS**.
- **Wpływ na dłuższe materiały:**
  - Dla filmu **5-minutowego** (8 991 klatek @ 131 FPS ≈ 68.6 s): narzut 1.79 s stanowi **2.5% czasu** -> `REAL_EXPORT_FPS ≈ 127.8 FPS`.
  - Dla filmu **15-minutowego** (26 973 klatki @ 131 FPS ≈ 205.9 s): narzut 1.79 s stanowi **0.8% czasu** -> `REAL_EXPORT_FPS ≈ 130.0 FPS`.

---

## K. Największa różnica między benchmarkiem a realnym eksportem

Główna przyczyna różnicy między **266.7 FPS** w benchmarku a **~107–118 FPS** w eksporcie produkcyjnym to **Layout i BBox Fallback**:

1. **W benchmarku syntetycznym**:
   Użyto wyizolowanego layoutu z samym dolnym paskiem (`1712×396 px`, 32.7% powierzchni, 2.59 MB/klatkę). Aktywny był HUD BBox transport, dając **266.7 FPS**.
2. **W normalnym eksporcie z GUI (`def_layout.json`)**:
   Domyślny profil zawiera wskaźnik zegara `time_block` u góry ekranu (`y=3%`) oraz wskaźniki na dole ekranu (`y=96%`).
   Funkcja BBox wyznacza obszar o wysokości od góry do dołu ekranu (`area = 100.0% > 85%`).
   Zgodnie z regułą fallbacku pipeline przełącza się na **Full Frame 1920×1080 (7.91 MB/klatkę)** i renderuje wszystkie 8 domyślnych wskaźników, co daje **~131.2 PIPELINE_FPS**.
3. **Narzut telemetrii i startu procesów**:
   Dodatkowe 1.79 s przygotowania telemetrii i inicjalizacji workerów obniża końcowy wynik krótkiego pliku do **~107.4 REAL_EXPORT_FPS**.

---

## L. Wnioski i odpowiedzi na kluczowe pytania

> **1. Jaka jest rzeczywista wydajność produkcyjnego eksportu TeleM w FPS?**

- **Czysty Frame Pipeline (1920×1080 Full Frame @ 4K NVENC)**: **131.2 FPS** (~4.4× realtime).
- **Rzeczywisty eksport streamingowy (`stream_overlay_to_ffmpeg`)**: **118.0 FPS**.
- **Pełny End-to-End Wall-Clock (od kliknięcia w GUI z ekstrakcją telemetrii)**: **107.4 FPS** (~3.6× realtime, 1132 klatki 4K w 10.5 sekundy).

---

> **2. Dlaczego wcześniejszy benchmark raportował ~266.7 FPS, jeśli realny eksport obserwowany przez użytkownika wynosi około 100+ FPS?**

Ponieważ w benchmarku testowano kompaktowy sub-window HUD (tylko dolny pasek, 32.7% powierzchni, 2.59 MB), który mieścił się w BBox i osiągał 266.7 FPS, natomiast domyślny layout produkcyjny w GUI (`def_layout.json`) posiada elementy rozrzucone od samej góry (`time_block` y=3%) do samego dołu (`y=96%`), co powoduje fallback do pełnej klatki 1920×1080 (7.91 MB) i renderowanie wszystkich wskaźników przy 131 FPS (oraz dodatkowo ~1.8 s narzutu startowego telemetrii i procesów).

---

> **3. Która faza eksportu zużywa obecnie najwięcej wall-clock czasu poza właściwym frame pipeline?**

Najwięcej czasu poza `FRAME_PIPELINE` zużywają:
1. **Przygotowanie telemetrii w GUI przed renderem**: **~0.95 s** (odczyt GPMF + dekodowanie FIT).
2. **First-Frame Latency (inicjalizacja 4 procesów workerów w systemie Windows)**: **~0.84 s**.

Łącznie te dwie fazy stanowią **1.79 s (17.0%)** całego czasu eksportu dla materiału 38-sekundowego.
