"""TeleM AMD Render Path Audit - benchmark harness.

AUDIT ONLY - measurement/diagnostic script.  Does not change production
behavior.  Runs the production AMD native D3D11 + AMF exporter across many
configurations (resolution, overlay content, decode/AMF/telemetry/map modes)
and collects the built-in `.amd_profile.json` timings plus a per-case system
resource sampler (CPU / GPU engines / RAM / VRAM).

Outputs (written to Raporty/AMD_RENDER_PATH_AUDIT/):
  audit_summary.json   - per-case aggregate metrics
  audit_summary.csv    - same, as CSV
  audit_system_<case>.csv - sampler samples per case (when sampler enabled)
  <case>.mp4 / <case>.mp4.amd_profile.json

Run e.g.:  python scratch/run_amd_render_path_audit.py --only baseline_720p
           python scratch/run_amd_render_path_audit.py            (all cases)
"""

from __future__ import annotations

import copy
import csv
import json
import os
import subprocess
import sys
import time
import tracemalloc
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.gui.telemetry_manager import TelemetryDataManager
from src.ffmpeg.amd_native_exporter import export_amd_native_d3d11
from src.telemetry_extract import (
    extract_speed_samples, extract_altitude_samples, extract_track_samples,
    extract_iso_samples, extract_exposure_samples, extract_temperature_samples,
    ensure_records_list, extract_gps_track,
    smooth_speed_samples, interpolate_value, get_rotation_from_metadata,
    get_container_rotation, find_metadata_json, load_json_with_fallback,
    smooth_speed_values, extract_accelerometer_samples, extract_gyroscope_samples,
)

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "Raporty" / "AMD_RENDER_PATH_AUDIT"
OUT_DIR.mkdir(parents=True, exist_ok=True)
SCRATCH = ROOT / "scratch"
MASTER_CSV = OUT_DIR / "audit_system_master.csv"
TAG_FILE = OUT_DIR / "current_case.txt"

VIDEO = ROOT / "Video" / "GX010115.MP4"
META = ROOT / "Video" / "GX010115.json"
FIT = ROOT / "Video" / "Jazda_na_rowerze_w_porze_lunchu.fit"
LAYOUT_PATH = ROOT / "presets" / "cycling_dashboard_v10.json"

# Default production env for a clean audit baseline.
_BASE_ENV = {
    "AMD_TELEMETRY_MODE": "PRECOMPUTED",
    "AMD_NATIVE_HUD_MODE": "GPU_HUD",
    "AMD_NATIVE_DECODE_MODE": "GPU_HUD_D3D11VA",
    "AMD_NATIVE_HUD_UPLOAD_MODE": "DIRTY",
    "AMD_MAP_PATH": "GPU",
    "AMD_CHART_PATH": "GPU_SPLIT",
    "AMD_GAUGE_PATH": "GPU",
    "AMD_OVERLAY_PROFILE": "1",
    "AMD_NATIVE_PROFILING": "1",
    "AMD_NATIVE_DIAGNOSTICS": "1",
    "AMD_CPU_GPU_PIPELINE": "SYNC",
}

# Keys to clear so every case starts from a clean env.
_CLEAR_ENV = [
    "AMD_MAP_PATH", "AMD_MAP_FILTER", "AMD_MAP_GPU_PATH", "AMD_CHART_PATH",
    "AMD_GAUGE_PATH", "AMD_TELEMETRY_MODE", "AMD_AMF_MODE", "AMD_AMF_DIAG",
    "AMD_NATIVE_HUD_MODE", "AMD_NATIVE_DECODE_MODE", "AMD_NATIVE_HUD_UPLOAD_MODE",
    "AMD_HUD_BUFFER_MODE", "AMD_NATIVE_DIRTY_MAX_RECTS", "AMD_ABOVE_DIRTY_MODE",
    "AMD_ABOVE_UPLOAD_BUFFER_MODE", "AMD_ABOVE_TEXT_CACHE", "AMD_ABOVE_MULTI_REGION",
    "AMD_CPU_GPU_PIPELINE", "AMD_QUEUE_DEPTH", "AMD_NATIVE_LEGACY_NO_HUD",
    "AMD_OVERLAY_PROFILE", "AMD_NATIVE_PROFILING", "AMD_NATIVE_DIAGNOSTICS",
    "AMD_GPU_TIMESTAMP_PROFILE", "AMD_AUDIT_ALLOCS", "AMD_FRAME_ACCOUNTING",
    "AMD_NATIVE_FRAME_ACCOUNTING", "AMD_NATIVE_DIAGNOSTICS",
    "AMD_FRAME_TRACE", "AMD_CHART_TRACE",
]


