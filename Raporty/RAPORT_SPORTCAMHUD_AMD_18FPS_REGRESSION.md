# SPORTCAMHUD — AMD 18 FPS: diagnoza i częściowa poprawa

Data: 2026-10-16. **STATUS: PARTIAL — 40 FPS z pełnym layoutem i pitch 30 nie osiągnięto.**

## 1. Rzeczywista przyczyna
Profil `D:/GoPro/SCH/20261015-1505.mp4.amd_profile.json` i odpowiadający log potwierdzają 44 449 klatek, Render 18,158 / Effective 18,133 FPS. To ograniczenie producenta CPU (54,43 ms), nie AMF (pipeline konsumenta 6,51 ms; bez retry/drop). `consumer_queue_wait` 48,52 ms jest oczekiwaniem na producenta, nie dodatkowym składnikiem czasu renderu. Zagnieżdżonych pomiarów nie dodawano.

`src/ffmpeg/amd_native_exporter.py`: warunek `gpu_map_rotate = ... and not has_pitch` wyłącza obrót GPU dla pitch > 0.001. `_render_track_map_gpu_tile`/`render_map_working_image` wywołuje wtedy `MovingMapRenderer.render_track_up` w `src/moving_map.py`. Ten obracał Pillow BICUBIC całą teksturę 706×706, a następnie wycinał 499×499; zewnętrzny obszar był liczony i odrzucany. Ustawienia użytkownika: Track-Up, satellite, zoom 13, size 13%, pitch 30°, opacity 0,85.

Pomiar podoperacji na oryginalnych danych: `Image.rotate` **33,258 ms**, render kafla **1,122 ms**, `warpPerspective` **0,194 ms**, cały pitch **0,728 ms**, opacity **0,664 ms**, shape **0,017 ms**. Render Track-Up **34,683 ms**, cały helper mapy **36,502 ms**. Są to pomiary zagnieżdżone, NIE składniki do sumowania. Zapis `map_cpu_upload` obejmuje przygotowanie obrazu CPU; nie oznacza samego transferu PCIe.

## 2. Repozytorium, materiał i synchronizacja
- Branch `fix/gui-freeze-hud-composite`; początkowy HEAD `1385e0d59b600ee304488f111a5c9e67a033bcbf`.
- Końcowy HEAD / commit poprawki: **`81af3603bf8967d2734c637bfb972d6f247f4037`**, `perf(map): skip unused Track-Up rotation overscan without changing pixels`.
- Materiał: `F:/GoPro/2026-10-15/GX010378.MP4` + `GX010379.MP4`, w tej kolejności.
- FIT `F:/GoPro/2026-10-15/2026-10-15_15-03-50.fit`, potwierdzony przez użytkownika i zapisany indeks Garmin. Brak ręcznego przesunięcia; istniejąca synchronizacja absolutnych timestampów pozostaje aktywna. Harness nie wymusił walidacji przez override.
- Layout: bajtowa kopia aktualnego prywatnego `def_layout.json` w `amd18fps_artifacts/layout_current_snapshot.json`, potwierdzona przez użytkownika. SHA `3acf21764d6edb2df396b4f678412160035e17f331f42cbe9a29b296443025db`.
- HEVC / BALANCED / VBR 40M (peak 60M), 3840×2160, 30000/1001, HLG preserve, podgląd eksportu GPU tap ON; takie parametry wynikają z oryginalnego logu.
- Porównania: 300 klatek od 60 s (fragment, w którym oryginalny przebieg już zwolnił); granica klipów osobno od 140 s. Nie eksportowano 44 449 klatek.
- Przeczytano AGENTS.md, BENCHMARKS.md i raporty map pitch, 5Z.5, HLG GUI text cleanup.
- Testy historyczne: `git archive` do izolowanych katalogów, bez zmiany aktywnego HEAD i bez cudzych zmian Intel/NVIDIA. Wszystkie używają tej samej przypiętej DLL e359d778…

