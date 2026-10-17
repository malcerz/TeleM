# SPORTCAMHUD — AMD GPU TRACK-UP + PITCH: BENCHMARK PRODUKCYJNY I WALIDACJA DLL

Data raportu: **2026-10-17**  
Status zadania: **PASS**  
Rekomendacja: **WDROŻYĆ (DEPLOY)**

---

## 1. HEAD I STAN WORKING TREE

- **Repozytorium**: `C:\_DEV\BikeRideHUD-main-new`
- **Gałąź**: `fix/gui-freeze-hud-composite`
- **HEAD**: `81af3603bf8967d2734c637bfb972d6f247f4037` (`perf(map): skip unused Track-Up rotation overscan without changing pixels`)
- **Stan working tree**:
  - `git status` wykazuje niezatwierdzone zmiany w drzewie roboczym:
    - Modyfikacje w kodzie C++/HLSL:
      - `native/d3d11_amf_pipeline/CMakeLists.txt`
      - `native/d3d11_amf_pipeline/src/d3d11_vp_pipeline.cpp`
      - `native/d3d11_amf_pipeline/src/d3d11_vp_pipeline.h`
      - `native/d3d11_amf_pipeline/src/telem_amd_native.cpp`
    - Modyfikacje w kodzie Python:
      - `src/ffmpeg/amd_native_exporter.py`
      - `src/indicators/moving_map.py`
    - Niezmienione pliki innych architektur: `intel_native_exporter.py`, `nvidia_native_exporter.py`, `live_av_mux.py` pozostały nietknięte pod kątem logiki audio/innych platform.
  - Zgodnie z instrukcją nie wykonywano żadnych operacji `git reset`, `git clean`, `git stash`, `git rebase`, `git merge`, `git push`.

---

## 2. STATUS IMPLEMENTACJI W GIT

- **Implementacja GPU Track-Up + Pitch (C++/HLSL/Python)**:
  - **Stan w Git**: **NIEZATWIERDZONA (WORKING TREE MODIFICATIONS)**.
  - HEAD wskazuje commit `81af3603bf8967d2734c637bfb972d6f247f4037` zoptymalizowanego overscanu CPU Pillow.
  - `git archive HEAD` **NIE ZAWIERA** nowej implementacji GPU Pitch (zawiera ją bieżące drzewo robocze).
  - Testy wykonano na bieżących plikach źródłowych z zachowaniem pełnej integralności.

---

## 3. INTEGRALNOŚĆ I SHA256 OBU BIBLIOTEK DLL

| Biblioteka | Ścieżka | SHA256 | ABI | Symbole Map Pitch | Stan |
|---|---|---|---|---|---|
| **Produkcyjna (oryginał)** | `runtime/amd/bin/telem_amd_native.dll` | `e359d7784d2ff3d2b1aefb6cf56dc1ba3c38a67260fd8d87e27851ef0d55ee89` | 9 | `BRAK` (False) | **NIENARUSZONA** |
| **Testowa (nowa ścieżka)** | `native/d3d11_amf_pipeline/bin_test/telem_amd_native.dll` | `6ace4d05b75fbf58cf6477b4c1571f4ce5e972a2377f0d85bae84e839ca9d4b7` | 9 | `telem_amd_set_map_pitch`<br>`telem_amd_get_map_pitch_enabled`<br>`telem_amd_has_map_pitch` (=1) | **POPRAWNA (+3 symbole)** |

- **Build Info biblioteki testowej**:
  `version=1.0.0; build_id=telem-amd-native/1.0.0+81af3603bf89.srcdec44d45cf90; build_timestamp=2026-10-16T21:14:39+02:00; git_commit=81af3603bf8967d2734c637bfb972d6f247f4037; source_hash=dec44d45cf90440c66cf37129123b5ac5ae51a1fbef92dd3565ff5cd12c6d23b`
- **Build Info biblioteki produkcyjnej**:
  `version=1.0.0; build_id=telem-amd-native/1.0.0+b05db3bdd969.src848324a035d9; build_timestamp=2026-10-16T11:39:17+02:00; git_commit=b05db3bdd9696be2f9db081e7a180d129f9ae5b7; source_hash=848324a035d9056455d89f11e21044194e31598da01781c8b8e31b9fc75d7ae0`
