# RAPORT — INTEGRATION MULTI-FILE PRODUCTION CORRECTNESS

## Verdict

**PASS** dla zakresu production correctness 014/015/016.

Walidacja została wykonana na branchu `integration/intel-amd`, HEAD bazowym
`feb0482`, bez commita i bez push. Repozytorium było już znacznie zmodyfikowane
przed tym etapem; nie cofano ani nie nadpisywano zastanych zmian.

## Inputs i ownership

Użyte read-only:

- `C:\_DEV\TeleM\Video\GX010114.MP4`
- `C:\_DEV\TeleM\Video\GX010115.MP4`
- `C:\_DEV\TeleM\Video\GX010116.MP4`
- `C:\_DEV\TeleM\Video\GX010114_116.fit`

Kanoniczna lista GUI/timeline zawiera dokładnie powyższe trzy MP4 w kolejności
014, 015, 016. `C:\_DEV\TeleM\Video\output_h265.mp4` nie trafił do input listy;
został użyty wyłącznie read-only jako wadliwy artefakt audytowy.

## A. Kanoniczna długość projektu

Polityka CFR: visual stream `nb_frames / (30000/1001)`. Nie używamy dłuższego
`format.duration` jako granicy dekodowania obrazu.

| Clip | Source duration / used duration [s] | Used local | Global range [s] | Expected frames | Timestamp source / quality | Absolute range UTC |
|---|---:|---:|---:|---:|---|---|
| GX010114.MP4 | 1956.587967 | 0.000000–1956.587967 | 0.000000–1956.587967 | 58639 | `gpmf_gps9` / `exact` | 2026-08-14 09:40:11.704920–10:12:48.292887 |
| GX010115.MP4 | 592.592000 | 0.000000–592.592000 | 1956.587967–2549.179967 | 17760 | `gpmf_gps9` / `exact` | 2026-08-14 11:18:02.250270–11:27:54.842270 |
| GX010116.MP4 | 1743.641900 | 0.000000–1743.641900 | 2549.179967–4292.821867 | 52257 | `gpmf_gps9` / `exact` | 2026-08-14 11:32:09.735793–12:01:13.377693 |

Suma i jedyny kanoniczny full-project expectation:

- project/video duration: **4292.821866667 s** (`71:32.821867`),
- frame count: **128656**,
- CFR duration `128656 × 1001 / 30000`: **4292.821866667 s**,
- brak `continuous_fallback` dla któregokolwiek klipu.

## B. Audyt starego wadliwego MP4

Read-only artefakt: `C:\_DEV\TeleM\Video\output_h265.mp4`.

| Element | Wynik ffprobe |
|---|---:|
| Video duration / frames | 1956.607512 s / 58639 |
| Audio duration / frames | 4293.211000 s / 201228 |
| Container duration | 4293.211000 s |
| Video rate / time base | 30000/1001 / 1/1200000 |

Profil starego renderu potwierdza: requested 128671, decoded/native/AMF/muxed
tylko 58639, `mf_eos_events=1`. Po 014 nie powstały pakiety wideo dla 015/016,
natomiast audio concat obejmował cały projekt. Stąd player widział długi
kontener z obrazem kończącym się po 014 i prezentował freeze ostatniej klatki.

Root cause składał się z trzech części:

1. granica klipu była wyznaczana z container duration, podczas gdy MF osiągał
   rzeczywisty visual EOF wcześniej; exporter kończył całość zamiast przełączyć
   reader,
2. AMF PTS był oparty na source-local MF timestamp, który resetuje się przy
   nowym readerze,
3. audio concat nie był kontraktowo związany z tym samym frame/range planem.

## C–F. Poprawiony kontrakt outputu

- `VideoTimeline` przechowuje source frame count i tworzy integer per-clip frame
  plan; source switch nie zależy od zaokrąglenia container duration.
- Native AMF PTS jest wyliczany wyłącznie z globalnego output frame index i
  dokładnego `fpsNum/fpsDen`.
- `telem_amd_switch_source()` wymienia reader, czyści pending surface/EOS i
  zachowuje compositor/HUD/AMF.
- Zakresy używają native source seek. Ponieważ MF seek może wylądować na
  wcześniejszym keyframe, `telem_amd_discard_video_sample()` odrzuca próbki
  wcześniejsze niż docelowa granica; nie zmienia to globalnego zegara outputu.
- Audio concat korzysta z tej samej uporządkowanej listy segmentów oraz
  `inpoint/outpoint`; finalizacja ogranicza audio do project duration.
- Profil zawiera requested/decoded/submitted/encoded per segment i total muxed.

## M/N. Realny test zakresów i dłuższa akceptacja obu switchy

