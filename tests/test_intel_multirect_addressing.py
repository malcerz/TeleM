import ctypes
import os
import pytest
from pathlib import Path

def _load_native():
    try:
        os.add_dll_directory(r"C:\_Dev\BikeRideHUD-intel\third_party\ffmpeg-9.0.1-full_build-shared\bin")
        os.add_dll_directory(r"C:\_Dev\BikeRideHUD-intel")
    except Exception:
        pass
    dll_path = Path(r"C:\_DEV\BikeRideHUD-intel-multirect\src\native\bin\telem_intel_native.dll")
    assert dll_path.exists(), f"DLL not found: {dll_path}"
    lib = ctypes.CDLL(str(dll_path))
    lib.intel_native_validate_subrect_addressing.argtypes = [
        ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
        ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int)
    ]
    lib.intel_native_validate_subrect_addressing.restype = ctypes.c_int
    return lib

@pytest.mark.parametrize("rect_name, l, t, r, b", [
    ("top_left", 0, 0, 100, 100),
    ("middle", 500, 400, 800, 600),
    ("right_edge", 2460, 200, 2560, 300),
    ("bottom_edge", 200, 1340, 400, 1440),
    ("one_pixel", 1234, 567, 1235, 568),
    ("odd_dimensions", 101, 203, 274, 456),  # width: 173, height: 253
])
def test_intel_multirect_subrect_addressing(rect_name, l, t, r, b):
    """Phase 5: Validate bit-exact D3D11 subrect addressing directly into full-pitch buffer."""
    lib = _load_native()
    out_diff = ctypes.c_int(-1)
    out_max_diff = ctypes.c_int(-1)

    ret = lib.intel_native_validate_subrect_addressing(
        l, t, r, b,
        ctypes.byref(out_diff), ctypes.byref(out_max_diff)
    )

    assert ret == 0, f"intel_native_validate_subrect_addressing failed with code {ret}"
    assert out_diff.value == 0, f"Rectangle {rect_name} [{l},{t},{r},{b}] had {out_diff.value} differing pixels"
    assert out_max_diff.value == 0, f"Rectangle {rect_name} max pixel difference was {out_max_diff.value}"

if __name__ == "__main__":
    lib = _load_native()
    test_cases = [
        ("top_left", 0, 0, 100, 100),
        ("middle", 500, 400, 800, 600),
        ("right_edge", 2460, 200, 2560, 300),
        ("bottom_edge", 200, 1340, 400, 1440),
        ("one_pixel", 1234, 567, 1235, 568),
        ("odd_dimensions", 101, 203, 274, 456),
    ]
    for name, l, t, r, b in test_cases:
        out_diff = ctypes.c_int(-1)
        out_max_diff = ctypes.c_int(-1)
        ret = lib.intel_native_validate_subrect_addressing(l, t, r, b, ctypes.byref(out_diff), ctypes.byref(out_max_diff))
        print(f"Test {name:16} [{l:4},{t:4},{r:4},{b:4}]: ret={ret} diff_pixels={out_diff.value} max_diff={out_max_diff.value} -> {'PASS' if ret==0 and out_diff.value==0 else 'FAIL'}")
