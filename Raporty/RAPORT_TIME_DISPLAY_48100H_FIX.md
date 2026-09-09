# RAPORT — TIME DISPLAY 48100H FIX & SINGLE SOURCE OF TRUTH

Data: 2026-09-05  
Gałąź: `integration/intel-amd`  
Zadanie: Naprawa krytycznego błędu licznika `CZAS` w `time_display` (`CZAS: 48100:24:43`) na projekcie użytkownika `D:/GoPro/2026-09-01/GX010241.MP4` + `Poranna_jazda_na_rowerze.fit`.  
Ustanowienie `src/indicators/frame_data.py` jako pojedynczego źródła prawdy (`Single Source of Truth`) dla `elapsed_seconds` i `avg_speed_kmh`.

---

## 1. ROOT CAUSE ANALIZA

### Objaw na Rzeczywistym Projekcie Użytkownika
- Klip: `D:/GoPro/2026-09-01/GX010241.MP4`
- Dopasowany FIT: `D:/GoPro/2026-09-01/Poranna_jazda_na_rowerze.fit`
- Czas startu MP4: `2026-09-01 04:24:48.795271 UTC`
- Czas startu FIT: `2026-09-01 04:24:36 UTC`
- Czas dnia na HUD: `GODZINA: 06:24:48` (poprawny czas lokalny UTC+2)
- Czas trwania na HUD: **`CZAS: 48100:24:43`** (absurdalna wartość: 48 100 godzin!)

Oczekiwana wartość na początku klipu:
$$T_{\text{elapsed}} = 04:24:48.795271 - 04:24:36 = 12.795271\text{ s} \implies \text{CZAS: 00:12}$$

### Mechanizm Powstania Błędu (Podwójna Przyczyna Pierwotna)

1. **Błędny timestamp początkowy w `.telemetry.npz`:**
   W natywnym parserze GPMF (`src/native/gpmf/gpmf_extractor.cpp`), `anchor_ts` został pobrany z pierwszego dostępnego pakietu GPS:
   ```cpp
   anchor_ts = result.gps[0].timestamp;
   ```
   Kamera GoPro w momencie włączenia nie miała jeszcze fixa GPS (`lat = 0.0, lon = 0.0, fix = 0`), przez co wypluła domyślny zegar bazowy procesora kamery z epoki fabrycznej:
   ```text
   timestamp: 1615075205.0 -> 2021-03-07 00:00:05 UTC!
   ```
   Wartość ta została zapisana do metadanych `GX010241.telemetry.npz` jako `start_dt_utc: 2021-03-07T00:00:05+00:00`.

2. **Rozdzielenie logiki i pominięcie FIT dla licznika HUD w `src/indicators/frame_data.py`:**
   W kodzie `prepare_overlay_frame_data()` obliczanie `elapsed_seconds` i `activity_elapsed_s` było rozdzielone na dwa niezależne bloki:
   ```python
   # Blok 1: Obliczenie elapsed_seconds dla time_display
   elapsed_seconds = 0.0
   if project_elapsed_s is not None:
       elapsed_seconds = max(0.0, float(project_elapsed_s))
   elif start_dt_utc is not None and target_dt is not None:
       elapsed_seconds = max(0.0, (_td - _sd).total_seconds())

   # Blok 2: Obliczenie activity_elapsed_s wyłącznie dla avg_speed_kmh
   if active_mapper is not None:
       activity_elapsed_s = active_mapper.wall_to_active_seconds(target_dt)
   ```
   W preview GUI (`preview_mixin.py` linia 689) parametr `project_elapsed_s` nie był przekazywany (`None`).
   W rezultacie `elapsed_seconds` wpadał w gałąź:
   $$\Delta t = 2026\text{-}09\text{-}01\ 04:24:48.795271 - 2021\text{-}03\text{-}07\ 00:00:05 = 173\,161\,483.795\text{ s}$$
   $$173\,161\,483.795\text{ s} = 48100\text{ h } 24\text{ min } 43\text{ s} \implies \mathbf{48100:24:43}!$$

   Co kluczowe: obliczony poprawnie `activity_elapsed_s` (12.795 s) z `ActiveTimeMapper` był używany **wyłącznie** jako mianownik dla `avg_speed_kmh`, a do słownika wynikowego jako `"elapsed_seconds"` zwracano wartość z Bloku 1! W efekcie wskaźnik `time_display` na HUD **zawsze ignorował FIT** i brał surową różnicę od `start_dt_utc`.

