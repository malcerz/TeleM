# SportCamHUD CPU P0.7a — Intel, stabilność i deterministyczność

## Decyzja: bez wdrożenia; przyczyna zmienności HUD niewyjaśniona

Na Intel Core i7-1265U, 12 wątków, wyniki nie dowodzą powtarzalnego zysku dla lookahead 3 lub 4. Trzy bazy wykazują wyraźny dryf 4,27 / 4,94 / 5,06 FPS eksportu. Nie stosowano arbitralnego progu 10%. Kodu produkcyjnego, profili i mechanizmów jakości nie zmieniono; nie ustawiono lookahead globalnie ani dla Intela.

## Stan początkowy i publikacja

Gałąź `cpu-optimization`, HEAD `d10055c2b0ca72a43fa4defa290151e03a5de1e2`, `git ls-remote origin refs/heads/cpu-optimization` zwrócił ten sam SHA. `git log` wskazał ten commit jako ostatnią zmianę raportu P0.7: raport i commit opublikowano. Indeks był pusty; zastano 778 usunięć, 107 modyfikacji i 338 pozycji nieśledzonych. Pozostawiono je. Nie modyfikowano AMD, Intel QSV, NVIDIA ani telemetrii.

## Warunki i ograniczenia

Plan Windows Wysoka wydajność, zasilanie podłączone, bateria 80%. Dwa 20-sekundowe okna liczników podczas testu: rzeczywista częstotliwość logicznego 0 (P) 1787–3191 MHz, logicznego 4 (E) 1300–2386 MHz; wartości obejmują zmiany obciążenia w czasie. Topologia Windows: P = 0–3 (dwa rdzenie SMT), E = 4–11 (osiem rdzeni). W próbce pod obciążeniem P 0–3 miały ~1790 MHz, flagę limitu 2 i limit wydajności 67%, E 4–11 ~1300 MHz i 100%. Kod flagi nie identyfikuje w tym pomiarze przyczyny; **temperatura i termiczny throttling NOT PROVEN**: standardowe ACPI i psutil nie zwróciły temperatury. Nie zmieniano planu ani limitów globalnych. Czasy dysku 0,2–9,1% w tych oknach; nie obejmują całej serii. Przed testem wolne ~5,6 GiB z 15,8 GiB; podczas prób użycie systemu do 14,68 GiB. W próbce pod obciążeniem CPU systemu 87%, ffmpeg ~7,7 rdzenia, dwa workery ~1,1 rdzenia; Chrome miał łącznie również zauważalne obciążenie. Procesów użytkownika nie zamykano. Pomiary CPU wrappera obejmują 25–90% czasu całego procesu, nie wyłącznie kodowanie. Odczyty częstotliwości i RAM wskazują na zmienne warunki i możliwą presję pamięci, nie ustalają mechanizmu dryfu ani przyczyny P0.7.

## Metoda

Wskazana przez użytkownika para `C:\GoPro\GX010378.MP4` + `C:\GoPro\2026-10-15_15-03-50.fit`, `def_layout.json`, start 900, 300 klatek, 4K, Main10 HLG, profil Szybki/ultrafast, ABR 16M. Kanoniczny `--test-cpu-export` z wrapperem P0.7 (pomiary psutil co 0,5 s). Kolejność: base1, 3_1, 4_1, 4_2, base2, 3_2, 3_3, 4_3, base3. Trzy bloki porównawcze współdzielą po jednej bazie między 3 i 4; kolejność przeplatana, ale nie tworzy sześciu niezależnych par. Brak pauzy stabilizującej temperaturę i brak jej odczytu, toteż warunki stabilne nie są udowodnione. Żadnego pełnego filmu ani innych parametrów nie testowano. Zrzuty 3 klatek HUD przy base1/base2 mogą mieć niewielki narzut I/O. Współdzielony wrapper mierzy osobno czas procesu (start aplikacji do wyjścia), czas eksportu (od kliknięcia do końca), steady w przedziale klatek 31–270 i finalizację FFmpeg. FPS procesu = 300/czas procesu; FPS eksportu = 300/czas eksportu.

| Przebieg | FPS cały proces | FPS eksport | steady FPS | przygotowanie s | finalizacja s | CPU % | szczyt RAM systemu GiB | peak RSS FFmpeg MiB | kb/s x265 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| base1 | 3,59 | 4,27 | 4,47 | 4,33 | 4,46 | 86,6 | 14,30 | 3058,6 | 15133,78 |
| 3_1 | 3,70 | 4,44 | 4,49 | 4,57 | 3,82 | 96,2 | 14,68 | 2995,0 | 15121,26 |
| 4_1 | 4,22 | 5,02 | 5,26 | 4,31 | 3,38 | 94,9 | 14,38 | 3116,2 | 15115,36 |
| 4_2 | 4,02 | 4,86 | 5,03 | 6,03 | 3,91 | 95,7 | 14,34 | 2962,0 | 15115,87 |
| base2 | 4,18 | 4,94 | 5,11 | 4,16 | 3,23 | 97,1 | 14,28 | 3004,7 | 15129,94 |
| 3_2 | 4,13 | 4,86 | 5,04 | 4,09 | 3,74 | 96,9 | 14,33 | 3124,2 | 15124,76 |
| 3_3 | 4,28 | 5,06 | 5,26 | 4,18 | 3,48 | 96,9 | 14,19 | 3006,9 | 15126,55 |
| 4_3 | 4,10 | 4,86 | 5,03 | 4,48 | 3,72 | 95,9 | 14,22 | 2985,5 | 15135,40 |
| base3 | 4,23 | 5,06 | 5,22 | 4,10 | 3,57 | 97,2 | 14,07 | 3003,4 | 15119,91 |

