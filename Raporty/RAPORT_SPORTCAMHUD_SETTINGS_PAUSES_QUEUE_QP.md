# RAPORT — SPORTCAMHUD: ZAPIS USTAWIEŃ, „POMIŃ PAUZY”, QP W KOLEJCE

Data: 2026-10-15
Gałąź: `fix/gui-freeze-hud-composite`
Stan początkowy: HEAD `05bf51bd505a716152dbbf1bfddda7d2a6363679`

## 1. Zadanie

1. Usunąć osobny przycisk „Zapisz folder eksportu”; wszystkie ustawienia zapisuje zielony „Zapisz ustawienia”.
2. Trwały zapis „Pomiń pauzy aktywności” (TRUE i FALSE, po restarcie, bez resetów).
3. Spójny status QP podczas eksportu AMD (bezpośredni i z kolejki), bez wymyślania QP.

## 2. Stan początkowy

- `git status` przed pracą: zmodyfikowane przez użytkownika `def_layout.json`,
  `src/ffmpeg/intel_native_exporter.py`, `src/ffmpeg/nvidia_native_exporter.py`,
  `Raporty/RAPORT_SPORTCAMHUD_ETAP_5R_F_LIVE_MUX_AUDIO_FINALIZATION.md` oraz wiele
  nieśledzonych plików w `Raporty/`, `runtime/amd/`, `src/ffmpeg/live_av_mux.py`.
  **Nie zostały dotknięte ani dodane do commitów.**
- `def_layout.json` w repozytorium nie był zapisywany w trakcie pracy
  (mtime bez zmian: 2026-10-15 08:15:52, sprzed rozpoczęcia zadania). Testy pracowały
  na tymczasowym `base_dir` i izolowanym `APPDATA`.

## 3. Przyczyny

### 3.1 Dwa przyciski zapisu
`settings_tab.py` miał osobny `btn_save_export_dir` zapisujący tylko folder do
`%APPDATA%\SportCamHUD\app_preferences.json`, a zielony przycisk emitował wyłącznie
`sig_save_global_settings` (zapis layoutu: font, obramowanie itd. do `def_layout.json`).
Język i motyw nie miały żadnej logiki zapisu.

### 3.2 „Pomiń pauzy” nie przetrwa restartu
- Checkbox był tworzony z `setChecked(False)` i **nigdy nie był odtwarzany** przy starcie,
  mimo że wartość istniała w `def_layout.json` (`"charts_skip_pauses": true`).
  Po restarcie GUI pokazywało OFF, a eksport mógł używać ON — rozjazd GUI/eksport.
- Wartość żyła tylko w `self.layout`, więc była nadpisywana przy: wczytaniu MP4
  (layout projektu `.layout.json` / startowy preset / def_layout), wczytaniu presetu,
  „Wyczyść HUD” (layout bez klucza → False) oraz po zadaniu z kolejki
  (`_restore_job_snapshot_onto_controller` podmienia `ctrl.layout` na snapshot zadania,
  więc kolejne zadanie/eksport bezpośredni dziedziczyły starą wartość).

### 3.3 QP w kolejce
Przepływ sprawdzony: AMF → `telem_amd_get_encoder_qp_stats` (DLL) → `amd_native_exporter.py`
(`RenderProgressTracker.frame`) → `amd_child_process.py` (IPC przekazuje **cały** słownik
`hud_state`, bez filtrowania pól) → `render_mixin` callback → `RenderProgressState` →
`render_tab._on_render_state` / `format_render_progress_status`.

Ustalenia:
- Kolejka **nie gubi** `current_qp`/`qp_avg`/`is_cqp` — eksport bezpośredni i z kolejki
  używają tego samego procesu potomnego AMD (wybór `amd_child_enabled` nie zależy od trybu)
  i tego samego callbacku postępu.
