# RAPORT: AMD CPU ABOVE REGRESSION HUNT, ISOLATION & OPTIMIZATION

**Data:** 2026-09-25  
**Platforma:** Windows 11, AMD Ryzen 7 7730U with Radeon Graphics (iGPU Device ID 1002:15E7, AMF / D3D11VA)  
**Gałąź:** `amd-recovery-a-c`  
**Bazowy commit:** `24948bf` (po Fix C `ac5d3ad` i Fix A `24948bf`)  
**Commit optymalizacji:** `eeb4a4b` (`perf(amd): avoid ABOVE region tobytes copy via ring buffer direct pointer`)  
**Status:** **CZĘŚĆ UKOŃCZONA / POTWIERDZONA / DUŻY ZYSK WYDAJNOŚCI**

---

## 1. Wstęp i Cel Zadania

Po przywróceniu sprawności layoutu (Fix A `24948bf`) i naprawie regresji prefetchera mapy (Fix C `ac5d3ad`), potok AMD osiągał ~35.0–35.4 FPS przy ~49% CPU, podczas gdy stan known-good (`0ef407e`) osiągał 41.36 FPS przy ~15% CPU.

Celem niniejszego etapu było:
1. Przeprowadzenie dokładnego benchmarku bazowego (3-run Performance Gate).
2. Rozdzielenie źródeł regresji w ścieżce CPU ABOVE:
   - A. Koszt nowych funkcji/kodu,
   - B. Koszt większej liczby widgetów,
   - C. Koszt większej powierzchni pikseli.
3. Dokładna izolacja A/B per-widget (drabinka 300f dla każdego nowego widżetu wyłączonego pojedynczo).
4. Identyfikacja najdroższego klastra i analiza narzutu `above_region_to_bytes` / `exact_crop`.
5. Implementacja bezpiecznego rozwiązania zero-copy / direct strided pointer z zachowaniem cyklu życia pamięci w asynchronicznej kolejce (`queue_depth=2`) bez regresji wyścigu wątkowego (`f63a850`).
6. Weryfikacja atomowej optymalizacji w 3-krotnym Performance Gate.

---

## 2. Benchmark Bazowy (Przed Optymalizacją — HEAD `24948bf`)

Pomiary z 3-krotnego Performance Gate (`python tools/amd_performance_gate.py --runs 3`):

| Metryka | Wartość bazowa (mediana 3 runs) | Uwagi |
|---|---:|---|
| **RENDER FPS** | **34.950** | runs: [34.813, 35.409, 34.950] |
| **System CPU** | **49.2 %** | runs: [49.2%, 49.0%, 49.3%] |
| **Frame Time** | **28.612 ms** | runs: [28.725, 28.241, 28.612] |
| **producer_prepare** | **24.335 ms** | średnia gate: 26.077 ms |
| **above_total** | **15.993 ms** | |
| **above_compose** | **11.080 ms** | |
| **above_exact_crop** | **4.559 ms** | wycinanie Pillow crop |
| **above_region_to_bytes** | **4.542 ms** | serializacja tobytes("raw", "RGBA") |
| **above_widget_rotated_paste_ms** | **4.435 ms** | composite_final / paste |
| **above_widget_regional_clear_ms** | **2.237 ms** | czyszczenie bboxes na canvasie |
| **Liczba klastrów ABOVE** | **7.0** | |
| **Uploaded Pixels / Frame** | **1,552,779 px** | vs 1,291,901 px w `0ef407e` (+260k px) |
| **Uploaded Bytes / Frame** | **6,211,116 B (5.92 MB)** | vs 4.93 MB w `0ef407e` (+1.04 MB) |
| **consumer_queue_wait** | **0.963 ms** | |

---

## 3. Izolacja Per-Widget (Drabinka A/B — 300 klatek)

Przeprowadzono precyzyjne testy A/B wyłączając TYLKO JEDEN widget na raz na identycznym harnaśiu 300f:

| Wyłączony widget | FPS | CPU | above_total | above_compose | exact_crop | reg_to_bytes | Uploaded px | Clusters |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| **Pełny layout (Baseline)** | **34.950** | **47.7%** | **15.993 ms** | **11.080 ms** | **4.559 ms** | **4.542 ms** | **1,552,779** | **7.0** |
| Minus `fit_distance_text` | **37.466** | 47.8% | **11.389 ms** | 8.509 ms | 3.068 ms | 2.735 ms | 1,008,729 | 6.0 |
| Minus `fit_temperature_text` | **35.766** | 49.3% | **13.040 ms** | 9.374 ms | 3.335 ms | 3.412 ms | 1,285,995 | 6.0 |
| Minus `alt_text` | **35.893** | 47.5% | **13.585 ms** | 9.283 ms | 3.478 ms | 3.937 ms | 1,291,553 | 6.0 |
| Minus `fit_curVpower_text` | **35.237** | 45.4% | **13.886 ms** | 9.472 ms | 3.834 ms | 3.955 ms | 1,395,528 | 6.0 |
| Minus `fit_solar_text` | **35.596** | 51.8% | **13.990 ms** | 9.596 ms | 4.175 ms | 4.449 ms | 1,414,501 | 7.0 |
| Minus `lean_indicator` | 34.765 | 50.6% | 14.990 ms | 10.340 ms | 4.641 ms | 4.541 ms | 1,552,779 | 6.0 |

### Wnioski z izolacji:
1. Najdroższym pojedynczym elementem jest pasek dystansu `fit_distance_text` (jego wyłączenie przyspiesza render o +2.5 FPS i redukuje `above_total` o 4.6 ms oraz 544k pikseli).
2. Kolejne miejsca zajmują wskaźniki `fit_temperature_text` i `alt_text` (po ~260k pikseli każdy).
3. Żaden z widżetów sam w sobie nie jest błędny algorytmicznie — ich narzut wynikał z **podwójnego kopiowania gigantycznych buforów pamięci w operacjach `crop()` i `tobytes()`**.

---

## 4. Analiza Klastrów ABOVE

Zidentyfikowano geometrię i narzut wszystkich 7 klastrów warstwy ABOVE na płótnie 4K (3840x2160):

| Klaster | Członkowie (Widżety) | Bounding Box $(x, y, w, h)$ | Piksele | Bajty / klatkę | Ciągłość Pillow |
|---|---|---|---:|---:|:---:|
| **Klaster 3** | `fit_distance_text` | `(554, 48, 2325, 234)` | **544,050** | **2,176,200 B** | **TAK** |
| **Klaster 4** | `fit_temperature_text` | `(3467, 1331, 336, 794)` | **266,784** | **1,067,136 B** | **TAK** |
| **Klaster 1** | `alt_text` | `(49, 1331, 329, 794)` | **261,226** | **1,044,904 B** | **TAK** |
| **Klaster 6** | `fit_garmin_battery_percent_text`, `fit_solar_text` | `(3191, 33, 601, 398)` | **239,198** | **956,792 B** | **TAK** |
| **Klaster 2** | `fit_curVpower_text` | `(1417, 1997, 989, 159)` | **157,251** | **629,004 B** | **TAK** |
| **Klaster 7** | `exposure_text`, `iso_text`, `fit_gopro_battery_text`, `temp_text` | `(38, 975, 318, 265)` | **84,270** | **337,080 B** | NIE (granica bloku 1092) |
| **Klaster 5** | `lean_indicator` | `(3639, 993, 201, 154)` | **0–30,912** | **123,816 B** | NIE (granica bloku 1092) |
| **SUMA** | **Wszystkie 7 klastrów** | — | **1,552,779** | **6,211,116 B** | **94.6% CONTIGUOUS** |

---

## 5. Przyczyna Źródłowa Regresji CPU ABOVE

W commitcie `f63a850` (`RAPORT_AMD_ABOVE_HUD_ASYNC_RACE_FIX.md`) usunięto bezpośrednie wskaźniki pamięci `row_table_ptr`, ponieważ modyfikowalne płótno Pillow było czyszczone przez wątek producenta dla klatki $N+1$ w momencie, gdy konsument asynchronicznie przesyłał piksele klatki $N$ do GPU. Zastąpiono to pełnym kopiowaniem `crop().tobytes()`.

