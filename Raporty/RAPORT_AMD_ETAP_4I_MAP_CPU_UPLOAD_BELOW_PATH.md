# AMD ETAP 4I — MAP CPU UPLOAD / BELOW PATH ELIMINATION

## Data raportu
2026-08-27

## Gałąź
`amd-render`

## Commit bazowy
`2db0004`

---

## Zadanie

Dokładnie sprofilować i możliwie wyeliminować CPU koszt:
- `map_cpu_upload` (cel podstawowy <= 1.5 ms, pref <= 1.0 ms, stretch <= 0.5 ms)
- `PIL/buffer preparation` (dirty rect crop + tobytes dla BELOW canvas)

Zasada nadrzędna: **PARITY FIRST (MaxDiff = 0, DifferentPixels = 0)**.

---

## Stan początkowy (ETAP 4H baseline)

Pełny profil 1131 klatek z ETAP 4H:

```
RENDER FPS:           32.581
producer_prepare:     20.708 ms AVG
map_cpu_upload:        6.144 ms AVG (Med 3.802, P95 22.676)
  render_map_inner:    4.688 ms AVG (Med 2.019)
  map_bytes tobytes:   1.454 ms AVG (Med 1.636)
above_total:          12.058 ms AVG
PIL/buffer prep:      ~1.45 ms (crop + tobytes per dirty rect)
```

Mapa: 978x978 RGBA = 1.82 MB/klatke, 3.30 GB/1131 klatek.

---

## Analiza i podejście

### 4I.1 - Dynamika unikalności mapy

Analiza 1131 klatek (scratch/analyze_map_dynamics_1131f.py):
- Unikalne unrotated map hashe: 585 (51.72%)
- Kolejne identyczne klatki: 546/1131 (48.28%)

GPU Track-Up obrót wykonywany jest przez `telem_amd_set_map_heading()` po stronie C++. Map raster upload można pominąć gdy raster identyczny z poprzednią klatką. Jednak właściwa detekcja identyczności wymaga porównania bajtów (kosztowne) lub klucza crop/grid.

Test `test_crop_box_equality.py` (1131 klatek):
```
False skips (CRITICAL ERROR if >0): 0
True skips verified: 12 frames (1.06%)
```

Klucz `_last_crop_key` nie jest wystarczająco precyzyjny (534 mismatchy). W praktyce skip upload nie jest bezpieczny bez droższego hash porównania. Skip upload pominięto jako ryzykowne / zysk 1%.

### 4I.2 - Direct strided pointer dla map upload

Pillow ImagingObject zawiera `row_table` (offset 40 / 0x28 w PyCapsule data). Gdy obraz jest ciagly w pamieci (weryfikacja: top_row + (mh-1)*stride == bottom_row), można przekazac surowy pointer do `telem_amd_update_map()` eliminujac `map_img.tobytes("raw", "RGBA")` (~1.45 ms).

`telem_amd_update_map.argtypes[1]` zmienione z `ctypes.c_char_p` na `c_void_p`.

Fallback do `tobytes()` gdy niespelnione.

### 4I.3 - Direct memmove dla below HUD dirty rects

Zamiast `composed_img.crop(rx, ry, rx+rw, ry+rh)` + `slice_img.tobytes()` (producer) + `np.frombuffer` + `np.copyto` (consumer):

Producer: wyciaga surowy pointer `top_row + rx*4` z canvas row_table.
Consumer: row-by-row `ctypes.memmove(dst_base + r*c_stride, src_ptr + r*c_stride, rw*4)`.

Tuple format len=8: `(rx, ry, rw, rh, None, src_ptr_int, canvas_stride, composed_img)`.

---

## Zmienione pliki

### `src/ffmpeg/amd_native_exporter.py`
- Linia ~2078: `telem_amd_update_map.argtypes[1]` zmienione na `c_void_p`
- Linie 4019-4053 (`_prepare_frame_cpu` — map section):
  - Zunifikowanie sciezki `gpu_map_rotate=True/False` (usuniecie duplikacji)
  - Wyciaganie `map_row_table_ptr` z `map_img.im.ptr` (PyCapsule offset 40)
  - Weryfikacja ciaglosci; pack `map_data = (None, mw, mh, map_dst, top_row, stride, map_img)` gdy contig, fallback `tobytes()` gdy nie
- Linie 4121-4150 (`_prepare_frame_cpu` — below dirty rects):
  - Wyciaganie `canvas_row_table_ptr` z `composed_img.im.ptr`
  - Dla kazdego dirty rect: weryfikacja ciaglosci, pack `(rx, ry, rw, rh, None, src_ptr, canvas_stride, composed_img)` gdy contig
  - Fallback do `crop + tobytes` gdy nie
- Linie 4505-4520 (`_consumer_thread` — map upload):
  - Rozpoznanie tuple len=7 (direct pointer) vs 4 (bytes)
  - `telem_amd_update_map(h_context, m_ptr, mw, mh, m_stride, ...)`
