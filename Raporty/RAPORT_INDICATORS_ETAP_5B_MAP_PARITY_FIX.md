# TeleM — ETAP 5B: minimalny fix parity mapy CPU_REFERENCE vs AMD

Data: 2026-08-21  
Zakres: minimalny fix first-render mapy oraz dedykowany test lokalnego fixture.

## 1. Root cause

ETAP 5A potwierdził, że CPU i AMD używają tego samego `MovingMapRenderer`, tile source, tracku, zoomu i style. Różnica powstawała przy niegotowym cache:

- CPU uruchamiał `background_precache()` i renderował z `download_missing=False`;
- pierwszy render AMD używał `download_missing=True`;
- brakujący tile pozostawał CPU ciemnym gridem `(30,30,30,255)`, a AMD pobierał go inline.

## 2. Implementowany fix

Zmieniony plik: `src/indicators/moving_map.py`, funkcja `_render_moving_map_indicator()`.

Przed:

```python
dl_missing = getattr(renderer, "_is_first_render", False)
renderer.render(..., download_missing=False)
```

Po:

```python
dl_missing = getattr(renderer, "_is_first_render", False)
renderer.render(..., download_missing=dl_missing)
```

CPU first render zachowuje się teraz tak samo jak AMD first-render preparation: może synchronicznie uzupełnić wymagane brakujące tile’e dokładnie raz. Po ustawieniu `_is_first_render = False` kolejne klatki nadal używają `download_missing=False`.

Nie dodano retry loop, nowego cache, zmian w downloaderze ani zmian w AMD.

## 3. Dlaczego fix jest minimalny

Wykorzystuje istniejącą flagę `_is_first_render`, istniejący `TileCache`, istniejące timeouty downloadera i istniejący fallback placeholdera. Zmieniona została jedna wartość argumentu w istniejącym wywołaniu renderera; compositor, layout, telemetry, AMD ordered map i NVIDIA pozostały bez zmian.

## 4. First-render behavior przed/po

| Path | Before | After |
|---|---|---|
| CPU / preview | `background_precache()` async + `download_missing=False` | first render `download_missing=True`, następne `False` |
| AMD map preparation | first render `True`, następne `False` | bez zmian |
| offline CPU | ciemny placeholder przy niedostępnym tile’u | ten sam deterministyczny placeholder, bez zawieszenia |
| offline AMD | ciemny placeholder po nieudanym pobraniu | bez zmian, taki sam raw wynik jak CPU |

## 5. Offline behavior

Dedykowany test używa lokalnego fake downloadera zwracającego `None`. CPU i AMD-style preparation:

- nie crashują;
- nie czekają bez końca;
- wykonują ograniczoną próbę pobrania;
- zwracają identyczny raw raster z obecnym ciemnym placeholderem brakującego tile’a.

Nie zmieniano istniejącego timeoutu `_download_tile_raw()` ani kontraktu `TileCache`.

## 6. Thread/cache safety

`background_precache()` nadal jest daemon thread, a jego zachowanie nie zostało przebudowane. CPU first render może działać równolegle z istniejącym precache, ale korzysta z tej samej polityki `download_missing=True`, co AMD. Nie dodano nowego współdzielonego stanu, blokady, retry ani ścieżki zapisu.

Istniejący `TileCache` zachowuje SQLite primary key `(z,x,y,style)`, lock LRU i obsługę błędów SQLite. Testy lokalnego fixture obejmujące sekwencję first-render/second-render i dostęp do cache nie wykazały deadlocku ani błędów; nie zastępują one osobnego testu wielowątkowego `background_precache()`.

## 7. Nowy test regresyjny

Dodano:

`tests/test_map_first_render_parity.py`

Test korzysta wyłącznie z lokalnych PNG fixture i tymczasowych baz SQLite:

1. dokładnie jeden tile jest missing w środku viewportu;
2. CPU first render pobiera go raz i generuje pełny raster;
3. drugi CPU render nie wykonuje kolejnego pobrania;
4. AMD-style first preparation przy identycznym fixture daje identyczny raster;
5. offline missing tile daje identyczny deterministyczny fallback;
6. complete cache nie wykonuje żadnego pobrania.

