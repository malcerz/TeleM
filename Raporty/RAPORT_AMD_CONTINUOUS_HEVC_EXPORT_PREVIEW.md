# AMD continuous HEVC Export Preview

## Zakres

Zastąpiono produkcyjny AMD Export Preview ciągłym, best-effort dekoderem FFmpeg
zasilanym kopią dokładnie tego samego strumienia HEVC, który został zapisany
przez końcowy mux AMF. Nie zmieniano natywnego D3D11/AMF decode/compositor,
pipe writera, Stage A/B/C, watchdogu ani polecenia końcowego muxera.

Stan początkowy: dirty worktree na `integration/intel-amd`, HEAD
`59277b4c920e0bb8a9642e4a574a32db0edcfacc`. Istniejące modyfikacje użytkownika
pozostały nietknięte; nie wykonano reset/clean/commit/push.

## Implementacja

Nowy moduł: `src/ffmpeg/amd_hevc_preview.py` (`AMDContinuousHEVCPreview`).

- Jeden proces FFmpeg na render, wejście `-f hevc -i pipe:0`, wyjście
  `-f rawvideo -pix_fmt bgra pipe:1`.
- Filtr: `fps=<AMD_EXPORT_PREVIEW_FPS>,scale=<W>:<H>:bicubic,eq=brightness=-0.08`.
- Domyślnie 1280x720, 1 fps; szerokość można ustawić przez
  `AMD_EXPORT_PREVIEW_WIDTH`, FPS przez `AMD_EXPORT_PREVIEW_FPS`.
- Sidecar ma własne stdin/stdout/stderr, proces, event stop i worker threads.
  Render cancel event nie jest współdzielony.
- Wejście ma bounded queue (256 chunks), `put_nowait`; pełna kolejka wyłącza
  tylko Preview. Końcowy mux zapisuje chunk najpierw, a dopiero potem wykonuje
  best-effort `preview_session.feed(chunk)`.
- Awaria/kill/EOF sidecara loguje `[EXPORT PREVIEW FFMPEG ERROR]`, ale nie
  ustawia render cancel i nie przerywa finalnego eksportu.
- `finish_input()` jest wykonywane dopiero po zakończeniu pumpa/muxu; przy
  Preview OFF lub końcu renderu proces jest zamykany i wszystkie trzy wątki
  są dołączane. Nie ma automatycznego restartu ani kumulowania decoderów.
- Callback przenosi surowy BGRA do GUI przez sygnał Qt; GUI tworzy kopię
  `QImage` i skaluje ją do `hud_preview_label`. Stara ścieżka OpenCV/seek/MPV
  jest pomijana dla AMD continuous HEVC.
- Domyślnie sidecar używa `-threads 1` i klasy procesu BELOW_NORMAL, aby nie
  konkurować z finalnym AMF/mux.

Zmodyfikowane punkty integracji:

- `src/ffmpeg/amd_native_exporter.py` — start/feed/finalizacja sidecara;
  final mux ma pierwszeństwo.
- `src/ffmpeg/streaming.py` — przekazanie sesji Preview do AMD exportera.
- `src/gui/qt/_mixins/render_mixin.py` — przekazanie opcji sesji.
- `src/gui/qt/tabs/render_tab.py` — utworzenie/teardown sesji, sygnały HEVC,
  diagnostyka i osobna generacja Preview.
- `scratch/run_background_preview_audit.py` — sekwencje testowe i konfigurowalny
  timeout harnessu.

Nie zmieniano plików native C++ ani DLL.

## Weryfikacja statyczna

`py_compile` dla modułu Preview, exportera AMD, streamingu, RenderMixin,
RenderTab i harnessu: **PASS**.

`git diff --check` dla tych plików: **PASS** (jedynie standardowe ostrzeżenia
LF/CRLF istniejące dla dirty plików).

Wersja FFmpeg użyta w testach:

`2026-08-17-git-426841da9d-full_build-www.gyan.dev`, build z `--enable-amf`
i `--enable-d3d11va`.

## Wyniki testów

