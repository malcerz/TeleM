# SportCamHUD — Intel D3D11/QSV: pomiar pipeline i optymalizacja, 2026-10-19

STATUS: poprawka startu workerów HUD wdrożona i zmierzona (+6.2 FPS mediany z pełnym HUD, bitstream identyczny).
Cel 55 FPS (mediana, pełny HUD, 1800 klatek): **NIE OSIĄGNIĘTY** w warunkach pomiaru (laptop na baterii z ograniczeniem mocy) — mediana 52.6 FPS, zakres 51.0–57.3. 60+ FPS: **NOT PROVEN** (patrz §13). Push: nie wykonano.

## 0. Zadanie, stan początkowy, warunki

- Repo `C:\_DEV\SportCamHUD`, gałąź `main`, HEAD przed zmianą `a32d854`. Przeczytano AGENTS.md, BENCHMARKS.md, poprzedni raport `RAPORT_USUNIECIE_QP_INTEL_WYDAJNOSC_20261019.md`.
- Zastana praca zachowana bez zmian i poza commitem: `M def_layout.json`, nieśledzone `C`, `RAPORT_INTEL_HEVC_SLICE_QP_20261017.md` (root), font PL, kopie `*.bak*` DLL.
- Sprzęt: i7-1265U / Iris Xe (sterownik 32.0.101.7085), oneVPL runtime 2.15 (API 2.17).
- **Zasilanie: przez cały czas pomiarów laptop pracował na baterii** (`PowerLineStatus=Offline`, od 100% do 30%). Od ok. 77% system wchodził okresowo w ograniczenie mocy (pobór systemu ~15 W zamiast 24–27 W, CPU perf 35%, temp. ~30°C) i stan ustalony spadał z ~63 do ~50–56 FPS. To jest udokumentowana przyczyna wcześniej obserwowanego rozrzutu 37–53 FPS. W tle działały Chrome/ChatGPT/codex (aplikacje użytkownika, nie zamykano ich).
- Dlatego wszystkie porównania przed/po są **parami naprzemiennymi w tym samym oknie czasu**; wyników z różnych faz baterii nie porównuję bezpośrednio.

## 1. Materiał i parowanie

- Główny materiał: `C:\GoPro\2026-10-16\GX010381.MP4`, 1800 klatek.
- FIT dla wariantów z HUD: `C:\GoPro\2026-10-16\2026-10-16_13-06-05.fit` — **parowanie wzięte z projektu użytkownika `C:\GoPro\GX010381.toproj`** (footage GX010381 + data 2026-10-16_13-06-05.fit), nie zgadywane z nazw/dat. Para nie jest w BENCHMARKS.md (kanoniczne `Video/GX0200xx` nie istnieją na tej maszynie); zgłaszam ją jawnie.
- Para kontrolna z poprzednich raportów (macierz jakości): `C:\GoPro\GX010378.MP4` + `C:\GoPro\2026-10-15_15-03-50.fit` (para zapisana w istniejącym harnessie).
- Layout pełnego HUD: `Raporty/intel_vbr_qp_20261017/layout.json` (18 aktywnych wskaźników, w tym mapa, wykresy HR/kadencji, gauge, kompas) — ten sam co w poprzednich raportach. „Bez HUD” = ten sam layout z `enabled=false` dla każdego wskaźnika (`layout_no_hud.json` w katalogu przebiegu).

## 2. Faktyczne parametry dekodowania i kodowania

Źródło (ffprobe): HEVC Main 10, `yuv420p10le`, 3840×2160, 30000/1001, `color_range=pc`, BT.2020nc / BT.2020 / `arib-std-b67` (HLG), Display Matrix rotacja −180°, AAC 48 kHz stereo, GPMF.

Ścieżka 10-bit native potwierdzona z logów, nie tylko z `-profile`: dekoder D3D11VA tekstura `Fmt=104` (DXGI P010), wyjście VP P010, powierzchnia enkodera `Format=104` (P010), FourCC enkodera P010, `Shift=1`, BitDepth 10.

