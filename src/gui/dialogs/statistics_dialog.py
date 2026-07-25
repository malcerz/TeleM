"""Dialog window for export statistics."""

import tkinter as tk
from tkinter import ttk
from pathlib import Path


def show_statistics_dialog(parent_root, stats: dict, export_duration: float, output_file):
    """Show modal dialog displaying export completion statistics."""
    dialog = tk.Toplevel(parent_root)
    dialog.title("Statystyki eksportu")
    dialog.geometry("500x320")
    dialog.resizable(False, False)
    dialog.transient(parent_root)
    dialog.grab_set()

    try:
        x = parent_root.winfo_x() + (parent_root.winfo_width() - 500) // 2
        y = parent_root.winfo_y() + (parent_root.winfo_height() - 320) // 2
        dialog.geometry(f"+{x}+{y}")
    except Exception:
        pass

    title_label = ttk.Label(dialog, text="Eksport zakończony pomyślnie!", font=("Segoe UI", 12, "bold"))
    title_label.pack(pady=(15, 5))

    desc_label = ttk.Label(dialog, text=f"Plik: {Path(output_file).name}", font=("Segoe UI", 9, "italic"))
    desc_label.pack(pady=(0, 15))

    table_frame = ttk.Frame(dialog, padding=10)
    table_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=5)

    ttk.Label(table_frame, text="Etap", font=("Segoe UI", 10, "bold")).grid(row=0, column=0, sticky="w", padx=10, pady=5)
    ttk.Label(table_frame, text="Czas trwania", font=("Segoe UI", 10, "bold")).grid(row=0, column=1, sticky="w", padx=10, pady=5)
    ttk.Label(table_frame, text="Średnia wydajność", font=("Segoe UI", 10, "bold")).grid(row=0, column=2, sticky="w", padx=10, pady=5)

    ttk.Separator(table_frame, orient='horizontal').grid(row=1, column=0, columnspan=3, sticky='ew', pady=5)

    def fmt_time(seconds):
        if seconds >= 60:
            mins = int(seconds // 60)
            secs = seconds % 60
            return f"{mins} min {secs:.1f} s"
        return f"{seconds:.2f} s"

    def fmt_fps(frames, duration):
        if duration <= 0:
            return "0.0 fps"
        return f"{frames / duration:.1f} fps"

    # 1. Total Export
    total_time_str = fmt_time(export_duration)
    total_fps_str = fmt_fps(stats.get('final_frames', 0), export_duration)

    ttk.Label(table_frame, text="Od naciśnięcia Export", font=("Segoe UI", 10, "bold")).grid(row=2, column=0, sticky="w", padx=10, pady=5)
    ttk.Label(table_frame, text=total_time_str, font=("Segoe UI", 10, "bold")).grid(row=2, column=1, sticky="w", padx=10, pady=5)
    ttk.Label(table_frame, text=total_fps_str, font=("Segoe UI", 10, "bold")).grid(row=2, column=2, sticky="w", padx=10, pady=5)

    # 2. Streaming render
    png_time_str = fmt_time(stats.get('png_duration', 0))
    png_fps_str = fmt_fps(stats.get('total_overlay_frames', 0), stats.get('png_duration', 0))

    ttk.Label(table_frame, text="Render HUD + kompresja").grid(row=3, column=0, sticky="w", padx=10, pady=5)
    ttk.Label(table_frame, text=png_time_str).grid(row=3, column=1, sticky="w", padx=10, pady=5)
    ttk.Label(table_frame, text=png_fps_str).grid(row=3, column=2, sticky="w", padx=10, pady=5)

    btn = ttk.Button(dialog, text="OK", command=dialog.destroy)
    btn.pack(pady=15)
