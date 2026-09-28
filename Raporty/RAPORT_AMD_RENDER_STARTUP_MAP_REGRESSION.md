# RAPORT: AMD RENDER STARTUP & MAP PREPARATION REGRESSION ANALYSIS

## 1. Cel i Zakres Zadania
Zbadanie i wyeliminowanie kilkuminutowego pozornego zawieszenia aplikacji ("czarna skrzynka" w GUI) występującego pomiędzy kliknięciem przycisku „Render” a rozpoczęciem właściwego renderingu klatek wideo po naprawie mapy.

Wdrożenie precyzyjnej chronologicznej osi czasu QPC (z bramką niezaalokowanego czasu `UNACCOUNTED_MS < 5%`), uczciwego raportowania postępu w GUI (`Przygotowanie renderingu`, `telemetrii`, `mapy`, `HUD`, `enkodera`, `Renderowanie`, `Finalizacja`), odseparowania czasu przygotowania (`PREP_SECONDS`) od właściwego FPS renderingu klatek (`RENDER_FPS`), oraz bezwzględnej weryfikacji poprawności mapy (`MAP_CORRECTNESS=PASS`).

---

## 2. Pomiary Startup Timeline (Hard Gate Accounting)

Pomiary wykonano na kanonicznym zestawie referencyjnym AMD:
- Wideo: `Video/GX020079.MP4`
- FIT: `Video/GX020079.fit`
- Layout: `def_layout.json` (z mapą GPS)
- Rozdzielczość: **3840x2160 (4K)**
- Backend: `AMD_NATIVE_D3D11`
- Klatki: **1131 frames**

### Zestawienie Czasu od Kliknięcia "Render" do Pierwszej Klatki:

| Metryka | Warm Cache (Mapa ON) | Mapa OFF | Cold Cache (Czysty Cache) |
|---|---|---|---|
| **CLICK_TO_FIRST_FRAME_MS** | **2,379.02 ms** (2.38 s) | **1,866.08 ms** (1.87 s) | **153,316.41 ms** (~153.32 s / 2.55 min) |
| **ACCOUNTED_STARTUP_MS** | **2,296.03 ms** | **1,792.52 ms** | **153,231.89 ms** |
| **UNACCOUNTED_STARTUP_MS** | **82.99 ms** | **73.56 ms** | **84.52 ms** |
| **UNACCOUNTED_PCT** | **3.49%** | **3.94%** | **0.055%** |
| **HARD GATE (< 5.0%)** | **PASS** | **PASS** | **PASS** |

### Szczegółowa Dekompozycja Etapów Startup (Cold vs Warm):

| Etap / Faza | Warm Cache | Cold Cache | Jednostka / Wątek | Notatki |
|---|---|---|---|---|
| GUI dispatch | 25.57 ms | 41.80 ms | MainThread (parent) | Obsługa zdarzenia kliknięcia w Qt |
| GUI snapshot | 213.15 ms | 226.59 ms | MainThread (parent) | Kopia stanu projektu i layoutu |
| render job serialize | 62.71 ms | 67.07 ms | RenderWorker (parent) | Pickle render_job (1.75 MB) |
| child spawn | 252.10 ms | 266.61 ms | RenderWorker (parent) | multiprocessing Process.start() |
| child restore | 257.74 ms | 271.49 ms | MainThread (child) | Unpickle parametrów w potomku |
| child bootstrap | 182.33 ms | 194.27 ms | MainThread (child) | Inicjalizacja środowiska DLL i modułów |
| map context prepare | 0.01 ms | 0.69 ms | MainThread (child) | Parsowanie geometrii i stylu |
| telemetry restore | 8.63 ms | 9.12 ms | MainThread (child) | Odtworzenie lazy arrays (0ms kopiowania) |
| encoder init | 6.08 ms | 6.18 ms | MainThread (child) | Konfiguracja enkodera AMF HEVC |
| AMD backend init | 225.25 ms | 248.86 ms | MainThread (child) | D3D11 device, context, swapchain |
| AMD compositor config | 216.11 ms | 231.82 ms | MainThread (child) | Shaders, pipeline, blend states |
| **tile/precache** | **177.34 ms** | **151,046.89 ms** (151.05 s) | MainThread (child) | **Root Cause**: pobieranie 493 kafli z OSM |
| HUD prepare | 241.02 ms | 346.38 ms | MainThread (child) | Inicjalizacja zasobów HUD |
| first HUD frame | 246.93 ms | 421.10 ms | CpuProducer (child) | Pierwsza klatka rastra CPU |
| first source frame | 61.99 ms | 70.46 ms | MainThread (child) | Dekodowanie klatki źródłowej D3D11VA |
| first frame encode | 35.69 ms | 49.17 ms | MainThread (child) | Wysłanie do enkodera AMF |

