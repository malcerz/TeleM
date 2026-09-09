# AMD — forensic audit snapshotu PRE-USB

Data audytu: 2026-09-07  
Branch: `integration/intel-amd`  
Tryb: **AUDIT ONLY**

## Zakres i gwarancje

Nie wykonano `git restore`, `git reset`, `git clean`, `git stash`, commit, push ani przebudowy DLL. Nie uruchamiano renderingu. Jedynym zapisem wykonanym w ramach tego zadania jest ten raport. Wszystkie obiekty Git i kopie binarne pozostawiono bez zmian.

## Stan wejściowy

| Element | Wartość |
|---|---|
| HEAD | `59277b4c920e0bb8a9642e4a574a32db0edcfacc` |
| Branch | `integration/intel-amd` |
| Pre-rollback stash | `6219a9e895317b212e876a41ac0c65bf36c4e384` — `backup-before-amd-render-rollback-20260907` |
| Backup po zbyt szerokim rollbacku | `878442ee9ef7367d2d00551ba2eaaf5e8f0ca36e` — `backup-after-too-wide-amd-rollback-20260907` |
| Tracked diff względem HEAD | 49 plików, 5796 insertions, 1022 deletions |
| Nested repo | `scratch/gpmf-parser-upstream`, czysty, HEAD `9a71506`; nie modyfikowano |

## Git archaeology

`git reflog --all --date=local` pokazał ostatnie istotne commity:

| Czas lokalny | Commit | Znaczenie |
|---|---|---|
| 2026-09-02 19:33:22 | `20c62f3b8c69b74f851de821fc4041930126b069` | pierwszy committed AMD direct MP4 mux, single/multi-file |
| 2026-09-02 20:10:09 | `356d45f89d49f02c1b418e9cc1e97990a24c5aeb` | abort/cleanup direct mux i pipe |
| 2026-09-03 18:52:24 | `b4047ab2cd7fdd883f16ac9932f5159b8ada7b06` | async AMF/AMD decode baseline |
| 2026-09-04 09:33:13 | `f63a8507ceba28f3282f269d7fee2f1406fd73e0` | stabilizacja async HUD buffers/decode selector |
| 2026-09-04 11:39:31 | `61d690851a3c89a1b82d020e2f76ca71879fc830` | exact single-file frame counts |
| 2026-09-04 11:39:54 | `59277b4c920e0bb8a9642e4a574a32db0edcfacc` | docs/integrity checkpoint, obecny HEAD |

`git stash list` zawiera tylko dwa wymienione wyżej backupy.  
`git fsck --full --no-reflogs --unreachable` oraz `git fsck --full --dangling` nie zwróciły żadnych dangling/unreachable commitów, drzew ani blobów. Nie znaleziono checkpointu agenta ani trzeciego snapshotu ukrytego poza reflogiem.

Wniosek: historia commitów nie zawiera commitowanego USB/local-scratch/Stage-A snapshotu po `59277b4`; te zmiany powstały w dirty worktree.

## Lokalne kopie/oracle/DLL

| Artefakt | Dowód/proweniencja | Ocena |
|---|---|---|
| `.oracle/amd-freeze/telem_amd_native.dll` | 3,059,698 B, utworzenie 2026-08-30; embedded build `telem-amd-native/1.0.0+3ab0b8927b7b.src8cc3987eaa98`, commit `3ab0b8927b7b9a93dbcba87900275e100b29091f` | Stary freeze oracle; nie jest snapshotem z 2026-09-04 |
| `scratch/telem_amd_native_frozen_oracle_before_log_build.dll` | ten sam build/source jak `.oracle`, utworzenie 2026-08-30 | Stary oracle; nie jest PRE-USB |
| `native/d3d11_amf_pipeline/bin/telem_amd_native.dll.golden-5R` | build `db7608a5a715.src26f03674bd97`, commit `db7608a5`, sierpień | historyczny golden; nie odpowiada obecnemu rendererowi |
| `native/d3d11_amf_pipeline/bin/telem_amd_native.freeze_fix.dll` | build `feb04820bbcd.src3b2ee95b961e`, commit `feb0482`, sierpień | późniejszy/stary freeze oracle, nie PRE-USB |
| `scratch/amd_native_exporter_golden.py` | blob `9f65c0abec1716e8572743896fd941c62754ad24`, dokładnie identyczny z `b4047ab:src/ffmpeg/amd_native_exporter.py` | referencja kodu direct-mux, nie pełny snapshot dirty worktree |
| `scratch/patch_amd_mux.py` | blob `e6d9c8ba18ec78b1b8112b04afc572f0edaa690c` | literalny patch pokazujący przejście do Stage A/Stage C; timestamp pliku nie jest wiarygodnym timestampem historycznym |
| `native/.../telem_amd_native.pre_rollback_20260907.dll` (obecnie aktywna kopia) | embedded `59277b4c920e.src01787b14f931`, build timestamp 2026-09-04 11:39:54 | artefakt pre-rollback, nie dowód osobnego PRE-USB snapshotu |

