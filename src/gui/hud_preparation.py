"""HUD_PREPARING state of a project load: real stages, real progress only.

The tracker belongs to one project load generation.  Workers report stage
start / item progress / finish; every change publishes a snapshot through
``emit`` (a Qt signal in the controller).  The Preview dims itself and shows
the snapshot while ``active`` is True.

Progress honesty: a stage is *determinate* only when its worker reports a
real item count (map tiles, telemetry clips when there are several);
otherwise the bar is indeterminate.  Nothing advances on a timer.
"""

from __future__ import annotations

import itertools
import threading
import time
from typing import Callable, Optional

HUD_PREPARING = "HUD_PREPARING"
HUD_READY = "HUD_READY"

STAGE_LABELS = {
    "telemetry": "Wczytywanie telemetrii",
    "fit_sync": "Synchronizacja FIT",
    "compass": "Analiza IMU i kalibracja kompasu",
    "hud_data": "Przygotowanie danych HUD",
    "hud_frame": "Składanie podglądu HUD",
    "hud_frame_charts": "Budowanie wykresów i podglądu HUD",
    "map": "Przygotowanie mapy",
}
STAGE_ORDER = ("telemetry", "fit_sync", "compass", "hud_data", "hud_frame", "map")
# Display names of the indicator a failed stage leaves unavailable.
STAGE_INDICATOR = {"compass": "Kompas", "map": "Mapa", "hud_frame": "Podgląd HUD"}

PENDING, ACTIVE, DONE, ERROR = "pending", "active", "done", "error"

# Global snapshot order: a later tracker of the same generation (late FIT
# attach) must never look older than the one it replaced.
_SEQ = itertools.count(1)


class HudPreparation:
    def __init__(self, generation: int, emit: Callable[[dict], None]) -> None:
        self.generation = int(generation)
        self._emit = emit
        self._lock = threading.Lock()
        self._stages: dict[str, dict] = {}
        self._labels: dict[str, str] = {}
        self._closed = False
        self._t0 = time.perf_counter()

    # ── worker API (any thread) ───────────────────────────────────────
    def add(self, key: str, label: Optional[str] = None) -> None:
        with self._lock:
            if self._closed:
                return
            if key not in self._stages or self._stages[key]["state"] in (DONE, ERROR):
                self._stages[key] = {"state": PENDING, "done": None, "total": None, "error": ""}
            if label:
                self._labels[key] = label
        self._publish()

    def start(self, key: str, label: Optional[str] = None) -> None:
        with self._lock:
            if self._closed:
                return
            st = self._stages.setdefault(key, {"state": PENDING, "done": None, "total": None, "error": ""})
            st.update(state=ACTIVE, done=None, total=None, error="")
            if label:
                self._labels[key] = label
        self._publish()

    def progress(self, key: str, done: int, total: int) -> None:
        with self._lock:
            st = self._stages.get(key)
            if self._closed or st is None or st["state"] in (DONE, ERROR):
                return
            st.update(state=ACTIVE, done=max(0, int(done)), total=max(0, int(total)))
        self._publish()

    def finish(self, key: str, error: str = "") -> None:
        with self._lock:
            st = self._stages.get(key)
            if self._closed or st is None or st["state"] in (DONE, ERROR):
                return
            st.update(state=ERROR if error else DONE, error=str(error or ""))
        self._publish()

    def state_of(self, key: str) -> Optional[str]:
        with self._lock:
            st = self._stages.get(key)
            return st["state"] if st else None

    def close(self) -> None:
        """Cancelled / superseded / failed load: publish an inactive snapshot."""
        with self._lock:
            if self._closed:
                return
            self._closed = True
        self._publish(force_inactive=True)

    # ── snapshot ──────────────────────────────────────────────────────
    def snapshot(self, force_inactive: bool = False) -> dict:
        with self._lock:
            keys = [k for k in STAGE_ORDER if k in self._stages] + [k for k in self._stages if k not in STAGE_ORDER]
            stages = [{"key": k, "label": self._labels.get(k) or STAGE_LABELS.get(k, k), **self._stages[k]} for k in keys]
            seq = next(_SEQ)
            closed = self._closed
        active = (not force_inactive and not closed and any(s["state"] in (PENDING, ACTIVE) for s in stages))
        current = next((s for s in stages if s["state"] == ACTIVE), None) or \
            next((s for s in stages if s["state"] == PENDING), None)
        determinate = bool(current and current["total"] and current["total"] >= 1 and current["done"] is not None)
        errors = [{"stage": s["key"], "label": s["label"], "indicator": STAGE_INDICATOR.get(s["key"], s["label"]),
                   "error": s["error"]} for s in stages if s["state"] == ERROR]
        return {
            "state": HUD_PREPARING if active else HUD_READY,
            "active": active,
            "cancelled": closed,
            "generation": self.generation,
            "seq": seq,
            "title": "Przygotowywanie wskaźników...",
            "stage_key": current["key"] if (current and active) else "",
            "stage_label": current["label"] if (current and active) else "Gotowe",
            "stage_index": (stages.index(current) + 1) if (current and active) else len(stages),
            "stage_count": len(stages),
            "determinate": determinate and active,
            "done": current["done"] if determinate else None,
            "total": current["total"] if determinate else None,
            "fraction": (min(1.0, current["done"] / current["total"]) if determinate else None),
            "errors": errors,
            "stages": stages,
            "elapsed_s": round(time.perf_counter() - self._t0, 3),
        }

    def _publish(self, force_inactive: bool = False) -> None:
        try:
            self._emit(self.snapshot(force_inactive=force_inactive))
        except Exception:
            pass
