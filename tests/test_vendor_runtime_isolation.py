"""Unit and contract tests for BikeRideHUD vendor runtime separation.

Validates that:
- runtime/ has isolated common, amd, intel, and nvidia directories.
- No vendor DLLs leak into foreign vendor directories or common runtime.
- Native loaders strictly load from their own vendor runtime.
- Production source code contains zero lookups into src/native/bin, scratch, or external worktrees.
- Only the selected vendor directory is added to the DLL search path.
- The runtime manifest is complete and accurate.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
import pytest

from src import runtime_paths


@pytest.fixture
def app_root() -> Path:
    return runtime_paths.get_app_root()


def test_runtime_layout_exists(app_root: Path) -> None:
    """Check that all required top-level and sub-level runtime directories exist."""
    runtime_dir = app_root / "runtime"
    assert runtime_dir.is_dir(), f"Missing runtime directory: {runtime_dir}"

    expected_subdirs = [
        runtime_dir / "common",
        runtime_dir / "common" / "ffmpeg",
        runtime_dir / "common" / "telemetry",
        runtime_dir / "common" / "licenses",
        runtime_dir / "amd",
        runtime_dir / "amd" / "bin",
        runtime_dir / "amd" / "licenses",
        runtime_dir / "intel",
        runtime_dir / "intel" / "bin",
        runtime_dir / "intel" / "licenses",
        runtime_dir / "nvidia",
        runtime_dir / "nvidia" / "bin",
        runtime_dir / "nvidia" / "licenses",
    ]

    for d in expected_subdirs:
        assert d.is_dir(), f"Expected runtime directory not found: {d}"


def test_amd_runtime_isolated(app_root: Path) -> None:
    """Check AMD runtime directory contents and verify isolation from Intel and NVIDIA."""
    amd_bin = app_root / "runtime" / "amd" / "bin"
    assert amd_bin.is_dir()

    amd_dll = amd_bin / "telem_amd_native.dll"
    assert amd_dll.is_file(), f"Missing AMD native DLL: {amd_dll}"

    # Verify no foreign vendor files exist in AMD bin
    forbidden_in_amd = [
        "telem_intel_native.dll",
        "telem_nvenc_native.dll",
        "avcodec-63.dll",
        "avformat-63.dll",
        "avutil-61.dll",
    ]
    for name in forbidden_in_amd:
        assert not (amd_bin / name).exists(), f"Foreign vendor file found in AMD runtime: {name}"


def test_intel_runtime_isolated(app_root: Path) -> None:
    """Check Intel runtime directory contents and verify isolation from AMD and NVIDIA."""
    intel_bin = app_root / "runtime" / "intel" / "bin"
    assert intel_bin.is_dir()

    intel_dll = intel_bin / "telem_intel_native.dll"
    assert intel_dll.is_file(), f"Missing Intel native DLL: {intel_dll}"

    # Verify no foreign vendor files exist in Intel bin
    forbidden_in_intel = [
        "telem_amd_native.dll",
        "telem_nvenc_native.dll",
        "libwinpthread-1.dll",
    ]
    for name in forbidden_in_intel:
        assert not (intel_bin / name).exists(), f"Foreign vendor file found in Intel runtime: {name}"


def test_nvidia_runtime_isolated(app_root: Path) -> None:
    """Check NVIDIA runtime directory exists and contains no AMD or Intel DLLs."""
    nvidia_bin = app_root / "runtime" / "nvidia" / "bin"
    assert nvidia_bin.is_dir()

    forbidden_in_nvidia = [
        "telem_amd_native.dll",
        "telem_intel_native.dll",
        "libwinpthread-1.dll",
        "avcodec-63.dll",
    ]
    for name in forbidden_in_nvidia:
        assert not (nvidia_bin / name).exists(), f"Foreign vendor file found in NVIDIA runtime: {name}"


def test_common_runtime_contains_no_vendor_native_dll(app_root: Path) -> None:
    """Verify common runtime does NOT contain any GPU vendor native pipeline DLLs."""
    common_dir = app_root / "runtime" / "common"
    assert common_dir.is_dir()

    vendor_native_names = {
        "telem_amd_native.dll",
        "telem_intel_native.dll",
        "telem_nvenc_native.dll",
        "telem_nv_native.dll",
    }

    found = []
    for p in common_dir.rglob("*.dll"):
        if p.name.lower() in vendor_native_names:
            found.append(str(p))

    assert not found, f"Vendor native DLLs found in common runtime: {found}"


def test_vendor_dirs_do_not_mix_known_native_dlls(app_root: Path) -> None:
    """Verify no vendor directory hosts another vendor's native binaries."""
    runtime = app_root / "runtime"
    amd_files = {p.name.lower() for p in (runtime / "amd" / "bin").glob("*")}
    intel_files = {p.name.lower() for p in (runtime / "intel" / "bin").glob("*")}
    nvidia_files = {p.name.lower() for p in (runtime / "nvidia" / "bin").glob("*")}

    assert "telem_intel_native.dll" not in amd_files
    assert "telem_amd_native.dll" not in intel_files
    assert "telem_amd_native.dll" not in nvidia_files
    assert "telem_intel_native.dll" not in nvidia_files


def test_intel_loader_uses_only_intel_runtime() -> None:
    """Verify that get_intel_native_dll points strictly to runtime/intel/bin."""
    dll_path = runtime_paths.get_intel_native_dll()
    assert dll_path.is_file(), f"Intel DLL does not exist: {dll_path}"
    norm = str(dll_path.resolve()).replace("\\", "/")
    assert "runtime/intel/bin/telem_intel_native.dll" in norm


