# RAPORT AMD — ETAP 5U: feed enkodera / lifecycle powierzchni / obsługa QueryOutput + FRONTEND BYPASS

**Status: PASS.** DLL SHA `0D54126B75AC708DF698C61FC1E2B1AB20B67E464745540282D7B54DFB9FAF2C`
(ABI 8). Narzędzia: `AMD_AMF_MODE=BYPASS`, `AMD_AMF_QUERY_MODE=REFERENCE|DRAIN_READY`,
`AMD_VP_POOL_SIZE=4|6|8`. 1131 klatek każdy przebieg.

**Cel (spec):** rozdzielić 1) ceiling frontendu D3D11/VP/GPU, 2) ceiling AMF/VCN,
3) pacing z lifecycle powierzchni, 4) pacing ze sposobu obsługi QueryOutput.
Odpowiedź: **czy hardware encoder jest naprawdę wolniejszy, czy nasz
feed/query/resource lifecycle sztucznie ogranicza throughput?**

---

## WPROWADZONE MECHANIZMY

- **BYPASS (5O, odblokowany w 5R):** `telem_amd_set_amf_mode(ctx,1)` — pomija
  SubmitInput + QueryOutput i mux; frontend D3D11/VP/compute do końca. Exporter:
  `AMD_AMF_MODE=BYPASS` (true_fps liczony z `c_vp`).
- **DRAIN_READY (nowe):** `AMD_AMF_QUERY_MODE=DRAIN_READY` — po pierwszym
  udanym `QueryPacket` drenuje **wszystkie** natychmiast-gotowe pakiety, stop na
  pierwszym `AMF_REPEAT`, **zero czekania** (bez sleep/retry/flush). Nowe metryki
  w trace: `amf_query_calls`, `amf_outputs` (kolumny CSV).
- **Pool runtime (nowe):** `AMD_VP_POOL_SIZE=4|6|8` (domyślnie 4 = obecne
  zachowanie). Refaktor `POOL_SIZE` (statyczny 4) → `m_poolSize` (wektory
  `m_outputPool/m_outputViewPool/m_outputYViews/m_outputUVViews` + `SetPoolSize` +
  defensywny resize w init + `m_slotLastFrame` lifecycle tracking).

---

## CEILING FRONTENDU — BYPASS (spec 1/2)

| run | wall [s] | frontend FPS | GPU tl | AMF output | drops |
|---|---|---|---|---|---|
| BYPASS 1131 (5U sesja) | 30.53 | **39.36** | 1115 | 0 | 0 |
| BYPASS 1131 (wcześniej) | 28.23 | **40.07** | 1115 | 0 | 0 |

**Frontend ceiling ≈ 39.4–40 FPS** (cadence ~25 ms). BYPASS GPU timeline: span
med 20.66 ms, cadence 37.4 FPS, CPU-wait korelacja ~0 (brak AMF). Frontend
D3D11/VP/compute **nie jest** limitowany przez GPU 3D (ma zapas).

---

## ENCODE REFERENCE (baseline, spec 3)

- A (ENCODE/pool4/REF/gpu_ts=True): **34.25 FPS** (wall 34.84)
- A1/A2 (ENCODE/pool4/REF/gpu_ts=False, czysto): **31.48 / 31.59 → med 31.54 FPS**
- 5T baseline: 32–35 FPS typowo (termicznie zależne).

Dane szczegółowe N4 (pool4 + native acct + gpu_ts): wall 40.39 s, FPS 30.07,
**process_frame med 14.72 ms / p95 27.94**, AMF outstanding **5**, AMF query med
0.118 ms, GPU span med 30.04 ms, GPU cadence 30.4 ms = **32.9 FPS**,
**1007/1131 klatek z process_frame > 10 ms (89 %)**.

---

## ENCODE vs BYPASS (spec 4/5)

| | FPS | wall |
|---|---|---|
| BYPASS (ceiling frontendu) | 39.4–40.1 | 28.2–30.5 s |
| ENCODE pool4 REF | 31.5–34.3 | 34.8–37.6 s |
| **ENCODE pool8 REF** | **37.8–38.3** | **31.3–31.7 s** |

