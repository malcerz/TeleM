"""Modele danych — struktury przekazywane między GUI a kontrolerem.

GUI operuje tylko na tych strukturach, nie zna szczegółów GPMF/GPX/FIT.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any

from src.indicators.icons import ICON_NAMES, ICON_LABELS

_ICON_CHOICES = [(name, f"{ICON_LABELS.get(name, name)} ({name})" if name != "none" else "Brak") for name in ICON_NAMES]


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
    """Schema pojedynczego pola właściwości wskaźnika.

    ``default`` jest KANONICZNĄ wartością pola (jedno źródło prawdy):
    - używane przez ``canonical_defaults()`` do uzupełniania konfiguracji
      nowo tworzonego wskaźnika (``_create_indicator``),
    - używane przez Property Editor, gdy pola brakuje w konfiguracji
      (stare/niepełne projekty) — zamiast domyślnych wartości widgetów
      (0 / False / "" / pierwsza pozycja combo).
    Musi odpowiadać fallbackowi używanemu przez renderer (``cfg.get(...)``),
    aby model == Properties == Preview == Rendering.
    """

    name: str           # nazwa pola (np. "font_size", "color", "min_val")
    field_type: str     # typ: "bool", "int", "float", "choice", "text", "color", "font"
    label: str          # etykieta wyświetlana

    # Zakładka w panelu właściwości ("" = header nad zakładkami):
    tab: str = "Text"

    # Kanoniczna (domyślna) wartość pola:
    default: Any = None

    # Dla typów numerycznych:
    min_val: float | None = None
    max_val: float | None = None
    step: float | None = None

    # Dla typu choice:
    choices: list[str] | None = None

    # Placeholder / podpowiedź dla pól tekstowych (np. format progów):
    placeholder: str | None = None


def canonical_defaults(schema: list[FieldSchema]) -> dict[str, Any]:
    """Zwraca mapę {nazwa pola: kanoniczna wartość} dla pól z ustawionym default.

    JEDNO źródło kanonicznych wartości konfiguracji wskaźnika — używane
    zarówno przy tworzeniu nowego wskaźnika, jak i jako fallback Property
    Editor dla niepełnych (starych) konfiguracji.
    """
    return {
        field.name: field.default
        for field in schema
        if field.default is not None
    }


# Indicator-specific defaults that are part of the generic numeric property
# contract.  These are presentation defaults only; resolver semantics and
# source values remain untouched.
def indicator_default_decimals(indicator_key: str, cfg: Mapping[str, Any] | None = None) -> int | None:
    """Return an explicit canonical decimal default for known indicators."""
    from src.telemetry_resolver import is_integer_only_field
    if is_integer_only_field(indicator_key, cfg):
        return 0
    key = str(indicator_key or "").strip().lower()
    if key in {"iso_text", "fit_gopro_battery_text"}:
        return 0
    if "garmin_battery" in key or key == "battery_text":
        return 2
    return None


def get_schema_for_indicator(
    indicator_key: str,
    form: str,
    *,
    bar_style: str = "ruler",
    chart_time_scope: str = "activity",
    cfg: Mapping[str, Any] | None = None,
) -> list[FieldSchema]:
    """Build a form schema with the indicator's canonical numeric defaults."""
    from src.telemetry_resolver import is_integer_only_field
    schema = get_schema_for_form(
        form, bar_style=bar_style, chart_time_scope=chart_time_scope,
    )
    if is_integer_only_field(indicator_key, cfg):
        # Fixed integer presentation: hide/omit decimals & decimal_places from GUI
        return [
            field for field in schema
            if field.name not in ("decimals", "decimal_places")
        ]
    default = indicator_default_decimals(indicator_key, cfg)
    if default is None:
        return schema
    # Do not mutate shared factory results or alter the generic form defaults.
    return [
        replace(field, default=default,
                label="Liczba miejsc po przecinku"
                if field.name in ("decimals", "decimal_places") else field.label)
        if field.name in ("decimals", "decimal_places") else field
        for field in schema
    ]


def normalize_indicator_decimal_defaults(layout: dict[str, Any]) -> dict[str, Any]:
    """Fill missing canonical decimal defaults and clamp precision to 0-2 in layout."""
    from src.telemetry_resolver import is_integer_only_field
    indicators = layout.get("indicators", {}) if isinstance(layout, dict) else {}
    if isinstance(indicators, dict):
        for key, cfg in indicators.items():
            if not isinstance(cfg, dict):
                continue
            if is_integer_only_field(key, cfg):
                # Integer-only fields do not retain redundant decimals in new saved layouts
                cfg.pop("decimals", None)
                cfg.pop("decimal_places", None)
                continue
            if "decimals" in cfg and cfg["decimals"] is not None:
                try:
                    cfg["decimals"] = max(0, min(2, int(cfg["decimals"])))
                except (TypeError, ValueError, OverflowError):
                    pass
            if "decimal_places" in cfg and cfg["decimal_places"] is not None:
                try:
                    cfg["decimal_places"] = max(0, min(2, int(cfg["decimal_places"])))
                except (TypeError, ValueError, OverflowError):
                    pass
            if "decimals" not in cfg:
                default = indicator_default_decimals(key, cfg)
                if default is not None:
                    cfg["decimals"] = default
    return layout


# ── Fabryki pól per-zakładka ────────────────────────────────────────────────

