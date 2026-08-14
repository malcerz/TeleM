# TeleM — AMD ETAP 2 — raport końcowy

## Wynik

**ETAP 2: PASS.** CPU `BlendRGBAToNV12()` został całkowicie pominięty w trybie `GPU_HUD`, realny HUD jest składany na GPU, pełny eksport zakończył się bilansem **1131/1131**, bez błędów i utraconych zgłoszeń AMF. Ścieżka `CPU_REFERENCE` pozostała dostępna jako jawny reference/fallback.

Nie zmieniono dekodera FFmpeg, uploadu bazowego NV12, generowania HUD przez Pillow, telemetrii, ustawień AMF ani backendów NVIDIA/Intel.

## Wybrany compositor

**GPU compositor selected: OTHER — direct planar NV12 compute shader.**

Przed implementacją sprawdzono istniejące `CreateHUDTexture()`, `m_hudTexture`, `m_hudInputView`, historyczne użycie VP Stream 1, `d3d11_hud_bridge`, pixel-shader PoC oraz stary compute-shader PoC.

Najpierw faktycznie uruchomiono VP z dwiema pozycjami `ID3D11VideoProcessorStream`:

- Stream 0: bazowe NV12,
- Stream 1: RGBA/BGRA HUD,
- liczba streamów: 2.

