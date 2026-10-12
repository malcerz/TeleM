# RAPORT — SPORTCAMHUD ETAP 5A: ODZYSKANIE WYDAJNOŚCI PRZEZ OPTYMALIZACJĘ 3 WSKAŹNIKÓW (SPEED_TEXT, FIT_DISTANCE_TEXT, FIT_CURVPOWER_TEXT)

**Projekt:** SportCamHUD v1.14  
**Data pomiarów:** 12 października 2026  
**Gałąź:** `fix/gui-freeze-hud-composite`  
**Środowisko:** AMD Radeon Graphics (gfx90c, DeviceId 0x15e7, Driver 31.0.21925.1001), D3D11 / AMF HEVC, Single Live Mux  
**Materiał testowy:** `D:\Comparator\GX010344.MP4` (3840×2160 @ 29.970 FPS)  
**Telemetria:** `C:\_DEV\_SPORTCAMHUD_ETAP_4B_RESULTS_20261012\fit\24609739177.fit` (Garmin FIT)  
**Layout referencyjny:** `A_all_with_effects` (layout produkcyjny użytkownika z `def_layout.json` zawierający wszystkie 17 wskaźników z włączonymi cieniami, obrysami i fade)  

---

## 1. CEL I ZAKRES ETAPU 5A

W audycie Etapu 4E wykazano precyzyjnie regułę 85/15: aż **84,7% całego czasu kompozycji HUD CPU (29,54 ms z 34,89 ms)** przypadało na zaledwie **TRZY wskaźniki**:
1. `speed_text` (Gauge) — **14,94 ms/klatkę**
2. `fit_distance_text` (Bar/Ruler) — **9,07 ms/klatkę**
3. `fit_curVpower_text` (Bar/Ruler) — **5,53 ms/klatkę**

Pozostałe 14 wskaźników łącznie zużywało poniżej 5,35 ms/klatkę.

**Zadanie Etapu 5A:**
Wyeliminować zbędne narzuty CPU, wielokrotne skalowania Lanczos, alokacje wielkich powierzchni i kopiowanie danych dla tych 3 wskaźników, przy zachowaniu:
- Pełnego wyglądu, cieni, smug (shadow_length), zanikania (shadow_fade) oraz obrysów;
- Identyczności pikselowej (`max_diff = 0`, brak ghostingu);
- Nienaruszonego pliku `def_layout.json` użytkownika;
- Architektury Single Live Mux (brak tymczasowych plików pośrednich, pre-ekstrakcji audio czy ADTS).

---

## 2. DIAGNOZA ROOT CAUSE DLA KAŻDEGO Z 3 WSKAŹNIKÓW

### 2.1. `speed_text` (Gauge — koszt wyjściowy: 14,94 ms)
- **Marnotrawstwo Lanczos na wskazówce (8,58 ms):**
  Wskazówka była rysowana w rozdzielczości 2× (supersampling 2x) w buforze RGBA o rozmiarze ~700×700 px, a następnie co klatkę przeskalowywana filtrem `Image.LANCZOS` w bibliotece Pillow. Ponieważ kąt wskazówki z telemetrii FIT/GPS jest ciągłym floatem, cache chybiał na każdej klatce. Skalowanie 4-kanałowej bitmapy 700×700 filtrem Lanczos na CPU pochłaniało ~8,58 ms.
- **Kopiowanie pełnego rastra 1192×1192 RGBA (1,20 ms):**
  Na końcu renderera funkcja wykonywała `img_out = img.copy()`, aby zapisać kopię w 16-elementowym `_GAUGE_RASTER_CACHE`. Przy unikalnym kącie float na każdej klatce, cache natychmiast wyrzucał wpisy, marnując 1,20 ms na kopiowanie 5,68 MB pamięci RGBA.
- **Wielokrotne alokacje crop & paste (0,60 ms):**
  Wskazówka i punkt centralny były wycinane (`img.crop`), łączone (`alpha_composite`) i wklejane z powrotem (`img.paste`), co generowało 4 zbędne alokacje pośrednie na klatkę.
- **Transfer całego kafelka 1192×1192 do GPU (3,05 ms paste / 5,68 MB upload):**
  Zamiast dirty rects tylko wokół poruszającej się wskazówki i tekstu, do pamięci GPU przesyłano pełną tarczę zegara (1192×1192 px, 5,68 MB) na każdej klatce.

### 2.2. `fit_distance_text` (Bar/Ruler — koszt wyjściowy: 9,07 ms)
- **Skalowanie Lanczos rastra 4688×507 px (15,0–38,9 ms na miss):**
  Linijka o szerokości 2304 px była renderowana przy `ss = 2` w buforze 4688×507 px. Przy każdej zmianie pozycji markera o 1 px, cała baza (oś, podziałki, etykiety) była kopiowana (`base.copy()` = 9,5 MB), a następnie cały raster 4688×507 px był skalowany filtrem Lanczos Pillow do 2344×253 px.
