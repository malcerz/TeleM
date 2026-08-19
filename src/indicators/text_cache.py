"""
Dirty Text Cache / Selective Rendering for CPU_ABOVE_MAP (ETAP 8Q).

Caches rendered and rotated text rasters with bounded LRU memory.
Ensures 100% byte-exact pixel parity while eliminating repeated Pillow text rendering.
"""
from __future__ import annotations

import os
from collections import OrderedDict
from dataclasses import dataclass
from typing import Optional, Any
from PIL import Image


@dataclass(frozen=True)
class TextRasterKey:
    """Immutable cache key capturing all properties affecting raster pixels."""
    key: str
    text: str
    font_path: str
    font_size: int
    color: tuple[int, int, int, int]
    outline_width: int
    outline_color: tuple[int, int, int, int]
    rotation: int
    canvas_w: int
    canvas_h: int


@dataclass
class TextRasterEntry:
    """Cached raster and metadata."""
    image: Image.Image
    width: int
    height: int


class AboveTextCache:
    """Bounded LRU cache for rendered text indicators."""

    def __init__(self, max_entries: int = 512):
        self.max_entries = max_entries
        self.cache: OrderedDict[TextRasterKey, TextRasterEntry] = OrderedDict()
        self.hits: dict[str, int] = {}
        self.misses: dict[str, int] = {}
        self.total_bytes: int = 0

    def clear(self) -> None:
        self.cache.clear()
        self.hits.clear()
        self.misses.clear()
        self.total_bytes = 0

    def get(self, key: TextRasterKey) -> Optional[TextRasterEntry]:
        entry = self.cache.get(key)
        if entry is not None:
            self.cache.move_to_end(key)
            self.hits[key.key] = self.hits.get(key.key, 0) + 1
            return entry
        self.misses[key.key] = self.misses.get(key.key, 0) + 1
        return None

    def put(self, key: TextRasterKey, entry: TextRasterEntry) -> None:
        if key in self.cache:
            self.cache.move_to_end(key)
            return
        while len(self.cache) >= self.max_entries:
            _, old_entry = self.cache.popitem(last=False)
            self.total_bytes -= old_entry.width * old_entry.height * 4
        self.cache[key] = entry
        self.total_bytes += entry.width * entry.height * 4

    def stats(self) -> dict[str, Any]:
        tot_hits = sum(self.hits.values())
        tot_misses = sum(self.misses.values())
        tot_req = tot_hits + tot_misses
        rate = (tot_hits / tot_req * 100.0) if tot_req > 0 else 0.0
        return {
            "entries": len(self.cache),
            "total_bytes": self.total_bytes,
            "peak_mb": self.total_bytes / (1024 * 1024),
            "hits": tot_hits,
            "misses": tot_misses,
            "hit_rate_pct": rate,
            "per_indicator_hits": dict(self.hits),
            "per_indicator_misses": dict(self.misses),
        }


# Global singleton instance for export sessions
_GLOBAL_ABOVE_TEXT_CACHE = AboveTextCache()


def get_above_text_cache() -> AboveTextCache:
    return _GLOBAL_ABOVE_TEXT_CACHE
