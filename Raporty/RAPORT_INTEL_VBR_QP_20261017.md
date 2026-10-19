# Intel D3D11/QSV — presety, VBR/VBV/HRD i telemetria QP

## Stan i zakres

Gałąź `main`, HEAD `e21d625`, bez przełączania gałęzi. Zachowano zastane niezacommitowane zmiany, w tym NVIDIA/live mux oraz `def_layout.json` (`auto_activity_source=garmin`). Audyt: [osobny raport](RAPORT_INTEL_VBR_QP_AUDYT_20261017.md).

Sprzęt: Intel Core i7-1265U / Iris Xe, sterownik 32.0.101.7085, Windows, Python 3.15. AV1 encode sprzętowo niedostępny. Poprzednie rzeczywiste próby możliwości potwierdziły H.264 8-bit SDR, HEVC 8-bit SDR i HEVC Main10 HLG; ta macierz obejmuje H.264 SDR i HEVC Main10 HLG. Nie potwierdza obsługi innych urządzeń przez samą identyfikację CPU.

## Przyczyny i poprawki

- Native zapisywał rozstrzygnięty TargetUsage w zmiennej środowiskowej traktowanej następnie jako override. Usunięto zapis; każde zadanie przekazuje TU do nowej funkcji konfiguracyjnej biblioteki. Fast/Balanced/Quality: 7/4/1.
- FFmpeg używał `veryfast` dla wszystkich profili. Obecnie: `veryfast` / `medium` / `veryslow`, odpowiadające TU 7/4/1. Przyjęte wartości są odczytywane z diagnostyki QSV.
- Wspólna polityka Intel VBR: cel z GUI, maksimum 125% celu, bufor 2 sekund celu, początkowe zapełnienie 50%. Przy 40M: 40000/50000 kbps, 10000/5000 KB. Bez stuffing, CQP, CBR, ICQ lub lookahead. Mnożnik reprezentuje wartości przekraczające pola 16-bitowe; 100M testowane jednostkowo, nie sprzętowo.
- Native odczytuje `GetVideoParam`, sprawdza VBR oraz zaakceptowane parametry; FFmpeg analogicznie weryfikuje faktyczny `RateControlMethod` i efektywne wartości z uwzględnieniem mnożnika. Brak odczytu lub inny tryb kończy eksport błędem. Stara biblioteka bez nowego API nie jest uznawana za zweryfikowaną ścieżkę native.
- HRD jest żądane także przy ponownej inicjalizacji bez VSI. Zapisano statusy oneVPL. Kod wrappera `-11` oznacza dwukrotne niepowodzenie inicjalizacji enkodera, sam nie identyfikuje błędu sterownika.
- Nie zmieniono GOP, referencji, B-frames, lookahead ani algorytmu kompozycji. Istniejące różnice GOP między backendami pozostają; porównanie presetów jest wykonywane wewnątrz danego backendu/kodeka.

## QP: źródło i granice wiarygodności

H.264 native: persistent `mfxExtAVCEncodedFrameInfo` przypięty do bitstreamu każdego slotu, odczyt po synchronizacji. Średnia arytmetyczna zwróconych QP klatek, jawna liczba próbek; bez pobierania obrazów GPU do CPU. H.264 FFmpeg: rzeczywista packet quality side data QSV, próbkowana przez progress; średnia po różnych obserwowanych numerach klatek, nie po wszystkich klatkach.

HEVC: Query potwierdza rozszerzenie, jednak Windows runtime zwraca niejednoznaczne zera i w dłuższym materiale wartości 1–2. Kontrolny nagłówek klatki po 12 s ma `init_qp_minus26=0`, `slice_qp_delta=0` (bazowy QP 26). Bazowy slice QP i średni QP jednostek kodowania nie są równoważne, więc ten test nie dowodzi konkretnej usterki sterownika; nie wystarcza też do potwierdzenia prawdziwości odczytów API. Po tej obserwacji wycofano publikowanie **wszystkich** odczytów HEVC jako rzeczywistego QP. GUI: `QP: --` z przyczyną; surowe wartości tylko w `qp_unverified_feedback`. Wcześniejsze pliki macierzy z wartościami HEVC są diagnostyczne i nie stanowią poprawnych statystyk QP.

