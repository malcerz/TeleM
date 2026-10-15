# RAPORT — SportCamHUD: rzeczywisty odczyt QP z AMD AMF (HEVC VBR)

Data: 2026-10-15. Gałąź: `fix/gui-freeze-hud-composite`. HEAD początkowy: `f14e45f`.

## 1. Zadanie
GUI pokazywało `RC: VBR | QP avg: N/A`. Ustalić, dlaczego AMF nie dostarcza statystyk QP, i naprawić odczyt rzeczywistych wartości z kodera sprzętowego bez wpływu na wydajność.

## 2. Stan początkowy
- Working tree przed zmianą (niezmieniany przez to zadanie): `def_layout.json`, `src/ffmpeg/intel_native_exporter.py`, `src/ffmpeg/nvidia_native_exporter.py`, `Raporty/RAPORT_SPORTCAMHUD_ETAP_5R_F_...md`, nieśledzone `live_av_mux.py`, `tests/test_live_av_mux.py`, `runtime/amd/`.
- DLL produkcyjna: `runtime/amd/bin/telem_amd_native.dll` SHA256 `380f86b044ab61eefb60c0e1d6fd386dcfe0e95d9c12dac756a93bf8e71ea50b` (ABI 9).
- AMF SDK w drzewie: 1.5.2. Sterownik: AMD Radeon(TM) Graphics (gfx90c) 31.0.21925.1001.

## 3. Przyczyna braku QP
`d3d11_amf_encoder.cpp` (stara linia 244) ustawiał `AMF_VIDEO_ENCODER_HEVC_STATISTICS_FEEDBACK` wyłącznie na komponencie enkodera (`m_encoder->SetProperty`). Wynik tej operacji był ignorowany, a w rzeczywistości wynosi **`AMF_INVALID_ARG` (4)**: komponent HEVC nie przyjmuje tej właściwości. Flaga nigdy nie była ustawiana na wejściowej `AMFSurface`, a według AMF HEVC API (i `libavcodec/amfenc.c`) jest to właściwość per‑klatka ustawiana na powierzchni przed `SubmitInput`. W efekcie `GetProperty` na buforze wyjściowym zwracało **`AMF_NOT_FOUND` (11)** dla FRAME_QP, AVERAGE_QP, MIN_QP i MAX_QP na każdej klatce → `samples = 0` → `N/A`.

Dowód (ta sama DLL, przełącznik diagnostyczny `TELEM_AMD_QP_FEEDBACK_SURFACE=0` odtwarza stare zachowanie), test samego enkodera 4K, 120 klatek, 40 Mb/s:

| | encoder SetProperty | surface SetProperty | GetProperty FRAME/AVG/MIN/MAX | próbki |
|---|---|---|---|---|
| A: flaga tylko na enkoderze (stan sprzed poprawki) | 4 (INVALID_ARG) | — | 11/11/11/11 (NOT_FOUND) | 0/120 |
| B: flaga na AMFSurface (poprawka) | 4 (INVALID_ARG) | 0 (AMF_OK) | 0/0/0/0 (AMF_OK) | 120/120 |

`samples=0` nie wynikało więc z braku wsparcia sprzętowego: sprzęt i sterownik dostarczają statystyki po poprawnym żądaniu.

## 4. Poprawka (minimalna)
- `native/d3d11_amf_pipeline/src/d3d11_amf_encoder.cpp`
  - `CreateSurface()`: dla HEVC po `SetPts` ustawia `STATISTICS_FEEDBACK=true` na `AMFSurface`. Dotyczy obu ścieżek (produkcyjna `CreateSurface`→`SubmitSurface` w `telem_amd_native.cpp` oraz `SubmitTexture`), raz na klatkę, przed każdym `SubmitInput` (przy ponowieniu po `AMF_INPUT_FULL` ta sama powierzchnia ma już flagę).
  - `QueryPacket()`: odczyt wszystkich 4 statystyk z `AMFBuffer` zwróconego przez `QueryOutput`, zapis każdego `AMF_RESULT`. Seria średniej eksportu = per‑klatkowe **AVERAGE_QP** (średni QP bloków CTB), tylko wartości z zakresu 0..51. FRAME_QP (bazowy QP rate control) nie jest już wpychany do tej serii jako fallback (bazowy QP nie jest nazywany średnią blokową). Zliczanie próbek I (IDR/I) i P.
  - Wynik `SetProperty` na enkoderze jest zapisywany (wywołanie zostaje dla zgodności), logowany przy inicjalizacji.
  - Opcjonalny ślad `TELEM_AMD_QP_TRACE=1` (pierwsze 120 wyjść) i przełącznik A/B `TELEM_AMD_QP_FEEDBACK_SURFACE=0` (domyślnie flaga włączona).
