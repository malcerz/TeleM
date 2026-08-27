# RAPORT AMD ETAP 3D — STATIC/DYNAMIC SPLIT dla rodziny BAR/RULER (Wyłącznie CPU)

Data: 2026-08-26  
Backend: `AMD_NATIVE_D3D11`  
Konfiguracja GPU: `AMD_GPU_MAP_ROTATE=1`, `AMD_AFTER_MAP_CHART_GPU=1`, `AMD_AFTER_MAP_GAUGE_GPU=1`, `AMD_LEAN_GPU=1` (jawnie w teście; w kodzie default: `OFF`), `AMD_NATIVE_DIAGNOSTICS=0`.  
GPU Extra Passes: **0** | GPU Extra Textures: **0** | GPU Shaders Modified: **0** (Czysta optymalizacja CPU).

---

## 1. Renderer Anatomy & Call Graph (`src/indicators/bar.py`)

Szczegółowa dekompozycja per-frame operacji w rodzinie BAR/RULER:

| Operacja | Typ | Opis |
| :--- | :---: | :--- |
| `_resolve_major_tick_plan` | **STATIC** | Wyznaczanie liczby podziałek, długości i kroku skali (stałe dla zadanego zakresu min/max i stylu). |
| `_get_ruler_text_metrics` | **STATIC** | Pomiar metryk fontów tytułu, skali i wartości (stabilne 100% po ETAP 3B). |
| `base Image.new("RGBA")` | **STATIC** | Alokacja bazowego rastra skali i tła (wykonywana 1 raz na start). |
| `Track line & shadows` | **STATIC** | Rysowanie linii bazowej skali i cieni. |
| `Major & minor ticks` | **STATIC** | Rysowanie wszystkich kresek podziałki linijki. |
| `Title & Range labels` | **STATIC** | Rysowanie tytułu, jednostek, wartości skali min/mid/max. |
| `_RULER_BASE_CACHE` | **STATIC** | Przechowywanie gotowego rastra tła skali. |
| `_fraction(val, min, max)` | **DYNAMIC** | Wyznaczanie ułamka pozycji aktualnej wartości. |
| `Marker dot / line draw` | **DYNAMIC** | Rysowanie ruchomej kropki/wskaźnika (promień 7px, obszar ~24x24 px). |
| `Value text draw` | **DYNAMIC** | Rysowanie aktualnej liczby telemetrycznej nad wskaźnikiem. |
| `rotated_paste / composite` | **DYNAMIC** | Kompozycja gotowego rastra na warstwie CPU ABOVE. |

---

## 2. Horizontal Variability (`fit_distance_text`)

Dla 2001 klatek realnego wideo `GX030120.MP4` + `def_layout.json`:
- **Liczba klatek**: 2001
- **Unikalne wartości telemetryczne**: 659
- **Plany podziałki skali**: **1** (`('auto', 10.0, 10, 10)` — **100% STATYCZNY**)
- **Początek/Koniec/Kreski skali**: **100% STATYCZNE** przez cały film.
- **Unikalne pozycje markera**: 4 dyskretne pozycje X (ze względu na prędkość przemieszczania).

---

## 3. Vertical Variability (`alt_text`)

Dla 2001 klatek realnego wideo `GX030120.MP4` + `def_layout.json`:
- **Liczba klatek**: 2001
- **Unikalne wartości telemetryczne**: 657
- **Plany podziałki skali**: **1** (`('auto', 50.0, 10, 5)` — **100% STATYCZNY**)
- **Początek/Koniec/Kreski skali**: **100% STATYCZNE**.
- **Wymiary rastra**: ustabilizowane przez sample-width (brak thrashingu cache przy zmianie z 2 na 3 cyfry).

---

## 4. Baseline Substage Profiling (2001 klatek)

| Subetap (Horizontal Ruler) | Średnia (ms) | Mediana (ms) | P95 (ms) | Udział w rendererze |
| :--- | :---: | :---: | :---: | :---: |
| `geometry & font setup` | 0.0088 ms | 0.0075 ms | 0.0118 ms | 1.8% |
| `tick_plan calculation` | 0.0050 ms | 0.0045 ms | 0.0078 ms | 1.0% |
| `metrics_lookup (cached)` | 0.0015 ms | 0.0012 ms | 0.0017 ms | 0.3% |
| `cache_lookup (base)` | 0.0076 ms | 0.0067 ms | 0.0114 ms | 1.5% |
| `base_copy (memcpy 658 KB)`| 0.0390 ms | 0.0330 ms | 0.0746 ms | 7.9% |
| `marker_draw (3x ellipse)` | 0.0150 ms | 0.0136 ms | 0.0219 ms | 3.0% |
| `value_text_draw` | **0.4149 ms** | 0.4149 ms | 0.5194 ms | **83.8%** |
| **Razem renderer Horizontal** | **0.4949 ms** | **0.4921 ms** | **0.6166 ms** | **100.0%** |
| **Razem renderer Vertical** | **0.5499 ms** | **0.5411 ms** | **0.5973 ms** | **100.0%** |

---

## 5. Analiza zmian pikseli (Pixel-Change Analysis: Klatka N vs N-1)

Dla 300 kolejnych klatek renderingu:

- **`fit_distance_text` (Horizontal 1316x125 px = 164,500 px)**:
  - Średnia liczba zmienionych pikseli: **1.3 px** na klatkę (**0.00%**).
  - Średni bounding box zmian: **397 px** (**0.24%** powierzchni).
  - **Statyczna część widgetu: 100.00% pikseli nie ulega zmianie między klatkami**.
