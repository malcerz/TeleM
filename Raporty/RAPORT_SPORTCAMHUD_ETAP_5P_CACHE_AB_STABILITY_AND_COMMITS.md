# SPORTCAMHUD — ETAP 5P: stabilizacja A/B i decyzja o commitach 5O

Data: 2026-10-13, Europe/Warsaw. Repo: `C:\_DEV\BikeRideHUD-main-new`.

**STATUS: PARTIAL / PERFORMANCE NOT PROVEN.** Wykonano 20 kanonicznych eksportów po 1500 klatek, pełne 189 testów, monitoring zegarów/temperatur i kontrolę izolacji A/B. Oba warianty ponownie osiągają około 40 Render FPS. Nie dowiedziono powtarzalnej regresji kodu 5O, lecz niewielki wpływ kodu na FPS nie jest jednoznacznie rozstrzygnięty. Nie utożsamiamy braku silnego dowodu regresji z dowodem braku regresji. Zgodnie z warunkiem użytkownika **nie utworzono żadnego commita produkcyjnego ani testowego 5P/5O**. Nie stosowano arbitralnego marginesu akceptacji.

## 1. Stan Git i zakres

- Przeczytano AGENTS.md, BENCHMARKS.md, rzeczywisty diff oraz raport 5O.
- Gałąź: `fix/gui-freeze-hud-composite`. HEAD początkowy i końcowy: `8465744675c5e75b1ce19a6edde7792ee6da7adc`.
- Znany dobry tag `amd-known-good-40fps-20261012` nadal wskazuje commit `e7582d8e2c212990987380ee10e5980f2dfd5867`; annotated tag object `8feaa2f78af38ac60fa9713eabe2090564ec4fde` bez zmiany.
- Zastane: zmodyfikowany def_layout i pięć modułów 5O, zmodyfikowany test ROSE, nieśledzone raster_ownership/test_bar_cache_ownership oraz raporty/artifacts użytkownika. Zachowano je. Brak zmian staged przed/po; nie wykonano git add/commit.
- Etap 5P nie zmienił żadnego pliku aplikacji ani testu. Utworzono wyłącznie ten raport oraz lokalne narzędzia/artefakty diagnostyczne w `Raporty/etap5p_artifacts/`.
- Bez reset/clean/stash/rebase/merge/push, zmiany tagu i synchronizacji portable. Bez nowych optymalizacji, refaktoru ani zmiany profilu zasilania/BIOS/limitów.

## 2. Warianty i identyczny workload

A = HEAD 5N, bez Bar ownership. B = aktualne niezacommitowane 5O. Izolacja przez sprawdzony import finder 5O: cztery moduły A (bar/dispatcher/compositor/widget_cache) są dokładnymi bajtami `git show 846574...`, zapisanymi w `etap5p_artifacts/ab_hook/`. Zweryfikowano identyczność z izolacją 5O. Working tree nie był podmieniany. Exit-only observer zapisuje źródło modułu, cache i kopie poza gorącą pętlą. B ładuje pliki z właściwego src/.

Kanoniczny harness `SportCamHUD.py --test-amd-export --mode direct`:

- VIDEO `D:\Comparator\GX010345.MP4`;
- FIT `C:\Users\Malcerz\AppData\Local\SportCamHUD\remote_telemetry\garmin\24621925414.fit`;
- layouty `Raporty/etap5m_artifacts/layout_needle.json` / `layout_rose.json`, identyczne jak 5N/5O;
- 3840x2160, 1500 klatek, start-seconds 120, pełny HUD i aktualne cienie;
- AMD Native HEVC FAST, QP 28, bitrate 45M, Single Live Mux;
- ta sama DLL ABI 9 i buildID `telem-amd-native/1.0.0+600c2a6b1826.srcb9957bf212e2`;
- brak ambient AMD_*; default flags, fingerprint wszystkich 20 profili `ed2077e94adedf1882f3051bc895da0fddf272ba3fa20916cca9c0f4d2739abf`.

Przed każdym przebiegiem identyczne 15 s idle z monitorowaniem. Eksporty sekwencyjne. Nie uruchamiano pytest ani mikrobenchmarków równocześnie z eksportem. Każdy MP4 jest końcowym produktem osobnego uruchomienia, nie pośrednikiem w potoku.

