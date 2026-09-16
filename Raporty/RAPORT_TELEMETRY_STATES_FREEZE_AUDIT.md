# RAPORT: Telemetry States Freeze Audit & Backend Readiness

Data wykonania: 2026-09-15  
Workspace: `H:\_Dev\BikeRideHUD`  
Status: **COMPLETE (CASE A — NVIDIA TELEMETRY FROZEN, F64 ONLY DIAGNOSTIC, AMD NOT YET CONNECTED)**

---

## 1. Cel zadania

1. Wyjaśnić i udokumentować rozbieżność między kolumnami `BATTERY_RAW (f32)` a `BATTERY_RAW (f64)` z poprzedniego raportu testowego.
2. Podać i potwierdzić kanoniczne wartości modelu baterii Garmin dla rzeczywistego produkcyjnego stanu na klatkach granicznych:
   - `Clip 1 -> Clip 2`: klatki 4595, 4596, 4597
   - `Clip 2 -> Clip 3`: klatki 54515, 54516, 54517
3. Przeprowadzić audyt gotowości backendu AMD pod kątem wykorzystania modułu `compute_fast_telemetry_states`.
4. Przedstawić macierz ścieżek przygotowania telemetrii dla backendów NVIDIA, AMD i Intel.
5. Podjąć i udokumentować decyzję o zamrożeniu (`FREEZE`) zoptymalizowanego modułu telemetrii dla NVIDIA.

---

## 2. Wyjaśnienie F32 vs F64 w Raporcie Baterii

### 2.1. Obserwacja
W poprzednim raporcie walidacyjnym dla klatki 4596 odnotowano:
- `BATTERY_RAW (f32) ~= 68.899010%`
- `BATTERY_RAW (f64) ~= 68.834748%`
Obie wartości wykazywały stałą deltę międzyklatkową, jednak różniły się wartością bezwzględną o $\sim 0.064\%$.

### 2.2. Ustalenia i Root Cause
1. **Wartość F32 (`BATTERY_RAW (f32)`):**
   - Jest to **RRECZYWISTA WARTOŚĆ PRODUKCYJNA** generowana przez produkcyjny model `compute_fast_telemetry_states()` oraz `battery_presentation_plan()`.
   - Parametry planu wyliczone z pliku `20260911.fit`:
     - $\text{start\_value} = 69.0\%$
     - $\text{end\_value} = 67.6070817\%$
     - $\text{span} = 2115.146367\text{ s}$
   - Dla klatki 4596 ($t_{\text{global}} = 153.3532\text{ s}$):
     $$\text{raw\_f64} = 69.0 + (67.6070817 - 69.0) \cdot \frac{153.3532}{2115.146367} = 68.89901008\%$$
   - Zapis do `ctypes.c_float` (float32 w `TelemFrameState`): **`68.89900970%`** ($\approx 68.899010\%$).

2. **Wartość F64 (`BATTERY_RAW (f64)`):**
   - Był to **POMOCNICZY ARTEFAKT DIAGNOSTYCZNY SKRYPTU TESTOWEGO** `scratch/test_all_63391_frames_parity.py` (linia 73):
     ```python
     val_f64 = 68.9 + ((68.0 - 68.9) / timeline.project_duration_s) * t_global
     ```
   - Autor skryptu testowego wpisał w kolumnie diagnostycznej poglądowe stałe $68.9 \to 68.0$ zamiast odpytać `plan.segments[0]`.
   - Obliczenie $68.9 + \frac{-0.9}{2115.15} \cdot 153.3532$ dawało syntetyczne $68.834748\%$.

3. **Wnioski:**
   - W kodzie produkcyjnym **NIE MA BŁĘDU**.
   - Wartość trafiająca do struktury `TelemFrameState.garmin_battery_pct`: **`68.899010%`**.
   - Wartość trafiająca do Direct2D / finalnego HUD: **`68.899010%`** (formatowana jako string `b"68.9"` w C-struct, oraz `68.90%` w rendererze Pillow).
   - Różnica wynikała w 100% z syntetycznej formuły w kolumnie pomocniczej skryptu testowego.

---

## 3. Kanoniczne Wartości Produkcyjne Baterii Garmin

Poniższa tabela przedstawia rzeczywiste stany produkcyjne pobrane bezpośrednio z tablicy `TelemFrameState` dla klatek granicznych:

| Klatka | Czas globalny | Obliczenie float64 (model) | Zapisane do ctypes (f32) | Odczytane z ctypes (f32) | Ciąg prezentacyjny (`st.garmin_battery_str`) |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **4595** (Clip 0 end) | 153.3198 s | 68.89903205% | 68.89903259% | **68.89903259%** | `68.9` |
| **4596** (Clip 1 start) | 153.3532 s | 68.89901008% | 68.89900970% | **68.89900970%** | `68.9` |
| **4597** | 153.3866 s | 68.89898810% | 68.89898682% | **68.89898682%** | `68.9` |
| | | | | | |
| **54515** (Clip 1 end) | 1818.9838 s | 67.80211799% | 67.80211639% | **67.80211639%** | `67.8` |
| **54516** (Clip 2 start) | 1819.0172 s | 67.80209602% | 67.80209351% | **67.80209351%** | `67.8` |
| **54517** | 1819.0506 s | 67.80207404% | 67.80207062% | **67.80207062%** | `67.8` |

