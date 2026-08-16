"""ETAP 5W — device-refcount isolation (ctypes create+close, no frame proc).

Loads telem_amd_native.dll directly, runs N create/close cycles with a given
debug-skip combo (AMD_DEBUG_NO_AMF / AMD_DEBUG_NO_MF), and reports the
"[TELEM AMD DLL] close: D3D11 device refcount=..." line after teardown.

If refcount > 1, something leaked a device reference -> device never destroyed
-> driver kernel objects (events/mutants/threads/sections) leak per cycle.
"""
from __future__ import annotations

import ctypes
import os
import sys
from ctypes import c_uint, c_void_p, c_wchar_p, c_int

DLL = r"C:\_DEV\TeleM\native\d3d11_amf_pipeline\bin\telem_amd_native.dll"


def main() -> int:
    combo = sys.argv[1] if len(sys.argv) > 1 else "base"
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 3

    flags = ("AMD_POOL_LIFECYCLE_STATS", "AMD_DEBUG_NO_AMF", "AMD_DEBUG_NO_MF",
             "AMD_DEBUG_NO_VP", "AMD_VP_POOL_SIZE", "AMD_AMF_MODE",
             "AMD_GPU_TIMESTAMP_PROFILE", "AMD_NATIVE_FRAME_ACCOUNTING",
             "AMD_VP_STATE_MODE", "AMD_MAP_PATH", "AMD_MAP_FILTER",
             "AMD_COMPOSE_5Q", "AMD_CHART_PATH", "AMD_GAUGE_PATH",
             "AMD_NATIVE_DIAGNOSTICS", "AMD_NATIVE_PROFILING")
    for f in flags:
        os.environ.pop(f, None)
    os.environ["AMD_POOL_LIFECYCLE_STATS"] = "1"
    os.environ["AMD_VP_POOL_SIZE"] = "8"
    os.environ["AMD_AMF_MODE"] = "BYPASS"
    if combo in ("noamf", "both", "novp"):
        os.environ["AMD_DEBUG_NO_AMF"] = "1"
    if combo in ("nomf", "both", "novp"):
        os.environ["AMD_DEBUG_NO_MF"] = "1"
    if combo == "novp":
        os.environ["AMD_DEBUG_NO_VP"] = "1"

    if hasattr(os, "add_dll_directory"):
        try:
            os.add_dll_directory(r"C:\tools\mingw64\bin")
        except Exception:
            pass
    dll = ctypes.CDLL(DLL)
    dll.telem_amd_create.restype = c_void_p
    dll.telem_amd_create.argtypes = [c_wchar_p, c_wchar_p, c_uint, c_uint, c_uint, c_uint]
    dll.telem_amd_close.restype = c_int
    dll.telem_amd_close.argtypes = [c_void_p]

    import io
    import contextlib

    sys.path.insert(0, r"C:\_DEV\TeleM\scratch")
    from etap5w_handles import handle_type_counts  # noqa: E402

    refcounts = []
    for i in range(n):
        buf = io.StringIO()
        h0 = handle_type_counts().get("_TOTAL", 0)
        with contextlib.redirect_stdout(buf):
            h = dll.telem_amd_create(
                r"C:\_DEV\TeleM\Video\GX020079.mp4",
                f"C:\\_DEV\\TeleM\\Raporty\\AMD_ETAP5G\\l5w_devref_{combo}_{i}.mp4",
                3840, 2160, 30000, 1001)
            if not h:
                print(f"[{combo}] create NULL", flush=True)
                continue
            dll.telem_amd_close(h)
        h1 = handle_type_counts().get("_TOTAL", 0)
        txt = buf.getvalue()
        import re
        m = re.search(r"close: D3D11 device refcount=(\d+)", txt)
        rc = int(m.group(1)) if m else None
        refcounts.append(rc)
        print(f"[{combo}] cycle {i}: device refcount={rc} handles {h0}->{h1} "
              f"(delta {h1 - h0:+d})", flush=True)

    print(f"[{combo}] refcounts={refcounts}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
