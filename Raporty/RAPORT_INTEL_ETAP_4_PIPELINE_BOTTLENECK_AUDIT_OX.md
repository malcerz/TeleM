# TeleM — INTEL ETAP 4: AUDYT BOTTLENECKÓW PIPELINE'U (OX)

Data: 2026-08-25. Tryb: AUDIT ONLY. Gałąź: `intel-render`, HEAD `e019a6b45278f09f718f528642767f505ea87934`.

## Status ważności audytu

**PINNED_STATE_AUDIT — ważny dla stanu przypiętego hashami (T0), bez finalnych wniosków z okresu sprzed przypięcia.**

W trakcie wstępnej analizy working tree był aktywnie modyfikowany przez równoległą sesję (`streaming.py` rósł +14 → +75 → +108 linii vs HEAD; `def_layout.json`, nowe raporty 3C/HOTFIX pojawiały się na żywo). Na sygnał STOP analiza została przerwana, wnioski sprzed przypięcia potraktowane jako nieostateczne, a rekonstrukcja pipeline'u wykonana **od nowa** na jednym stanie roboczym zamkniętym hashami SHA-256.

Okno stabilności przed ponownym audytem: T0 → T1 = ≥75 s bez zmian (ostatnie obce zapisy 09:24–09:29, T1 o 09:37:02).

### Wynik kontroli zamknięcia (T2)

Po zakończeniu rekonstrukcji ponownie policzono SHA-256 (`scratch/intel_etap4_audit_T2.json`): **0/9 plików zmienionych** — wszystkie audytowane pliki źródłowe mają hashe identyczne z T0/T1. Różnica `git status` względem T0 ogranicza się wyłącznie do nowych plików untracked: własnych artefaktów tego audytu (raport OX + JSON-e T0/T1/T2) oraz jednego obcego dokumentu `Raporty/RAPORT_INTEL_HOTFIX_2_QSV_HWDOWNLOAD_SYNC.md` (dokument bez wpływu na kod; jego treść odpowiada 1:1 zmianom już obecnym w stanie przypiętym — software-decode p010 bez hwdownload — i została uwzględniona w rekonstrukcji). Żaden plik objęty hashami nie uległ zmianie podczas audytu → status WAŻNY, Final verdict obowiązuje.

### Snapshot stanu audytowanego (T0)

`git status --short`:

```text
 M def_layout.json
 M src/ffmpeg/command_builder.py
 M src/ffmpeg/streaming.py
 M tests/test_video_helpers.py
?? Raporty/RAPORT_INTEL_ETAP_3B_AB_PARITY_PERF.md
?? Raporty/RAPORT_INTEL_ETAP_3C_HUD_REGION.md
?? Raporty/RAPORT_INTEL_HOTFIX_10BIT_CPU_REFERENCE.md
?? scratch/intel_etap3b/
```

`git diff --stat` vs HEAD:

```text
 def_layout.json               |   2 +-
 src/ffmpeg/command_builder.py |  33 ++++++++++++-  (w chwili T0)
 src/ffmpeg/streaming.py       | 108 ++++++++++++++++--..--  (+108 w chwili T0; wcześniej 14/75)
 tests/test_video_helpers.py   |  26 ++++++++++-
```

SHA-256 plików poddanych audytowi (T0 == T1):

| Plik | SHA-256 (pierwsze 16) |
|---|---|
| src/ffmpeg/streaming.py | `5244B67B05F6F010` |
| src/ffmpeg/command_builder.py | `8209D60DADC24F33` |
| src/ffmpeg/shared_memory.py | `E981384C50A062BF` |
| src/ffmpeg/frame_renderer.py | `1B4A845B38CE1B3B` |
| src/ffmpeg/shm_image.py | `88DE70DAD7D9F6E1` |
| src/ffmpeg/intel_backend.py | `32F334B520DD364A` |
| src/indicators/compositor.py | `32E16C1515F4D1EC` |
| tests/test_video_helpers.py | `57749CE0E6092ECE` |
| def_layout.json | `926E8B38AE01514B` |

Pełne hashe: `scratch/intel_etap4_audit_T0.json`, `scratch/intel_etap4_audit_T1.json`. Kontrola zamknięcia: sekcja „Tested / State closure”.

## Executive summary

