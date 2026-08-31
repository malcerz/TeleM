# MULTI-FILE absolute sync + playback przez granice klipów

## Zakres

Naprawa poprawności projektu bez zmian AMD compositor, AMF, D3D11VA, layoutu ani optymalizacji.

Inputy tylko do odczytu:

- `C:\_DEV\TeleM\Video\GX010114.MP4`
- `C:\_DEV\TeleM\Video\GX010115.MP4`
- `C:\_DEV\TeleM\Video\GX010116.MP4`
- `C:\_DEV\TeleM\Video\GX010114_116.fit`

## Fakty źródłowe GPMF

Tabela pochodzi z bezpośredniego parsowania `gpmd/GPS9` każdego MP4, bez `VideoTimeline`.

| Clip | source | pierwszy reliable GPMF UTC | local pierwszej próbki | ostatni reliable GPMF UTC | local ostatniej próbki | duration |
|---|---|---:|---:|---:|---:|---:|
| 014 | `gpmf_gps9` | 2026-08-14 09:40:12.000 | 0.295080 | 2026-08-14 10:12:48.300 | 1956.641472 | 1956.955 s |
| 015 | `gpmf_gps9` | 2026-08-14 11:18:03.000 | 0.749730 | 2026-08-14 11:27:54.799 | 592.581824 | 592.597 s |
| 016 | `gpmf_gps9` | 2026-08-14 11:32:10.000 | 0.264207 | 2026-08-14 12:01:13.300 | 1743.608320 | 1743.742 s |

`VideoTimeline` normalizuje start do local=0 (`first_abs - first_local`): `09:40:11.704920`, `11:18:02.250270`, `11:32:09.735793` UTC. Wszystkie trzy mają `source=gpmf_gps9`, `quality=exact`, `reliable=True`; brak `continuous_fallback`.

FIT obejmuje `2026-08-14 09:40:10`–`12:01:13` UTC, dystans `0.00`–`24231.54 m`. Między 014/015 jest około 65 min przerwy, a między 015/016 około 4 min 15 s.

## Root cause i model czasu

`build_timeline_from_paths()` dla pierwszego pliku tworzył `project_start_anchor`, gdy otrzymał `base_dt`, więc nie parsował własnego GPMF 014. Następnie `_rebuild()` bezwarunkowo nadpisywał start clip 0 przez anchor. Anchor około `11:18:03` dał 014 i 015 prawie ten sam timestamp; dlatego 014 zaczynał od FIT około 12.1 km.

Kolejność po naprawie:

1. reliable clip-local GPMF;
2. inne reliable metadata;
3. `project_start_anchor` wyłącznie jako fallback clip 0;
4. `continuous_fallback` na końcu.

Model: `global project time -> active clip + local time -> clip absolute start + local time -> FIT/GPMF`. Globalna oś usuwa przerwy wideo, ale telemetryczna oś absolutna ich nie usuwa.

## Dziewięć punktów kontrolnych FIT

Koniec to ostatnia dekodowalna klatka (`duration - 1/fps`); dokładna granica należy do następnego clipu. `—` = brak najbliższej próbki.

| clip/punkt | global s | local s | absolute UTC | distance m | HR | cadence | speed km/h | GPS lat, lon |
|---|---:|---:|---|---:|---:|---:|---:|---|
| 014 start | 0.000 | 0.000 | 09:40:11.704920 | 0.00 | 73 | — | — | — |
| 014 middle | 978.477 | 978.477 | 09:56:30.182420 | 6156.93 | 102 | 67 | 25.830 | 54.362309, 18.641993 |
| 014 end | 1956.922 | 1956.922 | 10:12:48.626553 | 12075.53 | 95 | 0 | 0.000 | 54.397388, 18.578868 |
| 015 start | 1956.955 | 0.000 | 11:18:02.250270 | 12075.53 | 78 | — | 2.149 | 54.397434, 18.578719 |
| 015 middle | 2253.254 | 296.299 | 11:22:58.548936 | 13514.23 | 97 | 63 | 21.866 | 54.387462, 18.591143 |
| 015 end | 2549.519 | 592.564 | 11:27:54.814236 | 15015.19 | 91 | 0 | 0.000 | 54.378845, 18.606021 |
| 016 start | 2549.552 | 0.000 | 11:32:09.735793 | 15018.83 | 88 | 0 | 0.000 | 54.378806, 18.606045 |
| 016 middle | 3421.423 | 871.871 | 11:46:41.606793 | 20059.99 | 110 | 63 | 21.096 | 54.350564, 18.631315 |
| 016 end | 4293.261 | 1743.709 | 12:01:13.444426 | 24231.54 | 101 | 0 | 9.371 | 54.331224, 18.601701 |

