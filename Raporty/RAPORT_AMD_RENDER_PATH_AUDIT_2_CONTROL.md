# RAPORT: Kontrolny audyt ścieżki renderingu AMD — pełne rozliczenie 4K + GPU_SPLIT chartów

**Data pomiaru:** 2026-08-24
**Typ zadania:** `AUDIT ONLY / DIAGNOSTICS ONLY` (bez zmian funkcjonalnych; wyłącznie instrumentacja i testy)
**Kontynuacja:** `Raporty/RAPORT_AMD_RENDER_PATH_AUDIT.md`
**Maszyna:** AMD Ryzen 5 5500U + Radeon iGPU (gfx90c, pamięć współdzielona), Windows 11
**Backend:** `AMD_NATIVE_D3D11` — MF D3D11VA decode → D3D11 VideoProcessor → GPU compositor (NV12) → AMF HEVC → mux
**Materiał:** `Video/GX010115.MP4` (HEVC Main10 4K, 17760 klatek) + FIT (`offset +2.000 s`)
**Preset:** `presets/cycling_dashboard_v10.json`

---

# SEKCJA 1 — Accounting 4K full (300 klatek, pełny preset)

Świeży pomiar 300 klatek 4K @ 60 (5 s wideo) z `AMD_FRAME_TRACE=1` + `AMD_NATIVE_FRAME_ACCOUNTING=1` + `AMD_GPU_TIMESTAMP_PROFILE=1`.
**render_fps = 12.06** (średni czas klatki 84.3 ms).

## 1.1 Rozliczenie klatki (300 klatek, ms)

| Poziom | mean | med | p95 | p99 | max | Uwaga (exclusive/overlap) |
|---|---:|---:|---:|---:|---:|---|
| **FRAME WALL CLOCK** | **84.30** | 63.65 | 83.34 | 154.09 | 4883.70 | mierzone `perf_counter` wokół producer+consumer |
| producer (CPU) | 45.89 | 42.59 | 56.06 | 68.06 | 423.77 | `_prepare_frame_cpu` |
| consumer (GPU/CPU) | 38.41 | 19.84 | 28.05 | 53.22 | 4833.52 | `_consume_prepared_frame` |
| inter-frame gap | 0.03 | 0.02 | 0.04 | 0.12 | 0.15 | między klatkami w SYNC |

**Weryfikacja:** `producer + consumer + gap = 45.89 + 38.41 + 0.03 = 84.33 ≈ FRAME WALL 84.30 ms`. **Rachunek domyka się na poziomie klatki w 100%.**

## 1.2 Rozbicie producer (mean, ms)

| Podetap | mean | med | exclusive |
|---|---:|---:|---|
| telemetry (PRECOMPUTED) | 0.03 | 0.03 | tak |
| compose BELOW (time/distance/battery/solar) | 4.72 | 4.40 | tak |
| **above_compose (render ABOVE: charty, compass, slope, …)** | **23.18** | 22.17 | tak |
| **above_region_to_bytes** | **7.90** | 6.95 | tak |
| above_region_upload (przygotowanie) | 2.07 | 1.79 | tak |
| map working image | 2.10 | 2.00 | tak |
| HUD dirty extract | 0.83 | 0.72 | częściowo (wchodzi w PIL prep) |
| PIL/buffer preparation | 0.99 | 0.77 | rodzic HUD dirty |
| **producer_other (reszta)** | ~4.1 | ~3.8 | bbox plan, ekspedycja, narzut |
| **RAZEM producer** | **45.89** | 42.59 | ≈100% |

## 1.3 Rozbicie consumer (mean, ms)

| Podetap | mean | med | exclusive |
|---|---:|---:|---|
| decode (MF ReadSample) | 1.13 | 0.59 | tak |
| consumer_upload (chart/gauge/map/above/HUD uploady) | 5.80 | 6.31 | tak |
| **consumer_native_call (`telem_amd_process_frame`)** | **31.26** | 14.58 | zawiera VP+AMF |
| ├ VideoProcessor CPU submit | 4.85 | 0.29 | **w spike'ach ogromny (1345 ms!)** |
| ├ **VideoProcessor GPU completion** | **27.14** | 9.64 | **GPU czas + wait; zawiera GPU wait** |
| ├ GPU wait/synchronization | 11.39 | 9.97 | **nakłada się z GPU completion (wait na to samo GPU)** |
| ├ AMF submit/backpressure | 0.34 | 0.30 | tak |
| ├ AMF QueryOutput | 0.16 | 0.13 | tak |
| └ Packet write | 0.17 | 0.14 | tak |
| **RAZEM consumer (pipeline_total)** | **38.41** | 19.84 | ≈100% |

