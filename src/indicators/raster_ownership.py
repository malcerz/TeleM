"""Owned snapshots at public Bar/widget-cache boundaries.

Internal borrowed rasters are read-only by contract: never paint, putalpha,
paste into, or mutate their metadata. Keep the owner alive through consumption.
Only the small indicator tile is copied here, never the composed HUD canvas.
"""
from copy import deepcopy

from PIL import Image

_COPY_STATS = {"images": 0, "bytes": 0}


def owned_render_result(result):
    image, x, y, metadata = result
    if isinstance(image, Image.Image):
        image = image.copy()
        image.info = deepcopy(image.info)
        # Image.copy intentionally drops private dynamic cache signatures.
        # A mutable public image must use content-based effects lookup after
        # caller edits, rather than an immutable borrowed-raster signature.
        _COPY_STATS["images"] += 1
        _COPY_STATS["bytes"] += image.width * image.height * len(image.getbands())
    return image, x, y, deepcopy(metadata)


def get_owned_copy_stats():
    """Copied raster payload estimate (not allocator/driver memory usage)."""
    return dict(_COPY_STATS)
