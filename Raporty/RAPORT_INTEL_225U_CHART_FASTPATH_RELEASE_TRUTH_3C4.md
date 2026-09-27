# RAPORT: INTEL 225U — ETAP 3C.4 FINAL RELEASE TRUTH
# EXPERIMENTAL OPT-IN CLASSIFICATION, LEGACY PRODUCTION DEFAULT, FULL PYTEST VALIDATION, SELECTIVE HUNK PROOF & ZERO GPU-MAP CONTAMINATION

**Data sporządzenia:** 2026-09-23  
**Platforma testowa:** Intel Core Ultra 5 225U (Arrow Lake-U / Meteor Lake, DevID `0x7D41`, 4 Xe-cores, 12 wątków CPU), Windows 11 Pro Build 26200, oneVPL HEVC Main10 Hardware Encode, D3D11 Native HUD Compositor.  
**Baza referencyjna (Git Base):** `2cd43bad3fbd99e756cc651256cfe2ee27ee08a8` (gałąź `intel-225u`).  
**Status etapu:** **PASS — EXPERIMENTAL OPT-IN COMMIT READY; PRODUCTION DEFAULT REMAINS LEGACY**

---

## 1. HISTORIA I ROZWÓJ PRAWDY ETAPÓW 3C–3C.4

Niniejszy raport podsumowuje pełną sekwencję walidacji architektonicznej i wydajnościowej Chart Fastpath bez zacierania historii:

1. **Etap 3C (Kandydat wyłoniony):**  
   Zidentyfikowano architekturę `C2_REUSABLE_WORKER_SCRATCH_BUFFER`, która wyeliminowała 100% alokacji sterty na klatkę (~4.94 MB -> 0 MB) i zredukowała zapisy UMA o ~93%. Pomiary syntetyczne i 300f wykazały zysk ~+4.4%, a parytet pikselowy był absolutny (`MAX_DIFF=0`).
2. **Etap 3C.1 (Błędna interpretacja bramki kanonicznej):**  
   Wykonano 3 pary kanoniczne 1131f na `GX020297.mp4`, które dały wynik `-0.56%`. Raport 3C.1 błędnie oznaczył bramkę jako `PASS`, racjonalizując ujemny wynik redukcją pamięci i zyskami syntetycznymi.
3. **Etap 3C.2 (Błąd bramki 6-parowej i problem copy-paste):**  
   Wprowadzono zrównoważoną kolejność naprzemienną. W pierwszych 6 parach OPT wygrał tylko 3/6 par (bramka wymagała >=4/6), po czym rozszerzono bieg do 8 par (5/8). Raport 3C.2 błędnie ogłosił gotowość produkcyjną (`READY_FOR_3C_COMMIT=YES`), zawierał błędy w wyliczeniach efektu kolejności (`+3.04%` zamiast `+1.57%`) oraz omyłkowo wpisał nieistniejący plik `GX020079.MP4`.
4. **Etap 3C.3 (Pre-rejestrowana walidacja dwu-workloadowa):**  
   Przeprowadzono ścisłe testy A/B na rzeczywistych zestawach: Workload A (`GX020293.mp4`, 1131f) oraz Workload B (`GX020297.mp4`, 1131f). Workload B przeszedł pomyślnie (+11.70%, 3/4 wygrane), lecz Workload A nie osiągnął 3 wygranych (2/4) i wykazał duży efekt kolejności (+10.63%). Zgodnie z pre-rejestracją werdykt brzmi: `FINAL_PERFORMANCE_CLASS = WORKLOAD_DEPENDENT`.
5. **Etap 3C.4 (Finalna prawda wdrożeniowa):**  
   Zamknięto wszelkie dalsze testy wydajnościowe. Fastpath zaklasyfikowano jako **`EXPERIMENTAL_OPT_IN`**, a domyślnym trybem produkcyjnym pozostawiono **`LEGACY`**. Potwierdzono czystą separację gita (0 zmian GPU Map w commitowanym patchu) oraz pełną surową regresję testową.

---

## 2. JAWNA KOREKTA BŁĘDU 3C.3

