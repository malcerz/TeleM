# Raport: ETAP 10O — Current Bottleneck Profile (po ETAPACH 10M / 10M2 / 10N)

**Data pomiaru:** 2026-08-22  
**Typ zadania:** `AUDIT ONLY / PROFILING` (brak zmian w kodzie produkcyjnym)  
**Preset bazowy:** `presets/cycling_dashboard_v10.json`  
**Materiał testowy:** `Video/GX010115.MP4` + `Video/GX010115.json` + `Video/Jazda_na_rowerze_w_porze_lunchu.fit`  
**Benchmark:** AMD Native D3D11, 1280×720, 120 klatek @ 60 FPS, pełny preset v10 (wszystkie wskaźniki aktywne)

---

## 1. Konfiguracja Benchmarku i Środowiska

- **Platforma:** Windows AMD Native D3D11VA + AMF HEVC Hardware Encoder
- **Pipeline:** `CPU_BELOW_MAP -> GPU_MAP -> CPU_ABOVE_MAP`
- **Rozdzielczość wyjściowa:** `1280x720 @ 60.0 FPS` (120 klatek, czas wideo: 2.0 s)
- **Tryby pracy:** `AMD_MAP_PATH = GPU`, `AMD_CHART_PATH = CPU_REFERENCE`, `AMD_GAUGE_PATH = GPU`, `AMD_TELEMETRY_MODE = PRECOMPUTED`, `AMD_NATIVE_HUD_MODE = GPU_HUD`, `AMD_NATIVE_HUD_UPLOAD = DIRTY`
- **Pomiary telemetryczne:** FIT 4299 punktów, SmartSync offset = +2.000 s (confidence: high)

---

## 2. Świeże Pomiary Per-Widget — `CPU_BELOW_MAP` (120 klatek)

| Widget | Renderer (mean / med / p95) | Paste/Blend (mean / med) | TOTAL (mean / med / p95) |
|---|---:|---:|---:|
| **`time_display`** | 0.800 / **1.141** / 1.311 ms | 0.237 / **0.198** ms | **1.036 ms** (med: **1.339 ms**, p95: 1.546 ms) |
| **`dist_visual`** | 0.153 / **0.112** / 0.161 ms | 0.598 / **0.539** ms | **0.750 ms** (med: **0.650 ms**, p95: 0.837 ms) |
| **`fit_battery_pct_text`** | 0.047 / **0.018** / 0.033 ms | 0.204 / **0.175** ms | **0.251 ms** (med: **0.193 ms**, p95: 0.283 ms) |
| **`fit_solar_pct_text`** | 0.029 / **0.015** / 0.027 ms | 0.197 / **0.173** ms | **0.226 ms** (med: **0.187 ms**, p95: 0.256 ms) |
| **SUMA WIDGETÓW BELOW** | **1.029 ms** | **1.236 ms** | **2.263 ms/frame** |

> **Weryfikacja `time_display`:**
> `time_display` pozostaje jedynym widgetem w `CPU_BELOW_MAP` o koszcie renderera $> 0.5\text{ ms}$ (średnia: `0.800 ms`, mediana: `1.141 ms`). Wynika to z formatowania 3 linii tekstu (czas, data, aktywność) z pełnym TrueType outline stroke w Pillow.

---

## 3. Świeże Pomiary Per-Widget — `CPU_ABOVE_MAP` (120 klatek)

