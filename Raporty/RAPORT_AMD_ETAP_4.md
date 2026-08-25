# TeleM — AMD ETAP 4-CONTINUE — raport końcowy

**Wynik: PASS.** Finalna ścieżka `GPU_HUD_D3D11VA` dekoduje HEVC Main10 sprzętowo przez Media Foundation do `DXGI_FORMAT_P010`, przekazuje subresource dekodera bezpośrednio do VideoProcessora i nie tworzy CPU rawvideo ani bazowego uploadu CPU→GPU. Istniejący HUD ETAP 3 pozostał na ścieżce persistent RGBA + multi-dirty target 8 + direct planar NV12 compute compositor.

Walidację wykonano 14.08.2026 na rzeczywistym materiale `Video/GX020079.mp4` (3840×2160, 30000/1001, HEVC Main10, HLG/BT.2020, 1131 klatek).

## 1. Finalna DLL

| Pole | Wynik |
|---|---|
| CMake target | `telem_amd_native` |
| Clean configure/build | PASS |
| DLL path | `C:\_DEV\TeleM\native\d3d11_amf_pipeline\bin\telem_amd_native.dll` |
| LOAD | PASS |
| ABI | **4** |
| Build ID | `telem-amd-native/1.0.0+42dc5799a538.src0b7f5ae005a6` |
| Build timestamp | `2026-08-14T07:22:26+02:00` |
| Git commit | `42dc5799a53851a7b7ca9216068c9dd082eb496c` |
| Source hash | `0b7f5ae005a6f5ad1b3b6796a7ecf2af88d34266abd3f3503c386366f486825d` |
| DLL SHA-256 | `CE640BB8047B3354ADE3518B90FB4B89DAD932A4E22A4CEEFE890A4B6C0348BD` |

Dokładne polecenia:

```powershell
C:\tools\mingw64\bin\cmake.exe --fresh `
  -S native\d3d11_amf_pipeline `
  -B native\d3d11_amf_pipeline\build-etap4-final-clean `
  -G Ninja `
  -DCMAKE_BUILD_TYPE=Release `
  -DCMAKE_MAKE_PROGRAM=C:\tools\mingw64\bin\ninja.exe `
  -DCMAKE_CXX_COMPILER=C:\tools\mingw64\bin\g++.exe

C:\tools\mingw64\bin\cmake.exe --build `
  native\d3d11_amf_pipeline\build-etap4-final-clean `
  --config Release --target telem_amd_native --clean-first
```

DLL sprzed finalnego clean build i DLL z clean build mają ten sam SHA-256. Reproducibility = PASS.

## 2. Błędy wykryte przez finalną walidację

Polecenie zakazywało zmian architektury, dopóki test nie wykaże błędu. Test wykazał dwa błędy correctness, więc naprawiono wyłącznie je:

1. Krótki HUD-OFF potrafił dojść do `AMF_INPUT_FULL`; arbitralny limit 10000 prób kończył klatkę 23 błędem. Retry zachowuje teraz tę samą surface i odpytuje output do skutku albo do 60-sekundowego timeoutu. Queue depth, jakość i ustawienia AMF nie zostały zmienione.
2. Zastany finalny stan nominal-range ustawiony przez VP dawał obraz magenta/prześwietlony (MAE około 97–99 zamiast oczekiwanej poprawy poprzedniego MAE ~17). Taki sam błąd dało jawne `VideoProcessorSetStreamColorSpace1`. Audyt YUV wykazał, że golden CPU zawiera historycznie dwie kwantyzowane transformacje full→studio. Korektę odizolowano więc do dwóch GPU-resident passów na wyjściowym NV12, tylko dla `GPU_HUD_D3D11VA`, przed niezmienionym compositorem HUD. Nie ma readbacku, CPU conversion ani zmiany shader math HUD.

## 3. Test A — BASE ONLY, 30 klatek

