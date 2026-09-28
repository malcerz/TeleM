# RAPORT: AMD MAP BACKGROUND PREFETCH ARCHITECTURE & COLD-START ELIMINATION

## 1. Cel i Podsumowanie Zadania
Celem zadania było wyeliminowanie ~2.5-minutowego opóźnienia cold-start (`CLICK_TO_FIRST_FRAME ≈ 153 s`, z czego `tile/precache ≈ 151 s`) występującego przy braku kafli mapy w pamięci podręcznej.

Wdrożono architekturę asynchronicznego pobierania kafli w tle na poziomie projektu (`MapBackgroundPrefetchManager`), która przygotowuje niezbędne zasoby mapy natychmiast po wczytaniu mediów / telemetrii / zmianie stylu lub zoomu, podczas gdy użytkownik swobodnie edytuje layout lub przegląda wideo. Jednocześnie zachowano deterministyczny fallback poprawności w eksporterze (`ensure_map_tiles_cached()`), gwarantujący 100% kompletności kafli przy renderowaniu bez duplikowania pobierania ani blokowania interfejsu GUI.

---

## 2. Kluczowe Metryki i Podsumowanie Wymagane

```text
PREVIOUS_COLD_RENDER_WAIT_SECONDS=151

PREFETCH_ASYNC=True
PREFETCH_BLOCKS_GUI=False

PREVIEW_EXPORT_SHARED_TILE_CACHE=True

BACKGROUND_PREFETCH_TOTAL_SECONDS=43.11

REQUIRED_TILES=70
UNIQUE_REQUIRED_TILES=70
DUPLICATE_TILE_REQUESTS=0

TILES_READY_BEFORE_RENDER=70
MISSING_TILES_AT_RENDER=0

RENDER_AFTER_READY_FIRST_FRAME_MS=2313.80
RENDER_DURING_PREFETCH_FIRST_FRAME_MS=26315.40

CACHE_LOCK_WAIT_MS=0.00
GUI_THREAD_BLOCK_MS=0.02

PROJECT_CHANGE_CANCEL_SAFE=True
STALE_GENERATION_IGNORED=True

MAP_CORRECTNESS=PASS
AMD_RENDER_REGRESSION=NONE

ROOT_CAUSE=Synchronous blocking tile download in ensure_map_tiles_cached() on cold cache prior to frame loop (151s delay).
FIX=Project-level background prefetch with generation tokens, non-blocking GUI status, shared tile cache, and safety fallback in exporter.

MODIFIED_FILES=11
CASE=CASE A — background prefetch works, normal render <=5 s
```

---

## 3. Szczegółowe Wyniki Scenariuszy Testowych

Pomiary wykonano w izolowanych, czystych katalogach cache (`cold_tile_cache`, `cold_tile_cache_partial`, `cold_tile_cache_cancel`) na referencyjnym zestawie AMD:
- Wideo: `Video/GX020079.MP4`
- FIT: `Video/GX020079.fit`
- Layout: `def_layout.json`
- Rozdzielczość: **3840x2160 (4K)**
- Klatki: **1131 frames**
- Backend: `AMD_NATIVE_D3D11`

### 3.1 Scenariusz 1: Cold Open → Background Prefetch → Render After Ready (Główny Case Produkcyjny)
1. **Otwarcie projektu w trybie cold cache**:
   - Wyczyszczono katalog `cold_tile_cache`.
   - Projekt i telemetria załadowane w ~2.35 s (`COLD_OPEN_TO_PREFETCH_START_MS = 2358.28 ms`).
   - Prefetch w tle natychmiast rozpoczął pobieranie 70 wymaganych kafli z zachowaniem limitów serwerów OSM.
   - Status GUI wyświetlał dyskretny postęp w pasku stanu: `Mapa: przygotowywanie 1/70` ... `Mapa: przygotowywanie 70/70` -> `Mapa: gotowa`.
   - GUI i podgląd wideo MPV pozostały w 100% responsywne (`GUI_THREAD_BLOCK_MS = 0.02 ms`).
2. **Ukończenie prefetchu**:
   - Czas trwania prefetchu w tle: **43.11 s** (`BACKGROUND_PREFETCH_TOTAL_SECONDS = 43.11`).
   - Kafle gotowe przed kliknięciem Render: **70 / 70** (`TILES_READY_BEFORE_RENDER = 70`).
3. **Kliknięcie Render**:
   - Kontrakt: `REQUIRED_TILES=70, CACHED_TILES=70, MISSING_TILES=0, BACKGROUND_PREFETCH_ACTIVE=False`.
   - Faza `tile/precache` w procesie potomnym renderera: **25.931 ms** (spadek ze 151 046.89 ms!).
   - Czas od kliknięcia do pierwszej klatki: **2,313.80 ms** (**2.31 s** <= 5.0 s hard gate **PASS**).
   - Renderowanie 1131 klatek 4K ukończone pomyślnie z kodem powrotu 0.

