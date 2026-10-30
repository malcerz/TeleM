# SportCamHUD — CPU P0.3: presety wydajności, bitrate i Main10

## Status: SUKCES z zastrzeżeniami (patrz „Niezaliczone / NOT TESTED")

Wdrożono trzy profile CPU (Szybki / Zbalansowany / Jakość → x265 ultrafast / faster / medium) oraz rozdzielone tryby rate control (ABR z suwaka bitrate albo CRF 24). Pomiary wykonano sekwencyjnie na Ryzen 7 7730U (8C/16T, 30 GB), 300 klatek, `GX010370.MP4` + `2026-10-13_15-02-49.fit`, `def_layout.json`, 3840×2160, start klatki 900, przez rzeczywistą ścieżkę GUI (harness `--test-cpu-export`). Wszystkie pomiary zakończyły się o 22:09, przed automatycznym trybem oszczędzania energii (22:30, ok. 400 MHz) zgłoszonym przez użytkownika, więc nie są nim skażone. Throttlingu termicznego nie monitorowano.

Repo: `C:\_DEV\SportCamHUD`, gałąź `intel-60fps-preview`, HEAD 1601497, liczne niezacommitowane zmiany sprzed zadania zachowane.

## 1. Zadanie 1 — presety CPU

### Czy `faster` jest lepszym kompromisem niż `fast` (pełny eksport z HUD, ABR 16 Mb/s żądane, 300 klatek)

| preset | wall FPS | steady FPS (pipe) | x265 FPS | bitrate wideo | PSNR Y cały kadr | SSIM Y |
|---|---:|---:|---:|---:|---:|---:|
| ultrafast | 11,53 | 12,51 | 12,35 | 19,07 Mb/s | 37,00 | 0,9559 |
| **faster** | **7,28** | 7,88 | 7,60 | 18,89 Mb/s | 37,96 | 0,9659 |
| fast | 6,26 | 6,73 | 6,50 | 18,90 Mb/s | 38,12 | 0,9670 |
| medium | 4,53 | 4,91 | 4,65 | 19,00 Mb/s | 38,51 | 0,9699 |

Przy 40 Mb/s żądanych: ultrafast 10,41 / faster 6,16 / fast 5,63 / medium 3,62 FPS (PSNR cały kadr 41,68 / 42,45 / 42,53 / 43,23 dB).

**Decyzja:** `faster` jest szybszy od `fast` o 16% (16M) i 9% (40M) przy różnicy jakości 0,03–0,3 dB PSNR Y w obszarach HUD (sekcja 3), więc zatwierdzono `faster` dla „Zbalansowany". `fast` nie daje mierzalnej przewagi jakościowej.

### Mapowanie wdrożone

| Profil GUI | x265 preset | wall FPS 16M | wall FPS 40M |
|---|---|---:|---:|
| Szybki | ultrafast | 11,5 | 10,4 |
| Zbalansowany | faster | 7,3 | 6,2 |
| Jakość | medium | 4,5 | 3,6 |

Profile z GUI przez harness (`--profile`, workery auto = 4): Szybki ≈ 10,7–11,2 FPS, Zbalansowany ≈ 6,7–6,9 FPS, Jakość 4,45 FPS (16M, 300 klatek). Presety AMD, Intel i NVIDIA nie były zmieniane.

### Pomiar zasobów (okno 25–90% przebiegu, 16M)

| profil | czas do 1. klatki | finalizacja | rdzenie ffmpeg+workery+main | CPU systemu | RSS ffmpeg | RSS workerów | szczyt RAM systemu |
|---|---:|---:|---:|---:|---:|---:|---:|
| Szybki (ultrafast) | 1,22 s | 2,1 s | 13,3 | 89% | 3,3 GB | 2,4 GB | 18,1 GB |
| Zbalansowany (faster) | 1,17 s | 4,7 s | 14,6 | 95% | 4,3 GB | 2,3 GB | 18,9 GB |
| Jakość (medium) | 1,15 s | 8,1 s | 13,3 | 89% | 4,4 GB | 2,4 GB | 19,7 GB |

