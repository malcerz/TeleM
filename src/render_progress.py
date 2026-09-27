"""Cost-based progress reporting for long-running render preparation."""
from __future__ import annotations

import os
import time
from dataclasses import dataclass
from enum import Enum
from typing import Callable, Optional

from src.render_logging import render_debug_print

_generation_counter = 0


class RenderCancelReason(str, Enum):
    """Why a render session was asked to stop."""

    NONE = "NONE"
    USER_CANCEL = "USER_CANCEL"
    INTERNAL_STOP = "INTERNAL_STOP"
    SUPERSEDED = "SUPERSEDED"
    ERROR = "ERROR"
    APP_SHUTDOWN = "APP_SHUTDOWN"


@dataclass(frozen=True)
class RenderCancelRequest:
    """Generation-tagged cancellation request crossing the GUI boundary."""

    generation_id: int
    reason: RenderCancelReason
    source: str


def render_cancel_log_message(reason: RenderCancelReason) -> str:
    """Return the user-facing exporter cancellation message for a reason."""
    if reason == RenderCancelReason.USER_CANCEL:
        return "Export cancelled by user."
    return f"Export cancelled (reason={reason.value})."


def next_render_generation_id() -> int:
    """Return a process-wide monotonically increasing export generation."""
    global _generation_counter
    _generation_counter += 1
    return _generation_counter


@dataclass(frozen=True)
class RenderProgressState:
    """Canonical GUI snapshot for one export session."""

    generation_id: int
    state: str
    frame: int = 0
    total_frames: int = 0
    percent: float = 0.0
    global_percent: float = 0.0
    elapsed_s: float = 0.0
    fps: float = 0.0
    eta_s: float | None = None
    finalization_stage: str = ""
    cancel_requested: bool = False
    cancelled: bool = False
    failed: bool = False
    completed: bool = False
    cancel_reason: RenderCancelReason = RenderCancelReason.NONE
    cancel_source: str = ""
    # Cross-backend semantic contract.  The legacy names above remain for Qt
    # callers; these fields make the producer/backend meaning explicit.
    backend: str = ""
    role: str = ""
    phase: str = ""
    frame_done: int = 0
    frame_total: int = 0
    fps_instant: float = 0.0
    fps_average: float = 0.0
    compression_text: str = ""
    # HUD preparation state
    prep_phase: str = ""
    prep_done: int = 0
    prep_total: int = 0
    prep_pct: float = 0.0
    prep_label: str = ""


def format_render_progress_status(snapshot: RenderProgressState) -> str:
    """Format the canonical snapshot for the application status bar."""
    if snapshot.state == "preparing":
        frame = f"{snapshot.prep_done} / {snapshot.prep_total}" if snapshot.prep_total else "--"
        pct = f"{snapshot.percent:.1f}%" if snapshot.prep_total or snapshot.percent > 0 else "--"
        fps = "--"
    else:
        frame = f"{snapshot.frame} / {snapshot.total_frames}" if snapshot.total_frames else "--"
        pct = f"{snapshot.percent:.1f}%" if snapshot.total_frames else "--"
        fps = f"{snapshot.fps:.1f}" if snapshot.fps > 0 else "--"
    if snapshot.elapsed_s is None or not (0 <= snapshot.elapsed_s <= 3600000):
        elapsed_txt = "--:--"
    else:
        elapsed = max(0, int(snapshot.elapsed_s))
        mins, secs = divmod(elapsed, 60)
        hours, mins = divmod(mins, 60)
        elapsed_txt = f"{hours}:{mins:02d}:{secs:02d}" if hours else f"{mins:02d}:{secs:02d}"
    if snapshot.eta_s is None or not (0 <= snapshot.eta_s <= 3600000):
        eta_txt = "--:--"
    else:
        eta = max(0, int(snapshot.eta_s))
        eta_m, eta_s = divmod(eta, 60)
        eta_h, eta_m = divmod(eta_m, 60)
        eta_txt = f"{eta_h}:{eta_m:02d}:{eta_s:02d}" if eta_h else f"{eta_m:02d}:{eta_s:02d}"
    if snapshot.completed:
        status = "Gotowe"
    elif snapshot.cancelled:
        status = "Anulowano"
    elif snapshot.failed:
        status = "Błąd"
    elif snapshot.cancel_requested:
        status = "Anulowanie..."
    elif snapshot.state == "finalizing":
        status = snapshot.finalization_stage or "Finalizacja..."
    elif snapshot.state == "preparing":
        status = snapshot.prep_label or snapshot.finalization_stage or "Przygotowywanie HUD..."
    else:
        status = "Renderowanie..."
    item_label = "HUD" if snapshot.state == "preparing" else "Frame"
    return (
        f"{item_label}: {frame} | {pct} | FPS: {fps} | Czas: {elapsed_txt} "
        f"| ETA: {eta_txt} | {status}"
    )


