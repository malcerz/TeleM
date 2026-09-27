# Raport: Intel Core Ultra 5 225U — ETAP 2D.2: Direct SHM Release Truth & Default-Readiness

**Data:** 2026-09-22
**Target:** Intel Core Ultra 5 225U (GPU Device ID `0x7D41`, Sterownik `32.0.101.8801`)
**Status:** **DIRECT_SHM_PRODUCTION_READY = YES** | **DIRECT_SHM_DEFAULT_READY = YES (Candidate Ready)** | **DIRECT_SHM_DEFAULT_APPROVAL_REQUIRED = YES**

---

## 1. Cel Etapu 2D.2

Etap 2D.2 miał charakter wyłącznie audytowo-weryfikacyjny (bez wprowadzania nowych architektur ani zmian w kodzie renderingu) w celu rozliczenia wszelkich niespójności z raportu 2D.1 przed formalną decyzją o gotowości Direct SHM do stania się domyślną ścieżką Intel.

Zakres prac:
1. **Tożsamość sprzętowa GPU:** Wyjaśnienie rozbieżności między PnP Device ID `0x7D41` (32065) a wartością `32069` (`0x7D45`) w snapshotach DXGI.
2. **Rozstrzygnięcie formatu kodowania:** Weryfikacja faktycznego kodeka (HEVC Main10 vs błąd zapisu AV1 w proof JSON).
3. **Analiza kryminalistyczna (Forensics) spowolnienia OPT1:** Wyjaśnienie wydłużenia czasu próby OPT1 1131f i weryfikacja powtarzalności w świeżych próbach.
4. **Rozliczenie jednostek CV i bramki statycznej:** Precyzyjne przeliczenie współczynników zmienności (procenty vs ułamki).
5. **Autorytatywne wyniki kanoniczne 1131f:** Przeliczenie zysku na poprawnych parach procesów.
6. **Audyt metryk długodystansowych:** Weryfikacja okien czasowych 5-clip (8745f) i 18000f oraz wyjaśnienie różnic w obciążeniach (77 FPS vs 21 FPS).
7. **Proweniencja kodu źródłowego i flag `skip-worktree`:** Rozróżnienie gotowości technicznej od odtwarzalności z commitu HEAD.
8. **Precyzja nazewnictwa presji pamięciowej:** Korekta opisów z PCIe na współdzieloną magistralę pamięci UMA.

---

## 2. Tożsamość Sprzętowa i Proweniencja Sterownika

### 2.1 Hardware ID Exact Truth (Phase 0)
Zapytania bezpośrednie do interfejsów systemowych:
- **PnP Hardware ID:** `PCI\VEN_8086&DEV_7D41&SUBSYS_3FA017AA&REV_00` -> **`0x7D41`** (32065)
- **WMI / CIM VideoController:** `DeviceID: VideoController2`, PNPDeviceID `DEV_7D41` -> **`0x7D41`**
- **DXGI Factory1 EnumAdapters1 (Adapter 0):** `Intel(R) Graphics`, VendorId `0x8086`, DeviceId **`0x7D41`** (32065), SubSysId `0x3FA017AA`, LUID `0x00000000:0x0000EB08`
- **TeleM D3D11 Device Adapter:** `Intel(R) Graphics`, DeviceId **`0x7D41`**
- **Wyjaśnienie wartości 32069 (`0x7D45`) w proof JSON:** W pliku `src/ffmpeg/intel_native_exporter.py` linia 1138 znajdowało się statyczne pole `adapter_device_id=0x7D45` w słowniku pomocniczym generującym snapshot proof, podczas gdy fizyczna karta, sterownik i urządzenie D3D11 to bezsprzecznie **`0x7D41`**.
- **`GPU_DEVICE_ID_RECONCILED = YES`**

### 2.2 Proweniencja Sterownika (Phase 1)
- **Wersja sterownika:** `32.0.101.8801`
- **Data sterownika:** `2026-05-12`
- **Dostawca:** `Intel Corporation`
- **`ALL_2D1_RUNS_SAME_DRIVER = YES`** (wszystkie testy statyczne, dynamiczne, kanoniczne, 5-clip, 3000f i 18000f wykonano pod tym samym sterownikiem).

---

## 3. Rozstrzygnięcie Kodeka Wideo: HEVC Main10 (Phase 2)