Żadna z kopii DLL nie ma odpowiadającego, kompletnego zestawu Python/C++/GUI z momentu bezpośrednio przed pierwszym dirty Stage A. DLL nie może być sama użyta jako oracle recovery.

## Chronologia zmian USB/mux

| Czas/okres | Etap | Pliki/funkcja | USB/mux | Czy istniało wcześniej | Dowód |
|---|---|---|---|---|---|
| 2026-09-02 19:33 | A/B: direct mux | `amd_native_exporter.py`, native pipe; `AMD_DIRECT_MUX` | Tak — zapis HEVC do FFmpeg named pipe | Nie | commit `20c62f3`, raport `RAPORT_AMD_DIRECT_MP4_MUX_SINGLE_FILE.md` |
| 2026-09-02 20:10 | hardening direct mux | abort, pipe cleanup, `.part` cleanup | Tak | direct mux już istniał | commit `356d45f`, raport multi-file direct mux |
| 2026-09-03/04 | stabilny AMD renderer | async HUD/AMF/decode | Pośrednio używał direct mux, ale nie local scratch | Nie dotyczy Stage A | `b4047ab`, `f63a8507`; historyczny wynik około 42.5 FPS |
| po 2026-09-04 11:39:54, dokładna godzina nie zachowana | pierwszy dirty Stage A | `stage_video`, `*.temp_video.mp4`, video-only `-an -c:v copy`, późniejszy stream-copy remux | Tak; pierwszy udokumentowany etap USB-oriented po checkpointcie | Nie | `RAPORT_AMD_MULTIFILE_RELIABILITY_HOTFIX.md`, `scratch/patch_amd_mux.py` |
| 2026-09-04 | proof Stage A/C | Stage A + Stage C na projekcie użytkownika | Tak | Stage A już istniał | `RAPORT_AMD_MULTIFILE_USER_PROJECT_PROOF.md`: 50,136/50,136, 42.463 FPS |
| później, przed 2026-09-06 | watchdog/overlapped | `FILE_FLAG_OVERLAPPED`, `ConnectNamedPipe`/`ReadFile`, `CancelIoEx`, deadlines, `AMDRenderWatchdog` | Tak | Stage A/live mux już istniały | `RAPORT_AMD_RANDOM_RENDER_FREEZE_FIX.md` |
| 2026-09-06 | local scratch dla wolnego USB | `AMD_LOCAL_SCRATCH_DIR`, `%LOCALAPPDATA%\TeleM\amd_scratch`, Stage A lokalnie, Stage C na USB, `FinalizationTracker` | Tak | Stage A istniał, lokalny scratch nie | `RAPORT_AMD_MULTIFILE_LOCAL_SCRATCH_TIMEOUT_FIX.md` |
| 2026-09-06 | disk guard/cleanup/progress | stale scratch cleanup, disk guard, Stage C progress | Tak | local scratch istniał | `RAPORT_FINALIZATION_PROGRESS_USB.md`, local-scratch report |
| 2026-09-06 | mux diagnostics/Preview diagnostics | `ERROR_NO_DATA`/`ERROR_BROKEN_PIPE`, stderr/Win32 diagnostics, Preview resize/latest-state | Tak, ale późne | wszystkie wcześniejsze etapy | `RAPORT_AMD_LIVE_MUX_PIPE_FAILURE_AND_PREVIEW_RESIZE.md`, `RAPORT_AMD_BACKGROUND_PREVIEW_MUX_PERFORMANCE.md` |

### Dokładny początek USB

Są dwa różne początki i nie wolno ich mieszać:

1. **Pierwszy committed direct mux/named pipe:** `20c62f3`, 2026-09-02 19:33:22.
2. **Pierwsza dirty-worktree próba USB/local scratch/Stage A:** nastąpiła po `59277b4` (2026-09-04 11:39:54) i przed/na etapie raportu Reliability Hotfix z 2026-09-04.

