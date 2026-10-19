# SportCamHUD — Git po instalacji: zabezpieczenie i commity lokalne

Data: 2026-10-19 · Repo: `C:\_DEV\SportCamHUD` · Gałąź: `main` · Autor commitów: `Piotr <piotr@bikeridehud.local>` (podany per commit, bez zmiany konfiguracji git)

## 1. Środowisko
- git 2.56.0 (`C:\tools\Git\cmd`). PATH odświeżono z rejestru. Uwaga: po odświeżeniu `python` wskazuje na 3.14 bez numpy; testy uruchamiano jawnie `pythoncore-3.15-64\python.exe`.
- `origin = https://github.com/malcerz/TeleM.git`. `user.name` / `user.email` nie są skonfigurowane.

## 2. Stan GitHuba — PROBLEM
- `git fetch`: **`origin/main` force-update `e21d625 → ae57717`** (10 commitów NVIDIA/runtime, ostatni 2026-10-01). Gałęzie `origin/backup/*` zostały **usunięte** na GitHubie.
- Wspólny przodek z lokalnym `main`: `cd7c3c4` (2026-09-29). **Żaden ref na GitHubie nie zawiera `e21d625`** → 139 commitów z 2026-09-30…10-17 istniało wyłącznie lokalnie.
- Nic nie zostało wypchnięte. Uzgodnienie historii z GitHubem (merge/rebase/push) wymaga osobnej decyzji.

## 3. Zabezpieczenie (przed commitami)
- `C:\GoPro\TeleM_backup_20261018\TeleM_all_refs_20261018.bundle` — wszystkie refy (`git bundle verify`: OK, 1,79 GB).
- `uncommitted_tracked_20261018.patch` (`git diff --binary HEAD`), `untracked_tree\` (324 nieśledzone pliki ze strukturą katalogów) i `untracked_files_20261018.zip`.
- Lokalny tag adnotowany `safety/pre-commit-20261018` → `e21d625`. Lokalne gałęzie `backup/amd-release-checkpoint-20261017` (`e21d625`) i `backup/main-before-amd-release-20261017` (`3adc9ad`) pozostały nienaruszone.

## 4. Commity (HEAD przed: `e21d625`, po: patrz niżej)
| Commit | Zakres |
|---|---|
| `835d857` feat(intel): QSV HEVC slice QP / VBR control, runtime capabilities and live A/V mux | wcześniejsze zadanie: `src/ffmpeg/*`, `live_av_mux.py`, `intel_telemetry.py`, `telem_intel_native.c`, testy/narzędzia Intel, `build_portable_release.py`, `application.py` (harness), `render_tab.py` i `render_mixin.py` w wersji **sprzed SmartSync** |
| `6fa9a1d` fix(gui): generation-tagged project load state, clear project and license panel | wcześniejsze zadanie: `main_window`, `load_tab`, `settings_tab`, `license_dialog`, test i narzędzia GUI; `project_mixin`, `signals`, `controller` w wersji **sprzed SmartSync** |
| `67dfce7` docs(raport): Intel QSV/VBR/QP, GUI recovery and DJI sync-loss audit reports | wcześniejsze raporty i katalogi dowodów w `Raporty/` |
| `6d41d1e` feat(sync): telemetry sync contract and SmartSync IMU offset estimation | `telemetry_sync.py`, `telemetry_smartsync_imu.py`, `telemetry_manager.py`, `telemetry_active_time.py`, `render_preparation.py` |
| `535fb7a` feat(sync): telemetry sync panel, async SmartSync and per-material persistence | `sync_mixin`, panel, `property_editor`, `preset_mixin`, `__init__`, oraz **wyłącznie hunki sync** w `project_mixin`, `render_mixin`, `render_tab`, `signals`, `controller`; testy sync |
| `d79a682` docs(raport): SmartSync DJI IMU restore report | raport SmartSync |
| (ten) docs(raport): git safety report | niniejszy raport |

Separacja plików mieszanych: do commitów wcześniejszych trafiła dokładnie zawartość z kopii sprzed zadania SmartSync (`git hash-object` + `update-index --cacheinfo`). Do commitów sync trafiła wersja bieżąca. Weryfikacja: w `67dfce7` jest 0 odwołań do kodu sync; diff `67dfce7..d79a682` obejmuje wyłącznie 19 plików sync (+2560/−45).

## 5. Poza commitami (celowo)
- `def_layout.json` — prywatna zmiana `auto_activity_source` (jak w poprzednich etapach).
- `C` — zbłąkany plik CSV statystyk enkodera (321 B).
- `RAPORT_INTEL_HEVC_SLICE_QP_20261017.md` w katalogu głównym — duplikat różniący się od wersji w `Raporty/`. Raporty mają być tylko w `Raporty/`; do decyzji.
- `third_party/Digital-7 Mono PL.ttf` — brak odwołań w kodzie; do decyzji.
- `runtime/intel/bin/*.dll.bak_*` — kopie DLL objęte `.gitignore` (`*.dll`).

## 6. Testy
- HEAD po commitach (sync, telemetria, mapa, preparacja, walidacja FIT/GPX, GUI recovery, live mux, Intel VBR): **169 passed, 1 skipped**.
- Pełny pakiet vs stan sprzed SmartSync (osobne procesy, izolowany AppData): **0 nowych regresji**; 137 faili / 18 errorów istniało wcześniej (szczegóły w `RAPORT_SMARTSYNC_DJI_IMU_RESTORE.md`).
- Zależności: commit Intel nie wymaga GUI recovery. Commit GUI zawiera komplet sygnałów (`sig_project_load_state`, `sig_project_cleared`) i `license_dialog` używane przez `main_window` / `settings_tab`. Pośrednie commity nie były osobno testowane — testowano stan końcowy i stan bazowy.

## 7. Cofanie
- Cofnięcie wszystkich nowych commitów bez utraty pracy: `git reset --soft safety/pre-commit-20261018` (zmiany wracają do indeksu). Wymaga zgody, nie wykonano.
- Pełne odtworzenie: bundle z pkt 3 oraz patch i kopia plików nieśledzonych.

## 8. Ograniczenia
- SmartSync DJI **nie jest w pełni przetestowany**: realny DJI Action 6 nie ma danych IMU (EIS włączone, `djmd` 134 B/klatkę), brak FIT z dnia nagrania, a natywny parser DJI (cp314) nie działa w Pythonie 3.15 używanym przez aplikację na tej maszynie.
- Brak push; rozbieżność z `origin/main` pozostaje do rozstrzygnięcia przez użytkownika.
