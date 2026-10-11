# RAPORT SPORTCAMHUD v1.14 — NAPRAWA METADANYCH, ARCHITEKTURA LATE-ATTACH I OPTYMALIZACJA WCZYTYWANIA

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

### Zidentyfikowane wąskie gardła:
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

## 4. Architektura cyklu życia AutoFIT i Late-Attach Telemetry

### Rozwiązane problemy regresji:
W wersji rozwojowej flaga `_loaded_once` nie była resetowana przy zmianie filmu ani czyszczeniu projektu, a we wcześniejszym commicie z `bg_load` przypadkowo usunięto przypisania `self.video_paths = ...` i `self.video_path = ...`, co powodowało ciche przerywanie `late_attach_telemetry`. Ponadto w `late_attach_telemetry` znajdowały się odwołania do nieistniejących sygnałów i metod.

### Pełna architektura cyklu życia:
1. **Ścisła izolacja generacji i ścieżek (`load_tab.py`):**
   - Wprowadzono zmienne stanu: `_loaded_paths: list[str] = []`, `_loaded_once: bool = False`, `_pending_late_fit: str = ""`, `_autofit_gen: int = 0`, `_autofit_target_paths: list[str] = []`.
   - Zmiana plików wideo w `set_video_paths()` lub czyszczenie w `_on_clear()` natychmiast:
     - anuluje trwający wątek AutoFIT przez `self._autofit_cancel_event.set()`,
     - inkrementuje licznik generacji `self._autofit_gen += 1`,
     - resetuje stan wczytania: `self._loaded_once = False`, `self._loaded_paths = []`, `self._pending_late_fit = ""`.
   - Dzięki temu plik FIT znaleziony dla Filmu A nigdy nie zostanie przypisany do Filmu B, nawet jeśli wątek tła dla Filmu A zakończy się z opóźnieniem.

2. **Obsługa 3 stanów czasowych znalezienia FIT:**
   - **Przed wczytaniem projektu (`not self._loading` i `not self._loaded_once`):** Ścieżka FIT jest zapisywana w `self._fit_path` i etykiecie przycisku; po kliknięciu „Wczytaj” przekazywana jest standardowo jako argument `sig_files_selected`.
   - **Podczas wczytywania projektu (`self._loading == True`):** Ścieżka FIT jest buforowana w `self._pending_late_fit`. Po osiągnięciu 100% postępu wczytywania w `_finish_loading_success()`, sygnał `sig_late_telemetry_matched` jest emitowany jednorazowo, gwarantując brak wyścigu wątków.
   - **Po zakończeniu wczytywania projektu (`self._loaded_once == True`):** Sygnał `sig_late_telemetry_matched` jest emitowany natychmiast do `AppController`.

3. **Bezpieczne dołączanie telemetrii w `AppController` (`project_mixin.py`):**
   - Przywrócono stan `self.video_paths` i `self.video_path` w `bg_load`.
   - Metoda `late_attach_telemetry(fit_path)`:
     - Weryfikuje istnienie wczytanego filmu i pliku FIT.
     - Wywołuje `self.telemetry.load_fit(fit_path)` bez naruszania zdekodowanych strumieni wideo.
     - Uruchamia preloading kafelków mapy (`self._start_map_preload()`).
     - Aktualizuje i emituje dostępne strumienie danych (`sig_data_streams_ready`).
     - Odświeża geometrię i warstwy wskaźników HUD (`refresh_preview_geometry_and_hud()`).
     - Wszystko odbywa się asynchronicznie, bez zamrażania GUI i bez ponownego dekodowania wideo.

---

## 5. Rzeczywiste pomiary wydajności ładowania (Plik 8.60 GB GX010361.MP4)

Pomiary wykonano za pomocą skryptu referencyjnego `scripts/benchmark_v114_load.py` na rzeczywistym pliku `F:\GoPro\2026-10-09\GX010361.MP4`.

Wcześniej raportowany czas **62.70 ms** dotyczył wyłącznie zwrócenia kontroli do pętli zdarzeń Qt w wątku GUI (kickoff / natychmiastowe odblokowanie GUI). Poniżej zestawiono rzeczywiste czasy wszystkich 4 etapów cyklu ładowania aż do pełnej gotowości projektu i wygenerowania kompozycji HUD:

