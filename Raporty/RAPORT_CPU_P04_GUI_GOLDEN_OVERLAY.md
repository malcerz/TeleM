# SportCamHUD — CPU P0.4: walidacja GUI, zgodność HUD i bezpieczna optymalizacja

## Podsumowanie: CZĘŚCIOWO (4 zakresy zaliczone, ograniczenia wymienione w pkt 7)

| Zakres | Wynik |
|---|---|
| Etap 1 — GUI i ustawienia | **PASS** (25/25 kontroli) po naprawie regresji migracji z P0.3; żywe GUI poza offscreen: NOT TESTED |
| Etap 2 — Golden HUD (rysowanie) | **PASS** — HUD edytora = algorytm eksportu = klatka przed kompresją, 0 różnic, powtarzalne |
| Etap 2 — mapowanie HLG | **PASS numerycznie** (luma ±1 kod; chroma wewnątrz jednolitych obszarów ≤ 6 kodów); monitor HDR: NOT TESTED |
| Etap 2 — straty kompresji | **ZMIERZONE**, nie oceniane jako PASS/FAIL (brak progu akceptacji) |
| Etap 3 — workery 2 vs 4 | **PASS** — FPS równoważny, wdrożono mniej RAM (2 workery na 16 wątkach, skalowanie z CPU) |
| Etap 4 — overlay FFmpeg | **PASS (pomiar), brak optymalizacji wdrożonej** — koszt zmierzony, wariant `threads` bit‑exact ale zysk +0,8% w szumie |
| Main10 HLG, rotacja 0°/180°, audio, AMD | **PASS** (dowody w pkt 6) |

Repo `C:\_DEV\SportCamHUD`, gałąź `intel-60fps-preview`, HEAD 1601497, wiele niezacommitowanych zmian sprzed zadania zachowanych. Pomiary po 06:00 w trybie wydajności; kontrola: dekodowanie 76,0 FPS vs 77,7 FPS w P0.2. Materiał: `D:\GoPro\GX010370.MP4`, `D:\GoPro\2026-10-13_15-02-49.fit`, `def_layout.json`, 3840×2160, kanoniczny harness `--test-cpu-export`, eksporty 160–300 klatek, sekwencyjnie.

## 1. Etap 1 — GUI i ustawienia

Sonda `CPU_P04_GUI_GOLDEN_OVERLAY/scripts/gui_probe.py` uruchamia prawdziwe `MainWindow` + `AppController` + `RenderTab` (Qt offscreen) z izolowanym `TELEM_CONFIG_DIR`, więc nie dotyka sesji użytkownika. Faza 1 i 2 to osobne procesy (restart).

| Kontrola | Wynik |
|---|---|
| Domyślne widżety bez layoutu: Zbalansowany + ABR, suwak bitrate aktywny | PASS |
| Panel opcji CPU widoczny dla enkodera CPU, ukryty dla AMD | PASS |
| Zmiana profilu CPU (Szybki/Jakość/Zbalansowany) → `cpu_profile` w opcjach eksportu | PASS ×3 |
| CRF blokuje suwak bitrate; ABR go odblokowuje | PASS |
| Inny backend (AMD) przy zapisanym CRF: suwak bitrate aktywny; CRF znów blokuje po powrocie do CPU | PASS ×2 |
| Wpis bitrate `23M` → opcje eksportu | PASS |
| Zapis sesji zawiera `cpu_profile`, `cpu_rate_mode` | PASS |
| Round‑trip presetu (`apply_export_settings`) Szybki/ABR | PASS |
| **Po restarcie (nowy proces):** profil Jakość, tryb CRF, suwak zablokowany | PASS ×3 |
| Migracja (patrz niżej) ×6 | PASS |

### Znaleziona i naprawiona regresja z P0.3
W P0.3 projekty bez `cpu_rate_mode` dostawały po cichu ABR + Zbalansowany (dotąd: medium + CRF 24). To niezgodne z wymogiem zachowania starych projektów. **Reguła migracji (jawna, `src/ffmpeg/cpu_x265.py::settings_to_cpu_choice`):**

| Zapisane ustawienia | Wynik |
|---|---|
| brak `cpu_profile` i `cpu_rate_mode` (projekt sprzed P0.3, w tym `def_layout.json`) | **Jakość (medium) + CRF 24**, wpis w logu `[CPU] export settings without cpu_rate_mode … keeping previous encoding` |
| tylko `cpu_profile` | profil z pliku + CRF |
| tylko `cpu_rate_mode` | Jakość + tryb z pliku |
| oba klucze | wartości z pliku |

