# AMD 8K checkpoint clean verification

## Cel

Sprawdzenie, czy commit `0ef407e` jest samowystarczalny i kompilowalny bez lokalnych unstaged hunków głównego working tree.

## Initial main working tree status

Wykonano `git status --short` przed rozpoczęciem. Główny working tree zawierał wcześniejsze zmiany `M`, `D` i `??`, między innymi:

```text
 M native/d3d11_amf_pipeline/src/d3d11_vp_pipeline.cpp
 M native/d3d11_amf_pipeline/src/d3d11_vp_pipeline.h
 M native/d3d11_amf_pipeline/src/telem_amd_native.cpp
```

Status obejmował również wcześniejsze zmiany raportów, skryptów, scratch, UI, GPMF i artefaktów builda. Żaden z tych plików nie został przywrócony, wyczyszczony, zstashowany ani zmodyfikowany.

## Checkpoint worktree

- Worktree: `C:\_DEV\SportCamHUD-amd-checkpoint`
- HEAD: `0ef407e9ce71cb192f43289abebf6b60c8259839`
- `CHECKPOINT_WORKTREE_CLEAN=True`
- Worktree usunięto po sprawdzeniu czystości.

## Build

Build wykonano wyłącznie w checkpoint worktree:

```text
ninja -C native\d3d11_amf_pipeline\build telem_amd_native
```

Wynik:

```text
CHECKPOINT_NATIVE_BUILD=PASS
DLL_BUILT_FROM_CHECKPOINT=True
```

DLL wygenerowana z commita:

```text
C:\_DEV\SportCamHUD-amd-checkpoint\native\d3d11_amf_pipeline\bin\telem_amd_native.dll
```

Build zakończył się ostrzeżeniami kompilatora, ale bez błędu linkowania.

## 2-frame smoke

Użyto committed harnessu `scratch/test_8k_x265_gate2.py` z `AMD_TEST_FRAMES=2` i `AMD_READBACK_ONLY=1`.

- 2F `COPY_ONLY`: PASS.
- Próba pełnego 2F copy+shader: pierwszy dispatch osiągnął `DEVICE_REASON=0`, ale drugi frame zakończył się `PROCESS_OK_ALL=False`.
- Końcowy flush x265/readback został pominięty w izolowanym wariancie, ponieważ nie był częścią wymaganego copy+shader-only smoke.
- Harness nadal inicjalizuje tryb x265, dlatego wynik nie jest akceptowany jako czysty PASS ścieżki bez x265/readback.

Wymagany gate:

```text
CHECKPOINT_8K_SHADER_2F=FAIL
```

## Dependency audit

Porównano w głównym repo:

```text
git diff 0ef407e -- native/d3d11_amf_pipeline/src/d3d11_vp_pipeline.cpp
git diff 0ef407e -- native/d3d11_amf_pipeline/src/d3d11_vp_pipeline.h
git diff 0ef407e -- native/d3d11_amf_pipeline/src/telem_amd_native.cpp
```

Pozostałe lokalne hunki dotyczyły map/ALT_VISUAL/AMF/QP i innych prac, nie brakującej implementacji 8K wymaganej do kompilacji checkpointu.

```text
MISSING_DEPENDENCY_FROM_UNSTAGED_HUNK=False
```

## Required result

```text
CHECKPOINT_SHA=0ef407e9ce71cb192f43289abebf6b60c8259839
CHECKPOINT_WORKTREE_CLEAN=True

CHECKPOINT_NATIVE_BUILD=PASS
DLL_BUILT_FROM_CHECKPOINT=True
CHECKPOINT_8K_SHADER_2F=FAIL

MISSING_DEPENDENCY_FROM_UNSTAGED_HUNK=False

MAIN_WORKTREE_UNCHANGED=True
SAFE_TO_PUSH=False
```

`MAIN_WORKTREE_UNCHANGED=True` oznacza zachowanie istniejących zmian głównego working tree. Dodano wyłącznie ten raport i wynik NTFY wymagane przez bieżące zadanie.

## NTFY

- Notification: wysłane poprawnie.
- Próba: 1.
- Exit code: `0`.
- `NTFY_SUCCESS=True`.
- Push Git: nie wykonano.

## Timing

```text
TOTAL_STAGE_WALL_TIME=NOT RECORDED
AUDIT_TIME=NOT RECORDED
REPRO_TIME=NOT RECORDED
IMPLEMENTATION_TIME=NOT APPLICABLE
VALIDATION_TIME=NOT RECORDED
LONGEST_SINGLE_COMMAND_SECONDS=8.0 (worktree add)
```

## Final summary

Checkpoint jest samowystarczalny kompilacyjnie, ale nie spełnił wymaganego 2-frame copy+shader smoke w czystym worktree. Nie poprawiano kodu i nie wykonano push.
