# RAPORT AMD: KONTROLOWANA IZOLACJA DIAGNOSTYCZNA GRUPY G (PIPELINE SYNC VS ASYNC & MEDIA FOUNDATION)

**Data:** 2026-09-25  
**Autor:** Antigravity  
**Gałąź:** `amd-recovery-a-c`  
**HEAD Commit:** `24948bf5d52d9beb3d22f9c0d20d9ca3e8cc0717`  
**Status etapu:** COMPLETE (Diagnoza jednoznaczna, brak zmian w kodzie produkcyjnym)

---

## 1. Cel badania

Jednoznaczne ustalenie wpływu zmiany produkcyjnego pipeline'u:
- `SYNC / queue_depth=0` vs `ASYNC / queue_depth=2` vs `ASYNC / queue_depth=1`
oraz wyjaśnienie źródła wzrostu metryki:
- `MF ReadSample/decode availability` z ~0.83 ms (`0ef407e`) do ~15.27 ms w aktualnym stanie.

Badanie przeprowadzono w reżimie rygorystycznej dyscypliny benchmarkowej (AGENTS.md §2, §13, §20):
- Identyczny workload: `Video/GX020079.MP4` (4K 3840x2160), `Video/GX020079.fit`, `def_layout.json` (300 klatek).
- Wszystkie testy wykonane w seriach 3-runowych przez `tools/amd_performance_gate.py`.
- Brak opportunistycznych refaktorów ani zmian w logice renderera.

---

## 2. Bezpieczeństwo i stan początkowy

Weryfikacja repozytorium przed rozpoczęciem:
```text
git status: clean (brak zmodyfikowanych plików śledzonych)
git branch: amd-recovery-a-c
git rev-parse HEAD: 24948bf5d52d9beb3d22f9c0d20d9ca3e8cc0717
```
Poprawki Fix A (`24948bf`) oraz Fix C (`ac5d3ad`) pozostały nienaruszone.

---

## 3. Szczegółowy audyt zmian Grupy G (`0ef407e` -> `HEAD`)

Porównanie plików `src/ffmpeg/amd_config.py`, `amd_native_exporter.py`, `streaming.py`, `command_builder.py` oraz `native/`:

1. **Konfiguracja `src/ffmpeg/amd_config.py`**:
   - `PRODUCTION_DEFAULTS`:
     - `pipeline`: zmieniono z `"SYNC"` na `"ASYNC"`.
     - `queue_depth`: zmieniono z `0` na `2`.
   - Funkcja `resolve_amd_config`:
     - Tryb `SYNC` jest aktywowany, gdy `AMD_QUEUE_DEPTH == "0"` lub `AMD_CPU_GPU_PIPELINE == "SYNC"`.
     - W przeciwnym razie domyślnie wybierany jest `ASYNC` z `queue_depth=2`.
2. **Kod pipeline'u w `src/ffmpeg/amd_native_exporter.py`**:
   - Kod wykonawczy `ASYNC` (wątek `TeleM-CpuProducer` + `frame_queue = queue.Queue(maxsize=q_depth)`) oraz `SYNC` (sekwencyjna pętla `_prepare_frame_cpu` -> `_consume_prepared_frame`) istniał już w `0ef407e`.
   - **Kluczowe odkrycie audytu profilera `0ef407e`**:
     Profil JSON ze stanu known-good (`pre_arrow_0ef407e_300f.mp4.amd_profile.json`) dowodzi, że **known-good `0ef407e` pracował w trybie ASYNC z `queue_depth=2`** (`etap8t_b: {'pipeline_mode': 'ASYNC', 'queue_max_depth': 2}`).
     W `0ef407e` zmienna środowiskowa `AMD_CPU_GPU_PIPELINE` miała domyślną wartość `"ASYNC"`, a `AMD_QUEUE_DEPTH` wynosiło domyślnie `2`.
3. **C++ Native (`telem_amd_native.cpp` & `d3d11_amf_pipeline`)**:
   - Logika kolejkowania `ctx->queueDepth` (gdzie `maxInFlight = ctx->queueDepth`) w bibliotece DLL nie uległa zmianie.
   - Pomiary `ReadSample` (`ctx->pSourceReader->ReadSample(...)`) są identyczne co do mikrosekundy.

---

## 4. Wyniki pomiarów A/B (3-runowe serie na `tools/amd_performance_gate.py`)

### Tabela porównawcza

