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


def _cmd_av1(pix_fmt: str = "p010le") -> list[str]:
    return ["ffmpeg", "-c:v", "av1_qsv", "-pix_fmt", pix_fmt, "out.mp4"]


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


def test_av1_qsv_graph_contract():
    graph = (
        "[0:v]format=p010le,scale=3840:2160[base];"
        "[1:v]format=rgba[ov];[base][ov]overlay=0:0[vtemp]"
    )
    result = validate_intel_graph_contract(
        _cmd_av1("p010le"), graph, gpu_resident=False, software_decode=True, expected_codec="av1",
    )
    assert result["actual_path"] == "CPU_REFERENCE"
    assert result["expected_decode_residency"] == "CPU"
    assert result["actual_graph"]["av1_qsv"] is True
    assert result["mismatch"] is False


def test_proof_json_schema_and_debug_only_write(tmp_path, monkeypatch):
    caps = IntelRenderCapabilities(
        adapter_name="Intel test adapter",
        adapter_device_id=0x1234,
        adapter_dxgi_index=1,
        qsv_available=True,
        qsv_hevc_encode=False,
        qsv_av1_encode=True,
        encode_codec="AV1",
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
        encode_path="QSV_AV1",
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
    assert snapshot["capabilities"]["qsv_av1_encode"] is True
    assert snapshot["capabilities"]["encode_codec"] == "AV1"

    output = tmp_path / "render.mp4"
    assert write_intel_proof_json(snapshot, str(output)) is None
    assert not (tmp_path / "render.mp4.intel_proof.json").exists()
    monkeypatch.setenv("TELEM_INTEL_PROOF", "1")
    proof_path = write_intel_proof_json(snapshot, str(output))
    assert proof_path is not None
    data = json.loads(proof_path.read_text(encoding="utf-8"))
    assert required <= data.keys()
    assert data["capabilities"]["qsv_av1_encode"] is True
    assert data["capabilities"]["encode_codec"] == "AV1"
    assert "_timeline_object" not in data


def test_bounded_hud_proof_snapshot_and_emission(capsys, monkeypatch):
    from src.ffmpeg.intel_backend import emit_intel_proof

    caps = IntelRenderCapabilities(
        adapter_name="Intel(R) Graphics",
        adapter_vendor_id=0x8086,
        adapter_device_id=32069,
        adapter_dxgi_index=0,
        driver_version="32.0.101.8993",
        qsv_available=True,
        qsv_av1_encode=True,
        encode_codec="AV1",
        d3d11_device_available=True,
        input_codec="hevc",
        input_width=3840,
        input_height=2160,
        input_bit_depth=10,
        input_pixel_format="yuv420p10le",
        input_hdr=True,
        decode_path="SOFTWARE",
        decode_residency="CPU",
        hud_transport="BOUNDED_REGION",
        hud_canvas_width=2560,
        hud_canvas_height=1440,
        hud_width=960,
        hud_height=480,
        hud_bytes_per_frame=960 * 480 * 4,
        hud_full_frame_bytes=2560 * 1440 * 4,
        hud_transfer_reduction_percent=87.5,
        hud_uploads_per_frame=1,
        hud_region_mode="SINGLE_BBOX",
        hud_region_bbox=(800, 960, 960, 480),
        hud_bbox_source=(800, 960, 960, 480),
        hud_bbox_output=(1200, 1440, 1440, 720),
        compositor_path="GPU_D3D11",
        gpu_texture_format="P010 / BGRA",
        compositor_output_format="QSV/P010",
        encode_path="QSV_AV1",
        encode_pixel_format="p010le",
        hwdownload_count_expected=0,
        hwupload_count_expected=2,
        capability_class=INTEL_CAPABILITY_CPU_REFERENCE,
    )
    snapshot = intel_proof_snapshot(
        caps,
        input_info={"path": "input.mp4", "codec": "hevc"},
        timeline=None,
        contract_validation={"mismatch": False},
        ffmpeg_exe="ffmpeg",
    )
    assert snapshot["hud"]["transport"] == "BOUNDED_REGION"
    assert snapshot["hud"]["region_mode"] == "SINGLE_BBOX"
    assert snapshot["hud"]["full_frame_bytes"] == 14_745_600
    assert snapshot["hud"]["bytes_per_frame"] == 1_843_200
    assert snapshot["hud"]["transfer_reduction_percent"] == 87.5
    assert snapshot["hud"]["bbox_source"] == (800, 960, 960, 480)
    assert snapshot["hud"]["bbox_output"] == (1200, 1440, 1440, 720)
    assert snapshot["transfers"]["hwupload_count_expected"] == 2
    assert snapshot["transfers"]["hwdownload_count_expected"] == 0

    monkeypatch.setenv("TELEM_INTEL_PROOF", "1")
    emit_intel_proof(snapshot)
    out = capsys.readouterr().out
    assert "[INTEL PROOF] HUD_TRANSPORT=BOUNDED_REGION" in out
    assert "[INTEL PROOF] HUD_REGION_MODE=SINGLE_BBOX" in out
    assert "[INTEL PROOF] HUD_BYTES_FRAME=1843200" in out
    assert "[INTEL PROOF] HUD_FULL_FRAME_BYTES=14745600" in out
    assert "[INTEL PROOF] HUD_TRANSFER_REDUCTION_PERCENT=87.5" in out
    assert "[INTEL PROOF] HUD_BBOX_SOURCE=(800, 960, 960, 480)" in out
    assert "[INTEL PROOF] HUD_BBOX_OUTPUT=(1200, 1440, 1440, 720)" in out
    assert "[INTEL PROOF] COMPOSITOR_PATH=GPU_D3D11" in out
    assert "[INTEL PROOF] HWDOWNLOAD_EXPECTED=0" in out
    assert "[INTEL PROOF] HWUPLOAD_EXPECTED=2" in out


def test_multi_region_proof_snapshot_and_emission(capsys, monkeypatch):
    from src.ffmpeg.intel_backend import emit_intel_proof

    regions = [
        (0, 0, 0, 0, 2560, 300),
        (0, 1000, 0, 300, 2560, 440),
        (0, 240, 0, 744, 240, 760),
        (2000, 240, 248, 744, 560, 760),
    ]
    active_region_bytes = sum(r[4] * r[5] * 4 for r in regions)
    assert active_region_bytes == 10_009_600

    caps = IntelRenderCapabilities(
        adapter_name="Intel(R) Graphics",
        adapter_vendor_id=0x8086,
        adapter_device_id=32069,
        adapter_dxgi_index=0,
        driver_version="32.0.101.8993",
        qsv_available=True,
        qsv_av1_encode=True,
        encode_codec="AV1",
        d3d11_device_available=True,
        input_codec="hevc",
        input_width=3840,
        input_height=2160,
        input_bit_depth=10,
        input_pixel_format="yuv420p10le",
        input_hdr=True,
        decode_path="SOFTWARE",
        decode_residency="CPU",
        hud_transport="BOUNDED_MULTI_REGION",
        hud_canvas_width=2560,
        hud_canvas_height=1440,
        hud_width=2560,
        hud_height=1504,
        hud_bytes_per_frame=2560 * 1504 * 4,
        hud_full_frame_bytes=2560 * 1440 * 4,
        hud_transfer_reduction_percent=32.1,
        hud_uploads_per_frame=4,
        hud_region_mode="MULTI_REGION",
        hud_region_count=4,
        hud_regions=regions,
        total_region_bytes_frame=active_region_bytes,
        compositor_path="GPU_D3D11",
        gpu_texture_format="P010 / BGRA",
        compositor_output_format="QSV/P010",
        encode_path="QSV_AV1",
        encode_pixel_format="p010le",
        hwdownload_count_expected=0,
        hwupload_count_expected=5,
        capability_class=INTEL_CAPABILITY_CPU_REFERENCE,
    )
    snapshot = intel_proof_snapshot(
        caps,
        input_info={"path": "input.mp4", "codec": "hevc"},
        timeline=None,
        contract_validation={"mismatch": False},
        ffmpeg_exe="ffmpeg",
    )
    assert snapshot["hud"]["transport"] == "BOUNDED_MULTI_REGION"
    assert snapshot["hud"]["region_mode"] == "MULTI_REGION"
    assert snapshot["hud"]["region_count"] == 4
    assert len(snapshot["hud"]["regions"]) == 4
    assert snapshot["hud"]["bytes_per_frame"] == 2560 * 1504 * 4
    assert snapshot["hud"]["total_region_bytes_frame"] == 10_009_600
    assert snapshot["hud"]["full_frame_bytes"] == 14_745_600
    assert snapshot["transfers"]["hwupload_count_expected"] == 5

    monkeypatch.setenv("TELEM_INTEL_PROOF", "1")
    emit_intel_proof(snapshot)
    out = capsys.readouterr().out
    assert "[INTEL PROOF] HUD_TRANSPORT=BOUNDED_MULTI_REGION" in out
    assert "[INTEL PROOF] HUD_REGION_MODE=MULTI_REGION" in out
    assert "[INTEL PROOF] HUD_REGION_COUNT=4" in out
    assert "[INTEL PROOF] HUD_REGION_0=(0, 0, 0, 0, 2560, 300)" in out
    assert "[INTEL PROOF] HUD_REGION_3=(2000, 240, 248, 744, 560, 760)" in out
    assert "[INTEL PROOF] HUD_BYTES_FRAME=15400960" in out
    assert "[INTEL PROOF] HUD_TOTAL_REGION_BYTES_FRAME=10009600" in out
    assert "[INTEL PROOF] TOTAL_REGION_BYTES_FRAME=10009600" in out
    assert "[INTEL PROOF] HUD_FULL_FRAME_BYTES=14745600" in out
    assert "[INTEL PROOF] COMPOSITOR_PATH=GPU_D3D11" in out
    assert "[INTEL PROOF] HWUPLOAD_EXPECTED=5" in out


def test_intel_proof_byte_consistency():
    """Verify that width * height * bytes_per_pixel matches reported bytes across all modes."""
    # 1. Full Frame
    caps_full = IntelRenderCapabilities(
        hud_canvas_width=2560,
        hud_canvas_height=1440,
        hud_width=2560,
        hud_height=1440,
        hud_bytes_per_frame=2560 * 1440 * 4,
        hud_full_frame_bytes=2560 * 1440 * 4,
        hud_region_mode="FULL_CANVAS",
        total_region_bytes_frame=2560 * 1440 * 4,
    )
    assert caps_full.hud_width * caps_full.hud_height * 4 == caps_full.hud_bytes_per_frame
    assert caps_full.hud_full_frame_bytes == 14_745_600
    assert caps_full.hud_bytes_per_frame == 14_745_600

    # 2. Single BBox
    bx, by, bw, bh = 800, 960, 960, 480
    caps_bbox = IntelRenderCapabilities(
        hud_canvas_width=2560,
        hud_canvas_height=1440,
        hud_width=bw,
        hud_height=bh,
        hud_bytes_per_frame=bw * bh * 4,
        hud_full_frame_bytes=2560 * 1440 * 4,
        hud_region_mode="SINGLE_BBOX",
        total_region_bytes_frame=bw * bh * 4,
    )
    assert caps_bbox.hud_width * caps_bbox.hud_height * 4 == caps_bbox.hud_bytes_per_frame
    assert caps_bbox.hud_bytes_per_frame == 1_843_200

    # 3. Multi-Region with Atlas
    regions = [
        (0, 0, 0, 0, 2560, 300),
        (0, 1000, 0, 300, 2560, 440),
        (0, 240, 0, 744, 240, 760),
        (2000, 240, 248, 744, 560, 760),
    ]
    atlas_w, atlas_h = 2560, 1504
    sum_active_bytes = sum(r[4] * r[5] * 4 for r in regions)
    caps_multi = IntelRenderCapabilities(
        hud_canvas_width=2560,
        hud_canvas_height=1440,
        hud_width=atlas_w,
        hud_height=atlas_h,
        hud_bytes_per_frame=atlas_w * atlas_h * 4,
        hud_full_frame_bytes=2560 * 1440 * 4,
        hud_region_mode="MULTI_REGION",
        hud_region_count=len(regions),
        hud_regions=regions,
        total_region_bytes_frame=sum_active_bytes,
    )
    # Transported atlas raster
    assert caps_multi.hud_width * caps_multi.hud_height * 4 == caps_multi.hud_bytes_per_frame
    assert caps_multi.hud_bytes_per_frame == 15_400_960
    # Active region bytes
    assert caps_multi.total_region_bytes_frame == sum_active_bytes
    assert caps_multi.total_region_bytes_frame == 10_009_600
    # Full canvas reference
    assert caps_multi.hud_full_frame_bytes == 14_745_600

    # 4. Multi-Region CPU (CPU ROI) Full Frame Transport
    sum_active_bytes = sum(r[4] * r[5] * 4 for r in regions)
    caps_cpu_roi = IntelRenderCapabilities(
        hud_canvas_width=2560,
        hud_canvas_height=1440,
        hud_width=2560,
        hud_height=1440,
        hud_bytes_per_frame=2560 * 1440 * 4,
        hud_full_frame_bytes=2560 * 1440 * 4,
        hud_region_mode="MULTI_REGION_CPU",
        hud_region_count=len(regions),
        hud_regions=regions,
        total_region_bytes_frame=sum_active_bytes,
        compositor_path="CPU_ROI",
    )
    assert caps_cpu_roi.hud_width * caps_cpu_roi.hud_height * 4 == caps_cpu_roi.hud_bytes_per_frame
    assert caps_cpu_roi.hud_bytes_per_frame == 14_745_600
    assert caps_cpu_roi.total_region_bytes_frame == 10_009_600
    assert caps_cpu_roi.hud_full_frame_bytes == 14_745_600
    assert caps_cpu_roi.compositor_path == "CPU_ROI"


def test_cpu_roi_graph_contract():
    graph = (
        "[0:v]format=p010le[base];"
        "[1:v]setpts=PTS-STARTPTS,split=4[ov_raw_0][ov_raw_1][ov_raw_2][ov_raw_3];"
        "[ov_raw_0]crop=2560:300:0:0,scale=3840:450:flags=bilinear[ov_0];"
        "[ov_raw_1]crop=2560:440:0:1000,scale=3840:660:flags=bilinear[ov_1];"
        "[ov_raw_2]crop=240:760:0:240,scale=360:1140:flags=bilinear[ov_2];"
        "[ov_raw_3]crop=560:760:2000:240,scale=840:1140:flags=bilinear[ov_3];"
        "[base][ov_0]overlay=0:0[v_step_0];"
        "[v_step_0][ov_1]overlay=0:1500[v_step_1];"
        "[v_step_1][ov_2]overlay=0:360[v_step_2];"
        "[v_step_2][ov_3]overlay=3000:360:shortest=1[vtemp]"
    )
    result = validate_intel_graph_contract(
        _cmd_av1("p010le"), graph, gpu_resident=False, gpu_compositor=False, software_decode=True, cpu_roi=True, expected_codec="av1",
    )
    assert result["actual_path"] == "CPU_ROI"
    assert result["expected_path"] == "CPU_ROI"
    assert result["expected_decode_residency"] == "CPU"
    assert result["actual_graph"]["hwdownload_count"] == 0
    assert result["actual_graph"]["hwupload_explicit_count"] == 0
    assert result["actual_graph"]["overlay_cpu"] is True
    assert result["actual_graph"]["overlay_qsv"] is False
    assert result["mismatch"] is False



