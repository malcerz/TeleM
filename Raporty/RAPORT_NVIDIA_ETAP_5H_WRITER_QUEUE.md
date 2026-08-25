# TeleM — NVIDIA ETAP 5H: Post-Zero-Copy Writer / Queue Tuning

Data: 2026-08-20. Pomiary wykonano na aktualnym repozytorium po ETAPIE 5G.

## A. Post-5G lifecycle

Konfiguracja referencyjna:

```text
GX030120.MP4 + Popoludniowa_jazda_na_rowerze_solar_battery.fit
5400 frames, 29.970 FPS
DIRECT_REGION / MULTI_REGION_ATLAS / atlas 1900x762
workers=4, MAX_IN_FLIGHT=8, preview=ON
zero_copy=5400/5400, fallback=0
```

Świeży audyt po 5G i po korekcie timestampów. Wartości w ms:

| Faza | avg | median | p90 | p95 | p99 | max |
|---|---:|---:|---:|---:|---:|---:|
| wait_for_free_slot | 3.813 | 2.184 | 11.048 | 12.399 | 13.804 | 551.560 |
| executor.submit | 0.336 | 0.125 | 0.202 | 0.233 | 0.323 | 290.436 |
| worker queue delay | 0.543 | 0.431 | 0.762 | 0.865 | 1.123 | 276.438 |
| worker render | 3.419 | 3.028 | 4.903 | 5.673 | 8.394 | 40.042 |
| clear | 0.332 | 0.305 | 0.404 | 0.446 | 0.991 | 4.754 |
| worker SHM copy | 0 | 0 | 0 | 0 | 0 | 0 |
| worker compute | 3.869 | 3.468 | 5.362 | 6.263 | 9.134 | 42.283 |
| result → main observed | 14.502 | 14.621 | 21.744 | 23.905 | 31.269 | 805.537 |
| HOL / reorder wait | 0.163 | 0.067 | 0.122 | 0.156 | 0.312 | 22.194 |
| queue.put | 0.008 | 0.006 | 0.015 | 0.018 | 0.026 | 0.304 |
| queue → writer dequeue | 9.133 | 6.737 | 19.206 | 21.266 | 26.550 | 569.339 |
| stdin.write | 3.893 | 2.274 | 11.047 | 12.426 | 13.900 | 551.300 |
| post-worker SHM hold | 27.723 | 25.025 | 34.720 | 36.578 | 41.617 | 922.636 |
| total slot lifetime | 32.437 | 29.327 | 38.614 | 40.423 | 45.352 | 1217.292 |

## B. Writer starvation vs saturation

Writer diagnostics for the fresh `MAX_IN_FLIGHT=8` audit:

```text
writer thread active: 22964.1 ms
idle waiting:          1716.0 ms = 7.47%
inside stdin.write:   21023.9 ms = 91.55%
```

The writer is primarily saturated, not starved. There are short starvation
periods (`7.47%` idle), but the producer does not block materially on the
writer queue: `queue.put` median is only `0.006 ms`. Frames already handed to
the queue wait for the writer a median `6.737 ms`.

The former ambiguous `writer_ready_wait` is now also reported as the explicit
`queue_to_writer_wait` phase.

## C. Occupancy

Fresh post-5G audit, buckets `0–2 / 3–5 / 6–7 / 8+`:

| Occupancy | 0–2 | 3–5 | 6–7 | 8+ |
|---|---:|---:|---:|---:|
| futures / in-flight | 4.89% | 44.63% | 33.59% | 16.89% |
| SHM slots | 0.04% | 0.06% | 0.04% | 99.87% |
| ready writer queue | 50.31% | 44.67% | 5.02% | 0% |

SHM slots are effectively full because each slot remains owned until the
writer completes its write. The ready queue is usually non-empty, but not
permanently full.

## D. HOL / reorder

Fresh `MAX_IN_FLIGHT=8`:

```text
HOL median: 0.0667 ms
HOL p95:    0.1555 ms
HOL p99:    0.3124 ms
frames >1 ms: 39
frames >5 ms: 33
sum HOL:      877.58 ms
```

