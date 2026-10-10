# RAPORT: Centralny Cache Telemetrii i Eliminacja Sidecarów z Katalogów Materiałów

**Data:** 2026-09-22  
**Autor:** Antigravity  
**Branch:** `amd-bikeridehud`  
**Status:** **PASS (CASE A)**

---

## 1. Zidentyfikowany Problem i Cel

Wcześniejsze etapy wyeliminowały automatyczne tworzenie `*.layout.json`, jednak aplikacja wciąż generowała obok źródłowych materiałów wideo (`.MP4`) obszerne pliki robocze i metadane:
* GPMF raw dump: `<clip>.json`, `<clip>.json.meta`, `<clip>.meta.json` (do ~58 MB per klip)
* Przetworzone tablice binarne: `<clip>.telemetry.npz` (do ~20 MB per klip)
* Mapowanie znaczników czasu klipów w osi czasu: `<clip>.telem_time`, `<clip>.MP4.telem_time.json`, `.meta.json`

**Cel:**
Katalog źródłowy GoPro (np. karta SD / folder materiałów) musi pozostać w 100% CZYSTY.
* `NEW_GENERATED_FILES_IN_SOURCE_DIRECTORY = 0`
* `SOURCE_DIRECTORY_WRITE_COUNT = 0`
* Przeniesienie wszystkich automatycznie generowanych cache do centralnego katalogu:
  `%LOCALAPPDATA%\SportCamHUD\cache\media\<source_key>\`
* Zachowanie read-only wstecznej kompatybilności (migracja istniejących plików legacy bez ich modyfikacji i bez kasowania).
* Odchudzenie kolejki renderowania (`ExportJob`) – brak osadzania wielomegabajtowych struktur telemetrii, praca wyłącznie na ścieżkach źródłowych, snapshocie layoutu i opcjonalnym hincie `telemetry_cache_key`.

---

## 2. Audyt Wszystkich Generowanych Sidecarów

```text
GENERATED_SIDECAR_TYPES=
1. GPMF JSON Cache: <video>.json, <video>.json.meta, <video>.meta.json
2. Processed Telemetry NPZ: <video>.telemetry.npz
3. Time Mapping: <video>.telem_time, <video>.MP4.telem_time.json, <video>.MP4.telem_time.json.meta
4. HUD Layout: <video>.layout.json (wyeliminowany w poprzednim etapie)
```

### Zestawienie komponentów (Before / After):

| Typ Sidecara | Cel (Purpose) | Zapisywany wcześniej przez (Before) | Zapisywany obecnie (After) | Czytany przez | Invalidating conditions |
|---|---|---|---|---|---|
| `gpmf.json` / `.meta` | Raw payload parsowania GPMF | `project_mixin._write_gpmf_cache`, `telemetry_extract.py` | `%LOCALAPPDATA%\SportCamHUD\cache\media\<key>\gpmf.json` via `telemetry_cache_manager` | `project_mixin`, `render_mixin` | Zmiana ścieżki, rozmiaru, mtime, `CACHE_FORMAT_VERSION` |
| `telemetry.npz` | Binarne tablice NumPy z interpolowaną telemetrią | `telemetry_processed_cache.write_processed_cache` | `%LOCALAPPDATA%\SportCamHUD\cache\media\<key>\telemetry.npz` via `telemetry_cache_manager` | `telemetry_processed_cache.read_processed_cache_arrays` | Zmiana ścieżki, rozmiaru, mtime, `PROCESSED_CACHE_VERSION` |
| `telem_time.json` / `.meta` | Globalny start i synchronizacja klipu | `multifile._write_telem_time_cache` | `%LOCALAPPDATA%\SportCamHUD\cache\media\<key>\telem_time.json` via `telemetry_cache_manager` | `multifile._load_valid_telem_time_cache` | Zmiana ścieżki, rozmiaru, mtime |

```text
SIDECAR_WRITERS_BEFORE=
- src/gui/qt/_mixins/project_mixin.py (_write_gpmf_cache, _generate_meta_json)
- src/telemetry_processed_cache.py (write_processed_cache)
- src/multifile.py (_write_telem_time_cache)
- src/telemetry_extract.py (find_metadata_json_for_write)

