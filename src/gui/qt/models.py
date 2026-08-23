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
    field_type: str     # typ: "bool", "int", "float", "choice", "text", "color", "font"
    label: str          # etykieta wyświetlana

    # Zakładka w panelu właściwości ("" = header nad zakładkami):
    tab: str = "Text"

    # Dla typów numerycznych:
    min_val: float | None = None
    max_val: float | None = None
    step: float | None = None

    # Dla typu choice:
    choices: list[str] | None = None

    # Placeholder / podpowiedź dla pól tekstowych (np. format progów):
    placeholder: str | None = None


# ── Fabryki pól per-zakładka ────────────────────────────────────────────────

def _header_fields(with_source: bool = True, text_size: bool = False) -> list[FieldSchema]:
    """Pola zawsze widoczne nad zakładkami (pozycja, etykieta, rotacja)."""
    fields = [
        FieldSchema(
            "font_size" if text_size else "size", "float", "Rozmiar", tab="",
            min_val=0.5 if text_size else 1.0,
            max_val=10.0 if text_size else 100.0,
            step=0.1,
        ),
        FieldSchema("label", "text", "Etykieta", tab=""),
        FieldSchema("unit", "text", "Jednostka", tab=""),
        FieldSchema("x", "float", "Pozycja X", tab="",
                    min_val=0.0, max_val=100.0, step=0.1),
        FieldSchema("y", "float", "Pozycja Y", tab="",
                    min_val=0.0, max_val=100.0, step=0.1),
        FieldSchema("rotation", "choice", "Rotacja", tab="",
                    choices=["0", "90", "180", "270"]),
        FieldSchema("font", "font", "Font", tab=""),
        FieldSchema("icon", "choice", "Ikona", tab="", choices=[
            "none", "clock", "camera", "temperature", "battery", "solar",
        ]),
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
    font_range=(0.5, 10.0), repo_range=(-0.5, 0.5),
    with_color: bool = True, with_distance: bool = False,
    include_font_size: bool = True,
) -> list[FieldSchema]:
    """Zakładka Text – wygląd tekstu wartości i jego pozycja."""
    fields: list[FieldSchema] = []
    if include_font_size:
        fields.append(FieldSchema("font_size", "float", "Size",
                                   tab="Text",
                                   min_val=font_range[0], max_val=font_range[1], step=0.1))
    fields += [FieldSchema("decimals", "int", "Decimals",
                    tab="Text", min_val=0, max_val=3, step=1),
        FieldSchema("show_value", "bool", "Value", tab="Text"),
        FieldSchema("show_units", "bool", "Units", tab="Text"),
    ]
    if with_distance:
        fields.append(
            FieldSchema("text_distance", "float", "Distance",
                        tab="Text", min_val=-200.0, max_val=200.0, step=1.0))
    if with_color:
        fields.append(
            FieldSchema("text_color", "color", "Color", tab="Text"))
    fields += [
        FieldSchema("text_offset_x", "float", "Pos X",
                    tab="Text",
                    min_val=repo_range[0], max_val=repo_range[1], step=0.01),
        FieldSchema("text_offset_y", "float", "Pos Y",
                    tab="Text",
                    min_val=repo_range[0], max_val=repo_range[1], step=0.01),
    ]
    return fields


def _labels_tab_fields() -> list[FieldSchema]:
    """Zakładka Labels – etykiety na osi."""
    return [
        FieldSchema("show_x_axis_values", "bool", "Wartości osi poziomej", tab="Labels"),
        FieldSchema("show_y_axis_values", "bool", "Wartości osi pionowej", tab="Labels"),
        FieldSchema("label_count", "int", "Number",
                    tab="Labels", min_val=2, max_val=21, step=1),
        FieldSchema("label_font_size", "float", "Size",
                    tab="Labels", min_val=1.0, max_val=10.0, step=0.1),
        FieldSchema("label_units", "bool", "Units", tab="Labels"),
        FieldSchema("show_average", "bool", "Average", tab="Labels"),
    ]


