# SPORTCAMHUD — bezwzględny direct copy audio AMD

2026-10-14, Europe/Warsaw. **PASS dla celowanego kontraktu Windows/original GoPro. Długa finalizacja pełnego eksportu: NOT TESTED.**

## Stan i zakres

Początkowy i końcowy HEAD: `e76d6b1da0bcf1487e5061d16b05d7916adefb3b`; gałąź `fix/gui-freeze-hud-composite`. Przeczytano AGENTS.md/BENCHMARKS.md i zastane zmiany. Już przed zadaniem istniały zmiany AMD, Intel, NVIDIA, def_layout i nieśledzone live_av_mux.py/mp4_audio_feed.py/testy. Zachowano je; nie resetowano ani nie commitowano.

W tym zadaniu zmieniono: `src/ffmpeg/amd_native_exporter.py`, `src/ffmpeg/streaming.py` (wyłącznie dispatch AMD), `src/ffmpeg/mp4_audio_feed.py`, `tests/test_mp4_audio_feed.py`, `tests/test_amd_live_mux_audio_finalization.py`, `tests/test_amd_direct_mp4_mux.py`; dodano ten raport i artefakty testów. Shared live_av_mux.py i pliki Intel/NVIDIA nie zostały zmienione przez to zadanie.

## Zabezpieczenia

- Każdy normalny AMD_NATIVE_D3D11 eksport używa jednego live muxera z globalnym **`-c copy`**. Jednoplikowe zakresy, wiele klipów i retained ranges po pomijaniu pauz używają istniejącego mp4_audio_feed.py. AAC payload jest odczytywany z oryginalnych sample tables i opakowywany ADTS wyłącznie w pamięci/named pipe; nagłówek transmisyjny nie zmienia payloadu.
- AMD nie wywołuje już `build_live_audio_inputs`, którego gałąź concat_filter koduje AAC dla pozostałych backendów. `_require_amd_audio_copy` odrzuca mode concat_filter, kodek inny niż copy oraz filter_complex. Takie błędy są jawne, bez rekompresji.
- W normalnym eksporcie wyłączenie AMD_DIRECT_MUX/AMD_SINGLE_PASS_AV_MUX, błąd utworzenia pipe, startu FFmpeg lub brak input setts oznacza AMDNativeFinalizationError. Dispatch streaming nie przechodzi po porażce AMD do eksportera software. Dawne Stage C/file mux pozostały w źródle, ale są nieosiągalne w normalnym eksporcie przez te bramki. Tryby diagnostyczne AMF BYPASS/SUBMIT_NO_MUX nie są produkcyjnymi eksportami A/V.
- Audio ranges mają ten sam limit klatek co wideo, także TELEM_MAX_FRAMES. Podajnik odmawia niezgodnych formatów AAC/ASC, mieszanki audio i mute, nieregularnego czasu AAC, złożonych edit-list/composition offsets i zbyt dużych ramek transportu. Akceptuje AAC-LC, stałe 1024 próbki, kompatybilną konfigurację. Przekroczenie jednej ramki AAC skumulowanego błędu granic powoduje czytelny błąd zamiast korekcji stratnej.
- Named pipe ma własne poprawne prototypy Win32, obsługuje krótkie zapisy i zgłasza zerowy postęp/niepełne podanie. CancelSynchronousIo przerywa blokujący ConnectNamedPipe/WriteFile/Flush; przy abort nie czeka na FlushFileBuffers od zatrzymanego klienta. Normalny EOF nadal opróżnia pipe. Rzeczywiste testy Windows obejmują brak czytelnika i czytelnika, który nie odbiera danych.

## Rzeczywiste testy GoPro

Istniejący harness pytest i seam export_amd_native_d3d11 uruchomiono z rzeczywistą DLL na Windows. FFmpeg/ffprobe z runtime/common/ffmpeg. Źródła oryginalne na F::