## 3. Baseline i A/B
| Próba | Render FPS | Effective FPS* | Producer ms | Map CPU ms | ABOVE compose ms | Consumer wait ms |
|---|---:|---:|---:|---:|---:|---:|
| A_full_clean2 | 19.640 | 16.937 | 52.086 | 33.699 | 11.249 | 45.414 |
| B_pitch0 | 41.388 | 31.452 | 21.731 | 2.571 | 10.825 | 2.072 |
| C_pitch45 | 19.064 | 16.745 | 53.282 | 35.055 | 11.224 | 46.406 |
| D_no_map | 31.476 | 25.801 | 31.102 | 0.010 | 0.000 | 16.970 |
| E_no_charts | 19.373 | 17.132 | 52.247 | 34.869 | 10.634 | 45.525 |
| F_map_charts | 18.744 | 16.742 | 53.960 | 35.057 | 11.245 | 47.353 |
| H_before_pitch | 19.109 | 16.468 | 53.731 | 34.288 | 11.703 | 46.935 |
| H_before_tile | 18.921 | 16.642 | 54.001 | 34.563 | 11.796 | 47.073 |
| P_full_r1 | 22.850 | 19.465 | 44.423 | 26.549 | 11.034 | 37.729 |
| P_full_r2 | 22.666 | 19.445 | 44.598 | 26.836 | 10.978 | 37.996 |
| P_full_probe | 22.273 | 19.034 | 45.593 | 27.134 | 11.182 | 39.020 |
| T_baseline | 19.528 | 17.033 | 51.933 | 34.980 | 9.875 | 45.159 |
| T_candidate | 23.426 | 20.023 | 43.274 | 26.666 | 9.862 | 36.518 |
| S_baseline | 35.778 | 31.061 | 2.382 | 0.004 | 0.000 | 0.236 |
| S_candidate | 35.876 | 30.347 | 2.362 | 0.004 | 0.000 | 0.236 |
| P_boundary | 21.813 | 18.461 | 46.179 | 26.223 | 12.497 | 38.458 |

*Effective FPS z profilu obejmuje przygotowanie wewnątrz eksportera; wynik całego harnessu GUI jest osobną, niższą miarą i pozostaje w `result.json`.

A/F = pełny oryginalny layout i mapa+wykresy. B = tylko pitch 0. C = tylko pitch 45. D = tylko mapa OFF w kopii (uwaga: bez mapy eksporter zmienia organizację kompozycji, stąd ABOVE=0; nie jest to odejmowalny koszt samej mapy). E = tylko wykresy kadencji/tętna OFF w kopii. P = poprawka, wszystkie oryginalne wskaźniki ON. T = pełny layout HLG→SDR. S = osobny SDR `F:/GoPro/2026-10-05/DJI_0010.MP4`, bez FIT, jawnie zgłoszony przed próbą; brakujące strumienie FIT/GPS są niedostępne, więc jego FPS NIE oznacza wydajności pełnego HUD GoPro. P_boundary = pełny layout, przekroczenie granicy źródeł.

Wyniki P_full_r1/r2: **22,850 / 22,666 FPS**, Effective **19,465 / 19,445**. Średnia **22,758 FPS** wobec krótkiego matched baseline A/F **19,192 FPS**, poprawa **18,6%**. Nie utożsamiać tego z pomiarem całego zgłoszonego filmu 18,158 FPS.

Cache mapy we wszystkich próbach: **0 żądań sieciowych**. Oryginalny profil: 727 trafień, 0 pobrań; koszt lookup/decode łącznie kilkaset ms na cały długi eksport, nie 34 ms/kl. Kopie source zachowują tę samą lokalną bazę cache; pierwsze zimne alokacje w obrębie procesu są wliczone w próby, nie usunięto wybranych wolnych klatek.

Profilowanie natywne i diagnostyka były wyłączone w oryginalnym profilu oraz próbach porównawczych. Osobne sondy A/P dodają opakowania czasowe: A_probe 18,768 vs clean 19,640; P_probe 22,273 vs clean 22,666–22,850. Sonda ma koszt i nie stanowi końcowego benchmarku. Nie wyjaśnia spadku 40→18, który występuje również bez niej.

CPU/GPU: istniejący `tools/amd_stage4b_gpu_monitor.ps1`, surowe `monitor_system.csv` / `monitor_gpu.csv` w każdej próbie. A CPU drzewa procesu średnio 6.38% wszystkich logicznych CPU; P1 7.11%, P2 7.50%. Są to rzadkie próbki obejmujące także rozruch, nie pomiar pojedynczej klatki ani gwarancja wysycenia GPU. Maksima i typy silników GPU zapisano dla każdej próby w `runs_summary.json`; nie sumowano różnych silników do sztucznego „GPU %”.

