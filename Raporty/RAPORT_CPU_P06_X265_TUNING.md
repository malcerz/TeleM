# SportCamHUD — CPU P0.6: strojenie libx265

## Decyzja: ODRZUCIĆ strojenie, konfiguracja libx265 bez zmian

Żaden parametr nie przekroczył preferowanego progu +10% FPS. Najlepszy kandydat, `lookahead-threads=4` dla profilu Szybki (ultrafast), daje **+7,2% powtarzalnie** (zarówno w benchmarku z HUD, jak i w prawdziwym eksporcie harnessu) przy **bit‑w‑bit identycznym pliku** (te same md5), czyli bez żadnej zmiany jakości. To realny, ale mały zysk, a wartość nie była sprawdzona na innych procesorach, więc zgodnie z wymogiem „bez ustawień tylko pod jeden model CPU" nie jest wdrożona. Zbalansowany (faster) i Jakość (medium) nie mają żadnego wariantu wątkowania z mierzalnym zyskiem. **W `src/` i `tests/` nie zmieniono żadnego pliku w tym etapie.**

## 0. Zamknięcie P0.5 (Git)

Gałąź `cpu-optimization`, HEAD przed etapem `d6ee6b0` = `origin/cpu-optimization` (0/0 rozbieżności). Zmiany NVIDIA, Intel, AMD i telemetrii pozostały niezacommitowane i nietknięte (nic nie było w indeksie). Commit dokumentacyjny P0.5: **`057f35e` docs(cpu): archive P0.5 ROI overlay experiments** (77 plików, raport + skrypty, planer prototypu, pomiary i mapy; bez zrzutów RGBA/YUV i wideo). ROI nie wdrożono i nie powtarzano jego benchmarków.

## 1. Parametry x265

Domyślna konfiguracja zgłaszana przez x265 4.3 (build 10‑bit, ABR 16 000 kb/s, 16 wątków logicznych, AMD Ryzen 7 7730U):

| Preset (profil) | pula wątków | frame‑threads | wpp | rc‑lookahead | bframes / b‑adapt | scenecut | wykorzystanie CPU |
|---|---:|---:|---|---:|---|---:|---:|
| ultrafast (Szybki) | 16 | 4 | włączone (68 wierszy CTU) | 5 | 3 / 0 | 40 | 82–84% |
| faster (Zbalansowany) | 16 | 4 | włączone (34 wiersze) | 15 | 4 / 0 | 40 | 84–88% |
| medium (Jakość) | 16 | 4 | włączone (34 wiersze) | 20 | 4 / 2 | 40 | 84% |

Testowane: `frame-threads` 2/3/5/6/8, `pools` 8/12, `wpp=0`, `lookahead-slices` 0/4, `lookahead-threads` 2–8, `pmode`, `pme`, oraz parametry zmieniające kodowanie (tylko pomiar): `rc-lookahead` 5/10/20/30, `bframes` 0/1/2/6, `scenecut=0`, `ctu=32`, `ref=2`. Poza zakresem celowo: wyłączanie mechanizmów jakości (SAO, AQ, psy‑rd, rskip, subme, rd…).

## 2. Metoda

- Materiał: `D:\GoPro\GX010370.MP4`, FIT `2026-10-13_15-02-49.fit`, `def_layout.json`, 3840×2160 HEVC Main10 HLG, start klatki 900, ABR 16 Mb/s żądane, profil Main10 yuv420p10le, BT.2020 HLG, `-noautorotate` jak w eksporcie CPU.
- **Sweepy**: ten sam graf FFmpeg co w produkcji (RGBA HUD → `auto_scale` → `yuva420p10le` → `overlay` 10‑bit), klatka HUD z harnessu CPU zapętlona z pliku, prawdziwe dekodowanie; 300 klatek, sekwencyjnie, 8 s przerwy, baza przeplatana co kilkanaście przebiegów (dryf bazy ±1%).
- **Potwierdzenie**: kanoniczny harness `--test-cpu-export` (workery Pythona, HUD zmienny w czasie, live mux audio, walidator MP4), przebieg 300 klatek, 3 pary naprzemiennie.
- **Jakość**: referencja lossless (`x265 lossless=1`) z tym samym grafem i HUD; PSNR/SSIM per obszar (cyfry, BAR‑y, kompas, prędkościomierz, mapa, wykresy) i cały kadr.
- Pomiary 08:35–09:55, tryb wydajności. W trakcie sweepów nie działały inne obciążenia.

