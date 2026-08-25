# TeleM — ETAP 10E4: BUGFIX wykresu aktywności z pauzami (HR/Cadence)

## Status i decyzja

**PAUSE TIMELINE CHART: FIXED**

---

## 1. Korekta założeń

Wykresy Heart Rate oraz Cadence w presecie `cycling_dashboard_v10` są **wykresami osi czasu całej aktywności** (timeline chart 0–100%), a nie 60-sekundowym oknem ruchomym.

- Zakres osi X odpowiada pełnemu czasowi trwania aktywności FIT (`09:40:10 .. 12:01:13 UTC`, 141.05 min).
- Cała seria danych (wszystkie segmenty aktywności) jest w całości widoczna na wykresie.
- Bieżący moment odtwarzania wideo / aktywności wskazywany jest przez ruchomy znacznik (kursor `ci`), przemieszczający się wzdłuż osi X.
- Pauzy w aktywności są reprezentowane jako fizyczne przerwy (gaps / nieciągłości) pomiędzy segmentami wykresu.

---

## 2. Analiza aktywności FIT i pauz

Dla pliku `Video/Jazda_na_rowerze_w_porze_lunchu.fit` (4299 punktów):
- Czas startu: `2026-08-14 09:40:10 UTC`
- Czas końca: `2026-08-14 12:01:13 UTC`
- Całkowity czas rozpiętości: **8463 s (~141 min)**

Wykryto dokładnie **2 pauzy (> 5 s)** i **3 segmenty aktywności**:
1. **Segment 1**: próbki `0 .. 1958` (1959 punktów) od `09:40:10` do `10:12:48` (czas: 1958 s = 32.63 min).
   - *Pauza 1*: `10:12:48` do `11:18:01` (trwanie: **3913 s = 65.22 min**).
2. **Segment 2**: próbki `1959 .. 2552` (594 punkty) od `11:18:01` do `11:27:54` (czas: 593 s = 9.88 min).
   - *Wideo `GX010115.MP4` nagrane w oknie `11:18:03 .. 11:23:03` (wewnątrz Segmentu 2).*
   - *Pauza 2*: `11:27:54` do `11:32:08` (trwanie: **254 s = 4.23 min**).
3. **Segment 3**: próbki `2553 .. 4298` (1746 punktów) od `11:32:08` do `12:01:13` (czas: 1745 s = 29.08 min).

---

## 3. Dokładna przyczyna błędu (Root Cause)

Zidentyfikowano dwie powiązane przyczyny w kodzie:

1. **Ucinanie przyszłych próbek przez `prefix_dynamic` w `src/indicators/chart.py`**:
   - Dla kluczy `fit_cadence_text` oraz `fit_heart_rate_text` flaga `prefix_dynamic` była ustawiana na `True` przy każdym przekazaniu `target_dt`, niezależnie od trybu `time_scope`.
   - W rezultacie `get_history_chart_prefix_background()` w `src/indicators/chart_utils.py` ucinał serię do `full_points[:visible_count]`, ukrywając wszystkie punkty w przyszłości względem bieżącego timestampu `target_dt`.
   - Przy wejściu / seeku do wideo (np. `00:07`, czyli początek Segmentu 2), Segment 3 był całkowicie niewidoczny (0 pikseli), a Segment 2 miał tylko 7 sekund danych i domalowywał się w miarę upływu odtwarzania.

2. **Pomijanie widgetu przy `value is None` w `src/indicators/compositor.py`**:
   - Gdy w danym momencie brakowało chwilowej wartości (np. kadencja na samym początku segmentu przed rozpoczęciem pedałowania lub w trakcie pauzy), `compose_overlay()` pomijał renderowanie całego widgetu chartu zamiast narysować tło osi czasu z wartością `"-- RPM"`.

---

## 4. Wprowadzony Fix (Minimal Change)

1. **`src/indicators/chart.py`**:
   - Ograniczono aktywację `prefix_dynamic` wyłącznie do trybu `time_scope == "window"`.
   - Dla trybów osi czasu (`"activity"`, `"video"`) wykres generuje i cache'uje pełne, statyczne tło ze wszystkimi 3 segmentami i przerwami za pomocą `get_history_chart_background()`, a dla każdej klatki renderuje jedynie ruchomy kursor pozycji `ci`.

2. **`src/indicators/compositor.py`**:
   - Dodano obsługę braku chwilowej wartości dla wykresów (`chart_missing`), dzięki czemu wykres nie znika podczas pauz/braku odczytu, lecz wyświetla `"--"` przy zachowaniu pełnej osi czasu.

3. **`presets/cycling_dashboard_v10.json`**:
   - Ustawiono `"chart_time_scope": "activity"` dla `fit_cadence_text` oraz `fit_heart_rate_text`.

---

## 5. Wyniki testów i weryfikacja

### A. Obecność wszystkich 3 segmentów na pojedynczej klatce
Wygenerowano klatki diagnostyczne:
- `Raporty/INDICATORS_ETAP_10E4_DIRECT_SEEK_0007.png` (wideo `00:07`)
- `Raporty/INDICATORS_ETAP_10E4_DIRECT_SEEK_0945.png` (wideo `09:45`)

