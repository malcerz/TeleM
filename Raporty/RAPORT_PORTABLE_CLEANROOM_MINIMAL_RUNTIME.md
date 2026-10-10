# RAPORT: PORTABLE CLEANROOM MINIMAL RUNTIME & PACKAGING

Data: 2026-09-30  
Autor: Antigravity / Gemini High  
Target środowiskowy: Intel Core i7 / Intel Iris Xe / Windows 11  

---

## 1. METRYKI GŁÓWNE I STATUS KOŃCOWY

```ini
SOURCE_PORTABLE=C:\_DEV\SportCamHUD-portable
SOURCE_REPO=C:\_DEV\SportCamHUD-main-new
CLEAN_TARGET=C:\_DEV\SportCamHUD-portable-clean

ORIGINAL_FILE_COUNT=2499
ORIGINAL_TOTAL_BYTES=1710662812

CLEAN_FILE_COUNT=256
CLEAN_TOTAL_BYTES=816671991

FILE_REDUCTION_COUNT=2243
FILE_REDUCTION_PERCENT=89.76%

SIZE_REDUCTION_BYTES=893990821
SIZE_REDUCTION_PERCENT=52.26%

REMOVED_GROUPS=Raporty, tests, scratch, Video, build, native_source, root_duplicate_binaries, ffplay, ltcdump, duplicate_telemetry_parser, nested_archives, debug_logs, pycache

PYTHON_FILES_SHIPPED=133
ASSET_FILES_SHIPPED=92

COMMON_RUNTIME_FILES=3
AMD_RUNTIME_FILES=2
INTEL_RUNTIME_FILES=8
NVIDIA_RUNTIME_FILES=1

CLEAN_INTEL_DLL_SHA256=113abafbab0c877bc406692a4f60d287041d7e6307912a1b6e790d602888ba4b
CLEAN_INTEL_QUANT_DLL_MATCH=YES

CLEAN_AMD_DLL_SHA256=90be5af56bb56a73cdc161a0508b0d6a2c71987be44a565712c37aa5b5d66647
AMD_KNOWN_GOOD_MATCH=YES

CROSS_VENDOR_RUNTIME_MIXING=NO

EXTERNAL_APPLICATION_FILE_LOADS=0

GUI_START_PASS=YES

INTEL_DIRECT_PASS=YES
INTEL_LIVE_Q_PASS=YES
INTEL_LIVE_MUX_PASS=YES

INTEL_QUEUE_PASS=YES
QUEUE_Q_PASS=YES
QUEUE_FINAL_QUANT_RANGE_PASS=YES

GPMF_EXPORT_PASS=YES

DJI_IMPORT_PASS=YES
DJI_TELEMETRY_OPEN_PASS=YES

AMD_RUNTIME_CONTRACT_PASS=YES
NVIDIA_RUNTIME_CONTRACT_PASS=YES

PORTABLE_MANIFEST=runtime\portable_manifest.json

CLEAN_ZIP=C:\_DEV\SportCamHUD-portable-clean.zip
CLEAN_ZIP_BYTES=322832187

ZIP_EXTRACT_START_PASS=YES
ZIP_EXTRACT_INTEL_PASS=YES

TESTS=PASS
NEW_REGRESSIONS=NONE

COMMIT=c14ca2d
PUSH_RESULT=NOT_PUSHED_REMOTE_AHEAD_OR_NO_FORCE

FINAL_STATUS=PORTABLE_CLEANROOM_PASS
```

---

## 2. CEL I ZAŁOŻENIA PROJEKTOWE

Celem zadania było utworzenie czystego, drastycznie zredukowanego pakietu produkcyjnego SportCamHUD Portable w lokalizacji:
`C:\_DEV\SportCamHUD-portable-clean`
oraz jego archiwum dystrybucyjnego `C:\_DEV\SportCamHUD-portable-clean.zip`, zawierającego **wyłącznie** pliki niezbędne do uruchomienia i pełnego działania aplikacji.

