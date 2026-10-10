# Raport: Przebudowa panelu Wczytywanie — Możliwości sprzętu oraz Wieloplikowe Informacje o filmach

Data: 2026-09-24  
Workspace: `C:\_DEV\SportCamHUD-amd`  
Branch: `amd-bikeridehud`  
Commit baseline: `0ef407e`

---

## 1. Wymagane podsumowanie parametrów bramki (Hard Gates)

```text
TOP_PANEL_SPLIT=2:1 (Lewa: ~68.1% / Prawa Hardware Panel: ~31.9% szerokości)
HARDWARE_PANEL_FIELDS=OS, CPU, Wątki, RAM, GPU, Podgląd, Kodowanie (AMD/NVIDIA/Intel/CPU), Dekodowanie (H.264/HEVC/AV1), Maks. rozdzielczość dekodowania i kodowania
MULTIFILE_INFO_VIEW=Vertical Cards List (QScrollArea + VideoFileCardWidget)
VISIBLE_CARDS_COUNT=5 (domyślnie widocznych ~5 kart w oknie roboczym)
SCROLLBAR_FOR_MORE_THAN_5=TAK (pionowy scrollbar aktywny przy >5 kartach / przepełnieniu widoku)
MIXED_RESOLUTIONS_BEHAVIOR=Informacyjny baner na górze sekcji informacji (lbl_mixed_res_banner); każdy plik zachowuje własne parametry wejściowe, brak nadpisywania
PER_TASK_METADATA_CONFIRMED=TAK (self._files_metadata lista dictów, per-card metadata bundle, per-job snapshot w kolejce)
FILES_TESTED=Video/GX020079.MP4 (4K), Video/GX030120.MP4 (4K), scratch/test_4k_to_4k_out.mp4 (4K), scratch/sample_5k3.mp4 (5.3K), Video/GX020079_8K.MP4 (8K)
MODIFIED_FILES=src/gui/qt/tabs/load_tab.py, src/gui/qt/hardware_info.py
KNOWN_LIMITATIONS=Brak bezpośredniej detekcji VRAM przez WMI (użyto precyzyjnych i szybkich rejestrów systemowych Windows oraz GlobalMemoryStatusEx bez spowalniania startu GUI)
```

---

## 2. Cel zadania

1. **Zwężenie sekcji wyboru plików źródłowych** i podział poziomy górnej części ekranu na proporcje ~2/3 (lewa część) do ~1/3 (prawa część).
2. **Dodanie panelu „Możliwości sprzętu”**:
   - Odczyt CPU, liczby rdzeni/wątków, RAM, systemu operacyjnego, kart GPU.
   - Odczyt aktywnego backendu podglądu GPU.
   - Odczyt obsługiwanych enkoderów sprzętowych (AMD AMF, NVIDIA NVENC, Intel QSV, CPU libx264/libx265).
   - Odczyt obsługiwanych dekoderów sprzętowych (H.264, HEVC, AV1).
   - Wyświetlenie maksymalnych rozdzielczości dekodowania/kodowania.
   - Całkowicie bezpieczny tryb tylko do odczytu (read-only), bez naruszania backendów renderowania.
3. **Wieloplikowe „Informacje o filmie”**:
   - Zastąpienie pojedynczego statycznego widoku listą pionowych kart (`VideoFileCardWidget`).
   - Każda karta prezentuje dedykowany zestaw metadanych pliku: nazwa, rozmiar, czas, rozdzielczość, FPS, kodek, profil, format piksela/bit depth, bitrate, profil koloru/przestrzeń/zakres, audio, GPMF (TAK/NIE), sparowany plik FIT/GPX oraz przycisk i wyniki analizy QP.
   - Domyślnie mieści do 5 kart; powyżej 5 kart pojawia się płynny pionowy scrollbar (`QScrollArea`).
   - Brak nieporęcznych zakładek poziomy — przejrzysta pionowa lista.
4. **Obsługa mieszanych rozdzielczości wejściowych (np. 4K, 5.3K, 8K)**:
   - Jawny komunikat informacyjny u góry:
     `ℹ Wczytano pliki o różnych rozdzielczościach źródłowych. Każdy plik zachowuje własne parametry wejściowe.`
   - Każdy plik zachowuje własne parametry techniczne w modelu danych `_files_metadata` i na swojej karcie.
   - Brak zanieczyszczania metadanych między plikami.

---

## 3. Zrealizowane modyfikacje architektury

