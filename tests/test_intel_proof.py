"""ETAP 1B: Intel proof/capability contracts (synthetic, no hardware)."""

from __future__ import annotations

import json

import pytest

from src.ffmpeg.intel_backend import (
    INTEL_CAPABILITY_CPU_REFERENCE,
    INTEL_CAPABILITY_GPU_RESIDENT_SDR,
    INTEL_CAPABILITY_UNAVAILABLE,
    IntelRenderCapabilities,
    classify_intel_capability,
    intel_proof_snapshot,
    validate_intel_graph_contract,
    write_intel_proof_json,
)


def _cmd(pix_fmt: str = "nv12") -> list[str]:
    return ["ffmpeg", "-c:v", "hevc_qsv", "-pix_fmt", pix_fmt, "out.mp4"]


@pytest.mark.parametrize(
    ("qsv", "resident", "hdr", "expected"),
    [
        (True, True, False, INTEL_CAPABILITY_GPU_RESIDENT_SDR),
        (True, False, True, INTEL_CAPABILITY_CPU_REFERENCE),
        (True, False, False, INTEL_CAPABILITY_CPU_REFERENCE),
        (False, False, None, INTEL_CAPABILITY_UNAVAILABLE),
    ],
)
def test_capability_class_is_capability_based(qsv, resident, hdr, expected):
    assert classify_intel_capability(
        qsv_available=qsv, gpu_resident=resident, input_hdr=hdr,
    ) == expected


def test_native_graph_contract_and_hud_accounting():
    graph = (
        "[0:v]scale_qsv=3840:2160[base];"
        "[1:v]format=bgra,hwupload=derive_device=qsv[ov];"
        "[base][ov]overlay_qsv=0:0[vtemp]"
    )
    result = validate_intel_graph_contract(
        _cmd(), graph, gpu_resident=True, software_decode=False,
    )
    assert result["actual_path"] == "QSV_GPU"
    assert result["actual_graph"]["hwdownload_count"] == 0
    assert result["mismatch"] is False

    caps = IntelRenderCapabilities(
        hud_canvas_width=2560,
        hud_canvas_height=1440,
        hud_width=2560,
        hud_height=1440,
        hud_bytes_per_frame=2560 * 1440 * 4,
        hud_region_mode="FULL_CANVAS",
        capability_class=INTEL_CAPABILITY_GPU_RESIDENT_SDR,
    )
    assert caps.hud_bytes_per_frame == 14_745_600


def test_cpu_reference_qsv_graph_contract():
    graph = (
        "[0:v]hwdownload,format=nv12,scale=1920:1080[base];"
        "[1:v]format=rgba[ov];[base][ov]overlay=0:0:shortest=1[vtemp]"
    )
    result = validate_intel_graph_contract(
        _cmd(), graph, gpu_resident=False, software_decode=False,
    )
    assert result["actual_path"] == "CPU_REFERENCE"
    assert result["expected_decode_residency"] == "GPU_TO_CPU"
    assert result["actual_graph"]["hwdownload_count"] == 1
    assert result["mismatch"] is False


def test_p010_software_decode_does_not_claim_hwdownload():
    graph = (
        "[0:v]format=p010le,scale=3840:2160[base];"
        "[1:v]format=rgba[ov];[base][ov]overlay=0:0[vtemp]"
    )
    result = validate_intel_graph_contract(
        _cmd("p010le"), graph, gpu_resident=False, software_decode=True,
    )
    assert result["actual_path"] == "CPU_REFERENCE"
    assert result["expected_decode_residency"] == "CPU"
    assert result["actual_graph"]["hwdownload_count"] == 0
    assert result["mismatch"] is False


def test_rotation_or_cut_unsafe_case_stays_cpu_reference():
    """The existing routing gate, represented here by resident=False, wins."""
    graph = "[0:v]hwdownload,format=nv12[base];[base][ov]overlay=0:0[v]"
    result = validate_intel_graph_contract(
        _cmd(), graph, gpu_resident=False, software_decode=False,
    )
    assert result["expected_path"] == "CPU_REFERENCE"
    assert result["actual_path"] == "CPU_REFERENCE"


def test_graph_mismatch_is_reported_without_repair():
    result = validate_intel_graph_contract(
        _cmd(), "[0:v]hwdownload,format=nv12[base];[base]overlay=0:0[v]",
        gpu_resident=True, software_decode=False,
    )
    assert result["mismatch"] is True
    assert result["mismatch_reasons"]


def test_proof_json_schema_and_debug_only_write(tmp_path, monkeypatch):
    caps = IntelRenderCapabilities(
        adapter_name="Intel test adapter",
        adapter_device_id=0x1234,
        adapter_dxgi_index=1,
        qsv_available=True,
        qsv_hevc_encode=True,
        d3d11_device_available=True,
        input_codec="hevc",
        input_width=3840,
        input_height=2160,
        input_bit_depth=10,
        input_pixel_format="p010le",
        input_hdr=True,
        decode_path="SOFTWARE",
        decode_residency="CPU",
        hud_transport="CPU_RGBA_PIPE",
        hud_canvas_width=2560,
        hud_canvas_height=1440,
        hud_width=1000,
        hud_height=500,
        hud_bytes_per_frame=2_000_000,
        hud_region_mode="REGION",
        hud_region_bbox=[20, 30, 1000, 500],
        compositor_path="CPU_REFERENCE",
        encode_path="QSV_HEVC",
        encode_pixel_format="p010le",
        hwdownload_count_expected=0,
        hwupload_count_expected=1,
        capability_class=INTEL_CAPABILITY_CPU_REFERENCE,
    )
    snapshot = intel_proof_snapshot(
        caps,
        input_info={"path": "input.mp4", "codec": "hevc"},
        timeline=None,
        contract_validation={"mismatch": False},
        ffmpeg_exe="ffmpeg",
    )
    required = {
        "system", "adapter", "capabilities", "input", "timeline", "decode",
        "hud", "compositor", "encode", "transfers", "timings",
        "contract_validation",
    }
    assert required <= snapshot.keys()

    output = tmp_path / "render.mp4"
    assert write_intel_proof_json(snapshot, str(output)) is None
    assert not (tmp_path / "render.mp4.intel_proof.json").exists()
    monkeypatch.setenv("TELEM_INTEL_PROOF", "1")
    proof_path = write_intel_proof_json(snapshot, str(output))
    assert proof_path is not None
    data = json.loads(proof_path.read_text(encoding="utf-8"))
    assert required <= data.keys()
    assert "_timeline_object" not in data
