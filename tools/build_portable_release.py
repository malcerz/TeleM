"""SportCamHUD portable release packager (ETAP 5Y).

Builds a self-contained portable folder from:
  * application code and the distribution layout template exported from a
    git commit (default: HEAD) — uncommitted work-in-progress never leaks in;
  * an explicit allowlist of runtime binaries and untracked assets from the
    working tree, each verified (pinned SHA-256 where the release depends on
    an exact build);
  * optionally (default on) a bundled CPython runtime with exactly the
    dependency closure of the app's requirements, so the folder runs on a
    machine without Python.

The target must not exist (or be empty).  A manifest with commit, versions,
SHA-256 of the key binaries and the full file list is written to
``portable_manifest.json``; ``THIRD_PARTY_NOTICES.txt`` lists redistributed
components and their licences.
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import importlib.metadata as md
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]

# Pinned production native builds (verified before copy).
EXPECTED_SHA256 = {
    # AMD Native D3D11/AMF, ABI 9: Native GPU Track-Up + Pitch (commit fafc798), with real AMF QP feedback (17.10.2026),
    # map style, HLG preserve (HEVC Main10) and HLG->SDR, tone-mapped HLG export-preview tap.
    "runtime/amd/bin/telem_amd_native.dll": "bbca75fbd0dfc5d7cbb61922e92f8d5f049b4305dd18335315667e6e5e54ca5f",
    "runtime/intel/bin/telem_intel_native.dll": "dafa1b9b42dc2af1df23411d5e5d9f9e66556512a3130eb5794e7483cc29c14c",
}
FORBIDDEN_SHA256 = {
    "18a0503f4eec574b9a967fb0d1d5ddea6061b6fd3fbccf6c26f8bafd2c4827bb",  # AMD DLL with QP removed (2026-10-19)
    "41658018ae4979071837dfef4e412c40a855771266380cf84595a66bf89c0cca",  # old Intel non-quantizer DLL
    "380f86b044ab61eefb60c0e1d6fd386dcfe0e95d9c12dac756a93bf8e71ea50b",  # AMD DLL before QP feedback
    "6c43f398fbb1421c6dbb21928309f996e9967afea8040c2d42af6c72ba7f29ca",  # AMD DLL before map style
    "5ad042bb8f61db32af52df2a3ea1fdd77c40b253866ce28724c6fe01e4a3c0df",  # AMD DLL before HDR (ETAP 5Y)
    "2ceb50cc4d85343237f9aaf6634c7a2d93bb8de1375388166533d71227e0761e",  # AMD DLL 5Z.2, untone-mapped HDR preview
    "e359d7784d2ff3d2b1aefb6cf56dc1ba3c38a67260fd8d87e27851ef0d55ee89",  # AMD DLL 5Z.4 before native GPU pitch
}

# Code/templates taken from the git commit.
COMMIT_PATHS = [
    "SportCamHUD.py", "TeleMGP.py", "telemetry_fit.py", "telemetry_gpx.py",
    "pyproject.toml", "README.md", "Start_SportCamHUD.cmd", "def_layout.json",
    "presets", "src", "runtime/common/telemetry/gpmf/telem_gpmf_native.pyd",
]
# Inside src/native only the prebuilt GPMF parser is runtime; sources are not shipped.
COMMIT_SRC_NATIVE_KEEP = {"runtime/common/telemetry/gpmf/telem_gpmf_native.pyd"}
COMMIT_EXCLUDE_DIRS = {"__pycache__", "bikeridehud.egg-info"}

# Untracked runtime files from the working tree: (source, destination).
WORKTREE_FILES = [
    ("libmpv-2.dll", "libmpv-2.dll"),
    ("wzor/rower_ico.png", "wzor/rower_ico.png"),
    ("runtime/common/ffmpeg/ffmpeg.exe", "runtime/common/ffmpeg/ffmpeg.exe"),
    ("runtime/common/ffmpeg/ffprobe.exe", "runtime/common/ffmpeg/ffprobe.exe"),
    ("runtime/amd/bin/telem_amd_native.dll", "runtime/amd/bin/telem_amd_native.dll"),
    ("runtime/intel/bin/telem_intel_native.dll", "runtime/intel/bin/telem_intel_native.dll"),
    *[(f"runtime/intel/bin/{n}", f"runtime/intel/bin/{n}") for n in (
        "avcodec-63.dll", "avdevice-63.dll", "avfilter-12.dll", "avformat-63.dll",
        "avutil-61.dll", "swresample-7.dll", "swscale-10.dll")],
    *[(f"runtime/telemetry_parser/{n}", f"runtime/common/telemetry/telemetry_parser/{n}") for n in (
        "LICENSE-APACHE", "LICENSE-MIT", "README.md",
        "telemetry_parser/__init__.py", "telemetry_parser/telemetry_parser.cp314-win_amd64.pyd")],
]
WORKTREE_DIRS = [("src/assets/icons/png", "src/assets/icons/png", "*.png")]

# The AMD DLL is an MSVC build (MSVCP140/VCRUNTIME140/_1); ship them app-locally
# from the Visual Studio redistributable folder (redistributable per the VS
# licence) so the DLL loads without a separately installed VC++ redist.
VC_REDIST_DLLS = ("msvcp140.dll", "vcruntime140.dll", "vcruntime140_1.dll")

APP_REQUIREMENTS = ["PySide6", "numpy", "Pillow", "opencv-python", "fitparse", "orjson",
                    "python-mpv", "pyopencl", "requests", "garminconnect"]
PY_EXCLUDE_DIRS = {"__pycache__", "test", "tests", "idlelib", "tkinter", "turtledemo", "ensurepip",
                   "tcl", "Doc", "include", "libs", "Scripts", "site-packages"}

DENYLIST_EXTENSIONS = {".pdb", ".obj", ".exp", ".lib", ".ilk", ".map", ".log", ".tmp", ".bak", ".7z", ".rar"}
DENYLIST_PATTERNS = (".bak_", ".pre_quant_candidate", ".golden-", ".fresh-backup")


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(1 << 20):
            h.update(chunk)
    return h.hexdigest()


def git(*args: str) -> bytes:
    return subprocess.check_output(["git", *args], cwd=REPO)


def export_commit(commit: str, target: Path) -> str:
    full = git("rev-parse", commit).decode().strip()
    data = git("archive", "--format=tar", full, *COMMIT_PATHS)
    with tarfile.open(fileobj=io.BytesIO(data)) as tar:
        for m in tar.getmembers():
            if not m.isfile():
                continue
            parts = Path(m.name).parts
            if any(p in COMMIT_EXCLUDE_DIRS for p in parts):
                continue
            if m.name.startswith("src/native/") and m.name not in COMMIT_SRC_NATIVE_KEEP:
                continue
            dst = target / m.name
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(tar.extractfile(m).read())
    return full


def copy_checked(src_rel: str, dst_rel: str, target: Path) -> None:
    src = REPO / src_rel
    if not src.is_file():
        raise RuntimeError(f"Missing required runtime file: {src}")
    digest = sha256(src)
    expected = EXPECTED_SHA256.get(src_rel)
    if expected and digest != expected:
        raise RuntimeError(f"SHA-256 mismatch for {src_rel}: {digest} (expected {expected})")
    if digest in FORBIDDEN_SHA256:
        raise RuntimeError(f"Refusing superseded binary {src_rel} ({digest})")
    dst = target / dst_rel
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def find_vc_redist() -> Path:
    roots = [Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")),
             Path(os.environ.get("ProgramFiles", r"C:\Program Files"))]
    cands = []
    for root in roots:
        cands += sorted(root.glob("Microsoft Visual Studio/*/*/VC/Redist/MSVC/*/x64/Microsoft.VC14*.CRT"))
    if not cands:
        raise RuntimeError("Visual C++ redistributable folder (Microsoft.VC14x.CRT) not found")
    return cands[-1]


def dist_closure(roots: list[str]) -> list[md.Distribution]:
    seen: dict[str, Any] = {}
    stack = list(roots)
    while stack:
        name = stack.pop()
        key = re.sub(r"[-_.]+", "-", name).lower()
        if key in seen:
            continue
        try:
            dist = md.distribution(name)
        except md.PackageNotFoundError:
            seen[key] = None
            continue
        seen[key] = dist
        for req in dist.requires or []:
            if "extra ==" in req:
                continue
            m = re.match(r"\s*([A-Za-z0-9_.\-]+)", req)
            if m:
                marker = req.split(";", 1)[1] if ";" in req else ""
                if any(s in marker for s in ('sys_platform != "win32"', 'platform_system == "Linux"',
                                             'platform_system == "Darwin"', 'python_version < "3.1')):
                    continue
                stack.append(m.group(1))
    missing = [k for k, v in seen.items() if v is None]
    for k in missing:
        if k in {re.sub(r"[-_.]+", "-", r).lower() for r in roots}:
            raise RuntimeError(f"Required package not installed: {k}")
    return [v for v in seen.values() if v is not None]


def bundle_python(target: Path) -> dict[str, Any]:
    base = Path(sys.base_prefix)
    py_dst = target / "python"
    for root, dirs, files in os.walk(base):
        rel = Path(root).relative_to(base)
        dirs[:] = [d for d in dirs if d not in PY_EXCLUDE_DIRS]
        for f in files:
            if f.endswith((".pyc", ".pdb")):
                continue
            src = Path(root) / f
            dst = py_dst / rel / f
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
    site = py_dst / "Lib" / "site-packages"
    dists = dist_closure(APP_REQUIREMENTS)
    for dist in dists:
        for f in dist.files or []:
            src = Path(dist.locate_file(f))
            if not src.is_file() or "__pycache__" in f.parts or src.suffix == ".pyc":
                continue
            dst = site / f
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
    return {
        "python_version": sys.version.split()[0],
        "python_source": str(base),
        "packages": {d.metadata["Name"]: d.version for d in sorted(dists, key=lambda d: d.metadata["Name"].lower())},
    }


LAUNCHER = r"""@echo off
setlocal
pushd "%~dp0"
rem Portable runtime first (isolated: -s no user site, -E no PYTHON* env), then system Python.
if exist "python\python.exe" (
    "python\python.exe" -s -E "SportCamHUD.py" %*
) else (
    python "SportCamHUD.py" %*
)
set "APP_EXIT_CODE=%ERRORLEVEL%"
if not "%APP_EXIT_CODE%"=="0" (
    echo SportCamHUD exited with code %APP_EXIT_CODE%.
    echo Startup output is shown above. Press any key to close this window.
    pause >nul
)
popd
exit /b %APP_EXIT_CODE%
"""

NOTICES = """SportCamHUD portable — third-party components

