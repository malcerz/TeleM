# RAPORT SPORTCAMHUD v1.14 — NAPRAWA METADANYCH I OPTYMALIZACJA WCZYTYWANIA

**Data:** 2026-10-11  
**Projekt:** SportCamHUD v1.14 (wcześniej BikeRideHUD / TeleM)  
**Środowisko:** Windows, AMD Radeon Graphics (D3D11 / AMF HEVC), Python 3.14  
**Gałąź:** `fix/gui-freeze-hud-composite`  
**Plik referencyjny:** `F:\GoPro\2026-10-09\GX010361.MP4` (8.60 GB, 3840×2160 @ 29.97 fps, HEVC Main 10 / HLG, 26:14, GPMF obecny)  

---

## 1. Przyczyna braku daty i modelu kamery w GUI

### Diagnoza:
1. **Ciche ignorowanie wyjątków (`except Exception: pass`):**  
   W `src/gui/qt/mp4_inspector.py` blok ekstrakcji metadanych GPMF był opleciony klauzulą `except Exception: pass`. Wszelkie błędy lub brakujące pola powodowały ciche wyczyszczenie słownika `gpmf_meta = {}`, skutkując wyświetleniem `"Data nagrania: Brak danych"` oraz `"Kamera: Brak danych"` w GUI (`VideoFileCardWidget`).
2. **Brak strefy czasowej i źródła daty:**  
   Formatowanie daty nie uwzględniało pełnej informacji o źródle danych (GPMF GPS) oraz przesunięciu lokalnej strefy czasowej (czas polski w październiku: UTC+2 / CEST).
3. **Generyczny model kamery w atomie MP4 (`GoPro`):**  
   Kamery GoPro (od HERO9 wzwyż) w strumieniu metadanych zwracają identyfikator bazowy `"GoPro"`. Dokładny wariant sprzętowy (`GoPro HERO13 Black`) znajduje się w tagu kontenera MP4 `firmware: H26.02.02.02.00`. Brakowało precyzyjnego mapowania prefiksów firmware (`H19` -> HERO9, `H21` -> HERO10, `H22` -> HERO11, `H23` -> HERO12, `H24` -> HERO11 Mini, `H26` -> HERO13).

### Rozwiązanie:
- Zastąpiono `except Exception: pass` jawnym logowaniem `logging.warning` i `print()` z opisem błędu.
- Wprowadzono słownik `GOPRO_FIRMWARE_MODELS` mapujący kody firmware na pełne nazwy kamer wraz z oznaczeniem źródła (np. `firmware H26.02.02.02.00`).
- Skonwertowano znacznik czasu `start_dt_utc = 1791520075.839021` na czas lokalny Windows (`2026-10-09 06:27:55`) wraz z informacją o strefie (`UTC+2`) i źródle (`GPMF (GPS)`).
- Zaktualizowano etykiety `VideoFileCardWidget` w GUI oraz tekst w `format_file_info_text()`.

---

## 2. Przyczyna wolnego wczytywania MP4

### Zidentyfikowane wąskie gardła (3 najkosztowniejsze operacje):
1. **Pełna ekstrakcja telemetrii w `auto_telemetry_preflight.py` (2383 ms):**  
   Wyszukiwanie AutoFIT wywoływało `extract_gpmf_native(video_paths[0])` w trybie pełnym (dekodowanie wszystkich 14 451 punktów GPS, akcelerometru, żyroskopu i temperatury na pliku 8.6 GB) wyłącznie po to, by odczytać pierwszą współrzędną `(lat, lon)` do oceny odległości.
2. **Legacy ekstrakcja GPMF przez FFmpeg i Python w `resolve_clip_timestamp()` (4058 ms):**  
   Gdy plik nie miał jeszcze cache czasu, `_resolve_from_gpmf()` w `src/multifile.py` uruchamiał proces `ffmpeg -map 0:3 -c copy` do pliku tymczasowego, a następnie powolny parser w czystym Pythonie `parse_gpmf(raw)`.