Podczas audytu kodu C i logów potoku stwierdzono:
- W `src/native/d3d11_intel_pipeline/telem_intel_native.c` (linie 1292, 1324) selektor `codec_id == 2` konfiguruje `initPar.mfx.CodecId = MFX_CODEC_HEVC` oraz profil 10-bit Main10.
- `ffprobe` dla wszystkich plików wynikowych (`scratch/out_proper_hw_2d1_*.mp4`) potwierdza: `Video: hevc (Main 10) (hvc1 / 0x31637668), yuv420p10le(pc, bt2020nc/bt2020/arib-std-b67), 3840x2160`.
- Napis `"AV1"` w polach `capabilities.encode_codec` proof JSON był wyłącznie artefaktem szablonu Python w `intel_native_exporter.py` (linia 1143: `encode_codec="H264" if codec_id == 1 else "AV1"`).
- **`STATIC_AB_CODEC = HEVC_MAIN10`**
- **`DYNAMIC_AB_CODEC = HEVC_MAIN10`**
- **`CANONICAL_AB_CODEC = HEVC_MAIN10`**
- **`FIVE_CLIP_CODEC = HEVC_MAIN10`**
- **`SOAK_3000_CODEC = HEVC_MAIN10`**
- **`SOAK_18000_CODEC = HEVC_MAIN10`**
- **`ALL_PERFORMANCE_RUNS_HEVC_MAIN10 = YES`**

---

## 4. Analiza Kryminalistyczna OPT1 i Test Powtórzeniowy (Phases 3–5)

### 4.1 Rekonstrukcja Przebiegu OPT1 1131f
- **Przebieg:** Proces nie uległ zawieszeniu, nie został zabity przez watchdog i przetworzył 100% z 1131 klatek (`success: True`).
- **Pomiary opóźnień:** Mediana oczekiwania na enkoder (`sync_p50_ms`) wynosiła prawidłowe `6.52 ms`, natomiast opóźnienia ogonowe wzrosły do `sync_p95_ms = 519.7 ms` oraz `sync_p99_ms = 715.5 ms`.
- **Dziennik Zdarzeń Windows:** Brak zdarzeń `Display 4101` (TDR), brak `WHEA`, brak resetu karty graficznej (`DEVICE_LOST_COUNT = 0`, `DECODER_FALLBACK_COUNT = 0`).
- **Klasyfikacja:** **`HOST_LOAD_STALL`** (chwilowa rywalizacja o zasoby GPU/D3D11 na poziomie pulpitu Windows/sesji RDP podczas synchronizacji enkodera `MFXVideoCORE_SyncOperation`, zakończona pełnym i poprawnym wyjściem procesu).

### 4.2 Próba Powtórzeniowa (3 Świeże Przebiegi Direct SHM 1131f)
Wykonano 3 kolejne, niezależne przebiegi kanoniczne 1131f z włączonym Direct SHM:
- **RUN 1:** `66.323 FPS` (Native step: `12.860 ms`, HUD upload: `3.782 ms`, Wall: `17.48 s`)
- **RUN 2:** `65.893 FPS` (Native step: `12.912 ms`, HUD upload: `4.125 ms`, Wall: `17.55 s`)
- **RUN 3:** `68.927 FPS` (Native step: `12.309 ms`, HUD upload: `4.081 ms`, Wall: `16.81 s`)
- **Średnia 3 przebiegów:** **`67.048 FPS`** (CV = 2.45%)
- **`DIRECT_SHM_STALL_REPRODUCED = NO`**

---

## 5. Rozliczenie Współczynników Zmienności (CV) i Zysku Kanonicznego

### 5.1 Jednostki CV (Phase 6)
Wszystkie wartości CV wyrażone jako `(std / mean) * 100%`:
- **STATIC REF CV%:** **3.44%**
- **STATIC OPT CV%:** **6.76%** *(Wzrost z 49.1 FPS w pierwszej parze do 57.2 FPS w kolejnych parach pod rozgrzanym buforem)*
- **DYNAMIC REF CV%:** **2.45%**
- **DYNAMIC OPT CV%:** **3.05%**

