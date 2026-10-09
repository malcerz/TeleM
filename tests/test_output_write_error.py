import pytest
from src.ffmpeg.output_error import (
    ExportOutputError,
    OutputWriteError,
    classify_output_error,
)

def test_classify_disk_full():
    cat, reason = classify_output_error(
        output_path="test.mp4",
        os_error="No space left on device"
    )
    assert cat == "ENOSPC"

def test_classify_permission_denied():
    cat, reason = classify_output_error(
        output_path="test.mp4",
        os_error="Permission denied"
    )
    assert cat == "EACCES"

def test_classify_broken_pipe():
    cat, reason = classify_output_error(
        output_path="test.mp4",
        ffmpeg_return_code=1,
        os_error="Broken pipe"
    )
    assert cat == "EPIPE"

def test_classify_device_unavailable():
    cat, reason = classify_output_error(
        output_path="test.mp4",
        os_error="The device is not ready"
    )
    assert cat == "ENOENT"

def test_typed_exception():
    exc = ExportOutputError(
        "Write failed",
        output_path="test.mp4",
        os_error="Permission denied",
    )
    assert exc.code == "EACCES"

def test_json_ipc_roundtrip():
    import json
    from src.ffmpeg.render_errors import RenderError
    exc = OutputWriteError(
        "Write failed no space",
        output_path="test.mp4",
        os_error="No space left on device",
        pause_queue=True
    )
    
    d = exc.to_dict()
    s = json.dumps(d)
    d2 = json.loads(s)
    
    exc2 = RenderError.from_dict(d2)
    assert isinstance(exc2, RenderError)
    assert exc2.code == "ENOSPC"
    assert exc2.pause_queue is True

def test_queue_blocker_and_partial():
    from src.ffmpeg.render_errors import ErrorScope
    exc = OutputWriteError(
        "Write failed no space",
        output_path="test.mp4",
        os_error="No space left on device"
    )
    assert exc.pause_queue is True
    # By default storage errors don't guarantee valid partial output, but it's evaluated
    assert hasattr(exc, "partial_output_valid")

def test_classify_mux_failure():
    cat, reason = classify_output_error(
        output_path="test.mp4",
        ffmpeg_return_code=1,
        os_error="Some strange error"
    )
    assert cat == "MUX_ERROR"
