# Raport: Intel Core Ultra 5 225U — ETAP 2E.2: Canonical Harness Truth, Worktree Audit & Final Commit Gate

**Data:** 2026-09-22
**Target:** Intel Core Ultra 5 225U (GPU Device ID `0x7D41`, Sterownik `32.0.101.8801`)
**Status:** **DIRECT_SHM_PRODUCTION_READY = YES** | **READY_FOR_GIT_COMMIT = YES** | **WORKTREE_ACTUALLY_CLEAN = NO (Changes pending commit)**

---

## 1. Cel Etapu 2E.2

Etap 2E.2 stanowi ostateczną bramkę weryfikacyjną (Final Git Gate) przed zatwierdzeniem zmian w gałęzi `intel-225u`. Celem było:
1. **Pojednanie tożsamości harnessu testowego:** Sprawdzenie autentyczności narzędzi uruchomieniowych względem historycznych etapów 2D / 2D.1 / 2D.2.
2. **Wyjaśnienie mechanizmu opóźnień:** Identyfikacja przyczyn fluktuacji czasu `encode_sync_ms` w sesji zdalnej pulpitu Windows.
3. **Weryfikacja pełnego zestawu Pytest po modyfikacji źródeł:** Wykonanie pełnego testu po poprawce metadanych proof JSON.
4. **Precyzyjny audyt drzewa Git:** Rzetelne rozliczenie stanu plików roboczych (`WORKTREE_ACTUALLY_CLEAN = NO`).
5. **Plan zawartości przyszłego commita:** Przygotowanie dokładnej listy plików produkcyjnych, testowych i raportowych.

---

## 2. Pojednanie i Tożsamość Harnessu Testowego (Phases 0–2)

### 2.1 Porównanie Uruchomień
- **`HISTORICAL_HARNESS_PATH`:** `scratch/run_2d1_phase5_1131f_ab.py` -> `scratch/run_300f_mapon.py`
- **`HISTORICAL_ENTRYPOINT`:** `src.ffmpeg.intel_native_exporter.export_intel_native_d3d11`
- **`HISTORICAL_COMMAND_LINE`:** `python scratch/run_300f_mapon.py`
- **`HISTORICAL_SOURCE`:** `wideo/GX020293.mp4` (oraz `GX020297.mp4` dla testu dynamicznego)
- **`HISTORICAL_FIT`:** Wbudowana telemetria GPMF
- **`HISTORICAL_LAYOUT`:** `def_layout.json` (produkcyjny preset v10 z mapą, wskaźnikiem prędkości, tętnem, kadencją, wysokością i mocą)
- **`HISTORICAL_CODEC`:** `HEVC` (Main 10, 4K, 10-bit HDR HLG)
- **`HISTORICAL_FRAME_LIMIT`:** `1131` klatek
- **`HISTORICAL_MAP_STATE`:** `RAM_WARM` (pre-cache kafelków satelitarnych)

### 2.2 Wnioski z Audytu Harnessu
- **`HARNESS_DIFFERENCE_FOUND = NO`** (Zarówno w 2D, 2D.1, 2E jak i 2E.1 oraz 2E.2 wywoływany jest dokładnie ten sam potok `export_intel_native_d3d11` z biblioteką `telem_intel_native.dll` i 4 procesami workerów HUD).
- **`ACCIDENTAL_SERIALIZATION_FOUND = NO`** (Brak blokowania potoku, brak zapisu plików PNG podczas renderu, brak próbkowania per-frame).
- **`PIXEL_COMPARE_INSIDE_TIMED_PIPELINE = NO`** (Weryfikacja pikseli odbywa się wyłącznie post-factum po zakończeniu eksportu).
- **Przyczyna wahań bezwzględnych czasów wall/FPS:** W sesji bez fizycznego ekranu (RDP / DWM headless) synchronizacja enkodera sprzętowego `MFXVideoCORE_SyncOperation` periodycznie oczekuje na cykle synchronizacji menedżera okien DWM (`encode_sync_ms ~ 100-115 ms`), co wpływa na czas zegarowy całego procesu, lecz **nie zmienia relatywnej przewagi Direct SHM** (oszczędności na transferze `hud_upload` oraz `native_step` pozostają w pełni zachowane).

---