Plik: `Raporty/AMD_ETAP4/continue_test_a_d3d11va_base_30_gpu_range.mp4`.

| Sprawdzenie | Wynik |
|---|---|
| Hardware decode | YES |
| Decoder output | `DXGI_FORMAT_P010` |
| Direct decoder surface → VP | YES, 30/30 |
| Additional GPU copy | NO, 0/30 |
| FFmpeg rawvideo pipe | NO |
| CPU raw base | 0 MiB/frame |
| CPU→GPU base upload | 0 MiB/frame |
| GPU→CPU base readback | 0 MiB/frame |
| Black/green/magenta artefacts | NO |
| AMF dropped | 0 |

Porównanie z `GPU_HUD_CPU_DECODE_REFERENCE` po niezależnym kodowaniu obu plików:

| Frame | MAE | MAX | P95 | P99 |
|---:|---:|---:|---:|---:|
| 0 | 2.510 | 43 | 7 | 12 |
| 15 | 3.124 | 43 | 9 | 14 |
| 29 | 3.108 | 44 | 10 | 14 |

Wizualnie: brightness PASS, contrast PASS, highlights PASS, shadows PASS, saturation PASS. Poprzednia duża regresja koloru została usunięta; nie ma clippingu ani dominanty magenta/green.

HUD-OFF celowo produkuje klatki szybciej niż AMF je przyjmuje: `AMF_INPUT_FULL=53018`, retries `53018`, dropped `0`. Ten wynik potwierdza działanie retry. Nie zmieniano kolejki ani jakości.

## 4. Test B — real HUD, 30 klatek

Plik: `Raporty/AMD_ETAP4/continue_test_b_d3d11va_real_hud_30.mp4`.

| Element | Wynik |
|---|---|
| Base video | PASS |
| FIT / speed / cadence / HR | PASS |
| GPMF / ISO / exposure / temperature / battery | PASS |
| Map | PASS |
| Date/time | PASS |
| HUD alpha | PASS |
| HUD color | PASS |
| GPU HUD frames | 30/30 |
| CPU BlendRGBAToNV12 | 0 |
| AMF dropped | 0 |

Nie stwierdzono czarnych klatek, pasów green/magenta, uszkodzonej alfy ani clippingu.

## 5. Pełny REAL production GUI export

Realna funkcja `src.ffmpeg.streaming.stream_overlay_to_ffmpeg()` wykonała dispatch do produkcyjnego AMD native backendu. GUI przekazuje obecnie `tz_offset_hours=2`; dlatego realny GUI output pokazuje lokalny czas `06:28:xx`. Dodatkowo wykonano pełny kontrolny run UTC, aby porównanie z historycznym golden (`04:28:xx`) miało identyczne parametry renderera.

Pliki:

- real GUI: `Raporty/AMD_ETAP4/continue_full_gui_dispatch_d3d11va_1131.mp4`,
- kontrola golden UTC: `Raporty/AMD_ETAP4/continue_full_utc_golden_control_1131.mp4`.

### Frame accounting — real GUI

| Licznik | Wynik |
|---|---:|
| Source / requested | 1131 / 1131 |
| MF ReadSample calls | 1131 |
| Video samples | 1131 |
| D3D11 surfaces | 1131 |
| Direct decoder→VP | 1131 |
| Additional decoder GPU copies | 0 |
| VP processed | 1131 |
| HUD generated / uploaded | 1131 / 1131 |
| GPU HUD | 1131 |
| AMF submitted | 1131 |
| AMF output | 1131 |
| Muxed video frames | 1131 |
| AMF dropped / ignored | 0 / 0 |
| Stream ticks / null samples | 0 / 0 |
| Format changes | 1 (inicjalny output type) |

`MF_SOURCE_READERF_ENDOFSTREAM` nie został odczytany w tym bounded runie, ponieważ eksporter zakończył pętlę po dokładnych 1131 klatkach znanych z metadanych źródła. Nie wygenerował syntetycznej klatki 1132. Obsługa EOS/stream tick pozostaje w kodzie.

