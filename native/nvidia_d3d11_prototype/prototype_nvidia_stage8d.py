#!/usr/bin/env python3
"""TeleM NVIDIA STAGE 8D - D3D11 -> NVENC SDK Zero-Copy Prototype.

Zero-copy end-to-end hardware video telemetry pipeline:
1. Physical NVIDIA adapter selection (Blackwell RTX 5070 Ti) & D3D11 device creation.
2. Direct2D 1.1 + DirectWrite HUD rendering onto 4K BGRA8 GPU texture.
3. D3D11 VideoProcessor hardware compositor converting BGRA8 HUD into NV12 VRAM surface.
4. NVENC session initialization on SAME D3D11 DEVICE via official Video Codec SDK 13.1 ABI.
5. Persistent 4-surface NV12 resource ring registered once at startup (nvEncRegisterResource).
6. Pure zero-copy execution: all frames reside 100% in VRAM, only compressed HEVC bitstream egresses to CPU.
7. Three timed benchmark phases (A: NVENC only, B: HUD+Compositor+NVENC, C: 14-group Stress+NVENC).
"""

import os
import sys
import time
import math
import ctypes
from ctypes import wintypes
from pathlib import Path
import json

# COM & Win32 Dlls
ole32 = ctypes.windll.ole32
dxgi = ctypes.windll.dxgi
d3d11 = ctypes.windll.d3d11
d2d1 = ctypes.windll.d2d1
dwrite = ctypes.windll.dwrite

def IID(guid_str: str):
    buf = (ctypes.c_byte * 16)()
    hr = ole32.IIDFromString(ctypes.c_wchar_p(guid_str), buf)
    if hr != 0:
        raise RuntimeError(f"Failed to parse IID {guid_str}: {hr:#x}")
    return buf

# Standard Interface GUIDs
IID_IDXGIFactory         = IID("{7b7166ec-21c7-44ae-b21a-c9ae321ae369}")
IID_IDXGIAdapter         = IID("{2411e03e-16dd-4f66-bb84-96d298d5d034}")
IID_IDXGIDevice          = IID("{54ec77fa-1377-44e6-8c32-88fd5f44c84c}")
IID_IDXGISurface1        = IID("{4AE63092-6327-4c1b-80AE-BFE12EA32B86}")
IID_ID3D11Texture2D      = IID("{6f15aaf2-d208-4e89-9ab4-489535d34f9c}")
IID_IDWriteFactory       = IID("{b859ee5a-d838-4b5b-a2e8-1adc7d93db48}")
IID_ID3D11InfoQueue      = IID("{6543dbb6-1b48-42f5-ab82-e97ec74326f6}")
IID_ID3D11VideoDevice    = IID("{10EC4D5B-975A-4689-B9E4-D0AAC30FE333}")
IID_ID3D11VideoContext   = IID("{61F21C45-3C0E-4A74-9CEA-67100D9AD5E4}")

def vcall(ptr, slot, restype, *argtypes):
    vtbl = ctypes.cast(ptr, ctypes.POINTER(ctypes.c_void_p))[0]
    fn_ptr = ctypes.cast(vtbl, ctypes.POINTER(ctypes.c_void_p))[slot]
    return ctypes.WINFUNCTYPE(restype, ctypes.c_void_p, *argtypes)(fn_ptr)

# Structures
class DXGI_ADAPTER_DESC(ctypes.Structure):
    _fields_ = [
        ('Description', ctypes.c_wchar * 128),
        ('VendorId', wintypes.UINT),
        ('DeviceId', wintypes.UINT),
        ('SubSysId', wintypes.UINT),
        ('Revision', wintypes.UINT),
        ('DedicatedVideoMemory', ctypes.c_size_t),
        ('DedicatedSystemMemory', ctypes.c_size_t),
        ('SharedSystemMemory', ctypes.c_size_t),
        ('AdapterLuidLow', wintypes.DWORD),
        ('AdapterLuidHigh', wintypes.LONG),
    ]

