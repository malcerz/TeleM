# SportCamHUD — CPU P0.5: ROI HUD i optymalizacja nakładania 4K

## Decyzja: ODRZUCIĆ regionowy overlay na standardowym FFmpeg; pipeline CPU bez zmian

Prototyp regionowy jest **w pełni poprawny pikselowo** (90/90 przypadków bit‑w‑bit identycznych z pełnym overlayem, 0 pikseli alfa poza regionami), ale **nie daje powtarzalnego zysku FPS**: najlepsze plany to +0,7% do +1,9% (Szybki, strona FFmpeg), plan o najmniejszej powierzchni jest o 5,2% wolniejszy, a przy `faster` −1,1%. Powód: każdy kolejny `overlay` w łańcuchu kosztuje ok. 2,9 ms (kopia klatki głównej 4K 10‑bit), co odpowiada ok. 17% powierzchni kadru, więc przy rzeczywistej geometrii HUD optimum planu to jeden region o powierzchni 84–98% kadru, czyli praktycznie pełny overlay. Zgodnie z wymogiem zadania wdrożenie produkcyjne nie nastąpiło: **w `src/` nie zmieniono żadnego pliku w tym etapie**. Prototyp, planer i wyniki są zachowane w `Raporty/CPU_P05_ROI_OVERLAY/`.

Stan wyjściowy bez zmian: Golden HUD, Main10 HLG, rotacja 0°/180°, live mux audio, 2 workery, 3 profile x265, ABR/CRF. Testy jednostkowe po etapie: 23 passed, 1 skipped (brak zmian w kodzie produkcyjnym).

## 1. Warunki pomiaru

Ryzen 7 7730U (8C/16T), pomiary 07:25–07:57 w trybie wydajności (kontrola: dekodowanie 76 FPS). Sekwencyjnie, przerwy 15–25 s. Wideo: `D:\GoPro\GX010370.MP4` start klatki 900, 3840×2160 HLG Main10, `-noautorotate`. HUD: prawdziwe klatki zrzucone z rury eksportu (hak `TELEM_CPU_DIAG_DUMP_*` z P0.4) dla **trzech layoutów**: `def_layout.json`, preset `cycling_dashboard_v10` (15 wskaźników) i `cycling_dashboard_v3` (13 wskaźników), w **pięciu momentach** eksportu (klatki 0, 80, 160, 240, 319), w orientacji zapisu (obrót 180°). Pomiary izolowane używają pętli jednej klatki HUD z pliku (bez kosztu transportu z Pythona).

## 2. Etap 1 — mapa zajętości HUD i planer regionów

Maska zajętości = rzeczywisty kanał alfa (alfa > 0, czyli także cienie i antyaliasing), suma po klatkach próbnych, dylatacja o margines (8/16/32 px, zaokrąglany w górę do kafli), siatka kafli 16/32/64 px, następnie **partycja guillotine** (cięcia tylko wzdłuż pustych pasów, kosztowo: pole + stały koszt regionu), ograniczenie liczby regionów przez scalanie o najmniejszym przyroście pola, wyrównanie do parzystych współrzędnych (YUV420), pakowanie półkowe do atlasu. Planer nie zna layoutu; plan powstaje tylko z pikseli, jednorazowo przed eksportem (10–11 ms), a nie z pełnej maski w każdej klatce.

| Layout | alfa>0 na klatkę | alfa>0 suma po 5 klatkach | regionów (min. powierzchnia, kafel 16, ov 60k) | powierzchnia regionów | atlas |
|---|---:|---:|---:|---:|---:|
| `def_layout.json` | 11,96–11,99% | 12,54% | 11 | 39,9% 4K | 56,0% |
| preset v10 | 9,27–9,29% | 9,54% | 1 (nie da się podzielić) | 84,3% | 84,3% |
| preset v3 | 10,28–10,49% | 10,94% | 8 | 39,6% | 50,7% |

Aktywny HUD to 9,5–12,5% pikseli, ale zajmuje 40–84% powierzchni po objęciu prostokątami; v10 jest układem „młynka" (wykresy u góry, linijki po bokach, tarcza w środku, mapa po lewej), w którym nie ma pustego pasa przecinającego cały obszar. Mapy planów: `analysis/roi_map_*_tile16_m16_ov60k.png` (obraz w orientacji zapisu, czyli obrócony o 180°; pomarańczowe prostokąty = regiony), maski `analysis/alpha_union_*.png`, siatka 64 px `analysis/occupancy_grid_*_64px.txt`. Dla layoutu `def` (stara metoda `get_layout_hud_regions`: atlas 119% powierzchni):

