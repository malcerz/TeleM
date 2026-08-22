import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import json
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from src.indicators.helpers import (
    resolve_indicator_font_path,
    resolve_font_file,
    load_font,
    FONT_CACHE,
    _FONT_PATH_CACHE,
)
from src.indicators.compositor import compose_overlay

print("==================================================")
print("ETAP 10H: SYSTEM FONT RESOLUTION & RENDER TEST")
print("==================================================")

test_fonts = ["default", "Comic Sans", "Digital-7", "Iona-u1", "__FONT_DOES_NOT_EXIST__"]

results = {}
for tf in test_fonts:
    raw_val = None if tf == "default" else tf
    resolved = resolve_indicator_font_path(raw_val, default_font_path="")
    p = Path(resolved) if resolved else None
    exists = p.is_file() if p else False
    suffix = p.suffix if p else ""

    try:
        if resolved:
            pil_font = ImageFont.truetype(resolved, size=32)
            pil_status = f"SUCCESS ({pil_font.getname()})"
        else:
            pil_font = ImageFont.load_default()
            pil_status = "DEFAULT"
    except Exception as e:
        pil_font = ImageFont.load_default()
        pil_status = f"FAILED: {e}"

    effective_font = load_font(resolved, 32)
    is_fallback = (resolved == "" or not exists)

    results[tf] = {
        "property_value": raw_val,
        "resolved_path": resolved,
        "exists": exists,
        "suffix": suffix,
        "pil_status": pil_status,
        "effective_font_type": type(effective_font).__name__,
        "is_fallback": is_fallback,
    }

for tf, r in results.items():
    print(f"\nFont Property: '{tf}'")
    for k, v in r.items():
        print(f"  {k:20}: {v}")

print("\n==================================================")
print("WIDGET RENDER TEST (Speed Gauge & Speed Text)")
print("==================================================")

def render_with_font(font_name: str, form: str = "text"):
    raw_font = "" if font_name == "default" else font_name
    key = "speed_text" if form == "text" else "speed_visual"
    cfg = {
        "x": 50.0, "y": 50.0, "size": 30.0, "font_size": 4.0,
        "font": raw_font, "enabled": True, "label": "SPEED",
        "unit": "km/h", "show_value": True, "show_units": True,
        "form": form,
    }
    layout = {
        "indicators": {key: cfg},
        "global": {"antialiasing": 1},
    }
    _bboxes = {}
    img = compose_overlay(
        600, 300, layout, font_path="",
        date_text="", time_text="",
        speed_value=28.6, distance_m=1000.0,
        _bboxes=_bboxes, reuse_canvas=False
    )
    return img

widget_renders = {}
for tf in ["default", "Comic Sans", "Digital-7", "Iona-u1"]:
    img = render_with_font(tf, form="text")
    out_p = Path(f"Raporty/WIDGET_TEST_{tf.replace(' ', '_')}.png")
    img.save(out_p)
    widget_renders[tf] = np.array(img)
    print(f"Rendered Speed Text with font '{tf}': saved to {out_p}")

print("\n=== WIDGET RASTER COMPARISONS ===")
for tf in ["Comic Sans", "Digital-7", "Iona-u1"]:
    diff = np.abs(widget_renders[tf].astype(np.int16) - widget_renders["default"].astype(np.int16)).max()
    print(f"Speed Text diff '{tf}' vs default: max diff = {diff} (Distinct: {diff > 0})")

diff_dig_iona = np.abs(widget_renders["Digital-7"].astype(np.int16) - widget_renders["Iona-u1"].astype(np.int16)).max()
print(f"Speed Text diff Digital-7 vs Iona-u1: max diff = {diff_dig_iona} (Distinct: {diff_dig_iona > 0})")

# Gauge test
print("\n=== SPEED GAUGE RENDER TEST ===")
gauge_renders = {}
for tf in ["default", "Comic Sans", "Digital-7", "Iona-u1"]:
    img = render_with_font(tf, form="gauge")
    out_p = Path(f"Raporty/GAUGE_TEST_{tf.replace(' ', '_')}.png")
    img.save(out_p)
    gauge_renders[tf] = np.array(img)
    print(f"Rendered Speed Gauge with font '{tf}': saved to {out_p}")

for tf in ["Comic Sans", "Digital-7", "Iona-u1"]:
    diff = np.abs(gauge_renders[tf].astype(np.int16) - gauge_renders["default"].astype(np.int16)).max()
    print(f"Speed Gauge diff '{tf}' vs default: max diff = {diff} (Distinct: {diff > 0})")

print("\n==================================================")
print("INVALIDATION SEQUENCE: Arial -> Digital-7 -> Iona-u1 -> Arial")
print("==================================================")
seq = ["Arial", "Digital-7", "Iona-u1", "Arial"]
seq_renders = [np.array(render_with_font(font_name, form="text")) for font_name in seq]

diff_arial1_arial2 = np.abs(seq_renders[0].astype(np.int16) - seq_renders[3].astype(np.int16)).max()
diff_arial1_dig = np.abs(seq_renders[0].astype(np.int16) - seq_renders[1].astype(np.int16)).max()
diff_dig_iona = np.abs(seq_renders[1].astype(np.int16) - seq_renders[2].astype(np.int16)).max()

print(f"Arial (first) == Arial (second): max diff = {diff_arial1_arial2} (Identical: {diff_arial1_arial2 == 0})")
print(f"Arial != Digital-7:              max diff = {diff_arial1_dig} (Distinct: {diff_arial1_dig > 0})")
print(f"Digital-7 != Iona-u1:            max diff = {diff_dig_iona} (Distinct: {diff_dig_iona > 0})")
