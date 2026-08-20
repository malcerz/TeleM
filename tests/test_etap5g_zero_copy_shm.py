from __future__ import annotations

from multiprocessing import shared_memory

import numpy as np
from PIL import Image, ImageDraw

from src.ffmpeg.shm_image import close_writable_image, writable_rgba_image


def _shm_array(shm: shared_memory.SharedMemory, width: int, height: int) -> np.ndarray:
    return np.frombuffer(shm.buf, dtype=np.uint8, count=width * height * 4).reshape(
        (height, width, 4)
    )


def test_pillow_target_writes_directly_into_shm_and_supports_compositing():
    width, height = 16, 12
    shm = shared_memory.SharedMemory(create=True, size=width * height * 4)
    view = None
    image = None
    try:
        view = _shm_array(shm, width, height)
        view.fill(0)
        image = writable_rgba_image(shm.buf, (width, height))
        assert image.mode == "RGBA"
        assert getattr(image, "_readonly", 1) == 0

        ImageDraw.Draw(image).rectangle((2, 2, 6, 5), fill=(255, 10, 20, 255))
        source = Image.new("RGBA", (4, 4), (10, 200, 30, 128))
        image.alpha_composite(source, (5, 4))
        image.paste((50, 60, 70, 255), (10, 8, 12, 11))

        assert tuple(view[2, 2]) == (255, 10, 20, 255)
        assert tuple(view[4, 5]) != (0, 0, 0, 0)
        assert tuple(view[8, 10]) == (50, 60, 70, 255)
    finally:
        close_writable_image(image)
        view = None
        shm.close()
        shm.unlink()


def test_two_numpy_views_share_shm_backing_and_clear_removes_dirty_pixels():
    width, height = 8, 8
    shm = shared_memory.SharedMemory(create=True, size=width * height * 4)
    first = second = None
    try:
        first = _shm_array(shm, width, height)
        second = _shm_array(shm, width, height)
        assert np.shares_memory(first, second)
        first[:] = (1, 2, 3, 255)
        assert tuple(second[0, 0]) == (1, 2, 3, 255)
        second.fill(0)
        assert not np.any(first)
    finally:
        first = None
        second = None
        shm.close()
        shm.unlink()


def test_mapped_image_can_be_reused_after_close_without_dangling_view():
    width, height = 8, 8
    shm = shared_memory.SharedMemory(create=True, size=width * height * 4)
    try:
        for color in ((20, 30, 40, 255), (90, 80, 70, 255)):
            backing = _shm_array(shm, width, height)
            backing.fill(0)
            image = writable_rgba_image(shm.buf, (width, height))
            image.paste(color, (0, 0, width, height))
            assert tuple(backing[0, 0]) == color
            close_writable_image(image)
            backing = None
    finally:
        shm.close()
        shm.unlink()