- `F:\GoPro\2026-10-07\GX010350.MP4`, zakres [10.000, 13.003).
- `F:\GoPro\2026-10-12\GX010366.MP4`, zakres [20.000, 23.003).
- Pomijanie pauzy: dwa retained ranges pierwszego pliku [10.000, 13.003) i [25.000, 28.003).

Single 90 klatek FAST; multi 180 klatek BALANCED; pause 180 klatek QUALITY; 720p, 5M, 30000/1001 FPS, bez HUD/telemetrii. FIT nie był używany ani dobierany — to test audio/mux, nie renderowania HUD. Wszystkie trzy profile wideo korzystają z tego samego copy audio.

Finalny zestaw trzech plików: **40 passed in 18.23s, 0 failed, 0 skipped**. JUnit: `direct_copy_audio_windows_20261014/targeted_tests.xml`.

| Przypadek | PID FFmpeg | AAC identyczne / wybrane | Demux audio przed EOF wideo | Etap mux (ms) | stdin.close → wykrycie końca FFmpeg (ms) |
|---|---:|---:|---:|---:|---:|
| single_trim | 9492 | 141/141 | 97.87% | 1.139 | 50.603 |
| multi_trim | 29688 | 282/282 | 98.58% | 1.074 | 57.891 |
| pause_cuts | 6336 | 282/282 | 100.00% | 1.050 | 59.169 |

705/705 pakietów: SHA-256 payloadu finalnego MP4 identyczne z niezależnym ffprobe źródeł, kolejność i liczba zgodne z zakresem. Pełne listy hashy źródłowych i wynikowych w evidence.json/accepted_cases.json. Selekcja IN/OUT: midpoint całej ramki AAC w [IN,OUT), obliczany na całkowitej timebase; bez dekodowania PCM. FFmpeg usuwa jedynie opakowanie ADTS przy zapisaniu MP4.

PTS=DTS, początek audio 0, kolejne DTS co 1024/48000 s, bez luk/duplikatów. Wideo: 3.003/6.006 s. Audio: 3.008/6.016 s. Błąd granicy po pierwszym klipie +5.000 ms, po drugim +10.000 ms — mniej niż ramka AAC 21.333 ms. Kopiowanie AAC nie zapewnia cięcia co do pojedynczej próbki PCM; ten kontrakt jest jawny i sprawdzany na granicach, bez rekompresji.

W każdym realnym przebiegu **wszystkie wybrane payloady źródłowe odczytano przed EOF HEVC** (zero source_read_chunks_after_eof; timestamp końca generatora wcześniejszy niż stdin.close). Kilka końcowych pakietów może pojawić się w demux/logu po EOF podczas opróżniania bufora. Odczyt źródła nie został odłożony do finalizacji. To obserwacje aplikacyjne, nie pomiar fizycznego I/O F:.

W początkowym realnym teście wykryto około 0.997 s prerollu audio przed IN w starym single-file -ss/-i; zastąpiono tę ścieżkę podajnikiem sample-table. Pierwsza niezgodność testu multi-file wynikała z zaokrąglonych pts_time na IN; naprawiono niezależny oracle przez timestampy całkowite, bez osłabienia porównania hashy. Próba bardziej restrykcyjnej walidacji ASC początkowo odrzuciła zerowy padding GoPro; dopuszczono go po odczycie rzeczywistej extradata. Nieudane krótkie przebiegi zachowano w artifacts; końcowe dowody są wskazane w accepted_cases.json.

## Dokładne wykonane komendy

`-debug_ts` dodano wyłącznie przez obserwator testowy. Pozostałe argumenty pochodzą z produkcyjnego buildera; -f aac opisuje wejście transportowe, a nie rekompresję. Żaden z realnych testów nie tworzy osobnego audio/wideo ani dodatkowego remuxu.

### single_trim