## 3. Wyniki: wątkowanie i parametry zmieniające kodowanie

Sweep 1, ultrafast (baza: n=4, średnia 12.57 FPS)

| wariant | wall FPS | zmiana vs baza | CPU % z 16 | RSS ffmpeg MB | bitrate kb/s | do 1. klatki | finalizacja |
|---|---:|---:|---:|---:|---:|---:|---:|
| ft2 | 12.55 | -0.1% | 83 | 2904 | 19349.46 | 1.09 s | 0.14 s |
| ft3 | 12.47 | -0.8% | 83 | 3008 | 19303.94 | 1.60 s | 0.14 s |
| ft5 | 12.34 | -1.8% | 83 | 3767 | 19404.36 | 1.60 s | 0.22 s |
| ft6 | 12.58 | +0.1% | 84 | 3310 | 19321.03 | 1.60 s | 0.14 s |
| ft8 | 12.44 | -1.0% | 82 | 4200 | 19253.89 | 1.59 s | 0.22 s |
| pools8 | 10.86 | -13.6% | 63 | 2959 | 19303.94 | 1.59 s | 0.15 s |
| pools12 | 12.66 | +0.7% | 80 | 2960 | 19303.94 | 1.59 s | 0.11 s |
| wpp0 | 10.96 | -12.8% | 63 | 4635 | 19140.24 | 3.66 s | 0.20 s |
| wpp0_ft8 | 10.17 | -19.1% | 52 | 3740 | 19248.59 | 2.63 s | 0.14 s |
| las0 | 9.60 | -23.7% | 61 | 3346 | 19250.84 | 1.60 s | 0.15 s |
| las4 | 12.45 | -0.9% | 80 | 3765 | 19264.54 | 1.60 s | 0.15 s |
| lat2 | 11.86 | -5.6% | 75 | 3739 | 19284.6 | 1.60 s | 0.17 s |
| lat4 | 13.50 | +7.4% | 91 | 3674 | 19284.6 | 1.59 s | 0.15 s |
| pmode | 10.54 | -16.2% | 85 | 3825 | 19202.78 | 1.60 s | 0.17 s |
| pme | 12.56 | -0.0% | 83 | 3147 | 19284.6 | 1.61 s | 0.17 s |

Sweep 1, faster (baza: n=4, średnia 7.51 FPS)

| wariant | wall FPS | zmiana vs baza | CPU % z 16 | RSS ffmpeg MB | bitrate kb/s | do 1. klatki | finalizacja |
|---|---:|---:|---:|---:|---:|---:|---:|
| ft2 | 6.98 | -7.0% | 74 | 4294 | 19129.63 | 2.10 s | 0.20 s |
| ft3 | 7.46 | -0.6% | 86 | 4336 | 19082.59 | 2.62 s | 0.21 s |
| ft5 | 7.52 | +0.2% | 87 | 4659 | 19004.98 | 2.63 s | 0.23 s |
| ft6 | 7.50 | -0.1% | 88 | 5543 | 19163.7 | 2.65 s | 0.26 s |
| ft8 | 7.55 | +0.6% | 88 | 5135 | 19051.64 | 2.63 s | 0.27 s |
| pools8 | 6.92 | -7.8% | 58 | 4281 | 19082.59 | 2.12 s | 0.19 s |
| pools12 | 7.43 | -1.0% | 80 | 4340 | 19082.59 | 2.63 s | 0.23 s |
| wpp0 | 4.02 | -46.4% | 36 | 9750 | 19103.78 | 8.84 s | 0.55 s |
| wpp0_ft8 | 3.82 | -49.1% | 34 | 9445 | 19041.27 | 6.74 s | 0.50 s |
| las0 | 6.62 | -11.8% | 74 | 5448 | 19017.52 | 2.64 s | 0.22 s |
| las4 | 7.53 | +0.3% | 87 | 5135 | 19015.05 | 2.64 s | 0.19 s |
| lat2 | 7.57 | +0.9% | 88 | 4591 | 19027.91 | 2.62 s | 0.18 s |
| lat4 | 7.49 | -0.2% | 83 | 4539 | 19027.91 | 2.63 s | 0.18 s |
| pmode | 5.90 | -21.4% | 89 | 6072 | 19025.77 | 2.65 s | 0.28 s |
| pme | 7.26 | -3.2% | 87 | 4609 | 19027.91 | 2.63 s | 0.21 s |

