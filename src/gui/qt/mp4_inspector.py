"""Inspekcja metadanych pliku MP4 przez ffprobe (warstwa GUI).

Odczytuje podstawowe informacje techniczne o filmie BEZ pełnego dekodowania.
Używa osobnego ffprobe (tej samej instalacji FFmpeg co reszta TeleM) oraz
istniejących narzędzi projektu (video_helpers, telemetry_gpmf_new).

Nie dotyka pipeline'u GPU/AMD — jedynie odczyt metadanych.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any

from src.video_helpers import find_executable, find_local_tool, parse_fps
from src.telemetry_gpmf_new import find_gpmf_stream_index


# ── Ścieżka ffprobe (ta sama logika co kontroler) ─────────────────────────

def resolve_ffprobe() -> str:
    """Znajdź ffprobe z instalacji FFmpeg używanej przez TeleM."""
    base_dir = Path(__file__).resolve().parent.parent.parent.parent
    local = find_local_tool(base_dir, ["ffprobe.exe", "ffprobe"])
    exe = find_executable(
        str(local or "ffprobe"),
        [str(base_dir / "ffprobe.exe"), "ffprobe.exe"],
    )
    return exe or "ffprobe"


# ── Główna inspekcja ──────────────────────────────────────────────────────

def inspect_mp4(video_path: str | Path, ffprobe_exe: str | None = None) -> dict[str, Any]:
    """Odczytaj podstawowe informacje techniczne o pliku MP4.

    Zwraca słownik z polami: filename, size_bytes, size_text, duration_s,
    duration_text, video (dict), audio (dict|None), color (dict), gpmf (bool).
    Rzuca wyjątek przy błędzie odczytu (uszkodzony plik, brak ffprobe itd.).
    """
    path = Path(video_path)
    ffprobe = ffprobe_exe or resolve_ffprobe()

    cmd = [
        ffprobe, "-v", "error",
        "-show_entries",
        "format=duration,size,bit_rate:"
        "stream=index,codec_type,codec_name,profile,width,height,pix_fmt,"
        "avg_frame_rate,r_frame_rate,bit_rate,bits_per_raw_sample,"
        "sample_rate,channels,channel_layout,"
        "color_range,color_space,color_transfer,color_primaries",
        "-of", "json",
        str(path),
    ]
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError((p.stderr or p.stdout or "ffprobe error").strip())

    data = json.loads(p.stdout or "{}")
    streams = data.get("streams", []) or []
    fmt = data.get("format", {}) or {}

    video_stream = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio_stream = next((s for s in streams if s.get("codec_type") == "audio"), None)

    # GPMF — istniejący, tani mechanizm wykrywania (ffprobe -show_streams)
    gpmf = find_gpmf_stream_index(path, ffprobe) is not None

    return {
        "filename": path.name,
        "size_bytes": _to_int(fmt.get("size")),
        "size_text": _fmt_size(_to_int(fmt.get("size"))),
        "duration_s": _to_float(fmt.get("duration")),
        "duration_text": _fmt_duration(_to_float(fmt.get("duration"))),
        "video": _parse_video(video_stream),
        "audio": _parse_audio(audio_stream),
        "color": _parse_color(video_stream),
        "gpmf": bool(gpmf),
    }


# ── Parsowanie strumieni ──────────────────────────────────────────────────

def _parse_video(stream: dict[str, Any] | None) -> dict[str, Any]:
    if stream is None:
        return {
            "codec": "", "codec_label": "—", "profile": "—",
            "width": None, "height": None, "resolution": "—",
            "fps": None, "fps_text": "—",
            "pix_fmt": "—", "bit_depth": None, "bit_depth_text": "—",
            "bitrate": None, "bitrate_text": "—",
        }
    codec = str(stream.get("codec_name") or "")
    width = _to_int(stream.get("width"))
    height = _to_int(stream.get("height"))
    pix_fmt = str(stream.get("pix_fmt") or "")
    bit_depth = _bit_depth(stream, pix_fmt)
    fps = _fps_value(stream)
    bitrate = _to_int(stream.get("bit_rate"))
    return {
        "codec": codec,
        "codec_label": _video_codec_label(codec),
        "profile": str(stream.get("profile") or "—"),
        "width": width,
        "height": height,
        "resolution": f"{width} × {height}" if width and height else "—",
        "fps": fps,
        "fps_text": _fmt_fps(fps),
        "pix_fmt": pix_fmt or "—",
        "bit_depth": bit_depth,
        "bit_depth_text": f"{bit_depth} bit" if bit_depth else "—",
        "bitrate": bitrate,
        "bitrate_text": _fmt_bitrate(bitrate) if bitrate else "—",
    }


def _parse_audio(stream: dict[str, Any] | None) -> dict[str, Any] | None:
    if stream is None:
        return None  # brak strumienia audio
    codec = str(stream.get("codec_name") or "")
    sample_rate = _to_int(stream.get("sample_rate"))
    channels = _to_int(stream.get("channels"))
    channel_layout = str(stream.get("channel_layout") or "")
    bitrate = _to_int(stream.get("bit_rate"))
    return {
        "codec": codec,
        "codec_label": _audio_codec_label(codec),
        "sample_rate": sample_rate,
        "sample_rate_text": f"{sample_rate / 1000:.0f} kHz" if sample_rate else "—",
        "channels": channels,
        "channel_layout": channel_layout,
        "channels_text": _channel_label(channels, channel_layout),
        "bitrate": bitrate,
        "bitrate_text": _fmt_bitrate(bitrate) if bitrate else "—",
    }


def _parse_color(stream: dict[str, Any] | None) -> dict[str, str]:
    if stream is None:
        return {"primaries": "—", "transfer": "—", "space": "—",
                "range": "—", "summary": "—"}
    primaries = str(stream.get("color_primaries") or "")
    transfer = str(stream.get("color_transfer") or "")
    space = str(stream.get("color_space") or "")
    color_range = str(stream.get("color_range") or "")

    prim_label = _COLOR_PRIMARIES.get(primaries, primaries.upper() if primaries else "—")
    trans_label = _COLOR_TRANSFER.get(transfer, transfer.upper() if transfer else "—")
    space_label = _COLOR_SPACE.get(space, space.upper() if space else "—")
    range_label = {"tv": "Limited", "pc": "Full"}.get(
        color_range, color_range.upper() if color_range else "—",
    )

    parts = [x for x in (prim_label, trans_label) if x != "—"]
    summary = " / ".join(parts) if parts else "—"

    return {
        "primaries": prim_label,
        "transfer": trans_label,
        "space": space_label,
        "range": range_label,
        "summary": summary,
    }


# ── Konwersje i etykiety ──────────────────────────────────────────────────

def _to_int(value: Any) -> int | None:
    try:
        if value in (None, ""):
            return None
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _to_float(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _fmt_size(size_bytes: int | None) -> str:
    if not size_bytes or size_bytes < 0:
        return "—"
    size = float(size_bytes)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024.0:
            return f"{int(size)} {unit}" if unit == "B" else f"{size:.2f} {unit}"
        size /= 1024.0
    return f"{size:.2f} PB"


def _fmt_duration(seconds: float | None) -> str:
    if seconds is None or seconds < 0:
        return "—"
    total = int(seconds)
    h = total // 3600
    m = (total % 3600) // 60
    s = total % 60
    return f"{h:02d}:{m:02d}:{s:02d}"


def _fps_value(stream: dict[str, Any]) -> float | None:
    """Poprawnie wylicz FPS z avg_frame_rate / r_frame_rate, albo None."""
    rate = str(stream.get("avg_frame_rate") or stream.get("r_frame_rate") or "")
    if rate and rate != "0/0":
        return parse_fps(rate)
    return None


def _fmt_fps(fps: float | None) -> str:
    if fps is None:
        return "—"
    if abs(fps - round(fps)) < 0.001:
        return f"{fps:.0f}"
    return f"{fps:.2f}"


def _fmt_bitrate(bps: int | float | None) -> str:
    """bps → „92.4 Mb/s” / „192 kb/s”; None → „—”."""
    if not bps:
        return "—"
    b = float(bps)
    if b >= 1_000_000_000:
        return f"{b / 1_000_000_000:.2f} Gb/s"
    if b >= 1_000_000:
        return f"{b / 1_000_000:.1f} Mb/s"
    if b >= 1_000:
        return f"{b / 1_000:.0f} kb/s"
    return f"{b:.0f} b/s"


def _bit_depth(stream: dict[str, Any], pix_fmt: str) -> int | None:
    bprs = _to_int(stream.get("bits_per_raw_sample"))
    if bprs:
        return bprs
    m = re.search(r"(\d+)(?:le|be)\b", pix_fmt or "")
    if m:
        return int(m.group(1))
    return None


_VIDEO_CODEC_LABELS: dict[str, str] = {
    "h264": "H.264 / AVC",
    "hevc": "HEVC / H.265",
    "av1": "AV1",
    "vp9": "VP9",
    "mpeg4": "MPEG-4 Part 2",
    "mjpeg": "MJPEG",
    "prores": "ProRes",
}


def _video_codec_label(codec: str) -> str:
    if not codec:
        return "—"
    return _VIDEO_CODEC_LABELS.get(codec, codec.upper())


_AUDIO_CODEC_LABELS: dict[str, str] = {
    "aac": "AAC",
    "mp3": "MP3",
    "ac3": "AC-3",
    "eac3": "E-AC-3",
    "opus": "Opus",
    "vorbis": "Vorbis",
    "flac": "FLAC",
    "pcm_s16le": "PCM",
    "pcm_s24le": "PCM 24-bit",
    "truehd": "TrueHD",
    "dts": "DTS",
}


def _audio_codec_label(codec: str) -> str:
    if not codec:
        return "—"
    return _AUDIO_CODEC_LABELS.get(codec, codec.upper())


_CHANNEL_LAYOUTS: dict[str, str] = {
    "mono": "Mono",
    "stereo": "Stereo",
    "2.1": "2.1",
    "5.0": "5.0",
    "5.1": "5.1",
    "6.1": "6.1",
    "7.1": "7.1",
}


def _channel_label(channels: int | None, layout: str) -> str:
    if layout and layout.lower() in _CHANNEL_LAYOUTS:
        return _CHANNEL_LAYOUTS[layout.lower()]
    if channels is not None:
        return {
            1: "Mono", 2: "Stereo", 3: "2.1", 4: "4.0",
            5: "5.0", 6: "5.1", 7: "6.1", 8: "7.1",
        }.get(channels, f"{channels} kanałów")
    return "—"


_COLOR_PRIMARIES: dict[str, str] = {
    "bt709": "BT.709",
    "bt2020": "BT.2020",
    "smpte170m": "SMPTE 170M",
    "smpte240m": "SMPTE 240M",
    "bt470bg": "BT.470 BG",
    "bt470m": "BT.470 M",
    "film": "Film",
    "jedec-p22": "JEDEC P22",
}

_COLOR_TRANSFER: dict[str, str] = {
    "bt709": "BT.709",
    "bt2020-10": "BT.2020 (10-bit)",
    "bt2020-12": "BT.2020 (12-bit)",
    "smpte2084": "PQ (HDR10)",
    "arib-std-b67": "HLG",
    "srgb": "sRGB",
    "gamma22": "Gamma 2.2",
    "gamma28": "Gamma 2.8",
    "linear": "Linear",
}

_COLOR_SPACE: dict[str, str] = {
    "bt709": "BT.709",
    "bt2020nc": "BT.2020 NC",
    "bt2020c": "BT.2020 C",
    "bt601": "BT.601",
    "smpte170m": "BT.601",
    "fcc": "FCC",
}


# ── Formatowanie do wyświetlenia w GUI ────────────────────────────────────

def format_file_info_text(info: dict[str, Any]) -> str:
    """Sformatuj wynik inspect_mp4() na czytelny blok tekstu dla GUI."""
    v = info.get("video") or {}
    c = info.get("color") or {}
    a = info.get("audio")

    lines: list[str] = [
        f"Nazwa pliku: {info.get('filename') or '—'}",
        f"Rozmiar: {info.get('size_text') or '—'}",
        f"Czas: {info.get('duration_text') or '—'}",
        f"Rozdzielczość: {v.get('resolution') or '—'}",
        f"FPS: {v.get('fps_text') or '—'}",
        f"Kodek: {v.get('codec_label') or '—'}",
        f"Profil: {v.get('profile') or '—'}",
        f"Pixel format: {v.get('pix_fmt') or '—'}",
        f"Bit depth: {v.get('bit_depth_text') or '—'}",
        f"Bitrate: {v.get('bitrate_text') or '—'}",
        "",
        "Kolor:",
        f"{c.get('summary') or '—'}",
        f"Range: {c.get('range') or '—'}",
    ]
    if c.get("space") and c["space"] != "—":
        lines.append(f"Space: {c['space']}")
    lines.append("")

    if a:
        lines.append("Audio:")
        lines.append(a.get("codec_label") or "—")
        lines.append(a.get("sample_rate_text") or "—")
        lines.append(a.get("channels_text") or "—")
        lines.append(a.get("bitrate_text") or "—")
    else:
        lines.append("Audio: BRAK")

    lines.append("")
    lines.append(f"GPMF: {'TAK' if info.get('gpmf') else 'NIE'}")
    return "\n".join(lines)


# ── Placeholder wyniku analizy QP ─────────────────────────────────────────

QP_PLACEHOLDER = (
    "Analiza QP\n\n"
    "Średni:   —\n"
    "Mediana:  —\n"
    "Min:      —\n"
    "Max:      —"
)
