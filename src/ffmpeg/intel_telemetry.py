"""Intel QSV observations only: never infer QP or RC mode from bitrate."""
import math
import threading
import re


class IntelQsvTracker:
    def __init__(self, codec):
        self.codec = codec
        self.frame = 0
        self.last_frame = -1
        self.values = []
        self.vbr_verified = False
        self.accepted = {}
        self.actual_rc = ""
        self.lock = threading.Lock()

    def feed_progress_line(self, line):
        with self.lock:
            if "RateControlMethod:" in line:
                mode = re.search(r"RateControlMethod:\s*(\w+)", line)
                if mode:
                    self.actual_rc = mode[1]
                    self.vbr_verified = self.actual_rc == "VBR"
            for key, value in re.findall(r"(TargetUsage|TargetKbps|MaxKbps|BufferSizeInKB|InitialDelayInKB|BRCParamMultiplier):\s*(\d+)", line):
                self.accepted[key] = int(value)
            if line.startswith("frame="):
                try: self.frame = int(line.split("=", 1)[1])
                except ValueError: pass
            if line.startswith("stream_0_0_q=") and self.codec == "h264" and self.frame > self.last_frame and self.frame > 0:
                try:
                    value = float(line.split("=", 1)[1])
                    if math.isfinite(value) and 0 <= value <= 51:
                        self.values.append(value)
                        self.last_frame = self.frame
                except ValueError:
                    pass

    def get_hud_state_dict(self):
        with self.lock:
            values = list(self.values)
            reason = ("FFmpeg QSV reports encoded-frame QP side data only for H.264; HEVC quality is unavailable"
                      if self.codec != "h264" else "waiting for encoded-frame quality side data")
            result = {"rate_control": "VBR" if self.vbr_verified else "", "is_cqp": False,
                      "rate_control_raw": self.actual_rc, "encoder_accepted": dict(self.accepted),
                      "quant_metric": "QP", "quant_samples": len(values), "compression_active": bool(values),
                      "qp_source": "FFmpeg QSV oneVPL frame-info via packet quality side data (progress sampled)" if self.codec == "h264" else "unavailable in this FFmpeg HEVC runtime",
                      "qp_aggregation": "arithmetic mean of distinct progress-frame samples; not all frames",
                      "quant_reason": "" if values else reason,
                      "compression_text": "QP: -- (" + reason + ")"}
            if values:
                mean = sum(values) / len(values)
                result.update(quant_current=values[-1], current_qp=values[-1], quant_avg=mean, avg_qp=mean,
                              quant_min=min(values), quant_max=max(values),
                              compression_text=f"QP: {values[-1]:.1f} | Avg: {mean:.1f} | Min: {min(values):.1f} | Max: {max(values):.1f} (próbki progress)")
            return result
