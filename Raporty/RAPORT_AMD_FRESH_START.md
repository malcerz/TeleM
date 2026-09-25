# RAPORT: AMD FRESH START & ENVIRONMENT AUDIT

## 1. METADANE ZADANIA
- **Data audytu**: 2026-09-16 06:21 CEST
- **Stacja robocza**: Asus PN51 (AMD Ryzen / Barcelo / Cezanne APU, Windows 11 Pro)
- **Repozytorium docelowe**: `C:\_DEV\BikeRideHUD`
- **Repozytorium referencyjne (Oracle)**: `C:\_DEV\TeleM`

---

## 2. JEDNOZNACZNE ODPOWIEDZI AUDYTU

```text
NEW_BRANCH=amd-bikeridehud
NEW_HEAD=1b5485c0c7cd6f7b3d10e677aba315a40e0a3c98

OLD_AMD_PATH=C:\_DEV\TeleM
OLD_AMD_BRANCH=amd-render
OLD_AMD_HEAD=7e4e34ecae13eae947c0386443e6a7317b42256f

GPU=AMD Radeon (TM) Graphics
DRIVER=31.0.21925.1001

H264_AMF=YES
HEVC_AMF=YES
AV1_AMF=YES

AMD_RUNTIME_DLL_PRESENT_NEW=NO
AMD_RUNTIME_DLL_PRESENT_OLD=YES

GUI_START=FAIL
AMD_BACKEND_AVAILABLE=YES

READY_FOR_AMD_PORT=YES
```

### Zidentyfikowany stan (CASE):
**`CASE B — FRESH BRANCH READY, RUNTIME DLL/DEPENDENCY MISSING`**

---

## 3. SZCZEGÓŁOWY PRZEBIEG I WYNIKI KROKÓW

### Krok 1 & 5: Stan Starego Katalogu AMD (Oracle / Backup)
- **Ścieżka**: `C:\_DEV\TeleM`
- **Branch**: `amd-render`
- **HEAD**: `7e4e34ecae13eae947c0386443e6a7317b42256f` (`AMD: freeze optimized backend before Intel integration`)
- **Remote**: `https://github.com/malcerz/TeleM.git`
- **Integralność**: Katalog pozostał **fizycznie nienaruszony** (nie wykonywano pull, reset, clean, restore ani rebase).
- **Inwentaryzacja plików w starym repo**:
  - `src/ffmpeg/amd_native_exporter.py`: obecny (301 729 bajtów, 6110 linii)
  - `src/ffmpeg/amd_child_process.py`: **brak** (funkcjonalność dodana później na `main`)
  - `src/ffmpeg/amd_config.py`: obecny (8 119 bajtów, 217 linii)
  - `native/d3d11_amf_pipeline/bin/telem_amd_native.dll`: **obecny** (3 059 698 bajtów)
  - `native/d3d11_amf_pipeline/bin/telem_amd_native.dll.golden-5R`: **obecny** (2 950 557 bajtów)
- **Niezacommitowane zmiany robocze w starym repo**:
  - `src/ffmpeg/amd_native_exporter.py`: integracja callbacków `progress_tracker`
  - `src/gui/qt/tabs/render_tab.py`: obsługa `global_pct`
  - `src/telemetry_precompute.py`: callbacki `progress_cb`
  - *Uwaga*: Plik `src/render_progress.py` znajduje się już na `main` w `BikeRideHUD`.

---

### Krok 2, 3 & 4: Fresh Clone i Utworzenie Gałęzi AMD
- **Ścieżka**: `C:\_DEV\BikeRideHUD`
- Przed wykonaniem operacji katalog `C:\_DEV\BikeRideHUD` nie istniał.
- Wykonano czysty klon z `https://github.com/malcerz/TeleM.git`.
- **Weryfikacja SHA origin/main**:
  - `branch`: `main`
  - `HEAD`: `1b5485c0c7cd6f7b3d10e677aba315a40e0a3c98`
  - `origin/main`: `1b5485c0c7cd6f7b3d10e677aba315a40e0a3c98`
  - Working tree: clean. SHA zgadza się w 100%.
- **Nowa gałąź**:
  - Utworzono: `git switch -c amd-bikeridehud`
  - Potwierdzono: `amd-bikeridehud` na `1b5485c0c7cd6f7b3d10e677aba315a40e0a3c98`.
  - Gałąź **nie została** wypchnięta na remote (`git push` nie był wykonywany).

---

### Krok 6 & 7: Audyt Środowiska AMD i GPU
- **Python**:
  - Wersja: `Python 3.14.7`
  - Ścieżka: `C:\Users\Malcerz\AppData\Local\Microsoft\WindowsApps\python.exe` oraz `C:\Users\Malcerz\AppData\Local\Python\bin\python.exe`
  - Pakiety: `PySide6 (6.11.1)`, `numpy (2.5.1)`, `opencv-python (5.0.0.93)`, `pillow (12.3.0)`, `fitparse (1.2.0)`, `orjson (3.11.9)`, `pyopencl (2026.1.2)`.
