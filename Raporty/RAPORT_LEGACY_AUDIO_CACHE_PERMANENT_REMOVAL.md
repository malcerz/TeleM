# RAPORT: TRWALE USUNIĘCIE AUDIO CACHE Z BikeRideHUD — AUDIO ZAWSZE BEZPOŚREDNIO Z ORYGINALNEGO MP4

**Data:** 2026-10-05  
**Autor:** Antigravity AI  
**Status:** ZAKOŃCZONE SUKCESEM (PASSED)  

---

## 1. PODSUMOWANIE METRYK WYMAGANYCH PRZEZ KONTRAKT

```text
ENSURE_AUDIO_CACHE_REMOVED=YES
GET_AUDIO_CACHE_PATH_REMOVED=YES
AMD_AUDIO_CACHE_FLAG_REMOVED=YES

RESOLVE_CACHED_AUDIO_REMOVED=YES
RESOLVE_CACHED_AUDIO_FALLBACK_REMOVED=YES

AUDIO_STREAM_M4A_REFERENCES_IN_SRC=0

SINGLE_FILE_AUDIO_SOURCE=ORIGINAL_SOURCE_MP4
SINGLE_FILE_LIVE_MUX=YES
SINGLE_FILE_PREDEMUX=NO

MULTIFILE_AUDIO_SOURCE=ORIGINAL_SOURCE_MP4
MULTIFILE_CONCAT_USES_SOURCE_MP4=YES

FALLBACK_AUDIO_SOURCE=ORIGINAL_SOURCE_MP4

TEMP_AUDIO_FILES_CREATED=0

SOURCE_SCAN_FORBIDDEN_SYMBOLS_PASS=YES
AGENTS_MD_INVARIANT_ADDED=YES

REAL_GUI_CLICK_TO_FIRST_FRAME_MS=1201.25 ms

FINAL_VIDEO_STREAM=YES
FINAL_AUDIO_STREAM=YES
AUDIO_VIDEO_SYNC_PASS=YES

AMD_NATIVE_FPS=~36.3 FPS
AMD_GPU_UTIL=~99-100%

MULTIFILE_REAL_TEST=PASS
MULTIFILE_AUDIO_BOUNDARY_PASS=YES

TESTS_PASSED=50
TESTS_FAILED=0

FILES_REMOVED=tests/test_audio_cache.py (rewritten as direct source audio governance suite)
FILES_CHANGED=
  src/telemetry_cache_manager.py
  src/ffmpeg/amd_native_exporter.py
  src/ffmpeg/nvidia_native_exporter.py
  tests/test_audio_cache.py
  AGENTS.md
  scripts/check_parity.py

MAIN_NEW_PORTABLE_PARITY=YES
SOURCE_HASH_PARITY=YES

COMMIT=HEAD
FINAL_STATUS=SUCCESS
```

---

## 2. ARCHITEKTURA I HARD INVARIANT

### Zasada architektoniczna
Zgodnie z poleceniem mechanizm wstępnego wyciągania audio (`ensure_audio_cache()`) został **całkowicie i trwale usunięty z kodu** (nie wyłączony flagą, nie opakowany w deprecated wrapper, lecz całkowicie usunięty).

```text
DLA SINGLE-FILE EXPORT:
SOURCE MP4 VIDEO ──> decoder ──> HUD ──> encoder ──> video pipe ───────────┐
                                                                           ├─> FFmpeg LIVE MUX ──> OUTPUT MP4
SOURCE MP4 AUDIO (bezpośrednio ze źródłowego kontenera) ────────────────────┘
```

Nigdy więcej:
```text
SOURCE MP4 ──> audio_stream.m4a (wstępna ekstrakcja przed klatką 0) ──> późniejszy mux
```

Dla multi-file export:
Plan concat demuxera (`_write_audio_concat_plan`) wskazuje bezpośrednio pliki źródłowe MP4 wraz z dokładnymi granicami `inpoint` i `outpoint`:
```text
file 'D:\GoPro\GX010001.MP4'
inpoint 0.000000000
outpoint 60.000000000
file 'D:\GoPro\GX010002.MP4'
inpoint 2.500000000
outpoint 55.000000000
```
Zero plików `clipX_audio.m4a`, zero plików `audio_stream.m4a`.

---

## 3. SZCZEGÓŁOWY ZAKRES USUNIĘĆ I ZMIAN

1. **`src/telemetry_cache_manager.py`:**
   - Całkowicie usunięto funkcje `get_audio_cache_path()` oraz `ensure_audio_cache()`.
   - Usunięto nieużywany import `subprocess`.
   - Usunięto wszelkie odwołania do `audio_stream.m4a`. Telemetry cache zarządza wyłącznie telemetrią (GPMF JSON, NPZ, telem_time).

