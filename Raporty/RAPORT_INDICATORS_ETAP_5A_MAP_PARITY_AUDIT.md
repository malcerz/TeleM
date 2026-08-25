# TeleM — ETAP 5A: audyt parity mapy CPU_REFERENCE vs AMD

Data: 2026-08-21  
Zakres: diagnostyka wyłącznie; kod produkcyjny nie był modyfikowany.

## 1. Reprodukcja problemu

Materiał i layout:

```text
presets/cycling_dashboard_v2.json
Video/GX030120.MP4
Video/Popoludniowa_jazda_na_rowerze_solar_battery.fit
Video/GX030120.json
video_time = 60.0 s
activity_time = 60.0 s
frame = 1799 (1-based)
resolution = 3840x2160
```

W czasie audytu bieżący cache był już kompletny dla badanego viewportu, więc zwykła reprodukcja dała pełną mapę CPU i AMD. Kontrolowany test z jednym brakującym centralnym tile’em odtworzył dokładnie obserwowany objaw: CPU pozostawił ciemny obszar, a ścieżka AMD uzupełniła tile podczas pierwszego renderu.

## 2. CPU map pipeline

Dla `track_map.form = "map"` v2 ścieżka jest następująca:

```text
preset track_map
  → src/indicators/compositor.py:compose_overlay()
  → src/indicators/dispatcher.py:render_value_indicator()
  → src/indicators/moving_map.py:_render_moving_map_indicator()
  → src/moving_map.py:MovingMapRenderer
  → TileCache (SQLite + in-memory LRU)
  → MovingMapRenderer.render()
  → apply_map_shape("square")
  → Pillow compositor / CPU_REFERENCE
```

Konkretne parametry v2:

- configured zoom: `14`;
- effective zoom na canvasie 3840 px: `16` (`src/indicators/moving_map.py:_map_render_plan`);
- źródło: `fit`;
- style: `light_all`;
- working/source raster: `768x768`;
- destination bbox: `[2918, 437, 768, 768]`;
- track width po skalowaniu zoom: `8` px;
- marker radius po skalowaniu zoom: `28` px;
- shape: square;
- track i marker są rysowane przez ten sam `MovingMapRenderer`.

CPU tworzy renderer, uruchamia `background_precache()` w daemon thread, a następnie wywołuje `render(..., download_missing=False)`. Brakujący tile nie jest wtedy pobierany synchronicznie.

`src/map_renderer.py` i `src/indicators/static_map.py` są osobną, starszą ścieżką `static_map`; nie są używane przez v2 `form = "map"`.

## 3. AMD map pipeline

AMD wybiera ordered map path po guardzie pojedynczego canonical `track_map`:

```text
layout
  → _map_gpu_layout_safe()
  → _ordered_map_layout_parts()
  → CPU_BELOW_MAP: compose_overlay()
  → render_map_working_image()
  → ten sam MovingMapRenderer / ten sam TileCache
  → map_data: RGBA bytes 768x768
  → telem_amd_update_map()
  → GPU_MAP: D3D11 resize/blend
  → CPU_ABOVE_MAP: compose_overlay()
  → final D3D11 frame
```

AMD nie buduje mapy innym rendererem i nie korzysta z innego źródła tile’i. `render_map_working_image()` tworzy ten sam typ `MovingMapRenderer`, uruchamia precache, a przy pierwszym renderze ustawia `download_missing=True`. Po pierwszym renderze flaga `_is_first_render` przechodzi na `False`.

Runtime AMD probe zakończył się sukcesem i zgłosił:

```text
AMD_MAP_PATH: GPU
GPU map filter: LANCZOS (2) | GPU map path: DIRECT_AUTO (0)
AMD_MAP_ORDER: CPU_BELOW_MAP -> GPU_MAP -> CPU_ABOVE_MAP
AMD_CHART_PATH: GPU_SPLIT
AMD_GAUGE_PATH: GPU
AMD_TELEMETRY_MODE: PRECOMPUTED
AMD Native video decode: GPU_HUD_D3D11VA
GPU charts fallback -> CPU_REFERENCE (no active chart widgets)
GPU gauge fallback -> CPU_REFERENCE bbox=None (gauge not rendered)
```

