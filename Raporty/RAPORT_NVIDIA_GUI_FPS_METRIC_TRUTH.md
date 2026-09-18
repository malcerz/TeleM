# NVIDIA GUI FPS metric truth

Nie wykonywano optymalizacji. Wykonano wyłącznie diagnostyczne przechwycenie sygnału GUI oraz analizę istniejących timerów. Workload obu nowych capture'ów jest identyczny: `GX020079.MP4`, `GX020079.fit`, `def_layout.json`, 3840×2160, HEVC Main10, 40M, Full HUD, 1131 klatek.

## Implementacja licznika GUI

Źródła:

- `src/gui/qt/tabs/render_tab.py:1297`, `_on_render_progress()` → `_set_stats()` (label at `:1499–1503`): etykieta `FPS:` formatuje dokładnie wartość `fps` przekazaną przez sygnał `sig_render_progress` (`fps_txt = f"{fps:.1f}"`).
- Legacy: `src/ffmpeg/streaming.py:620`, `_report_stream_progress()`; producer `start_time=time.time()` is set at `:1645` just before the producer/writer loop. `done` is the number of frames sent to the pipe. There is no averaging window or warm-up correction.
- Native: `src/ffmpeg/nvidia_native_exporter.py:2026`, polling loop `telem_nvenc_get_progress()` (`:2060`); `t_start=time.perf_counter()` is set before `telem_nvenc_start_export`. DLL progress starts at `native/d3d11_nvenc_pipeline/src/d3d11_nvenc_pipeline.cpp:4313` and updates `current_fps` at `:4965`.

```text
Legacy GUI_FPS = done / (time.time() - start_time)
Native GUI_FPS = progress.current_fps
Native current_fps = completed / (QPC_now - wall_t0)

GUI_FPS_FORMULA=Legacy: done/(time.time()-start_time); Native: completed/(QPC_now-wall_t0); Qt displays latest callback without averaging
```

Frame counter jest kumulatywny. GUI nie liczy mediany ani ruchomej średniej; Qt tylko wyświetla ostatnią wartość callbacka.

## Benchmark harness

`scratch/nvidia_real_perf_truth/assemble_results.py:97–101` liczył:

```text
EXPORT_END_TO_END_FPS = output_frames / (render_finished_perf - render_click_perf)
FULL_PROCESS_FPS      = output_frames / (process_end_epoch - process_start_epoch)

BENCHMARK_FPS_FORMULA=output_frames / measured wall interval (render_finished-render_click for export end-to-end; process_end-process_start for full-process)
```

To jest timer od kliknięcia Render do sygnału zakończenia (a dla full-process od startu procesu do jego zamknięcia). Obejmuje odpowiednio przygotowanie HUD, backend startup, encoder init, first-frame latency, render loop, drain/mux, file close i GUI completion — zależnie od wybranego zakresu. Nie jest to steady-state producer FPS.

W `src/ffmpeg/streaming.py:2252–2255` istnieje dodatkowo:

```text
PIPELINE_FPS    = total_overlay_frames / (last_frame_time - first_frame_time)
REAL_EXPORT_FPS = total_overlay_frames / t_prod_total
```

`PIPELINE_FPS` wycina prepare/startup i końcowy drain; `REAL_EXPORT_FPS` obejmuje `t_prod_start` → postprocess, ale nie GUI process startup. Native ABI `throughput_fps_native` analogicznie obejmuje natywny `wall_t0` → `wall_t1`, gdzie `wall_t1` jest po drain/file close, przed `EndNvencSession`/`CloseDecoder`.

## Real GUI capture

`run_gui_render.py --timeseries` zapisuje ten sam sygnał `sig_render_progress`, który konsumuje RenderTab. Steady-state quantiles wykluczają pierwsze 2 s od pierwszego render callbacka oraz ostatnią 1 s przed `render_finished`; pełne szeregi są zachowane w artefaktach.

```text
LEGACY_GUI_FPS_MEDIAN=85.870
LEGACY_GUI_FPS_P10=65.923
LEGACY_GUI_FPS_P90=94.128

NATIVE_GUI_FPS_MEDIAN=123.590
NATIVE_GUI_FPS_P10=120.492
NATIVE_GUI_FPS_P90=124.169

STEADY_STATE_GAIN_PERCENT=43.93
```

