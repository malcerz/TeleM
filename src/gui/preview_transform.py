"""Preview geometry and coordinate transformation system.

Provides mathematical mapping between:
1. Source / canonical video coordinates (e.g. 3840x2160, layout pixels)
2. Normalized coordinates (0.0 .. 100.0 percent)
3. Displayed video rectangle in the preview viewport (accounting for letterbox/pillarbox)
4. Physical raster pixels (DPI-aware, devicePixelRatio)
"""

from __future__ import annotations

from dataclasses import dataclass


def calculate_displayed_video_rect(
    viewport_w: int,
    viewport_h: int,
    source_w: int,
    source_h: int,
) -> tuple[int, int, int, int]:
    """Calculate (offset_x, offset_y, displayed_w, displayed_h) in logical viewport pixels.

    Preserves source aspect ratio exactly.
    Handles letterbox (horizontal bars top/bottom) when viewport is taller than video.
    Handles pillarbox (vertical bars left/right) when viewport is wider than video.
    """
    viewport_w = max(1, int(viewport_w))
    viewport_h = max(1, int(viewport_h))
    source_w = max(1, int(source_w))
    source_h = max(1, int(source_h))

    source_aspect = float(source_w) / float(source_h)
    viewport_aspect = float(viewport_w) / float(viewport_h)

    if viewport_aspect >= source_aspect:
        # Viewport is wider than video -> pillarbox (bars on left and right)
        target_h = viewport_h
        target_w = max(1, int(round(viewport_h * source_aspect)))
        # Guard against rounding exceeding viewport
        if target_w > viewport_w:
            target_w = viewport_w
        ox = (viewport_w - target_w) // 2
        oy = 0
    else:
        # Viewport is taller than video -> letterbox (bars on top and bottom)
        target_w = viewport_w
        target_h = max(1, int(round(viewport_w / source_aspect)))
        # Guard against rounding exceeding viewport
        if target_h > viewport_h:
            target_h = viewport_h
        ox = 0
        oy = (viewport_h - target_h) // 2

    return (ox, oy, target_w, target_h)


def calculate_physical_video_rect(
    viewport_w: int,
    viewport_h: int,
    source_w: int,
    source_h: int,
    dpr: float = 1.0,
) -> tuple[int, int, int, int]:
    """Calculate (phys_ox, phys_oy, phys_w, phys_h) in physical device pixels."""
    dpr = max(0.1, float(dpr))
    ox, oy, dw, dh = calculate_displayed_video_rect(viewport_w, viewport_h, source_w, source_h)
    return (
        int(round(ox * dpr)),
        int(round(oy * dpr)),
        max(1, int(round(dw * dpr))),
        max(1, int(round(dh * dpr))),
    )


def source_to_preview_coords(
    sx: float,
    sy: float,
    viewport_w: int,
    viewport_h: int,
    source_w: int,
    source_h: int,
) -> tuple[float, float]:
    """Transform canonical source pixel coordinates (sx, sy) to preview widget pixel coordinates."""
    ox, oy, dw, dh = calculate_displayed_video_rect(viewport_w, viewport_h, source_w, source_h)
    u = float(sx) / max(1.0, float(source_w))
    v = float(sy) / max(1.0, float(source_h))
    return (ox + u * dw, oy + v * dh)


def preview_to_source_coords(
    px: float,
    py: float,
    viewport_w: int,
    viewport_h: int,
    source_w: int,
    source_h: int,
) -> tuple[float, float]:
    """Transform preview widget pixel coordinates (px, py) to canonical source coordinates."""
    ox, oy, dw, dh = calculate_displayed_video_rect(viewport_w, viewport_h, source_w, source_h)
    u = (float(px) - ox) / max(1.0, float(dw))
    v = (float(py) - oy) / max(1.0, float(dh))
    return (u * float(source_w), v * float(source_h))


def norm_to_preview_coords(
    nx: float,
    ny: float,
    viewport_w: int,
    viewport_h: int,
    source_w: int,
    source_h: int,
) -> tuple[float, float]:
    """Transform normalized percentage coordinates (0..100) to preview widget pixel coordinates."""
    ox, oy, dw, dh = calculate_displayed_video_rect(viewport_w, viewport_h, source_w, source_h)
    u = float(nx) / 100.0
    v = float(ny) / 100.0
    return (ox + u * dw, oy + v * dh)


def preview_to_norm_coords(
    px: float,
    py: float,
    viewport_w: int,
    viewport_h: int,
    source_w: int,
    source_h: int,
) -> tuple[float, float]:
    """Transform preview widget pixel coordinates (px, py) to normalized percentage coordinates (0..100)."""
    ox, oy, dw, dh = calculate_displayed_video_rect(viewport_w, viewport_h, source_w, source_h)
    u = (float(px) - ox) / max(1.0, float(dw))
    v = (float(py) - oy) / max(1.0, float(dh))
    return (u * 100.0, v * 100.0)


@dataclass(frozen=True)
class PreviewGeometry:
    """Immutable snapshot of the preview transform geometry."""

    viewport_w: int
    viewport_h: int
    source_w: int
    source_h: int
    dpr: float
    offset_x: int
    offset_y: int
    displayed_w: int
    displayed_h: int
    physical_w: int
    physical_h: int

    @classmethod
    def compute(
        cls,
        viewport_w: int,
        viewport_h: int,
        source_w: int,
        source_h: int,
        dpr: float = 1.0,
    ) -> PreviewGeometry:
        ox, oy, dw, dh = calculate_displayed_video_rect(viewport_w, viewport_h, source_w, source_h)
        _, _, pw, ph = calculate_physical_video_rect(viewport_w, viewport_h, source_w, source_h, dpr)
        return cls(
            viewport_w=viewport_w,
            viewport_h=viewport_h,
            source_w=source_w,
            source_h=source_h,
            dpr=float(dpr),
            offset_x=ox,
            offset_y=oy,
            displayed_w=dw,
            displayed_h=dh,
            physical_w=pw,
            physical_h=ph,
        )

    def source_to_preview(self, sx: float, sy: float) -> tuple[float, float]:
        u = float(sx) / max(1.0, float(self.source_w))
        v = float(sy) / max(1.0, float(self.source_h))
        return (self.offset_x + u * self.displayed_w, self.offset_y + v * self.displayed_h)

    def preview_to_source(self, px: float, py: float) -> tuple[float, float]:
        u = (float(px) - self.offset_x) / max(1.0, float(self.displayed_w))
        v = (float(py) - self.offset_y) / max(1.0, float(self.displayed_h))
        return (u * float(self.source_w), v * float(self.source_h))

    def norm_to_preview(self, nx: float, ny: float) -> tuple[float, float]:
        u = float(nx) / 100.0
        v = float(ny) / 100.0
        return (self.offset_x + u * self.displayed_w, self.offset_y + v * self.displayed_h)

    def preview_to_norm(self, px: float, py: float) -> tuple[float, float]:
        u = (float(px) - self.offset_x) / max(1.0, float(self.displayed_w))
        v = (float(py) - self.offset_y) / max(1.0, float(self.displayed_h))
        return (u * 100.0, v * 100.0)