Nie ma dowodu na ponowne renderowanie mapy w C++/D3D11. AMD dostaje raster wygenerowany po stronie Pythona i dopiero ten raster blenduje na GPU.

## 4. Porównanie wejść

| Parametr | CPU | AMD |
|---|---:|---:|
| track points | 1707 | 1707 |
| target timestamp | `2026-08-18T04:47:25.700000+00:00` | taki sam |
| renderer time from track start | `2765.700000 s` | taki sam |
| renderer-selected GPS sample | index `888`, `04:47:26` | taki sam |
| sample lat/lon | `54.34901587665081, 18.61895595677197` | taki sam |
| configured/effective zoom | `14 / 16` | `14 / 16` |
| style | `light_all` | `light_all` |
| raster size | `768x768` RGBA | `768x768` RGBA |
| destination bbox | `[2918,437,768,768]` | taki sam |
| tile source | CartoCDN `light_all` | taki sam |

Wymagany viewport obejmuje tile coordinates:

```text
z=16
x=36154..36160
y=20930..20936
49 tile’i
```

## 5. Raw map comparison

Artefakty przed compositingiem:

- [CPU raw](MAP_PARITY_CPU_RAW.png)
- [AMD raw](MAP_PARITY_AMD_RAW.png)
- [CPU second render](MAP_PARITY_CPU_SECOND.png)
- [CPU after synchronous precache](MAP_PARITY_CPU_PRECACHED.png)

CPU raw został przechwycony z wyniku `render_value_indicator()` dla mapy, a AMD raw z wyniku `render_map_working_image()` przekazywanego do `telem_amd_update_map()`.

Oba rastry mają `768x768`, `RGBA`, alpha extrema `220..255`. Dla bieżącego kompletnego cache:

| Porównanie | Mean absolute diff | >5 | >20 |
|---|---:|---:|---:|
| CPU raw vs AMD raw | `0.0` | `0.0%` | `0.0%` |
| CPU first vs CPU second | `0.0` | `0.0%` | `0.0%` |
| CPU first vs CPU after precache | `0.0838` | `0.0%` | `0.0%` |

Wniosek: przy kompletnym cache CPU i AMD przekazują ten sam raster mapy.

## 6. Tile/cache analysis

| Cache / warstwa | CPU | AMD | Klucz | Moment utworzenia | Ryzyko różnicy |
|---|---|---|---|---|---|
| `TileCache` SQLite | tak | tak | `(z,x,y,style)`; PK w `tilecache.sqlite` | `MovingMapRenderer` | brak, jeśli tile jest gotowy |
| `TileCache._mem` LRU | tak | tak | `(z,x,y,style)`, max 256 | przy odczycie/zapisie tile’a | proces/invalidation timing |
| renderer grid cache | tak | tak | tile range, zoom, style, track draw/color/width | pierwszy render viewportu | użycie niepełnego gridu jest trwałe dla renderera |
| `background_precache` | daemon thread | daemon thread | track + zoom + style w instancji renderera | przy pierwszym rendererze | brak join/wait przed CPU renderem |
| legacy `src/map_renderer.py` PNG cache | nie dla v2 `form=map` | nie | `~/.telem_map_tiles/{z}/{x}/{y}.png` | tylko `static_map` | nie jest przyczyną tego przypadku |

Cache użyty w audycie:

```text
C:\Users\Malcerz\.telem_map_tiles\tilecache.sqlite
```

Wszystkie 49 wymaganych w tym punkcie tile’i było obecnych. Każdy zapisany blob był PNG `256x256`, palette mode `P`, a po odczycie `TileCache` konwertuje go do RGBA. Rozmiary blobów wynosiły `9717..22044` bajtów. Alpha tile’i była całkowicie nieprzezroczysta (`255`). Brak placeholdera po stronie tile cache w aktualnym stanie.

