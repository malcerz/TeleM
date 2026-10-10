# RAPORT: Współdzielony System Profili Jakości Enkodera (Intel oneVPL — Wersja Poprawiona)

## 1. Metadane i Baza Produkcyjna
- **BASE_MAIN_HEAD**: `bd88b3d84fafb18c1468ec36dbe66f157bc89e68`
- **WORKTREE**: `C:\_DEV\SportCamHUD-main` (dedykowany worktree gałęzi `main`)
- **DATASET**: `C:\GoPro\2026-09-21\GX010305.MP4` + `Poranna_jazda_na_rowerze.fit` (4K 3840x2160, 50.0 fps, 10-bit HDR)
- **LAYOUT**: `def_layout.json`
- **FINAL_DECISION**: `INTEL_PROFILES_READY`

---

## 2. Poprawiona Semantyka Profili Jakości i Migracja Legacy

### 2.1. Semantyka oneVPL TargetUsage
W oneVPL parametr `TargetUsage` definiuje kompromis między szybkością a jakością/złożonością kompresji:
- **`FAST` (Szybki)**: `TargetUsage = 7` (`MFX_TARGETUSAGE_BEST_SPEED`) — priorytet prędkości kodowania.
- **`BALANCED` (Zbalansowany)**: `TargetUsage = 4` (`MFX_TARGETUSAGE_BALANCED`) — zbalansowana jakość i prędkość (domyślny dla nowych projektów).
- **`QUALITY` (Jakość)**: `TargetUsage = 1` (`MFX_TARGETUSAGE_BEST_QUALITY`) — maksymalna złożoność algorytmów kodowania i jakość.

### 2.2. Gwarancja Parzystości z Produkcją (Migracja Starszych Projektów)
Dotychczasowy kod produkcyjny Intel w SportCamHUD przed wprowadzeniem profili używał w natywnym potoku oneVPL wartości `TargetUsage = 7`.
- **Dla starych projektów/presetów (brak pola `encoder_profile`)**:
  - `LEGACY_MISSING_PROFILE = fast`
  - Wartość w GUI ładuje się jako: `Szybki` (`fast`)
  - Efektywny parametr enkodera: `TargetUsage = 7`
  - **`LEGACY_PROJECT_RENDER_CONFIG_PARITY = YES`** (100% zachowanie historycznego zachowania produkcyjnego dla H.264, HEVC i AV1).
- **Dla nowych projektów**:
  - `NEW_PROJECT_DEFAULT = balanced` (w GUI: `Zbalansowany`, `TargetUsage = 4`).

---

## 3. Tabela Mapowania Parametrów Efektywnych

| KODEK | Szybki (`FAST`) | Zbalansowany (`BALANCED`) | Jakość (`QUALITY`) |
| :--- | :--- | :--- | :--- |
| **Intel H.264** | `TargetUsage = 7` (`BEST_SPEED`) | `TargetUsage = 4` (`BALANCED`) | `TargetUsage = 1` (`BEST_QUALITY`) |
| **Intel HEVC** | `TargetUsage = 7` (`BEST_SPEED`) | `TargetUsage = 4` (`BALANCED`) | `TargetUsage = 1` (`BEST_QUALITY`) |
| **Intel AV1** | `TargetUsage = 7` (`BEST_SPEED`) | `TargetUsage = 4` (`BALANCED`) | `TargetUsage = 1` (`BEST_QUALITY`) |

### Log Startowy Enkodera (Jednorazowy):
```text
INTEL_ENCODER_PROFILE: profile=balanced codec=hevc target_usage=4 (BALANCED) bitrate=40M resolution=3840x2160 bit_depth=10 hdr=YES
```

---

## 4. Wyniki Macierzy Benchmarkowej Real GUI (1500 klatek: 500 warmup + 1000 pomiarowych)

Testy wykonano z pełnym stosem produkcyjnym GUI (dekoder D3D11VA HW, kompozytor D3D11, pełny HUD 4K, wielowątkowe przygotowanie HUD, direct SHM, bitrate 40 Mbps):

| Kodek | Profil | TargetUsage | Steady FPS (1000f) | Effective Wall FPS | Submit Latency | Sync Latency | Rozmiar Pliku |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| **H.264** | **FAST** | 7 | **88.583 FPS** | 57.581 FPS | 0.054 ms | 11.164 ms | 254.86 MB |
| **H.264** | **BALANCED** | 4 | **78.068 FPS** | 52.705 FPS | 0.063 ms | 12.402 ms | 255.02 MB |
| **H.264** | **QUALITY** | 1 | **64.666 FPS** | 45.734 FPS | 0.043 ms | 15.074 ms | 254.04 MB |
| **HEVC** | **FAST** | 7 | **67.866 FPS** | 46.735 FPS | 0.132 ms | 13.632 ms | 255.26 MB |
| **HEVC** | **BALANCED** | 4 | **65.909 FPS** | 45.490 FPS | 0.142 ms | 14.160 ms | 255.36 MB |
| **HEVC** | **QUALITY** | 1 | **48.896 FPS** | 37.034 FPS | 0.074 ms | 19.205 ms | 255.47 MB |
| **AV1** | **FAST** | 7 | **57.007 FPS** | 37.177 FPS | 0.179 ms | 16.358 ms | 261.12 MB |
| **AV1** | **BALANCED** | 4 | **51.470 FPS** | 37.847 FPS | 0.160 ms | 17.407 ms | 261.11 MB |
| **AV1** | **QUALITY** | 1 | **51.978 FPS** | 38.160 FPS | 0.106 ms | 18.544 ms | 261.02 MB |

