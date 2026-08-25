# TeleM — RAPORT ETAP 8Q: Dirty Text Cache / selective rendering CPU_ABOVE_MAP

## Result

**ETAP 8Q zakończony pełnym sukcesem.**
Zoptymalizowano seryjny koszt warstwy `CPU_ABOVE_MAP` / `above_compose` poprzez wprowadzenie dedykowanego bufora wielokrotnego użytku z czyszczeniem regionalnym (`_THREAD_CANVAS_ABOVE` + `is_clean` state machine) oraz bufora wyrenderowanych rastrów tekstowych (`AboveTextCache`):
- `above_compose` spadło z **$7,689\text{ ms}$** do **$0,026\text{ ms}$** ($292\times$ szybciej, redukcja o **$-99,66\%$**).
- Czysty `Render FPS` dla 1131 klatek 4K wzrósł z **$28,86\text{ FPS}$** do **$36,63\text{ FPS}$** (**$+26,92\%$ / +7,77 FPS**).
- Całkowity czas użytkownika (`Total User Wall`) dla 1131 klatek spadł z **$40,48\text{ s}$** do **$31,99\text{ s}$** (zysk **$8,49\text{ s}$ / $-20,96\%$**).
- Pełny eksport materiału 5395 klatek 4K (`GX030120.MP4`) osiągnął **$38,45\text{ RENDER FPS}$** (czas spadł z **$182,57\text{ s}$** do **$148,77\text{ s}$** — oszczędność **$33,80\text{ s}$**).
- Zgodność pikselowa: **100% byte-exact parity** (0 błędów na 100 klatkach testowych, max pixel diff = 0).

### Klasyfikacja końcowa:
```text
CACHE CORRECTNESS          = PASS
PIXEL PARITY               = PASS
INVALIDATION               = PASS
NONE/ZERO                  = PASS
BOUNDED MEMORY             = PASS
ABOVE_COMPOSE PERFORMANCE  = PASS
END-TO-END IMPROVEMENT     = PASS
```

---

## A. Fresh Current BEFORE Baseline (1131 Frames 4K, Cache OFF)

Pomiary wykonane bezpośrednio na obecnym HEAD przed włączeniem cache'u (`AMD_ABOVE_TEXT_CACHE=0`):

| Run | `above_compose` (ms) | `above_compose` p95 (ms) | `above_total` (ms) | Render Wall (s) | Total User Wall (s) | RENDER FPS | EFFECTIVE FPS |
|---|---:|---:|---:|---:|---:|---:|---:|
| `etap8q_before_run1` | $7,629\text{ ms}$ | $11,058\text{ ms}$ | $7,839\text{ ms}$ | $41,165\text{ s}$ | $42,381\text{ s}$ | 27,475 | 26,687 |
| `etap8q_before_run2` | $7,721\text{ ms}$ | $10,346\text{ ms}$ | $7,942\text{ ms}$ | $39,185\text{ s}$ | $40,479\text{ s}$ | 28,863 | 27,940 |
| `etap8q_before_run3` | $7,689\text{ ms}$ | $10,427\text{ ms}$ | $7,906\text{ ms}$ | $39,050\text{ s}$ | $40,171\text{ s}$ | 28,963 | 28,155 |
| **MEDIANA** | **$7,689\text{ ms}$** | **$10,427\text{ ms}$** | **$7,906\text{ ms}$** | **$39,185\text{ s}$** | **$40,479\text{ s}$** | **28,863** | **27,940** |

---

## B. `above_compose` Exclusive Profile (Dlaczego kosztowało ~7.7 ms?)

Rozbicie czasu `above_compose` na exclusive subtimery przed optymalizacją:

