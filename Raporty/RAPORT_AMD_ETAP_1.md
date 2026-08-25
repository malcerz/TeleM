# TeleM — AMD ETAP 1

Status: **PASS**

Zakres ETAPU 1 został zachowany. Nie zmieniono `BlendRGBAToNV12`, `compose_overlay`, Pillow, FFmpeg software decode, ścieżki staging NV12, architektury VideoProcessora, ustawień AMF, NVIDIA ani Intel. Nie rozpoczęto GPU HUD.

## ZMIANY

### Production GPU wait

Timestamp queries D3D11 i pętle blokujące `GetData(...) == S_FALSE` służyły wyłącznie pomiarowi czasu GPU. Nie były barierą correctness.

Kolejność pozostaje poprawna bez CPU wait, ponieważ `CopyResource`, `VideoProcessorBlt` oraz przekazanie tekstury do AMF są wykonywane na tym samym D3D11 device/context. Kolejność komend GPU jest zachowana, a AMF przyjmuje bezpośrednio wynikową `ID3D11Texture2D`.

Normalna produkcja nie wykonuje teraz `Begin/End/GetData` dla timestamp queries. Dokładny pomiar można jawnie włączyć:

```powershell
$env:AMD_NATIVE_PROFILING='ON'
```

`AMD_NATIVE_DIAGNOSTICS=ON` również automatycznie włącza profiling GPU. Krótki test profilingu przetworzył 31/31 klatek, zarejestrował 31 GPU-profiled frames, GPU completion AVG 7.829 ms i CPU wait AVG 11.488 ms.

### HUD OFF fast path

Aktywność HUD jest ustalana raz przed eksportem na podstawie włączonych wskaźników i niepustych, włączonych custom texts. Przy HUD OFF pomijane są:

- worker cache HUD/telemetry,
- `prepare_overlay_frame_data`,
- `compose_overlay`,
- `PIL.Image.tobytes`,
- `telem_amd_update_hud`,
- `BlendRGBAToNV12`.

DLL otrzymuje jawny stan HUD, czyści bufor RGBA i ma natywny licznik rzeczywistych wywołań blendu. Produkcyjna ścieżka HUD OFF to teraz:

```text
FFmpeg CPU NV12 -> staging memcpy -> CopyResource -> VideoProcessor Stream 0 -> AMF -> mux
```

Opcjonalny `AMD_NATIVE_LEGACY_NO_HUD=ON` istnieje wyłącznie do kontrolowanego A/B starego narzutu; domyślnie jest OFF.

## BUILD

DLL została zbudowana dwukrotnie przez CMake z `--clean-first`. Oba artefakty były bitowo identyczne.

**Build ID:** `telem-amd-native/1.0.0+42dc5799a538.src18c3c898b6a3`

**DLL SHA-256:** `56adecdb73c27826e3ef37d744423a0a146003f8748a578ff6523811ff9c7fba`

**DLL size:** 2,896,820 bytes

## HUD ON

| Pomiar | ETAP 0 | ETAP 1 production |
|---|---:|---:|
| Frames | 1131 | 1131 |
| Total wall-clock | 267.445 s | 271.777 s |
| TRUE FPS | 4.229 | 4.161 |
| GPU wait/synchronization AVG | 8.398 ms | 0.000 ms |
| GPU profiled frames | 1131 | 0 |
| Blend calls | 1131 | 1131 |

Usunięto dokładnie 8.398 ms/frame blokującego waitu profilującego. W tym pojedynczym pełnym przebiegu TRUE FPS HUD ON nie wzrósł: ciężkie i niezmienione etapy CPU miały większą zmienność niż usunięty koszt (`decode`, `tobytes`, `compose_overlay`, blend). ETAP 1 nie przedstawia enqueue jako czasu GPU i nie przypisuje tej zmienności optymalizacji.

Wybrane czasy ETAP 1 HUD ON:

| Stage | AVG | P95 | P99 |
|---|---:|---:|---:|
| Decode/pipe | 20.897 ms | 29.777 ms | 35.572 ms |
| Telemetry | 19.373 ms | 21.900 ms | 24.067 ms |
| compose_overlay | 35.783 ms | 49.184 ms | 83.418 ms |
| PIL tobytes | 22.668 ms | 32.718 ms | 47.727 ms |
| update_hud | 3.621 ms | 4.122 ms | 5.231 ms |
| BlendRGBAToNV12 | 134.374 ms | 158.565 ms | 205.309 ms |
| VP CPU submit | 0.426 ms | 0.496 ms | 0.759 ms |
| GPU wait production | 0.000 ms | 0.000 ms | 0.000 ms |
| AMF SubmitInput/backpressure | 0.337 ms | 0.406 ms | 0.565 ms |