> [!CAUTION]
> **KOREKTA BRAMKI Z ETAPU 3C.3:**  
> W etapie 3C.3 wyemitowano token `READY_FOR_3C_COMMIT=YES`, podczas gdy specyfikacja wymagała `FINAL_PERFORMANCE_CLASS=POSITIVE` dla wdrożenia produkcyjnego.  
> Ponieważ wynik wyniósł `WORKLOAD_DEPENDENT`, niniejszym odnotowuje się formalnie:  
> - **`3C3_PRODUCTION_COMMIT_GATE_VALID = NO`**  
> - **`3C3_READY_FOR_PRODUCTION_DEFAULT_COMMIT = NO`**

---

## 3. OSTATECZNA POLITYKA I KLASYFIKACJA PRODUKTOWA

### 3.1. Klasyfikacja funkcjonalności
- `CHART_FASTPATH_RELEASE_CLASS = EXPERIMENTAL_OPT_IN`
- Chart Fastpath **nie jest** i **nie może być** nazywany domyślną optymalizacją produkcyjną. Jest zaawansowaną, eksperymentalną ścieżką pamięciową dostępną na żądanie użytkownika.

### 3.2. Semantyka zmiennej środowiskowej
W pliku `src/indicators/chart.py`:
- `UNSET` (zmienna nieustawiona lub pusta) -> **LEGACY (Fastpath wyłączony)** (`False, "default"`)
- `TELEM_INTEL_CHART_FASTPATH = 0` -> **LEGACY** (`False, "env legacy-fallback"`)
- `TELEM_INTEL_CHART_FASTPATH = 1` -> **FASTPATH (Opt-in aktywny)** (`True, "env"`)
- Wartości nierozpoznane -> ostrzeżenie `UserWarning` i bezpieczny powrót do **LEGACY** (`False, "default"`).
- `FINAL_UNSET_PATH = LEGACY`
- `FINAL_ENV0_PATH = LEGACY`
- `FINAL_ENV1_PATH = FASTPATH`

---

## 4. WERYFIKACJA PARYTETU PIKSELOWEGO I TESTY JEDNOSTKOWE

### 4.1. Parity Smoke (20 klatek)
Wykonano test na 20 klatkach z dynamicznej osi czasu wideo:
- `FINAL_PARITY_SMOKE_FRAMES = 20`
- `FINAL_PARITY_MAX_DIFF = 0`
- `FINAL_PARITY_DIFF_PIXELS = 0`
- W połączeniu z wcześniejszymi kampaniami 1000f i 100f: parytet pikselowy jest w 100% matematycznie bezstratny (`MAE = 0.000000`).

### 4.2. Testy jednostkowe polityki (22/22 PASS)
Zaktualizowano `tests/test_intel_chart_fastpath_policy.py`:
- Sprawdzono pełną macierz flag (None, pusty ciąg, spacje, 0, 1, true, false, selective cadence/hr, unknown).
- Wynik: **22 passed w 0.19s**.

---

## 5. PEŁNY AUDYT REGRESYJNY PYTEST

Po ostatecznym wdrożeniu semantyki `LEGACY_DEFAULT` w kodzie produkcyjnym przeprowadzono pełną surową weryfikację:

1. **Testy Intel (`pytest -k intel`):**
   - **`FINAL_INTEL_RESULT = PASS (129 passed, 0 failed w 4.60s)`**
2. **Pełna suita (`pytest -q`):**
   - **`FINAL_FULL_PASSED = 1384`**
   - **`FINAL_FULL_FAILED = 97`** (błędy tożsame z bazowymi brakami plików wideo/JSON w repozytorium)
   - **`FINAL_FULL_ERRORS = 6`**
   - **`FINAL_FULL_SKIPPED = 44`**
   - **`NEW_FAILURE_IDENTITIES = 0`**
   - **`NEW_PRODUCTION_REGRESSIONS = 0`** (Bramka regresji: **SPEŁNIONA**)

---

## 6. AUDYT HUNKÓW W `intel_native_exporter.py` I DOWÓD CZYSTEGO PATCHA

### 6.1. Re-audyt hunków w eksporterze
W pliku `src/ffmpeg/intel_native_exporter.py`:
- `Hunk 1 (linie 278–296)`: Importy i deklaracje GPU Map (3B)
- `Hunk 2 (linie 600–768)`: Setup GPU Map (3B) + **Logowanie Fastpath (linie 758–765, 3C)**
- `Hunk 3 (linie 1026–1046)`: Per-frame blit GPU Map (3B)
- `Hunk 4 (linie 1313–1322)`: Statystyki GPU Map (3B)
- `EXPORTER_TOTAL_CHANGED_HUNKS = 4`
- `EXPORTER_GPU_MAP_HUNKS = 3`
- `EXPORTER_CHART_HUNKS = 1`
- `EXPORTER_OTHER_HUNKS = 0`