### Kluczowe zasady bezpieczeństwa (Safety Rules):
1. **Nietknięte środowisko wzorcowe (Golden Runtime)**: `C:\_DEV\SportCamHUD-portable` pozostało w 100% nienaruszone (2499 plików, 1.59 GB).
2. **Zachowanie produkcyjnej biblioteki Intel AV1 Quantizer**: Pakiet zawiera zaakceptowaną bibliotekę `telem_intel_native.dll` (`113abafbab0c877bc406692a4f60d287041d7e6307912a1b6e790d602888ba4b`, 216 064 B) ze wsparciem dla live telemetrii kwantyzatora Q. Poprzednia wersja fallback (`41658018ae...`) została wykluczona.
3. **Zachowanie kontraktu AMD i NVIDIA**: Biblioteki AMD (`telem_amd_native.dll`, SHA256: `90be5af56bb5...`) oraz struktura i resolvery NVIDIA zostały w pełni zachowane.
4. **Ścisła izolacja vendorów**: Brak mieszania plików DLL pomiędzy `runtime/common`, `runtime/amd/bin`, `runtime/intel/bin` oraz `runtime/nvidia/bin`.
5. **Podejście Allowlist + Hard Denylist**: Narzędzie pakujące kopiuje tylko jawnie zdefiniowane grupy produkcyjne i weryfikuje brak jakichkolwiek artefaktów developerskich/debugowych.
6. **Autonomia (Zero External Dependencies)**: Czysty runtime nie odwołuje się do repozytorium gita ani innych katalogów deweloperskich.

---

## 3. ANALIZA INWENTARYZACJI I REDUKCJI (FAZY 1, 2, 12, 15, 24)

### 3.1. Porównanie rozmiaru i liczby plików

| Kategoria | Środowisko pierwotne (`portable`) | Czysty pakiet (`portable-clean`) | Różnica / Oszczędność |
| :--- | :--- | :--- | :--- |
| **Liczba plików** | 2 499 | **256** | **-2 243 pliki (-89.76%)** |
| **Liczba katalogów** | 211 | **14** | **-197 katalogów (-93.36%)** |
| **Rozmiar rozpakowany** | 1 710 662 812 B (1.59 GB) | **816 671 991 B (778.84 MB)** | **-893 990 821 B (-52.26%)** |
| **Rozmiar ZIP** | ~500 MB (zanieczyszczony) | **322 832 187 B (307.88 MB)** | **-38.4% oszczędności ZIP** |

### 3.2. Identyfikacja i usunięcie grup zbędnych (Bloat Analysis)

1. **Root Duplicate Executables (-427 MB)**:
   - Duplikaty `ffmpeg.exe` (213.7 MB) oraz `ffprobe.exe` (213.6 MB) w katalogu głównym. Aplikacja SportCamHUD korzysta ze scentralizowanej ścieżki `runtime/common/ffmpeg.exe` i `ffprobe.exe`.
2. **Unused FFplay (-215 MB)**:
   - `runtime/common/ffplay.exe` (215.1 MB) – binarka odtwarzacza FFmpeg nieużywana przez aplikację (podgląd wideo oparty jest na `libmpv-2.dll`).
3. **Raporty developerskie (-100.2 MB)**:
   - Katalog `Raporty/` zawierał 100 MB historii analiz, logów i zrzutów ekranowych.
4. **Archiwa zagnieżdżone (-72 MB)**:
   - `TeleM_project.zip` (43 MB) oraz `mpv-dev.7z` (29 MB) w katalogu głównym.
5. **Kompilacje i źródła natywne (-14.4 MB)**:
   - Źródła C/C++ (`src/native/` oraz `native/`), pliki `.c`, `.cpp`, `.h`, pliki kompilatora (`.obj`, `.lib`, `.exp`), narzędzia CMake i skrypty kompilacji.
6. **Zestawy testowe (-8.1 MB)**:
   - Katalog `tests/` zawierający setki skryptów pytest.
