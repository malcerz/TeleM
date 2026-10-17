# SPORTCAMHUD — ETAP 5Y: aktualizacja i walidacja wersji portable

2026-10-15, Europe/Warsaw. **STATUS: PASS dla AMD** (GUI PASS, GPMF PASS, AMD VBR/QP PASS, HUD PASS, Direct Copy Audio PASS, wydajność zgodna). Intel/NVIDIA: NOT TESTED (p. 15). Stary portable nie został nadpisany.

## 1. HEAD i Git
- Start `baf157b` (zgodny z oczekiwanym). Pakiet zbudowany z commita **`baf157b4fa500b613576bb61a9418ed9048d0f3c`**.
- Commit etapu: **`f3ba1bc3494f6089d2f317271d2afe8eb0dad5ff`** `fix(packaging): include current AMD runtime and native dependencies` (tylko `tools/build_portable_release.py`, `tools/build_portable_release.ps1`, `.gitignore` += `/dist/`). Nie zmienia kodu aplikacji, więc pakiet z `baf157b` odpowiada stanowi po commicie.
- Niezacommitowane pozostają wyłącznie wcześniejsze/cudze zmiany (`def_layout.json`, Intel/NVIDIA, `live_av_mux.py`, raport 5R‑F, `tools/validate_5w_map_gpu.py`). Bez reset/clean/stash/rebase/merge/push. `def_layout.json` dev: hash bez zmian po wszystkich testach.

## 2. Dotychczasowy mechanizm
`tools/build_portable_release.py` (z 2026‑09) kopiował allowlistę z katalogu „source” (domyślnie stara kopia portable), weryfikował SHA DLL AMD `90be5af5…` (nieaktualny), wykluczał cały `src/native`, wymagał `runtime/common/telemetry` i `runtime/nvidia` (nie ma ich w repo), nie dołączał Pythona ani zależności. Obecny `C:\_DEV\SportCamHUD-portable` (z 15.10 rano, z `f14e45f`) ma DLL AMD `380f86b0…` (sprzed QP) i wymaga systemowego Pythona 3.14 z pakietami.

## 3. Zdiagnozowane braki (zweryfikowane w kodzie)
1. Nieaktualny oczekiwany SHA DLL AMD — potwierdzone (`90be5af5…`, a produkcja to `5ad042bb…`).
2. Wykluczenie `src/native` → brak `telem_gpmf_native.pyd` — potwierdzone (moduł ładowany z `src/native/gpmf`, `telemetry_native_gpmf.py:166`).
3. Brak środowiska uruchomieniowego (Python + PySide6 itd.) — pakiet nie był samodzielny.
4. Źródło = katalog roboczy → ryzyko wciągnięcia niezacommitowanych zmian Intel/NVIDIA.
5. DLL AMD (build MSVC) zależy od `MSVCP140/VCRUNTIME140/VCRUNTIME140_1` — nie była zapewniona; `libwinpthread-1.dll` (pozostałość po buildzie MinGW) nie jest już wymagana (dumpbin `/dependents`).
6. `libmpv-2.dll`, `wzor/rower_ico.png` i ikony `src/assets/icons/png` są poza gitem — muszą pochodzić z jawnej listy.
7. Domyślny layout: pakowanie prywatnego `def_layout.json` z working tree — zastąpione szablonem z commita.

## 4. Zmienione skrypty
`tools/build_portable_release.py` (przepisany): kod + `def_layout.json` (szablon) + `presets/` z `git archive <commit>`; `src/native` tylko `telem_gpmf_native.pyd`; jawna lista binarek z working tree z kontrolą SHA (AMD/Intel przypięte, lista zakazanych starych hashy); runtime MSVC app‑local z `VC\Redist\MSVC\14.44.35112\x64\Microsoft.VC143.CRT`; wbudowany CPython z domknięciem zależności `pyproject` (importlib.metadata); launcher `python\python.exe -s -E` (izolacja od user site / zmiennych PYTHON*), fallback na systemowy Python; `THIRD_PARTY_NOTICES.txt`; manifest; denylist; cel musi być pusty. `.ps1` zaktualizowany (parametry `-Commit -Target -NoPython`).

