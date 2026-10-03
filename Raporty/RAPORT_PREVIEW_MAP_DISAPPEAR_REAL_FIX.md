# RAPORT: REALNY FIX ZNIKANIA MAPY W PREVIEW (PREVIEW MAP DISAPPEAR FIX)

Data: 2026-10-03
Autor: Antigravity Agent
Status: ZAKOŃCZONY POMYŚLNIE / SUCCESS

---

## 1. KLUCZOWE METRYKI I PARAMETRY AUDYTU

```text
ROOT_CAUSE=1) Brak importu 'os' w src/moving_map.py (render_track_up rzucał NameError: name 'os' is not defined przy os.environ.get, co zewnętrzny try/except tłumił zwracając None i powodując całkowite znikanie mapy przy orientacji track_up); 2) W src/indicators/static_map.py nadal aktywny był twardy warunek 'coverage >= 0.5' z fallbackiem do _placeholder() i render_overview_map(); 3) Thread storm: w moving_map.py przy braku kafelków każda klatka uruchamiała nowy 'threading.Thread(target=_detail_fill)'; 4) Brak unieważniania cache renderera po pobraniu kafelków w tle; 5) W src/map_renderer.py brak obsługi preview_only na zimnym cache.
PREVIOUS_FIX_MISSING_OR_REGRESSED=YES
ASYNC_COVERAGE_GATE_BEFORE=YES (w static_map.py coverage >= 0.5; w moving_map.py powiązane z fallbackami)
ASYNC_COVERAGE_GATE_AFTER=NO (usunięto próg widoczności; coverage decyduje WYŁĄCZNIE o zleceniu pobierania)
PLACEHOLDER_FALLBACK_BEFORE=YES (_placeholder 'Ładowanie mapy…' aktywne przy braku kafelków)
PLACEHOLDER_FALLBACK_AFTER=NO (nigdy nie zastępuje właściwej mapy)
OVERVIEW_FALLBACK_BEFORE=YES (render_overview_map / MapContext zastępował mapę)
OVERVIEW_FALLBACK_AFTER=NO (brak fallbacku; neutralne tło zachowuje trasę i marker)
TRACK_MAP_PROJECT_AVAILABLE=YES (dostępność liczona raz dla całego projektu, nie znika per-frame)
CACHE_MISS_COVERAGE=0.0
CACHE_MISS_MAP_VISIBLE=YES
CACHE_MISS_TRACK_VISIBLE=YES
CACHE_MISS_MARKER_VISIBLE=YES
SEEK_TEST_PASS=YES (przetestowano sekwencję 0% -> 25% -> 50% -> 75% -> 10% na realnym GUI)
PREFETCH_THREAD_STORM_FIXED=YES (BEFORE=thread-per-frame, AFTER=1 dedykowany worker TeleM-PreviewTiles)
MAIN_NEW_SHA=15d84235bfc57aaf919c707dadd60502688a535d739071d57a9a20920414b734
PORTABLE_SHA=15d84235bfc57aaf919c707dadd60502688a535d739071d57a9a20920414b734
SOURCE_HASH_PARITY=YES
TESTED_RUNTIME_ROOT=C:\_DEV\BikeRideHUD-main-new
FILES_CHANGED=src/indicators/moving_map.py, src/indicators/static_map.py, src/map_renderer.py, src/moving_map.py, src/gui/map_viewport_prefetch.py, tests/test_map_overview_first.py, tests/test_preview_map_cache_miss.py, tests/manual_preview_map_real_gui.py
TESTS_PASSED=16
TESTS_FAILED=0
COMMIT=fb4bdb1
FINAL_STATUS=SUCCESS
```

---

## 2. POTWIERDZENIE ŹRÓDEŁ RUNTIME I HASH PARITY

Audyt hashów SHA-256 wykazał pełną zgodność między środowiskiem deweloperskim a portable:

| Plik | Ścieżka main-new | Ścieżka portable | Status SHA-256 |
|---|---|---|---|
| `moving_map.py` | `src/indicators/moving_map.py` | `src/indicators/moving_map.py` | `15d84235bfc57aaf919c707dadd60502688a535d739071d57a9a20920414b734` (MATCH) |
| `static_map.py` | `src/indicators/static_map.py` | `src/indicators/static_map.py` | MATCH |
| `map_renderer.py` | `src/map_renderer.py` | `src/map_renderer.py` | MATCH |
| `moving_map.py` (core) | `src/moving_map.py` | `src/moving_map.py` | MATCH |
| `map_viewport_prefetch.py` | `src/gui/map_viewport_prefetch.py` | `src/gui/map_viewport_prefetch.py` | MATCH |
| `test_preview_map_cache_miss.py` | `tests/test_preview_map_cache_miss.py` | `tests/test_preview_map_cache_miss.py` | MATCH |

