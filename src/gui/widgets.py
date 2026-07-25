"""GUI widget components for the TeleM HUD Tuner.

Provides reusable Tkinter widgets for building the property editor:
- ScrollableFrame – a frame with a vertical scrollbar
- NumericRow     – labelled scale + entry for numeric values
- BoolRow        – labelled checkbox for boolean values
- ChoiceRow      – labelled combobox for choice values
- TextRow        – labelled text entry
- ColorRow       – colour picker with preview swatch
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Any, Callable, Optional

# ── Field label translations (English) ──────────────────────────────────────

FIELD_LABELS: dict[str, str] = {
    "enabled": "enabled",
    "label": "label",
    "x": "position X",
    "y": "position Y",
    "rotation": "rotation",
    "form": "form (text/gauge/bar/chart)",
    "font_size": "font size",
    "font_label": "font label",
    "font_date": "font date",
    "font_time": "font time",
    "size": "size",
    "thickness": "thickness",
    "min_val": "min",
    "max_val": "max",
    "ticks": "ticks",
    "show_value": "show value",
    "source": "source",
    "show_range_labels": "show range",
    "range_label_offset_x": "offset X",
    "range_label_offset_y": "offset Y",
    "range_label_spread_x": "spread X",
    "chart_color": "chart colour",
    "fill_color": "fill colour",
    "fill_alpha": "fill alpha",
    "value_offset_x": "value offset X",
    "value_offset_y": "value offset Y",
    "text": "text content",
    "color": "text colour",
}

# GPX extension indicator keys and their display labels
GPX_EXT_FIELDS: list[str] = ["power_text", "atemp_text", "hr_text", "cad_text", "battery_text"]
GPX_EXT_LABELS: dict[str, str] = {
    "power_text": "Power (W)",
    "atemp_text": "Amb. Temp.",
    "hr_text": "Heart Rate (BPM)",
    "cad_text": "Cadence",
    "battery_text": "Battery (%)",
}


# ── Widget classes ──────────────────────────────────────────────────────────


class FlowFrame(tk.Frame):
    """Frame z przepływem — elementy układają się od lewej do prawej,
    zawijając do nowego rzędu gdy brak miejsca w poziomie."""

    def __init__(self, master: tk.Widget, **kwargs) -> None:
        super().__init__(master, **kwargs)
        self._rows: list[tk.Frame] = []
        self._row_widths: list[int] = []
        self._total_width = 0
        self._start_new_row()
        self.bind("<Configure>", self._on_resize, add="+")

    def _start_new_row(self) -> None:
        row = tk.Frame(self)
        row.pack(fill=tk.X, anchor="w")
        self._rows.append(row)
        self._row_widths.append(0)

    def add_widget(self, widget: tk.Widget, padx: int = 2, pady: int = 1) -> None:
        """Dodaje widget do przepływu — automatycznie zawija."""
        if not self._rows:
            self._start_new_row()
        row = self._rows[-1]
        widget.pack(in_=row, side=tk.LEFT, padx=padx, pady=pady)
        self._total_width += widget.winfo_reqwidth() + padx * 2
        self._row_widths[-1] += widget.winfo_reqwidth() + padx * 2
        self._reflow()

    def _reflow(self) -> None:
        """Przepakowuje elementy — zawija do nowego rzędu gdy brak miejsca."""
        avail = self.winfo_width()
        if avail < 20:
            return
        # Zbierz wszystkie widgety
        all_widgets: list[tk.Widget] = []
        for row in self._rows:
            for child in list(row.winfo_children()):
                all_widgets.append(child)
            row.destroy()
        self._rows.clear()
        self._row_widths.clear()
        self._total_width = 0

        if not all_widgets:
            return

        self._start_new_row()
        for w in all_widgets:
            w.pack_forget()
            rw = w.winfo_reqwidth() + 4  # 2*2 padx
            if self._row_widths[-1] + rw > avail and self._row_widths[-1] > 0:
                self._start_new_row()
            w.pack(in_=self._rows[-1], side=tk.LEFT, padx=2, pady=1)
            self._row_widths[-1] += rw

    def _on_resize(self, event: tk.Event | None = None) -> None:
        self._reflow()

    def clear(self) -> None:
        """Usuwa wszystkie widgety."""
        for row in self._rows:
            row.destroy()
        self._rows.clear()
        self._row_widths.clear()
        self._total_width = 0
        self._start_new_row()


class ScrollableFrame(tk.Frame):
    """A frame with a built-in vertical scrollbar.

    Usage:
        container = ScrollableFrame(parent)
        container.pack(fill='both', expand=True)
        child_widget = tk.Label(container.inner, text='Hello')
        child_widget.pack()
    """

    def __init__(self, master: tk.Widget) -> None:
        super().__init__(master)
        self.canvas = tk.Canvas(self, highlightthickness=0)
        self.vbar = tk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.vbar.set)
        self.vbar.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.inner = tk.Frame(self.canvas)
        self.window_id = self.canvas.create_window(
            (0, 0), window=self.inner, anchor="nw"
        )
        self.inner.bind("<Configure>", self._on_frame_configure)
        self.canvas.bind("<Configure>", self._on_canvas_configure)

    def _on_frame_configure(self, event: Optional[tk.Event] = None) -> None:
        """Update the scroll region when the inner frame resizes."""
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _on_canvas_configure(self, event: Optional[tk.Event] = None) -> None:
        """Resize the inner frame to fill the canvas width."""
        if event is not None:
            self.canvas.itemconfigure(self.window_id, width=event.width)


class NumericRow(tk.Frame):
    """A labelled horizontal slider + entry for editing a numeric property.

    Args:
        master: Parent widget.
        name: Property name (used for the label via FIELD_LABELS).
        value: Initial value.
        mn: Minimum value.
        mx: Maximum value.
        step: Step / resolution.
        callback: Called when the value changes.
        is_int: If True, the value is displayed and returned as an integer.
    """

    def __init__(
        self,
        master: tk.Widget,
        name: str,
        value: float,
        mn: float,
        mx: float,
        step: float,
        callback: Callable[[], None],
        is_int: bool = False,
    ) -> None:
        super().__init__(master)
        self.mn, self.mx, self.step = mn, mx, step
        self.callback = callback
        self.is_int = is_int
        self.var = tk.DoubleVar(value=float(value))

        self.grid_columnconfigure(0, weight=0)
        self.grid_columnconfigure(1, weight=1)
        self.grid_columnconfigure(2, weight=0)

        tk.Label(
            self, text=FIELD_LABELS.get(name, name), width=12, anchor="w"
        ).grid(row=0, column=0, sticky="w", padx=(0, 4))

        self.scale = tk.Scale(
            self,
            variable=self.var,
            from_=mn,
            to=mx,
            resolution=step,
            orient=tk.HORIZONTAL,
            showvalue=False,
            length=85,
            sliderlength=12,
            width=10,
            takefocus=1,
            command=lambda _: self.on_scale(),
        )
        self.scale.grid(row=0, column=1, sticky="ew", padx=(0, 4))
        self.scale.bind("<Button-1>", lambda e: self.scale.focus_set())
        self.entry = tk.Entry(self, width=5)
        self.entry.grid(row=0, column=2, sticky="e")
        self.entry.insert(0, self.format_value(value))
        self.entry.bind("<Return>", self.on_entry)
        self.entry.bind("<FocusOut>", self.on_entry)

    def format_value(self, value: float) -> str:
        """Format a numeric value for display in the entry field."""
        if self.is_int or self.step >= 1:
            return str(int(round(value)))
        return f"{value:.3f}".rstrip("0").rstrip(".")

    def clamp(self, value: float) -> float:
        """Clamp value to [mn, mx]."""
        return max(self.mn, min(self.mx, value))

    def on_scale(self) -> None:
        """Handle scale slider movement."""
        self.sync_entry()
        self.callback()

    def on_entry(self, event: Optional[tk.Event] = None) -> None:
        """Handle manual entry in the text field."""
        try:
            value = float(self.entry.get().replace(",", "."))
        except ValueError:
            self.sync_entry()
            return
        self.var.set(self.clamp(value))
        self.sync_entry()
        self.callback()

    def sync_entry(self) -> None:
        """Sync the entry text with the current var value."""
        self.entry.delete(0, tk.END)
        self.entry.insert(0, self.format_value(self.var.get()))

    def _on_arrow_left(self, event: Optional[tk.Event] = None) -> None:
        """Decrement by step on left arrow key."""
        self.var.set(self.clamp(self.var.get() - self.step))
        self.sync_entry()
        self.callback()

    def _on_arrow_right(self, event: Optional[tk.Event] = None) -> None:
        """Increment by step on right arrow key."""
        self.var.set(self.clamp(self.var.get() + self.step))
        self.sync_entry()
        self.callback()

    def get(self) -> int | float:
        """Return the current value (int if is_int, else float)."""
        return int(round(self.var.get())) if self.is_int else float(self.var.get())


class BoolRow(tk.Frame):
    """A labelled checkbox for editing a boolean property.

    Args:
        master: Parent widget.
        name: Property name (used for the label via FIELD_LABELS).
        value: Initial value.
        callback: Called when the value changes.
    """

    def __init__(
        self,
        master: tk.Widget,
        name: str,
        value: bool,
        callback: Callable[[], None],
    ) -> None:
        super().__init__(master)
        self.var = tk.BooleanVar(value=bool(value))
        tk.Checkbutton(
            self,
            text=FIELD_LABELS.get(name, name),
            variable=self.var,
            command=callback,
        ).pack(anchor="w")

    def get(self) -> bool:
        """Return the current boolean value."""
        return bool(self.var.get())


class ChoiceRow(tk.Frame):
    """A labelled combobox for editing a choice property.

    Args:
        master: Parent widget.
        name: Property name (used for the label via FIELD_LABELS).
        value: Initial value.
        choices: List of valid choices.
        callback: Called when the selection changes.
    """

    def __init__(
        self,
        master: tk.Widget,
        name: str,
        value: Any,
        choices: list[Any],
        callback: Callable[[], None],
    ) -> None:
        super().__init__(master)
        self.callback = callback

        tk.Label(
            self, text=FIELD_LABELS.get(name, name), width=8, anchor="w"
        ).pack(side=tk.LEFT)

        self.var = tk.StringVar(value=str(value))

        cb = ttk.Combobox(
            self,
            textvariable=self.var,
            values=[str(c) for c in choices],
            state="readonly",
            width=3,
        )
        cb.pack(side=tk.LEFT, padx=(2, 0))
        cb.bind("<<ComboboxSelected>>", lambda e: self.callback())

    def get(self) -> int | str:
        """Return the current selection as int (if possible) or str."""
        val = self.var.get()
        try:
            return int(val)
        except (ValueError, TypeError):
            return val


class TextRow(tk.Frame):
    """A labelled text entry field.

    Args:
        master: Parent widget.
        name: Property name (used for the label via FIELD_LABELS).
        value: Initial text value.
        callback: Called when the value changes (Enter or FocusOut).
    """

    def __init__(
        self,
        master: tk.Widget,
        name: str,
        value: str,
        callback: Callable[[], None],
    ) -> None:
        super().__init__(master)
        self.callback = callback
        tk.Label(
            self, text=FIELD_LABELS.get(name, name), width=12, anchor="w"
        ).pack(side=tk.LEFT)
        self.var = tk.StringVar(value=str(value))
        e = tk.Entry(self, textvariable=self.var)
        e.pack(side=tk.LEFT)
        e.bind("<Return>", lambda e: self.callback())
        e.bind("<FocusOut>", lambda e: self.callback())

    def get(self) -> str:
        """Return the current text value."""
        return self.var.get()


class ColorRow(tk.Frame):
    """A colour picker widget with a preview swatch and a palette button.

    Args:
        master: Parent widget.
        name: Property name (used for the label via FIELD_LABELS).
        value: Initial colour value (hex string, e.g. '#FF3232').
        callback: Called when the colour changes.
    """

    def __init__(
        self,
        master: tk.Widget,
        name: str,
        value: str,
        callback: Callable[[], None],
    ) -> None:
        super().__init__(master)
        self.callback = callback
        tk.Label(
            self, text=FIELD_LABELS.get(name, name), width=12, anchor="w"
        ).pack(side=tk.LEFT)
        self.var = tk.StringVar(value=str(value) if value else "#FF3232")

        # Colour preview swatch
        self.color_preview = tk.Canvas(
            self, width=24, height=18, highlightthickness=1, highlightbackground="#555"
        )
        self.color_preview.pack(side=tk.LEFT, padx=(2, 4))
        self._update_preview()

        # Palette button
        btn = tk.Button(self, text="Palette...", command=self._choose_color)
        btn.pack(side=tk.LEFT)

    def _update_preview(self) -> None:
        """Update the preview swatch colour."""
        try:
            color = self.var.get().strip()
            if not color.startswith("#"):
                color = "#" + color
            self.color_preview.configure(bg=color)
        except Exception:
            self.color_preview.configure(bg="#888888")

    def _choose_color(self) -> None:
        """Open the system colour picker dialog."""
        from tkinter import colorchooser

        initial = self.var.get().strip()
        if not initial.startswith("#"):
            initial = "#" + initial
        result = colorchooser.askcolor(color=initial, title="Choose chart colour")
        if result and result[1]:
            self.var.set(result[1])
            self._update_preview()
            self.callback()

    def get(self) -> str:
        """Return the current colour value (hex string)."""
        val = self.var.get().strip()
        if val and not val.startswith("#"):
            val = "#" + val
        return val