Kontrolowany test z brakującym centralnym tile’em `z=16, x=36157, y=20933, style=light_all`:

```text
CPU: download_missing=False
CPU vs pełny raster: mean_abs=16.4883; pixels >5 = 10.4097%

AMD-like first render: download_missing=True
fetch: [16, 36157, 20933, light_all]
AMD-like vs pełny raster: mean_abs=0.0; pixels >5 = 0.0%
```

To jest kontrola na dokładnych danych tile’a z istniejącego cache, bez pobierania losowych nowych tile’i.

## 7. Async/timing analysis

Asynchroniczność ma wpływ i została potwierdzona.

CPU:

```text
background_precache(...)  # daemon, bez oczekiwania
render(..., download_missing=False)
```

AMD:

```text
background_precache(...)  # daemon
first render(..., download_missing=True)
subsequent render(..., download_missing=False)
```

W `MovingMapRenderer.render()` canvas grid startuje jako `(30,30,30,255)`. Jeżeli tile jest nieobecny i `download_missing=False`, pozostaje ciemnym prostokątem, podczas gdy route i marker są nadal rysowane. To dokładnie odpowiada opisowi „ciemny lub niepełny obszar kafli”.

Test powtarzalności:

- A — pierwszy CPU render w nowym procesie: pełny, bo 49/49 tile’i było już w cache;
- B — drugi CPU render w tym samym procesie: identyczny, diff `0.0`;
- C — istniejący synchroniczny `precache_tiles()`: `0` nowych tile’i, obraz pełny;
- D — nowy proces po istniejącym cache: pełny, identyczny raw CPU/AMD.

Brak pełnej mapy w pierwszym CPU renderze jest więc zależny od momentu i stanu cache, a nie od stałej różnicy zoomu, tracku ani źródła tile’i.

## 8. Alpha/compositing analysis

Raw CPU i raw AMD są identyczne, więc różnica nie powstaje w D3D11 blendzie ani w Pillow compositingu dla badanego pełnego cache.

- tile source: opaque PNG;
- raw map: RGBA, alpha `220..255`;
- `apply_map_shape("square")` nie wycina mapy;
- route ma półprzezroczysty kolor tracku, marker jest pełny;
- nie ma dowodu na premultiplied-vs-straight alpha jako przyczynę ciemnych tile’i.

## 9. Crop/resize/bbox analysis

CPU i AMD używają tego samego `768x768` working rasteru i tego samego destination bbox `[2918,437,768,768]`. W tym v2 przypadku source i destination mają ten sam rozmiar, więc nie ma realnego resize mapy na granicy Python → AMD.

AMD ma skonfigurowany filtr `LANCZOS` i `DIRECT_AUTO`, ale przy tych wymiarach nie tłumaczy brakujących/ciemnych tile’i. Crop oraz center na aktualnej pozycji są wykonywane przez wspólny `MovingMapRenderer`.

## 10. Pixel diff

Najważniejszy wynik:

```text
CPU raw != AMD raw: NIE — dla kompletnego cache są byte-identical.
```

Kontrolowana awaria niepełnego cache różni CPU od pełnego rastra przed compositingiem; AMD-like first render uzupełnia dokładnie ten sam tile i wraca do pełnej mapy.

## 11. Root cause

```text
ROOT CAUSE CONFIRMED
```

Dokładny mechanizm:

1. `src/indicators/moving_map.py:_render_moving_map_indicator()` uruchamia asynchroniczny `background_precache()`.
2. CPU renderuje natychmiast z `download_missing=False`.
3. `src/moving_map.py:280` inicjalizuje grid ciemnym `(30,30,30,255)`, a `src/moving_map.py:286` pobiera brakujący tile tylko wtedy, gdy `download_missing=True`.
4. `src/indicators/moving_map.py:render_map_working_image()` dla pierwszego renderu AMD ustawia `dl_missing=True`, więc AMD synchronicznie uzupełnia brakujące tile’e.

