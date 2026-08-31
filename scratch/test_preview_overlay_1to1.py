"""Automated verification of native physical raster 1:1 preview resolution, geometry, and DPI scaling."""

import os, sys, time
from pathlib import Path

os.add_dll_directory(r'C:\_DEV\TeleM-integration')
os.add_dll_directory(r'C:\_DEV\TeleM')
os.environ['PATH'] = r'C:\_DEV\TeleM-integration;' + r'C:\_DEV\TeleM;' + os.environ.get('PATH', '')
os.environ['TELEM_PREVIEW_DEBUG'] = '1'
sys.path.insert(0, r'C:\_DEV\TeleM-integration')

from PySide6.QtWidgets import QApplication
from src.gui.qt.controller import AppController
from src.gui.qt.main_window import MainWindow

app = QApplication.instance() or QApplication(sys.argv)

print("=================================================================")
print("=== TELEM NATIVE PHYSICAL RASTER 1:1 PREVIEW TEST SUITE ===")
print("=================================================================")

# ─────────────────────────────────────────────────────────────────────────────
# TEST 1: Single-file preview native physical raster 1:1
# ─────────────────────────────────────────────────────────────────────────────
print("\n--- TEST 1: Single-file Project (GX010115) Native Physical Raster 1:1 ---")
ctrl = AppController()
window = MainWindow()
window.set_controller(ctrl)
window.resize(1600, 1000)
window.show()

v15 = r'C:\_DEV\TeleM\Video\GX010115.MP4'
fit = r'C:\_DEV\TeleM\Video\GX010114_116.fit'
ctrl._on_files_selected([v15], gpx_path='', fit_path=fit)

for _ in range(60):
    app.processEvents()
    time.sleep(0.05)
    if ctrl.video_timeline is not None and getattr(ctrl, 'last_src_pil', None) is not None:
        break

p = window.preview
vrect = p.get_video_rect()
dpr = p.get_dpr()
phys_rect = p.get_physical_video_rect()

print(f"Widget logical size: {p.size().width()}x{p.size().height()}")
print(f"Stacked widget logical size: {p.stacked_widget.width()}x{p.stacked_widget.height()}")
print(f"Device Pixel Ratio (DPR): {dpr:.2f}")
print(f"Video rect logical: x={vrect.x()}, y={vrect.y()}, w={vrect.width()}, h={vrect.height()}")
print(f"Video rect physical: x={phys_rect.x()}, y={phys_rect.y()}, w={phys_rect.width()}, h={phys_rect.height()}")
print(f"Controller preview target: {ctrl._preview_target_w}x{ctrl._preview_target_h} (DPR={ctrl._preview_dpr})")
print(f"Controller src_img size (physical raster buffer): {ctrl.src_img.size if ctrl.src_img else None}")

# Verify physical raster buffer matches physical video rect exactly 1:1
assert phys_rect.width() == ctrl._preview_target_w, f"Physical width mismatch! phys={phys_rect.width()} vs target={ctrl._preview_target_w}"
assert phys_rect.height() == ctrl._preview_target_h, f"Physical height mismatch! phys={phys_rect.height()} vs target={ctrl._preview_target_h}"
assert ctrl.src_img.size == (phys_rect.width(), phys_rect.height()), f"src_img size mismatch! {ctrl.src_img.size} vs {phys_rect.size()}"

if hasattr(p, "hud_overlay") and p.hud_overlay.hud_pixmap:
    pix = p.hud_overlay.hud_pixmap
    logical_w = pix.width() / pix.devicePixelRatio()
    logical_h = pix.height() / pix.devicePixelRatio()
    print(f"HUD overlay pixmap physical: {pix.width()}x{pix.height()} | logical: {logical_w}x{logical_h} (DPR={pix.devicePixelRatio()})")
    assert pix.width() == phys_rect.width(), "Physical pixmap width mismatch!"
    assert pix.height() == phys_rect.height(), "Physical pixmap height mismatch!"
    assert abs(logical_w - vrect.width()) < 1e-3, "Logical pixmap width mismatch!"
    assert abs(logical_h - vrect.height()) < 1e-3, "Logical pixmap height mismatch!"
    assert abs(pix.devicePixelRatio() - dpr) < 1e-3, "Pixmap DPR mismatch!"

print("PASS: Native physical raster buffer matches physical video rect 1:1 with zero post-raster resize!")