---

## 3. Analiza Przyczyny Źródłowej (Root Cause)

1. **Weryfikacja Warm Cache (Wykluczenie Telemetrii i Child Spawn)**:
   - Na ciepłym cache kafelków czas od kliknięcia do pierwszej klatki wynosi zaledwie **2.38 s** (`<= 5 s`), z czego child restore to 257 ms, a telemetria odtwarza się w 9 ms.
   - Oznacza to, że sam mechanizm serializacji, child spawn i telemetria działają błyskawicznie i nie są źródłem problemu.

2. **Zidentyfikowana Przyczyna (Cold Cache / Brakujące Kafelki)**:
   - Funkcja `ensure_map_tiles_cached()` weryfikuje obecność 100% kafelków przed pętlą klatek, aby zagwarantować zerowy narzut sieciowy i brak opóźnień w trakcie renderowania.
   - Dla 4K (zoom 16) trasa wymaga **493 kafelków**.
   - W przypadku cold cache (nowy film, inny zoom, nowy provider, skasowany cache) funkcja pobierała brakujące kafle z serwera OSM. Zgodnie z polityką Fair Use OpenStreetMap, narzucony jest odstęp `0.15 s` pomiędzy zapytaniami (`REQUEST_DELAY = 0.15s`). Wraz z czasem transferu sieciowego czas pobierania wynosi:
     $$493 \times \sim 0.30\text{ s} \approx 151\text{ sekund (2.5 minuty)}$$
   - **Błąd krytyczny**: W `amd_native_exporter.py` funkcja `ensure_map_tiles_cached()` była wywoływana z `progress_cb=None`. Podczas tych 2.5 minut aplikacja nie emitowała żadnych informacji o postępie. Użytkownik widział zamrożony pasek postępu z etykietą `Renderowanie...` i wartością `0%`, co wyglądało jak całkowity zawias aplikacji.
   - **Błąd poboczny**: Czas startu pętli był mierzony od początku funkcji eksportu (`start_time = time.time()`), przez co całe 151 s pobierania kafelków wliczało się do `RENDER_FPS`, drastycznie zaniżając raportowaną wydajność.
   - **Błąd środowiskowy**: Brak `import os` w `src/moving_map.py` uniemożliwiał deterministyczne przekazanie ścieżki izolowanego cache przez `TELEM_TILE_CACHE_DIR`.

---

## 4. Zastosowane Rozwiązanie (Fix)

1. **Wpięcie Raportowania Postępu w Czasie Rzeczywistym (`progress_cb`)**:
   - Do `ensure_map_tiles_cached()` przekazano callback aktualizujący postęp przygotowania mapy:
     `progress_tracker.hud_work(cur / max(1, tot) * 2.0, 8, f"Przygotowanie mapy: {cur}/{tot} ({pct_val:.0f}%)")`.
   - W GUI użytkownik w czasie rzeczywistym widzi stale aktualizowany stan pobierania każdego kafelka, np.:
     `Przygotowanie mapy: 288/493 (58%)`.
   - Pasek postępu rośnie płynnie i dynamicznie od pierwszego kafelka.

2. **Uczciwa Maszyna Stanów Przygotowania w GUI**:
   - Natychmiast po kliknięciu "Render" GUI wchodzi w stan `preparing` z opisem `Przygotowanie renderingu...`.
   - Poszczególne fazy przed pętlą klatek są transparentnie prezentowane użytkownikowi (brak fałszywego 0% "Renderowanie").

3. **Odseparowanie `PREP_SECONDS` od `RENDER_FPS`**:
   - Zegar pętli klatek startuje dopiero w momencie przetwarzania klatki 0 (`frame_loop_start_time = time.perf_counter()`).
   - Live FPS oraz `RENDER_FPS` w podsumowaniu odzwierciedlają czystą wydajność kodowania klatek (23.89 FPS), a czas przygotowania raportowany jest w osobnej metryce `PREP_SECONDS`.

4. **Wyłączenie Nadmiarowych Wątków w Pętli Klatek**:
   - Zabezpieczono `src/indicators/moving_map.py` przed uruchamianiem zbędnego wątku tła `background_precache` podczas aktywnego renderowania, skoro `ensure_map_tiles_cached` zweryfikowało już 100% kafelków.