- Pozorny „koszt VCN” przy pool 4 = **5–8 FPS**, ALE to **NIE** jest koszt
  enkodera — to throttling lifecycle (patrz niżej).
- Przy pool 8 ENCODE osiąga **~38 FPS ≈ ceiling frontendu** → **samo VCN kosztuje
  tylko ~1–2 FPS**. Hardware encoder NIE jest prawdziwym bottleneckiem.

---

## QUERY MODE — DRAIN_READY (spec 6–10)

Czysta izolacja (gpu_ts=False, med):

| pool | REFERENCE | DRAIN_READY | delta |
|---|---|---|---|
| 4 | 31.54 (A1/A2) | 31.51 (C1/C2) | **−0.03** |
| 6 | 37.46 (D1) | 36.76 (D2) | −0.70 |
| 8 | 37.75 (E1) | 38.27 (E2) | **+0.52** |

**Sposób obsługi QueryOutput NIE ma wpływu na throughput** (−0.03/−0.70/+0.52 =
szum; powtórki C1/C2 32.20/30.81 też w szumie). Smoke: tylko 8/61 klatek miało
>1 pakiet gotowy naraz — steady-state enkoder produkuje ~1 pakiet/klatkę, więc
„drenuj wszystko co gotowe” nie ma czego drenażować. `amf_query` med 0.12–0.14 ms
— QueryOutput sam w sobie tani.

---

## POOL SIZE (spec 11–15)

Czysta izolacja (gpu_ts=False):

| pool | REFERENCE | DRAIN_READY |
|---|---|---|
| 4 | 31.54 | 31.51 |
| 6 | **37.46** | 36.76 |
| 8 | **37.75** | 38.27 |

**Pool-size delta (REF): 6 vs 4 = +5.92 FPS; 8 vs 4 = +6.21 FPS.**
**Pool-size delta (DRAIN): 6 vs 4 = +5.26; 8 vs 4 = +6.76.**
Pool 6 daje niemal całość; 8 dodaje ~0.3–0.5 FPS.

**Spec 15 (test krytyczny):** wall poszło z **37.5 s (pool4) → 31.7 s (pool8)**
(≈ −5.8 s, +6 FPS) — **to NIE jest „przesunięcie buforowania”, to realny
bottleneck feed/lifecycle.** Równolegle: `process_frame` med **14.72 → 2.30 ms**,
AMF outstanding **5 → 10**, GPU span **30.0 → 20.3 ms**, GPU cadence **32.9 → 41.3
FPS**, klatki z process_frame>10 ms **1007/1131 (89 %) → 96/1131 (8.5 %)**.

---

## LIFETIME / MECHANIZM (spec 16–21)

**Mechanizm throttlingu pool 4 (pełny obraz):**
1. VP output pool ma **4 sloty**. Po 4 klatkach frontend wraca do slotu 0.
2. Enkoder wciąż może trzymać ten surface (SubmitTexture = zero-copy wrap DX11,
   czytanie asynchroniczne).
3. Driver/enkoder **serializuje reuse**: nowy VideoProcessorBlt nie może
   nadpisać surface, którego nie skończył czytać VCN → **implicit wait**.
4. Efekt: periodyczne **spiki 40–70 ms co 4 klatki** (wrap pool); process_frame
   med 14.7 ms; GPU span rośnie do 30 ms (GPU czeka w ramach mierzonego okna).
5. Pool 8 → wrap co 8 klatek, spiki znikają (96/1131), process_frame med 2.3 ms,
   GPU cadence 41.3 FPS, ENCODE ~38 FPS.

**Lifecycle tracking:** `m_slotLastFrame` (per-slot) dodane jako diagnostyka;
przy pool 4 slot jest ponownie używany, gdy enkoder może go jeszcze trzymać
(outstanding 5 > pool 4) — to właśnie źródło czekania.

**BYPASS life-time:** przy BYPASS brak enkodera → brak reuse-wait → 39.4–40 FPS.

---

## BEST A/B REPEAT (spec 23/24)

