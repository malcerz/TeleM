"""Capture a frame through libmpv with the exact SportCamHUD preview options."""
import os, sys, time
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
os.environ["PATH"] = str(ROOT) + os.pathsep + os.environ["PATH"]
sys.path.insert(0, str(ROOT))
import mpv
from src.gui.qt.mpv_hwdec import build_mpv_options

video, t, out = sys.argv[1], float(sys.argv[2]), sys.argv[3]
opts = build_mpv_options("amd")
opts.update(dict(vo="gpu-next" if len(sys.argv) > 4 and sys.argv[4] == "next" else "gpu",
                 pause=True, mute=True, audio="no", osc=False, force_window="yes",
                 geometry="960x540", hr_seek="yes"))
print("options:", opts, flush=True)
p = mpv.MPV(**opts)
p.play(video)
time.sleep(4)
p.seek(t, reference="absolute", precision="exact")
time.sleep(4)
p.screenshot_to_file(out, includes="video")
time.sleep(1)
print("vo", p.current_vo, "hwdec", p.hwdec_current, "video-params", p.video_params, "target", p.video_target_params, flush=True)
p.terminate()
