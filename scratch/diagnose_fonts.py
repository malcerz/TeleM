import os
import winreg
from pathlib import Path
from PIL import ImageFont

print("=== 1. CHECKING WINDOWS FONT DIRS ===")
win_fonts_dir = Path(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")
local_fonts_dir = Path(os.environ.get("LOCALAPPDATA", ""), r"Microsoft\Windows\Fonts")
print(f"System Fonts Dir: {win_fonts_dir} (exists: {win_fonts_dir.exists()})")
print(f"User Fonts Dir:   {local_fonts_dir} (exists: {local_fonts_dir.exists()})")

print("\n=== 2. SCANNING FILES FOR DIGITAL / IONA / COMIC ===")
for d in [win_fonts_dir, local_fonts_dir]:
    if d.exists():
        for p in d.glob("*.*"):
            name_lower = p.name.lower()
            if any(k in name_lower for k in ["digital", "iona", "comic"]):
                print(f"  Found file: {p} (size={p.stat().st_size} bytes)")

print("\n=== 3. SCANNING WINDOWS REGISTRY (HKLM & HKCU) ===")
reg_keys = [
    (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Fonts", "HKLM"),
    (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Fonts", "HKCU"),
]

for root_h, subkey, label in reg_keys:
    try:
        with winreg.OpenKey(root_h, subkey) as k:
            count = winreg.QueryInfoKey(k)[1]
            print(f"{label} has {count} entries")
            for i in range(count):
                name, val, _ = winreg.EnumValue(k, i)
                name_l = name.lower()
                val_l = str(val).lower()
                if any(tag in name_l or tag in val_l for tag in ["digital", "iona", "comic"]):
                    print(f"  [{label}] \"{name}\" -> \"{val}\"")
    except Exception as e:
        print(f"  {label} error: {e}")

print("\n=== 4. TESTING QFontDatabase FAMILIES ===")
try:
    from PySide6.QtGui import QFontDatabase, QGuiApplication
    app = QGuiApplication.instance() or QGuiApplication([])
    families = QFontDatabase.families()
    print(f"Total QFontDatabase families: {len(families)}")
    matched = [f for f in families if any(k in f.lower() for k in ["digital", "iona", "comic"])]
    print(f"Matched families in QFontDatabase: {matched}")
except Exception as e:
    print(f"QFontDatabase error: {e}")
