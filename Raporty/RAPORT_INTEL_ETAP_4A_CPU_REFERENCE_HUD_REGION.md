# RAPORT INTEL ETAP 4A — CPU_REFERENCE: instrumentacja + HUD REGION (SDR/P010)

Data: 2026-08-25 | Branch: `intel-render` | HEAD (start): `e019a6b45278f09f718f528642767f505ea87934`
Tryb: implementacja (ETAP 4A wg rekomendacji `RAPORT_INTEL_ETAP_4_PIPELINE_BOTTLENECK_AUDIT_OX.md`)
Commit: **brak (zgodnie z zadaniem — bez commits)**

## Zakres wykonany

1. **4A0 — instrumentacja + baseline Intel CPU_REFERENCE** (FULL_CANVAS).
2. **4A1 — HUD REGION transport dla CPU_REFERENCE** (SDR nv12 + HDR p010le) z kill-switchem.
3. Kontrolowane A/B interleaved + parity + testy jednostkowe + raport.

## Changed

### `src/ffmpeg/streaming.py`
- `_intel_hud_region_gate()` (nowa, ~linia 94): wspólna bramka bounded-HUD dla Intel.
  - Native (GPU-resident): bez zmian — decyduje `TELEM_INTEL_HUD_REGION` (ETAP 3C).
  - **CPU_REFERENCE (nowość 4A)**: własny switch `TELEM_INTEL_CPU_REF_HUD_REGION`
    (domyślnie **ON**), ograniczony do projektów **bez rotacji**
    (`rotation_degrees == 0 and container_rotation == 0`). Przy rotacji ≠ 0
    CPU_REFERENCE zachowuje zachowanie sprzed 4A (FULL_CANVAS) — uzasadnienie w sekcji „Rotacje".
  - Wywoływana raz per render; zero logowania per-frame; ASCII-safe.
- Blok REGION (d. linia 841): warunek `encoder == "intel" and not is_no_hud and
  _intel_hud_region_gate(...)` zamiast `... and intel_gpu_resident and env-check` —
  dzięki temu ten sam, już istniejący mechanizm (bbox → crop → overlay x/y → `-s WxH`)
  działa też dla CPU_REFERENCE.
- Nowy diagnostyczny print `[INTEL] HUD bbox ratio: X.XXX` (raz per render).
- `pipeline_audit`: `PipelineAuditRecorder()` tworzony też dla `encoder == "intel"`
  (opt-in `TELEM_PIPELINE_AUDIT`; NVIDIA bez zmian).

### `src/benchmark.py`
- `BenchmarkTracker.get_summary()`: dodane `median` i `p99` (obok avg/p95/min/max/count).

### `tests/test_video_helpers.py`
- Nowa sekcja „INTEL ETAP 4A" + helper `_cpu_ref_kwargs()`; **4 nowe testy**:
  1. `test_intel_cpu_ref_region_graph` — SDR: `-s 704x410`, `overlay=102:50`,
     `hwdownload,format=nv12`, brak `overlay_qsv`, `hevc_qsv`, `pix_fmt nv12`.
  2. `test_intel_cpu_ref_region_rotation_graphs` — rotacje 90/180/270 z wymiarami REGION:
     base dostaje `transpose=1` / `vflip,hflip` / `transpose=2`, overlay x/y i `-s` bez zmian.
  3. `test_intel_cpu_ref_region_hdr_p010_graph` — P010 SW-decode: bez `hwdownload`,
     `format=p010le[base]`, overlay x/y, `pix_fmt p010le`.
  4. `test_intel_hud_region_gate_switches` — bramka: native switch, CPU_REF switch,
     rotacje blokują CPU_REF, kill-switch działa.

## Root cause (problemu wydajnościowego)

CPU_REFERENCE przenosił pełny kanvas HUD RGBA przez SHM→pipe
(`overlay_w × overlay_h × 4` B/frame), podczas gdy aktywne piksele HUD zajmują
typowo ~10% pola. Pipeline audyt (ETAP 4) wskazał to jako P0. Rozwiązanie 4A
włącza istniejący mechanizm bounded-HUD (z ETAP 3C, dotąd native-only) dla
ścieżki CPU_REFERENCE: worker cropuje kanvas do wspólnego bboxa layoutu,
a graf FFmpeg pozycjonuje go `overlay=x:y` z wejściem rawvideo `-s bboxWxbboxH`.

## Wyniki pomiarów (kontrolowane A/B)

Materiał: `scratch/intel_etap3b/canonical_sdr_720p.mp4`, 180 klatek @30 fps,
layout `cluster` (speed/alt/dist w lewym-górnym klastrze), syntetyczna telemetria,
`TELEM_INTEL_GPU_RESIDENT=0`, hevc_qsv. Harness: `scratch/intel_etap4a/run_interleaved.py`
(naprzemiennie REGION/FULL w jednym procesie — odporność na dryf środowiska).