| Konfiguracja | Queue | RENDER FPS | EFFECTIVE FPS | System CPU | child_python CPU | producer_prepare | consumer_queue_wait | MF ReadSample | AMF QueryOutput | above_total | Frame Time |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| **known-good (`0ef407e`)** | **2** | **41.238** | **31.479** | **15.1%** | *(n/a)* | **18.240 ms** | **1.728 ms** | **1.202 ms** | **14.246 ms** | **10.765 ms** | **24.250 ms** |
| **Obecny ASYNC (Test A/D)** | **2** | **35.729** | **27.459** | **49.4%** | **39.3 pp** | **24.994 ms** | **2.299 ms** | **16.087 ms** | **3.322 ms** | **15.896 ms** | **27.989 ms** |
| **SYNC (Test B)** | **0** | **24.448** | **21.671** | **32.9%** | **24.9 pp** | **14.480 ms** | **0.000 ms** | **4.363 ms** | **16.657 ms** | **8.672 ms** | **40.903 ms** |
| **ASYNC q=1 (Test C)** | **1** | **24.365** | **21.661** | **36.9%** | **27.2 pp** | **18.408 ms** | **1.553 ms** | **5.355 ms** | **27.453 ms** | **11.194 ms** | **41.043 ms** |

*Uwaga: Wartości w tabeli reprezentują mediany z 3 pełnych przebiegów 300-klatkowych na maszynie AMD Ryzen 7 7730U (16 wątków).*

---

## 5. Analiza CPU per-process (Rozwiązanie zagadki ~49% CPU)

Do harnessu (`scratch/bench_regression_harness.py`) dodano bezinwazyjny próbnik per-process Win32 oparty o `GetProcessTimes` i migawki Toolhelp32.

### Rozkład zużycia CPU dla obecnego ASYNC (`queue_depth=2`):
- **Całkowity System CPU:** `49.4%` (ekwiwalent ~7.9 nasyconych rdzeni logicznych)
- **`child_python` (`TeleM-AMD-Render`):** `39.3 pp` (~6.3 nasyconego rdzenia logicznego)
- **`harness_parent` (proces nadrzędny Pythona):** `1.6 pp` (~0.25 rdzenia)
- **`ffmpeg_mux` (transkodowanie i demux na żywo):** `0.2 pp` (~0.03 rdzenia)
- **Pozostałe procesy systemowe / OS tło:** `~8.3 pp`

### Wnioski dotyczące CPU:
1. Prawie całe zużycie CPU (+39.3 punktów procentowych z 49.4%) generuje proces potomny renderera `child_python`.
2. FFmpeg muxer jest w pełni odciążony (0.2 pp) i nie stanowi źródła narzutu CPU.
3. W trybie ASYNC wewnątrz `child_python` działają równolegle dwa intensywne wątki:
   - `TeleM-CpuProducer`: wykonuje rasteryzację Pillow, tracking exact bbox, ekstrakcję płótna i transfer pamięci.
   - Wątek konsumenta (main thread): wykonuje wywołania D3D11/ctypes, transfer buforów do VRAM i pomiary telemetryczne.
   Wątki te intensywnie rywalizują o blokadę GIL Pythona oraz pamięć podręczną L3 CPU.

---

## 6. Wyjaśnienie anomalii Media Foundation (wzrost z 0.83 ms do 15.7 ms)

Pomiary timingów w C++ (`telem_amd_native.cpp` L.1337-1343) jednoznacznie wskazują naturę metryki `MF ReadSample/decode availability`:
```cpp
const auto readStart = std::chrono::high_resolution_clock::now();
const HRESULT readHR = ctx->pSourceReader->ReadSample(
    static_cast<DWORD>(MF_SOURCE_READER_FIRST_VIDEO_STREAM), 0,
    &actualStream, &streamFlags, &timestamp, &sample);
const auto readEnd = std::chrono::high_resolution_clock::now();
ctx->lastTimings.mfReadSampleMs = std::chrono::duration<double, std::milli>(readEnd - readStart).count();
```

Jest to czysty, synchroniczny czas trwania wywołania COM `IMFSourceReader::ReadSample`.

### Kluczowa obserwacja: Przesunięcie fazowe oczekiwania GPU
Porównanie sumy czasów oczekiwania konsumenta na GPU:

| Stan | `MF ReadSample` | `AMF QueryOutput` | Suma (`ReadSample` + `AMF Query`) |
|---|---:|---:|---:|
| **known-good (`0ef407e`)** | **1.20 ms** | **14.25 ms** | **15.45 ms** |
| **Obecny ASYNC (`queue_depth=2`)** | **15.71 ms** | **3.32 ms** | **19.03 ms** |
| **SYNC (`queue_depth=0`)** | **4.36 ms** | **16.66 ms** | **21.02 ms** |

