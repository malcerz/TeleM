# RAPORT: AMD BIKERIDEHUD BOOTSTRAP & REAL GUI SMOKE RENDER

## 1. STATUS I METADANE
- **Status zadania**: CASE A — AMD BIKERIDEHUD BOOTSTRAP READY
- **Branch**: `amd-bikeridehud`
- **HEAD**: `1b5485c0c7cd6f7b3d10e677aba315a40e0a3c98`
- **Katalog roboczy**: `C:\_DEV\SportCamHUD`
- **Katalog referencyjny (Oracle)**: `C:\_DEV\TeleM` (nietknięty, stan read-only)
- **Data wykonania**: 2026-09-16 07:22 CEST
- **Platforma**: Asus PN51 (AMD Radeon (TM) Graphics, Barcelo / Cezanne APU, Driver 31.0.21925.1001)

---

## 2. ETAP 1 — REKONSTRUKCJA LAUNCHERA (SportCamHUD.py)

- **Problem wyjściowy**: Po commicie `b3c74bf` brakowało fizycznego pliku `SportCamHUD.py`, a kompatybilny shim `TeleMGP.py` importował z niego symbole, powodując `ModuleNotFoundError`.
- **Rozwiązanie**:
  - Utworzono plik `SportCamHUD.py`, który implementuje kanoniczny punkt wejścia PySide6 (`src.gui.qt.application.main()`) oraz re-eksportuje 12 kluczowych funkcji telemetrycznych z `src.telemetry_extract` (wspierając zgodność wsteczną z testami i `TeleMGP.py`).
  - Plik `TeleMGP.py` oraz `SportCamHUD.py` uruchamiają się bezbłędnie.
