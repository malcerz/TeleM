import os
import sys
import subprocess
import json

def verify(out_path, name):
    if not os.path.exists(out_path):
        print(f"[{name}] FAIL: Output file does not exist!")
        return False
        
    try:
        cmd = ["ffprobe", "-v", "error", "-show_streams", "-of", "json", out_path]
        out = subprocess.check_output(cmd).decode("utf-8")
        meta = json.loads(out)
    except Exception as e:
        print(f"[{name}] FAIL to read with ffprobe: {e}")
        return False
        
    frames = 0
    fps = 0
    audio = False
    
    for s in meta.get("streams", []):
        if s.get("codec_type") == "video":
            nb = s.get("nb_frames")
            if not nb: nb = s.get("tags", {}).get("NUMBER_OF_FRAMES-eng", 0)
            if not nb: nb = s.get("tags", {}).get("NUMBER_OF_FRAMES", 0)
            frames = int(nb) if nb else 0
            r_fr = s.get("r_frame_rate", "0/1")
            num, den = map(int, r_fr.split("/"))
            fps = num/den if den != 0 else 0
        elif s.get("codec_type") == "audio":
            audio = True
            
    print(f"[{name}] RESULT: {frames} frames | {fps} FPS | Audio: {audio}")
    if frames < 100:
        print(f"[{name}] FAIL: Too few frames!")
        return False
    else:
        print(f"[{name}] PASS")
        return True

if __name__ == '__main__':
    direct_ok = verify(r"scratch\amd_real_direct.mp4", "DIRECT")
    queue_ok = verify(r"scratch\amd_real_queue.mp4", "QUEUE")
    if direct_ok and queue_ok:
        sys.exit(0)
    else:
        sys.exit(1)
