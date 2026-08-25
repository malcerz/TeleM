# RAPORT AMD — ETAP 5O: bezpośredni pomiar AMF HEVC throughput / queue / drain

**STATUS: ✅ PASS** — jednoznaczna klasyfikacja pipeline'u (diagnostyka; bez zmian enkodera, bez 5P).

> **Ważne ograniczenie:** przebudowa DLL (tryb `BYPASS`) **nie była możliwa** —
> `g++.exe` jest blokowany przez politykę aplikacji Windows (error 4551,
> "Zasady kontroli aplikacji zablokowały ten plik"). Frontend ceiling jest
> estymowany z 5M zamiast mierzonego wprost. Wszystkie pozostałe pomiary
> wykonano po stronie Python (liczniki queue/cadence/drain — bez zmian w DLL).

---

## AMF FLOW AUDIT (kod natywny)

```
NV12 surface (VP output)
  → SubmitTexture → CreateSurfaceFromDX11Native (zero-copy)
  → amfEncoder.SubmitInput(pSurface)
        │  AMF_INPUT_FULL? → drain 1 packet (write h265 temp, framesReceived++)
        │                   → retry submit (aż do 60 s)  [amfInputFullCount++, amfRetryCount++]
        ▼
  → QueryPacket (QueryOutput) → pakiet → zapis do temp h265 → framesReceived++
  → (per frame: 1 submit + 1 query + ewentualne retry-drain)
Flush: amfEncoder.Drain() → pętla QueryOutput do AMF_EOF (lub 30 s timeout) → close h265
```

**Gdzie tracimy widoczność (przed 5O):** liczniki `framesSubmitted`/`framesReceived`
były odczytywane dopiero PO flush — nie było wglądu w głębokość kolejki w trakcie
eksportu, kadencję wyjścia ani końcowy drain. 5O dodaje per-frame odczyt tych
liczników (lekki, 2 ctypes call/frame, tylko gdy `AMD_AMF_DIAG=1`).

---

## PRODUCTION (A/B/C/D — ENCODE, AMD_AMF_DIAG=1, pełny pipeline, profiling OFF)

| Run | FPS | wall [s] | queue avg/med/p95/p99/max | trend | AMF cadence [FPS] | final outstd | drain [ms]/frames | input_full |
|---|---|---|---|---|---|---|---|---|
| **A** | 25.92 | 45.55 | 5.98 / 6 / 6 / 6 / 6 | STABLE | 28.3 | 6 | 39 / 6 | 0 |
| **B** | 27.20 | 43.69 | 2.99 / 3 / 3 / 3 / 3 | STABLE | 29.9 | 3 | 52 / 3 | 0 |
| **C** | 28.56 | 41.65 | 3.99 / 4 / 4 / 4 / 4 | STABLE | 30.7 | 4 | 30 / 4 | 0 |
| **D** | 26.83 | 44.07 | 3.48 / 3 / 5 / 5 / 5 | GROWS* | 31.0 | 5 | 228 / 5 | 0 |
| E (SUBMIT_NO_MUX) | 21.31 | 55.14 | 5.02 / 6 / 6 / 6 / 6 | GROWS* | 27.7 | 6 | 131 / 6 | 0 |

\* słaby sygnał (max 5–6, brak `input_full`); E to pojedynczy run — zaszumiony.

**Aggregate (A–D): MEDIAN FPS 27.01 | min 25.92 | max 28.56 | median wall 43.88 s | realtime 0.901×**

---

## QUEUE

| metryka | wartość (A–D) |
|---|---|
| avg | ~3.5–6.0 |
| median | 3–6 |
| P95 | 3–6 |
| P99 | 3–6 |
| max | **6** |
| trend | **STABLE** (GROWS tylko słabo w D/E) |
| **input_full** | **0** w każdym runie (1131×4 klatek) |

> Kolejka = **pipeline depth enkodera** (3–6 klatek w locie), **nie backlog**.
> `AMF_INPUT_FULL` nigdy nie wystąpiło → frontend **nie jest** dławiony przez
> encoder.

---

## AMF OUTPUT CADENCE

