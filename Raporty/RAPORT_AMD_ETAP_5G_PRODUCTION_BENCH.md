# RAPORT AMD — ETAP 5G-FINAL-PRODUCTION-BENCH
# Benchmark wydajności 5G w prawdziwym produkcyjnym pipeline D3D11VA + GPU MAP

**Status: ✅ PASS** — 5G działa w prawdziwym D3D11VA production path.
**GPU MAP GAIN: +54.9 %** (mediany, ta sama sesja, D3D11VA hardware decode).

> Ten etap to WYŁĄCZNIE benchmark wydajności. Correctness mapy (PASS-VISUAL)
> została zamknięta wcześniej w 5G-VALIDATION na czystym źródle. Nie powtarzano
> żadnych testów obrazu. **Brak zmian produkcyjnych. STOP — nie rozpoczęto 5H.**

---

## SOURCE

```
Video/GX020079.mp4
```

| Element | Wartość |
|---|---|
| Original GoPro | **YES** — 3840×2160, HEVC Main10, BT.2020/HLG (`bt2020nc`/`arib-std-b67`), full-range, 1131 klatek, oryginalny plik kamery (VUI `primaries=9/transfer=16`, MF SAMPLE `array=11`) |
| Clean | N/A — wiadomo, że plik zawiera stary overlay; **nieistotne dla benchmarku** (tylko wydajność) |
| Re-encode do benchmarku | **NIE** — użyty oryginalny plik |

---

## DECODE

```
AMD_NATIVE_DECODE_MODE=GPU_HUD_D3D11VA
```

| Element | Wartość |
|---|---|
| D3D11VA | **YES** (`hardware_acceleration_confirmed=True`, `decode_mode=GPU_HUD_D3D11VA`) |
| P010 | **YES** (`decoder_output_format=DXGI_FORMAT_P010`) |
| Direct decoder→VP | **YES** (`direct_decoder_surface_to_vp_frames=1131`, `decoder_gpu_copy_frames=0`) |
| CPU raw base | **0** (`rawvideo_pipe=False`) |
| CPU→GPU base | **0** |
| GPU→CPU base | **0** |

> Bramka sekcji 2 spełniona — **nie wystąpił CPU decode fallback**. Benchmark jest ważny.

---

## RUNS (każdy pełny: 1131 frames, ta sama sesja, D3D11VA)

Ustawienia wszystkich runów: `AMD_OVERLAY_PROFILE=0`, `AMD_NATIVE_PROFILING=0`,
`AMD_NATIVE_DIAGNOSTICS=0`, `AMD_MAP_AB_READBACK=0`, `AMD_NATIVE_DECODE_MODE=GPU_HUD_D3D11VA`.
Brak innych testów pomiędzy runami.

| Run | Ścieżka mapy | Wall-clock | TRUE FPS | Frames | AMF drops |
|---|---|---|---|---|---|
| A | CPU_REFERENCE | 96.9 s | **11.675** | 1131/1131 | 0 |
| B | GPU | 66.2 s | **17.083** | 1131/1131 | 0 |
| C | CPU_REFERENCE | 87.0 s | **12.994** | 1131/1131 | 0 |
| D | GPU | 53.5 s | **21.126** | 1131/1131 | 0 |

Pliki: `VAL/pcA_cpu_ref.mp4`, `VAL/pcB_gpu.mp4`, `VAL/pcC_cpu_ref.mp4`, `VAL/pcD_gpu.mp4` (+ `.amd_profile.json`).

---

## MEDIANY / GAIN

```
CPU_REFERENCE MEDIAN:  12.334 FPS   (A=11.675, C=12.994)
GPU MAP MEDIAN:        19.105 FPS   (B=17.083, D=21.126)
GAIN:                  +54.9 %
```

- GPU szybszy w OBU parach (11.7→17.1; 13.0→21.1).
- GPU runy rosną w czasie (B=17.1 → D=21.1) — steady-state/warm-up GPU.
- Nie porównywano pojedynczego najlepszego runu — **mediany z 2 przebiegów**.

---

## GPU PROFILE (osobny profiling run, 300 klatek — NIE do TRUE FPS)

Run: `VAL/pc_profile_gpu300.mp4` (`AMD_OVERLAY_PROFILE=1`, `AMD_NATIVE_PROFILING=1`,
`AMD_MAP_STATS=1`, D3D11VA, GPU map). Czasy mediana/klatkę:

| Etap | med (ms) | Źródło |
|---|---|---|
| decode (MF ReadSample/decode availability) | 0.730 | native (profiling) |
| telemetry (`prepare_overlay_frame_data`) | 3.026 | overlay profile |
| compose_overlay | **17.423** | timing (produkcja B/D: 24.59 / 21.14) |
| HUD buffer prep (`PIL/buffer preparation`, ~8.4 MB/fr) | **9.312** | timing |
| HUD upload (`HUD texture upload`) | 1.535 | timing |
| map CPU crop+marker (izolowany pomiar) | 0.78 | `scratch/timing_map_split.py` |
| map tobytes 692×692 RGBA (izolowany pomiar) | 1.38 | `scratch/timing_map_split.py` |
| map upload (native `UpdateSubresource`) | 0.197 | `AMD_MAP_STATS=1` |
| map GPU resize+blend submit (Pass1+Pass2+Flush) | 0.191 | `AMD_MAP_STATS=1` |
| VP CPU submit | 0.402 | native |
| AMF submit/backpressure | 0.275 | native |
| AMF QueryOutput / Packet write | 0.144 / 0.173 | native |

