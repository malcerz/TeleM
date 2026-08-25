# TeleM — AMD ETAP 5C-PRECHECK

Status: **PASS — Preview i finalny eksport mają zgodny geograficzny viewport mapy.**

Zakres prac ograniczono do diagnostyki i poprawki correctness `track_map`. Nie wykonano optymalizacji planowanych dla ETAPU 5C; nie zmieniono GPU pipeline, telemetry, pozostałych wskaźników ani audio.

## ROOT CAUSE

Preview i eksport wywoływały ten sam łańcuch renderujący mapę:

`render_preview()` / finalny `compose_overlay()` → `render_value_indicator()` → `_render_moving_map_indicator()` → `MovingMapRenderer.render()`.

Obie ścieżki używały tego samego renderera kafelkowego, route background, interpolacji markera, cropu i cache. Różnił się canvas:

- rzeczywisty GUI Preview: `960×540`,
- finalny eksport: `3840×2160`.

`size=18%` dawało widget `173×173` w Preview oraz `691×691` w eksporcie. Jednocześnie obie ścieżki przekazywały stały kafelkowy `zoom=14`. `MovingMapRenderer.render()` wycinał crop o rozmiarze widgetu bezpośrednio w pikselach świata Web Mercator. Czterokrotnie większy crop 4K przy tej samej gęstości świata pokazywał prawie czterokrotnie większy obszar geograficzny.

Na klatce 30:

- Preview latitude span: `0.008658199757°`, longitude span: `0.014848709106°`,
- Export latitude span: `0.034582752093°`, longitude span: `0.059309005737°`,
- stosunek zakresu Export/Preview: `3.9942×` (różnica od 4× wynika z zaokrąglenia `173×4` vs `691`).

`fast_preview=True` wyłącza supersampling innych wskaźników, ale nie zmieniał zoomu ani cropu mapy.

Resolution-dependent calculation: **YES**.

Cache mismatch: **NO**.

## PARAMETRY RUNTIME PRZED POPRAWKĄ

Konfiguracja layoutu:

- `x=88.02%`, `y=22.31%` — pozycja środka widgetu,
- `width=height=size=18.0%` szerokości canvasu,
- map style: `satellite`,
- configured tile zoom: `14`,
- marker size: `9` logicznych pikseli.

| Parametr | Preview | 1920×1080 | Export 4K |
|---|---:|---:|---:|
| Canvas | 960×540 | 1920×1080 | 3840×2160 |
| Layout center x/y | 845 / 120 | 1690 / 241 | 3380 / 482 |
| Widget | 173×173 | 346×346 | 691×691 |
| Tile zoom | 14 | 14 | 14 |
| Grid dla klatki 30 | 1280×1280 | 1280×1280 | 1792×1792 |
| Crop dla klatki 30 | 570,638,173,173 | 484,552,346,346 | 567,635,691,691 |
| Canvas scale vs Preview | 1× | 2× | 4× |

## CACHE AUDIT

Przed poprawką cache obiektu renderer miał klucz:

`(id(gps_track), configured_zoom, map_style)`.

Nie zawierał jawnie wymiarów mapy/canvasu. Nie powodowało to jednak błędnego obrazu, ponieważ wewnętrzny grid cache ma klucz:

`(tx1, tx2, ty1, ty2, zoom, style, draw_track, track_color, track_width)`.

Wymiary viewportu wpływają na `tx1..ty2`; dokładny crop jest wykonywany osobno przy każdym wywołaniu. Preview i eksport mogły bezpiecznie współdzielić grid tylko wtedy, gdy potrzebowały tego samego zakresu kafelków. Dyskowy `TileCache` jest indeksowany przez zoom/x/y/style. Route i bounds są związane z tożsamością `gps_track`; map source wybiera ten track przed wywołaniem compositora.

Po poprawce cache renderer rozróżnia również efektywny zoom, więc Preview (`z14`) i 4K (`z16`) nie mogą omyłkowo współdzielić obiektu o innej gęstości świata.

## FIX

Dodano wyłącznie resolution-independent render plan dla `track_map`:

- zoom ustawiany w GUI opisuje viewport widziany na logicznym canvasie Preview `960 px`,
- 1920 używa efektywnego `zoom=15`,
- 3840 używa efektywnego `zoom=16`,
- crop jest najpierw kwantowany w logicznych pikselach (`173`), a następnie skalowany gęstością kafelków (`346`, `692`),
- gotowe `692×692` jest skalowane o jeden piksel do rzeczywistego widgetu 4K `691×691`,
- marker i grubość route są skalowane razem z gęstością kafelków,
- dla niepotęgowych skal canvasu pozostały ułamek obsługuje końcowy resize.

Nie zmieniono algorytmu route/marker, large cached-grid copy, crop-before-copy, map compositing ani GPU pipeline.

## PARAMETRY RUNTIME PO POPRAWCE

| Parametr | Preview | 1920×1080 | Export 4K |
|---|---:|---:|---:|
| Final widget | 173×173 | 346×346 | 691×691 |
| Logical viewport | 173×173 | 173×173 | 173×173 |
| Effective tile zoom | 14 | 15 | 16 |
| Map working image | 173×173 | 346×346 | 692×692 |
| Final resize scale | 1.0 | 1.0 | 691/692 |
| Grid, frame 30 | 1280×1280 | 1280×1280 | 1792×1792 |
| Crop, frame 30 | 570,638,173,173 | 373,509,346,346 | 491,507,692,692 |
| Marker source, frame 30 | 2313873 / 1340117 | 4627746 / 2680234 | 9255493 / 5360469 |
| Marker widget-local, frame 30 | 87 / 87 | 173 / 173 | 346 / 346 |

