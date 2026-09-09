# AMD multi-file Stage A render error — forensic fix

## Zakres i stan początkowy

Pracowano na `integration/intel-amd`, HEAD `59277b4`. Nie wykonano reset,
clean, commit ani push. Nie zmieniano Intel, native DLL, D3D11/AMF lifecycle,
Stage A/B/C ani architektury continuous Export Preview.

Źródło testowe harnessu RenderTab:

- `Video/GX010114.MP4`
- `Video/GX010115.MP4`
- `Video/GX010114_116.fit`

Harness używa rzeczywistego `RenderTab`/`RenderMixin` w QApplication offscreen.
Checkbox Preview OFF jest ustawiany przez `chk_hud_preview.setChecked(False)`.

## Minimalna reprodukcja

Preview OFF, multi-file, pełny HUD:

| klatki | wynik |
|---:|---|
| 20 | PASS |
| 50 | PASS |
| 100 | PASS |
| 300 | PASS |
| 1000 | PASS |
| 3000 z pierwotnym harness `tracemalloc` | FAIL — `MemoryError` |
| 3000 bez `tracemalloc` | PASS |

Wszystkie krótkie testy przechodziły Stage A i Stage C. Błąd nie był
zależny od samego przejścia clip1→clip2.

## Pierwotny root cause

`scratch/run_background_preview_audit.py` uruchamiał `tracemalloc.start()`
bezwarunkowo. Przy pełnym HUD, PIL i 3840×2160 dirty-region extraction,
tracemalloc przechowywał ślady każdej alokacji. Przy 3000 klatkach proces
dochodził do presji pamięci i kończył się:

```
[TELEM AMD DLL] Encoded output file write failed
MemoryError: <empty message>
  ... amd_native_exporter.py, _prepare_frame_cpu
  ... _extract_exact_above_regions
  ... PIL.Image.tobytes("raw", "RGBA")
```

Native write error i niedomknięty pump były skutkiem zatrzymania producenta
przez `MemoryError`, a nie pierwotną awarią FFmpeg/pipe. W pierwszej próbie
z pustym `.part.temp_video.mp4` dodatkowo zadziałał 240-sekundowy timeout
harnessu przed finalizacją.

Zmiana diagnostyczna: `tracemalloc` jest teraz opcjonalny przez
`AMD_AUDIT_TRACEMALLOC` (domyślnie wyłączony; `=1` włącza audyt) i nie jest
wymagany do produkcyjnego smoke testu.
Nie zmieniono ścieżki produkcyjnego renderera.

## Zachowanie po zmianie

### Multi-file, Preview OFF, 3000 klatek

Źródło: `scratch/amd_multifile_off_3000_no_tracemalloc.log`.

- planned/decoded/composed/submitted/encoded/written: 3000/3000 w profilu;
- source boundary: `[AMD DIRECT MUX] source_switch 1->2 global_frame=1500`;
- Stage A: `735522562` bytes;
- final `.part`: `738747831` bytes;
- Render FPS: `42.798`;
- Effective FPS: `38.662`;
- Stage C returncode: `0`;
- final render: **PASS**.

### Multi-file, Preview ON, 3000 klatek

Źródło: `scratch/amd_multifile_on_3000_no_tracemalloc.log`.

- final render: **PASS 3000/3000**;
- source boundary: global frame `1500` przekroczony;
- Stage A/final sizes: `735522562` / `738747831` bytes;
- Render FPS: `42.698`;
- Effective FPS: `34.799`;
- Preview generated one GUI update, potem bounded queue zgłosiła
  `bounded input queue full; preview disabled`;
- final mux nie został przerwany; `dropped_chunks=1`, `restarts=0`.

Preview failure pozostał best-effort i nie wpłynął na finalny eksport.

### Multi-file, Preview OFF, 10000 klatek

Źródło: `scratch/amd_multifile_off_10000.log`.

- final render: **PASS 10000/10000**;
- source boundary: global frame `5000`;
- Stage A: `3096775327` bytes;
- final `.part`: `3107550385` bytes;
- Render FPS: `42.248`;
- Effective FPS: `39.910`;
- Stage C returncode: `0`.

