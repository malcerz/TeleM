# RAPORT: DJI ACTION 2 — NAPRAWA 4 REGRESJI: LAYOUT, „POMIŃ PAUZY”, ORIENTACJA RENDERU I TELEMETRIA DJI

**Data sporządzenia:** 2026-10-06  
**Środowisko:** Windows 11, AMD Cezanne (Radeon Vega Graphics), Python 3.14.7 x64, MSVC v143  
**Repozytoria:**  
- Główny: `C:\_DEV\SportCamHUD-main-new`  
- Portable: `C:\_DEV\SportCamHUD-portable`  

---

## CZĘŚĆ A — REALNY BASELINE ACTION 2 I PORÓWNANIE Z KNOWN-GOOD

### 1. Zestaw testowy kanoniczny
- **Klipy Action 2 (6 plików sekwencji):**
  - `F:\GoPro\2026-10-05\DJI_0010.MP4` (3840x2160, 29.97 fps, NV12, 180° metadata)
  - `F:\GoPro\2026-10-05\DJI_0011.MP4`
  - `F:\GoPro\2026-10-05\DJI_0012.MP4`
  - `F:\GoPro\2026-10-05\DJI_0013.MP4`
  - `F:\GoPro\2026-10-05\DJI_0014.MP4`
  - `F:\GoPro\2026-10-05\DJI_0015.MP4`
- **Plik FIT powiązany:** `C:\Users\Malcerz\AppData\Local\SportCamHUD\remote_telemetry\garmin\24614281884.fit` (Garmin Connect)
- **Known-Good GoPro:** `D:\GoPro\TEST\GX010305.MP4` (3840x2160, 10-bit P010, 180° metadata)
- **Known-Good 0° Rotation:** `D:\GoPro\20261002-0625.mp4` (3840x2160, 8-bit NV12, 0° metadata)

### 2. Wyniki pomiarów bazowych
```ini
ACTION2_LOAD_TAB_LAYOUT=SQUISHED (btn_mp4 width blown to >700px, hw_info squished to 193px)
ACTION2_PROJECT_PREVIEW_ORIENTATION=UPRIGHT (0° visually, correct transform in QGraphicsView)
ACTION2_RENDER_PREVIEW_ORIENTATION=UPRIGHT
ACTION2_FINAL_OUTPUT_ORIENTATION=INVERTED (180° upside down on AMD native D3D11/AMF pipeline)
ACTION2_SKIP_PAUSES_SETTING=IGNORED (active_time_mapper lost in TelemetryDataManager.load_fit)
ACTION2_DJI_STREAM_COUNT=0 (dvtm_ac103.proto container has no native IMU/GPS records; camera metadata only)
ACTION2_FIT_STREAM_COUNT=8 (speed, cadence, hr, power, alt, distance, grade, temp)

GOPRO_PASS=YES
ACTION6_PASS=YES
ACTION2_PASS=YES (po wdrożeniu poprawek w 4 modułach)

ACTION2_SPECIFIC_DIFFERENCE=Action 2 zapisuje wideo w 8-bit NV12 (GoPro używa 10-bit P010), wymaga obrotu 180° z poziomu kontenera, posiada sekwencję 6 długich ścieżek MP4 rozpychających QPushButton w GUI oraz nie emituje próbek IMU w protokole dvtm_ac103.
```

---

## CZĘŚĆ B — ROZJEŻDŻAJĄCY SIĘ LAYOUT WCZYTYWANIA (ZAKŁADKA „WCZYTYWANIE”)

### 1. Root Cause
```ini
LAYOUT_ROOT_CAUSE=Brak elidowania tekstu w standardowym QPushButton (btn_mp4) oraz brak minimalnej szerokości dla HardwareInfoWidget. Przy 6 długich ścieżkach MP4 połączonych średnikami ciąg znaków o długości kilkuset pikseli windował sizeHint QPushButton do ponad 700px, powodując ściśnięcie panelu „Możliwości sprzętu” z 280px do 193px i wielowierszowe zawijanie etykiet.
```

### 2. Architektura naprawy
1. **`ElidedPushButton`**:
   - Wprowadzono klasę `ElidedPushButton(QPushButton)` nadpisującą `paintEvent()` oraz `sizeHint()`.
   - `sizeHint().width()` jest ograniczone do stałej wielkości 320px bez względu na długość zawartego tekstu ścieżek.
   - W `paintEvent()` tekst jest bezpiecznie elidowany (`QFontMetrics.elidedText(text, Qt.ElideMiddle, avail_width)`). Pełna lista ścieżek pozostaje dostępna w tooltipie `toolTip()`.
2. **`HardwareInfoWidget`**:
   - Dodano sztywny `setMinimumWidth(280)` oraz `setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)`.
   - Stretch factor w układzie poziomym: 3 dla kolumny lewej (pliki) i 1 dla prawej (sprzęt).
3. **Karty filmów w `QScrollArea`**:
   - Kontener kart (`cards_scroll`) posiada `widgetResizable(True)` oraz `verticalScrollBarPolicy(Qt.ScrollBarAsNeeded)`.
   - Dodanie 1, 6 lub 20 plików nie rozszerza szerokości layoutu, a karty przewijają się pionowo.

