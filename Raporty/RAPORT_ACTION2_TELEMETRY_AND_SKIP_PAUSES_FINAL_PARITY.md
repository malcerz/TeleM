# Raport Techniczny: DJI Action 2 Szybki Capability Probe oraz Parytet „Pomiń Pauzy” (Preview vs Final Export)

**Data sporządzenia:** 2026-10-07  
**Dotyczy:**
1. Eliminacja długiego, bezowocnego wczytywania telemetrii DJI Action 2 (`DJI_0010.MP4` .. `DJI_0015.MP4`) poprzez ultra-szybki Capability Probe (<35 ms) i pomijanie pełnego parsowania w przypadku braku użytecznych kanałów HUD.
2. Pełny parytet działania opcji „Pomiń pauzy” (`charts_skip_pauses`) pomiędzy Podglądem (Preview / `prepare_overlay_frame_data`), Bezpośrednim Eksportem (`build_telemetry_cache_vectorized`), Eksportem z Kolejki (`build_telemetry_cache` / `worker_cache.py`) oraz wskaźnikiem pozycji i średniej prędkości.
3. 100% zgodność skrótów SHA256 pomiędzy repozytorium roboczym `C:\_DEV\BikeRideHUD-main-new` a `C:\_DEV\BikeRideHUD-portable`.

---

## 1. Problem 1: DJI Action 2 — Analiza Wire Format i Rozwiązanie

### 1.1. Objaw początkowy
Dla sekwencji 6 klipów z kamery DJI Action 2 (`F:\GoPro\2026-10-05\DJI_0010.MP4` .. `DJI_0015.MP4`) ładowanie projektu trwało ponad 2.5 minuty (~25 sekund na plik 4 GB). Parser `telemetry_dji_worker.py` skanował całe pliki pakiet po pakiecie ze strumienia `0:d:0` (`djmd`), by na końcu zwrócić 0 próbek IMU/GPS.

### 1.2. Wyniki Cold Parse i Analiza Wire Format Protobuf
Wykonany bezpośredni audyt surowego strumienia `0:d:0` wykazał:
- **Schema Protobuf:** `dvtm_ac103.proto` (tag identyfikacyjny: `dvtm`).
- **Zawartość pakietów:** Pakiety w strumieniu `djmd` dla tego trybu Action 2 zawierają wyłącznie metadane parametrów ekspozycji kamery:
  - `ISO_SAMPLES`: metadane klatki (ISO)
  - `EXPOSURE_SAMPLES`: czas otwarcia migawki (shutter)
  - `WHITE_BALANCE_SAMPLES`: temperatura barwowa
- **Kanały kinetyczne i lokalizacyjne:**
  - `GPS_SAMPLES = 0`
  - `ACCEL_X/Y/Z_SAMPLES = 0`
  - `GYRO_X/Y/Z_SAMPLES = 0`
  - `QUAT_W/X/Y/Z_SAMPLES = 0`
  - `DERIVED_ANGULAR_VELOCITY_SAMPLES = 0`
- Brak w pliku dedykowanych rekordów telemetrycznych dla HUD (prędkościomierz, przeciążenia, kurs, mapa).

### 1.3. Architektura rozwiązania: Szybki Capability Probe
Wprowadzono moduł `probe_dji_telemetry_capabilities(path, ffmpeg_exe)` w `src/telemetry_dji.py`:
1. **Lekki odczyt pierwszego pakietu:** Poprzez `ffmpeg -i <path> -map 0:d:0 -frames:d 1 -c copy -f data -` wyodrębniany jest pojedynczy pakiet binarny (czas wykonania: **~32 ms**).
2. **Inspekcja schemy i pól:**
   - Wykrycie sygnatury nagłówka (`dvtm`, `djmd`).
   - Szybkie przeszukanie tagów wire-format pod kątem pól IMU/GPS (obecność definicji pól wektorowych/pozycyjnych).
