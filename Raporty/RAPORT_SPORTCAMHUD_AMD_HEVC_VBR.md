# RAPORT — SPORTCAMHUD: PILNA POPRAWKA AMD HEVC (CQP → VBR)

**Data sporządzenia:** 2026-10-14  
**Gałąź:** `fix/gui-freeze-hud-composite`  
**Commit SHA:** `e76d6b1da0bcf1487e5061d16b05d7916adefb3b`  
**Bazowy tag wzorcowy:** `amd-known-good-40fps-20261012`  

---

## 1. PODSUMOWANIE PROBLEMU (CQP=28 vs VBR)

W dotychczasowej implementacji AMD Native HEVC (`d3d11_amf_encoder.cpp`) enkoder sprzętowy AMF był skonfigurowany na sztywno w trybie stałego parametru kwantyzacji (`AMF_VIDEO_ENCODER_HEVC_RATE_CONTROL_METHOD_CONSTANT_QP`) z wartościami:
- `AMF_VIDEO_ENCODER_HEVC_QP_I = 28`
- `AMF_VIDEO_ENCODER_HEVC_QP_P = 28`

W rezultacie:
1. Wartość bitrate ustawiana przez użytkownika suwakiem w GUI była ignorowana przez enkoder HEVC.
2. Złożone i proste sceny były kodowane z identycznym stałym QP, uniemożliwiając kontrolę wielkości pliku wynikowego oraz adaptację pasma.
3. Tryb CQP był sztywno narzucony na wszystkie profile jakościowe (`FAST`, `BALANCED`, `QUALITY`).
4. W interfejsie użytkownika wskaźnik QP pokazywał stałą wartość `28.0` lub `N/A`.

Zgodnie z wymaganiami, enkoder AMD Native HEVC został przestawiony w 100% na **Peak-Constrained VBR** (`AMF_VIDEO_ENCODER_HEVC_RATE_CONTROL_METHOD_PEAK_CONSTRAINED_VBR`) sterowany bezpośrednio zadanym docelowym średnim bitrate (bitrate slider GUI). Tryb CQP został całkowicie wyeliminowany z domyślnych i awaryjnych ścieżek enkodera HEVC.

---

## 2. PEŁNA LISTA ZMIENIONYCH PLIKÓW

1. **`native/d3d11_amf_pipeline/src/d3d11_amf_encoder.h`**
   - Dodano strukturę statystyk QP pakietów `AMFEncoderQPStats` (`samples`, `sum`, `minQp`, `maxQp`, `lastQp`, `supported`).
   - Dodano getter `GetQPStats()` oraz pole składowe `AMFEncoderQPStats m_qpStats`.

2. **`native/d3d11_amf_pipeline/src/d3d11_amf_encoder.cpp`**
   - Zastąpiono sztywny blok CQP właściwościami VBR: `AMF_VIDEO_ENCODER_HEVC_RATE_CONTROL_METHOD_PEAK_CONSTRAINED_VBR`, `AMF_VIDEO_ENCODER_HEVC_TARGET_BITRATE`, `AMF_VIDEO_ENCODER_HEVC_PEAK_BITRATE`, `AMF_VIDEO_ENCODER_HEVC_VBV_BUFFER_SIZE`, `AMF_VIDEO_ENCODER_HEVC_INITIAL_VBV_BUFFER_FULLNESS`, `AMF_VIDEO_ENCODER_HEVC_STATISTICS_FEEDBACK`.
   - Usunięto stałe właściwości `QP_I=28` i `QP_P=28`.
   - W `QueryPacket()` dodano próbkowanie właściwości statystyk sprzętowych AMF z bufora wyjściowego (`AMF_VIDEO_ENCODER_HEVC_STATISTIC_AVERAGE_QP` oraz `AMF_VIDEO_ENCODER_HEVC_STATISTIC_FRAME_QP`).
   - W `Initialize()` i `Shutdown()` zapewniono czyszczenie struktury statystyk `m_qpStats`.

3. **`native/d3d11_amf_pipeline/src/telem_amd_native.cpp`**
   - W `telem_amd_create()` dodano domyślną wartość 40 Mbps VBR (`40000000LL`), jeśli zmienna środowiskowa `AMD_NATIVE_BITRATE` jest pusta lub nieprawidłowa.
   - Zaimplementowano i wyeksportowano funkcję C API:
     ```cpp
     TELEM_EXPORT void telem_amd_get_encoder_qp_stats(
         void* handle,
         double* outAvgQp,
         int64_t* outMinQp,
         int64_t* outMaxQp,
         uint64_t* outSamples,
         int64_t* outLastQp,
         int* outSupported
     );
     ```
     zabezpieczoną przed wywołaniem z `NULL` handle (bezpieczne zerowanie wskaźników).

