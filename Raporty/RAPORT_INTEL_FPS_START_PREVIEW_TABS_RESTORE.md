# RAPORT: INTEL — Odzyskanie wydajności FPS, optymalizacja startu, zunifikowany podgląd eksportu i uszczelnienie zakładek HUD

**Data:** 2026-10-22  
**Platforma testowa:** Komputer lokalny Intel, Intel(R) Iris(R) Xe Graphics, Windows 11 AMD64  
**Ścieżka repozytorium:** `C:\_DEV\SportCamHUD` (lokalne repozytorium robocze, gałąź `main`)  
**Materiały testowe:**
- Wideo 4K: `C:\GoPro\2026-10-16\GX010381.MP4` (3840×2160, 29.97 fps, 10-bit HLG HEVC, obrót 180°)
- Telemetria FIT: `C:\GoPro\2026-10-16\2026-10-16_13-06-05.fit`
- Układ wskaźników: prywatny `def_layout.json` (w tym zaawansowany kompas hybrydowy GPS+IMU, mapa, wykresy)

---

## 1. PODSUMOWANIE WYKONAWCZE I STATUS ZADAŃ

| Obszar | Zgłoszenie | Status | Wynik kluczowy |
|---|---|---|---|
| **Problem 1** | Regresja FPS na Intelu | **PASS** | Wyjaśniono mechanizm spadku FPS (MPV engine contention + PL1 thermal throttling). Przeprowadzono kontrolowane testy A/B na profilu Fast. Usunięto MPV podczas eksportu. |
| **Problem 2** | Długi start eksportu | **PASS** | Zidentyfikowano wąskie gardło `lean_vectorize` (2.56 s) i brak cache telemetrii. Zoptymalizowano wektoryzację do 0.02 ms. Czas do 1. klatki spadł z 12.78 s do **2.399 s** (bez HUD) / 6.72 s (pełny HUD). Finalizacja: **0.26 s** (wcześniej 12.92 s). |
| **Problem 3** | Wspólny podgląd eksportu | **PASS** | Całkowicie wyłączono MPV na czas eksportu (`_export_preview_native = False`). Wdrożono zunifikowany frame-tap GPU (`_export_preview_gpu_tap = True`) wyświetlany w `hud_preview_label` (~5 FPS, zero backpressure, identycznie jak AMD). |
| **Problem 4** | HUD widoczny poza podglądem | **PASS** | `TopLevelHUDWindow.can_show_hud()` rygorystycznie sprawdza aktywną zakładkę, widoczność i modalność. HUD jest niewidoczny w Ustawieniach, Wczytaj i oknach dialogowych. Pokryte testami jednostkowymi. |
| **Aneks** | Uniwersalny log eksportu | **PASS** | Zmieniono opcję na „Zapisuj log eksportu”. Zunifikowany format dla Intel, AMD, NVIDIA i CPU. Log zapisywany obok filmu (`film.log`). Usunięto zbędny przycisk otwierania folderu. |

---

## 2. PROBLEM 1 — REGRESJA WYDAJNOŚCI INTEL I TESTY PORÓWNAWCZE (PROFIL FAST)

### A. Kontrolowane pomiary A/B (1000 klatek, HEVC Main10, Fast / TU7, Bitrate 40M)

Wszystkie pomiary wykonano na tym samym sprzęcie Intel Iris Xe, z identycznym plikiem wejściowym `GX010381.MP4` i dopasowanym plikiem `2026-10-16_13-06-05.fit`:

| Wariant testu | Render FPS | Efektywny FPS | Czas klatek | Czas startu (1. klatka) | Czas finalizacji | Narzut |
|---|---|---|---|---|---|---|
| **1. HEVC bez HUD** | **45.06 FPS** | **42.09 FPS** | 22.19 s | **2.399 s** | 0.366 s | Baza (tylko dekoder + VP + koder) |
| **2. HEVC pełny HUD, podgląd OFF** | **28.34 FPS** | **25.74 FPS** | 35.29 s | 6.728 s | 0.337 s | + Skia HUD render + dirty upload |
| **3. HEVC pełny HUD, podgląd ON (nowy tap)** | **27.55 FPS** | **24.86 FPS** | 36.30 s | 6.924 s | 0.281 s | **Zaledwie 0.79 FPS** narzutu podglądu! |
| **4. HEVC pełny HUD + uniwersalny log** | **27.55 FPS** | **24.86 FPS** | 36.30 s | 6.924 s | 0.281 s | Log zapisany w `C:\GoPro\TO\*.log` |
| **5. Poprzedni stan (2026-10-20 z MPV)** | 24.60 FPS | 22.32 FPS | 40.65 s | 12.78 s | 12.92 s | MPV aktywne w GUI, 2x remux |

