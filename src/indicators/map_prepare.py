"""Map placeholder / progress rendering for the async GUI map path.

The map indicator renders a real-size placeholder while the overview/detail
tiles are being prepared (during project load or a provider switch).  The
placeholder carries the widget geometry (x/y/size), the same z-order as the
map, and shows the real tile progress (loaded / required).  It never blocks
the GUI thread.
"""

from __future__ import annotations

import threading

try:
    from PIL import Image, ImageDraw
except ImportError:  # pragma: no cover
    Image = None  # type: ignore[assignment]
    ImageDraw = None  # type: ignore[assignment]

# The MapContext for the current project (set by the GUI controller).  Worker
# processes (final render) never set it — those paths stay fully synchronous.
_CURRENT_MAP_CONTEXT = None
_LOCK = threading.Lock()

_BG = (24, 26, 30, 255)
_FG = (210, 214, 220, 255)
_BAR = (0, 120, 212, 255)
_ERR = (200, 60, 60, 255)


def set_current_map_context(ctx) -> None:
    global _CURRENT_MAP_CONTEXT
    with _LOCK:
        _CURRENT_MAP_CONTEXT = ctx


def get_current_map_context():
    with _LOCK:
        return _CURRENT_MAP_CONTEXT


def render_overview_map(
    overview_img,
    w: int,
    h: int,
    bounds=None,
    marker_latlon=None,
    marker_color=(255, 255, 255, 255),
    marker_radius: int = 7,
) -> Image.Image | None:
    """Scale the prepared overview image to the widget and draw the position marker.

    ``bounds`` = (min_lat, min_lon, max_lat, max_lon).  ``marker_latlon`` is the
    current GPS position (absolute target_dt → track).  Used as the immediate
    "Level 1" map while detail tiles load in the background.
    """
    if overview_img is None or Image is None:
        return None
    w = max(1, int(w))
    h = max(1, int(h))
    img = overview_img.convert("RGBA")
    img.thumbnail((w, h), Image.Resampling.LANCZOS)
    canvas = Image.new("RGBA", (w, h), (30, 30, 30, 255))
    ox = (w - img.width) // 2
    oy = (h - img.height) // 2
    canvas.paste(img, (ox, oy))
    if marker_latlon is not None and bounds:
        lat, lon = marker_latlon
        min_lat, min_lon, max_lat, max_lon = bounds
        span_lon = max(1e-9, max_lon - min_lon)
        span_lat = max(1e-9, max_lat - min_lat)
        fx = (lon - min_lon) / span_lon
        fy = 1.0 - (lat - min_lat) / span_lat
        mx = int(ox + fx * img.width)
        my = int(oy + fy * img.height)
        d = ImageDraw.Draw(canvas)
        r = max(2, marker_radius)
        d.ellipse((mx - r, my - r, mx + r, my + r),
                  fill=marker_color, outline=(0, 0, 0, 220), width=2)
    return canvas


def render_map_placeholder(
    w: int,
    h: int,
    progress: float | None = None,
    loaded: int | None = None,
    required: int | None = None,
    error: str | None = None,
    label: str = "Ładowanie mapy…",
) -> Image.Image | None:
    """Render a real-size map placeholder with status/progress."""
    if Image is None:
        return None
    w = max(1, int(w))
    h = max(1, int(h))
    img = Image.new("RGBA", (w, h), _BG)
    d = ImageDraw.Draw(img)
    d.rectangle((0, 0, w - 1, h - 1), outline=(90, 100, 112, 255), width=1)

    font = None
    try:
        from src.indicators.helpers import load_font
        fs = max(9, int(min(w, h) * 0.10))
        font = load_font("", fs)
    except Exception:
        font = None

    cx = w // 2
    main = error or label
    text_fill = _ERR if error else _FG
    if font is not None:
        bb = d.textbbox((0, 0), main, font=font)
        d.text((max(1, cx - (bb[2] - bb[0]) // 2), max(1, h // 4)), main,
               font=font, fill=text_fill)
    else:
        d.text((max(1, cx - 30), max(1, h // 4)), main, fill=text_fill)

    # Status line (tile progress) below the label
    status = ""
    if loaded is not None and required is not None:
        status = f"{loaded}/{required} kafelków"
    elif error:
        status = ""
    if status and font is not None:
        bb = d.textbbox((0, 0), status, font=font)
        d.text((max(1, cx - (bb[2] - bb[0]) // 2), max(1, h // 2)), status,
               font=font, fill=_FG)

    # Progress bar (bottom area)
    bar_w = max(20, int(w * 0.6))
    bar_h = max(4, int(h * 0.06))
    bx = cx - bar_w // 2
    by = h - bar_h - max(4, int(h * 0.05))
    d.rectangle((bx, by, bx + bar_w, by + bar_h), outline=(70, 80, 92, 255), width=1)
    if progress is not None and progress > 0:
        fill_w = max(1, int(bar_w * max(0.0, min(1.0, progress))))
        d.rectangle((bx + 1, by + 1, bx + fill_w, by + bar_h - 1), fill=_BAR)
    else:
        fill_w = max(1, int(bar_w * 0.5))
        d.rectangle((bx + 1, by + 1, bx + fill_w, by + bar_h - 1),
                    fill=(_BAR[0], _BAR[1], _BAR[2], 120))
    return img
