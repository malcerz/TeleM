# TeleM — NVIDIA ETAP 5G: Zero-Copy SHM Render Target

Data: 2026-08-20. Audyt i implementacja wykonane na aktualnym repozytorium.

## A. Zakres i konfiguracja

Zmieniono wyłącznie workerowe renderowanie atlasu RGBA bezpośrednio do slotu
SharedMemory. Nie zmieniano chart rendererów, gauge, atlas geometry,
Direct-Region, FFmpeg graph, NVDEC/NVENC, telemetrii, preview, workerów ani
`MAX_IN_FLIGHT`.

```text
GX030120.MP4 + Popoludniowa_jazda_na_rowerze_solar_battery.fit
5400 frames, 29.970 FPS
NVIDIA / DIRECT_REGION / MULTI_REGION_ATLAS
atlas 1900x762, 5 regions, 5.52 MiB/frame
workers=4, MAX_IN_FLIGHT=8, preview=ON
```

## B. Root cause i stan przed zmianą

Ścieżka 5F wykonywała:

```text
render_overlay_frame()
  -> local PIL RGBA atlas
  -> np.asarray(img)
  -> np.copyto(SHM ndarray, image ndarray)
  -> writer stdin.write(memoryview(SHM))
```

W pełnym audycie 5F mediana wynosiła około `7.71 ms` dla workerowego SHM
copy oraz `14.54 ms` dla worker compute+copy.

## C. Proof of concept mapowania Pillow

Na używanej wersji Pillow `Image.frombuffer()` dla RGBA nie daje użytecznego
zapisywalnego targetu: obraz jest readonly albo nie udostępnia zapisu do
podanego bufora. POC potwierdził działanie `Image.core.map_buffer` przez
adapter `src/ffmpeg/shm_image.py`.

Sprawdzone operacje na obrazie mapowanym do SHM:

- `ImageDraw`;
- `paste`;
- `alpha_composite`;
- zapis widoczny natychmiast w niezależnym NumPy view na SHM;
- ponowne użycie dwóch generacji targetu;
- `SharedMemory.close()` i `unlink()` bez `BufferError`.

`np.shares_memory` jest używane dla niezależnych NumPy views tego samego SHM.
Nie jest używane na `np.asarray(mapped_image)`, ponieważ taka konwersja sama
w sobie tworzy kopię.

## D. Implementacja

Dla aktywnego `DIRECT_REGION` worker wykonuje:

```text
acquire slot
  -> writable NumPy view na atlas SHM
  -> pełne transparentne clear: uint8.fill(0)
  -> Pillow Image.core.map_buffer na ten sam backing
  -> compose_overlay(target_image=mapped_target) dla regionów
  -> zamknięcie mapped Pillow wrappera
  -> zwrot (frame_index, slot, metadata)
```

W tej gałęzi nie występują już `np.asarray(full_atlas)` ani
`np.copyto(full_atlas, shm)`. Fallback pozostaje aktywny: jeżeli mapowanie
lub operacja Pillow na targetcie nie powiedzie się, bieżąca klatka wraca do
istniejącej ścieżki local PIL → NumPy → SHM. W benchmarku produkcyjnym fallback
nie wystąpił.

Clear jest pełny przed każdym renderem, więc rozwiązanie nie zależy od
kolejności klatek ani od ponownego przydzielenia tego samego slotu.

## E. Zmodyfikowane pliki

- `src/ffmpeg/shm_image.py` — adapter zapisywalnego Pillow targetu SHM;
- `src/ffmpeg/shared_memory.py` — clear, mapowanie targetu, fast path i fallback;
- `src/ffmpeg/frame_renderer.py` — `target_image`, direct region i cut-frame;
- `tests/test_etap5g_zero_copy_shm.py` — testy backing, compositingu, clear i reuse;
- `scratch/etap5g_poc.py`, `scratch/benchmark_etap5g_target.py` oraz aktualny
  `scratch/etap5f_ceilings.py` — harnessy pomiarowe.

Istniejącą integrację lifecycle z `src/ffmpeg/streaming.py` i
`src/ffmpeg/pipeline_audit.py` wykorzystano do pomiaru metadanych zero-copy;
nie wymagała ona dodatkowej zmiany w tym etapie. Nie zmieniono ustawień
FFmpeg/NVENC/NVDEC ani liczby workerów.

## F. Proof braku pełnej kopii atlasu

Dowód opiera się na trzech obserwacjach:

1. mapped Pillow `ImageDraw`, `paste` i `alpha_composite` zmieniają bajty
   niezależnego NumPy view SHM;
2. worker zero-copy nie wykonuje `np.asarray(img)` ani `np.copyto`;
3. audyt oznaczył `5400/5400` klatek jako `zero_copy=true`, `fallback=0`.

Pozostają małe, lokalne kopie widgetów wymagane przez istniejące operacje
komponentów, np. crop/transpose ROT180. Nie ma pełnej kopii `1900x762x4`
pomiędzy PIL atlasem a SHM.

## G. Pixel parity

Na rzeczywistym layoucie porównano starą ścieżkę copy i nowy mapped target
dla checkpointów:

```text
0, 10%, 25%, 50%, 75%, 90%, frame 5000 (przed FIT gap),
frame 5200 (wewnątrz FIT gap), frame 5399 (ostatnia klatka / 100%)
```

Wynik dla każdego checkpointu:

```text
max_diff = 0
different_bytes = 0
```

