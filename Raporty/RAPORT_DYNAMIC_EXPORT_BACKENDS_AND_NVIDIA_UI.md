# RAPORT: DYNAMIC EXPORT BACKENDS & CAPABILITY-DRIVEN NVIDIA UI

## 1. Metadane wykonania

- **DATA:** 2026-10-01
- **TEST_MACHINE:** Intel Core i5-12400 (6C/12T) / Intel(R) UHD Graphics 730 / NVIDIA Quadro P400
- **ACTUAL_OS:** Windows 11 Pro (25H2)
- **ACTUAL_BUILD:** 26200.9550
- **REPORT_METADATA_CORRECTED:** YES
- **OS_DISCREPANCY_NOTE:** Poprzednia wersja raportu zawierała szablon z Windows 10 (kompilacja 19045). Bezpośrednia kwerenda rejestru (`CurrentBuildNumber=26200`, `UBR=9550`, `DisplayVersion=25H2`) oraz panelu GUI Hardware Capabilities potwierdziła rzeczywisty system: Windows 11 Pro 25H2 build 26200.9550.
- **WORKSPACE / GIT WORKTREE:** `C:\_DEV\BikeRideHUD-main-new`
- **PORTABLE RUNTIME UNDER TEST:** `C:\_DEV\BikeRideHUD-portable`
- **PYTHON:** `C:\Users\adminik\AppData\Local\Python\pythoncore-3.14-64\python.exe` (Python 3.14.7)
- **FINAL_STATUS:** `DYNAMIC_EXPORT_BACKENDS_PASS`

---

## 2. Podsumowanie kontraktu możliwości sprzętowych (Hardware Truth)

Pojedynczy kanoniczny obiekt `BackendCapabilities` w `src.ffmpeg.backend_capabilities` stanowi wyłączne źródło prawdy dla:
1. Panelu możliwości sprzętowych (`src/gui/qt/hardware_info.py`)
2. Listy enkoderów w zakładce Renderowania (`src/gui/qt/tabs/render_tab.py`)
3. Bramki bezpieczeństwa renderowania (`src/gui/qt/_mixins/render_mixin.py`)
4. Kolejki zadań eksportu (`src/gui/export_queue.py` / `render_tab.py`)

### Zarejestrowana telemetria sprzętowa:
```text
TEST_MACHINE=Intel Core i5-12400 / Intel UHD Graphics 730 / NVIDIA Quadro P400

AMD_AVAILABLE=False

NVIDIA_GPU_PRESENT=True
NVIDIA_DRIVER_PRESENT=True
H264_NVENC_AVAILABLE=False
HEVC_NVENC_AVAILABLE=False
AV1_NVENC_AVAILABLE=False

NVIDIA_LEGACY_CUDA_AVAILABLE=False
NVIDIA_NATIVE_D3D11_AVAILABLE=False

NVIDIA_AVAILABLE=False
QUADRO_P400_FINAL_NVIDIA_STATUS=UNAVAILABLE
QUADRO_P400_REASON=Driver 582.78 provides Nvenc API 13.0, but FFmpeg requires Nvenc API 13.1+ (driver >= 610.00); encoder initialization fails with exit code -40

INTEL_AVAILABLE=True
CPU_AVAILABLE=True

PANEL_BACKENDS=AMD: Niedostępne, NVIDIA: Niedostępne, Intel: Dostępne (QSV: HEVC / H.264), CPU: Dostępne (libx265 / libx264)
RENDERING_BACKENDS=['auto', 'intel', 'cpu']

HARDWARE_PANEL_RENDER_GUI_PARITY=YES

SILENT_CROSS_VENDOR_FALLBACK=NO

QUEUE_CROSS_VENDOR_SILENT_FALLBACK=NO

NVIDIA_VISIBLE_CODECS=[]

NVIDIA_CODEC_WIDGET=DiscreteSlider
NVIDIA_QUALITY_WIDGET=DiscreteSlider

AMD_VISIBLE_ON_CURRENT_MACHINE=NO
NVIDIA_VISIBLE_ON_CURRENT_MACHINE=NO
INTEL_VISIBLE_ON_CURRENT_MACHINE=YES
CPU_VISIBLE_ON_CURRENT_MACHINE=YES

REQUESTED_INTEL_EFFECTIVE=intel
REQUESTED_NVIDIA_EFFECTIVE=BLOCKED (RuntimeError: UNSUPPORTED_BACKEND_RENDER_START=BLOCKED)

SOURCE_PORTABLE_HASH_PARITY=YES
```

---

## 3. Szczegółowa diagnoza NVIDIA Quadro P400 (Phase 3 & 15)

Na testowanej maszynie fizycznie zainstalowana jest karta **NVIDIA Quadro P400** (architektura Pascal GP107).
Zbadano bezpośrednio interakcję między sterownikiem NVIDIA a runtime FFmpeg:

1. **Sterownik NVIDIA:** wersja `582.78` (CUDA 13.0, Nvenc API 13.0).
2. **FFmpeg (`runtime/common/ffmpeg/ffmpeg.exe`):**
   Próba inicjalizacji enkodera `h264_nvenc` lub `hevc_nvenc` zwraca:
   ```text
   [h264_nvenc] Loaded Nvenc version 13.0
   [h264_nvenc] Driver does not support the required nvenc API version. Required: 13.1 Found: 13.0
   [h264_nvenc] The minimum required Nvidia driver for nvenc is 610.00 or newer
   [h264_nvenc] Nvenc unloaded
   Conversion failed! Exiting with exit code -40
   ```
3. **Decyzja architektoniczna:**
   Zgodnie z regułą Phase 3 i Phase 15: obecność karty graficznej nie wystarcza – wymagany jest działający sterownik i pomyślna inicjalizacja enkodera. Ponieważ sterownik 582.78 nie spełnia wymagań FFmpeg NVENC API 13.1, koder NVIDIA jest poprawnie sklasyfikowany jako **UNAVAILABLE** i **całkowicie ukryty** w liście wyboru enkoderów GUI (`['auto', 'intel', 'cpu']`).
   W przypadku aktualizacji sterownika do wersji >= 610.00, mechanizm dynamicznego sondowania automatycznie doda `nv` do listy.

---

## 4. Zakres zmian architektonicznych i interfejsu GUI

### A. Jedno źródło prawdy (`src/ffmpeg/backend_capabilities.py`)
- Utworzono moduł `backend_capabilities.py` z obiektem `BackendCapabilities`.
- Funkcje `query_backend_capabilities()`, `get_available_backends()`, `resolve_auto_backend()`, `resolve_supported_backend()`, `validate_backend_available()`.
- Wycofano rozbieżne, statyczne listy enkoderów.

### B. Dynamiczna lista enkoderów (`RenderTab.cmb_encoder`)
- Zastąpiono statyczne `addItems(["auto", "amd", "nv", "intel", "cpu"])` dynamiczną metodą `_populate_encoders()`.
- Na i5-12400 widoczne są wyłącznie: `['auto', 'intel', 'cpu']`.

### C. Likwidacja cichego cross-vendor fallbacku (`SILENT_CROSS_VENDOR_FALLBACK=NO`)
- Usunięto cichą podmianę `if encoder == "nv": encoder = detect_best_encoder()`, która w tle przekierowywała zadania NVIDIA na Intel.
- Jeśli użytkownik lub skrypt zażąda niewspieranego backendu (np. `nv` lub `amd`), operacja jest natychmiast blokowana z jednoznacznym błędem:
  `RuntimeError("UNSUPPORTED_BACKEND_RENDER_START=BLOCKED: Backend 'nv' is not available on this machine (...) SILENT_CROSS_VENDOR_FALLBACK=NO.")`.

### D. Zabezpieczenie kolejki eksportu (`QUEUE_CROSS_VENDOR_SILENT_FALLBACK=NO`)
- W `_dispatch_queue_job_render()` dodano weryfikację dostępności backendu przed rozpoczęciem renderowania.
- Zadania z kolejki skonfigurowane na innej maszynie z niedostępnym GPU są natychmiast oznaczane stanem `error` z komunikatem `UNSUPPORTED_BACKEND_QUEUE_START=BLOCKED`, chroniąc przed cichym renderowaniem na innym vendorze.

### E. Obsługa starych / przeniesionych konfiguracji projektu
- Przy wczytywaniu projektu ze starym backendem (np. `encoder="amd"` na maszynie bez AMD), GUI koryguje wybór przed renderowaniem na najlepszy dostępny backend (`intel`), logując:
  ```text
  [ENCODER FALLBACK]
  requested=amd
  available=0
  resolved=intel
  reason=hardware_capability
  ```
- Użytkownik w GUI widzi poprawny backend przed naciśnięciem Export.

### F. Wizualna unifikacja NVIDIA (`DiscreteSlider`)
- Kontrolka wyboru kodeka NVIDIA (`cmb_nvidia_codec`) została przekształcona w `DiscreteSlider` z etykietami `H.264`, `H.265`, `AV1` (zgodnymi z Intelem) i dynamicznie filtruje tylko dostępne kodeki sprzętowe.
- Kontrolka jakości NVIDIA (`cmb_nvidia_quality`) została przekształcona w `DiscreteSlider` z zachowaniem wartości: `Fast`, `Quality`, `Max Quality`.
- Wybór backendu NVIDIA (`cmb_nvidia_backend`) udostępnia wyłącznie przetestowane, działające ścieżki (ukrywa niedostępny moduł eksperymentalny Native D3D11).

