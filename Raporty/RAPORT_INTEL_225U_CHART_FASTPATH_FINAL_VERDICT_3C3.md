# RAPORT: INTEL 225U — ETAP 3C.3 FINAL
# PRE-REGISTERED PERFORMANCE VERDICT, DUAL-WORKLOAD VALIDATION, LAYOUT PROVENANCE, RAW-MATH AUDIT & FINAL SELECTIVE COMMIT READINESS

**Data sporządzenia:** 2026-09-23  
**Platforma testowa:** Intel Core Ultra 5 225U (Arrow Lake-U / Meteor Lake, DevID `0x7D41`, 4 Xe-cores, 12 wątków CPU), Windows 11 Pro Build 26200, oneVPL HEVC Main10 Hardware Encode, D3D11 Native HUD Compositor.  
**Baza referencyjna (Git Base):** `2cd43bad3fbd99e756cc651256cfe2ee27ee08a8` (gałąź `intel-225u`).  
**Status etapu:** **PASS — PRE-REGISTERED VERDICT COMPLETE, DEFAULT POLICY LOCKED TO LEGACY_DEFAULT, READY FOR SELECTIVE COMMIT**

---

## 1. REKONCYLIACJA MATEMATYCZNA I BŁĘDÓW 3C.2 (RAW-MATH AUDIT)

### 1.1. Weryfikacja surowych obliczeń z 3C.2
Przeprowadzono ponowne przeliczenie wszystkich 8 par z etapu 3C.2 bezpośrednio z surowych plików `.intel_proof.json`:
- `RECALC_6_PAIR_MEAN_PERCENT = +2.0338%`
- `RECALC_6_PAIR_MEDIAN_PERCENT = +1.7159%`
- `RECALC_8_PAIR_MEAN_PERCENT = +2.0099%`
- `RECALC_8_PAIR_MEDIAN_PERCENT = +1.9383%`
- `RECALC_REF_FIRST_6_MEAN_PERCENT = +1.5670%` (Pary 1, 3, 5: +7.36%, -0.36%, -2.30%)
- `RECALC_OPT_FIRST_6_MEAN_PERCENT = +2.5005%` (Pary 2, 4, 6: -0.27%, +3.70%, +4.07%)
- `RECALC_ORDER_EFFECT_6_PERCENT = -0.9334%`
- `RECALC_REF_FIRST_8_MEAN_PERCENT = +1.7308%`
- `RECALC_OPT_FIRST_8_MEAN_PERCENT = +2.2890%`
- `RECALC_ORDER_EFFECT_8_PERCENT = -0.5582%`

> [!WARNING]
> **Korekta błędu raportu 3C.2:**  
> `3C2_REPORTED_ORDER_METRICS_CORRECT = NO`.  
> W raporcie 3C.2 błędnie podano: `REF_FIRST_MEAN = +3.04%` oraz `OPT_FIRST_MEAN = +1.02%`. Prawidłowe wartości wyliczone bezpośrednio z danych wynoszą odpowiednio **+1.5670%** oraz **+2.5005%** (`ORDER_EFFECT = -0.9334%`).

### 1.2. Korekta bramki 6-parowej 3C.2
- `3C2_PRIMARY_6_OPT_WIN_COUNT = 3`
- `3C2_PRIMARY_6_REF_WIN_COUNT = 3`
- **`3C2_PRIMARY_6_PAIR_GATE_PASS = NO`** (Zgodnie z pre-rejestracją bramka wymagała co najmniej 4 na 6 wygranych par dla OPT; rozszerzenie do 8 par dało 5/8, ale nie unieważnia faktu, że pierwotna bramka 6-parowa nie została spełniona).

---

## 2. PROWENIENCJA UKŁADU (LAYOUT PROVENANCE)

### 2.1. Weryfikacja ścieżek i sum kontrolnych
Zbadano wszystkie potencjalne lokalizacje pliku `def_layout.json`:
- `WORKTREE_LAYOUT_PATH = C:\_DEV\BikeRideHUD-intel\def_layout.json` (Rozmiar: 28,856 B, SHA256: `a696d15157265c2d2abe8b5d922100a1cad1372b37216fa6acaef4d7e2c0d6e9`)
- `EXTERNAL_LAYOUT_PATH = C:\_DEV\TeleM\def_layout.json` (**NIE ISTNIEJE** na tej maszynie)
- `LAYOUT_HASH_MATCH = NO` (zewnętrzny katalog `C:\_DEV\TeleM` nie istnieje)

