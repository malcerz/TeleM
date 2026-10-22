import ctypes as c
import ctypes.wintypes as w
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import threading
import time

ROOT = Path(r"C:\_DEV\SportCamHUD")
OUT_DIR = ROOT / "Raporty/intel_ab_benchmark_60m"
OUT_DIR.mkdir(parents=True, exist_ok=True)
VIDEO = r"C:\GoPro\2026-10-16\GX010381.MP4"
FIT = r"C:\GoPro\2026-10-16\2026-10-16_13-06-05.fit"
FFMPEG = ROOT / "runtime/common/ffmpeg/ffmpeg.exe"
FRAMES = 1000
BITRATE = "60M"

class _FmtValue(c.Structure):
    _fields_ = [("status", w.DWORD), ("pad", w.DWORD), ("value", c.c_double)]

class _Item(c.Structure):
    _fields_ = [("name", w.LPWSTR), ("value", _FmtValue)]

class FullSystemSampler:
    def __init__(self):
        self.pdh = c.WinDLL("pdh")
        self.pdh.PdhOpenQueryW.argtypes = [w.LPCWSTR, c.c_size_t, c.POINTER(c.c_void_p)]
        self.pdh.PdhAddEnglishCounterW.argtypes = [c.c_void_p, w.LPCWSTR, c.c_size_t, c.POINTER(c.c_void_p)]
        self.pdh.PdhCollectQueryData.argtypes = [c.c_void_p]
        self.pdh.PdhGetFormattedCounterArrayW.argtypes = [c.c_void_p, w.DWORD, c.POINTER(w.DWORD), c.POINTER(w.DWORD), c.c_void_p]
        self.query = c.c_void_p()
        assert self.pdh.PdhOpenQueryW(None, 0, c.byref(self.query)) == 0
        self.counters = {}
        for key, path in (
            ("gpu", r"\GPU Engine(*)\Utilization Percentage"),
            ("cpu_perf", r"\Processor Information(_Total)\% Processor Performance"),
            ("cpu_freq", r"\Processor Information(_Total)\Processor Frequency"),
            ("cpu_time", r"\Processor Information(_Total)\% Processor Time"),
            ("perf_limit", r"\Processor Information(_Total)\% Performance Limit"),
            ("limit_flags", r"\Processor Information(_Total)\Performance Limit Flags"),
            ("thermal", r"\Thermal Zone Information(*)\Temperature"),
        ):
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
        return [(items[i].name or "", items[i].value.value) for i in range(count.value) if items[i].value.status in (0, 1)]

    def sample(self):
        self.pdh.PdhCollectQueryData(self.query)
        out = {}
        if "gpu" in self.counters:
            engines = {}
            for name, value in self._array(self.counters["gpu"]):
                m = re.search(r"(luid_\w+?_phys_\d+)_eng_(\d+)_engtype_(\w*)$", name)
                if m and m[3]:
                    key = f"{m[3]}_eng{m[2]}"
                    engines[key] = engines.get(key, 0.0) + value
            out["gpu_engines"] = {k: min(100.0, v) for k, v in engines.items()}
        for key in ("cpu_perf", "cpu_freq", "cpu_time", "perf_limit", "limit_flags"):
            if key in self.counters:
                vals = self._array(self.counters[key])
                out[key] = vals[0][1] if vals else None
        if "thermal" in self.counters:
            out["thermal_c"] = {n: round(v - 273.15, 1) for n, v in self._array(self.counters["thermal"]) if v > 0}
        return out

def get_power_status():
    class SPS(c.Structure):
        _fields_ = [("ACLineStatus", c.c_byte), ("BatteryFlag", c.c_byte), ("BatteryLifePercent", c.c_byte),
                    ("SystemStatusFlag", c.c_byte), ("BatteryLifeTime", w.DWORD), ("BatteryFullLifeTime", w.DWORD)]
    s = SPS()
    c.windll.kernel32.GetSystemPowerStatus(c.byref(s))
    return {"ac_line": s.ACLineStatus, "batt_pct": s.BatteryLifePercent}

def make_no_hud_layout():
    path = OUT_DIR / "layout_no_hud.json"
    data = json.loads((ROOT / "def_layout.json").read_text(encoding="utf-8"))
    for k, v in data.get("indicators", {}).items():
        if isinstance(v, dict):
            v["enabled"] = False
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return path

