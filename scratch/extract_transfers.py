import json

for name in ("abl_full_720p", "test_A_1080p_full", "test_B_4k_full"):
    p = json.load(open("Raporty/AMD_RENDER_PATH_AUDIT/%s.mp4.amd_profile.json" % name, encoding="utf-8"))
    e3 = p["etap3"]
    e8 = p["etap8n"]
    g = p["etap5g"]
    fr = p["frame_accounting"].get("muxed_frames", 1)
    hud = e3["native_uploaded_bytes_total"] / fr / 1e6
    abv = e8["above_upload_bytes_total"] / fr / 1e6
    mp = g["map_upload_bytes_total"] / fr / 1e6
    tb = p["timings"]["above_region_to_bytes"]["median_ms"]
    print("%-22s hud=%.2fMB/f above=%.2fMB/f map=%.2fMB/f total_cpu2gpu=%.2fMB/f above_tobytes_ms=%.2f" % (name, hud, abv, mp, hud + abv + mp, tb))
