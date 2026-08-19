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

def _header_fields(with_source: bool = True, text_size: bool = False) -> list[FieldSchema]:
    """Pola zawsze widoczne nad zakładkami (pozycja, etykieta, rotacja)."""
    fields = [
        FieldSchema(
            "font_size" if text_size else "size", "float", "Rozmiar", tab="",
            min_val=0.5 if text_size else 1.0,
            max_val=10.0 if text_size else 50.0,
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


def _chart_tab_fields() -> list[FieldSchema]:
    """Zakładka Chart – wygląd wykresu."""
    return [
        FieldSchema(
            "chart_time_scope", "choice", "Zakres czasu wykresu", tab="Chart",
            choices=[("activity", "Cała aktywność"), ("video", "Zakres filmu")],
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
                        min_val=-20.0, max_val=20.0, step=0.1),
            FieldSchema("range_label_offset_y", "float", "Offset Y", tab="Text",
                        min_val=-20.0, max_val=20.0, step=0.1),
            FieldSchema("bar_direction", "choice", "Kierunek", tab="Gauge",
                        choices=["horizontal", "vertical"]),
            FieldSchema("dot_color", "color", "Kolor kropki", tab="Gauge"),
        ]
    )


def chart_indicator_fields() -> list[FieldSchema]:
    """Chart: Header, Text, Labels, Ticks (bez Tick), Chart (własna zakładka)."""
    return (
        _header_fields() + _form_field()
        + _text_tab_fields(with_color=True)
        + _labels_tab_fields()
        + _ticks_tab_fields(with_ticks=False)
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
    ]


def _map_shape_tab_fields() -> list[FieldSchema]:
    return [
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
    "bar":         bar_indicator_fields,
    "chart":       chart_indicator_fields,
    "segment_bar": segment_bar_indicator_fields,
    "map":         map_indicator_fields,
    "static_map":  map_indicator_fields,
    "time_display": time_display_indicator_fields,
}


def get_schema_for_form(form: str) -> list[FieldSchema]:
    """Zwraca schemat pól dla podanej formy wskaźnika."""
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
