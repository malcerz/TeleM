# TeleM — INTEL ETAP 2: hard device pinning

Data: 2026-08-24

## Active FFmpeg baseline

```text
ACTIVE_FFMPEG_PATH: F:\\_DEV\\TeleM\\ffmpeg.exe
ACTIVE_FFMPEG_VERSION: 2026-08-17-git-426841da9d-full_build-www.gyan.dev
```

The active build was re-probed after the ETAP 2 implementation. It exposes
`qsv`, `d3d11va`, `dxva2`, `d3d12va`, `vaapi`, `vulkan` and other hardware
device types. `-init_hw_device qsv=intel_qsv,child_device=1,child_device_type=d3d11va`
created the Intel device successfully.

Short runtime probes on this build passed:

- H.264 QSV decode: PASS, Intel device `8086:4692` selected;
- H.264 QSV encode: PASS;
- HEVC QSV encode: PASS.

The newer build is now the current validation baseline; the earlier 2023
version mentioned below is historical only.

## Root cause

Poprzedni `INTEL_FORCE` wybierał Intel po Vendor ID i sprawdzał QSV, ale komenda TeleM używała jedynie `-hwaccel d3d11va` oraz `-c:v hevc_qsv`. Nie wskazywało to jawnie konkretnego urządzenia na komputerze multi-GPU.

## Hardware

Aktualna enumeracja DXGI TeleM:

| index | adapter | vendor | device |
|---:|---|---:|---:|
| 0 | NVIDIA Quadro P400 | `0x10DE` | `0x1CB3` |
| 1 | Intel(R) UHD Graphics 730 | `0x8086` | `0x4692` |
| 2 | Microsoft Basic Render Driver | `0x1414` | `0x008C` |

Indeks `1` jest używany wyłącznie jako wynik bieżącej enumeracji; nie jest zahardkodowany.

## FFmpeg feature probe

`ffmpeg -version` w aktualnym PATH nadal zwraca:

```text
2023-06-26-git-285c7f6f6b-full_build-www.gyan.dev
```

Jest to rozbieżne z deklarowaną przez użytkownika wersją `2026-08-17-git-426841da9d`. Źródłem prawdy testu był faktycznie uruchomiony binarny FFmpeg; nie zmieniano środowiska.

Dostępne są `qsv`, `d3d11va`, `dxva2`, `cuda`, `vulkan` oraz encodery/dekodery `h264_qsv` i `hevc_qsv`.

Próba:

```text
-init_hw_device qsv=intel_qsv,child_device=1,child_device_type=d3d11va
```

zakończyła się sukcesem i zalogowała:

```text
Using device 8086:4692 (Intel(R) UHD Graphics 730).
```

`-qsv_device intel_qsv` jest niepoprawne dla tego builda: opcja oczekuje indeksu DirectX i przy nazwie próbowała utworzyć urządzenie NVIDIA. Poprawny wariant to `-qsv_device 1`, gdzie `1` pochodzi dynamicznie z DXGI.

## Implementation

Zmieniono wyłącznie ścieżkę Intel:

- `src/ffmpeg/intel_backend.py` — `IntelDeviceSelection`, dynamiczny indeks oraz helper argumentów FFmpeg; kontrolowana porażka przy braku Intel D3D11.
- `src/ffmpeg/streaming.py` — dla `encoder="intel"` pominięto ogólne wykrywanie hwaccel i dodano jawne device arguments.
- `src/ffmpeg/command_builder.py` — zachowano istniejące parametry jakości QSV; brak zmian w AMD/NVIDIA/CPU.
- `src/ffmpeg/__init__.py` — eksport helperów.
- `tests/test_intel_backend.py` — testy indeksów 0/1 i odrzucenia obcego vendora.

## Generated command

Istotne argumenty wygenerowane dla Intel:

```text
-init_hw_device qsv=intel_qsv,child_device=<dynamic Intel DXGI index>,child_device_type=d3d11va
-hwaccel qsv
-hwaccel_device intel_qsv
-hwaccel_output_format qsv
-qsv_device <dynamic Intel DXGI index>
...
-c:v hevc_qsv -preset veryfast -global_quality 24 -look_ahead 0 -async_depth 4 -pix_fmt nv12
```

## Decode pinning

`PROVEN` dla minimalnego FFmpeg probe. Test z wejściem H.264 pokazał:

```text
Using device 8086:4692 (Intel(R) UHD Graphics 730).
Selecting decoder 'h264_qsv'
Decoder: output is video memory surface
```

W pełnym renderze TeleM pozostaje CPU filter chain po decode; nie jest to zmieniane w ETAP 2.

## Encode pinning

`PROVEN` dla minimalnego probe. `h264_qsv` i `hevc_qsv` zakończyły się poprawnie z:

```text
-qsv_device 1
Initialized an internal MFX session using hardware accelerated implementation
```

Wariant z dynamicznym indeksem jest generowany z wybranego adaptera Intel.

## D3D11 compositor

```text
Intel native D3D11 compositor: NOT IMPLEMENTED IN ETAP 2
```

Intel nadal używa istniejącego CPU filter chain.

## NVIDIA isolation

W testach pinningu log wskazywał `8086:4692`. Nie używano CUDA, NVDEC, NVENC ani NVIDIA compositora. Próba błędnego `-qsv_device intel_qsv` została zatrzymana i nie jest używana w implementacji.

## Runtime TeleM render

Pełny krótki render TeleM nie został uruchomiony w tej walidacji; wykonano minimalne realne testy FFmpeg decode/encode. Nie deklaruję pełnej walidacji finalnego renderu.

## CPU/GPU transfers

Obecna architektura pozostawia możliwy przepływ:

```text
GPU decode -> CPU filter/composite -> QSV encode
```

Jest to znane ograniczenie ETAPU 2 i zakres ETAPU 3.

## Tests

```text
python -m pytest tests/test_intel_backend.py tests/test_video_helpers.py -q
44 passed
```

Wykonano również CLI probes dla QSV device creation, QSV encode i QSV decode.

## Preserved

```text
AMD path preserved.
NVIDIA path preserved.
CPU path preserved.
```

Runtime AMD/NVIDIA nie był testowany.

## Remaining work — INTEL ETAP 3

Zbudować Intel D3D11/QSV compositor lub bezpieczne mapowanie powierzchni, aby ograniczyć przepływ GPU → CPU → GPU, bez zmiany semantyki CPU reference i bez naruszania AMD/NVIDIA.