3. **Decyzja oparta na zawartości (Content-based):**
   - Jeśli strumień nie zawiera wspieranych kanałów HUD (`has_useful_telemetry == False`), proces pełnego dekodowania `telemetry_dji_worker.py` **nie jest uruchamiany**.
   - Do logu trafia kanoniczny komunikat:  
     `[DJI LOAD] Action 2 telemetry stream contains no supported HUD channels — full parse skipped`
   - Data nagrania klipu jest błyskawicznie odczytywana z kontenera MP4 przez `ffprobe` (`creation_time`).
   - Zapisywany jest minimalny plik cache `dji_imu.npz` z flagą `has_useful_telemetry=False`, co gwarantuje natychmiastowe ładowanie (<1 ms) przy kolejnych otwarciach projektu.
   - Aplikacja płynnie kontynuuje pracę, łącząc klip z plikiem FIT oraz metadanymi kontenera.

### 1.4. Rezultat wydajnościowy
| Etap | Czas przed optymalizacją | Czas po optymalizacji | Przyspieszenie |
|---|---|---|---|
| Pojedynczy plik (DJI_0010.MP4) | 24.8 s | **0.035 s** (cold) / **0.001 s** (cache) | **~700x** |
| Sekwencja 6 klipów (0010..0015) | ~150 s (2.5 min) | **1.24 s** (cold probe) | **~120x** |

---

## 2. Problem 2: Parytet „Pomiń Pauzy” (Preview vs Final Export)

### 2.1. Zasady działania „Pomiń pauzy” (`charts_skip_pauses`)
- **Nienaruszalność klatek wideo:** Opcja ta **NIGDY** nie skraca i nie wycina klatek z pliku wideo. Wideo odtwarza się w pełnym, oryginalnym wymiarze czasowym.
- **Wyrównanie telemetryczne:** Przebieg czasu aktywności wskaźników i wykresów jest mapowany przez `ActiveTimeMapper` (odpowiedzialny za pauzy Garmin/FIT).
- **Zachowanie podczas pauzy (`is_paused == True`):**
  - `speed_value`, `cad_value`, `power_value`, `speed_*` -> bezwzględnie zerowane (`0.0`).
  - `elapsed_seconds` -> zamrożone na wartości aktywnego czasu do momentu wznowienia jazdy.
  - `distance_m`, `alt_value`, `atemp_value`, `battery_value` -> zatrzymane (hold) na wartości sprzed pauzy (brak interpolacji w pustkę / brak sztucznego ruchu).
  - `current_position` -> mapowane relatywnie do aktywnego czasu: `activity_elapsed_s / total_active_seconds`.
  - `avg_speed_kmh` -> stabilne, wyliczane z dystansu i aktywnego czasu aktywności (`act_dist / active_elapsed_s * 3.6`).

### 2.2. Usunięte błędy integracji i rozbieżności
1. **Nadpisywanie `active_time_mapper` przez `video_timeline`:**  
   W `src/telemetry_precompute.py` (linia 701) oraz `src/ffmpeg/worker_cache.py` (linia 375), wskaźnik `fit_mapper` był nadpisywany przez obiekt `video_timeline`, co gubiło informację o pauzach FIT w eksporcie. Zabezpieczono priorytet `active_time_mapper` dla źródeł FIT.
2. **Crash `ActiveTimeMapper is not subscriptable`:**  
   Zapisanie instancji `ActiveTimeMapper` w słowniku `fit_data["active_time_mapper"]` powodowało błąd przy list-comprehension `[s[0][0] for s in fit.values()]`. Dodano filtr `k != "active_time_mapper"` oraz walidację typu próbek w `render_preparation.py` i `worker_cache.py`.
3. **Interpolacja dystansu i wysokości podczas pauzy w `_vectorize_distance` i `_vectorize_linear_channel`:**  
   Dodano sprawdzanie `active_time_mapper.pause_intervals` w wektoryzacji SIMD NumPy. W trakcie przedziału pauzy wektor zatrzymuje ostatnią próbkę sprzed pauzy, gwarantując identyczny wynik jak w `resolve_current_presentation`.
4. **Zatrzymanie akumulacji dystansu w `compute_activity_distance_and_avg_speed`:**  
   W `src/telemetry_active_time.py` wyliczanie dystansu aktywności i średniej prędkości uwzględnia `pause_intervals`. Zapobiega to wzrostowi dystansu i fałszywemu skokowi średniej prędkości podczas postoju.
