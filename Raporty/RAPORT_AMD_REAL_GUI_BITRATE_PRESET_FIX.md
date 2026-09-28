# RAPORT: NAPRAWA PROPAGACJI BITRATE ORAZ PRESETÓW JAKOŚCI Z GUI (AMD REAL GUI ENCODER FIX)

## 1. Cel i Identyfikacja Zadania
- **Zadanie:** P0 — Naprawa ignorowania ustawień enkodera (`bitrate` oraz presetów `Fast`/`Balanced`/`Quality`) podczas rzeczywistego renderu z interfejsu graficznego GUI (PySide6 / `RenderTab` / `RenderMixin`).
- **Ścieżka renderu:** `GUI` (`render_tab.py`) → `RenderMixin` (`render_mixin.py`) → `AMD child process` (`amd_child_process.py`) → `streaming.py` → `amd_native_exporter.py` → `telem_amd_native.dll` → `AMF HEVC Hardware Encoder`.
- **Gałąź:** `amd-bikeridehud`
- **Dataset kanoniczny:** `Video/GX020079.MP4` + `Video/GX020079.fit` (1131 klatek, 37.74 s, 3840x2160 @ 29.97 fps, layout `def_layout.json` v10).

---

## 2. Diagnoza Stanu Początkowego (Root Cause Analysis)

### Objaw zgłoszony przez Użytkownika:
Trzy rendery z GUI (`FAST.mp4`, `Balans.mp4`, `qual.mp4`) dla żądania `10 Mb/s` zakończyły się wygenerowaniem plików o **dokładnie identycznym rozmiarze co do bajta** (`6 573 741 621 B`, ~6.57 GB) oraz faktycznym bitrate `~88.8 Mb/s` zamiast `10 Mb/s`.

### Warstwy audytu i przyczyny źródłowe:
1. **Brak propagacji wyboru presetu jakości w `streaming.py`:**
   - W warstwie dyspozytora renderu `src/ffmpeg/streaming.py:1193` funkcja `stream_overlay_to_ffmpeg()` przyjmowała parametr `amd_encoder_quality`, ale przy wywołaniu backendu `export_amd_native_d3d11(...)` **nie przekazywała go w argumentach**.
   - W konsekwencji `export_amd_native_d3d11` zawsze używał domyślnej wartości `"FAST"`. Wybór `Balanced` i `Quality` w GUI był bezpowrotnie tracony przed dotarciem do backendu.
2. **Hardcoded CQP 28 w native AMF HEVC Encoder:**
   - W `native/d3d11_amf_pipeline/src/d3d11_amf_encoder.cpp:99` właściwość `AMF_VIDEO_ENCODER_HEVC_RATE_CONTROL_METHOD` była sztywno ustawiona na `AMF_VIDEO_ENCODER_HEVC_RATE_CONTROL_METHOD_CONSTANT_QP` (0) z `QP_I=28` i `QP_P=28`.
   - Parametr `video_bitrate` z GUI nigdy nie był konwertowany na bps ani ustawiany w parametrach AMF `AMF_VIDEO_ENCODER_HEVC_TARGET_BITRATE` i `AMF_VIDEO_ENCODER_HEVC_PEAK_BITRATE`.
   - W trybie Constant QP enkoder sprzętowy całkowicie ignoruje bitrate, dopasowując przepływność wyłącznie do stałego kwantyzatora 28 dla każdej klatki.
3. **Identyczność plików co do bajta:**
   - Ponieważ każdy eksport z GUI był wymuszany do `FAST` + `CQP 28` na tym samym źródle wideo i tych samych klatkach telemetrii, enkoder AMD sprzętowo generował deterministyczny strumień bit po bicie o rozmiarze 6.57 GB i bitrate ~88.8 Mb/s.

---

## 3. Zastosowane Poprawki (Minimal Patch)

1. **`src/ffmpeg/amd_config.py`:**
   - Dodano funkcję `parse_bitrate_bps()` poprawnie interpretującą formaty GUI: `"10M"`, `"10 Mb/s"`, `"20M"`, `"40M"`, `"10000k"`, `"10"`, etc.
   - Włączono `encoder_rate_control`, `encoder_target_bitrate` oraz `encoder_peak_bitrate` do konfiguracji nadzorowanej (`PRODUCTION_DEFAULTS` oraz `GOVERNED_AMD_ENV`).
2. **`src/ffmpeg/streaming.py`:**
   - Poprawiono wywołanie `export_amd_native_d3d11(...)` poprzez dodanie brakującego argumentu `amd_encoder_quality=amd_encoder_quality`.