| Parametr (zaakceptowany przez sterownik) | FFmpeg A (`hevc_qsv`, log enkodera) | SportCamHUD native (`GetVideoParam`) |
|---|---|---|
| Profil | main10 | MAIN10 |
| TargetUsage | 7 | 7 |
| RateControl | VBR | VBR (rc=2) |
| Target / Max | 40000 / 50000 kbps | 40000 / 50000 kbps |
| BufferSizeInKB / InitialDelayInKB | 10000 / 5000 (80 / 40 Mbit) | 10000 / 5000 |
| BRCParamMultiplier | 1 | 1 |
| NalHrdConformance / VuiNalHrd | ON / ON | ON / ON (16/16) |
| GopPicSize / GopRefDist | 60 / 1 (wymuszone `-g 60 -bf 0`) | 60 / 1 |
| IdrInterval | 1 (każde I = IDR, FFmpeg dodaje +1 dla HEVC) | 0 (dla HEVC: tylko pierwsze I = IDR) |
| AsyncDepth | 4 | 8 |
| LowPower | nie ustawiane (domyślne) | nie ustawiane (domyślne) |

Wyjścia (ffprobe): oba HEVC Main 10, `yuv420p10le`, pc, BT.2020/HLG, 30000/1001, 1800 klatek, rotacja −180°, I co 60 klatek, pozostałe ramki GPB („B” bez przestawiania) — struktura identyczna. Różnica IdrInterval i AsyncDepth nie zmienia jakości, opisana dla porządku. Uwaga: w wariancie A audio kopiowane w całości (`-frames:v` nie przycina audio; 71 s) — koszt pomijalny, ale wynik A nie jest pełnym odpowiednikiem eksportu A/V.

## 3. Benchmark bez HUD i z HUD (identyczny materiał)

Narzędzie: `tools/benchmark_intel_qsv_pipeline.py` (uruchamia kanoniczny harness `SportCamHUD.py --test-intel-export`, nie zmienia renderingu; zbiera liczniki). Warianty: A = FFmpeg QSV decode→`hevc_qsv` bez HUD; B = native bez HUD; B0 = native `TELEM_INTEL_PACKAGE_MODE=VIDEO_ONLY` (diagnostyczny); C = native pełny HUD; D = ścieżka FFmpeg SportCamHUD bez HUD.

Faza bazowa (bateria 100→63%, przed zmianą):

| Wariant | Przebiegi render FPS | Mediana | Stan ustalony 500–1500 | 1. klatka |
|---|---|---|---|---|
| A FFmpeg | 67.4, 64.7, 68.7, 69.3 | 68.1 | – | – |
| B native bez HUD | 57.4, 50.1, 58.0, 43.6 | 53.8 | 62.9–63.3 | 2.6–9.1 s |
| B0 VIDEO_ONLY | 63.6 | – | 62.9 | 0.007 s |
| C pełny HUD (bateria 95–83%) | 39.6, 56.2, 60.2 | 56.2 | 63.3–70.4 | 2.7–11.4 s |
| C pełny HUD (po spadku mocy, 77–56%) | 34.5, 39.0, 39.9, 35.2, 38.7, 44.9 | 39.0 | 49.8–56.2 | 5.9–11.3 s |
| D FFmpeg path bez HUD | 11.7 (efektywne harnessu) | – | 14.0 | – |

- B0 dał 1799 klatek zamiast 1800 (walidacja harnessu FAIL). To tryb diagnostyczny spoza produkcji; anomalia zapisana do osobnego zbadania, nie użyto go jako „bez HUD”.
- D wykonano raz (ok. 3 min/przebieg); ścieżka FFmpeg SportCamHUD jest ~5× wolniejsza od native i nie była przedmiotem optymalizacji. 3 powtórzenia D: NOT TESTED.
- **C_r3 zawiesił się** na klatce 100 na >15 min (proces zabity przez watchdog narzędzia; brak zrzutu faulthandlera). Ostatni ślad: start 4. workera HUD po pierwszej klatce. W 20+ pozostałych przebiegach C nie wystąpiło. Przyczyna: **NOT PROVEN** — do osobnego zadania (watchdog narzędzia skrócono do 300 s, aby kolejne wystąpienie dało zrzut stosu).

