"""HDR/SDR classification of source videos and HDR export-mode policy (ETAP 5Z.2).

HLG is recognised only from reliable stream metadata (``color_transfer ==
arib-std-b67``) and is accepted only when the rest of the signalling is
consistent (>= 10-bit, BT.2020 primaries and matrix, known range).  A 10-bit
file, a BT.2020 file or a GoPro file is *not* HDR by itself.  PQ/HDR10 is
recognised but not routed through the HLG pipeline.
"""
from __future__ import annotations

import json
import os
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable, Optional

HDR_MODE_PRESERVE = "preserve_hlg"
HDR_MODE_TONEMAP = "tonemap_sdr"
HDR_MODES = (HDR_MODE_PRESERVE, HDR_MODE_TONEMAP)
DEFAULT_HDR_MODE = HDR_MODE_PRESERVE

HDR_MODE_LABELS = {
    HDR_MODE_PRESERVE: "Zachowaj HDR (HLG 10-bit)",
    HDR_MODE_TONEMAP: "Konwertuj do SDR (tone mapping)",
}
HDR_MODE_DESCRIPTIONS = {
    HDR_MODE_PRESERVE: (
        "Zachowuje HLG, 10-bit i szeroką przestrzeń barw BT.2020. "
        "Najlepsze do odtwarzania na ekranach HDR."
    ),
    HDR_MODE_TONEMAP: (
        "Konwertuje HDR do standardowego obrazu SDR BT.709 z zachowaniem możliwie "
        "dużej ilości szczegółów świateł i cieni."
    ),
}

KIND_SDR8 = "sdr8"
KIND_SDR10 = "sdr10"
KIND_HLG = "hlg"
KIND_PQ = "pq"
KIND_AMBIGUOUS = "ambiguous"
KIND_UNKNOWN = "unknown"

# Message shown when the colour format cannot be established reliably (fail-closed).
UNCERTAIN_HDR_MESSAGE = ("Nie można jednoznacznie ustalić formatu HDR nagrania. "
                         "Eksport wstrzymany, aby uniknąć nieprawidłowych kolorów.")
# SDR transfer characteristics (ffprobe names).  BT.2020 SDR transfers are not
# accepted: they are wide-gamut, which the SDR pipeline does not convert.
SDR_TRANSFERS = {"bt709", "smpte170m", "bt470bg", "bt470m", "smpte240m", "iec61966-2-1",
                 "iec61966-2-4", "bt1361e", "gamma22", "gamma28"}

# Native colour pipeline values (AMD_NATIVE_COLOR_PIPELINE / telem_amd_get_color_pipeline).
PIPELINE_SDR = 0
PIPELINE_HLG_TO_SDR = 1
PIPELINE_HLG_PRESERVE = 2
PIPELINE_ENV = {PIPELINE_SDR: "SDR", PIPELINE_HLG_TO_SDR: "HLG_TO_SDR", PIPELINE_HLG_PRESERVE: "HLG_PRESERVE"}


def normalize_hdr_mode(value: Any) -> str:
    """Map a stored/legacy value to a valid mode; anything unknown -> default (preserve)."""
    text = str(value or "").strip().lower()
    if text in HDR_MODES:
        return text
    if text in ("sdr", "tonemap", "convert", "konwertuj"):
        return HDR_MODE_TONEMAP
    return DEFAULT_HDR_MODE


@dataclass
class VideoColorInfo:
    path: str = ""
    kind: str = KIND_UNKNOWN
    codec: str = ""
    profile: str = ""
    pix_fmt: str = ""
    bit_depth: int = 0
    color_transfer: str = ""
    color_primaries: str = ""
    color_space: str = ""
    color_range: str = ""
    full_range: Optional[bool] = None
    width: int = 0
    height: int = 0
    fps: str = ""
    rotation: int = 0
    reason: str = ""

    @property
    def is_hlg(self) -> bool:
        return self.kind == KIND_HLG

    def summary(self) -> str:
        rng = {True: "full", False: "limited", None: "?"}[self.full_range]
        return (f"{Path(self.path).name}: {self.kind} {self.codec}/{self.profile} {self.pix_fmt} "
                f"{self.bit_depth}-bit {self.color_primaries}/{self.color_transfer}/{self.color_space} "
                f"range={rng} {self.width}x{self.height}@{self.fps} rot={self.rotation}")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SourceColorSummary:
    """Combined decision for all segments of one export."""
    kind: str = KIND_UNKNOWN          # sdr | hlg | pq | mixed | ambiguous | unknown
    clips: list[VideoColorInfo] = field(default_factory=list)
    full_range: Optional[bool] = None
    error: str = ""

    @property
    def is_hlg(self) -> bool:
        return self.kind == KIND_HLG and not self.error

    def to_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "full_range": self.full_range, "error": self.error,
                "clips": [c.to_dict() for c in self.clips]}


