# RAPORT AMD — ETAP 5S: lokalizacja VideoProcessorSetStream* sync + test STATIC_CACHE

**STATUS: ✅ PASS-SYNC-MIGRATION** — dokładny call zlokalizowany
(`VideoProcessorSetStreamFrameFormat`), ale **udowodniono, że to FIRST-D3D11-CALL
PACING**, nie koszt settera. STATIC_CACHE jest **pixel-exact** (framemd5 1131/1131),
redukuje SetStream 12.97→0.00 ms, **ALE wait migruje 1:1 do `VideoProcessorBlt`
(0.31→13.33 ms)** → **ZERO zysku** (process_frame 14.35→14.41 ms, FPS +0.06).
Zgodnie z warunkiem 5T: **5T NIE powinien utrwalać cache'owania setterów**.

---

## REFERENCE SETSTREAM (per-setter, exclusive QPC; 1131 klatek)

| # | setter | med [ms] | p95 [ms] | p99 [ms] | max [ms] | corr |
|---|---|---|---|---|---|---|
| 1 | **VideoProcessorSetStreamFrameFormat** | **12.953** | **23.799** | **25.137** | **28.621** | **0.990** |
| 2 | VideoProcessorSetStreamSourceRect | 0.011 | 0.021 | 0.040 | 0.059 | 0.176 |
| 3 | VideoProcessorSetStreamDestRect | 0.002 | 0.003 | 0.006 | 0.012 | 0.098 |
| | **TOTAL settery** | **12.966** | **23.811** | — | **28.633** | **0.990** |

> `CreateVideoProcessorInputView` (per-frame) = 0.002 ms — nie optymalizowany (jak spec 6).
> Blt = 0.310 ms (async enqueue). Wait siedzi w **pierwszym** setterze klatki.

---

## FIRST CALL TEST (spec 3/4)

| tryb | pierwszy call VP | wait [ms] | drugi call | wait [ms] |
|---|---|---|---|---|
| REFERENCE | **SetStreamFrameFormat** | **12.95** | SetStreamSourceRect | 0.011 |
| **REORDER** | **SetStreamSourceRect** | **11.85** | SetStreamFrameFormat | 0.011 |
| **STATIC_CACHE** | **VideoProcessorBlt** | **13.33** | — | 0 |

- **wait podąża za pierwszym callem: TAK** (REORDER: 12 ms przeszło na src_rect).
- **wait podąża za konkretnym setterem: NIE** (żaden setter nie jest samo w sobie drogi).

---

## STATE CLASSIFICATION (spec 5)

| param | klasa | wartości / 1131 klatek |
|---|---|---|
| SetStreamFrameFormat | **STATIC PER PIPELINE** | PROGRESSIVE × 1131 (state_sig = 1) |
| SetStreamSourceRect | **STATIC PER PIPELINE** | fullRect {0,0,w,h} × 1131 |
| SetStreamDestRect | **STATIC PER PIPELINE** | fullRect {0,0,w,h} × 1131 |
| SetStreamColorSpace / SetOutputColorSpace | STATIC (once w SetupVideoProcessor) | — |

> **state_sig distinct = 1** — stan VP identyczny we wszystkich 1131 klatkach.
> Wszystkie 3 per-frame settery są udowodnione jako niezmienne.

---

## DECODER INPUT (spec 8 — nowa bramka)

| | |
|---|---|
| unique surfaces | **1** (ta sama tekstura decoder co klatkę, `0xb5d6de0`) |
| reuse distance | 1.0 (każda klatka) |
| corr set_stream ↔ reuse distance | **0.067** (brak) |
| corr set_stream ↔ reuse w oknie 4 | −0.127 (brak) |

> **Hipoteza decoder-input-reuse NIE potwierdzona** — wait nie koreluje z decoder
> surface.

---

## VP OUTPUT (spec 7)

| | |
|---|---|
| pool | **4** (frozen, spec 19) |
| setstream by slot (med) | slot0 12.79 · slot1 13.37 · slot2 12.71 · slot3 12.96 |
| **slot correlation** | **BRAK** (równomiernie na 4 slotach) |

---

## AMF LIFETIME (spec 9 — nie zgaduj)