3. **Duplikacja w CPU fallback renderera (`src/ffmpeg/frame_renderer.py`):**
   W `render_frame_job` (linie 491–496) znajdowało się niezależne obliczenie:
   ```python
   _elapsed = max(0.0, (current_dt_utc - start_dt_utc).total_seconds())
   ```
   które również nie uwzględniało `active_mapper` ani czasu aktywności FIT.

4. **Brak spójności w cache prekomputacji (`src/telemetry_precompute.py`):**
   W pętli ramek `telemetry_precompute.py` (linia 970) do rekordu przekazywano `elapsed_seconds=el_s` (oparte na osi wideo) zamiast `elapsed_seconds=act_el_s` (czas aktywny FIT).

---

## 2. ZAIMPLEMENTOWANE ROZWIĄZANIE

Zgodnie z wytycznymi, **nie modyfikowano formatowania w `src/indicators/time_display.py`** (brak modulo 24, brak clampowania). Usunięto źródło problemu u podstaw.

### A. Jedno Kanoniczne Źródło Prawdy: `src/indicators/frame_data.py`
W `src/indicators/frame_data.py` zunifikowano wyznaczanie `elapsed_seconds` w oparciu o ścisłą hierarchię priorytetów wraz z walidacją `sanity check`:

```text
Hierarchia czasu upłyniętego:
1. FIT + poprawny ActiveTimeMapper -> aktywny czas od startu aktywności (pauzy zamrażają licznik)
2. FIT / GPX bez aktywnego mappera -> target_dt - start_aktywności (czas zegarowy aktywności)
3. Brak FIT -> project_elapsed_s (oś timeline wideo)
4. Fallback ostateczny -> target_dt - start_dt_utc (zabezpieczony sanity checkiem)
```

Implementacja sanity check:
- Jeśli `active_elapsed > wall_elapsed_activity + 5.0 s` (aktywny czas nie może przekroczyć zegarowego) lub interwał przekracza 30 dni: system loguje ostrzeżenie `[SanityCheck]` i bezpiecznie cofa się do `wall_elapsed` lub `project_elapsed_s`.
- W gałęzi fallbacku wideo: różnica $> 30\text{ dni}$ (`2592000.0 s`) jest natychmiast wychwytywana, logowana i zerowana do `0.0 s`, uniemożliwiając wyświetlenie 48 100 godzin.
- Wartość `activity_elapsed_s` została zrównana z `elapsed_seconds`:
  ```python
  activity_elapsed_s = elapsed_seconds
  avg_speed_kmh = (distance_m / activity_elapsed_s) * 3.6 if ... else 0.0
  ```

### B. Przekazywanie `project_elapsed_s` w GUI
W `src/gui/qt/_mixins/preview_mixin.py` (linia 720) do wywołania `prepare_overlay_frame_data()` dodano parametr `project_elapsed_s=global_time`.

### C. Wyrównanie w `src/telemetry_precompute.py`
- Zabezpieczono pobieranie `active_mapper` zarówno ze słownika `dict` jak i obiektu `FitDataset`.
- Rekordy klatki `_FrameRec` otrzymują `elapsed_seconds=act_el_s` z sanity checkiem, gwarantując 100% zgodności z `prepare_overlay_frame_data()`.

### D. Wyrównanie w `src/ffmpeg/frame_renderer.py`
W `render_frame_job` wprowadzono pobieranie `active_mapper` z `WORKER_CACHE.get("fit_data")` oraz sanity check chroniący przed błędnymi datami.

### E. Auto-uzdrawianie i Ochrona Przed Zegarem Epoki Fabrycznej
- **`src/telemetry_native_gpmf.py`:** W `populate_telemetry_from_native` priorytet ma zweryfikowany timestamp z `resolve_clip_timestamp(video_path)` (bazujący na korelacji `stmp` GPS9); odrzucany jest surowy `start_ts` sprzed 2022 roku.
- **`src/telemetry_processed_cache.py`:** W `read_processed_cache` dodano auto-heal: jeśli zdeserializowany z cache `.telemetry.npz` timestamp ma `year < 2022` (stary cache z epoki fabrycznej), zostaje w locie uzdrowiony przez `resolve_clip_timestamp(source_path)` do właściwej daty nagrania (`2026-09-01 04:24:48.795271`).

---

