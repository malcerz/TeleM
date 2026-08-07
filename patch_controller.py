import re

with open("src/gui/qt/controller.py", "r", encoding="utf-8") as f:
    code = f.read()

# 1. Change self.src_img initialization to RGBA transparent in _on_files_selected
code = code.replace(
    'self.src_img = Image.new("RGB", (w, h), (0, 0, 0))',
    'self.src_img = Image.new("RGBA", (w, h), (0, 0, 0, 0))'
)
code = code.replace(
    'self.src_img = Image.new("RGB", (1280, 720), (0, 0, 0))',
    'self.src_img = Image.new("RGBA", (1280, 720), (0, 0, 0, 0))'
)

# 2. In _on_files_selected, don't scale first_frame to preview_target_w, just make src_img transparent
code = re.sub(
    r'first_frame = extract_frame.*?\n.*?self\._render_preview\(0\)',
    r'''self.src_img = Image.new("RGBA", (self._preview_target_w, int(self._preview_target_w*h/w)), (0,0,0,0))
                if self.mpv_player:
                    self.mpv_player.play(str(self.video_path))
                    self.mpv_player.pause()
                self._render_preview(0)''',
    code, flags=re.DOTALL
)

# 3. Replace QImage conversion in _render_preview to preserve Alpha
qimg_convert = """            # Konwertuj PIL Image \u2192 QImage (thread-safe, GUI wątek zrobi QPixmap)
            from PySide6.QtGui import QImage
            img_rgba = preview.convert("RGBA")
            data = img_rgba.tobytes("raw", "RGBA")
            qimg = QImage(
                data, img_rgba.width, img_rgba.height,
                img_rgba.width * 4, QImage.Format_RGBA8888,
            )
            self.signals.sig_preview_frame_ready.emit(qimg)"""

code = re.sub(
    r'# Konwertuj PIL Image.*?sig_preview_frame_ready\.emit\(qimg\)',
    qimg_convert,
    code, flags=re.DOTALL
)

# 4. Update playback controls (play, stop, seek)
code = code.replace(
    'self.media_player.play()',
    'if self.mpv_player: self.mpv_player.unpause()'
)
code = code.replace(
    'self.media_player.pause()',
    'if self.mpv_player: self.mpv_player.pause()'
)
code = code.replace(
    'self.media_player.stop()',
    'if self.mpv_player: self.mpv_player.command("stop")'
)
code = code.replace(
    'self.media_player.setPosition(int(seconds * 1000))',
    'if self.mpv_player: self.mpv_player.time_pos = seconds'
)

# 5. Fix _on_playback_start
code = code.replace(
    'self._playback_timer = QTimer()\n        self._playback_timer.timeout.connect(self._sync_playback_pos)\n        self._playback_timer.start(500)',
    'self._playback_timer = QTimer()\n        self._playback_timer.timeout.connect(lambda: self._trigger_hud_update(self.mpv_player.time_pos or 0.0) if self.mpv_player else None)\n        self._playback_timer.start(33)  # ~30 FPS HUD update'
)

# Save
with open("src/gui/qt/controller.py", "w", encoding="utf-8") as f:
    f.write(code)

print("controller.py patched!")