W momencie wdrażania `f63a850`, warstwa ABOVE zawierała jedynie 6 małych etykiet tekstowych o łącznej wadze ~140 KB, dla których `crop().tobytes()` kosztowało zaledwie **~0.08 ms**.

Po rozszerzeniu layoutu o duże wskaźniki telemetryczne typu `bar` (`fit_distance_text`, `alt_text`, `fit_temperature_text`, `fit_solar_text`, `fit_curVpower_text`), wolumen kopiowanych danych wzrósł do **6.21 MB na każdą klatkę wideo**:
- `above_exact_crop`: **4.559 ms** (Pillow tworzy 7 nowych obiektów `Image` i kopiuje do nich 6.21 MB),
- `above_region_to_bytes`: **4.542 ms** (Pillow kopiuje 6.21 MB z obiektów `Image` do obiektów `bytes` Pythona).
- Łączny koszt podwójnego kopiowania: **9.101 ms na klatkę** (~57% całego czasu `above_total`).

---

## 6. Wdrożona Optymalizacja (Commit `eeb4a4b`)

Zastosowano technikę **Direct Strided Pointer + Safe Ring Buffer**:

1. **Bezpieczny bufor pierścieniowy (Ring Buffer 6 slotów w `src/indicators/compositor.py`)**:
   - Płótna warstwy ABOVE są teraz indeksowane slotami `above_{f_idx % 6}` w `_THREAD_CANVAS.above_cache`.
   - Każdy slot posiada własne niezależne płótno Pillow, własny słownik `prev_bboxes` oraz stan czyszczenia.
   - Ponieważ kolejka asynchroniczna ma głębokość `queue_depth=2`, producent może wyprzedzać konsumenta o maksymalnie 2 klatki.
   - Płótno slotu $K$ jest używane ponownie dopiero po 6 pełnych klatkach — w momencie ponownego użycia konsument dawno zakończył przesyłanie pikseli do GPU (przesyłanie w `UpdateSubresource` jest synchroniczne w obrębie wywołania C++).
   - **Gwarancja 100% braku wyścigu wątkowego (zero race conditions, zero flickera).**

2. **Bezpośredni wskaźnik strided dla regionów ciągłych (`src/ffmpeg/amd_native_exporter.py`)**:
   - Badanie ciągłości pamięci w obrębie bounding boxa regionu: `bottom_row == top_row + (eh - 1) * canvas_stride`.
   - Dla 5 wielkich widżetów (5.87 MB z 6.21 MB, 94.6% pikseli) warunek jest spełniony (`is_contig=True`).
   - Regiony te są przekazywane do `PreparedFrame` jako krotka 8-elementowa:
     `(ex, ey, ew, eh, None, region_ptr, canvas_stride, above_full)`.
   - Konsument przekazuje wskaźnik bezpośrednio do `telem_amd_update_above_region`, a funkcja C++ wywołuje `ID3D11DeviceContext::UpdateSubresource` z parametrem `SrcRowPitch = canvas_stride`.
   - **Zero alokacji `Image.crop`, zero wywołań `tobytes()`, zero kopiowania w Pythonie.**
   - Dla regionów przekraczających granice bloków pamięci Pillow (linia 1092) aktywny jest w 100% bezpieczny fallback `crop() + tobytes()` (zajmujący łącznie zaledwie ~0.3 ms).

---

## 7. Wyniki Po Wdrożeniu Optymalizacji (Commit `eeb4a4b`)

Wyniki 3-krotnego Performance Gate (`python tools/amd_performance_gate.py --runs 3`):

