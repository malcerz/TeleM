# SPORTCAMHUD — 5R-F: diagnoza dalszej długiej finalizacji

2026-10-14, Europe/Warsaw. **PRZYCZYNA KONKRETNEGO PRZEBIEGU: NOT PROVEN.** Nie ogłaszamy naprawy. Nie zmieniono implementacji ani nie uruchamiano testów/eksportów.

HEAD: `7d9d10dd7c07bf7d3c202312eee53169525abb4a`, gałąź `fix/gui-freeze-hud-composite`. Przeczytano AGENTS.md, rzeczywisty kod i raport 5R-F. Zastane modyfikacje raportu 5R-F i def_layout.json zachowano. Exporter nie ma niezacommitowanego diffu. Jego SHA256: `da78c01c04a4e8b668a662e46b4a5c9863d95a11d31ad98c5f9eea0f2bc9c2d1`.

## Zachowane dowody rzeczywistego eksportu

Podczas diagnozy nie było już procesu SportCamHUD/Python ani FFmpeg. Na A: znaleziono zakończony `A:\20261012-0625.mp4`, 2 662 749 783 B (ostatni zapis 07:50:20), z profilem zapisanym 07:50:25. To rzeczywisty eksport **1280×720, 66 423 klatki**, źródło `F:\GoPro\2026-10-12\GX010366.MP4`, źródłowy MP4 12 917 424 694 B. Dostarczony przez użytkownika log rodzica potwierdził następnie ten przebieg na A: (720p, bitrate 5M, quality FAST, ten sam plik źródłowy). Opis początkowy wskazywał D:, lecz log i profil wskazują A:. Dzisiejszy ślad kolejki dla D:\GoPro\BRH\20261012-0625_001.mp4 kończy się anulowaniem o 07:35:24 przy około 7%, przed finalizacją.

Profil A: potwierdza `single_pass_av_mux=true`, jeden klip, Stage C 0 ms, brak pośredniego Stage A. Pump: `pipe_read_bytes=ffmpeg_stdin_bytes=2591868813`, `exit_reason=pipe_closed_error_109`; audio obecne, 103 889 klatek AAC. To potwierdza końcowe przekazanie HEVC i zakończenie pumpa, lecz nie chwilę EOF podczas finalizacji. Wynik nie wskazuje na remux Stage C; aktualny kod wybiera dla jednego klipu direct MP4, a concat dopiero przy `clip_count > 1` (exporter:3295, 3396, 3433). Dokładny załadowany hash modułu Python nie jest zapisany w profilu; ścieżka DLL wskazuje to repozytorium. Log użytkownika potwierdza AMD child PID 424, parent PID 25276, generation 4, process_exit exitcode=0. To nie jest PID FFmpeg. inline_gpmf_plan=None, podgląd był natywnym GPU frame tap (bez procesu FFmpeg preview), a map prefetch nie działał przy starcie/pierwszej klatce. Zatrzymanie preview potwierdzono w logu; nie jest to dowód braku I/O wszystkich procesów w czasie finalizacji.

`etap8p_a.mux_wall_ms=57942.5613`: **57,943 s** od wejścia do finalizacji mux do jej końca. `video_render_end=749397.1973`, `mux_begin=749429.3145`, `mux_end=807371.8758` ms względem początku eksportu: **57,975 s** od końca pętli klatek do końca etapu mux. To nie jest osobny pomiar czasu do zamknięcia PID FFmpeg: etap obejmuje także `pump_thread.join(timeout=60)` (exporter:7159), opcjonalne kończenie preview i oczekiwanie FFmpeg. Bez logów nie rozdzielimy tych czasów.

Mały profil skopiowano do `Raporty/etap5rf_diagnostics_20261014/actual_A_export_profile.json`, aby zachować dowód z RAM-dysku; jego SHA256: `a502270710a18633b0ed58c07656ba5445ffcc0634342b7e7cb3ef95e79a0fc1`. Nie kopiowano MP4.

## Dlaczego brak wymaganych logów

`src/ffmpeg/amd_child_process.py:1120–1124` kasuje `diagnostics_path` po sukcesie, gdy `AMD_CHILD_HANDLE_DIAGNOSTICS` nie jest włączone. Po anulowaniu również kasuje log (:1137–1141). Dla zakończonego A: pliku logu nie ma. W exporterze `finalization_summary` pozostaje pusty (:3332, :8387); profil zawiera `finalization: {}` i nie przechowuje komendy/PID/serii I/O.

W odnalezionych zachowanych logach są starsze wpisy AMD DIRECT MUX i FINALIZATION; **nie odnaleziono wymaganych czterech markerów dla nowego zakończonego eksportu A: ani zgłoszonego przypadku D:**. Nie zastępujemy ich logami wcześniejszych krótkich testów.

