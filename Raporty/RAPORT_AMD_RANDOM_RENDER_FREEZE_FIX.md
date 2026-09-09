# AMD — random render freeze / pipeline deadlock fix

## Zadanie

Naprawa losowego zatrzymania długiego eksportu wyłącznie w ścieżce
`AMD_NATIVE_D3D11`, bez restartowania renderu, pomijania klatek ani zmian w
pozostałych backendach.

Stan wejściowy zgłoszony przez użytkownika: eksport 85 574 klatek zatrzymał się
około klatki 31 990 przy około 28,6 FPS, bez błędu i jeszcze przed granicą
plików źródłowych.

## Stan repozytorium

- branch: `integration/intel-amd`
- HEAD przed zmianami: `59277b4`
- worktree był już silnie zmodyfikowany; wszystkie istniejące zmiany zostały
  zachowane
- nie wykonano commit, push, reset, clean, restore ani rebase

## Audyt pełnego łańcucha AMD

Rzeczywisty łańcuch jednej klatki:

```text
Python exporter / frame producer
  -> Media Foundation ReadSample (D3D11VA surface)
  -> native D3D11 video processor + HUD compositor
  -> AMF SubmitInput / QueryOutput
  -> native encoded packet write
  -> Windows named pipe
  -> Python pipe pump
  -> FFmpeg stdin / live MP4 mux
  -> output .part / Stage A
```

Sprawdzone potencjalne punkty blokowania:

1. `IMFSourceReader::ReadSample` — synchroniczne wywołanie sterownika; przed
   zmianą brakowało diagnostyki wskazującej, że właśnie ono stoi.
2. D3D11 video processor — trzy pętle `GetData()` w trybie profilowania miały
   nieograniczone oczekiwanie.
3. AMF — pętle input-full/repeat miały ograniczenie, lecz 60 s było zbyt długie
   względem wymaganego watchdoga.
4. Zapis pakietu AMF — `std::ofstream` pisał synchronicznie do named pipe bez
   timeoutu i bez skutecznej propagacji błędu.
5. Python pipe pump — synchroniczne `ConnectNamedPipe`/`ReadFile`; podczas
   ścieżki błędu `_abort_direct_mux()` mógł zawisnąć w `CloseHandle`, gdy drugi
   wątek nadal stał w `ReadFile`.
6. FFmpeg stdout/stderr — stdout jest kierowany do `DEVNULL`; stderr ma osobny
   reader. Bufor diagnostyczny stderr nie miał ograniczonego rozmiaru.
7. Kolejki Python — istniejące kolejki klatek miały timeouty i stop event; nie
   były bezpośrednią przyczyną domyślnego synchronicznego renderu.
8. GUI progress callback — był wykonywany w zależności renderera, więc wolny lub
   zablokowany callback mógł wstrzymać eksport.
9. Żywotność tekstur D3D11 — pending decoded texture jest zwalniana po sukcesie,
   błędzie VP, discard, zmianie źródła i close; nie znaleziono narastającego
   wycieku powierzchni.

## Root cause

Główny nieograniczony punkt blokowania znajdował się po odebraniu pakietu z AMF:

```text
AMF QueryOutput
  -> std::ofstream::write(encoded packet)
  -> Windows named pipe
  -> Python pump / FFmpeg stdin
```

Jeżeli konsument potoku przestawał odbierać dane lub zamykał się w
niekorzystnym momencie, `telem_amd_process_frame()` mógł pozostać na zawsze w
synchronicznym zapisie. Renderer nie wracał do Pythona, więc licznik klatek,
GUI i log również przestawały się aktualizować. Wyjaśnia to losowy charakter
awarii i brak komunikatu błędu.

Podczas testu błędu odtworzono również konkretny deadlock zamykania: wątek pump
stał w synchronicznym `ReadFile`, a `_abort_direct_mux()` zawisł w
`CloseHandle`. Zapisany dump wątków pokazał oba miejsca oczekiwania.

## Implementacja

### Native packet output

- live named pipe używa teraz Win32 overlapped I/O zamiast `std::ofstream`
- `WaitNamedPipeW`: limit 15 s
- `WriteFile` + event + `WaitForSingleObject`: limit 15 s
- timeout przerywa operację przez `CancelIoEx` i zwraca błąd do exportera
- każdy zapis pakietu, również drain/flush/backpressure, sprawdza wynik
- zwykły plik pozostaje na ścieżce `std::ofstream`, ale jego stan jest
  sprawdzany

Nie ma automatycznego restartu, retry od starej klatki ani pomijania klatek.
Niedziałający downstream kończy się kontrolowanym błędem zamiast wiecznego
freeze.

### Python named-pipe pump