Wniosek: w stanie ustalonym native z pełnym HUD osiąga to samo ~63 FPS co bez HUD; różnica wobec FFmpeg i rozrzut wyników pochodzą głównie (1) z czasu startu przed pierwszą klatką i wolnego rozbiegu, (2) z warunków zasilania.

## 4. Koszt etapów pipeline (finalny przebieg C_r22, na klatkę)

Czasy CPU po stronie wywołań (nie czas pracy GPU). Etapy nakładają się — **nie sumować**.

| Etap | Wątek | ms/klatkę | Charakter |
|---|---|---|---|
| Demux | producent | 0.25 | CPU |
| Decode D3D11VA (submit/receive) | producent | 2.34 | CPU submit, równolegle z konsumentem |
| Kolejka decode → konsument | konsument | 0.000 | dekoder zawsze wyprzedza |
| HUD Wait (future workera) | konsument | 0.58 | |
| Upload HUD (UpdateSubresource, 6 regionów, 9.72 MB) | konsument | 2.69 | CPU + praca GPU |
| VideoProcessorBlt (submit) | konsument | 1.52 | praca GPU asynchroniczna |
| CopyResource VP→enkoder (submit) | konsument | 0.32 | praca GPU asynchroniczna |
| **Oczekiwanie na wolny slot enkodera** (nowy licznik) | konsument | **10.80** | CPU czeka na GPU |
| GetSurfaceForEncode (nowy licznik) | konsument | 0.016 | |
| EncodeFrameAsync | konsument | 0.12 | CPU submit |
| SyncOperation | drain | 17.73 | CPU czeka; nakłada się na całą resztę |
| Zapis bitstreamu do potoku live-mux (nowy licznik) | drain | 0.14 | |
| Finalizacja | – | 0.22 s łącznie | |

Max pending encode surfaces = 8 (= AsyncDepth/watermark). Konsument przez ~2/3 czasu czeka na slot enkodera, a dekoder i HUD nie są ograniczeniem w stanie ustalonym → pipeline jest ograniczony przez GPU (enkoder + praca 3D), nie przez CPU, kolejki czy zapis.

Wykorzystanie silników GPU (PDH `GPU Engine`, suma procesów, mediana środkowej połowy aktywnego okna):

| Wariant | 3D | VideoProcessing | VideoDecode (2× VDBox) | FPS w oknie |
|---|---|---|---|---|
| A FFmpeg | 63–67% | 0% | ~60% | ~68 |
| B native bez HUD | 81–85% | ~12% | ~58–75% | ~63 |
| C native pełny HUD | 90–97% | 12–14% | ~57–68% | ~56–63 |

- Sterownik nie udostępnia silnika „VideoEncode”: koder pracuje na VDBox raportowanym jako `VideoDecode` (eng 1 i eng 4). Wcześniejsze raporty mylnie wnioskowały „brak licznika” — nie należy go raportować jako 0%; tu podaję VDBox łącznie (dekod + enkod).
- Taktowania GPU, mocy GPU i limitów mocy GPU: **NOT AVAILABLE** (brak liczników bez narzędzi Intel/administratora). Dostępne: pobór całego systemu z baterii (WMI `DischargeRate`), temperatura strefy ACPI, częstotliwość/perf CPU — zapisane w `measurement.json` każdego przebiegu.
- Enkoder HEVC TU7 sam zużywa ~9.6 ms pracy silnika 3D na klatkę (A: 65% przy 68 FPS). Native dokłada VP Blt (~+20 pp 3D) i upload HUD (~+10 pp). Przy 90–97% 3D to silnik 3D jest wąskim gardłem w stanie ustalonym.

