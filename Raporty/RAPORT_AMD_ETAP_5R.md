# RAPORT AMD — ETAP 5R: native process_frame internal pacing audit

**STATUS: ✅ PASS** — build DLL deterministyczny; ProcessFrame rozbity na exclusive
substage'y (QPC); **99.2–99.3 % wall rozliczone**; **blocking point wskazany
liczbowo**: `VideoProcessorSetStream*` (region setup VP) = **~12.9 ms mediana /
24.4 ms p95 / 27.1 ms p99 / 42 ms max** — implicit D3D11 driver sync (GPU/enkoder
zajęty). Overhead native <=5 % (−2.2 %). Bez zmian pipeline/AMF/pool; **bez 5S**.

---

## BUILD

| | |
|---|---|
| toolchain | **MinGW-W64 g++ 16.2.0** (C:\tools\mingw64) + CMake 4.4 + Ninja (istniejący) |
| clean configure | **YES** (build-etap5r) |
| clean build | **YES** (target `telem_amd_native`) |
| determinizm | **YES** — clean-first rebuild → identyczny SHA (`9A9C90B5F6...`) |
| DLL | `native/d3d11_amf_pipeline/bin/telem_amd_native.dll`, ABI 8 |
| build ID | `telem-amd-native/1.0.0+db7608a5a715.src9e7a1b15c4b1` (git `db7608a5`) |
| smoke | 31/31 klatek, **framemd5 ≡ golden** (brak regresji obrazu) |

> Uwaga: `source_hash` w build ID pochodzi z initial configure (CMake nie
> re-generuje go przy zmianie źródeł bez re-configure); sam build jest
> deterministyczny (SHA `20B0E567...` powtarzalny `--clean-first`).

> **Blokada g++ (error 4551) już NIE obowiązuje** — `g++.exe --version` exit 0.
> Jedyny błąd builda: **niezacommitowany kod 5O BYPASS** (`goto amf_bypassed`
> przeskakujący inicjalizacje) — naprawiony **semantics-preserving** (owinięcie
> bloku submit/query w `{}`; ścieżka domyślna bez zmian; autoryzacja użytkownika).
> Drugi błąd: stary POC `d3d11_etap2c_poc` (nie-DLL, stale `CreateHUDTexture`) —
> pominięty (budujemy tylko target DLL).

## GOLDEN BEFORE

- Golden DLL zbackupowana: `telem_amd_native.dll.golden-5R` (SHA256 `22966C53...`, 2950557 B).
- Golden 31-frame smoke: `l5r_smoke31.mp4` (REFERENCE) — framemd5 identyczny z golden DLL.
- Instrumentacja (włączona) nie zmienia obrazu: **framemd5 accounting-ON ≡ accounting-OFF** (31/31).

---

## CONTROL (spec 17/18)

| Run | native FA | Python 5P | wall [s] | TRUE FPS | csv | valid |
|---|---|---|---|---|---|---|
| **A** | OFF | OFF | 34.68 | 34.29 | — | ✅ |
| **B** | ON | ON | 37.02 | 32.19 | 1131 | ✅ |
| **C** | ON | ON | 37.46 | 31.79 | 1131 | ✅ |
| **A2** | OFF | OFF | 39.06 | 30.31 | — | ✅ |
| **B2** | ON | OFF | 38.21 | 31.04 | 1131 | ✅ |

**Overhead:**
- native-only (B2−A2)/A2 = **−2.18 %** (szum termiczny; **<=5 % → PASS**).
- native + Python 5P (BC−A)/A = 7.36 % w tej sesji (3.49 % w poprzedniej) —
  **zdominowane wariancją termiczną** (A2 30.31 vs A 34.29 w sąsiednich runach).

---

## PROCESS_FRAME (spec 20/21)

| | B | C |
|---|---|---|
| Python wall med [ms] | 13.336 | 14.057 |
| Native wall med [ms] | 13.316 | 14.038 |
| **cross-check delta [ms]** | **0.020** | **0.019** |

> **Cross-check <0.2 ms ✅** — Python `process_frame` ≡ suma native substage'ów.

---

## NATIVE TOP (exclusive; B: med / p95 / p99 / max; corr z pf_total)

