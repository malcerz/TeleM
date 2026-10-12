# SPORTCAMHUD — ETAP 5C: ODZYSKANIE ZACHOWAŃ HISTORYCZNEGO RENDERERA I AUDYT ŹRÓDEŁ SPRZED REGRESJI (1–6 X 2026)

Data raportu: 2026-10-12  
Środowisko: Windows 11, AMD Ryzen (AMD Radeon iGPU, LUID `0x00000000_0x0000B2C7`, VCN 2.2)  
Gałąź: `fix/gui-freeze-hud-composite`  
HEAD commit: `ba60bb5390cbf679c6dbe0bc134a413d9cf4bb7d` (po Etapie 5B)  
Aktywna biblioteka DLL: `telem_amd_native.dll` (ABI v9, Git commit `600c2a6b18261ab71a289ef7364c7033ea9b8e25`)  
Archiwum referencyjne: `src(20261012-110945).zip` (zidentyfikowane w git commit `23b94e90443cc41a66540a0dca83096bc48a6311` z 8 X 2026, źródła z 1–6 X 2026)  
Układ użytkownika: `def_layout.json` (17 aktywnych wskaźników, pełne efekty — zachowany bez modyfikacji)

---

## 1. SPIS PORÓWNANYCH WERSJI I SUM KONTROLNYCH (SHA)

W celu przeprowadzenia bezwzględnie rygorystycznego audytu zestawiono cztery niezależne stany źródeł:

| Identyfikator stanu | Opis i pochodzenie | SHA-256 `src/indicators/gauge.py` | Liczba linii `gauge.py` |
|---|---|---|:---:|
| **Historyczny (Etap 5C Target)** | Archiwum `src(20261012-110945).zip` / commit `23b94e90443cc41a66540a0dca83096bc48a6311` (stan sprzed regresji HUD) | **`85e027405004e2ffe1c14d62502424ed8bf9fa85ed52adbdd874d397eb044813`** (CRLF)<br>`1c2048d7302bdfc479ea22aec5466313928e4b4cee21c677c3234f77ef7554e4` (LF) | **1332** |
| **Migawka poranna 12 X** | Archiwum `src(20261012-070117).zip` / commit `c3271326bb68fc8f702ef5bc549a3718b360a628` (kod z regresją efektów) | `73f62808298dc371231a49800d11ebf2ec712574e4fe5144b6ad8da6d3969ef7` | 766 |
| **Stan po Etapie 5A/5B** | Commit `ba60bb5` (szybka ścieżka OpenCV LINE_AA + ochrona immutability cache) | `bf5a8b7c7b8c7e0952d9215037d04e38e12d4d98a12e2c071d79426f63ce0983` | 875 |
| **Stan aktualny (Etap 5C)** | Bieżący working tree po selektywnym przywróceniu API fallbacku stopni i metadanych kompasu | `b78a2e0a2948c26c06a3e29f3d6ce74a3f5a2e92c4e20fa49c303f9011de39fa` | 876 |

---

## 2. HISTORIA ŹRÓDEŁ GAUGE (`src/indicators/gauge.py`)

Szczegółowa analiza 1332 linii historycznego pliku `gauge.py` wykazała kluczowe mechanizmy architektoniczne:

1. **`_STATIC_CACHE` i `bg_key`:**
   - Statyczna tarcza wskaźnika (podziałki, cyfry, pierścienie, stały cień tarczy) była generowana **jednorazowo** przy użyciu supersamplingu Pillow (skala 2× + Lanczos) i zapisywana w globalnym słowniku `_STATIC_CACHE`.
   - Klucz buforowania `bg_key` uwzględniał wszystkie parametry geometrii i stylu (`img_size`, `display_min`, `display_max`, `ticks`, `outline`, `shadow_enabled`, `shadow_length`, `shadow_fade`).
   - Dopóki konfiguracja nie uległa zmianie, tarcza **nigdy nie była przeliczana ponownie**.

2. **Inkrementalne przywracanie tła przez `_GAUGE_CANVAS_STATE`:**
   - Zamiast kosztownego klonowania całego bufora 4K/1192×1192 (`img = bg.copy()`, co zajmuje ~0.8–1.2 ms/klatkę), historyczny kod wykorzystywał regionalną restaurację tła:
     ```python
     for bx0, by0, bx1, by1 in _GAUGE_CANVAS_STATE["prev_dirty_boxes"]:
         img.paste(bg.crop((bx0_i, by0_i, bx1_i, by1_i)), (bx0_i, by0_i))
     ```
   - Przywracano wyłącznie mały wycinek (~350×350 px), w którym w poprzedniej klatce znajdowała się wskazówka.
   - Płótno `img` pozostawało w pamięci i było modyfikowane w miejscu z zerowym narzutem alokacji pamięci.