### Multi-file, Preview ON, 10000 klatek

Źródło: `scratch/amd_multifile_on_10000.log`.

- final render: **PASS 10000/10000**;
- source boundary: global frame `5000`;
- Stage A/final sizes: `3096775327` / `3107550385` bytes;
- Render FPS: `21.924`;
- Effective FPS: `20.800`;
- Preview updates: `32`;
- `dropped_chunks=1`, `last_error=bounded input queue full; preview disabled`;
- final mux i Stage C returncode `0`.

Sidecar jest celowo bounded/non-blocking, ale jego CPU contention obniżył FPS
w długim teście ON. To ryzyko wydajnościowe, nie błąd poprawności.

## Pierwszy pakiet / pump / FFmpeg

Dodano jednorazowy log:

```
[MULTIFILE FIRST PACKET] frame=2 encoded_bytes=262144 pipe_write_ok=1
pump_read_bytes=262144 ffmpeg_stdin_bytes=262144 output_size=0
```

Dla krótkiego multi-file runu:

```
[AMD DIRECT MUX DIAGNOSTICS] ffmpeg_pid=8880 returncode=0
pump_exit_reason=pipe_closed_error_109
pipe_read_bytes=2903074 ffmpeg_stdin_bytes=2903074 chunks=20
```

`ERROR_BROKEN_PIPE (109)` przy końcu zapisu jest normalnym EOF named pipe po
zamknięciu writer-side i nie jest traktowany jako failure, gdy FFmpeg kończy
się z `returncode=0`. Stage A FFmpeg stderr zawiera tylko informacyjne nagłówki
i ostrzeżenie o unset timestamps; kontener jest poprawny.

## Primary error

`src/gui/qt/_mixins/render_mixin.py` zachowuje teraz pierwszy wyjątek:

- `[RENDER PRIMARY ERROR] <Type>: <message>`;
- `[RENDER PRIMARY TRACEBACK]` z pełnym tracebackiem;
- sygnał GUI zawiera typ i komunikat zamiast pustego `Render error:`.

W reprodukcji diagnostycznej primary error był `MemoryError` z PIL. Późniejsze
cleanup/pump warnings nie nadpisują tej przyczyny.

## Preview OFF — rzeczywisty lifecycle

W logach RenderTab dla Preview OFF:

- brak `[EXPORT PREVIEW FFMPEG START]`;
- `decoder=none`, `hardware_decode=off`;
- `workers=0`;
- brak continuous sidecar i brak async preview update.

Checkbox steruje więc rzeczywistym lifecycle, nie tylko tworzeniem nowych ramek.

## Zmienione pliki

- `scratch/run_background_preview_audit.py` — opcjonalny tracemalloc i timeout;
- `src/gui/qt/_mixins/render_mixin.py` — primary error + traceback;
- `src/ffmpeg/amd_native_exporter.py` — first-packet/pump/FFmpeg diagnostics;
- `Raporty/RAPORT_AMD_MULTIFILE_STAGE_A_RENDER_ERROR_FIX.md` — ten raport.

Native source/DLL, Intel i Export Preview architecture: bez zmian w tej fazie.

## MP4 validation

Po 3000-frame runs `ffprobe` potwierdził dla obu wariantów:

```
video: hevc 3840x2160 nb_frames=3000
audio: aac nb_frames=4675
duration=100.100000
```

## Status

**READY — multi-file baseline recovered.**

Spełnione:

- MULTIFILE 3000 Preview OFF: PASS;
- MULTIFILE 3000 Preview ON: PASS;
- source boundary: PASS (`global_frame=1500` / `5000`);
- primary error preserved: PASS;
- real RenderTab Preview OFF: PASS;
- no final pipe failure / no false cancel: PASS;
- 10000 OFF and ON: PASS.

CPU/RSS sidecara nie zostały wiarygodnie zarejestrowane po zakończeniu procesu
(krótkie próbki psutil były `null`); długi ON test wykazał jednak bounded
teardown i brak child process po renderze. Nie uruchamiano 85574 klatek.