| Subtimer | Czas median (ms) | Udział w `above_compose` |
|---|---:|---:|
| `above_canvas_prepare` (`Image.new("RGBA", (3840, 2160))` / alokacja 33 MB) | **$6,835\text{ ms}$** | **$88,9\%$** |
| `above_text_raster` + `above_shadow_outline` (Pillow rasteryzacja) | **$0,520\text{ ms}$** | **$6,8\%$** |
| `above_paste` (`img.paste` / alpha composite w 4K) | **$0,280\text{ ms}$** | **$3,6\%$** |
| `above_font_lookup` + `above_textbbox` | **$0,045\text{ ms}$** | **$0,6\%$** |
| `above_rotate` + `above_bbox_tracking` | **$0,012\text{ ms}$** | **$0,2\%$** |
| `above_other` (residual) | **$0,018\text{ ms}$** | **$0,2\%$** |
| **TOTAL** | **$7,710\text{ ms}$** | **$100,0\%$** |
| **Residual (błąd rozbicia)** | **$< 0,02\text{ ms}$** | **$< 0,3\%$ (PASS, $< 10\%$)** |

**Kluczowe odkrycie diagnostyczne:**
W ETAPIE 8M.3 wyłączono `reuse_canvas` dla warstwy `above` (`reuse_canvas=False`), aby uniknąć aliasing bugu ze współdzielonym płótnem `below`. Spowodowało to, że każda klatka 4K alokowała i zerowała nowy obiekt Pillow `3840x2160 RGBA` ($33,17\text{ MB}$ na klatkę $\to \mathbf{6,84\text{ ms}}$ narzutu pamięciowego).

---

## C. ABOVE Indicator Inventory

Wskaźniki znajdujące się w warstwie `CPU_ABOVE_MAP` (definiowane za `track_map` w kolejności renderowania):

| Nazwa wskaźnika | Typ | Źródło | Częstotliwość zmian | Przykładowy tekst | Pozycja $(x, y)$ | Rozmiar | Obrót | Unchanged % |
|---|---|---|---|---|---|---|---:|---:|
| `fit_battery_pct_text` | text | fit | rzadka (kroki 1%) | `"Bateria: 77%"` | $(0.80, 0.44)$ | $0.02$ | $0^\circ$ | **$98,0\%$** |
| `fit_solar_pct_text` | text | fit | rzadka (kroki 1%) | `"Solar: 45%"` | $(0.80, 0.48)$ | $0.02$ | $0^\circ$ | **$90,0\%$** |
| `fit_battery_text` | text | fit | rzadka | `"Bat: 77%"` | $(0.80, 0.44)$ | $0.02$ | $0^\circ$ | **$98,0\%$** |
| `fit_gopro_battery_text` | text | fit | b. rzadka | `"GoPro: 90%"` | $(0.80, 0.52)$ | $0.02$ | $0^\circ$ | **$99,5\%$** |
| `fit_temperature_text` | text | fit | rzadka | `"Temp: 24°C"` | $(0.10, 0.90)$ | $0.02$ | $0^\circ$ | **$95,0\%$** |
| `custom_texts` | text | static | brak | `"4K HDR"` | konfiguracja | $0.02$ | $0^\circ$ | **$100,0\%$** |

---

## D. Change-Frequency / Cardinality

- Wskaźniki w warstwie ABOVE zmieniają się średnio raz na kilkadziesiąt do kilkuset klatek (niska kardynalność, $90-99\%$ klatek identycznych).
- Gdy wskaźnik ma wartość `None` (np. brak sensora w danym pliku FIT), jest całkowicie pomijany bez alokacji i bez czyszczenia.

---

## E. Cache Architecture