- `d3d11_amf_encoder.h`: struktura `AMFEncoderQPFeedbackDiag`.
- `telem_amd_native.cpp`: nowy, addytywny eksport `telem_amd_get_encoder_qp_feedback_diag` (ABI pozostaje 9, istniejące 81 eksportów bez zmian, +1 nowy).
- `src/ffmpeg/amd_native_exporter.py`: struktura ctypes + jedna linia diagnostyczna `[AMD ENCODER] QP feedback diag: ...` na końcu eksportu. Istniejące API `telem_amd_get_encoder_qp_stats` i prezentacja GUI bez zmian.

Znaczenie wartości w GUI: `QP` = AVERAGE_QP ostatniej klatki zwróconej przez `QueryOutput` (ostatnia zakodowana, nie ostatnia wysłana; opóźnienie = głębokość kolejki AMF), `QP avg` = średnia arytmetyczna AVERAGE_QP ze wszystkich rzeczywiście otrzymanych klatek eksportu.

Nie zmieniano: VBR/bitrate, presetów, Direct Copy Audio, Single Live Mux, finalizacji, HUD, Intel/NVIDIA, FIT/GPX, `def_layout.json`. Nie włączono PRE-ANALYSIS, PSNR/SSIM ani BLOCK_QP_FEEDBACK.

## 5. DLL
- Stara: `380f86b044ab61eefb60c0e1d6fd386dcfe0e95d9c12dac756a93bf8e71ea50b`, kopie: `runtime/amd/bin/telem_amd_native.dll.bak_pre_qpfeedback`, `native/d3d11_amf_pipeline/bin/telem_amd_native.dll.bak_pre_qpfeedback`.
- Nowa: `6c43f398fbb1421c6dbb21928309f996e9967afea8040c2d42af6c72ba7f29ca` (MSVC Release, `cmake --build build_msvc --config Release --target telem_amd_native`), zainstalowana w `runtime/amd/bin/`.
- ABI: `telem_amd_get_abi_version()` = 9; dumpbin: brak usuniętych eksportów, dodany 1.

## 6. Testy
### 6.1 Sam enkoder AMF (rzeczywisty sprzęt AMD)
`Raporty/amd_real_qp_feedback_20261015/amf_qp_probe.cpp` (produkcyjna klasa `D3D11AMFEncoder`, syntetyczne tekstury NV12 4K, bez dekodowania). Logi: `probe_A_encoder_flag_only.log`, `probe_B_surface_flag.log`. Wynik B: 120/120 próbek, I=4, P=116, średnia 48.40, min 37, max 50 (wysokie QP przez szumową treść syntetyczną). Przykłady (B):

| wyjście | typ | FRAME_QP | AVERAGE_QP | MIN_QP | MAX_QP |
|---|---|---|---|---|---|
| 1 | IDR | 15 | 39 | 11 | 51 |
| 2 | P | 37 | 37 | 37 | 41 |
| 5 | P | 39 | 39 | 39 | 39 |
| 31 | IDR | 49 | 48 | 45 | 49 |
| 61 | IDR | 50 | 49 | 46 | 50 |
| 120 | P | 49 | 49 | 49 | 49 |

Na klatkach IDR FRAME_QP ≠ AVERAGE_QP i MIN ≠ MAX, więc statystyki należą do konkretnej klatki (I i P), a nie są wartością globalną. Strumienie A i B mają tę samą wielkość (19 446 864 B): flaga nie zmienia kodowania.