1. **Architektura jest dwuścieżkowa i asymetryczna.** NATIVE (D3D11/QSV): wideo GPU-resident end-to-end (`scale_qsv` → `overlay_qsv` → `hevc_qsv`), HUD renderowany na CPU i uploadowany regionowo. CPU_REFERENCE: wideo wykonuje pełny round-trip GPU→CPU→GPU (`hwdownload` → filtry SW → niejawny upload przed enkoderem QSV), a HUD jest przesyłany **zawsze pełną klatką**.
2. **Po ETAP 3C (REGION dla native) największy nierozwiązany koszt transportowy leży w CPU_REFERENCE**, nie w native: (a) round-trip wideo przez PCIe, (b) pełno-klatkowy RGBA HUD (7,91 MiB/f @FHD, 31,64 MiB/f @4K) przez pipe + 2 kopie user-space + konwersja `rgba→yuva420p` w FFmpeg.
3. **HUD nie jest bottleneckiem sam z siebie** — jest nim *objetność transportu HUD proporcjonalna do pola canvasu*, nie liczba wskaźników. Dowód pośredni: ETAP 3C uzyskał 1,09–1,30× wall-speedup redukcją transportu przy minimalnym HUD; koszt generacji HUD (~14 ms/f dla bogatego layoutu wg historycznego pomiaru AMD ETAP5E) jest rozproszony na N−1 procesów i zwykle nie ogranicza FPS agregatowo.
4. **Synchronizacja jest zaprojektowana poprawnie** (SHM + memoryview zero-copy IPC, writer-thread izoluje backpressure pipe, producer pool pracuje równolegle). Nie stwierdzono antywzorca „CPU work → WAIT → GPU work → WAIT”.
5. **Najbardziej opłacalny następny krok:** rozszerzenie istniejącego mechanizmu REGION (ETAP 3C) na ścieżkę Intel CPU_REFERENCE + instrumentacja per-stage generacji HUD przed jakąkolwiek optymalizacją rendererów. Szczegóły w sekcji końcowej.
## Actual CPU_REFERENCE pipeline (krok po kroku, stan przypięty)

Warunki wejścia: `encoder="intel"`, `intel_gpu_resident=False` (multi-file / rotacja / cięcia / HDR-10bit / brak probe SDR → fallback), `INTEL_FORCE`.

1. **Decode**: `-hwaccel qsv -hwaccel_output_format qsv` + `-init_hw_device qsv=intel_qsv,...` + `-hwaccel_device intel_qsv` + `-qsv_device <idx>` (`intel_ffmpeg_device_args`, `intel_backend.py`). Klatki po dekodowaniu: **QSV/D3D11 surfaces w pamięci GPU**. Wyjątek (nowość HOTFIX): źródło 10-bit/HDR → `intel_cpu_software_decode=True`, `hwaccel=None` — dekodowanie **software**, klatki od razu w RAM (brak `hwdownload`).
2. **Granica GPU→CPU**: gałąź `elif encoder == "intel":` w `command_builder.py`: `[0:v]hwdownload,format=nv12|p010le[,scale=lanczos][,rotacje]`. To pierwszy i wymuszony transfer + sync.
3. **Skalowanie**: `scale=lanczos` na CPU (tylko gdy `target_res`; przy `source` brak).
4. **Telemetria**: precompute (`build_telemetry_cache`) jednorazowo ~3,8 ms dla 180 f (log `cpu_file.log`); lookup per-frame z cache — pomijalne.
5. **HUD**: render w procesach roboczych (ProcessPool, `render_frame_shm_job`) na canvasie `stream_w×stream_h` RGBA; dla CPU_REFERENCE `stream_w/h == overlay_w/h` (**zawsze pełna klatka** — bramka REGION wymaga `intel_gpu_resident`, `streaming.py:838`).
6. **IPC HUD**: worker robi `np.asarray(img)` (widok) + `np.copyto` do slotu SHM (1 memcpy pełnej klatki) → kolejka → writer-thread pisze memoryview prosto do stdin (druga kopia kernelowa pipe). Zero-copy SHM istnieje, ale mapped-PIL target jest używany wyłącznie przez NVIDIA direct-region (`shared_memory.py:153-178`).
7. **Overlay w FFmpeg**: `[1:v]format=rgba[ov]; [base][ov]overlay=x:y` — overlay konwertuje rgba→yuva420p (swscale, pełny canvas) i blenduje na NV12/P010.
8. **Granica CPU→GPU**: hevc_qsv otrzymuje software NV12/P010 → FFmpeg wstawia niejawny `hwupload` przed enkoderem. Drugi transfer PCIe.
9. **Encode**: `hevc_qsv -preset veryfast -global_quality 24 -look_ahead 0 -async_depth 4 -pix_fmt nv12|p010le`.
10. **Output**: mux + audio copy; `-progress pipe:1`.