Sweep 2, ultrafast (baza: n=4, średnia 12.57 FPS)

| wariant | wall FPS | zmiana vs baza | CPU % z 16 | RSS ffmpeg MB | bitrate kb/s | do 1. klatki | finalizacja |
|---|---:|---:|---:|---:|---:|---:|---:|
| lat3 | 13.14 | +4.5% | 86 | 3671 | 19284.6 | 1.60 s | 0.16 s |
| lat4 | 13.29 | +5.7% | 92 | 3135 | 19284.6 | 1.61 s | 0.13 s |
| lat5 | 13.33 | +6.1% | 87 | 3731 | 19284.6 | 1.59 s | 0.15 s |
| lat6 | 12.96 | +3.1% | 85 | 3793 | 19284.6 | 1.60 s | 0.16 s |
| lat8 | 12.25 | -2.5% | 76 | 3617 | 19284.6 | 1.61 s | 0.16 s |
| ft2_lat4 | 13.40 | +6.6% | 90 | 3449 | 19349.46 | 1.08 s | 0.17 s |
| ft3_lat4 | 13.41 | +6.7% | 91 | 2928 | 19303.94 | 1.60 s | 0.12 s |
| ft6_lat4 | 13.72 | +9.1% | 91 | 3248 | 19321.03 | 1.59 s | 0.11 s |
| lat4_pools12 | 12.53 | -0.4% | 78 | 2938 | 19303.94 | 1.59 s | 0.11 s |
| lat4_las4 | 13.38 | +6.4% | 89 | 3827 | 19264.54 | 1.59 s | 0.19 s |
| rcla10 | 12.15 | -3.4% | 80 | 3419 | 19340.17 | 1.60 s | 0.16 s |
| rcla20 | 12.13 | -3.5% | 79 | 3958 | 19397.81 | 2.10 s | 0.18 s |
| bf0 | 12.60 | +0.2% | 76 | 2604 | 19233.05 | 1.07 s | 0.09 s |
| bf1 | 13.20 | +5.0% | 83 | 2829 | 19070.09 | 1.59 s | 0.13 s |
| bf6 | BŁĄD | — | — | — | — | — | — |
| sc0 | 12.66 | +0.7% | 84 | 3799 | 19284.6 | 1.60 s | 0.16 s |
| ctu32 | 12.57 | +0.0% | 84 | 3161 | 19284.6 | 1.58 s | 0.10 s |
| lat4_ctu32 | 13.62 | +8.3% | 91 | 3550 | 19284.6 | 1.58 s | 0.15 s |

Sweep 2, faster (baza: n=2, średnia 7.51 FPS)

