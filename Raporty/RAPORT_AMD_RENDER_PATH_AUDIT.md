# RAPORT: Audyt ścieżki renderingu AMD (D3D11 + AMF) — pełna diagnostyka

**Data pomiaru:** 2026-08-24
**Typ zadania:** `AUDIT ONLY / DIAGNOSTICS` (bez zmian produkcyjnych poza minimalną, wyłączaną instrumentacją)
**Maszyna:** AMD Ryzen 5 5500U + Radeon iGPU (gfx90c, pamięć współdzielona APU), Windows 11
**Preset:** `presets/cycling_dashboard_v10.json`
**Materiał:** `Video/GX010115.MP4` (HEVC Main10 4K, 17760 klatek, obrót 180°, audio 592.6 s) + `GX010115.json` + `Jazda_na_rowerze_w_porze_lunchu.fit` (offset +2.000 s)
**Backend:** `AMD_NATIVE_D3D11` — MF D3D11VA decode → D3D11 VideoProcessor → GPU compositor (compute NV12) → AMF HEVC → mux

**Konfiguracja produkcyjna benchmarku (domyślna):**
`AMD_MAP_PATH=GPU`, `AMD_CHART_PATH=GPU_SPLIT`, `AMD_GAUGE_PATH=GPU`, `AMD_TELEMETRY_MODE=PRECOMPUTED`, `AMD_NATIVE_HUD_MODE=GPU_HUD`, `AMD_NATIVE_DECODE_MODE=GPU_HUD_D3D11VA`, `AMD_NATIVE_HUD_UPLOAD_MODE=DIRTY`, `AMD_ABOVE_DIRTY_MODE=EXACT`, `AMD_ABOVE_UPLOAD_BUFFER_MODE=DIRECT`, `AMD_CPU_GPU_PIPELINE=SYNC`, `AMD_NATIVE_PROFILING=1`.

---

# 1. Aktualna architektura pipeline AMD

Pętla produkcyjna to **producer–consumer (SYNC)** wewnątrz `export_amd_native_d3d11` (`src/ffmpeg/amd_native_exporter.py`). Producer (CPU) przygotowuje overlay per-klatkę, consumer (CPU→GPU/natywny) dekoduje, wgrywa HUD i wywołuje `telem_amd_process_frame`.

## Krok po kroku dla jednej klatki (tryb produkcyjny)

| # | Etap | Miejsce | CPU/GPU | Ile razy/klatkę |
|---|---|---|---|---|
| 1 | **Telemetry lookup** | `_prepare_frame_cpu` → `telemetry_cache.lookup(idx)` (PRECOMPUTED) | CPU | 1 |
| 2 | **Compose BELOW-map** (time_display, distance, battery, solar) | `compose_overlay(layout=compose_layout, reuse_canvas="below")` | CPU (Pillow) | 1 |
| 3 | **Compose ABOVE-map** (compass, slope, iso, shutter, temp, alt, vpower, charts, speed gauge) | `compose_overlay(layout=map_above_layout, reuse_canvas="above")` | CPU (Pillow) | 1 |
| 4 | **Ekstrakcja dirty regionów ABOVE** (EXACT tight-bbox → crop → `tobytes`) | `_extract_exact_above_regions` | CPU | 1 |
| 5 | **Charts static/dynamic tile + Gauge + Map working image** | `render_map_working_image` (692×692) + chart/gauge capture → `tobytes` | CPU | 1 |
| 6 | **HUD dirty rects BELOW** (bbox → crop → `tobytes` → `np.copyto` do persistent backing) | `_dirty_rects_from_bboxes` + konsumer | CPU | 1 |
| 7 | **Decode** (MF `ReadSample` → powierzchnia DXGI `P010`) | natywnie `telem_amd_read_video_sample` | GPU | 1 |
| 8 | **Uploady CPU→GPU**: chart tiles, gauge, above regions, map, HUD regions | ctypes → `telem_amd_update_*` | CPU→GPU | 1–8 (recty) |
| 9 | **VideoProcessor** P010→NV12 + compositing HUD/map (z-order: base→normalize→clear-above→blend-charts→blend-gauge→blend-map→HUD NV12) | `telem_amd_process_frame` → `D3D11VideoProcessorPipeline::ProcessFrame` | GPU | 1 |
| 10 | **AMF encode** (SubmitTexture→QueryPacket→zapis h265) | `telem_amd_process_frame` / `d3d11_amf_encoder.cpp` | GPU | 1 |
| 11 | **Flush + remux** (audio copy) | `telem_amd_flush` + subprocess `ffmpeg -c:v copy -c:a copy` | CPU | 1/eksport |

> **Kluczowa obserwacja:** ramka bazowa wideo **pozostaje GPU-resident** (`direct_decoder_surface_to_vp_frames = 90`, `decoder_gpu_copy_frames = 0`). Nie występuje round-trip `GPU→CPU→GPU` dla ramki wideo. Cały HUD/overlay jest renderowany na CPU i wgrywany do GPU jako RGBA.