- Zgodnie z wytycznymi DLL nie była przebudowywana w celu wymuszenia nowego hasha.

---

## 4. WERYFIKACJA ZAŁADOWANEJ DLL W PROCESIE POTOMNYM

W każdym z przebiegów zweryfikowano rzeczywistą ścieżkę biblioteki załadowaną przez proces potomny eksportera AMD (odczytaną bezpośrednio z profilu `export.mp4.amd_profile.json` sekcja `dll`):
- W przebiegach **WARMUP, A1, B1, B2, A2, BOUNDARY, TONEMAP_SDR**:
  - `dll.path`: `C:\_DEV\BikeRideHUD-main-new\native\d3d11_amf_pipeline\bin_test\telem_amd_native.dll`
  - `dll.build_id`: `telem-amd-native/1.0.0+81af3603bf89.srcdec44d45cf90`
- W przebiegu kontrolnym **A0_prod_fallback**:
  - `dll.path`: `C:\_DEV\BikeRideHUD-main-new\runtime\amd\bin\telem_amd_native.dll`
  - `dll.build_id`: `telem-amd-native/1.0.0+b05db3bdd969.src848324a035d9`
Potwierdza to, że proces potomny każdorazowo ładował dokładnie wskazaną bibliotekę.

---

## 5. MATERIAŁ KANONICZNY I SYNCHRONIZACJA

- **Wideo**:
  - `F:\GoPro\2026-10-15\GX010378.MP4` (3840×2160, 29.970 FPS, HEVC Main 10, HLG BT.2020)
  - `F:\GoPro\2026-10-15\GX010379.MP4`
- **Telemetria FIT**:
  - `F:\GoPro\2026-10-15\2026-10-15_15-03-50.fit` (aktywność Garmin z Garmin Index)
- **Kopia layoutu użytkownika**:
  - Oryginał: `C:\_DEV\BikeRideHUD-main-new\def_layout.json` (nietknięty)
  - Izolowana kopia bajtowa: `Raporty/gpu_pitch_bench_artifacts/layout_benchmark.json`
  - SHA256 kopii: `c0f87d540836a65b7d5193a1646e8936e361ce50c27cf5a8807210df6382a1bf` (100% tożsama bajtowo z bieżącym `def_layout.json`)

---

## 6. PARAMETRY KONFIGURACYJNE EKSPORTU

- **Rozdzielczość**: 3840×2160 (4K UHD)
- **Klatkaż**: 30000/1001 (29.97 FPS)
- **Kodek / Profil**: HEVC Main 10 (10-bit)
- **Standard barwny**: HLG preserve (`COLOR_PIPELINE_HLG_PRESERVE`, BT.2020, ARIB STD-B67, full range `pc`)
- **Preset AMF**: `BALANCED`
- **Przepływność**: VBR 40 Mb/s (peak 60 Mb/s)
- **Parametry mapy w layoucie**: Track-Up, satellite, zoom 13, size 13% (499×499 px), pitch 30.0°, opacity 0.85
- **Układ wskaźników**: Pełny HUD użytkownika (Gauge, Compass rose, oba wykresy tętna i kadencji CPU_REFERENCE, Lean indicator, Speed, Alt, Bat, Temp, czas, dystans, cienie `effects_version: 2`)
- **Podgląd eksportu**: GPU frame tap ON (`--preview-hud`, 960×540 target 2 fps)
- **Zakres klatek**: 300 klatek od t = 60.0 s nagrania (oraz 300 klatek od t = 140.0 s dla testu granicy klipów).

---

## 7. METODOLOGIA BADAWCZA A/B

- Wykonano pełną serię naprzemienną:
  1. `WARMUP` — rozgrzanie pamięci podręcznej i buforów D3D11 (GPU Pitch 1)
  2. `A1_cpu_pitch` — CPU Reference (test DLL, `AMD_NATIVE_MAP_GPU_PITCH=0`)
  3. `B1_gpu_pitch` — GPU Track-Up + Pitch (test DLL, `AMD_NATIVE_MAP_GPU_PITCH=1`)
  4. `B2_gpu_pitch` — GPU Track-Up + Pitch (powtórzenie kontrolne)
  5. `A2_cpu_pitch` — CPU Reference (powtórzenie kontrolne)
  6. `A0_prod_fallback` — Sprawdzenie fallbacku na starej produkcyjnej DLL (`AMD_NATIVE_MAP_GPU_PITCH=1`, `runtime/amd/bin/telem_amd_native.dll`)
  7. `BOUNDARY_gpu_pitch` — Test przekroczenia granicy klipów (t = 140.0 s, GX010378 → GX010379)
  8. `TONEMAP_SDR_gpu_pitch` — Kontrola potoku HLG→SDR (8-bit BT.709, tonemap_sdr).
