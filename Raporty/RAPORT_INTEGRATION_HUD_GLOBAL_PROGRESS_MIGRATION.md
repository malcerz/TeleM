# TeleM — migracja AMD HUD global progress do repo integracyjnego

## Worktree i stan początkowy

| Worktree | Branch | HEAD | Stan przed migracją |
|---|---|---|---|
| `C:\_DEV\TeleM` | `amd-render` | `7e4e34e` | dirty: liczne usunięcia artefaktów, zmiany `def_layout.json`/scratch oraz niezatwierdzony diff progressu |
| `C:\_DEV\TeleM-integration` | `integration/intel-amd` | `feb0482` | clean |

Stare repo zostało użyte wyłącznie jako źródło porównania i nie było modyfikowane podczas migracji.

## Audyt starego diffu

Poprzedni etap nie był osobnym commitem. Rzeczywisty diff obejmował:

- nowy `src/render_progress.py` z `RenderProgressTracker`, estymacją kosztu HUD/renderu, monotonicznym globalnym mappingiem, adaptacją render FPS i throttlingiem callbacku;
- opcjonalny `progress_cb` w `build_telemetry_cache`, milestone’y etapów wektorowych oraz iteracyjny raport `frame records`;
- podłączenie AMD exportera do worker initialization, map preload, telemetry cache, native HUD resources, klatek, finalize i completion;
- GUI `RenderTab._on_render_progress` obsługujące `global_pct` z monotonicznym guardem;
- raport starego etapu, którego nie kopiowano.

## Różnice architektoniczne

Repo integracyjne zachowuje tę samą sygnaturę AMD `on_render_progress(completed, total, elapsed, fps, hud_state)` oraz tę samą architekturę telemetry cache/exportera. Nie istnieje w nim wcześniejszy wspólny tracker globalnego kosztu. Intel i NVIDIA nadal używają dotychczasowego kontraktu fazowego/klatkowego; ich ścieżek wykonawczych nie zmieniano.

## Przeniesione i zaadaptowane

Przeniesiono selektywnie cztery fragmenty logiczne:

1. `src/render_progress.py` — tracker backend-neutralny.
2. `src/telemetry_precompute.py` — opcjonalny callback i rzeczywiste jednostki pracy cache.
3. `src/ffmpeg/amd_native_exporter.py` — callbacki w AMD native path i finalne 100% po sukcesie.
4. `src/gui/qt/tabs/render_tab.py` — odczyt `global_pct` bez resetu paska.

Nie przeniesiono: zmian layoutu, binariów AMD, artefaktów scratch, benchmarków, zmian Intel/NVIDIA oraz raportu ze starego worktree.

## Testy

- `compileall` modułów migracji: PASS.
- Istniejące testy telemetry cache: `22 passed`.
- Test `RenderProgressTracker`: PASS; global sequence monotonic, completion `100.0`.
- AMD native smoke: NOT RUN — integration worktree nie zawiera kanonicznych `Video/GX020079.MP4` i `Video/GX020079.fit`; nie skopiowano danych zewnętrznych ani nie użyto nieautoryzowanego pairing’u.
- Intel smoke: NOT RUN; wykonano compile/import wspólnego modułu, bez zmian w Intel exporterze.

## Ochrona backendów

Zmiany AMD są selektywne. Nowy tracker jest importowany wyłącznie przez AMD native exporter, a callback w telemetry cache jest opcjonalny, więc istniejące wywołania Intel/NVIDIA zachowują kompatybilność. Nie zmieniono ich renderingu, urządzeń, encoderów ani filtrów.

## Zmienione pliki

- `src/render_progress.py`
- `src/telemetry_precompute.py`
- `src/ffmpeg/amd_native_exporter.py`
- `src/gui/qt/tabs/render_tab.py`
- `Raporty/RAPORT_INTEGRATION_HUD_GLOBAL_PROGRESS_MIGRATION.md`

## Diff stat

Stan po migracji (bez raportu i nowego pliku, których `git diff --stat` nie pokazuje jako untracked):

```text
 src/ffmpeg/amd_native_exporter.py | 42 ++++++++++++++++++++-------------------
 src/gui/qt/tabs/render_tab.py     |  9 +++++++++
 src/telemetry_precompute.py       | 20 +++++++++++++++++++
 3 files changed, 51 insertions(+), 20 deletions(-)
```

## Verdict