3. **`src/ffmpeg/amd_native_exporter.py`:**
   - Zintegrowano parsowanie `video_bitrate` z GUI do bps i wyznaczanie metody rate control (`PEAK_CONSTRAINED_VBR` jako domyślna metoda sterowania bitrate).
   - Przekazano do środowiska procesu potomnego zmienne: `AMD_ENCODER_QUALITY_PRESET`, `AMD_ENCODER_RATE_CONTROL`, `AMD_ENCODER_TARGET_BITRATE` oraz `AMD_ENCODER_PEAK_BITRATE`.
4. **`native/d3d11_amf_pipeline/src/d3d11_amf_encoder.h` & `.cpp`:**
   - Rozszerzono metodę `Initialize()` o dynamiczną konfigurację trybów rate control (`PEAK_CONSTRAINED_VBR`, `CBR`, `CONSTANT_QP`) oraz ustawianie właściwości `TARGET_BITRATE` i `PEAK_BITRATE`.
   - Zapewniono obsługę telemetrii QP w czasie rzeczywistym poprzez `AMF_VIDEO_ENCODER_HEVC_STATISTIC_AVERAGE_QP`.
5. **`native/d3d11_amf_pipeline/src/telem_amd_native.cpp`:**
   - W `telem_amd_init()` zaimplementowano odczyt parametrów jakości i kontroli bitrate ze środowiska procesowego i przekazanie ich do enkodera AMF.
   - Dodano logowanie statystyk QP (`[AMD QP TELEMETRY]`) podczas finalizacji sesji renderu w `telem_amd_close()`.
6. **Kompilacja biblioteki DLL:**
   - Przekompilowano `telem_amd_native.dll` z użyciem MinGW-W64 GCC + Ninja (rozmiar: `3,106,131 B`, SHA-256: `0faf697b9b8ae93d9a473948ac4b0035b76ca3d8c5d4676cbda729a3d539b063`).

---

## 4. Wyniki Testów Rzeczywistej Ścieżki GUI (Full GUI Pipeline)

Wszystkie testy zostały wykonane przez pełną ścieżkę GUI (`AppController` + `MainWindow` + `RenderTab` + `RenderMixin` + `AMD Child Process` + `AMF Encoder`), ładując pliki i preset przez interfejs PySide6 i klikając programowo przycisk `[ EKSPORTUJ ]` (`btn_render.click()`).

### A. Test Skalowania Bitrate (Fast @ 10M, 20M, 40M)

| Żądany Bitrate (GUI) | Target Bitrate (AMF) | Rzeczywisty Bitrate (ffprobe) | Rozmiar Pliku (Bytes) | Rozmiar (MB) | Tryb Rate Control | Średni QP | Zakres QP (Min-Max) | Render FPS |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **10 Mb/s** | 10 000 000 bps | **10 276 725 bps (10.28 Mb/s)** | 48 477 497 B | 46.23 MB | PEAK_CONSTRAINED_VBR | 37.77 | 20 – 46 | 43.415 |
| **20 Mb/s** | 20 000 000 bps | **20 216 917 bps (20.22 Mb/s)** | 95 367 496 B | 90.95 MB | PEAK_CONSTRAINED_VBR | 32.19 | 15 – 42 | 43.188 |
| **40 Mb/s** | 40 000 000 bps | **40 039 267 bps (40.04 Mb/s)** | 188 873 735 B | 180.12 MB | PEAK_CONSTRAINED_VBR | 26.65 | 11 – 37 | 42.648 |

**Wnioski:**
- Zależność wielkości pliku i bitrate od wartości zadanej w GUI jest **ściśle liniowa i dokładna** (10M → 46 MB, 20M → 91 MB, 40M → 180 MB).
- Średni kwantyzator QP prawidłowo maleje wraz ze wzrostem bitrate (37.77 → 32.19 → 26.65).

---

### B. Test Presetów Jakości (Fast, Balanced, Quality @ Stały Bitrate 20 Mb/s)

| Preset GUI | AMF Quality Preset ID | Nazwa AMF | Target Bitrate | Rzeczywisty Bitrate | Średni QP | Render FPS | Czas Wywołania Native DLL | Profil HEVC |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Fast** | **10** | SPEED | 20 000 000 bps | 20.22 Mb/s | 32.19 | 43.276 | 15.31 ms | Main |
| **Balanced** | **5** | BALANCED | 20 000 000 bps | 20.23 Mb/s | 32.08 | 42.965 | 12.48 ms | Main |
| **Quality** | **0** | QUALITY | 20 000 000 bps | 20.21 Mb/s | 31.30 | 38.402 | 19.80 ms | Main |

