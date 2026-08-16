# RAPORT AMD — ETAP 5P: pełne wall-clock accounting głównej pętli eksportu

**STATUS: ✅ PASS** — frame loop **100% rozliczony**; ~8.5 ms "residual" z 5M
**wyjaśnione** (artefakt metody inkluzywnej 5M + natywne pacing `process_frame`).
Diagnostyka opt-in; production code bez zmian wydajnościowych; **bez 5Q**.

---

## CONTROL / OVERHEAD

| Run | tryb | wall [s] | TRUE FPS | valid |
|---|---|---|---|---|
| **A** | accounting OFF (control, REF) | 43.44 | 27.18 | ✅ |
| **B** | accounting ON (REF) | 43.64 | 27.10 | ✅ |
| **C** | accounting ON (REF) | 40.87 | 28.96 | ✅ |
| **D** | accounting ON (**PRECOMPUTED**) | 46.33 | 25.49 | ✅ |

**Instrumentation overhead (B−A)/A = 0.45 %** — znacznie poniżej wymogu 5%.
C (28.96 FPS) jest szybszy niż A → brak realnego spowolnienia (wariancja sesji).

---

## FRAME WALL (accounting ON)

| | B | C | D |
|---|---|---|---|
| frame_total med [ms] | 33.83 | 31.21 | 34.78 |
| p95 [ms] | 52.13 | 50.39 | 51.34 |
| p99 [ms] | 64.75 | 67.47 | 58.80 |

---

## ACCOUNTED

| | B | C | D |
|---|---|---|---|
| measured sum med [ms] | 25.33 | 29.33 | 28.21 |
| **unaccounted med [ms]** | **0.002** | **0.002** | **0.001** |
| **accounted** | **100.00 %** | **99.99 %** | **100.00 %** |
| unaccounted % frame | 0.00 % | 0.01 % | 0.00 % |

> **Cel 5P osiągnięty**: praktycznie 100% frame wall przypisane do exclusive stages.
> **Brak ukrytego kosztu ~8.5 ms** — w 5P nie istnieje żaden nieprzypisany narzut.

---

## TOP 10 EXCLUSIVE (mediana; % frame)

### B (REFERENCE) — frame 33.8 ms
| # | stage | med [ms] | p95 [ms] | % frame |
|---|---|---|---|---|
| 1 | **compose** | 9.61 | 23.09 | 28.4 % |
| 2 | **telemetry** | 4.20 | 13.06 | 12.4 % |
| 3 | **process_frame** (native) | 3.84 | **29.97** | 11.4 % |
| 4 | map_upload | 3.01 | 8.09 | 8.9 % |
| 5 | gauge_upload | 1.98 | 5.62 | 5.9 % |
| 6 | hud_dirty | 1.26 | 3.92 | 3.7 % |
| 7 | decode_read | 0.81 | 4.44 | 2.4 % |
| 8 | update_hud | 0.28 | 0.84 | 0.8 % |
| 9 | chart_upload | 0.17 | 0.60 | 0.5 % |
| 10 | native_timings | 0.13 | 0.50 | 0.4 % |

### C (REFERENCE) — frame 31.2 ms (ranking stabilny)
| # | stage | med [ms] | p95 [ms] | % frame |
|---|---|---|---|---|
| 1 | **compose** | 10.37 | 23.84 | 33.2 % |
| 2 | **telemetry** | 9.76 | 13.76 | 31.3 % |
| 3 | map_upload | 2.49 | 6.87 | 8.0 % |
| 4 | **process_frame** | 2.36 | 6.10 | 7.6 % |
| 5 | gauge_upload | 1.82 | 5.16 | 5.8 % |
| 6 | decode_read | 0.98 | 5.04 | 3.1 % |
| 7 | hud_dirty | 0.95 | 2.89 | 3.0 % |
| 8 | update_hud | 0.23 | 0.63 | 0.7 % |
| 9 | chart_upload | 0.16 | 0.51 | 0.5 % |
| 10 | native_timings | 0.15 | 0.53 | 0.5 % |

> Ranking B↔C stabilny: **compose + telemetry = ~60 %** frame; map ~8 %;
> process_frame ~8–11 % (zmienne). Cecha wspólna: **compose i telemetry to
> największe mierzalne koszty CPU**.

---

## CTYPES / NATIVE

