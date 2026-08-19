import sys
import time
import statistics
sys.path.insert(0, ".")
from PIL import Image, ImageDraw
from src.ffmpeg.amd_native_exporter import (
    _rendered_bbox_union,
    _tight_alpha_bbox_from_candidate,
    _cluster_above_bboxes,
)

w, h = 3840, 2160
img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
draw = ImageDraw.Draw(img)
# Element A at top-left
draw.rectangle((50, 40, 250, 100), fill=(255, 0, 0, 255))
# Element B at bottom-right
draw.rectangle((3500, 2000, 3750, 2100), fill=(0, 255, 0, 255))

bboxes = {
    "elem_tl": (50, 40, 200, 60),
    "elem_br": (3500, 2000, 250, 100),
}

# 1. Measure BEFORE (single union bbox)
N = 100
before_times = []
before_cand_pixels = 0
before_scanned_pixels = 0
for _ in range(N):
    t0 = time.perf_counter()
    cand = _rendered_bbox_union(bboxes, w, h, pad=64)
    cand_img = img.crop((cand[0], cand[1], cand[0] + cand[2], cand[1] + cand[3]))
    local_alpha = cand_img.getchannel("A").getbbox()
    final_img = cand_img.crop(local_alpha)
    final_bytes = final_img.tobytes("raw", "RGBA")
    t1 = time.perf_counter()
    before_times.append((t1 - t0) * 1000.0)
    before_cand_pixels = cand[2] * cand[3]
    before_scanned_pixels = cand[2] * cand[3]

# 2. Measure AFTER (multi-region)
after_times = []
after_cand_pixels = 0
after_scanned_pixels = 0
after_uploaded_pixels = 0
for _ in range(N):
    t0 = time.perf_counter()
    clusters = _cluster_above_bboxes(bboxes, w, h, pad=16, merge_dist=32, max_regions=16)
    regions = []
    c_pixels = 0
    for cx, cy, cw, ch in clusters:
        c_pixels += cw * ch
        cand_img = img.crop((cx, cy, cx + cw, cy + ch))
        local_alpha = cand_img.getchannel("A").getbbox()
        if local_alpha:
            r_img = cand_img.crop(local_alpha)
            r_bytes = r_img.tobytes("raw", "RGBA")
            regions.append(r_img)
    t1 = time.perf_counter()
    after_times.append((t1 - t0) * 1000.0)
    after_cand_pixels = c_pixels
    after_scanned_pixels = c_pixels
    after_uploaded_pixels = sum(r.width * r.height for r in regions)

print("=== SPARSE DISTANT BENCHMARK (4K: 3840x2160) ===")
print(f"BEFORE (Single Union):")
print(f"  Candidate Box:   {cand}")
print(f"  Candidate Pixels: {before_cand_pixels:,} ({before_cand_pixels*4/(1024*1024):.2f} MB)")
print(f"  Median Time:     {statistics.median(before_times):.3f} ms")
print(f"  Avg Time:        {statistics.mean(before_times):.3f} ms")
print(f"  P95 Time:        {statistics.quantiles(before_times, n=20)[18]:.3f} ms")

print(f"\nAFTER (Multi-Region):")
print(f"  Regions Count:   {len(clusters)}")
print(f"  Candidate Pixels: {after_cand_pixels:,} ({after_cand_pixels*4/(1024*1024):.2f} MB)")
print(f"  Uploaded Pixels:  {after_uploaded_pixels:,} ({after_uploaded_pixels*4/(1024*1024):.2f} MB)")
print(f"  Median Time:     {statistics.median(after_times):.3f} ms")
print(f"  Avg Time:        {statistics.mean(after_times):.3f} ms")
print(f"  P95 Time:        {statistics.quantiles(after_times, n=20)[18]:.3f} ms")

speedup = statistics.median(before_times) / statistics.median(after_times)
pixel_red = 100.0 * (1.0 - after_cand_pixels / before_cand_pixels)
print(f"\nSPEEDUP:           {speedup:.2f}x faster ({statistics.median(before_times):.3f} ms -> {statistics.median(after_times):.3f} ms)")
print(f"PIXEL REDUCTION:   {pixel_red:.2f}% reduction")
