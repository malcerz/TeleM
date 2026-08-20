Raport: FINAL RELEASE-CANDIDATE ADVERSARIAL AUDIT
WYNIK: 2 issues P1, 0 issues P0
❌ P1-A — h_context (D3D11 context) nie jest zamykany gdy ASYNC producer rzuca wyjątek
Plik: 

amd_native_exporter.py

Dowód z kodu:

python
# L2442-2446 — ASYNC finally block
finally:
    cancel_evt.set()
    prod_thread.join(timeout=2.0)
    if producer_error:
        raise producer_error[0]   # ← wyjątek propaguje się tutaj
Gdy producer_worker rzuci wyjątek (np. błąd Pillow, błąd telemetrii, MemoryError) i wpisze go do producer_error, finally blok konsumenta podnosi go dalej. W tym momencie:

h_context wskazuje na żywy D3D11+AMF kontekst stworzony przez telem_amd_create
proc_dec może być żywym procesem FFmpeg
Żaden z nich nie jest zamknięty / zabity
Wyjątek trafia do worker() w 

render_mixin.py:50
:

python
except Exception as e:
    self.signals.sig_error.emit(f"Render error: {e}")
GUI poprawnie raportuje błąd i wraca do stanu idle. Ale h_context jest już wyciekiem — D3D11 device, AMF enkoder, MF decoder, NV12 textury pozostają w pamięci VRAM. Kolejny eksport uruchamia nowy telem_amd_create, który tworzy nowe zasoby. Po kilku awariach/retrybach VRAM może być wyczerpany lub AMD driver może odmówić alokacji nowego AMF encoder.

Zakres: Tylko pipeline_mode == "ASYNC" (tryb rzadko używany w produkcji, ale env AMD_CPU_GPU_PIPELINE=ASYNC go aktywuje). W SYNC mode wyjątek propaguje się analogicznie — ale tam nie ma osobnego producer, tylko _prepare_frame_cpu() rzuca do konsumenta bezpośrednio przez call stack, i analogicznie h_context + proc_dec nie są zamknięte.

Sprawdzam SYNC path: L2456 — prep = _prepare_frame_cpu(f_idx) rzuca wyjątek → wylatuje z pętli for → t_video_render_end = ... → flush_ok = telem_amd_flush(h_context) — to jest wywołanie na kontekst który może być w nieokreślonym stanie po wyjątku w _prepare_frame_cpu. Jeśli wyjątek pochodzi np. z telemetrii (nie z GPU), flush jest nadal poprawny. Ale jeśli wyjątek pochodzi z DLL call w _consume_prepared_frame — flush kontekstu w błędnym stanie może crashować. Nieudowodnione, oznaczam UNPROVEN dla tego wariantu.

Udowodnione: ASYNC path — producer_error raise → h_context leak.

❌ P1-B — Natychmiastowe _end_render() przy anulowaniu (cancel) — stan GUI może rozbiec się z działającym GPU workerem
Plik: 

render_tab.py:453-460

python
def _on_cancel(self) -> None:
    self.signals.sig_render_cancelled.emit()  # ← ustawia cancel_event.set()
    self._set_stats(...)
    self._end_render()                         # ← natychmiast: _rendering = False, btn_render.setEnabled(True)
_end_render() natychmiast przywraca _rendering = False i aktywuje przycisk "Renderuj". Ale render worker thread nadal działa — czeka na drenaż przez prod_thread.join(timeout=2.0) (ASYNC) lub przetwarza aktualną klatkę (SYNC). W tym oknie użytkownik może kliknąć "Renderuj" ponownie przed zakończeniem poprzedniego pipeline.

Drugi sig_render_requested.emit() uruchamia nowy worker thread w render_mixin.py:53. Teraz dwa wątki jednocześnie wywołują init_worker() na globalnym WORKER_CACHE, tworzą osobne h_context, i oba zapisują do tego samego output_file_str. Wynik: korupcja pliku wyjściowego + potencjalny crash D3D11 (dwa konteksty na tym samym adapterze).

Okno czasowe: Typowy czas proc_dec.kill() + prod_thread.join(2.0s) + zatrzymanie pętli konsumenta = od kilkuset ms do 2s. To realne — użytkownik który anuluje i od razu klika Render ponownie trafia w ten bug.

Nota: _on_finished też wywołuje _end_render() natychmiast, ale tam worker już skończy normalnie — jest mniej problematyczne (choć technicznie ta sama race window, jeśli sig_render_finished dotrze zanim GPU context się zamknął).

✅ Nie wykryto P0
Brak dowodów na:

Corrupcję finalnego pliku MP4 przy normalnym eksporcie (mux używa -c:v copy, sprawdzony)
Deadlock — cancel_evt jest sprawdzany w pętlach z timeoutem 50ms, join z timeout=2s
Utratę audio — remux kopiuje stream 1:a? opcjonalnie
Błędną telemetrię — PRECOMPUTED cache jest budowany z zamrożonym layout = copy.deepcopy(layout) (L753)
Podwójny telem_amd_close — każda ścieżka zamknięcia wykonuje go dokładnie raz i od razu return
PODSUMOWANIE
ID	Priorytet	Opis
P1-A	P1	ASYNC producer exception → h_context D3D11 leak; proc_dec nie killowany
P1-B	P1	_end_render() przy cancel przed zakończeniem GPU wątku → możliwy drugi eksport równolegle
Obydwa wymagają naprawy przed finalnym wydaniem. P1-A naprawia się przez try/finally w ASYNC consumer wrapping telem_amd_close. P1-B naprawia się przez opóźnienie reaktywacji btn_render do momentu sygnału zakończenia wątku (lub przez guard "is_cancelling").