"""Print HEVC sample-entry colour boxes (colr/hvcC VUI-relevant) of an MP4 without loading mdat."""
import struct, sys

CONTAINERS = {b"moov", b"trak", b"mdia", b"minf", b"stbl", b"stsd"}

def walk(f, start, end, depth, out):
    pos = start
    while pos + 8 <= end:
        f.seek(pos)
        hdr = f.read(16)
        size, typ = struct.unpack(">I4s", hdr[:8])
        hlen = 8
        if size == 1:
            size = struct.unpack(">Q", hdr[8:16])[0]; hlen = 16
        elif size == 0:
            size = end - pos
        if typ in CONTAINERS:
            skip = 8 if typ == b"stsd" else 0
            walk(f, pos + hlen + skip, pos + size, depth + 1, out)
        elif typ in (b"hvc1", b"hev1"):
            # VisualSampleEntry header is 78 bytes after the box header
            walk(f, pos + hlen + 78, pos + size, depth + 1, out)
        elif typ == b"colr":
            f.seek(pos + hlen)
            body = f.read(size - hlen)
            ct = body[:4]
            if ct == b"nclx":
                p, t, m = struct.unpack(">HHH", body[4:10])
                full = body[10] >> 7
                out.append(f"colr nclx primaries={p} transfer={t} matrix={m} full_range={full}")
            else:
                out.append(f"colr {ct!r}")
        elif typ == b"hvcC":
            out.append(f"hvcC size={size}")
        pos += size

for path in sys.argv[1:]:
    with open(path, "rb") as f:
        f.seek(0, 2); end = f.tell()
        out = []
        walk(f, 0, end, 0, out)
    print(path, "->", out or ["NO colr box"])