- A1/A2 (ENCODE pool4 REF): **31.48 / 31.59 FPS** — powtarzalne (spread 0.35 %).
- C1/C2 (ENCODE pool4 DRAIN): 32.20 / 30.81 — w szumie query-mode.
- E1/E2 (ENCODE pool8 REF): **37.75 / 38.27 FPS** — powtarzalne (+6.2 FPS vs pool4).
- B (BYPASS): 39.36 / 40.07 — ceiling frontendu.
- **Best production (non-bypass): ENCODE/pool8/REFERENCE ≈ 38 FPS**; BYPASS
  najlepszy bezwzględnie (39.4–40) ale bez enkodera.

First-call (pierwszy pakiet AMF): klatka **3 (pool4) / 2 (pool8)**, ~3.5–3.7 ms.

---

## CORRECTNESS (spec 25/26)

| para | framemd5 (1131) | wynik |
|---|---|---|
| A1 (pool4 REF) vs C1 (pool4 DRAIN) | 1131/1131 identyczne | ✅ |
| A1 vs D1 (pool6 REF) | 1131/1131 identyczne | ✅ |
| A1 vs E1 (pool8 REF) | 1131/1131 identyczne | ✅ |

**DRAIN_READY i pool 6/8 NIE zmieniają pikseli** (brak korupcji z głębszego
poolu — potwierdza, że pool 4 nie psuł obrazu, tylko go throttlował). Wszystkie
runy: 1131/1131, input_full=0, retries=0, dropped=0.

---

## CLASSIFICATION (spec 29)

| | YES/NO |
|---|---|
| **TRUE VCN LIMIT** | **NO** (pool8 ENCODE 38 ≈ BYPASS 39.4–40; VCN ~1–2 FPS) |
| **QUERYOUTPUT SERVICING** | **NO** (DRAIN_READY: −0.03/−0.70/+0.52 = szum) |
| **VP OUTPUT SURFACE LIFETIME** | **YES — główny bottleneck** (pool wrap → serializacja reuse) |
| **TOO-SHALLOW OUTPUT POOL** | **YES** (pool 4; 6/8 → +6 FPS) |
| **DRIVER QUEUE THROTTLE** | **YES** (mechanizm: implicit surface-in-use wait; spiki 40–70 ms co 4 kl.) |
| **FRONTEND LIMIT** | **YES przy ~39–40 FPS** (ceiling; nie przy pool 4) |
| **MIXED** | **YES** (pool4 = lifecycle-bound 30–35; pool8 = frontend/VCN-bound ~38) |

**Klasyfikacja główna: TOO-SHALLOW OUTPUT POOL / VP OUTPUT SURFACE LIFETIME.**
Enkoder NIE jest wolniejszy — nasz 4-slotowy pool outputu VP sztucznie
ograniczał throughput do ~30–35 FPS. QueryOutput nie ma znaczenia.

---

## ODPOWIEDZ WPROST

1. **Czy hardware encoder (VCN) jest naprawdę wolniejszy?** → **NIE.** Przy pool 8
   ENCODE osiąga ~38 FPS, czyli ceiling frontendu (BYPASS 39.4–40).
2. **Jaki jest rzeczywisty ceiling frontendu?** → **~39.4–40 FPS** (BYPASS,
   cadence ~25 ms); GPU 3D ma zapas (span 20.7 ms, cadence 37.4–41 FPS).
3. **Jaki jest ceiling ENCODE przy obecnym pool 4?** → **~31.5–34 FPS** (termicznie
   zależne) — to NIE limit VCN, tylko lifecycle.
4. **Jaki jest ceiling ENCODE przy pool 8?** → **~37.5–38.3 FPS**.
5. **Ile realnie kosztuje samo VCN?** → **~1–2 FPS** (BYPASS 39.4–40 vs pool8 ENCODE 38).
6. **Czy sposób obsługi QueryOutput ogranicza throughput?** → **NIE.**
   DRAIN_READY (drenuj wszystkie gotowe, zero czekania) = delta 0 (szum).
7. **Czy bywają >1 gotowe pakiety?** → Tylko sporadycznie (8/61 w smoke); w
   steady-state enkoder daje ~1 pakiet/klatkę — drenaż nie ma czego oddać.