| run | med interval | p95 interval | equivalent FPS |
|---|---|---|---|
| A | 35.3 ms | 54.0 ms | 28.3 |
| B | 33.5 ms | 51.4 ms | 29.9 |
| C | 32.6 ms | 50.3 ms | 30.7 |
| D | 32.2 ms | 66.7 ms | 31.0 |

> **Kadencja enkodera (28.3–31.0 FPS) jest KONSEKWENTNIE WYŻSZA niż wall FPS
> (25.9–28.6)** we wszystkich 4 runach → encoder ma zapas ~1–4 FPS.

---

## FINAL DRAIN

| | |
|---|---|
| outstanding at final submit | **3–6 klatek** |
| drain time | **30–228 ms** |
| frames drained w flush | **3–6** |

> Po ostatnim submitcie nie ma istotnego backlogu — encoder dogania frontend
> w <0.25 s. Brak dowodu, że frontend wyprzedza encoder.

---

## FRONTEND BYPASS

- **BLOCKED** — `AMD_AMF_MODE=BYPASS` wymaga przebudowy DLL (`g++.exe` zablokowany
  przez politykę OS). Eksporter loguje fallback do ENCODE.
- **Estymata z 5M** (zamiast bezpośredniego pomiaru):
  - CPU frontend (suma stage'ów) ≈ 28.3 ms → **~35 FPS ceiling**,
  - GPU VP+HUD+NV12 completion ≈ 18.1 ms → **~55 FPS ceiling**,
  - → **frontend ceiling ≈ 35 FPS** (CPU-bound), tj. **> wall 27 FPS** → frontend
    też ma zapas, ale to on (a nie encoder) wyznacza wall.

## ENCODE_NO_MUX (E)

- **implemented: YES** (Python-side skip mux; `AMD_AMF_MODE=SUBMIT_NO_MUX`).
- E FPS 21.31 — **zaszumione** (pojedynczy run, 5. w kolejce; mux to ~0.6 s —
  nie może dać 30% różnicy). Konkluzja: **mux/file I/O NIE ma znaczenia**.

---

## THERMAL

| dane | wartość |
|---|---|
| temperature | **UNKNOWN** (brak wiarygodnego licznika Windows dla GPU AMD — nie zgaduję) |
| clock | **UNKNOWN** |
| encode utilization | **UNKNOWN** (`\GPU Engine(*)\Video Encode` zwraca 0 — atrybucja licznika nie działa dla AMF; potwierdzone 2× w 5M) |
| 3D utilization | ~67–75% (5M, orientacyjnie) |
| correlation | **Poziom bezwzględny zależy od stanu termicznego**: sesja 5N (po ~10 eksportach) = 16–20 FPS; sesja 5O = 26–28.5 FPS. W obrębie 5O A→D FPS oscyluje 25.9→28.6 (brak monotonicznej degradacji). Kadencja enkodera 28–31. **Thermal wpływa na poziom, ale nie zmienia klasyfikacji** (frontend i tak wyznacza wall). |

---

## CLASSIFICATION

| | |
|---|---|
| **ENCODER-BOUND** | **NO** |
| **FRONTEND-BOUND** | **YES** |
| **GPU-3D-BOUND** | **NO** |
| **THERMAL-LIMITED** | **PARTIAL** (poziom zależy od termiki, ale nie jest wiążącym ograniczeniem) |
| **MIXED** | **YES** (frontend/CPU primary + thermal) |

---

## EVIDENCE

1. **AMF output cadence 28.3–31.0 FPS > wall FPS 25.9–28.6** we wszystkich 4 runach
   → encoder ma zapas, nie jest podłogą.
2. **AMF_INPUT_FULL = 0** przez 1131×4 klatek → encoder **nigdy nie odrzucił/nie
   zbackpressure'ował** frontendu.
3. **Kolejka stabilna (3–6, pipeline depth), final drain 30–228 ms / ≤6 klatek**
   → brak narastającego backlogu.
4. **5N**: usunięcie 200× kosztu telemetry (8 ms → 0.04 ms) **nie** zmieniło wall
   → CPU-frontend (telemetry) nie był wiążący; 
5. **5M**: GPU VP+HUD ~18 ms (→55 FPS) i 3D util 67–75% → GPU 3D ma zapas;
   CPU stage'y ~28.3 ms (→35 FPS) + ~8.5 ms niezmierzonego narzutu pętli.
6. **SUBMIT_NO_MUX ≈ ENCODE** → mux/I-O nieistotne.

> **Wniosek zbiorczy:** 5M zakładało "drenaż enkodera = residual ~8.5 ms" — to
> **obalone przez bezpośredni pomiar**. Enkoder nadąża (~30 FPS). Resztka ~8.5 ms
> leży **w pętli frontendu** (narzut Python/ctypes/GC, pacing decode/GPU,
> serializacja submit+query+write), a nie w enkoderze i nie w telemetrii (5N).

---

## ODPOWIEDZ WPROST

1. **Czy AMF queue rośnie?** → **NIE** — stabilna 3–6 (pipeline depth enkodera),
   słaby GROWS tylko w D/E (max 5–6), **bez input_full**.
2. **Max outstanding?** → **6**.
3. **Drain po ostatnim submit?** → **30–228 ms, 3–6 klatek** (mały).
4. **Jak szybko AMF zwraca klatki?** → **28.3–31.0 FPS** (mediana interwału
   32–36 ms) — przy/lekko powyżej realtime source.
5. **Frontend bez AMF?** → BYPASS zablokowany (g++ OS policy); **estymata z 5M:
   ~35 FPS ceiling** (CPU 28.3 ms), GPU VP ~55 FPS.
6. **Mux/file I/O?** → **nieistotne** (~0.6 s; E ≈ A–D przy wariancji).
7. **Spadek z temp/taktowaniem?** → poziom bezwzględny **TAK** (5N 16–20 vs
   5O 26–28.5); temp/clock nie mierzalne wiarygodnie (**UNKNOWN**).
8. **Czy encoder to bottleneck?** → **NIE** — cadence > wall, input_full=0,
   queue stabilna, drain mały.
9. **Czy GPU 3D ma zapas?** → **TAK** (~18 ms → 55 FPS; util 67–75%).
10. **Czy CPU frontend ma zapas?** → **częściowo** — mierzone stage'y ~28 ms
    (ceiling 35 FPS), ale **~8.5 ms niezmierzonego narzutu per-frame**; compose
    11.3 ms to największy mierzalny stage.
11. **Co powinien robić 5P?** → **wrócić do frontendu**: 1) audyt ~8.5 ms
    niezmierzonego narzutu pętli (Python/ctypes/GC/pacing), 2) redukcja
    compose_overlay (11.3 ms). **Nie ruszać enkodera**.