**Wnioski:**
- Wszystkie trzy presety (`Fast` → 10, `Balanced` → 5, `Quality` → 0) docierają bezpośrednio do enkodera sprzętowego AMF.
- Preset `Quality` realizuje głębsze przeszukiwanie wektorów ruchu, co odzwierciedla się w niższym średnim QP (31.30 vs 32.19) i odpowiednio wyższym nakładzie obliczeniowym (38.4 FPS vs 43.3 FPS).
- Bitrate wyjściowy i rozmiar pliku pozostają stabilne i zgodne z zadanym limitem 20 Mb/s.
- Kodek i profil wyjściowy to bez zmian `HEVC Main` (profil kodeka nie ulega zmianie między presetami, co jest w 100% prawidłowe).

---

## 5. Zestawienie Metryk Wymaganych

```text
ROOT_CAUSE=Brak przekazania amd_encoder_quality w streaming.py do export_amd_native_d3d11() oraz hardcoded CONSTANT_QP (0, QP=28) w d3d11_amf_encoder.cpp z pominięciem parametru bitrate.

BEFORE_GUI_BITRATE=10 Mb/s
BEFORE_RATE_CONTROL=CONSTANT_QP (QP=28)
BEFORE_EFFECTIVE_BITRATE=88 848 kb/s (~88.8 Mb/s)
BEFORE_AMF_PRESET=10 (wymuszone SPEED dla wszystkich opcji)

AFTER_RATE_CONTROL=PEAK_CONSTRAINED_VBR

BITRATE_10_REQUESTED=10M
BITRATE_10_ACTUAL=10.28 Mb/s (10 276 725 bps, 48 477 497 B)

BITRATE_20_REQUESTED=20M
BITRATE_20_ACTUAL=20.22 Mb/s (20 216 917 bps, 95 367 496 B)

BITRATE_40_REQUESTED=40M
BITRATE_40_ACTUAL=40.04 Mb/s (40 039 267 bps, 188 873 735 B)

FAST_EFFECTIVE_PRESET=10 (AMF_VIDEO_ENCODER_HEVC_QUALITY_PRESET_SPEED)
BALANCED_EFFECTIVE_PRESET=5 (AMF_VIDEO_ENCODER_HEVC_QUALITY_PRESET_BALANCED)
QUALITY_EFFECTIVE_PRESET=0 (AMF_VIDEO_ENCODER_HEVC_QUALITY_PRESET_QUALITY)

FAST_EFFECTIVE_RATE_CONTROL=PEAK_CONSTRAINED_VBR
BALANCED_EFFECTIVE_RATE_CONTROL=PEAK_CONSTRAINED_VBR
QUALITY_EFFECTIVE_RATE_CONTROL=PEAK_CONSTRAINED_VBR

QP_DYNAMIC=True
QP_MIN=11
QP_MAX=46
QP_AVG=32.19 (przy 20M), 37.77 (przy 10M), 26.65 (przy 40M)

HEVC_PROFILE=Main
HEVC_PROFILE_UNCHANGED=True

REAL_GUI_PATH_VALIDATED=True

MODIFIED_FILES=src/ffmpeg/amd_config.py, src/ffmpeg/streaming.py, src/ffmpeg/amd_native_exporter.py, native/d3d11_amf_pipeline/src/d3d11_amf_encoder.h, native/d3d11_amf_pipeline/src/d3d11_amf_encoder.cpp, native/d3d11_amf_pipeline/src/telem_amd_native.cpp

CASE=CASE A — REAL GUI BITRATE AND QUALITY PRESETS FULLY PROPAGATED
```

---

## 6. Manifest Artefaktów i Weryfikacja

Wszystkie pliki zostały wygenerowane i zweryfikowane w katalogu `scratch/amd_real_gui_encoder_settings_fix/`:
- `before_trace.txt`
- `root_cause.md`
- `after_trace.txt`
- `bitrate_10/` (`output_10m.mp4`, `ffprobe.txt`, `metrics.txt`, klatki kontrolne PNG, logi)
- `bitrate_20/` (`output_20m.mp4`, `ffprobe.txt`, `metrics.txt`, klatki kontrolne PNG, logi)
- `bitrate_40/` (`output_40m.mp4`, `ffprobe.txt`, `metrics.txt`, klatki kontrolne PNG, logi)
- `fast/` (`output_fast.mp4`, `ffprobe.txt`, `metrics.txt`, klatki kontrolne PNG, logi)
- `balanced/` (`output_balanced.mp4`, `ffprobe.txt`, `metrics.txt`, klatki kontrolne PNG, logi)
- `quality/` (`output_quality.mp4`, `ffprobe.txt`, `metrics.txt`, klatki kontrolne PNG, logi)
- `bitrate_results.csv`
- `preset_results.csv`
- `ffprobe_results.txt`
- `gui_runtime_trace.txt`
- `modified_files.txt`
- `reproduction_commands.txt`
- `artifacts_manifest.txt`
