#include "d3d11_nvenc_pipeline.h"
#include <iostream>
#include <iomanip>
#include <algorithm>

// Static GUID definitions
static const GUID GUID_IID_ID3D11Multithread = { 0x9B7E4E00, 0x342C, 0x4106, { 0xA1, 0x9F, 0x4F, 0x27, 0x04, 0xF6, 0x89, 0xF0 } };
static const GUID GUID_IID_IMFDXGIBuffer     = { 0xE7174CFA, 0x1C9E, 0x48B1, { 0x88, 0x66, 0x62, 0x62, 0x26, 0xBF, 0xC2, 0x58 } };
static const GUID GUID_IID_IDXGIAdapter3     = { 0x645967A4, 0x1392, 0x4310, { 0xA7, 0x98, 0x80, 0x53, 0xCE, 0x3E, 0x93, 0xFD } };
static const GUID GUID_MF_SOURCE_READER_D3D_MANAGER = { 0xEC822DA2, 0xE1E9, 0x4B29, { 0xA0, 0xD8, 0x56, 0x3C, 0x71, 0x9F, 0x52, 0x69 } };
static const GUID GUID_MF_READWRITE_ENABLE_HARDWARE_TRANSFORMS = { 0xA634A91C, 0x822B, 0x41B9, { 0xA4, 0x94, 0x4D, 0xE4, 0x64, 0x36, 0x12, 0xB0 } };
static const GUID GUID_MF_SOURCE_READER_ENABLE_ADVANCED_VIDEO_PROCESSING = { 0x0F81DA2C, 0xB537, 0x4672, { 0xA8, 0xB2, 0xA6, 0x81, 0xB1, 0x73, 0x07, 0xA3 } };
static const GUID GUID_MFVideoFormat_P010    = { 0x30313050, 0x0000, 0x0010, { 0x80, 0x00, 0x00, 0xAA, 0x00, 0x38, 0x9B, 0x71 } };

static bool IsStage8L4C2MfLogEnabled() {
    char value[8] = {};
    DWORD size = GetEnvironmentVariableA("TELEM_STAGE8L4C2_MF_LOG", value, (DWORD)sizeof(value));
    return size > 0 && size < sizeof(value) && value[0] == '1';
}

static void LogMfMediaType(FILE* file, const char* label, IMFMediaType* type) {
    if (!file || !type) return;
    GUID subtype{};
    UINT32 width = 0, height = 0, fps_num = 0, fps_den = 0;
    HRESULT subtype_hr = type->GetGUID(MF_MT_SUBTYPE, &subtype);
    HRESULT size_hr = MFGetAttributeSize(type, MF_MT_FRAME_SIZE, &width, &height);
    HRESULT fps_hr = MFGetAttributeRatio(type, MF_MT_FRAME_RATE, &fps_num, &fps_den);
    fprintf(file,
            "%s subtype_hr=0x%08X subtype={%08X-%04X-%04X-%02X%02X-%02X%02X%02X%02X%02X%02X} "
            "frame_size_hr=0x%08X width=%u height=%u frame_rate_hr=0x%08X fps=%u/%u\n",
            label, (unsigned int)subtype_hr,
            (unsigned int)subtype.Data1, (unsigned int)subtype.Data2, (unsigned int)subtype.Data3,
            (unsigned int)subtype.Data4[0], (unsigned int)subtype.Data4[1],
            (unsigned int)subtype.Data4[2], (unsigned int)subtype.Data4[3],
            (unsigned int)subtype.Data4[4], (unsigned int)subtype.Data4[5],
            (unsigned int)subtype.Data4[6], (unsigned int)subtype.Data4[7],
            (unsigned int)size_hr, width, height, (unsigned int)fps_hr, fps_num, fps_den);
}

// Direct2D factory creation typedef
typedef HRESULT (WINAPI *PFN_D2D1CreateDevice)(IDXGIDevice*, const D2D1_CREATION_PROPERTIES*, ID2D1Device**);
typedef HRESULT (WINAPI *PFN_DWriteCreateFactory)(DWRITE_FACTORY_TYPE, REFIID, IUnknown**);
#include <smmintrin.h>

static void FastCopyFromGpuStaging(uint8_t* dst, const uint8_t* src, size_t rowBytes, size_t rowPitch, uint32_t height) {
    bool aligned = (((uintptr_t)src % 16) == 0) && ((rowPitch % 16) == 0);
    for (uint32_t r = 0; r < height; ++r) {
        const uint8_t* rowSrc = src + r * rowPitch;
        uint8_t* rowDst = dst + r * rowBytes;
        if (aligned) {
            size_t nBlocks = rowBytes / 16;
            size_t remainder = rowBytes % 16;
            const __m128i* pSrcVec = (const __m128i*)rowSrc;
            __m128i* pDstVec = (__m128i*)rowDst;
            for (size_t b = 0; b < nBlocks; ++b) {
                __m128i val = _mm_stream_load_si128(const_cast<__m128i*>(pSrcVec + b));
                _mm_storeu_si128(pDstVec + b, val);
            }
            if (remainder > 0) {
                memcpy(rowDst + nBlocks * 16, rowSrc + nBlocks * 16, remainder);
            }
        } else {
            memcpy(rowDst, rowSrc, rowBytes);
        }
    }
}

static double GetQpcTimeSec() {
    static LARGE_INTEGER freq = {};
    if (freq.QuadPart == 0) QueryPerformanceFrequency(&freq);
    LARGE_INTEGER counter;
    QueryPerformanceCounter(&counter);
    return (double)counter.QuadPart / (double)freq.QuadPart;
}

static double CalcPercentile(std::vector<double>& v, double p) {
    if (v.empty()) return 0.0;
    std::sort(v.begin(), v.end());
    double k = (v.size() - 1) * (p / 100.0);
    size_t f = (size_t)std::floor(k);
    size_t c = (size_t)std::ceil(k);
    if (f == c) return v[f];
    return v[f] * (c - k) + v[c] * (k - f);
}

D3D11NvencPipeline::D3D11NvencPipeline()
    : m_configured(false), m_video_opened(false)
    , m_current_clip_idx(0), m_clip_frames_decoded(0), m_clip_switch_ms(0.0)
    , m_pPendingSample(nullptr)
    , m_pFactory(nullptr), m_pAdapter(nullptr), m_pAdapter3(nullptr)
    , m_pDevice(nullptr), m_pContext(nullptr)
    , m_pHudTexture(nullptr), m_pStagingHudTex(nullptr), m_pD2DDevice(nullptr), m_pD2DContext(nullptr)
    , m_pDWriteFactory(nullptr)
    , m_fmt_time(nullptr), m_fmt_speed_val(nullptr), m_fmt_speed_unit(nullptr)
    , m_fmt_hr_val(nullptr), m_fmt_hr_unit(nullptr), m_fmt_label(nullptr)
    , m_brush_white(nullptr), m_brush_text_muted(nullptr), m_brush_cyan(nullptr)
    , m_brush_coral(nullptr), m_brush_card_bg(nullptr), m_brush_card_border(nullptr)
    , m_pVideoDevice(nullptr), m_pVideoContext(nullptr)
    , m_pVPEnum(nullptr), m_pVP(nullptr)
    , m_pHudSyncStagingTex(nullptr)
    , m_pDevMgr(nullptr), m_pReaderAttributes(nullptr), m_pSourceReader(nullptr)
    , m_decoder_eof(false)
    , m_hNvencDll(nullptr), m_hEncoder(nullptr)
    , m_is_active(false), m_cancel_requested(false), m_is_finished(false)
{
    memset(&m_config, 0, sizeof(m_config));
    memset(&m_adapter_desc, 0, sizeof(m_adapter_desc));
    memset(&m_nvenc, 0, sizeof(m_nvenc));
    memset(&m_preset_cfg, 0, sizeof(m_preset_cfg));
    memset(&m_progress, 0, sizeof(m_progress));
    memset(&m_stats, 0, sizeof(m_stats));

    m_enable_compression_analysis = false;
    m_compression_csv_file = nullptr;
    memset(&m_live_compression_stats, 0, sizeof(m_live_compression_stats));
    m_i_frame_qp_sum = 0;
    m_p_frame_qp_sum = 0;
    m_b_frame_qp_sum = 0;
    m_total_qp_sum = 0;

    m_preview_tap_enabled = false;
    m_preview_tap_width = 960;
    m_preview_tap_height = 540;
    m_preview_interval_sec = 0.125;
    m_preview_last_submit_time = 0.0;
    m_pPreviewVPEnum = nullptr;
    m_pPreviewVP = nullptr;
    for (int i = 0; i < 2; ++i) {
        m_preview_output_tex[i] = nullptr;
        m_preview_output_view[i] = nullptr;
        m_preview_staging_tex[i] = nullptr;
        m_preview_query[i] = nullptr;
    }
    m_preview_capture_in_flight = false;
    m_preview_in_flight_slot = 0;
    m_preview_in_flight_frame = 0;
    m_preview_in_flight_pts = 0.0;
    m_preview_next_slot = 0;
    m_preview_has_new_frame = false;
    m_preview_ready_frame_idx = 0;
    m_preview_ready_pts = 0.0;

    CoInitializeEx(NULL, COINIT_MULTITHREADED);
    MFStartup(MF_VERSION, MFSTARTUP_NOSOCKET);
}

D3D11NvencPipeline::~D3D11NvencPipeline() {
    Destroy();
    MFShutdown();
    CoUninitialize();
}

bool D3D11NvencPipeline::Configure(const TelemNvencConfig& config) {
    if (m_is_active) return false;
    m_config = config;

    // Synchronize bit depth from encoder_config if specified
    if (m_config.encoder_config.bit_depth != 0) {
        m_config.bit_depth = m_config.encoder_config.bit_depth;
    }
    if (m_config.bit_depth == 0) m_config.bit_depth = 10;

    // Compression analysis setup (Stage 8K.5)
    m_enable_compression_analysis = (m_config.encoder_config.enable_compression_analysis != 0);
    m_compression_csv_path.clear();
    if (m_config.encoder_config.compression_csv_path[0] != L'\0') {
        m_compression_csv_path = m_config.encoder_config.compression_csv_path;
    }
    m_compression_samples.clear();
    if (m_enable_compression_analysis) {
        m_compression_samples.reserve(60000);
    }
    memset(&m_live_compression_stats, 0, sizeof(m_live_compression_stats));
    m_live_compression_stats.is_active = m_enable_compression_analysis ? 1 : 0;
    m_live_compression_stats.is_av1 = (m_config.encoder_config.codec == TELEM_CODEC_AV1) ? 1 : 0;
    m_i_frame_qp_sum = 0;
    m_p_frame_qp_sum = 0;
    m_b_frame_qp_sum = 0;
    m_total_qp_sum = 0;

    // Ring size for persistent D3D11 textures (needs >= 64 for lookahead 25 + 7 B-frames)
    uint32_t min_ring = 64;
    if (m_config.ring_size < min_ring) m_config.ring_size = min_ring;

    if (m_config.fps_den == 0) m_config.fps_den = 1001;
    if (m_config.fps_num == 0) m_config.fps_num = 30000;
    if (m_config.width == 0) m_config.width = 3840;
    if (m_config.height == 0) m_config.height = 2160;

    if (!SelectAdapter()) return false;
    if (!CreateDevice()) return false;
    if (!CreateHudResources()) return false;
    if (!CreateDWrite()) return false;
    if (!CreateBrushes()) return false;
    if (!CreateVideoProcessor()) return false;
    if (!CreateRingResources()) return false;

    m_configured = true;
    return true;
}

bool D3D11NvencPipeline::SelectAdapter() {
    SafeRelease(m_pFactory);
    SafeRelease(m_pAdapter);
    SafeRelease(m_pAdapter3);

    HRESULT hr = CreateDXGIFactory1(__uuidof(IDXGIFactory1), (void**)&m_pFactory);
    if (FAILED(hr)) return false;

    UINT idx = 0;
    IDXGIAdapter1* pAdapter = nullptr;
    while (m_pFactory->EnumAdapters1(idx, &pAdapter) != DXGI_ERROR_NOT_FOUND) {
        DXGI_ADAPTER_DESC desc;
        pAdapter->GetDesc(&desc);
        if (desc.VendorId == 0x10DE) { // NVIDIA
            m_pAdapter = pAdapter;
            m_adapter_desc = desc;
            break;
        }
        pAdapter->Release();
        idx++;
    }

    if (!m_pAdapter) return false;

    m_pAdapter->QueryInterface(__uuidof(IDXGIAdapter3), (void**)&m_pAdapter3);
    return true;
}

bool D3D11NvencPipeline::CreateDevice() {
    SafeRelease(m_pContext);
    SafeRelease(m_pDevice);

    // Keep the device flags used by the validated P010 Source Reader path.
    // Stage 8L.4C.2 proved that host access to the MF/GPU decoder, rather than
    // an encoder profile or additional D3D11 creation flag, is the gate here.
    UINT flags = D3D11_CREATE_DEVICE_BGRA_SUPPORT;
    if (m_config.enable_debug_layer) {
        flags |= D3D11_CREATE_DEVICE_DEBUG;
    }

    D3D_FEATURE_LEVEL levels[] = { D3D_FEATURE_LEVEL_11_1, D3D_FEATURE_LEVEL_11_0 };
    D3D_FEATURE_LEVEL flOut;

    HRESULT hr = D3D11CreateDevice(
        m_pAdapter,
        D3D_DRIVER_TYPE_UNKNOWN,
        NULL,
        flags,
        levels,
        2,
        D3D11_SDK_VERSION,
        &m_pDevice,
        &flOut,
        &m_pContext
    );

    if (FAILED(hr) && (flags & D3D11_CREATE_DEVICE_DEBUG)) {
        // Fallback without debug layer
        flags &= ~D3D11_CREATE_DEVICE_DEBUG;
        hr = D3D11CreateDevice(m_pAdapter, D3D_DRIVER_TYPE_UNKNOWN, NULL, flags, levels, 2, D3D11_SDK_VERSION, &m_pDevice, &flOut, &m_pContext);
    }

    if (FAILED(hr)) return false;

    if (IsStage8L4C2MfLogEnabled()) {
        CreateDirectoryA("scratch", NULL);
        CreateDirectoryA("scratch/stage8l4c2_logs", NULL);
        FILE* file = fopen("scratch/stage8l4c2_logs/mf_media_types.txt", "w");
        if (file) {
            fprintf(file, "stage=NVIDIA_8L4C2\n");
            fprintf(file, "d3d11_create_flags=0x%08X BGRA_SUPPORT=1 VIDEO_SUPPORT=0 create_hr=0x%08X\n",
                    flags, (unsigned int)hr);
            fclose(file);
        }
    }

    // Enable multithread protection
    ID3D10Multithread* pMultithread = nullptr;
    if (SUCCEEDED(m_pDevice->QueryInterface(__uuidof(ID3D10Multithread), (void**)&pMultithread))) {
        pMultithread->SetMultithreadProtected(TRUE);
        pMultithread->Release();
    }

    return true;
}

bool D3D11NvencPipeline::CreateHudResources() {
    SafeRelease(m_pD2DContext);
    SafeRelease(m_pD2DDevice);

    IDXGIDevice* pDxgiDevice = nullptr;
    HRESULT hr = m_pDevice->QueryInterface(__uuidof(IDXGIDevice), (void**)&pDxgiDevice);
    if (FAILED(hr)) return false;

    HMODULE hD2D = LoadLibraryW(L"d2d1.dll");
    if (!hD2D) { pDxgiDevice->Release(); return false; }
    PFN_D2D1CreateDevice pfnCreateDevice = (PFN_D2D1CreateDevice)GetProcAddress(hD2D, "D2D1CreateDevice");
    if (!pfnCreateDevice) { pDxgiDevice->Release(); return false; }

    hr = pfnCreateDevice(pDxgiDevice, NULL, &m_pD2DDevice);
    pDxgiDevice->Release();
    if (FAILED(hr)) return false;

    hr = m_pD2DDevice->CreateDeviceContext(D2D1_DEVICE_CONTEXT_OPTIONS_NONE, &m_pD2DContext);
    if (FAILED(hr)) return false;

    m_pD2DContext->SetAntialiasMode(D2D1_ANTIALIAS_MODE_PER_PRIMITIVE);
    m_pD2DContext->SetTextAntialiasMode(D2D1_TEXT_ANTIALIAS_MODE_GRAYSCALE);

    return true;
}

bool D3D11NvencPipeline::CreateDWrite() {
    SafeRelease(m_fmt_time);
    SafeRelease(m_fmt_speed_val);
    SafeRelease(m_fmt_speed_unit);
    SafeRelease(m_fmt_hr_val);
    SafeRelease(m_fmt_hr_unit);
    SafeRelease(m_fmt_label);
    SafeRelease(m_pDWriteFactory);

    HMODULE hDWrite = LoadLibraryW(L"dwrite.dll");
    if (!hDWrite) return false;
    PFN_DWriteCreateFactory pfnCreateFactory = (PFN_DWriteCreateFactory)GetProcAddress(hDWrite, "DWriteCreateFactory");
    if (!pfnCreateFactory) return false;

    HRESULT hr = pfnCreateFactory(DWRITE_FACTORY_TYPE_SHARED, __uuidof(IDWriteFactory), (IUnknown**)&m_pDWriteFactory);
    if (FAILED(hr)) return false;

    m_pDWriteFactory->CreateTextFormat(L"Segoe UI", NULL, DWRITE_FONT_WEIGHT_BOLD, DWRITE_FONT_STYLE_NORMAL, DWRITE_FONT_STRETCH_NORMAL, 68.0f, L"en-us", &m_fmt_time);
    m_pDWriteFactory->CreateTextFormat(L"Segoe UI", NULL, DWRITE_FONT_WEIGHT_BOLD, DWRITE_FONT_STYLE_NORMAL, DWRITE_FONT_STRETCH_NORMAL, 112.0f, L"en-us", &m_fmt_speed_val);
    m_pDWriteFactory->CreateTextFormat(L"Segoe UI", NULL, DWRITE_FONT_WEIGHT_SEMI_BOLD, DWRITE_FONT_STYLE_NORMAL, DWRITE_FONT_STRETCH_NORMAL, 36.0f, L"en-us", &m_fmt_speed_unit);
    m_pDWriteFactory->CreateTextFormat(L"Segoe UI", NULL, DWRITE_FONT_WEIGHT_BOLD, DWRITE_FONT_STYLE_NORMAL, DWRITE_FONT_STRETCH_NORMAL, 112.0f, L"en-us", &m_fmt_hr_val);
    m_pDWriteFactory->CreateTextFormat(L"Segoe UI", NULL, DWRITE_FONT_WEIGHT_SEMI_BOLD, DWRITE_FONT_STYLE_NORMAL, DWRITE_FONT_STRETCH_NORMAL, 36.0f, L"en-us", &m_fmt_hr_unit);
    m_pDWriteFactory->CreateTextFormat(L"Segoe UI", NULL, DWRITE_FONT_WEIGHT_SEMI_BOLD, DWRITE_FONT_STYLE_NORMAL, DWRITE_FONT_STRETCH_NORMAL, 26.0f, L"en-us", &m_fmt_label);
    m_font_cache.Init(m_pDWriteFactory);
    m_icon_cache.Init();

    return true;
}