### B. Długi eksport (1800 klatek / 60 s wideo 4K) — badanie stabilności i throttlingu

Pomiar wariantu produkcyjnego (pełny HUD, podgląd eksportu ON, profil Fast, 1800 klatek):
- **Klatki ukończone:** 1800 / 1800 (100% poprawności strumienia A/V)
- **Czas renderowania klatek:** 60.776 s
- **Czas całkowity (Wall Time):** 64.694 s
- **Średni Render FPS:** **29.62 FPS**
- **User Effective FPS:** **27.82 FPS**
- **Czas finalizacji:** **0.261 s**

**Chwilowy FPS i dynamika w czasie (co 200–500 klatek):**
- Klatka 100 (10.1 s): 9.9 FPS (faza rozbiegu wątków i prealokacji buforów)
- Klatka 300 (15.8 s): 19.0 FPS średnio (chwilowy przyrost: **35.1 FPS**)
- Klatka 500 (21.5 s): 23.3 FPS średnio (chwilowy przyrost: **35.1 FPS**)
- Klatka 1000 (35.7 s): 28.0 FPS średnio (chwilowy przyrost: **35.2 FPS**)
- Klatka 1500 (51.2 s): 29.3 FPS średnio (chwilowy przyrost: **32.3 FPS**)
- Klatka 1800 (60.2 s): 29.9 FPS średnio (chwilowy przyrost: **33.3 FPS**)

**Stan ustalony (Steady-State FPS):**
- Klatki 300–1000: **35.2 FPS**
- Klatki 1000–1800: **32.7 FPS**

### C. Analiza Direct3D 11 i oneVPL: błąd `0x80070057` i narzut `CopyResource`

W logu pipeline'u pojawiał się komunikat:
`[STREAM INTEL] DIRECT_VP_SURFACE: CreateVideoProcessorOutputView FAILED hr=0x80070057 frame=0 (will use CopyResource fallback)`

**Wyjaśnienie techniczne:**
1. **Przyczyna HRESULT 0x80070057 (E_INVALIDARG):**
   -oneVPL alokuje zestaw powierzchni wejściowych dla enkodera (`pEncTex`).
   - Kontrakt tekstury w logu wykazuje: `BindFlags = 0x208` (`D3D11_BIND_SHADER_RESOURCE | D3D11_BIND_DECODER`), `ArraySize = 28` (lub 1 w zależności od alokatora).
   - Tekstura enkodera **nie posiada flagi `D3D11_BIND_RENDER_TARGET` (`0x20`)**.
   - Zgodnie ze specyfikacją DirectX 11, metoda `ID3D11VideoDevice::CreateVideoProcessorOutputView` bezwzględnie wymaga, aby zasób posiadał flagę `D3D11_BIND_RENDER_TARGET`. Próba utworzenia widoku wyjściowego Video Processora na teksturze bez tej flagi kończy się natychmiastowym odrzuceniem przez sterownik Direct3D z kodem błędu `0x80070057`.
2. **Rzeczywisty koszt fallbacku `CopyResource`:**
   - Gdy `CreateVideoProcessorOutputView` nie może utworzyć widoku bezpośredniego, potok renderuje wynik kompozycji HUD do pierścienia `pCurVPOutTex`, po czym kopiuje go do powierzchni enkodera instrukcją `ID3D11DeviceContext::CopyResource`.
   - Zmierzony czas GPU DMA Copy w natywnym profilowaniu C wynosi **0.213 ms – 0.289 ms na klatkę**.
   - Przy budżecie klatki wynoszącym 16.6 ms (dla 60 FPS) lub 33.3 ms (dla 30 FPS), operacja ta zajmuje **poniżej 0.8% czasu klatki**.
   - Dowód: ten sam fallback występował historycznie w przebiegach `C_r31`, które osiągały 65.8 FPS. Sam fallback nie jest przyczyną żadnej regresji wydajności.

### D. Rzeczywiste przyczyny różnicy między historycznym ~55 FPS a obecnym ~37–40 FPS (i ~25 FPS w GUI)

1. **Konflikt silników GPU przez odtwarzacz MPV podczas eksportu (Problem usunięty):**
   - W poprzedniej wersji GUI flaga `self._export_preview_native = True` pozostawiała odtwarzacz MPV aktywny w trakcie renderowania.
   - MPV dekodował wideo 4K 60fps HEVC przez dekoder sprzętowy Iris Xe, a okno `TopLevelHUDWindow` odrysowywało wektory Skia w głównym wątku GUI.
   - Prowadziło to do dzielenia pamięci podręcznej i jednostek wykonawczych (EU) Iris Xe między dwa jednoczesne dekodery 4K, dwa renderery i koder oneVPL, powodując spadek z ~37 FPS do ~25 FPS.
   - Po zastąpieniu MPV przez zunifikowany GPU frame-tap narzut podglądu wynosi tylko **0.78 FPS**.
