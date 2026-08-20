"""Opt-in, low-volume diagnostics for the NVIDIA producer pipeline.

This module is intentionally inert unless ``TELEM_PIPELINE_AUDIT`` is set to
one of ``1``, ``true``, ``yes`` or ``on``.  It records compact per-frame
timestamps in the parent process and writes aggregate statistics at the end of
an export.  It is an audit aid, not a runtime scheduling policy.
"""

from __future__ import annotations

import csv
import json
import math
import os
import statistics
import threading
from pathlib import Path
from typing import Any


def env_enabled(name: str = "TELEM_PIPELINE_AUDIT") -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _percentiles(values: list[float]) -> dict[str, float]:
    if not values:
        return {key: 0.0 for key in ("avg", "median", "p90", "p95", "p99", "max")}
    ordered = sorted(values)

    def percentile(p: float) -> float:
        if len(ordered) == 1:
            return ordered[0]
        pos = (len(ordered) - 1) * p
        lo = math.floor(pos)
        hi = math.ceil(pos)
        if lo == hi:
            return ordered[lo]
        return ordered[lo] + (ordered[hi] - ordered[lo]) * (pos - lo)

    return {
        "avg": statistics.fmean(values),
        "median": statistics.median(values),
        "p90": percentile(0.90),
        "p95": percentile(0.95),
        "p99": percentile(0.99),
        "max": max(values),
    }


def _ms(values_ns: list[int | float]) -> list[float]:
    return [float(value) / 1_000_000.0 for value in values_ns if value is not None and value >= 0]


def _duration(records: list[dict[str, Any]], start: str, end: str) -> list[float]:
    return _ms([
        row[end] - row[start]
        for row in records
        if row.get(start) is not None and row.get(end) is not None and row[end] >= row[start]
    ])