| Wariant planu (def) | regiony | powierzchnia | atlas |
|---|---:|---:|---:|
| kafel 16, koszt regionu 60 kpx (minimalna powierzchnia) | 11 | 39,9% | 56,0% |
| kafel 32, koszt 60 kpx | 8 | 52,6% | 69,0% |
| kafel 16, koszt regionu 1,4 Mpx (optimum wg zmierzonego kosztu) | 1 | 97,6% | 97,6% |
| kafel 64 | 1 | 100% | 100% |

Dokładność planowania (wszystkie warianty kafel 16/32/64 × margines 8/16/32 × 2 koszty × 3 layouty): **0 pikseli alfa poza regionami**, w tym w teście leave‑one‑out (plan z 4 klatek, 5. klatka jako nieznana: 0 pikseli poza planem), 0 par nakładających się regionów. Dynamiczne elementy (wskazówka, wykresy, wartości) mieszczą się w planie z marginesem 16 px; test obejmuje tylko 5 momentów z 320‑klatkowego odcinka, nie pełny przebieg.

### Błąd znaleziony w prototypie
Pierwsza wersja planera (obwiednie składowych spójnych) dawała regiony nachodzące na siebie. Półprzezroczysty cień (RGBA 0,0,0,123) w strefie nakładania był blendowany dwukrotnie: 1504 próbek luma z różnicą do 256 kodów 10‑bit. Naprawa: regiony zawsze rozłączne (partycja guillotine, wymuszone scalanie nakładających się). To warunek poprawności każdej przyszłej implementacji regionowej.

## 3. Etap 2 — strategie A/B

| Strategia | Opis | Wynik |
|---|---|---|
| **A** | obecny: pełnoklatkowy RGBA → `auto_scale` → `yuva420p10le` → `overlay=0:0` | punkt odniesienia |
| **B1** | atlas regionów w rurze, 1× konwersja atlasu, `split` + `crop` + łańcuch `overlay=x:y` na pozycjach źródłowych (min. powierzchnia, 8–11 regionów) | bit‑exact, **wolniejszy** |
| **B2** | jak B1, każdy region konwertowany osobno po `crop` | bit‑exact, bez różnicy względem B1 (19,3–19,6 FPS vs 19,5) |
| **B3** | 1–2 regiony (plan wg zmierzonego kosztu) | bit‑exact, zysk ≤ 1,9% |
| C | własny filtr C `hudblend` (jeden filtr, tablica regionów, blend in‑place, wielowątkowy) | NIE ZAIMPLEMENTOWANE — szacunek poniżej |
| D | pasy poziome: `crop` bazy, overlay tylko na pasach z HUD, `vstack` | NIE MIERZONE: `vstack` kopiuje całą klatkę, więc łączny koszt kopii nie spada |

Zgodnie z poleceniem nie dzielono wideo na fragmenty, nie kodowano kafli osobno, nie wykonywano dodatkowego remuxu ani wydzielania audio. Wariant B używa wyłącznie standardowych filtrów FFmpeg (`crop`, `split`, `overlay`), bez własnego filtra i bez C/C++.

### Szacunek kosztu wariantu C (własny filtr)
FFmpeg nie ładuje filtrów jako wtyczek, więc filtr musiałby być wkompilowany w własny build. Repo dostarcza gotowy `runtime/common/ffmpeg/ffmpeg.exe` (build `2026-08-17-git-426841da9d-full_build`), z libx265 i wieloma bibliotekami zewnętrznymi; trzeba by odtworzyć ten zestaw, utrzymywać własny fork i przebudowywać go przy każdej aktualizacji FFmpeg. Nakład: kilka dni na filtr (ok. 300–400 linii C + testy bit‑exact) plus build i utrzymanie. Oczekiwany zysk: koszt overlay spadłby z ok. 0,133 core‑s/klatkę do ok. 0,05 core‑s (szacunek z modelu pola, NIE ZMIERZONY), czyli ok. 5–7% CPU Szybkiego, ok. 4% Zbalansowanego, ok. 1,5% Jakości. Nie rekomenduję przy obecnym stosunku zysku do kosztu.

