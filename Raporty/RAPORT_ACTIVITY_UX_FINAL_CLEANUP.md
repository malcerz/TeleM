# RAPORT — ACTIVITY UX FINAL CLEANUP

Data: 2026-09-05  
Gałąź: `integration/intel-amd`  
Zadanie: Naprawa 2 problemów znalezionych podczas przeglądu raportu Activity UX:
1. Automatyczna nazwa eksportu — konwersja UTC do lokalnego czasu nagrania z uwzględnieniem strefy i DST.
2. Auto-FIT — eliminacja heurystyki 600 s na rzecz rzeczywistych przedziałów każdego klipu i scoringu multi-file.

---

## 1. AUTOMATYCZNA NAZWA EKSPORTU — CZAS LOKALNY

### Timezone Root Cause
W poprzedniej implementacji timestamp `start_dt` (reprezentowany jako naive-UTC z GPMF / timeline `2026-08-31 13:03:35.299 UTC`) był bezpośrednio zaokrąglany do najbliższych 5 minut przez `round_dt_to_nearest_5min(start_dt)`, generując nazwę:
```text
20260831-1305.mp4
```
Kod traktował czas UTC bezpośrednio jako lokalny. W rzeczywistości nagranie w Polsce miało miejsce o godzinie 15:03:35 CEST (czas letni UTC+2).

### Rozwiązanie i Kanoniczna Kolejność Timezone
W `src/video_helpers.py` zaimplementowano funkcję `resolve_local_datetime(dt, fit_data=None, tz_offset_hours=None, tzinfo=None)` o kanonicznej hierarchii:
1. **FIT / GPMF / projekt**: Odczyt offsetu strefy czasowej z pliku FIT (np. Garmin Edge zapisuje w wiadomości `activity` pola `timestamp` [UTC] i `local_timestamp` [lokalny], różnica: `15:03:33 - 13:03:33 = +2.0 h`). W `telemetry_fit.py` dodano `probe_fit_timezone_offset()` oraz atrybut `timezone_offset_hours` w `FitRecords` i `FitDataset`.
2. **Timezone offset aplikacji / projektu**: Jeśli podano jawny `tz_offset_hours` w projekcie, zostaje zastosowany.
3. **Lokalna strefa systemowa jako fallback (DST-aware)**: Przekształcenie `dt.replace(tzinfo=timezone.utc).astimezone()` do strefy systemowej Windows (`Europe/Warsaw`). Automatycznie rozróżnia czas letni (CEST, UTC+2 w sierpniu) i czas zimowy (CET, UTC+1 w styczniu). Żadna stała `UTC+2` nie jest wpisana na sztywno.

### Wyniki Retestu (Real Project)
Dla rzeczywistego klipu `D:/GoPro/2026-08-31/GX010239.MP4`:
- **Absolute UTC start:** `2026-08-31 13:03:35.299 UTC`
- **Resolved timezone (FIT):** `FIT activity offset (+2.0h)`
- **Local datetime:** `2026-08-31 15:03:35.299`
- **Rounded local datetime (5 min):** `2026-08-31 15:05:00`
- **Generated filename:** `20260831-1505.mp4`

Retest dla czystego fallbacku systemowego (bez FIT):
- **Resolved timezone:** `System local timezone (Środkowoeuropejski czas letni, +2:00:00)`
- **Local datetime:** `2026-08-31 15:03:35.299`
- **Generated filename:** `20260831-1505.mp4`

Retest dla daty zimowej (styczeń, sprawdzenie DST):
- **Absolute UTC start:** `2026-01-15 13:03:35.299 UTC`
- **Resolved timezone:** `System local timezone (Środkowoeuropejski czas standardowy, +1:00:00)`
- **Local datetime:** `2026-01-15 14:03:35.299`
- **Generated filename:** `20260115-1405.mp4` (dowód: brak zahardkodowanego UTC+2)

Kolizje nazw (`-01`, `-02`):
- `base`: `20260831-1505.mp4`
- `collision 1`: `20260831-1505-01.mp4`
- `collision 2`: `20260831-1505-02.mp4`

Ochrona ręcznej edycji nazwy (`manual filename protection`):
- W `RenderTab` flaga `self._user_edited_output` rejestruje `edit_output.textEdited` oraz wybór z okna dialogowego `btn_out`.
- Sygnał `sig_default_export_name_ready` nie nadpisuje nazwy, jeśli `_user_edited_output is True`.

---

## 2. AUTO-FIT — RZECZYWISTE DŁUGOŚCI I MULTI-FILE SCORING

### Auto-FIT Old 600s Behavior
Wcześniejszy kod stosował sztywny fallback:
```python
if end_dt is None:
    end = start + timedelta(seconds=600)
```
W efekcie dla 2 klipów raportował sztuczne `Overlap = 1200.0 s` (2 × 600 s), ignorując prawdziwy czas trwania nagrań.

### Źródło Rzeczywistego Duration
W `src/multifile.py` zaimplementowano funkcję `probe_clip_time_interval(path, ...)`:
- Odczytuje dokładny czas trwania z `_FFPROBE_DURATION_CACHE` lub szybkiego odczytu metadanych kontenera MP4 przez `probe_video_info(ffprobe_exe, p)` (bez ciężkiego parsowania GPMF).
- Odczytuje `absolute_start_dt` przez `resolve_clip_timestamp(p)` (z `.telemetry.npz` / szybkiego nagłówka).
- Wyznacza rzeczywisty koniec klipu: `absolute_end_dt = absolute_start_dt + timedelta(seconds=dur_s)`.
- Przy braku duration stosuje degraded fallback `600 s` z flagą `confidence = "degraded"`.