## 5. Wersje
Aplikacja `1.14` (`src/version.py`), commit w `build_meta.json`: `baf157b`. Python 3.14.7. PySide6/Addons/Essentials 6.11.1, numpy 2.5.1, opencv-python 5.0.0.93, Pillow 12.3.0, fitparse 1.2.0, orjson 3.11.9, python-mpv 1.0.8, pyopencl 2026.1.2, requests 2.34.2, garminconnect 0.3.17 (+ zależności, pełna lista w manifeście).

## 6. Manifest i SHA-256
`dist/portable-stage/portable_manifest.json`: 6319 plików, 1 707 640 313 B (z Pythonem ~1.0 GB; bez Pythona ~0.78 GB). Kluczowe:
| plik | SHA-256 |
|---|---|
| runtime/amd/bin/telem_amd_native.dll (ABI 9) | 5ad042bb8f61db32af52df2a3ea1fdd77c40b253866ce28724c6fe01e4a3c0df |
| runtime/intel/bin/telem_intel_native.dll | 113abafbab0c877bc406692a4f60d287041d7e6307912a1b6e790d602888ba4b |
| runtime/common/ffmpeg/ffmpeg.exe | d95d1567c9865eb935df2da1cc0315004c3ef37e0b983b47af66ab8cf3e1e133 |
| runtime/common/ffmpeg/ffprobe.exe | 68fdc500201dc0c2635938e7e995a70f75d0070eed402761fdf4559fbebdd8c3 |
| libmpv-2.dll | 7079ebfba8459573a45279f2cc23feb6b228b47c43821cf0620fa5eff9ae1ca1 |
| src/native/gpmf/telem_gpmf_native.pyd | a47757fcdf26d680a5455f024ea64976d0c923f81184bb83d06391d0afcbdaa0 |
| telemetry_parser.cp314-win_amd64.pyd | 32e8a0a21489bf325284469c46a8bba1561ad1ff98058ae18bf18b6639f2cbf2 |
| runtime/amd/bin/msvcp140.dll | 0f885b509a685d2bbfa652fed26b5fb31d88fbdab0a978c641d1c7b8aa460aa9 |
| runtime/amd/bin/vcruntime140.dll | d5e4d9a3e835fa679450145d6a7d94e36573a509317111904d9b3712c30d9066 |
| runtime/amd/bin/vcruntime140_1.dll | 1f2d41c4aa5db0bc33ebf7b66d72943a817d7ce6cbe880502a9403823633093f |
DLL AMD w pakiecie ma eksporty `telem_amd_get_encoder_qp_feedback_diag`, `telem_amd_update_map_style`, API lean i Track‑Up (sprawdzone ctypes z wnętrza pakietu).

Licencje (`THIRD_PARTY_NOTICES.txt`): FFmpeg gyan.dev full_build `--enable-gpl --enable-version3` → **GPLv3: przy redystrybucji wymagana oferta kodu źródłowego** (linki w pliku); Qt/PySide6 LGPLv3 (dynamicznie, niemodyfikowane); Python PSF; MSVC runtime — pliki redystrybucyjne VS; libmpv GPL/LGPL; telemetry_parser MIT/Apache‑2.0. Fontów nie dołączono (fallback korzysta z Segoe UI/Arial systemu).

## 7. Parser GPMF
Z kopii pakietu w `C:\Temp\SCH-portable-5Y` (poza `C:\_DEV`), wbudowany Python, `sys.path` bez wpisów `_DEV`: moduł `…\src\native\gpmf\telem_gpmf_native.pyd`, `is_native_gpmf_available()=True`. `F:\GoPro\2026-10-09\GX010361.MP4`: kamera „GoPro” (pole camera_model), start nagrania 2026‑10‑09 04:27:55.839 UTC, czas 1574.34 s, **1573 payloady**, pierwszy GPS (40.3359305, 27.1676837); próbki: GPS 14 451, ACCL/GYRO 312 870, ISO/ekspozycja 47 183, temperatura 1 573; pełne parsowanie 2.14 s. Wynik: `etap5y_artifacts/probe_portable.txt`.

