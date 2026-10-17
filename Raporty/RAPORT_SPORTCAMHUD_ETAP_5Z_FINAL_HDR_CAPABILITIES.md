# SPORTCAMHUD — ETAP 5Z.1: finalny audyt HDR/HLG, HEVC Main10 i tone mappingu GPU

Data: 2026-10-16. **STATUS: PASS (audyt diagnostyczny)** — testy Main10 i benchmark tone mappingu wykonane; integracja z produkcyjnym pipeline pozostaje **projektem (NOT VERIFIED w SportCamHUD)**.
Production changes: **NONE**. DLL SHA256: **UNCHANGED**.

Oznaczenia: **CODE** (odczyt kodu), **API** (zwrócone przez API), **HARDWARE TEST** (sonda na sprzęcie), **VIDEO TEST** (analiza plików wideo), **MEASURED** (zmierzone), **ESTIMATED** (szacunek), **NOT VERIFIED**.

---

## 1. HEAD i git status

- Gałąź `fix/gui-freeze-hud-composite`, HEAD **`f3ba1bc`** (zgodny z ostatnim potwierdzonym).
- Zmiany sprzed etapu (nietknięte): `M def_layout.json`, `M src/ffmpeg/intel_native_exporter.py`, `M src/ffmpeg/nvidia_native_exporter.py`, `M Raporty/RAPORT_..._5R_F_...md`, liczne `??` (raporty, artefakty, `runtime/amd/`, `src/ffmpeg/live_av_mux.py`, `native/.../bin/*.bak_*`).
- Nowe w tym etapie wyłącznie: `Raporty/etap5z1_artifacts/` (sondy, logi, wyniki, ~2,1 MB) i ten raport. Brak commitów, brak reset/clean/stash/rebase/merge/push.

## 2. Stan początkowy (z ETAP 5Z, raport częściowy)

GoPro: HEVC Main 10, `yuv420p10le`, full range, BT.2020nc/BT.2020/HLG. Pipeline: MF → P010 → `VideoProcessorBlt` P010→NV12 (utrata 10 bit) → fused HUD NV12 → AMF HEVC Main. VP w trybie produkcyjnym: macierz BT.709, zakres „0” (w praktyce studio), brak HLG/BT.2020. Wynik HLG→SDR: INCORRECT (MAE 4,1/5,0/2,5 do „BT.709 limited bez transferu”). Main10 encode i koszt tone mappingu: NOT VERIFIED. Ten etap kontynuuje od tego miejsca.

## 3. Sprzęt i sterownik [API / HARDWARE TEST]

- AMD Ryzen 7 7730U, iGPU **AMD Radeon (TM) Graphics, VEN=1002 DEV=15E7** (Vega gfx90c) — odczyt `IDXGIAdapter::GetDesc` w sondzie.
- Sterownik 31.0.21925.1001 (z 5Z; nie zmieniano).
- **AMF runtime (amfrt64.dll, `AMFQueryVersion`): 1.4.31.0**; nagłówki SDK w repo: 1.5.2. `AMFInit(AMF_FULL_VERSION)` = AMF_OK.

## 4. Test AMF HEVC — metoda [HARDWARE TEST]

Sonda `Raporty/etap5z1_artifacts/amf_main10_probe.cpp` (osobny exe, MSVC 2022, `/I native/d3d11_amf_pipeline/include`; **nie linkuje i nie ładuje produkcyjnej DLL**, ABI 9 nietknięte):
`D3D11CreateDevice(VIDEO_SUPPORT)` → `AMFInit` → `InitDX11` → `CreateComponent(AMFVideoEncoder_HEVC)` → `GetCaps` (profile, level, IO caps) → SetProperty (konfiguracja jak produkcja: TRANSCODING, SPEED, PEAK_CONSTRAINED_VBR 40/60 Mbps, VBV 40 Mbit, 3840x2160, 30000/1001) → `Init(format)` → 300 klatek: `CreateSurfaceFromDX11Native` → `SubmitInput` → `QueryOutput` → zapis surowego HEVC → `Drain`.
Treść: 8 tekstur z gładkimi gradientami 10-bit (wrażliwe na banding), przesuwanymi per klatka.

**Błąd konfiguracji testu wykryty i usunięty:** pierwsza próba Main10 dała strumień 72 KB z czarnym obrazem. Readback tekstury pokazał zera — **sterownik ignoruje `pInitialData` w `CreateTexture2D` dla planarnego P010**. Po wgraniu danych przez teksturę STAGING + `CopyResource` tekstura zawiera gradient (readback `9 130 252 374 …` w kodach 10-bit). To był błąd sondy, nie kodera.

## 5. Wynik TEST A — HEVC Main / NV12 8-bit [HARDWARE TEST, MEASURED]

