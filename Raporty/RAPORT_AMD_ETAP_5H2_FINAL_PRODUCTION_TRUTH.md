# RAPORT: AMD ETAP 5H.2 — FINAL PRODUCTION TRUTH AUDIT

**Data:** 2026-08-28  
**Backend:** AMD (Ryzen 7 7730U / Radeon Graphics — 8C/16T, 32GB RAM UMA)  
**Gałąź:** `amd-render`  
**Status:** COMPLETE (STOP GATE 5H.2: PASS)

---

## 1. Executive Summary

W ramach etapu **ETAP 5H.2**:
1. **Wyjaśniono niespójność domyślnego stanu `AMD_MAP_SOURCE_REUSE`:**
   - W kodzie `src/ffmpeg/amd_native_exporter.py` linia 1787 domyślna flaga `_env_flag("AMD_MAP_SOURCE_REUSE", True)` była ustawiona na `True`, podczas gdy wszystkie kanoniczne benchmarki od etapu 5D.3 uruchamiały `AMD_MAP_SOURCE_REUSE=0`.
   - Zaktualizowano domyślną wartość w kodzie na `False` (`AMD_MAP_SOURCE_REUSE = 0`).
2. **Przeprowadzono rygorystyczny test A/B Map Source Reuse (1 warmup + 3 measured runs):**
   - **Wariant A (`AMD_MAP_SOURCE_REUSE=0`):** True FPS = **38.026 FPS** | Total Export = **29.743 s** | Map CPU = **1.024 ms**.
   - **Wariant B (`AMD_MAP_SOURCE_REUSE=1`):** True FPS = **37.857 FPS** | Total Export = **29.875 s** | Map CPU = **1.122 ms**.
   - **Wynik:** Wariant REUSE=1 jest wolniejszy o **-0.44% True FPS** i zwiększa czas eksportu o **+0.45%**.
   - **Decyzja:** **REUSE OFF (`AMD_MAP_SOURCE_REUSE=0`)** jako oficjalny, czysty domyślny standard produkcyjny.
3. **Audyt stanu GPU Lean (`LEAN_GPU`):**
   - Sprawdzono kanoniczny preset `presets/cycling_dashboard_v10.json`: wskaźnik `lean_indicator` **nie występuje** w tym layoucie (`lean_in_layout = False`).
   - Wartość `LEAN_GPU = 0` w logu produkcyjnym jest w 100% poprawna i oczekiwana.
4. **Korekta metodologii Frame Interval i rekalkulacja TOP10:**
   - Obok teoretycznego okresu wideo (**33.367 ms** @ 29.97 fps) wprowadzono **Rzeczywisty Interwał Renderera (Actual Render Interval)**:  
     $$\text{Actual Render Interval} = \frac{1000}{\text{RENDER\_FPS}} = \frac{1000}{40.022} = \mathbf{24.986\text{ ms}}$$
   - Względem rzeczywistego interwału `above_compose` stanowi aż **36.4%** czasu klatki, a narzut kadrowania i transferu dirty-rect (`above_region_to_bytes` + `above_exact_crop` + `above_region_upload`) stanowi kolejne **14.4%**.
5. **Potwierdzenie 5H Micro-Opt:**
   - 100% redukcji alokacji kanału alfa (14 703 → 0), `MaxDiff = 0`, brak wycieków pamięci. Status: **LOCAL PASS / SAFE MICRO-OPT** (zostaje w produkcji: **KEEP = YES**).

---

## 2. Map Source Reuse A/B Results

| Wariant | True FPS (mediana) | Czas eksportu (mediana) | Map CPU Upload (mediana) | Status |
| :--- | :--- | :--- | :--- | :--- |
| **A: `MAP_SOURCE_REUSE=0`** | **38.026 fps** | **29.743 s** | **1.024 ms** | **ZWYCIĘZCA (PRODUKCJA)** |
| **B: `MAP_SOURCE_REUSE=1`** | **37.857 fps** | **29.875 s** | **1.122 ms** | Odrzucono (-0.44% FPS) |

---

## 3. Recalculated TOP 10 Production Bottlenecks

| Ranga | Komponent / Obszar | Czas (ms median) | % Video Period (33.367ms) | % Actual Render Interval (24.986ms) | Ścieżka krytyczna |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **1** | `above_compose` | **9.107 ms** | 27.3% | **36.4%** | CPU text raster on 4K canvas |
| **2** | `consumer_native_call` | **6.580 ms** | 19.7% | **26.3%** | D3D11 VideoProcessor / GPU HUD / Fused CS |
| **3** | `above_region_to_bytes` | **1.438 ms** | 4.3% | **5.8%** | Dirty rect memory conversion |
| **4** | `above_exact_crop` | **1.210 ms** | 3.6% | **4.8%** | Pillow canvas bounding box crop |
| **5** | `map_cpu_upload` | **1.021 ms** | 3.1% | **4.1%** | Dynamic map tile slice & math |
| **6** | `above_region_upload` | **0.953 ms** | 2.9% | **3.8%** | D3D11 UpdateSubresource for dirty rects |
| **7** | `MF ReadSample/decode` | **0.618 ms** | 1.9% | **2.5%** | D3D11VA HW HEVC decode |
| **8** | `above_tight_bbox_collect` | **0.580 ms** | 1.7% | **2.3%** | Widget tight bbox tracking |
| **9** | `AMF submit/backpressure` | **0.428 ms** | 1.3% | **1.7%** | AMF HW HEVC encode submit |
| **10**| `VideoProcessor CPU submit` | **0.260 ms** | 0.8% | **1.0%** | Native Blt call |

---

## 4. STOP GATE 5H.2 Checklist

- [x] Preview map: **PASS (6/6 matrix tests)**
- [x] Map reuse state: **Jednoznaczny (REUSE=0 default w kodzie i benchmarku)**
- [x] Lean state: **Jednoznaczny (nieobecny w v10 -> LEAN_GPU=0)**
- [x] Compass / Slope: **Dynamiczne z FIT (561 kątów, 12 nachyleń)**
- [x] Production configuration: **Jednoznaczna (SYNC, REFERENCE, REFERENCE, GPU MAP ALIGN16 REUSE0, GPU GAUGE AUTO, GPU CHARTS SPLIT, GPU HUD, FUSED NV12)**
- [x] 5H Parity: **PASS (MaxDiff = 0)**

**Decyzja:** STOP GATE 5H.2 osiągnięty. Przejście do **ETAP 5I**.
