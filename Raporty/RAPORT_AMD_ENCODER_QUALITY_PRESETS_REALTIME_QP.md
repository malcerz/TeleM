# Raport: AMD HEVC Encoder Quality Presets & Realtime Average QP Telemetry

## 1. Cel i Zadanie
- **Zadanie**: Dodanie trzech jawnych presetów jakości dla enkodera AMD AMF HEVC (`Fast`, `Balanced`, `Quality`) z zachowaniem domyślnego `Fast` odpowiadającego dotychczasowemu baseline (SPEED / 10).
- **Telemetria QP**: Dodanie pomiaru w czasie rzeczywistym średniego QP (`Average QP`) podczas eksportu AMD z wykorzystaniem właściwości AMF (`AMF_VIDEO_ENCODER_HEVC_STATISTICS_FEEDBACK` oraz `AMF_VIDEO_ENCODER_HEVC_STATISTIC_AVERAGE_QP`).
- **Integracja GUI**: Dodanie selektora presetu jakości AMD w zakładce Renderowania (`RenderTab`), prezentacja bieżącej średniej QP (`QP avg: XX.X`) w statystykach kompresji, wyzerowanie QP przy nowym eksporcie / restarcie / anulowaniu.
- **Izolacja**: Wyłącznie backend AMD — brak zmian w backendach NVIDIA / Intel / CPU, brak zmian w geometrii i matematyce HUD.

---

## 2. Stan Początkowy (Initial State)
- Encoder AMD AMF HEVC w `d3d11_amf_encoder.cpp` konfigurował na stałe `AMF_VIDEO_ENCODER_HEVC_QUALITY_PRESET_SPEED` (wartość `10`).
- Brak możliwości wyboru cięższych presetów jakości z poziomu GUI lub konfiguracji środowiskowej.
- Brak zbierania statystyk QP z enkodera AMF HEVC (feedback statistics był nieaktywny).
- W GUI RenderTab brak kontrolki wyboru presetu jakości dla backendu AMD.

---

## 3. Zmienione Pliki (Changed Files)

### C++ Native Pipeline (`native/d3d11_amf_pipeline/`):
- `src/d3d11_amf_encoder.h`:
  - Dodano pole konfiguracji `qualityPreset` (`AMF_VIDEO_ENCODER_HEVC_QUALITY_PRESET_SPEED=10`, `BALANCED=5`, `QUALITY=0`),
  - Dodano flagę `enableStatsFeedback`,
  - Dodano akumulator statystyk QP (`m_qpSum`, `m_qpSamples`, `m_qpMin`, `m_qpMax`, `m_qpLast`, `m_qpSupported`),
  - Dodano metody `GetQPStats(double* pAvgQP, uint32_t* pMinQP, uint32_t* pMaxQP, uint64_t* pSamples, bool* pSupported)` oraz `ResetQPStats()`.
- `src/d3d11_amf_encoder.cpp`:
  - W metodzie `Initialize(...)` ustawiono właściwość `AMF_VIDEO_ENCODER_HEVC_QUALITY_PRESET` zgodnie z wybranym presetem,
  - W metodzie `SubmitSurface(...)` ustawiono właściwość `AMF_VIDEO_ENCODER_HEVC_STATISTICS_FEEDBACK = true` na powierzchni wejściowej,
  - W metodzie `QueryPacket(...)` odczytano właściwości `AMF_VIDEO_ENCODER_HEVC_STATISTIC_AVERAGE_QP`, `MIN_QP`, `MAX_QP` z pakietu wyjściowego i zaktualizowano bieżące statystyki.
- `src/telem_amd_native.cpp`:
  - W `telem_amd_create(...)` odczytano zmienne `AMD_ENCODER_QUALITY_PRESET` oraz `AMD_ENCODER_STATS_FEEDBACK` i przekazano do enkodera AMF,
  - Wyeksportowano funkcję C API `telem_amd_get_encoder_qp_stats(void* handle, double* outAvgQP, uint32_t* outMinQP, uint32_t* outMaxQP, uint64_t* outSamples, int* outSupported)`.

### Python Governance & Backend:
- `src/ffmpeg/amd_config.py`:
  - Zdefiniowano enum `AMDQualityPreset` (`FAST=10`, `BALANCED=5`, `QUALITY=0`),
  - Dodano helper `resolve_amd_encoder_quality(value)` z domyślnym fallbackiem do `FAST`,
  - Dodano `encoder_quality: "FAST"` do `PRODUCTION_DEFAULTS`,
  - Dodano `AMD_ENCODER_QUALITY_PRESET` do `GOVERNED_AMD_ENV`,
  - Zaimplementowano jednolite rozwiązywanie presetu w `resolve_amd_config()`.
