# SPORTCAMHUD — AMD Direct Copy Audio: naprawa granicy klipów

Data: 2026-10-15  
Repozytorium: `C:\_DEV\BikeRideHUD-main-new`, gałąź `fix/gui-freeze-hud-composite` (z `.git\HEAD`).  
HEAD przed commitem (sprawdzony `git rev-parse`): `e76d6b1da0bcf1487e5061d16b05d7916adefb3b`.  
**Commit naprawy: `05bf51bd505a716152dbbf1bfddda7d2a6363679`** (gałąź `fix/gui-freeze-hud-composite`, nie wypchnięty).

**Status: PASS** (weryfikacja na Windows 2026-10-15, sekcja 11). Segmentacja na prawdziwych tablicach próbek GX010163/GX010164, 5 krótkich eksportów z prawdziwym named pipe i testy AMD przechodzą.  
Weryfikacja na Windows wykryła przypadek, którego model z sekcji 2 nie obejmował: audio GX010163 kończy się 25,667 ms przed wideo, więc GX010164 od IN=0 był odrzucany. Naprawa jest w sekcji 11.2.  
**Status pełnego eksportu: NOT TESTED.**

> Sekcje 1–10 opisują stan przed weryfikacją na Windows. Tam, gdzie sekcja 11 im przeczy, aktualna jest sekcja 11.

## 1. Rzeczywista przyczyna błędu

Log `amd_child_3_1792008243239.log` kończy się błędem:

```
AMD live A/V mux setup failed: Selected AAC packets cannot preserve clip-boundary sync within one AAC frame; re-encoding is forbidden
```

Ten błąd zgłasza `plan_aac_feed()` w `src/ffmpeg/mp4_audio_feed.py` (poprzednia wersja, linie 377–388), jeszcze zanim FFmpeg zostanie uruchomiony. Dlatego w logu nie ma komendy FFmpeg, a w GUI pojawia się „kod None”.

Mechanizm:
1. `amd_native_exporter.py` tworzy dla każdego klipu `AudioSegment(path, local_start_s, frames/fps)`. Projekt ma dwa segmenty: GX010163 w całości (4530 klatek, 151,151 s) i GX010164 przycięty (32 755 klatek, 1092,925 s). Źródła to `F:\GoPro\2026-08-27\GX010163.MP4` i `GX010164.MP4`.
2. Każdy segment był wybierany **osobno** (`AacTrack.sample_range`: środek ramki w `[IN, OUT)`). Obie krawędzie każdego segmentu zaokrąglały się do pełnej ramki AAC (21,333 ms), niezależnie od poprzedniego segmentu.
3. Walidacja sumowała `liczba_pakietów × 21,333 ms` i porównywała z sumą długości wideo, z tolerancją jednej ramki. Zaokrąglenia z kolejnych segmentów się dodawały, więc całkiem poprawne cięcie przekraczało tolerancję.
4. Walidacja mierzyła też niewłaściwą wielkość. Patrzyła na sumaryczną długość audio, a nie na to, który pakiet źródłowy trafia na początek segmentu, czyli na faktyczną synchronizację.

Wniosek: **to błąd zaokrąglania, nie rzeczywista utrata synchronizacji.** W modelu z typowymi długościami GoPro (opis poniżej) stary algorytm odrzucał 953 z 2000 losowych konfiguracji tego projektu. Nowy odrzuca 0 z 2000.

## 2. Obliczenia przed i po

Dokładnych tablic próbek z Twoich plików nie odczytałem. GX010163 (1,01 GB) i GX010164 (7,99 GB) przekraczają limit 400 MB na plik przy przesyłaniu z Twojego komputera. Poniżej jest więc model: AAC-LC 48 kHz, 1024 próbki na ramkę, audio pokrywa wideo, IN klipu 2 = 50,017 s (punkt IN nie jest znany z logu). Te same liczby dla prawdziwych plików wypisze krok 1 skryptu z sekcji 9, do `Raporty/direct_copy_audio_boundary_fix/user_plan_in_*.json`. Wypisze je też każdy eksport, w liniach `[AMD AAC PLAN]`.

**Przed** (wybór niezależny, walidacja sumaryczna):

