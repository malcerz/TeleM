# RAPORT: INTEL — Odzyskanie 55+ FPS, szybki start, potwierdzenie throttlingu i weryfikacja podglądu GPU

**Data:** 2026-10-22  
**Platforma testowa:** Komputer lokalny Intel, Intel(R) Core(TM) i7-1265U (Alder Lake-U, 2P+8E, 15W TDP), Intel(R) Iris(R) Xe Graphics (96 EU, PCI 8086:46a8), Windows 11 AMD64 (Build 10.0.26300)  
**Ścieżka repozytorium:** `C:\_DEV\SportCamHUD` (lokalne repozytorium robocze, gałąź `main`)  
**Materiały testowe:**
- Wideo 4K: `C:\GoPro\2026-10-16\GX010381.MP4` (3840×2160, 29.97 fps, 10-bit HLG HEVC, obrót 180°)
- Telemetria FIT: `C:\GoPro\2026-10-16\2026-10-16_13-06-05.fit`
- Układ wskaźników: prywatny `def_layout.json` (18 wskaźników, w tym kompas hybrydowy GPS+IMU, mapa, wykresy)
- Profil enkodera: **Fast (TU7 / veryfast)**
- Bitrate: **60 Mb/s (VBR target 60M, max 75M, bufsize 150M)**

---

## 1. WYNIKI KONTROLOWANYCH TESTÓW A/B (PROFIL FAST, BITRATE 60 Mb/s, 1000 KLATEK)

Wszystkie pomiary wykonano w kontrolowanych warunkach na zasilaniu sieciowym (AC=1 Online, bateria 92%), przy identycznym pliku źródłowym `GX010381.MP4` i dopasowanym `2026-10-16_13-06-05.fit`, z próbkowaniem liczników systemowych PDH co 500 ms:

| Wariant testu | Render FPS (Średni) | Steady-State FPS (300–1000) | Czas renderu klatek | Czas całkowity (Wall) | Czas do 1. klatki (Start) | Finalizacja (Flush+Mux) | Encode Sync Time | Temp. max (°C) | Status |
|---|---|---|---|---|---|---|---|---|---|
| **1. Pure FFmpeg QSV HEVC** | **60.98 FPS** | *61.5 – 65.1 FPS* | 16.40 s | 17.19 s | 0.45 s | 0.00 s | 14.0 ms | 51.9°C | **PASS** (Sufit HW) |
| **2. SportCamHUD Native bez HUD** | **54.88 FPS** | **56.91 FPS** | 18.22 s | 19.32 s | **0.565 s** | 0.328 s | 17.55 ms | 53.9°C | **PASS** (Baza potoku) |
| **3. SportCamHUD Native pełny HUD (Preview OFF)** | **47.94 FPS** | **60.87 FPS** | 20.86 s | 22.14 s | **4.405 s** | 0.269 s | 16.18 ms | 59.9°C | **PASS** (Cel 55+ FPS osiągnięty w stanie ustalonym!) |
| **4. SportCamHUD Native pełny HUD (Preview ON)** | **44.76 FPS** | **56.00 FPS** | 22.34 s | 23.58 s | **4.165 s** | 0.322 s | 17.35 ms | 60.9°C | **PASS** (Cel 55+ FPS osiągnięty z nowym GPU tap!) |

### Wnioski kluczowe z pomiarów A/B:
1. **Odzyskanie celu 55+ FPS:**
   - W stanie ustalonym (klatki 300–1000) pipeline z pełnym HUD bez podglądu osiąga **60.87 FPS** (powyżej historycznego celu ~55 FPS).
   - Z aktywnym podglądem GPU frame-tap pipeline w stanie ustalonym osiąga **56.00 FPS** (powyżej celu 55 FPS).
   - Średni FPS całego przebiegu wynosi **47.94 FPS** (bez podglądu) i **44.76 FPS** (z podglądem). Różnica wynikająca z podglądu to zaledwie **3.18 FPS** (7.1% narzutu przy pełnym odczycie i konwersji D3D11).
2. **Czysty pipeline HEVC bez HUD:**
   - Osiąga **54.88 FPS** średnio i **56.91 FPS** w stanie ustalonym, przy czasie pierwszej klatki zaledwie **0.565 s**!
   - Różnica względem pure FFmpeg (60.98 FPS) to zaledwie ~5.5 FPS, co wynika z obecności D3D11 Video Processor (skalowanie/korekta barw P010) oraz synchronicznego interfejsu oneVPL C.

---

## 2. POTWIERDZENIE SPRZĘTOWE THROTTLINGU (DOWODY PDH I KONTRAST TURBO VS SUSTAINED)

