"""Compare decoded output samples within one backend/codec, never as ground truth."""
from pathlib import Path
import json
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def main():
    out = ROOT / "Raporty/intel_vbr_qp_20261017/matrix"
    ffmpeg = ROOT / "runtime/common/ffmpeg/ffmpeg.exe"
    results = []
    # Thirty aligned frames at the start, middle and end of the 600-frame test.
    select = "select='between(n,0,29)+between(n,285,314)+between(n,570,599)',setpts=N/FRAME_RATE/TB"
    for backend in ("native", "ffmpeg"):
        for codec in ("h264", "hevc"):
            for profile in ("balanced", "quality"):
                name = f"{backend}_{codec}_fast_vs_{profile}"
                a = out / f"benchmark_{backend}_{codec}_fast.mp4"
                b = out / f"benchmark_{backend}_{codec}_{profile}.mp4"
                graph = f"[0:v]{select},split[a][c];[1:v]{select},split[b][d];[a][b]ssim[s];[c][d]psnr[p]"
                proc = subprocess.run([str(ffmpeg), "-nostdin", "-threads", "2", "-i", str(a), "-threads", "2", "-i", str(b),
                    "-filter_complex_threads", "2", "-filter_complex", graph, "-map", "[s]", "-map", "[p]", "-an", "-f", "null", "-"],
                    capture_output=True, text=True, timeout=600)
                (out / (name + "_quality.log")).write_text(proc.stderr, encoding="utf-8")
                if proc.returncode: raise RuntimeError(name + ": " + proc.stderr[-1500:])
                ssim = re.search(r"SSIM .*All:([\d.]+)", proc.stderr)
                psnr = re.search(r"PSNR .*average:([\d.inf]+)", proc.stderr)
                if not ssim or not psnr: raise RuntimeError("Missing metrics: " + name)
                item = dict(name=name, ssim=float(ssim[1]), psnr_db=psnr[1], frames=90,
                            meaning="pairwise decoded similarity; no uncompressed HUD reference, not an absolute quality ranking")
                results.append(item)
                (out / "quality_comparison.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
                print(item, flush=True)


if __name__ == "__main__":
    main()