@dataclass
class HudPhaseProfile:
    phase_id: str
    name: str
    weight: float
    start_time: float = 0.0
    end_time: float = 0.0
    elapsed_ms: float = 0.0
    items_done: int = 0
    items_total: int = 0
    completed: bool = False


class HudPrepProgressTracker:
    """Central source of truth for HUD Preparation Progress.

    Tracks registered phases with measured weights and real items counters (current / total).
    Computes monotonic 0..100% HUD preparation progress and reports to GUI.
    """

    def __init__(
        self,
        phases: list[tuple[str, str, float]],
        callback: Optional[Callable] = None,
        *,
        global_prep_start_pct: float = 0.0,
        global_prep_end_pct: float = 10.0,
        backend_name: str = "",
    ):
        self.callback = callback
        self.global_prep_start_pct = float(global_prep_start_pct)
        self.global_prep_end_pct = float(global_prep_end_pct)
        self.backend_name = backend_name
        self.start_time = time.perf_counter()

        total_w = sum(w for _, _, w in phases) or 1.0
        self.phases: list[HudPhaseProfile] = [
            HudPhaseProfile(
                phase_id=p_id,
                name=name,
                weight=w / total_w,
            )
            for p_id, name, w in phases
        ]
        self._phase_index_map = {p.phase_id: i for i, p in enumerate(self.phases)}
        self.current_phase_idx = -1
        self._last_overall_pct = 0.0
        self._last_emit_time = 0.0
        self._last_logged_pct = -5.0
        self.is_finished = False

    def start_phase(self, phase_id: str, items_total: int = 1, detail: str = "") -> None:
        """Begin a new phase. Any prior incomplete phases are marked complete."""
        now = time.perf_counter()
        target_idx = self._phase_index_map.get(phase_id)
        if target_idx is None:
            return

        for idx in range(target_idx):
            p = self.phases[idx]
            if not p.completed:
                if p.start_time == 0.0:
                    p.start_time = now
                p.end_time = now
                p.elapsed_ms = (p.end_time - p.start_time) * 1000.0
                p.items_done = max(p.items_done, p.items_total)
                p.completed = True

        self.current_phase_idx = target_idx
        cur = self.phases[target_idx]
        cur.start_time = now
        cur.items_total = max(1, items_total)
        cur.items_done = 0
        cur.completed = False

        self._emit(force=True, detail=detail)

    def update(self, items_done: int, items_total: Optional[int] = None, detail: str = "") -> None:
        """Update items count for the current phase and report progress."""
        if self.current_phase_idx < 0 or self.current_phase_idx >= len(self.phases):
            return
        cur = self.phases[self.current_phase_idx]
        if items_total is not None and items_total > 0:
            cur.items_total = items_total
        cur.items_done = min(items_done, cur.items_total)
        self._emit(force=False, detail=detail)

    def step(self, delta: int = 1, detail: str = "") -> None:
        """Increment items done by delta."""
        if self.current_phase_idx < 0 or self.current_phase_idx >= len(self.phases):
            return
        cur = self.phases[self.current_phase_idx]
        self.update(cur.items_done + delta, cur.items_total, detail=detail)

    def complete_phase(self, phase_id: Optional[str] = None) -> None:
        """Mark current (or specified) phase as complete."""
        now = time.perf_counter()
        idx = self._phase_index_map.get(phase_id) if phase_id else self.current_phase_idx
        if idx is None or idx < 0 or idx >= len(self.phases):
            return
        cur = self.phases[idx]
        cur.end_time = now
        cur.elapsed_ms = (cur.end_time - (cur.start_time or now)) * 1000.0
        cur.items_done = cur.items_total
        cur.completed = True
        self._emit(force=True)

    def finish(self) -> dict:
        """Complete all phases and mark HUD prep 100% complete."""
        now = time.perf_counter()
        for p in self.phases:
            if not p.completed:
                if p.start_time == 0.0:
                    p.start_time = now
                p.end_time = now
                p.elapsed_ms = (p.end_time - p.start_time) * 1000.0
                p.items_done = p.items_total
                p.completed = True
        self.is_finished = True
        self._last_overall_pct = 100.0
        self._emit(force=True)

        total_ms = (now - self.start_time) * 1000.0
        print(f"[HUD PREP PROGRESS] TOTAL HUD PREPARATION: {total_ms:.1f} ms ({total_ms/1000.0:.2f} s)", flush=True)
        return self.get_profile()

    def get_profile(self) -> dict:
        """Return diagnostic profile of all phases."""
        total_ms = sum(p.elapsed_ms for p in self.phases)
        slowest = sorted(self.phases, key=lambda p: p.elapsed_ms, reverse=True)
        return {
            "total_prep_ms": total_ms,
            "total_prep_s": total_ms / 1000.0,
            "phases": [
                {
                    "phase_id": p.phase_id,
                    "name": p.name,
                    "weight": p.weight,
                    "elapsed_ms": p.elapsed_ms,
                    "items_done": p.items_done,
                    "items_total": p.items_total,
                }
                for p in self.phases
            ],
            "slowest_3": [
                {"phase_id": p.phase_id, "name": p.name, "elapsed_ms": p.elapsed_ms}
                for p in slowest[:3]
            ],
        }

    def _emit(self, force: bool = False, detail: str = "") -> None:
        now = time.perf_counter()
        completed_weight = sum(p.weight for p in self.phases if p.completed)
        if self.current_phase_idx >= 0 and self.current_phase_idx < len(self.phases):
            cur = self.phases[self.current_phase_idx]
            if not cur.completed and cur.items_total > 0:
                frac = max(0.0, min(1.0, cur.items_done / cur.items_total))
                completed_weight += cur.weight * frac
                phase_done = cur.items_done
                phase_total = cur.items_total
                phase_name = cur.name
                phase_id = cur.phase_id
                phase_pct = frac * 100.0
            else:
                phase_done = cur.items_total
                phase_total = cur.items_total
                phase_name = cur.name
                phase_id = cur.phase_id
                phase_pct = 100.0
        else:
            phase_done = 0
            phase_total = 0
            phase_name = "Przygotowanie HUD"
            phase_id = "prep"
            phase_pct = 0.0

        overall_pct = min(100.0, max(self._last_overall_pct, completed_weight * 100.0))
        self._last_overall_pct = overall_pct

        if not force and not self.is_finished:
            if (now - self._last_emit_time < 0.08) and (overall_pct - self._last_overall_pct < 0.5):
                return
        self._last_emit_time = now

        if force or (overall_pct - self._last_logged_pct >= 2.0) or self.is_finished:
            self._last_logged_pct = overall_pct
            elapsed_ms = (now - self.start_time) * 1000.0
            print(
                f"[HUD PREP PROGRESS] phase={phase_id} done={phase_done} total={phase_total} "
                f"phase_pct={phase_pct:.1f}% overall_pct={overall_pct:.1f}% elapsed_ms={elapsed_ms:.1f}",
                flush=True,
            )

        if self.is_finished:
            label = "Przygotowanie HUD — 100% · Gotowe"
        elif phase_total > 1:
            label = f"Przygotowanie HUD — {overall_pct:.0f}% · {phase_name} {phase_done}/{phase_total}"
        elif detail:
            label = f"Przygotowanie HUD — {overall_pct:.0f}% · {detail}"
        else:
            label = f"Przygotowanie HUD — {overall_pct:.0f}% · {phase_name}"

        global_pct = self.global_prep_start_pct + (overall_pct / 100.0) * (self.global_prep_end_pct - self.global_prep_start_pct)

        hud_state = {
            "phase": "prep",
            "prep_phase": phase_id,
            "pct": overall_pct / 100.0,
            "overall_hud_pct": overall_pct,
            "phase_pct": phase_pct,
            "work_done": phase_done,
            "work_total": phase_total,
            "label": label,
            "global_pct": global_pct,
            "backend": self.backend_name,
        }

        if self.callback:
            try:
                self.callback(phase_done, phase_total, now - self.start_time, 0.0, hud_state)
            except Exception:
                pass