# ─────────────────────────────────────────────────────────────────────────────
# TEST 2: Dynamic window resize & physical raster tracking
# ─────────────────────────────────────────────────────────────────────────────
print("\n--- TEST 2: Dynamic Window Resize Physical Raster Tracking ---")
test_sizes = [
    (1400, 900),
    (1200, 800),
    (1800, 1050),
    (1600, 1000),
]

for w, h in test_sizes:
    print(f"\nResizing MainWindow to {w}x{h}...")
    window.resize(w, h)
    for _ in range(20):
        app.processEvents()
        time.sleep(0.02)
    
    vr = p.get_video_rect()
    pr = p.get_physical_video_rect()
    print(f"  Result: vrect_logical={vr.x()},{vr.y()},{vr.width()}x{vr.height()} | vrect_phys={pr.x()},{pr.y()},{pr.width()}x{pr.height()}")
    print(f"  Controller target: {ctrl._preview_target_w}x{ctrl._preview_target_h} (DPR={ctrl._preview_dpr}) | src_img: {ctrl.src_img.size}")
    assert pr.width() == ctrl._preview_target_w, f"Target width failed to track resize to {w}x{h}!"
    assert pr.height() == ctrl._preview_target_h, f"Target height failed to track resize to {w}x{h}!"
    assert ctrl.src_img.size == (pr.width(), pr.height()), "src_img failed to match resized physical video rect!"

print("PASS: Physical raster buffer dynamically tracked all window resizes 1:1!")

# ─────────────────────────────────────────────────────────────────────────────
# TEST 3: Multi-file project (GX010114 + GX010115 + GX010116)
# ─────────────────────────────────────────────────────────────────────────────
print("\n--- TEST 3: Multi-file Project (014+015+016) Native Physical Raster 1:1 ---")
v14 = r'C:\_DEV\TeleM\Video\GX010114.MP4'
v16 = r'C:\_DEV\TeleM\Video\GX010116.MP4'
ctrl._on_files_selected([v14, v15, v16], gpx_path='', fit_path=fit)

for _ in range(200):
    app.processEvents()
    time.sleep(0.05)
    if (ctrl.video_timeline is not None and ctrl.video_timeline.clip_count == 3
            and getattr(ctrl, 'last_src_pil', None) is not None
            and getattr(ctrl, '_prepare_cache', None) is not None):
        break

time.sleep(0.5)
for _ in range(20):
    app.processEvents()
    time.sleep(0.02)

pr = p.get_physical_video_rect()
print(f"Multi-file physical video rect: {pr.x()},{pr.y()} {pr.width()}x{pr.height()}")
print(f"Controller target: {ctrl._preview_target_w}x{ctrl._preview_target_h} | src_img: {ctrl.src_img.size}")
assert pr.width() == ctrl._preview_target_w
assert pr.height() == ctrl._preview_target_h
assert ctrl.src_img.size == (pr.width(), pr.height())

print("Verifying indicator bounding box coverage...")
for key, bbox in ctrl.indicator_bboxes.items():
    bx, by, bw, bh = bbox
    print(f"  {key:24s}: bbox=({bx}, {by}, {bw}, {bh}) on physical canvas {pr.width()}x{pr.height()}")
    cx = bx + bw // 2
    cy = by + bh // 2
    assert 0 <= cx <= pr.width(), f"Indicator {key} center X ({cx}) out of canvas [0, {pr.width()}]!"
    assert 0 <= cy <= pr.height(), f"Indicator {key} center Y ({cy}) out of canvas [0, {pr.height()}]!"

print("PASS: Multi-file project physical raster overlay and indicator bounding boxes match 1:1!")

# ─────────────────────────────────────────────────────────────────────────────
# TEST 4: Seek across clips
# ─────────────────────────────────────────────────────────────────────────────
print("\n--- TEST 4: Seek Across Clips in Native Physical Raster Preview ---")
for target_s in [500.0, 2200.0, 3500.0]:
    ctrl._on_seek_changed(target_s)
    for _ in range(20):
        app.processEvents()
        time.sleep(0.02)
    pr = p.get_physical_video_rect()
    assert ctrl.src_img.size == (pr.width(), pr.height()), f"Seek to {target_s}s disrupted physical 1:1 size!"

print("PASS: Seeking across clips maintains exact native physical raster resolution!")

window.close()
print("\n=================================================================")
print("=== ALL NATIVE PHYSICAL RASTER 1:1 TESTS PASSED SUCCESSFULLY! ===")
print("=================================================================")
