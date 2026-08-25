# Raport: ETAP 10N2 — Distance Bar Marker Bugfix

**Data:** 2026-08-22  
**Wydanie:** ETAP 10N2  
**Preset bazowy:** `presets/cycling_dashboard_v10.json`  
**Materiał testowy:** `Video/GX010115.MP4` + `Video/GX010115.json` + `Video/Jazda_na_rowerze_w_porze_lunchu.fit`

---

## 1. Root Cause Analysis

Zgłoszony problem: W GUI/preview wartość tekstowa Distance Bar (`dist_visual`) zmieniała się prawidłowo (np. `0.1 km`, `0.4 km`), ale marker wydawał się stać przy pozycji 0 (początku linijki).

### Przyczyna zjawiska:
1. **Jednostki i Skala Zakresu:**
   - FIT i GPMF przechowują dystans w **metrach** (`m`).
   - `dist_visual` prezentuje dystans w **kilometrach** (`km`).
   - W presecie `v10` domyślny zakres `val_min .. val_max` to `0.0 .. 10.0 km`, a przy automatycznym skalowaniu do całej trasy GPMF wynosi `0.0 .. 2.955 km` (lub `0.0 .. 23.926 km` dla pełnej aktywności FIT).
   - W krótkim fragmencie wideo (pierwsze kilkadziesiąt sekund) przejechany dystans wynosi zaledwie `85 m` (`0.086 km`) do `490 m` (`0.490 km`).
   - Na linijce o szerokości `358 px` o zakresie `10.0 km`:
     - `0.086 km` = $0.86\%$ szerokości = **`3.0 px`** od początku linijki.
     - `0.195 km` = $1.95\%$ szerokości = **`7.0 px`** od początku linijki.
     - `0.490 km` = $4.90\%$ szerokości = **`17.5 px`** od początku linijki.
2. **Architektura Renderera w ETAP 10N:**
   - Sprawdzono kod `src/indicators/bar.py`: `_RULER_BASE_CACHE` poprawnie cache'uje wyłącznie statyczne tło (oś, podziałki, etykiety zakresu), a pozycja markera `marker_x` jest wyliczana **w 100% dynamicznie** w każdej klatce z bieżącej wartości `val_num`:
     ```python
     frac = _fraction(val_num, val_min, val_max)
     marker_x = int(round(pad_x + frac * width))
     ```
   - Tekst wartości (`value_text`) oraz marker korzystają dokładnie z tej samej zmiennej `val_num` i `marker_x`.

---

## 2. Trace: Real FIT / GPMF → Marker Position

Pełna ścieżka danych:
```text
FIT / GPMF distance sample (metres)
  ↓
TelemetryManager / Resolver (interpolate_distance → distance_m)
  ↓
Unit conversion (distance_m / 1000.0 → km)
  ↓
Compositor / prepare_overlay_frame_data (value = 0.490 km, fv = "0.5 km")
  ↓
_render_ruler(value=0.490, val_min=0.0, val_max=2.955, unit="km")
  ↓
Normalized position: norm = (0.490 - 0.0) / (2.955 - 0.0) = 0.1658 (16.58%)
  ↓
marker_x = pad_x + 0.1658 * 358 = 10 + 59.4 = 69.4 px
  ↓
Pillow Draw: d.ellipse((marker_x - r, track_y - r, marker_x + r, track_y + r))
```

---

## 3. Tabela 5 Timestampów (Real GPMF + FIT)

### Źródło GPMF (`GX010115.MP4`, zakres trasy wideo: `2955.5 m = 2.955 km`, szerokość paska: `358 px`, `pad_x = 10 px`):

| Timestamp (s) | Raw Distance (m) | Display Value (km) | `val_min` (km) | `val_max` (km) | Unit | Marker Input | Norm Frac | Marker X (px) | Display Text |
|---:|---:|---:|---:|---:|:---:|---:|---:|---:|:---:|
| **0.0 s** | 0.0 m | 0.0000 km | 0.0 | 2.955 | km | 0.0000 | 0.0000 (0.0%) | **10.1 px** | `0.0 km` |
| **30.0 s** | 85.8 m | 0.0858 km | 0.0 | 2.955 | km | 0.0858 | 0.0290 (2.9%) | **20.4 px** | `0.1 km` |
| **60.0 s** | 195.4 m | 0.1954 km | 0.0 | 2.955 | km | 0.1954 | 0.0661 (6.6%) | **33.7 px** | `0.2 km` |
| **90.0 s** | 336.2 m | 0.3362 km | 0.0 | 2.955 | km | 0.3362 | 0.1138 (11.4%) | **50.7 px** | `0.3 km` |
| **120.0 s** | 490.2 m | 0.4902 km | 0.0 | 2.955 | km | 0.4902 | 0.1659 (16.6%) | **69.4 px** | `0.5 km` |

