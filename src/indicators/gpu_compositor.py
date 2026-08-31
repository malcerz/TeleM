"""GPU-accelerated compositor using PyOpenCL for AMD Radeon iGPU.

Provides alpha blending, bilinear resize, and rotation kernels that run
on the GPU.  Falls back gracefully to CPU/Pillow when OpenCL is not
available.

On AMD iGPU (unified memory) we use ``CL_MEM_USE_HOST_PTR`` so the GPU
operates directly on the CPU-side numpy buffer — zero-copy.
"""

from __future__ import annotations

import threading
from typing import Optional

import numpy as np
from src.render_logging import render_print

print = render_print

try:
    from PIL import Image
except ImportError:
    Image = None  # type: ignore

# ── Lazy OpenCL import ──────────────────────────────────────────────────────

_CL_AVAILABLE = False
try:
    import pyopencl as cl

    _CL_AVAILABLE = True
except ImportError:
    cl = None  # type: ignore


# ── OpenCL kernel source ───────────────────────────────────────────────────

_KERNEL_SRC = r"""
// Alpha-blend *overlay* onto *base* at offset (ox, oy).
// Both buffers are RGBA uint8, row-major, tightly packed.
__kernel void alpha_blend(
    __global uchar4 *base,
    __global const uchar4 *overlay,
    const int base_w,
    const int base_h,
    const int ov_w,
    const int ov_h,
    const int ox,
    const int oy)
{
    int gid = get_global_id(0);
    int ov_y = gid / ov_w;
    int ov_x = gid - ov_y * ov_w;
    if (ov_x >= ov_w || ov_y >= ov_h) return;

    int bx = ov_x + ox;
    int by = ov_y + oy;
    if (bx < 0 || bx >= base_w || by < 0 || by >= base_h) return;

    uchar4 fg = overlay[gid];
    float a = fg.w / 255.0f;
    if (a < 0.004f) return;          // fully transparent — skip

    int bi = by * base_w + bx;
    uchar4 bg = base[bi];

    float inv_a = 1.0f - a;
    uchar4 out;
    out.x = (uchar)(fg.x * a + bg.x * inv_a);
    out.y = (uchar)(fg.y * a + bg.y * inv_a);
    out.z = (uchar)(fg.z * a + bg.z * inv_a);
    out.w = (uchar)min(255.0f, fg.w + bg.w * inv_a);
    base[bi] = out;
}

// Bilinear resize from src (sw×sh) to dst (dw×dh).
__kernel void bilinear_resize(
    __global const uchar4 *src,
    __global uchar4 *dst,
    const int sw, const int sh,
    const int dw, const int dh)
{
    int gid = get_global_id(0);
    int dy = gid / dw;
    int dx = gid - dy * dw;
    if (dx >= dw || dy >= dh) return;

    float sx_f = ((float)dx + 0.5f) * sw / dw - 0.5f;
    float sy_f = ((float)dy + 0.5f) * sh / dh - 0.5f;

    int x0 = (int)floor(sx_f);
    int y0 = (int)floor(sy_f);
    int x1 = x0 + 1;
    int y1 = y0 + 1;
    float fx = sx_f - x0;
    float fy = sy_f - y0;

    x0 = clamp(x0, 0, sw - 1);
    x1 = clamp(x1, 0, sw - 1);
    y0 = clamp(y0, 0, sh - 1);
    y1 = clamp(y1, 0, sh - 1);

    uchar4 p00 = src[y0 * sw + x0];
    uchar4 p10 = src[y0 * sw + x1];
    uchar4 p01 = src[y1 * sw + x0];
    uchar4 p11 = src[y1 * sw + x1];

    float4 a = (float4)(p00.x, p00.y, p00.z, p00.w) * (1 - fx) + (float4)(p10.x, p10.y, p10.z, p10.w) * fx;
    float4 b = (float4)(p01.x, p01.y, p01.z, p01.w) * (1 - fx) + (float4)(p11.x, p11.y, p11.z, p11.w) * fx;
    float4 r = a * (1 - fy) + b * fy;

    uchar4 out;
    out.x = (uchar)clamp(r.x, 0.0f, 255.0f);
    out.y = (uchar)clamp(r.y, 0.0f, 255.0f);
    out.z = (uchar)clamp(r.z, 0.0f, 255.0f);
    out.w = (uchar)clamp(r.w, 0.0f, 255.0f);
    dst[gid] = out;
}

// Rotate 180°  (flip both axes).
__kernel void rotate_180(
    __global const uchar4 *src,
    __global uchar4 *dst,
    const int w, const int h)
{
    int gid = get_global_id(0);
    if (gid >= w * h) return;
    int y = gid / w;
    int x = gid - y * w;
    dst[(h - 1 - y) * w + (w - 1 - x)] = src[gid];
}

// Rotate 90° clockwise.
__kernel void rotate_90cw(
    __global const uchar4 *src,
    __global uchar4 *dst,
    const int sw, const int sh)
{
    int gid = get_global_id(0);
    if (gid >= sw * sh) return;
    int sy = gid / sw;
    int sx = gid - sy * sw;
    // dst is sh×sw  (rotated dimensions)
    int dx = sh - 1 - sy;
    int dy = sx;
    dst[dy * sh + dx] = src[gid];
}

// Rotate 90° counter-clockwise.
__kernel void rotate_90ccw(
    __global const uchar4 *src,
    __global uchar4 *dst,
    const int sw, const int sh)
{
    int gid = get_global_id(0);
    if (gid >= sw * sh) return;
    int sy = gid / sw;
    int sx = gid - sy * sw;
    int dx = sy;
    int dy = sw - 1 - sx;
    dst[dy * sh + dx] = src[gid];
}
"""


