import sys
import subprocess

def run_test(video, fit, expect_pass):
    cmd = [sys.executable, "BikeRideHUD.py", "--test-sync-integrity", "--video", video, "--fit", fit]
    print(f"\nRunning: {' '.join(cmd)}")
    try:
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=15)
        out = res.stdout
        ret = res.returncode
    except subprocess.TimeoutExpired as e:
        print(f"BLOCKED: Timeout expired.\nOutput:\n{e.output}")
        return False

    passed = ("[TEST SYNC INTEGRITY] PASS:" in out or "[TEST SYNC INTEGRITY] SUCCESS_IMPLICIT" in out) and ret == 0
    failed = ("[TEST SYNC INTEGRITY] FAIL:" in out or "[TEST SYNC INTEGRITY] ERROR:" in out) and ret != 0
    
    if expect_pass and not passed:
        print(f"FAILED (expected pass, got fail). Return Code: {ret}\nOutput:\n{out}")
        return False
    if not expect_pass and not failed:
        print(f"FAILED (expected fail, got pass). Return Code: {ret}\nOutput:\n{out}")
        return False
        
    print(f"SUCCESS: video={video} fit={fit} -> {'PASS' if expect_pass else 'FAIL (as expected)'}")
    return True

def main():
    print("[SYNC TEST] Running negative case (A - 8-hour gap mismatch)...")
    video = r"F:\GoPro\2026-09-25\GX010321.MP4"
    fit = r"F:\GoPro\2026-09-25\Poranna_jazda_na_rowerze.fit"
    # To pliki, w których GoPro ma błędny czas o 8h. System testowy odrzuci to prawidłowo, bo zakazano `user_override=True`.
    ok_a = run_test(video, fit, expect_pass=False)
    
    print("\n[SYNC TEST] Running negative case (B - Complete date mismatch)...")
    video_mismatch = r"F:\GoPro\2026-10-09\GX010361.MP4"
    ok_b = run_test(video_mismatch, fit, expect_pass=False)

    print("\n[SYNC TEST] Running negative case (C - Missing MP4)...")
    ok_c = run_test(r"F:\GoPro\Missing.MP4", fit, expect_pass=False)

    print("\n[SYNC TEST] Running negative case (D - Missing FIT)...")
    ok_d = run_test(video, r"F:\GoPro\Missing.fit", expect_pass=False)

    if ok_a and ok_b and ok_c and ok_d:
        print("\n[SYNC TEST] SYNC_INTEGRITY_PASS")
    else:
        sys.exit(1)

if __name__ == '__main__':
    main()