### Szczegółowy podział na 4 etapy cyklu ładowania:

| Etap pomiaru | Zimny cache (Cold) | Ciepły cache (Warm) | Opis stanu |
| :--- | :---: | :---: | :--- |
| **1. Kliknięcie „Wczytaj” -> Rozpoczęcie operacji (kickoff)** | **0.96 ms** | **2.15 ms** | Natychmiastowe odblokowanie wątku GUI, brak blokujących pętli |
| **2. Kliknięcie „Wczytaj” -> Dane telemetrii gotowe** | **19 551.70 ms** (19.55 s) | **1 523.55 ms** (1.52 s) | Parsowanie GPMF / candidate range / budowa strumieni telemetrii |
| **3. Kliknięcie „Wczytaj” -> Pierwsza klatka podglądu** | **19 901.45 ms** (19.90 s) | **1 581.24 ms** (1.58 s) | Ekstrakcja ramki referencyjnej wideo do podglądu w GUI |
| **4. Kliknięcie „Wczytaj” -> Projekt gotowy (100% postępu)** | **19 904.23 ms** (19.90 s) | **1 583.89 ms** (1.58 s) | Złożenie HUD, inicjalizacja silnika podglądu, 100% gotowości |

### Porównanie operacji pomocniczych:

| Operacja | Stan pierwotny | Po optymalizacji | Przyspieszenie |
| :--- | :---: | :---: | :---: |
| **Pojawienie się karty filmu (Warm Cache)** | 239.12 ms | **36.57 ms** | **6.5×** |
| **Odczyt metadanych GPMF (In-Memory)** | 164.61 ms | **0.18 ms** | **900×** |
| **resolve_clip_timestamp() (bez sidecar)** | 4058.81 ms | **0.29 ms** | **14 000×** |
| **probe_clip_time_interval() (bez sidecar)** | 1228.13 ms | **38.00 ms** | **32×** |
| **Preflight AutoFIT (wyszukiwanie + GPS)** | 2383.96 ms | **41.21 ms** | **58×** |
| **Czas gotowości projektu (Warm Cache)** | ~4100 ms (blokada GUI) | **1.58 s** (asynchronicznie) | **2.6× szybszy rendering** |

---

## 6. Weryfikacja metadanych na pliku referencyjnym GX010361.MP4

Inspekcja rzeczywistego pliku nagrania `F:\GoPro\2026-10-09\GX010361.MP4` w karcie `VideoFileCardWidget`:

- **Data nagrania:** `2026-10-09 06:27:55`
- **Źródło daty:** `GPMF (GPS)`
- **Strefa czasowa:** `UTC+2` (czas polski letni / CEST, zgodny z ustawieniami systemu Windows)
- **Kamera:** `GoPro HERO13 Black`
- **Źródło modelu kamery:** `firmware H26.02.02.02.00`
- **Strumienie:** Wideo HEVC 3840×2160 @ 29.97 fps (HLG / BT.2020), Audio AAC Stereo 48 kHz, Dane GPMF obecne.

---

## 7. Wyniki kanonicznego harnessu testowego

Wykonano pełen zestaw testów we wszystkich 9 pakietach kanonicznych projektu:

```text
tests\test_v114_load_performance.py ............                         [  9%]
tests\test_mp4_inspector.py .....................                        [ 25%]
tests\test_central_telemetry_cache.py .............                      [ 35%]
tests\test_auto_telemetry_preflight_suite.py .............               [ 45%]
tests\test_multifile_timeline.py ...............................         [ 68%]
tests\test_multifile_etap3_clip_time.py .......................          [ 86%]
tests\test_autofit_pre_load.py ....                                      [ 89%]
tests\test_load_tab_layout_action2.py .....                              [ 93%]
tests\test_gpmf_native_perf_and_cache_clear.py .........                 [100%]

============================ 131 passed in 14.58s =============================
```

