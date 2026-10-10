# RAPORT: AMD QUEUE DEPTH A/B TEST
## Porównanie trybów: `AMD_QUEUE_DEPTH=0` (SYNC) vs `AMD_QUEUE_DEPTH=2` (ASYNC)

**Data:** 2026-09-16  
**Platforma:** Asus PN51 (AMD Radeon (TM) Graphics, Driver 31.0.21925.1001), Windows 11  
**Repozytorium robocze:** `C:\_DEV\SportCamHUD` (branch: `amd-bikeridehud`, HEAD: `1b5485c0c7cd6f7b3d10e677aba315a40e0a3c98`)  
**Oracle READ-ONLY:** `C:\_DEV\TeleM` (branch: `amd-render`, HEAD: `7e4e34ecae13eae947c0386443e6a7317b42256f`)  
**Ścieżka wykonania:** Pełna ścieżka produkcyjna Real GUI (`SportCamHUD.py` -> `MainWindow` -> `RenderTab` -> `RenderMixin` -> `AMDChildProcess` -> `amd_native_exporter` -> `telem_amd_native.dll` -> `AMF HEVC`).  

---

## 1. SEMANTYKA FLAGI (POTWIERDZENIE Z KODU)

Na podstawie analizy kodu `src/ffmpeg/amd_config.py`, `src/ffmpeg/amd_native_exporter.py` oraz `native/d3d11_amf_pipeline/src/telem_amd_native.cpp`:

1. **`AMD_QUEUE_DEPTH=0` (Direct / Synchronous Path)**:
   - W module `amd_config.py` wartość `queue_depth=0` jest tożsama z trybem `AMD_CPU_GPU_PIPELINE=SYNC`.
   - W module `amd_native_exporter.py` (linie 6380–6425) brak jest wątku kolejkowego; pętla główna wykonuje w jednym wątku sekwencyjnie przygotowanie klatki CPU (`_prepare_frame_cpu`), bezpośrednie przesłanie i natywne wywołanie GPU (`_consume_prepared_frame`). Czas oczekiwania na kolejkę (`producer_queue_wait`, `consumer_queue_wait`) wynosi ściśle `0.0 ms`.
   - W DLL C++ `telem_amd_native.cpp` (linia 1537) parametr `pipeEnv="SYNC"` ustawia `isAsync=false`.
2. **`AMD_QUEUE_DEPTH=2` (Asynchronous Producer-Consumer Queue)**:
   - Odpowiada trybowi `AMD_CPU_GPU_PIPELINE=ASYNC` z kolejką `queue.Queue(maxsize=2)`.
   - W module `amd_native_exporter.py` (linie 6289–6375) uruchamiany jest dedykowany wątek roboczy `TeleM-CpuProducer`, który niezależnie rasteryzuje warstwy HUD na CPU i buforuje do 2 przygotowanych klatek w pamięci.
   - Wątek główny (konsument) pobiera ramki z kolejki i asynchronicznie przesyła je do GPU, realizując nakładanie sprzętowe VideoProcessor i kodowanie AMF HEVC równolegle do pracy CPU.

---

## 2. WYNIK DECYZJI (CASE)

```text
CASE A — AMD_QUEUE_DEPTH=2 VALIDATED
```

### Uzasadnienie:
1. **Mierzalny, powtarzalny zysk wydajności**:
   - Prędkość renderowania wzrosła z **32.09 FPS** do **36.74 FPS** (**+4.65 FPS**, zysk **+14.50%**).
   - Całkowity czas renderowania 300 klatek 4K uległ skróceniu z **9.349 s** do **8.165 s** (**-1.184 s**, oszczędność **12.67%**).
2. **100% zgodność pikselowa (Exact Parity)**:
   - Wszystkie klatki kontrolne (0, 50, 150, 250, 299) wykazują **0 różniących się pikseli** (Max Diff = 0, MAE = 0.0000).
3. **Stabilność potoku i brak zakleszczeń**:
   - 0 błędów AMF / D3D11, 0 porzuconych klatek, poprawny kod zakończenia procesu potomnego (`exitcode=0`), brak wycieków uchwytów.
4. **Dyspozycja**: Zgodnie z wytycznymi, pomimo uzyskania +14.50% zysku, **nie zmieniamy jeszcze domyślnego defaultu w kodzie produkcyjnym**.

---

## 3. HARD CONFIG PROOF (DOWÓD IZOLACJI)

