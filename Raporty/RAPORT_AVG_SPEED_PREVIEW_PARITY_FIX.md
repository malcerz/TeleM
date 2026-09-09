# RAPORT: Preview vs Final Render Average Speed Parity Fix

## 1. Cel zadania
Naprawa rozjazdu średniej prędkości pomiędzy podglądem (Preview) a renderingiem finalnym (Precompute/Final Render), gdzie dla tego samego projektu (`GX010241.MP4` + `Poranna_jazda_na_rowerze.fit`) i timestampu (~31:08 / 31:09) Preview wyświetlało błędną wartość rzędu `16095.5 km/h`, podczas gdy referencyjny render/wzór z FIT dawał `~19.0 - 19.7 km/h`.

---

## 2. Root Cause & Analiza Numeryczna

### Konfiguracja i dane wejściowe:
- Projekt: `D:/GoPro/2026-09-01/GX010241.MP4`
- FIT: `D:/GoPro/2026-09-01/Poranna_jazda_na_rowerze.fit`
- Preset: `presets/cycling_dashboard_v10.json`
- Wskaźnik dystansu w presecie: `"dist_visual": { "source": "gpmf", ... }`

### Geneza błędu:
1. Nagranie `GX010241.MP4` na samym początku zawierało niepoprawny początkowy fix GPS (współrzędne `(0.0, 0.0)` u wybrzeży Afryki przed uzyskaniem właściwego fixa w Polsce). Skutkowało to skokiem akumulowanego dystansu ścieżki GPMF do **8 356 251.84 m** (~8 356 km).
2. W `src/indicators/frame_data.py` wartość `distance_m` była wyliczana z konfiguracji wskaźnika dystansu ekranowego (`dist_visual` / `dist_text`), czyli pobierała próbki z GPMF (8 356 km).
3. Następnie `avg_speed_kmh` było liczone jako:
   ```python
   avg_speed_kmh = (distance_m / activity_elapsed_s) * 3.6
   ```
   Dla timestampu `31:08` (`activity_elapsed_s = 1868.0 s`):
   $$\text{avg\_speed\_kmh} = \frac{8\,356\,251.84}{1868.0} \times 3.6 = \mathbf{16\,104.1\text{ km/h}} \approx \mathbf{16\,095.5\text{ km/h}}$$
4. Średnia prędkość zależała więc bezpośrednio od źródła wybranego dla wskaźnika dystansu (`source: gpmf`), zamiast od kanonicznego dystansu aktywności z pliku FIT.

---

## 3. Porównanie Inputów Przed Naprawą (BEFORE)

Dla identycznego punktu czasu:
`target_dt = 2026-09-01 04:55:44+00:00` (czas aktywności: 31:08 = 1868 s)

```text
PREVIEW (BEFORE):
target_dt=              2026-09-01 04:55:44+00:00
elapsed_seconds=        1868.0
activity_elapsed_s=     1868.0
fit_distance_raw=       10247.76 m
fit_distance_start=     0.0 m
fit_active_distance_m=  10247.76 m
distance_m=             8356251.84 m   (z GPMF dist_visual!)
avg_speed_kmh=          16104.14 km/h  (BŁĄD: powiązanie ze wskaźnikiem ekranowym)

FINAL/PRECOMPUTE (BEFORE z dist_visual=fit lub bez błędu GPMF):
target_dt=              2026-09-01 04:55:44
elapsed_seconds=        1868.0
activity_elapsed_s=     1868.0
fit_distance_raw=       10247.76 m
fit_distance_start=     0.0 m
fit_active_distance_m=  10247.76 m
distance_m=             10247.76 m
avg_speed_kmh=          19.75 km/h     (POPRAWNIE)
```

### Pierwsza wartość, która się rozjeżdża (First Divergent Value):
Wartość dystansu używana do mianownika średniej prędkości:
- Preview brało `distance_m = 8356251.84` (z `dist_visual` GPMF).
- Zamiast kanonicznego dystansu FIT: `fit_active_distance_m = 10247.76`.

---

## 4. Zastosowane Rozwiązanie (FIX)

