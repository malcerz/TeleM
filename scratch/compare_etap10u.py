"""ETAP 10U: decode MP4s to RGBA and compare pixel-by-pixel (temporary)."""
import subprocess
import sys
import numpy as np

FFMPEG = "ffmpeg"


def decode_rgba(mp4: str) -> bytes:
    proc = subprocess.run(
        [FFMPEG, "-hide_banner", "-loglevel", "error", "-i", mp4,
         "-f", "rawvideo", "-pix_fmt", "rgba", "pipe:1"],
        capture_output=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.decode(errors="replace"))
    return proc.stdout


def compare(a_path: str, b_path: str, label: str, frames: int = 120):
    a = decode_rgba(a_path)
    b = decode_rgba(b_path)
    assert len(a) == len(b), f"{label}: length {len(a)} vs {len(b)}"
    n_pixels = len(a) // 4
    per_frame = n_pixels // frames
    frames_diff = 0
    diff_pixels = 0
    max_delta = 0
    for fi in range(frames):
        s = fi * per_frame * 4
        e = s + per_frame * 4
        fa, fb = a[s:e], b[s:e]
        if fa != fb:
            frames_diff += 1
            na = np.frombuffer(fa, dtype=np.uint8).reshape(-1, 4)
            nb = np.frombuffer(fb, dtype=np.uint8).reshape(-1, 4)
            max_delta = max(max_delta, int(np.abs(na.astype(np.int16) - nb.astype(np.int16)).max()))
            diff_pixels += int(np.count_nonzero(np.any(na != nb, axis=1)))
    print(f"[PARITY] {label}: frames_diff={frames_diff}/{frames} "
          f"diff_pixels={diff_pixels}/{n_pixels} ({100.0*diff_pixels/max(1,n_pixels):.5f}%) max_delta={max_delta}")
    return {"frames_diff": frames_diff, "diff_pixels": diff_pixels, "max_delta": max_delta}


if __name__ == "__main__":
    pairs = [
        (sys.argv[1], sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else "A vs B"),
    ]
    for a, b, label in pairs:
        compare(a, b, label)
