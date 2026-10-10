# Raport AMD 4K VideoProcessorBlt checkpoint A/B

Data: 2026-09-23  
Repozytorium: `C:\_DEV\SportCamHUD-amd`  
Branch główny: `amd-bikeridehud`  
Checkpoint: `0ef407e9ce71cb192f43289abebf6b60c8259839`

## Wynik

```text
CASE=CASE B — checkpoint także kończy się VideoProcessorBlt E_FAIL
REGRESSION_AFTER_CHECKPOINT=False
SAFE_TO_PUSH=False
```

Czysty checkpoint nie przechodzi testu 4K. Ten sam błąd występuje w dirty
tree, dlatego nie ma podstaw do przypisania regresji zmianom po checkpointcie.
Nie wykonano diff-isolation ani fixa.

## Worktree i build

```text
REQUESTED_WORKTREE=C:\_DEV\SportCamHUD-amd-vp-checkpoint
REQUESTED_WORKTREE_STATUS=NOT CLEAN (pre-existing modification in d3d11_vp_pipeline.cpp)
TEST_WORKTREE=C:\_DEV\SportCamHUD-amd-vp-checkpoint-clean
WORKTREE_CLEAN_BEFORE_TEST=True
HEAD=0ef407e9ce71cb192f43289abebf6b60c8259839
CHECKPOINT_BUILD=PASS
```

`ninja` nie był dostępny w `PATH`; użyto tego samego MinGW/Ninja z
`C:\tools\mingw64\bin` po lokalnej konfiguracji CMake w świeżym worktree.
Główny dirty tree nie był resetowany, stashowany, czyszczony, commitowany ani
pushowany.

## Test A/B

Dokładny workload:

```text
VIDEO=C:\_DEV\SportCamHUD-amd\Video\GX020079.MP4
INPUT=3840x2160 4K
OUTPUT=3840x2160 4K
DECODE=D3D11VA / Media Foundation
HUD=OFF
ENCODER=AMF ON
```

```text
CHECKPOINT_4K_VP_1F=FAIL
CHECKPOINT_4K_VP_10F=FAIL
CHECKPOINT_VP_BLT_HRESULT=0x80004005 E_FAIL
CHECKPOINT_DEVICE_REMOVED_REASON=0x0

CURRENT_DIRTY_4K_VP_1F=FAIL
CURRENT_DIRTY_4K_VP_10F=FAIL
```

W obu przypadkach przetworzono `0` klatek; awaria wystąpiła na frame 0.
Checkpoint został uruchomiony w świeżych procesach, w tym dwukrotnie z AMF ON.
Wariant checkpointu z `AMD_DEBUG_NO_AMF=1` również doszedł do VP i zakończył
się błędem GPU compositora, więc AMF nie jest rozdzielaczem tego wyniku.

## Kontrakt VP

Checkpointowy kod nie zawierał jeszcze diagnostyki `VP CONTRACT BEFORE BLT`,
dlatego poniższe pola checkpointu nie są bezpośrednio obserwowane:

```text
CHECKPOINT_INPUT_DESC=NOT OBSERVED — checkpoint fails before comparable contract dump
CHECKPOINT_OUTPUT_DESC=NOT OBSERVED — checkpoint fails before comparable contract dump
CHECKPOINT_SRC_RECT=NOT OBSERVED
CHECKPOINT_DST_RECT=NOT OBSERVED
```

Dirty tree wypisał bezpośrednio przed `VideoProcessorBlt`:

```text
DIRTY_INPUT_DESC=3840x2160, DXGI_FORMAT=104 (P010), ArraySize=11, BindFlags=0x208, MiscFlags=0x0, subresource=0, arraySlice=0
DIRTY_OUTPUT_DESC=3840x2160, DXGI_FORMAT=103 (NV12), ArraySize=1, BindFlags=0xa8, outputView!=nullptr
DIRTY_SRC_RECT=(0,0,3840,2160)
DIRTY_DST_RECT=(0,0,3840,2160)

FOR_SHADER_SCALER_4K=False
BYPASS_CAN_USE_INPUT_SURFACE_4K=False (normal CanUseInputSurface decision path)
COMPUTE_ONLY_TOPOLOGY_4K=False
USE_SHADER_SCALER_4K=False
FRAME_FORMAT=PROGRESSIVE
STREAM_ENABLED=True
VIDEO_PROCESSOR_BLT_USED=True
```

Zaobserwowane warunki dirty 4K są zgodne z oczekiwanym zwykłym VP path.
Nie dowodzi to jeszcze poprawności kontraktu checkpointu, ponieważ checkpoint
nie posiadał tej samej diagnostyki, ale A/B rozstrzyga się wcześniej: oba
buildy kończą się na VP `E_FAIL`.

## Diff isolation

```text
VP_RELEVANT_DIFF_HUNKS=NOT APPLICABLE — CASE B; zgodnie z procedurą nie wykonywano izolacji regresji po checkpointcie
```

Nie wprowadzono minimalnego fixa:

```text
ROOT_CAUSE=NOT CONFIRMED as source regression; common 4K VideoProcessorBlt E_FAIL is reproduced on clean checkpoint and dirty tree. Driver/runtime state or a common resource/view contract remains unresolved.
FIX=NONE
```

## Testy po rozstrzygnięciu

```text
4K_1F=FAIL (frame 0, VideoProcessorBlt E_FAIL)
4K_10F=FAIL (frame 0, VideoProcessorBlt E_FAIL)
4K_30F=NOT TESTED — no fix was allowed in CASE B
4K_RENDER_FPS=NOT MEASURABLE — zero frames completed

8K_SHADER_ONLY_10F=NOT TESTED — explicitly stopped after CASE B
8K_SHADER_ONLY_100F=NOT TESTED
8K_SHADER_ONLY_300F=NOT TESTED
```

Nie wykonano restartu Windows/driver-state. Powtórzenie checkpointu w świeżych
procesach było wystarczające do reprodukcji CASE B; dalsze działania wymagają
restartu środowiska poza zakresem bezpiecznej ingerencji tego przebiegu.

## Timing / notifications

```text
TOTAL_STAGE_WALL_TIME=approximately 20 minutes
AUDIT_TIME=approximately 6 minutes
REPRO_TIME=approximately 10 minutes
IMPLEMENTATION_TIME=0 minutes (no code fix)
VALIDATION_TIME=approximately 4 minutes
LONGEST_SINGLE_COMMAND_SECONDS=approximately 10.3
NTFY=3/3 successful, EXIT_CODE=0
```

## Backend isolation / final summary

Nie zmieniono kodu NVIDIA, Intel, CPU/reference ani kodu renderera AMD.
Jedynym artefaktem w głównym repozytorium jest ten raport oraz dopisana sekcja
w istniejącym `ntfy_result.txt`; diagnostyka checkpointu była wykonywana w
osobnym worktree.

```text
FINAL=FAIL / CASE B
CHECKPOINT_4K_VP=FAIL
CURRENT_DIRTY_4K_VP=FAIL
REGRESSION_AFTER_CHECKPOINT=False
SAFE_TO_PUSH=False
```