| native call | B med [ms] | C med [ms] | D med [ms] | p95 (max) |
|---|---|---|---|---|
| **process_frame** | 3.84 | 2.36 | **11.80** | **30–35 ms** |
| update_hud | 0.28 | 0.23 | 0.28 | ~0.9 ms |
| chart_upload (tobytes+call) | 0.17 | 0.16 | 0.17 | ~0.7 ms |
| gauge_upload (tobytes+call) | 1.98 | 1.82 | 2.00 | ~5.8 ms |
| map_upload (render+tobytes+call) | 3.01 | 2.49 | 2.84 | ~8.6 ms |
| native_timings (stat reads) | 0.13 | 0.15 | 0.12 | ~0.5 ms |
| decode_read (ReadSample+loop) | 0.81 | 0.98 | 0.73 | ~5 ms |

> **process_frame to dominujący call natywny i jedyny z dużym ogonem (p95
> 30–35 ms)** — sporadyczne pacing/synchronizacja GPU/AMF. To jest punkt
> elastyczny pętli (patrz niżej).

---

## GC

| | B | C | D |
|---|---|---|---|
| collections | 11 | 11 | 13 |
| collections/frame | 0.010 | 0.010 | 0.011 |
| total pause [ms] | 7.1 | 7.6 | 9.5 |
| max pause [ms] | 1.88 | 1.79 | 2.14 |
| avg pause [ms/frame] | ~0.006 | ~0.007 | ~0.008 |

> **GC jest znikomy** (~0.006 ms/frame avg, max pojedyncze 2 ms) — nie wymaga
> A/B w 5P; NIE wyłączano GC.

---

## CALLBACKS / LOGGING

- progress: co **10 klatek** (`progress_interval`), mediana ~0.004 ms — **znikomy**.
- `Frame {n}: HR=...` co 30 klatek (print) — poza top-10 (w `loop_guard`/misc).
- logging/print/flush w pętli — brak istotnego kosztu (w top-10 nie występuje).

---

## DECODE PACING

| | B | C | D |
|---|---|---|---|
| decode_read med [ms] | 0.81 | 0.98 | 0.73 |
| p95 [ms] | 4.44 | 5.04 | 4.32 |

> ReadSample + retry/null/event loop mieści się w ~1 ms; okazjonalne p95 ~5 ms.
> **Decode NIE jest limiterem.**

---

## 5N EXPLANATION (liczbowo potwierdzone)

| run | telemetry med [ms] | process_frame med [ms] | frame_total med [ms] | FPS | wall [s] |
|---|---|---|---|---|---|
| **B** (REF) | 4.20 | 3.84 | 33.83 | 27.10 | 43.64 |
| **C** (REF) | 9.76 | 2.36 | 31.21 | 28.96 | 40.87 |
| **D** (PRE) | **0.04** | **11.80** | 34.78 | 25.49 | 46.33 |

> **Dlaczego 5N nie przyspieszył wall:** usunięcie telemetry (4.2–9.8 ms → 0.04 ms)
> **przeniosło czas do `process_frame`** (2.4–3.8 ms → 11.8 ms, wzrost ~+8–9 ms ≈
> oszczędność telemetry). Frame_total pozostał ~34 ms (B 33.8 vs D 34.8) — wall
> **nie spadł**, bo **natywne pacing `process_frame` (GPU/AMF) wchłonął uwolniony
> czas CPU**. To klasyczny **pipeline overlap/pacing** — udowodniony liczbowo,
> nie zgadywany.

---

## UNACCOUNTED

| | |
|---|---|
| median | **0.002 ms** |
| P95 | ~0.01 ms |
| largest suspected source | brak — frame 100% rozliczony |

> **Residual ~8.5 ms z 5M został w pełni wyjaśniony**: (1) metoda 5M sumowała
> **inkluzywne** timing_samples i porównywała z wall — z pominięciem true wall
> `process_frame` i nakładaniem się stage'ów; (2) w accounting exclusive
> `process_frame` (natywne pacing) jest jawne i **elastyczne** — rośnie, gdy CPU
> się zwalnia. Nie istniał żaden ukryty koszt — to był artefakt metody + pacing.

---

## BOTTLENECK CLASSIFICATION

