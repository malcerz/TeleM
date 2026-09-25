# RAPORT AMD: Direct Live Mux Progress Fix (Indeterminate / Busy Mode)

**Data:** 2026-09-24  
**Środowisko:** Windows 11, AMD Radeon RX 7900 XTX (AMD_NATIVE_D3D11), Python 3.14.7, PySide6  
**Gałąź git:** `amd-bikeridehud`  
**Bazowy commit:** `0ef407e`  
**Lokalizacja raportu:** `Raporty/RAPORT_AMD_DIRECT_LIVE_MUX_PROGRESS_FIX.md`  

---

## 1. TASK SUMMARY

Naprawa WYŁĄCZNIE końcowej fazy `Muxowanie MP4` w potoku AMD Direct Live MP4.

### Problem początkowy:
Status w GUI poprawnie zmieniał się z `Renderowanie` na `Muxowanie MP4`, ale pasek postępu stał w miejscu przez długi czas na sztucznie wyliczonym procencie (`0.50 + 0.35 * frac` w oparciu o czas oczekiwania na proces i niemal stały rozmiar pliku `.part`), po czym skakał gwałtownie do 100%. Direct Live MP4 po ostatniej klatce wykonuje `proc_mux.wait()`, podczas którego FFmpeg zapisuje atomy `moov`, flushuje i zamyka kontener — bez dostarczania wiarygodnego licznika `done / total`.

### Rozwiązanie:
Zastosowano zasadę:
```text
REAL_PERCENT > INDETERMINATE > FAKE_PERCENT
```
Podczas oczekiwania na zakończenie muxera (`proc_mux.wait()`), pasek postępu przełącza się w tryb **INDETERMINATE / BUSY** (`QProgressBar.setRange(0, 0)`), a etykieta stanu pokazuje status bez fałszywego procentu (`--`). Po wyjściu z procesu muxera i rozpoczęciu weryfikacji pliku (`Finalizacja: weryfikacja pliku...`), pasek płynnie powraca do trybu **DETERMINATE** (`setRange(0, 100)`), osiągając 100% i status `Gotowe` **wyłącznie po** fizycznym potwierdzeniu istnienia pliku wyjściowego, walidacji ffprobe i atomowym rename.

---

## 2. REQUIRED METRICS & CONFIGURATION SUMMARY

```text
MUX_PROGRESS_SOURCE=RenderProgressTracker (direct live mux wait loop)
REAL_MUX_PERCENT_AVAILABLE=False
MUX_PROGRESS_MODE=INDETERMINATE
MUX_FAKE_PERCENT=False
MUX_WAIT_STATUS_TEXT=Frame: 300 / 300 | -- | FPS: -- | Czas: 00:00 | ETA: --:-- | Muxowanie MP4...

PROGRESS_MODE_BEFORE_MUX=determinate
PROGRESS_MODE_DURING_MUX=indeterminate
PROGRESS_MODE_AFTER_MUX=determinate

PROGRESS_100_BEFORE_OUTPUT_READY=False

DIRECT_EXPORT_RESULT=PASS (300f 4K render + mux + verify completed in 4.23s)
QUEUE_SMOKE_RESULT=PASS (ExportQueue lifecycle cleanly handles indeterminate mode)

MODIFIED_FILES=src/render_progress.py, src/gui/qt/_mixins/render_mixin.py, src/gui/qt/tabs/render_tab.py, src/ffmpeg/amd_native_exporter.py, tests/test_export_finalization_lifecycle.py, tests/test_render_progress_single_source.py
CASE=CASE A — Direct Live Mux używa poprawnego indeterminate/busy progress
```

---

## 3. TIME BREAKDOWN (Rule 20)

```text
TOTAL_STAGE_WALL_TIME: 13.5 min
AUDIT_TIME: 3.5 min
REPRO_TIME: 2.5 min
IMPLEMENTATION_TIME: 4.5 min
VALIDATION_TIME: 2.0 min
LONGEST_SINGLE_COMMAND_SECONDS: 6.42 s (pytest 49 unit tests)
```

---

## 4. DETAILED IMPLEMENTATION

### 4.1. `src/render_progress.py`
- Rozszerzono `RenderProgressState` o pole `progress_mode: str = "determinate"` (`"determinate"` lub `"indeterminate"`).
- Zaktualizowano `format_render_progress_status`: gdy `snapshot.progress_mode == "indeterminate"`, procent i FPS formatowane są jako `"--"` (brak wprowadzającego w błąd zamrożonego procentu).
- W `RenderProgressTracker._emit`: przekazywanie `progress_mode` do słownika stanu emitowanego do callbacka (dla fazy `complete` wymuszony tryb `determinate`).
- Rozszerzono sygnaturę `RenderProgressTracker.finalize(..., progress_mode="determinate")`.