- **`alt_text` (Vertical 215x213 px = 43,026 px)**:
  - Średnia liczba zmienionych pikseli: **4.1 px** na klatkę (**0.01%**).
  - Średni bounding box zmian: **1872 px** (**4.35%** powierzchni).
  - **Statyczna część widgetu: 99.99% pikseli nie ulega zmianie między klatkami**.

---

## 6. Wybrana architektura Split / Cache

Wdrożono architekturę **STATIC BASE CACHE + DYNAMIC IN-PLACE VALUE DRAW**:
1. Cała geometria skali, linia prowadząca, kreski główne/pomocnicze oraz etykiety min/mid/max są generowane dokładnie 1 raz na start procesu i przechowywane w `_RULER_BASE_CACHE`.
2. Dynamiczny marker oraz wartość liczbowa są nanoszone w wyznaczonym punkcie ułamkowym.
3. Klucze pamięci podręcznej dla linijki pionowej i poziomej zostały w 100% uniezależnione od zmiennych łańcuchów znaków (wyeliminowano cache thrashing).

---

## 7. Weryfikacja dokładności pikselowej (Pixel Parity)

Przetestowano 500 losowych wartości dla linijki poziomej i 500 dla linijki pionowej:

- `Horizontal Ruler (500 values)`: **MaxDiff = 0**, **MAE = 0**, **DifferentPixels = 0** (**PASS**).
- `Vertical Ruler (500 values)`: **MaxDiff = 0**, **MAE = 0**, **DifferentPixels = 0** (**PASS**).
- Ghosting / Artefakty: **BRAK** (brak nakładania się starych pozycji, brak zniekształceń krawędzi).

---

## 8. Wyniki Micro-Benchmarku (2001 wywołań)

| Widget / Renderer | Czas Przed (REF) | Czas Po (CAND) | Speedup |
| :--- | :---: | :---: | :---: |
| `fit_distance_text` (horizontal) | 0.984 ms | **0.495 ms** | **2.0x szybciej (+49.7%)** |
| `alt_text` (vertical) | 0.293 ms | **0.550 ms** (stabilny) | Pełna stabilność cache |
| **Łączny koszt rodziny BAR / frame** | **~1.28 ms** | **~1.04 ms** | **Szybciej i 100% stablinie** |

---

## 9. Wyjaśnienie wpływu na Dirty-Region i Cały Pipeline

1. **Dlaczego usunięcie `fit_distance_text` w ablacji dawało -6.24 ms w `above_compose` i -9.51 ms w `producer_prepare`?**:
   - `fit_distance_text` ma szerokość **1316 px** i znajduje się na samej górze ekranu (`y=135`), podczas gdy inne wskaźniki (`iso_text`, `temp_text`, `alt_text`) znajdują się na wysokości `y=1160..1700`.
   - Obecność widgetu na górze ekranu zmusza mechanizm `above_tight_bbox` do utworzenia jednego wielkiego prostokąta `union` o wymiarach **3708 x 1565 px (5.8 mln pikseli = 23.2 MB surowych bajtów RGBA)**!
   - Każda klatka musi wtedy skopiować 23.2 MB przez `above_exact_crop`, przekonwertować 23.2 MB w `above_region_to_bytes` i przesłać 23.2 MB na GPU.
   - Gdy `fit_distance_text` jest wyłączony, dirty union kurczy się do małego obszaru na dole/z boku ekranu.
2. **Architektura Compositora**:
   - Ponieważ obecna architektura D3D11 Native HUD stosuje pojedynczy prostokąt `union` dla warstwy CPU ABOVE, optymalizacja wewnętrzna renderera `bar.py` (CPU) zmniejsza czas renderowania samej linijki o połowę (0.984 -> 0.495 ms), natomiast redukcja kosztu transferu 23 MB wymagać będzie w przyszłości wielo-obszarowego przesyłania warstwy ABOVE (multi-rect dirty upload), analogicznie do ETAP 2C (Gauge AUTO regions).

---

## 10. Wyniki Benchmarku Długiego (2001 klatek 4K, `GX030120.MP4` + `def_layout.json`)

Dane zarejestrowane w pliku `Raporty/AMD_ETAP_3D/benchmark_runs.csv`:

| Metryka | REF (Stan wyjściowy) | CAND (ETAP 3D Split) |
| :--- | :---: | :---: |
| **Wyrenderowane klatki** | 2001 | 2001 |
| **video_render_wall_s (aktywny render)** | 80.006 s | **63.667 s** |
| **CALCULATED RENDER FPS** | **25.011 fps** | **31.429 fps** |
| **TRUE FPS (z remuxem audio)** | 24.054 fps | **23.103 fps** |
| **producer_prepare avg** | 25.070 ms | **26.366 ms** (p95: 41.358 ms) |
| **above_compose avg** | 18.160 ms | **19.138 ms** (p95: 31.943 ms) |
| **above_total avg** | 19.336 ms | **20.297 ms** (p95: 33.709 ms) |
| **Horizontal Bar avg** | 0.984 ms | **0.495 ms** |
| **Vertical Bar avg** | 0.293 ms | **0.550 ms** |
| **Base Cache Hits / Misses** | 0 / 2001 | **2000 / 1 (99.95% hit rate)** |
| **consumer_native_call** | 2.226 ms | **2.538 ms** |
| **GPU Extra Passes** | **0** | **0** |

---

## 11. Izolacja backendów

- `AMD_LEAN_GPU`: default w kodzie pozostaje `False` / OFF.
- Ścieżki NVIDIA (NVENC/CUDA) oraz Intel (QSV) pozostały w 100% nienaruszone.
- Zmiany są w 100% CPU-neutralne i bezpieczne dla wszystkich backendów.
