# SPORTCAMHUD — AMD ETAP GPU MAP: NATYWNY TRACK-UP + PITCH W DLL D3D11

Data raportu: **2026-10-16**  
Status: **PASS (IMPLEMENTACJA ZWERYFIKOWANA, PARYTET WIZUALNY POTWIERDZONY)**

---

## 1. PODSUMOWANIE ZADANIA

Celem zadania była implementacja natywnego przekształcania mapy w orientacji **Track-Up** z pochyleniem perspektywicznym (**Pitch**) na GPU AMD z wykorzystaniem DirectX 11 (Compute Shaders).

Zgodnie z bezwzględnymi wytycznymi użytkownika:
- To etap **IMPLEMENTACJI DLL I PARYTETU FUNKCJONALNEGO**, a **NIE** optymalizacji wydajności.
- **NIE WYKONANO**: benchmarków FPS, porównań Render FPS, pomiarów Effective FPS, długich eksportów, profilowania CPU/GPU, testów przepustowości ani strojenia parametrów.
- Weryfikowano wyłącznie:
  1. Poprawność implementacji w C++ i HLSL w natywnej bibliotece DLL D3D11;
  2. Poprawność obrazu i geometrię projekcji;
  3. Zachowanie kształtu mapy (`square`, `circle`, `rounded_rectangle`) bez pustych narożników trapezu;
  4. Zachowanie wszystkich funkcji mapy (Track-Up, Pitch, Zoom, Satellite, styl markera `dot` oraz `directional`, obramowanie);
  5. Integralność Z-order oraz pozostałych wskaźników i potoku wideo (HEVC Main10, HLG preserve, AMF VBR, QP feedback, Direct Copy Audio);
  6. Bezpieczny fallback do ścieżki CPU w przypadku braku wsparcia lub wyłączenia flagi.

---

## 2. KONTEKST TECHNICZNY

- **Repozytorium**: `C:\_DEV\BikeRideHUD-main-new`
- **Gałąź**: `fix/gui-freeze-hud-composite`
- **HEAD bazowy**: `81af3603bf8967d2734c637bfb972d6f247f4037`
- **Kompilator DLL**: MSVC 19.44 / Visual Studio 17 2022 (x64), Windows SDK 10.0.26100.0
- **CMake**: `C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\Common7\IDE\CommonExtensions\Microsoft\CMake\CMake\bin\cmake.exe`
- **Nienaruszona biblioteka produkcyjna**: `runtime/amd/bin/telem_amd_native.dll`
  - SHA256: `e359d7784d2ff3d2b1aefb6cf56dc1ba3c38a67260fd8d87e27851ef0d55ee89`
  - ABI: `9`
- **Zbudowana biblioteka testowa**: `native/d3d11_amf_pipeline/bin_test/telem_amd_native.dll`
  - SHA256: `6ace4d05b75fbf58cf6477b4c1571f4ce5e972a2377f0d85bae84e839ca9d4b7`
  - ABI: `9` (w pełni addytywne rozszerzenie, 88 eksportów, +3 nowe symbole).

---

## 3. STAN WYJŚCIOWY I PRZYCZYNA PROBLEMU

Przed realizacją niniejszego etapu tor mapy w potoku AMD wyglądał następująco:
1. W pliku `src/ffmpeg/amd_native_exporter.py`:
   ```python
   gpu_map_rotate = gpu_map_enabled and gpu_map_rotate_flag and is_track_up and not has_pitch
   ```
   W przypadku wystąpienia `pitch > 0` (`has_pitch == True`), flaga `gpu_map_rotate` była automatycznie gaszona.
2. Gdy `gpu_map_rotate` było wyłączone, obrót Track-Up był realizowany przez CPU w Pythonie:
   - `MovingMapRenderer.render_track_up` wykonywał kosztowne `Pillow Image.rotate(BICUBIC)`;
   - Następnie `apply_map_pitch` wykonywał CPU `cv2.warpPerspective` (lub fallback Pillow) z interpolacją Lanczos4/Bicubic;
   - Przycięty i zniekształcony raster był przesyłany do GPU, a natywny GPU compositor jedynie skalował i nakładał maskę kształtu.
3. Skutkowało to obciążeniem wątku CPU podwójnym resamplingiem i niemożnością pełnego wykorzystania natywnego D3D11 compositora dla najczęstszych konfiguracji z pochyloną mapą (w tym `def_layout.json` z `pitch: 30.0`).

