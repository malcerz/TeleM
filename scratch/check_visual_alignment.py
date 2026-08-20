import sys
from pathlib import Path
_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

import numpy as np
from PIL import Image

im_a = Image.open('scratch/exact_atlas_0.0.png')
im_f = Image.open('scratch/exact_full_0.0.png')

arr_a = np.asarray(im_a)
arr_f = np.asarray(im_f)

# Let's crop the time block from both and compare
tb_a = arr_a[40:160, 40:400]
tb_f = arr_f[40:160, 40:400]
tb_diff = np.abs(tb_a.astype(int) - tb_f.astype(int))
print("Time block diff: mean =", np.mean(tb_diff), "max =", np.max(tb_diff))

# Let's crop the gauge center from both and compare
g_a = arr_a[1650:1950, 1650:2150]
g_f = arr_f[1650:1950, 1650:2150]
g_diff = np.abs(g_a.astype(int) - g_f.astype(int))
print("Gauge diff: mean =", np.mean(g_diff), "max =", np.max(g_diff))
