"""MP4 display-matrix (tkhd) inspection & injection utility.

This build of FFmpeg drops the source Display Matrix when frames pass through
overlay_cuda, and neither `-metadata:s:v:0 rotate=180` nor `-display_rotation`
can write a real Display Matrix into the output container. The reliable local
method is to copy the source video track's tkhd matrix (which encodes rotation
180) into the output video track's tkhd. The matrix field is a fixed 36 bytes,
so the rewrite is in-place (box sizes unchanged).

Usage:
    python inject_displaymatrix.py dump <mp4>            # show video tkhd matrix
    python inject_displaymatrix.py inject <ref> <target> <out>   # copy matrix ref->target
    python inject_displaymatrix.py inject_rot180 <target> <out> <width> <height>   # write 180-degree rotation matrix
"""
from __future__ import annotations

import sys
from pathlib import Path


def _u32(b: bytes, off: int) -> int:
    return int.from_bytes(b[off:off + 4], "big")


def _set_u32(ba: bytearray, off: int, val: int) -> None:
    ba[off:off + 4] = val.to_bytes(4, "big")


def iter_boxes(b: bytes, start: int, end: int):
    """Yield (box_start, type, payload_start, payload_end)."""
    off = start
    while off + 8 <= end:
        size = _u32(b, off)
        typ = b[off + 4:off + 8].decode("latin1")
        if size == 1:
            size = int.from_bytes(b[off + 8:off + 16], "big")
            hdr = 16
        elif size == 0:
            size = end - off
            hdr = 8
        else:
            hdr = 8
        if size < hdr or off + size > end:
            break
        yield off, typ, off + hdr, off + size
        off += size


def find_video_tkhd(b: bytes) -> tuple[int, int] | None:
    """Find (matrix_offset, matrix_end) of the video track's tkhd, or None.

    Walks moov -> trak -> [tkhd, mdia->hdlr]. Only tracks whose hdlr handler
    is 'vide' are considered.
    """
    for moov_start, moov_typ, moov_p, moov_end in iter_boxes(b, 0, len(b)):
        if moov_typ != "moov":
            continue
        for trak_start, trak_typ, trak_p, trak_end in iter_boxes(b, moov_p, moov_end):
            if trak_typ != "trak":
                continue
            tkhd_range = None
            is_video = False
            for c_start, c_typ, c_p, c_end in iter_boxes(b, trak_p, trak_end):
                if c_typ == "tkhd":
                    tkhd_range = (c_start, c_p, c_end)
                elif c_typ == "mdia":
                    for d_start, d_typ, d_p, d_end in iter_boxes(b, c_p, c_end):
                        if d_typ == "hdlr" and d_p + 12 <= d_end:
                            handler = b[d_p + 8:d_p + 12].decode("latin1")
                            if handler == "vide":
                                is_video = True
            if tkhd_range and is_video:
                _, tkhd_p, tkhd_end = tkhd_range
                version = b[tkhd_p]
                # matrix starts after: version(1)+flags(3) + times/duration fields
                if version == 1:
                    matrix_off = tkhd_p + 4 + 8 + 8 + 4 + 4 + 8 + 2 + 2 + 2 + 2
                else:
                    matrix_off = tkhd_p + 4 + 4 + 4 + 4 + 4 + 8 + 2 + 2 + 2 + 2
                return matrix_off, matrix_off + 36
    return None


def fmt_matrix(b: bytes, off: int) -> str:
    words = []
    for i in range(9):
        v = int.from_bytes(b[off + i * 4:off + i * 4 + 4], "big", signed=True)
        words.append(f"{v:08x}")
    return " ".join(words)


def dump(path: str) -> None:
    b = Path(path).read_bytes()
    r = find_video_tkhd(b)
    if not r:
        print(f"{path}: video tkhd matrix not found")
        return
    mo, me = r
    print(f"{path}: video tkhd matrix @ {mo}: {fmt_matrix(b, mo)}")


def inject(ref_path: str, target_path: str, out_path: str) -> None:
    ref = Path(ref_path).read_bytes()
    tgt = bytearray(Path(target_path).read_bytes())
    rr = find_video_tkhd(ref)
    tr = find_video_tkhd(bytes(tgt))
    if not rr or not tr:
        print("matrix location not found in ref/target")
        sys.exit(1)
    rmo, rme = rr
    tmo, tme = tr
    tgt[tmo:tme] = ref[rmo:rme]
    Path(out_path).write_bytes(bytes(tgt))
    print(f"injected matrix into {out_path} @ {tmo}: {fmt_matrix(bytes(tgt), tmo)}")


def inject_rot180(target_path: str, out_path: str, width: int, height: int) -> None:
    """Write a 180-deg rotation display matrix (rotation about output center)
    into the video track's tkhd. Matrix (16.16 fixed point):

        [-1.0  0    0 ]
        [ 0   -1.0  0 ]
        [ W    H    1 ]
    """
    tgt = bytearray(Path(target_path).read_bytes())
    tr = find_video_tkhd(bytes(tgt))
    if not tr:
        print("video tkhd matrix location not found in target")
        sys.exit(1)
    tmo, tme = tr
    import struct
    neg1 = struct.pack(">i", -1 << 16)          # -1.0 (16.16)
    z = b"\x00\x00\x00\x00"
    wval = struct.pack(">I", width << 16)       # width  (16.16)
    hval = struct.pack(">I", height << 16)      # height (16.16)
    # Empirically verified layout (matches what movenc writes for rotation 180
    # and the GoPro source): [0, -1, 0, 0, 0, -1, 0, W, H]
    matrix = z + neg1 + z + z + z + neg1 + z + wval + hval
    assert len(matrix) == 36
    tgt[tmo:tme] = matrix
    Path(out_path).write_bytes(bytes(tgt))
    print(f"wrote rot180 matrix ({width}x{height}) into {out_path} @ {tmo}: {fmt_matrix(bytes(tgt), tmo)}")


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "dump":
        dump(sys.argv[2])
    elif len(sys.argv) == 5 and sys.argv[1] == "inject":
        inject(sys.argv[2], sys.argv[3], sys.argv[4])
    elif len(sys.argv) == 6 and sys.argv[1] == "inject_rot180":
        inject_rot180(sys.argv[2], sys.argv[3], int(sys.argv[4]), int(sys.argv[5]))
    else:
        print(__doc__)
        sys.exit(2)
