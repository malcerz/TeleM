# TeleM — ETAP 8E: Naprawa wykresów — pełna aktywność + ruchomy `current marker`

## Result

**ETAP 8E zakończony.**
Klasyfikacja:
```text
FULL-ACTIVITY CHART TIMELINE = PASS
```

Wykresy wskaźników (`fit_cadence_text`, `fit_heart_rate_text`, itp.) przedstawiają teraz **pełną aktywność widoczną w filmie** (zakres `[video_start_dt, video_end_dt]`) niezmiennie przez cały czas trwania nagrania. Kształt krzywej wykresu pozostaje stały, a ruchomy kursor (`current marker` — pionowa linia oraz punkt na krzywej) przesuwa się płynnie po pełnej osi X wraz z upływem czasu filmu (`current_position` od 0.0 do 1.0). Bieżąca wartość (`current value`) jest wyznaczana ściśle według reguły STEP (`greatest timestamp <= target_dt`), a przyszłe próbki widoczne na wykresie nie wpływają na wartość bieżącą.

---

## A. Root Cause

### 1. Lokalizacja błędu
- **Pliki**: `src/indicators/chart_builder.py` (`clip_chart_data`), `src/indicators/frame_data.py` (linia 436), `src/telemetry_precompute.py` (linia 130).
- **Stary kontrakt (po ETAPIE 6D)**:
  `clip_chart_data(chart_data, target_dt, start_dt_utc)` obcinał listę próbek `chart_data` do warunku `timestamp <= target_dt` dla każdej klatki osobno.

### 2. Dlaczego deformowało to oś X
1. Renderer wykresu (`generate_history_chart` / `get_history_chart_background`) skaluje przekazaną mu serię próbek na **100% szerokości wykresu**.
2. Na początku filmu (np. `14.3 s` z 180 s) przekazywano tylko 15 próbek. Renderer rozciągał te 15 próbek na całą szerokość wykresu, co dawało zniekształcony, płaski prostokąt.
3. W ~70% filmu (np. `126 s`) pierwsze 70% danych było rozciągnięte na 100% szerokości, podczas gdy kursor znajdował się na pozycji 70%. Marker i kształt krzywej odnosiły się do dwóch zupełnie różnych skal osi X.
4. Ciągłe mutowanie/przycinanie serii per-frame unieważniało cache tła wykresu (`_CHART_BG_CACHE` oraz `_FINAL_STATIC_CHART_CACHE`), wymuszając ciągłe przeliczanie geometrii wykresu co klatkę.

---

## B. Correct Chart Contract (Docelowy Kontrakt)

Rozdzielono **FULL DISPLAY SERIES** od **CURRENT LOOKUP**:

```text
display_series =
    [samples where video_start_dt <= timestamp <= video_end_dt]
    (stała, niemutowalna seria dla całego filmu)

current_value =
    lookup(source_samples, target_dt)
    (STEP: greatest timestamp <= target_dt; linear dla speed/alt/dist)

current_position =
    (target_dt - video_start_dt) / (video_end_dt - video_start_dt)
    (współrzędna znormalizowana 0.0 .. 1.0 na osi wykresu)
```

- **Wykres**: Rysuje całą krzywą aktywności dla zakresu filmu od klatki 0 do końca.
- **Marker**: Rysuje pionową linię i punkt na krzywej w pozycji `current_position * width`.
- **Display invariance**: Seria punktów wykresu jest identyczna w każdej klatce.

---

## C. Video-Visible Range (Zakres Czasowy Wykresu)

Zakres wykresu jest wyznaczany jako iloczyn zbiorów (intersection) zakresu źródła telemetrii oraz czasu trwania filmu:

```text
chart_start_dt = max(source_first_timestamp, video_start_dt)
chart_end_dt   = min(source_last_timestamp,  video_end_dt)
```

Dla materiału referencyjnego `GX030120.MP4` (180,013 s) i `Poranna_jazda_na_rowerze.fit`:
- `video_start_dt` = `2026-08-18 04:46:25.700000 UTC`
- `video_end_dt`   = `2026-08-18 04:49:25.713000 UTC`
- Cały plik FIT: 1672 próbki (od 04:29:39 do 04:57:30 UTC).
- **Video-visible FIT range**: dokładnie **180 próbek** (od 04:46:26 do 04:49:25 UTC).
- Próbki sprzed startu filmu (< 04:46:25.7) oraz po jego końcu (> 04:49:25.7) są odcinane przy budowie serii wykresu i nie rozszerzają osi czasu.