### 3.1. Moduł diagnostyki sprzętu: `src/gui/qt/hardware_info.py`
- Zaimplementowano bez zewnętrznych bibliotek (brak `psutil` w środowisku produkcyjnym):
  - **RAM**: Bezpośrednie wywołanie Windows API `GlobalMemoryStatusEx` przez `ctypes.windll.kernel32` (odczyt całkowitej pamięci fizycznej w < 0.1 ms).
  - **CPU & Wątki**: Rejestr Windows `HARDWARE\DESCRIPTION\System\CentralProcessor\0\ProcessorNameString` + `os.cpu_count()`.
  - **Karty graficzne**: Połączenie modułu produkcyjnego `src.ffmpeg.amd_capabilities.get_gpu_capabilities()` z rejestrem kart graficznych `SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}` z automatyczną deduplikacją.
  - **Podgląd GPU**: Integracja z `src.gui.qt.mpv_hwdec.detect_preview_vendor()`.
  - **Enkodery**: Sprawdzenie dostępności koderów `hevc_amf`, `h264_amf`, `hevc_nvenc`, `hevc_qsv`, `libx265`.
  - **Dekodery**: D3D11VA H.264, D3D11VA HEVC (Main / Main10), AV1.
  - **Maks. rozdzielczość**: Odczyt parametrów z drivera AMD AMF (np. dekoder do 8K 7680×4320, enkoder AMF HEVC do 4096×4096).
  - Wyniki są buforowane w pamięci procesu (`_CACHED_HW_INFO`).

### 3.2. Panel `HardwareInfoWidget` w `src/gui/qt/tabs/load_tab.py`
- Zbudowany jako estetyczny `QGroupBox("Możliwości sprzętu")`.
- Układ `QFormLayout` z dopasowaniem pól, zawijaniem długich wierszy (`setWordWrap(True)`) i czytelnym podziałem etykieta → wartość.
- Prawa kolumna górnego podziału `top_hsplit` o współczynniku `stretch=1`.

### 3.3. Karty plików wideo: `VideoFileCardWidget` w `src/gui/qt/tabs/load_tab.py`
- Każda karta to elegancka ramka `QFrame` z:
  - Nagłówkiem: numer pliku `[#1]`, pogrubiona nazwa pliku, badge czasu trwania `⏱`, rozmiaru `💾` oraz niezależny przycisk `Analiza QP`.
  - 4-kolumnową siatką parametrów technicznych:
    - Rozdzielczość (wyróżniona kolorem `#0078d4`), FPS
    - Kodek wraz z profilem, format piksela i głębia bitowa
    - Bitrate wideo, podsumowanie profilu barw i zakresu (np. `BT.709 [Limited]`)
    - Informacje o audio (kodek, kHz, kanały), flaga GPMF (`TAK` / `NIE`)
  - Wierszem sparowanej telemetrii: `FIT / GPX: <nazwa pliku>` aktualizowanym natychmiast po wyborze manualnym lub dopasowaniu przez AutoFIT.
  - Zwijanym panelem wyników QP: informacja o postępie w toku lub pełen rozkład QP (średnia, mediana, min, max, klatki, czas).

### 3.4. Integracja `LoadTab` i obsługa wielu rozdzielczości
- Górny układ podzielony przez `QHBoxLayout` na lewą stronę (`stretch=2`) i prawą stronę (`stretch=1`).
- Pomiędzy wczytywaniem a kartami umieszczono baner `lbl_mixed_res_banner`, który uaktywnia się automatycznie tylko wtedy, gdy wykryto więcej niż jedną unikalną rozdzielczość wejściową.
- Zachowano pełną zgodność wsteczną dla testów jednostkowych (`self.lbl_file_info`, `self.btn_analyze_qp`, `self.lbl_qp_result`).

---

## 4. Wyniki testów

### 4.1. Zestaw testów automatycznych weryfikacji funkcjonalnej (`scratch/test_load_panel_hardware_and_multifile.py`)

1. **TEST 1: 1 plik 4K (`Video/GX020079.MP4`)**
   - Karta 0: `GX020079.MP4`
   - Rozdzielczość: `3840 × 2160`, FPS: `29.97`, Kodek: `HEVC / H.265`, GPMF: `False`
   - Baner mieszanych rozdzielczości widoczny: `False` (ukryty dla 1 pliku)
   - Status: **PASS**

