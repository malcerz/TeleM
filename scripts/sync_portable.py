import os
import shutil
import subprocess
import json

def get_git_hash():
    try:
        return subprocess.check_output(['git', 'rev-parse', '--short', 'HEAD']).decode('utf-8').strip()
    except:
        return "unknown"

def inject_hash_and_sync():
    src_dir = r'C:\_DEV\BikeRideHUD-main-new'
    dst_dir = r'C:\_DEV\BikeRideHUD-portable'
    
    current_hash = get_git_hash()
    print(f"Current git hash: {current_hash}")
    
    for root, dirs, files in os.walk(src_dir):
        if '.git' in root or '__pycache__' in root or 'scratch' in root or 'cache' in root:
            continue
        for file in files:
            if file.endswith(('.py', '.json', '.cpp', '.h', '.md', '.dll', '.pyd')):
                src_file = os.path.join(root, file)
                rel_path = os.path.relpath(src_file, src_dir)
                dst_file = os.path.join(dst_dir, rel_path)
                os.makedirs(os.path.dirname(dst_file), exist_ok=True)
                shutil.copy2(src_file, dst_file)
                
    # Write build metadata to Portable ONLY so Portable knows its version
    meta_path = os.path.join(dst_dir, 'build_meta.json')
    with open(meta_path, 'w', encoding='utf-8') as f:
        json.dump({'commit': current_hash}, f)
        
    print("Sync to Portable completed.")

if __name__ == '__main__':
    inject_hash_and_sync()