Zbadano nagłówki bitstreamu: pozwalają odczytać bazowy slice QP, ale nie średni QP CU bez dalszego parsowania danych kodowanych. Nie zastąpiono nim średniego QP. Ten FFmpeg udostępnia packet quality dla QSV H.264, nie HEVC. AV1 `base_q_idx` nie jest QP H.264/HEVC; stary parser o stałych offsetach nie publikuje zweryfikowanej metryki. AV1 encode NOT TESTED na tym sprzęcie.

## Metoda pomiarów

Kanoniczny harness `SportCamHUD.py --test-intel-export`, uruchamiany seryjnie przez `tools/run_intel_vbr_matrix.py`. Wspólny materiał `C:\GoPro\GX010378.MP4`, jawnie zadeklarowana para `C:\GoPro\2026-10-15_15-03-50.fit`; nie jest to kanoniczna para AMD z BENCHMARKS.md. Snapshot bieżącego HUD: `intel_vbr_qp_20261017/layout.json`, SHA256 `820e3bc6379ecdbe25469eebf02576a3870afde41f452684bb63320b0e312044`.

4K 3840×2160, oryginalne 30000/1001 FPS, 40M, te same HUD/FIT/fragment. Smoke: 30 klatek × 12; benchmark: 600 klatek (20,020 s) × 12. Czas i FPS harnessu obejmują przygotowanie i finalizację; dodatkowy process wall w JSON obejmuje także start/zamknięcie aplikacji. Średnia i maksima bitrate liczone z pakietów wideo, bez audio i narzutu kontenera. Maksima w przesuwanych oknach 0,1 i 1 s; bufor HRD nie oznacza sztywnego limitu każdego takiego okna.

Każdy plik: ffprobe, liczba klatek, obecność audio, różnica czasów A/V <0,1 s, pełne dekodowanie kontrolne wideo i audio, nagłówki HRD. Audio jest multipleksowane bezpośrednio z oryginalnego MP4 podczas eksportu. Brak osobnego pliku audio i `ensure_audio_cache`.

Windows PDH nie udostępnia dla tych procesów licznika `VideoEncode`. Wykorzystanie GPU Video Encode: **NOT MEASURED**, nie 0%. Początkowe zerowe pola smoke powstały przez sumowanie pustej listy liczników i są nieważne; poprawiono runner, benchmark zapisuje `null` i powód. Liczniki VideoDecode/VideoProcessing nie zastępują tej metryki.

## Wyniki

Wszystkie 12 krótkich oraz 12 dłuższych prób zakończyło się poprawnym MP4. Poniżej benchmark 600 klatek; wszystkie pliki mają 3840×2160, 30000/1001 FPS, właściwy kodek/profil/transfer, HRD i dźwięk. GPU Video Encode: N/A w każdym wierszu.