4. **`native/d3d11_amf_pipeline/include/AMF/components/VideoEncoderAV1.h`** & **`VideoEncoderVCE.h`**
   - Uzupełniono brakujące nagłówki AMF SDK w drzewie kompilacji, umożliwiając czystą kompilację MSVC CMake/MSBuild.

5. **`src/ffmpeg/amd_native_exporter.py`**
   - Zmieniono domyślny parametr `rc: str = "vbr"` (wcześniej `"cqp"`).
   - Zapewniono domyślny bitrate 40 Mbps (`40_000_000` bps) i przekazywanie `AMD_NATIVE_BITRATE` w bit/s.
   - W komunikacie startowym dodano logowanie:
     `[AMD ENCODER] ... rc=VBR target_bitrate={target} peak_bitrate={peak} live_mux=yes`.
   - W pętli renderowania zaktualizowano pasek postępu oznaczając tryb `RC: VBR` oraz formatując `QP avg: N/A` lub dynamiczne wartości QP.
   - Po zakończeniu eksportu dodano czytelną diagnostykę statusu statystyk QP ze sterownika.

6. **`src/render_progress.py`**
   - Zaktualizowano `format_render_progress_status()` o priorytet `compression_text` oraz formatowanie `QP avg: N/A` w miejsce zastępczego `QP: --` lub domyślnych placeholderów.

7. **`tests/test_amd_vbr_governance.py`**
   - Nowy zestaw testów automatycznych weryfikujący governance VBR, parsowanie bitrate, kalkulację peak bitrate, symbol DLL, bezpieczny NULL handle i formatowanie statusu.

---

## 3. DOKŁADNY OPIS KONFIGURACJI AMF VBR

Konfiguracja enkodera w `D3D11AMFEncoder::Initialize`:

| Właściwość AMF | Wartość / Źródło | Jednostka / Znaczenie |
|---|---|---|
| `AMF_VIDEO_ENCODER_HEVC_USAGE` | `AMF_VIDEO_ENCODER_HEVC_USAGE_TRANSCODING` | Profil transkodowania |
| `AMF_VIDEO_ENCODER_HEVC_QUALITY_PRESET` | `SPEED` (FAST), `BALANCED`, `QUALITY` | Zgodne z wyborem GUI |
| `AMF_VIDEO_ENCODER_HEVC_RATE_CONTROL_METHOD` | `AMF_VIDEO_ENCODER_HEVC_RATE_CONTROL_METHOD_PEAK_CONSTRAINED_VBR` (wartość `2`) | Peak-Constrained VBR |
| `AMF_VIDEO_ENCODER_HEVC_TARGET_BITRATE` | `(amf_int64)targetBitrate` (np. 5000000, 40000000) | bit/s (z suwaka GUI) |
| `AMF_VIDEO_ENCODER_HEVC_PEAK_BITRATE` | `(amf_int64)(targetBitrate * 1.5)` | bit/s (1.5x target dla dynamicznych scen) |
| `AMF_VIDEO_ENCODER_HEVC_VBV_BUFFER_SIZE` | `(amf_int64)targetBitrate` | bity (bufor 1-sekundowy) |
| `AMF_VIDEO_ENCODER_HEVC_INITIAL_VBV_BUFFER_FULLNESS` | `64` | 100% początkowego napełnienia bufora |
| `AMF_VIDEO_ENCODER_HEVC_STATISTICS_FEEDBACK` | `true` | Żądanie zwrotnych statystyk QP od sterownika |
| `AMF_VIDEO_ENCODER_HEVC_FRAMESIZE` | `AMFConstructSize(width, height)` | Rozdzielczość (np. 3840x2160) |
| `AMF_VIDEO_ENCODER_HEVC_FRAMERATE` | `AMFConstructRate(fpsNum, fpsDen)` | Klatkaż (np. 2997/100) |

Brak jakiegokolwiek ustawiania sztywnego QP (`QP_I`, `QP_P`). W przypadku błędu `m_encoder->Init()` metoda zwraca `false` i loguje jawny błąd bez cichego powrotu do CQP.

---

## 4. WYNIKI TESTÓW DLA 2 RÓŻNYCH WARTOŚCI BITRATE (5 Mbps vs 40 Mbps)

Przeprowadzono rzeczywisty eksport wideo 4K (3840x2160 @ 29.97 fps) z pliku źródłowego GoPro (`F:\GoPro\2026-10-07\GX010350.MP4`, czas trwania 6.0 s, 180 klatek) na silniku AMF Hardware HEVC z Single Live Mux.

