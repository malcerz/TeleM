# SportCamHUD — CPU P0.2: profilowanie i pierwsza optymalizacja wydajności 4K

## Status: CZĘŚCIOWO (pomiary kompletne, jedna zmiana wdrożona; zysk FPS niewielki, zysk RAM/start/finalizacja potwierdzony)

Ten raport zastępuje wcześniejszą, niepełną wersję P0.2 (jeden pomiar bazowy). Dane wcześniejszej próby są nadal w `CPU_P02_PERFORMANCE/baseline/`.

## 1. Warunki

- Repo `C:\_DEV\SportCamHUD`, gałąź `intel-60fps-preview`, HEAD 1601497, liczne niezacommitowane zmiany sprzed zadania (zachowane).
- Maszyna: Ryzen 7 7730U, 8C/16T, 30 GB RAM. Wszystkie pomiary **sekwencyjne**, z przerwą 20–25 s między uruchomieniami (APU w laptopie; throttling nie był monitorowany).
- Materiał: `D:\GoPro\GX010370.MP4` + `D:\GoPro\2026-10-13_15-02-49.fit`, layout `def_layout.json`, **3840×2160**, 30000/1001, źródło HLG Main10 z rotacją 180°. Odcinek: start klatki 900, 150 klatek (300 dla przed/po i ultrafast).
- Rozdzielczość eksportu testowego potwierdzona: 3840×2160 (ffprobe wyjścia). Rozdzielczości źródła w HandBrake nie mogłem zweryfikować.
- Skrypty: `CPU_P02_PERFORMANCE/scripts/` (`bench_ffmpeg.py`, `run_harness.py`, `quality.py`, `sweep_*.sh`, `before_after.sh`). Surowe wyniki: `A_B/`, `C/`, `D/`, `presets/`, `workers/`, `beforeafter/`.

Bieżąca konfiguracja rate control CPU (`command_builder.py`): `libx265 -preset medium -crf 24` oraz `-b:v 40M`. Log x265 pokazuje `Rate Control: CRF-24.0`, czyli **`-b:v` jest ignorowane**; bitrate wynika z CRF. Nie zmieniałem semantyki rate control.

## 2. Warianty pomiarowe (150 klatek, medium, CRF 24)

| Wariant | Opis | wall FPS | steady FPS | CPU ffmpeg (rdzenie) | RSS ffmpeg peak |
|---|---|---:|---:|---:|---:|
| A0 | tylko dekodowanie (`-f null`) | 77,7 | 102,8 | 10,2 | 0,8 GB |
| A | dekodowanie + x265 medium, bez HUD | 4,79 | 4,89 (x265 4,83) | 13,7 | 3,9 GB |
| B1 | A + statyczny overlay z PNG (`-loop 1`) | 3,98 | 4,31 (x265 4,28) | 11,9 | 6,4 GB |
| B2 | A + statyczny overlay przez rawvideo pipe z Pythona | 4,05 | 4,23 (x265 4,15) | 12,3 | 4,4 GB |
| C | sam HUD: te same workery/SHM/pipe, ffmpeg tylko odrzuca RGBA (`TELEM_CPU_DIAG_NULL_SINK=1`) | ok. 28 FPS łącznie ze startem workerów (150 kl. w 5,3 s) | — | workery ok. 12 rdzeni w szczycie | workery 5,2 GB |
| D | pełny eksport z audio live mux (domyślne 15 workerów) | 3,88–4,05 | pipe 5,3–5,6; x265 4,2–4,4 | ffmpeg 13,0–13,3; workery 0,44 | ffmpeg 4,4 GB, workery 5,8 GB |

Uwagi:
- B używa syntetycznego statycznego RGBA (`scripts/static_hud_rgba.png`), nie rzeczywistego HUD. Wariant C: pomiar CPU workerów w oknie startu jest niedokładny (workery startują w trakcie); ok. 40–50 core‑s na 150 klatek, czyli **ok. 0,3 core‑s na klatkę HUD** (w tym start workerów).
- Wariant C nie kończy się poprawnym MP4 (displaymatrix) — z założenia, to diagnostyka.
- Wariant „C z pełnym potokiem bez audio" nie został wykonany osobno: audio to `-c:a copy` z oryginalnego MP4 w jednym procesie ffmpeg, bez cache; różnica D−C jest wiec nie do wyodrębnienia od x265. NOT TESTED osobno.