Podsumowanie lokalizacji: wideo = GPU(dekoduj) → CPU(filtry+blend) → GPU(koduj); HUD = zawsze CPU → GPU.

## Actual GPU_RESIDENT pipeline (krok po kroku)

Warunki: single-file, 8-bit SDR (probe `_probe_intel_native_source`), bez rotacji/cięć, HUD obecny, rozdz. ∈ {source,720p,1080p}, `TELEM_INTEL_GPU_RESIDENT!=0`.

1. **Decode**: QSV, klatki GPU (`-hwaccel_output_format qsv`, `-filter_hw_device intel_qsv`).
2. **Base**: `[0:v]scale_qsv=W:H[base]` (GPU; rotacja ≠ 0 niedozwolona — raise).
3. **HUD region** (ETAP 3C): globalny bbox z `get_layout_hud_bbox()` → clamp + wyrównanie do parzystości; jeśli pole <85% canvasu → `stream_w/h` = bbox, `hud_bbox=(x,y,w,h)`; inaczej FULL_CANVAS. Renderer (`frame_renderer.py:308-310`) cropuje gotowy canvas do bbox.
4. **Transport HUD**: RGBA bboxu → pipe → `[1:v]setpts...,format=bgra,scale=W:H,hwupload=derive_device=qsv[ov]` (konwersja **rgba→bgra pełnego regionu** na CPU + upload do QSV surface).
5. **Compose**: `[base][ov]overlay_qsv=x:y` (vpp QSV, GPU).
6. **Encode**: `hevc_qsv` pobiera QSV surfaces **bezpośrednio** — ogon pipeline'u faktycznie zero-copy.
7. Multi-region atlas: **niedostępny** (`raise ValueError` przy >1 regions); dirty-frame reuse (NVIDIA `_prev_atlas_img`): **nie dotyczy Intela**.

## Memory transfer map (per frame, stan przypięty)

| # | Transfer | Ścieżka | Format/rozmiar źródła | Kiedy | Freq | Sync? | Konieczny? | Eliminowalny? |
|---|---|---|---|---|---|---|---|---|
| T1 | PIL→SHM memcpy (`np.copyto`) | worker RAM→SHM | RGBA `region×4` | co klatkę | per-frame | nie (RAM) | tak (IPC) | częściowo (mapped-target jak NVIDIA) |
| T2 | SHM→pipe (`stdin.write(memview)`) | SHM→kernel pipe | j.w. | co klatkę | per-frame | backpressure | tak | nie (architektura pipe) |
| T3 | hwdownload wideo | GPU(QSV)→CPU | NV12/P010 `W×H` | co klatkę | per-frame | **TAK (device sync)** | definicją CPU_REFERENCE | tylko rezygnacją ze ścieżki |
| T4 | rgba→yuva420p (FFmpeg overlay) | CPU swscale | RGBA pełny canvas (CPU_REF) / region (native bgra) | co klatkę | per-frame | nie | format wynika z overlay SW | zmianą formatu wej./atlasem |
| T5 | niejawny hwupload przed hevc_qsv | CPU→GPU | NV12/P010 | co klatkę | per-frame | pot. blokujące | definicją CPU_REFERENCE | j.w. |
| T6 | rgba→bgra + scale (native ov_input) | CPU swscale | RGBA region | co klatkę | per-frame | nie | wymagany przez overlay_qsv | render BGRA natywnie — możliwy |
| T7 | hwupload HUD (native) | CPU→GPU | BGRA region | co klatkę | per-frame | pot. blokujące | tak (compose na GPU) | nie |
| T8 | decode QSV→scale_qsv→overlay_qsv→encode | GPU→GPU | NV12 surfaces | co klatkę | per-frame | brak hosta | — | **zero-copy (native)** |