## 5. Diagnoza CopyResource

- A/B. Bezpośredni zapis VP do powierzchni enkodera nie działa, bo wewnętrzne powierzchnie oneVPL mają `Bind=0x208` (SHADER_RESOURCE|DECODER), `Misc=0x900` (SHARED_NTHANDLE|SHARED_KEYEDMUTEX) i **brak RENDER_TARGET** → `CreateVideoProcessorOutputView` zwraca `E_INVALIDARG (0x80070057)`. To wymóg D3D11 (widok wyjściowy VP wymaga RT), nie błąd allocatora aplikacji.
- C/D. Sprawdzone eksperymentalnie (sonda 6 kombinacji, 60 klatek, każda zakończona poprawnym MP4 dzięki fallbackowi):
  - Tekstura P010 z `RENDER_TARGET|DECODER` — D3D11 odrzuca (`E_INVALIDARG`). Jedna tekstura nie może być jednocześnie wyjściem VP i natywną powierzchnią enkodera.
  - `mfxMemoryInterface::ImportFrameSurface(ENCODE, IMPORT_SHARED)` z tekstury RT (MISC SHARED, NTHANDLE|SHARED, NTHANDLE|KEYEDMUTEX) — zawsze `MFX_ERR_MEMORY_ALLOC (-4)` w runtime 2.15.
  - Pozostaje zewnętrzny allocator (legacy `SetFrameAllocator`) — nie wdrożony, bo pomiar poniżej pokazał brak zysku na wąskim gardle.
- Czy kopia obciąża wąskie gardło? Diagnostyczny przebieg z pominiętą kopią (`C_SKIP`, obraz celowo niepoprawny) pokazał, że **całe ~12% obciążenia silnika VideoProcessing pochodzi z CopyResource P010**, a obciążenie 3D pozostaje ~90%. Kopia wykonuje się na VEBOX, równolegle do nasyconego silnika 3D, więc jej usunięcie nie odciąży ograniczenia. FPS z C_SKIP odrzucono jako miarę (enkoder kodował niezapisane powierzchnie — Encode Sync spadł z ~18 do 5–10 ms, czyli inna treść).
- Znaleziony ukryty błąd: warunek kopii `if (pTargetOutView != pEncTex)` porównywał wskaźnik widoku z teksturą — zawsze prawda. Gdyby bezpośredni widok kiedykolwiek się udał, CopyResource nadpisałby świeży kadr nieaktualną klatką z pierścienia. Poprawiono na jawną flagę `direct_view_used` (na tym sprzęcie bez zmiany zachowania — bezpośredni widok zawsze się nie udaje).
- Kod eksperymentu zero-copy **nie wszedł do commitu** (brak udowodnionej korzyści, nie działa na tym sterowniku); źródło eksperymentu zachowano w scratchpadzie sesji, wyniki sondy w `intel_qsv_pipeline_20261019/zc_probe3/`.

## 6. Równoległość Decode / VP / HUD / Encode

- Dekoder działa w osobnym wątku z pierścieniem 4 klatek; konsument nigdy na niego nie czeka (Queue Wait 0.000 ms).
- HUD renderują 4 procesy z prefetchem 8; w stanie ustalonym HUD Wait ~0.1–0.6 ms.
- Enkoder: 8 klatek w locie, osobny wątek drain synchronizuje najstarszą. Synchronizacja nie odbywa się per klatka w wątku konsumenta — konsument czeka tylko, gdy kolejka jest pełna (to jest zamierzony backpressure, a nie przypadkowa serializacja).
- **Przypadkowa serializacja znaleziona po stronie startu HUD**: `ProcessPoolExecutor` (spawn) wysyłał każdemu workerowi 41 MB spiklowanych `initargs` przez potok. Rodzic blokował się w `submit()` do czasu, aż dziecko uruchomi interpreter, zaimportuje moduły i odczyta dane (~1.5–2.4 s/worker). Workery startowały jeden po drugim, a wątek główny był zablokowany przed pierwszą klatką i w pierwszych klatkach pętli (4. worker). Ślad (`TELEM_HUD_STARTUP_TRACE=1`): worker N+1 tworzony dopiero w chwili, gdy worker N kończy start; klatka 0 HUD gotowa po 2.1 s, pierwsza klatka eksportu dopiero po ~5 s.
- Zwiększanie AsyncDepth lub głębokości kolejek nie pomoże: ograniczeniem jest nasycony silnik 3D, a nie zbyt mała liczba klatek w locie.

