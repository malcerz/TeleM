# RAPORT — SPORTCAMHUD: DOKOŃCZENIE USTAWIEŃ + KONFIGUROWALNE LOGOWANIE AMD

Data: 2026-10-15
Gałąź: `fix/gui-freeze-hud-composite`
Stan początkowy: HEAD `7272c5f` (po `1f7f8e0` settings, `7272c5f` QP)
Stan końcowy: HEAD `f14e45f`

STATUS: **PASS** (testy poprawności; pełny eksport AMD na sprzęcie — NOT TESTED, patrz pkt 12)

## 0. Stan początkowy working tree

Przed pracą zmodyfikowane przez użytkownika: `def_layout.json`, `src/ffmpeg/intel_native_exporter.py`,
`src/ffmpeg/nvidia_native_exporter.py`, `Raporty/RAPORT_SPORTCAMHUD_ETAP_5R_F_LIVE_MUX_AUDIO_FINALIZATION.md`
oraz wiele nieśledzonych plików (`Raporty/…`, `runtime/amd/`, `src/ffmpeg/live_av_mux.py`, `tests/test_live_av_mux.py`).
Nie zostały dotknięte ani dodane do commitów. `def_layout.json` w repozytorium: SHA-256
`9cdb9cd788a872694a1016dc2eb4e7b9606be81e539fa7108ff4dfb226164111` przed i po pracy (mtime 2026-10-15 08:15:52, bez zmian).

## 1. Przyczyna niespójności ustawień

- **Startowy preset**: `edit_startup_preset.textChanged` emitował `sig_settings_changed("startup_preset")`,
  a kontroler przy **każdym znaku** zapisywał `_startup_preset` do `def_layout.json`. Jednocześnie zielony
  przycisk (zapis layoutu) zerował `_startup_preset` w `def_layout.json` i w pamięci — wartość wpisana
  i „zapisana” znikała. Pole nie było też odtwarzane w formularzu po restarcie.
- **„Wyczyść” przy folderze eksportu** od razu utrwalał tryb automatyczny (`save_default_export_dir("")`),
  z pominięciem zielonego przycisku.
- **„Pomiń pauzy” po kolejce**: `_restore_job_snapshot_onto_controller` podmienia `ctrl.layout` na kopię
  snapshotu zadania i nic go nie przywracało — podgląd po zadaniu używał wartości ze snapshotu.

## 2. Zmienione pliki

Commit 1 `25eb07e` fix(settings): finalize unified preferences persistence
- `src/export_paths.py` — `load_startup_preset(base_dir)` (profil → legacy `_startup_preset` z def_layout tylko do odczytu → "").
- `src/gui/qt/tabs/settings_tab.py` — brak autozapisu startowego presetu; odtwarzanie pola przy starcie;
  zielony przycisk zapisuje `startup_preset` i po zapisie layoutu przekazuje wartość kontrolerowi;
  „Wyczyść” czyści tylko pole.
- `src/gui/qt/_mixins/preset_mixin.py` — `startup_preset` aktualizuje wyłącznie stan w pamięci (bez zapisu def_layout.json).
- `src/gui/qt/controller.py` — przy starcie `_startup_preset_path = load_startup_preset(base_dir)`.
- `src/gui/qt/tabs/render_tab.py` — `_restore_controller_global_preferences()` wywoływane w `_end_render`.
- `tests/test_default_export_dir_settings.py` — test zaktualizowany do nowego kontraktu „Wyczyść”.

Commit 2 `f14e45f` feat(logging): configurable AMD export log beside output MP4
- `src/ffmpeg/amd_export_log.py` (nowy) — ścieżka logu, rozstrzyganie flagi, nagłówek/koniec sesji, append bez fsync.
- `src/ffmpeg/amd_child_process.py` — `run_amd_render_child(..., export_log_path=None)`; log zawsze w trybie append;
  OFF → stdio dziecka do `os.devnull`, brak pliku; postęp kodowania co ≥10 s; traceback błędu w logu;
  `diagnostics_path` w szczegółach błędów lifecycle/no-terminal.