### Final MP4

| Pole | Wynik |
|---|---|
| Resolution | 3840×2160 |
| Video codec/profile | HEVC Main |
| Pixel format | yuv420p |
| Frames (`ffprobe -count_frames`) | 1131 |
| Video duration | 37.738077 s |
| Audio | AAC LC, 48 kHz, stereo, 1768 packets |
| Audio duration | 37.717333 s |
| Audio ADTS SHA-256 | `E7D3FA3DF057F0705BF2F8410B6FDE44FAC298002A55BDB1B6EC403E642D1FF3` |

Hash audio jest identyczny z golden ETAP 0–3. Audio = PASS.

## 6. Timestamp sync

Media Foundation PTS jest porównany z `frame_index × 1001/30000`:

| Frame | D3D11VA PTS | CPU reference | Delta |
|---:|---:|---:|---:|
| 0 | 0.000 s | 0.000 s | 0 ms |
| 30 | 1.001 s | 1.001 s | ~0 ms |
| 300 | 10.010 s | 10.010 s | 0 ms |
| 600 | 20.020 s | 20.020 s | 0 ms |
| 900 | 30.030 s | 30.030 s | 0 ms |

Timestamp sync = PASS. HUD odpowiada tej samej klatce video.

## 7. Golden 30 / 300 / 900

Kontrolny run UTC porównano z finalnym ETAP 3 CPU-decode golden. Są to dwa osobne encode HEVC i inna ścieżka P010→VP→NV12, dlatego wymaganiem nie była exact equality.

| Frame | MAE | MAX | P95 | P99 | Wizualnie |
|---:|---:|---:|---:|---:|---|
| 30 | 2.727 | 66 | 8 | 14 | PASS |
| 300 | 2.332 | 105 | 7 | 13 | PASS |
| 900 | 1.999 | 246 | 7 | 13 | PASS |

Wysokie wartości MAX są pojedynczymi pikselami/ostrymi krawędziami dynamicznych wykresów po dwóch niezależnych kompresjach. Dla frame 900 tylko 0.00063% kanałów ma różnicę >128; P99 pozostaje 13. Oględziny pełnych klatek potwierdzają:

- FIT dynamic: PASS,
- GPMF dynamic: PASS,
- Map: PASS,
- Date/time: PASS,
- HUD text/graphs/alpha/color: PASS,
- Base brightness/contrast/highlights/shadows/saturation: PASS,
- Audio: PASS.

## 8. Transfer audit

| Transfer bazowego video | ETAP 3 | ETAP 4 |
|---|---:|---:|
| FFmpeg rawvideo pipe | YES | **NO** |
| CPU raw base | 11.865 MiB/frame | **0 MiB/frame** |
| CPU→GPU base | 11.865 MiB/frame | **0 MiB/frame** |
| GPU→CPU base | 0 | **0** |
| Staging upload | YES | **NO** |
| Decoder surface→VP | nie dotyczy | **direct 1131/1131** |
| Dodatkowa GPU copy | nie dotyczy | **0** |

CPU reference path `GPU_HUD_CPU_DECODE_REFERENCE` nadal istnieje.

## 9. Performance — real GUI

Definicja TRUE FPS pozostała identyczna: start przed decode, stop po AMF drain, finalize, audio mux i zamknięciu pliku.

| Run | Wall-clock | TRUE FPS |
|---|---:|---:|
| ETAP 3 CPU decode baseline | 107.784 s | 10.493 |
| ETAP 4 D3D11VA real GUI | **67.745 s** | **16.695** |
| ETAP 4 UTC golden control | 70.141 s | 16.125 |

Real GUI: +6.202 FPS, około +59.1% względem ETAP 3.