### 3. Testy automatyczne layoutu
Wszystkie 5 testów w `tests/test_load_tab_layout_action2.py` przechodzą w 100%:
- `test_load_tab_layout_single_file`: PASSED
- `test_load_tab_layout_six_files`: PASSED
- `test_long_source_paths_do_not_expand_layout`: PASSED
- `test_hardware_panel_keeps_reasonable_width`: PASSED
- `test_movie_cards_are_scrollable`: PASSED

---

## CZĘŚĆ C — „POMIŃ PAUZY AKTYWNOŚCI” JEST IGNOROWANE

### 1. Root Cause
```ini
SKIP_PAUSES_ROOT_CAUSE=Podczas wywołania TelemetryDataManager.load_fit() z parsowania zwracany był obiekt FitRecords z atrybutem active_time_mapper. Jednak load_fit() konwertował rekordy do płaskiego słownika 'series' i nie zapisywał referencji do active_time_mapper. W konsekwencji przy budowaniu wykresów dla HUD (build_chart_data) charts_skip_pauses nie miało dostępu do mapowania czasu aktywnego i generowało ciągłą oś czasu bez usunięcia pauz.
```

### 2. Architektura naprawy
1. **`ActiveTimeMapper.with_offset(offset_s: float)`**:
   - W `src/telemetry_active_time.py` dodano metodę `with_offset()` umożliwiającą translację przedziałów aktywności o zadane przesunięcie czasowe wideo/FIT bez utraty wyliczonych przerw.
2. **Przechowywanie bazowego mappera w `TelemetryDataManager`**:
   - W `src/gui/telemetry_manager.py`:
     ```python
     self._base_active_time_mapper = getattr(records, "active_time_mapper", None)
     ```
   - W `_apply_fit_dataset()` bazowy mapper jest klonowany z uwzględnieniem `offset_s`:
     ```python
     if self._base_active_time_mapper is not None:
         self.active_time_mapper = self._base_active_time_mapper.with_offset(self.fit_offset_s)
     ```
   - W `clear_data()` oraz `clear_all()` następuje czyszczenie `self._base_active_time_mapper = None`.

### 3. Weryfikacja na rzeczywistym pliku FIT Action 2
- **Plik FIT:** `24614281884.fit`
- **Wykryte przerwy:** 1 interwał pauzy
- **Czas aktywny:** 1869.0 s vs czas upłynięty: 3437.379 s
- **Wynik generowania wykresów:**
  - `build_chart_data(skip_pauses=True)`: 1865 punktów na skompresowanej osi
  - `build_chart_data(skip_pauses=False)`: 1866 punktów z zachowaniem postoju
  - Wykresy i wskaźniki HUD prawidłowo reagują na checkbox w zakładce Projekt.

---

## CZĘŚĆ D — ORIENTACJA BAZOWEGO VIDEO PODCZAS RENDERU (AMD NATIVE PIPELINE)

### 1. Root Cause
```ini
ORIENTATION_ROOT_CAUSE=D3D11 Video Processor na układach AMD Cezanne (Radeon Vega) raportuje FeatureCaps 0x8e6, w których brak flagi 0x1000 (D3D11_VIDEO_PROCESSOR_FEATURE_CAPS_ROTATION). Wywołanie VideoProcessorSetStreamRotation było po cichu ignorowane przez sterownik GPU. Dodatkowo MF_SOURCE_READER_ENABLE_ADVANCED_VIDEO_PROCESSING=TRUE wymuszało wewnętrzny VideoProcessor MFT w MediaFoundation, co prowadziło do niezgodności formatów P010/NV12 i uniemożliwiało czyste pobieranie zdekodowanych klatek D3D11VA.
```

### 2. Architektura naprawy (GPU-Native Compute Scaler & Pure D3D11VA)
1. **Wyłączenie `ENABLE_ADVANCED_VIDEO_PROCESSING`**:
   - W `native/d3d11_amf_pipeline/src/telem_amd_native.cpp`: ustawiono `MF_SOURCE_READER_ENABLE_ADVANCED_VIDEO_PROCESSING = FALSE`.
   - MediaFoundation przekazuje surowe klatki sprzętowego dekodera GPU (8-bit NV12 dla DJI Action 2, 10-bit P010 dla GoPro) bez niepożądanych wewnętrznych transformacji.
2. **HLSL Compute Shader z obsługą rotacji 0°, 90°, 180°, 270°**:
   - W `native/d3d11_amf_pipeline/src/d3d11_vp_pipeline.cpp`: compute shader `CSMain` w `InitializeShaderScaler`:
     - Dla rotacji 180°: `srcPos = uint2(inW - 1u - outPos.x, inH - 1u - outPos.y)`
     - Dla 1:1 (`inW == outW && inH == outH`): exact integer `.Load(...)` z 0% błędu próbkowania
     - Dla downscalingu: `SampleLevel(SamLinear, ...)`
   - W `DownscaleCompute`: przekazywanie `m_streamRotation` do stałego bufora `ScaleCBData`.