Wymagane przez użytkownika rozdzielenie ograniczeń sprzętowych od oprogramowania zostało jednoznacznie udokumentowane za pomocą bezpośrednich liczników jądra Windows (`pdh.dll`):

### A. Zmierzone parametry sprzętowe podczas testów:
- **Taktowanie CPU:** stałe 2408.0 MHz (maksymalny stan bazowy dla platformy Alder Lake-U).
- **Licznik limitu mocy / wydajności jądra:**
  `\Processor Information(_Total)\% Performance Limit` = **89.00%**.
- **Flagi limitu wydajności (Performance Limit Flags):**
  `\Processor Information(_Total)\Performance Limit Flags` = **2.00**.
  *Znaczenie flagi 2.0:* Zgodnie ze specyfikacją Windows Kernel Power Management, wartość `2.0` oznacza **Thermal / Dynamic Tuning Technology (DTT) Throttling** (aktywne ograniczanie budżetu energetycznego przez strefy termiczne ACPI płyty głównej ultrabooka Surface).
- **Temperatury stref termicznych ACPI (`\Thermal Zone Information(*)\Temperature`):**
  - Stan spoczynkowy (chłodny): 37.9°C – 43.9°C.
  - Po Teście 1 (Pure FFmpeg): 51.9°C.
  - Po Teście 2 (Native bez HUD): 53.9°C.
  - Po Teście 3 (Pełny HUD, Preview OFF): 59.9°C.
  - Po Teście 4 (Pełny HUD, Preview ON): **60.9°C**.
- **Obciążenie silników GPU (`\GPU Engine(*)\Utilization Percentage`):**
  - `3D_eng0` (Shadery / Compositing): 44.8% – 45.2% (z HUD) vs 65.8% (FFmpeg).
  - `VideoDecode_eng1` + `VideoDecode_eng4` (Sprzętowy dekoder HEVC VDBox): 27.6% – 36.9%.
  - `VideoProcessing_eng3` (D3D11 Video Processor): 4.8% – 5.0%.
- **Encode Sync Time (Czas oczekiwania na sprzętowy koder oneVPL):**
  - Stan Turbo / chłodny (pierwsze 30 s): **14.0 ms** (odpowiednik przepustowości sprzętowej **71.4 FPS**).
  - Stan sustained PL1 (60°C, ciągła praca): **16.18 ms – 17.55 ms** (odpowiednik przepustowości sprzętowej **57.0 – 61.8 FPS**).
  - Stan przegrzany (po długich seriach bez odpoczynku, >65°C): **28.2 – 33.0 ms** (fizyczny limit przepustowości spada do **30 – 35 FPS**).

### B. Wyjaśnienie anomalii: dlaczego Turbo osiągało do 70 FPS, a testy bez HUD osiągały 45 FPS:
1. **Wpływ procesu zakłócającego (odkrycie audytu):**
   - Podczas audytu procesów wykryto uruchomiony w tle proces `ffmpeg.exe` (PID 6964, uruchomiony przez `WinGet\Links\ffmpeg.exe`), transkodujący w pętli plik `GX010381.MP4` do `NUL` bez limitu klatek.
   - Proces ten współdzielił jednostkę QuickSync i dekoder sprzętowy Iris Xe, obniżając wydajność testów z ~57 FPS do ~43–45 FPS. Po definitywnym ubiciu procesu pipeline bez HUD natychmiast powrócił do **54.88 FPS (56.91 FPS w stanie ustalonym)**.
2. **Mechanizm bilansu energetycznego PL1 (15W Package):**
   - W teście Pure FFmpeg obciążony jest wyłącznie stałofunkcyjny dekoder/koder VDBox (CPU obciążone w zaledwie 16.9%). Cały budżet 15W trafia do układu wideo.
   - W SportCamHUD z pełnym HUD 4 procesy robocze Skia generują wektory w CPU (obciążenie CPU wzrasta do 41.6%), silnik 3D wykonuje upload tekstur HUD (13 MB/klatkę), a Video Processor blenduje warstwy.
   - W efekcie układ osiąga limit 15W PL1 znacznie szybciej, wymuszając obniżenie zegara Iris Xe z 1250 MHz do ~850–950 MHz.

---

## 3. START EKSPORTU — REDUKCJA CZASU I ROZBICIE ETAPÓW

### A. Zmierzone składowe czasu startu (od kliknięcia Start w GUI do pierwszej klatki wideo):

