# RAPORT INTEL ETAP 5D — REAL GUI regression: lost REGION HUD + telemetry precompute timezone bug + 180° rotated final MP4 (OX)

Data: 2026-08-26 · Tryb: TARGETED AUDIT → REAL GUI REPRODUCTION → ROOT CAUSE → SMALL FIX → REAL GUI VALIDATION
Źródło prawdy: prawdziwy GUI run użytkownika (GX020079.MP4, 4K HDR, Intel UHD 730 + ignorowana Quadro P400, single-file, CPU_REFERENCE/SOFTWARE decode/P010/HWDownload NO/hevc_qsv/40M/-r 30000/1001).

---

## State pinning

- Branch `intel-render`, HEAD `e019a6b…` (bez commitów), working tree zawiera serię 3B–5C + zmiany 5D.
- Evidence 5D: `scratch/intel_etap5d/**` (repro_precompute, rotation_contract, orientation_check, smoke_gui/multi, patch skrypty, logi).

## Real GUI reproduction

Odtworzono produkcyjny przeplyw: render_mixin (rotation_degrees=get_rotation_from_metadata, container_rotation=get_container_rotation, overlay=render*hud_scale, video_timeline, aware start_dt_utc) -> stream_overlay_to_ffmpeg. GX020079: Display Matrix rotation=-180 => GUI przekazuje rotation_degrees=180, container_rotation=180. Layout uzytkownika = def_layout.json: 23 wskazniki ROZRZUCONE po calej klatce (x 0.77..93.93%, y 4.32..91.47%), kazdy z jawnym form= (time_display/text/map size=18/lean size=8).

## Regression summary

A: lost REGION - DWA czynniki: (1) [BUG] _intel_hud_region_gate blokowal REGION dla KAZDEGO zrodla z rotacja != 0 w real GUI (harness 5A podawal domyslne 0, stad rozjazd); (2) [GEOMETRIA] realny layout ma ratio bboxa = 1.000 >= 0.85, wiec dla TEGO projektu FULL_CANVAS jest poprawna decyzja geometryczna.

B: telemetry precompute timezone bug - build_telemetry_cache liczyl elapsed jako dt(naive z VideoTimeline.frame_to_absolute) - start_dt_utc(aware z GUI) => TypeError offset-naive/aware => caly precompute wylaczany => live resolver ~57 ms/frame.

C: 180 stopni rotated final MP4 - produkcja uzywala kontraktu -noautorotate + vflip,hflip (bake) + -metadata rotate=0; empirycznie: MP4 muxer KOPIUJE Display Matrix side-data do outputu (-metadata nie czysci side-data) => player obraca drugi raz => DOUBLE_ROTATION. Pomiar: top/bot luma REF(upright)=106.86/141.32; PROD=141.32/106.86 (INVERTED); autorot=106.86/141.32 (match).

## GUI vs harness diff

| wejscie | harness 5A/5B/5C | real GUI |
|---|---|---|
| rotation/container | brak (0) | 180/180 |
| layout | 3 sztuczne wskazniki w rogu | 23 realne rozrzucone (form=map/lean/time_display) |
| start_dt_utc | naive EPOCH (T1/T2) | AWARE UTC (+00:00) |
| field_samples/fit_data/gps_track/workers/video_bitrate | puste/defaulty | pelne GUI |

## REGION audit

get_layout_hud_bbox(def_layout,3840x2160) => (0,0,3840,2160), ratio=1.000; threshold 0.85; gate przed naprawa: rotation!=0 => False => FULL_CANVAS bez decision logu o geometrii. Env flagi: TELEM_INTEL_CPU_REF_HUD_REGION domyslnie ON; MAX_RATIO 0.85.

## REGION root cause

PRIMARY (kod): rotacyjny warunek gate'a dla CPU_REFERENCE - nieaktualny po przejsciu Intel na kontrakt autorotate (base wchodzi do grafu upright, HUD crop dzieli wspolrzedne z overlay destination). SECONDARY (dane): realny layout uzytkownika pokrywa caly canvas => ratio 1.0 => FULL_CANVAS poprawny niezaleznie od gate'a.