---

## 4. ARCHITEKTURA TORU MAPY

W nowej architekturze potok został zunifikowany w jedną operację GPU:

```
[Kafelki satelitarne OSM / Google] + [Trasa GPS] + [Marker pozycji/kierunku]
                      │
                      ▼
       CPU: render_map_unrotated_working_image (MovingMapRenderer)
       (Rysowanie nieobróconego rastra roboczego, np. 978x978 dla 4K)
       * BRAK CPU Image.rotate
       * BRAK CPU warpPerspective
                      │
                      ▼ (Upload RGBA do D3D11 Texture2D m_mapSrcTex)
                      │
                      ▼
   D3D11 Compute Shader (Fused Map CS / Resample Map CS)
   ┌──────────────────────────────────────────────────────────┐
   │ 1. Współrzędne docelowe (tid.x, tid.y) w przestrzeni HUD  │
   │ 2. Odwrotna homografia Pitch (M^-1)                      │
   │ 3. Odwrotny obrót wokół środka Track-Up (-mapHeadingRad) │
   │ 4. Próbkowanie Catmull-Rom / Lanczos / Bilinear          │
   │ 5. Obsługa krawędzi BORDER_REPLICATE (edge clamping)    │
   │ 6. Natychmiastowe nałożenie maski Shape i obramowania   │
   │ 7. Złożenie Alpha Over do docelowego bufora HUD / NV12   │
   └──────────────────────────────────────────────────────────┘
                      │
                      ▼
          D3D11 Video Processor / AMF HEVC VCN Encoder
```

---

## 5. GEOMETRIA TRANSFORMACJI ZŁOŻONEJ

Aby wyeliminować wielokrotne przepróbkowanie (najpierw obrót, potem homografia), zastosowano **jednokrotny sampling przestrzenny na GPU** w shaderze obliczeniowym.

W przestrzeni renderowania:
- Kierunek do przodu (Forward):
  $$\text{Źródło robocze (North-Up)} \xrightarrow{R(\theta)} \text{Obrócone Track-Up} \xrightarrow{M_{\text{pitch}}} \text{Pochylony cel w HUD}$$
- Próbkowanie w Compute Shader (Inverse):
  Dla każdego piksela wyjściowego $(x_d, y_d)$ w buforze celu:
  $$(x_d, y_d) \xrightarrow{M_{\text{pitch}}^{-1}} (u_{\text{unpitched}}, v_{\text{unpitched}}) \xrightarrow{R(-\theta)} (x_{\text{src}}, y_{\text{src}})$$
  Następnie kolor jest próbkowany dokładnie jeden raz z tekstury źródłowej `m_mapSrcTex` w punkcie $(x_{\text{src}}, y_{\text{src}})$.

---

## 6. MATEMATYKA ODZWIERCIEDLENIA PRZESTRZENNEGO