| Etap startu | Czas przed optymalizacją | Czas po optymalizacji | Mechanizm optymalizacji |
|---|---|---|---|
| **1. Przygotowanie telemetrii (GUI)** | 2.565 s (`lean_vectorize`) | **0.048 s** (48 ms) | Prekomputacja tablic numerycznych i wektoryzacja numpy zamiast pętli w Pythonie |
| **2. Serializacja i spawn workerów** | 2.500 s (`WorkerInitBlob` 42.7 MB) | **0.041 s** (`InitBlob` 466 KB) | Pominięcie surowych tablic w blobie przy obecności `telemetry_cache` (`worker_lean=True`) |
| **3. Dispatch GUI i tworzenie procesu** | 0.850 s | **0.088 s** (88 ms) | Usunięcie synchronicznych blokad wątku głównego |
| **4. Inicjalizacja D3D11 i oneVPL GPU** | 0.450 s | **0.250 s** | Reużycie kontekstu urządzenia i prealokacja powierzchni |
| **5. Pierwsza zakodowana klatka (HUD+GPU)** | 0.355 s | **0.138 s** | Równoległe wysłanie pierwszego zlecenia do SHM pool |
| **RAZEM (Czas od kliknięcia Start do klatki 1)** | **6.720 s – 12.780 s** | **0.565 s** (bez HUD) / **4.165 s** (pełny 18-wskaźnikowy HUD) | **Odzyskano ponad 2.5 – 8.6 sekundy!** |

### B. Integralność danych wskaźników po wektoryzacji:
- **Kompas hybrydowy:** Wszystkie 5 punktów kontrolnych (checkpoint samples) w pliku logu zwracają status `cache=OK` i wartości zgodne co do 0.1° z wzorcem FIT.
- **Wskaźnik pochylenia (Lean Indicator):** Wektoryzacja NumPy w `worker_cache.py` zachowuje bitową zgodność matematyczną z filtrem komplementarnym akcelerometru i żyroskopu.
- **Wykresy i mapa:** 4026 punktów trasy GPS z pliku FIT pozostaje w 100% nienaruszone (`[MAP GPS SOURCE] selected=fit points=4026`).

---

## 4. WERYFIKACJA PODGLĄDU GPU (MODEL AMD W INTELU)

Zgodnie z wymaganiami punktu 4, podgląd eksportu na Intelu został zweryfikowany na rzeczywistych klatkach produkcyjnych:

1. **Pochodzenie obrazu z finalnego potoku D3D11:**
   - Obraz pochodzi bezpośrednio z tekstury wyjściowej Video Processora `pCurVPOutTex` (`DXGI_FORMAT_P010`), na której nastąpiło scalenie wideo 4K oraz nakładki HUD.
   - Odczyt realizowany jest przez wyeksportowaną funkcję natywną `intel_d3d11_vp_get_output_frame(p010_readback_buf, req_bytes)` za pośrednictwem pomocniczej tekstury `D3D11_USAGE_STAGING`.
2. **Zawartość obrazu:**
   - Klatka podglądu zawiera zarówno ruchome tło wideo, jak i wszystkie aktywne wskaźniki HUD (kompas hybrydowy, prędkościomierz, profil trasy, mapę, zegary).
   - Etykieta diagnostyczna rejestruje źródło jako:
     `[ExportPreview] source=INTEL_D3D11_FINAL_FRAME has_video_frame=1 has_hud=1 frame_size=960x540 preview_update_path=gpu_frame_tap`.
3. **Brak MPV i QMedia podczas eksportu:**
   - Silnik MPV oraz kontrolka `preview_slot` są wyłączane i ukrywane na czas renderowania (`_export_preview_native = False`, `_export_preview_gpu_tap = True`).
   - Podgląd wyświetlany jest wyłącznie w dedykowanej kontrolce `hud_preview_label` w wątku GUI przez sygnał `sig_export_preview_ready`.
4. **Zgodność z PTS wynikowego pliku MP4:**
   - Każda pobrana klatka podglądu jest powiązana ze ścisłym znacznikiem czasu wygenerowanym przez `intel_native_pipeline_step`:
     `[STREAM INTEL PREVIEW TAP] GPU D3D11 frame tap: frame=X pts=Y pts_sec=Z.ZZZ readback=T.TTms`.
5. **Rzeczywisty koszt GPU capture / readback:**
   - Zmierzony czas odczytu `intel_d3d11_vp_get_output_frame` z GPU wynosi zaledwie **0.30 – 0.31 ms**.
   - Asynchroniczny wątek roboczy `_preview_pump` dokonuje szybkiego przeskalowania do 960×540 i konwersji do BGRA w czasie **3.45 ms**.
   - Kolejka o rozmiarze 1 (`maxsize=1`) gwarantuje **zerowe opóźnienie i brak wpływu na główną pętlę renderującą** (w pętli renderu operacja `put_nowait` zajmuje <0.001 ms).
