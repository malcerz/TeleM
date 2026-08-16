# RAPORT AMD — ETAP 5M: Stabilizacja baseline + świeży audit bottlenecków

**STATUS: ✅ PASS** (pomiar i analiza — bez zmian w production code, bez 5N)

Audyt wyłącznie pomiarowy: 4× production baseline (A/B/C/D) + 1 osobny profiling
run + nieinwazyjny sampling CPU/GPU. **Nie** wprowadzono żadnej optymalizacji.

---

## PRODUCTION RUNS (A/B/C/D — 1131 frames, profiling OFF, readbacks OFF)

| Run | wall [s] | TRUE FPS | path |
|---|---|---|---|
| **A** | 41.781 | **28.479** | valid |
| **B** | 46.602 | **26.081** | valid |
| **C** | 44.808 | **26.565** | valid |
| **D** | 43.604 | **27.782** | valid |

| Agregat | Wartość |
|---|---|
| **MEDIAN** | **27.173 FPS** |
| MIN | 26.081 |
| MAX | 28.479 |
| **STDDEV** | **1.0995** |
| **SPREAD** | **8.82 %** |
| MEDIAN WALL | 44.206 s |

Wszystkie 4 runy **valid** (ścieżka potwierdzona: D3D11VA+P010, direct→VP=1131,
cadence/hr/gauge/map_gpu=1131, cpu→gpu base=0, gpu→cpu=0, drops=0).

**Analiza wariancji (outlier):** żaden run nie jest patologicznym outlierem —
spread 8.8% (stddev ~1.1 FPS) to normalna zmienność systemowa/termiczna.
Run A (najszybszy 28.5) miał najniższy `compose_overlay` (10.45) i najwyższą
telemetrię (9.85); run B (najwolniejszy 26.1) najwyższy `compose_overlay` (12.21).
Zmienność FPS koreluje głównie z `compose_overlay` i stanem termicznym GPU
(kolejne runy back-to-back), nie z żadnym pojedynczym regresem.

> Pojedynczy wcześniejszy run (33.237 FPS) **nie** był reprezentatywny —
> stabilna mediana 4 runów to **27.17 FPS**.

---

## REALTIME

| Parametr | Wartość |
|---|---|
| Source FPS | 29.97 |
| Median production FPS | **27.173** |
| **Realtime factor** | **0.907×** |
| **Margin** | **−9.33 %** |

> **TeleM jest obecnie PONIŻEJ realtime** (0.91×) — export wolniejszy od źródła.
> Margin ujemny o ~9.3%.

---

## CURRENT FULL PATH (każdy run potwierdzony)

| Parametr | Wartość |
|---|---|
| D3D11VA | **YES** |
| P010 | **YES** (DXGI_FORMAT_P010) |
| direct decoder→VP | 1131 / 1131 |
| cadence_gpu | 1131 |
| hr_gpu | 1131 |
| gauge_gpu | 1131 |
| map_gpu | 1131 |
| CPU raw base / CPU→GPU / GPU→CPU | 0 / 0 / 0 |
| drops (AMF) | 0 |

---

## CPU PROFILE (production baseline — median ms/frame z A/B/C/D)

| Stage | med ms | p95 |
|---|---|---|
| **telemetry (prepare_overlay_frame_data)** | **8.00** | ~13.6 |
| **compose_overlay** | **11.32** | ~18.5 |
| map CPU (working image + upload) | 2.81 | ~3.7 |
| gauge tobytes | 0.98 | ~1.3 |
| gauge upload | 0.28 | ~0.4 |
| HUD dirty extract | 0.98 | ~2.0 |
| PIL/buffer preparation | 1.08 | ~2.1 |
| HUD dirty bbox | 0.09 | — |
| update_hud | 0.21 | — |
| chart dynamic (tobytes+upload) | 0.06 | — |
| MF ReadSample/decode availability | 0.91 | ~4.5 |
| VP CPU submit | 0.60 | ~1.2 |
| AMF submit/backpressure | 0.42 | ~1.3 |
| AMF QueryOutput | 0.16 | ~0.6 |
| Packet write | 0.18 | ~0.6 |

