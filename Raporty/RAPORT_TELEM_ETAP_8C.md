# TeleM — ETAP 8C — eliminacja pełnoklatkowego alpha scan `CPU_ABOVE_MAP`

## Result

**ETAP 8C zakończony.** Ścieżka `CPU_ABOVE_MAP` nie wykonuje już pełnoklatkowego skanu alpha. Wykorzystuje geometrię faktycznie wyrenderowanych elementów, skanuje tylko konserwatywny lokalny kandydat, a następnie wykonuje kompaktowy crop do uploadu.

## A. Root cause

Dotychczasowy kod wykonywał dla każdej klatki `3840 × 2160 = 8 294 400` pikseli przez `getchannel("A").getbbox()` na całym ABOVE canvas, po czym wykonywał crop do właściwego bbox. Pomiar ETAPU 8B potwierdził, że stary bucket `chart_upload` był w praktyce zdominowany przez `CPU_ABOVE_MAP`: mediana `above_bbox_crop` wynosiła około **10,811 ms**, a p95 około **19,073 ms**.

## B. Nowa architektura

```text
existing compositor bboxes
        ↓
rendered bbox union + conservative pad=64
        ↓
candidate crop
        ↓
local alpha getbbox()
        ↓
final compact crop
        ↓
existing native ABOVE_MAP upload/lifecycle
```

Nie zmieniono kolejności compositingu ani natywnego z-order. Wykorzystano istniejące bboxy kompozytora; dla custom text dodano brakujący wpis geometryczny do tego samego `_bboxes`.

## C. Implementacja

Zmodyfikowane pliki:

- `src/ffmpeg/amd_native_exporter.py` — `_rendered_bbox_union(...)`, `_tight_alpha_bbox_from_candidate(...)`, lokalny candidate crop i alpha scan dla ABOVE oraz profil `etap8c`.
- `src/indicators/compositor.py` — rzeczywisty bbox custom text trafia do istniejącego `_bboxes`.
- `tests/test_amd_native_above_dirty_bbox.py` — testy geometrii, cropu, alpha, przejść i custom text.

API uploadu natywnego pozostało bez zmian.

## D. Kontrakt bbox

- `None` oznacza brak renderowanych elementów i nie powoduje skanu pełnej klatki.
- bbox o zerowym rozmiarze jest ignorowany.
- union jest przycinany do granic klatki.
- pad `64 px` jest konserwatywnym marginesem dla renderowanych elementów.
- finalny bbox powstaje z alpha scan wyłącznie wewnątrz candidate crop.
- istniejąca geometria compositora jest zachowana dla elementów i custom text; nie wprowadzono nowej semantyki osi ani z-order.

## E. Poprawność cropu

Dodany pixel oracle porównuje nową ścieżkę z referencyjną ścieżką pełnoklatkową. Dla częściowej alpha, wielu elementów, brzegów klatki i pustego obszaru wynik finalnego cropu jest identyczny z referencją po odtworzeniu do pełnego canvasu.

## F. Walidacja dynamiczna i przypadki brzegowe

Testy obejmują visible → `None` → visible, zmianę pozycji i rozmiaru bbox, częściową alpha, element dotykający krawędzi klatki, wiele elementów i custom text. Istniejące testy ETAPU 7D dotyczące clear lifecycle, kolejności i native ordered-map również przechodzą.

## G. Eliminacja pełnoklatkowego skanu

| parametr | przed | po |
|---|---:|---:|
| alpha-scan pixels/frame | 8 294 400 | 106 210 |
| candidate bbox | pełna klatka | 559 × 190 |
| redukcja | — | **98,719%** |
| full-frame alpha scan | tak | **nie** |

W realnym materiale finalny bbox wynosił około `431 × 62` (`26 722` piksele). Upload pozostaje kompaktowy i nie został sztucznie zmniejszony kosztem poprawności.

Uwaga: nadal tworzony jest pełny obraz wynikowy przez istniejący `compose_overlay`. ETAP 8C eliminuje pełnoklatkowy alpha scan i pełnoklatkowy crop; eliminacja samej alokacji/clear pełnego canvasu jest osobnym kandydatem dla ETAPU 8D.

## H. Timing critical path

Pomiary mediany z trzech przebiegów po 900 klatek (`GX030120.MP4`, produkcyjny layout):

