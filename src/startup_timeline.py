"""Startup timeline instrumentation and accounting for TeleM render pipeline."""

from __future__ import annotations

import csv
import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional


@dataclass
class TimelineEntry:
    stage: str
    t_start: float
    t_end: float
    duration_ms: float
    thread: str
    process: str
    cache_hit: Optional[bool] = None
    notes: str = ""

    def to_row(self) -> dict[str, Any]:
        hit_str = ""
        if self.cache_hit is not None:
            hit_str = "True" if self.cache_hit else "False"
        return {
            "stage": self.stage,
            "t_start": f"{self.t_start:.6f}",
            "t_end": f"{self.t_end:.6f}",
            "duration_ms": f"{self.duration_ms:.3f}",
            "thread": self.thread,
            "process": self.process,
            "cache_hit": hit_str,
            "notes": self.notes,
        }


class StartupTimelineTracker:
    _instance: Optional["StartupTimelineTracker"] = None
    _lock = threading.Lock()

    def __init__(self, role: str = "auto") -> None:
        self.role = role if role != "auto" else ("child" if os.environ.get("TELEM_AMD_CHILD_PROCESS") == "1" else "parent")
        self.pid = os.getpid()
        self.entries: list[TimelineEntry] = []
        self._active_stages: dict[str, tuple[float, str, str]] = {}
        self._tracker_lock = threading.Lock()

    @classmethod
    def get_instance(cls) -> "StartupTimelineTracker":
        with cls._lock:
            if cls._instance is None:
                cls._instance = StartupTimelineTracker()
            return cls._instance

    def mark_event(
        self,
        stage: str,
        cache_hit: Optional[bool] = None,
        notes: str = "",
        timestamp: Optional[float] = None,
    ) -> float:
        """Record an instantaneous point event (t_start == t_end, duration == 0)."""
        now = time.perf_counter() if timestamp is None else timestamp
        th_name = threading.current_thread().name
        entry = TimelineEntry(
            stage=stage,
            t_start=now,
            t_end=now,
            duration_ms=0.0,
            thread=th_name,
            process=f"{self.role}:{self.pid}",
            cache_hit=cache_hit,
            notes=notes,
        )
        with self._tracker_lock:
            self.entries.append(entry)
        print(f"[STARTUP TIMELINE] event='{stage}' t={now:.6f}s {notes}".strip(), flush=True)
        return now

    def start_stage(self, stage: str, notes: str = "", start_suffix: str = "begin") -> float:
        """Start a timed stage."""
        now = time.perf_counter()
        th_name = threading.current_thread().name
        with self._tracker_lock:
            self._active_stages[stage] = (now, th_name, notes)
        self.mark_event(f"{stage} {start_suffix}".strip(), notes=notes, timestamp=now)
        return now

    def end_stage(
        self,
        stage: str,
        cache_hit: Optional[bool] = None,
        notes: str = "",
        end_suffix: str = "end",
    ) -> float:
        """End a timed stage and record its interval."""
        now = time.perf_counter()
        with self._tracker_lock:
            start_info = self._active_stages.pop(stage, None)
        if start_info is not None:
            t_start, th_name, start_notes = start_info
            dur_ms = (now - t_start) * 1000.0
            combined_notes = f"{start_notes} {notes}".strip()
            entry = TimelineEntry(
                stage=stage,
                t_start=t_start,
                t_end=now,
                duration_ms=dur_ms,
                thread=th_name,
                process=f"{self.role}:{self.pid}",
                cache_hit=cache_hit,
                notes=combined_notes,
            )
            with self._tracker_lock:
                self.entries.append(entry)
            self.mark_event(f"{stage} {end_suffix}".strip(), notes=notes, timestamp=now)
            print(f"[STARTUP TIMELINE] stage='{stage}' duration={dur_ms:.3f}ms notes={combined_notes}", flush=True)
            return now
        # If no start was found, record point event
        return self.mark_event(f"{stage} {end_suffix}".strip(), cache_hit=cache_hit, notes=notes, timestamp=now)

    def record_interval(
        self,
        stage: str,
        t_start: float,
        t_end: float,
        cache_hit: Optional[bool] = None,
        notes: str = "",
        start_suffix: str = "begin",
        end_suffix: str = "end",
    ) -> None:
        """Record an interval with known start and end timestamps."""
        dur_ms = (t_end - t_start) * 1000.0
        th_name = threading.current_thread().name
        entry = TimelineEntry(
            stage=stage,
            t_start=t_start,
            t_end=t_end,
            duration_ms=dur_ms,
            thread=th_name,
            process=f"{self.role}:{self.pid}",
            cache_hit=cache_hit,
            notes=notes,
        )
        self.mark_event(f"{stage} {start_suffix}".strip(), notes=notes, timestamp=t_start)
        with self._tracker_lock:
            self.entries.append(entry)
        self.mark_event(f"{stage} {end_suffix}".strip(), notes=notes, timestamp=t_end)
        print(f"[STARTUP TIMELINE] stage='{stage}' duration={dur_ms:.3f}ms notes={notes}", flush=True)

    def save_partial_csv(self, path: Path | str) -> Path:
        """Save this process's entries to a partial CSV."""
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        fieldnames = [
            "stage", "t_start", "t_end", "duration_ms",
            "thread", "process", "cache_hit", "notes"
        ]
        with p.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            with self._tracker_lock:
                for entry in self.entries:
                    writer.writerow(entry.to_row())
        return p


