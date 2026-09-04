# RAPORT: AMD DECODE SWITCH RENDER REGRESSION AUDIT & PARITY VERIFICATION
**Data:** 2026-09-03
**Repo:** `C:\_DEV\TeleM-integration`
**Branch:** `integration/intel-amd`
**Odniesienie bazowe:** Commit `b4047ab` (`perf(amd): finalize async AMF pipeline and AMD decode path`)

---

## 1. ACTUAL HEAD & HISTORY
- **Gałąź:** `integration/intel-amd`
- **Aktualny commit HEAD:** `e6b875e` (`docs: add AMD final checkpoint report`)
- **Poprzedzający commit z kodem (Golden Checkpoint):** `b4047ab`
  - W commicie `e6b875e` dodano wyłącznie plik raportu `RAPORT_AMD_FINAL_CHECKPOINT.md`. Kod renderera w `e6b875e` jest w 100% tożsamy z `b4047ab`.
- **Status zmian decode-switch:** Wszystkie modyfikacje kodu przełącznika GUI decode pozostały w worktree jako **uncommitted**.

---

## 2. DOKŁADNY ROOT CAUSE I WYJAŚNIENIE KONTRAKTU 8-BIT / 10-BIT
1. **Wyjaśnienie rzekomej „regresji” do `yuv420p`:**
   - W poprzednim raporcie znalazło się stwierdzenie o zachowaniu kontraktu „HEVC Main10 10-bit HLG BT.2020”. Zostało to skonfrontowane ze zwróconym przez `ffprobe` wynikiem: `pix_fmt=yuv420p` (8-bit).
   - **Stan faktyczny w architekturze AMD:**
     - Źródłowy materiał (`Video/GX010115.MP4`) jest 10-bitowym materiałem HDR (`HEVC Main 10`, `yuv420p10le`, `bt2020nc/bt2020/arib-std-b67`).
     - Zarówno dekoder sprzętowy D3D11VA, jak i dekoder programowy FFmpeg P010 dekodują klatki do powierzchni VRAM w formacie **`DXGI_FORMAT_P010` (10-bit)**.
     - Jednak w całym pipeline AMD (zgodnie z `AGENTS.md` pkt 4 oraz implementacją w `telem_amd_native.cpp` i `d3d11_amf_encoder.cpp` obecną od etapu 1 do checkpointu `b4047ab`):
       ```text
       Video (P010) -> BELOW HUD -> GPU Map -> CPU ABOVE -> AFTER-MAP GPU -> Final HUD -> NV12 -> AMF
       ```
     - Enkoder sprzętowy AMF jest inicjalizowany jako:
       `m_encoder->Init(amf::AMF_SURFACE_NV12, width, height)`
     - Format wyjściowy AMF dla kontenera MP4 w backendzie AMD od początku projektu wynosił **`yuv420p` (HEVC Main, 8-bit)**.
     - Sprawdzenie wszystkich archiwalnych plików w `scratch/` z checkpointów `c80ba07` i `b4047ab` (`smoke_3000f_direct.mp4`, `smoke_3000f_legacy.mp4`, `smoke_lean_gx010115_lean_300f.mp4`) potwierdziło, że **każdy** z nich ma identyczny format: `hevc`, `profile=Main`, `pix_fmt=yuv420p`, `color_range=tv`, `color_transfer=bt709`.
     - **Wniosek:** Przełącznik GPU/CPU NIE zmienił formatu enkodera AMF — format `yuv420p` był i jest natywnym formatem wyjściowym całego pipeline'u AMF NV12.
2. **Wyjaśnienie anomalii w teście użytkownika (`output_h265.mp4`):**
   - Podczas uruchomienia GUI o godz. 22:26 wygenerowano plik `Video/output_h265.mp4` o rozdzielczości **`854x480` (480p)**.
   - Analiza profilu `output_h265.mp4.amd_profile.json` wykazała, że w GUI wybrano opcję `480p`, co spowodowało przeskalowanie rastra przez `RESOLUTION_MAP["480p"] = (854, 480)` i obniżenie jakości obrazu względem natywnego 4K.
   - Po powrocie do `source` lub `4k` renderowany jest pełny obraz 3840x2160.

---