FFmpeg (runtime/common/ffmpeg/ffmpeg.exe, ffprobe.exe): gyan.dev "full_build",
  configured with --enable-gpl --enable-version3 -> GPLv3. Redistribution must
  be accompanied by an offer of the corresponding source
  (https://www.gyan.dev/ffmpeg/builds/ and https://ffmpeg.org/download.html).
FFmpeg shared libraries for the Intel backend (runtime/intel/bin/av*.dll, sw*.dll):
  FFmpeg project, licence per their build configuration (LGPL/GPL); source at ffmpeg.org.
libmpv (libmpv-2.dll): mpv project, GPLv2+/LGPLv2.1+ depending on build; source at mpv.io.
Python (python/): Python Software Foundation License.
PySide6 / Qt 6 (python/Lib/site-packages/PySide6, shiboken6): LGPLv3 (dynamically
  linked, unmodified); Qt sources at https://download.qt.io/.
numpy (BSD), Pillow (MIT-CMU), opencv-python (Apache 2.0, bundled FFmpeg LGPL),
  fitparse (MIT), orjson (Apache 2.0/MIT), python-mpv (GPLv2+/LGPLv2.1+), pyopencl (MIT),
  requests/urllib3/idna/certifi/charset-normalizer (Apache 2.0/MIT/BSD/MPL-2.0),
  garminconnect and dependencies: see each package's dist-info in python/Lib/site-packages.
telemetry_parser (runtime/common/telemetry/telemetry_parser): MIT OR Apache-2.0.
Microsoft Visual C++ runtime (msvcp140.dll, vcruntime140*.dll in runtime/amd/bin):
  Visual Studio redistributable files (Microsoft.VC14x.CRT).
Fonts: none are shipped. Missing glyphs fall back to Windows system fonts (Segoe UI / Arial).
"""


AMD_ABI = 9
AMD_REQUIRED_EXPORTS = (
    "telem_amd_get_abi_version", "telem_amd_create", "telem_amd_process_frame", "telem_amd_update_map_style",
    "telem_amd_get_encoder_qp_feedback_diag", "telem_amd_set_preview_tap", "telem_amd_poll_preview_tap",
    "telem_amd_get_color_features", "telem_amd_get_color_pipeline", "telem_amd_probe_hevc_main10",
)


def verify_amd_dll(path: Path) -> dict[str, Any]:
    """Load the staged AMD DLL (with its app-local MSVC runtime) and check ABI, exports and colour features."""
    import ctypes
    import os
    handle = os.add_dll_directory(str(path.parent))
    try:
        dll = ctypes.CDLL(str(path))
        dll.telem_amd_get_abi_version.restype = ctypes.c_uint
        dll.telem_amd_get_build_info.restype = ctypes.c_char_p
        missing = [n for n in AMD_REQUIRED_EXPORTS if not hasattr(dll, n)]
        abi = int(dll.telem_amd_get_abi_version())
        features = int(dll.telem_amd_get_color_features())
        build_info = dll.telem_amd_get_build_info().decode("utf-8", "replace")
    finally:
        handle.close()
    if abi != AMD_ABI or missing or features & 0x3 != 0x3:
        raise RuntimeError(f"AMD DLL check failed: abi={abi} missing={missing} color_features=0x{features:x}")
    return {"abi": abi, "color_features": features, "required_exports": list(AMD_REQUIRED_EXPORTS),
            "build_info": build_info}


def build(commit: str, target: Path, with_python: bool) -> dict[str, Any]:
    if target.exists() and any(target.iterdir()):
        raise RuntimeError(f"SAFETY STOP: target {target} exists and is not empty")
    target.mkdir(parents=True, exist_ok=True)

    full_commit = export_commit(commit, target)
    for src_rel, dst_rel in WORKTREE_FILES:
        copy_checked(src_rel, dst_rel, target)
    for src_rel, dst_rel, pattern in WORKTREE_DIRS:
        src_dir = REPO / src_rel
        files = sorted(src_dir.glob(pattern))
        if not files:
            raise RuntimeError(f"Missing assets: {src_dir}/{pattern}")
        for f in files:
            copy_checked(f"{src_rel}/{f.name}", f"{dst_rel}/{f.name}", target)
    vc = find_vc_redist()
    for name in VC_REDIST_DLLS:
        shutil.copy2(vc / name, target / "runtime/amd/bin" / name)

    (target / "Start_SportCamHUD.cmd").write_text(LAUNCHER.replace("\n", "\r\n"), encoding="ascii")
    (target / "THIRD_PARTY_NOTICES.txt").write_text(NOTICES, encoding="utf-8")
    app_version = re.search(r"APP_VERSION\s*=\s*'([^']+)'", (target / "src/version.py").read_text()).group(1)
    (target / "build_meta.json").write_text(json.dumps({"commit": full_commit[:7]}), encoding="utf-8")
    amd_check = verify_amd_dll(target / "runtime/amd/bin/telem_amd_native.dll")
    ffmpeg_version = subprocess.run([str(target / "runtime/common/ffmpeg/ffmpeg.exe"), "-hide_banner", "-version"],
                                    capture_output=True, text=True).stdout.splitlines()[:1]

    py_info = bundle_python(target) if with_python else {"python_version": None, "packages": {}}

    violations = []
    for p in target.rglob("*"):
        if p.is_file():
            rel = p.relative_to(target).as_posix()
            if p.suffix.lower() in DENYLIST_EXTENSIONS and not rel.startswith("python/"):
                violations.append(rel)
            if any(s in p.name for s in DENYLIST_PATTERNS):
                violations.append(rel)
    if violations:
        raise RuntimeError("Denylist violations:\n" + "\n".join(violations))

    key_files = [
        "runtime/amd/bin/telem_amd_native.dll", "runtime/intel/bin/telem_intel_native.dll",
        "runtime/common/ffmpeg/ffmpeg.exe", "runtime/common/ffmpeg/ffprobe.exe", "libmpv-2.dll",
        "runtime/common/telemetry/gpmf/telem_gpmf_native.pyd",
        "runtime/common/telemetry/telemetry_parser/telemetry_parser/telemetry_parser.cp314-win_amd64.pyd",
        *[f"runtime/amd/bin/{n}" for n in VC_REDIST_DLLS],
    ]
    files = []
    total = 0
    for p in sorted(target.rglob("*")):
        if p.is_file():
            size = p.stat().st_size
            total += size
            rel = p.relative_to(target).as_posix()
            entry = {"path": rel, "size": size}
            if not rel.startswith("python/"):
                entry["sha256"] = sha256(p)
            files.append(entry)
    manifest = {
        "schema": "sportcamhud_portable_manifest_v3",
        "source_commit": full_commit,
        "app_version": app_version,
        "python": py_info,
        "build_date_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        "amd_native": amd_check,
        "ffmpeg_version": ffmpeg_version[0] if ffmpeg_version else None,
        "binary_sources": {dst: str(REPO / src) for src, dst in WORKTREE_FILES},
        "key_sha256": {k: sha256(target / k) for k in key_files},
        "native_modules": ["runtime/common/telemetry/gpmf/telem_gpmf_native.pyd",
                           "runtime/common/telemetry/telemetry_parser/telemetry_parser/telemetry_parser.cp314-win_amd64.pyd"],
        "vc_redist_source": str(vc),
        "file_count": len(files) + 1,
        "total_bytes": total,
        "files": files,
    }
    (target / "portable_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return {"target": str(target), "commit": full_commit, "files": len(files) + 1,
            "total_mb": round(total / 1e6, 1), "app_version": app_version,
            "python": py_info.get("python_version")}


def main() -> None:
    ap = argparse.ArgumentParser(description="SportCamHUD portable release packager")
    ap.add_argument("--commit", default="HEAD")
    ap.add_argument("--target", default=str(REPO / "dist" / "portable-stage"))
    ap.add_argument("--no-python", action="store_true", help="do not bundle the Python runtime")
    args = ap.parse_args()
    print(json.dumps(build(args.commit, Path(args.target).resolve(), not args.no_python), indent=2))


if __name__ == "__main__":
    main()
