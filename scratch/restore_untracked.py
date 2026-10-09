import os
import shutil

with open('scripts/check_parity.py', 'r') as f:
    text = f.read()

import re
matches = re.findall(r"'([^']+)'", text)

for f in matches:
    if f.endswith('.py') or f.endswith('.md') or f.endswith('.cpp') or f.endswith('.h') or f.endswith('.json'):
        src = os.path.join(r'C:\_DEV\BikeRideHUD-portable', f)
        dst = os.path.join(r'C:\_DEV\BikeRideHUD-main-new', f)
        if os.path.exists(src):
            if not os.path.exists(dst):
                print(f"Restoring {f}")
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                shutil.copy2(src, dst)
