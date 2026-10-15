# RAPORT â€” SportCamHUD: rzeczywisty odczyt QP z AMD AMF (HEVC VBR)

Data: 2026-10-15. GaĹ‚Ä…Ĺş: `fix/gui-freeze-hud-composite`. HEAD poczÄ…tkowy: `f14e45f`.

## 1. Zadanie
GUI pokazywaĹ‚o `RC: VBR | QP avg: N/A`. UstaliÄ‡, dlaczego AMF nie dostarcza statystyk QP, i naprawiÄ‡ odczyt rzeczywistych wartoĹ›ci z kodera sprzÄ™towego bez wpĹ‚ywu na wydajnoĹ›Ä‡.

## 2. Stan poczÄ…tkowy
- Working tree przed zmianÄ… (niezmieniany przez to zadanie): `def_layout.json`, `src/ffmpeg/intel_native_exporter.py`, `src/ffmpeg/nvidia_native_exporter.py`, `Raporty/RAPORT_SPORTCAMHUD_ETAP_5R_F_...md`, nieĹ›ledzone `live_av_mux.py`, `tests/test_live_av_mux.py`, `runtime/amd/`.
- DLL produkcyjna: `runtime/amd/bin/telem_amd_native.dll` SHA256 `380f86b044ab61eefb60c0e1d6fd386dcfe0e95d9c12dac756a93bf8e71ea50b` (ABI 9).
- AMF SDK w drzewie: 1.5.2. Sterownik: AMD Radeon(TM) Graphics (gfx90c) 31.0.21925.1001.

## 3. Przyczyna braku QP
`d3d11_amf_encoder.cpp` (stara linia 244) ustawiaĹ‚ `AMF_VIDEO_ENCODER_HEVC_STATISTICS_FEEDBACK` wyĹ‚Ä…cznie na komponencie enkodera (`m_encoder->SetProperty`). Wynik tej operacji byĹ‚ ignorowany, a w rzeczywistoĹ›ci wynosi **`AMF_INVALID_ARG` (4)**: komponent HEVC nie przyjmuje tej wĹ‚aĹ›ciwoĹ›ci. Flaga nigdy nie byĹ‚a ustawiana na wejĹ›ciowej `AMFSurface`, a wedĹ‚ug AMF HEVC API (i `libavcodec/amfenc.c`) jest to wĹ‚aĹ›ciwoĹ›Ä‡ perâ€‘klatka ustawiana na powierzchni przed `SubmitInput`. W efekcie `GetProperty` na buforze wyjĹ›ciowym zwracaĹ‚o **`AMF_NOT_FOUND` (11)** dla FRAME_QP, AVERAGE_QP, MIN_QP i MAX_QP na kaĹĽdej klatce â†’ `samples = 0` â†’ `N/A`.

DowĂłd (ta sama DLL, przeĹ‚Ä…cznik diagnostyczny `TELEM_AMD_QP_FEEDBACK_SURFACE=0` odtwarza stare zachowanie), test samego enkodera 4K, 120 klatek, 40 Mb/s:

| | encoder SetProperty | surface SetProperty | GetProperty FRAME/AVG/MIN/MAX | prĂłbki |
|---|---|---|---|---|
| A: flaga tylko na enkoderze (stan sprzed poprawki) | 4 (INVALID_ARG) | â€” | 11/11/11/11 (NOT_FOUND) | 0/120 |
| B: flaga na AMFSurface (poprawka) | 4 (INVALID_ARG) | 0 (AMF_OK) | 0/0/0/0 (AMF_OK) | 120/120 |

`samples=0` nie wynikaĹ‚o wiÄ™c z braku wsparcia sprzÄ™towego: sprzÄ™t i sterownik dostarczajÄ… statystyki po poprawnym ĹĽÄ…daniu.

## 4. Poprawka (minimalna)
- `native/d3d11_amf_pipeline/src/d3d11_amf_encoder.cpp`
  - `CreateSurface()`: dla HEVC po `SetPts` ustawia `STATISTICS_FEEDBACK=true` na `AMFSurface`. Dotyczy obu Ĺ›cieĹĽek (produkcyjna `CreateSurface`â†’`SubmitSurface` w `telem_amd_native.cpp` oraz `SubmitTexture`), raz na klatkÄ™, przed kaĹĽdym `SubmitInput` (takĹĽe przy ponowieniu po `AMF_INPUT_FULL` ta sama powierzchnia ma juĹĽ flagÄ™).
  - `QueryPacket()`: odczyt wszystkich 4 statystyk z `AMFBuffer` zwrĂłconego przez `QueryOutput`, zapis kaĹĽdego `AMF_RESULT`. Seria Ĺ›redniej eksportu = perâ€‘klatkowe **AVERAGE_QP** (Ĺ›redni QP blokĂłw CTB), tylko wartoĹ›ci z zakresu 0..51. FRAME_QP (bazowy QP rate control) nie jest juĹĽ wpychany do tej serii jako fallback (nie nazywamy bazowego QP Ĺ›redniÄ… blokowÄ…). Zliczanie prĂłbek I (IDR/I) i P.
  - Wynik `SetProperty` na enkoderze jest zapisywany (zostaje dla zgodnoĹ›ci), logowany przy inicjalizacji.
  - Opcjonalny Ĺ›lad `TELEM_AMD_QP_TRACE=1` (pierwsze 120 wyjĹ›Ä‡) i przeĹ‚Ä…cznik A/B `TELEM_AMD_QP_FEEDBACK_SURFACE=0` (domyĹ›lnie flaga wĹ‚Ä…czona).
