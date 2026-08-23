import fitparse
from datetime import datetime

fitfile = fitparse.FitFile("Video/Jazda_na_rowerze_w_porze_lunchu.fit")

solar_pct_pts = []
solar_pts = []

for msg in fitfile.get_messages("record"):
    t = None
    spct = None
    sol = None
    for f in msg.fields:
        if f.name == "timestamp":
            t = f.value
        elif f.name == "solar_pct":
            spct = f.value
        elif f.name == "solar":
            sol = f.value
    if spct is not None:
        solar_pct_pts.append((t, spct))
    if sol is not None:
        solar_pts.append((t, sol))

print(f"solar_pct points: {len(solar_pct_pts)}")
print(f"  First: {solar_pct_pts[0]}")
print(f"  Last:  {solar_pct_pts[-1]}")

print(f"solar points: {len(solar_pts)}")
print(f"  First: {solar_pts[0]}")
print(f"  Last:  {solar_pts[-1]}")