### 2.2. Ustalenie faktycznego layoutu aplikacji i harnessu
Audyt kodu źródłowego (`src/gui/qt/controller.py:316`, `src/gui/qt/_mixins/render_mixin.py:661`, `src/gui/qt/_mixins/project_mixin.py:338` oraz `scratch/run_300f_mapon.py:99`) wykazał, że aplikacja oraz harness zawsze odwoływały się do pliku `def_layout.json` w głównym katalogu bieżącego repozytorium:
- `ACTUAL_LAYOUT_PATH = C:\_DEV\BikeRideHUD-intel\def_layout.json`
- `ACTUAL_LAYOUT_EXISTS = YES`
- `ACTUAL_LAYOUT_SHA256 = a696d15157265c2d2abe8b5d922100a1cad1372b37216fa6acaef4d7e2c0d6e9`
- `LAYOUT_SELECTED_BY_HARNESS = C:\_DEV\BikeRideHUD-intel\def_layout.json`
- `HARNESS_LAYOUT_MATCH = YES`
- `FINAL_LAYOUT_PATH = C:\_DEV\BikeRideHUD-intel\def_layout.json`
- `FINAL_LAYOUT_SHA256 = a696d15157265c2d2abe8b5d922100a1cad1372b37216fa6acaef4d7e2c0d6e9`

---

## 3. GEOMETRIA WYKRESÓW I WYJAŚNIENIE KSIĘGOWANIA BAJTÓW

### 3.1. Rzeczywiste wymiary wskaźników wykresów (def_layout.json)
W rozdzielczości 4K (3840x2160, `min_dim = 2160`), dla parametrów `size = 30.0%`:
- Wymiary wyrenderowanego obrazu wykresu: **1160 x 532 px**
- Bajty surowe na wykres (RGBA 4 B/px): `1160 * 532 * 4 = 2,468,480 B` (~2.35 MiB / 2.47 MB)
- Liczba aktywnych wykresów: **2** (`fit_cadence_text` oraz `fit_heart_rate_text`)
- `FINAL_CHART_RAW_BYTES_FRAME = 4,936,960 B` (~4.71 MiB / 4.94 MB)

### 3.2. Przyczyna rozbieżności 5,180,672 B vs 4,936,960 B
- `CHART_BYTE_ACCOUNTING_DIFFERENCE_CAUSE`: Wartość `5,180,672 B` w raporcie 3C.2 powstała wskutek błędu konwersji jednostek w kalkulacji ręcznej: potraktowano dziesiętną wartość `4.94 MB` jako mebibajty binarne i przemnożono przez `1024^2` (`4.940698 * 1048576 = 5,180,672 B`). Prawdziwa geometria buforów RGBA to dokładnie `2 * 1160 * 532 * 4 = 4,936,960 B`, co precyzyjnie zgadza się z raportami 3C i 3C.1.

---

## 4. PROWENIENCJA HARNESSU I JAWNA KOREKTA GX020079

### 4.1. Ustalenie faktycznego harnessu
- `HARNESS_PATH = C:\_Dev\BikeRideHUD-intel\scratch\run_300f_mapon.py`
- `HARNESS_TRACKED = NO` (skrypt pomocniczy pod `scratch/`, utworzony w Etapie 2/Faza 6)
- `HARNESS_SHA256 = efc3f335e96f1a233c748caa9a73bba275c2b1c5a671702ce6014a564da90f12`
- `HARNESS_COMMAND = python scratch/run_300f_mapon.py`
- `HARNESS_ENTRYPOINT = src.ffmpeg.intel_native_exporter.export_intel_native_d3d11`
- `HARNESS_CANONICAL_PROVENANCE`: Skrypt `run_300f_mapon.py` jest kanonicznym runnerem eksportu Intel D3D11 Direct SHM. Nazwa `RUN_BENCHMARK_INTEL.py` w raporcie 3C.2 była syntetycznym symbolem tekstowym i fizycznie nie istniała jako osobny plik na dysku.

