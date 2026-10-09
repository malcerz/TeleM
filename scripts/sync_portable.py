import os
import shutil
import subprocess
import re

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
    
    version_file = os.path.join(src_dir, 'src', 'version.py')
    with open(version_file, 'r', encoding='utf-8') as f:
        text = f.read()
    
    text = re.sub(r"APP_BUILD_COMMIT\s*=\s*['\"].*?['\"]", f"APP_BUILD_COMMIT = '{current_hash}'", text)
    with open(version_file, 'w', encoding='utf-8') as f:
        f.write(text)
        
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
                
    print("Sync to Portable completed.")

if __name__ == '__main__':
    inject_hash_and_sync()