---

# 2. Diagram przepływu klatki (stan faktyczny, bez zmian)

```text
GX010115.MP4 (HEVC Main10 4K, obrót 180°)
   │
   ▼
MF SourceReader / D3D11VA  ──►  powierzchnia DXGI_FORMAT_P010 (GPU)
   │  (ReadSample ~0.6 ms)
   ▼
FIT/GPMF/GPX ─► resolver ─► precomputed cache ─► telemetry lookup (CPU, ~0.03 ms)
   ▼
CPU (producer): compose BELOW (Pillow RGBA) ──► dirty rects ──► np.copyto → persistent RGBA
   ▼
CPU (producer): compose ABOVE (Pillow RGBA) ──► EXACT tight bbox ──► crop ──► tobytes ──► bytes
   ▼
CPU (producer): map working image 692×692 RGBA ──► tobytes
   ▼
CPU→GPU uploads (ctypes / UpdateSubresource):
   • HUD below regions  (RGBA  → R8G8B8A8_UNORM)
   • above dirty regions (RGBA  → R8G8B8A8_UNORM)
   • map working image   (RGBA  → R8G8B8A8_UNORM)
   • chart static/dynamic, gauge
   ▼
D3D11 VideoProcessor:  P010 → NV12  +  GPU compositor (compute shader)
   z-order: base → normalize → ClearPreviousAboveMap → BlendCharts → BlendGauge
            → BlendAboveMap → ComposeHUDDirectNV12
   ▼
AMF HEVC encoder:  NV12 → HEVC (hevc_amf) ──► temp .h265
   ▼
FFmpeg remux:  -i temp.h265 -i source -map 0:v -map 1:a? -c:v copy -c:a copy
   ▼
MP4 wyjściowy:  WIDEO 1.5 s + AUDIO 592.6 s (cała ścieżka źródłowa — patrz sekcja 8)
```

**Formaty w pipeline:** `P010` (decode) → `NV12` (VP, 8-bit) + `RGBA`/`R8G8B8A8_UNORM` (HUD) → `NV12` (encode) → HEVC.

---

# 3. Wyniki benchmarków

## 3.1 Baseline — Testy A–D (pełny preset / bez overlay)

| Test | Rozdz. | FPS render | TRUE FPS | Mux [ms] | above_total med [ms] | producer med [ms] | consumer_native med [ms] | pipeline_total med [ms] |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| **A** 1080p60 full | 1920×1080 | **17.97** | 7.21 | 6975 | 16.15 | 23.84 | 6.55 | 9.07 |
| **B** 4K60 full | 3840×2160 | **5.93** | 3.36 | 7076 | 34.66 | 47.76 | 17.27 | 23.24 |
| **C** 1080p60 bez overlay | 1920×1080 | **23.62** | 6.28 | 6732 | 0 | 0.01 | 12.10 | 13.10 |
| **D** 4K60 bez overlay | 3840×2160 | **9.91** | 4.60 | 6629 | 0 | 0.01 | 20.02 | 21.10 |

> **TRUE FPS jest ~3–4× niższy od RENDER FPS** w każdym teście. Główną przyczyną jest stały koszt remuxu (~6.6–7.1 s), który kopiuje **całą** ścieżkę audio źródła (592.6 s) — patrz sekcja 8.
> Testy C/D (bez overlay) pokazują **sprzętowy sufit kodeka** iGPU: ~23.6 FPS (1080p) i ~9.9 FPS (4K) dla samego VP+encode. **4K60 nie jest osiągalne na tym APU nawet bez overlay.**

## 3.2 Rozbicie etapów (mediana ms/klatkę)