### 4.2. Jawna korekta błędu GX020079
> [!IMPORTANT]
> **KOREKTA DANYCH WEJŚCIOWYCH:**  
> Plik `Video/GX020079.MP4` **NIE ISTNIEJE** na tej maszynie Intel (jest to plik kanoniczny dla środowiska AMD ze specyfikacji `BENCHMARKS.md`).  
> Surowe pliki telemetryczne `out_proper_hw_c3c2_p*.intel_proof.json` dowodzą bezspornie, że **w etapie 3C.2 wszystkie 8 par biegów wykonano na `wideo/GX020297.mp4`** z parametrem `TELEM_MAX_FRAMES=1131`. Pojawienie się nazwy `GX020079` w raporcie 3C.2 było błędnym copy-paste z szablonu AMD i zostaje niniejszym definitywnie sprostowane.

---

## 5. DUAL-WORKLOAD CANONICAL VALIDATION (WYNIKI 3C.3)

Zgodnie z zatwierdzoną procedurą przetestowano oba kanoniczne zestawy testowe Intela w pre-rejestrowanych schematach ABBA / BAAB (po 4 pary każdy, `FRAME_LIMIT=1131`):

### 5.1. WORKLOAD A — Statyczny klip referencyjny (`wideo/GX020293.mp4`, 1131f)
Kolejność pre-rejestrowana: **A1: REF->OPT, A2: OPT->REF, A3: OPT->REF, A4: REF->OPT**

| Para | Kolejność | REF Eff FPS | OPT Eff FPS | Delta (FPS) | Zysk (%) | Wygrana |
| :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **A1** | REF -> OPT | 51.098 | 55.507 | +4.409 | **+8.63%** | **OPT** |
| **A2** | OPT -> REF | 68.705 | 63.261 | -5.444 | **-7.92%** | REF |
| **A3** | OPT -> REF | 67.760 | 67.621 | -0.139 | **-0.21%** | REF |
| **A4** | REF -> OPT | 67.223 | 70.249 | +3.027 | **+4.50%** | **OPT** |

- `A_MEAN_GAIN_PERCENT = +1.25%`
- `A_MEDIAN_GAIN_PERCENT = +2.15%`
- `A_OPT_WIN_COUNT = 2`
- `A_REF_WIN_COUNT = 2`
- `A_REF_CV_PERCENT = 13.22%`
- `A_OPT_CV_PERCENT = 10.05%`
- `A_ORDER_EFFECT_PERCENT = +10.63%`
- `A_NATIVE_DELTA_MS = +0.428 ms` (oszczędność w kroku natywnym)
- `A_UPLOAD_DELTA_MS = +0.253 ms` (oszczędność uploadu SHM)

> [!CAUTION]
> **Ocena bramki Workload A:**  
> Warunki: `mean >= +0.75%` (TAK), `median > 0` (TAK), `co najmniej 3/4 wygrane OPT` (**NIE: 2/4**), `|order_effect| <= 1.5%` (**NIE: +10.63%**).  
> **`WORKLOAD_A_GATE = FAIL`**

---

### 5.2. WORKLOAD B — Dynamiczny klip długi z pełną telemetrią (`wideo/GX020297.mp4`, 1131f)
Kolejność pre-rejestrowana: **B1: OPT->REF, B2: REF->OPT, B3: REF->OPT, B4: OPT->REF**

| Para | Kolejność | REF Eff FPS | OPT Eff FPS | Delta (FPS) | Zysk (%) | Wygrana |
| :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **B1** | OPT -> REF | 63.661 | 64.520 | +0.859 | **+1.35%** | **OPT** |
| **B2** | REF -> OPT | 49.201 | 43.662 | -5.539 | **-11.26%** | REF |
| **B3** | REF -> OPT | 22.766 | 32.039 | +9.274 | **+40.74%** | **OPT** |
| **B4** | OPT -> REF | 40.956 | 47.497 | +6.541 | **+15.97%** | **OPT** |

- `B_MEAN_GAIN_PERCENT = +11.70%`
- `B_MEDIAN_GAIN_PERCENT = +8.66%`
- `B_OPT_WIN_COUNT = 3`
- `B_REF_WIN_COUNT = 1`
- `B_REF_CV_PERCENT = 38.66%`
- `B_OPT_CV_PERCENT = 28.64%`
- `B_ORDER_EFFECT_PERCENT = +6.08%`
- `B_NATIVE_DELTA_MS = +2.064 ms` (oszczędność w kroku natywnym)
- `B_UPLOAD_DELTA_MS = +1.584 ms` (oszczędność uploadu SHM)