## REGION fix

ZAIMPLEMENTOWANY (czesc kodowa): _intel_hud_region_gate(..., encoder) - dla encoder==intel CPU_REF decyzja geometryczna zapada niezaleznie od rotacji; inne encodery zachowuja stare reguly. Dla obecnego layoutu uzytkownika wynik pozostaje FULL_CANVAS reason=ratio_above_threshold(1.000>=0.85) - to jest POPRAWNE (pelny transport, zero utraty wskaznikow); REGION aktywuje sie automatycznie dla layoutow skupionych (test dowodzi na real-shape clustered layout: mode=region, ratio<0.85, even-aligned crop).

## Telemetry datetime audit

Wyjatek: telemetry_precompute.py, build_telemetry_cache, sekcja Record Assembly (elapsed_secs_arr = (dt - start_dt_utc)). target_dts: VideoTimeline.frame_to_absolute zwraca NAIVE UTC (konwencja projektu, src/multifile.py); start_dt_utc real GUI = AWARE UTC.

## Datetime source objects

A (dt): VideoTimeline.frame_to_absolute => naive UTC (multifile _as_naive_utc). B (start_dt_utc): GUI telemetry anchor => aware UTC 2026-08-11T04:27:21+00:00. Rozbieznosc w logu absolute= bez +00:00 to formatting; obiekty byly mieszane naive/aware.

## Telemetry precompute root cause

Brak normalizacji na granicy timeline->precompute przy AWARE anchorze (single-file GUI tworzy 1-klipowy VideoTimeline).

## Telemetry fix

ZAIMPLEMENTOWANY (najwezszy boundary): (1) normalizacja calej listy target_dts do naive-UTC zaraz po budowie (astimezone(UTC).replace - bez blind replace na nieznanej strefie), (2) elapsed liczone wzgledem start znormalizowanego tym samym helperem. Import timezone. Live resolver niezmieniony.

## Rotation contract

Nowy kontrakt Intel: import z AUTOROTATE ON. Empiria: autorot wariant => output BEZ Display Matrix i pixel-match z upright REF (diff 0.71 = kompresja). Bake+metadata-rotate-0 => matrix SKOPIOWANY do outputu => double rotation (diff vs REF 61.25, inverted).

## Source / preview / export comparison

Source w playerach/preview: upright (metadata respektowana). Export przed naprawa: pixels upright(bake) + metadata -180 => wyswietlany INVERTED. Po naprawie: pixels upright + brak metadanych => zgodny ze source/preview. Preview i export uzywaly ROZNYCH kontraktow (preview czytal metadata; export bake+zostawial metadata) - to byl rdzen C.

## Rotation metadata audit

ffprobe source: side_data_list=[Display Matrix rotation=-180], tags.rotate BRAK. Output przed naprawa: ta sama Display Matrix obecna. Po naprawie: side_data_list=[] i tags puste.

## Rotation root cause

PRIMARY: DOUBLE_ROTATION (manual bake vflip,hflip + skopiowana Display Matrix w output MP4; -metadata rotate=0 nie czysci side-data). Secondary: PREVIEW_EXPORT_CONTRACT_MISMATCH jako mechanizm powstania bledu.

## Rotation fix

ZAIMPLEMENTOWANY: streaming -noautorotate pomijany dla encoder==intel (NV/AMD/CPU kontrakt bez zmian); command_builder: intel SW-decode i hwdownload branchy usunely reczne vflip,hflip/transpose (pozostaje format/scale). 5B rational -r, writer lifecycle, REGION logic, frame count, timeline - nietkniete.

## Real GUI after-fix validation

Real-GUI-like smoke (GX020079, 4K HDR, rotation 180/180, real def_layout, aware anchor):

