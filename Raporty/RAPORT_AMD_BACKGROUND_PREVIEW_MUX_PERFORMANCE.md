# AMD — background/foreground, Preview, live mux i logging

Data audytu: 2026-09-06  
Gałąź: `integration/intel-amd`  
Backend: AMD Native D3D11 + AMF. Intel/NVIDIA nie były modyfikowane.

## Zadanie

Sprawdzić zależność między przełączeniem TeleM/Chrome, Export Preview Async,
logowaniem, pumpem named pipe, `stdin.flush()` i życiem procesu FFmpeg oraz
usunąć możliwe zalegające requesty Preview i diagnostyczny brak kontekstu przy
awarii pipe.

## Stan początkowy

W produkcji obserwowano spadek do około 22 FPS, bardzo duży output konsoli oraz
późniejsze `ERROR_NO_DATA` przy zapisie native do live-mux pipe. Sam komunikat
`Live mux pipe write failed: err=232` nie rozstrzygał, czy wcześniej zakończył
się FFmpeg, czy tylko druga strona pipe została zamknięta.

Working tree był już zmodyfikowany przed audytem. Nie cofano tych zmian i nie
wykonywano commit/push.

## Implementacja

### Diagnostyka pipe przed cleanupem

Przed zamknięciem zasobów dla `ERROR_NO_DATA`, `ERROR_BROKEN_PIPE`,
`BrokenPipeError`, błędu pumpa lub niezerowego return code FFmpeg wypisywany jest
jeden blok `[AMD LIVE MUX FAILURE CONTEXT]`. Zawiera:

- native error code/name/text, frame, stage, stage age i liczniki native,
- pipe connected, bytes, cancel flags,
- pump thread, exit reason, error, bytes/chunks, czas write/flush,
- FFmpeg PID, alive, returncode i ostatnie 100 linii stderr,
- cancel state/reason, generation ID, Preview state, render thread,
- wolne miejsce i rozmiar scratch.

Dump jest idempotentny i wykonywany przed teardownem.

### Preview

`Export Preview Async` jest teraz latest-state-only:

- maksymalnie jeden aktywny worker,
- nowy timestamp zastępuje poprzedni pending timestamp,
- stary wynik jest odrzucany, jeśli pojawił się nowszy request,
- w tle/minimized/nieaktywnym TeleM nie startuje kosztowny seek/render,
- po powrocie na pierwszy plan pobierany jest tylko najnowszy timestamp,
- wyjątek Preview nie propaguje się do lifecycle renderu.

Stan Preview jest dostępny również w snapshotach watchdog/failure context.

### Logging i watchdog

- domyślny heartbeat: jedna linia maksymalnie co 10 s,
- usunięto per-frame output eksportera,
- dodano poziomy `ERROR`, `INFO`, `DEBUG`, `TRACE` w polityce Python logging,
- `TELEM_RENDER_DEBUG=1` włącza szczegółowy strumień,
- szczegółowe stall snapshots trafiają do `*.amd_watchdog.jsonl`,
- próg watchdog: warning >2 s, detail snapshot >5 s, thread dump/freeze
  handling >15 s.

### Mux pump / flush

Dodano tryby diagnostyczne `AMD_MUX_FLUSH_MODE=none|batch|every_chunk`.
Domyślnie produkcja używa `none`; `stdin.close()` nadal finalizuje zapis.

## Kontrolowane A/B — 1000 klatek

Źródło było identyczne we wszystkich czterech testach:
`Video/GX010115.MP4` + `Video/GX010114_116.fit`, 4K, ten sam layout,
`SYNC`, queue depth 0, zakres 1000 klatek.

`B` i `C` używały kontrolowanego stanu okna TeleM w tle. Nie sterowano Chrome,
zgodnie z zakresem zadania; nie jest to dowód realnego obciążenia GPU przez
Chrome.

| Test | Stan | Render FPS | Effective FPS | Preview build/update | stage age max | producer q max | encoder q max | FFmpeg |
|---|---|---:|---:|---:|---:|---:|---:|---|
| A | TeleM foreground, Preview ON | 17.613 | 16.692 | 64 / 60.34 s ≈ 1.06 Hz | 0.000 s* | 0 | 1 | alive, clean |
| B | TeleM background, Preview ON | 36.114 | 32.472 | 0 | 0.016 s | 0 | 1 | alive, clean |
| C | TeleM background, Preview OFF | 35.468 | 31.922 | 0 | 0.016 s | 0 | 1 | alive, clean |
| D | TeleM foreground, Preview OFF | 37.949 | 33.924 | 0 | 0.016 s | 0 | 1 | alive, clean |

\* Heartbeat precision in this log rounded the observed values to 0.000 s.

Wszystkie cztery pliki mają po 1000 klatek HEVC i przeszły probe MP4.