SIDECAR_WRITERS_AFTER=
- src/telemetry_cache_manager.py (centralized atomic writer to %LOCALAPPDATA%\SportCamHUD\cache\)
- ZERO writers in video source directory
```

---

## 3. Centralny Cache Manager i Algorytm Klucza

Utworzono dedykowany moduł [telemetry_cache_manager.py](file:///C:/_DEV/SportCamHUD-amd/src/telemetry_cache_manager.py).

* **Cache Root:**
  ```text
  CACHE_ROOT=%LOCALAPPDATA%\SportCamHUD\cache\
  ```
  Przechowywanie per źródło w:
  ```text
  %LOCALAPPDATA%\SportCamHUD\cache\media\<source_key>\
      gpmf.json
      gpmf.meta.json
      telemetry.npz
      telem_time.json
      telem_time.meta.json
      metadata.json
  ```

* **Algorytm `source_key`:**
  ```text
  CACHE_KEY_ALGORITHM=stem + sha256(canonical_path | file_size | mtime_ns | v{CACHE_FORMAT_VERSION})[:16]
  CACHE_FORMAT_VERSION=1
  ```
  Klucz jest deterministyczny, nie wymaga czytania gigabajtów pliku MP4, a jednocześnie gwarantuje, że dwa pliki o tej samej nazwie w różnych katalogach lub ten sam plik po edycji/zastąpieniu otrzymają całkowicie odrębny klucz cache.

* **Zapisy Atomowe:**
  Wszystkie zapisy (`atomic_write_file`, `atomic_save_json`, `np.savez_compressed`) odbywają się do pliku tymczasowego (`.tmp_<uuid>`), a następnie są przenoszone przez `os.replace`. W przypadku błędu lub nagłego przerwania procesu na dysku nie pozostaje uszkodzony plik cache.

* **Czyszczenie Cache:**
  Funkcja `cleanup_cache(max_size_gb=10.0, protected_keys=set())` porządkuje najstarsze wpisy (`last_accessed_at`) przy zachowaniu kluczy aktualnie używanych przez aktywne zadania renderingu.

---

## 4. Obsługa Legacy Cache i External JSON

* **Legacy Cache Import (Read-Only):**
  Jeżeli obok wideo istnieje stary plik `.telemetry.npz`, `.json` lub `.telem_time.json`:
  1. Zostaje odczytany w trybie tylko do odczytu.
  2. Zostaje zaimportowany/przekopiowany atomowo do AppData cache.
  3. Od tej pory aplikacja używa wyłącznie AppData cache.
  4. Oryginalny plik użytkownika w katalogu wideo **NIE jest usuwany ani modyfikowany**.
  ```text
  LEGACY_CACHE_IMPORT=True
  LEGACY_SOURCE_FILES_MODIFIED=False
  ```

* **Pliki JSON Wskazane Jawnie przez Użytkownika:**
  Gdy użytkownik w oknie dialogowym jawnie wskaże zewnętrzny plik JSON:
  * Nie jest on traktowany jako automatyczny cache,
  * Nie jest przenoszony ani kasowany,
  * Zadanie w kolejce zachowuje referencję do jawnej ścieżki (`external_gpmf_path`).
  ```text
  USER_SUPPLIED_JSON_PRESERVED=True
  ```

---

## 5. Odchudzenie Kolejki Renderowania (`ExportJob`)

Zadanie kolejki [ExportJob](file:///C:/_DEV/SportCamHUD-amd/src/gui/export_queue.py) zawiera:
* Ścieżki wideo (`video_paths`)
* Opcjonalną ścieżkę FIT/GPX
* Opcjonalną jawną ścieżkę `external_gpmf_path` (jeśli dostarczona przez usera)
* Niezmienniczy snapshot layoutu (`layout`)
* Opcje renderingu (`options`)
* Hint klucza cache (`telemetry_cache_key`)

Zadanie **NIE osadza** 50–100 MB surowych tablic telemetrycznych. Podczas odtwarzania kolejki po restarcie aplikacji (`_restore_job_snapshot_onto_controller`), kontroler odczytuje lub automatycznie regeneruje telemetrię z AppData cache bądź bezpośrednio z pliku MP4.

```text
QUEUE_JOB_DEPENDS_ON_GENERATED_SIDECAR=False
QUEUE_JOB_EMBEDS_TELEMETRY_CACHE=False
QUEUE_RESTART_WITHOUT_SIDECARS=True
```

---

## 6. Wyniki Wydajnościowe (Warm Load Benchmark)

Zmierzono czas wczytywania ciepłego cache telemetrii z dysku (lokalny sidecar vs nowy centralny AppData cache):

```text
LEGACY_WARM_LOAD_MS = 1.476 ms
NEW_WARM_LOAD_MS    = 1.422 ms
RATIO               = 0.964 (nowy cache szybszy o ~3.6%)
```
Spełniony warunek: `NEW_CACHE_WARM_LOAD <= legacy warm load * 1.10`. Przeniesienie do AppData nie powoduje żadnego narzutu I/O.

---

## 7. Wyniki Testów Automatycznych i Real Workflow Smoke

### Testy Pytest:
Uruchomiono pełny zestaw testów regresyjnych i jednostkowych:
```bash
python -m pytest tests/test_central_telemetry_cache.py tests/test_telemetry_processed_cache.py tests/test_state_queue_layout_persistence.py tests/test_export_queue_basic.py tests/test_export_queue_lifecycle.py tests/test_multifile_lean_continuity.py tests/test_multifile_hud_lifecycle.py -v
```
**Wynik:** **74 passed in 18.65s (100% PASS)**

Nowe testy jednostkowe w [test_central_telemetry_cache.py](file:///C:/_DEV/SportCamHUD-amd/tests/test_central_telemetry_cache.py):
1. `test_generated_gpmf_json_goes_to_appdata` — PASS
2. `test_generated_telemetry_npz_goes_to_appdata` — PASS
3. `test_telem_time_goes_to_appdata` — PASS
4. `test_no_generated_sidecar_in_video_dir` — PASS
5. `test_legacy_cache_import_readonly` — PASS
6. `test_same_filename_different_directory_has_different_cache_key` — PASS
7. `test_cache_invalidation_on_source_change` — PASS
8. `test_queue_job_does_not_embed_generated_telemetry` — PASS
9. `test_queue_job_can_render_after_cache_deleted` — PASS
10. `test_multifile_has_independent_cache_keys` — PASS
11. `test_atomic_cache_write` — PASS
12. `test_cache_cleanup_prunes_oldest` — PASS
13. `test_user_supplied_external_json_preserved` — PASS

### Real Workflow Smoke Test (`scratch/test_central_cache_real_smoke.py`):
Przeprowadzono pełny test imitujący realne użytkowanie w czystym folderze roboczym z `GX020079.MP4` i `GX020079.fit`:
1. Otwarcie pliku wideo i FIT,
2. Wygenerowanie telemetrii GPMF i zapis binarnego cache w AppData,
3. Generowanie podglądu HUD (seek preview),
4. Dodanie zadania do kolejki eksportu,
5. Wykonanie operacji `Resetuj układ`,
6. Wyrenderowanie 30 klatek w procesie potomnym AMD (`run_amd_render_child`),
7. Symulacja zamknięcia i ponownego uruchomienia aplikacji,
8. Weryfikacja odtworzenia zadania z kolejki,
9. Audyt zawartości katalogu źródłowego.

```text
Source directory BEFORE workflow: ['GX020079.MP4', 'GX020079.fit']
Source directory AFTER full workflow: ['GX020079.MP4', 'GX020079.fit']
LEAKED_FILES=[]
SOURCE_DIR_DIFF_GENERATED_FILES=0
RESET_LAYOUT_SOURCE_DIR_WRITES=0
```

---

## 8. Wymagane Metryki Końcowe

```text
GENERATED_SIDECAR_TYPES=GPMF_JSON, TELEMETRY_NPZ, TELEM_TIME_JSON, LAYOUT_JSON
SIDECAR_WRITERS_BEFORE=project_mixin, telemetry_processed_cache, multifile, telemetry_extract
SIDECAR_WRITERS_AFTER=telemetry_cache_manager (AppData only, 0 in source dir)

