"""Per-HUD-region PSNR/SSIM of encoded exports vs the lossless reference.

One ffmpeg decode per encoded file; every region is cropped from both inputs
(-noautorotate: raw pixels, identical orientation) in yuv420p10le.
Usage: region_quality.py <dir> <ref.mp4> <tag> [<tag> ...]  -> <dir>/region_quality.json
"""
import json
import re
import subprocess
import sys

FF = r"C:\_DEV\SportCamHUD\runtime\common\ffmpeg\ffmpeg.exe"
S = 1.92  # preview (2000 px wide) -> 3840


def box(x0, y0, x1, y1):
    x0, y0, x1, y1 = (int(round(v * S)) // 2 * 2 for v in (x0, y0, x1, y1))
    return x0, y0, x1 - x0, y1 - y0


# The stored video is rotated 180 deg (display matrix); regions are given in the
# displayed orientation and mirrored for the raw stored frame.
DISPLAY_REGIONS = {
    "digits_text_topleft": (50, 20, 260, 130),
    "bar_distance": (390, 55, 1610, 140),
    "bar_power": (740, 1040, 1260, 1120),
    "map_and_track": (22, 164, 323, 464),
    "compass": (1780, 260, 1960, 440),
    "speed_gauge": (820, 840, 1180, 1040),
    "chart_cadence": (150, 900, 660, 1105),
    "chart_hr": (1330, 900, 1840, 1105),
    "battery_digits_bar": (1700, 15, 1960, 105),
    "full_frame": (0, 0, 2000, 1125),
}


def raw_box(name):
    x0, y0, x1, y1 = DISPLAY_REGIONS[name]
    if name == "full_frame":
        return 0, 0, 3840, 2160
    w, h = x1 - x0, y1 - y0
    X0, Y0, X1, Y1 = 2000 - x1, 1125 - y1, 2000 - x0, 1125 - y0
    return box(X0, Y0, X1, Y1)


def main():
    out_dir, ref, tags = sys.argv[1], sys.argv[2], sys.argv[3:]
    results = {}
    for tag in tags:
        enc = f"{out_dir}/{tag}.mp4"
        parts, labels = [], []
        n = len(DISPLAY_REGIONS)
        parts.append(f"[0:v]format=yuv420p10le,split={n}" + "".join(f"[a{i}]" for i in range(n)))
        parts.append(f"[1:v]format=yuv420p10le,split={n}" + "".join(f"[b{i}]" for i in range(n)))
        for i, name in enumerate(DISPLAY_REGIONS):
            x, y, w, h = raw_box(name)
            parts.append(f"[a{i}]crop={w}:{h}:{x}:{y},split=2[ca{i}s][ca{i}p]")
            parts.append(f"[b{i}]crop={w}:{h}:{x}:{y},split=2[cb{i}s][cb{i}p]")
            parts.append(f"[ca{i}s][cb{i}s]ssim@s{i}[os{i}]")
            parts.append(f"[ca{i}p][cb{i}p]psnr@p{i}[op{i}]")
        fc = ";".join(parts)
        maps = []
        for i in range(n):
            maps += ["-map", f"[os{i}]", "-map", f"[op{i}]"]
        cmd = [FF, "-hide_banner", "-nostats", "-noautorotate", "-i", enc, "-noautorotate", "-i", ref,
               "-filter_complex", fc, *maps, "-f", "null", "-"]
        r = subprocess.run(cmd, capture_output=True, text=True)
        res = {}
        for i, name in enumerate(DISPLAY_REGIONS):
            m = re.search(rf"ssim@s{i} @ [0-9a-fx]+\] SSIM Y:([\d.]+).*All:([\d.]+)", r.stderr)
            p = re.search(rf"psnr@p{i} @ [0-9a-fx]+\] PSNR y:([\d.]+).*average:([\d.]+|inf)", r.stderr)
            res[name] = {"ssim_y": float(m[1]) if m else None,
                         "psnr_y": float(p[1]) if p else None}
        if r.returncode != 0:
            res["_error"] = r.stderr[-500:]
        results[tag] = res
        print(tag, json.dumps({k: (v["psnr_y"], v["ssim_y"]) for k, v in res.items() if isinstance(v, dict) and "psnr_y" in v}))
    json.dump(results, open(f"{out_dir}/region_quality.json", "w"), indent=1)


if __name__ == "__main__":
    main()