- `src/gui/qt/_mixins/render_mixin.py` — rozstrzygnięcie flagi i ścieżki logu po ustaleniu ostatecznej ścieżki MP4,
  nagłówek sesji przed preflight/spawn, przekazanie ścieżki do dziecka, status końca sesji (completed/cancelled/failed),
  wskazanie logu w komunikacie błędu GUI.
- `src/gui/qt/tabs/settings_tab.py` — checkbox „Zapisuj log eksportu AMD” (Wydajność, domyślnie ON), zapis zielonym przyciskiem, odtwarzanie.
- `src/gui/qt/_mixins/preset_mixin.py`, `src/gui/qt/controller.py` — stan `amd_export_logging_enabled` w kontrolerze.
- `src/gui/qt/tabs/render_tab.py` — snapshot flagi w opcjach zadania przy dodaniu do kolejki.
- `src/export_paths.py` — `load_amd_export_logging_enabled()` (domyślnie True).
- `tests/test_amd_child_process.py` — test bootstrap: log obok MP4 zamiast `scratch/amd_child_*.log`.
- `tests/test_settings_and_amd_export_logging.py` (nowy, 21 testów).

## 3. Zapis i restart

Wszystkie ustawienia z zakładki zapisuje zielony „Zapisz ustawienia” do
`%APPDATA%\SportCamHUD\app_preferences.json`: `default_export_dir`, `startup_preset`, `charts_skip_pauses`,
`amd_export_logging_enabled`, `ui_language`, `ui_theme`; następnie istniejący, świadomy zapis layoutu
(font, obramowanie, layout) do `def_layout.json` — bez zmian.

Wyniki (izolowany APPDATA, tymczasowy base_dir):
- startowy preset: wpis bez kliknięcia → brak w profilu, def_layout.json bez zmian, kontroler bez zmian; po kliknięciu → zapisany;
  po „restarcie” (nowy SettingsTab + AppController) odtworzony; wyczyszczenie też wymaga kliknięcia — PASS
- legacy `_startup_preset` z def_layout odczytany bez zapisu — PASS
- „Wyczyść” folder: czyści pole, profil bez zmian aż do kliknięcia, potem `""` — PASS
- komplet ustawień (folder, preset, pauzy, log AMD, język) po restarcie — PASS

## 4. „Pomiń pauzy” po kolejce

`_end_render` (wspólny koniec dla sukcesu, błędu i anulowania, także zadań kolejki) nakłada globalną wartość
na `ctrl.layout` i odświeża podgląd (`_chart_data_cache=None`, `_render_preview`). Snapshot zadania (`job.layout`)
nie jest modyfikowany; kolejne zadanie przywraca własny zamrożony snapshot. Algorytm pauz i synchronizacja FIT/GPX — bez zmian.
Test: zadanie z snapshotem OFF przy globalnym ON, zakończenie `completed`/`cancelled`/`failed` → podgląd ON,
snapshot OFF niezmieniony, następne zadania OFF/ON dostają własne wartości — PASS (3 warianty).

## 5. Lokalizacja i nazewnictwo logów

- `D:\GoPro\SCH\20261015-0752.mp4` → `D:\GoPro\SCH\20261015-0752.log`; `A:\20260827-1505.mp4` → `A:\20260827-1505.log`.
- Nazwa z ostatecznej ścieżki eksportu (`.mp4` → `.log`); `.part` / `.part.mp4` nigdy nie wyznacza nazwy.
- Brak katalogu `scratch`, brak `amd_child_*.log` (ani w scratch, ani w AppData). Historyczne logi w scratch nietknięte.
- Ponowny eksport pod tę samą nazwę dopisuje sesję oddzieloną linią `=====` z datą, PID, `job_id`, `generation`, trybem (DIRECT/QUEUE).
- Ścieżka MP4 i jego nazwa — bez zmian.