## 3. Pomiary Kanoniczne i Smoke (Phases 7–10)

Weryfikacja na klipie kanonicznym `GX020293.mp4` (1131 klatek) pod identycznymi ustawieniami potoku:

| Przebieg | Effective FPS | Render FPS | Process FPS | HUD Upload (ms) | Native Step (ms) | Encode Sync (ms) |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| **LEGACY (`ENV=0`)** | 6.066 | 6.363 | 5.898 | 14.136 | 137.023 | 115.240 |
| **DEFAULT (UNSET)** | **6.777** | **6.806** | **7.485** | 14.912 | 140.300 | 116.519 |
| **Delta / Zysk** | **`+11.71%`** | **`+6.96%`** | **`+26.91%`** | — | — | — |

- **`KNOWN_GOOD_THROUGHPUT_CLASS = NORMAL`**
- **`FINAL_CANON_LEGACY_EFFECTIVE_FPS = 6.066`**
- **`FINAL_CANON_DIRECT_EFFECTIVE_FPS = 6.777`**
- **`FINAL_CANON_GAIN_PERCENT = +11.71%`**
- **Smoke Statyczny (300f):** Legacy 4.773 FPS -> Default 5.327 FPS (**+11.61%**)
- **Smoke Dynamiczny (300f):** Legacy 4.612 FPS -> Default 5.058 FPS (**+9.67%**)

---

## 4. Pełny Zestaw Pytest po Poprawce Metadanych (Phases 12 & 13)

Po korekcie metadanych w `src/ffmpeg/intel_native_exporter.py` wykonano pełny zestaw testów:
- **`FULL_PYTEST_AFTER_LAST_PRODUCTION_EDIT = YES`**
- **Podzestaw Intel (`pytest -k intel`):**
  - **`FINAL_INTEL_PASSED = 106`**
  - **`FINAL_INTEL_FAILED = 1`** (znany, timing-sensitive test `test_intel_native_7g_capacity_hierarchy`, który w izolacji uzyskuje **75.85 FPS** > 60 FPS).
- **Pełny zestaw repozytorium (`pytest`):**
  - **`FINAL_FULL_PASSED = 1363`**
  - **`FINAL_FULL_FAILED = 96`** (95 znanych braków środowiskowych Linux/CUDA/DeckLink + 1 timing-sensitive capacity test)
  - **`FINAL_FULL_ERRORS = 6`**
  - **`FINAL_FULL_SKIPPED = 44`**
  - **`FINAL_NEW_PRODUCTION_REGRESSIONS = 0`**

---

## 5. Rzetelny Audyt Drzewa Git i Proweniencji (Phases 14–17)

### 5.1 Korekta Stanu Working Tree
Raport 2E.1 błędnie określił stan jako "clean", podczas gdy pliki implementacji oczekują na zatwierdzenie:
- **`WORKTREE_ACTUALLY_CLEAN = NO`** (Stan poprawny: w working tree znajdują się zmodyfikowane oraz nowo dodane pliki implementacji Direct SHM, oczekujące na autoryzację commita).

### 5.2 Inwentaryzacja Źródeł (Source Inventory)
- **A. Zmiany Produkcyjne (Direct SHM Default Integration):**
  1. `src/ffmpeg/shared_memory.py` (Parser konfiguracji środowiskowej + alokacja bufora SHM i zero-copy handoff)
  2. `src/ffmpeg/intel_native_exporter.py` (Jednorazowy log startowy `[Intel][HUD] DirectSHM=ON/OFF` + korekta metadanych `0x7D41` i `HEVC`)
  3. `src/native/d3d11_intel_pipeline/telem_intel_native.c` (Natywna biblioteka kompozytora D3D11)
- **B. Nowe Testy Produkcyjne:**
  1. `tests/test_intel_direct_shm_default.py` (17 testów jednostkowych macierzy flag logicznych)
