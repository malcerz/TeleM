import hashlib
import glob
import os
import json
from pathlib import Path

def hash_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(1024 * 1024):
            h.update(chunk)
    return h.hexdigest()

files = sorted(glob.glob(r"C:\_DEV\_SPORTCAMHUD_ETAP_5A_RESULTS_20261012\canonical_3000\*.mp4"))
manifest = []

for f in files:
    size = os.path.getsize(f)
    mtime = os.path.getmtime(f)
    sha = hash_file(f)
    rec = {
        "file": os.path.basename(f),
        "path": f,
        "size_bytes": size,
        "mtime": mtime,
        "sha256": sha
    }
    manifest.append(rec)
    print(f"{os.path.basename(f):<12} | {size:>10} bytes | {sha}")

out_path = Path(r"C:\_DEV\_SPORTCAMHUD_ETAP_5A_RESULTS_20261012\canonical_3000\mp4_manifest_sha256.json")
with open(out_path, "w", encoding="utf-8") as out_f:
    json.dump(manifest, out_f, indent=2)

print(f"\nManifest saved to {out_path}")
