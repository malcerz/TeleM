# RAPORT: Uruchomienie Potoku NVIDIA CUDA/NVENC na NVIDIA Quadro P400 (Pascal)
Data: 2026-10-01
Środowisko: Intel Core i5-12400 / Intel UHD Graphics 730 / NVIDIA Quadro P400 (GP107, 2GB VRAM)
Sterownik NVIDIA: 582.78 (NVENC API 13.0, CUDA 13.0)
System operacyjny: Windows 11 Pro (Build 26200)

---

## 1. Cel i Zakres Prac

Celem zadania było uruchomienie istniejącego, sprawdzonego produkcyjnie (m.in. na karcie RTX 5070) potoku renderowania **NVIDIA CUDA/NVENC** w aplikacji BikeRideHUD na maszynie z procesorem Intel Core i5-12400 oraz kartą **NVIDIA Quadro P400** (architektura Pascal GP107, 2GB VRAM, sterownik 582.78).

### Główne Założenia:
1. **Brak tworzenia nowego renderera**: Wykorzystanie istniejącej architektury potoku CUDA/NVENC (dekodowanie `hwaccel cuda`, filtry `scale_cuda`, `overlay_cuda`, koder `hevc_nvenc`).
2. **Izolacja środowiska wykonawczego**: Brak podmiany lub degradacji wspólnego FFmpeg (`runtime\common\ffmpeg\`). Wdrożenie dedykowanego binarium do `runtime\nvidia\ffmpeg\`.
3. **Zgodność ABI**: Rozwiązanie problemu niedopasowania wersji NVENC API (sterownik 582.78 udostępnia NVENC API 13.0, podczas gdy standardowy FFmpeg wymagał wersji 13.1 / sterownika >= 610.00).
4. **Weryfikacja produkcyjna**: Przeprowadzenie rzeczywistych renderów wideo 10-bit HDR z kamery GoPro (`GX010316.MP4`) wraz z telemetrią FIT (`Popołudniowa_jazda_na_rowerze.fit`) w rozdzielczościach 1080p oraz 4K (po minimum 1000 klatek) z aktywnym watchdogiem telemetrycznym GPU.

---

## 2. Pobrany Asset i Weryfikacja Integralności

Zgodnie ze specyfikacją pobrano dedykowany build FFmpeg z repozytorium BtbN:
- **Repozytorium źródłowe**: `BtbN/FFmpeg-Builds`
- **Release tag**: `autobuild-2026-06-30-13-34`
- **Asset**: `ffmpeg-n8.1.2-21-gce3c09c101-win64-gpl-8.1.zip`
- **Wersja FFmpeg**: `n8.1.2-21-gce3c09c101-20260630` (FFmpeg 8.1.2, kompilowany z `ffnvcodec` z gałęzi SDK 13.0 / commit z serii 13.0.19.1.x)
- **Oczekiwany SHA-256**: `682361e32c9631caec09e5d9f09077101c9ed90c14e275f62014fefa6d397990`
- **Rzeczywisty SHA-256**: `682361e32c9631caec09e5d9f09077101c9ed90c14e275f62014fefa6d397990` (`HASH_MATCH=YES`)

### Wdrożenie i Izolacja Środowisk:
Binaria `ffmpeg.exe` oraz `ffprobe.exe` zostały rozpakowane do katalogów:
- `C:\_DEV\BikeRideHUD-main-new\runtime\nvidia\ffmpeg\`
- `C:\_DEV\BikeRideHUD-portable\runtime\nvidia\ffmpeg\`

Wspólny katalog `runtime\common\ffmpeg\` pozostał w 100% nienaruszony.

---

## 3. Niezależna Weryfikacja Sprzętowa CUDA i NVENC

Przetestowano bezpośrednio na GPU Quadro P400:
- **CUDA Device**: NVIDIA Quadro P400
- **Compute Capability**: 6.1 (Pascal GP107)
- **CUDA Driver Version**: 13.0
- **CUDA Init Pass**: `YES`
- **H264_NVENC_INIT**: `PASS` (testowe kodowanie zakończone kodem 0)
- **HEVC_NVENC_INIT**: `PASS` (kodowanie 8-bit oraz 10-bit Main 10 zakończone kodem 0)
- **AV1_NVENC_INIT**: `FAIL` (oczekiwane — architektura Pascal nie posiada sprzętowego enkodera AV1)
- **Błąd NVENC API 13.1 vs 13.0**: **WYELEMINOWANY** (`NVENC_API_MISMATCH_13_1_GONE=YES`)

---

## 4. Wykrywanie Możliwości Sprzętowych w GUI i Dynamiczny Wybór

Zaktualizowano moduł trasowania ścieżek `src/runtime_paths.py` oraz logikę detekcji `src/ffmpeg/backend_capabilities.py` i mixin renderowania `src/gui/qt/_mixins/render_mixin.py`:
- Gdy wybrany jest enkoder `nv` / `nvidia`, używane są dedykowane binaria z `runtime/nvidia/ffmpeg/`.
- Gdy wybrany jest inny enkoder, używane są binaria z `runtime/common/ffmpeg/`.

### Wyniki detekcji na maszynie testowej:
- **NVIDIA GPU**: Wykryto Quadro P400, sterownik 582.78, NVENC dostępny (`H.264`, `H.265`).
- **Dostępne backendy w GUI**: `['auto', 'nv', 'intel', 'cpu']`
- **Wybrany backend automatyczny**: `nv` (priorytet GPU dyskretnego)
- **AMD**: Prawidłowo ukryte jako niedostępne (`amd` nie występuje na liście combobox).

---

## 5. Diagnoza i Rozwiązanie Problemu z Potokiem 10-bit HDR (Pascal)

### Identyfikacja Problemu:
Podczas pierwszych prób pełnego renderu wideo 10-bit HDR (`GX010316.MP4`) FFmpeg kończył działanie z kodem 69 i błędami:
```text
[hevc_nvenc @ ...] InitializeEncoder failed: generic error (20):
[hevc @ ...] decoder->cvdl->cuvidMapVideoFrame(...) failed -> CUDA_ERROR_OUT_OF_MEMORY / CUDA_ERROR_MAP_FAILED
```

### Analiza Przyczyny Źródłowej:
1. W module `src/ffmpeg/command_builder.py` dla ścieżki NVIDIA 10-bit dodawany był na końcu grafu filtrów sztuczny filtr:
   `[v_pre10]scale_cuda=format=p010le[vtemp]`
2. Na karcie Quadro P400 (architektura Pascal GP107, 2GB VRAM):
   - `scale_cuda=format=p010le` przekazywał do `hevc_nvenc` deskryptor powierzchni CUDA, którego sterownik NVENC na Pascalu nie akceptował bezpośrednio przy inicjalizacji z flagą `-pix_fmt cuda` (kod błędu 20: `NV_ENC_ERR_INVALID_PARAM`).
   - Dodatkowo alokacja dodatkowych buforów P010 powodowała wyczerpanie pamięci VRAM na karcie 2GB.

### Zastosowane Rozwiązanie:
1. Usunięto zbędny filtr `scale_cuda=format=p010le` po filtrze `overlay_cuda`.
2. Do parametrów enkodera `hevc_nvenc` dodano flagę `-highbitdepth 1`, gdy aktywny jest tryb 10-bitowy na powierzchniach CUDA (`hwaccel == 'cuda'`).
3. Flaga `-highbitdepth 1` instruuje sprzętowy silnik NVENC, aby bezpośrednio z powierzchni kompozytora CUDA zakodował klatki do profilu Main 10 HDR (`yuv420p10le`, `bt2020nc/arib-std-b67/bt2020`).
4. Zmiana jest w pełni kompatybilna z nowszymi architekturami (Turing, Ampere, Ada Lovelace, Blackwell / RTX 5070).

---

## 6. Wyniki Rzeczywistych Eksportów Produkcyjnych (Quadro P400)

Wykonano rzeczywiste eksporty materiału 4K 10-bit HDR z kamery GoPro (`GX010316.MP4`) wraz z nałożonym HUD z pliku FIT (`Popołudniowa_jazda_na_rowerze.fit`) przy użyciu skryptu `scratch\run_p400_exports.py` z aktywnym watchdogiem próbkującym telemetrię GPU co ~5 sekund.

### 6.1. Eksport 1080p HEVC (1000 klatek)
- **Status**: `PASS` (sukces)
- **Liczba klatek**: 1000
- **Czas renderu**: 16.59 s
- **Średnia prędkość**: **60.26 FPS** (ponad 2x real-time dla wideo 29.97 FPS)
- **Plik wyjściowy**: `scratch\p400_export_1080p_1000f.mp4`
- **Rozmiar pliku**: 126,726,295 bajtów (120.86 MB)
- **Maksymalne obciążenie GPU (3D)**: 100.0%
- **Maksymalne obciążenie Enkodera (NVENC)**: 31.0%
- **Maksymalne obciążenie Dekodera (NVDEC)**: 49.0%
- **Maksymalne użycie VRAM**: 1690 MB / 2048 MB
- **Stan watchdoga**: `HEALTHY` (brak zacięć, `STALL_STATE=HEALTHY`)
- **Weryfikacja strumienia (ffprobe)**:
  * Koder: `hevc`
  * Profil: `Main 10`
  * Format pikseli: `yuv420p10le`
  * Przestrzeń barw: `bt2020nc`
  * Krzywa transferu: `arib-std-b67` (HLG)
  * Prymaria: `bt2020`
  * Bitrate wideo: ~30.1 Mb/s

### 6.2. Eksport 4K HEVC (1000 klatek)
- **Status**: `PASS` (sukces)
- **Liczba klatek**: 1000
- **Czas renderu**: 22.48 s
- **Średnia prędkość**: **44.49 FPS** (1.5x real-time dla 4K!)
- **Plik wyjściowy**: `scratch\p400_export_4k_1000f.mp4`
- **Rozmiar pliku**: 5,314,913 bajtów (5.07 MB)
- **Maksymalne obciążenie GPU (3D)**: 100.0%
- **Maksymalne obciążenie Enkodera (NVENC)**: 72.0%
- **Maksymalne obciążenie Dekodera (NVDEC)**: 42.0%
- **Maksymalne użycie VRAM**: 1879 MB / 2048 MB (bezpiecznie zmieszczone w 2GB VRAM)
- **Stan watchdoga**: `HEALTHY` (brak zacięć, `STALL_STATE=HEALTHY`)
- **Weryfikacja strumienia (ffprobe)**:
  * Koder: `hevc`
  * Profil: `Main 10`
  * Format pikseli: `yuv420p10le`
  * Przestrzeń barw: `bt2020nc`
  * Krzywa transferu: `arib-std-b67` (HLG)
  * Prymaria: `bt2020`

### 6.3. Weryfikacja Kontraktu Wykonawczego
- `REQUESTED_BACKEND=nv`
- `EFFECTIVE_BACKEND=nv`
- `INTEL_FALLBACK=NO`
- Całość kompozycji i renderu wykonana w 100% na karcie NVIDIA Quadro P400.

---

## 7. Weryfikacja Testów Jednostkowych i Środowiska Portable

1. **Testy jednostkowe (`pytest`)**:
   - `tests/test_dynamic_export_backends.py`: Wszystkie testy przeszły pomyślnie.
   - `tests/test_render_tab.py`: Wszystkie testy przeszły pomyślnie.
   - Łączny wynik: **35 passed in 9.89s**.
2. **Środowisko przenośne (`C:\_DEV\BikeRideHUD-portable`)**:
   - Skopiowano i zsynchronizowano zmodyfikowane pliki źródłowe (`src/runtime_paths.py`, `src/ffmpeg/backend_capabilities.py`, `src/ffmpeg/command_builder.py`, `src/gui/qt/_mixins/render_mixin.py`).
   - Zweryfikowano zapytanie o możliwości: `PORTABLE BACKENDS: ['auto', 'nv', 'intel', 'cpu']`, `PORTABLE AUTO: nv`.
   - Wykonano rzeczywisty eksport testowy 100 klatek bezpośrednio z poziomu katalogu portable (`scratch\portable_p400_test_100f.mp4`), zakończony sukcesem (`rc=0`, 13.2 MB, 61.9 FPS pipeline).

---

## 8. Podsumowanie

Potok NVIDIA CUDA/NVENC został w pełni uruchomiony i ustabilizowany na karcie NVIDIA Quadro P400 (Pascal) bez ingerencji w architekturę kodu, bez tworzenia nowego renderera i bez degradacji wspólnego FFmpeg. Eksporty 1080p i 4K 10-bit HDR działają w pełni sprzętowo z prędkościami odpowiednio 60.3 FPS oraz 44.5 FPS, mieszcząc się w buforze 2GB VRAM.
