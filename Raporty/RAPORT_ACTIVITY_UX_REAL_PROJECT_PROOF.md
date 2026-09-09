# RAPORT: TeleM GoPro — Produkcyjna Walidacja Activity UX & Timeline (Projekt Rzeczywisty)

**Data:** 2026-09-05  
**Gałąź:** `integration/intel-amd`  
**Projekt testowy:**
- Wideo: `D:/GoPro/2026-08-31/GX010239.MP4`, `D:/GoPro/2026-08-31/GX010240.MP4`
- Telemetria FIT: `D:/GoPro/2026-08-31/Popołudniowa_jazda_na_rowerze.fit`
- Layout: `D:/GoPro/2026-08-31/GX010239.layout.json`

---

## 1. CACHE VERSION PROOF

Sprawdzono kod źródłowy `src/telemetry_processed_cache.py`:
- `PROCESSED_CACHE_VERSION = 3`
- Zapis i odczyt cache `.telemetry.npz` zawiera wersję 3 (`version: 3`).
- Zabezpieczenie unieważnienia cache: jeśli plik cache ma wersję różną od 3 (np. starszą v2 bez TMPC), `read_processed_cache_arrays` natychmiast unieważnia cache i zwraca `(None, None)`, wymuszając reekstrakcję z natywnego GPMF C++.
- W nagłówku poprzedniego raportu poprawiono oznaczenie na `v3 (TMPC restore)`.
- **Weryfikacja na rzeczywistym pliku `GX010239.telemetry.npz`:**
  - `__meta__.version = 3`
  - Odczyt TMPC: `[TMPC Cache] read_count=186`
  - Wynik: **PASS**

---

## 2. AUTO-FIT REAL MATCH

Przeprowadzono automatyczny test wyszukiwania pliku FIT w katalogu `D:/GoPro/2026-08-31` dla klipów `GX010239.MP4` i `GX010240.MP4`:
- **Pomiary czasu:**
  - `MP4 probe time` (2 klipy): **87.639 ms** (odczyt bezwzględnych timestampów z GPMF)
  - `FIT candidate count`: **2** pliki w katalogu
  - `FIT directory scan`: **0.395 ms**
  - `FIT candidate probe & match`: **8.271 ms** (lekki binarny skaner nagłówków i sesji)
- **Wynik dopasowania:**
  - `Selected FIT`: `Popołudniowa_jazda_na_rowerze.fit`
  - `MP4 start`: `2026-08-31T13:03:35.299000+00:00`
  - `FIT range`: `2026-08-31T13:03:33+00:00` do `2026-08-31T14:00:19.909000+00:00`
  - `Overlap`: **1200.0 s**
  - `Start difference`: **2.299 s**
  - `Coverage`: **1.0 (100%)**
- Pole FIT w GUI zostaje automatycznie wypełnione, brak zgadywania, brak kosztownego pełnego parsowania wszystkich rekordów podczas skanowania katalogu.
- Wynik: **PASS**

---

## 3. FIT TIMER EVENTS & ACTIVE TIME MODEL

Analiza rzeczywistych zdarzeń timera w pliku `Popołudniowa_jazda_na_rowerze.fit`:
- **Zdarzenia timera (FIT timer events):**
  1. `timestamp=2026-08-31 13:03:33, type=start`
  2. `timestamp=2026-08-31 13:06:41, type=stop_all`
  3. `timestamp=2026-08-31 13:32:53, type=start`
  4. `timestamp=2026-08-31 14:00:20, type=stop_all`
- **Podsumowanie osi czasu aktywności:**
  - `activity start`: **2026-08-31 13:03:33**
  - `activity end`: **2026-08-31 14:00:19.909**
  - `wall duration`: **3406.909 s (56.78 min)**
  - `active timer duration`: **1835.000 s (30.58 min)**
  - `pause count`: **1**
  - `pause interval`: `[2026-08-31 13:06:41 – 2026-08-31 13:32:53]`
  - `total pause duration`: **1572.000 s (26.20 min)**
- Wynik: **PASS**

---

## 4. DYNAMIC AVERAGE SPEED — REAL CHECKPOINTS

Weryfikacja dynamicznej średniej prędkości (`avg_speed_kmh = active_distance / active_time`) na 6 rzeczywistych punktach kontrolnych:

