"""ETAP 5V — long soak (spec 12/13/14/15) + pool recreation (spec 6)
+ device recreate (spec 7) + memory growth (spec 9).

No 5-minute source exists (Video/ has only GX020079.mp4, 1131 frames / 37.7s),
so per spec 13 we run 12 FULL exports of the real clip in ONE process.  Each
export = telem_amd_create -> run -> flush -> close (full device lifecycle).

Pool sequence across exports: 8,8,4,8,6,8,8,8,8,8,8,8  (8->8, then 4->8->6->8
recreation, then six more 8s for a 12-cycle soak; >=10 create/destroy cycles).

Per export: wall, frame accounting (decoded/VP/HUD/AMF submitted/AMF output/
muxed == 1131, drops=0), [VP POOL] lifecycle (live=0 after destroy), process
working set (RAM) before/after -> memory growth check.

Corruption (spec 15): blackdetect + freezedetect via ffmpeg on export 12, and
framemd5 of export 12 vs golden pool8 reference (l5v_f1131_p8.mp4).
"""
from __future__ import annotations

import contextlib
import csv
import io
import json
import os
import re
import statistics
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

try:
    import psutil
except Exception:  # pragma: no cover
    psutil = None

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
PY = r"c:/_DEV/TeleM/.venv-1/Scripts/python.exe"
OUT = ROOT / "Raporty" / "AMD_ETAP5G"
FF = r"C:\tools\ffmpeg.exe"

POOL_SEQUENCE = [8, 8, 4, 8, 6, 8, 8, 8, 8, 8, 8, 8]
N_EXPORTS = len(POOL_SEQUENCE)


def _setup_env() -> dict:
    env = dict(os.environ)
    for flag in ("AMD_GAUGE_AB_READBACK", "AMD_MAP_AB_READBACK", "AMD_CHART_AB_READBACK",
                 "AMD_CHART_STATIC_READBACK", "AMD_NATIVE_DIAGNOSTICS", "AMD_NATIVE_PROFILING",
                 "AMD_OVERLAY_PROFILE", "AMD_MAP_STATS", "AMD_TELEMETRY_MODE",
                 "AMD_FRAME_ACCOUNTING", "AMD_AMF_DIAG", "AMD_COMPOSE_5Q",
                 "AMD_NATIVE_FRAME_ACCOUNTING", "AMD_VP_STATE_MODE",
                 "AMD_GPU_TIMESTAMP_PROFILE", "AMD_AMF_MODE", "AMD_AMF_QUERY_MODE",
                 "AMD_VP_POOL_SIZE", "AMD_POOL_LIFECYCLE_STATS", "AMD_CHART_PATH",
                 "AMD_GAUGE_PATH"):
        env.pop(flag, None)
    env["AMD_MAP_PATH"] = "GPU"
    env["AMD_MAP_FILTER"] = "LANCZOS"
    env["AMD_COMPOSE_5Q"] = "OPTIMIZED"
    env["AMD_VP_STATE_MODE"] = "REFERENCE"
    env["AMD_POOL_LIFECYCLE_STATS"] = "1"
    env["AMD_CHART_PATH"] = "GPU_SPLIT"
    env["AMD_GAUGE_PATH"] = "GPU"
    return env


def _ws_bytes() -> int:
    if psutil is not None:
        return psutil.Process().memory_info().rss
    return 0