PARTIAL — migracja logiczna zakończona, testy cache/tracker/import przechodzą. AMD runtime smoke oraz Intel runtime smoke pozostają NOT TESTED z powodu braku danych w integration worktree. Nie wykonano commit ani push.

## LONG RUNTIME VALIDATION — GX010115

Walidację wykonano z kodu `TeleM-integration`, używając wejść read-only ze starego repo:

- MP4: `C:\_DEV\TeleM\Video\GX010115.MP4`
- FIT: `C:\_DEV\TeleM\Video\GX010114_116.fit` — jedyny FIT obejmujący sekwencję `GX010114→GX010116`, potwierdzony przez `BENCHMARKS.md`.
- długość źródła: `592.597333 s` (ffprobe)
- renderowany fragment: `60 s`, `1800` klatek, 3840×2160, AMD native
- output/log: `C:\_DEV\TeleM-integration\scratch\integration_hud_progress_gx010115_60s.mp4` / `.log`

### Pomiary

| Metryka | Wynik |
|---|---:|
| HUD actual duration | 2.178 s |
| HUD estimate/cost przy zakończeniu | 2.178 s (pomiar bieżącego eksportu) |
| Render estimate przed klatkami | 68.288 s (26.359 FPS baseline) |
| HUD global weight | 3.07% |
| global_pct po HUD | 3.0688% |
| actual HUD share / total actual | 2.4787% (2.178 / 87.869 s) |
| błąd global_pct vs actual HUD share | 0.5901 pp |
| render actual duration | 79.437 s |
| actual render FPS | 22.660 FPS (render wall); 20.937 FPS end-to-end |
| actual total duration | 87.869 s export wall; 85.971 s measured native end-to-end |
| predicted total przed renderem | 70.966 s (`2.178 + 68.288 + 0.5`) |
| stabilized predicted total | 82.115 s (`2.178 + 79.437 + 0.5`) |
| stabilized predicted vs actual export wall | −5.754 s / −6.55% |

### Progress i GUI

Log potwierdził regularny wzrost HUD progressu (`1.03% → 2.73% → 2.98% → 3.07%`) oraz regularny wzrost progressu klatek (`3.07% → 99.83%`). Przejście HUD → render nie resetowało ani nie cofało paska. `100%` pojawiło się dopiero po flush, mux i kompletnej finalizacji outputu.

Callback AMD → `RenderTab._on_render_progress` został zweryfikowany w długim runtime przez callback kontraktu (`GUI_PROGRESS`), a headless Qt `RenderTab` smoke przeszedł wszystkie 12 kontroli (`SMOKE PASS`). Throttling trackera ogranicza emisję do około 10 Hz / 0.25 pp. Nie zaobserwowano wielosekundowego martwego odcinka podczas faktycznej pracy HUD; telemetry cache zakończył się w 68.2 ms.

Intel safety: `compileall`, import/API compatibility oraz istniejące testy cache przechodzą; Intel exportera nie zmieniano. Pełny Intel runtime smoke pozostaje poza tym testem.

### Zaktualizowany verdict

PASS — długi AMD runtime potwierdził monotoniczny cost-based progress, poprawne HUD → render → finalize → 100% oraz brak regresji API Intel. Pełny 592-sekundowy eksport i pełny Intel runtime nie były wykonywane.
## TIMELINE PROGRESS + LOG CLEANUP

### Root cause and implementation

The previous `timeline` report covered a single callback around several list
comprehensions. The long operation was the four per-frame transformations in
`build_telemetry_cache` (`src/telemetry_precompute.py`): target datetime
resolution/fallback, UTC normalization, local date/time formatting, and naive
timestamp-array preparation. Because the callback was emitted only after all
four operations, the GUI could remain at `2/8` while work was active.

The implementation now reports `timeline` as `4 * total_frames` real units,
with bounded approximately 1% callback cadence and a final `done == total`
event. The AMD exporter maps that stream to the existing HUD cost range
`2.0/8.0 .. 4.5/8.0`; `frame records` continues from `4.5/8.0 .. 6.0/8.0`.
The aggregate stage counter uses `timeline complete`, so it cannot emit the
old misleading `1/N` reset. `RenderProgressTracker` keeps its monotonic global
guard and adapts the HUD estimate from measured work while rendering updates
the render estimate from observed FPS.

`RenderTab` now displays `HUD: done / total` during preparation and `Frame:`
during rendering. The existing global estimator and preview timestamp path are
preserved.

### Log policy

