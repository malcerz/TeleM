"""
Prototype of Dirty Text Cache and Reusable ABOVE Canvas for ETAP 8Q.
Validates:
1. Pixel correctness against uncached render (100% byte-exact parity).
2. Performance speedup on above_compose.
3. Hit rate on slow-changing and identical texts.
4. None/zero lifecycle and 0 ghosting.
"""
import sys
import time
import copy
import statistics
from pathlib import Path
from collections import OrderedDict
from dataclasses import dataclass
from typing import Optional, Any
from PIL import Image, ImageDraw, ImageFont

root = Path("c:/_DEV/TeleM")
sys.path.insert(0, str(root))
sys.path.insert(0, str(root / "src"))

from src.indicators.helpers import s, load_font, parse_hex_color
from src.gui.layout_manager import normalize_layout
from src.ffmpeg.amd_native_exporter import _ordered_map_layout_parts
from scratch.measure_current_builder_baseline import setup_telemetry
from src.telemetry_precompute import build_telemetry_cache
from src.indicators.compositor import compose_overlay
from src.indicators.frame_data import build_active_fit_field_plan
from src.ffmpeg.worker_cache import _resolve_cache_value, init_worker


@dataclass(frozen=True)
class TextRasterKey:
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
    image: Image.Image
    width: int
    height: int


class AboveTextCache:
    def __init__(self, max_entries: int = 512):
        self.max_entries = max_entries
        self.cache: OrderedDict[TextRasterKey, TextRasterEntry] = OrderedDict()
        self.hits: dict[str, int] = {}
        self.misses: dict[str, int] = {}
        self.total_bytes: int = 0

    def clear(self):
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

    def put(self, key: TextRasterKey, entry: TextRasterEntry):
        if key in self.cache:
            self.cache.move_to_end(key)
            return
        # Evict if full
        while len(self.cache) >= self.max_entries:
            _, old_entry = self.cache.popitem(last=False)
            self.total_bytes -= old_entry.width * old_entry.height * 4
        self.cache[key] = entry
        self.total_bytes += entry.width * entry.height * 4

    def stats(self):
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


# Global instance
_ABOVE_TEXT_CACHE = AboveTextCache()
_ABOVE_REUSABLE_CANVAS: Optional[tuple[Image.Image, dict[str, tuple[int, int, int, int]]]] = None


def render_above_indicator_cached(
    canvas_w: int,
    canvas_h: int,
    ind_cfg: dict,
    key: str,
    txt: str,
    font_path: str,
    cache: AboveTextCache,
) -> tuple[Optional[Image.Image], int, int]:
    """Render or retrieve cached rotated raster of a text indicator."""
    min_dim = min(canvas_w, canvas_h)
    fs_val = ind_cfg.get("font_size") if "font_size" in ind_cfg else ind_cfg.get("size", 0.02)
    fs = max(8, s(fs_val, min_dim))
    outline_raw = int(ind_cfg.get("text_outline", 3))
    outline = max(0, int(round(outline_raw * min_dim / 1000)))
    text_color = parse_hex_color(ind_cfg.get("text_color", "#FFFFFF")) or (255, 255, 255)
    color_rgba = (text_color[0], text_color[1], text_color[2], 255)
    outline_rgba = (0, 0, 0, 255)
    rotation = int(ind_cfg.get("rotation", 0)) % 360

    cache_key = TextRasterKey(
        key=key, text=txt, font_path=font_path, font_size=fs,
        color=color_rgba, outline_width=outline, outline_color=outline_rgba,
        rotation=rotation, canvas_w=canvas_w, canvas_h=canvas_h,
    )

    cached_entry = cache.get(cache_key)
    if cached_entry is not None:
        return cached_entry.image, cached_entry.width, cached_entry.height

    # Render once
    font = load_font(font_path, fs)
    txt_w = int(font.getlength(txt) + outline * 4)
    tmp = Image.new("RGBA", (txt_w, int(fs * 2)), (0, 0, 0, 0))
    draw = ImageDraw.Draw(tmp)
    draw.text(
        (outline, 0), txt, font=font,
        fill=color_rgba,
        stroke_width=outline, stroke_fill=outline_rgba,
    )
    bbox = tmp.getbbox()
    if not bbox:
        return None, 0, 0

    cropped = tmp.crop(bbox)
    if rotation == 90:
        res = cropped.transpose(Image.Transpose.ROTATE_90)
    elif rotation == 180:
        res = cropped.transpose(Image.Transpose.ROTATE_180)
    elif rotation == 270:
        res = cropped.transpose(Image.Transpose.ROTATE_270)
    else:
        res = cropped

    entry = TextRasterEntry(image=res, width=res.width, height=res.height)
    cache.put(cache_key, entry)
    return res, res.width, res.height


