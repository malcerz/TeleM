# RAPORT: AMD ABOVE BATCHED A/B TEST
## Porównanie trybów: `AMD_ABOVE_BATCHED=0` vs `AMD_ABOVE_BATCHED=1`

**Data:** 2026-09-16  
**Platforma:** Asus PN51 (AMD Radeon (TM) Graphics, Driver 31.0.21925.1001), Windows 11  
**Repozytorium robocze:** `C:\_DEV\BikeRideHUD` (branch: `amd-bikeridehud`, HEAD: `1b5485c0c7cd6f7b3d10e677aba315a40e0a3c98`)  
**Oracle READ-ONLY:** `C:\_DEV\TeleM` (branch: `amd-render`, HEAD: `7e4e34ecae13eae947c0386443e6a7317b42256f`)  
**Ścieżka wykonania:** Pełna ścieżka produkcyjna GUI (`BikeRideHUD.py` -> `MainWindow` -> `RenderTab` -> `RenderMixin` -> `AMDChildProcess` -> `amd_native_exporter` -> `telem_amd_native.dll` -> `AMF HEVC`).  

---

## 1. WYNIK DECYZJI (CASE)

```text
CASE B — AMD_ABOVE_BATCHED FUNCTIONAL BUT NO MATERIAL GAIN
```

### Uzasadnienie:
1. **Pełna sprawność funkcjonalna**: Tryb zbiorczego przesyłania wycinków warstwy ABOVE (`telem_amd_update_above_regions_batch`) działa stabilnie w procesie potomnym, nie generując żadnych błędów potoku D3D11 ani AMF (0 błędów, exit code 0).
2. **100% zgodność wizualna (Exact Parity)**: Porównanie pikselowe wszystkich wyekstrahowanych klatek kontrolnych (klatki 0, 50, 150, 250, 299) wykazało **0 różniących się pikseli** (Max Diff = 0, MAE = 0.0000).
3. **Brak mierzalnego zysku wydajności**:
   - FPS wzrósł z **37.48 FPS** do **37.52 FPS** (różnica +0.04 FPS / +0.11%, w granicach błędu statystycznego).
   - Średni czas `above_upload` wyniósł **1.978 ms** (Run A) vs **1.980 ms** (Run B) (różnica +0.002 ms).
   - Dominujący koszt w warstwie ABOVE stanowi rasteryzacja CPU widgetów w PIL (`above_total` ~13.7 ms), a nie sam narzut wywołań JNI/ctypes do C++.
4. **Rekomendacja**: Pozostawić flagę `AMD_ABOVE_BATCHED` na jej bezpiecznym, sprawdzonym domyślnym poziomie `0` (opt-in). Nie zmieniać domyślnej konfiguracji produkcyjnej.

---

## 2. HARD CONFIG PROOF (DOWÓD IZOLACJI ZMIENNEJ)

Pomiędzy testem Run A a Run B zmieniono wyłącznie jedną zmienną środowiskową: `AMD_ABOVE_BATCHED`. Wszystkie pozostałe parametry potoku renderingu, kompozytora i enkodera pozostały w 100% tożsame.

| Parametr | Run A (Baseline) | Run B (Batched) | Status |
|---|---|---|---|
| **AMD_ABOVE_BATCHED** | **0** | **1** | **JEDYNA ZMIENNA** |
| **AMD_AFTER_MAP_GAUGE_GPU** | GPU (AUTO) | GPU (AUTO) | Identyczne |
| **AMD_AFTER_MAP_CHART_GPU** | GPU_SPLIT | GPU_SPLIT | Identyczne |
| **AMD_GPU_MAP_ROTATE** | GPU (Track-Up) | GPU (Track-Up) | Identyczne |
| **AMD_QUEUE_DEPTH** | 0 (direct) | 0 (direct) | Identyczne |
| **AMD_VP_PROCESSOR_RING_SIZE** | 1 | 1 | Identyczne |
| **Rozdzielczość** | 3840x2160 (4K UHD) | 3840x2160 (4K UHD) | Identyczne |
| **Kodek** | HEVC Main (AMF) | HEVC Main (AMF) | Identyczne |
| **Liczba klatek** | 300 / 300 | 300 / 300 | Identyczne |
| **Plik wejściowy wideo** | `Video/GX020079.mp4` | `Video/GX020079.mp4` | Identyczne |
| **Plik telemetryczny FIT** | `Video/GX020079.fit` | `Video/GX020079.fit` | Identyczne |
| **DLL Build ID** | `telem-amd-native/1.0.0+1b5485c0c7cd` | `telem-amd-native/1.0.0+1b5485c0c7cd` | Identyczne |
| **DLL ABI** | 9 | 9 | Identyczne |
| **Config Fingerprint** | `a2d3c3c31020f591ad48...` | `67f242a125050457501d...` | Zgodne z przełączeniem flagi |

