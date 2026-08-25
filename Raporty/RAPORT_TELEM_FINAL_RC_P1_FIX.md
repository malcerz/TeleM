# TeleM — RAPORT: FINAL RC P1 FIX (Export Lifecycle P1-A + P1-B)

Data: 2026-08-20  
Status: **PEŁNY PASS (100% GREEN)**  
Test Suite: **523 passed, 17 skipped in 38.69s**

---

## A. P1-B Root Cause
`RenderTab._on_cancel()` bezpośrednio po wyemitowaniu sygnału anulowania wywoływał `self._end_render()`.
Powodowało to natychmiastowe ustawienie `_rendering = False` i odblokowanie przycisku `btn_render` ("EKSPORTUJ"), podczas gdy wątek renderujący (`worker`) w tle nadal realizował procedury zamykania pipeline'u D3D11 / AMF / MediaFoundation oraz zwalniania procesów dekodera. W efekcie użytkownik mógł natychmiast uruchomić drugi eksport równolegle do wciąż trwającego cleanupu pierwszego, prowadząc do kolizji kontekstów GPU i wyścigu o pliki wyjściowe.

---

## B. New GUI State Machine
Wprowadzono jawny, 3-stanowy automat w `RenderTab`:
- **`IDLE`** (`_rendering=False`, `_cancelling=False`):
  - `btn_render`: ENABLED
  - `btn_cancel`: DISABLED
- **`RENDERING`** (`_rendering=True`, `_cancelling=False`):
  - `btn_render`: DISABLED
  - `btn_cancel`: ENABLED
  - Status: "Renderowanie..." / progress / preview
- **`CANCELLING`** (`_rendering=True`, `_cancelling=True`):
  - `btn_render`: DISABLED (brak możliwości uruchomienia kolejnego eksportu)
  - `btn_cancel`: DISABLED (brak powtórnego klikania cancel)
  - Status: "Anulowanie..."
  - Preview & progress updates zablokowane

---

## C. Cancel Request vs Worker Completion
Rozdzielono żądanie anulowania od potwierdzenia zakończenia:
1. **Żądanie**: `RenderTab._on_cancel()` emituje `sig_render_cancelled` i przełącza GUI w stan `CANCELLING`.
2. **Realizacja**: `RenderMixin.worker()` odbiera `render_cancel_event` i po zakończeniu pracy/cleanupu emituje `sig_render_stopped`.
3. **Zakończenie**: `RenderTab._on_stopped()` odbiera sygnał potwierdzenia, aktualizuje status na "Anulowano" i dopiero wtedy wywołuje `_end_render()` (powrót do stanu `IDLE`).

---

## D. P1-A Resource Ownership
Zasoby natywne powiązane z procesem renderowania (`h_context`, proces dekodera `proc_dec`, wątek producencki `prod_thread`) mają teraz jednego, scentralizowanego właściciela opartego o blok `try ... finally` i idempotentną procedurę `_cleanup_native_resources()`.

---

## E. h_context Cleanup
- Po wywołaniu `telem_amd_create` utworzony kontekst jest zwalniany przez `_cleanup_native_resources()`.
- Funkcja pobiera referencję do uchwytu i natychmiast zeruje pole (`h_context = None`), po czym wywołuje `telem_amd_close(ctx)`.
- Gwarantuje to wykonanie `telem_amd_close` **dokładnie raz** na wszystkich ścieżkach:
  - Sukces normalnego eksportu
  - Anulowanie użytkownika (SYNC / ASYNC)
  - Błąd flush/drain AMF
  - Wyjątek w wątku producenckim / telemetrycznym / Pillow / pamięci
  - Wyjątek po stronie konsumenta / dekodera.

---

## F. proc_dec Cleanup
- Jeśli proces potomny dekodera FFmpeg (`proc_dec`) istnieje i jest aktywny (`poll() is None`), `_cleanup_native_resources()` wykonuje `kill()` oraz `wait(timeout=2.0)`.
- Po zakończeniu referencja jest zerowana (`proc_dec = None`), zapobiegając powstawaniu procesów zombie i blokowaniu uchwytów plików.

---

## G. ASYNC Exception Test
W teście `test_async_producer_exception_cleans_up_resources` wymuszono kontrolowany wyjątek w producencie telemetrii/nakładki:
- Wyjątek został poprawnie przekazany do wątku konsumenta i wypropagowany bez maskowania.
- `mock_dll.telem_amd_close` został wywołany dokładnie 1 raz z identyfikatorem kontekstu.
- GUI powraca do stanu `IDLE`.

---

## H. SYNC Exception Test
W teście `test_sync_exception_cleans_up_resources` zasymulowano błąd dekodowania / konsumpcji klatki:
- Wyjątek został poprawnie rzucony i wyłapany.
- Kontekst natywny D3D11 został zamknięty dokładnie 1 raz.

---

## I. Cancel/Restart Test
W testach:
- `test_cancel_then_immediate_render_blocked_until_stopped`: zweryfikowano blokadę startu drugiego renderu podczas stanu `CANCELLING` i poprawne odblokowanie po `sig_render_stopped`.
- `test_real_smoke_cancel_and_restart`: wykonano realny smoke na sprzętowym GPU pipeline (anulowanie w trakcie trwania klatek -> zakończenie -> natychmiastowy ponowny start pełnego eksportu -> wygenerowanie poprawnego pliku MP4).

---

## J. Normal Export Smoke
W teście `test_real_smoke_normal_export` zweryfikowano poprawność normalnego eksportu 30 klatek na realnym materiale źródłowym (D3D11VA + AMF HEVC + Fused NV12 + Remux). Plik wynikowy został poprawnie utworzony i zremuksowany z audio.

---

## K. Full Pytest
Uruchomiono pełny pakiet testów:
```
====================== 523 passed, 17 skipped in 38.69s =======================
```
100% testów przeszło pomyślnie, brak jakichkolwiek regresji.

---

## L. Remaining Risks
Brak zidentyfikowanych ryzyk blokujących release (wszystkie wykryte luki cyklu życia eksportu i wyścigu stanów GUI zostały załatane).

---

## Podsumowanie i Bramki Jakościowe

| Metryka / Kontrakt | Wynik |
|---|---|
| **CANCEL RACE FIXED** | **PASS** |
| **SECOND EXPORT GUARDED** | **PASS** |
| **ASYNC EXCEPTION CLEANUP** | **PASS** |
| **SYNC EXCEPTION CLEANUP** | **PASS** |
| **H_CONTEXT CLOSE EXACTLY ONCE** | **PASS** |
| **PROC_DEC CLEANUP** | **PASS** |
| **EXPORT PREVIEW AFTER CANCEL** | **PASS** |
| **NORMAL EXPORT** | **PASS** |
| **PYTEST** | **PASS (523/523)** |
| **RELEASE BLOCKERS REMAINING** | **0** |
