# SPORTCAMHUD — ETAP 4B: AMD Native FPS i GPU

Data: 2026-10-12
Repo: `C:\_DEV\BikeRideHUD-main-new`
Gałąź na starcie: `fix/gui-freeze-hud-composite`
HEAD na starcie: `896775653782e56e18e71dc4e0f1aa33712746ca`

## Status

- **DIAGNOSTIC A/B PASS** — dziewięć kontrolowanych eksportów po 3 000 klatek z rzeczywistego materiału 4K HEVC, plus osobny profil efektów.
- **CANONICAL GATE NOT RUN** — to nie jest historyczny acceptance `GX020079 + FIT`; wyników nie przedstawiam jako kanonicznego acceptance ani jako A/B z historycznym GoPro.
- **PERFORMANCE ROOT CAUSE PROVEN** dla tej konfiguracji: producent HUD jest ograniczony przez koszt CPU podczas składania efektów tekstu i wskaźników. Nie zmieniałem renderera ani wyglądu. Bezpieczna optymalizacja wymagałaby refaktoru rastryzacji i testu pikselowego, dlatego zatrzymałem się na diagnozie oraz planie.

## Wejście i dopasowanie FIT

Wszystkie wymienione MP4 ponownie otworzyły się w `ffprobe`; poniżej podaję formaty z metadanych i widoczne strumienie. Do głównego A/B wybrałem `GX010344.MP4`, bo zawiera GoPro GPMF. Metadane potwierdzają GoPro H.265, firmware `H26.02.02.02.00` i strumień `gpmd`/`GoPro MET`. Sam tag nie nazywa wprost modelu HERO13; HERO13 jest etykietą tego pliku przekazaną wraz z materiałem.

| Plik | Creation time UTC | Format / długość | Strumienie danych i FIT |
|---|---|---|---|
| `D:\Comparator\GX010344.MP4` | 2026-10-05 04:29:07 | HEVC Main 10, 3840×2160, 30000/1001 FPS, 1493.61 s | GoPro `gpmd` 1493 próbek; GPMF GPS/IMU; aktywny FIT `24609739177.fit` |
| `D:\Comparator\GX010345.MP4` | 2026-10-06 04:22:51 | HEVC, 3840×2160, 30000/1001 FPS, 1871.60 s | GoPro `gpmd` 1870 próbek; poza głównym A/B |
| `D:\Comparator\DJI_20261005062901_0004_D.MP4` | 2026-10-05 04:29:02 | HEVC, 3840×2160, 30000/1001 FPS, 1504.79 s | DJI `CAM meta` i `CAM dbgi`; poza głównym A/B |
| `D:\Comparator\DJI_20261006062240_0005_D.MP4` | 2026-10-06 04:22:41 | HEVC, 3840×2160, 30000/1001 FPS, 1883.65 s | DJI `CAM meta` i `CAM dbgi`; poza głównym A/B |
| `F:\GoPro\2026-10-05\DJI_0010.MP4` | 2026-10-05 12:53:30 | HEVC, 3840×2160, 30000/1001 FPS, 172.84 s | DJI `DJI meta` i `DJI dbgi`; poza głównym A/B |

Parą dla `GX010344.MP4` jest dokładnie `C:\_DEV\_SPORTCAMHUD_ETAP_4B_RESULTS_20261012\fit\24609739177.fit`, rozmiar 127 544 B, SHA-256 `9675932f4ce93e6b2eee249cb52c082e93426df984af55c06fe1a088b175ee61`. Istniejący indeks Garmin łączy ten FIT z klipem; ponowna walidacja przestrzenna zwróciła **VALID**, GPS overlap, 120/120 dopasowanych punktów, coverage 1.0, medianę błędu 2.65 m, p90 7.23 m, offset 0.0 s i metodę `absolute_time_trajectory_refine`.

Komenda SmartSync zwróciła jednak ogólny `INVALID`, bo jej jawne pole walidacji pliku było `null`. To nie unieważnia oddzielnego wyniku przestrzennego, ale nie oznacza pełnego kanonicznego SmartSync acceptance. Eksporty zażądały walidacji aplikacji i zakończyły się poprawnie; MP4 wynikowe raportują `output_validation.state=valid`.