| Widget | Renderer (mean / med / p95) | Rotacja / Paste (mean / med) | TOTAL (mean / med / p95) |
|---|---:|---:|---:|
| **`compass`** | 0.360 / **0.394** / 0.479 ms | 0.449 / **0.417** ms | **0.809 ms** (med: **0.810 ms**, p95: 0.935 ms) |
| **`slope_text`** | 0.173 / **0.135** / 0.209 ms | 0.601 / **0.546** ms | **0.774 ms** (med: **0.683 ms**, p95: 0.872 ms) |
| **`fit_enhanced_speed_text`** (Speed Gauge) | 0.446 / **0.191** / 0.640 ms | 0.217 / **0.177** ms | **0.663 ms** (med: **0.400 ms**, p95: 0.861 ms) |
| **`fit_curVpower_text`** (Virtual Power) | 0.103 / **0.083** / 0.124 ms | 0.391 / **0.372** ms | **0.494 ms** (med: **0.458 ms**, p95: 0.568 ms) |
| **`alt_visual`** (Altitude) | 0.138 / **0.094** / 0.256 ms | 0.344 / **0.326** ms | **0.482 ms** (med: **0.420 ms**, p95: 0.753 ms) |
| **`exposure_text`** (Shutter) | 0.279 / **0.016** / 0.733 ms | 0.059 / **0.053** ms | **0.339 ms** (med: **0.069 ms**, p95: 0.802 ms) |
| **`fit_heart_rate_text`** (HR Chart 10M) | 0.178 / **0.140** / 0.205 ms | 0.155 / **0.141** ms | **0.332 ms** (med: **0.283 ms**, p95: 0.380 ms) |
| **`fit_cadence_text`** (Cadence Chart 10M) | 0.161 / **0.127** / 0.190 ms | 0.121 / **0.113** ms | **0.282 ms** (med: **0.243 ms**, p95: 0.328 ms) |
| **`iso_text`** (ISO) | 0.198 / **0.021** / 0.535 ms | 0.071 / **0.059** ms | **0.270 ms** (med: **0.082 ms**, p95: 0.639 ms) |
| **`temp_text`** (Temperature) | 0.037 / **0.015** / 0.022 ms | 0.063 / **0.058** ms | **0.100 ms** (med: **0.074 ms**, p95: 0.117 ms) |
| **SUMA WIDGETÓW ABOVE** | **2.073 ms** | **2.472 ms** | **4.545 ms/frame** |

---

## 4. Rozbicie Ścieżki `Altitude` (`rotated_paste`)

Dokładny pomiar kroków wykonywanych dla wskaźnika `alt_visual` (120 klatek):
- **Czysty render linijki:** `0.139 ms` (mediana: `0.105 ms`)
- **Wywołanie `Image.rotate(-90.0)`:** `0.027 ms` (mediana: `0.022 ms`)
- **Kopia / alokacja kafelka:** `< 0.005 ms`
- **Nakładanie przez `alpha_composite`:** `0.344 ms` (mediana: `0.326 ms`)
- **TOTAL:** `0.482 ms` (mediana: `0.420 ms`)

> **Wniosek:** Koszt rotacji Pillow `Image.rotate(90)` sam w sobie wynosi zaledwie `0.022 ms`. Dominującym kosztem jest nakładanie wyrotowanego bufora RGBA przez `alpha_composite` na duży obszar docelowy.

---

## 5. Izolowany Mikrobenchmark Rotacji (1000 iteracji)

Test przeprowadzony na rzeczywistym rastrze `alt_visual`:
- `Image.rotate(-90.0, expand=True, resample=Image.BICUBIC)`: **`0.010 ms/call`**
- `Image.rotate(-90.0, expand=True, resample=Image.NEAREST)`: **`0.010 ms/call`**
- `Image.transpose(Image.Transpose.ROTATE_270)`: **`0.009 ms/call`** (zysk: 1.1x)
- **Pixel Parity (`NEAREST` vs `TRANSPOSE`):** `diff bbox = None` (100% Byte-Exact).

---

## 6. Rozbicie Wskaźnika `Compass`

- **Renderer (tarcza + igła + tekst kierunku):** `0.360 ms` (mediana: `0.394 ms`)
- **Rotacja igły:** wykonywana wewnątrz renderera w małym wycinku (`< 0.020 ms`).
- **Placement & Alpha Composite:** `0.449 ms` (mediana: `0.417 ms`).
- **TOTAL Compass:** `0.809 ms` (mediana: `0.810 ms`).

---

## 7. Rozbicie Wskaźnika `Virtual Power` (`fit_curVpower_text`)

- **Czysty renderer (formatowanie + font tile):** `0.103 ms` (mediana: `0.083 ms`).
- **Placement / Blend (`alpha_composite`):** `0.391 ms` (mediana: `0.372 ms`).
- **TOTAL Virtual Power:** `0.494 ms` (mediana: `0.458 ms`).

> **Rekomendacja:** Renderer ma $\le 0.1\text{ ms}$. Ponad 80% kosztu to nakładanie w kompozytorze. **Optymalizacja renderera Virtual Power NIE jest rekomendowana.**

---

