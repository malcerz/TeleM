# RAPORT: MULTI-FILE AVERAGE SPEED FIX (ŚREDNIA PRĘDKOŚĆ)

**Data:** 2026-08-31  
**Repozytorium:** `C:\_DEV\TeleM-integration`  
**Gałąź:** `integration/intel-amd`  
**Zadanie:** Naprawa semantyki wskaźnika `Średnia prędkość` w projektach multi-file (usunięcie mieszania osi skumulowanego dystansu aktywności z lokalnym czasem klipu wideo).

---

## 1. Problem i Root Cause

### Zaobserwowany błąd w GUI (GX010115 ~26s):
* **Skumulowany dystans z FIT:** $\approx 12.13 \text{ km}$ ($12134.47 \text{ m}$)
* **Lokalny czas trwania drugiego klipu:** $\approx 00:26$ ($26.0 \text{ s}$)
* **Wyświetlana średnia prędkość (BŁĄD):** $\mathbf{1680.2 \text{ km/h}}$ ($\approx 1668.4 \text{ km/h}$)

### Matematyczny dowód błędu:
$$\text{avg\_speed} = \frac{12134.47 \text{ m}}{26.0 \text{ s}} \times 3.6 = 1680.15 \text{ km/h}$$

### Dokładna przyczyna (Root Cause):
1. **Numerator (licznik):** Wskaźnik korzystał ze skumulowanego dystansu aktywności z pliku FIT (`12.13 km` przebyte od początku całej trasy).
2. **Denominator (mianownik):** W module `src/indicators/frame_data.py` oraz `src/telemetry_precompute.py`, mianownik czasu (`elapsed_seconds`) był wyliczany jako `(target_dt - start_dt_utc)` lub `project_elapsed_s`.
3. Podczas podglądu lub renderowania drugiego klipu (GX010115), `start_dt_utc` reprezentował początek danego pliku wideo (`11:18:02`), podczas gdy aktywność FIT rozpoczęła się o `09:40:10`.
4. Różnica czasu wynosiła zaledwie $26 \text{ s}$, podczas gdy rzeczywisty czas aktywności od startu wynosił $\mathbf{5898.3 \text{ s}}$ ($98 \text{ min } 18 \text{ s}$).
5. Podzielenie dystansu całej 98-minutowej trasy przez 26 sekund spowodowało eksplozję wyniku do ponad $1600 \text{ km/h}$.

---

## 2. Docelowa Semantyka i Wdrożona Poprawka

### Licznik i Mianownik:

| Element | Przed poprawką | Po poprawce |
| :--- | :--- | :--- |
| **Numerator (Dystans)** | Cumulative FIT distance ($12.13 \text{ km}$) | Cumulative FIT distance ($12.13 \text{ km}$) |
| **Denominator (Czas)** | Clip-local time / start klipu wideo ($26.0 \text{ s}$) | Activity-global elapsed time ($5898.3 \text{ s}$) |
| **Średnia prędkość** | **$1680.2 \text{ km/h}$ (BŁĄD)** | **$7.4 \text{ km/h}$ (POPRAWNA REALNA WARTOŚĆ)** |

### Algorytm wyliczania `activity_elapsed_s`:
W `src/indicators/frame_data.py` oraz `src/telemetry_precompute.py`:
1. Pobierany jest kanoniczny znacznik czasu startu aktywności (`activity_start_dt`) z pierwszego punktu strumienia FIT / GPX (`fit_pts[0][0]` lub `gpx_track_samples[0][0]`), z fallbackiem do `start_dt_utc`.
2. Dla aktualnego znacznika czasu ramki `target_dt`, mianownik wyliczany jest jako:
   $$\text{activity\_elapsed\_s} = (\text{target\_dt} - \text{activity\_start\_dt}).\text{total\_seconds}()$$
3. Średnia prędkość to:
   $$\text{avg\_speed\_kmh} = \frac{\text{distance\_m}}{\text{activity\_elapsed\_s}} \times 3.6$$
4. Wskaźnik `Czas` (`show_elapsed`) w `time_display` nadal zachowuje swoją niezależną semantykę (czas trwania materiału/klipu, np. `00:26`), nie wpływając negatywnie na średnią prędkość.

---

## 3. Wyniki Weryfikacji