def load_telemetry():
    with open(LAYOUT_PATH, "r", encoding="utf-8") as f:
        layout = json.load(f)
    telemetry = TelemetryDataManager(
        extract_speed_fn=extract_speed_samples,
        extract_altitude_fn=extract_altitude_samples,
        extract_track_fn=extract_track_samples,
        extract_iso_fn=extract_iso_samples,
        extract_exposure_fn=extract_exposure_samples,
        extract_temperature_fn=extract_temperature_samples,
        smooth_fn=smooth_speed_samples,
        interpolate_fn=interpolate_value,
        get_rotation_meta_fn=get_rotation_from_metadata,
        get_container_rotation_fn=get_container_rotation,
        find_meta_json_fn=find_metadata_json,
        find_meta_json_write_fn=lambda p: p.with_suffix(".json"),
        load_telemetry_fn=lambda *a: None,
        ensure_records_fn=ensure_records_list,
        load_json_fallback_fn=load_json_with_fallback,
        write_records_fn=lambda p, r: None,
        extract_samples_exiftool_fn=lambda f: [],
        extract_altitude_exiftool_fn=lambda f: [],
        extract_gps_track_fn=extract_gps_track,
        find_gps_anchor_fn=lambda r: None,
        smooth_values_fn=smooth_speed_values,
        extract_accelerometer_fn=extract_accelerometer_samples,
        extract_gyroscope_fn=extract_gyroscope_samples,
    )
    with open(META, "r", encoding="utf-8") as f:
        meta = json.load(f)
    records = ensure_records_list(meta)
    telemetry.load_gpmf_records(records)
    telemetry.load_gps_track(records)
    telemetry.load_fit(VIDEO, telemetry.start_dt_utc, manual_path=FIT)
    return layout, telemetry


def family_subset(layout: dict, forms: set[str] | None, keys: set[str] | None) -> dict:
    """Return a layout with only the indicators whose form/key is in the set."""
    out = copy.deepcopy(layout)
    inds = {}
    for key, cfg in out.get("indicators", {}).items():
        if keys is not None and key not in keys:
            continue
        if forms is not None and cfg.get("form") not in forms:
            continue
        inds[key] = copy.deepcopy(cfg)
        inds[key]["enabled"] = True
    out["indicators"] = inds
    out["custom_texts"] = []
    return out


def empty_layout(layout: dict) -> dict:
    out = copy.deepcopy(layout)
    out["indicators"] = {}
    out["custom_texts"] = []
    return out


def _pct(values, p):
    if not values:
        return 0.0
    x = sorted(values)
    return x[min(len(x) - 1, int(len(x) * p))]