def _ticks_tab_fields(with_range: bool = True, with_ticks: bool = True) -> list[FieldSchema]:
    """Zakładka Ticks – podziałki i zakres wartości."""
    fields: list[FieldSchema] = []
    if with_ticks:
        fields.append(FieldSchema("ticks", "int", "Liczba podziałek",
                                  tab="Ticks", min_val=0, max_val=20, step=1))
    fields.append(FieldSchema("major_step", "float", "Krok główny", tab="Ticks",
                              min_val=0.0, max_val=1000.0, step=0.1))
    fields.append(FieldSchema("thickness", "int", "Grubość podziałek",
                              tab="Ticks", min_val=1, max_val=10, step=1))
    if with_range:
        fields += [
            FieldSchema("min_val", "float", "Minimum", tab="Ticks",
                        min_val=-1000, max_val=1000, step=1),
            FieldSchema("max_val", "float", "Maksimum", tab="Ticks",
                        min_val=-1000, max_val=10000, step=1),
        ]
    return fields


def _gauge_tab_fields() -> list[FieldSchema]:
    """Zakładka Gauge – kropka kursora, kąt, pionowy bar."""
    return [
        FieldSchema("show_marker", "bool", "Kropka środka", tab="Gauge"),
        FieldSchema("marker_size", "int", "Rozmiar kropki",
                    tab="Gauge", min_val=0, max_val=30, step=1),
        FieldSchema("marker_color", "color", "Kolor kropki", tab="Gauge"),
        FieldSchema("start_angle", "int", "Kąt startu",
                    tab="Gauge", min_val=0, max_val=360, step=5),
        FieldSchema("sweep_angle", "int", "Rozpiętość",
                    tab="Gauge", min_val=30, max_val=360, step=5),
        FieldSchema("needle_length", "float", "Dł. wskazówki",
                    tab="Gauge", min_val=0.1, max_val=2.0, step=0.05),
        FieldSchema("needle_width", "int", "Grubość wskazówki",
                    tab="Gauge", min_val=2, max_val=20, step=1),
        FieldSchema("needle_color", "color", "Kolor wskazówki", tab="Gauge"),
    ]


def _chart_tab_fields(chart_time_scope: str = "activity") -> list[FieldSchema]:
    """Zakładka Chart – wygląd wykresu."""
    fields = [
        FieldSchema(
            "chart_time_scope", "choice", "Zakres czasu wykresu", tab="Chart",
            choices=[
                ("activity", "Cała aktywność"),
                ("video", "Zakres filmu"),
                ("window", "Ostatnie N sekund"),
            ],
        ),
        FieldSchema("chart_color", "color", "Linia", tab="Chart"),
        FieldSchema("fill_color", "color", "Wypełnienie", tab="Chart"),
        FieldSchema("fill_alpha", "int", "Alfa", tab="Chart",
                    min_val=0, max_val=255, step=5),
        FieldSchema("grid_color", "color", "Siatka", tab="Chart"),
        FieldSchema("show_grid", "bool", "Pokaż siatkę", tab="Chart"),
        FieldSchema("line_width", "int", "Grubość linii", tab="Chart",
                    min_val=1, max_val=8, step=1),
    ]
    if chart_time_scope == "window":
        fields.insert(
            1,
            FieldSchema(
                "chart_window_s", "float", "Okno historii [s]", tab="Chart",
                min_val=5.0, max_val=600.0, step=1.0,
            ),
        )
    return fields


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
    """Text: one canonical size control in the header + Text settings."""
    return (
        _header_fields(text_size=True) + _form_field()
        + _text_tab_fields(include_font_size=False)
    )


def gauge_indicator_fields() -> list[FieldSchema]:
    """Gauge: Header, Text, Ticks, Gauge."""
    return (
        _header_fields() + _form_field()
        + _text_tab_fields()
        + [FieldSchema("tick_profile", "choice", "Profil ticków", tab="Ticks",
                       choices=["default", "pixel"])]
        + _ticks_tab_fields()
        + _gauge_tab_fields()
    )