> [!NOTE]
> **Ocena bramki Workload B:**  
> Warunki: `mean >= 0.0%` (TAK: +11.70%), `median >= 0.0%` (TAK: +8.66%), `co najmniej 2/4 wygrane OPT` (TAK: 3/4), `brak powtarzalnej regresji natywnej >0.25 ms` (TAK: zysk +2.064 ms).  
> **`WORKLOAD_B_GATE = PASS`**

---

## 6. OSTATECZNY WERDYKT WYDAJNOŚCI I POLITYKA DOMYŚLNA

### 6.1. Klasyfikacja wydajnościowa
Zgodnie z pre-rejestrowanymi regułami:
- Klasa `POSITIVE` wymaga zaliczenia **obu** bramek (`WORKLOAD_A_GATE=PASS` ORAZ `WORKLOAD_B_GATE=PASS`).
- Ponieważ Workload A nie osiągnął 3 wygranych i wykazał duży efekt kolejności (+10.63%), klasyfikacja brzmi:
- **`FINAL_PERFORMANCE_CLASS = WORKLOAD_DEPENDENT`** (lub `REGRESSION`).

### 6.2. Mechaniczna decyzja polityki domyślnej
Pre-rejestrowana reguła decyzyjna nie dopuszcza subiektywnej interpretacji:
- `FINAL_CHART_DEFAULT_POLICY = LEGACY_DEFAULT`
- **`UNSET -> LEGACY`** (Fastpath wyłączony domyślnie w kodzie produkcyjnym)
- **`TELEM_INTEL_CHART_FASTPATH = 1` -> FASTPATH** (jawny opt-in użytkownika)
- **`TELEM_INTEL_CHART_FASTPATH = 0` -> LEGACY** (jawny fallback)

### 6.3. Wdrożenie polityki w kodzie
Zaktualizowano funkcję `get_intel_chart_fastpath_config` w `src/indicators/chart.py`:
- Domyślna wartość zwracana przy braku zmiennej: `False, "default"`.
- Nierozpoznane wartości: ostrzeżenie i fallback do `False, "default"`.
- Zaktualizowano testy w `tests/test_intel_chart_fastpath_policy.py`: wszystkie 22 testy przeszły pomyślnie (`22 passed in 0.19s`).
- `POLICY_SOURCE_CHANGED = YES`
- `POLICY_TEST_RESULT = PASS (22/22)`

---

## 7. WERYFIKACJA PARYTETU PIKSELOWEGO (EXACT PARITY)

Sprawdzono 100 reprezentatywnych klatek dla obu workloadów (A i B) na fizycznych próbkach telemetrycznych:
- `A_PARITY_MAX_DIFF = 0`
- `A_PARITY_MAE = 0.000000`
- `A_PARITY_DIFF_PIXELS = 0`
- `B_PARITY_MAX_DIFF = 0`
- `B_PARITY_MAE = 0.000000`
- `B_PARITY_DIFF_PIXELS = 0`
- **Parytet pikselowy jest bezwzględny (bajtowo zerowy) w obu przypadkach.**

---

## 8. AUDYT HUNKÓW W `intel_native_exporter.py` I DOWÓD IZOLACJI

### 8.1. Hunk-level audit pliku eksportera
W pliku `src/ffmpeg/intel_native_exporter.py` zidentyfikowano 4 hunki zmian:
1. `Hunk 1 (linie 678–756)`: Inicjalizacja i prekomputacja GPU Map (Etap 3B)
2. `Hunk 2 (linie 758–765)`: **Logowanie startowe Chart Fastpath (Etap 3C)**
3. `Hunk 3 (linie 1026–1046)`: Per-frame update GPU Map (Etap 3B)
4. `Hunk 4 (linie 1313–1322)`: Statystyki GPU Map (Etap 3B)

- `EXPORTER_TOTAL_CHANGED_HUNKS = 4`
- `EXPORTER_3B_HUNKS = 3`
- `EXPORTER_3C_HUNKS = 1`
- `EXPORTER_OTHER_HUNKS = 0`
- Wygenerowano czysty patch `scratch/exporter_3c_only.patch` zawierający wyłącznie Hunk 2.

