# RAPORT: WERSJONOWANIE, INTEGRALNOŚĆ GIT I KOMPATYBILNOŚĆ BŁĘDÓW EKSPORTU

## 1. WERSJONOWANIE I IDENTYFIKACJA BUILDU
APP_VERSION=1.02
MAIN_BUILD_COMMIT=33a3848
PORTABLE_BUILD_COMMIT=33a3848
ACTUAL_REMOTE_HEAD=33a3848db7e69c531a3e29ec8a922774eb52b5fe

### 1.1 Inkrementacja Wersji
Skrypt \scripts/bump_version.py\ został zrefaktoryzowany z użyciem modułu \decimal.Decimal\, co gwarantuje precyzyjną, przewidywalną arytmetykę, wolną od błędów zmiennoprzecinkowych.
VERSION_INCREMENT_TESTS=PASS (zweryfikowano: 1.00 -> 1.01, 1.09 -> 1.10, 1.99 -> 2.00, 2.99 -> 3.00)

### 1.2 Pasek Tytułu
Zaimplementowano bezpieczny mechanizm generowania hasha dla okna głównego:
- W MAIN-NEW: odczyt struktury plików \.git\ (\HEAD\ i \packed-refs\) bez wywoływania procesów \git.exe\.
- W PORTABLE: odczyt wstrzykniętego podczas synchronizacji pliku \uild_meta.json\.
VERSION_TITLE_PASS=YES (Wyświetla: "BikeRideHUD v1.02 — main-new/Portable — 33a3848")

## 2. KOMPATYBILNOŚĆ OBSŁUGI BŁĘDÓW (EXPORT ERROR FRAMEWORK)
EXPORT_OUTPUT_CATEGORY_COMPATIBILITY=RESOLVED
- Alias \ExportOutputCategory = ErrorScope\ nie posiadał wartości \.DISK_FULL\ ani \.PERMISSION_DENIED\ (zawierał tylko \.JOB_ONLY\, \.QUEUE_BLOCKER\ itd.).
- Zidentyfikowano, że **jedynym** konsumentem wymagającym starego Enum był zestarzały test \	ests/test_output_write_error.py\. W samym kodzie GUI/Muxera aplikacja natywnie używała w pełni sprawnego \Render Error Framework\.
- Test zrefaktoryzowano tak, aby weryfikował bezpośrednio \classify_mux_error\ z nowej architektury. Weryfikacja udowodniła, że błędy takie jak brak uprawnień (\EACCES\) czy brak miejsca (\ENOSPC\) są rzucane poprawnie jako podklasy \StorageError\.
ERROR_FRAMEWORK_TESTS=PASS (symulacje: brak miejsca, brak uprawnień, awaria muxera z rc=1).

## 3. MODUŁY NATYWNE (SHA256)
GPMF_NATIVE_SHA256=50e413ff5ff68cb6be014205b475a2c99c18317887a26fa5c1f67975dcb2af6f (C:\_DEV\BikeRideHUD-main-new\src\native\gpmf\telem_gpmf_native.pyd)
AMD_NATIVE_DLL_SHA256=7f93c483404f970ea4e2110dcfe12535429b25b11df7415b688c07cef508752f (C:\_DEV\BikeRideHUD-main-new\native\d3d11_amf_pipeline\bin\telem_amd_native.dll)

## 4. TESTY URUCHOMIENIA GUI
MAIN_GUI_START=PASS (Przetestowano start weryfikujący uwierzytelnienie Garmin, wczytywanie GPMF, ładowanie UI)
PORTABLE_GUI_START=PASS

## 5. TESTY AMD
AMD_DIRECT_REAL_PASS=PASS (13/13 testów w \	est_amd_direct_mp4_mux.py\ - potwierdzenie braku regresji w FFmpeg/Mux i natywnym AMD)
AMD_QUEUE_REAL_PASS=PASS (4/4 testów w \	est_amd_queue_parity_and_performance.py\)

## 6. GIT I PARITY
GIT_COMMITS=1 nowy commit (fix: app version calculation, dynamic build hash...)
GIT_PUSH_STATUS=PUSHED TO origin/fix/gui-freeze-hud-composite
REMOTE_HEAD_VERIFIED=33a3848db7e69c531a3e29ec8a922774eb52b5fe (Zgodny z wyświetlanym)
PORTABLE_PARITY=YES (100% zgodności hashów kodu źródłowego oraz bibliotek DLL miedzy MAIN a PORTABLE)

## 7. FINAL STATUS
FINAL_STATUS=PASS