### 6.2. Konstrukcja patcha 3C-only
Utworzono dedykowany patch `scratch/chart_fastpath_3c_only.patch` (14,746 bajtów), zawierający wyłącznie:
1. `src/indicators/chart.py`
2. `tests/test_intel_chart_fastpath_policy.py`
3. Hunk logowania startowego z `src/ffmpeg/intel_native_exporter.py`
- `CHART_ONLY_PATCH_CREATED = YES`

---

## 7. SKANY BEZPIECZEŃSTWA COMMITA

1. **Skan kontaminacji GPU Map:**
   - Przeszukano proponowany patch pod kątem symboli 3B (`TELEM_INTEL_GPU_MAP`, `gpu_map`, `telem_intel_native_gpu_map`, `map_renderer_ctx` itp.).
   - `SIMULATED_GPU_MAP_HUNK_COUNT = 0`
   - `SIMULATED_GPU_MAP_SYMBOL_COUNT = 0`
2. **Skan niezwiązanych plików:**
   - Patch nie modyfikuje `TeleMGP.py`, `def_layout.json`, GUI, streaming, telemetry, ani video helpers.
   - `SIMULATED_UNRELATED_HUNK_COUNT = 0`
3. **Diff check (Whitespace / Formatowanie):**
   - Walidacja `git diff --check` na patchu 3C: brak błędów whitespace, brak pustych linii na końcu plików.
   - `SIMULATED_DIFF_CHECK_PASS = YES`
4. **Skan poufności (Secret Scan):**
   - Brak kluczy API, tokenów, haseł i poświadczeń.
   - `SIMULATED_SECRET_SCAN_PASS = YES`
5. **Skan ścieżek maszynowych i mediów:**
   - Brak zakodowanych ścieżek `C:\_DEV`, brak nazw plików wideo w kodzie produkcyjnym.
   - `MACHINE_PATH_FOUND = NO`
   - `HARDCODED_MEDIA_FOUND = NO`

---

## 8. WERYFIKACJA NA CZYSTYM COMMICIE BAZOWYM (FRESH BASE PROOF)

W wyizolowanym katalogu roboczym rozpakowano commit `2cd43bad3fbd99e756cc651256cfe2ee27ee08a8` i zaaplikowano wyłącznie wygenerowany patch 3C:
- `TEMP_PATCH_APPLY_PASS = YES`
- `TEMP_GPU_MAP_CHANGE_COUNT = 0`
- `TEMP_UNRELATED_CHANGE_COUNT = 0`
- `TEMP_POLICY_TEST_RESULT = PASS (22/22 passed)`
- `TEMP_INTEL_TEST_RESULT = PASS (67/67 passed)`
- `TEMP_APP_IMPORT_PASS = YES`
- `TEMP_STARTUP_LOG_PASS = YES` (Potwierdzono komunikat startowy: `[Intel][Charts] Fastpath=OFF source=default`)

---

## 9. PLAN PRZYSZŁEGO COMMITA I DECYZJA KOŃCOWA

> [!IMPORTANT]
> **Zgodnie z poleceniem nie wykonano żadnego `git add`, `git commit` ani `git push`. Poniżej przedstawiono zawartość przyszłego commita po uzyskaniu zgody Użytkownika:**

### 9.1. Manifest commita:
- **Pliki produkcyjne:**
  - `src/indicators/chart.py` (bufor roboczy, funkcja czyszcząca ROI, bezpieczny fallback i polityka `LEGACY_DEFAULT`)
  - `src/ffmpeg/intel_native_exporter.py` (wyłącznie linie 758–765: logowanie startowe)
- **Pliki testowe:**
  - `tests/test_intel_chart_fastpath_policy.py`
- **Raporty:**
  - `Raporty/RAPORT_INTEL_225U_CHART_FASTPATH_MASTER_3C.md`
  - `Raporty/RAPORT_INTEL_225U_CHART_FASTPATH_PRODUCTION_CLOSEOUT_3C1.md`
  - `Raporty/RAPORT_INTEL_225U_CHART_FASTPATH_FINAL_TRUTH_3C2.md`
  - `Raporty/RAPORT_INTEL_225U_CHART_FASTPATH_FINAL_VERDICT_3C3.md`
  - `Raporty/RAPORT_INTEL_225U_CHART_FASTPATH_RELEASE_TRUTH_3C4.md`

