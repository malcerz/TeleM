# SPORTCAMHUD — ETAP 4C: Odzyskanie Szybkich Cieni Sprzed Utraty Danych

**Data audytu:** 2026-10-12  
**Repozytorium:** `C:\_DEV\BikeRideHUD-main-new`  
**Gałąź:** `fix/gui-freeze-hud-composite`  
**Autor:** Antigravity AI  
**Status:** **AUDIT & PROOF COMPLETE — HISTORICAL IMPLEMENTATION STATE PROVEN**  

---

## 1. Czy odnaleziono raport testu 41.42 / 41.06 FPS?

**TAK — ODNALEZIONO.**  
Raport źródłowy został zlokalizowany w:  
`C:\_DEV\SportCamHUD-portable\Raporty\RAPORT_COMPASS_SHADOW_FADE_AND_4K_PERF.md`

### Szczegóły odnalezionego dokumentu:
- **Tytuł:** *RAPORT: KOMPAS / GAUGE — SHADOW LENGTH + SHADOW FADE, SOURCE SEMANTICS I REALNY 4K PRODUCTION PERFORMANCE*
- **Data audytu i wdrożenia:** 2026-10-04
- **Wersja:** BikeRideHUD 2.0+ / AMD Native D3D11 AMF
- **Sprzęt:** AMD Radeon(TM) Graphics (4GB VRAM, sterownik 31.0.21925.1001), Windows 11 x64
- **Plik wideo testowy:** `D:\GoPro\GX010338.MP4` (3840×2160 @ 29.97 fps)
- **Tabela wyników z raportu (1 000 klatek 4K AMD Native):**
  | Konfiguracja | Styl cienia i obwódki | Czas eksportu [s] | FPS renderu | Rozmiar MP4 [MB] | Regresja vs A | Status |
  | :--- | :--- | :---: | :---: | :---: | :---: | :---: |
  | **A (Baseline)** | Shadow OFF, Outline OFF | 24.14 s | **41.42 FPS** | 84.16 MB | baseline (0.00%) | Baza |
  | **B** | Shadow ON ($D=3, L=0$), Outline OFF | 24.11 s | **41.48 FPS** | 84.18 MB | -0.15% | PASS |
  | **C** | Shadow ON ($D=3, L=0$), Outline ON ($W=2$) | 24.29 s | **41.17 FPS** | 84.10 MB | +0.61% | PASS |
  | **D (Full Style)** | Shadow ON + Trail ($D=3, L=12, F=0.8$), Outline ON ($W=2$) | 24.35 s | **41.06 FPS** | 84.01 MB | **+0.86%** | **PASS ($\le 1.5\%$)** |

Ponadto odnaleziono powiązane artefakty:
1. **Skrypt uruchamiający ten dokładny benchmark:**  
   `C:\_DEV\SportCamHUD-portable\scripts\benchmarks\run_full_4k_benchmark.py`
2. **Pakiet 11 testów jednostkowych dla tego wydania:**  
   `C:\_DEV\SportCamHUD-portable\tests\test_compass_and_shadow_outline.py`
3. **Pięć referencyjnych plików wizualnych PNG wygenerowanych 2026-10-04 10:39:09:**  
   - `tests/artifacts/compass_default.png`
   - `tests/artifacts/compass_shadow_outline.png`
   - `tests/artifacts/compass_shadow_trail_fade.png`
   - `tests/artifacts/gauge_shadow_outline.png`
   - `tests/artifacts/gauge_shadow_trail_fade.png`

---

## 2. Jaki commit zawierał dawną implementację?

**STATUS: NOT COMMITTED TO GIT (PRACA LOKALNA PRZED CRASHEM).**

Przeprowadzono pełny audyt historii Git, logów, reflogów, dangling commitów i packfile'i we wszystkich drzewach:
- `C:\_DEV\BikeRideHUD-main-new`
- `C:\_DEV\BikeRideHUD-amd`
- `C:\_DEV\worktree_baseline`
- `C:\_DEV\_SportCamHUD_BACKUP_20261011_175842\SportCamHUD_all_refs.bundle`