## 4. Etap 3 — zgodność pikselowa przed kompresją

Porównanie próbek `yuv420p10le` wyjścia etapu overlay (surowe ramki, bez enkodera) między strategią A i B: 3 layouty × 2 orientacje (zapisana 180° i obrócona o 180° = źródło 0°) × 3 plany (kafel 16/60k, kafel 16/1,4M, kafel 64) × 5 momentów, po 2 klatki każdy, 24 883 200 próbek na przypadek:

| Metryka | Wynik |
|---|---|
| przypadki bit‑exact | **90 / 90** |
| max_diff (kody 10‑bit, Y/U/V) | 0 |
| MAE | 0 |
| different samples | 0 |
| piksele alfa>0 poza regionami | 0 |

Brak szwów i zmian chromy na granicach regionów (potwierdzone sumą różnic 0, także w chromie), poprawne półprzezroczyste cienie, mapa, wykresy i teksty (porównanie z pełnym overlayem tej samej klatki). Plan nie zależy od `def_layout.json`: trzy różne layouty, dwie orientacje. Warunki: regiony rozłączne, współrzędne parzyste, margines ≥ 16 px (obejmuje filtr chromy swscale). Porównanie dotyczy etapu FFmpeg; prototyp nie obejmuje pakowania atlasu w workerach Pythona (patrz pkt 6).

## 5. Etap 4 — wydajność

### 5a. Izolowany overlay (dekodowanie 4K + HUD → `-f null`, 300 klatek)

| Konfiguracja | wall FPS | ms/klatkę | core‑s/klatkę |
|---|---:|---:|---:|
| tylko dekodowanie | 82,8 | 12,1 | 0,121 |
| A pełny overlay | 28,7–29,3 | 34,8 | 0,25–0,30 (koszt overlay ok. 22,8 ms, ok. 0,13 core‑s) |
| 1 region 1,6% kadru | 73,9 | 13,5 | 0,144 |
| 2 regiony 2,9% | 64,3 | 15,6 | 0,165 |
| 1 region 25% kadru | 55,8–57,5 | 17,4–17,9 | 0,205 |
| 1 region 97,6% | 28,3 | 35,3 | 0,26 |
| 6 regionów 54% | 25,9 | 38,7 | 0,27 |
| 11 regionów 40% (B1 / B2) | 19,5 / 19,4 | 51,3 | 0,25 |

Z tego model czasu etapu (zmierzone punkty): **ok. 16,7 ms × (powierzchnia/4K) + ok. 2,9 ms × liczba regionów + stały koszt**. Koszt regionu odpowiada ok. 17% powierzchni 4K (każdy `overlay` kopiuje klatkę główną; to wniosek z dopasowania, nie zmierzony bezpośrednio). Powierzchnia do konwersji i blendu faktycznie jest tańsza, ale koszt regionów ją zjada.

### 5b. FFmpeg + prawdziwy x265 (300 klatek, ABR 16 Mb/s, strumień wejściowy z pętli HUD)

| Layout / profil | plan | regiony / powierzchnia | wall FPS średnio (powtórzenia) | core‑s/klatkę | RSS ffmpeg (szczyt) |
|---|---|---|---:|---:|---:|
| def / Szybki | A pełny | — | 12,42 (3) | 1,05–1,06 | 3,2–3,8 GB |
| def / Szybki | B1 min. powierzchnia | 11 / 39,9% | 11,78 (3) → **−5,2%** | 1,12–1,17 | 3,5 GB |
| def / Szybki | B3 2 regiony | 2 / 90,6% | 12,51 (3) → +0,7% | 1,06–1,08 | 3,2–3,7 GB |
| v10 / Szybki | A | — | 12,53 (2) | 1,06–1,07 | 3,7 GB |
| v10 / Szybki | B3 1 region | 1 / 84,3% | 12,77 (2) → **+1,9%** | 1,03–1,04 | 3,7 GB |
| v3 / Szybki | A | — | 12,64 (2) | 1,05–1,07 | 3,8 GB |
| v3 / Szybki | B3 5 regionów | 5 / 47,4% | 12,88 (2) → **+1,9%** | 1,03–1,04 | 3,2–3,6 GB |
| def / Zbalansowany | A | — | 7,54 (2) | 1,84–1,87 | 5,1 GB |
| def / Zbalansowany | B3 2 regiony | 2 / 90,6% | 7,46 (2) → −1,1% | 1,86–1,89 | 5,0 GB |

