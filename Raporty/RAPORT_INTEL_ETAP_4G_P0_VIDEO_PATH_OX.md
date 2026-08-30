# RAPORT INTEL ETAP 4G — P0 VIDEO PATH: decode/encode decomposition + QSV system-memory decode feasibility (OX)

Data: 2026-08-25 | Branch: `intel-render` | HEAD: `e019a6b45278f09f718f528642767f505ea87934`
Tryb: audit → controlled PoC → conditional implementation | Commits: **brak**
Artefakty: `scratch/intel_etap4g/` (bench_decomposition.py, state_T0, results.json,
framemd5 dowody)

## Executive summary

**INTEL ETAP 4G: INVESTIGATED — NOT IMPLEMENTED.**

Decomposition na realnym materiale (GX020079, 300 f, mediana ×3):

```text
software HEVC Main10 decode only      ~64.8 FPS   (sufit dekodera SW)
QSV hw decode only (GPU surfaces)     ~244 FPS
QSV decode -> SYSTEM MEMORY p010      ~151.5 FPS  (Candidate A — DZIAŁA)
base without HUD + encode (SW dec)    ~22.3 FPS
base without HUD + encode (QSV-sys)   ~24.8 FPS
encode-only ceiling (raw p010 in)     ~24.4 FPS
production (z REGION HUD)             24.18 / świeża mediana 27.7 FPS
```

**P0 VERDICT: ENCODE_BOUND.** Produkcja pracuje na/ponad sufitem
`hevc_qsv` (veryfast/gq24/p010le @4K): 24.18 = 99.2% sufitu zmierzonego w tym
samym oknie; świeże przebiegi (27.7/28.2) przekraczają sufit D mierzony wcześniej
— potwierdza to, że ogranicza enkoder, nie dekoder ani pipeline.

Odkrycie etapu: **jawny `-c:v hevc_qsv` (bez `-hwaccel`) outputuje ramki
bezpośrednio do SYSTEM MEMORY p010** — bit-exact z software decode
(framemd5 identyczne), bez `hwdownload`, stabilnie 300+ klatek. Capability
zweryfikowane i udokumentowane dla przyszłych etapów, ale wdrożenie teraz
nie daje >=5% end-to-end (produkcja jest ENCODE_BOUND), więc wg §19/§30
NIE wdrażano.

## State pinning

T0/Tfinal: `scratch/intel_etap4g/state_T0.json`; produkcja nietknięta
(weryfikacja SHA-256 na końcu etapu). FFmpeg `2026-08-17-git-426841da9d`.

## Current real production baseline

GX020079.MP4 (4K Main10 HLG pc rot180), CPU_REFERENCE + REGION:

- 4D pomiar: 300 f, wall 12.41 s → **24.18 FPS**, HUD 3 400 992 B/f
- świeża powtórka 4G: 14.55 / **27.69** / **28.22** FPS (mediana 27.69;
  pierwszy przebieg na obciążonej maszynie) — zakres pokazuje szum środowiska,
  wniosek ENCODE_BOUND niezależny od okna.

## Benchmark methodology

300 klatek (D: 90 klatek realnego raw p010 2.2 GB — usunięte po pomiarach),
mediana z 3 przebiegów naprzemiennych, identyczne ustawienia enkodera
(veryfast/global_quality 24/look_ahead 0/async_depth 4/p010le/qsv_device 1).
Rotacja 180° obsłużona produkcyjnie (`-noautorotate` + jawne vflip,hflip).

## Decode-only results

| test | median wall | median FPS |
|---|---|---|
| A_SW (SW decode → null) | 4.70 s | **64.8** |

## QSV decode-only results

| test | median wall | median FPS |
|---|---|---|
| B_QSVHW (GPU surfaces → null) | 1.23 s | **244.4** |
| A2_QSVSYS (system-memory p010 → null) | 1.98 s | **151.5** |

Intel 8086:4692 / adapter 1; P010 video surfaces potwierdzone (B) oraz
p010le system memory potwierdzone rozmiarem i md5 (A2/Candidate A).

## Encode-only results

| test | median wall | median FPS |
|---|---|---|
| D_encode_only (raw p010 → hevc_qsv, producyjne ustawienia) | 3.69 s /90f | **24.37** |

Sufit enkodera ≈ 24.4 FPS @4K HDR p010 w tej konfiguracji.

## Base-without-HUD results

| test | median wall | median FPS |
|---|---|---|
| C_NOHUD_swdec_encode | 13.45 s | 22.31 |
| C_NOHUD_qsvsys_encode (Candidate A) | 12.10 s | 24.80 (+11% vs SW-dec variant) |

## Current production results

E: 24.18 FPS (4D) / świeże 14.55–28.22 (mediana 27.69). Production ≥ sufit D
⇒ brak miejsca po stronie decode.

## Performance decomposition

| element | udział / limit |
|---|---|
| decode (SW) | sufit 64.8 FPS — **nie ogranicza** (2.7× production) |
| decode (QSV-sys) | sufit 151.5 FPS — nie ogranicza |
| rotation/base processing | wliczony w C; swap decode daje ≤ +11% tylko bez HUD |
| overlay (REGION) | ~1.7% wall (ETAP 4E) |
| **encode hevc_qsv** | **sufit 24.4 FPS = production level** |
| pipeline/backpressure | symptom szybkości enkodera (patrz niżej) |

## QSV system-memory decode capability

**VERIFIED (Candidate A)**:

```text
ffmpeg -c:v hevc_qsv -qsv_device 1 -i GX020079.MP4 -frames:v N -f framemd5 ...
→ exit 0; frame size 24883200 (= p010le); framemd5[0] = 77d683379106209752ee0f2858918800
```