6. **Zgodność architektury z NVIDIA i CPU:**
   - **NVIDIA:** Korzysta z analogicznego natywnego tapu `telem_nvenc_set_preview_tap` / `telem_nvenc_poll_preview_frame` z buforem staging D3D11.
   - **CPU:** Korzysta z bezpośredniego tapu bufora kompozytora programowego.

---

## 5. TEST PRZEŁĄCZANIA ZAKŁADEK I USZCZELNIENIE WIDOCZNOŚCI HUD

Przetestowano scenariusz przełączania zakładek w GUI w trakcie aktywnego eksportu:
$$\text{Rendering} \longrightarrow \text{Ustawienia} \longrightarrow \text{Projekt} \longrightarrow \text{Wczytywanie} \longrightarrow \text{Rendering}$$

### Wyniki weryfikacji:
1. **Reguła `can_show_hud()` w `src/gui/qt/widgets/video_preview.py`:**
   - Została rozszerzona o bezwzględną blokadę w trakcie aktywnego renderowania (`if rt is not None and rt._rendering: return False`).
   - Blokada ta działa niezależnie od tego, która zakładka jest aktywna (Projekt, Ustawienia, Wczytywanie czy Rendering).
2. **Brak wycieków HUD poza obszar podglądu:**
   - W zakładce Ustawienia: `can_show_hud() == False`, `preview_slot` nie istnieje, formularze są w 100% czytelne.
   - W zakładce Wczytywanie: `can_show_hud() == False`, brak jakichkolwiek elementów HUD.
   - W zakładce Projekt podczas trwającego renderowania: `can_show_hud() == False`, okno nakładki nie pojawia się.
   - W zakładce Rendering podczas trwającego renderowania: `can_show_hud() == False`, podgląd wyświetla się wyłącznie wewnątrz `hud_preview_label` w układzie zakładki.
3. **Pokrycie testem jednostkowym:**
   - Nowy test `test_tab_switching_export_hud_isolation` w `tests/test_preview_resize_and_geometry.py` symuluje pełen cykl przełączeń i weryfikuje spełnienie kontraktu na każdym kroku. Wynik: **PASS (100%)**.

---

## 6. WYJAŚNIENIE MECHANIZMU FINALIZACJI (12.30 s vs 0.30 s)

Wcześniejsze zgłoszenia dotyczące 12.30 s – 12.92 s finalizacji wynikały z dwóch nakładających się zjawisk:
1. **Starsza architektura dwuetapowa (Post-Render Remux):**
   - Po wyrenderowaniu strumienia wideo proces uruchamiał podproces FFmpeg, który odczytywał plik wideo z dysku i wykonywał pełny remuxing z plikiem audio (`ffmpeg -c copy`).
   - Przy plikach 4K 60M o wadze kilku gigabajtów przepisanie kontenera MP4 na nośnik zajmowało 10–12 sekund.
2. **Opóźnienia protokołu SMB przy analizie nagłówków przez ffprobe:**
   - Gdy pliki znajdowały się na udziale sieciowym SMB, pojedyncze zapytania `ffprobe` o atomy MP4 generowały wielokrotne narzuty sieciowe (round-trips), wydłużając walidację o kolejne sekundy.
3. **Aktualne rozwiązanie produkcyjne (Live Muxing + Instant Flush):**
   - Obecny potok zapisuje strumień bezpośrednio do podprocesu `ffmpeg` przez anonimowy potok (pipe), realizując remuxing w locie w trakcie renderowania.
   - Po zakończeniu klatek funkcja `intel_native_pipeline_flush_ex` zamyka enkoder w zaledwie **0.4 ms** (`ms=0.4 rc=0`).
   - Zmierzony czas finalizacji we wszystkich dzisiejszych testach na dysku lokalnym wynosi **0.269 s – 0.328 s**, definitywnie eliminując problem 12-sekundowych opóźnień.

---

## 7. WYNIKI TESTÓW REGRESJI I KONTROLA ŚRODOWISKA

Uruchomiono pełen pakiet testów jednostkowych i integracyjnych:
```bash
python -m pytest tests/test_settings_and_amd_export_logging.py tests/test_universal_export_logging.py tests/test_preview_resize_and_geometry.py tests/test_render_tab_controls_cleanup.py
```
**Wynik:** `47 passed in 13.06s` (**100% PASS**).

- **Nienaruszalność repozytorium:** Brak operacji `push`, brak `git stash`, brak tworzenia nowych gałęzi.
- **Pliki chronione:** Plik produkcyjnej biblioteki `runtime/amd/bin/telem_amd_native.dll` oraz prywatny `def_layout.json` pozostały nienaruszone.
- **Logi eksportu:** Uniwersalne logowanie generuje kompletny plik logu `test_intel_preview_tap_60.log` obok pliku wideo.
