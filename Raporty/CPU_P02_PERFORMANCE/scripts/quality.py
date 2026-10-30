"""SSIM/PSNR of an encoded no-HUD clip against the source frames it came from.

Usage: quality.py <encoded.mp4> [--frames N] [--start-frame S]
Prints JSON; also writes <encoded>.quality.json.
"""
import argparse
import json
import re
import subprocess

FF = r"C:\_DEV\SportCamHUD\runtime\common\ffmpeg\ffmpeg.exe"
VIDEO = r"D:\GoPro\GX010370.MP4"

ap = argparse.ArgumentParser()
ap.add_argument("enc")
ap.add_argument("--frames", type=int, default=150)
ap.add_argument("--start-frame", type=int, default=900)
a = ap.parse_args()
ss = f"{a.start_frame * 1001 / 30000:.9f}"
cmd = [FF, "-hide_banner", "-nostats", "-noautorotate", "-i", a.enc,
       "-noautorotate", "-ss", ss, "-i", VIDEO, "-frames:v", str(a.frames),
       "-lavfi", "[0:v]format=yuv420p10le[a];[1:v]format=yuv420p10le[b];"
                 "[a]split[a1][a2];[b]split[b1][b2];[a1][b1]ssim;[a2][b2]psnr",
       "-f", "null", "-"]
r = subprocess.run(cmd, capture_output=True, text=True)
out = {"enc": a.enc}
m = re.search(r"SSIM Y:([\d.]+).*All:([\d.]+)", r.stderr)
if m:
    out["ssim_y"], out["ssim_all"] = float(m[1]), float(m[2])
m = re.search(r"PSNR y:([\d.]+).*average:([\d.]+)", r.stderr)
if m:
    out["psnr_y"], out["psnr_avg"] = float(m[1]), float(m[2])
out["returncode"] = r.returncode
if "ssim_all" not in out:
    out["stderr_tail"] = r.stderr[-600:]
json.dump(out, open(a.enc + ".quality.json", "w"), indent=1)
print(json.dumps(out))
