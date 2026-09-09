# AMD CPU software decode → GPU compose / AMF — experiment

**Data:** 2026-09-09  
**Branch:** `integration/intel-amd`  
**Zakres:** wyłącznie diagnostyczny opt-in AMD; bez zmiany domyślnej ścieżki GPU, Intel/NVIDIA ani HUD.

## Stan i cel

Hipoteza: dekodowanie HEVC Main10 na CPU, upload P010 do istniejącego D3D11 compositora i dalsze kodowanie AMF może odciążyć VCN. Materiał Stage A był rzeczywistym `D:\GoPro\2026-09-01\GX010244.MP4`, 3840×2160, HEVC Main10, 29.97 FPS; FFmpeg dekodował software (`-hwaccel none`) dokładnie 10 000 klatek do `null`, bez zapisu dużego pliku.

## Stage A — CPU decode-only

Surowe wyniki: [D:\TeleM_CPU_DECODE_ONLY_20260909_073444\matrix.json](D:/TeleM_CPU_DECODE_ONLY_20260909_073444/matrix.json). Próbki sekundowe CPU/RAM/I/O są w podkatalogach `threads_*`.

| Wątki FFmpeg | Czas | FPS | CPU avg/peak | RSS peak |
|---:|---:|---:|---:|---:|
| 4 | 290.560 s | 34.416 | 32.69/55% | 284 MB |
| 8 | 214.804 s | 46.554 | 48.50/77% | 465 MB |
| 12 | 198.065 s | 50.488 | 55.79/77% | 644 MB |
| 16 | 180.302 s | 55.463 | 63.99/91% | 828 MB |

Bramka decode-only `≥45 FPS`: **PASS** dla 8/12/16 wątków. Najszybszy wariant: 16 wątków, 55.463 FPS.

## Stage B — real GUI pipeline

Uruchomiono normalne GUI (`QApplication → AppController → MainWindow → RenderTab._on_render`) z:

```text
AMD_DECODE_MODE=CPU
AMD_NATIVE_DECODE_MODE=GPU_HUD_CPU_DECODE_REFERENCE
AMD_NATIVE_HUD_MODE=GPU_HUD
AMD_CPU_GPU_PIPELINE=ASYNC
AMD_QUEUE_DEPTH=2
```

Output root: [D:\TeleM_CPU_DECODE_PIPELINE_20260909_](D:/TeleM_CPU_DECODE_PIPELINE_20260909_). GUI załadowało projekt i podgląd GPU, a child został utworzony (`pid=12708`). Następnie **nie pojawił się start renderera, checkpoint ani pierwsza klatka**. Proces pozostawał responsywny, lecz finalny MP4 miał 0 bajtów; przebieg został zatrzymany kontrolowanie po ponad 22 minutach. Po zatrzymaniu nie pozostał proces Python/FFmpeg.

Wniosek: Stage B **BLOCKED** przed właściwym renderem (podgląd/child startup), więc nie wolno z tego przebiegu wyliczać FPS ani deklarować A/V/parity. Nie uruchamiano q1/q4, 20k ani 85574.

## Kryteria

| Kryterium | Wynik |
|---|---|
| CPU decode-only ≥45 FPS | PASS (8/12/16 threads) |
| CPU decode → P010 upload → GPU compose → AMF, 10k | **BLOCKED — render nie wystartował** |
| Render regression ≤2% | NOT TESTED |
| P010/HDR visual parity | NOT TESTED w tym przebiegu |
| GPU Video Decode off / Video Encode / CPU/GPU/RAM/Disk podczas pełnego renderu | NOT PROVEN |
| Cancel/error/no orphan | Child po przerwaniu zakończony; pełny acceptance NOT TESTED |

Istniejący wcześniejszy raport apples-to-apples (`RAPORT_AMD_CPU_VS_GPU_DECODE_BENCHMARK.md`) pozostaje jedynym ukończonym dowodem CPU pipeline i wykazuje spadek do ok. 22.67 FPS dla Full HUD. Ten przebieg nie unieważnia ani nie poprawia tamtych wyników.

## Zmiany i izolacja

- Dodano wyłącznie skrypt pomiarowy `scratch/run_cpu_decode_only_matrix.ps1` oraz ten raport.
- Nie zmieniono produkcyjnego defaultu AMD (`GPU/D3D11VA`), Intel, NVIDIA ani HUD.
- Nie wykonano commit/push/reset/clean/rebase.

**STATUS = BLOCKED / NO-GO dla dalszego Stage B do czasu naprawy blokady podglądu/child startup.**
