#include "gpmf_extractor.h"

#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <ctime>
#include <algorithm>
#include <vector>

#include "GPMF_parser.h"
#include "demo/GPMF_mp4reader.h"

namespace {

constexpr double GPS_EPOCH_UNIX = 946684800.0; // 2000-01-01 00:00:00 UTC
constexpr double QUICKTIME_EPOCH_OFFSET = 2082844800.0; // 1904-01-01 to 1970-01-01
constexpr double PI = 3.14159265358979323846;
constexpr double DEG2RAD = PI / 180.0;
constexpr double RAD2DEG = 180.0 / PI;
constexpr double EARTH_RADIUS_M = 6371000.0;

struct VectorBlock {
    uint64_t stmp = 0;
    uint32_t tsmp = 0;
    std::vector<Vector3> samples;
};

struct IntBlock {
    uint64_t stmp = 0;
    uint32_t tsmp = 0;
    std::vector<int32_t> samples;
};

struct DoubleBlock {
    uint64_t stmp = 0;
    uint32_t tsmp = 0;
    std::vector<double> samples;
};

double HaversineM(double lat1, double lon1, double lat2, double lon2) {
    double phi1 = lat1 * DEG2RAD;
    double phi2 = lat2 * DEG2RAD;
    double dphi = (lat2 - lat1) * DEG2RAD;
    double dlambda = (lon2 - lon1) * DEG2RAD;
    double a = std::sin(dphi * 0.5) * std::sin(dphi * 0.5) +
               std::cos(phi1) * std::cos(phi2) *
               std::sin(dlambda * 0.5) * std::sin(dlambda * 0.5);
    double c = 2.0 * std::atan2(std::sqrt(a), std::sqrt(1.0 - a));
    return EARTH_RADIUS_M * c;
}

double CalculateBearing(double lat1, double lon1, double lat2, double lon2) {
    double phi1 = lat1 * DEG2RAD;
    double phi2 = lat2 * DEG2RAD;
    double dlambda = (lon2 - lon1) * DEG2RAD;
    double y = std::sin(dlambda) * std::cos(phi2);
    double x = std::cos(phi1) * std::sin(phi2) -
               std::sin(phi1) * std::cos(phi2) * std::cos(dlambda);
    double b = std::atan2(y, x) * RAD2DEG;
    return std::fmod(b + 360.0, 360.0);
}

// Format unix epoch seconds to ISO UTC datetime string "YYYY-MM-DD HH:MM:SS.mmm"
std::string FormatUtcIso(double ts) {
    if (ts <= 0.0) return "";
    time_t sec = (time_t)std::floor(ts);
    int ms = (int)std::round((ts - std::floor(ts)) * 1000.0);
    if (ms >= 1000) { sec += 1; ms -= 1000; }
    tm tm_utc;
#ifdef _WIN32
    gmtime_s(&tm_utc, &sec);
#else
    gmtime_r(&sec, &tm_utc);
#endif
    char buf[64];
    std::snprintf(buf, sizeof(buf), "%04d-%02d-%02d %02d:%02d:%02d.%03d",
                  tm_utc.tm_year + 1900, tm_utc.tm_mon + 1, tm_utc.tm_mday,
                  tm_utc.tm_hour, tm_utc.tm_min, tm_utc.tm_sec, ms);
    return std::string(buf);
}

} // anonymous namespace