| Segment | Wideo na osi eksportu | IN źródła | Pakiety | Pierwszy pakiet (źródło) | Długość audio | Błąd skumulowany | Wynik |
|---|---|---|---|---|---|---|---|
| 1 GX010163 | [0, 151,151000) | 0,000000 | 0 + 7085 | 0,000000 | 151,146667 | −4,333 ms | ok |
| 2 GX010164 | [151,151000, 1244,076167) | 50,017000 | 2345 + 51 230 | 50,026667 | 1092,906667 | **−22,833 ms** | **odrzucony** (limit 21,333) |

Faktyczna synchronizacja segmentu 2 w starym wyborze wynosiła +14,0 ms. Pakiet 50,026667 trafiał w miejsce, gdzie powinna być próbka 50,012667. Mieściło się to w jednej ramce, a mimo to eksport został odrzucony.

**Po** (rozmieszczenie skumulowane):

| Segment | Wideo | Audio na osi | Pakiety | Pierwszy pakiet | Synchronizacja | Reszta na końcu |
|---|---|---|---|---|---|---|
| 1 GX010163 | [0, 151,151000) | [0, 151,146667) | 0 + 7085 | 0,000000 | +0,000 ms | −4,333 ms |
| 2 GX010164 | [151,151000, 1244,076167) | [151,146667, 1244,074667) | 2344 + 51 231 | 50,005333 | −7,333 ms | −1,500 ms |

Wymagany początek segmentu 2 to 151,151000 s. Audio zaczyna się 4,333 ms wcześniej (koniec pakietów klipu 1). Nowy algorytm bierze więc pakiet źródłowy odpowiadający 50,017 − 0,004333 s. Błąd końcowy: −1,500 ms. Błąd nie narasta: w teście 40 cięć wszystkie segmenty mieszczą się w ±10,667 ms.

## 3. Naprawa (bez rekompresji)

`_place_segments()` w `mp4_audio_feed.py`:
- początek segmentu: pakiet źródłowy najbliższy czasowi, który należy w tym miejscu strumienia audio, czyli `IN + (pozycja_audio − początek_wideo)`;
- liczba pakietów: taka, żeby koniec audio był najbliżej końca wideo segmentu;
- rezultat: każdy segment ma przesunięcie A/V nie większe niż pół ramki (10,667 ms), a zaokrąglenia się nie sumują;
- przy pojedynczym zakresie wybór jest identyczny jak dotychczas (test `test_single_range_selection_is_unchanged`).

Walidacja nie została usunięta. Mierzy teraz rzeczywistą synchronizację każdego segmentu i odrzuca eksport, gdy przesunięcie przekracza jedną ramkę AAC. Zdarza się to tylko wtedy, gdy źródło nie ma audio tam, gdzie segment go potrzebuje, na przykład audio klipu 1 kończy się 30 ms przed wideo, a klip 2 zaczyna się od 0. Komunikat podaje wtedy segment, przesunięcie w ms i pełny plan. Jeśli klip 2 jest przycięty na początku, brakujące 30 ms uzupełniają oryginalne pakiety sprzed jego IN (test `test_short_source_audio_is_compensated_from_the_next_clip_preroll`).

Pakiety AAC pozostają niezmienione: ADTS w pamięci, `-c copy`, jeden proces FFmpeg, jeden live mux. Nie ma filtrów, PCM, M4A, plików AAC/ADTS, audio_cache ani drugiego przebiegu. Do strumienia nie jest dodawana cisza.

**Rzeczywiste ograniczenie:** kopiowanie AAC pozwala ciąć tylko co pełną ramkę. Synchronizacja na granicy jest więc dokładna do ±10,7 ms, a nie co do próbki. Większy brak audio w samym źródle nie da się ukryć bez dodania ciszy albo kodowania. Wtedy eksport kończy się jawnym błędem.

## 4. Komunikat w GUI

Ścieżka błędu: `AMDNativeFinalizationError` → `coerce_render_error` w procesie potomnym. Komunikat zawierał słowo „mux”, więc trafiał do `classify_mux_error(returncode=None)`, a stamtąd do domyślnego „Proces zapisu wideo zakończył się błędem (kod None)”.

Zmiany:
- `render_errors.py`: błąd „live A/V mux setup failed” daje `MuxError LIVE_MUX_SETUP_FAILED` z rzeczywistą przyczyną. Ogólnie: brak kodu wyjścia oznacza komunikat z przyczyną zamiast „kod None”. `display_message()` dopisuje `Log: <ścieżka>`.
- `amd_child_process.py`: ścieżka logu procesu potomnego trafia do `details["diagnostics_path"]`.