- Sterownik AMF na tej platformie **nie zwraca próbek QP** (`samples=0`); potwierdzają to
  rzeczywiste logi z 2026-10-14 (`Raporty/direct_copy_audio_windows_20261014/*/export.log`:
  „Hardware QP statistics feedback is not supported by current AMF driver/hardware”).
- Faktyczna przyczyna sprzecznego widoku: dwa formattery GUI. Linia statystyk
  (`RenderTab._set_stats`) przy braku liczb pokazywała `QP: --`, a druga linia
  (`lbl_compression_stats`) pokazywała tekst z enkodera `QP avg: N/A`. Informacja
  o aktywnym VBR (`RC: VBR`) była tylko w tekście `progress_cb`, nie w `hud_state`.
- Dodatkowo `format_render_progress_status` rzucał `UnboundLocalError` w stanie
  `preparing` (brak `qp_str`) — utajony błąd tego samego formattera.

## 4. Zmienione pliki i implementacja

### Commit 1 — `1f7f8e0` fix(settings): unify persistence and save skip-pauses option
- `src/export_paths.py`: `load_app_preferences()`, `update_app_preferences()` (atomowy zapis,
  scalanie kluczy), `load_charts_skip_pauses(base_dir)` (preferencja profilu → wartość z
  def_layout tylko do odczytu → False). `save_default_export_dir` korzysta z `update_app_preferences`.
- `src/gui/qt/tabs/settings_tab.py`: usunięty „Zapisz folder eksportu”; zielony przycisk →
  `_on_save_settings_clicked`: walidacja i zapis folderu (błędny folder blokuje cały zapis
  z ostrzeżeniem), zapis `charts_skip_pauses`, `ui_language`, `ui_theme` do
  `app_preferences.json`, potem dotychczasowy `sig_save_global_settings` (font/obramowanie/
  layout). Przy starcie `_load_app_preferences_into_form()` odtwarza checkbox (z blokadą
  sygnałów), język i motyw. „Wybierz”/„Wyczyść” bez zmian znaczenia.
- `src/gui/qt/controller.py`: `self.charts_skip_pauses` wczytywane przy starcie i nakładane na layout.
- `src/gui/qt/_mixins/preset_mixin.py`: `_apply_global_chart_preferences()`; zmiana checkboxa
  aktualizuje też `charts_skip_pauses`; nałożenie po wczytaniu presetu.
- `src/gui/qt/_mixins/project_mixin.py`: nałożenie po wyborze layoutu przy wczytaniu MP4.
- `src/gui/qt/_mixins/indicator_mixin.py`: nałożenie po „Wyczyść HUD”.
- `src/gui/qt/_mixins/render_mixin.py`: eksport bezpośredni (bez `options["layout"]`) nakłada
  globalną wartość, bo layout mógł zostać nadpisany snapshotem zadania z kolejki.
- `src/gui/qt/tabs/render_tab.py` (`_on_add_to_queue`): snapshot zadania dostaje bieżące
  `charts_skip_pauses` w chwili dodania; już dodane/uruchomione zadania nie są zmieniane.
- `tests/test_settings_skip_pauses_persistence.py` (nowy).

Sposób trwałego zapisu: `%APPDATA%\SportCamHUD\app_preferences.json`
(`default_export_dir`, `charts_skip_pauses`, `ui_language`, `ui_theme`). Konfiguracja globalna
ma pierwszeństwo przed wartością w layoucie projektu/presetu — brak konfliktu.
Zielony przycisk nadal wywołuje istniejący zapis layoutu do `def_layout.json` (zachowanie
sprzed zmian, nie modyfikowane). Algorytm wykrywania pauz i synchronizacji — bez zmian.

### Commit 2 — `7272c5f` fix(gui): restore consistent AMD VBR QP status in queue
- `src/ffmpeg/amd_native_exporter.py` (tylko blok raportowania postępu): jeden tekst
  `RC: VBR | QP: <bieżący> | QP avg: <średni>` albo `RC: VBR | QP avg: N/A`, plus
  `rate_control="VBR"` w `hud_state`. Brak próbek → N/A; żadnego QP=28, żadnego wyliczania
  z bitrate. Enkoder, VBR, bitrate, presety AMF, DLL, Live Mux, audio — bez zmian.