Dlatego: PID, bieżący stdin/EOF, stan pumpa w trakcie oczekiwania, przyrost .part, ReadTransferCount i fizyczny odczyt F: oraz proces odpowiedzialny za F: są **NOT MEASURED** dla tego zdarzenia. Koniec pumpa jest znany wyłącznie z końcowego profilu. Oczekiwanie na audio jest hipotezą, nie rozpoznaną przyczyną. F: to dysk nr 2, USB „JMicron Tech”; typ nośnika jest Unspecified, nie zakładamy HDD ani SSD.

## Komenda i błędy wcześniejszej diagnozy

Z aktualnego buildera (exporter:3433–3489) i profilu można odtworzyć oczekiwaną topologię A: poniżej. To **rekonstrukcja**, nie odzyskany rzeczywisty argv; dokładny ffmpeg_cmd był tylko w skasowanym logu. Nie potwierdzamy tą rekonstrukcją komendy zgłoszonego D:.

```text
<ffmpeg_exe> -y -f hevc -r 30000/1001 -thread_queue_size 512 -i - -thread_queue_size 512 -i F:\GoPro\2026-10-12\GX010366.MP4 -map 0:v -map 1:a? -t 2216.314100 -c:v copy -c:a copy -f mp4 a:\20261012-0625.mp4.part
```

`-map 1?` i `-map 1:a?` są różne; produkcyjny builder używa drugiego. W FFmpeg 426841da9d nieużywane strumienie otrzymują AVDISCARD_ALL, a MOV pomija ich payload w mov_read_packet. Zatem direct MOV ogranicza czytanie payloadu wideo, a nie tylko wybór strumieni wyjścia. Nie usuwa jednak probing, nagłówków, buforowania ani odczytów sąsiednich danych. AVIO używa domyślnie bufora i progu krótkiego seeku 32 KiB; mała próbka AAC nie oznacza równie małego odczytu źródła. Źródła: [ffmpeg_demux.c](https://github.com/FFmpeg/FFmpeg/blob/426841da9d/fftools/ffmpeg_demux.c), [mov.c](https://github.com/FFmpeg/FFmpeg/blob/426841da9d/libavformat/mov.c), [aviobuf.c](https://github.com/FFmpeg/FFmpeg/blob/426841da9d/libavformat/aviobuf.c).

169,02 MB z poprzedniego raportu było licznikiem procesu, **nie wielkością AAC ani pomiarem fizycznego USB**. Buforowane odczyty wokół rozproszonych próbek, probing i inne I/O procesu tłumaczą możliwość takiej nadwyżki. Bez wcześniejszego surowego śladu ReadFile/offset/rozmiar nie ustalono dokładnego podziału tych 169 MB; twierdzenie „tylko moov i AAC” jest nieudowodnione. 0,12 s może obejmować odczyty z cache. Również twierdzenie, że concat nie używa indeksów MP4, jest błędne: otwiera właściwy demuxer przez avformat_open_input ([concatdec.c](https://github.com/FFmpeg/FFmpeg/blob/426841da9d/libavformat/concatdec.c)). Zachowanie discard wewnątrz concat wymaga osobnej analizy, ale aktualna ścieżka jednego klipu go nie wybiera.

GUI „MB/s” pochodzi z przyrostu rozmiaru .part (exporter:7342–7362), nie z fizycznego transferu dysku. Samo 98% aktywności F: nie wskazuje PID ani sekwencyjnej przepustowości.

## Minimalny następny pomiar, bez nowego demuxera

Przy następnym **rzeczywistym eksporcie użytkownika**, bez kolejnego automatycznego testu 4K: zachować log istniejącym `AMD_CHILD_HANDLE_DIAGNOSTICS=1` w środowisku uruchomienia. W trakcie finalizacji zebrać argv/PID i istniejące markery, równolegle krótki ślad ETW Disk I/O + File I/O z PID/nazwą pliku/offsetem/rozmiarem oraz fizyczne DiskReadBytes/sec, IOPS, latency i kolejkę dla dysku nr 2. Śledzić także Python/Media Foundation, ffprobe, System i pozostałe procesy, nie tylko FFmpeg. Liczniki procesu zapisywać oddzielnie od fizycznych I/O. Zestawić ostatnią klatkę, encoder close, pump join, stdin EOF, wejście mux wait, przyrost .part i koniec PID. Jeśli FFmpeg czyta audio: porównać postęp timestampów AAC z końcem HEVC, aby potwierdzić opóźnienie audio.

Dopiero po takim przypisaniu przyczyny można zaproponować minimalną poprawkę w builderze wejścia audio lub lifecycle. Nie proponujemy teraz zmiany parametrów „na próbę”, nowego demuxera ani przebudowy architektury.

**Zmiany w tym etapie:** wyłącznie niniejszy raport i trzy małe artefakty dowodowe. DLL, D3D11, HUD, Compass, mapa, Intel/NVIDIA, FIT, def_layout i Single Live Mux bez ingerencji. Bez M4A/ADTS/audio_cache/osobnego wideo/remuxingu. Bez testów regresyjnych, eksportów, commitów, push lub operacji destrukcyjnych Git. **STATUS: diagnoza częściowa; potwierdzono długą finalizację i utratę jej diagnostyki, przyczyna I/O nadal NOT PROVEN.**