## Harness i konfiguracja

`BENCHMARKS.md` wskazywał `tools/amd_performance_gate.py`, którego nie ma w checkout ani w sprawdzonych branchach/bundlu. Starszy plik w sąsiednim checkout zależy od brakującego `scratch/bench_regression_harness.py`. `scripts/test_amd_real.py` pomijałem, bo jego preflight korzysta z audio cache/preparacji niezgodnej z zakazem osobnego audio. Zamiast nazywać test ad-hoc kanonicznym, dodałem powtarzalny wrapper wokół produkcyjnego `SportCamHUD.py --test-amd-export` i osobny monitor liczników GPU per PID.

Izolowałem `APPDATA`, `LOCALAPPDATA` i `TELEM_CACHE_ROOT` do katalogu wyników. Każdy eksport korzystał z jednego źródła, tych samych 3 000 klatek od 120 s, oryginalnych 30000/1001 FPS, `FAST`, 40 Mb/s, QP 28 i ustawień AMD odziedziczonych bez override. Wszystkie pliki źródłowe pozostały tylko do odczytu. Nie wyodrębniałem audio, nie tworzyłem ADTS/audio cache, nie remuxowałem materiałów i nie przygotowywałem wideo w osobnym przebiegu. Profil potwierdza `single_pass_av_mux=true`.

Aktywna konfiguracja z profilu: pipeline `SYNC`, queue depth `0`; dekoder MF D3D11VA/P010, AMF HEVC, średni QP 28; HUD GPU `GPU_HUD`; upload `DIRTY`; NV12 `FUSED`; map `GPU`; chart `GPU_SPLIT`; gauge path zgłasza `GPU`, lecz brak aktywnego GPU gauge w tej scenie. `AMD_ABOVE_BATCHED=0`, fine dirty `0`, sparse `0`, multi-rect `1`, dirty mode `EXACT`, upload `DIRECT`. Aktywne i ignorowane env overrides raportują `{}`.

Pozostałe szczegóły profilu: `GPU_SPLIT` chart bez aktywnych klatek GPU; bezpieczny fallback heart-rate chart do CPU wynika z nakładania się `fit_heart_rate_text` z bbox. Mapa użyła źródła GPMF i przygotowania mapy; `track_map`, `iso_text` i `temp_text` w logu pochodzą z GPMF, a `speed_text` i widoczne pola treningowe z wybranego FIT. Nie dobierałem przypadkowego FIT.

## Kontrolowane A/B/C

A wyłączało w kopii layoutu globalny `text_outline` oraz outline/shadow wskaźników. B i C używały byte-identycznego layoutu użytkownika; ich SHA-256 to `8375ca40ba3670dd52de765eb91642082c9097a8fbc12dbe7fa1d1203ffa4440`. Oryginalny `def_layout.json` zachował ten sam SHA-256. B i C są więc dwoma labelami i niezależnymi powtórzeniami pełnego HUD, a nie dwiema odmiennymi konfiguracjami.

Wszystkie przebiegi: 4K HEVC, 3 000 klatek, QP 28, output valid, audio obecne, 0 zgłoszonych AMF dropped/ignored submissions.

| Wariant | Render FPS mediana (zakres) | Effective FPS mediana (zakres) | Czas aplikacji mediana | `compose_overlay` ms/klatkę mediana | `producer_prepare` ms | `consumer_queue_wait` ms | Video Codec 0 średnia aktywnego PID |
|---|---:|---:|---:|---:|---:|---:|---:|
| A — efekty OFF | 28.10 (27.08–28.95) | 27.65 (26.34–28.48) | 113.06 s | 21.43 | 34.76 | 22.22 | 73.5% |
| B — efekty ON | 11.91 (11.80–12.27) | 11.81 (11.70–12.18) | 258.81 s | 70.55 | 83.25 | 70.67 | 49.5% |
| C — pełny HUD użytkownika | 11.95 (9.41–12.20) | 11.86 (9.36–12.11) | 257.59 s | 70.27 | 82.97 | 70.39 | 49.3% |