def compass_indicator_fields() -> list[FieldSchema]:
    """Compass: gauge layout controls plus compass-only styling fields."""
    return (
        _header_fields() + _form_field(["gauge"])
        + _text_tab_fields()
        + _ticks_tab_fields(with_range=False)
        + [
            FieldSchema("tick_profile", "choice", "Profil ticków", tab="Compass",
                        choices=["default", "pixel"]),
            FieldSchema("field", "choice", "Pole", tab="Compass", choices=["heading"]),
            FieldSchema("gauge_style", "choice", "Styl", tab="Compass", choices=["compass"]),
            FieldSchema("opacity", "float", "Przezroczystość", tab="Compass",
                        min_val=0.0, max_val=1.0, step=0.05),
            FieldSchema("compass_show_cardinals", "bool", "N/E/S/W", tab="Compass"),
            FieldSchema("compass_show_heading", "bool", "Wartość heading", tab="Compass"),
            FieldSchema("compass_heading_format", "choice", "Format heading", tab="Compass",
                        choices=["03d", "d"]),
            FieldSchema("compass_tick_degrees", "int", "Subtick co", tab="Compass",
                        min_val=5, max_val=90, step=5),
            FieldSchema("compass_major_tick_degrees", "int", "Główny tick co", tab="Compass",
                        min_val=15, max_val=90, step=15),
            FieldSchema("compass_tick_color", "color", "Kolor ticków", tab="Compass"),
            FieldSchema("compass_cardinal_color", "color", "Kolor N/E/S/W", tab="Compass"),
            FieldSchema("compass_needle_color", "color", "Kolor wskazówki", tab="Compass"),
            FieldSchema("compass_ring_color", "color", "Kolor tarczy", tab="Compass"),
            FieldSchema("compass_heading_color", "color", "Kolor wartości", tab="Compass"),
        ]
    )


def _bar_ruler_fields() -> list[FieldSchema]:
    """Pola specyficzne dla stylu 'ruler'."""
    return [
        # Tab Text
        FieldSchema("show_value", "bool", "Wartość", tab="Text"),
        FieldSchema("show_label", "bool", "Etykieta", tab="Text"),
        FieldSchema("show_range_labels", "bool", "Zakres", tab="Text"),
        FieldSchema("show_mid_label", "bool", "Środek", tab="Text"),
        FieldSchema("range_units", "bool", "Jednostki", tab="Text"),
        FieldSchema("title_with_unit", "bool", "Tytuł z jednostką", tab="Text"),
        FieldSchema("decimals", "int", "Decimals", tab="Text", min_val=0, max_val=3, step=1),
        FieldSchema("text_color", "color", "Kolor tekstu", tab="Text"),
        FieldSchema("range_color", "color", "Kolor zakresu", tab="Text"),
        FieldSchema("text_offset_x", "float", "Pos X", tab="Text", min_val=-0.5, max_val=0.5, step=0.01),
        FieldSchema("text_offset_y", "float", "Pos Y", tab="Text", min_val=-0.5, max_val=0.5, step=0.01),
        # Tab Ticks
        FieldSchema("major_ticks", "int", "Podziałki gł.", tab="Ticks", min_val=1, max_val=30, step=1),
        FieldSchema("minor_ticks", "int", "Podziałki drobne", tab="Ticks", min_val=1, max_val=10, step=1),
        FieldSchema("ticks", "int", "Ticks (legacy)", tab="Ticks", min_val=0, max_val=30, step=1),
        FieldSchema("track_color", "color", "Kolor osi", tab="Ticks"),
        FieldSchema("tick_color", "color", "Kolor kresek", tab="Ticks"),
        FieldSchema("marker_color", "color", "Kolor wskaźnika", tab="Ticks"),
        FieldSchema("marker_border_color", "color", "Obramowanie wsk.", tab="Ticks"),
        FieldSchema("marker_size", "float", "Rozmiar wskaźnika", tab="Ticks", min_val=2.0, max_val=30.0, step=0.5),
        FieldSchema("tick_profile", "choice", "Profil ticków", tab="Ticks", choices=["default", "pixel"]),
        # Tab Gauge (Zakres / Grubość)
        FieldSchema("min_val", "float", "Minimum", tab="Gauge", min_val=-10000.0, max_val=10000.0, step=1.0),
        FieldSchema("max_val", "float", "Maksimum", tab="Gauge", min_val=-10000.0, max_val=100000.0, step=1.0),
        FieldSchema("thickness", "int", "Grubość", tab="Gauge", min_val=1, max_val=10, step=1),
    ]