### 8.2. Fresh-Checkout Proof (Czyste repozytorium)
Rozpakowano czysty commit bazowy `2cd43bad3fbd99e756cc651256cfe2ee27ee08a8` i nałożono wyłącznie zmiany 3C (wraz z nową polityką `LEGACY_DEFAULT`):
- `TEMP_FRESH_BASE_SHA = 2cd43bad3fbd99e756cc651256cfe2ee27ee08a8`
- `TEMP_3C_PATCH_APPLY_PASS = YES`
- `TEMP_3C_GPU_MAP_FILE_COUNT = 0`
- `TEMP_FLAG_TEST_RESULT = PASS (22/22)`
- `TEMP_INTEL_TEST_RESULT = PASS (70 passed)`
- `TEMP_PARITY_RESULT = PASS (DIFF=0)`
- `TEMP_APP_IMPORT_PASS = YES`
- `TEMP_CHART_FASTPATH_STARTUP_PASS = YES (FASTPATH_CONFIG: False default)`
- `TEMP_3C_DEPENDS_ON_3B = NO`

---

## 9. PODSUMOWANIE TOKENÓW 3C.3

```text
BRANCH=intel-225u
HEAD=2cd43bad3fbd99e756cc651256cfe2ee27ee08a8
WORKTREE_CLEAN=NO
ALL_CHANGED_FILES=[76 files]
RECALC_6_PAIR_MEAN_PERCENT=+2.0338%
RECALC_6_PAIR_MEDIAN_PERCENT=+1.7159%
RECALC_8_PAIR_MEAN_PERCENT=+2.0099%
RECALC_8_PAIR_MEDIAN_PERCENT=+1.9383%
RECALC_REF_FIRST_6_MEAN_PERCENT=+1.5670%
RECALC_OPT_FIRST_6_MEAN_PERCENT=+2.5005%
RECALC_ORDER_EFFECT_6_PERCENT=-0.9334%
RECALC_REF_FIRST_8_MEAN_PERCENT=+1.7308%
RECALC_OPT_FIRST_8_MEAN_PERCENT=+2.2890%
RECALC_ORDER_EFFECT_8_PERCENT=-0.5582%
3C2_REPORTED_ORDER_METRICS_CORRECT=NO
3C2_PRIMARY_6_OPT_WIN_COUNT=3
3C2_PRIMARY_6_REF_WIN_COUNT=3
3C2_PRIMARY_6_PAIR_GATE_PASS=NO
3C2_EXTENDED_8_OPT_WIN_COUNT=5
3C2_EXTENDED_8_REF_WIN_COUNT=3
WORKTREE_LAYOUT_PATH=C:\_DEV\BikeRideHUD-intel\def_layout.json
WORKTREE_LAYOUT_SHA256=a696d15157265c2d2abe8b5d922100a1cad1372b37216fa6acaef4d7e2c0d6e9
EXTERNAL_LAYOUT_PATH=C:\_DEV\TeleM\def_layout.json
EXTERNAL_LAYOUT_SHA256=DOES_NOT_EXIST
LAYOUT_HASH_MATCH=NO
LAYOUT_SEMANTIC_MATCH=NO
ACTUAL_LAYOUT_PATH=C:\_DEV\BikeRideHUD-intel\def_layout.json
ACTUAL_LAYOUT_EXISTS=YES
ACTUAL_LAYOUT_SHA256=a696d15157265c2d2abe8b5d922100a1cad1372b37216fa6acaef4d7e2c0d6e9
LAYOUT_SELECTED_BY_HARNESS=C:\_DEV\BikeRideHUD-intel\def_layout.json
HARNESS_LAYOUT_MATCH=YES
FINAL_LAYOUT_PATH=C:\_DEV\BikeRideHUD-intel\def_layout.json
FINAL_LAYOUT_SHA256=a696d15157265c2d2abe8b5d922100a1cad1372b37216fa6acaef4d7e2c0d6e9
FINAL_CADENCE_SIZE=1160 x 532 px (2,468,480 RGBA bytes)
FINAL_HEART_SIZE=1160 x 532 px (2,468,480 RGBA bytes)
FINAL_CHART_RAW_BYTES_FRAME=4936960 B
CHART_BYTE_ACCOUNTING_DIFFERENCE_CAUSE=Arithmetic conversion error in 3C.2 report (4.94 * 1024^2 ≈ 5,180,672 B) vs true pixel geometry 2 * 1160 * 532 * 4 = 4,936,960 B
HARNESS_PATH=C:\_Dev\BikeRideHUD-intel\scratch\run_300f_mapon.py
HARNESS_TRACKED=NO
HARNESS_SHA256=efc3f335e96f1a233c748caa9a73bba275c2b1c5a671702ce6014a564da90f12
HARNESS_COMMAND=python scratch/run_300f_mapon.py
HARNESS_ENTRYPOINT=src.ffmpeg.intel_native_exporter.export_intel_native_d3d11
HARNESS_CANONICAL_PROVENANCE=run_300f_mapon.py is the canonical Intel D3D11 runner from ETAP 2/FAZA 6; RUN_BENCHMARK_INTEL.py was a virtual report token
WORKLOAD_A_SOURCE=wideo/GX020293.mp4
WORKLOAD_A_FIT=Embedded GPMF telemetry / Poranna_jazda_na_rowerze.fit
WORKLOAD_A_FRAME_COUNT=1131
WORKLOAD_B_SOURCE=wideo/GX020297.mp4
WORKLOAD_B_FIT=Embedded GPMF telemetry / Poranna_jazda_na_rowerze.fit
WORKLOAD_B_FRAME_LIMIT=1131
GPU_MAP_ACTIVE=NO
DIRECT_SHM_ACTIVE=YES
HW_DECODE_ACTIVE=YES
ZERO_COPY_ACTIVE=YES
REGION_UPLOAD_ACTIVE=NO
ENCODE_CODEC=HEVC
ENCODE_PROFILE=Main10
ASYNC_DEPTH=8
DRAIN_WATERMARK=8
HUD_WORKER_COUNT=4
A_ENVIRONMENT_CLEAN=YES
B_ENVIRONMENT_CLEAN=YES
A1_REF_FPS=51.098
A1_OPT_FPS=55.507
A2_REF_FPS=68.705
A2_OPT_FPS=63.261
A3_REF_FPS=67.760
A3_OPT_FPS=67.621
A4_REF_FPS=67.223
A4_OPT_FPS=70.249
B1_REF_FPS=63.661
B1_OPT_FPS=64.520
B2_REF_FPS=49.201
B2_OPT_FPS=43.662
B3_REF_FPS=22.766
B3_OPT_FPS=32.039
B4_REF_FPS=40.956
B4_OPT_FPS=47.497
A_PAIR1_GAIN=+8.63%
A_PAIR2_GAIN=-7.92%
A_PAIR3_GAIN=-0.21%
A_PAIR4_GAIN=+4.50%
B_PAIR1_GAIN=+1.35%
B_PAIR2_GAIN=-11.26%
B_PAIR3_GAIN=+40.74%
B_PAIR4_GAIN=+15.97%
A_MEAN_GAIN_PERCENT=+1.25%
A_MEDIAN_GAIN_PERCENT=+2.15%
A_OPT_WIN_COUNT=2
A_REF_WIN_COUNT=2
A_REF_CV_PERCENT=13.22%
A_OPT_CV_PERCENT=10.05%
A_ORDER_EFFECT_PERCENT=+10.63%
WORKLOAD_A_GATE=FAIL
B_MEAN_GAIN_PERCENT=+11.70%
B_MEDIAN_GAIN_PERCENT=+8.66%
B_OPT_WIN_COUNT=3
B_REF_WIN_COUNT=1
B_REF_CV_PERCENT=38.66%
B_OPT_CV_PERCENT=28.64%
B_ORDER_EFFECT_PERCENT=+6.08%
WORKLOAD_B_GATE=PASS
FINAL_PERFORMANCE_CLASS=WORKLOAD_DEPENDENT
FINAL_CHART_DEFAULT_POLICY=LEGACY_DEFAULT
POLICY_SOURCE_CHANGED=YES
POLICY_TEST_RESULT=PASS (22/22)
A_PARITY_MAX_DIFF=0
A_PARITY_MAE=0.000000
A_PARITY_DIFF_PIXELS=0
B_PARITY_MAX_DIFF=0
B_PARITY_MAE=0.000000
B_PARITY_DIFF_PIXELS=0
A_NATIVE_DELTA_MS=+0.428 ms
A_UPLOAD_DELTA_MS=+0.253 ms
A_SYNC_DELTA_MS=-0.075 ms
B_NATIVE_DELTA_MS=+2.064 ms
B_UPLOAD_DELTA_MS=+1.584 ms
B_SYNC_DELTA_MS=-0.115 ms
EXPORTER_TOTAL_CHANGED_HUNKS=4
EXPORTER_3B_HUNKS=3
EXPORTER_3C_HUNKS=1
EXPORTER_OTHER_HUNKS=0
READY_FOR_3C_COMMIT=YES
SAFE_TO_CONTINUE=YES
NEXT=USER_APPROVAL_FOR_SELECTIVE_3C_COMMIT_PUSH
```
