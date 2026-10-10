# RAPORT: AUDYT I DOMKNIĘCIE NVIDIA AUDIO LIVE MUX ORAZ TWARDE POTWIERDZENIE AUTO FIT PARITY W PORTABLE

**Data:** 2026-10-06  
**Status:** ZAKOŃCZONO POMYŚLNIE  
**Środowiska:**  
- `C:\_DEV\SportCamHUD-main-new`  
- `C:\_DEV\SportCamHUD-portable`  

---

## CZĘŚĆ 1 — NVIDIA AUDIO LIVE MUX AUDYT I REFAKTOR

### 1. Wyniki audytu `get_clip_adts()`

Przed refaktorem przeprowadzono szczegółowy audyt implementacji audio w eksporterze NVIDIA (`src/ffmpeg/nvidia_native_exporter.py`):

- **GET_CLIP_ADTS_DEFINED:** `src/ffmpeg/nvidia_native_exporter.py:810` (poprzednio)
- **GET_CLIP_ADTS_CALLERS:** `build_streaming_audio_slice(video_timeline, ...)` (poprzednio linia 944) wywoływane w fazie 4 prep (`prep_tracker.start_phase("audio_slice")`, poprzednio linia 1196) przed uruchomieniem dekodera wideo i pierwszej klatki.
- **GET_CLIP_ADTS_READS_FULL_CLIP:** **YES**  
  Poprzednia funkcja uruchamiała proces `ffmpeg -y -ss ... -t ... -i <source> -vn -c:a copy -f adts -` z `stdout=subprocess.PIPE` i wywoływała `proc.communicate()`, czytając całość strumienia audio do pamięci RAM.
- **GET_CLIP_ADTS_RUNS_BEFORE_FIRST_FRAME:** **YES**  
  Całość procedury wykonywała się synchronicznie w fazie przygotowania przed utworzeniem `cmd_mux`, podłączeniem potoku wideo i narysowaniem/zakodowaniem klatki 0.
- **GET_CLIP_ADTS_ALLOCATES_FULL_AUDIO_BUFFER:** **YES**  
  Pobierała cały strumień do bufora `out_data: bytes`, po czym funkcja `parse_adts_packets()` parsowała i alokowała listę pakietów w pamięci RAM (`List[bytes]`), a wątek `PacedAudioFeeder` pompował je do Windows named pipe `\\.\pipe\telem_audio_...`.
- **GET_CLIP_ADTS_REQUIRED_FOR_LIVE_MUX:** **NO**  
  Live muxer FFmpeg przyjmuje bezpośrednie strumienie audio z oryginalnego pliku MP4 lub pliku listy concat (`-f concat -i concat.txt`), dokładnie tak samo jak eksporter AMD i Intel.

### 2. Decyzja
**USUNIĘTO CAŁKOWICIE I TRWALE.**

Usunięto z `src/ffmpeg/nvidia_native_exporter.py`:
- `get_clip_adts()`
- `parse_adts_packets()`
- `build_streaming_audio_slice()`
- `PacedAudioFeeder`
- wszelkie bufory ADTS w RAM
- dedykowane potoki nazwane audio Windows (`\\.\pipe\telem_audio_*`)

### 3. Zastosowane rozwiązanie architektoniczne
Wdrożono bezpośredni live mux z oryginalnego kontenera źródłowego:
- **Dla single-file:**
  - Argumenty wejściowe audio: `-i <source_mp4>` (lub `-ss <local_start_s> -i <source_mp4>` przy przycięciu początku).
  - Mapowanie w live muxerze:
    ```
    ffmpeg -y -f <v_fmt> -r <fps> -i - \
      [-ss <start>] -i <source_mp4> \
      -map 0:v:0 -map 1:a:0? \
      -c:v copy -c:a copy -t <duration> ...
    ```
- **Dla multi-file:**
  - Generowany jest jednolity concat plan `.audio.concat.txt` wskazujący bezpośrednio na oryginalne pliki MP4 z dokładnymi znacznikami `inpoint` / `outpoint` (zgodnie z `_write_audio_concat_plan`).
  - Argumenty wejściowe audio: `-copyts -avoid_negative_ts make_zero -f concat -safe 0 -i <audio_concat_path>`.
  - Concat plan jest bezpiecznie czyszczony w bloku `finally:` po zakończeniu muxera.