bool D3D11NvencPipeline::CreateBrushes() {
    SafeRelease(m_brush_white);
    SafeRelease(m_brush_text_muted);
    SafeRelease(m_brush_cyan);
    SafeRelease(m_brush_coral);
    SafeRelease(m_brush_card_bg);
    SafeRelease(m_brush_card_border);

    if (!m_pD2DContext) return false;

    m_pD2DContext->CreateSolidColorBrush(D2D1::ColorF(1.0f, 1.0f, 1.0f, 1.0f), &m_brush_white);
    m_pD2DContext->CreateSolidColorBrush(D2D1::ColorF(0.75f, 0.82f, 0.90f, 0.90f), &m_brush_text_muted);
    m_pD2DContext->CreateSolidColorBrush(D2D1::ColorF(0.0f, 0.88f, 1.0f, 1.0f), &m_brush_cyan);
    m_pD2DContext->CreateSolidColorBrush(D2D1::ColorF(1.0f, 0.32f, 0.32f, 1.0f), &m_brush_coral);
    m_pD2DContext->CreateSolidColorBrush(D2D1::ColorF(0.04f, 0.06f, 0.10f, 0.68f), &m_brush_card_bg);
    m_pD2DContext->CreateSolidColorBrush(D2D1::ColorF(0.25f, 0.35f, 0.50f, 0.60f), &m_brush_card_border);

    return true;
}

bool D3D11NvencPipeline::CreateVideoProcessor() {
    SafeRelease(m_pVP);
    SafeRelease(m_pVPEnum);
    SafeRelease(m_pVideoContext);
    SafeRelease(m_pVideoDevice);

    HRESULT hr = m_pDevice->QueryInterface(__uuidof(ID3D11VideoDevice), (void**)&m_pVideoDevice);
    if (FAILED(hr)) return false;

    hr = m_pContext->QueryInterface(__uuidof(ID3D11VideoContext), (void**)&m_pVideoContext);
    if (FAILED(hr)) return false;

    D3D11_VIDEO_PROCESSOR_CONTENT_DESC vpDesc{};
    vpDesc.InputFrameFormat = D3D11_VIDEO_FRAME_FORMAT_PROGRESSIVE;
    vpDesc.InputFrameRate.Numerator = m_config.fps_num;
    vpDesc.InputFrameRate.Denominator = m_config.fps_den;
    vpDesc.InputWidth = m_config.width;
    vpDesc.InputHeight = m_config.height;
    vpDesc.OutputFrameRate.Numerator = m_config.fps_num;
    vpDesc.OutputFrameRate.Denominator = m_config.fps_den;
    vpDesc.OutputWidth = m_config.width;
    vpDesc.OutputHeight = m_config.height;
    vpDesc.Usage = D3D11_VIDEO_USAGE_PLAYBACK_NORMAL;

    hr = m_pVideoDevice->CreateVideoProcessorEnumerator(&vpDesc, &m_pVPEnum);
    if (FAILED(hr)) return false;

    hr = m_pVideoDevice->CreateVideoProcessor(m_pVPEnum, 0, &m_pVP);
    if (FAILED(hr)) return false;

    UINT formatFlags = 0;
    DXGI_FORMAT outFormat = (m_config.bit_depth == 10) ? DXGI_FORMAT_P010 : DXGI_FORMAT_NV12;
    HRESULT hrCheck = m_pVPEnum->CheckVideoProcessorFormat(outFormat, &formatFlags);
    if (SUCCEEDED(hrCheck)) {
        printf("[VP FORMAT %p] Format %s: 0x%X (Input: %d, Output: %d)\n",
               this,
               (outFormat == DXGI_FORMAT_P010) ? "P010" : "NV12",
               formatFlags,
               (formatFlags & D3D11_VIDEO_PROCESSOR_FORMAT_SUPPORT_INPUT) ? 1 : 0,
               (formatFlags & D3D11_VIDEO_PROCESSOR_FORMAT_SUPPORT_OUTPUT) ? 1 : 0);
        fflush(stdout);
    }

    return true;
}

bool D3D11NvencPipeline::CreateRingResources() {
    for (auto* pView : m_ring_vp_out_views) SafeRelease(pView);
    for (auto* pTex : m_ring_nv12_textures) SafeRelease(pTex);
    for (auto* pInView : m_ring_vp_in_view_huds) SafeRelease(pInView);
    for (auto* pTarget : m_ring_d2d_bitmap_targets) SafeRelease(pTarget);
    for (auto* pTex : m_ring_hud_textures) SafeRelease(pTex);
    for (auto* pTex : m_ring_hud_resolved_textures) SafeRelease(pTex);
    for (auto* pView : m_ring_preview_in_views) SafeRelease(pView);
    for (auto* pQuery : m_ring_hud_queries) SafeRelease(pQuery);
    for (auto* pQuery : m_ring_vp_queries) SafeRelease(pQuery);
    m_ring_vp_out_views.clear();
    m_ring_nv12_textures.clear();
    m_ring_vp_in_view_huds.clear();
    m_ring_d2d_bitmap_targets.clear();
    m_ring_hud_textures.clear();
    m_ring_hud_resolved_textures.clear();
    m_ring_preview_in_views.clear();
    m_ring_hud_queries.clear();
    m_ring_vp_queries.clear();
    m_pHudTexture = nullptr;

    D3D11_VIDEO_PROCESSOR_INPUT_VIEW_DESC inDesc{};
    inDesc.FourCC = 0;
    inDesc.ViewDimension = D3D11_VPIV_DIMENSION_TEXTURE2D;
    inDesc.Texture2D.MipSlice = 0;
    inDesc.Texture2D.ArraySlice = 0;

    for (UINT i = 0; i < m_config.ring_size; ++i) {
        // 1. Persistent NV12/P010 composite output texture & VP view
        DXGI_FORMAT outFormat = (m_config.bit_depth == 10) ? DXGI_FORMAT_P010 : DXGI_FORMAT_NV12;
        D3D11_TEXTURE2D_DESC desc{};
        desc.Width = m_config.width;
        desc.Height = m_config.height;
        desc.MipLevels = 1;
        desc.ArraySize = 1;
        desc.Format = outFormat;
        desc.SampleDesc.Count = 1;
        desc.SampleDesc.Quality = 0;
        desc.Usage = D3D11_USAGE_DEFAULT;
        desc.BindFlags = D3D11_BIND_RENDER_TARGET | D3D11_BIND_SHADER_RESOURCE;

        ID3D11Texture2D* pTex = nullptr;
        HRESULT hr = m_pDevice->CreateTexture2D(&desc, NULL, &pTex);
        if (FAILED(hr)) return false;
        m_ring_nv12_textures.push_back(pTex);

        D3D11_VIDEO_PROCESSOR_OUTPUT_VIEW_DESC outDesc{};
        outDesc.ViewDimension = D3D11_VPOV_DIMENSION_TEXTURE2D;
        outDesc.Texture2D.MipSlice = 0;

        ID3D11VideoProcessorOutputView* pOutView = nullptr;
        hr = m_pVideoDevice->CreateVideoProcessorOutputView(pTex, m_pVPEnum, &outDesc, &pOutView);
        if (FAILED(hr)) return false;
        m_ring_vp_out_views.push_back(pOutView);

        // 2. Persistent BGRA8 HUD texture & D2D target & VP input view for this slot
        D3D11_TEXTURE2D_DESC hudDesc{};
        hudDesc.Width = m_config.width;
        hudDesc.Height = m_config.height;
        hudDesc.MipLevels = 1;
        hudDesc.ArraySize = 1;
        hudDesc.Format = DXGI_FORMAT_B8G8R8A8_UNORM;
        hudDesc.SampleDesc.Count = 1;
        hudDesc.SampleDesc.Quality = 0;
        hudDesc.Usage = D3D11_USAGE_DEFAULT;
        hudDesc.BindFlags = D3D11_BIND_RENDER_TARGET | D3D11_BIND_SHADER_RESOURCE;

        ID3D11Texture2D* pHudTex = nullptr;
        hr = m_pDevice->CreateTexture2D(&hudDesc, NULL, &pHudTex);
        if (FAILED(hr)) return false;
        m_ring_hud_textures.push_back(pHudTex);

        IDXGISurface1* pDxgiSurface = nullptr;
        hr = pHudTex->QueryInterface(__uuidof(IDXGISurface1), (void**)&pDxgiSurface);
        if (FAILED(hr)) return false;

        D2D1_BITMAP_PROPERTIES1 bp{};
        bp.pixelFormat.format = DXGI_FORMAT_B8G8R8A8_UNORM;
        bp.pixelFormat.alphaMode = D2D1_ALPHA_MODE_PREMULTIPLIED;
        bp.dpiX = 96.0f;
        bp.dpiY = 96.0f;
        bp.bitmapOptions = D2D1_BITMAP_OPTIONS_TARGET | D2D1_BITMAP_OPTIONS_CANNOT_DRAW;

        ID2D1Bitmap1* pD2DTarget = nullptr;
        hr = m_pD2DContext->CreateBitmapFromDxgiSurface(pDxgiSurface, &bp, &pD2DTarget);
        pDxgiSurface->Release();
        if (FAILED(hr)) return false;
        m_ring_d2d_bitmap_targets.push_back(pD2DTarget);

        ID3D11VideoProcessorInputView* pVPInViewHUD = nullptr;
        hr = m_pVideoDevice->CreateVideoProcessorInputView(pHudTex, m_pVPEnum, &inDesc, &pVPInViewHUD);
        if (FAILED(hr)) {
            printf("[RING ERROR] CreateVideoProcessorInputView for pHudTex failed: 0x%08X\n", (unsigned int)hr);
            return false;
        }
        m_ring_vp_in_view_huds.push_back(pVPInViewHUD);

        // 3. Persistent GPU slot completion query fences (HUD & VP)
        D3D11_QUERY_DESC qDesc{};
        qDesc.Query = D3D11_QUERY_EVENT;
        qDesc.MiscFlags = 0;
        ID3D11Query* pHudQuery = nullptr;
        hr = m_pDevice->CreateQuery(&qDesc, &pHudQuery);
        if (FAILED(hr)) return false;
        m_ring_hud_queries.push_back(pHudQuery);

        ID3D11Query* pVpQuery = nullptr;
        hr = m_pDevice->CreateQuery(&qDesc, &pVpQuery);
        if (FAILED(hr)) return false;
        m_ring_vp_queries.push_back(pVpQuery);
    }

    SafeRelease(m_pStagingHudTex);
    D3D11_TEXTURE2D_DESC stagingDesc{};
    stagingDesc.Width = m_config.width;
    stagingDesc.Height = m_config.height;
    stagingDesc.MipLevels = 1;
    stagingDesc.ArraySize = 1;
    stagingDesc.Format = DXGI_FORMAT_B8G8R8A8_UNORM;
    stagingDesc.SampleDesc.Count = 1;
    stagingDesc.SampleDesc.Quality = 0;
    stagingDesc.Usage = D3D11_USAGE_STAGING;
    stagingDesc.BindFlags = 0;
    stagingDesc.CPUAccessFlags = D3D11_CPU_ACCESS_READ;
    stagingDesc.MiscFlags = 0;
    HRESULT hr = m_pDevice->CreateTexture2D(&stagingDesc, NULL, &m_pStagingHudTex);
    if (FAILED(hr)) {
        printf("[RING ERROR] CreateTexture2D for m_pStagingHudTex failed: 0x%08X\n", (unsigned int)hr);
        return false;
    }

    if (!m_ring_hud_textures.empty()) {
        m_pHudTexture = m_ring_hud_textures[0];
    }

    if (m_preview_tap_enabled) {
        if (!m_pPreviewVPEnum) {
            ConfigurePreviewTap(m_preview_tap_width, m_preview_tap_height, (m_preview_interval_sec > 0.0) ? (1.0 / m_preview_interval_sec) : 8.0);
        } else {
            for (auto* pView : m_ring_preview_in_views) SafeRelease(pView);
            m_ring_preview_in_views.clear();
            for (size_t i = 0; i < m_ring_nv12_textures.size(); ++i) {
                ID3D11VideoProcessorInputView* pInView = nullptr;
                HRESULT hr = m_pVideoDevice->CreateVideoProcessorInputView(m_ring_nv12_textures[i], m_pPreviewVPEnum, &inDesc, &pInView);
                if (SUCCEEDED(hr) && pInView) {
                    m_ring_preview_in_views.push_back(pInView);
                }
            }
        }
    }

    return true;
}

bool D3D11NvencPipeline::OpenVideo(const std::wstring& video_path) {
    if (m_is_active) return false;
    TelemVideoClipDesc desc{};
    wcsncpy_s(desc.path, video_path.c_str(), 511);
    desc.frame_count = 0;
    desc.fps_num = m_config.fps_num;
    desc.fps_den = m_config.fps_den;
    desc.global_start_frame = 0;
    desc.global_start_time = 0.0;
    return SetVideoSequence(&desc, 1);
}

bool D3D11NvencPipeline::SetVideoSequence(const TelemVideoClipDesc* clips, uint32_t count) {
    if (m_is_active || !clips || count == 0) return false;
    CloseDecoder();
    m_clips.assign(clips, clips + count);
    m_current_clip_idx = 0;
    m_clip_frames_decoded = 0;
    m_clip_switch_ms = 0.0;
    return OpenClip(0);
}

bool D3D11NvencPipeline::InitDecoder() {
    if (m_clips.empty()) return false;
    return OpenClip(0);
}

bool D3D11NvencPipeline::OpenClip(uint32_t clip_idx) {
    if (clip_idx >= m_clips.size()) return false;

    for (auto& pair : m_view_cache) {
        if (pair.second) pair.second->Release();
    }
    m_view_cache.clear();
    SafeRelease(m_pPendingSample);
    SafeRelease(m_pSourceReader);

    if (!m_pDevMgr) {
        UINT resetToken = 0;
        HRESULT hr = MFCreateDXGIDeviceManager(&resetToken, &m_pDevMgr);
        if (FAILED(hr)) {
            printf("[OPENCLIP ERROR] MFCreateDXGIDeviceManager hr=0x%08X\n", (unsigned int)hr);
            fflush(stdout);
            return false;
        }

        hr = m_pDevMgr->ResetDevice(m_pDevice, resetToken);
        if (FAILED(hr)) {
            printf("[OPENCLIP ERROR] ResetDevice hr=0x%08X\n", (unsigned int)hr);
            fflush(stdout);
            return false;
        }
    }

    if (!m_pReaderAttributes) {
        HRESULT hr = MFCreateAttributes(&m_pReaderAttributes, 4);
        if (FAILED(hr)) {
            printf("[OPENCLIP ERROR] MFCreateAttributes hr=0x%08X\n", (unsigned int)hr);
            fflush(stdout);
            return false;
        }

        HRESULT manager_hr = m_pReaderAttributes->SetUnknown(GUID_MF_SOURCE_READER_D3D_MANAGER, m_pDevMgr);
        HRESULT hardware_hr = m_pReaderAttributes->SetUINT32(GUID_MF_READWRITE_ENABLE_HARDWARE_TRANSFORMS, 1);
        HRESULT advanced_hr = m_pReaderAttributes->SetUINT32(GUID_MF_SOURCE_READER_ENABLE_ADVANCED_VIDEO_PROCESSING, 1);
        if (IsStage8L4C2MfLogEnabled()) {
            FILE* file = fopen("scratch/stage8l4c2_logs/mf_media_types.txt", "a");
            if (file) {
                fprintf(file, "reader_attributes D3D_MANAGER=0x%08X HARDWARE_TRANSFORMS=0x%08X ADVANCED_VIDEO_PROCESSING=0x%08X\n",
                        (unsigned int)manager_hr, (unsigned int)hardware_hr, (unsigned int)advanced_hr);
                fclose(file);
            }
        }
    }

    const auto& clip = m_clips[clip_idx];
    HRESULT hr = MFCreateSourceReaderFromURL(clip.path, m_pReaderAttributes, &m_pSourceReader);
    if (FAILED(hr)) {
        printf("[OPENCLIP ERROR] MFCreateSourceReaderFromURL clip=%u path=%ls hr=0x%08X\n", clip_idx, clip.path, (unsigned int)hr);
        fflush(stdout);
        return false;
    }

    m_pSourceReader->SetStreamSelection(MF_SOURCE_READER_ALL_STREAMS, FALSE);
    m_pSourceReader->SetStreamSelection(MF_SOURCE_READER_FIRST_VIDEO_STREAM, TRUE);

    IMFMediaType* pNativeMT = nullptr;
    hr = m_pSourceReader->GetNativeMediaType(MF_SOURCE_READER_FIRST_VIDEO_STREAM, 0, &pNativeMT);
    if (FAILED(hr)) {
        printf("[OPENCLIP ERROR] GetNativeMediaType clip=%u hr=0x%08X\n", clip_idx, (unsigned int)hr);
        fflush(stdout);
        return false;
    }

    FILE* pMfLog = nullptr;
    if (IsStage8L4C2MfLogEnabled()) {
        pMfLog = fopen("scratch/stage8l4c2_logs/mf_media_types.txt", "a");
        if (pMfLog) {
            fprintf(pMfLog, "clip=%u path=%ls\n", clip_idx, clip.path);
            LogMfMediaType(pMfLog, "native_type_0", pNativeMT);
        }
    }

    // Validate video format compatibility
    UINT32 width = 0, height = 0;
    MFGetAttributeSize(pNativeMT, MF_MT_FRAME_SIZE, &width, &height);
    if (m_config.width > 0 && m_config.height > 0) {
        if (width != m_config.width || height != m_config.height) {
            printf("[CLIP ERROR] Clip %u resolution mismatch: %ux%u vs config %ux%u\n",
                   clip_idx, width, height, m_config.width, m_config.height);
            fflush(stdout);
            if (pMfLog) fclose(pMfLog);
            pNativeMT->Release();
            return false;
        }
    }

    IMFMediaType* pDecMT = nullptr;
    hr = MFCreateMediaType(&pDecMT);
    if (FAILED(hr) || !pDecMT) {
        if (pMfLog) fclose(pMfLog);
        pNativeMT->Release();
        return false;
    }
    pNativeMT->CopyAllItems(pDecMT);
    pDecMT->SetGUID(MF_MT_SUBTYPE, GUID_MFVideoFormat_P010);
    pNativeMT->Release();
    LogMfMediaType(pMfLog, "requested_output", pDecMT);

    hr = m_pSourceReader->SetCurrentMediaType(MF_SOURCE_READER_FIRST_VIDEO_STREAM, NULL, pDecMT);
    pDecMT->Release();
    if (pMfLog) {
        fprintf(pMfLog, "SetCurrentMediaType(P010)=0x%08X\n", (unsigned int)hr);
        if (SUCCEEDED(hr)) {
            IMFMediaType* pCurrentMT = nullptr;
            HRESULT current_hr = m_pSourceReader->GetCurrentMediaType(MF_SOURCE_READER_FIRST_VIDEO_STREAM, &pCurrentMT);
            fprintf(pMfLog, "GetCurrentMediaType=0x%08X\n", (unsigned int)current_hr);
            if (SUCCEEDED(current_hr) && pCurrentMT) LogMfMediaType(pMfLog, "current_output", pCurrentMT);
            SafeRelease(pCurrentMT);
        }
        fclose(pMfLog);
        pMfLog = nullptr;
    }
    if (FAILED(hr)) {
        printf("[OPENCLIP ERROR] SetCurrentMediaType clip=%u subtype=P010 hr=0x%08X\n", clip_idx, (unsigned int)hr);
        fflush(stdout);
        return false;
    }

    m_current_clip_idx = clip_idx;
    m_clip_frames_decoded = 0;
    m_decoder_eof = false;
    m_video_opened = true;
    return true;
}