### Rzeczywiste wąskie gardło

1. **x265 medium na 4K Main10** — samo A osiąga 4,8 FPS i zajmuje ok. 86% z 16 wątków; dekodowanie to ok. 100 FPS.
2. Budżet CPU na klatkę (ok. 16 rdzeni / 4,3 FPS ≈ 3,7 core‑s): x265 ≈ 2,8; overlay ffmpeg (konwersja RGBA→yuva420p10 + blend) ≈ 0,35 (ok. 12%); HUD Pillow ≈ 0,3 (ok. 8–10%). Workery są prawie bezczynne (0,4–0,5 rdzenia), bo SHM jest pełne i czekają na backpressure; transport pipe nie jest ogranicznikiem (ok. 150 MB/s).
3. Wcześniejszy odczyt P0.1 „wall 3,02 FPS / pipe 23 FPS" był zdominowany przez rozruch i drenaż 30 klatek; przy 150–300 klatkach stan ustalony ≈ 4,3–4,5 FPS.
4. Finalizacja/drain 9–17 s to opróżnianie bufora x265 (lookahead 20, 4 frame threads), nie remuxing.

## 3. Presety x265 (A, decode + x265, 150 klatek, bez HUD)

Jakość: SSIM/PSNR (yuv420p10le) względem klatek źródła; to nie jest ocena HUD ani HDR.

**CRF 24 (obecna konfiguracja):**

| preset | wall FPS | x265 FPS | bitrate kb/s | SSIM | PSNR dB |
|---|---:|---:|---:|---:|---:|
| medium | 4,67 | 4,71 | 15674 | 0,98465 | 39,97 |
| fast | 7,05 | 7,14 | 15145 | 0,98333 | 39,80 |
| faster | 8,21 | 8,33 | 14959 | 0,98318 | 39,78 |
| veryfast | 8,50 | 8,63 | 14991 | 0,98316 | 39,78 |
| ultrafast | 16,89 | 17,30 | 11530 | 0,97937 | 39,30 |

**ABR 16384 kb/s (osobno, bez CRF):** rzeczywisty bitrate ok. 18,4 Mb/s dla wszystkich (przeregulowanie ABR na 5‑sekundowym klipie), więc porównanie jest przy równym bitrate.

| preset | wall FPS | x265 FPS | bitrate kb/s | SSIM | PSNR dB |
|---|---:|---:|---:|---:|---:|
| medium | 4,56 | 4,60 | 18378 | 0,98571 | 40,12 |
| fast | 7,06 | 7,14 | 18429 | 0,98475 | 40,00 |
| faster | 8,03 | 8,13 | 18459 | 0,98471 | 40,00 |
| veryfast | 8,00 | 8,10 | 18459 | 0,98469 | 40,00 |
| ultrafast | 15,68 | 16,03 | 18453 | 0,98377 | 39,92 |

Wnioski: przy równym bitrate ultrafast jest 3,4× szybszy kosztem ok. 0,2 dB PSNR (−0,0019 SSIM); fast daje 1,55× za ok. 0,12 dB. faster i veryfast praktycznie nie różnią się od fast jakościowo. Ultrafast 4K (16–17 FPS) jest w tym samym rzędzie wielkości co 21 FPS z HandBrake (rozdzielczości HandBrake nie znam). **Domyślnego presetu nie zmieniłem** (wymóg zadania; brak pomiaru jakości na rzeczywistym HUD z ostrym tekstem). To najsilniejsza dźwignia FPS — decyzja należy do użytkownika; rekomendacja: ocenić `fast` jako domyślny i `ultrafast` jako opcję „szybki".

## 4. Liczba workerów Pillow (pełny pipeline, harness)