| Ścieżka / kodek | Profil (TU) | Czas s | FPS | Śr. Mb/s | Maks. 0,1 / 1 s Mb/s | QP min / śr. / max | Próbki QP |
|---|---|---:|---:|---:|---:|---|---:|
| native / HEVC | Fast (7) | 23.03 | 26.06 | 41.16 | 81.33 / 46.01 | -- | 0 |
| native / HEVC | Balanced (4) | 27.89 | 21.51 | 41.11 | 83.71 / 45.75 | -- | 0 |
| native / HEVC | Quality (1) | 49.71 | 12.07 | 41.58 | 83.01 / 45.97 | -- | 0 |
| native / H.264 | Fast (7) | 22.85 | 26.26 | 41.28 | 80.44 / 47.46 | 19 / 24.61 / 28 | 600 |
| native / H.264 | Balanced (4) | 23.07 | 26.01 | 41.53 | 79.96 / 46.68 | 19 / 24.33 / 29 | 600 |
| native / H.264 | Quality (1) | 23.59 | 25.44 | 40.86 | 77.38 / 46.15 | 19 / 23.95 / 26 | 600 |
| FFmpeg / HEVC | Fast (7) | 116.76 | 5.14 | 40.97 | 87.11 / 47.45 | -- | 0 |
| FFmpeg / HEVC | Balanced (4) | 121.00 | 4.96 | 41.12 | 88.84 / 47.90 | -- | 0 |
| FFmpeg / HEVC | Quality (1) | 121.07 | 4.96 | 41.02 | 88.35 / 48.09 | -- | 0 |
| FFmpeg / H.264 | Fast (7) | 197.50 | 3.04 | 41.40 | 84.33 / 47.42 | 19 / 25.37 / 28 | 269 |
| FFmpeg / H.264 | Balanced (4) | 197.51 | 3.04 | 41.28 | 83.77 / 48.16 | 19 / 25.24 / 28 | 269 |
| FFmpeg / H.264 | Quality (1) | 196.21 | 3.06 | 41.42 | 82.63 / 45.58 | 20 / 25.32 / 28 | 262 |

Przyjęte parametry **we wszystkich 12 przypadkach**: cel 40000 kbps, maksimum 50000 kbps, bufor 10000 KB, opóźnienie początkowe 5000 KB, mnożnik 1. Native: `RateControlMethod=2`, GetVideoParam=0, HRD ON/ON. FFmpeg: rzeczywisty `RateControlMethod: VBR`; pola odczytane z przyjętej konfiguracji QSV. Nagłówki wszystkich strumieni potwierdzają HRD, VBR `cbr_flag=0`, przepływność HRD ≈50 Mb/s (zaokrąglenie kodowania pól) oraz CPB dokładnie 80 Mb. Średnia filmu 40,86–41,58 Mb/s jest spójna z VBR 40M na 20-sekundowym fragmencie. Szczyty 0,1 s przekraczają 50 Mb/s, ale wszystkie zmierzone okna 1 s są poniżej 50 Mb/s; nie deklaruje to dowodu zgodności HRD dla dowolnego strumienia/czasu.

H.264 native: pokrycie QP 600/600 dla każdego profilu, zakresy i zmienność potwierdzone w tabeli. FFmpeg H.264: 269/600, 269/600, 262/600 obserwowanych klatek; nie są to średnie całego filmu. HEVC: 0 **zweryfikowanych** próbek, niezależnie od liczby surowych raportów API. Dla tego kodeka nie deklaruję odczytu prawdziwego QP ani wniosków o jego dynamice na podstawie tych raportów.

Dowody: [zweryfikowane wyniki JSON](intel_vbr_qp_20261017/matrix/validated_summary.json), [kontrola strumieni](intel_vbr_qp_20261017/stream_validation.log), [smoke](intel_vbr_qp_20261017/smoke_matrix.log), [benchmark](intel_vbr_qp_20261017/benchmark_matrix.log). Surowe MP4, nagłówki, komendy i logi są w `intel_vbr_qp_20261017/matrix/`.

## Wydajność i ograniczenia wnioskowania

Native HEVC: Fast/Balanced/Quality różnią się w tej próbie znacząco. Fast: decode 7,17 ms/kl., HUD upload 6,57 ms/kl., encode submit 0,31 ms/kl., encode sync 13,09 ms/kl.; Quality: odpowiednio 59,08 / 59,09 / 0,24 / 67,00 ms/kl. Oczekiwania na GPU i współdzielony kontekst D3D11 przenoszą koszt między etapami; sumowanie tych równoległych czasów jako niezależnych kosztów byłoby błędne. Pomiary wskazują silny wzrost oczekiwania na ukończenie kodowania / postęp D3D11; nie dowodzą, że sam dekoder lub sam HUD stał się przyczyną. Nie zmieniano rendererów ani transferów w celu poprawienia tych wyników.

