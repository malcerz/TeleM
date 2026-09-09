# Export Preview isolation i jednostki Distance BAR

Data: 2026-09-07  
Branch: `integration/intel-amd`  
HEAD: `59277b4c920e0bb8a9642e4a574a32db0edcfacc`  
Stan wejściowy: odzyskany dirty worktree po chirurgicznym rollbacku Stage A/C.

## Zakres i zasady bezpieczeństwa

Zadanie dotyczyło wyłącznie Export Preview oraz danych/skali Distance BAR.
Nie zmieniono w tym zadaniu:

- `native/d3d11_amf_pipeline/src/telem_amd_native.cpp` ani DLL,
- native pipe writera, D3D11 VP, AMF submit/query,
- Stage A/B/C, polecenia FFmpeg mux ani synchronicznego pipe I/O,
- lifecycle render cancel, producer, mux pump i FFmpeg,
- backendów Intel/NVIDIA.

Nie wykonano commit, push, reset, clean ani restore. Widoczne w `git status`
pozostałe zmiany rendererowe należą do odzyskanego stanu wejściowego, a nie do
tego zadania.

## Preview — ustalenia

### Pierwszy błąd

Historyczny log zawierał jedynie:

```text
[AMD DIRECT MUX] WARNING: pump did not stop within 2s; handle left to worker.
```

Jest to komunikat teardownu. Pierwszy organiczny wyjątek poprzedzający ten log
nie został zapisany i na podstawie istniejących artefaktów nie da się go
uczciwie odtworzyć. **Pierwszy organiczny wyjątek: NOT PROVEN.** Nie ma też
dowodu pozwalającego twierdzić, że sam wyjątek Python Preview bezpośrednio
zamknął pipe. Poprzedni raport audytu także oznaczył pierwotną przyczynę
`ERROR_NO_DATA` jako `NOT PROVEN`.

Audyt kodu wykazał jednak dwa konkretne problemy architektury Preview:

1. worker Preview wykonywał seek i operacje MPV/QMedia/Qt poza wątkiem GUI;
2. podczas AMD export wykonywany był dodatkowy `absolute+exact` seek/decode,
   równolegle z natywnym dekoderem Media Foundation D3D11VA.

To tłumaczyło duży koszt Preview i tworzyło niedozwolone ryzyko zasobowe, lecz
nie stanowi dowodu na dokładną kolejność historycznego teardownu.

Po dodaniu diagnostyki pierwszy rzeczywiście przechwycony wyjątek pochodzi z
obowiązkowego testu fault injection:

```text
[EXPORT PREVIEW ERROR]
generation=1
timestamp=0.300300
worker=TeleM-ExportPreview-1
stage=preview_worker
exception_type=RuntimeError
exception=preview fault injection
traceback=Traceback (most recent call last):
  File ".../src/gui/qt/tabs/render_tab.py", line 1387, in worker
    raise RuntimeError("preview fault injection")
RuntimeError: preview fault injection
```

Po tym wyjątku Preview wyłączyło tylko własną generację. Final render zakończył
1000/1000 klatek, FFmpeg pozostał żywy, a MP4 jest poprawny.

### Zasoby i architektura

Przed zmianą:

```text
render progress -> Preview worker -> exact seek MPV/QMedia -> HUD -> GUI
```

Worker korzystał z ogólnego stanu renderu (`_rendering`, `_cancelling`) i nie
miał własnego lifecycle. AMD render i Preview mogły równolegle używać dwóch
ciężkich ścieżek decode.

Po zmianie:

```text
render progress -> nadpisywalny latest timestamp -> maks. 1 Preview worker
                                               -> CPU/proxy snapshot + HUD
```

- Preview ma własny `stop_event`, niezależny od `render_cancel_event`,
  producera, mux pumpa i FFmpeg;
- wyjątek jest przechwytywany jako `BaseException`, logowany z pełnym
  tracebackiem i zatrzymuje wyłącznie bieżącą generację Preview;
