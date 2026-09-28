# RAPORT: Naprawa cyklu życia postępu eksportu i finalizacji AMD (Export Finalization Progress Lifecycle)

Data: 2026-09-24  
Środowisko: Windows 11, AMD Radeon RX 7900 XTX, Python 3.14.7, telem_amd_native.dll ABI 9  
Backend: `AMD_NATIVE_D3D11`  

---

## 1. Problem i cel zadania

Pod koniec eksportu, po zakodowaniu wszystkich klatek (`frame == total_frames`), GUI pozostawało w stanie:
- `status = Renderowanie...`
- `progress` zatrzymany (np. na 92–95%)
- Interfejs potrafił wisieć od kilku sekund do kilku minut (zwłaszcza na dużych plikach lub przy fallbacku analizy QP)
- Po zakończeniu operacji pasek skakał nagle do `100%`

Celem było:
1. Rozbicie i precyzyjne zmierzenie ogona eksportu od zakodowania ostatniej klatki (`LAST_FRAME_ENCODED`) do gotowości pliku końcowego (`FINAL_OUTPUT_READY`).
2. Przełączenie GUI z `Renderowanie...` na `Finalizacja...` (lub szczegółowe etapy: enkodera, potoku, muxowania, weryfikacji, analizy QP) natychmiast po ukończeniu klatek.
3. Wymuszenie twardej bramki: `100% != last encoded frame` (100% pokazywane dopiero po zrzucie danych, zamknięciu kontenera, ffprobe i atomic rename).
4. Przebudowa modelu progressu na fazowy: klatki kończą się na `RENDER_PROGRESS_END_PERCENT` (92.0%), a zakres 92.0%–100.0% reprezentuje rzeczywiste etapy finalizacji.
5. Zapewnienie mierzalnego postępu finalizacji (Stage C stream-copy remux na podstawie przetworzonych bajtów; Direct Live Mux na podstawie próbek wielkości i czasu; analiza QP z callbackiem per-klatka).
6. Usunięcie blokującego wywołania `analyze_qp(output)` z głównego wątku GUI i przeniesienie go do wątku renderującego z aktywnym callbackiem postępu.
7. Zapewnienie spójności cyklu życia w `ExportQueue` (`preparing` -> `running` -> `finalizing` -> `done`).
8. Zagwarantowanie monotoniczności progressu (`PROGRESS_MONOTONIC=True`) i braku przedwczesnego 100% (`PROGRESS_100_BEFORE_FINAL_OUTPUT=False`).

---

## 2. Diagnoza backendu i pomiary ogona (Tail Breakdown)

Zbadano cały pipeline po wyjściu z pętli klatek:
```text
LAST_FRAME_ENCODED
  ↓
[EXPORT PHASE] encoder_drain: telem_amd_flush(h_context)
  ↓
[EXPORT PHASE] mux:
    - Direct Live MP4: pump_thread.join() + proc_mux.wait() (zapis atomu moov, zamknięcie pliku .part)
    - Multi-file Stage C: FFmpeg stream-copy remux z audio concat
  ↓
Sanity check: ffprobe _probe_video_summary() na .part
  ↓
Atomic rename: os.replace(output_part_str, output_file_str) (do 10 prób)
  ↓
FINAL_OUTPUT_READY
  ↓
[Opcjonalnie] Single-export analyze_qp() fallback
  ↓
[EXPORT PHASE] complete: progress_tracker.complete() -> 100% "Gotowe"
```

### Trace czasowy zarejestrowany dla 300 klatek 4K (`scratch\measure_tail_timing.py`):
```text
[EXPORT TAIL]
last_frame_time=1779.3601
encoder_drain_start=1779.3601
encoder_drain_end=1779.4284
mux_start=1779.4284
mux_end=1779.5120
final_file_ready=1779.5798
LAST_FRAME_TO_FINAL_READY_SECONDS=0.220
```

### Rozbicie czasowe operacji w ogonie:
1. `encoder_drain`: 0.068 s (opróżnienie buforów sprzętowych AMF przez `telem_amd_flush`)
2. `mux`: 0.084 s (zrzucenie potoku nazwanego, zapis atomu `moov` przez FFmpeg w procesie `proc_mux`)
3. `file_verify_and_rename`: 0.068 s (`ffprobe` na pliku `.part`, sprawdzenie obecności klatek i audio, atomowe `os.replace` na `.mp4`)
4. Łączny czas ogona: 0.220 s dla 300 klatek.

