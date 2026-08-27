"""ETAP 2D validation matrix for AFTER-MAP GPU gauge production enable.

Cases (run individually; GPU exports are serial):
  phase 1 (before default flip):
    A_supported     stock v10 preset, AMD_AFTER_MAP_GAUGE_GPU=1
                    -> expect mode=AUTO, oracle missed=0, region frames > 0
    B_rot90         v10 copy with fit_enhanced_speed_text.rotation=90
                    -> AUTO selected but per-frame unsupported
                    -> epoch label AUTO_FALLBACK_FULLTILE, FULL-TILE GPU
                       uploads only, gauge still present on canvas
    C_compass       fit_enhanced_speed_text.gauge_style=compass (+heading)
                    -> renderer reports supported=False -> same safe
                       AUTO_FALLBACK_FULLTILE degradation, never CPU
    preflip_on      120f GUI-like smoke with explicit flag ON + HUD dumps +
                    HTTP/tile-miss counters == 0
  phase 2 (after default flip):
    cpu_off         explicit AMD_AFTER_MAP_GAUGE_GPU=0 -> CPU gauge path
                    (etap2b upload calls == 0), no crash
    fulltile_forced flag ON + AMD_GAUGE_AUTO_REGIONS=0 -> mode=FULL_TILE,
                    region uploads == 0
    zeroenv_default no gauge env at all -> log must say "ON (default)",
                    mode=AUTO, HTTP/tile-miss counters == 0

Usage: python scratch/run_etap2d_matrix.py CASE [CASE ...]
"""
import copy
import io
import json
import os
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

PRESET = ROOT / "presets/cycling_dashboard_v10.json"
VIDEO = ROOT / "Video/GX010115.MP4"
FIT = ROOT / "Video/Jazda_na_rowerze_w_porze_lunchu.fit"
OUT_BASE = ROOT / "scratch/etap2d_test"

FRAMES = {"A_supported": 40, "B_rot90": 40, "C_compass": 40,
          "preflip_on": 120, "cpu_off": 40, "fulltile_forced": 40,
          "zeroenv_default": 120}
DUMP_FRAMES = {"A_supported": "30", "B_rot90": "30", "C_compass": "30",
               "preflip_on": "40,80", "cpu_off": "", "fulltile_forced": "30",
               "zeroenv_default": "60"}
GAUGE_KEY = "fit_enhanced_speed_text"


class _Tee(io.TextIOBase):
    """Forward prints to the real stdout and an in-memory buffer."""

    def __init__(self, original):
        self._original = original
        self.buffer = []

    def write(self, s):
        self._original.write(s)
        self.buffer.append(s)
        return len(s)

    def flush(self):
        self._original.flush()

    def text(self):
        return "".join(self.buffer)


def _base_env(case):
    os.environ["AMD_GPU_MAP_ROTATE"] = "1"
    os.environ["AMD_AFTER_MAP_CHART_GPU"] = "1"
    os.environ["AMD_MAP_PATH"] = "GPU"
    os.environ["AMD_MAP_FILTER"] = "BICUBIC"
    os.environ["AMD_NATIVE_HUD_MODE"] = "GPU_HUD"
    os.environ["AMD_GAUGE_REGION_ORACLE"] = "1"
    for var in ("AMD_GAUGE_DYNAMIC_RECTS", "AMD_GAUGE_AUTO_REGIONS",
                "AMD_GAUGE_FULL_REFRESH_N", "AMD_PROFILING",
                "AMD_NATIVE_DIAGNOSTICS", "AMD_FRAME_TRACE",
                "AMD_CHART_TRACE", "AMD_ETAP2A_COMPOSE_PROBE",
                "AMD_HUD_DUMP_FRAMES"):
        os.environ.pop(var, None)
    if DUMP_FRAMES.get(case):
        os.environ["AMD_HUD_DUMP_FRAMES"] = DUMP_FRAMES[case]
        os.environ["AMD_ETAP2A_COMPOSE_PROBE"] = "cand"
        # Native H_hud_canvas_<f>.png dumps are gated on diagnostics.
        os.environ["AMD_NATIVE_DIAGNOSTICS"] = "1"