### 6.2 Krótki eksport (kanoniczny harness `SportCamHUD.py --test-amd-export`)
Para kanoniczna z BENCHMARKS.md: `GX020079.mp4` + `GX020079.fit` (lokalizacja `F:\_DEV\BikeRideHUD-amd\Video\`), layout `def_layout.json` (working tree), 300 klatek od 0 s, HEVC FAST, 40M, AMD_NATIVE_D3D11. Skrypt: `amd_real_qp_feedback_20261015/run_export_ab.py`.

| przebieg | DLL | Render FPS | efektywne FPS (krótki run) | QP w GUI (koniec) | próbki |
|---|---|---|---|---|---|
| A direct | stara | 41.702 | 25.16 | `RC: VBR \| QP avg: N/A` | 0 |
| B direct | nowa | 41.911 | 27.33 | `RC: VBR \| QP: 30 \| QP avg: 33.6` | 300 |
| C direct | nowa (zainstalowana) | 41.894 | 28.9 | `RC: VBR \| QP: 30 \| QP avg: 33.6` | 300 |
| D queue | nowa (zainstalowana) | 41.862 | 28.1 | `RC: VBR \| QP: 30 \| QP avg: 33.6` | 300 |

- Diag B/C/D: `encoder_set=4 surface_set=0 ok=300 fail=0 outputs=300 get_results=0/0/0/0 samples=300/300/300/300 intra=10 inter=290`.
- Seria AVERAGE_QP eksportu: średnia 33.60, min 19, max 37.
- QP w GUI w trakcie (przebieg C, tekst z `hud_state.compression_text`): f3 `QP: 19 | avg 19.0`, f30 `32 | 25.9`, f60 `34 | 30.0`, f90 `36 | 31.9`, f120 `37 | 33.2`, f210 `33 | 34.4`, f300 `30 | 33.6`. Wartości zmieniają się zgodnie z treścią i mieszczą w 0..51.
- Kolejka (tryb `queue`) i GUI odbierają statystyki (`live_qp_samples` 100/100 z wartością).
- Bitrate: ffprobe strumienia wideo A i B = 38 916 459 b/s (cel 40M), 300 klatek, 3840x2160, 30000/1001. Pliki MP4 A i B są **bajtowo identyczne** (SHA256 `80f21814…a06050`), więc poprawka nie zmienia bitstreamu ani VBR. Pliki MP4 usunięto po pomiarach.
- Wpływ na FPS: brak spadku (Render FPS 41.70 → 41.86–41.91; różnice w granicach szumu pojedynczego krótkiego przebiegu). Efektywne FPS krótkiego runu zawiera stały koszt startu i finalizacji.
- Testy jednostkowe: `tests/test_amd_vbr_qp_status.py`, `test_amd_qp_governance.py`, `test_amd_vbr_governance.py`: 22 passed.
- `def_layout.json`: harness GUI zapisuje plik przy zamknięciu; treść bajtowo identyczna z kopią sprzed testów (porównanie `fc /b`), nie commitowano.

## 7. Izolacja backendów
Zmiany wyłącznie w natywnej ścieżce AMD (`d3d11_amf_pipeline`) i `amd_native_exporter.py`. AVC/AV1 w enkoderze nie dostają flagi (warunek HEVC). Intel/NVIDIA nietknięte.

## 8. Ryzyka i nierozwiązane
- `SetProperty(STATISTICS_FEEDBACK)` na komponencie zwraca `AMF_INVALID_ARG`; zostawiony (nieszkodliwy, logowany).
- „Aktualny” QP dotyczy ostatniej klatki zwróconej z enkodera (opóźnienie kilku klatek względem wysłanej), co wynika ze źródła danych `QueryOutput`.
- Natywny `std::cout` z DLL w procesie potomnym nie trafia do logu harnessu, dlatego dowody per‑klatkę pochodzą z testu enkodera i z `hud_state`; podsumowanie diag trafia do logu przez Pythona.
- Pełny 1131‑klatkowy benchmark: NOT TESTED (zgodnie z zadaniem tylko krótkie testy).
- Portable `C:\_DEV\SportCamHUD-portable` nadal ma starą DLL (budowa z f14e45f), nie aktualizowano.
- Wersja raportu w commicie `d66bc70` ma uszkodzone kodowanie polskich znaków (błąd zapisu przez PowerShell); naprawione w kolejnym commicie.

## 9. Commit
SHA poprawki: `d66bc7002c39b4f7b21e33a4c0cf8cdd38bc77ea` („fix(amd): request HEVC QP statistics feedback on input surface”). Bez push.

## 10. Podsumowanie
PASS: rzeczywiste QP z AMF dostępne (300/300 próbek, AMF_OK), GUI i kolejka pokazują `RC: VBR | QP: <aktualny> | QP avg: <średni>`, bitstream i Render FPS bez zmian.
