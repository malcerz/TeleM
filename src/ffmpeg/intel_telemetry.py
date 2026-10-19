"""Accepted Intel QSV rate-control metadata; no quantizer diagnostics."""
import re
import threading


class IntelQsvTracker:
    def __init__(self, codec):
        self.actual_rc = ""
        self.vbr_verified = False
        self.accepted = {}
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

    def get_hud_state_dict(self):
        with self.lock:
            return {"rate_control": "VBR" if self.vbr_verified else "", "is_cqp": False,
                    "rate_control_raw": self.actual_rc, "encoder_accepted": dict(self.accepted)}
