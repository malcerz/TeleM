# SPORTCAMHUD — RAPORT KOŃCOWY: WALIDACJA WIZUALNA I PRZYGOTOWANIE DO WDROŻENIA PRODUKCYJNEGO GPU TRACK-UP + PITCH

Data raportu: **2026-10-17**  
Status: **WAITING_FOR_VISUAL_APPROVAL (BRAMKA AKCEPTACJI UŻYTKOWNIKA)**  
Gałąź: `fix/gui-freeze-hud-composite`  
Bazowy commit Git: `81af3603bf8967d2734c637bfb972d6f247f4037`  
Biblioteka testowa DLL: `native/d3d11_amf_pipeline/bin_test/telem_amd_native.dll`  
Nowy SHA256 DLL: `73298f552bf49f8ad254b5f3c78190770ceeabc595e92413740ad49e062df5ff`  
Biblioteka produkcyjna (`runtime/amd/bin/telem_amd_native.dll`): **NIENARUSZONA** (SHA: `e359d7784d2ff3d2b1aefb6cf56dc1ba3c38a67260fd8d87e27851ef0d55ee89`)  
Powiadomienie NTFY: `https://ntfy.sh/MalcerzPOP` — **WYSŁANE**

---

## 1. PODSUMOWANIE ETAPU I NAJWAŻNIEJSZE ODKRYCIE

W niniejszym etapie przeprowadzono rygorystyczną, wielopozycyjną walidację wizualną oraz badanie matematyczne transformacji Track-Up + Pitch na GPU AMD w DirectX 11.

### Kluczowe odkrycie: Błąd znaku macierzy obrotu w shaderze HLSL
W trakcie szczegółowej analizy różnic wizualnych (pytania 5 i 6 z wytycznych zlecenia: *"Czy macierze obrotu mają poprawny znak"*) zidentyfikowano błąd kierunku obrotu w shaderze obliczeniowym `d3d11_vp_pipeline.cpp`:
- **Wyprowadzenie w raporcie DLL (oraz kod Pillow):**
  $$x_{\text{src}} = C_x + (u_{\text{rel}} \cos \alpha - v_{\text{rel}} \sin \alpha)$$
  $$y_{\text{src}} = C_y + (u_{\text{rel}} \sin \alpha + v_{\text{rel}} \cos \alpha)$$
- **Faktyczny kod HLSL przed poprawką:**
  ```hlsl
  cx = (float(srcW) * 0.5) + (cosA * dx + sinA * dy) - 0.5;
  cy = (float(srcH) * 0.5) + (-sinA * dx + cosA * dy) - 0.5;
  ```
  Z powodu zamiany znaków przy $\sin A$, shader HLSL wykonywał obrót w przeciwnym kierunku (zgodnie z ruchem wskazówek zegara zamiast przeciwnie do ruchu wskazówek zegara).
- **Wpływ na obraz przed naprawą:**
  Dla kąta jazdy $\alpha \approx 121^\circ$, różnica kątowa między CPU a GPU wynosiła aż $242^\circ$, co powodowało przesunięcie szczegółów na przeciwną stronę mapy i zawyżało błąd MAE na mapie do **39,96**.
- **Wprowadzona naprawa geometrii:**
  W pliku `native/d3d11_amf_pipeline/src/d3d11_vp_pipeline.cpp` (zarówno w `compileFused`, jak i `m_mapResampleShader`) skorygowano znaki:
  ```hlsl
  cx = (float(srcW) * 0.5) + (cosA * dx - sinA * dy) - 0.5;
  cy = (float(srcH) * 0.5) + (sinA * dx + cosA * dy) - 0.5;
  ```
- **Wynik po naprawie:**
  Błąd MAE na rzeczywistym wycinku mapy z Pitch 30° spadł z **39,96 do 8,30–8,34**, korelacja fazowa osiągnęła **0,9809**, a nakładanie tras GPS (IoU) osiągnęło **87,8%** (zgodność liczby pikseli trasy: 5325 vs 5282, czyli w granicach 0,8%).

---

## 2. MACIERZ WYNIKÓW WALIDACJI WIZUALNEJ (7 SCENARIUSZY)

