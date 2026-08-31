"""Cost-weighted progress for the background project-load pipeline."""

from __future__ import annotations

from collections.abc import Callable


class LoadProgressTracker:
    """Map real load stages to one monotonic 0..100 progress value.

    Weights are deliberately small and local to one load.  They are based on
    the measured GPMF extractor costs, not on an artificial timer.
    """

    GPMF_WEIGHTS = {
        "gpmf_convert": 1.0,
        "gpmf_exiftool_extract": 0.2,
        "track_extract": 3.34,
        "iso_extract": 6.29,
        "exposure_extract": 5.95,
        "temperature_extract": 3.11,
        "accelerometer_extract": 3.84,
        "gyroscope_extract": 4.31,
        "speed_extract": 0.5,
        "altitude_extract": 0.5,
        "gps_anchor": 0.2,
        "smoothing": 0.4,
        "gps_track_extract": 1.0,
        "heading_derive": 0.2,
        "slope_derive": 0.2,
    }

    def __init__(self, emit: Callable[[int, str], None]) -> None:
        self.emit = emit
        self._last = 0
        self._stage_start: int | None = None
        self._stage_end: int | None = None
        self._stage_name: str | None = None
        self._gpmf_start = 45
        self._gpmf_end = 72
        self._weights = dict(self.GPMF_WEIGHTS)
        self._total = sum(self._weights.values())

    def _stage_bounds(self, stage: str) -> tuple[int, int]:
        keys = list(self._weights)
        index = keys.index(stage) if stage in self._weights else len(keys)
        before = sum(self._weights[key] for key in keys[:index])
        weight = self._weights.get(stage, 0.1)
        start = round(self._gpmf_start + before / self._total * (self._gpmf_end - self._gpmf_start))
        end = round(self._gpmf_start + (before + weight) / self._total * (self._gpmf_end - self._gpmf_start))
        return start, max(start, end)

    def _set(self, value: float, text: str) -> None:
        pct = max(self._last, min(99, int(value)))
        if pct != self._last or text:
            self._last = pct
            self.emit(pct, text)

    def fixed(self, percent: int, text: str) -> None:
        self._set(percent, text)

    def start(self, stage: str, text: str | None = None) -> None:
        self._stage_start, self._stage_end = self._stage_bounds(stage)
        self._stage_name = stage
        self._set(self._stage_start, text or f"GPMF: {stage.replace('_extract', '')}")

    def update(self, stage: str, done: int, total: int, text: str | None = None) -> None:
        if self._stage_name != stage or self._stage_start is None or self._stage_end is None:
            self.start(stage, text)
        fraction = done / max(1, total)
        value = self._stage_start + (self._stage_end - self._stage_start) * min(1.0, max(0.0, fraction))
        self._set(value, text or f"GPMF: {stage.replace('_extract', '')}")

    def finish(self, stage: str, text: str | None = None) -> None:
        self.start(stage, text)
        self._set(self._stage_end or self._last, text or f"GPMF: {stage.replace('_extract', '')}")
        self._stage_start = self._stage_end = None
        self._stage_name = None