bool D3D11NvencPipeline::SwitchToNextClip() {
    if (m_current_clip_idx + 1 >= m_clips.size()) {
        return false;
    }
    auto t0 = std::chrono::high_resolution_clock::now();
    uint32_t next_idx = m_current_clip_idx + 1;
    bool ok = OpenClip(next_idx);
    auto t1 = std::chrono::high_resolution_clock::now();
    if (ok) {
        m_clip_switch_ms = std::chrono::duration<double, std::milli>(t1 - t0).count();
        printf("[CLIP SWITCH] Transitioned to clip %u in %.3f ms\n", next_idx, m_clip_switch_ms);
        fflush(stdout);
    }
    return ok;
}

bool D3D11NvencPipeline::SeekToGlobalFrame(uint32_t target_global_frame) {
    if (m_clips.empty()) return false;

    uint32_t target_clip_idx = 0;
    uint32_t target_local_frame = 0;
    bool found = false;

    for (size_t i = 0; i < m_clips.size(); ++i) {
        uint32_t start_f = m_clips[i].global_start_frame;
        uint32_t count = m_clips[i].frame_count;
        if (count > 0 && target_global_frame >= start_f && target_global_frame < start_f + count) {
            target_clip_idx = (uint32_t)i;
            target_local_frame = target_global_frame - start_f;
            found = true;
            break;
        }
    }

    if (!found && !m_clips.empty()) {
        target_clip_idx = 0;
        target_local_frame = target_global_frame;
    }

    if (m_current_clip_idx != target_clip_idx || !m_pSourceReader) {
        m_current_clip_idx = target_clip_idx;
        if (!OpenClip(m_current_clip_idx)) {
            return false;
        }
    }

    if (target_local_frame == 0) {
        m_clip_frames_decoded = 0;
        return true;
    }

    const auto& clip = m_clips[target_clip_idx];
    double fps = (clip.fps_den > 0 && clip.fps_num > 0) ? ((double)clip.fps_num / clip.fps_den) : (30000.0 / 1001.0);
    double target_time_sec = target_local_frame / fps;
    LONGLONG target_hns = (LONGLONG)(target_time_sec * 10000000.0);

    PROPVARIANT var;
    PropVariantInit(&var);
    var.vt = VT_I8;
    var.hVal.QuadPart = target_hns;
    HRESULT hr = m_pSourceReader->SetCurrentPosition(GUID_NULL, var);
    PropVariantClear(&var);

    if (m_config.enable_debug_layer) {
        printf("[SEEK] target_global=%u target_clip=%u target_local=%u target_hns=%lld hr=0x%08X\n",
               target_global_frame, target_clip_idx, target_local_frame, (long long)target_hns, (unsigned int)hr);
        fflush(stdout);
    }

    LONGLONG frame_hns = (LONGLONG)(10000000.0 / fps);
    uint32_t discarded = 0;
    while (true) {
        DWORD actualStreamIndex = 0;
        DWORD streamFlags = 0;
        LONGLONG timestamp = 0;
        IMFSample* pSample = nullptr;

        HRESULT hrRead = m_pSourceReader->ReadSample(
            MF_SOURCE_READER_FIRST_VIDEO_STREAM,
            0,
            &actualStreamIndex,
            &streamFlags,
            &timestamp,
            &pSample
        );

        if (FAILED(hrRead) || (streamFlags & MF_SOURCE_READERF_ENDOFSTREAM)) {
            if (m_config.enable_debug_layer) {
                printf("[SEEK] End of stream or error hrRead=0x%08X flags=0x%08X\n", (unsigned int)hrRead, (unsigned int)streamFlags);
                fflush(stdout);
            }
            if (pSample) pSample->Release();
            break;
        }

        if (!pSample) continue;

        if (SUCCEEDED(hr) && target_hns > 0) {
            if (timestamp + frame_hns / 2 >= target_hns) {
                if (m_config.enable_debug_layer) {
                    printf("[SEEK] Reached target: pts=%lld target_hns=%lld discarded=%u\n", (long long)timestamp, (long long)target_hns, discarded);
                    fflush(stdout);
                }
                m_pPendingSample = pSample;
                m_clip_frames_decoded = target_local_frame;
                return true;
            }
        } else {
            discarded++;
            if (discarded >= target_local_frame) {
                if (m_config.enable_debug_layer) {
                    printf("[SEEK] Discarded fallback reached: discarded=%u\n", discarded);
                    fflush(stdout);
                }
                m_pPendingSample = pSample;
                m_clip_frames_decoded = target_local_frame;
                return true;
            }
        }
        discarded++;
        pSample->Release();
    }

    m_clip_frames_decoded = target_local_frame;
    return true;
}

void D3D11NvencPipeline::CloseDecoder() {
    for (auto& pair : m_view_cache) {
        if (pair.second) pair.second->Release();
    }
    m_view_cache.clear();

    SafeRelease(m_pPendingSample);
    SafeRelease(m_pSourceReader);
    SafeRelease(m_pReaderAttributes);
    SafeRelease(m_pDevMgr);
    m_decoder_eof = false;
    m_video_opened = false;
    m_clips.clear();
    m_current_clip_idx = 0;
    m_clip_frames_decoded = 0;
}

ID3D11VideoProcessorInputView* D3D11NvencPipeline::AcquireDecoderFrame(int64_t& out_pts, uint32_t& out_flags) {
    if (m_decoder_eof) return nullptr;

    while (true) {
        IMFSample* pSample = nullptr;
        if (m_pPendingSample) {
            pSample = m_pPendingSample;
            m_pPendingSample = nullptr;
            LONGLONG sample_time = 0;
            pSample->GetSampleTime(&sample_time);
            out_pts = sample_time;
            out_flags = 0;
        } else {
            if (!m_pSourceReader) {
                if (!SwitchToNextClip()) {
                    m_decoder_eof = true;
                    return nullptr;
                }
            }

            DWORD actualStreamIndex = 0;
            DWORD streamFlags = 0;
            LONGLONG timestamp = 0;

            HRESULT hr = m_pSourceReader->ReadSample(
                MF_SOURCE_READER_FIRST_VIDEO_STREAM,
                0,
                &actualStreamIndex,
                &streamFlags,
                &timestamp,
                &pSample
            );

            out_pts = timestamp;
            out_flags = streamFlags;

            if (FAILED(hr) || (streamFlags & MF_SOURCE_READERF_ENDOFSTREAM)) {
                if (pSample) pSample->Release();
                if (SwitchToNextClip()) {
                    continue;
                }
                m_decoder_eof = true;
                return nullptr;
            }

            if (!pSample) continue;
        }

        IMFMediaBuffer* pBuffer = nullptr;
        HRESULT hr = pSample->GetBufferByIndex(0, &pBuffer);
        if (FAILED(hr) || !pBuffer) {
            pSample->Release();
            continue;
        }

        IMFDXGIBuffer* pDXGIBuffer = nullptr;
        hr = pBuffer->QueryInterface(GUID_IID_IMFDXGIBuffer, (void**)&pDXGIBuffer);
        if (FAILED(hr) || !pDXGIBuffer) {
            pBuffer->Release();
            pSample->Release();
            continue;
        }

        ID3D11Texture2D* pVideoTexture = nullptr;
        UINT subresource = 0;
        pDXGIBuffer->GetResource(IID_ID3D11Texture2D, (void**)&pVideoTexture);
        pDXGIBuffer->GetSubresourceIndex(&subresource);

        std::pair<ID3D11Texture2D*, UINT> key(pVideoTexture, subresource);
        ID3D11VideoProcessorInputView* pInputView = nullptr;

        auto it = m_view_cache.find(key);
        bool hit = (it != m_view_cache.end());
        if (!hit) {
            D3D11_VIDEO_PROCESSOR_INPUT_VIEW_DESC inDesc{};
            inDesc.FourCC = 0;
            inDesc.ViewDimension = D3D11_VPIV_DIMENSION_TEXTURE2D;
            inDesc.Texture2D.MipSlice = 0;
            inDesc.Texture2D.ArraySlice = subresource;

            HRESULT hr_v = m_pVideoDevice->CreateVideoProcessorInputView(pVideoTexture, m_pVPEnum, &inDesc, &pInputView);
            if (SUCCEEDED(hr_v)) {
                m_view_cache[key] = pInputView;
                if (m_config.enable_debug_layer) {
                    printf("[VIEW CACHE CREATE] tex=%p sub=%u pInView=%p\n", (void*)pVideoTexture, subresource, (void*)pInputView);
                    fflush(stdout);
                }
            }
        } else {
            pInputView = it->second;
        }

        // Release intermediate COM objects; D3D11 retains internal resource reference in InputView
        if (pVideoTexture) pVideoTexture->Release();
        pDXGIBuffer->Release();
        pBuffer->Release();
        pSample->Release();

        m_clip_frames_decoded++;
        return pInputView;
    }
}

bool D3D11NvencPipeline::SetTelemetry(const TelemFrameState* states, uint32_t count) {
    if (!states || count == 0) return false;
    m_telemetry_table.assign(states, states + count);
    return true;
}

bool D3D11NvencPipeline::SetIndicators(const TelemIndicatorDesc* indicators, uint32_t count) {
    if (m_is_active) return false;
    for (auto& ind : m_indicators) {
        ind->DiscardDeviceResources();
    }
    m_indicators.clear();
    if (!indicators || count == 0) return true;

    for (uint32_t i = 0; i < count; ++i) {
        const auto& desc = indicators[i];
        std::unique_ptr<IndicatorBase> pInd;

        switch (desc.type) {
            case TELEM_IND_TEXT:
                pInd = std::make_unique<TextIndicator>(desc, &m_font_cache, &m_icon_cache);
                break;
            case TELEM_IND_TIME_DISPLAY:
                pInd = std::make_unique<TimeDisplayIndicator>(desc, &m_font_cache, &m_icon_cache);
                break;
            case TELEM_IND_BAR_RULER_H:
            case TELEM_IND_BAR_RULER_V:
                pInd = std::make_unique<BarIndicator>(desc, &m_font_cache);
                break;
            case TELEM_IND_BAR_SEGMENTS:
                pInd = std::make_unique<SegmentBarIndicator>(desc, &m_font_cache);
                break;
            case TELEM_IND_GAUGE:
                pInd = std::make_unique<GaugeIndicator>(desc, &m_font_cache);
                break;
            case TELEM_IND_CHART: {
                auto chartInd = std::make_unique<ChartIndicator>(desc, &m_font_cache);
                auto it = m_chart_samples.find(desc.key);
                if (it != m_chart_samples.end() && !it->second.empty()) {
                    chartInd->SetSamples(it->second.data(), (uint32_t)it->second.size());
                }
                pInd = std::move(chartInd);
                break;
            }
            case TELEM_IND_MAP: {
                auto mapInd = std::make_unique<MapIndicator>(desc);
                if (!m_map_route.empty()) {
                    std::vector<double> lats(m_map_route.size()), lons(m_map_route.size());
                    for (size_t r = 0; r < m_map_route.size(); ++r) {
                        lats[r] = m_map_route[r].first;
                        lons[r] = m_map_route[r].second;
                    }
                    mapInd->SetRoute(lats.data(), lons.data(), (uint32_t)m_map_route.size());
                }
                for (const auto& kv : m_preloaded_tiles) {
                    int32_t z = std::get<0>(kv.first);
                    int32_t x = std::get<1>(kv.first);
                    int32_t y = std::get<2>(kv.first);
                    mapInd->PreloadTile(z, x, y, kv.second.data(), (uint32_t)kv.second.size());
                }
                pInd = std::move(mapInd);
                break;
            }
            default:
                break;
        }

        if (pInd) {
            if (m_pD2DContext && m_pDWriteFactory) {
                pInd->CreateDeviceResources(m_pD2DContext, m_pDWriteFactory);
            }
            m_indicators.push_back(std::move(pInd));
        }
    }

    std::sort(m_indicators.begin(), m_indicators.end(), [](const auto& a, const auto& b) {
        return a->GetZOrder() < b->GetZOrder();
    });

    return true;
}

bool D3D11NvencPipeline::SetChartSamples(const char* indicator_key, const float* samples, uint32_t sample_count) {
    if (!indicator_key || !samples || sample_count == 0) return false;
    m_chart_samples[indicator_key] = std::vector<float>(samples, samples + sample_count);

    for (auto& ind : m_indicators) {
        if (ind->GetKey() == indicator_key && ind->GetType() == TELEM_IND_CHART) {
            static_cast<ChartIndicator*>(ind.get())->SetSamples(samples, sample_count);
        }
    }
    return true;
}

bool D3D11NvencPipeline::SetMapRoute(const double* lats, const double* lons, uint32_t count) {
    if (!lats || !lons || count == 0) return false;
    m_map_route.clear();
    m_map_route.reserve(count);
    for (uint32_t i = 0; i < count; ++i) {
        m_map_route.push_back({ lats[i], lons[i] });
    }
    for (auto& ind : m_indicators) {
        if (ind->GetType() == TELEM_IND_MAP) {
            static_cast<MapIndicator*>(ind.get())->SetRoute(lats, lons, count);
        }
    }
    return true;
}

bool D3D11NvencPipeline::PreloadMapTile(int32_t z, int32_t x, int32_t y, const void* data, uint32_t size_bytes) {
    if (!data || size_bytes == 0) return false;
    auto key = std::make_tuple(z, x, y);
    const uint8_t* bytePtr = static_cast<const uint8_t*>(data);
    m_preloaded_tiles[key] = std::vector<uint8_t>(bytePtr, bytePtr + size_bytes);
    for (auto& ind : m_indicators) {
        if (ind->GetType() == TELEM_IND_MAP) {
            static_cast<MapIndicator*>(ind.get())->PreloadTile(z, x, y, data, size_bytes);
        }
    }
    return true;
}

void D3D11NvencPipeline::GetMapCacheStats(TelemMapCacheStats& out_stats) {
    out_stats = TelemMapCacheStats{};
    for (auto& ind : m_indicators) {
        if (ind->GetType() == TELEM_IND_MAP) {
            static_cast<MapIndicator*>(ind.get())->GetCacheStats(out_stats);
            return;
        }
    }
}

bool D3D11NvencPipeline::SaveTextureToPng(ID3D11Texture2D* pTex, const wchar_t* output_png_path) {
    if (!pTex || !m_pDevice || !m_pContext) return false;

    D3D11_TEXTURE2D_DESC desc{};
    pTex->GetDesc(&desc);
    desc.Usage = D3D11_USAGE_STAGING;
    desc.BindFlags = 0;
    desc.CPUAccessFlags = D3D11_CPU_ACCESS_READ;
    desc.MiscFlags = 0;

    ID3D11Texture2D* pStaging = nullptr;
    HRESULT hr = m_pDevice->CreateTexture2D(&desc, NULL, &pStaging);
    if (FAILED(hr) || !pStaging) return false;

    m_pContext->Flush(); // Ensure all pending GPU work is committed before readback
    m_pContext->CopyResource(pStaging, pTex);

    D3D11_MAPPED_SUBRESOURCE mapped{};
    hr = m_pContext->Map(pStaging, 0, D3D11_MAP_READ, 0, &mapped);
    if (FAILED(hr)) {
        pStaging->Release();
        return false;
    }

    IWICImagingFactory* pWic = nullptr;
    hr = CoCreateInstance(CLSID_WICImagingFactory, NULL, CLSCTX_INPROC_SERVER, IID_PPV_ARGS(&pWic));
    if (SUCCEEDED(hr) && pWic) {
        IWICStream* pStream = nullptr;
        hr = pWic->CreateStream(&pStream);
        if (SUCCEEDED(hr)) {
            hr = pStream->InitializeFromFilename(output_png_path, GENERIC_WRITE);
            if (SUCCEEDED(hr)) {
                IWICBitmapEncoder* pEncoder = nullptr;
                hr = pWic->CreateEncoder(GUID_ContainerFormatPng, NULL, &pEncoder);
                if (SUCCEEDED(hr)) {
                    hr = pEncoder->Initialize(pStream, WICBitmapEncoderNoCache);
                    if (SUCCEEDED(hr)) {
                        IWICBitmapFrameEncode* pFrame = nullptr;
                        hr = pEncoder->CreateNewFrame(&pFrame, NULL);
                        if (SUCCEEDED(hr)) {
                            hr = pFrame->Initialize(NULL);
                            pFrame->SetSize(desc.Width, desc.Height);
                            WICPixelFormatGUID format = GUID_WICPixelFormat32bppPBGRA;
                            pFrame->SetPixelFormat(&format);
                            pFrame->WritePixels(desc.Height, mapped.RowPitch, desc.Height * mapped.RowPitch, (BYTE*)mapped.pData);
                            pFrame->Commit();
                            pFrame->Release();
                        }
                        pEncoder->Commit();
                    }
                    pEncoder->Release();
                }
            }
            pStream->Release();
        }
        pWic->Release();
    }

    m_pContext->Unmap(pStaging, 0);
    pStaging->Release();

    return SUCCEEDED(hr);
}

bool D3D11NvencPipeline::RenderHudFrameToFile(uint32_t frame_index, const std::wstring& output_png_path) {
    if (!m_pD2DContext || m_ring_hud_textures.empty() || !m_pDevice || !m_pContext) return false;

    TelemFrameState state{};
    if (frame_index < m_telemetry_table.size()) {
        state = m_telemetry_table[frame_index];
    }

    RenderHud(state, 0);
    return SaveTextureToPng(m_ring_hud_textures[0], output_png_path.c_str());
}

bool D3D11NvencPipeline::RenderHudFrameToBuffer(uint32_t frame_index, void* out_bgra_buffer, uint32_t buffer_size, uint32_t* out_width, uint32_t* out_height, uint32_t* out_pitch) {
    if (!m_pD2DContext || m_ring_hud_textures.empty() || !m_pDevice || !m_pContext || !out_bgra_buffer) return false;

    TelemFrameState state{};
    if (frame_index < m_telemetry_table.size()) {
        state = m_telemetry_table[frame_index];
    } else if (!m_telemetry_table.empty()) {
        state = m_telemetry_table.back();
    }

    int slot = (int)(frame_index % m_config.ring_size);
    RenderHud(state, slot);

    ID3D11Texture2D* pSrcTex = m_ring_hud_textures[slot];
    D3D11_TEXTURE2D_DESC desc{};
    pSrcTex->GetDesc(&desc);

    uint32_t row_bytes = desc.Width * 4;
    uint32_t needed_bytes = desc.Height * row_bytes;
    if (buffer_size < needed_bytes) return false;

    if (!m_pStagingHudTex) {
        D3D11_TEXTURE2D_DESC sDesc = desc;
        sDesc.Usage = D3D11_USAGE_STAGING;
        sDesc.BindFlags = 0;
        sDesc.CPUAccessFlags = D3D11_CPU_ACCESS_READ;
        sDesc.MiscFlags = 0;
        HRESULT hr = m_pDevice->CreateTexture2D(&sDesc, NULL, &m_pStagingHudTex);
        if (FAILED(hr) || !m_pStagingHudTex) return false;
    }

    m_pContext->CopyResource(m_pStagingHudTex, pSrcTex);

    D3D11_MAPPED_SUBRESOURCE mapped{};
    HRESULT hr = m_pContext->Map(m_pStagingHudTex, 0, D3D11_MAP_READ, 0, &mapped);
    if (FAILED(hr)) return false;

    uint8_t* pDst = static_cast<uint8_t*>(out_bgra_buffer);
    const uint8_t* pSrc = static_cast<const uint8_t*>(mapped.pData);
    for (uint32_t y = 0; y < desc.Height; ++y) {
        memcpy(pDst + y * row_bytes, pSrc + y * mapped.RowPitch, row_bytes);
    }

    m_pContext->Unmap(m_pStagingHudTex, 0);

    if (out_width) *out_width = desc.Width;
    if (out_height) *out_height = desc.Height;
    if (out_pitch) *out_pitch = row_bytes;
    return true;
}