`src/render_logging.py` defines the single switch `TELEM_RENDER_DEBUG`.
Normal mode retains errors, warnings, cancellation/failure diagnostics, and
the short summary; detailed progress, timing tables, AMD configuration, and
native success chatter are muted. `TELEM_RENDER_DEBUG=1` restores detailed
Python and native diagnostics. Native `std::cout` was gated in
`native/d3d11_amf_pipeline/src/telem_amd_native.cpp`; `std::cerr` remains
visible for errors/warnings.

### Validation

- `python -m compileall -q src`: PASS.
- Timeline contract: PASS; 25-frame synthetic cache emitted `0/100` through
  `100/100`, monotonic, and produced 25 records.
- Targeted cache/timeline tests: PASS (`32 passed`).
- AMD runtime on `GX010115.MP4` + authoritative `GX010114_116.fit`, 3840x2160,
  GPU map, GPU HUD, 120 frames: PASS. Output contained 120 video frames and
  audio; HUD prepare `0.843 s`, render `6.120 s`, finalize `0.431 s`, total
  `7.903 s`, render FPS `19.608`, effective FPS `15.185`.
- Fresh MSVC DLL build from TeleM-integration sources: PASS. Compiler MSVC
  `19.44.35228.0`, generator `Visual Studio 17 2022`, x64 Release, fresh DLL
  size `204288` bytes, SHA256
  `24FFB5CB7A9308FBD59BE382334592B248158AC9A3F16A8001BA5C26BF37C519`.
  Frozen oracle was preserved at
  `native/d3d11_amf_pipeline/bin/telem_amd_native.dll`, SHA256
  `D309A73551E80A61DC1AD8F6EDB5E47EA0C519927D995F4C7BA7F6390E3E846E`.
- Log modes: PASS; normal smoke showed the short summary and no native
  success/progress stream, while debug smoke restored detailed diagnostics.
- Full pytest: `1126 passed, 37 skipped, 56 failed, 5 errors`. The failures
  are pre-existing/out-of-scope baseline issues (missing integration `Video`
  fixtures, dirty layout/native source expectations, and unrelated indicator/
  timeline tests); direct cache/render-tab/logging checks pass.

### Changed files for this task

- `src/render_logging.py`
- `src/render_progress.py`
- `src/telemetry_precompute.py`
- `src/ffmpeg/amd_native_exporter.py`
- `src/gui/qt/tabs/render_tab.py`
- `native/d3d11_amf_pipeline/src/telem_amd_native.cpp`

Ignored build/scratch outputs are validation artifacts only. No commit or push
was performed. No Intel or NVIDIA rendering path was changed.

### Verdict

PASS — real timeline progress and default quiet render logging are implemented
and validated. Full-suite status remains PARTIAL because of the pre-existing
out-of-scope failures listed above.
## FULL CONSOLE CLEANUP

### Audit and normal-log result

The full AMD render-path audit followed GUI export preparation, FIT/GPMF and
SmartSync, telemetry preparation, HUD/map preparation, AMD native creation,
encode, mux, and completion. The representative captured log was made with
`GX010115.MP4` and the authoritative `GX010114_116.fit`, using the fresh DLL
build and the existing 3840x2160 AMD path.

| Capture | Lines |
|---|---:|
| NORMAL before this cleanup | 703 |
| NORMAL after this cleanup | 12 |
| DEBUG after this cleanup | 360 |

The 12-line normal capture includes the four-line smoke harness banner and the
final harness line. The renderer itself contributes only the eight-line final
summary. No renderer progress, SmartSync, FIT, cache, AMD configuration, or
native success stream remains in normal mode.

Main muted groups:

- FIT/GPX discovery and synchronization details;
- SmartSync candidate/trajectory metrics;
- `TelemetryManager` field and sample inventories;
- HUD resolution, map preload/cache statistics, and telemetry stages;
- AMD/Intel/NVIDIA path and device configuration diagnostics;
- D3D11/AMF/native success messages and per-frame statistics;
- progress callbacks, timing tables, benchmark counters, command/filter dumps,
  and historical ETAP/audit messages.

The remaining normal output is intentional: the final summary, true errors,
meaningful warnings/fallbacks, cancellation messages, and failure details.
The smoke harness banner is test-script output, not production renderer output.
Startup/test-mode messages in `src/gui/qt/application.py` and layout warnings
remain outside the click-to-completion render interval.

### One-switch debug policy