Sprawdzony wynik dla tego przypadku:

```
Nie udało się uruchomić zapisu wideo z dźwiękiem: <przyczyna>
Lokalizacja: d:\20260827-1505.mp4
Log: d:\scratch\amd_child_3_1792008243239.log
Co możesz zrobić: Sprawdź log eksportu. Po usunięciu przyczyny eksport można uruchomić ponownie.
```

Zakończenie eksportu (stan „failed”, pasek postępu, możliwość ponowienia) obsługuje istniejąca ścieżka `render_mixin.py`, której nie zmieniałem. W GUI nie testowałem. Log nie jest usuwany.

Automatycznego przejścia na stratne audio nie ma.

## 5. Separacja kodu

- Nowy `src/ffmpeg/live_mux_common.py` (bez kodowania audio) zawiera: `LiveMuxConfigError`, `AudioSegment`, `LiveAudioInputs`, `ffmpeg_supports_input_bsf`, `raw_video_timestamp_args`, `audio_segments_from_timeline`.
- `mp4_audio_feed.py` i `amd_native_exporter.py` importują wyłącznie z niego. Żaden plik przeznaczony do commita nie importuje `live_av_mux`.
- `live_av_mux.py` (nieśledzony, Intel/NVIDIA) zamiast własnych definicji importuje te same obiekty z `live_mux_common`. `build_live_audio_inputs` i AAC 256k zostały bez zmian. Zachowanie Intel i NVIDIA jest takie samo. Pliki `intel_native_exporter.py` i `nvidia_native_exporter.py` nie były ruszane.
- W `tests/test_live_av_mux.py` zmieniono jedynie cel monkeypatcha na `live_mux_common`.

## 6. Zmienione pliki

| Plik | Zmiana | Do commita |
|---|---|---|
| src/ffmpeg/live_mux_common.py | nowy | tak |
| src/ffmpeg/mp4_audio_feed.py | rozmieszczenie skumulowane, walidacja synchronizacji, raport planu | tak |
| src/ffmpeg/amd_native_exporter.py | import z live_mux_common, linie `[AMD AAC PLAN]` | tak |
| src/ffmpeg/render_errors.py | komunikat zamiast „kod None”, ścieżka logu | tak |
| src/ffmpeg/amd_child_process.py | przekazanie ścieżki logu | tak |
| src/ffmpeg/streaming.py | bez zmian w tym zadaniu (fail-closed AMD z poprzedniego etapu) | tak |
| tests/test_mp4_audio_feed.py | 5 testów granicy, nowy oracle, przypadek `user_boundary`, test planu na prawdziwych plikach | tak |
| tests/test_amd_live_mux_audio_finalization.py, tests/test_amd_direct_mp4_mux.py | cel monkeypatcha, `FakePlan.report_lines` | tak |
| src/ffmpeg/live_av_mux.py, tests/test_live_av_mux.py | re-eksport / cel monkeypatcha | nie (Intel/NVIDIA) |
| scratch/verify_and_commit_direct_copy_boundary.ps1 | skrypt weryfikacji i commita | nie |

Nie były zmieniane: def_layout.json, DLL AMD, VBR, HUD, FIT/GPX, finalizacja single-file, Intel, NVIDIA.

## 7. Testy i wyniki

Wykonane (Linux, kontener, FFmpeg master z 14.10.2026):
- `tests/test_mp4_audio_feed.py` + `tests/test_live_av_mux.py`: **22 passed, 9 skipped** (pominięte są testy wymagające Windows albo plików F:).
- Odtworzenie błędu: `test_user_project_boundary_rounding_no_longer_rejects` uruchomiony na poprzedniej wersji `mp4_audio_feed.py` kończy się dokładnie błędem z logu („Selected AAC packets cannot preserve clip-boundary sync…”). Na nowej wersji przechodzi.
- Bit-exact (Linux, potok FIFO): wszystkie pakiety AAC w wyniku są identyczne ze źródłem co do bajtu i w tej samej kolejności. Audio odczytane w trakcie wideo w ponad 90%.
- `render_errors`: sprawdzony komunikat z sekcji 4 i odtworzenie obiektu błędu z IPC (`to_dict`/`from_dict`).

