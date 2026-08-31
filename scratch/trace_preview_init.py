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
win.showMaximized()
app.processEvents()

events_log = []

def log_event(name, **kwargs):
    t = time.time()
    info = ' '.join(f'{k}={v}' for k, v in kwargs.items())
    msg = f'[{t:.3f}] {name}: {info}'
    events_log.append(msg)
    print(msg, flush=True)

# Patch set_preview_target_size to log
orig_set_target = ctrl.set_preview_target_size
def logged_set_target(w, h, dpr=1.0):
    log_event('set_preview_target_size', w=w, h=h, dpr=dpr)
    orig_set_target(w, h, dpr=dpr)
ctrl.set_preview_target_size = logged_set_target

# Patch _render_preview to log
orig_render_preview = ctrl._render_preview
def logged_render_preview(seek_seconds=None):
    w = getattr(ctrl, '_preview_target_w', None)
    h = getattr(ctrl, '_preview_target_h', None)
    dpr = getattr(ctrl, '_preview_dpr', None)
    log_event('_render_preview_CALLED', seek=seek_seconds, target_w=w, target_h=h, dpr=dpr)
    orig_render_preview(seek_seconds)
ctrl._render_preview = logged_render_preview

# Patch on_frame_ready
orig_on_frame_ready = win.preview.on_frame_ready
def logged_on_frame_ready(qimg):
    if qimg is not None:
        vrect = win.preview.get_video_rect()
        prect = win.preview.get_physical_video_rect()
        dpr = win.preview.get_dpr()
        log_event('on_frame_ready_ARRIVED',
                  img_w=qimg.width(), img_h=qimg.height(), img_dpr=qimg.devicePixelRatio(),
                  vrect_w=vrect.width(), vrect_h=vrect.height(),
                  prect_w=prect.width(), prect_h=prect.height(), dpr=dpr)
    orig_on_frame_ready(qimg)
win.preview.on_frame_ready = logged_on_frame_ready

print('=== STARTING PROJECT LOAD ===')
get_signals().sig_files_selected.emit(
    [r'C:\_DEV\TeleM\Video\GX010115.MP4'], '', r'C:\_DEV\TeleM\Video\GX010114_116.fit'
)

# Process events until load is complete
t0 = time.time()
while time.time() - t0 < 3.0:
    app.processEvents()
    time.sleep(0.05)

print('\n=== FINAL STATE AFTER LOAD ===')
vrect = win.preview.get_video_rect()
prect = win.preview.get_physical_video_rect()
print(f'Final video_rect logical: {vrect.width()}x{vrect.height()}, physical: {prect.width()}x{prect.height()}')
if win.preview.hud_overlay.hud_pixmap:
    pm = win.preview.hud_overlay.hud_pixmap
    print(f'Final HUD pixmap: width={pm.width()}, height={pm.height()}, dpr={pm.devicePixelRatio()}')
    print(f'IS HUD FILLING THE SCREEN? {pm.width() == prect.width() and pm.height() == prect.height()}')

win.close()