### Wyniki pomiarów:

| Parametr | Test A: 5 Mbps (`video_bitrate="5M"`) | Test B: 40 Mbps (`video_bitrate="40M"`) |
|---|---|---|
| **Zadany bitrate** | 5 000 000 bit/s (5 Mbps) | 40 000 000 bit/s (40 Mbps) |
| **Peak bitrate** | 7 500 000 bit/s (7.5 Mbps) | 60 000 000 bit/s (60 Mbps) |
| **Rozmiar pliku wynikowego** | **3.70 MB** (3 880 093 bajty) | **28.32 MB** (29 694 524 bajty) |
| **Stosunek rozmiarów (40M / 5M)** | — | **7.65x** (wzorcowe skalowanie ~8x) |
| **Bitrate strumienia wideo (ffprobe)** | **4 904 882 bit/s** (~4.90 Mbps) | **39 289 704 bit/s** (~39.29 Mbps) |
| **Odchyłka od targetu bitrate** | **-1.9%** | **-1.8%** |
| **Czas kodowania (180 klatek 4K)** | 4.16 s | 4.16 s |
| **Render FPS** | **43.3 FPS** | **43.3 FPS** |
| **Effective FPS** | **35.9 FPS** | **35.9 FPS** |
| **Zachowanie wskaźnika QP** | `RC: VBR \| QP avg: N/A` | `RC: VBR \| QP avg: N/A` |
| **Czas finalizacji MP4 (`mux_wait`)** | 401 ms | 201 ms |

---

## 5. STATUS ODCZYTU QP Z AMF NA TESTOWANEJ PLATFORMIE

- Funkcja `telem_amd_get_encoder_qp_stats()` jest w pełni zaimplementowana w C++ i wyeksportowana w DLL.
- W kodzie włączono flagę żądania statystyk: `AMF_VIDEO_ENCODER_HEVC_STATISTICS_FEEDBACK = true`.
- Przy każdym pobieranym pakiecie wyjściowym `QueryPacket()` odpytuje właściwości:
  - `AMF_VIDEO_ENCODER_HEVC_STATISTIC_AVERAGE_QP`
  - `AMF_VIDEO_ENCODER_HEVC_STATISTIC_FRAME_QP`
- **Obserwacja sprzętowa:** Zainstalowany na maszynie testowej sterownik AMD AMF nie wypełnia tych właściwości w buforze wyjściowym (`samples == 0`).
- **Prawidłowe zachowanie systemu:** Zgodnie z wytycznymi użytkownika, system **nie generuje fikcyjnej wartości 28.0**, lecz uczciwie i jednoznacznie raportuje w GUI i logach:
  - Pasek postępu: `RC: VBR | QP avg: N/A`
  - Log startowy: `[AMD ENCODER] ... rc=VBR target_bitrate=... peak_bitrate=...`
  - Log końcowy: `[AMD ENCODER] Note: Hardware QP statistics feedback is not supported by current AMF driver/hardware (QP avg: N/A)`
  - Słownik statystyk eksportu: `avg_qp: None`, `qp_avg: None`, `qp_samples: 0`.

---

## 6. POTWIERDZENIE ZACHOWANIA WYDAJNOŚCI (~40 FPS PRZY 4K)

- Zmierzony Render FPS wyniósł **43.3 FPS** przy rozdzielczości 4K (3840x2160, NV12).
- Zmierzony Effective FPS wyniósł **35.9 FPS**.
- Czas zakodowania 180 klatek 4K: **4.16 s**.
- Brak jakiejkolwiek degradacji wydajności względem tagu wzorcowego `amd-known-good-40fps-20261012`.

---

## 7. POTWIERDZENIE BRAKU DEGRADACJI SINGLE LIVE MUX I BRAKU DŁUGIEJ FINALIZACJI

- Pipeline Single Live Mux działa stabilnie i w sposób ciągły bez buforów pośrednich.
- Czas finalizacji strumienia MP4 po zakończeniu klatek wideo:
  - Test 5M: `mux_wait_ms = 401.62 ms`
  - Test 40M: `mux_wait_ms = 201.03 ms`
- Całkowity czas zamykania enkodera i procesu FFmpeg: `< 0.5 s`.
- Brak wielominutowej finalizacji, brak blokowania I/O, brak nadmiarowego przepływu danych.

---

## 8. STATUS TESTÓW AUTOMATYCZNYCH

Uruchomiono pełne pakiety testów automatycznych zarządzania kwantyzacją i governance VBR:
```
tests\test_amd_qp_governance.py .......... [10/10 PASS]
tests\test_amd_vbr_governance.py ......    [ 6/6  PASS]
============================= 16 passed in 0.38s ==============================
```