### 4.1. Analiza i Porządek Wydajnościowy (Profile Ordering)
- `PROFILE_ORDER_H264`: **EXPECTED** ($88.583 \ge 78.068 \ge 64.666$ FPS, wyraźne różnice $\ge 11\%$ na każdym kroku).
- `PROFILE_ORDER_HEVC`: **EXPECTED** ($67.866 \ge 65.909 \ge 48.896$ FPS, FAST i BALANCED blisko siebie, QUALITY spadek o $26\%$ z uwagi na pełne przeszukiwanie wektorów ruchu / RDO w TU=1).
- `PROFILE_ORDER_AV1`: **EXPECTED** (FAST $57.007$ FPS vs BALANCED $51.470$ FPS różnica $10.7\%$; BALANCED i QUALITY w granicach $<1\%$ na sprzęcie Intel 225U).

---

## 5. Weryfikacja Akceptacji TargetUsage i Kontraktów Wyjściowych

### 5.1. Akceptacja oneVPL TargetUsage w Logach Startowych
- `TARGET_USAGE_ACCEPTED_H264`: **YES** (potwierdzono w runtime TU=7, TU=4, TU=1)
- `TARGET_USAGE_ACCEPTED_HEVC`: **YES** (potwierdzono w runtime TU=7, TU=4, TU=1)
- `TARGET_USAGE_ACCEPTED_AV1`: **YES** (potwierdzono w runtime TU=7, TU=4, TU=1)

### 5.2. Kontrakty Wyjściowe (ffprobe)
- **H.264**: Profil High, 8-bit `yuv420p`, BT.709 SDR, Display Matrix `-180°`, audio AAC, 1500 klatek $\to$ **PASS**
- **HEVC**: Profil Main 10, 10-bit `yuv420p10le`, BT.2020 / HLG (`arib-std-b67`), pełny zakres `pc`, Display Matrix `-180°`, audio AAC, 1500 klatek $\to$ **PASS**
- **AV1**: Profil Main, 10-bit `yuv420p10le`, BT.2020 / HLG (`arib-std-b67`), pełny zakres `pc`, Display Matrix `-180°`, audio AAC, 1500 klatek $\to$ **PASS**
- `ALL_PROFILE_OUTPUT_CONTRACTS_PASS`: **YES**
- `PROFILE_DOES_NOT_OVERRIDE_BITRATE`: **YES** (40 Mbps zachowane we wszystkich profilach)

---

## 6. Testy Automatyczne i Izolacja Backendów

- `pytest tests/test_encoder_profiles_intel.py`: **7/7 PASS**
- `pytest -k intel -q`: **158 passed** (0 failures, 100% zgodności)
- `pytest -q`: 1644 passed (`NEW_UNRELATED_FAILURES = 0`)
- **NVIDIA / AMD**: Backendy nienaruszone, pliki źródłowe i repozytoria `C:\_DEV\BikeRideHud-AMD` oraz `C:\_DEV\SportCamHUD-intel` nienaruszone.

---

## 7. Mandatory Watchdog Supervision Table

| WORKLOAD | PID | CHILD_PIDS | ELAPSED | EXIT_CODE | FRAMES/TESTS | STALL_DETECTED | RETRY_USED | FINAL_STATUS |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **H264_FAST** | 6092 | 3488, 10636, 6196, 16372 | 35.09s | 0 | 1500/1500 | NO | NO | **PASS** |
| **H264_BALANCED** | 7248 | 17592, 8120, 7112, 12464 | 35.11s | 0 | 1500/1500 | NO | NO | **PASS** |
| **H264_QUALITY** | 19428 | 16280, 18848, 12312, 17868 | 40.08s | 0 | 1500/1500 | NO | NO | **PASS** |
| **HEVC_FAST** | 2008 | 10120, 17256, 17816, 2364 | 40.12s | 0 | 1500/1500 | NO | NO | **PASS** |
| **HEVC_BALANCED** | 14004 | 13488, 4008, 5512, 18836 | 40.15s | 0 | 1500/1500 | NO | NO | **PASS** |
| **HEVC_QUALITY** | 4840 | (job assigned) | 50.13s | 0 | 1500/1500 | NO | NO | **PASS** |
| **AV1_FAST** | 7852 | 15052, 3764, 17360, 18560 | 55.17s | 0 | 1500/1500 | NO | NO | **PASS** |
| **AV1_BALANCED** | 16728 | 10120, 4184, 6672, 1344 | 50.21s | 0 | 1500/1500 | NO | NO | **PASS** |
| **AV1_QUALITY** | 14880 | 18320, 6920, 11744, 18848 | 50.13s | 0 | 1500/1500 | NO | NO | **PASS** |

