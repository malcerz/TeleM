# RAPORT: AMD DECODE MODE GUI SWITCH
**Data:** 2026-09-03
**Repo:** `C:\_DEV\TeleM-integration`
**Branch:** `integration/intel-amd`
**Bazowy HEAD:** `e6b875e` (zawierający `b4047ab`)

---

## 1. MIEJSCE USTAWIENIA W GUI
- **Wyłączna lokalizacja (Zakładka Renderingu):**
  - **Zakładka:** `Rendering` (`RenderTab`).
  - **Sekcja:** Formularz `Ustawienia eksportu` (bezpośrednio pod wyborem `Encoder:`, przed rozdzielczością i parametrami HUD).
  - **Widget:** `QComboBox` (`cmb_amd_decode`).
  - **Etykieta formularza:** `Dekodowanie AMD:`.
  - **Dostępne opcje:**
    1. `GPU — sprzętowe (zalecane)` (wartość logiczna: `"gpu"`, indeks domyślny `0`).
    2. `CPU — programowe` (wartość logiczna: `"cpu"`, indeks `1`).
  - **Ostrzeżenie / Help text:**
    - Tekst ostrzegawczy: `"Tryb CPU może być znacznie wolniejszy od GPU i mocno obciążać procesor."`.
    - Tooltip na comboboxie + dynamiczna etykieta `lbl_cpu_warning` w kolorze bursztynowym (`#e6a700`) pod polem wyboru, widoczna wyłącznie przy wyborze trybu CPU (`setVisible(mode == "cpu")`).
- **Całkowity brak w zakładce Ustawienia (`SettingsTab`):**
  - Opcja dekodowania dotyczy **WYŁĄCZNIE procesu renderingu** (finalnego eksportu wideo).
  - Nie ma nic wspólnego z podglądem wideo (`mpv` / neutralny podgląd roboczy).
  - Usunięto grupę `Renderowanie / AMD`, pole wyboru oraz wszelkie powiązania sygnałów z `SettingsTab`. W zakładce `Ustawienia` nie ma żadnego elementu związanego z dekodowaniem AMD.

---

## 2. PERSISTENCE KEY I LOGIKA ZAPISU
- **Klucz globalny:** `"amd_decode_mode": "gpu"` / `"amd_decode_mode": "cpu"`.
- **Lokalizacja:** Sekcja `"global"` w pliku `def_layout.json`.
- **Mechanizm zapisu:**
  - Wybór w UI zmienia wartość w pamięci (`controller.amd_decode_mode`), lecz **nie wyzwala autosave**.
  - Zapis na dysk następuje po kliknięciu przycisku **„Zapisz ustawienia”** (`sig_save_global_settings`) lub zapisie presetu.
  - W przypadku braku zapisu i ponownego uruchomienia programu przywracana jest ostatnia zapisana wartość z `def_layout.json` (lub domyślne GPU).
- **Izolacja presetów i layoutów:**
  - Zmiana trybu dekodowania NIE modyfikuje presetu użytkownika (`.json`).
  - Zmiana NIE modyfikuje roboczego layoutu projektu wideo (`.layout.json`).
  - Zmiana NIE modyfikuje wskaźników (`indicators`) w `def_layout.json`.

---

## 3. PRIORYTET KONFIGURACJI (PRIORITY CONTRACT)
Zaimplementowano ścisłą hierarchię trzech poziomów:
1. **Priorytet 1 (Najwyższy):** Explicit environment override:
   - `AMD_DECODE_MODE=CPU` lub `AMD_DECODE_MODE=0` $\rightarrow$ wymusza tryb CPU (niezależnie od GUI).
   - `AMD_DECODE_MODE=GPU` lub `AMD_DECODE_MODE=1` $\rightarrow$ wymusza tryb GPU (niezależnie od GUI).
2. **Priorytet 2 (Standardowy bieg aplikacji):** Ustawienie z interfejsu graficznego przekazywane jako explicit parametr wywołania:
   - `options["amd_decode_mode"]` $\rightarrow$ `stream_overlay_to_ffmpeg(..., amd_decode_mode=...)` $\rightarrow$ `export_amd_native_d3d11(..., amd_decode_mode=...)`.
3. **Priorytet 3 (Fallback):** W przypadku braku parametru i braku zmiennej środowiskowej:
   - Domyślnie: **`GPU`** (`GPU_HUD_D3D11VA`).

---

## 4. GPU SMOKE (REAL RUN 150 KLATEK)
- **Polecenie / parametr:** `amd_decode_mode="gpu"` (bez zmiennych env).
- **Potwierdzony log startowy:**
  ```text
  [AMD DECODE] requested=GPU effective=GPU source=GUI backend=D3D11VA
    DECODE_MODE      = GPU (D3D11VA / VCN)
  ```
