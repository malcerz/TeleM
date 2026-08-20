from __future__ import annotations

import os
os.environ["TELEM_ETAP5C_DIRECT"] = "1"
from profile_etap5c_baseline import main as profile_main

# The baseline harness is kept as the single setup/timing implementation.
# Direct mode is enabled by the worker layout flag in a small source-level
# variant created below only for this diagnostic run.
if __name__ == "__main__":
    profile_main()