## 8. `CPU_ABOVE_MAP` — Analiza Residualna

- **Całkowity czas `above_compose` w pętli produkcyjnej:** `5.280 ms` (mediana: `4.713 ms`, P95: `6.128 ms`).
- **Suma poszczególnych wskaźników ABOVE:** `4.545 ms` (mediana: `4.072 ms`).
- **`CPU_ABOVE RESIDUAL`:** **`0.735 ms/frame`** (mediana: **`0.641 ms`**).
  - Czyszczenie bufora wielokrotnego użytku (`canvas.regional_clear`): `~0.320 ms`.
  - Śledzenie bounding boxów (`_paste_prior_bboxes` + dispatch overhead): `~0.415 ms`.

---

## 9. Szczegółowe Pomiary Crop / Alpha Scan w `CPU_ABOVE_MAP`

Pomiary z profilu produkcyjnego AMD D3D11VA (120 klatek):
- **`above_candidate_crop`:** średnia **`0.762 ms`** (mediana: **`0.647 ms`**, P95: `1.205 ms`)
- **`above_local_alpha_scan`:** średnia **`0.428 ms`** (mediana: **`0.338 ms`**, P95: `0.710 ms`)
- **`above_final_crop`:** średnia **`0.579 ms`** (mediana: **`0.476 ms`**, P95: `0.974 ms`)
- **`above_bbox_tracking` (planowanie klastrów):** średnia **`0.076 ms`** (mediana: **`0.057 ms`**)
- **ŁĄCZNY KOSZT `above_bbox_crop`:** średnia **`1.845 ms`** (mediana: **`1.526 ms`**, P95: `3.188 ms`)

### Metryki skanowania pikseli per-frame:
- Liczba klastrów kandydatów (`candidate_clusters`): średnio **`2.0` regiony/klatkę**.
- Skanowane piksele alfa (`scanned_pixels`): średnio **`340 500` px/klatkę**.
- Przesyłane piksele po przycięciu (`uploaded_pixels`): średnio **`210 240` px/klatkę**.

---

## 10. Konwersja `RGBA -> bytes` w `CPU_ABOVE_MAP`

- **Czas trwania `above_region_to_bytes`:** średnia **`1.003 ms`** (mediana: **`0.933 ms`**, P95: `1.515 ms`, P99: `2.283 ms`).
- **Objętość danych:** średnio **`840 960` bajtów/klatkę** (~0.84 MB per-frame dla dirty regions).
- **Zasięg konwersji:** wyłącznie wykadrowane regiony dirty (`reg_img.crop(local_alpha_bbox).tobytes("raw", "RGBA")`), nie cały canvas 1280×720.

---

## 11. `CPU_BELOW_MAP` — Analiza Residualna

- **Całkowity czas `compose_overlay` (BELOW):** `2.542 ms` (mediana: `2.609 ms`, P95: `3.428 ms`).
- **Suma wskaźników BELOW:** `2.263 ms`.
- **`CPU_BELOW RESIDUAL`:** **`0.279 ms/frame`**.
- **Etap przygotowania bufora dirty (`PIL/buffer preparation`):** `0.308 ms` (mediana: `0.256 ms`).
- **Ekstrakcja wycinków dirty (`HUD dirty extract`):** `0.231 ms` (mediana: `0.211 ms`).

---

## 12. Pomiary Ścieżki Mapy (`track_map`)

Pomiary z produkcyjnego profilu AMD (GPU Map Path):
- **`render_map_working_image` (CPU prep):** `1.028 ms` (mediana).
- **`map_cpu_upload` (Pillow tobytes + przekazanie):** średnia **`3.519 ms`** (mediana: **`1.028 ms`**, P95: `1.981 ms`).
- **GPU upload & resize/composite submit:** `< 0.001 ms` (praca asynchroniczna GPU D3D11).

---

## 13. Pomiary Dekodera, Synchronizacji GPU i Enkodera AMF