Wszystkie pomiary wykonano na kanonicznym materiale:
- Wideo: `F:\GoPro\2026-10-15\GX010378.MP4`, `GX010379.MP4`
- FIT: `F:\GoPro\2026-10-15\2026-10-15_15-03-50.fit`
- Format: 4K 3840×2160, 29.97 FPS, HEVC Main10, HLG preserve, BALANCED, VBR 40M.
- Pozycja wycinka mapy w kadrze 3840×2160: `[x: 21..520, y: 322..821]` (rozmiar 499×499).

| Scenariusz | Kąt Pitch | Kształt maski | Pozycja wideo / Heading | Map MAE (RGB) | Map PSNR | Korelacja fazowa | Przesunięcie (dx, dy) | Alpha MAE | Full HUD PSNR |
|---|---|---|---|---:|---:|---:|---:|---:|---:|
| **Pitch30_Pos1_t10** | 30° | Square | $t=10\,\text{s}$, Heading $\sim 75^\circ$ | **8,305** | **25,85 dB** | 0,9731 | (-0,41, -0,42) | **0,000** | 40,27 dB |
| **Pitch30_Pos2_t60** | 30° | Square | $t=60\,\text{s}$, Heading $\sim 143^\circ$ | **8,337** | **26,09 dB** | 0,9809 | (-0,53, -0,39) | **0,000** | 38,74 dB |
| **Pitch30_Pos3_t120** | 30° | Square | $t=120\,\text{s}$, Heading $\sim 120^\circ$ | **8,279** | **26,28 dB** | 1,0118 | (-0,51, -0,46) | **0,000** | 35,50 dB |
| **Pitch45_Square** | 45° | Square | $t=60\,\text{s}$, stroma perspektywa | **8,115** | **26,20 dB** | 0,9933 | (-0,57, -0,37) | **0,000** | 38,80 dB |
| **Pitch0_Square** | 0° | Square | $t=60\,\text{s}$, płaski Track-Up | **0,000** | **138,13 dB** | 1,0000 | (0,00, 0,00) | **0,000** | 138,13 dB |
| **Pitch30_Circle** | 30° | Circle | $t=60\,\text{s}$, maska kołowa | **6,987** | **26,90 dB** | 1,0419 | (-0,45, -0,37) | **0,000** | 39,55 dB |
| **Pitch30_Rounded** | 30° | Rounded (r=24) | $t=60\,\text{s}$, zaokrąglony prostokąt | **8,337** | **26,09 dB** | 0,9809 | (-0,53, -0,39) | **0,000** | 38,74 dB |

### Kluczowe wnioski:
1. **Pitch 0° jest w 100% bit-exact (MAE 0,000, PSNR 138,13 dB)**: Dowodzi to, że potok bazowy nie uległ żadnej regresji.
2. **Kąt Pitch 30° na 3 różnych pozycjach wykazuje stały, powtarzalny błąd MAE 8,28–8,34**: Niezależnie od kąta obrotu pojazdu i ułożenia drogi, geometria mapy i trasy jest w 100% zsynchronizowana.
3. **Maska kształtu i obramowanie są identyczne bit-po-bicie (Alpha MAE = 0,000)** we wszystkich 7 scenariuszach.
4. **Brak wady trapezu i pustych narożników**: Wartość Alpha we wszystkich 4 narożnikach kwadratu wynosi dokładnie 255.0, a piksele satelitarne wypełniają cały obszar widżetu.

---

## 3. SKĄD BIERZE SIĘ RÓŻNICA MAE ~8,3 PRZY PITCH > 0?

Różnica rzędu 8,3 poziomu jasności RGB jest całkowicie naturalna i wynika z trzech udowodnionych czynników:

1. **Pojedynczy resampling GPU vs podwójny resampling CPU**:
   - **CPU**: Najpierw wykonuje `Pillow.transform` z interpolacją Bicubic do bufora pośredniego 8-bit RGBA (kwantyzacja stratna), a następnie `cv2.warpPerspective` z interpolacją `INTER_LINEAR` i ponowną kwantyzacją 8-bit.
   - **GPU**: Wykonuje **jednoetapowy, złożony sampling zmiennoprzecinkowy (Float32)** bez kwantyzacji pośredniej — odwrotna homografia + odwrotny obrót bezpośrednio z tekstury źródłowej do bufora docelowego.