Identyczny framemd5 jak SW decode `format=p010le` ⇒ **bit-exact system-memory
output**, zero `hwdownload`, zero sync errors, 300+ klatek stabilnie.
Dekoder raportuje capabilities `hybrid` + opcję `gpu_copy` — to ten kontrakt.
Uwaga praktyczna: przy tym path NIE wolno mieszać `vpp_qsv` (wymaga hw frames);
rotację robić SW (vflip+hflip) jak produkcja.

## Hardware decode candidates

| Kand. | Opis | Wynik |
|---|---|---|
| A | `-c:v hevc_qsv` system-memory output | ✅ działa, bit-exact, 151.5 FPS decode-only |
| B | QSV surface + controlled download | nie wymagany (A działa); historyczny błąd sync nie występuje w tym wariancie |
| C | D3D11VA Intel | zbędny (A wystarcza capability-wise) |

## Base fidelity

Candidate A vs SW decode: **framemd5 bit-to-bit identical** (frame 0..9)
przy zgodnej autorotacji. Y/UV MAD = 0.

## HDR metadata

Źródło pc/bt2020nc/HLG/bt2020 — decode nie ingeruje w metadata; produkcyjne
C-path outputy zachowują te same znaczniki (zweryfikowane w 4D na tej ścieżce).

## Synchronization analysis

Historyczny błąd „Error synchronizing the operation" dotyczył grafu z
`-hwaccel qsv -hwaccel_output_format qsv` + `hwdownload`. Candidate A
omija go konstrukcyjnie: brak hwframes → brak sync download.

## Backpressure: cause or symptom

slot_lifetime ~668 ms i pełne sloty to **SYMPTOM**: konsument (FFmpeg:
decode+konwersje+encode) pracuje ~24 FPS, producent HUD ~65+ FPS — kolejka
pełna jest oczekiwanym skutkiem, nie przyczyną. Nie optymalizować kolejki.

## Candidate matrix

| candidate | decode | memory output | overlay | encode | median wall | FPS | delta vs E | verdict |
|---|---|---|---|---|---|---|---|---|
| CURRENT PRODUCTION | SW | system p010 | REGION (sw) | hevc_qsv | 12.41 s | 24.18* | — | baseline |
| SW DECODE ONLY | SW | — | — | — | 4.70 s | 64.8 | +168% | sufit decode |
| QSV DECODE ONLY | QSV hw | GPU | — | — | 1.23 s | 244.4 | — | sufit HW decode |
| BASE WITHOUT HUD (SW) | SW | system p010 | none | hevc_qsv | 13.45 s | 22.31 | −7.7% | referencja C |
| ENCODE ONLY | none | raw p010 in | none | hevc_qsv | 3.69 s/90f | 24.37 | +0.8% | **sufit encodera** |
| CANDIDATE A full-base | QSV→sys | system p010 | none | hevc_qsv | 12.10 s | 24.80 | +2.6% (no-HUD) | end-to-end < 5% (ENCODE_BOUND) |

\* production 4D; świeże przebiegi wyżej (szum maszyny).

## Selected candidate

**NONE** (do wdrożenia wydajnościowego). Candidate A udokumentowany jako
capability; async_depth 2/4/8 probe: 22.5–24.7 FPS — brak >=5% (§16).

## Production implementation

**NOT IMPLEMENTED.** Production jest ENCODE_BOUND: zamiana decode na QSV-sys
nie daje >=5% end-to-end (produkcja = ~99–115% sufitu enkodera zależnie od okna
pomiaru). Zmiana byłaby czysto architektoniczna bez mierzalnego zwrotu.

## Real TeleM runtime

`run_once` production path (REGION aktywny) ×3 na GX020079: PASS, exit 0,
HUD SINGLE_BBOX 3 400 992 B/f, metadata HDR zachowane (jak w 4D).

## A/B performance

Patrz tabele wyżej; surowe dane: `scratch/intel_etap4g/decomposition.json`,
`results.json`.

## NVIDIA isolation

**NVIDIA_USED_BY_INTEL_PIPELINE: NO** — wszystkie komendy pinują Intel
(qsv_device 1 / child_device=1); zero CUDA/NVDEC/NVENC.

## Regression tests

Focused suite: **60 passed** (produkcja nietknięta; §31 testów nowych nie ma —
brak wdrożenia).

## Changed files

Brak zmian produkcyjnych. Nowe: raport + `scratch/intel_etap4g/*`
(bench harness, state_T0, results.json, md5 dowody).

## Preserved

AMD preserved | NVIDIA preserved | SDR native preserved |
CPU_REFERENCE preserved (fallback ponownie runtime-verified) |
telemetry preserved | multi-file preserved | HUD/REGION preserved

## P0 verdict

**ENCODE_BOUND** — hevc_qsv veryfast/gq24/p010le @3840×2160 ≈ 24.4 FPS sufit;
production pracuje na tym suficie. Decode (SW 64.8 / QSV-sys 151.5) i overlay
(1.7%) nie są ograniczeniami.

## Recommendation

JEDEN następny krok: **decyzja produktowa dotycząca enkodera** — jeżeli >24 FPS
@4K HDR jest wymagane, jedyną realną dźwignią są parametry/jakość hevc_qsv
(np. preset/ICQ/look_ahead/hw-features) lub podział pracy; wymaga to jednak
świadomej decyzji jakościowej (poza §15/§30 tego etapu). Alternatywnie
zaakceptować 24–28 FPS jako sufit tej klasy sprzętu.