def _bit_depth(pix_fmt: str, bits_raw: Any) -> int:
    try:
        b = int(bits_raw or 0)
        if b > 0:
            return b
    except (TypeError, ValueError):
        pass
    pf = (pix_fmt or "").lower()
    if pf in ("none", "unknown"):
        return 0
    for depth in (16, 12, 10):
        if f"p{depth}" in pf or pf.startswith(f"p0{depth}") or f"{depth}le" in pf or f"{depth}be" in pf:
            return depth
    if pf.startswith("p010"):
        return 10
    return 8 if pf else 0


def classify_stream(stream: dict[str, Any], path: str = "", rotation: int = 0) -> VideoColorInfo:
    info = VideoColorInfo(path=str(path))
    info.codec = str(stream.get("codec_name") or "")
    info.profile = str(stream.get("profile") or "")
    info.pix_fmt = str(stream.get("pix_fmt") or "")
    info.bit_depth = _bit_depth(info.pix_fmt, stream.get("bits_per_raw_sample"))
    info.color_transfer = str(stream.get("color_transfer") or "").lower()
    info.color_primaries = str(stream.get("color_primaries") or "").lower()
    info.color_space = str(stream.get("color_space") or "").lower()
    info.color_range = str(stream.get("color_range") or "").lower()
    info.full_range = {"pc": True, "jpeg": True, "tv": False, "mpeg": False}.get(info.color_range)
    info.width = int(stream.get("width") or 0)
    info.height = int(stream.get("height") or 0)
    info.fps = str(stream.get("avg_frame_rate") or stream.get("r_frame_rate") or "")
    info.rotation = int(rotation) % 360

    transfer = info.color_transfer
    missing = [name for name, value in (("color_transfer", transfer), ("color_primaries", info.color_primaries),
                                        ("color_space", info.color_space), ("color_range", info.color_range))
               if not value or value == "unknown"]
    missing_txt = f" (brak pól: {', '.join(missing)})" if missing else ""
    wide_gamut = info.color_primaries == "bt2020" or info.color_space.startswith("bt2020")
    if not info.pix_fmt or info.bit_depth <= 0:
        info.kind = KIND_UNKNOWN
        info.reason = f"nieznana głębia bitowa (pix_fmt={info.pix_fmt or 'brak'}){missing_txt}"
    elif transfer == "arib-std-b67":
        problems = []
        if info.bit_depth < 10:
            problems.append(f"głębia {info.bit_depth}-bit")
        if info.color_primaries != "bt2020":
            problems.append(f"primaries={info.color_primaries or 'brak'}")
        if info.color_space not in ("bt2020nc", "bt2020_ncl"):
            problems.append(f"macierz={info.color_space or 'brak'}")
        if info.full_range is None:
            problems.append("nieznany zakres (full/limited)")
        if problems:
            info.kind = KIND_AMBIGUOUS
            info.reason = "transfer HLG, ale niespójne oznaczenia: " + ", ".join(problems)
        else:
            info.kind = KIND_HLG
            info.reason = "color_transfer=arib-std-b67 + BT.2020 + " + ("full" if info.full_range else "limited")
    elif transfer == "smpte2084":
        info.kind = KIND_PQ
        info.reason = "color_transfer=smpte2084 (PQ/HDR10)"
    elif wide_gamut:
        # BT.2020 without an HDR transfer: SDR wide-gamut or mislabelled HDR.  The SDR
        # pipeline would read it as BT.709, so it is refused instead of guessed.
        info.kind = KIND_AMBIGUOUS
        info.reason = (f"BT.2020 bez transferu HDR (transfer={transfer or 'brak'}, primaries="
                       f"{info.color_primaries or 'brak'}, macierz={info.color_space or 'brak'}){missing_txt}")
    elif info.bit_depth >= 10 and transfer not in SDR_TRANSFERS:
        info.kind = KIND_AMBIGUOUS
        info.reason = f"{info.bit_depth}-bit bez rozpoznanego transferu (transfer={transfer or 'brak'}){missing_txt}"
    else:
        # 8-bit without HDR signalling keeps the historical SDR classification.
        info.kind = KIND_SDR10 if info.bit_depth >= 10 else KIND_SDR8
        info.reason = f"transfer={transfer or 'brak'} (SDR){missing_txt}"
    return info


