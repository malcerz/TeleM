if __name__ == '__main__':
    import sys, runpy
    sys.path.insert(0, r'C:\_DEV\SportCamHUD')
    import src.gui.qt.harness_golden as gold
    from PySide6.QtCore import QTimer
    original = gold.capture_editor_hud
    def defer(controller, abs_frame, out_dir, width, height):
        def poll():
            ready, _ = controller.export_readiness()
            if ready:
                original(controller, abs_frame, out_dir, width, height)
            else:
                QTimer.singleShot(30, poll)
        QTimer.singleShot(30, poll)
        return {'deferred': True, 'frame': abs_frame}
    gold.capture_editor_hud = defer
    sys.argv[0] = r'C:\_DEV\SportCamHUD\SportCamHUD.py'
    runpy.run_path(sys.argv[0], run_name='__main__')