### 3.2 Scenariusz 2: Render w Trakcie Prefetchu (Kliknięcie przy 40% Pobrania)
1. **Otwarcie projektu w trybie cold cache**:
   - Prefetch wystartował asynchronicznie.
   - Przy osiągnięciu progu 40% (28/70 kafli) zainicjowano kliknięcie „Render”.
2. **Bezpieczne przejście i brak duplikatów**:
   - Menedżer prefetchu bezpiecznie anulował zadanie w tle (`prefetch_job_cancelled`), zwalniając wątki sieciowe.
   - Kontrakt: `REQUIRED_TILES=70, CACHED_TILES=28, MISSING_TILES=42, BACKGROUND_PREFETCH_ACTIVE=True`.
   - Brak jakichkolwiek duplikatów: `DUPLICATE_TILE_REQUESTS = 0`.
3. **Fallback eksportera**:
   - Funkcja `ensure_map_tiles_cached()` w rendererze pobrała wyłącznie brakujące 42 kafle (60%) z uczciwym raportowaniem postępu: `Przygotowanie mapy: X/70`.
   - Czas od kliknięcia do pierwszej klatki: **26.32 s** (dokładnie proporcjonalny do 42 brakujących kafli, eliminując 125 sekund zbędnego oczekiwania).
   - Cały render 1131 klatek 4K ukończony deterministycznie i bezbłędnie (`exitcode = 0`).

### 3.3 Scenariusz 3: Zmiana Projektu / Zoomu i Semantyka Anulowania (Generation Tokens)
1. Prefetch Generacji 1 wystartował dla trasy i zoomu 16.
2. W trakcie pracy zmieniono zoom na 12 (`prop_zoom`).
3. Nastąpiła natychmiastowa invalidacja:
   - Zdarzenie: `[MapPrefetch] Superseding generation 1 with new key (reason=prop_zoom)`.
   - Generacja 1 została bezpiecznie przerwana, a niespójne stare kafle pominięte (`STALE_GENERATION_IGNORED = True`).
   - Wystartowała Generacja 2 dla zoomu 12 (`PROJECT_CHANGE_CANCEL_SAFE = True`).
   - Brak równoległych downloaderów: `ACTIVE_PREFETCH_JOB_COUNT <= 1`.

---

## 4. Analiza Przyczyny Źródłowej i Wdrożone Zmiany

### 4.1 Przyczyna Źródłowa (Root Cause)
W dotychczasowej architekturze przygotowanie kafli było powiązane wyłącznie z momentem uruchomienia eksportu:
```text
Load Project -> Idle / Layout Edit -> Click Render -> ensure_map_tiles_cached() [SYNCHRONOUS NETWORK DOWNLOAD 151s] -> First Frame
```
Dopiero wewnątrz procesu potomnego renderera sprawdzano stan pamięci podręcznej i sekwencyjnie pobierano setki brakujących kafli, blokując pętlę klatek i powodując wrażenie zawieszenia programu.

### 4.2 Wdrożona Architektura Prefetchu
1. **Wzorzec Singletonu i Tokenów Generacji (`src/gui/map_prefetch.py`)**:
   - `MapBackgroundPrefetchManager` monitoruje stan projektu i layoutu.
   - Posiada ściśle ograniczoną pulę 4 wątków roboczych z odstępami `polite delay` zgodnymi z polityką OSM.
   - Każde nowe zapotrzebowanie otrzymuje unikalny token generacji (`_current_generation += 1`). Starsze zadania natychmiast weryfikują `cancel_event` przed każdym żądaniem HTTP.
2. **Niezmienniczość Właściwości Wizualnych (Cache Key Invariance)**:
   - Klucz generacji zależy wyłącznie od: `(route_hash, provider, zoom, style, orientation)`.
   - Zmiany parametrów wizualnych widgetu (`x, y, shape, pitch, opacity, border, selection`) nie restartują prefetchu i nie generują zbędnych zapytań.
3. **Współdzielona Fizyczna Pamięć Podręczna (`SHARED_TILE_CACHE = True`)**:
   - Zarówno proces nadrzędny GUI, jak i proces potomny renderera korzystają z tej samej zmiennej `TELEM_TILE_CACHE_DIR` oraz wspólnej bazy SQLite (`tilecache.sqlite`).
   - Kafle pobrane w tle podczas pracy w GUI są natychmiast widoczne dla procesu renderera bez ponownego pobierania.