- frames: 300/300 exact (5B preserved)
- pix_fmt yuv420p10le, arib-std-b67 (HDR preserved)
- output rotation metadata: [] (C fixed)
- final composite orientation: top/bot luma 107.16/141.36 vs REF 106.86/141.32 => NOT rotated (diff 1.67 = HUD+kompresja)
- cmd: brak -noautorotate, brak vflip/hflip, -r 30000/1001 obecne (5B preserved)
- [STREAM] Telemetry mode: PRECOMPUTED (300 frames) - brak offset-naive/aware erroru (B fixed)
- HUD upload path: FULL_CANVAS reason=ratio_above_threshold(1.000>=0.85) - poprawna geometrycznie decyzja dla obecnego layoutu uzytkownika, z jawnym powodem w logu

## Multi-file safety

2x canonical przez granice klipu, aware anchor + timeline: precompute OK (bez fallbacku), decoded 360/360, orientacja kontrakt wspolny. Native multi-file nadal poza zakresem.

## Performance before/after

Strukturalnie: precompute aktywny usuwa live-resolver ~57 ms/frame z sciezki renderera; REGION dla TEGO layoutu pozostaje FULL_CANVAS (ratio 1.000 - geometrycznie poprawne), wiec overlay_rendering (~256 ms przy 4K RGBA canvas) nie zmienia sie dla tego projektu i wymaga oddzielnego zadania (np. per-indicator region packing) jesli layout ma zostac rozrzucany. Preview_cycle (3.4 FPS) to osobna metryka preview - nie mylic z export throughput (ffmpeg_write n=300). Brak deklaracji speedupu (proby male/noisy).

## HDR validation

yuv420p10le / bt2020nc / bt2020 / arib-std-b67 kompletne; bez tone mappingu; hevc_qsv 40M.

## NVIDIA isolation

Log: Selected adapter Intel UHD 730 index 1 (dynamicznie), Quadro enumerated+ignored; zero cuda/nvenc/nvdec/cuvid w Intel grafie. NV rot180 CUDA fast-path i -noautorotate kontrakt NV nietkniete (warunek encoder!=intel).

## Tests

Nowe: tests/test_etap5d_real_gui_regressions.py (7): REGION real-nested-layout rotated => region; full-span => full_threshold+reason; non-intel unrotated-only rule; def_layout bbox sanity; precompute aware-anchor+timeline (brak wyjatku, elapsed/speed parity, local time), pure-aware path; Intel SW-decode rotated graph bez baked flips.
Zaktualizowane do nowego kontraktu: test_intel_cpu_ref_region_rotation_graphs, test_intel_hud_region_gate_switches, test_intel_and_cpu_pipeline_unchanged, test_intel_rotation180_no_nv2 (stare kodowaly bake-flips kontrakt).
Focused suite: 81 passed. Full suite: 1107 passed / 22 skipped / 30 failed / 5 errors (= baseline 5B + 7 nowych testow; failures identyczne/pre-existing).

## Changed files

- src/ffmpeg/streaming.py: gate(encoder=...) + pomijanie -noautorotate dla intel
- src/ffmpeg/command_builder.py: intel branchy bez recznych rot-transformow
- src/telemetry_precompute.py: naive-UTC boundary normalization + import timezone
- tests/test_video_helpers.py: 4 testy aktualizowane do autorotate contract
- tests/test_etap5d_real_gui_regressions.py: NOWY (7 testow)
- Raporty/RAPORT_INTEL_ETAP_5D_REAL_GUI_REGRESSION_OX.md + scratch/intel_etap5d/**

## Remaining limitations

- REGION dla rozrzutnego layoutu uzytkownika: ratio 1.000 => FULL_CANVAS (poprawne); ewentualna optymalizacja = dedykowane zadanie (per-indicator packing), nie 5D.
- overlay_rendering ~256 ms @4K FULL canvas pozostaje do osobnej optymalizacji.
- AMD native exporter: stary rotation wzorzec - poza zakresem (freeze).

## Recommendation

JEDEN nastepny krok: real GUI render przez uzytkownika (ten sam GX020079 projekt) celem wizualnego potwierdzenia upright + PRECOMPUTED w GUI logu, nastepnie commit zestawu 5A..5D wg planu 5C uzupelnionego o pliki 5D.
