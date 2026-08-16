# RAPORT AMD — ETAP 5T: asynchroniczny GPU timeline / timestamp profiling

**STATUS: ✅ PASS** — D3D11 timestamp ring (async, **zero per-frame wait**),
observer overhead **−3.08 %**, GPU frame span / cadence / passes / overlap /
korelacja zmierzone. **GPU 3D/VP engine ma zapas (span 21.2 ms, cadence 36.2 FPS)**;
prawdziwym limiterem wall jest **ENCODER (VCN ~30–33 FPS)** + CPU sync (12 ms,
korelacja z AMF outstanding 0.835). Najdroższe GPU passy: **VP 7.6 ms (36 %) +
NORMALIZE 6.6 ms (32 %)**. Bez zmian pool/decoder/shader/AMF; **bez 5U**.

---

## QUERY SYSTEM

| | |
|---|---|
| ring | **64 slotów × 9 query** (8 timestamp + 1 disjoint), persistent |
| queries per frame | 9 issue + 9 read (z opóźnieniem 16 klatek) |
| CreateQuery per frame | **0** (wszystkie persistent) |
| **GetData blocking loops** | **0** (`D3D11_ASYNC_GETDATA_DONOTFLUSH`, 1 sprawdzenie/query) |
| GetData calls / not-ready | 10035 / **0** (run D, 1115 klatek) |
| ready latency | **16 klatek** (READ_DELAY) |
| VRAM/overhead | 576 query objects (system/driver, brak VRAM) |
| **instrumentation overhead** | **−3.08 %** (A 32.96 FPS vs BC 32.68/35.21; <=5 % PASS) |

---

## GPU FRAME (spec 8)

| | ms |
|---|---|
| span med | **21.198** |
| p95 | 35.836 |
| p99 | 37.945 |
| MAX | 71.375 |

---

## GPU CADENCE (spec 9)

| | ms | equiv FPS |
|---|---|---|
| begin interval med | **27.602** | **36.23** |
| begin interval p95 | 36.433 | 27.4 |
| end interval med | 27.692 | 36.11 |

> GPU 3D/VP engine **nie jest nasycony**: span 21.2 ms vs cadence 27.6 ms →
> ~6.4 ms idle/klatkę (silnik 3D pracuje ~77 % czasu).

---

## GPU PASSES (spec 5/7/19; med / p95 / p99 / %span)

| pass | med [ms] | p95 [ms] | p99 [ms] | max [ms] | % span |
|---|---|---|---|---|---|
| **VP (VideoProcessorBlt)** | **7.631** | 19.350 | 25.383 | 64.346 | **36.1** |
| **NORMALIZE (range pass)** | **6.564** | 11.466 | 12.499 | 12.842 | **32.2** |
| MAP (resize+blend) | 2.547 | 4.888 | 8.289 | 9.740 | 12.7 |
| HUD / NV12 compositor | 1.398 | 2.787 | 5.479 | 5.824 | 7.1 |
| CHARTS (GPU_SPLIT blend) | 0.754 | 1.396 | 1.759 | 4.377 | 4.0 |
| GAUGE (GPU blend) | 0.359 | 0.675 | 0.945 | 1.978 | 1.8 |

**TOP GPU: 1. VP (7.6 ms), 2. NORMALIZE (6.6 ms), 3. MAP (2.5 ms).**
Suma wszystkich passów ≈ **19.2 ms**; span 21.2 ms → ~2 ms inne (release/transition).

> VP execution (GPU) to **7.6 ms** — zupełnie inne niż CPU enqueue (0.31 ms).
> NORMALIZE 6.6 ms to realny GPU koszt pełnego 4K NV12 range pass (wysoki jak na
> mały dispatch — kandydat do audytu wydajności shadera w 5U).

---

## OVERLAP (spec 10)

**Inter-frame GPU overlap: NIE (0/1114 = 0.0 %)** — klatki GPU wykonują się
serialnie (frame N+1 zaczyna dopiero po skończeniu N). Żaden czas passów nie
sumuje się ze sobą.

---

## CPU PACING CORRELATION (spec 16)

| korelacja first-call wait ↔ | r |
|---|---|
| GPU previous frame span | **0.587** |
| GPU previous frame END | **0.682** |
| **AMF outstanding** | **0.835** |

> CPU wait (12 ms) **silnie koreluje z AMF outstanding** (0.835) i końcem
> poprzedniej pracy GPU (0.682) — CPU czeka, gdy enkoder trzyma powierzchnie
> (5–6 in-flight), a VP output pool (4) się zapycha.

---

## DECODER (spec 18)

