# TeleM — agent context

## 1. Projekt

TeleM to desktopowa aplikacja Windows/PySide6 do nakładania telemetrycznego HUD na wideo, głównie z kamer GoPro. Źródła danych obejmują GPMF, FIT, GPX/GPS i dane mapowe. Finalny eksport ma zachować poprawny obraz, audio i synchronizację telemetrii, a jednocześnie wykorzystywać sprzętowe decode/compose/encode tam, gdzie ma to sens.

Główne moduły projektu:
- `src/gui/qt/` — GUI PySide6,
- `src/ffmpeg/` — eksport, FFmpeg, worker/SharedMemory i backendy sprzętowe,
- `src/indicators/` — renderery HUD/Pillow,
- `native/d3d11_amf_pipeline/` — natywny backend AMD D3D11/AMF.

## 2. Zasada nadrzędna

**Correctness przed performance. Realny eksport uruchomiony normalną ścieżką GUI jest źródłem prawdy.**

Nie deklaruj PASS na podstawie wyłącznie:
- syntetycznego PoC,
- pojedynczej klatki,
- mikrobenchmarku,
- samego buildu,
- scratch harnessu, jeśli GUI używa innej konfiguracji.

Każda optymalizacja musi zachować finalny obraz i dane. Preferowane są A/B, frame accounting i framemd5/pixel comparison, gdy ścieżka jest deterministyczna.

## 3. Materiał referencyjny

Podstawowy materiał testowy:
- `GX020079.MP4`,
- 3840×2160,
- ok. 29.97 FPS (`30000/1001`),
- HEVC Main10 / GoPro,
- **rzeczywista liczba klatek = 1131**.

Nie wyliczaj bezwarunkowo `ceil(duration * fps)` jako autorytatywnego frame count. Dla tego pliku historycznie prowadziło to do błędnych 1132 klatek.

## 4. AMD — ZAKOŃCZONE I FROZEN

Optymalizacja AMD została zakończona po etapach 5G–5W. Nie przenoś zmian NVIDIA do AMD i nie refaktoruj AMD „przy okazji”.

Finalny AMD production path:

```text
D3D11VA / Media Foundation HEVC Main10 decode
→ P010 decoder surface
→ D3D11 VideoProcessor
→ NV12 output pool
→ GPU HUD compositor
→ GPU_SPLIT cadence/HR charts
→ GPU gauge
→ GPU map
→ AMF HEVC
→ audio mux
```

Najważniejsze finalne ustawienia AMD:
- VP output pool default = **8**,
- `AMD_MAP_PATH` default = `GPU`,
- `AMD_CHART_PATH` default = `GPU_SPLIT`,
- `AMD_GAUGE_PATH` default = `GPU`,
- `AMD_COMPOSE_5Q` default = `OPTIMIZED`,
- telemetry default = `REFERENCE`,
- AMF QueryOutput = `REFERENCE`,
- CPU base-frame upload = 0,
- GPU→CPU readback bazowej klatki = 0,
- 1131/1131, drops=0.

Finalny baseline AMD po 5W wynosił ok. **37.5 FPS**, czyli ok. **1.25× realtime** dla 29.97 FPS. Realny GUI po poprawieniu błędnych production defaults osiąga >34 FPS i renderuje prawidłowo.

Istotny fix 5W: usunięto leak D3D11 `AddRef/Release` w VP pipeline. Nie cofaj kolejności teardown ani ownership device/context.

### Chronione obszary podczas prac NVIDIA

Nie modyfikuj bez wyraźnej potrzeby:
- `src/ffmpeg/amd_native_exporter.py`,
- `native/d3d11_amf_pipeline/**`,
- AMD pool/lifecycle,
- AMF quality/configuration,
- AMD map/chart/gauge shaders.

Jeśli wspólny plik musi zostać zmieniony dla NVIDIA, udowodnij, że zachowanie AMD pozostaje bez zmian i wykonaj regresję.

## 5. Wspólne optymalizacje HUD

Część optymalizacji Pillow jest wspólna dla wszystkich backendów.

`AMD_COMPOSE_5Q` ma historyczną nazwę, ale implementacja w `src/indicators/` jest wspólna. Finalny default to `OPTIMIZED`.

5Q obejmuje m.in. pixel-exact cache:
- center value text gauge,
- dynamic value tiles cadence/HR.

Nie usuwaj tych cache'y i nie zakładaj, że są „AMD-only” tylko z powodu nazwy zmiennej.

## 6. Aktualny cel — osobna optymalizacja NVIDIA

AMD jest zamknięte. Teraz optymalizujemy **NVIDIA** jako osobny backend.

Nie kopiuj architektury AMD 1:1. NVIDIA ma własny CUDA/NVENC path i najpierw wymaga aktualnego audytu/baseline.

Z aktualnego kodu wynika, że ścieżka NVIDIA prawdopodobnie wygląda tak:

```text
HEVC input
→ CUDA/NVDEC decode
→ CUDA base frame / scale_cuda

równolegle:
Python/Pillow HUD
→ raw RGBA przez SharedMemory/pipe do FFmpeg
→ format=rgba
→ (przy 4K prawdopodobnie CPU scale overlay 1920×1080 → 3840×2160)
→ hwupload_cuda

base + overlay
→ overlay_cuda
→ hevc_nvenc
→ mux
```

**To jest hipoteza na podstawie kodu, nie wynik NV0. Najpierw potwierdź realny command i runtime.**

W aktualnym GUI Smart Canvas Scaling ogranicza overlay dla 4K do około 1920 px szerokości. W `command_builder.py` istnieje ścieżka `format=rgba,scale=...:flags=bilinear,hwupload_cuda`, więc szczególnie ważne jest ustalenie, czy finalny 4K HUD jest skalowany na CPU przed uploadem do CUDA i jaki jest koszt tej operacji.

## 7. Pierwszy etap NVIDIA: NV0

NV0 ma być **wyłącznie audytem i pomiarem**. Nie optymalizuj produkcyjnego NVIDIA path przed poznaniem bottlenecku.

NV0 powinien co najmniej:
1. prześledzić REAL GUI path do FFmpeg/NVENC,
2. wypisać faktyczny `filter_complex`,
3. potwierdzić NVDEC/CUDA decode, `scale_cuda`, `overlay_cuda`, `hevc_nvenc`,
4. zmierzyć REAL GUI TRUE FPS na 1131 klatkach,
5. zmierzyć koszt CPU HUD/Pillow,
6. zmierzyć SHM/queue/stdin backpressure,
7. ustalić gdzie wykonywany jest overlay resize 1080p→4K,
8. zmierzyć ceiling samego CUDA decode/scale + NVENC bez HUD,
9. opcjonalnie zmierzyć static-overlay ceiling,
10. sklasyfikować bottleneck na podstawie danych.

Nie wykonuj NV1 w tym samym kroku.

## 8. NVIDIA — czego nie zakładać

Nie zakładaj na podstawie starych raportów, że:
- NVENC jest bottleneckiem,
- CPU HUD jest bottleneckiem,
- `overlay_cuda` jest bottleneckiem,
- stary FPS nadal obowiązuje.

Kod i konfiguracja projektu zmieniły się znacząco. Wykonaj świeży baseline na aktualnym repo.

Sprzęt NVIDIA również wykrywaj w runtime (`nvidia-smi`/FFmpeg); nie hardcoduj konkretnego modelu GPU, jeśli nie jest wymagany przez test.

## 9. Benchmarking

TRUE FPS:

```text
faktycznie ukończone/zakodowane klatki / pełny wall-clock eksportu
```

W production benchmarku uwzględniaj:
- decode,
- HUD,
- transport overlay,
- GPU processing,
- encode,
- drain/flush,
- finalny mux/close.

Raportuj minimum:
- wall,
- TRUE FPS,
- frames source/processed/encoded/muxed,
- drops,
- audio present,
- Median/P95 dla profilowanych stage'y.

Nie oceniaj optymalizacji na podstawie jednego runu, jeśli różnica jest mała. Preferuj interleaved A/B/C/D w tej samej sesji. Uwzględniaj thermal/system variance.

Ciężkie profilery, readbacki i forced GPU waits uruchamiaj osobno od TRUE FPS benchmarku.

## 10. GUI / progress / HUD preview

Zakładka Rendering została przebudowana w kierunku:
- przycisk Export po prawej pod ustawieniami eksportu,
- progress i statystyki pod podglądem,
- HUD Preview bez filmu,
- preview aktualizowany około 1 Hz,
- brak GPU→CPU readback finalnego HUD do preview,
- progress ma wynikać z faktycznie ukończonych klatek, nie z timera/duration.

Nie cofaj tych zasad podczas prac NVIDIA. Backend renderujący nie może czekać na HUD Preview.

## 11. Git / zakres zmian

Przed zmianą:
- sprawdź `git status`,
- nie usuwaj niepowiązanych zmian użytkownika,
- nie rób szerokiego cleanup/refactoru poza celem etapu.

Podczas prac NVIDIA:
- AMD frozen,
- Intel frozen,
- zmiany mają być minimalne i mierzalne,
- każde odstępstwo od obecnej semantyki wymaga uzasadnienia i testu.

## 12. Styl pracy agenta

Dla każdego etapu:
1. AUDIT,
2. hipoteza poparta kodem/pomiarem,
3. minimalna zmiana albo tylko diagnostyka zgodnie ze spec,
4. correctness gate,
5. production A/B,
6. raport z liczbami,
7. STOP.

Nie przechodź automatycznie do następnego etapu.

Jeżeli wynik jest niejednoznaczny, użyj statusu `INCONCLUSIVE`, a nie sztucznego PASS.