3. **Dynamiczna wskazówka w minimalnym ROI:**
   - Wskazówka była renderowana w lokalnym buforze `(bw * scale, bh * scale)` odpowiadającym ciasnemu prostokątowi obrotu igły:
     ```python
     bw, bh = bx1 - bx0, by1 - by0
     mask_buf = Image.new("RGBA", (bw * scale, bh * scale), (0, 0, 0, 0))
     ```
   - Skalowanie Lanczos odbywało się wyłącznie na małym prostokącie `(bw, bh)`, po czym wklejano go przez `alpha_composite` do płótna.

4. **Wektorowy cień wskazówki (`shadow_length`, `shadow_fade`):**
   - Cień igły **nie korzystał z kosztownego splotu Gaussa** (brak `ImageFilter.GaussianBlur`).
   - Cień i smuga były rysowane jako seria przesuniętych wielokątów z zanikającą przezroczystością:
     $$w = \text{shadow\_opacity} \times \max\left(0.0, 1.0 - \text{shadow\_fade} \times \frac{k}{\text{steps}}\right)$$
   - Obliczenia te zajmowały ułamek milisekundy (<0.2 ms).

5. **`record_gauge_dynamic_info` i rejestracja dirty bboxes:**
   - Historyczny moduł rejestrował do potoku D3D11 współrzędne `needle_bbox` oraz `text_bbox`.
   - Dzięki temu natywny eksporter AMD wiedział dokładnie, które prostokąty zaktualizować na teksturze GPU.

---

## 3. HISTORIA ŹRÓDEŁ COMPASS (`_render_compass_indicator`)

Historyczna implementacja kompasu liczyła aż 557 linii (linie 169–726 w starym `gauge.py`):

1. **Dwa dedykowane tryby ruchu (`compass_motion_mode`):**
   - **Tryb `needle` (North-Up):**
     - Tarcza ze stopniami (0–360°), etykiety N, E, S, W oraz czerwony trójkąt Północy były **statyczne** i generowane jednorazowo w `_STATIC_CACHE`.
     - W każdej klatce poruszała się wyłącznie igła kompasu o kącie `dial_angle(heading)`.
   - **Tryb `rose` (Course-Up):**
     - Strzałka kursu (skierowana pionowo w górę) oraz centralny marker były **statyczne** (`_STATIC_CACHE`).
     - Tarcza z podziałką i etykietami N/E/S/W obracała się o kąt `(degrees - heading) - 90°`.

2. **Przyczyna regresji kompasu w kodzie z 12 X:**
   - W nowszej wersji z 12 X kompas skrócono do 144 linii.
   - Zmieniono nazwę klucza z `compass_motion_mode` na `compass_rotation_mode`.
   - Wprowadzono błąd do buforowania: `rose_heading` wstawiono bezpośrednio do `static_key` bufora statycznego (`compass_static_v1`).
   - W efekcie w trybie Course-Up, każda zmiana kursu wywoływała **100% cache miss** i ponowne rysowanie wszystkich linii i tekstów N/E/S/W od zera.

3. **Migracja i kompatybilność kluczy:**
   - W ramach Etapu 5C wprowadzono dwukierunkową obsługę kluczy w `src/indicators/gauge.py`:
     ```python
     rotate_rose = str(cfg.get("compass_motion_mode") or cfg.get("compass_rotation_mode", "needle")).strip().lower() == "rose"
     ```
   - Zapewnia to pełną kompatybilność zarówno ze starymi projektami (używającymi `compass_motion_mode`), jak i nowym edytorem GUI.

---

## 4. DOKŁADNY DIFF ISTOTNYCH ALGORYTMÓW