The reorder stage is not the main bottleneck at 8. Increasing the window
causes queued frames to wait longer and substantially increases HOL tails.

## E. Slot lifetime

For the fresh corrected audit, the lifetime components are:

| Component | median | p95 | p99 |
|---|---:|---:|---:|
| worker finished → ordered | 14.754 ms | 23.957 ms | 31.305 ms |
| ordered → writer begins | 6.744 ms | 21.274 ms | 26.559 ms |
| stdin.write | 2.274 ms | 12.426 ms | 13.900 ms |
| write end → release | 0.015 ms | 0.041 ms | 0.100 ms |
| worker finished → release | 25.025 ms | 36.578 ms | 41.617 ms |

The slot is never released before `stdin.write` ends. No early release and no
additional full-frame copy were introduced.

## F. Writer buffer / syscall path

The production writer receives:

```text
process.stdin.buffer
type: _io.BufferedWriter
input: memoryview(SHM)
frame: 5,791,200 B
```

No `bytes()`, `bytearray()`, `.tobytes()`, or NumPy materialization is used
between SHM and the writer. The current default performs exactly one
`write()` per frame.

The pipe-only A/B used the same prebuilt SHM-backed memoryview and unchanged
FFmpeg graph:

| Path | 3-run median | writes/frame | partial frames |
|---|---:|---:|---:|
| current BufferedWriter | 301.53 FPS | 1 | 0 |
| raw FileIO | 303.17 FPS | 1 | 0 |
| `os.write` | 305.05 FPS | 1 | 0 |
| `bufsize=0` / FileIO | 302.46 FPS | 1 | 0 |

All variants accepted exactly:

```text
requested: 31,272,480,000 B
returned:  31,272,480,000 B
partial writes: 0
```

None reaches the required `+5%` improvement. Therefore no alternate syscall,
unbuffered mode, chunking, or default writer replacement was implemented.
The raw path remains only as an opt-in diagnostic A/B path.

## G. MAX_IN_FLIGHT sweep

One stable 5400-frame audited run per value, preview ON. SHM usage is based on
`5.52 MiB` per slot.

| MIF | SHM | FRAME_PIPELINE | REAL_EXPORT | writer idle | writer busy | queue→writer med | HOL med | slot lifetime med |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 8 | 44.2 MiB | 284.4 | 260.8 | 7.50% | 92.11% | 5.81 ms | 0.05 ms | 26.17 ms |
| 12 | 66.3 MiB | 284.6 | 261.5 | 6.89% | 92.69% | 15.77 ms | — | — |
| 16 | 88.4 MiB | 288.2 | 263.7 | 6.86% | 92.67% | 20.51 ms | — | — |
| 24 | 132.6 MiB | 288.3 | 264.9 | 6.62% | 92.90% | 23.22 ms | 4.01 ms | 73.63 ms |

The candidate `24` received the required three additional full exports. The
three-run medians were:

| MIF | runs FRAME_PIPELINE | median | runs REAL_EXPORT | median |
|---:|---|---:|---|---:|
| 8 | 284.4 / 261.6 / 265.3 | 265.3 | 260.8 / 238.0 / 238.5 | 238.5 |
| 24 | 288.3 / 265.7 / 268.7 | 268.7 | 264.9 / 245.5 / 247.9 | 247.9 |

The apparent gain is only about `1.3%` in FRAME_PIPELINE and `4.0%` in
REAL_EXPORT, below the writer-change acceptance threshold. It comes with
much higher queue wait, HOL, slot lifetime and 3× SHM memory. The production
default therefore remains `MAX_IN_FLIGHT=8`.

## H. Pipe-only and FFmpeg graph

Fresh three-run ceilings using the unchanged graph:

```text
PIPE_ONLY median:   301.53 FPS
FFMPEG_GRAPH median: 324.75 FPS
```

The older 5G values are not used as current measurements. The current
pipe-only ceiling remains below the graph ceiling, confirming that raw RGBA
pipe/writer transport is the next architectural boundary.

## I. Implemented changes

Only diagnostic and safety changes were made:

- separated `queue_to_writer_wait` from writer write time;
- measured writer idle and busy time;
- recorded ready-queue occupancy;
- recorded requested/returned bytes and write-call count;
- added opt-in raw FileIO A/B support, disabled by default;
- corrected audit timestamp order so `write_finished` precedes SHM release;
- added writer lifecycle, partial-write and exception tests;
- added the pipe-only writer benchmark harness.

The default writer remains `BufferedWriter.write(memoryview)`. Zero-copy SHM
remains active and no HUD/FFmpeg/worker/telemetry code was optimized here.

## J. Correctness

Verified:

```text
zero_copy: 5400/5400
fallback: 0
requested bytes/frame: 5,791,200
returned bytes/frame:  5,791,200
partial writes: 0
encoded frames: 5400
```

`ffprobe` reported `nb_frames=5400` for both the MIF8 and MIF24 final A/B
outputs. Normal finish completed without stuck slots or writer threads.

Targeted tests:

```text
9 passed
```

This includes normal writer finish, raw partial-write loop, writer exception,
zero-copy SHM safety and lifecycle audit tests. Existing cancel lifecycle
coverage also passed. No chart/HUD raster was changed.

The focused ETAP5/NVIDIA suite completed with `28 passed`. A full repository
run was not a valid 5H signal: it reproduced the two pre-existing AMD/NVIDIA
environment failures and later terminated in an unrelated Qt access violation
in `tests/test_mp4_inspector.py` / `src/gui/qt/tabs/load_tab.py`.

## K. Production benchmark 3×

The accepted production configuration is still MIF8, workers 4, preview ON,
DIRECT_REGION and zero-copy SHM. Three full audited exports used for the final
comparison gave:

```text
FRAME_PIPELINE: 265.3 FPS median
REAL_EXPORT:    238.5 FPS median
preview:        approximately 4.8–5.1 FPS
pipe-only:      301.53 FPS median
FFmpeg graph:   324.75 FPS median
stdin.write:    approximately 2.18 ms median in the 3-run set
writer idle:    approximately 7.2% median
queue wait:     approximately 6.5 ms median
HOL:            approximately 0.06 ms median
slot lifetime:  approximately 28.3 ms median
```

Run-to-run GPU/FFmpeg variance was significant; the raw per-run artifacts are
kept under `scratch/etap5f_etap5h_*.json` and `.csv`.

## L. Remaining ceiling

The writer is mostly saturated, not starved. The next real limitation is the
CPU raw RGBA pipe plus the FFmpeg ingestion/processing path. The current
pipe-only ceiling is about `301.5 FPS`, while the graph ceiling is about
`324.7 FPS`. Increasing the in-flight window only hides short producer
variations and increases buffering/lifetime; it does not remove the raw pipe
cost.

GPU-native transport is explicitly not implemented in ETAP 5H.

## O. Final answers

1. Writer jest głównie nasycony; idle występuje przez około `7.5%` czasu.
2. Kolejka ma głębokość `0–2` przez około `50.3%`, `3–5` przez `44.7%`,
   `6–7` przez `5.0%`, nigdy `8+` w świeżym MIF8 audycie.
3. `MAX_IN_FLIGHT=8` pozostaje domyślnie najlepszym kompromisem; 24 nie daje
   wystarczającej stabilnej przewagi względem kosztu i HOL.
4. `stdin.write` korzysta z `_io.BufferedWriter`, ale otrzymuje bezpośredni
   `memoryview(SHM)`; nie wykryto dodatkowej kopii frame ani partial write.
5. `raw FileIO`, `os.write` i `bufsize=0` nie były szybsze o wymagane 5%.
6. Nowy PIPE_ONLY: `301.53 FPS` median.
7. Nowy FRAME_PIPELINE dla zaakceptowanego MIF8: `265.3 FPS` median w świeżym
   trzy-run A/B.
8. Nowy REAL_EXPORT dla zaakceptowanego MIF8: `238.5 FPS` median.
9. Następne rzeczywiste ograniczenie to CPU raw RGBA pipe / FFmpeg ingestion,
   nie worker SHM renderer.

Po zakończeniu ETAPU 5H zatrzymano dalsze prace.
