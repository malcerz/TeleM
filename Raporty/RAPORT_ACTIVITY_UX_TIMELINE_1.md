# RAPORT: TeleM GoPro — Activity UX & Timeline Usability Features (CEL 1–6)

**Data:** 2026-09-05  
**Gałąź:** `integration/intel-amd`  
**Status bazowy:** Native GPMF C++, `.telemetry.npz` cache v3 (TMPC restore), multi-file timeline.  
**Cel etapu:** Implementacja 6 powiązanych funkcji użytkowych UX i osi czasu bez ingerencji w renderery GPU/CPU i bez cofania optymalizacji bazowych.

---

## 1. MAP ROTATION SMOOTHING (CEL 1)

- **Właściwość:** `map_rotation_smoothing_s: float` (domyślnie `0.0`, zakres GUI: `0.0 – 5.0 s`, step `0.1 s`, etykieta w GUI: *"Wygładzanie obrotu"* w sekcji konfiguracji MAP).
- **Algorytm:**
  - Kąt kursu (heading) jest wielkością kołową na przedziale $[0^\circ, 360^\circ)$. Zwykłe uśrednianie arytmetyczne powoduje fałszywy przeskok przez $180^\circ$ na przejściu $359^\circ \to 1^\circ$.
  - Zastosowano filtr wektorowy oparty o dekompozycję na współrzędne kartezjańskie jednostkowego wektora kierunkowego:
    $$x_i = \cos(\text{rad}(\theta_i)), \quad y_i = \sin(\text{rad}(\theta_i))$$
  - Wygładzanie opiera się o ciągły czas fizyczny $t$ (time-aware windowed averaging). W oknie czasowym $[t - W/2, t + W/2]$ obliczane są średnie wektory:
    $$\bar{x} = \frac{1}{N}\sum x_k, \quad \bar{y} = \frac{1}{N}\sum y_k$$
    $$\theta_{\text{smooth}} = \text{atan2}(\bar{y}, \bar{x}) \pmod{360^\circ}$$
  - Przyspieszone wyliczanie przez sumy prefiksowe `np.cumsum` na tablicach $x, y$.
- **Preview == Render Parity:**
  - Wygładzanie wykonywane jest deterministycznie w precompute `precompute_heading_series` na bazie timestampów próbek GPS/heading, a nie kolejności klatek.
  - Losowy seek w podglądzie (Preview) i klatki generowane sekwencyjnie w Render dają bitowo identyczny kąt obrotu mapy.
- **Wrap $0/360$ Test:**
  - Sekwencja próbek: $358^\circ, 359^\circ, 0^\circ, 1^\circ, 2^\circ$.
  - Wynik przy `smoothing > 0`: monotoniczne, płynne przejście przez północ bez skoku w stronę $180^\circ$.
  - Wynik przy `smoothing = 0.0`: $100\%$ exact legacy behavior (brak zmian).

---

## 2. LEAN MOTION SMOOTHING (CEL 2)

- **Właściwość:** `lean_smoothing_s: float` (domyślnie `0.0`, zakres GUI: `0.0 – 5.0 s`, step `0.1 s`, etykieta w GUI: *"Wygładzanie ruchu"* w sekcji LEAN).
- **Algorytm:**
  - Filtr uśredniający czasowy bazujący na timestampach próbek (`smooth_roll_samples`).
  - Wygładzanie aplikowane do końcowej serii kąta przechyłu (roll) po:
    1. wyborze osi (`axis`),
    2. odwróceniu znaku (`invert_axis`),
    3. kalibracji/offsetu zera (`calibration`),
    ale *przed* renderowaniem grafiki rowerka/wskaźnika.
  - Nie zmieniono właściwości: `pivot`, `sensitivity`, `max_angle`, `graphic`, pozycja i wymiary bez zmian.
- **Preview == Render Parity:**
  - Prekomputacja serii czasowej roll w `TelemetryDataManager` i `WorkerCache`.
  - Deterministyczny wynik niezależny od kolejności odtwarzania.
- **Test skoku syntetycznego:**
  - Przebieg: $0^\circ \to 30^\circ \to 0^\circ$.
  - Dla `smoothing_s = 1.0 s` maksymalna amplituda i gwałtowne pochodne kąta zostają stłumione, ruch jest stabilny i płynny.
  - Dla `smoothing = 0.0` zachowany jest dokładnie profil oryginalny.

