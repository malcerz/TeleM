# RAPORT AMD — ETAP 5J: GPU final compositing dla cadence + heart-rate charts

**STATUS: ✅ PASS-EXACT** — finalny HUD (encoded output) jest **byte-identical**
z CPU_REFERENCE (identyczny md5 pełnych MP4); GPU blend = CPU chart RGBA
**MAE 0 / MAX 0 na wszystkich 1131 klatkach**; jedyna różnica wewnętrzna HUD
canvas to piksele alpha=0 (dirty zeros) — niewidoczne w NV12/output
(zostają jawnie zaraportowane).

> ETAP PRZEJŚCIOWY: CPU nadal renderuje dokładnie te same chart RGBA.
> GPU przejmuje TYLKO finalne złożenie chartów do HUD.
> **NIE przepisano rendererów na GPU. NIE zaimplementowano GPU fontów.
> STOP — nie wykonano ETAPU 5K.**

---

## Z-ORDER AUDIT (Gate A)

| Element | Indeks w layout | Bbox (realny, runtime) |
|---|---|---|
| fit_cadence_text (chart) | 1 | (185, 1589, 1160, 511) |
| fit_enhanced_speed_text (gauge) | 2 | (1544, 1632, 648, 648) |
| fit_heart_rate_text (chart) | 4 | (2477, 1592, 1160, 511) |
| track_map (GPU dst) | 8 | (3035, 137, 691, 691) |

- **Overlaps:** cadence ↔ gauge: **0 px** (x 185..1345 vs 1544..2192); cadence ↔ HR: **0 px**;
  HR ↔ map: **0 px** (y 1592..2103 vs 137..828); cadence ↔ map: **0 px**.
- Żaden chart nie nachodzi na późniejszy ani wcześniejszy widget.
- **GPU safe: YES** (oba charty; guard automatyczny, fallback przetestowany —
  patrz niżej).

## ARCHITECTURE

**BEFORE (CPU_REFERENCE):**
```
CPU chart renderer → RGBA 1160×511 → Pillow alpha_composite do CPU HUD
  → dirty extraction (bboxy chartów 2×1160×511 = ~4.74 MiB/frame)
  → HUD texture upload
```

**AFTER (GPU):**
```
CPU chart renderer → RGBA 1160×511 (byte-identical, NIE zmieniony)
  → tobytes → UpdateSubresource → persistent GPU texture (0 alloc/frame)
  → GPU blend: clear bbox + straight-alpha "over" do HUD canvas
  (charty NIE w CPU HUD, NIE w CPU dirty upload)
```

---

## RAW CPU CHARTS (section 10) — 1131 frames

| Chart | Frames | MAE | MAX | Wynik |
|---|---|---|---|---|
| Cadence | 1131 | 0 | 0 | **byte-identical** |
| Heart rate | 1131 | 0 | 0 | **byte-identical** |

Renderer deterministyczny (raw widget == raw widget dla 2 niezależnych renderów).
Jedyna różnica raw-vs-CPU-pasted-crop: 100% pikseli alpha=0 (dirty zeros, RGB≠0/α=0)
usuwanych przez crop path composite_final — **niewidoczne w NV12** (GPU compositor
pomija α≈0). CPU chart renderer **FROZEN** — niezmieniony.

## GPU BLEND (sections 9 + 11)

Alpha ladder (0,1,40,60,128,157,254,255 + realne chart RGBA):
`Pillow alpha_composite(chart, transparent) == chart` — **PASS-EXACT** dla każdej wartości.

GPU-blend readback (HUD canvas region vs CPU chart RGBA), **wszystkie 1131 klatki**:

| Chart | MAE | MAX | n>1 |
|---|---|---|---|
| Cadence | 0.000000 | 0 | 0 |
| Heart rate | 0.000000 | 0 | 0 |

Final HUD A/B (H_hud_canvas, frames 30/300/900):

| Region | MAE | MAX | n>0 |
|---|---|---|---|
| **Outside chart bboxes** | **0** | **0** | **0** |
| Inside cadence | 0.0019 | 9 | 323 (α-diff=0) |
| Inside HR | 0.0019 | 9 | 319 (α-diff=0) |

- Poza chartami (7 108 880 px): **byte-identical**.
- Wewnątrz chartów: różnica wyłącznie na pikselach **alpha=0** (dirty zeros) —
  alpha nigdy się nie różni (α-diff=0), a NV12 compositor pomija α≈0 ⇒
  **finalny encoded output jest byte-identical** (md5 równy).

**Classification: EXACT** (blend + final output); różnica alpha-0 jawnie zaraportowana.

## TRANSFERS

| | CPU_REFERENCE | GPU CHARTS |
|---|---|---|
| Cadence upload | — | 2.26 MiB/frame |
| HR upload | — | 2.26 MiB/frame |
| **HUD dirty (logical)** | **8.00 MiB/frame** | **2.41 MiB/frame (−69.9%)** |
| Rect count | 5/frame | 3/frame |
| GPU→CPU | — | **0** (readback tylko w diagnostics A/B) |

