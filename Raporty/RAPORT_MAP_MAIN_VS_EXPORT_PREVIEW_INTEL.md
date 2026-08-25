# TeleM — Main Preview vs Export Preview: mapa na Intel

## 1. Reprodukcja

Opisany objaw został odtworzony na poziomie kontraktu renderera: `MapContext` ma gotowy `overview_image`, ale jego stan wskazuje na trwające przygotowanie szczegółów. Przed poprawką asynchroniczna ścieżka Main Preview zwracała placeholder mimo dostępnego obrazu overview.

Nie wykonano fizycznego testu widocznego okna Qt ani pomiaru na dokładnie nowym MP4 użytkownika. Obowiązuje: `PHYSICAL GUI VISUAL TEST: NOT EXECUTED`.

## 2. Main Preview pipeline

`src/gui/qt/_mixins/preview_mixin.py::_render_preview()` publikuje bieżący `map_context` przez `set_current_map_context()` (linia 343), wylicza `target_dt` w przygotowaniu danych overlay i wywołuje `render_preview(..., async_map=True)` (linia 562 i 592). Dalej:

`src/indicators/compositor.py::render_preview()` → `compose_overlay()` → `src/indicators/dispatcher.py::render_value_indicator()` → `static_map.py::_render_static_map_indicator()` albo `moving_map.py::_render_moving_map_indicator()`.

Main Preview używa więc współdzielonego przez GUI `MapContext` i nieblokującej ścieżki async.

## 3. Export Preview pipeline

`src/gui/qt/tabs/render_tab.py::_build_preview_qimage()` wylicza `target_dt` przez `VideoTimeline.global_to_absolute()` (gdy timeline istnieje), buduje `overlay_data` i wywołuje `render_preview()` w linii 856 bez `async_map=True`, czyli synchroniczną ścieżkę mapy.

W tej ścieżce `static_map.py`/`moving_map.py` korzystają z `render_map_overlay()`/`MovingMapRenderer` i cache kafelków. Export Preview nie korzysta z GUI-owego `MapContext` jako bramki placeholdera. Dlatego kompletna mapa w Export Preview nie była dowodem, że Main Preview wybiera właściwy stan.

## 4. Pierwsza różnica

W Main Preview przed poprawką oba renderery wykonywały:

```python
if snap["status"] == "error":
    return placeholder
if snap["status"] in ("idle", "preparing"):
    return placeholder
```

Ten warunek był wykonywany bez sprawdzenia `snap["overview_image"]`. Export Preview nie miał tej bramki i mógł wykorzystać gotowe kafelki/cache. To była pierwsza istotna różnica wejścia/decyzji renderera, nie problem Intel/QSV, FIT ani pobierania GPS.

## 5. Stan MapContext

Main Preview używa jednego obiektu `self.map_context`, przekazanego do globalnego `map_prepare._CURRENT_MAP_CONTEXT`; w aktualnej ścieżce nie utworzono drugiego MapContext dla mapy.

Export Preview korzysta z synchronicznego renderera i nie przechodzi przez tę bramkę `MapContext`. Nie zmieniono architektury generation guard ani provider cache.

## 6. Overview/detail/placeholder decision

Po poprawce oba asynchroniczne renderery najpierw wyznaczają:

```python
overview_ready = snap.get("overview_image") is not None
```

Placeholder jest zwracany dla `idle`/`preparing` lub `error` tylko wtedy, gdy overview nie istnieje. Gdy overview istnieje, renderer przechodzi do dotychczasowej logiki: pokazuje overview, a szczegóły są doczytywane w tle; przy wystarczającym pokryciu szczegółowym używany jest normalny render mapy.

## 7. Faktyczna przyczyna

Placeholder miał pierwszeństwo nad gotowym overview w Main Preview. Status `preparing` oznaczał przygotowanie bieżącego/refinement jobu, ale był traktowany jak brak jakiejkolwiek użytecznej mapy.

## 8. Zmiana

Minimalnie zmieniono:

- `src/indicators/static_map.py` — overview ma pierwszeństwo przed placeholderem;
- `src/indicators/moving_map.py` — identyczny kontrakt dla ruchomej mapy;
- `tests/test_map_overview_first.py` — regresja dla obu form.

Nie zmieniano finalnego renderera, dekoderów, encoderów, QSV, AMF, NVENC, CUDA ani logiki telemetrycznej.

## 9. Standard

Przypadek `overview_image` gotowe + `status=preparing` jest testowany dla `static_map`. Renderer zwraca obraz mapy, nie ciemny placeholder.

## 10. Satellite

Warunek działa provider-neutralnie: najpierw sprawdzany jest zgodny provider (`snap["provider"] == map_style`), następnie obecność overview. Przełączanie Standard/Satellite oraz generation lifecycle pozostają bez zmian. Nie wykonano fizycznego przełączenia w GUI.

## 11. Timing przed/po

W teście regresyjnym decyzja o zwróceniu obrazu overview jest synchroniczna i nie wykonuje pobierania kafelków; czas renderu jest poniżej 1 s. Nie zmierzono jeszcze czasu od żądania klatki do fizycznie widocznej klatki na maszynie Intel.

## 12. Intel

Problem jest backend-neutralny. Kod mapy w tej poprawce nie zależy od Intel/QSV, AMD/AMF ani NVIDIA/NVENC. Maszyna Intel ujawniła objaw, ale nie wymagała specjalnego `if intel`.

## 13. AMD/NVIDIA preservation

Sprawdzono diff i zakres zmian: dotknięte są wyłącznie renderery wskaźnika mapy oraz test. Ścieżki AMD, NVIDIA, Intel i CPU pozostają statycznie zachowane; AMD/NVIDIA nie były runtime-testowane na tej maszynie.

## 14. Testy

- `python -m pytest -q tests/test_map_overview_first.py tests/test_map_preload_etap1.py tests/test_map_sync.py` — **54 passed**.
- `python -m pytest -q tests/test_map_preload_etap1b_runtime.py tests/test_map_first_render_parity.py tests/test_track_up_map.py tests/test_static_indicator_cache.py` — **12 passed, 2 skipped, 1 unrelated failure**.
- `tests/test_static_indicator_cache.py::test_slope_dynamic_marker_and_static_style_miss` fails także uruchomiony osobno (`misses == 0`, oczekiwano `>= 2`); nie dotyczy mapy ani zmienionych plików.
- `py_compile` zmienionych modułów i testu — bez błędów.

## 15. Real GUI

`PHYSICAL GUI VISUAL TEST: NOT EXECUTED`.

## 16. Deferred issues

- real mouse selection/drag,
- final render time overlap,
- Lean preview/final mismatch,
- altitude rotated text.