Zmieniono też fallbacki: `render_mixin` (`cpu_profile`→`quality`, `cpu_rate_mode`→`crf`), `streaming.py` i `_build_stream_ffmpeg_cmd` (`cpu_rate_mode` domyślnie `crf`). Test: stary projekt generuje `-preset medium -crf 24` bez `-b:v`. Konsekwencja: **użytkownik z istniejącymi ustawieniami nie zobaczy zmiany**, a nowe domyślne (ABR/Zbalansowany) obowiązują tylko, gdy użyje kontrolek i zapisze sesję. Propozycja, nie wdrożona: dodać w GUI jednorazowy komunikat „Przełączyć na Zbalansowany + ABR?".

## 2. Etap 2 — Golden HUD

Wzorzec: `Raporty/CPU_P04_GUI_GOLDEN_OVERLAY/golden/` — klatka eksportu 150 przy starcie 900, czyli klatka bezwzględna **1050** (t = 35,035 s), HUD przed kompresją (RGBA8, PNG bezstratny, w orientacji zapisu i po obrocie), rekord telemetrii, manifest z SHA‑256 wideo, FIT i layoutu oraz hash pikseli, obraz kontrolny z jawnym tone mappingiem. Istniejącego wzorca `tests/golden_hud` nie zmieniano. Test integralności: `tests/test_cpu_golden_p04.py` (pełne ponowne przechwycenie przy `TELEM_GOLDEN_RERUN=1`, nie uruchamiane w CI).

Trzy źródła porównane dla tej samej klatki i tego samego rekordu telemetrii (edytor i eksport czytają ten sam `PreparedHUDFrameProvider`):

1. **Edytor CPU HUD** — `render_preview` (fast_preview=True, async_map=True) na przezroczystym płótnie 3840×2160.
2. **Algorytm eksportu** — `compose_overlay` (fast_preview=False) w procesie GUI.
3. **HUD przed kompresją** — rzeczywista klatka zrzucona z rury do ffmpeg (hak `TELEM_CPU_DIAG_DUMP_*`).

### 2a. Rysowanie HUD (8‑bit RGBA, 8 294 400 pikseli)

| Porównanie | max_diff | MAE | different_pixels |
|---|---:|---:|---:|
| edytor vs algorytm eksportu | 0 | 0 | 0 |
| algorytm eksportu vs eksport przed kompresją | 0 | 0 | 0 |
| edytor vs eksport przed kompresją | 0 | 0 | 0 |
| ta sama klatka z 3 kolejnych eksportów (Szybki/Zbalansowany/Jakość) vs bezstratny | 0 | 0 | 0 |

Wszystkie 14 elementów (data/czas, mapa i ślad GPS, BAR dystansu, bateria Garmin, solar, kompas, przechył, tekst GPMF EXP/ISO/GP/BAT, skala wysokości, temperatura, prędkościomierz, BAR mocy, wykres kadencji, wykres HR) mają 0 różnic. Eksport przechowuje HUD obrócony o 180° (display matrix przywraca orientację); po jednokrotnym obrocie jest identyczny z edytorem, co potwierdza brak podwójnej rotacji.

Zastrzeżenie: edytor używa `fast_preview=True`, co wymusza supersample = 1. `def_layout.json` nie ustawia antyaliasingu (domyślnie 1), więc różnicy nie ma. **Dla layoutu z antyaliasingiem > 1 edytor i eksport będą się różnić — NOT TESTED.** Edytor porównano na płótnie 4K, nie w rzeczywistym rozmiarze podglądu GUI, a mapa w edytorze pochodziła z tego samego przygotowanego kontekstu.

### 2b. Wartości i teksty vs telemetria
Rekord (`golden/telemetry_f1050.json`) i rysunek zgodne wzrokowo na obrazie kontrolnym (arkusz `golden/control/elements_sheet_lossless.png`): data 2026‑10‑13, godzina 15:03:27, czas 00:38, średnia 7,4 km/h, dystans 0,1 km z 7,5, prędkość 6,1 km/h, wysokość 36 m, moc 137 W, kadencja 45, tętno 89, kompas 061°, przechył +2,6°, bateria Garmin 29,98%, solar 0%, temperatura 25,2 °C, GPMF: EXP 1/277, ISO 160, GP 30,1 °C, BAT 99,7%. Mapa i ślad GPS widoczne z atrybucją Esri. To ocena wzrokowa jednej klatki, nie niezależny test synchronizacji FIT/GPX/GPMF (NOT TESTED).

