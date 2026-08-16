"""ETAP 5K — isolate the value-text rendering mismatch.

Renders the same cadence value text two ways on a transparent background and
compares pixel-by-pixel:
  A) the way the CPU full-chart path does it: draw.text((px, py), ...) directly
     on a 1160x511 transparent image (px/py from the chart layout).
  B) the way _render_value_text_tile produces the tile, pasted at its local
     offset on the same transparent image.
If A != B the text tile render itself differs from the full-image render.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PIL import Image, ImageDraw
from src.indicators.chart import _render_value_text_tile
from src.indicators.helpers import load_font, s, parse_hex_color


def main() -> int:
    layout = json.loads((ROOT / "def_layout.json").read_text(encoding="utf-8"))
    cfg = layout["indicators"]["fit_cadence_text"]
    canvas_w, canvas_h = 3840, 2160
    min_dim = min(canvas_w, canvas_h)
    chart_w = 1152
    fs = 30
    font_path = str(ROOT / "include" / "mpv")
    font = load_font(font_path, fs)
    outline = 2
    tox = int(round(cfg.get("text_offset_x", 0.0) * chart_w))
    toy = int(round(cfg.get("text_offset_y", 0.0) * 449))
    text_color_rgb = parse_hex_color(cfg.get("text_color", "#FFFFFF")) or (255, 255, 255)
    text_color = (text_color_rgb[0], text_color_rgb[1], text_color_rgb[2], 255)
    v_str = "85.0 rpm"

    print(f"cfg: text_offset_x={cfg.get('text_offset_x')} text_offset_y={cfg.get('text_offset_y')} "
          f"text_color={cfg.get('text_color')} font_size={cfg.get('font_size')}")
    print(f"tox={tox} toy={toy} fs={fs} outline={outline} text_color={text_color}")

    # A) full-image CPU-style render
    img_a = Image.new("RGBA", (1160, 511), (0, 0, 0, 0))
    da = ImageDraw.Draw(img_a)
    vw = da.textbbox((0, 0), v_str, font=font)[2]
    px = chart_w - vw + tox
    py = toy
    da.text((px, py), v_str, font=font, fill=text_color,
            stroke_width=outline, stroke_fill=(0, 0, 0, 255))
    print(f"CPU draw origin: ({px},{py}) vw={vw}")

    # B) tile via _render_value_text_tile
    tile, lx, ly = _render_value_text_tile(v_str, font, text_color, outline, chart_w, tox, toy)
    print(f"tile size={tile.size} local=({lx},{ly})")
    img_b = Image.new("RGBA", (1160, 511), (0, 0, 0, 0))
    img_b.paste(tile, (lx, ly), tile)

    a = np.asarray(img_a, dtype=np.int16)
    b = np.asarray(img_b, dtype=np.int16)
    d = np.abs(a - b)
    m = d.max(axis=2) > 0
    print(f"diff_px={int(m.sum())} MAE={d.mean():.3f} MAX={d.max()}")
    if int(m.sum()):
        ys, xs = np.where(m)
        for y, x in zip(ys[:6], xs[:6]):
            print(f"  ({x},{y}) A={tuple(a[y, x])} B={tuple(b[y, x])}")

    # C) Now draw the SAME text on the tile at origin (0,0) instead of (-sl,-st)
    #    to see whether the origin affects rasterization.
    probe = ImageDraw.Draw(Image.new("RGBA", (1, 1), (0, 0, 0, 0)))
    sl, st, sr, sb = probe.textbbox((0, 0), v_str, font=font, stroke_width=outline)
    print(f"stroke_bbox=({sl},{st},{sr},{sb}) -> expected origin (-sl,-st)=({-sl},{-st})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
