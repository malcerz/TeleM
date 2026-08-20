import sys
from pathlib import Path
_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

import numpy as np
from PIL import Image

arr_a = np.asarray(Image.open('scratch/exact_atlas_0.0.png'))
arr_f = np.asarray(Image.open('scratch/exact_full_0.0.png'))

diff = np.abs(arr_a.astype(int) - arr_f.astype(int))
y_d, x_d = np.nonzero(diff.any(axis=-1))

print("Atlas vs Full frame diff:")
print(f"Diff pixel count: {len(x_d)}")
print(f"X range: [{np.min(x_d)}, {np.max(x_d)}]")
print(f"Y range: [{np.min(y_d)}, {np.max(y_d)}]")

# Inspect Region 0 (time_block)
reg0_diff = diff[0:400, 0:900]
print(f"Region 0 (time_block) diff: max={np.max(reg0_diff)}, count={np.count_nonzero(reg0_diff.any(axis=-1))}")

# Inspect Region 1 (heart rate)
reg1_diff = diff[1400:2160, 2300:3840]
print(f"Region 1 (heart rate) diff: max={np.max(reg1_diff)}, count={np.count_nonzero(reg1_diff.any(axis=-1))}")

# Inspect Region 2 (cadence & speed)
reg2_diff = diff[1400:2160, 0:2300]
print(f"Region 2 (cadence & speed) diff: max={np.max(reg2_diff)}, count={np.count_nonzero(reg2_diff.any(axis=-1))}")

# Check non-HUD background (middle of frame)
mid_diff = diff[500:1300, 500:3000]
print(f"Middle background diff: max={np.max(mid_diff)}, count={np.count_nonzero(mid_diff.any(axis=-1))}")