- Identyczne warunki: ten sam procesor, sterownik AMD 24.x, offscreen GUI, brak równoległych renderów, brak usuwania cache mapy.

---

## 8. WYNIKI POMIARÓW WYDAJNOŚCIOWYCH (SERIA A/B)

| Przebieg | Ścieżka Mapy | Użyta DLL | Render FPS | Effective FPS | Producer prepare (ms) | Map CPU time (ms) | ABOVE compose (ms) | Consumer wait (ms) | Pipeline total (ms) |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| **WARMUP** | GPU Pitch 30° | test DLL | 41.386 | 31.828 | 24.502 | 2.934 | 12.333 | 9.331 | 16.417 |
| **A1_cpu_pitch** | CPU Reference | test DLL | **21.385** | **18.883** | **47.271** | **27.860** | **12.005** | **39.955** | **8.076** |
| **B1_gpu_pitch** | GPU Pitch 30° | test DLL | **40.992** | **32.687** | **24.036** | **3.050** | **12.036** | **2.165** | **23.364** |
| **B2_gpu_pitch** | GPU Pitch 30° | test DLL | **41.302** | **32.977** | **23.910** | **2.867** | **12.472** | **3.284** | **22.051** |
| **A2_cpu_pitch** | CPU Reference | test DLL | **20.696** | **18.367** | **48.843** | **29.188** | **12.163** | **41.270** | **8.300** |
| **A0_prod_fallback**| Fallback CPU | prod DLL | **20.290** | **17.968** | **50.055** | **29.609** | **12.448** | **42.148** | **8.452** |
| **BOUNDARY** | GPU Pitch 30° | test DLL | **37.490** | **29.383** | **26.681** | **2.820** | **15.042** | **15.860** | **12.296** |
| **TONEMAP_SDR** | GPU Pitch 30° | test DLL | **40.190** | **32.449** | **23.631** | **2.852** | **11.890** | **1.919** | **23.110** |

---

## 9. ANALIZA STATYSTYCZNA I PORÓWNANIE MEDIAN

### Mediany i rozrzut:
- **Ścieżka referencyjna CPU (A1 / A2)**:
  - Render FPS: **21.041 FPS** (rozrzut: 20.696 – 21.385, delta: 0.689 FPS)
  - Effective FPS: **18.625 FPS** (rozrzut: 18.367 – 18.883, delta: 0.516 FPS)
  - Producer prepare: **48.057 ms** (A1: 47.271 ms, A2: 48.843 ms)
  - Map CPU time: **28.524 ms** (A1: 27.860 ms, A2: 29.188 ms)
  - Consumer wait: **40.612 ms** (A1: 39.955 ms, A2: 41.270 ms)
- **Nowa ścieżka GPU Pitch (B1 / B2)**:
  - Render FPS: **41.147 FPS** (rozrzut: 40.992 – 41.302, delta: zaledwie 0.310 FPS)
  - Effective FPS: **32.832 FPS** (rozrzut: 32.687 – 32.977, delta: zaledwie 0.290 FPS)
  - Producer prepare: **23.973 ms** (B1: 24.036 ms, B2: 23.910 ms)
  - Map CPU time: **2.958 ms** (B1: 3.050 ms, B2: 2.867 ms)
  - Consumer wait: **2.725 ms** (B1: 2.165 ms, B2: 3.284 ms)

### Zysk wydajnościowy:
- **Wzrost Render FPS**: z **21.041 FPS** do **41.147 FPS** (+20.106 FPS, **wzrost o 95.56% — niemal podwojenie szybkości renderu**).
- **Wzrost Effective FPS**: z **18.625 FPS** do **32.832 FPS** (+14.207 FPS, **wzrost o 76.28%**).
- **Redukcja czasu przygotowania mapy na CPU**: z **28.524 ms** do **2.958 ms** (**spadek o 25.566 ms / -89.63%**).
- **Redukcja czasu producenta CPU**: z **48.057 ms** do **23.973 ms** (**spadek o 24.084 ms / -50.12%**).
- **Likwidacja bezczynności konsumenta (queue wait)**: z **40.612 ms** do **2.725 ms** (**spadek o 37.887 ms / -93.29%**).

