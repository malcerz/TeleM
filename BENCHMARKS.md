# TeleM — Canonical Benchmark Datasets

## Purpose

This file defines the canonical VIDEO/FIT pairings used for TeleM development,
performance testing, synchronization validation, and regression testing.

Agents MUST use these mappings exactly.
Do not infer VIDEO/FIT pairings from filenames, file dates, metadata dates,
activity names, or directory proximity.

---

## 1. Primary single-file canonical benchmark

```text
Video/GX020079.MP4
Video/GX020079.fit
```

Use this pair as the default single-file benchmark unless a task explicitly
requires another dataset.

Roles:
- primary AMD performance benchmark
- moving-map benchmark
- synchronization validation
- single-file rendering regression

---

## 2. Secondary single-file benchmark

```text
Video/GX030120.MP4
Video/GX030120.fit
```

Use as a secondary validation workload.

Do NOT pair `GX030120.MP4` with:

```text
Jazda_na_rowerze_w_porze_lunchu.fit
```

That pairing is invalid.

---

## 3. Canonical multi-file benchmark

```text
Video/GX010114.MP4
Video/GX010115.MP4
Video/GX010116.MP4
Video/GX010114_116.fit
```

`GX010114_116.fit` covers the multi-file activity represented by clips
GX010114, GX010115, and GX010116.

Do not associate the FIT only with GX010114. It belongs to the complete
114–116 sequence.

---

## 4. Pairing rules

Agents MUST:

1. Use the mappings in this file exactly.
2. Never choose a FIT file by guessing from activity names.
3. Never substitute another FIT because its timestamp appears closer.
4. Never silently pair a VIDEO and FIT that are not defined here.
5. If a benchmark requires another dataset, explicitly report the proposed
   VIDEO/FIT pair before using it.
6. For multi-file tests, preserve clip order:
   GX010114 -> GX010115 -> GX010116.
7. Validate SmartSync/timeline against the selected canonical pair rather than
   replacing the canonical pair with a different file.

---

## 5. Benchmark naming convention

For a single-file dataset:

```text
GXnnnnnn.MP4
GXnnnnnn.fit
```

Example:

```text
GX020079.MP4
GX020079.fit
```

For a FIT covering a consecutive multi-file sequence:

```text
GX<first>_<last>.fit
```

Example:

```text
GX010114_116.fit
```

---

## 6. AMD production default and benchmark governance

The real AMD production default is intentionally conservative:

```text
AMD_CPU_GPU_PIPELINE=SYNC
AMD_QUEUE_DEPTH=0
AMD_VP_STATE_MODE=REFERENCE
AMD_VP_POOL_SIZE=8
AMD_AMF_QUERY_MODE=REFERENCE
```

Use the canonical runner with `--production-defaults` to ignore governed
ambient `AMD_*` overrides and record the ignored values in the profile. Use
`--set-amd NAME=VALUE` only for an explicit, labelled ablation. Every native
AMD profile contains `benchmark.config` and `benchmark.config_fingerprint`.

The following is the historical experimental benchmark configuration; it is
not the GUI production baseline:

Unless an AMD task explicitly says otherwise:

```text
Branch: amd-render
Power mode: Max Performance
AMD_NATIVE_PROFILING=0
AMD_CPU_GPU_PIPELINE=ASYNC
AMD_QUEUE_DEPTH=2
AMD_VP_STATE_MODE=STATIC_CACHE
AMD_AMF_QUERY_MODE=DRAIN_READY
```

It must be labelled `EXPLICIT_ABLATION` or `HISTORICAL_EXPERIMENTAL_CONFIG`.

Current accepted map production policy:

```text
MAP_ALIGN_16_NEAREST
FUSED MAP SHADER = OFF
```

Any change to the canonical workload must be explicitly stated in the report.

---

## 7. Historical invalid benchmark warning

Some earlier AMD benchmark work used:

```text
GX030120.MP4
+
Jazda_na_rowerze_w_porze_lunchu.fit
```

This is NOT a canonical pair.

Do not reuse that pairing for new performance baselines.
Historical results may remain in reports for traceability, but must be labelled
as historical/non-canonical when compared with current measurements.