Kopiowania Python-side pełnej klatki (CPU_REFERENCE): `img.tobytes()`-równoważne `copyto` (T1) + pipe write (T2) + odczyt w FFmpeg + T4 = **≥3–4 obiegów bajtów RGBA** na klatkę.

## Estimated bytes/frame and bandwidth

Współczynniki: RGBA/BGRA = 4 B/px, NV12 = 1,5 B/px, P010 = 3 B/px. MiB = 2^20 B.

| Strumień | 1920×1080 B/f | @30 FPS | @60 FPS | 3840×2160 B/f | @30 FPS | @60 FPS |
|---|---:|---:|---:|---:|---:|---:|
| HUD RGBA full canvas | 8 294 400 | 237,0 MiB/s | 474,0 MiB/s | 33 177 600 | 949 MiB/s | 1897 MiB/s |
| HUD region (przykład 3C @4K: 854 784) | zależny od bbox | — | — | 854 784 | 24,4 MiB/s | 48,9 MiB/s |
| Wideo NV12 (T3/T5/T8) | 3 110 400 | 89,0 MiB/s | 178,0 MiB/s | 12 441 600 | 356 MiB/s | 712 MiB/s |
| Wideo P010 (HDR CPU_REF, T3') | 6 220 800 | 178 MiB/s | 356 MiB/s | 24 883 200 | 712 MiB/s | 1424 MiB/s |

Wniosek ilościowy: w CPU_REFERENCE strumień HUD (RGBA) jest **~2,67× większy niż wideo NV12** w tej samej rozdzielczości i przechodzi ≥3 kopie user-space; w native po ETAP 3C spada o 95–97% dla kompaktowych layoutów (raport 3C: 24,4 MiB/s @4K30).

## CPU ↔ GPU synchronization points

| Miejsce | Klasyfikacja | Uzasadnienie |
|---|---|---|
| `hwdownload` (CPU_REF) | **DEFINITELY BLOCKING** | sync na dekodowanych surfaces QSV przed pierwszym filtrem SW |
| niejawny `hwupload` przed hevc_qsv | POTENTIALLY BLOCKING | submit + sync przy konsumpcji; async_depth=4 częściowo amortyzuje |
| `hwupload=derive_device=qsv` (HUD native) | POTENTIALLY BLOCKING | j.w., per region |
| `shm_pool.acquire` (`streaming.py:465-496`) | POTENTIALLY BLOCKING | bounded 30 s, fail-fast gdy FFmpeg martwy; blokada = backpressure enkodera |
| `wait(FIRST_COMPLETED, timeout=0.1)` pętla producenta | ASYNC | równoległe procesy; polling 10 Hz |
| `_put_frame` → `queue.put(timeout=0.1)` | POTENTIALLY BLOCKING | maxsize=max(8,2N); izoluje cancel/failure |
| writer-thread `stdin_buffer.write(memview)` | **DEFINITELY BLOCKING (tylko wątek writera)** | celowa izolacja backpressure; producer działa dalej do wyczerpania MAX_IN_FLIGHT |
| `writer_t.join(timeout)` / drain końcowy | BOUNDED | timeouty 1–3 s |
| QSV decode→filter (native) | ASYNC (GPU) | brak hosta między scale_qsv/overlay_qsv/encode |

Brak map/unmap D3D11 po stronie Pythona — Python nigdy nie dotyka surfaces; cała synchronizacja GPU jest zamknięta w procesie FFmpeg.

## FFmpeg/QSV filter graph analysis (grafy rzeczywiste z logów)

CPU_REFERENCE (720p, `cpu_file.log`):

```text
[0:v]hwdownload,format=nv12,scale=1280:720:flags=lanczos[base];
[1:v]setpts=PTS-STARTPTS,format=rgba[ov];
[base][ov]overlay=0:0:shortest=1[vtemp];[vtemp]null[vtemp2];[vtemp2]null[vout]
-c:v hevc_qsv ... -pix_fmt nv12
```

Kosztowne: wyjście z GPU (T3), swscale rgba→yuva420p pełnego canvasu (T4), blend SW, powrót na GPU (T5). Obecność QSV po obu stronach NIE oznacza zero-copy — środek grafu jest w pełni software'owy.

GPU_RESIDENT (`gpu_file.log`, po 3C: W×H = bbox):

```text
[0:v]scale_qsv=1280:720[base];
[1:v]setpts=PTS-STARTPTS,format=bgra,scale=W:H,hwupload=derive_device=qsv[ov];
[base][ov]overlay_qsv=x=X:y=Y:shortest=1[vtemp];...
-c:v hevc_qsv ... -pix_fmt nv12
```

Jedyne opuszczenie GPU to upload HUD (region). Uwaga: `format=bgra` (nie rgba jak NVIDIA!) = dodatkowa konwersja T6. Softwarowe filtry między hardware w ścieżce wideo: brak.

## HUD/indicator path

- Render: zawsze CPU/PIL (obie ścieżki), w procesach (domyślnie workers = cpu_n−1; tu 11).
- Jeden wspólny canvas RGBA (compositor: reuse-canvas + regionalny clear poprzednich bboxów, paste/alpha_composite per wskaźnik); crop do bbox dopiero na końcu (`frame_renderer.py:308-310`).
- Transport: CPU_REFERENCE = pełna klatka ZAWSZE; native = bbox (fallback FULL_CANVAS przy ≥85% pola).
- Przezroczyste piksele są kopiowane — brak alpha-tight cropu w transporcie Intel.
- Dirty-frame skip: tylko NVIDIA MULTI_REGION (`_prev_atlas_img`); Intel przerysowuje każdą klatkę.
- Koszt generacji: historyczny pomiar AMD ETAP5E (`compositing_after.json`, 1131 f): suma `pillow.alpha_composite` ≈ 14,0 ms/f dla bogatego layoutu (per-wskaźnik 0,2–6 ms); na 11 procesach ≈ 1,3 ms/f efektywnie.

Werdykt „czy HUD bottleneckiem”: TRANSPORT HUD — tak dla CPU_REFERENCE (dominanta bajtowa ~2,67× vs wideo NV12; potwierdzone zyskiem 1,09–1,30× po redukcji w native 3C). GENERACJA HUD — nie jako dominanta wall-clock (równoległa), lecz niezmierzona per-stage → instrumentacja przed jakąkolwiek zmianą rendererów.

## Threading and pipeline overlap

Realny overlap: N−1 procesów HUD ∥ writer-thread ∥ FFmpeg ∥ stdout-reader. To NIE jest sekwencja WAIT. Słabe punkty:

1. `MAX_IN_FLIGHT = max(4, 2·n_workers)` (tu 22): 4K FULL_CANVAS ≈ 22 × 31,6 MiB ≈ 680 MiB SHM; po REGION native maleje; CPU_REF 4K nadal duże (pamięć, nie CPU).
2. Head-of-line w reorder_buf: sekwencyjny next_idx — pojedynczy wolny worker wstrzymuje drain mimo gotowych dalszych ramek.
3. Writer single-thread: 4K60 full canvas ≈ 1897 MiB/s przez stdin — blisko praktycznych sufitów pipe.
4. Telemetria PRECOMPUTED (3,8 ms jednorazowo) — poza ścieżką krytyczną.

## Ranked bottlenecks P0–P3

| Priorytet | Problem | Miejsce | Mechanizm / koszt | Rośnie z rozdz.? | z FPS? | CPU_REF? | NATIVE? | 1080p60/4K60 wpływ | Pewność |
|---|---|---|---|---|---|---|---|---|---|
| **P0** | Round-trip wideo GPU→CPU→GPU; dla 10-bit dodatkowo pełny SW decode | `command_builder.py` gałęzie intel + niejawny hwupload przed hevc_qsv | T3+T5 przez PCIe, device sync; P010 podwaja bajty | liniowo | liniowo | TAK | nie | wysoki / bardzo wysoki | HIGH mechanizm, MEDIUM udział czasowy |
| **P1** | HUD zawsze FULL_CANVAS w CPU_REFERENCE | `streaming.py:838` gate `intel_gpu_resident` | 7,9/31,6 MiB/f RGBA × ≥3 kopie + swscale rgba→yuva420p pełnej klatki | liniowo | liniowo | TAK | nie (ma REGION) | wysoki / dominujący bajtowo | HIGH mechanizm, MEDIUM zysk (zależny od bbox layoutu) |
| **P1.5** | Brak instrumentacji per-stage generacji HUD | compositor/frame_renderer | decyzje ślepe; hist. ~14 ms/f bogaty layout | słabo | słabo | TAK | TAK | średni | HIGH potrzeba pomiaru |
| **P2** | Brak dirty-frame reuse na Intel | `frame_renderer.py` (skip tylko NV atlas) | re-render + re-transfer statyki co klatkę | pole canvasu | tak | TAK | TAK | średni (zmierzyć clean-ratio!) | MEDIUM |
| **P2** | rgba→bgra + scale regionu (native) | builder ov_input | pełny swscale regionu co klatkę | polem bboxu | tak | nie | TAK | niski–średni | MEDIUM |
| **P2** | SHM memory sizing | `MAX_IN_FLIGHT = max(4, 2·n_workers)` | setki MiB przy 4K FULL_CANVAS | liniowo | sloty | TAK | mniejsze po 3C | ryzyko pamięciowe | HIGH arytmetyka |
| **P3** | Head-of-line reorder; multi-region atlas raise dla Intel | streaming producer / builder | sporadyczne stalle; rozproszone layouty → FULL fallback | — | — | TAK | TAK | niski–średni | LOW-MEDIUM |

## Evidence

- Grafy/timingi: `scratch/intel_etap3b/cpu_file.log` (WALL 4,1608 s; ffmpeg_write avg 12,71 ms p95 35,25 max 599; workers=11; SHM 22×3,5 MB; telemetry precompute 3,8 ms), `gpu_file.log` (WALL 4,3973 s; avg 14,31 p95 40,43 max 661), `cpu3.log` (run aborted: child process died), `cpu.log` (89 MB spam REPL — pominięty).
- ETAP 3C (sesja równoległa, zweryfikowano z kodem): transport −95,0/−96,3/−97,4%; wall speedup 1,19×/1,09×/1,30× (720p/1080p/4K); parity bez artefaktów brzegowych.
- HOTFIX 10-bit (zweryfikowano z kodem i testami): probe pix_fmt → nv12|p010le; HDR render PASS, metadata zachowana; SW-decode branch dla p010.
- Kod stanu przypiętego: `streaming.py:838-865` REGION gate (tylko native); `streaming.py:1015+` input args SW-decode; `shared_memory.py:122-232`; `frame_renderer.py:161-200` (NV dirty-check) i `:284-316` (crop hud_bbox); `command_builder.py` gałęzie intel (SW-decode → format=p010le bez hwdownload; hwdownload branch; encoder pix_fmt); `benchmark.py` (tracker off domyślnie).
- HOTFIX 2 QSV hwdownload-sync (`Raporty/RAPORT_INTEL_HOTFIX_2_QSV_HWDOWNLOAD_SYNC.md`, pojawił się w trakcie zamykania audytu): dokument opisuje zmiany już obecne w stanie przypiętym (SW decode p010 bez `-hwaccel qsv`/`hwdownload`, device pinning zachowany, real streaming test PASS). Zweryfikowano zgodność z kodem hash-pinned — rekonstrukcja CPU_REFERENCE-HDR w tym raporcie już ją odzwierciedla.

## Tested

- Stabilność stanu: SHA-256 T0 vs T1 (okno ≥75 s; obce zapisy ostatnie o 09:29, T1 o 09:37:02) — **9/9 plików identycznych**.
- Focused suite na stanie przypiętym: `python -m pytest tests/test_intel_backend.py tests/test_video_helpers.py tests/test_gpu_compositor.py tests/test_amd_native_overlay_handoff.py -q` → **51 passed** (zgodne z 3C/HOTFIX).
- Nowych benchmarków runtime świadomie NIE wykonano: współdzielone drzewo robocze + istniejący materiał pomiarowy 3B/3C; uruchamianie renderów mogłoby skolonizować artefakty i zanieczyścić pomiary.

## Not tested

- Nowe rendery Intel runtime w tym audycie (1080p60/4K60) — wpływy P0/P1 w tych punktach pracy to ekstrapolacja arytmetyki bajtowej + danych 3C, nie pomiar.
- Wydajność ścieżki p010le/SW-decode (poprawność potwierdzona przez sesję równoległą, wydajność nie).
- AMD/NVIDIA/CPU-generic runtime — nietknięte statycznie (hash-pinned diff review).

## Risks

1. Concurrent modification: dalsza edycja plików unieważnia odniesienia liniowe i wnioski o niezatwierdzonym diffie.
2. REGION dla CPU_REFERENCE: ryzyko parity krawędzi regionu przy niezależnym lanczos-scale regionu vs pełnej klatki (sub-px pierścień ≤2 px) — wymagane A/B wizualne + rotacje 90/180/270.
3. Dirty-reuse bez zmierzonego clean-ratio da prawdopodobnie znikomy zysk (time_display/charts dirtyują większość klatek).
4. SHM pamięć przy 4K i wielu workerach — rozważyć limit MAX_IN_FLIGHT względem rozmiaru ramki.

## Recommended next optimization stage

**Etap 4A: REGION transport dla Intel CPU_REFERENCE + instrumentacja per-stage HUD.**

- Co: usunąć `intel_gpu_resident` z warunku REGION (`streaming.py:838`) lub dodać równoległą bramkę CPU_REFERENCE (+ env kill-switch analogiczny do `TELEM_INTEL_HUD_REGION`); builder już obsługuje hud_bbox w gałęzi generic overlay (`overlay=x:y`, scale regionu), renderer już cropuje. Plus timery per-stage (compose/dispatch/copyto/write) — zgodnie z rekomendacją 3C.
- Dlaczego: największy pozostały strumień bajtów Intela (pełny RGBA canvas) w jedynej ścieżce bez redukcji; mechanizm zwalidowany po stronie native; zmiana zawężona do gate'u + testów; zero dotknięć AMD/NVIDIA/CPU-generic.
- Czego NIE optymalizować teraz: rendererów wskaźników/GPU-fontów (brak danych per-stage), SHM/pipe (już zero-copy IPC), presetów QSV, liczby workerów, dirty-reuse/atlasu (najpierw clean-ratio i rozkład bboxów realnych projektów).
- Oczekiwany zysk: proporcjonalny do (1 − pole_bbox/pole_canvas) transportu + odpadające swscale pełnej klatki; analogia 3C ≈ 1,1–1,3× wall @30 fps dla kompaktowych HUD; większy przy 60 fps / 4K (sufity pipe i kopii bliżej).
- Ryzyka regresji: krawędzie regionu (lanczos edge), interakcja z needs_cpu_rotation (region działa przez stream_w/h we wszystkich gałęziach generic — pokryć testami), z-order bez zmian (crop po compose).
- Pomiar A/B: harness typu run_ab.py; warianty REGION on/off (env); 720p kanoniczny + 1080p + 4K smoke ×3 powtórzenia; metryki WALL, ffmpeg_write avg/p95 (BenchmarkTracker.enable()), `[INTEL] HUD upload bytes/frame`; parity decode 0,5/3,0/5,0 s próg >2 (metodyka 3B/3C).

## Final verdict

Na stanie hash-pinned (T0==T1, kontrola zamknięcia poniżej): pipeline Intel NATIVE jest architektonicznie zdrowy — wideo zero-copy end-to-end (decode→scale_qsv→overlay_qsv→encode), HUD ograniczony do bboxu. **Największe nierozwiązane koszty skupiają się w Intel CPU_REFERENCE: P0 — wymuszony round-trip wideo GPU→CPU→GPU (P010 podwaja bajty dla HDR), P1 — pełno-klatkowy transport HUD RGBA.** Synchronizacja i IPC są poprojektowane (brak antywzorca sekwencyjnych WAIT). Najbardziej opłacalny następny etap: przeniesienie gotowego mechanizmu REGION na CPU_REFERENCE wraz z instrumentacją per-stage HUD; optymalizacje rendererów dopiero po jej wynikach.

### State closure — WYNIK: VALID

Powtórne SHA-256 po zakończeniu audytu (`scratch/intel_etap4_audit_T2.json`, 2026-08-25 09:47:14): **CHANGED_FILES=0** — 9/9 audytowanych plików źródłowych identycznych z T0/T1. Różnica `git status` względem T0 obejmuje wyłącznie: (a) własne artefakty audytu (niniejszy raport, JSON-e T0/T1/T2), (b) obcy dokument untracked `RAPORT_INTEL_HOTFIX_2_QSV_HWDOWNLOAD_SYNC.md` bez wpływu na kod (treść = zmiany już obecne w stanie przypiętym). Żaden hash się nie zmienił → **raport nie jest INVALIDATED; Final verdict obowiązuje**. Zastrzeżenie: sesja równoległa pozostaje aktywna — jakiekolwiek kolejne jej commity/edycje po chwili zamknięcia wykraczają poza ten audyt.