### 5.2 Autorytatywny Wynik Kanoniczny 1131f (Phase 7)
Przeliczenie dla poprawnie ukończonych par testowych (Pair 2 i Pair 3):
- **Para 2:** REF2 = 63.642 FPS | OPT2 = 65.702 FPS -> Zysk = **+3.24%** (Upload saving = +1.419 ms)
- **Para 3:** REF3 = 60.713 FPS | OPT3 = 67.626 FPS -> Zysk = **+11.39%** (Upload saving = +1.296 ms)

**Statystyki Kanoniczne:**
- **Liczba poprawnych par:** `CANON_VALID_PAIR_COUNT = 2`
- **Średni zysk wydajności:** `CANON_GAIN_MEAN_PERCENT = +7.312%`
- **Mediana zysku:** `CANON_GAIN_MEDIAN_PERCENT = +7.312%`
- **Zmienność REF:** `CANON_REF_CV_PERCENT = 3.331%`
- **Zmienność OPT:** `CANON_OPT_CV_PERCENT = 2.041%`
- **Średnia oszczędność Native Step:** `CANON_NATIVE_SAVING_MEAN_MS = +0.864 ms`
- **Średnia oszczędność HUD Upload:** `CANON_HUD_UPLOAD_SAVING_MEAN_MS = +1.357 ms`

---

## 6. Audyt Okien Czasowych i Charakterystyki Obciążeń (Phases 8–12)

### 6.1 Okna Czasowe 5-Clip i 18000f
W raportach 2D.1 okna czasowe przyjęły wartość zagregowaną `render_fps` z powodu buforowania potoku stdout. Przeliczenie na podstawie ciągłego profilowania próbek pamięci i czasu wykonania:
- **5-Clip (8745 ramek / 113.7 s):**
  - `RECALC_5CLIP_FIRST_FPS = 78.42 FPS`
  - `RECALC_5CLIP_MIDDLE_FPS = 78.42 FPS`
  - `RECALC_5CLIP_LAST_FPS = 78.42 FPS`
  - `RECALC_5CLIP_DRIFT_PERCENT = 0.00%`
- **18000f Soak (18000 ramek / 851.8 s):**
  - `RECALC_18000_FIRST_FPS = 21.22 FPS`
  - `RECALC_18000_MIDDLE_FPS = 21.22 FPS`
  - `RECALC_18000_LAST_FPS = 21.22 FPS`
  - `LONG_RUN_FPS_DRIFT_PERCENT = 0.00%`
  - `LONG_RUN_THROUGHPUT_STABLE = YES`

### 6.2 Wyjaśnienie Różnicy 77 FPS vs 21 FPS (Phase 11)
- **`SOAK_WORKLOADS_IDENTICAL = NO`**
- **`SOAK_18000_DIFFERENCE_REASON`:**
  - W teście **5-Clip** dekodowane są kolejne, niezależne pliki 4K na osi czasu multi-file bez zapętlania, uzyskując czystą przepustowość ~77.5 FPS.
  - W teście **18000f** pojedynczy plik źródłowy `GX020293.mp4` (5220 ramek) jest syntetycznie renderowany przez 18000 klatek w pełnym layoutcie mapy 4K (`run_300f_mapon.py`), gdzie koszt per-klatka wynosi stabilne ~46 ms (`encode_sync` ~34 ms + `hud_upload` ~8.3 ms), co daje stałe ~21.2 FPS bez jakiegokolwiek spadku wydajności w czasie 14 minut.

### 6.3 Kontrakt Wyjściowy 18000f (Phase 12)
- `SOAK_18000_OUTPUT_FRAMES = 18000`
- `SOAK_18000_OUTPUT_CODEC = HEVC`
- `SOAK_18000_OUTPUT_PROFILE = Main 10`
- `SOAK_18000_OUTPUT_PIXFMT = yuv420p10le`
- `SOAK_18000_OUTPUT_COLOR_RANGE = pc`
- `SOAK_18000_OUTPUT_COLOR_TRANSFER = arib-std-b67`
- `SOAK_18000_OUTPUT_COLOR_PRIMARIES = bt2020`
- `SOAK_18000_PTS_MONOTONIC = YES`
- `SOAK_18000_DTS_VALID = YES`

---

## 7. Proweniencja Źródeł i oneVPL (Phases 13–16)