| Etap | 720p full | 1080p full | 4K full | p95 4K | % frame 1080p (55.6 ms) | CPU/GPU |
|---|---:|---:|---:|---:|---:|---|
| Decode (MF ReadSample) | 0.58 | 0.58 | 0.65 | 1.47 | 1.0% | GPU |
| Telemetry (PRECOMPUTED) | 0.03 | 0.04 | 0.04 | 0.26 | 0.1% | CPU |
| compose_overlay (BELOW) | 4.10 | 3.94 | 4.87 | 23.3 | 7.1% | CPU |
| **above_compose (render ABOVE)** | **11.65** | **13.98** | **23.64** | 56.9 | **25.1%** | CPU |
| above_bbox_crop (EXACT) | 0.06 | 0.09 | 0.10 | 0.5 | 0.2% | CPU |
| above_region_to_bytes | 0.91 | 1.94 | **10.95** | 38.1 | 3.5% | CPU |
| above_region_upload | 0.39 | 0.59 | 1.89 | 4.9 | 1.1% | CPU→GPU |
| **above_total** | **12.64** | **16.15** | **34.66** | 78.4 | **29.0%** | CPU |
| map_cpu_upload (working image) | 1.10 | 1.20 | 2.21 | 5.9 | 2.2% | CPU |
| HUD dirty extract (BELOW) | 0.22 | 0.30 | 0.99 | 2.6 | 0.5% | CPU |
| PIL/buffer preparation | 0.27 | 0.35 | 1.05 | 4.3 | 0.6% | CPU |
| update_hud | 0.06 | 0.12 | 0.29 | 1.1 | 0.2% | CPU→GPU |
| VideoProcessor CPU submit | 0.19 | 0.21 | 0.26 | 1.1 | 0.4% | CPU |
| VideoProcessor GPU completion | 2.17 | 4.16 | 12.05 | 29.2 | 7.5% | GPU |
| GPU wait/synchronization | 2.73 | 5.14 | 11.99 | 28.0 | 9.2% | CPU↔GPU |
| AMF submit/backpressure | 0.27 | 0.27 | 0.29 | 1.1 | 0.5% | CPU |
| AMF QueryOutput | 0.10 | 0.11 | 0.13 | 0.5 | 0.2% | CPU |
| Packet write | 0.09 | 0.11 | 0.14 | 0.6 | 0.2% | CPU |
| **Audio mux (cały eksport)** | 6415 | 6975 | 7076 | — | stały ~6.5–7.1 s | CPU |
| producer_prepare (CPU per-klatka) | 19.08 | 23.84 | 47.76 | 129.9 | 42.9% | CPU |
| consumer_upload | 0.85 | 1.82 | 3.28 | 11.7 | 3.3% | CPU→GPU |
| consumer_native_call | 4.27 | 6.55 | 17.27 | 53.8 | 11.8% | CPU/GPU |

> Frame time 1080p ≈ 55.6 ms (17.97 FPS); 4K ≈ 168.6 ms (5.93 FPS).

## 3.3 Ablacje rodzin wskaźników (720p60, 90 klatek) — koszt rodzin

| Konfiguracja | FPS render | compose_overlay med [ms] | above_compose med [ms] | map_cpu med [ms] | Wniosek |
|---|---:|---:|---:|---:|---|
| brak wskaźników | 40.79 | 0.00 | 0 | 0 | sufit VP+encode 720p |
| tylko tekst/liczby (time+iso+shutter+temp) | 40.52 | 2.47 | 0 | 0 | rodzina tekst ≈ **2.5 ms** |
| tylko gauge (compass + speed) | 42.31 | 1.85 | 0 | 0 | rodzina gauge ≈ **1.9 ms** |
| tylko chart (HR + Cadence) | 38.37 | 5.49 | 0 | 0 | rodzina chart ≈ **5.5 ms** (2×~2.7 ms) |
| tylko mapa (track_map, GPU) | 41.52 | 0.05 | 0.03 | 1.54 | mapa GPU ≈ **1.6 ms** (CPU working image) |
| gauge + chart | 32.68 | 11.80 | 0 | 0 | > suma (7.3) — większy canvas/kompozycja |
| mapa + gauge + chart | 29.27 | 0.05 | **8.46** | 1.09 | chart+gauge w ABOVE = **8.5 ms** |
| **pełny zestaw v10** | **24.74** | 4.10 | **11.65** | 1.10 | BELOW 4.1 + ABOVE 11.7 = ~15.8 ms compose |

> **Wniosek z ablacji:** koszt wskaźników ABOVE-map (11.65 ms) dominuje; z tego **charty ≈ 5.5 ms** (2 × ~2.7 ms renderer CPU_REFERENCE). Rodziny text/gauge/map są tanie (< 2.5 ms). Wartości `compose_overlay` dla kombinacji są wyższe niż suma rodzin z powodu re-renderu canvasu i większych regionów dirty.

## 3.4 Warianty (720p60) — mapa / decode / AMF / telemetria

| Wariant | FPS render | Kluczowy pomiar |
|---|---:|---|
| Mapa GPU (domyślna) | 41.52 (map-only) / 24.74 (full) | `map_cpu_upload` 1.54 ms |
| **Mapa CPU_REFERENCE** | **23.20** | `compose_overlay` **19.47 ms** (mapa w HUD Pillow) — **~18 ms drożej niż GPU** |
| Decode D3D11VA (domyślne) | 24.74 (full 720p) | `MF ReadSample` 0.58 ms |
| **Decode CPU (FFmpeg pipe)** | **14.30** | `consumer_upload` **23.46 ms** (odczyt raw NV12 z potoku) |
| AMF ENCODE (domyślne) | 24.74 | mux 6.4 s |
| **AMF SUBMIT_NO_MUX** | 23.91 | **TRUE FPS 22.47** (brak mux) — dowód, że enkoder nie jest wąskim gardłem |
| **AMF BYPASS** | n/a | TRUE FPS 26.26 (sam frontend, bez encode) |
| Telemetry PRECOMPUTED (domyślne) | 24.74 | `Telemetry/frame_data` 0.03 ms |
| **Telemetry REFERENCE** | **15.63** | `Telemetry/frame_data` **21.44 ms** (żywy resolver + interpolacja) |