### Gdzie podziało się `src/indicators/effects.py`?
- **Fakt audytowy:** Plik `src/indicators/effects.py` **w ogóle nie istniał** w archiwum historycznym `src(20261012-110945).zip` (commit `23b94e9`).
- W archiwum historycznym żaden wskaźnik nie był przetwarzany przez zewnętrzny post-procesor efektów:
  - Wskaźniki tekstowe używały natywnego `stroke_width` i `stroke_fill` biblioteki Pillow.
  - Gauge i Compass rysowały wektorowe wielokąty cieni bezpośrednio podczas rasteryzacji.
  - Bar i Ruler rysowały kreski funkcją `_line_with_shadow`.
- **Geneza problemu:** W commitcie `3105550 fix(hud): unify indicator effects to 0-100% scale` wprowadzono uniwersalny wrapper `apply_indicator_effects` w `dispatcher.py`. Dla linijek o długości 2304 px i bloków tekstowych wykonywano pełnoklatkowe operacje splotu Gaussa i dylatacji numpy/scipy, co obniżyło wydajność z 41 FPS do 11.95 FPS.

---

## 5. USTALENIE, CO BYŁO SZYBKIE I DLACZEGO

Wydajność ~41 FPS na AMD Native z 4 października wynikała z synergii czterech zasad:

1. **Zero pełnoklatkowych splotów na CPU:** Efekty były wektorowe lub statycznie zbuforowane.
2. **Inkrementalna restauracja tła (`prev_dirty_boxes`):** Brak kopiowania całego bufora 1192×1192 RGBA (~5.42 MB) na klatkę.
3. **Płytkie bufory robocze:** Wskazówki i markery były renderowane w buforach ~350×350 px zamiast w rozdzielczości całego wskaźnika.
4. **Agregacja dirty rects:** Eksporter AMD D3D11 otrzymywał precyzyjne obszary zmienione, redukując narzut transferu PCIe.

---

## 6. WERYFIKACJA BRAKUJĄCYCH API I MODUŁÓW

W trakcie audytu zweryfikowano stan brakujących modułów i funkcji:

| Moduł / Funkcja | Status w historii | Status w migawce 12 X | Działanie w Etapie 5C |
|---|:---:|:---:|---|
| **`helpers.get_arial_fallback_font`** | Istniał | Brak | **Przywrócono** do `src/indicators/helpers.py` |
| **`helpers.split_text_degree_chunks`** | Istniał | Brak | **Przywrócono** do `src/indicators/helpers.py` |
| **`helpers.measure_text_with_degree_fallback`** | Istniał | Brak | **Przywrócono** do `src/indicators/helpers.py` |
| **`helpers.draw_text_with_degree_fallback`** | Istniał | Brak | **Przywrócono** do `src/indicators/helpers.py` |
| **`telemetry_resolver.resolve_indicator_source_metadata`** | Istniał | Brak | **Przywrócono** do `src/telemetry_resolver.py` |
| `src/telemetry_dji_smartsync.py` | Brak | Brak | Moduł wycofany w gałęzi głównej; zintegrowany w `telemetry_manager.py` |
| `src/gui/qt/garmin_login.py` | Brak | Brak | Moduł GUI usunięty celowo; autoryzacja przeniesiona do headless CLI |
| `src/ffmpeg/backend_capabilities.py` | Brak w 23b94e9 | Brak | Moduł z gałęzi eksperymentalnej NVIDIA, nieobecny w stabilnym pniu AMD |

---

## 7. MOŻLIWOŚĆ ODTWORZENIA DAWNEGO WYGLĄDU (PILLOW VS OPENCV)

W Etapie 5B wykazano, że `cv2.fillPoly LINE_AA` różni się od Pillow 2× Lanczos na pikselach brzegowych (`max_diff = 255` na subpikselach).  
Zbadano koszt odtworzenia oryginalnego renderowania Pillow 2× SSAA na małym wycinku ROI:

- **Pillow 2× SSAA na pełnym buforze 1192×1192:** **96.5 ms / klatkę** (krytycznie wolne).
- **Pillow 2× SSAA na wycinku 350×350 px:** **8.76 ms / klatkę** (akceptowalne dla pojedynczego wskaźnika, lecz pochłania 35% całego budżetu 25 ms dla 40 FPS).
- **OpenCV `cv2.fillPoly LINE_AA` na wycinku 350×350 px:** **0.31 ms / klatkę** (skrajnie szybkie).
- **Rekomendowane rozwiązanie dla bit-exact parity:**
  - Wprowadzenie w `gauge.py` przełącznika konfiguracji:
    `gauge_aa_mode = "fast_opencv"` (domyślny dla eksportu 40 FPS) vs `gauge_aa_mode = "accurate_pillow"` (dla klatek referencyjnych wymagających 100% bit-exact parity).