def parse_log(text: str) -> dict:
    res = {}
    patterns = {
        "render_fps": r"RENDER FPS:\s+([\d.]+)",
        "user_effective_fps": r"USER EFFECTIVE FPS:\s+([\d.]+)",
        "total_wall_s": r"Total Wall Time:\s+([\d.]+)",
        "frame_render_wall_s": r"Frame Render Wall Time:\s+([\d.]+)",
        "finalization_s": r"Finalization Wall Time:\s+([\d.]+)",
        "first_frame_latency_s": r"First Frame Latency:\s+([\d.]+)",
        "sync_ms": r"Encode Sync Time:\s+([\d.]+)",
        "blt_ms": r"VideoProcessorBlt Time:\s+([\d.]+)",
        "dma_copy_ms": r"GPU DMA Copy Time:\s+([\d.]+)",
        "hud_upload_ms": r"HUD Upload Time:\s+([\d.]+)",
        "avg_native_step_ms": r"Avg Native Step Time:\s+([\d.]+)",
        "slot_wait_ms": r"Encoder Slot Wait:\s+([\d.]+)",
        "hud_wait_ms": r"Avg HUD Wait Time:\s+([\d.]+)",
    }
    for k, pat in patterns.items():
        m = re.search(pat, text)
        if m:
            res[k] = float(m[1])
    prog = [(int(a), float(b)) for a, b in re.findall(r"\[DIRECT PROGRESS\] frame=(\d+)/\d+ fps=[\d.]+ elapsed=([\d.]+)s", text)]
    p300 = next((t for f, t in prog if f == 300), None)
    p1000 = next((t for f, t in prog if f == 1000), None)
    if p300 is not None and p1000 is not None and p1000 > p300:
        res["steady_300_1000_fps"] = 700.0 / (p1000 - p300)
    return res

def run_pure_ffmpeg():
    out_mp4 = OUT_DIR / "pure_ffmpeg_60m.mp4"
    log_path = OUT_DIR / "pure_ffmpeg_60m.log"
    cmd = [
        str(FFMPEG), "-nostdin", "-y", "-hide_banner", "-benchmark",
        "-hwaccel", "qsv", "-hwaccel_output_format", "qsv", "-noautorotate",
        "-i", VIDEO, "-map", "0:v:0", "-map", "0:a:0", "-frames:v", str(FRAMES),
        "-c:v", "hevc_qsv", "-preset", "veryfast", "-strict", "strict", "-async_depth", "4",
        "-b:v", "60000000", "-maxrate", "75000000", "-bufsize", "150000000", "-rc_init_occupancy", "60000000",
        "-look_ahead", "0", "-profile:v", "main10", "-g", "60", "-bf", "0",
        "-color_primaries", "bt2020", "-color_trc", "arib-std-b67", "-colorspace", "bt2020nc",
        "-c:a", "copy", str(out_mp4)
    ]
    sampler = FullSystemSampler()
    samples = []
    t0 = time.perf_counter()
    with log_path.open("w", encoding="utf-8") as f:
        proc = subprocess.Popen(cmd, stdout=f, stderr=subprocess.STDOUT)
        while proc.poll() is None:
            samples.append(sampler.sample())
            time.sleep(0.5)
    wall = time.perf_counter() - t0
    txt = log_path.read_text(encoding="utf-8", errors="replace")
    fps = FRAMES / wall
    m = re.search(r"bench: utime=([\d.]+)s stime=([\d.]+)s rtime=([\d.]+)s", txt)
    rtime_fps = FRAMES / float(m[3]) if m else fps
    return {
        "name": "Pure FFmpeg QSV HEVC (60M)",
        "wall_s": round(wall, 2),
        "fps": round(rtime_fps, 2),
        "samples": samples,
        "success": proc.returncode == 0
    }

def run_native_variant(name: str, layout: Path, preview: bool):
    out_mp4 = OUT_DIR / f"{name}.mp4"
    out_json = OUT_DIR / f"{name}.json"
    log_path = OUT_DIR / f"{name}.log"
    cmd = [
        sys.executable, str(ROOT / "SportCamHUD.py"), "--test-intel-export",
        "--intel-path", "native", "--codec", "hevc", "--profile", "fast",
        "--frames", str(FRAMES), "--bitrate", BITRATE, "--video", VIDEO, "--fit", FIT,
        "--layout", str(layout), "--watchdog-seconds", "300",
        "--output", str(out_mp4), "--result-json", str(out_json)
    ]
    if preview:
        cmd.append("--preview-hud")
    env = os.environ.copy()
    env.update(QT_QPA_PLATFORM="offscreen", TELEM_INTEL_HEVC_HW_DECODE="1")
    sampler = FullSystemSampler()
    samples = []
    t0 = time.perf_counter()
    with log_path.open("w", encoding="utf-8") as f:
        proc = subprocess.Popen(cmd, cwd=ROOT, env=env, stdout=f, stderr=subprocess.STDOUT)
        while proc.poll() is None:
            samples.append(sampler.sample())
            time.sleep(0.5)
    wall = time.perf_counter() - t0
    txt = log_path.read_text(encoding="utf-8", errors="replace")
    parsed = parse_log(txt)
    hj = json.loads(out_json.read_text(encoding="utf-8")) if out_json.exists() else {}
    return {
        "name": name,
        "wall_s": round(wall, 2),
        "parsed": parsed,
        "harness": hj,
        "samples": samples,
        "success": proc.returncode == 0 and bool(hj.get("success"))
    }

