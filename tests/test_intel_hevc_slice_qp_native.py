"""Native HEVC Slice QP parser (telem_intel_native.dll) against real bitstreams.

Reference per frame: FFmpeg ``trace_headers`` (independent CBS parser), from
which SliceQpY = 26 + init_qp_minus26 + slice_qp_delta is weighted by the CTUs
each slice segment covers, exactly as the native parser defines it.
"""
from __future__ import annotations

import ctypes
import os
from pathlib import Path
import random
import re
import subprocess
import tempfile

try:
    import pytest
except ImportError:  # helpers are reused by tools/run_intel_hevc_qp_ab.py outside pytest
    pytest = None

ROOT = Path(__file__).resolve().parents[1]
DLL = Path(os.environ.get("TELEM_INTEL_NATIVE_DLL", ROOT / "runtime/intel/bin/telem_intel_native.dll"))
FFMPEG = ROOT / "runtime/common/ffmpeg/ffmpeg.exe"
INTEL_SAMPLE = ROOT / "Raporty/intel_hevc_qp_20261017/ab/hevc_fast_on_0.mp4"


def _skip(reason: str):
    if pytest is None:
        raise RuntimeError(reason)
    pytest.skip(reason)


def _lib():
    if not DLL.exists() or not FFMPEG.exists():
        _skip("native DLL or ffmpeg missing")
    os.add_dll_directory(str(DLL.parent))
    lib = ctypes.CDLL(str(DLL))
    if not hasattr(lib, "intel_native_hevc_slice_qp_selftest"):
        _skip("DLL without Slice QP self-test hook")
    from src.ffmpeg.intel_native_exporter import IntelHevcSliceQpStats
    lib.intel_native_hevc_slice_qp_selftest.argtypes = [ctypes.c_char_p, ctypes.c_uint32,
                                                         ctypes.POINTER(ctypes.c_double), ctypes.c_int]
    lib.intel_native_hevc_slice_qp_selftest.restype = ctypes.c_int
    lib.intel_native_get_hevc_slice_qp.argtypes = [ctypes.POINTER(IntelHevcSliceQpStats)]
    return lib, IntelHevcSliceQpStats


def native_parse(data: bytes):
    lib, Stats = _lib()
    out = (ctypes.c_double * 100000)()
    n = lib.intel_native_hevc_slice_qp_selftest(data, len(data), out, len(out))
    stats = Stats()
    lib.intel_native_get_hevc_slice_qp(ctypes.byref(stats))
    return [out[i] for i in range(n)], stats


def to_annexb(src: Path, dst: Path, frames: int | None = None) -> bytes:
    cmd = [str(FFMPEG), "-nostdin", "-v", "error", "-y", "-i", str(src), "-map", "0:v:0", "-c:v", "copy",
           "-bsf:v", "hevc_mp4toannexb", "-f", "hevc"]
    if frames:
        cmd[cmd.index("-c:v"):cmd.index("-c:v")] = ["-frames:v", str(frames)]
    subprocess.run(cmd + [str(dst)], check=True)
    return dst.read_bytes()


def x265(dst: Path, params: str, frames: int = 48) -> bytes:
    subprocess.run([str(FFMPEG), "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i",
                    f"testsrc2=size=640x360:rate=30,noise=alls=20:allf=t", "-frames:v", str(frames),
                    "-pix_fmt", "yuv420p10le", "-c:v", "libx265", "-profile:v", "main10",
                    "-x265-params", "log-level=error:" + params, "-f", "hevc", str(dst)], check=True)
    return dst.read_bytes()


_TRACE = re.compile(r"\]\s+\d+\s+(\w+(?:\[\d+\])?)\s+[01]+\s+=\s+(-?\d+)")