Wniosek z tego A/B: Preview ON jest kosztowny, gdy TeleM pozostaje aktywny,
natomiast po przejściu TeleM w tło nie tworzy backlogu i nie wykonuje updateów.
Różnica B/C jest mała i mieści się w zmienności tego pojedynczego przebiegu.

## `stdin.flush()` — 1000 klatek

Każdy wariant używał tego samego wejścia i ustawień.

| Tryb | Effective FPS | Pipe throughput | Flushes | Flush time | MP4 |
|---|---:|---:|---:|---:|---|
| none | 33.031 | 6.688 MB/s | 0 | 0.000 ms | valid |
| batch/8 | 33.473 | 6.774 MB/s | 134 | 1.909 ms | valid |
| every chunk | 33.195 | 6.730 MB/s | 1078 | 141.422 ms | valid |

Nie ma dowodu, że explicit flush po każdym chunku jest potrzebny. Koszt
`every_chunk` jest mierzalny, a integralność MP4 bez explicit flush została
potwierdzona. Produkcyjny default pozostaje `none`.

W pumpie normalne zamknięcie przez drugą stronę jest rejestrowane jako
`overlapped_result_error (109)` w `exit_reason`, ale nie jako `mux_pump_error`.
To normalny EOF po zakończeniu muxowania, nie pipe failure.

## Logging A/B

Na tym samym 1000-frame workload:

- production logging: 147 linii, Effective FPS 33.031,
- `TELEM_RENDER_DEBUG=1`: 528 linii, Effective FPS 31.676.

Ten pojedynczy pomiar wskazuje około 4.1% różnicy na niekorzyść verbose
logging. Nie spełnia to kryterium overhead `<1%`; pomiar jest wrażliwy na
zmienność workloadu i wymagałby powtórzeń do formalnej charakterystyki.

## Test 3000+ klatek

Kontrolowane testy foreground/background model:

- Preview ON: 3000/3000, render 17.504 FPS, effective 17.188 FPS,
  MP4 valid, `ok=true`.
- Preview OFF: 3000/3000, render 35.849 FPS, effective 34.146 FPS,
  MP4 valid, `ok=true`.

Nie były to testy z aktywnie sterowanym Chrome. Nie wolno ich interpretować jako
pełnego dowodu Chrome GPU contention.

## Długi test > frame 33710

Uruchomiono 34 000 klatek na kanonicznym zestawie wieloplikowym:

`GX010114.MP4 + GX010115.MP4 + GX010116.MP4 + GX010114_116.fit`

Wynik:

- 34 000/34 000 klatek,
- render 31.473 FPS, effective 31.363 FPS,
- `producer_q=0`, `encoder_q=1`, max `native_stage_age=0.032 s`,
- FFmpeg żywy przez render i zakończony poprawnie,
- MP4: `mov,mp4,m4a`, 12.345 GB, duration 1134.485 s,
- brak pipe failure, brak freeze handling, brak Preview backlog.

Przebieg obejmował obserwowany obszar frame 33710.

## Testy automatyczne i statyczne

- `pytest` — wybrany zestaw regresji: **32 passed**.
- Testy fokusowe audytu Preview/watchdog: **7 passed**.
- `py_compile` zmienionych modułów: PASS.
- `git diff --check`: brak nowych błędów w plikach audytu; istniejące ostrzeżenia
  whitespace dotyczą innych, wcześniejszych zmian.

Nie wywołano rzeczywistego failure context, ponieważ żaden kontrolowany test nie
zerwał pipe. Pola failure block są więc zaimplementowane, ale ich wartości dla
FFmpeg/crash path pozostają **NOT TESTED** na sztucznie wywołanej awarii.

## Root cause / ryzyka

Root cause pierwotnego `ERROR_NO_DATA` pozostaje **NOT PROVEN**. Z dotychczasowego
logu można było stwierdzić tylko zamknięcie/utracenie named pipe; nie można było
rozstrzygnąć kolejności FFmpeg-vs-pipe. Nowy dump pozwoli rozstrzygnąć to przy
następnym realnym wystąpieniu.

Najważniejsze pozostałe ograniczenia:

1. Brak automatycznego testu z Chrome faktycznie na pierwszym planie — Chrome
   nie był sterowany.
2. Kryterium logging overhead `<1%` nie jest spełnione/proven na obecnym
   pojedynczym pomiarze verbose-vs-production.
3. `preview_ready_calls` w harnessie nie jest wiarygodnym licznikiem sygnału;
   użyto faktycznych `preview_build_calls`. Nie wpływa to na pipeline renderu.

## Werdykt

Stabilność live mux, brak Preview backlogu, brak zależności renderu od GUI
foreground oraz usunięcie per-frame console spam zostały potwierdzone w
kontrolowanych przebiegach.

**NOT READY** jako pełne zamknięcie acceptance criteria: realny Chrome
foreground contention i logging overhead `<1%` nie zostały jeszcze dowiedzione,
a root cause historycznego pipe failure nie został odtworzony.