| | |
|---|---|
| exact VP-texture retention proven | **NO** (moment release AMF nieobserwowalny przez dostępne API) |
| evidence | `vp_out_tex_unique=4` (4 tekstury VP), reuse gap 4.0; **AMF outstanding 5–6** utrzymuje GPU zajęty |
| wniosek | AMF trzyma powierzchnie in-flight, ale **nie ma bezpośredniego dowodu**, że konkretna VP output texture jest trzymana — **UNKNOWN** jako dowód per-texture |

---

## STATIC_CACHE (spec 10/11/13)

| | REFERENCE | STATIC_CACHE | saving |
|---|---|---|---|
| SetStream total med [ms] | 12.97 | **0.000** | −12.97 (−100 %) |
| setters_skipped | 0 / 1131 | **1130 / 1131** | — |
| **Blt med [ms]** | 0.310 | **13.333** | **+13.02 (migracja)** |
| process_frame total med [ms] | 14.349 | 14.408 | **+0.06 (brak zysku)** |

> **SYNC MIGRATION: TAK — 1:1.** SetStream 12.97→0.00, ale Blt 0.31→13.33.
> Całkowity wait ≈ 13.3 ms w obu trybach. **NO REAL GAIN** (kryterium spec 13).

---

## PROCESS_FRAME (spec 14/18)

| | REF (E) | CACHE (F) |
|---|---|---|
| pf_total med [ms] | 14.349 | 14.408 |
| p95 [ms] | 25.264 | 25.527 |
| p99 [ms] | 26.684 | 27.470 |
| max [ms] | 30.054 | 52.278 |

---

## LONG FRAMES (spec 15)

| tryb | dominujący call (TOP50) | frame (najdłuższy) | decoder | slot | AMF out |
|---|---|---|---|---|---|
| REFERENCE | **vp_setter_fmt** (50/50) | 596 / 961 / 268 | `0xb5d6de0` | 0–3 | 5 |
| STATIC_CACHE | **vp_blt / submit_window** (50/50) | 11 / 804 / 23 | `0x27853c60` | 0–3 | 6 |

> p95/p99 **przesunęło się z SetStream do Blt** (migracja), wartość ~25–27 ms
> pozostała ta sama.

---

## PRODUCTION A/B/C/D (spec 17, accounting OFF)

| Run | tryb | TRUE FPS | wall [s] |
|---|---|---|---|
| A | REFERENCE | 32.57 | 36.39 |
| B | STATIC_CACHE | 31.93 | 37.14 |
| C | REFERENCE | 32.50 | 36.77 |
| D | STATIC_CACHE | 33.26 | 35.81 |
| **median REFERENCE** | | **32.534** | **36.58** |
| **median STATIC_CACHE** | | **32.596** | **36.48** |
| **gain** | | **+0.062 FPS (0.2 %)** | **−0.10 s (0.3 %, szum)** |

> **Brak realnego zysku wall-clock** — potwierdza migrację sync na poziomie produkcji.

---

## CORRECTNESS (spec 16)

| | |
|---|---|
| framemd5 REF vs STATIC_CACHE (pełne 1131) | **1131/1131 identyczne** |
| 1131/1131 | ✅ |
| drops | 0 |
| cadence/hr/map/gauge GPU | 1131 / 1131 / 1131 / 1131 (wszystkie runy) |

> Skip setterów **nie zmienia obrazu** (driver utrzymuje stan VP między Blt).

---

## CLASSIFICATION (spec 22)

| klasa | YES/NO |
|---|---|
| SPECIFIC SETTER | **NO** (REORDER: wait podąża za pierwszym callem) |
| **FIRST CALL PACING** | **YES** |
| DECODER INPUT | **NO** (unique=1, corr ~0) |
| VP OUTPUT REUSE | **NO** (równomiernie na slotach) |
| AMF LIFETIME | **UNKNOWN** (brak bezpośredniego dowodu per-texture; outstanding 5–6) |
| **GENERAL DRIVER THROTTLE** | **YES** (~12 ms = throttle przy zajętym GPU, w pierwszym callu VP) |
| MIXED | **YES** (general throttle + GPU/AMF load) |

**Mechanizm:** GPU (VP + AMF HEVC encode ~30 fps) jest wolniejszy niż frontend CPU.
CPU dociera do pierwszego D3D11 VP calla klatki i driver synchronizuje (czeka, aż
GPU/enkoder nadąży). To jest ta sama „elastyczna paczka”, co w 5P/5Q/5R — teraz
z lokalizacją: **pierwszy VP call klatki, niezależnie od jego typu**.

---

## WARUNEK 5T (spec 23)

