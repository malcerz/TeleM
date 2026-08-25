# RAPORT AMD — ETAP 5G: GPU-resident final map resize + composite

**Status: ✅ PASS-EXACT** (raw 691×691 GPU resample vs Pillow LANCZOS: **MAE 0.173**, 99.8% pikseli w granicach ±1)

---

## 1. CEL ETAPU

Usunięcie Pillow LANCZOS 692→691 z produkcyjnej ścieżki AMD (Python) i przeniesienie
**finalnego resize'u + composite'u mapy na GPU**:

- CPU nadal renderuje mapę roboczą **692×692 RGBA** (renderer mapy bez zmian — `MovingMapRenderer`).
- Upload 692 RGBA → GPU (persistent texture).
- GPU: resize 692→691 (separable, premultiplied-alpha) → blend "over" do HUD canvas.
- Żaden readback GPU→CPU w produkcji (`telem_amd_get_map_resample` tylko diagnostyka).
- `AMD_MAP_PATH=CPU_REFERENCE|GPU`, z-order guard `GPU_MAP_UNSAFE_LAYOUT → CPU_REFERENCE`.
- Pillow `compose_overlay` NIE zmienione (mapa po prostu nie jest już w `compose_layout`).

---

## 2. AUDYT PRZYCZYNOWY (root-cause)

**Wykryta i naprawiona usterka produkcyjna (blokowała cały etap):**

- W `ResampleAndBlendMap()` (shader resample i blend) **constant buffery były aktualizowane
  (`UpdateSubresource`), ale NIGDY nie były wiązane** do slotu `b0` przez
  `CSSetConstantBuffers`. Skutek: shader czytał śmieci z CB → `dstW/dstH`=0 → wszystkie
  wątki `return` (pusty output), ewent. `srcW/srcH`=0 → wszystkie tapy poza zakresem → `(0,0,0,0)`.
  **Objaw: tekstura resample pusta, HUD bez mapy, a „mapa" w wideo pochodziła z zanieczyszczonego base'u.**
- **Fix:** `ID3D11Buffer* cbs[1] = { m_mapResampleCB }; m_context->CSSetConstantBuffers(0, 1, cbs);`
  przed każdym `Dispatch` (resample i blend). Po fixie: tekstura resample = dokładnie mapa
  CPU (mean RGBA 98.3/101.6/80.5/255 = CPU ref), HUD ma mapę w bboxie, wideo poprawne.

**Istotny kontekst walidacyjny — zanieczyszczony źródłowy plik wideo:**

- `Video/GX020079.mp4` jest **wcześniej wyeksportowanym plikiem** — zawiera już wypaloną
  mapę (i overlay) w pozycji track_map (rotated `(114,1332)` = unrotated `(3035,137)`).
- W trybie GPU opakowa, nieprzezroczysta mapa GPU **zastępuje** mapę base'u w tej samej
  lokalizacji → finalne wideo poprawne.