def _bar_segments_fields() -> list[FieldSchema]:
    """Pola specyficzne dla stylu 'segments' (Segment Bar, ETAP 10T)."""
    return [
        # ── Tab Text (wartość / etykieta / zakres) ──────────────────────
        FieldSchema("show_value", "bool", "Wartość", tab="Text"),
        FieldSchema("show_label", "bool", "Etykieta", tab="Text"),
        FieldSchema("show_min", "bool", "Pokaż min.", tab="Text"),
        FieldSchema("show_max", "bool", "Pokaż max", tab="Text"),
        FieldSchema("show_marker", "bool", "Pokaż marker", tab="Text"),
        FieldSchema("range_units", "bool", "Jednostki", tab="Text"),
        FieldSchema("decimals", "int", "Decimals", tab="Text", min_val=0, max_val=3, step=1),
        FieldSchema("value_font", "font", "Font wartości", tab="Text"),
        FieldSchema("value_font_size", "float", "Rozmiar wartości", tab="Text", min_val=0.5, max_val=5.0, step=0.05),
        FieldSchema("label_font", "font", "Font etykiety", tab="Text"),
        FieldSchema("label_font_size", "float", "Rozmiar etykiety", tab="Text", min_val=0.3, max_val=3.0, step=0.05),
        FieldSchema("range_font", "font", "Font zakresu", tab="Text"),
        FieldSchema("range_font_size", "float", "Rozmiar zakresu", tab="Text", min_val=0.3, max_val=3.0, step=0.05),
        FieldSchema("value_color", "color", "Kolor wartości", tab="Text"),
        FieldSchema("label_color", "color", "Kolor etykiety", tab="Text"),
        FieldSchema("text_color", "color", "Kolor tekstu", tab="Text"),
        FieldSchema("range_color", "color", "Kolor zakresu", tab="Text"),
        FieldSchema("value_align", "choice", "Wyrównanie wartości", tab="Text", choices=["left", "center", "right"]),
        FieldSchema("label_align", "choice", "Wyrównanie etykiety", tab="Text", choices=["left", "center", "right"]),
        FieldSchema("value_gap", "int", "Odstęp wartości", tab="Text", min_val=0, max_val=40, step=1),
        FieldSchema("label_gap", "int", "Odstęp etykiety", tab="Text", min_val=0, max_val=40, step=1),
        FieldSchema("range_gap", "int", "Odstęp zakresu", tab="Text", min_val=0, max_val=40, step=1),
        # ── Tab Segments (geometria) ─────────────────────────────────────
        FieldSchema("segments", "int", "Segmenty", tab="Segments", min_val=2, max_val=100, step=1),
        FieldSchema("segment_count", "int", "Liczba segmentów", tab="Segments", min_val=2, max_val=100, step=1),
        FieldSchema("segment_width", "float", "Szerokość segmentu", tab="Segments", min_val=0.0, max_val=200.0, step=1.0),
        FieldSchema("segment_height", "float", "Wysokość segmentu", tab="Segments", min_val=0.0, max_val=200.0, step=1.0),
        FieldSchema("segment_gap", "int", "Odstęp segmentów", tab="Segments", min_val=0, max_val=20, step=1),
        FieldSchema("segment_shape", "choice", "Kształt segmentu", tab="Segments", choices=[("rectangle", "Prostokąt"), ("rounded", "Zaokrąglony"), ("pill", "Pigułka")]),
        FieldSchema("segment_corner_radius", "float", "Zaokrąglenie", tab="Segments", min_val=0.0, max_val=40.0, step=0.5),
        FieldSchema("segment_radius", "float", "Zaokrągl. (legacy)", tab="Segments", min_val=0.0, max_val=40.0, step=0.5),
        FieldSchema("grow_height", "bool", "Rosnąca wys.", tab="Segments"),
        FieldSchema("grow_start", "float", "Start wzrostu", tab="Segments", min_val=0.0, max_val=1.0, step=0.05),
        FieldSchema("segment_fill_mode", "choice", "Tryb wypełnienia", tab="Segments", choices=[("whole", "Cały"), ("partial", "Częściowy")]),
        FieldSchema("fill_direction", "choice", "Kierunek", tab="Segments", choices=[("forward", "Lewo → prawo"), ("reverse", "Prawo → lewo")]),
        FieldSchema("min_val", "float", "Minimum", tab="Segments", min_val=-10000.0, max_val=10000.0, step=1.0),
        FieldSchema("max_val", "float", "Maksimum", tab="Segments", min_val=-10000.0, max_val=100000.0, step=1.0),
        # ── Tab Colors (kolory segmentów) ────────────────────────────────
        FieldSchema("segment_color_mode", "choice", "Tryb kolorów", tab="Colors",
                    choices=[("solid", "Jednolity"), ("gradient", "Gradient"), ("threshold", "Progi")]),
        FieldSchema("segment_color", "color", "Kolor segmentu", tab="Colors"),
        FieldSchema("segment_color_start", "color", "Kolor początku grad.", tab="Colors"),
        FieldSchema("segment_color_end", "color", "Kolor końca grad.", tab="Colors"),
        FieldSchema("gradient_space", "choice", "Przestrzeń gradientu", tab="Colors", choices=[("rgb", "RGB"), ("hsv", "HSV")]),
        FieldSchema("segment_thresholds", "text", "Progi (wartość:kolor)", tab="Colors",
                    placeholder="20:#ff0000;50:#ffaa00;80:#00cc66;100:#00ff00"),
        FieldSchema("segment_inactive_color", "color", "Kolor nieaktywny", tab="Colors"),
        FieldSchema("segment_inactive_opacity", "float", "Przezroczystość nieakt.", tab="Colors", min_val=0.0, max_val=1.0, step=0.05),
        FieldSchema("inactive_color", "color", "Kolor nieakt. (legacy)", tab="Colors"),
        FieldSchema("inactive_alpha", "int", "Alfa nieakt. (legacy)", tab="Colors", min_val=0, max_val=255, step=5),
        # ── Tab Marker ───────────────────────────────────────────────────
        FieldSchema("marker_style", "choice", "Styl markera", tab="Marker",
                    choices=[("none", "Brak"), ("triangle", "Trójkąt"), ("line", "Linia"), ("circle", "Koło")]),
        FieldSchema("marker_size", "float", "Rozmiar markera", tab="Marker", min_val=1.0, max_val=40.0, step=0.5),
        FieldSchema("marker_color", "color", "Kolor markera", tab="Marker"),
        FieldSchema("marker_border_color", "color", "Kolor obrysu", tab="Marker"),
        FieldSchema("marker_border_width", "float", "Grubość obrysu", tab="Marker", min_val=0.0, max_val=8.0, step=0.5),
        FieldSchema("marker_position", "choice", "Pozycja markera", tab="Marker",
                    choices=[("top", "Góra"), ("bottom", "Dół"), ("center", "Środek")]),
        FieldSchema("marker_offset", "float", "Odstęp markera", tab="Marker", min_val=0.0, max_val=40.0, step=1.0),
        # ── Tab Range (zakres min/max) ───────────────────────────────────
        FieldSchema("show_min", "bool", "Pokaż minimum", tab="Range"),
        FieldSchema("show_max", "bool", "Pokaż maksimum", tab="Range"),
        FieldSchema("range_units", "bool", "Jednostki zakresu", tab="Range"),
        FieldSchema("range_font", "font", "Font zakresu", tab="Range"),
        FieldSchema("range_font_size", "float", "Rozmiar zakresu", tab="Range", min_val=0.3, max_val=3.0, step=0.05),
        FieldSchema("range_color", "color", "Kolor zakresu", tab="Range"),
    ]


