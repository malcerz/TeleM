# TeleM — RENDER CANCEL: poprawny częściowy MP4 ETAP 1B

## 1. Root cause uszkodzonego `output.mp4`

ETAP 1 zamykał `process.stdin` z kontrolera, gdy writer mógł nadal wykonywać `stdin.write()`. W praktyce EOF/BrokenPipe następował w trakcie zapisu danych wejściowych, a FFmpeg nie zawsze dostawał czyste zakończenie rawvideo i nie zapisywał poprawnego trailera MP4.

## 2. Czy FFmpeg był terminate/kill po 3 s

Nie wykonano fizycznego eksportu użytkownika, więc nie ma historycznego pomiaru dla jego pliku. Kod został zmieniony tak, aby normalny cancel miał teraz 10 s bounded graceful wait. `terminate/kill` jest używany dopiero po tym limicie. Poprzedni sztywny limit wynosił 3 s.

## 3. Czas naturalnego graceful exit

Brak pomiaru na realnym materiale 1080p/4K w tej sesji. Diagnostyka raportuje co sekundę oczekiwania:

```text
[RenderCancel] stdin_closed ...
[RenderCancel] ffmpeg still running after 1s ...
[RenderCancel] ffmpeg still running after 2s ...
[RenderCancel] ffmpeg exited rc=0 ...
```

## 4. Writer/stdin lifecycle

Nowa kolejność:

```text
cancel event
-> producer stop
-> pending futures/reorder frames discarded
-> pipe_done dla writera
-> writer odrzuca queue i kończy bieżący bezpieczny stan write
-> bounded writer join
-> stdin EOF
-> FFmpeg finalization
```

GUI nie zamyka już stdin bezpośrednio podczas potencjalnego `write()`.

## 5. FFmpeg stderr przy Cancel

Reader FFmpeg pozostaje aktywny, a ostatnie maksymalnie 8 linii po anulowaniu jest wypisywane jako ASCII-safe `[RenderCancel] ffmpeg tail: ...`. Nie wyłączono stderr; w aktualnym torze stderr jest zbierane przez wspólny stdout/stderr reader.

## 6. Nowy bounded graceful timeout

Normalny cancel: 10 s na naturalny exit po EOF, następnie 1 s po `terminate`, a na końcu hard cleanup. App shutdown nadal ma własny limit oczekiwania 7 s i może użyć krótkiego forced fallbacku.

## 7. Zachowanie GUI

Przycisk pozostaje natychmiastowy. Stan `Anulowanie...` nie blokuje event loop. Faza finalizacji może być raportowana jako `Finalizacja...`, ale nie oznacza generowania nowych klatek — dotyczy wyłącznie opróżnienia encoder/muxera i trailera.

## 8. Graceful vs forced cancel

Proces otrzymuje status:

- `graceful` — naturalny exit po EOF,
- `terminate` — wymuszone zakończenie po graceful timeout,
- `kill` — ostatni fallback.

Po graceful wykonywana jest walidacja partial MP4 przez lokalny `ffprobe`. Po terminate/kill plik nie jest przedstawiany jako ukończony eksport.

## 9. ffprobe częściowego MP4

Dodano walidację wymagającą:

- `ffprobe returncode == 0`,
- dodatniego `format.duration`,
- obecności streamu video.

## 10. Test 1080p

Nie wykonano realnego renderu TeleM 1080p. Test integracyjny używa krótkiego deterministycznego rawvideo i sprawdza poprawny MP4 po EOF.

## 11. Test 4K

`PHYSICAL 4K TEST: NOT EXECUTED`.

## 12. Orphan process check

Nie wykonano fizycznej kontroli procesu po realnym eksporcie. Kod zachowuje bounded cleanup oraz Windows `taskkill /PID /T /F` jako ostatni fallback.

## 13. Testy automatyczne

- `tests/test_render_cancel_process_lifecycle.py`: 3 passed, w tym rawvideo EOF → MP4 → ffprobe.
- `tests/test_etap5h_writer_queue.py`, `tests/test_render_tab.py`: razem z lifecycle `26 passed`.
- `py_compile` zmienionych modułów: OK.

## 14. Zmienione pliki

- `src/ffmpeg/streaming.py` — kolejność writer/stdin, 10 s graceful wait, status graceful/forced, ffprobe validation i końcowe logi FFmpeg.
- `src/gui/qt/_mixins/render_mixin.py` — GUI nie zamyka stdin podczas aktywnego writera; bounded app-shutdown fallback.
- `src/gui/qt/tabs/render_tab.py` — możliwość pokazania fazy finalizacji podczas cancel.
- `tests/test_render_cancel_process_lifecycle.py` — test EOF partial MP4 i ffprobe.

Nie zmieniano HUD Resolution, HUD Frequency, encoderów, map, telemetry ani rendererów GPU.
