"""Archive current Git-tracked files, excluding Python bytecode.

This is a source snapshot, not a portable runtime distribution. Tracked native
binaries (including .pyd) are preserved; ignored runtime files are not included.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import zipfile


def source_members(root: Path) -> list[Path]:
    tracked = subprocess.check_output(["git", "ls-files", "-z"], cwd=root)
    members = []
    for name in tracked.decode("utf-8").split("\0"):
        if not name:
            continue
        relative = Path(name)
        if "__pycache__" in {part.lower() for part in relative.parts}:
            continue
        if relative.suffix.lower() in {".pyc", ".pyo"}:
            continue
        if (root / relative).is_file():
            members.append(relative)
    return members


def create_source_archive(root: Path, output: Path) -> int:
    root, output = root.resolve(), output.resolve()
    members = source_members(root)
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "x", compression=zipfile.ZIP_DEFLATED) as archive:
        for relative in members:
            if (root / relative).resolve() != output:
                archive.write(root / relative, relative.as_posix())
    return len(members)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    print(f"Archived {create_source_archive(args.root, args.output)} tracked files")