---

## D. Implementation (Zmodyfikowane Komponenty)

1. **`src/indicators/chart_builder.py`**:
   - `build_chart_data(layout, get_samples_fn, resolve_samples_fn, start_dt_utc=None, end_dt_utc=None)`:
     Wycina surowe próbki źródła do zakresu `[start_dt_utc, end_dt_utc]` przy użyciu `bisect_left` i `bisect_right`. Zwraca `ChartHistory` ze stałą listą wartości i timestampów.
   - `clip_chart_data(chart_data, start_dt=None, end_dt=None)`:
     Wykonuje wycięcie przedziału `[start_dt, end_dt]` (nie przycina per-frame do `target_dt`).
2. **`src/indicators/frame_data.py`**:
   - `prepare_overlay_frame_data`: przekazuje `chart_data` bezpośrednio do `compose_overlay` bez obcinania do `target_dt`.
3. **`src/telemetry_precompute.py`**:
   - `TelemetryFrameCache.lookup`: przekazuje `st.chart_data` bez obcinania per-frame.
4. **`src/ffmpeg/worker_cache.py`**:
   - `init_worker`: oblicza `end_dt_utc = start_dt_utc + timedelta(seconds=duration_s)` i przekazuje granice do `build_chart_data`.
5. **`src/gui/qt/_mixins/preview_mixin.py`**:
   - `_chart_data_cache`: oblicza `end_dt_utc` z długości wideo i przekazuje granice do `build_chart_data`.
6. **`src/indicators/chart.py`**:
   - `_render_chart_indicator`: wyznacza pozycję markera `ci` na podstawie timestampów próbki lub `current_position`.
7. **`src/indicators/dispatcher.py`**:
   - `render_value_indicator`: przekazuje `target_dt` do `_render_chart_indicator`.

---

## E. Full-Series Invariance (Niezmienniczość Serii Wykresu)

Pomiary z realnego materiału `GX030120.MP4` + `Poranna_jazda_na_rowerze.fit`:

| `video_s` | Frame Index | `current_position` | HR Sample Count | HR Series SHA256 (prefix) | CAD Sample Count | CAD Series SHA256 (prefix) |
|---:|---:|---:|---:|---|---:|---|
| **0.0 s** | 0 | 0.0000 | **180** | `5a84108a` | **180** | `25822a91` |
| **14.3 s** | 429 | 0.0795 | **180** | `5a84108a` | **180** | `25822a91` |
| **60.0 s** | 1798 | 0.3333 | **180** | `5a84108a` | **180** | `25822a91` |
| **120.0 s** | 3596 | 0.6667 | **180** | `5a84108a` | **180** | `25822a91` |
| **175.0 s** | 5245 | 0.9724 | **180** | `5a84108a` | **180** | `25822a91` |
| **179.9 s** | 5392 | 0.9996 | **180** | `5a84108a` | **180** | `25822a91` |

**Wniosek:** Seria danych wykresu jest w 100% identyczna (ten sam hash, ta sama liczba 180 próbek) na każdej klatce.

---

## F. HR Real Material (`fit_heart_rate_text`)

| `video_s` | `target_dt` | Chart Count | First Sample TS | Last Sample TS | Current Value (BPM) | Marker Index `ci` / 180 | Marker X Pos (%) |
|---:|---|---:|---|---|---:|---:|---:|
| **0.0 s** | 04:46:25.7 | 180 | 04:46:26 | 04:49:25 | **103.0** | 0 | 0.0% |
| **14.3 s** | 04:46:40.0 | 180 | 04:46:26 | 04:49:25 | **102.0** | 14 | 7.9% |
| **60.0 s** | 04:47:25.7 | 180 | 04:46:26 | 04:49:25 | **91.0** | 60 | 33.3% |
| **120.0 s** | 04:48:25.7 | 180 | 04:46:26 | 04:49:25 | **109.0** | 120 | 66.7% |
| **175.0 s** | 04:49:20.7 | 180 | 04:46:26 | 04:49:25 | **110.0** | 175 | 97.2% |
| **179.9 s** | 04:49:25.6 | 180 | 04:46:26 | 04:49:25 | **108.0** | 179 | 100.0% |

---

## G. Cadence Real Material (`fit_cadence_text`)