Render FPS spada o ok. 58% z A do C; Effective FPS o ok. 57%. Wartości A/B/C pochodzą z dziewięciu surowych profili, a nie z porównania sumarycznego GPU Total. Pojedyncze wolniejsze C2 zwiększyło rozrzut, lecz pozostałe pełne-HUD powtórzenia wyniosły 11.95 i 12.20 Render FPS.

## CPU/GPU i stage timings

Monitor pobierał `Win32_PerfFormattedData_GPUPerformanceCounters_GPUEngine` dla drzewa procesów renderu. Aktywny adapter w każdym przebiegu to fizyczny adapter 0, LUID `0x00000000_0x0000B2C7` (AMD Radeon iGPU). Video Codec 0 i 3D podano jako średnie licznika aktywnego render PID; to nie jest GPU Total. Średnie 3D wyniosły 27.9% w A, 13.2% w B i 13.0% w C. Silniki `Video Decode 1` i `Copy` raportowały 0%; aplikacja równocześnie potwierdza D3D11VA dla wszystkich 3 000 klatek, 3 026 powierzchni MF oraz `decoder_gpu_copy_frames=3000`. Nie utożsamiam więc zerowego, osobnego Video Decode licznika z dekodowaniem programowym.

| Średni koszt, ms/klatkę | A OFF | B ON | C HUD |
|---|---:|---:|---:|
| Producer prepare | 34.76 | 83.25 | 82.97 |
| `compose_overlay` | 21.43 | 70.55 | 70.27 |
| PIL/buffer preparation | 10.20 | 9.79 | 9.53 |
| `consumer_queue_wait` | 22.22 | 70.67 | 70.39 |
| MF ReadSample/decode availability | 0.606 | 0.597 | 0.589 |
| Decoder surface GPU copy | 0.009 | 0.008 | 0.008 |
| HUD texture upload | 2.419 | 2.361 | 2.376 |
| AMF submit/backpressure | 0.662 | 0.502 | 0.494 |
| AMF QueryOutput | 4.248 | 4.386 | 4.406 |
| Packet write | 0.111 | 0.112 | 0.106 |
| Audio mux finalization | 0.203 | 0.202 | 0.203 |

Najdłuższe etapy oddzielnie: mediana czasu do pierwszego postępu wyniosła 5.63 s (A), 6.28 s (B), 6.17 s (C). Video render wall wyniósł medianę 103.61 s, 251.84 s i 245.93 s. Finalizacja/mux była ok. 0.20 s w medianie; A1 miało jednorazowo 0.60 s. Producer queue wait wyniósł ok. 0.03 ms/klatkę, podczas gdy konsument czekał 68–71 ms w pełnym HUD — czeka na przygotowanie klatki przez producenta. `Decode/pipe wait` i GPU wait/synchronization raportują 0. AMF, mux i transfery są znacznie krótsze niż koszt przygotowania overlayu.

GPU/CPU: drzewo eksportu zużywało średnio ok. 7.1–8.6% mocy 16-logical-CPU hosta (około 1.1–1.4 rdzenia równoważnego), przy średnim system CPU ok. 10–14%. Nie jest to nasycenie wszystkich CPU; przygotowanie overlayu działa jako dominująca jednowątkowa praca producenta. Temperatura, taktowanie limitujące i power-throttling nie były dostępne przez odczyt WMI/sterownika, więc stan throttlingu pozostaje **niezmierzony**; plan zasilania pozostał Balanced.

Upload mapy/ROI: `map_cpu_upload` trwał ok. 1.8–2.1 ms/klatkę przy ok. 5.98 GB danych mapy na 3 000 klatek. Above/HUD działał w `EXACT` dirty mode: jedna region/klatkę, 103 041 pikseli i 412 164 B/klatkę, bez full-frame alpha scan i bez fallbacków. `above_total` to ok. 0.60–0.65 ms/klatkę. Nie ma dowodu, że FULL_TILE, upload czy blokująca synchronizacja odpowiadają za główną utratę FPS.