def _bar_slope_fields() -> list[FieldSchema]:
    """Fields for the canonical slope/grade vertical ruler."""
    return [
        FieldSchema("field", "choice", "Pole", tab="", choices=["slope"]),
        FieldSchema("show_value", "bool", "Wartość", tab="Text"),
        FieldSchema("show_label", "bool", "Etykieta", tab="Text"),
        FieldSchema("show_range_labels", "bool", "Zakres", tab="Text"),
        FieldSchema("show_units", "bool", "Jednostki", tab="Text"),
        FieldSchema("decimals", "int", "Decimals", tab="Text", min_val=0, max_val=3, step=1),
        FieldSchema("text_color", "color", "Kolor tekstu", tab="Text"),
        FieldSchema("range_color", "color", "Kolor zakresu", tab="Text"),
        FieldSchema("opacity", "float", "Opacity", tab="Text", min_val=0.0, max_val=1.0, step=0.05),
        FieldSchema("min_val", "float", "Minimum", tab="Gauge", min_val=-10000.0, max_val=10000.0, step=1.0),
        FieldSchema("max_val", "float", "Maksimum", tab="Gauge", min_val=-10000.0, max_val=10000.0, step=1.0),
        FieldSchema("major_tick", "float", "Major tick", tab="Ticks", min_val=0.1, max_val=100.0, step=0.5),
        FieldSchema("minor_tick", "float", "Minor tick", tab="Ticks", min_val=0.1, max_val=100.0, step=0.5),
        FieldSchema("track_color", "color", "Kolor osi", tab="Ticks"),
        FieldSchema("tick_color", "color", "Kolor kresek", tab="Ticks"),
        FieldSchema("zero_tick_color", "color", "Kolor zera", tab="Ticks"),
        FieldSchema("marker_color", "color", "Kolor markera", tab="Ticks"),
        FieldSchema("marker_border_color", "color", "Obramowanie markera", tab="Ticks"),
        FieldSchema("marker_size", "float", "Rozmiar markera", tab="Ticks", min_val=1.0, max_val=30.0, step=0.5),
        FieldSchema("tick_profile", "choice", "Profil ticków", tab="Ticks", choices=["default", "pixel"]),
    ]


