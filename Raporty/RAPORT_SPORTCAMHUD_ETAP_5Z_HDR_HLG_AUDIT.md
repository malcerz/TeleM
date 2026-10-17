# SPORTCAMHUD — ETAP 5Z: audyt HDR/HLG, 10-bit i kolorów AMD (CZĘŚCIOWY)

2026-10-15. **STATUS: BLOCKED (audyt przerwany limitem użycia)** — punkty 1–4 i 6 wykonane, 5 (test Main10) i 8 (pomiar kosztu tone mappingu) niewykonane. Zmiany produkcyjne: **NONE**.

## 1. Git
HEAD `f3ba1bc`, working tree bez nowych zmian w kodzie (tylko artefakty w `Raporty/etap5z_artifacts/`). DLL, audio, renderer, `def_layout.json` nietknięte.

## 2. Sprzęt [API]
AMD Ryzen 7 7730U, iGPU Radeon Graphics (Vega, gfx90c, PCI `VEN_1002&DEV_15E7`), sterownik 31.0.21925.1001 (2026-05-20). AMF SDK w repo 1.5.2.

## 3. Nagrania [VIDEO TEST, ffprobe] (`etap5z_artifacts/inputs.json`)
- GoPro (GX020079, GX010297, GX010321, GX010349, GX010361; 8K GX010369): HEVC Main 10, `yuv420p10le`, **full range (pc)**, BT.2020nc / BT.2020 / **HLG (arib-std-b67)** — HDR HLG. Brak mastering display / CLL (dla HLG typowe).
- DJI (2 pliki): HEVC Main 10, tv, BT.709/BT.709/BT.709 — 10-bit bez transferu HDR (możliwy profil log oznaczony jako 709 — NOT VERIFIED).
- Kontrola SDR 8-bit: DJI_0010 (GoPro folder), 20261012-0625.mp4.

## 4. Pipeline [CODE]
MF dekoder → `DXGI_FORMAT_P010` (`telem_amd_native.cpp:1596`) → `SetupVideoProcessor(P010, NV12)` (`telem_amd_native.cpp:1895`) → pula wyjściowa NV12 (`d3d11_vp_pipeline.cpp:698`) → **`VideoProcessorBlt` P010→NV12 (`d3d11_vp_pipeline.cpp:4664`)** — tu 10 bit → 8 bit. Przestrzeń barw VP w trybie produkcyjnym `AMD_VP_COLORSPACE_MODE=0` (`d3d11_vp_pipeline.cpp:610-631`): wejście `YCbCr_Matrix=1` (BT.709), `Nominal_Range=0` (domyślny = studio), wyjście BT.709 studio; brak informacji o transferze HLG i primaries BT.2020. HUD kompozytowany w NV12 (fused compute). AMF HEVC `Init(AMF_SURFACE_NV12)`; dla HEVC nie są ustawiane właściwości koloru (`d3d11_amf_encoder.cpp`, ustawiane tylko dla AVC/AV1). Mux `-c copy` bez tagów koloru. Wynik: `yuv420p`, transfer bt709, primaries/matrix nieoznaczone.

## 5. Przyczyna i poprawność konwersji [VIDEO TEST] (`etap5z_artifacts/cmp/hlg_compare.json`)
Porównanie klatek 30/150/270 eksportu AMD (300 kl., GX020079) z interpretacjami źródła (centralny wycinek bez HUD, RGB 8-bit):
| wariant | MAE vs eksport (f30/f150/f270) |
|---|---|
| macierz BT.709 + zakres ograniczony, bez transferu | **4.1 / 5.0 / 2.5** |
| BT.709 + pełny zakres | 8.9 / 9.6 / 9.5 |
| poprawna macierz BT.2020 + pełny zakres (HLG bez tone mappingu) | 8.6 / 9.3 / 9.9 |
| zscale HLG→linear(npl 100)→BT.709→tonemap hable | 21.6 / 22.2 / 9.8 |
| libplacebo → BT.709/BT.1886 (domyślny tone mapping) | 17.9 / 18.1 / 7.3 |
Wniosek: obecny wynik = **E (kombinacja)**: obcięcie do 8 bit (C), zła macierz BT.709 zamiast BT.2020 i odczyt pełnego zakresu jako ograniczonego (B + błąd zakresu), brak linearizacji/tone mappingu/mapowania gamutu, oznaczenie jako SDR bt709 (D). Skutki: pikseli przepalonych (≥250) 25.4% / 25.6% vs 14.9–16.3% / 22.3–22.8% przy poprawnym zakresie (≈ +3…+10 pp prześwietlenia), więcej czystej czerni (0.4–5.7% vs 0.004–0.6%), kolory BT.2020 wyświetlane jako BT.709 (niedosycone/przesunięte względem referencji tone-mapped: nasycenie 0.23–0.26 vs 0.28–0.39). Obecna konwersja HLG→SDR: **INCORRECT**.

## 6. Main10 [API / NOT VERIFIED]
Dekodowanie HEVC Main10: działa (MF zwraca P010) [HARDWARE TEST]. VP przyjmuje P010 (`[VP FORMATS] P010 In: YES` w logach) [API]. Kodowanie HEVC Main10 przez AMF: `telem_amd_probe_capabilities` zwraca `hevc_main10=0`, ale kod tej funkcji **nie sprawdza** Main10 (pole zawsze 0) — to nie jest dowód. **AMD Main10 encode: NOT VERIFIED** — wymagany izolowany test AMF (Init `AMF_SURFACE_P010`, `HEVC_PROFILE_MAIN_10`, `COLOR_BIT_DEPTH_10`) — niewykonany.

## 7. Tone mapping GPU
libplacebo (Vulkan) działa na tym GPU funkcjonalnie (wygenerował klatki referencyjne) [HARDWARE TEST]. Koszt/FPS: **NOT VERIFIED**. Docelowo sensowny jest shader w istniejącym fused compute (P010 → linear HLG → BT.2390/BT.2408 tone map + gamut BT.2020→709 → BT.709 + dither → NV12) zamiast VP Blt — [INFERENCE], koszt niezmierzony.

## 8. Rekomendacja wstępna [INFERENCE]
- Wariant B (poprawny HDR→SDR na GPU) jako domyślny dla HLG na tym sprzęcie; minimalny pierwszy krok: poprawne flagi VP (BT.2020, pełny zakres) usuną błąd macierzy/zakresu, ale nie tone mapping.
- Wariant A (HDR Main10) dopiero po teście AMF Main10 i z mapowaniem HUD (sRGB→HLG, biel HUD ~203 nit).
- Decyzje użytkownika: wybór wariantu, zgoda na zmiany DLL, ewentualna opcja „HDR: zachowaj / konwertuj do SDR”.

## 9. Pozostało do zrobienia
Test AMF Main10/P010 (sonda), pomiar kosztu tone mappingu GPU i FPS, analiza HUD na HDR, pełny plan implementacji.

## 10. Potwierdzenie
Brak zmian w DLL, audio, rendererze, portable, `def_layout.json`. Duże artefakty (MP4, zrzut 4K) usunięte.