def compose_above_overlay_fast(
    canvas_w: int,
    canvas_h: int,
    layout: dict[str, Any],
    font_path: str,
    f_rec: dict[str, Any],
    _bboxes: dict[str, tuple[int, int, int, int]],
    cache: AboveTextCache,
    reuse_canvas: bool = True,
    timing_dict: Optional[dict] = None,
) -> Image.Image:
    """Fast compose for ABOVE overlay using dedicated reusable canvas + dirty text cache."""
    global _ABOVE_REUSABLE_CANVAS

    t_start = time.perf_counter()
    t_canvas_start = time.perf_counter()

    if reuse_canvas:
        if _ABOVE_REUSABLE_CANVAS is None or _ABOVE_REUSABLE_CANVAS["img"].size != (canvas_w, canvas_h):
            img = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))
            _ABOVE_REUSABLE_CANVAS = {
                "img": img,
                "prev_bboxes": {},
                "is_clean": True,
            }
        
        img = _ABOVE_REUSABLE_CANVAS["img"]
        prev_bboxes = _ABOVE_REUSABLE_CANVAS["prev_bboxes"]
        
        if prev_bboxes:
            pad = 40
            for bx, by, bw, bh in prev_bboxes.values():
                x1 = max(0, bx - pad)
                y1 = max(0, by - pad)
                x2 = min(canvas_w, bx + bw + pad)
                y2 = min(canvas_h, by + bh + pad)
                img.paste((0, 0, 0, 0), (x1, y1, x2, y2))
            prev_bboxes.clear()
            _ABOVE_REUSABLE_CANVAS["is_clean"] = True
        elif not _ABOVE_REUSABLE_CANVAS["is_clean"]:
            img.paste((0, 0, 0, 0), (0, 0, canvas_w, canvas_h))
            _ABOVE_REUSABLE_CANVAS["is_clean"] = True
    else:
        img = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))
        prev_bboxes = None

    t_canvas_ms = (time.perf_counter() - t_canvas_start) * 1000.0

    t_lookup_ms = 0.0
    t_hit_ms = 0.0
    t_miss_ms = 0.0
    t_paste_ms = 0.0

    extra_ind = f_rec.get("extra_indicators", {})

    for key, ind_cfg in layout.get("indicators", {}).items():
        if not ind_cfg or not ind_cfg.get("enabled", True):
            continue

        known = extra_ind.get(key)
        val = known[0] if known else None
        unit = known[1] if known else ind_cfg.get("unit", "")
        label = known[2] if known else ind_cfg.get("label", key)

        if val is None:
            continue

        decimals = int(ind_cfg.get("decimals", 0))
        val_str = f"{val:.{decimals}f}"
        show_units = ind_cfg.get("show_units", True)
        if show_units and unit:
            txt = f"{label}: {val_str} {unit}" if label else f"{val_str} {unit}"
        elif label:
            txt = f"{label}: {val_str}"
        else:
            txt = val_str

        if not txt:
            continue

        t_lk0 = time.perf_counter()
        res, rw, rh = render_above_indicator_cached(
            canvas_w, canvas_h, ind_cfg, key, txt, font_path, cache
        )
        t_lk_ms = (time.perf_counter() - t_lk0) * 1000.0
        t_lookup_ms += t_lk_ms

        if res is not None:
            t_p0 = time.perf_counter()
            rotation = int(ind_cfg.get("rotation", 0)) % 360
            px_x = s(ind_cfg.get("x", 0.0), canvas_w)
            px_y = s(ind_cfg.get("y", 0.0), canvas_h)
            
            if rotation in (90, 270):
                center_x = px_x + rh // 2
                center_y = px_y + rw // 2
            else:
                center_x = px_x + rw // 2
                center_y = px_y + rh // 2

            paste_x = int(round(center_x - rw / 2.0))
            paste_y = int(round(center_y - rh / 2.0))

            img.paste(res, (paste_x, paste_y), res)
            _bboxes[key] = (paste_x, paste_y, rw, rh)
            t_paste_ms += (time.perf_counter() - t_p0) * 1000.0

    if prev_bboxes is not None and _bboxes:
        prev_bboxes.update(_bboxes)
        _ABOVE_REUSABLE_CANVAS["is_clean"] = False

    t_total_ms = (time.perf_counter() - t_start) * 1000.0
    if timing_dict is not None:
        timing_dict.update({
            "above_canvas_prepare": t_canvas_ms,
            "above_cache_lookup": t_lookup_ms,
            "above_cached_paste": t_paste_ms,
            "above_compose_total": t_total_ms,
        })

    return img


