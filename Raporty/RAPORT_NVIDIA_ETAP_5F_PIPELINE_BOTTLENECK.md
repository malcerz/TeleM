# TeleM — NVIDIA ETAP 5F: End-to-End Producer / IPC Bottleneck Audit

Data audytu: 2026-08-20. Audyt wykonano na aktualnym repozytorium, bez cofania wcześniejszych zmian.

## Zakres i zasady

Zbadano wyłącznie ścieżkę producenta end-to-end. Nie zmieniano chart renderer, gauge, atlas geometry, Direct-Region, NVDEC/NVENC, telemetry semantics, liczby workerów ani domyślnego `MAX_IN_FLIGHT`.

Konfiguracja produkcyjna:

```text
GX030120.MP4 + Popoludniowa_jazda_na_rowerze_solar_battery.fit
5400 frames, 29.970 FPS
NVIDIA / Direct-Region / Multi-Region Atlas
atlas 1900x762, 5 regionów, 5.52 MiB/frame
workers=4, MAX_IN_FLIGHT=8, preview=ON
```

Diagnostyka jest opt-in przez `TELEM_PIPELINE_AUDIT=1`. Przy wyłączonej zmiennej środowiskowej produkcyjna ścieżka nadal wysyła stare, dwu-elementowe joby `(frame, slot)`.

## A. Aktualny lifecycle

```text
main: frame scheduled
  -> acquire SHM slot
  -> executor.submit
  -> ProcessPool worker starts
  -> render_overlay_frame
  -> NumPy copy do SHM
  -> Future completed / result observed w main
  -> reorder_buf pozwala na kolejność
  -> get_memview + pipe_queue.put
  -> writer thread: stdin.write
  -> SHM release
```

Writer FFmpeg działa już w osobnym wątku. Kolejność wyników jest utrzymywana przez `pending` i `reorder_buf`; FFmpeg otrzymuje klatki w kolejności indeksów.

## B. Timestampy i artefakty

Do pomiaru użyto `time.perf_counter_ns()`. Dla każdej klatki zapisywane są timestampy:

```text
frame_scheduled
slot_acquired
submit_started / job_submitted
worker_started
worker_render_started / worker_render_finished
shm_copy_finished
future_completed / result_observed
ordered_output
shm_view_ready / queue_put_started / queue_put_finished
ffmpeg_write_started / ffmpeg_write_finished
shm_released
```

Pełny audyt 5400 klatek:

- [etap5f_production_audit_final.json](../scratch/etap5f_production_audit_final.json)
- [etap5f_production_audit_final.csv](../scratch/etap5f_production_audit_final.csv)

## C. Percentyle faz pipeline

Wartości w ms, pełny audyt 5400 klatek, `workers=4`, `MAX_IN_FLIGHT=8`.

| Faza | avg | median | p90 | p95 | p99 | max |
|---|---:|---:|---:|---:|---:|---:|
| wait_for_free_slot | 3.61 | 2.57 | 7.72 | 11.94 | 14.50 | 349.75 |
| executor.submit | 0.29 | 0.09 | 0.20 | 0.24 | 0.32 | 278.09 |
| worker queue delay | 5.39 | 5.10 | 11.42 | 13.19 | 16.54 | 240.98 |
| worker render | 7.38 | 6.78 | 9.39 | 13.45 | 18.17 | 40.30 |
| worker SHM copy | 7.97 | 7.71 | 10.05 | 11.91 | 15.18 | 23.22 |
| worker compute + copy | 15.35 | 14.54 | 18.98 | 25.66 | 30.01 | 46.07 |
| worker done → main observed | 6.04 | 4.62 | 11.99 | 14.03 | 18.99 | 682.91 |
| ordered-output / HOL wait | 1.00 | 0.03 | 4.59 | 6.90 | 10.96 | 21.79 |
| main SHM view | 0.005 | 0.004 | 0.008 | 0.010 | 0.014 | 0.177 |
| main `pipe_queue.put` | 0.010 | 0.005 | 0.020 | 0.024 | 0.035 | 0.186 |
| writer ready wait | 3.81 | 2.11 | 8.88 | 11.85 | 17.29 | 371.36 |
| FFmpeg `stdin.write` | 3.66 | 2.63 | 7.70 | 11.93 | 14.53 | 349.60 |
| SHM post-worker hold | 14.52 | 14.13 | 21.15 | 23.99 | 28.53 | 774.52 |
| SHM slot lifetime | 35.53 | 33.20 | 41.30 | 43.36 | 47.45 | 1003.52 |