HRESULT D3D11NvencPipeline::RenderHud(const TelemFrameState& state, int slot) {
    if (!m_pD2DContext || slot < 0 || slot >= (int)m_ring_d2d_bitmap_targets.size()) return E_FAIL;

    m_pD2DContext->SetTarget(m_ring_d2d_bitmap_targets[slot]);
    m_pD2DContext->SetTransform(D2D1::Matrix3x2F::Identity());
    m_pD2DContext->BeginDraw();
    m_pD2DContext->Clear(D2D1::ColorF(0.0f, 0.0f, 0.0f, 0.0f));

    if ((state.frame_index >= 146 && state.frame_index <= 155) || (state.frame_index >= 1255 && state.frame_index <= 1265)) {
        printf("[FRAME %u RENDERHUD START] slot=%d inds=%zu\n", state.frame_index, slot, m_indicators.size());
        fflush(stdout);
    }

    if (!m_indicators.empty()) {
        for (size_t k = 0; k < m_indicators.size(); ++k) {
            auto& ind = m_indicators[k];
            ind->Render(m_pD2DContext, state);
        }
    } else {
        // Fallback prototype cards
        D2D1_ROUNDED_RECT rcTime = D2D1::RoundedRect(D2D1::RectF(100.0f, 80.0f, 560.0f, 220.0f), 20.0f, 20.0f);
        m_pD2DContext->FillRoundedRectangle(&rcTime, m_brush_card_bg);
        m_pD2DContext->DrawRoundedRectangle(&rcTime, m_brush_card_border, 2.5f);

        D2D1_ROUNDED_RECT rcSpeed = D2D1::RoundedRect(D2D1::RectF(100.0f, 1680.0f, 680.0f, 2040.0f), 20.0f, 20.0f);
        m_pD2DContext->FillRoundedRectangle(&rcSpeed, m_brush_card_bg);
        m_pD2DContext->DrawRoundedRectangle(&rcSpeed, m_brush_card_border, 2.5f);
        D2D1_ELLIPSE elCyan = D2D1::Ellipse(D2D1::Point2F(170.0f, 1750.0f), 22.0f, 22.0f);
        m_pD2DContext->FillEllipse(&elCyan, m_brush_cyan);

        D2D1_ROUNDED_RECT rcHr = D2D1::RoundedRect(D2D1::RectF(740.0f, 1680.0f, 1300.0f, 2040.0f), 20.0f, 20.0f);
        m_pD2DContext->FillRoundedRectangle(&rcHr, m_brush_card_bg);
        m_pD2DContext->DrawRoundedRectangle(&rcHr, m_brush_card_border, 2.5f);
        D2D1_ELLIPSE elCoral = D2D1::Ellipse(D2D1::Point2F(810.0f, 1750.0f), 22.0f, 22.0f);
        m_pD2DContext->FillEllipse(&elCoral, m_brush_coral);

        wchar_t wBuf[64];
        D2D1_RECT_F rLabelTime = D2D1::RectF(130.0f, 95.0f, 500.0f, 130.0f);
        m_pD2DContext->DrawText(L"RECORDING TIME", 14, m_fmt_label, &rLabelTime, m_brush_text_muted);

        MultiByteToWideChar(CP_UTF8, 0, state.time_display_time[0] ? state.time_display_time : state.speed_str, -1, wBuf, 64);
        D2D1_RECT_F rValTime = D2D1::RectF(130.0f, 120.0f, 540.0f, 200.0f);
        m_pD2DContext->DrawText(wBuf, (UINT32)wcslen(wBuf), m_fmt_time, &rValTime, m_brush_white);

        D2D1_RECT_F rLabelSpeed = D2D1::RectF(220.0f, 1735.0f, 500.0f, 1770.0f);
        m_pD2DContext->DrawText(L"SPEED", 5, m_fmt_label, &rLabelSpeed, m_brush_text_muted);

        MultiByteToWideChar(CP_UTF8, 0, state.speed_str, -1, wBuf, 64);
        D2D1_RECT_F rValSpeed = D2D1::RectF(130.0f, 1780.0f, 510.0f, 1960.0f);
        m_pD2DContext->DrawText(wBuf, (UINT32)wcslen(wBuf), m_fmt_speed_val, &rValSpeed, m_brush_white);

        D2D1_RECT_F rUnitSpeed = D2D1::RectF(520.0f, 1850.0f, 660.0f, 1930.0f);
        m_pD2DContext->DrawText(L"km/h", 4, m_fmt_speed_unit, &rUnitSpeed, m_brush_cyan);

        D2D1_RECT_F rLabelHr = D2D1::RectF(860.0f, 1735.0f, 1200.0f, 1770.0f);
        m_pD2DContext->DrawText(L"HEART RATE", 10, m_fmt_label, &rLabelHr, m_brush_text_muted);

        MultiByteToWideChar(CP_UTF8, 0, state.hr_str, -1, wBuf, 64);
        D2D1_RECT_F rValHr = D2D1::RectF(770.0f, 1780.0f, 1150.0f, 1960.0f);
        m_pD2DContext->DrawText(wBuf, (UINT32)wcslen(wBuf), m_fmt_hr_val, &rValHr, m_brush_white);

        D2D1_RECT_F rUnitHr = D2D1::RectF(1160.0f, 1850.0f, 1280.0f, 1930.0f);
        m_pD2DContext->DrawText(L"bpm", 3, m_fmt_hr_unit, &rUnitHr, m_brush_coral);
    }

    D2D1_TAG tag_flush1 = 0, tag_flush2 = 0;
    HRESULT hr_flush = m_pD2DContext->Flush(&tag_flush1, &tag_flush2);
    if (FAILED(hr_flush)) {
        printf("[D2D ERROR] Flush before EndDraw failed at slot=%d: 0x%08X tag1=%llu tag2=%llu\n", slot, (unsigned int)hr_flush, (unsigned long long)tag_flush1, (unsigned long long)tag_flush2);
        fflush(stdout);
    }

    D2D1_TAG tag1 = 0, tag2 = 0;
    HRESULT hr_d2d = m_pD2DContext->EndDraw(&tag1, &tag2);
    if (FAILED(hr_d2d)) {
        printf("[D2D ERROR] EndDraw failed at slot=%d: 0x%08X tag1=%llu tag2=%llu\n", slot, (unsigned int)hr_d2d, (unsigned long long)tag1, (unsigned long long)tag2);
        fflush(stdout);
    }

    m_last_end_draw_hr = hr_d2d;
    m_last_d2d_flush_hr = hr_flush;
    m_last_d2d_tag1 = tag1;
    m_last_d2d_tag2 = tag2;

    // Critical: force D2D's GPU commands into the immediate context command queue NOW.
    // D2D's EndDraw() queues D3D11 commands but does not call ID3D11DeviceContext::Flush().
    // Without this flush, the fence query End() (placed by the caller AFTER we return) would
    // be recorded BEFORE D2D's actual GPU work arrives in the command stream, so the fence
    // would complete before the HUD texture is rendered — causing VideoProcessorBlt to sample
    // an empty/stale HUD texture.
    m_pContext->Flush();

    if ((state.frame_index >= 146 && state.frame_index <= 155) || (state.frame_index >= 1255 && state.frame_index <= 1265)) {
        printf("[FRAME %u ENDDRAW] hr_d2d=0x%08X tag1=%llu tag2=%llu hr_flush=0x%08X\n",
               state.frame_index, (unsigned int)hr_d2d, (unsigned long long)tag1, (unsigned long long)tag2, (unsigned int)hr_flush);
        fflush(stdout);
    }

    m_pD2DContext->SetTarget(nullptr);
    ID3D11RenderTargetView* nullRTV[1] = { nullptr };
    m_pContext->OMSetRenderTargets(1, nullRTV, nullptr);
    return hr_d2d;
}

void D3D11NvencPipeline::LogSlot0State(const char* event_name) {
    if (!m_pSlot0File) return;
    void* hud_tex = m_ring_hud_textures.empty() ? nullptr : (void*)m_ring_hud_textures[0];
    void* d2d_tgt = m_ring_d2d_bitmap_targets.empty() ? nullptr : (void*)m_ring_d2d_bitmap_targets[0];
    void* vp_in_hud = m_ring_vp_in_view_huds.empty() ? nullptr : (void*)m_ring_vp_in_view_huds[0];
    void* nv12_tex = m_ring_nv12_textures.empty() ? nullptr : (void*)m_ring_nv12_textures[0];
    void* nvenc_reg = m_ring_registered_handles.empty() ? nullptr : m_ring_registered_handles[0];

    bool is_busy = false;
    if (!m_slot_in_flight.empty() && m_slot_in_flight[0] != -1) {
        is_busy = true;
    }
    const char* busy_free = is_busy ? "BUSY" : "FREE";
    uint32_t pending_count = (uint32_t)m_in_flight_bitstream_buffers.size();

    fprintf(m_pSlot0File, "{\"event\":\"%s\",\"slot_index\":0,\"hud_texture_identity\":\"0x%p\",\"d2d_target_identity\":\"0x%p\",\"vp_hud_input_view_identity\":\"0x%p\",\"video_p010_texture_identity\":\"0x%p\",\"nvenc_registered_handle\":\"0x%p\",\"nvenc_mapped_input_handle\":\"0x%p\",\"slot_busy_free_state\":\"%s\",\"pending_encoder_ownership\":%u,\"map_unmap_state\":\"%s\",\"last_input_frame_using_slot\":%d,\"last_encoded_frame_associated_with_slot\":%d}\n",
            event_name, hud_tex, d2d_tgt, vp_in_hud, nv12_tex, nvenc_reg, m_slot0_mapped_handle, busy_free, pending_count, m_slot0_map_state, m_slot0_last_input, m_slot0_last_encoded);
    fflush(m_pSlot0File);
    printf("[SLOT 0 LOG] %s: busy=%s map=%s last_in=%d last_enc=%d pending=%u\n",
           event_name, busy_free, m_slot0_map_state, m_slot0_last_input, m_slot0_last_encoded, pending_count);
    fflush(stdout);
}

bool D3D11NvencPipeline::Composite(ID3D11VideoProcessorInputView* pVideoInView, int ring_slot, bool include_hud) {
    if (!m_pVideoContext || !m_pVP || !pVideoInView) return false;
    if (ring_slot < 0 || ring_slot >= (int)m_ring_vp_out_views.size()) return false;
    ID3D11VideoProcessorOutputView* pOutView = m_ring_vp_out_views[ring_slot];

    bool result = false;
    if (!include_hud) {
        D3D11_VIDEO_PROCESSOR_STREAM stream{};
        stream.Enable = TRUE;
        stream.pInputSurface = pVideoInView;
        HRESULT hr = m_pVideoContext->VideoProcessorBlt(m_pVP, pOutView, 0, 1, &stream);
        result = SUCCEEDED(hr);
    } else {
        D3D11_VIDEO_PROCESSOR_STREAM streams[2]{};
        streams[0].Enable = TRUE;
        streams[0].pInputSurface = pVideoInView;

        streams[1].Enable = TRUE;
        streams[1].pInputSurface = m_ring_vp_in_view_huds[ring_slot];

        m_pVideoContext->VideoProcessorSetStreamFrameFormat(m_pVP, 0, D3D11_VIDEO_FRAME_FORMAT_PROGRESSIVE);
        m_pVideoContext->VideoProcessorSetStreamFrameFormat(m_pVP, 1, D3D11_VIDEO_FRAME_FORMAT_PROGRESSIVE);
        m_pVideoContext->VideoProcessorSetStreamAutoProcessingMode(m_pVP, 0, FALSE);
        m_pVideoContext->VideoProcessorSetStreamAutoProcessingMode(m_pVP, 1, FALSE);
        m_pVideoContext->VideoProcessorSetStreamAlpha(m_pVP, 0, FALSE, 1.0f);
        m_pVideoContext->VideoProcessorSetStreamAlpha(m_pVP, 1, TRUE, 1.0f);
        HRESULT hr = m_pVideoContext->VideoProcessorBlt(m_pVP, pOutView, 0, 2, streams);
        m_last_vp_blt_hr = hr;
        if (FAILED(hr)) {
            printf("[VP ERROR] VideoProcessorBlt failed: 0x%08X\n", (unsigned int)hr);
        }
        result = SUCCEEDED(hr);
    }
    return result;
}

bool D3D11NvencPipeline::ResolveEncoderProfile(GUID& outCodecGuid, GUID& outProfileGuid, GUID& outPresetGuid, NV_ENC_TUNING_INFO& outTuningInfo, NV_ENC_CONFIG& outConfig, uint32_t& outRequiredRingSize) {
    const TelemEncoderConfig& enc = m_config.encoder_config;
    uint32_t codec = enc.codec;
    uint32_t qmode = enc.quality_mode;

    uint32_t bitDepth = (enc.bit_depth != 0) ? enc.bit_depth : m_config.bit_depth;
    if (bitDepth == 0) bitDepth = 10;

    uint32_t targetBps = (enc.bitrate_bps != 0) ? enc.bitrate_bps : 20000000;
    uint32_t maxBps = (enc.max_bitrate_bps != 0) ? enc.max_bitrate_bps : (uint32_t)(targetBps * 1.25);
    uint32_t vbvBits = (enc.vbv_size_bits != 0) ? enc.vbv_size_bits : targetBps;

    if (codec == TELEM_CODEC_AV1) {
        outCodecGuid = NV_ENC_CODEC_AV1_GUID;
        outProfileGuid = NV_ENC_AV1_PROFILE_MAIN_GUID;
        if (qmode == TELEM_QUALITY_FAST) {
            printf("[RESOLVE ERROR] AV1_FAST profile is unsupported. Only AV1_QUALITY and AV1_MAX are supported.\n");
            return false;
        } else if (qmode == TELEM_QUALITY_QUALITY) {
            outPresetGuid = NV_ENC_PRESET_P5_GUID;
            outTuningInfo = NV_ENC_TUNING_INFO_HIGH_QUALITY;
            outRequiredRingSize = 32;
        } else if (qmode == TELEM_QUALITY_MAX) {
            outPresetGuid = NV_ENC_PRESET_P7_GUID;
            outTuningInfo = NV_ENC_TUNING_INFO_ULTRA_HIGH_QUALITY;
            outRequiredRingSize = 40;
        } else {
            printf("[RESOLVE ERROR] Unknown AV1 quality mode: %u\n", qmode);
            return false;
        }
    } else { // HEVC
        outCodecGuid = NV_ENC_CODEC_HEVC_GUID;
        outProfileGuid = (bitDepth == 10) ? NV_ENC_HEVC_PROFILE_MAIN10_GUID : NV_ENC_HEVC_PROFILE_MAIN_GUID;
        if (qmode == TELEM_QUALITY_FAST) {
            outPresetGuid = NV_ENC_PRESET_P1_GUID;
            outTuningInfo = NV_ENC_TUNING_INFO_HIGH_QUALITY;
            outRequiredRingSize = 8;
        } else if (qmode == TELEM_QUALITY_QUALITY) {
            outPresetGuid = NV_ENC_PRESET_P5_GUID;
            outTuningInfo = NV_ENC_TUNING_INFO_HIGH_QUALITY;
            outRequiredRingSize = 32;
        } else if (qmode == TELEM_QUALITY_MAX) {
            outPresetGuid = NV_ENC_PRESET_P7_GUID;
            outTuningInfo = NV_ENC_TUNING_INFO_ULTRA_HIGH_QUALITY;
            outRequiredRingSize = 40;
        } else {
            printf("[RESOLVE ERROR] Unknown HEVC quality mode: %u\n", qmode);
            return false;
        }
    }

    m_preset_cfg.version = NV_ENC_PRESET_CONFIG_VER;
    m_preset_cfg.presetCfg.version = NV_ENC_CONFIG_VER;
    NVENCSTATUS stat = m_nvenc.nvEncGetEncodePresetConfigEx(m_hEncoder, outCodecGuid, outPresetGuid, outTuningInfo, &m_preset_cfg);
    if (stat != NV_ENC_SUCCESS) {
        printf("[RESOLVE ERROR] nvEncGetEncodePresetConfigEx failed: %d\n", stat);
        return false;
    }

    outConfig = m_preset_cfg.presetCfg;
    outConfig.profileGUID = outProfileGuid;

    outConfig.rcParams.rateControlMode = NV_ENC_PARAMS_RC_VBR;
    outConfig.rcParams.averageBitRate = targetBps;
    outConfig.rcParams.maxBitRate = maxBps;
    outConfig.rcParams.vbvBufferSize = vbvBits;
    outConfig.gopLength = (enc.gop_length != 0) ? enc.gop_length : 250;

    if (codec == TELEM_CODEC_AV1) {
        NV_ENC_CONFIG_AV1& a1 = outConfig.encodeCodecConfig.av1Config;
        a1.inputBitDepth = (bitDepth == 10) ? NV_ENC_BIT_DEPTH_10 : NV_ENC_BIT_DEPTH_8;
        a1.outputBitDepth = (bitDepth == 10) ? NV_ENC_BIT_DEPTH_10 : NV_ENC_BIT_DEPTH_8;
        a1.repeatSeqHdr = 1;
        a1.chromaFormatIDC = 1; // 4:2:0
        a1.colorRange = 1; // full swing / pc
        a1.colorPrimaries = NV_ENC_VUI_COLOR_PRIMARIES_BT2020;
        a1.transferCharacteristics = NV_ENC_VUI_TRANSFER_CHARACTERISTIC_ARIB_STD_B67;
        a1.matrixCoefficients = NV_ENC_VUI_MATRIX_COEFFS_BT2020_NCL;

        if (qmode == TELEM_QUALITY_QUALITY) {
            outConfig.frameIntervalP = (enc.b_frames != 0) ? (enc.b_frames + 1) : 6; // 5 B-frames
            a1.useBFramesAsRef = NV_ENC_BFRAME_REF_MODE_MIDDLE;
            outConfig.rcParams.multiPass = NV_ENC_TWO_PASS_FULL_RESOLUTION;
            outConfig.rcParams.enableLookahead = 1;
            outConfig.rcParams.lookaheadDepth = (enc.lookahead_depth != 0) ? enc.lookahead_depth : 16;
            outConfig.rcParams.enableAQ = 1;
            outConfig.rcParams.aqStrength = 8;
            outConfig.rcParams.enableTemporalAQ = 1;
        } else if (qmode == TELEM_QUALITY_MAX) {
            outConfig.frameIntervalP = (enc.b_frames != 0) ? (enc.b_frames + 1) : 8; // 7 B-frames
            a1.useBFramesAsRef = NV_ENC_BFRAME_REF_MODE_MIDDLE;
            a1.tfLevel = NV_ENC_TEMPORAL_FILTER_LEVEL_4;
            outConfig.rcParams.multiPass = NV_ENC_TWO_PASS_FULL_RESOLUTION;
            outConfig.rcParams.enableLookahead = 1;
            outConfig.rcParams.lookaheadDepth = (enc.lookahead_depth != 0) ? enc.lookahead_depth : 25;
            outConfig.rcParams.enableAQ = 1;
            outConfig.rcParams.aqStrength = 8;
            outConfig.rcParams.enableTemporalAQ = 1;
        }
    } else { // HEVC
        NV_ENC_CONFIG_HEVC& h = outConfig.encodeCodecConfig.hevcConfig;
        h.inputBitDepth = (bitDepth == 10) ? NV_ENC_BIT_DEPTH_10 : NV_ENC_BIT_DEPTH_8;
        h.outputBitDepth = (bitDepth == 10) ? NV_ENC_BIT_DEPTH_10 : NV_ENC_BIT_DEPTH_8;
        h.repeatSPSPPS = 1;

        if (bitDepth == 10) {
            NV_ENC_CONFIG_HEVC_VUI_PARAMETERS& vui = h.hevcVUIParameters;
            vui.videoSignalTypePresentFlag = 1;
            vui.videoFormat = NV_ENC_VUI_VIDEO_FORMAT_COMPONENT;
            vui.videoFullRangeFlag = 1; // pc full range
            vui.colourDescriptionPresentFlag = 1;
            vui.colourPrimaries = NV_ENC_VUI_COLOR_PRIMARIES_BT2020;
            vui.transferCharacteristics = NV_ENC_VUI_TRANSFER_CHARACTERISTIC_ARIB_STD_B67;
            vui.colourMatrix = NV_ENC_VUI_MATRIX_COEFFS_BT2020_NCL;
        }

        if (qmode == TELEM_QUALITY_FAST) {
            outConfig.frameIntervalP = 1;
            h.useBFramesAsRef = NV_ENC_BFRAME_REF_MODE_DISABLED;
            outConfig.rcParams.multiPass = NV_ENC_MULTI_PASS_DISABLED;
            outConfig.rcParams.enableLookahead = 0;
            outConfig.rcParams.enableAQ = 0;
            outConfig.rcParams.enableTemporalAQ = 0;
        } else if (qmode == TELEM_QUALITY_QUALITY) {
            outConfig.frameIntervalP = (enc.b_frames != 0) ? (enc.b_frames + 1) : 4; // 3 B-frames
            h.useBFramesAsRef = NV_ENC_BFRAME_REF_MODE_MIDDLE;
            outConfig.rcParams.multiPass = NV_ENC_TWO_PASS_FULL_RESOLUTION;
            outConfig.rcParams.enableLookahead = 1;
            outConfig.rcParams.lookaheadDepth = (enc.lookahead_depth != 0) ? enc.lookahead_depth : 16;
            outConfig.rcParams.enableAQ = 1;
            outConfig.rcParams.aqStrength = 8;
            outConfig.rcParams.enableTemporalAQ = 1;
        } else if (qmode == TELEM_QUALITY_MAX) {
            outConfig.frameIntervalP = (enc.b_frames != 0) ? (enc.b_frames + 1) : 6; // 5 B-frames
            h.useBFramesAsRef = NV_ENC_BFRAME_REF_MODE_MIDDLE;
            h.tfLevel = NV_ENC_TEMPORAL_FILTER_LEVEL_4;
            outConfig.rcParams.multiPass = NV_ENC_TWO_PASS_FULL_RESOLUTION;
            outConfig.rcParams.enableLookahead = 1;
            outConfig.rcParams.lookaheadDepth = (enc.lookahead_depth != 0) ? enc.lookahead_depth : 25;
            outConfig.rcParams.enableAQ = 1;
            outConfig.rcParams.aqStrength = 8;
            outConfig.rcParams.enableTemporalAQ = 1;
        }
    }

    return true;
}

