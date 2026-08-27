import json

layout = json.load(open("def_layout.json", encoding="utf-8"))

for k, v in layout.get("indicators", {}).items():
    print(f"Widget: {k:<25} | form: {v.get('form', '<none>'):<15} | enabled: {v.get('enabled')} | source: {v.get('source')} | pos: ({v.get('x')}, {v.get('y')}) | size: {v.get('size')}")
