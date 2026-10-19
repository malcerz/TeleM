"""Additional queue/error/audit cases through the canonical Intel harness."""
from pathlib import Path
import json
import os
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def main():
    out = ROOT / "Raporty/intel_vbr_qp_20261017"
    cases = [("queue_hevc_final", "native", 30, ["--mode", "queue"]),
             ("native_init_fallback_final", "native", 30, ["--codec", "h264", "--fail-native-init"]),
             ("executor_error_final", "ffmpeg", 30, ["--codec", "h264", "--fail-executor-init"]),
             ("ffmpeg_hevc_pipeline_audit", "ffmpeg", 120, [])]
    results = []
    for name, backend, frames, extra in cases:
        env = os.environ.copy()
        env["QT_QPA_PLATFORM"] = "offscreen"
        for key in ("TELEM_INTEL_TARGET_USAGE", "TELEM_INTEL_QUANT_TELEMETRY", "TELEM_INTEL_QP_TRACE"):
            env.pop(key, None)
        if name.endswith("audit"):
            env["TELEM_PIPELINE_AUDIT"] = "1"
            env["TELEM_PIPELINE_AUDIT_PATH"] = str(out / "ffmpeg_hevc_pipeline_audit.json")
        cmd = [sys.executable, str(ROOT / "SportCamHUD.py"), "--test-intel-export", "--intel-path", backend,
            "--codec", "hevc", "--profile", "balanced", "--frames", str(frames), "--bitrate", "40M",
            "--video", r"C:\GoPro\GX010378.MP4", "--fit", r"C:\GoPro\2026-10-15_15-03-50.fit",
            "--layout", str(out / "layout.json"), "--watchdog-seconds", "300", "--output", str(out / (name + ".mp4")),
            "--result-json", str(out / (name + "_result.json"))] + extra
        print("START", name, flush=True)
        result_path = out / (name + "_result.json")
        if result_path.exists(): result_path.unlink()
        with (out / (name + ".log")).open("w", encoding="utf-8") as log:
            subprocess.run(cmd, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT, timeout=330, check=True)
        item = json.loads((out / (name + "_result.json")).read_text(encoding="utf-8"))
        if name == "executor_error_final":
            assert not item["success"]
            assert "HARNESS_EXECUTOR_INIT_FAILURE" in (out / (name + ".log")).read_text(encoding="utf-8")
            assert not item["ffmpeg_children_after_error"]
        else:
            assert item["success"] and item["validation"]["valid"]
        if name == "queue_hevc_final":
            assert item["stats"]["quant_samples"] == 0 and item["stats"]["quant_avg"] is None
            assert item["stats"]["quant_reason"]
        results.append(dict(name=name, passed=True, elapsed_s=item["elapsed_s"], success=item["success"]))
        (out / "regression_summary.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
        print("PASS", name, flush=True)
    # Reuse the isolated Portable test copy; never modify the user's installation.
    import shutil
    portable = ROOT / "scratch/intel_portable_validation"
    if not (portable / "python/python.exe").exists():
        raise RuntimeError("Isolated Portable runtime unavailable")
    files = ["src/ffmpeg/intel_config.py", "src/ffmpeg/intel_native_exporter.py", "src/ffmpeg/intel_telemetry.py",
             "src/ffmpeg/command_builder.py", "src/ffmpeg/streaming.py", "src/gui/qt/application.py",
             "src/gui/qt/_mixins/render_mixin.py", "runtime/intel/bin/telem_intel_native.dll"]
    for relative in files:
        shutil.copy2(ROOT / relative, portable / relative)
    for codec in ("h264", "hevc"):
        name = "portable_vbr_" + codec
        env = os.environ.copy(); env["QT_QPA_PLATFORM"] = "offscreen"
        env["TELEM_INTEL_NATIVE_DLL"] = str(portable / "runtime/intel/bin/telem_intel_native.dll")
        for key in ("TELEM_INTEL_TARGET_USAGE", "TELEM_PIPELINE_AUDIT", "TELEM_INTEL_QP_TRACE"):
            env.pop(key, None)
        result_path = out / (name + "_result.json")
        if result_path.exists(): result_path.unlink()
        cmd = [str(portable / "python/python.exe"), "-s", "-E", str(portable / "SportCamHUD.py"),
               "--test-intel-export", "--intel-path", "native", "--codec", codec, "--profile", "balanced",
               "--frames", "30", "--bitrate", "40M", "--video", r"C:\GoPro\GX010378.MP4",
               "--fit", r"C:\GoPro\2026-10-15_15-03-50.fit", "--layout", str(out / "layout.json"),
               "--watchdog-seconds", "180", "--output", str(out / (name + ".mp4")), "--result-json", str(result_path)]
        print("START", name, flush=True)
        with (out / (name + ".log")).open("w", encoding="utf-8") as log:
            subprocess.run(cmd, cwd=portable, env=env, stdout=log, stderr=subprocess.STDOUT, timeout=210, check=True)
        item = json.loads(result_path.read_text(encoding="utf-8"))
        assert item["success"] and item["stats"]["encoder_accepted"]["target_usage"] == 4
        if codec == "hevc": assert item["stats"]["quant_avg"] is None
        results.append(dict(name=name, passed=True, elapsed_s=item["elapsed_s"], success=True))
        (out / "regression_summary.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
        print("PASS", name, flush=True)


if __name__ == "__main__":
    main()
