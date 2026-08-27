import json
import sys
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.indicators.text import _render_text_indicator, clear_text_cache, get_text_cache_stats

layout = json.load(open("def_layout.json", encoding="utf-8"))
w, h = 3840, 2160
font_path = "arial.ttf"

print("=" * 90)
print("MICROBENCHMARK: TEXT INDICATORS (1000 calls per widget)")
print("=" * 90)

widgets = [
    ("iso_text", [100, 200, 400, 800, 1600, 3200, 6400] * 150),
    ("exposure_text", ["1/120", "1/240", "1/500", "1/1000", "1/2000"] * 200),
    ("temp_text", [20, 21, 22, 23, 24, 25] * 170),
]

for key, val_sequence in widgets:
    cfg = layout["indicators"].get(key, {})
    clear_text_cache()
    
    # 1. Cold run (1000 calls)
    t0 = time.perf_counter()
    for v in val_sequence[:1000]:
        _render_text_indicator(
            canvas_w=w, canvas_h=h, layout=layout, font_path=font_path,
            key=key, value=v if isinstance(v, (int, float)) else None, unit="",
            label=cfg.get("label", ""), cfg=cfg, min_dim=2160, outline=2, fs=28,
            font=None, val_min=0, val_max=1000, ticks=0, thickness=2, size_px=100, ss=1,
            formatted_val=str(v)
        )
    t_total = (time.perf_counter() - t0) * 1000.0
    stats = get_text_cache_stats()
    
    print(f"{key:<18}: Total Time={t_total:.3f} ms, Avg per call={t_total/1000.0:.4f} ms, "
          f"Hits={stats['hits']}, Misses={stats['misses']}, Hit Rate={stats['hit_rate_pct']:.1f}%")

# Combined realistic sequence (simulating 1000 frames rendering all 3 text widgets)
clear_text_cache()
t0 = time.perf_counter()
for i in range(1000):
    iso_val = [100, 200, 400, 800][(i // 100) % 4]
    exp_val = ["1/240", "1/500", "1/1000"][(i // 50) % 3]
    temp_val = [23, 24, 25][(i // 300) % 3]
    
    _render_text_indicator(
        canvas_w=w, canvas_h=h, layout=layout, font_path=font_path,
        key="iso_text", value=iso_val, unit="", label="ISO",
        cfg=layout["indicators"].get("iso_text", {}), min_dim=2160, outline=2, fs=28,
        font=None, val_min=0, val_max=6400, ticks=0, thickness=2, size_px=100, ss=1,
        formatted_val=f"ISO: {iso_val}"
    )
    _render_text_indicator(
        canvas_w=w, canvas_h=h, layout=layout, font_path=font_path,
        key="exposure_text", value=None, unit="", label="EXP",
        cfg=layout["indicators"].get("exposure_text", {}), min_dim=2160, outline=2, fs=28,
        font=None, val_min=0, val_max=1, ticks=0, thickness=2, size_px=100, ss=1,
        formatted_val=f"EXP: {exp_val}"
    )
    _render_text_indicator(
        canvas_w=w, canvas_h=h, layout=layout, font_path=font_path,
        key="temp_text", value=temp_val, unit="°C", label="TEMP",
        cfg=layout["indicators"].get("temp_text", {}), min_dim=2160, outline=2, fs=28,
        font=None, val_min=0, val_max=100, ticks=0, thickness=2, size_px=100, ss=1,
        formatted_val=f"TEMP: {temp_val}°C"
    )

t_comb = (time.perf_counter() - t0) * 1000.0
stats_comb = get_text_cache_stats()
print(f"\nCOMBINED 3 Text Widgets (1000 frames = 3000 calls):")
print(f"  Total Time:   {t_comb:.3f} ms")
print(f"  Per Frame:    {t_comb/1000.0:.4f} ms ({t_comb/3000.0:.4f} ms per widget)")
print(f"  Cache Hits:   {stats_comb['hits']} / 3000 ({stats_comb['hit_rate_pct']:.2f}%)")
print(f"  Cache Misses: {stats_comb['misses']}")