W tym materiale pierwszy rekord po długiej luce FIT wypada poza 5400-klatkowy
film; rozcięcie segmentu i zachowanie historii przed/po luce jest objęte
istniejącymi testami chartów. Ścieżka nie zmienia semantyki `None`, zera
cadence ani dynamicznych pól FIT.

ROT180: istniejący test produkcyjnego atlasu dla 5 checkpointów przeszedł z
`max_diff=0` i `different_pixels=0`. Obrót 90°/270° korzysta z istniejącego
CPU-rotation path; nowy target nie jest dla niego aktywowany.

## H. Testy bezpieczeństwa i lifecycle

```text
pytest tests/test_etap5*.py tests/test_nvidia*.py
25 passed

pytest (pełny suite)
553 passed, 23 skipped, 3 failed
```

Trzy pełne suite failures są niezwiązane z ETAPEM 5G: brak DLL
`native/d3d11_amf_pipeline/bin/telem_amd_native.dll` w dwóch AMD smoke tests
oraz test fallbacku encodera oczekujący AMD w środowisku NVIDIA.

Dodatkowy smoke produkcyjny 100 klatek z preview ON przeszedł. Writer nadal
zwalnia slot po `stdin.write`; nie dodano drugiego writera ani zmiany ownership.

## I. Microbenchmark 2000 real frames

Pomiar wykonano na realnym layoucie. Wartości to `avg / median / p95`, w ms:

| Metryka | przed: local PIL + copy | po: mapped target |
|---|---:|---:|
| render | 2.102 / 2.118 / 2.637 | 1.114 / 1.090 / 1.270 |
| clear | — | 0.213 / 0.206 / 0.236 |
| SHM transfer | 2.212 / 2.331 / 2.761 | 0 / 0 / 0 |
| worker job wall | 4.477 / 4.621 / 5.429 | 1.357 / 1.329 / 1.532 |

To izolowany pomiar funkcji workerowej; nie jest bezpośrednim zamiennikiem
pełnego audytu ProcessPool.

Worker-only ProcessPool po zmianie:

```text
1222.86, 1213.18, 1213.76 FPS
mediana: 1213.76 FPS
worker job median: około 2.12 ms
```

## J. Ceilings pipeline

Trzy przebiegi po 5400 klatek:

```text
FFmpeg graph median: 352.22 FPS
pipe-only median:    308.35 FPS
worker-only median:  1213.76 FPS
```

Zero-copy nie przesunął ograniczenia do workerów; dominują writer/pipe i graf
CUDA/FFmpeg.

## K. Produkcyjny benchmark 3 eksportów

Każdy eksport używał `preview=ON`, `DIRECT_REGION`, 5-region atlasu,
`workers=4`, `MAX_IN_FLIGHT=8` i tej samej konfiguracji kodera.

| Metryka | prod1 | prod2 | prod3 | mediana |
|---|---:|---:|---:|---:|
| FRAME_PIPELINE FPS | 255.2 | 282.6 | 289.2 | **282.6** |
| REAL_EXPORT FPS | 233.1 | 255.1 | 261.2 | **255.1** |
| preview FPS | 4.66 | 5.10 | 5.22 | **5.10** |
| worker render median ms | 2.967 | 2.742 | 2.740 | **2.742** |
| clear median ms | 0.346 | 0.330 | 0.332 | **0.332** |
| SHM copy median ms | 0 | 0 | 0 | **0** |
| worker compute median ms | 3.447 | 3.191 | 3.197 | **3.197** |
| ffmpeg stdin write median ms | 2.217 | 2.071 | 2.002 | **2.071** |
| SHM slot lifetime median ms | 29.335 | 26.557 | 25.934 | **26.557** |

Wszystkie trzy audyty raportują:

```text
zero_copy frames: 5400 / 5400
fallback copy frames: 0
HUD producer: DIRECT_REGION
```

## L. Największy hotspot po ETAPIE 5G

Workerowy full-atlas copy został usunięty. Aktualnym ograniczeniem jest
backpressure writer/FFmpeg: mediana `writer_ready_wait` wynosiła około
`5.84–6.30 ms`, a mediana `stdin.write` około `2.00–2.22 ms`. Izolowany graf
FFmpeg ma około `352 FPS`, a pipe-only około `308 FPS`.

## M. Uwagi o zgodności

`TELEM_ZERO_COPY_SHM=0` wymusza dotychczasową ścieżkę copy dla A/B i awarii.
Domyślna fast path działa tylko dla zaplanowanego `DIRECT_REGION`; pozostałe
tryby transportu zachowują dotychczasową implementację.

Nie zmieniono dynamicznego wykrywania pól FIT, chart data, semantyki źródeł,
`None != 0`, cadence zero, SmartSync ani timeline.

## N. Wnioski końcowe

1. `activity start → current` i semantyka chartów pozostały bez zmian; 5G
   zmienił wyłącznie target pamięci atlasu.
2. W poprawnej ścieżce nie występuje pełna kopia PIL → NumPy → SHM; fallback
   jest dostępny, lecz w 3 eksportach nie został użyty.
3. Pixel parity atlasu i ROT180 wynosi `max_diff=0`, `different=0`.
4. Clear kosztuje około `0.332 ms median` w produkcji; transfer SHM jest
   raportowany jako `0 ms`, bo dane są zapisywane bezpośrednio w target.
5. Produkcyjna mediana to `282.6 FRAME_PIPELINE FPS` i `255.1 REAL_EXPORT FPS`.
6. Direct-Region pozostał aktywny; FFmpeg graph, pipe format, NVDEC/NVENC,
   workers i MAX_IN_FLIGHT pozostały bez zmian.

Po tym etapie zatrzymano dalszą optymalizację.
