import sys
import time
from PySide6.QtWidgets import QApplication

def check_gui(dir_path):
    sys.path.insert(0, dir_path)
    from src.gui.qt.main_window import MainWindow
    
    app = QApplication.instance() or QApplication(sys.argv)
    window = MainWindow()
    app.processEvents()
    
    title = window.windowTitle()
    print(f"[{dir_path}] Window Title: {title}")
    assert "BikeRideHUD" in title
    
    sys.path.pop(0)
    
if __name__ == '__main__':
    check_gui(r"C:\_DEV\BikeRideHUD-main-new")
    check_gui(r"C:\_DEV\BikeRideHUD-portable")
    print("STARTUP: PASS")