### 4K (3840×2160) — 3 pary, bez outlierów: **STRONG WIN**

| | REGION (mediana) | FULL (mediana) | Δ |
|---|---|---|---|
| wall | **6,50 s** | 10,81 s | **1,66× szybciej** |
| efektywny FPS | **27,68** | 16,65 | +66% |
| HUD transport | **3 310 592 B/f** | 33 177 600 B/f | **−90,0%** |

Przebiegi REGION: 6,30 / 6,50 / 6,95 s (rozrzut ~10%); FULL: 10,50 / 12,03 / 10,81 s.

Fazy (audyt, avg ms, para p2): `worker_shm_copy` 6,3 vs 78,6 (12× mniej bajtów),
`ffmpeg_stdin_write` 12,4 vs 39,1, `wait_for_free_slot` 11,2 vs 34,5,
`slot_lifetime` 290 vs 857. Koszt cropu: `worker_render` 4,27 vs 2,80 ms (+1,5 ms) — pomijalny.

### 1080p (1920×1080) — 4 pary (jedna z szumem środowiska): MODERATE WIN

Pary stabilne: REGION 5,89 / 3,93 / 4,30 s vs FULL 6,41 / 4,80 / 7,04 s
→ REGION szybszy o **8–39%** (typowo ~15–20%).
Transport: 8 294 400 → 850 048 B/f (**−89,7%**, bbox ratio 0,102).

### Baseline 4A0 (sprzed włączenia REGION; osobne procesy)