- `ConnectNamedPipe` i `ReadFile` są overlapped oraz anulowalne
- abort ustawia stop event, wywołuje `CancelIoEx` i wykonuje ograniczony join
- zamknięcie nie czeka bez końca na synchroniczny `ReadFile`
- stderr muxera jest przechowywany w `deque(maxlen=200)`

### AMF / D3D11 waits

- maksymalne oczekiwanie w pętli AMF: 15 s
- trzy pętle profilujących zapytań D3D11 `GetData`: deadline 15 s i sleep
  100 us zamiast busy-wait bez końca
- błąd native frame processing jest propagowany jako `RuntimeError`; nie jest
  traktowany jak poprawny EOS ani ukrywany fallbackiem CPU

### Heartbeat i watchdog

Dodano lekką telemetrię atomic w DLL i eksport
`telem_amd_get_liveness()` bez zmiany ABI 9. Etapy:

```text
decode_wait -> decoded -> vp_compose -> amf_query -> amf_submit
-> packet_write -> frame_complete -> flush
```

Heartbeat co 5 s raportuje:

- completed/current frame
- produced, decoded, composed, submitted, encoded, written
- producer i encoder queue depth
- aktualny etap native i jego wiek
- stan wątków oraz procesu FFmpeg

Po 15 s bez ukończonej klatki, tylko podczas aktywnej fazy renderowania i bez
cancel, watchdog jednorazowo wypisuje pełny snapshot, końcówkę stderr/stdout i
zapisuje `faulthandler` dump wszystkich wątków do:

```text
<output>.amd_freeze_threads.log
```

Watchdog jest wyłączany przed legalną finalizacją, więc długi remux nie jest
fałszywie zgłaszany jako freeze.

### GUI progress

Callback postępu został odłączony od krytycznego łańcucha klatki. Bounded queue
przechowuje stan postępu; gdy GUI nie nadąża, usuwany jest najstarszy nieaktualny
snapshot. Render nie czeka na GUI. Stop dispatchera ma limit czasu i nie może
zablokować zamykania eksportu.

## Zmienione pliki

- `native/d3d11_amf_pipeline/src/telem_amd_native.cpp`
- `native/d3d11_amf_pipeline/src/d3d11_vp_pipeline.cpp`
- `src/ffmpeg/amd_native_exporter.py`
- `src/ffmpeg/amd_pipeline_watchdog.py` — nowy
- `tests/test_amd_pipeline_watchdog.py` — nowy
- `scratch/run_amd_freeze_long_proof.py` — deterministyczny runner dowodu
- `Raporty/RAPORT_AMD_RANDOM_RENDER_FREEZE_FIX.md`

Kanoniczna `native/d3d11_amf_pipeline/bin/telem_amd_native.dll` została
przebudowana. Załadowany build:

```text
ABI: 9
build_id: telem-amd-native/1.0.0+59277b4c920e.src01787b14f931
liveness symbol: present
```

## Testy automatyczne i fault injection

```text
python -m py_compile \
  src/ffmpeg/amd_pipeline_watchdog.py \
  src/ffmpeg/amd_native_exporter.py \
  scratch/run_amd_freeze_long_proof.py
PASS

python -m pytest -q \
  tests/test_amd_pipeline_watchdog.py \
  tests/test_etap8t_b_async_pipeline.py \
  tests/test_amd_direct_mp4_mux.py
26 passed in 4.73s
```

Obejmuje to:

- brak nowych klatek: heartbeat, freeze alert i all-thread dump
- etap `packet_write` widoczny w diagnostyce
- cancel: brak fałszywego freeze
- całkowicie blokujący callback GUI: submit 1000 aktualizacji nie blokuje
  renderera
- bounded/overlapped native packet write
- deadline zapytań GPU
- wyjątek producenta, pełną/pustą kolejkę, błąd konsumenta i EOS
- awarię procesu muxera, cancel i direct MP4 mux

Osobne wymuszone napełnienie bufora stdout/stderr: **NOT TESTED**. W produkcyjnym
live mux stdout nie jest pipe (`DEVNULL`), więc nie może się napełnić; stderr
jest opróżniany równolegle i ograniczony ring-bufferem. Długi test 60 139 klatek
potwierdził tę architekturę pod realnym obciążeniem, ale nie zastępuje osobnego
fault-injection saturującego stderr.

Dodatkowy przebieg `tests/test_amd_direct_mp4_mux.py`: 9 passed in 3.75 s.

`tests/test_indicator_exhaustive_proof.py` nie został uruchomiony.

## Realne testy AMD

### Smoke z granicą plików

Autorytatywna para z `BENCHMARKS.md`:

```text
Video/GX010114.MP4
Video/GX010115.MP4
Video/GX010114_116.fit
3840x2160
```

