"""Small, GUI-only helpers for the preview shown during export.

The encoder never calls this module.  It deliberately operates on a copied
preview frame so the export/encoder input cannot be dimmed as a side effect.
"""

from __future__ import annotations

from PIL import Image

from src.indicators.helpers import PREVIEW_VIDEO_BRIGHTNESS, dim_preview_video


def compose_export_preview(
    video_frame: Image.Image,
    hud_overlay: Image.Image,
    brightness: float = PREVIEW_VIDEO_BRIGHTNESS,
) -> Image.Image:
    """Return ``DIM VIDEO`` followed by ``HUD`` for the GUI export preview."""
    video = dim_preview_video(video_frame, brightness)
    hud = hud_overlay.convert("RGBA")
    if video.size != hud.size:
        hud = hud.resize(video.size, Image.Resampling.BILINEAR)
    video.alpha_composite(hud)
    return video