Różnica CPU vs AMD nie wynika z innego rastra, zoomu, bbox, tracku, markeru, alpha ani źródła mapy. Wynika z różnego zachowania przy niegotowym cache: CPU nie czeka i nie pobiera brakujących tile’i, AMD pierwszy render może je pobrać inline.

## 12. Minimalny plan naprawy — bez implementacji

Najmniejszy fix powinien ujednolicić gotowość tile’i przed pierwszym renderem CPU/AMD. Do rozważenia, w tej kolejności:

1. wspólny helper w `src/moving_map.py`, który przygotowuje wymagany viewport i daje deterministyczny status `ready/missing`;
2. w `src/indicators/moving_map.py` CPU: albo poczekać na zakończenie precache, albo wykonać dokładnie jeden synchroniczny `download_missing=True` dla pierwszego viewportu;
3. zachować jawny fallback offline: jeśli tile nie może być pobrany, obie ścieżki muszą zwrócić ten sam placeholder i ten sam log diagnostyczny;
4. nie zmieniać map style, zoom modelu, track-up ani z-order.

Potencjalnie zmieniane przy osobnym zadaniu byłyby:

- `src/indicators/moving_map.py` — wspólna polityka first render/cache readiness;
- ewentualnie `src/moving_map.py` — helper/status dla required tile range.

Nie ma potrzeby zmiany `src/map_renderer.py`, `src/indicators/compositor.py`, AMD DLL, D3D11, AMF ani telemetry.

## 13. Ryzyko dla AMD/NVIDIA

AMD: fix musi zachować ordered map path `CPU_BELOW_MAP -> GPU_MAP -> CPU_ABOVE_MAP`, obecne fallbacki oraz brak dodatkowego GPU→CPU readbacku.

NVIDIA korzysta statycznie ze wspólnego `compose_overlay()` przez `src/ffmpeg/frame_renderer.py`, więc fix w `src/indicators/moving_map.py` może automatycznie wpłynąć na NVIDIA CPU/reference HUD. Należy wykonać po fixie testy mapy preview/final oraz testy NVIDIA map region bounds.

NVIDIA path preserved statically; runtime validation was not possible on this AMD machine.

## 14. Test regresyjny potrzebny dla fixu

Brakujący test powinien:

1. utworzyć tymczasowy `TileCache` z jednym brakującym tile’em w środku viewportu;
2. uruchomić CPU first render i AMD map-preparation first render na identycznym tracku, zoomie i style;
3. sprawdzić, że oba raw rastry mają identyczne wymiary i diff `0`;
4. powtórzyć test z całkowicie gotowym cache oraz z nieosiągalnym tile’em/offline;
5. zachować asercję na route/marker, alpha i destination bbox.

Istniejące testy przeanalizowane i uruchomione:

```text
tests/test_map_sync.py
tests/test_etap8m_resolution_and_map.py
tests/test_etap8u_b_exact_map.py
tests/test_etap8u_c_universal_map.py
tests/test_amd_native_ordered_map.py
tests/test_amd_native_ordered_map_clear.py
tests/test_amd_native_above_dirty_bbox.py
tests/test_amd_native_etap4.py
tests/test_etap8m3_runtime_layout_and_parity.py
tests/test_nvidia_map_region_bounds.py
tests/test_gpmf_cache.py
tests/test_etap8q_dirty_text_cache.py
101 passed in 6.22s
```

Obecny zestaw testów sprawdza geometrię, sync, ordered map, dirty bbox i regiony NVIDIA, ale nie łapie asynchronicznego wyścigu `background_precache()` kontra różne wartości `download_missing` w CPU i AMD. Nie dodawano testu produkcyjnego w ETAPIE 5A.

## Stan kodu

Nie zmieniano kodu aplikacji, presetów, rendererów, compositora, FFmpeg, AMD, NVIDIA ani telemetry. Utworzono wyłącznie diagnostyczne skrypty tymczasowe oraz artefakty PNG i ten raport; skrypty zostaną usunięte po audycie.