## 3.5 Skalowanie z rozdzielczością (pełny preset)

| Rozdzielczość | FPS render | above_total [ms] | above_compose [ms] | above_region_to_bytes [ms] | VP GPU [ms] | GPU wait [ms] |
|---|---:|---:|---:|---:|---:|---|
| 720p | 22.23 | 12.30 | 11.28 | 0.89 | 2.38 | 3.01 |
| 1080p | 17.97 | 16.15 | 13.98 | 1.94 | 4.16 | 5.14 |
| 1440p | 10.95 | 19.39 | 15.89 | 3.20 | 5.33 | 6.15 |
| **4K** | **5.93** | **34.66** | **23.64** | **10.95** | **12.05** | **11.99** |

> **Etapy skalujące się gorzej niż liniowo (px 720p→4K = ×9):**
> - `above_region_to_bytes`: 0.89 → 10.95 ms (**×12.3**) — konwersja dużych regionów dirty.
> - `above_total`: 12.3 → 34.7 ms (**×2.8**) — render Pillow + tobytes.
> - `VP GPU completion` + `GPU wait`: 5.4 → 24.0 ms (**×4.4**) — sprzętowy sufit iGPU.
> - `above_region_upload` bytes: 2.17 → 17.47 MB/klatkę (**×8**).

## 3.6 Stabilność dłuższego renderu (soak 720p, 600 klatek)

| Miernik | Wartość |
|---|---|
| FPS render (steady-state) | **32.53** (wyższy niż 90-klatkowe przebiegi ~24.7 — efekt warm-up/cache) |
| TRUE FPS | 23.40 |
| Frame accounting | decoded 600 / processed 600 / AMF 600 / muxed 600 (**100%**, 0 zagubionych) |
| Mux | 6.88 s |
| System (sampler): CPU / GPU 3D / GPU encode | 21.7% / 10.7% / 37.8% |
| Degradacja | **Brak** — FPS stabilny przez cały przebieg; RAM ~22 GB użyte, VRAM ded. ~416 MB (stabilne) |

## 3.7 Metryki systemowe (sampler, średnia)

| Przypadek | CPU [%] | GPU 3D [%] | GPU Decode [%] | GPU Encode [%] | RAM użyte [MB] | VRAM ded. [MB] | VRAM shared [MB] |
|---|---:|---:|---:|---:|---:|---:|---:|
| 1080p full (sysprobe 300f) | 18.5 | 10.5 | 0* | 27.1 (max 54) | 22 103 | 423 | 698 |
| 720p full (soak 600f) | 21.7 | 10.7 | 0* | 37.8 | 22 168 | 416 | 738 |
| 4K full (test_B, n=2) | 23.0 | 4.0 | 0* | 0* (próba w mux) | 22 269 | 412 | 716 |

\* `GPU Decode` i `GPU Encode` przy krótkich przebiegach często trafiają w fazę remux (CPU-bound), stąd 0. Wiarygodne wartości encode (27–38%) pochodzą z długich przebiegów (soak/sysprobe). Częstotliwość samplera ~7–13 s/próbkę (limit licznika `GPU Engine`); n=1–2 dla krótkich case'ów.

---

# 4. Transfery pamięci (CPU ↔ GPU)

## 4.1 Uploady CPU→GPU (per klatka, z profilu)

| Operacja | Kierunek | Liczba/klatkę | 720p [MB/f] | 1080p [MB/f] | 4K [MB/f] | Koszt [ms] 4K |
|---|---:|---:|---:|---:|---:|---:|
| HUD BELOW dirty regiony (RGBA) | CPU→GPU | ~3 recty (max 8) | 0.56 | 0.91 | 2.29 | ~1.05 (prep) |
| **Above dirty regiony (RGBA)** | CPU→GPU | 1 region | **2.17** | **4.81** | **17.47** | **10.95 (tobytes) + 1.89 (upload)** |
| Mapa working image (RGBA 692×692) | CPU→GPU | 1 | 0.18 | 0.40 | 1.61 | 2.21 |
| **RAZEM CPU→GPU** | | | **2.91** | **6.12** | **21.37** | ~15+ |
| Gauge / chart tiles | CPU→GPU | 0–2 (fallback CPU) | ~0 (chart w above) | ~0 | ~0 | — |

## 4.2 Downloads GPU→CPU

- **Brak** w ścieżce produkcyjnej: ramka wideo pozostaje GPU-resident (`decoder_gpu_copy_frames = 0`), brak readback HUD/above w pętli. Readbacki A/B są wyłącznie diagnostyczne (`AMD_MAP_AB_READBACK`, `AMD_CHART_AB_READBACK`, `AMD_GAUGE_AB_READBACK` — domyślnie wyłączone).