- brak wait/join Preview w pętli renderu i brak backpressure;
- pending state przechowuje wyłącznie najnowszy timestamp;
- zmiana generacji unieważnia wynik starego workera;
- operacje Qt/player pozostają w GUI thread;
- AMD Export Preview nie uruchamia MPV/QMedia D3D11VA ani exact seek;
- orientacyjny obraz ma maks. 480 px szerokości, dekodowany jest CPU/proxy i
  cache'owany przez 8 s czasu źródła; HUD aktualizuje się z limitem 0.5 Hz;
- Preview używa asynchronicznej mapy (`async_map=True`), więc nie wykonuje
  synchronicznych pobrań kafli podczas eksportu.

Summary z testu 3000f:

```text
[EXPORT PREVIEW RESOURCES]
decoder=OpenCV/FFmpeg snapshot
hardware_decode=off
device=CPU/proxy
workers=1
updates=56
mean_ms=307.551
p95_ms=1003.141
```

## Distance BAR — źródło i przyczyna

Kontrakt po poprawce:

```text
telemetry/FIT distance internal = metry
Distance BAR current/range display = metry / 1000.0 = km
```

Źródłem dla FIT jest w pierwszej kolejności monotoniczny zapisany strumień
`fit_data["distance"]`. GPS-derived `fit_data["track"]` jest używany tylko jako
fallback, gdy zapisany dystans jest nieużyteczny. Current value i activity max
korzystają teraz z tego samego resolvera.

Przyczyna wartości typu `2183 KM ... 43746 KM` była dwuczęściowa:

- zakres FIT występował jako surowe metry, lecz w części ścieżek UI mógł być
  traktowany jako zakres wyświetlany w km;
- ścieżka Export Preview obliczała `auto_ranges`, ale nie przekazywała ich do
  `compose_overlay`, podczas gdy final renderer je przekazywał.

Poprawka centralizuje konwersję w `distance_m_to_km()` /
`distance_range_m_to_km()`, stosuje ją do zakresów GUI, przygotowania ramek i
compositora oraz przekazuje `overlay_data["auto_ranges"]` także w Export
Preview. Nie zmieniono geometrii, fontu, orientacji ani algorytmu ticków BAR.

Przykładowy rzeczywisty zakres FIT:

```text
source: 2183 m .. 43746 m
display: 2.183 km .. 43.746 km
```

## Zmienione pliki

- `src/gui/qt/tabs/render_tab.py` — niezależny Preview lifecycle, latest-state,
  CPU/proxy decode, limit 0.5 Hz, diagnostyka błędów i zasobów, forwarding
  `auto_ranges`;
- `src/telemetry_resolver.py` — wspólny kontrakt metrów i konwersja do km;
- `src/indicators/compositor.py` — jedna konwersja dystansu na granicy display;
- `src/indicators/frame_data.py` — wspólne źródło FIT current/max i zakres km;
- `src/gui/telemetry_manager.py` — dynamiczny zakres FIT m -> km;
- `src/gui/qt/_mixins/indicator_mixin.py` — GUI autoscale m -> km;
- `tests/test_amd_background_preview_audit.py`;
- `tests/test_export_preview_video_restore.py`;
- `tests/test_distance_bar_scale_contract.py`;
- `scratch/run_background_preview_audit.py` — kontrolowany harness A–D.

## Testy automatyczne

`py_compile` zmienionych modułów i harnessu: **PASS**.

Zestaw Preview + Distance BAR:

```text
25 passed
1 failed: test_marker_0_percent_at_scale_start (x=8, historyczne expected=10)
```

Jedyny fail dotyczy istniejącej geometrii środka markera (2 px), nie jednostki,
zakresu ani tej poprawki. Zgodnie z zakazem zmiany wyglądu BAR nie został
naprawiany opportunistycznie.

Konwersje jednostek:

| metry | wynik km |
|---:|---:|
| 0 | 0.0 |
| 500 | 0.5 |
| 1000 | 1.0 |
| 11500 | 11.5 |
| 43746 | 43.746 |

Testy potwierdzają również:

- auto range `2183..43746 m -> 2.183..43.746 km`;
- FIT recorded distance jako wspólne źródło current i max;
- fallback do GPS track tylko dla nieużytecznego recorded distance;
- wspólny `compose_overlay`, ten sam current oraz te same left/middle/right
  ticks w Preview i final render;
- latest-state-only, brak workera w tle i izolację fault injection.

## Testy renderu A–D

Testy A–C: `GX010115.MP4`, telemetry activity
`GX010114_116.fit`, aktualny layout 4K, pełny HUD, AMD D3D11VA + native HUD +
AMF, SYNC/queue 0. Są to testy funkcjonalne na fragmencie aktywności, nie nowy
kanoniczny baseline wydajności.

Test D: 1500 ostatnich klatek `GX010114.MP4` + 1500 pierwszych klatek
`GX010115.MP4`, z kanonicznym `GX010114_116.fit`; granica wystąpiła dokładnie
przy global frame 1500.

| Test | Preview | Frames | Render FPS | Effective FPS | Wynik |
|---|---|---:|---:|---:|---|
| A | OFF | 1000/1000 | 37.747 | 33.855 | PASS |
| B | ON | 1000/1000 | 32.152 | 29.403 | PASS |
| C | ON + fault | 1000/1000 | 38.640 | 34.656 | PASS, Preview zatrzymane lokalnie |
| D | ON, multi | 3000/3000 | 24.249 | 22.934 | PASS |

Dodatkowo test D raportował natywną wydajność per clip 42.347 oraz 43.435 FPS.
Całkowity wynik obejmuje przygotowanie HUD i koszt orientacyjnego Preview.
Jest wyraźnie lepszy od historycznego Preview ON około 17–18 FPS; nie dokonano
dalszej optymalizacji renderera.

W żadnym z A–D nie wystąpiły `ERROR_NO_DATA`, `ERROR_BROKEN_PIPE`, unexpected
FFmpeg exit ani pump teardown. Test D miał 0 map cache misses podczas renderu.

## ffprobe

| Artefakt | Video | Frames | Audio | Duration | Size |
|---|---|---:|---|---:|---:|
| A OFF | HEVC | 1000 | AAC, 1565 frames | 33.386667 s | 197993142 B |
| B ON | HEVC | 1000 | AAC, 1565 frames | 33.386667 s | 197993142 B |
| C fault | HEVC | 1000 | AAC, 1565 frames | 33.386667 s | 197993142 B |
| D multi | HEVC | 3000 | AAC, 4675 frames | 100.100000 s | 738747831 B |

Wszystkie kontenery MP4 są prawidłowe i mają oczekiwaną liczbę klatek.

## Ryzyka i ograniczenia

- Dokładny pierwszy organiczny wyjątek ze świeżej instancji użytkownika nie
  został zachowany w starym logu; jego root cause pozostaje `NOT PROVEN`.
- Preview jest celowo orientacyjne i może pokazywać bazową klatkę starszą o do
  około 8 s; HUD pozostaje latest-state z limitem 0.5 Hz.
- Preview nadal zużywa CPU i obniża całkowity FPS, ale nie blokuje logicznie
  render thread i nie korzysta z jego D3D11 device/lifecycle.
- Istniejący 2 px fail geometrii markera pozostaje poza zakresem.

## Kryteria READY

```text
PREVIEW ON DOES NOT BREAK FINAL RENDER: PASS
PREVIEW FAULT ISOLATED: PASS
PREVIEW NO MUX LIFECYCLE ACCESS: PASS
PREVIEW PERFORMANCE ACCEPTABLE: PASS
DISTANCE BAR UNIT: PASS
DISTANCE BAR SCALE: PASS
PREVIEW/FINAL BAR PARITY: PASS
3000F MULTIFILE: PASS
FINAL MP4 VALID: PASS
```

STATUS: **READY** dla zakresu Preview isolation + Distance BAR units.  
Historyczny organiczny wyjątek pozostaje jawnie **NOT PROVEN**; nie jest to
blokada dla potwierdzonej izolacji fault path i testów A–D.
