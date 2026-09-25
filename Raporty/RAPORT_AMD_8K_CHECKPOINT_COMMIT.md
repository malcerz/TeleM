# Raport AMD true 8K CPU-x265 — checkpoint commit

## Task

Bezpieczne utworzenie checkpointu dla prac nad AMD true-8K CPU-x265 / D3D11 interop.

Checkpoint nie oznacza ukończenia eksportu 8K.

## Initial state

- Branch: `amd-bikeridehud`
- Copy + shader multiframe: PASS do 300 klatek.
- 8K staging/readback: BLOCKED — `DXGI_ERROR_DRIVER_INTERNAL_ERROR 0x887A0020`.
- True 8K x265 end-to-end: NOT PROVEN.
- Wymagany final output: `7680x4320`.
- 4K downscale nie został zaakceptowany jako rozwiązanie.

## Commit

- SHA: `0ef407e`
- Message: `AMD: checkpoint true 8K x265 D3D11 interop`
- Branch: `amd-bikeridehud`
- Push: nie wykonano.

## Committed files

Commit zawiera selektywnie wybrane zmiany związane z bieżącym etapem:

- `native/d3d11_amf_pipeline/src/d3d11_vp_pipeline.cpp`
- `native/d3d11_amf_pipeline/src/d3d11_vp_pipeline.h`
- `native/d3d11_amf_pipeline/src/telem_amd_native.cpp`
- `Raporty/RAPORT_AMD_8K_CPU_X265_D3D11_INTEROP_GATES.md`
- `Raporty/RAPORT_AMD_8K_MULTIFRAME_RESOURCE_LIFETIME.md`
- `Raporty/RAPORT_AMD_8K_P010_PLANE_READBACK.md`
- `scratch/test_8k_x265_gate1.py`
- `scratch/test_8k_x265_gate2.py`

DLL `native/d3d11_amf_pipeline/bin/telem_amd_native.dll` nie została dodana: nie jest śledzona przez Git i jest ignorowana przez `.gitignore`.

## Staging safety

- Nie użyto `git add .` ani `git add -A`.
- Zmiany źródłowe zostały staged selektywnie hunkami.
- NVIDIA, Intel, GPMF, UI, map/ALT_VISUAL i QP telemetry nie zostały dodane do commita.
- Wszystkie pozostałe dirty/untracked changes zostały zachowane.
- Pozostałe hunki w trzech plikach źródłowych pozostały unstaged.

## Tests and benchmarks

- Nowych testów po commicie nie uruchamiano zgodnie z poleceniem.
- Benchmarku po commicie nie uruchamiano.
- Wcześniejszy build DLL: PASS.
- 8K readback: BLOCKED.
- True 8K x265 end-to-end: NOT PROVEN.

## NTFY

- `NTFY_SUCCESS=True`
- Próba: 1
- Push: `False`
- Wynik zapisano w lokalnym pliku `ntfy_result.txt`, poza commitem.

## Risks / regressions

- Readback nadal kończy się błędem sterownika `0x887A0020`.
- Nie ma podstaw do oznaczenia produkcyjnego eksportu true 8K jako PASS.
- Nie wykonano regresji NVIDIA/Intel/4K AMF w ramach tej operacji.

## Backend isolation

Checkpoint obejmuje wyłącznie AMD true-8K CPU-x265 / D3D11 interop. Nie zmieniano zachowania NVIDIA/NVENC/CUDA ani Intel/QSV.

## Time accounting

- `TOTAL_STAGE_WALL_TIME`: NOT RECORDED
- `AUDIT_TIME`: NOT RECORDED
- `REPRO_TIME`: NOT RUN in checkpoint operation
- `IMPLEMENTATION_TIME`: NOT RECORDED
- `VALIDATION_TIME`: NOT RUN in checkpoint operation
- `LONGEST_SINGLE_COMMAND_SECONDS`: NOT RECORDED

## Final summary

**PASS:** bezpieczny checkpoint commit utworzony.

**NOT PASS:** finalny true 8K CPU-x265 export nadal nie jest potwierdzony z powodu zablokowanego staging/readback.