### A. Punkt ze screena użytkownika (GX010115 local = 26s):
* **Absolute timestamp:** `2026-08-14 11:18:28.250`
* **Cumulative distance:** `12134.47 m` ($12.13 \text{ km}$)
* **Activity elapsed time:** `5898.3 s` ($98 \text{ min } 18 \text{ s}$)
* **Clip local time:** `26.0 s` (wyświetlane w polu `Czas`: `00:26`)
* **Średnia prędkość PRZED:** `1680.2 km/h`
* **Średnia prędkość PO:** **`7.4 km/h`** (zgodna z profilem trasy i przerwą rowerzysty)

### B. Ciągłość na granicach klipów (014 → 015 → 016):

| Punkt | Klip | Czas lokalny | Absolute Time | Dystans | Czas aktywności | Średnia prędkość |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| **014 Start** | 0 | 0.0 s | 09:40:11 | 0.00 km | 00:01 | **0.0 km/h** |
| **014 End** | 0 | 1956.1 s | 10:12:47 | 12.08 km | 32:37 | **22.2 km/h** |
| *(Przerwa 65 min)* | — | — | 10:12 → 11:18 | — | — | *(postój rowerzysty)* |
| **015 Start** | 1 | 0.5 s | 11:18:02 | 12.08 km | 97:52 | **7.4 km/h** |
| **015 (~26s)** | 1 | 26.0 s | 11:18:28 | 12.13 km | 98:18 | **7.4 km/h** |
| **015 End** | 1 | 592.1 s | 11:27:54 | 15.02 km | 107:44 | **8.4 km/h** |
| **016 Start** | 2 | 0.5 s | 11:32:10 | 15.02 km | 112:00 | **8.0 km/h** |
| **016 End** | 2 | 1743.1 s | 12:01:12 | 24.23 km | 141:02 | **10.3 km/h** |

*Brak jakichkolwiek skoków rzędu 1600 km/h przy przejściu pomiędzy plikami GoPro.*

### C. Test regresji Single-File (GX020079):
* **Start (0.0s):** `dist = 0.001 km`, `avg_speed = 0.8 km/h`
* **End (18.85s):** `dist = 0.048 km`, `avg_speed = 6.9 km/h`
* Wartości w 100% zgodne z fizycznym modelem pojedynczego pliku.

### D. Spójność Preview ↔ Precomputed Export (Parytet):
* `prepare_overlay_frame_data` oraz `build_telemetry_cache` (używane przez eksportery AMD/Intel) korzystają z identycznej definicji `activity_elapsed_s` względem `activity_start_dt`.
* Testy jednostkowe `tests/test_multifile_avg_speed.py` oraz `scratch/test_avg_speed_fix.py`: **100% PASS**.

---

## 4. Zmienione Pliki i `git diff --stat`

### Zmodyfikowane pliki:
1. `src/indicators/frame_data.py`:
   * Dodano obliczanie `activity_elapsed_s` oparte na znaczniku początku aktywności FIT/GPX.
   * Zabezpieczono fallback dla `distance_m` z `fit_data["distance"]` i `resolve_cache_value`.
   * Zachowano pole `elapsed_seconds` dla wskaźnika czasu materiału wideo.
2. `src/telemetry_precompute.py`:
   * Zsynchronizowano obliczanie `avg_spd` w pętli montażu rekordów klatek z `activity_start_dt`.
3. `tests/test_multifile_avg_speed.py`:
   * Dodano dedykowany zestaw testów automatycznych dla ciągłości średniej prędkości multi-file.

### `git diff --stat`:
```text
 src/indicators/frame_data.py      |  54 +++++++++++++++++++
 src/telemetry_precompute.py       | 122 +++++++++++++++++++++++++++++++++++--------
 tests/test_multifile_avg_speed.py |  88 +++++++++++++++++++++++++++++++
 3 files changed, 243 insertions(+), 21 deletions(-)
```

---

## 5. Podsumowanie (PASS/FAIL)

* **Root Cause Udowodniony:** TAK ($12.13 \text{ km} / 26 \text{ s} \times 3.6 \approx 1680.2 \text{ km/h}$)
* **Poprawka Mianownika Activity Elapsed:** TAK ($12.13 \text{ km} / 5898.3 \text{ s} \times 3.6 = 7.4 \text{ km/h}$)
* **Ciągłość na Przejściach 014→015→016:** TAK (brak resetu mianownika i brak anomalii)
* **Pojedynczy Plik (Single-File):** TAK (brak regresji)
* **Parytet Preview ↔ Export:** TAK
* **Zgodność z AGENTS.md / Izolacja:** TAK (brak commitu, brak pushu)
* **Status Końcowy:** **PASS**
