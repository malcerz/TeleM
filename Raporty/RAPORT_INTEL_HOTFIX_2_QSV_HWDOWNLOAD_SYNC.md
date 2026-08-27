# TeleM — Intel HOTFIX 2: QSV hwdownload synchronization

Data: 2026-08-25. Aktualny FFmpeg: `F:\_DEV\TeleM\ffmpeg.exe`, `2026-08-17-git-426841da9d-full_build-www.gyan.dev`.

## Real GUI failure and root cause

Zgłoszony błąd produkcyjny:

`[AVHWFramesContext] Error synchronizing the operation: -1` oraz `[hwdownload] Failed to download frame: -1313558101`, zakończone `frame=0`.

Poprzedni hotfix usunął błąd negocjacji `nv12`; nie usunął jednak synchronizacji QSV surface w realnym streamingu. Minimalny probe `QSV decode -> hwdownload p010le` przechodził, ale nie odwzorowywał lifetime/synchronizacji surface w produkcyjnym `stream_overlay_to_ffmpeg` z process-pool HUD i pipe writerem.

## Production command BEFORE

Przed hotfixem komenda nadal zawierała:

`-hwaccel qsv -hwaccel_device intel_qsv -hwaccel_output_format qsv`

oraz:

`[0:v]hwdownload,format=p010le,scale=...`

Pierwszy błąd następował na transferze QSV hardware frame do CPU.

## Production command AFTER

Dla odrzuconego native HDR/10-bit fallback komenda używa:

`-init_hw_device qsv=intel_qsv,child_device=1,child_device_type=d3d11va -qsv_device 1 -i Video/GX020079.MP4`

bez:

`-hwaccel qsv`, `-hwaccel_output_format qsv` i `hwdownload`.

Filter graph:

`[0:v]format=p010le,scale=1280:720:flags=lanczos[base]; ... [base][ov]overlay=...`

Encoder pozostaje:

`-c:v hevc_qsv ... -pix_fmt p010le`

QSV device jest nadal przypięty dynamicznie do Intel UHD 730 (`0x8086`, device `0x4692`); nie zakodowano indeksu w kodzie.

## Decode / CPU formats / HDR metadata

Materiał źródłowy: `yuv420p10le`, 10-bit, BT.2020NC, HLG `arib-std-b67`, full/PC range.

Nowa ścieżka: software HEVC decode -> `format=p010le` CPU working format -> CPU scale/overlay/HUD -> QSV HEVC encode. Output probe: `yuv420p10le`, BT.2020NC, HLG, BT.2020, PC range. Nie dodano tone mappingu ani konwersji HDR do 8-bit.

Diagnostyka runtime:

`[INTEL] Decode path: SOFTWARE`

`[INTEL] CPU working format: 10-bit`

`[INTEL] HWDownload used: NO`

## Real TeleM streaming runtime test

Wykonano rzeczywisty entry point `stream_overlay_to_ffmpeg` z process-pool HUD writerem, aktywnym HUD, materiałem `Video/GX020079.MP4`, 180 klatkami i Intel encoderem. To nie był wyłącznie ręczny probe CLI.

Wynik: PASS, FFmpeg exit code 0, output MP4 utworzony, 5.638967 s, 180 wygenerowanych klatek. Log potwierdza native rejection `hdr_or_non_8bit_source`, software decode i brak hwdownload.

## SDR regression and native regression

8-bit SDR CPU_REFERENCE nadal używa istniejącego QSV decode -> `hwdownload,format=nv12` -> CPU composite -> QSV encode; test zakończył się exit code 0.

Intel D3D11_NATIVE SDR nadal używa QSV decode, `scale_qsv`, bounded HUD upload i `overlay_qsv`; test zakończył się exit code 0. Native eligibility nie została rozszerzona.

## Tests

Focused suite: `51 passed in 1.02s`.

Dodano asercje dla:

- HDR/10-bit software decode: brak `hwdownload`, `format=p010le`, encoder `p010le`;
- 10-bit CPU fallback z QSV hwdownload pozostaje rozdzielony od nowej ścieżki;
- 8-bit CPU_REFERENCE `nv12`;
- Intel native SDR bez `hwdownload` i z `overlay_qsv`;
- brak CUDA/NVENC/AMF leakage.

## Changed / preserved

Zmieniono `src/ffmpeg/streaming.py`, `src/ffmpeg/command_builder.py` i `tests/test_video_helpers.py`. AMD, NVIDIA, GUI, telemetry, map, HUD region, multi-file, rotation, QSV quality settings oraz Intel D3D11_NATIVE nie zostały celowo zmienione. Wcześniejsze niezatwierdzone zmiany ETAPU 3B/3C w tych plikach pozostają w working tree.

## Final status

`REAL HDR TELEM EXPORT: PASS`

`QSV HWDOWNLOAD IN HDR CPU_REFERENCE: NO`

`NVIDIA USED: NO`