| wariant | wall FPS | zmiana vs baza | CPU % z 16 | RSS ffmpeg MB | bitrate kb/s | do 1. klatki | finalizacja |
|---|---:|---:|---:|---:|---:|---:|---:|
| lat3 | 7.56 | +0.6% | 86 | 4553 | 19027.91 | 2.63 s | 0.22 s |
| lat6 | 7.07 | -5.9% | 75 | 4515 | 19027.91 | 2.64 s | 0.18 s |
| lat8 | 6.38 | -15.1% | 64 | 4489 | 19027.91 | 2.65 s | 0.19 s |
| ft3_lat4 | 7.45 | -0.9% | 82 | 4299 | 19082.59 | 2.11 s | 0.19 s |
| rcla5 | 7.57 | +0.8% | 89 | 4040 | 18879.27 | 2.10 s | 0.17 s |
| rcla30 | 7.38 | -1.8% | 86 | 7342 | 19041.08 | 3.14 s | 0.33 s |
| bf2 | 7.54 | +0.4% | 86 | 4708 | 19346.12 | 2.10 s | 0.24 s |
| bf6 | 7.38 | -1.8% | 88 | 5489 | 18885.94 | 2.61 s | 0.29 s |
| sc0 | 7.52 | +0.1% | 87 | 4584 | 19027.91 | 2.63 s | 0.19 s |
| ctu32 | 7.97 | +6.1% | 84 | 5014 | 18976.46 | 2.12 s | 0.28 s |
| ref2 | 7.48 | -0.4% | 87 | 4607 | 19027.91 | 2.13 s | 0.25 s |

Uwagi: „baza" to średnia przebiegów bez parametrów w danym sweepie. `bf6` w ultrafast: pierwszy przebieg zawiesił się (890 s, błąd odczytu wejścia), a powtórzenie zakończyło się natychmiast błędem; wariant uznany za niewspierany i nie badany dalej. `faster` ma przy `ctu=32` o ok. 0,2–0,3% mniejszy bitrate, `bframes=1` w ultrafast daje o 1,1% mniejszy.

## 4. Powtarzalność kandydatów (ultrafast, 4 pary naprzemiennie, 300 klatek)

| Wariant | wall FPS (4 przebiegi) | średnia | zysk vs baza | zysk w parach | CPU % z 16 | bitrate kb/s | RSS ffmpeg |
|---|---|---:|---:|---|---:|---:|---:|
| baza | 12,54 / 12,67 / 12,68 / 12,60 | 12,62 | — | — | 83,3 | 19 285 | 3,5 GB |
| `lookahead-threads=4` | 13,48 / 13,30 / 13,71 / 13,65 | 13,53 | **+7,2%** | 5,0–8,4% | 90,8 | 19 285 | 3,4 GB |
| `lookahead-threads=5` | 13,59 / 13,39 / 13,52 / 13,49 | 13,50 | +7,0% | 5,7–8,4% | 89,5 | 19 285 | 3,4 GB |
| `frame-threads=6:lookahead-threads=4` | 13,64 / 13,34 / 13,54 / 13,64 | 13,54 | +7,3% | 5,4–8,8% | 90,3 | 19 321 | 3,2 GB |
| `frame-threads=8:lookahead-threads=4` | 13,58 / 13,49 / 13,67 / 13,66 | 13,60 | +7,8% | 6,5–8,4% | 90,9 | 19 254 | 3,9 GB |

Faster, 2 pary: `ctu=32` +5,5% (4,6% i 6,4%), kosztem zmiany kodowania. Medium (150 klatek, pojedyncze przebiegi): baza 4,40 / 4,38 FPS, `lookahead-threads=4` 4,58 (+4%, mieści się w szumie jednego przebiegu), `lookahead-threads=3` 4,30, `ctu=32` 4,07 (−7%); brak potencjału, Jakość bez zmian.

## 5. Jakość względem lossless (150 klatek, ABR 16 Mb/s; PSNR Y dB / SSIM Y)