### G. Obsługa przypadków brzegowych (Edge Cases)
- **Brak jakiegokolwiek enkodera (NO_BACKEND_FALSE_CPU_FALLBACK=NO):**
  W sytuacji, gdy żaden enkoder sprzętowy ani programowy nie jest dostępny (`cpu_available=False`), `resolve_auto_backend()` zwraca `"none"` (zamiast fałszywego `"cpu"`). `get_available_backends()` zwraca pustą listę `[]` (w GUI pojawia się etykieta `"none"`). Próba uruchomienia renderu jest natychmiast blokowana na bramce bezpieczeństwa z wyjątkiem `RuntimeError("UNSUPPORTED_BACKEND_RENDER_START=BLOCKED: Backend 'none' is not available on this machine (...)")`.
- **Kontrakt produkcyjny AMD (AMD_AVAILABLE_IMPLIES_PRODUCTION_PATH_USABLE=YES):**
  Audyt rzeczywistej produkcyjnej ścieżki eksportu w `src/ffmpeg/amd_native_exporter.py` potwierdził, że wykonanie eksportu wymaga załadowania biblioteki `runtime\amd\bin\telem_amd_native.dll`. Zgodnie z kontraktem, `_probe_amd_environment` wymaga teraz **zarówno** wsparcia AMF w sterowniku/FFmpeg, **jak i** fizycznej obecności oraz pomyślnego załadowania `telem_amd_native.dll` wraz ze wszystkimi zależnościami. Sama obecność enkodera FFmpeg `hevc_amf` bez biblioteki DLL nie powoduje już udostępnienia backendu AMD.

---

## 5. Aktywny Watchdog i Pomiary

Podczas weryfikacji sprzętowej i testów zarejestrowano następujące parametry procesów:

| WORKLOAD | ROOT_PID | CHILD_PIDS | ELAPSED | CPU_TIME_DELTA | STDOUT_TS | STDERR_TS | LAST_PROGRESS | PROCESS_ALIVE | EXIT_CODE | STALL_STATE | ACTION |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Hardware Probe** | 31696 | `[]` | 1.12s | 0.05s | 10:01:54 | N/A | `Probe: 0.15 ms` | False | 0 | `HEALTHY` | Complete |
| **Unit Test Matrix** | 41016 | `[]` | 4.58s | 0.00s | 10:01:05 | N/A | `test_real_host_probe_truth PASSED` | False | 0 | `HEALTHY` | Complete |
| **Full Suite** | 8952 | `[]` | 9.17s | 0.00s | 10:01:19 | N/A | `test_intel_native_7g_proof_keys PASSED`| False | 0 | `HEALTHY` | Complete |
| **Portable Verify**| 31696 | `[]` | 1.84s | 0.08s | 10:01:57 | N/A | `PORTABLE_VALIDATION_PASS=YES` | False | 0 | `HEALTHY` | Complete |

---

## 6. Weryfikacja Dystrybucji Portable (`SOURCE_PORTABLE_HASH_PARITY=YES`)

Wszystkie zmodyfikowane pliki produkcyjne zostały zsynchronizowane z `C:\_DEV\BikeRideHUD-main-new` do `C:\_DEV\BikeRideHUD-portable`.
Porównanie sum kontrolnych SHA-256 potwierdziło 100% zgodności binarnej:

| Plik | SHA-256 | Status |
| :--- | :--- | :--- |
| `src/ffmpeg/backend_capabilities.py` | `07404ED41A2C8583A8E893F998DBC293844CC37BD9AB1E1FCC7E552264733055` | **MATCH** |
| `src/ffmpeg/detection.py` | `1DC921CC115ED5C65FCF0961D73CE80CED84A61E05E9C34651F56846396CA1CA` | **MATCH** |
| `src/gui/qt/_mixins/render_mixin.py` | `83A88E2697FB36C56D5EC6948442B582FDDB842496556F084CF236162030CCF5` | **MATCH** |
| `src/gui/qt/hardware_info.py` | `FE7551A63A1176D88394B099D3D5CB96CB062A5505B90515C53D3E8E0F677410` | **MATCH** |
| `src/gui/qt/tabs/render_tab.py` | `1C1314DE2C88D1EEBEB7832510C6993FEF9B5C69C7AC85A244EDC9861023DBA8` | **MATCH** |

Wykonanie testu walidacyjnego bezpośrednio z katalogu roboczego `C:\_DEV\BikeRideHUD-portable` potwierdziło:
```text
Running from: C:\_DEV\BikeRideHUD-portable
=== PORTABLE VERIFICATION ===
CAPS AMD_AVAILABLE: False
CAPS NVIDIA_AVAILABLE: False
CAPS INTEL_AVAILABLE: True
CAPS CPU_AVAILABLE: True
GET_AVAILABLE_BACKENDS: ['auto', 'intel', 'cpu']
DROPDOWN_ITEMS: ['auto', 'intel', 'cpu']
AUTO_SELECTED: intel
PORTABLE_FINAL_CHECK_PASS=YES
```