## 4.3 Kopie GPU→GPU / D3D11

- `CopyResource submission`: 0 (ramki P010 trafiają wprost do VP — `direct_decoder_surface_to_vp_frames`).
- Compositing HUD→NV12 wykonuje compute shader (`DIRECT_NV12_COMPUTE_SHADER`) na GPU; jedna tekstura HUD `R8G8B8A8_UNORM` (utworzona 1×, upload 90×).
- Copy NV12 → staging → AMF: brak dodatkowych kopii w pętli (natywnie bufor NV12).

## 4.4 Mapa przepływu pamięci (rzeczywisty stan)

```text
Decode surface P010 (GPU) ──► VideoProcessor P010→NV12 (GPU) ──► AMF NV12 (GPU) ──► .h265
                                      ▲
              HUD RGBA (CPU/Pillow) ──► UpdateSubresource (CPU→GPU, ~0.6 MB)
              Above RGBA (CPU)      ──► UpdateSubresource (CPU→GPU, 2.2–17.5 MB)  ──► GPU compositor
              Map RGBA 692×692      ──► UpdateSubresource (CPU→GPU, 0.18–1.6 MB)        │
                                                                                        ▼
                                                    BlendCharts/BlendGauge/BlendMap → ComposeHUDDirectNV12 → NV12
```

**Brak round-trip GPU→CPU→GPU.** Cały koszt transferu to upload overlay (2.9–21.4 MB/klatkę), rosnący z rozdzielczością.

---

# 5. Konwersje formatów pikseli

| Konwersja | Skąd | Dokąd | CPU/GPU | Ile/klatkę | Koszt | 1080p | 4K |
|---|---|---|---|---|---:|---:|---:|
| HEVC 10-bit → P010 | dekoder MF | powierzchnia D3D11 `DXGI_FORMAT_P010` | GPU | 1 | decode ~0.6 ms | — | — |
| P010 → NV12 (8-bit) | VP | NV12 base | GPU | 1 | `VP GPU completion` | 4.16 ms | 12.05 ms |
| RGBA (HUD) → NV12 | GPU compositor (compute) | NV12 | GPU | 1 | w VP | (w VP) | (w VP) |
| RGBA → bytes (`tobytes`) | Pillow canvas | bytes upload | CPU | 1–8 | `above_region_to_bytes` | 1.94 ms | 10.95 ms |
| NV12 → HEVC | AMF | .h265 | GPU | 1 | AMF submit/query | 0.27+0.11 ms | 0.29+0.13 ms |

> **Brak powtarzalnych konwersji typu `BGRA→X→BGRA` i brak pełnej konwersji klatki na CPU.** Najdroższa konwersja CPU to `RGBA→bytes` regionów ABOVE (10.95 ms przy 4K). Najdroższa GPU to `P010→NV12` (VP).

---

# 6. Synchronizacje (miejsca, gdzie pipeline czeka)

| Miejsce | Mechanizm | 720p | 1080p | 4K | Uwaga |
|---|---|---:|---:|---:|---|
| `VideoProcessor GPU completion` | czekanie na zakończenie pracy VP na GPU | 2.17 ms | 4.16 ms | 12.05 ms | czek na GPU (kolejkuje AMF) |
| **`GPU wait/synchronization`** | blokująca synchronizacja CPU↔GPU (fence/query) | 2.73 ms | **5.14 ms** | **11.99 ms** | rośnie z rozdzielczością |
| `AMF submit/backpressure` | submit klatki do enkodera + ewentualne czekanie | 0.27 ms | 0.27 ms | 0.29 ms | **brak backpressure** (`input_full=0`, retry=0) |
| `AMF QueryOutput` | pobranie pakietu z enkodera | 0.10 ms | 0.11 ms | 0.13 ms | — |
| `MF ReadSample` | czekanie na dostępność próbki dekodera | 0.58 ms | 0.58 ms | 0.65 ms | p95 1.47 ms |
| `producer_queue_wait` / `consumer_queue_wait` | kolejka ASYNC | 0 | 0 | 0 | tryb SYNC |
| `consumer_native_call` | pełny czas wywołania natywnego (decode→VP→AMF) | 4.27 ms | 6.55 ms | 17.27 ms | p99 do 53.8 ms |
| **`Audio mux`** (subprocess) | **blokujący remux CAŁEJ ścieżki audio** | **6.4 s** | **6.98 s** | **7.08 s** | **stały koszt ~6.5–7.1 s niezależnie od długości wideo** |
| `thread.join` / flush | `telem_amd_flush` | ~0 | ~0 | ~0 | pomijalne |

> **Brak jawnych `flush`/`finish`/`map`/`unmap`/`future.result` w pętli per-klatkę.** Pipeline stoi realnie na: (a) blokującej synchronizacji VP (GPU wait), (b) remuxie audio na końcu. Przy 4K sumaryczny czas czekania na GPU (~24 ms/klatkę) stanowi ~14% budżetu klatki (168 ms).