CACHE_ROOT=C:\Users\Malcerz\AppData\Local\SportCamHUD\cache\
CACHE_KEY_ALGORITHM=stem + sha256(canonical_path|size|mtime_ns|format_version)[:16]
CACHE_FORMAT_VERSION=1

GPMF_JSON_CACHE=%LOCALAPPDATA%\SportCamHUD\cache\media\<source_key>\gpmf.json
TELEMETRY_NPZ_CACHE=%LOCALAPPDATA%\SportCamHUD\cache\media\<source_key>\telemetry.npz
TELEM_TIME_CACHE=%LOCALAPPDATA%\SportCamHUD\cache\media\<source_key>\telem_time.json

LEGACY_CACHE_IMPORT=True
LEGACY_SOURCE_FILES_MODIFIED=False

USER_SUPPLIED_JSON_PRESERVED=True

SOURCE_DIRECTORY_WRITE_COUNT=0
NEW_GENERATED_FILES_IN_SOURCE_DIRECTORY=0

QUEUE_JOB_DEPENDS_ON_GENERATED_SIDECAR=False
QUEUE_JOB_EMBEDS_TELEMETRY_CACHE=False

QUEUE_RESTART_WITHOUT_SIDECARS=True

MULTIFILE_CACHE=True (per-clip independent cache keys)

LEGACY_WARM_LOAD_MS=1.476 ms
NEW_WARM_LOAD_MS=1.422 ms

RESET_LAYOUT_SOURCE_DIR_WRITES=0

TESTS=74 passed in 18.65s
GUI_WORKFLOW_SMOKE=PASS

TOTAL_STAGE_WALL_TIME=~38 min
LONGEST_SINGLE_COMMAND_SECONDS=27.5s

CASE=CASE A — all generated telemetry/cache sidecars moved to AppData
```