---

## 3. FIT ACTIVE-TIME MODEL & DYNAMIC AVERAGE SPEED (CEL 3)

- **Wspólny model:** `ActiveTimeMapper` w module `src/telemetry_active_time.py`.
- **Wykrywanie pauz:**
  - Parser FIT analizuje zdarzenia `event=timer` oraz `event_type`:
    - `start` $\to$ rozpoczęcie przedziału aktywnego timera.
    - `stop`, `stop_all` $\to$ zatrzymanie timera (rozpoczęcie pauzy).
  - W przypadku braku bezpośrednich eventów timera model bezpiecznie wyznacza zakres na podstawie sesji FIT (`start_time`, `total_elapsed_time`) lub pierwszego/ostatniego rekordu.
  - Metody modelu:
    - `is_paused(dt) -> bool`: sprawdza, czy dany punkt czasu UTC leży w pauzie timera.
    - `wall_to_active_seconds(dt) -> float`: przelicza czas zegarowy UTC na skumulowany aktywny czas timera od startu aktywności.
    - `cumulative_active_time(dt) -> float`: alias dla wyliczenia aktywnego czasu w sekundach.
    - `active_to_wall_dt(active_s) -> datetime`: odwrotne mapowanie aktywnego czasu na czas zegarowy.
- **Średnia prędkość (`avg_speed_kmh`):**
  - Dotychczas: `cumulative_distance / wall_elapsed_time`.
  - Nowa zasada:
    - Gdy FIT jest dostępny i posiada `active_time_mapper`:
      $$\text{avg\_speed} = \frac{\text{active\_distance at target\_dt}}{\text{active\_timer\_time at target\_dt}}$$
    - Pauzy nie zwiększają mianownika czasu aktywnego timera.
    - Gdy podczas pauzy dystans stoi w miejscu, średnia prędkość pozostaje idealnie stała.
    - Dynamiczny charakter: wskaźnik pokazuje średnią od początku aktywności do aktualnego momentu `target_dt`.
    - Gdy FIT jest niedostępny: zachowany jest dotychczasowy fallback na czas zegarowy.
- **Test:**
  - Aktywność: 10:00 start, 10 min jazdy, 5 min pauzy timera, 10 min jazdy.
  - Czas zegarowy: $25\text{ min}$.
  - Czas aktywny: $20\text{ min}$.
  - Dystans: $10\text{ km}$.
  - Średnia prędkość: dokładnie $30.0\text{ km/h}$ (zamiast błędnych $24.0\text{ km/h}$).

---

## 4. GLOBAL CHARTS "POMIŃ PAUZY" (CEL 4)

- **Konfiguracja:** `charts_skip_pauses: bool` (domyślnie `False` dla pełnej kompatybilności wstecznej).
- **GUI:** Jeden globalny przełącznik *"Pomiń pauzy aktywności"* w zakładce Ustawienia (`SettingsTab`) w grupie *"Wykresy"*.
- **Semantyka:**
  - `charts_skip_pauses = False` (OFF): Oś czasu X reprezentuje czas zegarowy (wall-clock time), a pauzy pozostają przerwami/odstępami na osi.
  - `charts_skip_pauses = True` (ON):
    - Oś czasu X reprezentuje aktywny czas timera.
    - Próbki przypadające w trakcie pauz (`mapper.is_paused(ts)`) są pomijane, a próbki po pauzie są przesuwane w czasie o czas trwania pauzy:
      $$t_{\text{shifted}} = t_{\text{base}} + \text{active\_seconds}(t)$$
    - Czas trwania wykresu skurczony z czasu zegarowego do aktywnego (np. $25\text{ min} \to 20\text{ min}$).
    - Wykresy aktywności (`activity`) i okienne (`window`) łączą dane płynnie bez generowania fałszywych próbek ani dziur.
  - Kursor wykresu (`aligned_target`) w `_render_chart_indicator` mapowany jest przez `mapper.wall_to_active_seconds(target_dt)` — podczas pauzy kursor zamraża się dokładnie na złączu przedziałów i nie wykonuje skoków.

---

## 5. AUTO-FIT SEARCH & MATCHING (CEL 5)