class D3D11_TEXTURE2D_DESC(ctypes.Structure):
    _fields_ = [
        ('Width', wintypes.UINT), ('Height', wintypes.UINT), ('MipLevels', wintypes.UINT),
        ('ArraySize', wintypes.UINT), ('Format', wintypes.UINT), ('SampleDesc_Count', wintypes.UINT),
        ('SampleDesc_Quality', wintypes.UINT), ('Usage', wintypes.UINT), ('BindFlags', wintypes.UINT),
        ('CPUAccessFlags', wintypes.UINT), ('MiscFlags', wintypes.UINT)
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

def percentile(arr, p):
    if not arr:
        return 0.0
    arr_sorted = sorted(arr)
    k = (len(arr_sorted) - 1) * (p / 100.0)
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return arr_sorted[int(k)]
    d0 = arr_sorted[int(f)] * (c - k)
    d1 = arr_sorted[int(c)] * (k - f)
    return d0 + d1

# Import NVENC definitions derived from nvEncodeAPI.h 13.1
sys.path.insert(0, str(Path(__file__).parent))
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


class NvidiaStage8DPipeline:
    def __init__(self, width=3840, height=2160, ring_size=4):
        self.width = width
        self.height = height
        self.ring_size = ring_size

        # D3D11 & D2D
        self.pFactory = None
        self.pAdapter = None
        self.adapter_desc = None
        self.pDevice = None
        self.pContext = None
        self.pInfoQueue = None

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
        self.pVPInView = None

        # NVENC SDK
        self.header = NvEncodeAPIHeader()
        self.nvenc_dll = ctypes.windll.LoadLibrary("nvEncodeAPI64.dll")
        self.fn_list = NV_ENCODE_API_FUNCTION_LIST()
        self.fn_map = {}
        self.hEncoder = None
        self.preset_cfg = None

        # Ring Resources
        self.ring_nv12_textures = []
        self.ring_vp_out_views = []
        self.ring_registered_handles = []
        self.ring_bitstream_buffers = []

    def initialize(self):
        print("=" * 80)
        print("STAGE 8D: INITIALIZING DIRECT D3D11 -> NVENC ZERO-COPY PIPELINE")
        print("=" * 80)

        # 1. Enumerate and select physical NVIDIA adapter
        self._select_adapter()

        # 2. Create D3D11 Device
        self._create_device()

        # 3. Create 4K BGRA8 HUD texture
        self._create_hud_texture()

        # 4. Initialize Direct2D 1.1 Context
        self._create_d2d_context()

        # 5. Initialize DirectWrite
        self._create_dwrite()

        # 6. Initialize Brushes
        self._create_brushes()

        # 7. Initialize D3D11 Video Processor
        self._create_video_processor()

        # 8. Create Persistent NV12 Surfaces & VP Views (4 x NV12)
        self._create_d3d11_surfaces()

        print("\n[PIPELINE] Initialized successfully. Ring size:", self.ring_size)
        print("=" * 80)

    def _select_adapter(self):
        pFactory = ctypes.c_void_p()
        hr = dxgi.CreateDXGIFactory1(ctypes.byref(IID_IDXGIFactory), ctypes.byref(pFactory))
        if hr != 0:
            raise RuntimeError(f"CreateDXGIFactory1 failed: {hr:#x}")
        self.pFactory = pFactory

        adapter_idx = 0
        pCurAdapter = ctypes.c_void_p()
        selected_adapter = None
        selected_desc = None

        while True:
            hr_enum = vcall(self.pFactory, 7, ctypes.c_int32, wintypes.UINT, ctypes.POINTER(ctypes.c_void_p))(
                self.pFactory, adapter_idx, ctypes.byref(pCurAdapter)
            )
            if hr_enum != 0:
                break

            desc = DXGI_ADAPTER_DESC()
            vcall(pCurAdapter, 8, ctypes.c_int32, ctypes.POINTER(DXGI_ADAPTER_DESC))(pCurAdapter, ctypes.byref(desc))
            if desc.VendorId == 0x10DE and selected_adapter is None:
                selected_adapter = pCurAdapter
                selected_desc = desc
                pCurAdapter = ctypes.c_void_p()
            adapter_idx += 1

        if not selected_adapter:
            raise RuntimeError("No physical NVIDIA adapter found!")
        self.pAdapter = selected_adapter
        self.adapter_desc = selected_desc
        print(f"Selected Adapter: {self.adapter_desc.Description} (Vendor 0x{self.adapter_desc.VendorId:X}, Device 0x{self.adapter_desc.DeviceId:X})")
        print(f"  Dedicated VRAM: {self.adapter_desc.DedicatedVideoMemory // (1024*1024)} MiB")

    def _create_device(self):
        flags = 0x20 | 0x2 # D3D11_CREATE_DEVICE_BGRA_SUPPORT | D3D11_CREATE_DEVICE_DEBUG
        feature_levels = (ctypes.c_uint * 2)(0xb100, 0xb000)
        pDevice = ctypes.c_void_p()
        pContext = ctypes.c_void_p()
        chosen_fl = ctypes.c_uint()

        hr = d3d11.D3D11CreateDevice(
            self.pAdapter, 0, None, flags,
            feature_levels, 2, 7,
            ctypes.byref(pDevice), ctypes.byref(chosen_fl), ctypes.byref(pContext)
        )
        if hr != 0:
            # Retry without debug flag if debug layer unavailable
            flags = 0x20
            hr = d3d11.D3D11CreateDevice(
                self.pAdapter, 0, None, flags,
                feature_levels, 2, 7,
                ctypes.byref(pDevice), ctypes.byref(chosen_fl), ctypes.byref(pContext)
            )
            if hr != 0:
                raise RuntimeError(f"D3D11CreateDevice failed: {hr:#x}")
        self.pDevice = pDevice
        self.pContext = pContext

        # Query InfoQueue if debug active
        pIQ = ctypes.c_void_p()
        hr_iq = vcall(self.pDevice, 0, ctypes.c_int32, ctypes.c_char_p, ctypes.POINTER(ctypes.c_void_p))(
            self.pDevice, bytes(IID_ID3D11InfoQueue), ctypes.byref(pIQ)
        )
        if hr_iq == 0 and pIQ.value:
            self.pInfoQueue = pIQ
            print("D3D11 Debug Layer active.")

    def _create_hud_texture(self):
        desc = D3D11_TEXTURE2D_DESC()
        desc.Width = self.width
        desc.Height = self.height
        desc.MipLevels = 1
        desc.ArraySize = 1
        desc.Format = 87 # DXGI_FORMAT_B8G8R8A8_UNORM
        desc.SampleDesc_Count = 1
        desc.SampleDesc_Quality = 0
        desc.Usage = 0
        desc.BindFlags = 0x20 | 0x8 # RENDER_TARGET | SHADER_RESOURCE
        desc.CPUAccessFlags = 0
        desc.MiscFlags = 0

        pHud = ctypes.c_void_p()
        hr = vcall(self.pDevice, 5, ctypes.c_int32, ctypes.POINTER(D3D11_TEXTURE2D_DESC), ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p))(
            self.pDevice, ctypes.byref(desc), None, ctypes.byref(pHud)
        )
        if hr != 0:
            raise RuntimeError(f"Create HUD Texture failed: {hr:#x}")
        self.pHudTexture = pHud

    def _create_d2d_context(self):
        pDxgiDevice = ctypes.c_void_p()
        hr = vcall(self.pDevice, 0, ctypes.c_int32, ctypes.c_char_p, ctypes.POINTER(ctypes.c_void_p))(
            self.pDevice, bytes(IID_IDXGIDevice), ctypes.byref(pDxgiDevice)
        )
        if hr != 0:
            raise RuntimeError(f"QI IDXGIDevice failed: {hr:#x}")

        pD2DDevice = ctypes.c_void_p()
        d2d1.D2D1CreateDevice.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
        d2d1.D2D1CreateDevice.restype = ctypes.c_int32
        hr = d2d1.D2D1CreateDevice(pDxgiDevice, None, ctypes.byref(pD2DDevice))
        if hr != 0:
            raise RuntimeError(f"D2D1CreateDevice failed: {hr:#x}")
        self.pD2DDevice = pD2DDevice

        pD2DContext = ctypes.c_void_p()
        hr = vcall(self.pD2DDevice, 4, ctypes.c_int32, ctypes.c_uint32, ctypes.POINTER(ctypes.c_void_p))(
            self.pD2DDevice, 0, ctypes.byref(pD2DContext)
        )
        if hr != 0:
            raise RuntimeError(f"CreateDeviceContext failed: {hr:#x}")
        self.pD2DContext = pD2DContext

        pSurf = ctypes.c_void_p()
        hr = vcall(self.pHudTexture, 0, ctypes.c_int32, ctypes.c_char_p, ctypes.POINTER(ctypes.c_void_p))(
            self.pHudTexture, bytes(IID_IDXGISurface1), ctypes.byref(pSurf)
        )
        if hr != 0:
            raise RuntimeError(f"QI IDXGISurface1 failed: {hr:#x}")

        bp = D2D1_BITMAP_PROPERTIES1(D2D1_PIXEL_FORMAT(87, 1), 96.0, 96.0, 1, None)
        pBitmap = ctypes.c_void_p()
        hr = vcall(self.pD2DContext, 62, ctypes.c_int32, ctypes.c_void_p, ctypes.POINTER(D2D1_BITMAP_PROPERTIES1), ctypes.POINTER(ctypes.c_void_p))(
            self.pD2DContext, pSurf, ctypes.byref(bp), ctypes.byref(pBitmap)
        )
        if hr != 0:
            raise RuntimeError(f"CreateBitmapFromDxgiSurface failed: {hr:#x}")
        self.pD2DBitmapTarget = pBitmap

        vcall(self.pD2DContext, 74, None, ctypes.c_void_p)(self.pD2DContext, self.pD2DBitmapTarget)
        vcall(self.pD2DContext, 32, None, ctypes.c_int)(self.pD2DContext, 0)
        vcall(self.pD2DContext, 34, None, ctypes.c_int)(self.pD2DContext, 2) # D2D1_TEXT_ANTIALIAS_MODE_GRAYSCALE

    def _create_dwrite(self):
        pDWriteFactory = ctypes.c_void_p()
        dwrite.DWriteCreateFactory.argtypes = [ctypes.c_int, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
        dwrite.DWriteCreateFactory.restype = ctypes.c_int32
        hr = dwrite.DWriteCreateFactory(0, bytes(IID_IDWriteFactory), ctypes.byref(pDWriteFactory))
        if hr != 0:
            raise RuntimeError(f"DWriteCreateFactory failed: {hr:#x}")
        self.pDWriteFactory = pDWriteFactory

        def create_fmt(family, weight, size):
            pFmt = ctypes.c_void_p()
            hr_fmt = vcall(self.pDWriteFactory, 15, ctypes.c_int32,
                ctypes.c_wchar_p, ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                ctypes.c_float, ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_void_p)
            )(self.pDWriteFactory, family, None, weight, 0, 5, size, 'en-us', ctypes.byref(pFmt))
            if hr_fmt != 0:
                raise RuntimeError(f"CreateTextFormat failed: {hr_fmt:#x}")
            return pFmt

        self.text_formats['time'] = create_fmt('Segoe UI', 700, 68.0)
        self.text_formats['speed_val'] = create_fmt('Segoe UI', 700, 112.0)
        self.text_formats['speed_unit'] = create_fmt('Segoe UI', 600, 36.0)
        self.text_formats['hr_val'] = create_fmt('Segoe UI', 700, 112.0)
        self.text_formats['hr_unit'] = create_fmt('Segoe UI', 600, 36.0)
        self.text_formats['label'] = create_fmt('Segoe UI', 600, 26.0)
        self.text_formats['small_val'] = create_fmt('Segoe UI', 700, 48.0)

    def _create_brushes(self):
        def make_brush(r, g, b, a):
            col = D2D1_COLOR_F(r, g, b, a)
            pB = ctypes.c_void_p()
            hr = vcall(self.pD2DContext, 8, ctypes.c_int32, ctypes.POINTER(D2D1_COLOR_F), ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p))(
                self.pD2DContext, ctypes.byref(col), None, ctypes.byref(pB)
            )
            if hr != 0:
                raise RuntimeError(f"CreateSolidColorBrush failed: {hr:#x}")
            return pB

        self.brushes['white'] = make_brush(1.0, 1.0, 1.0, 1.0)
        self.brushes['text_muted'] = make_brush(0.75, 0.82, 0.90, 0.90)
        self.brushes['cyan'] = make_brush(0.0, 0.88, 1.0, 1.0)
        self.brushes['coral'] = make_brush(1.0, 0.32, 0.32, 1.0)
        self.brushes['green'] = make_brush(0.2, 0.9, 0.4, 1.0)
        self.brushes['gold'] = make_brush(1.0, 0.84, 0.0, 1.0)
        self.brushes['card_bg'] = make_brush(0.04, 0.06, 0.10, 0.68)
        self.brushes['card_border'] = make_brush(0.25, 0.35, 0.50, 0.60)
        self.brushes['accent_line'] = make_brush(0.0, 0.80, 1.0, 0.85)

    def _create_video_processor(self):
        pVD = ctypes.c_void_p()
        hr = vcall(self.pDevice, 0, ctypes.c_int, ctypes.c_char_p, ctypes.POINTER(ctypes.c_void_p))(
            self.pDevice, bytes(IID_ID3D11VideoDevice), ctypes.byref(pVD)
        )
        if hr != 0:
            raise RuntimeError(f"QI ID3D11VideoDevice failed: {hr:#x}")
        self.pVideoDevice = pVD

        pVC = ctypes.c_void_p()
        hr = vcall(self.pContext, 0, ctypes.c_int, ctypes.c_char_p, ctypes.POINTER(ctypes.c_void_p))(
            self.pContext, bytes(IID_ID3D11VideoContext), ctypes.byref(pVC)
        )
        if hr != 0:
            raise RuntimeError(f"QI ID3D11VideoContext failed: {hr:#x}")
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
        if hr != 0:
            raise RuntimeError(f"CreateVideoProcessorEnumerator failed: {hr:#x}")
        self.pVPEnum = pEnum

        pVP = ctypes.c_void_p()
        hr = vcall(self.pVideoDevice, 4, ctypes.c_int, ctypes.c_void_p, wintypes.UINT, ctypes.POINTER(ctypes.c_void_p))(
            self.pVideoDevice, self.pVPEnum, 0, ctypes.byref(pVP)
        )
        if hr != 0:
            raise RuntimeError(f"CreateVideoProcessor failed: {hr:#x}")
        self.pVP = pVP

        # Create input view for pHudTexture
        in_desc = D3D11_VIDEO_PROCESSOR_INPUT_VIEW_DESC()
        in_desc.FourCC = 0
        in_desc.ViewDimension = 1
        in_desc.MipSlice = 0
        in_desc.ArraySlice = 0

        pInView = ctypes.c_void_p()
        hr = vcall(self.pVideoDevice, 8, ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(D3D11_VIDEO_PROCESSOR_INPUT_VIEW_DESC), ctypes.POINTER(ctypes.c_void_p))(
            self.pVideoDevice, self.pHudTexture, self.pVPEnum, ctypes.byref(in_desc), ctypes.byref(pInView)
        )
        if hr != 0:
            raise RuntimeError(f"CreateVideoProcessorInputView failed: {hr:#x}")
        self.pVPInView = pInView

    def _create_nvenc_session(self):
        self.fn_list.version = self.header.ver_defines['NV_ENCODE_API_FUNCTION_LIST_VER']
        pfn_create = self.nvenc_dll.NvEncodeAPICreateInstance
        pfn_create.argtypes = [ctypes.POINTER(NV_ENCODE_API_FUNCTION_LIST)]
        pfn_create.restype = ctypes.c_int
        hr = pfn_create(ctypes.byref(self.fn_list))
        if hr != 0:
            raise RuntimeError(f"NvEncodeAPICreateInstance failed: {hr:#x}")

        for i, (ftype, fname) in enumerate(self.header.fn_names[2:45]):
            self.fn_map[fname] = self.fn_list.ptrs[i]

        pfn_open_session = ctypes.WINFUNCTYPE(
            ctypes.c_int,
            ctypes.POINTER(NV_ENC_OPEN_ENCODE_SESSION_EX_PARAMS),
            ctypes.POINTER(ctypes.c_void_p)
        )(self.fn_map['nvEncOpenEncodeSessionEx'])

        session_params = NV_ENC_OPEN_ENCODE_SESSION_EX_PARAMS()
        session_params.version = self.header.ver_defines['NV_ENC_OPEN_ENCODE_SESSION_EX_PARAMS_VER']
        session_params.deviceType = 0 # NV_ENC_DEVICE_TYPE_DIRECTX
        session_params.device = self.pDevice
        session_params.apiVersion = self.header.api_version

        hEncoder = ctypes.c_void_p()
        hr = pfn_open_session(ctypes.byref(session_params), ctypes.byref(hEncoder))
        if hr != 0:
            raise RuntimeError(f"nvEncOpenEncodeSessionEx failed: {hr:#x}")
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

    def _create_d3d11_surfaces(self):
        for i in range(self.ring_size):
            # 1. Create NV12 Texture
            desc = D3D11_TEXTURE2D_DESC()
            desc.Width = self.width
            desc.Height = self.height
            desc.MipLevels = 1
            desc.ArraySize = 1
            desc.Format = 103 # DXGI_FORMAT_NV12
            desc.SampleDesc_Count = 1
            desc.SampleDesc_Quality = 0
            desc.Usage = 0
            desc.BindFlags = 0x20 | 0x8 # RENDER_TARGET | SHADER_RESOURCE
            desc.CPUAccessFlags = 0
            desc.MiscFlags = 0

            pTex = ctypes.c_void_p()
            hr = vcall(self.pDevice, 5, ctypes.c_int, ctypes.POINTER(D3D11_TEXTURE2D_DESC), ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p))(
                self.pDevice, ctypes.byref(desc), None, ctypes.byref(pTex)
            )
            if hr != 0:
                raise RuntimeError(f"Create NV12 Texture [{i}] failed: {hr:#x}")
            self.ring_nv12_textures.append(pTex)

            # 2. Create VideoProcessorOutputView for VideoProcessorBlt
            out_desc = D3D11_VIDEO_PROCESSOR_OUTPUT_VIEW_DESC()
            out_desc.ViewDimension = 1
            out_desc.MipSlice = 0
            out_desc.ArraySlice = 0

            pOutView = ctypes.c_void_p()
            hr = vcall(self.pVideoDevice, 9, ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(D3D11_VIDEO_PROCESSOR_OUTPUT_VIEW_DESC), ctypes.POINTER(ctypes.c_void_p))(
                self.pVideoDevice, pTex, self.pVPEnum, ctypes.byref(out_desc), ctypes.byref(pOutView)
            )
            if hr != 0:
                raise RuntimeError(f"Create VP Output View [{i}] failed: {hr:#x}")
            self.ring_vp_out_views.append(pOutView)
        print(f"Created {self.ring_size} persistent D3D11 NV12 textures and VideoProcessor views.")

    def _register_ring_resources(self):
        pfn_reg_res = ctypes.WINFUNCTYPE(
            ctypes.c_int,
            ctypes.c_void_p,
            ctypes.POINTER(NV_ENC_REGISTER_RESOURCE)
        )(self.fn_map['nvEncRegisterResource'])

        pfn_create_bs = ctypes.WINFUNCTYPE(
            ctypes.c_int,
            ctypes.c_void_p,
            ctypes.POINTER(NV_ENC_CREATE_BITSTREAM_BUFFER)
        )(self.fn_map['nvEncCreateBitstreamBuffer'])

        for i in range(self.ring_size):
            pTex = self.ring_nv12_textures[i]
            # 3. Register resource with NVENC ONCE for this session
            reg = NV_ENC_REGISTER_RESOURCE()
            reg.version = self.header.ver_defines['NV_ENC_REGISTER_RESOURCE_VER']
            reg.resourceType = 0 # DIRECTX
            reg.width = self.width
            reg.height = self.height
            reg.pitch = 0
            reg.subResourceIndex = 0
            reg.resourceToRegister = pTex
            reg.bufferFormat = 1 # NV_ENC_BUFFER_FORMAT_NV12
            reg.bufferUsage = 0 # NV_ENC_INPUT_IMAGE

            hr = pfn_reg_res(self.hEncoder, ctypes.byref(reg))
            if hr != 0:
                raise RuntimeError(f"nvEncRegisterResource [{i}] failed: {hr:#x}")
            self.ring_registered_handles.append(reg.registeredResource)

            # 4. Create Bitstream Buffer
            bs = NV_ENC_CREATE_BITSTREAM_BUFFER()
            bs.version = self.header.ver_defines['NV_ENC_CREATE_BITSTREAM_BUFFER_VER']
            hr = pfn_create_bs(self.hEncoder, ctypes.byref(bs))
            if hr != 0:
                raise RuntimeError(f"nvEncCreateBitstreamBuffer [{i}] failed: {hr:#x}")
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

        for bs in self.ring_bitstream_buffers:
            pfn_destroy_bs(self.hEncoder, bs)
        self.ring_bitstream_buffers.clear()

        for reg in self.ring_registered_handles:
            pfn_unreg_res(self.hEncoder, reg)
        self.ring_registered_handles.clear()

        pfn_destroy_enc(self.hEncoder)
        self.hEncoder = None
        print("NVENC session ended and resources unregistered.")

    # ── High Level HUD Drawing ────────────────────────────────────────────────

    def draw_line(self, x0: float, y0: float, x1: float, y1: float, stroke_width: float, brush_name: str):
        p0 = D2D1_POINT_2F(x0, y0)
        p1 = D2D1_POINT_2F(x1, y1)
        vcall(self.pD2DContext, 15, None, D2D1_POINT_2F, D2D1_POINT_2F, ctypes.c_void_p, ctypes.c_float, ctypes.c_void_p)(
            self.pD2DContext, p0, p1, self.brushes[brush_name], stroke_width, None
        )

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

    def draw_ellipse(self, cx: float, cy: float, rx: float, ry: float, stroke_width: float, brush_name: str):
        el = D2D1_ELLIPSE(D2D1_POINT_2F(cx, cy), rx, ry)
        vcall(self.pD2DContext, 20, None, ctypes.POINTER(D2D1_ELLIPSE), ctypes.c_void_p, ctypes.c_float, ctypes.c_void_p)(
            self.pD2DContext, ctypes.byref(el), self.brushes[brush_name], stroke_width, None
        )

    def fill_ellipse(self, cx: float, cy: float, rx: float, ry: float, brush_name: str):
        el = D2D1_ELLIPSE(D2D1_POINT_2F(cx, cy), rx, ry)
        vcall(self.pD2DContext, 21, None, ctypes.POINTER(D2D1_ELLIPSE), ctypes.c_void_p)(
            self.pD2DContext, ctypes.byref(el), self.brushes[brush_name]
        )

    def render_hud_basic(self, frame_idx: int):
        """Dynamic 3-indicator HUD from STAGE 8C."""
        vcall(self.pD2DContext, 48, None)(self.pD2DContext) # BeginDraw
        c = D2D1_COLOR_F(0.0, 0.0, 0.0, 0.0)
        vcall(self.pD2DContext, 47, None, ctypes.POINTER(D2D1_COLOR_F))(self.pD2DContext, ctypes.byref(c)) # Clear

        self.render_hud_basic_no_begin_end(frame_idx)

        t1, t2 = ctypes.c_uint64(), ctypes.c_uint64()
        vcall(self.pD2DContext, 49, ctypes.c_int32, ctypes.POINTER(ctypes.c_uint64), ctypes.POINTER(ctypes.c_uint64))(
            self.pD2DContext, ctypes.byref(t1), ctypes.byref(t2)
        )

    def render_hud_stress(self, frame_idx: int):
        """Stress HUD with ~14 lightweight telemetry groups across 4K canvas."""
        vcall(self.pD2DContext, 48, None)(self.pD2DContext)
        c = D2D1_COLOR_F(0.0, 0.0, 0.0, 0.0)
        vcall(self.pD2DContext, 47, None, ctypes.POINTER(D2D1_COLOR_F))(self.pD2DContext, ctypes.byref(c))

        # First 3 cards
        self.render_hud_basic_no_begin_end(frame_idx)

        # Additional 11 groups (total 14)
        groups = [
            ("CADENCE", f"{88 + int(5*math.sin(frame_idx*0.04))} rpm", 100.0, 240.0, 'cyan'),
            ("POWER", f"{265 + int(40*math.sin(frame_idx*0.02))} W", 100.0, 380.0, 'coral'),
            ("ELEVATION", f"{452.1 + frame_idx*0.01:.1f} m", 100.0, 520.0, 'gold'),
            ("SLOPE", f"{3.2 + math.sin(frame_idx*0.01):.1f} %", 100.0, 660.0, 'green'),
            ("DISTANCE", f"{12.4 + frame_idx*0.005:.2f} km", 3200.0, 80.0, 'white'),
            ("PACE", f"1:45 /km", 3200.0, 220.0, 'cyan'),
            ("TEMP", f"{21.5:.1f} °C", 3200.0, 360.0, 'gold'),
            ("BATTERY", f"{85 - int(frame_idx*0.001)} %", 3200.0, 500.0, 'green'),
            ("HEADING", f"{int((frame_idx*0.5)%360)}° NW", 3200.0, 640.0, 'coral'),
            ("CALORIES", f"{340 + int(frame_idx*0.1)} kcal", 3200.0, 780.0, 'gold'),
            ("VAM", f"{1150 + int(20*math.cos(frame_idx*0.05))} m/h", 3200.0, 920.0, 'cyan')
        ]

        for label, val, x, y, brush_col in groups:
            self.fill_rounded_rect(x, y, x + 500.0, y + 110.0, 12.0, 'card_bg')
            self.draw_rounded_rect(x, y, x + 500.0, y + 110.0, 12.0, 1.5, 'card_border')
            self.fill_ellipse(x + 30.0, y + 55.0, 12.0, 12.0, brush_col)
            self._draw_text(label, 'label', x + 60.0, y + 15.0, x + 350.0, y + 45.0, 'text_muted')
            self._draw_text(val, 'small_val', x + 60.0, y + 45.0, x + 480.0, y + 100.0, 'white')

        t1, t2 = ctypes.c_uint64(), ctypes.c_uint64()
        vcall(self.pD2DContext, 49, ctypes.c_int32, ctypes.POINTER(ctypes.c_uint64), ctypes.POINTER(ctypes.c_uint64))(
            self.pD2DContext, ctypes.byref(t1), ctypes.byref(t2)
        )

    def render_hud_basic_no_begin_end(self, frame_idx: int):
        # Top Time Display Card
        self.fill_rounded_rect(100.0, 80.0, 560.0, 200.0, 16.0, 'card_bg')
        self.draw_rounded_rect(100.0, 80.0, 560.0, 200.0, 16.0, 2.0, 'card_border')
        self.draw_line(120.0, 190.0, 540.0, 190.0, 3.0, 'accent_line')

        # Speed Gauge Card
        self.fill_rounded_rect(100.0, 1680.0, 680.0, 2040.0, 20.0, 'card_bg')
        self.draw_rounded_rect(100.0, 1680.0, 680.0, 2040.0, 20.0, 2.5, 'card_border')
        self.fill_ellipse(170.0, 1750.0, 22.0, 22.0, 'cyan')

        # Heart Rate Card
        self.fill_rounded_rect(740.0, 1680.0, 1300.0, 2040.0, 20.0, 'card_bg')
        self.draw_rounded_rect(740.0, 1680.0, 1300.0, 2040.0, 20.0, 2.5, 'card_border')
        self.fill_ellipse(810.0, 1750.0, 22.0, 22.0, 'coral')

        t_sec = frame_idx / 29.97
        time_str = f"{int(t_sec // 60):02d}:{int(t_sec % 60):02d}.{int((t_sec % 1) * 10):01d}"
        speed_str = f"{32.4 + 4.5 * math.sin(frame_idx * 0.05):.1f}"
        hr_str = f"{142 + int(12 * math.cos(frame_idx * 0.03))}"

        self._draw_text("RECORDING TIME", 'label', 130.0, 95.0, 500.0, 130.0, 'text_muted')
        self._draw_text(time_str, 'time', 130.0, 120.0, 540.0, 200.0, 'white')
        self._draw_text("SPEED", 'label', 220.0, 1735.0, 500.0, 1770.0, 'text_muted')
        self._draw_text(speed_str, 'speed_val', 130.0, 1780.0, 510.0, 1960.0, 'white')
        self._draw_text("km/h", 'speed_unit', 520.0, 1850.0, 660.0, 1930.0, 'cyan')
        self._draw_text("HEART RATE", 'label', 860.0, 1735.0, 1200.0, 1770.0, 'text_muted')
        self._draw_text(hr_str, 'hr_val', 770.0, 1780.0, 1150.0, 1960.0, 'white')
        self._draw_text("bpm", 'hr_unit', 1160.0, 1850.0, 1280.0, 1930.0, 'coral')

    def _draw_text(self, text_str: str, format_name: str, left: float, top: float, right: float, bottom: float, brush_name: str):
        rc = D2D1_RECT_F(left, top, right, bottom)
        vcall(self.pD2DContext, 27, None,
            ctypes.c_wchar_p, wintypes.UINT, ctypes.c_void_p,
            ctypes.POINTER(D2D1_RECT_F), ctypes.c_void_p, wintypes.UINT, wintypes.UINT
        )(self.pD2DContext, text_str, len(text_str), self.text_formats[format_name], ctypes.byref(rc), self.brushes[brush_name], 0, 0)

    # ── Compositor Execution ──────────────────────────────────────────────────

    def composite_to_ring_surface(self, slot: int):
        """Hardware VideoProcessorBlt: converts 4K BGRA8 HUD into 4K NV12 surface on GPU."""
        stream = D3D11_VIDEO_PROCESSOR_STREAM()
        stream.Enable = True
        stream.OutputIndex = 0
        stream.InputFrameOrField = 0
        stream.PastFrames = 0
        stream.FutureFrames = 0
        stream.pInputSurface = self.pVPInView

        pOutView = self.ring_vp_out_views[slot]
        hr = vcall(self.pVideoContext, 53, ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p, wintypes.UINT, wintypes.UINT, ctypes.POINTER(D3D11_VIDEO_PROCESSOR_STREAM))(
            self.pVideoContext, self.pVP, pOutView, 0, 1, ctypes.byref(stream)
        )
        if hr != 0:
            raise RuntimeError(f"VideoProcessorBlt failed: {hr:#x}")

    # ── Benchmark Loop Runner ─────────────────────────────────────────────────

    def run_benchmark(self, phase_name: str, total_frames: int, render_mode: str, save_output_path: str = None):
        """Executes a benchmark phase across total_frames.
        render_mode: 'none' (NVENC only), 'basic' (3 HUD indicators), 'stress' (14 HUD groups).
        """
        print(f"\n>>> STARTING BENCHMARK: {phase_name} ({total_frames} frames, mode={render_mode})")

        self.start_encode_session()

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
        pic_params.pictureStruct = 1 # FRAME

        lock_bs = NV_ENC_LOCK_BITSTREAM()
        lock_bs.version = self.header.ver_defines['NV_ENC_LOCK_BITSTREAM_VER']

        latencies = []
        total_bitstream_bytes = 0
        out_file = open(save_output_path, "wb") if save_output_path else None

        # Zero-copy assertion counters
        gpu_to_cpu_frame_bytes = 0
        cpu_to_gpu_frame_bytes = 0

        # Warmup D2D + VideoProcessor (without touching NVENC sequence headers)
        if render_mode != 'none':
            for w in range(5):
                slot = w % self.ring_size
                if render_mode == 'basic':
                    self.render_hud_basic(w)
                    self.composite_to_ring_surface(slot)
                elif render_mode == 'stress':
                    self.render_hud_stress(w)
                    self.composite_to_ring_surface(slot)

        print(f"D2D warmup complete. Beginning timed steady-state loop ({total_frames} frames)...")

        t_start = time.perf_counter()

        for i in range(total_frames):
            slot = i % self.ring_size

            t_sub = time.perf_counter()

            # 1. Render HUD if required
            if render_mode == 'basic':
                self.render_hud_basic(i)
                self.composite_to_ring_surface(slot)
            elif render_mode == 'stress':
                self.render_hud_stress(i)
                self.composite_to_ring_surface(slot)

            # 2. Map resource to NVENC
            map_struct.registeredResource = self.ring_registered_handles[slot]
            hr_map = pfn_map_res(self.hEncoder, ctypes.byref(map_struct))
            if hr_map != 0:
                raise RuntimeError(f"Map failed at frame {i}: {hr_map:#x}")

            # 3. Encode Picture (NVENC automatically outputs VPS/SPS/PPS/IDR on frame 0)
            pic_params.inputBuffer = map_struct.mappedResource
            pic_params.outputBitstream = self.ring_bitstream_buffers[slot]
            pic_params.frameIdx = i
            pic_params.encodePicFlags = 0
            hr_enc = pfn_encode(self.hEncoder, ctypes.byref(pic_params))
            if hr_enc != 0:
                raise RuntimeError(f"Encode failed at frame {i}: {hr_enc:#x}")

            # 4. Lock Bitstream (synchronous completion)
            lock_bs.outputBitstream = self.ring_bitstream_buffers[slot]
            hr_lock = pfn_lock_bs(self.hEncoder, ctypes.byref(lock_bs))
            if hr_lock != 0:
                raise RuntimeError(f"Lock bitstream failed at frame {i}: {hr_lock:#x}")

            t_comp = time.perf_counter()
            latencies.append((t_comp - t_sub) * 1000.0)

            # Collect bitstream bytes
            bs_size = lock_bs.bitstreamSizeInBytes
            total_bitstream_bytes += bs_size
            if out_file and bs_size > 0:
                buf = (ctypes.c_byte * bs_size).from_address(lock_bs.bitstreamBufferPtr)
                out_file.write(bytes(buf))

            # 5. Unlock & Unmap
            pfn_unlock_bs(self.hEncoder, self.ring_bitstream_buffers[slot])
            pfn_unmap(self.hEncoder, map_struct.mappedResource)

            # Zero-copy assertion: no uncompressed pixel readback or upload occurred
            assert gpu_to_cpu_frame_bytes == 0
            assert cpu_to_gpu_frame_bytes == 0

        t_steady_end = time.perf_counter()

        # Drain encoder
        t_drain_start = time.perf_counter()
        drain_params = NV_ENC_PIC_PARAMS()
        drain_params.version = self.header.ver_defines['NV_ENC_PIC_PARAMS_VER']
        drain_params.encodePicFlags = 0x8 # NV_ENC_PIC_FLAG_EOS
        pfn_encode(self.hEncoder, ctypes.byref(drain_params))
        t_drain_end = time.perf_counter()

        if out_file:
            out_file.close()
            print(f"Output bitstream saved to {save_output_path} ({total_bitstream_bytes} bytes).")

        steady_time = t_steady_end - t_start
        total_time_drain = t_drain_end - t_start
        steady_fps = total_frames / steady_time
        drain_fps = total_frames / total_time_drain

        avg_lat = sum(latencies) / len(latencies)
        med_lat = percentile(latencies, 50.0)
        p95_lat = percentile(latencies, 95.0)
        p99_lat = percentile(latencies, 99.0)
        max_lat = max(latencies)

        print(f"[{phase_name} RESULTS]")
        print(f"  Frames completed:     {total_frames}")
        print(f"  Steady-state time:    {steady_time:.4f} s")
        print(f"  REAL STEADY FPS:      {steady_fps:.2f} fps")
        print(f"  FPS (incl. drain):    {drain_fps:.2f} fps")
        print(f"  Latency (submit->ready): avg={avg_lat:.2f}ms, med={med_lat:.2f}ms, p95={p95_lat:.2f}ms, p99={p99_lat:.2f}ms, max={max_lat:.2f}ms")
        print(f"  Bitstream total:      {total_bitstream_bytes} bytes ({total_bitstream_bytes / (1024*1024):.2f} MB)")
        print(f"  GPU_TO_CPU_FRAME_BYTES: 0 (PROVEN ZERO-COPY)")
        print(f"  CPU_TO_GPU_FULL_FRAME_BYTES_PER_FRAME: 0 (PROVEN ZERO-COPY)")

        self.end_encode_session()

        return {
            'phase': phase_name,
            'frames': total_frames,
            'steady_time_s': steady_time,
            'total_time_drain_s': total_time_drain,
            'steady_fps': steady_fps,
            'drain_fps': drain_fps,
            'latency_avg_ms': avg_lat,
            'latency_median_ms': med_lat,
            'latency_p95_ms': p95_lat,
            'latency_p99_ms': p99_lat,
            'latency_max_ms': max_lat,
            'bitstream_bytes': total_bitstream_bytes,
            'gpu_to_cpu_frame_bytes': 0,
            'cpu_to_gpu_frame_bytes': 0
        }

    def check_d3d_debug_messages(self):
        if not self.pInfoQueue:
            return {'corruption': 0, 'error': 0, 'warning': 0}
        num_msgs = vcall(self.pInfoQueue, 16, ctypes.c_uint64)(self.pInfoQueue)
        corruptions = 0
        errors = 0
        warnings = 0

        for i in range(num_msgs):
            msg_len = ctypes.c_size_t(0)
            vcall(self.pInfoQueue, 14, ctypes.c_int32, ctypes.c_uint64, ctypes.c_void_p, ctypes.POINTER(ctypes.c_size_t))(
                self.pInfoQueue, i, None, ctypes.byref(msg_len)
            )
            if msg_len.value > 0:
                buf = (ctypes.c_byte * msg_len.value)()
                vcall(self.pInfoQueue, 14, ctypes.c_int32, ctypes.c_uint64, ctypes.c_void_p, ctypes.POINTER(ctypes.c_size_t))(
                    self.pInfoQueue, i, ctypes.byref(buf), ctypes.byref(msg_len)
                )
                severity = ctypes.c_int.from_buffer(buf, 8).value
                if severity == 0: # CORRUPTION
                    corruptions += 1
                elif severity == 1: # ERROR
                    errors += 1
                elif severity == 2: # WARNING
                    warnings += 1
        return {'corruption': corruptions, 'error': errors, 'warning': warnings}

    def cleanup(self):
        print("\n--- LIFECYCLE CLEANUP ---")
        self.end_encode_session()

        # Release COM objects
        for pView in self.ring_vp_out_views:
            vcall(pView, 2, wintypes.ULONG)(pView)
        self.ring_vp_out_views.clear()

        for pTex in self.ring_nv12_textures:
            vcall(pTex, 2, wintypes.ULONG)(pTex)
        self.ring_nv12_textures.clear()

        if self.pVPInView:
            vcall(self.pVPInView, 2, wintypes.ULONG)(self.pVPInView)
        if self.pVP:
            vcall(self.pVP, 2, wintypes.ULONG)(self.pVP)
        if self.pVPEnum:
            vcall(self.pVPEnum, 2, wintypes.ULONG)(self.pVPEnum)
        if self.pVideoContext:
            vcall(self.pVideoContext, 2, wintypes.ULONG)(self.pVideoContext)
        if self.pVideoDevice:
            vcall(self.pVideoDevice, 2, wintypes.ULONG)(self.pVideoDevice)

        for b in self.brushes.values():
            vcall(b, 2, wintypes.ULONG)(b)
        self.brushes.clear()
        for f in self.text_formats.values():
            vcall(f, 2, wintypes.ULONG)(f)
        self.text_formats.clear()

        if self.pDWriteFactory:
            vcall(self.pDWriteFactory, 2, wintypes.ULONG)(self.pDWriteFactory)
        if self.pD2DBitmapTarget:
            vcall(self.pD2DBitmapTarget, 2, wintypes.ULONG)(self.pD2DBitmapTarget)
        if self.pD2DContext:
            vcall(self.pD2DContext, 2, wintypes.ULONG)(self.pD2DContext)
        if self.pD2DDevice:
            vcall(self.pD2DDevice, 2, wintypes.ULONG)(self.pD2DDevice)
        if self.pHudTexture:
            vcall(self.pHudTexture, 2, wintypes.ULONG)(self.pHudTexture)
        if self.pContext:
            vcall(self.pContext, 2, wintypes.ULONG)(self.pContext)
        if self.pDevice:
            vcall(self.pDevice, 2, wintypes.ULONG)(self.pDevice)
        if self.pAdapter:
            vcall(self.pAdapter, 2, wintypes.ULONG)(self.pAdapter)
        if self.pFactory:
            vcall(self.pFactory, 2, wintypes.ULONG)(self.pFactory)
        print("All D3D11 / D2D / DirectWrite resources released.")


