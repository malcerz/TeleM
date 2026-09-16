"""
TeleM NVIDIA STAGE 8E Prototype:
REAL VIDEO HARDWARE DECODE + REAL TELEMETRY + DIRECT2D HUD + NVENC ZERO-COPY PIPELINE

Architecture:
- Video Source: Video/GX030120.MP4 (3840x2160, 29.970 fps rational 30000/1001, HEVC Main 10)
- Telemetry Source: Video/Popoludniowa_jazda_na_rowerze_solar_battery.fit
- Hardware Decode: Media Foundation D3D11VA SourceReader via IMFDXGIDeviceManager on SAME D3D11 Device
- Bit Depth: 10-bit P010 decode -> D3D11 VideoProcessor -> 8-bit NV12 output ring
- Telemetry: Precomputed frame-indexed FrameState table (time, speed, heart_rate)
- HUD: Direct2D / DirectWrite on 4K BGRA8 texture
- GPU Compositor: D3D11 VideoProcessorBlt multi-stream (Stream 0: P010 video, Stream 1: BGRA8 HUD with stream alpha)
- Encoder: NVIDIA Video Codec SDK 13.1, NVENC HEVC P1 HQ zero-copy from GPU VRAM
- Assertions: DECODE_GPU_TO_CPU_FRAME_BYTES = 0, GPU_TO_CPU_FRAME_BYTES = 0, CPU_TO_GPU_FULL_FRAME_BYTES_PER_FRAME = 0
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import json
import math
import os
from pathlib import Path
import sys
import time
from typing import Dict, List, Optional, Tuple, NamedTuple
from datetime import datetime, timedelta

# Ensure repo root and prototype dir in sys.path
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).parent))

import psutil
from nvenc_api import (
    NvEncodeAPIHeader, GUID,
    NV_ENC_OPEN_ENCODE_SESSION_EX_PARAMS,
    NV_ENC_INITIALIZE_PARAMS,
    NV_ENC_PRESET_CONFIG_BUFFER,
    NV_ENC_REGISTER_RESOURCE,
    NV_ENC_MAP_INPUT_RESOURCE,
    NV_ENC_CREATE_BITSTREAM_BUFFER,
    NV_ENC_PIC_PARAMS,
    NV_ENC_LOCK_BITSTREAM,
    NV_ENCODE_API_FUNCTION_LIST
)

# ── COM / D3D11 Definitions ──────────────────────────────────────────────────

d3d11 = ctypes.windll.d3d11
dxgi = ctypes.windll.dxgi
d2d1 = ctypes.windll.d2d1
dwrite = ctypes.windll.dwrite
mfplat = ctypes.windll.mfplat
mfreadwrite = ctypes.windll.mfreadwrite
ole32 = ctypes.windll.ole32

def str_to_guid(s: str) -> GUID:
    parts = s.strip('{}').split('-')
    d1 = int(parts[0], 16)
    d2 = int(parts[1], 16)
    d3 = int(parts[2], 16)
    b0_1 = [int(parts[3][i:i+2], 16) for i in (0, 2)]
    b2_7 = [int(parts[4][i:i+2], 16) for i in (0, 2, 4, 6, 8, 10)]
    return GUID(d1, d2, d3, (wintypes.BYTE * 8)(*(b0_1 + b2_7)))

IID_ID3D11Multithread = str_to_guid("9B7E4E00-342C-4106-A19F-4F2704F689F0")
IID_ID3D11Texture2D   = str_to_guid("6F15AAF2-D208-4E89-9AB4-489535D34F9C")
IID_IMFDXGIBuffer     = str_to_guid("E7174CFA-1C9E-48B1-8866-626226BFC258")
IID_IDXGIAdapter3     = str_to_guid("645967A4-1392-4310-A798-8053CE3E93FD")
IID_IDXGIDevice       = str_to_guid("54ec77fa-1377-44e6-8c32-88fd5f44c84c")
IID_IDXGISurface1     = str_to_guid("4AE63092-6327-4c1b-80AE-BFE12EA32B86")
IID_IDWriteFactory    = str_to_guid("b859ee5a-d838-4b5b-a2e8-1adc7d93db48")
IID_ID3D11InfoQueue   = str_to_guid("6543dbb6-1b48-42f5-ab82-e97ec74326f6")
IID_ID3D11VideoDevice = str_to_guid("10EC4D5B-975A-4689-B9E4-D0AAC30FE333")
IID_ID3D11VideoContext= str_to_guid("61F21C45-3C0E-4A74-9CEA-67100D9AD5E4")

MF_SOURCE_READER_D3D_MANAGER = str_to_guid("EC822DA2-E1E9-4B29-A0D8-563C719F5269")
MF_READWRITE_ENABLE_HARDWARE_TRANSFORMS = str_to_guid("A634A91C-822B-41B9-A494-4DE4643612B0")
MF_SOURCE_READER_ENABLE_ADVANCED_VIDEO_PROCESSING = str_to_guid("0F81DA2C-B537-4672-A8B2-A681B17307A3")
MF_MT_MAJOR_TYPE = str_to_guid("48eba18e-f827-49ed-96d5-241517452d3a")
MF_MT_SUBTYPE    = str_to_guid("f7e34c9a-42e8-4714-b74b-cb29d72c35e5")
MFMediaType_Video= str_to_guid("73646976-0000-0010-8000-00aa00389b71")
MFVideoFormat_NV12 = str_to_guid("3231564E-0000-0010-8000-00AA00389B71")
MFVideoFormat_P010 = str_to_guid("30313050-0000-0010-8000-00AA00389B71")
MF_SOURCE_READER_ALL_STREAMS = 0xFFFFFFFE
MF_SOURCE_READER_FIRST_VIDEO_STREAM = 0xFFFFFFFC

def vcall(ptr, slot, restype, *argtypes):
    vtbl = ctypes.cast(ptr, ctypes.POINTER(ctypes.c_void_p))[0]
    fn_ptr = ctypes.cast(vtbl, ctypes.POINTER(ctypes.c_void_p))[slot]
    return ctypes.WINFUNCTYPE(restype, ctypes.c_void_p, *argtypes)(fn_ptr)

def vt(punk, slot, restype, argtypes, *args):
    vt_ptr = ctypes.cast(punk, ctypes.POINTER(ctypes.c_void_p)).contents.value
    fn_ptr = ctypes.cast(vt_ptr + slot * 8, ctypes.POINTER(ctypes.c_void_p)).contents.value
    full_argtypes = [ctypes.c_void_p] + list(argtypes)
    proto = ctypes.WINFUNCTYPE(restype, *full_argtypes)
    return proto(fn_ptr)(punk, *args)

# ── D3D11 Structures ─────────────────────────────────────────────────────────

class DXGI_ADAPTER_DESC(ctypes.Structure):
    _fields_ = [
        ('Description', wintypes.WCHAR * 128),
        ('VendorId', wintypes.UINT),
        ('DeviceId', wintypes.UINT),
        ('SubSysId', wintypes.UINT),
        ('Revision', wintypes.UINT),
        ('DedicatedVideoMemory', ctypes.c_size_t),
        ('DedicatedSystemMemory', ctypes.c_size_t),
        ('SharedSystemMemory', ctypes.c_size_t),
        ('AdapterLuid_LowPart', wintypes.DWORD),
        ('AdapterLuid_HighPart', wintypes.LONG),
    ]

class DXGI_QUERY_VIDEO_MEMORY_INFO(ctypes.Structure):
    _fields_ = [
        ('Budget', ctypes.c_uint64),
        ('CurrentUsage', ctypes.c_uint64),
        ('AvailableForReservation', ctypes.c_uint64),
        ('CurrentReservation', ctypes.c_uint64)
    ]

class D3D11_TEXTURE2D_DESC(ctypes.Structure):
    _fields_ = [
        ('Width', wintypes.UINT),
        ('Height', wintypes.UINT),
        ('MipLevels', wintypes.UINT),
        ('ArraySize', wintypes.UINT),
        ('Format', wintypes.UINT),
        ('SampleDesc_Count', wintypes.UINT),
        ('SampleDesc_Quality', wintypes.UINT),
        ('Usage', wintypes.UINT),
        ('BindFlags', wintypes.UINT),
        ('CPUAccessFlags', wintypes.UINT),
        ('MiscFlags', wintypes.UINT)
    ]

class D2D1_PIXEL_FORMAT(ctypes.Structure):
    _fields_ = [('format', wintypes.UINT), ('alphaMode', wintypes.UINT)]

class D2D1_BITMAP_PROPERTIES1(ctypes.Structure):
    _fields_ = [
        ('pixelFormat', D2D1_PIXEL_FORMAT),
        ('dpiX', ctypes.c_float),
        ('dpiY', ctypes.c_float),
        ('bitmapOptions', wintypes.UINT),
        ('colorContext', ctypes.c_void_p)
    ]

class D2D1_COLOR_F(ctypes.Structure):
    _fields_ = [('r', ctypes.c_float), ('g', ctypes.c_float), ('b', ctypes.c_float), ('a', ctypes.c_float)]

class D2D1_RECT_F(ctypes.Structure):
    _fields_ = [('left', ctypes.c_float), ('top', ctypes.c_float), ('right', ctypes.c_float), ('bottom', ctypes.c_float)]

class D2D1_POINT_2F(ctypes.Structure):
    _fields_ = [('x', ctypes.c_float), ('y', ctypes.c_float)]

class D2D1_ROUNDED_RECT(ctypes.Structure):
    _fields_ = [('rect', D2D1_RECT_F), ('radiusX', ctypes.c_float), ('radiusY', ctypes.c_float)]

class D2D1_ELLIPSE(ctypes.Structure):
    _fields_ = [('point', D2D1_POINT_2F), ('radiusX', ctypes.c_float), ('radiusY', ctypes.c_float)]

class DXGI_RATIONAL(ctypes.Structure):
    _fields_ = [('Numerator', wintypes.UINT), ('Denominator', wintypes.UINT)]

class D3D11_VIDEO_PROCESSOR_CONTENT_DESC(ctypes.Structure):
    _fields_ = [
        ('InputFrameFormat', wintypes.UINT),
        ('InputFrameRate', DXGI_RATIONAL),
        ('InputWidth', wintypes.UINT),
        ('InputHeight', wintypes.UINT),
        ('OutputFrameRate', DXGI_RATIONAL),
        ('OutputWidth', wintypes.UINT),
        ('OutputHeight', wintypes.UINT),
        ('Usage', wintypes.UINT)
    ]

class D3D11_VIDEO_PROCESSOR_INPUT_VIEW_DESC(ctypes.Structure):
    _fields_ = [
        ('FourCC', wintypes.UINT),
        ('ViewDimension', wintypes.UINT),
        ('MipSlice', wintypes.UINT),
        ('ArraySlice', wintypes.UINT)
    ]

class D3D11_VIDEO_PROCESSOR_OUTPUT_VIEW_DESC(ctypes.Structure):
    _fields_ = [
        ('ViewDimension', wintypes.UINT),
        ('MipSlice', wintypes.UINT),
        ('ArraySlice', wintypes.UINT)
    ]

class D3D11_VIDEO_PROCESSOR_STREAM(ctypes.Structure):
    _fields_ = [
        ('Enable', wintypes.BOOL),
        ('OutputIndex', wintypes.UINT),
        ('InputFrameOrField', wintypes.UINT),
        ('PastFrames', wintypes.UINT),
        ('FutureFrames', wintypes.UINT),
        ('ppPastSurfaces', ctypes.c_void_p),
        ('pInputSurface', ctypes.c_void_p),
        ('ppFutureSurfaces', ctypes.c_void_p),
        ('ppPastSurfacesRight', ctypes.c_void_p),
        ('pInputSurfaceRight', ctypes.c_void_p),
        ('ppFutureSurfacesRight', ctypes.c_void_p)
    ]

# ── Telemetry Precomputation ─────────────────────────────────────────────────

class FrameState(NamedTuple):
    frame_idx: int
    t_sec: float
    speed_kmh: float
    heart_rate_bpm: float
    time_str: str
    speed_str: str
    hr_str: str

class TelemetryProvider:
    def __init__(self, fit_path: str, total_frames: int = 5395, fps_num: int = 30000, fps_den: int = 1001):
        self.fit_path = fit_path
        self.total_frames = total_frames
        self.fps = fps_num / fps_den
        self.frame_states: List[FrameState] = []

    def precompute(self):
        print(f"[TELEMETRY] Precomputing frame state for {self.total_frames} frames from {self.fit_path}...")
        t0 = time.perf_counter()
        from src.gui.telemetry_manager import TelemetryDataManager
        from src.telemetry_extract import interpolate_speed, interpolate_value

        tdm = TelemetryDataManager()
        tdm.load_fit(video_path="Video/GX030120.MP4", manual_path=Path(self.fit_path))

        speed_samples = tdm.fit_data.get('speed', [])
        hr_samples = tdm.fit_data.get('heart_rate', [])
        if not speed_samples or not hr_samples:
            raise RuntimeError("Failed to extract speed or heart_rate from FIT file")

        start_dt = speed_samples[0][0]

        for f in range(self.total_frames):
            t_sec = f / self.fps
            curr_dt = start_dt + timedelta(seconds=t_sec)
            spd = interpolate_speed(speed_samples, curr_dt)
            hr = interpolate_value(hr_samples, curr_dt)
            if hr is None:
                hr = hr_samples[0][1]

            m = int(t_sec // 60)
            s = int(t_sec % 60)
            tenth = int((t_sec % 1) * 10)
            time_str = f"{m:02d}:{s:02d}.{tenth:01d}"
            speed_str = f"{spd:.1f}"
            hr_str = f"{int(round(hr))}"

            self.frame_states.append(FrameState(
                frame_idx=f,
                t_sec=t_sec,
                speed_kmh=spd,
                heart_rate_bpm=hr,
                time_str=time_str,
                speed_str=speed_str,
                hr_str=hr_str
            ))

        t1 = time.perf_counter()
        print(f"[TELEMETRY] Precomputation complete in {(t1 - t0)*1000.0:.2f} ms. "
              f"First: frame 0 -> time={self.frame_states[0].time_str}, spd={self.frame_states[0].speed_str} km/h, hr={self.frame_states[0].hr_str} bpm; "
              f"Last: frame {self.total_frames-1} -> time={self.frame_states[-1].time_str}, spd={self.frame_states[-1].speed_str} km/h, hr={self.frame_states[-1].hr_str} bpm.")

    def get(self, frame_idx: int) -> FrameState:
        if frame_idx < len(self.frame_states):
            return self.frame_states[frame_idx]
        return self.frame_states[-1]

# ── Media Foundation Hardware Decoder ────────────────────────────────────────

class MediaFoundationDecoder:
    def __init__(self, pDevice: ctypes.c_void_p, video_path: str, pVPEnum: ctypes.c_void_p, pVideoDevice: ctypes.c_void_p):
        self.pDevice = pDevice
        self.video_path = video_path
        self.pVPEnum = pVPEnum
        self.pVideoDevice = pVideoDevice

        self.pDevMgr = None
        self.pAttributes = None
        self.pReader = None
        self.view_cache: Dict[Tuple[int, int], ctypes.c_void_p] = {}
        self.current_frame = 0
        self.eof = False

    def open(self):
        # Enable Multithread on pDevice
        pMultithread = ctypes.c_void_p()
        vt(self.pDevice, 0, ctypes.c_long, [ctypes.c_void_p, ctypes.c_void_p], ctypes.byref(IID_ID3D11Multithread), ctypes.byref(pMultithread))
        vt(pMultithread.value, 5, ctypes.c_int, [ctypes.c_int], 1)
        vt(pMultithread.value, 2, ctypes.c_ulong, [])

        # Create DXGI Device Manager
        resetToken = ctypes.c_uint()
        pDevMgr = ctypes.c_void_p()
        hr = mfplat.MFCreateDXGIDeviceManager(ctypes.byref(resetToken), ctypes.byref(pDevMgr))
        if hr != 0: raise RuntimeError(f"MFCreateDXGIDeviceManager failed: {hr:#x}")
        hr = vt(pDevMgr.value, 7, ctypes.c_long, [ctypes.c_void_p, ctypes.c_uint], self.pDevice, resetToken.value)
        if hr != 0: raise RuntimeError(f"ResetDevice failed: {hr:#x}")
        self.pDevMgr = pDevMgr

        # Attributes
        pAttributes = ctypes.c_void_p()
        hr = mfplat.MFCreateAttributes(ctypes.byref(pAttributes), ctypes.c_uint32(4))
        if hr != 0: raise RuntimeError(f"MFCreateAttributes failed: {hr:#x}")
        vt(pAttributes.value, 27, ctypes.c_long, [ctypes.c_void_p, ctypes.c_void_p], ctypes.byref(MF_SOURCE_READER_D3D_MANAGER), self.pDevMgr.value)
        vt(pAttributes.value, 21, ctypes.c_long, [ctypes.c_void_p, ctypes.c_uint32], ctypes.byref(MF_READWRITE_ENABLE_HARDWARE_TRANSFORMS), 1)
        vt(pAttributes.value, 21, ctypes.c_long, [ctypes.c_void_p, ctypes.c_uint32], ctypes.byref(MF_SOURCE_READER_ENABLE_ADVANCED_VIDEO_PROCESSING), 1)
        self.pAttributes = pAttributes

        # Create Source Reader
        pReader = ctypes.c_void_p()
        mfreadwrite.MFCreateSourceReaderFromURL.argtypes = [ctypes.c_wchar_p, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
        mfreadwrite.MFCreateSourceReaderFromURL.restype = ctypes.c_long
        hr = mfreadwrite.MFCreateSourceReaderFromURL(self.video_path, self.pAttributes.value, ctypes.byref(pReader))
        if hr != 0: raise RuntimeError(f"MFCreateSourceReaderFromURL failed: {hr:#x}")
        self.pReader = pReader

        # Stream Selection
        vt(self.pReader.value, 4, ctypes.c_long, [ctypes.c_uint32, ctypes.c_int], MF_SOURCE_READER_ALL_STREAMS, 0)
        vt(self.pReader.value, 4, ctypes.c_long, [ctypes.c_uint32, ctypes.c_int], MF_SOURCE_READER_FIRST_VIDEO_STREAM, 1)

        # Clone native media type and configure P010 output
        pNativeMT = ctypes.c_void_p()
        hr = vt(self.pReader.value, 5, ctypes.c_long, [ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p], MF_SOURCE_READER_FIRST_VIDEO_STREAM, 0, ctypes.byref(pNativeMT))
        if hr != 0: raise RuntimeError(f"GetNativeMediaType failed: {hr:#x}")

        pDecMT = ctypes.c_void_p()
        mfplat.MFCreateMediaType.argtypes = [ctypes.POINTER(ctypes.c_void_p)]
        mfplat.MFCreateMediaType.restype = ctypes.c_long
        mfplat.MFCreateMediaType(ctypes.byref(pDecMT))
        vt(pNativeMT.value, 32, ctypes.c_long, [ctypes.c_void_p], pDecMT.value)
        vt(pNativeMT.value, 2, ctypes.c_ulong, [])
        vt(pDecMT.value, 24, ctypes.c_long, [ctypes.c_void_p, ctypes.c_void_p], ctypes.byref(MF_MT_SUBTYPE), ctypes.byref(MFVideoFormat_P010))

        hr = vt(self.pReader.value, 7, ctypes.c_long, [ctypes.c_uint32, ctypes.c_void_p, ctypes.c_void_p], MF_SOURCE_READER_FIRST_VIDEO_STREAM, None, pDecMT.value)
        vt(pDecMT.value, 2, ctypes.c_ulong, [])
        if hr != 0: raise RuntimeError(f"SetCurrentMediaType(P010) failed: {hr:#x}")

        print("[DECODER] Hardware D3D11VA SourceReader initialized with format P010 (10-bit).")

    def read_frame_input_view(self) -> Tuple[Optional[ctypes.c_void_p], int, int]:
        """Reads a hardware decoded frame. Returns (pVideoInView, timestamp_100ns, sample_flags).
        Releases all intermediate IMFSample/IMFMediaBuffer COM objects while retaining cached view.
        """
        if self.eof or not self.pReader:
            return None, 0, 1

        actualStreamIndex = ctypes.c_uint32()
        streamFlags = ctypes.c_uint32()
        timestamp = ctypes.c_int64()
        pSample = ctypes.c_void_p()

        hr = vt(self.pReader.value, 9, ctypes.c_long,
                [ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p],
                MF_SOURCE_READER_FIRST_VIDEO_STREAM, 0,
                ctypes.byref(actualStreamIndex), ctypes.byref(streamFlags), ctypes.byref(timestamp), ctypes.byref(pSample))

        if hr != 0 or (streamFlags.value & 1):
            self.eof = True
            if pSample.value: vt(pSample.value, 2, ctypes.c_ulong, [])
            return None, 0, streamFlags.value

        if not pSample.value:
            return None, timestamp.value, streamFlags.value

        # Extract D3D11 Texture2D via IMFDXGIBuffer
        pBuffer = ctypes.c_void_p()
        vt(pSample.value, 40, ctypes.c_long, [ctypes.c_uint32, ctypes.c_void_p], 0, ctypes.byref(pBuffer))
        pDXGIBuffer = ctypes.c_void_p()
        vt(pBuffer.value, 0, ctypes.c_long, [ctypes.c_void_p, ctypes.c_void_p], ctypes.byref(IID_IMFDXGIBuffer), ctypes.byref(pDXGIBuffer))

        pVideoTexture = ctypes.c_void_p()
        subres = ctypes.c_uint()
        vt(pDXGIBuffer.value, 3, ctypes.c_long, [ctypes.c_void_p, ctypes.c_void_p], ctypes.byref(IID_ID3D11Texture2D), ctypes.byref(pVideoTexture))
        vt(pDXGIBuffer.value, 4, ctypes.c_long, [ctypes.c_void_p], ctypes.byref(subres))

        key = (pVideoTexture.value, subres.value)
        if key not in self.view_cache:
            in_desc = D3D11_VIDEO_PROCESSOR_INPUT_VIEW_DESC(0, 1, 0, subres.value)
            pVideoInView = ctypes.c_void_p()
            hr_v = vt(self.pVideoDevice, 8, ctypes.c_long, [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p],
                      pVideoTexture.value, self.pVPEnum, ctypes.byref(in_desc), ctypes.byref(pVideoInView))
            if hr_v != 0:
                raise RuntimeError(f"CreateVideoProcessorInputView failed: {hr_v:#x}")
            self.view_cache[key] = pVideoInView
        else:
            pVideoInView = self.view_cache[key]

        # Release intermediate COM objects
        vt(pVideoTexture.value, 2, ctypes.c_ulong, [])
        vt(pDXGIBuffer.value, 2, ctypes.c_ulong, [])
        vt(pBuffer.value, 2, ctypes.c_ulong, [])
        vt(pSample.value, 2, ctypes.c_ulong, [])

        self.current_frame += 1
        return pVideoInView, timestamp.value, streamFlags.value

    def close(self):
        for v in self.view_cache.values():
            if v and v.value:
                vt(v.value, 2, ctypes.c_ulong, [])
        self.view_cache.clear()

        if self.pReader and self.pReader.value:
            vt(self.pReader.value, 2, ctypes.c_ulong, [])
            self.pReader = None
        if self.pAttributes and self.pAttributes.value:
            vt(self.pAttributes.value, 2, ctypes.c_ulong, [])
            self.pAttributes = None
        if self.pDevMgr and self.pDevMgr.value:
            vt(self.pDevMgr.value, 2, ctypes.c_ulong, [])
            self.pDevMgr = None

# ── Pipeline Implementation ──────────────────────────────────────────────────

class NvidiaStage8EPipeline:
    def __init__(self, width=3840, height=2160, ring_size=4):
        self.width = width
        self.height = height
        self.ring_size = ring_size

        # DXGI & D3D11
        self.pFactory = None
        self.pAdapter = None
        self.pAdapter3 = None
        self.adapter_desc = None
        self.pDevice = None
        self.pContext = None
        self.pInfoQueue = None

        # Direct2D & DirectWrite
        self.pHudTexture = None
        self.pD2DDevice = None
        self.pD2DContext = None
        self.pD2DBitmapTarget = None
        self.pDWriteFactory = None
        self.text_formats = {}
        self.brushes = {}

        # D3D11 Video Processor
        self.pVideoDevice = None
        self.pVideoContext = None
        self.pVPEnum = None
        self.pVP = None
        self.pVPInViewHUD = None

        # Ring Resources
        self.ring_nv12_textures = []
        self.ring_vp_out_views = []
        self.ring_registered_handles = []
        self.ring_bitstream_buffers = []

        # NVENC SDK 13.1
        self.header = NvEncodeAPIHeader()
        self.nvenc_dll = ctypes.windll.LoadLibrary("nvEncodeAPI64.dll")
        self.fn_list = NV_ENCODE_API_FUNCTION_LIST()
        self.fn_map = {}
        self.hEncoder = None
        self.preset_cfg = None

        # Telemetry & Decoder
        self.telemetry: Optional[TelemetryProvider] = None
        self.decoder: Optional[MediaFoundationDecoder] = None

    def initialize(self):
        print("=" * 80)
        print("STAGE 8E: INITIALIZING REAL VIDEO + REAL TELEMETRY ZERO-COPY PIPELINE")
        print("=" * 80)

        ole32.CoInitializeEx(None, 0)
        mfplat.MFStartup(0x00020070, 0)

        self._select_adapter()
        self._create_device()
        self._create_hud_resources()
        self._create_dwrite()
        self._create_brushes()
        self._create_video_processor()
        self._create_ring_resources()

        print("\n[PIPELINE] Initialized successfully. Ring size:", self.ring_size)
        print("=" * 80)

    def _select_adapter(self):
        pFactory = ctypes.c_void_p()
        dxgi.CreateDXGIFactory1(ctypes.byref(str_to_guid("770aae78-f26f-4dba-a829-253c83d1b387")), ctypes.byref(pFactory))
        self.pFactory = pFactory

        pAdapter = ctypes.c_void_p()
        desc = DXGI_ADAPTER_DESC()
        idx = 0
        while True:
            hr = vcall(self.pFactory, 7, ctypes.c_int, wintypes.UINT, ctypes.POINTER(ctypes.c_void_p))(
                self.pFactory, idx, ctypes.byref(pAdapter)
            )
            if hr != 0: break
            vcall(pAdapter, 8, ctypes.c_int, ctypes.POINTER(DXGI_ADAPTER_DESC))(pAdapter, ctypes.byref(desc))
            if desc.VendorId == 0x10DE:
                self.pAdapter = pAdapter
                self.adapter_desc = desc
                break
            vcall(pAdapter, 2, ctypes.c_ulong)(pAdapter)
            idx += 1

        if not self.pAdapter:
            raise RuntimeError("NVIDIA GPU adapter not found!")

        # QI IDXGIAdapter3
        pAdapter3 = ctypes.c_void_p()
        hr_a3 = vcall(self.pAdapter, 0, ctypes.c_int, ctypes.c_char_p, ctypes.POINTER(ctypes.c_void_p))(
            self.pAdapter, bytes(IID_IDXGIAdapter3), ctypes.byref(pAdapter3)
        )
        if hr_a3 == 0:
            self.pAdapter3 = pAdapter3

        print(f"Selected Adapter: {self.adapter_desc.Description} (Vendor 0x{self.adapter_desc.VendorId:X}, Device 0x{self.adapter_desc.DeviceId:X})")
        print(f"  Dedicated VRAM: {self.adapter_desc.DedicatedVideoMemory // (1024*1024)} MiB")

    def query_vram_info(self) -> Dict[str, float]:
        if not self.pAdapter3:
            return {"budget_mib": 0.0, "current_usage_mib": 0.0, "available_mib": 0.0}
        mem = DXGI_QUERY_VIDEO_MEMORY_INFO()
        # QueryVideoMemoryInfo is slot 14 of IDXGIAdapter3
        hr = vcall(self.pAdapter3, 14, ctypes.c_int, wintypes.UINT, wintypes.UINT, ctypes.POINTER(DXGI_QUERY_VIDEO_MEMORY_INFO))(
            self.pAdapter3, 0, 0, ctypes.byref(mem)
        )
        if hr == 0:
            return {
                "budget_mib": mem.Budget / (1024.0 * 1024.0),
                "current_usage_mib": mem.CurrentUsage / (1024.0 * 1024.0),
                "available_mib": mem.AvailableForReservation / (1024.0 * 1024.0)
            }
        return {"budget_mib": 0.0, "current_usage_mib": 0.0, "available_mib": 0.0}

    def _create_device(self):
        pDev = ctypes.c_void_p()
        pCtx = ctypes.c_void_p()
        fl = ctypes.c_uint()
        flags = 0x20 # BGRA
        try:
            hr = d3d11.D3D11CreateDevice(
                self.pAdapter, 0, None, flags | 0x02, (ctypes.c_uint * 2)(0xb100, 0xb000), 2, 7,
                ctypes.byref(pDev), ctypes.byref(fl), ctypes.byref(pCtx)
            )
            if hr == 0:
                print("D3D11 Debug Layer active.")
        except Exception:
            hr = -1

        if hr != 0:
            hr = d3d11.D3D11CreateDevice(
                self.pAdapter, 0, None, flags, (ctypes.c_uint * 2)(0xb100, 0xb000), 2, 7,
                ctypes.byref(pDev), ctypes.byref(fl), ctypes.byref(pCtx)
            )
        if hr != 0:
            raise RuntimeError(f"D3D11CreateDevice failed: {hr:#x}")

        self.pDevice = pDev
        self.pContext = pCtx

        # Multithread protection
        pMultithread = ctypes.c_void_p()
        hr_mt = vcall(self.pDevice, 0, ctypes.c_int, ctypes.c_char_p, ctypes.POINTER(ctypes.c_void_p))(
            self.pDevice, bytes(IID_ID3D11Multithread), ctypes.byref(pMultithread)
        )
        if hr_mt == 0:
            vcall(pMultithread, 5, ctypes.c_int, ctypes.c_int)(pMultithread, 1)
            vcall(pMultithread, 2, ctypes.c_ulong)(pMultithread)

    def _create_hud_resources(self):
        desc = D3D11_TEXTURE2D_DESC()
        desc.Width = self.width
        desc.Height = self.height
        desc.MipLevels = 1
        desc.ArraySize = 1
        desc.Format = 87 # DXGI_FORMAT_B8G8R8A8_UNORM
        desc.SampleDesc_Count = 1
        desc.SampleDesc_Quality = 0
        desc.Usage = 0
        desc.BindFlags = 0x20 | 0x08 # RENDER_TARGET | SHADER_RESOURCE
        desc.CPUAccessFlags = 0
        desc.MiscFlags = 0

        pTex = ctypes.c_void_p()
        hr = vcall(self.pDevice, 5, ctypes.c_int, ctypes.POINTER(D3D11_TEXTURE2D_DESC), ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p))(
            self.pDevice, ctypes.byref(desc), None, ctypes.byref(pTex)
        )
        if hr != 0: raise RuntimeError(f"CreateTexture2D HUD failed: {hr:#x}")
        self.pHudTexture = pTex

        # D2D setup
        pDxgiDevice = ctypes.c_void_p()
        hr = vcall(self.pDevice, 0, ctypes.c_int, ctypes.c_char_p, ctypes.POINTER(ctypes.c_void_p))(
            self.pDevice, bytes(IID_IDXGIDevice), ctypes.byref(pDxgiDevice)
        )
        if hr != 0: raise RuntimeError(f"QI IDXGIDevice failed: {hr:#x}")

        pD2DDevice = ctypes.c_void_p()
        d2d1.D2D1CreateDevice.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
        d2d1.D2D1CreateDevice.restype = ctypes.c_int32
        hr = d2d1.D2D1CreateDevice(pDxgiDevice, None, ctypes.byref(pD2DDevice))
        if hr != 0: raise RuntimeError(f"D2D1CreateDevice failed: {hr:#x}")
        self.pD2DDevice = pD2DDevice

        pD2DContext = ctypes.c_void_p()
        hr = vcall(self.pD2DDevice, 4, ctypes.c_int32, ctypes.c_uint32, ctypes.POINTER(ctypes.c_void_p))(
            self.pD2DDevice, 0, ctypes.byref(pD2DContext)
        )
        if hr != 0: raise RuntimeError(f"CreateDeviceContext failed: {hr:#x}")
        self.pD2DContext = pD2DContext

        pSurf = ctypes.c_void_p()
        hr = vcall(self.pHudTexture, 0, ctypes.c_int32, ctypes.c_char_p, ctypes.POINTER(ctypes.c_void_p))(
            self.pHudTexture, bytes(IID_IDXGISurface1), ctypes.byref(pSurf)
        )
        if hr != 0: raise RuntimeError(f"QI IDXGISurface1 failed: {hr:#x}")

        bp = D2D1_BITMAP_PROPERTIES1(D2D1_PIXEL_FORMAT(87, 1), 96.0, 96.0, 1, None)
        pBitmap = ctypes.c_void_p()
        hr = vcall(self.pD2DContext, 62, ctypes.c_int32, ctypes.c_void_p, ctypes.POINTER(D2D1_BITMAP_PROPERTIES1), ctypes.POINTER(ctypes.c_void_p))(
            self.pD2DContext, pSurf, ctypes.byref(bp), ctypes.byref(pBitmap)
        )
        if hr != 0: raise RuntimeError(f"CreateBitmapFromDxgiSurface failed: {hr:#x}")
        self.pD2DBitmapTarget = pBitmap

        vcall(self.pD2DContext, 74, None, ctypes.c_void_p)(self.pD2DContext, self.pD2DBitmapTarget)
        vcall(self.pD2DContext, 32, None, ctypes.c_int)(self.pD2DContext, 0)
        vcall(self.pD2DContext, 34, None, ctypes.c_int)(self.pD2DContext, 2) # GRAYSCALE

    def _create_dwrite(self):
        pDWriteFactory = ctypes.c_void_p()
        dwrite.DWriteCreateFactory.argtypes = [ctypes.c_int, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
        dwrite.DWriteCreateFactory.restype = ctypes.c_int32
        hr = dwrite.DWriteCreateFactory(0, bytes(IID_IDWriteFactory), ctypes.byref(pDWriteFactory))
        if hr != 0: raise RuntimeError(f"DWriteCreateFactory failed: {hr:#x}")
        self.pDWriteFactory = pDWriteFactory

        def create_fmt(family, weight, size):
            pFmt = ctypes.c_void_p()
            hr_fmt = vcall(self.pDWriteFactory, 15, ctypes.c_int32,
                ctypes.c_wchar_p, ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                ctypes.c_float, ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_void_p)
            )(self.pDWriteFactory, family, None, weight, 0, 5, size, 'en-us', ctypes.byref(pFmt))
            if hr_fmt != 0: raise RuntimeError(f"CreateTextFormat failed: {hr_fmt:#x}")
            return pFmt

        self.text_formats['time'] = create_fmt('Segoe UI', 700, 68.0)
        self.text_formats['speed_val'] = create_fmt('Segoe UI', 700, 112.0)
        self.text_formats['speed_unit'] = create_fmt('Segoe UI', 600, 36.0)
        self.text_formats['hr_val'] = create_fmt('Segoe UI', 700, 112.0)
        self.text_formats['hr_unit'] = create_fmt('Segoe UI', 600, 36.0)
        self.text_formats['label'] = create_fmt('Segoe UI', 600, 26.0)

    def _create_brushes(self):
        def make_brush(r, g, b, a):
            col = D2D1_COLOR_F(r, g, b, a)
            pB = ctypes.c_void_p()
            hr = vcall(self.pD2DContext, 8, ctypes.c_int32, ctypes.POINTER(D2D1_COLOR_F), ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p))(
                self.pD2DContext, ctypes.byref(col), None, ctypes.byref(pB)
            )
            if hr != 0: raise RuntimeError(f"CreateSolidColorBrush failed: {hr:#x}")
            return pB

        self.brushes['white'] = make_brush(1.0, 1.0, 1.0, 1.0)
        self.brushes['text_muted'] = make_brush(0.75, 0.82, 0.90, 0.90)
        self.brushes['cyan'] = make_brush(0.0, 0.88, 1.0, 1.0)
        self.brushes['coral'] = make_brush(1.0, 0.32, 0.32, 1.0)
        self.brushes['card_bg'] = make_brush(0.04, 0.06, 0.10, 0.68)
        self.brushes['card_border'] = make_brush(0.25, 0.35, 0.50, 0.60)

    def _create_video_processor(self):
        pVD = ctypes.c_void_p()
        hr = vcall(self.pDevice, 0, ctypes.c_int, ctypes.c_char_p, ctypes.POINTER(ctypes.c_void_p))(
            self.pDevice, bytes(IID_ID3D11VideoDevice), ctypes.byref(pVD)
        )
        if hr != 0: raise RuntimeError(f"QI ID3D11VideoDevice failed: {hr:#x}")
        self.pVideoDevice = pVD

        pVC = ctypes.c_void_p()
        hr = vcall(self.pContext, 0, ctypes.c_int, ctypes.c_char_p, ctypes.POINTER(ctypes.c_void_p))(
            self.pContext, bytes(IID_ID3D11VideoContext), ctypes.byref(pVC)
        )
        if hr != 0: raise RuntimeError(f"QI ID3D11VideoContext failed: {hr:#x}")
        self.pVideoContext = pVC

        vp_desc = D3D11_VIDEO_PROCESSOR_CONTENT_DESC()
        vp_desc.InputFrameFormat = 0
        vp_desc.InputFrameRate.Numerator = 30000
        vp_desc.InputFrameRate.Denominator = 1001
        vp_desc.InputWidth = self.width
        vp_desc.InputHeight = self.height
        vp_desc.OutputFrameRate.Numerator = 30000
        vp_desc.OutputFrameRate.Denominator = 1001
        vp_desc.OutputWidth = self.width
        vp_desc.OutputHeight = self.height
        vp_desc.Usage = 0

        pEnum = ctypes.c_void_p()
        hr = vcall(self.pVideoDevice, 10, ctypes.c_int, ctypes.POINTER(D3D11_VIDEO_PROCESSOR_CONTENT_DESC), ctypes.POINTER(ctypes.c_void_p))(
            self.pVideoDevice, ctypes.byref(vp_desc), ctypes.byref(pEnum)
        )
        if hr != 0: raise RuntimeError(f"CreateVideoProcessorEnumerator failed: {hr:#x}")
        self.pVPEnum = pEnum

        pVP = ctypes.c_void_p()
        hr = vcall(self.pVideoDevice, 4, ctypes.c_int, ctypes.c_void_p, wintypes.UINT, ctypes.POINTER(ctypes.c_void_p))(
            self.pVideoDevice, self.pVPEnum, 0, ctypes.byref(pVP)
        )
        if hr != 0: raise RuntimeError(f"CreateVideoProcessor failed: {hr:#x}")
        self.pVP = pVP

        # Create input view for HUD texture
        in_desc = D3D11_VIDEO_PROCESSOR_INPUT_VIEW_DESC(0, 1, 0, 0)
        pInView = ctypes.c_void_p()
        hr = vcall(self.pVideoDevice, 8, ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(D3D11_VIDEO_PROCESSOR_INPUT_VIEW_DESC), ctypes.POINTER(ctypes.c_void_p))(
            self.pVideoDevice, self.pHudTexture, self.pVPEnum, ctypes.byref(in_desc), ctypes.byref(pInView)
        )
        if hr != 0: raise RuntimeError(f"CreateVideoProcessorInputView HUD failed: {hr:#x}")
        self.pVPInViewHUD = pInView

        # Configure Stream 1 Alpha blending on VideoProcessor (slot 32)
        vcall(self.pVideoContext, 32, None, ctypes.c_void_p, wintypes.UINT, wintypes.BOOL, ctypes.c_float)(
            self.pVideoContext, self.pVP, 1, True, 1.0
        )

    def _create_ring_resources(self):
        desc = D3D11_TEXTURE2D_DESC()
        desc.Width = self.width
        desc.Height = self.height
        desc.MipLevels = 1
        desc.ArraySize = 1
        desc.Format = 103 # DXGI_FORMAT_NV12
        desc.SampleDesc_Count = 1
        desc.SampleDesc_Quality = 0
        desc.Usage = 0
        desc.BindFlags = 0x20 | 0x08 # RENDER_TARGET | SHADER_RESOURCE
        desc.CPUAccessFlags = 0
        desc.MiscFlags = 0

        out_desc = D3D11_VIDEO_PROCESSOR_OUTPUT_VIEW_DESC(1, 0, 0)

        for i in range(self.ring_size):
            pTex = ctypes.c_void_p()
            hr = vcall(self.pDevice, 5, ctypes.c_int, ctypes.POINTER(D3D11_TEXTURE2D_DESC), ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p))(
                self.pDevice, ctypes.byref(desc), None, ctypes.byref(pTex)
            )
            if hr != 0: raise RuntimeError(f"CreateTexture2D NV12 failed: {hr:#x}")
            self.ring_nv12_textures.append(pTex)

            pOutView = ctypes.c_void_p()
            hr = vcall(self.pVideoDevice, 9, ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(D3D11_VIDEO_PROCESSOR_OUTPUT_VIEW_DESC), ctypes.POINTER(ctypes.c_void_p))(
                self.pVideoDevice, pTex, self.pVPEnum, ctypes.byref(out_desc), ctypes.byref(pOutView)
            )
            if hr != 0: raise RuntimeError(f"CreateVideoProcessorOutputView failed: {hr:#x}")
            self.ring_vp_out_views.append(pOutView)

        print(f"Created {self.ring_size} persistent D3D11 NV12 textures and VideoProcessor views.")

    def _create_nvenc_session(self):
        self.fn_list.version = self.header.ver_defines['NV_ENCODE_API_FUNCTION_LIST_VER']
        pfn_create = self.nvenc_dll.NvEncodeAPICreateInstance
        pfn_create.argtypes = [ctypes.POINTER(NV_ENCODE_API_FUNCTION_LIST)]
        pfn_create.restype = ctypes.c_int
        hr = pfn_create(ctypes.byref(self.fn_list))
        if hr != 0: raise RuntimeError(f"NvEncodeAPICreateInstance failed: {hr:#x}")

        for i, (ftype, fname) in enumerate(self.header.fn_names[2:45]):
            self.fn_map[fname] = self.fn_list.ptrs[i]

        pfn_open_session = ctypes.WINFUNCTYPE(
            ctypes.c_int,
            ctypes.POINTER(NV_ENC_OPEN_ENCODE_SESSION_EX_PARAMS),
            ctypes.POINTER(ctypes.c_void_p)
        )(self.fn_map['nvEncOpenEncodeSessionEx'])

        session_params = NV_ENC_OPEN_ENCODE_SESSION_EX_PARAMS()
        session_params.version = self.header.ver_defines['NV_ENC_OPEN_ENCODE_SESSION_EX_PARAMS_VER']
        session_params.deviceType = 0
        session_params.device = self.pDevice
        session_params.apiVersion = self.header.api_version

        hEncoder = ctypes.c_void_p()
        hr = pfn_open_session(ctypes.byref(session_params), ctypes.byref(hEncoder))
        if hr != 0: raise RuntimeError(f"nvEncOpenEncodeSessionEx failed: {hr:#x}")
        self.hEncoder = hEncoder
        print(f"NVENC session opened on SAME D3D11 DEVICE: hEncoder={self.hEncoder.value:#x}")

        # Get Preset Config Ex for HEVC + P1 + HIGH_QUALITY
        self.preset_cfg = NV_ENC_PRESET_CONFIG_BUFFER()
        self.preset_cfg.version = self.header.ver_defines['NV_ENC_PRESET_CONFIG_VER']
        self.preset_cfg.reserved = 0
        self.preset_cfg.cfg_version = self.header.ver_defines['NV_ENC_CONFIG_VER']

        pfn_preset_cfg_ex = ctypes.WINFUNCTYPE(
            ctypes.c_int,
            ctypes.c_void_p,
            GUID,
            GUID,
            ctypes.c_int,
            ctypes.POINTER(NV_ENC_PRESET_CONFIG_BUFFER)
        )(self.fn_map['nvEncGetEncodePresetConfigEx'])

        hr = pfn_preset_cfg_ex(
            self.hEncoder,
            self.header.guids['NV_ENC_CODEC_HEVC_GUID'],
            self.header.guids['NV_ENC_PRESET_P1_GUID'],
            1, # NV_ENC_TUNING_INFO_HIGH_QUALITY
            ctypes.byref(self.preset_cfg)
        )
        if hr != 0:
            raise RuntimeError(f"nvEncGetEncodePresetConfigEx failed: {hr:#x}")
        print("nvEncGetEncodePresetConfigEx (HEVC + P1 + HIGH_QUALITY) SUCCESS.")

        # Initialize Encoder
        pfn_init_enc = ctypes.WINFUNCTYPE(
            ctypes.c_int,
            ctypes.c_void_p,
            ctypes.POINTER(NV_ENC_INITIALIZE_PARAMS)
        )(self.fn_map['nvEncInitializeEncoder'])

        init_params = NV_ENC_INITIALIZE_PARAMS()
        init_params.version = self.header.ver_defines['NV_ENC_INITIALIZE_PARAMS_VER']
        init_params.encodeGUID = self.header.guids['NV_ENC_CODEC_HEVC_GUID']
        init_params.presetGUID = self.header.guids['NV_ENC_PRESET_P1_GUID']
        init_params.encodeWidth = self.width
        init_params.encodeHeight = self.height
        init_params.darWidth = self.width
        init_params.darHeight = self.height
        init_params.frameRateNum = 30000
        init_params.frameRateDen = 1001
        init_params.enableEncodeAsync = 0
        init_params.enablePTD = 1
        init_params.tuningInfo = 1 # HIGH_QUALITY
        init_params.encodeConfig = ctypes.addressof(self.preset_cfg) + 8

        hr = pfn_init_enc(self.hEncoder, ctypes.byref(init_params))
        if hr != 0:
            pfn_err = ctypes.WINFUNCTYPE(ctypes.c_char_p, ctypes.c_void_p)(self.fn_map['nvEncGetLastErrorString'])
            raise RuntimeError(f"nvEncInitializeEncoder failed: {hr:#x} ({pfn_err(self.hEncoder)})")
        print("nvEncInitializeEncoder SUCCESS.")

    def _register_ring_resources(self):
        pfn_reg_res = ctypes.WINFUNCTYPE(
            ctypes.c_int, ctypes.c_void_p, ctypes.POINTER(NV_ENC_REGISTER_RESOURCE)
        )(self.fn_map['nvEncRegisterResource'])

        pfn_create_bs = ctypes.WINFUNCTYPE(
            ctypes.c_int, ctypes.c_void_p, ctypes.POINTER(NV_ENC_CREATE_BITSTREAM_BUFFER)
        )(self.fn_map['nvEncCreateBitstreamBuffer'])

        for i in range(self.ring_size):
            reg = NV_ENC_REGISTER_RESOURCE()
            reg.version = self.header.ver_defines['NV_ENC_REGISTER_RESOURCE_VER']
            reg.resourceType = 0
            reg.width = self.width
            reg.height = self.height
            reg.pitch = self.width
            reg.resourceToRegister = self.ring_nv12_textures[i]
            reg.bufferFormat = 1 # NV12
            reg.bufferUsage = 0
            hr = pfn_reg_res(self.hEncoder, ctypes.byref(reg))
            if hr != 0: raise RuntimeError(f"nvEncRegisterResource[{i}] failed: {hr:#x}")
            self.ring_registered_handles.append(reg.registeredResource)

            bs = NV_ENC_CREATE_BITSTREAM_BUFFER()
            bs.version = self.header.ver_defines['NV_ENC_CREATE_BITSTREAM_BUFFER_VER']
            hr = pfn_create_bs(self.hEncoder, ctypes.byref(bs))
            if hr != 0: raise RuntimeError(f"nvEncCreateBitstreamBuffer[{i}] failed: {hr:#x}")
            self.ring_bitstream_buffers.append(bs.bitstreamBuffer)

        print(f"Registered {self.ring_size} persistent NV12 textures and bitstream buffers with NVENC.")

    def start_encode_session(self):
        self._create_nvenc_session()
        self._register_ring_resources()

    def end_encode_session(self):
        if not self.hEncoder:
            return
        pfn_destroy_bs = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p)(self.fn_map['nvEncDestroyBitstreamBuffer'])
        pfn_unreg_res = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p)(self.fn_map['nvEncUnregisterResource'])
        pfn_destroy_enc = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_void_p)(self.fn_map['nvEncDestroyEncoder'])

        for bs_buf in self.ring_bitstream_buffers:
            pfn_destroy_bs(self.hEncoder, bs_buf)
        self.ring_bitstream_buffers.clear()

        for reg_h in self.ring_registered_handles:
            pfn_unreg_res(self.hEncoder, reg_h)
        self.ring_registered_handles.clear()

        pfn_destroy_enc(self.hEncoder)
        self.hEncoder = None
        print("NVENC session closed and ring resources unregistered.")

    def close(self):
        if self.decoder:
            self.decoder.close()
            self.decoder = None

        self.end_encode_session()

        for view in self.ring_vp_out_views:
            vcall(view, 2, ctypes.c_ulong)(view)
        self.ring_vp_out_views.clear()

        for tex in self.ring_nv12_textures:
            vcall(tex, 2, ctypes.c_ulong)(tex)
        self.ring_nv12_textures.clear()

        if self.pVPInViewHUD:
            vcall(self.pVPInViewHUD, 2, ctypes.c_ulong)(self.pVPInViewHUD)
            self.pVPInViewHUD = None
        if self.pVP:
            vcall(self.pVP, 2, ctypes.c_ulong)(self.pVP)
            self.pVP = None
        if self.pVPEnum:
            vcall(self.pVPEnum, 2, ctypes.c_ulong)(self.pVPEnum)
            self.pVPEnum = None
        if self.pVideoContext:
            vcall(self.pVideoContext, 2, ctypes.c_ulong)(self.pVideoContext)
            self.pVideoContext = None
        if self.pVideoDevice:
            vcall(self.pVideoDevice, 2, ctypes.c_ulong)(self.pVideoDevice)
            self.pVideoDevice = None

        for b in self.brushes.values():
            vcall(b, 2, ctypes.c_ulong)(b)
        self.brushes.clear()
        for f in self.text_formats.values():
            vcall(f, 2, ctypes.c_ulong)(f)
        self.text_formats.clear()

        if self.pDWriteFactory:
            vcall(self.pDWriteFactory, 2, ctypes.c_ulong)(self.pDWriteFactory)
            self.pDWriteFactory = None
        if self.pD2DBitmapTarget:
            vcall(self.pD2DBitmapTarget, 2, ctypes.c_ulong)(self.pD2DBitmapTarget)
            self.pD2DBitmapTarget = None
        if self.pD2DContext:
            vcall(self.pD2DContext, 2, ctypes.c_ulong)(self.pD2DContext)
            self.pD2DContext = None
        if self.pD2DDevice:
            vcall(self.pD2DDevice, 2, ctypes.c_ulong)(self.pD2DDevice)
            self.pD2DDevice = None
        if self.pHudTexture:
            vcall(self.pHudTexture, 2, ctypes.c_ulong)(self.pHudTexture)
            self.pHudTexture = None

        if self.pContext:
            vcall(self.pContext, 2, ctypes.c_ulong)(self.pContext)
            self.pContext = None
        if self.pDevice:
            vcall(self.pDevice, 2, ctypes.c_ulong)(self.pDevice)
            self.pDevice = None
        if self.pAdapter3:
            vcall(self.pAdapter3, 2, ctypes.c_ulong)(self.pAdapter3)
            self.pAdapter3 = None
        if self.pAdapter:
            vcall(self.pAdapter, 2, ctypes.c_ulong)(self.pAdapter)
            self.pAdapter = None
        if self.pFactory:
            vcall(self.pFactory, 2, ctypes.c_ulong)(self.pFactory)
            self.pFactory = None

        mfplat.MFShutdown()
        ole32.CoUninitialize()
        print("[PIPELINE] Clean shutdown complete.")

    # ── HUD Drawing ───────────────────────────────────────────────────────────

    def _draw_text(self, text_str: str, format_name: str, left: float, top: float, right: float, bottom: float, brush_name: str):
        rc = D2D1_RECT_F(left, top, right, bottom)
        vcall(self.pD2DContext, 27, None,
            ctypes.c_wchar_p, wintypes.UINT, ctypes.c_void_p,
            ctypes.POINTER(D2D1_RECT_F), ctypes.c_void_p, wintypes.UINT, wintypes.UINT
        )(self.pD2DContext, text_str, len(text_str), self.text_formats[format_name], ctypes.byref(rc), self.brushes[brush_name], 0, 0)

    def draw_rounded_rect(self, left: float, top: float, right: float, bottom: float, radius: float, stroke_width: float, brush_name: str):
        rr = D2D1_ROUNDED_RECT(D2D1_RECT_F(left, top, right, bottom), radius, radius)
        vcall(self.pD2DContext, 18, None, ctypes.POINTER(D2D1_ROUNDED_RECT), ctypes.c_void_p, ctypes.c_float, ctypes.c_void_p)(
            self.pD2DContext, ctypes.byref(rr), self.brushes[brush_name], stroke_width, None
        )

    def fill_rounded_rect(self, left: float, top: float, right: float, bottom: float, radius: float, brush_name: str):
        rr = D2D1_ROUNDED_RECT(D2D1_RECT_F(left, top, right, bottom), radius, radius)
        vcall(self.pD2DContext, 19, None, ctypes.POINTER(D2D1_ROUNDED_RECT), ctypes.c_void_p)(
            self.pD2DContext, ctypes.byref(rr), self.brushes[brush_name]
        )

    def fill_ellipse(self, cx: float, cy: float, rx: float, ry: float, brush_name: str):
        el = D2D1_ELLIPSE(D2D1_POINT_2F(cx, cy), rx, ry)
        vcall(self.pD2DContext, 21, None, ctypes.POINTER(D2D1_ELLIPSE), ctypes.c_void_p)(
            self.pD2DContext, ctypes.byref(el), self.brushes[brush_name]
        )

    def render_hud_frame(self, state: FrameState):
        vcall(self.pD2DContext, 48, None)(self.pD2DContext) # BeginDraw
        c = D2D1_COLOR_F(0.0, 0.0, 0.0, 0.0)
        vcall(self.pD2DContext, 47, None, ctypes.POINTER(D2D1_COLOR_F))(self.pD2DContext, ctypes.byref(c)) # Clear

        # Recording Time Card
        self.fill_rounded_rect(100.0, 80.0, 560.0, 220.0, 20.0, 'card_bg')
        self.draw_rounded_rect(100.0, 80.0, 560.0, 220.0, 20.0, 2.5, 'card_border')

        # Speed Card
        self.fill_rounded_rect(100.0, 1680.0, 680.0, 2040.0, 20.0, 'card_bg')
        self.draw_rounded_rect(100.0, 1680.0, 680.0, 2040.0, 20.0, 2.5, 'card_border')
        self.fill_ellipse(170.0, 1750.0, 22.0, 22.0, 'cyan')

        # Heart Rate Card
        self.fill_rounded_rect(740.0, 1680.0, 1300.0, 2040.0, 20.0, 'card_bg')
        self.draw_rounded_rect(740.0, 1680.0, 1300.0, 2040.0, 20.0, 2.5, 'card_border')
        self.fill_ellipse(810.0, 1750.0, 22.0, 22.0, 'coral')

        self._draw_text("RECORDING TIME", 'label', 130.0, 95.0, 500.0, 130.0, 'text_muted')
        self._draw_text(state.time_str, 'time', 130.0, 120.0, 540.0, 200.0, 'white')
        self._draw_text("SPEED", 'label', 220.0, 1735.0, 500.0, 1770.0, 'text_muted')
        self._draw_text(state.speed_str, 'speed_val', 130.0, 1780.0, 510.0, 1960.0, 'white')
        self._draw_text("km/h", 'speed_unit', 520.0, 1850.0, 660.0, 1930.0, 'cyan')
        self._draw_text("HEART RATE", 'label', 860.0, 1735.0, 1200.0, 1770.0, 'text_muted')
        self._draw_text(state.hr_str, 'hr_val', 770.0, 1780.0, 1150.0, 1960.0, 'white')
        self._draw_text("bpm", 'hr_unit', 1160.0, 1850.0, 1280.0, 1930.0, 'coral')

        t1, t2 = ctypes.c_uint64(), ctypes.c_uint64()
        vcall(self.pD2DContext, 49, ctypes.c_int32, ctypes.POINTER(ctypes.c_uint64), ctypes.POINTER(ctypes.c_uint64))(
            self.pD2DContext, ctypes.byref(t1), ctypes.byref(t2)
        )

    # ── Compositor Execution ──────────────────────────────────────────────────

    def composite(self, pVideoInView: ctypes.c_void_p, slot: int, include_hud: bool):
        pOutView = self.ring_vp_out_views[slot]
        if not include_hud:
            stream = D3D11_VIDEO_PROCESSOR_STREAM()
            stream.Enable = 1
            stream.OutputIndex = 0
            stream.InputFrameOrField = 0
            stream.pInputSurface = pVideoInView
            hr = vcall(self.pVideoContext, 53, ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p, wintypes.UINT, wintypes.UINT, ctypes.c_void_p)(
                self.pVideoContext, self.pVP, pOutView, 0, 1, ctypes.byref(stream)
            )
        else:
            streams = (D3D11_VIDEO_PROCESSOR_STREAM * 2)()
            streams[0].Enable = 1
            streams[0].OutputIndex = 0
            streams[0].InputFrameOrField = 0
            streams[0].pInputSurface = pVideoInView

            streams[1].Enable = 1
            streams[1].OutputIndex = 0
            streams[1].InputFrameOrField = 0
            streams[1].pInputSurface = self.pVPInViewHUD

            hr = vcall(self.pVideoContext, 53, ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p, wintypes.UINT, wintypes.UINT, ctypes.c_void_p)(
                self.pVideoContext, self.pVP, pOutView, 0, 2, ctypes.byref(streams)
            )
        if hr != 0:
            raise RuntimeError(f"VideoProcessorBlt failed: {hr:#x}")

    # ── Benchmark Runner ──────────────────────────────────────────────────────

    def run_benchmark(self, phase_name: str, total_frames: int, include_hud: bool, save_output_path: Optional[str] = None) -> Dict:
        print(f"\n>>> STARTING BENCHMARK: {phase_name} ({total_frames} frames, include_hud={include_hud})")

        # Start fresh NVENC session for this benchmark phase
        self.start_encode_session()

        # Setup decoder
        video_abs_path = str(ROOT / "Video" / "GX030120.MP4")
        decoder = MediaFoundationDecoder(self.pDevice, video_abs_path, self.pVPEnum, self.pVideoDevice)
        decoder.open()

        f_out = open(save_output_path, "wb") if save_output_path else None

        pfn_map_res = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.POINTER(NV_ENC_MAP_INPUT_RESOURCE))(self.fn_map['nvEncMapInputResource'])
        pfn_unmap = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p)(self.fn_map['nvEncUnmapInputResource'])
        pfn_encode = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.POINTER(NV_ENC_PIC_PARAMS))(self.fn_map['nvEncEncodePicture'])
        pfn_lock_bs = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.POINTER(NV_ENC_LOCK_BITSTREAM))(self.fn_map['nvEncLockBitstream'])
        pfn_unlock_bs = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p)(self.fn_map['nvEncUnlockBitstream'])

        map_struct = NV_ENC_MAP_INPUT_RESOURCE()
        map_struct.version = self.header.ver_defines['NV_ENC_MAP_INPUT_RESOURCE_VER']

        pic_params = NV_ENC_PIC_PARAMS()
        pic_params.version = self.header.ver_defines['NV_ENC_PIC_PARAMS_VER']
        pic_params.inputWidth = self.width
        pic_params.inputHeight = self.height
        pic_params.inputPitch = self.width
        pic_params.bufferFmt = 1 # NV12
        pic_params.pictureStruct = 1

        lock_bs = NV_ENC_LOCK_BITSTREAM()
        lock_bs.version = self.header.ver_defines['NV_ENC_LOCK_BITSTREAM_VER']
        lock_bs.doNotWait = 0

        # Memory tracking
        proc = psutil.Process()
        vram_start = self.query_vram_info()
        ram_start_mib = proc.memory_info().rss / (1024.0 * 1024.0)

        vram_mid = {}
        ram_mid_mib = 0.0
        mid_frame = total_frames // 2

        # Timings breakdown
        t_decode_total = 0.0
        t_telem_total = 0.0
        t_hud_total = 0.0
        t_vp_total = 0.0
        t_nvenc_total = 0.0
        t_bs_total = 0.0

        latencies_ms = []
        total_encoded_bytes = 0
        completed_frames = 0

        wall_t0 = time.perf_counter()

        for frame_idx in range(total_frames):
            frame_t0 = time.perf_counter()

            # 1. Decode acquire
            td0 = time.perf_counter()
            pVideoInView, pts, flags = decoder.read_frame_input_view()
            td1 = time.perf_counter()
            t_decode_total += (td1 - td0)

            if pVideoInView is None:
                print(f"[BENCHMARK] Reached end-of-stream at frame {frame_idx}")
                break

            # 2. Telemetry lookup
            tt0 = time.perf_counter()
            if include_hud and self.telemetry:
                state = self.telemetry.get(frame_idx)
            else:
                state = None
            tt1 = time.perf_counter()
            t_telem_total += (tt1 - tt0)

            # 3. Direct2D HUD Submission
            th0 = time.perf_counter()
            if include_hud and state is not None:
                self.render_hud_frame(state)
            th1 = time.perf_counter()
            t_hud_total += (th1 - th0)

            # 4. GPU Composition (VideoProcessorBlt)
            slot = frame_idx % self.ring_size
            tvp0 = time.perf_counter()
            self.composite(pVideoInView, slot, include_hud)
            tvp1 = time.perf_counter()
            t_vp_total += (tvp1 - tvp0)

            # 5. NVENC Submit & Encode
            te0 = time.perf_counter()
            map_struct.registeredResource = self.ring_registered_handles[slot]
            pfn_map_res(self.hEncoder, ctypes.byref(map_struct))

            pic_params.inputBuffer = map_struct.mappedResource
            pic_params.outputBitstream = self.ring_bitstream_buffers[slot]
            pic_params.frameIdx = frame_idx
            pic_params.encodePicFlags = 0
            pfn_encode(self.hEncoder, ctypes.byref(pic_params))
            pfn_unmap(self.hEncoder, map_struct.mappedResource)
            te1 = time.perf_counter()
            t_nvenc_total += (te1 - te0)

            # 6. Bitstream Handling
            tbs0 = time.perf_counter()
            lock_bs.outputBitstream = self.ring_bitstream_buffers[slot]
            pfn_lock_bs(self.hEncoder, ctypes.byref(lock_bs))
            b_size = lock_bs.bitstreamSizeInBytes
            total_encoded_bytes += b_size
            if f_out and b_size > 0:
                bs_data = bytes((ctypes.c_byte * b_size).from_address(lock_bs.bitstreamBufferPtr))
                f_out.write(bs_data)
            pfn_unlock_bs(self.hEncoder, self.ring_bitstream_buffers[slot])
            tbs1 = time.perf_counter()
            t_bs_total += (tbs1 - tbs0)

            frame_t1 = time.perf_counter()
            latencies_ms.append((frame_t1 - frame_t0) * 1000.0)
            completed_frames += 1

            if frame_idx == mid_frame:
                vram_mid = self.query_vram_info()
                ram_mid_mib = proc.memory_info().rss / (1024.0 * 1024.0)

            if (frame_idx + 1) % 500 == 0 or (frame_idx + 1) == total_frames:
                cur_wall = time.perf_counter() - wall_t0
                print(f"  Frame {frame_idx + 1:5d}/{total_frames}: "
                      f"elapsed={cur_wall:.2f}s, rolling_fps={completed_frames / cur_wall:.2f} FPS")

        # Drain NVENC encoder at EOS
        drain_params = NV_ENC_PIC_PARAMS()
        drain_params.version = self.header.ver_defines['NV_ENC_PIC_PARAMS_VER']
        drain_params.encodePicFlags = 0x8 # NV_ENC_PIC_FLAG_EOS
        pfn_encode(self.hEncoder, ctypes.byref(drain_params))

        wall_t1 = time.perf_counter()
        wall_time_sec = wall_t1 - wall_t0
        fps = completed_frames / wall_time_sec if wall_time_sec > 0 else 0.0

        vram_end = self.query_vram_info()
        ram_end_mib = proc.memory_info().rss / (1024.0 * 1024.0)

        if f_out:
            f_out.close()

        decoder.close()
        self.end_encode_session()

        def percentile(arr, p):
            if not arr: return 0.0
            sorted_arr = sorted(arr)
            k = (len(sorted_arr) - 1) * (p / 100.0)
            f = math.floor(k)
            c = math.ceil(k)
            if f == c: return sorted_arr[int(k)]
            return sorted_arr[int(f)] * (c - k) + sorted_arr[int(c)] * (k - f)

        res = {
            "phase": phase_name,
            "completed_frames": completed_frames,
            "wall_time_sec": wall_time_sec,
            "fps": fps,
            "bitstream_bytes": total_encoded_bytes,
            "bitrate_mbps": (total_encoded_bytes * 8.0 / (completed_frames / 29.97)) / 1_000_000.0 if completed_frames > 0 else 0.0,
            "latency": {
                "avg_ms": sum(latencies_ms) / len(latencies_ms) if latencies_ms else 0.0,
                "median_ms": percentile(latencies_ms, 50),
                "p95_ms": percentile(latencies_ms, 95),
                "p99_ms": percentile(latencies_ms, 99),
                "max_ms": max(latencies_ms) if latencies_ms else 0.0
            },
            "breakdown_ms_per_frame": {
                "decode_acquire_ms": (t_decode_total / completed_frames) * 1000.0 if completed_frames > 0 else 0.0,
                "telemetry_lookup_ms": (t_telem_total / completed_frames) * 1000.0 if completed_frames > 0 else 0.0,
                "hud_d2d_ms": (t_hud_total / completed_frames) * 1000.0 if completed_frames > 0 else 0.0,
                "vp_composite_ms": (t_vp_total / completed_frames) * 1000.0 if completed_frames > 0 else 0.0,
                "nvenc_submit_ms": (t_nvenc_total / completed_frames) * 1000.0 if completed_frames > 0 else 0.0,
                "bitstream_handling_ms": (t_bs_total / completed_frames) * 1000.0 if completed_frames > 0 else 0.0,
            },
            "memory": {
                "ram_start_mib": ram_start_mib,
                "ram_mid_mib": ram_mid_mib,
                "ram_end_mib": ram_end_mib,
                "vram_start": vram_start,
                "vram_mid": vram_mid,
                "vram_end": vram_end
            }
        }

        print(f"\n--- RESULTS: {phase_name} ---")
        print(f"  Frames Encoded: {completed_frames}")
        print(f"  Wall Time:      {wall_time_sec:.3f} s")
        print(f"  Throughput FPS: {fps:.2f} FPS")
        print(f"  Avg Latency:    {res['latency']['avg_ms']:.2f} ms (p95: {res['latency']['p95_ms']:.2f} ms, max: {res['latency']['max_ms']:.2f} ms)")
        print(f"  Breakdown (ms/f): decode={res['breakdown_ms_per_frame']['decode_acquire_ms']:.3f}, hud={res['breakdown_ms_per_frame']['hud_d2d_ms']:.3f}, vp={res['breakdown_ms_per_frame']['vp_composite_ms']:.3f}, nvenc={res['breakdown_ms_per_frame']['nvenc_submit_ms']:.3f}")
        print(f"  RAM:  start={ram_start_mib:.1f} MB -> mid={ram_mid_mib:.1f} MB -> end={ram_end_mib:.1f} MB")
        print(f"  VRAM: budget={vram_end.get('budget_mib', 0):.1f} MB, usage={vram_end.get('current_usage_mib', 0):.1f} MB")
        return res

# ── Main Entry Point ─────────────────────────────────────────────────────────

def run_stage8e():
    total_file_frames = 5395 # GX030120 duration 180.013s * 29.97fps
    fit_file = str(ROOT / "Video" / "Popoludniowa_jazda_na_rowerze_solar_battery.fit")

    # 1. Precompute Real Telemetry
    telem = TelemetryProvider(fit_file, total_frames=total_file_frames)
    telem.precompute()

    # 2. Initialize Stage 8E Pipeline
    pipeline = NvidiaStage8EPipeline(3840, 2160, ring_size=4)
    pipeline.initialize()
    pipeline.telemetry = telem

    results = {}

    # BENCHMARK A: REAL VIDEO DECODE ONLY (3000 frames)
    res_a = pipeline.run_benchmark(
        phase_name="BENCHMARK A — REAL VIDEO DECODE ONLY",
        total_frames=3000,
        include_hud=False,
        save_output_path=None
    )
    results["benchmark_a"] = res_a

    # BENCHMARK B: REAL VIDEO + REAL TELEMETRY HUD (3000 frames)
    out_hevc_path = str(ROOT / "scratch" / "nvidia_stage8e_realvideo_output.hevc")
    res_b = pipeline.run_benchmark(
        phase_name="BENCHMARK B — REAL VIDEO + REAL TELEMETRY HUD",
        total_frames=3000,
        include_hud=True,
        save_output_path=out_hevc_path
    )
    results["benchmark_b"] = res_b

    # BENCHMARK C: LONGER STABILITY — FULL FILE (~5395 frames)
    res_c = pipeline.run_benchmark(
        phase_name="BENCHMARK C — FULL FILE REAL VIDEO + TELEMETRY HUD",
        total_frames=total_file_frames,
        include_hud=True,
        save_output_path=None
    )
    results["benchmark_c"] = res_c

    # Save summary json
    json_path = ROOT / "scratch" / "nvidia_stage8e_benchmark_results.json"
    with open(json_path, "w") as f_json:
        json.dump(results, f_json, indent=2)
    print(f"\n[BENCHMARK] Results saved to {json_path}")

    # Clean shutdown
    pipeline.close()

if __name__ == "__main__":
    run_stage8e()