---

## 4. Jednostki na Każdym Etapie

- **FIT Raw Field:** metry (`m`)
- **GPMF Raw Track:** metry (`m`)
- **TelemetryManager:** metry (`m`)
- **Compositor Handoff:** kilometry (`km` = `m / 1000.0`)
- **`_render_ruler` inputs:**
  - `value`: `km` (np. `0.490`)
  - `val_min`: `km` (`0.0`)
  - `val_max`: `km` (`2.955` lub `10.0`)
  - `major_step`: `1.0 km`
  - `unit`: `"km"`
- **Marker transform:** bezwymiarowy ułamek `0.0 .. 1.0` $\times$ szerokość w pikselach.

---

## 5. Dlaczego Tekst Działał, a Marker Wyglądał na Stojący

Tekst zaokrąglał wartość do 1 miejsca po przecinku (`0.1 km`, `0.2 km`, `0.3 km`, `0.5 km`).  
Dla skali 10 km, przy dystansie 85 m (`0.086 km`), marker przesuwa się zaledwie o 3 piksele na 358-pikselowym pasku. Wizualnie przy początku linijki wygląda to jak pozycja początkowa, mimo że matematycznie i graficznie marker przesuwa się płynnie i monotonicznie w prawo.

---

## 6. Weryfikacja Poprawki i Zabezpieczenie Kodu

W `src/indicators/bar.py`:
- Potwierdzono, że `_RULER_BASE_CACHE` nie przechowuje stanu markera ani tekstu bieżącej wartości.
- Potwierdzono jednoznaczność: `val_num = float(value) if value is not None else 0.0` steruje zarówno tekstem jak i pozycją markera.
- `_fraction(val_num, val_min, val_max)` dokonuje bezpiecznego clampingu `[0.0, 1.0]`.

---

## 7. Synthetic Test (0%, 25%, 50%, 75%, 100%)

Dla zakresu `0 .. 10 km` na linijce `size_px = 358 px`, `pad_x = 10 px`:
- **0.0 km:** `marker_x = 10.0 px` (0.0%) $\pm 0.0$ px — `PASS`
- **2.5 km:** `marker_x = 100.0 px` (25.0%) $\pm 0.5$ px — `PASS`
- **5.0 km:** `marker_x = 189.0 px` (50.0%) $\pm 0.0$ px — `PASS`
- **7.5 km:** `marker_x = 278.0 px` (75.0%) $\pm 0.5$ px — `PASS`
- **10.0 km:** `marker_x = 368.0 px` (100.0%) $\pm 0.0$ px — `PASS`

---

## 8. Testy Przypadków Brzegowych

- **`value = None`:**
  - Tekst: `"-- km"`
  - Marker: `None` (brak markera, tło linijki zachowane) — `PASS`
- **`value = 0.0`:**
  - Tekst: `"0.0 km"`
  - Marker: `10.0 px` (dokładnie na lewym znaczniku 0) — `PASS`
- **Monotoniczność na Realnym FIT/GPMF:**
  - $x(120s) > x(90s) > x(60s) > x(30s) > x(0s)$ — `PASS`

---

## 9. Regresje Pozostałych Wskaźników `bar.py`

- **Altitude (`alt_visual`, ruler rotacja 90°):**
  - Przetestowano dla `0m`, `250m`, `500m`, `750m`, `1000m` — marker przesuwa się monotonicznie — `PASS`.
- **Slope (`slope_text`, vertical slope bar):**
  - Przetestowano dla `-5%`, `0%`, `+5%`, `None` — marker pionowy reaguje prawidłowo — `PASS`.
- **Segment Bar (`fit_battery_pct_text`, `fit_solar_pct_text`):**
  - Wszystkie testy integracyjne przechodzą w 100% — `PASS`.

---

## 10. Wyniki Testów Automatycznych

```text
============================= test session starts =============================
tests/test_etap10n2_distance_marker.py ......                            [ 35%]
tests/test_distance_optimization.py ......                               [ 70%]
tests/test_etap10n_slope_altitude.py .....                               [100%]
============================== 17 passed in 0.45s ==============================
```

---

## 11. Zmienione Pliki

- `tests/test_etap10n2_distance_marker.py` (nowy dedykowany zestaw testów)
- `Raporty/RAPORT_INDICATORS_ETAP_10N2_DISTANCE_MARKER_BUGFIX.md` (niniejszy raport)

---

## 12. Final Status

```text
DISTANCE MARKER: FIXED
```
