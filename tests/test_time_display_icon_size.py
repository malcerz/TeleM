"""ETAP 15 — time_display: ikona + globalna skala Rozmiar + cache.

Contract (task parts 1–13):

- Nowy time_display ma rozsądne, nie-gigantyczne domyślne rozmiary
  (baseline = sprawdzony wizualnie preset v10).
- Globalne ``size`` (Rozmiar) jest skalą master całego bloku:
  1.0 = standard, 0.5 = połowa, 2.0 = podwójny.
- Per-line ``{prefix}_font_size`` zmienia TYLKO jedną linię.
- Schema zawiera pole ``icon`` (domyślnie ``clock``) — renderer obsługiwał
  ikonę od zawsze, ale GUI nie miało pola.
- Ikona skaluje się z globalnym Rozmiarem.
- Cache nie zwraca nieaktualnego rastra po zmianie size / ikony / per-line
  fontów / kolorów / etykiet (klucz cache zawiera wszystkie te parametry).
- Preview == Final (ten sam renderer, deterministyczny wynik).
- Legacy configi (size=0.1, brak ``icon``) nie psują się i zachowują wygląd
  (0.1 == 1.0 po normalizacji; brak ikony == icon "none").
"""

from __future__ import annotations

import os

import pytest
from PIL import ImageChops

from src.gui.qt.models import (
    canonical_defaults,
    get_schema_for_form,
    time_display_indicator_fields,
)
from src.indicators.compositor import compose_overlay
from src.indicators.helpers import resolve_indicator_font_path
from src.indicators.time_display import render_time_display

# ── Helpers ────────────────────────────────────────────────────────────────
# Prawdziwy font TrueType jest potrzebny do testów skali wysokości — fallback
# PIL ("load_default()") rysuje stałą wysokość niezależnie od rozmiaru.
def _resolve_test_font() -> str:
    for family in ("Arial", "Segoe UI", "Calibri"):
        path = resolve_indicator_font_path(family, "")
        if path and os.path.isfile(path):
            return path
    for cand in (r"C:/Windows/Fonts/arial.ttf", r"C:/Windows/Fonts/segoeui.ttf",
                 r"C:/Windows/Fonts/calibri.ttf"):
        if os.path.isfile(cand):
            return cand
    return ""


_FONT = _resolve_test_font()


def _require_font() -> None:
    if not _FONT:
        pytest.skip("TrueType font (Arial) niedostępny — pomijam test skali wysokości")


def _rgb_diff(a, b):
    """Różnica w kanale RGB — getbbox() na RGBA zwraca None przy alfa=0."""
    return ImageChops.difference(a.convert("RGB"), b.convert("RGB"))
# Baseline wzorowany na sprawdzonym presecie cycling_dashboard_v10.json.
_BASELINE = {
    "enabled": True, "form": "time_display", "label": "TIME",
    "x": 2.0, "y": 2.0, "rotation": 0, "icon": "clock", "size": 1.0,
    "font_size": 1.8,
    "show_date": True, "show_time": True, "show_elapsed": True,
    "show_avg_speed": True,
    "show_date_label": True, "date_label": "Data",
    "show_time_label": True, "time_label": "Godzina",
    "show_elapsed_label": True, "elapsed_label": "Czas",
    "show_avg_speed_label": True, "avg_speed_label": "Średnia prędkość",
    "date_font_size": 1.2, "time_font_size": 1.9,
    "elapsed_font_size": 1.5, "avg_speed_font_size": 1.5,
    "date_color": "#D2D2D2", "time_color": "#FFFFFF",
    "elapsed_color": "#FFFFFF", "avg_speed_color": "#FFFFFF",
}


def _td_cfg(**over) -> dict:
    cfg = dict(_BASELINE)
    cfg.update(over)
    return cfg


def _render(cfg, canvas=(1280, 720), date="2026-07-28", time="14:32:15",
            elapsed=3600, avg_speed=25.4):
    w, h = canvas
    layout = {"global": {"text_outline": 3}, "indicators": {"time_display": cfg}}
    return render_time_display(w, h, layout, _FONT, date, time, elapsed, avg_speed)


def _size_of(cfg) -> tuple[int, int]:
    img = _render(cfg)[0]
    assert img is not None
    return img.size


def _single_line_cfg(prefix: str = "time", **over) -> dict:
    """Tylko jedna linia włączona (czyste porównanie wysokości)."""
    cfg = _td_cfg(
        show_date=False, show_time=False, show_elapsed=False,
        show_avg_speed=False, icon="none",
    )
    cfg[f"show_{prefix}"] = True
    cfg[f"show_{prefix}_label"] = False
    cfg.update(over)
    return cfg


# ---------------------------------------------------------------------------
# TEST 1 — Nowy time_display ma rozsądny rozmiar (baseline v10, NIE gigant)
# ---------------------------------------------------------------------------

