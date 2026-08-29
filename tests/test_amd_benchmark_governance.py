"""Pure tests for AMD production-default benchmark governance."""

from src.ffmpeg.amd_config import (
    clear_ambient_overrides,
    make_benchmark_fingerprint,
    resolve_amd_config,
)


def test_production_defaults_ignore_ambient_fast_path_values():
    env = {
        "AMD_CPU_GPU_PIPELINE": "ASYNC",
        "AMD_QUEUE_DEPTH": "2",
        "AMD_VP_STATE_MODE": "STATIC_CACHE",
        "AMD_AMF_QUERY_MODE": "DRAIN_READY",
        "AMD_MAP_PATH": "CPU_REFERENCE",
    }
    ignored = clear_ambient_overrides(env)
    config = resolve_amd_config(env)
    assert config["pipeline"] == "SYNC"
    assert config["queue_depth"] == 0
    assert config["vp_state"] == "REFERENCE"
    assert config["amf_query"] == "REFERENCE"
    assert config["map"] == "GPU"
    assert ignored["AMD_CPU_GPU_PIPELINE"] == "ASYNC"


def test_compute_base_conversion_is_governed_and_off_by_default():
    config = resolve_amd_config({"AMD_BASE_CONVERT_MODE": "COMPUTE_P010_NV12"})
    assert config["base_convert"] == "COMPUTE_P010_NV12"
    assert "AMD_BASE_CONVERT_MODE" in config["active_env_overrides"]
    assert resolve_amd_config({})["base_convert"] == "VP_REFERENCE"


def test_explicit_environment_is_visible_in_runtime_snapshot():
    config = resolve_amd_config({
        "AMD_CPU_GPU_PIPELINE": "ASYNC",
        "AMD_QUEUE_DEPTH": "2",
        "AMD_VP_STATE_MODE": "STATIC_CACHE",
        "AMD_AMF_QUERY_MODE": "DRAIN_READY",
    })
    assert config["pipeline"] == "ASYNC"
    assert config["queue_depth"] == 2
    assert config["vp_state"] == "STATIC_CACHE"
    assert config["amf_query"] == "DRAIN_READY"
    assert config["active_env_overrides"]["AMD_QUEUE_DEPTH"] == "2"


def test_benchmark_fingerprint_is_stable_and_workload_bound():
    config = resolve_amd_config({})
    first = make_benchmark_fingerprint(
        config, video="video", fit="fit", layout="layout",
        layout_sha256="abc", output=r"C:\out.mp4",
    )
    same = make_benchmark_fingerprint(
        config, video="video", fit="fit", layout="layout",
        layout_sha256="abc", output=r"C:\out.mp4",
    )
    changed = make_benchmark_fingerprint(
        config, video="other", fit="fit", layout="layout",
        layout_sha256="abc", output=r"C:\out.mp4",
    )
    assert first == same
    assert first == make_benchmark_fingerprint(
        config, video="video", fit="fit", layout="layout",
        layout_sha256="abc", output=r"C:\other-output.mp4",
    )
    assert first != changed
    assert len(first) == 64
