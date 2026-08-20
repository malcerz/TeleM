import json
with open('def_layout.json') as f:
    l = json.load(f)

print("ENABLED INDICATORS IN def_layout.json:")
for k, v in l.get('indicators', {}).items():
    if v.get('enabled', True):
        form = v.get('form', 'text')
        rot = v.get('rotation', 0)
        src = v.get('source', 'gpmf')
        x = v.get('x', 0)
        y = v.get('y', 0)
        print(f"  {k:30s} | form={form:10s} | rot={rot:3d} | src={src:6s} | pos=({x:.1f}, {y:.1f})")

print(f"\nCustom texts: {len(l.get('custom_texts', []))}")