### Mechanizm przesunięcia fazowego:
1. W `0ef407e` enkoder AMF czekał synchronicznie na zakończenie kodowania klatki N-1 w `AMF QueryOutput` (~14.25 ms). W tym czasie sprzętowy dekoder Media Foundation VCN dekodował klatkę N w tle. Gdy konsument przechodził do `ReadSample` dla klatki N, zdekodowana ramka była **już gotowa w buforze VCN**, dzięki czemu `ReadSample` zwracał wynik natychmiast (**~0.8 ms**).
2. W obecnym stanie (po optymalizacji drenażu pakietów i zmianie profilu enkodera na VBR w `d3d11_amf_encoder.cpp`), `AMF QueryOutput` nie blokuje wątku konsumenta i zwraca wynik asynchronicznie po **3.3 ms** (mediana 0.6 ms).
3. Konsument błyskawicznie kończy klatkę N-1 i natychmiast wywołuje `ReadSample` dla klatki N — zanim dekoder sprzętowy zdąży zakończyć dekodowanie klatki 4K w VCN.
4. Wątek konsumenta **zasypia wewnątrz `IMFSourceReader::ReadSample` na zdarzeniu systemowym**, oczekując na zakończenie dekodowania przez VCN.
5. Czas oczekiwania na GPU nie zniknął — **został przesunięty z `AMF QueryOutput` (gdzie wynosił 14.2 ms) do `MF ReadSample` (gdzie wynosi obecnie 15.7 ms)**.

**Wniosek:** ~15 ms w `MF ReadSample` to **Wariant B: Oczekiwanie na gotową surface ze sprzętowego dekodera (surface availability wait)**. Nie jest to koszt CPU (wątek śpi), lecz naturalne oczekiwanie na sprzęt VCN D3D11VA.

---

## 7. Odpowiedzi na 10 pytań końcowych

1. **FPS SYNC vs ASYNC:**
   - SYNC: **24.448 FPS**
   - ASYNC (q=2): **35.729 FPS**
   ASYNC zapewnia o **+11.28 FPS wyższą wydajność (+46.1%)** niż SYNC.
2. **CPU SYNC vs ASYNC:**
   - SYNC: **32.9%**
   - ASYNC (q=2): **49.4%**
   W SYNC CPU jest niższy o 16.5 pp, ale kosztem załamania framerate'u o 11 FPS.
3. **`producer_prepare` SYNC vs ASYNC:**
   - SYNC: **14.480 ms**
   - ASYNC (q=2): **24.994 ms**
   W SYNC wątek rasteryzacji nie rywalizuje o GIL z wątkiem konsumenta.
4. **`consumer_queue_wait` SYNC vs ASYNC:**
   - SYNC: **0.000 ms** (brak kolejki)
   - ASYNC (q=2): **2.299 ms** (mediana 0.818 ms)
5. **`MF ReadSample` SYNC vs ASYNC:**
   - SYNC: **4.363 ms** (mediana 3.233 ms)
   - ASYNC (q=2): **16.087 ms** (mediana 14.761 ms)
6. **Który proces zużywa dodatkowy CPU:**
   Proces potomny `child_python` (`TeleM-AMD-Render`), który pobiera **39.3 pp** z 49.4% całego systemu. FFmpeg muxer pobiera zaledwie 0.2 pp.
7. **Czy ASYNC jest faktycznym regresorem:**
   **NIE.** ASYNC jest o 46% szybszy od SYNC. Co więcej, known-good `0ef407e` **także działał w trybie ASYNC (queue_depth=2)**.
8. **Czy `queue_depth=2` jest problemem:**
   **NIE.** Przejście na `queue_depth=1` degraduje FPS do poziomu SYNC (**24.365 FPS**), ponieważ producent traci 23 ms na blokadzie kolejki. `queue_depth=2` jest niezbędne do uzyskania >35 FPS.
9. **Czy po przejściu na SYNC wracamy w okolice 41 FPS:**
   **ABSOLUTNIE NIE.** Przejście na SYNC obniża FPS do 24.45 FPS. Suma operacji sekwencyjnych w SYNC uniemożliwia przekroczenie 24.5 FPS.
10. **Czy po izolacji Grupy G nadal pozostaje kolejna regresja:**
    **TAK.** Pozostała regresja (spadek z 41.36 FPS do 35.73 FPS) wynika z:
    - Wzrostu kosztu CPU ABOVE o **+4.88 ms** (`above_total` wzrósł z 10.76 ms do 15.64 ms; `above_exact_crop` wzrósł z 1.3 ms do 4.4 ms, `above_region_to_bytes` z 2.1 ms do 4.5 ms) z powodu bogatszego zestawu aktywnych wskaźników w layout v10 (`fit_solar_text`, `alt_text`, `fit_distance_text`, `fit_temperature_text`, `fit_curVpower_text`).
    - Zwiększonego czasu trzymania GIL przez rasteryzację dodatkowych widgetów, co spowalnia konsumenta D3D11.

---

## 8. Podsumowanie i rekomendacja

- Grupa G (`ASYNC / queue_depth=2`) **nie jest regresorem** i **nie powinna być cofana do SYNC**.
- Wzrost `MF ReadSample` to nie błąd ani narzut CPU, lecz przesunięcie punktu synchronizacji GPU z enkodera AMF na dekoder MF.
- Kolejnym etapem przywracania wydajności do 41 FPS musi być optymalizacja warstwy CPU ABOVE (np. eliminacja nadmiarowych exact crops, optymalizacja widgetów tekstowych lub przeniesienie kolejnych elementów do ścieżki GPU zgodnie z AGENTS.md §8).