class RenderProgressTracker:
    """Map measured HUD work and frame work onto one monotonic 0..100 scale."""

    def __init__(self, total_frames: int, callback: Optional[Callable], *, target_fps: float = 30.0):
        self.total_frames = max(1, int(total_frames))
        self.target_fps = max(1.0, float(target_fps))
        self.callback = callback
        self.started = time.perf_counter()
        self.hud_started = self.started
        self.hud_done = 0.0
        self.hud_total = 0.0
        self.hud_complete = False
        self.hud_actual_estimate = 0.0
        self.render_done = 0
        self.render_elapsed = 0.0
        self.last_global = 0.0
        self.last_emit = 0.0
        default_fps = float(os.environ.get("TELEM_PROGRESS_BASELINE_FPS", "26.359"))
        self.render_estimate = self.total_frames / max(1.0, default_fps)
        self.hud_initial_estimate = max(1.0, self.total_frames * 0.00035)
        self.other_estimate = 0.5
        render_debug_print("[Progress] HUD estimated time/cost initial=learning from measured work", flush=True)
        render_debug_print(f"[Progress] Render estimated time/cost={self.render_estimate:.3f}s baseline_fps={default_fps:.3f}", flush=True)

    def _hud_estimate(self) -> float:
        if self.hud_complete:
            return max(self.hud_actual_estimate, 0.001)
        if self.hud_done > 0 and self.hud_total > 0:
            return max(0.001, (time.perf_counter() - self.hud_started) / (self.hud_done / self.hud_total))
        return self.hud_initial_estimate

    def _emit(self, *, phase: str, internal: float, label: str, done: int = 0, total: int = 0,
              elapsed: Optional[float] = None, force: bool = False, **extra) -> None:
        now = time.perf_counter()
        hud_est = self._hud_estimate()
        render_est = max(self.render_estimate, self.render_elapsed)
        total_est = hud_est + render_est + self.other_estimate
        if phase == "complete":
            global_pct = 100.0
        elif phase == "prep":
            global_pct = 100.0 * hud_est * max(0.0, min(1.0, internal)) / total_est
        elif phase == "render":
            # Render frames map to 0..95% of total bar
            raw_render_pct = 100.0 * (hud_est + render_est * max(0.0, min(1.0, internal))) / total_est
            global_pct = min(95.0, raw_render_pct)
        elif phase == "finalize":
            drain_pct = extra.get("drain_pct")
            if drain_pct is not None:
                # Map drain to 95..98%
                global_pct = 95.0 + (max(0.0, min(100.0, float(drain_pct))) / 100.0) * 3.0
            else:
                # Mux / postprocess holds at 98..99.9%
                global_pct = max(98.0, min(99.9, self.last_global))
        else:
            global_pct = 100.0 * (hud_est + render_est) / total_est
        global_pct = max(self.last_global, min(99.9 if phase != "complete" else 100.0, global_pct))
        if not force and phase != "finalize" and now - self.last_emit < 0.10 and global_pct - self.last_global < 0.25:
            return
        self.last_global = global_pct
        self.last_emit = now
        state = {
            "phase": "prep" if phase == "prep" else ("finalize" if phase == "finalize" else "render"),
            "pct": max(0.0, min(1.0, internal)),
            "global_pct": global_pct,
            "label": label,
            "hud_internal": max(0.0, min(1.0, self.hud_done / max(1.0, self.hud_total))) if self.hud_total else 0.0,
            "hud_estimate_s": hud_est,
            "render_estimate_s": render_est,
            "hud_weight": hud_est / total_est,
            "work_done": done,
            "work_total": total,
            **extra,
        }
        render_debug_print(f"[Progress] global progress={global_pct:.2f}% phase={phase} label={label}", flush=True)
        if self.callback:
            self.callback(done, total, max(0.0, elapsed if elapsed is not None else now - self.started), 0.0, state)

    def hud_work(self, done: float, total: int, label: str) -> None:
        total = max(1, int(total))
        self.hud_total = max(self.hud_total, float(total))
        self.hud_done = max(self.hud_done, min(float(done), self.hud_total))
        if self.hud_done > 0 and time.perf_counter() - self.last_emit >= 0.10:
            render_debug_print(f"[HUD] internal progress={100.0 * self.hud_done / self.hud_total:.2f}% {done}/{total} {label}", flush=True)
        self._emit(phase="prep", internal=self.hud_done / self.hud_total, label=f"Przygotowywanie HUD: {label}", done=done, total=total)

    def hud_complete_report(self) -> None:
        self.hud_done = max(self.hud_done, self.hud_total or 1.0)
        self.hud_complete = True
        actual = time.perf_counter() - self.hud_started
        self.hud_actual_estimate = actual
        render_debug_print(f"[HUD] actual total duration={actual:.3f}s", flush=True)
        weight = self._hud_estimate() / (self._hud_estimate() + self.render_estimate + self.other_estimate)
        render_debug_print(f"[Progress] HUD global weight={weight * 100.0:.2f}%", flush=True)
        self._emit(phase="prep", internal=1.0, label="Renderowanie klatek...", force=True)

    def frame(self, completed: int, elapsed: float, fps: float) -> None:
        self.render_done = max(self.render_done, int(completed))
        self.render_elapsed = max(self.render_elapsed, float(elapsed))
        if completed > 0 and elapsed > 0:
            self.render_estimate = max(self.render_estimate, elapsed * self.total_frames / completed)
        self._emit(phase="render", internal=self.render_done / self.total_frames,
                   label="Renderowanie klatek...", done=self.render_done, total=self.total_frames,
                   elapsed=elapsed, fps=fps, ts=(self.render_done - 1) / self.target_fps,
                   frame_idx=max(0, self.render_done - 1))

    def complete(self, elapsed: float) -> None:
        self._emit(phase="complete", internal=1.0, label="Zakończono", done=self.total_frames,
                   total=self.total_frames, elapsed=elapsed, force=True)