| | |
|---|---|
| texture IDs | **1** (ta sama `0xb5d6de0` przez 1131 klatek) |
| subresources / array slices | **3 (0, 1, 2)** — rotują 0,1,2,0,1,2… |
| actual unique frame surfaces | **1 texture × 3 array slices** (ring dekodera D3D11VA) |
| korelacja z wait | ~0 (5S: corr 0.067) |

> „Unique texture=1” z 5S było mylące: dekoder używa **jednej tekstury z 3 array
> slices** (standardowy ring D3D11VA). Nie zmieniano schedulingu.

---

## WORKLOAD-OFF (spec 20–26; diagnostyka, 1131 klatek)

| test | GPU span Δ [ms] | wall FPS Δ |
|---|---|---|
| FULL (baseline) | — (span 27.14, cadence 27.43) | 32.31 |
| MAP OFF (CPU_REFERENCE) | **−15.70** | **−7.09** (confounded: mapa przeniesiona na CPU — CPU przeładowany) |
| GAUGE OFF | −1.75 | **+1.42** |
| CHARTS OFF | −0.13 | +0.08 |
| HUD OFF | −1.95 | **+1.41** |

> gauge/HUD off dają tylko ~+1.4 FPS (w szumie termicznym ±2 FPS); charts ~0.
> **MAP OFF jest zafałszowane** — CPU_REFERENCE przenosi mapę do Pillow (CPU),
> przez co wall spada mimo −15.7 ms GPU span. Wniosek: **redukcja GPU rendererów
> NIE podnosi wall** — GPU 3D nie jest limiterem.

---

## CORRECTNESS (spec 27/28)

| | |
|---|---|
| framemd5 GPU-ts OFF vs ON (31 klatek) | **31/31 identyczne** |
| 1131/1131 | ✅ (wszystkie runy A/B/C/D + workload-off) |
| drops | 0 |
| production default | **GPU-ts OFF** (AMD_GPU_TIMESTAMP_PROFILE domyślnie wyłączony) |

---

## CLASSIFICATION (spec 29)

| | YES/NO |
|---|---|
| VP GPU-bound | **YES** (7.6 ms — najdroższy pass; ale NIE limiter wall) |
| NORMALIZE GPU-bound | **YES** (6.6 ms — 2. najdroższy) |
| HUD | NO (1.4 ms; off → +1.4 FPS szum) |
| MAP | NO (2.5 ms; test zafałszowany CPU-shift) |
| CHARTS | NO (0.75 ms) |
| GAUGE | NO (0.36 ms) |
| **ENCODE CADENCE** | **YES — limiter wall (~30–33 FPS; 5O cadence 28.3–31)** |
| GENERAL GPU SATURATION | **NO** (span 21.2 ms, cadence 36.2 FPS → silnik 3D ma zapas) |
| **MIXED** | **YES** (encoder-limited + CPU sync 12 ms przy pełnym VP output pool) |

**Mechanizm (pełny obraz):** GPU 3D/VP engine robi klatkę w **21.2 ms** i ma
cadence **36 FPS** (zapas ~6 ms/klatkę). **Enkoder VCN (~30–33 FPS)** jest
wolniejszy → AMF outstanding rośnie (5–6) → VP output pool (4) się zapycha →
driver throttle CPU przy pierwszym callu D3D11 (12 ms, korelacja 0.835) → wall
~33 FPS. GPU passy (VP 7.6 + normalize 6.6) są najdroższe, ale NIE ograniczają
wall.

---

## 5U CANDIDATES (spec 30; max 3, na podstawie timestampów)

1. **Zbadać overlap/cadence enkodera (VCN) — 5U główny cel.**
   - change: pipeline jest **encoder-limited** (GPU 3D 36 FPS, encode ~31–33).
     5U: feed enkodera / VP output pool tak, by enkoder był nasycony bez czekania
     CPU; ewentualnie dekodowanie submit/query od pracy 3D.
   - expected gain: **+2–5 FPS** (z ~33 do ~35–36, zbliżenie do cadence 3D).
   - risk: średni (AMF/pool); correctness risk: średni (jawny lifecycle).
   - memory: +surfaces (jeśli pool głębszy).
2. **Audyt wydajności NORMALIZE (range pass 6.6 ms, 32 % GPU span).**
   - change: 4K NV12 range pass kosztuje 6.6 ms GPU — podejrzanie dużo; audyt
     shadera / dispatch fusion z VP lub HUD pass.
   - expected gain: **GPU span −5–6 ms** (NIE wall — GPU ma zapas, ale zmniejsza
     zajętość 3D i wydłuża czas do nasycenia).
   - risk: niski; correctness risk: średni (pixel-exact gate).
   - memory: ~0.