| `video_s` | `target_dt` | Chart Count | First Sample TS | Last Sample TS | Current Value (RPM) | Marker Index `ci` / 180 | Marker X Pos (%) |
|---:|---|---:|---|---|---:|---:|---:|
| **0.0 s** | 04:46:25.7 | 180 | 04:46:26 | 04:49:25 | **67.0** | 0 | 0.0% |
| **14.3 s** | 04:46:40.0 | 180 | 04:46:26 | 04:49:25 | **62.0** | 14 | 7.9% |
| **60.0 s** | 04:47:25.7 | 180 | 04:46:26 | 04:49:25 | **45.0** | 60 | 33.3% |
| **120.0 s** | 04:48:25.7 | 180 | 04:46:26 | 04:49:25 | **74.0** | 120 | 66.7% |
| **175.0 s** | 04:49:20.7 | 180 | 04:46:26 | 04:49:25 | **59.0** | 175 | 97.2% |
| **179.9 s** | 04:49:25.6 | 180 | 04:46:26 | 04:49:25 | **61.0** | 179 | 100.0% |

---

## H. Marker Alignment (Zgodność Pozycji Kursora z Osią Czasu)

| Czas filmu | Teoretyczny postęp filmu | Obliczony `current_position` | Punkt na wykresie (`points[ci]`) | Wartość w punkcie kursora | Błąd dopasowania |
|---|---:|---:|---:|---:|---|
| **0% filmu** (0.0 s) | 0.00% | **0.0000** | Punkt 0 (04:46:26) | HR=103 / CAD=67 | 0.0% |
| **25% filmu** (45.0 s) | 25.00% | **0.2500** | Punkt 45 (04:47:11) | HR=95 / CAD=50 | 0.0% |
| **50% filmu** (90.0 s) | 50.00% | **0.5000** | Punkt 90 (04:47:56) | HR=104 / CAD=71 | 0.0% |
| **70% filmu** (126.0 s) | 70.00% | **0.6999** | Punkt 126 (04:48:32) | HR=108 / CAD=73 | < 0.1% |
| **75% filmu** (135.0 s) | 75.00% | **0.7499** | Punkt 135 (04:48:41) | HR=107 / CAD=70 | < 0.1% |
| **100% filmu** (180.0 s) | 100.00% | **1.0000** | Punkt 179 (04:49:25) | HR=108 / CAD=61 | 0.0% |

---

## I. Runtime Artifacts & Visual Validation

Wygenerowano i zapisano pełne klatki HUD w katalogu `Raporty/AMD_ETAP8E/`:
- `overlay_frame_000.0s.png` — początek filmu: pełny wykres widoczny od pierwszej klatki, marker na pozycji 0%.
- `overlay_frame_014.3s.png` — 14.3 s: ten sam pełny wykres, marker na pozycji ~8%.
- `overlay_frame_060.0s.png` — 60.0 s: ten sam pełny wykres, marker na pozycji 33.3%.
- `overlay_frame_120.0s.png` — 120.0 s: ten sam pełny wykres, marker na pozycji 66.7%.
- `overlay_frame_175.0s.png` — 175.0 s: ten sam pełny wykres, marker na pozycji 97.2%.
- `overlay_frame_179.9s.png` — koniec filmu: ten sam pełny wykres, marker na pozycji 100.0%.

---

## J. Source Ownership

| Źródło w layout | Seria wykresu | Wartość bieżąca | Fallback do innego źródła? |
|---|---|---|---|
| `source = "fit"` | FIT samples only | FIT only | **BRAK** (gwarancja izolacji) |
| `source = "gpmf"` | GPMF samples only | GPMF only | **BRAK** |
| `source = "gpx"` | GPX samples only | GPX only | **BRAK** |

---

## K. None / Zero Contract

| Scenariusz | Seria wykresu | Wartość bieżąca (`current_value`) | Pozycja markera |
|---|---|---|---|
| Brak pliku FIT / puste źródło | Pusta lista `[]` | `None` | `None` (brak markera) |
| Próbki przed pierwszym timestampem | Pełna seria wideo | `None` / `103.0` (zgodnie z 6E) | `0.0` |
| Rzeczywiste `0.0` (np. postój na światłach: cadence = 0) | Zachowane jako punkt `0.0` na krzywej | `0.0` | Zgodna z czasem |

---