7. **Zbędny duplikat biblioteki parsera DJI (-5.6 MB)**:
   - Katalog `runtime/telemetry_parser/` stanowił zbędny duplikat modułu `runtime/common/telemetry_parser.cp314-win_amd64.pyd`.
8. **Skrypty pomocnicze i scratch (-3.3 MB)**:
   - Katalog `scratch/` z tymczasowymi skryptami debugowania.
9. **Logi, zrzuty i debug (-2.4 MB)**:
   - Pliki `.log`, `.tmp`, `.bak`, `.crash` oraz zrzuty wideo w `Video/`.
10. **Narzędzia debugowe (-1.1 MB)**:
    - Narzędzie `ltcdump.exe` w `runtime/common/`.
11. **Pamięć podręczna Pythona (`__pycache__`)**:
    - Usunięcie wszystkich plików `.pyc` przed pakowaniem dystrybucyjnym.

---

## 4. ARCHITEKTURA NOWEGO PAKIETU I SYSTEMU BUDOWANIA (FAZY 13, 14, 23)

Utworzono automatyczne, deterministyczne narzędzie pakujące allowlistowe:
- `tools/build_portable_release.py`
- `tools/build_portable_release.ps1`

### 4.1. Struktura katalogów pakietu produkcyjnego (256 plików)

```text
C:\_DEV\SportCamHUD-portable-clean\
├── SportCamHUD.py                     [Główny punkt wejścia GUI]
├── TeleMGP.py                         [Punkt wejścia CLI / headless export]
├── Start_SportCamHUD.cmd              [Launcher cmd dla Windows]
├── def_layout.json                    [Domyślny układ HUD]
├── telemetry_fit.py                   [Moduł parsera FIT dla telemetrii]
├── telemetry_gpx.py                   [Moduł parsera GPX dla telemetrii]
├── libmpv-2.dll                       [Biblioteka MPV do odtwarzania podglądu]
├── pyproject.toml                     [Metadane pakietu]
├── README.md                          [Dokumentacja podstawowa]
├── presets/                           [10 plików schematów JSON]
├── wzor/
│   └── rower_ico.png                  [Wzorzec graficzny wskaźnika nachylenia roweru]
├── src/                               [129 produkcyjnych modułów Python]
│   └── assets/icons/svg/              [81 ikon wektorowych SVG]
└── runtime/
    ├── portable_manifest.json         [Deterministyczny manifest SHA256 dla 256 plików]
    ├── common/                        [ffmpeg.exe, ffprobe.exe, telemetry_parser.pyd]
    ├── amd/bin/                       [telem_amd_native.dll, libwinpthread-1.dll]
    ├── intel/bin/                     [telem_intel_native.dll + 7 DLL FFmpeg]
    └── nvidia/bin/                    [README.txt - profil resolvera]
```

### 4.2. Hard Denylist Safety Gate

Skrypt budujący posiada wbudowaną blokadę bezpieczeństwa odrzucającą budowanie pakietu w przypadku wykrycia jakichkolwiek zabronionych wzorców:
- `Raporty/`, `tests/`, `scratch/`, `Video/`, `build/`, `.git/`, `src/native/`, `__pycache__/`
- `*.pdb`, `*.obj`, `*.exp`, `*.lib`, `*.ilk`, `*.map`, `*.log`, `*.tmp`, `*.bak`
- `*.fresh-backup`, `*.golden-*`, `*.pre_quant_candidate`, `*.zip`, `*.7z`, `*.rar`

---

## 5. WERYFIKACJA INTEGRALNOŚCI RUNTIME (FAZY 8, 9, 10, 11, 22)