def bar_indicator_fields(bar_style: str = "ruler") -> list[FieldSchema]:
    """Bar: Header (w tym Styl: Ruler/Segments) + zakładki specyficzne dla stylu."""
    style = str(bar_style).strip().lower()
    style_choice = [
        FieldSchema("bar_style", "choice", "Styl", tab="", choices=[("ruler", "Ruler"), ("segments", "Segments"), ("slope", "Slope")]),
    ]
    header = _header_fields() + _form_field() + style_choice
    if style in ("segment", "segments", "segmented", "segment_bar"):
        return header + _bar_segments_fields()
    if style in ("slope", "grade", "vertical_slope"):
        return header + _bar_slope_fields()
    return header + _bar_ruler_fields()


def chart_indicator_fields(chart_time_scope: str = "activity") -> list[FieldSchema]:
    """Chart: Header, Text, Labels, Ticks (bez Tick), Chart (własna zakładka)."""
    return (
        _header_fields() + _form_field()
        + _text_tab_fields(with_color=True)
        + _labels_tab_fields()
        + _ticks_tab_fields(with_ticks=False)
        + _chart_tab_fields(chart_time_scope=chart_time_scope)
    )


def segment_bar_indicator_fields() -> list[FieldSchema]:
    """SegmentBar (legacy): przekierowanie do bar z bar_style='segments'."""
    return bar_indicator_fields(bar_style="segments")


def _map_labels_tab_fields() -> list[FieldSchema]:
    return [
        FieldSchema("show_label", "bool", "Tytuł (Title)", tab="Labels"),
        FieldSchema("label_font_size", "float", "Rozmiar (Size)", tab="Labels",
                    min_val=1.0, max_val=20.0, step=0.1),
        FieldSchema("text_distance", "float", "Dystans (Distance)", tab="Labels",
                    min_val=-5.0, max_val=5.0, step=0.1),
    ]


def _map_gauge_tab_fields() -> list[FieldSchema]:
    return [
        FieldSchema("hide_marker", "bool", "Ukryj znacznik", tab="Gauge"),
        FieldSchema("arrow_marker", "bool", "Strzałka zamiast kropki", tab="Gauge"),
        FieldSchema("marker_size", "int", "Rozmiar (Size)", tab="Gauge",
                    min_val=1, max_val=20, step=1),
        FieldSchema("marker_color", "color", "Kolor", tab="Gauge"),
    ]