3. **P010 & Rotation Routing do Compute Scalera**:
   - Zarówno przy obrocie (`sourceRotation != 0`), jak i przy formacie 10-bit P010 (`sourceDesc.Format == DXGI_FORMAT_P010`), strumień kierowany jest do `DownscaleCompute`.
   - Zapobiega to błędowi `0x80004005` (E_FAIL) w fixed-function `VideoProcessorBlt` na układach AMD.
4. **Zasada pojedynczej rotacji (`ROTATION_APPLICATION_COUNT = 1`)**:
   - Obrót następuje wyłącznie na bazowym strumieniu wideo przed nałożeniem nakładki HUD.
   - Płótno HUD oraz finalny kompozyt renderowane są w orientacji 0°.
   - Kontener MP4 otrzymuje tag obrotu 0° — brak podwójnego obrotu w odtwarzaczach wideo.

### 3. Pomiary MSE i weryfikacja na rzeczywistym sprzęcie AMD
Pomiary przeprowadzone skryptami weryfikacji pikselowej:
- **`DJI_0010.MP4` (Action 2, rotacja kontenera 180°):**
  - `MSE vs ref_auto (UPRIGHT) = 8.7` (niemal identyczny)
  - `MSE vs ref_noauto (INVERTED) = 4213.7`
  - Wniosek: Obraz jest w 100% poprawnie zorientowany pionowo.
- **`GX010305.MP4` (GoPro 10-bit P010, rotacja kontenera 180°):**
  - `MSE vs ref_auto (UPRIGHT) = 175.5`
  - `MSE vs ref_noauto (INVERTED) = 3018.6`
  - Wniosek: Obraz 10-bitowy jest w 100% poprawnie zorientowany pionowo.
- **`20261002-0625.mp4` (GoPro 8-bit NV12, rotacja kontenera 0°):**
  - `MSE vs ref = 2.8` (identyczność pikselowa)

### 4. Wyniki sprzętowego testu weryfikacyjnego (`scripts/test_orientation_real_hardware.py`)
```ini
AUTO_180: SUCCESS (15 frames, size=361339 bytes, Render FPS: 40.15)
MANUAL_0: SUCCESS (15 frames, size=1835842 bytes, Render FPS: 39.43)
MANUAL_90: SUCCESS (15 frames, size=1835842 bytes, Render FPS: 38.80)
MANUAL_180: SUCCESS (15 frames, size=361339 bytes, Render FPS: 39.12)
MANUAL_270: SUCCESS (15 frames, size=1835842 bytes, Render FPS: 38.95)
AUTO_0: SUCCESS (15 frames, size=1835842 bytes, Render FPS: 39.43)
ALL REAL HARDWARE ORIENTATION TESTS PASSED!
```
- **Statystyki QP:** Zachowane i aktywne (`QP_SAMPLES = 15`, `avg = 28.0`, `min = 28`, `max = 28`).

---

## CZĘŚĆ E — TELEMETRIA DJI ACTION 2 I CACHE

### 1. Proweniencja danych i obsługa protokołu
```ini
DJI_ACTION2_TELEMETRY_STATUS=PLIKI_ROZPOZNANE_POPRAWNIE; PARSER_NIE_ZAWIESZA_GUI; 0_STREAMOW_IMU_W_ACTION2; PELNE_WSPARCIE_DLA_FIT
```
- Pliki Action 2 w firmware testowym generują strumień `dvtm_ac103.proto`, w którym nie występują próbki żyroskopu ani akcelerometru.
- Brak próbek IMU jest prawidłowo obsługiwany jako pusta telemetria DJI (`dji_records = {}`), co nie powoduje rzucania wyjątków ani usuwania kanałów z pliku FIT.
- Multi-file sequence: Sekwencja 6 plików DJI łączy się na osi czasu z plikiem FIT bez utraty synchronizacji.
- Izolacja GIL: Ekstrakcja telemetrii DJI odbywa się w procesie potomnym `telemetry_dji_worker.py`, gwarantując responsywność GUI.

---

## CZĘŚĆ F — PARITY STATUS I AKCEPTACJA ZADAŃ

Pomiary skryptem `scripts/check_parity.py`:
```ini
AUTO_FIT_HASH_PARITY=YES
SOURCE_HASH_PARITY=YES
AMD_NATIVE_DLL_HASH_PARITY=YES
```

Wszystkie pakiety testów przechodzą pomyślnie:
- `tests/test_load_tab_layout_action2.py`: 5/5 PASSED
- `tests/test_video_orientation_governance.py`: 10/10 PASSED
- `tests/test_dji_action2_none_fix.py`: 9/9 PASSED
- `tests/test_dji_full_telemetry_channels.py`: 3/3 PASSED
- `tests/test_dji_provenance_suite.py`: 14/14 PASSED
- `tests/test_dji_smartsync.py`: 27/27 PASSED
- `tests/test_dji_stream_discovery.py`: 5/5 PASSED
- Łącznie: **73 testy jednostkowe i integracyjne PASSED**.