Native H.264: różnica FPS między profilami jest mała (26,26→25,44), choć przyjęte TU to faktycznie 7/4/1, a średni QP i strumienie się różnią. Brak dowodu, że sterownik zrównał wewnętrzne algorytmy tych presetów. Fallback wykonuje programową kompozycję; H.264 dodatkowo tonemapping HLG→SDR. Sama etykieta QSV nie oznacza, że cały potok jest sprzętowy. Native zachowuje rzeczywisty dekoder D3D11VA, kompozytor D3D11 i kodowanie QSV; jego logi potwierdzają brak kopii CPU obrazu między dekoderem/VP/enkoderem.

Dla H.264 Fast/Balanced/Quality encode sync wynosi 4,49 / 7,27 / 24,66 ms/kl., a oczekiwanie na HUD 7,75 / 8,22 / 1,45 ms/kl. HUD upload pozostaje blisko 6 ms/kl. Wzrost czasu kodowania zmienia nakładanie etapów i zmniejsza oczekiwanie na producenta HUD. To wyjaśnia, dlaczego podobny wynik końcowy FPS nie dowodzi identycznej pracy enkodera. Nie wskazuję jednego stałego bottlenecku dla wszystkich profili.

Uzupełniający kanoniczny audyt fallbacku HEVC Balanced (120 klatek, po zakończeniu wszystkich innych obciążeń): 11 workerów, średni worker render 37,12 ms, kolejka workerów 1,66 ms, zapis stdin FFmpeg 71,11 ms, oczekiwanie na wolny slot 51,47 ms, main queue put 0,021 ms. Writer spędza 69,3% aktywnego czasu na zapisie, 30,6% na oczekiwaniu; przekazano 120/120 pełnych buforów po 14 745 600 bajtów. Wskazuje to presję zwrotną od potoku FFmpeg i transportu, nie wyłącznie niedobór przygotowanych HUD. Nie rozdziela dekodera, CPU overlay, konwersji, transferu i QSV wewnątrz FFmpeg. Nie przypisuję więc podobnego FPS presetów samemu enkoderowi ani nie optymalizuję tych etapów. [Audyt](intel_vbr_qp_20261017/ffmpeg_hevc_pipeline_audit_clean.json), [wynik harnessu](intel_vbr_qp_20261017/ffmpeg_hevc_pipeline_audit_clean_result.json). Krótszy, instrumentowany przebieg nie zastępuje tabeli 600 klatek. Wcześniejszy audyt wykonywany równolegle z analizą obrazu zachowano jako diagnostykę, ale nie użyto jego czasów do tych wniosków.

## Różnice obrazów między presetami

90 zgodnych klatek na parę: 0–29, 285–314, 570–599, przed porównaniem dekodowanych do tego samego formatu danego kodeka. Narzędzie `compare_intel_presets.py` nie zmienia strumieni i nie służy do telemetrii QP. SSIM/PSNR poniżej są **podobieństwem dwóch skompresowanych wyników**, bez nieskompresowanej referencji z HUD; niższe podobieństwo nie dowodzi gorszej jakości jednego z nich.

| Ścieżka / kodek | Para | SSIM | PSNR dB |
|---|---|---:|---:|
| native / H.264 | Fast–Balanced | 0.993637 | 46.940 |
| native / H.264 | Fast–Quality | 0.992749 | 46.198 |
| native / HEVC | Fast–Balanced | 0.996703 | 49.904 |
| native / HEVC | Fast–Quality | 0.996603 | 49.862 |
| FFmpeg / H.264 | Fast–Balanced | 0.992907 | 46.221 |
| FFmpeg / H.264 | Fast–Quality | 0.991702 | 45.395 |
| FFmpeg / HEVC | Fast–Balanced | 0.996073 | 49.089 |
| FFmpeg / HEVC | Fast–Quality | 0.995954 | 48.967 |