def _map_path_tab_fields() -> list[FieldSchema]:
    return [
        FieldSchema("hide_track", "bool", "Ukryj (Hide)", tab="Path"),
        FieldSchema("track_width", "int", "Grubość (Width)", tab="Path",
                    min_val=1, max_val=20, step=1),
        FieldSchema("track_color", "color", "Kolor", tab="Path"),
        # ETAP 10T: track antialiasing + outline
        FieldSchema("track_antialiasing", "choice", "Wygładzanie trasy", tab="Path",
                    choices=[("1", "Wyłączone"), ("2", "2x"), ("4", "4x")]),
        FieldSchema("track_outline_width", "int", "Grubość obrysu trasy", tab="Path",
                    min_val=0, max_val=12, step=1),
        FieldSchema("track_outline_color", "color", "Kolor obrysu trasy", tab="Path"),
    ]


def _map_shape_tab_fields() -> list[FieldSchema]:
    return [
        FieldSchema("map_orientation", "choice", "Orientacja mapy", tab="Shape",
                    choices=["north_up", "track_up"]),
        FieldSchema("map_style", "choice", "Mapa (Map)", tab="Shape",
                    choices=["light_all", "light_nolabels", "dark_all",
                             "dark_nolabels", "voyager_all", "voyager_nolabels", "satellite"]),
        FieldSchema("map_shape", "choice", "Kształt (Shape)", tab="Shape",
                    choices=["square", "round"]),
        FieldSchema("language", "choice", "Język (Language)", tab="Shape",
                    choices=["English", "Polski"]),
        FieldSchema("light_mode", "choice", "Światło (Light)", tab="Shape",
                    choices=["Day", "Night"]),
        FieldSchema("opacity", "float", "Przezroczystość", tab="Shape",
                    min_val=0.0, max_val=10.0, step=0.1),
        FieldSchema("zoom", "int", "Zoom", tab="Shape",
                    min_val=1, max_val=24, step=1),
        FieldSchema("pitch", "float", "Pochylenie (Pitch)", tab="Shape",
                    min_val=0.0, max_val=60.0, step=1.0),
        FieldSchema("orient", "float", "Orientacja", tab="Shape",
                    min_val=0.0, max_val=10.0, step=0.1),
        FieldSchema("magnify", "float", "Powiększenie", tab="Shape",
                    min_val=0.5, max_val=3.0, step=0.1),
        FieldSchema("terrain", "float", "Teren (Terrain)", tab="Shape",
                    min_val=0.0, max_val=5.0, step=0.1),
        FieldSchema("highlights", "bool", "Podświetlenia", tab="Shape"),
        FieldSchema("rotate", "float", "Obrót (Rotate)", tab="Shape",
                    min_val=-180.0, max_val=180.0, step=1.0),
    ]


def map_indicator_fields() -> list[FieldSchema]:
    """Map: Header, Text, mapa."""
    return (
        _header_fields()
        + [FieldSchema("form", "choice", "Typ mapy", tab="",
                       choices=["map", "static_map"])]
        + _text_tab_fields(with_color=False)
        + _map_labels_tab_fields()
        + _map_gauge_tab_fields()
        + _map_path_tab_fields()
        + _map_shape_tab_fields()
    )