### 2c. Odwzorowanie HLG (eksport bezstratny, bez kompresji) — niezależny model
HUD (8‑bit RGB) jest kodowany jako wartości sygnału HLG BT.2020nc full range, bez konwersji transferu; model niezależny od ffmpeg w numpy:

| Kontrola | Wynik |
|---|---|
| Piksele nieprzezroczyste, luma (121 053 px) | max różnica 1 kod 10‑bit, MAE 0,013, 100% w ±2 |
| Piksele półprzezroczyste, luma (872 083 px, model `Yb + A·(Yh−Yb)`) | max 2,77 kodu, MAE 0,52, 100% w ±3 |
| Piksele przezroczyste = obraz bazowy | 0 różnic luma (7 301 264 px) i 0 różnic chroma (1 814 629 bloków): baza 10‑bit nietknięta |
| Chroma, bloki jednolite z jednolitymi sąsiadami (4 383) | Cb max 6 / MAE 0,82, Cr max 2 / MAE 1,00, 99,66% w ±2 |
| Chroma, jednolite bloki na granicy kolorów (14 494) | MAE 1,26, max 45 — filtr podpróbkowania 4:2:0 swscale rozlewa chromę na sąsiednie piksele, nie błąd koloru |

Wniosek: kolor i jasność HUD w eksporcie zgodne z modelem. **Obserwacja (nie błąd udowodniony):** biel HUD (255) = pełny sygnał HLG, czyli szczyt jasności na ekranie HDR, a nie biel referencyjna; ocena komfortu wymaga fizycznego monitora HDR — NOT TESTED.

### 2d. Straty kompresji (klatka 150 vs eksport bezstratny; ABR 16 Mb/s żądane)

| Profil | PSNR Y / U / V cały kadr | cyfry i data | mapa | kompas | prędkościomierz | wykres HR |
|---|---|---:|---:|---:|---:|---:|
| Szybki (ultrafast) | 36,86 / 47,04 / 48,93 | 35,68 | 37,13 | 30,72 | 34,77 | 32,28 |
| Zbalansowany (faster) | 39,48 / 48,41 / 50,52 | 39,24 | 39,64 | 33,86 | 37,55 | 34,75 |
| Jakość (medium) | 39,95 / 48,31 / 51,09 | 39,79 | 39,94 | 34,22 | 38,05 | 34,98 |

(PSNR Y w dB wewnątrz obszaru; pełna tabela w `golden_run/golden_analysis.json`.) Zbalansowany jest o 0,5 dB od Jakości, Szybki traci ok. 2,6 dB względem Zbalansowanego. Straty są rozdzielone od rysowania (2a: 0) i od mapowania (2c).

## 3. Etap 3 — workery 2 vs 4 (300 klatek, ABR 16 Mb/s, 2 powtórzenia naprzemiennie)

| Profil | Workery | wall FPS (średnia) | steady FPS | do 1. klatki | finalizacja | RSS workerów | szczyt RAM systemu |
|---|---:|---:|---:|---:|---:|---:|---:|
| Szybki | 2 / 4 | 11,20 / 11,21 | 12,46 / 12,23 | 1,03 / 1,19 s | 1,95 / 2,10 s | 1,03 / 2,39 GB | 18,9 / 19,6 GB |
| Zbalansowany | 2 / 4 | 7,06 / 7,03 | 7,73 / 7,58 | 1,03 / 1,24 s | 4,29 / 4,82 s | 1,03 / 2,29 GB | 19,7 / 20,4 GB |
| Jakość | 2 / 4 | 4,69 / 4,56 | 4,97 / 4,96 | 1,04 / 1,17 s | 7,07 / 8,08 s | 1,02 / 2,18 GB | 20,0 / 20,6 GB |

