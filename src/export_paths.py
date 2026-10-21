"""User-level export directory preference and safe output path resolution."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Iterable


def preferences_path() -> Path:
    """Return the user profile preferences file beside other app data."""
    base = Path(os.environ.get("APPDATA") or (Path.home() / "AppData" / "Roaming"))
    return base / "SportCamHUD" / "app_preferences.json"


def load_default_export_dir() -> str | None:
    """Return the saved global directory, or None if no preference exists."""
    path = preferences_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        value = data.get("default_export_dir")
        return str(value or "") if isinstance(value, (str, Path)) else None
    except (OSError, ValueError, TypeError, AttributeError):
        return None


def load_app_preferences() -> dict:
    """Return all saved user-level preferences (empty dict when none)."""
    try:
        data = json.loads(preferences_path().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def load_charts_skip_pauses(base_dir: Path | None = None) -> bool:
    """Global 'Pomiń pauzy aktywności' value.

    The user profile preference wins; without it the legacy value from
    def_layout.json is used (read-only), then False.
    """
    value = load_app_preferences().get("charts_skip_pauses")
    if isinstance(value, bool):
        return value
    if base_dir is not None:
        try:
            data = json.loads((Path(base_dir) / "def_layout.json").read_text(encoding="utf-8"))
            legacy = data.get("charts_skip_pauses")
            if legacy is None and isinstance(data.get("global"), dict):
                legacy = data["global"].get("charts_skip_pauses")
            if legacy is not None:
                return bool(legacy)
        except (OSError, ValueError, TypeError, AttributeError):
            pass
    return False


def load_startup_preset(base_dir: Path | None = None) -> str:
    """Saved 'Startowy preset' path.

    The user profile preference wins; without it the legacy ``_startup_preset``
    from def_layout.json is used (read-only), then "".
    """
    value = load_app_preferences().get("startup_preset")
    if isinstance(value, str):
        return value
    if base_dir is not None:
        try:
            data = json.loads((Path(base_dir) / "def_layout.json").read_text(encoding="utf-8"))
            legacy = data.get("_startup_preset")
            if isinstance(legacy, str):
                return legacy
        except (OSError, ValueError, TypeError, AttributeError):
            pass
    return ""


def startup_preset_conflict(startup_preset: str, saved_path: Path | str) -> str:
    """Warning text when another existing file is the 'Startowy preset'.

    That file — not ``saved_path`` — is what the next project open / app
    start loads, so a layout saved elsewhere looks as if it was not saved.
    """
    preset = str(startup_preset or "").strip()
    if not preset or not Path(preset).is_file():
        return ""
    try:
        if Path(preset).resolve() == Path(saved_path).resolve():
            return ""
    except OSError:
        pass
    return (
        "Układ zapisano do:\n"
        f"{saved_path}\n\n"
        "Ale jako „Startowy preset” ustawiony jest INNY plik:\n"
        f"{preset}\n\n"
        "Przy następnym uruchomieniu lub otwarciu MP4 zostanie wczytany tamten plik, "
        "a nie zapisany układ. Ustaw „Startowy preset” na zapisany plik albo wyczyść "
        "to pole w Ustawieniach i kliknij „Zapisz ustawienia”."
    )


def load_amd_export_logging_enabled() -> bool:
    """Global 'Zapisuj log eksportu AMD' value (default ON)."""
    value = load_app_preferences().get("amd_export_logging_enabled")
    return value if isinstance(value, bool) else True


def save_default_export_dir(value: str) -> None:
    """Persist only this global preference; never write it into a layout."""
    update_app_preferences({"default_export_dir": str(value or "")})


def update_app_preferences(values: dict) -> None:
    """Atomically merge ``values`` into the user profile preferences file."""
    path = preferences_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    data: dict = {}
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            data = loaded
    except (OSError, ValueError, TypeError):
        pass
    data.update(values)
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=path.parent, prefix=".app_preferences_",
        suffix=".tmp", delete=False,
    ) as stream:
        temp_path = Path(stream.name)
        json.dump(data, stream, indent=2, ensure_ascii=False)
        stream.write("\n")
    try:
        temp_path.replace(path)
    finally:
        temp_path.unlink(missing_ok=True)


def legacy_default_export_dir(layout: dict | None = None, base_dir: Path | None = None) -> str:
    """Read a legacy layout value without modifying the layout file."""
    layout = layout if isinstance(layout, dict) else {}
    value = layout.get("default_export_dir")
    if value is None:
        global_settings = layout.get("global")
        if isinstance(global_settings, dict):
            value = global_settings.get("default_export_dir")
    if value:
        return str(value)
    if base_dir is not None:
        try:
            data = json.loads((base_dir / "def_layout.json").read_text(encoding="utf-8"))
            global_settings = data.get("global")
            value = data.get("default_export_dir")
            if not value and isinstance(global_settings, dict):
                value = global_settings.get("default_export_dir")
            if value:
                return str(value)
        except (OSError, ValueError, TypeError, AttributeError):
            pass
    return ""


def is_export_dir_usable(path: str | Path) -> bool:
    """Check that an existing directory can accept a temporary file."""
    directory = Path(path).expanduser()
    if not directory.is_absolute() or not directory.is_dir():
        return False
    probe_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", dir=directory, prefix=".sportcamhud_write_test_", delete=False
        ) as probe:
            probe_path = Path(probe.name)
        return True
    except OSError:
        return False
    finally:
        if probe_path is not None:
            try:
                probe_path.unlink(missing_ok=True)
            except OSError:
                pass


def requires_deferred_validation(path: str | Path) -> bool:
    """Identify remote/removable Windows paths that must not be probed in GUI."""
    value = str(path)
    if value.startswith(("\\\\", "//")):
        return True
    candidate = Path(value)
    drive = candidate.drive
    if not drive or len(drive) < 2 or drive[1] != ":":
        return False
    try:
        import ctypes

        drive_type = ctypes.windll.kernel32.GetDriveTypeW(drive + "\\")
        # DRIVE_REMOVABLE=2, DRIVE_REMOTE=4, DRIVE_CDROM=5.
        return drive_type in {2, 4, 5}
    except (AttributeError, OSError):
        return False


def resolve_export_path(
    output: str | Path,
    *,
    source_paths: Iterable[str | Path],
    configured_dir: str | Path | None = None,
    legacy_dir: str | Path | None = None,
    defer_remote_validation: bool = False,
) -> Path:
    """Resolve explicit output first, then preference/legacy, then source parent.

    Invalid configured/legacy preferences fall back to the source directory with
    a diagnostic. An explicit absolute path is honored or rejected; it is never
    silently redirected. No directories are created here.
    """
    output_path = Path(output).expanduser()
    if output_path.is_absolute():
        parent = output_path.parent
        if defer_remote_validation and requires_deferred_validation(parent):
            return output_path
        if not is_export_dir_usable(parent):
            raise RuntimeError(f"Wybrany katalog eksportu jest niedostępny lub niezapisywalny: {parent}")
        return output_path

    sources = [Path(p).expanduser() for p in source_paths if str(p).strip()]
    source_dir = next((p.parent for p in sources if p.is_file()), None)
    if source_dir is None:
        source_dir = next((p.parent for p in sources if p.suffix.lower() in {".mp4", ".mov", ".m4v"}), None)

    chosen = str(configured_dir or "").strip()
    if not chosen:
        chosen = str(legacy_dir or "").strip()
    if chosen:
        candidate = Path(chosen).expanduser()
        if defer_remote_validation and requires_deferred_validation(candidate):
            return candidate / output_path
        if is_export_dir_usable(candidate):
            return candidate / output_path
        print("[EXPORT DIR] configured directory unavailable, using source directory", flush=True)

    if source_dir is not None and is_export_dir_usable(source_dir):
        return source_dir / output_path
    raise RuntimeError("Brak dostępnego katalogu eksportu i zapisywalnego folderu pliku źródłowego.")