def time_display_indicator_fields() -> list[FieldSchema]:
    """TimeDisplay: Header + 4 per-line tabs."""
    header = [
        FieldSchema("size", "float", "Rozmiar", tab="",
                    min_val=0.1, max_val=100.0, step=0.1),
        FieldSchema("label", "text", "Etykieta", tab=""),
        FieldSchema("x", "float", "Pozycja X", tab="",
                    min_val=0.0, max_val=100.0, step=0.1),
        FieldSchema("y", "float", "Pozycja Y", tab="",
                    min_val=0.0, max_val=100.0, step=0.1),
        FieldSchema("rotation", "choice", "Rotacja", tab="",
                    choices=["0", "90", "180", "270"]),
        FieldSchema("font", "font", "Font", tab=""),
    ]
    date_tab = [
        FieldSchema("show_date", "bool", "Pokaż datę", tab="Data"),
        FieldSchema("show_date_label", "bool", "Pokaż etykietę", tab="Data"),
        FieldSchema("date_label", "text", "Etykieta", tab="Data"),
        FieldSchema("date_font_size", "float", "Rozmiar czcionki",
                    tab="Data", min_val=0.8, max_val=8.0, step=0.1),
        FieldSchema("date_color", "color", "Kolor", tab="Data"),
    ]
    time_tab = [
        FieldSchema("show_time", "bool", "Pokaż czas GPMF", tab="Czas"),
        FieldSchema("show_time_label", "bool", "Pokaż etykietę", tab="Czas"),
        FieldSchema("time_label", "text", "Etykieta", tab="Czas"),
        FieldSchema("time_font_size", "float", "Rozmiar czcionki",
                    tab="Czas", min_val=0.8, max_val=8.0, step=0.1),
        FieldSchema("time_color", "color", "Kolor", tab="Czas"),
    ]
    elapsed_tab = [
        FieldSchema("show_elapsed", "bool", "Pokaż czas od startu", tab="Od początku"),
        FieldSchema("show_elapsed_label", "bool", "Pokaż etykietę", tab="Od początku"),
        FieldSchema("elapsed_label", "text", "Etykieta", tab="Od początku"),
        FieldSchema("elapsed_font_size", "float", "Rozmiar czcionki",
                    tab="Od początku", min_val=0.8, max_val=8.0, step=0.1),
        FieldSchema("elapsed_color", "color", "Kolor", tab="Od początku"),
    ]
    avg_speed_tab = [
        FieldSchema("show_avg_speed", "bool", "Pokaż śr. prędkość", tab="Śr. prędkość"),
        FieldSchema("show_avg_speed_label", "bool", "Pokaż etykietę", tab="Śr. prędkość"),
        FieldSchema("avg_speed_label", "text", "Etykieta", tab="Śr. prędkość"),
        FieldSchema("avg_speed_font_size", "float", "Rozmiar czcionki",
                    tab="Śr. prędkość", min_val=0.8, max_val=8.0, step=0.1),
        FieldSchema("avg_speed_color", "color", "Kolor", tab="Śr. prędkość"),
    ]
    return header + date_tab + time_tab + elapsed_tab + avg_speed_tab


# Mapa: forma → funkcja generująca schemat
FORM_SCHEMA_MAP: dict[str, callable] = {
    "text":        text_indicator_fields,
    "gauge":       gauge_indicator_fields,
    "compass":      compass_indicator_fields,
    "bar":         bar_indicator_fields,
    "chart":       chart_indicator_fields,
    "segment_bar": segment_bar_indicator_fields,
    "map":         map_indicator_fields,
    "static_map":  map_indicator_fields,
    "time_display": time_display_indicator_fields,
}


def get_schema_for_form(
    form: str, bar_style: str = "ruler", chart_time_scope: str = "activity",
) -> list[FieldSchema]:
    """Zwraca schemat pól dla podanej formy wskaźnika."""
    if form == "bar":
        return bar_indicator_fields(bar_style=bar_style)
    if form == "segment_bar":
        return bar_indicator_fields(bar_style="segments")
    if form == "chart":
        return chart_indicator_fields(chart_time_scope=chart_time_scope)
    fn = FORM_SCHEMA_MAP.get(form, text_indicator_fields)
    return fn()


def _sync_size_font_fields(cfg: dict, field_name: str) -> None:
    """Synchronizuje size/font_size tylko dla formy "text".

    Dla formy "text" ``font_size`` jest kanonicznym źródłem geometrii.
    Legacy ``size`` jest aktualizowane wyłącznie jako kompatybilna kopia po
    edycji kanonicznego pola; stare eventy ``size`` nie mogą nadpisywać fontu.
    Dla gauge/chart/bar/segment_bar/map pole ``size`` ustawia wymiary wskaźnika,
    a ``font_size`` rozmiar czcionki etykiety — muszą pozostać niezależne, inaczej
    "Size" z zakładki Text zmieniałby rozmiar całego wskaźnika.
    """
    if cfg.get("form", "text") != "text":
        return
    if field_name == "font_size":
        cfg["size"] = cfg["font_size"]