FPS równoważny (różnice ≤ 2,8%, w szumie przy 2 powtórzeniach), 2 workery oszczędzają ok. 1,3 GB RSS i ok. 0,6–0,7 GB szczytu RAM systemu oraz skracają start i finalizację. **Wdrożono** (`streaming.py`, tylko CPU, tylko gdy `workers is None`): `max(2, min(8, wątki // 8))` → 2 na 16 wątkach, 3 na 24, 4 na 32; HUD zużywa ok. 0,1 core‑s/klatkę, a FPS enkodera rośnie z liczbą rdzeni, więc liczba workerów skaluje się z CPU. `TELEM_CPU_WORKERS` pozostaje jako ręczny override. Potwierdzenie ścieżki domyślnej: 300 klatek Zbalansowany, 2 procesy workerów, 7,12 FPS, MP4 poprawny. Reguła przetestowana tylko na tym Ryzenie; dla innych CPU to ekstrapolacja (NOT TESTED).

FPS przed/po zmianie (4 → 2 workery): Szybki 11,21 → 11,20, Zbalansowany 7,03 → 7,06 (7,12 w przebiegu domyślnym), Jakość 4,56 → 4,69.

## 4. Etap 4 — koszt overlay FFmpeg RGBA → yuva420p10le + blend

Metoda: prawdziwy HUD (klatka złota zapętlona z pliku, bez kosztu transportu z Pythona) na prawdziwym dekodowaniu 4K HLG, wyjście `-f null`, 300 klatek, 2 powtórzenia (CPU ffmpeg, core‑s/klatkę).

| Graf | wall FPS | rdzenie | core‑s/klatkę | uwagi |
|---|---:|---:|---:|---|
| tylko dekodowanie | 82,8 | 10,0 | 0,121 | punkt odniesienia |
| **obecny** (`auto_scale` + `overlay=…format=yuv420p10`) | **28,7** | 7,3 | **0,255** | koszt overlay: +22,8 ms/klatkę, +0,133 core‑s/klatkę |
| jawna konwersja `threads=1` | 26,6 | 5,6 | 0,209 | |
| `scale threads=2 / 4 / 8 / 16` | 29,3 / 29,9 / 29,7 / 28,4 | 6,6–7,6 | 0,23–0,26 | |
| tylko konwersja RGBA→yuva (t1 / t4) | 37,6 / 38,8 | 3,0–3,3 | 0,08 | zawiera odczyt 33 MB z pliku |
| overlay na wstępnie skonwertowanym yuva | 22,0 | 8,6 | 0,39 | nie nadaje się do rozkładu kosztów (wejście 41 MB/klatkę zmienia ścieżkę); pominięte w wnioskach |

Wnioski:
- Auto‑wstawiony skaler pracuje domyślnie jednowątkowo (`threads=1`); jawny `threads` daje na tym etapie ok. +3–4% (29,9 vs 28,7 FPS).
- **Wynik wizualny bit‑w‑bit identyczny** we wszystkich wariantach (5 klatek, `max diff = 0`, 0 różnych próbek).
- **End‑to‑end z x265 ultrafast** (300 klatek, 3 powtórzenia, ten sam strumień bitowy): obecny 12,82 FPS vs `scale threads=4` 12,92 FPS (+0,8%, w szumie). Zgodnie z regułą „tylko po potwierdzonym A/B" **nie wdrożono**.
- Udział overlay w budżecie CPU (core‑s/klatkę z pełnego potoku): Jakość ok. 4,5%, Zbalansowany ok. 6,5%, Szybki ok. 11%; w eksporcie Szybki sam overlay (ok. 13 FPS z overlay vs 16–17 FPS bez) zabiera ok. 20–25% przepustowości.
- Brak zbędnych pełnoklatkowych kopii do usunięcia w konfiguracji ffmpeg: `[0:v]null[base]` jest przeźroczysty; baza pozostaje 10‑bit, HUD jest konwertowany jednokrotnie do `yuva420p10le`.
- **Największa możliwa dźwignia, niewdrożona (poza zakresem, wymaga zmiany potoku):** tylko ok. 12,0% pikseli HUD ma alfa > 0 (993 136 z 8 294 400), a bbox tego layoutu to cały kadr. Overlay i konwersja ograniczone do kafli/regionów (jak ścieżka AMD) mogłyby zredukować ten koszt kilkukrotnie. Wcześniejszy pomiar P0.2 pokazał, że obecne `get_layout_hud_regions` daje atlas 119% powierzchni, więc wymagałoby to nowej geometrii. Do osobnego zadania.

## 5. Zmiany w kodzie (P0.4)

