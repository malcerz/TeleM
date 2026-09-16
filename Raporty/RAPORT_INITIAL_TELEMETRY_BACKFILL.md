# RAPORT: Bounded Initial Telemetry Backfill (Kompensacja Opóźnienia Pierwszej Próbki)

Data wykonania: 2026-09-15  
Workspace: `H:\_Dev\BikeRideHUD`  
Status: **PASS (CASE A — FRAME0 FILLED + NO OUTSIDE-WINDOW REGRESSION + <1S)**

---

## 1. Cel i Kontekst Zadania

### 1.1. Problem
W rzeczywistych materiałach wideo (zarówno GPMF z kamer GoPro, np. GPS9 startujący z opóźnieniem $\sim 0.14463\text{ s}$, jak i w logach FIT, gdzie początek wideo wypada minimalnie przed pierwszą zarejestrowaną próbką, np. $t = -0.34463\text{ s}$ względem bazy):
- Na klatce 0 (oraz kilku początkowych klatkach) wartości części wskaźników (np. prędkość, temperatura) wynosiły `0.0` lub domyślny fallback.
- HUD pojawiał się nagle po upływie ułamka sekundy (kilka klatek później).

### 1.2. Rozwiązanie (Bounded Initial Backfill)
Wdrożono scentralizowany mechanizm **ograniczonego wstecznego wypełnienia początkowego (Bounded Initial Backfill)**:
- Jeśli żądany czas klatki jest wcześniejszy niż pierwsza poprawna próbka ($t < t_{\text{first}}$), a odstęp od początku projektu nie przekracza ściśle zdefiniowanego limitu:
  $$\text{gap} = t_{\text{first}} - t_{\text{start}} \le \text{INITIAL\_BACKFILL\_MAX\_S} = 0.50\text{ s}$$
- Klatki w oknie początkowym $[t_{\text{start}}, t_{\text{first}})$ przyjmują wartość pierwszej poprawnej próbki ($v_{\text{first}}$).
- W przypadku odstępów większych niż limit ($> 0.50\text{ s}$, np. kadencja rozpoczynająca się po $+4.0\text{ s}$, ślad GPS po $+47\text{ s}$ lub bateria po $+58\text{ s}$), wsteczne wypełnianie **nie jest stosowane**.
- Brak ekstrapolacji wstecznej z 2 punktu (prosty i stabilny `hold first sample backward to t=0`).
- Model globalny baterii Garmin pozostaje nienaruszony (działa od $t=0$).
- Globalna oś czasu projektu w trybie multi-file pozostaje kanoniczna (brak sztucznego resetu na granicach klipów 2 i 3).

---

## 2. Zmiany w Kodzie