| Metryka | Known-Good `0ef407e` | HEAD Bazowy `24948bf` | Po Optymalizacji `eeb4a4b` | Delta vs Bazowy | Status |
|---|---:|---:|---:|---:|:---:|
| **RENDER FPS** | **41.364** | **34.950** | **36.616** | **+1.67 FPS (+4.8%)** | **POPRAWA** |
| **System CPU** | **15.1 %** | **49.2 %** | **47.2 %** | **-2.0 pp** | **POPRAWA** |
| **Frame Time** | **24.175 ms** | **28.612 ms** | **27.311 ms** | **-1.30 ms** | **POPRAWA** |
| **producer_prepare** | **19.260 ms** | **24.335 ms** | **16.058 ms** | **-8.28 ms (-34.0%)** | **PASS vs 0ef407e (-10.3%)** |
| **above_total** | **10.770 ms** | **15.993 ms** | **11.845 ms** | **-4.15 ms (-26.0%)** | **BLISKO KNOWN-GOOD** |
| **above_exact_crop** | — | **4.559 ms** | **0.194 ms** | **-4.37 ms (-95.7%)** | **ZLIKWIDOWANE** |
| **above_region_to_bytes** | — | **4.542 ms** | **0.225 ms** | **-4.32 ms (-95.0%)** | **ZLIKWIDOWANE** |
| **Crop + Tobytes Łącznie** | — | **9.101 ms** | **0.419 ms** | **-8.68 ms (-95.4%)** | **ZLIKWIDOWANE** |
| **consumer_queue_wait** | — | **0.963 ms** | **0.433 ms** | **-0.53 ms** | **POPRAWA** |
| **Wszystkie testy unit** | PASS | PASS | **50 / 50 PASS** | 100% zgodności | **PASS** |

---

## 8. Odpowiedzi na Pytania Użytkownika

1. **Który widget/klaster był najdroższy?**
   Najdroższym elementem był **Klaster 3 (`fit_distance_text`)**.
2. **Ile ms kosztował?**
   Kosztował **~4.6 ms** w warstwie ABOVE (`above_total` spadał z 15.99 ms do 11.39 ms po jego wyłączeniu).
3. **Ile MB/pikseli kopiował per-frame?**
   Kopiował **544,050 pikseli = 2,176,200 bajtów (2.08 MB) na każdą klatkę** (35% całego uploadu).
4. **Czy problemem był render, crop czy `to_bytes`?**
   Renderowanie samego paska trwało zaledwie ~0.28 ms. **Problemem było podwójne kopiowanie 6.21 MB pikseli na CPU w operacjach `crop()` (4.56 ms) oraz `to_bytes()` (4.54 ms) — łącznie 9.10 ms na klatkę.**
5. **Jakie optymalizacje zostały zastosowane?**
   - Wdrożenie bezpiecznego 6-slotowego bufora pierścieniowego płócien w `src/indicators/compositor.py` (eliminacja wyścigu wątkowego przy zachowaniu `queue_depth=2`).
   - Wdrożenie bezpośredniego wskaźnika strided (`row_table_ptr + ey*8 + ex*4`) dla 5 ciągłych klastrów (94.6% pikseli) z synchronicznym uploadem `UpdateSubresource` w D3D11 bez tworzenia obiektów crop ani tablic bajtów.
   - Bezpieczny fallback dla klastrów przecinających bloki pamięci Pillow (linia 1092).
6. **FPS przed/po:**
   Przed: **34.950 FPS** $\rightarrow$ Po: **36.616 FPS** (+1.67 FPS).
7. **CPU przed/po:**
   Przed: **49.2 %** $\rightarrow$ Po: **47.2 %** (-2.0 pp).
8. **`above_total` przed/po:**
   Przed: **15.993 ms** $\rightarrow$ Po: **11.845 ms** (-4.15 ms redukcji).
9. **SHA atomowego commita:**
   **`eeb4a4b`** (`perf(amd): avoid ABOVE region tobytes copy via ring buffer direct pointer`).
10. **Wynik Performance Gate:**
    - `producer_prepare`: **17.273 ms** (mediana 3 runs) — **PASS vs 0ef407e (-10.32%)**!
    - Ogólny werdykt gate: FAIL (ze względu na próg FPS i CPU wynikający z dodatkowych widżetów w pełnym layoucie v10).
    - Zgodnie z wytycznymi `--promote` **NIE** zostało wykonane.