bool D3D11NvencPipeline::StartNvencSession() {
    EndNvencSession();

    if (!m_hNvencDll) {
        m_hNvencDll = LoadLibraryW(L"nvEncodeAPI64.dll");
        if (!m_hNvencDll) return false;

        typedef NVENCSTATUS(NVENCAPI *PFN_NvEncodeAPICreateInstance)(NV_ENCODE_API_FUNCTION_LIST*);
        PFN_NvEncodeAPICreateInstance pfnCreate = reinterpret_cast<PFN_NvEncodeAPICreateInstance>(reinterpret_cast<void*>(GetProcAddress(m_hNvencDll, "NvEncodeAPICreateInstance")));
        if (!pfnCreate) return false;

        m_nvenc.version = NV_ENCODE_API_FUNCTION_LIST_VER;
        if (pfnCreate(&m_nvenc) != NV_ENC_SUCCESS) return false;
    }

    NV_ENC_OPEN_ENCODE_SESSION_EX_PARAMS openParams{};
    openParams.version = NV_ENC_OPEN_ENCODE_SESSION_EX_PARAMS_VER;
    openParams.deviceType = NV_ENC_DEVICE_TYPE_DIRECTX;
    openParams.device = m_pDevice;
    openParams.apiVersion = NVENCAPI_VERSION;

    NVENCSTATUS status = m_nvenc.nvEncOpenEncodeSessionEx(&openParams, &m_hEncoder);
    if (status != NV_ENC_SUCCESS) return false;

    while (!m_free_bitstream_buffers.empty()) m_free_bitstream_buffers.pop();
    while (!m_in_flight_bitstream_buffers.empty()) m_in_flight_bitstream_buffers.pop();
    while (!m_in_flight_bitstream_ownership.empty()) m_in_flight_bitstream_ownership.pop();
    m_consumer_index = 0;
    m_first_bs_seen = false;
    m_slot_in_flight.assign(m_config.ring_size, -1);
    m_ring_release_diags.clear();

    GUID codecGuid{};
    GUID profileGuid{};
    GUID presetGuid{};
    NV_ENC_TUNING_INFO tuningInfo{};
    NV_ENC_CONFIG encConfig{};
    uint32_t reqRingSize = 8;

    if (!ResolveEncoderProfile(codecGuid, profileGuid, presetGuid, tuningInfo, encConfig, reqRingSize)) {
        return false;
    }

    NV_ENC_INITIALIZE_PARAMS initParams{};
    initParams.version = NV_ENC_INITIALIZE_PARAMS_VER;
    initParams.encodeGUID = codecGuid;
    initParams.presetGUID = presetGuid;
    initParams.encodeWidth = m_config.width;
    initParams.encodeHeight = m_config.height;
    initParams.darWidth = m_config.width;
    initParams.darHeight = m_config.height;
    initParams.frameRateNum = m_config.fps_num;
    initParams.frameRateDen = m_config.fps_den;
    initParams.enableEncodeAsync = 0;
    initParams.enablePTD = 1;
    initParams.tuningInfo = tuningInfo;
    initParams.encodeConfig = &encConfig;

    status = m_nvenc.nvEncInitializeEncoder(m_hEncoder, &initParams);
    if (status != NV_ENC_SUCCESS) {
        printf("[NVENC INIT ERROR] nvEncInitializeEncoder failed: %d (0x%08X)\n", status, status);
        return false;
    }

    // Register persistent ring textures
    m_ring_registered_handles.clear();
    NV_ENC_BUFFER_FORMAT bufFmt = (m_config.bit_depth == 10) ? NV_ENC_BUFFER_FORMAT_YUV420_10BIT : NV_ENC_BUFFER_FORMAT_NV12;

    for (UINT i = 0; i < m_config.ring_size; ++i) {
        NV_ENC_REGISTER_RESOURCE reg{};
        reg.version = NV_ENC_REGISTER_RESOURCE_VER;
        reg.resourceType = NV_ENC_INPUT_RESOURCE_TYPE_DIRECTX;
        reg.width = m_config.width;
        reg.height = m_config.height;
        reg.pitch = 0; // For DirectX resources pitch must be 0
        reg.resourceToRegister = m_ring_nv12_textures[i];
        reg.bufferFormat = bufFmt;
        reg.bufferUsage = NV_ENC_INPUT_IMAGE;

        status = m_nvenc.nvEncRegisterResource(m_hEncoder, &reg);
        if (status != NV_ENC_SUCCESS) return false;
        m_ring_registered_handles.push_back(reg.registeredResource);
    }

    // Allocate decoupled bitstream buffer pool (64 buffers to support lookahead + B-frames)
    m_all_bitstream_buffers.clear();
    while (!m_free_bitstream_buffers.empty()) m_free_bitstream_buffers.pop();
    while (!m_in_flight_bitstream_buffers.empty()) m_in_flight_bitstream_buffers.pop();
    while (!m_in_flight_bitstream_ownership.empty()) m_in_flight_bitstream_ownership.pop();

    const size_t NUM_BS_BUFFERS = 64;
    for (size_t i = 0; i < NUM_BS_BUFFERS; ++i) {
        NV_ENC_CREATE_BITSTREAM_BUFFER bs{};
        bs.version = NV_ENC_CREATE_BITSTREAM_BUFFER_VER;
        status = m_nvenc.nvEncCreateBitstreamBuffer(m_hEncoder, &bs);
        if (status != NV_ENC_SUCCESS) return false;
        m_all_bitstream_buffers.push_back(bs.bitstreamBuffer);
        m_free_bitstream_buffers.push(bs.bitstreamBuffer);
    }

    if (m_enable_compression_analysis && !m_compression_csv_path.empty()) {
        if (m_compression_csv_file) {
            fclose(m_compression_csv_file);
            m_compression_csv_file = nullptr;
        }
        m_compression_csv_file = _wfopen(m_compression_csv_path.c_str(), L"w");
        if (m_compression_csv_file) {
            setvbuf(m_compression_csv_file, nullptr, _IOFBF, 64 * 1024);
            fprintf(m_compression_csv_file, "time_sec,frame,avg_qp,frame_type,encoded_bytes\n");
        }
    }

    return true;
}

void D3D11NvencPipeline::EndNvencSession() {
    if (!m_hEncoder) return;

    while (!m_free_bitstream_buffers.empty()) m_free_bitstream_buffers.pop();
    while (!m_in_flight_bitstream_buffers.empty()) m_in_flight_bitstream_buffers.pop();
    while (!m_in_flight_bitstream_ownership.empty()) m_in_flight_bitstream_ownership.pop();

    for (HANDLE h : m_ring_completion_events) {
        if (h) CloseHandle(h);
    }
    m_ring_completion_events.clear();

    for (void* bs : m_all_bitstream_buffers) {
        if (bs) m_nvenc.nvEncDestroyBitstreamBuffer(m_hEncoder, bs);
    }
    m_all_bitstream_buffers.clear();

    for (void* reg : m_ring_registered_handles) {
        if (reg) m_nvenc.nvEncUnregisterResource(m_hEncoder, reg);
    }
    m_ring_registered_handles.clear();

    if (m_compression_csv_file) {
        fflush(m_compression_csv_file);
        fclose(m_compression_csv_file);
        m_compression_csv_file = nullptr;
    }

    m_nvenc.nvEncDestroyEncoder(m_hEncoder);
    m_hEncoder = nullptr;
}

bool D3D11NvencPipeline::EncodeFrame(int ring_slot, uint32_t session_frame_idx, uint32_t global_frame_idx, HANDLE hOutputFile, double& out_submit_time, double& out_bs_time, TelemEncodeDiagInfo* pDiag) {
    (void)session_frame_idx;
    double t_sub0 = GetQpcTimeSec();

    NV_ENC_MAP_INPUT_RESOURCE mapRes{};
    mapRes.version = NV_ENC_MAP_INPUT_RESOURCE_VER;
    mapRes.registeredResource = m_ring_registered_handles[ring_slot];

    NVENCSTATUS status = m_nvenc.nvEncMapInputResource(m_hEncoder, &mapRes);
    if (status != NV_ENC_SUCCESS) return false;

    if (ring_slot == 0) {
        m_slot0_mapped_handle = mapRes.mappedResource;
        m_slot0_map_state = "MAPPED";
    }
    if (pDiag) {
        pDiag->mapped_input_handle = mapRes.mappedResource;
    }

    if (m_free_bitstream_buffers.empty()) {
        printf("[NVENC ERROR] Free bitstream buffer pool exhausted!\n");
        m_nvenc.nvEncUnmapInputResource(m_hEncoder, mapRes.mappedResource);
        if (ring_slot == 0) {
            m_slot0_mapped_handle = nullptr;
            m_slot0_map_state = "UNMAPPED";
        }
        return false;
    }
    void* curBs = m_free_bitstream_buffers.front();
    m_free_bitstream_buffers.pop();

    NV_ENC_PIC_PARAMS picParams{};
    picParams.version = NV_ENC_PIC_PARAMS_VER;
    picParams.inputWidth = m_config.width;
    picParams.inputHeight = m_config.height;
    picParams.inputPitch = m_config.width;
    picParams.inputBuffer = mapRes.mappedResource;
    picParams.outputBitstream = curBs;
    picParams.bufferFmt = mapRes.mappedBufferFmt;
    picParams.pictureStruct = NV_ENC_PIC_STRUCT_FRAME;
    picParams.frameIdx = global_frame_idx;
    picParams.encodePicFlags = 0;

    status = m_nvenc.nvEncEncodePicture(m_hEncoder, &picParams);
    m_nvenc.nvEncUnmapInputResource(m_hEncoder, mapRes.mappedResource);
    if (ring_slot == 0) {
        m_slot0_mapped_handle = nullptr;
        m_slot0_map_state = "UNMAPPED";
    }

    if (pDiag) {
        pDiag->encode_status = (uint32_t)status;
        pDiag->pending_count = (uint32_t)m_in_flight_bitstream_buffers.size();
    }

    if (status != NV_ENC_SUCCESS && status != NV_ENC_ERR_NEED_MORE_INPUT) {
        printf("[NVENC ERROR] nvEncEncodePicture failed: %d\n", status);
        m_free_bitstream_buffers.push(curBs);
        return false;
    }

    // Keep the exact resource ownership chain.  NVENC's lock metadata is an
    // output record; it is not the authoritative surface-slot owner.
    if (ring_slot >= 0 && ring_slot < (int)m_slot_in_flight.size()) {
        if (pDiag) {
            pDiag->slot_reused = (m_slot_in_flight[ring_slot] != -1);
        }
        m_slot_in_flight[ring_slot] = global_frame_idx;
    }
    m_in_flight_bitstream_buffers.push(curBs);
    m_in_flight_bitstream_ownership.push({curBs, global_frame_idx, ring_slot});
    double t_sub1 = GetQpcTimeSec();

    double t_bs0 = GetQpcTimeSec();
    if (status == NV_ENC_SUCCESS) {
        // 1. Drain completed bitstream buffers non-blocking
        while (!m_in_flight_bitstream_buffers.empty()) {
            if (!ProcessBitstreamQueue(hOutputFile, false, pDiag)) {
                break;
            }
        }

        // 2. Bounded pipeline depth: prevent CPU from running ahead of GPU
        // In FAST (no lookahead, no B-frames), bound depth to 4 frames.
        // In QUALITY (lookahead 25 + B-frames), allow depth 32.
        uint32_t max_in_flight = (m_config.encoder_config.enable_lookahead || m_config.encoder_config.b_frames > 0) ? 32 : 4;
        while (m_in_flight_bitstream_buffers.size() > max_in_flight) {
            if (!ProcessBitstreamQueue(hOutputFile, true, pDiag)) {
                break;
            }
        }
    }
    double t_bs1 = GetQpcTimeSec();

    out_submit_time = (t_sub1 - t_sub0);
    out_bs_time = (t_bs1 - t_bs0);

    return true;
}

bool D3D11NvencPipeline::ProcessBitstreamQueue(HANDLE hOutputFile, bool blocking, TelemEncodeDiagInfo* pDiag) {
    if (!m_hEncoder || m_in_flight_bitstream_buffers.empty() || m_in_flight_bitstream_ownership.empty()) return false;
    void* readyBs = m_in_flight_bitstream_buffers.front();
    const auto& ownership = m_in_flight_bitstream_ownership.front();
    if (ownership.bitstream != readyBs) {
        printf("[NVENC OWNERSHIP ERROR] bitstream queue desynchronized\n");
        fflush(stdout);
        return false;
    }
    NV_ENC_LOCK_BITSTREAM lockBs{};
    lockBs.version = NV_ENC_LOCK_BITSTREAM_VER;
    lockBs.doNotWait = blocking ? 0 : 1;
    lockBs.outputBitstream = readyBs;

    NVENCSTATUS lockStat = m_nvenc.nvEncLockBitstream(m_hEncoder, &lockBs);
    if (lockStat == NV_ENC_SUCCESS) {
        m_consumer_index++;
        const uint32_t submitted_input_frame = ownership.input_frame;
        const int rel_slot = ownership.ring_slot;
        const bool lock_frame_matches_owner = (lockBs.frameIdx == submitted_input_frame);
        int previous_owner = -1;
        if (rel_slot >= 0 && rel_slot < (int)m_slot_in_flight.size()) {
            previous_owner = m_slot_in_flight[rel_slot];
        }
        m_ring_release_diags.push_back({
            submitted_input_frame,
            (uint32_t)lockBs.frameIdx,
            rel_slot,
            rel_slot,
            previous_owner,
            lock_frame_matches_owner,
        });
        if (pDiag) {
            pDiag->bitstream_ready = true;
            pDiag->bitstream_frame_index = lockBs.frameIdx;
            pDiag->bitstream_picture_type = lockBs.pictureType;
            int bs_idx = -1;
            for (size_t b = 0; b < m_all_bitstream_buffers.size(); ++b) {
                if (m_all_bitstream_buffers[b] == readyBs) { bs_idx = (int)b; break; }
            }
            pDiag->bitstream_slot = bs_idx;
            pDiag->released_slot = rel_slot;
        }
        if (rel_slot >= 0 && rel_slot < (int)m_slot_in_flight.size() &&
            m_slot_in_flight[rel_slot] == (int)submitted_input_frame) {
            m_slot_in_flight[rel_slot] = -1;
        }
        if (rel_slot == 0) {
            m_slot0_last_encoded = (int)submitted_input_frame;
            if (submitted_input_frame == 0) {
                LogSlot0State("after_release_frame_0");
            }
        }
        if (!m_first_bs_seen) {
            m_first_bs_seen = true;
            if (pDiag) pDiag->is_first_bitstream = true;
        }
        if (m_config.enable_debug_layer) {
            printf("[LOCKED BS] frameIdx=%u picType=%u bytes=%u pts=%lld\n",
                   lockBs.frameIdx, lockBs.pictureType, lockBs.bitstreamSizeInBytes, (long long)lockBs.outputTimeStamp);
            fflush(stdout);
        }
        if (m_enable_compression_analysis) {
            RecordCompressionSample(lockBs.frameIdx, lockBs.outputTimeStamp, lockBs.pictureType, lockBs.frameAvgQP, lockBs.bitstreamSizeInBytes);
        }
        m_in_flight_bitstream_buffers.pop();
        m_in_flight_bitstream_ownership.pop();
        if (hOutputFile != INVALID_HANDLE_VALUE && lockBs.bitstreamSizeInBytes > 0) {
            DWORD written = 0;
            WriteFile(hOutputFile, lockBs.bitstreamBufferPtr, lockBs.bitstreamSizeInBytes, &written, NULL);
        }
        m_stats.total_bitstream_bytes += lockBs.bitstreamSizeInBytes;
        m_nvenc.nvEncUnlockBitstream(m_hEncoder, readyBs);
        m_free_bitstream_buffers.push(readyBs);
        return true;
    }
    return false;
}

