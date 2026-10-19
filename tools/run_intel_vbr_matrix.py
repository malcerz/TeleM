"""Drive the canonical GUI harness serially; inspect packets and PID-scoped GPU counters."""
from __future__ import annotations
import argparse
import ctypes as c
from ctypes import wintypes as w
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import psutil


class Value(c.Structure):
    _fields_ = [("status", w.DWORD), ("value", c.c_double)]


class Item(c.Structure):
    _fields_ = [("name", w.LPWSTR), ("value", Value)]


class GpuCounter:
    def __init__(self):
        self.query = c.c_void_p(); self.counter = c.c_void_p()
        self.pdh = c.WinDLL("pdh")
        self.pdh.PdhOpenQueryW.argtypes = [w.LPCWSTR, c.c_size_t, c.POINTER(c.c_void_p)]
        self.pdh.PdhAddEnglishCounterW.argtypes = [c.c_void_p, w.LPCWSTR, c.c_size_t, c.POINTER(c.c_void_p)]
        self.pdh.PdhCollectQueryData.argtypes = [c.c_void_p]
        self.pdh.PdhGetFormattedCounterArrayW.argtypes = [c.c_void_p, w.DWORD, c.POINTER(w.DWORD), c.POINTER(w.DWORD), c.c_void_p]
        self.pdh.PdhCloseQuery.argtypes = [c.c_void_p]
        assert self.pdh.PdhOpenQueryW(None, 0, c.byref(self.query)) == 0
        assert self.pdh.PdhAddEnglishCounterW(self.query, r"\GPU Engine(*)\Utilization Percentage", 0, c.byref(self.counter)) == 0
        self.pdh.PdhCollectQueryData(self.query)

    def sample(self, pids):
        self.pdh.PdhCollectQueryData(self.query)
        size, count = w.DWORD(), w.DWORD()
        self.pdh.PdhGetFormattedCounterArrayW(self.counter, 0x8200, c.byref(size), c.byref(count), None)
        if not size.value: return None
        buf = c.create_string_buffer(size.value)
        rc = self.pdh.PdhGetFormattedCounterArrayW(self.counter, 0x8200, c.byref(size), c.byref(count), buf)
        if rc: return None
        items = c.cast(buf, c.POINTER(Item))
        values = []
        for i in range(count.value):
            name = items[i].name or ""
            match = re.search(r"pid_(\d+)_", name)
            if match and int(match[1]) in pids and "engtype_VideoEncode" in name and items[i].value.status in (0, 1):
                values.append(items[i].value.value)
        return sum(values) if values else None

    def close(self):
        self.pdh.PdhCloseQuery(self.query)