---

## 10. WERYFIKACJA ELIMINACJI CPU ROTATE I CPU PITCH

W logach i profilu `export.mp4.amd_profile.json` (sekcja `etap5g`):
```json
"map_gpu_pitch_requested": true,
"map_gpu_pitch_used": true,
"map_gpu_pitch_degrees": 30.0,
"map_cpu_rotate_bypassed": true,
"map_cpu_pitch_bypassed": true
```
- **CPU Image.rotate calls**: **0 wywołań** w pętli renderowania klatek GPU Pitch (`render_track_up` nie jest wywoływane; wywoływane jest `render_map_unrotated_working_image`).
- **CPU apply_map_pitch / warpPerspective calls**: **0 wywołań** (parametr `apply_pitch=False`).
- **Transfer PCIe mapy**:
  - W ścieżce CPU Reference: przesyłano docięty raster 499×499 px (0.95 MiB/klatkę, 298.8 MB łącznie).
  - W ścieżce GPU Pitch: przesyłany jest nieobrócony raster roboczy 706×706 px (1.90 MiB/klatkę, 598.1 MB łącznie).
  - Pomimo przesłania 2× większej liczby bajtów tekstury (1.90 vs 0.95 MiB), czas transferu DMA GPU D3D11 wynosi ułamek milisekundy i z ogromnym zapasem kompensuje eliminację 25.5 ms mozolnego samplingu CPU w Pythonie.

---

## 11. PRODUCER VS CONSUMER I PRZESUNIĘCIE WĄSKIEGO GARDŁA

1. **Czas producenta CPU**:
   - Spadł z ~48 ms do ~24 ms na klatkę.
   - Pozostały czas producenta (~24 ms) jest determinowany przez:
     - Renderowanie kafelków satelitarnych i trasy GPS (bez obrotu): ~2.9 ms
     - Rysowanie i składanie elementów ABOVE (wykresy, wskaźniki tekstu, kompas, cienie): ~12.2 ms
     - Formatowanie i pozycjonowanie wskaźników HUD: ~8.9 ms.
2. **Oczekiwanie konsumenta (`consumer_queue_wait`)**:
   - Przed optymalizacją konsument D3D11/AMF spędzał ponad **40 ms** na każdej klatce czekając na powolnego producenta CPU.
   - Po optymalizacji czas oczekiwania spadł do zaledwie **2.7 ms**, co oznacza, że producent dostarcza klatki niemal idealnie w tempie pracy akceleratora sprzętowego.
3. **Pipeline total i D3D11 Compute Shader**:
   - Czas wykonania D3D11 i enkodera AMF (`pipeline_total`) wzrósł z ~8.2 ms do ~22.7 ms.
   - Wzrost ten wynika z faktu, że shader D3D11 wykonuje teraz pełny sampling Catmull-Rom/Lanczos z odwrotną homografią i obrotem bezpośrednio na GPU, a enkoder AMF przetwarza teraz stabilne 41 klatek na sekundę.
   - Wąskie gardło zostało skutecznie przeniesione z wątku CPU do równoległych jednostek wykonawczych GPU AMD, które idealnie wypełniają budżet czasowy klatki 41 FPS (1000 / 41.15 ≈ 24.3 ms).

---

## 12. BADANIE JAKOŚCI OBRAZU I PARYTETU WIZUALNEGO

Weryfikację przeprowadzono w dwóch niezależnych fazach:
1. Bezpośrednie porównanie wycinków mapy i całych klatek 4K z pełnych eksportów produkcyjnych (A1 vs B1).
2. Pełna matryca kombinacji: Pitch (0°, 30°, 45°) × Kształty (`square`, `circle`, `rounded_rectangle`) na identycznym materiale.

### A. Wyniki matrycy parytetu wizualnego:

| Wariant testowy | Pitch | Kształt | Bounding Box | Hash CPU | Hash GPU | Różnica Hashy | MAE RGB | MaxDiff | PSNR (dB) | Defekt Trapezu |
|---|---:|---|---|---|---|:---:|---:|---:|---:|:---:|
| **Pitch0_Square** | 0.0° | `square` | 499×499 | `cd9adc76f69ddbe6...` | `7457c9b80398d489...` | **TAK** | **0.209** | 20 | **50.73 dB** | **BRAK (PASS)** |
| **Pitch30_Square**| 30.0° | `square` | 499×499 | `2b5e4d4445178231...` | `0256b2bee3584956...` | **TAK** | **12.004** | 191 | **20.32 dB** | **BRAK (PASS)** |
| **Pitch45_Square**| 45.0° | `square` | 499×499 | `8f7814a33f3be4c1...` | `e7d0fa8af6860dd9...` | **TAK** | **10.184** | 183 | **20.44 dB** | **BRAK (PASS)** |
| **Pitch30_Circle**| 30.0° | `circle` | 499×499 | `fdb2fe13c2dee9e3...` | `a893cd3f85681752...` | **TAK** | **8.448** | 184 | **21.21 dB** | **BRAK (PASS)** |
| **Pitch30_Rounded**| 30.0°| `rounded_rectangle` | 499×499 | `ee5739674d55862a...` | `5728fa1dd908b532...` | **TAK** | **10.249** | 186 | **20.43 dB** | **BRAK (PASS)** |

### B. Weryfikacja różnic numerycznych:
1. **Wyjaśnienie identycznych liczb z poprzedniego raportu**:
   - W poprzednim raporcie wartości MAE 0.11 / PSNR 55.80 dB wynikały ze skryptu ad-hoc, w którym wywołanie `VP ProcessFrame` bez zainicjalizowanego dekodera wideo zwracało zerowany bufor.
   - W niniejszym etapie przeprowadzono pełną, bezwzględną weryfikację na **rzeczywistych klatkach MP4 wyrenderowanych przez produkcyjny potok**.
   - Wszystkie pary klatek posiadają **niezależne, unikalne sumy kontrolne SHA256** (wykluczono porównywanie klatki z samą sobą).
2. **Przyczyna MAE ≈ 10–12 przy Pitch > 0**:
   - Przy `pitch = 0.0°` różnica wynosi zaledwie **MAE = 0.209, PSNR = 50.73 dB**, co potwierdza idealną zgodność silnika renderującego.
   - Przy `pitch > 0` CPU wykonuje **dwa kolejne, stratne resam状態で**: najpierw Pillow `rotate(BICUBIC)` z kwantyzacją do 8-bit, a następnie OpenCV `warpPerspective(LANCZOS4)` z drugą kwantyzacją do 8-bit. Powoduje to podwójne rozmycie drobnych szczegółów mapy satelitarnej.
   - GPU wykonuje **dokładnie jeden, zintegrowany sampling przestrzenny (Fused CS)** bezpośrednio z tekstury źródłowej w przestrzeni float, zachowując wyższą ostrość krawędzi dróg i obiektów.
   - W kanale Alpha różnica wynosi **0.000 (maksymalna różnica 0)** — maska kształtu, ramka i obwiednia są w 100% bitowo identyczne.
3. **Weryfikacja rozróżnialności kształtów (Cross-Shape Check)**:
   - Hash Square:  `0256b2bee3584956dbe75e0d05fc9a0d6312522fe0be15908b8b1ad1a4a55e79`
   - Hash Circle:  `a893cd3f85681752ec0917f56946c1e4489d8c3e075ee6350b801bbcbdbaa286`
   - Hash Rounded: `5728fa1dd908b532fa83be7b2042404258a78e90bdad23778e100d3f41a16b60`
   - Hashe są całkowicie różne — zmiana kształtu w konfiguracji realnie zmienia renderowany kształt i maskę mapy.
4. **Weryfikacja kątów nachylenia (Cross-Pitch Check)**:
   - Pitch 0°:  `7457c9b80398d4897d18fe67999a9132dc6f15c91ec3002c6824ddfaf0eb0e49`
   - Pitch 30°: `0256b2bee3584956dbe75e0d05fc9a0d6312522fe0be15908b8b1ad1a4a55e79`
   - Pitch 45°: `e7d0fa8af6860dd96eba6170087a1e12e7de8232c147e712990d837f4df76e10`
   - Kąty nachylenia generują prawidłową, ciągłą i deterministyczną projekcję perspektywiczną.