---

# 7. Alokacje per-frame

## 7.1 Liczniki alokacji (AMD_AUDIT_ALLOCS, 60 klatek, 720p full)

| Strona | Średnia | Mediana | p95 | p99 (pierwsza klatka/warm-up) |
|---|---:|---:|---:|---:|
| Producer (CPU, live bloki netto) | 498 | **98** | 107 | 9 926 |
| Consumer (upload/native) | 27.8 | **27** | 27.1 | 61.3 |

## 7.2 Top lokacje alokacji (tracemalloc, delta nad 30-klatkowy eksport; per-klatka = /30)

| Lokacja | Rozmiar łączny [B] | Alokacje | ~/klatkę | Typ |
|---|---:|---:|---:|---|
| `src/indicators/chart_utils.py:914` (cache osi/layout chart) | 622 784 | 8 572 | ~286 / 20 KB | bufory RGBA chartów |
| `src/moving_map.py:384` (working image mapy) | 311 520 | 4 288 | ~143 | tile/array mapy |
| `src/moving_map.py:81` (dane RGB tile) | 274 368 | 8 574 | ~286 | dane pikseli tile |
| `src/moving_map.py:386/385` (kopie working image) | 174 400 / 174 336 | 4 289 | ~143 | array working image |
| `src/moving_map.py:508` (mapa) | 112 576 | 1 759 | ~59 | tile mapy |
| `PIL/ImageFont.py:282` (font tile) | 114 444 | 18 | <1 | tesselacja fontu |
| `src/indicators/chart_builder.py:58/59` (tiles chart) | 68 672 / 68 592 | 2 | <1 | tile statyczny/dynamiczny |
| `PIL/Image.py` (679/690/547/682) | ~30–13 KB | 167–265 | ~5–9 | kopie Image |

> **Gorące punkty alokacji:** rendering **chartów** (chart_utils: ~1 MB/klatkę) i **mapy** (moving_map: ~1 MB/klatkę). Do tego per-klatka bufor danych uploadu: HUD 0.56 MB + above 2.17 MB + mapa 0.18 MB (bytes). To one generują churn GC (producent ~98 żywych bloków/klatkę netto).

> Uwaga: pomiar tracemalloc dodaje ~30–50% narzutu (TRUE FPS ~1.5 przy 30 klatkach) — wyłącznie narzędzie diagnostyczne.

---

# 8. Ranking bottlenecków

Klasyfikacja wg zmierzonego kosztu i wpływu na wynik końcowy.

### 🔴 CRITICAL

**1. Remux kopiuje CAŁĄ ścieżkę audio źródła (stały koszt ~6.5–7.1 s/eksport)**
- **Plik/funkcja:** `src/ffmpeg/amd_native_exporter.py` — `cmd_mux = [ffmpeg, -i temp.h265, -i input, -map 0:v, -map 1:a?, -c:v copy, -c:a copy, output]` (brak `-t`/`-shortest` na mapie audio).
- **Mechanizm:** `-map 1:a?` + `-c:a copy` bez limitu kopiuje **całe** 592.6 s audio źródła (27 778 pakietów AAC).
- **Zmierzony koszt:** 6 415–7 076 ms **na każdy eksport, niezależnie od długości wideo** (1.5 s czy 10 s).
- **Udział:** TRUE FPS 7–8 vs RENDER FPS 24–32 → **remux obcina wydajność ~3–4×**. Przy 1080p (90 kl.) mux 6.4 s > render 3.6 s (64% czasu ściany).
- **Dodatkowo błąd poprawności:** plik wyjściowy ma wideo 1.5 s, ale **audio 592.6 s** (format duration = 592.6 s). Odtwarzacz pokaże 592 s z 1.5 s wideo.
- **Dlaczego bottleneck:** dominuje całkowity czas eksportu we wszystkich testach.

**2. Renderowanie CPU wskaźników ABOVE-map (głównie charty)**
- **Plik/funkcja:** `compose_overlay` (`src/indicators/compositor.py`) z layoutem `map_above_layout`; renderery `src/indicators/chart.py` (HR/Cadence) i `src/indicators/gauge.py`.
- **Mechanizm:** wskaźniki po mapie renderuje Pillow na CPU; charty w tym layoucie **nie** idą ścieżką GPU_SPLIT (`frame_accounting: cadence_gpu=0, hr_gpu=0`) i trafiają do dirty regionów ABOVE.
- **Zmierzony koszt:** `above_compose` = 11.65 ms (720p) / 13.98 (1080p) / 23.64 (4K); charty ≈ 5.5 ms (ablacja).
- **Udział:** 25% frame time (1080p); 14% (4K). To największy pojedynczy koszt per-klatka po stronie CPU.
- **Dlaczego bottleneck:** koszt renderera Pillow (zwłaszcza chartów ~2.7 ms każdy) + alokacje ~1 MB/klatkę.

