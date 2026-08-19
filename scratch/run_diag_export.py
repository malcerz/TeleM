"""Run export with AMD_NATIVE_DIAGNOSTICS=1 to capture 01_python_hud_30.png and 02_buffer_sent_to_dll.png."""
import os
import sys
from pathlib import Path

root = Path("c:/_DEV/TeleM")
sys.path.insert(0, str(root))

os.environ["AMD_NATIVE_DIAGNOSTICS"] = "1"

import scratch.test_real_720p_amd_export as exp
exp.run_720p_export()