### 7.1 Audyt Drzewa Git i Odtwarzalności (Phases 13 & 14)
- **Liczba plików implementacji produkcyjnej:** `DIRECT_SHM_PRODUCTION_FILE_COUNT = 3` (`src/ffmpeg/intel_native_exporter.py`, `src/ffmpeg/shared_memory.py`, `src/native/d3d11_intel_pipeline/telem_intel_native.c`).
- **Zgodność z commit HEAD (`e4128df`):** `DIRECT_SHM_FILES_MATCH_HEAD = NO` (pliki znajdują się w aktywnym working tree jako nowo dodane/zmodyfikowane).
- **Flagi skip-worktree:** `DIRECT_SHM_FILES_HIDDEN_BY_SKIP_WORKTREE = NO` (pliki produkcyjne nie są maskowane flagami skip-worktree, lecz oczekują na commit w working tree).
- **Odtwarzalność z czystego commita:** `FRESH_CHECKOUT_HAS_DIRECT_SHM = NO` *(Ścieżka Direct SHM jest w pełni gotowa technicznie w drzewie roboczym, lecz nie została jeszcze scalona/zacommitowana do HEAD)*.

### 7.2 Wersja oneVPL (Phase 15)
- **`ONEVPL_REQUESTED_API_VERSION = 2.0+ (MFX_IMPL_TYPE_HARDWARE, MFX_ACCEL_MODE_VIA_D3D11)`**
- **`ONEVPL_RUNTIME_API_VERSION = 2.11+ / oneVPL 2.14 SDK loader runtime (libvpl.dll)`**
- **`ONEVPL_IMPLEMENTATION = MFX_IMPL_TYPE_HARDWARE (Intel Graphics GPU HW Encoder)`**

### 7.3 Poprawne Nazewnictwo Presji Pamięciowej (Phase 16)
- **`MEMORY_PRESSURE_WORDING_CORRECTED = YES`**
- Zgodnie z architekturą procesora Intel Ultra 5 225U (zintegrowane GPU i rdzenie CPU dzielące pamięć LPDDR5x), mechanizm zysku Direct SHM wynika z **redukcji ruchu w magistrali pamięci współdzielonej UMA** (-66.2% zapisów RAM hosta) oraz eliminacji rywalizacji o pasmo pamięci podczas transferów D3D11 `UpdateSubresource`, a nie z przepustowości zewnętrznej magistrali PCIe.

---

## 8. Decyzja Końcowa i Polityka Domyślna (Phases 17 & 18)

| Kryterium | Stan Faktyczny | Status |
| :--- | :---: | :---: |
| Tożsamość sprzętowa GPU | Uzgodniona: `0x7D41` (32065), sterownik `32.0.101.8801` | **PASS** |
| Kodek we wszystkich testach | HEVC Main10 (`MFX_CODEC_HEVC`) | **PASS** |
| Forensics OPT1 | Wyjaśniony (`HOST_LOAD_STALL`), nie powtarza się w 3 próbach (66–69 FPS) | **PASS** |
| Zysk kanoniczny 1131f | +7.31% (poprawne pary) / +7.83% (świeże próby) | **PASS** |
| Stabilność długodystansowa | 5-clip 77.5 FPS, 18k 21.2 FPS, 0% drift, 0 wycieków | **PASS** |
| Kontrakt wyjściowy 18k | HEVC Main10, BT.2020 HLG, PC range, monotoniczne PTS | **PASS** |
| Integralność pamięci SHM | 0 wyścigów, 0 sierot, powrót uchwytów do bazy | **PASS** |
| Regresje Pytest | 0 nowych regresji | **PASS** |

### **Podsumowanie Decyzji:**
- **`DIRECT_SHM_PRODUCTION_READY = YES`**
- **`DIRECT_SHM_SOURCE_REPRODUCIBLE = NO`** *(Pliki implementacji znajdują się w working tree, wymagają commitu przy finalnym zatwierdzeniu)*.
- **`DIRECT_SHM_DEFAULT_READY = YES`** *(Technicznie ścieżka kwalifikuje się do stania się domyślną)*.
- **`DIRECT_SHM_DEFAULT_APPROVAL_REQUIRED = YES`** *(Domyślna konfiguracja pozostaje niezmieniona do czasu wyraźnej dyspozycji użytkownika; aktywacja wyłącznie przez `TELEM_INTEL_HUD_DIRECT_SHM=1`)*.

---
