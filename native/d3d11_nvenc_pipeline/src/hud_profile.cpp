#include "hud_profile.h"

#include <windows.h>
#include <algorithm>
#include <cstdio>
#include <cstdlib>
#include <map>
#include <mutex>
#include <string>
#include <vector>
#include <tuple>

namespace {

struct Samples {
    std::vector<double> values;
};

std::mutex g_mutex;
std::map<std::string, Samples> g_samples;
std::map<std::string, uint64_t> g_counts;
struct TimelineRow { uint32_t frame; std::string event; double qpc; };
std::vector<TimelineRow> g_timeline;
struct UpdateStats { std::string last; uint64_t renders = 0; uint64_t changes = 0; };
std::map<std::string, UpdateStats> g_updates;
uint32_t g_max_frame = 0;
std::string g_output_dir;
bool g_enabled = false;

bool EnvOn(const char* name) {
    char value[8] = {};
    DWORD len = GetEnvironmentVariableA(name, value, (DWORD)sizeof(value));
    return len > 0 && len < sizeof(value) && value[0] == '1';
}

double Percentile(std::vector<double> values, double p) {
    if (values.empty()) return 0.0;
    std::sort(values.begin(), values.end());
    const double k = (values.size() - 1) * (p / 100.0);
    const size_t f = (size_t)k;
    const size_t c = (size_t)(k + 0.999999999);
    if (f == c) return values[f];
    return values[f] * (c - k) + values[c] * (k - f);
}

void WriteTable(const char* file_name, const char* header, int columns, const char* table_filter) {
    if (g_output_dir.empty()) return;
    CreateDirectoryA("scratch", nullptr);
    CreateDirectoryA(g_output_dir.c_str(), nullptr);
    std::string path = g_output_dir + "\\" + file_name;
    FILE* file = nullptr;
    if (fopen_s(&file, path.c_str(), "w") != 0 || !file) return;
    std::fprintf(file, "%s\n", header);
    for (const auto& entry : g_samples) {
        const std::string& key = entry.first;
        const auto& src = entry.second.values;
        if (src.empty()) continue;
        double sum = 0.0;
        double max_v = 0.0;
        for (double value : src) { sum += value; max_v = (std::max)(max_v, value); }
        const double mean = sum / (double)src.size();
        const double median = Percentile(src, 50.0);
        const double p95 = Percentile(src, 95.0);
        const size_t sep1 = key.find('\t');
        const size_t sep2 = sep1 == std::string::npos ? sep1 : key.find('\t', sep1 + 1);
        const std::string a = sep1 == std::string::npos ? key : key.substr(0, sep1);
        const std::string b = sep1 == std::string::npos ? "" : key.substr(sep1 + 1, sep2 - sep1 - 1);
        const std::string c = sep2 == std::string::npos ? "" : key.substr(sep2 + 1);
        if (table_filter && a != table_filter) continue;
        if (columns == 1) {
            const std::string metric = c.empty() ? b : b + ":" + c;
            std::fprintf(file, "%s,%.9f,%.9f,%.9f,%.9f,%zu\n",
                         metric.c_str(), mean, median, p95, max_v, src.size());
        } else {
            std::fprintf(file, "%s,%s,%.9f,%.9f,%.9f,%.9f,%zu\n",
                         b.c_str(), c.c_str(), mean, median, p95, max_v, src.size());
        }
    }
    std::fclose(file);
}

} // namespace

