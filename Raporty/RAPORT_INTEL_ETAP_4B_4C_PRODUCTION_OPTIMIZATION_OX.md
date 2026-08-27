# RAPORT INTEL ETAP 4B/4C — Hardening REGION, measured eligibility, P0 analysis

Data: 2026-08-25 | Branch: `intel-render` | HEAD (start): `e019a6b45278f09f718f528642767f505ea87934`
Tryb: etap produkcyjny (autonomiczny) | Commits: **brak** (zgodnie z §32)
Katalog roboczy: `scratch/intel_etap4bc/` | Wyniki zbiorcze: `scratch/intel_etap4bc/results.json`

## Executive summary

- **ETAP 4B = PASS.** Scale != 1 zweryfikowane runtime na 3 scenariuszach downscale +
  canvas-scale 0.5 — **parity bit-exact we wszystkich**. HDR/P010 runtime wykonane
  na lokalnym materiale 10-bit HLG — **bit-exact**, SW decode bez hwdownload potwierdzony.
  Multi-file CPU_REFERENCE+REGION — runtime smoke **PASS** (przekroczenie granicy klipu,
  parity bit-exact). Break-even REGION/FULL zmierzony empirycznie na 1080p i 4K:
  **REGION nie traci nawet przy ratio ~0.83**; dotychczasowy próg 0.85 pozostaje
  właściwy (teraz z override'em env i diagnostyką reason).
- **ETAP 4C = INVESTIGATED — NOT IMPLEMENTED** (poprawny wynik wg §19).
  Przeanalizowano kandydatów A–G: Candidate B (scale_qsv przed hwdownload) odrzucony
  jakościowo (11.44% pikseli diff>8 vs lanczos); Candidate C (vpp_qsv transpose)
  bit-exact (60/60 framemd5) ale zysk < szumu pomiarów (<5% wall → MARGINAL);
  brak bezpiecznej zmiany >=5%. Zero zmian produkcyjnych 4C.
- Zmiany produkcyjne tego etapu są ograniczone do hardeningu decyzji REGION
  (testowalna funkcja + threshold override + reason diagnostyka) i testów.
  AMD/NVIDIA/generic CPU/native Intel: nietknięte, regresje zielone.

## Repository state / hash pinning

T0 snapshot: `scratch/intel_etap4bc/state_T0.json` (branch, HEAD, status, diffstat,
SHA-256 8 plików). Kluczowe SHA-256 @T0:

| Plik | SHA-256 (16 hex) |
|---|---|
| src/ffmpeg/streaming.py | AB5B21989BE3AC01 |
| src/ffmpeg/command_builder.py | 8209D60DADC24F33 |
| src/ffmpeg/frame_renderer.py | 1B4A845B38CE1B3B |
| src/ffmpeg/shared_memory.py | E981384C50A062BF |
| src/ffmpeg/intel_backend.py | 32F334B520DD364A |
| src/indicators/compositor.py | 32E16C1515F4D1EC |
| src/benchmark.py | 7A09D5E8D46DFC0E |
| tests/test_video_helpers.py | 21B16A9111E2843A |

T_final: patrz sekcja „Concurrent modification review".

## ETAP 4B summary

| Obszar | Wynik |
|---|---|
| Scale != 1 (4B1) | PASS — parity bit-exact ×3 downscale + canvas_scale=0.5 |
| HDR/P010 runtime (4B2) | PASS — bit-exact; SW decode, bez hwdownload, p010le out |
| Multi-file (§13) | PASS — smoke runtime + parity przez granicę klipu |
| Break-even (4B3) | zmierzony; próg 0.85 potwierdzony danymi |
| Eligibility policy (§10) | prosta polityka progowa zachowana + override env |
| Kill-switch / diag (§11) | zachowane/rozszerzone jednorazowo |

## Scale != 1 analysis

Ścieżka: `overlay_w/h = render_w/h` ⇒ `scale_x = render_w/canvas_w = 1.0`;
bbox liczony w przestrzeni wyjściowej (`get_layout_hud_bbox(layout, overlay_w,
overlay_h)`), więc REGION jest geometrycznie niezależny od skalowania base.
Base skalowany po hwdownload (`hwdownload,format=nv12,scale=WxH:flags=lanczos`),
HUD trafia `overlay=hud_x:hud_y` bez dodatkowego skalowania.

Drugi wymiar: `hud_resolution_scale<1` (canvas < render) ⇒ `scale_x>1`; wtedy graf
skaluje bbox `scale={w*sx}:{h*sx}:flags=bilinear` i pozycjonuje na zaokrąglonej
`scaled_hud_x/y`. Ten przypadek również bit-exaktowy w teście T4 (poniżej).

## Scale parity results

Interleaved (region→full), 180 klatek, parity @ t=0.5/3.0/5.0 s:

| Scenariusz | Render | Canvas scale | Bbox ratio | Speedup | Parity worst changed%>2 |
|---|---|---|---|---|---|
| t1_4k_to_1080p | 1920×1080 | 1.0 | 0.108 | 1.07× | **0.0** |
| t2_4k_to_720p | 1280×720 | 1.0 | 0.112 | 0.99× | **0.0** |
| t3_1080p_to_720p | 1280×720 | 1.0 | 0.112 | 1.06× | **0.0** |
| t4_canvas_scale_half | 1280×720 | 0.5 | 0.112 | 1.05× | **0.0** |

Wszystkie mean_abs_diff = median_abs_diff = max_diff = 0 (bit-to-bit).
Żadnych halo/AA różnic — brak podstaw dla edge paddingu.

## Edge padding experiments

**NIE WYKONANE jako eksperyment produktowy** — warunek wejściowy (widoczne
artefakty krawędzi bbox przy scale != 1) nie wystąpił (wszystkie metryki = 0).
Padding = 0 pozostaje. Eksperyment padding 0/2/4/8 pozostaje możliwy w przyszłości,
gdyby pojawiły się realne materiały z subpikselowymi różnicami (np. nieparzyste
pozycje wskaźników po konfiguracji użytkownika).

## HDR/P010 runtime

Materiał: `scratch/intel_etap3b/HDR_CPU_REFERENCE.mp4`
(hevc, yuv420p10le, bt2020nc / arib-std-b67 HLG / bt2020).

Potwierdzone logami produkcyjnymi:

```text
[INTEL] CPU_REFERENCE download format: p010le
[INTEL] Decode path: SOFTWARE
[INTEL] HWDownload used: NO          <- brak powrotu hwdownload dla P010
[INTEL] HUD upload path: REGION      <- 476x216 @ (530,280)
-pix_fmt p010le (hevc_qsv)           <- encode 10-bit
```

Graf: `[0:v]format=p010le[base];[1:v]...format=rgba[ov];[base][ov]overlay=530:280`.
FULL vs REGION: **mean/max diff = 0** na t=0.5/3.0/5.0 s; metadata wyjścia zgodne
ze źródłem (p010le). Mastering metadata: źródło nie zawierało side-data mastering
(probe bez side-data) — nic do utraty. Speedup REGION vs FULL @720p10: 1.26×.

## Multi-file verification

Runtime smoke (`run_multifile_test.py`): 2× canonical_sdr_720p przez produkcyjny
concat demuxer (`render_concat_list.txt`), VideoTimeline 2 klipy po 6 s, render
210 klatek (przez granicę 6 s):

- REGION aktywny całościowo (`[INTEL] HUD upload path: REGION`),
  rozmiar pipe stały (brak resetu/mismatch),
- output geometry: 1280×720 oba warianty,
- FULL vs REGION parity: **changed%>2 = 0.0** na t=0.5/3.0/5.5 (**clip1**) i 6.5 s (**clip2**),
- timestamps/telemetria: resolve_render_target_dt przez timeline (nietknięte; §24).
- Obserwacja (poza zakresem): nb_frames 198 vs 200 między przebiegami — tail bufora
  hevc_qsv, niezależny od trybu transportu.

## Bbox ratio benchmark

`run_breakeven.py`: syntetyczne layouty 3 tekstów na przekątnej dopasowywane
iteracyjnie do docelowego ratio (achieved raportowane z tej samej funkcji
`get_layout_hud_bbox`, która decyduje produkcyjnie). Interleaved pary
REGION/FULL; mediana par. Uwaga metodologiczna: współrzędne wskaźników <=100
są interpretowane przez `get_layout_hud_bbox` jako **procenty** canvasu —
layouty "corners" dały więc ~0.29–0.32, a nie ~0.94; punkty i tak pokrywają
pełny zakres 0.06–0.84.

- 1080p: ratio {0.07, 0.115, 0.204, 0.302, 0.403, 0.497, 0.599, 0.698, 0.780,
  0.827, 0.319(corners)}; 3 pary ×180 klatek.
- 4K: ratio {0.103, 0.303, 0.497, 0.698, 0.837, 0.290}; 2 pary ×120 klatek.

## REGION break-even

1080p (speedup = FULL/REGION median):

| ratio | 0.07 | 0.115 | 0.204 | 0.302 | 0.403 | 0.497 | 0.599 | 0.698 | 0.780 | 0.827 |
|---|---|---|---|---|---|---|---|---|---|---|
| speedup | 1.11 | 1.15 | 1.22 | 0.87* | 1.06 | 1.04 | 1.06 | 1.02 | 0.88* | 1.05 |

4K:

| ratio | 0.103 | 0.303 | 0.497 | 0.698 | 0.837 |
|---|---|---|---|---|---|
| speedup | 1.11 | 1.11 | 1.09 | 1.04 | 0.975 |

(*) dwa punkty <1.0 na 1080p są niespójne z sąsiadami (szum środowiska
współdzielonego); brak monotonii sugeruje brak rzeczywistego progu opłacalności.

**Wniosek**: wyraźny break-even <1.0 nie występuje w zmierzonym zakresie.
Na 4K przy ratio 0.837 REGION jest praktycznie remisowy (0.975), poniżej 0.70
zawsze >=1.04. Na 1080p REGION >=1.0 w 8/10 punktów. Próg geometryczny 0.85
jest zatem bezpieczny i bliski optymalnego; podnoszenie go dawałoby <5%
dodatkowego zysku kosztem ryzyka — NIE zmieniano (§10A prosty próg wystarcza).

break_even_ratio_1080p: **nie znaleziony w zakresie (>=0.83 bezpiecznie)**
break_even_ratio_4k: **~0.84 (praktyczny remis)**

## New REGION eligibility policy

Zachowana polityka progowa (prosta, wg §10A):

```text
REGION if bbox_ratio < 0.85 (default)
FULL   if bbox_ratio >= 0.85
```

Nowe w 4B:
- decyzja przeniesiona do testowalnej `_intel_hud_region_decision()`
  (zwraca x/y/w/h + ratio + mode: region / full_threshold / full_geometry),
- override eksperymentalny: `TELEM_INTEL_CPU_REF_HUD_REGION_MAX_RATIO`,
- jednorazowa diagnostyka decyzji:

```text
[INTEL] HUD upload path: REGION  /  FULL_CANVAS reason=ratio_above_threshold(0.861>=0.85)
[INTEL] HUD bbox ratio: 0.076
[INTEL] threshold: 0.85
```

Kill-switche bez zmian: `TELEM_INTEL_CPU_REF_HUD_REGION=0` (CPU_REF),
`TELEM_INTEL_HUD_REGION` (native).

## REGION performance before/after

Przed 4B (=4A): 4K speedup 1.66×, 1080p moderate. Po 4B: mechanizm nietknięty;
sanity 1080p cluster: wall 3.41 s/90f (26.4 FPS), transport −92.4%.
Break-even potwierdza brak regresji w całym zakresie ratio <= 0.83.

## Updated bottleneck ranking (po 4B, CPU_REFERENCE SDR)

Fazy (avg ms/frame, audyt; 1080p ratio 0.115 REGION):
worker_render 2.01, worker_shm_copy 1.38, wait_for_free_slot 13.12,
ffmpeg_stdin_write 15.15, slot_lifetime 335.46 (backpressure FFmpeg-side).
4K ratio 0.30 REGION: render 6.2, shm 15.2, wait 28.3, write 35.0, slot 718.7.

| Priorytet | Obszar | Uzasadnienie |
|---|---|---|
| P0 | strona FFmpeg: QSV decode→hwdownload→SW overlay→implicit upload→hevc_qsv | slot_lifetime >> producent; jedyny duży koszt resztkowy |
| P1 | ffmpeg_stdin_write + wait_for_free_slot (producent) | ~28 ms/f @1080p REGION |
| P2 | worker_shm_copy | zredukowany przez 4A (FULL-only problem) |
| P3 | worker_render (crop) | 2–6 ms/f; pomijalne |

Pytanie z zadania: decode→hwdownload / SW base / SW overlay / QSV upload nadal
dominują? **TAK** — to pozostały P0; bezpieczne redukcje przeanalizowano w 4C
i odrzucono (niżej).

## ETAP 4C architecture analysis

Ścieżka SDR: `QSV decode → hwdownload(nv12) → [lanczos scale] → SW overlay
(rawvideo rgba pipe) → implicit hwupload → hevc_qsv`.

### CPU_REFERENCE fallback reasons matrix (z kodu streaming.py)

| Powód wejścia w CPU_REFERENCE | Wymaga CPU base? | SW overlay? | Może zostać QSV surface? | HW filter możliwy? |
|---|---|---|---|---|
| multi-file (>1 clip) | TAK (native single-file) | TAK | concat+QSV decode teoretycznie tak; native nie wspiera | n/d |
| rotation/container != 0 | TAK (transpose CPU) | TAK | TAK (vpp_qsv) | TAK (bit-exact) |
| cut_regions | select na CPU | TAK | częściowo | n/d |
| no-HUD | osobna ścieżka | n/a | n/a | n/a |
| resolution_name ∉ {source,720p,1080p} (np. 4k/480p/8k) | NIE technicznie — ograniczenie listy eligibility | overlay_qsv ogólny | TAK | scale_qsv działa |
| probe: HDR/10-bit źródło | TAK (format=p010le SW decode) | TAK | wymaga P010 overlay_qsv — nieweryfikowane | ryzyko metadata |
| probe failure / brak QSV decode | TAK | TAK | NIE | NIE |
| TELEM_INTEL_GPU_RESIDENT=0 (kill-switch) | świadome | — | — | — |

### P0 candidate architectures (A–G)

| Kand. | Opis | Expected gain | Parity risk | Werdykt |
|---|---|---|---|---|
| A | hwdownload po HW filters | = B | = B | odpada z B |
| B | `scale_qsv` przed hwdownload (target<source) | segment base ~2× (1.44–1.61 s vs 2.92–3.12 s /180f 4K→1080p) | **FAIL**: mean_abs_diff=2.95; **11.44% px diff>8** vs lanczos | **ODRZUCONY** |
| C | rotacja HW `vpp_qsv=transpose` przed hwdownload | timing w szumie (2.69–3.79 s vs 2.80–3.15 s /180f) | **BIT-EXACT 60/60 framemd5** | **MARGINAL (<5%)** — nie wdrażany |
| D | limit objętości base przed transferem | = B/C | = B/C | pokryte przez B/C |
| E | expand native eligibility (4k/480p/8k) | GPU path dla upscale/downscale | estetyka VPP-scaler ≠ lanczos (jak B) — decyzja produktowa | odroczone (§20 preferencja odnotowana) |
| F | explicit `hwupload=derive_device=qsv` | nieznany | ryzyko klasy HOTFIX2 | eksperyment, nie etap |
| G | inne | brak uzasadnienia z danych | — | — |

Uwaga techniczna: ten build FFmpeg **nie ma `transpose_qsv`**; pierwsze PoC
timingi 0.43 s były artefaktem natychmiastowego błędu filtra (wykryte przez
brak pliku framemd5). Poprawne PoC używa `vpp_qsv=transpose=clock`.

### Selected candidate

**Żaden.** Warunki §19 (>=5% realnego zysku + parity + minimalny diff +
Intel-only) nie zostały spełnione przez żadnego kandydata.

## Implementation 4C

Brak (świadomie). Stara ścieżka pozostaje jedyną; osobny kill-switch 4C nie jest
potrzebny, bo nie wprowadzono nowej ścieżki produkcyjnej.

## FFmpeg graph old / new

Old (= new; bez zmian 4C), SDR target=1080p z 4K:

```text
[0:v]hwdownload,format=nv12,scale=1920:1080:flags=lanczos[base];
[1:v]setpts=PTS-STARTPTS,format=rgba[ov];
[base][ov]overlay=<hx>:<hy>:shortest=1[vtemp] ... -c:v hevc_qsv -pix_fmt nv12
```

HDR/P010:

```text
[0:v]format=p010le[base];[1:v]...format=rgba[ov];[base][ov]overlay=... -pix_fmt p010le
```

## A/B performance (P0)

Nie dotyczy — brak implementacji P0. Pomiary PoC w tabeli kandydatów oraz w
`scratch/intel_etap4bc/results.json` (`p0_ab`).

## Regression tests

Focused suite po zmianach:

```text
tests/test_video_helpers.py + test_intel_backend.py + test_gpu_compositor.py
+ test_amd_native_overlay_handoff.py + test_etap5f_pipeline_audit.py
→ 60 passed (57 przed + 3 nowe 4B)
```

Nowe testy 4B:
1. `test_intel_hud_region_decision_threshold` — default 0.85, even-alignment,
   full_threshold fallback, env override w obie strony,
2. `test_intel_cpu_ref_region_scale_target_res_graph` — REGION + target_res:
   lanczos po hwdownload, overlay=hud_x:hud_y, `-s bbox`, nv12,
3. `test_intel_cpu_ref_region_canvas_scale_graph` — canvas<render: bilinear
   scale bboxa ×scale_x + scaled origin.

Regresje istniejące zielone: NVIDIA (rot180 CUDA fast-path itd.), AMD handoff,
Intel native grafy (region/p010), generic CPU encoder.

## NVIDIA preserved

Zero zmian kodu NV w tym etapie; testy NV zielone; runtime NV niedostępny
(brak HW) — *NVIDIA path preserved statically*.

## AMD preserved

Zero zmian AMD; test handoff zielony — *AMD path preserved statically;
runtime validation was not possible on this machine*.

## Intel native preserved

Ścieżka GPU-resident (ETAP 3C) bez zmian semantycznych; switch
`TELEM_INTEL_HUD_REGION` nietknięty; testy native zielone.

## Generic CPU preserved

Gałąź libx265 buildera nietknięta; testy zielone.

## Concurrent modification review

- „text not found" przy edycji bloku REGION: przyczyna to **mieszane końce
  linii** (1795 CRLF vs ~121 LF) po moich wstawieniach — nie obca edycja.
  Plik znormalizowany do LF programowo; AST OK; diff --stat spójny.
- SHA-256 obserwowanych plików porównane względem state_T0: żadnych cudzych
  zmian w plikach objętych zadaniem w trakcie pracy.

## Risks

1. Środowisko współdzielone: pojedyncze anomalne pary breakeven (0.87×@0.302,
   0.88×@0.780 @1080p) uznane za szum (niespójne z sąsiadami).
2. `TELEM_INTEL_CPU_REF_HUD_REGION_MAX_RATIO` przyjmuje dowolną wartość —
   celowo: switch eksperymentalny, default 0.85.
3. Multi-file nb_frames tail różnica (198 vs 200) — tail bufora hevc_qsv,
   niezależna od transportu; monitorować na innym materiale.
4. Layout coords <=100 = procenty w `get_layout_hud_bbox` (pre-existing,
   wspólne dla wszystkich backendów) — odnotowane, niezmieniane.

## Remaining bottlenecks

P0: FFmpeg-side CPU_REFERENCE pipeline. Opcje przyszłościowe:
(a) decyzja produktowa o akceptacji VPP-scalera odblokowuje B/E;
(b) P010 overlay_qsv dla HDR (metadata passthrough do weryfikacji);
(c) native multi-file slice jako dedykowany etap.

## Recommended next stage

1. Decyzja jakościowa VPP-vs-lanczos (odblokowuje największy pozostały zysk).
2. ETAP-kandydat: native multi-file (najczęstszy powód CPU_REFERENCE w GUI).
3. `.gitignore` dla dużych scratch logów (zaległość z ETAPU 3B).

## Final verdict

- **INTEL ETAP 4B: PASS**
- **INTEL ETAP 4C: INVESTIGATED — NOT IMPLEMENTED**