```text
C:\_DEV\BikeRideHUD-main-new\runtime\common\ffmpeg\ffmpeg.exe -debug_ts -y -f hevc -r 30000/1001 -bsf:v setts=ts=N*1001/30000/TB:duration=1001/30000/TB -thread_queue_size 512 -i - -thread_queue_size 512 -f aac -i \\.\pipe\telem_amf_audio_27776_977813ea.aac -map 0:v -map 1:a:0 -t 3.003000 -c copy -f mp4 C:\_DEV\BikeRideHUD-main-new\Raporty\direct_copy_audio_windows_20261014\single_trim_2cdbc744\final.mp4.part
```

Dowód: `C:\_DEV\BikeRideHUD-main-new\Raporty\direct_copy_audio_windows_20261014\single_trim_2cdbc744\evidence.json`.

### multi_trim

```text
C:\_DEV\BikeRideHUD-main-new\runtime\common\ffmpeg\ffmpeg.exe -debug_ts -y -f hevc -r 30000/1001 -bsf:v setts=ts=N*1001/30000/TB:duration=1001/30000/TB -thread_queue_size 512 -i - -thread_queue_size 512 -f aac -i \\.\pipe\telem_amf_audio_27776_23baa4ca.aac -map 0:v -map 1:a:0 -t 6.006000 -c copy -f mp4 C:\_DEV\BikeRideHUD-main-new\Raporty\direct_copy_audio_windows_20261014\multi_trim_09e39a4c\final.mp4.part
```

Dowód: `C:\_DEV\BikeRideHUD-main-new\Raporty\direct_copy_audio_windows_20261014\multi_trim_09e39a4c\evidence.json`.

### pause_cuts

```text
C:\_DEV\BikeRideHUD-main-new\runtime\common\ffmpeg\ffmpeg.exe -debug_ts -y -f hevc -r 30000/1001 -bsf:v setts=ts=N*1001/30000/TB:duration=1001/30000/TB -thread_queue_size 512 -i - -thread_queue_size 512 -f aac -i \\.\pipe\telem_amf_audio_27776_44685554.aac -map 0:v -map 1:a:0 -t 6.006000 -c copy -f mp4 C:\_DEV\BikeRideHUD-main-new\Raporty\direct_copy_audio_windows_20261014\pause_cuts_8107f996\final.mp4.part
```

Dowód: `C:\_DEV\BikeRideHUD-main-new\Raporty\direct_copy_audio_windows_20261014\pause_cuts_8107f996\evidence.json`.

## Integralność i ograniczenia

Hashy chronione na początku i po testach identyczne (manifest accepted_cases.json):

- `src/ffmpeg/intel_native_exporter.py`: `5ae96ea83f35bf67b5f6361238a64e3917617e627501add943f9fec9c38400ff`.
- `src/ffmpeg/nvidia_native_exporter.py`: `152b4a37d72e7530ee44d5da23fefe498f284acfb848169c46c61d6eb8e6a4ff`.
- `def_layout.json`: `177c4f59f222f25e38d5d4151c42729181c057edf1f57544591d3b3ff5eb9c64`.
- `runtime/amd/bin/telem_amd_native.dll`: `380f86b044ab61eefb60c0e1d6fd386dcfe0e95d9c12dac756a93bf8e71ea50b`.

Nie przebudowywano FFmpeg/DLL; bez zmian D3D11, HUD, kompasu, mapy, FIT, def_layout i backendów Intel/NVIDIA. Ich zastane modyfikacje pozostały bez ingerencji. `git diff --check` dla zmienionych plików kodu/testów PASS. Globalny check zgłasza zastane trailing whitespace w wcześniejszym raporcie 5R-F; nie poprawiano go kosmetycznie.

Nie wykonano pełnego eksportu 4K ani 200-testowej macierzy. Nie mierzono wpływu na 40 FPS ani finalizacji wielominutowego materiału. Wynik to potwierdzenie wymogu lossless copy dla wyżej opisanych oryginalnych zakresów, nie deklaracja rozwiązania każdej długiej finalizacji. Nieobsługiwane formaty/timing kończą eksport błędem; nie uruchamiają stratnego fallbacku. Bez commit/push, portable sync, reset/clean/stash/rebase.
