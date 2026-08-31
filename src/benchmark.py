"""Benchmark and performance measurement utility for TeleM.
"""

from __future__ import annotations

import time
from collections import defaultdict
import numpy as np
from src.render_logging import render_print

print = render_print


class BenchmarkTracker:
    _instance = None

    @classmethod
    def get_instance(cls) -> BenchmarkTracker:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self, window_size: int = 300) -> None:
        self.window_size = window_size
        self.enabled = False
        self.reset()

    def reset(self) -> None:
        self.timings = defaultdict(list)
        self.counters = defaultdict(int)
        self.active_timers = {}

    def enable(self, val: bool = True) -> None:
        self.enabled = val

    def start_timer(self, name: str) -> None:
        if not self.enabled:
            return
        self.active_timers[name] = time.perf_counter()

    def stop_timer(self, name: str) -> None:
        if not self.enabled:
            return
        t_start = self.active_timers.pop(name, None)
        if t_start is not None:
            dt = (time.perf_counter() - t_start) * 1000.0  # in ms
            history = self.timings[name]
            history.append(dt)
            if len(history) > self.window_size:
                history.pop(0)

    def count(self, name: str, value: int = 1) -> None:
        if not self.enabled:
            return
        self.counters[name] += value

    def get_summary(self) -> dict[str, Any]:
        summary = {}
        for name, values in self.timings.items():
            if not values:
                continue
            arr = np.array(values)
            summary[name] = {
                "avg": float(np.mean(arr)),
                "p95": float(np.percentile(arr, 95)),
                "min": float(np.min(arr)),
                "max": float(np.max(arr)),
                "count": len(values),
            }
        
        # Add frame rate calculations for specific cycles
        for cycle_name in ("preview_cycle", "render_cycle"):
            if cycle_name in self.timings and len(self.timings[cycle_name]) > 1:
                # Calculate average FPS over the window
                avg_ms = summary[cycle_name]["avg"]
                summary[cycle_name]["fps"] = 1000.0 / avg_ms if avg_ms > 0 else 0.0

        summary["counters"] = dict(self.counters)
        return summary

    def print_summary(self) -> None:
        if not self.enabled:
            return
        summary = self.get_summary()
        print("\n=== TeleM PERFORMANCE BENCHMARK ===", flush=True)
        for name, stats in summary.items():
            if name == "counters":
                continue
            fps_str = f" | FPS: {stats['fps']:.1f}" if "fps" in stats else ""
            print(
                f"{name:<25}: avg={stats['avg']:6.2f}ms | p95={stats['p95']:6.2f}ms "
                f"| range=[{stats['min']:.2f}-{stats['max']:.2f}]ms (n={stats['count']}){fps_str}",
                flush=True
            )
        if "counters" in summary and summary["counters"]:
            print("Counters:", flush=True)
            for name, val in summary["counters"].items():
                print(f"  {name:<23}: {val}", flush=True)
        print("===================================\n", flush=True)