def inspect(path, ffmpeg, ffprobe, out):
    data = json.loads(subprocess.check_output([str(ffprobe), "-v", "error", "-show_streams", "-show_packets",
                       "-show_entries", "stream=codec_type,codec_name,profile,pix_fmt,color_transfer,nb_frames,duration,avg_frame_rate:packet=stream_index,pts_time,size",
                       "-of", "json", str(path)], text=True))
    video = next(s for s in data["streams"] if s["codec_type"] == "video")
    audio = next(s for s in data["streams"] if s["codec_type"] == "audio")
    packets = sorted((float(p["pts_time"]), int(p["size"])) for p in data["packets"] if p["stream_index"] == 0)
    peaks = {}
    for window in (0.1, 1.0):
        first = 0; total = 0; peak = 0
        for last, (t, size) in enumerate(packets):
            total += size
            while first < last and packets[first][0] <= t - window:
                total -= packets[first][1]; first += 1
            peak = max(peak, total * 8 / window / 1e6)
        peaks[f"peak_{window:g}s_mbps"] = peak
    headers = subprocess.run([str(ffmpeg), "-nostdin", "-v", "verbose", "-i", str(path), "-map", "0:v:0", "-frames:v", "1",
                              "-c:v", "copy", "-bsf:v", "trace_headers", "-an", "-f", "null", "-"],
                             capture_output=True, text=True, timeout=60)
    (out / (path.stem + "_headers.log")).write_text(headers.stderr, encoding="utf-8")
    hrd = {}
    for key in ("nal_hrd_parameters_present_flag", "bit_rate_scale", "cpb_size_scale", "bit_rate_value_minus1[0]", "cpb_size_value_minus1[0]", "cbr_flag[0]"):
        match = re.search(re.escape(key) + r"\s+\S+\s+=\s+(\d+)", headers.stderr)
        hrd[key] = int(match[1]) if match else None
    decode = subprocess.run([str(ffmpeg), "-nostdin", "-v", "error", "-i", str(path), "-map", "0:v:0", "-map", "0:a:0", "-f", "null", "-"],
                            capture_output=True, text=True, timeout=180)
    return dict(video=video, audio=audio, avg_video_mbps=sum(s for _, s in packets)*8/float(video["duration"])/1e6,
                **peaks, hrd=hrd, decode_ok=decode.returncode == 0, decode_error=decode.stderr,
                av_duration_delta_s=abs(float(video["duration"])-float(audio["duration"])))


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--frames",type=int,default=600)
    parser.add_argument("--smoke-frames",type=int,default=30)
    parser.add_argument("--output",default="Raporty/intel_vbr_qp_20261017/matrix")
    parser.add_argument("--phase",choices=["smoke","benchmark","both"],default="both")
    args=parser.parse_args()
    out=(ROOT/args.output).resolve(); out.mkdir(parents=True,exist_ok=True)
    layout=ROOT/"Raporty/intel_vbr_qp_20261017/layout.json"
    ffmpeg=ROOT/"runtime/common/ffmpeg/ffmpeg.exe"; ffprobe=ffmpeg.with_name("ffprobe.exe")
    env=os.environ.copy(); env["QT_QPA_PLATFORM"]="offscreen"
    for name in ("TELEM_INTEL_TARGET_USAGE","TELEM_INTEL_QSV_BITRATE_MBPS","TELEM_INTEL_QP_TRACE","TELEM_INTEL_FORCE_SERIAL_7D"):
        env.pop(name,None)
    env["TELEM_INTEL_NATIVE_DLL"]=str(ROOT/"runtime/intel/bin/telem_intel_native.dll")
    all_results=[]
    for phase, frames in (("smoke",args.smoke_frames),("benchmark",args.frames)):
        if args.phase not in (phase,"both"): continue
        for backend in ("native","ffmpeg"):
            for codec in ("hevc","h264"):
                for profile in ("fast","balanced","quality"):
                    name=f"{phase}_{backend}_{codec}_{profile}"
                    mp4=out/(name+".mp4"); result=out/(name+".json")
                    if result.exists(): result.unlink()
                    cmd=[sys.executable,str(ROOT/"SportCamHUD.py"),"--test-intel-export","--intel-path",backend,"--codec",codec,
                         "--profile",profile,"--frames",str(frames),"--bitrate","40M","--video",r"C:\GoPro\GX010378.MP4",
                         "--fit",r"C:\GoPro\2026-10-15_15-03-50.fit","--layout",str(layout),"--watchdog-seconds","900",
                         "--output",str(mp4),"--result-json",str(result)]
                    print("START",name,flush=True)
                    samples=[]; counter_error=""; counter=None
                    try: counter=GpuCounter()
                    except Exception as exc: counter_error=str(exc)
                    started=time.perf_counter()
                    with (out/(name+".log")).open("w",encoding="utf-8") as log:
                        proc=subprocess.Popen(cmd,cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT)
                        while proc.poll() is None:
                            time.sleep(1)
                            try:
                                pids={proc.pid}|{p.pid for p in psutil.Process(proc.pid).children(recursive=True)}
                                if counter:
                                    sample=counter.sample(pids)
                                    if sample is not None: samples.append(sample)
                            except psutil.Error: pass
                    if counter: counter.close()
                    if proc.returncode:
                        raise RuntimeError(f"Harness exited with {proc.returncode}: {name}")
                    if not samples and not counter_error:
                        counter_error="Driver exposes no PID-scoped VideoEncode counter; VideoDecode/VideoProcessing cannot be substituted"
                    elapsed=time.perf_counter()-started
                    if not result.exists(): raise RuntimeError(f"Harness produced no result: {name}")
                    item=json.loads(result.read_text(encoding="utf-8"))
                    item.update(name=name,phase=phase,process_wall_s=elapsed,command=cmd,
                                gpu_encode_samples=samples,gpu_counter_error=counter_error,
                                gpu_encode_mean=sum(samples)/len(samples) if samples else None,
                                gpu_encode_active_mean=sum(v for v in samples if v>0)/len([v for v in samples if v>0]) if any(v>0 for v in samples) else None,
                                layout_sha256=hashlib.sha256(layout.read_bytes()).hexdigest())
                    if not item["success"]: raise RuntimeError(f"Harness failed: {name}: {item['error']}")
                    item["stream"]=inspect(mp4,ffmpeg,ffprobe,out)
                    assert item["stream"]["decode_ok"] and int(item["stream"]["video"]["nb_frames"])==frames
                    stream = item["stream"]["video"]
                    assert stream["codec_name"] == codec and stream["avg_frame_rate"] == "30000/1001"
                    assert item["stream"]["av_duration_delta_s"] < 0.1
                    assert stream["pix_fmt"] == ("yuv420p10le" if codec == "hevc" else "yuv420p")
                    assert stream["color_transfer"] == ("arib-std-b67" if codec == "hevc" else "bt709")
                    assert item["stream"]["hrd"]["nal_hrd_parameters_present_flag"] == 1
                    assert item["stream"]["hrd"]["cbr_flag[0]"] == 0
                    if backend=="native": assert "encoder_accepted" in item["stats"] and "target_usage" in item["stats"]["encoder_accepted"]
                    all_results.append(item)
                    (out/f"summary_{args.phase}.json").write_text(json.dumps(all_results,indent=2),encoding="utf-8")
                    print("DONE",name,"fps=",item["effective_fps"],"Mbps=",round(item["stream"]["avg_video_mbps"],2),flush=True)


if __name__=="__main__": main()