### 1280x720, 1 fps, jedna instancja procesu

Sekwencja `ON → OFF → ON → OFF`, 20 klatek na render:

- wszystkie 4 rendery zakończone poprawnie;
- dwa rendery ON otrzymały `source=final_hevc_stream`, `frame_size=1280x720`;
- `updates=1`, `dropped_chunks=0`, `restarts=0`, `last_error=`;
- po każdym renderze `workers=0`, `preview_process_alive=0`, brak child PID;
- Render FPS: 22.704 / 28.080 / 27.227 / 28.080 (krótkie smoke runy).

Źródło: `scratch/continuous_preview_onoffonoff_20.log`.

### 960x540 fallback

Sekwencja `ON → OFF → OFF`, 20 klatek:

- **PASS**;
- `frame_size=960x540`, `updates=1`, `dropped_chunks=0`, brak błędu Preview;
- kolejne dwa rendery OFF zakończone poprawnie.

Źródło: `scratch/continuous_preview_960_20.log`.

### Fault injection

Sekwencja `Preview ON + fault injection → Preview OFF`, 20 klatek:

- sidecar zgłosił `last_error=fault injection` i został zamknięty;
- pierwszy finalny render zakończył się `RENDER COMPLETE`;
- drugi render OFF w tej samej instancji również zakończył się poprawnie;
- brak anulowania renderu przez błąd sidecara.

Źródło: `scratch/continuous_preview_fault20_threads1.log`.

### MP4 / ffprobe

Artefakty z renderów smoke są poprawnymi HEVC MP4:

```
codec_name=hevc
width=3840
height=2160
nb_frames=20
duration=0.667333
```

Sprawdzone dla renderów ON/OFF oraz fault-injection przez lokalny `ffprobe`.

### Multi-file 3000 klatek

Test boundary `AMD_AUDIT_MULTIFILE=1`, 3000 klatek, wykonano zarówno z
Preview ON (`multifile_on`), jak i OFF (`multifile_off`). Obie próby kończą się
wcześniej ogólnym `Render error` i pustym `.part.temp_video.mp4`, zanim pojawi
się wynik renderu. Taki sam błąd przy Preview OFF dowodzi, że nie jest to
regresja sidecara; jest to istniejący problem multi-file poza zakresem tego
zadania. Test wymagany przez acceptance pozostaje **NOT PROVEN**.

Źródła: `scratch/continuous_preview_multifile_3000_retry.log` oraz
`scratch/continuous_preview_multifile_3000_off.log`.

### CPU / RSS sidecara

Kod zbiera throttled `cpu_percent_mean/peak` i `rss_peak_bytes`, ale krótkie
smoke runy zakończyły zbyt szybko fazę karmienia, aby uzyskać próbkę psutil
(wartości `null`). Długi 3000-frame multi-file run jest zablokowany opisanym
wyżej błędem bazowego multi-file. CPU/RSS sidecara: **NOT MEASURED**.

## Ocena bezpieczeństwa

Potwierdzone:

- final mux write wykonywany przed sidecar feed;
- sidecar failure nie kończy renderu;
- bounded/non-blocking feed;
- osobny lifecycle i teardown procesu/wątków;
- brak OpenCV/VideoCapture/seek/recompose w AMD production path;
- cztery kolejne generacje ON/OFF działają w jednej instancji;
- brak child process/worker po teardown.

Niepotwierdzone:

- pełna akceptacja multi-file 3000 klatek (bazowy błąd multi-file);
- docelowy pomiar CPU 2–5% i regresji <=10% na długim materiale;
- długi 1000-frame single-file z aktualnym środowiskiem.

## Status

**IMPLEMENTED / SMOKE PASS — NOT READY FOR FULL ACCEPTANCE**.

Powód statusu NOT READY: wymagany multi-file 3000-frame acceptance test jest
zablokowany niezależnym błędem istniejącym także przy Preview OFF, a CPU/RSS
sidecara nie zostały zmierzone na długim przebiegu. Nie wykonywano żadnych
dalszych zmian naprawczych.
