# SportCamHUD — usunięcie diagnostyki QP, 2026-10-19

STATUS: diagnostyka QP usunięta z produkcyjnego eksportu; cel >55 FPS NIE OSIĄGNIĘTY w końcowym pomiarze. Walidacja sprzętowa Intel PASS, AMD/NVIDIA GPU NOT TESTED. Nie wykonano push.

## 1. Zadanie i stan początkowy
Istniejący C:\_DEV\SportCamHUD, main, HEAD aa42e65cf8231f80d13c077bfc6db561bb1f2a61. Przeczytano AGENTS.md i BENCHMARKS.md. Stan źródeł sprzed zadania pozostaje w historii Git; poprzedni merge 482e943 zachowuje obie historie. Poprzedni bundle SportCamHUD_reconciled_20261019.bundle pozostaje nienaruszony.
Prywatny def_layout.json: font Digital-7 Mono PL, amd_hdr_mode=preserve_hlg, auto_activity_source=garmin. Nie zatwierdzano tego pliku. Zachowano C, pusty raport w root, font PL oraz zastane kopie DLL. Nie tworzono gałęzi, worktree ani kopii projektu; buildy kandydatów i artefakty są w istniejącym repo.

Przed nadpisaniem runtime zapisano osobne kopie:
- runtime/intel/bin/telem_intel_native.dll.bak_before_qp_removal_20261019
- runtime/amd/bin/telem_amd_native.dll.bak_before_qp_removal_20261019
Żadnej wcześniejszej kopii nie nadpisano ani nie usunięto.

## 2. Jak działało QP i jaki był narzut
Intel C czytał oneVPL encoded-frame-info, dołączał rozszerzenie mfxExtAVCEncodedFrameInfo do slotów bitstreamu i wykonywał record_slot_qp po SyncOperation. H264 agregował QP, AV1 miał własny parser base_q_idx. HEVC dodatkowo skanował NAL, usuwał emulation-prevention bytes i parsował SPS/PPS/slice headers. Tworzył agregaty per-frame/per-typ i chronił statystyki critical section; wykonywał cross-check z oneVPL i opcjonalny trace.
CABAC NIE był dekodowany w produkcyjnej ścieżce. Eksperymentalne narzędzia scratch/hevcqp i src/qp_analyzer były osobne. Produkcyjny eksport ich nie uruchamiał; podczas audytu nie znaleziono procesu hevcqp. Nie przypisano spadku FPS dekodowaniu CABAC, którego tam nie było.

Python IntelCompressionTracker wykonywał sprawdzenie czasu przy każdym raporcie klatki, polling zwykłych statystyk do 2 Hz i osobny odczyt HEVC Slice QP przy raportach progress. Kopiował słowniki, agregaty i teksty. Harness odkładał słownik QP dla kolejnych numerów klatek. FFmpeg Intel/NVIDIA przetwarzał stream_0_0_q. GUI rozwiązywało pola QP, formatowało je w progress, kolejce i popupie.
AMD wykonywał per-surface request STATISTICS_FEEDBACK i cztery odczyty właściwości wyjściowych AMF oraz agregację. Python odczytywał te statystyki przy progress/finalizacji. NVIDIA native gromadził frameAvgQP, histogram i wektor próbek, opcjonalnie CSV; Python odpytywał je w pętli postępu.

Z bazowego przebiegu: HEVC parser 113.294 mikrosekundy/klatkę, około 0.204 s łącznie dla 1800 klatek, maksimum 640.3 mikrosekundy, 0 błędów. To pomiar samego parsera, nie całego C/Python/GUI. Stara flaga TELEM_INTEL_QUANT_TELEMETRY=0 nie usuwała wszystkich wywołań ani rozszerzenia SDK. Wynik ON 49.709 FPS, OFF 48.969 FPS nie potwierdził mierzalnego przyspieszenia od flagi w tej parze; nie podano go jako ujemnego kosztu QP. Przebiegi kontrolne pokazują zmienne warunki GPU i rozgrzewki. Nie da się uczciwie przypisać całych 55→49 FPS diagnostyce.

