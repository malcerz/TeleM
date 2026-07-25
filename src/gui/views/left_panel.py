"""Left panel view for HUD Tuner GUI application."""

import tkinter as tk
from tkinter import ttk
import tkinter.font as tkfont

from src.gui.widgets import GPX_EXT_FIELDS, ScrollableFrame


class LeftPanelView:
    """Encapsulates the widgets and layout of the left control panel."""

    def __init__(self, parent, app):
        self.app = app
        self.frame = tk.Frame(parent)

        self.left_scroll = ScrollableFrame(self.frame)
        self.left_scroll.pack(fill='both', expand=True, padx=8, pady=8)
        left = self.left_scroll.inner

        # ── Top action buttons & info labels ──
        top = tk.Frame(left)
        top.pack(fill=tk.X, pady=(0, 8))
        tk.Button(top, text='Wybierz MP4', command=app.open_video).pack(anchor='w', pady=(6, 0))
        tk.Label(top, textvariable=app.meta_info_var, justify='left', anchor='w').pack(fill=tk.X, pady=(6, 0))
        tk.Button(top, text='Wczytaj GPX/FIT', command=app.open_telemetry).pack(anchor='w', pady=(4, 0))

        app.gpx_info_var = tk.StringVar(value='GPX: brak (auto-wykrywanie)')
        tk.Label(top, textvariable=app.gpx_info_var, justify='left', anchor='w', fg='#0077cc').pack(fill=tk.X, pady=(2, 0))

        app.fit_info_var = tk.StringVar(value='FIT: brak')
        tk.Label(top, textvariable=app.fit_info_var, justify='left', anchor='w', fg='#cc5500').pack(fill=tk.X, pady=(0, 4))

        tk.Button(top, text='Zapisz Konfigurację', command=app.save_configuration).pack(fill=tk.X, pady=(6, 0))
        tk.Button(top, text='Wczytaj Konfiguracje', command=app.load_json).pack(fill=tk.X, pady=(6, 0))

        # ── Czcionka HUD ──
        font_frame = tk.LabelFrame(left, text='Czcionka HUD')
        font_frame.pack(fill=tk.X, pady=(0, 8))
        fonts = sorted(tkfont.families())
        if 'Arial' not in fonts and fonts:
            app.font_style_var.set(fonts[0])
            app.font_path = app.resolve_font_path(fonts[0]) if hasattr(app, 'resolve_font_path') else fonts[0]
        app.font_combo = ttk.Combobox(font_frame, textvariable=app.font_style_var, values=fonts, state='readonly')
        app.font_combo.pack(fill=tk.X, padx=4, pady=4)
        app.font_combo.bind('<<ComboboxSelected>>', app.on_font_change)

        # ── Outline (obramowanie tekstu) ──
        outline_frame = tk.LabelFrame(left, text='Obramowanie (outline)')
        outline_frame.pack(fill=tk.X, pady=(0, 8))
        app.outline_var.set(app.layout.get("global", {}).get("text_outline", 3))
        tk.Scale(outline_frame, variable=app.outline_var, from_=0, to=10,
                 resolution=1, orient=tk.HORIZONTAL, length=200,
                 command=lambda _: app.on_outline_change()).pack(padx=4, pady=4)

        # ── Wskaźniki telemetrii ──
        builtin_box = tk.LabelFrame(left, text='Wskaźniki Telemetrii')
        builtin_box.pack(fill=tk.X, pady=(0, 8))
        list_frame = tk.Frame(builtin_box)
        list_frame.pack(fill=tk.X)

        left_list_frame = tk.Frame(list_frame)
        left_list_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        tk.Label(left_list_frame, text="Główne", font=('', 8, 'bold')).pack()
        app.indicator_list = tk.Listbox(left_list_frame, height=10, exportselection=False)
        for key in app.layout['indicators'].keys():
            if key not in GPX_EXT_FIELDS and not key.startswith("fit_"):
                app.indicator_list.insert(tk.END, key)
        app.indicator_list.pack(fill=tk.X)
        app.indicator_list.bind('<<ListboxSelect>>', app.on_builtin_select)
        app.indicator_list.selection_set(0)

        ext_list_frame = tk.Frame(list_frame)
        ext_list_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)
        tk.Label(ext_list_frame, text="Extension", font=('', 8, 'bold')).pack()
        app.ext_list = tk.Listbox(ext_list_frame, height=10, exportselection=False)
        app._rebuild_ext_list()
        app.ext_list.pack(fill=tk.X)
        app.ext_list.bind('<<ListboxSelect>>', app.on_ext_select)

        reset_frame = tk.Frame(builtin_box)
        reset_frame.pack(fill=tk.X, pady=(4, 0))
        tk.Button(reset_frame, text='Resetuj wskaźniki (bez daty/czasu)', command=app.reset_indicators).pack(fill=tk.X)

        # ── Niestandardowe Teksty ──
        custom_texts_box = tk.LabelFrame(left, text='Niestandardowe Teksty')
        custom_texts_box.pack(fill=tk.X, pady=(0, 8))
        ct_list_frame = tk.Frame(custom_texts_box)
        ct_list_frame.pack(fill=tk.X)
        app.custom_texts_list = tk.Listbox(ct_list_frame, height=5, exportselection=False)
        app._rebuild_custom_texts_list()
        app.custom_texts_list.pack(fill=tk.X)
        app.custom_texts_list.bind('<<ListboxSelect>>', app.on_custom_text_select)
        ct_btn_frame = tk.Frame(custom_texts_box)
        ct_btn_frame.pack(fill=tk.X, pady=(2, 0))
        tk.Button(ct_btn_frame, text='Dodaj tekst', command=app.add_custom_text).pack(side=tk.LEFT, padx=(0, 4))
        tk.Button(ct_btn_frame, text='Usuń', command=app.remove_custom_text).pack(side=tk.LEFT)

        # ── Właściwości ──
        props_box = tk.LabelFrame(left, text='Właściwości')
        props_box.pack(fill=tk.BOTH, expand=True, pady=(0, 8))
        app.props_scroll = ScrollableFrame(props_box)
        app.props_scroll.pack(fill='both', expand=True, ipady=150)
        app.props_container = app.props_scroll.inner
        app.property_widgets = {}
        app.edit_mode = 'builtin'