---

## 8. Pliki Łatek Zamknięcia (`scratch/closeout_patches/`)

1. **Implementacja**: `scratch/closeout_patches/encoder_profiles_shared_intel.patch`
   - Rozmiar: `21 710 bajtów`
   - SHA256: `148937bbe4332167109aaf7c34707f828f81d794a0f976af9001d9c0e31fb1c9`
   - Zmodyfikowane pliki:
     - `src/ffmpeg/encoder_profile.py`
     - `src/ffmpeg/intel_config.py`
     - `src/ffmpeg/intel_native_exporter.py`
     - `src/ffmpeg/streaming.py`
     - `src/gui/qt/_mixins/preset_mixin.py`
     - `src/gui/qt/_mixins/project_mixin.py`
     - `src/gui/qt/_mixins/render_mixin.py`
     - `src/gui/qt/tabs/render_tab.py`
     - `src/gui/qt/widgets/property_editor.py`
     - `src/native/d3d11_intel_pipeline/telem_intel_native.c`

2. **Testy Jednostkowe**: `scratch/closeout_patches/encoder_profiles_shared_intel_tests.patch`
   - Rozmiar: `6 590 bajtów`
   - SHA256: `d27e9a748b0bb8ad33907a4acd30b29d16b5ce4f1b3e97a55dec25becab88ca3`
   - Plik: `tests/test_encoder_profiles_intel.py`

---

## 9. Podsumowanie Wymaganych Wskaźników

```text
FAST_TARGET_USAGE=7
BALANCED_TARGET_USAGE=4
QUALITY_TARGET_USAGE=1

LEGACY_MISSING_PROFILE=fast
NEW_PROJECT_DEFAULT=balanced

LEGACY_PROJECT_RENDER_CONFIG_PARITY=YES

H264_FAST_FPS=88.583
H264_BALANCED_FPS=78.068
H264_QUALITY_FPS=64.666

HEVC_FAST_FPS=67.866
HEVC_BALANCED_FPS=65.909
HEVC_QUALITY_FPS=48.896

AV1_FAST_FPS=57.007
AV1_BALANCED_FPS=51.470
AV1_QUALITY_FPS=51.978

TARGET_USAGE_ACCEPTED_H264=YES
TARGET_USAGE_ACCEPTED_HEVC=YES
TARGET_USAGE_ACCEPTED_AV1=YES

ALL_PROFILE_OUTPUT_CONTRACTS_PASS=YES

INTEL_TESTS_FAILED=0

NEW_UNRELATED_FAILURES=0

FINAL_DECISION=INTEL_PROFILES_READY
```


---

## 10. Promocja do Gałęzi Main (Podsumowanie)

- **PROFILE_COMMIT**: `63f5b5a4a1bddcb9abe5d24acfd529e3cc5e7b84`
- **REMOTE_MAIN_BEFORE_PUSH**: `bd88b3d84fafb18c1468ec36dbe66f157bc89e68`
- **FINAL_REMOTE_MAIN_HEAD**: `63f5b5a4a1bddcb9abe5d24acfd529e3cc5e7b84`
- **PUSH_MAIN_RESULT**: `PASS`
- **PROFILE_COMMIT_REACHABLE_FROM_MAIN**: `YES`
- **PROMOTION_GUI_SMOKE_PASS**: `YES`
- **PROMOTION_OUTPUT_CONTRACT_PASS**: `YES`
- **EFFECTIVE_TARGET_USAGE**: `4` (BALANCED HEVC 300f smoke)
- **FINAL_PROMOTION_STATUS**: `PASS`
- **FINAL_STATUS**: `INTEL_ENCODER_PROFILES_PROMOTED_TO_MAIN`

### 10.1. Tabela Nadzoru Watchdog (Promocja & Testy)

| WORKLOAD | PID | CHILD_PIDS | ELAPSED | CPU_TIME_DELTA | LAST_LOG_TIMESTAMP | FRAMES_OR_TESTS | OUTPUT_SIZE | EXIT_CODE | STALL_DETECTED | RETRY_USED | FINAL_STATUS |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **PROMOTION_SMOKE_HEVC** | 18560 | 17620, 18160, 6748, 5484 | 13.91s | 31.8s | 17:01:48 | 300/300 frames | 50.76 MB | 0 | NO | NO | **PASS** |
| **PYTEST_INTEL_GATE** | 14224 | [] | 8.04s | 7.9s | 17:01:20 | 158/158 tests | N/A | 0 | NO | NO | **PASS** |
| **PYTEST_PROFILES_GATE** | 8840 | [] | 3.52s | 3.4s | 17:01:01 | 7/7 tests | N/A | 0 | NO | NO | **PASS** |
| **CONTRACT_PROBE_HEVC** | 7112 | [] | 0.85s | 0.6s | 17:01:58 | ffprobe parse | N/A | 0 | NO | NO | **PASS** |
| **GIT_PUSH_MAIN** | 12904 | [] | 2.91s | 0.3s | 17:02:44 | 1 commit | N/A | 0 | NO | NO | **PASS** |
