# -*- coding: utf-8 -*-
import re
with open('src/gui/qt/main_window.py', 'r', encoding='utf-8') as f:
    text = f.read()

import_block = '''from src.version import APP_VERSION, APP_BUILD_COMMIT
import os

def get_window_title() -> str:
    title = f"BikeRideHUD v{APP_VERSION}"
    abs_path = os.path.abspath(__file__)
    if "BikeRideHUD-portable" in abs_path:
        repo_name = "Portable"
    elif "BikeRideHUD-main-new" in abs_path:
        repo_name = "main-new"
    else:
        repo_name = "unknown"
    if APP_BUILD_COMMIT and APP_BUILD_COMMIT != "unknown":
        return f"{title} — {repo_name} — {APP_BUILD_COMMIT}"
    return f"{title} — {repo_name}"

'''
text = re.sub(r'APP_TITLE = "BikeRideHUD"\s*APP_VERSION = "1\.0"', import_block, text)
text = text.replace('self.setWindowTitle(f"{APP_TITLE} v{APP_VERSION}")', 'self.setWindowTitle(get_window_title())')

with open('src/gui/qt/main_window.py', 'w', encoding='utf-8') as f:
    f.write(text)
