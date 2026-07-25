"""Center panel view for HUD Tuner GUI application."""

import tkinter as tk
from tkinter import ttk


class CenterPanelView:
    """Encapsulates the preview video label, timeline seekbar, and progress bars."""

    def __init__(self, parent, app):
        self.app = app
        self.frame = tk.Frame(parent)

        center_pw = tk.PanedWindow(self.frame, orient=tk.VERTICAL, sashrelief=tk.RAISED)
        center_pw.pack(fill='both', expand=True, padx=8, pady=8)

        # ── Preview Label Frame ──
        preview_wrap = tk.Frame(center_pw)
        center_pw.add(preview_wrap, minsize=480, height=550)
        app.preview_label = tk.Label(preview_wrap, bg='#222')
        app.preview_label.pack(fill=tk.BOTH, expand=True)
        app.preview_label.bind('<Configure>', app.on_preview_resize)
        app.preview_label.bind('<Button-1>', app.preview_ctrl.on_mouse_down)
        app.preview_label.bind('<B1-Motion>', app.preview_ctrl.on_drag_motion)
        app.preview_label.bind('<ButtonRelease-1>', app.preview_ctrl.on_mouse_up)

        # ── Timeline Seekbar + Play/Stop (ta sama linia) ──
        seek_frame = tk.Frame(center_pw)
        center_pw.add(seek_frame, minsize=90)

        ctrl_seek_row = tk.Frame(seek_frame)
        ctrl_seek_row.pack(fill=tk.X)

        play_btn = tk.Button(
            ctrl_seek_row, text='\u25B6', width=2,
            command=app.playback_start, relief=tk.FLAT,
            font=('Segoe UI', 11),
        )
        play_btn.pack(side=tk.LEFT, padx=(0, 2))
        stop_btn = tk.Button(
            ctrl_seek_row, text='\u25A0', width=2,
            command=app.playback_stop, relief=tk.FLAT,
            font=('Segoe UI', 11),
        )
        stop_btn.pack(side=tk.LEFT, padx=(0, 4))

        app.seek_slider = tk.Scale(ctrl_seek_row, variable=app.seek_var, from_=0, to=100,
                                   orient=tk.HORIZONTAL, showvalue=False, label="",
                                   resolution=1, tickinterval=0,
                                   command=lambda _: (app.schedule_refresh(100), app.update_seek_time_label()),
                                   takefocus=1)
        app.seek_slider.pack(fill=tk.X, expand=True, side=tk.LEFT)
        app.seek_slider.bind('<Button-1>', lambda e: app.seek_slider.focus_set())
        for key in ('<Left>', '<Right>', '<Up>', '<Down>'):
            app.seek_slider.bind(key, app.on_seek_arrow)

        tick_canvas = tk.Canvas(seek_frame, height=20, highlightthickness=0, bg='#1e1e1e')
        tick_canvas.pack(fill=tk.X)
        tick_canvas.bind('<Configure>', lambda e: app.draw_tick_labels())
        app.tick_canvas = tick_canvas

        # ── Loading progress frame (hidden by default) ──
        loading_frame = tk.Frame(self.frame, height=40)
        app.loading_progress = ttk.Progressbar(loading_frame, orient=tk.HORIZONTAL, mode='determinate', maximum=100, value=0)
        app.loading_progress.pack(fill=tk.X, pady=(4, 2), padx=8)
        app.loading_status_label = tk.Label(loading_frame, textvariable=app.loading_status, font=('Consolas', 8), anchor='w')
        app.loading_status_label.pack(fill=tk.X, pady=(0, 4), padx=8)
        app._loading_frame = loading_frame

        # ── Render progress frame (hidden by default) ──
        progress_frame = tk.Frame(self.frame, height=50)
        app.render_progress = ttk.Progressbar(progress_frame, orient=tk.HORIZONTAL, mode='determinate')
        app.render_progress.pack(fill=tk.X, pady=(4, 2), padx=8)
        app.render_stats = tk.Label(progress_frame, text="Gotowy", font=('Consolas', 8))
        app.render_stats.pack(fill=tk.X, pady=(0, 4), padx=8)
        app._render_frame = progress_frame
