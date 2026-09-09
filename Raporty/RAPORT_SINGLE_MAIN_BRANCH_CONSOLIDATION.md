# TeleM — single `main` branch consolidation

Data: 2026-09-09  
Repo: `C:\_DEV\TeleM-integration`  
Remote: `https://github.com/malcerz/TeleM.git`

## Starting state

- starting branch: `integration/intel-amd`
- starting HEAD: `59277b4c920e0bb8a9642e4a574a32db0edcfacc`
- local `main`: `e8a811e5149807e5d5b12b68ff3862f507e81dc5`
- `origin/main`: `cbfcf8d4c0063539294bfdf20cbc839f24ddab97`
- `integration/intel-amd` was a strict superset of both local and remote
  `main` (`main..integration` had 28 commits before the checkpoint).

The initial dirty tree contained 1332 status entries: 1211 tracked changes,
including 1149 deletions under `scratch`, plus 121 untracked files. Those
changes were inspected before staging.

## Integration commit

Only code, tests, reports, source assets and development guidance were staged.
The following were explicitly excluded from the commit:

- `scratch/**` and `Video/scratch/**`;
- generated telemetry caches (`*.telemetry.json.gz`, `*.telemetry.npz`);
- compiler/build artifacts (`*.obj`, `*.pyd`, `*.exp`);
- screenshots, render outputs and Python cache directories.

Staged file list was shown before commit; 187 files were staged.

Integration commit:

```text
3546274f8083c51c34bb708ba13debde9f41cab5
TeleM: consolidate integrated AMD and shared presentation pipeline
```

No renderer or backend code was changed by the consolidation operation itself;
the commit records the already-present integrated AMD/shared state.

## Safety tag

Annotated tag:

```text
amd-final-2026-09-09
Stable AMD checkpoint before NVIDIA and Intel work on unified main branch
```

Tag object: `90d1f5d4be65d4d2fb3ac34a3e040e981c12757e`  
Tag target: `3546274f8083c51c34bb708ba13debde9f41cab5`

## Main and push

`main` was updated with a fast-forward from `e8a811e` to
`3546274f8083c51c34bb708ba13debde9f41cab5`. No force update was required.

Push results:

- `main` → `origin/main`: PASS (`cbfcf8d..3546274`)
- `amd-final-2026-09-09` → origin: PASS
- local `main` and `origin/main`: identical commit
- remote tag target and local `main`: identical commit

## Branch cleanup

Deleted locally (all had empty `git log main..BRANCH`):

```text
amd-optimization
backup/amd-pre-intel-20260829
gui-redesign
integrate-amd-gui
integrate-gui-amd
integration/intel-amd
```

Deleted remotely:

```text
origin/amd-render
origin/backup/amd-pre-intel-20260829
origin/integration/intel-amd
origin/intel-render
```

Preserved because they are not merged into `main` or are active worktrees:

- `intel-coreultra` / `origin/intel-coreultra` — unmerged commit
  `e4128df Intel Core Ultra: add path observability and capability proof`;
- local `amd-render` — checked out by the separate worktree
  `C:\_DEV\TeleM`, therefore not deleted or forcibly detached.

No branch with unmerged commits was deleted. No tag was deleted.

## Final refs

Current primary worktree:

```text
* main 3546274 [origin/main] TeleM: consolidate integrated AMD and shared presentation pipeline
```

Remote branches after prune:

```text
origin/HEAD -> origin/main
origin/main
origin/intel-coreultra
```

The separate linked worktree still has `amd-render` checked out; removing it
would require changing that worktree, so it was intentionally left intact.

## Final status

`main` is clean with respect to the committed integration files. The working
tree still reports the pre-existing excluded `scratch` deletions and local
build/cache artifacts; they were deliberately not discarded and were not
included in the checkpoint commit. No `reset`, `clean`, `rebase` or force push
was used.

## Development rule

`AGENTS.md` now records the unified workflow: future NVIDIA work proceeds on
`main`, shared changes require an AMD smoke regression, and Intel work starts
only after NVIDIA is complete. The AMD safety checkpoint is
`amd-final-2026-09-09`; next work is NVIDIA, then Intel.

## Status

```text
ACTIVE PRIMARY BRANCH = main
AMD SAFETY CHECKPOINT = amd-final-2026-09-09
NEXT WORK = NVIDIA
AFTER NVIDIA = INTEL
```