| Obszar | ultra baza | ultra `lat4` | ultra `ft6+lat4` | ultra `bf1` | faster baza | faster `ctu32` | faster `bf2` |
|---|---|---|---|---|---|---|---|
| cyfry i tekst | 36,62/0,9644 | 36,62/0,9644 | 36,29/0,9639 | 36,64/0,9647 | 38,50/0,9836 | 38,43/0,9834 | 38,60/0,9841 |
| BAR dystansu | 39,30/0,9763 | 39,30/0,9763 | 39,14/0,9759 | 39,11/0,9754 | 41,35/0,9860 | 41,19/0,9855 | 41,43/0,9865 |
| BAR mocy | 36,26/0,9501 | 36,26/0,9501 | 36,14/0,9486 | 36,05/0,9482 | 37,83/0,9653 | 37,78/0,9655 | 37,96/0,9666 |
| mapa i ślad GPS | 37,27/0,9780 | 37,27/0,9780 | 37,28/0,9782 | 37,38/0,9785 | 39,45/0,9876 | 39,42/0,9877 | 39,38/0,9873 |
| kompas | 35,53/0,9555 | 35,53/0,9555 | 35,42/0,9558 | 35,50/0,9562 | 37,56/0,9779 | 37,58/0,9780 | 37,57/0,9786 |
| prędkościomierz | 35,28/0,9498 | 35,28/0,9498 | 34,93/0,9476 | 35,17/0,9483 | 36,35/0,9635 | 36,35/0,9634 | 36,54/0,9652 |
| wykres kadencji | 36,83/0,9510 | 36,83/0,9510 | 36,62/0,9492 | 36,55/0,9477 | 38,41/0,9645 | 38,36/0,9640 | 38,47/0,9652 |
| wykres HR | 37,79/0,9637 | 37,79/0,9637 | 37,62/0,9631 | 37,60/0,9623 | 39,42/0,9744 | 39,38/0,9743 | 39,52/0,9750 |
| bateria | 36,91/0,9636 | 36,91/0,9636 | 36,48/0,9618 | 37,06/0,9638 | 39,65/0,9834 | 39,58/0,9830 | 39,80/0,9839 |
| **cały kadr** | **39,39/0,9718** | **39,39/0,9718** | 39,17/0,9712 | 39,19/0,9705 | **40,62/0,9787** | 40,53/0,9783 | 40,75/0,9793 |

- `lookahead-threads=4`: plik **bit‑w‑bit identyczny** z bazą (`md5 57065ea8e736cebcf580d3a6a519aa23` dla obu), więc różnice jakości = 0, w tym półprzezroczystości i kolorów HUD.
- `frame-threads=6`: lekki spadek (−0,2 dB cały kadr, do −0,4 dB w cyfrach, prędkościomierzu i baterii), bez zysku FPS ponad `lat4`; odrzucony.
- `bframes=1`: −0,2 dB cały kadr i SSIM −0,0013; `ctu=32` (faster) −0,09 dB i SSIM −0,0004 przy +5,5% FPS; `bframes=2` (faster) +0,13 dB bez zmiany FPS.
- Ocena nie opiera się na bitrate: bitrate różni się maks. o 1–2% między wariantami, a PSNR/SSIM policzono względem klatek lossless.

## 6. Potwierdzenie w prawdziwym eksporcie (harness, Szybki, 300 klatek, ABR 16M, 3 pary naprzemiennie)

| | wall FPS | steady FPS (rura) | do 1. klatki | finalizacja | rdzenie (ffmpeg+workery+main) | CPU systemu | RSS ffmpeg+workery | szczyt RAM systemu | bitrate | MP4 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| baza (`-b:v 16000k`, ultrafast) | 10,99 / 11,12 / 11,12 = **11,08** | 12,14 | 1,00 s | 1,81 s | 13,13 | 90,2% | 4,33 GB | 18,05 GB | 19 074 | 300/300 poprawne |
| `lookahead-threads=4` | 11,90 / 11,78 / 11,93 = **11,87** | 12,95 | 0,99 s | 1,70 s | 13,90 | 94,4% | 4,24 GB | 18,02 GB | 19 074 | 300/300 poprawne |

**FPS przed/po: 11,08 → 11,87 (+7,2%)**, każdy przebieg z `lookahead-threads=4` szybszy od każdego przebiegu bazy; start, finalizacja i RAM bez regresji. Ta konfiguracja nie jest wdrożona.