- **Przebieg renderu:**
  - Wyrenderowano: **150 klatek**.
  - Czas kodowania wideo: **3.525 s**.
  - Render FPS: **42.551 FPS** (Effective: 30.837 FPS ze startem pipeline'u).
  - Wygenerowany plik: `scratch/smoke_decode_gpu.mp4` (**21 856 788 bajtów**).
  - Sonda FFprobe: `3840x2160`, `yuv420p`, `29.970 FPS`, `nb_frames=150`.

---

## 5. CPU SMOKE (REAL RUN 150 KLATEK)
- **Polecenie / parametr:** `amd_decode_mode="cpu"` (bez zmiennych env).
- **Potwierdzony log startowy:**
  ```text
  [AMD DECODE] requested=CPU effective=CPU source=GUI backend=FFmpeg-P010
    DECODE_MODE      = CPU (FFmpeg P010)
  ```
- **Przebieg renderu:**
  - Wyrenderowano: **150 klatek**.
  - Czas kodowania wideo: **6.747 s**.
  - Render FPS: **22.233 FPS** (Effective: 18.907 FPS).
  - Wygenerowany plik: `scratch/smoke_decode_cpu.mp4` (**22 134 286 bajtów**).
  - Sonda FFprobe: `3840x2160`, `yuv420p`, `29.970 FPS`, `nb_frames=150`.

---

## 6. JAKOŚĆ I FORMAT (HDR / P010 / HEVC MAIN10)
- Istniejąca ścieżka CPU decode pozostała w 100% nienaruszona:
  - FFmpeg software HEVC Main10 $\rightarrow$ potok P010 10-bit przez 64 MB Named Pipe.
  - Natywny bufor stagingowy DirectX 11 w formacie `DXGI_FORMAT_P010`.
  - Przestrzeń barw i metadane HDR (HLG / BT.2020) zachowane identycznie jak w ścieżce GPU.
  - Zero degradacji do 8-bit NV12 czy RGB na etapie podawania klatek wideo do compositingu.

---

## 7. BACKEND ISOLATION (IZOLACJA PLATFORMOWA)
- Parametr `amd_decode_mode` jest aplikowany **wyłącznie** gdy aktywnym enkoderem jest AMD (`encoder in ("amd", "amd_native")`).
- Ścieżki Intel QSV (`encoder == "intel"`), NVIDIA NVENC (`encoder == "nv"`) oraz fallback software'owy nie odczytują ani nie są modyfikowane przez ten przełącznik.
- Podgląd roboczy (`mpv`) nie korzysta z tego przełącznika i działa w 100% niezależnie.

---

## 8. WYNIKI TESTÓW AUTOMATYCZNYCH
- Zestaw testowy: `tests/test_amd_decode_gui_switch.py`:
  - `test_settings_tab_has_no_amd_decode_control`: **PASSED** (potwierdza brak kontrolki w `SettingsTab`)
  - `test_default_no_setting_defaults_to_gpu`: **PASSED** (domyślnie GPU w `RenderTab`)
  - `test_gui_change_cpu_without_save_reverts_on_restart`: **PASSED**
  - `test_gui_change_cpu_with_save_persists_across_restart`: **PASSED**
  - `test_options_pipeline_passes_amd_decode_mode`: **PASSED**
  - `test_priority_resolution_contract`: **PASSED**
  - `test_render_tab_amd_decode_switch`: **PASSED** (weryfikacja przełącznika w `RenderTab`, dynamiczne ostrzeżenie, emisja w `options["amd_decode_mode"]`, przywracanie sygnałem)
- Wynik: **7 PASSED / 0 FAILED** w 1.26 s.

---

## 9. GIT STATUS --SHORT
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
?? tests/test_amd_decode_gui_switch.py
```

---

## 10. GIT DIFF --STAT
```text
 def_layout.json                    |  3 ++-
 src/ffmpeg/amd_native_exporter.py  | 31 +++++++++++++++++++++++++++
 src/ffmpeg/streaming.py            |  2 ++
 src/gui/layout_manager.py          |  2 +-
 src/gui/qt/_mixins/preset_mixin.py |  5 +++++
 src/gui/qt/_mixins/render_mixin.py |  1 +
 src/gui/qt/controller.py           |  7 ++++++
 src/gui/qt/signals.py              |  4 ++++
 src/gui/qt/tabs/render_tab.py      | 44 ++++++++++++++++++++++++++++++++++++++
 9 files changed, 97 insertions(+), 2 deletions(-)
```

---

## FINAL VERDICT

```text
GPU DEFAULT:                   YES
CPU MANUAL SELECT:             YES
CPU PERSISTENCE:               YES
ENV OVERRIDE:                  YES
PRESET/LAYOUT ISOLATION:       YES
INTEL/NVIDIA UNCHANGED:        YES
```