def _ffprobe_path(ffmpeg_exe: Optional[str]) -> str:
    name = "ffprobe.exe" if os.name == "nt" else "ffprobe"
    if ffmpeg_exe:
        candidate = Path(ffmpeg_exe).with_name(name)
        if candidate.exists():
            return str(candidate)
    return name


def probe_video_color(path: str | Path, ffmpeg_exe: Optional[str] = None, timeout: float = 30.0,
                      attempts: int = 2) -> VideoColorInfo:
    """ffprobe the first video stream; one retry on failure.  A failure is KIND_UNKNOWN, never SDR."""
    info = VideoColorInfo(path=str(path), kind=KIND_UNKNOWN, reason="ffprobe: nie uruchomiono")
    for _ in range(max(1, attempts)):
        info = _probe_video_color_once(path, ffmpeg_exe, timeout)
        if info.kind != KIND_UNKNOWN or not info.reason.startswith("ffprobe"):
            return info
    return info


def _probe_video_color_once(path: str | Path, ffmpeg_exe: Optional[str], timeout: float) -> VideoColorInfo:
    cmd = [
        _ffprobe_path(ffmpeg_exe), "-v", "error", "-select_streams", "v:0", "-show_entries",
        "stream=codec_name,profile,pix_fmt,bits_per_raw_sample,width,height,avg_frame_rate,r_frame_rate,"
        "color_range,color_space,color_transfer,color_primaries:stream_side_data=rotation",
        "-of", "json", str(path),
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if result.returncode != 0:
            return VideoColorInfo(path=str(path), kind=KIND_UNKNOWN,
                                  reason=f"ffprobe: kod {result.returncode}: {(result.stderr or '').strip()[-200:]}")
        data = json.loads(result.stdout or "{}")
    except Exception as exc:  # pragma: no cover - environment dependent
        return VideoColorInfo(path=str(path), kind=KIND_UNKNOWN, reason=f"ffprobe: {type(exc).__name__}: {exc}")
    streams = data.get("streams") or []
    if not streams:
        return VideoColorInfo(path=str(path), kind=KIND_UNKNOWN, reason="ffprobe: brak strumienia wideo")
    stream = streams[0]
    rotation = 0
    for side in stream.get("side_data_list", []) or []:
        try:
            rotation = int(round(float(side.get("rotation", 0))))
            break
        except (TypeError, ValueError):
            continue
    return classify_stream(stream, str(path), rotation)


def summarize_sources(clips: Iterable[VideoColorInfo]) -> SourceColorSummary:
    clips = list(clips)
    summary = SourceColorSummary(clips=clips)
    if not clips:
        summary.kind = KIND_UNKNOWN
        summary.error = "Brak plików wideo."
        return summary
    kinds = {c.kind for c in clips}
    names = lambda pred: ", ".join(Path(c.path).name for c in clips if pred(c))
    if KIND_UNKNOWN in kinds:
        bad = [c for c in clips if c.kind == KIND_UNKNOWN]
        summary.kind = KIND_UNKNOWN
        summary.error = f"{UNCERTAIN_HDR_MESSAGE} ({Path(bad[0].path).name}: {bad[0].reason})"
        return summary
    if KIND_AMBIGUOUS in kinds:
        bad = [c for c in clips if c.kind == KIND_AMBIGUOUS]
        summary.kind = KIND_AMBIGUOUS
        summary.error = f"{UNCERTAIN_HDR_MESSAGE} ({Path(bad[0].path).name}: {bad[0].reason})"
        return summary
    if KIND_PQ in kinds:
        summary.kind = KIND_PQ
        summary.error = ("Materiał PQ/HDR10 nie jest jeszcze obsługiwany przez eksport AMD "
                         f"({names(lambda c: c.kind == KIND_PQ)}). Eksport przerwano, aby nie wykonać błędnej konwersji.")
        return summary
    if KIND_HLG in kinds:
        if kinds != {KIND_HLG}:
            summary.kind = "mixed"
            summary.error = ("Projekt łączy segmenty HLG HDR i SDR "
                             f"(HLG: {names(lambda c: c.is_hlg)}; SDR: {names(lambda c: not c.is_hlg)}). "
                             "Wspólny tryb nie jest obsługiwany — wyeksportuj je osobno.")
            return summary
        ranges = {c.full_range for c in clips}
        geometry = {(c.width, c.height, c.fps) for c in clips}
        if len(ranges) != 1:
            summary.kind = "mixed"
            summary.error = "Segmenty HLG mają różny zakres sygnału (full/limited) — nieobsługiwane w jednym eksporcie."
            return summary
        if len(geometry) != 1:
            summary.kind = "mixed"
            summary.error = "Segmenty HLG mają różną rozdzielczość lub FPS — nieobsługiwane w jednym eksporcie."
            return summary
        rotations = {c.rotation for c in clips}
        if not rotations <= {0, 180}:
            summary.kind = KIND_HLG
            summary.error = f"Obrót {sorted(rotations)}° nie jest obsługiwany dla materiału HLG (tylko 0° i 180°)."
            return summary
        summary.kind = KIND_HLG
        summary.full_range = ranges.pop()
        return summary
    summary.kind = "sdr"
    return summary


def classify_sources(
    paths: Iterable[str | Path],
    ffmpeg_exe: Optional[str] = None,
    fallback_streams: Optional[dict[str, tuple[dict[str, Any], int]]] = None,
) -> SourceColorSummary:
    """Classify every segment.  When ffprobe fails for a file, an already existing,
    complete probe of the same file (``fallback_streams[path] = (stream, rotation)``)
    is used instead; otherwise the clip stays UNKNOWN and the export is refused."""
    clips = []
    for p in paths:
        info = probe_video_color(p, ffmpeg_exe)
        fallback = (fallback_streams or {}).get(str(p))
        if info.kind == KIND_UNKNOWN and info.reason.startswith("ffprobe") and fallback:
            alt = classify_stream(fallback[0], str(p), fallback[1])
            alt.reason = f"{alt.reason} [źródło: istniejący probe eksportera; {info.reason}]"
            info = alt
        clips.append(info)
    return summarize_sources(clips)


class HDRExportConfigError(RuntimeError):
    """Raised before render when the requested HDR handling cannot be honoured."""


def resolve_native_pipeline(
    summary: SourceColorSummary,
    hdr_mode: Any,
    codec_name: str,
    dll_color_features: int,
    main10_supported: Optional[bool],
) -> int:
    """Decide the native colour pipeline.  Never falls back silently.

    ``dll_color_features`` bit 0 = HLG_TO_SDR, bit 1 = HLG_PRESERVE (0 for a DLL
    without the ETAP 5Z.2 exports).  ``main10_supported`` is the result of the
    real Main10 encode probe (None = not probed).
    """
    if summary.error:
        raise HDRExportConfigError(summary.error)
    if summary.kind != KIND_HLG:
        return PIPELINE_SDR
    mode = normalize_hdr_mode(hdr_mode)
    if mode == HDR_MODE_PRESERVE:
        if not dll_color_features & 0x2:
            raise HDRExportConfigError(
                "Załadowana biblioteka AMD (telem_amd_native.dll) nie obsługuje zachowania HDR. "
                "Eksport HDR nie został rozpoczęty.")
        if str(codec_name).upper() != "HEVC":
            raise HDRExportConfigError(
                "Zachowanie HDR (HLG 10-bit) wymaga kodeka HEVC. Wybierz HEVC albo tryb „Konwertuj do SDR”.")
        if main10_supported is not True:
            raise HDRExportConfigError(
                "Ten procesor graficzny nie zakodował strumienia HEVC Main10 (10-bit), więc nie można zachować HDR. "
                "Wybierz tryb „Konwertuj do SDR (tone mapping)” i uruchom eksport ponownie.")
        return PIPELINE_HLG_PRESERVE
    if not dll_color_features & 0x1:
        raise HDRExportConfigError(
            "Załadowana biblioteka AMD (telem_amd_native.dll) nie obsługuje konwersji HLG→SDR. "
            "Eksport nie został rozpoczęty, aby nie zapisać błędnych kolorów.")
    return PIPELINE_HLG_TO_SDR