Najważniejszy wniosek: `compose`/render nie jest całym kosztem worker job. Sama kopia RGBA do SHM ma medianę 7.71 ms i jest porównywalna z medianą renderowania 6.78 ms.

## D. Worker utilization

Wykryto 4 procesy workerów. Dla workerów busy percentage w aktywnym przedziale wyniósł odpowiednio około `85.2%`, `87.8%`, `87.6%`, `86.7%`; mediana to około `87.4%`.

Mediany jobów workerów wyniosły około `13.80–14.97 ms`, mediana między workerami około `14.69 ms`. Mediana idle gap między kolejnymi jobami każdego workera wyniosła około `0.90–0.94 ms`; duże maksima idle są głównie efektem startu/procesowego rozkładu pracy, nie stałego bezczynnego workera.

## E. Occupancy

Dla futures/reorder occupancy z 5400 próbek:

| Zakres | Udział |
|---|---:|
| 0–2 | 0.09% |
| 3–5 | 10.61% |
| 6–7 | 34.31% |
| 8 | 54.98% |

SHM było zajęte w 8 z 8 slotów w `99.87%` próbek pomiarowych. To oznacza, że obecny producer pracuje blisko granicy okna in-flight, ale samo zwiększenie okna nie musi poprawić przepustowości — weryfikacja sweepem jest w sekcji N.

## F. SHM lifetime

Slot jest zwalniany dopiero po zakończeniu `stdin.write`, zgodnie z aktualnym kontraktem. Nie zmieniano tego kontraktu.

Wynik:

- worker copy finished → SHM release: median `14.13 ms`, p95 `23.99 ms`;
- slot acquired → SHM release: median `33.20 ms`, p95 `43.36 ms`;
- 5400 klatek × `5,791,200 B` = `31,272,480,000 B` danych RGBA.

## G. Ordered-output / HOL

HOL jest rzeczywiście mierzalny, ale nie dominuje mediany:

- median `0.0325 ms`;
- p95 `6.90 ms`;
- 925 klatek miało oczekiwanie >1 ms;
- 487 klatek miało oczekiwanie >5 ms;
- suma oczekiwań ordered-output: `5416.7 ms`.

`reorder_buf` jest zatem źródłem ogonów opóźnień, lecz nie głównym ograniczeniem średniej przepustowości.

## H. Serialna praca main thread

Main thread nie wykonuje kosztownego compositingu HUD. Pomiar `get_memview` wyniósł medianę `0.0036 ms`, a `pipe_queue.put` `0.0050 ms`.

Preview callback był wywoływany około `4.14–4.21 Hz`; jego koszt w audycie miał medianę `0.0034 ms`, p95 `0.0067 ms`. Producer przekazuje do GUI stan klatki/progress; nie odtwarza pełnego kosztownego obrazu HUD dla każdej klatki.

Kontrolny monitor CPU (49 próbek):

- main process: średnio `52.2%`, maksimum `85.3%`;
- suma procesów worker: średnio `683.9%`, maksimum `953.4%`;
- system: średnio `31.5%`, maksimum `50.0%`;
- maksimum pojedynczego rdzenia: `100%` w części próbek.

Main thread nie jest stale wysycony. Obciążenie skupia się w workerach i ścieżce transferu.

## I. FFmpeg backpressure

`stdin.write` ma medianę `2.63 ms`, p95 `11.93 ms`; 5243 z 5400 zapisów trwało >1 ms, a 716 >5 ms. Suma zmierzonych czasów write wyniosła `19.77 s`.

Korelacja czasu write z occupancy in-flight: `-0.022`, czyli brak użytecznej liniowej zależności w tym przebiegu. Backpressure istnieje jako koszt writer-a, ale nie rośnie monotonicznie wraz z samym occupancy.

## J. Pipe bandwidth

```text
frame: 1900 × 762 × 4 = 5,791,200 B = 5.52 MiB
writer span: 23.707 s
total raw RGBA: 31.27 GB
writer throughput: 1.319 GB/s = 1319 MB/s
```

Jest to przepustowość zaobserwowana na `stdin.write`, a nie teoretyczna przepustowość systemu.

## K. Worker-only ceiling

Test: 5400 jobów, 4 workery, SHM, submit/receive/release, bez FFmpeg. Trzy powtórzenia dały `441.2`, `439.6`, `436.6 FPS`; mediana:

```text
WORKER_ONLY = 439.6 FPS
```

Pomiar joba worker-only: średnio około `7.94 ms`, mediana `7.65 ms`, p95 `9.74 ms` w środkowym przebiegu. Jest to sufit ścieżki bez konsumenta FFmpeg i nie jest bezpośrednio zamienny z produkcyjnym worker compute z pełnego audytu.

## L. Pipe-only ceiling

Test: Python wysyła prebuilt RGBA atlas do `pipe:0`; brak ProcessPool, Pillow i telemetry; ten sam atlas, 5 regionów, aktualny graf CUDA/overlay/NVENC. Trzy powtórzenia:

```text
313.30, 313.34, 320.33 FPS
PIPE_ONLY = 313.34 FPS median
```

## M. FFmpeg graph ceiling i pełna produkcja

Syntetyczny transparentny atlas, aktualny graf 5-regionowy, bez Pillow:

```text
364.68, 351.74, 367.27 FPS
FFMPEG_GRAPH = 364.68 FPS median
```

Pełna produkcja, 3 eksporty 5400 klatek, identyczne ustawienia:

| Run | FRAME_PIPELINE | REAL_EXPORT |
|---:|---:|---:|
| 1 | 225.9 FPS | 211.05 FPS |
| 2 | 225.8 FPS | 210.67 FPS |
| 3 | 223.5 FPS | 209.15 FPS |
| **mediana** | **225.8 FPS** | **210.67 FPS** |

Preview ON: 108 aktualizacji/export, około `4.14–4.22 FPS`. Kontrolny preview OFF: `222.8 FRAME_PIPELINE`, `208.7 REAL_EXPORT`; różnica mieści się w wariancji i nie wskazuje na istotny koszt callbacku preview.

## N. Sweep MAX_IN_FLIGHT

Sweep diagnostyczny użył 1200 klatek, więc `REAL_EXPORT` zawiera stały koszt końcowego drain FFmpeg i nie jest porównaniem do pełnego eksportu 5400 klatek. Wartości `FRAME_PIPELINE`:

| MAX_IN_FLIGHT | FRAME_PIPELINE | SHM | Wniosek |
|---:|---:|---:|---|
| 4 | 191.3 FPS | ~22 MB | za małe okno |
| 8 | 202.6 FPS | ~44 MB | dobry punkt |
| 12 | 208.9 FPS | ~66 MB | brak potwierdzonej przewagi end-to-end |
| 16 | 206.6 FPS | ~88 MB | brak przewagi |

Na krótkim przebiegu 12 było minimalnie wyżej od 8, ale różnica nie jest rozstrzygająca wobec wariancji i drain. Nie zmieniono produkcyjnego `MAX_IN_FLIGHT=8`; pełny audyt produkcyjny potwierdza, że przy 8 occupancy jest już wysokie.

## O. Sweep worker count

Diagnostycznie użyto 1200 klatek i odpowiednich okien `4/8/12`:

| Workers | MAX_IN_FLIGHT | FRAME_PIPELINE | REAL_EXPORT | worker compute median |
|---:|---:|---:|---:|---:|
| 2 | 4 | 183.5 FPS | 68.1 FPS | 8.97 ms |
| 4 | 8 | 209.0 FPS | 69.5 FPS | 14.44 ms |
| 6 | 12 | 208.2 FPS | 67.6 FPS | 16.24 ms |

Wynik wspiera utrzymanie `workers=4`; 6 workerów nie daje poprawy i zwiększa koszt per-job/SHM hold.

## P. CPU/GPU

W audycie CPU main nie był stale ograniczeniem, natomiast workery zajmowały średnio około 684% CPU łącznie. W pomiarach `nvidia-smi dmon` dla syntetycznego grafu obserwowano orientacyjnie:

- SM: średnio około 43–50%;
- NVENC: średnio około 59–70%;
- NVDEC: średnio około 71–84%.

GPU nie pracował przy stałym 100% SM/NVENC w syntetycznym teście, więc nie ma podstaw do wniosku, że bieżący limit to twardy sufit RTX 5070 Ti.

## Q. Ranking root cause