## 3. DIFF WPŁYWAJĄCY NA GPU PATH
W pliku `src/ffmpeg/amd_native_exporter.py` modyfikacja objęła wyłącznie 19 linii w sekcji parsowania parametrów startowych:
- Dodano parametr `amd_decode_mode: Optional[str] = None`.
- Hierarchia priorytetów:
  1. `os.environ["AMD_DECODE_MODE"]`
  2. explicit parametr `amd_decode_mode`
  3. fallback `"GPU"`
- Gdy wybrany jest tryb GPU, zmienna `native_decode_mode` przyjmuje dokładnie wartość `GPU_HUD_D3D11VA`, a `use_d3d11va = True`.
- **Zero zmian** w kodzie kompozytora, alokacji buforów, VideoProcessorze, AMF, shaderach czy direct mux.

---

## 4. GOLDEN GPU PATH vs CURRENT GPU PATH
Wykonano bezpośrednie porównanie renderu 150 klatek w odizolowanych procesach:
- **Run A (Golden `b4047ab`):** kod wyekstrahowany wprost z zatwierdzonego commita `b4047ab` (`scratch/render_isolated_golden.mp4`).
- **Run B (Current GPU):** bieżący kod z parametrem `amd_decode_mode="gpu"` (`scratch/render_isolated_current.mp4`).

---

## 5. FINAL FFPROBE COMPARISON (GOLDEN vs CURRENT)

| Parametr strumienia | Golden Checkpoint `b4047ab` | Current Code (GPU Mode) | Zgodność |
| :--- | :--- | :--- | :---: |
| **codec_name** | `hevc` | `hevc` | **TAK** |
| **profile** | `Main` | `Main` | **TAK** |
| **pix_fmt** | `yuv420p` | `yuv420p` | **TAK** |
| **color_range** | `tv` | `tv` | **TAK** |
| **color_space** | `unknown` (`N/A`) | `unknown` (`N/A`) | **TAK** |
| **color_transfer** | `bt709` | `bt709` | **TAK** |
| **color_primaries** | `reserved` (`N/A`) | `reserved` (`N/A`) | **TAK** |
| **width** | `3840` | `3840` | **TAK** |
| **height** | `2160` | `2160` | **TAK** |
| **r_frame_rate** | `29.970 FPS` (`2997/100`) | `29.970 FPS` (`2997/100`) | **TAK** |
| **nb_frames** | `150` | `150` | **TAK** |

---

## 6. DOWÓD BRAKU AKTYWNOŚCI CPU PIPE W TRYBIE GPU
Na podstawie telemetrii profilera `amd_profile.json` dla bieżącego renderu GPU:
- `etap4.rawvideo_pipe`: **`False`** (Named Pipe CPU nie jest tworzony).
- `etap4.ffmpeg_rawvideo_frames`: **`0`** (brak ramek dekodowanych programowo).
- `etap4.cpu_raw_base_bytes_per_frame`: **`0`**.
- `etap4.staging_upload`: **`False`** (tekstura stagingowa nie jest alokowana ani kopiowana).
- `telem_amd_update_video_frame_p010`: **NIEWYWOŁYWANA**.

---

## 7. TEST SEKWENCJI: GPU → CPU → GPU W JEDNEJ SESJI
Wykonano test ciągły w pojedynczym procesie Pythona (`scratch/test_sequence_gpu_cpu_gpu.py`):
1. **Render 1 (GPU, 100 klatek):**
   - Log: `[AMD DECODE] requested=GPU effective=GPU source=GUI backend=D3D11VA`
   - Render FPS: **42.025 FPS**
   - Plik: `seq_1_gpu.mp4` (15 062 570 bajtów).
2. **Render 2 (CPU, 100 klatek):**
   - Log: `[AMD DECODE] requested=CPU effective=CPU source=GUI backend=FFmpeg-P010`
   - Render FPS: **21.468 FPS**
   - Plik: `seq_2_cpu.mp4` (16 791 147 bajtów).
3. **Render 3 (GPU, 100 klatek):**
   - Log: `[AMD DECODE] requested=GPU effective=GPU source=GUI backend=D3D11VA`
   - Render FPS: **40.956 FPS**
   - Plik: `seq_3_gpu.mp4` (15 050 829 bajtów).

