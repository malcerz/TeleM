import os
import sys
import subprocess
from pathlib import Path
import pybind11

def build():
    root = Path(__file__).resolve().parent
    vcvars = r"C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat"
    if not os.path.exists(vcvars):
        # Check standard Community/Professional locations
        for edition in ["BuildTools", "Community", "Professional", "Enterprise"]:
            p = rf"C:\Program Files\Microsoft Visual Studio\2022\{edition}\VC\Auxiliary\Build\vcvars64.bat"
            if os.path.exists(p):
                vcvars = p
                break

    py_inc = os.path.join(sys.base_prefix, "Include")
    py_lib = os.path.join(sys.base_prefix, "libs")
    pybind_inc = pybind11.get_include()
    gpmf_inc = str(root / "third_party" / "gpmf-parser")

    out_pyd = str(root / "src" / "native" / "gpmf" / "telem_gpmf_native.pyd")
    src_bindings = str(root / "src" / "native" / "gpmf" / "gpmf_bindings.cpp")
    src_extractor = str(root / "src" / "native" / "gpmf" / "gpmf_extractor.cpp")
    src_parser = str(root / "third_party" / "gpmf-parser" / "GPMF_parser.c")
    src_utils = str(root / "third_party" / "gpmf-parser" / "GPMF_utils.c")
    src_mp4reader = str(root / "third_party" / "gpmf-parser" / "demo" / "GPMF_mp4reader.c")

    cmd = (
        f'"{vcvars}" && cl /O2 /std:c++17 /EHsc /MD /LD '
        f'/I"{gpmf_inc}" /I"{py_inc}" /I"{pybind_inc}" '
        f'/Fe"{out_pyd}" '
        f'"{src_bindings}" "{src_extractor}" "{src_parser}" "{src_utils}" "{src_mp4reader}" '
        f'/link /LIBPATH:"{py_lib}"'
    )
    print(f"Building {out_pyd}...")
    res = subprocess.run(f'cmd.exe /c "{cmd}"', shell=True, capture_output=True, text=True)
    print("STDOUT:\n", res.stdout)
    if res.stderr:
        print("STDERR:\n", res.stderr)
    if res.returncode != 0:
        raise RuntimeError(f"Compilation failed with exit code {res.returncode}")
    print("Build successful!")

if __name__ == "__main__":
    build()