Dla dłuższych eksportów / innych wariantów (np. 1131 klatek 4K, eksporty wieloplikowe na wolne dyski USB lub pojedyncze eksporty bez telemetrii QP z enkodera):
- Zapis atomu `moov` i remux Stage C potrafił trwać od kilku do kilkudziesięciu sekund.
- Wywołanie `analyze_qp(output)` wykonywane było synchronicznie na głównym wątku Qt (`render_tab.py:_show_export_finished_popup`), co przy prędkości ~8 fps analizy blokowało GUI na 140 sekund bez żadnego odświeżania.

---

## 3. Zastosowane zmiany architektoniczne

### A. Model postępu fazowego (`src/render_progress.py`)
- Wprowadzono stałe podziału:
  - `RENDER_PROGRESS_END_PERCENT = 92.0`
  - `FINALIZATION_START_PERCENT = 92.0`
  - `FINALIZATION_MAX_PERCENT = 99.9`
- Metoda `frame()` ogranicza postęp fazy renderowania klatek ściśle do `<= 92.0%`.
- Dodano metodę `finalize(label="Finalizacja...", internal=0.0, **extra)`:
  - Przelicza `internal` (0.0..1.0) na zakres `92.0% .. 99.9%`.
  - Dla drainu enkodera (`drain_pct`) dedykowany zakres `92.0% .. 94.0%`.
  - Wymusza odświeżenie GUI (`force=True`).
- Zaktualizowano `format_render_progress_status`:
  - Gdy `snapshot.state == "finalizing"` lub `snapshot.phase == "finalize"` lub `snapshot.frame >= snapshot.total_frames`, GUI wyświetla `snapshot.finalization_stage` (np. `"Finalizacja enkodera..."`, `"Muxowanie MP4 75%..."`, `"Analiza QP..."`).
  - Gdy `snapshot.completed` lub `snapshot.phase == "complete"`, wyświetla `"Gotowe"`.

### B. Emisja zdarzeń w backendzie AMD (`src/ffmpeg/amd_native_exporter.py`)
- Dodano logi fazowe: `[EXPORT PHASE] prepare`, `[EXPORT PHASE] render`, `[EXPORT PHASE] encoder_drain`, `[EXPORT PHASE] mux`, `[EXPORT PHASE] complete`.
- Natychmiast po wyjściu z pętli klatek emitowane jest `progress_tracker.finalize(label="Finalizacja enkodera...", internal=0.15, drain_pct=0.0)`.
- Po zakończeniu `telem_amd_flush()` emitowane jest `progress_tracker.finalize(label="Finalizacja: zamykanie potoku...", internal=0.35, drain_pct=100.0)`.
- W Direct Live MP4 Mux: pętla oczekiwania na zakończenie `proc_mux` emituje `progress_tracker.finalize(label="Muxowanie MP4...", internal=0.50 + 0.35 * frac)`.
- W Stage C stream-copy remux: pętla monitoruje rzeczywisty rozmiar pliku `.part` i emituje postęp na podstawie `cur_part_sz / stage_a_size_bytes` (`"Muxowanie MP4 {pct}%..."`).
- Przed `_probe_video_summary()`: `progress_tracker.finalize(label="Finalizacja: weryfikacja pliku...", internal=0.90)`.
- Przed `os.replace`: `progress_tracker.finalize(label="Finalizacja: zapis końcowy...", internal=0.95)`.
- Po udanym rename: `t_final_file_ready = time.perf_counter()`, `progress_tracker.finalize(label="Finalizacja zakończona", internal=1.0)`.
- Zapis bloku `[EXPORT TAIL]` z dokładnymi czasami kamieni milowych.
- `progress_tracker.complete()` wywoływane dopiero na samym końcu po potwierdzeniu pliku końcowego.

### C. Warstwa GUI i wątek roboczy (`src/gui/qt/_mixins/render_mixin.py` & `src/gui/qt/tabs/render_tab.py`)
- W `emit_render_progress`:
  - Jeśli `frame >= total_frames` lub `phase == "finalize"`, stan jest automatycznie mapowany na `state="finalizing"`, `phase="finalize"`.
  - Zapobiega to pokazywaniu statusu `Renderowanie...` w ogonie eksportu.
- W `worker()`:
  - Usunięto synchroniczną blokadę z GUI thread w `_show_export_finished_popup`.
  - Jeśli pojedynczy eksport nie posiada danych QP z enkodera, fallback `analyze_qp(output)` jest uruchamiany w tle w `worker()` z logiem `[EXPORT PHASE] qp_analysis` oraz callbackiem aktualizującym postęp GUI (`"Analiza QP {pct}%..."`, zakres 99.0%..99.9%).
  - Sygnał terminalny `completed` i 100% są emitowane dopiero PO zakończeniu analizy QP.