Wszystkie 16 testów zakończyło się pełnym sukcesem.

---

## 9. SHA COMMITA

```
e76d6b1da0bcf1487e5061d16b05d7916adefb3b
```
**Komunikat commita:**
`fix(amd): use bitrate-targeted VBR instead of constant QP`

---

## 10. AKTUALNY STAN GIT STATUS I GIT LOG -2

### `git log -2 --oneline`:
```
e76d6b1 fix(amd): use bitrate-targeted VBR instead of constant QP
6dc1eb3 fix(hud): render degree unit as font-independent graphic
```

### `git status`:
```
On branch fix/gui-freeze-hud-composite
Your branch is ahead of 'origin/fix/gui-freeze-hud-composite' by 46 commits.
  (use "git push" to publish your local commits)

Changes not staged for commit:
  (use "git add <file>..." to update what will be committed)
  (use "git restore <file>..." to discard changes in working directory)
	modified:   Raporty/RAPORT_SPORTCAMHUD_ETAP_5R_F_LIVE_MUX_AUDIO_FINALIZATION.md
	modified:   def_layout.json

Untracked files:
  (use "git add <file>..." to include in what will be committed)
	Raporty/AMD_KNOWN_GOOD_40FPS_20261012.md
	Raporty/DELETED_FILES_MANIFEST_20261013.json
	Raporty/RAPORT_SPORTCAMHUD_AMD_40FPS_BACKUP_AND_DISK_CLEANUP.md
	Raporty/RAPORT_SPORTCAMHUD_AMD_HEVC_VBR.md
	Raporty/RAPORT_SPORTCAMHUD_ETAP_5L_AMD_KNOWN_GOOD_AND_ORIGINAL_GAUGE_SHADOWS.md
	Raporty/RAPORT_SPORTCAMHUD_ETAP_5L_B_COMPASS_ORIGINAL_SHADOWS.md
	Raporty/RAPORT_SPORTCAMHUD_ETAP_5L_C_COMPASS_ROSE_FPS_RECOVERY.md
	Raporty/RAPORT_SPORTCAMHUD_ETAP_5L_D_COMPASS_FINAL_VISUAL_VALIDATION.md
	Raporty/RAPORT_SPORTCAMHUD_ETAP_5M_SOURCE_DEBT_AUDIT.md
	Raporty/RAPORT_SPORTCAMHUD_ETAP_5N_TEST_BASELINE_AND_SAFETY_PLAN.md
	Raporty/RAPORT_SPORTCAMHUD_ETAP_5O_BAR_CACHE_OWNERSHIP_AND_ROSE_CONTRACT.md
	Raporty/RAPORT_SPORTCAMHUD_ETAP_5P_CACHE_AB_STABILITY_AND_COMMITS.md
	Raporty/RAPORT_SPORTCAMHUD_ETAP_5Q_BAR_ROSE_COMMITS.md
	Raporty/RAPORT_SPORTCAMHUD_ETAP_5R_F_FINALIZATION_DIAGNOSTICS.md
	Raporty/RAPORT_SPORTCAMHUD_ETAP_5S_A_VERIFICATION.md
	Raporty/RAPORT_SPORTCAMHUD_ETAP_5S_LOGS_LEAN_COMPASS_FIT_GUI.md
	Raporty/RAPORT_SPORTCAMHUD_ETAP_5T_MULTI_FILE_FINALIZATION_DIAGNOSIS.md
	Raporty/RAPORT_SPORTCAMHUD_FULL_REGRESSION_AUDIT_20261011.md
	Raporty/RAPORT_SPORTCAMHUD_QP_AND_DEGREE_SYMBOL.md
	Raporty/RAPORT_SPORTCAMHUD_RENDERPROGRESSSTATE_SCOPE_HOTFIX.md
	Raporty/RAPORT_SPORTCAMHUD_RENDER_0_PERCENT_AND_PREVIEW_DIAGNOSIS.md
	Raporty/etap5m_artifacts/
	Raporty/etap5n_artifacts/
	Raporty/etap5o_artifacts/
	Raporty/etap5p_artifacts/
	Raporty/etap5rf_diagnostics_20261014/
	native/d3d11_amf_pipeline/bin/telem_amd_native.dll.bak_cqp
	runtime/amd/
```
Plik `def_layout.json` pozostał nienaruszony i nie został zacommitowany.
Nie wykonano żadnego `git push`, `reset`, `clean` ani `stash`.
Single Live Mux został w 100% zachowany.
