from src.ffmpeg.hybrid_render import (
    GpuTopology,
    HybridAdaptiveController,
    HybridFrameState,
    HybridReorderBuffer,
    HybridWorkScheduler,
    NvidiaPreparedFrameAdapter,
    PreparedVideoFrame,
    SingleEncoderHandoff,
    RenderMode,
    choose_hybrid_mode,
    normalize_render_mode,
)
from src.ffmpeg.streaming import _report_stream_progress


def test_cpu_stream_progress_is_a_real_render_contract():
    received = []
    _report_stream_progress(
        7, 100, 1.0, None,
        lambda done, total, elapsed, fps, state: received.append((done, total, state)),
        30.0,
    )
    done, total, state = received[-1]
    assert (done, total) == (7, 100)
    assert state["phase"] == "render"
    assert state["role"] == "cpu"
    assert state["frame_done"] == 7
    assert state["frame_total"] == 100
    assert state["ts"] == 6 / 30.0


def test_hybrid_apu_is_safe_gpu_only_until_handoff_exists():
    decision = choose_hybrid_mode(
        requested=RenderMode.HYBRID,
        backend="amd",
        topology=GpuTopology.APU,
    )
    assert decision.effective is RenderMode.GPU
    assert decision.cpu_workers == 0


def test_hybrid_dgpu_is_not_mixed_encoder_fallback():
    decision = choose_hybrid_mode(
        requested="hybrid", backend="nv", topology=GpuTopology.DISCRETE,
    )
    assert decision.effective is RenderMode.GPU
    assert "handoff" in decision.reason


def test_normalize_existing_enum():
    assert normalize_render_mode(RenderMode.HYBRID) is RenderMode.HYBRID


def _frame(index: int, payload: bytes = b"x") -> PreparedVideoFrame:
    return PreparedVideoFrame(
        frame_index=index, pts=index, duration=1,
        effective_timeline_timestamp=index / 30.0,
        pixel_format="rgba", width=1, height=1,
        color_primaries="bt2020", transfer="arib-std-b67",
        matrix="bt2020nc", range="tv", orientation=0, payload=payload,
    )


def test_hybrid_scheduler_rejects_duplicate_and_cpu_overlap():
    scheduler = HybridWorkScheduler(3)
    assert scheduler.claim_gpu(0)
    assert not scheduler.claim_cpu(0)
    assert scheduler.claim_cpu(1)
    assert scheduler.mark_ready(_frame(1))
    assert scheduler.mark_encoded(1)
    assert scheduler.ticket(1).state is HybridFrameState.ENCODED


def test_hybrid_reorder_buffer_is_bounded_and_ordered():
    buf = HybridReorderBuffer(capacity=2)
    buf.put(_frame(1, b"12"))
    buf.put(_frame(0, b"0"))
    assert buf.peak_frames == 2
    assert buf.peak_payload_bytes == 3
    assert buf.pop_next().frame_index == 0
    assert buf.pop_next().frame_index == 1
    assert buf.pop_next() is None


def test_nvidia_adapter_preserves_canonical_payload_and_timing():
    frame = NvidiaPreparedFrameAdapter.from_rgba(
        4, b"abcd", width=1, height=1, fps=30.0,
        effective_timeline_timestamp=12.5,
    )
    assert frame.pts == 4 and frame.duration == 1
    assert frame.effective_timeline_timestamp == 12.5
    assert frame.pixel_format == "rgba"
    seen = []
    assert NvidiaPreparedFrameAdapter.handoff(frame, lambda f: seen.append(f) or "surface") == "surface"
    assert seen[0].payload == b"abcd"


def test_nvidia_adapter_accepts_native_p010_without_8bit_conversion():
    frame = NvidiaPreparedFrameAdapter.from_payload(
        0, bytes(1 * 2 * 3), width=1, height=2, fps=30.0,
        pixel_format="p010le",
    )
    assert frame.pixel_format == "p010le"
    assert len(frame.payload) == 6


def test_hybrid_controller_disables_on_gpu_regression():
    controller = HybridAdaptiveController(workers=1, max_workers=4)
    assert controller.observe(combined_gain_pct=8.0, gpu_regression_pct=0.5) == 2
    assert controller.observe(combined_gain_pct=0.2, gpu_regression_pct=4.0) == 1
    assert controller.observe(combined_gain_pct=0.0, gpu_regression_pct=0.0, memory_safe=False) == 0


def test_single_encoder_handoff_orders_transitions_without_second_codec():
    encoded = []
    handoff = SingleEncoderHandoff(lambda frame: encoded.append(frame.frame_index) or frame.frame_index, capacity=2)
    # Completion order is intentionally out of order; encoder order remains 0,1.
    assert handoff.submit(_frame(1), "cpu") == []
    assert handoff.submit(_frame(0), "gpu") == [0, 1]
    handoff.finish()
    assert encoded == [0, 1]
    assert handoff.producer_counts == {"gpu": 1, "cpu": 1}
    assert handoff.transitions == [("gpu", "cpu")]