Wszystkie pary różnią się dekodowanymi pikselami, zatem presety nie tworzą identycznego obrazu. Różnice są niewielkie w skali całego obrazu tej próbki. Nie wyznaczono obiektywnego rankingu jakości względem bezstratnej referencji ani jakości subiektywnej; QP nie jest używany do porównania H.264 z HEVC. [Pełne wyniki i metoda](intel_vbr_qp_20261017/matrix/quality_comparison.json), logi filtrów w tym samym katalogu.

To pojedyncze przebiegi na jednym urządzeniu, bez kontrolowanego A/B poprzedniego DLL przy identycznych ustawieniach i bez kontroli termiki. Brak regresji FPS względem wersji sprzed zmiany: **NOT PROVEN**. Spowolnienie Quality HEVC względem Fast jest mierzone, nie ukrywane jako „brak regresji”. Nowa telemetria czyta mały bufor metadanych po istniejącym sync; nie dodaje pobierania całych klatek ani nowego GPU sync.

## Build i pliki

Zmienione w tym etapie: `src/ffmpeg/intel_config.py`, `intel_native_exporter.py`, nowy `intel_telemetry.py`, `command_builder.py`, `streaming.py`; native `src/native/d3d11_intel_pipeline/telem_intel_native.c`; harness `src/gui/qt/application.py`; jedna wspólna reguła `src/gui/qt/_mixins/render_mixin.py` (nie wnioskować CQP z jednakowych próbek QP przy jawnym VBR); testy `test_intel_vbr_control.py`, korekta kruchej asercji `test_intel_native_8a.py`; `tools/build_portable_release.py` (wyłącznie pin Intel DLL), narzędzia `build_intel_native.py`, `run_intel_vbr_matrix.py`, `compare_intel_presets.py`, `verify_intel_vbr_regressions.py`, `report_intel_vbr_results.py`; raporty i artefakty w `Raporty/`.

Zainstalowany i użyty w macierzy DLL `runtime/intel/bin/telem_intel_native.dll`: SHA256 `a3b5d6777c7bd8cc90cdbb126a6a186bfd2c49d098e8ccec4ea34f5386a1b58a`. Kopię poprzedniego zachowano w scratch. Narzędzie trwałego buildu również uruchomiono z powodzeniem; tworzy osobnego kandydata i manifest. LLVM-MinGW 20261006, clang 23.1.3, istniejące flagi AVX2/FMA. Manifest: `scratch/intel_native_build/build_manifest.json`; log [native_build.log](intel_vbr_qp_20261017/native_build.log). Kandydat ma inny hash PE niż użyty runtime; nie podmieniano biblioteki podczas macierzy. Pozostaje istniejące ostrzeżenie kompilatora o porównaniu różnych typów wskaźników w kodzie VP; nie dotyczy nowej telemetrii.

Nagłówki buildu: FFmpeg commit `e9b3c55fe0321915a70f44f30b276ef2afdc3a0c`, libvpl commit `674d015bcb294bc39fa276e99a652ea045423e82`. Aktualny native kod źródłowy SHA256 `aa27c9a2e58e842e79944741056f82de3bc07e08511f317b379d206a7a9cb2ff`.

Backendów AMD/NVIDIA nie zmieniano w tym etapie. Zastany diff NVIDIA nie jest częścią tej naprawy. Nie modyfikowano parametrów/wyglądu HUD. Nie budowano nowej architektury Intel ani osobnego toru audio.

## Testy i stan odbioru

