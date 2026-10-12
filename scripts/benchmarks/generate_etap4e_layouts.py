import json
import copy
from pathlib import Path

BASE_LAYOUT_PATH = Path(r"C:\_DEV\BikeRideHUD-main-new\def_layout.json")
OUT_DIR = Path(r"C:\_DEV\_SPORTCAMHUD_ETAP_4E_RESULTS_20261012\matrix\layouts")
OUT_DIR.mkdir(parents=True, exist_ok=True)

with open(BASE_LAYOUT_PATH, "r", encoding="utf-8") as f:
    base_layout = json.load(f)

TEXT_KEYS = [
    "exposure_text",
    "fit_gopro_battery_text",
    "iso_text",
    "temp_text",
    "time_display",
]

GRAPHIC_KEYS = [
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

def strip_effects(cfg: dict):
    res = copy.deepcopy(cfg)
    res["shadow_enabled"] = False
    res["outline_enabled"] = False
    if "track_outline_width" in res:
        res["track_outline_width"] = 0
    return res

def enable_shadow_only(cfg: dict):
    res = copy.deepcopy(cfg)
    res["shadow_enabled"] = True
    res["outline_enabled"] = False
    return res

def enable_outline_only(cfg: dict):
    res = copy.deepcopy(cfg)
    res["shadow_enabled"] = False
    res["outline_enabled"] = True
    return res

# 1. Variant A: Full HUD with full effects (verbatim copy)
layout_A = copy.deepcopy(base_layout)
with open(OUT_DIR / "A_all_with_effects.json", "w", encoding="utf-8") as f:
    json.dump(layout_A, f, indent=2, ensure_ascii=False)

# 2. Variant B: All indicators active, effects OFF
layout_B = copy.deepcopy(base_layout)
layout_B.setdefault("global", {})["text_outline"] = 0
for k in layout_B.get("indicators", {}):
    layout_B["indicators"][k] = strip_effects(layout_B["indicators"][k])
with open(OUT_DIR / "B_all_no_effects.json", "w", encoding="utf-8") as f:
    json.dump(layout_B, f, indent=2, ensure_ascii=False)

# 3. Variant C: Text indicators ONLY (confirming user's 40 FPS observation)
layout_C = copy.deepcopy(base_layout)
for k, ind in layout_C.get("indicators", {}).items():
    if k not in TEXT_KEYS:
        ind["enabled"] = False
with open(OUT_DIR / "C_text_only.json", "w", encoding="utf-8") as f:
    json.dump(layout_C, f, indent=2, ensure_ascii=False)

# 4. Variant F: Graphical indicators ONLY, NO effects
layout_F = copy.deepcopy(base_layout)
layout_F.setdefault("global", {})["text_outline"] = 0
for k, ind in layout_F.get("indicators", {}).items():
    if k in TEXT_KEYS:
        ind["enabled"] = False
    elif k in GRAPHIC_KEYS:
        layout_F["indicators"][k] = strip_effects(ind)
    else:
        ind["enabled"] = False
with open(OUT_DIR / "F_graphical_no_effects.json", "w", encoding="utf-8") as f:
    json.dump(layout_F, f, indent=2, ensure_ascii=False)

# 5. Variant G: Graphical indicators ONLY, WITH effects
layout_G = copy.deepcopy(base_layout)
for k, ind in layout_G.get("indicators", {}).items():
    if k in TEXT_KEYS:
        ind["enabled"] = False
    elif k not in GRAPHIC_KEYS:
        ind["enabled"] = False
with open(OUT_DIR / "G_graphical_with_effects.json", "w", encoding="utf-8") as f:
    json.dump(layout_G, f, indent=2, ensure_ascii=False)

# 6. Single graphical indicator variants (D = no effects, E = with effects, shadow_only, outline_only)
for g_key in GRAPHIC_KEYS:
    # D: single no effects
    l_d = copy.deepcopy(base_layout)
    l_d.setdefault("global", {})["text_outline"] = 0
    for k, ind in l_d.get("indicators", {}).items():
        if k == g_key:
            ind["enabled"] = True
            l_d["indicators"][k] = strip_effects(ind)
        else:
            ind["enabled"] = False
    with open(OUT_DIR / f"D_{g_key}_no_effects.json", "w", encoding="utf-8") as f:
        json.dump(l_d, f, indent=2, ensure_ascii=False)

    # E: single with effects
    l_e = copy.deepcopy(base_layout)
    for k, ind in l_e.get("indicators", {}).items():
        if k == g_key:
            ind["enabled"] = True
        else:
            ind["enabled"] = False
    with open(OUT_DIR / f"E_{g_key}_with_effects.json", "w", encoding="utf-8") as f:
        json.dump(l_e, f, indent=2, ensure_ascii=False)

    # Shadow only
    l_s = copy.deepcopy(base_layout)
    l_s.setdefault("global", {})["text_outline"] = 0
    for k, ind in l_s.get("indicators", {}).items():
        if k == g_key:
            ind["enabled"] = True
            l_s["indicators"][k] = enable_shadow_only(ind)
        else:
            ind["enabled"] = False
    with open(OUT_DIR / f"S_{g_key}_shadow_only.json", "w", encoding="utf-8") as f:
        json.dump(l_s, f, indent=2, ensure_ascii=False)

    # Outline only
    l_o = copy.deepcopy(base_layout)
    for k, ind in l_o.get("indicators", {}).items():
        if k == g_key:
            ind["enabled"] = True
            l_o["indicators"][k] = enable_outline_only(ind)
        else:
            ind["enabled"] = False
    with open(OUT_DIR / f"O_{g_key}_outline_only.json", "w", encoding="utf-8") as f:
        json.dump(l_o, f, indent=2, ensure_ascii=False)

print(f"Generated layouts in {OUT_DIR}: {len(list(OUT_DIR.glob('*.json')))} files.")