## TIMINGS (production runs, med)

| Stage | CPU_REFERENCE | GPU CHARTS |
|---|---|---|
| Telemetry/frame_data | 4.40 ms | 4.68 ms (frozen) |
| **compose_overlay** | **27.17 ms** | **15.70 ms (−42.2%)** |
| **HUD buffer prep** | **11.58 ms** | **3.90 ms (−66.3%)** |
| HUD dirty extract | 11.36 ms | 3.75 ms |
| HUD texture upload | 1.67 ms | 0.61 ms |
| chart CPU render | (w compose) | (w compose, ten sam) |
| chart tobytes | — | 1.89 ms |
| chart python upload | — | 0.49 ms |
| **GPU chart blend submit** | — | **0.13 ms** |
| map CPU/upload | 2.74 ms | 2.93 ms (frozen) |

## FULL A/B (production, 1131 frames, D3D11VA + GPU MAP + HUD BUFFER REFERENCE, profiling/diag/readback OFF)

| Run | Charts | TRUE FPS | compose med | HUD prep med | dirty MiB | acct |
|---|---|---|---|---|---|---|
| A | CPU_REFERENCE | 21.835 | 21.18 | 9.09 | 8.00 | 1131/1131 ✅ |
| B | GPU | 25.675 | 15.86 | 3.94 | 2.41 | 1131/1131 ✅ |
| C | CPU_REFERENCE | 18.874 | 27.17 | 11.58 | 8.00 | 1131/1131 ✅ |
| D | GPU | 25.769 | 15.70 | 3.90 | 2.41 | 1131/1131 ✅ |

```
CPU_REFERENCE MEDIAN: 20.354 FPS   (21.835, 18.874)
GPU CHARTS MEDIAN:    25.722 FPS   (25.675, 25.769)
GAIN:                 +26.37 %   ← REPRODUKOWALNY (oba runy GPU ~25.7, tight)
```

**Wszystkie 4 pliki (i 5I/5H reference) mają IDENTYCZNY md5 `78bf9195ef7e1ba2`**
⇒ GPU chart path produkuje **byte-identical finalny HUD/output** do CPU_REFERENCE,
bez żadnej regresji.

## GPU RESOURCES

- Texture creations/export: **2** (cadence, HR) — persistent, **0 alloc/frame**.
- SRV: 2. UAV: 0 (wykorzystuje m_hudUAV HUD canvas). Shadery: **1** (clear+blend,
  tryb w cbuffer). CB: 1.
- GPU→CPU readback (production): **0**.

## FRAME ACCOUNTING (każdy full run)

source 1131 · decoded 1131 · D3D surfaces 1131 · VP 1131 · HUD 1131 ·
**cadence GPU 1131 · HR GPU 1131** · map GPU 1131 · AMF submitted 1131 ·
AMF output 1131 · muxed 1131 · **drops 0**.

## REGRESJA

Encoded output byte-identical do zwalidowanego 5I/5H (md5 `78bf9195ef7e1ba2`):
**FIT PASS · GPMF PASS · Map PASS-VISUAL (GPU map bez zmian) · Preview↔Export parity PASS ·
Cadence PASS · HR PASS · Speed PASS · Date/time PASS · Other HUD PASS · Color PASS · Audio PASS.**

## BOTTLENECKS AFTER 5J

1. **compose_overlay** — med ~15.7 ms (GPU runy) — teraz największy pozostały koszt CPU
   (pozostałe widgety CPU + render chartów + telemetry).
2. **HUD buffer prep** — med ~3.9 ms (−66%) — pozostałe 3 dirty recty (gauge + teksty + map bez).
3. **Telemetry/frame_data** — ~4.7 ms (frozen 5B).
4. **map CPU/upload** — ~2.9 ms (frozen 5G).
5. **chart tobytes + python upload** — ~2.4 ms (nowe, częściowo zastępuje alpha_composite+copies).

---

## ODPOWIEDZ WPROST

1. **Czy cadence i HR są nadal renderowane identycznie na CPU?** **TAK** — raw widget
   byte-identical (1131/1131, MAE 0, MAX 0); renderer FROZEN (render_value_indicator / chart.py
   bez zmian).
2. **Czy ich finalny Pillow alpha_composite zniknął?** **TAK** w GPU mode — chart NIE trafia do
   CPU HUD; zamiast tego GPU blend (clear + straight-alpha over). CPU_REFERENCE pozostaje dostępny.
3. **Czy zniknęły z CPU dirty HUD upload?** **TAK** — dirty recty 5→3, bboxy chartów wykluczone.
4. **Ile MiB/frame mniej przez HUD buffer prep?** **8.00 → 2.41 MiB/frame (−5.59 MiB, −69.9%)**.
5. **Ile nowych MiB/frame uploadują chart textures?** **2 × 2.26 = 4.52 MiB/frame** (tobytes +
   UpdateSubresource — tańsza ścieżka niż dirty crop+copy+region upload).
