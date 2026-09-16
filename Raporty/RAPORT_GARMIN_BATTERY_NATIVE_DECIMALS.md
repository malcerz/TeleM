# RAPORT: Prezentacja Garmin Battery w Natywnym HUD NVIDIA (2 Miejsca po Przecinku)

Data wykonania: 2026-09-15  
Workspace: `H:\_Dev\BikeRideHUD`  
Status: **PASS (CASE B — NATIVE STRING FIXED TO 2 DECIMALS)**

---

## 1. Cel zadania

1. Sprawdzić produkcyjną ścieżkę renderowania Garmin Battery w natywnym HUD NVIDIA D3D11 / NVENC (`telem_nvenc_d3d11.dll` / Direct2D).
2. Ustalić jednoznacznie, czy natywny renderer Direct2D pobiera tekst z pola `garmin_battery_str`, czy formatuje `garmin_battery_pct` po stronie C++.
3. Zapewnić i zweryfikować, że tekst wyświetlany na ekranie w natywnym HUD NVIDIA ma **zawsze dokładnie 2 miejsca po przecinku** (np. `68.90 %`, `67.80 %`), zgodnie z wymaganiem projektowym.
4. Przeprowadzić audyt i walidację na zestawie klatek testowych (frame 0, 4595..4597, 54515..54517, last frame) oraz potwierdzić 100% parzystość na wszystkich 63 391 klatkach.

---

## 2. Identyfikacja Ścieżki Produkcyjnej (Native Path Trace)

### 2.1. Odpowiedź na pytanie kluczowe
> **Czy finalny natywny HUD Garmin Battery bierze tekst z:**  
> **A. `garmin_battery_str`** czy **B. `garmin_battery_pct` i formatuje float po stronie native/D2D?**  
> 
> **ODPOWIEDŹ: A. `garmin_battery_str`**