def aggregate_samples(samples):
    if not samples:
        return {}
    active = samples[2:-2] if len(samples) > 6 else samples
    def _avg(k):
        vals = [s[k] for s in active if s.get(k) is not None]
        return round(sum(vals) / len(vals), 2) if vals else None
    res = {
        "cpu_freq_mhz": _avg("cpu_freq"),
        "cpu_perf_pct": _avg("cpu_perf"),
        "cpu_time_pct": _avg("cpu_time"),
        "perf_limit_pct": _avg("perf_limit"),
        "limit_flags": _avg("limit_flags"),
    }
    th = [max(s["thermal_c"].values()) for s in active if s.get("thermal_c")]
    res["thermal_max_c"] = round(max(th), 1) if th else None
    res["thermal_mean_c"] = round(sum(th) / len(th), 1) if th else None
    eng = {}
    for s in active:
        for k, v in s.get("gpu_engines", {}).items():
            eng.setdefault(k, []).append(v)
    res["gpu_engines_mean"] = {k: round(sum(v)/len(v), 1) for k, v in eng.items() if sum(v) > 0}
    return res

def main():
    print("=== STARTING CONTROLLED INTEL A/B BENCHMARK (60 Mb/s, PROFILE FAST, 1000 FRAMES) ===")
    pwr = get_power_status()
    print(f"System Power Status: AC={pwr['ac_line']} (1=Online), Battery={pwr['batt_pct']}%")

    results = {}

    # Clean leftover partial files
    for p in Path(r"C:\GoPro\TO").glob("*.part*"):
        try:
            p.unlink()
        except Exception:
            pass

    # 1. Pure FFmpeg QSV HEVC (Reference ceiling)
    print("\n--- [TEST 1/4] Pure FFmpeg QSV HEVC (60M, Fast/veryfast) ---")
    time.sleep(3)
    r1 = run_pure_ffmpeg()
    r1["agg"] = aggregate_samples(r1["samples"])
    results["pure_ffmpeg"] = r1
    print(f"-> Result: FPS={r1['fps']}, Wall={r1['wall_s']}s, Temp={r1['agg']['thermal_max_c']}C, Limit%={r1['agg']['perf_limit_pct']}%, LimitFlags={r1['agg']['limit_flags']}")

    # 2. SportCamHUD Native bez HUD
    print("\n--- [TEST 2/4] SportCamHUD Native bez HUD (60M, Fast) ---")
    time.sleep(3)
    no_hud_layout = make_no_hud_layout()
    r2 = run_native_variant("intel_native_no_hud", no_hud_layout, preview=False)
    r2["agg"] = aggregate_samples(r2["samples"])
    results["native_no_hud"] = r2
    p2 = r2.get("parsed", {})
    print(f"-> Result: RenderFPS={p2.get('render_fps')}, SteadyFPS={p2.get('steady_300_1000_fps')}, SyncTime={p2.get('sync_ms')}ms, FFL={p2.get('first_frame_latency_s')}s, Fin={p2.get('finalization_s')}s, Temp={r2['agg']['thermal_max_c']}C")

    # 3. SportCamHUD Native pełny HUD, Preview OFF
    print("\n--- [TEST 3/4] SportCamHUD Native pełny HUD, Preview OFF (60M, Fast) ---")
    time.sleep(3)
    r3 = run_native_variant("intel_native_full_hud_preview_off", ROOT / "def_layout.json", preview=False)
    r3["agg"] = aggregate_samples(r3["samples"])
    results["full_hud_preview_off"] = r3
    p3 = r3.get("parsed", {})
    print(f"-> Result: RenderFPS={p3.get('render_fps')}, SteadyFPS={p3.get('steady_300_1000_fps')}, SyncTime={p3.get('sync_ms')}ms, FFL={p3.get('first_frame_latency_s')}s, Fin={p3.get('finalization_s')}s, Temp={r3['agg']['thermal_max_c']}C")

    # 4. SportCamHUD Native pełny HUD, Preview ON (Nowy GPU tap)
    print("\n--- [TEST 4/4] SportCamHUD Native pełny HUD, Preview ON (60M, Fast) ---")
    time.sleep(3)
    r4 = run_native_variant("intel_native_full_hud_preview_on", ROOT / "def_layout.json", preview=True)
    r4["agg"] = aggregate_samples(r4["samples"])
    results["full_hud_preview_on"] = r4
    p4 = r4.get("parsed", {})
    print(f"-> Result: RenderFPS={p4.get('render_fps')}, SteadyFPS={p4.get('steady_300_1000_fps')}, SyncTime={p4.get('sync_ms')}ms, FFL={p4.get('first_frame_latency_s')}s, Fin={p4.get('finalization_s')}s, Temp={r4['agg']['thermal_max_c']}C")

    # Save summary
    summary_path = OUT_DIR / "intel_ab_benchmark_60m_summary.json"
    clean_results = {}
    for k, v in results.items():
        clean_results[k] = {
            "name": v["name"],
            "wall_s": v["wall_s"],
            "fps": v.get("fps") or v.get("parsed", {}).get("render_fps"),
            "steady_fps": v.get("parsed", {}).get("steady_300_1000_fps"),
            "parsed": v.get("parsed"),
            "agg": v.get("agg"),
            "success": v.get("success")
        }
    summary_path.write_text(json.dumps(clean_results, indent=2), encoding="utf-8")
    print("\n=== BENCHMARK COMPLETE. Summary written to", summary_path, "===")

if __name__ == "__main__":
    main()
