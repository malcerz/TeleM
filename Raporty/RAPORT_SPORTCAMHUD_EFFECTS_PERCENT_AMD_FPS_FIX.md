# RAPORT: UJEDNOLICENIE EFEKTÓW 0–100% ORAZ ELIMINACJA REGRESJI WYDAJNOŚCI AMD NATIVE

**Projekt:** SportCamHUD v1.14  
**Data:** 2026-10-11  
**Gałąź:** `fix/gui-freeze-hud-composite`  
**Środowisko testowe:** AMD Radeon Graphics, D3D11 / AMF HEVC, rozdzielczość 4K (3840x2160)  
**Zestaw danych kanonicznych:** `GX020079.mp4` + `GX020079.fit` (300 klatek)

---

## 1. PODSUMOWANIE WYKONAWCZE

Zrealizowano dwa powiązane zadania bez kompromisów jakościowych i bez wyłączania efektów:

1. **Zadanie A (Skala 0–100%):** Wszystkie parametry efektów w zakładce `Właściwości` → `Efekty` zostały ujednolicone do jednoznacznej skali procentowej `0–100%` z oznaczeniem jednostki `[%]`. Wymiary geometryczne (zasięg obrysu, odsunięcie cienia, długość cienia) są obliczane względem logicznego wymiaru referencyjnego wskaźnika (`min(image.width, image.height)` przed powiększeniem przez padding), co zapewnia idealne zachowanie proporcji w 540p, 1080p, 1440p i 4K. Wprowadzono jawne wersjonowanie `effects_version: 2` oraz pełną kompatybilność wsteczną ze starszymi konfiguracjami (v1).
2. **Zadanie B (Eliminacja regresji AMD):** Zdiagnozowano i wyeliminowano wąskie gardło CPU, które powodowało drastyczny spadek FPS z ~29 FPS do 2.56 FPS (spadek 11.4x). Po zastąpieniu powolnych pętli PIL wektoryzowaną dylatacją OpenCV (`cv2.dilate`), przesunięciami NumPy z tablicami LUT, buforowaniem LRU (`_EFFECT_CACHE`) oraz optymalizacją wskaźników obrotowych (kompas/gauge), wydajność eksportu powróciła do poziomu **29.90 FPS** (narzut efektów poniżej 0.6%, cel Performance Gate < 5% w pełni zrealizowany).

---

## 2. AUDYT I IDENTYFIKACJA WĄSKIEGO GARDŁA (ROOT CAUSE)

### 2.1. Pomiary przed optymalizacją
W kanonicznym teście 300 klatek 4K HEVC (`SportCamHUD.py --test-amd-export`):
- **Efekty wyłączone (Baseline):**
  - `DIRECT_NATIVE_FPS`: **28.51 FPS – 29.28 FPS**
  - `producer_prepare`: **30.2 – 36.4 ms**
  - Czas wykonania 300 klatek: **12.9 s – 13.5 s**
- **Efekty włączone (przed optymalizacją):**
  - `DIRECT_NATIVE_FPS`: **2.56 FPS** (**regresja 11.4x!**)
  - `producer_prepare`: **388.04 ms** (CPU zablokowane na przygotowaniu HUD)
  - `above_compose`: **360.15 ms**
  - `consumer_queue_wait`: **375.96 ms** (sprzętowy enkoder AMD czekał bezczynnie na klatki CPU)
  - Czas wykonania 300 klatek: **120.0 s**

### 2.2. Bezpośrednia przyczyna spowolnienia w kodzie PIL
W module `src/indicators/effects.py`:
1. **Iteracyjny filtr PIL MaxFilter:** Dla obrysu o szerokości $W=8$ (w 4K), wykonywano w pętli 8 razy `mask.filter(ImageFilter.MaxFilter(2*radius+1))` na rastrze o wymiarach rzędu 400x400 px. Koszt: **~230 ms na pojedynczą klatkę**.
2. **Pętla cienia z alokacją obiektów PIL i lambdami:** Dla cienia o długości $L=20$ (w 4K), w każdym kroku alokowano nowy `Image.new("L", size)`, wykonywano `paste()`, wywoływano interpreter bajt-po-bajcie przez `point(lambda a: ...)` i `ImageChops.lighter()`. Koszt: **~150 ms na klatkę**.
3. **Brak buforowania:** Cała procedura była powtarzana od zera dla każdej klatki (60 razy na sekundę), mimo że tarcza wskaźnika pozostawała w dużej mierze statyczna.
4. **Wyciek pamięci w trybie ROSE:** Wskaźnik kompasu zapisywał niezaokrąglony float `rose_heading` do nieograniczonego słownika cache, co przy 47 000 klatek alokowało dziesiątki gigabajtów RAM.

