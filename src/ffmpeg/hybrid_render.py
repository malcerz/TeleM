"""Safe policy primitives for the experimental GPU+CPU render mode.

This module deliberately does not split a movie into independently encoded
chunks.  A hybrid contributor may be enabled only after a backend exposes a
canonical CPU-frame handoff to its *one* native final encoder.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import threading
from typing import Callable, Iterable


class RenderMode(str, Enum):
    GPU = "gpu"
    HYBRID = "hybrid"
    CPU = "cpu"


class GpuTopology(str, Enum):
    APU = "apu"
    DISCRETE = "discrete"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class PreparedVideoFrame:
    """Backend-neutral semantic frame contract for a future hybrid producer."""

    frame_index: int
    pts: int
    duration: int
    effective_timeline_timestamp: float
    pixel_format: str
    width: int
    height: int
    color_primaries: str
    transfer: str
    matrix: str
    range: str
    orientation: int
    payload: object | None = None
    surface: object | None = None


class HybridFrameState(str, Enum):
    """Ownership state for one frame in the bounded hybrid scheduler."""

    FREE = "free"
    CLAIMED_GPU = "claimed_gpu"
    CLAIMED_CPU = "claimed_cpu"
    READY = "ready"
    ENCODED = "encoded"


@dataclass
class HybridFrameTicket:
    """Mutable scheduler bookkeeping; payload ownership stays explicit."""

    frame_index: int
    state: HybridFrameState = HybridFrameState.FREE
    producer: str | None = None
    frame: PreparedVideoFrame | None = None


class HybridWorkScheduler:
    """Thread-safe, duplicate-free producer claim table.

    A CPU producer may claim only a frame still in ``FREE`` state.  The GPU
    producer claims first, so CPU work can never duplicate or overlap a GPU
    frame.  This class contains no encoder or codec logic and is therefore
    backend-neutral.
    """

    def __init__(self, total_frames: int) -> None:
        if int(total_frames) < 0:
            raise ValueError("total_frames must be non-negative")
        self._lock = threading.Lock()
        self._tickets = {i: HybridFrameTicket(i) for i in range(int(total_frames))}

    def claim(self, frame_index: int, producer: str) -> bool:
        producer = str(producer).strip().lower()
        if producer not in ("gpu", "cpu"):
            raise ValueError("producer must be gpu or cpu")
        with self._lock:
            ticket = self._tickets.get(int(frame_index))
            if ticket is None or ticket.state is not HybridFrameState.FREE:
                return False
            ticket.producer = producer
            ticket.state = (
                HybridFrameState.CLAIMED_GPU
                if producer == "gpu" else HybridFrameState.CLAIMED_CPU
            )
            return True

    def claim_gpu(self, frame_index: int) -> bool:
        return self.claim(frame_index, "gpu")

    def claim_cpu(self, frame_index: int) -> bool:
        return self.claim(frame_index, "cpu")

    def mark_ready(self, frame: PreparedVideoFrame) -> bool:
        with self._lock:
            ticket = self._tickets.get(int(frame.frame_index))
            if ticket is None or ticket.state not in (
                HybridFrameState.CLAIMED_GPU, HybridFrameState.CLAIMED_CPU,
            ):
                return False
            ticket.frame = frame
            ticket.state = HybridFrameState.READY
            return True

    def mark_encoded(self, frame_index: int) -> bool:
        with self._lock:
            ticket = self._tickets.get(int(frame_index))
            if ticket is None or ticket.state is not HybridFrameState.READY:
                return False
            ticket.state = HybridFrameState.ENCODED
            ticket.frame = None
            return True

    def ticket(self, frame_index: int) -> HybridFrameTicket | None:
        with self._lock:
            ticket = self._tickets.get(int(frame_index))
            if ticket is None:
                return None
            return HybridFrameTicket(ticket.frame_index, ticket.state, ticket.producer, ticket.frame)

    def counts(self) -> dict[str, int]:
        with self._lock:
            return {
                state.value: sum(1 for t in self._tickets.values() if t.state is state)
                for state in HybridFrameState
            }


class HybridReorderBuffer:
    """Bounded ordered buffer for CPU/GPU completion races.

    ``pop_next`` is the only operation that advances the encoder-facing
    sequence.  Payload byte accounting is intentionally exposed so production
    proofs can report the actual peak rather than an estimate.
    """

    def __init__(self, capacity: int = 8) -> None:
        if int(capacity) < 1:
            raise ValueError("capacity must be >= 1")
        self.capacity = int(capacity)
        self._lock = threading.Lock()
        self.next_frame_index = 0
        self._frames: dict[int, PreparedVideoFrame] = {}
        self._payload_bytes = 0
        self.peak_payload_bytes = 0
        self.peak_frames = 0

    @staticmethod
    def _payload_size(frame: PreparedVideoFrame) -> int:
        payload = frame.payload
        try:
            return max(0, int(len(payload))) if payload is not None else 0
        except Exception:
            return 0

    def put(self, frame: PreparedVideoFrame) -> None:
        index = int(frame.frame_index)
        with self._lock:
            if index < self.next_frame_index:
                raise ValueError(f"frame {index} is older than next {self.next_frame_index}")
            if index in self._frames:
                raise ValueError(f"duplicate frame {index}")
            if len(self._frames) >= self.capacity:
                raise BufferError("hybrid reorder buffer capacity exceeded")
            self._frames[index] = frame
            self._payload_bytes += self._payload_size(frame)
            self.peak_payload_bytes = max(self.peak_payload_bytes, self._payload_bytes)
            self.peak_frames = max(self.peak_frames, len(self._frames))

    def pop_next(self) -> PreparedVideoFrame | None:
        with self._lock:
            frame = self._frames.pop(self.next_frame_index, None)
            if frame is None:
                return None
            self._payload_bytes -= self._payload_size(frame)
            self.next_frame_index += 1
            return frame

    def __len__(self) -> int:
        with self._lock:
            return len(self._frames)

    def clear(self) -> None:
        with self._lock:
            self._frames.clear()
            self._payload_bytes = 0


class SingleEncoderHandoff:
    """Ordered CPU/GPU frame handoff to one encoder callback.

    The callback represents the already-open native encoder session (NVENC for
    the NVIDIA adapter).  There is deliberately no codec creation or muxing in
    this helper, making a second encoder impossible by construction.
    """

    def __init__(self, encode: Callable[[PreparedVideoFrame], object], capacity: int = 8) -> None:
        self._encode = encode
        self.reorder = HybridReorderBuffer(capacity)
        self.encoded_frames = 0
        self.producer_counts = {"gpu": 0, "cpu": 0}
        self.transitions: list[tuple[str, str]] = []
        self._last_producer: str | None = None
        self._producer_by_index: dict[int, str] = {}

    def submit(self, frame: PreparedVideoFrame, producer: str) -> list[object]:
        producer = str(producer).strip().lower()
        if producer not in self.producer_counts:
            raise ValueError("producer must be gpu or cpu")
        self.reorder.put(frame)
        self._producer_by_index[int(frame.frame_index)] = producer
        self.producer_counts[producer] += 1
        return self.drain()

    def drain(self) -> list[object]:
        results: list[object] = []
        while True:
            frame = self.reorder.pop_next()
            if frame is None:
                break
            producer = self._producer_by_index.pop(int(frame.frame_index), "gpu")
            if self._last_producer is not None and producer != self._last_producer:
                self.transitions.append((self._last_producer, producer))
            self._last_producer = producer
            results.append(self._encode(frame))
            self.encoded_frames += 1
        return results

    def finish(self) -> None:
        if len(self.reorder):
            raise RuntimeError("encoder handoff closed with a gap in frame order")


@dataclass
class HybridAdaptiveController:
    """Small rolling-window controller; never restarts an export."""

    workers: int = 1
    max_workers: int = 8
    window: int = 8
    history: list[tuple[float, float, float, bool]] = field(default_factory=list)

    def observe(
        self,
        *,
        combined_gain_pct: float,
        gpu_regression_pct: float,
        cpu_clock_ok: bool = True,
        memory_safe: bool = True,
    ) -> int:
        """Return the next worker budget using the documented conservative gate."""
        safe = bool(cpu_clock_ok and memory_safe)
        self.history.append((float(combined_gain_pct), float(gpu_regression_pct), float(self.workers), safe))
        if len(self.history) > max(1, int(self.window)):
            del self.history[:-int(self.window)]
        if not safe or gpu_regression_pct > 3.0 or combined_gain_pct < 1.0:
            self.workers = max(0, self.workers - 1)
        elif combined_gain_pct >= 5.0 and gpu_regression_pct < 3.0:
            self.workers = min(max(0, self.max_workers), self.workers + 1)
        return self.workers


class NvidiaPreparedFrameAdapter:
    """NVIDIA-specific boundary for a future CPU-frame upload to NVENC.

    The adapter intentionally does not encode, mux, or change pixel depth. It
    validates the canonical frame and delegates the actual CUDA/D3D11 upload
    to a caller-supplied function owned by the NVIDIA backend.
    """

    backend = "nv"
    encoder = "NVENC"

    @staticmethod
    def from_payload(
        frame_index: int,
        payload: bytes | bytearray | memoryview,
        *,
        width: int,
        height: int,
        fps: float,
        pixel_format: str,
        effective_timeline_timestamp: float | None = None,
        color_primaries: str = "bt2020",
        transfer: str = "arib-std-b67",
        matrix: str = "bt2020nc",
        range: str = "tv",
        orientation: int = 0,
    ) -> PreparedVideoFrame:
        """Build a frame without narrowing the source to 8-bit.

        P010 is accepted at its native 3 bytes/pixel semiplanar size. RGBA and
        NV12 are retained for SDR/diagnostic callers, but no implicit
        conversion is performed here.
        """
        raw = bytes(payload)
        fmt = str(pixel_format).strip().lower()
        pixels = int(width) * int(height)
        expected_by_format = {
            "rgba": pixels * 4,
            "nv12": pixels * 3 // 2,
            "p010le": pixels * 3,
            "p010": pixels * 3,
        }
        expected = expected_by_format.get(fmt)
        if expected is None:
            raise ValueError(f"unsupported NVIDIA prepared pixel format: {pixel_format}")
        if expected <= 0 or len(raw) != expected:
            raise ValueError(f"{fmt} payload size {len(raw)} != {expected}")
        if float(fps) <= 0:
            raise ValueError("fps must be positive")
        index = int(frame_index)
        return PreparedVideoFrame(
            frame_index=index,
            pts=index,
            duration=1,
            effective_timeline_timestamp=(
                index / float(fps)
                if effective_timeline_timestamp is None
                else float(effective_timeline_timestamp)
            ),
            pixel_format=("p010le" if fmt == "p010" else fmt),
            width=int(width),
            height=int(height),
            color_primaries=str(color_primaries),
            transfer=str(transfer),
            matrix=str(matrix),
            range=str(range),
            orientation=int(orientation) % 360,
            payload=raw,
        )

    @staticmethod
    def from_rgba(
        frame_index: int,
        payload: bytes | bytearray | memoryview,
        *,
        width: int,
        height: int,
        fps: float,
        effective_timeline_timestamp: float | None = None,
        color_primaries: str = "bt2020",
        transfer: str = "arib-std-b67",
        matrix: str = "bt2020nc",
        range: str = "tv",
        orientation: int = 0,
    ) -> PreparedVideoFrame:
        return NvidiaPreparedFrameAdapter.from_payload(
            frame_index, payload, width=width, height=height, fps=fps,
            pixel_format="rgba",
            effective_timeline_timestamp=effective_timeline_timestamp,
            color_primaries=color_primaries, transfer=transfer, matrix=matrix,
            range=range, orientation=orientation,
        )

    @staticmethod
    def handoff(frame: PreparedVideoFrame, upload: Callable[[PreparedVideoFrame], object]) -> object:
        if frame.pixel_format.lower() not in ("rgba", "nv12", "p010le"):
            raise ValueError("unsupported NVIDIA prepared pixel format")
        if frame.frame_index < 0 or frame.duration <= 0:
            raise ValueError("invalid frame timing")
        if frame.payload is None:
            raise ValueError("prepared frame has no payload")
        return upload(frame)


@dataclass(frozen=True)
class BackendHybridCapability:
    backend: str
    final_encoder: str
    canonical_cpu_frame_handoff: bool
    reason: str


CAPABILITIES = {
    "amd": BackendHybridCapability("amd", "AMF", False, "AMF CPU-frame handoff is not production-proven"),
    "nv": BackendHybridCapability("nv", "NVENC", False, "NVENC CPU-frame handoff is not production-proven"),
    "intel": BackendHybridCapability("intel", "QSV", False, "QSV CPU-frame handoff is not production-proven"),
}


@dataclass(frozen=True)
class HybridDecision:
    requested: RenderMode
    effective: RenderMode
    cpu_workers: int
    cpu_share: float
    reason: str


def normalize_render_mode(value: object) -> RenderMode:
    if isinstance(value, RenderMode):
        return value
    try:
        return RenderMode(str(value or "gpu").strip().lower())
    except ValueError:
        return RenderMode.GPU


def classify_topology(adapter_names: Iterable[str] = ()) -> GpuTopology:
    """Conservative classifier; unknown never authorizes CPU contribution."""
    names = " ".join(str(item).lower() for item in adapter_names)
    if any(token in names for token in ("radeon(tm) graphics", "ryzen", "intel(r) uhd", "intel(r) iris")):
        return GpuTopology.APU
    if any(token in names for token in ("nvidia", "geforce", "rtx", "radeon rx", "arc a")):
        return GpuTopology.DISCRETE
    return GpuTopology.UNKNOWN


def choose_hybrid_mode(
    *,
    requested: object,
    backend: str,
    topology: GpuTopology = GpuTopology.UNKNOWN,
    gpu_regression_pct: float = 0.0,
    combined_gain_pct: float = 0.0,
    memory_safe: bool = True,
) -> HybridDecision:
    """Return a fail-safe execution decision for a rolling hybrid window.

    The thresholds are policy only.  Until a backend has a verified canonical
    handoff, HYBRID resolves to GPU; it never falls back to mixed encoders or
    a second audio stream.
    """
    mode = normalize_render_mode(requested)
    if mode is not RenderMode.HYBRID:
        return HybridDecision(mode, mode, 0, 0.0, "explicit render mode")
    cap = CAPABILITIES.get(backend, CAPABILITIES["amd"])
    if topology is GpuTopology.APU:
        return HybridDecision(mode, RenderMode.GPU, 0, 0.0, "APU/shared-memory: GPU priority")
    if not cap.canonical_cpu_frame_handoff:
        return HybridDecision(mode, RenderMode.GPU, 0, 0.0, f"{cap.final_encoder}: {cap.reason}")
    if not memory_safe:
        return HybridDecision(mode, RenderMode.GPU, 0, 0.0, "memory/commit safety controller")
    if gpu_regression_pct > 3.0 or combined_gain_pct < 1.0:
        return HybridDecision(mode, RenderMode.GPU, 0, 0.0, "rolling GPU-priority controller")
    return HybridDecision(mode, RenderMode.HYBRID, 1, 0.05, "bounded experimental contribution")