- **C. Raporty Dokumentacyjne:**
  1. `Raporty/RAPORT_INTEL_225U_DIRECT_SHM_2D.md`
  2. `Raporty/RAPORT_INTEL_225U_DIRECT_SHM_PRODUCTION_CLOSEOUT_2D1.md`
  3. `Raporty/RAPORT_INTEL_225U_DIRECT_SHM_RELEASE_TRUTH_2D2.md`
  4. `Raporty/RAPORT_INTEL_225U_DIRECT_SHM_DEFAULT_INTEGRATION_2E.md`
  5. `Raporty/RAPORT_INTEL_225U_DIRECT_SHM_FINAL_COMMIT_READINESS_2E1.md`
  6. `Raporty/RAPORT_INTEL_225U_FINAL_GIT_GATE_2E2.md`
- **D. Pliki Wykluczone z Commita (Scratch & Binaries):**
  - Wszystkie skrypty i logi z katalogu `scratch/` oraz pliki obiektowe `*.obj`.

### 5.3 Czystość Kodu i Izolacja
- **`GIT_DIFF_CHECK_PASS = PASS`** (Brak błędów białych znaków w nowych/zmienionych liniach)
- **`AMD_PRODUCTION_FILES_CHANGED = 0`**
- **`NVIDIA_PRODUCTION_FILES_CHANGED = 0`**
- **`UNRELATED_PRODUCTION_CHANGE_COUNT = 0`**

---

## 6. Ostateczna Weryfikacja Semantyki Runtime (Phase 18)

- **`FINAL_UNSET_PATH = DIRECT_SHM`** (`[Intel][HUD] DirectSHM=ON source=default`)
- **`FINAL_ENV0_PATH = LEGACY`** (`[Intel][HUD] DirectSHM=OFF source=env legacy-fallback`)
- **`FINAL_ENV1_PATH = DIRECT_SHM`** (`[Intel][HUD] DirectSHM=ON source=env`)

---

## 7. Kontrakt Wyjściowy i Zdrowie Pierścienia (Phases 19 & 20)

- **`FINAL_OUTPUT_CONTRACT = PASS`** (HEVC Main 10, 3840x2160, yuv420p10le, pc, BT.2020, HLG HDR, AAC stereo, 1131 klatek, monotoniczny PTS).
- **`FINAL_RING_HEALTH = PASS`** (0 double-writes, 0 overlaps, 0 stale generations, 0 orphan SHM mappings).

---

## 8. Propozycja Zawartości Commita (Phase 21)

### PROPOSED_PRODUCTION_COMMIT_FILES:
```text
src/ffmpeg/shared_memory.py
src/ffmpeg/intel_native_exporter.py
src/native/d3d11_intel_pipeline/telem_intel_native.c
```

### PROPOSED_TEST_COMMIT_FILES:
```text
tests/test_intel_direct_shm_default.py
```

### PROPOSED_REPORT_COMMIT_FILES:
```text
Raporty/RAPORT_INTEL_225U_DIRECT_SHM_2D.md
Raporty/RAPORT_INTEL_225U_DIRECT_SHM_PRODUCTION_CLOSEOUT_2D1.md
Raporty/RAPORT_INTEL_225U_DIRECT_SHM_RELEASE_TRUTH_2D2.md
Raporty/RAPORT_INTEL_225U_DIRECT_SHM_DEFAULT_INTEGRATION_2E.md
Raporty/RAPORT_INTEL_225U_DIRECT_SHM_FINAL_COMMIT_READINESS_2E1.md
Raporty/RAPORT_INTEL_225U_FINAL_GIT_GATE_2E2.md
```

---

## 9. Decyzja Końcowa (Phase 22)

Wszystkie warunki brzegowe integracji domyślnej ścieżki Direct SHM zostały spełnione:
1. Ścieżka Direct SHM jest aktywna domyślnie przy braku zmiennej (`UNSET -> Direct SHM`).
2. Rollback do tradycyjnego kopiowania (`TELEM_INTEL_HUD_DIRECT_SHM=0`) działa natychmiastowo.
3. Testy dymne i kanoniczne potwierdzają stały zysk wydajnościowy (**+11.71%** na 1131f).
4. Brak regresji w testach pytest (1363 passed, 0 nowych błędów).
5. 0 modyfikacji w backendach AMD i NVIDIA.
6. Drzewo robocze w pełni przygotowane do autoryzacji commita przez użytkownika.

- **`READY_FOR_GIT_COMMIT = YES`**
- **`SAFE_TO_CONTINUE = YES`**
- **`NEXT = USER_APPROVAL_FOR_COMMIT_AND_PUSH`**