- `src/render_progress.py`: pole `RenderProgressState.rate_control`; formatter akceptuje
  tekst `RC:`; naprawiony `UnboundLocalError` w stanie `preparing`.
- `src/gui/qt/_mixins/render_mixin.py`: snapshot przenosi `rate_control`.
- `src/gui/qt/tabs/render_tab.py`: `_set_stats(rate_text=...)` — gdy enkoder podał tryb RC,
  linia statystyk pokazuje ten sam tekst co linia kompresji i pasek statusu.
- `tests/test_amd_vbr_qp_status.py` (nowy).

Widok przy braku QP ze sterownika: `Frame: 4450 / 70995 | ... | FPS: 36.3 | RC: VBR | QP avg: N/A | ...`
oraz druga linia `RC: VBR | QP avg: N/A` — ta sama informacja, N/A nie jest błędem renderu.

## 5. Testy (tylko poprawności — komputer był obciążony przez użytkownika)

| Test | Wynik |
|---|---|
| `tests/test_settings_skip_pauses_persistence.py` (11 testów) | PASS |
| `tests/test_amd_vbr_qp_status.py` (6 testów) | PASS |
| Restart w osobnych procesach (zapis → nowy proces → odczyt), ON i OFF + folder | PASS |
| `test_default_export_dir_settings.py` 13 | PASS |
| `test_amd_qp_governance.py` 10 | PASS |
| `test_render_progress_state_scope_hotfix.py` 5 | PASS |
| `test_gui_v5_autosave_preview_and_aa.py` 6 | PASS |
| `test_amd_queue_trim_snapshot.py` 5 | PASS |
| `test_activity_ux_timeline.py` 26 | PASS |
| `test_gui_v3_runtime_acceptance.py::test_full_layout_persistence_contract` | PASS |

Zakres pokryty testami celowanymi:
- folder → zielony Zapisz → restart → poprawny folder; sama edycja bez zapisu nie utrwala;
- checkbox ON → Zapisz → restart → ON; OFF → Zapisz → restart → OFF (także gdy stary
  def_layout ma wartość przeciwną);
- przełączanie zakładek nie resetuje; wczytanie presetu, „Wyczyść HUD”, layout podmieniony
  przez zadanie z kolejki — wartość globalna zachowana; blok wczytania projektu wywołuje
  nałożenie (test statyczny);
- kolejka dostaje bieżącą wartość i zamrożony snapshot;
- QP: ścieżka bezpośrednia i kolejki (`_on_render_state` z aktywnym zadaniem kolejki),
  VBR z dostępnym QP, VBR bez QP, brak `QP: --`, brak fałszywego 28, NVIDIA/Intel bez zmian
  formatowania, formatter w stanie `preparing` bez wyjątku.

Wynik restartu procesowego:
```
SAVED True  …/exp2   → RESTORED checkbox=True  ctrl=True  layout=True  folder=…/exp2
SAVED False …/exp1   → RESTORED checkbox=False ctrl=False layout=False folder=…/exp1
```

Testy istniejące z porażkami — **identyczne porażki na czystym HEAD 05bf51b**
(sprawdzone na kopii `git archive HEAD`), więc nie są regresją:
- `test_gui_logic_degree_export_settings_cleanup.py`: 5 FAIL (nieaktualne oczekiwania,
  np. brak `spin_threads`, `_ensure_disk_persistence`; test czyta prawdziwy APPDATA).
- `test_export_gpmf_and_qp_summary.py`: 5 FAIL (czyta prawdziwy folder eksportu `D:/GoPro/SCH`).
- `test_skip_pauses_parity.py`: 2 FAIL (`telemetry_fit` brak modułu, `ActiveTimeMapper` not subscriptable).
- `test_export_queue_basic.py::test_notify_render_done_success_queues_upload`: 1 FAIL.
- `test_render_progress_single_source.py`: zawiesza się (także na HEAD).

