# Raport — jeden kanoniczny status postępu eksportu

## Zakres

Naprawiono wyłącznie niespójność statusu postępu podczas eksportu. Nie
zmieniano renderera, mapy, chartów, Preview ani ustawień backendów GPU.

## Audyt — stara ścieżka

### Dolny status zakładki Rendering

```text
AMD_NATIVE_D3D11 / streaming exporter
  → progress_tracker.frame(...) lub _report_stream_progress(...)
  → RenderMixin: sig_render_progress
  → RenderTab._on_render_progress
  → RenderTab._set_stats(...)
```

AMD przekazywał poprawny FPS w `hud_state["fps"]`, ale czwarty argument
callbacku `sig_render_progress` był ustawiany przez `RenderProgressTracker`
na `0.0`. W efekcie część statusu GUI mogła pokazywać `FPS: --`.

### Górny status MainWindow

```text
AMD exporter progress_cb(pct, stats_str)
  → RenderMixin: sig_progress
  → MainWindow._on_progress
  → status_label
```

Był to drugi, niezależny kanał. Status ten otrzymywał surowy tekst eksportera,
podczas gdy `RenderTab` formatował osobny stan z `sig_render_progress`.

### Dokładne źródło `Frame: 19`

`RenderTab._on_stopped()` wykonywał:

```python
self._set_stats(self.progress.value(), self._render_total, ..., "Anulowano")
```

`self.progress.value()` jest wartością wspólnego paska GUI w zakresie 0–100,
a nie numerem klatki eksportera. Dlatego wartość `19` w tekście `Frame: 19 /
55649` pochodziła z paska GUI i została błędnie użyta jako licznik klatek.

Tekst `Anulowano` był ustawiany wyłącznie przez `_on_stopped()`.
Dotychczasowy kontrakt `sig_render_stopped` nie miał `generation_id`, więc
GUI nie mogło odróżnić starego queued stop signal od bieżącej sesji. Kod nie
rejestrował źródła generacji tego sygnału; dokładna przyczyna jego nadejścia
podczas aktywnego eksportu nie jest więc retrospektywnie obserwowalna. Fix
eliminuje możliwość zastosowania takiego sygnału do aktywnej generacji.

## Nowa ścieżka — single source of truth

Dodano `RenderProgressState` z polami:

```text
generation_id
state
frame / total_frames / percent / global_percent
elapsed_s / fps / eta_s
finalization_stage
cancel_requested / cancelled / failed / completed
```

Przepływ:

```text
exporter callback
  → RenderMixin canonical snapshot
  → sig_render_state(RenderProgressState)
       ├→ RenderTab labels + progress bar
       └→ MainWindow status label + progress bar
```

`sig_progress` pozostaje dla load/legacy compatibility, ale jest ignorowany
przez MainWindow podczas aktywnej sesji eksportu. `sig_render_progress`
pozostaje podłączony wyłącznie do throttlowanego export Preview.

## Frame / FPS / elapsed / ETA

- `frame` i `total_frames` pochodzą z callbacku eksportera, nie z Preview ani
  liczby odświeżeń GUI.
- AMD FPS jest pobierany z `hud_state["fps"]`; dla pozostałych ścieżek z
  callbackowego argumentu `fps`.
- `elapsed_s` korzysta ze wspólnego zegara sesji renderu w `RenderMixin`.
- ETA jest wyliczane raz w canonical snapshot jako
  `(total_frames - frame) / fps`.
- Oba GUI odbiorniki formatują dokładnie ten sam snapshot.

## Cancel / stale signal / generation

`cancel_requested` oznacza tylko żądanie anulowania. `cancelled=True` jest
publikowane dopiero po zakończeniu workera i pipeline'u z powodu cancel.

Każdy eksport otrzymuje procesowo unikalny `generation_id`, przekazywany w
wewnętrznej opcji renderu i terminalnych snapshotach. `RenderTab` odrzuca
snapshoty starszej generacji. Stare lifecycle signals nie mogą nadpisać
aktywnego renderu:

- `sig_render_stopped` jest ignorowany, jeśli aktywny render nie jest w stanie
  anulowania;
- `sig_render_finished`/`sig_error` są ignorowane przez aktywną generację;
- terminalny stan kanoniczny jest obsługiwany przed kompatybilnym starym
  sygnałem lifecycle.

## Preview separation

Postęp eksportu i export Preview są rozdzielone:

```text
EXPORTER PROGRESS → RenderProgressState → GUI status
EXPORTER FRAME SNAPSHOT → existing throttled Preview (~5 Hz)
```

Licznik statusu nie zależy od częstotliwości Preview.

## Zmienione pliki

- `src/render_progress.py` — canonical snapshot, generation i wspólne
  formatowanie statusu.
- `src/gui/qt/signals.py` — `sig_render_state`.
- `src/gui/qt/_mixins/render_mixin.py` — mapowanie callbacków eksportera,
  wspólny zegar i terminalne stany generacji.
- `src/gui/qt/tabs/render_tab.py` — jeden odbiorca statusu, guard generacji,
  poprawny cancel lifecycle.
- `src/gui/qt/main_window.py` — odbiór tego samego snapshotu i blokada
  legacy progress podczas eksportu.
- `tests/test_render_progress_single_source.py` — regresja `19` vs `10330`,
  cancel requested vs cancelled, FPS/ETA i MainWindow.

## Testy

```text
python -m pytest tests/test_render_progress_single_source.py \
  tests/test_export_lifecycle_p1_fixes.py tests/test_render_tab.py \
  tests/test_render_no_legacy_json.py tests/test_nvidia_regression_chart_preview.py \
  tests/test_finalization_tracker.py -q
39 passed, 2 skipped

python -m pytest tests/test_render_progress_single_source.py -q
4 passed

python -m py_compile \
  src/render_progress.py src/gui/qt/signals.py src/gui/qt/main_window.py \
  src/gui/qt/_mixins/render_mixin.py src/gui/qt/tabs/render_tab.py
PASS
```

Nie uruchamiano `tests/test_indicator_exhaustive_proof.py`.

## Real GUI proof

Nie wykonano pełnego realnego eksportu z obserwacją pierwszych 30 sekund na
żywym projekcie. Jest to `NOT TESTED`. Testy kierunkowe obejmują konkretny
objaw oraz oba odbiorniki GUI.

## Podsumowanie

SINGLE CANONICAL PROGRESS SOURCE: PASS
EXPORTER FRAME COUNTER: PASS
EXPORTER FPS SHARED: PASS
ELAPSED/ETA SHARED: PASS
CANCEL REQUESTED != CANCELLED: PASS
STALE GENERATION GUARD: PASS
FRAME 19 REGRESSION: PASS
ACTIVE EXPORT CANNOT SHOW ANULOWANO: PASS
REAL GUI LONG EXPORT: NOT TESTED