### 5.1. Runtime Intel
- Plik: `runtime\intel\bin\telem_intel_native.dll`
- Rozmiar: 216 064 bajtów
- SHA256: `113abafbab0c877bc406692a4f60d287041d7e6307912a1b6e790d602888ba4b`
- Wymagane biblioteki zależne FFmpeg w `runtime\intel\bin\`:
  `avcodec-63.dll`, `avdevice-63.dll`, `avfilter-12.dll`, `avformat-63.dll`, `avutil-61.dll`, `swresample-7.dll`, `swscale-10.dll`.
- Wynik: **CLEAN_INTEL_QUANT_DLL_MATCH=YES**

### 5.2. Runtime AMD
- Plik: `runtime\amd\bin\telem_amd_native.dll`
- Rozmiar: 196 608 bajtów
- SHA256: `90be5af56bb56a73cdc161a0508b0d6a2c71987be44a565712c37aa5b5d66647`
- Zależność: `libwinpthread-1.dll`
- Wynik: **AMD_KNOWN_GOOD_MATCH=YES**, **AMD_RUNTIME_CONTRACT_PASS=YES**

### 5.3. Runtime NVIDIA
- Profil oraz parametry enkoderów NVENC weryfikowane statycznie (`resolve_nvidia_profile`, `resolve_nvenc_ffmpeg_params`).
- Wynik: **NVIDIA_RUNTIME_CONTRACT_PASS=YES**

### 5.4. Brak mieszania vendorów
- Weryfikacja strukturalna wykazała pełną separację:
  `CROSS_VENDOR_RUNTIME_MIXING=NO`.

---

## 6. WERYFIKACJA BRAKU ZEWNĘTRZNYCH ZALEŻNOŚCI (FAZY 16, 17)

Wykonano audyt importów modułów oraz ładowania zasobów (`sys.modules`, `os.walk`, uchwyty bibliotek DLL) podczas startu z katalogu `C:\_DEV\SportCamHUD-portable-clean`.
- Żaden moduł ani biblioteka nie zostały załadowane z `C:\_DEV\SportCamHUD-main-new`, `C:\_DEV\SportCamHUD-portable`, `C:\_DEV\SportCamHUD-intel`, dysku `Z:` ani lokalizacji deweloperskich.
- Wynik audytu: **EXTERNAL_APPLICATION_FILE_LOADS=0**.
- Test uruchomienia GUI:
  - `GUI_START_PASS=YES`
  - `NO_MISSING_MODULE=YES`
  - `NO_MISSING_ASSET=YES`
  - `NO_MISSING_DLL=YES`
  - Dostępność podglądu MPV: `_MPV_AVAILABLE=True`

---

## 7. TESTY FUNKCJONALNE I WYDAJNOŚCIOWE REAL-WORLD (FAZY 18–21)

Wszystkie testy wykonano na rzeczywistych plikach wideo (GoPro 4K HDR 10-bit + dane FIT/GPMF/DJI).

### 7.1. Intel AV1 Direct Export (Faza 18)
- Parametry: 1000 klatek, AV1 10-bit HDR, profil Intel Arc/Iris Xe, 40 Mbit/s, HUD Auto, Live Mux aktywny.
- Plik wyjściowy: `C:\GoPro\TO\clean_intel_direct_1000.mp4` (157 329 316 B).
- Statystyki telemetrii kwantyzatora Q:
  - `Q_cur` = 47
  - `Q_min` = 28
  - `Q_max` = 77
  - `Q_samples` = 1000
  - `Q_avg` = 49.666
- Live Mux:
  - `final_mp4_full_remux_count` = 0
  - `post_render_full_mux_seconds` = 0.0s
- Status: **INTEL_DIRECT_PASS=YES**, **INTEL_LIVE_Q_PASS=YES**, **INTEL_LIVE_MUX_PASS=YES**.

### 7.2. Intel AV1 Queue Export (Faza 19)
- Parametry: identyczne jak w teście Direct, uruchomione przez silnik kolejki zadań `ExportQueue`.
- Plik wyjściowy: `C:\GoPro\TO\clean_intel_queue_1000.mp4` (157 329 316 B).
- Wynik: Plik wyjściowy posiada **co do bajta identyczny rozmiar** jak w eksporcie Direct (157 329 316 bajtów), z zachowaniem identycznych parametrów kwantyzatora Q (`Q_avg=49.666`, `Q_min=28`, `Q_max=77`).
- Status: **INTEL_QUEUE_PASS=YES**, **QUEUE_Q_PASS=YES**, **QUEUE_FINAL_QUANT_RANGE_PASS=YES**.

### 7.3. Eksport GPMF (Faza 20)
- Parametry: 300 klatek z włączoną opcją `Dołącz oryginalny GPMF = ON`.
- Plik wyjściowy: `C:\GoPro\TO\clean_gpmf_test.mp4` (49 382 195 B).
- Analiza strumieni (`ffprobe`):
  - Strumień telemetrii obecny: `Stream #0:2: Data: bin_data (gpmd / 0x646D7067)`
  - Tag metadanych: `handler_name: GoPro MET`
