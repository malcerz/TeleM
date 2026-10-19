"""Build an AMD DLL candidate with the canonical CMake source identity and C ABI.

Uses the same source list and optimization/link flags as the existing CMake
target. Does not replace the installed runtime. LLVM MinGW additionally needs
the UUID import libraries for GUID_NULL.
"""
import argparse
import datetime
import hashlib
import json
from pathlib import Path
import subprocess


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--toolchain", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    source = root / "native/d3d11_amf_pipeline"
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=True)
    inputs = ["CMakeLists.txt", "src/telem_amd_native.cpp", "src/d3d11_vp_pipeline.cpp",
              "src/d3d11_vp_pipeline.h", "src/d3d11_amf_encoder.cpp",
              "src/d3d11_amf_encoder.h", "src/telem_amd_build_info.h.in"]
    hashes = {name: hashlib.sha256((source / name).read_bytes()).hexdigest() for name in inputs}
    material = "".join(f"{name}:{hashes[name]}\n" for name in inputs)
    source_hash = hashlib.sha256(material.encode()).hexdigest()
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    build_id = f"telem-amd-native/1.0.0+{head[:12]}.src{source_hash[:12]}"
    text = (source / "src/telem_amd_build_info.h.in").read_text()
    values = {"PROJECT_VERSION": "1.0.0", "TELEM_BUILD_ID": build_id,
              "TELEM_BUILD_TIMESTAMP": datetime.datetime.now(datetime.timezone.utc).isoformat(),
              "TELEM_GIT_COMMIT": head, "TELEM_SOURCE_HASH": source_hash}
    for key, value in values.items():
        text = text.replace(f"@{key}@", value)
    (out / "telem_amd_build_info.h").write_text(text)
    compiler = args.toolchain.resolve() / "bin/clang++.exe"
    cmd = [str(compiler), "-shared", "-O2", "-std=c++17", "-static-libgcc", "-static-libstdc++",
           "-Wl,--no-insert-timestamp", "-I" + str(source / "include"), "-I" + str(source / "src"),
           "-I" + str(out), *[str(source / "src" / name) for name in
                              ("telem_amd_native.cpp", "d3d11_vp_pipeline.cpp", "d3d11_amf_encoder.cpp")],
           "-ld3d11", "-ldxgi", "-ld3dcompiler", "-lmfplat", "-lmfreadwrite", "-lmfuuid", "-lole32",
           "-luuid", "-ldxguid", "-o", str(out / "telem_amd_native.dll")]
    subprocess.run(cmd, check=True)
    manifest = {"command": cmd, "source_hash": source_hash, "source_files": hashes,
                "build_id": build_id, "abi": 9,
                "compiler": subprocess.check_output([str(compiler), "--version"], text=True),
                "dll_sha256": hashlib.sha256((out / "telem_amd_native.dll").read_bytes()).hexdigest()}
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
