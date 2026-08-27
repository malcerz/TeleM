# TeleM — INTEL ETAP 3B: A/B parity i wydajność

Data pomiaru: 2026-08-25. Raport opisuje pomiar aktualnego środowiska, nie dane historyczne.

## Environment

`ACTIVE_FFMPEG_PATH: F:\_DEV\TeleM\ffmpeg.exe`

`ACTIVE_FFMPEG_VERSION: 2026-08-17-git-426841da9d-full_build-www.gyan.dev`

`where.exe ffmpeg` zwraca także `C:\tools\ffmpeg.exe`, ale aktywny executable TeleM i pierwszy wpis PATH to `F:\_DEV\TeleM\ffmpeg.exe`.

Adapter wybrany dynamicznie po `vendor_id=0x8086`: Intel UHD Graphics 730, DXGI index 1 w bieżącej enumeracji. Index nie jest zakodowany w ścieżce produkcyjnej. QSV device creation przeszło z `child_device_type=d3d11va`; użyto także `-filter_hw_device intel_qsv` w ścieżce native.

## Canonical input

Utworzono `scratch/intel_etap3b/canonical_sdr_720p.mp4`: 6.006 s, 1280x720, 29.97 fps, H.264, `yuv420p`, BT.709, limited range, 8-bit. Materiał jest deterministycznym SDR pochodzącym z bieżącego pliku GoPro; źródłowy HDR 10-bit BT.2020/HLG nie został dopuszczony do native.

## CPU baseline and GPU render

Ten sam layout, próbki telemetryczne, rozdzielczość, FPS i ustawienia kodera uruchomiono w dwóch trybach:

- `CPU_REFERENCE`: QSV decode -> `hwdownload,format=nv12` -> CPU composite -> QSV HEVC encode.
- `D3D11_NATIVE`: QSV decode -> `scale_qsv` -> `overlay_qsv`; HUD pozostaje CPU RGBA i jest uploadowany przez `hwupload=derive_device=qsv`; brak pełnego readbacku obrazu.

Oba przebiegi zakończyły się poprawnie po 180 wygenerowanych klatkach. Wymuszenie native nie rozszerza eligibility: nadal obowiązuje istniejąca pionowa konfiguracja SDR, pojedynczy plik, brak rotacji/cutów i HUD.

## Visual parity

Porównano dekodowane klatki RGB z punktów 0.5 s, 3.0 s i 5.0 s. Próg changed-pixel: dowolny kanał różniący się o więcej niż 2.

| czas | mean absolute diff | max diff | changed pixels |
|---|---:|---:|---:|
| 0.5 s | 1.3615 | 15 | 27.9147% |
| 3.0 s | 1.3249 | 14 | 27.9256% |
| 5.0 s | 1.2435 | 14 | 25.7663% |

Różnice są niskie w skali 8-bit i stabilne czasowo; wymagają interpretacji jako różnica CPU overlay vs GPU overlay oraz ponownego kodowania QSV, a nie jako dowód bitowej identyczności. Nie stwierdzono przesunięcia HUD ani zmiany geometrii w punktach kontrolnych.

## Timing and performance

Wall time dla 6 s materiału:

- CPU_REFERENCE: 4.1608 s; `ffmpeg_write` avg 12.71 ms, p95 35.25 ms.
- D3D11_NATIVE: 4.3973 s; `ffmpeg_write` avg 14.31 ms, p95 40.43 ms.

To krótki smoke benchmark 720p, nie reprezentatywny benchmark 4K. W tym przebiegu native nie uzyskał przewagi wall-clock, ponieważ dominującym kosztem pozostaje generowanie pełnej bitmapy HUD i jej transfer do FFmpeg.

## HUD upload audit

Canvas HUD: 1280x720 RGBA = 3,686,400 B/frame = 3.52 MiB/frame. Przy 29.97 fps daje około 105.4 MiB/s danych wejściowych pipe. Dla orientacji: 1920x1080 to 7.91 MiB/frame i około 237.0 MiB/s przy 29.97 fps; 3840x2160 to 31.64 MiB/frame i około 948.1 MiB/s.

W kodzie dodano jednorazowy diagnostyczny log `[INTEL] HUD upload bytes/frame`. Region uploadu jest technicznie wykonalny i byłby preferowany dla statycznego, ograniczonego HUD, ale obecny kontrakt renderera generuje pełny canvas, a dynamiczne bbox/z-order/alpha wymaga osobnego pomiaru i zachowania semantyki. Nie wdrożono ryzykownej optymalizacji regionowej w tym etapie.

## NVIDIA isolation

NVIDIA Quadro P400 jest obecny, ale przy `INTEL_FORCE` został jawnie pominięty. NVIDIA runtime path nie był testowany w tym zadaniu i nie został zmieniony. AMD path również nie był runtime-testowany i nie został zmieniony.

## Tests

Focused suite: `51 passed in 1.22s`:

`tests/test_intel_backend.py`, `tests/test_video_helpers.py`, `tests/test_gpu_compositor.py`, `tests/test_amd_native_overlay_handoff.py`.

Dodane asercje chronią rozdzielenie CPU Intel (`hwdownload,format=nv12`, CPU overlay) i native Intel (brak `hwdownload`, `overlay_qsv`).

## Changed / preserved

Zmieniono wyłącznie Intel/streaming scope: jawny transfer QSV surface do CPU w CPU_REFERENCE, propagację błędu writer’a stdin, diagnostykę rozmiaru HUD uploadu oraz testy grafu. Zachowano istniejącą eligibility native, QSV settings i ścieżki AMD/NVIDIA/CPU poza koniecznym Intel fallbackiem.

## Remaining bottleneck

Najważniejszym bottleneckiem native jest pełny CPU RGBA HUD upload na każdą klatkę; sam GPU-resident video path nie kompensuje jeszcze tego kosztu w krótkim benchmarku 720p.

## HDR audit

HDR 10-bit/BT.2020/HLG pozostaje poza native eligibility. Nie dodano HDR implementation ani nie zmieniono konwersji kolorów.

## Recommendation — one next step

Wykonać następny dedykowany etap optymalizacji ograniczonego regionu HUD: zmierzyć bbox union i porównać region uploadu z pełnym canvasem na 720p/1080p, bez zmiany eligibility i bez ruszania AMD/NVIDIA.