---

## 3. TABELA METRYK WYDAJNOŚCIOWYCH (A/B)

| METRIC | BATCHED=0 (Run A) | BATCHED=1 (Run B) | DELTA (B - A) | DELTA % |
|---|---|---|---|---|
| **Render Wall Time (s)** | 8.005 s | 7.996 s | -0.009 s | -0.11% |
| **FPS** | **37.48 FPS** | **37.52 FPS** | **+0.04 FPS** | **+0.11%** |
| **Frames Rendered** | 300 / 300 | 300 / 300 | 0 | 0.0% |
| **above_upload Avg (ms)** | 1.978 ms | 1.980 ms | +0.002 ms | +0.10% |
| **above_upload Median (ms)** | 1.629 ms | 1.647 ms | +0.018 ms | +1.07% |
| **above_upload P95 (ms)** | 4.081 ms | 4.072 ms | -0.009 ms | -0.21% |
| **above_upload P99 (ms)** | 4.698 ms | 5.161 ms | +0.463 ms | +9.86% |
| **above_total Avg (ms)** | 13.738 ms | 13.775 ms | +0.037 ms | +0.27% |
| **Output File Size (bytes)** | 85,375,163 | 85,375,163 | 0 | 0.0% |
| **AMF / D3D11 Errors** | 0 | 0 | 0 | 0.0% |
| **Child Exit Code** | 0 | 0 | 0 | 0.0% |
| **Visual Verdict** | `EXACT PARITY` | `EXACT PARITY` | 0 diff pixels | 100% tożsame |

---

## 4. WERYFIKACJA WIZUALNA (PIXEL PARITY)

Z obu wyrenderowanych plików MP4 wyodrębniono klatki o indeksach: `0`, `50`, `150`, `250`, `299`.

| Klatka | Czas wideo | Max Diff (0-255) | MAE | Różniące się piksele | % Różnicy | Werdykt |
|---|---|---|---|---|---|---|
| **Frame 0** | 0.00 s | 0 | 0.0000 | 0 | 0.00% | `EXACT PARITY` |
| **Frame 50** | 1.67 s | 0 | 0.0000 | 0 | 0.00% | `EXACT PARITY` |
| **Frame 150** | 5.00 s | 0 | 0.0000 | 0 | 0.00% | `EXACT PARITY` |
| **Frame 250** | 8.34 s | 0 | 0.0000 | 0 | 0.00% | `EXACT PARITY` |
| **Frame 299** | 9.98 s | 0 | 0.0000 | 0 | 0.00% | `EXACT PARITY` |

- **Status wizualny**: `USER VISUAL ACCEPTANCE=PENDING`
- **Contact Sheet Run A**: [contact_sheet.png](file:///C:/_DEV/BikeRideHUD/scratch/amd_above_batched/runA/contact_sheet.png)
- **Contact Sheet Run B**: [contact_sheet.png](file:///C:/_DEV/BikeRideHUD/scratch/amd_above_batched/runB/contact_sheet.png)
- **Raport różnic pikselowych**: [visual_diff.md](file:///C:/_DEV/BikeRideHUD/scratch/amd_above_batched/visual_diff.md)

---

## 5. PODSUMOWANIE I ZACHOWANIE GIT SAFETY

1. **Git status**:
   - Brak modyfikacji plików śledzonych (`git status --short` czysty dla śledzonych).
   - Wszystkie artefakty testowe zapisano w `scratch/amd_above_batched/`.
   - Repozytorium referencyjne Oracle `C:\_DEV\TeleM` pozostało w 100% nienaruszone.
2. **Kolejne kroki**:
   - Nie włączamy domyślnie `AMD_ABOVE_BATCHED=1`.
   - Następny obszar o realnym potencjale zysku FPS to rozbicie wąskich gardeł rasteryzacji CPU ABOVE (`alt_visual` ~3.2 ms, `compass` ~1.8 ms).