| # | substage | med [ms] | p95 [ms] | p99 [ms] | max [ms] | corr |
|---|---|---|---|---|---|---|
| 1 | **vp_setup (VP setup: CreateView+SetStream*)** | **11.74–12.91** | **24.4** | **27.1** | **42.1** | **0.985–0.992** |
| 2 | vp_total (cały VP ProcessFrame) | 13.72 | 25.05 | 26.88 | 35.9 | 0.996 |
| 3 | vp_submit_window (Blt→HUD enqueue) | 0.73–0.82 | 1.35 | 2.5 | 16.6 | 0.14–0.17 |
| 4 | amf_submit_input | 0.33–0.37 | 0.66 | 1.4 | 11.7–20.1 | 0.03–0.07 |
| 5 | vp_blt (VideoProcessorBlt) | 0.29 | 0.48 | 0.98 | 4.7 | 0.07–0.25 |
| 6 | vp_map_blend | 0.17–0.20 | 0.36 | 0.74 | 3.5 | 0.07–0.15 |
| 7 | vp_chart_blend | 0.17–0.19 | 0.32 | 0.73 | 6.1 | 0.08–0.10 |
| 8 | amf_query (QueryOutput) | 0.12–0.13 | 0.25 | 0.44 | 1.1 | −0.21–0.17 |
| 9 | vp_gauge_blend | 0.09–0.12 | 0.22 | 0.42 | 2.1 | 0.04–0.12 |
| 10 | amf_packet_write | 0.11–0.12 | 0.29 | 0.62 | 4.7 | −0.37–0.20 |
| 11 | surf_acquire | 0.041 | 0.11 | 0.19 | 0.43 | −0.16–0.28 |
| 12 | amf_create_surface | 0.018–0.020 | 0.03 | 0.05 | 0.19 | 0.03–0.07 |
| 13 | vp_range_pass (Normalize) | 0.012 | 0.026 | 0.04 | 0.12 | 0.05–0.07 |
| 14 | vp_release_view | 0.013 | 0.022 | 0.04 | 0.06 | 0.04–0.09 |
| 15 | vp_hud_compute (NV12 comp.) | 0.005 | 0.011 | 0.02 | 0.08 | 0.10–0.18 |
| 16 | vp_create_view | 0.002 | 0.008 | 0.02 | 0.11 | −0.12–0.20 |

**Accounted: 99.2–99.3 %** (mediana sumy exclusive / process_frame_total); residual vp
`vp_unacct_med = 0.0015 ms`. **PASS (kryterium 4: >95 %).**

---

## VP

| | med [ms] | p95 [ms] |
|---|---|---|
| **setup (entry→Blt; CreateView + SetStream\*)** | **11.74–12.91** | **24.4** |
| Blt (VideoProcessorBlt) | 0.29 | 0.48 |
| range pass (NormalizeD3D11VARangeNV12) | 0.012 | 0.026 |
| release view | 0.013 | 0.022 |

> W produkcji istnieje **jeden** range pass (Normalize). „Pass 2” nie występuje w
> ścieżce produkcyjnej (HUD range jest częścią NV12 compositora, `hud_compute`).

---

## GPU COMPUTE

| | med [ms] |
|---|---|
| HUD / NV12 compositor (`ComposeHUDDirectNV12`) | 0.005 |
| charts (`BlendCharts`) | 0.17–0.19 |
| gauge (`BlendGauge`) | 0.09–0.12 |
| map resize+blend (`ResampleAndBlendMap`) | 0.17–0.20 |

> Wszystkie dispatche **krótkie (async enqueue)** — żaden nie blokuje.

---

## RESOURCE POOL

| | |
|---|---|
| pool size (VP output NV12) | **4** (round-robin) |
| surfaces in flight | VP 4 + AMF outstanding **5–6** |
| reuse distance | 4 klatki (wrap co 4) |
| wait | **implicit sync w VP setup** (NIE per-slot: submity 0.32–0.38 ms równo na slotach 0–3) |

---

## AMF

| | med [ms] |
|---|---|
| CreateSurfaceFromDX11Native | 0.018–0.020 |
| SubmitInput | 0.33–0.37 (max 20.1) |
| QueryOutput | 0.12–0.13 |
| packet write | 0.11–0.12 |
| **outstanding** | **5–6** (med 5–6, max 6) |
| INPUT_FULL / retries | **0 / 0** (jak 5O) |

