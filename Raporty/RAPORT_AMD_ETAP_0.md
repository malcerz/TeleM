# TeleM — AMD ETAP 0

Status: **PASS**

Zakres został ograniczony do infrastruktury, diagnostyki, pomiarów i jednej naprawy correctness w obsłudze AMF drain/backpressure. Nie zmieniono decode path, algorytmu HUD, `BlendRGBAToNV12`, VideoProcessora, ustawień AMF, backendu NVIDIA ani kodu Intel.

## BUILD

**CMake target:** `telem_amd_native`

Źródła produkcyjnej DLL:

- `src/telem_amd_native.cpp`
- `src/d3d11_vp_pipeline.cpp`
- `src/d3d11_amf_encoder.cpp`

Martwy eksperymentalny `d3d11_hud_bridge` nie jest częścią targetu. Linkowane zależności: D3D11, DXGI, D3DCompiler, Media Foundation (`mfplat`, `mfreadwrite`, `mfuuid`), `ole32` oraz nagłówki/runtime AMF używane przez produkcyjne źródła.

Dokładne komendy czystego buildu:

```powershell
C:\tools\mingw64\bin\cmake.exe -S native\d3d11_amf_pipeline -B native\d3d11_amf_pipeline\build-etap0 -G Ninja -DCMAKE_BUILD_TYPE=Release
C:\tools\mingw64\bin\cmake.exe --build native\d3d11_amf_pipeline\build-etap0 --target telem_amd_native --clean-first --parallel
```

**Clean build:** PASS

**Powtarzalność:** PASS — dwa kolejne czyste buildy dały identyczny SHA-256:

`f194b6b0e647f8cffea65ac60a680379a34158e22c373a7921d178fb52795659`

**DLL path:** `C:\_DEV\TeleM\native\d3d11_amf_pipeline\bin\telem_amd_native.dll`

Ścieżka jest wyprowadzana z absolutnej lokalizacji modułu Pythona, a nie z CWD. GUI nie wybiera przypadkowej DLL z PATH ani innego katalogu.

**ABI:** 1

**Build ID:** `telem-amd-native/1.0.0+42dc5799a538.src4f556fb41e12`

**Build timestamp:** `2026-08-14T07:22:26+02:00`

**Git commit:** `42dc5799a53851a7b7ca9216068c9dd082eb496c`

**Source hash:** `4f556fb41e1264ac792c766e08f4797220d72ab474704e9f61f0f248c3d94f79`

DLL eksportuje C ABI dla wersji ABI, build info, diagnostyki, rozszerzonych liczników i timingów. Python wymaga ABI=1; brak funkcji lub niezgodność ABI kończy native backend jednoznacznym `False`, po czym istniejąca polityka `streaming.py` jawnie przechodzi do software fallbacku.

## BASELINE

Materiał: `GX020079.mp4` + `GX020079.json` + `Morning_Ride.fit` + `def_layout.json`, 3840×2160, 29.97 fps.

**Frames encoded:** 1131

**Total wall-clock:** 267.445 s

**TRUE FPS:** 4.229

Timer startuje bezpośrednio przed uruchomieniem FFmpeg decode, a kończy się po AMF drain, zamknięciu surowego video, zakończeniu audio mux, zamknięciu finalnego MP4 i usunięciu pliku tymczasowego.

## TIMINGS

Wartości w milisekundach. Wszystkie etapy per-frame mają po 1131 próbek; `Audio mux` jest jednym pomiarem całej operacji.

| Stage | AVG | Median | P95 | P99 |
|---|---:|---:|---:|---:|
| Decode/pipe wait | 15.981 | 14.109 | 20.667 | 24.835 |
| Telemetry/frame_data | 19.023 | 19.188 | 21.098 | 22.707 |
| compose_overlay | 34.137 | 31.868 | 44.936 | 61.000 |
| PIL tobytes | 19.647 | 19.366 | 24.972 | 33.148 |
| update_hud | 3.579 | 3.509 | 4.068 | 5.108 |
| NV12 staging memcpy | 1.122 | 1.104 | 1.318 | 1.645 |
| BlendRGBAToNV12 | 132.169 | 128.931 | 154.065 | 171.389 |
| staging Unmap/CopyResource submission | 0.029 | 0.029 | 0.035 | 0.050 |
| VideoProcessor CPU submit | 0.402 | 0.375 | 0.458 | 0.594 |
| VideoProcessor GPU completion | 6.218 | 5.568 | 9.271 | 11.382 |
| GPU wait/synchronization | 8.398 | 7.995 | 11.441 | 14.041 |
| AMF SubmitInput/backpressure | 0.326 | 0.214 | 0.670 | 1.069 |
| AMF QueryOutput | 0.170 | 0.107 | 0.390 | 0.625 |
| Packet write | 0.176 | 0.141 | 0.418 | 0.617 |
| Audio mux | 657.249 | 657.249 | 657.249 | 657.249 |

`CopyResource submission` i `VideoProcessor CPU submit` są czasami enqueue po stronie CPU. Nie są raportowane jako wykonanie GPU. `VideoProcessor GPU completion` pochodzi z zapytań timestamp D3D11, a `GPU wait/synchronization` mierzy osobno czas oczekiwania CPU na zakończenie zapytań. Końcowy drain AMF jest objęty timerem end-to-end, nie jest sztucznie dopisywany do próbki pojedynczej klatki.

