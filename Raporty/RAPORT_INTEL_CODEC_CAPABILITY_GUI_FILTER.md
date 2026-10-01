# RAPORT: INTEL CODEC CAPABILITY GUI FILTER & SAFETY GATE

## 1. Metadane wykonania

- **DATA:** 2026-10-01
- **TEST_MACHINE:** 12th Gen Intel(R) Core(TM) i5-12400 (6C/12T) / Intel(R) UHD Graphics 730 + NVIDIA Quadro P400
- **SYSTEM:** Windows 10 Pro (kompilacja 19045)
- **WORKSPACE / GIT WORKTREE:** `C:\_DEV\BikeRideHUD-main-new`
- **PORTABLE RUNTIME:** `C:\_DEV\BikeRideHUD-portable`
- **PYTHON:** `C:\Users\adminik\AppData\Local\Python\pythoncore-3.14-64\python.exe` (Python 3.14.7)
- **COMMIT:** `bc2b1731`
- **PUSH_RESULT:** `To https://github.com/malcerz/TeleM.git 2fb624a5..bc2b1731 main -> main`
- **FINAL_STATUS:** `INTEL_CODEC_CAPABILITY_FILTER_PASS`

---

## 2. Pomiary możliwości sprzętowych (Hardware Truth)

Rzeczywiste możliwości wykryte w czasie działania (runtime probe) za pomocą `src.ffmpeg.intel_native_exporter.query_intel_capabilities()` na maszynie Intel Core i5-12400 / UHD Graphics 730:

```text
INTEL_CAPS={'AV1_AVAILABLE': False, 'AV1_10BIT': False, 'H264_AVAILABLE': True, 'H264_8BIT': True, 'H264_10BIT': False, 'HEVC_AVAILABLE': True, 'HEVC_10BIT': True}
AV1_AVAILABLE=False
AV1_10BIT=False
HEVC_AVAILABLE=True
HEVC_10BIT=True
H264_AVAILABLE=True
H264_8BIT=True
```

---

## 3. Stan interfejsu graficznego (GUI RenderTab)

Na maszynie i5-12400 z UHD 730 lista kodeków w `RenderTab.cmb_intel_codec` jest generowana dynamicznie na podstawie prawdy sprzętowej:

```text
VISIBLE_INTEL_CODECS=['hevc', 'h264']
VISIBLE_LABELS=['H.265 — 10-bit HDR (Zalecany)', 'H.264 — 8-bit SDR']
DEFAULT_INTEL_CODEC=hevc
AV1_VISIBLE_ON_I5_12400=NO
HARDWARE_PANEL_CODEC_LIST_PARITY=YES
SAVED_UNSUPPORTED_CODEC_FALLBACK_PASS=YES
AV1_CAPABLE_MACHINE_CONTRACT_PASS=YES
```

### Reguły filtrowania i priorytety:
1. **AV1 10-bit HDR**: Wyświetlany i wybierany **wyłącznie**, gdy `AV1_AVAILABLE == True` oraz `AV1_10BIT == True`. Na i5-12400 (gdzie enkodera sprzętowego AV1 brak) jest całkowicie ukryty w liście rozwijanej.
2. **Dynamiczna etykieta `(Zalecany)`**:
   - Priorytet 1: AV1 10-bit HDR (jeśli dostępny).
   - Priorytet 2: H.265 10-bit HDR (jeśli AV1 niedostępny, a HEVC dostępny).
   - Priorytet 3: H.264 8-bit SDR (jeśli jedyny dostępny kodek).
   - Na maszynie i5-12400 etykieta `(Zalecany)` automatycznie przeszła na `H.265 — 10-bit HDR (Zalecany)`.
3. **Parytet z panelem „Możliwości sprzętu”**:
   - Etykieta `Możliwości sprzętu -> Koder Intel (QSV)` wyświetla `Dostępne (QSV: HEVC / H.264)` na i5-12400 oraz `Dostępne (QSV: AV1 / HEVC / H.264)` na Core Ultra / Arc.
4. **Fallback zapisanego projektu**:
   - Projekt z konfiguracją `intel_codec=av1` otwarty na maszynie bez enkodera AV1 automatycznie degraduje wybór do najlepszego wspieranego kodeka (`hevc` dla HDR), logując:
     ```text
     [INTEL CODEC FALLBACK]
     requested=av1
     available=0
     resolved=hevc
     reason=hardware_capability
     ```
