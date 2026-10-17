# RAPORT — Kopia zapasowa aplikacji na F: (2026-10-15)

## Zadanie
Kopia bezpieczeństwa aplikacji w ZIP na dysku F:.

## Wynik
- Plik: `F:\SportCamHUD_BACKUPS\SportCamHUD_backup_20261015_1704.zip`
- Rozmiar: 2 505 627 498 B (2390 MiB), 3357 plików, 441 folderów, dane źródłowe 3371 MiB.
- SHA256: `42CFCB36B419BF75B358DA8C9591DBA01086F4BAE301EC77D203DE854B7BF091`
- Test `7z t`: Everything is Ok.

## Zawartość
Cały `C:\_DEV\BikeRideHUD-main-new` w stanie z HEAD `cbe0dd4` (`fix/gui-freeze-hud-composite`) razem z:
- `.git` (pełna historia, wszystkie gałęzie i tagi),
- niezacommitowanymi zmianami (`def_layout.json`, eksportery NVIDIA/Intel, `live_av_mux.py`),
- `runtime/` (ffmpeg, DLL AMD z poprawką QP i kopia `.bak_pre_qpfeedback`, DLL Intel),
- `native/`, `Raporty/`, `tests/`, `presets/`, `wzor/`.

Pominięto (odtwarzalne): `.venv`, `cache/` (cache telemetrii renderu), `scratch/`, `__pycache__`, `.pytest_cache`, `.ruff_cache`.

## Odtworzenie
Rozpakować do `C:\_DEV\`, utworzyć `.venv` i zainstalować zależności z `pyproject.toml`.

## Podsumowanie
PASS.
