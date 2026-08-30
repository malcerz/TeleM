# RAPORT INTEL — ETAP 5I: FINAL CHANGESET CURATION + STAGING AUDIT BEFORE COMMIT

**Autor:** AntiGRAVITY  
**Data:** 2026-08-27  
**Gałąź:** `intel-render`  
**Środowisko:** Windows 11, Intel UHD Graphics 730 (aktywny), NVIDIA Quadro P400 (ignorowana)  
**Status:** ZAKOŃCZONY (STAGED AND READY FOR COMMIT)

---

## 1. Branch / HEAD

- **Gałąź bieżąca:** `intel-render`
- **HEAD commit hash:** `e019a6b45278f09f718f528642767f505ea87934`

---

## 2. Production files staged

Pliki specyficzne dla potoku renderowania Intel / FFmpeg oraz bazowych reguł projektu:

1. [`.gitignore`](file:///f:/_DEV/TeleM/.gitignore)
   - Trwałe ignorowanie katalogu artefaktów roboczych `scratch/`.
2. [`src/ffmpeg/command_builder.py`](file:///f:/_DEV/TeleM/src/ffmpeg/command_builder.py)
   - `_fps_rational_arg()`: Precyzyjna reprezentacja ułamkowa framerate (`30000/1001`) dla parametru `-r` w FFmpeg (eliminacja gubienia klatki ogonowej w 5B).
   - `_build_stream_ffmpeg_cmd()`: Obsługa programowego dekodera HEVC Main10 (`p010le`) z respektowaniem kontraktu autorotacji FFmpeg (5D) oraz usunięcie nieaktywnego `-global_quality 24` przy VBR `-b:v 40M` (4K).
3. [`src/ffmpeg/streaming.py`](file:///f:/_DEV/TeleM/src/ffmpeg/streaming.py)
   - Odizolowanie potoku Intel HDR CPU_REFERENCE (dekoder programowy 10-bit P010 -> hevc_qsv na karcie Intel).
   - Usunięcie wymuszonego `-noautorotate` dla Intela (5D — prawidłowa orientacja bez podwójnych obrotów matrycy kontenera).
   - Utwardzenie cyklu życia pipe writera: czyste osuszanie kolejki z wartownikiem `None` w trybie FIFO przy EOF (5B) oraz natychmiastowe porzucanie (`writer_discard_pending`) przy Cancel/Error.
   - Rozszerzenie aliasów wskaźników telemetrycznych (prędkość, wysokość, dystans) dla spójności źródeł (5E).
4. [`src/ffmpeg/worker_cache.py`](file:///f:/_DEV/TeleM/src/ffmpeg/worker_cache.py)
   - Rozszerzona detekcja źródeł FIT/GPX/GPMF dla wskaźników `fit_speed_text`, `fit_altitude_text`, `fit_distance_text` w procesach workerów (5E).

---

## 3. Shared-code files staged

Pliki współdzielone między wszystkimi backendami (sprawdzone pod kątem neutralności vendorowej — brak warunków `if intel:`):

1. [`src/benchmark.py`](file:///f:/_DEV/TeleM/src/benchmark.py)
   - Dodanie miar statystycznych `median` oraz `p99` do `BenchmarkTracker` (narzędzie pomiarowe A/B).
2. [`src/gui/qt/_mixins/preview_mixin.py`](file:///f:/_DEV/TeleM/src/gui/qt/_mixins/preview_mixin.py)
   - Spójna rezolucja źródeł prędkości i wysokości w podglądzie edytora GUI.
3. [`src/gui/qt/_mixins/render_mixin.py`](file:///f:/_DEV/TeleM/src/gui/qt/_mixins/render_mixin.py)
   - Wykorzystanie aktywnych próbek `speed_samples`, `track_samples`, `alt_samples` z instancji telemetrycznej podczas eksportu (eliminacja rozbieżności z ponownej ekstrakcji).
4. [`src/gui/telemetry_manager.py`](file:///f:/_DEV/TeleM/src/gui/telemetry_manager.py)
   - Poprawka semantyczna generatora wskaźników: zakres `0..100%` dla pól baterii zamiast min/max z sesji FIT (5G/5H).
5. [`src/indicators/bar.py`](file:///f:/_DEV/TeleM/src/indicators/bar.py)
   - Niezależność od rozdzielczości: obliczanie `size_px` pionowych wskaźników linijkowych względem `canvas_h` (5E).
6. [`src/indicators/compositor.py`](file:///f:/_DEV/TeleM/src/indicators/compositor.py)
   - Respektowanie konfiguracji `auto_scale=False` dla wskaźników prędkości i wysokości (5E).
7. [`src/indicators/dispatcher.py`](file:///f:/_DEV/TeleM/src/indicators/dispatcher.py)
   - Poprawka skalowania geometrycznego wskaźników wartości (5E).
8. [`src/indicators/frame_data.py`](file:///f:/_DEV/TeleM/src/indicators/frame_data.py)
   - Spójna rezolucja źródeł w `prepare_overlay_frame_data`.
9. [`src/telemetry_precompute.py`](file:///f:/_DEV/TeleM/src/telemetry_precompute.py)
   - Normalizacja znaczników czasu do kanonicznego `naive UTC` (likwidacja błędu odejmowania aware/naive w trybie PRECOMPUTED - 5D).
   - Pełna obsługa prekomputacji dla wskaźnika przechyłu (`lean_indicator` - gyro roll oraz grade slope - 5E).

---

## 4. Test files staged

Trwałe testy regresyjne zweryfikowane pod kątem braku lokalnych ścieżek bezwzględnych i zależności od tymczasowych plików:

1. [`tests/test_etap5d_real_gui_regressions.py`](file:///f:/_DEV/TeleM/tests/test_etap5d_real_gui_regressions.py) (NEW)
   - Testy wyboru REGION/FULL dla realnych układów GUI, kontraktu stref czasowych prekomputacji oraz braku sztucznych obrotów w grafie filtrów.
2. [`tests/test_etap5e_preview_export_parity.py`](file:///f:/_DEV/TeleM/tests/test_etap5e_preview_export_parity.py) (NEW)
   - Testy paritetu podglądu i eksportu: `lean_indicator`, respektowanie flagi `auto_scale`, spójność aliasów źródeł.
3. [`tests/test_etap5h_writer_queue.py`](file:///f:/_DEV/TeleM/tests/test_etap5h_writer_queue.py) (MODIFIED)
   - Testy jednostkowe osuszania kolejki writera oraz zachowania przy Cancel/EOF.
4. [`tests/test_render_cancel_process_lifecycle.py`](file:///f:/_DEV/TeleM/tests/test_render_cancel_process_lifecycle.py) (MODIFIED)
   - Testy cyklu życia procesu FFmpeg i bezpiecznego anulowania.
5. [`tests/test_video_helpers.py`](file:///f:/_DEV/TeleM/tests/test_video_helpers.py) (MODIFIED)
   - Testy decyzji HUD region, skalowania bazowego w CPU_REFERENCE, ułamkowego framerate oraz kontraktu kontroli przepływności QSV.

---

## 5. Documentation staged/not staged

Zgodnie z wytycznymi raporty historyczne i techniczne zostały zaklasyfikowane jako **DOCUMENTATION — OPTIONAL SEPARATE COMMIT** i pozostawione w stanie **unstaged** (untracked):

- `Raporty/RAPORT_AUDYT_NIEZATWIERDZONE_ZMIANY_ETAP_3B.md`
- `Raporty/RAPORT_INTEL_ETAP_3B_AB_PARITY_PERF.md`
- `Raporty/RAPORT_INTEL_ETAP_3C_HUD_REGION.md`
- `Raporty/RAPORT_INTEL_ETAP_4A_CPU_REFERENCE_HUD_REGION.md`
- `Raporty/RAPORT_INTEL_ETAP_4B_4C_PRODUCTION_OPTIMIZATION_OX.md`
- `Raporty/RAPORT_INTEL_ETAP_4D_HDR_P010_NATIVE_OX.md`
- `Raporty/RAPORT_INTEL_ETAP_4E_P010_CPU_OVERLAY_OX.md`
- `Raporty/RAPORT_INTEL_ETAP_4F_10BIT_REGION_COMPOSITOR_OX.md`
- `Raporty/RAPORT_INTEL_ETAP_4G_P0_VIDEO_PATH_OX.md`
- `Raporty/RAPORT_INTEL_ETAP_4H_HEVC_QSV_QUALITY_PERF_OX.md`
- `Raporty/RAPORT_INTEL_ETAP_4I_QP_REALTIME_FRONTIER_OX.md`
- `Raporty/RAPORT_INTEL_ETAP_4J_VBR_PRODUCTION_OX.md`
- `Raporty/RAPORT_INTEL_ETAP_4K_QSV_RC_CONTRACT_OX.md`
- `Raporty/RAPORT_INTEL_ETAP_4_PIPELINE_BOTTLENECK_AUDIT_OX.md`
- `Raporty/RAPORT_INTEL_ETAP_5A_PRODUCTION_HARDENING_OX.md`
- `Raporty/RAPORT_INTEL_ETAP_5B_QSV_TAIL_LOSS_OX.md`
- `Raporty/RAPORT_INTEL_ETAP_5C_FINAL_COMMIT_AUDIT_OX.md`
- `Raporty/RAPORT_INTEL_ETAP_5D_REAL_GUI_REGRESSION_OX.md`
- `Raporty/RAPORT_INTEL_ETAP_5E_PREVIEW_EXPORT_PARITY_ANTIGRAVITY.md`
- `Raporty/RAPORT_INTEL_ETAP_5F_REAL_GUI_VALIDATION_ANTIGRAVITY.md`
- `Raporty/RAPORT_INTEL_ETAP_5G_EXACT_FRAME_TELEMETRY_PARITY_ANTIGRAVITY.md`
- `Raporty/RAPORT_INTEL_ETAP_5H_CANONICAL_PROJECT_PROOF_ANTIGRAVITY.md`
- `Raporty/RAPORT_INTEL_ETAP_5I_FINAL_CHANGESET_STAGING_ANTIGRAVITY.md`
- `Raporty/RAPORT_INTEL_HOTFIX_10BIT_CPU_REFERENCE.md`
- `Raporty/RAPORT_INTEL_HOTFIX_2_QSV_HWDOWNLOAD_SYNC.md`

---

## 6. User data excluded

- [`def_layout.json`](file:///f:/_DEV/TeleM/def_layout.json):
  - Zawiera modyfikację użytkownika (`label_count: 4 -> 5`).
  - **Status:** EXCLUDED FROM STAGING (pozostawiona nienaruszona w working tree jako `modified, unstaged`).

---

## 7. Generated/scratch excluded

Pliki tymczasowe wykluczone ze stagingu:
- `NUL-bad` (log z testów etapu 5A)
- `etap5f_preview_values.json` (zrzut diagnostyczny)
- `etap5f_render_stats.json` (zrzut diagnostyczny)

---

## 8. Suspicious/unrelated findings

- **Brak.** Kod w indeksie stagingu w 100% dotyczy prac Intel/HDR/Parity/Hardening. Ścieżki AMD, NVIDIA i ogólny silnik CPU Reference pozostały w pełni nienaruszone.

---

## 9. Decyzje szczegółowe

### `.gitignore`
- **Decyzja:** STAGED.
- **Uzasadnienie:** Trwałe wykluczenie katalogu roboczego `scratch/` chroni repozytorium przed przypadkowym commitowaniem zrzutów diagnostycznych.

### `src/benchmark.py`
- **Decyzja:** STAGED.
- **Uzasadnienie:** Rozszerzenie `BenchmarkTracker` o medianę i 99. percentyl jest czystą, nietworzącą skutków ubocznych poprawką narzędzi benchmarkowych w repozytorium.

### `def_layout.json`
- **Decyzja:** EXCLUDED (Unstaged).
- **Uzasadnienie:** Zmiana `label_count: 4 -> 5` jest prywatną konfiguracją użytkownika i nie może trafić do commita silnika.

---

## 10. Staged diff summary

Statystyka indeksu Git (`git diff --cached --stat`):
```text
 .gitignore                                    |   3 +
 src/benchmark.py                              |   3 +
 src/ffmpeg/command_builder.py                 |  58 ++++-
 src/ffmpeg/streaming.py                       | 283 +++++++++++++++++++++--
 src/ffmpeg/worker_cache.py                    |   9 +-
 src/gui/qt/_mixins/preview_mixin.py           |   6 +-
 src/gui/qt/_mixins/render_mixin.py            |  18 +-
 src/gui/telemetry_manager.py                  |   7 +
 src/indicators/bar.py                         |   6 +-
 src/indicators/compositor.py                  |  14 +-
 src/indicators/dispatcher.py                  |   4 +-
 src/indicators/frame_data.py                  |   8 +-
 src/telemetry_precompute.py                   |  88 ++++++--
 tests/test_etap5d_real_gui_regressions.py     | 162 +++++++++++++
 tests/test_etap5e_preview_export_parity.py    | 213 +++++++++++++++++
 tests/test_etap5h_writer_queue.py             |  79 +++++++
 tests/test_render_cancel_process_lifecycle.py |  29 ++-
 tests/test_video_helpers.py                   | 314 +++++++++++++++++++++++++-
 18 files changed, 1240 insertions(+), 64 deletions(-)
```

---

## 11. Unstaged diff summary

Statystyka niezatwierdzonego diffa (`git diff --stat`):
```text
 def_layout.json | 2 +-
 1 file changed, 1 insertion(+), 1 deletion(-)
```

---

## 12. Regression result

Uruchomiono pełny zestaw testów (`python -m pytest -q`):
```text
30 failed, 1111 passed, 22 skipped, 5 errors in 73.00s
```
- **Zgodność z baseline 5H:** 100% identyczny zestaw znanych błędów/braków danych zewnętrznych (`Video/Jazda_na_rowerze_w_porze_lunchu.fit` itp.).
- **Nowe błędy (failures/errors):** **0** (ZERO).
- **Delta:** **0**.

---

## 13. Final contract checklist

- [x] **Intel GPU Isolation:** Dynamiczne wykrywanie `vendor = 0x8086`, Quadro P400 ignorowana.
- [x] **HDR 10-bit Production Path:** Dekodowanie programowe Main10 + CPU_REFERENCE HUD + `hevc_qsv` (10-bit P010).
- [x] **QSV RC Contract:** `hevc_qsv -b:v 40M -preset veryfast` (brak martwego `-global_quality`).
- [x] **Frame / Tail Contract:** Precyzyjne ułamkowe FPS `-r 30000/1001`, pełny drain kolejki, 1131/1131 klatek.
- [x] **Rotation Contract:** Prawidłowa obsługa autorotacji FFmpeg dla Intela (brak podwójnych obrotów).
- [x] **Telemetry Precomputation:** Format `naive UTC` wolny od błędów stref czasowych, obsługa `lean_indicator`.
- [x] **Preview ↔ Export Parity:** Identyczne wartości telemetrii na identycznych klatkach, respektowanie `auto_scale=False`.
- [x] **Battery Semantic Range:** Wskaźnik baterii generowany w zakresie `0..100%`.
- [x] **Cross-Vendor Safety:** Ścieżki AMD i NVIDIA nienaruszone.

---

## 14. Proposed commit message

```text
Intel: harden HDR pipeline, writer lifecycle, and preview-export parity

- Enforce software HEVC Main10 decode with CPU_REFERENCE HUD compositor and hevc_qsv 10-bit output
- Isolate Intel QSV device dynamically and ignore non-Intel GPUs under INTEL_FORCE
- Fix export tail-frame loss via rational framerate (-r 30000/1001) and FIFO sentinel queue draining
- Correct Intel rotation handling relying on FFmpeg autorotate without duplicate flips
- Harden telemetry precompute with canonical naive UTC normalization and lean_indicator support
- Align Editor Preview and Export telemetry source resolution and auto_scale semantics
- Fix newly generated battery indicator to use canonical 0..100% semantic range
- Add comprehensive regression test suite for Intel pipeline and preview/export parity
```

---

## 15. Verdict

```text
INTEL ETAP 5I: STAGED AND READY FOR COMMIT
```