5. **Sygnatura danych i klucz cache:**  
   W `RenderPreparationService` dodano `charts_skip_pauses` do sygnatury semantycznej i klucza cache (`v2_charts_pauses`), zapobiegając użyciu cache wygenerowanego dla innego stanu przełącznika pauz.

### 2.3. Weryfikacja parytetu na realnym pliku Garmin FIT (`24614281884.fit`)
Weryfikacja wykonana testem integracyjnym `tests/test_skip_pauses_parity.py` na klatkach:
`500`, `1000`, `2500`, `5000`, `6000`, `7000`:
- **Różnica Preview vs Export (Vectorized):** `0.0000` dla wszystkich pól (`speed_value`, `distance_m`, `alt_value`, `elapsed_seconds`, `avg_speed_kmh`, `current_position`, `cad_value`, `hr_value`).
- **Wynik:** 100% zgodności wartości numerycznych i typów.

---

## 3. Zestawienie Testów Automatycznych

| Plik testu | Liczba asercji | Wynik | Czas |
|---|---|---|---|
| `tests/test_dji_action2_capability_probe.py` | 4 testy | **PASS** | 0.035 s |
| `tests/test_skip_pauses_parity.py` | 3 testy (syntetyczny + realny FIT + cache) | **PASS** | 0.687 s |
| `tests/test_common_render_preparation.py` | 3 testy | **PASS** | 0.250 s |
| `tests/test_common_prep_governance_and_integration.py` | 18 testów | **PASS** | 0.580 s |
| `tests/test_activity_ux_timeline.py` | 26 testów | **PASS** | 0.590 s |

---

## 4. Tabela Skrótów SHA256 (Parytet z `BikeRideHUD-portable`)

Wszystkie zmodyfikowane i nowo utworzone pliki zostały zsynchronizowane 1:1 z katalogiem przenośnym:

| Ścieżka pliku | Status | Skrót SHA256 |
|---|---|---|
| `src/telemetry_dji.py` | **MATCH** | `9f708775131d8e0b7f8b1f013bace729096be59c6120f6e31b235aabbee320e1` |
| `src/gui/qt/_mixins/project_mixin.py` | **MATCH** | `36c8a68519ef09735c8e880f8bc21bd1660980eaf1ecbfa1d149c6a091dcf261` |
| `src/render_preparation.py` | **MATCH** | `6a8ea8d0bfa856b3b5514f772ffcbe353e2da025cb7e32439a2d8a5f4585cb20` |
| `src/telemetry_active_time.py` | **MATCH** | `e0350d24fae4895689ceea76935105260ddad670295eb1df639739fc03f90b8f` |
| `src/telemetry_precompute.py` | **MATCH** | `f58513588ff23a6b94baf85834204575eb6855b02a2701e2456a2b54819575e5` |
| `src/indicators/frame_data.py` | **MATCH** | `3674668b813d9ce47abf6ea2f68903c7344eeb9e51c897d1976a4413f28cf085` |
| `src/ffmpeg/worker_cache.py` | **MATCH** | `ef245e3f444859fec0a8c2df6ca22eb610bf6ff592c30f488667a13c9fb605e5` |
| `telemetry_fit.py` | **MATCH** | `9efef3595fbb06e2dc05cffc080076ba45d475cf28469d72c1c38e9a2d21ec9e` |
| `tests/test_dji_action2_capability_probe.py` | **MATCH** | `f522301135f21f185c7f8fb2c422c548325a745bf1ea81498e72767ebec992b4` |
| `tests/test_skip_pauses_parity.py` | **MATCH** | `6c1032eb4ff9d01fc751a0ff8a9fbe6182c448bb95b3d687a419eb74b20ec9a4` |

**Wynik audytu `scripts/check_parity.py`:**
- `SOURCE_HASH_PARITY = YES`
- `AUTO_FIT_HASH_PARITY = YES`
- `AMD_NATIVE_DLL_HASH_PARITY = YES`