### 🟠 MAJOR

**3. `above_region_to_bytes` + upload regionów ABOVE (CPU→GPU)**
- **Plik/funkcja:** `_extract_exact_above_regions` → `Image.tobytes("raw","RGBA")` + `telem_amd_update_above_region`.
- **Mechanizm:** wycięcie i serializacja RGBA dużych regionów dirty ABOVE do uploadu.
- **Zmierzony koszt:** tobytes 0.91 → 10.95 ms; upload 0.39 → 1.89 ms; dane 2.17 → 17.47 MB/klatkę.
- **Udział:** 4.5% (1080p) → 7.6% (4K); **skalowanie super-liniowe (×12 dla ×9 px)**.
- **Dlaczego bottleneck:** przy 4K to drugi najdroższy etap CPU po renderze ABOVE.

**4. Synchronizacja VideoProcessor + GPU wait (P010→NV12 + compositing)**
- **Plik/funkcja:** `D3D11VideoProcessorPipeline::ProcessFrame` + fence/query w `telem_amd_native.cpp`.
- **Mechanizm:** VP na GPU + blokująca synchronizacja CPU↔GPU.
- **Zmierzony koszt:** VP GPU 2.17/4.16/12.05 ms + GPU wait 2.73/5.14/11.99 ms (720p/1080p/4K).
- **Udział:** ~17% (1080p), ~14% (4K) frame time.
- **Dlaczego bottleneck:** sprzętowy sufit iGPU — bez overlay (test D) 4K osiąga tylko ~9.9 FPS.

### 🟡 MODERATE

**5. Telemetry w trybie REFERENCE (żywy resolver)**
- **Plik/funkcja:** `_live_frame_data` / `prepare_overlay_frame_data` (`src/indicators/frame_data.py`).
- **Mechanizm:** resolver + interpolacja per-klatka zamiast precomputed cache.
- **Zmierzony koszt:** 21.44 ms vs 0.03 ms (PRECOMPUTED). FPS 15.63 vs 24.74.
- **Ryzyko:** tylko gdy ktoś wyłączy PRECOMPUTED (domyślnie włączone).

**6. Map working image na CPU (`moving_map`)**
- **Plik/funkcja:** `render_map_working_image` (`src/indicators/moving_map.py`).
- **Mechanizm:** render kafelków 692×692 na CPU + upload.
- **Zmierzony koszt:** 1.10–2.21 ms; ~1 MB/klatkę alokacji; top alokator w tracemalloc.
- **Uwaga:** ścieżka GPU mapy jest już ~18 ms tańsza niż CPU_REFERENCE (19.47 ms compose).

### 🟢 NEGLIGIBLE

**7. AMF enkoder** — submit 0.27 ms, query 0.10 ms, `input_full=0`, retry=0, dropped=0. **Enkoder nie jest wąskim gardłem**; `SUBMIT_NO_MUX` daje TRUE FPS 22.47 przy 720p (ogranicza go frontend, nie encode). Przy 4K ogranicza go sprzętowy sufit enkodera (~10 FPS).

**8. Decode (D3D11VA)** — 0.58–0.65 ms. CPU decode fallback (23.46 ms consumer_upload) tylko gdy D3D11VA niedostępne.

**9. Telemetry PRECOMPUTED, HUD below, compose BELOW, map upload** — łącznie < 5 ms/klatkę.

---

## Ranking (największy wpływ na wynik):

1. **Remux audio (cała ścieżka)** — `amd_native_exporter.py` mux — ~6.5–7.1 s/eksport — CRITICAL (główny powód niskiego TRUE FPS + błąd długości pliku).
2. **CPU render ABOVE (charty)** — `compositor.py`/`chart.py` — 11.65–23.64 ms/klatkę — CRITICAL (największy koszt per-klatka).
3. **above_region_to_bytes/upload** — `_extract_exact_above_regions` — 0.9→10.95 ms, 17.5 MB/klatkę (4K) — MAJOR.
4. **VP GPU completion + GPU wait/sync** — `d3d11_vp_pipeline.cpp` — 5→24 ms/klatkę (4K) — MAJOR.
5. **Telemetry REFERENCE** (21.4 ms) / **Map CPU working image** (1–2 ms + ~1 MB alokacji) — MODERATE.

---

# 9. Wnioski — 2–5 miejsc z największym potencjałem optymalizacji

*(NIE wdrażano żadnej z nich — zgodnie z zakresem AUDIT ONLY.)*

