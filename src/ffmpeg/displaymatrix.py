"""MP4 display-matrix (tkhd) writer for the NVIDIA rotation=180 CUDA fast-path.

The local FFmpeg build (2023-06-26) does NOT write a real Display Matrix when
frames pass through ``overlay_cuda`` (the source display-matrix side data is
dropped by the filter), and neither ``-metadata:s:v:0 rotate=180`` nor
``-display_rotation`` (input-side in this build) can create one in the output
container. The reliable local method is to write the rotation directly into the
video track's ``tkhd`` matrix field — a fixed 36-byte field, so the box sizes
are unchanged.

The byte layout is the one movenc itself produces for rotation 180
(verified against both ``-display_rotation`` transcodes and the GoPro source):

    [0, -1.0, 0, 0, 0, -1.0, 0, W, H]

where the last two values are the display translation in 16.16 fixed point.

Hardening guarantees:
- the MP4 atom tree is fully bounds-checked; an unknown/truncated structure or a
  missing video track is a controlled failure (returns False, file untouched);
- only the video track (hdlr == 'vide') is modified, never a wrong track;
- the write is atomic (temp file in the same directory + os.replace), so a
  failure cannot leave a corrupted file;
- the written matrix is verified by re-reading and re-parsing the file; True is
  returned only when the video-track matrix bytes match the expected 180-deg
  matrix.
"""

from __future__ import annotations

import os
import struct
from pathlib import Path
from typing import Optional

_MATRIX_LEN = 36


def _u32(b: bytes, off: int) -> int:
    return int.from_bytes(b[off:off + 4], "big")


def _rot180_matrix_bytes(width: int, height: int) -> bytes:
    """36-byte rotation-180 display matrix with (W, H) 16.16 translation."""
    if width <= 0 or height <= 0:
        raise ValueError(f"invalid display dimensions: {width}x{height}")
    neg1 = struct.pack(">i", -1 << 16)
    z = b"\x00\x00\x00\x00"
    wval = struct.pack(">I", width << 16)
    hval = struct.pack(">I", height << 16)
    matrix = z + neg1 + z + z + z + neg1 + z + wval + hval
    assert len(matrix) == _MATRIX_LEN
    return matrix


def _iter_boxes(b: bytes, start: int, end: int):
    """Yield (box_start, type, payload_start, payload_end) with bounds checks.

    Stops (without raising) when the remaining data is truncated or a box would
    overrun *end* — callers treat that as a controlled failure.
    """
    off = start
    while off < end:
        if off + 8 > end:
            return
        size = _u32(b, off)
        typ = b[off + 4:off + 8].decode("latin1")
        hdr = 8
        if size == 1:
            if off + 16 > end:
                return
            size = int.from_bytes(b[off + 8:off + 16], "big")
            hdr = 16
        elif size == 0:
            size = end - off
        if size < hdr or off + size > end:
            return
        yield off, typ, off + hdr, off + size
        next_off = off + size
        if next_off <= off:  # guard against zero-progress loop
            return
        off = next_off


def find_video_tkhd_matrix(b: bytes) -> Optional[tuple[int, int]]:
    """Return (matrix_offset, matrix_end) of the video track's tkhd, or None.

    Walks moov -> trak -> [tkhd, mdia->hdlr] and only considers tracks whose
    hdlr handler is 'vide'. Bounds-checked: any truncated/invalid structure or a
    tkhd whose matrix field would overrun its box yields None (controlled
    failure). Never touches non-video tracks.
    """
    for moov_start, moov_typ, moov_p, moov_end in _iter_boxes(b, 0, len(b)):
        if moov_typ != "moov":
            continue
        for trak_start, trak_typ, trak_p, trak_end in _iter_boxes(b, moov_p, moov_end):
            if trak_typ != "trak":
                continue
            tkhd_range = None
            is_video = False
            for c_start, c_typ, c_p, c_end in _iter_boxes(b, trak_p, trak_end):
                if c_typ == "tkhd":
                    tkhd_range = (c_start, c_p, c_end)
                elif c_typ == "mdia":
                    for d_start, d_typ, d_p, d_end in _iter_boxes(b, c_p, c_end):
                        if d_typ == "hdlr" and d_p + 12 <= d_end:
                            if b[d_p + 8:d_p + 12].decode("latin1") == "vide":
                                is_video = True
            if tkhd_range and is_video:
                _, tkhd_p, tkhd_end = tkhd_range
                if tkhd_p >= tkhd_end:
                    continue
                version = b[tkhd_p]
                if version == 1:
                    matrix_off = tkhd_p + 4 + 8 + 8 + 4 + 4 + 8 + 2 + 2 + 2 + 2
                elif version == 0:
                    matrix_off = tkhd_p + 4 + 4 + 4 + 4 + 4 + 8 + 2 + 2 + 2 + 2
                else:
                    continue  # unsupported tkhd version -> controlled failure
                if matrix_off < 0 or matrix_off + _MATRIX_LEN > tkhd_end:
                    continue  # matrix would overrun the tkhd box -> ignore track
                return matrix_off, matrix_off + _MATRIX_LEN
    return None


def verify_rotation_180_displaymatrix(
    mp4_path: str | Path, width: int, height: int
) -> bool:
    """Re-parse an MP4 and confirm the video track carries the rotation-180 matrix."""
    try:
        data = Path(mp4_path).read_bytes()
    except OSError:
        return False
    rng = find_video_tkhd_matrix(data)
    if not rng:
        return False
    mo, me = rng
    return data[mo:me] == _rot180_matrix_bytes(width, height)


def write_rotation_180_displaymatrix(
    mp4_path: str | Path, width: int, height: int
) -> bool:
    """Write (atomically) and verify the rotation=180 display matrix.

    The matrix rotates the whole composite about the display centre (W, H), so
    after a player applies the display rotation the base video and the (already
    physically rotated) HUD both appear in their logical orientation.

    Returns True only after the written matrix has been re-read and verified.
    On any structural problem (invalid/truncated MP4, missing video track,
    matrix overrun) returns False WITHOUT modifying the file.
    """
    path = Path(mp4_path)
    try:
        data = path.read_bytes()
    except OSError:
        return False
    rng = find_video_tkhd_matrix(data)
    if not rng:
        return False
    mo, me = rng
    try:
        matrix = _rot180_matrix_bytes(width, height)
    except ValueError:
        return False

    buf = bytearray(data)
    buf[mo:me] = matrix

    # Transaction safety: write a temp file in the same directory, flush, then
    # atomically replace the target so a failure cannot corrupt the output.
    try:
        tmp = path.with_name(path.name + ".nvrot.tmp")
        with open(tmp, "wb") as fh:
            fh.write(bytes(buf))
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except OSError:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        return False

    # Mandatory verification: re-read and confirm the matrix is exactly what we
    # wrote. True is returned only when verification passes.
    return verify_rotation_180_displaymatrix(path, width, height)