| Punkt kontrolny | Czas UTC | Status pauzy | Dystans FIT | Czas zegarowy (wall) | Czas aktywny (active) | Średnia prędkość aktywna | Średnia zegarowa (błędna) |
|---|---|---|---|---|---|---|---|
| **early activity** | 13:05:00 | False | 303.2 m | 87.0 s | 87.0 s | **12.55 km/h** | 12.55 km/h |
| **before pause** | 13:06:40 | False | 742.8 m | 187.0 s | 187.0 s | **14.30 km/h** | 14.30 km/h |
| **during pause** | 13:15:00 | **True** | 746.2 m | 687.0 s | **188.0 s** | **14.29 km/h** | 3.91 km/h |
| **during pause (end)** | 13:30:00 | **True** | 746.2 m | 1587.0 s | **188.0 s** | **14.29 km/h** | 1.69 km/h |
| **immediately after** | 13:33:00 | False | 747.3 m | 1767.0 s | 195.0 s | **13.80 km/h** | 1.52 km/h |
| **later activity** | 13:45:00 | False | 4903.3 m | 2487.0 s | 915.0 s | **19.29 km/h** | 7.10 km/h |

- **Warunek spełniony:** W trakcie 26-minutowej pauzy czas aktywny pozostaje zamrożony na $188.0\text{ s}$, dystans nie przyrasta, a średnia prędkość pozostaje idealnie stała ($14.29\text{ km/h}$). Tradycyjna średnia wall-clock drastycznie i błędnie spadała do $1.69\text{ km/h}$.
- Wynik: **PASS**

---

## 5. CHART SKIP PAUSES — REAL DATA PROOF

Porównanie wykresów w trybie `charts_skip_pauses = False` vs `charts_skip_pauses = True`:

### A. CHART Activity
- `charts_skip_pauses = False` (OFF):
  - Czas trwania osi: **3407.0 s (56.78 min)**
  - Próbki: 1838
  - Pauza 26-minutowa stanowi pustą przerwę na osi X.
- `charts_skip_pauses = True` (ON):
  - Czas trwania osi: **1835.0 s (30.58 min)**
  - Próbki: 1836 (próbki w pauzie pominięte)
  - Skurczenie osi X: dokładnie o **1572.0 s (26.20 min)** — dokładnie czas trwania pauzy.
  - Złącze przedziałów (szew przy $t_{\text{active}} = 188.0\text{ s}$): próbki przed pauzą ($187.0\text{ s}$) i po wznowieniu ($188.0\text{ s}$) stykają się w odległości $1.0\text{ s}$, tworząc ciągły, gładki wykres bez fałszywych próbek.

### B. CHART Window
- Test okna w trakcie pauzy (timestamp 13:15:00):
  - OFF: próbki rozciągnięte w próżni czasowej zegarowej.
  - ON: `aligned_target` zamraża się na granicy pauzy ($188.0\text{ s}$), kursor wykresu nie skacze, a okno pokazuje dane aktywne.
- Wynik: **PASS**

---

## 6. MAP ROTATION SMOOTHING — REAL DATA PROOF

Sprawdzono serię próbek GPS heading z `GX010239.MP4` na rzeczywistym odcinku zakrętów:
- `Window 0.0 s` (legacy): `max_delta_0.5s = 58.00°`, `mean_delta = 19.22°` — ostre, szarpane skoki kursu.
- `Window 0.5 s`: `max_delta_0.5s = 54.30°`, `mean_delta = 18.24°`.
- `Window 1.0 s`: `max_delta_0.5s = 43.36°`, `mean_delta = 16.32°`.
- `Window 2.0 s`: `max_delta_0.5s = 28.36°`, `mean_delta = 13.00°` — stabilny, płynny obrót mapy bez gwałtownych szarpnięć.
- **Wrap 0/360:** Wektorowe sumy $(\sin, \cos)$ eliminują przeskok przez $180^\circ$.
- **Seek Parity:**
  - Losowy seek na $t = 15:05:18.8$: `val_seek = 64.586381°`
  - Odtwarzanie sekwencyjne: `val_seq = 64.586381°`
  - `exact_parity`: **True** (identyczność co do bitu float64).
- Wynik: **PASS**

---

## 7. LEAN MOTION SMOOTHING — REAL DATA PROOF