- **`MF ReadSample / decode availability`:** średnia **`1.544 ms`** (mediana: **`0.613 ms`**, P95: `1.269 ms`).
- **`MF decoder surface acquisition`:** `0.011 ms`.
- **`VideoProcessor CPU submit`:** średnia **`0.408 ms`** (mediana: **`0.192 ms`**).
- **`GPU wait/synchronization`:** `0.000 ms` (brak blokujących CPU-GPU syncs).
- **`AMF submit/backpressure`:** średnia **`0.557 ms`** (mediana: **`0.456 ms`**).
- **`AMF QueryOutput`:** średnia **`0.131 ms`** (mediana: **`0.112 ms`**).
- **`Packet write`:** średnia **`0.141 ms`** (mediana: **`0.115 ms`**).

---

## 14. Analiza Warm-up (klatki 1–10) vs Steady-State (klatki 11–120)

| Etap | Warm-up (Klatki 1–10, avg / med) | Steady-State (Klatki 11–120, avg / med) | Wpływ Cache / Stabilizacji |
|---|---:|---:|---|
| **`above_compose`** | 10.412 / **8.125 ms** | 4.813 / **4.640 ms** | 2.2x przyspieszenie po rozgrzaniu cache |
| **`below_compose`** | 3.840 / **3.210 ms** | 2.424 / **2.518 ms** | Stabilizacja bufora canvas |
| **`above_bbox_crop`** | 3.120 / **2.450 ms** | 1.729 / **1.480 ms** | Ustalone klastry bbox |
| **`above_region_to_bytes`** | 1.450 / **1.210 ms** | 0.963 / **0.912 ms** | Mniejsze regiony po warmup |
| **`producer_prepare`** | 42.150 / **38.400 ms** | 24.046 / **17.850 ms** | 2.4x przyspieszenie steady-state |

---

## 15. Weryfikacja Rozliczenia Klatek (*Frame Accounting*)

- **Decoded samples:** `120`
- **Producer submitted:** `120`
- **Consumer processed:** `120`
- **AMF encoded:** `120`
- **Muxer written:** `120`
- **Status:** **`100% PASS` (0 klatek pominiętych, 0 zduplikowanych)**.

---

## 16. Aktualna Wydajność Klatkowa (FPS)

- **`RENDER FPS`:** **`35.247 FPS`** (czas generowania wideo: 3.405 s dla 120 klatek @ 60 FPS).
- **`TRUE FPS` (wraz z audio remux):** **`13.534 FPS`** (całkowity czas: 8.866 s).

---

## 17. Aktualny TOP 15 Wąskich Gardeł (Ranking wg `ms/frame`)

| Rank | Komponent / Operacja | Koszt (ms/frame) | Kategoria | Opis i Wpływ |
|---:|---|---:|---|---|
| **1** | **`above_candidate_crop` + `above_local_alpha_scan` + `above_final_crop`** | **1.845 ms** (med: 1.526) | `COMPOSITOR` | Wielokrotne kadrowanie i skanowanie kanału alfa w `map_above` |
| **2** | **`above_region_to_bytes`** | **1.003 ms** (med: 0.933) | `MEMORY/COPY` | Konwersja RGBA do bajtów dla przesyłanych regionów dirty |
| **3** | **`time_display` (Renderer)** | **0.800 ms** (med: 1.141) | `RENDERER` | 3 linie tekstu z obrysem TrueType per-frame bez tile cache |
| **4** | **`compass` (Total: Render 0.36 + Paste 0.45)** | **0.809 ms** (med: 0.810) | `RENDERER / PLACEMENT` | Render tarczy, igły i nakładanie na canvas |
| **5** | **`slope_text` (Total: Render 0.17 + Paste 0.60)** | **0.774 ms** (med: 0.683) | `PLACEMENT` | Nakładanie dużej linijki pionowej na canvas |
| **6** | **`dist_visual` (Total: Render 0.15 + Paste 0.60)** | **0.750 ms** (med: 0.650) | `PLACEMENT` | Nakładanie linijki poziomej na canvas |
| **7** | **`CPU_ABOVE RESIDUAL` (Canvas clear + dispatch)** | **0.735 ms** (med: 0.641) | `COMPOSITOR` | Czyszczenie regionalne bufora + obsługa layoutu |
| **8** | **`fit_enhanced_speed_text` (Speed Gauge)** | **0.663 ms** (med: 0.400) | `RENDERER` | Rysowanie łuku prędkości i formatowanie cyfrowe |
| **9** | **`MF ReadSample / decode availability`** | **0.613 ms** (mediana) | `DECODER` | Dostępność próbki DXGI w dekoderze MediaFoundation |
| **10** | **`AMF submit / hardware encode`** | **0.456 ms** (mediana) | `ENCODER` | Czas przekazania ramki do kodera AMF HEVC |
| **11** | **`fit_curVpower_text` (Virtual Power)** | **0.494 ms** (med: 0.458) | `PLACEMENT` | Render 0.10 ms, Paste 0.39 ms na canvas |
| **12** | **`alt_visual` (Altitude)** | **0.482 ms** (med: 0.420) | `PLACEMENT` | Render 0.14 ms, Paste 0.34 ms |
| **13** | **`map_cpu_upload`** | **1.028 ms** (mediana) | `MAP` | Pobranie i konwersja roboczego kafelka mapy |
| **14** | **`exposure_text` (Shutter)** | **0.339 ms** (med: 0.069) | `RENDERER` | Generowanie etykiety migawki |
| **15** | **`fit_heart_rate_text` (HR Chart 10M)** | **0.332 ms** (med: 0.283) | `RENDERER` | Zoptymalizowany wykres 10M |

