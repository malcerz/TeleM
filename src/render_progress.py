"""Cost-based progress reporting for long-running render preparation."""
from __future__ import annotations

import os
import time
from typing import Callable, Optional

from src.render_logging import render_debug_print


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
        self.other_estimate = 0.5
        render_debug_print("[Progress] HUD estimated time/cost initial=learning from measured work", flush=True)
        render_debug_print(f"[Progress] Render estimated time/cost={self.render_estimate:.3f}s baseline_fps={default_fps:.3f}", flush=True)

    def _hud_estimate(self) -> float:
        if self.hud_complete:
            return max(self.hud_actual_estimate, 0.001)
        if self.hud_done > 0 and self.hud_total > 0:
            return max(0.001, (time.perf_counter() - self.hud_started) / (self.hud_done / self.hud_total))
        return 0.001

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
            global_pct = 100.0 * (hud_est + render_est * max(0.0, min(1.0, internal))) / total_est
        else:
            global_pct = 100.0 * (hud_est + render_est) / total_est
        global_pct = max(self.last_global, min(99.9 if phase != "complete" else 100.0, global_pct))
        if not force and now - self.last_emit < 0.10 and global_pct - self.last_global < 0.25:
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