namespace TelemHudProfile {

bool Enabled() {
    return g_enabled;
}

void Reset() {
    std::lock_guard<std::mutex> lock(g_mutex);
    g_enabled = EnvOn("TELEM_NATIVE_HUD_PROFILE");
    g_samples.clear();
    g_counts.clear();
    g_timeline.clear();
    g_updates.clear();
    g_max_frame = 0;
    char dir[1024] = {};
    DWORD len = GetEnvironmentVariableA("TELEM_NATIVE_HUD_PROFILE_DIR", dir, (DWORD)sizeof(dir));
    if (len > 0 && len < sizeof(dir)) g_output_dir.assign(dir, len);
    else g_output_dir = "scratch\\nvidia_hud_opt";
    if (g_enabled) {
        CreateDirectoryA("scratch", nullptr);
        CreateDirectoryA(g_output_dir.c_str(), nullptr);
    }
}

double NowSeconds() {
    if (!g_enabled) return 0.0;
    static LARGE_INTEGER frequency = {};
    if (frequency.QuadPart == 0) QueryPerformanceFrequency(&frequency);
    LARGE_INTEGER counter{};
    QueryPerformanceCounter(&counter);
    return (double)counter.QuadPart / (double)frequency.QuadPart;
}

void Record(const char* table, const char* item, const char* stage, double milliseconds) {
    if (!g_enabled || !table || !item || !stage) return;
    std::lock_guard<std::mutex> lock(g_mutex);
    g_samples[std::string(table) + "\t" + item + "\t" + stage].values.push_back(milliseconds);
}

void Count(const char* table, const char* item) {
    if (!g_enabled || !table || !item) return;
    std::lock_guard<std::mutex> lock(g_mutex);
    g_counts[std::string(table) + "\t" + item]++;
}

void Timeline(uint32_t frame, const char* event) {
    if (!g_enabled || !event) return;
    std::lock_guard<std::mutex> lock(g_mutex);
    g_timeline.push_back({frame, event, NowSeconds()});
}

void Update(uint32_t frame, const char* item, const char* value) {
    if (!g_enabled || !item || !value) return;
    std::lock_guard<std::mutex> lock(g_mutex);
    auto& s = g_updates[item];
    if (s.renders && s.last != value) ++s.changes;
    s.last = value;
    ++s.renders;
    g_max_frame = (std::max)(g_max_frame, frame);
}

void Dump() {
    std::lock_guard<std::mutex> lock(g_mutex);
    if (!g_enabled) return;
    WriteTable("wait_breakdown.csv", "metric,mean_ms,median_ms,p95_ms,max_ms,count", 1, "wait");
    WriteTable("chart_profile.csv", "chart,stage,mean_ms,median_ms,p95_ms,max_ms,count", 2, "chart");
    WriteTable("map_profile.csv", "component,stage,mean_ms,median_ms,p95_ms,max_ms,count", 2, "map");
    WriteTable("widget_costs_before.csv", "widget,stage,mean_ms,median_ms,p95_ms,max_ms,count", 2, "widget");
    WriteTable("widget_costs_full.csv", "widget,stage,mean_ms,median_ms,p95_ms,max_ms,count", 2, "widget");
    WriteTable("text_profile.csv", "kind,stage,mean_ms,median_ms,p95_ms,max_ms,count", 2, "text");
    WriteTable("resource_creation_profile.csv", "resource,stage,mean_ms,median_ms,p95_ms,max_ms,count", 2, "resource");
    WriteTable("d2d_call_counts.csv", "call,count,total_per_frame", 1, "d2d");
    if (!g_output_dir.empty()) {
        FILE* f = nullptr;
        std::string path = g_output_dir + "\\hud_frame_timeline.csv";
        if (fopen_s(&f, path.c_str(), "w") == 0 && f) {
            std::fprintf(f, "frame,event,qpc_seconds\n");
            for (const auto& row : g_timeline)
                std::fprintf(f, "%u,%s,%.9f\n", row.frame, row.event.c_str(), row.qpc);
            std::fclose(f);
        }
        path = g_output_dir + "\\d2d_call_counts.csv";
        if (fopen_s(&f, path.c_str(), "w") == 0 && f) {
            std::fprintf(f, "call,count,total_per_frame\n");
            uint64_t frame_count = 0;
            auto it = g_counts.find("d2d\tBeginDraw");
            if (it != g_counts.end()) frame_count = it->second;
            if (!frame_count) frame_count = 1;
            const char* calls[] = {"BeginDraw","EndDraw","Flush","DrawText","DrawTextLayout",
                                   "DrawGeometry","FillGeometry","DrawBitmap","DrawLine",
                                   "FillRectangle","SetTransform","SetTarget","D3D11Flush"};
            for (const char* call : calls) {
                auto it_call = g_counts.find(std::string("d2d\t") + call);
                const uint64_t n = it_call == g_counts.end() ? 0 : it_call->second;
                std::fprintf(f, "%s,%llu,%.6f\n", call, (unsigned long long)n,
                             (double)n / (double)frame_count);
            }
            std::fclose(f);
        }
        path = g_output_dir + "\\widget_update_rates.csv";
        if (fopen_s(&f, path.c_str(), "w") == 0 && f) {
            std::fprintf(f, "widget,render_count,value_change_count,render_rate_hz,value_change_rate_hz\n");
            const double duration_s = ((double)g_max_frame + 1.0) / 29.97;
            for (const auto& e : g_updates) {
                std::fprintf(f, "%s,%llu,%llu,%.6f,%.6f\n", e.first.c_str(),
                             (unsigned long long)e.second.renders,
                             (unsigned long long)e.second.changes,
                             duration_s > 0.0 ? e.second.renders / duration_s : 0.0,
                             duration_s > 0.0 ? e.second.changes / duration_s : 0.0);
            }
            std::fclose(f);
        }
        path = g_output_dir + "\\resource_creation_profile.csv";
        if (fopen_s(&f, path.c_str(), "w") == 0 && f) {
            std::fprintf(f, "resource,creation_count,creations_per_frame\n");
            const double frames = (double)g_max_frame + 1.0;
            const char* resources[] = {"CreateSolidColorBrush","CreatePathGeometry","OpenGeometrySink",
                                       "CreateTextFormat","CreateTextLayout","CreateBitmap","CreateLayer",
                                       "CreateStrokeStyle"};
            for (const char* resource : resources) {
                auto it_resource = g_counts.find(std::string("resource\t") + resource);
                const uint64_t n = it_resource == g_counts.end() ? 0 : it_resource->second;
                std::fprintf(f, "%s,%llu,%.9f\n", resource, (unsigned long long)n,
                             frames > 0.0 ? (double)n / frames : 0.0);
            }
            std::fclose(f);
        }
        WriteTable("hud_profile.csv", "component,stage,mean_ms,median_ms,p95_ms,max_ms,count", 2, "hud");
    }
}

} // namespace TelemHudProfile