### 2.2. Dokładna proweniencja kodu:
1. **Plik generowania telemetrii (Python precompute):**
   - [src/telemetry_states_fast.py](file:///H:/_Dev/BikeRideHUD/src/telemetry_states_fast.py), linia 277:
     ```python
     st.garmin_battery_str = f"{st.garmin_battery_pct:.2f}".encode("ascii")
     ```
2. **Definicja struktury C-struct:**
   - [src/ffmpeg/nvidia_config.py](file:///H:/_Dev/BikeRideHUD/src/ffmpeg/nvidia_config.py) $\to$ `class TelemFrameState(ctypes.Structure)`:
     - Pole string: `("garmin_battery_str", ctypes.c_char * 32)`
     - Pole float: `("garmin_battery_pct", ctypes.c_float)`
3. **Deskryptor wskaźnika w eksporterze:**
   - [src/ffmpeg/nvidia_native_exporter.py](file:///H:/_Dev/BikeRideHUD/src/ffmpeg/nvidia_native_exporter.py), linie 538–578:
     - Typ wskaźnika: `4` (`SegmentBarIndicator`)
     - Klucz: `b"fit_garmin_battery_percent_text"`
     - Pole telemetrii: `9`
4. **Implementacja w natywnym rendererze Direct2D:**
   - `native/d3d11_nvenc_pipeline/src/indicators/segment_bar_indicator.cpp`
   - Funkcja: `void SegmentBarIndicator::Render(ID2D1DeviceContext* pD2D, const TelemFrameState& state)`
   - Linie 107–109:
     ```cpp
     float raw_val = state.garmin_battery_pct;
     const char* val_str = state.garmin_battery_str;
     ```
   - Linie 155–168:
     ```cpp
     if (m_pFmtValue && val_str && val_str[0]) {
         std::wstring fullValText;
         wchar_t wVal[64] = { 0 };
         MultiByteToWideChar(CP_UTF8, 0, val_str, -1, wVal, 64);
         fullValText = wVal;
         if (strcmp(val_str, "--") != 0 && m_style.unit[0] && fullValText.find(m_style.unit) == std::wstring::npos) {
             fullValText += L" ";
             fullValText += m_style.unit;
         }
         FontCache::DrawTextOutlined(pD2D, fullValText.c_str(), m_pFmtValue, valRect, m_pTextBrush, m_pOutlineBrush, outline_w, DWRITE_TEXT_ALIGNMENT_LEADING);
     }
     ```

---

## 3. Wprowadzona Poprawka

W pliku [src/telemetry_states_fast.py](file:///H:/_Dev/BikeRideHUD/src/telemetry_states_fast.py) zmieniono formatowanie ciągu z `1` na `2` miejsca po przecinku:
```diff
- st.garmin_battery_str = f"{st.garmin_battery_pct:.1f}".encode("ascii")
+ st.garmin_battery_str = f"{st.garmin_battery_pct:.2f}".encode("ascii")
```

Nie zmieniono:
- Wartości `raw_float` ani `st.garmin_battery_pct` (dokładność float64/float32 zachowana).
- Nachylenia baterii (`battery slope`).
- Osi czasu (`concatenated timeline`).
- Interpolacji ani ciągłości granic klipów.

---

## 4. Tabela Zweryfikowanych Klatek Produkcyjnych

Poniższa tabela przedstawia rzeczywisty łańcuch wartości od modelu matematycznego do finalnego tekstu renderowanego na ekranie:

| Klatka | Czas globalny | Model float64 | Ctypes float32 | Ctypes string (`garmin_battery_str`) | Wejście natywnego D2D | Finalny tekst na ekranie |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **0** (Start) | 0.0000 s | 69.000000% | 69.000000% | `69.00` | `69.00` | **`69.00 %`** |
| **4595** (Clip 0 end) | 153.3198 s | 68.899032% | 68.899033% | `68.90` | `68.90` | **`68.90 %`** |
| **4596** (Clip 1 start) | 153.3532 s | 68.899010% | 68.899010% | `68.90` | `68.90` | **`68.90 %`** |
| **4597** | 153.3866 s | 68.898988% | 68.898987% | `68.90` | `68.90` | **`68.90 %`** |
| **54515** (Clip 1 end) | 1818.9838 s | 67.802118% | 67.802116% | `67.80` | `67.80` | **`67.80 %`** |
| **54516** (Clip 2 start) | 1819.0172 s | 67.802096% | 67.802094% | `67.80` | `67.80` | **`67.80 %`** |
| **54517** | 1819.0506 s | 67.802074% | 67.802071% | `67.80` | `67.80` | **`67.80 %`** |
| **63390** (Koniec) | 2115.1130 s | 67.607104% | 67.607101% | `67.61` | `67.61` | **`67.61 %`** |

Wszystkie klatki wykazują **dokładnie 2 miejsca po przecinku** w finalnym HUD.

---

## 5. Pełna Walidacja Parzystości 63 391 Klatek

Przeprowadzono pełny test parzystości na wszystkich 63 391 klatkach (`scratch/test_all_63391_frames_parity.py`):
- **14 pól numerycznych:** 100% PASS (0 różnic $> 10^{-6}$, max diff = 0.0).
- **15 ciągów tekstowych:** 100% PASS (0 niezgodności bajtowych na 63 391 klatkach).
- **Czas wykonania prekomputacji:** **`0.4293 s`** ($\sim 80\times$ speedup względem 34.23 s).

---

## 6. Izolacja Backendów

- **AMD:** Kod AMD nie został dotknięty ani zmodyfikowany.
- **Intel:** Kod Intel nie został dotknięty.
- **Pola całkowite (HR, Cadence, Power, ISO, Exposure):** Pozostają ściśle 0 miejsc po przecinku (integer presentation).

---

## 7. Podsumowanie i Spis Artefaktów

Klasyfikacja: **`CASE B — NATIVE STRING FIXED TO 2 DECIMALS`**

Zapisane artefakty w `scratch/garmin_battery_native_decimals/`:
- `native_path_trace.txt`
- `battery_format_samples.txt`
- `generate_artifacts.py`
- `test.log`
- `artifacts_manifest.txt`
- `ntfy_result.txt` (wysłano z kodem wyjścia 0)