- Linie 4546-4562 (`_consumer_thread` — below HUD dirty rects):
  - Rozpoznanie tuple len=8 (memmove) vs 5 (np.copyto)
  - Row-by-row `ctypes.memmove` z direct pointer

### `src/moving_map.py`
- Linia ~643: Dodanie `self._last_crop_key` (grid_key, x1, y1, draw_track, draw_marker, marker_state) — uzywany przez testy diagnostyczne.

---

## Testy

### Golden Parity
```
tests/test_golden_parity_etap4.py: 4 passed
  MaxDiff = 0
  DifferentPixels = 0
```

### Full suite (165 testow)
```
165 passed, 0 failed, 0 errors
```

Uruchomione testy: test_bar_orientation_contract, test_slope_rendering, test_static_indicator_cache,
test_etap10t2_segment_gui_hardening, test_etap10t_segment_bar_map_visuals, test_pixel_indicator_style,
test_bar_ruler_opt_parity_etap3b, test_text_indicator_opt_etap3c, test_distance_optimization,
test_golden_parity_etap4, test_gauge_rendering, test_lean_tight_rotation, test_lean_gpu_bridge.

---

## Benchmark E2E (3x1131 klatek, GX030120/def_layout/4K)

| Metryka | 4H baseline | Run 1 | Run 2 | Run 3 | Median 4I | Delta |
|---------|-------------|-------|-------|-------|-----------|-------|
| RENDER FPS | 32.581 | 35.864 | 35.984 | 35.482 | **35.864** | +3.283 (+10.1%) |
| map_cpu_upload AVG | 6.144 ms | 1.456 ms | 1.438 ms | 1.429 ms | **1.438 ms** | -4.706 ms (-76.6%) |
| PIL/buffer prep AVG | ~1.45 ms | 0.085 ms | 0.084 ms | 0.083 ms | **0.084 ms** | -1.366 ms (-94.1%) |
| producer_prepare AVG | 20.708 ms | 16.986 ms | 16.635 ms | 16.301 ms | **16.635 ms** | -4.073 ms (-19.7%) |
| above_total AVG | 12.058 ms | 11.143 ms | 10.720 ms | 10.618 ms | **10.720 ms** | -1.338 ms (-11.1%) |

### Warunki akceptacji map_cpu_upload:
- Cel <= 1.5 ms: OSIAGNIETY (1.438 ms median) PASS
- Cel pref <= 1.0 ms: NOT ACHIEVED (render_map_inner sam kosztuje ~1.4 ms)
- Cel stretch <= 0.5 ms: NOT ACHIEVED

### Warunki akceptacji RENDER FPS:
- Cel >= 35 FPS: OSIAGNIETY (35.864 median) PASS
- Cel pref >= 36 FPS: NOT ACHIEVED (max 35.984)

---

## Diagnostyka skip-upload

Test `crop_box equality` 1131 klatek:
- False skips = 0
- True skips = 12/1131 (1.06%)
Skip upload nie wdrozony — zysk 1%, ryzyko nieakceptowalne.

---

## Izolacja backendow

- Zmiany wylacznie w `AMD_NATIVE_D3D11` sciezkach
- NVIDIA/NVENC/CUDA: brak zmian
- Intel/QSV: brak zmian
- `src/moving_map.py`: dodanie `_last_crop_key` (atrybut diagnostyczny, brak wplywu na rendering)

---

## Ryzyka

1. **PyCapsule offset 40**: offset `row_table` w `ImagingObject` jest wewnetrzny do Pillow. Zweryfikowany na Pillow 11.x / Python 3.14.7. Fallback do `tobytes()` aktywny gdy pointer nieprawidlowy lub obraz nieciagly.
2. **Memmove safety**: `composed_img` musi przezyc do konca consumer upload — gwarantowane przez tuple reference na `composed_img`.
3. **Contig check**: Weryfikacja `bottom_row == top_row + (mh-1)*stride` zabezpiecza przed nieciagla geometria.

---

## PASS / FAIL

```
TASK:         AMD ETAP 4I - MAP CPU UPLOAD / BELOW PATH ELIMINATION
STATUS:       PASS

CHANGED:      src/ffmpeg/amd_native_exporter.py, src/moving_map.py
TESTED:       Golden Parity MaxDiff=0 DifferentPixels=0 | 165/165 tests | 3x1131f E2E benchmark
NOT TESTED:   Skip-map-upload (zdecydowano nie wdrazac - 1% zysk)
PERFORMANCE:  RENDER FPS 32.581->35.864 (+10.1%) | map_cpu_upload 6.144->1.438 ms (-76.6%) | cel <=1.5ms PASS
RISKS:        PyCapsule offset staly dla Pillow 11.x; fallback aktywny

REPORT:       Raporty/RAPORT_AMD_ETAP_4I_MAP_CPU_UPLOAD_BELOW_PATH.md
```