### Multi-File Scoring
W `telemetry_fit.py`:
- Każdy klip wideo posiada własny rzeczywisty przedział `[clip_start, clip_end]`.
- Overlap z FIT liczony jest jako suma nachodzenia każdego rzeczywistego klipu z FIT:
  $$\text{total\_overlap} = \sum_{i} \max(0, \min(c_{i,\text{end}}, \text{fit\_end}) - \max(c_{i,\text{start}}, \text{fit\_start}))$$
- Coverage liczone jest względem sumy rzeczywistych długości klipów:
  $$\text{coverage} = \frac{\text{total\_overlap}}{\sum_{i} \text{clip\_durations}_i}$$
- Przerwa między klipami (22 minuty bez nagrywania) nie jest wliczana do mianownika i nie obniża coverage.

### Wyniki Retestu (Real Project)
Zestaw plików:
- `D:/GoPro/2026-08-31/GX010239.MP4`
- `D:/GoPro/2026-08-31/GX010240.MP4`
- `D:/GoPro/2026-08-31/Popołudniowa_jazda_na_rowerze.fit`

Pomiary:
```text
clip1 start:            2026-08-31 13:03:35.299 UTC
clip1 real duration:    186.053 s
clip1 end:              2026-08-31 13:06:41.352 UTC

clip2 start:            2026-08-31 13:33:08.200 UTC
clip2 real duration:    1632.431 s
clip2 end:              2026-08-31 14:00:20.631 UTC

sum real clip duration: 1818.483 s

FIT start/end:           2026-08-31 13:03:33 UTC / 2026-08-31 14:00:19.909 UTC (dur: 3406.909 s)

real overlap:            1817.762 s (186.053 s z klipu 1 + 1631.709 s z klipu 2)
coverage:                0.99960 (99.96%)
selected FIT:            Popołudniowa_jazda_na_rowerze.fit
confidence:              exact
```

---

## 3. REGRESYJNY FIX — UNBOUNDLOCALERROR W PROJECT_MIXIN.PY

### Root Cause
W `ProjectMixin._on_files_selected(self, video_paths, gpx_path, fit_path)` funkcja `bg_load()` dziedziczyła argumenty closure. Wewnątrz `bg_load()` dodano przypisanie:
```python
fit_path = str(matched_fit)
```
Zgodnie z semantyką kompilacji Pythona, obecność instrukcji przypisania do nazwy wewnątrz funkcji sprawia, że Python traktuje ją jako zmienną lokalną (`co_varnames`) w całym ciele funkcji. W rezultacie wcześniejsze sprawdzenie:
```python
if not fit_path and not gpx_path and self.video_paths:
```
zgłaszało `UnboundLocalError: cannot access local variable 'fit_path' where it is not associated with a value`.

### Naprawa
Na początku `bg_load()` skopiowano parametry do zmiennych lokalnych:
```python
effective_fit_path = fit_path
effective_gpx_path = gpx_path
```
i konsekwentnie użyto ich w całym procesie wczytywania:
- Auto-FIT aktualizuje `effective_fit_path = str(matched_fit)` oraz `self.fit_path = Path(effective_fit_path)`.
- MapPreload preparsuje `effective_fit_path` / `effective_gpx_path`.
- Wczytywanie telemetryczne (`load_fit`, `load_gpx`) i rejestracja pól w GUI korzysta wyłącznie z `effective_*`.

---

## 4. TESTY AUTOMATYCZNE

Wykonano testy jednostkowe i integracyjne:
1. `tests/test_activity_ux_timeline.py` (17 testów):
   - `test_5min_rounding`: test zaokrąglania do 5 min z obsługą północy (23:58 $\to$ 00:00).
   - `test_summer_and_winter_dst_local_time`: weryfikacja automatycznej konwersji UTC $\to$ local dla lata (15:05) i zimy (14:05) — brak stałego UTC+2.
   - `test_fit_activity_timezone_offset_priority`: pierwszeństwo offsetu z pliku FIT nad systemem.
   - `test_project_timezone_offset_priority`: pierwszeństwo offsetu projektu/aplikacji.
   - `test_collision_handling`: generowanie `-01`, `-02`.
   - `test_multi_clip_real_duration_and_gap_isolation`: scoring wieloplikowy, ignorowanie przerw między klipami, mianownik równy sumie clip durations.
   - `test_degraded_fallback_flag`: oznaczenie `confidence = degraded` przy awaryjnym braku duration.
   - `test_effective_fit_path_precedence_and_safety`: hierarchia manual FIT/GPX $\to$ AutoFIT $\to$ no-crash fallback.
   - `test_project_mixin_bg_load_has_no_unbound_local`: weryfikacja tablicy symboli (`co_varnames`) funkcji `bg_load()` — `fit_path` nie występuje w zmiennych lokalnych, co uniemożliwia wystąpienie `UnboundLocalError`.
   - Wszystkie 17 testów zaliczone (`OK` w 0.44 s).
2. Regresyjne testy modułów:
   - `tests/test_fast_telemetry_materialization.py`: 7/7 PASSED
   - `tests/test_tmpc_native_and_cache.py`: 5/5 PASSED
   - `tests/test_solar_bar_title_clean.py`: 3/3 PASSED
   - `tests/test_render_no_legacy_json.py`: 3/3 PASSED

---

## 5. PODSUMOWANIE FINALNE

```text
EXPORT LOCAL TIME: PASS
AUTO FIT REAL DURATION: PASS
ACTIVITY UX FINAL: PASS
```