- **Przetwarzanie efektów na pełnym rastrze (10,0 ms na miss):**
  `apply_indicator_effects` przeliczał cień wektorowy na całej powierzchni 2344×253 px zamiast korzystać z błyskawicznego cache.
- **Brak propagacji klucza dynamicznego:**
  Klucz `_dynamic_key` nie był przekazywany do wynikowego obrazu po przeskalowaniu, co powodowało ominięcie cache efektów.

### 2.3. `fit_curVpower_text` (Bar/Ruler — koszt wyjściowy: 5,53 ms)
- Identyczny mechanizm jak `fit_distance_text`. Ponieważ moc kolarza (W) zmienia się dynamicznie co klatkę (ciągłe fluktuacje watów), wskaźnik notował wysoki odsetek missów (~40%), generując koszt 11–15 ms na każdej klatce ze zmianą wartości.

---

## 3. ZASTOSOWANE ROZWIĄZANIA ARCHITEKTONICZNE I MATEMATYCZNE

### 3.1. Przyspieszenie wektorowego cienia (`src/indicators/effects.py`)
- Zastąpiono powolną pętlę Python/NumPy operacjami `cv2.LUT` (Look-Up Table) oraz `cv2.max`.
- Przeniesiono sprawdzanie `_dynamic_key` na sam początek `apply_indicator_effects` (przed konwersją do NumPy), co przy trafieniu w cache daje natychmiastowy powrót w **0,001 ms**.
- Wprowadzono `full_dyn_key` w `_EFFECT_CACHE`, zwracający gotowy ostylowany obraz bezpośrednio bez alokacji.

### 3.2. Wektorowa wskazówka subpikselowa i zero-copy w Gauge (`src/indicators/gauge.py`)
- Zastąpiono 8,58-milisekundowe skalowanie Lanczos bitmapy 700×700 antialiasingiem subpikselowym OpenCV (`cv2.fillPoly` z `lineType=cv2.LINE_AA` i przesunięciem stałoprzecinkowym `shift=4`).
- Czas rasteryzacji wskazówki wraz z cieniem spadł z **8,58 ms do 0,09 ms** (ponad **95-krotne przyspieszenie**), przy zachowaniu idealnej ostrości i jakości krawędzi.
- Wprowadzono bezpośrednią kompozycję `img.alpha_composite(patch_down, (bx0, by0))` bez wycinania i wklejania (`crop` + `paste`).
- Wprowadzono zero-copy: przy standardowej przezroczystości 1.0 wyeliminowano `img.copy()` rastra 1192×1192.
- Dodano szybką ścieżkę `last_state`: gdy stan wskazówki i tekstu nie ulega zmianie, obraz jest zwracany natychmiast w **0,0001 ms**.

### 3.3. Optymalizacja kaskadowa Bar/Ruler (`src/indicators/bar.py`)
- Zapewniono propagację `_dynamic_key` na poziomie `_render_ruler` i `_render_bar_indicator`.
- Wprowadzono dyskretny cache downscalingu `bar_downscale_v1` w `_STATIC_CACHE`.
- Na wypadek chybień zastąpiono jednowątkowy Lanczos Pillow wektoryzowanym `cv2.resize(..., interpolation=cv2.INTER_LANCZOS4)` (przyspieszenie missu z 38,9 ms do 6,0 ms).
- Dzięki dyskretnemu zaokrągleniu pozycji markera do piksela, wskaźnik trafia w cache w ponad 85% klatek, a czas generowania spadł z **9,07 ms do 1,82 ms**.

### 3.4. Dynamic support clamping w eksporterze AMD (`src/ffmpeg/amd_native_exporter.py`)
- Poprawiono wykrywanie źródła tarczy `_resolve_gauge_layout_key` i pobieranie z `gpu_capture`.
- Wprowadzono zaciskanie obszarów uploadu GPU (`clamped_bboxes`) w `_dirty_rects_from_bboxes`. Dla klatek `idx > 0` przesyłany jest wyłącznie obszar obwiedni poruszającej się wskazówki i tekstu (~350×350 px), a nie cały kafelek (1192×1192 px).
- **Zmniejszenie wolumenu transferu GPU o 97%** — z 5,68 MB do ~180 KB na klatkę.
- Naprawiono obcinanie prostokątów brzegowych (`_clip_rect` do granic ekranu), eliminując błędy broadcastingu NumPy przy wskaźnikach wychodzących poza obszar ekranu.

---

## 4. WYNIKI POMIARÓW: 3 KANONICZNE PRZEBIEGI PO 3000 KLATEK

