"""Check tile cache for moving map renderer."""
from pathlib import Path
import os

root = Path("c:/_DEV/TeleM")

def check_cache():
    # MovingMapRenderer caches tiles in ~/.cache/telem/tiles or ./tiles or similar
    # Let's search for MovingMapRenderer cache directory
    from src.moving_map import MovingMapRenderer
    print("Checking MovingMapRenderer tile cache...")
    import inspect
    src_file = inspect.getfile(MovingMapRenderer)
    print(f"MovingMapRenderer defined in: {src_file}")

if __name__ == "__main__":
    check_cache()