bool D3D11NvencPipeline::DrainNvenc(HANDLE hOutputFile) {
    if (!m_hEncoder) return true;

    NV_ENC_PIC_PARAMS drainParams{};
    drainParams.version = NV_ENC_PIC_PARAMS_VER;
    drainParams.encodePicFlags = NV_ENC_PIC_FLAG_EOS;

    NVENCSTATUS status = m_nvenc.nvEncEncodePicture(m_hEncoder, &drainParams);
    (void)status;

    while (!m_in_flight_bitstream_buffers.empty()) {
        if (!ProcessBitstreamQueue(hOutputFile, true, nullptr)) {
            printf("[DRAIN ERROR] ProcessBitstreamQueue failed, remaining=%zu\n", m_in_flight_bitstream_buffers.size());
            fflush(stdout);
            return false;
        }
    }
    return true;
}

bool D3D11NvencPipeline::StartExport(const std::wstring& output_hevc_path, uint32_t start_frame, uint32_t frame_count, bool include_hud) {
    if (m_is_active) return false;
    if (!m_configured || !m_video_opened) return false;

    m_is_active = true;
    m_cancel_requested = false;
    m_is_finished = false;

    m_worker_thread = std::thread(&D3D11NvencPipeline::FrameLoopThread, this, output_hevc_path, start_frame, frame_count, include_hud);
    return true;
}

void D3D11NvencPipeline::Cancel() {
    m_cancel_requested = true;
}

bool D3D11NvencPipeline::WaitCompletion(uint32_t timeout_ms) {
    (void)timeout_ms;
    if (m_worker_thread.joinable()) {
        if (std::this_thread::get_id() != m_worker_thread.get_id()) {
            m_worker_thread.join();
            return true;
        }
    }
    return false;
}

void D3D11NvencPipeline::FrameLoopThread(std::wstring output_path, uint32_t start_frame, uint32_t frame_count, bool include_hud) {
    HANDLE hOutputFile = INVALID_HANDLE_VALUE;
    if (!output_path.empty()) {
        if (output_path.rfind(L"HANDLE:", 0) == 0) {
            HANDLE h = (HANDLE)(uintptr_t)_wcstoui64(output_path.c_str() + 7, NULL, 10);
            hOutputFile = h;
        } else if (output_path.rfind(L"\\\\.\\pipe\\", 0) == 0) {
            hOutputFile = CreateFileW(output_path.c_str(), GENERIC_WRITE, 0, NULL, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, NULL);
        } else {
            hOutputFile = CreateFileW(output_path.c_str(), GENERIC_WRITE, FILE_SHARE_READ, NULL, CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, NULL);
        }
    }

    if (!StartNvencSession()) {
        std::lock_guard<std::mutex> lock(m_progress_mutex);
        m_progress.error_code = -1;
        strcpy_s(m_progress.error_message, "StartNvencSession failed");
        m_is_active = false;
        m_is_finished = true;
        if (hOutputFile != INVALID_HANDLE_VALUE) {
            CloseHandle(hOutputFile);
        }
        return;
    }

    // Initialize progress & stats
    {
        std::lock_guard<std::mutex> lock(m_progress_mutex);
        m_progress.completed_frames = 0;
        m_progress.total_frames = frame_count;
        m_progress.elapsed_sec = 0.0;
        m_progress.current_fps = 0.0;
        m_progress.is_active = 1;
        m_progress.is_cancelled = 0;
        m_progress.is_finished = 0;
        m_progress.error_code = 0;
        m_progress.error_message[0] = '\0';

        memset(&m_stats, 0, sizeof(m_stats));
        m_stats.ram_start_bytes = QueryRam();
        QueryVram(m_stats.vram_budget_bytes, m_stats.vram_usage_bytes);
    }

    std::vector<double> latencies;
    latencies.reserve(frame_count);

    double t_decode_total = 0.0;
    double t_telem_total  = 0.0;
    double t_hud_total    = 0.0;
    double t_vp_total     = 0.0;
    double t_nvenc_total  = 0.0;
    double t_bs_total     = 0.0;

    double wall_t0 = GetQpcTimeSec();
    double last_progress_t = wall_t0;
    uint32_t completed = 0;

    if (start_frame > 0) {
        if (!SeekToGlobalFrame(start_frame)) {
            std::lock_guard<std::mutex> lock(m_progress_mutex);
            m_progress.error_code = -2;
            strcpy_s(m_progress.error_message, "SeekToGlobalFrame failed");
            m_is_active = false;
            m_is_finished = true;
            if (hOutputFile != INVALID_HANDLE_VALUE) {
                CloseHandle(hOutputFile);
            }
            return;
        }
    }

    FILE* pTimelineFile = fopen("scratch/stage8l4a_logs/hud_draw_timeline.jsonl", "w");
    CreateDirectoryA("scratch", NULL);
    CreateDirectoryA("scratch/stage8l4c_logs", NULL);
    FILE* pRingTransitionFile = fopen("scratch/stage8l4c_logs/ring_transition.jsonl", "w");
    CreateDirectoryA("scratch/stage8l4c1_logs", NULL);
    FILE* pRingAuditFile = fopen("scratch/stage8l4c1_logs/ring_230_300.jsonl", "w");
    m_pSlot0File = fopen("scratch/stage8l4c_logs/slot0_lifecycle.jsonl", "w");
    m_slot0_last_input = -1;
    m_slot0_last_encoded = -1;
    m_slot0_mapped_handle = nullptr;
    m_slot0_map_state = "UNMAPPED";

    m_lifecycle_logs.clear();
    m_lifecycle_logs.reserve(frame_count + 100);

    bool frame_loop_error = false;
    for (uint32_t i = 0; i < frame_count; ++i) {
        if (m_cancel_requested) {
            std::lock_guard<std::mutex> lock(m_progress_mutex);
            m_progress.is_cancelled = 1;
            break;
        }

        if (i == 0) LogSlot0State("before_frame_0");
        if (i == 64) LogSlot0State("before_frame_64");

        double frame_t0 = GetQpcTimeSec();
        uint32_t frame_idx = start_frame + i;
        int slot = (int)(frame_idx % m_config.ring_size);
        int slot_in_flight_before = (slot >= 0 && slot < (int)m_slot_in_flight.size()) ? m_slot_in_flight[slot] : -1;
        m_ring_release_diags.clear();

        HRESULT hud_q_status_before = S_OK;
        HRESULT vp_q_status_before = S_OK;
        if (slot < (int)m_ring_hud_queries.size() && m_ring_hud_queries[slot]) {
            BOOL done = FALSE;
            HRESULT hrQ = m_pContext->GetData(m_ring_hud_queries[slot], &done, sizeof(BOOL), D3D11_ASYNC_GETDATA_DONOTFLUSH);
            if (hrQ == S_OK) {
                hud_q_status_before = done ? S_OK : S_FALSE;
            } else {
                hud_q_status_before = hrQ;
            }
        }
        if (slot < (int)m_ring_vp_queries.size() && m_ring_vp_queries[slot]) {
            BOOL done = FALSE;
            HRESULT hrQ = m_pContext->GetData(m_ring_vp_queries[slot], &done, sizeof(BOOL), D3D11_ASYNC_GETDATA_DONOTFLUSH);
            if (hrQ == S_OK) {
                vp_q_status_before = done ? S_OK : S_FALSE;
            } else {
                vp_q_status_before = hrQ;
            }
        }

        // Ring Wrap-Around / Slot Reuse Guard:
        // If NVENC is still encoding the frame previously assigned to this slot,
        // we MUST wait for NVENC to finish and release this slot before overwriting it!
        if (slot < (int)m_slot_in_flight.size() && m_slot_in_flight[slot] != -1) {
            printf("[GUARD TRIGGER] input_frame=%u slot=%d in_flight_frame=%d in_flight_bs_count=%zu\n",
                   i, slot, m_slot_in_flight[slot], m_in_flight_bitstream_buffers.size());
            fflush(stdout);
        }
        while (slot < (int)m_slot_in_flight.size() && m_slot_in_flight[slot] != -1) {
            if (!ProcessBitstreamQueue(hOutputFile, true, nullptr)) {
                std::lock_guard<std::mutex> lock(m_progress_mutex);
                m_progress.error_code = -3;
                strcpy_s(m_progress.error_message, "NVENC ownership completion failed before slot reuse");
                frame_loop_error = true;
                break;
            }
        }
        if (frame_loop_error) break;
        int slot_in_flight_after_guard = (slot >= 0 && slot < (int)m_slot_in_flight.size()) ? m_slot_in_flight[slot] : -1;

        // 1. Decoder acquire
        double tdec0 = GetQpcTimeSec();
        int64_t pts = 0;
        uint32_t flags = 0;
        ID3D11VideoProcessorInputView* pVideoInView = AcquireDecoderFrame(pts, flags);
        double tdec1 = GetQpcTimeSec();
        t_decode_total += (tdec1 - tdec0);

        if (!pVideoInView) {
            std::lock_guard<std::mutex> lock(m_progress_mutex);
            m_progress.error_code = -3;
            strcpy_s(m_progress.error_message, "AcquireDecoderFrame returned null");
            break;
        }
        if (i == 0 && IsStage8L4C2MfLogEnabled()) {
            FILE* file = fopen("scratch/stage8l4c2_logs/mf_media_types.txt", "a");
            if (file) {
                fprintf(file, "first_P010_decode=PASS input_frame=%u pts=%lld\n",
                        frame_idx, (long long)pts);
                fclose(file);
            }
        }

        // 2. Telemetry Lookup
        double ttelem0 = GetQpcTimeSec();
        TelemFrameState cur_state{};
        if (!m_telemetry_table.empty()) {
            if (frame_idx < m_telemetry_table.size()) {
                cur_state = m_telemetry_table[frame_idx];
            } else {
                cur_state = m_telemetry_table.back();
            }
        }
        double ttelem1 = GetQpcTimeSec();
        t_telem_total += (ttelem1 - ttelem0);

        // 3. Render HUD (Direct2D)
        double thud0 = GetQpcTimeSec();
        HRESULT hr_d2d = S_OK;
        uint32_t hud_nonzero_alpha = 0;
        bool hud_query_done = false;
        if (include_hud) {
            hr_d2d = RenderHud(cur_state, slot);

            // GPU Fence: ensure Direct2D rendering to m_ring_hud_textures[slot] is 100% complete
            // before VideoProcessorBlt samples it on the video processing engine
            if (slot < (int)m_ring_hud_queries.size() && m_ring_hud_queries[slot]) {
                m_pContext->End(m_ring_hud_queries[slot]);
                m_pContext->Flush();
                BOOL done = FALSE;
                while (m_pContext->GetData(m_ring_hud_queries[slot], &done, sizeof(BOOL), 0) == S_FALSE) {
                    YieldProcessor();
                }
                hud_query_done = (done == TRUE);
            }
        }
        double thud1 = GetQpcTimeSec();
        t_hud_total += (thud1 - thud0);

        // 4. VideoProcessor Composite
        double tvp0 = GetQpcTimeSec();

        bool comp_ok = Composite(pVideoInView, slot, include_hud);
        if (i >= 115 && i <= 122) {
            printf("[FRAME %u DIAG] slot=%d hr_d2d=0x%08X comp_ok=%d\n", i, slot, (unsigned int)hr_d2d, comp_ok ? 1 : 0);
            fflush(stdout);
        }
        double tvp1 = GetQpcTimeSec();
        t_vp_total += (tvp1 - tvp0);

        // GPU Fence: ensure VideoProcessorBlt writes to m_ring_nv12_textures[slot] are complete before NVENC reads it
        if (slot < (int)m_ring_vp_queries.size() && m_ring_vp_queries[slot]) {
            m_pContext->End(m_ring_vp_queries[slot]);
            m_pContext->Flush();
            BOOL done = FALSE;
            while (m_pContext->GetData(m_ring_vp_queries[slot], &done, sizeof(BOOL), 0) == S_FALSE) {
                Sleep(0);
            }
        }

        if (i == 0) LogSlot0State("after_compose_frame_0");
        if (i == 64) LogSlot0State("after_compose_frame_64");

        if (pTimelineFile) {
            uint32_t active_inds = (uint32_t)m_indicators.size();
            uint32_t text_calls = 0, shape_calls = 0, chart_calls = 0;
            bool map_drawn = false;
            for (const auto& ind : m_indicators) {
                auto t = ind->GetType();
                if (t == TELEM_IND_TEXT || t == TELEM_IND_TIME_DISPLAY) text_calls++;
                else if (t == TELEM_IND_GAUGE || t == TELEM_IND_BAR_RULER_H || t == TELEM_IND_BAR_RULER_V || t == TELEM_IND_BAR_SEGMENTS) shape_calls++;
                else if (t == TELEM_IND_CHART) chart_calls++;
                else if (t == TELEM_IND_MAP) map_drawn = true;
            }
            double global_time = (m_config.fps_num > 0) ? (frame_idx * (double)m_config.fps_den / (double)m_config.fps_num) : 0.0;
            fprintf(pTimelineFile, "{\"frame_index\":%u,\"pts\":%lld,\"clip_index\":%u,\"global_time\":%.4f,\"number_of_active_indicators\":%u,\"number_of_text_draw_calls\":%u,\"number_of_shape_draw_calls\":%u,\"number_of_chart_draw_calls\":%u,\"map_drawn\":%s,\"d2d_hr\":\"0x%08X\",\"comp_ok\":%s,\"slot\":%d}\n",
                    frame_idx, (long long)pts, m_current_clip_idx, global_time, active_inds, text_calls, shape_calls, chart_calls,
                    map_drawn ? "true" : "false", (unsigned int)hr_d2d, comp_ok ? "true" : "false", slot);
            if (i % 30 == 0 || FAILED(hr_d2d) || !comp_ok) fflush(pTimelineFile);
        }

        if (i == 116 || FAILED(hr_d2d) || !comp_ok) {
            printf("[FRAME %u HUD STATUS] slot=%d hr_d2d=0x%08X comp_ok=%d\n", i, slot, (unsigned int)hr_d2d, comp_ok ? 1 : 0);
            fflush(stdout);
        }

        // Live Render Preview Tap (Stage 8L.4): Non-blocking downscale and readback
        if (m_preview_tap_enabled && m_pPreviewVP && m_pVideoContext && slot < (int)m_ring_preview_in_views.size()) {
            double now = GetQpcTimeSec();
            // 1. Check if prior in-flight preview readback finished
            if (m_preview_capture_in_flight) {
                BOOL queryData = FALSE;
                HRESULT hrQ = m_pContext->GetData(m_preview_query[m_preview_in_flight_slot], &queryData, sizeof(queryData), D3D11_ASYNC_GETDATA_DONOTFLUSH);
                if (hrQ == S_OK && queryData) {
                    D3D11_MAPPED_SUBRESOURCE mapSub{};
                    HRESULT hrMap = m_pContext->Map(m_preview_staging_tex[m_preview_in_flight_slot], 0, D3D11_MAP_READ, D3D11_MAP_FLAG_DO_NOT_WAIT, &mapSub);
                    if (SUCCEEDED(hrMap) && mapSub.pData) {
                        {
                            std::lock_guard<std::mutex> lock(m_preview_mutex);
                            size_t rowBytes = (size_t)m_preview_tap_width * 4;
                            if (m_preview_ram_buffer.size() != rowBytes * m_preview_tap_height) {
                                m_preview_ram_buffer.resize(rowBytes * m_preview_tap_height);
                            }
                            FastCopyFromGpuStaging(m_preview_ram_buffer.data(), (const uint8_t*)mapSub.pData, rowBytes, mapSub.RowPitch, m_preview_tap_height);
                            m_preview_has_new_frame = true;
                            m_preview_ready_frame_idx = m_preview_in_flight_frame;
                            m_preview_ready_pts = m_preview_in_flight_pts;
                        }
                        m_pContext->Unmap(m_preview_staging_tex[m_preview_in_flight_slot], 0);
                        m_preview_capture_in_flight = false;
                    }
                }
            }

            // 2. Submit new preview downscale capture if throttle interval elapsed
            if (!m_preview_capture_in_flight && (now - m_preview_last_submit_time >= m_preview_interval_sec)) {
                uint32_t tap_slot = m_preview_next_slot;
                D3D11_VIDEO_PROCESSOR_STREAM stream{};
                stream.Enable = TRUE;
                stream.pInputSurface = m_ring_preview_in_views[slot];

                HRESULT hrBlt = m_pVideoContext->VideoProcessorBlt(m_pPreviewVP, m_preview_output_view[tap_slot], 0, 1, &stream);
                if (SUCCEEDED(hrBlt)) {
                    m_pContext->CopyResource(m_preview_staging_tex[tap_slot], m_preview_output_tex[tap_slot]);
                    m_pContext->End(m_preview_query[tap_slot]);

                    m_preview_capture_in_flight = true;
                    m_preview_in_flight_slot = tap_slot;
                    m_preview_in_flight_frame = frame_idx;
                    m_preview_in_flight_pts = (double)pts / 10000000.0;
                    m_preview_last_submit_time = now;
                    m_preview_next_slot = (tap_slot + 1) % 2;
                }
            }
        }

        // 5 & 6. NVENC Encode & Bitstream
        double submit_sec = 0.0, bs_sec = 0.0;
        TelemEncodeDiagInfo diag{};
        bool enc_ok = EncodeFrame(slot, i, frame_idx, hOutputFile, submit_sec, bs_sec, &diag);
        t_nvenc_total += submit_sec;
        t_bs_total += bs_sec;

        if (i == 0) {
            m_slot0_last_input = 0;
            LogSlot0State("after_submit_frame_0");
        }
        if (i == 64) {
            m_slot0_last_input = 64;
            LogSlot0State("after_submit_frame_64");
        }

        if (pRingTransitionFile) {
            if (diag.is_first_bitstream) {
                fprintf(pRingTransitionFile, "{\"event\":\"FIRST_BITSTREAM_READY\",\"input_frame\":%u,\"encoded_frame\":%u,\"bitstream_slot\":%d,\"surface_slot\":%d,\"pending_count\":%u}\n",
                        i, diag.bitstream_frame_index, diag.bitstream_slot, diag.released_slot, diag.pending_count);
                fflush(pRingTransitionFile);
                printf("[FIRST_BITSTREAM_READY] input_frame=%u encoded_frame=%u bs_slot=%d surface_slot=%d pending=%u\n",
                       i, diag.bitstream_frame_index, diag.bitstream_slot, diag.released_slot, diag.pending_count);
                fflush(stdout);
            }
            if (i >= 15 && i <= 45) {
                fprintf(pRingTransitionFile, "{\"input_frame\":%u,\"pts\":%lld,\"producer_index\":%u,\"consumer_index\":%u,\"selected_ring_slot\":%d,\"hud_texture_slot\":%d,\"hud_texture_pointer_or_identity\":\"0x%p\",\"video_texture_slot\":\"0x%p\",\"p010_output_slot\":%d,\"vp_hud_input_view_slot\":%d,\"vp_video_input_view_slot\":\"0x%p\",\"vp_output_slot\":%d,\"nvenc_input_slot\":%d,\"encode_picture_status\":%u,\"pending_encode_count\":%u,\"bitstream_ready\":%s,\"bitstream_slot\":%d,\"bitstream_frame_index\":%u,\"bitstream_picture_type\":%u,\"slot_released\":%s,\"released_slot\":%d,\"slot_reused\":%s,\"nonzero_alpha\":%u}\n",
                        i, (long long)pts, i, m_consumer_index, slot, slot, (void*)m_ring_hud_textures[slot], (void*)pVideoInView, slot, slot, (void*)pVideoInView, slot, slot,
                        diag.encode_status, diag.pending_count, diag.bitstream_ready ? "true" : "false", diag.bitstream_slot, diag.bitstream_frame_index, diag.bitstream_picture_type,
                        (diag.released_slot >= 0) ? "true" : "false", diag.released_slot, diag.slot_reused ? "true" : "false", hud_nonzero_alpha);
                fflush(pRingTransitionFile);
            }
        }

        if (pRingAuditFile && frame_idx >= 230 && frame_idx <= 300) {
            int slot_in_flight_after = (slot >= 0 && slot < (int)m_slot_in_flight.size()) ? m_slot_in_flight[slot] : -1;
            int lock_frame_idx = m_ring_release_diags.empty() ? -1 : (int)m_ring_release_diags.back().lock_frame_idx;
            int released_slot = m_ring_release_diags.empty() ? -1 : m_ring_release_diags.back().released_slot;
            int released_previous_owner = m_ring_release_diags.empty() ? -1 : m_ring_release_diags.back().released_slot_previous_owner;
            int ownership_input_frame = m_ring_release_diags.empty() ? -1 : (int)m_ring_release_diags.back().submitted_input_frame;
            int ownership_slot = m_ring_release_diags.empty() ? -1 : m_ring_release_diags.back().owned_ring_slot;
            bool lock_matches_owner = m_ring_release_diags.empty() ? false : m_ring_release_diags.back().lock_frame_matches_owner;
            std::string release_details;
            for (const auto& release : m_ring_release_diags) {
                char detail[256];
                snprintf(detail, sizeof(detail),
                         "%s{\"submitted_input_frame\":%u,\"lockBs.frameIdx\":%u,\"owned_ring_slot\":%d,\"released_slot\":%d,\"released_slot_previous_owner\":%d,\"lock_frame_matches_owner\":%s}",
                         release_details.empty() ? "" : ",",
                         release.submitted_input_frame, release.lock_frame_idx,
                         release.owned_ring_slot, release.released_slot,
                         release.released_slot_previous_owner,
                         release.lock_frame_matches_owner ? "true" : "false");
                release_details += detail;
            }
            fprintf(pRingAuditFile,
                    "{\"input_frame\":%u,\"input_pts\":%lld,\"slot\":%d,\"slot_in_flight_before\":%d,\"slot_owner_input_frame\":%d,\"hud_texture_slot\":%d,\"vp_hud_view_slot\":%d,\"nvenc_input_slot\":%d,\"nvenc_submit_frame\":%u,\"lockBs.frameIdx\":%d,\"released_slot\":%d,\"released_slot_previous_owner\":%d,\"ownership_input_frame\":%d,\"ownership_ring_slot\":%d,\"lock_frame_matches_owner\":%s,\"pending_count\":%zu,\"slot_in_flight_after\":%d,\"slot_in_flight_after_guard\":%d,\"release_events\":%zu,\"release_details\":[%s],\"encode_ok\":%s}\n",
                    frame_idx, (long long)pts, slot, slot_in_flight_before, slot_in_flight_before,
                    slot, slot, slot, frame_idx, lock_frame_idx, released_slot,
                    released_previous_owner, ownership_input_frame, ownership_slot,
                    lock_matches_owner ? "true" : "false", m_in_flight_bitstream_buffers.size(),
                    slot_in_flight_after, slot_in_flight_after_guard, m_ring_release_diags.size(),
                    release_details.c_str(), enc_ok ? "true" : "false");
            fflush(pRingAuditFile);
        }

        if (frame_idx >= 1240 && frame_idx <= 1320) {
            FILE* fRing43 = fopen("scratch/gui_43s_forensics/ring_1240_1320.jsonl", "a");
            if (fRing43) {
                int wrap_count = (int)(frame_idx / m_config.ring_size);
                int released_input_frame = m_ring_release_diags.empty() ? -1 : (int)m_ring_release_diags.back().submitted_input_frame;
                int released_slot = m_ring_release_diags.empty() ? -1 : (int)m_ring_release_diags.back().released_slot;
                void* d2d_target_id = (slot >= 0 && slot < (int)m_ring_d2d_bitmap_targets.size()) ? (void*)m_ring_d2d_bitmap_targets[slot] : nullptr;
                void* hud_tex_id = (slot >= 0 && slot < (int)m_ring_hud_textures.size()) ? (void*)m_ring_hud_textures[slot] : nullptr;
                void* vp_hud_view_id = (slot >= 0 && slot < (int)m_ring_vp_in_view_huds.size()) ? (void*)m_ring_vp_in_view_huds[slot] : nullptr;

                fprintf(fRing43, "{\"frame\":%u,\"slot\":%d,\"wrap_count\":%d,\"slot_owner_input_frame\":%d,\"slot_in_flight\":%d,\"submitted_input_frame\":%u,\"submitted_slot\":%d,\"bitstream_ownership_queue_length\":%zu,\"released_input_frame\":%d,\"released_slot\":%d,\"d2d_target_identity\":\"0x%p\",\"hud_texture_identity\":\"0x%p\",\"vp_hud_input_view_identity\":\"0x%p\",\"begin_draw\":\"S_OK\",\"end_draw_hresult\":\"0x%08X\",\"d3d11_event_query_completion\":%s,\"composite_hresult\":\"%s\"}\n",
                        frame_idx, slot, wrap_count,
                        slot_in_flight_before, slot_in_flight_before,
                        frame_idx, slot,
                        m_in_flight_bitstream_buffers.size(),
                        released_input_frame, released_slot,
                        d2d_target_id, hud_tex_id, vp_hud_view_id,
                        (unsigned int)hr_d2d,
                        hud_query_done ? "true" : "false",
                        comp_ok ? "S_OK" : "FAILED");
                fclose(fRing43);
            }
        }

        // Continuous GPU command drain
        m_pContext->Flush();

        if (m_config.enable_debug_layer && ((i < 5) || (i >= 26 && i <= 31))) {
            printf("[DIAG FRAME %u] comp_ok=%d enc_ok=%d slot=%d pts=%lld\n", i, comp_ok, enc_ok, slot, (long long)pts);
            fflush(stdout);
        }

        FrameLifecycleLog logEntry{};
        logEntry.frame_index = frame_idx;
        LARGE_INTEGER qpc;
        QueryPerformanceCounter(&qpc);
        logEntry.qpc_timestamp = (uint64_t)qpc.QuadPart;
        logEntry.ring_slot = slot;
        logEntry.wrap_count = (int)(frame_idx / m_config.ring_size);
        logEntry.slot_owner_before = slot_in_flight_before;
        logEntry.slot_in_flight = slot_in_flight_after_guard;
        logEntry.submitted_input_frame = frame_idx;
        logEntry.submitted_slot = slot;
        logEntry.ownership_queue_depth = m_in_flight_bitstream_buffers.size();

        logEntry.hud_texture_ptr = (slot >= 0 && slot < (int)m_ring_hud_textures.size()) ? (void*)m_ring_hud_textures[slot] : nullptr;
        logEntry.d2d_target_ptr = (slot >= 0 && slot < (int)m_ring_d2d_bitmap_targets.size()) ? (void*)m_ring_d2d_bitmap_targets[slot] : nullptr;
        logEntry.vp_hud_input_view_ptr = (slot >= 0 && slot < (int)m_ring_vp_in_view_huds.size()) ? (void*)m_ring_vp_in_view_huds[slot] : nullptr;

        logEntry.hud_query_status_before_reuse = (int)hud_q_status_before;
        logEntry.vp_query_status_before_reuse = (int)vp_q_status_before;

        logEntry.begin_draw_status = (m_pD2DContext != nullptr) ? 0 : -1;
        logEntry.end_draw_hresult = (uint32_t)hr_d2d;
        logEntry.d2d_flush_hresult = (uint32_t)m_last_d2d_flush_hr;
        logEntry.d2d_tag1 = m_last_d2d_tag1;
        logEntry.d2d_tag2 = m_last_d2d_tag2;
        logEntry.composite_result = comp_ok;
        logEntry.vp_blt_hresult = (uint32_t)m_last_vp_blt_hr;

        logEntry.encoded_frame = diag.bitstream_ready ? (int)diag.bitstream_frame_index : -1;
        logEntry.released_input_frame = m_ring_release_diags.empty() ? -1 : (int)m_ring_release_diags.back().submitted_input_frame;
        logEntry.released_slot = m_ring_release_diags.empty() ? -1 : (int)m_ring_release_diags.back().released_slot;
        logEntry.slot_owner_after = (slot >= 0 && slot < (int)m_slot_in_flight.size()) ? m_slot_in_flight[slot] : -1;

        logEntry.active_indicators = (uint32_t)m_indicators.size();
        logEntry.device_removed_reason = m_pDevice ? (uint32_t)m_pDevice->GetDeviceRemovedReason() : 0;

        m_lifecycle_logs.push_back(logEntry);

        double frame_t1 = GetQpcTimeSec();
        latencies.push_back((frame_t1 - frame_t0) * 1000.0);
        completed++;

        // Periodic throttled progress update (~10 Hz)
        if (frame_t1 - last_progress_t >= 0.1 || i + 1 == frame_count) {
            double cur_elapsed = frame_t1 - wall_t0;
            std::lock_guard<std::mutex> lock(m_progress_mutex);
            m_progress.completed_frames = completed;
            m_progress.elapsed_sec = cur_elapsed;
            m_progress.current_fps = (cur_elapsed > 0.0) ? (completed / cur_elapsed) : 0.0;
            last_progress_t = frame_t1;

            uint64_t cur_ram = QueryRam();
            if (cur_ram > m_stats.ram_peak_bytes) m_stats.ram_peak_bytes = cur_ram;
        }
    }

    // Drain any in-flight preview capture
    if (m_preview_tap_enabled && m_preview_capture_in_flight && m_pContext) {
        for (int wait_iter = 0; wait_iter < 20; ++wait_iter) {
            BOOL queryData = FALSE;
            HRESULT hrQ = m_pContext->GetData(m_preview_query[m_preview_in_flight_slot], &queryData, sizeof(queryData), D3D11_ASYNC_GETDATA_DONOTFLUSH);
            if (hrQ == S_OK && queryData) {
                D3D11_MAPPED_SUBRESOURCE mapSub{};
                if (SUCCEEDED(m_pContext->Map(m_preview_staging_tex[m_preview_in_flight_slot], 0, D3D11_MAP_READ, 0, &mapSub)) && mapSub.pData) {
                    {
                        std::lock_guard<std::mutex> lock(m_preview_mutex);
                        size_t rowBytes = (size_t)m_preview_tap_width * 4;
                        if (m_preview_ram_buffer.size() != rowBytes * m_preview_tap_height) {
                            m_preview_ram_buffer.resize(rowBytes * m_preview_tap_height);
                        }
                        FastCopyFromGpuStaging(m_preview_ram_buffer.data(), (const uint8_t*)mapSub.pData, rowBytes, mapSub.RowPitch, m_preview_tap_height);
                        m_preview_has_new_frame = true;
                        m_preview_ready_frame_idx = m_preview_in_flight_frame;
                        m_preview_ready_pts = m_preview_in_flight_pts;
                    }
                    m_pContext->Unmap(m_preview_staging_tex[m_preview_in_flight_slot], 0);
                }
                m_preview_capture_in_flight = false;
                break;
            }
            Sleep(1);
        }
    }

    // Drain NVENC
    double t_drain0 = GetQpcTimeSec();
    DrainNvenc(hOutputFile);
    double t_drain1 = GetQpcTimeSec();
    t_bs_total += (t_drain1 - t_drain0);
    if (hOutputFile != INVALID_HANDLE_VALUE) {
        FlushFileBuffers(hOutputFile);
        CloseHandle(hOutputFile);
        hOutputFile = INVALID_HANDLE_VALUE;
    }

    double wall_t1 = GetQpcTimeSec();
    double wall_time_sec = wall_t1 - wall_t0;

    EndNvencSession();
    CloseDecoder();

    // Finalize statistics
    {
        std::lock_guard<std::mutex> lock(m_progress_mutex);
        m_stats.completed_frames = completed;
        m_stats.wall_time_sec = wall_time_sec;
        m_stats.throughput_fps = (wall_time_sec > 0.0) ? (completed / wall_time_sec) : 0.0;
        if (completed > 0) {
            double dur_sec = (double)completed / (m_config.fps_num / (double)m_config.fps_den);
            m_stats.bitrate_mbps = (dur_sec > 0.0) ? ((m_stats.total_bitstream_bytes * 8.0) / dur_sec / 1000000.0) : 0.0;
            m_stats.decode_acquire_ms = (t_decode_total / completed) * 1000.0;
            m_stats.telemetry_lookup_ms = (t_telem_total / completed) * 1000.0;
            m_stats.hud_d2d_ms = (t_hud_total / completed) * 1000.0;
            m_stats.vp_composite_ms = (t_vp_total / completed) * 1000.0;
            m_stats.nvenc_submit_ms = (t_nvenc_total / completed) * 1000.0;
            m_stats.bitstream_handling_ms = (t_bs_total / completed) * 1000.0;
        }

        if (!latencies.empty()) {
            double sum = 0.0;
            double max_v = 0.0;
            for (double l : latencies) {
                sum += l;
                if (l > max_v) max_v = l;
            }
            m_stats.avg_latency_ms = sum / latencies.size();
            m_stats.median_latency_ms = CalcPercentile(latencies, 50.0);
            m_stats.p95_latency_ms = CalcPercentile(latencies, 95.0);
            m_stats.p99_latency_ms = CalcPercentile(latencies, 99.0);
            m_stats.max_latency_ms = max_v;
        }

        m_stats.ram_end_bytes = QueryRam();
        QueryVram(m_stats.vram_budget_bytes, m_stats.vram_usage_bytes);
        m_stats.clip_switch_ms = m_clip_switch_ms;

        m_progress.is_active = 0;
        m_progress.is_finished = 1;
        m_progress.completed_frames = completed;
        m_progress.elapsed_sec = wall_time_sec;
        m_progress.current_fps = m_stats.throughput_fps;
    }

    if (IsStage8L4C2MfLogEnabled()) {
        FILE* file = fopen("scratch/stage8l4c2_logs/mf_media_types.txt", "a");
        if (file) {
            fprintf(file, "native_completed_frames=%u requested_frames=%u result=%s\n",
                    completed, frame_count, completed == frame_count ? "PASS" : "FAIL");
            fclose(file);
        }
    }

    if (pTimelineFile) {
        fclose(pTimelineFile);
        pTimelineFile = nullptr;
    }
    if (pRingTransitionFile) {
        fclose(pRingTransitionFile);
        pRingTransitionFile = nullptr;
    }
    if (pRingAuditFile) {
        fclose(pRingAuditFile);
        pRingAuditFile = nullptr;
    }
    if (m_pSlot0File) {
        fclose(m_pSlot0File);
        m_pSlot0File = nullptr;
    }

    DumpLifecycleLogs();

    m_is_active = false;
    m_is_finished = true;
}