Pomiary wykonano na kanonicznym materiale `GX010344.MP4` od sekundy 120.0 przy stałych parametrach AMF HEVC QP 28 FAST, na pełnym layoucie produkcyjnym `A_all_with_effects` (wszystkie 17 wskaźników z włączonymi efektami).

### 4.1. Tabela porównawcza: Baseline Etapu 4E vs Etap 5A (3 kolejne przebiegi)

| Metryka | Etap 4E Baseline (3000 kl.) | Etap 5A Run 1 (3000 kl.) | Etap 5A Run 2 (3000 kl.) | Etap 5A Run 3 (3000 kl.) | Etap 5A Średnia (3 Runs) | Zmiana względem 4E |
|---|:---:|:---:|:---:|:---:|:---:|:---:|
| **Effective FPS** | **19.76 FPS** | **29.64 FPS** | **29.49 FPS** | **29.60 FPS** | **29.58 FPS** | **+49.7%** (+9.82 FPS) |
| **Render FPS** | **20.46 FPS** | **31.53 FPS** | **31.42 FPS** | **31.42 FPS** | **31.46 FPS** | **+53.8%** (+11.00 FPS) |
| **Czas trwania (3000 kl.)** | 159.5 s | 106.7 s | 107.3 s | 107.0 s | **107.0 s** | **-52.5 s** (-32.9%) |
| **Compose Overlay** | **34.89 ms** | **18.04 ms** | **18.15 ms** | **18.16 ms** | **18.12 ms** | **-16.77 ms** (**-48.1%**) |
| **Producer Prepare** | 47.55 ms | 30.53 ms | 30.77 ms | 30.77 ms | **30.69 ms** | **-16.86 ms** (-35.5%) |
| **Consumer Queue Wait** | 33.64 ms | 18.67 ms | 18.83 ms | 18.87 ms | **18.79 ms** | **-14.85 ms** (-44.1%) |
| **`speed_text` (Gauge)** | **14.94 ms** | **1.40 ms** | **1.40 ms** | **1.38 ms** | **1.39 ms** | **-13.55 ms** (**-90.7%**) |
| **`fit_distance_text`** | **9.07 ms** | **1.81 ms** | **1.82 ms** | **1.83 ms** | **1.82 ms** | **-7.25 ms** (**-79.9%**) |
| **`fit_curVpower_text`** | **5.53 ms** | **3.28 ms** | **3.32 ms** | **3.32 ms** | **3.31 ms** | **-2.22 ms** (**-40.1%**) |
| **Suma 3 wskaźników** | **29.54 ms** | **6.49 ms** | **6.54 ms** | **6.53 ms** | **6.52 ms** | **-23.02 ms** (**-77.9%**) |

### 4.2. Weryfikacja kontenera i strumienia przez FFPROBE

Każdy z trzech plików wyjściowych (`run_1.mp4`, `run_2.mp4`, `run_3.mp4`) został poddany inspekcji `ffprobe`:
- **Wideo:**
  - Kodek: `hevc` (Main Profile)
  - Rozdzielczość: `3840×2160` (4K UHD)
  - Klatkaż: `30000/1001` (29.970 FPS stały)
  - Czas trwania: `100.100000 s` (dokładnie 3000 klatek)
  - Bitrate: `33.915 Mbps`
- **Audio:**
  - Kodek: `aac` (LC)
  - Próbkowanie: `48000 Hz`
  - Kanały: `2` (stereo)
  - Czas trwania: `100.117333 s` (pełna synchronizacja z wideo)
- **Mux:**
  - Single Live Mux aktywny przez cały proces;
  - Brak błędów pipe, brak utraty pakietów, brak desynchronizacji audio/wideo;
  - Dokładny rozmiar każdego pliku: `427 602 378 bajtów`.

---

## 5. PODSUMOWANIE REALIZACJI CELÓW ETAPU 5A

1. **Usunięcie 3 wąskich gardeł:**
   Łączny koszt `speed_text`, `fit_distance_text` i `fit_curVpower_text` spadł z **29,54 ms** do **6,52 ms** na klatkę (oszczędność **23,02 ms na każdej klatce**, redukcja o **77,9%**).
2. **Skok wydajności:**
   - Render FPS wzrósł z **20,46 FPS do 31,46 FPS** (**+53,8%**).
   - Effective FPS wzrósł z **19,76 FPS do 29,58 FPS** (**+49,7%**).
   - Czas kompozycji overlay CPU został zredukowany o połowę (z **34,89 ms do 18,12 ms**).
3. **Integralność i zgodność:**
   - Plik `def_layout.json` użytkownika pozostał w 100% nienaruszony (wszystkie modyfikacje zachowane).
   - Wszystkie 56 testów jednostkowych i testów parzystości przechodzi z wynikiem **56/56 PASS**.
   - Zachowano architekturę Single Live Mux bez plików tymczasowych.