- `d3d11_amf_encoder.h`: struktura `AMFEncoderQPFeedbackDiag`.
- `telem_amd_native.cpp`: nowy, addytywny eksport `telem_amd_get_encoder_qp_feedback_diag` (ABI pozostaje 9, istniejÄ…ce 81 eksportĂłw bez zmian, +1 nowy).
- `src/ffmpeg/amd_native_exporter.py`: struktura ctypes + jedna linia diagnostyczna `[AMD ENCODER] QP feedback diag: ...` na koĹ„cu eksportu. IstniejÄ…ce API `telem_amd_get_encoder_qp_stats` i prezentacja GUI bez zmian.

Znaczenie wartoĹ›ci w GUI: `QP` = AVERAGE_QP ostatniej klatki zwrĂłconej przez `QueryOutput` (ostatnia zakodowana, nie ostatnia wysĹ‚ana; opĂłĹşnienie = gĹ‚Ä™bokoĹ›Ä‡ kolejki AMF), `QP avg` = Ĺ›rednia arytmetyczna AVERAGE_QP ze wszystkich rzeczywiĹ›cie otrzymanych klatek eksportu.

Nie zmieniano: VBR/bitrate, presetĂłw, Direct Copy Audio, Single Live Mux, finalizacji, HUD, Intel/NVIDIA, FIT/GPX, `def_layout.json`. Nie wĹ‚Ä…czono PRE-ANALYSIS, PSNR/SSIM ani BLOCK_QP_FEEDBACK.

## 5. DLL
- Stara: `380f86b044ab61eefb60c0e1d6fd386dcfe0e95d9c12dac756a93bf8e71ea50b`, kopie: `runtime/amd/bin/telem_amd_native.dll.bak_pre_qpfeedback`, `native/d3d11_amf_pipeline/bin/telem_amd_native.dll.bak_pre_qpfeedback`.
- Nowa: `6c43f398fbb1421c6dbb21928309f996e9967afea8040c2d42af6c72ba7f29ca` (MSVC Release, `cmake --build build_msvc --config Release --target telem_amd_native`), zainstalowana w `runtime/amd/bin/`.
- ABI: `telem_amd_get_abi_version()` = 9; dumpbin: brak usuniÄ™tych eksportĂłw, dodany 1.

## 6. Testy
### 6.1 Sam enkoder AMF (rzeczywisty sprzÄ™t AMD)
`Raporty/amd_real_qp_feedback_20261015/amf_qp_probe.cpp` (produkcyjna klasa `D3D11AMFEncoder`, syntetyczne tekstury NV12 4K, bez dekodowania). Logi: `probe_A_encoder_flag_only.log`, `probe_B_surface_flag.log`. Wynik B: 120/120 prĂłbek, I=4, P=116, Ĺ›rednia 48.40, min 37, max 50 (wysokie QP przez szumowÄ… treĹ›Ä‡ syntetycznÄ…). PrzykĹ‚ady (B):

| wyjĹ›cie | typ | FRAME_QP | AVERAGE_QP | MIN_QP | MAX_QP |
|---|---|---|---|---|---|
| 1 | IDR | 15 | 39 | 11 | 51 |
| 2 | P | 37 | 37 | 37 | 41 |
| 5 | P | 39 | 39 | 39 | 39 |
| 31 | IDR | 49 | 48 | 45 | 49 |
| 61 | IDR | 50 | 49 | 46 | 50 |
| 120 | P | 49 | 49 | 49 | 49 |

Na klatkach IDR FRAME_QP â‰  AVERAGE_QP i MINâ‰ MAX, wiÄ™c statystyki naleĹĽÄ… do konkretnej klatki (I i P), a nie sÄ… wartoĹ›ciÄ… globalnÄ…. StrumieĹ„ A i B jest bajtowo tej samej wielkoĹ›ci (19 446 864 B), flaga nie zmienia kodowania.