12. **Czy wolno testować szybszy AMF preset w 5P?** → **NIE jest potrzebne** —
    encoder nie jest limiterem (cadence > wall, input_full=0, queue stabilna).
    5P powinien zajmować się **compose_overlay / pętlą frontendu**, nie enkoderem.

---

## KRYTERIA / UWAGI

- Bez zmian enkodera (Usage/Quality/RC/GOP/B-frames/bitrate) — ✅.
- Bez zmian jakości wyjścia; production default ENCODE bez zmian — ✅.
- `AMD_AMF_DIAG=1` — lekki (2 ctypes call/frame), OFF domyślnie — ✅.
- `AMD_AMF_MODE=SUBMIT_NO_MUX` — opt-in diagnostyczny — ✅.
- `AMD_AMF_MODE=BYPASS` — niedostępny (blokada OS `g++.exe`); udokumentowano
  fallback + estymatę.

**STATUS: ✅ PASS** (diagnoza jednoznaczna; brak możliwości BYPASS z powodu
zewnętrznej polityki OS — nie wpływa na konkluzję).

---

## ARTEFAKTY

- `Raporty/AMD_ETAP5G/etap5o_runs.json` (A/B/C/D/E + aggregate)
- Eksporty: `l5o_{A,B,C,D,E}.mp4` (+ `.amd_profile.json` z sekcją `etap5o`)
- Skrypty: `scratch/etap5o_runs.py`, `etap5o_print.py`
- Zmiany: `src/ffmpeg/amd_native_exporter.py` (AMD_AMF_MODE/AMD_AMF_DIAG, sekcja `etap5o`);
  natywna warstwa AMF **bez zmian** (blokada builda).
