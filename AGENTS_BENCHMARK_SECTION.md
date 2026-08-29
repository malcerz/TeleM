# Canonical benchmark datasets

Before running TeleM benchmarks, read:

```text
BENCHMARKS.md
```

The VIDEO/FIT mapping in `BENCHMARKS.md` is authoritative.

Hard rules:

- NEVER infer or guess a FIT file from an MP4 filename, activity title, timestamps, metadata dates, or folder order.
- NEVER silently substitute a different FIT.
- For the primary single-file benchmark use exactly:
  `Video/GX020079.MP4` + `Video/GX020079.fit`.
- For the secondary single-file benchmark use exactly:
  `Video/GX030120.MP4` + `Video/GX030120.fit`.
- For the canonical multi-file benchmark use exactly:
  `Video/GX010114.MP4`, `Video/GX010115.MP4`, `Video/GX010116.MP4`
  + `Video/GX010114_116.fit`.
- `GX030120.MP4 + Jazda_na_rowerze_w_porze_lunchu.fit` is an INVALID benchmark pairing.
- If a task requires a different dataset, explicitly report the proposed VIDEO/FIT pairing before using it.
- Code and working tree take precedence over reports, but the benchmark pairings in `BENCHMARKS.md` must not be changed implicitly.