> Uwaga: `VideoProcessor GPU completion` (med ~13.3 ms) i `GPU wait` (med ~14.7 ms)
> są mierzone **z wymuszonym wait** (profilowanie). W produkcji (profiling OFF) nie są
> blokujące — dlatego NIE używano profiling run do TRUE FPS.

---

## MAP PATH (GPU)

| Element | Wartość |
|---|---|
| Pillow LANCZOS mapy | **0 calls/frame** (mapa usunięta z `compose_layout`; `PIL tobytes`=0; brak `track_map` w compose) |
| CPU map generation (crop+marker 692×692) | 0.78 ms med (izolowany) |
| Map tobytes | 1.38 ms med (izolowany) |
| Map upload CPU→GPU (native) | 0.197 ms med |
| GPU Lanczos 692→691 + blend | 0.191 ms med (resize+blend submit) |
| GPU→CPU map | **0 MiB/frame** (readback OFF) |
| Upload mapa | **1.827 MiB/frame** (692×692×4) |

Map bbox: `(3035, 137, 691, 691)`, working 692×692, output 691×691.

---

## FRAME ACCOUNTING (każdy production run A–D)

```
source = 1131
decoded = 1131
D3D surfaces (mf_d3d11_surfaces) = 1131
VP = 1131
HUD = 1131
AMF submitted = 1131
AMF output = 1131
muxed = 1131
AMF drops = 0, retries = 0, input_full = 0
```

---

## TOP 10 CURRENT BOTTLENECKS

1. **compose_overlay (Pillow HUD compose)** — med 21.1–24.6 ms (produkcja GPU). Nadal
   największy koszt CPU; mapa już usunięta, reszta HUD (teksty, gauge, wykresy) Pillow.
2. **HUD buffer prep** (`PIL/buffer preparation`) — med 9.31 ms; Python→NumPy dirty-copy
   ~8.4 MB/frame do bufora backing (5 rectów/klatkę, tryb DIRTY).
3. **telemetry/frame_data** — med 3.0–6.5 ms (`resolve_cache_value` ~1.1, interpolacja ~1.9).
4. **map CPU praca** — razem ~2.0–2.5 ms: tobytes 1.38 + crop+marker 0.78 + upload 0.20.
5. **HUD texture upload Python→GPU** — med 1.54 ms (~8.4 MB/fr dirty rects).
6. **VideoProcessor GPU blit** — ~13 ms (pomiar z wait; w produkcji nakładane na CPU).
7. **MF ReadSample/decode availability** — med 0.73 ms.
8. **AMF submit/backpressure** — med 0.28–0.54 ms.
9. **VP CPU submit** — med 0.40 ms.
10. **AMF QueryOutput / Packet write** — med 0.14–0.17 ms.

---

## ODPOWIEDZI WPROST

1. **Czy benchmark rzeczywiście używał D3D11VA?** Tak — `GPU_HUD_D3D11VA`,
   hardware decode = YES, P010, direct decoder→VP = 1131/1131, `rawvideo_pipe=False`.
2. **Czy base video pozostawało cały czas na GPU?** Tak — CPU raw base 0, CPU→GPU base 0,
   GPU→CPU base 0 (zero transferów base'u; dekodowanie D3D11VA → P010 → VP na GPU).
3. **Medianowy CPU_REFERENCE FPS?** **12.334 FPS** (A=11.675, C=12.994).
4. **Medianowy GPU MAP FPS?** **19.105 FPS** (B=17.083, D=21.126).
5. **Rzeczywisty zysk 5G w production pipeline?** **+54.9 %** (mediany, ta sama sesja,
   D3D11VA). Wcześniejsze +40.5 % (5G-VALIDATION, CPU-decode reference) **potwierdza się
   i jest wyższe** w prawdziwym D3D11VA.
6. **Największy bottleneck?** `compose_overlay` (Pillow HUD compose, med ~21–25 ms)
   + `HUD buffer prep` (med ~9.3 ms) — to one tworzą CPU floor; VP GPU (~13 ms) i AMF
   nie są limitujące (drops 0, FPS 17–21).
7. **Co powinien optymalizować ETAP 5H?** (tylko notatka — nie implementowano)
   1. Ograniczyć/GPU-ować resztę `compose_overlay` (teksty/gauges/wykresy) — największy koszt.
   2. Zredukować `HUD buffer prep` (8.4 MB/fr dirty-copy; mniejsze recty / zero-copy).
   3. Przyspieszyć `telemetry/frame_data` (cache `resolve_cache_value`/interpolacji).
   4. `map tobytes` (1.38 ms) — zero-copy buffer dla uploadu mapy.

---

## PLIKI / ARTEFAKTY

- `Raporty/AMD_ETAP5G/VAL/pc_d3d11va_verify31b.mp4` — weryfikacja D3D11VA (31 kl.)
- `Raporty/AMD_ETAP5G/VAL/pcA_cpu_ref.mp4`, `pcB_gpu.mp4`, `pcC_cpu_ref.mp4`, `pcD_gpu.mp4` (+ profiles) — A/B/C/D
- `Raporty/AMD_ETAP5G/VAL/pc_profile_gpu300.mp4` (+ profile) — profiling run GPU
- `scratch/timing_map_split.py` — izolowany pomiar crop+marker vs tobytes

**STOP — raport gotowy. Nie implementowano ETAPU 5H. Nie zmieniano kodu produkcyjnego.**