Medium, 150 klatek:

| workery | wall FPS | czas do 1. klatki | drain | RSS workerów | szczyt RAM systemu |
|---:|---:|---:|---:|---:|---:|
| 2 | 4,26 | 1,04 s | 9,2 s | 1,0 GB | 18,5 GB |
| 4 | 4,29 | 1,14 s | 10,0 s | 2,1 GB | 19,0 GB |
| 8 | 4,24 | 1,47 s | 12,9 s | 3,8 GB | 19,9 GB |
| 15 (stare) | 4,05 | 2,20 s | 15,5 s | 5,1 GB | 21,1 GB |

Ultrafast, 300 klatek (HUD bliżej ograniczenia):

| workery | wall FPS | x265 FPS | czas do 1. klatki | drain | RSS workerów | szczyt RAM |
|---:|---:|---:|---:|---:|---:|---:|
| 2 | 11,50 | 12,23 | 1,04 s | 1,9 s | 1,1 GB | 17,2 GB |
| 4 | 11,32 | 12,09 | 1,16 s | 2,2 s | 2,4 GB | 18,0 GB |
| 8 | 10,95 | 11,88 | 1,54 s | 2,9 s | 5,4 GB | 19,3 GB |
| 15 (stare) | 10,74 | 11,98 | 2,18 s | 3,8 s | 7,8 GB | 20,9 GB |

Więcej workerów nie podnosi FPS, tylko zabiera rdzenie x265 i zwiększa RAM/SHM (pula SHM = max(4, 2×workery) slotów × 33,2 MB: 8 slotów ≈ 265 MB zamiast 30 ≈ 1 GB).

**Wdrożony automat** (`streaming.py`, tylko `encoder == "cpu"`, tylko gdy `workers is None`): `workers = max(2, min(8, logical_cpus // 4))` → 4 na 16 wątkach. Uzasadnienie: HUD potrzebuje ok. 0,3 core‑s/klatkę, a x265 jest ogranicznikiem. Dla szybszego enkodera na maszynie z większą liczbą rdzeni liczba rośnie proporcjonalnie (do 8). Nie testowano maszyn innych niż ta; granica górna 8 jest heurystyką. Ręczne ustawienie `render_threads` z presetu nadal ma pierwszeństwo.

## 5. Przed/po (ten sam odcinek: start 900, 300 klatek, medium, pełny HUD + audio)

| | wall FPS | elapsed | 1. klatka | drain | szczyt RAM systemu | RSS workerów |
|---|---:|---:|---:|---:|---:|---:|
| PRZED (15 workerów) run1 | 4,13 | 72,7 s | 2,26 s | 16,9 s | 22,35 GB | 7,9 GB |
| PRZED run2 | 4,31 | 69,6 s | 2,19 s | 14,7 s | 22,16 GB | 7,6 GB |
| PO (auto = 4) run1 | 4,34 | 69,1 s | 1,15 s | 9,1 s | 19,25 GB | 2,5 GB |
| PO run2 | 4,30 | 69,7 s | 1,15 s | 9,0 s | 19,26 GB | 2,5 GB |

Średnio: **4,22 → 4,32 FPS (+2%, w granicach szumu)**; czas do pierwszej klatki −1,0 s; drain −6,7 s; szczyt RAM systemu −3,1 GB. Poprawa FPS nie jest istotna statystycznie przy dwóch powtórzeniach; potwierdzone są zyski pamięci, startu i finalizacji. Wynik końcowy to nadal ok. 4,3 FPS, ponieważ ogranicza x265 medium.

## 6. Test poprawności po zmianie (harness, 300 klatek, oba warianty)

