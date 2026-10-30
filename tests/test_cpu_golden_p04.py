"""CPU P0.4 Golden HUD (GX010370, frame 1050): integrity of the frozen reference.

Set TELEM_GOLDEN_RERUN=1 to also re-export 160 frames through the canonical CPU
harness and require the pre-compression HUD to match the golden exactly.
"""
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
GOLD = ROOT / "Raporty" / "CPU_P04_GUI_GOLDEN_OVERLAY" / "golden"
pytestmark = pytest.mark.skipif(not (GOLD / "manifest.json").exists(), reason="golden not present")


def _load(name):
    return np.asarray(Image.open(GOLD / name).convert("RGBA"))


def test_golden_hashes_match_manifest():
    m = json.loads((GOLD / "manifest.json").read_text(encoding="utf-8"))
    stored = _load("hud_f1050_precompression_stored_rot180.png")
    upright = _load("hud_f1050_precompression_upright.png")
    assert hashlib.sha256(stored.tobytes()).hexdigest() == m["hud_rgba_sha256_stored"]
    assert hashlib.sha256(upright.tobytes()).hexdigest() == m["hud_rgba_sha256_upright"]
    assert np.array_equal(stored[::-1, ::-1], upright), "stored orientation must be the upright HUD rotated once"


@pytest.mark.skipif(os.environ.get("TELEM_GOLDEN_RERUN") != "1", reason="set TELEM_GOLDEN_RERUN=1 (needs D:\GoPro media)")
def test_golden_rerun_matches(tmp_path):
    m = json.loads((GOLD / "manifest.json").read_text(encoding="utf-8"))
    if not Path(m["video"]["path"]).exists():
        pytest.skip("source media missing")
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen", TELEM_CPU_DIAG_DUMP_FRAMES="150",
               TELEM_CPU_DIAG_DUMP_DIR=str(tmp_path))
    subprocess.run([sys.executable, "SportCamHUD.py", "--test-cpu-export", "--mode", "direct",
                    "--video", m["video"]["path"], "--fit", m["fit"]["path"], "--layout", m["layout"]["path"],
                    "--start-frame", "900", "--frames", "160", "--wait-prepared", "--profile", "fast",
                    "--output", str(tmp_path / "o.mp4"), "--result-json", str(tmp_path / "o.json")],
                   cwd=ROOT, env=env, check=True, timeout=600)
    x = np.fromfile(tmp_path / "export_hud_f150.rgba", dtype=np.uint8).reshape(2160, 3840, 4).copy()
    x[x[..., 3] == 0] = 0
    assert hashlib.sha256(x.tobytes()).hexdigest() == m["hud_rgba_sha256_stored"]
