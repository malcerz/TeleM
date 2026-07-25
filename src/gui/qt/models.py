"""Modele danych — struktury przekazywane między GUI a kontrolerem.

GUI operuje tylko na tych strukturach, nie zna szczegółów GPMF/GPX/FIT.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class DataStream:
    """Reprezentuje pojedynczy strumień danych telemetrycznych.

    Tworzony przez kontroler po analizie załadowanych danych.
    GUI używa go do dynamicznego tworzenia przycisków.
    """

    key: str            # unikalny identyfikator (np. "speed_text", "heart_rate")
    display_name: str   # nazwa wyświetlana (np. "Prędkość", "Heart Rate")
    source: str         # źródło: "gpmf", "gpx", "fit"
    category: str       # kategoria: "gps", "sensor", "camera", "other"
    unit: str = ""      # jednostka (np. "km/h", "bpm", "m")

    # Sugerowana forma wizualizacji
    suggested_form: str = "text"  # "text", "gauge", "bar", "chart", "map"

    # Liczba dostępnych próbek
    sample_count: int = 0

    # Zakres wartości [min, max]
    value_range: tuple[float, float] = (0.0, 100.0)


@dataclass
class FieldSchema:
    """Schema pojedynczego pola właściwości wskaźnika."""

    name: str           # nazwa pola (np. "font_size", "color", "min_val")
    field_type: str     # typ: "bool", "int", "float", "choice", "text", "color"
    label: str          # etykieta wyświetlana

    # Zakładka w panelu właściwości ("" = header nad zakładkami):
    tab: str = "Text"

    # Dla typów numerycznych:
    min_val: float | None = None
    max_val: float | None = None
    step: float | None = None

    # Dla typu choice:
    choices: list[str] | None = None


# ── Fabryki pól per-zakładka ────────────────────────────────────────────────

def _header_fields(with_source: bool = True) -> list[FieldSchema]:
    """Pola zawsze widoczne nad zakładkami (pozycja, etykieta, rotacja)."""
    fields = [
        FieldSchema("size", "float", "Rozmiar", tab="",
                    min_val=0.01, max_val=0.5, step=0.001),
        FieldSchema("label", "text", "Etykieta", tab=""),
        FieldSchema("x", "float", "Pozycja X", tab="",
                    min_val=0.0, max_val=1.0, step=0.001),
        FieldSchema("y", "float", "Pozycja Y", tab="",
                    min_val=0.0, max_val=1.0, step=0.001),
        FieldSchema("rotation", "choice", "Rotacja", tab="",
                    choices=["0", "90", "180", "270"]),
    ]
    if with_source:
        fields.append(
            FieldSchema("source", "choice", "Źródło", tab="",
                        choices=["gpmf", "gpx", "fit"]),
        )
    return fields


def _form_field(choices: list[str] | None = None) -> list[FieldSchema]:
    """Pole wyboru formy – zawsze widoczne."""
    if choices is None:
        choices = ["text", "gauge", "bar", "chart", "segment_bar", "map"]
    return [
        FieldSchema("form", "choice", "Forma", tab="", choices=choices),
    ]


def _text_tab_fields(
    font_range=(0.005, 0.1), repo_range=(-0.3, 0.3),
    with_color: bool = True, with_distance: bool = False,
) -> list[FieldSchema]:
    """Zakładka Text – wygląd tekstu wartości i jego pozycja."""
    fields: list[FieldSchema] = [
        FieldSchema("font_size", "float", "Size",
                    tab="Text",
                    min_val=font_range[0], max_val=font_range[1], step=0.001),
        FieldSchema("decimals", "int", "Decimals",
                    tab="Text", min_val=0, max_val=3, step=1),
        FieldSchema("show_value", "bool", "Value", tab="Text"),
        FieldSchema("show_units", "bool", "Units", tab="Text"),
    ]
    if with_distance:
        fields.append(
            FieldSchema("text_distance", "float", "Distance",
                        tab="Text", min_val=-2.0, max_val=2.0, step=0.1))
    if with_color:
        fields.append(
            FieldSchema("text_color", "color", "Color", tab="Text"))
    fields += [
        FieldSchema("text_offset_x", "float", "Pos X",
                    tab="Text",
                    min_val=repo_range[0], max_val=repo_range[1], step=0.001),
        FieldSchema("text_offset_y", "float", "Pos Y",
                    tab="Text",
                    min_val=repo_range[0], max_val=repo_range[1], step=0.001),
    ]
    return fields


def _labels_tab_fields() -> list[FieldSchema]:
    """Zakładka Labels – etykiety na osi."""
    return [
        FieldSchema("label_count", "int", "Number",
                    tab="Labels", min_val=2, max_val=21, step=1),
        FieldSchema("label_font_size", "float", "Size",
                    tab="Labels", min_val=1.0, max_val=10.0, step=0.1),
        FieldSchema("label_units", "bool", "Units", tab="Labels"),
        FieldSchema("show_average", "bool", "Average", tab="Labels"),
    ]


def _ticks_tab_fields(with_range: bool = True) -> list[FieldSchema]:
    """Zakładka Ticks – podziałki i zakres wartości."""
    fields: list[FieldSchema] = [
        FieldSchema("ticks", "int", "Tick",
                    tab="Ticks", min_val=0, max_val=20, step=1),
        FieldSchema("thickness", "int", "Width",
                    tab="Ticks", min_val=1, max_val=10, step=1),
    ]
    if with_range:
        fields += [
            FieldSchema("min_val", "float", "Minimum", tab="Ticks",
                        min_val=0, max_val=1000, step=1),
            FieldSchema("max_val", "float", "Maksimum", tab="Ticks",
                        min_val=1, max_val=10000, step=1),
        ]
    return fields


def _gauge_tab_fields() -> list[FieldSchema]:
    """Zakładka Gauge – kropka kursora, kąt, pionowy bar."""
    return [
        FieldSchema("marker_size", "int", "Size",
                    tab="Gauge", min_val=3, max_val=20, step=1),
        FieldSchema("marker_color", "color", "Color", tab="Gauge"),
        FieldSchema("bar_width", "int", "Width",
                    tab="Gauge", min_val=1, max_val=10, step=1),
        FieldSchema("show_bar", "bool", "Bar", tab="Gauge"),
        FieldSchema("start_angle", "int", "Kąt startu",
                    tab="Gauge", min_val=0, max_val=360, step=5),
        FieldSchema("sweep_angle", "int", "Rozpiętość",
                    tab="Gauge", min_val=30, max_val=360, step=5),
    ]


def _chart_tab_fields() -> list[FieldSchema]:
    """Zakładka Chart – wygląd wykresu."""
    return [
        FieldSchema("chart_color", "color", "Linia", tab="Chart"),
        FieldSchema("fill_color", "color", "Wypełnienie", tab="Chart"),
        FieldSchema("fill_alpha", "int", "Alfa", tab="Chart",
                    min_val=0, max_val=255, step=5),
        FieldSchema("grid_color", "color", "Siatka", tab="Chart"),
        FieldSchema("show_grid", "bool", "Pokaż siatkę", tab="Chart"),
        FieldSchema("window_s", "float", "Okno czasu (s)", tab="Chart",
                    min_val=5.0, max_val=300.0, step=5.0),
        FieldSchema("line_width", "int", "Grubość linii", tab="Chart",
                    min_val=1, max_val=8, step=1),
    ]


def _segments_tab_fields() -> list[FieldSchema]:
    """Zakładka Segments – specyficzne dla segment_bar."""
    return [
        FieldSchema("segments", "int", "Segmenty", tab="Segments",
                    min_val=2, max_val=50, step=1),
        FieldSchema("segment_gap", "int", "Odstęp", tab="Segments",
                    min_val=0, max_val=20, step=1),
        FieldSchema("segment_radius", "int", "Zaokrągl.", tab="Segments",
                    min_val=0, max_val=20, step=1),
        FieldSchema("inactive_alpha", "int", "Alfa nieakt.", tab="Segments",
                    min_val=20, max_val=255, step=5),
        FieldSchema("inactive_color", "color", "Kolor nieakt.", tab="Segments"),
        FieldSchema("direction", "choice", "Kierunek", tab="Segments",
                    choices=["horizontal", "vertical"]),
        FieldSchema("grow_height", "bool", "Rosnąca wys.", tab="Segments"),
        FieldSchema("min_val", "float", "Minimum", tab="Segments",
                    min_val=0, max_val=1000, step=1),
        FieldSchema("max_val", "float", "Maksimum", tab="Segments",
                    min_val=1, max_val=10000, step=1),
        FieldSchema("show_min", "bool", "Pokaż min.", tab="Segments"),
        FieldSchema("show_max", "bool", "Pokaż max", tab="Segments"),
    ]


def _shape_tab_fields() -> list[FieldSchema]:
    """Zakładka Shape – pola specyficzne dla kształtu."""
    return []


# ── Schematy per-typ wskaźnika ─────────────────────────────────────────────

def text_indicator_fields() -> list[FieldSchema]:
    """Text: Header + Text."""
    return (
        _header_fields() + _form_field() + _text_tab_fields()
    )


def gauge_indicator_fields() -> list[FieldSchema]:
    """Gauge: Header, Text, Labels, Ticks, Gauge."""
    return (
        _header_fields() + _form_field()
        + _text_tab_fields()
        + _labels_tab_fields()
        + _ticks_tab_fields()
        + _gauge_tab_fields()
    )


def bar_indicator_fields() -> list[FieldSchema]:
    """Bar: Header, Text, Labels, Ticks, Gauge + range_labels."""
    return (
        _header_fields() + _form_field()
        + _text_tab_fields(with_distance=False)
        + _labels_tab_fields()
        + _ticks_tab_fields()
        + _gauge_tab_fields()
        + [
            FieldSchema("show_range_labels", "bool", "Pokaż zakres", tab="Text"),
            FieldSchema("range_label_offset_x", "float", "Offset X", tab="Text",
                        min_val=-0.2, max_val=0.2, step=0.001),
            FieldSchema("range_label_offset_y", "float", "Offset Y", tab="Text",
                        min_val=-0.2, max_val=0.2, step=0.001),
            FieldSchema("bar_direction", "choice", "Kierunek", tab="Gauge",
                        choices=["horizontal", "vertical"]),
            FieldSchema("dot_color", "color", "Kolor kropki", tab="Gauge"),
        ]
    )


def chart_indicator_fields() -> list[FieldSchema]:
    """Chart: Header, Text, Labels, Ticks, Chart (własna zakładka)."""
    return (
        _header_fields() + _form_field()
        + _text_tab_fields(with_color=False)
        + _labels_tab_fields()
        + _ticks_tab_fields()
        + _chart_tab_fields()
    )


def segment_bar_indicator_fields() -> list[FieldSchema]:
    """SegmentBar: Header, Text, Segments (własna zakładka)."""
    return (
        _header_fields() + _form_field()
        + _text_tab_fields(with_color=False)
        + _segments_tab_fields()
        + [
            FieldSchema("show_label", "bool", "Pokaż etyk.", tab="Text"),
            FieldSchema("width", "int", "Szerokość", tab="Segments",
                        min_val=50, max_val=500, step=10),
            FieldSchema("height", "int", "Wysokość", tab="Segments",
                        min_val=20, max_val=200, step=5),
        ]
    )


def map_indicator_fields() -> list[FieldSchema]:
    """Map: Header, Text, mapa."""
    return (
        _header_fields()
        + [FieldSchema("form", "choice", "Typ mapy", tab="",
                       choices=["map", "static_map"])]
        + _text_tab_fields(with_color=False)
        + [
            FieldSchema("zoom", "int", "Zoom", tab="Text",
                        min_val=10, max_val=20, step=1),
            FieldSchema("map_style", "choice", "Styl mapy", tab="Text",
                        choices=["light_all", "light_nolabels", "dark_all",
                                 "dark_nolabels", "voyager_all", "voyager_nolabels"]),
            FieldSchema("marker_size", "int", "Znacznik", tab="Text",
                        min_val=3, max_val=20, step=1),
            FieldSchema("marker_color", "color", "Kolor znacz.", tab="Text"),
        ]
    )


# Mapa: forma → funkcja generująca schemat
FORM_SCHEMA_MAP: dict[str, callable] = {
    "text":        text_indicator_fields,
    "gauge":       gauge_indicator_fields,
    "bar":         bar_indicator_fields,
    "chart":       chart_indicator_fields,
    "segment_bar": segment_bar_indicator_fields,
    "map":         map_indicator_fields,
    "static_map":  map_indicator_fields,
}


def get_schema_for_form(form: str) -> list[FieldSchema]:
    """Zwraca schemat pól dla podanej formy wskaźnika."""
    fn = FORM_SCHEMA_MAP.get(form, text_indicator_fields)
    return fn()
