"""Build script for Intel native pipeline (telem_intel_native.dll).

Contract:
- Source: src/native/intel/d3d11_intel_pipeline/telem_intel_native.c
- Output directory: runtime/intel/bin/
- Output binary: runtime/intel/bin/telem_intel_native.dll
- Copies Intel FFmpeg runtime dependencies into runtime/intel/bin/
"""

import os
import sys
import shutil
import subprocess
from pathlib import Path


def build():
    root = Path(__file__).resolve().parent
    vcvars = r"C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat"
    if not os.path.exists(vcvars):
        for edition in ["BuildTools", "Community", "Professional", "Enterprise"]:
            p = rf"C:\Program Files\Microsoft Visual Studio\2022\{edition}\VC\Auxiliary\Build\vcvars64.bat"
            if os.path.exists(p):
                vcvars = p
                break

    ff_dir = root / "third_party" / "ffmpeg-9.0.1-full_build-shared"
    ff_inc = ff_dir / "include"
    ff_lib = ff_dir / "lib"
    ff_bin = ff_dir / "bin"
    vpl_inc = root / "third_party" / "oneVPL" / "include"

    out_dir = root / "runtime" / "intel" / "bin"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_dll = out_dir / "telem_intel_native.dll"
    src_c = root / "src" / "native" / "intel" / "d3d11_intel_pipeline" / "telem_intel_native.c"

    # Copy FFmpeg runtime DLLs to output directory so they are alongside telem_intel_native.dll
    if ff_bin.exists():
        for f in ff_bin.glob("*.dll"):
            dest_file = out_dir / f.name
            if not dest_file.exists() or dest_file.stat().st_mtime < f.stat().st_mtime:
                shutil.copy2(f, dest_file)

    cmd = (
        f'"{vcvars}" && cl /O2 /W3 /D_CRT_SECURE_NO_WARNINGS /std:c11 /arch:AVX2 /LD '
        f'/I"{ff_inc}" /I"{vpl_inc}" '
        f'"{src_c}" '
        f'/Fe"{out_dll}" '
        f'/link /LIBPATH:"{ff_lib}" '
        f'avformat.lib avcodec.lib avutil.lib swscale.lib swresample.lib '
        f'd3d11.lib dxgi.lib ole32.lib ws2_32.lib secur32.lib bcrypt.lib crypt32.lib ncrypt.lib shlwapi.lib'
    )
    print(f"Building {out_dll}...")
    res = subprocess.run(f'cmd.exe /c "{cmd}"', shell=True, capture_output=True, text=True, errors="replace")
    sys.stdout.buffer.write(("STDOUT:\n" + res.stdout + "\n").encode("utf-8", errors="replace"))
    if res.stderr:
        sys.stderr.buffer.write(("STDERR:\n" + res.stderr + "\n").encode("utf-8", errors="replace"))
    if res.returncode != 0:
        raise RuntimeError(f"Compilation failed with exit code {res.returncode}")
    print("Build successful!")


if __name__ == "__main__":
    build()