# ── Singleton GPU context ──────────────────────────────────────────────────

class GpuCompositor:
    """Thin wrapper around an OpenCL context + compiled kernels.

    Thread-safe lazy initialisation via ``get_instance()``.
    """

    _instance: Optional["GpuCompositor"] = None
    _lock = threading.Lock()

    def __init__(self) -> None:
        if not _CL_AVAILABLE:
            raise RuntimeError("PyOpenCL not available")

        platforms = cl.get_platforms()
        if not platforms:
            raise RuntimeError("No OpenCL platforms found")

        # Prefer AMD GPU device
        self.device = None
        for plat in platforms:
            for dev in plat.get_devices(cl.device_type.GPU):
                self.device = dev
                break
            if self.device:
                break

        if self.device is None:
            # Fall back to any device
            for plat in platforms:
                for dev in plat.get_devices():
                    self.device = dev
                    break
                if self.device:
                    break

        if self.device is None:
            raise RuntimeError("No OpenCL device found")

        self.ctx = cl.Context([self.device])
        self.queue = cl.CommandQueue(self.ctx)
        self.program = cl.Program(self.ctx, _KERNEL_SRC).build()
        self.device_name = self.device.name

        # Pre-extract kernel objects to avoid RepeatedKernelRetrieval overhead
        self._k_alpha_blend = cl.Kernel(self.program, "alpha_blend")
        self._k_bilinear_resize = cl.Kernel(self.program, "bilinear_resize")
        self._k_rotate_180 = cl.Kernel(self.program, "rotate_180")
        self._k_rotate_90cw = cl.Kernel(self.program, "rotate_90cw")
        self._k_rotate_90ccw = cl.Kernel(self.program, "rotate_90ccw")

        print(f"[GPU] OpenCL initialised: {self.device_name}", flush=True)

    # ── Public API ──────────────────────────────────────────────────────

    @classmethod
    def get_instance(cls) -> Optional["GpuCompositor"]:
        """Return singleton instance, or *None* if GPU is not available."""
        if cls._instance is not None:
            return cls._instance
        with cls._lock:
            if cls._instance is not None:
                return cls._instance
            try:
                cls._instance = GpuCompositor()
            except Exception as exc:
                print(f"[GPU] OpenCL not available: {exc}", flush=True)
                cls._instance = None  # type: ignore[assignment]
            return cls._instance

    @staticmethod
    def is_available() -> bool:
        """Return True if a usable OpenCL GPU compositor can be created."""
        return GpuCompositor.get_instance() is not None

    # ── Alpha-blend overlay onto base at (ox, oy) ───────────────────────

    def alpha_blend_pil(
        self,
        base: Image.Image,
        overlay: Image.Image,
        ox: int = 0,
        oy: int = 0,
    ) -> Image.Image:
        """Alpha-blend *overlay* onto *base* (in-place) using GPU.

        Both images must be RGBA.  Returns the modified *base*.
        """
        base_arr = np.array(base, dtype=np.uint8)
        ov_arr = np.array(overlay, dtype=np.uint8)

        bh, bw = base_arr.shape[:2]
        oh, ow = ov_arr.shape[:2]

        mf = cl.mem_flags
        base_buf = cl.Buffer(
            self.ctx, mf.READ_WRITE | mf.USE_HOST_PTR, hostbuf=base_arr
        )
        ov_buf = cl.Buffer(
            self.ctx, mf.READ_ONLY | mf.USE_HOST_PTR, hostbuf=ov_arr
        )

        self._k_alpha_blend(
            self.queue,
            (ow * oh,),
            None,
            base_buf,
            ov_buf,
            np.int32(bw),
            np.int32(bh),
            np.int32(ow),
            np.int32(oh),
            np.int32(ox),
            np.int32(oy),
        )
        cl.enqueue_copy(self.queue, base_arr, base_buf).wait()
        return Image.fromarray(base_arr, "RGBA")

    # ── Bilinear resize ─────────────────────────────────────────────────

    def resize_pil(
        self, src: Image.Image, dst_w: int, dst_h: int
    ) -> Image.Image:
        """Resize *src* to (dst_w, dst_h) using bilinear interpolation on GPU."""
        src_arr = np.array(src.convert("RGBA"), dtype=np.uint8)
        sh, sw = src_arr.shape[:2]
        dst_arr = np.empty((dst_h, dst_w, 4), dtype=np.uint8)

        mf = cl.mem_flags
        src_buf = cl.Buffer(
            self.ctx, mf.READ_ONLY | mf.USE_HOST_PTR, hostbuf=src_arr
        )
        dst_buf = cl.Buffer(
            self.ctx, mf.WRITE_ONLY, size=dst_arr.nbytes
        )

        self._k_bilinear_resize(
            self.queue,
            (dst_w * dst_h,),
            None,
            src_buf,
            dst_buf,
            np.int32(sw),
            np.int32(sh),
            np.int32(dst_w),
            np.int32(dst_h),
        )
        cl.enqueue_copy(self.queue, dst_arr, dst_buf).wait()
        return Image.fromarray(dst_arr, "RGBA")

    # ── Rotation ────────────────────────────────────────────────────────

    def rotate_pil(self, src: Image.Image, degrees: int) -> Image.Image:
        """Rotate *src* by 90, 180, or 270 degrees on GPU.

        Returns a new PIL Image.
        """
        degrees = degrees % 360
        if degrees == 0:
            return src

        src_arr = np.array(src.convert("RGBA"), dtype=np.uint8)
        sh, sw = src_arr.shape[:2]

        mf = cl.mem_flags
        src_buf = cl.Buffer(
            self.ctx, mf.READ_ONLY | mf.USE_HOST_PTR, hostbuf=src_arr
        )

        if degrees == 180:
            dst_arr = np.empty_like(src_arr)
            dst_buf = cl.Buffer(self.ctx, mf.WRITE_ONLY, size=dst_arr.nbytes)
            self._k_rotate_180(
                self.queue, (sw * sh,), None,
                src_buf, dst_buf, np.int32(sw), np.int32(sh),
            )
        elif degrees == 90:
            dst_arr = np.empty((sw, sh, 4), dtype=np.uint8)
            dst_buf = cl.Buffer(self.ctx, mf.WRITE_ONLY, size=dst_arr.nbytes)
            self._k_rotate_90cw(
                self.queue, (sw * sh,), None,
                src_buf, dst_buf, np.int32(sw), np.int32(sh),
            )
        elif degrees == 270:
            dst_arr = np.empty((sw, sh, 4), dtype=np.uint8)
            dst_buf = cl.Buffer(self.ctx, mf.WRITE_ONLY, size=dst_arr.nbytes)
            self._k_rotate_90ccw(
                self.queue, (sw * sh,), None,
                src_buf, dst_buf, np.int32(sw), np.int32(sh),
            )
        else:
            return src

        cl.enqueue_copy(self.queue, dst_arr, dst_buf).wait()
        return Image.fromarray(dst_arr, "RGBA")

    # ── Bulk alpha_composite (replace Pillow's img.alpha_composite) ────

    def composite_layers(
        self,
        canvas_w: int,
        canvas_h: int,
        layers: list[tuple[Image.Image, int, int]],
    ) -> Image.Image:
        """Composite multiple RGBA layers onto a transparent canvas using GPU.

        Args:
            canvas_w, canvas_h: output canvas size.
            layers: list of (pil_image, x, y) tuples.

        Returns:
            Final composited RGBA PIL Image.
        """
        canvas_arr = np.zeros((canvas_h, canvas_w, 4), dtype=np.uint8)
        mf = cl.mem_flags
        canvas_buf = cl.Buffer(
            self.ctx, mf.READ_WRITE | mf.USE_HOST_PTR, hostbuf=canvas_arr
        )

        for img, ox, oy in layers:
            ov_arr = np.ascontiguousarray(np.array(img, dtype=np.uint8))
            oh, ow = ov_arr.shape[:2]
            ov_buf = cl.Buffer(
                self.ctx, mf.READ_ONLY | mf.USE_HOST_PTR, hostbuf=ov_arr
            )
            self._k_alpha_blend(
                self.queue,
                (ow * oh,),
                None,
                canvas_buf,
                ov_buf,
                np.int32(canvas_w),
                np.int32(canvas_h),
                np.int32(ow),
                np.int32(oh),
                np.int32(ox),
                np.int32(oy),
            )

        cl.enqueue_copy(self.queue, canvas_arr, canvas_buf).wait()
        return Image.fromarray(canvas_arr, "RGBA")