def main():
    print("=== TESTING FAST ABOVE COMPOSE & PIXEL PARITY ===")
    layout_raw = normalize_layout(root / "def_layout.json", 3840, 2160)
    below_layout, map_above_layout, after_keys = _ordered_map_layout_parts(layout_raw)
    
    # Enable battery and solar indicators for validation
    for k in ["fit_battery_pct_text", "fit_solar_pct_text"]:
        if k in map_above_layout.get("indicators", {}):
            map_above_layout["indicators"][k]["enabled"] = True

    tm = setup_telemetry("GX030120.MP4", "Popoludniowa_jazda_na_rowerze_solar_battery.fit")
    fit_field_plan = build_active_fit_field_plan(layout_raw, (tm.fit_data or {}).keys())

    init_worker(
        video_width=3840, video_height=2160, font_path="assets/Roboto-Bold.ttf",
        layout=layout_raw, field_samples=tm.fit_data or {},
        fit_data=tm.fit_data, gps_track=tm.get_gps_track_for_source("fit"),
        start_dt_utc=tm.start_dt_utc, tz_offset_hours=2.0,
        speed_samples=tm.speed_samples or [], track_samples=tm.track_samples or [],
        alt_samples=tm.alt_samples or [], target_fps=29.97,
    )

    cache = build_telemetry_cache(
        layout=layout_raw, base_dt=tm.start_dt_utc, tz_offset_hours=2.0,
        start_dt_utc=tm.start_dt_utc, speed_samples=tm.speed_samples or [],
        track_samples=tm.track_samples or [], alt_samples=tm.alt_samples or [],
        fit_data=tm.fit_data, chart_data={}, resolve_cache_value=_resolve_cache_value,
        fit_field_plan=fit_field_plan, total_frames=100, target_fps=29.97,
    )

    font_path = "assets/Roboto-Bold.ttf"
    _ABOVE_TEXT_CACHE.clear()

    # 1. Test pixel parity on 100 frames with active visible text
    diff_count = 0
    max_pixel_diff = 0
    t_uncached_list = []
    t_cached_list = []

    for f_idx in range(100):
        f_rec = cache.lookup(f_idx)
        # Ensure extra_indicators has visible test values
        extra = dict(f_rec.get("extra_indicators", {}))
        extra["fit_battery_pct_text"] = (77.0 if f_idx < 50 else 78.0, "%", "Bateria")
        extra["fit_solar_pct_text"] = (45.0 + (f_idx // 10), "%", "Solar")
        f_rec_test = dict(f_rec)
        f_rec_test["extra_indicators"] = extra

        # UNCACHED render
        t0 = time.perf_counter()
        old_bboxes = {}
        old_img = compose_overlay(
            canvas_w=3840, canvas_h=2160,
            layout=map_above_layout, font_path=font_path,
            _bboxes=old_bboxes, reuse_canvas=False,
            **f_rec_test,
        )
        t_uncached = (time.perf_counter() - t0) * 1000.0
        t_uncached_list.append(t_uncached)

        # CACHED fast render
        t0 = time.perf_counter()
        new_bboxes = {}
        subt = {}
        new_img = compose_above_overlay_fast(
            canvas_w=3840, canvas_h=2160,
            layout=map_above_layout, font_path=font_path,
            f_rec=f_rec_test, _bboxes=new_bboxes,
            cache=_ABOVE_TEXT_CACHE, reuse_canvas=True,
            timing_dict=subt,
        )
        t_cached = (time.perf_counter() - t0) * 1000.0
        t_cached_list.append(t_cached)

        # Compare pixel parity
        old_bytes = old_img.tobytes()
        new_bytes = new_img.tobytes()
        if old_bytes != new_bytes:
            diff_count += 1
            for b1, b2 in zip(old_bytes, new_bytes):
                d = abs(b1 - b2)
                if d > max_pixel_diff:
                    max_pixel_diff = d

    med_uncached = statistics.median(t_uncached_list)
    med_cached = statistics.median(t_cached_list)

    print(f"OLD UNCACHED above_compose median: {med_uncached:.3f} ms")
    print(f"NEW CACHED above_compose median:   {med_cached:.3f} ms")
    print(f"SPEEDUP: {med_uncached / med_cached:.2f}x faster!")
    print(f"Cache Stats: {_ABOVE_TEXT_CACHE.stats()}")
    print(f"\n--- PIXEL PARITY (100 frames) ---")
    print(f"Differing Frames: {diff_count} / 100")
    print(f"Max Pixel Diff:   {max_pixel_diff}")
    if diff_count == 0:
        print(">>> BYTE-EXACT PIXEL PARITY: PASS! <<<")
    else:
        print(">>> PIXEL PARITY: FAIL! <<<")

if __name__ == "__main__":
    main()
