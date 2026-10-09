import os
import shutil
import subprocess
import json
import hashlib

def get_file_hash(filepath):
    h = hashlib.sha256()
    try:
        with open(filepath, 'rb') as f:
            for chunk in iter(lambda: f.read(65536), b''):
                h.update(chunk)
        return h.hexdigest()
    except:
        return None

def get_git_hash(src_dir):
    try:
        commit = subprocess.check_output(['git', 'rev-parse', '--short', 'HEAD'], cwd=src_dir).decode('utf-8').strip()
        status = subprocess.check_output(['git', 'status', '--porcelain'], cwd=src_dir).decode('utf-8').strip()
        if status:
            commit += "-DIRTY"
        return commit
    except:
        return "unknown"

def sync_and_manifest():
    src_dir = r'C:\_DEV\BikeRideHUD-main-new'
    dst_dir = r'C:\_DEV\BikeRideHUD-portable'
    
    current_hash = get_git_hash(src_dir)
    print(f"Current git hash: {current_hash}")
    
    extensions_to_copy = ('.py', '.json', '.cpp', '.h', '.md', '.dll', '.pyd', '.png', '.svg', '.qss', '.ini')
    skip_dirs = {'.git', '__pycache__', 'scratch', 'tests', 'Raporty', 'tests_mocks'}
    
    manifest = {}
    
    for root, dirs, files in os.walk(src_dir):
        # Exclude directories
        dirs[:] = [d for d in dirs if d not in skip_dirs]
        if 'cache' in root.lower() and 'telemetry' in root.lower():
            continue
        
        for file in files:
            if file.endswith(extensions_to_copy):
                src_file = os.path.join(root, file)
                rel_path = os.path.relpath(src_file, src_dir)
                
                if file == "build_meta.json":
                    continue
                
                dst_file = os.path.join(dst_dir, rel_path)
                os.makedirs(os.path.dirname(dst_file), exist_ok=True)
                shutil.copy2(src_file, dst_file)
                
                manifest[rel_path.replace('\\', '/')] = get_file_hash(dst_file)
                
    old_manifest_path = os.path.join(dst_dir, 'runtime_manifest.json')
    if os.path.exists(old_manifest_path):
        with open(old_manifest_path, 'r', encoding='utf-8') as f:
            try:
                old_meta = json.load(f)
                old_manifest = old_meta.get("manifest", {})
                for old_file in old_manifest:
                    if old_file not in manifest:
                        print(f"[STALE DETECTED] {old_file} no longer exists in source. Consider deleting it from portable.")
            except:
                pass
                
    meta_path = os.path.join(dst_dir, 'build_meta.json')
    with open(meta_path, 'w', encoding='utf-8') as f:
        json.dump({'commit': current_hash}, f)
        
    with open(old_manifest_path, 'w', encoding='utf-8') as f:
        json.dump({'commit': current_hash, 'manifest': manifest}, f, indent=2)
        
    print("Sync and manifest generation completed.")

if __name__ == '__main__':
    sync_and_manifest()