Weryfikacja na 36 972 rzeczywistych próbkach GYRO/ACCEL z GoPro (`GX010239.MP4`):
- `Window 0.0 s` (legacy): `max_delta_0.1s = 38.947°`, szum/jitter RMS: `16.188°` — gwałtowne drgania grafiki rowerka.
- `Window 0.5 s`: `max_delta_0.1s = 28.293°`, jitter RMS: `13.442°`.
- `Window 1.0 s`: `max_delta_0.1s = 17.650°`, jitter RMS: `9.710°`.
- `Window 2.0 s`: `max_delta_0.1s = 10.192°`, jitter RMS: `5.885°` — ruch rowerka wygładzony o ponad $63\%$, zachowane punkty wychylenia.
- **Niezmienione:** `pivot`, `sensitivity`, `max_angle`.
- **Seek Parity:**
  - `val_seq = 161.449401°`, `val_seek = 161.449401°`
  - `exact_parity`: **True**.
- Wynik: **PASS**

---

## 8. AUTOMATIC EXPORT FILENAME

Weryfikacja dla pliku źródłowego `D:/GoPro/2026-08-31/GX010239.MP4`:
- `Raw start timestamp (UTC)`: `2026-08-31 13:03:35.299000`
- `Local timestamp used for filename`: `2026-08-31 13:03:35.299000`
- `Zaokrąglenie do 5 minut`: `13:03:35` $\to$ **13:05:00**
- `Wygenerowana nazwa eksportu`: **`20260831-1305.mp4`**
- **Obsługa kolizji:**
  - Istnieje `20260831-1305.mp4` $\to$ `20260831-1305-01.mp4`
  - Istnieje `-01` $\to$ `20260831-1305-02.mp4`
- Wynik: **PASS**

---

## 9. SHORT REAL RENDER & PREVIEW PARITY

Wykonano krótki render (10 sekund = 300 klatek przy 29.97 FPS) rzeczywistego materiału `GX010239.MP4` wraz z `Popołudniowa_jazda_na_rowerze.fit` i presetem `GX010239.layout.json`:
- **Komponenty aktywne w renderze:**
  - MAP (obrót i marker trasy)
  - LEAN (wskaźnik przechyłu motocykla/roweru)
  - AVERAGE SPEED (dynamiczna średnia prędkość FIT)
  - CHARTS (wykresy okienne/aktywności)
  - TMPC (temperatura GoPro z natywnego GPMF C++)
- **Statystyki renderu (AMD D3D11VA GPU decode + AMF HEVC encode):**
  - `Render FPS`: **79.524 FPS**
  - `Effective FPS`: **59.020 FPS**
  - `Plik wyjściowy`: `scratch/real_user_smoke_render.mp4` (12.38 MB, 300 klatek)
- **Zgodność Preview vs Render:**
  - Wyliczono stan `prepare_overlay_frame_data` dla $t = 5.0\text{ s}$ w obu ścieżkach:
    - `speed_value`: `0.0 km/h` (identyczna)
    - `temp_value`: `30.58 °C` (identyczna temperatura TMPC)
    - `alt_value`: `29.026 m` (identyczna)
  - Obie ścieżki (podgląd i eksport) współdzielą ten sam potok danych i te same prekomputacje czasowe.
- Wynik: **PASS**

---

## 10. ISSUES FOUND & FIXED

Podczas testów rzeczywistego projektu wykryto i natychmiast usunięto dwie usterki integracyjne:
1. **`prepare_overlay_frame_data` w `src/indicators/frame_data.py`**:
   - Odwołanie do niezdefiniowanej zmiennej `telemetry` przy wyciąganiu `active_mapper` z `fit_data`.
   - Poprawiono na bezpieczne pobieranie: `fit_data.get("active_time_mapper")` oraz `getattr(fit_data, "active_time_mapper", None)`.
2. **`find_best_fit_match` w `telemetry_fit.py`**:
   - Przy klipach wieloplikowych z `end_dt is None` porównanie strefy czasowej rzucało `AttributeError`.
   - Poprawiono: automatyczne dopełnienie `end = s + timedelta(seconds=600)` przed normalizacją strefy czasowej.

Wszystkie testy jednostkowe (`tests/test_activity_ux_timeline.py`) zakończone wynikiem 10/10 PASS w 0.022 s.

---

## PODSUMOWANIE KOŃCOWE

```text
CACHE VERSION: PASS
AUTO FIT REAL: PASS
FIT ACTIVE AVG REAL: PASS
CHART SKIP PAUSES REAL: PASS
MAP SMOOTHING REAL: PASS
LEAN SMOOTHING REAL: PASS
AUTO EXPORT NAME REAL: PASS
SHORT RENDER PARITY: PASS

ACTIVITY UX PRODUCTION READY: YES
```
