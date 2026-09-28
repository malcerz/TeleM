# AMD 8K P010 plane-separated readback

## Zakres

Zachowano istniejący, potwierdzony 8K decode/copy/shader/event-query path.
Nie zmieniano NVIDIA, Intel, 4K AMF, map, GPMF, queue ani UI.

```text
TRUE_8K_REQUIRED=True
FINAL_OUTPUT=7680x4320
8K_CPU_X265_BIT_DEPTH=10
```

## Implementacja

Dodano eksperymentalny, domyślnie wyłączony przezroczysty dla 4K path
`AMD_8K_PLANE_READBACK=1`:

```text
P010 input
 -> GPU R16_UNORM Y 7680x4320
 -> GPU R16G16_UNORM UV 3840x2160
 -> osobne staging Y/UV
 -> completion query
 -> Map i row-by-row CPU pack P010
```

GPU shader kopiuje wartości `R16_UNORM`/`R16G16_UNORM` bez redukcji do R8,
więc nie ma konwersji 10-bit -> 8-bit -> 10-bit. NV12 AMF path pozostał
niezmieniony.

Ring ma trzy sloty i osobny query; slot jest konsumowany przed ponownym
użyciem. Nie dodano `Flush()` per frame. Jednorazowy `Flush()` występuje
wyłącznie przy EOS drain.

## Gate A — obecny multiplanar staging

```text
CURRENT_MULTIPLANE_STAGING_2F=FAIL
CURRENT_MULTIPLANE_FIRST_FAIL=multiframe NV12 staging path; device removal before Map/EOS drain
DEVICE_REASON=0x887A0020 (DXGI_ERROR_DRIVER_INTERNAL_ERROR)
```

Wprowadzono timeout query 10 s oraz logowanie formatu, CopyResource, query,
Map, RowPitch/DepthPitch i device reason. Test zakończył się fail-fast, bez
120-sekundowego oczekiwania.

## Gate B — Y-only plane staging

```text
Y_READBACK_2F=FAIL
Y_READBACK_10F=NOT RUN
Y_READBACK_100F=NOT RUN
```

Frame 0 wykonał shader oraz `R16_UNORM` `CopyResource` z
`DEVICE_REASON=0`. Przed ukończeniem drugiej klatki/EOS urządzenie zgłosiło
`0x887A0020`. Gate Y-only nie wykonuje UV `CopyResource`, więc failure nie
jest wynikiem przypadkowego skopiowania obu plane'ów.

## Gate C/D — UV i ring

```text
UV_READBACK_2F=NOT RUN (fail-fast after Y-only failure)
UV_READBACK_10F=NOT RUN
UV_READBACK_100F=NOT RUN
PLANE_RING_10F=NOT RUN
PLANE_RING_100F=NOT RUN
```

## P010 contract

```text
SOURCE_BIT_DEPTH=10
GPU_INTERMEDIATE_BIT_DEPTH=10 (R16/R16G16 P010 value contract)
CPU_READBACK_BIT_DEPTH=NOT REACHED
X265_INPUT_BIT_DEPTH=NOT REACHED

Y_ROW_BYTES=15360 (expected; Map not reached)
Y_ROW_PITCH=NOT REACHED
UV_ROW_BYTES=15360 (expected; Map not reached)
UV_ROW_PITCH=NOT REACHED
PACKED_P010_BYTES_PER_FRAME=99532800 (expected)
TRUE_10BIT_PRESERVED=GPU contract preserved; end-to-end NOT PROVEN
```

## Readback and x265

```text
GPU_COPY_Y_MS=measured on frame 0; value emitted in P010_PLANE_COPY log
GPU_COPY_UV_MS=not applicable to Y-only gate
QUERY_WAIT_MS=NOT REACHED
MAP_Y_MS=NOT REACHED
MAP_UV_MS=NOT REACHED
CPU_PACK_MS=NOT REACHED
TOTAL_READBACK_MS=NOT REACHED

X265_1F=NOT RUN in this stage (previous NV12 1f result is not a valid 10-bit proof)
X265_3F=NOT RUN
X265_10F=NOT RUN
X265_MS_PER_FRAME=NOT RUN
X265_FPS=NOT RUN

FFPROBE_CODEC=NOT RUN
FFPROBE_PROFILE=NOT RUN
FFPROBE_RESOLUTION=NOT RUN
FFPROBE_PIX_FMT=NOT RUN
```

The script was corrected to use `p010le` for plane readback and to fail when
the native flush returns failure. No x265 test was started after the Y gate
failure.

## Regression/build

```text
BUILD=PASS telem_amd_native
4K_AMF_REGRESSION=NOT RUN (fail-fast after plane Y gate)
TOTAL_STAGE_WALL_TIME=~25 min estimated active execution
LONGEST_SINGLE_COMMAND_SECONDS=8.3
```

## Final status

```text
CASE=C — staging driver fails even on single-plane R16 output
STATUS=BLOCKED
ROOT=DXGI_ERROR_DRIVER_INTERNAL_ERROR 0x887A0020 after the first R16 Y staging copy, before query/Map completion
```

The result does not prove that the GPU plane shader is invalid: shader/SRV
creation and the first Y copy submit succeed. It proves that this AMD device
also cannot complete the tested 8K single-plane staging readback path. Further
UV/ring/packing/x265 gates were intentionally stopped.