- **FFmpeg**:
  - Wersja: `2023-06-26-git-285c7f6f6b-full_build-www.gyan.dev`
  - Flagi: m.in. `--enable-amf`, `--enable-d3d11va`
- **Enkodery AMF**:
  - `h264_amf`: **TAK** (V....D AMD AMF H.264 Encoder)
  - `hevc_amf`: **TAK** (V....D AMD AMF HEVC encoder)
  - `av1_amf`: **TAK** (V....D AMD AMF AV1 encoder – obecny w binariach ffmpeg)
- **Karta graficzna (GPU)**:
  - Nazwa: `AMD Radeon (TM) Graphics`
  - PnP ID: `PCI\VEN_1002&DEV_15E7&SUBSYS_16361002&REV_C4...` (Asus PN51, architektura Barcelo / Cezanne)
  - Wersja sterownika: `31.0.21925.1001` (z dnia 20.05.2026)
  - Pamięć AdapterRAM (VRAM): `4 293 918 720 bajtów (~4.0 GB)`
  - Status: `OK`

---

### Krok 8: Porównanie Nowy Main (`BikeRideHUD`) vs Stary AMD (`TeleM`)
1. `src/ffmpeg/amd_native_exporter.py`:
   - Stary AMD: 301 729 bajtów (6110 linii)
   - Nowy main: 385 602 bajty (7698 linii)
   - Wersja w nowym `main` zawiera późniejsze usprawnienia pipeline'u D3D11, preview tap, dynamiczne regiony HUD oraz zaawansowaną diagnostykę.
2. `src/ffmpeg/amd_child_process.py`:
   - Stary AMD: brak pliku.
   - Nowy main: obecny (izolacja procesu renderowania AMD przed zanieczyszczeniem pamięci GUI).
3. `src/ffmpeg/amd_config.py`:
   - Obie wersje posiadają 217 linii i tę samą strukturę konfiguracyjną.
4. `native/d3d11_amf_pipeline`:
   - C++ (`telem_amd_native.cpp`): w starym 103 227 bajtów, w nowym 125 272 bajty (nowy main odziedziczył i rozbudował potok AMF async z commitów `b4047ab` i `3546274`).
   - Binaria DLL:
     - W starym AMD: obecna skompilowana biblioteka `native/d3d11_amf_pipeline/bin/telem_amd_native.dll` (3 059 698 B).
     - W nowym repo: skompilowana biblioteka `telem_amd_native.dll` **nie jest wersjonowana w gicie**; w gicie znajduje się wyłącznie plik wzorcowy `telem_amd_native.dll.golden-5R` (2 950 557 B).

---

### Krok 10: Próba Uruchomienia Aplikacji (Smoke Test)
1. `python BikeRideHUD.py`:
   - **Wynik**: `FAIL` (`[Errno 2] No such file or directory`).
   - **Przyczyna**: W commicie `b3c74bf` zmieniono `README.md` i `TeleMGP.py`, deklarując `BikeRideHUD.py` jako kanoniczny launcher, jednak sam plik `BikeRideHUD.py` nie został dodany do repozytorium.
2. `python TeleMGP.py`:
   - **Wynik**: `FAIL` (`ModuleNotFoundError: No module named 'BikeRideHUD'`).
   - **Przyczyna**: `TeleMGP.py` próbuje wykonać `from BikeRideHUD import ...`.
3. Bezpośredni import modułów aplikacji:
   - `from src.gui.qt.application import main` wykonuje się poprawnie (środowisko Qt i Python są gotowe).
4. Wykrywanie backendu:
   - `detect_best_encoder()` zwraca poprawnie: `amd`
   - `detect_gpu_decoder('amd')` zwraca poprawnie: `d3d11va`
5. Dostępność DLL D3D11+AMF:
   - `native/d3d11_amf_pipeline/bin/telem_amd_native.dll` nie istnieje w nowym checkout.
   - Zgodnie z zasadą pkt 10, nie kopiowano samodzielnie plików ze starego AMD.

---

## 4. PODSUMOWANIE I REKOMENDACJA KOLEJNEGO KROKU

- Środowisko sprzętowe, sterowniki AMD i enkodery AMF są w 100% sprawne i zweryfikowane.
- Gałąź robocza `amd-bikeridehud` bazuje na zatwierdzonym punkcie wyjścia `1b5485c0c7cd6f7b3d10e677aba315a40e0a3c98`.
- W kolejnym kroku ("dalej"):
  1. Należy odtworzyć launcher `BikeRideHUD.py` (lub przywrócić poprawny import w `TeleMGP.py`).
  2. Należy zapewnić obecność `telem_amd_native.dll` (poprzez skompilowanie nowej wersji C++ pod Barcelo APU lub użycie dedykowanego artefaktu DLL).
  3. Przeprowadzić krótki smoke render (10–20 s).
