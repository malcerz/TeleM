"""Telemetry synchronization (FIT/GPX ↔ video) for the application controller.

Manual offset, SmartSync (GoPro GPS trajectory or camera IMU) and per-material
persistence.  The contract and the data-layer shift live in
``src/telemetry_sync.py`` / ``TelemetryDataManager.set_telemetry_sync``.
"""

from __future__ import annotations

import threading
import time as _time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from src.telemetry_sync import (
    METHOD_MANUAL,
    METHOD_NONE,
    METHOD_SMARTSYNC_GPS,
    METHOD_SMARTSYNC_IMU,
    SYNC_CLIP_LAYOUT_KEY,
    SYNC_LAYOUT_KEY,
    SYNC_METHOD_LAYOUT_KEY,
    TelemetrySyncState,
    load_sync_state,
    material_key,
    save_sync_state,
)

OFFSET_LIMIT_S = 24 * 3600.0
CLIP_AGREEMENT_S = 0.3

METHOD_LABELS = {
    METHOD_NONE: "brak korekty (czas z plików)",
    METHOD_MANUAL: "ręczna",
    METHOD_SMARTSYNC_IMU: "SmartSync IMU",
    METHOD_SMARTSYNC_GPS: "SmartSync GPS",
}


def _epoch(dt: datetime) -> float:
    return (dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)).timestamp()