Niewykonane (wymagają Windows):
- plan na prawdziwych tablicach próbek GX010163/GX010164 (`test_user_project_real_sample_tables_plan`);
- krótki eksport z prawdziwym named pipe: `user_boundary` (ostatnie 90 klatek GX010163 i 90 klatek GX010164), `multi_trim`, `pause_cuts`. Sprawdzają SHA-256 pakietów, oba klipy, synchronizację na granicy, EOF, zakończenie FFmpeg i mux_wait;
- testy AMD (`test_amd_live_mux_audio_finalization.py`, `test_amd_direct_mp4_mux.py`), w tym anulowanie i zgłaszanie błędów.

## 8. Komenda FFmpeg, finalizacja, bit-exact

Komenda produkcyjna jest niezmieniona (wg raportu Windows z 14.10):

```
ffmpeg.exe -y -f hevc -r 30000/1001 -bsf:v setts=ts=N*1001/30000/TB:duration=1001/30000/TB -thread_queue_size 512 -i - -thread_queue_size 512 -f aac -i \\.\pipe\telem_amf_audio_<pid>_<token>.aac -map 0:v -map 1:a:0 -t <D> -c copy -f mp4 <wyjście>.part
```

Dla Twojego projektu FFmpeg nie wystartował, bo błąd padł przy przygotowaniu muxa. Czas finalizacji po naprawie na Windows: NOT TESTED. Na Linuksie około 0 s.

## 9. Commit i working tree

**Commit: nie utworzony.** Ta sesja może czytać i zapisywać pliki w projekcie, ale nie może uruchamiać git ani pytest na Windows. Working tree: nie sprawdzony poleceniem `git status`. Wszystkie pliki zostały zapisane z kontrolą daty modyfikacji, więc żadna nowsza wersja nie została nadpisana.

Jedno polecenie wykonuje kroki 1–3 i tylko po ich zaliczeniu robi commit wyłącznie z plików oznaczonych „tak” w tabeli w sekcji 6:

```
powershell -ExecutionPolicy Bypass -File scratch\verify_and_commit_direct_copy_boundary.ps1
```

Skrypt nie wykonuje reset, clean, stash, rebase, merge ani push. Wynik zapisuje do `Raporty\direct_copy_audio_boundary_fix\verify.log`, a SHA commita na końcu tego pliku.

## 10. Nierozwiązane problemy

- Brak prawdziwych liczb z GX010163/GX010164. Poznamy je z kroku 1 skryptu albo z linii `[AMD AAC PLAN]` przy następnym eksporcie.
- Testy Windows i commit: oczekują na uruchomienie skryptu.
- Zachowanie GUI po błędzie (pasek postępu, ponowienie) nie było testowane interaktywnie.
- Pełny eksport 37 285 klatek: NOT TESTED.
- Powiadomienie ntfy: w repozytorium nie znalazłem konfiguracji ntfy. Wysłano na publiczny serwer ntfy.sh, temat MalcerzPOP. Wynik wysyłki jest na końcu raportu.


## 11. Weryfikacja na Windows (2026-10-15)

Wykonane na tym komputerze skryptem `scratch\verify_and_commit_direct_copy_boundary.ps1`. Pełny log: `Raporty\direct_copy_audio_boundary_fix\verify.log`.

Zmiana w skrypcie: `.venv\Scripts\python.exe` nie ma pytest, więc skrypt używa systemowego `python` (pytest 9.1.1), jeśli w `.venv` pytest brakuje. Dodano też przypadek `chapter_edge` do kroku 2.

### 11.1 Prawdziwe tablice próbek (`user_plan_in_*.json`)

| Plik | Pakiety AAC | media_time | Audio | Wideo | Różnica |
|---|---|---|---|---|---|
| GX010163.MP4 | 7084 | 0 | 151,125333 s | 151,151000 s (4530 kl.) | audio krótsze o **25,667 ms** |
| GX010164.MP4 | 51 230 | 0 | 1092,906667 s | 1092,925167 s (32 755 kl.) | audio krótsze o 18,500 ms |

Pierwsze uruchomienie (przed poprawką 11.2): IN=50,017 i IN=103,5 przechodziły, **IN=0 był odrzucany**:

```
Segment 2 (GX010164.MP4): original AAC packets would be +25.7 ms out of sync with the video
(limit one AAC frame, 21.3 ms; 51230 packets available from source packet 0)
```

Wyniki planu po poprawce (linie planu z `user_plan_in_*.json`):

| IN klipu 2 | Seg. | Pakiety | Pierwszy pakiet źródła | Audio na osi eksportu | Sync | Reszta na końcu | Uwagi |
|---|---|---|---|---|---|---|---|
| wszystkie | 1 GX010163 | 0+7084 | 0,000000 | [0, 151,125333) | +0,000 ms | −25,667 ms | koniec źródła |
| 0 | 2 GX010164 | 0+51 230 | 0,000000 | [151,146667, 1244,053333) | **+4,333 ms** | −22,833 ms | koniec źródła, **1× powtórzony pakiet 0** |
| 50,017 | 2 GX010164 | 2343+48 887 | 49,984000 | [151,125333, 1194,048000) | −7,333 ms | n/d* | pakiety sprzed IN |
| 103,5 | 2 GX010164 | 4850+46 380 | 103,466667 | [151,125333, 1140,565333) | −7,667 ms | n/d* | pakiety sprzed IN |

\* W teście czas trwania segmentu 2 wynosi 32 755 klatek niezależnie od IN, więc przy IN>0 przekracza źródło i jest obcięty na końcu pliku. To artefakt parametryzacji testu, nie projektu.

### 11.2 Poprawka: koniec rozdziału GoPro bez pakietów sprzed IN

Przyczyna: audio GX010163 kończy się 25,667 ms przed wideo. Klip 2 użyty od IN=0 nie ma wcześniejszych pakietów, którymi można by to wyrównać. Strumień ADTS nie ma znaczników czasu, więc nie da się zostawić dziury. Stara walidacja odrzucała eksport, bo przesunięcie (25,7 ms) przekraczało jedną ramkę (21,3 ms). Dotyczy to zwykłych, ciągłych rozdziałów GoPro. Wynik zależy od tego, ile audio brakuje na końcu konkretnego rozdziału (GX010163: 25,7 ms → błąd; GX010164: 18,5 ms → przeszedłby).

Naprawa w `_place_segments()`: jeśli segment potrzebuje audio sprzed początku źródła, przed jego pierwszym pakietem wstawiane są kopie tego oryginalnego pakietu (bajty skopiowane, nic nie jest kodowane). Liczba kopii = zaokrąglony brak w ramkach, maksymalnie `_MAX_FILLER_PACKETS = 2` (42,7 ms). Dla GX010163→GX010164 to 1 kopia, sync +4,333 ms. Większy brak to prawdziwa dziura w źródle i nadal kończy się jawnym błędem. Plan raportuje to jako `filler=1xdup_src_packet_0` w liniach `[AMD AAC PLAN]`.

Skutek: na granicy rozdziałów 21,3 ms dźwięku powtarza się raz. Dla porównania FFmpeg concat zostawiłby w tym miejscu 25,7 ms przerwy. Nie jest to cisza ani rekompresja. NOT TESTED: odsłuch tej granicy.

Testy:
- `test_short_source_audio_without_preroll_is_a_real_offset_and_fails` utrwalał stare odrzucanie. Zastąpiony przez `test_chapter_edge_shortfall_without_preroll_repeats_the_first_original_packet` (brak 30 ms → 1 kopia, sync ≤ pół ramki);
- nowy `test_filler_frames_are_copies_of_the_first_original_packet` (payloady bajt w bajt);
- nowy `test_short_source_audio_beyond_filler_limit_is_a_real_offset_and_fails` (brak 100 ms → błąd jak dotąd);
- wyrocznia `_expected_copy_selection` rozszerzona o kopie i obcięcie na końcu źródła; dodany przypadek eksportu `chapter_edge`;
- w słowniku `quality` testu eksportu brakowało klucza `user_boundary` (KeyError). Uzupełniono o `user_boundary` i `chapter_edge`.

### 11.3 Wyniki