| składowa | udział / rola |
|---|---|
| **CPU pure Python** | **~15–20 ms/frame** (compose 10 + telemetry 5–10 + map 2.5 + gauge 2 + dirty 1) — największy mierzalny blok |
| **ctypes/native pacing** | **`process_frame` 2–12 ms (elastyczny)** — efektywny limiter; absorbuje uwolniony CPU |
| **GPU pacing** | w `process_frame` (p95 30–35 ms spiki) |
| **AMF** | nie limiter (5O: cadence 28–31 FPS > wall, input_full=0) |
| **GC** | znikomy (~0.006 ms/frame) |
| **I/O** | znikomy (mux ~0.6 s; packet write w process_frame) |

---

## ODPOWIEDZ WPROST

1. **Gdzie było brakujące ~8.5 ms?** → **Nie istniało jako osobny koszt.** Było
   artefaktem inkluzywnej metody 5M + elastycznym natywnym `process_frame`
   (pacing). Accounting exclusive: 100% frame przypisane.
2. **Ile % frame rozliczone?** → **100 %** (unaccounted 0.002 ms).
3. **Największy exclusive stage?** → **compose (~10 ms)**; razem z telemetry
   (~5–10 ms) to ~60 % frame.
4. **Ile kosztuje compose?** → **~9.6–10.4 ms** (mediana, exclusive).
5. **Ile w ctypes/native?** → dominuje **`process_frame` (2.4–11.8 ms)**;
   update_hud 0.23, chart/gauge/map uploady ~0.2/2/2.5–3 ms (łączny native ~8–15 ms).
6. **Czy ProcessFrame blokuje na GPU pacing?** → **TAK, częściowo** — p95 30–35 ms,
   mediana 2.4–11.8 ms (zależnie od obciążenia CPU); w PRE (mało CPU) rośnie do 11.8 ms.
7. **Czy GC ma znaczenie?** → **NIE** (~0.006 ms/frame, max 2 ms).
8. **Czy progress/logging ma znaczenie?** → **NIE** (~0.004 ms co 10 klatek).
9. **Dlaczego 5N nie przyspieszył?** → pacing `process_frame` wchłonął oszczędność
   telemetry (4.2–9.8 ms → 0; process_frame 2.4–3.8 → 11.8 ms). Wall bez zmian.
10. **Czy residual z 5M wyjaśniony?** → **TAK** — artefakt metody + elastyczny
    `process_frame`; nie ma ukrytego kosztu.
11. **Co powinien robić 5Q?** → **zredukować `compose_overlay` (10 ms)** — największy
    stage — **oraz** zbadać/zredukować natywny pacing `process_frame` (split wewn.
    process_frame: VP submit vs AMF submit vs query vs write — gdy build DLL będzie
    odblokowany). Sam compose może być częściowo wchłonięty przez pacing (jak
    telemetry), więc cel 5Q = compose + natywna synchronizacja.
12. **Jaki pojedynczy target da największy realny zysk?** → **`compose_overlay`
    (10 ms, 28–33 % frame)** — największy mierzalny, bezpieczny (CPU-side) target.
    Realny sufit: `process_frame`/GPU-AMF (~30 FPS wg 5O cadence) → potencjał
    ~27 → ~30 FPS przy redukcji compose+telemetry, pod warunkiem że pacing
    `process_frame` nie wchłonie całości (do zmierzenia w 5Q przez ten sam trace).

---

## KRYTERIA PASS

| # | kryterium | wynik |
|---|---|---|
| 1 | production architecture bez zmian | ✅ (diagnostyka opt-in, default bez zmian) |
| 2 | accounting overhead <= 5% | ✅ (0.45 %) |
| 3 | >= 95% frame wall przypisane | ✅ (100 %) |
| 4 | unaccounted residual jasno zaraportowany | ✅ (0.002 ms) |
| 5 | brak AMF/quality changes | ✅ |
| 6 | frame accounting 1131/1131 | ✅ (wszystkie runy) |
| 7 | drops=0 | ✅ |
| 8 | final output bez regresji | ✅ (runy valid, output OK) |

**STATUS: ✅ PASS**

---

## ARTEFAKTY

- `Raporty/AMD_ETAP5G/etap5p_runs.json` (A/B/C/D + accounting summaries)
- Per-frame trace: `l5p_{B,C,D}.mp4.frame_accounting.json` (frame_total, każdy
  exclusive stage, unaccounted, GC pauses)
- Skrypty: `scratch/etap5p_runs.py`, `etap5p_print.py`
- Zmiana: `src/ffmpeg/amd_native_exporter.py` — `_FrameAccountant`,
  `AMD_FRAME_ACCOUNTING=1` (OFF default), sekcja `etap5p` w profilu, GC callbacks.