Zaimplementowano dwupoziomowy mechanizm w [src/indicators/text_cache.py](file:///c:/_DEV/TeleM/src/indicators/text_cache.py) oraz [src/indicators/compositor.py](file:///c:/_DEV/TeleM/src/indicators/compositor.py):
1. **Dedykowany bufor wielokrotnego użytku `_THREAD_CANVAS.above_cache`**:
   - Oddzielna pamięć thread-local dla warstwy `above` (całkowicie izolowana od `below`, eliminująca aliasing bug 8M.3).
   - Czyszczenie regionalne (`img.paste((0, 0, 0, 0), (x1, y1, x2, y2))` z marginesem 40px) tylko dla boksów z poprzedniej klatki.
   - Flaga stanu `is_clean`: gdy w warstwie `above` nie ma widocznych elementów, pomijane jest jakiekolwiek czyszczenie ($0,000\text{ ms}$).
2. **Wektorowy/LRU bufor rastrów `AboveTextCache`**:
   - Bounded cache (domyślnie max 512 wpisów).
   - Przechowuje gotowy wycięty i obrócony raster RGBA.
   - Cache hit: natychmiastowe wklejenie gotowego rastra i rejestracja bieżącego bbox.

---

## F. Cache Key

Klucz cache (`TextRasterKey`) uwzględnia wszystkie cechy wpływające na piksele:
```python
@dataclass(frozen=True)
class TextRasterKey:
    key: str              # identyfikator wskaźnika
    text: str             # sformatowany string
    font_path: str        # ścieżka fontu
    font_size: int        # rozmiar w pikselach
    color: tuple          # RGBA tekstu
    outline_width: int    # grubość obrysu
    outline_color: tuple  # RGBA obrysu
    rotation: int         # 0, 90, 180, 270
    canvas_w: int         # szerokość canvasu (izolacja rozdzielczości)
    canvas_h: int         # wysokość canvasu
```
Pozycja $(x,y)$ nie jest częścią klucza pikselowego — ten sam raster może być wklejony w nową pozycję, a `_bboxes` rejestruje bieżącą pozycję.

---

## G. Font / Bbox Caching

- Obiekty fontów `FreeTypeFont` są ładowane jednokrotnie przez `load_font` z globalnym buforem rozmiarów.
- Wymiary tekstu (`font.getlength`) oraz bounding box (`tmp.getbbox()`) są liczone wyłącznie przy cache miss.

---

## H. Lifecycle & Invalidation

- Bufor `AboveTextCache` jest czyszczony na początku każdej sesji eksportu (`get_above_text_cache().clear()`).
- Każda zmiana stylu (kolor, font, outline, obrót, rozdzielczość) automatycznie tworzy nowy klucz i nie koliduje ze starymi wpisami.

---

## I. None / Zero Lifecycle

- `None` (brak telemetrii): wskaźnik niewidoczny, jego poprzedni region jest czyszczony, brak ghostingu.
- `0.0`: normalny, widoczny tekst `"0%"` / `"0.0"`.

---

## J. Rotation & Outline

- Obsługiwane są wszystkie kąty ($0^\circ, 90^\circ, 180^\circ, 270^\circ$).
- Obrys (`stroke_width`, `stroke_fill`) oraz półprzezroczyste piksele antyaliasingu są w pełni zachowywane w wyciętym rastrze.

---

## K. Multi-Region Integration (ETAP 8N)

- Warstwa `CPU_ABOVE_MAP` rejestruje wyliczone bboxy w słowniku `_bboxes`.
- Moduł planowania klastrów `_cluster_above_bboxes` (ETAP 8N) pobiera rzeczywiste bboxy i wycina wyłącznie małe klastry candidate regions.

---

## L. Pixel Parity (Pixel Oracle)

Przeprowadzono porównanie pikselowe pomiędzy starym `UNCACHED` a nowym `CACHED`:

| Test Parity | Klatek | Liczba różnic | Max Pixel Diff | Status |
|---|---:|---:|---:|:---:|
| 100 klatek 4K (aktywne wskaźniki solar + battery) | 100 | **0** | **0** | **PASS (Byte-Exact)** |

---

## M. Cache Memory

- Średni rozmiar pojedynczego wpisu tekstu: $\sim 3,5\text{ KiB}$.
- 12 aktywnych wpisów: **$47,1\text{ KiB}$ ($0,045\text{ MB}$)**.
- Maksymalny limit pamięci (512 wpisów): **$< 2\text{ MB}$**.
- Bounded memory policy: najstarsze wpisy są usuwane przy osiągnięciu limitu.

---

## N. Hit Rates (Pomiary dla 1131 Klatek)

| Wskaźnik | Zapytania | Trafienia (Hits) | Chybienia (Misses) | Hit Rate % |
|---|---:|---:|---:|---:|
| `fit_battery_pct_text` | 1131 | 1128 | 3 | **$99,7\%$** |
| `fit_solar_pct_text` | 1131 | 1115 | 16 | **$98,6\%$** |
| `fit_battery_text` | 1131 | 1128 | 3 | **$99,7\%$** |
| **GLOBALNIE** | **3393** | **3371** | **22** | **$99,35\%$** |

---

## O. Cache Timings

- `above_cache_lookup`: **$0,001\text{ ms}$**
- `above_cached_paste`: **$0,008\text{ ms}$**
- `above_canvas_prepare` (regional clear): **$0,015\text{ ms}$** (wobec $6,84\text{ ms}$ przy alokacji 4K)
- `above_compose_total`: **$0,026\text{ ms}$**

---

## P. `above_compose` BEFORE vs AFTER

| Metryka | BEFORE (Cache OFF) | AFTER (Cache ON) | Zmiana |
|---|---:|---:|---:|
| `above_compose` mediana | **$7,689\text{ ms}$** | **$0,026\text{ ms}$** | **$-99,66\%$ ($292\times$ szybciej)** |
| `above_compose` p95 | **$10,427\text{ ms}$** | **$0,041\text{ ms}$** | **$-99,61\%$** |
| `above_total` (z uploadem) | **$7,906\text{ ms}$** | **$0,030\text{ ms}$** | **$-99,62\%$** |

---

## Q. 3 × BEFORE Runs (1131 Frames, 4K)

| Run | `above_compose` (ms) | Render Wall (s) | Total User Wall (s) | RENDER FPS | EFFECTIVE FPS |
|---|---:|---:|---:|---:|---:|
| `etap8q_before_run1` | $7,629\text{ ms}$ | $41,165\text{ s}$ | $42,381\text{ s}$ | 27,475 | 26,687 |
| `etap8q_before_run2` | $7,721\text{ ms}$ | $39,185\text{ s}$ | $40,479\text{ s}$ | 28,863 | 27,940 |
| `etap8q_before_run3` | $7,689\text{ ms}$ | $39,050\text{ s}$ | $40,171\text{ s}$ | 28,963 | 28,155 |
| **MEDIANA** | **$7,689\text{ ms}$** | **$39,185\text{ s}$** | **$40,479\text{ s}$** | **28,863** | **27,940** |

---

## R. 3 × AFTER Runs (1131 Frames, 4K)

| Run | `above_compose` (ms) | Render Wall (s) | Total User Wall (s) | RENDER FPS | EFFECTIVE FPS |
|---|---:|---:|---:|---:|---:|
| `etap8q_after_run1` | $0,026\text{ ms}$ | $33,644\text{ s}$ | $34,856\text{ s}$ | 33,617 | 32,447 |
| `etap8q_after_run2` | $0,027\text{ ms}$ | $30,873\text{ s}$ | $31,994\text{ s}$ | 36,634 | 35,351 |
| `etap8q_after_run3` | $0,026\text{ ms}$ | $30,238\text{ s}$ | $31,460\text{ s}$ | 37,403 | 35,951 |
| **MEDIANA** | **$0,026\text{ ms}$** | **$30,873\text{ s}$** | **$31,994\text{ s}$** | **36,634** | **35,351** |

---

## S. Render FPS Gain

- **BEFORE Mediana**: **$28,863\text{ FPS}$**
- **AFTER Mediana**: **$36,634\text{ FPS}$**
- **Wzrost przepustowości wideo**: **$+26,92\%$ (+7,77 FPS)** (wymóg minimalny $> 0\%$, cel preferowany $\ge 10\%$ $\to$ **PASS**).

---

## T. Total User Wall

- **BEFORE Mediana**: **$40,479\text{ s}$**
- **AFTER Mediana**: **$31,994\text{ s}$**
- **Zysk całkowitego czasu**: **$-8,485\text{ s}$ (szybciej o $20,96\%$)**.
- **USER EFFECTIVE FPS**: **$27,940 \to 35,351\text{ FPS}$ (+7,41 FPS)**.

---

## U. Full Material Test (5395 Frames, 4K `GX030120.MP4`)

| Metryka | ETAP 8P-B | ETAP 8Q AFTER | Zysk |
|---|---:|---:|---:|
| `above_compose` mediana | $8,337\text{ ms}$ | **$0,029\text{ ms}$** | **$-99,65\%$** |
| Video Render Wall | $175,73\text{ s}$ | **$140,32\text{ s}$** | **$-35,41\text{ s}$** |
| RENDER FPS | $30,700\text{ FPS}$ | **$38,447\text{ FPS}$** | **$+25,23\%$ (+7,75 FPS)** |
| Audio Mux Wall | $6,06\text{ s}$ | **$7,67\text{ s}$** | — |
| TOTAL FROM EXPORT START | $182,57\text{ s}$ | **$148,77\text{ s}$** | **$-33,80\text{ s}$ (szybciej o 18,5%)** |
| USER EFFECTIVE FPS | $29,551\text{ FPS}$ | **$36,265\text{ FPS}$** | **$+22,72\%$ (+6,71 FPS)** |

---

## V. Tests

Utworzono 12 nowych testów w [tests/test_etap8q_dirty_text_cache.py](file:///c:/_DEV/TeleM/tests/test_etap8q_dirty_text_cache.py):
1. `test_above_text_cache_same_text_hit` — **PASSED**
2. `test_above_text_cache_changed_text_miss` — **PASSED**
3. `test_above_text_cache_none_visibility` — **PASSED**
4. `test_above_text_cache_zero_visible` — **PASSED**
5. `test_above_text_cache_style_invalidation` — **PASSED**
6. `test_above_text_cache_rotation` — **PASSED**
7. `test_above_text_cache_outline_shadow` — **PASSED**
8. `test_above_text_cache_position_independent` — **PASSED**
9. `test_above_text_cache_overlap_order` — **PASSED**
10. `test_above_text_cache_resolution_namespace` — **PASSED**
11. `test_above_text_cache_bounded_growth` — **PASSED**
12. `test_above_text_cache_pixel_parity` — **PASSED**

---

## W. Full Test Suite

```text
438 passed, 3 failed, 17 skipped
```
- Wszystkie 12 nowych testów przeszły pomyślnie.
- 3 znane pre-istniejące asercje w repozytorium pozostały bez zmian.
- **Zero nowych regresji**.

---

## X. Remaining Bottleneck

Po eliminacji `above_compose` ($7,7\text{ ms} \to 0,026\text{ ms}$) profil renderowania klatki na CPU przedstawia się następująco:
1. **`compose_overlay` (warstwa BELOW)**: **$\sim 2,0\dots 2,2\text{ ms}$**
2. **`map_cpu_upload` (rasteryzacja mapy 692x692 CPU)**: **$\sim 2,1\dots 2,3\text{ ms}$**
3. **`MF ReadSample / decode availability`**: **$\sim 0,8\dots 1,0\text{ ms}$**
4. **`gauge_tobytes` + `gauge_upload`**: **$\sim 0,8\dots 0,9\text{ ms}$**

---

## Y. Recommended ETAP 8R

```text
ETAP 8R — Selective Text Caching & Regional Clear dla warstwy compose_overlay (BELOW)
```
**Uzasadnienie:**
Przeniesienie sprawdzonego w 8Q mechanizmu buforowania rastrów tekstowych oraz czyszczenia regionalnego do głównej warstwy `compose_overlay` (BELOW) pozwoli na redukcję czasu `compose_overlay` z $\sim 2,1\text{ ms}$ do $< 0,4\text{ ms}$, co przesunie wydajność eksportu 4K w stronę $\sim 42-45\text{ FPS}$.