> **WAŻNE — nakładanie timerów:** `VideoProcessor GPU completion` i `GPU wait/synchronization` **mierzą to samo GPU**. `gpu_wait` to **blokujący busy-wait** (`while GetData()==S_FALSE {}`) czekający na zakończenie pracy, której czas to `gpu_completion`. **To nie są dwa niezależne koszty — to jeden koszt (czekanie CPU na GPU) mierzony z dwóch stron.** Dlatego przy prostym sumowaniu `consumer_children_sum` > `consumer_ms` (tzw. „ujemne unaccounted” ≈ −102 ms w 4K nohud) — to artefakt nakładania, nie brakujący czas.

## 1.4 Distribucja czasu klatki (300 klatek)

| Bucket | Liczba klatek | % |
|---|---:|---:|
| 25–50 ms | 0 | 0% |
| 50–100 ms | 295 | 98.3% |
| 100–200 ms | 3 | 1.0% |
| > 500 ms (spike) | 2 | 0.7% |

**Średnia (84.3 ms) >> mediana (63.7 ms)** — rozkład ogonowy. **FPS = 1/mean = 11.9**, nie 1/median.

## 1.5 Źródło spike'ów (natywny frame accounting)

| Klatka | process_frame_total [ms] | vp_total [ms] | vp_submit_window [ms] | AMF submit [ms] |
|---|---:|---:|---:|---:|
| 0 (warm-up) | 41.1 | 36.7 | 11.4 | 3.7 |
| **30** | **4828.5** | **4827.7** | **1345.3** | 0.24 |
| 3 | 44.0 | 41.9 | 0.3 | 0.96 |
| … steady state | 14–34 | 13–33 | 0.2–0.5 | 0.2–0.8 |

**Klatka 30 = 4.83 s**: `vp_submit_window` 1345 ms (CPU utknął w D3D11 submission) + `vp_total` 4828 ms (GPU wait). To **zastój sterownika D3D11** (shared iGPU), nie normalne działanie. Jeden taki spike w 60-klatkowym przebiegu dodaje ~80 ms/klatkę do średniej.

---

# SEKCJA 2 — Accounting 4K no-overlay (300 klatek)

**render_fps = 25.75** (średnia klatka 38.8 ms).

## 2.1 Rozliczenie klatki (300 klatek, ms)

| Poziom | mean | med | p95 | p99 | max |
|---|---:|---:|---:|---:|---:|
| **FRAME WALL CLOCK** | **38.81** | 21.78 | 56.78 | 152.21 | 4054.88 |
| producer | 0.03 | 0.03 | 0.06 | 0.11 | 0.14 |
| consumer (= native) | 38.78 | 21.74 | 56.76 | 152.17 | 4054.86 |
| inter-frame gap | 0.02 | 0.01 | 0.04 | 0.07 | 0.12 |

## 2.2 Rozbicie consumer (mean, ms)

| Podetap | mean | med | max |
|---|---:|---:|---:|
| decode (MF ReadSample) | 1.19 | 0.60 | 107.4 |
| consumer_upload | 0.00 | 0.00 | — |
| **consumer_native_call** | **37.44** | 20.65 | 4053.8 |
| ├ VideoProcessor CPU submit | 5.13 | 0.31 | 1423.5 |
| ├ **VideoProcessor GPU completion** | **35.88** | 18.45 | 4044.9 |
| ├ GPU wait/synchronization | 22.35 | 18.06 | 148.8 |
| └ AMF (submit/query/write) | 0.71 | 0.49 | — |

## 2.3 Distribucja czasu klatki

| Bucket | Liczba | % |
|---|---:|---:|
| < 25 ms | 166 | 55.3% |
| 25–50 ms | 114 | 38.0% |
| 50–100 ms | 15 | 5.0% |
| 100–200 ms | 4 | 1.3% |
| > 500 ms (spike) | 1 | 0.3% |

## 2.4 ODPOWIEDŹ: dlaczego ~20 ms `consumer_native` daje ~9.9 FPS zamiast ~50 FPS?