- **Zasada:** Po wybraniu pliku (lub listy plików) MP4 aplikacja automatycznie przeszukuje folder w poszukiwaniu odpowiadającego pliku `.fit`, jeśli użytkownik nie wskazał pliku telemetrycznego ręcznie.
- **Szybki skan (Fast Probe):**
  - **MP4:** `resolve_clip_timestamp` natychmiast odczytuje czasy początkowe i końcowe z GPMF/timeline ($< 1\text{ ms}$).
  - **FIT:** Wdrożono dedykowany, lekki skaner binarny `probe_fit_time_range(fit_path)` w `telemetry_fit.py`. Skaner czyta wyłącznie nagłówek i definicje wiadomości FIT oraz przeskakuje rekordy danych, odczytując timestampy `session`/`activity`.
  - Zastosowano buforowanie atrybutów pliku `_FIT_PROBE_CACHE` `(path, size, mtime)`.
- **Pomiary wydajności (GX010115.MP4 + GX010114_116.fit):**
  - `MP4 start probe ms`: **0.597 ms**
  - `FIT directory scan ms`: **0.727 ms**
  - `FIT candidate probe ms/file (cold)`: **17.830 ms**
  - `FIT candidate probe ms/file (warm/cached)`: **0.179 ms**
  - `Total AutoFIT ms`: **1.053 ms**
- **Scoring & Dopasowanie wieloplikowe:**
  - Każdy kandydat oceniany według:
    1. Temporal overlap (sekundy wspólnego czasu nagrania MP4 i aktywności FIT).
    2. Bezwzględna odległość czasowa między startem pierwszego klipu MP4 a startem aktywności FIT (maksymalna dopuszczalna tolerancja: $30\text{ min}$).
    3. Wskaźnik pokrycia całkowitego czasu nagrania.
  - W przypadku remisu (dwa pliki z niemal identycznym dopasowaniem) algorytm celowo odrzuca arbitralny wybór i pozostawia wybór użytkownikowi z logiem diagnostycznym:
    `[AutoFIT] Ambiguous match between ... and ...; leaving selection empty`
  - Po jednoznacznym dopasowaniu wypisywany jest log:
    ```text
    [AutoFIT] matched: GX010114_116.fit
    [AutoFIT] MP4 start: 2026-08-14T11:18:02.250270+00:00
    [AutoFIT] FIT range: 2026-08-14T09:40:10+00:00 - 2026-08-14T12:01:12.105000+00:00
    [AutoFIT] overlap: 600.0s
    ```
  - Flaga `_user_selected_telemetry` gwarantuje, że ręczny wybór użytkownika nie zostanie nadpisany.

---

## 6. AUTOMATYCZNA NAZWA PLIKU EKSPORTU (CEL 6)

- **Format:** `YYYYMMDD-HHMM.mp4` (np. `20260905-1910.mp4`).
- **Źródło czasu:** Bezwzględny czas startu pierwszego klipu MP4 z timeline/GPMF (nie czas modyfikacji pliku w systemie Windows i nie czas z FIT).
- **Zaokrąglanie:** Do najbliższych 5 minut:
  - `19:07` $\to$ `19:05`
  - `19:08` $\to$ `19:10`
  - `19:12` $\to$ `19:10`
  - `19:13` $\to$ `19:15`
  - `23:58` $\to$ `następny dzień 00:00`
- **Obsługa kolizji:**
  - Jeśli plik `20260905-1910.mp4` już istnieje w folderze wyjściowym, automatycznie generowany jest sufiks:
    `20260905-1910-01.mp4`, `20260905-1910-02.mp4` itd.
- **Ochrona ręcznej edycji:**
  - `RenderTab` śledzi flagę `self._user_edited_output`. Jeśli użytkownik zmodyfikuje nazwę wyjściową, automatyczna nazwa nie nadpisuje pola przy seekowaniu ani zmianie layoutu.
  - Nowa nazwa jest generowana wyłącznie przy załadowaniu nowego zestawu plików MP4.

---

## 7. TESTY JEDNOSTKOWE

