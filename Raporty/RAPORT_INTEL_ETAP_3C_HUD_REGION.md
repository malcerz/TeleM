# TeleM — INTEL ETAP 3C: bounded HUD region upload

Data pomiaru: 2026-08-25. Testy wykonano na aktualnym FFmpeg `2026-08-17-git-426841da9d-full_build-www.gyan.dev`, z dynamicznie wybranym Intel UHD Graphics 730 (`vendor_id=0x8086`).

## Root cause

Native Intel generował pełny transparentny RGBA canvas, który był przesyłany przez pipe i uploadowany do `overlay_qsv`. Koszt wynosił 3.52 / 7.91 / 31.64 MiB na klatkę dla 720p / 1080p / 4K.

## Architecture before / after

Przed zmianą:

`full HUD canvas -> rawvideo pipe -> hwupload=derive_device=qsv -> overlay_qsv`

Po zmianie dla bezpiecznego, małego union bbox:

`conservative HUD bbox -> crop/render region -> rawvideo pipe -> hwupload=derive_device=qsv -> overlay_qsv at bbox x/y`

Video pozostaje GPU-resident; nie wprowadzono pełnego GPU->CPU readbacku obrazu.

## BBox source and safety

Region korzysta z istniejącego `get_layout_hud_bbox()`, który wyznacza konserwatywne bounds aktywnych indicatorów według ich geometrii/formy, z marginesami dla tekstu, gauge, bar, map i pozostałych rodzin. Renderer używa istniejącego `hud_bbox` i cropuje po renderowaniu bez mutowania layoutu użytkownika. Region jest clampowany do canvasu, a jego pozycja/dimensions są rozszerzane do bezpiecznych parzystych wartości.

Nie zmieniono geometrii ani kolejności renderowania. Dla bbox obejmującego co najmniej 85% canvasu pozostaje `FULL_CANVAS`. Mechanizm można wyłączyć diagnostycznie przez `TELEM_INTEL_HUD_REGION=0`, co posłużyło do wariantu FULL.

## Transport measurements

Wszystkie testy: 29.97 fps, 180 klatek, 8-bit RGBA/BGRA.

| resolution | full B/frame | region B/frame | reduction | full MiB/s | region MiB/s |
|---|---:|---:|---:|---:|---:|
| 1280x720 | 3,686,400 | 185,472 | 95.0% | 105.4 | 5.3 |
| 1920x1080 | 8,294,400 | 308,096 | 96.3% | 237.0 | 8.8 |
| 3840x2160 | 33,177,600 | 854,784 | 97.4% | 948.1 | 24.4 |

## Performance

Short real SDR runs, same Intel QSV settings and same logical HUD. Effective FPS is 180 / wall time.

| resolution | FULL wall | REGION wall | FULL FPS | REGION FPS | speedup |
|---|---:|---:|---:|---:|---:|
| 1280x720 | 4.397 s | 3.693 s | 40.9 | 48.7 | 1.19x |
| 1920x1080 | 5.243 s | 4.801 s | 34.3 | 37.5 | 1.09x |
| 3840x2160 | 11.090 s | 8.537 s | 16.2 | 21.1 | 1.30x |

`ffmpeg_write`:

- 720p FULL avg 14.31 ms / p95 40.43 ms; REGION avg 12.65 ms / p95 33.06 ms.
- 1080p FULL avg 20.42 ms / p95 70.10 ms; REGION avg 17.25 ms / p95 59.98 ms.
- 4K FULL avg 54.44 ms / p95 191.11 ms; REGION avg 38.26 ms / p95 159.64 ms.

CPU HUD generation was not separately instrumented in this stage; the measured improvement therefore includes the reduced shared-memory slot, pipe and upload costs, while indicator rendering remains the same renderer.

## Visual parity

FULL vs REGION was compared on the canonical 720p run at 0.5 s, 3.0 s and 5.0 s. Both use the same D3D11/QSV compositor and encoder settings; small differences are attributable to separate QSV encode runs.

| timestamp | mean diff | max diff | changed pixels >2 |
|---|---:|---:|---:|
| 0.5 s | 1.3462 | 14 | 27.4886% |
| 3.0 s | 1.3174 | 14 | 27.7707% |
| 5.0 s | 1.2286 | 13 | 25.2086% |

No bbox-edge clipping, opaque border, alpha halo or HUD displacement was observed in the control frames. Z-order remains one composed HUD region and one `overlay_qsv` operation.

## Changed files

- `src/ffmpeg/streaming.py`: Intel-only bbox selection, clamp/alignment, FULL_CANVAS fallback and one-shot transport diagnostics.
- `tests/test_video_helpers.py`: Intel region command assertions.
- `Raporty/RAPORT_INTEL_ETAP_3C_HUD_REGION.md`: this report.

No AMD, NVIDIA, GUI, telemetry, map, timeline or native eligibility changes were made. HDR/10-bit/HLG/PQ, rotation, multi-file and cut regions remain outside Intel native eligibility.

## NVIDIA isolation

`NVIDIA_USED_BY_INTEL_PIPELINE: NO`. Logs show NVIDIA adapter ignored under `INTEL_FORCE`; no CUDA, NVDEC, NVENC, `overlay_cuda`, `hwupload_cuda` or `scale_cuda` entered the Intel graphs.

## Tests

Focused regression: `51 passed in 1.18s`:

`tests/test_intel_backend.py`, `tests/test_video_helpers.py`, `tests/test_gpu_compositor.py`, `tests/test_amd_native_overlay_handoff.py`.

Tests cover Intel native/CPU graph separation and bounded region dimensions/origin. Existing shared bbox helper tests remain unchanged; AMD/NVIDIA paths were not runtime-tested and were preserved statically.

## Preserved

AMD preserved. NVIDIA preserved. CPU reference preserved. Telemetry, multi-file behavior and HDR semantics untouched. Full HUD fallback retained. Native Intel eligibility not broadened.

## New bottleneck

Region transport is no longer dominant for the tested HUD: traffic falls by 95.0–97.4% and wall time improves 9–30%. Remaining cost is primarily Intel QSV video scaling/compositing/encoding plus CPU HUD generation and process-pool scheduling. CPU HUD generation was not isolated, so it is the next measured suspect rather than an implemented assumption.

## Recommendation

Instrument per-frame CPU HUD generation stages (`compose_overlay`, indicator rendering and RGBA preparation) separately from pipe/write and QSV timing before attempting any further renderer or GPU-font work.
