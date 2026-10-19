"""Intel QSV pipeline benchmark on identical material (FFmpeg vs SportCamHUD native).

Variants (all 1800 frames, HEVC Main10 Fast/TU7, VBR 40M/50M, VBV 80 Mbit, init 40 Mbit):
  A        FFmpeg hevc_qsv transcode, QSV decode, no HUD, GOP 60 / no B (matches native GOP)
  A_def    FFmpeg hevc_qsv transcode with FFmpeg GOP defaults (reference only)
  B        SportCamHUD native, layout with every indicator disabled (no HUD)
  B0       SportCamHUD native, TELEM_INTEL_PACKAGE_MODE=VIDEO_ONLY (no HUD workers/upload)
  C        SportCamHUD native, full HUD layout
  D        SportCamHUD FFmpeg QSV path, layout with every indicator disabled

Rendering is not modified; this only drives the canonical harness / ffmpeg and samples
system counters (GPU engines, CPU, thermal zone, battery discharge rate).
"""
import argparse
import ctypes as c
import ctypes.wintypes as w
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import threading
import time

import psutil

ROOT = Path(__file__).resolve().parents[1]
OUT_ROOT = ROOT / "Raporty/intel_qsv_pipeline_20261019"
VIDEO = r"C:\GoPro\2026-10-16\GX010381.MP4"
# Pairing taken from the user's own project file C:\GoPro\GX010381.toproj (not inferred).
FIT = r"C:\GoPro\2026-10-16\2026-10-16_13-06-05.fit"
FULL_LAYOUT = ROOT / "Raporty/intel_vbr_qp_20261017/layout.json"
FFMPEG = ROOT / "runtime/common/ffmpeg/ffmpeg.exe"
FRAMES = 1800


class _FmtValue(c.Structure):
    _fields_ = [("status", w.DWORD), ("pad", w.DWORD), ("value", c.c_double)]


class _Item(c.Structure):
    _fields_ = [("name", w.LPWSTR), ("value", _FmtValue)]


class SystemSampler:
    """PDH (English names) sampler: GPU engines system-wide, CPU, thermal zones."""

    def __init__(self):
        self.pdh = c.WinDLL("pdh")
        self.pdh.PdhOpenQueryW.argtypes = [w.LPCWSTR, c.c_size_t, c.POINTER(c.c_void_p)]
        self.pdh.PdhAddEnglishCounterW.argtypes = [c.c_void_p, w.LPCWSTR, c.c_size_t, c.POINTER(c.c_void_p)]
        self.pdh.PdhCollectQueryData.argtypes = [c.c_void_p]
        self.pdh.PdhGetFormattedCounterArrayW.argtypes = [c.c_void_p, w.DWORD, c.POINTER(w.DWORD), c.POINTER(w.DWORD), c.c_void_p]
        self.query = c.c_void_p()
        assert self.pdh.PdhOpenQueryW(None, 0, c.byref(self.query)) == 0
        self.counters = {}
        for key, path in (("gpu", r"\GPU Engine(*)\Utilization Percentage"),
                          ("cpu_perf", r"\Processor Information(_Total)\% Processor Performance"),
                          ("cpu_freq", r"\Processor Information(_Total)\Processor Frequency"),
                          ("cpu_time", r"\Processor Information(_Total)\% Processor Time"),
                          ("thermal", r"\Thermal Zone Information(*)\Temperature")):
            h = c.c_void_p()
            if self.pdh.PdhAddEnglishCounterW(self.query, path, 0, c.byref(h)) == 0:
                self.counters[key] = h
        self.pdh.PdhCollectQueryData(self.query)

    def _array(self, h):
        size, count = w.DWORD(), w.DWORD()
        self.pdh.PdhGetFormattedCounterArrayW(h, 0x8200, c.byref(size), c.byref(count), None)
        if not size.value:
            return []
        buf = c.create_string_buffer(size.value)
        if self.pdh.PdhGetFormattedCounterArrayW(h, 0x8200, c.byref(size), c.byref(count), buf):
            return []
        items = c.cast(buf, c.POINTER(_Item))
        return [(items[i].name or "", items[i].value.value) for i in range(count.value)
                if items[i].value.status in (0, 1)]

    def sample(self):
        self.pdh.PdhCollectQueryData(self.query)
        out = {}
        if "gpu" in self.counters:
            engines = {}
            for name, value in self._array(self.counters["gpu"]):
                m = re.search(r"(luid_\w+?_phys_\d+)_eng_(\d+)_engtype_(\w*)$", name)
                if not m or not m[3]:
                    continue
                key = f"{m[3]}_eng{m[2]}"
                engines[key] = engines.get(key, 0.0) + value
            # Only the adapter carrying video engines is the Intel iGPU.
            out["gpu_engines"] = {k: min(100.0, v) for k, v in engines.items()}
        for key in ("cpu_perf", "cpu_freq", "cpu_time"):
            if key in self.counters:
                vals = self._array(self.counters[key])
                out[key] = vals[0][1] if vals else None
        if "thermal" in self.counters:
            out["thermal_c"] = {n: round(v - 273.15, 1) for n, v in self._array(self.counters["thermal"]) if v > 0}
        return out


