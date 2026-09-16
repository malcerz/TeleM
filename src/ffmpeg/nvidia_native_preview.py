"""NVIDIA Native D3D11 Preview Renderer.

Provides fast, hardware-accelerated preview readback using Direct2D/DirectWrite
and GPU Map from the native pipeline, guaranteeing 100% geometry, font, icon,
and layout parity with the final export without invoking NVENC.
"""

from __future__ import annotations

import os
import ctypes
from typing import Any, Optional
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPixmap

from src.ffmpeg.nvidia_config import (
    load_native_pipeline,
    TelemNvencConfig,
    TelemEncoderConfig,
    TelemFrameState,
    TelemIndicatorDesc,
)
from src.ffmpeg.nvidia_native_exporter import (
    build_canonical_indicators,
    build_map_indicator_desc,
    preload_sqlite_tiles_to_native,
)


class NvidiaNativePreviewRenderer:
    """Renderer for native D3D11 HUD & Map preview frames."""

    def __init__(self, layout: dict, telemetry: Any = None) -> None:
        self.layout = layout
        self.telemetry = telemetry
        self.dll = load_native_pipeline()
        self.handle: Optional[int] = None
        self._buf = bytearray(3840 * 2160 * 4)
        self._width = ctypes.c_uint32(0)
        self._height = ctypes.c_uint32(0)
        self._pitch = ctypes.c_uint32(0)
        self._c_buf = (ctypes.c_char * len(self._buf)).from_buffer(self._buf)
        self._initialized = False

    def initialize(self) -> bool:
        if self._initialized and self.handle:
            return True

        self.handle = self.dll.telem_nvenc_create()
        if not self.handle:
            return False

        enc_cfg = TelemEncoderConfig(
            codec=0,
            quality_mode=0,
            bit_depth=10,
            bitrate_bps=40_000_000,
            max_bitrate_bps=50_000_000,
            vbv_size_bits=40_000_000,
            gop_length=250,
            b_frames=0,
            multipass=0,
            enable_lookahead=0,
            lookahead_depth=0,
            enable_aq=0,
            aq_strength=0,
            enable_temporal_aq=0,
            enable_compression_analysis=0,
            compression_csv_path="",
        )

        cfg = TelemNvencConfig(
            width=3840,
            height=2160,
            fps_num=30000,
            fps_den=1001,
            ring_size=4,
            bit_depth=10,
            preset_p1_to_p7=1,
            tuning_info=1,
            async_nvenc=0,
            enable_debug_layer=0,
            encoder_config=enc_cfg,
        )

        if not self.dll.telem_nvenc_configure(self.handle, ctypes.byref(cfg)):
            self.close()
            return False

        # Setup indicators
        inds = build_canonical_indicators(self.layout)
        map_desc = build_map_indicator_desc(self.layout)
        if map_desc:
            inds.append(map_desc)
            preload_sqlite_tiles_to_native(self.dll, self.handle, map_desc.style.map.zoom, "satellite")

        if inds:
            c_inds = (TelemIndicatorDesc * len(inds))(*inds)
            self.dll.telem_nvenc_set_indicators(self.handle, c_inds, len(inds))

        # Setup map route
        track = getattr(self.telemetry, "fit_gps_track", None) or getattr(self.telemetry, "gps_track", None) or []
        if track:
            route_lats = (ctypes.c_double * len(track))(*[float(pt[1]) for pt in track])
            route_lons = (ctypes.c_double * len(track))(*[float(pt[2]) for pt in track])
            self.dll.telem_nvenc_set_map_route(self.handle, route_lats, route_lons, len(track))

        self._initialized = True
        return True

    def set_telemetry_state(self, state: TelemFrameState) -> None:
        if not self._initialized or not self.handle:
            return
        c_state = (TelemFrameState * 1)(state)
        self.dll.telem_nvenc_set_telemetry(self.handle, c_state, 1)

    def render_hud_qimage(self, frame_index: int = 0, target_w: int = 0, target_h: int = 0) -> Optional[QImage]:
        if not self.initialize():
            return None

        res = self.dll.telem_nvenc_render_hud_frame_to_buffer(
            self.handle,
            frame_index,
            self._c_buf,
            len(self._buf),
            ctypes.byref(self._width),
            ctypes.byref(self._height),
            ctypes.byref(self._pitch),
        )
        if not res:
            return None

        w = self._width.value
        h = self._height.value
        pitch = self._pitch.value

        # Wrap buffer in QImage and make a deep copy so Qt owns the buffer
        qimg = QImage(self._buf, w, h, pitch, QImage.Format_ARGB32_Premultiplied).copy()

        if target_w > 0 and target_h > 0 and (target_w != w or target_h != h):
            qimg = qimg.scaled(target_w, target_h, Qt.KeepAspectRatio, Qt.SmoothTransformation)

        return qimg

    def render_hud_pixmap(self, frame_index: int = 0, target_w: int = 0, target_h: int = 0) -> Optional[QPixmap]:
        qimg = self.render_hud_qimage(frame_index, target_w, target_h)
        if qimg is None or qimg.isNull():
            return None
        return QPixmap.fromImage(qimg)

    def close(self) -> None:
        if self.handle:
            try:
                self.dll.telem_nvenc_destroy(self.handle)
            except Exception:
                pass
            self.handle = None
        self._initialized = False

    def __del__(self) -> None:
        self.close()