## AFTER FIX — BOUNDS I SYNCHRONIZACJA

Bounds podano jako `[min lat, max lat, min lon, max lon]`.

| Frame | Preview 960×540 | Export 3840×2160 | Wynik |
|---:|---|---|---|
| 30 | `[54.327185839924, 54.335844039680, 18.593845367432, 18.608694076538]` | `[54.327148300407, 54.335806508067, 18.593909740448, 18.608758449554]` | MATCH |
| 300 | `[54.327185839924, 54.335844039680, 18.593845367432, 18.608694076538]` | `[54.327148300407, 54.335806508067, 18.593909740448, 18.608758449554]` | MATCH |
| 900 | `[54.327085734470, 54.335743955301, 18.593416213989, 18.608264923096]` | `[54.327035681651, 54.335693913019, 18.593459129333, 18.608307838440]` | MATCH |

Pozostałe różnice środka/bounds są mniejsze niż jeden piksel logicznego Preview i wynikają z całkowitoliczbowej kwantyzacji współrzędnych kafelków. Longitude span jest zgodny do około `1×10⁻¹⁵°`; latitude span do `1.1×10⁻⁸°`.

- Frame 30 Preview vs Export: **MATCH**
- Frame 300 Preview vs Export: **MATCH**
- Frame 900 Preview vs Export: **MATCH**
- Geographic bounds: **MATCH**
- Marker position: **MATCH** (maks. odchylenie znormalizowane poniżej 0.003)
- Route: **MATCH** (maks. odchylenie współrzędnych znormalizowanych ≤ 1 px Preview)

Klatki 30 i 300 pokazują pierwszy punkt trasy, ponieważ rzeczywisty timestamp filmu zaczyna się 15 s przed pierwszą próbką FIT; obie ścieżki identycznie stosują istniejący clamp. Klatka 900 potwierdza parity dla poruszającego się markera.

## REAL FULL EXPORT I REGRESJA

Artefakt: `Raporty/AMD_ETAP5C_PRECHECK/full_gui_parity_1131.mp4`

- SHA-256 MP4: `e500111095c66d33415f58db7b93255cc050de8a134075c8581190571f78bcbe`
- video: HEVC Main, `3840×2160`, `yuv420p`, 1131 klatek,
- audio: AAC LC, 48 kHz stereo, 1768 ramek,
- duration: `37.738077 s`,
- decoded / HUD / VP / AMF submitted / AMF output / muxed: `1131/1131`,
- AMF dropped / ignored / INPUT_FULL: `0/0/0`,
- hardware decode, P010 direct decoder surface→VP i ETAP 3 GPU HUD pozostały aktywne,
- CPU base upload/readback: nadal `0`,
- audio elementary stream SHA-256 przed/po: identyczny `549c551024c0171d679cc8adb6ce35e6530291f75df485b51dfeee7a3e72ec55`.

Kontrola wizualna klatek 30/300/900:

- FIT: **PASS**
- GPMF: **PASS**
- pozostały HUD: **PASS**
- Date/time: **PASS**
- Color: **PASS**
- Audio: **PASS**
- black/green/magenta artifacts: **NONE**

Jedynym zmienionym modułem produkcyjnym jest ścieżka `track_map`. Pełny zestaw testów: `174 passed, 17 skipped`.

TRUE FPS tego correctness runu wyniósł `13.690`; nie jest to nowy baseline optymalizacyjny. Wyższa gęstość mapy ujawniła oczekiwany koszt renderowania/copy gridu (`compose_overlay AVG 49.692 ms`). Zgodnie z zakresem PRECHECK nie optymalizowano tego kosztu.

## ODPOWIEDZI WPROST

1. **Dlaczego Preview i Export miały inny zoom?** Finalny widget był około 4× większy w pikselach, ale zachowywał ten sam kafelkowy zoom 14; crop obejmował więc około 4× większy obszar geograficzny.
2. **Która ścieżka była błędna?** Finalny eksport 4K interpretował piksele renderowania jako logiczne piksele viewportu. Preview odpowiadało zoomowi ustawianemu przez użytkownika.
3. **Czy problem zależał od 1920 vs 3840?** Tak, ogólnie od rozdzielczości canvasu. Rzeczywiste Preview miało 960×540; test 1920×1080 vs 3840×2160 również potwierdził błąd i poprawkę.
4. **Czy cache uczestniczył w błędzie?** Nie. Cache mógł współdzielić poprawne kafelki/grid, lecz nie zmieniał cropu ani zoomu. Po poprawce klucz renderer cache jawnie rozróżnia efektywny zoom.
5. **Czy po poprawce mapy są zgodne?** Tak — bounds, marker i route odpowiadają sobie na klatkach 30/300/900.
6. **Czy można bezpiecznie rozpocząć właściwy ETAP 5C?** Tak. Correctness parity jest zamrożone i istnieją artefakty/runtime JSON do regresji.

## ARTEFAKTY

- `Raporty/AMD_ETAP5C_PRECHECK/map_parity_runtime.json` — pełne parametry Preview/1920/4K, crop, grid, marker i bounds,
- `Raporty/AMD_ETAP5C_PRECHECK/frame_*_960x540_map.png`, `frame_*_1920x1080_map.png`, `frame_*_3840x2160_map.png` — mapy dla klatek 30/300/900,
- `Raporty/AMD_ETAP5C_PRECHECK/final_frame_*_map_crop.png` — mapy wycięte z realnego finalnego MP4,
- `Raporty/AMD_ETAP5C_PRECHECK/full_gui_parity_1131.mp4.amd_profile.json` — frame accounting i pipeline validation,
- `Raporty/AMD_ETAP5C_PRECHECK/full_gui_parity_1131.log` — pełny log eksportu.
