# TeleM — RAPORT AMD ETAP 4: GPU HUD Compose + Multi-Region HUD Atlas + Walidacja Zero-Copy

**Data wykonania**: 12 sierpnia 2026 r.  
**Środowisko testowe**:
- **CPU**: AMD Ryzen 5 5500U (6 rdzeni / 12 wątków)
- **GPU**: AMD Radeon iGPU (gfx90c, pamięć współdzielona APU)
- **OS**: Windows 11
- **FFmpeg**: Wersja z obsługą `d3d11va`, `hevc_amf` oraz filtrami `split/crop/overlay`

---

## 1. Podsumowanie wyników Etapu 4

W ramach AMD ETAP 4 przeprowadzono audyt potoku zero-copy oraz zaimplementowano algorytm **Multi-Region HUD Atlas (2D Shelf Packing)**, wyeliminowany zbędne przesyłanie przezroczystości RGBA przez potok IPC do FFmpeg.

### Tabela porównawcza BEFORE (Etap 3) vs AFTER (Etap 4):

| Metryka | BEFORE (Etap 3) | AFTER (Etap 4) | Zmiana / Zysk |
| :--- | :---: | :---: | :---: |
| **NO HUD FPS (Direct GPU)** | 324.22 FPS | **768.40 FPS** | **+137% (Szczytowa przepustowość GPU)** |
| **SUB-WINDOW HUD FPS** | 26.85 FPS | **26.88 FPS** | **Brak regresji (0.5 MB transferu)** |
| **NORMAL HUD FPS** | 21.12 FPS | **23.95 FPS** | **+13.4% wzrost wydajności eksportu** |
| **NORMAL HUD transfer (MB/klatkę)** | 31.1 MB / klatkę | **19.4 MB / klatkę** | **-38.6% mniejszy bufor IPC** |
| **`ffmpeg_write` AVG (Normal HUD)** | 0.30 ms | **0.18 ms** | **-40.0% mniej czasu w zapisie** |
| **`ffmpeg_write` P95 (Normal HUD)** | 0.68 ms | **0.42 ms** | **-38.2%** |
| **Pętla `hwdownload` (NO HUD)** | 0 | **0** | **Wyeliminowana (Zero-Copy)** |
| **Pętla `hwdownload` (HUD Modes)** | 1 (auto-insert) | **1 (auto-insert)** | **Wewnętrzny sync FFmpeg overlay** |
| **1200-Frame Endurance Test** | 56.63 s (21.19 FPS) | **51.24 s (23.42 FPS)** | **PASS (100% dostarczonych klatek)** |

---

## 2. Wyniki Audytu Zero-Copy i Filtergraph FFmpeg

Uruchomienie FFmpeg z logowaniem `-loglevel verbose` potwierdziło:
1. **NO HUD Direct Passthrough**:  
   - Format wejściowy: `d3d11` (powierzchnia VRAM D3D11VA).  
   - Przekazywanie do enkodera: bezpośredni graficzny kontekst D3D11 do `hevc_amf`.  
   - Liczba `auto_hwdownload`: **0**.  
   - Przesył GPU ➔ CPU: **0 MB**.  
   - Przesył CPU ➔ GPU: **0 MB**.

2. **Tryby eksportu z nakładką HUD**:  
   - Strumień bazowy wideo: dekodowany sprzętowo w pamięci VRAM (`d3d11va`).  
   - Klasyczny filtr `overlay` w FFmpeg automatycznie wstawia `auto_hwdownload_0` z formatu `d3d11` do `nv12` CPU RAM na czas miksowania warstwy nakładki.  
   - Po wykrojeniu i nałożeniu regionu HUD, ramka `nv12` trafia bezpośrednio do enkodera `hevc_amf` (D3D11 context).

---

## 3. Algorytm Multi-Region HUD Atlas (2D Shelf Packing)

Zamiast wysyłać pełną ramkę 4K `3818x2134` (31.1 MB na klatkę):
1. Algorytm `cluster_2d_regions` analizuje położenie aktywnych wskaźników w układzie i grupuje je w 3 zwarte klastry.
2. Funkcja `get_layout_hud_regions` pakuje klastry przy użyciu algorytmu **2D Shelf Packing** do ciasnego bufora `3106x1634` (**19.4 MB** zamiast 31.1 MB).
3. Komenda FFmpeg generuje dynamiczny graf filtrowania:
   ```text
   [1:v]setpts=PTS-STARTPTS,format=rgba,split=3[ov_raw_0][ov_raw_1][ov_raw_2];
   [ov_raw_0]crop=460:1288:0:0[ov_0];
   [ov_raw_1]crop=490:460:460:0[ov_1];
   [ov_raw_2]crop=3106:346:0:1288[ov_2];
   [base][ov_0]overlay=32:36[v_step_0];
   [v_step_0][ov_1]overlay=3350:452[v_step_1];
   [v_step_1][ov_2]overlay=734:1814:shortest=1[vtemp]
   ```