| Parametr | Run A (SYNC / Q=0) | Run B (ASYNC / Q=2) | Status |
|---|---|---|---|
| **AMD_QUEUE_DEPTH** | **0** | **2** | **TESTOWANA ZMIENNA** |
| **AMD_CPU_GPU_PIPELINE** | **SYNC** | **ASYNC** | **SKORELOWANA ZMIENNA POTOKU** |
| **AMD_ABOVE_BATCHED** | 0 | 0 | Stała |
| **AMD_VP_PROCESSOR_RING_SIZE** | 1 | 1 | Stała |
| **AMD_AFTER_MAP_GAUGE_GPU** | GPU (AUTO) | GPU (AUTO) | Stała |
| **AMD_AFTER_MAP_CHART_GPU** | GPU_SPLIT | GPU_SPLIT | Stała |
| **AMD_GPU_MAP_ROTATE** | GPU (Track-Up) | GPU (Track-Up) | Stała |
| **Rozdzielczość** | 3840x2160 (4K UHD) | 3840x2160 (4K UHD) | Stała |
| **Kodek** | HEVC Main (AMF) | HEVC Main (AMF) | Stała |
| **Liczba klatek** | 300 / 300 | 300 / 300 | Stała |
| **Plik wideo / FIT** | `GX020079.mp4` / `.fit` | `GX020079.mp4` / `.fit` | Stała |
| **Config Fingerprint** | `a2d3c3c31020f591ad48...` | `62db3300c3e96a0d1b26...` | Zweryfikowano |

---

## 4. TABELA PORÓWNAWCZA METRYK (A/B)

| METRIC | QUEUE=0 (Run A) | QUEUE=2 (Run B) | DELTA (B - A) | DELTA % |
|---|---|---|---|---|
| **Render Wall Time (s)** | 9.349 s | 8.165 s | **-1.184 s** | **-12.67%** |
| **FPS** | **32.09 FPS** | **36.74 FPS** | **+4.65 FPS** | **+14.50%** |
| **Frames Rendered** | 300 / 300 | 300 / 300 | 0 | 0.0% |
| **producer_prepare Avg (ms)** | 21.656 ms | 25.275 ms | +3.619 ms | +16.71% |
| **producer_queue_wait Avg (ms)** | 0.000 ms | 0.177 ms | +0.177 ms | Nakładanie |
| **consumer_queue_wait Avg (ms)** | 0.000 ms | 11.567 ms | +11.567 ms | Nakładanie |
| **consumer_upload Avg (ms)** | 2.185 ms | 3.941 ms | +1.756 ms | +80.37% |
| **consumer_native_call Avg (ms)**| 4.488 ms | 8.734 ms | +4.246 ms | +94.61% |
| **above_total Avg (ms)** | 12.511 ms | 14.400 ms | +1.889 ms | +15.10% |
| **above_upload Avg (ms)** | 0.887 ms | 1.704 ms | +0.817 ms | +92.11% |
| **decode_mf Avg (ms)** | 0.826 ms | 0.979 ms | +0.153 ms | +18.52% |
| **vp_submit Avg (ms)** | 1.242 ms | 1.767 ms | +0.525 ms | +42.27% |
| **amf_submit Avg (ms)** | 0.422 ms | 0.475 ms | +0.053 ms | +12.56% |
| **amf_query Avg (ms)** | 2.285 ms | 5.430 ms | +3.145 ms | +137.64% |
| **Queue Stalls** | 0 | 0 | 0 | 0.0% |
| **AMF / D3D11 Errors** | 0 | 0 | 0 | 0.0% |
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
- **Contact Sheet Run A**: [contact_sheet.png](file:///C:/_DEV/SportCamHUD/scratch/amd_queue_depth/runA/contact_sheet.png)
- **Contact Sheet Run B**: [contact_sheet.png](file:///C:/_DEV/SportCamHUD/scratch/amd_queue_depth/runB/contact_sheet.png)
- **Raport wizualny**: [visual_diff.md](file:///C:/_DEV/SportCamHUD/scratch/amd_queue_depth/visual_diff.md)

---

## 6. WNIOSKI I DALSZE KROKI

1. Tryb asynchroniczny z kolejką 2 klatek (`AMD_QUEUE_DEPTH=2`) przynosi bardzo wyraźny, mierzalny zysk wydajności (**+14.50% FPS**) dzięki równoległemu przygotowaniu klatek na CPU i przetwarzaniu na GPU/AMF.
2. Zgodnie z poleceniem użytkownika: **STOP po tym teście**. Nie zmieniamy jeszcze domyślnego kodu ani nie przechodzimy do testów `ring=2` ani `alt_visual`.