Wynik nowego testu: `3 passed`.

## 8. CPU vs AMD raw parity

Na materiale referencyjnym zapisano:

- [CPU raw 5B](MAP_PARITY_5B_CPU_RAW.png)
- [AMD raw 5B](MAP_PARITY_5B_AMD_RAW.png)

Parametry: v2, `video_time=60.0 s`, 3840×2160, effective zoom `16`, working raster `768x768`, bbox `[2918,437,768,768]`.

```text
dimensions: 768x768 RGBA / 768x768 RGBA
mean absolute pixel diff: 0.0
pixels >5: 0.0%
pixels >20: 0.0%
max channel diff: 0
```

Kontrolowany missing-tile test również zakończył się raw diff `0` po fixie.

## 9. Preview result

CPU preview mapy dla dokładnego materiału i punktu 60 s wygenerował pełny raster bez ciemnego brakującego tile’a. Cache był kompletny w czasie renderu materiału, a test lokalny potwierdził zachowanie first render przy jednym brakującym tile’u.

Orientacyjny koszt na materiale referencyjnym:

```text
CPU first render: 271.6 ms
CPU second render: 1.1 ms
```

Koszt jest jednorazowy dla utworzenia renderera/gridu; kolejne klatki nie wykonują synchronicznych pobrań.

## 10. AMD runtime result

Krótki probe `AMD_NATIVE_D3D11` z presetem v2 zakończył się sukcesem. Logi:

```text
AMD_MAP_PATH: GPU
AMD_MAP_ORDER: CPU_BELOW_MAP -> GPU_MAP -> CPU_ABOVE_MAP
AMD_TELEMETRY_MODE: PRECOMPUTED
```

Zachowane zostały również `GPU_SPLIT` chart, GPU gauge, D3D11VA decode, route, marker i ordered z-order. Nie wprowadzono dodatkowego GPU→CPU readbacku ani zmian w uploadzie mapy, filtrze, D3D11 lub AMF.

## 11. Performance sanity

Nie wykonano benchmarku etapowego. Pomiar orientacyjny first/second render wskazuje jednorazowy koszt około `271.6 ms` vs `1.1 ms` na kompletnym cache. Nie zmieniano kolejnych klatek ani nie dodano pobierania tile’i na każdej klatce.

## 12. NVIDIA impact

Nie dodano żadnej logiki NVIDIA. Wspólny CPU map raster może pośrednio poprawić ścieżkę NVIDIA korzystającą z `compose_overlay()` / `frame_renderer.py`; po ewentualnym dalszym fixie należy uruchomić testy NVIDIA map bounds i preview/final parity.

NVIDIA path preserved statically; runtime validation was not possible on this AMD machine.

## 13. Lista zmienionych plików

Zmiany produkcyjne:

- `src/indicators/moving_map.py`

Test:

- `tests/test_map_first_render_parity.py`

Raport i artefakty:

- `Raporty/RAPORT_INDICATORS_ETAP_5B_MAP_PARITY_FIX.md`
- `Raporty/MAP_PARITY_5B_CPU_RAW.png`
- `Raporty/MAP_PARITY_5B_AMD_RAW.png`

Nie zmieniano presetów, `def_layout.json`, compositora, `src/map_renderer.py`, `src/indicators/static_map.py`, `src/ffmpeg/amd_native_exporter.py`, `src/ffmpeg/streaming.py` ani `src/ffmpeg/command_builder.py`.

## 14. Remaining risks

- Pierwszy render może chwilowo blokować się na istniejącym timeoutcie downloadera, jeśli tile jest niedostępny; nie ma jednak nieskończonego oczekiwania.
- `background_precache()` pozostaje asynchroniczny i może równolegle próbować pobrać ten sam tile, ale jest to istniejący mechanizm również używany przez AMD.
- NVIDIA runtime nie był dostępny na tej maszynie.
