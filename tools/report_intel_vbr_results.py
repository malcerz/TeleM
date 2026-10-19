"""Validate saved matrix evidence and write its report table without rerendering."""
from pathlib import Path
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    from src.ffmpeg.intel_native_exporter import _withhold_unverified_hevc_qp
    out = ROOT / "Raporty/intel_vbr_qp_20261017/matrix"
    data = json.loads((out / "summary_benchmark.json").read_text(encoding="utf-8"))
    assert len(data) == 12
    rows = ["| Ścieżka / kodek | Profil (TU) | Czas s | FPS | Śr. Mb/s | Maks. 0,1 / 1 s Mb/s | QP min / śr. / max | Próbki QP |",
            "|---|---|---:|---:|---:|---:|---|---:|"]
    for item in data:
        codec = item["codec"]; backend = item["intel_path"]
        stream = item["stream"]; video = stream["video"]; hrd = stream["hrd"]
        assert item["success"] and stream["decode_ok"] and int(video["nb_frames"]) == 600
        assert video["codec_name"] == codec and video["avg_frame_rate"] == "30000/1001"
        assert video["pix_fmt"] == ("yuv420p10le" if codec == "hevc" else "yuv420p")
        assert video["color_transfer"] == ("arib-std-b67" if codec == "hevc" else "bt709")
        assert video["profile"] == ("Main 10" if codec == "hevc" else "High")
        assert stream["av_duration_delta_s"] < .1
        assert hrd["nal_hrd_parameters_present_flag"] == 1 and hrd["cbr_flag[0]"] == 0
        assert abs((hrd["bit_rate_value_minus1[0]"] + 1) * 2 ** (6 + hrd["bit_rate_scale"]) - 50000000) < 2048
        assert (hrd["cpb_size_value_minus1[0]"] + 1) * 2 ** (4 + hrd["cpb_size_scale"]) == 80000000
        stats = item["stats"]; accepted = stats["encoder_accepted"]
        tu = {"fast":7,"balanced":4,"quality":1}[item["profile"]]
        if backend == "native":
            assert accepted["target_usage"] == tu and accepted["rate_control"] == 2
            assert tuple(accepted[k] for k in ("target_kbps","max_kbps","buffer_kb","initial_delay_kb")) == (40000,50000,10000,5000)
            if codec == "hevc": stats = item["stats"] = _withhold_unverified_hevc_qp(stats)
        else:
            assert stats["rate_control"] == "VBR" and accepted["TargetUsage"] == tu
            multiplier = accepted.get("BRCParamMultiplier", 1) or 1
            assert tuple(accepted[k]*multiplier for k in ("TargetKbps","MaxKbps","BufferSizeInKB","InitialDelayInKB")) == (40000,50000,10000,5000)
        qp = "--" if codec == "hevc" else f'{stats["quant_min"]:.1f} / {stats["quant_avg"]:.2f} / {stats["quant_max"]:.1f}'
        rows.append(f'| {backend} / {codec} | {item["profile"]} ({tu}) | {item["elapsed_s"]:.2f} | {item["effective_fps"]:.2f} | {stream["avg_video_mbps"]:.2f} | {stream["peak_0.1s_mbps"]:.2f} / {stream["peak_1s_mbps"]:.2f} | {qp} | {stats.get("quant_samples",0)} |')
    (out / "validated_summary.json").write_text(json.dumps(data, indent=2), encoding="utf-8")
    (out / "benchmark_table.md").write_text("\n".join(rows), encoding="utf-8")
    print("\n".join(rows))
    print("PASS: 12 streams, actual TU/VBR/VBV, HLG/SDR, frame rate/count, HRD, A/V and full decode")


if __name__ == "__main__":
    main()