def _apply_case_env(case):
    _base_env(case)
    if case in ("A_supported", "preflip_on", "B_rot90", "C_compass"):
        os.environ["AMD_AFTER_MAP_GAUGE_GPU"] = "1"
    elif case == "cpu_off":
        os.environ["AMD_AFTER_MAP_GAUGE_GPU"] = "0"
    elif case == "fulltile_forced":
        os.environ["AMD_AFTER_MAP_GAUGE_GPU"] = "1"
        os.environ["AMD_GAUGE_AUTO_REGIONS"] = "0"
    elif case == "zeroenv_default":
        os.environ.pop("AMD_AFTER_MAP_GAUGE_GPU", None)


def _case_layout(case, layout):
    layout = copy.deepcopy(layout)
    if case == "B_rot90":
        layout["indicators"][GAUGE_KEY]["rotation"] = 90
    elif case == "C_compass":
        cfg = layout["indicators"][GAUGE_KEY]
        cfg["gauge_style"] = "compass"
        cfg["field"] = "heading"
        cfg["source"] = "gpmf"
    return layout

def _dump_tile_has_artifacts(case_dir):
    """Gauge tile on dumped HUD canvas must contain real alpha art.

    Native H_hud_canvas_<f>.png lands in the process CWD (case dir root);
    Python compose-probe gauge_meta_f<f>.json lands under scratch/etap2a_test.
    """
    probe = case_dir / "scratch" / "etap2a_test"
    canvases = sorted(case_dir.glob("H_hud_canvas_*.png"))
    metas = sorted(probe.glob("gauge_meta_f*.json"))
    if not canvases or not metas:
        return False, (f"missing dump artifacts "
                       f"canvases={[p.name for p in canvases]} "
                       f"metas={[p.name for p in metas]}")
    checked = []
    for meta_p in metas:
        fnum = meta_p.stem.split("f")[-1]
        cand_p = case_dir / f"H_hud_canvas_{fnum}.png"
        if not cand_p.exists():
            continue
        meta = json.loads(meta_p.read_text(encoding="utf-8"))
        gx, gy = int(meta["x"]), int(meta["y"])
        gw, gh = int(meta["w"]), int(meta["h"])
        arr = np.asarray(Image.open(str(cand_p)).convert("RGBA"))
        h, w = arr.shape[:2]
        x0, y0 = max(0, gx), max(0, gy)
        x1, y1 = min(w, gx + gw), min(h, gy + gh)
        tile = arr[y0:y1, x0:x1]
        art_px = int(np.count_nonzero(tile[:, :, 3] > 8))
        checked.append({"frame": fnum, "art_pixels": art_px})
        if art_px < 500:
            return False, f"f{fnum}: gauge tile nearly empty ({art_px}px)"
    return True, checked