Liczba pikseli w poszczególnych segmentach osi czasu:
- **Segment 1 (0..35% osi)**: `3968` pikseli (Cadence), `711` pikseli (HR) — **100% obecny na klatce 00:07**.
- **Segment 2 (35..70% osi)**: obecny na obu klatkach wraz ze znacznikiem pozycji.
- **Segment 3 (70..100% osi)**: `3881` pikseli (Cadence), `721` pikseli (HR) — **100% obecny na klatce 00:07**.

### B. Direct Seek vs Sequential Playback

| Timestamp | Direct Seek vs Sequential (Max Pixel Diff) | Wynik |
|---|---:|:---:|
| `t = 7.0 s` (00:07) | **0** (byte-exact) | **PASS** |
| `t = 30.0 s` | **0** (byte-exact) | **PASS** |
| `t = 60.0 s` | **0** (byte-exact) | **PASS** |
| `t = 147.0 s` | **0** (byte-exact) | **PASS** |
| `t = 240.0 s` | **0** (byte-exact) | **PASS** |
| `t = 300.0 s` | **0** (byte-exact) | **PASS** |
| `t = 585.0 s` (09:45) | **0** (byte-exact) | **PASS** |

### C. Determinizm sekwencji Arbitrary / Backward / Forward Seek
Sekwencja testowa: `[147s, 300s, 90s, 180s, 60s, 300s, 147s, 7s, 585s, 7s]`
- `diff(147s_1, 147s_2) = 0`
- `diff(300s_1, 300s_2) = 0`
- `diff(7s_1, 7s_2) = 0`

---

## 6. Wydajność (Performance Sanity)

Dzięki temu, że tło wykresu osi czasu aktywności jest w 100% statyczne i cache'owane w `_CHART_BG_CACHE`:
- **Heart Rate**: ~2.619 ms / frame (steady-state)
- **Cadence**: ~2.595 ms / frame (steady-state)
- Brak per-frame alokacji i rysowania polilinii/fillu.

---

## 7. Walidacja testów automatycznych

### Pytest (21/21 passed)
- `tests/test_chart_seek_history.py` (3 testy: 3 segmenty / 2 pauzy, direct vs sequential, random-access determinism)
- `tests/test_chart_axis_cache.py` (2 testy)
- `tests/test_static_indicator_cache.py` (6 testów)
- `tests/test_nvidia_regression_chart_preview.py` (3 testy)
- `tests/test_etap6_chart_window.py` (7 testów)

### Precomputed Telemetry (22/22 passed)
- `tests/test_etap8p_b_fast_builder.py` (12 testów)
- `tests/test_etap8o_precomputed_telemetry.py` (10 testów)

---

## 8. AMD Native D3D11 Smoke Test

Uruchomiono smoke eksportu AMD Native (`1280x720`, `60 klatek`, `full cycling_dashboard_v10`, `AMD_CHART_PATH = CPU_REFERENCE`):
- `Encoded frames: 60/60`
- `Muxed frames: 60/60`
- `Frame accounting: 100% exact`
- `Result: SUCCESS`

---

## 9. Architektura pod przyszłą opcję „Pomijanie Pauz” (Design Notes)

Dla przyszłej implementacji przełącznika **„Pomijanie Pauz” / Skip Pauses**:
1. **Model danych**:
   - W `build_chart_data()` lub osobnym transformerze: funkcja `collapse_activity_pauses(samples, max_gap_s=5.0)`.
   - Oblicza zsumowany czas aktywności netto $T_{\text{net}} = \sum \Delta t_i$ bez czasu pauz.
   - Każda próbka otrzymuje skompresowany timestamp $t'_{\text{net}}$.
2. **Odwzorowanie pozycji kursora**:
   - Kursor pozycji dla bieżącego $t$: jeśli $t$ przypada wewnątrz pauzy, zatrzymuje się na końcu poprzedniego segmentu; w czasie jazdy przelicza $t \to t'_{\text{net}}$.
3. **Renderer**:
   - Wykorzystuje istniejący `generate_history_chart()`, który na złączonych segmentach automatycznie narysuje ciągłą oś czasu netto (0..100% czasu jazdy).
4. **GUI**:
   - Opcja w `PropertyEditor` w zakładce `Chart` jako checkbox: `skip_pauses: bool` (domyślnie `false`).

---

## 10. Zmienione pliki

- [src/indicators/chart.py](file:///c:/_DEV/TeleM/src/indicators/chart.py) — ograniczenie `prefix_dynamic` do trybu `window`.
- [src/indicators/compositor.py](file:///c:/_DEV/TeleM/src/indicators/compositor.py) — zachowanie renderowania widgetu wykresu przy chwilowym braku wartości.
- [presets/cycling_dashboard_v10.json](file:///c:/_DEV/TeleM/presets/cycling_dashboard_v10.json) — ustawienie `chart_time_scope: "activity"`.
- [tests/test_chart_seek_history.py](file:///c:/_DEV/TeleM/tests/test_chart_seek_history.py) — testy regresyjne pauz, 3 segmentów i determinizmu.
