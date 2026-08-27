# TeleM — Intel HOTFIX: CPU_REFERENCE 10-bit / HDR hwdownload

Data: 2026-08-25. Aktywny FFmpeg: `F:\_DEV\TeleM\ffmpeg.exe`, `2026-08-17-git-426841da9d-full_build-www.gyan.dev`.

## Root cause

Realny materiał `Video/GX020079.MP4` ma `yuv420p10le`, BT.2020, transfer HLG (`arib-std-b67`) i full/PC range. Intel native eligibility prawidłowo go odrzucała, ale CPU_REFERENCE używał bezwarunkowo `hwdownload,format=nv12`. Aktualny FFmpeg zgłaszał:

`[hwdownload] Invalid output format nv12 for hwframe download.`

Pierwszy złamany kontrakt występował na granicy QSV hardware surface -> CPU filter graph, przed `scale`, `overlay` i encoderem.

## Reproduction before

Wygenerowana przed zmianą komenda zawierała:

`[0:v]hwdownload,format=nv12,scale=1280:720:flags=lanczos[base]`

Minimalny probe na tym samym pliku potwierdził: `format=p010le` przechodzi, natomiast `format=nv12` kończy się `Invalid output format nv12`.

## Fix and verified command

Format jest wybierany po `ffprobe stream=pix_fmt`:

- 8-bit -> `nv12`
- 10-bit (`yuv420p10le`) -> `p010le`

Komenda po zmianie zawierała:

`[0:v]hwdownload,format=p010le,scale=1280:720:flags=lanczos[base]`

oraz:

`-c:v hevc_qsv ... -pix_fmt p010le`

Nie zmieniono preset, quality, look-ahead, async depth, rate control ani bitrate.

## HDR final render

Krótki render realnego materiału zakończył się PASS:

- Intel selected: YES, dynamiczny adapter `vendor_id=0x8086`
- native eligibility: REJECTED (`hdr_or_non_8bit_source`)
- render path: `CPU_REFERENCE`
- download format: `p010le`
- QSV encode: `hevc_qsv`, PASS
- FFmpeg exit code: 0
- output: `scratch/intel_etap3b/HDR_CPU_REFERENCE.mp4`

Output probe: `hevc`, `yuv420p10le`, `bt2020nc`, `arib-std-b67`, `bt2020`, `pc`, 1280x720. Bit depth i metadata HDR zostały zachowane; nie dodano tone mappingu.

## SDR regression

Istniejący 8-bit SDR CPU_REFERENCE nadal generuje `hwdownload,format=nv12` i przechodzi. Intel D3D11_NATIVE SDR nadal nie zawiera `hwdownload`, używa `scale_qsv` / `overlay_qsv` i pozostaje ograniczony do dotychczasowej eligibility.

## Changed files

- `src/ffmpeg/streaming.py`: probe wejściowego pixel format i wybór CPU download format; diagnostyka.
- `src/ffmpeg/command_builder.py`: Intel CPU_REFERENCE `nv12` vs `p010le` oraz odpowiedni QSV encoder pixel format.
- `tests/test_video_helpers.py`: asercje 8-bit, 10-bit, native i brak CUDA/AMF/NVENC leakage.

W working tree istniały wcześniejsze zmiany z ETAPU 3B/3C; hotfix nie zmienia AMD, NVIDIA, HUD region, `overlay_qsv`, `scale_qsv`, native eligibility, GUI, telemetry, map, multi-file ani rotation policy.

## Tests

Focused suite: `51 passed in 1.47s`.

Obejmuje `tests/test_intel_backend.py`, `tests/test_video_helpers.py`, `tests/test_gpu_compositor.py`, `tests/test_amd_native_overlay_handoff.py`.

## Preserved

AMD preserved. NVIDIA preserved. CPU generic path preserved. Intel native SDR preserved. HDR nie został rozszerzony do native. Nie dodano konwersji HDR do 8-bit NV12.
