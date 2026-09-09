# AMD CHILD — EXITCODE 120 / STDERR / INVALID HANDLE FIX

## Zadanie

Naprawa wyłącznie lifecycle `AMD_NATIVE_D3D11` child process: exit code 120,
utrata `sys.stderr` i nieprawidłowy odziedziczony Windows HANDLE. Nie zmieniano
renderera, HUD, single-pass A/V, Intel ani NVIDIA. Nie wykonano renderu 85574f.

## Stan początkowy i root cause

`_child_entry()` wykonywał `os.dup2(log_file.fileno(), 1/2)`, ale pozostawiał
oryginalne obiekty `sys.stdout`/`sys.stderr` (w tym obiekt zamknięty albo
odziedziczony z nieprawidłowym HANDLE). Następnie zamykał plik diagnostyczny bez
jawnego przywrócenia streamów. Podczas finalizacji interpretera Python flushuje
standardowe streamy; zamknięty/nieprawidłowy fd 2 powodował `OSError(9,
WinError 6)` i końcowy exit code 120. Ten mechanizm został odtworzony w macierzy
spawn dla `sys.stderr=None` i zamkniętego stderr.

Drugim blockerem był brak gwarancji wysłania wyjątku występującego przed
pełnym bootstrapem. IPC emitter był uruchamiany dopiero po części konfiguracji
stdio, więc `print()`/`traceback.print_exc()` nie były bezpiecznym kanałem.

## Implementacja

Zmieniono `src/ffmpeg/amd_child_process.py`:

- dodano `_ChildStdioRedirect`, który zachowuje oryginalne streamy, kieruje
  Python i native C stdio do niezależnych wrapperów logu oraz przywraca używalne
  streamy (albo otwarty `os.devnull`) przed zamknięciem logu;
- przed/po redirect oraz przed restore można włączyć
  `AMD_CHILD_HANDLE_DIAGNOSTICS=1`; low-level `os.open/os.write` zapisuje
  niezależnie od `sys.stderr` typ, fileno i walidację `GetFileType`/
  `GetHandleInformation` dla fd 1/2;
- emitter IPC startuje przed filesystem/stdio bootstrapem; każdy `BaseException`
  ma terminalną wiadomość `kind=error`, `phase=bootstrap/startup` albo
  `phase=render`, traceback i ścieżkę diagnostyki;
- diagnostyczny log pozostaje po sukcesie tylko przy jawnej fladze diagnostycznej;
  domyślny cleanup produkcyjny nadal go usuwa.

Zmieniono testy `tests/test_amd_child_process.py`:

- spawn matrix: normal stdout/stderr, przekierowanie, `sys.stderr=None`,
  zamknięty stderr — każdy child kończy się `exitcode=0`, nigdy 120;
- bootstrap exception jest odebrany przez IPC z fazą `bootstrap/startup`;
- sprawdzane są low-level wpisy `phase=entry` i `phase=before_restore`.

W harnessie testowym `scratch/run_amd_child_final_gui_acceptance.py` dodano
wyłącznie przełącznik `TELEM_ACCEPTANCE_SINGLE_FILE_TWICE=1`, aby wykonać dwa
single-file przebiegi w jednym GUI.

## Testy automatyczne

```text
python -m py_compile src/ffmpeg/amd_child_process.py tests/test_amd_child_process.py
python -m pytest -q tests/test_amd_child_process.py
9 passed

python -m pytest -q tests/test_amd_child_process.py \
  tests/test_amd_child_spawn_real.py \
  tests/test_amd_gui_range_contract.py \
  tests/test_amd_direct_mp4_mux.py
26 passed, 2 skipped (opt-in hardware tests)

git diff --check: PASS
```

## Real AMD GUI smoke — 1000f ×2

Uruchomiono normalny `QApplication → AppController → MainWindow →
RenderTab._on_render()` dla `D:\GoPro\2026-09-01\GX010244.MP4`, AMD native,
pełny HUD i GPU Preview ON. Oba przebiegi wykonano bez restartu GUI.

Wyniki:

| Run | Frames | Terminal | Child exit | Preview | Residue | Next render |
|---|---:|---|---:|---:|---|---|
| `single_1` | 1000/1000 | completed | 0 | 67 | none | ready |
| `single_2` | 1000/1000 | completed | 0 | 67 | none | ready |

Oba pliki mają:

```text
video: HEVC 3840x2160, 30000/1001, nb_frames=1000, duration=33.366667 s
audio: AAC, 48000 Hz, stereo, duration=33.386667 s
```

Logi childów potwierdzają dla obu PID-ów:

```text
[AMD CHILD HANDLE] phase=entry ... fd1.handle_valid=True fd2.handle_valid=True
[AMD CHILD HANDLE] phase=after_redirect ... fd1.handle_valid=True fd2.handle_valid=True
[AMD CHILD START]
[AMD CHILD JOB RESTORED]
[AMD CHILD RENDER START]
[AMD CHILD NATIVE INIT]
[AMD CHILD HANDLE] phase=before_restore ... handle_valid=True
```

Artefakty i logi znajdują się wyłącznie na D::

```text
D:\TeleM_exit120_acceptance_twice_diag_20260908_224001\
```

`acceptance_results.json` ma dla obu rekordów puste `acceptance_failures`,
`child_exited=True`, `rendering=False`, aktywny przycisk Render, widoczny slot
Preview i pustą listę residue. Nie wykryto orphan childa.

## Ocena

```text
ROOT CAUSE IDENTIFIED: PASS
NO INVALID STDERR HANDLE: PASS
NO LOST SYS.STDERR: PASS
NO EXITCODE 120: PASS
BOOTSTRAP ERROR VIA IPC: PASS
NORMAL CHILD EXITCODE 0: PASS
REAL AMD 1000F x2: PASS
PREVIEW RESTORE: PASS
NO ORPHAN: PASS

STATUS: READY FOR FINAL 85574 SINGLE-PASS PROOF
```

Pełny render 85574f pozostaje niewykonany zgodnie z zakresem zadania. Nie
wykonano commit ani push.
