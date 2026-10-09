# -*- coding: utf-8 -*-
with open('src/gui/qt/main_window.py', 'r', encoding='utf-8') as f:
    text = f.read()

import_block = '''from src.version import APP_VERSION, APP_BUILD_COMMIT
import os

APP_TITLE = "BikeRideHUD"

def get_window_title() -> str:
'''

text = text.replace('from src.version import APP_VERSION, APP_BUILD_COMMIT\nimport os\n\ndef get_window_title() -> str:\n', import_block)

with open('src/gui/qt/main_window.py', 'w', encoding='utf-8') as f:
    f.write(text)