| Kontrola | Wynik |
|---|---|
| Liczba klatek | 300 / 300 (PASS) |
| Audio | AAC LC, 9,991 s vs wideo 10,010 s; `-c:a copy`, live mux, brak cache audio (PASS) |
| Format | HEVC Main 10, yuv420p10le, BT.2020, arib-std-b67, bt2020nc, range pc (PASS) |
| Orientacja | display matrix rotation −180 (= 180°) tak jak przed zmianą (PASS) |
| Finalizacja | walidator harnessu `valid=True`, `color_valid=True` (PASS) |
| PO vs PRZED | PSNR Y 41,98 dB (min 40,5) — różnice z niedeterminizmu x265 (frame threads); rozmiar 32,37 vs 32,38 MB. Porównania pikseli HUD przed enkodowaniem **nie wykonano** (NOT PROVEN); liczba workerów nie wpływa na indeksowanie klatek HUD. |
| Testy jednostkowe | `pytest tests/test_video_helpers.py tests/test_cpu_p0_correctness.py tests/test_nvidia_displaymatrix_fast.py`: 40 passed |
| Brakujące wskaźniki | NOT TESTED (brak porównania z Golden) |

## 7. Rozważone, nie wdrożone (brak potwierdzonego zysku)

- **Ograniczenie transferu RGBA do regionu HUD**: dla `def_layout.json` bbox HUD = 3840×2160 (cały kadr), atlas 3 regionów = 119% powierzchni — brak redukcji.
- **Zero‑copy SHM dla CPU** (render prosto w SHM zamiast `paste`): oszczędza jedną kopię 33 MB/klatkę (≈ kilka ms przy ≈ 300 ms/klatkę HUD); poniżej rozdzielczości pomiaru, więc nie wdrażane.
- **Optymalizacja HUD (cache geometrii, mapy, wykresów)**: HUD to ok. 8–10% budżetu CPU; nawet 2× tańszy HUD dałby ok. +5% FPS. Profil per‑widget nie był wykonany (audyt pipeline działa tylko dla nv/intel). Osobne zadanie.
- **Overlay ffmpeg** (≈ 12%): nie zbadano wariantów konwersji RGBA→yuva420p10 bez zmiany wyniku.
- **Zmiana presetu / ABR**: patrz sekcja 3; decyzja użytkownika.

## 8. Pozostałe ograniczenia

- Pełna zgodność Golden HUD, wszystkich wskaźników i kolorów HUD w HLG oraz test na fizycznym monitorze HDR — NIE TESTOWANO (osobne zadanie).
- Pomiary na jednej maszynie, bez monitoringu temperatury; pojedyncze powtórzenia w sweepach (przed/po: 2 powtórzenia).
- „SHM" nie mierzone bezpośrednio z systemu; podano wartości wyliczone z konfiguracji (sloty × 33,2 MB) i RSS procesów.
- Przełączniki diagnostyczne env pozostają w kodzie (tylko CPU, domyślnie nieaktywne): `TELEM_CPU_WORKERS`, `TELEM_CPU_DIAG_NULL_SINK`, `TELEM_CPU_X265_PRESET`, `TELEM_CPU_X265_ABR_KBPS`.
- Backendy AMD/Intel/NVIDIA: kod nie zmieniony (zmiana auto‑workerów ograniczona do `encoder == "cpu"`); smoke test GPU nie był uruchamiany (NOT TESTED).

## 9. Zmienione pliki

- `src/ffmpeg/streaming.py`: auto‑dobór workerów dla CPU, przełączniki `TELEM_CPU_WORKERS` i `TELEM_CPU_DIAG_NULL_SINK`, import `_fps_rational_arg`. (Plik miał wcześniej inne niezacommitowane zmiany.)
- `src/ffmpeg/command_builder.py`: przełączniki pomiarowe `TELEM_CPU_X265_PRESET`, `TELEM_CPU_X265_ABR_KBPS` (domyślnie bez efektu).
- `Raporty/RAPORT_CPU_P02_PERFORMANCE.md`, `Raporty/CPU_P02_PERFORMANCE/**` (skrypty i surowe wyniki; duże pliki MP4 wariantów usunięto).

Powiadomienie ntfy: wynik dopisany niżej po wysłaniu.

Powiadomienie ntfy MalcerzPOP wysłane: DMeNBWINZM0d, status CZĘŚCIOWO.