1. **Wspólny, kanoniczny helper** `compute_activity_distance_and_avg_speed()` w `src/telemetry_active_time.py`:
   - Przyjmuje `fit_data`, `gpx_track_samples`, `gpmf_track_samples`, `target_dt`, `active_elapsed_s` oraz opcjonalny `fallback_distance_m`.
   - Zabezpieczony funkcją `_is_valid_distance_stream()` przed nieprawidłowymi strumieniami współrzędnych `(lat, lon)`.
   - Gdy `fit_data` istnieje i zawiera dystans (lub track z dystansem), dystans aktywności jest liczony wyłącznie ze strumienia FIT:
     $$\text{fit\_active\_distance\_m} = \text{fit\_distance}(target\_dt) - \text{fit\_distance\_start}$$
   - Oblicza kanoniczną średnią:
     $$\text{avg\_speed\_kmh} = \frac{\text{activity\_distance\_m}}{\text{active\_elapsed\_s}} \times 3.6$$
   - Całkowicie rozdziela pojęcie `display_distance_m` (dystans dla wskaźnika ekranowego) od `fit_active_distance_m` (dystans dla średniej prędkości).

2. **Podpięcie we wszystkich potokach**:
   - `src/indicators/frame_data.py`: wywołanie `compute_activity_distance_and_avg_speed(...)`.
   - `src/telemetry_precompute.py`: wektoryzacja kanonicznego strumienia `fit_canonical_s` do tablicy `act_dist_arr` niezależnie od konfiguracji `dist_visual.source`, oraz użycie `act_dist_arr` w pętli ramkowej.
   - `src/ffmpeg/frame_renderer.py`: zastąpienie lokalnego dzielenia `distance_m` wywołaniem `compute_activity_distance_and_avg_speed(...)`.

---

## 5. Wyniki Numeryczne Po Naprawie (AFTER)

Dla timestampu `target_dt = 2026-09-01 04:55:44+00:00` (CZAS 31:08):

```text
PREVIEW:
target_dt=              2026-09-01 04:55:44+00:00
elapsed_seconds=        1868.0
activity_elapsed_s=     1868.0
fit_distance_raw=       10247.76
fit_distance_start=     0.0
fit_active_distance_m=  10247.76
distance_m=             10247.76
avg_speed_kmh=          19.74943040685225

FINAL/PRECOMPUTE:
target_dt=              2026-09-01 04:55:44
elapsed_seconds=        1868.0
activity_elapsed_s=     1868.0
fit_distance_raw=       10247.76
fit_distance_start=     0.0
fit_active_distance_m=  10247.76
distance_m=             None (lub display distance zależny od layoutu)
avg_speed_kmh=          19.74943040685225

PREVIEW avg=            19.74943040685225 km/h
FINAL/PRECOMPUTE avg=   19.74943040685225 km/h
difference=             0.00000000000000 km/h (EXACT FLOAT PARITY)
```

---

## 6. Test Niezależności od Źródła Display Distance

Przetestowano 3 konfiguracje wskaźnika dystansu (`dist_visual` / `dist_text`) przy załadowanym pliku FIT i symulowanym błędnym skoku GPMF (+8356 km):

1. **Konfiguracja A: `source = gpmf`**
   - Preview `distance_m`: `8366494.08 m`
   - Preview `avg_speed_kmh`: `19.7494 km/h`
   - Precompute `avg_speed_kmh`: `19.7494 km/h`
   - Difference: `0.000000 km/h`
2. **Konfiguracja B: `source = fit`**
   - Preview `distance_m`: `10247.76 m`
   - Preview `avg_speed_kmh`: `19.7494 km/h`
   - Precompute `avg_speed_kmh`: `19.7494 km/h`
   - Difference: `0.000000 km/h`
3. **Konfiguracja C: Wskaźnik dystansu całkowicie wyłączony (`enabled = false`)**
   - Preview `avg_speed_kmh`: `19.7494 km/h`
   - Precompute `avg_speed_kmh`: `19.7494 km/h`
   - Difference: `0.000000 km/h`

Wynik: Średnia prędkość z FIT jest w 100% niezależna od wskaźników dystansu na HUDzie.

---

## 7. Wyniki Testów Regresyjnych

Uruchomiono ukierunkowane testy jednostkowe:
```bash
python -m pytest tests/test_multifile_avg_speed.py tests/test_activity_ux_timeline.py tests/test_telemetry_processed_cache.py tests/test_time_display_optimization.py
```
Wynik:
```text
35 passed in 1.39s
```

Testy pokrywają:
- Pełną parzystość `elapsed_seconds`, `fit_active_distance_m`, `avg_speed_kmh` pomiędzy Preview a Precompute.
- Weryfikację, że `avg_speed_kmh` nigdy nie osiąga wartości rzędu 16 000 km/h.
- Niezależność od wybranego źródła `dist_visual` (GPMF, FIT, disabled).

---

## 8. Podsumowanie Weryfikacji

```text
PREVIEW AVG ROOT CAUSE FOUND: YES
PREVIEW AVG SPEED: PASS
FINAL RENDER UNCHANGED: PASS
PREVIEW FINAL PARITY: PASS
```