## Koszt efektów i cache

Osobny, nieporównywalny pomiar z `TELEM_EFFECTS_CACHE_PROFILE=1`, `AMD_OVERLAY_PROFILE=1` i `AMD_PRODUCTION_ACCOUNTING=1` profilował 3 000 klatek pełnego HUD. Flagi wyłączyły się poza tym izolowanym przebiegiem. Jego FPS nie jest wynikiem „AFTER”. Zebrane czasy poniżej są licznikami kosztów wewnątrz efektów, a nie oddzielnym A/B FPS.

| Wskaźnik | Cache hit/miss | `apply_indicator_effects` suma czasu | Hash BLAKE2b | Miss render |
|---|---:|---:|---:|---:|
| `speed_text` | 1 753 / 1 248 (58.4% hit) | 120.59 s / 3 001 wywołań | 5.88 s; hash 4.26 GB alfa | 89.36 s |
| `fit_distance_text` | 2 834 / 167 (94.4% hit) | 19.19 s / 3 001 wywołań | 2.42 s; hash 1.71 GB alfa | 1.67 s |
| `fit_curVpower_text` | 1 488 / 1 513 (49.6% hit) | 11.43 s / 3 001 wywołań | 1.02 s; hash 0.71 GB alfa | 5.37 s |

Łącznie cache efektów uzyskał 6 075 hitów i 2 928 missów na 9 003 wywołania (67.5% hit). Wpisy zapełniły limit 128/128; szacowany payload samych cached RGBA rastrów to 453 852 456 B (ok. 432.7 MiB; bez narzutu obiektów). Efekt path zaalokował szacunkowo ok. 48.5 GB RGBA w ciągu całego przebiegu, głównie przez missy `speed_text`; to suma alokacji, nie jednoczesny resident memory. BLAKE2b czytał 6.69 GB kanałów alfa; tworzenie bufora `.tobytes()` zajęło ok. 0.98 s łącznie, a obliczanie hashy ok. 9.31 s.

`speed_text` miss render to dominujący koszt i odpowiada za dużą część różnicy `compose_overlay` między efektami OFF/ON. Cache jest kluczowany skrótem bieżącej maski alfa, rozmiarem i konfiguracją; przy hitach warstwa efektu jest kopiowana, po czym nakładane jest **aktualne RGB**. Zostawiłem ten bezpieczny model cache; nie przywracałem klucza opartego o `id(image)`. Efekty na RGB nie pokazują starego koloru, a test regresyjny mutated raster przechodzi.

Pozostałe liczniki w tym samym przebiegu: kompas/ROSE cache 2 403 hitów, 598 missów, 80.1% hit (64/64 wpisy); text-indicator cache 9 378 hitów i 2 626 missów, 78.1% hit (512/512); liczniki chart-dynamic zwróciły 0/0 i nie traktuję tego jako pomiaru aktywnego cache chart.

## Obraz, preview/render i regresje

- Wyeksportowane przykładowe klatki przy 50 s: A pokazuje oczekiwany diagnostyczny brak obrysu; B/C pełnego HUD pokazują czytelny ciemny outline. Pozycje/rozmiary layoutu poza stylami efektów nie zostały zmienione.
- B3/C3 korzystają z tego samego layoutu, a wyekstrahowana klatka 50 s ma identyczny SHA-256 i pikselową różnicę 0. To parytet dwóch identycznych eksportów, nie deklaracja ogólnego pixel parity preview vs render.
- W pełnym eksporcie kompas nie jest statyczny: wartość/igła zmieniła się z ok. 330° przy wyjściowych 50 s do 0° przy 90 s w obracającej się scenie.
- Test `test_compass_preview_final_surface_parity_on_bright_background` weryfikuje oba tryby NEEDLE/ROSE, zmianę 359°→1° i pikselową parę preview/final dla 960p, 1080p i 4K; test przeszedł.
- Testy efektów, aktualnego RGB, kompasu i pipeline błędów ETAPU 3: 23 passed. Łączny przebieg zestawu pięciu plików: 31 passed, 1 failed. Jedyna porażka to istniejące oczekiwanie UI schema na pole `field` w `test_compass_rendering.py::test_compass_gui_schema_exposes_common_and_compass_specific_controls`; `compass_indicator_fields()` go nie zwraca. Nie zmieniałem GUI, a błąd nie dotyczy renderera ani zmienionych plików.

