# RAPORT: AMD VIDEOPROCESSOR RING SIZE A/B TEST
## Porównanie trybów: `AMD_VP_PROCESSOR_RING_SIZE=1` vs `AMD_VP_PROCESSOR_RING_SIZE=2`

**Data:** 2026-09-16  
**Platforma:** Asus PN51 (AMD Radeon (TM) Graphics, Driver 31.0.21925.1001), Windows 11  
**Repozytorium robocze:** `C:\_DEV\BikeRideHUD` (branch: `amd-bikeridehud`, HEAD: `1b5485c0c7cd6f7b3d10e677aba315a40e0a3c98`)  
**Oracle READ-ONLY:** `C:\_DEV\TeleM` (branch: `amd-render`, HEAD: `7e4e34ecae13eae947c0386443e6a7317b42256f`)  
**Ścieżka wykonania:** Pełna produkcyjna ścieżka Real GUI (`BikeRideHUD.py` -> `MainWindow` -> `RenderTab` -> `RenderMixin` -> `AMDChildProcess` -> `amd_native_exporter` -> `telem_amd_native.dll` -> `AMF HEVC`).  

---

## 1. WYNIK DECYZJI (CASE)

```text
CASE B — RING_SIZE=2 NO MATERIAL GAIN
```

### Uzasadnienie:
1. **Stabilność i brak błędów**: Tryb pierścienia z 2 obiektami VideoProcessor (`RING_SIZE=2`) działa w 100% stabilnie w procesie potomnym (0 błędów D3D11, 0 błędów AMF, exitcode=0, 0 porzuconych klatek).
2. **100% zgodność pikselowa (Exact Parity)**: Wszystkie klatki kontrolne (0, 50, 150, 250, 299) wykazują **0 różniących się pikseli** (Max Diff = 0, MAE = 0.0000).
3. **Brak mierzalnego zysku wydajności (próg >= 2% nieosiągnięty)**:
   - Run A (`RING_SIZE=1`): **37.47 FPS** (czas: 8.007 s)
   - Run B (`RING_SIZE=2`): **37.32 FPS** (czas: 8.038 s)
   - Różnica wynosi **-0.15 FPS (-0.38%)**, co w całości mieści się w szumie pomiarowym run-to-run (< 0.5%).
   - Na zintegrowanym APU AMD narzut przełączania/cyklowania dwóch instancji VideoProcessor w sterowniku D3D11 nie przynosi skrócenia całkowitego czasu klatki, ponieważ wąskim gardłem pozostaje przygotowanie warstw HUD na CPU (~24.5 ms) oraz przepustowość kodera VCN.

---

## 2. REKOMENDOWANA KOMBINACJA PRODUKCYJNA

Na podstawie wyników poprzednich etapów (A/B Queue Depth oraz niniejszego A/B Ring Size):

```text
RECOMMENDED_QUEUE_DEPTH=2
RECOMMENDED_RING_SIZE=1
```

*(Uwaga: Zgodnie z wytycznymi, domyślne ustawienia w kodzie produkcyjnym pozostają jeszcze nienaruszone i zostaną zaktualizowane w osobnym etapie).*

---

## 3. HARD CONFIG PROOF (DOWÓD IZOLACJI)

| Parametr | Run A (RING=1) | Run B (RING=2) | Status |
|---|---|---|---|
| **AMD_VP_PROCESSOR_RING_SIZE** | **1** | **2** | **TESTOWANA ZMIENNA** |
| **AMD_QUEUE_DEPTH** | 2 | 2 | Stała |
| **AMD_CPU_GPU_PIPELINE** | ASYNC | ASYNC | Stała |
| **AMD_ABOVE_BATCHED** | 0 | 0 | Stała |
| **AMD_AFTER_MAP_GAUGE_GPU** | GPU (AUTO) | GPU (AUTO) | Stała |
| **AMD_AFTER_MAP_CHART_GPU** | GPU_SPLIT | GPU_SPLIT | Stała |
| **AMD_GPU_MAP_ROTATE** | GPU (Track-Up) | GPU (Track-Up) | Stała |
| **Rozdzielczość** | 3840x2160 (4K UHD) | 3840x2160 (4K UHD) | Stała |
| **Kodek** | HEVC Main (AMF) | HEVC Main (AMF) | Stała |
| **Liczba klatek** | 300 / 300 | 300 / 300 | Stała |
| **Plik wideo / FIT** | `GX020079.mp4` / `.fit` | `GX020079.mp4` / `.fit` | Stała |
| **Config Fingerprint** | `62db3300c3e96a0d1b26...` | `73ff7672ce7bbbaaea84...` | Zweryfikowano |