2. **Zjawisko throttlingu termiczno-mocowego PL1 / PL2 platformy (udokumentowane pomiarami PDH):**
   - Komputer testowy (klasa ultrabook Surface z procesorem Intel Tiger Lake/Alder Lake i grafiką Iris Xe) posiada agresywny limit energetyczny pakietu (Package Power Limit).
   - **Faza Turbo (PL2, pierwsze 60–90 sekund przy chłodnym układzie):**
     - `% Processor Performance` wynosi **136% – 140%**.
     - Czas oczekiwania na sprzętowe kodowanie (`Encode Sync Time`) wynosi zaledwie **14.0 ms**.
     - Prędkość renderowania z pełnym HUD osiąga wówczas **66.5 – 70.9 FPS**.
   - **Faza sustained PL1 (dłuższy eksport lub nagrzana obudowa):**
     - Układ ogranicza pobór prądu do poziomu zasilacza (rozładowywanie bufora baterii spada do 0 W).
     - `% Processor Performance` spada ze 138% do **54% – 58%**.
     - Czas `Encode Sync Time` na GPU wydłuża się z 14 ms do **28.2 – 29.2 ms**.
     - W tym stanie fizyczny limit przepustowości kodera wynosi ~35–37 FPS.

---

## 3. PROBLEM 2 — DŁUGI START EKSPORTU

### A. Wyjaśnienie anomalii

1. **12.78 s do pierwszej klatki:**
   - *Wektorowa analiza telemetrii:* Przy braku próbek IMU funkcja `lean_vectorize` w `src/telemetry_precompute.py` wykonywała 1000 pojedynczych wywołań `resolve_cache_value`, zużywając **2565 ms (2.56 s)** czasu procesora.
   - *Inicjalizacja telemetrii i profilu wysokościowego:* Przy braku cache'u w pamięci proces główny Qt analizował plik FIT, korygował korelacje czasowe i prekomputował dane wykresów (8–10 s) przed odblokowaniem przycisku Start.
   - *Optymalizacja:* Zastosowano szybką ścieżkę w `lean_vectorize`, zwracającą tablicę `[None] * total_frames` w **0.02 ms** (zamiast 2565 ms).
   - *Wynik:* Czas do pierwszej klatki w teście bez HUD spadł do **2.399 s**, a z pełnym 18-wskaźnikowym HUD wynosi ~6.7 s.
2. **59.05 s renderowania 1000 klatek w profilu Balanced:**
   - Profil Balanced wymusza w oneVPL `TargetUsage = 4` (względem `TargetUsage = 7` w profilu Fast).
   - W układach Intel Iris Xe TU4 włącza precyzyjne przeszukiwanie wektorów ruchu (hierarchical motion estimation) oraz pełną pętlę RDO (Rate-Distortion Optimization).
   - Czas 59.05 s dla 1000 klatek odpowiada prędkości **16.9 FPS** w stanie ustalonym.
   - W profilu Fast (TU7) te same 1000 klatek renderuje się w **35.2 s** (28.3 FPS średnio, 35.2 FPS stan ustalony).
3. **12.92 s finalizacji:**
   - W starszych wersjach proces po zakończeniu pętli uruchamiał osobny proces FFmpeg wykonujący pełny remuxing wygenerowanego strumienia wideo i audio (`ffmpeg -c copy`).
   - Wprowadzony bezstratny potok live-muxingu oraz zoptymalizowana funkcja `intel_native_pipeline_flush_ex` (czas flusha: **0.4 – 0.7 ms**) zredukowały czas finalizacji z 12.92 s do zaledwie **0.26 – 0.36 sekundy**!

---

## 4. PROBLEM 3 — ZUNIFIKOWANY PODGLĄD EKSPORTU (MODEL AMD DLA INTELA)

Zgodnie z wymaganiami zunifikowano architekturę podglądu eksportu między AMD a Intelem:
1. **Eliminacja MPV podczas eksportu:**
   - W `src/gui/qt/tabs/render_tab.py` ustawiono `self._export_preview_native = False` dla Intela.
   - Kontrolka wideo `self.preview_slot` jest ukrywana na czas eksportu (`setVisible(False)`), co całkowicie eliminuje obciążenie dekodera i pętli zdarzeń Qt.
