import json
with open('def_layout.json') as f:
    layout = json.load(f)
ind = layout.get('indicators', {})
for key in ['fit_cadence_text', 'fit_heart_rate_text']:
    cfg = ind.get(key, {})
    print(f"{key}:")
    print(f"  label_font_size = {cfg.get('label_font_size', 'NOT SET')}")
    print(f"  size = {cfg.get('size', 'NOT SET')}")
    print(f"  x = {cfg.get('x', 'NOT SET')}, y = {cfg.get('y', 'NOT SET')}")
    print()