STATIC_CACHE: redukuje SetStream (−100 %) **ALE** migruje wait do Blt (1:1)
i **nie obniża frame_total/wall** → **5T NIE powinien cache'ować setterów.**
Kandydaci 5T (kolejność wg danych):
1. **decoder/input surface scheduling** (unique=1 → brak buforowania dekodera),
2. **głębszy pipeline/ring** (POOL_SIZE 6–8 + jawny lifecycle) — możliwe wygładzenie,
3. **redukcja rzeczywistego GPU workload** (GPU jest sufitową przepustowością).

---

## ODPOWIEDZ WPROST

1. **Który dokładnie VideoProcessorSetStream\* blokuje?** → W REFERENCE:
   **VideoProcessorSetStreamFrameFormat** (pierwszy call klatki, 12.95 ms).
2. **Czy blok wynika z funkcji settera, czy z bycia pierwszym callem?** →
   **Z bycia pierwszym callem D3D11** (REORDER: 12 ms przeszło na src_rect;
   STATIC_CACHE: na Blt). Konkretny setter nie jest samo w sobie drogi.
3. **Czy parametry zmieniają się między klatkami?** → **NIE** (state_sig distinct=1).
4. **Czy można bezpiecznie ustawić je raz?** → **TAK** (STATIC_CACHE pixel-exact,
   framemd5 1131/1131 identyczny).
5. **Czy po pominięciu setterów wait migruje do Blt?** → **TAK — 1:1**
   (blt 0.31→13.33 ms).
6. **Czy wait koreluje z decoder input reuse?** → **NIE** (unique=1, corr ~0).
7. **Czy wait koreluje z VP output pool slot?** → **NIE** (równomiernie na 4 slotach).
8. **Czy mamy dowód, że AMF trzyma konkretną VP output texture?** → **NIE/UNKNOWN**
   (release nieobserwowalny; tylko pośrednie: outstanding 5–6, reuse gap 4).
9. **Ile naprawdę spadł ProcessFrame?** → **0** (14.35→14.41 ms, +0.06 ms).
10. **Ile naprawdę spadł wall?** → **0** (36.58→36.48 s, −0.3 % szum; FPS +0.06).
11. **Czy zwiększanie pool size nadal ma sens?** → **Możliwe, ale NIE udowodnione
    w 5S** — wait to general throttle, nie problem pool size; do testu w 5T.
12. **Co dokładnie powinien robić ETAP 5T?** → **NIE cache'ować setterów**.
    Zbadać: (a) dekoder surface scheduling (unique=1), (b) głębszy pipeline/ring
    z jawnym lifecycle, (c) redukcję GPU workload (GPU = sufit).

---

## KRYTERIA PASS (spec)

| # | kryterium | wynik |
|---|---|---|
| 1 | każdy SetStream zmierzony osobno | ✅ (fmt/src/dst + corr) |
| 2 | dominujący exact call wskazany | ✅ (SetStreamFrameFormat w REF) |
| 3 | first-call pacing sprawdzone | ✅ (REORDER + STATIC_CACHE) |
| 4 | decoder input reuse sprawdzone | ✅ (unique=1, corr ~0) |
| 5 | output slot reuse sprawdzone | ✅ (równomiernie, brak korelacji) |
| 6 | AMF lifetime bez dowodu | ✅ (UNKNOWN, bez gołosłownych twierdzeń) |
| 7 | STATIC_CACHE tylko dla state static | ✅ (state_sig distinct=1) |
| 8 | sync migration zmierzona | ✅ (SetStream→Blt 1:1) |
| 9 | correctness exact | ✅ (framemd5 1131/1131) |
| 10 | 1131/1131 | ✅ |
| 11 | drops=0 | ✅ |

---

## PLIKI

- Native: `src/d3d11_vp_pipeline.{h,cpp}` (per-setter timery, state sig, `SetVpStateMode`),
  `src/telem_amd_native.cpp` (env `AMD_VP_STATE_MODE`, trace 5S).
- Harnessy: `scratch/etap5s_analyze.py`, `scratch/etap5s_ab.py`.
- JSON/CSV: `Raporty/AMD_ETAP5G/etap5s_{analysis,ab}.json`,
  `l5s_{ref,reorder,cache,A,B,C,D}.mp4.frame_accounting.csv`.
- Wyjścia: `l5s_{ref,reorder,cache,A,B,C,D}.mp4`.