- Status: **GPMF_EXPORT_PASS=YES**.

### 7.4. Telemetria DJI Action 6 (Faza 21)
- Weryfikacja parsera: `runtime/common/telemetry_parser.cp314-win_amd64.pyd` załadowany poprawnie przez `src/telemetry_dji.py`.
- Weryfikacja na rzeczywistych nagraniach: `C:\GoPro\DJI_20260928064217_0001_D.MP4` oraz `...0002_D.MP4`.
- Wykryto strumień metadanych `dji_djmd` oraz model kamery `OsmoAction6`.
- Status: **DJI_IMPORT_PASS=YES**, **DJI_TELEMETRY_OPEN_PASS=YES**.

---

## 8. WERYFIKACJA ARCHIWUM DYSTRYBUCYJNEGO I ROZPAKUJ-I-URUCHOM (FAZY 25, 26, 27)

### 8.1. Archiwum ZIP
- Ścieżka: `C:\_DEV\SportCamHUD-portable-clean.zip`
- Rozmiar: **322 832 187 bajtów (307.88 MB)**
- Zawartość: dokładnie 256 plików produkcyjnych (zgodnych co do jednego pliku z `portable_manifest.json`).
- Brak jakichkolwiek raportów, testów, plików `.pdb`, archiwów zagnieżdżonych ani plików tymczasowych (postawa w 100% Defender-friendly).

### 8.2. Test Extract-and-Run (`portable-clean-verify`)
- Archiwum ZIP zostało rozpakowane do nowego, czystego folderu:
  `C:\_DEV\SportCamHUD-portable-clean-verify` (czas ekstrakcji: 2.7 s).
- Bez jakiegokolwiek ręcznego kopiowania plików:
  1. Wykonano test uruchomienia aplikacji: **ZIP_EXTRACT_START_PASS=YES**.
  2. Wykonano test eksportu Intel AV1 10-bit HDR (300 klatek) do `C:\GoPro\TO\verify_intel_direct_300.mp4`:
     - Wydajność: **30.85 FPS**
     - Telemetria Q aktywna: `Q_avg=56.70`, `Q_min=40`, `Q_max=77`
     - Status: **ZIP_EXTRACT_INTEL_PASS=YES**.

---

## 9. PODSUMOWANIE BEZPIECZEŃSTWA GITA I STATUSU ZADAŃ (FAZA 28)

- Środowisko `C:\_DEV\SportCamHUD-portable` **nie zostało zmienione** i pozostaje nietkniętym punktem odniesienia.
- Wszystkie testy jednostkowe izolacji vendorów (`tests/test_vendor_runtime_isolation.py`) zakończone wynikiem pozytywnym: **12 passed**.
- Wszystkie testy enkodera Intel AV1 i Live Mux zakończone wynikiem pozytywnym: **13 passed**.
- Wszystkie testy kolejki eksportu zakończone wynikiem pozytywnym: **32 passed**.
- Wszystkie testy telemetrii DJI zakończone wynikiem pozytywnym: **6 passed, 1 skipped**.
- Nie stwierdzono żadnych nowych regresji: **NEW_REGRESSIONS=NONE**.

---

## 10. DECYZJA KOŃCOWA

Wszystkie bramki jakościowe, testy wydajnościowe, weryfikacje archiwum oraz kryteria redukcji rozmiaru pakietu zostały spełnione w 100%.

**FINAL_STATUS=PORTABLE_CLEANROOM_PASS**
