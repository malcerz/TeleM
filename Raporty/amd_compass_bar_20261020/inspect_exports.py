"""Read-only analysis of canonical --test-amd-export results for this task."""
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from src.render_telemetry_cache import RenderTelemetryCache

OUT = Path(__file__).resolve().parent
evidence_path = OUT / "export_evidence.json"
summary = json.loads(evidence_path.read_text(encoding="utf-8")) if evidence_path.exists() else {}
names = sys.argv[1:] or ("before", "after_moving", "top_fit", "bottom_fit", "night_gpmf")
for name in names:
    result = json.loads((OUT / f"{name}.json").read_text(encoding="utf-8"))
    profile = json.loads((OUT / f"{name}.mp4.amd_profile.json").read_text(encoding="utf-8"))
    log = (OUT / f"{name}.log").read_text(encoding="utf-8", errors="replace")
    entries = re.findall(r"\[RENDER PREP\].*?key=([a-f0-9]+)", log)
    cache_info = {}
    if entries:
        matches = list((ROOT / "cache/render_telemetry").glob(entries[-1] + "*/manifest.json"))
        if len(matches) == 1:
            cache = RenderTelemetryCache.load(matches[0])
            values = [cache.lookup(i)["extra_indicators"].get("compass", (None,))[0] for i in range(cache.frames)]
            valid = [v for v in values if v is not None]
            cache_info = {"manifest": str(matches[0].relative_to(ROOT)), "frames": cache.frames,
                          "heading_values": values, "heading_min": min(valid) if valid else None,
                          "heading_max": max(valid) if valid else None,
                          "adjacent_value_changes": sum(a != b for a, b in zip(values, values[1:]))}
    probe = subprocess.run([
        str(ROOT / "runtime/common/ffmpeg/ffprobe.exe"), "-v", "error", "-count_frames",
        "-show_entries", "stream=codec_name,codec_type,nb_read_frames,width,height,color_transfer",
        "-of", "json", str(OUT / f"{name}.mp4")], capture_output=True, text=True, check=True)
    summary[name] = {"success": result["success"], "effective_fps": result["effective_fps"],
                     "native_fps": result["job_results"][0]["native_fps"],
                     "render_fps": profile["true_fps"], "benchmark": profile["benchmark"],
                     "dll": profile["dll"], "amf": profile["amf"],
                     "finalization": profile["finalization"], "audio_present": profile["audio_present"],
                     "streams": json.loads(probe.stdout)["streams"], "cache": cache_info}
    capture = cv2.VideoCapture(str(OUT / f"{name}.mp4"))
    montage = Image.new("RGB", (1600, 680), "#222222")
    for j, idx in enumerate((0, 30, 60, int(result["total_frames"])-1)):
        capture.set(cv2.CAP_PROP_POS_FRAMES, idx)
        ok, frame = capture.read()
        assert ok, (name, idx)
        image = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
        w, h = image.size
        compass = image.crop((int(w*.80), int(h*.18), w, int(h*.48))).resize((400, 310))
        temperature = image.crop((int(w*.55), int(h*.45), w, h)).resize((400, 310))
        montage.paste(compass, (j*400, 30))
        montage.paste(temperature, (j*400, 370))
        ImageDraw.Draw(montage).text((j*400+8, 8), f"{name} frame {idx}", fill="white")
    capture.release()
    montage.save(OUT / f"{name}_inspection.png")

summary["amd_dll_sha256"] = hashlib.sha256((ROOT / "runtime/amd/bin/telem_amd_native.dll").read_bytes()).hexdigest()
summary["user_layout_preserved"] = (ROOT / "def_layout.json").read_bytes() == (OUT / "user_layout_snapshot.json").read_bytes()
(OUT / "export_evidence.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
print(json.dumps({k: {field: v.get(field) for field in ("success", "render_fps", "native_fps")} for k, v in summary.items() if isinstance(v, dict)}, indent=2))
