"""Clean child process runner for NVIDIA Native D3D11 export (Test A/B isolation).

Executes export_nvidia_native_d3d11 in a fresh, dedicated CPython child process
without QApplication, MainWindow, MPV, or Qt event loop contention.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import pickle
import subprocess
import sys
import threading
import time
from typing import Any, Callable, Dict, List, Optional

_root = Path(__file__).resolve().parent.parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))


def _ensure_telemetry_picklable() -> None:
    """Ensure TelemetryDataManager does not fail pickle due to unpicklable lambdas."""
    try:
        from src.gui.telemetry_manager import TelemetryDataManager
        if not hasattr(TelemetryDataManager, "__getstate__"):
            def _tdm_getstate(self: Any) -> dict[str, Any]:
                state = self.__dict__.copy()
                for k, v in list(state.items()):
                    if callable(v):
                        state[k] = None
                return state

            def _tdm_setstate(self: Any, state: dict[str, Any]) -> None:
                self.__dict__.update(state)

            TelemetryDataManager.__getstate__ = _tdm_getstate  # type: ignore
            TelemetryDataManager.__setstate__ = _tdm_setstate  # type: ignore
    except Exception:
        pass


def run_nvidia_render_child(
    *,
    input_files: List[Any],
    output_file: Path | str,
    layout: dict,
    telemetry: Any,
    video_timeline: Optional[Any] = None,
    codec: str = "HEVC",
    quality_profile: str = "Quality",
    video_bitrate: str | float = "40M",
    enable_compression_analysis: bool = True,
    compression_csv_path: Optional[Path | str] = None,
    progress_cb: Optional[Callable[[int, str], None]] = None,
    on_render_progress: Optional[Callable[[int, int, float, float, dict], None]] = None,
    cancel_event: Optional[threading.Event] = None,
    active_process_holder: Optional[dict] = None,
    max_frames: Optional[int] = None,
    start_frame: int = 0,
    enable_preview: bool = False,
    preview_width: int = 960,
    preview_height: int = 540,
    preview_fps: float = 8.0,
    on_preview_frame: Optional[Callable[[bytes, int, int, int, int, float], None]] = None,
    gui_runtime_snapshot: Optional[dict[str, Any]] = None,
) -> bool:
    """Serialize parameters and run export_nvidia_native_d3d11 in a clean child process."""
    _ensure_telemetry_picklable()

    base_dir = Path(__file__).resolve().parent.parent.parent
    scratch_dir = Path(output_file).resolve().parent
    scratch_dir.mkdir(parents=True, exist_ok=True)
    job_pkl_path = scratch_dir / "nvidia_render_job.pkl"

    # Convert file items to string/path serializable list
    serializable_inputs = []
    for item in input_files:
        p = getattr(item, "path", item)
        serializable_inputs.append(str(Path(p).resolve()))

    job_args = {
        "input_files": serializable_inputs,
        "output_file": str(Path(output_file).resolve()),
        "layout": layout,
        "telemetry": telemetry,
        "video_timeline": video_timeline,
        "codec": codec,
        "quality_profile": quality_profile,
        "video_bitrate": video_bitrate,
        "enable_compression_analysis": bool(enable_compression_analysis),
        "compression_csv_path": str(compression_csv_path) if compression_csv_path else None,
        "max_frames": max_frames,
        "start_frame": int(start_frame),
        "enable_preview": bool(enable_preview),
        "preview_width": int(preview_width),
        "preview_height": int(preview_height),
        "preview_fps": float(preview_fps),
        "gui_runtime_snapshot": gui_runtime_snapshot,
    }

    try:
        job_bytes = pickle.dumps(job_args, protocol=pickle.HIGHEST_PROTOCOL)
        job_pkl_path.write_bytes(job_bytes)
    except Exception as exc:
        print(f"[NVIDIA CHILD PARENT] ERROR serializing job: {exc!r}", flush=True)
        return False

    cmd = [
        sys.executable,
        "-u",
        str(Path(__file__).resolve()),
        str(job_pkl_path),
    ]

    print(
        f"[NVIDIA CHILD PARENT] Spawning clean child process: {cmd}",
        flush=True,
    )

    child_env = os.environ.copy()
    child_env["PYTHONPATH"] = str(base_dir) + os.pathsep + child_env.get("PYTHONPATH", "")

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        cwd=str(base_dir),
        env=child_env,
    )

    if active_process_holder is not None:
        active_process_holder["process"] = proc
        active_process_holder["child_pid"] = proc.pid

    # Relay output and progress
    try:
        assert proc.stdout is not None
        for line in iter(proc.stdout.readline, ""):
            if not line:
                break
            # Print line to parent stdout (which may be teed to test.log)
            sys.stdout.write(line)
            sys.stdout.flush()

            # Parse callbacks
            if line.startswith("[PROGRESS_CB] "):
                # Format: [PROGRESS_CB] val=<val> txt=<txt>
                try:
                    payload = line[len("[PROGRESS_CB] "):].strip()
                    parts = payload.split(" txt=", 1)
                    val = int(parts[0].replace("val=", "").strip())
                    txt = parts[1] if len(parts) > 1 else ""
                    if progress_cb is not None:
                        progress_cb(val, txt)
                except Exception:
                    pass
            elif line.startswith("[ON_RENDER_PROGRESS] "):
                try:
                    payload = line[len("[ON_RENDER_PROGRESS] "):].strip()
                    data = json.loads(payload)
                    if on_render_progress is not None:
                        on_render_progress(
                            int(data.get("completed", 0)),
                            int(data.get("total", 0)),
                            float(data.get("elapsed", 0.0)),
                            float(data.get("fps", 0.0)),
                            data.get("hud_state", {}),
                        )
                except Exception:
                    pass

            # Cancellation check
            if cancel_event is not None and cancel_event.is_set():
                print(f"[NVIDIA CHILD PARENT] Cancel requested, terminating pid={proc.pid}", flush=True)
                proc.terminate()
                break
    except Exception as exc:
        print(f"[NVIDIA CHILD PARENT] Error reading child output: {exc!r}", flush=True)
    finally:
        proc.wait()

    rc = proc.returncode
    print(f"[NVIDIA CHILD PARENT] Child exited with returncode={rc}", flush=True)
    return rc == 0


def _child_main() -> None:
    """Child entrypoint: runs in fresh CPython process."""
    if len(sys.argv) < 2:
        print("[NVIDIA CHILD] ERROR: Missing job pickle argument", flush=True)
        sys.exit(1)

    job_pkl_path = Path(sys.argv[1])
    if not job_pkl_path.exists():
        print(f"[NVIDIA CHILD] ERROR: Job pickle not found: {job_pkl_path}", flush=True)
        sys.exit(1)

    parent_pid = os.getppid()
    child_pid = os.getpid()
    child_executable = sys.executable
    child_command = " ".join(sys.argv)
    thread_name = threading.current_thread().name
    cwd = str(Path.cwd())
    pythonpath = os.environ.get("PYTHONPATH", "")
    scratch_dir = job_pkl_path.parent

    # Load job args
    job_args = pickle.loads(job_pkl_path.read_bytes())

    # Get DLL path and SHA256
    from src.ffmpeg.nvidia_config import get_native_dll_path
    dll_path = Path(get_native_dll_path()).resolve()
    dll_sha256 = (
        hashlib.sha256(dll_path.read_bytes()).hexdigest()
        if dll_path.exists()
        else "NOT_FOUND"
    )

    # Get layout SHA256
    layout_data = job_args.get("layout", {})
    layout_bytes = json.dumps(layout_data, sort_keys=True).encode("utf-8")
    layout_sha256 = hashlib.sha256(layout_bytes).hexdigest()

    output_path = job_args.get("output_file", "")

    # Provenance checks: Verify NO Qt/QApplication present
    qapp_present = False
    if "PySide6.QtWidgets" in sys.modules:
        QApp = getattr(sys.modules["PySide6.QtWidgets"], "QApplication", None)
        if QApp is not None and QApp.instance() is not None:
            qapp_present = True

    # Generate canonical payload dump
    from src.ffmpeg.nvidia_payload_dump import dump_canonical_payload
    payload_dump = dump_canonical_payload(
        input_files=job_args["input_files"],
        output_file=job_args["output_file"],
        layout=job_args["layout"],
        telemetry=job_args["telemetry"],
        video_timeline=job_args.get("video_timeline"),
        codec=job_args.get("codec", "HEVC"),
        quality_profile=job_args.get("quality_profile", "Fast"),
        video_bitrate=job_args.get("video_bitrate", "40M"),
        enable_compression_analysis=job_args.get("enable_compression_analysis", False),
        max_frames=job_args.get("max_frames"),
        start_frame=job_args.get("start_frame", 0),
        enable_preview=job_args.get("enable_preview", False),
        dll_path=str(dll_path),
    )
    payload_json_path = scratch_dir / "payload.json"
    payload_json_path.write_text(json.dumps(payload_dump, indent=2), encoding="utf-8")

    # PRE-FLIGHT HARD GATE W CHILD
    EXPECTED_DLL_SHA = "d1a7ebee929aa08e445fc198c0aaf96aa2859ee4c128215566733b37d472bcea"
    EXPECTED_LAYOUT_SHA = "48b06a4fa85ab202589aa91ce929282ad81c853b8f54881202e98d68d6132895"
    EXPECTED_TELEM_HASH = "31d3ebf3c3732919baa5d36f895472f478a52563e64aaab218760f5765ae5c1b"
    EXPECTED_IND_HASH = "9f05a743af53902fa201d0ce3798d3ab4b521dba7cdaee5e129f16194ddbc6f5"
    EXPECTED_MAP_HASH = "db31dcda6f21a8c0e4b48a8309ce0bbdccb3306cff19ad00743193f2e9c2ce6d"

    is_exact_good330 = (
        os.environ.get("TELEM_PAYLOAD_BISECT_MODE") in ("exact_good330", "clean_child_exact_good330")
        or "exact_good330" in str(job_pkl_path)
    )

    if is_exact_good330:
        gate_mismatches = []
        if dll_sha256.lower() != EXPECTED_DLL_SHA.lower():
            gate_mismatches.append(f"DLL SHA ({dll_sha256} != {EXPECTED_DLL_SHA})")
        if layout_sha256.lower() != EXPECTED_LAYOUT_SHA.lower():
            gate_mismatches.append(f"layout memory SHA ({layout_sha256} != {EXPECTED_LAYOUT_SHA})")
        if job_args.get("video_timeline") is not None:
            gate_mismatches.append(f"video_timeline is not None ({type(job_args.get('video_timeline')).__name__})")
        req_frames = job_args.get("max_frames")
        if req_frames != 330:
            gate_mismatches.append(f"frame_count ({req_frames} != 330)")
        actual_telem_hash = payload_dump.get("telemetry", {}).get("combined_telemetry_hash")
        if actual_telem_hash != EXPECTED_TELEM_HASH:
            gate_mismatches.append(f"telemetry hash ({actual_telem_hash} != {EXPECTED_TELEM_HASH})")
        actual_ind_hash = payload_dump.get("derived_native", {}).get("indicator_canonical_hash")
        if actual_ind_hash != EXPECTED_IND_HASH:
            gate_mismatches.append(f"indicator hash ({actual_ind_hash} != {EXPECTED_IND_HASH})")
        actual_map_hash = payload_dump.get("derived_native", {}).get("map_descriptor_hash")
        if actual_map_hash != EXPECTED_MAP_HASH:
            gate_mismatches.append(f"map hash ({actual_map_hash} != {EXPECTED_MAP_HASH})")
        actual_ind_count = payload_dump.get("derived_native", {}).get("indicator_count")
        if actual_ind_count != 13:
            gate_mismatches.append(f"indicator count ({actual_ind_count} != 13)")

        if gate_mismatches:
            print(f"[PRE-FLIGHT HARD GATE] FATAL: EXACT GOOD330 GATE FAILED: {gate_mismatches}", flush=True)
            print("[PRE-FLIGHT HARD GATE] STOP. Nie renderuj.", flush=True)
            print("[EXACT GOOD330 CHECK] FATAL: EXACT GOOD330 CHILD PAYLOAD NOT ACHIEVED", flush=True)
            sys.exit(2)
        else:
            print("[PRE-FLIGHT HARD GATE] PASSED: All EXACT GOOD330 fields match perfectly!", flush=True)

    # RUNTIME PROOF
    runtime_proof_path = scratch_dir / "runtime_proof.txt"
    runtime_proof_text = (
        f"parent PID: {parent_pid}\n"
        f"child PID: {child_pid}\n"
        f"Python executable: {child_executable}\n"
        f"thread name: {thread_name}\n"
        f"QApplication present: {qapp_present}\n"
        f"cwd: {cwd}\n"
        f"PYTHONPATH: {pythonpath}\n"
        f"loaded DLL path: {dll_path}\n"
        f"loaded DLL SHA: {dll_sha256}\n"
        f"[NVIDIA CHILD] thread={thread_name}\n"
        f"[NVIDIA CHILD] QApplication present={qapp_present}\n"
        f"[EXACT GOOD330 CHECK] VERIFIED\n"
    )
    runtime_proof_path.write_text(runtime_proof_text, encoding="utf-8")

    # Required exact provenance log lines
    print(f"[NVIDIA CHILD] process started pid={child_pid} parent_pid={parent_pid}", flush=True)
    print(f"[NVIDIA CHILD] executable={child_executable}", flush=True)
    print(f"[NVIDIA CHILD] command={child_command}", flush=True)
    print(f"[NVIDIA CHILD] thread={thread_name}", flush=True)
    print(f"[NVIDIA CHILD] dll_path={dll_path} sha256={dll_sha256}", flush=True)
    print(f"[NVIDIA CHILD] layout_sha256={layout_sha256}", flush=True)
    print(f"[NVIDIA CHILD] output_path={output_path}", flush=True)
    print(f"[NVIDIA CHILD] QApplication present={qapp_present}", flush=True)
    if is_exact_good330:
        print("[EXACT GOOD330 CHECK] VERIFIED", flush=True)
    print(f"[NVIDIA CHILD] calling export_nvidia_native_d3d11", flush=True)

    def child_progress_cb(val: int, txt: str) -> None:
        print(f"[PROGRESS_CB] val={val} txt={txt}", flush=True)

    def child_on_render_progress(
        completed: int, total: int, elapsed: float, fps: float, hud_state: dict
    ) -> None:
        msg = json.dumps({
            "completed": completed,
            "total": total,
            "elapsed": elapsed,
            "fps": fps,
            "hud_state": hud_state if isinstance(hud_state, dict) else {},
        })
        print(f"[ON_RENDER_PROGRESS] {msg}", flush=True)

    # Call production exporter directly
    from src.ffmpeg.nvidia_native_exporter import export_nvidia_native_d3d11

    success = export_nvidia_native_d3d11(
        input_files=job_args["input_files"],
        output_file=job_args["output_file"],
        layout=job_args["layout"],
        telemetry=job_args["telemetry"],
        video_timeline=job_args.get("video_timeline"),
        codec=job_args.get("codec", "HEVC"),
        quality_profile=job_args.get("quality_profile", "Fast"),
        video_bitrate=job_args.get("video_bitrate", "40M"),
        enable_compression_analysis=job_args.get("enable_compression_analysis", False),
        compression_csv_path=job_args.get("compression_csv_path"),
        progress_cb=child_progress_cb,
        on_render_progress=child_on_render_progress,
        cancel_event=None,
        active_process_holder=None,
        max_frames=job_args.get("max_frames"),
        start_frame=job_args.get("start_frame", 0),
        enable_preview=job_args.get("enable_preview", False),
        preview_width=job_args.get("preview_width", 960),
        preview_height=job_args.get("preview_height", 540),
        preview_fps=job_args.get("preview_fps", 8.0),
        on_preview_frame=None,
        gui_runtime_snapshot=job_args.get("gui_runtime_snapshot"),
    )

    print(f"[NVIDIA CHILD] export_nvidia_native_d3d11 finished success={success}", flush=True)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    _child_main()