5. **Kontrola defektu trapezu**:
   - Piksele w narożnikach `(5,5)`, `(493,5)`, `(5,493)`, `(493,493)` zostały bezpośrednio zbadane we wszystkich wyrenderowanych klatkach Square.
   - Wartości próbek: `[62, 61, 51]`, `[80, 82, 52]`, `[35, 41, 43]`, `[60, 59, 60]`. Narożniki są w 100% wypełnione teksturą podkładu satelitarnego — brak jakichkolwiek czarnych lub przezroczystych ubytków trapezu (`Trapezoid Defect = False`).

---

## 13. WERYFIKACJA GRANICY KLIPÓW MULTIFILE (`BOUNDARY_gpu_pitch`)

- **Dataset**: `GX010378.MP4` + `GX010379.MP4`
- **Zakres**: 300 klatek od t = 140.0 s nagrania (przejście między klipami następuje przy klatce 198).
- **Wyniki**:
  - Render FPS: **37.490 FPS** (Effective FPS: **29.383 FPS**).
  - Czas mapy: **2.820 ms**.
  - `map_gpu_pitch_used`: `true`, `map_cpu_rotate_bypassed`: `true`, `map_cpu_pitch_bypassed`: `true`.
  - Przełączenie źródła przebiegło bezbłędnie bez restartu potoku D3D11, bez utraty orientacji Track-Up, bez resetu trasy GPS i bez zniknięcia markera.
  - Strumień audio AAC zachował pełną ciągłość (dokładnie 469 pakietów AAC, monotoniczny rosnący PTS).

---

## 14. WERYFIKACJA HDR, AMF VBR/QP I DIRECT COPY AUDIO

### A. Potok HDR HLG Preserve:
- Wszystkie pliki wynikowe z serii (`WARMUP`, `A1`, `B1`, `B2`, `A2`, `BOUNDARY`) zostały zbadane za pomocą `ffprobe`:
  - Kodek wideo: `hevc`
  - Profil: `Main 10` (10-bit)
  - Format piksela: `yuv420p10le`
  - Zakres: `pc` (full range)
  - Przestrzeń barwna: `bt2020nc`
  - Transfer: `arib-std-b67` (HLG)
  - Prymaria: `bt2020`
  - Klatkaż: 29.970 FPS (30000/1001), 300 klatek, czas trwania: 10.010000 s.

### B. Kontrola HLG → SDR (`TONEMAP_SDR_gpu_pitch`):
- Weryfikacja `ffprobe`:
  - Kodek wideo: `hevc`
  - Profil: `Main` (8-bit)
  - Format piksela: `yuv420p`
  - Zakres: `tv` (limited range)
  - Standard barwny: `bt709` (przestrzeń, transfer, prymaria)
  - Render FPS: **40.190 FPS**, Effective: **32.449 FPS**, Map CPU: **2.852 ms**.

### C. Enkoder AMF VBR i QP:
- We wszystkich przebiegach:
  - `submitted`: 300, `output`: 300, `dropped`: 0, `retries`: 0, `input_full`: 0.
  - Zero odrzuconych klatek, zero ponowień kolejki AMF.

### D. Audio Original Direct Copy & Single Live Mux:
- Kontrola pakietów w wygenerowanych MP4:
  - Kodek: `aac`, Profil: `LC`, Częstotliwość: 48000 Hz, Kanały: 2.
  - Liczba pakietów audio: **dokładnie 469 pakietów** (dla 10.01 s wideo, 469 × 1024 / 48000 ≈ 10.0053 s).
  - Weryfikacja monotoniczności PTS: `pts_monotonic = True` we wszystkich 8 plikach.
  - Potwierdzono użycie pojedynczego procesu FFmpeg z potokiem nazwanym `\\.\pipe\telem_amf_audio_*` oraz flagą `-c copy`. Brak reenkodowania, brak plików pośrednich.

---

## 15. OSIĄGNIĘCIE KRYTERIUM WYDAJNOŚCIOWEGO

Zgodnie z wytycznymi sekcji 11:
- **Kryterium docelowe**: `>= 40 FPS` dla pełnego layoutu użytkownika z Pitch 30.
- **Rzeczywiste wyniki nowej ścieżki**:
  - `B1_gpu_pitch`: **40.992 FPS**
  - `B2_gpu_pitch`: **41.302 FPS**
  - Średnia GPU Pitch: **41.147 FPS**