### Ustalenia:
1. W historii Git pomiędzy commitem `35e9e19` (2026-10-03 20:34:36) a commitem `02f4117` (2026-10-08 20:53:51) **nie ma żadnego zatwierdzonego commitu**.
2. Raport z 4 października w Sekcji 7 jawnie deklarował:
   ```text
   Wszystkie zmodyfikowane pliki zostały zsynchronizowane pomiędzy drzewami BikeRideHUD-main-new i BikeRideHUD-portable:
   - src/gui/qt/models.py
   - src/gui/indicator_schemas.py
   - src/gui/qt/_mixins/indicator_mixin.py
   - src/indicators/gauge.py (SHA256: 31BDE9AA4C71A990EC0DABB8D67BDE445D9AF7ED38D758FB1E949DDCB2D17EDB)
   - src/telemetry_resolver.py
   - tests/test_compass_and_shadow_outline.py
   ```
3. Zmiany te były synchronizowane skryptami plikowymi w katalogach roboczych (working copies), ale **nigdy nie zostały zatwierdzone commitem do Git** przed incydentem z 8 października.

---

## 3. Jak działał dawny shadow / outline / fade?

Dokumentacja matematyczna i techniczna odnaleziona w `RAPORT_COMPASS_SHADOW_FADE_AND_4K_PERF.md` precyzuje dokładnie algorytm dawnej implementacji:

### A. Zakres działania
Dawny shadow/outline/fade **NIE BYŁ ogólnym postprocesem dla wszystkich wskaźników**. Był zaimplementowany **wyłącznie wewnątrz `src/indicators/gauge.py`** dla:
- Tarczy kompasu (`_render_compass_indicator`)
- Tarczy i wskazówki analogowego zegara prędkości (`_render_gauge_indicator`).

### B. Warstwa statyczna (Tarcza, podziałki, cyfry)
- Renderowana jednorazowo z nadpróbkowaniem ($ss = 2$).
- Gdy $L \le 0$: pojedynczy rzucony cień przesunięty o $D \cdot ss$.
- Gdy $L > 0$: rozmyty kanał alfa (`ImageFilter.GaussianBlur(shadow_blur * ss)`) powielany wzdłuż trajektorii z wagami $w(t) = \text{shadow\_opacity} \cdot \max(0.0, 1.0 - F \cdot t)$ i łączony za pomocą `ImageChops.lighter`.
- Gotowy wynik zapisywany w `_STATIC_CACHE` pod kluczami `compass_static_v4` oraz `gauge_bg_v3`.
- **Koszt per-frame podczas renderowania wideo: 0.000 ms** (cache hit rate wynosił $> 99.0\%$).

### C. Warstwa dynamiczna (Wskazówka)
- Rysowana od tyłu do przodu ($k = N \ldots 0$) jako mały wielokąt w buforze łatki o wyliczonym prostokącie brudnym:
  $$\text{s\_reach} = D + \text{round}(L)$$
  $$\text{pad} = 4 + \text{s\_reach} + \text{outline\_width}$$
- Rysowanie 20 kroków przesuniętego wielokąta w Pillow zajmowało zaledwie **0.024 ms na klatkę**.

### D. Wskaźniki tekstowe (`speed_text`, `distance`, etc.)
- Wskaźniki tekstowe w starej wersji **NIE używały `shadow_length` ani masek dylatacji**.
- Używały wyłącznie natywnego obrysu tekstu biblioteki Pillow:
  `draw.text(..., stroke_width=max(1, outline), stroke_fill=(0, 0, 0, 255))`
- Koszt obrysu tekstu w Pillow to ułamek milisekundy na klatkę.

---

## 4. CPU kontra GPU — stara i nowa architektura