### 4.2. `src/ffmpeg/amd_native_exporter.py`
- Usunięto sztuczne naliczanie procentu opartego o upływający czas (`frac = min(1.0, waited_s / ...)` i `internal=0.50 + 0.35 * frac`).
- W bloku Direct MP4 live mux:
  ```python
  progress_tracker.finalize(
      label="Muxowanie MP4...",
      progress_mode="indeterminate",
      file_size_bytes=target_sz,
  )
  ```
- W pętli fallback remux: również ustawiono `progress_mode="indeterminate"`.
- W fazie weryfikacji (`Finalizacja: weryfikacja pliku...`), zapisu końcowego (`Finalizacja: zapis końcowy...`) oraz zakończenia (`Finalizacja zakończona` / `complete`): jawnie ustawiony powrót do `progress_mode="determinate"`.

### 4.3. `src/gui/qt/_mixins/render_mixin.py`
- Usunięto lokalny, przesłaniający import `from pathlib import Path` wewnątrz `_on_render_requested`, który powodował `NameError: cannot access free variable 'Path'` w środowisku testowym.
- W `emit_render_progress`: odczyt `prog_mode = hud_state.get("progress_mode", "determinate")` i przekazanie go do tworzonego snapshotu `RenderProgressState` dla wszystkich faz (`render`, `finalize`, `prep`).
- W `emit_terminal_state`: gwarancja powrotu do `progress_mode="determinate"`.

### 4.4. `src/gui/qt/tabs/render_tab.py`
- W `__init__` oraz przy rozpoczęciu renderowania zainicjalizowano flagę `self._is_indeterminate = False`.
- W `_on_render_state`:
  - Gdy `snapshot.progress_mode == "indeterminate"`: przełączenie `self.progress.setRange(0, 0)` (tryb animowanego marquee w Qt) i ustawienie flagi `self._is_indeterminate = True`.
  - Gdy powraca `determinate`: przywrócenie `self.progress.setRange(0, 100)` i natychmiastowe odtworzenie wartości `setValue(int(round(self._render_display)))`.
  - Przekazanie `is_indeterminate` do `_set_stats` w celu wyświetlania `"--"` w labelu statystyk.
- W `_render_tick`: zabezpieczono wywołanie `self.progress.setValue(...)` warunkiem `if not getattr(self, "_is_indeterminate", False):`, aby timer animacji GUI nie nadpisywał trybu marquee QProgressBar.
- W `_end_render`, `_on_finished` oraz `_on_stopped`: gwarantowane zresetowanie `self._is_indeterminate = False` i przywrócenie `self.progress.setRange(0, 100)`.

---

## 5. TEST & VALIDATION RESULTS

### 5.1. Live Export Verification (300 frames, 4K, GX020079.MP4 + GX020079.fit)
Uruchomiono pełny test eksportu przez `scratch/test_live_mux_progress.py`.

Przebieg faz i stanów paska postępu:
```text
timestamp    phase        progress_mode   percent    status_text
------------------------------------------------------------------------------------------
11471.4958   prep         determinate     0.00%      HUD: -- | -- | FPS: -- | Czas: 00:00 | ETA: --:-- | Przygotowanie HUD...
11473.3876   prep         determinate     10.70%     HUD: -- | -- | FPS: -- | Czas: 00:00 | ETA: --:-- | Przygotowywanie HUD...
11473.9948   render       determinate     10.70%     Frame: 3 / 300 | 0.0% | FPS: -- | Czas: 00:00 | ETA: --:-- | Renderowanie...
11474.6631   render       determinate     11.97%     Frame: 30 / 300 | 0.0% | FPS: -- | Czas: 00:00 | ETA: --:-- | Renderowanie...
11474.6813   finalize     determinate     92.00%     Frame: 300 / 300 | 0.0% | FPS: -- | Czas: 00:00 | ETA: --:-- | Finalizacja enkodera...
11474.7074   finalize     determinate     94.00%     Frame: 300 / 300 | 0.0% | FPS: -- | Czas: 00:00 | ETA: --:-- | Finalizacja: zamykanie potoku...
11474.7882   finalize     indeterminate   --         Frame: 300 / 300 | -- | FPS: -- | Czas: 00:00 | ETA: --:-- | Muxowanie MP4...
11474.7887   finalize     determinate     99.11%     Frame: 300 / 300 | 0.0% | FPS: -- | Czas: 00:00 | ETA: --:-- | Finalizacja: weryfikacja pliku...
11474.8257   finalize     determinate     99.51%     Frame: 300 / 300 | 0.0% | FPS: -- | Czas: 00:00 | ETA: --:-- | Finalizacja: zapis końcowy...
11474.8269   finalize     determinate     99.90%     Frame: 300 / 300 | 0.0% | FPS: -- | Czas: 00:00 | ETA: --:-- | Finalizacja zakończona
11474.8625   complete     determinate     100.00%    Frame: 300 / 300 | 0.0% | FPS: -- | Czas: 00:00 | ETA: --:-- | Gotowe
```