## Przyczyna, poprawka i bezpieczny następny krok

Potwierdzona przyczyna niskiego użycia GPU na tym HUD to CPU produkujący efekty tekstu/wskaźników, szczególnie dynamiczny `speed_text`. Wariant OFF zwiększał Render FPS z mediany 11.95 do 28.10 i obniżał `compose_overlay` o ok. 49 ms/klatkę; równocześnie GPU Video Codec 0 spadał do ok. 49%, bo kodowanie czekało na producenta. Dekoder HEVC, GPU upload, AMF i mux nie są dominującym wąskim gardłem w tym pomiarze.

Nie wprowadzono poprawki wydajnościowej ani zmiany wyglądu. Przeniesienie lub przeprojektowanie rastryzacji outline/shadow, cache admission, zakresu/zanikania lub GPU compositingu może zmienić piksele i zachowanie dynamicznego RGB; wymaga odrębnego refaktoru. Bezpieczny plan do następnego etapu:

1. W izolowanej konfiguracji osobno zmierzyć globalny `text_outline` i trzy rasterowe cienie/outline, bez zmiany innych elementów.
2. Zoptymalizować najpierw miss-render `speed_text`, zachowując dokładny hash alfa, bieżące RGB i obecny limit bezpieczeństwa. Rozważyć limit bajtowy/admission dla cache dopiero po pomiarze hit rate.
3. Porównać obraz na golden klatkach dla kilku wartości speed, outline/shadow, różnych fade/distance i jasnego tła; wymagać zgodności preview/render oraz braku starego RGB.
4. Powtórzyć ten sam zestaw 3×3 000 klatek i zaakceptować zmianę tylko przy wyższym rzeczywistym Effective FPS, braku wzrostu resident RAM i poprawnym MP4.

## Ograniczenia i pliki wynikowe

Aktywna DLL `runtime\amd\bin\telem_amd_native.dll` zgłasza build z commita `600c2a6b18261ab71a289ef7364c7033ea9b8e25`, ABI 9, timestamp 2026-10-02. Tracked C++ encoder source jest nowszy (ostatni commit `b33d3dfae0a893a3bd94ce537510a40ce0cf43d1`). Nie przebudowałem ani nie podmieniłem DLL/rendererów; wyniki opisują faktycznie załadowany runtime i ta rozbieżność ogranicza porównanie z nowszym źródłem natywnym. Historyczny known-good commit nie został uruchomiony, bo brakowało bezpiecznego zgodnego API/binariów dla tej konfiguracji.

Pełne surowe logi, profile AMD, GPU/system CSV, MP4 wyjściowe, manifest, probe, SmartSync i obrazy są w `C:\_DEV\_SPORTCAMHUD_ETAP_4B_RESULTS_20261012`. Najważniejsze pliki: `matrix\runs.csv`, `matrix\runs.json`, `matrix\manifest.json`, `analysis_summary.json`, `gpu_engine_medians.csv`, `effect_profile_final\runs\C_user_full_hud_01.mp4.amd_profile.json`. Wyniki zostały zapisane poza repozytorium; pliki źródłowe nie były kopiowane ani modyfikowane.

`def_layout.json` zachował SHA-256 `8375ca40ba3670dd52de765eb91642082c9097a8fbc12dbe7fa1d1203ffa4440`. Zmodyfikowane wcześniej przez użytkownika raport ETAP 4 i plik audytu pozostały poza staged changes. Kod harnessu/diagnostyki/cache-profiler zapisano w commicie `54c805581bb1db3cc7f916e94f07feb36fd4481d`; raport jest osobnym commitem.