class SyncMixin:
    # ------------------------------------------------------------------
    # Setup
    # ------------------------------------------------------------------

    def _init_telemetry_sync(self) -> None:
        self._sync_state = TelemetrySyncState()
        self._sync_proposal: Optional[dict[str, Any]] = None
        self._sync_message: str = ""
        self._sync_lock = threading.Lock()
        self._sync_pending: Optional[tuple[TelemetrySyncState, bool]] = None
        self._sync_worker: Optional[threading.Thread] = None
        self._sync_auto_cancel = threading.Event()
        self._sync_auto_thread: Optional[threading.Thread] = None
        self._sync_last_progress = ""
        s = self.signals
        s.sig_sync_offset_nudge.connect(self._on_sync_nudge)
        s.sig_sync_offset_set.connect(self._on_sync_set)
        s.sig_sync_offset_reset.connect(self._on_sync_reset)
        s.sig_sync_auto_requested.connect(self._on_sync_auto_requested)
        s.sig_sync_auto_cancel.connect(self._on_sync_auto_cancel)
        s.sig_sync_proposal_accept.connect(self._on_sync_proposal_accept)
        s.sig_sync_applied.connect(self._on_sync_applied)
        s.sig_sync_auto_finished.connect(self._on_sync_auto_finished)
        s.sig_sync_state_request.connect(self._publish_sync_state)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _sync_activity_path(self) -> Optional[Path]:
        p = getattr(self, "fit_path", None) or getattr(self, "gpx_path", None)
        return Path(p) if p else None

    def _sync_material_key(self) -> Optional[str]:
        paths = list(getattr(self, "video_paths", None) or [])
        activity = self._sync_activity_path()
        if not paths or activity is None:
            return None
        return material_key(paths, activity)

    def _sync_clip_windows(self) -> list[tuple[datetime, datetime]]:
        tl = getattr(self, "video_timeline", None)
        out: list[tuple[datetime, datetime]] = []
        for clip in getattr(tl, "clips", None) or []:
            a, b = getattr(clip, "absolute_start_dt", None), getattr(clip, "absolute_end_dt", None)
            if a is None or b is None:
                return []
            out.append((a, b))
        return out

    def _sync_has_activity(self) -> bool:
        tm = getattr(self, "telemetry", None)
        return bool(tm is not None and (getattr(tm, "_fit_base", None) or getattr(tm, "_gpx_base", None)))

    def _mirror_sync_to_layout(self, state: TelemetrySyncState) -> None:
        layout = getattr(self, "layout", None)
        if not isinstance(layout, dict):
            return
        layout[SYNC_LAYOUT_KEY] = round(float(state.offset_s), 4)
        layout[SYNC_METHOD_LAYOUT_KEY] = state.method
        clips = {str(k): round(float(v), 4) for k, v in state.clip_offsets_s.items() if abs(v) > 1e-9}
        if clips:
            layout[SYNC_CLIP_LAYOUT_KEY] = clips
        else:
            layout.pop(SYNC_CLIP_LAYOUT_KEY, None)
        if getattr(self, "layout_mgr", None):
            self.layout_mgr.layout = layout

    def _sync_payload(self, busy: bool = False) -> dict[str, Any]:
        st = self._sync_state
        tm = getattr(self, "telemetry", None)
        return {
            "offset_s": float(st.offset_s),
            "clip_offsets_s": dict(st.clip_offsets_s),
            "method": st.method,
            "method_label": METHOD_LABELS.get(st.method, st.method),
            "confidence": st.confidence,
            "confidence_level": st.confidence_level,
            "detail": st.detail,
            "message": self._sync_message,
            "proposal": dict(self._sync_proposal) if self._sync_proposal else None,
            "busy": bool(busy or (self._sync_auto_thread is not None and self._sync_auto_thread.is_alive())),
            "has_activity": self._sync_has_activity(),
            "has_imu": bool(tm is not None and getattr(tm, "gyroscope_samples", None)),
            "clip_count": len(self._sync_clip_windows()) or 1,
        }

    def _publish_sync_state(self, busy: bool = False) -> None:
        try:
            self.signals.sig_sync_state_changed.emit(self._sync_payload(busy))
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Applying an offset (coalesced, off the GUI thread)
    # ------------------------------------------------------------------

    def set_telemetry_sync_state(self, state: TelemetrySyncState, *, persist: bool = True,
                                 message: Optional[str] = None) -> None:
        state.offset_s = max(-OFFSET_LIMIT_S, min(OFFSET_LIMIT_S, round(float(state.offset_s), 3)))
        self._sync_state = state
        if message is not None:
            self._sync_message = message
        self._mirror_sync_to_layout(state)
        self._publish_sync_state()
        with self._sync_lock:
            self._sync_pending = (state, persist)
            if self._sync_worker is not None and self._sync_worker.is_alive():
                return
            self._sync_worker = threading.Thread(target=self._sync_worker_loop, name="TelemetrySync", daemon=True)
            self._sync_worker.start()

    def _sync_worker_loop(self) -> None:
        while True:
            with self._sync_lock:
                item = self._sync_pending
                self._sync_pending = None
                if item is None:
                    self._sync_worker = None
                    return
            state, persist = item
            try:
                info = self.telemetry.set_telemetry_sync(
                    state.offset_s, state.clip_offsets_s, self._sync_clip_windows(),
                )
            except Exception as exc:
                info = {"error": str(exc)}
                print(f"[TelemetrySync] apply failed: {exc}", flush=True)
            self.signals.sig_sync_applied.emit({"state": state, "persist": persist, "info": info})

    def _on_sync_applied(self, payload: object) -> None:
        if not isinstance(payload, dict):
            return
        state = payload.get("state")
        if payload.get("persist") and isinstance(state, TelemetrySyncState):
            self._persist_sync_state(state)
        self._invalidate_after_sync()

    def _invalidate_after_sync(self) -> None:
        self._clear_caches()
        render_tab = getattr(getattr(self, "ui", None), "render_tab", None) or getattr(self, "_render_tab", None)
        if render_tab is not None and hasattr(render_tab, "_hud_prepare_cache"):
            render_tab._hud_prepare_cache = None
        try:
            self._save_session_layout()
        except Exception:
            pass
        try:
            self._render_preview()
        except Exception as exc:
            print(f"[TelemetrySync] preview refresh failed: {exc}", flush=True)

    def _persist_sync_state(self, state: TelemetrySyncState) -> None:
        key = self._sync_material_key()
        if key is None:
            return
        try:
            names = ", ".join(Path(p).name for p in getattr(self, "video_paths", []) or [])
            act = self._sync_activity_path()
            unchanged = state.method == METHOD_NONE and abs(state.offset_s) < 1e-9 and not state.has_clip_offsets
            save_sync_state(key, None if unchanged else state, label=f"{names} + {act.name if act else ''}")
        except Exception as exc:
            print(f"[TelemetrySync] persist failed: {exc}", flush=True)

    # ------------------------------------------------------------------
    # Project lifecycle
    # ------------------------------------------------------------------

    def _reset_telemetry_sync_for_load(self) -> None:
        """New material: start from the file timestamps (no stale offset)."""
        self._sync_state = TelemetrySyncState()
        self._sync_proposal = None
        self._sync_message = ""
        tm = getattr(self, "telemetry", None)
        if tm is not None:
            tm.telemetry_sync_offset_s = 0.0
            tm.telemetry_sync_clip_offsets_s = {}
            tm.telemetry_sync_clip_windows = []

    def _restore_telemetry_sync_for_project(self) -> None:
        """Restore the saved sync of this video set + activity (worker-safe)."""
        tm = getattr(self, "telemetry", None)
        if tm is None:
            return
        windows = self._sync_clip_windows()
        tm.telemetry_sync_clip_windows = windows
        state = None
        key = self._sync_material_key()
        if key is not None:
            state = load_sync_state(key)
        if state is None:
            state = TelemetrySyncState()
            self._sync_message = ""
        else:
            self._sync_message = f"Przywrócono zapisaną synchronizację ({METHOD_LABELS.get(state.method, state.method)})."
            print(f"[TelemetrySync] restored offset={state.offset_s:+.3f}s method={state.method}", flush=True)
        self._sync_state = state
        if abs(state.offset_s) > 1e-9 or state.has_clip_offsets:
            tm.set_telemetry_sync(state.offset_s, state.clip_offsets_s, windows)
        self._mirror_sync_to_layout(state)
        self._publish_sync_state()

    def apply_layout_telemetry_sync(self, layout: Optional[dict] = None) -> None:
        """Apply the sync stored in a layout snapshot (export queue restore)."""
        layout = layout if isinstance(layout, dict) else getattr(self, "layout", None)
        if not isinstance(layout, dict):
            return
        clips = {}
        for k, v in (layout.get(SYNC_CLIP_LAYOUT_KEY) or {}).items():
            try:
                clips[int(k)] = float(v)
            except (TypeError, ValueError):
                continue
        state = TelemetrySyncState(
            offset_s=float(layout.get(SYNC_LAYOUT_KEY, 0.0) or 0.0),
            clip_offsets_s=clips,
            method=str(layout.get(SYNC_METHOD_LAYOUT_KEY) or METHOD_NONE),
        )
        self._sync_state = state
        tm = getattr(self, "telemetry", None)
        if tm is not None:
            tm.set_telemetry_sync(state.offset_s, state.clip_offsets_s, self._sync_clip_windows())
        self._mirror_sync_to_layout(state)

    # ------------------------------------------------------------------
    # Manual control
    # ------------------------------------------------------------------

    def _manual_state(self, offset_s: float) -> TelemetrySyncState:
        return TelemetrySyncState(
            offset_s=offset_s,
            clip_offsets_s=dict(self._sync_state.clip_offsets_s),
            method=METHOD_MANUAL,
            detail="Przesunięcie ustawione ręcznie.",
        )

    def _on_sync_nudge(self, delta_s: float) -> None:
        self.set_telemetry_sync_state(self._manual_state(self._sync_state.offset_s + float(delta_s)), message="")

    def _on_sync_set(self, value_s: float) -> None:
        if abs(float(value_s) - self._sync_state.offset_s) < 5e-4:
            return
        self.set_telemetry_sync_state(self._manual_state(float(value_s)), message="")

    def _on_sync_reset(self) -> None:
        self._sync_proposal = None
        self.set_telemetry_sync_state(TelemetrySyncState(), message="Przywrócono czas z plików (offset 0).")

    def _on_sync_proposal_accept(self) -> None:
        prop = self._sync_proposal
        if not prop or prop.get("offset_s") is None:
            return
        self._sync_proposal = None
        state = TelemetrySyncState(
            offset_s=float(prop["offset_s"]),
            clip_offsets_s={int(k): float(v) for k, v in (prop.get("clip_offsets_s") or {}).items()},
            method=prop.get("method") or METHOD_SMARTSYNC_IMU,
            confidence=prop.get("confidence"),
            confidence_level=prop.get("confidence_level") or "",
            detail="Propozycja SmartSync zaakceptowana ręcznie przez użytkownika.",
            smartsync=prop,
        )
        self.set_telemetry_sync_state(state, message="Zastosowano propozycję SmartSync (zatwierdzoną ręcznie).")

    # ------------------------------------------------------------------
    # SmartSync (asynchronous)
    # ------------------------------------------------------------------

    def _on_sync_auto_requested(self) -> None:
        if self._sync_auto_thread is not None and self._sync_auto_thread.is_alive():
            return
        if not self._sync_has_activity():
            self._sync_message = "Brak wczytanego pliku FIT/GPX — automatyczna synchronizacja niemożliwa."
            self._publish_sync_state()
            return
        self._sync_auto_cancel.clear()
        self._sync_message = "SmartSync: analiza..."
        self._sync_auto_thread = threading.Thread(target=self._sync_auto_worker, name="SmartSync", daemon=True)
        self._sync_auto_thread.start()
        self._publish_sync_state(busy=True)

    def _on_sync_auto_cancel(self) -> None:
        self._sync_auto_cancel.set()

    def _sync_progress(self, text: str) -> None:
        self._sync_last_progress = text
        try:
            self.signals.sig_sync_progress.emit(f"SmartSync: {text}")
        except Exception:
            pass

    def _sync_auto_worker(self) -> None:
        from src.telemetry_smartsync_imu import SmartSyncCancelled
        started = _time.perf_counter()
        try:
            result = self._run_smartsync()
        except SmartSyncCancelled:
            result = {"status": "CANCELLED", "message": "SmartSync anulowany przez użytkownika."}
        except Exception as exc:
            import traceback
            traceback.print_exc()
            result = {"status": "ERROR", "message": f"SmartSync: błąd analizy — {exc}"}
        result["elapsed_ms"] = round((_time.perf_counter() - started) * 1000.0, 1)
        print(f"[SmartSync] result {result.get('status')} offset={result.get('offset_s')} "
              f"method={result.get('method')} level={result.get('confidence_level')} "
              f"ms={result['elapsed_ms']}", flush=True)
        self.signals.sig_sync_auto_finished.emit(result)

    def _run_smartsync(self) -> dict[str, Any]:
        tm = self.telemetry
        cancel = self._sync_auto_cancel.is_set
        act = tm.activity_motion_arrays()
        if act is None:
            return {"status": "NO_ACTIVITY", "message": "Brak wczytanego pliku FIT/GPX z czasem i ruchem."}

        gps_note = ""
        gps_track = list(getattr(tm, "gps_track", None) or [])
        if len(gps_track) >= 10:
            self._sync_progress("dopasowanie śladu GPS kamery")
            res = self._smartsync_gps(tm, gps_track)
            if res.get("status") == "OK":
                return res
            gps_note = res.get("message", "")

        from src.telemetry_smartsync_imu import estimate_imu_offset
        gyro = getattr(tm, "gyroscope_array", None)
        accel = getattr(tm, "accelerometer_array", None)
        gyro = self._vector_array(gyro, getattr(tm, "gyroscope_samples", None))
        accel = self._vector_array(accel, getattr(tm, "accelerometer_samples", None))
        if gyro is None or len(gyro) < 50:
            proto = str((getattr(tm, "camera_metadata", None) or {}).get("proto", ""))
            extra = " (DJI Action 2, protokół dvtm_ac103 nie zapisuje IMU)" if "ac103" in proto else ""
            return {"status": "NO_IMU", "message": f"Nagranie nie zawiera danych IMU{extra} — dostępna tylko regulacja ręczna. {gps_note}".strip()}

        clips = self._sync_clip_windows()
        if not clips:
            start = getattr(tm, "start_dt_utc", None)
            dur = float(getattr(self, "video_duration_s", 0.0) or 0.0)
            if start is None or dur <= 0:
                return {"status": "ERROR", "message": "Brak czasu rozpoczęcia nagrania."}
            from datetime import timedelta
            clips = [(start, start + timedelta(seconds=dur))]

        per_clip = []
        for idx, (a, b) in enumerate(clips):
            if cancel():
                from src.telemetry_smartsync_imu import SmartSyncCancelled
                raise SmartSyncCancelled()
            label = f"klip {idx + 1}/{len(clips)}: " if len(clips) > 1 else ""
            t0 = _epoch(a)
            r = estimate_imu_offset(
                gyro=gyro, accel=accel, video_t0_epoch=t0,
                fit_t_epoch=act["t"], fit_speed_kmh=act["speed_kmh"], fit_lat=act["lat"], fit_lon=act["lon"],
                window_s=(0.0, (_epoch(b) - t0)),
                prior_offset_s=self._sync_state.effective_clip_offset(idx),
                cancel=cancel,
                progress=lambda m, label=label: self._sync_progress(label + m),
            )
            per_clip.append(r.to_dict())
        return self._combine_clip_results(per_clip, act.get("source", "fit"), gps_note)

    @staticmethod
    def _vector_array(arr: Any, samples: Any):
        import numpy as np
        if arr is not None and len(arr):
            return np.asarray(arr, dtype=np.float64)
        backing = getattr(samples, "_arr", None)
        if backing is not None and len(backing):
            return np.asarray(backing, dtype=np.float64)
        if samples:
            try:
                return np.array([[_epoch(dt), *v] for dt, v in samples], dtype=np.float64)
            except Exception:
                return None
        return None

    def _smartsync_gps(self, tm: Any, gps_track: list) -> dict[str, Any]:
        from src.gui import telemetry_manager as tmod
        base = getattr(tm, "_fit_base", None) or {}
        if base.get("records"):
            recs = [dict(r) for r in base["records"]]
        else:
            gb = getattr(tm, "_gpx_base", None) or {}
            recs = [{"timestamp": p[0], "lat": p[1], "lon": p[2]} for p in gb.get("points", []) if p[1] is not None]
        track = [((d.astimezone(timezone.utc).replace(tzinfo=None) if d.tzinfo else d), la, lo) for d, la, lo in gps_track]
        d = tmod._align_offset_by_track(recs, track)
        diag = dict(tmod.LAST_SMARTSYNC_DIAGNOSTICS)
        if d is None:
            return {"status": "GPS_REJECTED", "smartsync_gps": diag,
                    "message": "Ślad GPS kamery nie pasuje do aktywności (brak fixu lub inny przejazd) — próba IMU."}
        # FIT timestamps + d  <=>  shown at T - sync  =>  sync = -d
        off = -d.total_seconds()
        return {
            "status": "OK", "offset_s": round(off, 3), "method": METHOD_SMARTSYNC_GPS,
            "confidence": 1.0 if diag.get("p90_error_m", 999) <= 100 else 0.7,
            "confidence_level": "high", "events": int(diag.get("matched_points", 0)),
            "smartsync_gps": diag,
            "message": (f"SmartSync GPS: {off:+.2f} s (punkty {diag.get('matched_points')}/{diag.get('total_points')}, "
                        f"mediana błędu {diag.get('median_error_m', 0):.1f} m)."),
        }

    def _combine_clip_results(self, per_clip: list[dict], source: str, gps_note: str) -> dict[str, Any]:
        from statistics import median
        reliable = [(i, r) for i, r in enumerate(per_clip) if r.get("status") == "OK" and r.get("confidence_level") == "high"]
        base_info = {
            "method": METHOD_SMARTSYNC_IMU, "source": source, "per_clip": per_clip,
            "gps_note": gps_note,
        }
        if len(per_clip) == 1:
            r = per_clip[0]
            msg = r.get("message") or str(r.get("status"))
            if gps_note:
                msg = f"{gps_note} {msg}"
            return {**r, **base_info, "message": msg}
        if not reliable:
            best = max(per_clip, key=lambda r: (r.get("confidence") or 0.0))
            return {**base_info, "status": "AMBIGUOUS", "offset_s": best.get("offset_s"),
                    "confidence": best.get("confidence"), "confidence_level": best.get("confidence_level"),
                    "events": sum(int(r.get("events") or 0) for r in per_clip),
                    "message": "Żaden klip nie dał wiarygodnego dopasowania — pokazano propozycję, offset nie został zmieniony."}
        offs = [r["offset_s"] for _, r in reliable]
        glob = float(median(offs))
        clip_offsets: dict[int, float] = {}
        spread = max(offs) - min(offs)
        if spread > CLIP_AGREEMENT_S:
            # Clocks/timestamps differ between clips: keep per-clip corrections
            # only where that clip was itself reliable.
            for i, r in reliable:
                clip_offsets[i] = round(float(r["offset_s"]) - glob, 3)
        unreliable = [i + 1 for i, r in enumerate(per_clip) if (i, r) not in reliable]
        msg = (f"SmartSync IMU: {glob:+.2f} s (wiarygodne klipy {len(reliable)}/{len(per_clip)}"
               + (f", rozrzut {spread:.2f} s — zastosowano korekty per klip" if clip_offsets else "")
               + (f"; klipy {unreliable} bez wiarygodnego dopasowania używają offsetu globalnego" if unreliable else "")
               + ").")
        return {**base_info, "status": "OK", "offset_s": round(glob, 3), "clip_offsets_s": clip_offsets,
                "confidence": round(min(r.get("confidence") or 0 for _, r in reliable), 3),
                "confidence_level": "high", "events": sum(int(r.get("events") or 0) for _, r in reliable),
                "message": msg}

    def _on_sync_auto_finished(self, result: object) -> None:
        if not isinstance(result, dict):
            return
        self._sync_auto_thread = None  # the worker has finished its work
        status = result.get("status")
        msg = result.get("message") or str(status)
        if status == "OK" and result.get("offset_s") is not None:
            self._sync_proposal = None
            state = TelemetrySyncState(
                offset_s=float(result["offset_s"]),
                clip_offsets_s={int(k): float(v) for k, v in (result.get("clip_offsets_s") or {}).items()},
                method=result.get("method") or METHOD_SMARTSYNC_IMU,
                confidence=result.get("confidence"),
                confidence_level=result.get("confidence_level") or "high",
                detail=f"Zdarzenia: {result.get('events', 0)}.",
                smartsync=_json_safe(result),
            )
            self.set_telemetry_sync_state(state, message=f"Zastosowano. {msg}")
            return
        if result.get("offset_s") is not None and status in ("AMBIGUOUS", "INSUFFICIENT_EVENTS"):
            self._sync_proposal = _json_safe(result)
        else:
            self._sync_proposal = None
        self._sync_message = msg
        self._publish_sync_state()


def _json_safe(value: Any) -> Any:
    import math
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if hasattr(value, "item"):
        try:
            return _json_safe(value.item())
        except Exception:
            return str(value)
    return value
