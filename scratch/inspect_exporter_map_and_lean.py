import re

content = open("src/ffmpeg/amd_native_exporter.py", encoding="utf-8").read()

print("--- SEARCH FOR MAP RENDERING IN EXPORTER ---")
for line_no, line in enumerate(content.splitlines(), 1):
    if any(k in line for k in ["render_map_", "gpu_map_upload", "upload_map", "telem_amd_set_map", "set_map_texture", "telem_amd_submit_map", "map_dst", "map_bounds"]):
        print(f"{line_no:4d}: {line}")

print("\n--- SEARCH FOR LEAN RENDERING IN EXPORTER ---")
for line_no, line in enumerate(content.splitlines(), 1):
    if any(k in line for k in ["lean_indicator", "lean_gpu", "telem_amd_set_lean", "telem_amd_submit_lean", "lean_roll"]):
        print(f"{line_no:4d}: {line}")
