# ETAP 7B — RESULT

Data: 2026-08-18  
Zakres: ordered AMD `track_map` compositing. Nie zmieniano semantyki mapy,
geometrii, tracku, markera, zoomu, stylu, rotacji ani alpha.

## A. Audyt stanu wejściowego

Dotychczasowy compositor wykonywał GPU map jako ostatni pass. Guard wymagał,
aby `track_map` był ostatnim włączonym wpisem. Dla aktualnego
`def_layout.json` po mapie występują wpisy FIT, z których część ma `None`.
Ten stan był fałszywie niebezpieczny: mapę można było uruchomić GPU, gdy
wszystkie wpisy po niej były niewidoczne.

## B. Zmieniona semantyka z-order

Wprowadzono wyłącznie jeden, stały podział:

```text
CPU_BELOW_MAP → GPU_MAP → CPU_ABOVE_MAP
```

Podział zachowuje kolejność insertion-order layoutu. `custom_texts`, które
compositor Pillow rysuje po wszystkich indicatorach, trafiają do `above`.
`time_block` / `time_display` pozostają w warstwie below, zgodnie z ich
specjalną kolejnością renderowania.

## C. Implementacja

Zmodyfikowane pliki:

- `src/ffmpeg/amd_native_exporter.py`
- `native/d3d11_amf_pipeline/src/d3d11_vp_pipeline.h`
- `native/d3d11_amf_pipeline/src/d3d11_vp_pipeline.cpp`
- `native/d3d11_amf_pipeline/src/telem_amd_native.cpp`
- `tests/test_amd_native_ordered_map.py`

Nowe elementy:

- `_ordered_map_layout_parts()` — jeden lokalny split layoutu;
- `telem_amd_set_above_map_mode()`;
- `telem_amd_update_above_map()`;
- native `UpdateAboveMapTexture()` / `BlendAboveMap()`;
- kompaktowy upload tylko cropa alpha-bbox warstwy above;
- czyszczenie poprzedniego bbox przed blendem bieżącej warstwy.

Native kolejność jest teraz:

```text
VideoProcessor base
→ GPU charts/gauge (jeżeli bezpieczne i przed mapą)
→ GPU map
→ compact CPU above layer
→ final HUD/NV12 compositor
```

Nie powstał generalized compositor ani ścieżka wielu map.

## D. Przypadki layoutu

| Przypadek | Wynik |
|---|---|
| map-first | GPU map + pusty/aktywny above |
| map-middle | GPU map + CPU above |
| map-last | GPU map + pusty above |
| map disabled/unavailable | dotychczasowy CPU_REFERENCE |
| więcej niż jeden canonical map | safe fallback CPU_REFERENCE |
| `None` po mapie | nie blokuje GPU; above pozostaje pusty |
| chart/gauge po mapie | nie są capture’owane do GPU; renderują się w CPU_ABOVE_MAP |

## E. Weryfikacja aktualnego layoutu

Realny `def_layout.json` zachowano bez zapisu. Próba na
`Video/GX030120.MP4` wykazała:

```text
AMD_MAP_PATH requested/effective: GPU/GPU
AMD_MAP_ORDER: CPU_BELOW_MAP -> GPU_MAP -> CPU_ABOVE_MAP
CPU_ABOVE_MAP: EMPTY
GPU map geometry: dst=(3035,137), src=692x692, out=691x691
```

Pusta warstwa above jest poprawna: wpisy po mapie na aktualnym materiale nie
zwracają widocznej wartości.

## F. Weryfikacja realnego overlapu

Wykonano wariant in-memory, bez modyfikacji pliku layoutu: `temp_text` został
przeniesiony za `track_map`. Wynik:

```text
AMD_MAP_PATH: GPU
AMD_MAP_ORDER: ... CPU_BELOW_MAP -> GPU_MAP -> CPU_ABOVE_MAP
after: ... temp_text
AMD Native processed: 6
AMF output: 6
AMF dropped: 0
HW decode proof: YES
final mux: SUCCESS
```

Widoczny `temp_text` był renderowany w osobnej warstwie above; native blend tej
warstwy następuje po GPU map.

## G. Chart / gauge

Dotychczasowy chart `GPU_SPLIT` i gauge GPU pozostają przed mapą, jeśli są w
warstwie below i spełniają istniejące guardy. Wpis po mapie nie jest przekazywany
do capture GPU, więc nie może zostać przypadkowo narysowany przed mapą.

## H. Upload / wydajność

Warstwa above nie powoduje uploadu pełnego 4K HUD. Python przekazuje tylko
RGBA crop obejmujący nieprzezroczysty bbox. Przy pustym above przekazywany jest
wyłącznie sygnał clear poprzedniego bbox. Bazowe dirty-region HUD i istniejące
uploady mapy pozostały bez zmiany.

## I. Ochrona mapy

Nie zmieniono:

- `render_map_working_image()`;
- źródła i danych tracku;
- pozycji, rozmiaru i geometrii mapy;
- zoomu, stylu, rotacji i alpha;
- filtra GPU mapy;
- liczby map — nadal obsługiwany jest jeden canonical `track_map`.

## J. Testy ETAPU 7B

Dodano `tests/test_amd_native_ordered_map.py` obejmujący:

- map-first / map-middle / map-last;
- zachowanie insertion-order;
- unavailable after-map indicator;
- `custom_texts` jako above;
- obecność native entrypoints i passu `BlendAboveMap`.

Wynik testów powiązanych:

```text
50 passed
```

Pełna suite:

```text
326 passed, 3 failed, 17 skipped
```

Trzy failure’y są wcześniejsze i niezwiązane z ETAPEM 7B:

```text
tests/test_amd_native_etap4.py
tests/test_qp_analyzer.py
tests/test_render_tab.py
```

Nie naprawiano ich.

## K. Build native

Właściwy target `telem_amd_native` został zbudowany poprawnie przez MinGW.
Historyczny target `d3d11_etap2c_poc` nadal ma niezależny wcześniejszy błąd
`CreateHUDTexture`; nie jest używany przez produkcyjną DLL.

## L. Regression

Nie zmieniano implementacji:

```text
GPS9 / SmartSync / track_map data / telemetry / chart history / STEP lookup
```

Pozostały również bez zmian GPU chart/gauge, AMF, dekoder D3D11VA oraz
rendering layoutu.

## M. Status

```text
CONFIRMED:
- ordered single-map split działa w Python i native;
- pusty after-map nie blokuje GPU map;
- widoczny after-map indicator ma osobny pass po mapie;
- insertion-order layoutu nie jest zmieniany;
- realny AMD Native export kończy się sukcesem.

SUSPECTED:
- brak.

OUT OF SCOPE:
- generalized compositor;
- multiple maps;
- zmiany map renderer/settings;
- GPU chart/gauge generalization;
- telemetry, renderer, GPU optimization i layout redesign.
```

ETAP 7B zakończony. Zatrzymano pracę zgodnie z zakresem.