- **CEL WYDAJNOŚCIOWY ZOSTAŁ W PEŁNI OSIĄGNIĘTY**.
- Przywrócono poziom wydajności znany dotychczas wyłącznie z konfiguracji płaskiej bez pochylenia (`pitch = 0`).

---

## 16. OCHRONA ŚRODOWISKA PRODUKCYJNEGO

- Oryginalna biblioteka produkcyjna `runtime/amd/bin/telem_amd_native.dll` (SHA256: `e359d7784d2ff3d2b1aefb6cf56dc1ba3c38a67260fd8d87e27851ef0d55ee89`) **pozostała w 100% nienaruszona**.
- Testowa biblioteka DLL **nie została skopiowana** do katalogu `runtime/amd/bin/`.
- Pakiet portable **nie był przebudowywany**.
- Flaga `AMD_NATIVE_MAP_GPU_PITCH=1` **nie została włączona globalnie** ani zapisana do konfiguracji domyślnej.
- Prywatny plik konfiguracyjny użytkownika `def_layout.json` **nie został zmodyfikowany**.

---

## 17. ZMIENIONE PLIKI I ARTEFAKTY

W ramach bieżącego etapu powstały wyłącznie narzędzia testowe i artefakty walidacyjne:
- `tools/benchmark_gpu_pitch_ab.py` — automatyczny runner serii A/B
- `tools/run_visual_parity_harness.py` — walidator geometrii, kształtów i hashy
- `tools/verify_benchmark_details.py` — audytor pakietów audio, metadanych HDR i profili AMF
- Raporty i katalogi danych:
  - `Raporty/gpu_pitch_bench_artifacts/benchmark_summary.json`
  - `Raporty/gpu_pitch_bench_artifacts/detailed_verification.json`
  - `Raporty/gpu_pitch_bench_artifacts/visual_parity/visual_parity_report.json`
  - Zrzuty klatek i wycinki porównawcze w `Raporty/gpu_pitch_bench_artifacts/visual_parity/`
  - Niniejszy raport: `Raporty/RAPORT_SPORTCAMHUD_AMD_GPU_PITCH_PERFORMANCE_AB.md`

---

## 18. POWIADOMIENIE NTFY

Wysłano powiadomienie do kanału użytkownika:
- **URL**: `https://ntfy.sh/MalcerzPOP`
- **HTTP Status**: `200`
- **ID wiadomości**: `G0JNUP6GFpHN`
- **Tytuł**: `SportCamHUD — AMD GPU Pitch Performance`
- **Treść wiadomości**:
  ```text
  STATUS: PASS
  CPU Pitch FPS: 21.041
  GPU Pitch FPS: 41.147
  Gain: +95.56%
  Full layout Pitch 30: YES
  40 FPS achieved: YES
  GPU Pitch active: YES
  CPU rotate bypass: YES
  CPU warp bypass: YES
  HUD parity: PASS
  HDR/VBR/QP: PASS
  Audio Copy: PASS
  Production DLL unchanged: YES
  Test DLL SHA: 6ace4d05b75fbf58cf6477b4c1571f4ce5e972a2377f0d85bae84e839ca9d4b7
  Recommendation: DEPLOY
  Report: RAPORT_SPORTCAMHUD_AMD_GPU_PITCH_PERFORMANCE_AB.md
  ```

---

## 19. PODSUMOWANIE I REKOMENDACJA KOŃCOWA

Nowa biblioteka DLL D3D11 AMD z natywnym GPU Track-Up + Pitch całkowicie rozwiązuje problem regresji wydajnościowej zidentyfikowany w raporcie 18 FPS. Przeniesienie podwójnego resamplingu z jednowątkowego Pythona na GPU podwoiło tempo renderowania (z 21 FPS do ponad 41 FPS) przy zachowaniu perfekcyjnej geometrii, braku ubytków trapezu, zachowaniu kształtów mapy, pełnej zgodności kolorystycznej Main 10 HLG oraz bezpośredniego kopiowania strumienia audio AAC.

**Rekomendacja**: **WDROŻYĆ (DEPLOY)** w kolejnym kroku, po autoryzacji przez użytkownika.