Średnie FPS eksportu base/3/4: 4,76 / 4,79 / 4,91; różnica średnich jest silnie zależna od wolnej pierwszej bazy i kolejności. W bloku 2 baza 4,94 vs 3=4,86 i 4=4,86; w bloku 3 baza 5,06 vs 3=5,06 i 4=4,86. To nie dowodzi zysku. Pełne podsumowania i dane kontrolne: `CPU_P07A_INTEL_LOOKAHEAD/summaries.json`, `counters.csv`.

## Deterministyczność

Dwie bazy 300 klatek miały identyczne wejścia i ustawienia, graf filtra oraz log konfiguracji x265 (4.3+13, 10-bit, 12 wątków puli, frame threads 3, WPP, ABR 16000); różnią się statystyki wynikowe. SHA-256 HEVC base1 `260c27c849eca4ae738d76349047bdad021da78b273e5d34b2cb085f65c3f54a`, base2 `110d1d7c31b345e4c8fb0f151eded248f721e02fc2cf6d62d5ae5c8c19eecbd5`. HUD 0 i 150 bitowo równy, HUD 299 różny: 19 914 pikseli, bbox x=83–412, y=946–1652, max różnica kanału 255; różnice nie ograniczają się do pikseli z zerową alfą. Porównanie trzech próbek nie ustala pierwszej różnej klatki w tych dwóch bazach.

Następnie dwa odrębne eksporty diagnostyczne po 300 klatek z tymi samymi ustawieniami: nieinwazyjny poza procesem produkcyjnym launcher podmienia w pamięci funkcję zapisu diagnostycznego na SHA-256 HUD i dokłada `split` filtra z wyjściem framemd5 surowego yuv420p10le bezpośrednio po overlay, przed x265. Logger porównuje 300 rekordów przekazanych workerom. Zmodyfikowany graf/haszowanie wprowadza narzut; FPS tych przebiegów nie służy do benchmarku. Rekordy są identyczne (SHA-256 plików `b34f6bdf3fa6aa22068f573f92c9cc07bf0f11faa865e846e68b8c46dd10c9df`). Pierwszy różny HUD: klatka 13, 139/300 hashy różnych; pierwsza różna klatka po overlay także 13, 139/300 różnych. HEVC też różny. Pierwsza wykryta różnica jest więc **na etapie HUD**, przed overlay i kodowaniem; identyczność rekordów nie dowodzi identyczności całego stanu renderera. Źródła zmienności HUD nie ustalono; nie da się przypisać różnicy wyłącznie x265 ani lookahead. Ten test nie dowodzi deterministyczności x265 dla identycznych kompletnych wejść. PSNR/SSIM dla przypadku zmiennego wyłącznie HEVC nie wymagano, gdyż wejście enkodera różni się; porównanie jakości przy równym wejściu NOT TESTED. Nie wymuszano jednowątkowego x265.

Diagnostyczne skrypty i hashe klatek zachowano w `CPU_P07A_INTEL_LOOKAHEAD/`; rekordów telemetrii nie dołączono ze względu na dane lokalizacji. Surowe pliki i logi pozostają w `C:\GoPro\TO\p07a`. SHA-256 wejścia: MP4 `52f927849f8a198ce1a0b4057b62ccbbc680eeb57690ed65cb30bc4ffcb9b4f1`, FIT `8f8a00dcd191ee7e6a223c8961157d4dfbd59583897a9ea9f8741d1064a60344`, layout `0cd2a07e49f6a2ff32a24736112bc495b408a78e3cc72c9cc39b8f52f2ebfc8f`, FFmpeg `d95d1567c9865eb935df2da1cc0315004c3ef37e0b983b47af66ab8cf3e1e133`.

## Poprawność i testy

Wszystkie dziewięć pomiarów: sukces, 300/300, `valid=True`, audio obecne, timing bez błędu, walidacja koloru PASS. Próbka ffprobe P0.7 tego samego materiału: HEVC Main10 yuv420p10le, BT.2020, arib-std-b67, display matrix −180° taki jak wejściowy; bieżący przechwycony proces potwierdza `-noautorotate` i `rotate=180`, lecz wizualna ocena orientacji NOT TESTED. Pełna linia procesu base2 potwierdza audio bezpośrednio z oryginału przez `-map 0:a? -c:a copy`, brak pośredniego pliku w tym wywołaniu; nie wykonywano wyodrębnienia audio. `pytest` CPU Golden/presets/correctness: 23 passed, 1 skipped (oryginalny rerun Golden wymaga niedostępnego GX010370). Golden integralność PASS, pełny rerun NOT TESTED. Dwa przebiegi diagnostyczne także valid, 300 klatek.

## Podsumowanie

FPS przed/po i stabilność: zmienne, brak wiarygodnego powtarzalnego zysku. Wykryto zmienność HUD przed x265; jej przyczyna oraz dokładny wpływ taktowania/temperatury pozostają otwarte. Do wiarygodnego wyboru potrzeba usunięcia niedeterministyczności HUD, monitorowania temperatury/limitów i ponownego pomiaru w kontrolowanych warunkach. STATUS CZĘŚCIOWO: diagnoza etapu różnicy wykonana, pełna przyczyna i stabilne warunki NOT PROVEN; wdrożenie NIE.
