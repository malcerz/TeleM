"""Test multi-region sub-window overlay pipeline for AMD.
"""

from __future__ import annotations

import subprocess, shutil, time

ffmpeg = shutil.which('ffmpeg') or 'ffmpeg'

# Top region: 1000x200 at (50, 50) -> 0.8 MB
# Bottom region: 3840x400 at (0, 1760) -> 6.1 MB
# Stacked height: 200 + 400 = 600px -> 3840x600 = 9.2 MB (vs 31.6 MB full 4K)
top_w, top_h, top_x, top_y = 1000, 200, 50, 50
bot_w, bot_h, bot_x, bot_y = 3840, 400, 0, 1760

pipe_w = 3840
pipe_h = top_h + bot_h # 600px

cmd = [
    ffmpeg, '-hide_banner', '-y',
    '-hwaccel', 'd3d11va', '-i', 'Video/GX020079.mp4',
    '-f', 'rawvideo', '-pix_fmt', 'rgba', '-s', f'{pipe_w}x{pipe_h}', '-r', '30', '-i', 'pipe:0',
    '-filter_complex', (
        f'[0:v]scale=3840:2160[base];'
        f'[1:v]crop={top_w}:{top_h}:0:0,setpts=PTS-STARTPTS,format=rgba[ov1];'
        f'[1:v]crop={bot_w}:{bot_h}:0:{top_h},setpts=PTS-STARTPTS,format=rgba[ov2];'
        f'[base][ov1]overlay={top_x}:{top_y}[tmp];'
        f'[tmp][ov2]overlay={bot_x}:{bot_y}:shortest=1[vout]'
    ),
    '-map', '[vout]', '-c:v', 'hevc_amf', '-pix_fmt', 'nv12', '-f', 'null', '-'
]

p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
raw_frame = b'\x80\x00\x80\x80' * (pipe_w * pipe_h) # 9.2 MB per frame

t0 = time.perf_counter()
for _ in range(90): # 90 frames (3 seconds)
    p.stdin.write(raw_frame)
p.stdin.close()
p.wait()
dt = time.perf_counter() - t0

print('Return code:', p.returncode)
print(f'Processed 90 frames in {dt:.2f} s ({90/dt:.2f} FPS)')