Rozmiary 300 klatek (10 s) przy ABR 16M: 22,9–23,1 MiB we wszystkich profilach; przy ABR 40M: 56,5–57,6 MiB.

## 2. Zadanie 2 — bitrate i rate control

### Co było źle
`libx265 -preset medium -crf 24` plus `-b:v` (z GUI, domyślnie 40M): x265 dostawał CRF, a `-b:v` było ignorowane (log `Rate Control: CRF-24.0`), więc suwak bitrate nie miał skutku.

### Co wdrożono (`src/ffmpeg/cpu_x265.py`, tylko ścieżka CPU)
- **ABR** (`Bitrate (średni, ABR)`): `-b:v <kbps>k`, bez `-crf`, bez `-maxrate` i `-bufsize`. To średni bitrate; **nie jest CBR i nie ma twardego limitu**, co jest zapisane w tooltipie GUI i logu (`[CPU] x265 preset=… rate_control=ABR avg_bitrate=…kbps (average, not CBR, no hard cap)`).
- **CRF** (`Stała jakość (CRF 24)`): `-crf 24`, bez `-b:v`; suwak bitrate wyłączany w GUI.
- Niepoprawny bitrate w ABR → jawny fallback do CRF 24 z oznaczeniem `FALLBACK` w logu, nigdy po cichu.
- `append_bitrate_args` nie dokłada już `-b:v` dla CPU.

### Weryfikacja przez GUI (suwak → opcje → ffmpeg → log x265), 300 klatek, profil Zbalansowany

| żądany bitrate | `Rate Control` w x265 | rzeczywisty bitrate wideo | odchylenie | wall FPS |
|---:|---|---:|---:|---:|
| 8 Mb/s | ABR-8000 | 9,29 Mb/s | +16% | 7,55 |
| 16 Mb/s | ABR-16000 | 18,90 Mb/s | +18% | 6,74 |
| 40 Mb/s | ABR-40000 | 47,10 Mb/s | +18% | 5,60 |
| 80 Mb/s | ABR-80000 | 93,92 Mb/s | +17% | 4,67 |
| CRF (suwak 40M ignorowany) | CRF-24.0 | 25,24 Mb/s | — | 6,29 |
| 16 Mb/s, **900 klatek (30 s)** | ABR-16000 | **16,19 Mb/s** | **+1,2%** | 7,10 |

Wnioski: ABR działa i skaluje się z żądaną wartością, ale na krótkich klipach 10 s **przekracza cel o ok. 17%** (faza początkowa regulatora, duże klatki I); na 30 s odchylenie spada do ok. 1%. Nie ma gwarancji ani limitu bitrate. Odchylenie dla krótkich klipów jest zmierzoną cechą x265 ABR, nie została ona kompensowana ani ukrywana.

Domyślne zachowanie się zmienia: nowy domyślny tryb to ABR (suwak działa), więc domyślny plik 40M będzie ok. 2× większy niż dotychczasowy CRF 24 (25 Mb/s na tym materiale). Użytkownik może wybrać „Stała jakość (CRF 24)".

## 3. Zadanie 3 — jakość HUD przy wspólnym bitrate

Metoda: referencja = ten sam eksport z `x265 lossless=1` (ta sama klatki HUD, wideo, layout; 300 klatek). Dla każdego wariantu PSNR Y i SSIM Y względem referencji, osobno w obszarach HUD (surowe piksele, bez tone mappingu). Żądane bitrate ABR identyczne; rzeczywiste: 16M → 18,89–19,07 Mb/s (±0,5%), 40M → 47,10–47,98 Mb/s (±1,9%); ultrafast ma najwyższy rzeczywisty bitrate i mimo to najgorszą jakość.

**ABR 16 Mb/s (PSNR Y dB / SSIM Y):**