## 7. Dlaczego odrzucone

1. Zysk +7,2% < preferowany próg +10%; żaden inny wariant nie wyszedł poza szum.
2. Dla Zbalansowanego i Jakości nie ma wariantu wątkowania z mierzalnym zyskiem (`lookahead-threads` ≥ 6 i `pmode` szkodzą, `frame-threads=2`, `pools=8` −7–8%); `ctu=32` i `bframes` zmieniają kodowanie za kilka procent FPS.
3. `lookahead-threads=4` nie jest uniwersalny: optimum zależy od liczby wątków i obciążenia (`lat2` −5,6%, `lat8` −2,5% przy 16 wątkach); wartości nie zbadano na innych CPU, a stała 4 byłaby dostrojona do jednego modelu. Wzór `logiczne_CPU // 4` jest hipotezą bez pomiarów na innych procesorach.
4. Mechanizmy jakości (scenecut, rc‑lookahead, b‑adapt) pozostają włączone; `scenecut=0` nie daje żadnego zysku (+0,7% / +0,1%), więc nie ma powodu go ruszać.

**Jeśli zdecydujecie inaczej:** wariant do rozważenia dla profilu Szybki to `lookahead-threads` = ok. ¼ liczby wątków logicznych (4 przy 16), po zmierzeniu na co najmniej jednym innym CPU. Można go już teraz sprawdzić bez zmian w kodzie przez diagnostyczną zmienną `TELEM_CPU_X265_PARAMS=lookahead-threads=4` (działa dla wszystkich profili; dla faster/medium bez efektu).

## 8. Testy poprawności

| Kontrola | Wynik |
|---|---|
| Harness CPU, 6 przebiegów (baza i `lat4`), MP4 | wszystkie `valid=True`, 300/300 klatek |
| Pliki wyników sweepów: Main10 yuv420p10le HLG BT.2020 | parametry wywołania identyczne jak w produkcji (`-profile:v main10 -pix_fmt yuv420p10le`, BT.2020, arib‑std‑b67, range pc) |
| Rotacja 0°/180°, displaymatrix, audio live mux, FIT/GPX/GPMF | NIE ZMIENIANE (brak zmian w kodzie); w harnessie jak w P0.4 |
| Testy jednostkowe (`test_cpu_p03_presets`, `test_cpu_golden_p04`, `test_cpu_p0_correctness`, `test_video_helpers`) | 54 passed, 1 skipped |
| AMD/Intel/NVIDIA | bez zmian (kod nietknięty) |

## 9. NOT TESTED / ograniczenia

- Inne procesory niż Ryzen 7 7730U; inne liczby wątków dla `lookahead-threads` i `frame-threads`.
- Profil Jakość (medium): tylko 150‑klatkowe pojedyncze przebiegi (4 warianty), bez harnessu.
- Sweepy używają jednej klatki HUD w pętli (bez zmienności HUD i bez workerów); potwierdzenie na prawdziwym eksporcie wykonano tylko dla kandydata `lookahead-threads=4` w profilu Szybki.
- Parametry wyłączające mechanizmy jakości nie były badane (zgodnie z poleceniem).
- Czas pomiarów 08:35–09:55; temperatura APU niemonitorowana.

## 10. Pliki i Git

- Dodane w tym etapie: `Raporty/RAPORT_CPU_P06_X265_TUNING.md`, `Raporty/CPU_P06_X265_TUNING/` (skrypty `bench_x265.py`, `sweep_*.sh`, `quality_and_harness.sh`; logi i JSON sweepów; `q/` wyniki jakości; `harness/` wyniki potwierdzenia).
- Brak zmian w `src/` i `tests/`; zmiany GPU/telemetrii spoza P0.6 nie są w commicie.
- Commit P0.5: `057f35e`. Commit P0.6 i weryfikacja SHA na `origin/cpu-optimization`: patrz `git log`; potwierdzone w odpowiedzi końcowej zadania.