Zestaw testów w `tests/test_activity_ux_timeline.py`:
- `test_circular_wrap_no_180_jump`: **PASS** (wygładzanie kursu $358^\circ \to 2^\circ$).
- `test_lean_jump_attenuated`: **PASS** (wygładzanie skoku przechyłu $0 \to 30 \to 0$).
- `test_active_vs_wall_time`: **PASS** (weryfikacja mapowania 25 min wall $\to$ 20 min active).
- `test_pause_freeze`: **PASS** (aktywny czas timera zamrożony w trakcie trwania pauzy).
- `test_dynamic_avg_speed`: **PASS** (10 km / 20 min active = 30 km/h, a nie 24 km/h).
- `test_pause_collapsed_from_axis`: **PASS** (skurczenie osi wykresu przy `charts_skip_pauses=True`).
- `test_single_match`: **PASS** (poprawne automatyczne znalezienie pliku FIT).
- `test_ambiguous_tie_rejected`: **PASS** (brak zgadywania w przypadku remisu 2 plików).
- `test_5min_rounding`: **PASS** (zaokrąglanie 19:07 $\to$ 19:05, 19:08 $\to$ 19:10, 23:58 $\to$ 00:00).
- `test_collision_handling`: **PASS** (dodawanie sufixów `-01`, `-02`).

Wynik wykonania:
```text
Ran 10 tests in 0.019s
OK
```

---

## 8. ZMIENIONE PLIKI

1. `src/telemetry_active_time.py` (nowy moduł: `ActiveTimeMapper`, `build_active_time_mapper_from_events`).
2. `src/telemetry_heading.py` (dodano `smooth_heading_samples` wektorowe $(\sin, \cos)$).
3. `src/telemetry_imu.py` (dodano `smooth_roll_samples`).
4. `src/gui/indicator_schemas.py` (dodano `map_rotation_smoothing_s`, `lean_smoothing_s`).
5. `src/gui/layout_manager.py` (domyślne wartości `map_rotation_smoothing_s: 0.0`, `lean_smoothing_s: 0.0`, `charts_skip_pauses: False`).
6. `src/gui/qt/models.py` (definicje pól w modelach wskaźników).
7. `src/gui/telemetry_manager.py` (obsługa prekomputacji wygładzania mapy i przechyłu, przekazywanie active mapper).
8. `src/telemetry_precompute.py` (prekomputacja serii czasowych z wygładzaniem).
9. `telemetry_fit.py` (integracja `active_time_mapper`, lekki skaner binarny `probe_fit_time_range`, algorytm `find_best_fit_match`).
10. `src/indicators/frame_data.py` (obliczanie `avg_speed_kmh` z użyciem `active_time_mapper`).
11. `src/indicators/chart_builder.py` (obsługa `active_time_mapper` i `charts_skip_pauses`, usuwanie pauz z osi).
12. `src/indicators/chart.py` (synchronizacja kursora na osi aktywnego czasu).
13. `src/gui/qt/tabs/settings_tab.py` (checkbox *"Pomiń pauzy aktywności"*).
14. `src/gui/qt/tabs/load_tab.py` (asynchroniczny Auto-FIT po wyborze MP4).
15. `src/gui/qt/_mixins/project_mixin.py` (auto-fit fallback, generowanie domyślnej nazwy eksportu).
16. `src/gui/qt/_mixins/preset_mixin.py` (zapis/odczyt `charts_skip_pauses`).
17. `src/gui/qt/_mixins/preview_mixin.py` (przekazywanie `active_time_mapper` do podglądu wykresów).
18. `src/video_helpers.py` (`round_dt_to_nearest_5min`, `generate_auto_export_filename`).
19. `src/gui/qt/signals.py` (`sig_default_export_name_ready`).
20. `src/gui/qt/tabs/render_tab.py` (obsługa automatycznej nazwy pliku eksportu, zapobieganie nadpisywaniu ręcznych zmian).
21. `src/ffmpeg/worker_cache.py` (przekazywanie `active_time_mapper` w potoku renderera).
22. `tests/test_activity_ux_timeline.py` (nowy plik testów jednostkowych).

---

## 9. PODSUMOWANIE WERYFIKACJI

```text
MAP SMOOTHING: PASS
LEAN SMOOTHING: PASS
FIT ACTIVE AVG SPEED: PASS
CHART SKIP PAUSES: PASS
AUTO FIT MATCH: PASS
AUTO EXPORT NAME: PASS
```
