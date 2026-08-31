import os, sys, time
os.add_dll_directory(r'C:\_DEV\TeleM-integration')
os.add_dll_directory(r'C:\_DEV\TeleM')
os.environ['PATH'] = r'C:\_DEV\TeleM-integration;' + r'C:\_DEV\TeleM;' + os.environ.get('PATH', '')
sys.path.insert(0, r'C:\_DEV\TeleM-integration')

from PySide6.QtWidgets import QApplication
from src.gui.qt.main_window import MainWindow
from src.gui.qt.controller import AppController
from src.gui.qt.signals import get_signals

app = QApplication(sys.argv)
ctrl = AppController()
win = MainWindow()
win.set_controller(ctrl)
win.resize(1600, 900)
win.show()
app.processEvents()

print('=== TEST A: COLD START & INITIAL LOAD (SINGLE FILE GX010115) ===')
# Initially on LoadTab (tab 0)
win.tabs.setCurrentIndex(0)
app.processEvents()

print(f'Initial active tab: {win.tabs.currentIndex()} ({win.tabs.tabText(win.tabs.currentIndex())})')

status = {"loaded": False}
def on_prog(p, msg):
    if p >= 100:
        status["loaded"] = True
ctrl.signals.sig_progress.connect(on_prog)

# Select and load files
get_signals().sig_files_selected.emit(
    [r'C:\_DEV\TeleM\Video\GX010115.MP4'], '', r'C:\_DEV\TeleM\Video\GX010114_116.fit'
)

# Wait for background loading to finish and tab switch to occur
t0 = time.time()
while time.time() - t0 < 10.0 and not status["loaded"]:
    app.processEvents()
    time.sleep(0.05)

# Allow tab change events to process
app.processEvents()
time.sleep(0.1)
app.processEvents()

# Verify state after cold load
active_tab_idx = win.tabs.currentIndex()
print(f'Active tab after load: {active_tab_idx} ({win.tabs.tabText(active_tab_idx)})')
assert active_tab_idx == 1, f'Expected tab 1 (Projekt), got {active_tab_idx}'

vrect = win.preview.get_video_rect()
prect = win.preview.get_physical_video_rect()
dpr = win.preview.get_dpr()
pm = win.preview.hud_overlay.hud_pixmap

print(f'Video rect logical:  {vrect.x()},{vrect.y()},{vrect.width()}x{vrect.height()}')
print(f'Video rect physical: {prect.x()},{prect.y()},{prect.width()}x{prect.height()} (DPR={dpr:.2f})')
print(f'Controller target:   {ctrl._preview_target_w}x{ctrl._preview_target_h} (DPR={ctrl._preview_dpr:.2f})')

assert pm is not None, 'HUD pixmap must not be None'
print(f'HUD pixmap buffer:   {pm.width()}x{pm.height()} (DPR={pm.devicePixelRatio():.2f})')

# Check 1:1 match
match_w = (pm.width() == prect.width())
match_h = (pm.height() == prect.height())
match_dpr = (abs(pm.devicePixelRatio() - dpr) < 1e-4)
print(f'INITIAL HUD MATCHES SCREEN PHYSICAL VIDEO RECT EXACTLY: {match_w and match_h and match_dpr}')
assert match_w and match_h and match_dpr, f'Mismatch: HUD={pm.width()}x{pm.height()} vs Screen={prect.width()}x{prect.height()}'

print('\n=== TEST B: COMPARISON BEFORE AND AFTER FIRST DRAG ===')
initial_pm_w = pm.width()
initial_pm_h = pm.height()
initial_pm_dpr = pm.devicePixelRatio()

# Simulate drag
ctrl._on_indicator_moved('speed_visual', 50.0, 50.0)
app.processEvents()

pm_after_drag = win.preview.hud_overlay.hud_pixmap
print(f'After drag HUD pixmap buffer: {pm_after_drag.width()}x{pm_after_drag.height()} (DPR={pm_after_drag.devicePixelRatio():.2f})')
assert pm_after_drag.width() == initial_pm_w, 'Width must not change after drag'
assert pm_after_drag.height() == initial_pm_h, 'Height must not change after drag'
assert abs(pm_after_drag.devicePixelRatio() - initial_pm_dpr) < 1e-4, 'DPR must not change after drag'
print('DRAG COMPARISON: 100% IDENTICAL SIZE AND SCALE BEFORE AND AFTER DRAG.')

print('\n=== TEST C: MULTI-FILE LOAD (014+015+016) ===')
win.tabs.setCurrentIndex(0)
app.processEvents()

status["loaded"] = False
get_signals().sig_files_selected.emit(
    [r'C:\_DEV\TeleM\Video\GX010114.MP4', r'C:\_DEV\TeleM\Video\GX010115.MP4', r'C:\_DEV\TeleM\Video\GX010116.MP4'],
    '',
    r'C:\_DEV\TeleM\Video\GX010114_116.fit'
)

t0 = time.time()
while time.time() - t0 < 10.0 and not status["loaded"]:
    app.processEvents()
    time.sleep(0.05)

app.processEvents()
time.sleep(0.1)
app.processEvents()

prect_multi = win.preview.get_physical_video_rect()
pm_multi = win.preview.hud_overlay.hud_pixmap
print(f'Multi-file Video rect physical: {prect_multi.width()}x{prect_multi.height()}')
print(f'Multi-file HUD pixmap buffer:   {pm_multi.width()}x{pm_multi.height()}')
assert pm_multi.width() == prect_multi.width() and pm_multi.height() == prect_multi.height(), 'Multi-file initial HUD must fill physical video rect'
print('MULTI-FILE INITIAL HUD MATCHES SCREEN EXACTLY.')

print('\n=== TEST D: RESIZE & MONITOR CHANGE ===')
win.resize(1280, 720)
app.processEvents()
time.sleep(0.1)
app.processEvents()

prect_resized = win.preview.get_physical_video_rect()
pm_resized = win.preview.hud_overlay.hud_pixmap
print(f'Resized Video rect physical: {prect_resized.width()}x{prect_resized.height()}')
print(f'Resized HUD pixmap buffer:   {pm_resized.width()}x{pm_resized.height()}')
assert pm_resized.width() == prect_resized.width() and pm_resized.height() == prect_resized.height(), 'Resized HUD must fill physical video rect'
print('RESIZE MATCHES SCREEN EXACTLY.')

win.close()
print('\nALL INITIAL HUD TESTS PASSED SUCCESSFULLY.')