Na testowanym sterowniku AMD `VideoProcessorBlt` z włączoną alfą Stream 1 zwracał `E_FAIL (0x80004005)` zarówno dla RGBA, jak i BGRA. Po wyłączeniu alfy operacja wykonywała się, ale przezroczyste tło HUD stawało się nieprzezroczyste i czarne. Ten wariant został odrzucony. API D3D11 przewiduje tablicę wielu streamów oraz osobne sterowanie alfą streamu, ale deklarowana obsługa sterownika nie przełożyła się tu na poprawne wykonanie: [VideoProcessorBlt](https://learn.microsoft.com/en-us/windows/win32/api/d3d11/nf-d3d11-id3d11videocontext-videoprocessorblt), [VideoProcessorSetStreamAlpha](https://learn.microsoft.com/en-us/windows/win32/api/d3d11/nf-d3d11-id3d11videocontext-videoprocessorsetstreamalpha).

Istniejący pixel-shader PoC nie był kompletnym compositorem produkcyjnym. Stary compute PoC błędnie zakładał zwykły UAV dla planarnego NV12 i nie został użyty.

Zaimplementowany wariant jest kompletnym, plane-aware compositorem `cs_5_0`:

1. niezmieniony VP Stream 0 zapisuje bazę do NV12 z puli wyjściowej,
2. persistent RGBA8 HUD jest udostępniony shaderowi jako SRV,
3. osobne UAV zapisują plane 0 jako `R8_UNORM` i plane 1 jako `R8G8_UNORM`,
4. shader wykonuje straight-alpha blend oraz tę samą całkowitoliczbową konwersję BT.601/studio-range co ścieżka referencyjna,
5. ta sama tekstura NV12 z puli trafia do `CreateSurfaceFromDX11Native()` i następnie AMF.

Diagnostyka potwierdziła identyczność wskaźnika tekstury wyjściowej VP/compositora oraz tekstury przekazanej do AMF. Pula nadal ma 4 sloty; nie zmieniono własności powierzchni, retry `AMF_INPUT_FULL` ani drain do EOF.

## HUD texture

| Właściwość | Wartość |
|---|---:|
| Python | RGBA, straight alpha |
| D3D11 | `DXGI_FORMAT_R8G8B8A8_UNORM` |
| Rozmiar | 3840 × 2160 |
| Tło | alpha = 0 |
| Persistent | YES |
| Alokacje w pełnym eksporcie | 1 |
| Uploady | 1131 |
| Alokacja per frame | NO |

Nie ma CPU swizzle RGBA→BGRA ani niekontrolowanego premultiply.

## Pipeline ETAP 2

```text
FFmpeg software decode
  -> CPU NV12
  -> istniejący staging upload
  -> D3D11 NV12 base texture
  -> VideoProcessor Stream 0
  -> pooled DXGI_FORMAT_NV12 output
                         ^
Pillow RGBA straight alpha
  -> persistent RGBA8 D3D11 texture
  -> direct NV12 compute compositor (Y + UV UAV)
  -> ta sama pooled NV12 output surface
  -> CreateSurfaceFromDX11Native
  -> AMF HEVC
  -> audio mux
  -> final MP4
```

W trybie `GPU_HUD` liczba wywołań `BlendRGBAToNV12`: **0**. CPU i GPU blend nie wykonują się jednocześnie.

## Testy funkcjonalne

### Test statyczny — 30 klatek

- 30/30 klatek,
- persistent HUD texture: 1 utworzenie, 30 uploadów,
- CPU blend: 0,
- AMF errors/drops: 0,
- czysta baza, poprawna alfa i kolor,
- brak black frames oraz zielonych/magentowych linii.

Artefakt: `AMD_ETAP2/static_hud_vp_compute_30.mp4`.

### Real HUD — 30 klatek

Realne `compose_overlay()`, FIT, GPMF, mapa, wskaźniki oraz data/czas zostały wyrenderowane poprawnie. Nie stwierdzono clippingu ani artefaktów NV12.

Artefakt: `AMD_ETAP2/real_hud_gpu_30_correct_font.mp4`.

### Pełny eksport produkcyjny

Artefakt: `AMD_ETAP2/gpu_hud_full_1131_correct.mp4`.

| Licznik | Wynik |
|---|---:|
| Source | 1131 |
| Decoded | 1131 |
| HUD | 1131 |
| Native update | 1131 |
| VP processed | 1131 |
| GPU HUD frames | 1131 |
| AMF submitted | 1131 |
| AMF output | 1131 |
| Muxed | 1131 |

`requested_frames = 1132` wynika z zaokrąglenia `ceil(duration × fps)` dla nominalnego czasu materiału; źródło rzeczywiście zawiera 1131 klatek. Wszystkie faktycznie dostępne klatki przeszły cały pipeline.

AMF:

- `INPUT_FULL count`: 0,
- retries: 0,
- dropped submissions: 0,
- ignored submissions: 0.

Output: 3840×2160, HEVC Main, `yuv420p`, 1131 klatek, audio AAC stereo 48 kHz obecne. Audio ma ten sam SHA-256 co golden: `E7D3FA3DF057F0705BF2F8410B6FDE44FAC298002A55BDB1B6EC403E642D1FF3`.

## Golden comparison

Porównanie obrazu zdekodowanego z dwóch osobno zakodowanych plików HEVC nie jest bitowo identyczne. Małe różnice rozchodzą się przez predykcję kodeka. Dlatego wykonano również porównanie checkpointu NV12→RGBA **przed AMF**, które izoluje sam compositor.

Checkpoint przed AMF, frame 30:

- MAE: **0.0019906202**,
- MAX: **2**,
- P95: **0**,
- P99: **0**.

| Klatka | MAE po dekodowaniu MP4 | MAX | P95 | P99 | Wynik |
|---:|---:|---:|---:|---:|---:|
| 30 | 1.403913 | 56 | 6 | 11 | PASS |
| 300 | 1.535369 | 55 | 6 | 10 | PASS |
| 900 | 1.188364 | 52 | 5 | 10 | PASS |

Kontrola wizualna wszystkich trzech klatek:

| Element | Wynik |
|---|---:|
| Base video | PASS |
| FIT dynamic | PASS |
| GPMF dynamic | PASS |
| Map / GPS progression | PASS |
| Date/time | PASS |
| Text, graphs, gauge | PASS |
| Straight alpha / półprzezroczyste wykresy | PASS |
| HUD i base color | PASS |
| Brak clippingu i artefaktów | PASS |
| Audio | PASS |

Wynik odpowiada golden w sensie funkcjonalnym i wizualnym, lecz nie jest bitowo identyczny po dwóch niezależnych kompresjach HEVC. Różnica przed AMF jest ograniczona do MAX=2 i zerowego P99.

## Performance

| Pomiar | CPU_REFERENCE | GPU_HUD |
|---|---:|---:|
| TRUE FPS | 4.16 | **9.061** |
| Wall time / frame | ~240.385 ms | **110.367 ms** |
| BlendRGBAToNV12 | ~134 ms/frame | **0 ms/frame; 0 calls** |
| Total wall-clock, GPU_HUD | — | **124.825 s** |

Przyspieszenie względem wskazanego baseline: **2.18× / +117.8%**. Zysk end-to-end wynosi około **130.0 ms/frame**. Bezpośrednio usunięto około **134 ms/frame** CPU blendu; część zysku zużywa upload HUD i compositor GPU.

### Timingi pełnego eksportu produkcyjnego

| Stage | AVG ms | Median ms | P95 ms | P99 ms |
|---|---:|---:|---:|---:|
| Decode/pipe | 22.525 | 23.538 | 29.559 | 32.551 |
| Telemetry/frame_data | 19.484 | 19.727 | 22.297 | 24.417 |
| compose_overlay | 34.829 | 32.306 | 46.047 | 63.460 |
| PIL tobytes | 17.237 | 15.794 | 24.498 | 30.130 |
| update_hud | 6.418 | 6.157 | 7.539 | 10.502 |
| HUD texture upload | 6.376 | 6.118 | 7.492 | 10.459 |
| NV12 staging memcpy | 1.131 | 1.096 | 1.367 | 2.283 |
| BlendRGBAToNV12 | 0.000 | 0.000 | 0.000 | 0.000 |
| CopyResource submit | 0.031 | 0.030 | 0.046 | 0.079 |
| VP + compositor CPU submit | 0.504 | 0.456 | 0.679 | 1.151 |
| AMF submit/backpressure | 0.559 | 0.451 | 1.538 | 2.115 |
| AMF QueryOutput | 0.251 | 0.162 | 0.789 | 1.018 |
| Packet write | 0.273 | 0.165 | 0.843 | 1.311 |
| Audio mux | 671.020 total | — | — | — |

Normalny eksport nie wykonuje blocking GPU wait. Dlatego GPU completion w profilu produkcyjnym świadomie wynosi 0/niezmierzone, a 0.504 ms oznacza wyłącznie czas CPU submit, nie wykonanie GPU.

Osobny 30-klatkowy przebieg z timestamp queries i blocking `GetData`, dostępny tylko przy profiling ON, zmierzył rzeczywisty compositor GPU completion:

- AVG: **9.298 ms**,
- Median: **9.745 ms**,
- P95: **11.737 ms**,
- P99: **15.713 ms**.

Największym bottleneckiem jest teraz CPU HUD generation/memory path: `compose_overlay` około 34.8 ms, następnie decode/pipe 22.5 ms, telemetry 19.5 ms, PIL `tobytes` 17.2 ms i pełny upload HUD 6.4 ms. Tych elementów zgodnie z zakresem ETAPU 2 nie optymalizowano.

## Build i testy

- DLL: `C:\_DEV\TeleM\native\d3d11_amf_pipeline\bin\telem_amd_native.dll`
- ABI: 2
- Build ID użyty do pełnego eksportu: `telem-amd-native/1.0.0+42dc5799a538.src71981ae8ba2c`
- Git commit embedded: `42dc5799a53851a7b7ca9216068c9dd082eb496c`
- Build timestamp: `2026-08-14T07:22:26+02:00`
- DLL SHA-256: `066CDC84EB910D7A800A81255FD2913E7597336E0D4CECDD2901DE69D60C5127`
- dwa kolejne clean buildy: identyczny SHA-256 — PASS,
- `git diff --check`: PASS,
- testy: **153 passed, 17 skipped**.

Build:

```powershell
C:\tools\mingw64\bin\cmake.exe -S native\d3d11_amf_pipeline -B native\d3d11_amf_pipeline\build-etap2 -G Ninja -DCMAKE_BUILD_TYPE=Release -DCMAKE_MAKE_PROGRAM=C:/tools/mingw64/bin/ninja.exe -DCMAKE_CXX_COMPILER=C:/tools/mingw64/bin/g++.exe
C:\tools\mingw64\bin\cmake.exe --build native\d3d11_amf_pipeline\build-etap2 --target telem_amd_native --clean-first --parallel
```

## Odpowiedzi wprost

1. **Jak GPU composituje HUD?** VP Stream 0 tworzy bazową powierzchnię NV12, a kompletny compute shader składa persistent RGBA8 straight-alpha HUD bezpośrednio do osobnych plane UAV Y i UV tej samej powierzchni NV12.
2. **Czy CPU blend został całkowicie usunięty z GPU path?** Tak: 0 wywołań na 1131 klatek. Kod pozostaje dostępny wyłącznie w jawnym `CPU_REFERENCE`.
3. **Czy VP Stream 1 faktycznie działa?** Nie na testowanym sterowniku w wymaganym wariancie alpha: dwa rzeczywiste streamy kończą się `E_FAIL`; bez alfy wynik ma czarne tło. Dlatego nie został wybrany.
4. **Czy wynik odpowiada golden reference?** Tak funkcjonalnie i wizualnie. Przed AMF: MAE 0.00199, MAX 2, P99 0. Po osobnych kompresjach HEVC nie jest bitowo identyczny; dokładne różnice podano wyżej.
5. **Jaki jest TRUE FPS?** **9.061 FPS** dla pełnych 1131 klatek, od startu decode do zamknięcia pliku po audio mux.
6. **Ile ms/frame usunięto?** Około **134 ms/frame** CPU blendu; rzeczywisty zysk end-to-end to około **130.0 ms/frame**.
7. **Co jest teraz największym bottleneckiem?** CPU `compose_overlay`, a łącznie cały pozostawiony bez zmian CPU HUD/memory path; dalej decode/pipe i telemetry.
8. **Czy można przejść do następnego etapu?** Tak. Kryteria ETAPU 2 są spełnione; należy zachować `CPU_REFERENCE` do dalszych porównań A/B.

## Artefakty

- pełny profil: `AMD_ETAP2/gpu_hud_full_1131_correct.mp4.amd_profile.json`,
- liczby regresji: `AMD_ETAP2/regression_results.json`,
- klatki końcowe: `AMD_ETAP2/gpu_frames_correct/frame_30.png`, `frame_300.png`, `frame_900.png`,
- checkpointy przed AMF: `AMD_ETAP2/cpu_reference_pre_amf_frame30.png`, `gpu_hud_pre_amf_frame30.png`.