| etap | przed 8C | po 8C |
|---|---:|---:|
| `above_bbox_crop` | 10,716–11,066 ms | 0,243–0,252 ms |
| `above_bbox_crop` p95 | 18,943–19,127 ms | 0,793–1,087 ms |
| candidate pixels | 8 294 400 | 106 210 |
| upload bytes/frame | — | 106 888 B |

Średnie po 8C dla `above_bbox_crop` wynosiły około `0,346 ms`; mediana około `0,251 ms`. Kryterium celu `<3 ms median`, a także preferowane `<1 ms median`, zostało spełnione.

## I. 3 × 900 frames

| run | frames | output | FPS | dropped | full-frame input |
|---|---:|---:|---:|---:|---:|
| 8cfull1 | 900 | 900 | 28,073 | 0 | 0 |
| 8cfull2 | 900 | 900 | 28,349 | 0 | 0 |
| 8cfull3 | 900 | 900 | 27,786 | 0 | 0 |
| mediana | 900 | 900 | **28,073** | 0 | 0 |

Względem mediany przebiegów 8B (`26,764 FPS`) daje to około `+1,309 FPS` / `+4,9%`; jest to wynik end-to-end z naturalną wariancją środowiska. Przyczynowo zmierzona zmiana dotyczy wyłącznie ABOVE crop/scan.

## J. Poprawiony critical path

Po zmianie dominujący fragment ABOVE to:

```text
compose_overlay → candidate crop → local alpha scan → final crop → upload
```

Sam local alpha scan jest niewielki: około `0,09 ms` mediany w przebiegach realnych. Native map/gauge/composition nie zostały zmienione.

## K. 60 FPS gap i pozostały bottleneck

Przebiegi osiągnęły medianę około `28 FPS`, więc cel `60 FPS` nadal nie jest spełniony. Po usunięciu pełnoklatkowego alpha scan nie należy przypisywać pozostałej luki do tego konkretnego bottlenecku. Kolejne koszty znajdują się w szerszej ścieżce compose/native/export i wymagają osobnego audytu.

## L. Testy

Testy powiązane po implementacji:

```text
70 passed
```

Pełna suite:

```text
336 passed, 3 failed, 17 skipped
```

Trzy failure'y są tymi samymi, znanymi wcześniej i niezwiązanymi z ETAPEM 8C:

```text
tests/test_amd_native_etap4.py
tests/test_qp_analyzer.py
tests/test_render_tab.py
```

Nie dodano nowych niezwiązanych failure'ów.

## M. Regresja

Przechodzą testy dotyczące AMD ordered map, AMD clear order, GPU compositor, map sync, Telemetry source/None contract, chart history i STEP lookup. Nie zmieniono implementacji GPS9, SmartSync, ISOE, SHUT, TMPC ani map lifecycle. Native DLL została przebudowana w istniejącym build directory; kod native nie wymagał zmiany w ETAPIE 8C.

## N. Wydajność i cache

ETAP 8C nie zmienia cache telemetrycznego. Nie zwiększa rozmiaru cache ani nie wprowadza nowego formatu danych. Wpływ pomiarowy dotyczy CPU ABOVE path i liczby pikseli skanowanych lokalnie.

## O. Remaining issues

### CONFIRMED

- pełnoklatkowy alpha scan `CPU_ABOVE_MAP` usunięty;
- candidate/final bbox jest dynamiczny i clipped;
- pixel parity przechodzi;
- upload i native lifecycle pozostają aktywne;
- nie ma regresji w testach ordered map/clear.

### SUSPECTED / FOLLOW-UP

- pełny canvas `compose_overlay` nadal jest tworzony;
- end-to-end nadal jest poniżej 60 FPS;
- ewentualne dodatkowe koszty należy zmierzyć osobno po ustabilizowaniu pomiarów.

### OUT OF SCOPE

- GPU-native ABOVE rendering,
- eliminacja pełnoklatkowej alokacji/clear canvasu,
- zmiany z-order,
- chart upload redesign,
- zmiany renderera, kodera i pipeline'u AMD poza wymaganym pomiarem.

## P. Rekomendacja ETAPU 8D

Jeżeli optymalizacja ma być kontynuowana, następnym niezależnym krokiem powinien być audyt możliwości renderowania ABOVE bez tworzenia pełnoklatkowego CPU canvasu lub z region-aware composition. Nie wykonano tego w ETAPIE 8C.

**ETAP 8C — COMPLETE.**