def analyze_profile(profile: dict) -> dict:
    """Extract a flat summary of the most relevant timings/byte counters."""
    timings = profile.get("timings", {})
    keys = [
        "MF ReadSample/decode availability", "Telemetry/frame_data",
        "compose_overlay", "above_compose", "above_bbox_crop",
        "above_region_to_bytes", "above_region_upload", "above_total",
        "map_cpu_upload", "HUD dirty extract", "PIL/buffer preparation",
        "update_hud", "HUD texture upload", "VideoProcessor CPU submit",
        "VideoProcessor GPU completion", "GPU wait/synchronization",
        "AMF submit/backpressure", "AMF QueryOutput", "Packet write",
        "Audio mux", "producer_prepare", "consumer_upload",
        "consumer_native_call", "pipeline_total",
    ]
    tsum = {}
    for k in keys:
        if k in timings:
            v = timings[k]
            tsum[k] = {
                "avg": round(v.get("avg_ms", 0.0), 3),
                "med": round(v.get("median_ms", 0.0), 3),
                "p95": round(v.get("p95_ms", 0.0), 3),
                "p99": round(v.get("p99_ms", 0.0), 3),
            }
    out = {
        "render_fps": profile.get("etap8p_a", {}).get("render_fps"),
        "true_fps": profile.get("true_fps"),
        "mux_wall_ms": profile.get("etap8p_a", {}).get("mux_wall_ms"),
        "video_render_wall_ms": profile.get("etap8p_a", {}).get("video_render_wall_ms"),
        "timings": tsum,
    }
    # upload byte counters
    etap3 = profile.get("etap3", {})
    if etap3:
        out["hud_uploaded_bytes_total"] = etap3.get("native_uploaded_bytes_total")
        out["rects_per_frame_avg"] = (etap3.get("rects_per_frame", {}) or {}).get("avg")
        out["requested_upload_bytes_per_frame_avg"] = (
            etap3.get("requested_upload_bytes_per_frame", {}) or {}
        ).get("avg")
    etap8n = profile.get("etap8n", {})
    if etap8n:
        out["above_regions_per_frame_avg"] = (etap8n.get("regions_per_frame", {}) or {}).get("avg")
        out["above_uploaded_bytes_per_frame_avg"] = (etap8n.get("uploaded_bytes_per_frame", {}) or {}).get("avg")
        out["above_uploaded_pixels_per_frame_avg"] = (etap8n.get("uploaded_pixels_per_frame", {}) or {}).get("avg")
        out["above_scanned_pixels_per_frame_avg"] = (etap8n.get("scanned_pixels_per_frame", {}) or {}).get("avg")
    map_g = profile.get("etap5g", {})
    if map_g:
        out["map_path"] = map_g.get("map_path")
        out["map_gpu_direct_used"] = map_g.get("map_gpu_direct_used")
        out["map_upload_mib_per_frame"] = map_g.get("map_upload_mib_per_frame")
    chart_j = profile.get("etap5j", {})
    if chart_j:
        out["chart_path"] = chart_j.get("chart_path")
    gauge_l = profile.get("etap5l", {})
    if gauge_l:
        out["gauge_path"] = gauge_l.get("gauge_path")
    fa = profile.get("frame_accounting", {})
    if fa:
        out["frame_accounting"] = {
            "decoded": fa.get("decoded_frames"), "processed": fa.get("native_processed"),
            "amf": fa.get("amf_output"), "muxed": fa.get("muxed_frames"),
        }
    out["decoder_output_format"] = profile.get("etap4", {}).get("decoder_output_format")
    out["hardware_accel"] = profile.get("etap4", {}).get("hardware_acceleration_confirmed")
    alloc = profile.get("audit_allocations")
    if alloc:
        out["audit_allocations"] = alloc
    return out