1. **Ograniczenie remuxu do faktycznej długości wideo** (`-t <duration>` lub `-shortest` na mapie audio, względnie `-map 1:a? -t` / przycięcie audio). Potencjał: **TRUE FPS wzrasta z ~7 do ~22–24 FPS** (eliminacja 6.5–7.1 s stałego kosztu). Dodatkowo naprawia długość kontenera (592.6 s zamiast 1.5 s). **Najwyższy ROI w całym pipeline.**
2. **Przeniesienie chartów ABOVE na GPU / zmniejszenie kosztu renderera chartów.** Charty to ~5.5 ms + ~1 MB alokacji/klatkę. Wymaga to jednak analizy z-order (mapa jest barierą) i jest **blokowane przez AGENTS.md §35/§36** (otwarty bug chart seek/historia — nie refaktorować chartów poza zakresem). Potencjał: ~4–5 ms/klatkę.
3. **Redukcja `above_region_to_bytes`** (super-liniowe skalowanie przy 4K). Bezpośredni widok pamięci / mniejsze regiony / upload bez pośredniego `tobytes`. Potencjał: ~8–10 ms/klatkę przy 4K.
4. **Zmniejszenie liczby blokujących synchronizacji VP** (przy 4K `GPU wait` 12 ms). Wymaga ostrożności — nie zmieniać GPU↔CPU synchronizacji bez dedykowanego zadania (AGENTS.md §4).
5. **Alokacje mapy (moving_map)** — ~1 MB/klatkę, top alokator. Dopiero po zamknięciu 1–3.

---

# Zmienione pliki i instrumentacja

## Zmienione pliki produkcyjne

| Plik | Zmiana | Jak wyłączyć/usunąć |
|---|---|---|
| `src/ffmpeg/amd_native_exporter.py` | Dodano **wyłączaną** instrumentację `AMD_AUDIT_ALLOCS` (import `tracemalloc`, flaga, liczniki alokacji per-klatkę w `_prepare_frame_cpu`/`_consume_prepared_frame`, sekcja `audit_allocations` w profilu; merge producera zmieniony na `setdefault`) | Domyślnie **OFF** (`AMD_AUDIT_ALLOCS` nieustawione). Usunięcie: `git checkout src/ffmpeg/amd_native_exporter.py` (przywraca 1 wiersz diff). Zachowanie produkcyjne identyczne przy domyślnych zmiennych. |

## Nowe pliki diagnostyczne (scratch/ i Raporty/AMD_RENDER_PATH_AUDIT/)

- `scratch/run_amd_render_path_audit.py` — harness benchmarkowy (22 przypadki, profile, sampler).
- `scratch/audit_sampler.ps1` — ciągły sampler CPU/GPU/RAM/VRAM (CIM + Get-Counter).
- `scratch/analyze_audit_results.py`, `scratch/extract_alloc.py`, `scratch/extract_transfers.py`, `scratch/audit_tracemalloc_standalone.py`, `scratch/audit_counter_test*.ps1`, `scratch/audit_engtypes.ps1`, pliki `.log` — analiza i testy liczników.
- `Raporty/AMD_RENDER_PATH_AUDIT/` — wyniki: `<case>.mp4` + `<case>.mp4.amd_profile.json`, `audit_summary.json/.csv`, `audit_system_master.csv`.
- Usunięcie: usunąć powyższe pliki/katalog (żadne nie jest częścią builda ani importów produkcyjnych).

## Tested

- 22 przebiegi eksportu AMD (A–D, ablacje rodzin, mapa/decode/AMF/telemetria, skalowanie 720/1080/1440/4K, soak 600 kl., sysprobe 1080p 300 kl., tracemalloc).
- Pomiar: profile `.amd_profile.json`, frame accounting (100% klatek), sampler systemowy, tracemalloc, ffprobe (długość wyjścia).

## Not tested / ograniczenia

- **NVIDIA / Intel:** nie modyfikowano funkcjonalnie — zmiana dotyczy wyłącznie ścieżki AMD (`amd_native_exporter.py`) i jest wyłączona domyślnie. **Ścieżka NVIDIA zachowana statycznie; walidacja runtime nie była możliwa na tej maszynie AMD** (zgodnie z AGENTS.md §12).
- Próbki systemowe dla krótkich case'ów (A–D) są nieliczne (n=1–2) i część trafia w fazę remux (CPU-bound) — wartości `gpu_encode` przy krótkich przebiegach mogą być zaniżone; wiarygodne wartości dla długich przebiegów (soak/sysprobe).
- Licznik `GPU Decode` wykazywał 0 w próbkach — dekoder sprzętowy na tym APU jest bardzo lekki lub próbki omijały fazę dekodowania.
- Pomiary dotyczą wyłącznie tej maszyny (Ryzen 5 5500U / Radeon gfx90c); wyniki 4K odzwierciedlają sprzętowy sufit iGPU.

## Ryzyka / pozostałe problemy

- Remux kopiuje pełne audio (592.6 s) — **potwierdzony problem poprawności i wydajności** (opisany, nie naprawiony).
- `above_compose` i `above_region_to_bytes` skalują się super-liniowo z rozdzielczością.
- Zgodnie z AGENTS.md §35/§36 nie optymalizowano chartów ani nie dotykano buga seek/historii.