- `src/ffmpeg/amd_native_exporter.py`:
  - Podpięto binding ctypes dla `telem_amd_get_encoder_qp_stats`,
  - Zaimplementowano okresowe odpytywanie statystyk QP podczas renderowania i przekazywanie ich do progress trackera,
  - Zapisano pełne metryki QP do pliku `.amd_profile.json` w sekcji `"encoder"`.
- `src/ffmpeg/streaming.py`:
  - Przekazano parametr `amd_encoder_quality` do `export_amd_native_d3d11`.
- `src/render_progress.py`:
  - Dodano obsługę `**extra` w `HudPrepProgressTracker.frame(...)`, umożliwiając transparentne przekazywanie `compression_text` oraz statystyk QP do stanu GUI.

### GUI & State:
- `src/gui/qt/signals.py`:
  - Dodano sygnał `sig_amd_encoder_quality_restored = Signal(str)`.
- `src/gui/qt/controller.py`:
  - Zainicjalizowano `self.amd_encoder_quality = "FAST"`, dodano przywracanie z `def_layout.json`.
- `src/gui/qt/_mixins/preset_mixin.py`:
  - Dodano serializację i deserializację `amd_encoder_quality` w sekcji `global` layoutu projektu.
- `src/gui/qt/_mixins/render_mixin.py`:
  - Przekazano opcję `amd_encoder_quality` do parametrów eksportu, obsłużono formatowanie `compression_text` w `RenderProgressState`.
- `src/gui/qt/tabs/render_tab.py`:
  - Dodano combobox `cmb_amd_quality` ("Preset jakości AMD:" -> `Fast`, `Balanced`, `Quality`),
  - Podłączono sygnał przywracania `sig_amd_encoder_quality_restored`,
  - Przekazano `amd_encoder_quality` w słowniku `options` metody `_on_render()`,
  - Zapewniono czyszczenie etykiety `lbl_compression_stats` przy rozpoczęciu nowego eksportu i po jego zakończeniu.
- `def_layout.json`:
  - Zaktualizowano domyślną konfigurację o `"amd_encoder_quality": "FAST"`.

---

## 4. Testy i Weryfikacja

### Unit Tests:
- `tests/test_amd_encoder_quality_qp.py` (6 testów):
  - `test_preset_enum_values`: weryfikacja poprawności mapowania wartości AMF (10, 5, 0),
  - `test_resolve_from_string`: weryfikacja parsowania stringów i bezpiecznego fallbacku,
  - `test_governance_env_override`: weryfikacja priorytetu zmiennych środowiskowych,
  - `test_production_default`: weryfikacja domyślnego `FAST`,
  - `test_native_dll_exports`: weryfikacja obecności i sygnatury `telem_amd_get_encoder_qp_stats` w skompilowanej bibliotece DLL,
  - `test_rendertab_quality_widget`: weryfikacja kontrolki GUI `cmb_amd_quality`, opcji i metod przywracania stanu.
- `tests/test_amd_benchmark_governance.py` (5 testów):
  - Weryfikacja niezmienności governancyjnych kontraktów AMD.
- **Wynik**: 11/11 testów zaliczonych (PASS).

### Weryfikacja ABI DLL:
- `ABI_BEFORE`: 9
- `ABI_AFTER`: 9
- Wszystkie 25 eksportów natywnej biblioteki `telem_amd_native.dll` zweryfikowane pomyślnie.

### Dyspozycja Dotycząca Testów Wydajnościowych:
> [!NOTE]
> Zgodnie z bezpośrednią dyspozycją użytkownika (*"nie rób testów wydajności bo do 6:00 jest aktywny profil eco"*), ciężkie testy wydajnościowe (długie przebiegi benchmarkowe 3-presetów i pomiar narzutu procentowego AMF statistics feedback) zostały odroczone do czasu wyłączenia profilu eco.
> Wszelkie mechanizmy pomiarowe, akumulatory QP, governance oraz integracja GUI zostały w pełni zaimplementowane, skompilowane i zweryfikowane jednostkowo.

---

## 5. Izolacja Backendów i Bezpieczeństwo
- Zmiany ograniczone wyłącznie do modułów AMD (`native/d3d11_amf_pipeline/`, `src/ffmpeg/amd_*`, dedykowane kontrolki w `RenderTab`).
- Brak modyfikacji ścieżek NVIDIA NVENC/CUDA, Intel QSV czy procesora programowego CPU.
- Pełna zgodność wsteczna: brak podania presetu skutkuje domyślnym `Fast` (identycznym z dotychczasowym stanem produkcyjnym).

---

## 6. Podsumowanie
- **Status**: COMPLETE / PASS
- **Preset jakości AMD**: Dostępny w GUI i konfiguracji (`Fast`, `Balanced`, `Quality`).
- **Telemetria Average QP**: Zaimplementowana w C++ AMF encoderze, eksportowana przez DLL, zintegrowana w czasie rzeczywistym z GUI.
- **Governance**: Pojedyncze źródło prawdy w `src/ffmpeg/amd_config.py`.