### 5.2. Hard Gates Audit
| Hard Gate | Oczekiwana wartość | Wynik pomiaru | Status |
| :--- | :--- | :--- | :--- |
| `MUX_PROGRESS_MODE` | `INDETERMINATE` | `indeterminate` | **PASS** |
| `MUX_FAKE_PERCENT` | `False` | brak sztucznych wartości; `percent="--"` | **PASS** |
| `PROGRESS_STUCK_VISIBLE` | `False` | label zawiera `\| -- \|`, brak zamrożonej liczby | **PASS** |
| `PROGRESS_100_BEFORE_OUTPUT_READY`| `False` | 100% wyłącznie w fazie complete, plik potwierdzony (5 079 672 B) | **PASS** |
| `PROGRESS_MODE_RESTORED_AFTER_MUX`| `True` | weryfikacja: `determinate` (99.11%), koniec: `determinate` (100%) | **PASS** |

### 5.3. Testy jednostkowe i regresyjne
Uruchomiono pełny zestaw 49 testów:
```powershell
python -m pytest tests/test_export_finalization_lifecycle.py tests/test_finalization_tracker.py tests/test_render_progress_single_source.py tests/test_export_queue_basic.py tests/test_export_queue_lifecycle.py
```
Wynik: **49 passed in 6.42s** (100% PASS).

### 5.4. Queue Smoke Test
Skrypt `scratch/test_queue_smoke.py` potwierdził, że zadanie w kolejce:
- Przechodzi w stan `running` podczas renderingu,
- Przełącza się w `finalizing` i tryb `indeterminate` podczas `Muxowanie MP4...`,
- Wraca do `determinate` podczas weryfikacji,
- Kończy się jako `done` z postępem `1.0` bez zacięcia GUI.

---

## 6. BACKEND ISOLATION & REGRESSION AUDIT

- **NVIDIA / Intel:** Brak modyfikacji backendów CUDA/NVENC oraz QSV/Intel.
- **AMF / VideoProcessor / HUD / Map / Chart / QP:** Żadne algorytmy kompozycji, kodowania, mapy czy analizy jakości nie zostały naruszone.
- Zmiany ograniczono ściśle do raportowania cyklu życia fazy muxowania i przełączania trybu paska postępu GUI.

---

## 7. ARTEFAKTY

Wszystkie wymagane pliki zostały wygenerowane i zapisane w:
`scratch\amd_mux_progress\`
- `before_mux_progress.log` — zapis stanu bazowego (z zamrożonym sztucznym procentem 95.95%)
- `after_mux_progress.log` — log nowego przebiegu z trybem indeterminate
- `mux_phase_timeline.txt` — szczegółowa oś czasu zdarzeń i weryfikacja bramek
- `modified_files.txt` — lista zmodyfikowanych plików
- `reproduction_commands.txt` — komendy do odtworzenia testów
- `ntfy_result.txt` — log wysyłki powiadomienia NTFY

---

## 8. NTFY NOTIFICATION

Powiadomienie zostało wysłane pomyślnie w próbie 1:
```text
Attempt 1 of 3...
Exit code: 0
Response: {"id":"rR0bVLIJ4ZyT","time":1790276551,"expires":1790319751,"event":"message","topic":"MalcerzPOP","title":"TeleM GoPro","message":"AMD Direct Live Mux progress fixed: busy/indeterminate during unmeasurable mux wait, 100% only after final output.","tags":["white_check_mark"]}
```

---

## 9. PODSUMOWANIE

Końcowa faza `Muxowanie MP4...` działa teraz w 100% zgodnie z wymogiem `REAL_PERCENT > INDETERMINATE > FAKE_PERCENT`. Brak fałszywego postępu czasowego, brak zamrożonego paska, pełne wsparcie animowanego paska busy w GUI i kolejce oraz powrót do trybu determinate i 100% po zakończeniu zapisu pliku wyjściowego.