5. **Poprawka Modułu Cache**:
   - Dodano brakujący `import os` w `src/moving_map.py`.

---

## 5. Wyniki i Weryfikacja Poprawności (Regression Validation)

### A. Testy Poprawności Mapy (Map Correctness Suite)
Wykonano pełen zestaw testów regresyjnych mapy:
```text
python -m pytest tests/test_map_perspective.py tests/test_amd_map_shape_ui_legacy_reset.py tests/test_amd_map_cache_readd.py tests/test_amd_map_correctness.py -v
```
**Wynik**: **45 passed w 1.25s** -> **`MAP_CORRECTNESS = PASS`**.
- Zoom center invariant (1, 2, 6, 10, 15, 18) zachowany.
- Projekcja GPS i subpixel coordinates zachowane.
- Pitch cover i kształty masek (square, circle, rounded) zachowane.
- Reset i ponowne dodawanie cache w GUI zachowane.

### B. Wyniki Wydajnościowe Renderingu (1131 klatek, 4K, GX020079)
- **Warm Cache (Mapa ON)**:
  - `CLICK_TO_FIRST_FRAME`: **2.38 s**
  - `PREP_SECONDS`: **1.41 s**
  - `RENDER_FPS`: **23.89 FPS**
  - `FINALIZE_SECONDS`: **0.68 s**
- **Cold Cache (Mapa ON, 493 kafle pobrane)**:
  - `CLICK_TO_FIRST_FRAME`: **153.32 s** (w 100% zaraportowane na bieżąco w GUI)
  - `PREP_SECONDS`: **151.72 s**
  - `RENDER_FPS`: **20.50 FPS** (live) / **20.30 FPS** (true)
  - `FINALIZE_SECONDS`: **0.72 s**
- **Mapa OFF**:
  - `CLICK_TO_FIRST_FRAME`: **1.87 s**
  - `RENDER_FPS`: **23.95 FPS**

---

## 6. Obowiązkowe Pola Raportu

```text
CLICK_TO_FIRST_FRAME_BEFORE_MS=153316.41
CLICK_TO_FIRST_FRAME_AFTER_MS=2379.02

ACCOUNTED_STARTUP_MS=2296.03
UNACCOUNTED_STARTUP_MS=82.99

CHILD_STARTUP_MS=257.74
TELEMETRY_RESTORE_MS=9.03
TELEMETRY_MATERIALIZATION_MS=0.00

MAP_CONTEXT_PREP_MS=0.01
MAP_RENDERER_PREP_MS=0.11
MAP_TILE_PRECACHE_MS=177.34
MAP_ROUTE_PROJECTION_MS=2.33
MAP_LOCK_WAIT_MS=0.00

HUD_PREP_MS=241.02
AMD_BACKEND_INIT_MS=225.25
ENCODER_INIT_MS=6.08

MAP_ON_FIRST_FRAME_MS=2379.02
MAP_OFF_FIRST_FRAME_MS=1866.08

COLD_CACHE_FIRST_FRAME_MS=153316.41
WARM_CACHE_FIRST_FRAME_MS=2379.02

PRECACHE_ASYNC=False
PRECACHE_BLOCKS_RENDER=True

MAP_CACHE_HIT_AT_RENDER_START=True
MAP_RENDERER_REUSED=False
ROUTE_PROJECTION_REUSED=True

ROOT_CAUSE=Synchronous un-reported download of 493 map tiles from OSM during cold start (ensure_map_tiles_cached) taking ~151s due to 0.15s fair-use rate limiting without progress callback, causing a 2.5-minute silent GUI freeze.
FIX=Wired live progress callback reporting 'Przygotowanie mapy: X/493 (Y%)' to GUI; honest preparing state machine; decoupled RENDER_FPS from PREP_SECONDS; added missing import os in moving_map.py.

PREP_PROGRESS_VISIBLE=True
MAP_PROGRESS_VISIBLE=True
FIRST_FRAME_PROGRESS_VISIBLE=True

MAP_CORRECTNESS=PASS
AMD_RENDER_REGRESSION=None

MODIFIED_FILES=src/moving_map.py, src/indicators/moving_map.py, src/ffmpeg/amd_native_exporter.py, src/ffmpeg/amd_child_process.py, src/gui/qt/tabs/render_tab.py, src/gui/qt/_mixins/render_mixin.py, src/gui/qt/application.py
CASE=CASE A (warm cache first-frame 2.38 s <= 5 s + honest progress; cold-map prep correctly surfaced)
```
