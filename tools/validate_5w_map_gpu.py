"""Windows/D3D11 map-style raster probe; AMF BYPASS, NUL output, no movie export.

Uses existing native diagnostic readback. No private Pillow pointers.
"""
from pathlib import Path
import ctypes as c
import json
import os
import sys
import time

import numpy as np
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.indicators.helpers import apply_map_shape, map_style_layers


class Probe:
    def __init__(self, dll_path):
        self.dll = c.CDLL(str(dll_path))
        self.bind("create", [c.c_wchar_p, c.c_wchar_p] + [c.c_uint] * 4, c.c_void_p)
        self.bind("close", [c.c_void_p], None)
        for name in ["set_decode_mode", "set_hud_mode", "set_hud_enabled", "set_amf_mode", "set_map_mode", "set_map_filter", "set_map_gpu_path", "set_map_rotate_mode"]:
            self.bind(name, [c.c_void_p, c.c_int])
        self.bind("set_map_heading", [c.c_void_p, c.c_float])
        self.bind("set_map_geometry", [c.c_void_p] + [c.c_uint] * 6)
        self.bind("update_map", [c.c_void_p, c.c_void_p] + [c.c_uint] * 3 + [c.c_void_p] * 2)
        self.bind("update_hud", [c.c_void_p, c.c_void_p] + [c.c_uint] * 3)
        self.bind("update_map_marker", [c.c_void_p, c.c_void_p] + [c.c_uint] * 5)
        self.bind("process_frame", [c.c_void_p, c.c_uint, c.c_int])
        self.bind("update_video_frame_p010", [c.c_void_p, c.c_void_p] + [c.c_uint] * 3 + [c.c_void_p])
        self.bind("get_hud_region_readback", [c.c_void_p] + [c.c_uint] * 4 + [c.c_void_p, c.c_uint])
        if hasattr(self.dll, "telem_amd_update_map_style"):
            self.bind("update_map_style", [c.c_void_p, c.c_void_p] + [c.c_uint] * 3 + [c.c_float] * 4)
        self.bind("read_video_sample", [c.c_void_p] + [c.c_void_p] * 10)
        # Real GoPro/D3D11 decode. NUL.h265 is the Windows discard device;
        # no intermediate encoded file or audio is created (AMF BYPASS).
        self.h = self.create(r"F:\GoPro\2026-10-07\GX010350.MP4", "NUL", 3840, 2160, 30000, 1001)
        assert self.h, "Native D3D11 creation failed"
        assert self.set_hud_mode(self.h, 1)
        assert self.set_decode_mode(self.h, 1)
        assert self.set_hud_enabled(self.h, 1)
        assert self.set_amf_mode(self.h, 1)
        assert self.set_map_mode(self.h, 1)
        assert self.set_map_filter(self.h, 1)
        self.base = np.full((360 * 3 // 2, 640), 512 << 6, dtype=np.uint16)
        self.base[:360] = 64 << 6
        self.frame = 0

    def bind(self, name, args, result=c.c_int):
        fn = getattr(self.dll, "telem_amd_" + name)
        fn.argtypes, fn.restype = args, result
        setattr(self, name, fn)

    def configure(self, size, source_size, style, path, rotate):
        w, h = size
        self.size = size
        assert self.set_map_geometry(self.h, 40, 40, *source_size, w, h)
        assert self.set_map_gpu_path(self.h, path)
        assert self.set_map_rotate_mode(self.h, int(rotate))
        if style:
            _, _, payload, color = style
            assert self.update_map_style(self.h, payload, w, h, w * 4, *(v / 255 for v in color))

    def render(self, source, angle=0., marker=None):
        # Restore BELOW each frame, as in exporter's dirty-region lifecycle.
        below = Image.new("RGBA", (3840, 2160), (17, 29, 41, 255))
        assert self.read_video_sample(self.h, *([None] * 10)) == 1
        assert self.update_hud(self.h, below.tobytes(), 3840, 2160, 3840 * 4)
        assert self.update_map(self.h, source.tobytes(), *source.size, source.width * 4, None, None)
        assert self.set_map_heading(self.h, angle)
        if marker is not None:
            mx = (self.size[0] - marker.width) // 2
            my = (self.size[1] - marker.height) // 2
            assert self.update_map_marker(self.h, marker.tobytes(), *marker.size, marker.width * 4, mx, my)
        assert self.process_frame(self.h, self.frame, 1)
        self.frame += 1
        w, h = self.size
        output = (c.c_uint8 * (w * h * 4))()
        assert self.get_hud_region_readback(self.h, 40, 40, w, h, output, w * 4)
        return Image.frombytes("RGBA", (w, h), bytes(output))

    def finish(self):
        self.close(self.h)


def metrics(a, b):
    d = np.abs(np.array(a).astype(int) - np.array(b).astype(int))
    return dict(max_diff=int(d.max()), MAE=float(d.mean()), different_pixels=int(np.any(d, axis=2).sum()))


def main():
    out = ROOT / "Raporty/etap5w_map_artifacts"
    out.mkdir(exist_ok=True)
    dll = ROOT / "native/d3d11_amf_pipeline/bin/telem_amd_native.dll"
    cases = []
    # Each context retains a single viewport geometry, like a production job.
    for path_name, path, rotate in [("direct", 0, False), ("two_pass", 1, True), ("fused", 1, True)]:
        os.environ["AMD_MAP_FUSED"] = "1" if path_name == "fused" else "0"
        for shape, radius, width, color in [("rectangle", 0, 0, "#FFFFFF"),
                                            ("rounded", 0, 0, "#FFFFFF"),
                                            ("rounded", 18, 4, "#EF3010"),
                                            ("rounded", 1000, 4, "#20D0F0"),
                                            ("round", 16, 4, "#20D0F0")]:
            probe = Probe(dll)
            try:
                size = (128, 96)
                source_size = (192, 192) if rotate else size
                style = map_style_layers(size, shape, radius, width, color)
                probe.configure(size, source_size, style, path, rotate)
                # Solid content isolates coverage and blend from differences in
                # pre-existing Pillow vs Catmull-Rom map resampling kernels.
                source = Image.new("RGBA", source_size, (40, 90, 160, 255))
                for angle in [0., 35., 90., 180., 359.]:
                    gpu = probe.render(source, angle)
                    cpu = Image.new("RGBA", size, (17, 29, 41, 255))
                    cpu.alpha_composite(apply_map_shape(Image.new("RGBA", size, (40, 90, 160, 255)), shape, radius, width, color))
                    result = metrics(gpu, cpu)
                    cases.append(dict(path=path_name, shape=shape, radius=radius, angle=angle, **result))
                    assert result["max_diff"] <= 1, cases[-1]
                gpu.save(out / f"{path_name}_{shape}_{radius}.png")
                # Moving content A -> B -> A, static destination mask. An exact
                # return proves no stale pixels from the preceding map frame.
                a = source.copy()
                ImageDraw.Draw(a).line((0, source.height // 2, source.width, source.height // 2), fill="#FF0000", width=5)
                b = source.copy()
                ImageDraw.Draw(b).line((source.width // 2, 0, source.width // 2, source.height), fill="#00FF00", width=5)
                first = probe.render(a, 35.)
                middle = probe.render(b, 95.)
                last = probe.render(a, 35.)
                assert first.tobytes() == last.tobytes()
                assert first.tobytes() != middle.tobytes()
            finally:
                probe.finish()
    (out / "gpu_raster_cases.json").write_text(json.dumps(cases, indent=2), encoding="utf-8")
    print("MAP_GPU_CASES=" + str(len(cases)), flush=True)


if __name__ == "__main__":
    main()