| Stage — real GUI | AVG ms | Median | P95 | P99 |
|---|---:|---:|---:|---:|
| MF ReadSample/decode availability | 0.965 | 0.666 | 1.383 | 4.968 |
| Decoder surface acquisition | 0.011 | 0.010 | 0.018 | 0.051 |
| Optional decoder GPU copy | 0.000 | 0.000 | 0.000 | 0.000 |
| VP CPU submit | 0.204 | 0.194 | 0.276 | 0.325 |
| Telemetry/frame_data | 7.991 | 5.664 | 17.045 | 19.375 |
| HUD compose_overlay | **34.341** | 31.763 | 47.342 | 64.597 |
| HUD buffer preparation | 11.672 | 10.893 | 15.299 | 22.378 |
| HUD upload | 1.700 | 1.587 | 1.984 | 2.767 |
| AMF submit/backpressure | 0.383 | 0.313 | 0.609 | 1.643 |
| AMF QueryOutput | 0.127 | 0.117 | 0.213 | 0.292 |
| Packet write | 0.131 | 0.106 | 0.256 | 0.453 |
| Audio mux (raz) | 663.283 | — | — | — |

Production profiling nie wykonuje blocking GPU completion wait, więc VP jest poprawnie opisany jako **CPU submission**, nie czas wykonania GPU.

## 10. AMF backpressure

Pełny real GUI run:

- `AMF_INPUT_FULL = 0`,
- retries `0`,
- dropped `0`,
- czas stricte w retry/backpressure `0 ms`,
- całkowity submit API (zwykły submit + ewentualny backpressure) około `433.1 ms` dla 1131 klatek.

Backpressure nie jest dominującym kosztem pełnego runu. Duża liczba retry występuje tylko w nienaturalnie szybkim HUD-OFF short runie i nie była optymalizowana.

## 11. Testy

```text
164 passed, 17 skipped in 6.10s
```

`git diff --check` = PASS. Ostrzeżenia kompilatora pochodzą z istniejących nagłówków AMF/STB i nie blokują builda.

## 12. Odpowiedzi wprost

1. **Czy decode jest naprawdę hardware?** Tak. MF SourceReader zwraca 1131 `IMFDXGIBuffer`/D3D11 surfaces P010; hardware proof = YES.
2. **Czy jakikolwiek raw base frame trafia do CPU?** Nie. 0 B/frame CPU raw, 0 B/frame CPU→GPU i 0 B/frame GPU→CPU.
3. **Czy decoder surface trafia bezpośrednio do VP?** Tak, 1131/1131; dodatkowa GPU copy = 0.
4. **Jaki format daje decoder?** `DXGI_FORMAT_P010`.
5. **Czy frame timestamps zgadzają się z reference?** Tak, punkty 0/30/300/600/900 mają delta 0 ms (poza pomijalnym błędem float ~2e-13 ms dla frame 30).
6. **Czy base color odpowiada reference?** Tak wizualnie. Short base-only MAE 2.51–3.12, P99 12–14; nie ma poprzedniej regresji MAE ~17 ani artefaktów po wadliwej konfiguracji nominal range.
7. **Czy HUD ETAP 3 pozostał bez zmian?** Tak: persistent RGBA8, multi-dirty 8, regional upload i direct planar NV12 HUD compositor. CPU blend = 0.
8. **Jaki jest TRUE FPS?** **16.695 FPS** dla real production GUI, 1131 klatek, 67.745 s end-to-end.
9. **Co jest teraz największym bottleneckiem?** `compose_overlay` ~34.34 ms/frame, potem HUD buffer preparation ~11.67 ms i telemetry ~7.99 ms. Nie optymalizowano ich.
10. **Czy można przejść do optymalizacji compose_overlay/telemetry?** ETAP 4 spełnia kryteria PASS. Ten raport nie rozpoczyna ani nie implementuje ETAPU 5.

**Zatrzymano się po ETAPIE 4.**