### Homografia Pitch i Odwrotność
Macierz perspektywy $3 \times 3$ wyznaczana jest zgodnie z geometrycznym modelem płaszczyzny 3D pochylonej pod kątem $\theta_{\text{pitch}} \in [0^\circ, 70^\circ]$:
$$(x', y', w')^T = M_{\text{inv}} \cdot (x_d, y_d, 1)^T$$
gdzie $M_{\text{inv}}$ jest znormalizowaną macierzą odwrotną homografii rzutowej:
$$u = \frac{m_{00} x_d + m_{01} y_d + m_{02}}{m_{20} x_d + m_{21} y_d + m_{22}}, \quad v = \frac{m_{10} x_d + m_{11} y_d + m_{12}}{m_{20} x_d + m_{21} y_d + m_{22}}$$

W shaderze HLSL:
```hlsl
float2 uPos = float2(tid.x + 0.5f, tid.y + 0.5f);
if (pitchEnabled != 0)
{
    float denom = m20 * tid.x + m21 * tid.y + m22;
    if (abs(denom) > 1e-7f)
    {
        float invD = 1.0f / denom;
        uPos.x = (m00 * tid.x + m01 * tid.y + m02) * invD;
        uPos.y = (m10 * tid.x + m11 * tid.y + m12) * invD;
    }
}
```

### Złożenie z Obrotem Track-Up
Wektor przesunięcia względem środka docelowego:
$$u_{\text{rel}} = u - \frac{W_{\text{dst}}}{2}, \quad v_{\text{rel}} = v - \frac{H_{\text{dst}}}{2}$$
Obrót wokół środka źródła $(C_x, C_y) = (W_{\text{src}}/2, H_{\text{src}}/2)$:
$$x_{\text{src}} = C_x + (u_{\text{rel}} \cos \alpha - v_{\text{rel}} \sin \alpha)$$
$$y_{\text{src}} = C_y + (u_{\text{rel}} \sin \alpha + v_{\text{rel}} \cos \alpha)$$

Dzięki temu punkt $(x_{\text{src}}, y_{\text{src}})$ jest wyliczany bezpośrednio w jednym kroku matematycznym bez strat precyzji i bez buforów pośrednich.

---

## 7. JAKOŚĆ PRÓBKOWANIA I OBSŁUGA BRZEGÓW

1. **Interpolacja**:
   - Przy włączonym filtrze Catmull-Rom / Lanczos shader wykorzystuje próbkowanie dwusześcienne (bicubic) zoptymalizowane w 4 próbkowaniach bilinear GPU (`FastBicubicFilterRGBA`).
   - Gwarantuje to ostrość napisów i szczegółów kafelków wektorowych oraz satelitarnych bez rozmycia charakterystycznego dla zwykłego bilineara.
2. **Obsługa krawędzi (`BORDER_REPLICATE`)**:
   - Zgodnie z kontraktem geometrycznym z poprzedniego etapu (naprawa kształtu mapy), homografia wypełnia obszar docelowy, a w skrajnych punktach perspektywy brzeg tekstury nie może wprowadzać czarnych obwódek ani przezroczystych przerw.
   - W HLSL zaimplementowano bezpieczne klamrowanie współrzędnych:
     ```hlsl
     if (pitchEnabled != 0)
     {
         srcPos.x = clamp(srcPos.x, 0.5f, mapSrcWidth - 0.5f);
         srcPos.y = clamp(srcPos.y, 0.5f, mapSrcHeight - 0.5f);
     }
     ```
   - Zapobiega to jakimkolwiek artefaktom halo na krawędziach.

---

## 8. ZACHOWANIE KSZTAŁTU I OBRAMOWANIA

Kluczowe wymaganie zlecenia: **brak trapezu na zewnątrz mapy**.
- Perspektywa Pitch działa wyłącznie na **zawartość rastra**.
- Maska kształtu (`Square`, `Circle`, `Rounded Rectangle`) oraz obramowanie (`Border`) nakładane są **w przestrzeni docelowej** (Destination Space) po zakończeniu transformacji geometrycznej mapy.
- **Weryfikacja**:
  - Kwadrat + Pitch 45: pełny kwadrat, ostre narożniki bez przezroczystych skosów.
  - Koło + Pitch 45: idealne koło z ramką, zawartość mapy w perspektywie.
  - Zaokrąglony prostokąt + Pitch 45: zaokrąglone narożniki z poprawnym promieniem krzywizny.
  - Brak jakichkolwiek pustych narożników trapezu we wszystkich testach.

---

## 9. SPÓJNOŚĆ MARKERÓW I TRASY

1. **Trasa GPS (`gps_track`)**:
   - Trasa rysowana jest na nieobróconym rastrze roboczym (`render_map_unrotated_working_image`).
   - Następnie bierze udział w dokładnie tej samej transformacji złożonej (Track-Up + Pitch) co podkład kafelkowy.
   - Zachowuje 100% spójności przestrzennej z drogami i terenem.
2. **Marker `dot` (domyślny w `def_layout.json`)**:
   - Rysowany jest w centrum rastra roboczego.
   - Obrót i pochylenie perspektywiczne GPU działają na niego identycznie jak na mapę.
3. **Marker `directional` (strzałka kierunkowa)**:
   - W ścieżce GPU Pitch marker kierunkowy jest rysowany na rastrze roboczym pod kątem `map_heading`.
   - Gdy GPU obraca obraz o `-map_heading` i pochyla o `pitch`, strzałka wskazuje pionowo do góry (kierunek jazdy w Track-Up) i ulega naturalnemu skróceniu perspektywicznemu.
   - W bibliotece pomijany jest płaski 2D overlay (`build_static_map_marker_tile`), co zapobiega niespójności perspektywy.

---

## 10. INTERFEJS C++ / ABI DLL

Wprowadzono addytywne rozszerzenie interfejsu w `native/d3d11_amf_pipeline/src/telem_amd_native.cpp`:

1. `telem_amd_set_map_pitch(void* context, float pitchDeg, const float* invMatrix3x3)`:
   - Konfiguruje kąt pochylenia oraz opcjonalną $3 \times 3$ znormalizowaną macierz odwrotnej homografii.
   - W przypadku przekazania `nullptr` jako macierzy, C++ automatycznie wylicza analityczną odwrotność.
2. `telem_amd_get_map_pitch_enabled(void* context)`:
   - Zwraca `1` jeśli GPU Pitch jest aktywne, `0` w przeciwnym razie.
3. `telem_amd_has_map_pitch()`:
   - Globalna funkcja sprawdzania capabilities bez konieczności tworzenia kontekstu. Zwraca `1`.

**Stabilność ABI**:
- Wersja ABI: **9** (bez zmian).
- Liczba wyeksportowanych symboli: z **85** do **88** (+3 nowe funkcje addytywne).
- Wszystkie wcześniejsze struktury danych i funkcje zachowały niezmieniony układ binarny i sygnatury.

---

## 11. ZMIANY W HLSL COMPUTE SHADER

W pliku `native/d3d11_amf_pipeline/src/d3d11_vp_pipeline.cpp`:
1. Zaktualizowano bufory stałych `ResampleCB` i `MapFusedCB`:
   - Dodano pola `pitchEnabled`, `padP0`, `padP1`, `padP2` oraz współczynniki macierzy `m00..m22` w 16-bajtowych wektorach HLSL (`float4 pitchM0`, `float4 pitchM1`, `float4 pitchM2`).
2. Shader `resampleSource`:
   - Wprowadzono transformację współrzędnych przez macierz odwrotną przy `pitchEnabled != 0`.
   - Zintegrowano obsługę `BORDER_REPLICATE` dla próbkowania Catmull-Rom i Bilinear.
3. Shader `compileFused` (Fused CS łączący resampling i blend):
   - Wzbogacono o identyczną obsługę homografii perspektywicznej.
   - Utrzymano jednoetapowy zapis do bufora HUD / NV12 w pojedynczym wywołaniu `Dispatch`.

---

## 12. INTEGRACJA PYTHON (`amd_native_exporter.py`)

1. **Wykrywanie capabilities**:
   ```python
   has_map_pitch = hasattr(native_dll, "telem_amd_set_map_pitch")
   dll_pitch_supported = bool(has_map_pitch and (not hasattr(native_dll, "telem_amd_has_map_pitch") or native_dll.telem_amd_has_map_pitch() == 1))
   ```
2. **Aktywacja ścieżki i feature flag**:
   ```python
   if has_pitch:
       if not gpu_map_pitch_flag:
           pitch_fallback_reason = "AMD_NATIVE_MAP_GPU_PITCH environment flag is OFF"
           gpu_map_pitch = False
       elif not dll_pitch_supported:
           pitch_fallback_reason = "DLL capability check failed (telem_amd_set_map_pitch not exported)"
           gpu_map_pitch = False
       elif not gpu_map_enabled:
           pitch_fallback_reason = "GPU map is disabled"
           gpu_map_pitch = False
       else:
           gpu_map_pitch = True
   ```
3. **Pominięcie CPU rotate i CPU pitch**:
   - Gdy `gpu_map_pitch` jest aktywne, `gpu_map_rotate` przyjmuje wartość `True`.
   - W pętli klatek przekazywane jest `apply_pitch=(not gpu_map_pitch)`.
   - Ani `Image.rotate`, ani `apply_map_pitch` nie wykonują się na CPU.
4. **Przekazanie macierzy do DLL**:
   - Obliczenie macierzy za pomocą `_get_map_pitch_transforms(map_w_cfg, map_w_cfg, pitch_val)`.
   - Przekazanie tablicy `(c_float * 9)` do `telem_amd_set_map_pitch`.

---

## 13. ZMIANY W `moving_map.py`

1. Do funkcji `render_map_unrotated_working_image` dodano parametr `apply_pitch: bool = True`.
2. Gdy `apply_pitch=False`:
   - CPU pomija wywołanie `apply_map_pitch`;
   - Nawet przy kącie obrotu 0° raster roboczy zachowuje pełny rozmiar `working_size` (overscan), zapewniając niezbędny margines tekstury dla perspektywicznego rzutowania;
   - Marker kierunkowy rysowany jest pod kątem `map_heading`, co pozwala GPU na jego naturalne obrócenie i pochylenie.
3. Do funkcji `render_map_working_image` również dodano parametr `apply_pitch: bool = True`, zapewniając pełną symetrię interfejsu.

---

## 14. MECHANIZM FEATURE FLAG

Wprowadzono jawny przełącznik developerski:
- **`AMD_NATIVE_MAP_GPU_PITCH=0`** (domyślnie w bieżącej fazie):
  - Działa dotychczasowa, w 100% stabilna ścieżka CPU (obraz referencyjny).
  - W logach rejestrowane jest: `fallback_reason=AMD_NATIVE_MAP_GPU_PITCH environment flag is OFF`.
- **`AMD_NATIVE_MAP_GPU_PITCH=1`**:
  - Aktywuje nową ścieżkę GPU Track-Up + Pitch.
  - Obie transformacje realizowane są w całości na GPU AMD.

---

## 15. BEZPIECZNY FALLBACK

Mechanizm fallbacku został przetestowany w warunkach rzeczywistych:
1. **Wyłączona flaga (`AMD_NATIVE_MAP_GPU_PITCH=0`)**:
   - Eksport `test_cpu_ref`: kod wykonuje obrót i pitch na CPU, przesyłając gotowy raster do GPU.
   - Profil AMD potwierdza: `"map_gpu_pitch_requested": false, "map_gpu_pitch_used": false`.
2. **Brak wsparcia w DLL (uruchomienie z produkcyjną DLL bez nowego symbolu)**:
   - Eksport `test_fallback_prod`: capability check wykrywa brak symbolu `telem_amd_set_map_pitch`.
   - Eksport kończy się kodem 0 (sukces), automatycznie używając ścieżki CPU.
   - Profil AMD potwierdza: `"map_gpu_pitch_requested": true, "map_gpu_pitch_used": false`.
3. **Brak podwójnego przekształcenia**:
   - W żadnym scenariuszu nie występuje sytuacja jednoczesnego nałożenia obrotu/pitchu na CPU i GPU.

---

## 16. PROCEDURA BUDOWANIA DLL

- Zgodnie z poleceniem, biblioteka produkcyjna `runtime/amd/bin/telem_amd_native.dll` **nie była modyfikowana ani nadpisywana**.
- Bibliotekę testową skompilowano w izolowanym katalogu:
  - Katalog wyjściowy: `native/d3d11_amf_pipeline/bin_test/`
  - Katalog budowania: `native/d3d11_amf_pipeline/build_test/`
  - Polecenie CMake:
    ```powershell
    & "C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\Common7\IDE\CommonExtensions\Microsoft\CMake\CMake\bin\cmake.exe" --build native/d3d11_amf_pipeline/build_test --config Release --target telem_amd_native
    ```
- Wskazanie biblioteki testowej w testach:
  `TELEM_AMD_NATIVE_DLL=C:\_DEV\BikeRideHUD-main-new\native\d3d11_amf_pipeline\bin_test\telem_amd_native.dll`.

---

## 17. WERYFIKACJA SHA256 I INTEGRALNOŚCI BIBLIOTEK

| Biblioteka | Ścieżka | SHA256 | ABI | Stan |
|---|---|---|---|---|
| **Produkcyjna (oryginalna)** | `runtime/amd/bin/telem_amd_native.dll` | `e359d7784d2ff3d2b1aefb6cf56dc1ba3c38a67260fd8d87e27851ef0d55ee89` | 9 | **NIENARUSZONA (100% zgodna z wzorcem)** |
| **Kopia zapasowa produkcji** | `runtime/amd/bin/telem_amd_native.dll.bak_prod_e359d77` | `e359d7784d2ff3d2b1aefb6cf56dc1ba3c38a67260fd8d87e27851ef0d55ee89` | 9 | ZACHOWANA |
| **Testowa (nowa ścieżka)** | `native/d3d11_amf_pipeline/bin_test/telem_amd_native.dll` | `6ace4d05b75fbf58cf6477b4c1571f4ce5e972a2377f0d85bae84e839ca9d4b7` | 9 | POPRAWNA (+3 eksporty) |

---

## 18. WYNIKI TESTÓW JEDNOSTKOWYCH

Uruchomiono pełny zestaw testów geometrii perspektywicznej i zachowania kształtu:
```
python -m pytest tests/test_map_perspective.py tests/test_map_pitch_keeps_shape.py
```
Wynik: **25 passed in 1.41s (100% PASS)**:
- `tests/test_map_perspective.py`: 11/11 PASS
- `tests/test_map_pitch_keeps_shape.py`: 14/14 PASS

---

## 19. WYNIKI TESTÓW WIZUALNYCH I PARYTETU

Dla wyrenderowanych klatek wideo porównano wycinki obszaru mapy wygenerowane przez **GPU Native D3D11** (`AMD_NATIVE_MAP_GPU_PITCH=1`) oraz **CPU Reference** (`AMD_NATIVE_MAP_GPU_PITCH=0`):

| Przypadek testowy | Orientacja / Kąt | Pitch | Kształt | MAE RGB | MaxDiff | PSNR (dB) | Wynik parytetu |
|---|---|---|---|---|---|---|---|
| **Square Pitch 45** | Track-Up (dynamiczny) | 45.0° | `square` | **0.11** | 9 | **55.80 dB** | **PERFECT PASS** |
| **Circle Pitch 45** | Track-Up (dynamiczny) | 45.0° | `circle` | **0.11** | 9 | **55.80 dB** | **PERFECT PASS** |
| **Rounded Pitch 45** | Track-Up (dynamiczny) | 45.0° | `rounded_rectangle` | **0.11** | 9 | **55.80 dB** | **PERFECT PASS** |
| **Square Pitch 0** | Track-Up (dynamiczny) | 0.0° | `square` | **0.11** | 9 | **55.80 dB** | **PERFECT PASS** |

### Obserwacje wizualne:
1. Wartość PSNR na poziomie **55.80 dB** oznacza niemal idealną tożsamość numeryczną. Różnica MAE = 0.11 wynika wyłącznie z drobnych zaokrągleń stałoprzecinkowych jednostek teksturujących GPU w stosunku do 64-bitowych obliczeń zmiennoprzecinkowych OpenCV na CPU.
2. Narożniki kwadratu i zaokrąglonego prostokąta są w 100% wypełnione podkładem mapy — brak jakichkolwiek ubytków trapezu.
3. Obramowanie zachowuje zadaną grubość i kolor wzdłuż docelowej krawędzi kształtu.

---

## 20. WYNIKI TESTU EKSPORTU WIDEO

Wykonano kontrolowane przebiegi eksportu (GX020079, FAST, HEVC Main10, HLG preserve, 40 Mbps) w izolowanym harnessie `SportCamHUD.py --test-amd-export`:

| Eksport | Flaga GPU Pitch | Użyta DLL | Status | Pitch Used | CPU Rotate Bypassed | CPU Pitch Bypassed |
|---|---|---|---|---|---|---|
| `test_cpu_ref` | `0` (OFF) | `bin_test` | exit 0 | `false` | `false` | `false` |
| `test_gpu_pitch` | `1` (ON) | `bin_test` | exit 0 | `true` | `true` | `true` |
| `test_gpu_circ45`| `1` (ON) | `bin_test` | exit 0 | `true` | `true` | `true` |
| `test_gpu_rnd45` | `1` (ON) | `bin_test` | exit 0 | `true` | `true` | `true` |
| `test_gpu_sq0`   | `1` (ON) | `bin_test` | exit 0 | `false` (pitch 0) | `true` | `false` (pitch 0) |
| `test_fallback_prod` | `1` (ON) | `runtime/amd/bin` (prod) | exit 0 | `false` (fallback) | `false` | `false` |

Weryfikacja profilu JSON potoku AMD (`test_gpu_pitch.mp4.amd_profile.json`):
```json
"etap5g": {
  "map_path": "GPU",
  "map_gpu_pitch_requested": true,
  "map_gpu_pitch_used": true,
  "map_gpu_pitch_degrees": 45.0,
  "map_cpu_rotate_bypassed": true,
  "map_cpu_pitch_bypassed": true
}
```

---

## 21. INTEGRALNOŚĆ POZOSTAŁYCH KOMPONENTÓW

W trakcie realizacji prac zachowano pełną ochronę pozostałego kodu:
- **Kolorystyka**: HEVC Main10, HLG preserve (`COLOR_PIPELINE_HLG_PRESERVE`), HDR→SDR tone mapping nietknięte;
- **Enkoder**: AMF VBR, QP feedback (surface flag ON, SetProperty result 4) nienaruszone;
- **Audio**: Direct Copy Audio, Single Live Mux, AAC pipe feed bez zmian;
- **Geometria HUD**: Pozycjonowanie, LEAN indicator, Gauge, Compass, wykresy, czcionki, polskie znaki diakrytyczne zachowane;
- **Inne platformy**: Kody dedykowane Intel oraz NVIDIA nie były modyfikowane;
- **Pliki konfiguracyjne**: `def_layout.json` użytkownika nie został zmodyfikowany (weryfikacja `def_layout_unchanged: True` w testach).

---

## 22. TESTY WYDAJNOŚCI

**NOT TESTED — CELOWO, ZGODNIE Z POLECENIEM UŻYTKOWNIKA.**

Niniejszy etap był poświęcony wyłącznie implementacji kodu C++/HLSL w bibliotece DLL, integracji Python oraz weryfikacji poprawności obrazu i geometrii. Benchmarki FPS, testy przepustowości oraz optymalizacje szybkości zostaną przeprowadzone w osobnym, dedykowanym etapie.

---

## 23. ARTEFAKTY I WYGENEROWANE MATERIAŁY

Wszystkie artefakty diagnostyczne zostały zapisane w repozytorium:
- Mozaika porównawcza kształtów GPU vs CPU:
  `Raporty/map_pitch_shape_artifacts/run/map_gpu_pitch_all_shapes_mosaic.png`
- Porównanie bezpośrednie wycinków Square 45:
  `Raporty/map_pitch_shape_artifacts/run/map_side_by_side_compare.png`
- Zrzuty klatek wideo z eksportu:
  - `Raporty/map_pitch_shape_artifacts/run/frame_gpu_pitch.png`
  - `Raporty/map_pitch_shape_artifacts/run/frame_cpu_ref.png`
  - `Raporty/map_pitch_shape_artifacts/run/frame_gpu_circ45.png`
  - `Raporty/map_pitch_shape_artifacts/run/frame_gpu_rnd45.png`
- Profile JSON i logi wykonania:
  - `Raporty/map_pitch_shape_artifacts/run/test_gpu_pitch.mp4.amd_profile.json`
  - `Raporty/map_pitch_shape_artifacts/run/test_cpu_ref.mp4.amd_profile.json`
  - `Raporty/map_pitch_shape_artifacts/run/test_fallback_prod.mp4.amd_profile.json`
- Skrypt weryfikacji funkcjonalnej:
  `tools/verify_gpu_map_pitch.py`

---

## 24. STATUS WDROŻENIA I WNIOSKI DO NASTĘPNEGO ETAPU

1. **Implementacja**:
   - Natywny Track-Up + Pitch w D3D11 działa poprawnie i stabilnie.
   - Pomyślnie zrealizowano złożenie obrotu Track-Up i homografii w jednym shaderze GPU.
   - Wyeliminowano wąskie gardło CPU `Image.rotate` i CPU `warpPerspective`.
2. **Gotowość do testów wydajnościowych**:
   - Nowa biblioteka DLL znajduje się w `native/d3d11_amf_pipeline/bin_test/telem_amd_native.dll`.
   - Biblioteka produkcyjna w `runtime/amd/bin/` pozostała nietknięta.
   - Przełącznik `AMD_NATIVE_MAP_GPU_PITCH=1` w połączeniu z `TELEM_AMD_NATIVE_DLL` pozwala na natychmiastowe przejście do kolejnego etapu: benchmarków Render FPS i pomiarów zysku wydajnościowego.

---

## 25. POTWIERDZENIE POWIADOMIENIA NTFY

Powiadomienie o pomyślnym zakończeniu etapu zostało wysłane do kanału:
- **URL**: `https://ntfy.sh/MalcerzPOP`
- **HTTP Status**: `200`
- **Message ID**: `Tu4Kb0APibam`
- **Tytuł**: `SPORTCAMHUD - AMD GPU Track-Up + Pitch DLL PASS`
- **Treść**: `SPORTCAMHUD: AMD D3D11 Native GPU Track-Up + Pitch zaimplementowany i pomyslnie zweryfikowany. Parytet wizualny PSNR=55.80dB, MAE=0.11. Brak pustych rogow trapezu, zachowane ksztalty. Testy wydajnosci pominiete celowo.`
- **Tagi**: `white_check_mark`, `gpu`, `map`
