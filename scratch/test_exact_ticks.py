import math

def generate_ticks(val_min, val_max, major_step=None, major_ticks=None, minor_ticks=5):
    if val_max <= val_min:
        return []
    
    ticks = []
    if major_step is not None and float(major_step) > 0:
        step = float(major_step)
        minor_per_major = max(1, int(minor_ticks or 5))
        minor_step = step / minor_per_major
        
        k_min = math.floor(val_min / minor_step - 1e-7)
        k_max = math.ceil(val_max / minor_step + 1e-7)
        
        for k in range(k_min, k_max + 1):
            v = round(k * minor_step, 9)
            if val_min - 1e-7 <= v <= val_max + 1e-7:
                # check if major
                m_k = round(v / step)
                is_major = abs(m_k * step - v) < 1e-6
                fraction = (v - val_min) / (val_max - val_min)
                ticks.append({
                    "val": v,
                    "fraction": fraction,
                    "is_major": is_major,
                })
    else:
        m_divs = max(1, int(major_ticks if major_ticks and major_ticks > 0 else 8))
        minor_per_major = max(1, int(minor_ticks or 5))
        total_divisions = m_divs * minor_per_major
        for i in range(total_divisions + 1):
            fraction = i / total_divisions
            v = val_min + fraction * (val_max - val_min)
            is_major = (i % minor_per_major) == 0
            ticks.append({
                "val": v,
                "fraction": fraction,
                "is_major": is_major,
            })
    return ticks

print("--- Test 1: Distance 0..24.23 km, major_step=1.0, minor=5 ---")
t1 = generate_ticks(0.0, 24.23, major_step=1.0, minor_ticks=5)
major1 = [t["val"] for t in t1 if t["is_major"]]
print(f"Total ticks: {len(t1)}, Major ticks ({len(major1)}): {major1}")
assert major1 == [float(i) for i in range(25)]

print("\n--- Test 2: Temperature 23..41 C, major_step=1.0, minor=5 ---")
t2 = generate_ticks(23.0, 41.0, major_step=1.0, minor_ticks=5)
major2 = [t["val"] for t in t2 if t["is_major"]]
print(f"Total ticks: {len(t2)}, Major ticks ({len(major2)}): {major2}")
assert major2 == [float(i) for i in range(23, 42)]

print("\n--- Test 3: Non-zero min 23.4..31.7, major_step=1.0, minor=5 ---")
t3 = generate_ticks(23.4, 31.7, major_step=1.0, minor_ticks=5)
major3 = [t["val"] for t in t3 if t["is_major"]]
print(f"Total ticks: {len(t3)}, Major ticks ({len(major3)}): {major3}")
assert major3 == [float(i) for i in range(24, 32)]

print("\n--- Test 4: Explicit major_step=2.5 over 0..10 ---")
t4 = generate_ticks(0.0, 10.0, major_step=2.5, minor_ticks=5)
major4 = [t["val"] for t in t4 if t["is_major"]]
print(f"Total ticks: {len(t4)}, Major ticks ({len(major4)}): {major4}")
assert major4 == [0.0, 2.5, 5.0, 7.5, 10.0]

print("\nAll tick math assertions passed!")