- `src/ffmpeg/cpu_x265.py`: stałe migracji `LEGACY_PROFILE`/`LEGACY_RATE_MODE`, `settings_to_cpu_choice()`.
- `src/gui/qt/tabs/render_tab.py`: odczyt ustawień przez regułę migracji, komunikat w logu, tooltip.
- `src/gui/qt/_mixins/render_mixin.py`, `src/ffmpeg/streaming.py`, `src/ffmpeg/command_builder.py`: fallbacki zgodne z legacy (`quality`, `crf`).
- `src/ffmpeg/streaming.py`: automat workerów CPU `cpu // 8` (2 na 16 wątków); env‑gated zrzut klatki HUD (`TELEM_CPU_DIAG_DUMP_FRAMES`, `TELEM_CPU_DIAG_DUMP_DIR`, domyślnie nieaktywny) w ścieżce zapisu do rury.
- `src/gui/qt/harness_golden.py` (nowy, tylko harness) i `src/gui/qt/application.py`: opcje `--golden-dir`, `--golden-frame`.
- `tests/test_cpu_p03_presets.py` (+1 test migracji), `tests/test_cpu_golden_p04.py` (nowy).
- `Raporty/CPU_P04_GUI_GOLDEN_OVERLAY/`: skrypty, wzorzec `golden/`, wyniki; duże MP4/RGBA/YUV usunięto.

Backendy AMD/Intel/NVIDIA: zmiany ograniczone do `encoder == "cpu"` i opcji harnessu; zrzut klatki jest nieaktywny bez zmiennych środowiskowych.

## 6. Walidacja poprawności i regresji

| Kontrola | Wynik |
|---|---|
| Main10 yuv420p10le, HLG arib‑std‑b67, BT.2020, range pc | PASS (ffprobe 300/300 klatek, finalny przebieg domyślny) |
| Rotacja 180°: display matrix −180 raz, HUD upright po jednym obrocie | PASS (2a, ffprobe) |
| Rotacja 0° (fixture `source_0deg.mp4`, 45 klatek, profil Zbalansowany, po zmianach P0.4) | PASS: 45/45 klatek, brak rotacji w wyniku, Main10 HLG, audio, `color_valid=True` (krótki klip bez GPMF) |
| Audio: AAC `-c:a copy`, jeden live mux, bez cache | PASS (9,991 s przy wideo 10,010 s) |
| Walidator harnessu (`valid`, `color_valid`) | PASS we wszystkich przebiegach |
| Testy jednostkowe | `pytest` CPU P0/P03/golden/video_helpers/displaymatrix: **61 passed, 1 skipped** (skipped = rerun Golden wymagający `TELEM_GOLDEN_RERUN=1`) |
| AMD smoke (60 klatek, `GX020079.mp4` + `GX020079.fit` z `F:\_DEV\BikeRideHUD-amd\Video\`, `def_layout.json` repo) | PASS (success, 60 klatek); to nie jest benchmark wydajności, a layout `C:\_DEV\TeleM\def_layout.json` z BENCHMARKS.md nie istnieje na tym komputerze |
| Intel, NVIDIA | NOT TESTED (brak sprzętu: wykryte enkodery to tylko `amd` i `cpu`) |

## 7. Niezaliczone, NOT TESTED i ryzyka

- Żywe GUI: sonda działa na prawdziwych widżetach w Qt offscreen; nie wykonano ręcznego przeklikania ani zrzutów ekranu, a pełna ścieżka wczytania projektu z dysku (wideo + sesja) została zastąpiona odczytem JSON sesji i `apply_export_settings` (te same wywołania co w kodzie wczytania).
- Layout z antyaliasingiem > 1 (różnica edytor/eksport), edytor w realnym rozmiarze podglądu, inne klatki niż 1050, klatki z cięciami.
- Monitor HDR i ocena subiektywna HLG (biel HUD = pełny sygnał HLG).
- Niezależna weryfikacja synchronizacji FIT/GPX/GPMF; GPX/GPMF nieużywane w tym zestawie.
- Reguła workerów `cpu // 8` na innych procesorach; 2 powtórzenia przy 2 vs 4 workerach.
- Intel/NVIDIA smoke; benchmark AMD (tylko smoke).
- Rozkład kosztu overlay na konwersję i blend jest przybliżony (wariant z wstępną konwersją okazał się nieporównywalny).
- Pliki `streaming.py`, `command_builder.py`, `render_mixin.py`, `render_tab.py`, `application.py` miały wcześniejsze niezacommitowane zmiany; nic nie zacommitowano.

Powiadomienie ntfy MalcerzPOP wysłane: hYc0r0h4Fvbp, status CZĘŚCIOWO.