def _battery_loop(path: Path, stop: threading.Event):
    # One long-lived PowerShell: DischargeRate (mW) + PowerOnline once per second.
    script = ("while($true){$b=Get-CimInstance -Namespace root\\wmi -ClassName BatteryStatus;"
              "\"$([DateTime]::UtcNow.ToString('o'));$($b.DischargeRate);$($b.ChargeRate);$($b.PowerOnline)\";"
              "Start-Sleep -Milliseconds 1000}")
    with path.open("w", encoding="utf-8") as f:
        p = subprocess.Popen(["powershell", "-NoProfile", "-Command", script], stdout=f, stderr=subprocess.DEVNULL,
                             creationflags=0x08000000)
        stop.wait()
        p.kill()


def _power_online():
    class SPS(c.Structure):
        _fields_ = [("ACLineStatus", c.c_byte), ("BatteryFlag", c.c_byte), ("BatteryLifePercent", c.c_byte),
                    ("SystemStatusFlag", c.c_byte), ("BatteryLifeTime", w.DWORD), ("BatteryFullLifeTime", w.DWORD)]
    s = SPS()
    c.windll.kernel32.GetSystemPowerStatus(c.byref(s))
    return {"ac_line_status": s.ACLineStatus, "battery_percent": s.BatteryLifePercent}


def _empty_layout(out_dir: Path) -> Path:
    data = json.loads(FULL_LAYOUT.read_text(encoding="utf-8"))
    for cfg in data.get("indicators", {}).values():
        cfg["enabled"] = False
    path = out_dir / "layout_no_hud.json"
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return path


def _ffmpeg_cmd(variant: str, out_mp4: Path):
    gop = ["-g", "60", "-bf", "0"] if variant == "A" else []
    return [str(FFMPEG), "-nostdin", "-y", "-hide_banner", "-benchmark",
            "-hwaccel", "qsv", "-hwaccel_output_format", "qsv", "-noautorotate",
            "-i", VIDEO, "-map", "0:v:0", "-map", "0:a:0", "-frames:v", str(FRAMES),
            "-c:v", "hevc_qsv", "-preset", "veryfast", "-strict", "strict", "-async_depth", "4",
            "-b:v", "40000000", "-maxrate", "50000000", "-bufsize", "80000000", "-rc_init_occupancy", "40000000",
            "-look_ahead", "0", "-profile:v", "main10", *gop,
            "-color_primaries", "bt2020", "-color_trc", "arib-std-b67", "-colorspace", "bt2020nc",
            "-c:a", "copy", str(out_mp4), "-v", "verbose"]


def _harness_cmd(variant: str, out_dir: Path, layout: Path):
    path = "ffmpeg" if variant == "D" else "native"
    return [sys.executable, str(ROOT / "SportCamHUD.py"), "--test-intel-export",
            "--intel-path", path, "--codec", "hevc", "--profile", "fast",
            "--frames", str(FRAMES), "--bitrate", "40M", "--video", VIDEO, "--fit", FIT,
            "--layout", str(layout), "--watchdog-seconds", "300",
            "--output", str(out_dir / "output.mp4"), "--result-json", str(out_dir / "harness.json")]


