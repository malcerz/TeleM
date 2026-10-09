import pytest
from src.ffmpeg.output_error import (
    ExportOutputError,
    OutputWriteError,
    ExportOutputCategory,
    classify_output_error,
)

def test_classify_disk_full():
    cat, reason = classify_output_error(
        output_path="test.mp4",
        os_error="No space left on device"
    )
    assert cat == ExportOutputCategory.DISK_FULL

def test_classify_permission_denied():
    cat, reason = classify_output_error(
        output_path="test.mp4",
        os_error="Permission denied"
    )
    assert cat == ExportOutputCategory.PERMISSION_DENIED

def test_classify_broken_pipe():
    cat, reason = classify_output_error(
        output_path="test.mp4",
        ffmpeg_return_code=1,
        os_error="Broken pipe"
    )
    assert cat == ExportOutputCategory.BROKEN_PIPE

def test_classify_device_unavailable():
    cat, reason = classify_output_error(
        output_path="test.mp4",
        os_error="The device is not ready"
    )
    assert cat == ExportOutputCategory.DEVICE_UNAVAILABLE

def test_typed_exception():
    exc = ExportOutputError(
        "Write failed",
        output_path="test.mp4",
        os_error="Permission denied",
    )
    assert exc.category == ExportOutputCategory.PERMISSION_DENIED
