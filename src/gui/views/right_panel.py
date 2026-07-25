"""Right panel view for HUD Tuner GUI application."""

import tkinter as tk

from src.gui.hud_tuner_app import ENCODER_OPTIONS, RESOLUTION_OPTIONS, ROTATION_OPTIONS


class RightPanelView:
    """Encapsulates the right panel with render options and export controls."""

    def __init__(self, parent, app):
        self.app = app
        self.frame = tk.Frame(parent)

        render_box = tk.LabelFrame(self.frame, text='Render')
        render_box.pack(fill=tk.X, padx=8, pady=8)

        tk.Label(render_box, text='Encoder').pack(anchor='w')
        tk.OptionMenu(render_box, app.encoder_var, *ENCODER_OPTIONS).pack(fill=tk.X)

        tk.Label(render_box, text='Rotation').pack(anchor='w', pady=(6, 0))
        rot_om = tk.OptionMenu(render_box, app.rotation_var, *ROTATION_OPTIONS, command=lambda _: app.refresh())
        rot_om.config(width=6)
        rot_om.pack(fill=tk.X)

        tk.Label(render_box, text='Resolution').pack(anchor='w', pady=(6, 0))
        tk.OptionMenu(render_box, app.resolution_var, *RESOLUTION_OPTIONS).pack(fill=tk.X)

        tk.Label(render_box, text='Update rate').pack(anchor='w', pady=(6, 0))
        update_rate_om = tk.OptionMenu(render_box, app.update_rate_var, 'Full', 'Half', 'Quarter', command=lambda _: app.refresh())
        update_rate_om.pack(fill=tk.X)

        tk.Label(render_box, text='Video bitrate').pack(anchor='w', pady=(6, 0))
        tk.Entry(render_box, textvariable=app.video_bitrate_var).pack(fill=tk.X)

        tk.Label(render_box, text='TZ Offset (UTC)').pack(anchor='w', pady=(6, 0))
        tk.Entry(render_box, textvariable=app.tz_offset_var).pack(fill=tk.X)

        tk.Label(render_box, text='Workers').pack(anchor='w', pady=(6, 0))
        wm = tk.Frame(render_box)
        wm.pack(fill=tk.X)
        tk.Radiobutton(wm, text='Auto', variable=app.worker_mode_var, value='auto').pack(side=tk.LEFT)
        tk.Radiobutton(wm, text='Ręcznie', variable=app.worker_mode_var, value='manual').pack(side=tk.LEFT)
        tk.Entry(render_box, textvariable=app.worker_count_var).pack(fill=tk.X)

        tk.Label(render_box, text='Output file').pack(anchor='w', pady=(6, 0))
        tk.Entry(render_box, textvariable=app.output_var).pack(fill=tk.X)

        app.render_button = tk.Button(render_box, text='Eksport do mp4', command=app.render_now)
        app.render_button.pack(fill=tk.X, pady=(8, 0))