> SubmitInput jest szybki (0.36 ms), **nigdy** nie zwrócił INPUT_FULL w pełnych
> runach. AMF nie jest bezpośrednim blokerem — ale **trzyma 5–6 powierzchni
> in-flight**, co utrzymuje GPU zajęte.

---

## LONG FRAMES

- **Dominant cause: `vp_setup`** (implicit sync) — TOP50 najdłuższych ma w 50/50
  `vp_total` zdominowany przez `vp_setup` (który jest ~92 % vp_total).
- p95 ≈ **26 ms**, p99 ≈ **28 ms**, max ≈ **36–44 ms** (frames 766, 107, 795, 917).
- **Korelacja: vp_setup corr 0.985–0.992 z process_frame_total**; wszystkie inne
  substage corr <0.25.
- `submit_result` w TOP50 = **0 (OK)**, AMF outstanding = 5–6 — spiki NIE z AMF submit.

---

## CROSS-CHECK / CORRECTNESS

- Python vs native: delta **0.020 / 0.019 ms** (<0.2 ms ✅).
- 1131/1131, drops=0, wszystkie liczniki GPU (cadence/hr/map/gauge) = 1131.
- **framemd5 accounting-ON ≡ OFF** (31/31 smoke + 5/5 spot full) — **instrumentacja
  nie zmienia obrazu** (spec 25).

---

## CLASSIFICATION (spec 26)

| klasa | YES/NO |
|---|---|
| **D3D11 DRIVER PACING** | **YES** (blokada ~12.9 ms w VP setup = sync z zajętym GPU) |
| RESOURCE REUSE | **PARTIAL** (VP pool 4 + AMF 5–6 → GPU zajęty; blok NIE per-slot) |
| VP | **YES** (implicit sync w `VideoProcessorSetStream*`) |
| AMF LIFETIME | **YES** (enkoder trzyma 5–6 powierzchni) |
| AMF SUBMIT | NO |
| QUERYOUTPUT | NO |
| COMPUTE | NO |
| **MIXED** | **YES** (driver pacing + VP sync + AMF surface lifetime) |

**Mechanizm (spójny z 5P/5Q):** frontend CPU (~30–35 FPS) jest szybszy niż
przepustowość GPU (VP + AMF HEVC encode ~30 FPS). Gdy CPU dociera do następnego
`VideoProcessorSetStream*`, driver D3D11 **synchronizuje** (czeka, aż GPU/enkoder
nadąży) — to jest „elastyczne pacing process_frame”. Redukcja compose (5Q)
sprawia, że CPU szybciej dochodzi do tego sync → sync rośnie (absorpcja 280 %).

---

## 5S CANDIDATES (maks. 3; NIE implementowane)