`src/render_logging.py` is the shared policy. `TELEM_RENDER_DEBUG` is the only
switch: unset/false gives the quiet policy, while `TELEM_RENDER_DEBUG=1`
restores the detailed Python and native streams. Existing timing calculations,
FPS, HUD estimator, global progress, and profile data are unchanged. Native
`std::cout` is gated at export creation in
`native/d3d11_amf_pipeline/src/telem_amd_native.cpp`; native `std::cerr` is
not redirected. FFmpeg already uses `-loglevel error` for the progress pipe,
and remux stderr is now included in the visible failure warning. Encode
parameters are unchanged.

Example normal output:

```text
=== RENDER COMPLETE ===
Frames: 60
HUD prepare: 0.914 s
Render: 2.873 s
Finalize: 4.985 s
Total: 9.256 s
Render FPS: 20.886
Effective FPS: 6.482
```

### Tests

- NORMAL AMD smoke: PASS; 60 frames, audio preserved, 12 captured lines.
- DEBUG AMD smoke: PASS; 360 lines, including SmartSync, timeline progress,
  native diagnostics, render timings, and `USER EFFECTIVE FPS`.
- Fresh native AMD DLL remains the tested isolated build from the previous
  section; frozen oracle remains preserved and untouched.
- Targeted regression suite: `45 passed`.
- `python -m compileall -q src`: PASS.
- `git diff --check`: PASS (only standard LF/CRLF warnings from Git).
- Full pytest baseline remains `1126 passed, 37 skipped, 56 failed, 5 errors`;
  those failures are unrelated pre-existing fixture/layout/native-source
  baseline issues documented above, not console-policy failures.

### Changed files

This cleanup added the shared policy to the render-facing modules:

- `src/render_logging.py`
- `src/ffmpeg/amd_native_exporter.py`
- `src/ffmpeg/streaming.py`
- `src/ffmpeg/command_builder.py`
- `src/ffmpeg/second_pass.py`
- `src/ffmpeg/intel_backend.py`
- `src/benchmark.py`
- `src/multifile.py`
- `src/moving_map.py`
- `src/indicators/gpu_compositor.py`
- `src/gui/telemetry_manager.py`
- `telemetry_fit.py`
- `telemetry_gpx.py`
- `native/d3d11_amf_pipeline/src/telem_amd_native.cpp`
- `Raporty/RAPORT_INTEGRATION_HUD_GLOBAL_PROGRESS_MIGRATION.md`

Current `git diff --stat` for the worktree is:

```text
17 files changed, 337 insertions(+), 63 deletions(-)
```

The stat includes the pre-existing dirty `def_layout.json` and
`src/gui/qt/application.py` changes; they were preserved and not modified by
this cleanup. No renderer behavior, pixels, synchronization, cache semantics,
Intel/NVIDIA pipeline, AMD pipeline, or encode parameters were changed. No
commit and no push were performed.

## LOAD PROGRESS — GPMF 55% STALL FIX

Root cause: `bg_load` emitted a fixed 55% immediately before
`load_gpmf_records()`. Existing callbacks only logged after each extractor and
were not connected to `sig_progress`; the Qt signal path itself was not
blocked.

`src/load_progress.py` now maps GPMF to a monotonic 45–72% interval using the
measured representative costs track 3.34 s, ISO 6.29 s, exposure 5.95 s,
temperature 3.11 s, accelerometer 3.84 s, and gyroscope 4.31 s. Timed
ISO/SHUT/TMPC extraction and ACCL/GYRO loops report optional `done/total`
progress through a roughly 120 ms / percentage-change throttle. GUI labels
identify each GPMF substage. No artificial timer or `processEvents()` was added.

`[LoadProfile]` and `[LoadProfile:GPMF]` are silent normally and enabled with
`TELEM_LOAD_PROFILE=1`. The GPMF/cache/manager tests passed (`36 passed,
2 skipped`) and the tracker test passed. Long-file GUI validation is
**NOT TESTED** here; responsiveness and exact before/after traces are
**NOT PROVEN**. No GPMF parsing optimization, commit, or push was performed.

Changed files: `src/load_progress.py`, `src/telemetry_extract.py`,
`src/gui/telemetry_manager.py`, `src/gui/qt/_mixins/project_mixin.py`,
`tests/test_load_progress.py`, and this report.

### Cleanup verdict

PASS — normal render console is quiet, debug diagnostics remain available, and
errors/warnings/cancellation remain visible. No optimization was performed.
