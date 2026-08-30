# TeleM — RENDER CANCEL: process lifecycle ETAP 1

## 1. Obecny cancel call path

```text
RenderTab._on_cancel()
    -> sig_render_cancelled
    -> AppController._on_render_cancelled()
    -> render_cancel_event.set()
    -> zamknięcie FFmpeg stdin, aby przerwać blocking write
    -> producer loop wykrywa event
    -> futures są anulowane, reorder_buf jest odrzucany
    -> writer dostaje stop i odrzuca pending queue
    -> FFmpeg graceful stdin close / bounded wait
    -> terminate / kill process tree fallback
    -> SHM, pipe i worker cleanup
    -> sig_render_stopped
    -> RenderTab wraca do IDLE
```

Przy zamknięciu aplikacji `QApplication.aboutToQuit` wywołuje `cancel_render_and_wait()` z limitem 7 s.

## 2. Faktyczne miejsce blokady

Przed poprawką były trzy niezależne źródła długiego anulowania:

1. Po wyjściu z głównej pętli anulowania kod nadal opróżniał `reorder_buf` do kolejki pipe.
2. Writer mógł dalej wysyłać pending frames, a `stdin.write()` mógł blokować się na pełnym pipe.
3. Końcowe `process.wait()` nie miało timeoutu. Dodatkowo `with ProcessPoolExecutor` mogło czekać na już uruchomione zadania.

To tłumaczyło zarówno długie anulowanie, jak i pozostawiony `ffmpeg.exe` po ręcznym zakończeniu TeleM.

## 3. Czy producer generował dalej po Cancel

Przed poprawką mógł dokończyć część już zaplanowanych prac i przepchnąć reorder buffer. Po poprawce główne pętle sprawdzają event, top-up nie planuje nowych futures, a anulowane futures są odrzucane. Zadania już wykonujące rasteryzację są zatrzymywane przez nieblokujące zamknięcie lifecycle executora.

## 4. Czy queue była opróżniana

Przed poprawką pending frames były przepychane do FFmpeg. Po poprawce cancel oznacza odrzucenie kolejki: writer po ustawieniu `pipe_done` zwalnia oczekujące memoryview/SHM i nie wykonuje kolejnych zapisów.

## 5. Czy `stdin.write` mogło blokować

Tak. Był używany osobny writer thread z blokującym `stdin_buffer.write`. Przy cancel kontroler natychmiast zamyka `process.stdin`, co przerywa zapis lub powoduje `BrokenPipeError`; writer ma bounded join i nie jest wymagany do opróżnienia całej kolejki.

## 6. FFmpeg graceful shutdown

Pierwsza próba to zamknięcie stdin rawvideo. FFmpeg dostaje EOF i może dopisać trailer MP4. Następnie proces jest obserwowany przez ograniczony czas.

## 7. Timeout / terminate / kill fallback

`_stop_ffmpeg_process()` stosuje:

```text
stdin close
-> wait 3 s
-> terminate
-> wait 1 s
-> Windows: taskkill /PID /T /F
   POSIX: kill
-> wait 1 s
```

Żadne końcowe oczekiwanie procesu nie jest nieskończone.

## 8. Windows process tree

Na Windows końcowy fallback używa wbudowanego `taskkill /T /F`, więc obejmuje proces potomny FFmpeg, jeżeli FFmpeg uruchomił własne child processes. Nie dodano nowej zależności.

## 9. App shutdown

`aboutToQuit` żąda anulowania, zamyka stdin i czeka maksymalnie 7 s na worker. Przy normalnym anulowaniu worker sam wykonuje cleanup; aplikacja nie znika pozostawiając aktywny uchwyt procesu w kontrolerze.

## 10. Exception cleanup

Ścieżka wyjątku ustawia stop writer, odrzuca sentinel bez blokowania, wywołuje bounded FFmpeg cleanup, zwalnia pending memoryview i zamyka SHM. Referencja aktywnego procesu jest przekazywana przez `render_process_holder`.

## 11. Partial MP4

Jeśli stdin close zakończy FFmpeg graceful, częściowy MP4 może mieć poprawny trailer. Jeśli potrzebny jest terminate/kill, plik nie jest oznaczany jako sukces — GUI emituje stan zatrzymania/anulowania, a nie `sig_render_finished`. Fizyczna odtwarzalność częściowego pliku nie była testowana na realnym eksporcie.

## 12. Czas Cancel przed/po

Nie ma pomiaru realnego renderu przed poprawką w tej sesji. Po poprawce fallback jest ograniczony do około 5 s plus krótki cleanup; normalny graceful stop kończy się wcześniej.

## 13. Testy

- `tests/test_render_cancel_process_lifecycle.py`: bounded terminate/kill oraz writer discard pending frames.
- `tests/test_etap5h_writer_queue.py`.
- `tests/test_render_tab.py`.
- Wynik: `24 passed` dla zestawu lifecycle/writer/RenderTab.
- `py_compile` zmienionych modułów: OK.

## 14. Physical test

`PHYSICAL CANCEL TEST: NOT EXECUTED`

Nie wykonano realnego 20–30-sekundowego eksportu ani sprawdzenia `ffmpeg.exe` w Menedżerze zadań po kliknięciu Cancel.

## 15. Zmienione pliki

- `src/ffmpeg/streaming.py` — cancel-aware producer/writer, bounded FFmpeg cleanup, executor/process-tree lifecycle.
- `src/gui/qt/_mixins/render_mixin.py` — referencje worker/process, natychmiastowe stdin close, app-shutdown wait.
- `src/gui/qt/application.py` — cancel przy `aboutToQuit`.
- `tests/test_render_cancel_process_lifecycle.py` — testy lifecycle.

Zmiany nie dotyczą rendererów GPU, telemetry, map, HUD Resolution ani ustawień encoderów.