| obszar | medium | fast | faster | ultrafast |
|---|---|---|---|---|
| cyfry/tekst (lewy górny róg) | 37,87 / 0,9796 | 37,77 / 0,9791 | 37,51 / 0,9771 | 35,53 / 0,9530 |
| BAR dystansu | 38,39 / 0,9822 | 38,00 / 0,9799 | 37,85 / 0,9790 | 36,67 / 0,9672 |
| BAR mocy | 36,45 / 0,9537 | 35,75 / 0,9473 | 35,59 / 0,9464 | 34,25 / 0,9278 |
| mapa i ślad GPS | 38,95 / 0,9863 | 38,71 / 0,9855 | 38,65 / 0,9853 | 36,63 / 0,9749 |
| kompas | 33,70 / 0,9580 | 33,43 / 0,9550 | 33,12 / 0,9523 | 32,29 / 0,9292 |
| prędkościomierz | 35,80 / 0,9553 | 35,28 / 0,9493 | 35,14 / 0,9479 | 34,11 / 0,9309 |
| wykres kadencji | 37,42 / 0,9593 | 36,87 / 0,9535 | 36,75 / 0,9525 | 35,33 / 0,9360 |
| wykres HR | 36,79 / 0,9508 | 36,25 / 0,9449 | 36,13 / 0,9441 | 34,97 / 0,9301 |
| bateria | 34,09 / 0,9567 | 33,71 / 0,9525 | 33,68 / 0,9521 | 33,35 / 0,9399 |
| cały kadr | 38,51 / 0,9699 | 38,12 / 0,9670 | 37,96 / 0,9659 | 37,00 / 0,9559 |

**ABR 40 Mb/s:**

| obszar | medium | fast | faster | ultrafast |
|---|---|---|---|---|
| cyfry/tekst | 42,91 / 0,9917 | 42,58 / 0,9907 | 42,35 / 0,9902 | 40,88 / 0,9820 |
| BAR dystansu | 43,22 / 0,9929 | 42,62 / 0,9915 | 42,53 / 0,9913 | 41,76 / 0,9873 |
| mapa i ślad GPS | 44,91 / 0,9962 | 44,68 / 0,9960 | 44,54 / 0,9958 | 42,73 / 0,9931 |
| kompas | 39,20 / 0,9842 | 38,50 / 0,9812 | 38,45 / 0,9808 | 37,67 / 0,9708 |
| prędkościomierz | 40,58 / 0,9823 | 39,80 / 0,9785 | 39,72 / 0,9782 | 39,05 / 0,9714 |
| wykres kadencji | 42,16 / 0,9840 | 41,38 / 0,9807 | 41,29 / 0,9804 | 40,05 / 0,9736 |
| wykres HR | 41,51 / 0,9809 | 40,82 / 0,9777 | 40,74 / 0,9774 | 39,89 / 0,9717 |
| cały kadr | 43,23 / 0,9881 | 42,53 / 0,9859 | 42,45 / 0,9856 | 41,68 / 0,9814 |

### Ocena wizualna (powiększenia 2×, klatka 150, ABR 16M; `CPU_P03_PRESETS_AND_RATE_CONTROL/frames/`)
Ocena subiektywna jednego autora na jednej klatce, na wartościach surowych HLG bez tone mappingu; to nie jest ocena na monitorze HDR.

- **Fonty i cyfry** (`digits_montage.png`, kolejno: referencja, medium, faster, ultrafast): wszystkie czytelne; medium i faster praktycznie nie do odróżnienia; ultrafast ma nieco szersze obwódki/szum wokół cyfr, nadal czytelne.
- **BAR** (`bar_montage.png`): podziałki i suwak czytelne we wszystkich wariantach; ultrafast pokazuje lekki szum wokół kresek.
- **Kompas** (`compass_montage.png`): podziałki i cyfry czytelne; ultrafast ma widoczną blokowość tła i zabarwione piksele przy igle, tło w faster jest nieco miększe niż w medium.
- **Prędkościomierz, mapa, wykresy**: ocenione wyłącznie metrykami (powyżej); nie oglądano ich powiększeń.

Podsumowanie jakości: faster względem medium traci 0,3–0,9 dB w obszarach HUD, a względem fast 0,03–0,3 dB; ultrafast względem faster traci 0,3–2,0 dB przy 16M (najwięcej cyfry i mapa ok. −2 dB) i 0,7–1,8 dB przy 40M. Szybki jest użyteczny do podglądów i szkiców; Zbalansowany jest rozsądnym domyślnym kompromisem.

