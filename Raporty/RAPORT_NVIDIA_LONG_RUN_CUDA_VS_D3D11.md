# NVIDIA long-run CUDA Legacy vs Native D3D11

Nie wykonywano optymalizacji. Wykonano dwa rzeczywiste eksporty przez GUI production path, z identycznym wejściem i 49 920 klatkami.

## Kontrakt

```text
CONFIG_EQUIVALENT=True
VIDEO=Video/GX010291.mp4
FIT=Video/20260911.fit
LAYOUT=def_layout.json
FRAMES=49920
RESOLUTION=3840x2160
FPS=30000/1001
CODEC=HEVC Main10
BITRATE=40M
QUALITY=Fast
HUD_RESOLUTION=Auto
HUD_FREQUENCY=Full
MAP=True
CHARTS=True
AUDIO=True
ROTATION=0 (GUI selection; source container still reports displaymatrix=-180)
```

Oba pliki wynikowe mają po 49 920 klatek, HEVC Main 10, 3840×2160, 30000/1001 i `yuv420p10le`.

## Wynik główny

```text
LEGACY_FRAMES=49920
LEGACY_PIPELINE_FPS=118.409
LEGACY_REAL_EXPORT_FPS=89.237
LEGACY_TOTAL_OVERHEAD_SECONDS=137.195
LEGACY_OVERHEAD_PERCENT=24.6%
LEGACY_FFMPEG_WRITE_AVG_MS=2.15
LEGACY_FFMPEG_WRITE_P95_MS=5.01

NATIVE_FRAMES=49920
NATIVE_PIPELINE_FPS=116.669
NATIVE_REAL_EXPORT_FPS=108.650
NATIVE_TOTAL_OVERHEAD_SECONDS=31.590
NATIVE_OVERHEAD_PERCENT=6.9%

PIPELINE_GAIN_PERCENT=-1.47%
REAL_EXPORT_GAIN_PERCENT=21.75% (raw GUI click-to-finished)

LEGACY_HUD_LONG_RUN_MS=NOT_INSTRUMENTED
NATIVE_HUD_LONG_RUN_MS=7.444676 (aggregate; first/middle/last segments NOT_INSTRUMENTED)

NATIVE_RENDERER_ADVANTAGE=NONE
NATIVE_EXPORT_ADVANTAGE=RAW_21.75_PERCENT_BUT_CONFOUNDED
DECISION=NO-GO
CASE=E
```

`PIPELINE_FPS` używa tego samego diagnostycznego zakresu: pierwszy completed production frame → ostatni completed production frame. Dla Legacy jest to 421.583 s, dla Native 427.868 s. `REAL_EXPORT_FPS` w tym raporcie jest osobno raportowany jako GUI `render_click → render_finished`, bez procesu GUI startup/close. Full-process FPS wyniósł Legacy `88.367`, Native `106.521`.

Native ABI dodatkowo podał własny zakres eksportera `wall_t0 → wall_t1 = 427.932 s`, `throughput_fps_native=116.654`, a różnica względem tego zakresu wyniosła tylko `0.666 s`; nie jest to ten sam zakres co Legacy `REAL_EXPORT_FPS`, dlatego oba poziomy są zachowane osobno.

## Rozbieżność względem referencji Legacy

Referencja użytkownika (`116.5 / 109.0 / 29.727 s`) nie została potwierdzona w tym exact GUI run. `PIPELINE_FPS=118.4` jest podobny, ale `REAL_EXPORT_FPS=89.3` i overhead `137.195 s` są znacznie gorsze. Źródłowy MP4 zawiera `displaymatrix=-180°`; Legacy CUDA nadal przechodzi przez rot180/postprocess ścieżki, a koszt finalnego przetwarzania wielogigabajtowego MP4 jest wliczony do `REAL_EXPORT_FPS`. To koszt ścieżki eksportowej, nie koszt renderer frame loop. Wariant `rotation=auto` został wykonany dodatkowo i ma ten sam charakter; nie jest używany jako główny wynik.

W konsekwencji surowe `+21.75%` Native click-to-finished nie jest dowodem przewagi renderera. Przy odniesieniu do użytkownikowego Legacy `109.0 FPS`, Native `108.65 FPS` daje około `-0.3%`, a pipeline jest faktycznie `1.47%` wolniejszy. Zgodnie z hard gate: `NATIVE_RENDERER_ADVANTAGE=NONE` i decyzja `NO-GO`.

## Device-B i stabilność

Native ABI podał tylko agregat `hud_device_b_ms=7.444676 ms` dla całego przebiegu. First/middle/last 1000-frame means nie były instrumentowane, więc pozostają `NOT_INSTRUMENTED`. Początek/środek/koniec GPU nie były próbkowane w czasie renderu; `gpu_state.csv` zawiera jedynie jawnie oznaczony snapshot post-run.

## Artefakty

Wszystkie artefakty znajdują się w `scratch/nvidia_long_run_truth/`, w tym logi, MP4, timeseries, `performance.csv`, `hud_time_segments.csv`, `gpu_state.csv`, `decision.md`, manifest i komendy reprodukcji. Wysłanie NTFY zapisano w `ntfy_result.txt`.