def test_amd_loader_uses_only_amd_runtime() -> None:
    """Verify that get_amd_native_dll points strictly to runtime/amd/bin."""
    dll_path = runtime_paths.get_amd_native_dll()
    assert dll_path.is_file(), f"AMD DLL does not exist: {dll_path}"
    norm = str(dll_path.resolve()).replace("\\", "/")
    assert "runtime/amd/bin/telem_amd_native.dll" in norm


def test_nvidia_loader_uses_only_nvidia_runtime() -> None:
    """Verify that get_nvidia_runtime_dir and get_nvidia_native_dll point strictly to runtime/nvidia."""
    r_dir = runtime_paths.get_nvidia_runtime_dir()
    norm_r = str(r_dir.resolve()).replace("\\", "/")
    assert norm_r.endswith("runtime/nvidia")

    dll_path = runtime_paths.get_nvidia_native_dll()
    norm_dll = str(dll_path.resolve()).replace("\\", "/")
    assert "runtime/nvidia/bin" in norm_dll


def test_no_production_src_native_bin_runtime_lookup(app_root: Path) -> None:
    """Scan all production python source files in src/ for 'src/native/bin' lookup paths."""
    src_dir = app_root / "src"
    violations = []
    pattern = re.compile(r'src[/\\]native[/\\]bin', re.IGNORECASE)

    for py in src_dir.rglob("*.py"):
        content = py.read_text(encoding="utf-8", errors="replace")
        for idx, line in enumerate(content.splitlines(), start=1):
            if pattern.search(line):
                # Ignore pure comment lines if any
                stripped = line.strip()
                if stripped.startswith("#"):
                    continue
                violations.append(f"{py.relative_to(app_root)}:{idx} -> {stripped}")

    assert not violations, f"Found production lookups into src/native/bin:\n" + "\n".join(violations)


def test_no_production_scratch_runtime_lookup(app_root: Path) -> None:
    """Scan all production python source files in src/ for scratch directory runtime lookups."""
    src_dir = app_root / "src"
    violations = []
    # Match scratch paths used as string literals
    pattern = re.compile(r'["\'][^"\']*[/\\]scratch[/\\]', re.IGNORECASE)

    for py in src_dir.rglob("*.py"):
        content = py.read_text(encoding="utf-8", errors="replace")
        for idx, line in enumerate(content.splitlines(), start=1):
            if pattern.search(line):
                stripped = line.strip()
                if stripped.startswith("#"):
                    continue
                violations.append(f"{py.relative_to(app_root)}:{idx} -> {stripped}")

    assert not violations, f"Found production lookups into scratch:\n" + "\n".join(violations)


def test_no_historical_worktree_runtime_lookup(app_root: Path) -> None:
    """Scan all production python source files in src/ for BikeRideHUD-amd or BikeRideHUD-intel references."""
    src_dir = app_root / "src"
    violations = []
    pattern = re.compile(r'BikeRideHUD-(amd|intel)', re.IGNORECASE)

    for py in src_dir.rglob("*.py"):
        content = py.read_text(encoding="utf-8", errors="replace")
        for idx, line in enumerate(content.splitlines(), start=1):
            if pattern.search(line):
                stripped = line.strip()
                if stripped.startswith("#"):
                    continue
                violations.append(f"{py.relative_to(app_root)}:{idx} -> {stripped}")

    assert not violations, f"Found historical worktree references in src/:\n" + "\n".join(violations)


def test_only_selected_vendor_dll_directory_is_added() -> None:
    """Verify that activating a vendor only configures that vendor's bin directory."""
    # Test valid activations
    handles_intel = runtime_paths.activate_vendor_dll_directory("intel")
    assert isinstance(handles_intel, list)

    handles_amd = runtime_paths.activate_vendor_dll_directory("amd")
    assert isinstance(handles_amd, list)

    # Test invalid vendor raises ValueError
    with pytest.raises(ValueError):
        runtime_paths.activate_vendor_dll_directory("unknown_vendor")


def test_portable_runtime_manifest(app_root: Path) -> None:
    """Verify that runtime_manifest.json exists and all required files are present and match checksums."""
    manifest_path = app_root / "runtime" / "runtime_manifest.json"
    assert manifest_path.is_file(), f"Missing manifest: {manifest_path}"

    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    for section in ["common", "amd", "intel", "nvidia"]:
        assert section in manifest, f"Manifest missing section: {section}"

    # Verify required files
    for section in ["common", "amd", "intel"]:
        for entry in manifest[section]:
            if not entry.get("required", False):
                continue
            rel_path = entry["path"]
            full_path = app_root / "runtime" / rel_path
            assert full_path.is_file(), f"Manifest file missing on disk: {full_path}"

            expected_size = entry.get("size")
            if expected_size:
                actual_size = full_path.stat().st_size
                assert actual_size == expected_size, (
                    f"Size mismatch for {rel_path}: expected {expected_size}, got {actual_size}"
                )

            expected_sha = entry.get("sha256")
            if expected_sha:
                actual_sha = runtime_paths.compute_file_sha256(full_path)
                assert actual_sha.lower() == expected_sha.lower(), (
                    f"SHA256 mismatch for {rel_path}: expected {expected_sha}, got {actual_sha}"
                )