- W `render_tab.py`:
  - `_queue_job_text` obsługuje stan `"finalizing": f"FINALIZACJA {pct_r}"`.
  - `_on_render_state` przekazuje bieżącą fazę (`phase=snapshot.phase or snapshot.state`) do `export_queue.notify_render_progress`.
  - `_show_export_finished_popup` pobiera gotowe dane z obiektu `stats` natychmiast bez zamrażania interfejsu.

### D. Kolejka eksportu (`src/gui/export_queue.py`)
- `ExportJob.is_active()` uwzględnia stan `"finalizing"`.
- `notify_render_progress` przyjmuje opcjonalny parametr `phase: str = ""` i ustawia `job.render_status = "finalizing"`.
- Watchdog startu ignoruje fazę finalizacji.

---

## 4. Wymagane metryki i podsumowanie

```text
LAST_FRAME_TO_FINAL_READY_SECONDS=0.220

FINALIZATION_ROOT_CAUSE=Brak emitowania zdarzen postepu po petli klatek w amd_native_exporter.py, brak obslugi stanu finalizing w GUI (wiszenie na 'Renderowanie...' do 100%), oraz synchroniczne wywolanie analyze_qp w glownym watku Qt blokujace interfejs.
FINALIZATION_LONGEST_STAGE=Live MP4 moov atom flush & remux (or synchronous analyze_qp when encoder qp telemetry absent)

PROGRESS_MODEL_BEFORE=0..100% czysto klatkowy z zamrozeniem w ogonie
PROGRESS_MODEL_AFTER=PREPARE (0..12%), RENDER (12..92%), FINALIZATION (92..99.9%), COMPLETE (100.0%)

RENDER_PROGRESS_END_PERCENT=92.0

FINALIZATION_PHASES=encoder_drain (92..94%), live_mux/stream_copy (94..98%), verify_and_rename (98..99.9%), qp_analysis_fallback (99.0..99.9%)

FINALIZATION_REAL_PERCENT_AVAILABLE=TAK (Stage C remux: bytes_written / total_bytes; Direct Live Mux: czas adaptacyjny i probki wielkosci pliku; Analiza QP: ramki/probki z callbackiem)
FINALIZATION_INDETERMINATE_FALLBACK=TAK (bezpieczny fallback w razie nieznanej dlugosci strumienia)

QP_ANALYSIS_IN_FINALIZATION=TAK (przeniesione do watku tla render_mixin, z jawnym statusem 'Analiza QP %' i zdarzeniem [EXPORT PHASE] qp_analysis)
QP_ANALYSIS_PROGRESS_MODEL=Dedykowana podfaza 99.0%..99.9% z callbackiem na podstawie przetworzonych klatek

PROGRESS_MONOTONIC=True
PROGRESS_100_BEFORE_FINAL_OUTPUT=False

DIRECT_4K_RESULT=PASS (300f 4K wyeksportowane z pelnym ogonem, rozmiar: 5079672 bajtow)
UNIFIED_8K_TO_4K_RESULT=PASS (30f 8K->4K ukonczone z prawidlowa sekwencja faz: prep -> render -> finalize -> complete)
QUEUE_RESULT=PASS (pelny cykl: queued -> preparing -> running -> finalizing -> done, brak popupow per-job)
CANCEL_RESULT=PASS (cancel podczas renderu: PASS; cancel podczas finalizacji: PASS, brak procesow osieroconych)

MODIFIED_FILES=
- src/render_progress.py
- src/ffmpeg/amd_native_exporter.py
- src/gui/qt/_mixins/render_mixin.py
- src/gui/qt/tabs/render_tab.py
- src/gui/export_queue.py
- tests/test_finalization_tracker.py
- tests/test_export_finalization_lifecycle.py

CASE=CASE A — post-render tail widoczny i poprawnie reprezentowany przez progress
```

---

## 5. Wygenerowane artefakty w `scratch\amd_finalization_progress\`

- `before_progress.log`: Rejestracja dawnego zachowania z zawieszonym postępem na "Renderowanie...".
- `after_progress.log`: Rejestracja zrealizowanego testu 300f pokazująca przejścia faz, monotoniczny procent oraz etapy finalizacji.
- `tail_timing.txt`: Szczegółowe zestawienie pomiarów czasu trwania ogona eksportu i poszczególnych etapów.
- `phase_timeline.txt`: Oś czasu zdarzeń.
- `modified_files.txt`: Lista zmienionych plików produkcyjnych i testowych.
- `reproduction_commands.txt`: Polecenia weryfikacyjne.
- `ntfy_result.txt`: Potwierdzenie doręczenia powiadomienia NTFY z kodem HTTP 200.
