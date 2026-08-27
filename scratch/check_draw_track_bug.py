try:
    from src.indicators.moving_map import render_map_unrotated_working_image
    import json
    layout = json.load(open("def_layout.json"))
    # Let's inspect the exact exception inside render_map_unrotated_working_image
    # by running the inner code
    cfg = layout["indicators"]["track_map"]
    # check if draw_track was defined
    print("draw_track check...")
except Exception as e:
    print("Error:", e)