### 6.2 KrĂłtki eksport (kanoniczny harness `SportCamHUD.py --test-amd-export`)
Para kanoniczna z BENCHMARKS.md: `GX020079.mp4` + `GX020079.fit` (lokalizacja `F:\_DEV\BikeRideHUD-amd\Video\`), layout `def_layout.json` (working tree), 300 klatek od 0 s, HEVC FAST, 40M, AMD_NATIVE_D3D11. Skrypt: `amd_real_qp_feedback_20261015/run_export_ab.py`.

| przebieg | DLL | Render FPS | efektywne FPS (krĂłtki run) | QP w GUI (koniec) | prĂłbki |
|---|---|---|---|---|---|
| A direct | stara | 41.702 | 25.16 | `RC: VBR \| QP avg: N/A` | 0 |
| B direct | nowa | 41.911 | 27.33 | `RC: VBR \| QP: 30 \| QP avg: 33.6` | 300 |
| C direct | nowa (zainstalowana) | 41.894 | 28.90 | `RC: VBR \| QP: 30 \| QP avg: 33.6` | 300 |
| D queue | nowa (zainstalowana) | 41.862 | 28.1 | `RC: VBR \| QP: 30 \| QP avg: 33.6` | 300 |

- Diag B/C/D: `encoder_set=4 surface_set=0 ok=300 fail=0 outputs=300 get_results=0/0/0/0 samples=300/300/300/300 intra=10 inter=290`.
- Seria AVERAGE_QP eksportu: Ĺ›rednia 33.60, min 19, max 37.
- QP w GUI w trakcie (przebieg C, tekst z `hud_state.compression_text`): f3 `QP: 19 | avg 19.0`, f30 `32 | 25.9`, f60 `34 | 30.0`, f90 `36 | 31.9`, f120 `37 | 33.2`, f210 `33 | 34.4`, f300 `30 | 33.6`. WartoĹ›ci zmieniajÄ… siÄ™ zgodnie z treĹ›ciÄ… i mieszczÄ… w 0..51.
- Kolejka (tryb `queue`) i GUI odbierajÄ… statystyki (`live_qp_samples` 100/100 z wartoĹ›ciÄ…).
- Bitrate: ffprobe strumienia wideo A i B = 38 916 459 b/s (cel 40M), 300 klatek, 3840x2160, 30000/1001. Pliki MP4 A i B sÄ… **bajtowo identyczne** (SHA256 `80f21814â€¦a06050`), wiÄ™c poprawka nie zmienia bitstreamu ani VBR.
- WpĹ‚yw na FPS: brak spadku (Render FPS 41.70 â†’ 41.86â€“41.91; rĂłĹĽnice w granicach szumu pojedynczego krĂłtkiego przebiegu). Efektywne FPS krĂłtkiego runu zawiera staĹ‚y koszt startu/finalizacji.
- Testy jednostkowe: `tests/test_amd_vbr_qp_status.py`, `test_amd_qp_governance.py`, `test_amd_vbr_governance.py`: 22 passed.
- `def_layout.json`: harness GUI zapisuje plik przy zamkniÄ™ciu; treĹ›Ä‡ bajtowo identyczna z kopiÄ… sprzed testĂłw (porĂłwnanie `fc /b`), nie commitowano.

## 7. Izolacja backendĂłw
Zmiany wyĹ‚Ä…cznie w natywnej Ĺ›cieĹĽce AMD (`d3d11_amf_pipeline`) i `amd_native_exporter.py`. Kod AVC/AV1 w enkoderze nie dostaje flagi (warunek HEVC). Intel/NVIDIA nietkniÄ™te.

## 8. Ryzyka i nierozwiÄ…zane
- `SetProperty(STATISTICS_FEEDBACK)` na komponencie zwraca `AMF_INVALID_ARG`; zostawiony (nieszkodliwy, logowany).
- â€žAktualnyâ€ť QP dotyczy ostatniej klatki zwrĂłconej z enkodera (opĂłĹşnienie kilku klatek wzglÄ™dem wysĹ‚anej), co jest zgodne ze ĹşrĂłdĹ‚em danych `QueryOutput`.
- Natywny `std::cout` z DLL w procesie potomnym nie trafia do logu harnessu, dlatego dowody perâ€‘klatkÄ™ pochodzÄ… z testu enkodera i z `hud_state`; podsumowanie diag trafia do logu przez Pythona.
- PeĹ‚ny 1131â€‘klatkowy benchmark: NOT TESTED (zgodnie z zadaniem tylko krĂłtkie testy).
- Portable `C:\_DEV\SportCamHUD-portable` nadal ma starÄ… DLL (budowa z f14e45f), nie aktualizowano.

## 9. Commit
SHA: patrz commit â€žfix(amd): request HEVC QP statistics feedback on input surfaceâ€ť (podany w odpowiedzi koĹ„cowej i ntfy).

## 10. Podsumowanie
PASS: rzeczywiste QP z AMF dostÄ™pne (300/300 prĂłbek, AMF_OK), GUI i kolejka pokazujÄ… `RC: VBR | QP: <aktualny> | QP avg: <Ĺ›redni>`, bitstream i Render FPS bez zmian.
