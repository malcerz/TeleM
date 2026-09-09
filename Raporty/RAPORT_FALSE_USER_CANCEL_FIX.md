# Raport — false user cancel podczas eksportu

## Zakres

Naprawiono false-cancel w renderze AMD async oraz rozdzielono żądanie anulowania
od wewnętrznego zatrzymania producenta. Zachowano izolację backendów i nie
zmieniano Preview, map cache, chartów, finalizacji ani konfiguracji GPU poza
przekazaniem reasonu anulowania.

## Dokładna przyczyna

Znaleziony setter:

```text
src/ffmpeg/amd_native_exporter.py
export_amd_native_d3d11()
async producer/consumer finally
cancel_evt.set()
```

`cancel_evt` wskazywał na zewnętrzny `cancel_event` eksportu. Setter był
bezwarunkowy, więc wykonywał się również po normalnym zakończeniu pętli
producent/consumer. Eksporter później widział `cancel_event.is_set()` i
drukował błędny komunikat `Export cancelled by user.`. To był rzeczywisty
root cause false-cancel.

Drugi, niezależny błąd GUI wyjaśniający tekst `Frame: 19` był w
`RenderTab._on_stopped()`: wartość paska GUI (`progress.value()`, zakres
0–100) była formatowana jako numer klatki i bezpośrednio ustawiała `Anulowano`.
Ten lifecycle nie miał wcześniej generation guard.

## Audyt setterów i call-chain

Renderowy event jest ustawiany teraz wyłącznie przez centralny helper:

```text
RenderTab._on_cancel()
  → sig_render_cancel_requested(RenderCancelRequest)
  → AppController / RenderMixin._on_render_cancel_requested()
  → RenderMixin._set_render_cancel()
  → aktywny, świeży render_cancel_event.set()
```

Reason to `USER_CANCEL`, source to `GUI_BUTTON`.

Druga dozwolona ścieżka to zamknięcie aplikacji:

```text
QApplication.aboutToQuit
  → cancel_render_and_wait()
  → _set_render_cancel(reason=APP_SHUTDOWN, source=APPLICATION_EXIT)
```

Stary bezargumentowy `sig_render_cancelled` pozostaje wyłącznie jako
kompatybilna notyfikacja; kontroler nie używa go już do ustawiania eventu.

Pozostałe znalezione eventy są odrębne:

```text
LoadTab._qp_cancel_event      → tylko analiza QP
Map preload context.cancel()  → tylko preload mapy
streaming writer_failed       → tylko błąd writer'a
producer_stop_event           → tylko zatrzymanie producenta AMD
```

Nie są współdzielone z renderowym `cancel_event`.

## Naprawa lifecycle

Każdy nowy eksport tworzy nowy `threading.Event()`. Nie jest już używany jeden
obiekt czyszczony między sesjami. Stary worker zachowuje referencję do starego
eventu, a nowy worker do nowego eventu.

W AMD async `producer_stop_event` zastąpił błędne `cancel_evt.set()` w
`finally`. Normalne zakończenie producenta nie zmienia stanu anulowania
eksportu.

Każde żądanie anulowania ma:

```text
generation_id
reason = USER_CANCEL | INTERNAL_STOP | SUPERSEDED | ERROR | APP_SHUTDOWN | NONE
source
```

Centralny setter loguje:

```text
[RenderCancel] SET generation=... source=... reason=... thread=... frame=... elapsed=... stack=...
```

Stare generation są ignorowane. AMD może wypisać `Export cancelled by user.`
wyłącznie dla `reason == USER_CANCEL`; pozostałe powody mają osobny komunikat.

## Progress GUI

Oba statusy Rendering korzystają z `RenderProgressState` emitowanego z callbacku
eksportera. Frame, total, FPS, elapsed i ETA nie pochodzą z Preview ani z
licznika odświeżeń GUI. `sig_render_progress` pozostał tylko kanałem dla
throttled export Preview. Generation guard blokuje stary stop/completion/error.

## Zmienione pliki

- `src/render_progress.py` — reason/request oraz pola reason w stanie renderu.
- `src/gui/qt/signals.py` — generation-tagged cancel request.
- `src/gui/qt/controller.py` — podłączenie nowego requestu.
- `src/gui/qt/tabs/render_tab.py` — jawny request `USER_CANCEL`.
- `src/gui/qt/_mixins/render_mixin.py` — świeży event, centralny setter/log,
  generation guard i APP_SHUTDOWN.
- `src/ffmpeg/streaming.py` — przekazanie cancel reason provider.
- `src/ffmpeg/amd_native_exporter.py` — osobny producer stop event i
  semantycznie poprawny komunikat cancel.
- `tests/test_render_progress_single_source.py` — testy eventu, generation,
  Preview i reason.

## Testy

```text
python -m pytest tests/test_render_progress_single_source.py \
  tests/test_export_lifecycle_p1_fixes.py tests/test_render_tab.py \
  tests/test_render_no_legacy_json.py tests/test_nvidia_regression_chart_preview.py \
  tests/test_finalization_tracker.py tests/test_amd_direct_mp4_mux.py -q
54 passed, 2 skipped

python -m py_compile \
  src/render_progress.py src/gui/qt/signals.py src/gui/qt/controller.py \
  src/gui/qt/main_window.py src/gui/qt/_mixins/render_mixin.py \
  src/gui/qt/tabs/render_tab.py src/ffmpeg/streaming.py \
  src/ffmpeg/amd_native_exporter.py
PASS
```

Nie uruchamiano `tests/test_indicator_exhaustive_proof.py`.

Test jednostkowy potwierdza `GUI_BUTTON → USER_CANCEL`, odrzucenie starej
generacji, brak anulowania przez ścieżkę Preview oraz świeży event sesji.
Pełny realny unattended render projektu `GX010241.MP4` przez 15000+ klatek
nie został uruchomiony w tym etapie — `NOT TESTED`. Rzeczywiste kliknięcie
przycisku w działającej aplikacji również jest `NOT TESTED`; kontrakt GUI jest
pokryty testem sygnału.

## Podsumowanie

```text
FALSE USER CANCEL ROOT CAUSE: FOUND
RENDER CANCEL EVENT ISOLATED: PASS
STALE GENERATION PROTECTED: PASS
PREVIEW CANNOT CANCEL EXPORT: PASS
UNATTENDED 15000+ FRAME RENDER: NOT TESTED
REAL USER CANCEL: NOT TESTED
PROGRESS GUI CONSISTENT: PASS
```