## 3. Usunięte elementy
- Intel C: cały parser Slice QP, AV1 base_q_idx, record_quant_sample/record_slot_qp, trace, agregaty, globalne blokady i bufory parsera, diagnostyczne Query encode-stats, żądania encoded-frame-info i per-slot rozszerzenia SDK. W gorącej pętli nie ma już wywołania/warunku sprawdzającego QP.
- Intel Python: ctypes Slice QP, odczyty parsera, IntelCompressionTracker, withholding QP, słowniki QP i wszystkie przekazania per-frame do tego trackera. W FFmpeg pozostawiono wyłącznie accepted rate-control metadata/VBR validation.
- GUI/harness: checkbox analizy kompresji, osobna etykieta QP, formatowanie QP w progress/popupie/kolejce, bufor próbek QP harnessu i BENCH STATS QP. Kolejka nie zapisuje nowych metryk QP.
- AMD: odczyty i logi QP w Pythonie; w produkcyjnym native/d3d11_amf_pipeline usunięto request feedback i per-frame GetProperty/agregaty. Bez zmian operacji kompozycji/HUD.
- NVIDIA: usunięto produkcyjny FFmpeg CompressionTracker, dodatkową częstotliwość stats_period 0.25 i polling native statystyk. Flagi/CSV w produkcyjnym wywołaniu są zawsze wyłączone. W obu istniejących drzewach źródeł native NVENC usunięto RecordCompressionSample, histogram/wektor/prywatną blokadę i CSV. Kod enkodera/presety/AQ zachowano.

Zachowane są nieaktywne pola starych snapshotów/kolejek i nieużywane argumenty API dla kompatybilności zapisanych danych. Nie są zbierane ani wyświetlane. Publiczny IntelNativePipelineStats zachowuje 752 B i wszystkie offsety, IntelEncoderInfo 52 B; dawne sloty są zarezerwowane, zerowane wraz ze strukturą, nie odczytywane per-frame. Usunięto dwa eksporty Intel służące wyłącznie parserowi QP. AMD zachowuje ABI 9 i wszystkie 88 eksportów; dawne gettery statystyk zwracają brak danych, bez zbierania ich w rendererze. Gettery NVENC są stubami kompatybilności.
Samodzielne narzędzia offline i testy o innych zastosowaniach pozostawiono. Testowy helper parsera HEVC ma teraz własną strukturę ctypes, więc nie importuje usuniętej klasy z produkcyjnego eksportera. Stary analizator można testować przez jawnie wskazaną dawną DLL. Nie jest importowany przez produkcyjny eksport.

## 4. Warunki pomiaru i wyniki
Każdy przebieg wydajności: 1800 klatek, rzeczywisty GoPro C:\GoPro\GX010378.MP4 + FIT C:\GoPro\2026-10-15_15-03-50.fit, canonical GUI harness SportCamHUD.py --test-intel-export, native HEVC Fast, 3840×2160, 30000/1001 fps, 40M, ten sam HUD/layout i telemetria. Layout SHA256 820e3bc6379ecdbe25469eebf02576a3870afde41f452684bb63320b0e312044. Użyto pary zapisanej w istniejącym harnessie Intel; para Video/GX020079.MP4 + Video/GX020079.fit nie jest tu dostępna. Nie dobierano innego FIT do filmu.

