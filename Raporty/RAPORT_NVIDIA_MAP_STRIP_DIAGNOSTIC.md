# NVIDIA map strip diagnostic

## Macierz A/B

Ta sama scena: `Video/GX020079.mp4`, 90 klatek (~3 s), 1920×1080 overlay, NVIDIA NVDEC/CUDA/NVENC.

| Test | Konfiguracja | MAP_STRIP |
|---|---|---|
| A | Direct-Region + Multi-Region Atlas + zero-copy SHM | YES |
| B | `track_map` wyłączone | NO |
| C | wymuszony istniejący fallback FULL_FRAME | NO |
| D | Direct-Region + `TELEM_ZERO_COPY_SHM=0` | YES |

Artefakt został odtworzony w finalnym pliku `debug/diag_A.mp4`. Preview nie był używany jako dowód.

## Dumpy i clear

Wymagane dumpy są w `debug/diag_dumps_A/`:

`01_map_local.png`, `02_cadence_local.png`, `03_atlas_after_clear.png`,
`04_atlas_after_map.png`, `05_atlas_before_cadence.png`,
`06_atlas_after_cadence.png`, `07_final_atlas_before_ffmpeg.png`.

Pierwszy dump, na którym pasek pojawia się poza prawidłowym cropem mapy, to `04_atlas_after_map.png`. `03_atlas_after_clear.png` ma `non-zero bytes = 0` dla całego atlasu (`1832×574×4`). Pasek nie jest więc stale odziedziczonym pikselem SHM.

## Geometria przed poprawką

Wartości dla testu A, overlay 1920×1080:

| Element | Wartość |
|---|---|
| `track_map` logical anchor | `(1690, 241)` |
| `track_map` actual/precise rendered bbox | `(1517, 68, 346, 346)`; alpha bbox `(0,0,346,346)` |
| `track_map` region bbox | `(1472,118,448,244)` |
| map source crop | `crop=448:244:376:0` |
| map destination rect | `(2944,236,896,488)` w renderze 3840×2160 |
| map region origin | `(1096,118)` |
| map packed atlas offset | `(376,0)` |
| `fit_cadence_text` logical/paste bbox | `(91,790,584,264)` |
| cadence precise alpha bbox | `(1,1,578,246)` w obrazie `584×264` |
| cadence region bbox | `(46,754,1828,326)` |
| cadence source crop | `crop=1828:326:0:248` |
| cadence destination rect | `(92,1508,3656,652)` |
| cadence region origin | `(46,506)` |
| cadence packed atlas offset | `(0,248)` |

Mapa była kwadratowa `346×346`, ale planner używał wykresowego estimate `448×244`. Dolna część mapy wychodziła poza region i nadpisywała w atlasie początek regionu cadence; FFmpeg później poprawnie cropował te nadpisane piksele jako pasek.

## Root cause

Jedna klasa błędu: **atlas packing / region bbox geometry**. Dowody:

- A i D mają pasek, więc nie jest to problem wyłącznie zero-copy.
- B i C nie mają paska, więc problem wymaga mapy w Direct-Region.
- clear ma zero non-zero bytes.
- `01_map_local.png` jest prawidłową mapą; dodatkowe piksele pojawiają się w atlasie po zapisie mapy, już w obszarze kolejnego regionu.

## Minimalny fix

W `src/ffmpeg/command_builder.py` rozdzielono mapy od wykresów w obu plannerach (`get_layout_hud_bbox` i `get_layout_hud_regions`). Mapy otrzymują kwadratowy region oparty o skonfigurowany bok plus istniejący margines; wykresy zachowują dotychczasową geometrię. Nie zmieniono `chart.py`, `chart_utils.py`, cadence/HR, FIT ani fixed timeline.

Dodano test `tests/test_nvidia_map_region_bounds.py`.

## Weryfikacja po fixie

Test A po poprawce: `debug/diag_A_fix2.mp4`.

- MAP_STRIP: **NO**
- mapa działa: TAK
- cadence działa: TAK
- HR działa: TAK
- gauge działa: TAK
- zero-copy aktywne: TAK
- Direct-Region aktywne: TAK
- Multi-Region Atlas aktywny: TAK; atlas po poprawce `1248×764`
- testy: `15 passed` (`map_region_bounds`, zero-copy SHM, multi-region)