8. **Czy lifecycle powierzchni VP ogranicza throughput?** → **TAK — to główny
   bottleneck.** Wrap 4-slotowego poolu co 4 klatki = serializacja reuse
   (surface-in-use) → spiki 40–70 ms, process_frame med 14.7 ms.
9. **Jaki jest efekt głębokości pool?** → **+5.9 do +6.8 FPS** (6/8 vs 4; REF i
   DRAIN); wall 37.5→31.7 s.
10. **Jaki jest mechanizm czekania?** → Driver/enkoder czeka, aż VCN skończy
    czytać surface zanim VP go nadpisze (implicit sync). Pool 8 → rzadkie (8.5 %
    klatek z pf>10 ms vs 89 %).
11. **Czy pool 6/8 zmienia piksele?** → **NIE** — framemd5 1131/1131 identyczny.
12. **Klasyfikacja końcowa?** → **TOO-SHALLOW OUTPUT POOL (VP output surface
    lifetime) + DRIVER QUEUE THROTTLE; NIE VCN, NIE QueryOutput; MIXED.**

---

## REKOMENDACJA (dla 5V; NIE wykonywane w 5U)

- **Ustawić domyślny `AMD_VP_POOL_SIZE=8`** (lub 6) — najtańszy realny zysk
  ~+6 FPS (30–35 → ~38), zero kosztu CPU, zero zmiany pikseli, zero zmiany
  jakości enkodera, ~4 dodatkowe surface NV12 4K (pamięć GPU ~4×16.6 MB).
- QueryOutput: zostawić REFERENCE (DRAIN_READY bez zysku).
- Enkoder/jakość: bez zmian (CQP 28/28 Speed nietknięty).

---

## KRYTERIA PASS

| # | kryterium | wynik |
|---|---|---|
| 1 | BYPASS działa (frontend tylko, bez enkodera/muxu) | ✅ (39.4–40 FPS, AMF output 0) |
| 2 | ceiling frontendu zmierzony | ✅ (39.4–40 FPS) |
| 3 | ceiling AMF/VCN zmierzony (pool 4 i pool 8) | ✅ (31.5–34 / 37.8–38.3) |
| 4 | ENCODE vs BYPASS rozdzielone | ✅ (VCN ~1–2 FPS przy pool 8) |
| 5 | QueryOutput servicing zmierzony | ✅ (DRAIN_READY delta 0) |
| 6 | lifecycle powierzchni zmierzony | ✅ (pool 4→8: pf 14.7→2.3 ms, +6 FPS) |
| 7 | pool 6/8 bez regresji jakości | ✅ (framemd5 1131/1131) |
| 8 | 1131/1131, drops=0 | ✅ |
| 9 | A/B repeat powtarzalny | ✅ (A1/A2, E1/E2) |
| 10 | klasa bottlenecku wskazana | ✅ (TOO-SHALLOW OUTPUT POOL / SURFACE LIFETIME) |
| 11 | jakość enkodera nietknięta | ✅ (CQP 28/28; zero zmian encoder) |
| 12 | NIE wykonano 5V | ✅ (tylko diagnostyka + rekomendacja) |

---

## PLIKI

- Native: `src/d3d11_amf_pipeline/src/telem_amd_native.cpp` (`AMD_AMF_MODE=BYPASS`,
  `AMD_AMF_QUERY_MODE` DRAIN_READY, `AMD_VP_POOL_SIZE`, liczniki `amf_query_calls`/
  `amf_outputs` w trace), `src/d3d11_vp_pipeline.{h,cpp}` (`SetPoolSize`, wektory,
  `m_slotLastFrame` lifecycle).
- Exporter: `src/ffmpeg/amd_native_exporter.py` (`telem_amd_set_amf_mode` BYPASS,
  mux skip, true_fps z c_vp przy BYPASS).
- Harnessy: `scratch/etap5u_runs.py` (A/B/C/D/E), `scratch/etap5u_isolation.py`
  (czysta izolacja query×pool), `scratch/etap5u_detail.py` (N4/N8 + analiza).
- JSON/CSV: `Raporty/AMD_ETAP5G/etap5u_{runs,isolation,detail}.json`,
  `l5u_*.frame_accounting.csv`, `l5u_*.gpu_timeline.csv`, `l5u_*.md5`.
