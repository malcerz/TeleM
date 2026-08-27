# RAPORT INTEL ETAP 5B — QSV final-frame tail-loss: root cause + exact frame accounting + conditional fix (OX)

Data: 2026-08-26 · Tryb: AUDIT → REPRODUCTION → FRAME ACCOUNTING → ROOT CAUSE → CONDITIONAL IMPLEMENTATION → REAL RUNTIME VALIDATION
Cel: ustalić, czy klatki z ETAPU 5A (210 submitted → 193 output) są rzeczywiście gubione, gdzie, i czy można to bezpiecznie naprawić.

---

## State pinning

- Branch: `intel-render` · HEAD bez commitów; snapshot: `scratch/intel_etap5b/state_T0.json` (SHA-256 `streaming.py`, `command_builder.py`, `test_video_helpers.py`) i `state_Tfinal.json`.
- Working tree NIE był resetowany/stashowany.

## Reproduction

Canonical multi-file (2× canonical_sdr_720p, granica klipu w środku), N=210, produkcyjne wejście `stream_overlay_to_ffmpeg`, naturalne EOF, bez cancel.

Przed fixem (kilka powtórzeń):

| metryka | wartość |
|---|---|
| frames_requested | 210 |
| writer writes (`ffmpeg_write n=`) | 189–201 (zmienny) |
| decoded output | 188–201 |
| output duration | ~6.3–6.7 s zamiast 7.0 s |

Strata ZMIENNA między runami ⇒ race/lifecycle, nie deterministyczny bug muxera.

## Exact expected frame count

`total_overlay_frames = ceil(duration_s × generation_fps)` = **210**. Single-file control: źródło ma 180 f ⇒ dokładnie 180.

## Output frame-count methodology

Potrójna weryfikacja (§24): `ffprobe -count_frames` + pełny decode `-f null -` (0 błędów) + `nb_frames`. Zgodne. `-progress pipe:1` kończy `progress=end`.

## TeleM frame accounting

PipelineAuditRecorder (env-gated, production path):

| stage | frames |
|---|---|
| scheduled/submitted | 210/210 |
| reorder ordered_output | 210/210 |
| writer queue_put_finished | 210/210 (także index 209) |
| writer→stdin writes | 189–201 ❌ |

Producer dostarcza 100%; strata PO queue_put, PRZED/PODCZAS stdin write.

## Writer lifecycle

Normalne EOF: producer finish → `pipe_done.set()` → sentinel `None` → `writer_t.join(timeout=3.0)` → `stdin.close()` → wait.

**BUG #1 (primary):** `_pipe_writer_thread` traktował `done_event` jako „porzuć backlog" (`get_nowait()` drain + release BEZ zapisu). Producer ustawia done natychmiast po ostatnim put ⇒ discard 9–21 klatek.
Unit proof przed fixem: kontrola sentinel = 5/5 zapisanych; done+backlog = **0/5**.

**BUG #1b (secondary):** `join(3.0)` + `stdin.close()` gdy writer jeszcze pisał (write do 663 ms przy backpressure) ⇒ BrokenPipe. A/B: join bez limitu poprawia kilka klatek, ale nie naprawia (#1 dominuje).

## Reorder-buffer lifecycle

Audyt per-frame: 210/210 z `ordered_output_ms` + `queue_put_finished_ms`. Pełny final drain działa — reorder NIE jest źródłem straty.

## FFmpeg progress

Po fixie #1: writer n=210/210, decoded=209 ⇒ pozostała 1 klatka ginie WEWNĄTRZ FFmpeg (→ FPS/PTS). Final frame zgodny z decode.

## Single-file control

Single 180 f źródła: **180/180**, zero straty (ta sama ścieżka writera) — wyklucza „muxer zawsze gubi ogon".

## Multi-file control

Multi 210 f: 188–201 przed fixem; **210/210 po fixach**.

## HUD/no-HUD control

Statyczny PoC §10: 210 f testsrc2 → hevc_qsv bez HUD = **210** ✓ (enkoder+muxer czyste).

## Audio/no-audio control