3. **Zweryfikować czy VP 7.6 ms to realny koszt sprzętowy czy artifact pomiaru.**
   - change: VideoProcessorBlt GPU execution 7.6 ms przy 4K P010→NV12 + HUD
     overlay; sprawdzić czy da się zmniejszyć (np. mniejsze HUD, rzadszy overlay).
   - expected gain: GPU span −3–7 ms (NIE wall bezpośrednio).
   - risk: niski; correctness risk: średni.
   - memory: ~0.

> **Nie ma uzasadnienia dla większego pool/ring ze strony GPU 3D** (nie nasycony).
> Pool 4 ma znaczenie dla FEED enkodera (outstanding 5–6) — to część 5U #1.

---

## ODPOWIEDZ WPROST

1. **Ile rzeczywiście trwa praca GPU jednej klatki?** → **21.2 ms med** (span
   GPU_FRAME_BEGIN→END; p95 35.8, p99 37.9, max 71.4).
2. **Jaka jest rzeczywista GPU frame cadence?** → **27.6 ms = 36.2 FPS** (silnik 3D).
3. **Który GPU pass kosztuje najwięcej?** → **VP (VideoProcessorBlt) 7.63 ms (36 %)**.
4. **Ile kosztuje VP?** → **7.63 ms med, p95 19.35 ms** (GPU execution — nie CPU enqueue 0.31 ms).
5. **Ile kosztuje mapa?** → **2.55 ms med** (resize+blend).
6. **Ile kosztują charty?** → **0.75 ms med** (GPU_SPLIT blend).
7. **Ile kosztuje gauge?** → **0.36 ms med**.
8. **Ile kosztuje HUD/NV12?** → **1.40 ms med**.
9. **Czy klatki GPU nakładają się?** → **NIE (0 %)** — wykonują się serialnie.
10. **Czy CPU wait koreluje z końcem poprzedniej pracy GPU?** → **TAK** —
    prev GPU END r=0.682, prev span r=0.587, **AMF outstanding r=0.835**.
11. **Czy decoder naprawdę używa jednej surface?** → **NIE** — 1 tekstura ×
    **3 array slices** (rotacja 0,1,2), standardowy ring D3D11VA.
12. **Co daje największy marginalny FPS gain po wyłączeniu?** → **nic realnego**
    (gauge/HUD off +1.4 FPS = szum; map off gorzej przez CPU shift) — GPU 3D
    NIE jest limiterem wall.
13. **Czy większy ring/pool ma uzasadnienie?** → **Nie dla GPU 3D** (ma zapas);
    **tak dla feed enkodera** (VP output pool 4 → encoder outstanding 5–6) — to
    część 5U #1.
14. **Co dokładnie powinien robić ETAP 5U?** → Zbadać **overlap/cadence enkodera
    (VCN)** i feed VP-output-pool, by enkoder był nasycony (cel: zbliżenie wall do
    cadence 3D ~36 FPS); plus audyt NORMALIZE (6.6 ms) i VP (7.6 ms) jako
    redukcja GPU span (drugorzędne dla wall).

---

## KRYTERIA PASS (spec)

| # | kryterium | wynik |
|---|---|---|
| 1 | brak blocking query reads | ✅ (GetData 10035, not-ready 0, 0 spin) |
| 2 | observer overhead <=5 % | ✅ (−3.08 %) |
| 3 | GPU frame span zmierzony | ✅ (21.2 ms med) |
| 4 | GPU cadence zmierzony | ✅ (27.6 ms = 36.2 FPS) |
| 5 | najważniejsze GPU passes rozbite | ✅ (VP/normalize/map/HUD/charts/gauge) |
| 6 | TOP GPU hotspot wskazany | ✅ (VP 7.6 + NORMALIZE 6.6) |
| 7 | korelacja CPU wait ↔ GPU timeline | ✅ (AMF 0.835, prev-end 0.682) |
| 8 | diagnostic workload-off dla TOP kandydatów | ✅ (MAP/GAUGE/CHARTS/HUD OFF) |
| 9 | final output bez regresji | ✅ (framemd5 31/31; production default OFF) |
| 10 | 1131/1131 | ✅ |
| 11 | drops=0 | ✅ |

---

## PLIKI

- Native: `src/d3d11_vp_pipeline.{h,cpp}` (GPU timestamp ring, GPUFrameTimeline,
  `AMD_GPU_HUD_OFF` diag), `src/telem_amd_native.cpp` (env `AMD_GPU_TIMESTAMP_PROFILE`,
  gpu_timeline.csv).
- Harnessy: `scratch/etap5t_runs.py`, `scratch/etap5t_analyze.py`,
  `scratch/etap5t_workload_off.py`.
- JSON/CSV: `Raporty/AMD_ETAP5G/etap5t_{observer,analysis,workload_off}.json`,
  `l5t_{A,B,C,D,full,map_off,gauge_off,charts_off,hud_off}.mp4.gpu_timeline.csv`.