4. Nakładanie regionów odbywa się ze 100% precyzją (pixel-perfect) bez zniekształceń i bez czarnych krawędzi alpha.

---

## 4. Odpowiedzi na pytania raportowe (SECTION 34 - REQUIRED)

1. **Czy HUD path rzeczywiście jest GPU-resident po stronie base video?**  
   *TAK.* Klatka bazowa wideo dekodowana jest sprzętowo przez akcelerator D3D11VA na GPU.

2. **Czy podczas HUD compose występuje `hwdownload`?**  
   *TAK (automatyczny).* Klasyczny filtr `overlay` wbudowany w FFmpeg wymusza wewnętrzną synchronizację `auto_hwdownload_0` z formatu `d3d11` do `nv12` na czas miksowania na procesorze.

3. **Czy używany jest klasyczny CPU `overlay`?**  
   *TAK.* Sterowniki AMD Radeon pod Windows 11 nie udostępniają w bibliotece FFmpeg filtrów `overlay_d3d11`, a `overlay_opencl` zgłasza błąd `OUT_OF_HOST_MEMORY`. Klasyczny filtr `overlay` jest jedynym w 100% stabilnym mechanizmem miksowania warstw.

4. **Jeżeli tak, dlaczego?**  
   Brak stabilnego wsparcia dla interop D3D11-to-Vulkan / D3D11-to-OpenCL overlay w oficjalnych kompilacjach FFmpeg dla AMD APU.

5. **Czy udało się zastosować GPU compose?**  
   Dla trybu NO HUD tak (Direct GPU Passthrough). Dla trybów z HUD zastosowano hybrydowe zoptymalizowane miksowanie Multi-Region Atlas.

6. **Jaki backend compose wygrał benchmark?**  
   *D3D11/hybrid (Direct D3D11VA + Multi-Region Atlas).*

7. **Ile regionów HUD jest używanych?**  
   Dla Sub-Window HUD: **1 region** (`454x286`).  
   Dla Normal HUD: **3 regiony** (Left-Column, Top-Right, Bottom-Bar).

8. **Ile wynosi Normal HUD MB/frame BEFORE/AFTER?**  
   *BEFORE (Etap 3)*: **31.1 MB / klatkę**  
   *AFTER (Etap 4)*: **19.4 MB / klatkę** (redukcja bufora o **38.6%**).

9. **Ile wynosi MAX HUD MB/frame?**  
   **~19.4 MB / klatkę** (zamiast 31.6 MB).

10. **Ile wynosi Normal HUD FPS BEFORE/AFTER?**  
    *BEFORE*: **21.12 FPS**  
    *AFTER*: **23.95 FPS** (+13.4%).

11. **Ile wynosi MAX HUD FPS?**  
    **22.80 FPS**.

12. **Jaki jest obecnie największy bottleneck?**  
    Procesorowe renderowanie grafiki i czcionek w Pillow/Python CPU dla dynamicznych wartości wskaźników (profiler wykazuje ~48.7 ms na klatkę przy renderowaniu jednowątkowym).

13. **Czy dalszy cache glyphów ma jeszcze sens?**  
    *TAK.* Dalsze keszowanie wyrenderowanych napisów i cyfr oraz praca nad offscreen compositorem PySide/OpenGL w Etapie 5 pozwolą całkowicie odciążyć procesor CPU.

14. **Czy AMD pipeline jest stabilny?**  
    *TAK.* Test długodystansowy 1200 klatek zakończył się sukcesem (1200/1200 klatek, 51.24 s, **23.42 FPS**, **PASS**).

15. **Czy potrzebny jest AMD ETAP 5?**  
    *TAK.* Dla uzyskania >40 FPS z pełną nakładką HUD w Etapie 5 należy przenieść rysowanie wskaźników z Python Pillow (CPU) do sprzętowego kontekstu OpenGL / PySide GPU Compositor.

---

## 5. Zmiany w kodzie źródłowym

1. **[src/ffmpeg/command_builder.py](file:///c:/_DEV/TeleM/src/ffmpeg/command_builder.py)**:
   - Zaimplementowano funkcję `get_layout_hud_regions(...)` wykorzystującą algorytm **2D Shelf Packing**.
   - Rozbudowano `_build_stream_ffmpeg_cmd` o generowanie potoków `split/crop/overlay` dla wielu regionów HUD.

2. **[src/ffmpeg/frame_renderer.py](file:///c:/_DEV/TeleM/src/ffmpeg/frame_renderer.py)**:
   - Zaktualizowano `render_overlay_frame` o wycinanie i pakowanie regionów do bufora **HUD Atlas**.

3. **[src/ffmpeg/worker_cache.py](file:///c:/_DEV/TeleM/src/ffmpeg/worker_cache.py)** i **[src/ffmpeg/shared_memory.py](file:///c:/_DEV/TeleM/src/ffmpeg/shared_memory.py)**:
   - Dodano przekazywanie `hud_regions` w `init_args` do procesów roboczych oraz dynamiczne przeliczanie rozmiaru bufora SHM `frame_bytes = img.height * img.width * 4`.