## 7. Wprowadzona optymalizacja

Wybrane wąskie gardło: szeregowy start workerów HUD (zmierzony: 41 MB initargs na workera, serializacja spawn).

- `src/ffmpeg/shared_memory.py`: `WorkerInitBlob` — initargs piklowane **raz** do jednego bloku `SharedMemory`; `_init_worker_with_shm_blob` odczytuje je w workerze i woła dotychczasowy `_init_worker_with_shm` z identycznymi argumentami. Ślad startu włączany zmienną `TELEM_HUD_STARTUP_TRACE=1` (domyślnie wyłączony).
- `src/ffmpeg/intel_native_exporter.py`: eksport Intel native używa bloba domyślnie; `TELEM_INTEL_HUD_INIT_BLOB=0` przywraca starą ścieżkę; błąd tworzenia bloba → automatyczny fallback ze starą ścieżką i logiem. Blob zamykany przez istniejący `ExitStack` (także przy anulowaniu/błędzie).
- Natywna DLL Intel (instrumentacja, bez zmiany pipeline): nowy eksport `intel_native_pipeline_get_stage_timing` (osobna struktura 32 B; ABI `IntelNativePipelineStats` 752 B bez zmian) z licznikami oczekiwania na slot enkodera, `GetSurfaceForEncode` i zapisu bitstreamu; poprawka warunku CopyResource (§5).
- Wynik po zmianie: workery tworzone w ciągu ~40 ms, init ~0.7 s, klatki 0–3 gotowe niemal jednocześnie.

## 8–9. FPS przed i po (pary naprzemienne, ta sama faza baterii)

A/B samej poprawki (ta sama DLL kandydat, bateria 48→44%):

| | 1. klatka | Render FPS | Czas całkowity |
|---|---|---|---|
| C NOBLOB (stara ścieżka) | 4.76, 4.77, 4.75 s | 47.8, 49.1, 47.9 | 39.6, 38.6, 39.5 s |
| C BLOB (nowa) | 2.43, 2.15, 2.13 s | 54.0, 49.1, 53.6 | 35.3, 38.6, 35.5 s |

Przed vs po (stara Python-ścieżka + stara DLL vs finalny kod + finalna DLL; A/C/B naprzemiennie ×3; bateria 42→30%):

| Wariant | Mediana render FPS | Zakres | Mediana efektywne FPS | Mediana czas | Mediana 1. klatki | Mediana stanu ustalonego |
|---|---|---|---|---|---|---|
| A FFmpeg | 61.5 | 61.3–65.1 | 61.5 | 29.3 s | – | – |
| C przed | 46.4 | 44.4–49.7 | 44.8 | 40.2 s | 3.56 s | 55.0 |
| **C po** | **52.6** | 51.0–57.3 | 50.6 | 35.6 s | 2.23 s | 56.2 |
| B przed | 50.0 | 49.2–50.4 | 47.5 | 37.9 s | 3.53 s | 54.4 |
| B po | 53.6 | 51.4–56.4 | 51.1 | 35.2 s | 1.61 s | 56.2 |

Zysk mediany z pełnym HUD: +6.2 FPS (+13%), −4.6 s na 1800 klatek. Zysk pochodzi ze startu; stan ustalony (ograniczony przez GPU) się nie zmienił — zgodnie z diagnozą. Pierwsza próba kompilacji DLL nałożyła się na przebieg `cand_C_NOBLOB_r1` (wynik zgodny z r2/r3, pozostawiony).

