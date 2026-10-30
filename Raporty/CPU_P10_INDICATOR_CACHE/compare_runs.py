"""P1.0: compare per-frame RGBA SHA-256 lists and editor/pipeline Golden captures.

Usage:
  compare_runs.py hashes A.jsonl B.jsonl            -> different frame count
  compare_runs.py golden RUN_DIR ABS_FRAME REL_FRAME [--rotate180]
"""
import json, sys
import numpy as np
from PIL import Image


def load_hashes(path):
    out = {}
    for line in open(path):
        r = json.loads(line)
        out[r['frame']] = r['sha256']
    return out


def stats(a, b):
    a = a.astype(np.int16); b = b.astype(np.int16)
    for arr in (a, b):
        arr[arr[..., 3] == 0, :3] = 0  # RGB under zero alpha is not visible
    d = np.abs(a - b)
    return {'different_pixels': int(np.any(d, axis=2).sum()), 'max_diff': int(d.max()), 'MAE': float(d.mean())}


if sys.argv[1] == 'hashes':
    a, b = load_hashes(sys.argv[2]), load_hashes(sys.argv[3])
    common = sorted(set(a) & set(b))
    diff = [k for k in common if a[k] != b[k]]
    print(json.dumps({'frames_a': len(a), 'frames_b': len(b), 'common': len(common), 'different': len(diff),
                      'first_different': diff[:3]}))
else:
    run, absf, relf = sys.argv[2], int(sys.argv[3]), int(sys.argv[4])
    editor = np.array(Image.open(f'{run}/editor_hud_f{absf}.png').convert('RGBA'))
    algo = np.array(Image.open(f'{run}/exportalgo_hud_f{absf}.png').convert('RGBA'))
    h, w = editor.shape[:2]
    raw = np.frombuffer(open(f'{run}/export_hud_f{relf}.rgba', 'rb').read(), np.uint8)
    pipe = raw.reshape(-1, w if raw.size == h * w * 4 else h, 4)
    if pipe.shape[:2] != (h, w):
        pipe = pipe.reshape(h, w, 4)
    if '--rotate180' in sys.argv:
        pipe = pipe[::-1, ::-1]
    print(json.dumps({'editor_vs_algo': stats(editor, algo), 'editor_vs_pipe': stats(editor, pipe)}))