def run_case(case, telemetry, layout):
    from src.ffmpeg.amd_native_exporter import export_amd_native_d3d11
    from src.moving_map import get_map_tile_stats, reset_map_tile_stats

    frames = FRAMES[case]
    case_dir = OUT_BASE / case
    case_dir.mkdir(parents=True, exist_ok=True)
    (case_dir / "scratch" / "etap2a_test").mkdir(parents=True, exist_ok=True)
    out_mp4 = case_dir / "out.mp4"
    prof_path = Path(str(out_mp4) + ".amd_profile.json")
    for p in (out_mp4, prof_path):
        if p.exists():
            p.unlink()

    _apply_case_env(case)
    exp_layout = _case_layout(case, layout)

    reset_map_tile_stats()
    tee = _Tee(sys.stdout)
    old_cwd = os.getcwd()
    old_stdout = sys.stdout
    sys.stdout = tee
    ok = False
    t0 = time.perf_counter()
    try:
        os.chdir(case_dir)
        ok = export_amd_native_d3d11(
            ffmpeg_exe="ffmpeg",
            input_files=[str(VIDEO)],
            output_file=str(out_mp4),
            duration_s=frames / 59.94005994,
            video_width=3840,
            video_height=2160,
            start_dt_utc=telemetry.start_dt_utc,
            tz_offset_hours=2.0,
            speed_samples=telemetry.speed_samples,
            track_samples=telemetry.track_samples,
            alt_samples=telemetry.alt_samples,
            iso_samples=telemetry.iso_samples,
            exposure_samples=telemetry.exposure_samples,
            temperature_samples=telemetry.temperature_samples,
            font_path="",
            layout=exp_layout,
            field_samples=telemetry.fit_data,
            fit_data=telemetry.fit_data,
            gps_track=telemetry.get_gps_track_for_source("fit"),
            target_fps=59.94005994,
            video_bitrate="40M",
            quality="speed",
        )
    finally:
        os.chdir(old_cwd)
        sys.stdout = old_stdout
    wall = time.perf_counter() - t0
    log_text = tee.text()
    (case_dir / "console.log").write_text(
        log_text, encoding="utf-8", errors="replace")
    net = get_map_tile_stats()

    result = {"case": case, "ok": bool(ok), "frames": frames,
              "wall_s": round(wall, 2),
              "net_requests": net["network_requests"],
              "net_misses": net["network_misses"], "checks": {}}
    c = result["checks"]

    def chk(name, cond, detail=""):
        c[name] = {"pass": bool(cond), "detail": str(detail)[:300]}

    prof = None
    if prof_path.exists():
        prof = json.loads(prof_path.read_text(encoding="utf-8"))
    e2c = (prof or {}).get("etap2c_gauge_regions", {})
    e5l = (prof or {}).get("etap5l", {})

    chk("export_ok", ok)
    chk("profile_json", prof is not None)
    chk("no_cache_miss_log",
        "[MAP CACHE MISS DURING RENDER]" not in log_text)
    chk("net_zero",
        net["network_requests"] == 0 and net["network_misses"] == 0,
        json.dumps(net))
    chk("no_traceback", "Traceback (most recent call last)" not in log_text)
    if case in ("A_supported", "preflip_on", "zeroenv_default"):
        sel = "ON (default;" if case == "zeroenv_default" else "ON (env"
        chk("log_gauge_gpu_on",
            f"AMD_AFTER_MAP_GAUGE_GPU: {sel}" in log_text)
        chk("log_mode_auto",
            "[AMD GAUGE GPU] mode=AUTO rects=-" in log_text)
        chk("mode_auto", e2c.get("mode") == "AUTO", e2c.get("mode"))
        chk("oracle_ran", e2c.get("oracle_frames", 0) > 0,
            e2c.get("oracle_frames"))
        chk("oracle_missed_0",
            e2c.get("missed_dynamic_pixels", -1) == 0,
            e2c.get("missed_dynamic_pixels"))
        chk("region_frames_pos", e2c.get("oracle_region_frames", 0) > 0,
            e2c.get("oracle_region_frames"))
        chk("gpu_uploads",
            e5l.get("etap2b_gauge_upload_calls_total", 0) > 0,
            e5l.get("etap2b_gauge_upload_calls_total"))
        if case in ("preflip_on", "zeroenv_default"):
            chk("log_map_rotate_on", "AMD_GPU_MAP_ROTATE: 1" in log_text)
            chk("log_chart_gpu_on",
                "AMD_AFTER_MAP_CHART_GPU: ON" in log_text)
    elif case in ("B_rot90", "C_compass"):
        kind = "rotation!=0" if case == "B_rot90" else "compass style"
        chk("log_mode_auto_selection",
            "[AMD GAUGE GPU] mode=AUTO rects=-" in log_text)
        chk("log_fallback_epoch",
            "mode=AUTO_FALLBACK_FULLTILE" in log_text,
            f"unsupported ({kind}) -> full-tile epoch label")
        chk("mode_still_auto_selected", e2c.get("mode") == "AUTO",
            e2c.get("mode"))
        chk("no_region_frames", e2c.get("oracle_region_frames", 0) == 0,
            e2c.get("oracle_region_frames"))
        chk("fulltile_uploads",
            e5l.get("etap2b_gauge_full_upload_frames", 0) >= frames - 1,
            e5l.get("etap2b_gauge_full_upload_frames"))
        chk("oracle_missed_0",
            e2c.get("missed_dynamic_pixels", -1) == 0,
            e2c.get("missed_dynamic_pixels"))
        chk("never_cpu",
            e5l.get("etap2b_gauge_upload_calls_total", 0) > 0,
            "GPU tile uploads present -> not CPU-only")
    elif case == "cpu_off":
        chk("log_gauge_off_env",
            "AMD_AFTER_MAP_GAUGE_GPU: OFF (env" in log_text)
        chk("zero_gpu_uploads",
            e5l.get("etap2b_gauge_upload_calls_total", 0) == 0,
            e5l.get("etap2b_gauge_upload_calls_total"))
    elif case == "fulltile_forced":
        chk("log_mode_fulltile",
            "[AMD GAUGE GPU] mode=FULL_TILE rects=-" in log_text)
        chk("mode_fulltile", e2c.get("mode") == "FULL_TILE",
            e2c.get("mode"))
        chk("auto_off_recorded",
            e2c.get("auto_regions_default_on") is False)
        chk("region_zero",
            e5l.get("etap2b_gauge_region_upload_frames", 0) == 0,
            e5l.get("etap2b_gauge_region_upload_frames"))
        chk("full_uploads_pos",
            e5l.get("etap2b_gauge_full_upload_frames", 0) > 0,
            e5l.get("etap2b_gauge_full_upload_frames"))

    if DUMP_FRAMES.get(case):
        art_ok, detail = _dump_tile_has_artifacts(case_dir)
        chk("gauge_visible_in_dump", art_ok, detail)

    passed = all(v["pass"] for v in c.values())
    result["verdict"] = "PASS" if passed else "FAIL"
    print(f"[ETAP2D-MATRIX] {case}: {result['verdict']} "
          f"({sum(1 for v in c.values() if v['pass'])}/{len(c)} checks)")
    for name, v in c.items():
        if not v["pass"]:
            print(f"  FAILED {name}: {v['detail']}")
    return result