## 3. Dostępność sensorów i narzut obserwatora

Sprawdzono procesy, standardowe katalogi i rejestr aplikacji: brak znalezionego uruchomionego/zarejestrowanego HWiNFO/HardwareMonitor/Afterburner/GPU-Z. Sterownik AMD oraz `C:\Windows\System32\atiadlxx.dll` już zainstalowane. Niczego nie instalowano. ACPI MSAcpi_ThermalZoneTemperature zwraca Not supported; OD5 Temperature_Get status −100. **Nie zastąpiono ich zerami.**

Publiczny AMD PMLog_Get zwraca supported sensory CPU temperature/clock, GPU edge/GFX temperature, GFX/VCN/memory clocks oraz ASIC/CPU/GFX power. Zastosowano tylko publikowane getters, context create/destroy oraz zweryfikowane struktury z [AMD SDK](https://github.com/GPUOpen-LibrariesAndSDKs/display-library/blob/master/include/adl_structures.h), [sensor definitions](https://github.com/GPUOpen-LibrariesAndSDKs/display-library/blob/master/include/adl_defines.h) i [PMLog getter](https://gpuopen-librariesandsdks.github.io/adl/overdrive8_8h.html). Pobranie nagłówków do artifacts jest dokumentacją pomiaru, nie nową zależnością aplikacji. Monitor nie korzysta z prywatnych wskaźników Pillow; istniejąca ścieżka eksportera pozostała niezmieniona.

- CPU frequency: Windows `ProcessorInformation.ActualFrequency` i osobno driver PMLOG_CLK_CPUCLK. Nie użyto statycznego Win32_Processor CurrentClockSpeed 2000 jako częstotliwości pracy. Odczyty aggregate/instantaneous mają inną semantykę; nie są pomiarem konkretnego wątku/core eksportera.
- CPU/GPU temp: wyłącznie supported PMLog; surowe dane i statusy w JSONL.
- ASIC power: sensor23, W według SDK; **nie jest zweryfikowanym osobnym CPU package power**. Ten ostatni: N/A. CPU/GFX power zachowano jako driver raw (summary cpu_power_raw/gfx_power_raw), bez dopisywania niezweryfikowanych jednostek i bez przypisywania ich do osobnych szyn APU.
- GPU Video Codec/3D: Windows GPUEngine, także osobno PID procesu eksportu. Surowy licznik potrafi wskazać101–102%; nie obcięto go ukradkiem.
- CPU utilization/RAM: psutil oraz Windows performance counters. PageFaults/sec oddzielnie od PagesInput/sec; pierwsze obejmuje także soft faults.
- Disk active:100−PercentIdleTime, C:/D:/F:; zapisano również PercentDiskTime i queue length. Nie utożsamiano PercentDiskTime z aktywnością dysku.
- Plan zasilania od początku do końca: Balanced, GUID381b4222-f694-41f0-9685-ff5bb260df2e. Battery status niewystawiony (`None`); nie zgadywano AC/DC. Sterownik GPU31.0.21925.1001, Ryzen7 7730U,16logical CPUs.

**Zlokalizowany koszt diagnozy:** `psutil.process_iter(['pid','name','create_time','cpu_times'])` dla wszystkich procesów:635.9005ms wall /609.375ms CPU w oddzielnym pomiarze. Pełny sampler pojawiał się w swojej telemetrycznej liście z obciążeniem około 50% jednego rdzenia. Gettery ADL w pomiarze: activity1.05–1.90ms, temperature0.086–0.106ms, PMLog0.795–0.920ms; wskazanie0ms processCPU ma ograniczoną rozdzielczość, nie oznacza zerowego kosztu. CPU/RAM psutil <0.2ms, own tree około8.83ms. Surowe wyniki `psutil_cost.json` / `sensor_cost.json`.

Dlatego pierwszą serię oznaczono **FULL OBSERVER** i zachowano w całości. Następnie usunięto wyłącznie skan wszystkich procesów z narzędzia diagnostycznego (**LIGHT OBSERVER**), zachowując te same WMI/ADL, CPU/RAM i metryki export tree. W light brak listy top_processes: **NOT COLLECTED**, nie 0%. Narzędzia monitory zakończyły się po seriach; brak usług pozostawionych w tle.

## 4. Kolejność wszystkich przebiegów

1. FULL: NEEDLE A–B–B–A, ROSE A–B–B–A.
2. LIGHT: NEEDLE A–B–B–A, ROSE A–B–B–A.
3. CONFIRM_NEEDLE: ostatni, z góry zapowiedziany pełny A–B–B–A, ponieważ LIGHT NEEDLE objął zmianę stanu hosta. Identyczny lekki monitor. Nie wykonywano dalszych serii do uzyskania pożądanego wyniku.

Wszystkie wolne wyniki poniżej, bez usuwania ani korekty FPS. Czasy startu UTC; numery w kolejnych tabelach odnoszą się do tej listy.

| # | Start UTC | Seria / przebieg | Render FPS | Process Effective FPS |
|---|---|---|---:|---:|
| 1 | 11:27:04 | FULL/needle_1_A | 38.56490 | 32.74 |
| 2 | 11:28:16 | FULL/needle_2_B | 38.97020 | 33.06 |
| 3 | 11:29:26 | FULL/needle_3_B | 39.15870 | 33.28 |
| 4 | 11:30:35 | FULL/needle_4_A | 39.14044 | 33.63 |
| 5 | 11:31:43 | FULL/rose_1_A | 37.54120 | 32.12 |
| 6 | 11:32:53 | FULL/rose_2_B | 37.30043 | 32.17 |
| 7 | 11:34:03 | FULL/rose_3_B | 37.43052 | 32.18 |
| 8 | 11:35:11 | FULL/rose_4_A | 37.86582 | 32.47 |
| 9 | 11:39:14 | LIGHT/needle_1_A | 39.41328 | 33.66 |
| 10 | 11:40:19 | LIGHT/needle_2_B | 37.58987 | 32.81 |
| 11 | 11:41:26 | LIGHT/needle_3_B | 40.67326 | 35.60 |
| 12 | 11:42:28 | LIGHT/needle_4_A | 40.56545 | 35.72 |
| 13 | 11:43:30 | LIGHT/rose_1_A | 40.26244 | 35.37 |
| 14 | 11:44:34 | LIGHT/rose_2_B | 40.43382 | 35.59 |
| 15 | 11:45:36 | LIGHT/rose_3_B | 40.31218 | 35.63 |
| 16 | 11:46:38 | LIGHT/rose_4_A | 40.11472 | 35.21 |
| 17 | 11:48:03 | CONFIRM_NEEDLE/needle_1_A | 40.67454 | 35.73 |
| 18 | 11:49:05 | CONFIRM_NEEDLE/needle_2_B | 40.76308 | 36.04 |
| 19 | 11:50:07 | CONFIRM_NEEDLE/needle_3_B | 40.41709 | 35.74 |
| 20 | 11:51:10 | CONFIRM_NEEDLE/needle_4_A | 40.64629 | 35.71 |

Process Effective FPS = harness `effective_fps` wraz z przygotowaniem/startup; Render = job `native_fps`. Nie mieszano definicji.

| Seria / tryb | Mean A Render | Mean B Render | B/A−1 | Mean A Process | Mean B Process | B/A−1 |
|---|---:|---:|---:|---:|---:|---:|
| FULL/needle | 38.85267 | 39.06445 | +0.545% | 33.185 | 33.170 | -0.045% |
| FULL/rose | 37.70351 | 37.36548 | -0.897% | 32.295 | 32.175 | -0.372% |
| LIGHT/needle | 39.98937 | 39.13156 | -2.145% | 34.690 | 34.205 | -1.398% |
| LIGHT/rose | 40.18858 | 40.37300 | +0.459% | 35.290 | 35.610 | +0.907% |
| CONFIRM_NEEDLE/needle | 40.66042 | 40.59008 | -0.173% | 35.720 | 35.890 | +0.476% |

Średnie A z pozycji1/4 i B z2/3 równoważą liniowy drift czasu, **nie korygują nieliniowych zmian hosta**. Żadnego wyniku nie normalizowano zegarem ani temperaturą dla uzyskania PASS.

## 5. Temperatury, zegary i obciążenie

Podsumowanie z przybliżonej fazy steady: start_epoch+7s do finish_epoch−3s. Raw pełnego startup/render/idle/shutdown zachowano. Nie jest to dokładnie wycięty interwał render-loop. Mediany temperatur/zegarów PMLog, średnie Windows frequency/CPU load. GPU Edge to nazwa sensora SDK, nie CPU temperature.

| # | CPU °C med | Windows CPU MHz mean | PMLog CPU MHz med | GPU Edge °C med | GFX MHz med | VCN MHz med | CPU% mean | ASIC W med |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 72.0 | 3908 | 3690 | 64.0 | 400 | 866 | 23.7 | 31.0 |
| 2 | 77.0 | 3890 | 3838 | 66.0 | 400 | 866 | 24.6 | 31.0 |
| 3 | 76.0 | 3876 | 3656 | 67.0 | 400 | 866 | 23.7 | 31.0 |
| 4 | 77.0 | 3840 | 3588 | 67.0 | 400 | 866 | 25.8 | 31.0 |
| 5 | 78.5 | 3848 | 3690 | 68.5 | 300 | 866 | 26.6 | 32.0 |
| 6 | 80.0 | 3790 | 3654 | 69.0 | 400 | 866 | 27.3 | 32.0 |
| 7 | 77.5 | 3790 | 3568 | 68.0 | 400 | 866 | 25.9 | 31.5 |
| 8 | 76.5 | 3816 | 3572 | 68.5 | 400 | 866 | 25.6 | 31.0 |
| 9 | 75.0 | 3878 | 3729 | 65.0 | 400 | 866 | 21.9 | 31.0 |
| 10 | 75.0 | 3888 | 3631 | 66.0 | 400 | 866 | 21.5 | 30.0 |
| 11 | 69.0 | 3966 | 3609 | 62.0 | 400 | 866 | 13.6 | 25.0 |
| 12 | 67.0 | 3954 | 3588 | 60.0 | 400 | 866 | 15.4 | 25.0 |
| 13 | 69.5 | 3917 | 3527 | 61.0 | 400 | 866 | 15.6 | 28.0 |
| 14 | 69.0 | 3927 | 3548 | 61.0 | 400 | 866 | 17.8 | 28.0 |
| 15 | 70.0 | 3898 | 3506 | 62.0 | 400 | 866 | 17.3 | 27.0 |
| 16 | 69.0 | 3926 | 3538 | 61.0 | 542 | 866 | 17.7 | 27.0 |
| 17 | 66.0 | 3980 | 3633 | 59.0 | 400 | 866 | 14.2 | 26.0 |
| 18 | 67.0 | 3958 | 3588 | 59.0 | 400 | 866 | 13.4 | 25.0 |
| 19 | 66.0 | 3985 | 3570 | 59.0 | 600 | 866 | 15.2 | 25.0 |
| 20 | 68.0 | 3991 | 3570 | 60.0 | 400 | 866 | 15.4 | 26.0 |

Surowe min/mean/median/max oraz pozostałe supported sensory w `summary.json` / `all_runs.json`. W początkowych seriach zapisano przejściowy wzrost obciążenia Chrome i GFXclock; później temperatury i całkowite obciążenie CPU malały. Nie przekształcono tego w twierdzenie o thermal throttling. Windows PerformanceLimitFlags0 / PercentPerformanceLimit100 w zapisanych próbkach nie oznaczają pełnej diagnostyki limiterów firmware. PMLog raw throttler flags zapisano, bez zgadywania mapowania bitów.

## 6. HUD, kolejka, dysk i pamięć

| # | Bar ms avg | producer_prepare ms avg | compose_overlay ms avg | above_compose ms avg | consumer_queue_wait ms avg |
|---|---:|---:|---:|---:|---:|
| 1 | 3.06225 | 24.60573 | 0.49855 | 13.16399 | 11.95330 |
| 2 | 3.04967 | 24.51629 | 0.50079 | 13.11639 | 10.48053 |
| 3 | 2.98152 | 24.45248 | 0.51094 | 13.12219 | 8.89876 |
| 4 | 2.96651 | 24.43418 | 0.52233 | 13.10902 | 9.90344 |
| 5 | 3.04750 | 25.45586 | 0.50451 | 14.62313 | 16.71736 |
| 6 | 2.98161 | 25.65165 | 0.50961 | 14.77332 | 14.51061 |
| 7 | 3.07708 | 25.50681 | 0.51259 | 14.73228 | 16.39463 |
| 8 | 2.98131 | 25.26045 | 0.51104 | 14.55952 | 14.54988 |
| 9 | 2.93514 | 24.26392 | 0.50028 | 12.97562 | 9.94135 |
| 10 | 3.35462 | 25.41599 | 0.55771 | 14.31174 | 15.40017 |
| 11 | 2.67022 | 22.40130 | 0.49152 | 12.25094 | 2.73001 |
| 12 | 2.65034 | 22.25288 | 0.47790 | 12.22339 | 2.60485 |
| 13 | 2.69748 | 23.56568 | 0.47239 | 13.45438 | 5.91576 |
| 14 | 2.67349 | 23.41854 | 0.49905 | 13.55968 | 4.57487 |
| 15 | 2.72382 | 23.54664 | 0.48477 | 13.60974 | 6.03573 |
| 16 | 2.78228 | 23.69754 | 0.49706 | 13.83529 | 7.98880 |
| 17 | 2.67074 | 22.19480 | 0.49137 | 12.20999 | 2.61708 |
| 18 | 2.63575 | 22.06560 | 0.49123 | 12.18138 | 1.85433 |
| 19 | 2.67377 | 21.99249 | 0.49169 | 12.08440 | 2.24240 |
| 20 | 2.64445 | 21.94355 | 0.48834 | 12.14738 | 2.71972 |

`compose_overlay` w profilu nie obejmuje całego above_pass; dlatego podano także above_compose. Kolejka jest czasem oczekiwania, nie samym czasem pracy GPU.

| # | Min available RAM MB | PageFaults/s med | PagesInput/s med | C active% mean | D active% mean | Max queue C/D | Export 3D% med | Export Codec0% med |
|---|---:|---:|---:|---:|---:|---|---:|---:|
| 1 | 13770 | 150811 | 188 | 2.4 | 1.1 | 0/0 | 63.0 | 93.0 |
| 2 | 13766 | 144674 | 243 | 2.9 | 2.2 | 0/0 | 59.0 | 95.0 |
| 3 | 13720 | 150996 | 166 | 1.3 | 0.7 | 0/0 | 61.0 | 97.0 |
| 4 | 13676 | 144705 | 180 | 6.7 | 2.9 | 2/0 | 63.0 | 96.0 |
| 5 | 13774 | 142414 | 186 | 1.9 | 1.5 | 0/0 | 60.0 | 90.5 |
| 6 | 13686 | 146850 | 190 | 0.9 | 1.8 | 0/0 | 59.5 | 89.5 |
| 7 | 13704 | 141056 | 193 | 0.9 | 1.1 | 0/0 | 65.0 | 91.0 |
| 8 | 13653 | 142013 | 186 | 1.8 | 0.9 | 0/0 | 60.0 | 90.0 |
| 9 | 13746 | 146210 | 186 | 1.4 | 2.0 | 0/0 | 62.0 | 96.5 |
| 10 | 13572 | 139444 | 183 | 1.7 | 2.4 | 1/0 | 53.0 | 91.0 |
| 11 | 13719 | 159366 | 212 | 1.4 | 0.9 | 0/0 | 45.5 | 98.0 |
| 12 | 13715 | 161884 | 183 | 0.9 | 2.1 | 1/0 | 44.5 | 99.0 |
| 13 | 13694 | 148524 | 183 | 0.9 | 1.4 | 4/0 | 46.5 | 100.0 |
| 14 | 13575 | 157655 | 182 | 0.9 | 2.1 | 4/0 | 45.5 | 98.0 |
| 15 | 13633 | 154660 | 155 | 0.9 | 2.7 | 2/0 | 45.5 | 99.0 |
| 16 | 13666 | 162523 | 244 | 0.9 | 0.8 | 0/0 | 45.5 | 98.0 |
| 17 | 13732 | 156529 | 187 | 1.9 | 3.1 | 0/1 | 45.0 | 98.0 |
| 18 | 14146 | 156341 | 182 | 1.9 | 2.7 | 5/0 | 44.5 | 98.0 |
| 19 | 14056 | 158842 | 182 | 1.4 | 1.6 | 1/0 | 43.0 | 98.5 |
| 20 | 14068 | 154961 | 186 | 0.6 | 1.4 | 0/0 | 44.5 | 98.5 |

F: background disk oraz PercentDiskTime/AvgDiskQueueLength są w raw Windows JSONL i summary; peak export-tree RSS i observed processCPU seconds w runs.json/all_runs.json. RSS sumuje procesy, może liczyć shared pages wielokrotnie. CPU seconds z próbek są przybliżone, nie średnim utilization. WMI co około2.7s może nie uchwycić krótkiego spike; nie ogłaszamy pełnego wykluczenia I/O/preemption ani problemu pamięci tylko na tej podstawie.

## 7. Rozdzielenie przyczyn i decyzja wydajnościowa

**Potwierdzone:** monitor FULL wprowadzał istotną pracę CPU; monitor LIGHT ma mniejszy koszt. Stan hosta zmieniał się w czasie (temperature, clocks, utilization); ten sam B w LIGHT NEEDLE osiągnął37.58987 oraz40.67326FPS, różnica około8.2%, przy identycznym kodzie, flagach, hit/miss i identycznym MP4. W późniejszej fazie oba warianty ponownie osiągały około 40FPS.

**Niepotwierdzone:** konkretna fizyczna przyczyna spadków 5O. W 5O nie zbierano zegarów/temperatur. Nie da się uczciwie przypisać historycznych40.72→36.73/40.76→35.13 do temperatury, CPU power cap, GPU throttling lub dysku z samego dzisiejszego pomiaru. Również współwystępowanie mniejszej temperatury/CPU load z większym FPS w 5P nie dowodzi jednego mechanizmu. Nie raportujemy tego jako dowiedzionego wspólnego ograniczenia sprzętowego.

**Kod ownership:** brak nowych Image copies w export hot path, AST rasteryzacji Bar identyczny, mały koszt przejścia dispatchera opisany niżej. To silne dowody przeciwko dodatkowym kopiom jako przyczynie dużego spadku. Nie stanowią jednak matematycznego dowodu zerowego wpływu wszystkich nowych wywołań/kwargs na FPS.

Kierunek różnic A/B nie jest stały: FULL NEEDLE+0.545%, FULL ROSE−0.897%, LIGHT NEEDLE−2.145% (nieliniowy drift), LIGHT ROSE+0.459%, CONFIRM NEEDLE−0.173%. Nie wolno wybierać tylko dodatnich serii lub porównywać różnych monitorów jako identycznych warunków.

Ostatni NEEDLE: A40.67454/40.64629, B40.76308/40.41709; mean−0.07034FPS (−0.173%), podczas gdy Process mean rośnie35.72→35.89. B ma większy rozrzut i w jednym przebiegu inny median GFXclock600 zamiast400MHz. Nie ustalono jednoznacznego mechanizmu różnicy; nie uznano jej ani za dowiedzioną regresję kodu, ani automatycznie za nieistotny szum. **PERFORMANCE NOT PROVEN** w bramce wymagającej rozstrzygnięcia przed commitami. Nie wprowadzono umownej tolerancji1% czy0.2% i nie zmieniono kodu dla polepszenia wyniku.

## 8. Bar ownership: koszty i cache

W każdym z 10 procesów eksportu B: **0 nowych owned Image copies /0 payload bytes**. Observer odczytuje ten sam moduł raster_ownership i source path z procesu export child. Nie mierzy wszystkich historycznych alokacji Pillow/NumPy ani pamięci GPU. Dotychczasowe kopie renderera pozostają bez zmian; potwierdzono AST jego body (po usunięciu docstring) i identyczne argumenty wobec HEAD 5N: `bar_ast_parity.json`.

Każdy z 20 procesów ma identyczne liczniki Bar: 3660 hits / 3854 misses, 64 entries; widget cache 1492 hits / 9 misses. Obejmują przygotowanie sesji/warmup, nie wyłącznie 1500wywołań pojedynczego widgetu. AMD_CPU_WIDGET_CACHE pozostaje domyślnie1; compositor używa jawnego borrowed.

Po zakończeniu wszystkich eksportów przeprowadzono dodatkowy losowo przeplatany mikrobenchmark:100 bloków × 100 wywołań każdej wersji, 4K, realistyczny font_size 1.2, tile Bar z efektami, warm cache. Mean BEFORE 0.027250 ms, AFTER borrowed 0.027382 ms; różnica 0.131520 µs/call. Median 0.026965 / 0.027088 ms. Public owned mean 0.295041 ms (kopiuje tile po efektach, poza export borrowed). To pomiar konkretnego cache-hit, nie całego dynamicznego HUD ani gwarancja kosztu perframe.

Miejsca nowego narzutu: kwargs `_borrowed_bar` i wybór wewnętrznego entrypoint, wrapper get_or_render_borrowed / ownership-aware lookup. Brak nowego algorytmu pikselowego, cienia, font rasterization czy kopiowania w compositorze. Nie usunięto ochrony publicznego wyniku i nie optymalizowano innych rendererów. Szczegółowe koszty raw tile z 5O pozostają w jego raporcie; nie zastąpiono ich tym pomiarem innej konfiguracji.

## 9. Testy 189/189 i parytet

Po wyjściu wszystkich procesów eksportu/monitorów uruchomiono dokładnie grupę20plików 5N + test_bar_cache_ownership. **189 passed in 28.87s, 0 failed, 0 skipped**, log `etap5p_artifacts/suite189.log`. Bez xfail, usuwania testów lub modyfikacji assertions. `git diff --check` PASS. Grupa obejmuje cache/input/output/metadata/A→B→A, GUI, shadow/outline/parity, finalny ROSE, mux/cancel/finalization/governance.

20/20 końcowych MP4: success=true, 1500 klatek, child_exitcode 0, valid output, audio obecne,50.069333 s. Wszystkie 12 NEEDLE mają SHA256:
`0bcc2b261e622f4959168772a823e306c50b09a7b5a3d8c4ddd8d331ec93f55d`.
Wszystkie 8 ROSE mają SHA256:
`0d27c2270781fbb24e5065ae8fd90612ad19a2dd8d600c9792be007787923087`.

Są też identyczne z plikami 5O. To bit-exact kompletnego wideo/audio we wszystkich badanych klatkach, bez nowej zmiany obrazu, cieni czy ghostingu względem A. Bar raw/styled z istniejącej macierzy testów: max_diff0, MAE0, different_pixels0. Nie wykonywano nowego przechwytywania native pre-encode surfaces ani niezależnej ręcznej oceny wszystkich klatek; identical-before-existing-defect nie oznacza usunięcia starego defektu obrazu.

## 10. Single Live Mux i backendy

20/20 profili: single_pass_av_mux=true, rzeczywisty live pump ma dodatnie pipe_read_bytes równe ffmpeg_stdin_bytes; wyjście poprawne z audio. Nie zmieniono startup/finalization/mux/fallback. Nie tworzono audio_cache/M4A/ADTS/pośredniegoMP4 ani dodatkowego remuxingu. Poszczególne MP4 A/B to oddzielne finalne eksporty.

Intel/NVIDIA: kod backendów, FFmpeg/QSV/NVENC/device selection bez zmian; wspólny cache/compositor testowany. Rzeczywiste eksporty hardware Intel/NVIDIA i ich FPS: **NOT TESTED**, bez deklaracji pełnej zgodności sprzętowej. Gauge/Compass renderer, effects, SmartSync i GUI bez zmian w 5P.

## 11. SHA plików i commity

Wszystkie poniższe SHA sprawdzono przed i po; identyczne. Pierwsze5chronione pliki i layouty nie były zmieniane; pozostałe to zachowane poprawki 5O:

- `def_layout.json`: `8375ca40ba3670dd52de765eb91642082c9097a8fbc12dbe7fa1d1203ffa4440`.
- `src/ffmpeg/amd_native_exporter.py`: `0598bc640b6ba46ae261dc08fb444461791820e0a32777a83c2a0aea99c7dd43`.
- `src/indicators/gauge.py`: `2d8b408aa80a5ff98cfe1f44afd4a9b4730bd5f70153849bfa8c4f6142e55fca`.
- `src/indicators/effects.py`: `bdeab1dd376b0b7a91c8bc0a23e14c086ad1481865a9cad2499d65d3c08624d4`.
- `runtime/amd/bin/telem_amd_native.dll`: `7f93c483404f970ea4e2110dcfe12535429b25b11df7415b688c07cef508752f`.
- `src/indicators/bar.py`: `b491f512f12f892604cfa8d89b52889cda157afe9f4e70412178964e1cdbc6d5`.
- `src/indicators/dispatcher.py`: `8db8d56922817e9ab5695185c0e5fe29314c03da1f60ed5371c825d50958450b`.
- `src/indicators/compositor.py`: `f077a945359a0ba42dc8c63af08cff78618922f28e1d42818d33ed50ead08781`.
- `src/indicators/widget_cache.py`: `7dbaa1f060d81536440b3b3d117c2d67392bbccbf8315512ce5b9ce7eba658b7`.
- `src/indicators/raster_ownership.py`: `2122390aac2d9b9f4580f236866789cd76cf8d8ad55bc6e713870ad2df8beaf8`.
- `tests/test_bar_cache_ownership.py`: `5210701981945a1529ede8fc06d9172e7990c6444957b82bd706e41e437b7ca5`.
- `tests/test_compass_source_parity_hotfix.py`: `101d6ec7ebf2e84292b8ba24a8e7bc70776e3b788f910f5ed7a8e099051e58f5`.
- `Raporty/etap5m_artifacts/layout_needle.json`: `3435cbc6ad6d1d670b315fdeedee40a956821b66edc44c58938d150a1df0c018`.
- `Raporty/etap5m_artifacts/layout_rose.json`: `00d85219a589c9658526f577b0b6f011638e323df29eea6fb2c5eb05376b2455`.

SHA nowych commitów: **brak**. HEAD nadal 8465744675c5e75b1ce19a6edde7792ee6da7adc. Nie commitowano def_layout, raportów, MP4, SDK headers ani skryptów monitorowania. Zakres przyszłych commitów pozostaje dokładnie wskazany przez użytkownika (Bar 6 plików, ROSE 1 plik), lecz warunek performance rozstrzygnięcia nie został spełniony. Nie wykonano publikacji/push ani portable sync.

## 12. Otwarte ryzyka i zatrzymanie

**MEMORY SAFETY — ACTIVE RISK.** Prywatne ABI Pillow, map GPU, Gauge transfers, D3D11 i AMF bez zmian. Publiczne read-only gettery ADL użyto wyłącznie dla diagnozy; nie zmieniono pamięci natywnej eksportera ani nie wykonywano eksperymentalnych dereferencji.

**FILE MUX FALLBACK — ACTIVE RISK.** Brak zmiany historycznej gałęzi, brak deklaracji jej bezpieczeństwa na podstawie udanych normalnych eksportów. Badane uruchomienia potwierdzają Single Live Mux, nie eliminację fallbacku.

Wynik: tests/parity/audio/hot-path-copy gates PASS; performance decision NOT PROVEN; zatwierdzenie5O zatrzymane zgodnie z instrukcją. Wszystkie źródła5O pozostają reviewable w working tree. Monitory zamknięte, brak nowych procesów usługowych, bez rozpoczęcia kolejnego etapu.

Surowe dowody: `etap5p_artifacts/all_runs.json`, `validation.json`, `initial_hashes.json`, trzy katalogi runs/summary/Windows+sensor JSONL, kompletne logi i końcowe MP4. Zachowano wszystkie pomiary i protokoły; nie kasowano wolnych wyników.
