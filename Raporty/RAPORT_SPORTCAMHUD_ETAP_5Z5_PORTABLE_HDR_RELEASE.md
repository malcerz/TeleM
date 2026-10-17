# SPORTCAMHUD — ETAP 5Z.5: portable z pełną obsługą HDR

Data: 2026-10-16. **STATUS: PASS**

Uwaga: treść zadania urwała się w punkcie 15 („Wydajność … koszt finalizacji, jeśli”). Wymagania dotyczące raportu, ntfy i zakończenia przyjęto według schematu etapów 5Z.x.

| test | wynik |
|---|---|
| Kompletność i samodzielność pakietu | PASS |
| Test poza repozytorium (`C:\Temp`, PATH bez Pythona, CWD `C:\`) | PASS |
| GUI: wykrycie HLG, selektor, domyślnie Zachowaj HDR, zapis/przywrócenie | PASS |
| A. Zachowaj HDR (Main10) | PASS |
| B. HLG → SDR | PASS |
| C. Podgląd edytora i eksportu | PASS |
| D. Kolejka HDR + SDR | PASS |
| E. GPMF / telemetria | PASS |
| F. SDR bez regresji | PASS |
| Wydajność portable = dev | PASS |

## 1. Git i stan
- HEAD na starcie: `2004bf69cbbfa906dd4bebdffc9477863a3bba2b` (stan 5Z.4 po punkcie 26 — PASS).
- Zastane zmiany (Intel/NVIDIA, `def_layout.json`, `live_av_mux.py`, raport 5R_F) nietknięte.
- Commit etapu: `29bbd7d7c3911a2e0aeca52325dfadb73f927df7` — fix(packaging): ship the ETAP 5Z.4 HDR AMD runtime. Jedyna zmiana kodu to `tools/build_portable_release.py`.
- Bez reset/clean/stash/rebase/merge/push.

## 2. DLL AMD
- `runtime/amd/bin/telem_amd_native.dll` przed i po: `e359d7784d2ff3d2b1aefb6cf56dc1ba3c38a67260fd8d87e27851ef0d55ee89` (UNCHANGED, bez przebudowy).
- ABI 9, `color_features=0x3`.
- build_id `telem-amd-native/1.0.0+b05db3bdd969.src848324a035d9`; source_hash odpowiada źródłom z commita `2004bf6`.
- Zależności MSVC (`msvcp140`, `vcruntime140`, `vcruntime140_1`) dołączone app-local z VS Redist.
- Packager ładuje DLL ze stagingu i sprawdza: ABI 9, wymagane eksporty (`telem_amd_get_abi_version`, `create`, `process_frame`, `update_map_style`, `get_encoder_qp_feedback_diag`, `set/poll_preview_tap`, `get_color_features`, `get_color_pipeline`, `probe_hevc_main10`) oraz cechy HLG (0x3). Błąd zatrzymuje budowanie.
- Pin SHA zmieniono na `e359d778…`. Do zakazanych dodano DLL 5Y (`5ad042bb…`) oraz 5Z.2/5Z.3 (`2ceb50cc…`).

## 3. Budowanie
- `python tools/build_portable_release.py --commit HEAD --target dist/portable-hdr-stage` — nowy, pusty katalog. `dist/portable-stage` (5Y) i `C:\_DEV\SportCamHUD-portable` nietknięte.
- Kod i szablony z commita `2004bf6` (git archive). Weryfikacja treści po normalizacji CRLF:
  - `hdr_color.py`, `amd_native_exporter.py`, `streaming.py`, `mpv_hwdec.py`, `render_tab.py`, `amd_hevc_preview.py` = HEAD;
  - `intel_native_exporter.py`, `nvidia_native_exporter.py` = HEAD, **nie** wersje niezacommitowane;
  - `def_layout.json` = szablon z commita, **nie** prywatny plik użytkownika;
  - `live_av_mux.py` nie trafił do pakietu.
- Binarki z jawnych ścieżek working tree z kontrolą SHA. Python 3.14.7 wbudowany z domknięciem zależności.

## 4. Manifest (`portable_manifest.json`, schemat v3, rozszerzony minimalnie)

| pole | wartość |
|---|---|
| aplikacja | SportCamHUD 1.14 |
| source_commit | `2004bf69cbbf…` |
| build_date_utc | 2026-10-16T10:45:57+00:00 |
| Python / PySide6 / numpy / python-mpv / opencv | 3.14.7 / 6.11.1 / 2.5.1 / 1.0.8 / 5.0.0.93 |
| FFmpeg | 2026-08-17-git-426841da9d full_build (gyan.dev) |
| amd_native | abi 9, color_features 3, required_exports, build_info |
| AMD DLL | `e359d7784d2ff3d2…` |
| Intel DLL | `113abafbab0c877b…` |
| libmpv-2.dll | `7079ebfba8459573…` (mpv v0.41.0-920) |
| GPMF `telem_gpmf_native.pyd` | `a47757fcdf26d680…` |
| telemetry_parser `.pyd` | `32e8a0a21489bf32…` |
| ffmpeg.exe / ffprobe.exe | `d95d1567c9865eb9…` / `68fdc500201dc0c2…` |
| MSVC | msvcp140 `0f885b50…`, vcruntime140 `d5e4d9a3…`, vcruntime140_1 `1f2d41c4…` |
| pliki / rozmiar | 6320 / 1 707 699 607 B (1,71 GB) |
| binary_sources | źródło każdej binarki |

Używana DLL jest ustalona w diagnostyce (`runtime_paths.get_amd_native_dll` → `<portable>\runtime\amd\bin\…`) oraz w `amd_native.build_info`.

## 5. Test poza repozytorium (`C:\Temp\SportCamHUD-HDR-Portable-Test`, `portable_env.json`)
- Python `C:\Temp\…\python\python.exe` 3.14.7.
- PATH bez wpisów Pythona, uruchomienie z `C:\`.
- Wszystkie moduły aplikacji ładowane z kopii (jedyny wpis `_DEV` w sys.path to katalog skryptu testowego).
- AMD DLL: ścieżka z kopii, ABI 9, cechy 3, **rzeczywista próba Main10 = 1**.
- mpv v0.41 z opcjami 5Z.4: `tone-mapping=bt.2390`, `hdr-compute-peak=no`, `gamut-mapping-mode=relative`, `hdr-contrast-recovery=0`.
- PySide6 6.11.1 (QtWidgets, QtMultimedia); ffmpeg z `runtime/common/ffmpeg`.
- Klasyfikacja GX020079: HLG full.
- **Launcher**: `Start_SportCamHUD.cmd --test-amd-export …` uruchomiony z `C:\`, z PATH bez Pythona → exit 0, eksport 120 kl. success. Launcher wybiera `python\python.exe -s -E`.

## 6. GUI i ustawienia
- Harness (GUI) z pakietu:
  - GX020079: `kind=hlg`, selektor HDR **widoczny**, domyślnie `preserve_hlg`;
  - DJI_0010: `kind=sdr`, selektor **ukryty**.
- Zapis i przywrócenie przez istniejący mechanizm (`_on_settings_changed` → `_save_global_settings_to_default` → `def_layout.json` w katalogu aplikacji), w osobnych procesach portable: zapis `tonemap_sdr` → nowy proces przywraca `tonemap_sdr` (True); zapis `preserve_hlg` → przywraca `preserve_hlg` (True).
- Zmiana zakładki nie resetuje wyboru (stan kontrolki, potwierdzone w 5Z.2).
- Niejednoznaczne metadane: z pakietu plik nie-wideo i plik nieistniejący dają `unknown` → odmowa (5Z.3).

## 7. Test A — Zachowaj HDR (`run/PT_keep*`)
- GX020079 + FIT, 4K, FAST, 40M, 300 kl., layout 5Y.
- hvcC profil 2, 10/10 bit; SPS profile_idc 2, bit_depth −8 = 2/2, full_range 1; VUI i colr nclx 9/18/9 full; yuv420p10le; 74,9% próbek nie jest wielokrotnością 4 (prawdziwe 10 bit).
- Pipeline `HLG_PRESERVE` (applied), QP 33,7 (18–37), 300 próbek; VBR 40M; AAC FEED 320 071 B `completed=True`; jeden FFmpeg (Single Live Mux, `-c copy`).

## 8. Test B — HLG → SDR (`run/PT_tm*`)
- hvcC profil 1, 8 bit; SPS full_range 0; VUI i colr 1/1/1 limited; yuv420p; brak metadanych HDR.
- Pipeline `HLG_TO_SDR`, QP 33,4, 300 próbek, VBR 40M, AAC Direct Copy.

**Zgodność z wersją developerską (identyczne ustawienia i layout):**
- Przy szablonowym `def_layout.json` wideo różni się od dev. Przyczyną jest globalny font: szablon dystrybucyjny ma `global.font = "Digital-7 Mono"`, a prywatny `def_layout.json` w repo ma `"Digital-7"` (log `[FONT RESOLVER]`). Różnice występują tylko w cyfrowych tekstach HUD (`cmp/dev_vs_portable_top.png`). To ustawienie użytkownika, nie błąd pakowania.
- Po ustawieniu tego samego fontu w **testowej** kopii (`C:\Temp`, nie w pakiecie): **wideo bitowo identyczne** — Main10 `5053b230d1bb93b283eae7ee3aae5adb` (dev = portable), HLG→SDR `469ca74d2a8162854ede8449711c3726` (dev = portable); audio `913c9de6…` identyczne.

## 9. Test C — podgląd
- **Edytor (mpv z pakietu):** zrzut okna libmpv HLG vs eksport SDR w tym samym mpv → MAE 7,56 / 7,83 / 6,02, średnio **7,14** (identycznie jak dev w 5Z.4; poprzedni stan 19,45). Zmierzono przez `screenshot-raw window`, czyli obraz po zarządzaniu kolorem mpv. HUD w edytorze to okno Qt nad mpv (bez zmian).
- **Podgląd eksportu „Zachowaj HDR”:** natywny tap z 5Z.4 (shader HLG→SDR, 960×540), 20 klatek → **MAE 7,45**, luma +1,23 względem MP4 HLG→SDR (stara ścieżka VP: 17,65 / −10,1).
- **Podgląd eksportu „Konwertuj do SDR”:** tap z finalnej klatki NV12 → MAE 9,98 (jak w dev; różnice ze skalowania VP i kompresji).
- W obu trybach: brak dodatkowego dekodera i FFmpeg; Main10 z podglądem jest bitowo równy temu bez nowego tapu (5Z.4).

## 10. Test D — kolejka (`run/PT_queue*`)
- 2 zadania dodane z `preserve_hlg` i `tonemap_sdr`, potem zmiana GUI. Zamrożone tryby: `[preserve_hlg, tonemap_sdr]`.
- Zadanie 1: profil 2, 10 bit, colr 9/18/9 full, pipeline HLG_PRESERVE, QP 300 próbek.
- Zadanie 2: profil 1, 8 bit, colr 1/1/1, pipeline HLG_TO_SDR, QP 300.
- Osobne logi, po jednym FFmpeg na zadanie (różne PID), statusy done, bez zawieszenia.

## 11. Test E — GPMF z pakietu
- Moduł `C:\Temp\…\src\native\gpmf\telem_gpmf_native.pyd`, `is_native_gpmf_available=True`, brak brakujących DLL.
- `F:\GoPro\2026-10-09\GX010361.MP4`: kamera **GoPro**, start **2026-10-09 04:27:55.839 UTC**, **1573 payloady**, czas 1574,34 s — zgodnie z oczekiwaniem.

## 12. Test F — SDR (`run/PT_sdr*`)
- DJI_0010: pipeline SDR (shader HLG nieaktywny), selektor ukryty.
- Przebieg rozgrzany: wideo `43e50a3206e54a4e52e5459d59c895a5`, audio `1b9e2120932feaf5cad50faffdc66677` — **identyczne z dev i produkcją sprzed HDR**.
- Pierwszy przebieg każdej sesji daje `3f2dc4…`: znany wariant zimnego cache telemetrii (klatki 0–119), identyczny w dev.

## 13. Wydajność (4K, 300 kl., FAST, 40M, GX020079 + FIT, layout 5Y)
| wariant | Render FPS | Effective FPS |
|---|---|---|
| portable Zachowaj HDR | 39,89 / 41,75 / 41,29* | 27,35–27,56 |
| dev Zachowaj HDR | 39,38 (ta sama sesja) | 25,99 |
| portable HLG → SDR | 39,67 / 40,86 / 41,34* | 27,18–27,80 |
| dev HLG → SDR | 38,76 | 26,27 |
| portable SDR DJI_0010 | 38,69 (rozgrzany) | 27,48 |
| portable kolejka (2 zad.) | 40,02 | 27,5 / 30,6 |

\* z włączonym podglądem eksportu.

- Portable ≥ dev w tej samej sesji; w zakresie 5Z.4 (40–41) i powyżej 5Y (40,2).
- Czas przygotowania i finalizacji zawiera się w Effective FPS (harness nie raportuje ich osobno).

## 14. Ochrona
- Nie zmieniono: DLL, kodowania, HUD, tone mappingu, audio (Original AAC Direct Copy, Single Live Mux), VBR/QP, Intel/NVIDIA, MSIX, starego portable.
- `def_layout.json` repo: `65fa8390d1cda70ed8d115631a75e35559b24b9990e1ca15f944f0fb371606f4` przed i po.
- Testowa kopia `C:\Temp\…` ma zmieniony tylko `global.font` / `amd_hdr_mode` na potrzeby testu (kopia oryginału: `Raporty/etap5z5_artifacts/run/portable_def_layout.backup.json`); staging `dist/portable-hdr-stage` ma szablon z commita.

## 15. Ograniczenia
1. Font cyfrowy HUD zależy od ustawienia użytkownika (`global.font`) i fontów zainstalowanych w Windows. Pakiet nie zawiera fontów (zgodnie z wymaganiem). Na komputerze bez Digital-7 działa fallback (5Y).
2. Pakiet ma 1,71 GB (pełne PySide6 i Qt, jak w 5Y).
3. Ekran HDR nie testowany (patrz 5Z.4).
4. `C:\Temp\SportCamHUD-HDR-Portable-Test` pozostaje (1,7 GB) do porównań; do usunięcia za zgodą.

## 16. Artefakty
`Raporty/etap5z5_artifacts/`:
- `portable_env.json`, `run/*.json|log|stdout.txt|color.json`;
- `tap_compare.json` (w `etap5z4_artifacts`), `mpv_portable.json`;
- `cmp/dev_vs_portable_*.png`;
- skrypty `run_5z5_export.py`, `portable_env_check.py`, `settings_persist_check.py`, `diff_regions.py`, `diff_hotspots.py`, `patch_packager.py`.

Duże MP4 usunięto.

ntfy: wysłane po zapisaniu raportu, "id":"m1Lk6UMEMiCg", HTTP 200.