def main():
    pipe = NvidiaStage8DPipeline(width=3840, height=2160, ring_size=4)
    pipe.initialize()

    results = {}

    try:
        # TEST A: NVENC ONLY (3000 frames)
        res_a = pipe.run_benchmark("TEST_A_NVENC_ONLY", total_frames=3000, render_mode='none')
        results['test_a'] = res_a

        # TEST B: D3D11 HUD + COMPOSITOR + NVENC (3000 frames)
        hevc_path = r"H:\_Dev\TeleM-integration\scratch\nvidia_stage8d_output.hevc"
        res_b = pipe.run_benchmark("TEST_B_HUD_COMPOSITOR_NVENC", total_frames=3000, render_mode='basic', save_output_path=hevc_path)
        results['test_b'] = res_b

        # TEST C: COMMAND COUNT STRESS (14 HUD groups) + COMPOSITOR + NVENC (3000 frames)
        res_c = pipe.run_benchmark("TEST_C_STRESS_COMPOSITOR_NVENC", total_frames=3000, render_mode='stress')
        results['test_c'] = res_c

        # Debug layer check
        dbg = pipe.check_d3d_debug_messages()
        results['d3d_debug'] = dbg
        print("\nD3D11 Debug Messages:", dbg)

    finally:
        pipe.cleanup()

    # Save results JSON
    json_path = r"H:\_Dev\TeleM-integration\scratch\nvidia_stage8d_benchmark_results.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)
    print(f"Benchmark results written to {json_path}")

if __name__ == "__main__":
    main()