- multifile: 300/300, granica po klatce 150, audio obecne, PASS
- single-file: 150/150, PASS
- pełny `def_layout.json`, kanoniczna DLL: 300/300, granica 150, zero map
  cache misses, PASS

### Długi soak ponad historyczny freeze i granicę

Ponieważ dokładne przypisanie FIT dla zgłoszonego projektu 85 574 klatek nie
było jednoznaczne, zgodnie z `BENCHMARKS.md` nie zgadywano pliku telemetrycznego.
Użyto autorytatywnego zestawu powyżej:

```text
GX010114: pełne 58 639 klatek
GX010115: pierwsze 1 500 klatek
razem: 60 139 klatek
source boundary: 58 639
layout: pusty canvas przy aktywnym native HUD
```

Wynik:

```text
historyczny punkt 31 990: przekroczony
punkt około 41 500: przekroczony
granica źródeł 58 639: przekroczona
końcowy ffprobe: 60 139 / 60 139
render phase: 1417.594 s, 42.423 FPS
finalization: około 146.4 s
effective total: około 38.4 FPS
freeze alert: 0
```

Heartbeat przez cały przebieg pokazywał żywy renderer/FFmpeg, `encoder_q=1`
oraz zgodne `encoded == written`. Test zachował pełny decode -> VP -> AMF ->
live mux i zmianę źródła; pusty layout izolował stabilność pipeline od kosztu
konkretnego HUD.

Osobny test pełnego HUD na `def_layout.json` przeszedł 300/300 klatek i granicę
źródeł. Dokładny render zgłoszonego projektu 85 574 klatek: **NOT TESTED** z
powodu niejednoznacznego FIT. Minimalne kryterium długiego przebiegu ponad
31 990 i przez realną granicę plików zostało spełnione.

## Obraz i izolacja backendów

- nie zmieniono shaderów, kolejności kompozycji, parametrów enkodera, mapy ani
  implementacji HUD
- nie zmieniono NVIDIA, Intel ani CPU/reference
- frame-count i obecność audio potwierdzono
- pixel-exact A/B obrazu przed/po nie wykonano, ponieważ nie istniał
  kontrolowany pre-change capture dla tego dirty worktree: **NOT PROVEN**

## Wydajność

- długi izolowany przebieg: 42.423 render FPS
- krótki multifile w tym samym typie ścieżki: 42.891 FPS
- wcześniejszy zapisany punkt odniesienia 300f: 42.062 FPS
- różnica krótkiego testu: +0.829 FPS (+1.97%); nie jest traktowana jako zysk,
  ponieważ obciążenie środowiska nie było laboratoryjnie identyczne
- polling watchdoga co 250 ms i log heartbeat co 5 s nie wykazały mierzalnej
  regresji

## Ryzyka i artefakty

- pojedyncze wywołanie vendor API (`ReadSample` lub `AMF QueryOutput`) może
  zostać zablokowane wewnątrz sterownika; watchdog wskaże etap i zapisze dump,
  lecz nie zabija procesu ani nie restartuje renderu
- timeout pipe zmienia wieczny freeze downstream na jawny kontrolowany błąd
- pełny test dokładnie 85 574 klatek pozostaje NOT TESTED
- pozostał wygenerowany plik dowodowy
  `D:\TeleM-long-proof\amd_freeze_60139f_empty_hud.mp4`
  (22 837 066 763 bajty) oraz ignorowana przez Git pomocnicza
  `telem_amd_native.freeze_fix.dll`; próba ich usunięcia została zablokowana
  przez politykę wykonawczą środowiska. Kanoniczna DLL jest poprawnie
  przebudowana i użyta w końcowym smoke.

## Podsumowanie

```text
AMD BLOCKING-POINT AUDIT: PASS
ROOT CAUSE IDENTIFIED: PASS
BOUNDED LIVE PIPE I/O: PASS
PIPE ABORT DEADLOCK FIX: PASS
5 S HEARTBEAT: PASS
15 S FREEZE DIAGNOSTICS: PASS
GUI PROGRESS NON-BLOCKING: PASS
FAULT TESTS: PASS
REAL RUN > FRAME 31990: PASS
REAL SOURCE BOUNDARY: PASS
EXACT OUTPUT FRAME COUNT: PASS
FORCED FULL STDOUT/STDERR BUFFER: NOT TESTED
EXACT 85574-FRAME USER PROJECT: NOT TESTED
PIXEL-EXACT BEFORE/AFTER: NOT PROVEN
AMD/NVIDIA/INTEL/CPU ISOLATION: PASS

FINAL STATUS: READY WITH DOCUMENTED TEST-SCOPE LIMITS
```
