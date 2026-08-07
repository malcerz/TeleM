import urllib.request
import json
import os
import shutil
import sys

api_url = "https://api.github.com/repos/shinchiro/mpv-winbuild-cmake/releases/latest"
req = urllib.request.Request(api_url, headers={'User-Agent': 'Mozilla/5.0'})
try:
    with urllib.request.urlopen(req) as response:
        data = json.loads(response.read().decode())
        dev_url = None
        for asset in data['assets']:
            if asset['name'].startswith('mpv-dev-x86_64') and asset['name'].endswith('.zip'):
                dev_url = asset['browser_download_url']
                break
        if not dev_url:
            print("Did not find .zip, trying .7z...")
            for asset in data['assets']:
                if asset['name'].startswith('mpv-dev-x86_64') and asset['name'].endswith('.7z'):
                    dev_url = asset['browser_download_url']
                    break
            if dev_url:
                os.system('pip install py7zr')
                import py7zr
                print(f"Downloading {dev_url}...")
                urllib.request.urlretrieve(dev_url, "mpv-dev.7z")
                print("Extracting...")
                with py7zr.SevenZipFile("mpv-dev.7z", mode='r') as z:
                    z.extractall(path="mpv-dev")
        else:
            import zipfile
            print(f"Downloading {dev_url}...")
            urllib.request.urlretrieve(dev_url, "mpv-dev.zip")
            print("Extracting...")
            with zipfile.ZipFile("mpv-dev.zip", 'r') as z:
                z.extractall("mpv-dev")
        
        dll_path = None
        for root, dirs, files in os.walk("mpv-dev"):
            for file in files:
                if file in ("mpv-2.dll", "libmpv-2.dll", "mpv-1.dll", "libmpv-1.dll"):
                    dll_path = os.path.join(root, file)
                    break
        if dll_path:
            # We must place it in the same directory as the python executable OR in PATH
            # Easiest is to place it next to TeleMGP0.py
            shutil.copy(dll_path, "libmpv-2.dll")
            shutil.copy(dll_path, "mpv-2.dll")
            print(f"Successfully copied {os.path.basename(dll_path)} to root.")
        else:
            print("Could not find dll inside archive.")
except Exception as e:
    print(f"Error: {e}")
