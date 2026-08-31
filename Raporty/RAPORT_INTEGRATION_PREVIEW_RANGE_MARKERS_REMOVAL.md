# Raport — usunięcie markerów zakresu z podglądu

## Zadanie

Usunięto z podglądu stare elementy wyboru zakresu cięcia, pozostawiając
ustawianie zakresu w zakładce Rendering/Export.

## Stan początkowy i root cause

Worktree był już zmodyfikowany przez wcześniejsze zadania; zmian tych nie
resetowano ani nie nadpisywano. Branch: `integration/intel-amd`, HEAD przed
zadaniem: `feb0482`.

Stary UI był zaimplementowany w dwóch miejscach:

- `SeekBar` rysował pomarańczowe zaznaczenie A–B, czerwone znaczniki cięć,
  żółty marker A i czerwony marker B oraz pozwalał przeciągać A/B.
- `VideoPreview` dodawał przyciski `✂`, undo i restore. Były one widoczne po
  przejściu do Rendering, mimo że właściwe kontrolki IN/OUT znajdowały się już
  w `RenderTab._build_inout_bar()`.

Preview był współdzielony między Projekt i Rendering, dlatego usunięcie UI z
`VideoPreview` i neutralizacja `SeekBar` obejmuje oba miejsca użycia.

## Implementacja

- `SeekBar` zachowuje zwykły tor, playhead, kliknięcie i drag scrubowania.
  Nie rysuje markerów, nacięć ani zakresu A–B i nie interpretuje kliknięcia
  jako drag markera.
- Usunięto trzy przyciski cięcia z `VideoPreview` oraz ich lokalne handlery.
- Preview przestał synchronizować własną oś czasu z `controller._cut_regions`.
  Istniejące wewnętrzne API mapowania zakresu w `SeekBar` pozostaje dla
  kompatybilności modelu danych, ale nie jest eksponowane wizualnie.
- Usunięto skipowanie `cut_regions` z preview playbacku i seekowania; preview
  pozostaje neutralnym podglądem pełnej osi źródłowej.
- `RenderTab` nadal ma przyciski `IN`, `OUT`, `Wyczyść zakres` oraz zapisuje
  graniczne `cut_regions` do kontrolera. Odczyt pozycji Export odbywa się teraz
  bezpośrednio z neutralnej osi źródłowej.
- Usunięto pozostały overlay z `preview_mixin.py`: czerwony pasek i napis
  `WYCIĘTY FRAGMENT` nie są już rysowane, a `cut_regions` nie wyłączają HUD-u
  ani nie zmieniają pikseli preview.
- Nie zmieniano backendu eksportu ani modelu `controller._cut_regions`.

## Zmienione pliki

- `src/gui/qt/widgets/seek_bar.py`
- `src/gui/qt/widgets/video_preview.py`
- `src/gui/qt/_mixins/playback_mixin.py`
- `src/gui/qt/main_window.py`
- `src/gui/qt/tabs/project_tab.py`
- `src/gui/qt/tabs/render_tab.py`
- `tests/test_preview_range_markers_removal.py` — nowy kontrakt preview
- `tests/test_render_tab.py` — aktualizacja nieaktualnych asercji starego UI
- `tests/test_cut_feature.py` — pozostawiono testy wewnętrznego mapowania
  zakresu Export; usunięto testy usuniętych kontrolek preview

## Weryfikacja

Automatyczny test Qt w trybie offscreen potwierdził:

- brak `cut_btn`, undo i restore w `VideoPreview`,
- brak markerów A/B, pomarańczowego zakresu i czerwonych nacięć w rasterze
  `SeekBar`, także gdy wewnętrzne API otrzyma zakresy,
- brak czerwonego paska i etykiety `WYCIĘTY FRAGMENT` w renderowanej klatce
  preview,
- kliknięcie na dawną pozycję markera nadal wykonuje scrub,
- playhead pozostaje aktywny,
- `RenderTab` nadal udostępnia `IN`, `OUT` i `Wyczyść zakres`,
- stan cięcia Export nie skraca osi ani czasu neutralnego preview,
- współdzielenie preview Projekt/Rendering pozostaje zachowane.

Wyniki:

```text
pytest tests/test_cut_feature.py tests/test_preview_range_markers_removal.py tests/test_render_tab.py -q
38 passed

python -m compileall -q
PASS
```

Pełny test repository również został uruchomiony: `1120 passed, 37 skipped,
60 failed`. Pozostałe failures dotyczą wcześniejszych, niezależnych zmian i
brakujących/niezgodnych danych oraz kontraktów AMD/HUD/telemetrii; żaden z
testów bieżącego kontraktu preview/Export nie pozostał failing. Nie traktuję
tego jako globalnego PASS całego dirty worktree.

Manualne oględziny GUI z rzeczywistym oknem nie były wykonywane; weryfikacja
GUI jest automatyczna, Qt offscreen.

## Git diff stat

Stat całego istniejącego worktree (z wcześniejszymi zmianami użytkownika),
wykonany po zadaniu:

```text
32 files changed, 777 insertions(+), 661 deletions(-)
```

Nowy test preview jest nieśledzony w bieżącym worktree i dlatego nie jest
uwzględniany przez zwykłe `git diff --stat`.

## Backend isolation / ryzyka

Zmiana dotyczy wyłącznie Qt preview/playback i przepływu kontrolek Export.
Nie modyfowano kodu AMD, Intel, NVIDIA, encoderów ani renderera HUD.
Pozostawione `cut_regions` nadal są używane przez ścieżkę eksportu. Osierocony
`TrimBar` nie jest używany przez aktualny `MainWindow`/`RenderTab` i nie został
usunięty poza zakresem tego zadania.

## Final verdict

**PASS — preview nie eksponuje już zakresu cięcia; Export zachowuje obsługę
IN/OUT; play/pause, playhead i scrub pozostają dostępne.**

Nie wykonano commit ani push zgodnie z poleceniem.