1. **Worker render + SHM copy** — pełny job ma medianę `14.54 ms`; copy do SHM (`7.71 ms`) jest niemal tak drogie jak render (`6.78 ms`). Workery są zajęte około `85–88%`.
2. **Przetrzymanie slotu do zakończenia write** — median `14.13 ms`, occupancy 8-slotowego SHM w `99.87%` próbek. To ogranicza swobodę dalszego submitowania, choć większe okna nie dały pewnej poprawy.
3. **FFmpeg stdin/writer** — median `2.63 ms`, p95 `11.93 ms`, suma `19.77 s`; pipe-only ceiling `313.34 FPS` jest wyraźnie wyższy niż produkcja, więc writer nie wyjaśnia całości samodzielnie.
4. **Result delivery/HOL** — p95 `6.90 ms`, suma `5.42 s`; realny koszt ogona, ale mediana `0.0325 ms`.
5. **Main thread callbacks/bookkeeping** — pojedyncze operacje są sub-milisekundowe; preview callback nie jest hotspotem.

## R. Jedna rekomendacja na następny etap — bez implementacji w ETAPIE 5F

Najbliższy pojedynczy etap powinien dotyczyć **transferu renderera do SHM i lifetime slotu**: zmierzyć oraz zoptymalizować `PIL/NumPy → SHM` i przekazanie ownership slotu writerowi, zachowując kolejność, alpha i brak dodatkowej kopii pełnego canvasu. To jest najbardziej obiecujący następny quick-win, ponieważ obecnie copy ma medianę `7.71 ms`, a slot pozostaje zajęty jeszcze około `14.13 ms` po zakończeniu renderowania.

Nie wdrożono tej rekomendacji w ETAPIE 5F. Nie zmieniono writer thread, reorder policy, slot lifetime, worker count ani `MAX_IN_FLIGHT`.

## Odpowiedzi końcowe

1. **Czy worker rendering jest bottleneckiem?** Tak, ale jako łączny `worker render + SHM copy`; sama funkcja renderująca nie jest jedynym kosztem.
2. **Worker-only FPS?** Mediana `439.6 FPS`.
3. **Pipe-only FPS?** Mediana `313.34 FPS`.
4. **Dokładna strata do ~224 FPS?** Produkcja ma medianę `225.8 FPS`: około `-213.8 FPS` względem worker-only, `-87.5 FPS` względem pipe-only i `-138.9 FPS` względem syntetycznego grafu FFmpeg. Są to różne sufity diagnostyczne, więc strat nie należy sumować.
5. **Czy main thread jest przeciążony?** Nie. Main średnio ~`52%` CPU, a `get_memview`/`queue.put` mają mediany poniżej `0.01 ms`; występują tylko epizodyczne ogony.
6. **SHM post-render hold?** Mediana `14.13 ms`, p95 `23.99 ms`.
7. **HOL?** Mediana `0.0325 ms`, p95 `6.90 ms`, 925 klatek >1 ms, 487 >5 ms.
8. **Czy MAX_IN_FLIGHT=8 jest optymalne?** Jest najlepszym potwierdzonym ustawieniem produkcyjnym i zachowuje rozsądny koszt pamięci; krótki sweep nie dowiódł przewagi 12/16, więc nie zmieniono 8.
9. **Czy workers=4 jest optymalne?** Tak w aktualnym sweepie: 2 jest wolniejsze, 6 nie poprawia pipeline i zwiększa koszt joba/SHM.
10. **Jeden następny etap implementacyjny?** Optymalizacja `SHM copy + ownership/lifetime transferu` — dopiero w osobnym etapie, po zachowaniu obecnego kontraktu i ponownym A/B.

## Zmienione pliki

- `src/ffmpeg/pipeline_audit.py` — opt-in agregator lifecycle/percentyli/occupancy.
- `src/ffmpeg/shared_memory.py` — opt-in timestampy workera i SHM copy.
- `src/ffmpeg/streaming.py` — opt-in timestampy main/reorder/writer oraz diagnostyczny override sweepów.
- `tests/test_etap5f_pipeline_audit.py` — test zapisu i opt-in.
- `scratch/run_etap5f.py`, `scratch/etap5f_ceilings.py` — harnessy pomiarowe.

## Weryfikacja

```text
targeted ETAP 5F/5E tests: 6 passed
full suite: 550 passed, 23 skipped, 3 failed
```

Trzy pozostałe failures są niezwiązane z ETAPEM 5F: dwa wymagają brakującego `native/d3d11_amf_pipeline/bin/telem_amd_native.dll`, a jeden oczekuje AMD w środowisku, które wykrywa NVIDIA.

Po tym raporcie ETAP 5F zostaje zatrzymany. Nie wdrożono żadnej optymalizacji z sekcji R.