Production `VideoTimeline.subset()`:

1. ostatnie 10 s 014,
2. pierwsze 10 s 015,
3. ostatnie 10 s 015,
4. pierwsze 10 s 016.

Artefakty:

- `scratch/amd_multifile_real_ranges_40s.mp4`
- `scratch/amd_multifile_real_ranges_40s.mp4.amd_profile.json`
- `scratch/amd_multifile_real_ranges_40s_contact.png`

Frame accounting:

| Segment | Source start MF PTS [s] | Output start PTS [s] | Requested | Decoded | Submitted | Encoded | Seek-discarded |
|---|---:|---:|---:|---:|---:|---:|---:|
| 014 end | 1946.5779666 | 0.0000 | 300 | 300 | 300 | 300 | 19 |
| 015 start | 0.0000 | 10.0100 | 300 | 300 | 300 | 300 | 0 |
| 015 end | 582.5820 | 20.0200 | 300 | 300 | 300 | 300 | 0 |
| 016 start | 0.0000 | 30.0300 | 300 | 300 | 300 | 300 | 0 |
| **TOTAL** | — | — | **1200** | **1200** | **1200** | **1200** | **19** |

Native processed, VP processed, AMF submitted, AMF output i muxed: **1200**.

Packet boundary audit:

| Boundary | Previous PTS | Next PTS | Delta |
|---|---:|---:|---:|
| frame 300 | 9.976733 | 10.010100 | 0.033367 s |
| frame 600 | 19.986833 | 20.020200 | 0.033367 s |
| frame 900 | 29.996933 | 30.030300 | 0.033367 s |

PTS i DTS są monotoniczne; nie resetują się przy switchu i nie mają dziur.
Kontakt sheet pokazuje cztery różne sceny, oba realne przejścia 014→015 i
015→016, pojedynczy HUD oraz brak freeze/duplikacji warstw.

Finalny ffprobe:

- video: 1200 frames, 40.040400 s,
- audio: 1862 AAC frames, 40.043000 s,
- container: 40.043000 s,
- A/V difference: **2.600 ms**,
- start_time obu streamów: 0,
- `ffmpeg -f null` zdekodował cały video bez błędu.

## G. Player consistency

- ffprobe: kompletne 1200 video frames i spójne stream durations,
- MPC-HC: playback od 28 s przez 015→016 do EOF, proces odpowiadał i zamknął
  się po `/close`, brak freeze,
- widoczny Qt/MPV: oba source boundary przeszły podczas aktywnego PLAY,
- Avidemux: **NOT TESTED — program nie jest zainstalowany**.

## H/I. Project/activity-global HUD ranges

Root cause: preview/render budowały cache z lokalnie dostępnego GPMF lub z
pierwszego znalezionego wskaźnika, zamiast z jawnie wybranego źródła aktywnego
wskaźnika i pełnego wspólnego FIT.

Wspólny `build_activity_range_cache()`:

- wybiera aktywny indicator i dokładnie jego source,
- nie pożycza wartości z innego źródła, gdy wybrane źródło jest puste,
- dla FIT używa pełnego activity dataset,
- jest współdzielony przez preview i RenderTab,
- nie jest czyszczony przez source switch.

Realny pełny FIT:

- speed: 4293 próbek, max **45.684 km/h**,
- cumulative distance: 4299 próbek, max **24231.54 m**,
- altitude: 4299 próbek,
- cadence: 4273 próbki,
- heart rate: 4299 próbek.

`speed_text` ma activity-global auto-scale w production preset; wynikowa skala
to **0–50 km/h**, widoczna identycznie we wszystkich czterech segmentach.
`fit_distance_text` ma auto-scale i widoczny globalny max **24.2 km**.
Alt w bieżącym layoucie ma jawne `auto_scale=false`, HR/cad charts mają jawne
manualne zakresy, a battery indicators są wyłączone — ich semantyki nie
zmieniano. Timeline subset zachowuje oryginalny activity elapsed, dzięki czemu
średnia prędkość nie restartuje czasu przy cięciu z już skumulowanym dystansem.

## J/K. Realny Qt preview i atomic state

Widoczny production `MainWindow` + MPV został załadowany z realnych trzech MP4
i wspólnego FIT. Wyniki seek:

| Przejście | Clip/source | Global/local [s] | Distance [m] | Speed [km/h] | HR / cadence | Generations | HUD layers |
|---|---|---:|---:|---:|---:|---|---:|
| 014 end | 0 / GX010114 | 1955.587967 / 1955.587967 | 12075.53 | 2.5111 | 96 / 0 | source 0, HUD 1 | 1 |
| 015 start | 1 / GX010115 | 1957.587967 / 1.0 | 12076.64 | 1.5641 | 77 / 0 | source 1, HUD 2 | 1 |
| 016 start | 2 / GX010116 | 2550.179967 / 1.0 | 15018.83 | 0.7726 | 88 / 0 | source 2, HUD 3 | 1 |
| back 015 | 1 / GX010115 | 1957.587967 / 1.0 | 12076.64 | 1.5641 | 77 / 0 | source 3, HUD 4 | 1 |
| back 014 | 0 / GX010114 | 1955.587967 / 1955.587967 | 12075.53 | 2.5111 | 96 / 0 | source 4, HUD 5 | 1 |

Dla każdego stanu `absolute_time == hud_target_dt == map_target_dt ==
chart_target_dt`, a decoded source jest zgodny z clip source. Aktywny PLAY
przeszedł 014→015 i 015→016. Dodatkowy realny QMedia test także przeszedł oba
automatyczne switche i pięć seeków.

Source switch atomowo zwiększa source/visual generation, opróżnia starą kolejkę
compositingu, czyści retained source frame i akceptuje QMedia frame dopiero po
zgodności generation oraz source path. Stary callback nie może nadpisać nowego
preview. MPV tick wyznacza globalny czas z aktualnego readera i dopiero po EOF
przełącza logiczny klip; eliminuje wcześniejsze przedwczesne przejście i freeze.

## L. Global frame status

Frame total pochodzi z `VideoTimeline.output_frame_count()`, więc GUI/render
używa project-global total **128656**, nie 58639 pierwszego pliku. Jedyna linia
statusu niesie global frame/percent/FPS/elapsed/ETA/phase. Legacy tekst
`Render:` został usunięty; konsolowe podsumowanie fazy nazywa się
`Video encode:`.

## Changed files tego zadania

Najważniejsze pliki production correctness (część z nich zawiera także
wcześniejsze, zastane zmiany):

- `def_layout.json`
- `native/d3d11_amf_pipeline/src/telem_amd_native.cpp`
- `src/multifile.py`
- `src/ffmpeg/amd_native_exporter.py`
- `src/ffmpeg/streaming.py`
- `src/ffmpeg/frame_renderer.py`
- `src/telemetry_resolver.py`
- `src/telemetry_precompute.py`
- `src/indicators/frame_data.py`
- `src/gui/qt/_mixins/playback_mixin.py`
- `src/gui/qt/_mixins/preview_mixin.py`
- `src/gui/qt/tabs/render_tab.py`
- `tests/test_multifile_timeline.py`
- `tests/test_activity_range_cache.py`
- `scratch/run_amd_multifile_absolute_sync_smoke.py`
- `scratch/real_qt_multifile_mpv_visual.py`
- `scratch/real_qt_multifile_playback_boundary.py`

Zbudowano target `telem_amd_native` do
`native/d3d11_amf_pipeline/bin/telem_amd_native.dll`. Nie zmieniano intencjonalnie
Intel/QSV ani NVIDIA/CUDA/NVENC w tym zadaniu.

## Git diff --stat

Cały zastany i bieżący dirty worktree, a nie wyłącznie ten etap:

```text
39 files changed, 1863 insertions(+), 922 deletions(-)
```

Raport i nieśledzone testowe artefakty nie są ujęte w powyższym tracked stat.

## Tests

- focused multifile/timeline/preview/range/render/cut/chart: **111 passed**,
- rozszerzony focused run: **123 passed, 1 unrelated fail**
  (`distance ruler marker x=8` vs historyczny test oczekujący x≈10),
- pełny repo pytest: **1136 passed, 37 skipped, 60 failed**.

Pełne 60 FAIL nie pochodzi z tej poprawki i obejmuje zastany dirty worktree,
brakujące golden/FIT fixtures, usunięty wcześniej `lean_indicator`, historyczne
testy AMD EXACT, ruler/pixel oraz Intel rotation. Nie naprawiano ich, ponieważ
byłoby to rozszerzeniem scope i naruszałoby backend isolation.

## Final summary

- wszystkie 3 źródła są obecne w realnym output testowym: **PASS**,
- kanoniczna długość/frame plan: **PASS**,
- brak freeze i poprawny source switch: **PASS**,
- globalny ciągły PTS/DTS: **PASS**,
- audio/ranges/mux duration: **PASS**,
- visible Qt seek i PLAY przez oba boundary: **PASS**,
- pojedynczy HUD i spójny canonical state: **PASS**,
- activity-global FIT ranges i speed scale 50 km/h: **PASS**,
- Avidemux: **NOT TESTED (not installed)**,
- task verdict: **PASS**.