`build/probe_main8.log`: wszystkie SetProperty = 0 (AMF_OK); `Init(NV12,3840x2160)` = 0; `GetProperty`: profile=1, color_bit_depth=8; pierwszy `SubmitInput` = 0, `QueryOutput` = 0; **300/300 pakietów, 8 523 074 B**; enkoder-only (syntetyczna treść, z drenażem) 14,1 ms/kl., **70,8 FPS**. ffprobe: `hevc Main, yuv420p, tv`; SPS: profile_idc=1, bit_depth 8/8.
Uwaga [VIDEO TEST]: bez ustawionych właściwości koloru AMF zapisuje VUI `colour_primaries=0` (ffprobe: „reserved”), `transfer=1`, `matrix=2` — odpowiada obserwacji z 5Z, że wyjście produkcyjne ma nieoznaczone primaries/macierz.

## 6. Wynik TEST B — HEVC Main10 / P010 10-bit [HARDWARE TEST, MEASURED]

`build/probe_main10.log`:
| krok | wynik |
|---|---|
| `HevcProfile = MAIN_10 (2)` | AMF_OK |
| `HevcColorBitDepth = 10` | AMF_OK |
| VUI: In/Out ColorProfile FULL_2020, TransferChar ARIB_STD_B67 (18), Primaries BT2020 (9), NominalRange FULL | wszystkie AMF_OK |
| `Init(AMF_SURFACE_P010, 3840x2160)` | **AMF_OK (0)** |
| `GetProperty` po Init | profile=**2**, color_bit_depth=**10** |
| pierwszy `SubmitInput` / `QueryOutput` | 0 / 0 |
| pakiety | **300/300, 16 258 284 B** |
| szybkość (enkoder-only, syntetyczna) | 14,35 ms/kl., **69,7 FPS** (Main8 w tych samych warunkach: 70,8 FPS) |

## 7. ffprobe i SPS [VIDEO TEST]

`probe_main10.hevc` — ffprobe: `hevc`, **profile=Main 10**, **yuv420p10le**, color_range=**pc**, bt2020nc / bt2020 / **arib-std-b67**, 3840x2160, 300 klatek.
SPS/VUI (`build/sps_trace.txt`, `trace_headers`):
| pole | Main8 | **Main10** |
|---|---|---|
| general_profile_idc (VPS i SPS) | 1 | **2** |
| general_level_idc | 186 (6.2) | 186 |
| chroma_format_idc | 1 | 1 |
| bit_depth_luma_minus8 | 0 | **2** |
| bit_depth_chroma_minus8 | 0 | **2** |
| video_full_range_flag | 0 | **1** |
| colour_primaries / transfer / matrix | 0 / 1 / 2 | **9 / 18 / 9** |

Rzeczywista głębia [VIDEO TEST, MEASURED]: dekodowana klatka 0 vs wejście: luma MSE 0,31 kodu 10-bit (PSNR 65,3 dB), **74,9% próbek nie jest wielokrotnością 4** (ścieżka 8-bit dałaby ~0%), 880 różnych poziomów luma w jednym wierszu. Brak cichego powrotu do 8 bit.
Dekodowanie: D3D11VA (sprzętowo) → `p010le(pc, bt2020nc/bt2020/arib-std-b67)`, 300 klatek bez błędów; dekoder programowy `-xerror` bez błędów (`build/hwdecode_main10.txt`).
Brak fallbacku CPU: `GetAccelerationType()` = 0 = **AMF_ACCEL_HARDWARE**; 4K Main10 przy 69,7 FPS jest poza zasięgiem programowego HEVC na tym CPU.

## 8. Werdykt Main10 encode

**AMF HEVC Main10 encode na Ryzen 7 7730U / Vega gfx90c: SUPPORTED** [HARDWARE TEST + VIDEO TEST].

Porównanie z capability API [API]: `HEVC_CAP_MAX_PROFILE` = **1 (Main)** — **API zaniża możliwości**, faktyczny Init/encode Main10 działa. IO caps wejścia: NV12 (native), **P010 (native)**, YUV420P/YV12/BGRA/RGBA/ARGB (konwersja); rozdzielczość 128..4096; 1 instancja HW; `CAP_MAX_THROUGHPUT` = 0 (nieraportowany). Wniosek dla implementacji: **nie wolno opierać detekcji Main10 na `CAP_MAX_PROFILE`**; należy wykonać próbny `Init(P010)` (i ewentualnie 1 klatkę) na starcie. Obecne `telem_amd_probe_capabilities` (hevc_main10=0 na stałe) jest błędne [CODE, z 5Z].
Rozróżnienie: HEVC Main10 **decode** — działa (MF/D3D11VA P010) [HARDWARE TEST]; **VP P010 input** — działa dla G22 P2020 [HARDWARE TEST, §12]; **Main10 encode** — działa [HARDWARE TEST]. To trzy niezależne możliwości.

## 9. Parametry referencyjnego tone mappingu HLG→SDR