class PipelineAuditRecorder:
    """Parent-process collector for one audited stream."""

    def __init__(self, output_path: str | None = None) -> None:
        self.enabled = True
        self.started_ns = 0
        self.frames: dict[int, dict[str, Any]] = {}
        self.occupancy: dict[str, list[int]] = {
            "in_flight": [],
            "shm_used": [],
            "writer_queue": [],
        }
        self.main_stats: dict[str, list[float]] = {}
        self.counters: dict[str, int] = {}
        self._lock = threading.Lock()
        default_path = Path("scratch") / "etap5f_pipeline_audit.json"
        self.output_path = Path(output_path or os.environ.get("TELEM_PIPELINE_AUDIT_PATH", default_path))

    def start(self, started_ns: int) -> None:
        self.started_ns = started_ns

    def frame(self, index: int) -> dict[str, Any]:
        with self._lock:
            return self.frames.setdefault(index, {"index": index})

    def mark(self, index: int, name: str, value_ns: int | None = None) -> None:
        with self._lock:
            self.frames.setdefault(index, {"index": index})[name] = value_ns

    def add_stat(self, name: str, value_ms: float) -> None:
        with self._lock:
            self.main_stats.setdefault(name, []).append(float(value_ms))

    def increment(self, name: str, amount: int = 1) -> None:
        with self._lock:
            self.counters[name] = self.counters.get(name, 0) + amount

    def sample_occupancy(self, name: str, value: int) -> None:
        with self._lock:
            self.occupancy.setdefault(name, []).append(max(0, int(value)))

    def _summary_for(self, records: list[dict[str, Any]], start: str, end: str) -> dict[str, float]:
        return _percentiles(_duration(records, start, end))

    @staticmethod
    def _histogram(values: list[int], max_value: int | None = None) -> dict[str, Any]:
        if not values:
            return {"counts": {}, "percentages": {}, "buckets": {}}
        max_seen = max(max_value or 0, max(values))
        counts = {str(i): values.count(i) for i in range(max_seen + 1)}
        total = len(values)
        percentages = {key: (count / total * 100.0) for key, count in counts.items()}
        bucket_defs = {
            "0-2": lambda v: 0 <= v <= 2,
            "3-5": lambda v: 3 <= v <= 5,
            "6-7": lambda v: 6 <= v <= 7,
            "8+": lambda v: v >= 8,
        }
        buckets = {
            key: {
                "count": sum(1 for value in values if predicate(value)),
                "percent": sum(1 for value in values if predicate(value)) / total * 100.0,
            }
            for key, predicate in bucket_defs.items()
        }
        return {"counts": counts, "percentages": percentages, "buckets": buckets, "samples": total}

    @staticmethod
    def _correlation(xs: list[float], ys: list[float]) -> float | None:
        pairs = [(x, y) for x, y in zip(xs, ys) if math.isfinite(x) and math.isfinite(y)]
        if len(pairs) < 2:
            return None
        mx = statistics.fmean(x for x, _ in pairs)
        my = statistics.fmean(y for _, y in pairs)
        numerator = sum((x - mx) * (y - my) for x, y in pairs)
        den_x = math.sqrt(sum((x - mx) ** 2 for x, _ in pairs))
        den_y = math.sqrt(sum((y - my) ** 2 for _, y in pairs))
        return numerator / (den_x * den_y) if den_x and den_y else None

    def finalize(self, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        with self._lock:
            rows = [dict(self.frames[index]) for index in sorted(self.frames)]
            occupancy = {key: list(values) for key, values in self.occupancy.items()}
            main_stats = {key: list(values) for key, values in self.main_stats.items()}
            counters = dict(self.counters)

        raw_records = rows

        phases = {
            "wait_for_free_slot": self._summary_for(raw_records, "frame_scheduled_ns", "slot_acquired_ns"),
            "executor_submit": self._summary_for(raw_records, "submit_started_ns", "job_submitted_ns"),
            "worker_queue_delay": self._summary_for(raw_records, "job_submitted_ns", "worker_started_ns"),
            "worker_render": self._summary_for(raw_records, "worker_render_started_ns", "worker_render_finished_ns"),
            "worker_clear_target": self._summary_for(raw_records, "worker_clear_started_ns", "worker_clear_finished_ns"),
            "worker_shm_copy": self._summary_for(raw_records, "worker_render_finished_ns", "shm_copy_finished_ns"),
            "worker_compute": self._summary_for(raw_records, "worker_started_ns", "shm_copy_finished_ns"),
            "result_delivery_main": self._summary_for(raw_records, "worker_done_ns", "result_observed_ns"),
            "ordered_output_wait_hol": self._summary_for(raw_records, "result_observed_ns", "ordered_output_ns"),
            "main_shm_view": self._summary_for(raw_records, "ordered_output_ns", "shm_view_ready_ns"),
            "main_queue_put": self._summary_for(raw_records, "queue_put_started_ns", "queue_put_finished_ns"),
            "writer_ready_wait": self._summary_for(raw_records, "queue_put_finished_ns", "ffmpeg_write_started_ns"),
            "queue_to_writer_wait": self._summary_for(raw_records, "queue_put_finished_ns", "writer_dequeued_ns"),
            "ffmpeg_stdin_write": self._summary_for(raw_records, "ffmpeg_write_started_ns", "ffmpeg_write_finished_ns"),
            "slot_post_worker_hold": self._summary_for(raw_records, "shm_copy_finished_ns", "shm_released_ns"),
            "slot_lifetime": self._summary_for(raw_records, "slot_acquired_ns", "shm_released_ns"),
        }

        hol_values = _duration(raw_records, "result_observed_ns", "ordered_output_ns")
        write_values = _duration(raw_records, "ffmpeg_write_started_ns", "ffmpeg_write_finished_ns")

        worker_jobs: dict[str, list[dict[str, Any]]] = {}
        for row in raw_records:
            pid = row.get("worker_pid")
            if pid is not None:
                worker_jobs.setdefault(str(pid), []).append(row)
        worker_utilization: dict[str, Any] = {}
        for pid, jobs in worker_jobs.items():
            jobs.sort(key=lambda item: item.get("worker_started_ns", 0))
            busy = _duration(jobs, "worker_started_ns", "shm_copy_finished_ns")
            starts = [item["worker_started_ns"] for item in jobs if item.get("worker_started_ns") is not None]
            ends = [item["shm_copy_finished_ns"] for item in jobs if item.get("shm_copy_finished_ns") is not None]
            idle = _ms([
                starts[i] - ends[i - 1]
                for i in range(1, min(len(starts), len(ends)))
                if starts[i] >= ends[i - 1]
            ])
            span_ms = ((max(ends) - min(starts)) / 1_000_000.0) if starts and ends else 0.0
            worker_utilization[pid] = {
                "jobs": len(jobs),
                "busy_sum_ms": sum(busy),
                "busy_percent_active_span": (sum(busy) / span_ms * 100.0) if span_ms else 0.0,
                "active_span_ms": span_ms,
                "job": _percentiles(busy),
                "idle_gap": _percentiles(idle),
            }

        hol_over_1ms = sum(1 for value in hol_values if value > 1.0)
        hol_over_5ms = sum(1 for value in hol_values if value > 5.0)
        write_over_1ms = sum(1 for value in write_values if value > 1.0)
        write_over_5ms = sum(1 for value in write_values if value > 5.0)
        zero_copy_frames = sum(1 for row in raw_records if row.get("worker_zero_copy") is True)
        fallback_copy_frames = sum(1 for row in raw_records if row.get("worker_zero_copy") is False)
        write_rows = [
            row for row in raw_records
            if row.get("ffmpeg_write_started_ns") is not None
            and row.get("ffmpeg_write_finished_ns") is not None
        ]
        if write_rows:
            write_span_ms = (
                max(row["ffmpeg_write_finished_ns"] for row in write_rows)
                - min(row["ffmpeg_write_started_ns"] for row in write_rows)
            ) / 1_000_000.0
            bytes_per_frame = (metadata or {}).get("frame_size_bytes", 0)
            total_bytes = bytes_per_frame * len(write_rows)
            pipe_bandwidth = {
                "bytes_per_frame": bytes_per_frame,
                "total_bytes": total_bytes,
                "writer_span_ms": write_span_ms,
                "writer_MB_per_s": (total_bytes / 1_000_000.0) / (write_span_ms / 1000.0) if write_span_ms else 0.0,
                "writer_GB_per_s": (total_bytes / 1_000_000_000.0) / (write_span_ms / 1000.0) if write_span_ms else 0.0,
            }
        else:
            pipe_bandwidth = {"bytes_per_frame": 0, "total_bytes": 0, "writer_span_ms": 0.0,
                              "writer_MB_per_s": 0.0, "writer_GB_per_s": 0.0}

        result = {
            "schema": "telem-nvidia-etap5f-v1",
            "metadata": metadata or {},
            "frames": len(raw_records),
            "phases_ms": phases,
            "worker_utilization": worker_utilization,
            "occupancy": {
                name: self._histogram(values, max_value=8)
                for name, values in occupancy.items()
            },
            "main_serial_ms": {name: _percentiles(values) for name, values in main_stats.items()},
            "counters": counters,
            "hol": {
                "frames_with_ordered_wait_over_1ms": hol_over_1ms,
                "frames_with_ordered_wait_over_5ms": hol_over_5ms,
                "total_ordered_wait_ms": sum(hol_values),
            },
            "ffmpeg_backpressure": {
                "writes_over_1ms": write_over_1ms,
                "writes_over_5ms": write_over_5ms,
                "total_write_ms": sum(write_values),
            },
            "zero_copy": {
                "frames": zero_copy_frames,
                "fallback_copy_frames": fallback_copy_frames,
                "all_frames_zero_copy": bool(raw_records) and fallback_copy_frames == 0,
            },
            "pipe_bandwidth": pipe_bandwidth,
            "correlation": {
                "write_duration_vs_in_flight": self._correlation(
                    [float(row.get("in_flight_at_ordered", 0)) for row in raw_records if row.get("ffmpeg_write_started_ns") is not None], write_values
                ) if len(write_values) >= 2 else None,
                "slot_wait_vs_in_flight": self._correlation(
                    [float(row.get("in_flight_at_schedule", 0)) for row in raw_records if row.get("slot_acquired_ns") is not None],
                    _duration(raw_records, "frame_scheduled_ns", "slot_acquired_ns"),
                ) if len(_duration(raw_records, "frame_scheduled_ns", "slot_acquired_ns")) >= 2 else None,
            },
            "lifecycle_ms_from_run_start": [],
        }
        lifecycle_records = []
        for row in raw_records:
            converted = dict(row)
            if self.started_ns:
                for key, value in list(converted.items()):
                    if key.endswith("_ns") and isinstance(value, int):
                        converted[key.replace("_ns", "_ms")] = (value - self.started_ns) / 1_000_000.0
                        del converted[key]
            lifecycle_records.append(converted)
        result["lifecycle_ms_from_run_start"] = lifecycle_records
        out_json = self.output_path
        out_json.parent.mkdir(parents=True, exist_ok=True)
        out_json.write_text(json.dumps(result, indent=2), encoding="utf-8")
        out_csv = out_json.with_suffix(".csv")
        fieldnames = sorted({key for row in lifecycle_records for key in row})
        with out_csv.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(lifecycle_records)
        result["artifacts"] = {"json": str(out_json), "csv": str(out_csv)}
        return result
