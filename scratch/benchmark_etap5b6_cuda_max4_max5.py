from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scratch"))
from benchmark_etap5b5_cuda import run_case


def load_audit():
    path = ROOT / "scratch" / "etap5b6_geometry_audit.json"
    raw = path.read_bytes()
    text = raw.decode("utf-16") if raw.startswith(b"\xff\xfe") else raw.decode("utf-8")
    text = text.replace("\r\n", "\n")
    marker = '{\n  "layout_fit_indicators"'
    return json.loads(text[text.index(marker):])


def main():
    audit = load_audit()["fits"]["Popoludniowa"]["variants"]
    cases = {item["name"]: item for item in audit if item["name"] in {"MAX4_GRID16_current", "MAX5_GRID16"}}
    results = []
    for name, item in cases.items():
        results.append(run_case(name, tuple(item["atlas"]), item["regions"]))
    (ROOT / "scratch" / "etap5b6_cuda_max4_max5.json").write_text(json.dumps(results, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