## 4. Hipotezy H1–H6
| Hipoteza | Weryfikacja |
|---|---|
| H1 pitch powoduje drogie CPU | POTWIERDZONA: pitch wyłącza GPU rotate; dominuje Pillow rotate ~33,26 ms, nie warp. B pitch 0 = 41,39 FPS. |
| H2 direct/reupload | CZĘŚCIOWO: direct_1to1=false i dynamiczne uploady potwierdzone. Ten flag dotyczy mieszania 1:1, nie samego obrotu GPU; także B ma false. Sam transfer nie jest źródłem 34 ms. Reuse domyślnie OFF; nie włączano ryzykownego cache nieaktualnej mapy. |
| H3 regresja homografii | ODRZUCONA jako przyczyna 18 FPS: warp ~0,19 ms, przed poprawką pitch 19,11 FPS. Zachowano pełne pole i BORDER_REPLICATE. |
| H4 fallback wykresów | POTWIERDZONY i zasadny, ale wtórny: bez wykresów nadal 19,37 FPS. |
| H5 inny layout | POTWIERDZONA: wcześniejszy `layout_5y_full.json` ma pitch=0, obecny pitch=30. B przywraca 41,39 bez wyłączania innych wskaźników, lecz pitch=0 jest wyłącznie ablacją. |
| H6 ostatnie commity | NIE POTWIERDZONA: przed pitch fix `1404441` 19,11; przed GUI tile `29bbd7d` 18,92; obecna baza 18,74–19,64 na tych samych danych/DLL. HLG text cleanup nie zmienia renderera. |

## 5. Wykresy i Z-order
`fit_cadence_text` bbox (284,1722,968,438) nachodzi na `alt_text` (-10,1535,329,602): widoczne przecięcie 35×415 px. `fit_heart_rate_text` (2550,1722,968,438) nachodzi na `fit_temperature_text` (3468,1535,361,602): 50×415 px. Przycięcie do 3840×2160 nie usuwa przecięć. Ponieważ GPU chart blend czyści cały bbox, nawet przezroczyste fragmenty wykresu nie uprawniają do wymuszenia GPU. Nie przesunięto, nie zmniejszono ani nie wyłączono wskaźników w końcowym rozwiązaniu. Wykresy pozostają CPU_REFERENCE i są widoczne w finalnym MP4.

Uwaga diagnostyczna: log potrafi mimo fallbacku wypisać „GPU charts AFTER-MAP ... ACTIVE” dla kandydatów. Rzeczywistość rozstrzygają aktywne sloty, zero uploadów chart i `active_gpu_charts=[]`, nie ten komunikat. Nie zmieniano klasyfikacji ani Z-order.

## 6. Minimalna poprawka
Wyłącznie `src/moving_map.py` i `tests/test_track_up_viewport_parity.py`.

Nowy prywatny helper `_rotate_track_up_viewport` używa publicznego Pillow `Image.transform`, tej samej macierzy odwrotnej (15 cyfr trig), BICUBIC i obsługi premultiplied alpha. Liczy tylko górny/lewy prefiks kończący się na końcu widocznego cropu (602×602 zamiast 706×706), z którego wycina oryginalne 499×499. Zachowano początek współrzędnych: wariant liczący tylko sam viewport z przesuniętą macierzą odrzucono, bo miał różnice zaokrągleń. Cardinal 0/90/180/270 zachowują copy/transpose. Marker directional ma ten sam początek po odjęciu całkowitego offsetu cropu.

Bez nowego demuxera, rendererów, formatu tekstur, homografii, zmian kolejności mapy, DPI, shaderów, DLL, cache kafli lub jakości interpolacji. Brak dodatkowych full-frame transferów i brak nowych buforów retained między klatkami. Jest to współdzielona funkcja CPU; backendowa neutralność obrazu potwierdzona dokładnymi rastrami i SDR, bez edycji Intel/NVIDIA.

Po zmianie sonda: viewport rotate/crop **24,740 ms**, renderer tła **0,901 ms**, cały Track-Up **25,752 ms**, pitch **0,749 ms** (warp **0,200 ms**), opacity **0,686 ms**. Map helper **27,472 ms**. W czystych przebiegach `map_cpu_upload` **26,549 / 26,836 ms**, producer **44,423 / 44,598 ms**. Przygotowanie i właściwy Render FPS raportowano osobno.

