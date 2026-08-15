"""Extract ETAP 5G metrics from profile JSONs for the report."""
import json
import sys

def summarize(path, keys):
    d = json.load(open(path))
    print(f"=== {path} ===")
    t = d.get("timings", {})
    for k in keys:
        v = t.get(k)
        if v:
            print(f"  {k}: avg={v.get('avg_ms', 0):.2f} median={v.get('median_ms', 0):.2f} p95={v.get('p95_ms', 0):.2f}")
    print(f"  true_fps: {d.get('true_fps', 0):.3f}")
    fa = d.get("frame_accounting", {})
    print(f"  frames: src={fa.get('source_frames')} muxed={fa.get('muxed_frames')} amf_out={fa.get('amf_output')}")
    amf = d.get("amf", {})
    print(f"  amf drops: {amf.get('dropped_submissions')} retries: {amf.get('retry_count')}")
    g = d.get("etap5g", {})
    if g:
        print(f"  map_path={g.get('map_path')} filter={g.get('map_filter')} gpu_frames={g.get('map_gpu_frames')}")
        print(f"  map_upload_mib/frame: {g.get('map_upload_mib_per_frame')}")
        ab = g.get("map_ab")
        if ab:
            print(f"  map_ab MAE avg={ab.get('mae', {}).get('avg')} max={ab.get('max', {}).get('avg')} "
                  f"n>1={ab.get('n>1', {}).get('avg')} n>16={ab.get('n>16', {}).get('avg')}")

if __name__ == "__main__":
    keys = ["compose_overlay", "map_cpu_upload", "Telemetry/frame_data", "update_hud",
            "Native HUD CPU copy", "HUD texture upload", "VideoProcessor GPU completion",
            "GPU wait/synchronization", "AMF submit/backpressure", "AMF QueryOutput",
            "BlendRGBAToNV12", "Python->native bridge"]
    for path in sys.argv[1:]:
        summarize(path, keys)
        print()