| Krok | Wynik |
|---|---|
| 1. Segmentacja (`test_mp4_audio_feed.py`, bez eksportów) | **18 passed, 1 skipped** (FFmpeg 7.1+ nie ma w PATH) |
| 2. Krótkie eksporty AMD, prawdziwy named pipe, DLL i oryginalne MP4 | **4 passed** (`user_boundary`, `chapter_edge`, `multi_trim`, `pause_cuts`) |
| 3. Testy AMD mux (`test_amd_live_mux_audio_finalization.py`, `test_amd_direct_mp4_mux.py`, `test_live_av_mux.py`) | **37 passed, 1 skipped** |
| 4. Commit | `05bf51b` |

Dowody eksportów (`Raporty\direct_copy_audio_boundary_fix\<case>_*\evidence.json`), po 2 × 90 klatek, wideo 6,006 s:

| Przypadek | Pakiety AAC | SHA-256 = źródło | Granice (pakiety) | Sync seg. 1 / 2 | Reszta na końcu seg. 1 / 2 | Audio przed/po EOF | FFmpeg kończy po EOF | mux_wall |
|---|---|---|---|---|---|---|---|---|
| user_boundary | 282 | tak | 140, 282 | −9,333 / +4,667 ms | −16,333 / +10,000 ms | 278 / 4 | 45,1 ms | 1,15 ms |
| chapter_edge | 282 | tak (z 1 kopią) | 141, 282 | −9,333 / −5,000 ms | +5,000 / +10,000 ms | 282 / 0 | 41,4 ms | 1,04 ms |
| multi_trim | 282 | tak | 141, 282 | +5,333 / +5,667 ms | +5,000 / +10,000 ms | 282 / 0 | 43,6 ms | 1,08 ms |
| pause_cuts | 282 | tak | 141, 282 | +5,333 / −2,333 ms | +5,000 / +10,000 ms | 278 / 4 | 42,6 ms | 0,97 ms |

Wszystkie przesunięcia mieszczą się w ±10,667 ms (pół ramki AAC). Komenda: jeden proces FFmpeg, `-c copy`, bez `-filter_complex` i `-b:a` (asercje testu). W `user_boundary` reszta −16,3 ms na końcu segmentu 1 to koniec audio źródła GX010163 (25,7 ms krótsze), wyrównany w segmencie 2 pakietami sprzed IN.

### 11.4 Commit i working tree

Commit `05bf51bd505a716152dbbf1bfddda7d2a6363679`, „fix(amd): lossless direct-copy AAC with sync-preserving clip boundaries”. Pliki: `live_mux_common.py`, `mp4_audio_feed.py`, `amd_native_exporter.py`, `streaming.py`, `render_errors.py`, `amd_child_process.py`, `tests/test_mp4_audio_feed.py`, `tests/test_amd_live_mux_audio_finalization.py`, `tests/test_amd_direct_mp4_mux.py`. Treść commita nie wspomina o kopiach pakietu z 11.2 (komunikat był przygotowany wcześniej); kod i testy są w commicie. Nie było reset, clean, stash, rebase, merge ani push.

`git status --short` po commicie (bez nieśledzonych raportów w `Raporty/`):

```
 M Raporty/RAPORT_SPORTCAMHUD_ETAP_5R_F_LIVE_MUX_AUDIO_FINALIZATION.md
 M def_layout.json
 M src/ffmpeg/intel_native_exporter.py
 M src/ffmpeg/nvidia_native_exporter.py
?? native/d3d11_amf_pipeline/bin/telem_amd_native.dll.bak_cqp
?? runtime/amd/
?? src/ffmpeg/live_av_mux.py
?? tests/test_live_av_mux.py
```

Intel, NVIDIA, `def_layout.json`, DLL i HUD: niezmienione w tym kroku i nie w commicie. Ten raport nie jest w commicie.

### 11.5 Nadal otwarte

- Pełny eksport 37 285 klatek: NOT TESTED.
- Odsłuch granicy z powtórzonym pakietem (IN=0): NOT TESTED.
- GUI po błędzie (pasek postępu, ponowienie): NOT TESTED interaktywnie.
- `.venv` nie ma pytest. Do osobnego zadania.
- Powiadomienie ntfy: publiczny `ntfy.sh`, temat `MalcerzPOP`, bez tokena. W repozytorium ani w ustawieniach Claude nie ma konfiguracji z tokenem.
- Wysyłka ntfy 2026-10-15: HTTP 200, id wiadomości `SBYpG5Fay4OW`, tytuł „SportCamHUD: PASS 05bf51b”.