## 10. Jakość obrazu i audio

- SHA256 pakietów wideo i audio (ffmpeg `-c copy -f hash`) — **identyczne** we wszystkich przebiegach pełnego HUD: stara DLL, DLL kandydat (w tym fallback zero-copy), blob ON i OFF, finalna DLL: wideo `fbbd3c0bc71a812d…`, audio `d7acdb75cad9b269…`; bez HUD wideo `335f40b561c1dfdd…`. Bitstream się nie zmienił, więc HUD, mapa, wykresy i jakość są bitowo identyczne.
- Audio: live mux z oryginalnego MP4 (`audio_live_mux=True`), bez `ensure_audio_cache`, bez plików pośrednich audio. Zgodność długości A/V < 0.1 s (walidacja harnessu).
- Nie zmieniano: CQP/QP (nie przywracano), presetów, VBR/VBV/HRD, HLG/HDR, layoutu, jakości HUD, podglądu 5 FPS.

## 11. Testy regresyjne

- Testy celowane (Intel ×40 plików, SHM zero-copy, izolacja runtime, SmartSync, presety synchronizacji, profile enkodera, capability, async pipeline, live mux): **317 passed, 7 skipped, 2 failed, 1 collection error** (`pytest_targeted.log`).
  - `test_intel_av1_quantizer.py`: błąd importu `IntelCompressionTracker` — klasa usunięta w poprzednim commicie 98848d7 (usunięcie QP). Zastane, niezwiązane.
  - `test_intel_native_8b/8c ..._codec_selector`: lista kodeków w zakładce Render GUI vs capability sprzętu. Nie dotykałem GUI ani capability; zastane niezwiązane — **NOT PROVEN** uruchomieniem na HEAD (bez worktree/stash, zgodnie z zasadami).
- Nowe `tests/test_intel_hud_init_blob.py`: 3 passed (wierny round-trip initargs, idempotentne zamknięcie, rozmiar struktury vs eksport DLL).
- Macierz jakości Intel (`tools/run_intel_vbr_matrix.py`, 60 klatek, GX010378): **12/12 PASS** — native/FFmpeg × HEVC/H264 × Fast/Balanced/Quality.
- Python Portable 3.14.7: **PASS** — native HEVC Fast, pełny HUD, GX010381, 300 klatek, blob ON, workery startują równolegle.
- Tryb kolejki (queue), pełny HUD, 120 klatek: **PASS**.
- compileall, pyflakes nowych plików, `git diff --check`: PASS.
- Eksport wieloplikowy (rzeczywisty): **NOT TESTED** (brak kanonicznego zestawu `Video/GX010114–116` na tej maszynie; zmiana jest ogólna i nie dotyczy logiki klipów).
- Anulowanie w trakcie eksportu z blobem: **NOT TESTED** ręcznie (sprzątanie przez istniejący ExitStack).
- GUI ręcznie, podgląd 5 FPS: **NOT TESTED** (nie zmieniano kodu GUI/podglądu).
- AMD/NVIDIA: **NOT TESTED** (brak sprzętu). Izolacja: zmiany natywne tylko w DLL Intel; w `shared_memory.py` dodano klasę i inicjalizator używane wyłącznie przez eksporter Intel oraz ślad wyłączony domyślnie — ścieżki AMD/NVIDIA nie zmieniają zachowania.

## 12. Zmiany i commit