3. **Blokująca pętla 4.0 sekund w `load_tab.py:946`:**  
   Kliknięcie przycisku „Wczytaj” podczas trwania asynchronicznego preflightu AutoFIT wstrzymywało wątek GUI w pętli `while self._autofit_in_progress and time.time() < deadline: time.sleep(0.02)` na okres do 4 sekund.
4. **Ukryty błąd `NameError: name 'w' is not defined` w `project_mixin.py:725`:**  
   Pobieranie pierwszej klatki podglądu rzucało wyjątek z powodu niezdefiniowanych zmiennych `w` i `h`.

---

## 3. Lista usuniętych powtórnych operacji

1. **Wyeliminowano redundantne wywołanie `ffprobe`:**  
   W `inspect_mp4()` strumień GPMF jest teraz najpierw wykrywany bezpośrednio ze zwróconej już listy strumieni (`codec_name`, `codec_tag_string`, `handler_name`), bez ponownego uruchamiania osobnego procesu `ffprobe -show_streams`.
2. **Wyeliminowano pełne parsowanie GPMF dla AutoFIT:**  
   Zastąpiono pełne wywołanie `extract_gpmf_native()` lekkim odczytem `get_gpmf_light_metadata()` (`metadata_only=True`), który pobiera pierwszy punkt GPS i czas startu w 160 ms (cold) lub <0.2 ms (warm/cache).
3. **Wyeliminowano wywołania FFmpeg stream-copy w osi czasu:**  
   Funkcja `_resolve_from_gpmf()` w `src/multifile.py` najpierw odpytuje `get_gpmf_light_metadata()`, eliminując potrzebę zrzucania binarnego strumienia przez FFmpeg.
4. **Wyeliminowano 4-sekundowe blokowanie GUI przy kliknięciu „Wczytaj”:**  
   Usunięto pętlę oczekującą. Wczytywanie projektu startuje natychmiast, a ewentualnie odnaleziony w tle plik FIT jest podłączany dynamicznie przez sygnał `sig_late_telemetry_matched` bez przeładowywania wideo.
5. **Współdzielenie metadanych między modułami:**  
   Zarówno panel inspekcji wideo, AutoFIT, oś czasu multi-file, jak i kontroler projektu korzystają ze spójnego cache (`%LOCALAPPDATA%\SportCamHUD\cache\media\<key>\gpmf_light.json`) z weryfikacją fingerprintu (rozmiar pliku, mtime_ns).

---

## 4. Wyniki pomiarów BEFORE / AFTER (Plik 8.60 GB GX010361.MP4)

| Etap / Operacja | BEFORE (ms) | AFTER (ms) | Przyspieszenie |
| :--- | :---: | :---: | :---: |
| **Pojawienie się informacji o filmie (Cold Cache)** | 239.12 ms | **220.69 ms** | 1.1× |
| **Pojawienie się informacji o filmie (Warm Cache)** | 239.12 ms | **36.57 ms** | **6.5×** |
| **Odczyt metadanych GPMF (Warm Cache / In-Memory)** | 164.61 ms | **0.18 ms** | **900×** |
| **resolve_clip_timestamp() (bez cache sidecar)** | 4058.81 ms | **0.29 ms** | **14 000×** |
| **probe_clip_time_interval() (bez cache sidecar)** | 1228.13 ms | **38.00 ms** | **32×** |
| **Preflight AutoFIT (wyszukiwanie + GPS)** | 2383.96 ms | **41.21 ms** | **58×** |
| **Kliknięcie „Wczytaj” -> Gotowy projekt** | ~4100 ms (blokada) | **62.70 ms** | **65×** |
| **Liczba pełnych przebiegów dekodowania MP4** | 0 | **0 (ZERO)** | Zachowano |
| **Zużycie pamięci RAM (delta RSS)** | +240 MB | **+81.3 MB** | Zmniejszone 3× |

---

## 5. Wyniki harnessu testowego

Wykonano pełne testy jednostkowe kanonicznego harnessu projektu:

1. **`tests/test_v114_load_performance.py`** — **7/7 PASSED** (1.90s)
   - `test_firmware_mapping_accuracy`
   - `test_gpmf_light_metadata_flow`
   - `test_inspect_mp4_date_local_and_firmware_resolution`
   - `test_card_widget_ui_labels`
   - `test_non_blocking_load_click`
   - `test_late_attach_signal_emitted`
   - `test_multifile_resolver_uses_light_metadata`