Największym baseline bottleneckiem pozostaje niezmieniony CPU `BlendRGBAToNV12` (AVG 132.169 ms), następnie `compose_overlay`, telemetry i `PIL tobytes`. ETAP 0 ich nie optymalizuje.

## FRAME ACCOUNTING

| Counter | Frames |
|---|---:|
| Source metadata | 1131 |
| Requested (`ceil(duration × 29.97)`) | 1132 |
| FFmpeg decoded | 1131 |
| HUD generated | 1131 |
| Native HUD updates | 1131 |
| Native video updates | 1131 |
| Native processed | 1131 |
| VP processed | 1131 |
| AMF submitted | 1131 |
| AMF output | 1131 |
| Muxed video | 1131 |

Różnica `requested=1132` kontra `source/decoded=1131` wynika z zaokrąglenia żądanego czasu przez `ceil`; FFprobe źródła raportuje dokładnie 1131 klatek, a końcowy niepełny odczyt pipe nie jest liczony jako klatka ani próbka timingu.

Przed ETAPEM 0 AMF miał 1131 submissions, ale tylko 1130 outputs, ponieważ flush kończył drain na pierwszym `AMF_REPEAT`. Obecny flush czeka do `AMF_EOF`; jest to dozwolona naprawa correctness i przywraca ostatnią klatkę źródłową.

## AMF

**INPUT_FULL count:** 0

**Retries:** 0

**Dropped frames/submissions:** 0

**Ignored submissions:** 0

`AMF_INPUT_FULL` nie jest już traktowane jak sukces. Kod liczy zdarzenie i retry, odbiera gotowy packet i ponawia dokładnie tę samą surface bez zmiany queue depth ani ustawień AMF. Limit błędu nie wystąpił w baseline.

## NO HUD — obecne zachowanie

| Operacja | Wynik |
|---|---|
| compose_overlay executed | YES |
| tobytes executed | YES |
| HUD memcpy/update_hud executed | YES |
| Blend 4K executed | YES |

To potwierdzenie aktualnej ścieżki referencyjnej. Nie wykonano optymalizacji no-HUD.

## DIAGNOSTICS

**Production checkpoint readbacks:** OFF

**Debug flag works:** YES

`AMD_NATIVE_DIAGNOSTICS` jest domyślnie OFF. Pełny normalny eksport nie zmienił SHA żadnego checkpointu. Krótki eksport z flagą ON wykonał wszystkie checkpointy A–F, readbacki GPU, konwersję NV12→RGBA i zapis PNG. Kod diagnostyczny nie został usunięty.

## GOLDEN REGRESSION

Golden sprzed zmian i finalny ETAP 0 zostały zachowane w `Raporty/AMD_ETAP0_GOLDEN`. Klatki są indeksowane od zera.

| Check | Result |
|---|---|
| Frame 30 | PASS — exact pixel equality, MAE 0, max diff 0 |
| Frame 300 | PASS — exact pixel equality, MAE 0, max diff 0 |
| Frame 900 | PASS — exact pixel equality, MAE 0, max diff 0 |
| FIT | PASS |
| GPMF | PASS |
| Map | PASS |
| Date/time | PASS |
| Color | PASS |
| Audio | PASS — identyczny bitowo AAC/ADTS SHA-256 |
| Frame count | PASS — 1131/1131 po naprawie drainu |

Audio przed i po ma identyczny SHA-256 ADTS: `e7d3fa3df057f0705bf2f8410b6fde44fac298002a55bdb1b6ec403e642d1ff3`.

Kontrola wizualna klatki 900 potwierdziła clean base video, dynamiczne FIT/GPMF, mapę, date/time, brak clippingu i brak zielonych/magentowych artefaktów. Wartości telemetryczne 30/300/900 zapisano osobno jako regression-only; renderer ich nie hardcoduje.

## FALLBACK / REFERENCE

Aktualny CPU-blend `BlendRGBAToNV12` pozostaje produkcyjną ścieżką referencyjną. Software fallback w `streaming.py` pozostaje aktywny w razie odrzucenia DLL, niezgodnego ABI albo błędu native exportu. Nie usunięto żadnej ścieżki potrzebnej do przyszłego A/B `REFERENCE` kontra `NEW OPTIMIZED PATH`.

## WERYFIKACJA

- CMake configure + dwa clean buildy: PASS.
- Ładowanie DLL i C ABI: PASS.
- Krótki eksport diagnostics OFF: 31/31, checkpointy bez zmian.
- Krótki eksport diagnostics ON: 31/31, checkpointy wykonane.
- Pełny produkcyjny eksport FIT+GPMF: PASS, 1131/1131.
- `pytest`: 145 passed, 17 skipped.
- `git diff --check`: PASS.

## KRYTERIA PASS

1. Deterministyczny build DLL z repo: PASS.
2. Clean build: PASS.
3. Dokładna DLL + build ID w logu GUI/backendu: PASS.
4. Golden reference: PASS.
5. Checkpointy OFF w produkcji: PASS.
6. Profiling: PASS.
7. TRUE FPS baseline: PASS.
8. Frame accounting: PASS.
9. AMF_INPUT_FULL mierzone i poprawnie obsługiwane: PASS.
10. Finalny output odpowiada golden reference: PASS, z intencjonalnym odzyskaniem ostatniej klatki podczas AMF drain.

ETAP GPU HUD nie został rozpoczęty.
