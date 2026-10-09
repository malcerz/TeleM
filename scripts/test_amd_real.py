import os
import sys
import time
from pathlib import Path
from PySide6.QtWidgets import QApplication

def run_test():
    from src.gui.qt.main_window import MainWindow
    
    app = QApplication.instance() or QApplication(sys.argv)
    window = MainWindow()
    
    # Wait for init
    app.processEvents()
    
    mp4_path = r"F:\GoPro\2026-10-09\GX010361.MP4"
    if not os.path.exists(mp4_path):
        print(f"Skipping: test mp4 {mp4_path} not found.")
        sys.exit(1)
        
    # Drive UI to load video
    window._load_tab.set_video_paths([mp4_path], start_search=True)
    window._load_tab._on_load()
    app.processEvents()
    
    # Wait for project to be fully loaded
    t_wait = time.time()
    while not window._controller._project_manager.is_project_ready() if hasattr(window, "_controller") else False:
        app.processEvents()
        time.sleep(0.1)
        if time.time() - t_wait > 30:
            print("Timeout waiting for project ready.")
            sys.exit(1)
            
    # Truncate to 150 frames
    # window._render_tab.edit_duration.setText("5") # Export 5 seconds instead of frame count if possible, or use API
    # The actual API for setting export range:
    vt = window._controller._project_manager._video_timeline
    vt.set_export_range(0, 300)
    
    # Ensure AMD backend
    window._settings_tab.cmb_video_backend.setCurrentText("amd")
    window._settings_tab._on_save()
    
    direct_out = os.path.abspath("direct_export_real.mp4")
    if os.path.exists(direct_out): os.remove(direct_out)
    
    print("\n--- STARTING DIRECT EXPORT ---")
    window._render_tab.edit_output.setText(direct_out)
    window._render_tab._on_export_click()
    
    t0 = time.time()
    while window._render_tab.thread and window._render_tab.thread.isRunning():
        app.processEvents()
        time.sleep(0.1)
        if time.time() - t0 > 120:
            print("Direct export timeout!")
            break
            
    print(f"Direct Export finished in {time.time() - t0:.2f}s")
    
    queue_out = os.path.abspath("queue_export_real.mp4")
    if os.path.exists(queue_out): os.remove(queue_out)
    
    print("\n--- STARTING QUEUE EXPORT ---")
    window._render_tab.edit_output.setText(queue_out)
    window._render_tab._on_queue_add()
    window._render_tab._on_queue_start()
    
    t0 = time.time()
    q = window._render_tab._export_queue
    while q and q.is_running():
        app.processEvents()
        time.sleep(0.1)
        if time.time() - t0 > 120:
            print("Queue export timeout!")
            break
            
    print(f"Queue Export finished in {time.time() - t0:.2f}s")
    
    verify_output(direct_out, "DIRECT")
    verify_output(queue_out, "QUEUE")
    
    # cleanup
    try: os.remove("direct_export_real.mp4")
    except: pass
    try: os.remove("queue_export_real.mp4")
    except: pass
    
    sys.exit(0)

def verify_output(out_path, name):
    if not os.path.exists(out_path):
        print(f"[{name}] FAIL: Output file does not exist!")
        return
        
    from src.ffmpeg.ffprobe import FFprobeInspector
    inspector = FFprobeInspector(out_path)
    meta = inspector.get_metadata()
    
    frames = meta.get("video_frames", 0)
    fps = meta.get("video_fps", 0)
    audio = meta.get("audio_codec") is not None
    
    print(f"[{name}] RESULT: {frames} frames | {fps} FPS | Audio: {audio}")
    if frames < 100:
        print(f"[{name}] FAIL: Too few frames!")
    else:
        print(f"[{name}] PASS")

if __name__ == '__main__':
    run_test()