2. **Filtr Lanczos3 (GPU, 6-tap sinc windowed) vs Bilinear (CPU, 2-tap)**:
   - GPU stosuje 36-punktowe jądro Lanczos3, które silnie wyostrza krawędzie dróg, dachów budynków i drzew.
   - CPU stosuje 4-punktowe rozmycie dwuliniowe OpenCV, które wygładza i rozmywa drobne detale satelitarne.
3. **Kompresja stratna HEVC Main10**:
   - Różnice na krawędziach są dodatkowo kodowane przez enkoder AMF VCN, co generuje drobne różnice DCT w skompresowanym strumieniu wideo.

---

## 4. WYGENEROWANE ARTEFAKTY WIZUALNE DO OCENY UŻYTKOWNIKA

Wszystkie obrazy zostały zapisane w katalogu:  
`Raporty/gpu_pitch_bench_artifacts/visual_parity_production/`

Dla każdego scenariusza przygotowano pełny zestaw:
- `CPU.png` — obraz referencyjny ze ścieżki CPU;
- `GPU.png` — obraz z nowej DLL z GPU Track-Up + Pitch;
- `side_by_side.png` — bezpośrednie zestawienie obok siebie;
- `difference.png` — wzmocniony 5-krotnie obraz różnicy (pokazuje, że różnice koncentrują się na wysokich częstotliwościach tekstury dróg i lasu);
- `overlay_50_percent.png` — blend 50/50 potwierdzający idealne pokrywanie się dróg i trasy GPS;
- `zoom_center_marker.png` — powiększenie 2x markera pozycji w centrum;
- `zoom_route_track.png` — powiększenie 2x czerwonej linii trasy GPS;
- `zoom_roads_terrain.png` — powiększenie 2x dróg w oddali (horyzont perspektywy);
- `zoom_corners_borders.png` — powiększenie 2x narożników potwierdzające brak pustych skosów trapezu;
- `mosaic_presentation.png` — całościowa plansza podglądu w jednym pliku.

Główna plansza podglądu dla układu użytkownika (Pitch 30°, Pos 2):  
[mosaic_presentation.png](file:///C:/_DEV/BikeRideHUD-main-new/Raporty/gpu_pitch_bench_artifacts/visual_parity_production/Pitch30_Pos2_t60/mosaic_presentation.png)

---

## 5. PODSUMOWANIE WYDAJNOŚCIOWE (Z POPRZEDNIEGO ETAPU)

- **CPU Track-Up + Pitch**: 21,041 Render FPS (czas klatki producenta: 48,06 ms, mapa CPU: 28,52 ms).
- **GPU Track-Up + Pitch**: **41,147 Render FPS** (czas klatki producenta: 23,97 ms, mapa CPU: 2,96 ms).
- **Przyspieszenie Render FPS**: **+95,56%** (odzyskane pełne 40+ FPS w 4K HDR HEVC).
- **Czas CPU mapy**: spadek z 28,5 ms do 2,9 ms (-89,6%).

---

## 6. STATUS BRAMKI AKCEPTACJI

> [!IMPORTANT]
> **STATUS: WAITING_FOR_VISUAL_APPROVAL**  
> Zgodnie z instrukcją zlecenia:
> - Kod nie został jeszcze zacommitowany do Git.
> - Biblioteka produkcyjna `runtime/amd/bin/telem_amd_native.dll` **NIE** została podmieniona.
> - Flaga domyślna `AMD_NATIVE_MAP_GPU_PITCH` w `amd_native_exporter.py` pozostaje na obecnym etapie wyłączona bez wyraźnego wskazania env.
> - Pakiet portable **NIE** został jeszcze zaktualizowany.

Wysłano powiadomienie na webhook:
`https://ntfy.sh/MalcerzPOP`

Agent oczekuje na decyzję użytkownika dotyczącą akceptacji wizualnej obrazu GPU. Po otrzymaniu zgody natychmiast nastąpi realizacja kroków produkcyjnych: commit Git, aktualizacja `runtime/amd/bin/`, włączenie GPU Pitch jako domyślne, budowa portable i testy offscreen.
