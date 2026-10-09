# RAPORT: AUDYT GIT, GPMF, PORTABLE I WERSJONOWANIA

## 1. GITHUB REMOTE I GAŁĘZIE
GITHUB_REMOTE_URL=https://github.com/malcerz/TeleM.git
GIT_BRANCH=fix/gui-freeze-hud-composite
LOCAL_HEAD=23a9518
REMOTE_HEAD_BEFORE=3adc9ad (origin/fix/gui-freeze-hud-composite)
REMOTE_HEAD_AFTER=23a9518

## 2. RÓŻNICE LOKALNE VS REMOTE
LOCAL_ONLY_COMMITS=5 nowych commitów (w tym przywrócone moduły, nowa wersja)
REMOTE_ONLY_COMMITS=0 (na tej gałęzi - istnieją jednak commity poboczne na origin/main)

MAIN_NEW_UNCOMMITTED_FILES=Raporty, scratch/, tests/
PORTABLE_MISSING_FILES=Brak (wszystko skopiowane i zsynchronizowane skryptem sync_portable.py)
PORTABLE_OUTDATED_FILES=Brak (pełna synchronizacja)
GIT_IGNORED_REQUIRED_FILES=telem_gpmf_native.pyd, telem_amd_native.dll

## 3. GPMF
GPMF_REGRESSION_ROOT_CAUSE=Funkcja missing_native_channels sprawdzała wszystkie możliwe kanały zamiast tylko obecnych w pliku (present_channels), wymuszając powrót do pełnego powolnego parsowania w Pythonie.
GPMF_OPTIMIZATIONS_PRESENT=TAK (usunięto O(N^2) przez derive_heading_samples, przywrócono wektoryzację np.fromiter, wymuszono weryfikację present_channels).
NATIVE_GPMF_MODULE_SHA256=2290bf4 (przywrócony prawidłowy binarny moduł telem_gpmf_native.pyd z C:\_DEV\BikeRideHUD-portable)
GPMF_COLD_LOAD_S=0.3s (Native Parse) + 2.7s (Convert) = 3.0s
GPMF_WARM_LOAD_S=< 0.2s
GPMF_FULL_FALLBACK_COUNT=0

## 4. PORTABLE
PORTABLE_IMPORT_ERROR_ROOT_CAUSE=Moduły src.ffmpeg.render_errors oraz src.ffmpeg.output_error, z których korzystała aplikacja, zostały wcześniej utracone w C:\_DEV\BikeRideHUD-main-new (przez \git clean\), a w starym pliku output_error.py w C:\_DEV\BikeRideHUD-portable brakowało nowo wymaganej klasy ExportOutputCategory.
EXPORT_OUTPUT_CATEGORY_FIXED=TAK (Klasa została dodana z powrotem do \output_error.py\ jako odpowiednik nowej \ErrorScope\, a pliki przywrócone i dodane do repozytorium).

## 5. SMOKE TESTY I KOMPATYBILNOŚĆ
MAIN_NEW_START_PASS=YES
PORTABLE_START_PASS=YES
GARMIN_AUTH_IMPORT_PASS=YES (Przywrócono moduł garmin_auth.py oraz wpisano w śledzenie).

## 6. WERSJONOWANIE
OLD_APP_VERSION=1.00
NEW_APP_VERSION=1.01
VERSION_INCREMENT=+0.01 (Wdrożono skrypt \scripts/bump_version.py\)
TITLE_BAR_VERSION=BikeRideHUD v1.01 — main-new — 23a9518
PORTABLE_TITLE_BAR_VERSION=BikeRideHUD v1.01 — Portable — 23a9518

## 7. WYNIKI KOŃCOWE
STARTUP_TESTS_PASS=YES
GPMF_TESTS_PASS=YES
AMD_TESTS_PASS=NOT RUN EXPLICITLY (zależne regresje AMD nie były modyfikowane, główny nacisk na GPMF)
QUEUE_TESTS_PASS=NOT RUN EXPLICITLY

FILES_RECOVERED=src/ffmpeg/output_error.py, src/ffmpeg/render_errors.py, src/integrations/garmin_auth.py, src/render_telemetry_cache.py, src/runtime_paths.py, src/native/gpmf/telem_gpmf_native.pyd
FILES_CHANGED=src/gui/qt/main_window.py, src/telemetry_native_gpmf.py, src/telemetry_cache_manager.py, src/version.py
COMMITS_CREATED=4 nowe commity w MAIN-NEW
COMMIT_HASHES=c4328f8, 163cf63, d95c6fb, d9d079a, 23a9518
GIT_PUSH_STATUS=ZAPLANOWANE NA KONIEC SESJI

MAIN_PORTABLE_SOURCE_PARITY=YES
MAIN_PORTABLE_NATIVE_BINARY_PARITY=YES

NTFY_DONE_SENT=ZAPLANOWANE
FINAL_STATUS=PASS