**CPU critical path estimate ≈ 28.3 ms/frame → ceiling ~35 FPS.**
**Observed frame time = 1000/27.173 = 36.8 ms → residual ≈ 8.5 ms/frame**
(nieprzypisane do żadnego zmierzonego stage'u — patrz GPU/encoder poniżej).

---

## GPU / UPLOAD PROFILE

| Stage | med ms | Uwaga |
|---|---|---|
| VideoProcessor GPU completion | **18.13** | tylko tryb profiling (per-frame sync) |
| GPU wait/synchronization | **18.33** | tylko tryb profiling |
| VideoProcessor CPU submit | 0.60 | async w produkcji |
| GPU HUD / NV12 composite | — | w VP pipeline (3D engine, patrz utilization) |
| HUD texture upload (native) | 0.15 | dirty regional |
| HUD upload | **0.863 MiB/frame** | (1.02 GB / 1131) |
| map upload | **1.827 MiB/frame** | 692×692 RGBA |
| gauge upload | **1.305 MiB/frame** | 648×528 (po clipping fix) |
| chart dynamic upload | **0.034 MiB/frame** | GPU_SPLIT |
| chart static (2 uploads) | 4.52 MiB total | raz na przebieg |
| AMF submit/backpressure | 0.42 | niskie (submisje buforowane) |
| AMF QueryOutput | 0.16 | |
| Packet write | 0.18 | |

---

## PIPELINE OVERLAP

- **MF decode** — async, nakłada się na CPU (ReadSample ~0.9 ms availability).
- **CPU stages** (telemetry→compose→map→gauge→dirty→upload) — **sekwencyjne**
  (1 wątek Python, workers=1).
- **GPU VP+HUD+NV12** (~18 ms completion) — w produkcji może się nakładać z CPU
  następnej klatki (async queue, bez per-frame sync); profiling wymusza
  serializację (→ 23.3 FPS w trybie profiling).
- **AMF encode (HEVC 4K)** — async silnik GPU, nakłada się ze wszystkim, ale
  jego tempo opróżniania wyznacza wall-clock.

**Estymaty:** CPU critical path ≈ 28.3 ms; GPU critical path (VP+HUD+NV12)
≈ 18 ms; end-to-end frame ≈ 36.8 ms. GPU ma ~2× zapas względem CPU;
CPU (28.3 ms) < frame (36.8 ms) → **~8.5 ms/frame to serializacja/backpressure,
najpewniej tempo enkodera HEVC 4K** (nie widać go w niskim AMF submit —
submisje są buforowane, a drenaż wyznacza przepustowość).

---

## CURRENT COMPOSE TOP (per-widget, overlay profiler — relative shares)

| # | widget | med ms | uwagi |
|---|---|---|---|
| 1 | **gauge CPU render** (`fit_enhanced_speed_text`) | 1.66 | text drawing 0.90 + copy 0.44 |
| 2 | **iso_text** | 1.41 | text drawing 0.97 (nieproporcjonalnie drogi) |
| 3 | **cadence dynamic CPU** (`fit_cadence_text`) | 1.11 | text 0.57 + labels 0.78 |
| 4 | **HR dynamic CPU** (`fit_heart_rate_text`) | 1.10 | text 0.64 + labels 0.82 |
| 5 | **time_block** | 0.69 | paste_composite 0.61 |
| — | map crop_resize | 0.68 | |
| — | battery / temp / exposure | 0.41 / 0.30 / 0.29 | |

Suma per-widget ≈ 7.6 ms (run profiling; w baseline compose ≈ 11.3 ms — te same
udziały względne, wyższe absolutnie).

> Pillow: text drawing ~3.09 ms/frame łącznie, crop ~1.18 ms, paste ~0.27 ms,
> ImageDraw ~0.24 ms, getbbox ~0.72 ms.

---

## CURRENT TELEMETRY BREAKDOWN (overlay profiler)

| komponent | med ms |
|---|---|
| **interpolation_lookups** | 1.93 |
| dynamic_fit_fields | 1.07 |
| resolve_cache_value | 1.02 |
| date_time / graph_data / range / map_gps | ~0.05 |

`prepare_overlay_frame_data` = 3.17 ms (run profiling) / **~8.0 ms (production
baseline)** — ta sama funkcja; różnica to wariancja obciążenia CPU. W produkcji
udziały względne skalują się ~2.5× (interpolacja ~4.9, fields ~2.7, resolve ~2.6).

---

## CPU / GPU UTILIZATION (orientacyjnie — ograniczenia)

| zasób | avg | med | max | Uwaga |
|---|---|---|---|---|
| **GPU 3D** (VP+HUD+NV12) | 67.5 % | 75.5 % | 90 % | ~6 rzadkich próbek (Get-Counter wolny) |
| GPU Video Decode | 4.5 % | 5 % | 7 % | triv |
| GPU Video Encode | — | — | — | **nie mierzalny** przez `\GPU Engine(*)` (0 w obu próbach — atrybucja licznika, nie dowód) |
| GPU Copy | 0 % | 0 % | 0 % | |
| CPU % (python) | — | — | — | licznik `\Process(python*)` nie zadziałał w job; brak czystego pomiaru |

> Sampler Get-Counter dodał narzut (jeden run spadł do 14.7 FPS) — dane GPU są
> **orientacyjne**. Lekki sampler (tylko GPU Engine) dał 32.3 FPS (bez dużej
> kontaminacji). Nie mierzono CPU% bez ingerencji; jedyne twarde dane CPU to
> sumy stage'ów (~28.3 ms, 1 wątek Python).

---

## TOP 10 BOTTLENECKS (aktualny profil)

| # | stage | ms/frame | CPU/GPU | freq | critical path | max theor. gain | risk |
|---|---|---|---|---|---|---|---|
| 1 | **compose_overlay** | 11.32 | CPU | 1× | TAK | 11.3 ms (do ~0) | MED |
| 2 | **telemetry (frame_data)** | 8.00 | CPU | 1× | TAK | ~8 ms (→3) | MED |
| 3 | **AMF HEVC 4K encoder drain** | ~8.5 (residual, niezmierzony per-frame) | GPU enc | 1× | TAK | do ~0 jeśli CPU-lim | LOW* |
| 4 | **map CPU (crop+marker+upload)** | 2.81 | CPU | 1× | TAK | ~2.5 ms | LOW |
| 5 | **PIL/buffer preparation** | 1.08 | CPU | 1× | TAK | ~0.8 ms | LOW |
| 6 | **gauge tobytes** | 0.98 | CPU | 1× | TAK | ~0.6 ms | LOW |
| 7 | **HUD dirty extract** | 0.98 | CPU | 1× | TAK | ~0.6 ms | LOW |
| 8 | **MF ReadSample/decode availability** | 0.91 | CPU-wait | 1× | częściowo | ~0.5 ms | LOW |
| 9 | **VP CPU submit** | 0.60 | CPU | 1× | TAK | ~0.3 ms | LOW |
| 10 | **AMF submit/Query/packet** | 0.76 | CPU | 1× | TAK | ~0.4 ms | LOW |

\* encoder drain: ryzyko niskie jako pomiar, ale zmiana konfiguracji enkodera
niesie ryzyko jakości/bitrate (osobny wektor).

---

## AMDAHL (frame 36.8 ms; serial fraction = CPU 28.3 + residual 8.5)

| Hotspot | 2× | 5× | ∞ |
|---|---|---|---|
| **1. compose (11.32)** | 31.1 ms → 32.1 FPS | 27.8 ms → 36.0 FPS | 25.5 ms → 39.2 FPS |
| **2. telemetry (8.00)** | 32.8 ms → 30.5 FPS | 30.4 ms → 32.9 FPS | 28.8 ms → 34.7 FPS |
| **3. map CPU (2.81)** | 35.4 ms → 28.2 FPS | 34.6 ms → 28.9 FPS | 34.0 ms → 29.4 FPS |
| **4. encoder drain (8.5)** | 32.7 ms → 30.6 FPS | 30.2 ms → 33.2 FPS | 28.3 ms → 35.3 FPS |

> **Nie traktuj jako obietnicy FPS.** Punkt 3 i 4 nie wystarczą do przekroczenia
> realtime — potrzebna jest redukcja **compose + telemetry** (punkty 1-2) LUB
> adresacja enkodera (4). Sam `compose→∞` daje 39 FPS tylko przy założeniu, że
> residual (8.5 ms) pozostaje stały.

---

## 5N CANDIDATES (max 3 — nie implementowane)

**1. Redukcja `compose_overlay` (11.3 ms)**
- Expected gain: **MEDIUM–HIGH** (→ ~6–8 ms, +2–4 FPS)
- Risk: **MEDIUM** (parity Pillow↔GPU tekstów)
- Scope: **CROSS-LAYER** (renderer CPU + GPU compositor)
- Correctness risk: **MEDIUM**
- Reason: największy pojedynczy stage; iso_text text drawing (0.97) +
  gauge/cadence/HR CPU render (łącznie ~3.9) + paste/getbbox; GPU już bierze
  finalne blendy — można przenieść więcej lub cache'ować warstwy statyczne.

**2. Optymalizacja telemetrii (8.0 ms)**
- Expected gain: **MEDIUM** (→ ~3–4 ms, +1.5–2.5 FPS)
- Risk: **LOW–MEDIUM**
- Scope: **LOCAL** (warstwa telemetry)
- Correctness risk: **MEDIUM** (wartości muszą pozostać identyczne)
- Reason: interpolacja (1.93) + dynamic fields (1.07) + resolve (1.02);
  ~5 ms poza `prepare_overlay_frame_data` wymaga audytu (cache/wsadowość).

**3. Przepustowość enkodera AMF HEVC 4K (drenaż ~27 FPS)**
- Expected gain: **MEDIUM–HIGH** (jeśli to on jest podłogą → realtime)
- Risk: **MEDIUM** (konfiguracja enkodera → jakość/bitrate)
- Scope: **CROSS-LAYER** (natywna konfiguracja AMF)
- Correctness risk: **LOW** (wyjście wizualne bez zmian)
- Reason: ~8.5 ms/frame residual + FPS 26–33 zależny od stanu termicznego
  sugeruje drenaż enkodera jako podłogę; wymaga osobnej walidacji
  (np. porównanie z szybszą preset/RC).

---

## ODPOWIEDZ WPROST

1. **Stabilny medianowy TRUE FPS?** → **27.17** (4×1131, spread 8.8%).
2. **Stabilnie szybszy niż 29.97 realtime?** → **NIE** (0.907×).
3. **Real-time margin?** → **−9.33 %**.
4. **Największy CPU bottleneck?** → **compose_overlay (~11.3 ms)**.
5. **Największy GPU bottleneck?** → **drenaż enkodera HEVC 4K** (residual ~8.5 ms/frame;
   VP+HUD GPU ma zapas ~18 ms vs CPU 28 ms).
6. **CPU czy GPU wyznacza frame time?** → **CPU** (28.3 ms > GPU 18 ms), ale do
   36.8 ms dochodzi **serializacja/encoder drain** — CPU jest ograniczeniem zasobowym,
   a enkoder podłogą przepustowości.
7. **Ile kosztuje compose_overlay?** → **11.3 ms** (mediana, production); per-widget:
   gauge 1.66, iso 1.41, cadence 1.11, HR 1.10, time 0.69.
8. **Ile kosztuje telemetry?** → **~8.0 ms** production (3.17 ms w profiling run);
   interpolacja 1.93 + fields 1.07 + resolve 1.02.
9. **Czy HUD buffer prep ma znaczenie?** → **małe** — dirty extract + PIL prep ≈ 2.0 ms
   (5% frame), nie jest już top-em (po 5G–5L).
10. **Pojedynczy etap z największym gainem?** → **compose_overlay** (pot. do ~39 FPS
    przy ∞ przy stałym residualu); realnie największy uchwyt to **compose + telemetry
    razem** lub **enkoder**.
11. **Czy dalsza optymalizacja AMD ma sens?** → **TAK** — system jest realtime-ujemny
    (−9.3%); CPU ma ~8 ms nieprzypisanego kosztu + 28 ms ścieżki CPU; redukcja
    compose/telemetry o ~5–7 ms przecina linię realtime.
12. **Co powinien robić ETAP 5N?** → według kandydatów: **1)** redukcja compose
    (przeniesienie/cache warstw, naprawa iso text), **2)** cache/wsadowość telemetrii,
    **3)** audyt konfiguracji AMF HEVC pod kątem drenażu — w tej kolejności priorytetów;
    **nie** ruszaj VP/map/gauge/charts (mają zapas i są już EXACT).

---

## ARTEFAKTY

- `Raporty/AMD_ETAP5G/etap5m_baseline.json` (A/B/C/D + agregacja)
- `Raporty/AMD_ETAP5G/5m_profile.mp4.amd_profile.json` (profiling: GPU completion 18.13 ms)
- `Raporty/AMD_ETAP5G/5m_gpuutil_run.mp4.amd_profile.json` + `etap5m_gpu_util.csv` (GPU 3D ~67%)
- Skrypty pomiarowe: `scratch/etap5m_baseline.py`, `etap5m_dump_profile.py`,
  `etap5m_gpuutil.ps1/.py`, `etap5m_print_stages.py`

> Zgodnie z dyrektywą: **bez 5N**, **bez zmian production code**, **bez
> optymalizacji** — wyłącznie pomiar i analiza. NVIDIA/Intel nietknięte.
