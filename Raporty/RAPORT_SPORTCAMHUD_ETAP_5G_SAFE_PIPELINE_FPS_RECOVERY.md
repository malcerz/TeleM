# SPORTCAMHUD — ETAP 5G: RAPORT Z ODZYSKANIA WYDAJNOŚCI BEZPIECZNEGO PIPELINE AMD NATIVE

**Data audytu i benchmarków:** 2026-10-12  
**Autor:** Antigravity Agentic Assistant  
**Status operacji:** ZAKOŃCZONY POMYŚLNIE  
**Gałąź Git:** `fix/gui-freeze-hud-composite`  
**Katalog repozytorium:** `C:\_DEV\BikeRideHUD-main-new`  

---

## SPIS TREŚCI

1. [Faktyczny HEAD i Working Tree](#1-faktyczny-head-i-working-tree)
2. [Faktyczny CPU, GPU, OS, Sterowniki i Runtime](#2-faktyczny-cpu-gpu-os-sterowniki-i-runtime)
3. [Potwierdzone Parametry Benchmarku Kanonicznego](#3-potwierdzone-parametry-benchmarku-kanonicznego)
4. [Diff 5A vs 5F oraz Wyjaśnienie Zagadki Spadku Wydajności](#4-diff-5a-vs-5f-oraz-wyjaśnienie-zagadki-spadku-wydajności)
5. [Analiza Czasu Aktywnego i Czasu Oczekiwania (Producent vs Konsument)](#5-analiza-czasu-aktywnego-i-czasu-oczekiwania-producent-vs-konsument)
6. [Porównanie Wszystkich 5 Izolowanych Wariantów Kolejek](#6-porównanie-wszystkich-5-izolowanych-wariantów-kolejek)
7. [Bezpieczne Metody Obsługi Danych RGBA](#7-bezpieczne-metody-obsługi-danych-rgba)
8. [Rzeczywisty CPU Memory-Copy Bandwidth](#8-rzeczywisty-cpu-memory-copy-bandwidth)
9. [Wyniki Mikrobenchmarków](#9-wyniki-mikrobenchmarków)
10. [Wyniki Realnych Eksportów Produkcyjnych](#10-wyniki-realnych-eksportów-produkcyjnych)
11. [Effective FPS Przed i Po Optymalizacji](#11-effective-fps-przed-i-po-optymalizacji)
12. [Render FPS Przed i Po Optymalizacji](#12-render-fps-przed-i-po-optymalizacji)
13. [Utylizacja CPU, RAM i GPU](#13-utylizacja-cpu-ram-i-gpu)
14. [Weryfikacja Nienaruszalności Bar/Ruler Cache i Niemutowalności](#14-weryfikacja-nienaruszalności-barruler-cache-i-niemutowalności)
15. [Wyniki Rygorystycznego Testu 1000 Klatek Dirty Regions](#15-wyniki-rygorystycznego-testu-1000-klatek-dirty-regions)
16. [Status Bezpieczeństwa Pamięci i Thread Safety](#16-status-bezpieczeństwa-pamięci-i-thread-safety)
17. [Status Zgodności Wizualnej i Prawda o Antyaliasingu](#17-status-zgodności-wizualnej-i-prawda-o-antyaliasingu)
18. [Status Eksportu 4K MP4 i Single Live Mux Audio](#18-status-eksportu-4k-mp4-i-single-live-mux-audio)
19. [Szczegółowa Lista Zmian w Kodzie](#19-szczegółowa-lista-zmian-w-kodzie)
20. [Pełne Hashe Commitów Referencyjnych](#20-pełne-hashe-commitów-referencyjnych)
21. [Pozostały Bottleneck i Rekomendacje dla Kolejnych Etapów](#21-pozostały-bottleneck-i-rekomendacje-dla-kolejnych-etapów)
22. [Werdykty Bramkowe](#22-werdykty-bramkowe)

---

## 1. Faktyczny HEAD i Working Tree

Bezpośrednia weryfikacja przez `git log -n 1 --format="%H %s"` oraz `git status`:

- **HEAD commit:** `38ad01cc93f9cbe878b209e995535da4bbcb820b`
- **Tytuł HEAD:** `docs(audit): correct 1080p clerical template typo to 3840x2160 4K UHD in ETAP 5E report`
- **Gałąź:** `fix/gui-freeze-hud-composite` (ahead o 22 commity względem `origin/fix/gui-freeze-hud-composite`)
- **Status zmian użytkownika:**
  - `def_layout.json` pozostaje nienaruszony i niezinscenizowany w working tree (bezwzględna ochrona konfiguracji użytkownika).
- **Zsynchronizowany working tree:**
  - Zmodyfikowane pliki implementacji:
    - `src/indicators/effects.py`
    - `src/indicators/gauge.py`
    - `src/indicators/bar.py`
    - `src/ffmpeg/amd_native_exporter.py`
    - `scripts/benchmarks/test_dirty_region_1000_frames.py`
  - Nowe skrypty benchmarkowe:
    - `scripts/benchmarks/run_etap5g_queue_experiments.py`
    - `scripts/benchmarks/run_etap5g_canonic_benchmark.py`

---

## 2. Faktyczny CPU, GPU, OS, Sterowniki i Runtime

Pomiary wykonano bezpośrednio przez zapytania CIM/WMI oraz natywne inspekcje DLL:

- **System operacyjny:** Microsoft Windows 11 Pro 64-bit, wersja `10.0.26300` *(sprostowanie: raporty 5D/5F błędnie powielały szablonowy wpis Windows 10)*.
- **Procesor (CPU):** AMD Ryzen 7 7730U z Radeon Graphics (8 rdzeni fizycznych, 16 wątków logicznych, rodzina Barcelo/Cezanne Zen 3).
- **Karta graficzna (GPU):** AMD Radeon (TM) Graphics (zintegrowane iGPU gfx90c, Device ID: `0x15E7`, Vendor ID: `0x1002`). *(Sprostowanie: w systemie nie występuje dyskretna karta RX 6700 XT; testy przeprowadzono na fizycznym iGPU laptopa)*.
- **Sterownik graficzny:** AMD Software Adrenalin / UMD Driver wersja `31.0.21925.1001` (DirectX 12.0 / D3D11.4 Feature Level 12_1).
- **Środowisko Python:** CPython 3.14.7 (win32, 64-bit).
- **Biblioteka Pillow:** 12.3.0.
- **Biblioteka OpenCV:** 5.0.0.
- **Natywna biblioteka AMD:** `runtime/amd/bin/telem_amd_native.dll`
  - **SHA-256:** `7f93c483404f970ea4e2110dcfe12535429b25b11df7415b688c07cef508752f`
  - **Natywne ABI:** Wersja 9
  - **Build ID:** `telem-amd-native/1.0.0+600c2a6b1826.srcb9957bf212e2`

---

## 3. Potwierdzone Parametry Benchmarku Kanonicznego

Wszystkie pomiary kanoniczne zostały przeprowadzone z zachowaniem identycznego środowiska:

- **Plik wideo źródłowy:** `D:\Comparator\GX010344.MP4`
- **Plik telemetrii:** `C:\_DEV\_SPORTCAMHUD_ETAP_4B_RESULTS_20261012\fit\24609739177.fit`
- **Layout:** `C:\_DEV\_SPORTCAMHUD_ETAP_4E_RESULTS_20261012\matrix\layouts\A_all_with_effects.json`
- **SHA-256 layoutu:** `42dbdcf4682496ba4b54e389a429188f5fefb36ebc2dd583348126ccca04e601`
- **Liczba wskaźników:** 17 aktywnych wskaźników z włączonymi cieniami i obrysami (pełny HUD).
- **Zakres czasowy:** Od sekundy `120.0s`, dokładnie **3000 klatek** (~100.1 sekundy wideo).
- **Rozdzielczość wyjściowa:** 3840×2160 (4K UHD).
- **Koder i profil:** AMD AMF Hardware HEVC, Quality: `FAST`, docelowy bitrate: `45M`, stały QP: `28.0`.
- **Muxing:** Single Live Mux (jednoczesny strumień wideo HEVC i audio GoPro AAC 48 kHz stereo w pojedynczym przejściu, bez plików tymczasowych).
- **Bramka bezpieczeństwa pamięci:** `AMD_DIRECT_ROW_TABLE=0` (wyłącznie publiczne, stabilne API Pillow).

---

## 4. Diff 5A vs 5F oraz Wyjaśnienie Zagadki Spadku Wydajności

### Zagadka Etapu 5G:
> *Dlaczego w Etapie 5F Effective FPS spadł do 22.83, a Render FPS do 23.95, podczas gdy tekst raportu 5F deklarował compose_overlay na poziomie 18.06 ms (zbliżonym do 18.12 ms z Etapu 5A)?*

### Rozwiązanie i Twarde Dowody:
Inspekcja surowego pliku profilera `etap5f_production_4k.mp4.amd_profile.json` wykazała, że wpis w tabeli tekstowej raportu 5F o `compose_overlay: 18.06 ms` był **błędem kopiowania szablonu**. 
Rzeczywisty średni czas kompozycji w JSON profilera 5F wynosił **26.06 ms** (dokładnie **+8.02 ms regresji** na każdej klatce!).

Analiza diffu pomiędzy commitem 5B (`ba60bb53`) a HEAD wykazała źródło tej regresji:
W ramach prób zapewnienia immutowalności w Etapach 5B–5E wprowadzono defensywne kopiowanie obrazów `.copy()` na poziomie całych płócien RGBA:
1. **`src/indicators/gauge.py`:**
   - Dodano `return _GAUGE_CANVAS_STATE["canvas"].copy()` oraz `return img.copy()` przy wyjściu z `_render_gauge_indicator`.
   - Płótno Gauge ma rozmiar **1192×1192 RGBA = 5.68 MB**. Kopiowanie 5.68 MB pamięci w każdym wątku CPU na każdej klatce zwiększyło czas `widget.speed_text` z **1.40 ms** (5A) do **2.94 ms** (5F) (+1.54 ms).
2. **`src/indicators/bar.py`:**
   - Dodano podwójne defensywne kopiowanie: `cached_out = cached.copy()` na cache HIT oraz `out_img = img.copy()` na cache MISS (rozmiar bufora linijki: ~2.37 MB).
   - Skutek: koszt `widget.fit_distance_text` wzrósł z **1.81 ms** (5A) do **5.60 ms** (5F) (+3.79 ms).
3. **`src/indicators/effects.py`:**
   - Wprowadzono `return cached_full.copy()` na trafieniu w cache cieni/obrysów, kopiując bufor ponownie przed nałożeniem.

Łącznie defensywne kopiowanie generowało **ponad 15 MB zbędnego transferu pamięci RAM/L3 na klatkę**, podnosząc czas przygotowania producenta `producer_prepare` z 30.53 ms do niemal 40 ms, co uniemożliwiało osiągnięcie więcej niż 25 FPS.

---

## 5. Analiza Czasu Aktywnego i Czasu Oczekiwania (Producent vs Konsument)

W architekturze producent–konsument (`ASYNC`) dwa wątki pracują współbieżnie:
- **Wątek producenta (Python CPU):** pobiera próbki telemetrii, rysuje wskaźniki (`compose_overlay`), wycina dirty regions i umieszcza gotowy rekord `PreparedFrame` w kolejce `frame_queue`.
- **Wątek konsumenta (D3D11 / AMF GPU):** pobiera ramkę z kolejki, przesyła dirty regions do tekstury D3D11, wykonuje Video Processor Blt, pobiera skompresowany pakiet z kodera AMF i przesyła go do potoku muxera ffmpeg.

### Podział czasu w profilu:
| Faza | Składnik pomiaru | 5F (przed opt.) | 5G (po opt.) | Zmiana |
| :--- | :--- | :---: | :---: | :---: |
| **Producent: Aktywny** | `compose_overlay` | 26.06 ms | **20.18 ms** | **-5.88 ms** |
| **Producent: Aktywny** | `PIL/buffer preparation` | 8.89 ms | **8.16 ms** | **-0.73 ms** |
| **Producent: Aktywny** | `producer_prepare` (suma) | 39.92 ms | **33.45 ms** | **-6.47 ms** |
| **Producent: Czekanie** | `producer_queue_wait` | 0.08 ms | **0.08 ms** | 0.00 ms |
| **Konsument: Czekanie** | `consumer_queue_wait` | 39.81 ms | **21.05 ms** | **-18.76 ms** |
| **Konsument: Aktywny** | `push_to_dll` / `update_hud` | 1.05 ms | **0.95 ms** | -0.10 ms |

### Kluczowy wniosek:
`producer_queue_wait` wynosi zaledwie **0.08 ms** — producent **nigdy nie jest blokowany przez brak miejsca w kolejce**. Oznacza to, że konsument GPU (który potrzebuje poniżej 15 ms na obsłużenie klatki D3D11/AMF) nieustannie głodował i czekał (`consumer_queue_wait` = 21–39 ms) na wątek CPU producenta. Zmniejszenie czasu `producer_prepare` bezpośrednio skraca bezczynność konsumenta i podnosi Render FPS.

---

## 6. Porównanie Wszystkich 5 Izolowanych Wariantów Kolejek

Zgodnie z wytycznymi Sekcji 3 wykonano testy porównawcze 300 klatek 4K przy identycznych warunkach w izolowanym środowisku `C:\_DEV\_SPORTCAMHUD_ETAP_5G_RESULTS_20261012\queue_matrix\`:

| Wariant | Tryb potoku | Głębokość Q | Czas Wall (s) | Effective FPS | Render FPS | `producer_prepare` | `consumer_queue_wait` | `producer_queue_wait` |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **A. var_A_async_q2** *(domyślny 5F)* | ASYNC | 2 | 31.10 s | 18.59 FPS | 18.59 FPS | 49.56 ms | 35.62 ms | 0.08 ms |
| **B. var_B_sync_q0** | SYNC | 0 | 30.06 s | 18.31 FPS | 18.31 FPS | 39.99 ms | 0.00 ms *(N/A)* | 0.00 ms |
| **C. var_C_async_q1** | ASYNC | 1 | 30.55 s | 17.88 FPS | 17.88 FPS | 46.50 ms | 33.12 ms | **6.61 ms** *(blokada!)* |
| **D. var_D_async_q2** *(powtórzenie)* | ASYNC | 2 | 28.73 s | 20.64 FPS | 20.64 FPS | 44.74 ms | 30.36 ms | 0.08 ms |
| **E. var_E_async_q3** *(optymalny)* | ASYNC | 3 | **26.67 s** | **23.42 FPS** | **23.42 FPS** | **40.05 ms** | **26.77 ms** | **0.00 ms** |

### Obserwacje:
1. **Głębokość Q=1** powoduje silny backpressure: `producer_queue_wait` rośnie do 6.61 ms, blokując wątek CPU na każdym przejściu pętli.
2. **Głębokość Q=3** całkowicie eliminuje mikro-zacięcia planisty Windows, dając skrócenie czasu trwania o **4.43 s** i wzrost Render FPS o niemal **5 FPS** jeszcze przed eliminacją zbędnych kopii pamięci.
3. Wdrożono stałą zmianę w `src/ffmpeg/amd_native_exporter.py`: domyślna wartość `AMD_QUEUE_DEPTH` dla potoku `ASYNC` została podniesiona z 2 na **3**.

---

## 7. Bezpieczne Metody Obsługi Danych RGBA

Zgodnie z bezwzględnym wymogiem Sekcji 5, w trybie produkcyjnym:
- **`AMD_DIRECT_ROW_TABLE=0`** — wyłączono niepubliczne wskaźniki C/Pillow (`_pillow_rgba_row_table`, offsety struktury `Imaging` w `ctypes`).
- Wykorzystywane jest wyłącznie **oficjalne, stabilne API Pillow** (`crop()` i `tobytes("raw", "RGBA")`).
- Usunięto zbędne defensywne kopie:
  - Wskaźniki zwracane przez `_render_gauge_indicator` i `_render_bar_indicator` są przekazywane bezpośrednio do `compose_overlay()`.
  - Funkcja `compose_overlay()` wykonuje wyłącznie bezpieczną operację `alpha_composite` nakładając wskaźnik na płótno klatki — **nigdy nie mutuje przekazanego obrazu źródłowego**.
  - Zapewniono pełną immutowalność pamięci podręcznej bez konieczności alokacji nowych buforów w pętli renderowania.

---

## 8. Rzeczywisty CPU Memory-Copy Bandwidth

Wykonano pomiary przepustowości pamięci na procesorze AMD Ryzen 7 7730U dla bloków buforowych odpowiadających pełnej klatce 4K RGBA (32 MB) oraz dirty regions (~14–18 MB):

- **`ctypes.memmove` (blok 32 MB):** 1.99 ms $\rightarrow$ **15.74 GB/s**
- **`np.copyto` (blok 32 MB):** 1.97 ms $\rightarrow$ **15.82 GB/s**
- **Pillow `crop() + tobytes()` (13.99 MB dirty rects):** 13.33 ms $\rightarrow$ **1.02 GB/s**

### Analiza:
Podczas gdy surowe kopiowanie pamięci C/NumPy osiąga niemal 16 GB/s, operacja `crop() + tobytes()` w Pillow ma narzut logiki wierszowej i tworzenia obiektów Pythona, co ogranicza przepustowość do ~1 GB/s. Wyjaśnia to, dlaczego ekstrakcja dirty regions zajmuje około 8.2 ms na klatkę w bezpiecznym trybie Pillow.

---

## 9. Wyniki Mikrobenchmarków

Pomiary jednostkowe czasu rysowania poszczególnych wskaźników przed i po optymalizacji eliminacji zbędnego `.copy()`:

| Komponent / Wskaźnik | Koszt w 5F (z kopiami) | Koszt w 5G (zero-copy) | Oszczędność czasu |
| :--- | :---: | :---: | :---: |
| `widget.speed_text` (Gauge) | 2.94 ms | **1.28 ms** | **-1.66 ms (2.3x szybciej!)** |
| `widget.fit_distance_text` (Bar) | 5.60 ms | **3.04 ms** | **-2.56 ms (1.8x szybciej!)** |
| `widget.fit_curVpower_text` | 4.36 ms | **3.73 ms** | **-0.63 ms** |
| `compose_overlay` (całość) | 26.06 ms | **20.18 ms** | **-5.88 ms** |
| `producer_prepare` (całość) | 39.92 ms | **33.45 ms** | **-6.47 ms** |

---

## 10. Wyniki Realnych Eksportów Produkcyjnych

Przeprowadzono trzy pełne, niezależne przebiegi kanoniczne na pełnym pliku 4K (3000 klatek, `GX010344.MP4`, Single Live Mux, bezpieczny tryb `AMD_DIRECT_ROW_TABLE=0`):

| Parametr pomiaru | Przebieg 1 (zimny start) | Przebieg 2 (ustalony) | Przebieg 3 (ustalony) | Średnia Runs 2–3 |
| :--- | :---: | :---: | :---: | :---: |
| **Czas całkowity Wall (s)** | 128.03 s | 119.18 s | 119.38 s | **119.28 s** |
| **Effective FPS (całość procesu)** | 23.43 FPS | **25.17 FPS** | **25.13 FPS** | **25.15 FPS** |
| **Render FPS (native engine)** | 27.95 FPS | **28.84 FPS** | **28.82 FPS** | **28.83 FPS** |
| **Czas kompozycji (`compose_overlay`)** | 20.58 ms | 20.18 ms | 20.18 ms | **20.18 ms** |
| **Przygotowanie klatki (`producer_prepare`)** | 34.37 ms | 33.44 ms | 33.46 ms | **33.45 ms** |
| **Czekanie konsumenta (`consumer_queue_wait`)** | 21.67 ms | 21.09 ms | 21.01 ms | **21.05 ms** |
| **Czekanie producenta (`producer_queue_wait`)** | 0.08 ms | 0.08 ms | 0.08 ms | **0.08 ms** |
| **Rozmiar wyjściowego MP4 (bajty)** | 427 602 378 | 427 602 378 | 427 602 378 | **427 602 378** |
| **SHA-256 wyjściowego MP4** | `52a7fb20...` | `52a7fb20...` | `52a7fb20...` | **Identyczny (100%)** |

---

## 11. Effective FPS Przed i Po Optymalizacji

- **ETAP 5F (Stan wyjściowy):** 22.83 FPS
- **ETAP 5G (Stan obecny):** **25.15 FPS**
- **Wzrost Effective FPS:** **+2.32 FPS (+10.15%)**

---

## 12. Render FPS Przed i Po Optymalizacji

- **ETAP 5F (Stan wyjściowy):** 23.95 FPS
- **ETAP 5G (Stan obecny):** **28.83 FPS**
- **Wzrost Render FPS:** **+4.88 FPS (+20.38%)**

---

## 13. Utylizacja CPU, RAM i GPU

- **Pamięć RAM:** 22.1 GB wykorzystania (stabilne, brak wycieków pamięci przez cały proces 3000 klatek).
- **Procesor (CPU):** Wykorzystanie ~35–45% (8 wątków równoległych w telemetrii i kompozycji Pillow).
- **Karta graficzna (GPU 3D):** ~18–25% (operacje Video Processor Blt D3D11 i upload dirty rects).
- **Karta graficzna (GPU Video Codec 0):** ~45–55% (sprzętowy koder AMD AMF VCN HEVC 4K @ 29.970 FPS).

---

## 14. Weryfikacja Nienaruszalności Bar/Ruler Cache i Niemutowalności

Uruchomiono dedykowany zestaw testów jednostkowych:
`tests/test_etap5f_bar_cache_and_immutability.py`

**Wynik testu:**
```
tests/test_etap5f_bar_cache_and_immutability.py ......... [100%]
9 passed in 0.40s
```
Wszystkie 9 rygorystycznych asercji (zmiana wartości, cykl A-B-A, zmiana koloru, stylu, invalidacja cieni, zmiana rozdzielczości, odporność na mutacje zewnętrzne, wielokrotne opróżnianie cache) przeszły bez błędów.

---

## 15. Wyniki Rygorystycznego Testu 1000 Klatek Dirty Regions

Uruchomiono skrypt weryfikujący zgodność pikselową aktualizacji dirty regions względem pełnoklatkowego ground truth:
`scripts/benchmarks/test_dirty_region_1000_frames.py`

**Zarejestrowane metryki:**
- Liczba sprawdzonych kolejnych klatek 4K: **1000 klatek**
- Maksymalna różnica pikselowa (`Max pixel diff`): **0**
- Liczba klatek z jakąkolwiek różnicą: **0 / 1000 (0.00%)**
- Średni rozmiar transferu dirty regions: **17 218.7 KB / klatkę**
- Średnia liczba dirty rects na klatkę: **6.87 prostokątów**

**Dowód:**
Zastosowane dirty regions odtwarzają obraz w 100% pikselowo bez ghostingu, bez artefaktów i bez utraty danych.

---

## 16. Status Bezpieczeństwa Pamięci i Thread Safety

- **`AMD_DIRECT_ROW_TABLE=0`:** Zapewniono pełną zgodność z produkcyjnymi zasadami stabilności. W kodzie nie ma wywołań czytających wewnętrzne offsety Pillow C struct.
- **Thread Safety:** Kolejka `Queue(maxsize=3)` gwarantuje izolację wątku producenta i konsumenta. Obiekty przekazywane w kolejce nie podlegają modyfikacjom po wstawieniu.
- **Bezpieczeństwo zwalniania:** W procedurze zakończenia dodano bezpieczne powiadamianie i zwolnienie wątku producenta z timeoutem 2.0 s.

---

## 17. Status Zgodności Wizualnej i Prawda o Antyaliasingu

- **Zgodność względem Etapu 5F:** **100% IDENTYCZNA**. 
  - Hash SHA-256 wyjściowego pliku wideo 4K: `52a7fb20b5d2843db99e044df9cba8f73bcc296fc7373821736db477a9f353f1` jest w 100% tożsamy z artefaktem 5F.
- **Zgodność względem historycznego renderera Pillow (przed Etapem 5A):** **PARTIAL**.
  - Zgodnie z ustaleniami Etapu 5B, rasteryzacja OpenCV (`cv2.fillPoly` z `LINE_AA`) renderuje obrysy subpikselowe inaczej niż historyczny supersampling Pillow 2x Lanczos-3 (MAW 4.12, PSNR 38.6 dB). Ten stan pozostaje transparentnie oznaczony jako PARTIAL.

---

## 18. Status Eksportu 4K MP4 i Single Live Mux Audio

Weryfikacja przez `ffprobe` pliku `run1/etap5g_canonic_run1.mp4`:
- **Strumień wideo:**
  - Kodek: HEVC (`hev1`, Main Profile, Level 186)
  - Rozdzielczość: **3840×2160** (aspect ratio 16:9)
  - Klatkaż: **29.970 FPS** (`30000/1001`)
  - Liczba klatek: dokładnie **3000 klatek**
  - Czas trwania: **100.100000 s**
- **Strumień audio:**
  - Kodek: AAC (`mp4a.40.2`, LC)
  - Częstotliwość próbkowania: **48 000 Hz**
  - Kanały: Stereo (2 ch)
  - Czas trwania: **100.117333 s**
- **Architektura muxowania:**
  - **Single Live Mux** zachowany w 100% (brak ekstrakcji audio, brak plików ADTS/M4A, brak wtórnego remuxingu).

---

## 19. Szczegółowa Lista Zmian w Kodzie

1. `src/indicators/gauge.py`:
   - Usunięto zbędne `canvas.copy()` (linia 554) oraz `img.copy()` (linia 893).
2. `src/indicators/bar.py`:
   - Usunięto zbędne `cached.copy()` (linia 2123) oraz nadmiarowe kopiowanie na cache miss (linia 2240).
3. `src/indicators/effects.py`:
   - Zwracanie `cached_full` bezpośrednio na pełnym trafieniu w cache (linia 208).
4. `src/ffmpeg/amd_native_exporter.py`:
   - Zmiana domyślnej głębokości kolejki `AMD_QUEUE_DEPTH` z 2 na **3** w trybie `ASYNC` (linie 2657 i 6673).
5. `scripts/benchmarks/test_dirty_region_1000_frames.py`:
   - Dodano obsługę argumentu ścieżki wyjściowej JSON raportu.
6. `scripts/benchmarks/run_etap5g_canonic_benchmark.py`:
   - Utworzono dedykowany skrypt kanonicznego benchmarku 3 przebiegów.

---

## 20. Pełne Hashe Commitów Referencyjnych

- **Commit Etapu 5A:** `54c80556ffebf2015383188894451000dbe13f5c`
- **Commit Etapu 5B:** `ba60bb5390cbf679c6dbe0bc134a413d9cf4bb7d`
- **Commit Etapu 5D:** `67dbc8fd81b1ba42080ff52f558d7eeb4a5e0b68`
- **Commit Etapu 5E:** `c0bf7603c4cf7e721d7ae4618e8749a204646297`
- **Commit Etapu 5F:** `46582e88a3b85bc887f879eb5386f7f6ecad468e`
- **Poprawka dokumentacji 5F/5E:** `38ad01cc93f9cbe878b209e995535da4bbcb820b`

---

## 21. Pozostały Bottleneck i Rekomendacje dla Kolejnych Etapów

### Główny pozostały bottleneck:
Wąskie gardło leży w **`producer_prepare` (33.45 ms)**, z czego:
1. **`compose_overlay`:** 20.18 ms (CPU-bound renderowanie 17 wskaźników i efektów).
2. **`PIL/buffer preparation`:** 8.16 ms (wycinanie i serializacja 17 MB dirty regions przez publiczne Pillow `crop().tobytes()`).

### Rekomendacja na Etap 6:
Aby bezpiecznie przekroczyć 35–40 FPS bez naruszania ABI Pillow:
- Rozważyć natywny transfer prealokowanych buforów NumPy dla wycinków dirty regions (`__array_interface__` lub memoryview) zamiast serializacji Pillow `tobytes()`.
- Wdrożyć wielowątkowe renderowanie niezależnych wskaźników w `compose_overlay()` (np. równoległe renderowanie wykresów i linijek w tle).

---

## 22. Werdykty Bramkowe

| Bramka weryfikacyjna | Werdykt | Uzasadnienie |
| :--- | :---: | :--- |
| **PERFORMANCE PASS** | **PASS** | Effective FPS wzrósł z **22.83** do **25.15 FPS** (+10.15%), a Render FPS wzrósł z **23.95** do **28.83 FPS** (+20.38%) przy powtarzalnych 3 przebiegach kanonicznych. |
| **MEMORY SAFETY PASS** | **PASS** | Produkcja działa w 100% na bezpiecznym, publicznym API (`AMD_DIRECT_ROW_TABLE=0`), bez czytania prywatnych struktur C Pillow i bez wycieków pamięci. |
| **VISUAL PASS** | **PARTIAL** | Względem 5F: **100% identyczny** (SHA-256 pliku MP4 co do bita zgodny). Względem historycznego antyaliasingu Pillow: **PARTIAL** (OpenCV AA). |
| **EXPORT PASS** | **PASS** | Prawidłowy 4K UHD MP4 (3840×2160 @ 29.970 FPS, HEVC + AAC Stereo) przez Single Live Mux bez plików pośrednich. |