void D3D11NvencPipeline::GetProgress(TelemProgressInfo& out_progress) {
    std::lock_guard<std::mutex> lock(m_progress_mutex);
    out_progress = m_progress;
}

void D3D11NvencPipeline::GetStats(TelemPipelineStats& out_stats) {
    std::lock_guard<std::mutex> lock(m_progress_mutex);
    out_stats = m_stats;
}

void D3D11NvencPipeline::CloseVideo() {
    CloseDecoder();
}

void D3D11NvencPipeline::Destroy() {
    if (m_is_active) {
        Cancel();
    }
    if (m_worker_thread.joinable()) {
        if (std::this_thread::get_id() != m_worker_thread.get_id()) {
            m_worker_thread.join();
        }
    }

    EndNvencSession();
    CloseDecoder();

    for (auto* pView : m_ring_vp_out_views) SafeRelease(pView);
    for (auto* pTex : m_ring_nv12_textures) SafeRelease(pTex);
    for (auto* pInView : m_ring_vp_in_view_huds) SafeRelease(pInView);
    for (auto* pTarget : m_ring_d2d_bitmap_targets) SafeRelease(pTarget);
    for (auto* pTex : m_ring_hud_textures) SafeRelease(pTex);
    for (auto* pTex : m_ring_hud_resolved_textures) SafeRelease(pTex);
    for (auto* pQuery : m_ring_hud_queries) SafeRelease(pQuery);
    for (auto* pQuery : m_ring_vp_queries) SafeRelease(pQuery);
    m_ring_vp_out_views.clear();
    m_ring_nv12_textures.clear();
    m_ring_vp_in_view_huds.clear();
    m_ring_d2d_bitmap_targets.clear();
    m_ring_hud_textures.clear();
    m_ring_hud_resolved_textures.clear();
    m_ring_hud_queries.clear();
    m_ring_vp_queries.clear();
    m_pHudTexture = nullptr;
    SafeRelease(m_pStagingHudTex);
    SafeRelease(m_pHudSyncStagingTex);

    ReleasePreviewTap();

    SafeRelease(m_pVP);
    SafeRelease(m_pVPEnum);
    SafeRelease(m_pVideoContext);
    SafeRelease(m_pVideoDevice);

    SafeRelease(m_brush_white);
    SafeRelease(m_brush_text_muted);
    SafeRelease(m_brush_cyan);
    SafeRelease(m_brush_coral);
    SafeRelease(m_brush_card_bg);
    SafeRelease(m_brush_card_border);

    SafeRelease(m_fmt_time);
    SafeRelease(m_fmt_speed_val);
    SafeRelease(m_fmt_speed_unit);
    SafeRelease(m_fmt_hr_val);
    SafeRelease(m_fmt_hr_unit);
    SafeRelease(m_fmt_label);

    for (auto& ind : m_indicators) {
        ind->DiscardDeviceResources();
    }
    m_indicators.clear();
    m_font_cache.Clear();
    m_icon_cache.Clear();

    SafeRelease(m_pDWriteFactory);
    SafeRelease(m_pD2DContext);
    SafeRelease(m_pD2DDevice);

    SafeRelease(m_pContext);
    SafeRelease(m_pDevice);
    SafeRelease(m_pAdapter3);
    SafeRelease(m_pAdapter);
    SafeRelease(m_pFactory);

    if (m_hNvencDll) {
        FreeLibrary(m_hNvencDll);
        m_hNvencDll = nullptr;
    }

    if (m_compression_csv_file) {
        fflush(m_compression_csv_file);
        fclose(m_compression_csv_file);
        m_compression_csv_file = nullptr;
    }
    m_compression_samples.clear();

    m_configured = false;
    m_video_opened = false;
}

void D3D11NvencPipeline::QueryVram(uint64_t& out_budget, uint64_t& out_usage) {
    out_budget = 0;
    out_usage = 0;
    if (m_pAdapter3) {
        DXGI_QUERY_VIDEO_MEMORY_INFO memInfo{};
        HRESULT hr = m_pAdapter3->QueryVideoMemoryInfo(0, DXGI_MEMORY_SEGMENT_GROUP_LOCAL, &memInfo);
        if (SUCCEEDED(hr)) {
            out_budget = memInfo.Budget;
            out_usage = memInfo.CurrentUsage;
        }
    }
}