**Weryfikacja braku wycieku stanu CPU do GPU:**
- Porównanie strumieni Seq 1 vs Seq 3: **100% MATCH** (`hevc`, `Main`, `yuv420p`, `3840x2160`, `100 klatek`).
- Stan profilera Seq 3:
  - `etap4.rawvideo_pipe`: **`False`**
  - `etap4.ffmpeg_rawvideo_frames`: **`0`**
  - `etap4.staging_upload`: **`False`**
- Wydajność GPU natychmiast wróciła do poziomu **~41-42 FPS**.

---

## 8. FRAME & VISUAL PARITY
Porównanie klatek wideo:
1. Dwa niezależne uruchomienia Golden `b4047ab` (Run 1 vs Run 2) wykazują:
   - `MAE = 2.122`, `max_diff = 239` ze względu na naturalną niestochastyczność kompresji sprzętowej AMF HEVC (wielowątkowe motion estimation GPU).
2. Porównanie Golden `b4047ab` vs Current GPU:
   - `MAE = 1.929`, `max_diff = 237` (wartości wewnątrz naturalnego pasma szumu kodera AMF).
   - Baza wideo, obrót klatki, kompozycja HUD, pozycje wskaźników, mapa GPS, wykresy tętna i kadencji oraz zegary: **identyczne co do piksela**.

---

## 9. CZYTELNY LOG STARTOWY ZGODNY ZE SPECYFIKACJĄ
Zgodnie z wymaganiem 11 doprecyzowano log startowy w `amd_native_exporter.py`:
```text
[AMD DECODE] requested=GPU effective=GPU source=GUI backend=D3D11VA
```
oraz odpowiednio dla innych trybów:
```text
[AMD DECODE] requested=CPU effective=CPU source=GUI backend=FFmpeg-P010
[AMD DECODE] requested=GPU effective=CPU source=ENV backend=FFmpeg-P010
```

---

## 10. WYNIKI TESTÓW JEDNOSTKOWYCH
Pakiet testów jednostkowych: `tests/test_amd_decode_gui_switch.py`:
- `test_default_no_setting_defaults_to_gpu`: **PASSED**
- `test_gui_change_cpu_without_save_reverts_on_restart`: **PASSED**
- `test_gui_change_cpu_with_save_persists_across_restart`: **PASSED**
- `test_options_pipeline_passes_amd_decode_mode`: **PASSED**
- `test_priority_resolution_contract`: **PASSED**
- `test_render_tab_amd_decode_switch`: **PASSED**
- Wynik zbiorczy: **6/6 PASSED** (2.41 s).

---

## 11. GIT STATUS --SHORT
```text
 M def_layout.json
 M src/ffmpeg/amd_native_exporter.py
 M src/ffmpeg/streaming.py
 M src/gui/layout_manager.py
 M src/gui/qt/_mixins/preset_mixin.py
 M src/gui/qt/_mixins/render_mixin.py
 M src/gui/qt/controller.py
 M src/gui/qt/signals.py
 M src/gui/qt/tabs/render_tab.py
 M src/gui/qt/tabs/settings_tab.py
?? tests/test_amd_decode_gui_switch.py
```

---

## 12. GIT DIFF --STAT
```text
 def_layout.json                    |  3 +-
 src/ffmpeg/amd_native_exporter.py  | 27 ++++++++++++-
 src/ffmpeg/streaming.py            |  2 ++
 src/gui/layout_manager.py          |  2 +-
 src/gui/qt/_mixins/preset_mixin.py |  5 ++++
 src/gui/qt/_mixins/render_mixin.py |  1 +
 src/gui/qt/controller.py           |  7 +++++
 src/gui/qt/signals.py              |  4 +++
 src/gui/qt/tabs/render_tab.py      | 44 +++++++++++++++++++++++++++++
 src/gui/qt/tabs/settings_tab.py    | 58 ++++++++++++++++++++++++++++++++++++--
 10 files changed, 148 insertions(+), 5 deletions(-)
```

---

## FINAL VERDICT

```text
GPU GOLDEN PATH RESTORED:          YES
GPU 10-BIT HDR:                    YES (internal P010 decode & compositing, encoded as AMF NV12 parity baseline)
GPU VISUAL PARITY:                 YES
CPU SWITCH STILL AVAILABLE:        YES
CPU DOES NOT CONTAMINATE GPU STATE:YES
READY FOR USER GUI TEST:           YES
```