**Potwierdzenie:** `SOURCE_HASH_PARITY=YES`.

---

## 3. IDENTYFIKACJA ROOT CAUSE

Przeanalizowano kod i zachowanie w trakcie seek / playback w GUI:

1. **Cichy błąd krytyczny w `src/moving_map.py` (`render_track_up`):**
   W funkcji `render_track_up` znajdowało się wywołanie:
   ```python
   if os.environ.get("TELEM_MAP_DUMP_FRAMES") == "1":
   ```
   jednak na początku modułu brakowało instrukcji `import os`! W rezultacie przy domyślnej orientacji `map_orientation="track_up"` rzucany był wyjątek `NameError: name 'os' is not defined`. Zewnętrzny blok `try...except Exception: return None, 0, 0, None` wyłapywał ten błąd i zwracał `None`, przez co wskaźnik mapy ruchomej w preview całkowicie znikał w trakcie obrotu i odświeżania klatek.

2. **Pozostałość bramki `coverage >= 0.5` w `src/indicators/static_map.py`:**
   W `static_map.py` nadal znajdował się warunek:
   ```python
   if coverage >= 0.5:
       ...
   else:
       return _placeholder(w, h, "Ładowanie mapy…")
   ```
   co przy niepobranych kafelkach powodowało natychmiastowe zniknięcie mapy i zastąpienie jej szarym boksem z napisem.

3. **Plaga wątków (Thread Storm) przy seek / play:**
   Przy każdej klatce z `coverage < 1.0` kod wywoływał:
   ```python
   threading.Thread(target=_detail_fill, daemon=True).start()
   ```
   Szybkie przewijanie (seek) generowało dziesiątki równoległych wątków uderzających w I/O i serwery kafelków, blokując wątki i powodując zacięcia i spadek płynności interfejsu.

4. **Brak inwalidacji cache po doczytaniu kafelków w tle:**
   Po asynchronicznym pobraniu kafelków `_map_cache` nie wiedział, że dyskowy cache został zaktualizowany, przez co na zatrzymanej klatce nadal pokazywane było tło z momentu braku kafelków, dopóki użytkownik nie zmienił klatki.

5. **`map_renderer.py` fallback na placeholder zamiast rysowania ścieżki:**
   Gdy `download_missing=False`, `MapRenderer` przy pustym cache zwracał obraz zastępczy zamiast wygenerować neutralne tło i nałożyć na nie ścieżkę trasy (track) oraz kropkę pozycji (marker).

---

## 4. ZASTOSOWANE ROZWIĄZANIA ARCHITEKTONICZNE

1. **Poprawka importu `os` i wersjonowanie pamięci podręcznej w `src/moving_map.py`:**
   - Dodano brakujący import `import os`.
   - Wprowadzono `TileCache._content_revision`, zwiększany przy każdym zapisie nowego kafelka na dysk.

2. **Dedykowany i deduplikowany prefetch worker (`src/gui/map_viewport_prefetch.py`):**
   - Utworzono komponent `PreviewViewportPrefetch` działający w oparciu o pojedynczy wątek roboczy `TeleM-PreviewTiles`.
   - Zabezpieczenie przed thread-storm: kolejka ograniczona (max 8 zadań), deduplikacja kluczy `(style, zoom, x_min, x_max, y_min, y_max)`, ignorowanie przestarzałych klatek przy intensywnym seeku, 10-sekundowy cooldown w przypadku braku sieci.

3. **Neutralne tło i 100% stabilność trasy w `src/map_renderer.py`:**
   - Dodano parametr `preview_only: bool = False`.
   - W przypadku `coverage == 0.0` (brak jakichkolwiek kafelków) renderowana jest jednolita ciemna kanwa `(30, 30, 30, 255)`, na której normalnie i precyzyjnie rysowana jest pełna trasa GPS oraz marker pozycji.
   - Ani wskaźnik, ani trasa, ani marker nigdy nie znikają.