To są wartości pola `FPS:` w GUI, a nie rolling throughput. Dla kontroli, 1-second rolling FPS wyliczony z tego samego licznika klatek wyniósł `115.749` Legacy i `125.512` Native (`+8.43%`). Ponieważ Legacy i Native mają różne bazy czasu callbacka, `43.93%` nie jest uczciwą miarą przewagi samego renderera. Uczciwa metryka steady-state z tego samego licznika to:

```text
REAL_STEADY_STATE_GAIN=8.43%
```

Jeżeli w innej sesji literalne wartości GUI wynoszą około `110` i `113`, odpowiada to około `2.73%` różnicy tej metryki GUI; nie należy mieszać tego z eksportowym wall FPS.

```text
EXPORT_RENDER_LOOP_FPS=115.749 Legacy rolling / 124.282 Native native wall
EXPORT_END_TO_END_FPS=78.212 Legacy / 107.049 Native
FULL_PROCESS_FPS=61.422 Legacy / 78.736 Native
```

The new capture's wall boundaries are also explicit: Legacy process-start→Render click `2.932 s`, click→finished `14.461 s`, finished→GUI close `1.021 s`; Native respectively `2.778 s`, `10.565 s`, and `1.021 s`. The first interval is startup/project warm-up, the middle interval is the export end-to-end measurement, and the last interval is the deliberate GUI settle/close delay. The exact Legacy producer gap is independently present in the canonical stream log as `PIPELINE_FPS=114.5` versus `REAL_EXPORT_FPS=78.7`, with `4.490 s` of preparation/startup/first-frame/drain/postprocess overhead. The existing harness does not expose a separate timer for each of those sub-stages; the stage file therefore labels its source and does not claim an additive decomposition for Native.

## Obowiązkowe pola

```text
LEGACY_END_TO_END_FPS=78.212
NATIVE_END_TO_END_FPS=107.049
END_TO_END_GAIN_PERCENT=36.87

LEGACY_PREPARE_SECONDS=1.080
LEGACY_RENDER_SECONDS=9.878
LEGACY_MUX_CLOSE_SECONDS=1.030

NATIVE_PREPARE_SECONDS=0.910
NATIVE_RENDER_SECONDS=9.184
NATIVE_MUX_CLOSE_SECONDS=1.030

ROOT_CAUSE_OF_FPS_DISCREPANCY=GUI callback FPS and producer/native-loop FPS exclude different startup/prepare/drain intervals; the earlier 77–84/105–106 values are click-to-finished export-wall FPS, not the GUI callback or steady producer interval.

DECISION=METRICS_SEPARATED_NO_OPTIMIZATION
```

## Dlaczego Legacy wygląda jak >110, a raport miał 77–84

W canonical Legacy logu występują jednocześnie `PIPELINE_FPS=114.5` i `REAL_EXPORT_FPS=78.7`. `PIPELINE_FPS` mierzy tylko od pierwszej do ostatniej klatki zapisanej przez writer. `REAL_EXPORT_FPS` dodaje około `4.490 s` narzutu: HUD preparation (`1.080 s`), worker/FFmpeg/startup/first-frame overhead oraz drain/mux/postprocess. Dlatego `1131 / (9.878 + 4.490) ≈ 78.7`.

Raport sześciu procesów dodatkowo użył `render_finished - render_click`, co dało Legacy median `77–84 FPS` i Native `105–106 FPS`. To poprawny eksportowy wall FPS, ale nie ten sam licznik co producer/GUI steady-state. Wcześniejsze `26–35%` było różnicą eksportowego wall FPS między seriami; nie może być przedstawiane jako przewaga samego renderera. Nie wolno nazywać tych wszystkich wartości „true FPS”.

W tym capture GUI callback Legacy kończy około `95 FPS`, bo jego wzór kumuluje czas od `start_time` ustawionego przed producer loop; nie jest to `PIPELINE_FPS`. To wyjaśnia, dlaczego obserwacja `>110` wskazuje na pipeline/console metric, a nie literalny Qt `FPS:` field. Native callback korzysta z natywnego wall timer i osiągnął około `124 FPS` w tej sesji; wcześniejsze `~113` jest inną, wolniejszą sesją/zakresem, nie dowodem sprzeczności wzorów.

## Artefakty

Wszystkie szeregi i reprodukcja są w `scratch/nvidia_gui_fps_truth/`:

- `legacy_gui_fps_timeseries.csv`
- `native_gui_fps_timeseries.csv`
- `steady_state_summary.csv`
- `stage_breakdown.csv`
- `legacy_gui.result.json`, `native_gui.result.json`

Nie zmieniono kodu produkcyjnego, backendów, HUD, kodeka, layoutu ani ustawień jakości.
