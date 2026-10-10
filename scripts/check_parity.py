import os
import json
import hashlib
import sys

def get_file_hash(filepath):
    h = hashlib.sha256()
    try:
        with open(filepath, 'rb') as f:
            for chunk in iter(lambda: f.read(65536), b''):
                h.update(chunk)
        return h.hexdigest()
    except:
        return None

def check_parity():
    portable_dir = r'C:\_DEV\BikeRideHUD-portable'
    main_dir = r'C:\_DEV\BikeRideHUD-main-new'
    manifest_path = os.path.join(portable_dir, 'runtime_manifest.json')
    
    if not os.path.exists(manifest_path):
        print("FAIL: runtime_manifest.json not found in Portable!")
        sys.exit(1)
        
    with open(manifest_path, 'r', encoding='utf-8') as f:
        meta = json.load(f)
        manifest = meta.get('manifest', {})
        
    required_files = [
        "src/version.py",
        "src/ffmpeg/output_error.py",
        "src/ffmpeg/render_errors.py",
        "src/integrations/garmin_auth.py",
        "src/integrations/garmin_connect.py",
        "src/telemetry_native_gpmf.py",
        "src/telemetry_heading.py",
        "src/render_preparation.py",
        "src/native/gpmf/telem_gpmf_native.pyd",
        "native/d3d11_amf_pipeline/bin/telem_amd_native.dll"
    ]
    
    # Also verify all items in manifest
    all_match = True
    missing_in_portable = []
    hash_mismatch = []
    
    for rel_path, expected_hash in manifest.items():
        portable_file = os.path.join(portable_dir, rel_path)
        main_file = os.path.join(main_dir, rel_path)
        
        if not os.path.exists(portable_file):
            missing_in_portable.append(rel_path)
            all_match = False
            continue
            
        p_hash = get_file_hash(portable_file)
        m_hash = get_file_hash(main_file)
        
        if p_hash != expected_hash or p_hash != m_hash:
            hash_mismatch.append(rel_path)
            all_match = False
            
    for req in required_files:
        if req not in manifest:
            print(f"FAIL: Required file {req} is missing from sync manifest!")
            all_match = False
            
    if missing_in_portable:
        print("FAIL: Files missing in portable:", missing_in_portable)
    if hash_mismatch:
        print("FAIL: Hash mismatches:", hash_mismatch)
        
    if all_match:
        print("PARITY: YES (100% manifest match)")
        sys.exit(0)
    else:
        print("PARITY: NO")
        sys.exit(1)

if __name__ == '__main__':
    check_parity()