GpmfResult ExtractGpmfData(const std::string& mp4_path) {
    GpmfResult result;

    size_t mp4 = OpenMP4Source((char*)mp4_path.c_str(), MOV_GPMF_TRAK_TYPE, MOV_GPMF_TRAK_SUBTYPE, 0);
    if (!mp4) {
        result.success = false;
        result.error_message = "Failed to open MP4 GPMF track in: " + mp4_path;
        return result;
    }

    uint32_t payloads = GetNumberPayloads(mp4);
    result.payload_count = payloads;
    if (payloads == 0) {
        CloseSource(mp4);
        result.success = false;
        result.error_message = "No GPMF payloads found in: " + mp4_path;
        return result;
    }

    result.duration_sec = GetDuration(mp4);

    std::vector<GpsPoint> raw_gps;
    std::vector<VectorBlock> accl_blocks;
    std::vector<VectorBlock> gyro_blocks;
    std::vector<VectorBlock> grav_blocks;
    std::vector<VectorBlock> cori_blocks;
    std::vector<IntBlock> isoe_blocks;
    std::vector<IntBlock> shut_blocks;
    std::vector<DoubleBlock> tmpc_blocks;

    uint32_t raw_accl_tmpc_count = 0;
    uint32_t raw_gyro_tmpc_count = 0;

    double first_gpsu_ts = 0.0;
    // The first valid GPS9 sample may occur well after video frame 0 (GPS
    // lock).  Keep its absolute time and GPMF-local STMP position so the
    // anchor remains on the video timeline instead of shifting all dynamic
    // streams to the GPS-lock instant.
    double first_gps9_abs_ts = 0.0;
    double first_gps9_local_s = 0.0;
    char camera_name[64] = {0};

    size_t res = 0;
    GPMF_stream ms;

    for (uint32_t p = 0; p < payloads; p++) {
        uint32_t payloadsize = GetPayloadSize(mp4, p);
        res = GetPayloadResource(mp4, res, payloadsize);
        uint32_t* payload = GetPayload(mp4, res, p);
        if (!payload) continue;

        if (GPMF_Init(&ms, payload, payloadsize) != GPMF_OK) continue;

        // Camera name
        if (camera_name[0] == 0) {
            GPMF_DeviceName(&ms, camera_name, sizeof(camera_name));
        }

        DoubleBlock payload_tmpc_accl;
        bool has_tmpc_accl = false;
        DoubleBlock payload_tmpc_gyro;
        bool has_tmpc_gyro = false;
        DoubleBlock payload_tmpc_standalone;
        bool has_tmpc_standalone = false;

        // Iterate through all STRM blocks
        while (GPMF_FindNext(&ms, STR2FOURCC("STRM"), (GPMF_LEVELS)(GPMF_RECURSE_LEVELS | GPMF_TOLERANT)) == GPMF_OK) {
            GPMF_stream strm = ms;
            if (GPMF_SeekToSamples(&strm) == GPMF_OK) {
                uint32_t key = GPMF_Key(&strm);
                uint32_t samples = GPMF_PayloadSampleCount(&strm);
                uint32_t elements = GPMF_ElementsInStruct(&strm);

                if (samples == 0) continue;

                // 1. GPS9
                if (key == STR2FOURCC("GPS9")) {
                    GPMF_stream find_stream = strm;
                    uint64_t stmp = 0;
                    if (GPMF_FindPrev(&find_stream, STR2FOURCC("STMP"), GPMF_CURRENT_LEVEL) == GPMF_OK) {
                        stmp = BYTESWAP64(*(uint64_t*)GPMF_RawData(&find_stream));
                    }
                    std::vector<double> buf(samples * elements);
                    if (GPMF_ScaledData(&strm, buf.data(), (uint32_t)(buf.size() * sizeof(double)), 0, samples, GPMF_TYPE_DOUBLE) == GPMF_OK) {
                        for (uint32_t s = 0; s < samples; s++) {
                            double lat = buf[s * elements + 0];
                            double lon = buf[s * elements + 1];
                            double alt = buf[s * elements + 2];
                            double s2d = buf[s * elements + 3] * 3.6; // m/s -> km/h
                            double s3d = buf[s * elements + 4] * 3.6;
                            double days = buf[s * elements + 5];
                            double secs = buf[s * elements + 6];
                            double dop = buf[s * elements + 7];
                            double fix = buf[s * elements + 8];

                            // GoPro emits pre-GPS-lock GPS9 samples as (0,0).
                            // They are numerically in range but carry no
                            // absolute position/time and must not become the
                            // global telemetry anchor (GX010246 exposes this
                            // as stale 2021 blocks before the real 2026 data).
                            if (lat >= -90.0 && lat <= 90.0 && lon >= -180.0 && lon <= 180.0 &&
                                !(lat == 0.0 && lon == 0.0)) {
                                double ts = GPS_EPOCH_UNIX + days * 86400.0 + secs;
                                if (first_gps9_abs_ts <= 0.0) {
                                    first_gps9_abs_ts = ts;
                                    first_gps9_local_s = (double)stmp * 1e-6 + (double)s * 0.1;
                                }
                                raw_gps.push_back({ts, lat, lon, alt, s2d, s3d, dop, (int32_t)fix});
                            }
                        }
                    }
                }
                // 2. GPS5 (Hero 5/6 legacy)
                else if (key == STR2FOURCC("GPS5")) {
                    // Check GPSU in same STRM
                    GPMF_stream find_stream = strm;
                    if (first_gpsu_ts <= 0.0 && GPMF_FindPrev(&find_stream, STR2FOURCC("GPSU"), GPMF_CURRENT_LEVEL) == GPMF_OK) {
                        char* u = (char*)GPMF_RawData(&find_stream);
                        int year, month, day, hour, min, sec;
                        float fsec = 0;
                        if (std::sscanf(u, "%02d%02d%02d%02d%02d%f", &year, &month, &day, &hour, &min, &fsec) == 6) {
                            tm t{};
                            t.tm_year = year + 100; // 2000+
                            t.tm_mon = month - 1;
                            t.tm_mday = day;
                            t.tm_hour = hour;
                            t.tm_min = min;
                            t.tm_sec = (int)fsec;
#ifdef _WIN32
                            first_gpsu_ts = (double)_mkgmtime(&t) + (fsec - (int)fsec);
#else
                            first_gpsu_ts = (double)timegm(&t) + (fsec - (int)fsec);
#endif
                        }
                    }
                    double in_time = 0, out_time = 0;
                    GetPayloadTime(mp4, p, &in_time, &out_time);
                    double base_time = first_gpsu_ts > 0.0 ? (first_gpsu_ts + in_time) : in_time;
                    double dt_step = samples > 1 ? ((double)(out_time - in_time) / samples) : 0.05;

                    std::vector<double> buf(samples * elements);
                    if (GPMF_ScaledData(&strm, buf.data(), (uint32_t)(buf.size() * sizeof(double)), 0, samples, GPMF_TYPE_DOUBLE) == GPMF_OK) {
                        for (uint32_t s = 0; s < samples; s++) {
                            double lat = buf[s * elements + 0];
                            double lon = buf[s * elements + 1];
                            double alt = buf[s * elements + 2];
                            double s2d = buf[s * elements + 3] * 3.6;
                            double s3d = buf[s * elements + 4] * 3.6;
                            if (lat >= -90.0 && lat <= 90.0 && lon >= -180.0 && lon <= 180.0) {
                                double ts = base_time + s * dt_step;
                                raw_gps.push_back({ts, lat, lon, alt, s2d, s3d, 1.0, 3});
                            }
                        }
                    }
                }
                // 3. Motion vectors: ACCL, GYRO, GRAV, CORI
                else if ((key == STR2FOURCC("ACCL") || key == STR2FOURCC("GYRO") ||
                          key == STR2FOURCC("GRAV") || key == STR2FOURCC("CORI")) && elements >= 3) {
                    GPMF_stream find_stream = strm;
                    uint64_t stmp = 0;
                    uint32_t tsmp = 0;
                    if (GPMF_FindPrev(&find_stream, STR2FOURCC("STMP"), GPMF_CURRENT_LEVEL) == GPMF_OK) {
                        stmp = BYTESWAP64(*(uint64_t*)GPMF_RawData(&find_stream));
                    }
                    find_stream = strm;
                    if (GPMF_FindPrev(&find_stream, STR2FOURCC("TSMP"), GPMF_CURRENT_LEVEL) == GPMF_OK) {
                        tsmp = BYTESWAP32(*(uint32_t*)GPMF_RawData(&find_stream));
                    }
                    std::vector<double> buf(samples * elements);
                    if (GPMF_ScaledData(&strm, buf.data(), (uint32_t)(buf.size() * sizeof(double)), 0, samples, GPMF_TYPE_DOUBLE) == GPMF_OK) {
                        VectorBlock block;
                        block.stmp = stmp;
                        block.tsmp = tsmp;
                        block.samples.reserve(samples);
                        for (uint32_t s = 0; s < samples; s++) {
                            // GoPro raw coordinate order is ZXY -> convert to canonical XYZ:
                            // canonical.x = raw.y, canonical.y = raw.z, canonical.z = raw.x
                            double rx = buf[s * elements + 0];
                            double ry = buf[s * elements + 1];
                            double rz = buf[s * elements + 2];
                            block.samples.push_back({ry, rz, rx});
                        }
                        if (key == STR2FOURCC("ACCL")) {
                            accl_blocks.push_back(std::move(block));
                            // Extract canonical TMPC from ACCL stream (raw 32-bit big-endian float; do not scale by ACCL SCAL)
                            GPMF_stream find_tmpc = strm;
                            if (GPMF_FindPrev(&find_tmpc, STR2FOURCC("TMPC"), GPMF_CURRENT_LEVEL) == GPMF_OK) {
                                if (GPMF_RawDataSize(&find_tmpc) >= sizeof(float)) {
                                    uint32_t raw_bits = BYTESWAP32(*(uint32_t*)GPMF_RawData(&find_tmpc));
                                    float temp_c = 0.0f;
                                    std::memcpy(&temp_c, &raw_bits, sizeof(float));
                                    payload_tmpc_accl.stmp = stmp;
                                    payload_tmpc_accl.tsmp = tsmp;
                                    payload_tmpc_accl.samples.clear();
                                    payload_tmpc_accl.samples.push_back((double)temp_c);
                                    has_tmpc_accl = true;
                                    raw_accl_tmpc_count++;
                                }
                            }
                        }
                        else if (key == STR2FOURCC("GYRO")) {
                            gyro_blocks.push_back(std::move(block));
                            // Extract duplicate/fallback TMPC from GYRO stream
                            GPMF_stream find_tmpc = strm;
                            if (GPMF_FindPrev(&find_tmpc, STR2FOURCC("TMPC"), GPMF_CURRENT_LEVEL) == GPMF_OK) {
                                if (GPMF_RawDataSize(&find_tmpc) >= sizeof(float)) {
                                    uint32_t raw_bits = BYTESWAP32(*(uint32_t*)GPMF_RawData(&find_tmpc));
                                    float temp_c = 0.0f;
                                    std::memcpy(&temp_c, &raw_bits, sizeof(float));
                                    payload_tmpc_gyro.stmp = stmp;
                                    payload_tmpc_gyro.tsmp = tsmp;
                                    payload_tmpc_gyro.samples.clear();
                                    payload_tmpc_gyro.samples.push_back((double)temp_c);
                                    has_tmpc_gyro = true;
                                    raw_gyro_tmpc_count++;
                                }
                            }
                        }
                        else if (key == STR2FOURCC("GRAV")) grav_blocks.push_back(std::move(block));
                        else if (key == STR2FOURCC("CORI")) cori_blocks.push_back(std::move(block));
                    }
                }
                // 4. ISOE
                else if (key == STR2FOURCC("ISOE")) {
                    GPMF_stream find_stream = strm;
                    uint64_t stmp = 0;
                    uint32_t tsmp = 0;
                    if (GPMF_FindPrev(&find_stream, STR2FOURCC("STMP"), GPMF_CURRENT_LEVEL) == GPMF_OK) {
                        stmp = BYTESWAP64(*(uint64_t*)GPMF_RawData(&find_stream));
                    }
                    find_stream = strm;
                    if (GPMF_FindPrev(&find_stream, STR2FOURCC("TSMP"), GPMF_CURRENT_LEVEL) == GPMF_OK) {
                        tsmp = BYTESWAP32(*(uint32_t*)GPMF_RawData(&find_stream));
                    }
                    std::vector<double> buf(samples * elements);
                    if (GPMF_ScaledData(&strm, buf.data(), (uint32_t)(buf.size() * sizeof(double)), 0, samples, GPMF_TYPE_DOUBLE) == GPMF_OK) {
                        IntBlock block;
                        block.stmp = stmp;
                        block.tsmp = tsmp;
                        for (uint32_t s = 0; s < samples; s++) {
                            block.samples.push_back((int32_t)std::round(buf[s * elements]));
                        }
                        isoe_blocks.push_back(std::move(block));
                    }
                }
                // 5. SHUT
                else if (key == STR2FOURCC("SHUT")) {
                    GPMF_stream find_stream = strm;
                    uint64_t stmp = 0;
                    uint32_t tsmp = 0;
                    if (GPMF_FindPrev(&find_stream, STR2FOURCC("STMP"), GPMF_CURRENT_LEVEL) == GPMF_OK) {
                        stmp = BYTESWAP64(*(uint64_t*)GPMF_RawData(&find_stream));
                    }
                    find_stream = strm;
                    if (GPMF_FindPrev(&find_stream, STR2FOURCC("TSMP"), GPMF_CURRENT_LEVEL) == GPMF_OK) {
                        tsmp = BYTESWAP32(*(uint32_t*)GPMF_RawData(&find_stream));
                    }
                    std::vector<double> buf(samples * elements);
                    if (GPMF_ScaledData(&strm, buf.data(), (uint32_t)(buf.size() * sizeof(double)), 0, samples, GPMF_TYPE_DOUBLE) == GPMF_OK) {
                        IntBlock block;
                        block.stmp = stmp;
                        block.tsmp = tsmp;
                        for (uint32_t s = 0; s < samples; s++) {
                            double val = buf[s * elements];
                            int32_t denom = val > 1e-9 ? (int32_t)std::round(1.0 / val) : 0;
                            block.samples.push_back(denom);
                        }
                        shut_blocks.push_back(std::move(block));
                    }
                }
                // 6. TMPC (standalone stream fallback)
                else if (key == STR2FOURCC("TMPC")) {
                    GPMF_stream find_stream = strm;
                    uint64_t stmp = 0;
                    uint32_t tsmp = 0;
                    if (GPMF_FindPrev(&find_stream, STR2FOURCC("STMP"), GPMF_CURRENT_LEVEL) == GPMF_OK) {
                        stmp = BYTESWAP64(*(uint64_t*)GPMF_RawData(&find_stream));
                    }
                    find_stream = strm;
                    if (GPMF_FindPrev(&find_stream, STR2FOURCC("TSMP"), GPMF_CURRENT_LEVEL) == GPMF_OK) {
                        tsmp = BYTESWAP32(*(uint32_t*)GPMF_RawData(&find_stream));
                    }
                    if (GPMF_RawDataSize(&strm) >= sizeof(float)) {
                        uint32_t raw_bits = BYTESWAP32(*(uint32_t*)GPMF_RawData(&strm));
                        float temp_c = 0.0f;
                        std::memcpy(&temp_c, &raw_bits, sizeof(float));
                        payload_tmpc_standalone.stmp = stmp;
                        payload_tmpc_standalone.tsmp = tsmp;
                        payload_tmpc_standalone.samples.clear();
                        payload_tmpc_standalone.samples.push_back((double)temp_c);
                        has_tmpc_standalone = true;
                    }
                }
            }
        }

        // Deduplicate TMPC: prefer ACCL canonical, fallback to GYRO, fallback to standalone
        if (has_tmpc_accl) {
            tmpc_blocks.push_back(std::move(payload_tmpc_accl));
        } else if (has_tmpc_gyro) {
            tmpc_blocks.push_back(std::move(payload_tmpc_gyro));
        } else if (has_tmpc_standalone) {
            tmpc_blocks.push_back(std::move(payload_tmpc_standalone));
        }
    }

    if (res) FreePayloadResource(mp4, res);
    CloseSource(mp4);

    result.camera_model = camera_name[0] ? camera_name : "GoPro";

    // Sort raw GPS points and deduplicate identical timestamps
    std::sort(raw_gps.begin(), raw_gps.end(), [](const GpsPoint& a, const GpsPoint& b) {
        return a.timestamp < b.timestamp;
    });

    std::vector<GpsPoint> deduped_gps;
    for (const auto& pt : raw_gps) {
        if (deduped_gps.empty() || std::abs(pt.timestamp - deduped_gps.back().timestamp) > 1e-4) {
            deduped_gps.push_back(pt);
        }
    }
    result.gps = std::move(deduped_gps);

    // Global timing anchor
    double anchor_ts = 0.0;
    if (first_gps9_abs_ts > 0.0) {
        // Align the first valid GPS9 block to its file-local STMP position.
        // This preserves the pre-lock interval before the first GPS sample.
        anchor_ts = first_gps9_abs_ts - first_gps9_local_s;
    } else if (!result.gps.empty()) {
        anchor_ts = result.gps[0].timestamp;
    } else if (first_gpsu_ts > 0.0) {
        anchor_ts = first_gpsu_ts;
    }
    result.start_dt_utc = anchor_ts;
    result.start_dt_str = FormatUtcIso(anchor_ts);

    // Navigation streams derived from GPS
    if (!result.gps.empty()) {
        double cum_m = 0.0;
        result.cumulative_distance.push_back({result.gps[0].timestamp, 0.0});

        for (size_t i = 1; i < result.gps.size(); i++) {
            const auto& prev = result.gps[i - 1];
            const auto& curr = result.gps[i];
            double dist = HaversineM(prev.lat, prev.lon, curr.lat, curr.lon);
            cum_m += dist;
            result.cumulative_distance.push_back({curr.timestamp, cum_m});

            // Heading (bearing)
            double brg = CalculateBearing(prev.lat, prev.lon, curr.lat, curr.lon);
            result.heading.push_back({curr.timestamp, brg});

            // Slope (%) = (delta_alt / horizontal_dist) * 100
            double slope_pct = dist > 0.5 ? ((curr.alt - prev.alt) / dist) * 100.0 : 0.0;
            result.slope.push_back({curr.timestamp, slope_pct});
        }
        if (!result.heading.empty()) {
            result.heading.insert(result.heading.begin(), {result.gps[0].timestamp, result.heading[0].value});
        }
        if (!result.slope.empty()) {
            result.slope.insert(result.slope.begin(), {result.gps[0].timestamp, result.slope[0].value});
        }
    }

    // Motion synthesis helper
    auto synthesize_vectors = [&](const std::vector<VectorBlock>& blocks) -> std::vector<TimedVector3> {
        std::vector<TimedVector3> out;
        if (blocks.empty() || anchor_ts <= 0.0) return out;
        std::vector<double> steps;
        for (size_t idx = 0; idx < blocks.size(); idx++) {
            if (idx + 1 < blocks.size()) {
                double dt = (double)(blocks[idx + 1].stmp - blocks[idx].stmp);
                if (!blocks[idx].samples.empty()) {
                    steps.push_back(dt / blocks[idx].samples.size());
                    continue;
                }
            }
            if (!steps.empty()) steps.push_back(steps.back());
            else steps.push_back(0.0);
        }
        uint64_t base_stmp = blocks[0].stmp;
        for (size_t b = 0; b < blocks.size(); b++) {
            double step_us = steps[b];
            double block_offset_s = (double)(blocks[b].stmp - base_stmp) * 1e-6;
            for (size_t s = 0; s < blocks[b].samples.size(); s++) {
                double ts = anchor_ts + block_offset_s + (s * step_us) * 1e-6;
                out.push_back({ts, blocks[b].samples[s]});
            }
        }
        return out;
    };

    result.accl = synthesize_vectors(accl_blocks);
    result.gyro = synthesize_vectors(gyro_blocks);
    result.grav = synthesize_vectors(grav_blocks);
    result.cori = synthesize_vectors(cori_blocks);

    // Timed ints synthesis helper (ISOE, SHUT)
    auto synthesize_ints = [&](const std::vector<IntBlock>& blocks) -> std::vector<TimedInt> {
        std::vector<TimedInt> out;
        if (blocks.empty() || anchor_ts <= 0.0) return out;
        std::vector<double> steps;
        for (size_t idx = 0; idx < blocks.size(); idx++) {
            if (idx + 1 < blocks.size()) {
                double dt = (double)(blocks[idx + 1].stmp - blocks[idx].stmp);
                if (!blocks[idx].samples.empty()) {
                    steps.push_back(dt / blocks[idx].samples.size());
                    continue;
                }
            }
            if (!steps.empty()) steps.push_back(steps.back());
            else steps.push_back(0.0);
        }
        uint64_t base_stmp = blocks[0].stmp;
        for (size_t b = 0; b < blocks.size(); b++) {
            double step_us = steps[b];
            double block_offset_s = (double)(blocks[b].stmp - base_stmp) * 1e-6;
            for (size_t s = 0; s < blocks[b].samples.size(); s++) {
                double ts = anchor_ts + block_offset_s + (s * step_us) * 1e-6;
                out.push_back({ts, blocks[b].samples[s]});
            }
        }
        return out;
    };

    result.isoe = synthesize_ints(isoe_blocks);
    result.shut = synthesize_ints(shut_blocks);

    // Timed double synthesis helper (TMPC)
    auto synthesize_doubles = [&](const std::vector<DoubleBlock>& blocks) -> std::vector<TimedDouble> {
        std::vector<TimedDouble> out;
        if (blocks.empty() || anchor_ts <= 0.0) return out;
        std::vector<double> steps;
        for (size_t idx = 0; idx < blocks.size(); idx++) {
            if (idx + 1 < blocks.size()) {
                double dt = (double)(blocks[idx + 1].stmp - blocks[idx].stmp);
                if (!blocks[idx].samples.empty()) {
                    steps.push_back(dt / blocks[idx].samples.size());
                    continue;
                }
            }
            if (!steps.empty()) steps.push_back(steps.back());
            else steps.push_back(0.0);
        }
        uint64_t base_stmp = blocks[0].stmp;
        for (size_t b = 0; b < blocks.size(); b++) {
            double step_us = steps[b];
            double block_offset_s = (double)(blocks[b].stmp - base_stmp) * 1e-6;
            for (size_t s = 0; s < blocks[b].samples.size(); s++) {
                double ts = anchor_ts + block_offset_s + (s * step_us) * 1e-6;
                out.push_back({ts, blocks[b].samples[s]});
            }
        }
        return out;
    };

    result.tmpc = synthesize_doubles(tmpc_blocks);
    result.raw_accl_tmpc = raw_accl_tmpc_count;
    result.raw_gyro_tmpc = raw_gyro_tmpc_count;

    if (!result.tmpc.empty()) {
        std::printf("[TMPC Native] raw_accl=%u raw_gyro=%u logical=%zu first=%.6f C last=%.6f C\n",
                    raw_accl_tmpc_count, raw_gyro_tmpc_count, result.tmpc.size(),
                    result.tmpc.front().value, result.tmpc.back().value);
        std::fflush(stdout);
    }

    result.success = true;

    return result;
}