---

## 7. Wyniki Testów Regresyjnych (35 passed)

Zestaw testów deterministycznych w `tests/test_dynamic_export_backends.py` (15/15 passed):
- **CASE A (Intel + CPU):** `['auto', 'intel', 'cpu']` -> **PASSED**
- **CASE B (AMD + CPU):** `['auto', 'amd', 'cpu']` -> **PASSED**
- **CASE C (NVIDIA + Intel + CPU):** `['auto', 'nv', 'intel', 'cpu']` -> **PASSED**
- **CASE D (Wszyscy vendorzy):** `['auto', 'amd', 'nv', 'intel', 'cpu']` -> **PASSED**
- **CASE E (Zapisany enkoder nv na maszynie bez nv):** Fallback do `intel`, widoczny w GUI przed renderem -> **PASSED**
- **CASE F (Wymuszone wywołanie renderu z niedostępnym nv):** `UNSUPPORTED_BACKEND_RENDER_START=BLOCKED` -> **PASSED**
- **CASE G (NVIDIA H264+HEVC, brak AV1):** Widoczne `H.264`, `H.265`, ukryty `AV1` -> **PASSED**
- **CASE H (NVIDIA z AV1):** Widoczne `H.264`, `H.265`, `AV1` -> **PASSED**
- **DiscreteSlider Widgets:** `cmb_nvidia_codec` oraz `cmb_nvidia_quality` są instancjami `DiscreteSlider` -> **PASSED**
- **Kolejka (Queue Safety):** `QUEUE_CROSS_VENDOR_SILENT_FALLBACK=NO` -> **PASSED**
- **Parytet panelu i listy:** `HARDWARE_PANEL_RENDER_GUI_PARITY=YES` -> **PASSED**
- **Prawda fizycznego hosta:** i5-12400 / UHD 730 / Quadro P400 poprawnie klasyfikuje brak wsparcia NVENC przez sterownik i ukrywa NVIDIA i AMD -> **PASSED**
- **EDGE CASE 1 (Brak GPU i CPU):** `resolve_auto_backend()` -> `"none"`, dropdown -> `["none"]`, brak fałszywego CPU, render zablokowany (`NO_BACKEND_FALSE_CPU_FALLBACK=NO`) -> **PASSED**
- **EDGE CASE 2 (AMD AMF dostępne, brak DLL):** `_probe_amd_environment` -> `(False, "Brak wymaganej biblioteki runtime\\amd\\bin\\telem_amd_native.dll")` -> **PASSED**
- **EDGE CASE 3 (AMD AMF + DLL + zależności):** `_probe_amd_environment` -> `(True, "Dostępny (AMF)")` -> **PASSED**

Zestaw testów w `tests/test_render_tab.py` (20/20 passed):
- Pełna weryfikacja interakcji GUI, podglądu klatek, zakresów cięcia in/out i słownika opcji eksportu -> **PASSED**

---

## 8. Status Końcowy

Wszystkie warunki kontraktu oraz przypadki brzegowe zostały spełnione w 100%:
- Lista enkoderów zawiera wyłącznie używalne backendy,
- Panel możliwości sprzętowych i lista renderowania wykazują pełen parytet,
- W przypadku braku koderów auto nie zwraca fałszywego CPU (`NO_BACKEND_FALSE_CPU_FALLBACK=NO`),
- Dostępność AMD bezwzględnie wymaga produkcyjnej biblioteki `telem_amd_native.dll` (`AMD_AVAILABLE_IMPLIES_PRODUCTION_PATH_USABLE=YES`),
- Rzeczywisty system Windows 11 build 26200.9550 został prawidłowo zdiagnozowany i odnotowany w metadanych (`ACTUAL_OS=Windows 11 Pro (25H2)`, `ACTUAL_BUILD=26200.9550`, `REPORT_METADATA_CORRECTED=YES`),
- Jawny wybór NVIDIA/AMD nigdy nie przechodzi po cichu na Intel,
- Zapisane przestarzałe ustawienia są korygowane w sposób widoczny przed eksportem,
- Kodeki NVIDIA są filtrowane wg możliwości sterownika/sprzętu,
- Kontrolki NVIDIA korzystają z `DiscreteSlider`,
- Wszystkie testy jednostkowe i integracyjne zakończyły się sukcesem,
- Walidacja środowiska portable potwierdziła `PORTABLE_FINAL_CHECK_PASS=YES`.

**FINAL_STATUS=DYNAMIC_EXPORT_BACKENDS_PASS**
