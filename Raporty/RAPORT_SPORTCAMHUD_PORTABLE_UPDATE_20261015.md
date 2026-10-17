# RAPORT — Aktualizacja SportCamHUD-portable (2026-10-15)

## Zadanie
Zaktualizować `C:\_DEV\SportCamHUD-portable` (wersja do skopiowania na inny komputer, możliwie kompaktowa) do najnowszej wersji.

## Stan początkowy
- Repo: `fix/gui-freeze-hud-composite` @ `f14e45f`. Niezacommitowane: `def_layout.json`, `src/ffmpeg/intel_native_exporter.py`, `src/ffmpeg/nvidia_native_exporter.py` (WIP live mux), nowy `src/ffmpeg/live_av_mux.py`, raporty.
- Stary portable: commit `2460ad7`, 1240 MB, 3582 pliki (pełna kopia deweloperska: build, native, debug, scratch, tests, mpv-dev, NVIDIA ffmpeg itd.). `Start_BikeRideHUD.cmd` wskazywał nieistniejący `BikeRideHUD.py`.
- `tools/build_portable_release.py` nieużywalny bez zmian: nieaktualny oczekiwany SHA DLL AMD, wymóg `runtime/common/telemetry` i `runtime/nvidia` (brak w repo), denylist `native` wyklucza wymagany `telem_gpmf_native.pyd`.

## Wykonanie
Skrypt jednorazowy (scratchpad, wzorowany na allowliście `build_portable_release.py`):
- top-level: `SportCamHUD.py`, `TeleMGP.py`, `Start_SportCamHUD.cmd`, `def_layout.json`, `telemetry_fit.py`, `telemetry_gpx.py`, `libmpv-2.dll`, `pyproject.toml`, `README.md`; `presets/*.json`; `wzor/rower_ico.png`;
- `src/` bez `__pycache__`, `native` (poza `src/native/gpmf/telem_gpmf_native.pyd`) i `egg-info`; ikony PNG (ignorowane przez git) dołączone;
- kod = HEAD `f14e45f`: dwa zmodyfikowane eksportery (Intel/NVIDIA) zastąpione wersją z HEAD, nieśledzony `live_av_mux.py` pominięty;
- `def_layout.json` = wersja z working tree (aktualny layout użytkownika);
- runtime: `common/ffmpeg` (ffmpeg/ffprobe), `amd/bin` (DLL SHA `380f86b0…a50b` = produkcyjny VBR z commita e76d6b1, + libwinpthread), `intel/bin` (DLL `113abafb…ba4b` + av*.dll), parser telemetrii (z `runtime/telemetry_parser` w repo) w `runtime/common/telemetry/telemetry_parser`, README licencji;
- pominięte: NVIDIA ffmpeg (`runtime/nvidia/ffmpeg`, nieużywany przez kod), dev/test/debug/raporty.
- `build_meta.json` = `{"commit": "f14e45f", "def_layout": "working tree"}`, `runtime/portable_manifest.json` z SHA-256 wszystkich plików.

Zamiana: stary → `C:\_DEV\SportCamHUD-portable-old_20261015` (zachowany, zawiera 46 unikalnych raportów), nowy → `C:\_DEV\SportCamHUD-portable`.

## Wynik
364 pliki, 775 MB (było 1240 MB / 3582 pliki).

## Testy
- `compileall src`: PASS.
- Import smoke z katalogu portable: `app_root` poprawny, ffmpeg/ffprobe/AMD DLL/Intel DLL/parser telemetrii obecne, GPMF native = True, `ctypes` load AMD DLL OK, import eksporterów AMD/Intel/NVIDIA i `src.gui.qt.application` OK: PASS.
- Uruchomienie GUI (`python SportCamHUD.py`, 20 s): start bez błędów, MPV d3d11va na AMD, ExportQueue zainicjalizowana: PASS.
- Rzeczywisty eksport AMD z portable: **NOT TESTED** (brak katalogu `Video/` z parą benchmarkową).
- Uruchomienie na innym komputerze: **NOT TESTED**.

## Ryzyka
- Portable nie zawiera Pythona: docelowy komputer potrzebuje Python 3.14 (parser telemetrii `cp314`) + zależności z `pyproject.toml` (PySide6, numpy, Pillow, opencv-python, fitparse, orjson, python-mpv, pyopencl, requests). Tak samo było w starej wersji.
- Font `Digital-7` jest zainstalowany w profilu użytkownika, nie w paczce; na innym komputerze zadziała fallback.
- Ustawienia/cache w `%APPDATA%`/`%LOCALAPPDATA%\SportCamHUD` (nie w folderze portable).

## Izolacja backendów
Brak zmian w kodzie repo. Paczka zawiera kod z HEAD bez niezacommitowanych zmian NVIDIA/Intel.

## Podsumowanie
PASS (build + import + start GUI). Eksport rzeczywisty: NOT TESTED.

## Dopisek: usunięcie starej wersji
Na polecenie użytkownika („usuń”): 46 unikalnych raportów skopiowano do `Raporty/_z_portable_old_20261015/`, a `SportCamHUD-portable-old_20261015` (1240 MB) przeniesiono do Kosza.