- **Zachowano 100% istniejących testów:** wszystkie 126 testów przechodzi bez żadnych zmian ani regresji.
- **Dodano 5 nowych testów regresyjnych late-attach i lifecycle:**
  1. `test_autofit_lifecycle_film_a_to_b` — weryfikacja izolacji generacji i uniemożliwienia przypisania FIT z filmu A do filmu B.
  2. `test_fit_found_during_loading_attached_on_success` — weryfikacja buforowania FIT w trakcie trwania ładowania i dołączenia po osiągnięciu 100%.
  3. `test_clear_resets_loaded_once_and_cancels_worker` — weryfikacja resetu stanu i anulowania wątku przy czyszczeniu projektu.
  4. `test_real_late_attach_telemetry_execution` — weryfikacja rzeczywistego wywołania `late_attach_telemetry()` na `AppController`, załadowania FIT i odświeżenia HUD.
  5. `test_gx010361_real_file_metadata_and_card_display` — weryfikacja metadanych na rzeczywistym pliku referencyjnym HERO13 Black.

Łącznie: **131 testów zakończonych sukcesem (100% PASSED)**.

---

## 8. Potwierdzenie twardych niezmienników (Hard Invariants)

- **Pipelines GPU / Audio / Live Mux:** Nienaruszone. Żadnego wyodrębniania audio, żadnego `audio_cache.m4a`, żadnego podwójnego dekodowania, żadnego osobnego przebiegu kopiowania strumieni.
- **Synchronizacja FIT / GPMF:** Znacznik czasu `start_dt_utc = 1791520075.839021` pochodzi bezpośrednio z rekordów GPS9 z natywnego parsera C++ i jest w 100% zgodny z pozycją czasową nagrania.
- **Odpowiedź GUI:** Interfejs nie ulega zamrożeniu; kliknięcie „Wczytaj” odblokowuje GUI w <2 ms, a proces ładowania raportuje postęp asynchronicznie.
- **Parzystość środowiska:** Wersja portable (`C:\_DEV\SportCamHUD-portable`) jest w 100% zsynchronizowana z głównym kodem.

---

## 9. Zmodyfikowane i dodane pliki

- `src/gui/qt/tabs/load_tab.py` — Dodano precyzyjną kontrolę cyklu życia (`_loaded_paths`, `_loaded_once`, `_pending_late_fit`, `_autofit_target_paths`), anulowanie i inkrementację generacji przy zmianie plików i czyszczeniu, buforowanie FIT mid-load i dynamiczne dołączanie late-attach.
- `src/gui/qt/_mixins/project_mixin.py` — Przywrócono stan `self.video_paths` i `self.video_path` w `bg_load`, naprawiono `NameError: name 'w' is not defined`, zaimplementowano bezpieczne `late_attach_telemetry()` z discovery strumieni i odświeżaniem HUD.
- `src/gui/qt/mp4_inspector.py` — Wprowadzono `GOPRO_FIRMWARE_MODELS`, eliminację redundantnego ffprobe, obsługę `get_gpmf_light_metadata`, dokładne formatowanie czasu lokalnego Windows (UTC+2) i źródła danych.
- `src/telemetry_native_gpmf.py` — Dodano dwupoziomowy szybki cache `get_gpmf_light_metadata()`.
- `src/telemetry_cache_manager.py` — Dodano obsługę ścieżek cache `gpmf_light.json`.
- `src/integrations/auto_telemetry_preflight.py` — Zoptymalizowano pobieranie współrzędnych przez lekki cache, naprawiono statusy wyszukiwania.
- `src/multifile.py` — Zintegrowano szybką ścieżkę timestampu GPMF bez zrzucania plików przez FFmpeg.
- `pyproject.toml` — Skonfigurowano `--capture=sys` dla uniknięcia awarii deskryptorów Windows na Pythonie 3.14.
- `scripts/benchmark_v114_load.py` — Kanoniczny skrypt pomiaru 4 etapów cyklu ładowania.
- `tests/test_v114_load_performance.py` — Rozszerzono zestaw testów regresji z 7 do 12 (pełne pokrycie cyklu życia late-attach i metadanych rzeczywistego pliku).
- `Raporty/RAPORT_SPORTCAMHUD_V114_LOAD_PERFORMANCE.md` — Zaktualizowany raport.
