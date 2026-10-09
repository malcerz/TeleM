import os
import shutil

src_dir = r'C:\_DEV\BikeRideHUD-main-new'
dst_dir = r'C:\_DEV\BikeRideHUD-portable'

def sync_dirs(src, dst):
    for root, dirs, files in os.walk(src):
        if '.git' in root or '__pycache__' in root or 'scratch' in root or 'cache' in root:
            continue
        for file in files:
            if file.endswith(('.py', '.json', '.cpp', '.h', '.md', '.dll')):
                src_file = os.path.join(root, file)
                rel_path = os.path.relpath(src_file, src)
                dst_file = os.path.join(dst, rel_path)
                
                os.makedirs(os.path.dirname(dst_file), exist_ok=True)
                
                if not os.path.exists(dst_file) or os.path.getmtime(src_file) > os.path.getmtime(dst_file):
                    shutil.copy2(src_file, dst_file)
                    
sync_dirs(src_dir, dst_dir)
print("Sync complete.")