Produkcja `-map 2:a? -c:a copy`; PoC bez audio identyczne county — audio nie wpływa (brak globalnego `-shortest`).

## overlay shortest experiment

shortest=1 z równymi inputami 210 f = **210** ✓. Usunięcie `shortest=1` nieuzasadnione.

## FPS/PTS analysis

Base tikuje co **30000/1001** (33.367 ms); HUD rawvideo deklarowane float (`str(29.97003…)` / `30.0`) = siatka 33.333 ms ⇒ ostatnia klatka pada między tickami base przy shortest EOF ⇒ dokładnie −1 klatka.

Statyczny PoC produkcyjnego grafu (plik raw HUD 210 f):

| wariant | wynik |
|---|---|
| `-r 30.0` + shortest=1 (produkcja) | **209** ❌ |
| `-r 30000/1001` + shortest=1 | **210** ✓ |
| `-r 30.0` + shortest=0 + `-t 7` | 210 ✓ |

## Natural EOF vs graceful-stop experiment

Log normalnego renderu pokazuje `[RenderCancel] … stdin_closed / exited rc=0` NA KOŃCU NORMALNEGO RENDERU (nazwa myląca; semantyka stdin-close + bounded fallback). Nie jest przyczyną straty; realny problem: `stdin.close()` przed końcem writera (BUG #1b).


## Encoder flush analysis

hevc_qsv async_depth=4, look_ahead=0. Po dostarczeniu 210/210 i naturalnym EOF enkoder oddaje 210/210 (statyczny POC A) => flush kompletny; encoder delay nie gubi klatek.

## Tail identification

Brakujace klatki WYLACZNIE ogonowe (~indeksy 194-209), nigdy przy granicy klipu. Po fixie: 0.

## Root cause

PRIMARY:
TELEM_WRITER_DRAIN - writer discardowal backlog po done_event w normalnym EOF (+ wtorne join(3.0) -> stdin.close() race = BrokenPipe).

SECONDARY:
PTS/FPS_MISMATCH - float deklaracja -r HUD rawvideo vs racjonalna siatka 30000/1001 base => overlay shortest=1 ucina dokladnie ostatnia klatke.

Wylaczone dowodowo: CONCAT_TIMELINE, QSV_ENCODER_FLUSH, MUXER_DURATION, OVERLAY_SHORTEST (samo w sobie), AUDIO, FRAME_COUNT_MEASUREMENT_ERROR, FFMPEG_INPUT_EOF.

## Production fix

IMPLEMENTED:

1. src/ffmpeg/streaming.py
   - _pipe_writer_thread(..., discard_pending): nowy kontrakt EOF - done_event = koniec doplywu; writer zapisuje WSZYSTKO zakolejkowane (sentinel FIFO lub Empty+done). Discard TYLKO przy jawnym discard_pending.
   - Cancel/error path ustawia writer_discard_pending (stare cancel-semantics zachowane).
   - Finalize: jeden sentinel FIFO + done; join(timeout=60.0) z ostrzezeniem gdy alive (safety-net, nie mechanizm naprawy).
2. src/ffmpeg/command_builder.py
   - _fps_rational_arg(): HUD rawvideo -r racjonalnie (Fraction.limit_denominator(1001)); bez zmian timestampow timeline ani liczby generowanych ramek.

AMD native exporter (wlasny graf) NIETYKANY; NVIDIA/CPU dziedzicza poprawe przez wspolny builder/writer (statycznie; runtime tylko Intel).

## Before behavior

Multi 210 f: output 188-201 klatek (~0.3-0.7 s utraty ogona), zmiennie miedzy runami.

## After behavior

| scenariusz | requested | decoded | metadata |
|---|---|---|---|
| R1 SDR native single | 180 | 180 | bt709/yuv420p |
| R2 HDR CPU_REF GX020079 300f | 300 | 300 | HLG/bt2020/10bit kompletne |
| R3 MULTI 360f (boundary) | 360 | 360 | bt709 |
| R4 LONG single 600f HDR | 600 | 600 | HLG kompletne |
| R5 CANCEL mid-flight | - | thread exit OK, zombie=0 OK | partial MP4 poza zakresem |

Pelny decode null po kazdym: 0 bledow strumienia.

## Exact frame count after fix

single-file: PASS (180/180) - multi-file: PASS (360/360 oraz 210/210) - tail loss = 0.

## Long-run validation

R4: 600 f single GX020079 (20.007 s): 600/600 OK (par. 35). Material multi >600 f niedostepny w repo (canonical 2x6 s = max 360 f).

## SDR regression

R1 GPU-resident domyslnie, REGION path, no hang, no frozen tail, 180/180 OK.

## HDR regression

R2+R4: count exact; color_transfer=arib-std-b67 / bt2020 / yuv420p10le kompletne OK.

## Cancel regression

R5 cancel ~3 s: thread exits, rc clean, zombie=0; unit test potwierdza discard-on-cancel OK.

## NVIDIA isolation

Automatyczny scan logow/komend: zero nvenc/cuda/cuvid/overlay_cuda. Builder wspolny - NVIDIA dziedziczy poprawki statycznie; runtime NVIDIA niedostepny na tej maszynie.

## AMD preservation

amd_native_exporter.py nie uzywa _build_stream_ffmpeg_cmd ani _pipe_writer_thread - nietkniety. AMD path preserved statically; runtime validation was not possible on this machine.

## Tests

- tests/test_etap5h_writer_queue.py (+5): backlog-zapis przy done (regresja BUG#1), FIFO sentinel-vs-final-frame, discard only on explicit cancel, _fps_rational_arg (30000/1001, 60000/1001, 24000/1001, int), command-construction -r 30000/1001.
- tests/test_render_cancel_process_lifecycle.py: stary test kodowal BUG#1 jako kontrakt - zaktualizowany (done=>write; explicit cancel=>discard).

Focused suite (7 plikow, par. 41 + nowe): 74 passed.

## Full-suite comparison

Baseline 5A: 1095 passed / 22 skipped / 30 failed / 5 errors.
Teraz: 1100 passed / 22 skipped / 30 failed / 5 errors = baseline + dokladnie 5 nowych testow; failures/errors identyczne (pre-existing). Nowa regresja: BRAK.

## Performance sanity

A/B dzis (HDR GX020079 300 f x3):
- BEFORE (kopia src z cofnietymi fixami; unit-proof potwierdzil stary bug): median 17.68 FPS (14.94-18.30), decoded 293-294/300
- AFTER: seria1 16.30 / seria2 median 17.42 FPS (17.16-17.98), decoded 300/300

Delta median -1.5% (szum maszyn +/-10%). Zysk BEFORE = porzucone klatki + krotszy drain, nie throughput. Correctness > performance.

## Changed files

- src/ffmpeg/streaming.py - writer EOF contract + finalize drain order + cancel/error discard flag
- src/ffmpeg/command_builder.py - _fps_rational_arg() + racjonalne -r HUD input
- tests/test_etap5h_writer_queue.py, tests/test_render_cancel_process_lifecycle.py
- scratch/intel_etap5b/** (logi, PoC, audit.json, state_T0/Tfinal)

(src/benchmark.py, tests/test_video_helpers.py, def_layout.json - zmiany sprzed 5B per raport 5A; def_layout.json = user change MANUAL REVIEW.)

## Known remaining limitations

- AMD native exporter ma analogiczny wzorzec we wlasnym grafie - wymaga dedykowanego zadania z runtime AMD.
- Partial MP4 on cancel moze byc non-playable (poza zakresem, jak w 5A).
- target_fps musi odpowiadac realnej czestotliwosci zrodla (GUI robi to przez parse_fps); swiadome niedopasowanie da krotszy output o brzegowa klatke - wtedy to parametryzacja, nie tail-loss.

## Recommendation

JEDEN nastepny krok: commit zestawu 5A+5B wg Recommended-commit-set z raportu 5A + pliki 5B (streaming.py, command_builder.py, oba testy, raporty), po czym ETAP 6: native multi-file eligibility LUB jawny RC/GUI quality control (decyzja uzytkownika).

## FINAL VERDICT

INTEL ETAP 5B: PASS - TAIL LOSS FIXED