Nowy tools/benchmark_intel_qp_removal.py uruchamia ten harness i zbiera drzewo CPU oraz liczniki GPU bez zmiany renderingu. Pełne komendy, hashe DLL, logi i próbki: intel_qp_removal_20261019/*/measurement.json. Odcinek ustabilizowany jest wyliczony z raportów czasu klatek 500–1500 (rozdzielczość logu 0.1 s); średni render FPS pochodzi z całej pętli wraz z rozgrzewką. Pełny czas eksportu obejmuje przygotowanie wewnątrz eksportera, render i finalizację. Osobno zapisano czas procesu od startu GUI oraz FPS harnessu, nie pomylono ich z FPS pętli.

| Przebieg (1800 klatek) | Render FPS | Stały odcinek 500–1500 FPS | Cały eksport s | Efektywne FPS | CPU % maszyny |
|---|---:|---:|---:|---:|---:|
| before_qp_on | 49.709 | 47.847 | 37.285 | 48.276 | 21.24 |
| before_qp_off | 48.969 | 49.751 | 37.843 | 47.565 | 23.73 |
| after_qp_removed | 37.111 | 40.984 | 49.764 | 36.170 | 20.44 |
| control_old_dll_current_gui | 37.990 | 40.000 | 48.729 | 36.939 | 20.66 |
| after_qp_removed_repeat | 38.002 | 40.000 | 48.588 | 37.046 | 21.01 |
| control_original_python_old_dll | 51.979 | 51.282 | 35.667 | 50.467 | 22.47 |
| control_original_python_new_dll | 52.608 | 53.476 | 35.275 | 51.028 | 22.50 |
| control_final_python_new_dll | 49.368 | 52.632 | 37.660 | 47.796 | 23.16 |
| final_warm_no_qp | 53.031 | 52.632 | 35.033 | 51.380 | 21.88 |

CPU: średnia z dodatnich próbek całego drzewa procesu, znormalizowana do wszystkich CPU maszyny; obejmuje życie procesu, nie wyłącznie fazę kodowania. Brak udowodnionego spadku wykorzystania CPU. VideoEncode PDH zwracał None we wszystkich próbkach — GPU utilisation NOT AVAILABLE, nie 0%. Nie zastępowano go licznikiem VideoDecode/VideoProcessing. Testy były seryjne w części benchmarkowej; dłuższe przebiegi są osobne od smoke/pytest. Wykonywano odczyty/audyt podczas niektórych prób, więc nie jest to laboratoryjny benchmark o kontrolowanej temperaturze i mocy.

Pierwsza próba po zmianie 37.111 FPS wywołała dodatkowe kontrole. Stara i nowa DLL przy tym samym nowym Pythonie uzyskały odpowiednio 37.990 i 38.002 FPS. Przy ponownym użyciu oryginalnego Pythona stara DLL uzyskała 51.979, a nowa 52.608 FPS; końcowy rozgrzany nowy kod 53.031 FPS. Źródła oryginalnego Pythona odczytano chwilowo z HEAD do istniejących plików wyłącznie na czas kontroli; bieżące zmiany zachowano w pamięci i patchu, odtworzono w finally. Nie tworzono kopii projektu/gałęzi i nie tracono prywatnych zmian.
Nie traktujemy 49.709→53.031 jako udowodnionego czystego zysku z QP ze względu na zmienność pomiarów. Cel >55 FPS: NIE OSIĄGNIĘTY; końcowy ustabilizowany odcinek 52.632 FPS.

## 5. Wąskie gardło i ostatni merge
Przed zmianą: średni Native Step 17.64 ms/klatkę, Encode Sync 18.607 ms, HUD Wait 0.11 ms, consumer Queue Wait 0.001 ms. Podczas wolniejszych kontroli stary/nowy kod miał Encode Sync 24.522/24.720 ms oraz Native Step 23.35/23.42 ms. To nakładające się etapy, nie należy sumować ich czasów.
Konkretnym obserwowanym ograniczeniem jest oczekiwanie konsumenta/drain na QSV/GPU i wolny slot enkodera, a nie parser QP lub oczekiwanie na HUD. P010/decode i istniejąca kopia VP→encoder również pozostają; log zgłasza nieobsługiwane direct VP output-view i istniejący CopyResource fallback. Nie przebudowywano tego renderera ani nie zmieniano synchronizacji GPU w celu sztucznego poprawienia FPS.
Ostatni merge nie zmienił natywnej implementacji Intel: źródłowy blob przed/po przeniesieniu katalogu ma identyczny hash 4aa43d11a64ad4f64712bb302664497957b65343. Porównano też Python: qp_merge_intel_audit_20261019.diff. Zmiany wyboru kodeka/capability są przy inicjalizacji, nie tłumaczą same w sobie dużego wzrostu czasu Encode Sync. Nie udowodniono fizycznej przyczyny zmiennych czasów GPU (moc/temperatura/konkurencyjne obciążenie/sterownik); to hipotezy, nie ustalenia. Brak wiarygodnego GPU utilisation ogranicza diagnozę. Usunięcie diagnostyki nie uzasadnia zmiany presetów czy jakości.

## 6. Jakość i kompresja
Zachowano VBR (MFX RateControlMethod=2), TU Fast=7, target=40000 kbps, max=50000 kbps, VBV=10000 KB, initial delay=5000 KB, multiplier=1. Porównano zaakceptowane parametry w każdym długim przebiegu. Balanced/Quality TU 4/1 bez zmian. HDR/HLG, Main10/P010, profile, GOP, bitrate i dotychczasowe AQ nie zostały zmienione. Usunięcie feedback nie wyłącza wewnętrznego doboru QP enkodera. Nie włączano CQP ani stałego QP.

Pakiety zakodowanego wideo we wszystkich dziewięciu długich przebiegach mają identyczny SHA256:
2f6a37c20a6c208566999eb6269b0a622fee78a48ab9a791993d87e7eedd15f8.
To potwierdza identyczny wynik HEVC dla badanego materiału, a nie tylko równy bitrate lub subiektywną jakość. Nie jest to dowód dla wszystkich filmów/GPU. Brak dodatkowego pełnego kodowania/dekodowania QP; hash liczono offline po eksportach, poza benchmarkiem. Audio pozostało live mux z oryginalnego MP4, bez ensure_audio_cache i bez plików wydzielonego audio.

## 7. Testy
- Końcowy zestaw: 212 passed, 4 skipped — qp_removal_final_regression_20261019.log. Obejmuje Intel VBR i brak QP w native/progress, GUI recovery, manualny FIT/GPX offset, SmartSync algorytm, zapis/odczyt offsetu, presety, live mux/finalizację, dynamiczne capabilities, izolację runtime, AMD VBR, cykl życia kolejki, HDR i scope progress. Trzy SKIP wymagają UHD730/P400, czwarty test HDR szuka ffprobe.exe w starej lokalizacji. Nie oznaczono ich jako PASS.
- Istniejąca macierz Intel, 60 klatek na przypadek: 12/12 PASS, native/FFmpeg × HEVC/H264 × Fast/Balanced/Quality. Main10/yuv420p10le/HLG, 30000/1001 fps, live AAC, dekodowalny MP4, sygnalizacja HRD i cbr_flag=0, zgodność A/V <0.1 s. To testy poprawności, NIE benchmark. quality_matrix/summary_smoke.json.
- Realny preview z telemetrią: PASS, 60 klatek, has_video_frame=1, has_hud=1, 2 aktualizacje podglądu. qp_preview_smoke_20261019.log i preview_smoke.json. Pełna ręczna ocena wszystkich pikseli/GUI: NOT TESTED.
- Realny panel licencji/Ustawienia: PASS, 109 dokumentów, aktywny heartbeat, sondy ffmpeg/ffprobe; gui_licenses/result.json.
- Portable Python 3.14: PASS native HEVC Fast 60 klatek z bieżącym kodem i nową DLL, poprawna walidacja MP4. portable314.json.
- Składnia obu istniejących źródeł native NVIDIA: clang++ -fsyntax-only PASS. Brak zainstalowanej DLL native NVIDIA do podmiany. Sprzęt NVIDIA i AMD: NOT TESTED na tej maszynie Intel Iris Xe.
- ABI AMD 9 i komplet 88/88 eksportów PASS, Intel 752/52 B i zachowane offsety PASS; celowo usunięto dwa eksporty parsera QP. final_binary_exports.json, intel_abi_layout.json.
- Rozszerzone stare testy GUI nie zostały ukończone: pojedynczy test otwiera modalne ostrzeżenie o braku wideo przez _on_render bez kontrolera (faulthandler wskazał QMessageBox.warning). Zatrzymano próbę, nie zmieniano zabezpieczenia GUI, nie policzono tych testów jako PASS. Pełna suita repo: NOT TESTED.
- compileall i git diff --check: PASS. Nie deklarujemy globalnego braku regresji poza opisanym zakresem.

## 8. Buildy i ryzyka
Intel: nowa DLL z oryginalnym LLVM-MinGW/FFmpeg/oneVPL, -O2 -mavx2 -mfma. Manifest budowy zapisany w artefaktach.
AMD: konieczny rebuild wyłącznie dla usunięcia per-frame feedback z produkcyjnej DLL. Brak MSVC na tej maszynie; użyto LLVM-MinGW z tym samym zestawem źródeł i flagami optymalizacji/łączenia targetu CMake, ABI 9 i tożsamością źródeł zgodną z materiałem hash CMake. Nowy tools/build_amd_native.py buduje kandydata, nie nadpisuje runtime automatycznie. DLL zachowuje 88 eksportów, ładuje się i przechodzi testy bez GPU. Zmiana toolchainu MSVC→LLVM jest dodatkowym ryzykiem wymagającym realnego smoke AMD przed wydaniem. Nie deklarowano GPU PASS. Oryginalna DLL zachowana w backupie.
NVIDIA: wyłącznie usunięcie QP z źródeł i wyłączenie diagnostyki w istniejącym API; nie przebudowywano pozostałych elementów renderera. Native GPU export NOT TESTED. Parametry kompresji nie zostały zmienione.
Hashe obu nowych DLL są przypięte w tools/build_portable_release.py i runtime/runtime_manifest.json. Nowe DLL są częścią lokalnego commitu poprawki, aby odtworzenie kodu nie pozostawiało starej diagnostyki w runtime.

## 9. Pliki i Git
Lista zmienionych plików: qp_removal_changed_files_20261019.txt. Poza kodem, testami, dwoma DLL, manifestem i dwoma narzędziami dodano raporty/dowody; nie dodawano filmów, prywatnego layoutu, fontu, C ani backupów DLL do Git.
Nie zmieniano historii ani zdalnego main. Nowy commit poprawki ma rodzica aa42e65; jego SHA zostanie podane w końcowej odpowiedzi i uzupełnieniu raportu. Wszystkie wcześniejsze commity pozostają osiągalne.
Końcowy working tree ma zachować wyłącznie zastaną prywatną pracę i kopie bezpieczeństwa DLL. Nie wykonano push.

## 10. Werdykt
QP measurement/analysis w produkcyjnym eksporcie: USUNIĘTE. VBR, jakość i funkcje w testowanym Intel: PASS. Bitowo identyczny strumień testowy: PASS. Powrót do ponad 55 FPS: NIE OSIĄGNIĘTY. Wydajność końcowa: 53.031 FPS render / 51.380 FPS z finalizacją, 35.033 s dla 1800 klatek; ustabilizowany odcinek 52.632 FPS. Sprzętowe AMD/NVIDIA i globalny brak regresji: NOT PROVEN / NOT TESTED zgodnie z powyższym zakresem.

## 11. Potwierdzenie lokalnego commitu
Commit poprawki: 98848d712ecbb34c821d878207bed79b55aaaacc — perf: remove production QP diagnostics while preserving encoder rate control.
Rodzic: aa42e65cf8231f80d13c077bfc6db561bb1f2a61. Źródła, dwie DLL i dowody są w tym commicie; prywatny def_layout.json i backupy nie są jego częścią. Uzupełnienie niniejszego raportu jest osobnym commitem dokumentacyjnym.
Working tree po commicie: M def_layout.json; nieśledzone C, pusty RAPORT_INTEL_HEVC_SLICE_QP_20261017.md w root, font PL, dwie zastane kopie Intel i nowe kopie bezpieczeństwa Intel/AMD .bak_before_qp_removal_20261019. Nie ma niezacommitowanych zmian źródeł aplikacji. Nie wykonano push.
Kontrola git diff --check źródeł i końcowej niezacommitowanej pracy PASS. Staged kontrola obejmująca surowe logi zgłaszała whitespace w wyjściu pytest/FFmpeg oraz patchach audytowych; zachowano oryginalne logi zamiast zmieniać ich zapis. Nie uznano tego za błąd źródeł ani testów wykonania. Stan źródeł sprzed poprawki i wszystkich wcześniejszych commitów pozostał osiągalny.