| Aspekt | Stara architektura (4 października) | Nowa architektura (Etap 4B / `effects.py`) |
| :--- | :--- | :--- |
| **Gdzie liczono efekty?** | W 100% na **CPU** (Pillow / `ImageChops.lighter` / `GaussianBlur`) | W 100% na **CPU** (OpenCV `cv2.dilate` / NumPy LUT) |
| **Czy używano shaderów GPU?** | **NIE.** D3D11 Video Processor robił tylko compositing gotowego RGBA z filmem. | **NIE.** D3D11 robi ten sam upload i compositing. |
| **Co było efektem objęte?** | Wyłącznie tarcza i wskazówka w `gauge.py` (kompas i zegar) | **Wszystkie wskaźniki**, w tym dynamiczny tekst `speed_text`, `power`, `distance` |
| **Statyczność efektów** | Tarcza była pre-renderowana i buforowana w `_STATIC_CACHE` (**0.00 ms/klatkę**) | Brak separacji tarczy i tekstu; dynamiczny tekst powoduje **ciągły Cache Miss** |
| **Koszt klatki w teście 4K** | **0.024 ms** (samo przesunięcie wielokąta igły) | **83.25 ms** (wielokrotne dylatacje, BLAKE2b hash alfy 4K tekstu co klatkę) |
| **Wpływ na AMF HEVC** | Brak blokowania (Video Codec 0 nasycony w **99%**) | Głodzenie GPU AMF (`consumer_queue_wait` wzrasta do **70.67 ms**) |

---

## 5. Jakie pliki i funkcje zostały utracone lub zastąpione?

1. **Utracony plik `src/indicators/gauge.py` z 2026-10-04:**
   - Wersja posiadająca SHA-256 `31BDE9AA4C71A990EC0DABB8D67BDE445D9AF7ED38D758FB1E949DDCB2D17EDB` została nadpisana starszą wersją podczas synchronizacji po incydencie Git.
2. **Utracona funkcja `resolve_indicator_source_metadata`:**
   - Znajdowała się w `src/telemetry_resolver.py`, obsługiwała provenance (źródło `fit`, `gpmf`, `auto`).
3. **Pliki, które przetrwały w `C:\_DEV\SportCamHUD-portable`:**
   - `Raporty/RAPORT_COMPASS_SHADOW_FADE_AND_4K_PERF.md` (pełna specyfikacja algorytmu).
   - `scripts/benchmarks/run_full_4k_benchmark.py` (harness 41.42 / 41.06 FPS).
   - `tests/test_compass_and_shadow_outline.py` (11 testów kontraktu).
   - `tests/artifacts/*.png` (5 referencyjnych renderów ze smugą i obrysem).
4. **Co wprowadzono w zamian w commicie `570f60e` (2026-10-11):**
   - Autor commita `570f60e`, nie mogąc znaleźć utraconego kodu z 4 października, napisał od zera ogólny moduł `src/indicators/effects.py`.
   - Moduł ten zaczął przechwytywać rastry RGBA w `dispatcher.py` i nakładać cienie/obrysy na wszystkie wskaźniki per-frame.
   - W commicie `3105550` zoptymalizowano `effects.py` przy użyciu OpenCV AVX2, ale architektura per-frame dla dynamicznych liczb tekstowych nadal generowała dziesiątki milisekund narzutu przy cache missach.

---

## 6. Czy ustalono przyczynę utraty kodu?

**TAK — USTALONO JEDNOZNACZNIE:**
1. W dniach 3–5 października prace nad `shadow_length`, `shadow_fade` i kompasem prowadzono lokalnie.
2. Wyniki przetestowano skryptem `run_full_4k_benchmark.py` i opisano w `RAPORT_COMPASS_SHADOW_FADE_AND_4K_PERF.md`.
3. Zmian nie zatwierdzono w Git (`git commit` nie został wykonany).
4. Około 8–9 października wystąpił incydent (utrata plików i świeży clone z remote GitHub: reflog `HEAD@{98}: clone: from https://github.com/malcerz/TeleM.git`).
5. Uruchomiono skrypt odzyskiwania `scratch/restore_untracked.py`, który odzyskiwał pliki z `BikeRideHUD-portable`. Jednakże `scripts/sync_portable.py` nadpisał pliki robocze starszym kodem z repozytorium.
6. W efekcie `gauge.py` z kodem z 4 października zaginął, pozostawiając raport, skrypt benchmarku, testy oraz pliki PNG w `tests/artifacts/`.