## 8. GUI
`python\python.exe -s -E C:\Temp\SCH-portable-5Y\SportCamHUD.py`, CWD = `C:\`, PATH bez systemowego Pythona: okno „SportCamHUD v1.14 — unknown — baf157b” po 30 s żywe, bez błędów importu; QtMultimedia (FFmpeg 7.1.3 LGPL), `MPV zinicjalizowany pomyślnie (GPU: AMD, hwdec=d3d11va…)`, `ExportQueue Initialized`, fonty rozwiązane. QtWebEngineWidgets importuje się z pakietu (aplikacja go nie używa w `src`). Etykieta „unknown” w tytule: `main_window.get_window_title` rozpoznaje tylko ścieżki zawierające `SportCamHUD-portable`/`SportCamHUD-main-new` — w docelowej lokalizacji będzie „Portable”; kosmetyczne.
Ręczne przejście zakładek i przycisku „Zapisz ustawienia”: **NOT TESTED** (brak interakcji z oknem w tym środowisku).

## 9. Podgląd
Backend podglądu (mpv + d3d11va) inicjalizuje się w pakiecie; harness ładuje projekt GX020079 w GUI pakietu przed eksportem. Odtwarzanie podglądu sterowane ręcznie: NOT TESTED.

## 10. AMD VBR i rzeczywisty QP (harness `--test-amd-export`, GX020079.mp4 + .fit, 300 klatek, 4K, HEVC FAST 40M)
Z pakietu: `native_dll=C:\Temp\SCH-portable-5Y\runtime\amd\bin\telem_amd_native.dll`, `rc=VBR target=40000000 peak=60000000`, `Hardware QP stats: avg=33.7 min=19 max=37 samples=300`, diag `ok=300 fail=0 get_results 0/0/0/0`. Wideo 38.8 Mb/s, 300 klatek. Przy tym samym `def_layout.json` w katalogu aplikacji MP4 z pakietu jest **bajtowo identyczny** z wersją dev (SHA `18363a48…`).
Kolor: źródło HLG 10‑bit BT.2020 (`yuv420p10le`, `arib-std-b67`), wynik 8‑bit `yuv420p`, transfer `bt709`, primaries/matrix nieoznaczone — identycznie w dev (istniejące zachowanie potoku NV12, nie zmieniane w tym etapie; do osobnej decyzji).
Uwaga: font domyślny HUD pochodzi z `def_layout.json` w katalogu aplikacji (szablon w pakiecie: „Digital-7 Mono”; layout użytkownika: „Digital-7”), dlatego pierwsze przebiegi P1/P2 różniły się fontem od dev; po podstawieniu layoutu użytkownika w kopii testowej (nie w pakiecie) wynik = dev.

## 11. Mapa, LEAN, polskie znaki (zrzut przed kompresją z pakietu, klatka 150, `run/portable_hud_precompress_f150.png`)
Mapa zaokrąglona z czerwoną ramką i Track‑Up, kompas, LEAN z tytułem „PRZECHYŁ”, linią i podziałką, „-0.9°” z graficznym pierścieniem, „ŚREDNIA PRĘDKOŚĆ” (fallback Segoe UI dla polskich liter, reszta Digital‑7), miejsca po przecinku jak w dev. PASS.

## 12. Direct Copy Audio (kanoniczny test `tests/test_mp4_audio_feed.py::test_real_gopro_native_copy_packets_and_live_mux[multi_trim]` uruchomiony na kodzie i binarkach kopii pakietu)
Dwa nagrania: `F:\GoPro\2026-10-07\GX010350.MP4` [10 s, 90 kl.] + `F:\GoPro\2026-10-12\GX010366.MP4` [20 s, 90 kl.]: **1 passed**. Jeden FFmpeg z pakietu, `-c copy`, `setts`, audio przez named pipe z oryginalnych pakietów AAC; 282 pakiety AAC identyczne (SHA danych) z wybranymi ze źródeł, granice 141/282, synchronizacja 5.33/5.67 ms, FFmpeg kończy 43 ms po EOF, finalizacja 1.04 ms; w katalogu tylko `final.mp4` + profil/logi (brak plików pośrednich, bez `-b:a`/filtrów). Dowody: `etap5y_artifacts/direct_copy_multi_trim_evidence.json`, `…_export.log`.

## 13. Render FPS (300 klatek, ta sama para, layout, ustawienia)
| | Render FPS |
|---|---|
| dev D1 / D2 | 41.317 / 39.566 (śr. 40.44) |
| portable P1 / P2 / P4 | 40.256 / 40.072 / 40.279 (śr. 40.20) |
Różnica w granicach rozrzutu powtórzeń; pakiet nie jest wolniejszy.

## 14. Uruchomienie z innej lokalizacji
Kopia `C:\Temp\SCH-portable-5Y` (robocopy ze stagingu), CWD `C:\`, PATH bez Pythona: ścieżki runtime (`app_root`, ffmpeg, ffprobe, DLL AMD/Intel, parser telemetrii) wskazują na kopię; brak wpisów `_DEV` w `sys.path`; DLL ładowane z kopii; log eksportu powstaje obok MP4 (`P1_portable.log` przy `P1_portable.mp4`); po wyłączeniu logowania w preferencjach (`%APPDATA%\SportCamHUD\app_preferences.json`) log nie powstaje (P6), preferencje przywrócone bajtowo. Ustawienia trafiają do `%APPDATA%`, nie do katalogu aplikacji; layout zapisywany przez GUI trafia do `def_layout.json` w katalogu aplikacji (portable: zapisywalny; w Program Files byłby problem). Log przy błędzie/anulowaniu: NOT TESTED w tym etapie. Profil użytkownika ma `startup_preset = C:/_DEV/defaut_lyout.json` — ustawienie profilu, nie zależność pakietu. Kopia testowa usunięta po testach.

## 15. Intel / NVIDIA
- Intel: DLL `telem_intel_native.dll` (`113abafb…`, przypięty) + biblioteki FFmpeg z `runtime/intel/bin` są w pakiecie; kod z commita (bez niezacommitowanych prac live mux). Eksport Intel: **NOT TESTED** (brak sprzętu Intel w tym teście).
- NVIDIA: w repozytorium nie ma zbudowanej `telem_nvenc_native.dll` (także w dev i w starym portable — tylko README), więc natywny NVENC nie jest dostępny ani w dev, ani w pakiecie; stan bez zmian. **NOT TESTED**.
Żaden backend nie został wyłączony.

## 16. Commit
`f3ba1bc3494f6089d2f317271d2afe8eb0dad5ff`.

## 17. Pakiet
**`C:\_DEV\BikeRideHUD-main-new\dist\portable-stage`** (start: `Start_SportCamHUD.cmd`). Stary `C:\_DEV\SportCamHUD-portable` nienaruszony — podmiana dopiero po potwierdzeniu użytkownika.

## 18. Problemy blokujące / otwarte przed wydaniem
- Redystrybucja FFmpeg GPLv3 wymaga dołączenia oferty źródeł (informacja jest w `THIRD_PARTY_NOTICES.txt`; decyzja dystrybucyjna należy do użytkownika).
- Rozmiar ~1.7 GB (PySide6 Addons ~460 MB, OpenCV ~120 MB); bez wbudowanego Pythona ~0.78 GB, ale wtedy wymagany Python 3.14 z pakietami.
- Testy ręczne GUI (zakładki, „Zapisz ustawienia”, startowy preset, kolejka) i log przy błędzie/anulowaniu: NOT TESTED.
- Wyjście 8‑bit SDR z materiału HLG — istniejące zachowanie, do osobnej decyzji.
- Intel/NVIDIA: NOT TESTED.
Żaden z tych punktów nie blokuje użycia pakietu na tym komputerze z AMD.

## ntfy
Wysyłane po zapisaniu raportu; wynik poniżej.

Wynik: wysłano, id=wQCXPZRVLxV6.