2. **`tests/test_mp4_inspector.py`** — **21/21 PASSED** (3.19s)
3. **`tests/test_central_telemetry_cache.py`** — **13/13 PASSED** (0.66s)
4. **`tests/test_auto_telemetry_preflight_suite.py`** — **13/13 PASSED** (5.26s)
5. **`tests/test_multifile_timeline.py`** — **31/31 PASSED** (0.09s)
6. **`tests/test_multifile_etap3_clip_time.py`** — **23/23 PASSED** (0.11s)
7. **`tests/test_autofit_pre_load.py`** — **4/4 PASSED** (3.54s)
8. **`tests/test_load_tab_layout_action2.py`** — **5/5 PASSED** (3.28s)
9. **`tests/test_gpmf_native_perf_and_cache_clear.py`** — **9/9 PASSED** (0.65s)

**Łącznie:** 126 testów przeszło pomyślnie ze 100% wynikiem pozytywnym.

---

## 6. Potwierdzenie braku regresji FIT / GPMF i zachowania ograniczeń

- **Pipelines GPU / Audio / Live Mux:** Nienaruszone. Żadnego wyodrębniania audio, żadnego `audio_cache.m4a`, żadnego podwójnego dekodowania.
- **Synchronizacja FIT / GPMF:** Znacznik czasu `start_dt_utc = 1791520075.839021` pochodzi bezpośrednio z rekordów GPS9 z natywnego parsera C++ i jest w 100% identyczny jak przed optymalizacją.
- **Odpowiedź GUI:** Interfejs nie zawiesza się; wybór pliku MP4 wyświetla informacje natychmiast (36 ms warm / 220 ms cold), a wczytanie projektu następuje w 62 ms.
- **Late-attach FIT:** Jeśli użytkownik kliknie „Wczytaj” przed zakończeniem wyszukiwania online/lokalnego, dopasowany plik FIT jest podłączany asynchronicznie przez `late_attach_telemetry` bez przeładowywania podglądu wideo.

---

## 7. Zmodyfikowane pliki

- `src/gui/qt/mp4_inspector.py` — Dodano `GOPRO_FIRMWARE_MODELS`, optymalizację wykrywania GPMF bez dodatkowego ffprobe, obsługę `get_gpmf_light_metadata`, dokładne formatowanie czasu lokalnego i strefy UTC+2 oraz usunięto ciche połykanie błędów.
- `src/gui/qt/tabs/load_tab.py` — Rozszerzono `VideoFileCardWidget.update_info()` o prezentację źródła i strefy, usunięto 4-sekundową pętlę blokującą w `_on_load()`, dodano emisję `sig_late_telemetry_matched` w `_on_autofit_matched`.
- `src/telemetry_native_gpmf.py` — Dodano `get_gpmf_light_metadata()` z dwupoziomowym cache (pamięciowy + centralny w AppData) i weryfikacją fingerprintu (rozmiar, mtime_ns).
- `src/telemetry_cache_manager.py` — Dodano ścieżki cache `gpmf_light.json` i `gpmf_light.meta.json`.
- `src/integrations/auto_telemetry_preflight.py` — Zastąpiono pełne parsowanie GPMF wywołaniem `get_gpmf_light_metadata()`, naprawiono zmienną `best_score` oraz komunikaty statusu przy wyłączonym źródle online.
- `src/multifile.py` — Wprowadzono szybką ścieżkę w `_resolve_from_gpmf()` wykorzystującą `get_gpmf_light_metadata()`.
- `src/gui/qt/_mixins/project_mixin.py` — Naprawiono `NameError: name 'w' is not defined` przy obliczaniu wysokości ramki podglądu.
- `tests/test_v114_load_performance.py` — Nowy kanoniczny zestaw testów regresji i wydajności.

---

## 8. Stan Git i Commit

- Gałąź: `fix/gui-freeze-hud-composite`
- Gotowe do zacommitowania zgodnie z zasadami AGENTS.md.