1080p FULL: mediana 4,735 s (38,0 FPS); 4K FULL: mediana 7,902 s (22,8 FPS).
Zapis: `scratch/intel_etap4a/baseline_1080p.json`, `baseline_4k.json`.
(Uwaga: baseline 4K był szybszy niż FULL w interleaved — patrz „Środowisko testów".)

## Parity (FULL vs REGION, CPU_REFERENCE 4K)

`scratch/intel_etap4a/parity.py`, pary `i4k_*_p2.mp4`, klatki t=0,5/3,0/5,0 s:

- **mean_abs_diff = 0.0, max_diff = 0, changed_px = 0** — wynik **bit-to-bit identyczny**
  (przy source-res: scale_x=scale_y=1, brak przeskalowania regionu).
- Wizualna weryfikacja arkusza `parity_4k/cmp_3.0.png` (FULL | REGION | amplified diff):
  identyczne, diff czarny.

## Rotacje — świadome ograniczenie zakresu (dokumentacja decyzji)

Inspekcja kodu (§7 zadania): `frame_renderer.render_overlay_frame` (ścieżka
multi-worker, używana przez CPU_REFERENCE) **nie obraca** kanvasu HUD wg
`effective_rotation`; obrót całego kanvasu istnieje tylko w (a) NVIDIA rot180
CUDA fast-path (`hud_rotate_180`) i (b) single-worker `render_frame_bytes_job`.
W grafach CPU_REFERENCE przy rotacji ≠ 0 obracany jest base video
(`vflip,hflip` / `transpose`), a HUD pozostaje w przestrzeni outputu.

Konsekwencja: crop bbox wyliczony w przestrzeni overlay jest bezpieczny tylko
gdy **brak jakiejkolwiek transformacji** (`rotation_degrees == 0 and
container_rotation == 0`). Dlatego gate 4A celowo ogranicza REGION do
projektów bez rotacji; przy rotacji ≠ 0 zachowane jest zachowanie sprzed 4A
(FULL_CANVAS). Grafy dla rotacji 90/180/270 z wymiarami REGION są pokryte
testem jednostkowym (poprawne: transpose/vflip+hflip + overlay x/y + `-s`),
więc ewentualne rozszerzenie w przyszłości ma gotowe podstawy.

## Fallback

- `scattered` layout (3 wskaźniki w 2 narożnikach): bbox ratio 0,617 < 0,85 →
  SINGLE_BBOX 5 172 000 B/f, wall 4,76 s ≈ FULL. Kryterium area (0.85) działa.
- Kill-switch: `TELEM_INTEL_CPU_REF_HUD_REGION=0` → dokładnie stan sprzed 4A.
- `TELEM_INTEL_HUD_REGION` (native) — nietknięty, domyślnie ON jak w ETAP 3C.

## Preserved

- **NVIDIA**: zero zmian w kodzie NV; testy NV (rot180 CUDA fast-path itd.) zielone;
  runtime NV nie był możliwy (brak HW) — *NVIDIA path preserved statically*.
- **AMD**: zero zmian; `test_amd_native_overlay_handoff` zielony;
  *AMD path preserved statically; runtime validation was not possible on this machine*.
- **Native Intel (QSV GPU-resident)**: ścieżka ETAP 3C bez zmian semantyki
  (testy region_cmd/p010 native zielone).
- **CPU_REFERENCE przy rotacji ≠ 0** i przy kill-switchu: status quo ante.
- Kolejność renderowania/z-order, telemetria, parsery, SmartSync, backend
  selection, FFmpeg/PyAV/Qt — nietknięte.

## Tested

- `python -m pytest tests/test_video_helpers.py tests/test_intel_backend.py
  tests/test_gpu_compositor.py tests/test_amd_native_overlay_handoff.py
  tests/test_etap5f_pipeline_audit.py -q` → **57 passed** (51 przed + 2 audit
  z ETAPU 5F narzędziowo + 4 nowe 4A; w tym regresje NV/AMD/native/HDR).
- Runtime CPU_REFERENCE: interleaved A/B 1080p (4 pary) i 4K (3 pary),
  sanity REGION, scattered fallback — łącznie ~20 renderów 180-f.
- Parity: ekstrakcja 3 klatek/para, metryki pikselowe + wizualna inspekcja PNG.
- AST/parse check po każdej edycji `streaming.py`.

## Hardware tested

- Intel runtime: **tested** (iGPU QSV decode/encode + SW overlay; CPU_REFERENCE i native grafy).
- AMD runtime: not available.
- NVIDIA runtime: not available.

## Not tested

- Real GUI / fizyczna mysz — poza zakresem (headless harness CLI).
- HDR/P010 **runtime parity** (brak źródła HDR w scratch; pokryte grafowo testem).
- `target_res ≠ source` (scale ≠ 1): parity bit-exact pokazana tylko dla
  source-res; przy przeskalowaniu regionu vs pełnego kanvasu bilinear może
  dawać subpikselowe różnice na krawędziach bboxa (semantycznie poprawne;
  do osobnej weryfikacji, jeśli wymagana).
- Multi-file / GPMF — poza zakresem 4A.

## Performance

Patrz sekcja „Wyniki pomiarów". Kluczowe: **4K: 1,66× wall (16,7→27,7 FPS),
−90,0% transportu HUD; 1080p: ~8–39% (moderate)**. Koszt cropu ~+1,5 ms/frame.
Pamięć SHM pool 4K: 22×31,6 MB → 22×3,2 MB (−665 MB).

## Środowisko testów — ważne zastrzeżenie

Maszyna była w trakcie testów **równoległej sesji** (obce wywołania ffmpeg QSV
widoczne w historii terminala). Objawy: sporadyczne ~30-s stalle PRZED pierwszą
klatką (`first_sched` 30 s w audit lifecycle; para-0 1080p: 79,7 s), także w
wariancie FULL. Dlatego:
- wyniki oparte o **mediany przebiegów naprzemiennych** w jednym procesie,
- para z outlierem oznaczona i wykluczona z wniosków (pozostaje w JSON),
- 4K (3/3 pary spójne) uznane za miarodajne; 1080p za kierunkowe.
Instrumentacja audytu (fazy) była kluczowa do lokalizacji stallów.

## Zdarzenia procesowe (dla kontekstu)

- 10:04:22/32 — IDE Save-All dotknął `streaming.py`/`benchmark.py` w trakcie
  edycji (treść = wyłącznie moje zmiany; zweryfikowane diffem/hunkami 13=12+1).
  Spowodowało przejściowe race w edytorze („text not found") — bez skutków
  treściowych.

## Risks / Remaining issues

1. Contention QSV przy współdzielonej maszynie może wpływać na pomiary —
   przy kolejnych benchmarkach stosować interleaved + mediana (harness gotowy).
2. P010 runtime parity i scale≠1 parity — do dedykowanej weryfikacji.
3. `hud_regions` (DIRECT_REGION, per-wskaźnik) pozostaje poza CPU_REFERENCE —
   potencjalny ETAP 4B/4C (dalsza redukcja przy rozproszonych layoutach).
4. 89 MB `scratch/intel_etap3b/cpu.log` nadal nie-gitignore'owany (z audytu 3B).

## Artefakty

- `scratch/intel_etap4a_state_before.json` / `scratch/intel_etap4a_state_after.json`
  (SHA-256 9 plików przed/po; po: zmienione tylko streaming.py, benchmark.py,
  test_video_helpers.py).
- `scratch/intel_etap4a/`: harness (`run_cpu_ref_ab.py`, `run_interleaved.py`,
  `parity.py`, `lifecycle_breakdown.py`), wyniki JSON (baseline/ab/interleaved/
  scattered/sanity + audyty per-run), `parity_4k/cmp_3.0.png` (dowód wizualny),
  `parity_4k/parity.json`. Duże artefakty (raw ×2 ≈ 300 MB, mp4 diagnostyczne)
  usunięte po pomiarach; katalog ~14 MB.

## Report

`Raporty/RAPORT_INTEL_ETAP_4A_CPU_REFERENCE_HUD_REGION.md` (ten plik).