## 6. Przekazywanie przełącznika do child process

GUI checkbox → `sig_settings_changed` → `ctrl.amd_export_logging_enabled`.
Kolejka: `_on_add_to_queue` zamraża `options["amd_export_logging_enabled"]` (późniejsza zmiana nie wpływa na dodane/uruchomione zadania).
`_render_pipeline`: `resolve_amd_export_logging(options, ctrl.amd_export_logging_enabled)` — snapshot zadania ma pierwszeństwo,
eksport bezpośredni bierze bieżące ustawienie → `options["_amd_export_log_path"]` → `run_amd_render_child(export_log_path=…)`
→ argument `diagnostics_path` procesu potomnego (pusty = OFF). Konfiguracja uruchomionego eksportu się nie zmienia.

## 7. Zachowanie logu

- Sukces: log zostaje, `status=completed output=…`.
- Błąd: log zostaje, `[AMD CHILD ERROR]` + `[AMD CHILD TRACEBACK]` z dziecka i `status=failed` z błędem i tracebackiem z rodzica;
  komunikat GUI: `Lokalizacja: <MP4>` i `Log: <ścieżka .log>`.
- Anulowanie: log zostaje, `status=cancelled`.
- Błąd przed zapisem MP4 (np. preflight źródeł): nagłówek sesji już istnieje → log jest.
- Uchwyty: dziecko zamyka plik w `finally` przed wyjściem; rodzic pisze krótkimi append (open/write/close). Test: plik można od razu przemianować.
- OFF: brak pliku, renderer/FFmpeg/muxer bez zmian, błędy dalej w GUI (IPC).
- Zawartość: istniejące znaczniki zachowane (inicjalizacja, `[RUNTIME] native_dll=… sha256=…`, `[AMD ENCODER] rc=VBR …`,
  przygotowanie HUD, `[AMD DIRECT MUX FFMPEG] command=…`, Single Live Mux, `[AMD AAC PLAN]`, przejścia klipów, finalizacja).
  Nowe: nagłówek/koniec sesji, `[AMD EXPORT PROGRESS]` co ≥10 s, traceback. Bez logowania per klatka, bez fsync, bez dodatkowego FFmpeg.

## 8. Testy celowane (bez pełnego zestawu 200+)

| Test | Wynik |
|---|---|
| `tests/test_settings_and_amd_export_logging.py` (21) | PASS |
| `tests/test_settings_skip_pauses_persistence.py` (11) | PASS |
| `tests/test_amd_child_process.py` (12, realny spawn Windows) | PASS |
| `tests/test_default_export_dir_settings.py` (13) | PASS |
| `tests/test_amd_vbr_qp_status.py` (6) | PASS |
| `tests/test_render_progress_state_scope_hotfix.py` (5) | PASS |
| `tests/test_gui_v5_autosave_preview_and_aa.py` (6) | PASS |
| `tests/test_amd_queue_trim_snapshot.py` (5) | PASS |
| `tests/test_amd_qp_governance.py` (10) | PASS |
| `tests/test_config_cache_only.py` (3), `tests/test_activity_ux_timeline.py` (26) | PASS |
| `tests/test_gui_v3_runtime_acceptance.py::test_full_layout_persistence_contract` | PASS |
| commit 1 osobno (eksport indeksu): skip_pauses + default_export_dir (24) | PASS |

Pokrycie wymagań: A (ON: log obok MP4, nazwa, brak scratch, zostaje) — PASS; B (OFF: brak pliku, błąd w GUI) — PASS;
C (anulowanie: status w logu, uchwyty zamknięte) — PASS na poziomie rodzica, rzeczywiste anulowanie renderu w dziecku NOT TESTED;
D (błąd: log zostaje, GUI pokazuje ścieżkę) — PASS (realny proces potomny); E (dwa wyjścia → dwa logi, flaga w snapshocie
i do child, powtórny eksport dopisuje) — PASS; F (restart: checkbox ON/OFF, zapisany stan steruje tworzeniem logu) — PASS.