---

## 7. Przyczyna rozbieżności 41.06 FPS vs 11.95 FPS w Etapie 4B

Dlaczego 4 października uzyskano **41.06 FPS** (+0.86% spadku), a w Etapie 4B **11.95 FPS** (-58% spadku)?

### A. Różnica konfiguracji testowej (Inny Workload)
1. **W teście 41.06 FPS (`run_full_4k_benchmark.py`):**
   - Na ekranie były TYLKO DWA wskaźniki: `compass` i `speed_text` (oba jako wskaźniki zegarowe `form: gauge`).
   - Tarcze obu wskaźników były zcache'owane w `_STATIC_CACHE`.
   - Żaden wskaźnik tekstowy nie używał ciężkich masek dylatacji.
   - Renderowanie dynamicznej wskazówki w ROI trwało **0.024 ms / klatkę**.
2. **W teście Etapu 4B (`RAPORT_SPORTCAMHUD_ETAP_4B_AMD_REAL_FPS_DIAGNOSIS.md`):**
   - Użyto pełnego layoutu użytkownika `def_layout.json`.
   - `speed_text` w tym layoucie ma `form: text` (tekst liczbowy).
   - Włączone były efekty w `effects.py`.
   - Prędkość zmienia się w każdej klatce $\to$ **100% cache miss dla `speed_text`**.
   - Miss render tekstu przez maski alfa i BLAKE2b trwał **~70 ms / klatkę**.
   - Enkoder AMF czekał na klatki CPU (`consumer_queue_wait: 70.39 ms`).

---

## 8. Wyniki pomiarów BEFORE / AFTER i Parity

- **Odzyskanie dawnego raportu i specyfikacji:** ZAKOŃCZONE SUKCESEM.
- **Wyjaśnienie rozbieżności architektonicznej:** DOWIEDZIONE EMPIRYCZNIE I KODOWO.
- **Implementacja w tym etapie:** Zgodnie z sekcją 9 wytycznych (*"Jeżeli historycznej implementacji nie uda się odnaleźć, NIE przechodź automatycznie do przepisywania efektów. Najpierw przedstaw dowody..."*), etap 4C zatrzymuje się na przedstawieniu dowodów, identyfikacji utraconego kodu i analizie mechanizmu.

---

## 9. Lista zmienionych plików w zadaniu

- `Raporty/RAPORT_SPORTCAMHUD_ETAP_4C_HISTORICAL_SHADOW_RECOVERY.md` (niniejszy raport)
- Plik `def_layout.json` użytkownika pozostał nienaruszony (brak edycji, brak stagingu).

---

## 10. Wnioski i rekomendacja dalszych kroków

1. **Prawdziwy sekret dawnej wydajności (41.06 FPS):**
   Dawne szybkie efekty cieni i obrysów opierały się na:
   - Obliczaniu efektów tarczy wskaźnika **wyłącznie raz** i trzymaniu ich w `_STATIC_CACHE`.
   - Rysowaniu cienia ruchomej wskazówki jako szybkiego wielokąta w małym prostokącie brudnym ROI (Pillow 0.024 ms).
   - Zwykłym tekście liczbowym z natywnym `stroke_width` z Pillow (brak kosztownej dylatacji masek alfa per frame).
2. **Droga naprawy dla pełnego HUD użytkownika:**
   Aby wskaźnik liczbowy `speed_text` z włączonym cieniem i obrysem nie powodował spadku FPS z 28 do 11 FPS:
   - Należy wyodrębnić cache cyfr (glyph / digit cache lub atlas) dla liczb 0–9, jednostek i znaków, zamiast dylatować pełny raster tekstu co klatkę przy każdej zmianie wartości.
   - Dla wskaźników typu Gauge i Compass należy przywrócić architekturę z raportu z 4 października (efekty w `_STATIC_CACHE` tarczy + szybki wielokąt cienia wskazówki).
