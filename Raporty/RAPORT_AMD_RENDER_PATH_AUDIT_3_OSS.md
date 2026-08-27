# RAPORT_AMD_RENDER_PATH_AUDIT_3_OSS.md

## Summary

This report documents the diagnostic audit of the **AMD_NATIVE_D3D11** rendering path in the TeleM project, performed without any functional changes.

- **Instrumentation added**: AMD_AUDIT_ABOVE_Comp\u006Fse timer in src/indicators/compositor.py.
- **Environment flag**: Set AMD_AUDIT_ABOVE_Comp\u006Fse=1 to enable timing of bove_compose total duration.

## Collected Metrics

| Metric | Description | Value |
|--------|-------------|-------|
| bove_compose.total | Total time spent in the above-compose stage per frame (ms) | *Pending – to be filled after benchmark runs* |

## Benchmark Configuration

- **Resolution**: 1080p and 4K
- **Frames**: 300 warm-up + 300 measured
- **Preset**: presets/cycling_dashboard_v10.json
- **Audio**: Disabled (AMD_SKIP_MUX=1)
- **CSV Output**: c:/_DEV/TeleM/Raporty/AMD_RENDER_PATH_AUDIT/above_compose_1080p.csv and ..._4k.csv

## Next Steps

1. Run the benchmark harness scratch/run_amd_render_path_audit.py with the appropriate flags.
2. Gather CSV files and populate the tables above.
3. Extend the report with additional sections (dirty-region analysis, Z-order verification, GPU_SPLIT flow, stall diagnostics, etc.) as data becomes available.

---
*Report generated automatically by Antigravity following the approved implementation plan.*