## 4. Zadanie 4 — liczba workerów: 2 vs 4 (300 klatek, ABR 16M, 2 powtórzenia)

| profil | workery | wall FPS (r1 / r2) | steady FPS (r1 / r2) | do 1. klatki | finalizacja | RSS workerów | szczyt RAM systemu |
|---|---:|---|---|---:|---:|---:|---:|
| Szybki (ultrafast) | 2 | 11,22 / 10,67 | 12,18 / 11,90 | 1,06–1,14 s | 1,7–1,9 s | 1,0 GB | 20,9–21,8 GB |
| Szybki (ultrafast) | 4 | 11,03 / 10,81 | 12,13 / 11,93 | 1,19–1,21 s | 2,1–2,2 s | 2,3–2,4 GB | 21,5–22,3 GB |
| Zbalansowany (faster) | 2 | 6,84 / 6,80 | 7,55 / 7,42 | 1,07–1,08 s | 4,5–4,7 s | 1,0 GB | 21,5–22,5 GB |
| Zbalansowany (faster) | 4 | 6,90 / 6,72 | 7,50 / 7,23 | 1,17–1,21 s | 5,1–5,2 s | 2,4–2,5 GB | 22,2 GB |

Średnie: ultrafast 10,95 (2 workery) vs 10,92 (4); faster 6,82 vs 6,81. **Różnica FPS jest w granicach szumu (< 0,5%).** 2 workery dają ok. 1,4 GB mniej RSS workerów i ok. 0,1 s szybszy start, bez zysku FPS. Przy ultrafast workery zużywają ok. 1,2–1,4 rdzenia (HUD ≈ 0,1 core‑s/klatkę), więc 2 starczają na tym Ryzenie; margines przy ok. 12 FPS jest ok. 2×.

**Decyzja:** zostawiono automat z P0.2 (`max(2, min(8, wątki//4))` → 4 na 16 wątkach). Wartości 2 nie narzucono, bo pomiary dotyczą tylko tego procesora, a szybszy enkoder lub inny CPU mógłby wymagać więcej workerów. Optymalna liczba na testowym Ryzenie: 2–4 (równoważne FPS; 2 oszczędza RAM).

## 5. Stan Main10 / HLG / rotacji / audio

Sprawdzone ffprobe na wynikach (ultrafast, faster, medium; ABR 8/16/40/80M, CRF; 300 i 900 klatek):

| Kontrola | Wynik |
|---|---|
| Kodek / profil / format | HEVC Main 10, yuv420p10le (PASS) |
| HLG | color_transfer arib-std-b67, primaries bt2020, space bt2020nc, range pc (PASS) |
| Liczba klatek | 300/300 i 900/900; 45/45 dla fixture 0° (PASS) |
| Orientacja 180° | display matrix rotation −180 jak w źródle (PASS) |
| Orientacja 0° | `source_0deg.mp4`, profil Szybki, 45 klatek: brak rotacji w wyniku, `valid=True`, `color_valid=True` (PASS, ale fixture to krótki klip bez GPMF) |
| Audio | AAC LC, `-c:a copy`, jeden live mux; 9,991 s przy wideo 10,010 s; 30,023 s przy 30,030 s; brak cache audio (PASS) |
| Walidator harnessu | `valid=True`, `color_valid=True` we wszystkich 20+ przebiegach (PASS) |
| FIT | używany w każdym przebiegu; GPX/GPMF NOT TESTED w tym etapie (kod nie zmieniony) |
| Testy jednostkowe | `pytest tests/test_cpu_p03_presets.py tests/test_video_helpers.py tests/test_cpu_p0_correctness.py tests/test_nvidia_displaymatrix_fast.py`: **59 passed** (19 nowych) |

## 6. Lista zmian

