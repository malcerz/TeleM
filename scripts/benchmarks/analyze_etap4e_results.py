"""Analysis and aggregation script for ETAP 4E benchmark results."""
from __future__ import annotations

import json
from pathlib import Path


RESULTS_DIR = Path("C:/_DEV/_SPORTCAMHUD_ETAP_4E_RESULTS_20261012")
SUMMARY_JSON = RESULTS_DIR / "matrix_summary.json"


def main():
    with SUMMARY_JSON.open("r", encoding="utf-8") as f:
        data = json.load(f)

    graphical_keys = [
        "alt_text",
        "fit_cadence_text",
        "fit_curVpower_text",
        "fit_distance_text",
        "fit_garmin_battery_percent_text",
        "fit_heart_rate_text",
        "fit_solar_text",
        "fit_temperature_text",
        "lean_indicator",
        "speed_text",
        "track_map",
        "compass",
    ]

    print("=== GLOBAL BENCHMARK RUNS ===")
    for k in ["C_text_only_canonical", "B_all_no_effects_canonical", "A_all_with_effects_canonical",
              "C_text_only", "B_all_no_effects", "A_all_with_effects", "F_graphical_no_effects", "G_graphical_with_effects"]:
        if k in data:
            row = data[k]
            print(f"{k:30} | Frames: {row['frames']:4} | Eff FPS: {row['effective_fps']:5.2f} | Render FPS: {row['render_fps']:5.2f} | Compose: {row['compose_overlay_ms']:5.2f}ms | Prep: {row['producer_prepare_ms']:5.2f}ms | QWait: {row['consumer_queue_wait_ms']:5.2f}ms")

    print("\n=== ISOLATED WIDGET COST ANALYSIS (300 frames) ===")
    table_rows = []
    for key in graphical_keys:
        d_k = f"D_{key}_no_effects"
        e_k = f"E_{key}_with_effects"
        s_k = f"S_{key}_shadow_only"
        o_k = f"O_{key}_outline_only"

        d_compose = data.get(d_k, {}).get("compose_overlay_ms", 0.0)
        e_compose = data.get(e_k, {}).get("compose_overlay_ms", 0.0)
        s_compose = data.get(s_k, {}).get("compose_overlay_ms", 0.0)
        o_compose = data.get(o_k, {}).get("compose_overlay_ms", 0.0)

        d_fps = data.get(d_k, {}).get("render_fps", 0.0)
        e_fps = data.get(e_k, {}).get("render_fps", 0.0)

        # In A_all_with_effects, check profiler measurements
        a_metrics = data.get("A_all_with_effects_canonical", {}).get("widget_metrics", {})
        if not a_metrics:
            a_metrics = data.get("A_all_with_effects", {}).get("widget_metrics", {})

        w_base = a_metrics.get(f"widget.{key}.base_render", 0.0)
        w_eff = a_metrics.get(f"widget.{key}.effects", 0.0)
        w_shad = a_metrics.get(f"widget.{key}.shadow", 0.0)
        w_out = a_metrics.get(f"widget.{key}.outline", 0.0)
        w_needle = a_metrics.get(f"widget.{key}.needle_ms", 0.0)
        w_paste = a_metrics.get(f"widget.{key}.paste", a_metrics.get(f"widget.widget_{key}_paste_ms", 0.0))
        w_render = a_metrics.get(f"widget.{key}.render", a_metrics.get(f"widget.widget_{key}_ms", 0.0))
        w_total = a_metrics.get(f"widget.{key}.total", w_render + w_paste)

        delta_effects = e_compose - d_compose
        delta_shadow = s_compose - d_compose
        delta_outline = o_compose - d_compose

        table_rows.append({
            "key": key,
            "d_compose": d_compose,
            "e_compose": e_compose,
            "s_compose": s_compose,
            "o_compose": o_compose,
            "delta_effects": delta_effects,
            "delta_shadow": delta_shadow,
            "delta_outline": delta_outline,
            "d_fps": d_fps,
            "e_fps": e_fps,
            "w_base": w_base,
            "w_eff": w_eff,
            "w_shad": w_shad,
            "w_out": w_out,
            "w_needle": w_needle,
            "w_paste": w_paste,
            "w_render": w_render,
            "w_total": w_total,
        })

    # Sort by isolated compose time with effects
    table_rows.sort(key=lambda x: x["e_compose"], reverse=True)

    print(f"{'Widget Key':30} | {'Base (D)':8} | {'Effects (E)':11} | {'Delta Eff':9} | {'Shadow (S)':10} | {'Outline (O)':11} | {'HUD Total':9} | {'Base Render':11} | {'Paste':7}")
    print("-" * 125)
    for r in table_rows:
        print(f"{r['key']:30} | {r['d_compose']:7.2f}ms | {r['e_compose']:10.2f}ms | {r['delta_effects']:+8.2f}ms | {r['s_compose']:9.2f}ms | {r['o_compose']:10.2f}ms | {r['w_total']:8.2f}ms | {r['w_base']:10.2f}ms | {r['w_paste']:6.2f}ms")

    # Save detailed analysis JSON
    analysis_out = RESULTS_DIR / "etap4e_detailed_analysis.json"
    with analysis_out.open("w", encoding="utf-8") as f:
        json.dump({"summary": data, "widget_ranking": table_rows}, f, indent=2, ensure_ascii=False)
    print(f"\nDetailed analysis saved to: {analysis_out}")


if __name__ == "__main__":
    main()