## 7. Obraz, podgląd, shape i testy
- Celowane pytest po commicie: **51 PASSED, 0 FAILED, 0 SKIPPED**, 2,59 s (`parity_tests.xml`). Testy: viewport parity, map_pitch_keeps_shape, directional marker, map_style_5w, map_perspective. Nie uruchamiano pełnego zestawu 200+.
- 72 porównania losowych rastrów RGBA (nieprzezroczyste i mieszane alpha, rozmiary 64/255/499, kąty ułamkowe/cardinal/0–360) + marker directional A→B→A: dokładna zgodność bajtowa, brak ghostingu.
- Shape kwadrat/prostokąt/koło/rounded, pitch 0/30/45/70, radius zero/clamp, ramka i alpha: istniejące testy celowane PASS.
- **Rzeczywisty Qt AppController + MainWindow**, oryginalne dwa MP4 + FIT, ten sam layout, t=60, `_render_preview_sync`: przed/po 3840×2160, **max_diff=0, MAE=0, different_pixels=0** (`qt_preview_parity.json`). Bez autozapisu do prywatnego pliku.
- **Finalne MP4 pełnego HUD**: A→P1 oraz F→P2: wszystkie 300 pakietów HEVC i 469 AAC, DTS/PTS/duration — identyczne. HLG→SDR T→P: także identyczne. SDR: wszystkie 769 pakietów identyczne. Jest to porównanie zakodowanych danych, nie zmyślona statystyka MAE z dekompresji.
- Klatkę finalnego MP4 odczytano i obejrzano (`final_frame.png`): pełny satelitarny kwadrat z pitch, trasa/marker, kompas, gauge, boczne wskaźniki, oba wykresy i cienie. Bitowa zgodność streamów zabezpiecza fonty/układ także w pozostałych badanych klatkach.
- Nie wykonano długiego eksportu ani interaktywnego testu na ekranie HDR. Kwadrat pitch 0/45 sprawdzono w A/B; koło/rounded na tym nowym kodzie sprawdzono rastrowo, bez kolejnych osobnych eksportów tych kształtów.

## 8. HDR, VBR/QP, audio, finalizacja
HLG preserve: Main10/yuv420p10le, BT.2020/ARIB STD-B67/BT2020NC full. HLG→SDR: Main/yuv420p, BT.709 limited. SDR bez regresji bitstreamu. Logi: VBR 40M/peak60M, BALANCED, sprzętowy QP feedback 300 próbek, AMF bez retry/drop. Eksporter, encoder, HDR pipeline, setts, mux, anulowanie/retry/kolejka nie były modyfikowane; pełne testy anulowania nie były powtarzane.

**Original AAC Direct Copy / Single Live Mux**: jeden FFmpeg, `-c copy`, named pipe, bez plików audio, audio_cache, pośredniego MP4 i drugiego remuxu. `aac_source_comparison.json`: 469 payloadów SHA256 identycznych z oryginałem (PTS źródła 60,010667–69,994667 s), rosnący DTS, PTS=DTS. `P_boundary`: source_switch przy global_frame=198, 308 oryginalnych pakietów klipu 1 + 159 klipu 2 + 2 **istniejące** duplikaty źródłowego pakietu granicznego — wszystkie payloady bez zmian (`boundary_audio_parity.json`), bez rekompresji. Synchronizacja graniczna wg istniejącego planu +10,667 / −6,733 ms; koniec audio 10,005333 vs video 10,010000 s. Nie modyfikowano istniejącej polityki pakietów granicznych.

Rzeczywista komenda FFmpeg z P_boundary (PID 28444):
```text
ffmpeg.exe -y -f hevc -r 30000/1001 -bsf:v setts=ts=N*1001/30000/TB:duration=1001/30000/TB -thread_queue_size 512 -i - -thread_queue_size 512 -f aac -i \\.\pipe\telem_amf_audio_14220_80787efa.aac -map 0:v -map 1:a:0 -t 10.010000 -c copy -f mp4 <P_boundary>/export.mp4.part
```
Pełne absolutne ścieżki są w `P_boundary/export.log`. Rozszerzenie `.aac` opisuje istniejący pipe w pamięci, nie plik pośredni. Windows test rzeczywisty, oryginalne GoPro, oba źródła na granicy, pump zakończył się bez deadlocku. Finalizacja P1/P2: **1.158 / 1.103 ms**; nie ekstrapoluje się tego na inne długie eksporty.

## 9. Ochrona plików i Git
Poniższe hashe przed/po są identyczne:
- `def_layout.json`: `3acf21764d6edb2df396b4f678412160035e17f331f42cbe9a29b296443025db`
- `runtime/amd/bin/telem_amd_native.dll`: `e359d7784d2ff3d2b1aefb6cf56dc1ba3c38a67260fd8d87e27851ef0d55ee89`
- `src/ffmpeg/intel_native_exporter.py`: `5ae96ea83f35bf67b5f6361238a64e3917617e627501add943f9fec9c38400ff`
- `src/ffmpeg/nvidia_native_exporter.py`: `152b4a37d72e7530ee44d5da23fefe498f284acfb848169c46c61d6eb8e6a4ff`
- `src/ffmpeg/mp4_audio_feed.py`: `09da2380e998100e6ce9af12406b78e63165cd3b63a96af89116c0791c9983b1`