def test_new_default_size_is_sane():
    w, h = _size_of(_td_cfg())
    # Baseline v10 (master 1.0) daje blok ~65 px wysokości na 720p.
    # Poprzedni bug (size=2.5 -> stary size_mult=25) dawał kilkaset px.
    assert h > 20, f"blok podejrzanie mały: {h}px"
    assert h < 300, f"blok wciąż gigantyczny: {h}px"


def test_new_default_size_matches_v10_baseline():
    """Nowy size=1.0 renderuje identycznie jak legacy v10 size=0.1."""
    new_cfg = _td_cfg(size=1.0)
    legacy_cfg = _td_cfg(size=0.1)
    img_new = _render(new_cfg)[0]
    img_legacy = _render(legacy_cfg)[0]
    assert img_new is not None and img_legacy is not None
    assert img_new.size == img_legacy.size
    diff = _rgb_diff(img_new, img_legacy)
    assert diff.getbbox() is None, "size=1.0 i legacy size=0.1 różnią się pikselami"


# ---------------------------------------------------------------------------
# TEST 2 — Globalna skala: 1.0 vs 0.5 -> wysokość bloku ~połowa
# ---------------------------------------------------------------------------

def test_global_master_scale_halves_bbox():
    _require_font()
    w_full, h_full = _size_of(_td_cfg(size=1.0, icon="none"))
    w_half, h_half = _size_of(_td_cfg(size=0.5, icon="none"))
    assert h_full > 30
    # Zarówno wysokość, jak i szerokość maleją wraz z czcionką; kluczowy jest
    # stosunek wysokości: master 0.5 -> wysokość ~połowa.
    assert w_half < w_full
    assert 0.4 * h_full <= h_half <= 0.75 * h_full, (h_full, h_half)


def test_global_master_scale_doubles_single_line():
    """Master 2.0 -> ta sama pojedyncza linia ~2× wyższa."""
    _require_font()
    base = _single_line_cfg("time")
    _, h1 = _size_of(base)
    _, h2 = _size_of(_td_cfg(size=2.0, **{k: v for k, v in base.items() if k != "size"}))
    assert h2 > h1 * 1.4, (h1, h2)


# ---------------------------------------------------------------------------
# TEST 3 — Globalna skala wpływa na wszystkie komponenty
# ---------------------------------------------------------------------------

def test_master_scale_affects_every_line():
    """Każda z 4 linii skaluje się z globalnym Rozmiarem."""
    _require_font()
    for prefix in ("date", "time", "elapsed", "avg_speed"):
        _, h1 = _size_of(_single_line_cfg(prefix, size=1.0))
        _, h2 = _size_of(_single_line_cfg(prefix, size=2.0))
        assert h2 > h1, f"linia {prefix}: master 2.0 nie zwiększył wysokości ({h1}->{h2})"


# ---------------------------------------------------------------------------
# TEST 4 — Per-line font size zmienia TYLKO jedną linię
# ---------------------------------------------------------------------------

def test_local_font_size_affects_only_its_line():
    _require_font()
    # Dwie linie: time + date. Zmiana time_font_size nie zmienia date.
    cfg = _td_cfg(
        show_date=True, show_time=True, show_elapsed=False, show_avg_speed=False,
        show_date_label=False, show_time_label=False, icon="none",
    )
    base_h = _size_of(cfg)[1]
    big_h = _size_of(_td_cfg(
        time_font_size=4.0,
        show_date=True, show_time=True, show_elapsed=False, show_avg_speed=False,
        show_date_label=False, show_time_label=False, icon="none",
    ))[1]
    assert big_h > base_h, "time_font_size nie zwiększył wysokości bloku"

    # Pojedyncza linia date: zmiana time_font_size nie ma wpływu.
    d1 = _size_of(_single_line_cfg("date"))[1]
    d2 = _size_of(_single_line_cfg("date", time_font_size=4.0))[1]
    assert d1 == d2, "time_font_size zmienił linię date"


# ---------------------------------------------------------------------------
# TEST 5 — Schema zawiera pole icon
# ---------------------------------------------------------------------------

def test_schema_has_icon_field():
    schema = time_display_indicator_fields()
    names = [f.name for f in schema]
    assert "icon" in names
    icon_field = next(f for f in schema if f.name == "icon")
    assert icon_field.choices == [
        "none", "clock", "camera", "temperature", "battery", "solar",
    ]


def test_schema_icon_default_is_clock():
    schema = time_display_indicator_fields()
    icon_field = next(f for f in schema if f.name == "icon")
    assert icon_field.default == "clock"


def test_schema_size_default_is_one():
    """Rozmiar to teraz skala master z defaultem 1.0 (= standard)."""
    schema = time_display_indicator_fields()
    size_field = next(f for f in schema if f.name == "size")
    assert size_field.default == 1.0


# ---------------------------------------------------------------------------
# TEST 6 — Ikona: none vs clock różnią się, ikona skaluje się z Rozmiarem
# ---------------------------------------------------------------------------

def test_icon_clock_wider_than_none():
    w_none, _ = _size_of(_td_cfg(icon="none"))
    w_clock, _ = _size_of(_td_cfg(icon="clock"))
    assert w_clock > w_none, "ikona zegara powinna poszerzać blok"