Zysk najlepszego planu jest w granicach rozrzutu powtórzeń (ok. ±1%) i nie przekracza 1,9%; czas startu i finalizacji nie były mierzone w tej serii (pełny potok z workerami nie został zmieniony). RSS ffmpeg nie ulega istotnej zmianie. Pamięć SHM/pipe: atlas planu def to 56% wielkości klatki (18,6 MB zamiast 33,2 MB na klatkę), v3 51% (16,8 MB); oszczędność transferu (14–16 MB/klatkę, czyli ok. 150–180 MB/s przy 11 FPS) nie była mierzona w pełnym potoku z workerami (NOT TESTED); proces główny zużywa dziś łącznie ok. 0,1–0,25 rdzenia, więc zysk byłby mały.

Ponieważ prototyp nie spełnił kryterium wydajności, **nie wykonano krótkich eksportów 4K przez harness CPU z wdrożoną implementacją ROI** (NOT TESTED; nie ma wdrożenia). Pełny potok z workerami po stronie Pythona (pakowanie atlasu w SHM, rozmiar slotów) nie został zmodyfikowany.

## 6. Ocena ryzyka dla ewentualnego wdrożenia (gdyby zdecydować inaczej)

- Plan z 5 klatek próbnych musi być zbudowany przed startem ffmpeg (graf jest argumentem wiersza poleceń), a ffmpeg jest dziś uruchamiany przed pulą workerów; wymaga to przekolejkowania startu lub renderu próbnego w głównym procesie.
- Dynamiczne elementy poza próbkami wymagają strażnika alfa w locie (np. co N‑tą klatkę) i bezpiecznego fallbacku do pełnej klatki; ucięcie HUD jest cichą regresją obrazu.
- Zysk nie uzasadnia ryzyka: ≤ 1,9% w najlepszym przypadku przy stockowym FFmpeg.
- Jedyna klasa układów, gdzie ROI mogłoby dać duży zysk: kompaktowy HUD w jednym narożniku (1 region o powierzchni 1,6–25%: overlay 1,5–5,5 ms zamiast 22,8 ms). Nie sprawdzono na takim layoutcie; nie występuje wśród trzech badanych.

## 7. Pliki

- Brak zmian w `src/` i `tests/` w tym etapie.
- `Raporty/CPU_P05_ROI_OVERLAY/prototype/cpu_hud_roi.py` — planer (maska, dylatacja, kafle, partycja guillotine, atlas, graf FFmpeg); celowo poza `src/`, bo nie jest używany produkcyjnie.
- `scripts/`: `dump_frames.sh`, `roi_analysis.py`, `prototype_roi.py`, `parity_matrix.py`, `e2e_ab.sh`.
- `analysis/`: `roi_analysis.json`, `parity_matrix.json/log`, mapy regionów PNG, maski alfa PNG, siatki zajętości; `e2e_ab.log`, `proto/*.json`. Zrzuty RGBA/YUV i MP4 usunięto (653 KB w katalogu).

## 8. Niezaliczone / NOT TESTED / ograniczenia

- Wdrożenie produkcyjne, pakowanie atlasu w workerach, SHM/RAM i czas startu w pełnym potoku, krótkie eksporty harnessu z ROI: nie wykonano (decyzja: odrzucić).
- Własny filtr FFmpeg: tylko szacunek kosztu (niezmierzony).
- Layout z kompaktowym HUD; layouty użytkownika poza trzema badanymi; klatki z pełnego przebiegu (testowano 5 z 320).
- Pomiary FFmpeg‑side używają pętli jednej klatki HUD, więc nie obejmują zmienności HUD w czasie ani transportu z Pythona.
- Zysk transferu (atlas 51–56% klatki) niezmierzony w potoku z workerami.

Powiadomienie ntfy MalcerzPOP wysłane: 4SuLZ6zX3wha, status CZĘŚCIOWO.