---

## 4. TABELA PORÓWNAWCZA METRYK (A/B)

| METRIC | RING=1 (Run A) | RING=2 (Run B) | DELTA (B - A) | DELTA % |
|---|---|---|---|---|
| **Render Wall Time (s)** | 8.007 s | 8.038 s | +0.031 s | +0.39% |
| **FPS** | **37.47 FPS** | **37.32 FPS** | **-0.15 FPS** | **-0.38%** |
| **Frames Rendered** | 300 / 300 | 300 / 300 | 0 | 0.0% |
| **producer_prepare Avg (ms)** | 24.566 ms | 24.551 ms | -0.015 ms | -0.06% |
| **producer_queue_wait Avg (ms)** | 0.610 ms | 0.569 ms | -0.041 ms | -6.72% |
| **consumer_queue_wait Avg (ms)** | 2.613 ms | 4.562 ms | +1.949 ms | +74.59% |
| **consumer_upload Avg (ms)** | 4.803 ms | 4.588 ms | -0.215 ms | -4.48% |
| **consumer_native_call Avg (ms)**| 16.154 ms | 14.678 ms | -1.476 ms | -9.14% |
| **above_total Avg (ms)** | 13.553 ms | 13.563 ms | +0.010 ms | +0.07% |
| **above_upload Avg (ms)** | 2.105 ms | 1.923 ms | -0.182 ms | -8.65% |
| **decode_mf Avg (ms)** | 1.052 ms | 0.995 ms | -0.057 ms | -5.42% |
| **vp_submit Avg (ms)** | 1.851 ms | 1.837 ms | -0.014 ms | -0.76% |
| **amf_submit Avg (ms)** | 0.423 ms | 0.432 ms | +0.009 ms | +2.13% |
| **amf_query Avg (ms)** | 12.443 ms | 11.023 ms | -1.420 ms | -11.41% |
| **D3D11 / AMF Errors** | 0 | 0 | 0 | 0.0% |
| **Dropped Frames** | 0 | 0 | 0 | 0.0% |
| **Child Exit Code** | 0 | 0 | 0 | 0.0% |
| **Visual Parity** | `EXACT PARITY` | `EXACT PARITY` | 0 diff pixels | 100% tożsame |

---

## 5. WERYFIKACJA WIZUALNA (PIXEL PARITY)

| Klatka | Czas wideo | Max Diff (0-255) | MAE | Różniące się piksele | % Różnicy | Werdykt |
|---|---|---|---|---|---|---|
| **Frame 0** | 0.00 s | 0 | 0.0000 | 0 | 0.00% | `EXACT PARITY` |
| **Frame 50** | 1.67 s | 0 | 0.0000 | 0 | 0.00% | `EXACT PARITY` |
| **Frame 150** | 5.00 s | 0 | 0.0000 | 0 | 0.00% | `EXACT PARITY` |
| **Frame 250** | 8.34 s | 0 | 0.0000 | 0 | 0.00% | `EXACT PARITY` |
| **Frame 299** | 9.98 s | 0 | 0.0000 | 0 | 0.00% | `EXACT PARITY` |

- **Status wizualny**: `USER VISUAL ACCEPTANCE=PENDING`
- **Contact Sheet Run A**: [contact_sheet.png](file:///C:/_DEV/BikeRideHUD/scratch/amd_vp_ring_ab/runA/contact_sheet.png)
- **Contact Sheet Run B**: [contact_sheet.png](file:///C:/_DEV/BikeRideHUD/scratch/amd_vp_ring_ab/runB/contact_sheet.png)
- **Raport wizualny**: [visual_diff.md](file:///C:/_DEV/BikeRideHUD/scratch/amd_vp_ring_ab/visual_diff.md)

---

## 6. STATUS I PODSUMOWANIE

1. **Git safety**:
   - Brak modyfikacji plików śledzonych (`git status --short` czysty dla śledzonych).
   - Wszystkie artefakty testowe zapisano w `scratch/amd_vp_ring_ab/`.
   - Repozytorium referencyjne Oracle `C:\_DEV\TeleM` nienaruszone.
2. **Kolejne kroki**:
   - Nie włączamy `RING_SIZE=2`.
   - Zgodnie z dyscypliną zadania: **STOP po tym teście**. Nie przechodzimy samodzielnie do `alt_visual`.