def main() -> int:
    env = _setup_env()
    os.environ.update(env)

    from src.ffmpeg.streaming import stream_overlay_to_ffmpeg
    from src.gui.layout_manager import resolve_font_path
    from src.gui.telemetry_manager import TelemetryDataManager
    from src.telemetry_extract import (
        ensure_records_list, extract_speed_samples, extract_altitude_samples,
        extract_track_samples, extract_iso_samples, extract_exposure_samples,
        extract_temperature_samples, smooth_speed_samples, interpolate_value,
        load_json_with_fallback,
    )

    records = ensure_records_list(load_json_with_fallback(ROOT / "Video" / "GX020079.json"))
    telemetry = TelemetryDataManager(
        extract_speed_fn=extract_speed_samples,
        extract_altitude_fn=extract_altitude_samples,
        extract_track_fn=extract_track_samples,
        extract_iso_fn=extract_iso_samples,
        extract_exposure_fn=extract_exposure_samples,
        extract_temperature_fn=extract_temperature_samples,
        smooth_fn=smooth_speed_samples,
        interpolate_fn=interpolate_value,
    )
    telemetry.load_gpmf_records(records)
    telemetry.load_fit(ROOT / "Video" / "Morning_Ride.fit")
    telemetry.start_dt_utc = datetime(2026, 8, 5, 4, 28, 11)
    with (ROOT / "def_layout.json").open(encoding="utf-8") as handle:
        layout = json.load(handle)
    speed = smooth_speed_samples(telemetry.speed_samples, "moving_average", 5)
    altitude = smooth_speed_samples(telemetry.alt_samples, "moving_average", 5)
    track = telemetry.track_samples
    video = ROOT / "Video" / "GX020079.mp4"

    ws_before_all = _ws_bytes()
    exports = []
    for idx, pool in enumerate(POOL_SEQUENCE, start=1):
        os.environ["AMD_VP_POOL_SIZE"] = str(pool)
        mp4 = OUT / f"l5v_soak_{idx:02d}.mp4"
        buf = io.StringIO()
        t0 = time.time()
        ws_pre = _ws_bytes()
        try:
            with contextlib.redirect_stdout(buf):
                result = stream_overlay_to_ffmpeg(
                    ffmpeg_exe=FF, input_files=[str(video)], output_file=str(mp4),
                    duration_s=1131 * (1001.0 / 30000.0),
                    start_dt_utc=telemetry.start_dt_utc, tz_offset_hours=2,
                    speed_samples=speed, track_samples=track, alt_samples=altitude,
                    font_path=resolve_font_path("Arial"), layout=layout,
                    field_samples={"speed_samples": speed, "track_samples": track,
                                   "alt_samples": altitude},
                    max_distance_m=track[-1][1] if track else 0,
                    target_fps=30000 / 1001, update_rate_step=1, workers=1,
                    iso_samples=telemetry.iso_samples, exposure_samples=telemetry.exposure_samples,
                    temperature_samples=telemetry.temperature_samples,
                    gpx_speed_samples=telemetry.gpx_speed_samples,
                    gpx_track_samples=telemetry.gpx_track_samples,
                    gpx_alt_samples=telemetry.gpx_alt_samples,
                    gpx_power_samples=telemetry.gpx_power_samples,
                    gpx_atemp_samples=telemetry.gpx_atemp_samples,
                    gpx_hr_samples=telemetry.gpx_hr_samples,
                    gpx_cad_samples=telemetry.gpx_cad_samples,
                    fit_data=telemetry.fit_data,
                    gps_track=telemetry.get_gps_track_for_source(
                        layout.get("indicators", {}).get("track_map", {}).get("source", "fit")),
                    encoder="amd", gpu=0, video_bitrate="40M", render_w=3840, render_h=2160,
                    resolution_name="source", rotation_degrees=180, container_rotation=180,
                    overlay_w=1920, overlay_h=1080,
                )
        except Exception as exc:  # noqa: BLE001
            buf.write(f"\nEXCEPTION: {exc!r}")
            result = -1
        wall = time.time() - t0
        ws_post = _ws_bytes()
        out_txt = buf.getvalue()
        lifecycle = None
        m = re.search(r"\[VP POOL\] lifecycle: ([^\n]+)", out_txt)
        if m:
            lifecycle = m.group(1)
        # native success = profile JSON present and muxed == 1131
        profile = mp4.with_suffix(mp4.suffix + ".amd_profile.json")
        native_ok = profile.exists()
        fa = {}
        amf = {}
        if native_ok:
            d = json.loads(profile.read_text(encoding="utf-8"))
            fa = d.get("frame_accounting", {})
            amf = d.get("amf", {})
        accounting_ok = (native_ok and fa.get("muxed_frames") == 1131
                         and fa.get("amf_submitted") == 1131 and fa.get("amf_output") == 1131
                         and fa.get("vp_processed") == 1131 and fa.get("native_processed") == 1131
                         and amf.get("dropped_submissions") == 0)
        rec = {
            "export": idx, "pool": pool, "wall": wall, "true_fps": d.get("true_fps", 0.0)
            if native_ok else 0.0,
            "ws_pre": ws_pre, "ws_post": ws_post, "ws_delta": ws_post - ws_pre,
            "native_ok": native_ok, "accounting_ok": accounting_ok,
            "muxed": fa.get("muxed_frames", -1), "submitted": fa.get("amf_submitted", -1),
            "output": fa.get("amf_output", -1), "vp": fa.get("vp_processed", -1),
            "dropped": amf.get("dropped_submissions", -1),
            "input_full": amf.get("input_full_count", -1),
            "lifecycle": lifecycle,
            "exceptions": "EXCEPTION" in out_txt,
        }
        exports.append(rec)
        print(f"[soak {idx:02d}] pool={pool} wall={wall:.2f}s "
              f"FPS={rec['true_fps']:.2f} native={native_ok} acct={accounting_ok} "
              f"muxed={rec['muxed']} dropped={rec['dropped']} "
              f"ws={ws_pre/1e6:.1f}->{ws_post/1e6:.1f}MB", flush=True)
        if lifecycle:
            print(f"    lifecycle: {lifecycle}", flush=True)
        if not accounting_ok:
            tail = "\n".join(out_txt.splitlines()[-8:])
            print(f"    ACCOUNTING FAIL tail:\n{tail}", flush=True)

    ws_after_all = _ws_bytes()
    report = {
        "exports": exports,
        "ws_before_all": ws_before_all, "ws_after_all": ws_after_all,
        "ws_growth_all": ws_after_all - ws_before_all,
        "pool_sequence": POOL_SEQUENCE,
    }
    ok_all = all(e["accounting_ok"] and e["native_ok"] and not e["exceptions"] for e in exports)
    # lifecycle live=0 on every export
    live_ok = True
    for e in exports:
        if e["lifecycle"]:
            tm = re.search(r"textures created=\d+ released=\d+ live=(\d+)", e["lifecycle"])
            vm = re.search(r"views created=\d+ released=\d+ live=(\d+)", e["lifecycle"])
            if tm and int(tm.group(1)) != 0:
                live_ok = False
            if vm and int(vm.group(1)) != 0:
                live_ok = False
    report["all_accounting_ok"] = ok_all
    report["lifecycle_live0_all"] = live_ok

    # ── corruption spot check on export 12 ──────────────────────────────
    corrupt = {}
    if Path(f"{OUT / 'l5v_soak_12.mp4'}.amd_profile.json").exists():
        mp4 = OUT / "l5v_soak_12.mp4"
        bd = subprocess.run([FF, "-hide_banner", "-loglevel", "error", "-i", str(mp4),
                             "-vf", "blackdetect=d=0.1:pix_th=0.10", "-an", "-f", "null", "-"],
                            capture_output=True, text=True)
        fd = subprocess.run([FF, "-hide_banner", "-loglevel", "error", "-i", str(mp4),
                             "-vf", "freezedetect=n=-60dB:d=0.5", "-an", "-f", "null", "-"],
                            capture_output=True, text=True)
        black_seg = len(re.findall(r"black_start", bd.stderr))
        frozen_seg = len(re.findall(r"lavfi\.freezedetect\.freeze_start", fd.stderr))
        corrupt["black_segments"] = black_seg
        corrupt["frozen_segments"] = frozen_seg
        # framemd5 vs golden pool8 reference
        ref = OUT / "l5v_f1131_p8.mp4"
        if ref.exists():
            def _hashes(p):
                mf = p.with_suffix(p.suffix + ".md5")
                subprocess.run([FF, "-y", "-hide_banner", "-loglevel", "error", "-i", str(p),
                                "-map", "0:v:0", "-f", "framemd5", str(mf)], check=True)
                return [l.split()[-1] for l in mf.read_text(encoding="utf-8").splitlines()
                        if l and l[0].isdigit()]
            ha, hb = _hashes(mp4), _hashes(ref)
            same = sum(1 for x, y in zip(ha, hb) if x == y)
            corrupt["framemd5_vs_golden_p8"] = {"identical": same, "total": len(hb),
                                                "pass": same == len(ha) == len(hb)}
        report["corruption"] = corrupt
        print(f"\nCorruption soak12: black={black_seg} frozen={frozen_seg} "
              f"framemd5={corrupt.get('framemd5_vs_golden_p8')}", flush=True)

    report["SOAK_PASS"] = ok_all and live_ok and corrupt.get("framemd5_vs_golden_p8", {}).get("pass", False) and corrupt.get("black_segments", 0) == 0
    (OUT / "etap5v_soak.json").write_text(json.dumps(report, indent=2, default=str),
                                          encoding="utf-8")
    print(f"\nSOAK PASS = {report['SOAK_PASS']}  (all acct {ok_all}, live0 {live_ok}, "
          f"ws growth {report['ws_growth_all']/1e6:.1f}MB over {N_EXPORTS} exports)", flush=True)
    print(f"JSON: {OUT / 'etap5v_soak.json'}", flush=True)
    return 0 if report["SOAK_PASS"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
