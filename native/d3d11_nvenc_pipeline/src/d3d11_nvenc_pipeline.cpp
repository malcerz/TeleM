#include "d3d11_nvenc_pipeline.h"
#include <iostream>
#include <iomanip>
#include <algorithm>
#include <cstdlib>
#include <cstdio>
#include "indicators/lean_indicator.h"
#include "hud_profile.h"

thread_local TelemD2DStateTrace* g_telem_d2d_state_trace = nullptr;

static std::string CadenceTraceFile(const char* name) {
    char dir[1024] = {};
    DWORD len = GetEnvironmentVariableA("TELEM_CADENCE_TRACE_DIR", dir, (DWORD)sizeof(dir));
    if (len == 0 || len >= sizeof(dir)) return {};
    std::string path(dir, len);
    if (!path.empty() && path.back() != '\\' && path.back() != '/') path += '\\';
    path += name;
    return path;
}

static void AppendCadenceAlphaTrace(const char* stage, float raw, float normalized) {
    const std::string path = CadenceTraceFile("fill_alpha_trace.csv");
    if (path.empty()) return;
    FILE* f = nullptr;
    if (fopen_s(&f, path.c_str(), "a+") != 0 || !f) return;
    fseek(f, 0, SEEK_END);
    if (ftell(f) == 0) {
        std::fprintf(f, "stage,field_name,type,raw_value,normalized_value,expected_value\n");
    }
    std::fprintf(f, "%s,fill_alpha,float,%.9g,%.9g,%.9g\n",
                 stage, raw, normalized, 200.0f / 255.0f);
    std::fclose(f);
}

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

static bool IsDeterminismProbeFrame(uint32_t frame) {
    switch (frame) {
        case 0: case 1: case 2: case 5: case 10: case 20: case 30:
        case 40: case 50: case 60: case 80: case 99:
            return true;
        default:
            return false;
    }
}

static bool IsTargetBindingProbeFrame(uint32_t frame) {
    switch (frame) {
        case 0: case 1: case 2: case 5: case 10: case 20: case 30:
        case 40: case 60: case 80: case 99:
            return true;
        default:
            return false;
    }
}

static bool IsStaticHudDiagnostic() {
    char value[8] = {};
    DWORD len = GetEnvironmentVariableA("TELEM_NATIVE_STATIC_HUD", value, (DWORD)sizeof(value));
    return len > 0 && len < sizeof(value) && value[0] == '1';
}

static bool IsFreshResourceDiagnostic() {
    char value[8] = {};
    DWORD len = GetEnvironmentVariableA("TELEM_NATIVE_FRESH_RESOURCES", value, (DWORD)sizeof(value));
    return len > 0 && len < sizeof(value) && value[0] == '1';
}

static bool IsSingleHudDiagnostic() {
    char value[8] = {};
    DWORD len = GetEnvironmentVariableA("TELEM_NATIVE_SINGLE_HUD", value, (DWORD)sizeof(value));
    return len > 0 && len < sizeof(value) && value[0] == '1';
}

static std::string DeterminismD2DMode() {
    char value[8] = {};
    DWORD len = GetEnvironmentVariableA("TELEM_NATIVE_D2D_MODE", value, (DWORD)sizeof(value));
    if (len > 0 && len < sizeof(value)) return std::string(value, len);
    return "P";
}

static bool IsHoldHudUntilEncodeDiagnostic() {
    char value[8] = {};
    DWORD len = GetEnvironmentVariableA("TELEM_NATIVE_HOLD_HUD_UNTIL_ENCODE", value, (DWORD)sizeof(value));
    return len > 0 && len < sizeof(value) && value[0] == '1';
}

static int DeterminismHudPoolSize() {
    char value[8] = {};
    DWORD len = GetEnvironmentVariableA("TELEM_NATIVE_HUD_POOL", value, (DWORD)sizeof(value));
    if (len > 0 && len < sizeof(value)) {
        int n = atoi(value);
        if (n >= 2 && n <= 4) return n;
    }
    return 0;
}

static bool IsD2DStateDiagnostic(const char* name) {
    char value[8] = {};
    DWORD len = GetEnvironmentVariableA(name, value, (DWORD)sizeof(value));
    return len > 0 && len < sizeof(value) && value[0] == '1';
}

static bool IsD2DResetStateDiagnostic() {
    return IsD2DStateDiagnostic("TELEM_NATIVE_D2D_RESET_STATE");
}

static bool IsFreshD2DContextDiagnostic() {
    return IsD2DStateDiagnostic("TELEM_NATIVE_FRESH_D2D_CONTEXT");
}

static bool IsD2DSingleThreadDiagnostic() {
    return IsD2DStateDiagnostic("TELEM_NATIVE_D2D_SINGLE_THREAD");
}

static bool IsD2DMinimalDrawDiagnostic() {
    return IsD2DStateDiagnostic("TELEM_NATIVE_D2D_MINIMAL_DRAW");
}

static std::string D2DTargetDetachMode() {
    char value[16] = {};
    DWORD len = GetEnvironmentVariableA("TELEM_NATIVE_D2D_DETACH_MODE", value, (DWORD)sizeof(value));
    if (len > 0 && len < sizeof(value)) {
        std::string mode(value, len);
        if (mode == "A" || mode == "B" || mode == "C" || mode == "D") return mode;
    }
    // The production path already detaches the D2D target before the VP use.
    // Mode B is therefore the safe diagnostic default when a caller only
    // enables the determinism directory.
    return "B";
}

static bool IsD3D11DynamicControlDiagnostic() {
    return IsD2DStateDiagnostic("TELEM_NATIVE_D3D11_DYNAMIC_CONTROL");
}

static bool IsCopyOutControlDiagnostic() {
    return IsD2DStateDiagnostic("TELEM_NATIVE_COPY_OUT");
}

static bool IsD3D11CrossApiDebugDiagnostic() {
    return IsD2DStateDiagnostic("TELEM_NATIVE_D3D11_DEBUG");
}

static uint32_t InteractionLadderStage() {
    char value[16] = {};
    DWORD len = GetEnvironmentVariableA("TELEM_NATIVE_PIPELINE_INTERACTION_STAGE",
                                       value, (DWORD)sizeof(value));
    if (len == 0 || len >= sizeof(value)) return 0;
    const char* digit = (value[0] == 'L' || value[0] == 'l') ? value + 1 : value;
    if (digit[0] >= '1' && digit[0] <= '6' && digit[1] == '\0') {
        return (uint32_t)(digit[0] - '0');
    }
    return 0;
}

static bool IsInteractionContextSerializationRequested() {
    char value[8] = {};
    DWORD len = GetEnvironmentVariableA("TELEM_NATIVE_CONTEXT_SERIALIZE",
                                       value, (DWORD)sizeof(value));
    return len > 0 && len < sizeof(value) && value[0] == '1';
}

static const char* InteractionStageName(uint32_t stage) {
    switch (stage) {
        case 1: return "L1_PROD_DEVICE_D2D";
        case 2: return "L2_PROD_RESOURCES";
        case 3: return "L3_DECODE_ACTIVE";
        case 4: return "L4_VP_BACKGROUND";
        case 5: return "L5_VP_HUD";
        case 6: return "L6_NVENC";
        default: return "NONE";
    }
}

static bool IsSeparateHudDeviceRequested() {
    char value[8] = {};
    DWORD len = GetEnvironmentVariableA("TELEM_NATIVE_HUD_SEPARATE_DEVICE",
                                       value, (DWORD)sizeof(value));
    return len > 0 && len < sizeof(value) && value[0] == '1';
}

static bool IsSeparateHudCrossDeviceRequested() {
    char value[8] = {};
    DWORD len = GetEnvironmentVariableA("TELEM_NATIVE_HUD_CROSS_DEVICE",
                                       value, (DWORD)sizeof(value));
    return len > 0 && len < sizeof(value) && value[0] == '1';
}

static std::string SeparateHudMode() {
    char value[32] = {};
    DWORD len = GetEnvironmentVariableA("TELEM_NATIVE_HUD_SEPARATE_MODE",
                                       value, (DWORD)sizeof(value));
    if (len > 0 && len < sizeof(value)) return std::string(value, len);
    return "L3_MARKER";
}

static std::string AdapterDescriptionUtf8(const DXGI_ADAPTER_DESC& desc) {
    char buffer[512] = {};
    int n = WideCharToMultiByte(CP_UTF8, 0, desc.Description, -1,
                                buffer, (int)sizeof(buffer), nullptr, nullptr);
    if (n <= 0) return std::string();
    return std::string(buffer, (size_t)(n - 1));
}

static std::string D2DWidgetGroupDiagnostic() {
    char value[8] = {};
    DWORD len = GetEnvironmentVariableA("TELEM_NATIVE_WIDGET_GROUP", value, (DWORD)sizeof(value));
    if (len > 0 && len < sizeof(value)) return std::string(value, len);
    return "G";
}

