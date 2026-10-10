import os
import sys
import subprocess
import json
import time

def verify(out_path, name):
    if not os.path.exists(out_path):
        print(f"[{name}] FAIL: Output file does not exist! ({out_path})")
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
            
    print(f"[{name}] RESULT: {frames} frames | {fps:.2f} FPS | Audio: {audio}")
    if frames < 100:
        print(f"[{name}] FAIL: Too few frames! Expected ~150, got {frames}")
        return False
    else:
        print(f"[{name}] PASS")
        return True

def run_export_mode(mode, output_path):
    print(f"\n--- RUNNING {mode.upper()} EXPORT ---")
    if os.path.exists(output_path):
        os.remove(output_path)
        
    cmd = [
        sys.executable, "BikeRideHUD.py",
        "--test-amd-export",
        "--mode", mode,
        "--video", r"F:\GoPro\2026-09-25\GX010321.MP4",
        "--fit", r"F:\GoPro\2026-09-25\Poranna_jazda_na_rowerze.fit",
        "--frames", "800",
        "--output", output_path
    ]
    
    env = os.environ.copy()
    env["PYTHONPATH"] = "."
    
    t0 = time.time()
    proc = subprocess.Popen(cmd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    
    for line in iter(proc.stdout.readline, b''):
        l = line.decode('utf-8', errors='replace').rstrip()
        try:
            print(f"  {l}")
        except UnicodeEncodeError:
            print(f"  {l.encode('ascii', 'replace').decode('ascii')}")
            
    proc.wait()
    duration = time.time() - t0
    print(f"[{mode.upper()}] Process exited with code {proc.returncode} in {duration:.2f}s")
    
    if proc.returncode != 0:
        return False
        
    return verify(output_path, mode.upper())

if __name__ == '__main__':
    direct_out = os.path.abspath(r"scratch\amd_bench_direct.mp4")
    queue_out = os.path.abspath(r"scratch\amd_bench_queue.mp4")
    
    direct_ok = run_export_mode("direct", direct_out)
    queue_ok = run_export_mode("queue", queue_out)
    
    if direct_ok and queue_ok:
        print("\nOVERALL: FULL PASS")
        sys.exit(0)
    else:
        print("\nOVERALL: FAIL")
        sys.exit(1)