NOT TESTED:
- Pełny eksport AMD z kolejki na sprzęcie — nie uruchomiony, bo użytkownik obciążał komputer
  (w tym czasie działał jego własny render SportCamHUD) i prosił o same testy poprawności.
  Kanoniczne pliki z `BENCHMARKS.md` (`Video/GX020079.*`) nie istnieją w tym repozytorium.
  Status QP na sprzęcie opiera się na rzeczywistych logach z 2026-10-14 (samples=0) i testach GUI.
- Restart całej aplikacji `SportCamHUD.py` (okno główne) — sprawdzony restart komponentów
  (`SettingsTab` + `AppController`) w osobnych procesach.
- Wydajność — nie mierzona (brak wpływu na pętlę renderu poza formatowaniem tekstu co N klatek).

## 6. Czy QP jest dostępny z AMF?
Nie na tej platformie: `telem_amd_get_encoder_qp_stats` zwraca `samples=0`, sterownik nie
wypełnia `AMF_VIDEO_ENCODER_HEVC_STATISTIC_*_QP`. Wynik: `RC: VBR | QP avg: N/A` — status
sprzętowy, nie błąd. Jeśli inny sterownik zwróci próbki, GUI pokaże `RC: VBR | QP: x | QP avg: y`.
Analiza bitstreamu HEVC nie została wdrożona (poza zakresem).

## 7. Ryzyka / nierozwiązane
- Język i motyw są teraz zapisywane i odtwarzane w kontrolkach, ale w kodzie **nie ma logiki
  ich zastosowania** (zmiana języka/motywu niczego w aplikacji nie zmienia) — tak było wcześniej.
- „Startowy preset” nadal zapisuje się natychmiast przy zmianie pola (istniejąca logika, nie
  zmieniana); „Wyczyść” przy folderze eksportu nadal od razu utrwala tryb automatyczny
  (zgodnie z wymaganiem, by nie zmieniać znaczenia przycisku).
- Po wykonaniu zadania z kolejki `ctrl.layout` pozostaje snapshotem zadania (istniejące
  zachowanie); wartość „Pomiń pauzy” jest korygowana przy kolejnym eksporcie bezpośrednim
  i przy dodaniu do kolejki, ale podgląd może do tego czasu używać wartości ze snapshotu.
- Testy istniejące, które nie izolują APPDATA, mogą czytać/zapisywać prawdziwy profil
  (wyżej wymienione porażki) — do osobnego zadania.

## 8. Izolacja backendów
NVIDIA i Intel nie ustawiają `rate_control`, więc ich formatowanie QP jest bez zmian (test).
Niezacommitowane zmiany użytkownika w `intel_native_exporter.py` i `nvidia_native_exporter.py`
nie zostały dotknięte. AMD: zmieniony wyłącznie tekst raportu postępu; DLL, VBR, bitrate,
presety, Single Live Mux, Direct Copy Audio (oryginalne pakiety AAC, bez plików pośrednich)
i finalizacja MP4 — bez zmian. `def_layout.json` nie commitowany.

## 9. Git
- Commity: `1f7f8e0` (settings), `7272c5f` (QP). Bez pusha.
- Working tree po commitach: pozostają wyłącznie wcześniejsze zmiany użytkownika
  (`def_layout.json`, `intel_native_exporter.py`, `nvidia_native_exporter.py`, raport 5R_F)
  i nieśledzone pliki; ten raport nie jest commitowany.

## 10. Podsumowanie

```
Zapis ustawień (jeden zielony przycisk):  PASS
Pomiń pauzy (restart ON/OFF, bez resetów): PASS
QP w kolejce:                              N/A sprzętowe — status spójny „RC: VBR | QP avg: N/A” (PASS testów GUI)
Eksport AMD na sprzęcie:                   NOT TESTED (komputer obciążony)
STATUS:                                    PASS
```
