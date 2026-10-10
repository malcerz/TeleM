import sys
import time
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer

print("A. Importing src.ffmpeg")
import src.ffmpeg
print("B. Importing src.ffmpeg.output_error")
import src.ffmpeg.output_error
print("C. Importing src.ffmpeg.render_errors")
import src.ffmpeg.render_errors
print("D. Importing src.integrations.garmin_auth")
import src.integrations.garmin_auth
print("E. Importing src.integrations.garmin_connect")
import src.integrations.garmin_connect
print("F. Importing src.gui.qt.application")
import src.gui.qt.application
print("G. Checking SportCamHUD imports")
import SportCamHUD
print("Smoke test pass.")
