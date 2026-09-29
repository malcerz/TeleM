#pragma once

#include <string>
#include <vector>
#include <cstdint>

struct GpsPoint {
    double timestamp; // Unix epoch seconds
    double lat;
    double lon;
    double alt;
    double speed2d;   // km/h
    double speed3d;   // km/h
    double dop;
    int32_t fix;
};

struct Vector3 {
    double x;
    double y;
    double z;
};

struct TimedVector3 {
    double timestamp; // Unix epoch seconds
    Vector3 vec;
};

struct TimedInt {
    double timestamp; // Unix epoch seconds
    int32_t value;
};

struct TimedDouble {
    double timestamp; // Unix epoch seconds
    double value;
};

struct GpmfResult {
    // GPS & derived navigation
    std::vector<GpsPoint> gps;
    std::vector<TimedDouble> cumulative_distance; // (timestamp, metres)
    std::vector<TimedDouble> heading;             // (timestamp, degrees)
    std::vector<TimedDouble> slope;               // (timestamp, percent)

    // Motion & Orientation
    std::vector<TimedVector3> accl;
    std::vector<TimedVector3> gyro;
    std::vector<TimedVector3> grav;
    std::vector<TimedVector3> cori;

    // Camera settings
    std::vector<TimedInt> isoe;
    std::vector<TimedInt> shut;
    std::vector<TimedDouble> tmpc;

    // Metadata
    double start_dt_utc = 0.0;
    std::string start_dt_str;
    std::string camera_model;
    double duration_sec = 0.0;
    uint32_t payload_count = 0;
    uint32_t raw_accl_tmpc = 0;
    uint32_t raw_gyro_tmpc = 0;
    bool success = false;
    std::string error_message;
};

GpmfResult ExtractGpmfData(const std::string& mp4_path);