def main():
    cases = sys.argv[1:]
    valid = list(FRAMES.keys())
    if not cases or any(c not in valid for c in cases):
        print(f"usage: python scratch/run_etap2d_matrix.py "
              f"[{'|'.join(valid)}] ...")
        return 2
    OUT_BASE.mkdir(parents=True, exist_ok=True)
    for c in cases:
        (OUT_BASE / c).mkdir(parents=True, exist_ok=True)
    with open(PRESET, "r", encoding="utf-8") as fh:
        layout = json.load(fh)
    from src.gui.telemetry_manager import TelemetryDataManager
    telemetry = TelemetryDataManager()
    telemetry.load_gpmf_from_exiftool(VIDEO)
    telemetry.load_fit(VIDEO, telemetry.start_dt_utc, manual_path=FIT)

    results = [run_case(c, telemetry, layout) for c in cases]
    summary_path = OUT_BASE / f"matrix_{int(time.time())}.json"
    summary_path.write_text(json.dumps(results, indent=2), encoding="utf-8")
    verdicts = {r["case"]: r["verdict"] for r in results}
    print(f"[ETAP2D-MATRIX] results saved -> {summary_path}")
    print(f"[ETAP2D-MATRIX] SUMMARY: {verdicts}")
    overall = all(v == "PASS" for v in verdicts.values())
    print("ETAP2D MATRIX:", "PASS" if overall else "FAIL")
    return 0 if overall else 1


if __name__ == "__main__":
    raise SystemExit(main())