def reference_frames(path: Path):
    """Per-frame (weighted slice QP, slice types) from FFmpeg trace_headers, in decode order."""
    log = subprocess.run([str(FFMPEG), "-nostdin", "-v", "verbose", "-f", "hevc", "-i", str(path),
                          "-c:v", "copy", "-bsf:v", "trace_headers", "-f", "null", "-"],
                         capture_output=True, text=True, encoding="utf-8", errors="replace").stderr
    pps, sps, frames = {}, {}, []
    cur_pps = cur_sps = None
    seg = {}
    unit = None
    nal_type = None

    def flush_slice():
        if not seg or "slice_type" not in seg and not seg.get("dependent"):
            return
        p = pps[seg["pps"]]; s = sps[p["sps"]]
        ctb = 1 << (s["min_cb"] + 3 + s["diff_cb"])
        ctus = -(-s["w"] // ctb) * -(-s["h"] // ctb)
        if seg["first"]:
            frames.append({"ctus": ctus, "segs": [], "poc_lsb": seg.get("poc", 0), "nal": seg["nal"],
                           "log2_lsb": s["log2_lsb"]})
        qp = frames[-1]["segs"][-1][1] if seg.get("dependent") else 26 + p["init_qp"] + seg["qp_delta"]
        st = None if seg.get("dependent") else seg["slice_type"]
        frames[-1]["segs"].append((seg.get("addr", 0), qp, st))

    for line in log.splitlines():
        m = _TRACE.search(line)
        if not m:
            continue
        key, val = m.group(1), int(m.group(2))
        if key == "nal_unit_type":
            nal_type = val
        elif key == "sps_seq_parameter_set_id":
            unit = "sps"; cur_sps = {"id": val}; sps[val] = cur_sps
        elif key == "pps_pic_parameter_set_id":
            unit = "pps"; cur_pps = {"id": val}; pps[val] = cur_pps
        elif key == "first_slice_segment_in_pic_flag":
            flush_slice(); unit = "slice"; seg = {"first": val, "nal": nal_type}
        elif unit == "sps":
            mapping = {"pic_width_in_luma_samples": "w", "pic_height_in_luma_samples": "h",
                       "log2_min_luma_coding_block_size_minus3": "min_cb",
                       "log2_diff_max_min_luma_coding_block_size": "diff_cb",
                       "log2_max_pic_order_cnt_lsb_minus4": "log2_lsb"}
            if key in mapping:
                cur_sps[mapping[key]] = val + (4 if key.startswith("log2_max_pic_order") else 0)
        elif unit == "pps":
            if key == "pps_seq_parameter_set_id": cur_pps["sps"] = val
            elif key == "init_qp_minus26": cur_pps["init_qp"] = val
        elif unit == "slice":
            mapping = {"slice_pic_parameter_set_id": "pps", "dependent_slice_segment_flag": "dependent",
                       "slice_segment_address": "addr", "slice_type": "slice_type", "slice_qp_delta": "qp_delta",
                       "slice_pic_order_cnt_lsb": "poc"}
            if key in mapping:
                seg[mapping[key]] = val
    flush_slice()
    # Frame type by prediction structure (independent of the native RPS derivation):
    # intra if all slices are I; B if decoded after a picture with higher POC (reordered,
    # so it predicts from the future); otherwise P. Full POC per H.265 8.3.1 (TemporalId 0).
    out, max_poc, prev_lsb, prev_msb = [], None, 0, 0
    for f in frames:
        segs = f["segs"]
        w = sum(qp * ((segs[i + 1][0] if i + 1 < len(segs) else f["ctus"]) - a) for i, (a, qp, _) in enumerate(segs))
        types = {t for _, _, t in segs if t is not None}
        lsb, half = f["poc_lsb"], 1 << (f["log2_lsb"] - 1)
        if f["nal"] in (19, 20):
            msb = 0
        elif lsb < prev_lsb and prev_lsb - lsb >= half:
            msb = prev_msb + 2 * half
        elif lsb > prev_lsb and lsb - prev_lsb > half:
            msb = prev_msb - 2 * half
        else:
            msb = prev_msb
        poc = msb + lsb
        if f["nal"] > 14 or f["nal"] % 2 == 1 and f["nal"] not in (7, 9):
            prev_lsb, prev_msb = lsb, msb
        if types == {2}:
            kind = "I"
            max_poc = poc if f["nal"] in (19, 20) else max(poc, max_poc if max_poc is not None else poc)
        else:
            kind = "B" if max_poc is not None and poc < max_poc else "P"
            max_poc = poc if max_poc is None else max(max_poc, poc)
        out.append((w / f["ctus"], kind, len(segs)))
    return out


def _compare(path: Path, data: bytes):
    native, stats = native_parse(data)
    ref = reference_frames(path)
    assert len(native) == len(ref) > 0
    for i, (n, (r, _, _)) in enumerate(zip(native, ref)):
        assert n >= 0 and abs(n - r) < 1e-9, f"frame {i}: native={n} reference={r}"
    assert stats.rejected_frames == 0 and stats.parse_errors == 0
    return native, ref, stats


def test_real_intel_qsv_hevc_main10_packets():
    if not INTEL_SAMPLE.exists():
        pytest.skip("run tools/run_intel_hevc_qp_ab.py first")
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "intel.hevc"
        native, ref, stats = _compare(path, to_annexb(INTEL_SAMPLE, path, frames=120))
        assert {t for _, t, _ in ref} == {"I", "P"}  # Intel: generalized-B slices, no reordering
        assert stats.type_frames[0] == 0
        assert stats.type_frames[2] == sum(t == "I" for _, t, _ in ref)
        assert stats.type_frames[1] == sum(t == "P" for _, t, _ in ref)
        assert stats.bit_depth_luma == 10


def test_x265_main10_multi_slice_with_b_frames_and_varying_qp():
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "multi.hevc"
        data = x265(path, "slices=4:bframes=3:b-adapt=0:crf=30:aq-mode=2:keyint=24:min-keyint=24:no-open-gop=1:scenecut=0")
        native, ref, stats = _compare(path, data)
        assert stats.max_slices_per_frame == 4 and all(n == 4 for _, _, n in ref)
        assert {t for _, t, _ in ref} == {"I", "P", "B"}
        for idx, kind in ((0, "B"), (1, "P"), (2, "I")):
            assert stats.type_frames[idx] == sum(t == kind for _, t, _ in ref), kind
        assert stats.type_frames[0] > 0
        assert len({round(q, 6) for q in native}) > 1  # x265 CRF really varies slice QP


def test_parameter_set_change_mid_stream():
    with tempfile.TemporaryDirectory() as d:
        a = x265(Path(d) / "a.hevc", "crf=22:keyint=12", frames=24)
        b = x265(Path(d) / "b.hevc", "qp=40:keyint=12:slices=2", frames=24)
        path = Path(d) / "ab.hevc"
        path.write_bytes(a + b)
        native, ref, _ = _compare(path, a + b)
        assert max(native[24:]) > max(native[:24])


def test_missing_pps_yields_no_samples_not_guesses():
    with tempfile.TemporaryDirectory() as d:
        data = x265(Path(d) / "s.hevc", "crf=28", frames=10)
    # Drop every PPS NAL (type 34): slices must be rejected, never parsed with defaults.
    parts = re.split(b"(?=\x00\x00\x01)", data)
    kept = b"".join(p for p in parts if not (len(p) > 3 and ((p[3] >> 1) & 0x3F) == 34))
    native, stats = native_parse(kept)
    assert native and all(v == -1.0 for v in native)
    assert stats.frames == 0 and stats.rejected_frames == len(native) and not stats.valid


def test_truncated_and_corrupted_streams_never_crash_or_fabricate():
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "s.hevc"
        data = x265(path, "crf=28:slices=2", frames=12)
        good = reference_frames(path)
    rng = random.Random(1234)
    for cut in (5, 20, 60, 200, len(data) // 3):
        native, _ = native_parse(data[:cut])
        assert all(v == -1.0 or any(abs(v - r) < 1e-9 for r, _, _ in good) for v in native)
    for _ in range(30):
        buf = bytearray(data)
        for _ in range(8):
            buf[rng.randrange(len(buf))] = rng.randrange(256)
        native, stats = native_parse(bytes(buf))
        assert all(v == -1.0 or -12.0 <= v <= 51.0 for v in native)
    native, stats = native_parse(bytes(rng.randrange(256) for _ in range(50000)))
    assert stats.frames == 0 or all(-12.0 <= v <= 51.0 for v in native if v != -1.0)
    native, stats = native_parse(b"")
    assert native == [] and stats.frames == 0