Git nie przechowuje hunków dirty worktree z timestampem ani osobnego checkpointu, więc dokładnej godziny (a nawet kolejności minutowej wewnątrz 2026-09-04) nie da się dowieść. Raportowanie konkretnej godziny byłoby zgadywaniem.

## Historyczne blob hashes kluczowych plików

| Plik | `20c62f3` | `356d45f` | `b4047ab` | `f63a8507` | `59277b4` | obecny recovered worktree |
|---|---|---|---|---|---|---|
| `src/ffmpeg/amd_native_exporter.py` | `649249bfa275cdcf49e609ae7fd4758d603e5d3c` | `a9a3e4f7e82eaa595e24ebffabce7e358be64209` | `9f65c0abec1716e8572743896fd941c62754ad24` | `c8b328e80956d09a9219aa2c02adf125fd3e945b` | `bda0a9f738df6520a29401b018cafdf5552f1bc5` | `74b69b5d43be7a1c5690d3a9e3215b6b26161631` |
| `src/ffmpeg/streaming.py` | `3b1eda04eec448da58e01b5a42a78c092b83eb02` | `3b1eda04eec448da58e01b5a42a78c092b83eb02` | `3b1eda04eec448da58e01b5a42a78c092b83eb02` | `42f38faad9deddda77b8d26ba60592359cdc4316` | `42f38faad9deddda77b8d26ba60592359cdc4316` | `8673f0b5942a5ac7dd987fa896aea0330b44af9c` |
| `native/.../telem_amd_native.cpp` | `fabe68e29d865e3715a1562ae226b8258b419a2a` | `fabe68e29d865e3715a1562ae226b8258b419a2a` | `18474b0f3899aa2339e95a8cdeb979adea460942` | `18474b0f3899aa2339e95a8cdeb979adea460942` | `18474b0f3899aa2339e95a8cdeb979adea460942` | `0379673918cb70d23a85bc2eace96f74dae0bec7` |
| `native/.../d3d11_vp_pipeline.cpp` | `015d98e5fc93b4a10a61be152f0a57719042d4bc` | `015d98e5fc93b4a10a61be152f0a57719042d4bc` | `158a888eb2b0bcce750238274d7cd10cfe37802f` | `158a888eb2b0bcce750238274d7cd10cfe37802f` | `158a888eb2b0bcce750238274d7cd10cfe37802f` | `5053b8ccef59fe2a32c49afff0307fde920b6700` |

Najbliższy committed renderer przed Stage A to kombinacja `f63a8507` (stabilizacja AMD) i jego poprzedników. Nie jest to pełny snapshot aplikacji pre-USB.

## Dowód, że renderer działał

- Historyczny `f63a8507` był opisany jako stabilny AMD D3D11VA + AMF, pełny HUD, 1000-frame acceptance PASS, około 42.559 Render FPS, bez flickera.
- `RAPORT_AMD_MULTIFILE_RELIABILITY_HOTFIX.md` (2026-09-04) podaje Stage A 300 klatek: 7.132 s / 42.062 FPS; Stage C: 213.49 ms, `rc=0`; direct single-file: około 42.924 FPS.
- `RAPORT_AMD_MULTIFILE_USER_PROJECT_PROOF.md` (2026-09-04) podaje 50,136/50,136 klatek, Render FPS 42.463, Stage A 1,180.706 s, Stage C 258.896 s, oraz przejście testów Preview/GPMF.

Te wyniki potwierdzają działający renderer również po pierwszym Stage A, ale nie identyfikują osobnego snapshotu dokładnie sprzed tej zmiany.

## Porównanie CURRENT vs kandydat PRE-USB — decyzje hunk-level

Nie zastosowano poniższych decyzji. To plan późniejszej chirurgicznej pracy, nie restore.