1. **Zwiększyć przepustowość GPU/enkodera (jedyne realne źródło FPS).**
   - change: pipeline jest GPU-throughput-bound; lewar = szybciej VP/encode (np.
     mniej GPU dispatche'ów HUD/chart/gauge/map na klatkę, mniejszy HUD).
   - expected gain: +1–3 FPS (z ~30 do ~33 w stanie gorącym; chłodny już 33–34).
   - risk: niski (bez zmian AMF jakości); correctness risk: niski (zmiany
     compose/upload, walidacja pixel-exact).
   - memory: ~0.
2. **Głębszy pipeline in-flight (więcej VP output textures + decoupled submit/query).**
   - change: zwiększyć `POOL_SIZE` (4→6–8) + jawny lifecycle, by CPU nie blokował
     na VP setup, gdy GPU pracuje.
   - expected gain: **niski** (wall i tak GPU-bound; sync tylko się przesunie);
     wygładza throughput.
   - risk: średni (więcej VRAM, dłuższa latencja, hazard SRV/UAV); correctness
     risk: średni (readback/cleanup).
   - memory: +2–4 × 15 MB (NV12 4K) = +30–60 MB VRAM.
3. **Zredukować per-frame VP setup (cache input view + tylko zmieniony stan SetStream).**
   - change: reuse `CreateVideoProcessorInputView` (0.002 ms dziś) i unikać
     ponownego ustawiania niezmienionych rectów/formatów, jeśli driver syncuje na
     state-change.
   - expected gain: niepewny (zależny od drivera; może ściąć część 12.9 ms).
   - risk: niski; correctness risk: niski (pixel-exact gate).
   - memory: ~0.

> **Kluczowy wniosek:** pacing `process_frame` NIE jest limiterem FPS — jest
> **throttle'em CPU→GPU**. Wall jest ograniczony przepustowością GPU (VP+encode).
> Naprawa synca nie podniesie FPS ponad sufit GPU; 5S powinien celować w sam GPU.

---

## ODPOWIEDZ WPROST

1. **Która dokładna operacja blokuje process_frame?** → **`VideoProcessorSetStream*`
   (region setup VP, przed `VideoProcessorBlt`)** — implicit D3D11 driver sync.
2. **Ile wynosi jej mediana?** → **~12.9 ms** (11.74–12.91 w zależności od runu).
3. **Ile wynosi P95/P99?** → **P95 ~24.4 ms, P99 ~27.1 ms** (max 42.1 ms).
4. **Czy spiki 30–35 ms pochodzą z niej?** → **TAK** — TOP50 long frames 50/50
   zdominowane przez vp_total (92 % = vp_setup); corr 0.99.
5. **Czy problemem jest reuse surface?** → **Częściowo** — VP pool 4 + AMF trzyma
   5–6 powierzchni → GPU zajęty; ale blok NIE jest per-slot (submity równe na slotach).
6. **Czy AMF trzyma surface zbyt długo?** → **TAK, ale nie bezpośrednio blokuje**
   — outstanding 5–6, jednak SubmitInput szybki (0.36 ms), INPUT_FULL=0; to
   utrzymuje GPU zajęte, przez co VP setup czeka.
7. **Czy VP powoduje implicit sync?** → **TAK** — blokada siedzi w regionie setup VP.
8. **Czy compute shader powoduje wait?** → **NIE** — wszystkie dispatche (HUD/chart/
   gauge/map) ≤0.2 ms, corr <0.2.
9. **Ile klatek/resources jest jednocześnie in-flight?** → **~5–6** (VP pool 4 +
   AMF outstanding 5–6).
10. **Czy zwiększenie pool/ringu ma szansę pomóc?** → **Ograniczona** — wall jest
    GPU-bound; większy pool tylko przesunie sync. Realny lewar to przepustowość GPU.
11. **Jaki jest najbardziej prawdopodobny 5S?** → **Zwiększenie przepustowości GPU**
    (mniej pracy GPU per klatka) + ew. głębszy pipeline; nie sam sync.
12. **Jaki jest maksymalny realistyczny FPS po naprawie?** → **~33–34 FPS** (chłodny
    GPU już to osiąga; gorący ~27–30). **Nie przekracza realtime 29.97 stabilnie**
    — pipeline jest blisko sufitu GPU/enkodera; sync nie jest limiterem FPS.

---

## KRYTERIA PASS (spec)

| # | kryterium | wynik |
|---|---|---|
| 1 | build DLL działa | ✅ (deterministyczny, ABI 8) |
| 2 | native instrumentation overhead <=5 % | ✅ (−2.18 %) |
| 3 | ProcessFrame rozbity na exclusive substages | ✅ (16 substage'ów) |
| 4 | >95 % wall rozliczone | ✅ (99.2–99.3 %) |
| 5 | blocking point wskazany liczbowo | ✅ (vp_setup 12.9 ms, corr 0.99) |
| 6 | p95/p99 wyjaśnione | ✅ (24.4 / 27.1 ms — VP sync) |
| 7 | brak zmian pipeline semantics | ✅ (tylko timery; framemd5 identyczny) |
| 8 | 1131/1131 | ✅ |
| 9 | drops=0 | ✅ |
| 10 | final output bez regresji | ✅ (framemd5 ≡ golden) |

---

## PLIKI

- Native: `src/telem_amd_native.cpp` (trace+CSV, env `AMD_NATIVE_FRAME_ACCOUNTING`),
  `src/d3d11_vp_pipeline.{h,cpp}` (substage timery), `src/d3d11_amf_encoder.{h,cpp}`.
- Harnessy: `scratch/etap5r_runs.py`, `scratch/etap5r_analyze.py`, `scratch/etap5r_overhead.py`.
- JSON/CSV: `Raporty/AMD_ETAP5G/etap5r_control.json`, `etap5r_analysis.json`,
  `etap5r_overhead_native.json`, `l5r_{A,B,C,D,A2,B2}.mp4.frame_accounting.csv`.
- Golden: `bin/telem_amd_native.dll.golden-5R`.