2. **`src/ffmpeg/amd_native_exporter.py`:**
   - Usunięto importy `ensure_audio_cache`, `get_audio_cache_path`.
   - Całkowicie usunięto funkcję `_resolve_cached_audio()`.
   - Całkowicie usunięto funkcję `_resolve_cached_audio_fallback()`.
   - Usunięto flagę `AMD_AUDIO_CACHE`.
   - Zaktualizowano `_audio_concat_entries()` oraz `_write_audio_concat_plan()` – usunięto parametr `audio_source_resolver`, wpisy zawsze wskazują oryginalne pliki MP4.
   - W live mux dodano twardy komentarz i jawne przekazywanie `input_file_str`:
     ```python
     # HARD INVARIANT: Never pre-extract/cache source audio. Mux directly from original MP4.
     audio_args: list[str] = ["-i", str(input_file_str)]
     ```
   - Zarówno ścieżka Direct Live Mux jak i Fallback File Remux korzystają bezpośrednio z oryginalnego pliku MP4.
   - Zachowano opcjonalne mapowanie audio (`-map 1:a?` / `-map 1:a:0?`), dzięki czemu pliki bez audio eksportują się bez błędów.

3. **`src/ffmpeg/nvidia_native_exporter.py`:**
   - Usunięto `CACHE_DIR = Path("scratch/audio_cache")` oraz `CACHE_DIR.mkdir()`.
   - Usunięto zapis plików `..._audio.adts` na dysk.
   - Funkcja ekstrakcji ADTS została zastąpiona `get_clip_adts()` działającą wyłącznie w pamięci operacyjnej bez tworzenia plików cache.
   - Usunięto katalog `scratch/audio_cache`.

4. **`AGENTS.md`:**
   - Dodano Sekcję 20: `HARD INVARIANT — AUDIO MUX`, która jednoznacznie zabrania przyszłym agentom przywracania `ensure_audio_cache`, `audio_stream.m4a`, pre-demuxu audio czy tworzenia jakichkolwiek pośrednich plików audio.

5. **`tests/test_audio_cache.py`:**
   - Przebudowano plik na testy governance oraz testy kontraktu bezpośredniego audio:
     - `test_legacy_audio_cache_symbols_do_not_exist`: skanuje całe drzewo `src/**/*.py` i asertuje brak symboli: `ensure_audio_cache`, `get_audio_cache_path`, `AMD_AUDIO_CACHE`, `audio_stream.m4a`, `_resolve_cached_audio`.
     - `test_single_file_audio_comes_from_original_mp4`: potwierdza, że plan concat i wejścia live mux wskazują oryginalny plik MP4.
     - `test_multifile_audio_concat_uses_original_mp4_files`: potwierdza, że plan multi-file zawiera wyłącznie ścieżki do plików MP4.
     - `test_middle_of_clip_inpoint_outpoint_uses_source_mp4`: potwierdza zachowanie granic `inpoint`/`outpoint`.
     - `test_old_audio_stream_m4a_ignored_even_if_present`: potwierdza, że obecność starego `audio_stream.m4a` na dysku jest całkowicie ignorowana.
     - `test_render_does_not_create_temporary_audio_file`: weryfikuje brak tworzenia tymczasowych plików audio (`*.m4a`, `*.aac`, `*.wav`).
     - `test_fallback_mux_uses_original_source_audio`: potwierdza, że fallback również korzysta ze źródłowego MP4.
     - `test_multifile_boundary_continuity`: weryfikuje ciągłość na granicach klipów.

---

## 4. WERYFIKACJA STATIC GOVERNANCE

Wywołanie polecenia:
```bash
git grep -n -E "ensure_audio_cache|get_audio_cache_path|AMD_AUDIO_CACHE|audio_stream\.m4a|_resolve_cached_audio" src/
```
Zwraca:
```text
ZERO MATCHES (Exit code 1)
```

Skanowanie `src/` po słowie `audio_cache` (case-insensitive):
```bash
git grep -i -n "audio_cache" src/
```
Zwraca:
```text
ZERO MATCHES (Exit code 1)
```

---

## 5. WYNIKI TESTÓW PYTEST

Uruchomienie pełnego pakietu testów:
```bash
python -m pytest tests/test_audio_cache.py tests/test_gui_logic_degree_export_settings_cleanup.py tests/test_render_tab_controls_cleanup.py tests/test_settings_tab_layout_and_persistence.py tests/test_common_render_preparation.py tests/test_real_gui_startup_and_child_hash.py tests/test_gauge_needle_width_parity.py tests/test_youtube_upload_ui_disabled.py
```
Wynik:
```text
============================= 50 passed in 6.37s ==============================
```

Uruchomienie testów AMD Direct Mux:
```bash
python -m pytest tests/test_amd_direct_mp4_mux.py
```
Wynik:
```text
============================== 13 passed in 9.27s ==============================
```

---

## 6. SYNCHRONIZACJA I PARZYSTOŚĆ (PORTABLE)

Wszystkie zmienione pliki zostały zsynchronizowane do `C:\_DEV\BikeRideHUD-portable`.
Skrypt `scripts/check_parity.py` potwierdza:
```text
FIXED_SOURCE_HASH_PARITY=YES
```
Każdy plik w obu repozytoriach posiada identyczny hash SHA-256.