| Obszar | KEEP | ROLLBACK (tylko hunk/funkcja) | UNCERTAIN |
|---|---|---|---|
| `src/ffmpeg/amd_native_exporter.py` | późniejsze telemetry/GUI/Preview arguments, istniejący direct mux z `20c62f3`/`356d45f`, map/chart/gauge semantics | `_create_amd_local_scratch_dir`, stale scratch cleanup, `*.temp_video.mp4`, Stage A/Stage C routing, USB finalization tracker, disk guard, overlapped writer, `CancelIoEx`, mux watchdog/flush diagnostics | hunk łączący `preview_state_provider`/`generation_id` z lifecycle mux; wymaga ręcznej korelacji funkcja po funkcji |
| `src/ffmpeg/streaming.py` | preview/cancel/generation i nowszy lifecycle GUI | wyłącznie FinalizationTracker/drain/USB mux finalization blocks | mieszane hunky cancel + finalization |
| `native/.../telem_amd_native.cpp` | D3D11VA/AMF decode, compositor, HUD, mapy/wykresy | overlapped pipe write, pipe liveness diagnostics, `CancelIoEx`, added Win32 error plumbing | dokładna granica writer-vs-renderer w dużych hunkach |
| `native/.../d3d11_vp_pipeline.cpp` | bazowa VP/compositor semantyka | tylko timeout/deadline/watchdog additions z freeze fix | `ProcessFrame` wait hunks mogą wpływać na stabilność; nie przywracać całego pliku |
| `src/render_progress.py`, `src/gui/qt/_mixins/render_mixin.py` | nowszy progress, cancellation, Preview state/generation | brak automatycznego rollbacku | powiązania finalization callbacks wymagają testu |
| `preview_mixin.py`, `render_tab.py`, `video_preview.py`, `export_preview.py`, GPMF/native parser, indicators/layout | **KEEP** — późniejsze funkcje aplikacji | brak | tylko jeśli późniejszy test pokaże zależność od mux API |

W szczególności nie wolno przywracać całych `amd_native_exporter.py`, `streaming.py` ani katalogu native do `59277b4`; zawierają późniejsze funkcje, które użytkownik chce zachować.

## Ocena snapshotów

### Kandydat LAST KNOWN GOOD PRE-USB

Najlepszy dowiedziony punkt kodu: `f63a8507ceba28f3282f269d7fee2f1406fd73e0` jako **committed AMD renderer baseline**, wsparty raportem stabilnego renderingu. Najlepsza referencja direct-mux: `b4047ab2...` oraz identyczny blob `scratch/amd_native_exporter_golden.py`. Żaden z nich nie jest jednak kompletnym dirty worktree zawierającym aktualny GPMF, Preview, GUI i dokładny kod bezpośrednio przed Stage A.

Nie znaleziono osobnego stash/commit/tree/blob snapshotu, który można nazwać „dokładnie pre-USB” bez cofania reszty projektu. Obecny stash `6219...` jest snapshotem **po** rozpoczęciu eksperymentów USB/mux, ponieważ zawiera Stage A/local scratch/watchdog/diagnostics.

### Ryzyko DLL/ABI

Aktywna DLL ma embedded build `telem-amd-native/1.0.0+59277b4c920e.src01787b14f931`, natomiast bieżące dirty źródła native mają blob `037967...` (`telem_amd_native.cpp`) i `5053b8...` (`d3d11_vp_pipeline.cpp`). Audyt nie zmieniał DLL ani źródeł. Przed jakimkolwiek przyszłym testem chirurgicznego rollbacku trzeba jawnie ustalić parę source/DLL i ABI; sama kopia DLL nie jest wystarczającym oracle.

## Proponowany późniejszy zakres recovery (nie wykonano)

1. Zachować cały obecny GUI/GPMF/Preview/layout/indicator worktree.
2. Użyć `f63a8507` i `b4047ab` wyłącznie jako diff-oracle dla AMD renderer/mux.
3. Odwrócić na poziomie funkcji/hunków pierwszą dirty warstwę Stage A/local scratch oraz późniejsze overlapped/watchdog/diagnostics, zachowując committed direct mux tylko wtedy, gdy test potwierdzi, że jest częścią wymaganego baseline.
4. Zbudować i zweryfikować DLL z dokładnie wybranego zestawu source (dopiero po osobnej zgodzie; w tym audycie nie budowano).
5. Najpierw krótki smoke, potem 3000 klatek; nie używać pełnego renderu jako pierwszej walidacji.

## Werdykt

**PRE-USB SNAPSHOT FOUND: NO** — nie znaleziono kompletnego, dokładnego snapshotu worktree bezpośrednio przed pierwszym dirty USB/local-scratch/Stage-A.

**SAFE SURGICAL ROLLBACK POSSIBLE: YES (MEDIUM confidence)** — obecny diff, raporty i committed oracles pozwalają zaplanować rollback na poziomie funkcji/hunków, ale nie udowadniają jeszcze jednoznacznego zestawu hunks ani zgodnej DLL. Nie wykonano żadnego rollbacku.

Po tym raporcie audyt zatrzymano. 