def merge_startup_timelines(
    parent_csv: Path | str,
    child_csv: Path | str,
    output_csv: Path | str,
) -> list[dict[str, Any]]:
    """Merge parent and child startup timeline CSV files sorted chronologically."""
    rows: list[dict[str, Any]] = []
    fieldnames = [
        "stage", "t_start", "t_end", "duration_ms",
        "thread", "process", "cache_hit", "notes"
    ]
    seen: set[tuple[str, str, str]] = set()
    for p in (Path(parent_csv), Path(child_csv)):
        if p.exists():
            with p.open("r", newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for r in reader:
                    key = (r.get("stage", ""), r.get("t_start", ""), r.get("t_end", ""))
                    if key not in seen:
                        seen.add(key)
                        rows.append(r)

    rows.sort(key=lambda r: float(r["t_start"]))

    out_p = Path(output_csv)
    out_p.parent.mkdir(parents=True, exist_ok=True)
    with out_p.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in rows:
            writer.writerow(r)
    return rows


def compute_accounting_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Calculate unaccounted time gate: UNACCOUNTED_MS < 5% CLICK_TO_FIRST_FRAME_MS.
    
    Uses interval union of all tracked timeline stages between Click and First Frame
    to rigorously account for execution time, avoiding concurrent double-counting
    (such as parallel child spawn in parent vs child restore in child) while
    strictly tracking any untracked gaps.
    """
    t_click: Optional[float] = None
    t_first_frame: Optional[float] = None

    for r in rows:
        st = r.get("stage", "")
        if st in ("GUI Render clicked", "snapshot begin", "snapshot") and t_click is None:
            t_click = float(r["t_start"])
        elif st in ("first encoded frame", "first progress callback", "first frame encode end", "first source frame ready"):
            t_first_frame = float(r["t_end"])

    if t_click is None and rows:
        t_click = float(rows[0]["t_start"])
    if t_first_frame is None and rows:
        t_first_frame = float(rows[-1]["t_end"])

    click_to_first_frame_ms = (t_first_frame - t_click) * 1000.0 if (t_click and t_first_frame) else 0.0

    stage_durations: dict[str, float] = {}
    intervals: list[tuple[float, float]] = []

    for r in rows:
        st = r.get("stage", "")
        dur = float(r.get("duration_ms", 0.0))
        ts = float(r.get("t_start", 0.0))
        te = float(r.get("t_end", 0.0))

        # Record stage duration
        if dur > 0.0 and not st.endswith(" begin") and not st.endswith(" end"):
            stage_durations[st] = stage_durations.get(st, 0.0) + dur

        # Interval collection for union (only positive duration within startup window)
        if dur > 0.0 and ts < te and t_click is not None and t_first_frame is not None:
            c_start = max(t_click, ts)
            c_end = min(t_first_frame, te)
            if c_end > c_start:
                intervals.append((c_start, c_end))

    # Interval union calculation
    intervals.sort(key=lambda x: x[0])
    merged: list[tuple[float, float]] = []
    for iv in intervals:
        if not merged:
            merged.append(iv)
        else:
            prev_s, prev_e = merged[-1]
            if iv[0] <= prev_e:
                merged[-1] = (prev_s, max(prev_e, iv[1]))
            else:
                merged.append(iv)

    accounted_ms = sum((e - s) * 1000.0 for s, e in merged) if merged else sum(stage_durations.values())
    unaccounted_ms = max(0.0, click_to_first_frame_ms - accounted_ms)
    unaccounted_pct = (unaccounted_ms / click_to_first_frame_ms * 100.0) if click_to_first_frame_ms > 0 else 0.0
    gate_pass = unaccounted_pct < 5.0

    return {
        "click_to_first_frame_ms": click_to_first_frame_ms,
        "accounted_stage_ms": accounted_ms,
        "unaccounted_ms": unaccounted_ms,
        "unaccounted_pct": unaccounted_pct,
        "gate_pass": gate_pass,
        "stage_durations": stage_durations,
        "t_click": t_click,
        "t_first_frame": t_first_frame,
    }