def _parse_native_log(text: str) -> dict:
    res = {}
    for key, pat in {
        "render_fps": r"RENDER FPS:\s+([\d.]+)", "user_effective_fps": r"USER EFFECTIVE FPS:\s+([\d.]+)",
        "total_wall_s": r"Total Wall Time:\s+([\d.]+)", "frame_render_wall_s": r"Frame Render Wall Time:\s+([\d.]+)",
        "finalization_s": r"Finalization Wall Time:\s+([\d.]+)", "first_frame_latency_s": r"First Frame Latency:\s+([\d.]+)",
        "hud_wait_ms": r"Avg HUD Wait Time:\s+([\d.]+)", "native_step_ms": r"Avg Native Step Time:\s+([\d.]+)",
        "demux_ms": r"Demux Time:\s+([\d.]+)", "decode_ms": r"Decode Time \(Producer\):\s+([\d.]+)",
        "queue_wait_ms": r"Queue Wait \(Consumer\):\s+([\d.]+)", "hud_upload_ms": r"HUD Upload Time:\s+([\d.]+)",
        "hud_dirty_mb": r"HUD Upload Dirty Bytes:\s+([\d.]+)", "blt_ms": r"VideoProcessorBlt Time:\s+([\d.]+)",
        "dma_copy_ms": r"GPU DMA Copy Time:\s+([\d.]+)", "submit_ms": r"Encode Submit Time:\s+([\d.]+)",
        "sync_ms": r"Encode Sync Time:\s+([\d.]+)", "max_pending": r"Max Pending Encode Surfaces:\s*(\d+)",
        "slot_wait_ms": r"Encoder Slot Wait:\s+([\d.]+)", "surface_acquire_ms": r"Encoder Surface Acquire:\s+([\d.]+)",
        "bitstream_write_ms": r"Bitstream Write:\s+([\d.]+)",
    }.items():
        m = re.search(pat, text)
        if m:
            res[key] = float(m[1])
    for line in re.findall(r"\[(?:DIRECT|INTEL STAGE)[^\]]*\][^\n]+", text):
        pass
    prog = [(int(a), float(b)) for a, b in re.findall(r"\[DIRECT PROGRESS\] frame=(\d+)/\d+ fps=[\d.]+ elapsed=([\d.]+)s", text)]
    p500 = next((t for f, t in prog if f == 500), None)
    p1500 = next((t for f, t in prog if f == 1500), None)
    if p500 is not None and p1500 is not None and p1500 > p500:
        res["steady_500_1500_fps"] = 1000.0 / (p1500 - p500)
    for k in ("VBR ACCEPTED", "ENCODER TEX CONTRACT", "DIRECT_VP_SURFACE", "DECODER CONTRACT", "PIPELINE STAGE"):
        m = re.search(r"[^\n]*" + re.escape(k) + r"[^\n]*", text)
        if m:
            res.setdefault("lines", {})[k] = m[0].strip()
    return res


def _parse_ffmpeg_log(text: str, wall: float) -> dict:
    res = {"wall_s": wall, "fps_wall": FRAMES / wall}
    m = re.findall(r"frame=\s*(\d+).*?fps=\s*([\d.]+)", text)
    if m:
        res["ffmpeg_last_fps"] = float(m[-1][1])
    m = re.search(r"bench: utime=([\d.]+)s stime=([\d.]+)s rtime=([\d.]+)s", text)
    if m:
        res["bench_utime_s"], res["bench_stime_s"], res["bench_rtime_s"] = map(float, m.groups())
        res["fps_rtime"] = FRAMES / float(m[3])
    params = [l.strip() for l in text.splitlines() if re.search(
        r"TargetUsage|RateControlMethod|GopPicSize|GopRefDist|BufferSizeInKB|InitialDelayInKB|MaxKbps|TargetKbps|"
        r"LowPower|NalHrdConformance|AsyncDepth|IdrInterval|NumRefFrame|BitDepth|FourCC|profile|Using.*impl|Initialized an internal", l)]
    res["accepted_param_lines"] = params[:80]
    return res


