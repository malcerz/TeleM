import subprocess

ffmpeg_exe = "C:\\temp\\ffmpeg\\ffmpeg.exe"
video_file = "F:\\_DEV\\TeleM\\Video\\GX020079.MP4"

# Test A: -hwaccel cuda -autorotate
cmd_a = [
    ffmpeg_exe, "-y", "-hwaccel", "cuda", "-autorotate",
    "-i", video_file,
    "-f", "lavfi", "-i", "color=c=red@0.5:s=3840x2160:d=1",
    "-filter_complex", "[0:v]null[base];[1:v]setpts=PTS-STARTPTS,format=rgba[ov];[base][ov]overlay=0:0:shortest=1[v]",
    "-map", "[v]", "-c:v", "hevc_nvenc", "-frames:v", "5",
    "-f", "null", "-"
]

print("Running Test A (-autorotate)...")
res_a = subprocess.run(cmd_a, capture_output=True, text=True)
print("Return code A:", res_a.returncode)
print("Stderr A snippet:", res_a.stderr[-800:])