4. **Wyeliminowanie progów i placeholderów z `src/indicators/moving_map.py` oraz `src/indicators/static_map.py`:**
   - Usunięto bramki `coverage >= 0.5`.
   - Wyeliminowano wywołania `_placeholder()` oraz `render_overview_map()` jako substytutów mapy.
   - Klucz pamięci podręcznej wskaźnika uwzględnia `(preview_viewport_prefetch.revision, TileCache.content_revision())` — gdy w tle pojawi się nowy kafelek, kolejna klatka (bądź wymuszone odświeżenie) natychmiast płynnie podmienia tło, bez zmiany geometrii, przesunięcia trasy czy skoków pozycji markera.

5. **Nienaruszony eksport końcowy (`async_map=False`):**
   - Ścieżka finalnego renderu / eksportu pozostała całkowicie niezmieniona (`preview_only=False`, pobieranie synchroniczne kafelków dla 100% jakości).

---

## 5. WYNIKI TESTÓW JEDNOSTKOWYCH I REGRESJI

Uruchomiono pełny zestaw testów `pytest`:

```text
tests\test_preview_map_cache_miss.py ..............                      [ 87%]
tests\test_map_overview_first.py ..                                      [100%]

============================= 16 passed in 3.80s ==============================
```

Przetestowane scenariusze:
- `test_moving_map_coverage_zero_renders_track_and_marker`: `coverage = 0.0` -> widoczna trasa, marker, brak wyjątków.
- `test_moving_map_coverage_thresholds_all_render`: progi `0.0`, `0.25`, `0.49`, `1.0` dla orientacji `north_up` oraz `track_up` renderują kompletną mapę z trasą i markerem.
- `test_static_map_preview_cache_miss_renders`: `static_map` w preview nie zwraca placeholdera przy `coverage = 0.0`.
- `test_prefetch_worker_deduplicates_requests`: deduplikacja żądań kafelków do 1 aktywnego zadania.
- `test_tile_download_refreshes_background_without_geometry_shift`: podmiana tła po doczytaniu kafelków bez zmiany wymiarów i pozycji ścieżki.
- `test_export_path_retains_synchronous_behavior`: `async_map=False` zachowuje pełne synchroniczne pobieranie i parzystość pikseli.

---

## 6. WERYFIKACJA NA RZECZYWISTYM GUI (REAL GUI E2E EVIDENCE)

Przeprowadzono automatyczny test na rzeczywistym oknie aplikacji `BikeRideHUD-main-new`, z realnym filmem `D:\GoPro\GX010338.MP4` oraz powiązanym plikiem FIT `24574176578.fit`, z wymuszonym pustym cache (`isolated_cache` w tempie).

Wyniki z `scratch/preview_map_real_gui/evidence.json`:

| Klatka / Zdarzenie | Coverage | Map Present | Track Present | Marker Present | HUD Widget Visible | Pixmap Present |
|---|---|---|---|---|---|---|
| `FRAME 0` | 0.0 | YES | YES | YES | YES | YES |
| `FRAME 100` | 0.0 | YES | YES | YES | YES | YES |
| `FRAME 500` | 0.0 | YES | YES | YES | YES | YES |
| `FRAME 1000` | 0.0 | YES | YES | YES | YES | YES |
| `FRAME 2000` | 0.0 | YES | YES | YES | YES | YES |
| `SEEK 0%` | 0.0 | YES | YES | YES | YES | YES |
| `SEEK 25%` | 0.0 | YES | YES | YES | YES | YES |
| `SEEK 50%` | 0.0 | YES | YES | YES | YES | YES |
| `SEEK 75%` | 0.0 | YES | YES | YES | YES | YES |
| `SEEK 10%` | 0.0 | YES | YES | YES | YES | YES |
| `AFTER PRELOAD` | 1.0 | YES | YES | YES | YES | YES |

- **Liczba uruchomionych wątków prefetch podczas całego testu:** `prefetch_threads_started = 1` (wyeliminowano thread storm).
- **Po doczytaniu kafelków (`coverage = 1.0`):** rozmiar i współrzędne wskaźnika `(x: 99, y: 224, size: [183, 183])` pozostały identyczne co do piksela, trasa i marker idealnie spasowane.
- **Wynik ogólny testu GUI:** `PASS`.

---

## 7. PODSUMOWANIE
Wszystkie 15 punktów specyfikacji zadania zostało zrealizowanych i zweryfikowanych. Kod został zsynchronizowany pomiędzy `C:\_DEV\BikeRideHUD-main-new` a `C:\_DEV\BikeRideHUD-portable` z potwierdzeniem zgodności SHA-256 (`SOURCE_HASH_PARITY=YES`).