uint64_t D3D11NvencPipeline::QueryRam() {
    PROCESS_MEMORY_COUNTERS pmc{};
    if (GetProcessMemoryInfo(GetCurrentProcess(), &pmc, sizeof(pmc))) {
        return pmc.WorkingSetSize;
    }
    return 0;
}

void D3D11NvencPipeline::RecordCompressionSample(uint32_t frame_idx, uint64_t pts, NV_ENC_PIC_TYPE pic_type, uint32_t qp, uint32_t bytes) {
    (void)pts;
    std::lock_guard<std::mutex> lock(m_compression_mutex);

    char ftype = 'P';
    switch (pic_type) {
        case NV_ENC_PIC_TYPE_I:
        case NV_ENC_PIC_TYPE_IDR:
            ftype = 'I';
            m_live_compression_stats.i_frame_count++;
            m_i_frame_qp_sum += qp;
            break;
        case NV_ENC_PIC_TYPE_B:
        case NV_ENC_PIC_TYPE_BI:
            ftype = 'B';
            m_live_compression_stats.b_frame_count++;
            m_b_frame_qp_sum += qp;
            break;
        case NV_ENC_PIC_TYPE_P:
        case NV_ENC_PIC_TYPE_NONREF_P:
        case NV_ENC_PIC_TYPE_SWITCH:
        default:
            ftype = 'P';
            m_live_compression_stats.p_frame_count++;
            m_p_frame_qp_sum += qp;
            break;
    }

    uint8_t clamped_qp = (qp > 255) ? 255 : (uint8_t)qp;
    m_live_compression_stats.qp_histogram[clamped_qp]++;
    m_total_qp_sum += clamped_qp;

    double frame_dur = (m_config.fps_num > 0) ? ((double)m_config.fps_den / (double)m_config.fps_num) : (1001.0 / 30000.0);
    double time_sec = (double)frame_idx * frame_dur;
    double inst_mbps = (frame_dur > 0.0) ? (((double)bytes * 8.0) / frame_dur / 1000000.0) : 0.0;

    m_live_compression_stats.frames_analyzed++;
    m_live_compression_stats.current_qp = clamped_qp;
    m_live_compression_stats.current_frame_type = ftype;
    m_live_compression_stats.current_bitrate_mbps = inst_mbps;
    m_live_compression_stats.total_encoded_bytes += bytes;
    if (inst_mbps > m_live_compression_stats.peak_bitrate_mbps) {
        m_live_compression_stats.peak_bitrate_mbps = inst_mbps;
    }

    FrameCompressionSample sample{};
    sample.frame_index = frame_idx;
    sample.timestamp_sec = time_sec;
    sample.frame_type = ftype;
    sample.qp = clamped_qp;
    sample.encoded_bytes = bytes;
    m_compression_samples.push_back(sample);

    if (m_compression_csv_file) {
        fprintf(m_compression_csv_file, "%.3f,%u,%u,%c,%u\n", time_sec, frame_idx, (unsigned int)clamped_qp, ftype, bytes);
    }
}

void D3D11NvencPipeline::GetCompressionStats(TelemCompressionStats& out_stats) {
    std::lock_guard<std::mutex> lock(m_compression_mutex);
    out_stats = m_live_compression_stats;

    if (out_stats.frames_analyzed > 0) {
        out_stats.mean_qp = (double)m_total_qp_sum / (double)out_stats.frames_analyzed;
        out_stats.i_frame_mean_qp = (out_stats.i_frame_count > 0) ? ((double)m_i_frame_qp_sum / (double)out_stats.i_frame_count) : 0.0;
        out_stats.p_frame_mean_qp = (out_stats.p_frame_count > 0) ? ((double)m_p_frame_qp_sum / (double)out_stats.p_frame_count) : 0.0;
        out_stats.b_frame_mean_qp = (out_stats.b_frame_count > 0) ? ((double)m_b_frame_qp_sum / (double)out_stats.b_frame_count) : 0.0;

        out_stats.mean_bytes_per_frame = (double)out_stats.total_encoded_bytes / (double)out_stats.frames_analyzed;
        double frame_dur = (m_config.fps_num > 0) ? ((double)m_config.fps_den / (double)m_config.fps_num) : (1001.0 / 30000.0);
        out_stats.average_bitrate_mbps = (frame_dur > 0.0) ? (out_stats.mean_bytes_per_frame * 8.0 / frame_dur / 1000000.0) : 0.0;

        // Min & Max QP
        uint32_t min_q = 255;
        uint32_t max_q = 0;
        bool found = false;
        for (uint32_t q = 0; q < 256; ++q) {
            if (out_stats.qp_histogram[q] > 0) {
                if (!found) { min_q = q; found = true; }
                max_q = q;
            }
        }
        out_stats.min_qp = found ? min_q : 0;
        out_stats.max_qp = found ? max_q : 0;

        // Percentiles: p10, p50 (median), p90, p95
        uint64_t total = out_stats.frames_analyzed;
        uint64_t target_p10 = (uint64_t)(0.10 * (double)total);
        uint64_t target_p50 = (uint64_t)(0.50 * (double)total);
        uint64_t target_p90 = (uint64_t)(0.90 * (double)total);
        uint64_t target_p95 = (uint64_t)(0.95 * (double)total);

        uint64_t cum = 0;
        bool set_p10 = false, set_p50 = false, set_p90 = false, set_p95 = false;
        for (uint32_t q = 0; q < 256; ++q) {
            cum += out_stats.qp_histogram[q];
            if (!set_p10 && cum >= target_p10) { out_stats.p10_qp = (double)q; set_p10 = true; }
            if (!set_p50 && cum >= target_p50) { out_stats.median_qp = (double)q; out_stats.p50_qp = (double)q; set_p50 = true; }
            if (!set_p90 && cum >= target_p90) { out_stats.p90_qp = (double)q; set_p90 = true; }
            if (!set_p95 && cum >= target_p95) { out_stats.p95_qp = (double)q; set_p95 = true; }
        }
    }
}

bool D3D11NvencPipeline::ExportCompressionCsv(const wchar_t* csv_path) {
    if (!csv_path || csv_path[0] == L'\0') return false;
    std::lock_guard<std::mutex> lock(m_compression_mutex);

    FILE* fp = _wfopen(csv_path, L"w");
    if (!fp) return false;
    setvbuf(fp, nullptr, _IOFBF, 64 * 1024);

    fprintf(fp, "time_sec,frame,avg_qp,frame_type,encoded_bytes\n");
    for (const auto& s : m_compression_samples) {
        fprintf(fp, "%.3f,%u,%u,%c,%u\n", s.timestamp_sec, s.frame_index, (unsigned int)s.qp, s.frame_type, s.encoded_bytes);
    }
    fflush(fp);
    fclose(fp);
    return true;
}

void D3D11NvencPipeline::ReleasePreviewTap() {
    for (auto* pView : m_ring_preview_in_views) SafeRelease(pView);
    m_ring_preview_in_views.clear();

    for (int i = 0; i < 2; ++i) {
        SafeRelease(m_preview_output_view[i]);
        SafeRelease(m_preview_output_tex[i]);
        SafeRelease(m_preview_staging_tex[i]);
        SafeRelease(m_preview_query[i]);
    }

    SafeRelease(m_pPreviewVP);
    SafeRelease(m_pPreviewVPEnum);

    {
        std::lock_guard<std::mutex> lock(m_preview_mutex);
        m_preview_ram_buffer.clear();
        m_preview_has_new_frame = false;
        m_preview_ready_frame_idx = 0;
        m_preview_ready_pts = 0.0;
    }

    m_preview_tap_enabled = false;
    m_preview_capture_in_flight = false;
    m_preview_in_flight_slot = 0;
    m_preview_next_slot = 0;
}

bool D3D11NvencPipeline::ConfigurePreviewTap(uint32_t width, uint32_t height, double target_fps) {
    if (m_is_active) return false;
    ReleasePreviewTap();

    m_preview_tap_width = (width > 0) ? width : 960;
    m_preview_tap_height = (height > 0) ? height : 540;
    m_preview_interval_sec = (target_fps > 0.0) ? (1.0 / target_fps) : 0.125;
    m_preview_last_submit_time = 0.0;

    if (!m_pDevice || !m_pVideoDevice) {
        m_preview_tap_enabled = true;
        return true;
    }

    // 1. Create Preview VideoProcessor Enumerator & Processor
    D3D11_VIDEO_PROCESSOR_CONTENT_DESC previewVpDesc{};
    previewVpDesc.InputFrameFormat = D3D11_VIDEO_FRAME_FORMAT_PROGRESSIVE;
    previewVpDesc.InputFrameRate.Numerator = (m_config.fps_num > 0) ? m_config.fps_num : 60;
    previewVpDesc.InputFrameRate.Denominator = (m_config.fps_den > 0) ? m_config.fps_den : 1;
    previewVpDesc.InputWidth = (m_config.width > 0) ? m_config.width : 3840;
    previewVpDesc.InputHeight = (m_config.height > 0) ? m_config.height : 2160;
    previewVpDesc.OutputFrameRate.Numerator = previewVpDesc.InputFrameRate.Numerator;
    previewVpDesc.OutputFrameRate.Denominator = previewVpDesc.InputFrameRate.Denominator;
    previewVpDesc.OutputWidth = m_preview_tap_width;
    previewVpDesc.OutputHeight = m_preview_tap_height;
    previewVpDesc.Usage = D3D11_VIDEO_USAGE_PLAYBACK_NORMAL;

    HRESULT hr = m_pVideoDevice->CreateVideoProcessorEnumerator(&previewVpDesc, &m_pPreviewVPEnum);
    if (FAILED(hr)) {
        printf("[PREVIEW ERROR] Failed to create preview VP enumerator: 0x%08X\n", (unsigned int)hr);
        fflush(stdout);
        ReleasePreviewTap();
        return false;
    }

    hr = m_pVideoDevice->CreateVideoProcessor(m_pPreviewVPEnum, 0, &m_pPreviewVP);
    if (FAILED(hr)) {
        printf("[PREVIEW ERROR] Failed to create preview VideoProcessor: 0x%08X\n", (unsigned int)hr);
        fflush(stdout);
        ReleasePreviewTap();
        return false;
    }

    RECT srcRect = { 0, 0, (LONG)m_config.width, (LONG)m_config.height };
    RECT dstRect = { 0, 0, (LONG)m_preview_tap_width, (LONG)m_preview_tap_height };
    m_pVideoContext->VideoProcessorSetStreamSourceRect(m_pPreviewVP, 0, TRUE, &srcRect);
    m_pVideoContext->VideoProcessorSetStreamDestRect(m_pPreviewVP, 0, TRUE, &dstRect);
    m_pVideoContext->VideoProcessorSetOutputTargetRect(m_pPreviewVP, TRUE, &dstRect);

    // 2. Create double-buffered preview render targets & staging textures & queries
    D3D11_TEXTURE2D_DESC outDesc{};
    outDesc.Width = m_preview_tap_width;
    outDesc.Height = m_preview_tap_height;
    outDesc.MipLevels = 1;
    outDesc.ArraySize = 1;
    outDesc.Format = DXGI_FORMAT_B8G8R8A8_UNORM;
    outDesc.SampleDesc.Count = 1;
    outDesc.SampleDesc.Quality = 0;
    outDesc.Usage = D3D11_USAGE_DEFAULT;
    outDesc.BindFlags = D3D11_BIND_RENDER_TARGET;

    D3D11_TEXTURE2D_DESC stgDesc{};
    stgDesc.Width = m_preview_tap_width;
    stgDesc.Height = m_preview_tap_height;
    stgDesc.MipLevels = 1;
    stgDesc.ArraySize = 1;
    stgDesc.Format = DXGI_FORMAT_B8G8R8A8_UNORM;
    stgDesc.SampleDesc.Count = 1;
    stgDesc.SampleDesc.Quality = 0;
    stgDesc.Usage = D3D11_USAGE_STAGING;
    stgDesc.CPUAccessFlags = D3D11_CPU_ACCESS_READ;
    stgDesc.BindFlags = 0;

    D3D11_VIDEO_PROCESSOR_OUTPUT_VIEW_DESC vpOutViewDesc{};
    vpOutViewDesc.ViewDimension = D3D11_VPOV_DIMENSION_TEXTURE2D;
    vpOutViewDesc.Texture2D.MipSlice = 0;

    D3D11_QUERY_DESC qDesc{};
    qDesc.Query = D3D11_QUERY_EVENT;

    for (int i = 0; i < 2; ++i) {
        hr = m_pDevice->CreateTexture2D(&outDesc, nullptr, &m_preview_output_tex[i]);
        if (FAILED(hr)) { ReleasePreviewTap(); return false; }

        hr = m_pVideoDevice->CreateVideoProcessorOutputView(m_preview_output_tex[i], m_pPreviewVPEnum, &vpOutViewDesc, &m_preview_output_view[i]);
        if (FAILED(hr)) { ReleasePreviewTap(); return false; }

        hr = m_pDevice->CreateTexture2D(&stgDesc, nullptr, &m_preview_staging_tex[i]);
        if (FAILED(hr)) { ReleasePreviewTap(); return false; }

        hr = m_pDevice->CreateQuery(&qDesc, &m_preview_query[i]);
        if (FAILED(hr)) { ReleasePreviewTap(); return false; }
    }

    // 3. Create input views for ring NV12 textures if they already exist
    if (!m_ring_nv12_textures.empty()) {
        D3D11_VIDEO_PROCESSOR_INPUT_VIEW_DESC inDesc{};
        inDesc.FourCC = 0;
        inDesc.ViewDimension = D3D11_VPIV_DIMENSION_TEXTURE2D;
        inDesc.Texture2D.MipSlice = 0;
        inDesc.Texture2D.ArraySlice = 0;

        for (size_t i = 0; i < m_ring_nv12_textures.size(); ++i) {
            ID3D11VideoProcessorInputView* pInView = nullptr;
            hr = m_pVideoDevice->CreateVideoProcessorInputView(m_ring_nv12_textures[i], m_pPreviewVPEnum, &inDesc, &pInView);
            if (SUCCEEDED(hr) && pInView) {
                m_ring_preview_in_views.push_back(pInView);
            }
        }
    }

    {
        std::lock_guard<std::mutex> lock(m_preview_mutex);
        m_preview_ram_buffer.assign((size_t)m_preview_tap_width * 4 * m_preview_tap_height, 0);
        m_preview_has_new_frame = false;
    }

    m_preview_tap_enabled = true;
    printf("[PREVIEW CONFIG %p] Configured native preview tap: %ux%u @ %.1f FPS (interval %.3f s)\n",
           this, m_preview_tap_width, m_preview_tap_height, (m_preview_interval_sec > 0.0) ? (1.0 / m_preview_interval_sec) : 0.0, m_preview_interval_sec);
    fflush(stdout);
    return true;
}

bool D3D11NvencPipeline::PollPreviewFrame(uint8_t* out_bgra, uint32_t buffer_size, uint32_t* out_width, uint32_t* out_height, uint32_t* out_frame_idx, double* out_pts) {
    if (!out_bgra || !out_width || !out_height || !out_frame_idx || !out_pts) return false;
    std::lock_guard<std::mutex> lock(m_preview_mutex);
    if (!m_preview_has_new_frame || m_preview_ram_buffer.empty()) {
        return false;
    }
    size_t required_size = (size_t)m_preview_tap_width * 4 * m_preview_tap_height;
    if (buffer_size < required_size) {
        return false;
    }
    memcpy(out_bgra, m_preview_ram_buffer.data(), required_size);
    *out_width = m_preview_tap_width;
    *out_height = m_preview_tap_height;
    *out_frame_idx = m_preview_ready_frame_idx;
    *out_pts = m_preview_ready_pts;
    m_preview_has_new_frame = false;
    return true;
}

void D3D11NvencPipeline::DumpLifecycleLogs() {
    if (m_lifecycle_logs.empty()) return;

    CreateDirectoryA("scratch", NULL);
    CreateDirectoryA("scratch/gui_random_hud_forensics", NULL);

    // Determine target file name runN_lifecycle.jsonl
    int run_idx = 1;
    char pathBuf[256];
    while (true) {
        snprintf(pathBuf, sizeof(pathBuf), "scratch/gui_random_hud_forensics/run%d_lifecycle.jsonl", run_idx);
        FILE* fTest = fopen(pathBuf, "r");
        if (!fTest) {
            break; // found unused slot
        }
        fclose(fTest);
        run_idx++;
    }

    printf("[LIFECYCLE DUMP] Writing %zu records to %s and current_lifecycle.jsonl\n", m_lifecycle_logs.size(), pathBuf);
    fflush(stdout);

    FILE* fOut = fopen(pathBuf, "w");
    FILE* fCurr = fopen("scratch/gui_random_hud_forensics/current_lifecycle.jsonl", "w");

    for (const auto& entry : m_lifecycle_logs) {
        char lineBuf[1024];
        snprintf(lineBuf, sizeof(lineBuf),
            "{\"frame_index\":%u,\"qpc_timestamp\":%llu,\"ring_slot\":%d,\"wrap_count\":%d,"
            "\"slot_owner_before\":%d,\"slot_owner_after\":%d,\"slot_in_flight\":%d,"
            "\"submitted_input_frame\":%u,\"submitted_slot\":%d,\"ownership_queue_depth\":%zu,"
            "\"hud_texture_ptr\":\"0x%p\",\"d2d_target_ptr\":\"0x%p\",\"vp_hud_input_view_ptr\":\"0x%p\","
            "\"hud_query_status_before_reuse\":\"0x%08X\",\"vp_query_status_before_reuse\":\"0x%08X\","
            "\"begin_draw_status\":%d,\"end_draw_hresult\":\"0x%08X\",\"d2d_flush_hresult\":\"0x%08X\","
            "\"d2d_tag1\":%llu,\"d2d_tag2\":%llu,\"composite_result\":%s,\"vp_blt_hresult\":\"0x%08X\","
            "\"encoded_frame\":%d,\"released_input_frame\":%d,\"released_slot\":%d,"
            "\"active_indicators\":%u,\"device_removed_reason\":\"0x%08X\"}\n",
            entry.frame_index, (unsigned long long)entry.qpc_timestamp, entry.ring_slot, entry.wrap_count,
            entry.slot_owner_before, entry.slot_owner_after, entry.slot_in_flight,
            entry.submitted_input_frame, entry.submitted_slot, entry.ownership_queue_depth,
            entry.hud_texture_ptr, entry.d2d_target_ptr, entry.vp_hud_input_view_ptr,
            (unsigned int)entry.hud_query_status_before_reuse, (unsigned int)entry.vp_query_status_before_reuse,
            entry.begin_draw_status, (unsigned int)entry.end_draw_hresult, (unsigned int)entry.d2d_flush_hresult,
            (unsigned long long)entry.d2d_tag1, (unsigned long long)entry.d2d_tag2,
            entry.composite_result ? "true" : "false", (unsigned int)entry.vp_blt_hresult,
            entry.encoded_frame, entry.released_input_frame, entry.released_slot,
            entry.active_indicators, (unsigned int)entry.device_removed_reason
        );
        if (fOut) fputs(lineBuf, fOut);
        if (fCurr) fputs(lineBuf, fCurr);
    }

    if (fOut) fclose(fOut);
    if (fCurr) fclose(fCurr);
}
