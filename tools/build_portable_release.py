"""SportCamHUD Canonical Production Portable Release Packager.

Builds an isolated, minimal production portable directory using a strict ALLOWLIST.
Excludes all development, test, scratch, native source, debug, and backup materials.
Enforces hard denylist and cryptographic hash verification.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

EXPECTED_INTEL_DLL_SHA256 = "113abafbab0c877bc406692a4f60d287041d7e6307912a1b6e790d602888ba4b"
OLD_FORBIDDEN_INTEL_SHA256 = "41658018ae4979071837dfef4e412c40a855771266380cf84595a66bf89c0cca"
EXPECTED_AMD_DLL_SHA256 = "90be5af56bb56a73cdc161a0508b0d6a2c71987be44a565712c37aa5b5d66647"

DENYLIST_DIR_NAMES = {
    "raporty", "tests", "scratch", "video", ".git", ".github",
    "build", "native", "__pycache__", ".pytest_cache", ".mypy_cache",
    ".vscode", "debug", "benchmarks", "mpv-dev", "include", "third_party"
}

DENYLIST_EXTENSIONS = {
    ".pdb", ".obj", ".exp", ".lib", ".ilk", ".map", ".log",
    ".tmp", ".bak", ".old", ".7z", ".rar", ".zip",
}

DENYLIST_EXACT_NAMES = {
    "ffplay.exe", "ltcdump.exe", "download_mpv.py", "mpv_test.py",
    "patch_controller.py", "run_real_gui_export_interactive.py",
    "test_fps.py", "test_player_mpv.py", "test_rotation_behavior.py",
    "build_native_gpmf.py", "telem_intel_native.dll.pre_quant_candidate",
    ".coverage"
}


def compute_sha256(file_path: Path | str) -> str:
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(1048576):
            h.update(chunk)
    return h.hexdigest()


def categorize_file(rel_path: str) -> str:
    norm = rel_path.replace("\\", "/").lower()
    if norm.startswith("runtime/common/"):
        return "COMMON_RUNTIME"
    if norm.startswith("runtime/amd/"):
        return "AMD_RUNTIME"
    if norm.startswith("runtime/intel/"):
        return "INTEL_RUNTIME"
    if norm.startswith("runtime/nvidia/"):
        return "NVIDIA_RUNTIME"
    if norm.startswith("runtime/"):
        return "RUNTIME_MANIFEST"
    if norm.endswith(".py"):
        return "PYTHON"
    if norm.startswith("src/assets/") or norm.startswith("presets/") or norm.startswith("wzor/") or norm == "def_layout.json":
        return "ASSET"
    if norm.startswith("license") or "readme" in norm:
        return "LICENSE"
    if norm.endswith(".cmd") or norm.endswith(".toml") or norm.endswith(".json"):
        return "CONFIG"
    if norm == "libmpv-2.dll":
        return "COMMON_RUNTIME"
    return "UNKNOWN"


def build_portable(source_dir: Path, target_dir: Path) -> Dict[str, Any]:
    print(f"[PACKAGER] Source directory: {source_dir}")
    print(f"[PACKAGER] Target directory: {target_dir}")

    # Safety Gate 1: target directory must not exist or be empty
    if target_dir.exists():
        entries = os.listdir(target_dir)
        if entries:
            raise RuntimeError(
                f"SAFETY STOP: Target directory {target_dir} already exists and is non-empty ({len(entries)} items). Aborting."
            )
    target_dir.mkdir(parents=True, exist_ok=True)

    copied_files: List[Tuple[Path, str]] = []

    # 1. Top-Level Allowlist
    top_level_allowed = [
        "SportCamHUD.py",
        "TeleMGP.py",
        "Start_SportCamHUD.cmd",
        "def_layout.json",
        "telemetry_fit.py",
        "telemetry_gpx.py",
        "libmpv-2.dll",
        "pyproject.toml",
        "README.md",
    ]
    for name in top_level_allowed:
        src_f = source_dir / name
        if not src_f.is_file():
            raise RuntimeError(f"Missing required top-level file: {src_f}")
        dst_f = target_dir / name
        shutil.copy2(src_f, dst_f)
        copied_files.append((dst_f, name))

    # 2. Presets Directory
    presets_src = source_dir / "presets"
    presets_dst = target_dir / "presets"
    presets_dst.mkdir(parents=True, exist_ok=True)
    for p_file in presets_src.glob("*.json"):
        dst_f = presets_dst / p_file.name
        shutil.copy2(p_file, dst_f)
        copied_files.append((dst_f, f"presets/{p_file.name}"))

    # 3. Wzor Directory
    wzor_src = source_dir / "wzor"
    wzor_dst = target_dir / "wzor"
    wzor_dst.mkdir(parents=True, exist_ok=True)
    bike_ico = wzor_src / "rower_ico.png"
    if bike_ico.exists():
        shutil.copy2(bike_ico, wzor_dst / "rower_ico.png")
        copied_files.append((wzor_dst / "rower_ico.png", "wzor/rower_ico.png"))

    # 4. Production src/ package (excluding native source, pycache)
    src_src = source_dir / "src"
    for root, dirs, files in os.walk(src_src):
        rel_root = os.path.relpath(root, source_dir)
        norm_rel = rel_root.replace("\\", "/")
        if "src/native" in norm_rel or "__pycache__" in norm_rel:
            continue
        dst_dir = target_dir / rel_root
        dst_dir.mkdir(parents=True, exist_ok=True)
        for f in files:
            src_file = Path(root) / f
            dst_file = dst_dir / f
            shutil.copy2(src_file, dst_file)
            rel_file = os.path.relpath(dst_file, target_dir).replace("\\", "/")
            copied_files.append((dst_file, rel_file))

    # 5. Production runtime/ directory
    runtime_explicit_files = [
        # Common
        ("runtime/common/ffmpeg/ffmpeg.exe", "runtime/common/ffmpeg/ffmpeg.exe"),
        ("runtime/common/ffmpeg/ffprobe.exe", "runtime/common/ffmpeg/ffprobe.exe"),
        ("runtime/common/licenses/README.txt", "runtime/common/licenses/README.txt"),
        ("runtime/common/telemetry/telemetry_parser/LICENSE-APACHE", "runtime/common/telemetry/telemetry_parser/LICENSE-APACHE"),
        ("runtime/common/telemetry/telemetry_parser/LICENSE-MIT", "runtime/common/telemetry/telemetry_parser/LICENSE-MIT"),
        ("runtime/common/telemetry/telemetry_parser/README.md", "runtime/common/telemetry/telemetry_parser/README.md"),
        ("runtime/common/telemetry/telemetry_parser/telemetry_parser/telemetry_parser.cp314-win_amd64.pyd", "runtime/common/telemetry/telemetry_parser/telemetry_parser/telemetry_parser.cp314-win_amd64.pyd"),
        ("runtime/common/telemetry/telemetry_parser/telemetry_parser/__init__.py", "runtime/common/telemetry/telemetry_parser/telemetry_parser/__init__.py"),
        # AMD
        ("runtime/amd/bin/telem_amd_native.dll", "runtime/amd/bin/telem_amd_native.dll"),
        ("runtime/amd/bin/libwinpthread-1.dll", "runtime/amd/bin/libwinpthread-1.dll"),
        ("runtime/amd/licenses/README.txt", "runtime/amd/licenses/README.txt"),
        # Intel
        ("runtime/intel/bin/telem_intel_native.dll", "runtime/intel/bin/telem_intel_native.dll"),
        ("runtime/intel/bin/avcodec-63.dll", "runtime/intel/bin/avcodec-63.dll"),
        ("runtime/intel/bin/avdevice-63.dll", "runtime/intel/bin/avdevice-63.dll"),
        ("runtime/intel/bin/avfilter-12.dll", "runtime/intel/bin/avfilter-12.dll"),
        ("runtime/intel/bin/avformat-63.dll", "runtime/intel/bin/avformat-63.dll"),
        ("runtime/intel/bin/avutil-61.dll", "runtime/intel/bin/avutil-61.dll"),
        ("runtime/intel/bin/swresample-7.dll", "runtime/intel/bin/swresample-7.dll"),
        ("runtime/intel/bin/swscale-10.dll", "runtime/intel/bin/swscale-10.dll"),
        ("runtime/intel/licenses/README.txt", "runtime/intel/licenses/README.txt"),
        # NVIDIA
        ("runtime/nvidia/bin/README.txt", "runtime/nvidia/bin/README.txt"),
        ("runtime/nvidia/licenses/README.txt", "runtime/nvidia/licenses/README.txt"),
    ]

    for rel_src, rel_dst in runtime_explicit_files:
        src_path = source_dir / rel_src
        dst_path = target_dir / rel_dst
        dst_path.parent.mkdir(parents=True, exist_ok=True)
        if not src_path.is_file():
            raise RuntimeError(f"Missing required runtime file: {src_path}")
        shutil.copy2(src_path, dst_path)
        copied_files.append((dst_path, rel_dst))

    # 6. Verify Critical Binary Hashes
    intel_dll = target_dir / "runtime" / "intel" / "bin" / "telem_intel_native.dll"
    h_intel = compute_sha256(intel_dll)
    if h_intel.lower() != EXPECTED_INTEL_DLL_SHA256.lower():
        raise RuntimeError(
            f"INTEL DLL HASH MISMATCH!\nExpected: {EXPECTED_INTEL_DLL_SHA256}\nFound:    {h_intel}"
        )
    if h_intel.lower() == OLD_FORBIDDEN_INTEL_SHA256.lower():
        raise RuntimeError("FATAL: Old non-quantizer Intel DLL was accidentally copied!")

    amd_dll = target_dir / "runtime" / "amd" / "bin" / "telem_amd_native.dll"
    h_amd = compute_sha256(amd_dll)
    if h_amd.lower() != EXPECTED_AMD_DLL_SHA256.lower():
        raise RuntimeError(
            f"AMD DLL HASH MISMATCH!\nExpected: {EXPECTED_AMD_DLL_SHA256}\nFound:    {h_amd}"
        )

    # 7. Generate Manifest (Phase 23)
    manifest_entries = []
    for f_path, rel_str in copied_files:
        sz = f_path.stat().st_size
        sha = compute_sha256(f_path)
        cat = categorize_file(rel_str)
        manifest_entries.append({
            "relative_path": rel_str,
            "size": sz,
            "sha256": sha,
            "category": cat,
        })

    # Sort manifest deterministically
    manifest_entries.sort(key=lambda x: x["relative_path"])
    manifest_path = target_dir / "runtime" / "portable_manifest.json"
    manifest_payload = {
        "$schema": "bikeridehud_portable_manifest_v2",
        "description": "Deterministic manifest of production SportCamHUD portable runtime files.",
        "file_count": len(manifest_entries) + 1,  # +1 for the manifest itself
        "files": manifest_entries,
    }
    with open(manifest_path, "w", encoding="utf-8") as mf:
        json.dump(manifest_payload, mf, indent=2)

    # Add manifest to manifest list self-check
    manifest_sz = manifest_path.stat().st_size
    manifest_sha = compute_sha256(manifest_path)
    manifest_payload["files"].append({
        "relative_path": "runtime/portable_manifest.json",
        "size": manifest_sz,
        "sha256": manifest_sha,
        "category": "RUNTIME_MANIFEST",
    })
    manifest_payload["files"].sort(key=lambda x: x["relative_path"])
    with open(manifest_path, "w", encoding="utf-8") as mf:
        json.dump(manifest_payload, mf, indent=2)

    # 8. Hard Denylist Safety Gate (Phase 14)
    violations = []
    total_target_files = 0
    total_target_bytes = 0

    for root, dirs, files in os.walk(target_dir):
        rel_root = os.path.relpath(root, target_dir).replace("\\", "/").lower()
        root_parts = rel_root.split("/")
        for d in dirs:
            if d.lower() in DENYLIST_DIR_NAMES:
                violations.append(f"Forbidden directory: {os.path.join(rel_root, d)}")
        for f in files:
            total_target_files += 1
            f_path = Path(root) / f
            sz = f_path.stat().st_size
            total_target_bytes += sz
            f_lower = f.lower()
            ext = os.path.splitext(f_lower)[1]
            if ext in DENYLIST_EXTENSIONS:
                violations.append(f"Forbidden extension: {os.path.join(rel_root, f)}")
            if f_lower in DENYLIST_EXACT_NAMES:
                violations.append(f"Forbidden exact file: {os.path.join(rel_root, f)}")
            for part in [".pre_quant_candidate", ".fresh-backup", ".golden-"]:
                if part in f_lower:
                    violations.append(f"Forbidden pattern '{part}': {os.path.join(rel_root, f)}")

    if violations:
        shutil.rmtree(target_dir, ignore_errors=True)
        raise RuntimeError(f"HARD DENYLIST VIOLATIONS DETECTED:\n" + "\n".join(violations))

    print(f"[PACKAGER] Successfully packaged {total_target_files} files, {total_target_bytes} bytes.")
    print(f"[PACKAGER] Intel DLL SHA256: {h_intel} (MATCH=YES)")
    print(f"[PACKAGER] AMD DLL SHA256:   {h_amd} (MATCH=YES)")
    print(f"[PACKAGER] Denylist check passed: 0 violations.")

    return {
        "file_count": total_target_files,
        "total_bytes": total_target_bytes,
        "intel_sha256": h_intel,
        "amd_sha256": h_amd,
        "manifest_path": str(manifest_path),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="SportCamHUD Clean Portable Release Packager")
    parser.add_argument("--source", default=r"C:\_DEV\SportCamHUD-portable", help="Source directory")
    parser.add_argument("--target", default=r"C:\_DEV\SportCamHUD-portable-clean", help="Target clean directory")
    args = parser.parse_args()

    source_dir = Path(args.source).resolve()
    target_dir = Path(args.target).resolve()

    res = build_portable(source_dir, target_dir)
    print(json.dumps(res, indent=2))


if __name__ == "__main__":
    main()
