# TeleM — INTEL ETAP 1B: walidacja sprzętu Intel + Quadro P400

Data: 2026-08-24  
Zakres: diagnostyka sprzętu i aktualnej implementacji `INTEL_FORCE`; bez implementacji ETAP 2.

## Hardware

Systemowa enumeracja DXGI TeleM (kolejność rzeczywista):

| index | name | vendor_id | device_id | dedicated VRAM | d3d11_device_ok |
|---:|---|---:|---:|---:|---|
| 0 | NVIDIA Quadro P400 | `0x10DE` | `0x1CB3` | 1966 MiB | true |
| 1 | Intel(R) UHD Graphics 730 | `0x8086` | `0x4692` | 128 MiB | true |
| 2 | Microsoft Basic Render Driver | `0x1414` | `0x008C` | 0 MiB | true |

CPU: 12th Gen Intel(R) Core(TM) i5-12400. Systemowe `Win32_VideoController` potwierdziło oba fizyczne adaptery. Sterowniki: Intel `32.0.101.7085`, NVIDIA `32.0.15.7712`.

## Intel force

`resolve_intel_force()` wybrał:

```text
[INTEL] Selected adapter: Intel(R) UHD Graphics 730
[INTEL] Vendor ID: 0x8086
[NVIDIA] Adapter ignored: INTEL_FORCE active
[UNKNOWN] Adapter ignored: INTEL_FORCE active
[INTEL] INTEL_D3D11_DEVICE: OK
[INTEL] INTEL_CROSS_GPU_FALLBACK: DISABLED
```

Wybór jest po Vendor ID, nie po indeksie. Quadro był adapterem 0 i nie został wybrany.

## FFmpeg / QSV

```text
ffmpeg version 2023-06-26-git-285c7f6f6b-full_build-www.gyan.dev
```

Dostępne hwaccels: `cuda`, `dxva2`, `qsv`, `d3d11va`, `opencl`, `vulkan`.
FFmpeg zawiera `h264_qsv` i `hevc_qsv` (również inne encodery/dekodery QSV).

Realne krótkie testy sprzętowe, 320x240, 1 s, 30 klatek:

- `h264_qsv`: PASS, kod wyjścia 0; log: `Initialized an internal MFX session using hardware accelerated implementation`.
- `hevc_qsv`: PASS, kod wyjścia 0; ten sam komunikat sprzętowej sesji oneVPL/MFX.

Wniosek: `QSV_PRESENT_IN_FFMPEG = YES`, `QSV_HARDWARE_USABLE = YES`; encodowanie QSV jest zweryfikowane sprzętowo na Intel.

## Device selection

| część | status | dowód / ograniczenie |
|---|---|---|
| DECODE | NOT PROVEN | aktualna ścieżka buduje tylko `-hwaccel d3d11va`/`dxva2` przez `detect_gpu_decoder()`; brak `-hwaccel_device` lub równoważnego pinningu Intel |
| D3D11 / COMPOSITOR | PROVEN dla utworzenia urządzenia, NOT PROVEN dla render pipeline | `D3D11CreateDevice` na konkretnym adapterze Intel: OK; aktualny builder nie tworzy/podaje Intel device do kompozytora; Intel używa CPU filter chain |
| ENCODE | PROVEN jako QSV encode, NOT PROVEN jako przypięty TeleM pipeline | realne `h264_qsv` i `hevc_qsv` działają; komenda TeleM zawiera `-c:v hevc_qsv`, ale nie zawiera `-qsv_device` ani `-init_hw_device qsv=...` |

## NVIDIA isolation

W testach `INTEL_FORCE` nie zaobserwowano użycia CUDA, NVDEC, NVENC ani NVIDIA compositor. Statyczna inspekcja aktualnej ścieżki potwierdza, że `overlay_cuda`, `hwupload_cuda` i `scale_cuda` są warunkowane `encoder == "nv"`; dla `encoder == "intel"` builder używa zwykłych filtrów CPU i `hevc_qsv`.

Nie uruchamiano benchmarków ani testów backendu NVIDIA.

## Current Intel FFmpeg command

Aktualna komenda jest składana dynamicznie. Istotne argumenty dla `encoder="intel"` są następujące:

```text
ffmpeg -y -hwaccel d3d11va -i <input>
  -filter_complex "[0:v]scale=...:...:flags=lanczos[base];...overlay..."
  -c:v hevc_qsv -preset veryfast -global_quality 24
  -look_ahead 0 -async_depth 4 -pix_fmt nv12 <output>
```

Ocena:

- decode adapter selection: `NOT PROVEN` — `-hwaccel d3d11va` bez `-hwaccel_device`;
- filter/device selection: `NOT PROVEN` jako Intel D3D11 — brak `-filter_hw_device`/`-init_hw_device` dla Intel; kompozycja Intel jest CPU;
- encode adapter selection: `NOT PROVEN` jako twardo przypięty Intel — `hevc_qsv` działa sprzętowo, ale brak jawnego `qsv_device`/`init_hw_device`.

## Tests

```text
python -m pytest tests/test_intel_backend.py tests/test_video_helpers.py tests/test_mpv_hwdec.py -q
50 passed in 4.47s
```

Wykonano też realną enumerację DXGI, `resolve_intel_force()` oraz osobne krótkie testy FFmpeg `h264_qsv` i `hevc_qsv`.

## Changed

Nie zmieniono kodu produkcyjnego. Utworzono wyłącznie ten raport.

## Preserved

```text
AMD path preserved statically; runtime validation was not part of this task.
NVIDIA production path preserved; NVIDIA backend was intentionally not runtime-tested.
CPU path preserved.
```

## Not proven

- Intel-only decode dla aktualnego renderu TeleM;
- Intel D3D11 compositor/render device w aktualnym pipeline;
- twarde przypięcie QSV encode do konkretnego adaptera przy obecności Quadro;
- pełny finalny render TeleM na Intel-only path;
- brak użycia Quadro w każdym możliwym wariancie preview poza zbadanym `INTEL_FORCE`.

## Recommendation — INTEL ETAP 2

Najmniejsza kolejna zmiana powinna dodać jawny, Intel-specific helper device selection i przekazać go do aktualnego buildera tylko dla `encoder="intel"`: utworzenie QSV/D3D11 device na adapterze o Vendor ID `0x8086`, następnie użycie odpowiednich `-init_hw_device`, `-filter_hw_device`, `-hwaccel_device` i/lub `-qsv_device` zgodnie z możliwościami tej wersji FFmpeg. Należy dodać test argumentów oraz krótki test runtime potwierdzający Intel decode, Intel D3D11 i Intel QSV encode. AMD, NVIDIA i CPU pozostają bez zmian.

## Konkluzja

```text
Intel adapter: VERIFIED
Intel D3D11 device creation: VERIFIED
QSV encode: VERIFIED (h264_qsv, hevc_qsv)
INTEL_FORCE selects Intel despite Quadro being adapter 0: VERIFIED
Quadro ignored by tested INTEL_FORCE path: VERIFIED
Full Intel decode/render/encode pipeline: NOT VERIFIED
```