## L. Pipeline Parity (Zgodność we Wszystkich Ścieżkach)

Dla klatki `14.3 s` (429 klatka):

| Ścieżka wykonania | Liczba próbek HR | Liczba próbek CAD | `current_position` | `current_value` HR | `current_value` CAD | Status |
|---|---:|---:|---:|---:|---:|---|
| **GUI Preview** (`preview_mixin.py`) | 180 | 180 | 0.0795 | 102.0 | 62.0 | **PASS** |
| **CPU Final** (`frame_data.py`) | 180 | 180 | 0.0795 | 102.0 | 62.0 | **PASS** |
| **PRECOMPUTED** (`telemetry_precompute.py`) | 180 | 180 | 0.0795 | 102.0 | 62.0 | **PASS** |
| **Worker Cache** (`worker_cache.py`) | 180 | 180 | 0.0795 | 102.0 | 62.0 | **PASS** |
| **AMD GPU_SPLIT Input** | 180 | 180 | 0.0795 | 102.0 | 62.0 | **PASS** |

---

## M. Performance & Caching

1. **Brak alokacji/kopiowania serii per-frame**:
   - `build_chart_data` wykonuje się dokładnie **raz** przy starcie eksportu / inicjalizacji podglądu.
   - `TelemetryFrameCache` przechowuje referencję do niezmiennej serii `_Static.chart_data` (0 alokacji per frame).
2. **Efektywność `ChartSplit` / `AMD_CHART_PATH=GPU_SPLIT`**:
   - Ponieważ seria punktów `chart_vals` nie zmienia się między klatkami, klucz cache `bg_key` oraz `final_key` w `_FINAL_STATIC_CHART_CACHE` pozostają stałe przez cały eksport.
   - Statyczny raster wykresu (`bg_img` z siatką, osią i etykietami) jest generowany **raz w klatce 0** i wgrywany na GPU tylko raz.
   - W każdej klatce przesyłany jest wyłącznie mały kafelek kursora (`~10×400 px`) i etykiety wartości (`~150×50 px`).

---

## N. Tests (Podsumowanie Testów)

1. **Nowy zestaw testów**:
   - `tests/test_etap8e_full_activity_charts.py` (4 testy: niezmienniczość pełnej serii, ruch markera 0..1, wycinanie do zakresu wideo, brak wpływu przyszłych próbek na wartość bieżącą).
2. **Zaktualizowany zestaw**:
   - `tests/test_etap6d_chart_history.py` (3 testy: dostosowane do zakresu wideo zamiast obcinania do klatki).
3. **Powiązane zestawy testowe**:
   - `tests/test_etap6e_step_lookup.py` (3 testy — PASS)
   - `tests/test_etap6b_contract.py` (7 testów — PASS)
   - `tests/test_chart_rendering.py` (7 testów — PASS)
   - `tests/test_chart_static_assembly_etap5d.py` (3 testy — PASS)
   - `tests/test_telemetry_manager.py` (29 testów — PASS)
   - `tests/test_interpolation.py` (13 testów — PASS)
   - `tests/test_etap1_source_resolver.py` (6 testów — PASS)
4. **Pełny zestaw `pytest`**:
   ```text
   340 passed, 3 failed, 17 skipped in 21.06s
   ```
   Trzy znane, niezwiązane failure'y pozostają bez zmian:
   - `tests/test_amd_native_etap4.py`
   - `tests/test_qp_analyzer.py`
   - `tests/test_render_tab.py`

---

## O. Brak Regresji (Regression Verification)

- [x] **STEP lookup**: zachowano dokładny kontrakt `bisect_right - 1` z ETAPU 6E.
- [x] **Linear interpolation**: zachowano dla pól ciągłych (`speed`, `alt`, `dist`).
- [x] **Source ownership**: brak fallbacków między FIT / GPMF / GPX.
- [x] **Geometria / Layout**: brak zmian w bounding boxach, pozycjach, czcionkach.
- [x] **Map synchronization**: `track_map` i `gps_track` bez zmian.
- [x] **AMD Native pipeline & z-order**: nienaruszony (z-order: BELOW -> MAP -> ABOVE).
- [x] **Optymalizacje ETAPU 8C/8D**: nienaruszone (regional clear, candidate crop, local alpha scan).

---

## P. Final Classification

```text
FULL-ACTIVITY CHART TIMELINE = PASS
```

**ETAP 8E — COMPLETE.**
