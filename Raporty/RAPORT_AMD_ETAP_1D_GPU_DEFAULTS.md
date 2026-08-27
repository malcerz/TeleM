# RAPORT: AMD ETAP 1D — Aktywacja Domyślna Zwalidowanych Ścieżek GPU AMD

**Data:** 2026-08-25  
**Backend:** AMD_NATIVE_D3D11 (D3D11VA Decode, Direct Fused NV12 Compositor, AMF HEVC CQP 28 Speed)  
**Zadanie:** Ustawienie zwalidowanych w ETAPIE 1C ścieżek akceleracji GPU (`AMD_GPU_MAP_ROTATE` oraz `AMD_AFTER_MAP_CHART_GPU`) jako domyślnie włączone (`ON`), przy jednoczesnym zachowaniu pełnej możliwości jawnego wyłączenia każdej ścieżki przez zmienną środowiskową (`=0`).

---

## 1. ZMIENIONE PLIKI

- `src/ffmpeg/amd_native_exporter.py`:
  - Zmiana domyślnej wartości parsowania dla `AMD_AFTER_MAP_CHART_GPU` z `False` na `True` (linia 1294).
  - Zmiana domyślnej wartości parsowania dla `AMD_GPU_MAP_ROTATE` z `False` na `True` (linia 1406).
  - Uzupełnienie logów startowych o informację o pochodzeniu konfiguracji (`default` vs `env`).

---

## 2. STARE VS NOWE DEFAULTY

| Zmienna / Ścieżka | Stary Default (ETAP 1C) | Nowy Default (ETAP 1D) | Możliwość wymuszenia fallbacku CPU |
| :--- | :---: | :---: | :---: |
| `AMD_GPU_MAP_ROTATE` | `0` (OFF) | **`1` (ON)** | `AMD_GPU_MAP_ROTATE=0` |
| `AMD_AFTER_MAP_CHART_GPU` | `0` (OFF) | **`1` (ON)** | `AMD_AFTER_MAP_CHART_GPU=0` |

---

## 3. WYNIKI TESTÓW WALIDACYJNYCH

### Test A: Default (Brak zmiennych środowiskowych)
- **Komenda:** `run_test("test_a_default", {"AMD_GPU_MAP_ROTATE": None, "AMD_AFTER_MAP_CHART_GPU": None})`
- **Logi startowe:**
  - `[AMD NATIVE D3D11] AMD_AFTER_MAP_CHART_GPU: ON (default; native after-map chart GPU_SPLIT active)`
  - `[AMD NATIVE D3D11] AMD_GPU_MAP_ROTATE: 1 (flag=True [default], track_up=True)`
- **Wynik:** `PASS` (Obie funkcje GPU aktywne domyślnie, brak obrotu Pillow CPU, brak wykresów HR/Cadence w CPU ABOVE).

### Test B: Full Fallback (Jawne `=0` dla obu zmiennych)
- **Komenda:** `run_test("test_b_full_fallback", {"AMD_GPU_MAP_ROTATE": "0", "AMD_AFTER_MAP_CHART_GPU": "0"})`
- **Logi startowe:**
  - `[AMD NATIVE D3D11] AMD_AFTER_MAP_CHART_GPU: OFF (env; after-map charts CPU_REFERENCE)`
  - `[AMD NATIVE D3D11] AMD_GPU_MAP_ROTATE: 0 (flag=False [env], track_up=True)`
- **Wynik:** `PASS` (Klasyczna ścieżka referencyjna CPU działa w pełni poprawnie).

### Test C1: Override Indywidualny (Map OFF, Charts ON)
- **Komenda:** `run_test("test_c1_map_off_charts_on", {"AMD_GPU_MAP_ROTATE": "0", "AMD_AFTER_MAP_CHART_GPU": "1"})`
- **Logi startowe:**
  - `[AMD NATIVE D3D11] AMD_AFTER_MAP_CHART_GPU: ON (env; native after-map chart GPU_SPLIT active)`
  - `[AMD NATIVE D3D11] AMD_GPU_MAP_ROTATE: 0 (flag=False [env], track_up=True)`
- **Wynik:** `PASS` (Mapa na CPU, wykresy HR/Cadence na GPU).

### Test C2: Override Indywidualny (Map ON, Charts OFF)
- **Komenda:** `run_test("test_c2_map_on_charts_off", {"AMD_GPU_MAP_ROTATE": "1", "AMD_AFTER_MAP_CHART_GPU": "0"})`
- **Logi startowe:**
  - `[AMD NATIVE D3D11] AMD_AFTER_MAP_CHART_GPU: OFF (env; after-map charts CPU_REFERENCE)`
  - `[AMD NATIVE D3D11] AMD_GPU_MAP_ROTATE: 1 (flag=True [env], track_up=True)`
- **Wynik:** `PASS` (Obrót mapy na GPU, wykresy HR/Cadence na CPU).

---

## 4. POTWIERDZENIE GUI SMOKE RENDER (120 klatek 4K)

Wykonano test uruchomienia renderera ze standardowego środowiska produkcyjnego GUI (bez żadnych ustawionych zmiennych środowiskowych):
- **Plik wyjściowy:** `scratch/etap1d_test/gui_smoke_render_120f.mp4`
- **Czas renderowania wideo:** `4.966 s` (**24.162 RENDER FPS**)
- **`map_cpu_upload`:** `0.079 ms`
- **`above_total`:** `21.963 ms`
- **Log runtime:**
  ```text
  [AMD NATIVE D3D11] AMD_AFTER_MAP_CHART_GPU: ON (default; native after-map chart GPU_SPLIT active)
  [AMD NATIVE D3D11] AMD_GPU_MAP_ROTATE: 1 (flag=True [default], track_up=True)
  ```

---

## 5. ZGODNOŚĆ Z INNYMI BACKENDAMI (`AGENTS.md`)

- **NVIDIA GPU Path:** `NVIDIA path preserved statically; runtime validation was not possible on this machine.`
- **Intel / CPU Reference:** Ścieżki Intel oraz CPU Reference nie uległy zmianie (`INTEL UNCHANGED: YES`).
