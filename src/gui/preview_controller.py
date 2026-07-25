"""Preview controller for HUD Tuner GUI application.

Manages mouse interaction (drag-to-move, selection) and asynchronous frame loading.
"""

import queue
import threading
from typing import Optional, Tuple
from PIL import Image

# Import extract_frame from parent module helper or pipeline
from src.gui.hud_tuner_app import extract_frame


class PreviewController:
    """Manages preview label interaction, frame caching and mouse events."""

    def __init__(self, app):
        self.app = app
        self._drag_start: Optional[Tuple[int, int]] = None
        self._drag_indicator: Optional[str] = None
        self.indicator_bboxes = {}  # {key: (x, y, w, h)} in original image coords

        # Asynchronous preview frame loader setup
        self._preview_queue = queue.Queue(maxsize=1)
        self._preview_worker_thread = None
        self._start_preview_worker()

    def _start_preview_worker(self):
        def worker():
            while True:
                try:
                    task = self._preview_queue.get()
                    if task is None:
                        break
                    video_paths, ts, ffmpeg_exe, ffprobe_exe = task
                    img = extract_frame(video_paths, ts, ffmpeg_exe, ffprobe_exe, target_w=960)
                    if img:
                        self.app.root.after(0, self._on_frame_loaded, img, ts)
                except Exception as e:
                    print(f"Error in preview worker thread: {e}")
                finally:
                    self._preview_queue.task_done()

        self._preview_worker_thread = threading.Thread(target=worker, daemon=True)
        self._preview_worker_thread.start()

    def _on_frame_loaded(self, img: Image.Image, ts: float):
        self.app.src_img = img
        self.app.last_preview_timestamp = ts
        self.app.schedule_refresh(delay=0)

    def request_frame(self, video_paths, current_ts, ffmpeg_exe, ffprobe_exe):
        try:
            self._preview_queue.get_nowait()
        except queue.Empty:
            pass
        self._preview_queue.put((video_paths, current_ts, ffmpeg_exe, ffprobe_exe))

    def map_preview_to_orig(self, px: int, py: int) -> Tuple[float, float]:
        """Map preview-label pixel coords to original image coords."""
        pw = self.app.preview_label.winfo_width()
        ph = self.app.preview_label.winfo_height()
        src_w, src_h = self.app.src_img.size
        if pw < 10 or ph < 10 or src_w < 1 or src_h < 1:
            return 0.0, 0.0
        scale = min(pw / src_w, ph / src_h)
        thumb_w = int(src_w * scale)
        thumb_h = int(src_h * scale)
        offset_x = (pw - thumb_w) // 2
        offset_y = (ph - thumb_h) // 2
        return (px - offset_x) / scale, (py - offset_y) / scale

    def find_indicator_at(self, orig_x: float, orig_y: float) -> Optional[str]:
        """Return indicator key at original-image coords, or None."""
        indicator_order = (
            ['alt_text', 'alt_visual', 'dist_text', 'dist_visual',
             'speed_text', 'speed_visual', 'time_block', 'track_map',
             'temp_text', 'exposure_text', 'iso_text',
             'cad_text', 'hr_text', 'atemp_text', 'power_text', 'battery_text']
            + self.app.fit_ext_fields
        )
        for key in indicator_order:
            bbox = self.indicator_bboxes.get(key)
            if bbox is None:
                continue
            x, y, w, h = bbox
            if x <= orig_x <= x + w and y <= orig_y <= y + h:
                return key
        return None

    def on_mouse_down(self, event):
        """Record drag start and find indicator under cursor."""
        tm = self.app.telemetry
        has_speed = len(tm.speed_samples) > 0 if tm else False
        if not has_speed or not self.indicator_bboxes:
            return
        orig_x, orig_y = self.map_preview_to_orig(event.x, event.y)
        hit_key = self.find_indicator_at(orig_x, orig_y)
        if hit_key is None:
            return
        self._drag_start = (event.x, event.y)
        self._drag_indicator = hit_key

    def on_drag_motion(self, event):
        """Drag the indicator: update x/y in layout and refresh preview."""
        if self._drag_start is None or self._drag_indicator is None:
            return
        key = self._drag_indicator
        cfg = self.app.layout.get('indicators', {}).get(key)
        if cfg is None:
            return
        src_w, src_h = self.app.src_img.size
        if src_w < 1 or src_h < 1:
            return
        orig_x, orig_y = self.map_preview_to_orig(event.x, event.y)
        cfg['x'] = max(0.0, min(1.0, orig_x / src_w))
        cfg['y'] = max(0.0, min(1.0, orig_y / src_h))

        prev_suppress = getattr(self.app, '_suppress_builtin_change', False)
        self.app._suppress_builtin_change = True
        try:
            for field_name in ('x', 'y'):
                w = self.app.property_widgets.get(field_name)
                if w is not None:
                    try:
                        w.var.set(cfg[field_name])
                        w.sync_entry()
                    except Exception:
                        pass
        finally:
            self.app._suppress_builtin_change = prev_suppress
        self.app.schedule_refresh(20)

    def on_mouse_up(self, event):
        """Mouse release: if drag occurred, refresh; otherwise run click-to-select."""
        if self._drag_start is None:
            return
        dx = abs(event.x - self._drag_start[0])
        dy = abs(event.y - self._drag_start[1])
        was_drag = dx > 3 or dy > 3
        self._drag_start = None
        drag_indicator = self._drag_indicator
        self._drag_indicator = None
        if was_drag:
            self.app.refresh()
        elif drag_indicator is not None:
            self.on_preview_click(event)

    def on_preview_click(self, event):
        """Handle click on preview label – find indicator under cursor and select it."""
        tm = self.app.telemetry
        has_speed = len(tm.speed_samples) > 0 if tm else False
        if not has_speed or not self.indicator_bboxes:
            return
        orig_x, orig_y = self.map_preview_to_orig(event.x, event.y)
        hit_key = self.find_indicator_at(orig_x, orig_y)
        if hit_key is None:
            return

        import tkinter as tk
        from src.gui.widgets import GPX_EXT_FIELDS
        ext_all = list(GPX_EXT_FIELDS) + self.app.fit_ext_fields
        if hit_key in ext_all:
            try:
                idx = ext_all.index(hit_key)
                self.app.ext_list.selection_clear(0, tk.END)
                self.app.ext_list.selection_set(idx)
                self.app.ext_list.activate(idx)
                self.app.indicator_list.selection_clear(0, tk.END)
                self.app.custom_texts_list.selection_clear(0, tk.END)
                self.app.build_property_editor_builtin()
            except (ValueError, tk.TclError):
                pass
        else:
            all_builtin = [self.app.indicator_list.get(i) for i in range(self.app.indicator_list.size())]
            try:
                idx = all_builtin.index(hit_key)
                self.app.indicator_list.selection_clear(0, tk.END)
                self.app.indicator_list.selection_set(idx)
                self.app.indicator_list.activate(idx)
                self.app.ext_list.selection_clear(0, tk.END)
                self.app.build_property_editor_builtin()
            except (ValueError, tk.TclError):
                pass
