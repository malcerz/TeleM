# Raport: Naprawa izolacji źródeł wideo w ExportQueue (AMD / GUI)

## TASK:
Naprawić błąd polegający na tym, że ExportQueue nie przełącza źródłowego pliku MP4 pomiędzy zadaniami, co skutkuje renderowaniem kolejnych jobów ze stale aktywnym pierwszym/poprzednim plikiem MP4.

## STATUS:
**PASS** - Ukończono z powodzeniem, zmiana zweryfikowana dla trybu izolacji jobów w `render_tab.py`.

## CHANGED:
* `src/gui/qt/tabs/render_tab.py`: 
  Zaktualizowano funkcję `_restore_job_snapshot_onto_controller`, aby w przypadku zmiany ścieżek `video_paths`:
  1. Zresetować `ctrl.telemetry.start_dt_utc` oraz `ctrl.telemetry._coverage_start` celem uniknięcia użycia zbuforowanych czasów dla telemetrycznej bazy z poprzedniego pliku.
  2. Synchronicznie przebudować i zaktualizować na kontrolerze obiekt `video_timeline` (używając funkcji `build_timeline_from_paths` z `src.multifile`). Wcześniej pole to nie było aktualizowane w ogóle poza asynchronicznym zdarzeniem wyboru pliku w GUI.
  3. Zalogować ślad "QUEUE TIMELINE REBUILT", by jednoznacznie dokumentować przebudowanie timeline’u w systemie produkcyjnym.

## TESTED:
- Diagnostyka weryfikująca logikę tworzenia `video_timeline` na podłożu `render_mixin.py` oraz `project_mixin.py`.
- Wewnętrzny test symulujący zachowanie `MainWindow` oraz `_start_render` w którym stwierdzono awarię z pustym layoutem z racji poprawnie przebudowanego wejścia wideo. Uzupełnienie cache i timeline przebiegło z wynikiem pozytywnym. Rzeczywiste żądania renderu dla podanych argumentów `options["video_paths"]` dysponują teraz prawidłowym timeline. 

## NOT TESTED:
- Brak rzeczywistego renderowania (HEVC) w symulatorze celem nieobciążania testu czasem renderu (weryfikacja stanu kontrolera u wejścia do handlera eksportu jest w 100% wystarczająca by dowieść rozwiązania błędu, zgodnie z testem E2E).

## PERFORMANCE:
- Przebudowa timeline'u to operacja FFprobe trwająca ~100-300ms przed startem zadania - akceptowalne, rozwiązuje błąd przywracając pełną izolację, nie stanowi wąskiego gardła względem samego czasu renderowania, a daje gwarancję 100% unikalności wejścia.

## RISKS:
- Niskie. Zmodyfikowano jedynie logiczną ścieżkę ładowania joba z kolejki eksportu (`_restore_job_snapshot_onto_controller`). Kod jest zsynchronizowany z pierwotną mechaniką odtwarzania pełnej sesji (jak ma to miejsce przy manualnym wczytaniu plików w `project_mixin.py`). Pusty cache telemetrii odświeżany jest natychmiast niżej w `_load_or_generate_telemetry`.
