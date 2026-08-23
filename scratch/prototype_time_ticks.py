from typing import Union

_NICE_TIME_STEPS = [
    1, 2, 5, 10, 15, 30,
    60, 120, 300, 600, 900, 1800,
    3600, 7200, 14400, 21600, 43200, 86400,
]

def generate_nice_time_ticks(duration_s: float, target_count: int = 5) -> list[tuple[float, str]]:
    """Generate nice time ticks for a given duration.
    
    Returns a list of (norm_x, label_str) tuples where norm_x is in [0.0, 1.0].
    """
    duration_s = max(1.0, float(duration_s))
    
    # Select best step
    best_step = _NICE_TIME_STEPS[0]
    best_score = float("inf")
    
    for step in _NICE_TIME_STEPS:
        count = int(duration_s // step) + 1
        # Score based on distance from target_count (prefer 4-7 ticks)
        score = abs(count - target_count)
        if count < 2:
            score += 100
        elif count > 9:
            score += (count - 9) * 2
        if score < best_score:
            best_score = score
            best_step = step
            
    # Generate ticks
    ticks = []
    tick_sec = 0
    is_hours = duration_s >= 3600.0
    
    while tick_sec <= duration_s:
        norm_x = tick_sec / duration_s
        if is_hours:
            h = int(tick_sec // 3600)
            m = int((tick_sec % 3600) // 60)
            lbl = f"{h}:{m:02d}"
        else:
            m = int(tick_sec // 60)
            s = int(tick_sec % 60)
            lbl = f"{m:02d}:{s:02d}"
        ticks.append((norm_x, lbl))
        tick_sec += best_step
        
    return ticks

# Test on various durations
test_cases = [
    (8480.0, "FIT activity ~2h 21m"),
    (120.0, "Video 2m"),
    (600.0, "Activity 10m"),
    (3600.0, "Activity 1h"),
    (18000.0, "Activity 5h"),
    (45.0, "Short clip 45s"),
]

for dur, desc in test_cases:
    t = generate_nice_time_ticks(dur)
    print(f"\n{desc} ({dur}s): {len(t)} ticks")
    print("  " + ", ".join(f"{lbl} ({norm_x*100:.1f}%)" for norm_x, lbl in t))
