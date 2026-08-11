"""Tests for src/indicators/gpu_compositor.py (OpenCL GPU Compositor & CPU Fallback)."""

import pytest
import numpy as np
from PIL import Image
from src.indicators.gpu_compositor import GpuCompositor, _CL_AVAILABLE


def test_gpu_compositor_availability():
    """GpuCompositor.is_available() should return a boolean based on PyOpenCL environment."""
    is_avail = GpuCompositor.is_available()
    assert isinstance(is_avail, bool)
    if _CL_AVAILABLE:
        instance = GpuCompositor.get_instance()
        assert instance is not None
        assert instance.device_name != ""


def test_gpu_alpha_blend_pil():
    """alpha_blend_pil should correctly blend overlay onto base canvas."""
    gpu = GpuCompositor.get_instance()
    if not gpu:
        pytest.skip("OpenCL GPU not available")

    base = Image.new("RGBA", (200, 200), (0, 0, 0, 0))
    overlay = Image.new("RGBA", (50, 50), (255, 0, 0, 255))

    result = gpu.alpha_blend_pil(base, overlay, ox=20, oy=20)
    assert result.size == (200, 200)
    assert result.mode == "RGBA"

    arr = np.array(result)
    # Check pixel inside overlay region (25, 25)
    np.testing.assert_array_equal(arr[25, 25], [255, 0, 0, 255])
    # Check pixel outside overlay region (5, 5)
    np.testing.assert_array_equal(arr[5, 5], [0, 0, 0, 0])


def test_gpu_resize_pil():
    """resize_pil should scale image to target dimensions."""
    gpu = GpuCompositor.get_instance()
    if not gpu:
        pytest.skip("OpenCL GPU not available")

    src = Image.new("RGBA", (100, 100), (0, 255, 0, 255))
    resized = gpu.resize_pil(src, 50, 50)
    assert resized.size == (50, 50)
    assert resized.mode == "RGBA"


def test_gpu_rotate_pil():
    """rotate_pil should rotate image by specified degrees (90, 180, 270)."""
    gpu = GpuCompositor.get_instance()
    if not gpu:
        pytest.skip("OpenCL GPU not available")

    src = Image.new("RGBA", (100, 50), (100, 150, 200, 255))
    
    rot180 = gpu.rotate_pil(src, 180)
    assert rot180.size == (100, 50)

    rot90 = gpu.rotate_pil(src, 90)
    assert rot90.size == (50, 100)

    rot270 = gpu.rotate_pil(src, 270)
    assert rot270.size == (50, 100)


def test_gpu_composite_layers():
    """composite_layers should composite multiple layers sequentially onto canvas."""
    gpu = GpuCompositor.get_instance()
    if not gpu:
        pytest.skip("OpenCL GPU not available")

    layer1 = Image.new("RGBA", (80, 80), (255, 0, 0, 255))
    layer2 = Image.new("RGBA", (40, 40), (0, 255, 0, 255))

    layers = [(layer1, 10, 10), (layer2, 50, 50)]
    comp = gpu.composite_layers(200, 200, layers)

    assert comp.size == (200, 200)
    arr = np.array(comp)
    # Layer 1 region
    np.testing.assert_array_equal(arr[15, 15], [255, 0, 0, 255])
    # Layer 2 region (overwrites layer 1 overlap at 55, 55)
    np.testing.assert_array_equal(arr[55, 55], [0, 255, 0, 255])