4. **Dyskretny Status w GUI (`src/gui/qt/main_window.py`)**:
   - Informacje o postępie są emitowane przez `sig_map_status` i prezentowane w dedykowanej etykiecie paska stanu: `Mapa: przygotowywanie X/Y` -> `Mapa: gotowa`.
   - Główny pasek postępu renderowania pozostaje nienaruszony i służy wyłącznie właściwemu procesowi eksportu.

---

## 5. Weryfikacja Poprawności Mapy i Izolacji Backendów

1. **Testy Jednostkowe Mapy i Geometrii**:
   - Uruchomiono pełny zestaw 45 testów poprawności:
     - `tests/test_map_perspective.py`
     - `tests/test_amd_map_shape_ui_legacy_reset.py`
     - `tests/test_amd_map_cache_readd.py`
     - `tests/test_amd_map_correctness.py`
   - Wynik: **45 passed in 1.24s** (`MAP_CORRECTNESS = PASS`).
   - Żadne parametry projekcji GPS, zoomu, centrowania ani perspektywy nie uległy zmianie.

2. **Izolacja Backendów (AGENTS.md)**:
   - Zmiany wprowadzono wyłącznie w warstwie GUI, zarządzania pamięcią podręczną oraz pipeline AMD.
   - Backend NVIDIA oraz Intel pozostały nietknięte.
   - AMF HEVC encode i D3D11 compositor zachowały pełną stabilność i płynność (1131 klatek 4K wyrenderowane bez błędów).

---

## 6. Zmodyfikowane i Utworzone Pliki

### Nowe pliki:
1. `src/gui/map_prefetch.py` — singleton menedżera prefetchu w tle z obsługą generacji i logowaniem CSV.
2. `scratch/amd_map_background_prefetch/prefetch_timeline.csv`
3. `scratch/amd_map_background_prefetch/prefetch_events.csv`
4. `scratch/amd_map_background_prefetch/tile_counts.csv`
5. `scratch/amd_map_background_prefetch/cache_paths.txt`
6. `scratch/amd_map_background_prefetch/cold_background_ready.txt`
7. `scratch/amd_map_background_prefetch/render_after_ready.txt`
8. `scratch/amd_map_background_prefetch/render_during_prefetch.txt`
9. `scratch/amd_map_background_prefetch/project_change_cancel.txt`
10. `scratch/amd_map_background_prefetch/root_cause.md`
11. `scratch/amd_map_background_prefetch/implementation.md`
12. `scratch/amd_map_background_prefetch/modified_files.txt`
13. `scratch/amd_map_background_prefetch/created_files.txt`
14. `scratch/amd_map_background_prefetch/reproduction_commands.txt`
15. `scratch/amd_map_background_prefetch/artifacts_manifest.txt`
16. `scratch/amd_map_background_prefetch/ntfy_result.txt`
17. `Raporty/RAPORT_AMD_MAP_BACKGROUND_PREFETCH.md`

### Zmodyfikowane pliki:
1. `src/gui/qt/_mixins/project_mixin.py` — wyzwalanie prefetchu przy wczytaniu projektu, mediów i telemetrii.
2. `src/gui/qt/_mixins/preset_mixin.py` — filtr zmian właściwości i wyzwalanie przy zmianie zoomu/stylu.
3. `src/gui/qt/_mixins/indicator_mixin.py` — wyzwalanie przy dodaniu widgetu mapy.
4. `src/gui/qt/_mixins/render_mixin.py` — logowanie kontraktu mapy i koordynacja z menedżerem prefetchu.
5. `src/gui/qt/main_window.py` — etykieta statusu mapy w pasku stanu Qt.
6. `src/gui/qt/signals.py` — sygnały `sig_map_status` i `sig_map_progress`.
7. `src/gui/qt/controller.py` — powiązanie sygnałów statusu prefetchu.
8. `src/gui/qt/application.py` — obsługa harnessów testowych dla prefetchu.
9. `src/moving_map.py` — dynamiczna obsługa `TELEM_TILE_CACHE_DIR` oraz właściwość `db_path`.
10. `src/indicators/moving_map.py` — wydzielenie wspólnej funkcji `calculate_required_map_tiles()`.
11. `src/ffmpeg/amd_native_exporter.py` — logowanie kontraktu i synchronizacja fallbacku.

---

## 7. Weryfikacja NTFY Hard Gate
Wykonano powiadomienie webhook NTFY na adres `https://ntfy.sh/MalcerzPOP`:
- Treść: `AMD map prefetch: case=CASE A, missing-at-render=0, first-frame=2313.80ms.`
- Status: **Sukces w 1. próbie** (`NTFY_SUCCESS=True`).
- Wynik zapisany w `scratch/amd_map_background_prefetch/ntfy_result.txt`.