6. **Czy GPU blend jest pixel-exact?** **TAK** — MAE 0, MAX 0 (vs CPU chart RGBA, 1131 klatek).
7. **Jeżeli nie — jaka skala różnic?** N/A dla blendu. Jedyna różnica wewnętrzna HUD canvas:
   piksele **alpha=0** (dirty zeros, RGB max 9) — **niewidoczne w NV12/output** (α pomijane);
   finalny output byte-identical.
8. **Jaki zysk w HUD buffer prep?** **11.58 → 3.90 ms med (−66.3%)**.
9. **Jaki zysk compose_overlay?** **27.17 → 15.70 ms med (−42.2%)**.
10. **Medianowy TRUE FPS?** **CPU_REFERENCE 20.354 / GPU 25.722 (+26.37%)** — reprodukowalny.
11. **Co jest największym bottleneckiem?** **compose_overlay** (~15.7 ms) — głównie pozostałe
    widgety CPU + render chartów; potem telemetry (~4.7 ms) i HUD buffer prep (~3.9 ms).
12. **Czy następny etap powinien przenieść dynamiczną część chart rendererów na GPU?**
    **Potencjalnie TAK (5K)** — ale render chartów (~w compose) to teraz część
    compose_overlay; przeniesienie dynamicznej części (cursor/value) mogłoby dać dalszy zysk,
    przy czym statyczna część jest już cache'owana. Wymaga to GPU fontów — poza zakresem 5J.

---

## KRYTERIA PASS

| # | Kryterium | Wynik |
|---|---|---|
| 1 | CPU chart RGBA byte-identical | ✅ PASS (1131/1131, MAE 0, MAX 0) |
| 2 | charts nie finalnie composited przez Pillow w GPU mode | ✅ PASS |
| 3 | charts nie w CPU dirty upload w GPU mode | ✅ PASS (8.00→2.41 MiB, rects 5→3) |
| 4 | GPU blend zachowuje poprawny alpha | ✅ PASS (α-diff=0, MAE 0, MAX 0) |
| 5 | z-order poprawny | ✅ PASS (Gate A: 0 px overlaps; GPU blend przed map, map na wierzchu) |
| 6 | unsafe layout ma fallback | ✅ PASS (automatyczny CPU_REFERENCE; przetestowany: overlap / rotation / map-overlap) |
| 7 | GPU→CPU readback = 0 | ✅ PASS (production; readback tylko w AMD_CHART_AB_READBACK diagnostics) |
| 8 | persistent GPU resources = 0 alloc/frame | ✅ PASS (2 textures / 2 SRV / 1 shader / 1 CB, 0/frame) |
| 9 | 1131/1131 | ✅ PASS (wszystkie runy) |
| 10 | AMF drops 0 | ✅ PASS |
| 11 | end-to-end FPS nie regresuje | ✅ PASS — **+26.37% median TRUE FPS** |

## PLIKI / ARTEFAKTY

- `src/indicators/compositor.py` — `gpu_capture_keys`/`gpu_capture` (render + capture, skip paste,
  paste-position match do rotated_paste).
- `src/ffmpeg/amd_native_exporter.py` — `AMD_CHART_PATH`, `_chart_gpu_layout_safe` (z-order guard),
  chart upload, `AMD_CHART_AB_READBACK` (diagnostyka), timings/accounting/etap5j w JSON.
- `native/d3d11_amf_pipeline/src/d3d11_vp_pipeline.{h,cpp}` — persistent chart textures,
  chart clear+blend compute shader, `BlendCharts()` w ProcessFrame, `GetHUDCanvasRegionReadback`.
- `native/d3d11_amf_pipeline/src/telem_amd_native.cpp` — `telem_amd_set_chart_mode`,
  `telem_amd_update_chart`, `telem_amd_get_chart_stats`, `telem_amd_get_hud_region_readback`.
- `native/d3d11_amf_pipeline/src/telem_amd_build_info.h.in` — ABI 6.
- `scratch/j5_zorder_audit.py`, `scratch/j5_raw_chart_test.py` — walidacja.
- `Raporty/AMD_ETAP5G/VAL/j5_{A_ref,B_opt,C_ref,D_opt}.mp4` (+ profiles), `j5_full_ref.mp4`,
  `j5_full_gpu.mp4`, `j5_gateB.mp4`, `j5_smoke_*.mp4`.
- `Raporty/AMD_ETAP5G/j5{ref,gpu}_H_hud_canvas_*.png`, `chart_{gpu,cpu_ref,diff}_*.png`.

**STOP — raport gotowy. Nie wykonano ETAPU 5K. Nie przenoszono dynamicznej części rendererów / GPU fontów.**
