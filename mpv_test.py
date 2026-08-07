import sys
import os
import ctypes

os.environ["PATH"] = os.path.abspath(os.path.dirname(__file__)) + os.pathsep + os.environ["PATH"]

import mpv
from PySide6.QtWidgets import QApplication
from PySide6.QtOpenGLWidgets import QOpenGLWidget
from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QOpenGLContext, QPainter, QColor

class MpvGLWidget(QOpenGLWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.player = mpv.MPV(log_handler=print, hwdec='auto')
        self.mpv_gl = None

    def initializeGL(self):
        ctx = QOpenGLContext.currentContext()
        def get_proc_address(name):
            addr = ctx.getProcAddress(name.encode())
            return int(addr) if addr else 0

        # Wait, python-mpv API for MpvRenderContext might be different. Let's see if mpv.MPV has create_gl_context
        # Actually it's mpv.MpvRenderContext. Let's check python-mpv docs if create_gl_context exists.
        # But wait, there is mpv.MpvRenderContext(player, 'opengl', opengl_init_params={'get_proc_address': get_proc_address})
        
        # We will try both
        try:
            self.mpv_gl = mpv.MpvRenderContext(self.player, 'opengl', opengl_init_params={'get_proc_address': get_proc_address})
        except AttributeError:
            # Fallback for some mpv versions
            pass

        def on_update():
            QTimer.singleShot(0, self.update)
        
        self.mpv_gl.update_cb = on_update

    def paintGL(self):
        if self.mpv_gl:
            self.mpv_gl.render(fbo=self.defaultFramebufferObject(), w=self.width(), h=self.height(), flip_y=True)
            
        painter = QPainter(self)
        painter.setPen(Qt.red)
        painter.drawEllipse(100, 100, 200, 200)
        painter.end()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    win = MpvGLWidget()
    win.resize(1280, 720)
    win.show()
    win.player.play("video/GX020079.MP4")
    
    QTimer.singleShot(2000, app.quit) # auto quit after 2s for testing
    sys.exit(app.exec())
