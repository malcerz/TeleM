import os, sys, time
from pathlib import Path

os.add_dll_directory(r'C:\_DEV\TeleM-integration')
os.add_dll_directory(r'C:\_DEV\TeleM')
os.environ['PATH'] = r'C:\_DEV\TeleM-integration;' + r'C:\_DEV\TeleM;' + os.environ.get('PATH', '')
sys.path.insert(0, r'C:\_DEV\TeleM-integration')

from PySide6.QtWidgets import QApplication
from src.gui.qt.controller import AppController
from src.gui.qt.main_window import MainWindow

app = QApplication.instance() or QApplication(sys.argv)

print('=== STARTING REAL QT MULTIFILE MPV PLAYBACK TEST ===')

ctrl = AppController()
window = MainWindow()
window.set_controller(ctrl)

v14 = r'C:\_DEV\TeleM\Video\GX010114.MP4'
v15 = r'C:\_DEV\TeleM\Video\GX010115.MP4'
v16 = r'C:\_DEV\TeleM\Video\GX010116.MP4'
fit = r'C:\_DEV\TeleM\Video\GX010114_116.fit'

print(f'Loading project with {[v14, v15, v16]}...')
ctrl._on_files_selected([v14, v15, v16], gpx_path='', fit_path=fit)

# Wait for project load to finish (runs in bg_load thread)
for _ in range(100):
    app.processEvents()
    time.sleep(0.1)
    if ctrl.video_timeline is not None and getattr(ctrl, 'last_src_pil', None) is not None:
        break

print('Project loaded.')
print(f'Timeline clip_count: {ctrl.video_timeline.clip_count if ctrl.video_timeline else None}')
print(f'Timeline project_duration_s: {ctrl.video_timeline.project_duration_s if ctrl.video_timeline else None}')
print(f'Controller is_using_mpv: {ctrl.is_using_mpv()}')
print(f'Active clip index: {ctrl._active_preview_clip_index}')

# Check seek bar duration label
print(f'Preview duration label text: {window.preview.duration_label.text()}')
print(f'Preview seek bar duration: {window.preview.seek_bar._duration_s}')

# Seek to 2539s (10s before end of GX010115 at 2549.18s)
seek_target = 2539.0
print(f'\n--- SEEKING TO GLOBAL {seek_target}s (10s before end of 015) ---')
ctrl._on_seek_changed(seek_target)

for _ in range(40):
    app.processEvents()
    time.sleep(0.02)

print(f'Post-seek state:')
print(f'  _active_preview_clip_index: {ctrl._active_preview_clip_index}')
print(f'  mpv.path: {ctrl.mpv_player.path if ctrl.mpv_player else None}')
print(f'  mpv.time_pos: {ctrl.mpv_player.time_pos if ctrl.mpv_player else None}')
print(f'  Preview time label: {window.preview.time_label.text()}')

# Start playback
print('\n--- STARTING PLAYBACK ---')
ctrl._on_playback_start()

start_time = time.time()
tick_count = 0
last_clip = ctrl._active_preview_clip_index

while time.time() - start_time < 22.0:
    app.processEvents()
    time.sleep(0.033)
    tick_count += 1
    
    mpv_pos = ctrl.mpv_player.time_pos if ctrl.mpv_player else None
    mpv_path = ctrl.mpv_player.path if ctrl.mpv_player else None
    eof_reached = getattr(ctrl.mpv_player, 'eof_reached', None) if ctrl.mpv_player else None
    cur_idx = ctrl._active_preview_clip_index
    
    if tick_count % 10 == 0 or cur_idx != last_clip:
        last_clip = cur_idx
        local = mpv_pos or 0.0
        g_pos = ctrl._local_to_global(local)
        print(f"[MPV-MULTI] t_wall={time.time()-start_time:5.2f}s "
              f"clip_idx={cur_idx} "
              f"mpv_time_pos={mpv_pos} "
              f"global_time={g_pos:7.2f}s "
              f"mpv_path={Path(mpv_path).name if mpv_path else None} "
              f"eof={eof_reached} "
              f"playing={ctrl._playing} "
              f"time_label={window.preview.time_label.text()} "
              f"dur_label={window.preview.duration_label.text()}")

ctrl._on_playback_stop()
print('\nPlayback stopped.')
window.close()