static bool IncludeD2DWidgetForGroup(const IndicatorBase& indicator, const std::string& group) {
    if (group.empty() || group == "G") return true;
    TelemIndicatorType type = indicator.GetType();
    if (group == "A") {
        return type == TELEM_IND_TEXT || type == TELEM_IND_TIME_DISPLAY;
    }
    if (group == "B") {
        return type == TELEM_IND_TEXT || type == TELEM_IND_TIME_DISPLAY ||
               type == TELEM_IND_BAR_RULER_H || type == TELEM_IND_BAR_RULER_V ||
               type == TELEM_IND_BAR_SEGMENTS;
    }
    if (group == "C") {
        return IncludeD2DWidgetForGroup(indicator, "B") || type == TELEM_IND_GAUGE;
    }
    if (group == "D") {
        return IncludeD2DWidgetForGroup(indicator, "C") || type == TELEM_IND_CHART;
    }
    if (group == "E") {
        return IncludeD2DWidgetForGroup(indicator, "D") || type == TELEM_IND_MAP;
    }
    if (group == "F") {
        // Lean is represented by text/geometry indicators in the canonical
        // layout; keep all non-map widgets in this intermediate diagnostic.
        return type != TELEM_IND_MAP;
    }
    return true;
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
    TelemHudProfile::Reset();
    InitDeterminismDiagnostics();

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

    // Production keeps the profile-safe ring minimum.  A deliberately
    // opt-in diagnostic override lets the ring-wrap experiment exercise
    // smaller rings without changing the default architecture.
    char ring_override[32] = {};
    DWORD ring_override_len = GetEnvironmentVariableA(
        "TELEM_NATIVE_RING_SIZE", ring_override, (DWORD)sizeof(ring_override));
    const bool diagnostic_ring_override =
        ring_override_len > 0 && ring_override_len < sizeof(ring_override);
    if (diagnostic_ring_override) {
        unsigned long requested = std::strtoul(ring_override, nullptr, 10);
        if (requested >= 1 && requested <= 256) {
            m_config.ring_size = (uint32_t)requested;
            printf("[RING DIAG] TELEM_NATIVE_RING_SIZE=%u\n", m_config.ring_size);
            fflush(stdout);
        }
    }
    // Ring size for persistent D3D11 textures (needs >= 64 for the normal
    // lookahead/B-frame profile; diagnostic override is intentionally exempt).
    if (!diagnostic_ring_override && m_config.ring_size < 64) m_config.ring_size = 64;

    if (m_config.fps_den == 0) m_config.fps_den = 1001;
    if (m_config.fps_num == 0) m_config.fps_num = 30000;
    if (m_config.width == 0) m_config.width = 3840;
    if (m_config.height == 0) m_config.height = 2160;

    if (!SelectAdapter()) return false;
    if (!CreateDevice()) return false;
    if (!CreateHudResources()) return false;
    if (!CreateDWrite()) return false;
    if (!CreateBrushes()) return false;
    if (m_interaction_stage == 1) {
        // L1 deliberately stops after the production device and D2D setup.
        // A single production-format HUD texture/target is enough for the
        // dynamic D2D sanity loop; no decoder, VP or NVENC object is created.
        if (!CreateLadderHudResources()) return false;
        m_configured = true;
        return true;
    }
    if (!CreateVideoProcessor()) return false;
    if (!CreateRingResources()) return false;
    if (m_hud_separate_device) {
        if (!CreateSeparateHudDevice()) return false;
    }

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
            m_adapter_index = idx;
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
    if (m_config.enable_debug_layer ||
        (m_determinism_diag && IsD3D11CrossApiDebugDiagnostic())) {
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

    RecordInteractionIdentity("PRODUCTION_DEVICE", "created", "ID3D11Device",
                              m_pDevice, m_pContext);
    RecordInteractionIdentity("PRODUCTION_DEVICE", "created", "ID3D11DeviceContext",
                              m_pContext, m_pContext);
    RecordInteractionIdentity("PRODUCTION_DEVICE", "created", "IDXGIAdapter1",
                              m_pAdapter, m_pContext);

    if (m_determinism_diag && IsD3D11CrossApiDebugDiagnostic()) {
        HRESULT qhr = m_pDevice->QueryInterface(__uuidof(ID3D11InfoQueue),
                                                reinterpret_cast<void**>(&m_diag_info_queue));
        if (m_d3d11_debug_file) {
            fprintf(m_d3d11_debug_file, "device_create_hr=0x%08X,debug_flags=0x%08X,info_queue_hr=0x%08X\n",
                    (unsigned int)hr, (unsigned int)flags, (unsigned int)qhr);
            fflush(m_d3d11_debug_file);
        }
    }

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

    // Production historically enables multithread protection. The interaction
    // audit records the real state and offers explicit MT-OFF/MT-ON probes
    // without changing the default behavior.
    ID3D10Multithread* pMultithread = nullptr;
    if (SUCCEEDED(m_pDevice->QueryInterface(__uuidof(ID3D10Multithread), (void**)&pMultithread))) {
        m_diag_multithread_available = true;
        m_diag_multithread_before = pMultithread->GetMultithreadProtected();
        char mode[16] = {};
        DWORD mode_len = GetEnvironmentVariableA("TELEM_NATIVE_MULTITHREAD_MODE",
                                                 mode, (DWORD)sizeof(mode));
        bool explicit_off = mode_len > 0 && mode_len < sizeof(mode) &&
                            (_stricmp(mode, "OFF") == 0 || mode[0] == '0');
        bool explicit_on = mode_len > 0 && mode_len < sizeof(mode) &&
                           (_stricmp(mode, "ON") == 0 || mode[0] == '1');
        if (explicit_off) pMultithread->SetMultithreadProtected(FALSE);
        else if (explicit_on || mode_len == 0 || _stricmp(mode, "DEFAULT") == 0) {
            pMultithread->SetMultithreadProtected(TRUE);
        } else {
            // Preserve the production default for unknown diagnostic values.
            pMultithread->SetMultithreadProtected(TRUE);
        }
        m_diag_multithread_after = pMultithread->GetMultithreadProtected();
        if (m_interaction_decoder_file) {
            fprintf(m_interaction_decoder_file,
                    "MULTITHREAD_INTERFACE=available\nMULTITHREAD_PROTECTED_BEFORE=%s\nMULTITHREAD_PROTECTED_AFTER=%s\nMULTITHREAD_MODE=%s\n",
                    m_diag_multithread_before ? "TRUE" : "FALSE",
                    m_diag_multithread_after ? "TRUE" : "FALSE",
                    mode_len ? mode : "DEFAULT");
            fflush(m_interaction_decoder_file);
        }
        if (m_interaction_identity_file) {
            RecordInteractionIdentity("PRODUCTION_DEVICE", "multithread", "ID3D10Multithread",
                                      pMultithread, m_pContext);
        }
        pMultithread->Release();
    } else if (m_interaction_decoder_file) {
        fprintf(m_interaction_decoder_file,
                "MULTITHREAD_INTERFACE=unavailable\nMULTITHREAD_PROTECTED_BEFORE=UNKNOWN\nMULTITHREAD_PROTECTED_AFTER=UNKNOWN\n");
        fflush(m_interaction_decoder_file);
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

    D2D1_CREATION_PROPERTIES creation_properties{};
    const D2D1_CREATION_PROPERTIES* creation_properties_ptr = nullptr;
    if (m_determinism_diag && IsD2DStateDiagnostic("TELEM_NATIVE_D2D_DEBUG")) {
        creation_properties.threadingMode = D2D1_THREADING_MODE_MULTI_THREADED;
        creation_properties.debugLevel = D2D1_DEBUG_LEVEL_INFORMATION;
        creation_properties.options = D2D1_DEVICE_CONTEXT_OPTIONS_NONE;
        creation_properties_ptr = &creation_properties;
    }
    hr = pfnCreateDevice(pDxgiDevice, creation_properties_ptr, &m_pD2DDevice);
    RecordInteractionIdentity("HUD/D2D", "created", "IDXGIDevice", pDxgiDevice, m_pContext);
    pDxgiDevice->Release();
    if (FAILED(hr)) return false;

    hr = m_pD2DDevice->CreateDeviceContext(D2D1_DEVICE_CONTEXT_OPTIONS_NONE, &m_pD2DContext);
    if (FAILED(hr)) return false;

    m_pD2DContext->SetAntialiasMode(D2D1_ANTIALIAS_MODE_PER_PRIMITIVE);
    m_pD2DContext->SetTextAntialiasMode(D2D1_TEXT_ANTIALIAS_MODE_GRAYSCALE);

    RecordInteractionIdentity("HUD/D2D", "created", "ID2D1Device", m_pD2DDevice, m_pContext);
    RecordInteractionIdentity("HUD/D2D", "created", "ID2D1DeviceContext", m_pD2DContext, m_pContext);

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

    RecordInteractionIdentity("VIDEO_PROCESSOR", "created", "ID3D11VideoDevice",
                              m_pVideoDevice, m_pContext);
    RecordInteractionIdentity("VIDEO_PROCESSOR", "created", "ID3D11VideoContext",
                              m_pVideoContext, m_pContext);

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

    D3D11_VIDEO_PROCESSOR_CAPS vpCaps{};
    if (SUCCEEDED(m_pVPEnum->GetVideoProcessorCaps(&vpCaps))) {
        printf("[VP CAPS] max_input_streams=%u max_stream_states=%u feature_caps=0x%08X filter_caps=0x%08X\n",
               vpCaps.MaxInputStreams, vpCaps.MaxStreamStates,
               vpCaps.FeatureCaps, vpCaps.FilterCaps);
        fflush(stdout);
    }

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
    UINT hudFormatFlags = 0;
    HRESULT hrHudCheck = m_pVPEnum->CheckVideoProcessorFormat(DXGI_FORMAT_B8G8R8A8_UNORM, &hudFormatFlags);
    printf("[VP FORMAT %p] Format BGRA8: hr=0x%08X flags=0x%X (Input: %d)\n",
           this, (unsigned int)hrHudCheck, hudFormatFlags,
           (hudFormatFlags & D3D11_VIDEO_PROCESSOR_FORMAT_SUPPORT_INPUT) ? 1 : 0);
    fflush(stdout);

    return true;
}

bool D3D11NvencPipeline::CreateRingResources() {
    for (auto* pView : m_ring_vp_out_views) SafeRelease(pView);
    for (auto* pView : m_ring_vp_bgra_out_views) SafeRelease(pView);
    for (auto* pTex : m_ring_nv12_textures) SafeRelease(pTex);
    for (auto* pInView : m_ring_vp_in_view_huds) SafeRelease(pInView);
    for (auto* pTarget : m_ring_d2d_bitmap_targets) SafeRelease(pTarget);
    for (auto* pTarget : m_ring_d2d_bgra_composite_targets) SafeRelease(pTarget);
    for (auto* pInView : m_ring_vp_in_view_bgra_composites) SafeRelease(pInView);
    for (auto* pTex : m_ring_hud_textures) SafeRelease(pTex);
    for (auto* pTex : m_ring_hud_resolved_textures) SafeRelease(pTex);
    for (auto* pTex : m_ring_bgra_composite_textures) SafeRelease(pTex);
    for (auto* pSource : m_ring_d2d_hud_sources) SafeRelease(pSource);
    for (auto* pSource : m_ring_d2d_bgra_video_sources) SafeRelease(pSource);
    for (auto* pView : m_ring_preview_in_views) SafeRelease(pView);
    for (auto* pQuery : m_ring_hud_queries) SafeRelease(pQuery);
    for (auto* pQuery : m_ring_vp_queries) SafeRelease(pQuery);
    m_ring_vp_out_views.clear();
    m_ring_vp_bgra_out_views.clear();
    m_ring_nv12_textures.clear();
    m_ring_vp_in_view_huds.clear();
    m_ring_d2d_bitmap_targets.clear();
    m_ring_d2d_bgra_composite_targets.clear();
    m_ring_vp_in_view_bgra_composites.clear();
    m_ring_hud_textures.clear();
    m_ring_hud_resolved_textures.clear();
    m_ring_bgra_composite_textures.clear();
    m_ring_d2d_hud_sources.clear();
    m_ring_d2d_bgra_video_sources.clear();
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

        D2D1_BITMAP_PROPERTIES1 sourceBp = bp;
        sourceBp.bitmapOptions = D2D1_BITMAP_OPTIONS_NONE;
        ID2D1Bitmap1* pHudSource = nullptr;
        IDXGISurface1* pHudSourceSurface = nullptr;
        hr = pHudTex->QueryInterface(
            __uuidof(IDXGISurface1), (void**)&pHudSourceSurface
        );
        if (FAILED(hr)) return false;
        hr = m_pD2DContext->CreateBitmapFromDxgiSurface(
            pHudSourceSurface, &sourceBp, &pHudSource
        );
        pHudSourceSurface->Release();
        if (FAILED(hr)) return false;
        m_ring_d2d_hud_sources.push_back(pHudSource);

        ID3D11VideoProcessorInputView* pVPInViewHUD = nullptr;
        hr = m_pVideoDevice->CreateVideoProcessorInputView(pHudTex, m_pVPEnum, &inDesc, &pVPInViewHUD);
        if (FAILED(hr)) {
            printf("[RING ERROR] CreateVideoProcessorInputView for pHudTex failed: 0x%08X\n", (unsigned int)hr);
            return false;
        }
        m_ring_vp_in_view_huds.push_back(pVPInViewHUD);

        // 3. GPU-only composition surfaces.  Keep the VP BGRA output as a
        // source texture and use a separate BGRA render target for D2D.  A
        // D2D target cannot safely be written by VideoProcessor and D2D in
        // the same frame on all drivers (D2DERR_RECREATE_TARGET).
        ID3D11Texture2D* pVideoBgraTex = nullptr;
        hr = m_pDevice->CreateTexture2D(&hudDesc, NULL, &pVideoBgraTex);
        if (FAILED(hr)) return false;
        m_ring_hud_resolved_textures.push_back(pVideoBgraTex);

        ID3D11VideoProcessorOutputView* pVideoBgraOutView = nullptr;
        hr = m_pVideoDevice->CreateVideoProcessorOutputView(
            pVideoBgraTex, m_pVPEnum, &outDesc, &pVideoBgraOutView
        );
        if (FAILED(hr)) return false;
        m_ring_vp_bgra_out_views.push_back(pVideoBgraOutView);

        ID2D1Bitmap1* pVideoBgraSource = nullptr;
        IDXGISurface1* pVideoBgraSurface = nullptr;
        hr = pVideoBgraTex->QueryInterface(
            __uuidof(IDXGISurface1), (void**)&pVideoBgraSurface
        );
        if (FAILED(hr)) return false;
        hr = m_pD2DContext->CreateBitmapFromDxgiSurface(
            pVideoBgraSurface, &sourceBp, &pVideoBgraSource
        );
        pVideoBgraSurface->Release();
        if (FAILED(hr)) return false;
        m_ring_d2d_bgra_video_sources.push_back(pVideoBgraSource);

        ID3D11Texture2D* pCompositeTex = nullptr;
        hr = m_pDevice->CreateTexture2D(&hudDesc, NULL, &pCompositeTex);
        if (FAILED(hr)) return false;
        m_ring_bgra_composite_textures.push_back(pCompositeTex);

        ID3D11VideoProcessorInputView* pCompositeInView = nullptr;
        hr = m_pVideoDevice->CreateVideoProcessorInputView(pCompositeTex, m_pVPEnum, &inDesc, &pCompositeInView);
        if (FAILED(hr)) return false;
        m_ring_vp_in_view_bgra_composites.push_back(pCompositeInView);

        IDXGISurface1* pCompositeSurface = nullptr;
        hr = pCompositeTex->QueryInterface(__uuidof(IDXGISurface1), (void**)&pCompositeSurface);
        if (FAILED(hr)) return false;
        ID2D1Bitmap1* pCompositeD2DTarget = nullptr;
        hr = m_pD2DContext->CreateBitmapFromDxgiSurface(pCompositeSurface, &bp, &pCompositeD2DTarget);
        pCompositeSurface->Release();
        if (FAILED(hr)) return false;
        m_ring_d2d_bgra_composite_targets.push_back(pCompositeD2DTarget);

        // 4. Persistent GPU slot completion query fences (HUD & VP)
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

    if (!m_ring_hud_textures.empty()) {
        RecordInteractionIdentity("RESOURCE_ALLOCATOR", "created", "HUD_Texture_slot0",
                                  m_ring_hud_textures[0], m_pContext);
        RecordInteractionIdentity("RESOURCE_ALLOCATOR", "created", "D2D_Target_slot0",
                                  m_ring_d2d_bitmap_targets[0], m_pContext);
        RecordInteractionIdentity("RESOURCE_ALLOCATOR", "created", "VP_HUD_InputView_slot0",
                                  m_ring_vp_in_view_huds[0], m_pContext);
        RecordInteractionIdentity("RESOURCE_ALLOCATOR", "created", "P010_Output_slot0",
                                  m_ring_nv12_textures[0], m_pContext);
        RecordInteractionIdentity("RESOURCE_ALLOCATOR", "created", "HUD_Query_slot0",
                                  m_ring_hud_queries[0], m_pContext);
        RecordInteractionIdentity("RESOURCE_ALLOCATOR", "created", "VP_Query_slot0",
                                  m_ring_vp_queries[0], m_pContext);
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
        RecordInteractionIdentity("DECODER", "created", "IMFDXGIDeviceManager",
                                  m_pDevMgr, m_pContext);
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
    RecordInteractionIdentity("DECODER", "created", "IMFSourceReader",
                              m_pSourceReader, m_pContext);
    if (m_interaction_decoder_file) {
        fprintf(m_interaction_decoder_file,
                "clip=%u path=%ls dxgi_manager_ptr=0x%p compositor_device_ptr=0x%p immediate_context_ptr=0x%p\n",
                clip_idx, clip.path, (void*)m_pDevMgr, (void*)m_pDevice,
                (void*)m_pContext);
        fflush(m_interaction_decoder_file);
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

            RecordD3D11ContextOperation("MF_ReadSample", m_clip_frames_decoded,
                                        m_pSourceReader, -1);
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
        RecordDecoderDeviceAudit(pVideoTexture, subresource, m_clip_frames_decoded);
        RecordD3D11ContextOperation("Decoder_GetResource", m_clip_frames_decoded,
                                    pVideoTexture, -1);

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
            RecordD3D11ContextOperation("CreateVideoProcessorInputView", m_clip_frames_decoded,
                                        pVideoTexture, -1);
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
    m_diag_indicator_resources_deferred = false;
    if (!indicators || count == 0) return true;

    // The opt-in separate-HUD diagnostics own their D2D/DWrite resources on
    // Device B.  Rebind the shared font cache before constructing widgets so
    // every text format and icon bitmap is created by the B device/context.
    const bool use_separate_hud = m_hud_separate_device &&
        (m_hud_separate_mode == "FULL_HUD" ||
         m_hud_separate_mode == "VP_HUD" ||
         m_hud_separate_mode == "NVENC");
    if (use_separate_hud && m_hud_b_d2d_context && m_hud_b_dwrite_factory) {
        m_font_cache.Init(m_hud_b_dwrite_factory);
        // Any icon bitmaps cached while configuring the ordinary A path are
        // tied to that D2D device.  Discard them before B creates its copies.
        m_icon_cache.Clear();
    }
    ID2D1DeviceContext* indicator_d2d = use_separate_hud ? m_hud_b_d2d_context : m_pD2DContext;
    IDWriteFactory* indicator_dwrite = use_separate_hud ? m_hud_b_dwrite_factory : m_pDWriteFactory;

    for (uint32_t i = 0; i < count; ++i) {
        const auto& desc = indicators[i];
        std::unique_ptr<IndicatorBase> pInd;

        if (desc.type == TELEM_IND_CHART &&
            std::string(desc.key) == "fit_cadence_text") {
            const float raw_alpha = desc.style.chart.fill_alpha;
            const float normalized_alpha = raw_alpha > 1.0f
                ? raw_alpha / 255.0f : raw_alpha;
            AppendCadenceAlphaTrace("C ABI received field value",
                                    raw_alpha, normalized_alpha);
        }

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
                if (std::string(desc.key) == "fit_cadence_text") {
                    const float raw_alpha = desc.style.chart.fill_alpha;
                    const float normalized_alpha = raw_alpha > 1.0f
                        ? raw_alpha / 255.0f : raw_alpha;
                    AppendCadenceAlphaTrace("C++ descriptor copied to ChartIndicator",
                                            raw_alpha, normalized_alpha);
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
            case TELEM_IND_LEAN:
                pInd = std::make_unique<LeanIndicator>(desc, &m_font_cache);
                break;
            default:
                break;
        }

        if (pInd) {
            if (indicator_d2d && indicator_dwrite && !m_d2d_single_thread) {
                RecordD2DThread("CreateDeviceResources", UINT32_MAX);
                pInd->CreateDeviceResources(indicator_d2d, indicator_dwrite);
            } else if (m_d2d_single_thread) {
                m_diag_indicator_resources_deferred = true;
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

void D3D11NvencPipeline::InitDeterminismDiagnostics() {
    m_determinism_diag = false;
    m_determinism_serialized = false;
    m_interaction_stage = InteractionLadderStage();
    m_context_serialize = IsInteractionContextSerializationRequested();
    m_hud_separate_device = IsSeparateHudDeviceRequested();
    m_hud_cross_device = IsSeparateHudCrossDeviceRequested();
    m_hud_separate_mode = SeparateHudMode();
    m_determinism_dir.clear();
    m_interaction_dir.clear();
    m_d2d_reset_state = false;
    m_d2d_fresh_context = false;
    m_d2d_single_thread = false;
    m_d2d_minimal_draw = false;
    m_diag_indicator_resources_deferred = false;
    m_d2d_owner_thread_id = 0;
    m_interaction_worker_thread_id = 0;
    m_d2d_state_trace = TelemD2DStateTrace{};
    ReleaseCopyOutHudTexture();
    SafeRelease(m_diag_info_queue);
    SafeRelease(m_diag_multithread);
    m_diag_multithread_available = false;
    m_diag_multithread_before = FALSE;
    m_diag_multithread_after = FALSE;
    if (m_determinism_file) {
        fclose(m_determinism_file);
        m_determinism_file = nullptr;
    }
    for (FILE** file : {&m_d2d_state_stack_file, &m_d2d_transform_file,
                        &m_d2d_thread_file, &m_d2d_enddraw_file, &m_d2d_debug_file,
                        &m_d2d_target_binding_file, &m_d3d11_debug_file}) {
        if (*file) {
            fclose(*file);
            *file = nullptr;
        }
    }
    for (FILE** file : {&m_interaction_identity_file, &m_interaction_trace_file,
                        &m_interaction_timeline_file, &m_interaction_decoder_file,
                        &m_separate_identity_file, &m_resource_alias_file}) {
        if (*file) {
            fclose(*file);
            *file = nullptr;
        }
    }
    char dir[512] = {};
    DWORD len = GetEnvironmentVariableA("TELEM_NATIVE_DETERMINISM_DIR", dir, (DWORD)sizeof(dir));
    if (len > 0 && len < sizeof(dir)) {
        m_determinism_diag = true;
        m_determinism_dir.assign(dir, len);
    }

    char interaction_dir[512] = {};
    DWORD interaction_len = GetEnvironmentVariableA(
        "TELEM_NATIVE_PIPELINE_INTERACTION_DIR", interaction_dir,
        (DWORD)sizeof(interaction_dir));
    if (interaction_len > 0 && interaction_len < sizeof(interaction_dir)) {
        m_interaction_dir.assign(interaction_dir, interaction_len);
        CreateDirectoryA(m_interaction_dir.c_str(), nullptr);
        auto open_interaction = [&](const char* name, const char* header) {
            std::string path = m_interaction_dir + "\\" + name;
            FILE* file = fopen(path.c_str(), "w");
            if (file && header) {
                fputs(header, file);
                fflush(file);
            }
            return file;
        };
        m_interaction_identity_file = open_interaction(
            "device_context_identity.csv",
            "subsystem,phase,object,pointer,context_ptr,thread_id,adapter_luid_low,adapter_luid_high,vendor_id\n");
        m_interaction_trace_file = open_interaction(
            "d3d11_context_thread_trace.csv",
            "qpc,frame,thread_id,operation,context_ptr,resource_ptr,slot\n");
        m_interaction_timeline_file = open_interaction(
            "first_failure_timeline.csv",
            "qpc,frame,event,hr,thread_id\n");
        m_interaction_decoder_file = open_interaction("decoder_device_audit.txt", nullptr);
        m_separate_identity_file = open_interaction(
            "device_a_b_identity.csv",
            "device,adapter_index,luid_low,luid_high,vendor_id,description,device_ptr,context_ptr,dxgi_device_ptr,d2d_device_ptr,d2d_context_ptr,thread_id\n");
        m_resource_alias_file = open_interaction(
            "resource_alias_audit.csv",
            "frame,hud_texture_ptr,hud_underlying_resource_ptr,decoder_texture_ptr,decoder_queue_texture_ptr,resource_alias\n");
        if (m_interaction_decoder_file) {
            fprintf(m_interaction_decoder_file,
                    "stage=%s\nrequested_stage=%u\ncontext_serialize=%s\n",
                    InteractionStageName(m_interaction_stage), m_interaction_stage,
                    m_context_serialize ? "True" : "False");
            fflush(m_interaction_decoder_file);
        }
    }

    if (!m_determinism_diag) return;
    m_d2d_reset_state = IsD2DResetStateDiagnostic();
    m_d2d_fresh_context = IsFreshD2DContextDiagnostic();
    m_d2d_single_thread = IsD2DSingleThreadDiagnostic();
    m_d2d_minimal_draw = IsD2DMinimalDrawDiagnostic();
    char serialized[8] = {};
    DWORD slen = GetEnvironmentVariableA("TELEM_NATIVE_SERIALIZED", serialized, (DWORD)sizeof(serialized));
    m_determinism_serialized = slen > 0 && slen < sizeof(serialized) && serialized[0] == '1';
    CreateDirectoryA(m_determinism_dir.c_str(), nullptr);
    std::string path = m_determinism_dir + "\\stage_presence.csv";
    m_determinism_file = fopen(path.c_str(), "w");
    if (m_determinism_file) {
        fprintf(m_determinism_file, "frame,stage,present,hr\n");
        fflush(m_determinism_file);
    }
    auto open_diag = [&](const char* name, const char* header) {
        std::string path = m_determinism_dir + "\\" + name;
        FILE* file = fopen(path.c_str(), "w");
        if (file && header) {
            fputs(header, file);
            fflush(file);
        }
        return file;
    };
    m_d2d_state_stack_file = open_diag(
        "state_stack_trace.csv",
        "frame,clip_depth_begin,clip_depth_end,layer_depth_begin,layer_depth_end,BeginDraw_depth_begin,BeginDraw_depth_end,state_stack_leak,thread_id\n");
    m_d2d_transform_file = open_diag(
        "transform_trace.csv",
        "frame,phase,widget,m11,m12,m21,m22,dx,dy,thread_id\n");
    m_d2d_thread_file = open_diag(
        "thread_trace.csv",
        "frame,operation,thread_id,owner_thread_id,thread_mismatch\n");
    m_d2d_enddraw_file = open_diag(
        "enddraw_trace.csv",
        "frame,enddraw_hr,flush_hr,tag1,tag2,thread_id\n");
    m_d2d_target_binding_file = open_diag(
        "target_binding_trace.csv",
        "frame,phase,target_ptr,target_is_null,detach_mode,thread_id\n");
    m_d2d_debug_file = open_diag("d2d_debug_messages.txt", nullptr);
    if (m_d2d_debug_file) {
        fprintf(m_d2d_debug_file,
                "requested=%s\ndebug_level=D2D1_DEBUG_LEVEL_INFORMATION\n",
                IsD2DStateDiagnostic("TELEM_NATIVE_D2D_DEBUG") ? "True" : "False");
        fflush(m_d2d_debug_file);
    }
    m_d3d11_debug_file = open_diag("d3d11_cross_api_debug.txt", nullptr);
    if (m_d3d11_debug_file) {
        fprintf(m_d3d11_debug_file,
                "requested=%s\nmode=%s\ninfo_queue=initializing\n",
                IsD3D11CrossApiDebugDiagnostic() ? "True" : "False",
                D2DTargetDetachMode().c_str());
        fflush(m_d3d11_debug_file);
    }
}

void D3D11NvencPipeline::CloseDeterminismDiagnostics() {
    if (m_determinism_file) {
        fflush(m_determinism_file);
        fclose(m_determinism_file);
        m_determinism_file = nullptr;
    }
    for (FILE** file : {&m_d2d_state_stack_file, &m_d2d_transform_file,
                        &m_d2d_thread_file, &m_d2d_enddraw_file, &m_d2d_debug_file,
                        &m_d2d_target_binding_file, &m_d3d11_debug_file}) {
        if (*file) {
            fflush(*file);
            fclose(*file);
            *file = nullptr;
        }
    }
    for (FILE** file : {&m_interaction_identity_file, &m_interaction_trace_file,
                        &m_interaction_timeline_file, &m_interaction_decoder_file,
                        &m_separate_identity_file, &m_resource_alias_file}) {
        if (*file) {
            fflush(*file);
            fclose(*file);
            *file = nullptr;
        }
    }
    SafeRelease(m_diag_multithread);
}

void D3D11NvencPipeline::RecordInteractionIdentity(const char* subsystem,
                                                   const char* phase,
                                                   const char* object_name,
                                                   void* object_ptr,
                                                   void* context_ptr) {
    if (!m_interaction_identity_file) return;
    fprintf(m_interaction_identity_file, "%s,%s,%s,0x%p,0x%p,%lu,%llu,%llu,0x%04X\n",
            subsystem ? subsystem : "", phase ? phase : "",
            object_name ? object_name : "", object_ptr, context_ptr,
            (unsigned long)GetCurrentThreadId(),
            (unsigned long long)m_adapter_desc.AdapterLuid.LowPart,
            (unsigned long long)m_adapter_desc.AdapterLuid.HighPart,
            (unsigned int)m_adapter_desc.VendorId);
    fflush(m_interaction_identity_file);
}

void D3D11NvencPipeline::RecordD3D11ContextOperation(const char* operation,
                                                    uint32_t frame,
                                                    void* resource_ptr,
                                                    int slot) {
    if (!m_interaction_trace_file || !m_pContext) return;
    LARGE_INTEGER qpc{};
    QueryPerformanceCounter(&qpc);
    fprintf(m_interaction_trace_file, "%lld,%u,%lu,%s,0x%p,0x%p,%d\n",
            (long long)qpc.QuadPart,
            frame == UINT32_MAX ? m_interaction_current_frame : frame,
            (unsigned long)GetCurrentThreadId(), operation ? operation : "",
            (void*)m_pContext, resource_ptr, slot);
    fflush(m_interaction_trace_file);
}

void D3D11NvencPipeline::RecordInteractionTimeline(uint32_t frame,
                                                   const char* event_name,
                                                   HRESULT hr) {
    if (!m_interaction_timeline_file) return;
    LARGE_INTEGER qpc{};
    QueryPerformanceCounter(&qpc);
    fprintf(m_interaction_timeline_file, "%lld,%u,%s,0x%08X,%lu\n",
            (long long)qpc.QuadPart, frame, event_name ? event_name : "",
            (unsigned int)hr, (unsigned long)GetCurrentThreadId());
    fflush(m_interaction_timeline_file);
}

void D3D11NvencPipeline::RecordDecoderDeviceAudit(ID3D11Texture2D* texture,
                                                  UINT subresource,
                                                  uint32_t frame) {
    if (!m_interaction_decoder_file) return;
    ID3D11Device* texture_device = nullptr;
    HRESULT hr = E_POINTER;
    if (texture) {
        texture->GetDevice(&texture_device);
        hr = texture_device ? S_OK : E_FAIL;
    }
    fprintf(m_interaction_decoder_file,
            "frame=%u thread_id=%lu texture_ptr=0x%p subresource=%u texture_device_ptr=0x%p compositor_device_ptr=0x%p device_equal=%s get_device_hr=0x%08X\n",
            frame, (unsigned long)GetCurrentThreadId(), (void*)texture,
            subresource, (void*)texture_device, (void*)m_pDevice,
            texture_device == m_pDevice ? "True" : "False",
            (unsigned int)hr);
    if (texture_device) texture_device->Release();
    fflush(m_interaction_decoder_file);
    if (m_resource_alias_file) {
        ID3D11Texture2D* hud_texture = m_hud_separate_device
            ? m_hud_b_texture
            : (m_ring_hud_textures.empty() ? nullptr : m_ring_hud_textures[0]);
        void* hud_resource = hud_texture;
        bool alias = hud_texture && texture && hud_texture == texture;
        fprintf(m_resource_alias_file, "%u,0x%p,0x%p,0x%p,0x%p,%s\n",
                frame, (void*)hud_texture, hud_resource, (void*)texture,
                (void*)texture, alias ? "True" : "False");
        fflush(m_resource_alias_file);
    }
}

void D3D11NvencPipeline::RecordSeparateDeviceIdentity() {
    if (!m_separate_identity_file || !m_pAdapter || !m_hud_b_device) return;
    IDXGIAdapter1* b_adapter = nullptr;
    DXGI_ADAPTER_DESC b_desc{};
    if (m_hud_b_dxgi_device) {
        m_hud_b_dxgi_device->GetAdapter(reinterpret_cast<IDXGIAdapter**>(&b_adapter));
        if (b_adapter) b_adapter->GetDesc(&b_desc);
    }
    const std::string a_name = AdapterDescriptionUtf8(m_adapter_desc);
    const std::string b_name = AdapterDescriptionUtf8(b_desc);
    fprintf(m_separate_identity_file,
            "DEVICE_A,%u,%llu,%llu,0x%04X,\"%s\",0x%p,0x%p,0x%p,0x%p,0x%p,%lu\n",
            m_adapter_index,
            (unsigned long long)m_adapter_desc.AdapterLuid.LowPart,
            (unsigned long long)m_adapter_desc.AdapterLuid.HighPart,
            (unsigned int)m_adapter_desc.VendorId, a_name.c_str(),
            (void*)m_pDevice, (void*)m_pContext, nullptr,
            (void*)m_pD2DDevice, (void*)m_pD2DContext,
            (unsigned long)GetCurrentThreadId());
    fprintf(m_separate_identity_file,
            "DEVICE_B,%u,%llu,%llu,0x%04X,\"%s\",0x%p,0x%p,0x%p,0x%p,0x%p,%lu\n",
            m_adapter_index,
            (unsigned long long)b_desc.AdapterLuid.LowPart,
            (unsigned long long)b_desc.AdapterLuid.HighPart,
            (unsigned int)b_desc.VendorId, b_name.c_str(),
            (void*)m_hud_b_device, (void*)m_hud_b_context,
            (void*)m_hud_b_dxgi_device, (void*)m_hud_b_d2d_device,
            (void*)m_hud_b_d2d_context,
            (unsigned long)GetCurrentThreadId());
    fflush(m_separate_identity_file);
    if (b_adapter) b_adapter->Release();
}

bool D3D11NvencPipeline::CreateSeparateHudDevice() {
    if (!m_pAdapter) return false;
    SafeRelease(m_hud_b_d2d_context);
    SafeRelease(m_hud_b_d2d_device);
    SafeRelease(m_hud_b_dxgi_device);
    SafeRelease(m_hud_b_context);
    SafeRelease(m_hud_b_device);

    UINT flags = D3D11_CREATE_DEVICE_BGRA_SUPPORT;
    if (m_config.enable_debug_layer) flags |= D3D11_CREATE_DEVICE_DEBUG;
    D3D_FEATURE_LEVEL levels[] = {D3D_FEATURE_LEVEL_11_1, D3D_FEATURE_LEVEL_11_0};
    D3D_FEATURE_LEVEL fl_out{};
    HRESULT hr = D3D11CreateDevice(m_pAdapter, D3D_DRIVER_TYPE_UNKNOWN, nullptr,
                                   flags, levels, 2, D3D11_SDK_VERSION,
                                   &m_hud_b_device, &fl_out, &m_hud_b_context);
    if (FAILED(hr) && (flags & D3D11_CREATE_DEVICE_DEBUG)) {
        flags &= ~D3D11_CREATE_DEVICE_DEBUG;
        hr = D3D11CreateDevice(m_pAdapter, D3D_DRIVER_TYPE_UNKNOWN, nullptr,
                               flags, levels, 2, D3D11_SDK_VERSION,
                               &m_hud_b_device, &fl_out, &m_hud_b_context);
    }
    if (FAILED(hr) || !m_hud_b_device || !m_hud_b_context) return false;

    hr = m_hud_b_device->QueryInterface(__uuidof(IDXGIDevice),
                                        reinterpret_cast<void**>(&m_hud_b_dxgi_device));
    if (FAILED(hr) || !m_hud_b_dxgi_device) return false;
    HMODULE h_d2d = LoadLibraryW(L"d2d1.dll");
    if (!h_d2d) return false;
    PFN_D2D1CreateDevice pfn_create =
        (PFN_D2D1CreateDevice)GetProcAddress(h_d2d, "D2D1CreateDevice");
    if (!pfn_create) return false;
    D2D1_CREATION_PROPERTIES creation{};
    const D2D1_CREATION_PROPERTIES* creation_ptr = nullptr;
    if (m_determinism_diag && IsD2DStateDiagnostic("TELEM_NATIVE_D2D_DEBUG")) {
        creation.threadingMode = D2D1_THREADING_MODE_MULTI_THREADED;
        creation.debugLevel = D2D1_DEBUG_LEVEL_INFORMATION;
        creation.options = D2D1_DEVICE_CONTEXT_OPTIONS_NONE;
        creation_ptr = &creation;
    }
    hr = pfn_create(m_hud_b_dxgi_device, creation_ptr, &m_hud_b_d2d_device);
    if (FAILED(hr) || !m_hud_b_d2d_device) return false;
    hr = m_hud_b_d2d_device->CreateDeviceContext(D2D1_DEVICE_CONTEXT_OPTIONS_NONE,
                                                  &m_hud_b_d2d_context);
    if (FAILED(hr) || !m_hud_b_d2d_context) return false;
    m_hud_b_d2d_context->SetAntialiasMode(D2D1_ANTIALIAS_MODE_PER_PRIMITIVE);
    m_hud_b_d2d_context->SetTextAntialiasMode(D2D1_TEXT_ANTIALIAS_MODE_GRAYSCALE);

    HMODULE h_dw = LoadLibraryW(L"dwrite.dll");
    if (!h_dw) return false;
    PFN_DWriteCreateFactory pfn_dw =
        (PFN_DWriteCreateFactory)GetProcAddress(h_dw, "DWriteCreateFactory");
    if (!pfn_dw) return false;
    hr = pfn_dw(DWRITE_FACTORY_TYPE_SHARED, __uuidof(IDWriteFactory),
                reinterpret_cast<IUnknown**>(&m_hud_b_dwrite_factory));
    if (FAILED(hr) || !m_hud_b_dwrite_factory) return false;
    hr = m_hud_b_dwrite_factory->CreateTextFormat(
        L"Segoe UI", nullptr, DWRITE_FONT_WEIGHT_BOLD, DWRITE_FONT_STYLE_NORMAL,
        DWRITE_FONT_STRETCH_NORMAL, 68.0f, L"en-us", &m_hud_b_fmt);
    if (FAILED(hr) || !m_hud_b_fmt) return false;
    hr = m_hud_b_d2d_context->CreateSolidColorBrush(
        D2D1::ColorF(1.0f, 1.0f, 1.0f, 1.0f), &m_hud_b_brush);
    if (FAILED(hr) || !m_hud_b_brush) return false;
    auto make_fmt = [&](IDWriteTextFormat** out, DWRITE_FONT_WEIGHT weight, float size) {
        return SUCCEEDED(m_hud_b_dwrite_factory->CreateTextFormat(
            L"Segoe UI", nullptr, weight, DWRITE_FONT_STYLE_NORMAL,
            DWRITE_FONT_STRETCH_NORMAL, size, L"en-us", out));
    };
    if (!make_fmt(&m_hud_b_fmt_time, DWRITE_FONT_WEIGHT_BOLD, 68.0f) ||
        !make_fmt(&m_hud_b_fmt_speed_val, DWRITE_FONT_WEIGHT_BOLD, 112.0f) ||
        !make_fmt(&m_hud_b_fmt_speed_unit, DWRITE_FONT_WEIGHT_SEMI_BOLD, 36.0f) ||
        !make_fmt(&m_hud_b_fmt_hr_val, DWRITE_FONT_WEIGHT_BOLD, 112.0f) ||
        !make_fmt(&m_hud_b_fmt_hr_unit, DWRITE_FONT_WEIGHT_SEMI_BOLD, 36.0f) ||
        !make_fmt(&m_hud_b_fmt_label, DWRITE_FONT_WEIGHT_SEMI_BOLD, 26.0f)) {
        return false;
    }
    if (FAILED(m_hud_b_d2d_context->CreateSolidColorBrush(
            D2D1::ColorF(0.75f, 0.82f, 0.90f, 0.90f), &m_hud_b_brush_text_muted)) ||
        FAILED(m_hud_b_d2d_context->CreateSolidColorBrush(
            D2D1::ColorF(0.0f, 0.88f, 1.0f, 1.0f), &m_hud_b_brush_cyan)) ||
        FAILED(m_hud_b_d2d_context->CreateSolidColorBrush(
            D2D1::ColorF(1.0f, 0.32f, 0.32f, 1.0f), &m_hud_b_brush_coral)) ||
        FAILED(m_hud_b_d2d_context->CreateSolidColorBrush(
            D2D1::ColorF(0.04f, 0.06f, 0.10f, 0.68f), &m_hud_b_brush_card_bg)) ||
        FAILED(m_hud_b_d2d_context->CreateSolidColorBrush(
            D2D1::ColorF(0.25f, 0.35f, 0.50f, 0.60f), &m_hud_b_brush_card_border))) {
        return false;
    }
    if (!CreateSeparateHudTexture(m_hud_cross_device)) return false;
    RecordSeparateDeviceIdentity();
    RecordInteractionIdentity("HUD_DEVICE_B", "created", "ID3D11Device",
                              m_hud_b_device, m_hud_b_context);
    RecordInteractionIdentity("HUD_DEVICE_B", "created", "ID3D11DeviceContext",
                              m_hud_b_context, m_hud_b_context);
    RecordInteractionIdentity("HUD_DEVICE_B", "created", "IDXGIDevice",
                              m_hud_b_dxgi_device, m_hud_b_context);
    RecordInteractionIdentity("HUD_DEVICE_B", "created", "ID2D1Device",
                              m_hud_b_d2d_device, m_hud_b_context);
    RecordInteractionIdentity("HUD_DEVICE_B", "created", "ID2D1DeviceContext",
                              m_hud_b_d2d_context, m_hud_b_context);
    return true;
}

bool D3D11NvencPipeline::CreateSeparateHudTexture(bool shared_resource) {
    if (!m_hud_b_device || !m_hud_b_d2d_context) return false;
    SafeRelease(m_hud_b_target);
    SafeRelease(m_hud_b_texture);
    SafeRelease(m_hud_b_staging);
    SafeRelease(m_hud_b_mutex);
    D3D11_TEXTURE2D_DESC desc{};
    desc.Width = m_config.width;
    desc.Height = m_config.height;
    desc.MipLevels = 1;
    desc.ArraySize = 1;
    desc.Format = DXGI_FORMAT_B8G8R8A8_UNORM;
    desc.SampleDesc.Count = 1;
    desc.Usage = D3D11_USAGE_DEFAULT;
    desc.BindFlags = D3D11_BIND_RENDER_TARGET | D3D11_BIND_SHADER_RESOURCE;
    if (shared_resource) {
        desc.MiscFlags = D3D11_RESOURCE_MISC_SHARED_NTHANDLE |
                         D3D11_RESOURCE_MISC_SHARED_KEYEDMUTEX;
    }
    HRESULT hr = m_hud_b_device->CreateTexture2D(&desc, nullptr, &m_hud_b_texture);
    if (FAILED(hr) || !m_hud_b_texture) return false;
    IDXGISurface1* surface = nullptr;
    hr = m_hud_b_texture->QueryInterface(__uuidof(IDXGISurface1),
                                         reinterpret_cast<void**>(&surface));
    if (FAILED(hr) || !surface) return false;
    D2D1_BITMAP_PROPERTIES1 bp{};
    bp.pixelFormat.format = DXGI_FORMAT_B8G8R8A8_UNORM;
    bp.pixelFormat.alphaMode = D2D1_ALPHA_MODE_PREMULTIPLIED;
    bp.dpiX = 96.0f;
    bp.dpiY = 96.0f;
    bp.bitmapOptions = D2D1_BITMAP_OPTIONS_TARGET | D2D1_BITMAP_OPTIONS_CANNOT_DRAW;
    hr = m_hud_b_d2d_context->CreateBitmapFromDxgiSurface(surface, &bp,
                                                            &m_hud_b_target);
    surface->Release();
    if (FAILED(hr) || !m_hud_b_target) return false;
    D3D11_TEXTURE2D_DESC staging = desc;
    staging.Width = (std::min)(96u, desc.Width);
    staging.Height = (std::min)(96u, desc.Height);
    staging.Usage = D3D11_USAGE_STAGING;
    staging.BindFlags = 0;
    staging.CPUAccessFlags = D3D11_CPU_ACCESS_READ;
    staging.MiscFlags = 0;
    hr = m_hud_b_device->CreateTexture2D(&staging, nullptr, &m_hud_b_staging);
    if (FAILED(hr) || !m_hud_b_staging) return false;
    if (shared_resource) {
        hr = m_hud_b_texture->QueryInterface(__uuidof(IDXGIKeyedMutex),
                                             reinterpret_cast<void**>(&m_hud_b_mutex));
        if (FAILED(hr) || !m_hud_b_mutex) return false;
        if (!CreateCrossDeviceHudResource()) return false;
    }
    RecordInteractionIdentity("HUD_DEVICE_B", "created", "HUD_Texture2D",
                              m_hud_b_texture, m_hud_b_context);
    RecordInteractionIdentity("HUD_DEVICE_B", "created", "D2D_Target",
                              m_hud_b_target, m_hud_b_context);
    return true;
}

bool D3D11NvencPipeline::CreateCrossDeviceHudResource() {
    if (!m_hud_b_texture || !m_pDevice) return false;
    if (m_hud_shared_handle) {
        CloseHandle(m_hud_shared_handle);
        m_hud_shared_handle = nullptr;
    }
    SafeRelease(m_hud_a_shared_texture);
    SafeRelease(m_hud_a_mutex);
    SafeRelease(m_hud_a_shared_view);
    SafeRelease(m_hud_a_shared_staging);
    SafeRelease(m_hud_a_shared_query);
    IDXGIResource1* resource = nullptr;
    HRESULT hr = m_hud_b_texture->QueryInterface(__uuidof(IDXGIResource1),
                                                 reinterpret_cast<void**>(&resource));
    if (FAILED(hr) || !resource) return false;
    hr = resource->CreateSharedHandle(nullptr,
                                      DXGI_SHARED_RESOURCE_READ | DXGI_SHARED_RESOURCE_WRITE,
                                      nullptr, &m_hud_shared_handle);
    resource->Release();
    if (FAILED(hr) || !m_hud_shared_handle) return false;
    ID3D11Device1* device1 = nullptr;
    hr = m_pDevice->QueryInterface(__uuidof(ID3D11Device1),
                                   reinterpret_cast<void**>(&device1));
    if (FAILED(hr) || !device1) return false;
    hr = device1->OpenSharedResource1(m_hud_shared_handle,
                                      __uuidof(ID3D11Texture2D),
                                      reinterpret_cast<void**>(&m_hud_a_shared_texture));
    device1->Release();
    if (FAILED(hr) || !m_hud_a_shared_texture) return false;
    hr = m_hud_a_shared_texture->QueryInterface(__uuidof(IDXGIKeyedMutex),
                                                reinterpret_cast<void**>(&m_hud_a_mutex));
    if (FAILED(hr) || !m_hud_a_mutex) return false;
    if (m_pVideoDevice && m_pVPEnum) {
        D3D11_VIDEO_PROCESSOR_INPUT_VIEW_DESC view_desc{};
        view_desc.ViewDimension = D3D11_VPIV_DIMENSION_TEXTURE2D;
        hr = m_pVideoDevice->CreateVideoProcessorInputView(
            m_hud_a_shared_texture, m_pVPEnum, &view_desc, &m_hud_a_shared_view);
        if (FAILED(hr) || !m_hud_a_shared_view) return false;
    }
    D3D11_TEXTURE2D_DESC desc{};
    m_hud_a_shared_texture->GetDesc(&desc);
    desc.Width = (std::min)(96u, desc.Width);
    desc.Height = (std::min)(96u, desc.Height);
    desc.Usage = D3D11_USAGE_STAGING;
    desc.BindFlags = 0;
    desc.CPUAccessFlags = D3D11_CPU_ACCESS_READ;
    desc.MiscFlags = 0;
    hr = m_pDevice->CreateTexture2D(&desc, nullptr, &m_hud_a_shared_staging);
    if (FAILED(hr) || !m_hud_a_shared_staging) return false;
    D3D11_QUERY_DESC query_desc{};
    query_desc.Query = D3D11_QUERY_EVENT;
    hr = m_pDevice->CreateQuery(&query_desc, &m_hud_a_shared_query);
    if (FAILED(hr) || !m_hud_a_shared_query) return false;
    if (m_interaction_dir.size()) {
        std::string path = m_interaction_dir + "\\shared_resource_caps.txt";
        FILE* file = fopen(path.c_str(), "w");
        if (file) {
            fprintf(file, "create_shared_handle_hr=0x%08X\nopen_shared_resource1_hr=0x%08X\n",
                    (unsigned int)S_OK, (unsigned int)S_OK);
            fprintf(file, "keyed_mutex=available\nopened_texture_ptr=0x%p\n",
                    (void*)m_hud_a_shared_texture);
            fclose(file);
        }
    }
    RecordInteractionIdentity("HUD_CROSS_DEVICE", "opened", "Shared_HUD_Texture_A",
                              m_hud_a_shared_texture, m_pContext);
    RecordInteractionIdentity("HUD_CROSS_DEVICE", "opened", "IDXGIKeyedMutex_A",
                              m_hud_a_mutex, m_pContext);
    return true;
}

bool D3D11NvencPipeline::WaitSeparateContextEvent(ID3D11DeviceContext* context,
                                                  ID3D11Device* device,
                                                  const char* label,
                                                  uint32_t frame) {
    if (!context || !device) return false;
    D3D11_QUERY_DESC desc{};
    desc.Query = D3D11_QUERY_EVENT;
    ID3D11Query* query = nullptr;
    HRESULT hr = device->CreateQuery(&desc, &query);
    if (FAILED(hr) || !query) {
        RecordInteractionTimeline(frame, label, hr);
        return false;
    }
    context->End(query);
    context->Flush();
    const double event_t0 = TelemHudProfile::NowSeconds();
    BOOL done = FALSE;
    while (!done) {
        hr = context->GetData(query, &done, sizeof(done), 0);
        if (FAILED(hr)) break;
        if (!done) YieldProcessor();
    }
    const double event_ms = (TelemHudProfile::NowSeconds() - event_t0) * 1000.0;
    TelemHudProfile::Record("wait", "event_wait", label ? label : "event", event_ms);
    if (label && (::strstr(label, "full_hud") || ::strstr(label, "hud_complete"))) {
        TelemHudProfile::Record("wait", "device_b_completion_wait", label, event_ms);
    }
    query->Release();
    RecordInteractionTimeline(frame, label, hr);
    return SUCCEEDED(hr) && done == TRUE;
}

bool D3D11NvencPipeline::RenderSeparateHudMarker(uint32_t frame) {
    if (!m_hud_b_d2d_context || !m_hud_b_target || !m_hud_b_brush) return false;
    const double acquire_t0 = TelemHudProfile::NowSeconds();
    HRESULT acquire_hr = m_hud_b_mutex ? m_hud_b_mutex->AcquireSync(0, INFINITE) : S_OK;
    TelemHudProfile::Record("wait", "keyed_mutex_acquire_device_b", "marker",
                            (TelemHudProfile::NowSeconds() - acquire_t0) * 1000.0);
    if (FAILED(acquire_hr)) return false;
    m_hud_b_d2d_context->SetTarget(m_hud_b_target);
    m_hud_b_d2d_context->BeginDraw();
    m_hud_b_d2d_context->Clear(D2D1::ColorF(0.0f, 0.0f, 0.0f, 0.0f));
    D2D1_RECT_F marker = D2D1::RectF(0.0f, 0.0f, 96.0f, 96.0f);
    m_hud_b_d2d_context->FillRectangle(&marker, m_hud_b_brush);
    wchar_t frame_text[64] = {};
    swprintf_s(frame_text, L"FRAME %u", frame);
    D2D1_RECT_F text_rect = D2D1::RectF(120.0f, 40.0f, 1200.0f, 160.0f);
    m_hud_b_d2d_context->DrawText(frame_text, (UINT32)wcslen(frame_text),
                                  m_hud_b_fmt, &text_rect, m_hud_b_brush);
    D2D1_TAG tag1 = 0, tag2 = 0;
    HRESULT hr_flush = m_hud_b_d2d_context->Flush(&tag1, &tag2);
    HRESULT hr_end = m_hud_b_d2d_context->EndDraw(&tag1, &tag2);
    m_hud_b_d2d_context->SetTarget(nullptr);
    m_hud_b_context->Flush();
    bool done = SUCCEEDED(hr_flush) && SUCCEEDED(hr_end) &&
                WaitSeparateContextEvent(m_hud_b_context, m_hud_b_device,
                                         "device_b_hud_complete", frame);
    if (m_hud_b_mutex) {
        const double release_t0 = TelemHudProfile::NowSeconds();
        HRESULT release_hr = m_hud_b_mutex->ReleaseSync(1);
        TelemHudProfile::Record("wait", "keyed_mutex_release_device_b", "marker",
                                (TelemHudProfile::NowSeconds() - release_t0) * 1000.0);
        done = done && SUCCEEDED(release_hr);
    }
    RecordInteractionTimeline(frame, done ? "HUD_DEVICE_B" : "HUD_DEVICE_B_FAIL",
                              done ? S_OK : E_FAIL);
    return done;
}

bool D3D11NvencPipeline::ReadbackSeparateHudMarker() {
    if (!m_hud_b_context || !m_hud_b_device || !m_hud_b_texture || !m_hud_b_staging) return false;
    D3D11_BOX box{0, 0, 0,
                  (std::min)(96u, m_config.width),
                  (std::min)(96u, m_config.height), 1};
    m_hud_b_context->CopySubresourceRegion(m_hud_b_staging, 0, 0, 0, 0,
                                           m_hud_b_texture, 0, &box);
    if (!WaitSeparateContextEvent(m_hud_b_context, m_hud_b_device,
                                  "device_b_readback_complete", m_interaction_current_frame)) {
        return false;
    }
    D3D11_MAPPED_SUBRESOURCE mapped{};
    HRESULT hr = m_hud_b_context->Map(m_hud_b_staging, 0, D3D11_MAP_READ, 0, &mapped);
    if (FAILED(hr)) return false;
    uint32_t hits = 0;
    for (uint32_t y = 0; y < (std::min)(96u, m_config.height); ++y) {
        const uint8_t* row = static_cast<const uint8_t*>(mapped.pData) + y * mapped.RowPitch;
        for (uint32_t x = 0; x < (std::min)(96u, m_config.width); ++x) {
            const uint8_t* px = row + x * 4;
            if (px[0] > 220 && px[1] > 220 && px[2] > 220 && px[3] > 200) ++hits;
        }
    }
    m_hud_b_context->Unmap(m_hud_b_staging, 0);
    return hits >= 128u;
}

bool D3D11NvencPipeline::RenderSeparateHudFullFrame(const TelemFrameState& state,
                                                    uint32_t frame) {
    if (!m_hud_b_d2d_context || !m_hud_b_target || !m_hud_b_texture) return false;
    const double hud_total_t0 = TelemHudProfile::NowSeconds();
    TelemHudProfile::Timeline(frame, "HUD begin");
    const double acquire_t0 = TelemHudProfile::NowSeconds();
    HRESULT acquire_hr = m_hud_b_mutex ? m_hud_b_mutex->AcquireSync(0, INFINITE) : S_OK;
    TelemHudProfile::Record("wait", "keyed_mutex_acquire_device_b", "full_hud",
                            (TelemHudProfile::NowSeconds() - acquire_t0) * 1000.0);
    if (FAILED(acquire_hr)) return false;

    // RenderHud is the canonical widget compositor.  Temporarily redirect its
    // context, target pool and legacy fallback resources to B; no A resource
    // is written or aliased by this path.
    ID2D1DeviceContext* saved_d2d = m_pD2DContext;
    IDWriteFactory* saved_dwrite = m_pDWriteFactory;
    auto saved_hud_textures = std::move(m_ring_hud_textures);
    auto saved_hud_targets = std::move(m_ring_d2d_bitmap_targets);
    IDWriteTextFormat* saved_fmt_time = m_fmt_time;
    IDWriteTextFormat* saved_fmt_speed_val = m_fmt_speed_val;
    IDWriteTextFormat* saved_fmt_speed_unit = m_fmt_speed_unit;
    IDWriteTextFormat* saved_fmt_hr_val = m_fmt_hr_val;
    IDWriteTextFormat* saved_fmt_hr_unit = m_fmt_hr_unit;
    IDWriteTextFormat* saved_fmt_label = m_fmt_label;
    ID2D1SolidColorBrush* saved_brush_white = m_brush_white;
    ID2D1SolidColorBrush* saved_brush_text_muted = m_brush_text_muted;
    ID2D1SolidColorBrush* saved_brush_cyan = m_brush_cyan;
    ID2D1SolidColorBrush* saved_brush_coral = m_brush_coral;
    ID2D1SolidColorBrush* saved_brush_card_bg = m_brush_card_bg;
    ID2D1SolidColorBrush* saved_brush_card_border = m_brush_card_border;

    m_pD2DContext = m_hud_b_d2d_context;
    m_pDWriteFactory = m_hud_b_dwrite_factory;
    m_ring_hud_textures.push_back(m_hud_b_texture);
    m_ring_d2d_bitmap_targets.push_back(m_hud_b_target);
    m_fmt_time = m_hud_b_fmt_time;
    m_fmt_speed_val = m_hud_b_fmt_speed_val;
    m_fmt_speed_unit = m_hud_b_fmt_speed_unit;
    m_fmt_hr_val = m_hud_b_fmt_hr_val;
    m_fmt_hr_unit = m_hud_b_fmt_hr_unit;
    m_fmt_label = m_hud_b_fmt_label;
    m_brush_white = m_hud_b_brush;
    m_brush_text_muted = m_hud_b_brush_text_muted;
    m_brush_cyan = m_hud_b_brush_cyan;
    m_brush_coral = m_hud_b_brush_coral;
    m_brush_card_bg = m_hud_b_brush_card_bg;
    m_brush_card_border = m_hud_b_brush_card_border;
    m_rendering_separate_hud = true;
    HRESULT hr = RenderHud(state, 0);
    TelemHudProfile::Timeline(frame, "HUD render returned");
    bool done = SUCCEEDED(hr) &&
        WaitSeparateContextEvent(m_hud_b_context, m_hud_b_device,
                                 "device_b_full_hud_complete", frame);
    TelemHudProfile::Timeline(frame, "completion wait");
    m_rendering_separate_hud = false;

    m_pD2DContext = saved_d2d;
    m_pDWriteFactory = saved_dwrite;
    m_ring_hud_textures = std::move(saved_hud_textures);
    m_ring_d2d_bitmap_targets = std::move(saved_hud_targets);
    m_fmt_time = saved_fmt_time;
    m_fmt_speed_val = saved_fmt_speed_val;
    m_fmt_speed_unit = saved_fmt_speed_unit;
    m_fmt_hr_val = saved_fmt_hr_val;
    m_fmt_hr_unit = saved_fmt_hr_unit;
    m_fmt_label = saved_fmt_label;
    m_brush_white = saved_brush_white;
    m_brush_text_muted = saved_brush_text_muted;
    m_brush_cyan = saved_brush_cyan;
    m_brush_coral = saved_brush_coral;
    m_brush_card_bg = saved_brush_card_bg;
    m_brush_card_border = saved_brush_card_border;
    if (m_hud_b_mutex) {
        const double release_t0 = TelemHudProfile::NowSeconds();
        HRESULT release_hr = m_hud_b_mutex->ReleaseSync(1);
        TelemHudProfile::Record("wait", "keyed_mutex_release_device_b", "full_hud",
                                (TelemHudProfile::NowSeconds() - release_t0) * 1000.0);
        done = done && SUCCEEDED(release_hr);
    }
    TelemHudProfile::Timeline(frame, "ReleaseSync");
    TelemHudProfile::Record("hud", "total", "full", (TelemHudProfile::NowSeconds() - hud_total_t0) * 1000.0);
    RecordInteractionTimeline(frame, done ? "HUD_DEVICE_B_FULL" : "HUD_DEVICE_B_FULL_FAIL",
                               done ? S_OK : FAILED(hr) ? hr : E_FAIL);
    return done;
}

bool D3D11NvencPipeline::RunSeparateHudFullFrames(uint32_t start_frame,
                                                  uint32_t frame_count) {
    bool failed = false;
    uint32_t completed = 0;
    for (uint32_t i = 0; i < frame_count; ++i) {
        const uint32_t frame = start_frame + i;
        m_interaction_current_frame = frame;
        int64_t pts = 0;
        uint32_t flags = 0;
        ID3D11VideoProcessorInputView* view = AcquireDecoderFrame(pts, flags);
        if (!view) {
            failed = true;
            break;
        }
        TelemFrameState state{};
        if (frame < m_telemetry_table.size()) state = m_telemetry_table[frame];
        else if (!m_telemetry_table.empty()) state = m_telemetry_table.back();
        state.frame_index = frame;
        const bool rendered = RenderSeparateHudFullFrame(state, frame);
        const bool present = rendered && ReadbackSeparateHudMarker();
        RecordDeterminismStage(frame, "HUD_DEVICE_B_FULL", present, present ? S_OK : E_FAIL);
        if (!present) {
            failed = true;
            break;
        }
        ++completed;
        std::lock_guard<std::mutex> lock(m_progress_mutex);
        m_progress.completed_frames = completed;
        m_progress.total_frames = frame_count;
    }
    CloseDecoder();
    {
        std::lock_guard<std::mutex> lock(m_progress_mutex);
        m_progress.completed_frames = completed;
        m_progress.total_frames = frame_count;
        m_progress.is_active = 0;
        m_progress.is_finished = 1;
        m_progress.error_code = failed ? -10 : 0;
        strcpy_s(m_progress.error_message, failed ? "Device B full HUD stage failed" : "");
    }
    RecordInteractionTimeline(start_frame + completed, "ladder_end", failed ? E_FAIL : S_OK);
    m_is_active = false;
    m_is_finished = true;
    return !failed && completed == frame_count;
}

bool D3D11NvencPipeline::RunSeparateVpHudFrames(uint32_t start_frame,
                                                uint32_t frame_count) {
    if (!m_hud_b_mutex || !m_hud_a_mutex || !m_hud_a_shared_view ||
        m_ring_vp_in_view_huds.empty()) return false;
    bool failed = false;
    uint32_t completed = 0;
    for (uint32_t i = 0; i < frame_count; ++i) {
        const uint32_t frame = start_frame + i;
        m_interaction_current_frame = frame;
        int64_t pts = 0;
        uint32_t flags = 0;
        ID3D11VideoProcessorInputView* video_view = AcquireDecoderFrame(pts, flags);
        if (!video_view) {
            failed = true;
            break;
        }
        TelemFrameState state{};
        if (frame < m_telemetry_table.size()) state = m_telemetry_table[frame];
        else if (!m_telemetry_table.empty()) state = m_telemetry_table.back();
        state.frame_index = frame;
        const double consume_t0 = TelemHudProfile::NowSeconds();
        HRESULT consume_hr = S_OK;
        if (!RenderSeparateHudFullFrame(state, frame)) {
            consume_hr = E_FAIL;
        } else {
            consume_hr = m_hud_a_mutex->AcquireSync(1, INFINITE);
        }
        TelemHudProfile::Record("wait", "device_a_consume_wait", "separate_vp",
                                (TelemHudProfile::NowSeconds() - consume_t0) * 1000.0);
        if (FAILED(consume_hr)) {
            failed = true;
            break;
        }
        const int slot = (int)(frame % m_config.ring_size);
        if (slot >= (int)m_ring_vp_in_view_huds.size() ||
            slot >= (int)m_ring_vp_out_views.size() ||
            slot >= (int)m_ring_nv12_textures.size()) {
            m_hud_a_mutex->ReleaseSync(0);
            failed = true;
            break;
        }
        ID3D11VideoProcessorInputView* saved_view = m_ring_vp_in_view_huds[slot];
        m_ring_vp_in_view_huds[slot] = m_hud_a_shared_view;
        bool vp_ok = Composite(video_view, slot, true);
        m_ring_vp_in_view_huds[slot] = saved_view;
        if (vp_ok && slot < (int)m_ring_vp_queries.size() && m_ring_vp_queries[slot]) {
            m_pContext->End(m_ring_vp_queries[slot]);
            m_pContext->Flush();
            BOOL done = FALSE;
            while (!done) {
                HRESULT qhr = m_pContext->GetData(m_ring_vp_queries[slot], &done,
                                                  sizeof(done), 0);
                if (FAILED(qhr)) {
                    vp_ok = false;
                    break;
                }
                if (!done) YieldProcessor();
            }
        }
        const bool present = vp_ok && ReadbackHudMarker(m_ring_nv12_textures[slot], true);
        const double consume_release_t0 = TelemHudProfile::NowSeconds();
        m_hud_a_mutex->ReleaseSync(0);
        TelemHudProfile::Record("wait", "device_a_consume_release", "separate_vp",
                                (TelemHudProfile::NowSeconds() - consume_release_t0) * 1000.0);
        RecordDeterminismStage(frame, "HUD_AFTER_VP", present, present ? S_OK : E_FAIL);
        RecordDeterminismStage(frame, "HUD_BEFORE_NVENC", present, present ? S_OK : E_FAIL);
        if (!present) {
            failed = true;
            break;
        }
        ++completed;
        std::lock_guard<std::mutex> lock(m_progress_mutex);
        m_progress.completed_frames = completed;
        m_progress.total_frames = frame_count;
    }
    CloseDecoder();
    {
        std::lock_guard<std::mutex> lock(m_progress_mutex);
        m_progress.completed_frames = completed;
        m_progress.total_frames = frame_count;
        m_progress.is_active = 0;
        m_progress.is_finished = 1;
        m_progress.error_code = failed ? -10 : 0;
        strcpy_s(m_progress.error_message, failed ? "Device A VP HUD stage failed" : "");
    }
    RecordInteractionTimeline(start_frame + completed, "ladder_end", failed ? E_FAIL : S_OK);
    m_is_active = false;
    m_is_finished = true;
    return !failed && completed == frame_count;
}

bool D3D11NvencPipeline::RunSeparateHudMarkerFrames(uint32_t start_frame,
                                                    uint32_t frame_count) {
    bool failed = false;
    uint32_t completed = 0;
    for (uint32_t i = 0; i < frame_count; ++i) {
        uint32_t frame = start_frame + i;
        m_interaction_current_frame = frame;
        int64_t pts = 0;
        uint32_t flags = 0;
        RecordInteractionTimeline(frame, "decode_start", S_OK);
        ID3D11VideoProcessorInputView* view = AcquireDecoderFrame(pts, flags);
        RecordInteractionTimeline(frame, "decode_end", view ? S_OK : E_FAIL);
        if (!view || !RenderSeparateHudMarker(frame)) {
            failed = true;
            break;
        }
        bool present = ReadbackSeparateHudMarker();
        RecordDeterminismStage(frame, "HUD_DEVICE_B", present, present ? S_OK : E_FAIL);
        RecordInteractionTimeline(frame, present ? "HUD_DEVICE_B_READBACK" : "HUD_DEVICE_B_MISSING",
                                  present ? S_OK : E_FAIL);
        if (!present) {
            failed = true;
            break;
        }
        ++completed;
        std::lock_guard<std::mutex> lock(m_progress_mutex);
        m_progress.completed_frames = completed;
        m_progress.total_frames = frame_count;
    }
    CloseDecoder();
    {
        std::lock_guard<std::mutex> lock(m_progress_mutex);
        m_progress.completed_frames = completed;
        m_progress.total_frames = frame_count;
        m_progress.is_active = 0;
        m_progress.is_finished = 1;
        m_progress.error_code = failed ? -10 : 0;
        strcpy_s(m_progress.error_message, failed ? "separate HUD device stage failed" : "");
    }
    RecordInteractionTimeline(start_frame + completed, "ladder_end",
                              failed ? E_FAIL : S_OK);
    m_is_active = false;
    m_is_finished = true;
    return !failed && completed == frame_count;
}

bool D3D11NvencPipeline::RunSharedResourceCapabilityFrames(uint32_t start_frame,
                                                           uint32_t frame_count) {
    if (!m_hud_b_mutex || !m_hud_a_mutex || !m_hud_a_shared_texture ||
        !m_hud_a_shared_staging) return false;
    bool failed = false;
    uint32_t completed = 0;
    for (uint32_t i = 0; i < frame_count; ++i) {
        uint32_t frame = start_frame + i;
        m_interaction_current_frame = frame;
        int64_t pts = 0;
        uint32_t flags = 0;
        ID3D11VideoProcessorInputView* view = AcquireDecoderFrame(pts, flags);
        if (!view || !RenderSeparateHudMarker(frame)) {
            failed = true;
            break;
        }
        if (FAILED(m_hud_a_mutex->AcquireSync(1, INFINITE))) {
            failed = true;
            break;
        }
        D3D11_BOX box{0, 0, 0,
                      (std::min)(96u, m_config.width),
                      (std::min)(96u, m_config.height), 1};
        m_pContext->CopySubresourceRegion(m_hud_a_shared_staging, 0, 0, 0, 0,
                                          m_hud_a_shared_texture, 0, &box);
        bool copied = WaitSeparateContextEvent(m_pContext, m_pDevice,
                                               "device_a_shared_copy_complete", frame);
        D3D11_MAPPED_SUBRESOURCE mapped{};
        bool present = false;
        if (copied && SUCCEEDED(m_pContext->Map(m_hud_a_shared_staging, 0,
                                                D3D11_MAP_READ, 0, &mapped))) {
            uint32_t hits = 0;
            for (uint32_t y = 0; y < (std::min)(96u, m_config.height); ++y) {
                const uint8_t* row = static_cast<const uint8_t*>(mapped.pData) + y * mapped.RowPitch;
                for (uint32_t x = 0; x < (std::min)(96u, m_config.width); ++x) {
                    const uint8_t* px = row + x * 4;
                    if (px[0] > 220 && px[1] > 220 && px[2] > 220 && px[3] > 200) ++hits;
                }
            }
            m_pContext->Unmap(m_hud_a_shared_staging, 0);
            present = hits >= 128u;
        }
        m_hud_a_mutex->ReleaseSync(0);
        if (!present) {
            failed = true;
            break;
        }
        ++completed;
        std::lock_guard<std::mutex> lock(m_progress_mutex);
        m_progress.completed_frames = completed;
        m_progress.total_frames = frame_count;
    }
    CloseDecoder();
    {
        std::lock_guard<std::mutex> lock(m_progress_mutex);
        m_progress.completed_frames = completed;
        m_progress.total_frames = frame_count;
        m_progress.is_active = 0;
        m_progress.is_finished = 1;
        m_progress.error_code = failed ? -10 : 0;
        strcpy_s(m_progress.error_message, failed ? "shared GPU resource capability failed" : "");
    }
    RecordInteractionTimeline(start_frame + completed, "ladder_end",
                              failed ? E_FAIL : S_OK);
    m_is_active = false;
    m_is_finished = true;
    return !failed && completed == frame_count;
}

bool D3D11NvencPipeline::CreateLadderHudResources() {
    if (!m_pDevice || !m_pD2DContext) return false;
    D3D11_TEXTURE2D_DESC desc{};
    desc.Width = m_config.width;
    desc.Height = m_config.height;
    desc.MipLevels = 1;
    desc.ArraySize = 1;
    desc.Format = DXGI_FORMAT_B8G8R8A8_UNORM;
    desc.SampleDesc.Count = 1;
    desc.Usage = D3D11_USAGE_DEFAULT;
    desc.BindFlags = D3D11_BIND_RENDER_TARGET | D3D11_BIND_SHADER_RESOURCE;
    ID3D11Texture2D* texture = nullptr;
    HRESULT hr = m_pDevice->CreateTexture2D(&desc, nullptr, &texture);
    if (FAILED(hr) || !texture) return false;
    IDXGISurface1* surface = nullptr;
    hr = texture->QueryInterface(__uuidof(IDXGISurface1), (void**)&surface);
    if (FAILED(hr) || !surface) {
        SafeRelease(texture);
        return false;
    }
    D2D1_BITMAP_PROPERTIES1 bp{};
    bp.pixelFormat.format = DXGI_FORMAT_B8G8R8A8_UNORM;
    bp.pixelFormat.alphaMode = D2D1_ALPHA_MODE_PREMULTIPLIED;
    bp.dpiX = 96.0f;
    bp.dpiY = 96.0f;
    bp.bitmapOptions = D2D1_BITMAP_OPTIONS_TARGET | D2D1_BITMAP_OPTIONS_CANNOT_DRAW;
    ID2D1Bitmap1* target = nullptr;
    hr = m_pD2DContext->CreateBitmapFromDxgiSurface(surface, &bp, &target);
    surface->Release();
    if (FAILED(hr) || !target) {
        SafeRelease(texture);
        return false;
    }
    m_ring_hud_textures.push_back(texture);
    m_ring_d2d_bitmap_targets.push_back(target);
    RecordInteractionIdentity("HUD/D2D", "ladder_resource_create", "ID3D11Texture2D", texture, m_pContext);
    RecordInteractionIdentity("HUD/D2D", "ladder_resource_create", "ID2D1Bitmap1", target, m_pContext);
    return true;
}

void D3D11NvencPipeline::RunInteractionLadderFrames(std::wstring output_path,
                                                    uint32_t start_frame,
                                                    uint32_t frame_count,
                                                    bool include_hud) {
    (void)output_path;
    const uint32_t stage = m_interaction_stage;
    m_interaction_worker_thread_id = GetCurrentThreadId();
    RecordInteractionTimeline(start_frame, "ladder_start", S_OK);
    if (m_hud_separate_device) {
        if (m_hud_separate_mode == "SHARED_CAP") {
            RunSharedResourceCapabilityFrames(start_frame, frame_count);
        } else if (m_hud_separate_mode == "FULL_HUD") {
            RunSeparateHudFullFrames(start_frame, frame_count);
        } else if (m_hud_separate_mode == "VP_HUD") {
            RunSeparateVpHudFrames(start_frame, frame_count);
        } else {
            RunSeparateHudMarkerFrames(start_frame, frame_count);
        }
        return;
    }
    if (m_interaction_decoder_file) {
        fprintf(m_interaction_decoder_file,
                "device_ptr=0x%p context_ptr=0x%p dxgi_device_ptr=0x%p d2d_device_ptr=0x%p d2d_context_ptr=0x%p video_device_ptr=0x%p video_context_ptr=0x%p worker_thread_id=%lu\n",
                (void*)m_pDevice, (void*)m_pContext, (void*)m_pAdapter,
                (void*)m_pD2DDevice, (void*)m_pD2DContext,
                (void*)m_pVideoDevice, (void*)m_pVideoContext,
                (unsigned long)m_interaction_worker_thread_id);
        fflush(m_interaction_decoder_file);
    }

    bool failed = false;
    uint32_t completed = 0;
    const bool needs_decode = stage >= 3;
    const bool needs_vp = stage >= 4;
    const bool uses_hud_vp = stage >= 5;
    for (uint32_t i = 0; i < frame_count; ++i) {
        uint32_t frame = start_frame + i;
        m_interaction_current_frame = frame;
        int64_t pts = 0;
        uint32_t flags = 0;
        ID3D11VideoProcessorInputView* video_view = nullptr;
        if (needs_decode) {
            RecordInteractionTimeline(frame, "decode_start", S_OK);
            video_view = AcquireDecoderFrame(pts, flags);
            RecordInteractionTimeline(frame, "decode_end", video_view ? S_OK : E_FAIL);
            if (!video_view) {
                failed = true;
                break;
            }
        }

        if (m_context_serialize && needs_decode) {
            // Strict diagnostic mode also waits for the immediate-context
            // queue after MF/D3D11 decoder work, before D2D starts writing a
            // separate HUD resource.  The mutex below cannot serialize an
            // internal Media Foundation worker, whereas this EVENT fence can
            // prove completion of commands already submitted to this queue.
            D3D11_QUERY_DESC idle_desc{};
            idle_desc.Query = D3D11_QUERY_EVENT;
            ID3D11Query* idle_query = nullptr;
            HRESULT idle_hr = m_pDevice->CreateQuery(&idle_desc, &idle_query);
            if (SUCCEEDED(idle_hr) && idle_query) {
                RecordD3D11ContextOperation("End_query_decoder_idle", frame, idle_query, -1);
                m_pContext->End(idle_query);
                RecordD3D11ContextOperation("Flush_decoder_idle", frame, nullptr, -1);
                m_pContext->Flush();
                BOOL idle_done = FALSE;
                while (!idle_done) {
                    HRESULT qhr = m_pContext->GetData(idle_query, &idle_done,
                                                      sizeof(idle_done), 0);
                    RecordD3D11ContextOperation("GetData_decoder_idle", frame,
                                                idle_query, -1);
                    if (FAILED(qhr)) {
                        idle_hr = qhr;
                        break;
                    }
                    if (!idle_done) YieldProcessor();
                }
                idle_query->Release();
            }
            RecordInteractionTimeline(frame, "strict_decoder_idle",
                                       SUCCEEDED(idle_hr) ? S_OK : idle_hr);
            if (FAILED(idle_hr)) {
                failed = true;
                break;
            }
        }

        int slot = m_ring_hud_textures.empty() ? 0 : (int)(frame % m_ring_hud_textures.size());
        TelemFrameState state{};
        state.frame_index = frame;
        bool hud_ok = true;
        if (include_hud) {
            RecordInteractionTimeline(frame, "HUD_BeginDraw", S_OK);
            hud_ok = SUCCEEDED(RenderHud(state, slot));
            RecordInteractionTimeline(frame, "HUD_EndDraw", m_last_end_draw_hr);
            RecordInteractionTimeline(frame, "HUD_Flush", m_last_d2d_flush_hr);
            RecordD3D11ContextOperation("D2D_Flush_after_EndDraw", frame,
                                         m_ring_hud_textures.empty() ? nullptr : m_ring_hud_textures[slot], slot);
            bool present = !m_ring_hud_textures.empty() &&
                          ReadbackHudMarker(m_ring_hud_textures[slot], false);
            RecordInteractionTimeline(frame, present ? "HUD_readback_present" : "HUD_readback_missing",
                                       present ? S_OK : E_FAIL);
            RecordDeterminismStage(frame, "HUD_AFTER_D2D", present, hud_ok ? S_OK : E_FAIL);
            if (!hud_ok || !present) failed = true;
        }

        if (needs_vp) {
            bool vp_ok = false;
            if (stage == 4) {
                RecordInteractionTimeline(frame, "VPBlt_background", S_OK);
                vp_ok = CompositeVideoToBgra(video_view, slot);
            } else if (uses_hud_vp) {
                RecordInteractionTimeline(frame, "VPBlt_hud", S_OK);
                vp_ok = Composite(video_view, slot, true);
                if (slot < (int)m_ring_vp_queries.size() && m_ring_vp_queries[slot]) {
                    RecordD3D11ContextOperation("End_query_VP", frame, m_ring_vp_queries[slot], slot);
                    m_pContext->End(m_ring_vp_queries[slot]);
                    RecordD3D11ContextOperation("Flush_VP", frame, nullptr, slot);
                    m_pContext->Flush();
                    BOOL done = FALSE;
                    while (!done) {
                        HRESULT qhr = m_pContext->GetData(m_ring_vp_queries[slot], &done,
                                                         sizeof(done), 0);
                        RecordD3D11ContextOperation("GetData_VP", frame,
                                                     m_ring_vp_queries[slot], slot);
                        if (FAILED(qhr)) { vp_ok = false; break; }
                        if (!done) YieldProcessor();
                    }
                }
            }
            RecordInteractionTimeline(frame, "VP_complete", vp_ok ? S_OK : E_FAIL);
            if (!vp_ok) failed = true;
            if (uses_hud_vp) {
                bool vp_present = ReadbackHudMarker(m_ring_nv12_textures[slot], true);
                RecordDeterminismStage(frame, "HUD_AFTER_VP", vp_present,
                                       vp_ok ? S_OK : E_FAIL);
                RecordDeterminismStage(frame, "HUD_BEFORE_NVENC", vp_present,
                                       vp_ok ? S_OK : E_FAIL);
                if (!vp_present) failed = true;
            }
        }
        if (m_context_serialize) {
            // All explicit D3D calls in this ladder execute on this worker;
            // the lock is the diagnostic serialization boundary for our code.
            std::lock_guard<std::mutex> lock(m_d3d11_context_mutex);
            RecordD3D11ContextOperation("serialized_boundary", frame, nullptr, slot);
        }
        ++completed;
        {
            std::lock_guard<std::mutex> lock(m_progress_mutex);
            m_progress.completed_frames = completed;
            m_progress.total_frames = frame_count;
            m_progress.current_fps = 0.0;
        }
        if (failed) break;
    }

    if (needs_decode) CloseDecoder();
    RecordInteractionTimeline(start_frame + completed, "ladder_end",
                              failed ? E_FAIL : S_OK);
    {
        std::lock_guard<std::mutex> lock(m_progress_mutex);
        m_stats.completed_frames = completed;
        m_stats.wall_time_sec = 0.0;
        m_stats.throughput_fps = 0.0;
        m_progress.completed_frames = completed;
        m_progress.total_frames = frame_count;
        m_progress.is_active = 0;
        m_progress.is_finished = 1;
        m_progress.error_code = failed ? -10 : 0;
        strcpy_s(m_progress.error_message,
                 failed ? "interaction ladder stage failed" : "");
    }
    m_is_active = false;
    m_is_finished = true;
}

void D3D11NvencPipeline::RecordDeterminismStage(uint32_t frame, const char* stage, bool present, HRESULT hr) {
    if (!m_determinism_diag || !m_determinism_file || !IsDeterminismProbeFrame(frame)) return;
    fprintf(m_determinism_file, "%u,%s,%s,0x%08X\n", frame, stage, present ? "True" : "False", (unsigned int)hr);
    fflush(m_determinism_file);
}

void D3D11NvencPipeline::RecordD2DThread(const char* operation, uint32_t frame) {
    if (!m_determinism_diag || !m_d2d_thread_file) return;
    DWORD thread_id = GetCurrentThreadId();
    if (m_d2d_owner_thread_id == 0) m_d2d_owner_thread_id = thread_id;
    bool mismatch = thread_id != m_d2d_owner_thread_id;
    fprintf(m_d2d_thread_file, "%s,%s,%lu,%lu,%s\n",
            frame == UINT32_MAX ? "" : std::to_string(frame).c_str(),
            operation ? operation : "", (unsigned long)thread_id,
            (unsigned long)m_d2d_owner_thread_id, mismatch ? "True" : "False");
    fflush(m_d2d_thread_file);
}

void D3D11NvencPipeline::RecordD2DTransform(uint32_t frame, const char* phase, const char* widget) {
    if (!m_determinism_diag || !m_d2d_transform_file || !m_pD2DContext ||
        !IsDeterminismProbeFrame(frame)) return;
    D2D1_MATRIX_3X2_F matrix{};
    m_pD2DContext->GetTransform(&matrix);
    fprintf(m_d2d_transform_file, "%u,%s,%s,%.9g,%.9g,%.9g,%.9g,%.9g,%.9g,%lu\n",
            frame, phase ? phase : "", widget ? widget : "",
            matrix._11, matrix._12, matrix._21, matrix._22,
            matrix._31, matrix._32, (unsigned long)GetCurrentThreadId());
    fflush(m_d2d_transform_file);
}

void D3D11NvencPipeline::RecordD2DStateStack(uint32_t frame, int clip_begin, int layer_begin,
                                             int begin_depth, int clip_end, int layer_end,
                                             int end_depth) {
    if (!m_determinism_diag || !m_d2d_state_stack_file) return;
    bool leak = clip_begin != 0 || layer_begin != 0 || begin_depth != 0 ||
                clip_end != 0 || layer_end != 0 || end_depth != 0;
    fprintf(m_d2d_state_stack_file, "%u,%d,%d,%d,%d,%d,%d,%s,%lu\n",
            frame, clip_begin, clip_end, layer_begin, layer_end,
            begin_depth, end_depth, leak ? "True" : "False",
            (unsigned long)GetCurrentThreadId());
    fflush(m_d2d_state_stack_file);
}

void D3D11NvencPipeline::RecordTargetBinding(uint32_t frame, const char* phase) {
    if (!m_determinism_diag || !m_d2d_target_binding_file ||
        !IsTargetBindingProbeFrame(frame) || !m_pD2DContext) return;
    ID2D1Image* target = nullptr;
    m_pD2DContext->GetTarget(&target);
    bool is_null = target == nullptr;
    fprintf(m_d2d_target_binding_file, "%u,%s,0x%p,%s,%s,%lu\n",
            frame, phase ? phase : "", (void*)target,
            is_null ? "True" : "False", D2DTargetDetachMode().c_str(),
            (unsigned long)GetCurrentThreadId());
    fflush(m_d2d_target_binding_file);
    if (target) target->Release();
}

void D3D11NvencPipeline::DumpD3D11InfoQueue(const char* label, uint32_t frame) {
    if (!m_d3d11_debug_file) return;
    if (!m_diag_info_queue) {
        fprintf(m_d3d11_debug_file, "frame=%u,label=%s,info_queue=unavailable\n",
                frame, label ? label : "");
        fflush(m_d3d11_debug_file);
        return;
    }
    UINT64 count = m_diag_info_queue->GetNumStoredMessagesAllowedByRetrievalFilter();
    fprintf(m_d3d11_debug_file, "frame=%u,label=%s,message_count=%llu\n",
            frame, label ? label : "", (unsigned long long)count);
    for (UINT64 i = 0; i < count; ++i) {
        SIZE_T bytes = 0;
        if (FAILED(m_diag_info_queue->GetMessage(i, nullptr, &bytes)) || bytes == 0) continue;
        std::vector<uint8_t> buffer(bytes);
        auto* message = reinterpret_cast<D3D11_MESSAGE*>(buffer.data());
        if (SUCCEEDED(m_diag_info_queue->GetMessage(i, message, &bytes)) && message->pDescription) {
            fprintf(m_d3d11_debug_file, "  id=%u,severity=%u,category=%u,%s\n",
                    (unsigned int)message->ID, (unsigned int)message->Severity,
                    (unsigned int)message->Category, message->pDescription);
        }
    }
    m_diag_info_queue->ClearStoredMessages();
    fflush(m_d3d11_debug_file);
}

void D3D11NvencPipeline::RecordEndDrawTrace(uint32_t frame, HRESULT end_hr, HRESULT flush_hr,
                                            uint64_t tag1, uint64_t tag2) {
    if (!m_determinism_diag || !m_d2d_enddraw_file) return;
    fprintf(m_d2d_enddraw_file, "%u,0x%08X,0x%08X,%llu,%llu,%lu\n",
            frame, (unsigned int)end_hr, (unsigned int)flush_hr,
            (unsigned long long)tag1, (unsigned long long)tag2,
            (unsigned long)GetCurrentThreadId());
    fflush(m_d2d_enddraw_file);
}

void D3D11NvencPipeline::EnsureDeferredIndicatorResources() {
    if (!m_diag_indicator_resources_deferred || !m_pD2DContext) return;
    RecordD2DThread("CreateDeviceResources", UINT32_MAX);
    for (auto& ind : m_indicators) {
        ind->CreateDeviceResources(m_pD2DContext, m_pDWriteFactory);
    }
    m_diag_indicator_resources_deferred = false;
}

bool D3D11NvencPipeline::CreateFreshHudResources(ID3D11Texture2D** texture, ID2D1Bitmap1** target, ID3D11VideoProcessorInputView** view) {
    if (!texture || !target || !view || !m_pDevice || !m_pVideoDevice || !m_pVPEnum || !m_pD2DContext) return false;
    *texture = nullptr; *target = nullptr; *view = nullptr;
    D3D11_TEXTURE2D_DESC desc{};
    desc.Width = m_config.width; desc.Height = m_config.height;
    desc.MipLevels = 1; desc.ArraySize = 1; desc.Format = DXGI_FORMAT_B8G8R8A8_UNORM;
    desc.SampleDesc.Count = 1; desc.Usage = D3D11_USAGE_DEFAULT;
    desc.BindFlags = D3D11_BIND_RENDER_TARGET | D3D11_BIND_SHADER_RESOURCE;
    HRESULT hr = m_pDevice->CreateTexture2D(&desc, nullptr, texture);
    if (FAILED(hr)) return false;
    IDXGISurface1* surface = nullptr;
    hr = (*texture)->QueryInterface(__uuidof(IDXGISurface1), (void**)&surface);
    if (FAILED(hr)) { SafeRelease(*texture); return false; }
    D2D1_BITMAP_PROPERTIES1 bp{};
    bp.pixelFormat.format = DXGI_FORMAT_B8G8R8A8_UNORM;
    bp.pixelFormat.alphaMode = D2D1_ALPHA_MODE_PREMULTIPLIED;
    bp.dpiX = 96.0f; bp.dpiY = 96.0f;
    bp.bitmapOptions = D2D1_BITMAP_OPTIONS_TARGET | D2D1_BITMAP_OPTIONS_CANNOT_DRAW;
    hr = m_pD2DContext->CreateBitmapFromDxgiSurface(surface, &bp, target);
    surface->Release();
    if (FAILED(hr)) { SafeRelease(*texture); return false; }
    D3D11_VIDEO_PROCESSOR_INPUT_VIEW_DESC in_desc{};
    in_desc.ViewDimension = D3D11_VPIV_DIMENSION_TEXTURE2D;
    hr = m_pVideoDevice->CreateVideoProcessorInputView(*texture, m_pVPEnum, &in_desc, view);
    if (FAILED(hr)) { SafeRelease(*target); SafeRelease(*texture); return false; }
    return true;
}

static bool CreateD2DTargetAndOptionalView(
    ID3D11Device* device, ID3D11VideoDevice* video_device,
    ID3D11VideoProcessorEnumerator* vp_enum, ID3D11Texture2D* texture,
    ID2D1DeviceContext* d2d, ID2D1Bitmap1** target,
    ID3D11VideoProcessorInputView** view) {
    if (!device || !video_device || !vp_enum || !texture || !d2d || (!target && !view)) return false;
    if (target) *target = nullptr;
    if (view) *view = nullptr;
    HRESULT hr = S_OK;
    if (target) {
        IDXGISurface1* surface = nullptr;
        hr = texture->QueryInterface(__uuidof(IDXGISurface1), (void**)&surface);
        if (FAILED(hr)) return false;
        D2D1_BITMAP_PROPERTIES1 bp{};
        bp.pixelFormat.format = DXGI_FORMAT_B8G8R8A8_UNORM;
        bp.pixelFormat.alphaMode = D2D1_ALPHA_MODE_PREMULTIPLIED;
        bp.dpiX = 96.0f; bp.dpiY = 96.0f;
        bp.bitmapOptions = D2D1_BITMAP_OPTIONS_TARGET | D2D1_BITMAP_OPTIONS_CANNOT_DRAW;
        hr = d2d->CreateBitmapFromDxgiSurface(surface, &bp, target);
        surface->Release();
        if (FAILED(hr)) return false;
    }
    if (view) {
        D3D11_VIDEO_PROCESSOR_INPUT_VIEW_DESC in_desc{};
        in_desc.ViewDimension = D3D11_VPIV_DIMENSION_TEXTURE2D;
        hr = video_device->CreateVideoProcessorInputView(texture, vp_enum, &in_desc, view);
        if (FAILED(hr)) { if (target) SafeRelease(*target); return false; }
    }
    return true;
}

bool D3D11NvencPipeline::CreateFreshHudTargetForTexture(ID3D11Texture2D* texture, ID2D1Bitmap1** target, ID3D11VideoProcessorInputView** view) {
    return CreateD2DTargetAndOptionalView(m_pDevice, m_pVideoDevice, m_pVPEnum, texture, m_pD2DContext, target, view);
}

bool D3D11NvencPipeline::CreateFreshD2DContextForTexture(ID3D11Texture2D* texture,
                                                         ID2D1DeviceContext** context,
                                                         ID2D1Bitmap1** target) {
    if (!texture || !context || !target || !m_pD2DDevice) return false;
    *context = nullptr;
    *target = nullptr;
    HRESULT hr = m_pD2DDevice->CreateDeviceContext(D2D1_DEVICE_CONTEXT_OPTIONS_NONE, context);
    if (FAILED(hr) || !*context) return false;
    (*context)->SetAntialiasMode(D2D1_ANTIALIAS_MODE_PER_PRIMITIVE);
    (*context)->SetTextAntialiasMode(D2D1_TEXT_ANTIALIAS_MODE_GRAYSCALE);
    (*context)->SetPrimitiveBlend(D2D1_PRIMITIVE_BLEND_SOURCE_OVER);
    (*context)->SetUnitMode(D2D1_UNIT_MODE_DIPS);
    (*context)->SetDpi(96.0f, 96.0f);
    IDXGISurface1* surface = nullptr;
    hr = texture->QueryInterface(__uuidof(IDXGISurface1), (void**)&surface);
    if (FAILED(hr) || !surface) {
        SafeRelease(*context);
        return false;
    }
    D2D1_BITMAP_PROPERTIES1 bp{};
    bp.pixelFormat.format = DXGI_FORMAT_B8G8R8A8_UNORM;
    bp.pixelFormat.alphaMode = D2D1_ALPHA_MODE_PREMULTIPLIED;
    bp.dpiX = 96.0f;
    bp.dpiY = 96.0f;
    bp.bitmapOptions = D2D1_BITMAP_OPTIONS_TARGET | D2D1_BITMAP_OPTIONS_CANNOT_DRAW;
    hr = (*context)->CreateBitmapFromDxgiSurface(surface, &bp, target);
    surface->Release();
    if (FAILED(hr) || !*target) {
        SafeRelease(*context);
        return false;
    }
    return true;
}

void D3D11NvencPipeline::ReleaseFreshHudResources() {
    SafeRelease(m_diag_fresh_hud_view);
    SafeRelease(m_diag_fresh_hud_target);
    SafeRelease(m_diag_fresh_hud_texture);
}

bool D3D11NvencPipeline::PrepareCopyOutHudTexture(ID3D11Texture2D* source_texture) {
    if (!source_texture || !m_pDevice || !m_pVideoDevice || !m_pVPEnum) return false;
    SafeRelease(m_diag_copy_hud_view);
    SafeRelease(m_diag_copy_hud_texture);
    D3D11_TEXTURE2D_DESC desc{};
    source_texture->GetDesc(&desc);
    desc.BindFlags = D3D11_BIND_SHADER_RESOURCE | D3D11_BIND_RENDER_TARGET;
    desc.MiscFlags = 0;
    HRESULT hr = m_pDevice->CreateTexture2D(&desc, nullptr, &m_diag_copy_hud_texture);
    if (FAILED(hr) || !m_diag_copy_hud_texture) {
        ReleaseCopyOutHudTexture();
        return false;
    }
    D3D11_VIDEO_PROCESSOR_INPUT_VIEW_DESC view_desc{};
    view_desc.ViewDimension = D3D11_VPIV_DIMENSION_TEXTURE2D;
    hr = m_pVideoDevice->CreateVideoProcessorInputView(
        m_diag_copy_hud_texture, m_pVPEnum, &view_desc, &m_diag_copy_hud_view);
    if (FAILED(hr) || !m_diag_copy_hud_view) {
        ReleaseCopyOutHudTexture();
        return false;
    }
    return true;
}

bool D3D11NvencPipeline::PrepareCopyOutDrawTexture() {
    if (!m_pDevice || !m_pD2DContext || !m_pVideoDevice || !m_pVPEnum) return false;
    SafeRelease(m_diag_copy_draw_target);
    SafeRelease(m_diag_copy_draw_texture);
    D3D11_TEXTURE2D_DESC desc{};
    desc.Width = m_config.width;
    desc.Height = m_config.height;
    desc.MipLevels = 1;
    desc.ArraySize = 1;
    desc.Format = DXGI_FORMAT_B8G8R8A8_UNORM;
    desc.SampleDesc.Count = 1;
    desc.Usage = D3D11_USAGE_DEFAULT;
    desc.BindFlags = D3D11_BIND_RENDER_TARGET | D3D11_BIND_SHADER_RESOURCE;
    HRESULT hr = m_pDevice->CreateTexture2D(&desc, nullptr, &m_diag_copy_draw_texture);
    if (FAILED(hr) || !m_diag_copy_draw_texture) return false;
    if (!CreateD2DTargetAndOptionalView(m_pDevice, m_pVideoDevice, m_pVPEnum,
                                        m_diag_copy_draw_texture, m_pD2DContext,
                                        &m_diag_copy_draw_target, nullptr)) {
        SafeRelease(m_diag_copy_draw_texture);
        return false;
    }
    return true;
}

void D3D11NvencPipeline::ReleaseCopyOutHudTexture() {
    SafeRelease(m_diag_copy_hud_view);
    SafeRelease(m_diag_copy_hud_texture);
    SafeRelease(m_diag_copy_draw_target);
    SafeRelease(m_diag_copy_draw_texture);
}

bool D3D11NvencPipeline::RenderD3D11DynamicHud(uint32_t frame, int slot) {
    if (!m_pContext || !m_pDevice || slot < 0 || slot >= (int)m_ring_hud_textures.size()) return false;
    // The pure-D3D11 control must not leave a D2D target bound while the same
    // texture is written through its RTV and subsequently consumed by the VP.
    if (m_pD2DContext) m_pD2DContext->SetTarget(nullptr);
    RecordTargetBinding(frame, "d3d11_control_before_clear");
    ID3D11RenderTargetView* rtv = nullptr;
    HRESULT hr = m_pDevice->CreateRenderTargetView(m_ring_hud_textures[slot], nullptr, &rtv);
    if (FAILED(hr) || !rtv) return false;
    // Keep every probe pixel above the marker threshold while changing the
    // clear value deterministically on every frame.
    const float v = 0.90f + 0.01f * static_cast<float>(frame % 10u);
    const float color[4] = { v, v, v, 1.0f };
    RecordD3D11ContextOperation("ClearRenderTargetView", frame, rtv, slot);
    m_pContext->ClearRenderTargetView(rtv, color);
    rtv->Release();
    RecordD3D11ContextOperation("Flush_D3D11_control", frame, nullptr, slot);
    m_pContext->Flush();
    DumpD3D11InfoQueue("ClearRenderTargetView", frame);
    RecordTargetBinding(frame, "d3d11_control_after_clear");
    return true;
}

bool D3D11NvencPipeline::ReadbackHudMarker(ID3D11Texture2D* texture, bool p010) {
    if (!m_determinism_diag || !texture || !m_pDevice || !m_pContext) return false;
    D3D11_TEXTURE2D_DESC desc{};
    texture->GetDesc(&desc);
    const uint32_t sample_w = (std::min)(96u, desc.Width);
    const uint32_t sample_h = (std::min)(96u, desc.Height);
    D3D11_TEXTURE2D_DESC staging = desc;
    staging.Width = sample_w;
    staging.Height = sample_h;
    staging.Usage = D3D11_USAGE_STAGING;
    staging.BindFlags = 0;
    staging.CPUAccessFlags = D3D11_CPU_ACCESS_READ;
    staging.MiscFlags = 0;
    ID3D11Texture2D* staging_tex = nullptr;
    if (FAILED(m_pDevice->CreateTexture2D(&staging, nullptr, &staging_tex)) || !staging_tex) return false;
    RecordD3D11ContextOperation("CopyResource_readback", UINT32_MAX, texture, -1);
    D3D11_BOX box{0, 0, 0, sample_w, sample_h, 1};
    m_pContext->CopySubresourceRegion(staging_tex, 0, 0, 0, 0, texture, 0, &box);
    // Match the standalone D3D11 readback contract: the copy is followed by
    // an EVENT query and GetData completion before Map.  A bare Flush does
    // not prove that the copy has completed on every driver/queue timing.
    D3D11_QUERY_DESC event_desc{};
    event_desc.Query = D3D11_QUERY_EVENT;
    ID3D11Query* event_query = nullptr;
    HRESULT event_hr = m_pDevice->CreateQuery(&event_desc, &event_query);
    if (FAILED(event_hr) || !event_query) {
        RecordInteractionTimeline(m_interaction_current_frame, "readback_event_create", event_hr);
        staging_tex->Release();
        return false;
    }
    RecordD3D11ContextOperation("End_query_readback", UINT32_MAX, event_query, -1);
    m_pContext->End(event_query);
    RecordD3D11ContextOperation("Flush_readback", UINT32_MAX, staging_tex, -1);
    m_pContext->Flush();
    BOOL done = FALSE;
    while (!done) {
        HRESULT get_hr = m_pContext->GetData(event_query, &done, sizeof(done), 0);
        RecordD3D11ContextOperation("GetData_readback", UINT32_MAX, event_query, -1);
        if (FAILED(get_hr)) {
            RecordInteractionTimeline(m_interaction_current_frame, "readback_event_getdata", get_hr);
            event_query->Release();
            staging_tex->Release();
            return false;
        }
        if (!done) YieldProcessor();
    }
    event_query->Release();
    D3D11_MAPPED_SUBRESOURCE mapped{};
    RecordD3D11ContextOperation("Map_readback", UINT32_MAX, staging_tex, -1);
    HRESULT hr = m_pContext->Map(staging_tex, 0, D3D11_MAP_READ, 0, &mapped);
    if (FAILED(hr)) {
        staging_tex->Release();
        return false;
    }
    uint32_t hits = 0;
    if (!p010) {
        for (uint32_t y = 0; y < sample_h; ++y) {
            const uint8_t* row = static_cast<const uint8_t*>(mapped.pData) + y * mapped.RowPitch;
            for (uint32_t x = 0; x < sample_w; ++x) {
                const uint8_t* px = row + x * 4;
                if (px[2] > 220 && px[1] > 220 && px[0] > 220 && px[3] > 200) hits++;
            }
        }
    } else {
        const uint8_t* base = static_cast<const uint8_t*>(mapped.pData);
        for (uint32_t y = 0; y < sample_h; y += 2) {
            const uint16_t* yrow = reinterpret_cast<const uint16_t*>(base + y * mapped.RowPitch);
            const uint16_t* uvrow = reinterpret_cast<const uint16_t*>(base + staging.Height * mapped.RowPitch + (y / 2) * mapped.RowPitch);
            for (uint32_t x = 0; x < sample_w; x += 2) {
                uint32_t y10 = yrow[x] >> 6;
                uint32_t u10 = uvrow[x & ~1u] >> 6;
                uint32_t v10 = uvrow[(x & ~1u) + 1] >> 6;
                if (y10 > 820 && u10 > 400 && u10 < 650 && v10 > 400 && v10 < 650) hits++;
            }
        }
    }
    RecordD3D11ContextOperation("Unmap_readback", UINT32_MAX, staging_tex, -1);
    m_pContext->Unmap(staging_tex, 0);
    staging_tex->Release();
    return hits >= (p010 ? 12u : 128u);
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

HRESULT D3D11NvencPipeline::RenderHud(const TelemFrameState& state, int slot, ID2D1Bitmap1* target, bool clear_target) {
    if (!m_pD2DContext || slot < 0 || slot >= (int)m_ring_d2d_bitmap_targets.size()) return E_FAIL;

    int clip_depth_begin = m_d2d_state_trace.clip_depth;
    int layer_depth_begin = m_d2d_state_trace.layer_depth;
    int begin_draw_depth_begin = m_d2d_state_trace.begin_draw_depth;
    RecordD2DThread("SetTarget", state.frame_index);
    TelemHudProfile::Count("d2d", "SetTarget");
    TelemHudProfile::Timeline(state.frame_index, "SetTarget");
    RecordD2DTransform(state.frame_index, "before_begin_draw", "");
    m_pD2DContext->SetTarget(target ? target : m_ring_d2d_bitmap_targets[slot]);
    RecordTargetBinding(state.frame_index, "target_before_BeginDraw");
    if (m_determinism_diag && IsDeterminismProbeFrame(state.frame_index)) {
        ID2D1Image* bound_target = nullptr;
        m_pD2DContext->GetTarget(&bound_target);
        ID2D1Bitmap1* expected_target = target ? target : m_ring_d2d_bitmap_targets[slot];
        ID3D11Texture2D* expected_texture = m_diag_fresh_hud_texture ? m_diag_fresh_hud_texture : m_ring_hud_textures[slot];
        std::string identity_path = m_determinism_dir + "\\d2d_target_identity.csv";
        FILE* identity = fopen(identity_path.c_str(), "a+");
        if (identity) {
            fseek(identity, 0, SEEK_END);
            if (ftell(identity) == 0) fprintf(identity, "frame,texture_ptr,bitmap_ptr,d2d_gettarget_ptr,gettarget_equals_expected,surface_ptr\n");
            IDXGISurface1* surface = nullptr;
            if (expected_texture) expected_texture->QueryInterface(__uuidof(IDXGISurface1), (void**)&surface);
            fprintf(identity, "%u,0x%p,0x%p,0x%p,%s,0x%p\n", state.frame_index,
                    (void*)expected_texture, (void*)expected_target, (void*)bound_target,
                    bound_target == expected_target ? "True" : "False", (void*)surface);
            if (surface) surface->Release();
            if (bound_target) bound_target->Release();
            fclose(identity);
        }
    }
    if (m_d2d_reset_state) {
        m_pD2DContext->SetTarget(target ? target : m_ring_d2d_bitmap_targets[slot]);
        m_pD2DContext->SetTransform(D2D1::Matrix3x2F::Identity());
        m_pD2DContext->SetPrimitiveBlend(D2D1_PRIMITIVE_BLEND_SOURCE_OVER);
        m_pD2DContext->SetAntialiasMode(D2D1_ANTIALIAS_MODE_PER_PRIMITIVE);
        m_pD2DContext->SetTextAntialiasMode(D2D1_TEXT_ANTIALIAS_MODE_GRAYSCALE);
        m_pD2DContext->SetUnitMode(D2D1_UNIT_MODE_DIPS);
        m_pD2DContext->SetDpi(96.0f, 96.0f);
    } else {
        m_pD2DContext->SetTransform(D2D1::Matrix3x2F::Identity());
    }
    RecordD2DThread("BeginDraw", state.frame_index);
    TelemHudProfile::Count("d2d", "BeginDraw");
    TelemHudProfile::Timeline(state.frame_index, "BeginDraw");
    g_telem_d2d_state_trace = &m_d2d_state_trace;
    m_pD2DContext->BeginDraw();
    ++m_d2d_state_trace.begin_draw_depth;
    RecordTargetBinding(state.frame_index, "target_during_draw");
    if (clear_target) {
        m_pD2DContext->Clear(D2D1::ColorF(0.0f, 0.0f, 0.0f, 0.0f));
    }

    if ((state.frame_index >= 146 && state.frame_index <= 155) || (state.frame_index >= 1255 && state.frame_index <= 1265)) {
        printf("[FRAME %u RENDERHUD START] slot=%d inds=%zu\n", state.frame_index, slot, m_indicators.size());
        fflush(stdout);
    }

    bool marker_only = false;
    if (m_determinism_diag) {
        char marker_mode[8] = {};
        DWORD marker_len = GetEnvironmentVariableA("TELEM_NATIVE_MARKER_ONLY", marker_mode, (DWORD)sizeof(marker_mode));
        marker_only = marker_len > 0 && marker_len < sizeof(marker_mode) && marker_mode[0] == '1';
    }
    bool minimal_draw = m_d2d_minimal_draw;
    if (minimal_draw) {
        D2D1_RECT_F minimal_rect = D2D1::RectF(0.0f, 0.0f, 320.0f, 180.0f);
        m_pD2DContext->FillRectangle(&minimal_rect, m_brush_card_bg);
        wchar_t frame_text[64] = {};
        swprintf_s(frame_text, L"FRAME %u", state.frame_index);
        D2D1_RECT_F text_rect = D2D1::RectF(12.0f, 12.0f, 300.0f, 160.0f);
        m_pD2DContext->DrawText(frame_text, (UINT32)wcslen(frame_text), m_fmt_label, &text_rect, m_brush_white);
    } else if (!marker_only && !m_indicators.empty()) {
        const std::string widget_group = D2DWidgetGroupDiagnostic();
        for (size_t k = 0; k < m_indicators.size(); ++k) {
            auto& ind = m_indicators[k];
            if (!IncludeD2DWidgetForGroup(*ind, widget_group)) continue;
            const double widget_t0 = TelemHudProfile::NowSeconds();
            TelemHudProfile::Timeline(state.frame_index, ind->GetKey().c_str());
            const std::string& key = ind->GetKey();
            const char* update_value = "";
            if (key == "time_display") update_value = state.time_display_time;
            else if (key == "exposure_text") update_value = state.exposure_str;
            else if (key == "iso_text") update_value = state.iso_str;
            else if (key == "temp_text") update_value = state.temp_str;
            else if (key == "fit_gopro_battery_text") update_value = state.gopro_battery_str;
            else if (key == "fit_distance_text") update_value = state.distance_str;
            else if (key == "fit_solar_text") update_value = state.solar_str;
            else if (key == "alt_text") update_value = state.altitude_str;
            else if (key == "fit_curVpower_text") update_value = state.power_str;
            else if (key == "fit_garmin_battery_percent_text") update_value = state.garmin_battery_str;
            else if (key == "speed_text") update_value = state.speed_str;
            else if (key == "fit_heart_rate_text") update_value = state.hr_str;
            else if (key == "fit_cadence_text") update_value = state.cad_str;
            TelemHudProfile::Update(state.frame_index, key.c_str(), update_value);
            ind->Render(m_pD2DContext, state);
            TelemHudProfile::Timeline(state.frame_index, (key + " done").c_str());
            TelemHudProfile::Record("widget", ind->GetKey().c_str(), "render",
                                    (TelemHudProfile::NowSeconds() - widget_t0) * 1000.0);
            RecordD2DThread((std::string("draw:") + ind->GetKey()).c_str(), state.frame_index);
            RecordD2DTransform(state.frame_index, "after_widget", ind->GetKey().c_str());
        }
    } else if (!marker_only) {
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
        RecordD2DTransform(state.frame_index, "after_widget", "fallback");
    }
    if (minimal_draw) {
        RecordD2DThread("draw:minimal", state.frame_index);
        RecordD2DTransform(state.frame_index, "after_widget", "minimal");
    }

    if (m_determinism_diag) {
        // Diagnostic-only opaque red marker. It is never emitted unless the
        // caller explicitly sets TELEM_NATIVE_DETERMINISM_DIR.
        D2D1_RECT_F marker = D2D1::RectF(0.0f, 0.0f, 96.0f, 96.0f);
        m_pD2DContext->FillRectangle(&marker, m_brush_white);
    }

    // D2D requires Flush while the draw is open on this driver.  The
    // transition experiment below separates this D2D flush from the
    // immediate-context completion flush that fences the VP read.
    D2D1_TAG tag_flush1 = 0, tag_flush2 = 0;
    const double flush_t0 = TelemHudProfile::NowSeconds();
    HRESULT hr_flush = m_pD2DContext->Flush(&tag_flush1, &tag_flush2);
    TelemHudProfile::Record("hud", "flush", "d2d", (TelemHudProfile::NowSeconds() - flush_t0) * 1000.0);
    TelemHudProfile::Count("d2d", "Flush");
    TelemHudProfile::Timeline(state.frame_index, "Flush");
    if (FAILED(hr_flush)) {
        printf("[D2D ERROR] Flush before EndDraw failed at slot=%d: 0x%08X tag1=%llu tag2=%llu\n", slot, (unsigned int)hr_flush, (unsigned long long)tag_flush1, (unsigned long long)tag_flush2);
        fflush(stdout);
    }
    DumpD3D11InfoQueue("D2D_Flush", state.frame_index);

    D2D1_TAG tag1 = 0, tag2 = 0;
    const double enddraw_t0 = TelemHudProfile::NowSeconds();
    HRESULT hr_d2d = m_pD2DContext->EndDraw(&tag1, &tag2);
    TelemHudProfile::Record("hud", "enddraw", "d2d", (TelemHudProfile::NowSeconds() - enddraw_t0) * 1000.0);
    TelemHudProfile::Count("d2d", "EndDraw");
    TelemHudProfile::Timeline(state.frame_index, "EndDraw");
    --m_d2d_state_trace.begin_draw_depth;
    if (FAILED(hr_d2d)) {
        printf("[D2D ERROR] EndDraw failed at slot=%d: 0x%08X tag1=%llu tag2=%llu\n", slot, (unsigned int)hr_d2d, (unsigned long long)tag1, (unsigned long long)tag2);
        fflush(stdout);
    }

    RecordTargetBinding(state.frame_index, "target_after_EndDraw");

    // Mode C deliberately detaches before the D2D/device flush.  Modes B and
    // D retain the target through the flush and detach immediately after it;
    // mode A intentionally leaves it bound for the VP hazard control.
    const std::string detach_mode = D2DTargetDetachMode();
    if (detach_mode == "C") {
        m_pD2DContext->SetTarget(nullptr);
        RecordTargetBinding(state.frame_index, "target_after_detach_before_flush");
        DumpD3D11InfoQueue("SetTarget(nullptr)_before_flush", state.frame_index);
    }

    m_last_end_draw_hr = hr_d2d;
    m_last_d2d_flush_hr = hr_flush;
    m_last_d2d_tag1 = tag1;
    m_last_d2d_tag2 = tag2;
    RecordD2DThread("EndDraw", state.frame_index);
    RecordD2DThread("Flush", state.frame_index);
    RecordEndDrawTrace(state.frame_index, hr_d2d, hr_flush, tag1, tag2);
    RecordD2DTransform(state.frame_index, "end_frame", "");
    RecordD2DStateStack(state.frame_index, clip_depth_begin, layer_depth_begin,
                        begin_draw_depth_begin, m_d2d_state_trace.clip_depth,
                        m_d2d_state_trace.layer_depth, m_d2d_state_trace.begin_draw_depth);
    g_telem_d2d_state_trace = nullptr;

    if (m_determinism_diag) {
        std::string sequence_path = m_determinism_dir + "\\d2d_draw_sequence.csv";
        FILE* sequence = fopen(sequence_path.c_str(), "a+");
        if (sequence) {
            fseek(sequence, 0, SEEK_END);
            if (ftell(sequence) == 0) {
                fprintf(sequence, "frame,slot,set_target,begin_draw,clear,draw_count_expected,draw_count_actual,enddraw_hr,flush_hr\n");
            }
            uint32_t text_draws = 0, bitmap_draws = 0, geometry_draws = 0, chart_primitives = 0;
            for (const auto& ind : m_indicators) {
                auto type = ind->GetType();
                if (type == TELEM_IND_TEXT || type == TELEM_IND_TIME_DISPLAY) text_draws++;
                else if (type == TELEM_IND_MAP) bitmap_draws++;
                else if (type == TELEM_IND_CHART) chart_primitives++;
                else geometry_draws++;
            }
            uint32_t expected = text_draws + bitmap_draws + geometry_draws + chart_primitives + 1u;
            fprintf(sequence, "%u,%d,1,1,%d,%u,%u,0x%08X,0x%08X\n",
                    state.frame_index, slot, clear_target ? 1 : 0, expected,
                    SUCCEEDED(hr_d2d) ? expected : 0u, (unsigned int)hr_d2d, (unsigned int)hr_flush);
            fclose(sequence);
        }
    }

    // Critical: force D2D's GPU commands into the immediate context command queue NOW.
    // D2D's EndDraw() queues D3D11 commands but does not call ID3D11DeviceContext::Flush().
    // Without this flush, the fence query End() (placed by the caller AFTER we return) would
    // be recorded BEFORE D2D's actual GPU work arrives in the command stream, so the fence
    // would complete before the HUD texture is rendered — causing VideoProcessorBlt to sample
    // an empty/stale HUD texture.
    RecordD3D11ContextOperation("Flush_after_D2D_EndDraw", state.frame_index,
                                target ? target : (void*)m_ring_hud_textures[slot], slot);
    ID3D11DeviceContext* hud_flush_context =
        m_rendering_separate_hud ? m_hud_b_context : m_pContext;
    if (hud_flush_context) hud_flush_context->Flush();
    TelemHudProfile::Count("d2d", "D3D11Flush");
    DumpD3D11InfoQueue("D3D11_Flush_after_EndDraw", state.frame_index);
    RecordTargetBinding(state.frame_index, "target_after_Flush");

    if (detach_mode != "A" && detach_mode != "C") {
        m_pD2DContext->SetTarget(nullptr);
        RecordTargetBinding(state.frame_index, "target_after_detach");
        DumpD3D11InfoQueue("SetTarget(nullptr)_after_flush", state.frame_index);
    }

    if ((state.frame_index >= 146 && state.frame_index <= 155) || (state.frame_index >= 1255 && state.frame_index <= 1265)) {
        printf("[FRAME %u ENDDRAW] hr_d2d=0x%08X tag1=%llu tag2=%llu hr_flush=0x%08X\n",
               state.frame_index, (unsigned int)hr_d2d, (unsigned long long)tag1, (unsigned long long)tag2, (unsigned int)hr_flush);
        fflush(stdout);
    }

    // Production keeps the explicit target detach.  Mode A is diagnostic-only
    // and intentionally skips it to expose a simultaneous D2D-target/VP-input
    // role hazard.
    if (!m_determinism_diag || detach_mode != "A") {
        m_pD2DContext->SetTarget(nullptr);
    }
    ID3D11RenderTargetView* nullRTV[1] = { nullptr };
    RecordD3D11ContextOperation("OMSetRenderTargets_null", state.frame_index, nullptr, slot);
    if (m_pContext) m_pContext->OMSetRenderTargets(1, nullRTV, nullptr);
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
        RecordD3D11ContextOperation("VideoProcessorBlt_background", UINT32_MAX,
                                    pVideoInView, ring_slot);
        HRESULT hr = m_pVideoContext->VideoProcessorBlt(m_pVP, pOutView, 0, 1, &stream);
        result = SUCCEEDED(hr);
    } else {
        D3D11_VIDEO_PROCESSOR_STREAM streams[2]{};
        // D3D11 VideoProcessor composites stream 0 behind higher numbered
        // streams.  Keep decoded P010 video as the base and D2D BGRA HUD as
        // the alpha-blended overlay.
        streams[0].Enable = TRUE;
        streams[0].pInputSurface = pVideoInView;

        streams[1].Enable = TRUE;
        if (m_diag_copy_hud_view) {
            streams[1].pInputSurface = m_diag_copy_hud_view;
        } else if (m_diag_fresh_hud_view) {
            streams[1].pInputSurface = m_diag_fresh_hud_view;
        } else {
            int hud_view_slot = m_diag_hud_slot_override >= 0
                ? m_diag_hud_slot_override
                : ((IsStaticHudDiagnostic() || IsSingleHudDiagnostic()) ? 0 : ring_slot);
            streams[1].pInputSurface = m_ring_vp_in_view_huds[hud_view_slot];
        }

        m_pVideoContext->VideoProcessorSetStreamFrameFormat(m_pVP, 0, D3D11_VIDEO_FRAME_FORMAT_PROGRESSIVE);
        m_pVideoContext->VideoProcessorSetStreamFrameFormat(m_pVP, 1, D3D11_VIDEO_FRAME_FORMAT_PROGRESSIVE);
        m_pVideoContext->VideoProcessorSetStreamAutoProcessingMode(m_pVP, 0, FALSE);
        m_pVideoContext->VideoProcessorSetStreamAutoProcessingMode(m_pVP, 1, FALSE);
        m_pVideoContext->VideoProcessorSetStreamAlpha(m_pVP, 0, FALSE, 1.0f);
        m_pVideoContext->VideoProcessorSetStreamAlpha(m_pVP, 1, TRUE, 1.0f);
        RecordD3D11ContextOperation("VideoProcessorBlt_hud", UINT32_MAX,
                                    streams[1].pInputSurface, ring_slot);
        HRESULT hr = m_pVideoContext->VideoProcessorBlt(m_pVP, pOutView, 0, 2, streams);
        m_last_vp_blt_hr = hr;
        if (FAILED(hr)) {
            printf("[VP ERROR] VideoProcessorBlt failed: 0x%08X\n", (unsigned int)hr);
        }
        result = SUCCEEDED(hr);
    }
    return result;
}

bool D3D11NvencPipeline::CompositeVideoToBgra(ID3D11VideoProcessorInputView* pVideoInView, int ring_slot) {
    if (!m_pVideoContext || !m_pVP || !pVideoInView ||
        ring_slot < 0 || ring_slot >= (int)m_ring_vp_bgra_out_views.size()) {
        return false;
    }
    D3D11_VIDEO_PROCESSOR_STREAM stream{};
    stream.Enable = TRUE;
    stream.pInputSurface = pVideoInView;
    RecordD3D11ContextOperation("VideoProcessorBlt_to_bgra", UINT32_MAX,
                                pVideoInView, ring_slot);
    HRESULT hr = m_pVideoContext->VideoProcessorBlt(
        m_pVP, m_ring_vp_bgra_out_views[ring_slot], 0, 1, &stream
    );
    if (FAILED(hr)) {
        printf("[VP ERROR] P010-to-BGRA VideoProcessorBlt failed: 0x%08X\n", (unsigned int)hr);
        return false;
    }
    // The D2D immediate context consumes this texture next.  Submit and wait
    // for the base-video write without a CPU texture readback.
    if (ring_slot < (int)m_ring_vp_queries.size() && m_ring_vp_queries[ring_slot]) {
        m_pContext->End(m_ring_vp_queries[ring_slot]);
        m_pContext->Flush();
        BOOL done = FALSE;
        while (!done) {
            HRESULT qhr = m_pContext->GetData(
                m_ring_vp_queries[ring_slot], &done, sizeof(BOOL), 0
            );
            if (FAILED(qhr)) {
                break;
            }
            YieldProcessor();
        }
    }
    return true;
}

bool D3D11NvencPipeline::CompositeBgraToP010(int ring_slot) {
    if (!m_pVideoContext || !m_pVP ||
        ring_slot < 0 || ring_slot >= (int)m_ring_vp_in_view_bgra_composites.size() ||
        ring_slot >= (int)m_ring_vp_out_views.size()) {
        return false;
    }
    D3D11_VIDEO_PROCESSOR_STREAM stream{};
    stream.Enable = TRUE;
    stream.pInputSurface = m_ring_vp_in_view_bgra_composites[ring_slot];
    RecordD3D11ContextOperation("VideoProcessorBlt_to_p010", UINT32_MAX,
                                stream.pInputSurface, ring_slot);
    HRESULT hr = m_pVideoContext->VideoProcessorBlt(
        m_pVP, m_ring_vp_out_views[ring_slot], 0, 1, &stream
    );
    m_last_vp_blt_hr = hr;
    if (FAILED(hr)) {
        printf("[VP ERROR] BGRA-to-P010 VideoProcessorBlt failed: 0x%08X\n", (unsigned int)hr);
    }
    return SUCCEEDED(hr);
}

bool D3D11NvencPipeline::ComposeVideoAndHudOnBgra(int ring_slot) {
    if (!m_pD2DContext ||
        ring_slot < 0 ||
        ring_slot >= (int)m_ring_d2d_bgra_composite_targets.size() ||
        ring_slot >= (int)m_ring_d2d_hud_sources.size() ||
        ring_slot >= (int)m_ring_d2d_bgra_video_sources.size()) {
        printf("[D2D HUD BLEND] invalid slot/context slot=%d\n", ring_slot);
        fflush(stdout);
        return false;
    }
    ID2D1Bitmap1* target = m_ring_d2d_bgra_composite_targets[ring_slot];
    ID2D1Bitmap1* hud = m_ring_d2d_hud_sources[ring_slot];
    ID2D1Bitmap1* video = m_ring_d2d_bgra_video_sources[ring_slot];
    if (!target || !hud || !video) {
        printf("[D2D HUD BLEND] null bitmap slot=%d target=%p video=%p hud=%p\n",
               ring_slot, target, video, hud);
        fflush(stdout);
        return false;
    }

    m_pD2DContext->SetTarget(target);
    m_pD2DContext->SetTransform(D2D1::Matrix3x2F::Identity());
    m_pD2DContext->BeginDraw();
    D2D1_SIZE_F size = target->GetSize();
    D2D1_RECT_F dst = D2D1::RectF(0.0f, 0.0f, size.width, size.height);
    m_pD2DContext->DrawBitmap(video, &dst, 1.0f,
        D2D1_INTERPOLATION_MODE_NEAREST_NEIGHBOR, nullptr);
    m_pD2DContext->DrawBitmap(hud, &dst, 1.0f,
        D2D1_INTERPOLATION_MODE_NEAREST_NEIGHBOR, nullptr);
    HRESULT hr = m_pD2DContext->EndDraw();
    if (FAILED(hr)) {
        printf("[D2D HUD COMPOSE] EndDraw failed slot=%d hr=0x%08X\n",
               ring_slot, (unsigned int)hr);
        fflush(stdout);
    }
    m_last_end_draw_hr = hr;
    m_pContext->Flush();
    m_pD2DContext->SetTarget(nullptr);
    ID3D11RenderTargetView* nullRTV[1] = { nullptr };
    m_pContext->OMSetRenderTargets(1, nullRTV, nullptr);
    return SUCCEEDED(hr);
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
    printf("[NATIVE] StartNvencSession begin\n"); fflush(stdout);
    EndNvencSession();

    if (!m_hNvencDll) {
        printf("[NATIVE] Loading nvEncodeAPI64.dll\n"); fflush(stdout);
        m_hNvencDll = LoadLibraryW(L"nvEncodeAPI64.dll");
        if (!m_hNvencDll) return false;

        typedef NVENCSTATUS(NVENCAPI *PFN_NvEncodeAPICreateInstance)(NV_ENCODE_API_FUNCTION_LIST*);
        PFN_NvEncodeAPICreateInstance pfnCreate = reinterpret_cast<PFN_NvEncodeAPICreateInstance>(reinterpret_cast<void*>(GetProcAddress(m_hNvencDll, "NvEncodeAPICreateInstance")));
        if (!pfnCreate) return false;

        m_nvenc.version = NV_ENCODE_API_FUNCTION_LIST_VER;
        printf("[NATIVE] Calling NvEncodeAPICreateInstance\n"); fflush(stdout);
        if (pfnCreate(&m_nvenc) != NV_ENC_SUCCESS) return false;
        printf("[NATIVE] NvEncodeAPICreateInstance returned\n"); fflush(stdout);
    }

    NV_ENC_OPEN_ENCODE_SESSION_EX_PARAMS openParams{};
    openParams.version = NV_ENC_OPEN_ENCODE_SESSION_EX_PARAMS_VER;
    openParams.deviceType = NV_ENC_DEVICE_TYPE_DIRECTX;
    openParams.device = m_pDevice;
    openParams.apiVersion = NVENCAPI_VERSION;

    printf("[NATIVE] Calling nvEncOpenEncodeSessionEx device=%p\n", m_pDevice); fflush(stdout);
    NVENCSTATUS status = m_nvenc.nvEncOpenEncodeSessionEx(&openParams, &m_hEncoder);
    printf("[NATIVE] nvEncOpenEncodeSessionEx returned status=%d handle=%p\n", status, m_hEncoder); fflush(stdout);
    if (status != NV_ENC_SUCCESS) return false;

    while (!m_free_bitstream_buffers.empty()) m_free_bitstream_buffers.pop();
    while (!m_in_flight_bitstream_buffers.empty()) m_in_flight_bitstream_buffers.pop();
    while (!m_in_flight_bitstream_ownership.empty()) m_in_flight_bitstream_ownership.pop();
    m_consumer_index = 0;
    m_first_bs_seen = false;
    m_slot_in_flight.assign(m_config.ring_size, -1);
    m_slot_generation.assign(m_config.ring_size, 0);
    m_ring_release_diags.clear();

    GUID codecGuid{};
    GUID profileGuid{};
    GUID presetGuid{};
    NV_ENC_TUNING_INFO tuningInfo{};
    NV_ENC_CONFIG encConfig{};
    uint32_t reqRingSize = 8;

    printf("[NATIVE] Resolving encoder profile\n"); fflush(stdout);
    if (!ResolveEncoderProfile(codecGuid, profileGuid, presetGuid, tuningInfo, encConfig, reqRingSize)) {
        return false;
    }
    printf("[NATIVE] Encoder profile resolved\n"); fflush(stdout);

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

    printf("[NATIVE] Calling nvEncInitializeEncoder\n"); fflush(stdout);
    status = m_nvenc.nvEncInitializeEncoder(m_hEncoder, &initParams);
    printf("[NATIVE] nvEncInitializeEncoder returned status=%d\n", status); fflush(stdout);
    if (status != NV_ENC_SUCCESS) {
        printf("[NVENC INIT ERROR] nvEncInitializeEncoder failed: %d (0x%08X)\n", status, status);
        return false;
    }

    // Register persistent ring textures
    m_ring_registered_handles.clear();
    NV_ENC_BUFFER_FORMAT bufFmt = (m_config.bit_depth == 10) ? NV_ENC_BUFFER_FORMAT_YUV420_10BIT : NV_ENC_BUFFER_FORMAT_NV12;

    printf("[NATIVE] Registering %u input textures\n", m_config.ring_size); fflush(stdout);
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
        RecordInteractionIdentity("NVENC", "register", "registered_resource",
                                  reg.registeredResource, m_pContext);
    }

    // Allocate decoupled bitstream buffer pool (64 buffers to support lookahead + B-frames)
    m_all_bitstream_buffers.clear();
    while (!m_free_bitstream_buffers.empty()) m_free_bitstream_buffers.pop();
    while (!m_in_flight_bitstream_buffers.empty()) m_in_flight_bitstream_buffers.pop();
    while (!m_in_flight_bitstream_ownership.empty()) m_in_flight_bitstream_ownership.pop();

    const size_t NUM_BS_BUFFERS = 64;
    printf("[NATIVE] Creating %zu bitstream buffers\n", NUM_BS_BUFFERS); fflush(stdout);
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
    // NVENC owns the mapped input until the corresponding bitstream has been
    // locked successfully.  Unmapping here races a wrapped slot (the API
    // explicitly requires UnmapInputResource after LockBitstream).

    if (pDiag) {
        pDiag->encode_status = (uint32_t)status;
        pDiag->pending_count = (uint32_t)m_in_flight_bitstream_buffers.size();
    }

    if (status != NV_ENC_SUCCESS && status != NV_ENC_ERR_NEED_MORE_INPUT) {
        printf("[NVENC ERROR] nvEncEncodePicture failed: %d\n", status);
        m_nvenc.nvEncUnmapInputResource(m_hEncoder, mapRes.mappedResource);
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
    uint32_t generation = (ring_slot >= 0 && ring_slot < (int)m_slot_generation.size())
        ? m_slot_generation[ring_slot] : 0;
    m_in_flight_bitstream_ownership.push({curBs, global_frame_idx, ring_slot,
                                          mapRes.mappedResource, generation});
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
    const auto ownership = m_in_flight_bitstream_ownership.front();
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
        if (ownership.mapped_resource) {
            NVENCSTATUS unmap_status = m_nvenc.nvEncUnmapInputResource(
                m_hEncoder, ownership.mapped_resource);
            if (unmap_status != NV_ENC_SUCCESS) {
                printf("[NVENC OWNERSHIP ERROR] UnmapInputResource failed for frame %u slot %d: %d\n",
                       ownership.input_frame, ownership.ring_slot, unmap_status);
                fflush(stdout);
            }
        }
        if (ownership.ring_slot == 0) {
            m_slot0_mapped_handle = nullptr;
            m_slot0_map_state = "UNMAPPED";
        }
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
    if (!m_configured) return false;
    if (!m_video_opened && m_interaction_stage > 2) return false;

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

    if (m_interaction_stage >= 1 && m_interaction_stage <= 5) {
        // The ladder stages intentionally avoid the normal NVENC frame loop.
        // They still use the production-created D3D11/D2D/decoder/VP objects
        // selected by the stage, and finish through the same progress API.
        RunInteractionLadderFrames(output_path, start_frame, frame_count, include_hud);
        if (hOutputFile != INVALID_HANDLE_VALUE) CloseHandle(hOutputFile);
        return;
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

    // In the single-thread diagnostic, defer indicator resource creation
    // until this worker owns the D2D context.
    EnsureDeferredIndicatorResources();
    RecordD2DThread("worker_loop_begin", UINT32_MAX);

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
        m_interaction_current_frame = frame_idx;
        int slot = (int)(frame_idx % m_config.ring_size);
        const bool single_hud = IsSingleHudDiagnostic();
        const int hud_pool = m_determinism_diag ? DeterminismHudPoolSize() : 0;
        const int hud_slot = hud_pool > 0 ? (int)(frame_idx % hud_pool) : (single_hud ? 0 : slot);
        m_diag_hud_slot_override = hud_pool > 0 ? hud_slot : -1;
        int slot_in_flight_before = (slot >= 0 && slot < (int)m_slot_in_flight.size()) ? m_slot_in_flight[slot] : -1;
        m_ring_release_diags.clear();

        HRESULT hud_q_status_before = S_OK;
        HRESULT vp_q_status_before = S_OK;
        if (hud_slot < (int)m_ring_hud_queries.size() && m_ring_hud_queries[hud_slot]) {
            BOOL done = FALSE;
            HRESULT hrQ = m_pContext->GetData(m_ring_hud_queries[hud_slot], &done, sizeof(BOOL), D3D11_ASYNC_GETDATA_DONOTFLUSH);
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

        // A slot can be free from NVENC ownership while the D3D11 command
        // stream is still reading its HUD/input or output resource.  Do not
        // begin the next D2D draw until both per-slot fences report TRUE.
        if (hud_slot < (int)m_ring_hud_queries.size() && m_ring_hud_queries[hud_slot] &&
            hud_q_status_before == S_FALSE) {
            const double wait_t0 = TelemHudProfile::NowSeconds();
            BOOL done = FALSE;
            while (!done) {
                HRESULT qhr = m_pContext->GetData(
                    m_ring_hud_queries[hud_slot], &done, sizeof(BOOL), 0
                );
                if (FAILED(qhr)) break;
                YieldProcessor();
            }
            TelemHudProfile::Record("wait", "getdata_hud", "slot_reuse",
                                    (TelemHudProfile::NowSeconds() - wait_t0) * 1000.0);
        }
        if (slot < (int)m_ring_vp_queries.size() && m_ring_vp_queries[slot] &&
            vp_q_status_before == S_FALSE) {
            const double wait_t0 = TelemHudProfile::NowSeconds();
            BOOL done = FALSE;
            while (!done) {
                HRESULT qhr = m_pContext->GetData(
                    m_ring_vp_queries[slot], &done, sizeof(BOOL), 0
                );
                if (FAILED(qhr)) break;
                YieldProcessor();
            }
            TelemHudProfile::Record("wait", "getdata_vp", "slot_reuse",
                                    (TelemHudProfile::NowSeconds() - wait_t0) * 1000.0);
        }
        if (single_hud && i > 0 && !m_ring_vp_queries.empty() && m_ring_vp_queries[0]) {
            const double wait_t0 = TelemHudProfile::NowSeconds();
            BOOL done = FALSE;
            while (!done) {
                HRESULT qhr = m_pContext->GetData(m_ring_vp_queries[0], &done, sizeof(BOOL), 0);
                if (FAILED(qhr)) break;
                YieldProcessor();
            }
            TelemHudProfile::Record("wait", "getdata_vp", "single_hud_reuse",
                                    (TelemHudProfile::NowSeconds() - wait_t0) * 1000.0);
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
        ID2D1DeviceContext* frame_d2d_context = nullptr;
        ID2D1Bitmap1* frame_d2d_target = nullptr;
        ID2D1DeviceContext* saved_d2d_context = nullptr;
        const bool dynamic_control = include_hud && m_determinism_diag && IsD3D11DynamicControlDiagnostic();
        const bool copy_out_control = include_hud && m_determinism_diag && IsCopyOutControlDiagnostic();
        bool static_hud = false;
        bool mode_fresh_all = false;
        std::string d2d_mode = DeterminismD2DMode();
        const bool separate_nvenc_hud = m_hud_separate_device &&
                                        m_hud_separate_mode == "NVENC";
        if (include_hud) {
            if (separate_nvenc_hud) {
                hr_d2d = RenderSeparateHudFullFrame(cur_state, frame_idx) ? S_OK : E_FAIL;
                // The dedicated FULL_HUD stage already readbacks the B target
                // under its non-shared mutex contract.  NVENC keeps key=1 on
                // the shared resource for A's VP handoff, so a second B-side
                // CPU readback here would be an illegal ownership transition.
                const bool b_present = SUCCEEDED(hr_d2d);
                RecordDeterminismStage(frame_idx, "HUD_AFTER_D2D", b_present, hr_d2d);
                hud_query_done = b_present;
            } else {
            // Render the HUD into its slot-owned BGRA texture and hand it to
            // the established two-stream VideoProcessor compositor.
            static_hud = IsStaticHudDiagnostic();
            mode_fresh_all = d2d_mode == "F" || IsFreshResourceDiagnostic();
            const bool mode_fresh_target = d2d_mode == "T" || d2d_mode == "TV";
            const bool mode_fresh_view = d2d_mode == "V" || d2d_mode == "TV";
            const bool mode_is_isolation = m_determinism_diag && d2d_mode != "P";
            const bool use_fresh_context = m_d2d_fresh_context && !mode_fresh_all && !mode_is_isolation;
            if (dynamic_control) {
                hr_d2d = RenderD3D11DynamicHud(frame_idx, hud_slot) ? S_OK : E_FAIL;
            } else if (copy_out_control) {
                if (!PrepareCopyOutDrawTexture()) {
                    hr_d2d = E_FAIL;
                } else {
                    // Strict copy-out: D2D writes only the draw texture.  It
                    // is never exposed as the VP input view.
                    hr_d2d = RenderHud(cur_state, hud_slot, m_diag_copy_draw_target);
                }
            } else if (use_fresh_context) {
                if (!CreateFreshD2DContextForTexture(m_ring_hud_textures[hud_slot],
                                                     &frame_d2d_context, &frame_d2d_target)) {
                    hr_d2d = E_FAIL;
                } else {
                    saved_d2d_context = m_pD2DContext;
                    m_pD2DContext = frame_d2d_context;
                    hr_d2d = RenderHud(cur_state, hud_slot, frame_d2d_target);
                    m_pD2DContext = saved_d2d_context;
                    saved_d2d_context = nullptr;
                }
            } else if (mode_fresh_all) {
                ReleaseFreshHudResources();
                if (!CreateFreshHudResources(&m_diag_fresh_hud_texture, &m_diag_fresh_hud_target, &m_diag_fresh_hud_view)) {
                    hr_d2d = E_FAIL;
                } else {
                    hr_d2d = RenderHud(cur_state, 0, m_diag_fresh_hud_target);
                }
            } else if (mode_is_isolation && (mode_fresh_target || mode_fresh_view)) {
                ReleaseFreshHudResources();
                ID3D11Texture2D* persistent_texture = m_ring_hud_textures[hud_slot];
                ID2D1Bitmap1** target_out = mode_fresh_target ? &m_diag_fresh_hud_target : nullptr;
                ID3D11VideoProcessorInputView** view_out = mode_fresh_view ? &m_diag_fresh_hud_view : nullptr;
                if (!CreateFreshHudTargetForTexture(persistent_texture, target_out, view_out)) {
                    hr_d2d = E_FAIL;
                } else {
                    hr_d2d = RenderHud(cur_state, hud_slot, m_diag_fresh_hud_target);
                }
            } else if (!static_hud || i == 0) {
                hr_d2d = RenderHud(cur_state, static_hud ? 0 : hud_slot);
            } else {
                hr_d2d = S_OK;
                hud_query_done = true;
            }
            // GPU Fence: ensure Direct2D rendering to the persistent BGRA
            // composite is complete before VideoProcessor converts it to P010.
            // before VideoProcessorBlt samples it on the video processing engine
            if ((!static_hud || i == 0) && hud_slot < (int)m_ring_hud_queries.size() && m_ring_hud_queries[hud_slot]) {
                RecordD3D11ContextOperation("End_query_HUD", frame_idx,
                                            m_ring_hud_queries[hud_slot], hud_slot);
                m_pContext->End(m_ring_hud_queries[hud_slot]);
                RecordD3D11ContextOperation("Flush_HUD_query", frame_idx, nullptr, hud_slot);
                m_pContext->Flush();
                const double wait_t0 = TelemHudProfile::NowSeconds();
                BOOL done = FALSE;
                while (!done) {
                    HRESULT qhr = m_pContext->GetData(
                        m_ring_hud_queries[hud_slot], &done, sizeof(BOOL), 0
                    );
                    RecordD3D11ContextOperation("GetData_HUD", frame_idx,
                                                m_ring_hud_queries[hud_slot], hud_slot);
                    if (FAILED(qhr)) {
                        break;
                    }
                    YieldProcessor();
                }
                TelemHudProfile::Record("wait", "getdata_hud", "hud_complete",
                                        (TelemHudProfile::NowSeconds() - wait_t0) * 1000.0);
                hud_query_done = (done == TRUE);
            }
            if (copy_out_control && !dynamic_control && SUCCEEDED(hr_d2d)) {
                ID3D11Texture2D* draw_texture = m_diag_copy_draw_texture;
                if (!PrepareCopyOutHudTexture(draw_texture)) {
                    hr_d2d = E_FAIL;
                } else {
                    m_pContext->CopyResource(m_diag_copy_hud_texture, draw_texture);
                    RecordD3D11ContextOperation("CopyResource_HUD_DRAW_TO_VP", frame_idx,
                                                draw_texture, hud_slot);
                    RecordD3D11ContextOperation("Flush_HUD_DRAW_TO_VP", frame_idx,
                                                m_diag_copy_hud_texture, hud_slot);
                    m_pContext->Flush();
                    DumpD3D11InfoQueue("CopyResource_HUD_DRAW_TO_VP", frame_idx);
                }
            }
            if (m_determinism_diag && IsDeterminismProbeFrame(frame_idx)) {
                ID3D11Texture2D* hud_texture = copy_out_control
                    ? m_diag_copy_draw_texture
                    : (mode_fresh_all ? m_diag_fresh_hud_texture : m_ring_hud_textures[static_hud ? 0 : hud_slot]);
                bool hud_present = ReadbackHudMarker(hud_texture, false);
                RecordDeterminismStage(frame_idx, "HUD_AFTER_D2D", hud_present, hr_d2d);
                std::string counts_path = m_determinism_dir + "\\draw_call_counts.csv";
                FILE* counts = fopen(counts_path.c_str(), "a+");
                if (counts) {
                    fseek(counts, 0, SEEK_END);
                    if (ftell(counts) == 0) fprintf(counts, "frame,mode,text_draws,bitmap_draws,geometry_draws,chart_primitives,draw_count_expected,draw_count_actual\n");
                    uint32_t text_draws = 0, bitmap_draws = 0, geometry_draws = 0, chart_primitives = 0;
                    for (const auto& ind : m_indicators) {
                        auto type = ind->GetType();
                        if (type == TELEM_IND_TEXT || type == TELEM_IND_TIME_DISPLAY) text_draws++;
                        else if (type == TELEM_IND_MAP) bitmap_draws++;
                        else if (type == TELEM_IND_CHART) chart_primitives++;
                        else geometry_draws++;
                    }
                    uint32_t expected = text_draws + bitmap_draws + geometry_draws + chart_primitives + (m_determinism_diag ? 1u : 0u);
                    fprintf(counts, "%u,%s,%u,%u,%u,%u,%u,%u\n", frame_idx, d2d_mode.c_str(), text_draws, bitmap_draws, geometry_draws, chart_primitives, expected, SUCCEEDED(hr_d2d) ? expected : 0u);
                    fclose(counts);
                }
                if (frame_idx == 0 && !m_determinism_dir.empty() && hud_texture) {
                    std::string png_path = m_determinism_dir + "\\hud_after_d2d_000.png";
                    std::wstring wpath(png_path.begin(), png_path.end());
                    SaveTextureToPng(hud_texture, wpath.c_str());
                }
            }
            }
        }
        double thud1 = GetQpcTimeSec();
        t_hud_total += (thud1 - thud0);

        // 4. VideoProcessor Composite
        double tvp0 = GetQpcTimeSec();

        if (include_hud) {
            RecordTargetBinding(frame_idx, "target_before_VP");
        }

        bool comp_ok = false;
        bool separate_nvenc_mutex_held = false;
        ID3D11VideoProcessorInputView* separate_saved_hud_view = nullptr;
        if (include_hud) {
            if (separate_nvenc_hud) {
                const double consume_t0 = TelemHudProfile::NowSeconds();
                HRESULT consume_hr = m_hud_a_mutex ? m_hud_a_mutex->AcquireSync(1, INFINITE) : E_FAIL;
                TelemHudProfile::Record("wait", "device_a_consume_wait", "nvenc",
                                        (TelemHudProfile::NowSeconds() - consume_t0) * 1000.0);
                if (SUCCEEDED(consume_hr) &&
                    slot < (int)m_ring_vp_in_view_huds.size()) {
                    separate_nvenc_mutex_held = true;
                    separate_saved_hud_view = m_ring_vp_in_view_huds[slot];
                    m_ring_vp_in_view_huds[slot] = m_hud_a_shared_view;
                    comp_ok = Composite(pVideoInView, slot, true);
                    m_ring_vp_in_view_huds[slot] = separate_saved_hud_view;
                }
            } else {
                comp_ok = Composite(pVideoInView, slot, true);
            }
        } else {
            comp_ok = Composite(pVideoInView, slot, false);
        }
        DumpD3D11InfoQueue("VideoProcessorBlt", frame_idx);
        if (i >= 115 && i <= 122) {
            printf("[FRAME %u DIAG] slot=%d hr_d2d=0x%08X comp_ok=%d\n", i, slot, (unsigned int)hr_d2d, comp_ok ? 1 : 0);
            fflush(stdout);
        }
        double tvp1 = GetQpcTimeSec();
        t_vp_total += (tvp1 - tvp0);

        // GPU Fence: ensure VideoProcessorBlt writes to m_ring_nv12_textures[slot] are complete before NVENC reads it
        if (slot < (int)m_ring_vp_queries.size() && m_ring_vp_queries[slot]) {
            RecordD3D11ContextOperation("End_query_VP", frame_idx,
                                        m_ring_vp_queries[slot], slot);
            m_pContext->End(m_ring_vp_queries[slot]);
            RecordD3D11ContextOperation("Flush_VP_query", frame_idx, nullptr, slot);
            m_pContext->Flush();
            const double wait_t0 = TelemHudProfile::NowSeconds();
            BOOL done = FALSE;
            while (!done) {
                HRESULT qhr = m_pContext->GetData(
                    m_ring_vp_queries[slot], &done, sizeof(BOOL), 0
                );
                RecordD3D11ContextOperation("GetData_VP", frame_idx,
                                            m_ring_vp_queries[slot], slot);
                if (FAILED(qhr)) {
                    break;
                }
                YieldProcessor();
            }
            TelemHudProfile::Record("wait", "getdata_vp", "vp_complete",
                                    (TelemHudProfile::NowSeconds() - wait_t0) * 1000.0);
        }
        // The copy-out texture is used only by this frame's VP submission.
        // Release it after the completion query, never while the VP may still
        // sample it.
        ReleaseCopyOutHudTexture();
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
        if (m_determinism_diag && include_hud && IsDeterminismProbeFrame(frame_idx)) {
            bool vp_present = ReadbackHudMarker(m_ring_nv12_textures[slot], true);
            RecordDeterminismStage(frame_idx, "HUD_AFTER_VP", vp_present, m_last_vp_blt_hr);
            RecordDeterminismStage(frame_idx, "HUD_BEFORE_NVENC", vp_present, m_last_vp_blt_hr);
        }
        if (separate_nvenc_mutex_held && m_hud_a_mutex) {
            const double consume_release_t0 = TelemHudProfile::NowSeconds();
            m_hud_a_mutex->ReleaseSync(0);
            TelemHudProfile::Record("wait", "device_a_consume_release", "nvenc",
                                    (TelemHudProfile::NowSeconds() - consume_release_t0) * 1000.0);
            separate_nvenc_mutex_held = false;
        }
        if (frame_d2d_context || frame_d2d_target) {
            SafeRelease(frame_d2d_target);
            SafeRelease(frame_d2d_context);
        }
        if ((IsFreshResourceDiagnostic() || DeterminismD2DMode() != "P") && !IsHoldHudUntilEncodeDiagnostic()) {
            // The VP completion query above is the last consumer of the
            // per-frame HUD view/resource.
            ReleaseFreshHudResources();
        }

        // 5 & 6. NVENC Encode & Bitstream
        double submit_sec = 0.0, bs_sec = 0.0;
        TelemEncodeDiagInfo diag{};
        bool enc_ok = EncodeFrame(slot, i, frame_idx, hOutputFile, submit_sec, bs_sec, &diag);
        t_nvenc_total += submit_sec;
        t_bs_total += bs_sec;
        if (enc_ok && m_determinism_serialized) {
            while (!m_in_flight_bitstream_buffers.empty()) {
                if (!ProcessBitstreamQueue(hOutputFile, true, nullptr)) {
                    enc_ok = false;
                    break;
                }
            }
        }
        if (IsHoldHudUntilEncodeDiagnostic()) {
            ReleaseFreshHudResources();
        }
        m_diag_hud_slot_override = -1;

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
        RecordD3D11ContextOperation("Flush_frame_end", frame_idx, nullptr, slot);
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

    TelemHudProfile::Dump();
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
    ReleaseFreshHudResources();
    ReleaseCopyOutHudTexture();
    CloseDeterminismDiagnostics();
    CloseDecoder();

    for (auto* pView : m_ring_vp_out_views) SafeRelease(pView);
    for (auto* pView : m_ring_vp_bgra_out_views) SafeRelease(pView);
    for (auto* pTex : m_ring_nv12_textures) SafeRelease(pTex);
    for (auto* pInView : m_ring_vp_in_view_huds) SafeRelease(pInView);
    for (auto* pInView : m_ring_vp_in_view_bgra_composites) SafeRelease(pInView);
    for (auto* pTarget : m_ring_d2d_bitmap_targets) SafeRelease(pTarget);
    for (auto* pTarget : m_ring_d2d_bgra_composite_targets) SafeRelease(pTarget);
    for (auto* pTex : m_ring_hud_textures) SafeRelease(pTex);
    for (auto* pTex : m_ring_hud_resolved_textures) SafeRelease(pTex);
    for (auto* pTex : m_ring_bgra_composite_textures) SafeRelease(pTex);
    for (auto* pSource : m_ring_d2d_bgra_video_sources) SafeRelease(pSource);
    for (auto* pQuery : m_ring_hud_queries) SafeRelease(pQuery);
    for (auto* pQuery : m_ring_vp_queries) SafeRelease(pQuery);
    m_ring_vp_out_views.clear();
    m_ring_vp_bgra_out_views.clear();
    m_ring_nv12_textures.clear();
    m_ring_vp_in_view_huds.clear();
    m_ring_vp_in_view_bgra_composites.clear();
    m_ring_d2d_bitmap_targets.clear();
    m_ring_d2d_bgra_composite_targets.clear();
    m_ring_hud_textures.clear();
    m_ring_hud_resolved_textures.clear();
    m_ring_bgra_composite_textures.clear();
    m_ring_d2d_bgra_video_sources.clear();
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

    SafeRelease(m_hud_a_shared_view);
    SafeRelease(m_hud_a_mutex);
    SafeRelease(m_hud_a_shared_texture);
    SafeRelease(m_hud_a_shared_staging);
    SafeRelease(m_hud_a_shared_query);
    if (m_hud_shared_handle) {
        CloseHandle(m_hud_shared_handle);
        m_hud_shared_handle = nullptr;
    }
    SafeRelease(m_hud_b_mutex);
    SafeRelease(m_hud_b_target);
    SafeRelease(m_hud_b_texture);
    SafeRelease(m_hud_b_staging);
    SafeRelease(m_hud_b_query);
    SafeRelease(m_hud_b_brush);
    SafeRelease(m_hud_b_brush_text_muted);
    SafeRelease(m_hud_b_brush_cyan);
    SafeRelease(m_hud_b_brush_coral);
    SafeRelease(m_hud_b_brush_card_bg);
    SafeRelease(m_hud_b_brush_card_border);
    SafeRelease(m_hud_b_fmt_time);
    SafeRelease(m_hud_b_fmt_speed_val);
    SafeRelease(m_hud_b_fmt_speed_unit);
    SafeRelease(m_hud_b_fmt_hr_val);
    SafeRelease(m_hud_b_fmt_hr_unit);
    SafeRelease(m_hud_b_fmt_label);
    SafeRelease(m_hud_b_fmt);
    SafeRelease(m_hud_b_dwrite_factory);
    SafeRelease(m_hud_b_d2d_context);
    SafeRelease(m_hud_b_d2d_device);
    SafeRelease(m_hud_b_dxgi_device);
    SafeRelease(m_hud_b_context);
    SafeRelease(m_hud_b_device);

    SafeRelease(m_pDWriteFactory);
    SafeRelease(m_pD2DContext);
    SafeRelease(m_pD2DDevice);

    SafeRelease(m_pContext);
    SafeRelease(m_diag_info_queue);
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