### 2.1. Zmodyfikowane pliki
1. [src/telemetry_states_fast.py](file:///H:/_Dev/BikeRideHUD/src/telemetry_states_fast.py):
   - Wprowadzono stałą `INITIAL_BACKFILL_MAX_S: float = 0.5`.
   - Zaimplementowano wektorowe funkcje pomocnicze `_eval_continuous_channel` oraz `_eval_discrete_channel` z wbudowanym bounded initial backfill.
   - Usunięto destruktywne nadpisywania `arr_xxx[frame_rel_s < 0.0] = ...`, które zerowały prawidłowe próbki ujemnego offsetu.
2. [tests/test_telemetry_states_rate_aware.py](file:///H:/_Dev/BikeRideHUD/tests/test_telemetry_states_rate_aware.py):
   - Zaktualizowano asercje testowe: weryfikacja wypełnienia prędkości $5.508\text{ km/h}$ na klatkach $0..10$ oraz 100% parzystości poza oknem backfillu ($f \ge 11$).

### 2.2. Implementacja funkcji wektorowych
```python
INITIAL_BACKFILL_MAX_S: float = 0.5


def _eval_continuous_channel(
    frame_rel_s: np.ndarray,
    ts: np.ndarray,
    val: np.ndarray,
    default_val: float,
    max_backfill_s: float = INITIAL_BACKFILL_MAX_S,
) -> np.ndarray:
    if len(ts) == 0:
        return np.full(len(frame_rel_s), default_val, dtype=np.float64)
    first_ts = ts[0]
    first_val = val[0]
    start_s = frame_rel_s[0] if len(frame_rel_s) > 0 else 0.0
    gap = first_ts - start_s
    left_val = first_val if (0.0 < gap <= max_backfill_s) else default_val
    arr = np.interp(frame_rel_s, ts, val, left=left_val, right=val[-1])
    return arr


def _eval_discrete_channel(
    frame_rel_s: np.ndarray,
    ts: np.ndarray,
    val: np.ndarray,
    default_val: float,
    max_backfill_s: float = INITIAL_BACKFILL_MAX_S,
) -> np.ndarray:
    if len(ts) == 0:
        return np.full(len(frame_rel_s), default_val, dtype=np.float64)
    first_ts = ts[0]
    first_val = val[0]
    start_s = frame_rel_s[0] if len(frame_rel_s) > 0 else 0.0
    gap = first_ts - start_s
    idx = np.searchsorted(ts, frame_rel_s, side="right") - 1
    arr = np.full(len(frame_rel_s), default_val, dtype=np.float64)
    valid = idx >= 0
    arr[valid] = val[np.clip(idx[valid], 0, len(val) - 1)]
    if 0.0 < gap <= max_backfill_s:
        backfill_mask = (~valid) & (frame_rel_s >= start_s) & (frame_rel_s < first_ts)
        arr[backfill_mask] = first_val
    return arr
```

---

## 3. Wyniki Audytu Kanałów i Pierwszych Próbek

Zestawienie dla kanonicznego materiału `20260911.fit` + `[GX010290, GX010291, GX020291]` ($t_{\text{start}} = -0.344630\text{ s}$ na klatce 0):

| Kanał | Pierwszy znacznik czasu | Offset rel. $t_{\text{base}}$ | Pierwsza wartość | Odstęp od startu | Decyzja Backfill | Ostatnia klatka backfill | Pierwsza naturalna klatka |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **speed** | 2026-09-11 13:04:57 | $+0.000000\text{ s}$ | $5.508\text{ km/h}$ | $+0.344630\text{ s}$ | **TAK ($\le 0.5\text{ s}$)** | **f10** | **f11** |
| **heart_rate** | 2026-09-11 13:04:54 | $-3.000000\text{ s}$ | $82\text{ bpm}$ | $-2.655370\text{ s}$ | **NATURALNA ($\le 0$)** | Brak | **f0** |
| **cadence** | 2026-09-11 13:05:01 | $+4.000000\text{ s}$ | $34\text{ rpm}$ | $+4.344630\text{ s}$ | **NIE ($> 0.5\text{ s}$)** | Brak | **f131** |
| **curVpower** | 2026-09-11 13:04:54 | $-3.000000\text{ s}$ | $0\text{ W}$ | $-2.655370\text{ s}$ | **NATURALNA ($\le 0$)** | Brak | **f0** |
| **distance** | 2026-09-11 13:04:54 | $-3.000000\text{ s}$ | $0.000\text{ m}$ | $-2.655370\text{ s}$ | **NATURALNA ($\le 0$)** | Brak | **f0** |
| **temperature** | 2026-09-11 13:04:54 | $-3.000000\text{ s}$ | $25.0^\circ\text{C}$ | $-2.655370\text{ s}$ | **NATURALNA ($\le 0$)** | Brak | **f0** |
| **garmin_battery**| 2026-09-11 13:05:55 | $+58.000000\text{ s}$| $69.00\%$ | $+58.344630\text{ s}$ | **MODEL GLOBALNY** | Brak | **f0 (od $t=0$)** |
| **GPS Track** | 2026-09-11 13:05:44 | $+47.000000\text{ s}$| $54.3655, 18.6243$| $+47.344630\text{ s}$ | **HOLD FIRST POS** | Brak | **f0 (hold)** |

---

## 4. Porównanie Klatki 0: Przed vs Po Wdrożeniu

| Pole | Przed (Raw) | Przed (String) | Po (Raw) | Po (String) | Status |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Speed** | $0.000$ | `0.0` | **$5.508$** | **`5.5`** | **BACKFILLED** (Wypełniono pierwszą próbką z $t=0$) |
| **Heart Rate** | $82.000$ | `82` | **$82.000$** | **`82`** | IDENTICAL (Próbka istniała od $t=-3\text{ s}$) |
| **Cadence** | $0.000$ | `0` | **$0.000$** | **`0`** | IDENTICAL (Próbka dopiero od $+4.0\text{ s}$, gap $>0.5\text{ s}$) |
| **Power** | $0.000$ | `0` | **$0.000$** | **`0`** | IDENTICAL (Próbka $0\text{ W}$) |
| **Distance** | $0.000$ | `0.00` | **$0.001$** | **`0.00`** | NATURAL (Interpolacja między $-1\text{ s}$ a $0\text{ s}$) |
| **Temperature** | $24.000$ | `24.0°C` | **$25.000$** | **`25.0°C`** | NATURAL (Poprawna próbka FIT zamiast hardcoded 24.0) |
| **Garmin Battery**| $69.000$| `69.00` | **$69.000$** | **`69.00`** | IDENTICAL (Globalny model ciągły) |

### 4.1. Próbkowanie klatek 0..15 (Prędkość):
- Klatki 0..10 ($t = 0.0000\text{ s} .. 0.3337\text{ s}$, $\text{rel\_s} < 0.0\text{ s}$): `speed = 5.508 km/h` (`5.5`) [BACKFILLED]
- Klatka 11 ($t = 0.3670\text{ s}$, $\text{rel\_s} = +0.0224\text{ s}$): `speed = 5.533 km/h` (`5.5`) [NATURALNA INTERPOLACJA]
- Klatka 12 ($t = 0.4004\text{ s}$, $\text{rel\_s} = +0.0558\text{ s}$): `speed = 5.570 km/h` (`5.6`) [NATURALNA INTERPOLACJA]

---

## 5. Walidacja Parzystości Poza Oknem Backfillu (Klatki 11..63390)

Przeprowadzono pełne porównanie parzystości na wszystkich $63\,380$ klatkach poza oknem początkowym ($f \ge 11$):
- **14 pól numerycznych float32/float64:**
  - `speed_kmh`, `heart_rate_bpm`, `cadence_rpm`, `power_w`, `distance_km`, `altitude_m`, `solar_pct`, `garmin_battery_pct`, `gopro_battery_pct`, `temperature_c`, `iso`, `exposure_denom`, `map_latitude`, `map_longitude`
  - **Maksymalna różnica:** `0.00000000e+00`
  - **Liczba błędów ($> 10^{-6}$):** `0` $\to$ **100% PASS**
- **15 pól tekstowych (String Equality):**
  - `speed_str`, `hr_str`, `cad_str`, `power_str`, `distance_str`, `altitude_str`, `solar_str`, `garmin_battery_str`, `gopro_battery_str`, `temp_str`, `iso_str`, `exposure_str`, `time_display_date`, `time_display_time`, `time_display_elapsed`
  - **Liczba niezgodności:** `0` $\to$ **100% PASS**

---

## 6. Ciągłość Granic Klipów w Multi-File (Clip Boundaries)

Sprawdzono przejścia pomiędzy klipami w projekcie multi-file:
- **Przejście Clip 1 $\to$ Clip 2 (klatka 4595 $\to$ 4596, $t = 153.3532\text{ s}$):**
  - Bateria Garmin: $68.8990\% \to 68.8990\%$ (płynna kontynuacja, delta $-0.000022\%$).
  - Telemetria projektu jest ciągła i nie resetuje się na początku pliku MP4.
- **Przejście Clip 2 $\to$ Clip 3 (klatka 54515 $\to$ 54516, $t = 1819.0172\text{ s}$):**
  - Bateria Garmin: $67.8021\% \to 67.8021\%$ (płynna kontynuacja).
  - Prędkość i tętno: pełna ciągłość osi projektu.

---

## 7. Testy Wydajnościowe (Performance Benchmark)

Wykonano 3-krotny benchmark prekomputacji dla wszystkich $63\,391$ klatek:
- **Przebieg 1:** `0.4259 s` ($148\,832\text{ fps}$)
- **Przebieg 2:** `0.4186 s` ($151\,430\text{ fps}$)
- **Przebieg 3:** `0.4178 s` ($151\,719\text{ fps}$)
- **Mediana:** **`0.4186 s`** ($151\,430\text{ fps}$)

Wymóg krytyczny: $< 1.0\text{ s}$ $\to$ **PASS** (ponad $2.3\times$ szybciej niż limit).  
Wymóg preferowany: $< 0.6\text{ s}$ $\to$ **PASS**.

---

## 8. Izolacja Backendów i Bezpieczeństwo

- **AMD / Intel / NVENC / Direct2D:** Brak zmian w kodzie natywnym C++ rendererów ani enkoderów.
- **Zasady całkowite (Integer Policy):** HR, Cadence, Power, ISO, Exposure zachowują ściśle prezentację bez miejsc po przecinku (`0 decimals`).
- **Bateria Garmin:** Formatowanie 2 miejsc po przecinku (`.2f`) zachowane.
- **Audio / Preview / Geometria:** Nienaruszone.

---

## 9. Podsumowanie i Spis Artefaktów

Klasyfikacja: **`CASE A — FRAME0 FILLED + NO OUTSIDE-WINDOW REGRESSION + <1S`**

Artefakty w katalogu `scratch/initial_backfill_fix/`:
- `first_samples_audit.txt` (MD5: `3c949b4833c77a6f6301bb479c39e549`)
- `frame0_before_after.txt` (MD5: `169c60175c7818eb4d1509f05eb0779e`)
- `clip_boundaries.txt` (MD5: `a03167ae535c4d485b0f82a3ef040642`)
- `parity_outside_window.txt` (MD5: `20974617d604a0caab91b135d299424b`)
- `benchmark.txt` (MD5: `a11e22771251b3331583cab7fb133261`)
- `test.log` (MD5: `387cae9dfa77afcf7e3d2e5d0932d725`)
- `ntfy_result.txt` (MD5: `135dbac3e8678a6fa44136e080ab0812`, Exit Code: 0, Attempt 1/3)
- `artifacts_manifest.txt`

Powiadomienie NTFY zostało pomyślnie wysłane z kodem wyjścia 0.