**Założenie w poprzednim raporcie było oparte na MEDIANIE (20.0 ms), a FPS zależy od ŚREDNIEJ.**

- Poprzedni raport: test_D 60 klatek → `consumer_native med=20.02`, `render_fps=9.91` (100.9 ms/klatkę). To było interpretowane jako „brakujący czas”.
- **Prawda:** rozkład jest ogonowy. Mediana 20 ms, ale **średnia w 60-klatkowym przebiegu była ~96–100 ms** (p99 = 1862 ms; jedna klatka 30 trwała ~4 s).
- Świeży 300-klatkowy pomiar: **mean = 38.8 ms → 25.8 FPS steady-state**, mediana 21.8 ms. FPS = 1/mean, więc **25.75 FPS jest w pełni spójne** z accountingiem.
- **Gdzie „znikał” czas:** (a) jeden katastrofalny zastój sterownika w klatce 30 (~4 s) — w krótkim 60-klatkowym przebiegu dodaje ~80 ms/klatkę do średniej; (b) warm-up (klatki 0–4: 40–60 ms); (c) w steady-state czas idzie na **blokujące czekanie CPU na GPU** (VP `gpu_wait` ≈ 18 ms mediany) — GPU jest wąskim gardłem, CPU spinuje w `GetData`.
- **Nie ma fixed pacing ani ukrytego wait między klatkami:** `inter_frame_gap = 0.01–0.12 ms`, brak `flush`/`join` w pętli, `AMF retries (input_full) = 0`.
- **Throttling:** nie wykryto jawnego. Spowolnienie wynika z realnej pracy GPU (VP+encode 4K na wspólnej grafice iGPU) oraz sporadycznych zastojów sterownika.

> **Wniosek:** wcześniejsza teza o „sprzętowym limicie ~9.9 FPS” była **artefaktem krótkiego przebiegu trafionego zastojem sterownika**. Rzeczywisty steady-state 4K no-overlay to **~25.8 FPS**, a 4K full to **~12 FPS**. Spike'y (do ~4 s) są realne i obniżają średnią, ale nie są „normalnym” limitem.

---

# SEKCJA 3 — Timeline reprezentatywnej klatki (4K full)

## 3.1 Klatka steady-state (frame 150) — 59.0 ms

```text
 0.000  frame start (producer)
 0.025  telemetry lookup (PRECOMPUTED)
 3.656  compose BELOW (time, distance, battery, solar)
 25.075 above_compose (charty + compass + slope + ...)   [21.42 ms]
 32.222 above_region_to_bytes (tobytes 7.15 ms)
 33.716 above_region_upload (1.49 ms)
 35.723 map working image (2.01 ms)
 40.429 PRODUCER DONE (40.43 ms)
 40.450 handoff -> consumer (gap 0.02 ms)
 40.979 decode ReadSample (0.53 ms)
 48.452 consumer_upload (7.47 ms: HUD/above/map -> GPU)
 50.894 VP CPU submit (0.25 ms)
 59.409 VP GPU completion + GPU wait (8.5-8.8 ms, NAKŁADAJĄCE SIĘ)
 59.009 FRAME COMPLETE (consumer 18.58 ms)
```

## 3.2 Klatka spike (frame 30) — 4883.7 ms

```text
 0.000  frame start (producer 50.2 ms, normalny)
 50.179 producer done
 50.204 consumer start
 51.704 decode (1.5 ms)
 54.979 consumer_upload (3.3 ms)
 55.233 VP CPU submit START -> 1345.3 ms zastoj sterownika (submit window)
1400.5  VP GPU completion 4813.3 ms (czekanie na GPU)
4833.5  FRAME COMPLETE (consumer 4833.5 ms)
```

> Okresy WAIT/IDLE: w steady-state czas to głównie **blokujący wait na GPU** wewnątrz `telem_amd_process_frame` (`GetData` spin). W spike — **zastój sterownika D3D11** w ścieżce submission. Brak czekania na kolejce/threadach w trybie SYNC (gap 0.02 ms).

---

# SEKCJA 4 — GPU_SPLIT chartów (HR / Cadence)

## 4.1 Trace decyzji (AMD_CHART_TRACE=1, pełny preset, 1080p)