- `src/ffmpeg/cpu_x265.py` (nowy): mapowanie profil→preset, parser bitrate, budowa argumentów ABR/CRF; przełączniki pomiarowe `TELEM_CPU_X265_PRESET`, `TELEM_CPU_X265_PARAMS`.
- `src/ffmpeg/command_builder.py`: CPU używa `build_cpu_x265_args`; nowy parametr `cpu_rate_mode`; usunięto przełącznik pomiarowy `TELEM_CPU_X265_ABR_KBPS` z P0.2; brak `-b:v` dokładanego dla CPU.
- `src/ffmpeg/streaming.py`: przekazanie `cpu_rate_mode`.
- `src/gui/qt/_mixins/render_mixin.py`: profil CPU i tryb rate control przekazywane do eksportu (`encoder_profile` tylko dla CPU z `cpu_profile`).
- `src/gui/qt/tabs/render_tab.py`: zamiast martwego suwaka `Preset x265` — „Profil enkodera" (Szybki/Zbalansowany/Jakość) i „Kontrola bitrate" (ABR/CRF); opcje `cpu_profile`, `cpu_rate_mode`; wyłączanie suwaka bitrate w CRF; odczyt z ustawień.
- `src/gui/qt/_mixins/preset_mixin.py`: zapis `cpu_profile`, `cpu_rate_mode` w presetach.
- `src/gui/qt/application.py`: harness `--cpu-rate-mode`, ustawianie profilu CPU z `--profile`.
- `tests/test_cpu_p03_presets.py` (nowy), skrypty i surowe wyniki w `Raporty/CPU_P02_PERFORMANCE/scripts/` oraz `Raporty/CPU_P03_PRESETS_AND_RATE_CONTROL/` (duże MP4 usunięto; zostały JSON, logi i powiększenia).

Backendy AMD/Intel/NVIDIA: nie zmieniano ich kodu ani presetów; zmiany ograniczone do `encoder == "cpu"` oraz nowych opcji GUI widocznych dla CPU.

## 7. Niezaliczone / NOT TESTED / ryzyka

- **NOT TESTED:** żywe GUI (kliknięcie kontrolek, wyłączanie suwaka bitrate w CRF, zapis i odczyt presetu projektu). Sprawdzono tylko ścieżkę harnessu, który ustawia te same widżety (`rt.cmb_cpu_profile`, `rt.cmb_cpu_rate_mode`, `rt.edit_bitrate`) i testy jednostkowe buildera.
- **NOT TESTED:** smoke AMD, Intel, NVIDIA (zmiany wspólnego kodu ograniczone do gałęzi CPU, ale `render_mixin` wywołuje `stream_overlay_to_ffmpeg` z dodatkowym `cpu_rate_mode` i dla innych backendów; przyjmuje on `**kwargs`).
- **NOT TESTED:** Golden HUD, monitor HDR, kolory HUD w HLG (osobne zadanie); GPMF/GPX.
- **NOT PROVEN:** równość pikseli HUD przed enkodowaniem między wariantami (referencja lossless pochodzi z tego samego potoku, więc pikselowa zgodność HUD jest założona, nie porównana).
- Jakość oceniana na jednym 10‑sekundowym odcinku, jednej klatce wizualnie; ABR 16M/40M na krótkim klipie przeregulowuje ok. 17%.
- Domyślny profil nowych projektów CPU to Zbalansowany (faster), a tryb ABR; stare projekty bez kluczy dostają te same domyślne wartości, co zmienia rozmiar pliku względem dawnego CRF 24.
- Wspólny parametr `cpu_rate_mode` jest w sygnaturze `_build_stream_ffmpeg_cmd` z domyślną wartością `abr`; inne ścieżki wołające builder dla CPU dostają ABR.
- Pliki `streaming.py`, `command_builder.py`, `render_mixin.py`, `render_tab.py`, `application.py` miały wcześniej niezacommitowane zmiany użytkownika; nic nie zacommitowano.
- Pomiary: pojedyncze przebiegi (workery: 2 powtórzenia), temperatura APU niemonitorowana; po 22:30 test byłby nierzetelny (CPU ok. 400 MHz) i nie był wykonywany.

Powiadomienie ntfy MalcerzPOP wysłane (status SUKCES z zastrzeżeniami).