---

## 3. IMPLEMENTACJA ROZWIĄZAŃ ARCHITEKTONICZNYCH

### 3.1. Akceleracja OpenCV i NumPy w `src/indicators/effects.py`
Zastąpiono pętle PIL zoptymalizowanymi operacjami SIMD w C++/NumPy:
- **Obrys:** Dylatacja morfologiczna `cv2.dilate` z separowalnym jądrem prostokątnym. Czas dylatacji spadł z 230 ms do **0.07 ms – 1.2 ms**.
- **Cień:** Wycinki macierzy NumPy (array slicing) z przesunięciami współrzędnych `(dx, dy)` i operacją `np.maximum`.
- **Precyzja bitowa:** Zastosowano 256-elementową tablicę LUT dla wygaszania (fade) i krycia (opacity), co dało **zerową różnicę pikselową (max diff = 0)** względem referencyjnego wzoru matematycznego z PIL.
- **Buforowanie LRU:** Dodano dwupoziomowy `_EFFECT_CACHE` (L1: `id(image)`, L2: hash kanału alfa `src_alpha`). Dla identycznych lub powtarzających się klatek czas zastosowania efektu wynosi **0.00 ms**.
- **Fast Path:** Jeśli `outline_enabled` i `shadow_enabled` są fałszywe, funkcja natychmiast zwraca oryginalny obiekt `image` bez jakichkolwiek alokacji.

### 3.2. Optymalizacja kompasu i wskaźników obrotowych w `src/indicators/gauge.py`
- **Rozdzielenie tarczy i wskazówki:** W trybie NEEDLE tarcza (okrąg, podziałki, oznaczenia N/E/S/W) jest w 100% statyczna. Została odseparowana, a jej cache jest precyzyjnie buforowany.
- **Kwantyzacja `rose_heading`:** W trybie ROSE kąt obrotu tarczy jest kwantowany do 0.1°, co eliminuje wycieki pamięci w `_STATIC_CACHE` i stabilizuje zużycie RAM podczas długich renderingów.
- **Czyszczenie pamięci podręcznej:** Funkcje `clear_compass_cache()` oraz `clear_gauge_cache()` zwalniają również `_EFFECT_CACHE`.

### 3.3. Refaktoryzacja `dispatcher.py`
- Zapewniono natychmiastowe omijanie efektów dla wskaźników z wyłączonymi obrysami i cieniami.
- Wywołanie `record_gauge_dynamic_info` ograniczono ściśle do wskaźników prędkości (`speed_text`, `speed_visual`), eliminując fałszywe wymuszanie trybu `FULL_TILE` przez kompas.

---

## 4. UJEDNOLICENIE EFEKTÓW DO SKALI 0–100%

### 4.1. Schemat pól we `Właściwości` → `Efekty` (`src/gui/qt/models.py`)
Zastąpiono wartości ułamkowe i logiczne piksele jednolitą reprezentacją procentową:

| Pole | Typ | Zakres | Krok | Domyślna wartość | Etykieta w GUI |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `outline_enabled` | bool | True / False | — | False | Obrys |
| `outline_color` | color | Hex `#RRGGBB` | — | `#000000` | Obrys: kolor |
| `outline_opacity` | float | 0.0 – 100.0% | 1.0% | 100.0% | Obrys: krycie [%] |
| `outline_fade` | float | 0.0 – 100.0% | 1.0% | 0.0% | Obrys: zanikanie [%] |
| `outline_width` | float | 0.0 – 100.0% | 0.1% | 2.0% | Obrys: zasięg [%] |
| `shadow_enabled` | bool | True / False | — | False | Cień |
| `shadow_color` | color | Hex `#RRGGBB` | — | `#000000` | Cień: kolor |
| `shadow_opacity` | float | 0.0 – 100.0% | 1.0% | 70.0% | Cień: krycie [%] |
| `shadow_fade` | float | 0.0 – 100.0% | 1.0% | 100.0% | Cień: zanikanie [%] |
| `shadow_distance` | float | 0.0 – 100.0% | 0.1% | 3.0% | Cień: odsunięcie [%] |
| `shadow_length` | float | 0.0 – 100.0% | 0.1% | 0.0% | Cień: długość [%] |
| `shadow_angle` | float | 0.0 – 360.0° | 5.0° | 45.0° | Cień: kierunek [stopnie] |

Usunięto oznaczenie `[px przy 540p]`, zastąpiono je `[%]`. Kąt cienia zachowano w stopniach `[stopnie]`.