```text
CHART_TRACE fit_cadence_text requested=GPU_SPLIT final=CPU_REFERENCE
    reason='overlaps widget bbox=(681,763,558,73)' map_dst=(1416,209,317,317)
CHART_TRACE fit_heart_rate_text requested=GPU_SPLIT final=CPU_REFERENCE
    reason='overlaps widget bbox=(681,763,558,73)'
GPU charts fallback -> CPU_REFERENCE (GPU_CHART_UNSAFE_LAYOUT -> all charts CPU_REFERENCE: ...)
```

| Pytanie | Odpowiedź |
|---|---|
| requested | `GPU_SPLIT` (AMD_CHART_PATH=GPU_SPLIT) |
| final | `CPU_REFERENCE` (render Pillow → dirty region ABOVE) |
| reason | `GPU_CHART_UNSAFE_LAYOUT`: chart nachodzi na `dist_visual` |
| file | `src/ffmpeg/amd_native_exporter.py` |
| function | `_chart_gpu_layout_safe` (linia ~183) |
| condition | `cx < bx+bw and bx < cx+cw and cy < by+bh and by < cy+ch` — chart bbox vs bbox `dist_visual` |

## 4.2 Warunek blokujący (pełny preset)

W 1080p bboxy (probe render):
- `fit_cadence_text` = **(198, 770, 526, 233)** → y 770–1003
- `fit_heart_rate_text` = **(870, 770, 526, 233)** → y 770–1003
- **`dist_visual` (Distance) = (681, 763, 558, 73)** → x 681–1239, y 763–836

`dist_visual` (pozioma linijka dystansu na dole ekranu) **nachodzi na oba charty** (przecięcie x i y), więc guard z-order (`_chart_gpu_layout_safe`) odrzuca je → `GPU_CHART_UNSAFE_LAYOUT`.

## 4.3 Drugi, strukturalny bloker (map split)

Nawet gdyby guard zaakceptował charty (co dzieje się w prostszych layoutach), w pełnym presecie działa dodatkowy mechanizm:
- `_ordered_map_layout_parts` dzieli layout na `compose_layout` (BELOW) i `map_above_layout` (ABOVE).
- Charty w presecie v10 są **po `track_map`** → trafiają do `map_above_layout`.
- Compose ABOVE wywoływany jest z `gpu_capture_keys=set()` i `split_chart_keys=None` (exporter ~linia 2390).
- Capture chartów dla GPU działa **tylko w compose BELOW** (`gpu_capture_keys=capture_keys`), a BELOW nie zawiera chartów (są po mapie).
- → **charty po mapie nigdy nie zostają uchwycone do GPU**, niezależnie od guarda.

Dowód: **test5/test7** (charty po mapie) mają `active_gpu_charts=[…]` (guard je przyjął), ale `static_uploads=0`, `dynamic_uploads=0` — **nie dotarły do GPU**.

## 4.4 `cadence_gpu=0` / `hr_gpu=0` — martwy licznik

`chart_gpu_frames` w exporterze **nigdy nie jest inkrementowane** (tylko inicjalizowane i odczytywane). Wartości `cadence_gpu`/`hr_gpu` w `frame_accounting` są **zawsze 0 i nie są dowodem** — prawdziwym wskaźnikiem są `etap5k.static_uploads`/`dynamic_uploads` oraz natywne statystyki `BlendCharts`.

---

# SEKCJA 5 — Macierz testów chart path (1080p, 90 klatek)

| # | Test (kolejność layoutu) | Guard (probe) | static_uploads | dynamic_uploads | `active_gpu_charts` | Final |
|---|---|---|---|---|---|---|
| 1 | HR tylko | GPU safe | 1 | 180 | [HR] | **GPU_SPLIT ✓** |
| 2 | Cadence tylko | GPU safe | 1 | 180 | [CAD] | **GPU_SPLIT ✓** |
| 3 | HR + Cadence | GPU safe | 2 | 360 | oba | **GPU_SPLIT ✓** |
| 4 | HR+CAD → map (przed mapą) | GPU safe | 2 | 360 | oba | **GPU_SPLIT ✓** |
| 5 | map → HR+CAD (po mapie) | GPU safe | **0** | **0** | oba (stale) | **CPU/ABOVE ✗** |
| 6 | HR+CAD+elem → map | GPU safe | 2 | 360 | oba | **GPU_SPLIT ✓** |
| 7 | map → HR+CAD+elem | **CPU (overlap)** | **0** | **0** | oba | **CPU/ABOVE ✗** |
| 8 | **pełny preset v10** | **CPU (overlap `dist_visual`)** | **0** | **0** | [] | **CPU/ABOVE ✗** |
| — | gpu_charts_working (HR+CAD) | GPU safe | 2 | 360 | oba | **GPU_SPLIT ✓** |
| — | cpu_charts_reference (HR+CAD, CPU_REFERENCE) | — | 0 | 0 | [] | CPU |

