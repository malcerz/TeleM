"""CPU HUD region-of-interest (ROI) planning, atlas packing and filter graph.

The CPU export normally pipes a full-canvas RGBA HUD frame to FFmpeg, which
converts it to yuva420p10le and blends it over the whole 4K frame.  Only a small
part of that canvas ever carries alpha > 0.  This module plans a handful of
tile-aligned rectangles that cover every pixel the HUD can paint, packs just
those rectangles into a small "atlas" frame for the pipe, and builds the FFmpeg
filter graph that overlays each region at its source position.

Nothing here knows about a particular layout: the plan comes from the measured
alpha of real HUD frames (union over sample frames), dilated by a safety margin.
Geometry is expressed in the orientation of the frames being piped.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence

import numpy as np

# Cost model in "pixel equivalents": a region's cost is its area plus a fixed
# per-region overhead (extra crop/overlay filter instance and per-frame setup).
DEFAULT_REGION_OVERHEAD_PX = 60_000
DEFAULT_TILE = 32
DEFAULT_MARGIN_PX = 16
DEFAULT_MAX_REGIONS = 8
DEFAULT_ATLAS_WIDTH = 2048


@dataclass(frozen=True)
class Region:
    x: int
    y: int
    w: int
    h: int

    @property
    def area(self) -> int:
        return self.w * self.h

    @property
    def x2(self) -> int:
        return self.x + self.w

    @property
    def y2(self) -> int:
        return self.y + self.h


@dataclass(frozen=True)
class AtlasCell:
    region: Region
    ax: int
    ay: int


@dataclass(frozen=True)
class RoiPlan:
    canvas_w: int
    canvas_h: int
    tile: int
    cells: tuple[AtlasCell, ...]
    atlas_w: int
    atlas_h: int

    @property
    def regions(self) -> tuple[Region, ...]:
        return tuple(c.region for c in self.cells)

    @property
    def region_area(self) -> int:
        return sum(c.region.area for c in self.cells)

    @property
    def fraction_of_canvas(self) -> float:
        return self.region_area / float(self.canvas_w * self.canvas_h)

    @property
    def atlas_fraction(self) -> float:
        return self.atlas_w * self.atlas_h / float(self.canvas_w * self.canvas_h)


def alpha_union(alphas: Iterable[np.ndarray]) -> np.ndarray:
    """Union (any alpha > 0) of several HxW uint8 alpha planes."""
    union = None
    for a in alphas:
        m = a > 0
        union = m if union is None else (union | m)
    if union is None:
        raise ValueError("alpha_union needs at least one alpha plane")
    return union


def occupancy_grid(mask: np.ndarray, tile: int, margin_px: int) -> np.ndarray:
    """Tile grid (True = tile contains HUD) of ``mask`` dilated by ``margin_px``."""
    h, w = mask.shape
    gh, gw = -(-h // tile), -(-w // tile)
    pad = np.zeros((gh * tile, gw * tile), dtype=bool)
    pad[:h, :w] = mask
    grid = pad.reshape(gh, tile, gw, tile).any(axis=(1, 3))
    # margin_px dilation expressed in whole tiles (rounded up): covers chroma
    # filter support, anti-aliasing/shadow tails and small dynamic excursions.
    k = -(-int(margin_px) // tile) if margin_px > 0 else 0
    if k:
        g = np.pad(grid, k)
        out = np.zeros_like(grid)
        for dy in range(-k, k + 1):
            for dx in range(-k, k + 1):
                out |= g[k + dy:k + dy + gh, k + dx:k + dx + gw]
        grid = out
    return grid


def _tight(grid: np.ndarray, x0: int, y0: int, x1: int, y1: int):
    sub = grid[y0:y1, x0:x1]
    rows = np.flatnonzero(sub.any(axis=1))
    if rows.size == 0:
        return None
    cols = np.flatnonzero(sub.any(axis=0))
    return (x0 + int(cols[0]), y0 + int(rows[0]), x0 + int(cols[-1]) + 1, y0 + int(rows[-1]) + 1)


def _empty_runs(occupied: np.ndarray) -> list[tuple[int, int]]:
    """Maximal runs [start, end) of False strictly between True entries."""
    idx = np.flatnonzero(occupied)
    runs = []
    for a, b in zip(idx[:-1], idx[1:]):
        if b - a > 1:
            runs.append((int(a) + 1, int(b)))
    return runs


def _guillotine(grid: np.ndarray, box, cost, out: list) -> None:
    """Split ``box`` (tight, tile units) at the empty row/column band that saves most cost."""
    x0, y0, x1, y1 = box
    sub = grid[y0:y1, x0:x1]
    best = None
    for axis in (0, 1):  # 0: empty row bands (cut horizontally), 1: empty column bands
        occupied = sub.any(axis=1 - axis)
        for r0, r1 in _empty_runs(occupied):
            if axis == 0:
                a = _tight(grid, x0, y0, x1, y0 + r0)
                b = _tight(grid, x0, y0 + r1, x1, y1)
            else:
                a = _tight(grid, x0, y0, x0 + r0, y1)
                b = _tight(grid, x0 + r1, y0, x1, y1)
            if a is None or b is None:
                continue
            gain = cost(box) - cost(a) - cost(b)
            if gain > 0 and (best is None or gain > best[0]):
                best = (gain, a, b)
    if best is None:
        out.append(box)
        return
    _guillotine(grid, best[1], cost, out)
    _guillotine(grid, best[2], cost, out)


def _overlap(a, b) -> bool:
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def plan_rects(grid: np.ndarray, tile: int, overhead_px: int = DEFAULT_REGION_OVERHEAD_PX,
               max_regions: int = DEFAULT_MAX_REGIONS) -> list[tuple[int, int, int, int]]:
    """Disjoint tile-unit boxes covering every occupied tile.

    Cost-based guillotine partition (cuts only through empty bands, so regions
    never overlap and always hug the content), then, if over ``max_regions``,
    greedy least-extra-area merging.  Overlapping boxes are always merged:
    semi-transparent pixels must never be blended twice.
    """
    root = _tight(grid, 0, 0, grid.shape[1], grid.shape[0])
    if root is None:
        return []
    px = tile * tile

    def cost(b):
        return (b[2] - b[0]) * (b[3] - b[1]) * px + overhead_px

    def union(a, b):
        return (min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3]))

    boxes: list = []
    _guillotine(grid, root, cost, boxes)
    while len(boxes) > 1:
        pair = None
        for i in range(len(boxes)):
            for j in range(i + 1, len(boxes)):
                if _overlap(boxes[i], boxes[j]):
                    pair = (i, j)
                    break
            if pair:
                break
        if pair is None:
            if len(boxes) <= max_regions:
                break
            best = None
            for i in range(len(boxes)):
                for j in range(i + 1, len(boxes)):
                    u = union(boxes[i], boxes[j])
                    delta = cost(u) - cost(boxes[i]) - cost(boxes[j])
                    if best is None or delta < best[0]:
                        best = (delta, i, j)
            pair = best[1:]
        i, j = pair
        u = union(boxes[i], boxes[j])
        boxes = [b for k, b in enumerate(boxes) if k not in (i, j)] + [u]
    return boxes


def _align_even(v: int, up: bool) -> int:
    return (v + (v & 1)) if up else (v - (v & 1))


def to_pixel_regions(boxes: Sequence[tuple[int, int, int, int]], tile: int, canvas_w: int,
                     canvas_h: int) -> list[Region]:
    """Tile boxes -> even-aligned pixel regions clipped to the canvas (YUV420 safe)."""
    out = []
    for gx0, gy0, gx1, gy1 in boxes:
        x0, y0 = _align_even(gx0 * tile, False), _align_even(gy0 * tile, False)
        x1 = min(canvas_w, _align_even(gx1 * tile, True))
        y1 = min(canvas_h, _align_even(gy1 * tile, True))
        if x1 > x0 and y1 > y0:
            out.append(Region(x0, y0, x1 - x0, y1 - y0))
    return out


def _shelf(regions: Sequence[Region], width_limit: int):
    order = sorted(regions, key=lambda r: (-r.h, -r.w))
    cells: list[AtlasCell] = []
    shelf_y = shelf_h = cur_x = used_w = 0
    for r in order:
        if cur_x + r.w > width_limit:
            shelf_y += shelf_h
            shelf_h = cur_x = 0
        cells.append(AtlasCell(r, cur_x, shelf_y))
        cur_x += r.w
        shelf_h = max(shelf_h, r.h)
        used_w = max(used_w, cur_x)
    return cells, _align_even(used_w, True), _align_even(shelf_y + shelf_h, True)


def pack_atlas(regions: Sequence[Region], max_width: int = DEFAULT_ATLAS_WIDTH) -> tuple[list[AtlasCell], int, int]:
    """Shelf-pack regions into one atlas (even-aligned cells); tries several widths, keeps the smallest."""
    widest = max(r.w for r in regions)
    best = None
    for limit in sorted({max(widest, v) for v in (1024, 1536, max_width, 2560, 3072, 3840)}):
        cells, aw, ah = _shelf(regions, limit)
        if best is None or aw * ah < best[1] * best[2]:
            best = (cells, aw, ah)
    return best


def plan_from_mask(mask: np.ndarray, *, tile: int = DEFAULT_TILE, margin_px: int = DEFAULT_MARGIN_PX,
                   overhead_px: int = DEFAULT_REGION_OVERHEAD_PX, max_regions: int = DEFAULT_MAX_REGIONS,
                   atlas_width: int = DEFAULT_ATLAS_WIDTH) -> RoiPlan | None:
    """Plan ROI regions from a union alpha mask.  None if the HUD is empty."""
    h, w = mask.shape
    grid = occupancy_grid(mask, tile, margin_px)
    boxes = plan_rects(grid, tile, overhead_px, max_regions)
    regions = to_pixel_regions(boxes, tile, w, h)
    if not regions:
        return None
    cells, aw, ah = pack_atlas(regions, atlas_width)
    return RoiPlan(w, h, tile, tuple(cells), aw, ah)


def coverage_mask(plan: RoiPlan) -> np.ndarray:
    m = np.zeros((plan.canvas_h, plan.canvas_w), dtype=bool)
    for r in plan.regions:
        m[r.y:r.y2, r.x:r.x2] = True
    return m


def uncovered_alpha_pixels(plan: RoiPlan, alpha: np.ndarray, covered: np.ndarray | None = None) -> int:
    """Number of pixels with alpha > 0 outside every region (must be 0)."""
    if covered is None:
        covered = coverage_mask(plan)
    return int(np.count_nonzero((alpha > 0) & ~covered))


def pack_into_atlas(plan: RoiPlan, frame_rgba: np.ndarray, atlas_rgba: np.ndarray) -> None:
    """Copy every region of a full-canvas HxWx4 frame into the (preallocated, zeroed) atlas."""
    for c in plan.cells:
        r = c.region
        atlas_rgba[c.ay:c.ay + r.h, c.ax:c.ax + r.w] = frame_rgba[r.y:r.y2, r.x:r.x2]


# ---------------------------------------------------------------------------
# FFmpeg filter graph
# ---------------------------------------------------------------------------

#: RGBA -> yuva420p10le exactly as FFmpeg's auto-inserted scaler does for the
#: HLG BT.2020nc full-range main video (verified bit-exact in CPU P0.4).
ATLAS_CONVERT = "scale=in_range=full:out_range=full:out_color_matrix=bt2020:flags=bicubic,format=yuva420p10le"


def build_roi_filter(plan: RoiPlan, *, base_label: str = "base", overlay_input: str = "1:v",
                     out_label: str = "vtemp", convert_atlas_once: bool = True) -> str:
    """Filter graph fragment: atlas input -> N crops -> N overlays on ``base_label``.

    ``convert_atlas_once`` converts the small atlas a single time and crops the
    planar result; otherwise each region is cropped (RGBA) and converted alone.
    """
    n = len(plan.cells)
    parts = []
    src = f"[{overlay_input}]setpts=PTS-STARTPTS"
    if convert_atlas_once:
        src += "," + ATLAS_CONVERT
    labels = [f"r{i}" for i in range(n)]
    if n == 1:
        parts.append(f"{src}[atl]")
        split_in = "atl"
        parts.append(f"[{split_in}]" + _crop(plan.cells[0], convert_atlas_once) + f"[{labels[0]}]")
    else:
        parts.append(f"{src},split={n}" + "".join(f"[s{i}]" for i in range(n)))
        for i, c in enumerate(plan.cells):
            parts.append(f"[s{i}]" + _crop(c, convert_atlas_once) + f"[{labels[i]}]")
    prev = base_label
    for i, c in enumerate(plan.cells):
        last = i == n - 1
        out = out_label if last else f"o{i}"
        parts.append(f"[{prev}][{labels[i]}]overlay={c.region.x}:{c.region.y}:shortest=1:format=yuv420p10[{out}]")
        prev = out
    return ";".join(parts)


def _crop(cell: AtlasCell, converted: bool) -> str:
    r = cell.region
    s = f"crop={r.w}:{r.h}:{cell.ax}:{cell.ay}"
    return s if converted else s + "," + ATLAS_CONVERT