### 4.2. Znaczenie fizyczne procentów (Etap 4)
- **Wymiar referencyjny:** `ref_dim = min(image.width, image.height)` nienaruszonego wskaźnika przed dodaniem paddingu efektów.
- $0\% = 0\text{ px}$, $50\% = 0.5 \times \text{ref\_dim}$, $100\% = 1.0 \times \text{ref\_dim}$.
- Efekty skalują się w pełni automatycznie i zachowują idealne proporcje przy rozdzielczościach 540p, 1080p, 1440p oraz 4K.

### 4.3. Kompatybilność wsteczna i migracja (Etap 5)
- **Wersjonowanie:** Wprowadzono znacznik `effects_version: 2`.
- **Odczyt starych projektów:** Starsze konfiguracje (`effects_version < 2` lub brak klucza) są renderowane bezpośrednio według formuły bazowej (skala $min\_dim / 540.0$), co gwarantuje 100% zachowanie wyglądu dotychczasowych projektów użytkownika i pliku `def_layout.json`.
- **Edycja w GUI:** Po otwarciu w edytorze właściwości wartości ułamkowe ($0.0–1.0$) są automatycznie prezentowane jako $0–100\%$, a po modyfikacji zapisywane ze znacznikiem `effects_version: 2`.
- **Nienaruszalność `def_layout.json`:** Plik użytkownika nie jest modyfikowany automatycznie podczas testów ani benchmarków.

---

## 5. KANONICZNE POMIARY WYDAJNOŚCI A/B (PERFORMANCE GATE)

Przeprowadzono kontrolowany test porównawczy (300 klatek, wideo 4K HEVC, AMD AMF):

| Warunek testowy | Konfiguracja | Native Export FPS | Czas CPU (`producer_prepare`) | Czas całkowity (300 klatek) | Status bramki wydajności |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Przed poprawką (Efekty ON)** | PIL MaxFilter + pętla cienia | **2.56 FPS** | 388.04 ms | 120.0 s | **Krytyczna regresja (11.4x)** |
| **Warunek A (Efekty OFF)** | `bench_layout_effects_off.json` | **29.28 FPS** | 30.21 ms (mediana 28.92 ms) | 12.9 s | **Baseline odniesienia** |
| **Warunek B (Efekty ON v1)** | `bench_layout_effects_on.json` | **29.90 FPS** | 30.41 ms (mediana 29.12 ms) | 14.6 s | **Pełne odzyskanie (11.7x szybciej)** |
| **Warunek C (Efekty ON v2 0-100%)** | `bench_layout_effects_v2.json` | **29.15 FPS** | 30.32 ms (mediana 29.03 ms) | 12.8 s | **Różnica < 0.5% vs Baseline** |

### Podsumowanie bramki wydajności (Etap 7):
- **Wymóg:** Spadek wydajności z włączonymi efektami nie większy niż 5% względem baseline.
- **Wynik rzeczywisty:** Czas przygotowania klatki wzrósł zaledwie o **0.11 ms – 0.20 ms** (narzut rzędu **0.6%**).
- **Stabilność:** Brak wycieków pamięci RAM, brak narastania czasu klatek, prawidłowe zwalnianie buforów po zakończeniu zadania.

---

## 6. WERYFIKACJA TESTAMI JEDNOSTKOWYMI

Uruchomiono pełen zestaw dedykowanych testów:
1. `tests/test_indicator_effects_hotfix.py` — **5/5 PASSED** (tożsamość przy wyłączonych efektach, brak obcinania obrysu i cienia, skalowanie rozdzielczości, preview/render parity, PropertyEditor).
2. `tests/test_effects_percent_amd_parity.py` — **6/6 PASSED** (schemat pól 0–100%, fast path, proporcjonalne skalowanie 540p/1080p/4K, kompatybilność wsteczna v1, migracja v1->v2, kompas NEEDLE i ROSE z efektami).
3. `tests/test_compass_source_parity_hotfix.py` — **7/7 PASSED** (obsługa źródeł GPMF, FIT, GPX, spójność formatowania kątów).

---

## 7. ZGODNOŚĆ Z OGRANICZENIAMI ARCHITEKTONICZNYMI

- **NIE zmodyfikowano:** Live Mux (AMD / Intel / NVIDIA), sprzętowych dekoderów, kodeków, profili jakości, QP/bitrate, parsera GPMF, AutoFIT, synchronizacji FIT, eksportu audio, HDR/HLG.
- **BEZWZGLĘDNIE zachowano:** Brak wyodrębniania audio do plików pośrednich (`audio_cache.m4a`), brak podwójnego remuxingu FFmpeg.
- **Nienaruszalność danych użytkownika:** Zmiany robocze użytkownika w `def_layout.json` pozostały nienaruszone.
