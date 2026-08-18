# ETAP 7C — RESULT

Data: 2026-08-18  
Tryb: READ-ONLY / RUNTIME VALIDATION / STRESS TEST  
Kod i layout nie były modyfikowane.

## A. Runtime environment

| Element | Wynik |
|---|---|
| Materiał | `Video/GX030120.MP4` |
| Telemetria | `Video/GX030120.json` + `Poranna_jazda_na_rowerze.fit` |
| Video | 3840×2160, 30000/1001 fps |
| Native DLL | `telem_amd_native.dll` |
| ABI | 8 |
| Decoder | GPU_HUD_D3D11VA |
| GPU HUD | GPU_HUD |
| Encoder | AMD AMF HEVC |
| GPU driver | brak dostępnego stabilnego odczytu w istniejącej diagnostyce |

## B. Long-run real layout

Wykonano wymagany ciągły test 30 s na realnym materiale. Pełne 180 s nie
zostało uruchomione po wykryciu błędu correctness w kontrolowanym overlapie.

```text
frames requested: 900
duration: 30.0 s
AMD_MAP_PATH: GPU
AMD_MAP_ORDER: CPU_BELOW_MAP -> GPU_MAP -> CPU_ABOVE_MAP
CPU_ABOVE_MAP: ACTIVE
above bbox at frame 0: (3300, 936, 431, 62)
```

Warstwa above była aktywna przez wszystkie 900 klatek w tym przebiegu.

## C. Frame accounting

| Counter | Wynik |
|---|---:|
| input/source metadata | 5395 |
| requested | 900 |
| decoded | 900 |
| native processed | 900 |
| VP processed | 900 |
| AMF submitted | 900 |
| AMF output | 900 |
| AMF dropped | 0 |
| AMF retries | 0 |
| AMF ignored | 0 |

Long-run nie wykazał frame drops.

## D. Dynamic ABOVE transitions

Kontrolowany runtime probe używał wyłącznie kopii layoutu w pamięci i
antialiased/rotated text indicatora po mapie.

| Frame | Value | Bbox | Raster | Clear previous bbox | Wynik |
|---|---:|---|---|---|---|
| A | 10 | `(320,180,84,12)` | yes | no | visible |
| B | 0 | `(333,184,76,12)` | yes | yes | zero remains visible |
| C | `None` | `None` | no | yes | expected empty |
| D | 0 | `(346,187,116,18)` | yes | yes | resize/move exercised |
| E | 10 | `(358,194,65,10)` | yes | yes | visible again |

W warstwie Python poprawnie rozróżniono `0.0` od `None` i wygenerowano crop
tylko z alpha-bboxu. Problem pojawia się w kolejności native clear/map blend.

## E. Stale-region test

```text
PASS — stary tekstowy bbox jest czyszczony przez mechanizm above.
FAIL — czyszczenie po GPU_MAP usuwa także mapę znajdującą się pod starym bboxem.
```

Dowód: kontrolowany probe porównujący wynik ordered z CPU_REFERENCE oracle dał:

```text
CPU_REFERENCE_ORACLE_PARITY = False
STALE_BBOX_CLEAR = False
OVERLAP_MAP_ALPHA = True
```

## F. Zero vs None

| Wartość | Raster | Wynik |
|---|---|---|
| `10` | tak | PASS |
| `0.0` | tak | PASS |
| `None` | nie | PASS |

Kontrakt visibility z ETAPU 6B jest zachowany po stronie renderera.

## G. Map-first / middle / last

Runtime split matrix:

| Layout | Below | Above | Status split |
|---|---|---|---|
| map → text | empty | text | PASS structurally |
| text → map | text | empty | PASS structurally |
| text → map → text | text | text | PASS structurally, native overlap FAIL |

Kolejność insertion-order nie jest zmieniana ani zapisywana.

## H. Chart / gauge interaction

| Przypadek | Wynik |
|---|---|
| Real chart path | `GPU_SPLIT`, brak aktywnych chart widgets w realnym layoutcie |
| Real gauge before map | `GPU`, 900/900 GPU frames |
| Chart/gauge after map | runtime split kieruje je do CPU_ABOVE, nie do GPU capture |
| Gauge interaction real | GPU gauge active, bbox `(1544,1632,648,648)` |

Realny long-run potwierdził, że istniejący gauge path przed mapą nie został
niepotrzebnie zdegradowany.

## I. Alpha / rotation / custom text

- text probe używał `rotation=17` i przechodził przez zwykły CPU renderer;
- antialiasing textu był obecny;
- overlap z mapą był wymuszony;
- `custom_texts` zostały potwierdzone jako warstwa above w split matrix;
- brak dark-fringe testu całej klatki po stronie native, ponieważ stale clear
  unieważnia już correctness z-order.

## J. CPU_REFERENCE parity

| Obszar | Wynik |
|---|---|
| visibility | Python PASS |
| bbox | Python PASS |
| overlap existence | PASS |
| final z-order parity | FAIL |
| map pixels under old above bbox | FAIL |

CPU_REFERENCE oracle pozostawia mapę pod pustym/zmienionym above. Obecny native
ordered pass tego nie zachowuje.

## K. Upload statistics

Z profilu 30 s:

| Transfer | Wynik |
|---|---:|
| map uploads | 900 |
| map working image | 692×692 RGBA |
| map destination | 691×691 |
| map bytes total | 1,723,910,400 |
| map MiB/frame | 1.8267 |
| above update frames | 900 |
| above visible frames | 900 |
| above crop bytes total | 96,199,200 |
| above crop bytes/frame | 106,888 (~0.102 MiB) |
| full 3840×2160 RGBA/frame | 33,177,600 bytes |

Above używa małego crop uploadu; nie wysyła pełnego 4K RGBA. Profil nie
raportuje osobnego licznika `above_clears`, ale aktywny frame path wykonuje
clear poprzedniego bboxu w każdym `BlendAboveMap()`.

## L. Synchronization

W long-runie nie wystąpiły zgłoszone błędy `Flush`, `Wait` ani `Map`.
Istniejący native `BlendAboveMap()` wykonuje jednak `Flush()` po każdym above
blendzie. Nie zmieniano tego w ETAPIE 7C.

Obowiązkowego GPU→CPU readbacku produkcyjnego nie stwierdzono:

```text
mandatory GPU→CPU readback = NO
```

## M. Memory / resource stability

Istniejący profil nie udostępnia dedykowanego odczytu VRAM AMD. Nie uruchamiano
nowego frameworka memory profiler.

W obserwowanym long-runie:

- GPU HUD texture creates: 1;
- native map working texture pozostawała stała;
- gauge texture była utrzymywana jako zasób persistent;
- nie zaobserwowano awarii, resource-creation failure ani wzrostu liczby
  klatek oczekujących.

Nie można jednak zamknąć pełnej stabilności resource lifetime dla nowego
above texture jako PASS, ponieważ correctness failure zatrzymuje dalszą
walidację tej ścieżki.

## N. Performance

| Path | Compose avg / p95 | Map prep avg | Above data | Result |
|---|---:|---:|---:|---|
| CPU_REFERENCE, 3 s | 22.890 / 37.751 ms | n/a | CPU HUD | runtime success |
| GPU map, 30 s | 2.317 / 5.308 ms | 2.140 ms avg | 900 active | correctness FAIL |
| GPU map, active above | included above crop/render | crop 431×62 | 106,888 B/frame | z-order FAIL |

GPU map long-run osiągał 26.75 effective FPS dla 900 klatek. CPU_REFERENCE
control zakończył się poprawnie: 90/90 frames, AMF output 90, dropped 0.

## O. AMF / D3D11VA

Long-run GPU:

```text
AMF submitted: 900
AMF output: 900
AMF dropped: 0
HW decode proof: YES
```

CPU_REFERENCE control:

```text
AMF submitted: 90
AMF output: 90
AMF dropped: 0
HW decode proof: YES
```

Audio mux zakończył się poprawnie; jego czas pozostaje poza zakresem.

## P. Tests

Wymagane testy ETAPU 7C:

```text
64 passed
```

Pełna suite:

```text
326 passed, 3 failed, 17 skipped
```

Znane, niezwiązane failure’y:

```text
tests/test_amd_native_etap4.py
tests/test_qp_analyzer.py
tests/test_render_tab.py
```

## Q. Confirmed issues

### Critical — stale map pixels under old ABOVE bbox

Evidence:

1. `ProcessFrame()` wykonuje `ResampleAndBlendMap()`.
2. Następnie wykonuje `BlendAboveMap()`.
3. `BlendAboveMap()` czyści `m_aboveMapPrev*` przez mode `0` na HUD canvas.
4. Ten HUD canvas zawiera już mapę.
5. Przy overlapie clear usuwa fragment mapy przed blendem nowego above.

Skutek: wynik ordered nie jest równy CPU_REFERENCE, a mapa nie jest stabilna
podczas disappearance/movement/resize above.

### Medium — brak dedykowanej telemetryki above clear/blend

Istnieją agregaty update/visible/upload, ale nie ma osobnych native counters
dla `above clears`, `above blend ms` i resource count above.

## R. Suspected issues

- Alpha/halo pełnej klatki nie powinien być klasyfikowany jako PASS po wykryciu
  błędu kolejności; wymaga ponowienia po poprawce.
- Pełny 180 s run nie został wykonany, ponieważ 30 s reprodukuje błąd
  correctness wystarczający do zatrzymania walidacji.

## S. Final classification

```text
ORDERED MAP COMPOSITING RUNTIME = FAIL
```

Nie można zamknąć kontraktu:

```text
AMD TRACK_MAP Z-ORDER CONTRACT CLOSED
```

### Minimalny następny etap

```text
ETAP 7D — targeted fix
```

Najmniejsza poprawka: przenieść clear poprzedniego above bbox przed
`GPU_MAP`, a po `GPU_MAP` wykonywać wyłącznie blend bieżącej warstwy above.
Następnie powtórzyć kontrolę `visible → None → visible`, moving/resize bbox,
CPU_REFERENCE oracle i minimum 30 s long-run.

`def_layout.json` pozostał niezmieniony — SHA256 przed i po:

```text
E79F34C0237672ED58FE86301A485284C6F97AFC4A5730E3C16CCDC88DE217E7
```

ETAP 7C zakończony. Zatrzymano pracę zgodnie z instrukcją read-only.