def _header_fields(with_source: bool = True, text_size: bool = False,
                   allow_small_size: bool = False, with_icon: bool = True,
                   with_label: bool = True, with_unit: bool = True,
                   with_font: bool = True) -> list[FieldSchema]:
    """Pola zawsze widoczne nad zakładkami (pozycja, etykieta, rotacja)."""
    fields = [
        FieldSchema(
            "font_size" if text_size else "size", "float", "Rozmiar", tab="",
            min_val=0.5 if (text_size or allow_small_size) else 1.0,
            max_val=10.0 if text_size else 100.0,
            step=0.1,
            default=2.5,
        ),
    ]
    if with_label:
        fields.append(FieldSchema("label", "text", "Etykieta", tab="", default=""))
    if with_unit:
        fields.append(FieldSchema("unit", "text", "Jednostka", tab="", default=""))
    fields.extend([
        FieldSchema("x", "float", "Pozycja X", tab="",
                    min_val=0.0, max_val=100.0, step=0.1, default=50.0),
        FieldSchema("y", "float", "Pozycja Y", tab="",
                    min_val=0.0, max_val=100.0, step=0.1, default=50.0),
        FieldSchema("rotation", "choice", "Rotacja", tab="",
                    choices=["0", "90", "180", "270"], default="0"),
    ])
    if with_font:
        fields.append(FieldSchema("font", "font", "Font", tab="", default=""))
    if with_icon:
        fields.append(FieldSchema("icon", "choice", "Ikona", tab="Ikona", choices=_ICON_CHOICES, default="none"))
    if with_source:
        fields.append(
            FieldSchema("source", "choice", "Źródło", tab="",
                        choices=["gpmf", "gpx", "fit"], default="gpmf"),
        )
    return fields


def _form_field(choices: list[str] | None = None) -> list[FieldSchema]:
    """Pole wyboru formy – zawsze widoczne."""
    if choices is None:
        choices = ["text", "gauge", "bar", "chart", "segment_bar", "map",
                   ("lean", "Przechył")]
    return [
        FieldSchema("form", "choice", "Forma", tab="", choices=choices, default="text"),
    ]


def _text_tab_fields(
    font_range=(0.5, 10.0), repo_range=(-0.5, 0.5),
    with_color: bool = True, with_distance: bool = False,
    include_font_size: bool = True,
    with_decimals: bool = True,
) -> list[FieldSchema]:
    """Zakładka Text – wygląd tekstu wartości i jego pozycja."""
    fields: list[FieldSchema] = []
    if include_font_size:
        fields.append(FieldSchema("font_size", "float", "Size",
                                   tab="Text",
                                   min_val=font_range[0], max_val=font_range[1], step=0.1,
                                   default=2.5))
    if with_decimals:
        fields.append(FieldSchema("decimals", "int", "Decimals",
                                  tab="Text", min_val=0, max_val=2, step=1, default=1))
    fields += [
        FieldSchema("show_value", "bool", "Value", tab="Text", default=True),
        FieldSchema("show_units", "bool", "Units", tab="Text", default=True),
    ]
    if with_distance:
        fields.append(
            FieldSchema("text_distance", "float", "Distance",
                        tab="Text", min_val=-200.0, max_val=200.0, step=1.0,
                        default=0.0))
    if with_color:
        fields.append(
            FieldSchema("text_color", "color", "Color", tab="Text", default="#FFFFFF"))
    fields += [
        FieldSchema("text_offset_x", "float", "Pos X",
                    tab="Text",
                    min_val=repo_range[0], max_val=repo_range[1], step=0.01,
                    default=0.0),
        FieldSchema("text_offset_y", "float", "Pos Y",
                    tab="Text",
                    min_val=repo_range[0], max_val=repo_range[1], step=0.01,
                    default=0.0),
    ]
    return fields


def _labels_tab_fields() -> list[FieldSchema]:
    """Zakładka Labels – etykiety na osi."""
    return [
        FieldSchema("show_x_axis_values", "bool", "Wartości osi poziomej", tab="Labels", default=True),
        FieldSchema("show_y_axis_values", "bool", "Wartości osi pionowej", tab="Labels", default=True),
        FieldSchema("label_count", "int", "Number",
                    tab="Labels", min_val=2, max_val=21, step=1, default=2),
        # 0 = wyłączone (renderer traktuje brak/0 jako „brak etykiet wartości")
        FieldSchema("label_font_size", "float", "Size",
                    tab="Labels", min_val=0.0, max_val=10.0, step=0.1, default=0.0),
        FieldSchema("label_units", "bool", "Units", tab="Labels", default=False),
        FieldSchema("show_average", "bool", "Average", tab="Labels", default=False),
    ]


def _ticks_tab_fields(
    with_range: bool = True,
    with_ticks: bool = True,
    with_step: bool = True,
    with_tick_geometry: bool = True,
) -> list[FieldSchema]:
    """Zakładka Ticks – podziałki i zakres wartości."""
    fields: list[FieldSchema] = []
    if with_ticks:
        fields.append(FieldSchema("ticks", "int", "Liczba podziałek",
                                  tab="Ticks", min_val=0, max_val=20, step=1, default=0))
    # major_step=0 -> renderer przechodzi na major_ticks (fallback 0 = wyłączone)
    if with_step:
        fields.append(FieldSchema("major_step", "float", "Krok główny", tab="Ticks",
                                  min_val=0.0, max_val=1000.0, step=0.1, default=0.0))
    if with_tick_geometry:
        fields.append(FieldSchema("major_tick_length", "float", "Dł. podziałki głównej",
                                  tab="Ticks", min_val=0.5, max_val=20.0, step=0.5, default=4.0))
        fields.append(FieldSchema("minor_tick_length", "float", "Dł. podziałki drobnej",
                                  tab="Ticks", min_val=0.5, max_val=20.0, step=0.5, default=2.0))
        fields.append(FieldSchema("major_tick_thickness", "int", "Grubość podz. głównej",
                                  tab="Ticks", min_val=1, max_val=20, step=1, default=4))
        fields.append(FieldSchema("minor_tick_thickness", "int", "Grubość podz. drobnej",
                                  tab="Ticks", min_val=1, max_val=20, step=1, default=2))
    if with_range:
        fields += [
            FieldSchema("auto_scale", "bool", "Auto skala (zakres z danych)", tab="Ticks", default=False),
            FieldSchema("min_val", "float", "Minimum", tab="Ticks",
                        min_val=-1000, max_val=1000, step=1, default=0.0),
            FieldSchema("max_val", "float", "Maksimum", tab="Ticks",
                        min_val=-1000, max_val=10000, step=1, default=100.0),
        ]
    return fields