**Wnioski z macierzy:**
1. **GPU_SPLIT DZIAŁA** — gdy charty są przed mapą lub bez mapy, static tile wgrywany raz (490 KB/chart), dynamiczne tile kursor/wartość per-klatka.
2. **Charty po mapie (test5/7/8) nigdy nie trafiają na GPU** — map split (ABOVE bez capture).
3. **Dodatkowy z-order bloker w pełnym presecie**: `dist_visual` nachodzi na charty (test8).
4. `active_gpu_charts` w profilu to `sorted(gpu_chart_keys)`; dla test5/7 pokazuje stare wartości (guard przyjął, GPU nie zadziałało) — mylące, patrz sekcja 4.4.

## 5.1 Koszt CPU chart vs GPU_SPLIT chart (1080p, HR+CAD)

| Miernik | GPU_SPLIT | CPU_REFERENCE | Delta |
|---|---:|---:|---:|
| render_fps | 31.80 | 29.24 | **+2.6 FPS (+8.8%)** |
| compose_overlay med | 5.70 | 7.62 | **−1.92 ms** |
| producer_prepare med | 5.86 | 8.40 | **−2.54 ms** |
| consumer_native med | 5.52 | 4.92 | +0.6 (GPU blend) |
| upload (static+dyn) | 980 KB + 140 KB/f | 0 | +1.1 MB/f |

**Wniosek:** GPU_SPLIT w prostym layoucie daje ~1.9–2.5 ms oszczędności na klatkę (compose) przy niewielkim wzroście uploadu i GPU blend. W pełnym presecie jest **niedostępne** (sekcja 4).

---

# SEKCJA 6 — Wnioski (odpowiedzi na pytania)