## HUD OFF

ETAP 0 nie zapisał historycznego pełnego eksportu HUD OFF. Wartość referencyjna poniżej jest kontrolowanym odtworzeniem starego zachowania na tym samym materiale i buildzie: transparentny canvas, `tobytes`, update, blend oraz ETAP0-style GPU profiling wait były włączone.

| Pomiar | ETAP 0 behavior reference | ETAP 1 fast path |
|---|---:|---:|
| Frames | 1131 | 1131 |
| Total wall-clock | 92.182 s | 56.542 s |
| TRUE FPS | 12.269 | 20.003 |
| Wall time/frame | 81.504 ms | 49.993 ms |
| compose_overlay calls | 1131 | 0 |
| tobytes calls | 1131 | 0 |
| update_hud calls | 1131 | 0 |
| BlendRGBAToNV12 calls | 1131 | 0 |
| GPU profiled frames | 1131 | 0 |

Fast path usunął 31.511 ms wall-clock na klatkę w kontrolowanym A/B. TRUE FPS wzrósł o 63.0%, z 12.269 do 20.003 (1.630×).

Kontrola wizualna finalnego HUD OFF potwierdziła czyste bazowe wideo bez HUD, clippingu i artefaktów NV12.

## FRAME ACCOUNTING / AMF

Każdy pełny przebieg zakończył się:

```text
source metadata = 1131
decoded         = 1131
video updates   = 1131
VP processed    = 1131
AMF submitted   = 1131
AMF output      = 1131
muxed           = 1131
```

`requested=1132` pozostaje skutkiem `ceil(duration × fps)`, a nie brakującej klatki. AMF drain nadal czeka do `AMF_EOF`.

```text
AMF_INPUT_FULL = 0
retries        = 0
dropped        = 0
ignored        = 0
```

Nie zmieniono queue depth, jakości, QP ani kodeka.

## GOLDEN REGRESSION — HUD ON

| Check | Result |
|---|---|
| Frame 30 | PASS — pixel-identical, MAE 0, max diff 0 |
| Frame 300 | PASS — pixel-identical, MAE 0, max diff 0 |
| Frame 900 | PASS — pixel-identical, MAE 0, max diff 0 |
| FIT | PASS |
| GPMF | PASS |
| Map | PASS |
| Date/time | PASS |
| Color | PASS |
| Audio | PASS — bit-identical AAC/ADTS |

Audio ETAP 0 i oba finalne eksporty ETAP 1 mają identyczny SHA-256 ADTS:

`e7d3fa3df057f0705bf2f8410b6fde44fac298002a55bdb1b6ec403e642d1ff3`

## ODPOWIEDZI WPROST

1. **Czy per-frame GPU wait był potrzebny do correctness?** Nie. Był potrzebny wyłącznie do synchronicznego odczytu timestamp queries na potrzeby profilowania.
2. **Ile ms/frame udało się usunąć?** Z produkcyjnego HUD ON usunięto 8.398 ms/frame profiling-only GPU wait. W kontrolowanym HUD OFF A/B całkowity wall time zmalał o 31.511 ms/frame.
3. **Czy HUD OFF omija teraz cały HUD pipeline?** Tak. Worker/frame_data, compose, tobytes, update_hud i blend mają po 0 wywołań.
4. **Jaki jest TRUE FPS HUD ON?** 4.161 FPS w pełnym przebiegu ETAP 1.
5. **Jaki jest TRUE FPS HUD OFF?** 20.003 FPS; kontrolna referencja starego zachowania wyniosła 12.269 FPS.
6. **Czy output HUD ON jest pixel-identical z golden?** Tak, dla klatek 30, 300 i 900; wszystkie mają MAE 0 i max diff 0.
7. **Czy można przejść do ETAP 2 — GPU HUD?** Tak. ETAP 1 spełnia kryteria correctness i regresji; CPU `BlendRGBAToNV12` pozostaje niezmienionym dominującym kosztem HUD ON.

## WERYFIKACJA

- Dwa deterministyczne clean buildy: PASS.
- Produkcja HUD ON, profiling OFF: PASS.
- Produkcja HUD OFF fast path: PASS.
- Profiling ON, 31/31 dokładnych timingów GPU: PASS.
- Golden 30/300/900: PASS, exact equality.
- Audio bit-exact: PASS.
- `pytest`: 149 passed, 17 skipped.
- `git diff --check`: PASS.

ETAP GPU HUD nie został rozpoczęty.
