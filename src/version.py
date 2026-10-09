APP_VERSION = '1.03'

import os
import json

def get_build_commit() -> str:
    # 1. Try to read generated metadata (used by Portable)
    meta_path = os.path.join(os.path.dirname(__file__), '..', 'build_meta.json')
    if os.path.exists(meta_path):
        try:
            with open(meta_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                return data.get('commit', 'unknown')
        except Exception:
            pass

    # 2. Try to read .git files natively without spawning subprocess
    git_dir = os.path.join(os.path.dirname(__file__), '..', '.git')
    head_path = os.path.join(git_dir, 'HEAD')
    if os.path.exists(head_path):
        try:
            with open(head_path, 'r', encoding='utf-8') as f:
                head_ref = f.read().strip()
            if head_ref.startswith('ref: '):
                ref_path = os.path.join(git_dir, head_ref[5:])
                if os.path.exists(ref_path):
                    with open(ref_path, 'r', encoding='utf-8') as f:
                        return f.read().strip()[:7]
                # Check packed-refs if ref not found
                packed_refs = os.path.join(git_dir, 'packed-refs')
                if os.path.exists(packed_refs):
                    with open(packed_refs, 'r', encoding='utf-8') as f:
                        for line in f:
                            if line.endswith(head_ref[5:]) or head_ref[5:] in line:
                                return line.split(' ')[0][:7]
            else:
                return head_ref[:7]
        except Exception:
            pass

    return 'unknown'

APP_BUILD_COMMIT = get_build_commit()