- **Delta graniczna 4595 $\to$ 4596:** `-0.00002289%` (f32) / `-0.00002198%` (f64)
- **Delta normalna 4594 $\to$ 4595:** `-0.00002289%` (f32) / `-0.00002198%` (f64)
- **Stosunek (Boundary / Normal Ratio):** **`1.000000`** (**PASS**)

---

## 4. Audyt Gotowości Backendu AMD (AMD Readiness Audit)

### 4.1. Odpowiedź jednoznaczna
> **Czy AMD obecnie wywołuje `compute_fast_telemetry_states`?**  
> **`NO`**

### 4.2. Szczegóły architektury telemetrii w AMD:
1. **Lokalizacja:** `src/ffmpeg/amd_native_exporter.py` oraz `src/ffmpeg/amd_child_process.py`.
2. **Mechanizm:** 
   - AMD nie posiada w pamięci prekomputowanej tablicy `TelemFrameState` ctypes.
   - Pętla producenta CPU generuje klatki w locie za pomocą `compose_overlay()`, gdzie dla każdej klatki i każdego wskaźnika odpytywany jest `telemetry.resolve_value(indicator, target_dt)`.
   - Elementy dynamiczne (mapa, speed gauge, wykresy AFTER-MAP HR i Cadence) są wycinane i blendowane na GPU przez natywne shadery D3D11 (`BlendMap`, `BlendGauge`, `BlendAfterMapCharts`).
3. **Problem skalarny w AMD:**
   - Wskaźniki warstwy `CPU ABOVE` (np. teksty wysokości, nachylenia, kompasu) nadal ponoszą narzut rysowania Pillow i rozwiązywania skalarnego per-klatkę ($\sim 14-22\text{ ms/klatkę}$).
4. **Kontrakt podłączenia `telemetry_states_fast` w przyszłości:**
   - Gdy zapadnie decyzja o przyspieszeniu `CPU ABOVE` w AMD, wywołanie będzie zgodne z interfejsem:
     ```python
     states = compute_fast_telemetry_states(
         telemetry=telemetry,
         video_timeline=video_timeline,
         export_frames=export_frames,
         fps=fps,
         prep_tracker=prep_tracker,
         chunk_size=500,
     )
     ```
   - **Decyzja na teraz:** NIE podłączać modułu do AMD, zachować w pełni nienaruszony i ustabilizowany baseline AMD.

---

## 5. Macierz Przygotowania Telemetrii Backendów

| Backend | Ścieżka przygotowania telemetrii | Używa `telemetry_states_fast` | Narzut fazy prep (63 391 klatek) |
| :--- | :--- | :--- | :--- |
| **NVIDIA** | `compute_fast_telemetry_states` $\to$ C-struct array `TelemFrameState` $\to$ D2D natywny HUD | **YES** | **`~0.42 s`** ($\sim 82\times$ speedup) |
| **AMD** | On-the-fly `compose_overlay()` per klatka (Pillow/CPU) + D3D11 GPU passes | **NO** | `0.00 s` prep (rozłożony w pętli $\sim 14-22\text{ ms/f}$) |
| **Intel** | Izolowana podstawa DXGI/QSV (ETAP 1) / FFmpeg overlay stream | **NO** | N/A (etap przygotowawczy) |

---

## 6. Decyzja o Zamrożeniu (Freeze Decision)

Ponieważ:
1. Produkcyjne wartości `f32` w strukturze `TelemFrameState` oraz prezentacja w finalnym HUD są w 100% poprawne.
2. Stosunek delty granicznej baterii wynosi dokładnie `1.000000` (brak artefaktów na granicach klipów).
3. Pełna walidacja parzystości na wszystkich 63 391 klatkach zakończyła się wynikiem 100% PASS (0 różnic $> 10^{-6}$, 0 błędów stringów).
4. Rozbieżność `f64` została jednoznacznie wyjaśniona jako pomocniczy artefakt diagnostyczny skryptu testowego.

Zatwierdza się stan:
```text
TELEMETRY_STATES NVIDIA = FROZEN / DONE
```

Klasyfikacja: **`CASE A — NVIDIA TELEMETRY FROZEN, F64 ONLY DIAGNOSTIC, AMD NOT YET CONNECTED`**

---

## 7. Spis Artefaktów w `scratch/telemetry_states_freeze_audit/`

- `battery_f32_f64_explanation.txt` (szczegółowa analiza f32 vs f64)
- `production_state_samples.txt` (tabela próbek produkcyjnych dla klatek 4595..4597 i 54515..54517)
- `backend_telemetry_matrix.txt` (zestawienie backendów NVIDIA, AMD, Intel)
- `amd_readiness.txt` (raport gotowości i architektury AMD)
- `test.log` (log walidacji audytu)
- `artifacts_manifest.txt` (sumy kontrolne MD5 artefaktów)
- `ntfy_result.txt` (potwierdzenie doręczenia powiadomienia NTFY z kodem wyjścia 0)
