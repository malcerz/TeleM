import os
import re
import winreg
from pathlib import Path
from typing import Optional


_SYSTEM_FONT_MAP_CACHE: Optional[dict[str, str]] = None


def _build_windows_font_map() -> dict[str, str]:
    """Build a mapping from lower-case font names/families to absolute file paths."""
    font_map: dict[str, str] = {}
    if os.name != "nt":
        return font_map

    win_dir = Path(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")
    local_dir = Path(os.environ.get("LOCALAPPDATA", ""), r"Microsoft\Windows\Fonts")
    search_dirs = [local_dir, win_dir]

    # 1. Scan registry (HKLM and HKCU)
    reg_keys = [
        (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Fonts"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Fonts"),
    ]

    for root_h, subkey in reg_keys:
        try:
            with winreg.OpenKey(root_h, subkey) as k:
                count = winreg.QueryInfoKey(k)[1]
                for i in range(count):
                    raw_name, raw_val, _ = winreg.EnumValue(k, i)
                    val_str = str(raw_val).strip()
                    if not val_str:
                        continue

                    # Resolve candidate path
                    val_path = Path(val_str)
                    resolved_file: Optional[Path] = None
                    if val_path.is_absolute() and val_path.is_file():
                        resolved_file = val_path
                    else:
                        for sdir in search_dirs:
                            cand = sdir / val_str
                            if cand.is_file():
                                resolved_file = cand
                                break

                    if not resolved_file:
                        continue

                    file_str = str(resolved_file)

                    # Clean registry name, e.g. "Digital-7 (TrueType)" -> "Digital-7"
                    clean_name = re.sub(r"\s*\([^)]*\)$", "", raw_name).strip().lower()
                    if clean_name and clean_name not in font_map:
                        font_map[clean_name] = file_str

                    # Also map filename stem (e.g. "digital-7")
                    stem = resolved_file.stem.lower()
                    if stem not in font_map:
                        font_map[stem] = file_str
                    # And raw name
                    raw_lower = raw_name.strip().lower()
                    if raw_lower not in font_map:
                        font_map[raw_lower] = file_str
        except Exception:
            pass

    # 2. Also index files directly from font directories
    for sdir in search_dirs:
        if sdir.exists():
            try:
                for p in sdir.glob("*.*"):
                    if p.suffix.lower() in {".ttf", ".otf", ".ttc"}:
                        stem = p.stem.lower()
                        if stem not in font_map:
                            font_map[stem] = str(p)
            except Exception:
                pass

    return font_map


def resolve_font_path(font_name_or_path: str, default: Optional[str] = None) -> str:
    """Resolve a font name, family, or file path to an absolute font file path."""
    global _SYSTEM_FONT_MAP_CACHE
    raw = str(font_name_or_path or "").strip()
    if not raw:
        return default or ""

    # 1. Check if it is an existing file (absolute or relative)
    p = Path(raw)
    if p.is_file():
        return str(p.resolve())

    # 2. Check Windows font mapping
    if _SYSTEM_FONT_MAP_CACHE is None:
        _SYSTEM_FONT_MAP_CACHE = _build_windows_font_map()

    raw_lower = raw.lower()
    # Exact match
    if raw_lower in _SYSTEM_FONT_MAP_CACHE:
        return _SYSTEM_FONT_MAP_CACHE[raw_lower]

    # Prefix / substring match
    for k, v in _SYSTEM_FONT_MAP_CACHE.items():
        if k.startswith(raw_lower) or raw_lower.startswith(k):
            return v

    # 3. Direct extension search in font dirs
    if os.name == "nt":
        win_dir = Path(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")
        local_dir = Path(os.environ.get("LOCALAPPDATA", ""), r"Microsoft\Windows\Fonts")
        for sdir in [local_dir, win_dir]:
            for ext in (".ttf", ".otf", ".ttc"):
                cand = sdir / f"{raw}{ext}"
                if cand.is_file():
                    return str(cand.resolve())

    return default if default is not None else raw


# Test resolution
for test_font in ["Digital-7", "digital-7", "Digital-7 Mono", "Iona-u1", "IONA-U1", "Comic Sans", "Comic Sans MS", "Arial", "NonExistentFont"]:
    res = resolve_font_path(test_font, default="DEFAULT_FALLBACK")
    print(f"'{test_font}' -> '{res}'")