Początek 014 jest teraz `0.00 m`, nie około `12.1 km`.

## Playback przez EOF

Root cause był niezależny: `setSource()` zatrzymuje decoder, lecz kod wywoływał `play()` tylko przy `_playing=False`. MPV po zmianie źródła zostawał zapauzowany. QMedia wykonujący `setSource()` synchronicznie w `EndOfMedia` mógł ponadto kolidować z zamykaniem poprzedniego HEVC demuxera.

Naprawa:

- QMedia wznawia po pending local seek, gdy `_playing=True`;
- EOF source handoff jest odroczony o jeden obrót event loop i ma chronione wznowienie;
- MPV odpauzowuje nowe źródło;
- seek i EOF używają wspólnego `global_to_clip()`.

Realny `QMediaPlayer` w produkcyjnym `AppController` (oryginalne pliki, `QT_QPA_PLATFORM=offscreen`) przeszedł:

| test | wynik |
|---|---|
| 014 EOF -> 015 | PASS: global slider `1956.955`, `_playing=True`, nowe źródło local `0.085 s`, `PlayingState` |
| 015 EOF -> 016 | PASS: global slider `2549.552333`, `_playing=True`, nowe źródło local `0.085 s`, `PlayingState` |

To był realny EOF: odtwarzacz otworzył MP4, zgłosił EOF, załadował następny MP4 i odtworzył jego pierwsze klatki.

## AMD native final render parity

Krótki native smoke ujawnił dodatkowy bypass: AMD precompute nie otrzymywał `video_timeline`, a `c_dt` był liczony jako `base_dt + global`. Wideo przełączało źródło, lecz HUD pozostawał przy 014. Cache oraz local map/chart lookup dostały teraz `video_timeline.frame_to_absolute()`.

Finalny smoke `scratch/amd_multifile_absolute_sync_smoke_fixed.mp4`:

- 32 klatki HEVC/AMF, 1.068 s, trzy okna po 0.35 s i dwa native source switch;
- profil: D3D11VA + AMF, `mf_format_changes=3`, `decoded_frames=32`, `native_processed=32`, `muxed_frames=32`;
- wizualne klatki startów 014/015/016 mają pojedynczy HUD i prawidłowe local-display telemetry: `11:40:11`, `13:18:02 / 12.1 km / 78 bpm`, `13:32:09 / 15.0 km / 88 bpm` (UTC+2).

Mapa i wykresy dostają ten sam `target_dt` z cache. Test render timeline potwierdza także brak próbek telemetry w absolutnych lukach. Smoke nie jest benchmarkiem ani pełnym eksportem 4293 s.

## Regresje

- `67 passed`: timeline, preview seek/source switch/EOF, final-render timeline/precompute, Reset Layout x2, HUD lifecycle i aware/naive GUI datetime contract.
- Reset Layout x2: logika odtwarza jeden pełny layout za każdym razem i zachowuje obiekt telemetryczny/cache danych.
- Single file: regresja pojedynczego clipu przechodzi; reliable GPMF ma pierwszeństwo także dla clip 0.
- Input list: canonicalizacja zostawia wyłącznie wskazane `GX010114`, `GX010115`, `GX010116`; brak `output_h265.mp4`.
- `git diff --check`: PASS; komunikaty CRLF nie są błędami diff.

## Zmienione pliki w tym zadaniu

- `src/multifile.py`
- `src/gui/qt/_mixins/playback_mixin.py`
- `src/gui/qt/_mixins/preview_mixin.py`
- `src/ffmpeg/amd_native_exporter.py`
- `tests/test_multifile_timeline.py`
- `tests/test_multifile_etap4a_preview.py`
- `tests/test_multifile_hud_lifecycle.py`
- diagnostyczne skrypty `scratch/audit_multifile_*`, `scratch/real_qt_multifile_playback_boundary.py`, `scratch/run_amd_multifile_absolute_sync_smoke.py`

## Git diff --stat

Worktree był brudny przed zadaniem. Aktualny pełny `git diff --stat` to `38 files changed, 1253 insertions(+), 796 deletions(-)` i zawiera niezależne wcześniejsze zmiany użytkownika/integracji; nie jest rozmiarem wyłącznie tej naprawy.

## Verdict

**PARTIAL** — krytyczne absolute sync, realny QMedia playback przez oba EOF i krótki AMD native source-switch/render z widocznym HUD przeszły. Nie wykonano pełnej wielominutowej sesji w widocznym oknie GUI ani pełnego 4293-s final exportu, więc całości nie oznaczono jako PASS.