Pierwsza próba harnessu dopisała do prywatnego layoutu wyłącznie `integrations.auto_activity_source=none`. Porównano cały JSON z kopią początkową i cofnięto dokładnie tę zmianę wprowadzoną przez test; końcowe bajty/SHA są identyczne z początkiem. Dalsze testy uruchamiano wyłącznie z izolowanych kopii aplikacji (ich własne def_layout.json), bez zmiany pliku użytkownika.

Commit zawiera wyłącznie 2 wskazane pliki. `git diff 1385e0d..HEAD --check` PASS. Całe `git diff --check` wykrywa zastane końcowe spacje w cudzym raporcie 5R_F (linie 6/7/188/195–203); nie poprawiano ich. Końcowe tracked working tree (wszystkie te zmiany istniały przed zadaniem):
```text
 M Raporty/RAPORT_SPORTCAMHUD_ETAP_5R_F_LIVE_MUX_AUDIO_FINALIZATION.md
 M def_layout.json
 M src/ffmpeg/intel_native_exporter.py
 M src/ffmpeg/nvidia_native_exporter.py
```
Bez push/reset/clean/stash/rebase/merge. Nie zmieniono DLL, AMF, QP, def_layout, exporterów Intel/NVIDIA ani portable użytkownika.

## 10. Portable
Nowy katalog: **`C:/_DEV/BikeRideHUD-main-new/dist/portable-amd-map-rotation-cpu-20261016`**.
- Z commita `81af3603bf8967d2734c637bfb972d6f247f4037`; 6320 plików, 1707,7 MB, embedded Python 3.14.7, wszystkie poprawki 5Z.
- Ta sama DLL e359d778…; helper z pakietu identyczny ze źródłem po normalizacji CRLF.
- Packager sprawdził wymagane eksporty/ABI/cechy HDR; import i rzeczywista transformacja przez embedded Python PASS, resolver DLL wskazuje pakiet.
- Nie uruchamiano osobnego eksportu z nowego portable; właściwe eksporty wykonano kanonicznym harnessem z izolowanych źródeł identycznych z pakietem. Nie jest to pakiet z deklaracją „odzyskano 40 FPS”.
- Nie nadpisano `portable-hdr-hlg-text-cleanup`, `portable-hdr-map-shape-fix` ani `C:/_DEV/SportCamHUD-portable`.

## 11. Otwarte problemy i koszt dalszej pracy
**40 FPS przy pełnym oryginalnym layoucie/pitch 30 — NOT ACHIEVED.** Pozostaje ~24,7 ms samego obrotu CPU i ~44,5 ms całego producenta. Budżet 40 FPS to 25 ms, więc potrzeba usunąć jeszcze około 19,5 ms przygotowania na klatkę. Samo usunięcie homografii (~0,2 ms) lub wymuszenie GPU charts tego nie zapewni. Nie wyłączono pitch ani wskaźników jako „naprawy”.

Dalsze istotne odzyskanie wymaga odrębnie zaprojektowanej ścieżki obrotu+pitch (np. końcowa homografia mapy w natywnym shaderze, zachowująca maskę/marker i Z-order), albo szybszej implementacji tego samego resamplingu CPU z pełną kontrolą rastra. To szersza zmiana niż obecne pominięcie overscanu; DLL nie została zmieniona i nie będzie przebudowywana bez odrębnej zgody. Nie wdrożono alternatywnej architektury.

Niespójność diagnostyki: `benchmark.config.pipeline=SYNC/queue0` pochodzi z `resolve_amd_config` domyślnego SYNC; faktyczny eksporter tworzy ASYNC/queue2 (`etap8t_b`, timeline i czasy queue wait). Również wstępny print potrafi użyć innego defaultu kolejki. Wnioski i tabela dotyczą rzeczywistego ASYNC, nie nagłówka fingerprintu. Naprawa samego nagłówka nie odzyska FPS, dlatego nie rozszerzano commita o konfigurację.

## 12. Artefakty i ntfy
`Raporty/amd18fps_artifacts/`: oryginalny profil/log, layout i stan początkowy, komendy/środowiska, wyniki kanonicznego harnessu, profile, monitory CPU/GPU, podoperacje mapy, zrzut guardu wykresów, testy XML, rastry Qt, finalna klatka, porównania pakietów i hashe plików chronionych. `runs_summary.json` zawiera dokładne liczby bez zaokrąglania.

Powiadomienie ntfy będzie wysłane po fizycznym zapisaniu tego raportu; odpowiedź HTTP i ID zostaną dopisane poniżej.


ntfy: HTTP 200, ID `BgqIUShdq8ny`.