def _gauge_tab_fields() -> list[FieldSchema]:
    """Zakładka Gauge – kropka kursora, kąt, pionowy bar."""
    return [
        FieldSchema("show_marker", "bool", "Kropka środka", tab="Gauge", default=False),
        FieldSchema("marker_size", "int", "Rozmiar kropki",
                    tab="Gauge", min_val=0, max_val=30, step=1, default=0),
        FieldSchema("marker_color", "color", "Kolor kropki", tab="Gauge", default="#333333"),
        FieldSchema("start_angle", "int", "Kąt startu",
                    tab="Gauge", min_val=0, max_val=360, step=5, default=180),
        FieldSchema("sweep_angle", "int", "Rozpiętość",
                    tab="Gauge", min_val=30, max_val=360, step=5, default=180),
        FieldSchema("needle_length", "float", "Dł. wskazówki",
                    tab="Gauge", min_val=0.1, max_val=2.0, step=0.05, default=1.1),
        FieldSchema("needle_width", "int", "Grubość wskazówki",
                    tab="Gauge", min_val=2, max_val=20, step=1, default=4),
        FieldSchema("needle_color", "color", "Kolor wskazówki", tab="Gauge", default="#DC3232"),
        FieldSchema("opacity", "float", "Przezroczystość", tab="Gauge",
                    min_val=0.0, max_val=1.0, step=0.05, default=1.0),
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
            default="activity",
        ),
        FieldSchema("chart_color", "color", "Linia", tab="Chart", default="#00AAFF"),
        FieldSchema("fill_color", "color", "Wypełnienie", tab="Chart", default="#00AAFF"),
        FieldSchema("fill_alpha", "int", "Alfa", tab="Chart",
                    min_val=0, max_val=255, step=5, default=80),
        FieldSchema("grid_color", "color", "Siatka", tab="Chart", default="#444444"),
        FieldSchema("show_grid", "bool", "Pokaż siatkę", tab="Chart", default=True),
        FieldSchema("line_width", "int", "Grubość linii", tab="Chart",
                    min_val=1, max_val=8, step=1, default=2),
    ]
    if chart_time_scope == "window":
        fields.insert(
            1,
            FieldSchema(
                "chart_window_s", "float", "Okno historii [s]", tab="Chart",
                min_val=5.0, max_val=600.0, step=1.0, default=60.0,
            ),
        )
    return fields


