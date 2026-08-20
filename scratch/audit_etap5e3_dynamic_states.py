"""ETAP 5E.3 diagnostics: prefix states, Model-A cache safety and labels."""

from __future__ import annotations

import json
import statistics
import sys
from bisect import bisect_right
from datetime import timedelta
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scratch.validate_etap5b6_direct import FPS, H, N, W, setup
from src.ffmpeg.worker_cache import WORKER_CACHE
from src.indicators.dispatcher import render_value_indicator


def _aligned_target(history, target):
    sample_tz = history.timestamps[0].tzinfo
    if sample_tz is None and target.tzinfo is not None:
        return target.replace(tzinfo=None)
    if sample_tz is not None and target.tzinfo is None:
        from datetime import timezone
        return target.replace(tzinfo=timezone.utc)
    return target


def _state_indices(history):
    result = []
    for frame in range(N):
        # The chart contract is activity-start based.  Use each series'
        # immutable chart start so cadence and HR retain independent timelines.
        target = _aligned_target(
            history, history.chart_start_dt + timedelta(seconds=frame / FPS)
        )
        result.append(bisect_right(history.timestamps, target) - 1)
    return result


def _stats(indices):
    counts = {}
    for value in indices:
        counts[value] = counts.get(value, 0) + 1
    unique = len(counts)
    hits = len(indices) - unique
    return {
        "unique_states": unique,
        "cache_misses": unique,
        "cache_hits": hits,
        "hit_rate_pct": 100.0 * hits / len(indices),
        "avg_frames_per_state": len(indices) / unique if unique else 0.0,
        "max_frames_per_state": max(counts.values()) if counts else 0,
        "states_with_repeats": sum(1 for count in counts.values() if count > 1),
        "counts": counts,
    }


def _fmt(value, key):
    if value is None:
        return "—"
    # This matches the production chart value precision used by the audit
    # benchmark; missing remains a distinct state.
    return f"{value:.0f}"


def _render(layout, key, history, target, value):
    cfg = layout["indicators"][key]
    unit = "rpm" if key == "fit_cadence_text" else "BPM"
    return render_value_indicator(
        W, H, layout, "", key, value if value is not None else 0.0,
        unit, cfg.get("label", key), cfg_override=cfg,
        formatted_val=_fmt(value, key), history_data=history,
        current_position=0.5, target_dt=target,
    )[0]


def _quantization_diagnostic(layout, key, history, indices):
    # Select repeated-index frames strictly between two FIT timestamps.  The
    # exact frame is the Model-A reference; the quantized frame is diagnostic
    # only and is never used by production code.
    candidates = []
    for frame in range(1, N - 1):
        idx = indices[frame]
        if idx >= 0 and indices[frame - 1] == idx and indices[frame + 1] == idx:
            exact = _aligned_target(
                history, history.chart_start_dt + timedelta(seconds=frame / FPS)
            )
            quantized = history.timestamps[idx]
            if exact != quantized:
                candidates.append((frame, idx, exact, quantized))
    if not candidates:
        return {"available": False}
    # Sample a spread of repeated-index frames; one early frame can be a
    # degenerate one-point case where quantization happens to be invisible.
    sample_candidates = candidates[:: max(1, len(candidates) // 12)][:12]
    samples = []
    for frame, idx, exact, quantized in sample_candidates:
        value = history[idx]
        a = np.asarray(_render(layout, key, history, exact, value))
        b = np.asarray(_render(layout, key, history, quantized, value))
        diff = np.abs(a.astype(np.int16) - b.astype(np.int16))
        changed = np.any(diff != 0, axis=2)
        samples.append({
            "frame": frame,
            "visible_index": idx,
            "delta_ms": (exact - quantized).total_seconds() * 1000.0,
            "max_diff": int(diff.max()),
            "different_pixels": int(changed.sum()),
        })
    return {
        "available": True,
        "candidate_frames": len(candidates),
        "samples": samples,
        "max_diff_observed": max(item["max_diff"] for item in samples),
        "max_different_pixels_observed": max(item["different_pixels"] for item in samples),
    }


def main():
    layout, _regions, anchor, *_ = setup()
    histories = WORKER_CACHE["_precomputed_chart_data"]
    output = {"frames": N, "fps": FPS, "activity_anchor": str(anchor), "charts": {}}
    for key in ("fit_cadence_text", "fit_heart_rate_text"):
        history = histories[key]
        indices = _state_indices(history)
        state_stats = _stats(indices)
        values = [history[i] if i >= 0 else None for i in indices]
        labels = [_fmt(value, key) for value in values]
        label_counts = {}
        for label in labels:
            label_counts[label] = label_counts.get(label, 0) + 1
        numeric = [float(value) for value in values if value is not None]
        if key == "fit_heart_rate_text":
            avgs_by_index = []
            running_sum = 0.0
            running_count = 0
            for value in history:
                if value is not None:
                    running_sum += float(value)
                    running_count += 1
                avgs_by_index.append(
                    running_sum / running_count if running_count else None
                )
            avgs = [avgs_by_index[idx] if idx >= 0 else None for idx in indices]
            avg_keys = [None if value is None else round(value, 12) for value in avgs]
            avg_unique = len(set(avg_keys))
            avg_hits = len(avg_keys) - avg_unique
        else:
            avg_unique = None
            avg_hits = None
        output["charts"][key] = {
            "length": len(history),
            "chart_start": str(history.chart_start_dt),
            "chart_end": str(history.chart_end_dt),
            "first_sample": str(history.timestamps[0]),
            "last_sample": str(history.timestamps[-1]),
            "state_stats": state_stats,
            "visible_value_none_frames": sum(value is None for value in values),
            "visible_zero_frames": sum(value == 0 for value in values if value is not None),
            "unique_formatted_labels": len(label_counts),
            "label_cache_hits_if_keyed_by_string": len(labels) - len(label_counts),
            "label_hit_rate_pct_if_keyed_by_string": 100.0 * (len(labels) - len(label_counts)) / len(labels),
            "top_labels": sorted(label_counts.items(), key=lambda pair: -pair[1])[:10],
            "hr_average_unique_states": avg_unique,
            "hr_average_cache_hits": avg_hits,
            "hr_average_hit_rate_pct": (100.0 * avg_hits / len(values)) if avg_hits is not None else None,
            "quantization": _quantization_diagnostic(layout, key, history, indices),
        }
    destination = ROOT / "scratch" / "etap5e3_dynamic_states.json"
    destination.write_text(json.dumps(output, indent=2, default=str), encoding="utf-8")
    print(json.dumps(output, indent=2, default=str))


if __name__ == "__main__":
    main()