---

## 18. Klasyfikacja i ROI Potencjalnych Następnych Celów

| Kandydat | Aktualny Koszt | Oczekiwany Zysk | Ryzyko Architektoniczne | Zakres i Uwagi |
|---|---:|---:|---|---|
| **A. `above_bbox_crop` (Crop + Alpha Scan)** | **1.845 ms** | **~1.0 – 1.3 ms** | Średnie | Zastąpienie kosztownego skanowania alfa `candidate_image.getchannel("A").getbbox()` bezpośrednim śledzeniem dokładnych boksów wskaźników z `compose_overlay` |
| **B. `above_region_to_bytes`** | **1.003 ms** | **~0.4 – 0.6 ms** | Niskie | Wykorzystanie bezpośredniego widoku pamięci bez zbędnych alokacji pośrednich |
| **C. `time_display` (Renderer)** | **1.036 ms** (med: 1.34) | **~0.7 – 0.8 ms** | Niskie | Wdrożenie `_draw_text_bounded_cached` sprawdzonego w 10N |
| **D. `compass` (Renderer + Paste)** | **0.809 ms** | **~0.3 – 0.4 ms** | Niskie | Wdrożenie statycznej tarczy w LRU i cached text tile |
| **E. `rotated_paste` (Fixed 90° Altitude)** | **0.482 ms** | **~0.05 – 0.1 ms** | Niskie | `Image.rotate` trwa tylko 0.02 ms; zysk minimalny |
| **F. `fit_curVpower_text` (Virtual Power)** | **0.494 ms** | **< 0.05 ms** | Niskie | Sam renderer trwa tylko 0.10 ms; brak uzasadnienia |

---

## 19. Wnioski i Wybór Kolejnego Celu

1. **Lokalne renderery w `bar.py` (Slope, Altitude, Distance) oraz wykresy (HR, Cadence) przestały być wąskim gardłem:**
   - Wszystkie zoptymalizowane renderery działają w czasie $\le 0.15\text{ ms/frame}$.
2. **Głównym wąskim gardłem w całym pipeline stała się warstwa kompozytora dirty-region `CPU_ABOVE_MAP`:**
   - Sekwencja `above_candidate_crop` + `above_local_alpha_scan` + `above_final_crop` + `above_region_to_bytes` zajmuje łącznie **`~2.85 ms/frame`** (mediana: **`2.46 ms/frame`**).
   - Operacja ta wynika ze skanowania kanału alfa Pillow (`getchannel("A").getbbox()`) dla 340 000 pikseli w każdej klatce, mimo że kompozytor zna już dokładne współrzędne wszystkich wyrenderowanych wskaźników.
3. **Drugim, mniejszym wąskim gardłem renderera pozostaje `time_display`:**
   - Koszt renderera `time_display` wynosi **`0.800 ms`** (mediana: **`1.141 ms`**), co czyni go ostatnim drogim lokalnym rendererem.

---

## 20. Identyfikacja Wąskiego Gardła i Rekomendacja

```text
CURRENT BOTTLENECK: compositor dirty-region path (above_candidate_crop + above_local_alpha_scan + above_region_to_bytes)
NEXT TARGET: compositor dirty-region path
```