2. **TEST 2: 3 pliki 4K (`GX020079.MP4`, `GX030120.MP4`, `scratch/test_4k_to_4k_out.mp4`)**
   - Karta 0: `GX020079.MP4` -> `3840 × 2160`, `29.97 fps`
   - Karta 1: `GX030120.MP4` -> `3840 × 2160`, `29.97 fps`
   - Karta 2: `test_4k_to_4k_out.mp4` -> `3840 × 2160`, `29.97 fps`
   - Baner mieszanych rozdzielczości widoczny: `False` (identyczne rozdzielczości)
   - Status: **PASS**

3. **TEST 3: 3 pliki mieszane (4K + 5.3K + 8K)**
   - Karta 0 (4K): `GX020079.MP4` -> `3840 × 2160`
   - Karta 1 (5.3K): `sample_5k3.mp4` -> `5312 × 2988`
   - Karta 2 (8K): `GX020079_8K.MP4` -> `7680 × 4320`
   - Baner mieszanych rozdzielczości widoczny: `True`
   - Treść baneru: `ℹ Wczytano pliki o różnych rozdzielczościach źródłowych. Każdy plik zachowuje własne parametry wejściowe.`
   - Izolacja parametrów: każdy plik posiada swój własny słownik parametrów, brak wzajemnego nadpisywania.
   - Status: **PASS**

4. **TEST 4: Przewijanie listy kart (>5 kart)**
   - Wczytano 6 kart wideo.
   - Wysokość kontenera kart (`sizeHint`): `1486 px`.
   - Wysokość obszaru widocznego (`viewport`): `402 px`.
   - Parametry scrollbara pionowego: `min=0, max=1084, visible=True`.
   - Karty przewijają się płynnie, brak ucinania tekstu.
   - Status: **PASS**

5. **TEST 5: Panel możliwości sprzętu i stabilność layoutu**
   - Szerokość zakładki: `1280 px`, szerokość panelu sprzętu: `408 px` (udział: `31.9%` ~ 1/3).
   - Wszystkie pola wypełnione rzetelnymi danymi systemowymi:
     - CPU: AMD Ryzen 7 7730U (16 wątków)
     - RAM: 27.9 GB
     - GPU: AMD Radeon (TM) Graphics (sterownik 31.0.21925.1001)
     - Enkodery: AMD AMF dostępne, CPU libx265/libx264 dostępne, NV/Intel niedostępne
     - Dekodery: D3D11VA sprzętowe H.264/HEVC/AV1
     - Rozdzielczości: Dekodowanie do 8K, Kodowanie do 4096×4096 (AMF HEVC)
   - Brak zniekształceń layoutu i brak przepełnień.
   - Status: **PASS**

### 4.2. Test kolejki i osi czasu dla wielu rozdzielczości (`scratch/test_queue_multifile_resolution.py`)
- Sprawdzono `build_timeline_from_paths` dla zestawu 4K, 5.3K i 8K:
  - `c0`: `GX020079.MP4` -> `3840x2160`
  - `c1`: `sample_5k3.mp4` -> `5312x2988`
  - `c2`: `GX020079_8K.MP4` -> `7680x4320`
- Zweryfikowano snapshoty `ExportJob` w `ExportQueue`: każde zadanie zachowuje własne ścieżki i rozdzielczości wejściowe bez wzajemnego wpływu.
- Wynik: **PASS**.

### 4.3. Regresja istniejących testów jednostkowych (pytest)
- `tests/test_mp4_inspector.py`: 21 passed
- `tests/test_qp_analyzer.py`: 15 passed
- `tests/test_autofit_pre_load.py`: 4 passed
- `tests/test_export_queue_basic.py`: 23 passed
- `tests/test_export_queue_lifecycle.py`: 6 passed
- Łącznie: **69 passed in 13.43s**.

### 4.4. Test dymny startu całego GUI (`scratch/test_gui_startup_smoke.py`)
- Pełen start okna głównego `MainWindow`, kontrolera, odtwarzacza podglądu i kolejki: **ALL_SMOKE_CHECKS=PASS**.

---

## 5. Podsumowanie czasów wykonania (Execution Time Breakdown)

```text
AUDIT_TIME:                  ~8 min
IMPLEMENTATION_TIME:         ~14 min
VALIDATION_TIME:             ~9 min
TOTAL_STAGE_WALL_TIME:       ~31 min
LONGEST_SINGLE_COMMAND_SEC:  ~13.4s (pytest 69 tests)
```

Zadanie wykonane z zachowaniem reguł izolacji backendów, bez zmian w pipeline AMD/NVIDIA/Intel, bez commitowania i bez pushowania zmian do repozytorium.