def aggregate_by_tag(csv_path: str) -> dict:
    """Aggregate sampler CSV rows grouped by tag -> avg/med/max per metric."""
    cols = ["cpu_total", "cpu_py_norm", "gpu_3d", "gpu_decode", "gpu_encode",
            "gpu_copy", "ram_used_mb", "ram_avail_mb", "vram_ded_mb", "vram_shared_mb"]
    out: dict[str, dict] = {}
    if not os.path.exists(csv_path):
        return out
    data: dict[str, dict[str, list]] = {}
    with open(csv_path, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            tag = (row.get("tag") or "").strip()
            if not tag:
                continue
            bucket = data.setdefault(tag, {c: [] for c in cols})
            for c in cols:
                v = row.get(c, "")
                if v not in ("", None):
                    try:
                        bucket[c].append(float(v))
                    except ValueError:
                        pass
    for tag, bucket in data.items():
        agg = {}
        for c, vals in bucket.items():
            if not vals:
                agg[c] = None
                continue
            agg[c] = {
                "avg": round(sum(vals) / len(vals), 1),
                "med": round(sorted(vals)[len(vals) // 2], 1),
                "max": round(max(vals), 1),
                "n": len(vals),
            }
        out[tag] = agg
    return out


def summarize_system_csv(csv_path: str, tag: str | None = None) -> dict:
    """Aggregate a sampler CSV into avg/med/max per metric (optionally by tag)."""
    cols = ["cpu_total", "cpu_py_norm", "gpu_3d", "gpu_decode", "gpu_encode",
            "gpu_copy", "ram_used_mb", "ram_avail_mb", "vram_ded_mb", "vram_shared_mb"]
    if not os.path.exists(csv_path):
        return {}
    data = {c: [] for c in cols}
    with open(csv_path, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if tag is not None and row.get("tag") != tag:
                continue
            for c in cols:
                v = row.get(c, "")
                if v not in ("", None):
                    try:
                        data[c].append(float(v))
                    except ValueError:
                        pass
    agg = {}
    for c, vals in data.items():
        if not vals:
            agg[c] = None
            continue
        agg[c] = {
            "avg": round(sum(vals) / len(vals), 1),
            "med": round(sorted(vals)[len(vals) // 2], 1),
            "max": round(max(vals), 1),
        }
    return agg


def run_case(name: str, layout, width: int, height: int, fps: float,
             duration_s: float, env_overrides: dict, sampler: bool,
             telemetry, use_tracemalloc: bool = False, extra_kwargs: dict | None = None):
    # reset env
    for k in _CLEAR_ENV:
        os.environ.pop(k, None)
    env = dict(_BASE_ENV)
    env.update(env_overrides or {})
    os.environ.update(env)

    out_mp4 = OUT_DIR / f"{name}.mp4"
    if out_mp4.exists():
        out_mp4.unlink()
    prof = Path(str(out_mp4) + ".amd_profile.json")
    if prof.exists():
        prof.unlink()
    # tag the continuous master sampler with the active case (or idle)
    try:
        TAG_FILE.write_text(name if sampler else "idle", encoding="utf-8")
    except Exception:
        pass
    if use_tracemalloc:
        tracemalloc.start()
        tracemalloc.reset_peak()

    t0 = time.perf_counter()
    ok = False
    try:
        ok = export_amd_native_d3d11(
            ffmpeg_exe="ffmpeg",
            input_files=[str(VIDEO)],
            output_file=str(out_mp4),
            duration_s=duration_s,
            video_width=width,
            video_height=height,
            start_dt_utc=telemetry.start_dt_utc,
            tz_offset_hours=2.0,
            speed_samples=telemetry.speed_samples,
            track_samples=telemetry.track_samples,
            alt_samples=telemetry.alt_samples,
            iso_samples=telemetry.iso_samples,
            exposure_samples=telemetry.exposure_samples,
            temperature_samples=telemetry.temperature_samples,
            font_path="",
            layout=layout,
            field_samples=telemetry.fit_data,
            fit_data=telemetry.fit_data,
            gps_track=telemetry.get_gps_track_for_source("fit"),
            target_fps=fps,
            **(extra_kwargs or {}),
        )
    except Exception as e:
        print(f"[AUDIT] case {name} EXCEPTION: {e}", flush=True)
    elapsed = time.perf_counter() - t0

    tracemem = None
    if use_tracemalloc:
        current, peak = tracemalloc.get_traced_memory()
        snap = tracemalloc.take_snapshot()
        top = snap.statistics("lineno")[:25]
        tracemalloc.stop()
        tracemem = {
            "current_bytes": current,
            "peak_bytes": peak,
            "top_sites": [
                {"file": str(Path(s.traceback[0].filename).name) + ":" + str(s.traceback[0].lineno),
                 "size": s.size, "count": s.count}
                for s in top
            ],
        }

    result = {
        "name": name, "ok": ok, "wall_s": round(elapsed, 3),
        "width": width, "height": height, "fps": fps, "frames": int(duration_s * fps),
        "env": {k: v for k, v in env.items() if k in _BASE_ENV or k in env_overrides},
    }
    if prof.exists():
        with open(prof, encoding="utf-8") as f:
            profile = json.load(f)
        result["profile"] = analyze_profile(profile)
    result["system"] = {}
    if tracemem:
        result["tracemalloc"] = tracemem
    return result


def main():
    only = None
    args = sys.argv[1:]
    if "--only" in args:
        i = args.index("--only")
        only = set(x.strip() for x in args[i + 1].split(","))
    layout, telemetry = load_telemetry()

    forms_of = {k: v.get("form") for k, v in layout["indicators"].items()}
    print(f"[AUDIT] v10 indicators ({len(forms_of)}):")
    for k, f in forms_of.items():
        print(f"   {k:28s} form={f}")

    all_forms = set(forms_of.values())
    text_forms = {"text", "time_display"}
    gauge_forms = {"gauge"}
    chart_forms = {"chart"}
    map_forms = {"map"}

    cases = []
    # Tests A-D
    cases.append(("test_A_1080p_full", family_subset(layout, all_forms, None), 1920, 1080, 60.0, 1.5, {}, True))
    cases.append(("test_B_4k_full", family_subset(layout, all_forms, None), 3840, 2160, 60.0, 1.0, {}, True))
    cases.append(("test_C_1080p_nohud", empty_layout(layout), 1920, 1080, 60.0, 1.0, {}, True))
    cases.append(("test_D_4k_nohud", empty_layout(layout), 3840, 2160, 60.0, 1.0, {}, True))
    # 720p baseline + ablations
    cases.append(("abl_full_720p", family_subset(layout, all_forms, None), 1280, 720, 60.0, 1.5, {}, True))
    cases.append(("abl_none_720p", empty_layout(layout), 1280, 720, 60.0, 1.5, {}, False))
    cases.append(("abl_text_720p", family_subset(layout, text_forms, None), 1280, 720, 60.0, 1.5, {}, False))
    cases.append(("abl_gauge_720p", family_subset(layout, gauge_forms, None), 1280, 720, 60.0, 1.5, {}, False))
    cases.append(("abl_chart_720p", family_subset(layout, chart_forms, None), 1280, 720, 60.0, 1.5, {}, False))
    cases.append(("abl_map_720p", family_subset(layout, map_forms, None), 1280, 720, 60.0, 1.5, {}, False))
    cases.append(("abl_gauge_chart_720p", family_subset(layout, {"gauge", "chart"}, None), 1280, 720, 60.0, 1.5, {}, False))
    cases.append(("abl_map_gauge_chart_720p", family_subset(layout, {"map", "gauge", "chart"}, None), 1280, 720, 60.0, 1.5, {}, False))
    # Map variants
    cases.append(("map_cpu_reference_720p", family_subset(layout, all_forms, None), 1280, 720, 60.0, 1.5,
                 {"AMD_MAP_PATH": "CPU_REFERENCE"}, False))
    # Decode variant
    cases.append(("decode_cpu_reference_720p", family_subset(layout, all_forms, None), 1280, 720, 60.0, 1.5,
                 {"AMD_NATIVE_DECODE_MODE": "GPU_HUD_CPU_DECODE_REFERENCE", "AMD_NATIVE_HUD_MODE": "CPU_REFERENCE"}, False))
    # AMF variants
    cases.append(("amf_submit_no_mux_720p", family_subset(layout, all_forms, None), 1280, 720, 60.0, 1.5,
                 {"AMD_AMF_MODE": "SUBMIT_NO_MUX"}, False))
    cases.append(("amf_bypass_720p", family_subset(layout, all_forms, None), 1280, 720, 60.0, 1.5,
                 {"AMD_AMF_MODE": "BYPASS"}, False))
    # Telemetry variant
    cases.append(("telemetry_reference_720p", family_subset(layout, all_forms, None), 1280, 720, 60.0, 1.5,
                 {"AMD_TELEMETRY_MODE": "REFERENCE"}, False))
    # Resolution scaling
    cases.append(("res_720p_full", family_subset(layout, all_forms, None), 1280, 720, 60.0, 1.0, {}, False))
    cases.append(("res_1440p_full", family_subset(layout, all_forms, None), 2560, 1440, 60.0, 1.0, {}, False))
    # Soak (longer)
    cases.append(("soak_720p_600f", family_subset(layout, all_forms, None), 1280, 720, 60.0, 10.0, {}, True))
    # Dedicated long 1080p system probe (render-phase system metrics)
    cases.append(("sysprobe_1080p_300f", family_subset(layout, all_forms, None), 1920, 1080, 60.0, 5.0, {}, True))
    # tracemalloc allocation diagnostic
    cases.append(("alloc_tracemalloc_720p", family_subset(layout, all_forms, None), 1280, 720, 60.0, 1.0,
                 {"AMD_AUDIT_ALLOCS": "1"}, False))

    if only:
        cases = [c for c in cases if c[0] in only]

    # continuous master sampler
    sampler_proc = None
    try:
        if MASTER_CSV.exists():
            MASTER_CSV.unlink()
        try:
            TAG_FILE.write_text("idle", encoding="utf-8")
        except Exception:
            pass
        sampler_proc = subprocess.Popen(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
             "-File", str(SCRATCH / "audit_sampler.ps1"),
             "-Csv", str(MASTER_CSV)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
    except Exception as e:
        print(f"[AUDIT] master sampler start failed: {e}", flush=True)
        sampler_proc = None

    results = []
    summary_path = OUT_DIR / "audit_summary.json"
    existing = {}
    if summary_path.exists():
        try:
            existing = {r["name"]: r for r in json.load(open(summary_path, encoding="utf-8"))}
        except Exception:
            existing = {}

    for name, lay, w, h, fps, dur, env_ov, sampl, *rest in cases:
        use_tm = bool(rest[0]) if rest else False
        if name in existing and only is None:
            print(f"[AUDIT] skipping existing {name}", flush=True)
            results.append(existing[name])
            continue
        print(f"\n[AUDIT] === CASE {name}  {w}x{h} @ {fps}fps {int(dur*fps)} frames ===", flush=True)
        r = run_case(name, lay, w, h, fps, dur, env_ov,
                     sampler=True,  # continuous master sampler tags every case
                     telemetry=telemetry, use_tracemalloc=use_tm)
        results.append(r)
        # persist incrementally (fresh results take precedence over stale existing)
        merged = {**existing, **{r["name"]: r for r in results}}
        with open(summary_path, "w", encoding="utf-8") as f:
            json.dump(list(merged.values()), f, indent=2, ensure_ascii=False)
        print(f"[AUDIT] {name} done ok={r['ok']} wall={r['wall_s']}s "
              f"render_fps={r.get('profile',{}).get('render_fps')} "
              f"true_fps={r.get('profile',{}).get('true_fps')}", flush=True)

    # Write CSV summary
    csv_out = OUT_DIR / "audit_summary.csv"
    with open(csv_out, "w", newline="", encoding="utf-8") as f:
        wcsv = csv.writer(f)
        header = ["name", "ok", "wall_s", "w", "h", "fps", "frames", "render_fps", "true_fps",
                  "mux_wall_ms", "decode_med", "telemetry_med", "compose_med", "above_total_med",
                  "map_cpu_upload_med", "vp_submit_med", "vp_gpu_completion_med", "gpu_wait_med",
                  "amf_submit_med", "amf_query_med", "pipeline_total_med", "producer_med",
                  "consumer_upload_med", "consumer_native_med", "map_path", "chart_path", "gauge_path",
                  "sys_cpu_avg", "sys_cpu_med", "sys_gpu3d_avg", "sys_gpu3d_med", "sys_gpudec_avg",
                  "sys_gpuenc_avg", "sys_ram_used_avg", "sys_vram_ded_avg", "sys_vram_shared_avg"]
        wcsv.writerow(header)
        for r in results:
            p = r.get("profile", {})
            t = p.get("timings", {})
            s = r.get("system", {})
            def g(d, k, sub="med"):
                v = d.get(k) or {}
                return v.get(sub) if isinstance(v, dict) else None
            row = [
                r["name"], r["ok"], r["wall_s"], r["width"], r["height"], r["fps"], r["frames"],
                p.get("render_fps"), p.get("true_fps"), p.get("mux_wall_ms"),
                g(t, "MF ReadSample/decode availability"), g(t, "Telemetry/frame_data"),
                g(t, "compose_overlay"), g(t, "above_total"), g(t, "map_cpu_upload"),
                g(t, "VideoProcessor CPU submit"), g(t, "VideoProcessor GPU completion"),
                g(t, "GPU wait/synchronization"), g(t, "AMF submit/backpressure"),
                g(t, "AMF QueryOutput"), g(t, "pipeline_total"), g(t, "producer_prepare"),
                g(t, "consumer_upload"), g(t, "consumer_native_call"),
                p.get("map_path"), p.get("chart_path"), p.get("gauge_path"),
                g(s, "cpu_total", "avg"), g(s, "cpu_total", "med"), g(s, "gpu_3d", "avg"),
                g(s, "gpu_3d", "med"), g(s, "gpu_decode", "avg"), g(s, "gpu_encode", "avg"),
                g(s, "ram_used_mb", "avg"), g(s, "vram_ded_mb", "avg"), g(s, "vram_shared_mb", "avg"),
            ]
            wcsv.writerow(row)
    print(f"\n[AUDIT] summary written: {csv_out}")
    print(f"[AUDIT] json written: {summary_path}")

    # stop the continuous master sampler
    try:
        TAG_FILE.write_text("idle", encoding="utf-8")
    except Exception:
        pass
    if sampler_proc is not None:
        try:
            sampler_proc.terminate()
            sampler_proc.wait(timeout=5)
        except Exception:
            try:
                sampler_proc.kill()
            except Exception:
                pass
        print("[AUDIT] master sampler stopped", flush=True)
    # post-process: attach system metrics per case from the final master CSV
    try:
        per_tag = aggregate_by_tag(str(MASTER_CSV))
        for r in results:
            r["system"] = per_tag.get(r["name"], r.get("system") or {})
        merged_final = {**existing, **{r["name"]: r for r in results}}
        with open(summary_path, "w", encoding="utf-8") as f:
            json.dump(list(merged_final.values()), f, indent=2, ensure_ascii=False)
        print(f"[AUDIT] system metrics attached ({len(per_tag)} tags)", flush=True)
    except Exception as e:
        print(f"[AUDIT] system post-process failed: {e}", flush=True)


if __name__ == "__main__":
    main()