def test_icon_scales_with_master_size():
    w1, _ = _size_of(_td_cfg(icon="clock", size=1.0))
    w2, _ = _size_of(_td_cfg(icon="clock", size=2.0))
    assert w2 > w1, "ikona powinna rosnąć wraz z globalnym Rozmiarem"


# ---------------------------------------------------------------------------
# TEST 7 — Cache: zmiana size / ikony / per-line stylu unieważnia raster
# ---------------------------------------------------------------------------

def test_cache_invalidation_on_size_change():
    # Ten sam tekst, inny size -> MUSI dać inny wynik (wcześniej klucz cache
    # nie zawierał size -> "Rozmiar nie reaguje").
    img1 = _render(_td_cfg(size=1.0))[0]
    img2 = _render(_td_cfg(size=2.0))[0]
    assert img1 is not None and img2 is not None
    assert img1.size != img2.size


def test_cache_invalidation_on_icon_change():
    img_none = _render(_td_cfg(icon="none"))[0]
    img_clock = _render(_td_cfg(icon="clock"))[0]
    assert img_none is not None and img_clock is not None
    assert img_none.size != img_clock.size


def test_cache_invalidation_on_per_line_style_change():
    img_small = _render(_td_cfg(date_font_size=1.2))[0]
    img_big = _render(_td_cfg(date_font_size=4.0))[0]
    assert img_small is not None and img_big is not None
    assert img_small.size != img_big.size


def test_cache_invalidation_on_color_change():
    img_grey = _render(_td_cfg(time_color="#AAAAAA"))[0]
    img_red = _render(_td_cfg(time_color="#FF0000"))[0]
    assert img_grey is not None and img_red is not None
    assert img_grey.size == img_red.size  # kolor nie zmienia wymiarów
    diff = _rgb_diff(img_grey, img_red)
    assert diff.getbbox() is not None, "zmiana koloru nie dotarła do rastra (cache?)"


def test_property_live_update_reflects_immediately():
    """Symulacja GUI: zmiana cfg + ponowny render = natychmiastowy efekt."""
    cfg = _td_cfg()
    img_before = _render(cfg)[0]
    cfg["size"] = 0.5
    img_after = _render(cfg)[0]
    assert img_before is not None and img_after is not None
    assert img_after.size != img_before.size


# ---------------------------------------------------------------------------
# TEST 8 — Preview == Final (ten sam renderer, deterministyczny wynik)
# ---------------------------------------------------------------------------

def test_render_is_deterministic_preview_final_parity():
    a = _render(_td_cfg())[0]
    b = _render(_td_cfg())[0]
    assert a is not None and b is not None
    assert a.size == b.size
    diff = _rgb_diff(a, b)
    assert diff.getbbox() is None, "ten sam input dał różne rastry"


def test_compose_overlay_path_renders_time_display():
    """Składnia końcowa (compose_overlay) obsługuje time_display bez błędów."""
    layout = {
        "global": {"text_outline": 3},
        "indicators": {"time_display": _td_cfg()},
    }
    out = compose_overlay(
        1280, 720, layout, _FONT,
        "2026-07-28", "14:32:15", 0.0, 0.0,
        elapsed_seconds=3600, avg_speed_kmh=25.4,
        reuse_canvas=False,
    )
    assert out is not None


# ---------------------------------------------------------------------------
# TEST 9 — Legacy config: brak ikony / size=0.1 nie psuje i zachowuje wygląd
# ---------------------------------------------------------------------------

def test_legacy_config_without_icon_renders_like_none():
    cfg = _td_cfg()
    del cfg["icon"]
    img_legacy = _render(cfg)[0]
    img_none = _render(_td_cfg(icon="none"))[0]
    assert img_legacy is not None and img_none is not None
    assert img_legacy.size == img_none.size
    diff = _rgb_diff(img_legacy, img_none)
    assert diff.getbbox() is None, "brak ikony różni się od icon=none"


def test_minimal_legacy_cfg_does_not_crash():
    # Legacy preset zawsze zawiera x/y; reszta może być niepełna.
    img = _render({"enabled": True, "form": "time_display", "x": 2.0, "y": 2.0})[0]
    assert img is not None


# ---------------------------------------------------------------------------
# TEST 10 — Kanoniczne defaulty schematu = baseline v10 (nowy wskaźnik)
# ---------------------------------------------------------------------------

def test_canonical_defaults_match_v10_baseline():
    defaults = canonical_defaults(get_schema_for_form("time_display"))
    assert defaults["size"] == 1.0
    assert defaults["icon"] == "clock"
    # globalne font_size nie jest polem schematu time_display — pochodzi
    # z domyślnych wartości tworzenia wskaźnika (indicator_mixin).
    assert "font_size" not in defaults
    assert defaults["date_font_size"] == 1.2
    assert defaults["time_font_size"] == 1.9
    assert defaults["elapsed_font_size"] == 1.5
    assert defaults["avg_speed_font_size"] == 1.5
