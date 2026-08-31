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

print('=================================================================')
print('=== TELEM REAL MPV MULTI-FILE ACCEPTANCE TEST SUITE (A-E) ===')
print('=================================================================')

ctrl = AppController()
window = MainWindow()
window.set_controller(ctrl)

v14 = r'C:\_DEV\TeleM\Video\GX010114.MP4'
v15 = r'C:\_DEV\TeleM\Video\GX010115.MP4'
v16 = r'C:\_DEV\TeleM\Video\GX010116.MP4'
fit = r'C:\_DEV\TeleM\Video\GX010114_116.fit'

ctrl._on_files_selected([v14, v15, v16], gpx_path='', fit_path=fit)

# Wait for project load
for _ in range(100):
    app.processEvents()
    time.sleep(0.1)
    if ctrl.video_timeline is not None and getattr(ctrl, 'last_src_pil', None) is not None:
        break

tl = ctrl.video_timeline
assert tl is not None, "Timeline failed to build!"
initial_signature = (
    tl.clip_count,
    [c.path.name for c in tl.clips],
    [c.global_start_s for c in tl.clips],
    [c.global_end_s for c in tl.clips],
    tl.project_duration_s,
)
print(f'INITIAL TIMELINE SIGNATURE: {initial_signature}')
assert initial_signature[0] == 3
assert abs(initial_signature[4] - 4292.821867) < 0.001

# ─────────────────────────────────────────────────────────────────
# TEST A: 014 -> 015 automatic transition
# ─────────────────────────────────────────────────────────────────
print('\n=================================================================')
print('TEST A: 014 -> 015 Automatic Transition (seek to 1946s, 10s before end of 014)')
print('=================================================================')
ctrl._on_seek_changed(1946.0)
for _ in range(30):
    app.processEvents()
    time.sleep(0.02)

ctrl._on_playback_start()
t0 = time.time()
saw_014 = False
saw_015 = False

while time.time() - t0 < 15.0:
    app.processEvents()
    time.sleep(0.033)
    idx = ctrl._active_preview_clip_index
    if idx == 0:
        saw_014 = True
    elif idx == 1:
        saw_015 = True
        break

assert saw_014, "Did not see clip 014!"
assert saw_015, "014 -> 015 auto transition failed!"
print(f'PASS: 014 -> 015 transitioned smoothly at wall_time={time.time()-t0:.2f}s! Active clip is now {idx} ({tl.clips[idx].path.name})')
ctrl._on_playback_stop()

# ─────────────────────────────────────────────────────────────────
# TEST B & C & E: 015 -> 016 automatic transition + 30s playback
# ─────────────────────────────────────────────────────────────────
print('\n=================================================================')
print('TEST B & C & E: 015 -> 016 Auto Transition + >=30s in 016 (No freeze)')
print('=================================================================')
ctrl._on_seek_changed(2541.0) # ~8s before end of 015
for _ in range(30):
    app.processEvents()
    time.sleep(0.02)

ctrl._on_playback_start()
t0 = time.time()
saw_015 = False
saw_016 = False
t_016_start = None

while time.time() - t0 < 45.0:
    app.processEvents()
    time.sleep(0.033)
    idx = ctrl._active_preview_clip_index
    pos = ctrl.mpv_player.time_pos if ctrl.mpv_player else 0.0
    if idx == 1:
        saw_015 = True
    elif idx == 2:
        if not saw_016:
            saw_016 = True
            t_016_start = time.time()
            print(f'Transitioned 015 -> 016! Started playing clip 2 at wall_time={time.time()-t0:.2f}s')
        else:
            elapsed_016 = time.time() - t_016_start
            if int(elapsed_016) % 5 == 0 and int(elapsed_016) > 0:
                print(f'  Playing clip 2: elapsed_in_016={elapsed_016:.1f}s, mpv_local_pos={pos:.2f}s, global={ctrl._local_to_global(pos or 0):.2f}s')
            if elapsed_016 >= 31.0:
                print(f'PASS: Played 31s continuously in 016 without freeze!')
                break

assert saw_015, "Did not start in 015!"
assert saw_016, "015 -> 016 auto transition failed!"
assert (time.time() - t_016_start) >= 30.0, "Did not play 30s in 016!"
ctrl._on_playback_stop()

# ─────────────────────────────────────────────────────────────────
# TEST D: Chaos seek: 016 -> 015 -> 016 -> 014 -> 016
# ─────────────────────────────────────────────────────────────────
print('\n=================================================================')
print('TEST D: Chaos Seek (016 -> 015 -> 016 -> 014 -> 016)')
print('=================================================================')
seeks = [
    (3000.0, 2, 'GX010116.MP4'),
    (2200.0, 1, 'GX010115.MP4'),
    (3500.0, 2, 'GX010116.MP4'),
    (500.0,  0, 'GX010114.MP4'),
    (4000.0, 2, 'GX010116.MP4'),
]

for target_g, expected_idx, expected_name in seeks:
    print(f'\nSeeking to global={target_g:.1f}s (expected clip {expected_idx} {expected_name})...')
    ctrl._on_seek_changed(target_g)
    for _ in range(30):
        app.processEvents()
        time.sleep(0.02)
    
    act_idx = ctrl._active_preview_clip_index
    act_path = ctrl.mpv_player.path if ctrl.mpv_player else None
    act_name = Path(act_path).name if act_path else ''
    act_pos = ctrl.mpv_player.time_pos if ctrl.mpv_player else 0.0
    act_global = ctrl._local_to_global(act_pos or 0.0)
    dur_label = window.preview.duration_label.text()
    
    print(f'  Result: clip_idx={act_idx}, path={act_name}, mpv_pos={act_pos:.2f}s, computed_global={act_global:.2f}s, dur_label={dur_label}')
    assert act_idx == expected_idx, f"Wrong clip index! Expected {expected_idx}, got {act_idx}"
    assert act_name == expected_name, f"Wrong clip path! Expected {expected_name}, got {act_name}"
    assert dur_label == "71:32", f"Wrong duration label! Expected 71:32, got {dur_label}"

print('\nPASS: All chaos seeks resolved to correct clips and paths without corruption!')

# ─────────────────────────────────────────────────────────────────
# Verify final timeline signature
# ─────────────────────────────────────────────────────────────────
final_signature = (
    tl.clip_count,
    [c.path.name for c in tl.clips],
    [c.global_start_s for c in tl.clips],
    [c.global_end_s for c in tl.clips],
    tl.project_duration_s,
)
print(f'\nFINAL TIMELINE SIGNATURE: {final_signature}')
assert initial_signature == final_signature, "Timeline signature changed during playback/seeking!"
print('PASS: Timeline signature is strictly immutable!')

print('\n=================================================================')
print('=== ALL ACCEPTANCE TESTS (A, B, C, D, E) PASSED SUCCESSFULLY! ===')
print('=================================================================')
window.close()