**1. Gdzie był „brakujący” czas 4K?**
Nie było brakującego czasu. Poprzedni raport porównywał **medianę** (20 ms) z FPS liczonym ze **średniej**. Rozkład czasu klatki jest ogonowy (spike'y do ~4 s, głównie zastój sterownika w klatce 30 i warm-up). Średnia consumer ≈ średnia klatka; `FPS = 1/mean`. Nowe 300-klatkowe pomiary: **4K full 12.06 FPS, 4K no-overlay 25.75 FPS** (steady-state). W steady-state czas idzie na **blokujące czekanie CPU na GPU** (VP `gpu_wait`, busy-wait `GetData`) + CPU render overlay (above_compose 22 ms).

**2. Czy wcześniejszy wniosek o limicie ~9.9 FPS jest prawidłowy?**
**Nie.** 9.9 FPS (4K nohud, 60 klatek) było zdominowane przez jeden 4-sekundowy zastój sterownika (klatka 30) + warm-up. Rzeczywisty steady-state 4K no-overlay ≈ **25.8 FPS**. Spike'y są realne (obniżają średnią), ale nie stanowią stałego limitu sprzętowego.

**3. Czy `VP GPU completion` i `GPU wait` są niezależne czy się nakładają?**
**Nakładają się.** Mierzą to samo GPU: `gpu_wait` to blokujący busy-wait (`while GetData()==S_FALSE {}` w `d3d11_vp_pipeline.cpp::ProcessFrame`) czekający na zakończenie pracy, której czas to `gpu_completion`. **Nie sumować.** Prawdziwy koszt zatrzymujący pipeline to `gpu_wait` (czekanie CPU).

**4. Dlaczego GPU_SPLIT chartów nie działa w pełnym layoucie?**
Dwa powody: **(a)** guard z-order odrzuca oba charty, bo `dist_visual` (Distance, bbox (681,763,558,73) w 1080p) nachodzi na nie → `GPU_CHART_UNSAFE_LAYOUT`; **(b)** strukturalnie charty są po `track_map` → `map_above_layout` → compose ABOVE z `gpu_capture_keys=set()`, więc capture GPU nigdy ich nie obejmuje.

**5. Czy GPU_SPLIT działa w prostszym layoucie?**
**Tak** — bez mapy / z chartami przed mapą: static_uploads>0, dynamic_uploads>0, `active_gpu_charts` niepuste (testy 1–4, 6).

**6. Ile kosztuje CPU chart vs GPU_SPLIT chart?**
1080p, oba charty: **CPU_REFERENCE compose 7.62 ms vs GPU_SPLIT compose 5.70 ms** (−1.92 ms/klatkę, −2.54 ms producer) → **+8.8% FPS** (29.2 → 31.8). Koszt GPU: +~1.1 MB/f upload + blend w VP.

**7. Max 3 miejsca na przyszłą optymalizację (NIE wdrażano):**
1. **Usunięcie nakładania `dist_visual` z chartami** (przesunięcie linijki dystansu / zmiana bboxu) → odblokowuje guard; oraz **przeniesienie chartów przed `track_map`** (lub dodanie capture w compose ABOVE) → charty trafią na GPU_SPLIT. Potencjał: −2 ms/klatkę compose (1080p) i mniej w 4K.
2. **Redukcja `above_compose` (CPU render ABOVE, ~22 ms w 4K)** — głównie charty + reszta widgetów ABOVE; wraz z (1) charty opuszczają ABOVE.
3. **Eliminacja/łagodzenie spike'ów GPU** (zastój sterownika w `vp_submit_window`, ~4 s) — np. diagnostyka drivera/kolejki; oraz **ograniczenie remuxu audio** (z poprzedniego raportu: `-t`/`-shortest`), bo ~6.5–7 s stałego kosztu dominuje TRUE FPS.

---

# NA KOŃCU

## Zmienione pliki (produkcyjne)
- `src/ffmpeg/amd_native_exporter.py` — dodano **wyłączaną** instrumentację:
  - `AMD_CHART_TRACE=1` — per-chart log decyzji GPU_SPLIT w `_chart_gpu_layout_safe` (tylko dodaje `print`, zero zmiany logiki).
  - `AMD_FRAME_TRACE=1` — pełny per-klatkowy accounting (FRAME_TOTAL, producer/consumer, gap) w pętli SYNC + zapis `.frame_trace.csv`.
  - (plus wcześniejsza `AMD_AUDIT_ALLOCS` z poprzedniego audytu, dalej domyślnie OFF).

## Sposób wyłączenia/usunięcia
- Wszystkie nowe flagi są **domyślnie OFF** (nieustawione → zero narzutu, zachowanie produkcyjne identyczne).
- Usunięcie całej instrumentacji: `git checkout src/ffmpeg/amd_native_exporter.py` (przywraca oryginał; zmiana to wyłącznie dodane bloki pod `AMD_*_TRACE`/`AMD_AUDIT_ALLOCS`).

## Pliki diagnostyczne (scratch/ + Raporty/)
- `scratch/run_amd_render_path_audit2.py` — harness kontrolny (4K accounting + macierz chart path).
- `scratch/analyze_frame_trace.py`, `scratch/analyze_native_account.py`, `scratch/extract_chart_matrix.py`, `scratch/extract_chart_matrix2.py`, `scratch/extract_rep_frame.py`, `scratch/probe_chart_bboxes.py` — analiza.
- `Raporty/AMD_RENDER_PATH_AUDIT/account_4k_*.mp4.{frame_trace.csv, frame_accounting.csv, gpu_timeline.csv, amd_profile.json}`, `test*_*.mp4.amd_profile.json`, `Raporty/AMD_RENDER_PATH_AUDIT_2/audit2_summary.json` — wyniki.
- `scratch/audit2_*.log` — logi przebiegów.
- Usunięcie: skasować powyższe (nie są częścią builda).

## Potwierdzenia
- **Brak zmian funkcjonalnych** — dodana wyłącznie instrumentacja pod env-flagami (OFF domyślnie) i testy diagnostyczne; nie zmieniono logiki, Z-order, jakości, FPS, ścieżek, fallbacków.
- **NVIDIA i Intel nie zostały zmienione** — jedyny zmodyfikowany plik to `amd_native_exporter.py` (ścieżka AMD), a zmiany są env-guarded i wyłączone domyślnie. Ścieżka NVIDIA/Intel zachowana statycznie; walidacja runtime nie była możliwa na tej maszynie AMD (AGENTS.md §12).
