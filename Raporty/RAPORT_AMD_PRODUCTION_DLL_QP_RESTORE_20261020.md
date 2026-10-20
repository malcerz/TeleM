# Raport: Przywrócenie Zatwierdzonej Produkcyjnej DLL AMD (17.10.2026)

Data: 2026-10-20  
Gałąź: `main`  
Status: Wdrożono pomyślnie do produkcji (`runtime/amd/bin/telem_amd_native.dll`)  

---

## 1. Weryfikacja Sum Kontrolnych SHA-256

Zgodnie ze zleceniem zweryfikowano sumy kontrolne plików w `runtime/amd/bin/`:

| Plik | Rozmiar (B) | SHA-256 | Status |
| :--- | :--- | :--- | :--- |
| `runtime/amd/bin/telem_amd_native.dll.bak_before_qp_removal_20261019` | 297 984 | `BBCA75FBD0DFC5D7CBB61922E92F8D5F049B4305DD18335315667E6E5E54CA5F` | Zgodny z wzorcem |
| `runtime/amd/bin/telem_amd_native_QP_OLD.dll` | 297 984 | `BBCA75FBD0DFC5D7CBB61922E92F8D5F049B4305DD18335315667E6E5E54CA5F` | Zgodny z wzorcem |
| `runtime/amd/bin/telem_amd_native.dll.bak_18a0503f_20261020` | 1 884 160 | `18A0503F4EEC574B9A967FB0D1D5DDEA6061B6FD3FBCCF6C26F8BAFD2C4827BB` | Kopia zapasowa poprzedniej DLL |
| `runtime/amd/bin/telem_amd_native.dll` (**nowa produkcja**) | 297 984 | `BBCA75FBD0DFC5D7CBB61922E92F8D5F049B4305DD18335315667E6E5E54CA5F` | **AKTYWNA PRODUKCJA** |

Utworzono nienaruszalną kopię zapasową dotychczasowej biblioteki produkcyjnej:
`runtime/amd/bin/telem_amd_native.dll.bak_18a0503f_20261020`.

---

## 2. Weryfikacja Binarki, Zależności i ABI

Wykonano inspekcję struktury PE oraz testy ładowania aktywnej biblioteki `telem_amd_native.dll`:

1. **Zależności MSVC i systemowe:**
   - `MSVCP140.dll`, `VCRUNTIME140.dll`, `VCRUNTIME140_1.dll` (Visual C++ 2015-2022 CRT)
   - Windows UCRT (`api-ms-win-crt-*`)
   - DirectX 11 / Media Foundation (`d3d11.dll`, `D3DCOMPILER_47.dll`, `MFPlat.DLL`, `MFReadWrite.dll`, `ole32.dll`, `KERNEL32.dll`)
2. **Weryfikacja kontraktowa `verify_amd_dll()` (`tools/build_portable_release.py`):**
   - **ABI Version:** 9 (zgodna z bieżącym kontraktem SportCamHUD)
   - **Color Features:** `0x3` (pełna obsługa HLG preserve HEVC Main10 oraz konwersji HLG->SDR)
   - **Wymagane eksporty (88 funkcji):**
     - `telem_amd_get_encoder_qp_stats`
     - `telem_amd_get_encoder_qp_feedback_diag`
     - `telem_amd_has_map_pitch` / `telem_amd_set_map_pitch` / `telem_amd_get_map_pitch_enabled` (GPU Pitch)
     - `telem_amd_probe_hevc_main10`
     - `telem_amd_set_preview_tap` / `telem_amd_poll_preview_tap`
3. **Pochodzenie binarki (Build Info):**
   - Wbudowany znacznik buildu:
     `build_id=telem-amd-native/1.0.0+fafc7986b4a3.srcb6326040a87e; build_timestamp=2026-10-17T10:44:30+02:00; git_commit=fafc7986b4a31062b9d96863a76d882d90222ff1; source_hash=b6326040a87ec5db53c3ebf11c39c8e639cd6370be0a5adf8ec66b6630a14a4a`
   - **Zgodność ze źródłami:** Przywrócona binarka pochodzi ze sprawdzonego, historycznego buildu z 17 października 2026 (commit `fafc7986b4a3`). Może ona różnić się od aktualnych plików w drzewie `native/`, lecz jej kontrakt binarny (ABI 9, GPU Pitch, VBR QP feedback, HLG) został w 100% potwierdzony na fizycznej platformie AMD.

---

## 3. Aktualizacja Manifestu i Skryptu Wydania Portable

Zaktualizowano konfigurację repozytorium pod kątem zatwierdzonego hasha:

1. **`runtime/runtime_manifest.json`:**
   - Ścieżka: `amd/bin/telem_amd_native.dll`
   - Oczekiwany SHA-256: `bbca75fbd0dfc5d7cbb61922e92f8d5f049b4305dd18335315667e6e5e54ca5f`
   - Rozmiar: `297984`
   - Zgodność z plikiem na dysku: `SHA MATCH: True`, `SIZE MATCH: True`
2. **`tools/build_portable_release.py`:**
   - Wartość `EXPECTED_SHA256["runtime/amd/bin/telem_amd_native.dll"]` ustawiona na `bbca75fbd0dfc5d7cbb61922e92f8d5f049b4305dd18335315667e6e5e54ca5f`.
   - Poprzednia biblioteka bez diagnostyki QP (`18a0503f...`) została dodana do `FORBIDDEN_SHA256`, aby wykluczyć przypadkową regresję.
   - Weryfikacja: `EXPECTED MATCH: True`, `FORBIDDEN: False`.

---

## 4. Status Udziału Sieciowego AMD

Plik `runtime/amd/bin/telem_amd_native.dll` został pomyślnie podmieniony po potwierdzeniu przez użytkownika zamknięcia aplikacji na komputerze AMD. Kolejne uruchomienie SportCamHUD na komputerze AMD z udziału sieciowego `\\192.168.1.112\c\_DEV\SportCamHUD` automatycznie załaduje zatwierdzoną bibliotekę z działającym sprzętowym feedbackiem QP.