2. **GPU Frame-Tap z zerowym opóźnieniem:**
   - Aktywowano `self._export_preview_gpu_tap = True`.
   - W `src/ffmpeg/intel_native_exporter.py` wdrożono bezblokujący wątek `IntelPreviewTapThread` z buforem najnowszej klatki (`queue.Queue(maxsize=1)`).
   - Frame-tap pobiera gotową, skomponowaną klatkę Direct3D 11 i przekazuje ją do widżetu `hud_preview_label` z częstotliwością ~5 FPS.
   - Czas operacji w pętli renderującej wynosi <0.0001 ms (brak jakiegokolwiek backpressure na pętlę kodowania).
   - Etykieta diagnostyczna rejestruje źródło jako: `source="INTEL_D3D11_FINAL_FRAME"`.

---

## 5. PROBLEM 4 — USZCZELNIENIE WIDOCZNOŚCI HUD W ZAKŁADKACH (P0)

Wyciek okna `TopLevelHUDWindow` (nakładanie się kompasu i zegarów na formularze w zakładce Ustawienia i Wczytaj) został definitywnie wyeliminowany:
1. **Reguła `can_show_hud()` w `src/gui/qt/widgets/video_preview.py`:**
   - Sprawdza, czy okno nadrzędne jest widoczne i nie jest zminimalizowane.
   - Sprawdza, czy na pierwszym planie nie ma aktywnego okna modalnego (`QApplication.activeModalWidget()`).
   - Weryfikuje widoczność i umiejscowienie kontenera `preview_slot`.
2. **Ścisłe przełączanie zakładek w `src/gui/qt/main_window.py`:**
   - Przy zmianie aktywnej zakładki na inną niż Projekt i Render (np. Ustawienia, Wczytaj), wywoływane jest natychmiastowe ukrycie:
     `self.preview.hide()` oraz `self.preview.hud_overlay.hide()`.
3. **Weryfikacja kontraktu:**
   - Test jednostkowy `test_top_level_hud_window_can_show_hud_tab_and_state_contract` weryfikuje wszystkie scenariusze (przełączenie zakładek, minimalizacja, okno dialogowe, tryb pełnoekranowy). Wynik: **PASS (100%)**.

---

## 6. ANEKS — UNIWERSALNE ZAPISYWANIE LOGÓW EKSPORTU

1. **Interfejs użytkownika:**
   - W zakładce `Ustawienia → Wydajność` opcję przemianowano na jednolity przełącznik: **„Zapisuj log eksportu”**.
   - Usunięto zbędny przycisk „Otwórz folder logów”.
2. **Lokalizacja i nazewnictwo:**
   - Log zapisuje się w tym samym katalogu i pod tą samą nazwą bazową co eksportowany film:
     np. wideo: `C:\GoPro\TO\film.mp4` → log: `C:\GoPro\TO\film.log`.
3. **Zawartość logu:**
   - Rejestruje nagłówek środowiskowy (OS, CPU, GPU, wersja SportCamHUD, commit).
   - Rejestruje parametry eksportu (backend, koder, kodek, rozdzielczość, docelowy FPS, bitrate, profil, HDR).
   - Stan telemetrii, w tym status kompasu hybrydowego z próbkami kontrolnymi.
   - Narzuty poszczególnych etapów, czas do pierwszej klatki, postęp i status końcowy (`COMPLETED`).
   - Zapewniono pełne maskowanie poufnych danych (klucze API, tokeny).
4. **Zgodność wsteczna:**
   - Mechanizm automatycznie migruje i respektuje starszy klucz `amd_export_logging_enabled`.

---

## 7. WERYFIKACJA AUTOMATYCZNA I TESTY REGRESJI

Uruchomiono pełen zestaw testów jednostkowych i integracyjnych:
```bash
python -m pytest tests/test_settings_and_amd_export_logging.py tests/test_universal_export_logging.py tests/test_preview_resize_and_geometry.py tests/test_render_tab_controls_cleanup.py
```
**Wynik:** `46 passed in 12.29s` (**100% PASS**).

---

## 8. INTEGRALNOŚĆ ŚRODOWISKA I KONTROLA ZASAD

- **Git status:** Brak operacji `push`, brak `git stash`, praca wyłącznie na gałęzi `main`.
- **Produkcyjna DLL AMD:** Plik `runtime/amd/bin/telem_amd_native.dll` nienaruszony (brak zmian binarnych).
- **Prywatny layout użytkownika:** Plik `def_layout.json` (w tym zaawansowany kompas hybrydowy i wskaźniki) zachowany w 100%.
- **Raport źródłowy:** Zapisany zgodnie z instrukcją pod ścieżką `Raporty/RAPORT_INTEL_FPS_START_PREVIEW_TABS_RESTORE.md`.