## 3. WYNIKI TRACE DLA JEDNEJ KLATKI (REALNY PROJEKT PORANNY)

Skrypt: `scratch/trace_morning_frame.py`  
Klip: `D:/GoPro/2026-09-01/GX010241.MP4`  
FIT: `D:/GoPro/2026-09-01/Poranna_jazda_na_rowerze.fit`  

```text
=================== TRACE JEDNEJ KLATKI ===================
target_dt=                 2026-09-01 04:24:48.795271
start_dt_utc=              2026-09-01 04:24:48.795271
fit activity start=        2026-09-01 04:24:36
fit activity end=          2026-09-01 04:55:44.964000
active_mapper exists=      True
active_mapper type=        <class 'src.telemetry_active_time.ActiveTimeMapper'>
active intervals=          [(datetime.datetime(2026, 9, 1, 4, 24, 36), datetime.datetime(2026, 9, 1, 4, 55, 45))]
pause intervals=           []
wall_to_active_seconds(target_dt)= 12.795271
cumulative_active_time(target_dt)= 12.795271
project_elapsed_s=         0.0
elapsed_seconds FINAL=     12.795271
time_display formatted=    CZAS: 00:12
===========================================================
```

Wynik testu:
- Zegar na klatce 0: **`CZAS: 00:12`** (dla $12.795\text{ s}$, przy $13.0\text{ s}$ przechodzi na `00:13`).
- Błąd 48 100 godzin został całkowicie zlikwidowany.

---

## 4. PARYTET MIĘDZY ŚCIEŻKAMI PREVIEW, RENDER I PRECOMPUTE

Pomiary dla klatki 0 na rzeczywistym projekcie:
```text
PREVIEW frame 0 elapsed_seconds:     12.795271 s
REFERENCE frame 0 elapsed_seconds:   12.795271 s
PRECOMPUTED frame 0 elapsed_seconds: 12.795271 s
Maksymalna różnica (max_diff):       0.000000 s
Status parytetu:                     EXACT MATCH (PASS)
```

---

## 5. TESTY REGRESYJNE I JEDNOSTKOWE

W pliku `tests/test_activity_ux_timeline.py` utworzono nową klasę testów `TestElapsedSecondsSingleSourceAndParity`:
1. `test_fit_with_active_mapper`: weryfikacja priorytetu #1 (FIT active mapper $\to 12.795271\text{ s}$).
2. `test_pause_freezes_elapsed_seconds`: weryfikacja zamrożenia licznika `CZAS` podczas pauzy (np. na minucie 12 licznik zatrzymany na `600.0 s`).
3. `test_fit_without_mapper_fallback`: weryfikacja priorytetu #2 (FIT bez zdarzeń timera $\to$ różnica od startu aktywności).
4. `test_no_fit_project_elapsed`: weryfikacja priorytetu #3 (brak FIT $\to$ `project_elapsed_s`).
5. `test_sanity_check_prevents_48100h`: weryfikacja ucięcia 5.5-letniego błędu fabrycznego zegara kamery do `0.0 s`.
6. `test_sanity_check_active_exceeding_wall`: weryfikacja zabezpieczenia przed błędnym mapperem zwracającym wartość większą niż czas zegarowy.
7. `test_preview_render_precompute_parity`: weryfikacja 100% tożsamości `elapsed_seconds` między Preview, Referencją a Prekomputacją.

Wynik uruchomienia pakietu testów:
```text
pytest tests/test_activity_ux_timeline.py tests/test_telemetry_processed_cache.py tests/test_time_display_optimization.py tests/test_time_display_icon_size.py
Ran 52 passed in 1.12s
```

---

## 6. IZOLACJA BACKENDÓW

- Żadne zmiany nie ingerują w backendy NVIDIA (CUDA/NVENC), Intel (QSV) ani potok D3D11 / AMF.
- Zmiany dotyczą wyłącznie unifikacji danych telemetrycznych w Pythonie (`src/indicators/frame_data.py`, `src/telemetry_precompute.py`, `preview_mixin.py`, `frame_renderer.py`).
- Renderer wideo i formatowanie wizualne w `src/indicators/time_display.py` pozostały nietknięte.

---

## 7. FINAL VERDICT

```text
48100H ROOT CAUSE FOUND: YES
HUD ACTIVE ELAPSED: PASS
MORNING FIT REAL TEST: PASS
PREVIEW RENDER PARITY: PASS
```
