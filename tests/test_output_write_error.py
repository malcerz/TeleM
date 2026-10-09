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
    assert exc.legacy_output_category == ExportOutputCategory.PERMISSION_DENIED

def test_json_ipc_roundtrip():
    import json
    from src.ffmpeg.render_errors import RenderError
    exc = OutputWriteError(
        "Write failed no space",
        output_path="test.mp4",
        os_error="No space left on device",
        pause_queue=True
    )
    # Put enum into details so it can survive roundtrip if needed, or just test base framework
    exc.details["legacy_cat"] = exc.legacy_output_category.value
    
    d = exc.to_dict()
    s = json.dumps(d)
    d2 = json.loads(s)
    
    exc2 = RenderError.from_dict(d2)
    assert isinstance(exc2, RenderError)
    assert exc2.code == "ENOSPC"
    assert exc2.pause_queue is True
    assert exc2.code == ExportOutputCategory.DISK_FULL.value

def test_queue_blocker_and_partial():
    from src.ffmpeg.render_errors import ErrorScope
    exc = OutputWriteError(
        "Write failed no space",
        output_path="test.mp4",
        os_error="No space left on device"
    )
    assert exc.pause_queue is True
    assert exc.scope == ErrorScope.QUEUE_BLOCKER.value
    # By default storage errors don't guarantee valid partial output, but it's evaluated
    assert hasattr(exc, "partial_output_valid")

def test_classify_mux_failure():
    cat, reason = classify_output_error(
        output_path="test.mp4",
        ffmpeg_return_code=1,
        os_error="Some strange error"
    )
    assert cat == ExportOutputCategory.MUX_FAILURE