- **Weryfikacja startu GUI**:
  - `python SportCamHUD.py` -> **PASS**
  - `MainWindow` inicjalizuje się prawidłowo (tytuł: *SportCamHUD v0.7.9*, 4 zakładki: *Wczytywanie*, *Projekt*, *Rendering*, *Ustawienia*).
  - Log startu: [gui_start.log](file:///C:/_DEV/SportCamHUD/scratch/amd_bootstrap/gui_start.log)

---

## 3. ETAP 2 — BUILD I WERYFIKACJA NATIVE AMD DLL

- **Zasada**: Źródła C++ w `native/d3d11_amf_pipeline` zostały zbudowane bezpośrednio w nowym checkout; nie kopiowano skompilowanej binarki ze starego repo.
- **Narzędzia kompilacji**:
  - Kompilator: `C:\tools\mingw64\bin\g++.exe` (MinGW-W64 GCC 16.2.0)
  - Generator: `C:\tools\mingw64\bin\ninja.exe` (Ninja 1.13.2)
  - CMake: `C:\tools\mingw64\bin\cmake.exe` (CMake 4.4.2)
- **Polecenie konfiguracji i budowania**:
  ```powershell
  C:\tools\mingw64\bin\cmake.exe --fresh `
    -S native\d3d11_amf_pipeline `
    -B native\d3d11_amf_pipeline\build `
    -G Ninja `
    -DCMAKE_BUILD_TYPE=Release `
    -DCMAKE_MAKE_PROGRAM=C:\tools\mingw64\bin\ninja.exe `
    -DCMAKE_CXX_COMPILER=C:\tools\mingw64\bin\g++.exe

  C:\tools\mingw64\bin\cmake.exe --build `
    native\d3d11_amf_pipeline\build `
    --config Release --target telem_amd_native
  ```
- **Metryki zbudowanej biblioteki DLL**:
  - Ścieżka docelowa: `native\d3d11_amf_pipeline\bin\telem_amd_native.dll`
  - Rozmiar: **3 095 176 bajtów**
  - SHA256: `9bbc1aca974620b818bb02407bb738b8c09c03f9b057ea729ebd5a64601757e4`
  - Build Info w bibliotece: `version=1.0.0; build_id=telem-amd-native/1.0.0+1b5485c0c7cd.src698a06a0caed; git_commit=1b5485c0c7cd6f7b3d10e677aba315a40e0a3c98`
- **ABI & Load Test**:
  - Wersja ABI: **9**
  - Przetestowano i potwierdzono obecność oraz poprawne powiązanie wszystkich **66 symboli C** wymaganych przez `src/ffmpeg/amd_native_exporter.py`.
  - **Werdykt ładowania DLL**: **PASS**
  - Dowód: [dll_proof.txt](file:///C:/_DEV/SportCamHUD/scratch/amd_bootstrap/dll_proof.txt)

---

## 4. ETAP 3 — REAL GUI SMOKE RENDER

- **Ścieżka wykonania**:
  `GUI (MainWindow / RenderTab)` -> `RenderMixin` -> `AMD child process (run_amd_render_child)` -> `amd_native_exporter` -> `telem_amd_native.dll` -> `AMF HEVC`
- **Dane wejściowe**:
  - Wideo: `Video/GX020079.mp4` (4K UHD, 3840x2160, 29.97 fps)
  - Telemetria: `Video/GX020079.fit` (1704 rekordy FIT)
  - Zakres renderu: początkowe 10.0 s (300 klatek)
- **Wyniki renderu**:
  - Liczba wyrenderowanych klatek: **300 / 300** (100%)
  - Czas trwania renderingu: **8.29 s**
  - Średnia prędkość renderowania: **36.2 FPS** (prędkość w czasie rzeczywistym szybsza niż 1.2x czasu trwania wideo 4K!)
  - Błędy potoku AMF / D3D11: **0**
  - Status procesu potomnego: `exitcode=0`, czyste zwolnienie zasobów GPU.
  - **Werdykt renderu**: **PASS**
- **Wygenerowany plik wyjściowy**:
  - Ścieżka: [smoke_render_10s.mp4](file:///C:/_DEV/SportCamHUD/scratch/amd_bootstrap/smoke_render_10s.mp4)
  - Rozmiar: **85 375 163 bajty (~85.4 MB)**
  - Kodek: HEVC Main, 3840x2160, 29.97 fps, audio AAC 48 kHz stereo
  - Profiler: [smoke_render_10s.mp4.amd_profile.json](file:///C:/_DEV/SportCamHUD/scratch/amd_bootstrap/smoke_render_10s.mp4.amd_profile.json)

---

## 5. DOWODY WIZUALNE (VISUAL ACCEPTANCE)

Z wyrenderowanego pliku wideo wyodrębniono klatki wzorcowe:
1. Klatka 0 (0.00s): [frame_000.png](file:///C:/_DEV/SportCamHUD/scratch/amd_bootstrap/frames/frame_000.png)
2. Klatka środkowa 150 (5.00s): [frame_150.png](file:///C:/_DEV/SportCamHUD/scratch/amd_bootstrap/frames/frame_150.png)
3. Klatka końcowa 299 (9.98s): [frame_299.png](file:///C:/_DEV/SportCamHUD/scratch/amd_bootstrap/frames/frame_299.png)
4. Zestawienie (Contact Sheet): [contact_sheet.png](file:///C:/_DEV/SportCamHUD/scratch/amd_bootstrap/contact_sheet.png)

### Zestawienie klatek:
![Contact Sheet](file:///C:/_DEV/SportCamHUD/scratch/amd_bootstrap/contact_sheet.png)

- **Status wizualny**: `USER VISUAL ACCEPTANCE=PENDING`
- Wskaźniki overlayu:
  - Dynamiczna obracana mapa GPS (Track-up GPU Map)
  - Wykresy kadencji i tętna (AFTER-MAP GPU Split Charts)
  - Prędkościomierz (AFTER-MAP GPU Speed Gauge)
  - Pasek dystansu, bateria Garmin/GoPro, parametry kamery (ISO, ekspozycja, temperatura)

---

## 6. PLIKI ZMODYFIKOWANE / UTWORZONE

- Utworzone:
  - `SportCamHUD.py` (kanoniczny launcher)
  - `native/d3d11_amf_pipeline/bin/telem_amd_native.dll` (zbudowana natywna biblioteka)
  - `scratch/amd_bootstrap/*` (logi, dowody, skrypty walidacji, wyjściowy film MP4, klatki PNG)
  - `Raporty/RAPORT_AMD_BIKERIDEHUD_BOOTSTRAP.md` (niniejszy raport)
- Repozytorium referencyjne: `C:\_DEV\TeleM` **nienaruszone**.

---

## 7. PODSUMOWANIE WERDYKTÓW

```text
GUI_START=OK
DLL_BUILD=OK
DLL_LOAD=OK
SMOKE_RENDER=OK
CASE=CASE A — AMD BIKERIDEHUD BOOTSTRAP READY
```

---

## 8. NTFY RESULT
```text
attempts=1
final_exit_code=0
NTFY_SUCCESS=True
```