- **Pośrednie pliki / bufory:** **BRAK (NIE)**. Żadne pliki tymczasowe `.m4a`, `.aac`, `.wav` ani bufory RAM nie są alokowane.
- **Natychmiastowy start klatki 0:** **TAK**. Pierwsza klatka rusza natychmiast bez oczekiwania na demux audio (`CLICK_TO_FIRST_FRAME_MS <= 2s`).

### 4. Potwierdzenie aktualizacji dokumentacji
`AGENTS.md` (Sekcja 20: *AUDIO CACHE HARD ARCHITECTURAL INVARIANT*) została zaktualizowana o jawny, bezwzględny zakaz buforowania audio w pamięci RAM / ADTS pre-demuxingu:
> "ZABRONIONY JEST RÓWNIEŻ AUDIO CACHE W RAM / ADTS PRE-DEMUX.
> Zabrania się implementowania funkcji typu get_clip_adts(), PacedAudioFeeder, parse_adts_packets(),
> trzymania całego strumienia audio w buforach RAM (bytes, BytesIO, lista pakietów ADTS) przed pierwszą klatką.
> Audio z oryginalnego MP4 ma być podawane bezpośrednio do FFmpeg live muxera jako input plikowy:
> -i source.mp4 (lub concat plan dla multi-file)."

### 5. Wyniki testów `tests/test_audio_cache.py`
Wszystkie testy zaliczone w 100%:
- `test_legacy_audio_cache_symbols_do_not_exist`: **PASSED** (weryfikuje brak tokenów `ensure_audio_cache`, `get_audio_cache_path`, `AMD_AUDIO_CACHE`, `audio_stream.m4a`, `_resolve_cached_audio`, `get_clip_adts`, `PacedAudioFeeder`, `parse_adts_packets`, `build_streaming_audio_slice` w całym `src/`).
- `test_single_file_audio_comes_from_original_mp4`: **PASSED**
- `test_multifile_audio_concat_uses_original_mp4_files`: **PASSED**
- `test_middle_of_clip_inpoint_outpoint_uses_source_mp4`: **PASSED**
- `test_old_audio_stream_m4a_ignored_even_if_present`: **PASSED**
- `test_render_does_not_create_temporary_audio_file`: **PASSED**
- `test_fallback_mux_uses_original_source_audio`: **PASSED**
- `test_multifile_boundary_continuity`: **PASSED**
- `test_nvidia_native_exporter_uses_direct_source_audio_mux`: **PASSED**

---

## CZĘŚĆ 2 — AUTO FIT PORTABLE PARITY

### 1. Tabela SHA256 plików Auto FIT

Porównanie SHA-256 pomiędzy `C:\_DEV\SportCamHUD-main-new` a `C:\_DEV\SportCamHUD-portable`:

| Plik | Hash main-new | Hash portable | Status |
| :--- | :--- | :--- | :--- |
| `src/integrations/auto_telemetry_preflight.py` | `092ea9af43bcdeaeddc0f36bf91883ef7d20238753c81a0b3b3ff761819c3d8e` | `092ea9af43bcdeaeddc0f36bf91883ef7d20238753c81a0b3b3ff761819c3d8e` | **MATCH** |
| `src/gui/qt/_mixins/project_mixin.py` | `61c1cab7fe173aafdb0c3d969e0bf4d9287d8f4bb6373c616e03f3784ec12146` | `61c1cab7fe173aafdb0c3d969e0bf4d9287d8f4bb6373c616e03f3784ec12146` | **MATCH** |
| `src/gui/qt/tabs/load_tab.py` | `89e3eff5440774109b6e1e527e1a546f19f44f8d13255308a8bbc8e4c2005016` | `89e3eff5440774109b6e1e527e1a546f19f44f8d13255308a8bbc8e4c2005016` | **MATCH** |
| `src/gui/qt/main_window.py` | `fc7c533ac5f7ce5965d5e08e03befbec1ff7bddcff49e67dc01ec4ee284316ff` | `fc7c533ac5f7ce5965d5e08e03befbec1ff7bddcff49e67dc01ec4ee284316ff` | **MATCH** |
| `src/gui/qt/tabs/settings_tab.py` | `b0cad4410ed87406e46f9b018fbada9e48eb8f2a9094e1cac9b031069379c5eb` | `b0cad4410ed87406e46f9b018fbada9e48eb8f2a9094e1cac9b031069379c5eb` | **MATCH** |
| `tests/test_auto_telemetry_source_order.py` | `1d0df275946ac061007cd2c222c054b110e4ce5b9027fba3aa4807d93e37d73a` | `1d0df275946ac061007cd2c222c054b110e4ce5b9027fba3aa4807d93e37d73a` | **MATCH** |
| `tests/test_auto_telemetry_preflight_suite.py` | `a4fbfd27a7f61e34a8c93de169274c2d227651a646aa2c448355920167e71860` | `a4fbfd27a7f61e34a8c93de169274c2d227651a646aa2c448355920167e71860` | **MATCH** |
| `tests/test_autofit_pre_load.py` | `a5398400b08d7499ac57167d1b42232691fb2df21cc8e28397ac8430c9d70827` | `a5398400b08d7499ac57167d1b42232691fb2df21cc8e28397ac8430c9d70827` | **MATCH** |
| `src/gui/project_file_runtime.py` | N/A (Nie występuje w architekturze) | N/A | NOT_APPLICABLE |
| `src/gui/project_runtime.py` | N/A (Nie występuje w architekturze) | N/A | NOT_APPLICABLE |
| `src/gui/telemetry_fetch_runtime.py` | N/A (Nie występuje w architekturze) | N/A | NOT_APPLICABLE |
| `src/gui/auto_telemetry_service.py` | N/A (Nie występuje w architekturze) | N/A | NOT_APPLICABLE |
| `src/gui/auto_fit_service.py` | N/A (Nie występuje w architekturze) | N/A | NOT_APPLICABLE |
| `src/gui/panels/telemetry_panel.py` | N/A (Nie występuje w architekturze) | N/A | NOT_APPLICABLE |
| `src/gui/widgets/export_tab.py` | N/A (Nie występuje w architekturze) | N/A | NOT_APPLICABLE |
| `src/gui/main_window.py` | N/A (W architekturze: `src/gui/qt/main_window.py`) | N/A | NOT_APPLICABLE |
| `src/telemetry/gpx_loader.py` | N/A (Nie występuje w architekturze) | N/A | NOT_APPLICABLE |
| `src/telemetry/fit_worker.py` | N/A (Nie występuje w architekturze) | N/A | NOT_APPLICABLE |
| `src/services/auto_telemetry_finder.py` | N/A (Nie występuje w architekturze) | N/A | NOT_APPLICABLE |

### 2. Odpowiedzi na pytania audytowe dla Portable
- **PORTABLE_BLOCKING_REMOTE_WAIT_COUNT:** **0**  
  W całym procesie ładowania projektu (`project_mixin.py`) ani preflightu telemetrii (`auto_telemetry_preflight.py`) nie ma żadnego wywołania blokującego na wyszukiwanie sieciowe ani timeoutów blokujących UI/ładowanie projektu.
- **PORTABLE_LOCAL_SEARCH_IN_MP4_DIR_ONLY:** **YES**  
  Lokalne wyszukiwanie w `resolve_local_fit` oraz `scan_and_match_local_telemetry` jest ograniczone ściśle i wyłącznie do katalogu pierwszego pliku MP4 (`Path(video_paths[0]).parent`). Brak przeszukiwania podkatalogów, katalogów nadrzędnych oraz katalogów zewnętrznych.
- **PORTABLE_PRIORITY_ORDER_VERIFIED:** **YES**  
  Zgodnie z invariantem `TelemetryOrchestrator`:
  1. Ręcznie wybrany FIT / GPX (priorytet najwyższy)
  2. Plik `.fit` w dokładnym folderze źródłowego MP4
  3. Asynchroniczne odpytanie wybranej integracji (Garmin lub Strava) z late attach po zakończeniu pobierania.

### 3. Wyniki testów Auto FIT w Portable
Uruchomiono pełny zestaw testów Auto FIT i Audio Cache w `C:\_DEV\SportCamHUD-portable`:
- Liczba testów: **43**
- Wynik: **43 PASSED (100%)**
  - `tests/test_audio_cache.py`: 9 passed
  - `tests/test_auto_telemetry_source_order.py`: 17 passed
  - `tests/test_auto_telemetry_preflight_suite.py`: 13 passed
  - `tests/test_autofit_pre_load.py`: 4 passed

### 4. Podsumowanie skryptu check_parity.py
- **AUTO_FIT_HASH_PARITY:** **YES**
- **FIXED_SOURCE_HASH_PARITY:** **YES**