### 9.2. Wykluczone z commita:
- Wszystkie pliki i hunki prototypu 3B GPU Map (`src/native/d3d11_intel_pipeline/telem_intel_native.c`, `src/moving_map.py`, hunki 1, 3, 4 w eksporterze).
- Niezwiązane modyfikacje robocze w GUI i helperach wideo.
- Zawartość katalogu `scratch/`.

### 9.3. Tytuł i charakterystyka przyszłego commita:
- Commit musi być zatytułowany jako dodanie **eksperymentalnej, opt-in ścieżki Chart Fastpath** (np. `Intel: add experimental opt-in chart fastpath preserving legacy default`).
- Nie wolno używać sformułowań typu "production default optimization" ani podawać procentowych zysków w tytule.

---

## 10. PODSUMOWANIE TOKENÓW 3C.4

```text
3C3_PRODUCTION_COMMIT_GATE_VALID=NO
3C3_READY_FOR_PRODUCTION_DEFAULT_COMMIT=NO
CHART_FASTPATH_RELEASE_CLASS=EXPERIMENTAL_OPT_IN
FINAL_UNSET_PATH=LEGACY
FINAL_ENV0_PATH=LEGACY
FINAL_ENV1_PATH=FASTPATH
FINAL_PARITY_SMOKE_FRAMES=20
FINAL_PARITY_MAX_DIFF=0
FINAL_PARITY_DIFF_PIXELS=0
FINAL_INTEL_RESULT=PASS (129 passed in 4.60s)
FINAL_FULL_PASSED=1384
FINAL_FULL_FAILED=97
FINAL_FULL_ERRORS=6
FINAL_FULL_SKIPPED=44
NEW_FAILURE_IDENTITIES=0
NEW_PRODUCTION_REGRESSIONS=0
EXPORTER_TOTAL_CHANGED_HUNKS=4
EXPORTER_GPU_MAP_HUNKS=3
EXPORTER_CHART_HUNKS=1
EXPORTER_OTHER_HUNKS=0
CHART_ONLY_PATCH_CREATED=YES
SIMULATED_PRODUCTION_FILES=['src/indicators/chart.py', 'src/ffmpeg/intel_native_exporter.py']
SIMULATED_TEST_FILES=['tests/test_intel_chart_fastpath_policy.py']
SIMULATED_REPORT_FILES=['Raporty/RAPORT_INTEL_225U_CHART_FASTPATH_MASTER_3C.md', 'Raporty/RAPORT_INTEL_225U_CHART_FASTPATH_PRODUCTION_CLOSEOUT_3C1.md', 'Raporty/RAPORT_INTEL_225U_CHART_FASTPATH_FINAL_TRUTH_3C2.md', 'Raporty/RAPORT_INTEL_225U_CHART_FASTPATH_FINAL_VERDICT_3C3.md', 'Raporty/RAPORT_INTEL_225U_CHART_FASTPATH_RELEASE_TRUTH_3C4.md']
SIMULATED_GPU_MAP_HUNK_COUNT=0
SIMULATED_GPU_MAP_SYMBOL_COUNT=0
SIMULATED_UNRELATED_HUNK_COUNT=0
SIMULATED_DIFF_CHECK_PASS=YES
SIMULATED_SECRET_SCAN_PASS=YES
MACHINE_PATH_FOUND=NO
HARDCODED_MEDIA_FOUND=NO
TEMP_PATCH_APPLY_PASS=YES
TEMP_GPU_MAP_CHANGE_COUNT=0
TEMP_UNRELATED_CHANGE_COUNT=0
TEMP_POLICY_TEST_RESULT=PASS
TEMP_INTEL_TEST_RESULT=PASS
TEMP_APP_IMPORT_PASS=YES
TEMP_STARTUP_LOG_PASS=YES
READY_FOR_EXPERIMENTAL_FASTPATH_COMMIT=YES
READY_FOR_PRODUCTION_DEFAULT_COMMIT=NO
SAFE_TO_CONTINUE=YES
NEXT=USER_APPROVAL_FOR_EXPERIMENTAL_FASTPATH_COMMIT_PUSH
```