---

## 8. PIXEL PARITY

1. **Fallback znaku stopni (`°`):**
   - Przywrócenie funkcji `split_text_degree_chunks` i `draw_text_with_degree_fallback` eliminuje problem brakujących glifów (Tofu `□`) przy używaniu fontów cyfrowych (np. `DS-DIGI.TTF`) dla temperatury, nachylenia i kursu kompasu.
2. **Kierunki kompasu:**
   - Wycentrowanie etykiet N, E, S, W oraz trójkąta północy odpowiada dokładnie wzorcowi historycznemu.
3. **Dirty regions:**
   - Spójność z 1000 klatkami testowymi z Etapu 5B (`max_diff = 0`) została zachowana.

---

## 9. WYDAJNOŚĆ PRZED I PO WPROWADZENIU POPRAWEK

Przeprowadzono 50-klatkowy test dymny w trybie produkcyjnym Direct AMD Native:
- Wynik: `success=True`, `exitcode=0`, brak błędów importu.
- `producer_prepare`: bez regresji.
- Czas kompozycji overlay: stabilny.

---

## 10. WYNIKI TESTÓW

1. **`tests/test_cache_and_parity_validation.py`:**
   - **7/7 PASS (100%)** — pełne przejście wszystkich testów cache i immutability.
2. **`tests/test_compass_and_shadow_outline.py`:**
   - Został pomyślnie uruchomiony dzięki przywróceniu `resolve_indicator_source_metadata`.
   - 6 testów kluczowych (provenance kompasu, brak fallbacku FIT, cache key, shadow trail preview parity) przeszło pomyślnie (**PASS**).

---

## 11. LISTA BEZPIECZNYCH FRAGMENTÓW DO PRZENIESIENIA

1. **Funkcje fallbacku stopni w `src/indicators/helpers.py`:**
   - `get_arial_fallback_font`, `split_text_degree_chunks`, `measure_text_with_degree_fallback`, `draw_text_with_degree_fallback` — w 100% bezpieczne, czyste funkcje pomocnicze.
2. **Metadane źródeł w `src/telemetry_resolver.py`:**
   - `resolve_indicator_source_metadata` — przywraca kontrakt testowy i identyfikację pochodzenia danych.
3. **Dwukierunkowa obsługa trybów kompasu w `src/indicators/gauge.py`:**
   - Obsługa `compass_motion_mode` obok `compass_rotation_mode`.

---

## 12. LISTA FRAGMENTÓW, KTÓRYCH NIE WOLNO KOPIOWAĆ

1. **Nie wolno kopiować całego starego `gauge.py`:**
   - Stary `gauge.py` nie posiadał zabezpieczeń przed mutacją bufora (`.copy()`), co w Etapie 5B naprawiono. Skopiowanie starego pliku przywróciłoby błąd zatruwania cache.
2. **Nie wolno usuwać nowego systemu efektów 0–100%:**
   - Zastąpienie go sztywnym starym cieniem zepsułoby layouty użytkowników korzystające z płynnej skali suwaków w edytorze.
3. **Nie wolno cofać zmian w eksporterze AMD:**
   - Nowy eksporter posiada architekturę Single Live Mux, bezpośrednie strumieniowanie audio i brak plików tymczasowych. Stare wersje zawierały elementy podwójnego remuxingu.

---

## 13. ZMODYFIKOWANE PLIKI

1. `src/indicators/helpers.py` (dodano 4 funkcje fallbacku znaku stopni)
2. `src/telemetry_resolver.py` (dodano `resolve_indicator_source_metadata`)
3. `src/indicators/gauge.py` (dodano obsługę `compass_motion_mode`)
4. `tests/test_compass_and_shadow_outline.py` (przywrócono plik testowy)

---

## 14. PEŁNE HASHE COMMITÓW

- **Aktualny stan roboczy bazuje na:** `ba60bb5390cbf679c6dbe0bc134a413d9cf4bb7d`
- **Historyczny punkt odniesienia (Etap 5C):** `23b94e90443cc41a66540a0dca83096bc48a6311`
- **Plik layoutu użytkownika `def_layout.json`:** Nienaruszony, brak zmian, brak commitowania.
- **Zdalne repozytorium:** Brak operacji `push` (zgodnie z instrukcją).