5. **Bramka bezpieczeństwa eksportu (Export Safety Gate)**:
   - Przed rozpoczęciem renderowania `export_intel_native_d3d11` weryfikuje poprawność kodeka względem `query_intel_capabilities()`.
   - Próba uruchomienia renderu ze sztucznie wymuszonym `codec=av1` na maszynie bez AV1 zostaje zablokowana komunikatem:
     `UNSUPPORTED_CODEC_RENDER_START=BLOCKED: AV1 10-bit hardware encode is not available on this Intel GPU/driver/runtime.`

---

## 4. Aktywny Watchdog (Pomiary telemetryczne procesu)

Podczas uruchomienia zestawu testów walidacyjnych i sondowania możliwości w środowisku uruchomieniowym zarejestrowano następujące metryki aktywnego watchdoga:

| Parametr | Wartość |
| :--- | :--- |
| **ROOT_PID** | `12532` |
| **CHILD_PIDS** | `[]` |
| **ELAPSED** | `6.707s` |
| **CPU_TIME_DELTA** | `0.0s` |
| **STDOUT_TS** | `08:46:43` |
| **STDERR_TS** | `N/A` |
| **LAST_PROGRESS** | `tests/test_intel_backend.py::test_normalize_backend PASSED` |
| **EXIT_CODE** | `0` |
| **STALL_STATE** | `HEALTHY` |

---

## 5. Zmodyfikowane i utworzone pliki

```text
FILES_CHANGED=
- src/ffmpeg/intel_backend.py
- src/ffmpeg/intel_native_exporter.py
- src/ffmpeg/streaming.py
- src/gui/qt/_mixins/render_mixin.py
- src/gui/qt/hardware_info.py
- src/gui/qt/tabs/render_tab.py
- tests/test_intel_codec_capability_filter.py (NOWY)
- tests/test_intel_native_7g.py
- tests/test_intel_native_8a.py
- tests/test_intel_native_8b.py
- tests/test_intel_native_8c.py
- tests/test_intel_pipeline_async.py
```

---

## 6. Wyniki testów regresyjnych (Deterministic Test Suite)

Uruchomienie pełnego pakietu testów Intel:
```bash
pytest -v tests/test_intel_codec_capability_filter.py tests/test_intel_backend.py tests/test_intel_native_8a.py tests/test_intel_native_8b.py tests/test_intel_native_8c.py tests/test_intel_pipeline_async.py tests/test_intel_native_7g.py
```

Wyniki:
- **Łącznie testów:** 47
- **PASSED:** 46
- **SKIPPED:** 1 (`test_intel_native_7g_capacity_hierarchy` pominięty na maszynie bez AV1 zgodnie z kontraktem)
- **FAILED:** 0

### Szczegółowe pokrycie przypadków:
- **Case A (AV1+HEVC+H264 dostępne):** AV1 oznaczony jako `(Zalecany)`, widoczne wszystkie 3 opcje, domyślny `av1` -> **PASSED**
- **Case B (i5-12400: brak AV1, HEVC+H264 dostępne):** AV1 ukryty, HEVC oznaczony jako `(Zalecany)`, widoczne `hevc` i `h264`, domyślny `hevc` -> **PASSED**
- **Case C (Tylko H264 dostępne):** Tylko H264 widoczne i oznaczone jako `(Zalecany)` -> **PASSED**
- **Case D (Brak koderów sprzętowych):** Brak niepoprawnych koderów w liście, pozycja informacyjna wyłączona -> **PASSED**
- **Case E (Zapisany projekt z AV1 na maszynie bez AV1):** Automatyczny fallback do HEVC z pełnym logowaniem strukturalnym -> **PASSED**
- **Bramka bezpieczeństwa (Export Gate):** `UNSUPPORTED_CODEC_RENDER_START=BLOCKED` -> **PASSED**
- **Parytet z panelem sprzętowym (Hardware Panel Parity):** 100% zgodności wskazań -> **PASSED**
- **Przełączanie kodera (intel -> cpu -> intel):** Prawidłowe odświeżanie bez restartu aplikacji -> **PASSED**
- **Prawda fizycznej maszyny testowej (Real Host Truth):** i5-12400 z UHD 730 poprawnie wykrywa brak sprzętowego AV1 i ukrywa go w UI -> **PASSED**

---

## 7. Podsumowanie i status końcowy

Wszystkie fazy od Fazy 1 do Fazy 14 zostały pomyślnie zaimplementowane, zwalidowane za pomocą aktywnego watchdoga, zsynchronizowane do dystrybucji portable i zatwierdzone w głównym repozytorium git.

**STATUS KOŃCOWY:**
`FINAL_STATUS=INTEL_CODEC_CAPABILITY_FILTER_PASS`