SUFFIX_ENV = {"ZC": {"TELEM_INTEL_VP_ZERO_COPY": "1"}, "TR": {"TELEM_HUD_STARTUP_TRACE": "1"}, "NOBLOB": {"TELEM_INTEL_HUD_INIT_BLOB": "0"},
              "SKIP": {"TELEM_INTEL_DIAG_SKIP_VP_COPY": "1"}}
CANDIDATE_DLL = None


def run(variant: str, rep: int, settle_s: float, tag: str = "") -> dict:
    out = OUT_ROOT / f"{tag}{variant}_r{rep}"
    full_variant = variant
    parts = variant.split("_")
    extra_env = {}
    while len(parts) > 1 and parts[-1] in SUFFIX_ENV:
        extra_env.update(SUFFIX_ENV[parts.pop()])
    variant = "_".join(parts)
    out.mkdir(parents=True, exist_ok=False)
    if settle_s:
        time.sleep(settle_s)
    env = os.environ.copy()
    for key in list(env):
        if key.startswith("TELEM_INTEL_") and key not in ("TELEM_INTEL_NATIVE_DLL",):
            env.pop(key)
    env.pop("TELEM_PIPELINE_AUDIT", None)
    env.update(QT_QPA_PLATFORM="offscreen", APPDATA=str(ROOT / "scratch/qsvbench-profile"),
               LOCALAPPDATA=str(ROOT / "scratch/qsvbench-local"))
    env.update(extra_env)
    if CANDIDATE_DLL and variant not in ("A", "A_def") and (extra_env or tag == "cand_"):
        env["TELEM_INTEL_NATIVE_DLL"] = str(CANDIDATE_DLL)
    native_dll = Path(env.get("TELEM_INTEL_NATIVE_DLL") or ROOT / "runtime/intel/bin/telem_intel_native.dll")
    layout = FULL_LAYOUT
    if variant in ("B", "D"):
        layout = _empty_layout(out)
    if variant == "B0":
        env["TELEM_INTEL_PACKAGE_MODE"] = "VIDEO_ONLY"
    if variant in ("A", "A_def"):
        cmd = _ffmpeg_cmd(variant, out / "output.mp4")
    else:
        cmd = _harness_cmd(variant, out, layout)

    sampler = SystemSampler()
    stop = threading.Event()
    bat_path = out / "battery.csv"
    bat_thread = threading.Thread(target=_battery_loop, args=(bat_path, stop), daemon=True)
    bat_thread.start()
    samples = []
    power_before = _power_online()
    started = time.perf_counter()
    with (out / "export.log").open("w", encoding="utf-8") as log:
        proc = subprocess.Popen(cmd, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
        known = {}
        while proc.poll() is None:
            if time.perf_counter() - started > 420:
                proc.kill()
                raise TimeoutError("benchmark exceeded watchdog")
            try:
                procs = [psutil.Process(proc.pid)] + psutil.Process(proc.pid).children(recursive=True)
                cpu = 0.0
                for p in procs:
                    known.setdefault(p.pid, p)
                    cpu += known[p.pid].cpu_percent()
            except psutil.Error:
                cpu = None
            s = sampler.sample()
            s["wall_s"] = time.perf_counter() - started
            s["tree_cpu_percent_machine"] = cpu / (psutil.cpu_count() or 1) if cpu is not None else None
            samples.append(s)
            time.sleep(0.5)
    wall = time.perf_counter() - started
    stop.set()
    bat_thread.join(timeout=5)
    text = (out / "export.log").read_text(encoding="utf-8", errors="replace")
    summary = {"variant": full_variant, "extra_env": extra_env, "rep": rep, "command": cmd, "exit_code": proc.returncode,
               "process_wall_s": wall, "power_before": power_before, "power_after": _power_online(),
               "head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
               "layout_sha256": hashlib.sha256(layout.read_bytes()).hexdigest()}
    if variant in ("A", "A_def"):
        summary["ffmpeg"] = _parse_ffmpeg_log(text, wall)
        summary["success"] = proc.returncode == 0
    else:
        summary["dll_sha256"] = hashlib.sha256(native_dll.read_bytes()).hexdigest()
        hj = out / "harness.json"
        harness = json.loads(hj.read_text(encoding="utf-8")) if hj.exists() else {}
        summary["harness"] = {k: v for k, v in harness.items() if k not in ("validation",)}
        summary["harness_valid"] = harness.get("validation", {}).get("valid")
        summary["native"] = _parse_native_log(text)
        summary["success"] = proc.returncode == 0 and bool(harness.get("success"))
    # Aggregate counters over the active encode window (drop first/last 3 s).
    active = [s for s in samples if 3.0 < s["wall_s"] < wall - 3.0] or samples
    agg = {}
    for key in ("cpu_perf", "cpu_freq", "cpu_time", "tree_cpu_percent_machine"):
        vals = [s[key] for s in active if s.get(key) is not None]
        agg[key] = sum(vals) / len(vals) if vals else None
    eng = {}
    for s in active:
        for k, v in s.get("gpu_engines", {}).items():
            eng.setdefault(k, []).append(v)
    agg["gpu_engines_mean"] = {k: round(sum(v) / len(v), 1) for k, v in eng.items()}
    agg["gpu_engines_p90"] = {k: round(sorted(v)[int(len(v) * 0.9) - 1], 1) for k, v in eng.items() if v}
    th = [max(s["thermal_c"].values()) for s in active if s.get("thermal_c")]
    agg["thermal_max_c"] = max(th) if th else None
    agg["thermal_mean_c"] = sum(th) / len(th) if th else None
    bat = []
    for line in bat_path.read_text(encoding="utf-8", errors="replace").splitlines():
        parts = line.strip().split(";")
        if len(parts) == 4 and parts[1].isdigit():
            bat.append((int(parts[1]), int(parts[2] or 0), parts[3]))
    agg["battery_discharge_mw_mean"] = sum(b[0] for b in bat) / len(bat) if bat else None
    agg["battery_discharge_mw_max"] = max(b[0] for b in bat) if bat else None
    agg["power_online_values"] = sorted({b[2] for b in bat})
    summary["counters"] = agg
    (out / "samples.json").write_text(json.dumps(samples), encoding="utf-8")
    (out / "measurement.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    short = {"variant": full_variant, "rep": rep, "dll": summary.get("dll_sha256", "")[:8], "success": summary["success"], "wall": round(wall, 2)}
    if "native" in summary:
        n = summary["native"]
        short.update({k: n.get(k) for k in ("render_fps", "steady_500_1500_fps", "user_effective_fps",
                                            "native_step_ms", "sync_ms", "hud_upload_ms", "blt_ms", "dma_copy_ms",
                                            "slot_wait_ms", "hud_wait_ms", "first_frame_latency_s")})
    else:
        short.update({k: summary["ffmpeg"].get(k) for k in ("fps_rtime", "fps_wall")})
    short.update({"gpu": agg["gpu_engines_mean"], "cpu_freq": agg["cpu_freq"], "temp": agg["thermal_max_c"],
                  "discharge_mw": agg["battery_discharge_mw_mean"], "ac": summary["power_before"]["ac_line_status"]})
    print(json.dumps(short), flush=True)
    return summary


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--variants", default="A,B,C")
    ap.add_argument("--reps", type=int, default=3)
    ap.add_argument("--first-rep", type=int, default=1)
    ap.add_argument("--settle", type=float, default=20.0, help="idle seconds before each run (thermal settle)")
    ap.add_argument("--warmup", action="store_true", help="run one discarded C warm-up first")
    ap.add_argument("--candidate-dll", type=Path, help="DLL used for _ZC/_SKIP variants")
    ap.add_argument("--all-candidate", action="store_true", help="use candidate DLL for every native variant")
    args = ap.parse_args()
    global CANDIDATE_DLL
    CANDIDATE_DLL = args.candidate_dll.resolve() if args.candidate_dll else None
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    variants = [v.strip() for v in args.variants.split(",") if v.strip()]
    if args.warmup:
        run(variants[0], 0, 0, tag="warmup_")
    # Interleave variants so slow drifts (thermal, battery) affect every variant alike.
    for rep in range(args.first_rep, args.first_rep + args.reps):
        for v in variants:
            run(v, rep, args.settle, tag="cand_" if args.all_candidate else "")


if __name__ == "__main__":
    main()