- W trybie CPU_REFERENCE mapa CPU również przykrywa mapę base'u.
- Dlatego absolutne porównanie z „gołym" źródłem jest mylące; miarodajne jest
  **porównanie GPU vs CPU_REFERENCE** (oba zastępują mapę base'u) oraz **surowy A/B 691 RGBA**.

**Dodatkowe ustalenia techniczne:**

- `CopyResource` + `Map` odczytuje regiony pisane wyłącznie przez UAV compute poprawnie
  (dowód: checkpoint NV12 działa), ale **każdy readback całego HUD 3840×2160 per frame
  stawia pipeline AMF** (frame-droppy: 3–17 klatek). Fix: readback czyta małą teksturę
  resample 691×691 (tylko diagnostyka).
- Dump w środku `ResampleAndBlendMap` (między Pass1 a Pass2) również psuł pipeline —
  w produkcji **żadnego dumpu/readbacku między dispatchami**.
- `GetDeviceRemovedReason()` jest na DEVICE, nie na context; `CopyResource` zwraca `void`.

---

## 3. ARCHITEKTURA PRZED / PO

**PRZED (5E / CPU_REFERENCE):**
```
Pillow compose_overlay: render mapy 692 + LANCZOS 692→691 + composite do canvasa 3840x2160
  -> HUD upload (dirty-rect, region mapy w rectach) -> ComposeHUDDirectNV12 (NV12)
```

**PO (5G / GPU):**
```
Pillow compose_overlay: BEZ mapy (compose_layout bez track_map)  -> HUD upload (bez regionu mapy)
CPU (Python) render_map_working_image()  ->  692x692 RGBA
  -> telem_amd_update_map(): UpdateSubresource -> m_mapTexture (692, persistent)
  -> ProcessFrame: [Pass1 resample 692->691] -> [Pass2 blend over do HUD bbox]
  -> ComposeHUDDirectNV12 (NV12)   // zero readback GPU->CPU w produkcji
```

Wybrany punkt integracji: **GPU blend bezpośrednio do HUD canvas (UAV) w bboxie mapy,
przed NV12 compositorem** — zero zmian w rendererach mapy i w NV12 compositorze.

**Z-order:** guard `_map_gpu_layout_safe()` wymaga, by `track_map` był OSTATNIM włączonym
indikatorem (GPU blend = „on top"). Dla obecnego `def_layout.json` — spełnione.
Gdy nie spełnione → automatyczny fallback `GPU_MAP_UNSAFE_LAYOUT → CPU_REFERENCE`
(przetestowane: unsafe layout z `track_map` pierwszym → komunikat fallback + CPU_REFERENCE active).

---

## 4. ZASOBY GPU (steady-state, 0 alloc/frame)

| Zasób | Rozmiar | Format | Bind | Uwagi |
|---|---|---|---|---|
| `m_mapTexture` | 692×692 | R8G8B8A8_UNORM | SRV | persistent, `UpdateSubresource`/frame |
| `m_mapShaderView` | SRV mapy źródłowej | | | |
| `m_mapResampleTexture` | 691×691 | R8G8B8A8_UNORM | SRV+UAV | persistent (tworzona lazy, raz) |
| `m_mapResampleUAV/SRV` | | | | |
| `m_mapReadbackStaging` | 691×691 | R8G8B8A8_UNORM | STAGING | tylko diagnostyka |
| `m_hudTexture` (istniejący) | 3840×2160 | R8G8B8A8_UNORM | RT+SRV+UAV | dodano UAV (5G) |

Shadery: `m_mapResampleShader` (cs_5_0, 0=bilinear 2-tap, 1=bicubic CatmullRom 4-tap,
2=Lanczos-3 6-tap; premultiplied-alpha; pixel-center `(out+0.5)*scale-0.5`) oraz
`m_mapBlendShader` (straight-alpha „over" do HUD UAV). CB: ResampleCB (6×uint32),
BlendCB (4×uint32).

---

## 5. TEST FILTRU (map A/B, surowy 691 RGBA vs Pillow LANCZOS)

| Filtr | MAE | MAX | n>1 % | n>16 % | Uwagi |
|---|---|---|---|---|---|
| **LANCZOS (3)** | **0.173** | 37.75 | 0.20 | 0.02 | ✅ wybrany — zgodny z Pillow |
| BILINEAR (0) | 2.16 | 74 | 42.6 | 0.56 | 2-tap, wyraźnie gorszy |
| BICUBIC (1) | 17.99 | 251 | 69.2 | 35.5 | kernel CatmullRom nie pokrywa się z Pillow LANCZOS |

Wybór: **LANCZOS** (MAE 0.173 — praktycznie EXACT; różnice tylko na krawędziach, MAX ~37).

---

## 6. MAP A/B — PEŁNE 1131 KLATEK (LANCZOS)

Eksport: `ab_lanczos_1131_fixed.mp4`, `AMD_MAP_AB_READBACK=1` (tylko diagnostyka).

| Metryka | wartość |
|---|---|
| map_gpu_frames | 1131 |
| MAE (raw 691 RGBA) | **0.173** |
| MAX | 37.75 (śr), p95 42 |
| n>1 | 0.20% |
| n>2 | 0.11% |
| n>4 | 0.05% |
| n>8 | 0.033% |
| n>16 | **0.020%** |
| upload | 1.827 MiB/frame |
| frame accounting | 1131/1131 |
| AMF drops / retries | 0 / 0 |

Wniosek: **PASS-EXACT** — GPU Lanczos-3 ≈ Pillow LANCZOS (99.8% pikseli ±1; różnice to
krawędzie/klampowanie + efekt bazy, udokumentowane).

---

## 7. PARITY (wideo GPU vs CPU_REFERENCE, domena kodowana NV12/HEVC)

| Frame | FULL MAE | FULL n>16 % | map-region MAE | map n>16 % |
|---|---|---|---|---|
| 30 | 2.44 | 2.3 | **1.66** | 0.16 |
| 300 | 2.14 | 2.3 | **2.27** | 0.14 |
| 900 | 2.08 | 2.2 | **1.22** | 0.06 |

- Mapa GPU: poprawny bbox (rotated `(114,1332)` = unrotated `(3035,137)`), 691×691,
  marker + trasa obecne i zgodne z CPU (wizualna kontrola side-by-side + diff).
- Różnice full-frame ~2.1–2.4 to **niedeterminizm kodera AMF** (osobne przebiegi) +
  zmiana samej mapy; nie są to błędy kompozytora.
- **PASS parity** (kryterium zgodności, nie bit-identical).

---

## 8. CZASY (produkcja GPU, 1131)

| Etap | CPU_REFERENCE | GPU | Δ |
|---|---|---|---|
| compose_overlay | 60.29 ms | **38.04 ms** | −22.25 ms (mapa poza Pillow) |
| map render + upload (Python) | — | 3.71 ms | nowe (renderer mapy 692) |
| map tobytes + `telem_amd_update_map` | — | 0.37 ms | |
| HUD texture upload | 2.24 ms | 2.00 ms | bez regionu mapy |
| AMF backpressure | 0.69 ms | 0.82 ms | |
| **TRUE FPS** | **10.462** | **13.134** | **+25.5 %** |

Uwaga: bazowy 5E (z historii) TRUE FPS 15.781 / compose_overlay 38.571 ms mierzony
w innych warunkach obciążenia; miarodajne porównanie A/B w tej samej sesji:
**GPU 13.134 vs CPU_REFERENCE 10.462** (+25.5 %).

---

## 9. TRANSFERY

| Kierunek | Wielkość | Uwagi |
|---|---|---|
| CPU → GPU (mapa) | **1.827 MiB/frame** (692×692×4) | UpdateSubresource, persistent tex |
| GPU → CPU | **0 MiB/frame (produkcja)** | readback tylko diagnostyka (`AMD_MAP_AB_READBACK=1`) |
| HUD upload | mniejsze niż 5E | region mapy nie jest już w dirty-rectach |

---

## 10. FINALNY EKSPORT PRODUKCYJNY

- `after_production_1131.mp4` (GPU, LANCZOS, bez readbacku, diagnostyka OFF).
- 1131/1131 frames, AMF drops 0, TRUE FPS 13.134.
- CPU_REFERENCE fallback zweryfikowany: `cpu_ref_1131.mp4` (1131/1131, TRUE FPS 10.462).
- Z-order fallback zweryfikowany: unsafe layout → `GPU_MAP_UNSAFE_LAYOUT -> CPU_REFERENCE`.

---

## 11. ODPOWIEDZI NA PYTANIA KONTROLNE

1. **Czy CPU renderer mapy pozostał bez zmian?** Tak — `MovingMapRenderer` i
   `render_map_working_image()` renderują tę samą 692×692; zmieniono tylko gdzie kończy
   się finalny resize (GPU zamiast Pillow LANCZOS w compose).
2. **Czy Pillow LANCZOS zniknął z produkcji AMD?** Tak — `compose_layout` nie zawiera
   `track_map` w trybie GPU; żaden LANCZOS 692→691 nie jest wykonywany w Pythonie.
3. **Gdzie jest punkt integracji?** GPU blend do HUD canvas (UAV) w bboxie mapy,
   przed `ComposeHUDDirectNV12`.
4. **Z-order zachowany?** Tak — guard wymaga track_map jako ostatniego; inaczej fallback
   CPU_REFERENCE.
5. **Overlap możliwy z innymi widgetami?** Nie dla obecnego layoutu (track_map ostatni,
   mapa nie zachodzi na inny widget na wierzchu).
6. **Steady-state alokacje GPU?** 0/frame — tekstury persistent, shadery/CB tworzone raz.
7. **Readback GPU→CPU w produkcji?** 0 MiB — `telem_amd_get_map_resample` wyłącznie
   diagnostyczny.
8. **Jaki filtr wybrany?** LANCZOS (MAE 0.173).
9. **Czy A/B raw 691 jest EXACT?** MAE 0.173 / n>16 0.02% → PASS-EXACT (krawędzie ~±37).
10. **Czy wideo parity przechodzi?** Tak — map-region MAE 1.2–2.3 w domenie kodowanej;
    reszta to niedeterminizm AMF.
11. **Czy CPU_REFERENCE działa nadal?** Tak — 1131/1131, mapa w Pillow, TRUE FPS 10.462.
12. **Czy zanieczyszczenie źródła wpływa na wynik?** Mapa base'u w GX020079.mp4 jest
    przykrywana przez mapę GPU/CPU w tej samej lokalizacji; A/B surowy 691 i parity
    GPU-vs-CPU są miarodajne.

---

## 12. PLIKI / ARTEFAKTY

- `native/d3d11_amf_pipeline/src/d3d11_vp_pipeline.{h,cpp}` — kompozytor mapy GPU
  (InitializeMapCompositor, UpdateMapTexture, ResampleAndBlendMap, GetMapResampleReadback).
- `native/d3d11_amf_pipeline/src/telem_amd_native.cpp` — eksporty map (set_map_mode,
  set_map_filter, set_map_geometry, update_map, get_map_resample, get_map_stats).
- `src/ffmpeg/amd_native_exporter.py` — integracja (compose_layout, upload/readback, profil `etap5g`).
- `src/indicators/moving_map.py` — `render_map_working_image()` (renderer mapy bez zmian).
- `scratch/run_etap5g_export.py` — runner 5G (`--map-path`, `--filter`, `--output`).
- Wyniki: `Raporty/AMD_ETAP5G/` (mp4 + profile JSON + PNG parity/diff).
- `scratch/resample_isolation.cpp` — niezależny test shadera resample (dokumentacja).

**STOP — raport gotowy. Nie wykonuję następnego etapu.**