Porażki istniejące, identyczne na czystym HEAD (sprawdzone na kopii `git archive HEAD`), nie regresja:
`test_export_queue_basic.py::test_notify_render_done_success_queues_upload` (1 FAIL),
`test_font_persistence_v2.py::test_static_cache_cleared_on_indicator_font_change` (1 FAIL),
`test_amd_decode_gui_switch.py` (1 FAIL, potem zawieszenie — także na HEAD).

## 9. Commity

- `25eb07e` fix(settings): finalize unified preferences persistence
- `f14e45f` feat(logging): configurable AMD export log beside output MP4

Bez push. Commity rozdzielone na poziomie zawartości plików (staging przez `git hash-object`/`update-index`, bez zmian w working tree).

## 10. Working tree po commitach

Pozostały wyłącznie wcześniejsze zmiany użytkownika (`def_layout.json`, `intel_native_exporter.py`, `nvidia_native_exporter.py`,
raport 5R_F) i nieśledzone pliki. Ten raport nie jest commitowany.

## 11. Nienaruszalność renderera

Diff `7272c5f..f14e45f` nie obejmuje: `amd_native_exporter.py`, `streaming.py`, `mp4_audio_feed.py`, `live_av_mux.py`, DLL, D3D11,
AMF/VBR, HUD, Lean/Compass, mapy, FIT/GPX, Intel/NVIDIA, `def_layout.json`. Direct Copy Audio (oryginalne pakiety AAC, `-c copy`)
i Single Live Mux — bez zmian; brak audio_cache, M4A, plików AAC/ADTS, pośredniego MP4, remuxu. Zmieniony jest tylko cel stdio
procesu potomnego (plik obok MP4 albo `os.devnull`) i nazwa/lokalizacja logu.

## 12. Otwarte problemy / NOT TESTED

- Pełny eksport AMD na sprzęcie z logowaniem ON/OFF — NOT TESTED (zgodnie z poleceniem: bez eksportów i pomiarów; komputer
  może być obciążony renderem użytkownika). Logika logu przetestowana na rzeczywistym procesie potomnym (spawn) kończącym się błędem.
- Rzeczywiste anulowanie trwającego renderu w dziecku — NOT TESTED (testowany zapis statusu i zamknięcie uchwytów).
- Restart całego okna `SportCamHUD.py` — testowany restart komponentów (`SettingsTab` + `AppController`).
- Poza zakresem (do osobnego zadania): „Automatyczne źródło aktywności” i Strava Client ID nadal zapisują się do `def_layout.json`
  przy zmianie (w tym przy samym otwarciu zakładki, gdy kontroler jest już podłączony); Strava client secret trafia od razu do
  magazynu poświadczeń; „Liczba wątków”, „Katalog cache”, „Ścieżka ffmpeg” nie są nigdzie utrwalane; język i motyw są zapisywane,
  ale nic ich nie stosuje; `log_queue_trace` pisze do `scratch/amd_queue_zero/queue_trace.txt` (to nie log eksportu AMD).
- Zapis layoutu (`_save_current_layout_to_default`) nadal zeruje `_startup_preset` w `def_layout.json`; wartość obowiązująca jest w profilu.

## 13. ntfy

Wysłano jedno powiadomienie na `https://ntfy.sh/MalcerzPOP` po testach i zapisaniu raportu — HTTP 200.
Treść: Status PASS; Zapis ustawień PASS; Pomiń pauzy PASS; Logi AMD ON/OFF PASS; Lokalizacja logów PASS;
Raport RAPORT_SPORTCAMHUD_SETTINGS_AND_EXPORT_LOGGING.md; Commit 25eb07e, f14e45f. Bez tokenów/sekretów.