- Intel + profile + współdzielona logika AMD VBR/QP: **223 passed, 1 skipped** (stary pomiar AV1 niedostępny na urządzeniu), 3 istniejące ostrzeżenia pytest o nieznanym markerze. [Log](intel_vbr_qp_20261017/unit_tests_final.log).
- Dodatkowe testy VBR i GUI progress: **22 passed, 3 failed**. Trzy testy `test_render_progress_single_source.py` uruchamiają `_on_render()` bez wczytanego wideo i oczekują aktywnego renderu/progress. Normalny guard odrzuca start. Zwykłe uruchomienie czekało na modalne ostrzeżenie; w powtórzeniu zamockowano wyłącznie statyczne QMessageBox warning/critical/information, aby otrzymać rzeczywiste asercje. Nie zmieniano kodu produktu ani asercji tych testów. AST `RenderTab._on_render` jest identyczny z HEAD `e21d625`; [dowód](intel_vbr_qp_20261017/gui_test_provenance.json), [log FAIL](intel_vbr_qp_20261017/progress_regression_tests.log). To nie jest zielony pełny suite GUI.
- Kanoniczny harness: 12/12 smoke, 12/12 benchmark. Pełne dekodowanie audio/wideo i sprawdzenie profilu/transferu/FPS/liczby klatek/HRD parametrów: PASS dla 12 dłuższych plików.
- Końcowy harness kolejki HEVC i fallbacku H.264 po wstrzyknięciu native `-11`: PASS. Końcowy błąd ProcessPool: oczekiwany FAIL eksportu, PASS cleanup, FFmpeg zakończony w 0,054 s (poprzednie powtórzenie 0,052 s), brak żywych procesów FFmpeg potomnych. Czas całego harnessu obejmuje też przygotowanie — nie jest czasem samego cleanup.
- Odizolowana kopia Portable, własny Python 3.14 `-s -E`, aktualny kod i identyczny Intel DLL: **H.264 SDR PASS, HEVC Main10 HLG PASS**, 30 klatek z dźwiękiem każdy, TU4 i przyjęty VBR/VBV; HEVC QP poprawnie `null` z powodem. Logi i wyniki `portable_vbr_*` w katalogu artefaktów. Nie modyfikowano `C:\GoPro\SportCamHUD-Portable`; nie utworzono nowego kompletnego wydania Portable.
- Podsumowanie sześciu końcowych prób: [regression_summary.json](intel_vbr_qp_20261017/regression_summary.json). Dodatkowy audyt 120 klatek nie jest częścią porównawczej tabeli FPS. Próby poprawności i analiza SSIM mogą działać równolegle; macierz porównawcza była seryjna. Testy jednostkowe wykonano przy granicy między walidacją HEVC Fast i startem HEVC Balanced fallbacku, więc początkowe przygotowanie tego jednego przebiegu mogło nakładać się na końcówkę pytest — dodatkowe ograniczenie precyzji jego czasu całkowitego.

Nie przetestowano GPU AMD/NVIDIA ani AV1 encode; testy wspólnej logiki nie zastępują ich rzeczywistego smoke. Nie wykonano kontrolowanego A/B wydajności ze starym DLL ani referencji pikselowej przed kompresją. Wstrzyknięcie `-11` przed inicjalizacją nie dowodzi zwolnienia wszystkich częściowo przydzielonych zasobów native na każdym sterowniku. Nie wykonano sprzętowego eksportu 100M z mnożnikiem >1. Ostrzeżenie SmartSync dla wskazanej pary FIT nie jest dowodem prawidłowego dopasowania czasowego aktywności; porównania używają tej samej pary.

**Status odbioru: częściowo zweryfikowane, nie COMPLETE.** Presety, VBR/VBV/HRD i MP4 z oryginalnym audio potwierdzono rzeczywistymi eksportami. Prawdziwe QP H.264 potwierdzone; HEVC jawnie niedostępne. Pomiar Video Encode GPU i dowód braku regresji względem poprzedniej wersji pozostają nieuzyskane; trzy opisane testy GUI nadal FAIL.