- `src/native/intel/d3d11_intel_pipeline/telem_intel_native.c` — instrumentacja etapów, eksport `intel_native_pipeline_get_stage_timing`, poprawka warunku CopyResource.
- `runtime/intel/bin/telem_intel_native.dll` — przebudowana tym samym LLVM-MinGW/FFmpeg/oneVPL (`-O2 -mavx2 -mfma`), SHA256 `1eb0f4788c426c651da91fcfb8c8a141db3a284179db73df7ad8ca38eb31fba5`, źródło `9904013215c2…`; manifest budowy `intel_qsv_pipeline_20261019/intel_native_final_build_manifest.json`. Poprzednia DLL: `runtime/intel/bin/telem_intel_native.dll.bak_before_qsv_perf_20261019` (nieśledzona).
- `runtime/runtime_manifest.json`, `tools/build_portable_release.py` — nowy hash DLL.
- `src/ffmpeg/shared_memory.py`, `src/ffmpeg/intel_native_exporter.py` — blob initargs, licznik etapów w podsumowaniu, ślad startu.
- `tests/test_intel_hud_init_blob.py`, `tools/benchmark_intel_qsv_pipeline.py`.
- Dowody: `Raporty/intel_qsv_pipeline_20261019/*/measurement.json`, `samples.json`, `export.log`, `battery.csv`, podsumowanie `final_ab_summary.json`. Pliki MP4 (~14 GB) nie są w Git.
- Commit lokalny: SHA w odpowiedzi końcowej. Nie wykonano push.

## 13. Czy 55 FPS i czy 60+ FPS jest możliwe

- 55 FPS mediany z pełnym HUD: **NIE OSIĄGNIĘTO** w tych warunkach (52.6; najlepszy przebieg 57.3). Pomiar wykonano wyłącznie na baterii z ograniczeniem mocy, więc wynik na zasilaczu jest **NOT TESTED**. W fazie wysokiej baterii stara wersja osiągała już 56–60 FPS w części przebiegów, a stan ustalony wynosił ~63 FPS, więc 55+ na zasilaczu jest prawdopodobne, ale **NOT PROVEN**.
- 60+ FPS z pełnym HUD: ograniczeniem stanu ustalonego jest silnik 3D (90–97%); enkoder HEVC TU7 sam zajmuje ~65% przy 68 FPS, VP Blt i upload HUD dokładają resztę. Dalsze kroki, każdy jako osobne zadanie z pomiarem:
  1. Zmniejszenie bajtów uploadu HUD (dziś 9.72 MB/klatkę = 66% płótna, mimo że zmieniają się głównie cyfry) — wymaga dowodu parytetu pikseli.
  2. Dalsze skrócenie startu (pozostałe ~2 s: piklowanie 41 MB, start interpretera) — np. odchudzenie initargs.
  3. Tryb LowPower (VDEnc) enkodera odciążyłby EU/3D, ale zmienia tryb kodowania i wymaga osobnej oceny jakości — nie zmieniano.
  4. Zero-copy VP→enkoder nie odciąży 3D (kopia działa na VEBOX) — niski priorytet.
  5. Zawieszenie C_r3 i 1799 klatek w VIDEO_ONLY — do zbadania.
- Kosmetyka zauważona: podsumowanie wypisuje „HUD Upload Mode: FULL_UPLOAD”, choć 1799/1800 klatek idzie jako partial (etykieta zależy od zmiennej środowiskowej) — nie poprawiano (poza zakresem).

## Podsumowanie PASS/FAIL

| Kryterium | Wynik |
|---|---|
| Porównanie FFmpeg vs SportCamHUD na tym samym materiale | PASS |
| Faktyczne parametry enkodera zgodne (TU7, VBR 40/50, VBV 10000/5000 KB, HRD, Main10/P010, HLG) | PASS |
| Diagnoza CopyResource / równoległości | PASS (zero-copy niemożliwe na tym sterowniku; kopia nie obciąża wąskiego gardła) |
| Poprawka z udowodnioną korzyścią | PASS (+6.2 FPS mediany, −2.6 s startu w A/B) |
| Bitstream / HUD / audio identyczne | PASS |
| Macierz jakości 12/12, Portable 3.14, kolejka | PASS |
| 55 FPS mediany z pełnym HUD | FAIL (na baterii) / NOT TESTED (na zasilaczu) |
| 60+ FPS | NOT PROVEN |
| AMD/NVIDIA, wieloplikowy, GUI ręcznie | NOT TESTED |