Weryfikacja źródła [VIDEO TEST]: `F:\_DEV\BikeRideHUD-amd\Video\GX020079.mp4` — hevc Main 10, yuv420p10le, **pc**, bt2020nc/bt2020/**arib-std-b67**, 3840x2160, 30000/1001, 1131 klatek, 48,0 Mb/s. Zgodne z 5Z. Plik źródłowy tylko odczytywany.

Model shadera sondy (`hlg_tonemap_cs.hlsl`) — zgodny z punktami odniesienia libplacebo:
| parametr | wartość |
|---|---|
| wejście | P010, 10-bit, **full range** (Y'=kod/1023, C=(kod−512)/1023); limited wspierany flagą |
| macierz | BT.2020 NCL (Kr 0,2627, Kb 0,0593) |
| transfer | odwrotny OETF HLG (BT.2100, a=0,17883277, b=0,28466892, c=0,55991073) |
| OOTF / luminancja | HLG OOTF, **Lw = 1000 cd/m²**, γ = 1,2 (BT.2100 Tab. 5) |
| biel odniesienia | HDR reference white **203 cd/m²** (BT.2408, HLG 75%) = SDR 1,0 |
| tone mapping | **BT.2390 EETF** w domenie PQ, 1000 → 203 cd/m²; warianty: na luminancji (mode 0) i **na max(R,G,B) po BT.2020→709 (mode 2)**; mode 1 = tylko clip (dolna granica kosztu) |
| gamut | BT.2020→BT.709 macierzą liniową; reszta poza gamutem: twardy clip |
| transfer wyjściowy | BT.1886 odwrotny (γ 1/2,4), jak `color_trc=bt709` w libplacebo |
| wyjście | Y'CbCr BT.709 **limited** 8-bit NV12, dithering Bayer 4x4, chroma 2x2 uśredniana |

Referencje FFmpeg: (a) **libplacebo statyczny** `tonemapping=bt.2390:peak_detect=0:contrast_recovery=0:gamut_mode=clip` (ten sam model); (b) **libplacebo domyślny** (auto/bt.2390 + dynamiczna detekcja szczytu, contrast recovery 0,3, gamut perceptual, blue-noise dither); (c) zscale HLG→linear (npl 100) + hable (z 5Z). Żaden render nie jest „jedynym poprawnym”: wygląd zależy od bieli odniesienia, detekcji szczytu i operatora.

## 10. Benchmark GPU tone mappingu — FFmpeg [MEASURED]

300 klatek GX020079 4K, każdy test uruchomiony dwukrotnie (1. = rozgrzanie), czas `-benchmark rtime`, wyjście `-f null` (`bench/ffbench_summary.txt`). Repo `ffmpeg.exe` 2026-08-17 (libplacebo, vulkan, d3d11va, amf, opencl).
| test | API | ms/kl. | FPS |
|---|---|---|---|
| A0 dekodowanie D3D11VA (bez kopii) | D3D11 | 9,46 | 105,7 |
| A2 D3D11VA + hwdownload P010 | D3D11→CPU | 9,64 | 103,7 |
| B0 dekodowanie Vulkan | Vulkan | 15,35 | 65,1 |
| B1 Vulkan dec + libplacebo **domyślny** →NV12 (GPU) | Vulkan | 49,45 | 20,2 |
| B2 jw. + hwdownload NV12 | Vulkan→CPU | 45,58 | 21,9 |
| B5 Vulkan dec + libplacebo szybki (bt.2390, bez peak detect, clip, ordered) | Vulkan | 36,85 | 27,1 |
| B6 Vulkan dec + libplacebo minimalny (clip, bez ditheringu) | Vulkan | 35,39 | 28,3 |
| B4 **D3D11VA → hwdownload → hwupload Vulkan → libplacebo szybki → hwdownload** | D3D11+CPU+Vulkan | 30,87 | 32,4 |
| B3 D3D11VA → `hwmap` Vulkan (zero-copy) | — | **FAILED**: `init_hw_device vulkan@d3d11va: Function not implemented (-40)` | — |
| C1 D3D11VA → `hwmap` OpenCL + tonemap_opencl | — | **FAILED**: derived frames context −22 | — |
| A1 `scale_d3d11` P010→NV12 | — | FAILED (konfiguracja filtra) — zastąpione własną sondą §11 | — |

Wnioski: libplacebo/Vulkan na Vega gfx90c to **20–32 FPS całej ścieżki** (filtr nie jest izolowany od dekodowania Vulkan, które samo kosztuje 15 ms). **Brak zero-copy D3D11↔Vulkan** w tej kompilacji FFmpeg → integracja wymagałaby kopii przez CPU (≈ 2× 24,9 MB P010 + 12,4 MB NV12 na klatkę) albo własnej interop (shared NT handles + semafory). Izolowana prędkość filtra FFmpeg ≠ prędkość zintegrowanego SportCamHUD.

## 11. Benchmark D3D11 — VP vs compute shader [HARDWARE TEST, MEASURED]

Sonda `d3d11_hlg_probe.cpp` (osobny exe): 3 prawdziwe klatki P010 GX020079 (30/150/270, zdekodowane FFmpeg, wgrane do tekstur `DXGI_FORMAT_P010`), wyjście: pula 4 tekstur NV12 (RT|UAV|SRV) jak produkcyjna; UAV płaszczyzn przez `ID3D11Device3::CreateUnorderedAccessView1` (R8 / R8G8, PlaneSlice 0/1) — **ten sam mechanizm co produkcja** (`d3d11_vp_pipeline.cpp:1256-1272`). Czas GPU: `D3D11_QUERY_TIMESTAMP(_DISJOINT)` wokół każdego Blt/Dispatch (ta sama metoda co produkcyjne `m_tsQueries`, `d3d11_vp_pipeline.cpp:4656`). 30 klatek rozgrzania, 300 pomiarów.

Czas GPU 4K, średnia [ms] (kolejne serie; rozrzut wynika ze stanu zegarów/zasilania laptopa):
| konwersja | seria 1 | seria 2 | a | b | c |
|---|---|---|---|---|---|
| VP Blt P010→NV12, `YCBCR_FULL_G22_LEFT_P2020`→`STUDIO_G22_LEFT_P709` | 3,03 | 3,02 | 3,64 | 3,69 | 4,04 |
| VP Blt, `YCBCR_STUDIO_G22_LEFT_P2020` | 3,08 | 3,07 | — | — | — |
| **CS HLG→SDR BT.2390 max(RGB)** (mode 2) | — | — | **2,96** | **2,95** | **3,11** |
| CS HLG→SDR BT.2390 luminancja (mode 0) | 2,44 | 2,43 | 3,44 | 3,00 | 4,63 |
| CS tylko clip (mode 1, dolna granica) | 1,46 | 1,55 | 1,96 | 1,99 | 2,73 |

**W każdej parze pomiarów z tej samej serii shader HLG→SDR (max RGB) był szybszy od VP Blt o 0,7–0,9 ms.** Pełny poprawny HLG→SDR w compute shaderze nie zwiększa kosztu GPU względem obecnego kroku konwersji — zastępuje go.

Konwersja + AMF HEVC Main (bez dekodowania i HUD, pętla szeregowa sondy) [MEASURED, **NIEREPREZENTATYWNE**]: 21–52 FPS z dużym rozrzutem między seriami (VP+AMF: 31,1/51,7/52,1/30,9; CS+AMF: 30,4/29,8/31,4/27,0), bez stałej przewagi któregokolwiek wariantu. Wąskim gardłem tej pętli jest synchroniczne podawanie do AMF i stan zasilania, nie konwersja. Nie jest to Render FPS SportCamHUD.

## 12. D3D11 Video Processor — poprawne flagi (wariant A) [API / HARDWARE TEST]

API: `ID3D11VideoContext1::VideoProcessorSetStreamColorSpace1` / `VideoProcessorSetOutputColorSpace1` z `DXGI_COLOR_SPACE_TYPE`, sprawdzane `ID3D11VideoProcessorEnumerator1::CheckVideoProcessorFormatConversion` (produkcja ma to już jako tryby diagnostyczne `AMD_VP_COLORSPACE_MODE=2/3`, `d3d11_vp_pipeline.cpp:594-607`).
| wejście (P010) → wyjście NV12 `STUDIO_G22_LEFT_P709` | Check | Blt |
|---|---|---|
| `YCBCR_FULL_G22_LEFT_P2020` (11) | supported | **OK**, ~3,0–4,0 ms |
| `YCBCR_STUDIO_G22_LEFT_P2020` (10) | supported | OK |
| `YCBCR_FULL_GHLG_TOPLEFT_P2020` (19) | supported | **awaria procesu (access violation) w `VideoProcessorBlt`** |
| `YCBCR_STUDIO_GHLG_TOPLEFT_P2020` (18) | supported | **awaria w Blt** |
| `YCBCR_STUDIO_G2084_LEFT_P2020` (13) | supported | **awaria w Blt** |
| `YCBCR_STUDIO_G22_LEFT_P709` (8) i legacy struct produkcji (macierz 709, Nominal 0) | supported | `E_FAIL (0x80004005)` na teksturze nie-dekoderowej |

Wnioski:
- Flagi P2020 + FULL dają **tylko poprawną macierz i zakres oraz (prawdopodobnie) konwersję primaries**; transfer HLG jest traktowany jak gamma 2.2 — **to nie jest tone mapping**. [HARDWARE TEST + VIDEO TEST §13]
- Tryby z transferem HDR (GHLG/G2084) sterownik deklaruje, ale wywracają proces → **nieużywalne** na sterowniku 31.0.21925.1001 [HARDWARE TEST]. Każde ich użycie w produkcji groziłoby crashem eksportu.
- Produkcyjny tryb 709 nie dał się odtworzyć na samodzielnej teksturze P010 (produkcja używa powierzchni dekodera MF), więc **dokładny koszt produkcyjnego Blt: NOT VERIFIED**; Blt P2020 (ta sama operacja z inną macierzą) przyjęto jako przybliżenie [ESTIMATED].
- Wpływ na FPS samej zmiany flag: ≈ 0 (ten sam Blt) [ESTIMATED].

## 13. Format, zakres i jakość obrazu [VIDEO TEST, MEASURED]

Te same klatki (30/150/270), centralny wycinek bez HUD (1200,300)-(2600,1300) i regiony nazwane; wszystkie obrazy dekodowane tą samą konwersją BT.709 limited→RGB (`cmp/quality_compare.json`, `cmp/sheet_f*.jpg`).

Zgodność shadera z referencją tego samego modelu (`cmp/cs_vs_libplacebo_static.json`): **MAE 4,8 / 4,4 / 2,0** (centrum, 8-bit RGB), p95 16/14/5 — reszta wynika z uproszczonej chromy 2x2, dithera i operatora na luminancji vs libplacebo. Model shadera jest więc poprawnie zaimplementowany.

Klatka 30 (słoneczna ulica, jasne niebo), centrum:
| wariant | śr. luma | clip ≥250 | czerń ≤5 | nasycenie | niebo: clip / nasycenie |
|---|---|---|---|---|---|
| eksport produkcyjny (obecny) | 150 | 25,4% | 0,41% | 0,260 | 28,0% / 0,416 |
| VP P2020 full (tylko flagi) | 143 | 16,0% | 0,01% | 0,305 | 12,1% / 0,453 |
| CS BT.2390 luminancja | 161 | 32,8% | 0,01% | 0,302 | 38,8% / 0,446 |
| **CS BT.2390 max(RGB)** | 148 | 27,3% | 0,01% | 0,343 | 36,3% / 0,508 |
| libplacebo statyczny (ten sam model) | 157 | 31,4% | 0,01% | 0,305 | 38,7% / 0,450 |
| libplacebo domyślny (peak detection) | 133 | 23,8% | 0,02% | 0,324 | 31,0% / 0,481 |
| zscale hable (npl 100) | 131 | 18,6% | 0,01% | 0,395 | 13,8% / 0,580 |

Klatka 150: podobny układ (eksport 25,6% clip, 1,53% czerni; CS max(RGB) 27,2% / 0,07%; libplacebo domyślny 24,0% / 0,11%). Klatka 270 (cień, jasne podcienie): eksport 5,70% czystej czerni vs 0,77% CS i 0,91% libplacebo — **obecny eksport zgniata cienie** (błąd zakresu pełny→ograniczony).

Ocena wizualna arkuszy (`cmp/sheet_f30.jpg`: rząd 1 eksport | VP P2020 | CS luminancja; rząd 2 CS max(RGB) | libplacebo statyczny | libplacebo domyślny):
- eksport: wyblakłe, jasnoszare niebo, płaskie kolory (BT.2020 interpretowane jako 709), zgniecione cienie;
- VP P2020: poprawne kolory i cienie, ale HLG jako gamma 2.2 — średnie tony jasne, brak kompresji świateł;
- CS luminancja i libplacebo statyczny: **niebo przesunięte w cyjan** (kanał B > 1 po skalowaniu luminancji, twardy clip) — znany artefakt tone mappingu na luminancji;
- **CS max(RGB)**: niebo niebieskie, odcień zachowany, wygląd najbliższy libplacebo domyślnemu; nieco jaśniejsza nawierzchnia (brak dynamicznej detekcji szczytu).
Ograniczenia miar: MAE i „clip ≥250” w 8-bit RGB nie są miarami percepcyjnymi (ΔE ITP), jasne nasycone niebo ma kanał B ≥250 bez utraty detalu; banding oceniono tylko liczbą poziomów (wszystkie warianty 253–256) — dithering zastosowano. Wybór bieli 203 cd/m² i detekcji szczytu zmienia średnią jasność o ±15–25 kodów; to decyzja estetyczna, nie błąd. Nie wprowadzano korekt saturacji/kontrastu/gamma.

## 14. Zgodność z obecnym HUD [CODE]

- Fused compositor (`d3d11_vp_pipeline.cpp:1376-1437`, produkcja `AMD_FUSED_COMPOSITOR=1`) **czyta wyjście VP w miejscu** (`OutputY[pos]`/`OutputUV`) i **zakłada, że jest w pełnym zakresie**: normalizuje Y 0..255→16..235 i UV (`ScaleChroma`). Shader HLG→SDR musi więc albo zapisywać pełny zakres (kontrakt obecnego VP), albo fused musi pominąć normalizację dla tej ścieżki. Zapis limited bez zmiany fused dałby podwójną kompresję zakresu.
- HUD (sRGB RGBA) jest konwertowany do YUV współczynnikami **BT.601** (`66/129/25`, `-38/-74/112`, `112/-94/-18`), podczas gdy wideo jest BT.709 — istniejąca drobna niezgodność kolorów HUD (nie dotyczy HDR, odnotowane, nie zmieniane).
- Kolejność: tone mapping musi nastąpić **przed** nałożeniem HUD, aby HUD (sRGB) nie był tone-mapowany ani przepalany. W wariancie D3D11 jest to naturalne: shader zastępuje Blt, fused HUD działa dalej bez zmian (poza flagą zakresu).

## 15. Wariant zachowania HDR (Main10) — projekt [ESTIMATED / NOT VERIFIED]

Sprzęt potwierdza Main10 encode, więc tryb „Zachowaj HDR” jest **możliwy na tym GPU**. Projekt:
1. Dekoder MF P010 → **bez VP Blt do NV12**; pula wyjściowa **P010** (4K: 24,9 MB/teksturę vs 12,4 MB NV12; +~50 MB dla puli 4).
2. Nowy wariant fused compositora P010 (SRV R16/R16G16 + UAV R16_UNORM/R16G16_UNORM — te widoki produkcja już tworzy dla 8K, `d3d11_vp_pipeline.cpp:814-900`): wideo przechodzi **bit-exact** (bez zmiany transferu), HUD: sRGB → liniowe → **skalowanie do bieli graficznej 203 cd/m²** (BT.2408: biel HUD = HLG 75%, nie 100%, aby nie przepalać wskaźników) → primaries 709→2020 → dla HLG: odwrotny OOTF (Lw 1000) + OETF HLG; dla PQ: OETF PQ (203 nit) → Y'CbCr BT.2020 NCL **w zakresie źródła** (GoPro: full) → blend alfa w domenie zakodowanej (jak dziś) lub liniowej (dokładniej, droższe). Regulowana luminancja HUD (np. 100–300 nit) jako parametr.
3. AMF: `PROFILE_MAIN_10`, `COLOR_BIT_DEPTH_10`, `Init(AMF_SURFACE_P010)`, VUI z metadanych źródła: primaries 9, transfer **18 (HLG)** lub **16 (PQ)**, matrix 9, `NOMINAL_RANGE` = zakres źródła. Dla PQ/HDR10: przekazać mastering display + MaxCLL/MaxFALL (`HEVC_INPUT_HDR_METADATA`); dla HLG brak metadanych statycznych (zwykle). **Nigdy nie oznaczać HLG jako PQ ani odwrotnie.**
4. Mux `-c copy`: VUI w strumieniu jest poprawny (zweryfikowane w sondzie); obecność atomu `colr` w MP4 po remuxie: **NOT VERIFIED**.
5. Koszt: AMF Main10 ≈ Main8 (69,7 vs 70,8 FPS, syntetyczne) [MEASURED, enkoder-only]; fused P010 ≈ 2× ruch pamięci fused NV12 [ESTIMATED +0,5–1,5 ms]; brak Blt (−3 ms) [ESTIMATED]. Render FPS: NOT VERIFIED.

Różnice HLG vs PQ: HLG jest scenicznie-relatywny (OOTF zależy od szczytu wyświetlacza, wsteczna zgodność z SDR, brak metadanych), PQ jest absolutny (nity, wymaga metadanych HDR10, brak wstecznej zgodności). HUD musi być kodowany osobną ścieżką dla każdego transferu.

## 16. Wariant poprawnego HDR→SDR [HARDWARE TEST + MEASURED; integracja ESTIMATED]

Compute shader D3D11 (model §9, mode 2 max(RGB)) **zamiast** `VideoProcessorBlt` dla źródeł HDR: P010 SRV → HLG decode → OOTF → BT.2390 → 2020→709 → BT.1886 → NV12 (pełny zakres dla obecnego fused albo limited z flagą) → fused HUD → AMF Main. Opcjonalnie dynamiczna detekcja szczytu (redukcja max/histogram luma na 1/4 rozdzielczości, wygładzanie czasowe) dla wyglądu bliższego libplacebo domyślnemu: [ESTIMATED +0,2–0,5 ms, NOT VERIFIED].

## 17. Porównanie wariantów i rekomendowana architektura

| | A: flagi VP | **B: shader D3D11** | C: libplacebo/Vulkan |
|---|---|---|---|
| poprawność | macierz/zakres tak; **brak tone mappingu**; tryby HLG crashują | **pełny HLG→SDR** (zweryfikowany vs libplacebo, MAE 2–5) | pełny, najbogatszy (peak detect, perceptual gamut) |
| koszt GPU 4K | ~3,0–4,0 ms (jak dziś) [MEASURED] | **~2,95–3,1 ms; −0,7…−0,9 ms vs VP** [MEASURED] | 31–49 ms/kl. całej ścieżki (20–32 FPS) [MEASURED] |
| transfery | brak nowych | **brak nowych** (te same tekstury i pula) | brak zero-copy D3D11↔Vulkan w FFmpeg → CPU round-trip lub własny interop |
| bufory | brak | brak (opc. mały bufor peak-detect) | pośrednie tekstury Vulkan + staging |
| synchronizacja | bez zmian | bez zmian (ten sam context, kolejność Dispatch → fused) | semafory/klucze między API |
| HUD/alfa | bez zmian | bez zmian (flaga zakresu w fused) | HUD musiałby wrócić do D3D11 po kopii |
| utrzymanie | minimalne | 1 shader + 1 flaga, w obrębie istniejącego kodu | nowa zależność Vulkan/libplacebo w DLL |

**Rekomendacja: wariant B — compute shader w istniejącym pipeline D3D11**, jako osobny Dispatch w miejscu `VideoProcessorBlt` (najmniejsza zmiana, zachowuje kontrakt fused). Etap późniejszy (opcjonalny): wchłonięcie konwersji do fused compositora (odczyt P010 SRV zamiast in-place NV12; oszczędność jednego zapisu+odczytu 4K NV12, [ESTIMATED 0,3–0,6 ms]). Wariant A jako jedyna poprawka — **nie** (nie robi tone mappingu). Wariant C — **nie** dla tego GPU.

## 18. Prognoza Render FPS i ograniczenia

- Punkt odniesienia: 4K HEVC FAST, pełny HUD, AMD Native D3D11 ≈ 40–43 Render FPS (dane użytkownika); w przebiegu dev 5Z na GX020079 (300 kl.) `render_fps` = 34,1 (`etap5z_artifacts/Z1_dev_hdr.mp4.amd_profile.json`), `above_compose` śr. 10,1 ms — wąskie gardło leży po stronie przygotowania HUD (CPU), nie konwersji wideo [MEASURED w 5Z].
- Wariant B zmienia koszt GPU kroku konwersji o **−0,7…−0,9 ms/kl.** [MEASURED izolowanie] → wpływ na Render FPS **neutralny (±1 FPS)** [ESTIMATED]. Utrzymanie ~40 FPS jest **realne** [ESTIMATED], ale **NOT VERIFIED** w SportCamHUD — wymaga testu harnessem po implementacji.
- Ograniczenia: pomiary w sondzie bez równoległego dekodowania i HUD; iGPU laptopa zmienia zegary (rozrzut serii 2,4–4,6 ms); produkcyjny Blt 709 nieodtworzony 1:1; pętla „konwersja+AMF” sondy niereprezentatywna. Peak detection: niezmierzony.
- Wariant Main10 HDR: NOT VERIFIED dla Render FPS; [ESTIMATED] zbliżony do obecnego (brak Blt, droższy fused P010).

## 19. Minimalny plan implementacji (do akceptacji; nic nie wdrożono)

1. **Detekcja źródła** [Python]: z ffprobe (już zbierane) `color_transfer` (arib-std-b67 / smpte2084 / inne), `color_primaries`, `color_space`, `color_range`, bit depth → przekazanie do DLL jako parametry konfiguracji.
2. **DLL (przebudowa wymagana)**, `d3d11_vp_pipeline.cpp`:
   a. Shader `HlgToSdrCS` (z `hlg_tonemap_cs.hlsl`, mode 2) kompilowany obok istniejących; parametry: zakres wejścia, Lw 1000, biel 203, wyjście full-range (kontrakt fused).
   b. Dla źródła HLG/PQ: Dispatch shadera zamiast `VideoProcessorBlt` (te same tekstury dekodera — SRV `R16/R16G16` jak w ścieżce 8K, i ta sama pula NV12 + UAV z `CreateUnorderedAccessView1`); znaczniki GPU w istniejącym pierścieniu timestampów.
   c. Dla SDR: bez zmian. Dla 10-bit SDR (DJI BT.709): Blt jak dziś, ale z poprawnym zakresem (osobna, mała poprawka).
   d. Wariant PQ: ta sama ścieżka z EOTF PQ zamiast HLG+OOTF.
   e. AMF HEVC: ustawić VUI dla SDR (primaries 1, transfer 1, matrix 1, studio) — dziś „reserved”.
3. **Telemetria**: log wybranej ścieżki (`[HDR] source=HLG mode=SDR_TONEMAP`), czas GPU shadera w profilu.
4. **Testy**: harness 300 kl. GX020079 (Render FPS, porównanie klatek 30/150/270 z referencją), kontrola SDR (DJI_0010, 20261012-0625) — brak regresji, test 8K (osobna ścieżka compute — nie zmieniać w 1. kroku).
5. **Później (opcjonalnie)**: dynamiczna detekcja szczytu; tryb Main10 (§15) z poprawną detekcją możliwości przez próbny `Init(P010)`; opcja GUI (§ niżej).
ABI: dodanie parametrów koloru prawdopodobnie wymaga rozszerzenia struktury konfiguracji → **zmiana ABI (9→10)** do potwierdzenia przy projektowaniu.

### Polityka docelowa i opcja GUI (propozycja, niezaimplementowana)
| źródło | sprzęt | zachowanie | status |
|---|---|---|---|
| SDR | dowolny | SDR → SDR (jak dziś) | działa (produkcja) |
| HLG | Main10 dostępne | „Zachowaj HDR”: HLG Main10, BT.2020, HUD 203 nit | sprzęt: **przetestowany** (encode); pipeline: architektura |
| HLG | Main10 niedostępne | poprawny HLG→SDR (wariant B) | shader: **przetestowany w sondzie**; integracja: architektura |
| PQ/HDR10 | analogicznie | PQ zachowane z metadanymi HDR10 / PQ→SDR (EOTF PQ + BT.2390) | **nieprzetestowane** (brak materiału PQ) |
Opcja „Tryb HDR”: **Automatycznie** (domyślnie: HDR→SDR, bo wynik SDR jest uniwersalnie odtwarzalny i zgodny z obecnym oczekiwaniem użytkowników), **Zachowaj HDR** (gdy brak Main10 — komunikat i automatyczny powrót do „Konwertuj do SDR”, nigdy cichy 8-bit z tagami HDR), **Konwertuj do SDR**.

## 20. Otwarte problemy i ryzyka

- Produkcyjny koszt Blt 709 na powierzchniach dekodera — nieodtworzony w sondzie (E_FAIL na teksturze nie-dekoderowej).
- Tryby VP GHLG/G2084 — crash sterownika mimo `Check…=supported`: nie używać; ryzyko w razie przyszłych „szybkich poprawek flagami”.
- `HEVC_CAP_MAX_PROFILE` zaniża (1 zamiast 2) — detekcja musi być empiryczna.
- AMF runtime 1.4.31 vs SDK 1.5.2 — działa, ale nowe właściwości 1.5 mogą być ignorowane.
- Wygląd HLG→SDR zależy od bieli (203) i peak detection; statyczny BT.2390 daje jaśniejsze sceny słoneczne niż libplacebo domyślny — może wymagać detekcji szczytu lub decyzji estetycznej użytkownika.
- HUD w BT.601 vs wideo BT.709 (istniejące); VUI SDR „reserved”.
- `colr` w MP4 po `-c copy` dla Main10: NOT VERIFIED. Materiał PQ: brak — NOT VERIFIED. 8K HLG: osobna ścieżka compute — NOT VERIFIED.
- Pomiar łączony konwersja+AMF w sondzie niestabilny; FPS produkcyjny tylko szacowany.

## 21. Potwierdzenie braku zmian produkcyjnych

Nie zmieniono: DLL, ABI/eksportów, AMF VBR/QP/presetów, mapy GPU, LEAN, Compass, Gauge, BAR, Direct Copy Audio, Single Live Mux, setts, finalizacji, kolejki, FIT/GPX, Garmin, SmartSync, Intel/NVIDIA, portable, MSIX, `def_layout.json`, sterownika, plików GoPro. Brak przetwarzania audio. Sondy działają w osobnych exe w `Raporty/etap5z1_artifacts/build/`; shadery tylko tam. Pełny zestaw testów i pełny film — nieuruchamiane. Produkcyjny harness — nieuruchamiany (brak zmian do potwierdzenia).

## 22. SHA256 DLL

`runtime/amd/bin/telem_amd_native.dll` przed: `5ad042bb8f61db32af52df2a3ea1fdd77c40b253866ce28724c6fe01e4a3c0df`, po: `5ad042bb8f61db32af52df2a3ea1fdd77c40b253866ce28724c6fe01e4a3c0df` — **UNCHANGED**.

## 23. def_layout.json

Przed: `65fa8390d1cda70ed8d115631a75e35559b24b9990e1ca15f944f0fb371606f4`, po: identyczny — **UNCHANGED** w tym etapie (plik był już zmodyfikowany względem HEAD przed etapem; nie dotykano go).

## 24. Ścieżki

`Raporty/etap5z1_artifacts/`:
- `amf_main10_probe.cpp`, `build/probe_main8.log`, `build/probe_main10.log`, `build/sps_trace.txt`, `build/hwdecode_main10.txt` — test AMF;
- `d3d11_hlg_probe.cpp`, `hlg_tonemap_cs.hlsl`, `d3d11_probe_run1.log`, `d3d11_out/*.log` — VP/shader/AMF;
- `bench/run_ffbench*.sh`, `bench/ffbench_summary.txt`, `bench/log_*.txt` — FFmpeg;
- `quality_compare.py`, `cmp/quality_compare.json`, `cmp/cs_vs_libplacebo_static.json`, `cmp/sheet_f30|150|270.jpg` — jakość;
- `build/build.cmd`, `build/build_d3d11.cmd`, `build/*.exe` — kompilacja sond (exe nie do commitu).
Duże pliki (strumienie HEVC 8–16 MB, surowe klatki P010/NV12, PNG 4K) usunięto po pomiarach. Wcześniejsze: `Raporty/RAPORT_SPORTCAMHUD_ETAP_5Z_HDR_HLG_AUDIT.md` (nienadpisany), `Raporty/etap5z_artifacts/`.