def _segments_tab_fields() -> list[FieldSchema]:
    """Zakładka Segments – specyficzne dla segment_bar (legacy)."""
    return [
        FieldSchema("segments", "int", "Segmenty", tab="Segments",
                    min_val=2, max_val=50, step=1, default=20),
        FieldSchema("segment_gap", "int", "Odstęp", tab="Segments",
                    min_val=0, max_val=20, step=1, default=3),
        FieldSchema("segment_radius", "int", "Zaokrągl.", tab="Segments",
                    min_val=0, max_val=20, step=1, default=1),
        FieldSchema("inactive_alpha", "int", "Alfa nieakt.", tab="Segments",
                    min_val=0, max_val=255, step=5, default=60),
        FieldSchema("inactive_color", "color", "Kolor nieakt.", tab="Segments", default="#3E3E3E"),
        FieldSchema("direction", "choice", "Kierunek", tab="Segments",
                    choices=["horizontal", "vertical"], default="horizontal"),
        FieldSchema("grow_height", "bool", "Rosnąca wys.", tab="Segments", default=True),
        FieldSchema("min_val", "float", "Minimum", tab="Segments",
                    min_val=0, max_val=1000, step=1, default=0.0),
        FieldSchema("max_val", "float", "Maksimum", tab="Segments",
                    min_val=1, max_val=10000, step=1, default=100.0),
        FieldSchema("show_min", "bool", "Pokaż min.", tab="Segments", default=True),
        FieldSchema("show_max", "bool", "Pokaż max", tab="Segments", default=True),
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
    """Gauge: Header (bez label, gauge nie wyświetla etykiety), Text, Ticks, Gauge."""
    return (
        _header_fields(with_icon=False, with_label=False) + _form_field()
        + _text_tab_fields()
        + [FieldSchema("tick_profile", "choice", "Profil ticków", tab="Ticks",
                       choices=["default", "pixel"], default="default")]
        + _ticks_tab_fields(with_step=False)
        + _gauge_tab_fields()
    )


def compass_indicator_fields() -> list[FieldSchema]:
    """Compass: gauge layout controls plus compass-only styling fields."""
    return (
        _header_fields(with_icon=False, with_label=False, with_unit=False) + _form_field(["gauge"])
        + [
            FieldSchema("font_size", "float", "Rozmiar tekstu", tab="Compass", min_val=0.5, max_val=10.0, step=0.1, default=2.5),
            FieldSchema("tick_profile", "choice", "Profil ticków", tab="Compass",
                        choices=["default", "pixel"], default="default"),
            FieldSchema("opacity", "float", "Przezroczystość", tab="Compass",
                        min_val=0.0, max_val=1.0, step=0.05, default=1.0),
            FieldSchema("compass_show_cardinals", "bool", "N/E/S/W", tab="Compass", default=True),
            FieldSchema("compass_show_heading", "bool", "Wartość heading", tab="Compass", default=True),
            FieldSchema("compass_heading_format", "choice", "Format heading", tab="Compass",
                        choices=["03d", "d"], default="03d"),
            FieldSchema("compass_tick_degrees", "int", "Subtick co", tab="Compass",
                        min_val=5, max_val=90, step=5, default=15),
            FieldSchema("compass_major_tick_degrees", "int", "Główny tick co", tab="Compass",
                        min_val=15, max_val=90, step=15, default=45),
            FieldSchema("compass_tick_color", "color", "Kolor ticków", tab="Compass", default="#DDE7F2"),
            FieldSchema("compass_cardinal_color", "color", "Kolor N/E/S/W", tab="Compass", default="#FFFFFF"),
            FieldSchema("compass_needle_color", "color", "Kolor wskazówki", tab="Compass", default="#FFD42A"),
            FieldSchema("compass_ring_color", "color", "Kolor tarczy", tab="Compass", default="#B8C7D9"),
            FieldSchema("compass_heading_color", "color", "Kolor wartości", tab="Compass", default="#FFFFFF"),
            FieldSchema("compass_marker_size", "float", "Rozmiar markera", tab="Compass", min_val=1.0, max_val=20.0, step=0.5, default=4.0),
            FieldSchema("compass_needle_length", "float", "Dł. wskazówki", tab="Compass", min_val=0.2, max_val=2.0, step=0.05, default=0.9),
            FieldSchema("compass_needle_width", "int", "Grubość wskazówki", tab="Compass", min_val=1, max_val=15, step=1, default=3),
            FieldSchema("compass_ring_width", "int", "Grubość pierścienia", tab="Compass", min_val=1, max_val=15, step=1, default=2),
            FieldSchema("compass_tick_width", "int", "Grubość ticków", tab="Compass", min_val=1, max_val=10, step=1, default=1),
        ]
    )


def _bar_ruler_fields() -> list[FieldSchema]:
    """Pola specyficzne dla stylu 'ruler'."""
    return [
        # Tab Text
        FieldSchema("show_value", "bool", "Wartość", tab="Text", default=True),
        FieldSchema("show_label", "bool", "Etykieta", tab="Text", default=True),
        FieldSchema("label_position", "choice", "Pozycja etykiety", tab="Text",
                    choices=[("auto", "Auto"), ("top", "Góra"), ("bottom", "Dół"),
                             ("left", "Lewo"), ("right", "Prawo"), ("inside", "Wewnątrz")],
                    default="auto"),
        FieldSchema("label_offset_x", "float", "Przesunięcie etykiety X", tab="Text",
                    min_val=-500.0, max_val=500.0, step=1.0, default=0.0),
        FieldSchema("label_offset_y", "float", "Przesunięcie etykiety Y", tab="Text",
                    min_val=-500.0, max_val=500.0, step=1.0, default=0.0),
        FieldSchema("uppercase_title", "bool", "Tytuł WIELKIMI", tab="Text", default=True),
        FieldSchema("show_range_labels", "bool", "Zakres", tab="Text", default=True),
        FieldSchema("show_mid_label", "bool", "Środek", tab="Text", default=True),
        FieldSchema("range_units", "bool", "Jednostki", tab="Text", default=True),
        FieldSchema("title_with_unit", "bool", "Tytuł z jednostką", tab="Text", default=True),
        FieldSchema("decimals", "int", "Miejsca dzies.", tab="Text", min_val=0, max_val=2, step=1, default=1),
        FieldSchema("text_color", "color", "Kolor tekstu", tab="Text", default="#F4F4F4"),
        FieldSchema("range_color", "color", "Kolor zakresu", tab="Text", default="#E0E0E0"),
        FieldSchema("text_offset_x", "float", "Pos X", tab="Text", min_val=-0.5, max_val=0.5, step=0.01, default=0.0),
        FieldSchema("text_offset_y", "float", "Pos Y", tab="Text", min_val=-0.5, max_val=0.5, step=0.01, default=0.0),
        # Tab Ticks — wspólny kontrakt: Auto / Count / Step (ETAP 11B)
        FieldSchema("major_tick_mode", "choice", "Tryb podziałki gł.", tab="Ticks",
                    choices=[("auto", "Auto"), ("count", "Liczba (Count)"), ("step", "Krok (Step)")],
                    default="count"),
        FieldSchema("major_ticks", "int", "Podziałki gł.", tab="Ticks", min_val=1, max_val=30, step=1, default=8),
        FieldSchema("major_step", "float", "Krok główny (Step)", tab="Ticks", min_val=0.0, max_val=1000.0, step=0.1, default=0.0),
        FieldSchema("minor_ticks", "int", "Podziałki drobne", tab="Ticks", min_val=1, max_val=10, step=1, default=5),
        FieldSchema("track_color", "color", "Kolor osi", tab="Ticks", default="#F4F4F4"),
        FieldSchema("track_alpha", "int", "Alfa osi", tab="Ticks", min_val=0, max_val=255, step=5, default=235),
        FieldSchema("tick_color", "color", "Kolor kresek", tab="Ticks", default="#F6F6F6"),
        FieldSchema("tick_alpha", "int", "Alfa kresek", tab="Ticks", min_val=0, max_val=255, step=5, default=240),
        FieldSchema("tick_width", "float", "Szerokość kresek", tab="Ticks", min_val=0.5, max_val=10.0, step=0.5, default=1.4),
        FieldSchema("major_tick_length", "float", "Dł. podziałki głównej", tab="Ticks", min_val=4.0, max_val=40.0, step=1.0, default=17.0),
        FieldSchema("minor_tick_length", "float", "Dł. podziałki drobnej", tab="Ticks", min_val=2.0, max_val=30.0, step=1.0, default=10.0),
        FieldSchema("marker_color", "color", "Kolor wskaźnika", tab="Ticks", default="#159FA5"),
        FieldSchema("marker_border_color", "color", "Obramowanie wsk.", tab="Ticks", default="#D8D8D8"),
        FieldSchema("marker_border_width", "float", "Grubość obram. wsk.", tab="Ticks", min_val=0.5, max_val=8.0, step=0.5, default=1.5),
        FieldSchema("marker_size", "float", "Rozmiar wskaźnika", tab="Ticks", min_val=2.0, max_val=30.0, step=0.5, default=7.0),
        FieldSchema("tick_profile", "choice", "Profil ticków", tab="Ticks", choices=["default", "pixel"], default="default"),
        # Tab Gauge (Orientacja / Zakres / Grubość)
        FieldSchema("orientation", "choice", "Orientacja", tab="Gauge",
                    choices=[("horizontal", "Pozioma"), ("vertical", "Pionowa")], default="horizontal"),
        FieldSchema("auto_scale", "bool", "Auto skala (zakres z danych)", tab="Gauge", default=False),
        FieldSchema("min_val", "float", "Minimum", tab="Gauge", min_val=-10000.0, max_val=10000.0, step=1.0, default=0.0),
        FieldSchema("max_val", "float", "Maksimum", tab="Gauge", min_val=-10000.0, max_val=100000.0, step=1.0, default=100.0),
        FieldSchema("thickness", "float", "Grubość", tab="Gauge", min_val=0.25, max_val=10.0, step=0.25, default=3.0),
    ]


def _bar_segments_fields() -> list[FieldSchema]:
    """Pola specyficzne dla stylu 'segments' (Segment Bar, ETAP 10T)."""
    return [
        # ── Tab Text (wartość / etykieta / zakres) ──────────────────────
        FieldSchema("show_value", "bool", "Wartość", tab="Text", default=True),
        FieldSchema("show_label", "bool", "Etykieta", tab="Text", default=True),
        FieldSchema("label_position", "choice", "Pozycja etykiety", tab="Text",
                    choices=[("auto", "Auto"), ("top", "Góra"), ("bottom", "Dół"),
                             ("left", "Lewo"), ("right", "Prawo"), ("inside", "Wewnątrz")],
                    default="auto"),
        FieldSchema("label_offset_x", "float", "Przesunięcie etykiety X", tab="Text",
                    min_val=-500.0, max_val=500.0, step=1.0, default=0.0),
        FieldSchema("label_offset_y", "float", "Przesunięcie etykiety Y", tab="Text",
                    min_val=-500.0, max_val=500.0, step=1.0, default=0.0),
        FieldSchema("uppercase_label", "bool", "Etykieta WIELKIMI", tab="Text", default=False),
        FieldSchema("value_show_unit", "bool", "Jednostka przy wartości", tab="Text", default=True),
        FieldSchema("value_unit", "text", "Własna jednostka", tab="Text", default=""),
        FieldSchema("show_min", "bool", "Pokaż min.", tab="Text", default=True),
        FieldSchema("show_max", "bool", "Pokaż max", tab="Text", default=True),
        FieldSchema("show_marker", "bool", "Pokaż marker", tab="Text", default=True),
        FieldSchema("range_units", "bool", "Jednostki", tab="Text", default=False),
        FieldSchema("decimals", "int", "Decimals", tab="Text", min_val=0, max_val=2, step=1, default=1),
        FieldSchema("value_font", "font", "Font wartości", tab="Text", default=""),
        FieldSchema("value_font_size", "float", "Rozmiar wartości", tab="Text", min_val=0.5, max_val=5.0, step=0.05, default=1.70),
        FieldSchema("label_font", "font", "Font etykiety", tab="Text", default=""),
        FieldSchema("label_font_size", "float", "Rozmiar etykiety", tab="Text", min_val=0.3, max_val=3.0, step=0.05, default=0.72),
        FieldSchema("range_font", "font", "Font zakresu", tab="Text", default=""),
        FieldSchema("range_font_size", "float", "Rozmiar zakresu", tab="Text", min_val=0.3, max_val=3.0, step=0.05, default=0.82),
        FieldSchema("value_color", "color", "Kolor wartości", tab="Text", default="#FFFFFF"),
        FieldSchema("label_color", "color", "Kolor etykiety", tab="Text", default="#FFFFFF"),
        FieldSchema("text_color", "color", "Kolor tekstu", tab="Text", default="#FFFFFF"),
        FieldSchema("range_color", "color", "Kolor zakresu", tab="Text", default="#E0E0E0"),
        FieldSchema("value_align", "choice", "Wyrównanie wartości", tab="Text", choices=["left", "center", "right"], default="left"),
        FieldSchema("label_align", "choice", "Wyrównanie etykiety", tab="Text", choices=["left", "center", "right"], default="center"),
        FieldSchema("value_gap", "int", "Odstęp wartości", tab="Text", min_val=0, max_val=40, step=1, default=3),
        FieldSchema("label_gap", "int", "Odstęp etykiety", tab="Text", min_val=0, max_val=40, step=1, default=0),
        FieldSchema("range_gap", "int", "Odstęp zakresu", tab="Text", min_val=0, max_val=40, step=1, default=0),
        # ── Tab Segments (geometria) ─────────────────────────────────────
        FieldSchema("segments", "int", "Liczba segmentów", tab="Segments", min_val=2, max_val=100, step=1, default=20),
        FieldSchema("segment_width", "float", "Szerokość segmentu", tab="Segments", min_val=0.0, max_val=200.0, step=1.0, default=0.0),
        FieldSchema("segment_height", "float", "Wysokość segmentu", tab="Segments", min_val=0.0, max_val=200.0, step=1.0, default=0.0),
        FieldSchema("segment_height_ratio", "float", "Proporcja wys. segmentu", tab="Segments", min_val=0.1, max_val=1.0, step=0.05, default=0.7),
        FieldSchema("segment_gap", "int", "Odstęp segmentów", tab="Segments", min_val=0, max_val=20, step=1, default=3),
        FieldSchema("segment_shape", "choice", "Kształt segmentu", tab="Segments", choices=[("rectangle", "Prostokąt"), ("rounded", "Zaokrąglony"), ("pill", "Pigułka")], default="rounded"),
        # 4.0 = spójne z legacy segment_radius=4 ustawianym przez _create_indicator
        FieldSchema("segment_corner_radius", "float", "Zaokrąglenie", tab="Segments", min_val=0.0, max_val=40.0, step=0.5, default=4.0),
        FieldSchema("grow_height", "bool", "Rosnąca wys.", tab="Segments", default=True),
        FieldSchema("grow_start", "float", "Start wzrostu", tab="Segments", min_val=0.0, max_val=1.0, step=0.05, default=0.55),
        FieldSchema("segment_fill_mode", "choice", "Tryb wypełnienia", tab="Segments", choices=[("whole", "Cały"), ("partial", "Częściowy")], default="whole"),
        FieldSchema("fill_direction", "choice", "Kierunek", tab="Segments", choices=[("forward", "Lewo → prawo"), ("reverse", "Prawo → lewo")], default="forward"),
        FieldSchema("auto_scale", "bool", "Auto skala (zakres z danych)", tab="Segments", default=False),
        FieldSchema("min_val", "float", "Minimum", tab="Segments", min_val=-10000.0, max_val=10000.0, step=1.0, default=0.0),
        FieldSchema("max_val", "float", "Maksimum", tab="Segments", min_val=-10000.0, max_val=100000.0, step=1.0, default=100.0),
        # ── Tab Colors (kolory segmentów) ────────────────────────────────
        FieldSchema("segment_color_mode", "choice", "Tryb kolorów", tab="Colors",
                    choices=[("solid", "Jednolity"), ("gradient", "Gradient"), ("threshold", "Progi")], default="gradient"),
        FieldSchema("segment_color", "color", "Kolor segmentu", tab="Colors", default="#16A7AF"),
        FieldSchema("segment_color_start", "color", "Kolor początku grad.", tab="Colors", default="#16A7AF"),
        FieldSchema("segment_color_end", "color", "Kolor końca grad.", tab="Colors", default="#FF9A2E"),
        FieldSchema("gradient_space", "choice", "Przestrzeń gradientu", tab="Colors", choices=[("rgb", "RGB"), ("hsv", "HSV")], default="rgb"),
        FieldSchema("segment_thresholds", "text", "Progi (wartość:kolor)", tab="Colors",
                    placeholder="20:#ff0000;50:#ffaa00;80:#00cc66;100:#00ff00", default=""),
        FieldSchema("segment_inactive_color", "color", "Kolor nieaktywny", tab="Colors", default="#333333"),
        FieldSchema("segment_inactive_opacity", "float", "Przezroczystość nieakt.", tab="Colors", min_val=0.0, max_val=1.0, step=0.05, default=0.23529411764705882),
        # ── Tab Marker ───────────────────────────────────────────────────
        FieldSchema("marker_style", "choice", "Styl markera", tab="Marker",
                    choices=[("none", "Brak"), ("triangle", "Trójkąt"), ("line", "Linia"), ("circle", "Koło")], default="none"),
        FieldSchema("marker_size", "float", "Rozmiar markera", tab="Marker", min_val=1.0, max_val=40.0, step=0.5, default=8.0),
        FieldSchema("marker_color", "color", "Kolor markera", tab="Marker", default="#FFFFFF"),
        FieldSchema("marker_border_color", "color", "Kolor obrysu", tab="Marker", default="#000000"),
        FieldSchema("marker_border_width", "float", "Grubość obrysu", tab="Marker", min_val=0.0, max_val=8.0, step=0.5, default=1.0),
        FieldSchema("marker_position", "choice", "Pozycja markera", tab="Marker",
                    choices=[("top", "Góra"), ("bottom", "Dół"), ("center", "Środek")], default="top"),
        FieldSchema("marker_offset", "float", "Odstęp markera", tab="Marker", min_val=0.0, max_val=40.0, step=1.0, default=0.0),
    ]


def _bar_slope_fields() -> list[FieldSchema]:
    """Legacy slope/grade vertical ruler schema (ETAP 11B: kept for OLD configs).

    ``bar_style="slope"`` is no longer a selectable variant — the unified
    ``Ruler`` now exposes ``orientation`` (horizontal/vertical).  This schema is
    still used to EDIT an existing legacy ``slope`` config; it maps onto the
    ruler STEP contract at render time.
    """
    return [
        FieldSchema("field", "choice", "Pole", tab="", choices=["slope"], default="slope"),
        FieldSchema("orientation", "choice", "Orientacja", tab="",
                    choices=[("vertical", "Pionowa")], default="vertical"),
        FieldSchema("show_value", "bool", "Wartość", tab="Text", default=True),
        FieldSchema("show_label", "bool", "Etykieta", tab="Text", default=True),
        FieldSchema("show_tick_labels", "bool", "Etykiety ticków", tab="Text", default=True),
        FieldSchema("show_units", "bool", "Jednostki", tab="Text", default=True),
        FieldSchema("decimals", "int", "Miejsca dzies.", tab="Text", min_val=0, max_val=2, step=1, default=1),
        FieldSchema("text_color", "color", "Kolor tekstu", tab="Text", default="#FFFFFF"),
        FieldSchema("range_color", "color", "Kolor zakresu", tab="Text", default="#DDE7F2"),
        FieldSchema("opacity", "float", "Przezroczystość", tab="Text", min_val=0.0, max_val=1.0, step=0.05, default=1.0),
        FieldSchema("auto_scale", "bool", "Auto skala (zakres z danych)", tab="Gauge", default=False),
        FieldSchema("min_val", "float", "Minimum", tab="Gauge", min_val=-10000.0, max_val=10000.0, step=1.0, default=0.0),
        FieldSchema("max_val", "float", "Maksimum", tab="Gauge", min_val=-10000.0, max_val=10000.0, step=1.0, default=100.0),
        FieldSchema("major_tick", "float", "Krok główny (legacy)", tab="Ticks", min_val=0.1, max_val=100.0, step=0.5, default=5.0),
        FieldSchema("minor_tick", "float", "Krok drobny (legacy)", tab="Ticks", min_val=0.1, max_val=100.0, step=0.5, default=1.0),
        FieldSchema("track_color", "color", "Kolor osi", tab="Ticks", default="#8D9AA7"),
        FieldSchema("tick_color", "color", "Kolor kresek", tab="Ticks", default="#DDE7F2"),
        FieldSchema("zero_tick_color", "color", "Kolor zera", tab="Ticks", default="#FFFFFF"),
        FieldSchema("marker_color", "color", "Kolor wskaźnika", tab="Ticks", default="#FFD42A"),
        FieldSchema("marker_border_color", "color", "Obramowanie wskaźnika", tab="Ticks", default="#FFFFFF"),
        FieldSchema("marker_size", "float", "Rozmiar wskaźnika", tab="Ticks", min_val=1.0, max_val=30.0, step=0.5, default=6.0),
        FieldSchema("tick_profile", "choice", "Profil ticków", tab="Ticks", choices=["default", "pixel"], default="default"),
    ]


def bar_indicator_fields(bar_style: str = "ruler") -> list[FieldSchema]:
    """Bar: Header (w tym Styl: Ruler/Segments) + zakładki specyficzne dla stylu.

    ETAP 11B: ``slope`` nie jest już wybieranym wariantem — pionowy Ruler to
    ``bar_style="ruler"`` + ``orientation="vertical"``.  Stary ``slope`` nadal
    jest obsługiwany przez ``_bar_slope_fields()`` przy edycji legacy configów.
    """
    style = str(bar_style).strip().lower()
    style_choice = [
        FieldSchema("bar_style", "choice", "Styl", tab="",
                    choices=[("ruler", "Ruler"), ("segments", "Segments")], default="ruler"),
    ]
    header = _header_fields(allow_small_size=True, with_icon=(style in ("segment", "segments", "segmented", "segment_bar"))) + _form_field() + style_choice
    if style in ("segment", "segments", "segmented", "segment_bar"):
        return header + _bar_segments_fields()
    if style in ("slope", "grade", "vertical_slope"):
        return header + _bar_slope_fields()
    return header + _bar_ruler_fields()


def lean_indicator_fields() -> list[FieldSchema]:
    """Lean/Przechył: Header (bez source, ikony, label i unit), wygaszona forma, zakładki Data i Text."""
    return (
        _header_fields(with_source=False, with_icon=False, with_label=False, with_unit=False)
        + _form_field([("lean", "Przechył")])
        + [
            FieldSchema("source", "choice", "Źródło danych", tab="Data",
                        choices=[("gyro", "IMU GoPro (żyroskop + akcelerometr)"),
                                 ("grade", "FIT Grade / nachylenie terenu")],
                        default="gyro"),
            FieldSchema("axis", "choice", "Oś przechyłu", tab="Data",
                        choices=[("x", "X (roll)"), ("y", "Y (pitch)"), ("z", "Z (yaw)")],
                        default="x"),
            FieldSchema("calibration", "float", "Kalibracja / Offset [°]", tab="Data",
                        min_val=-90.0, max_val=90.0, step=0.5, default=6.0),
            FieldSchema("invert_axis", "bool", "Odwróć kierunek", tab="Data", default=False),
            FieldSchema("pivot_x", "float", "Punkt obrotu X", tab="Data",
                        min_val=0.0, max_val=1.0, step=0.01, default=0.5),
            FieldSchema("pivot_y", "float", "Punkt obrotu Y", tab="Data",
                        min_val=0.0, max_val=1.0, step=0.01, default=1.0),
            FieldSchema("sensitivity", "float", "Mnożnik wychyłu", tab="Data",
                        min_val=0.0, max_val=20.0, step=0.05, default=1.0),
            FieldSchema("max_angle", "float", "Maks. kąt wychyłu [°]", tab="Data",
                        min_val=1.0, max_val=90.0, step=1.0, default=30.0),
            FieldSchema("lean_smoothing_s", "float", "Wygładzanie ruchu", tab="Data",
                        min_val=0.0, max_val=5.0, step=0.1, default=0.0),
            FieldSchema("graphic", "choice", "Grafika", tab="Data",
                        choices=[("bike", "Rower (ikona)"), ("beam", "Belka"), ("none", "Brak")],
                        default="bike"),
            FieldSchema("show_reference", "bool", "Linia odniesienia 0°", tab="Data", default=True),
            FieldSchema("show_ticks", "bool", "Podziałka kątowa", tab="Data", default=True),
            FieldSchema("track_color", "color", "Kolor odniesienia", tab="Data", default="#FFFFFF"),
            FieldSchema("tick_color", "color", "Kolor podziałki", tab="Data", default="#F6F6F6"),
            FieldSchema("marker_color", "color", "Kolor grafiki", tab="Data", default="#FFFFFF"),
            FieldSchema("show_value", "bool", "Pokaż wartość", tab="Text", default=True),
            FieldSchema("show_label", "bool", "Pokaż etykietę", tab="Text", default=True),
            FieldSchema("title_text", "text", "Własna etykieta", tab="Text", default=""),
            FieldSchema("uppercase_title", "bool", "Etykieta WIELKIMI", tab="Text", default=False),
            FieldSchema("decimals", "int", "Miejsca dzies.", tab="Text",
                        min_val=0, max_val=2, step=1, default=0),
        ]
    )


def chart_indicator_fields(chart_time_scope: str = "activity") -> list[FieldSchema]:
    """Chart: Header, Text, Labels, Range, Chart (własna zakładka)."""
    return (
        _header_fields(with_icon=False) + _form_field()
        + _text_tab_fields(with_color=True, with_decimals=False)
        + [FieldSchema("decimal_places", "int", "Miejsca po przecinku", tab="Text",
                       min_val=0, max_val=2, step=1, default=1)]
        + _labels_tab_fields()
        + _ticks_tab_fields(with_ticks=False, with_step=False, with_tick_geometry=False)
        + _chart_tab_fields(chart_time_scope=chart_time_scope)
    )


def segment_bar_indicator_fields() -> list[FieldSchema]:
    """SegmentBar (legacy): przekierowanie do bar z bar_style='segments'."""
    return bar_indicator_fields(bar_style="segments")


def _map_gauge_tab_fields() -> list[FieldSchema]:
    return [
        FieldSchema("hide_marker", "bool", "Ukryj znacznik", tab="Gauge", default=False),
        FieldSchema("map_marker_style", "choice", "Styl znacznika", tab="Gauge",
                    choices=[("dot", "Kropka"), ("directional", "Strzałka kierunkowa"), ("none", "Brak")],
                    default="dot"),
        FieldSchema("marker_size", "int", "Rozmiar (Size)", tab="Gauge",
                    min_val=1, max_val=20, step=1, default=7),
        FieldSchema("marker_color", "color", "Kolor", tab="Gauge", default="#FFFFFF"),
    ]


def _map_path_tab_fields() -> list[FieldSchema]:
    return [
        FieldSchema("hide_track", "bool", "Ukryj (Hide)", tab="Path", default=False),
        FieldSchema("track_width", "int", "Grubość (Width)", tab="Path",
                    min_val=1, max_val=20, step=1, default=3),
        FieldSchema("track_color", "color", "Kolor", tab="Path", default="#FF3C1E"),
        # ETAP 10T: track antialiasing + outline
        FieldSchema("track_antialiasing", "choice", "Wygładzanie trasy", tab="Path",
                    choices=[("1", "Wyłączone"), ("2", "2x"), ("4", "4x")], default="1"),
        FieldSchema("track_outline_width", "int", "Grubość obrysu trasy", tab="Path",
                    min_val=0, max_val=12, step=1, default=0),
        FieldSchema("track_outline_color", "color", "Kolor obrysu trasy", tab="Path", default="#000000"),
    ]


def _map_shape_tab_fields() -> list[FieldSchema]:
    return [
        FieldSchema("map_orientation", "choice", "Orientacja mapy", tab="Shape",
                    choices=["north_up", "track_up"], default="north_up"),
        FieldSchema("map_rotation_smoothing_s", "float", "Wygładzanie obrotu", tab="Shape",
                    min_val=0.0, max_val=5.0, step=0.1, default=0.0),
        FieldSchema("map_style", "choice", "Mapa (Map)", tab="Shape",
                    choices=["light_all", "light_nolabels", "dark_all",
                             "dark_nolabels", "voyager_all", "voyager_nolabels", "satellite"],
                    default="light_all"),
        FieldSchema("map_shape", "choice", "Kształt (Shape)", tab="Shape",
                    choices=["square", "round"], default="square"),
        FieldSchema("opacity", "float", "Przezroczystość", tab="Shape",
                    min_val=0.0, max_val=1.0, step=0.05, default=1.0),
        FieldSchema("zoom", "int", "Zoom", tab="Shape",
                    min_val=1, max_val=24, step=1, default=16),
        FieldSchema("pitch", "float", "Pochylenie (Pitch)", tab="Shape",
                    min_val=0.0, max_val=70.0, step=1.0, default=0.0),
    ]


def map_indicator_fields() -> list[FieldSchema]:
    """Map: Header (bez label, unit, font), Typ, Gauge, Path, Shape."""
    return (
        _header_fields(with_source=False, allow_small_size=True, with_icon=False,
                       with_label=False, with_unit=False, with_font=False)
        + [FieldSchema("form", "choice", "Typ mapy", tab="",
                       choices=["map", "static_map"], default="map")]
        + _map_gauge_tab_fields()
        + _map_path_tab_fields()
        + _map_shape_tab_fields()
    )


def time_display_indicator_fields() -> list[FieldSchema]:
    """TimeDisplay: Header + 4 per-line tabs.

    ETAP 15: ``size`` to globalna skala master (1.0 = standardowy wygląd,
    0.5 = połowa, 2.0 = podwójny).  Legacy presety (v1..v10) zapisują 0.1 —
    renderer normalizuje je do tej samej skali (patrz
    ``time_display._time_display_master_size``).  ``icon`` przywrócono do
    schematu (domyślnie ``clock``) — renderer obsługiwał ikonę od zawsze,
    ale GUI nie miało pola do jej ustawienia.
    """
    header = [
        FieldSchema("size", "float", "Rozmiar", tab="",
                    min_val=0.05, max_val=10.0, step=0.05, default=1.0),
        FieldSchema("icon", "choice", "Ikona", tab="Ikona", choices=_ICON_CHOICES, default="clock"),
        FieldSchema("x", "float", "Pozycja X", tab="",
                    min_val=0.0, max_val=100.0, step=0.1, default=50.0),
        FieldSchema("y", "float", "Pozycja Y", tab="",
                    min_val=0.0, max_val=100.0, step=0.1, default=50.0),
        FieldSchema("rotation", "choice", "Rotacja", tab="",
                    choices=["0", "90", "180", "270"], default="0"),
        FieldSchema("font", "font", "Font", tab="", default=""),
    ]
    date_tab = [
        FieldSchema("show_date", "bool", "Pokaż datę", tab="Data", default=True),
        FieldSchema("show_date_label", "bool", "Pokaż etykietę", tab="Data", default=True),
        FieldSchema("date_label", "text", "Etykieta", tab="Data", default="Data"),
        FieldSchema("date_font_size", "float", "Rozmiar czcionki",
                    tab="Data", min_val=0.8, max_val=8.0, step=0.1, default=1.2),
        FieldSchema("date_color", "color", "Kolor", tab="Data", default="#D2D2D2"),
    ]
    time_tab = [
        FieldSchema("show_time", "bool", "Pokaż czas GPMF", tab="Czas", default=True),
        FieldSchema("show_time_label", "bool", "Pokaż etykietę", tab="Czas", default=True),
        FieldSchema("time_label", "text", "Etykieta", tab="Czas", default="Godzina"),
        FieldSchema("time_font_size", "float", "Rozmiar czcionki",
                    tab="Czas", min_val=0.8, max_val=8.0, step=0.1, default=1.9),
        FieldSchema("time_color", "color", "Kolor", tab="Czas", default="#FFFFFF"),
    ]
    elapsed_tab = [
        FieldSchema("show_elapsed", "bool", "Pokaż czas od startu", tab="Od początku", default=True),
        FieldSchema("show_elapsed_label", "bool", "Pokaż etykietę", tab="Od początku", default=True),
        FieldSchema("elapsed_label", "text", "Etykieta", tab="Od początku", default="Czas"),
        FieldSchema("elapsed_font_size", "float", "Rozmiar czcionki",
                    tab="Od początku", min_val=0.8, max_val=8.0, step=0.1, default=1.5),
        FieldSchema("elapsed_color", "color", "Kolor", tab="Od początku", default="#FFFFFF"),
    ]
    avg_speed_tab = [
        FieldSchema("show_avg_speed", "bool", "Pokaż śr. prędkość", tab="Śr. prędkość", default=True),
        FieldSchema("show_avg_speed_label", "bool", "Pokaż etykietę", tab="Śr. prędkość", default=True),
        FieldSchema("avg_speed_label", "text", "Etykieta", tab="Śr. prędkość", default="Średnia prędkość"),
        FieldSchema("avg_speed_font_size", "float", "Rozmiar czcionki",
                    tab="Śr. prędkość", min_val=0.8, max_val=8.0, step=0.1, default=1.5),
        FieldSchema("avg_speed_color", "color", "Kolor", tab="Śr. prędkość", default="#FFFFFF"),
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
    "lean":        lean_indicator_fields,
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
