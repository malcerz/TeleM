import sys
import time
from pathlib import Path
from PySide6.QtWidgets import QApplication, QWidget
from PySide6.QtCore import QTimer

from src.gui.qt.controller import AppController
from PySide6.QtCore import Qt

def run_test():
    app = QApplication(sys.argv)
    
    # Create the controller
    controller = AppController()
    
    # Create a plain widget instead of VideoOverlayContainer
    container = QWidget()
    container.setAttribute(Qt.WA_NativeWindow, True)
    container.setAttribute(Qt.WA_DontCreateNativeAncestors, True)
    container.setAttribute(Qt.WA_OpaquePaintEvent, True)
    container.setAttribute(Qt.WA_NoSystemBackground, True)
    container.setStyleSheet("background-color: #000000;")
    container.resize(1280, 720)
    container.show()
    controller.set_video_widget(container)
    
    frames = 0
    trigger_calls = 0
    start_time = 0
    
    def on_frame(qimg):
        nonlocal frames
        print("F", end="", flush=True)
        frames += 1
        
    controller.signals.sig_preview_frame_ready.connect(on_frame)
    
    print("[TEST] Setting up video...")
    test_video = str(Path("Video/GX020079.MP4").resolve())
    controller._on_files_selected([test_video], "", "")
    
    def start_playback(_):
        nonlocal start_time, frames, trigger_calls
        print("[TEST] Telemetry loaded. Starting playback...")
        # Reset counters
        frames = 0
        trigger_calls = 0
        
        controller._on_playback_start()
        start_time = time.time()
        
        # Stop playback and measure after 5 seconds of playing
        QTimer.singleShot(5000, end_test)
        
    # Wait for telemetry to finish loading before starting playback
    controller.signals.sig_data_streams_ready.connect(start_playback)
    
    def end_test():
        nonlocal start_time, frames
        duration = time.time() - start_time
        fps = frames / duration if duration > 0 else 0
        
        mpv_fps = 0.0
        if controller.mpv_player:
            try:
                mpv_fps = controller.mpv_player.estimated_vf_fps
            except:
                pass
                
        print("-" * 40)
        print(f"Test Duration: {duration:.2f} seconds")
        print(f"HUD Rendered Frames: {frames}")
        print(f"HUD Trigger Calls: {trigger_calls}")
        print(f"HUD FPS: {fps:.2f} fps")
        if mpv_fps:
            print(f"MPV Estimated Video FPS: {mpv_fps:.2f} fps")
        print("-" * 40)
        app.quit()
        
    sys.exit(app.exec())

if __name__ == "__main__":
    run_test()
