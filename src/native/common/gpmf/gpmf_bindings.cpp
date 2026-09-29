#include <pybind11/pybind11.h>
#include <pybind11/stl.h>

#include "gpmf_extractor.h"

namespace py = pybind11;

py::dict ExtractGpmfDict(const std::string& mp4_path) {
    GpmfResult res = ExtractGpmfData(mp4_path);
    py::dict out;
    out["success"] = res.success;
    out["error_message"] = res.error_message;
    if (!res.success) {
        return out;
    }

    out["camera_model"] = res.camera_model;
    out["duration_sec"] = res.duration_sec;
    out["payload_count"] = res.payload_count;
    out["start_dt_utc"] = res.start_dt_utc;
    out["start_dt_str"] = res.start_dt_str;

    // GPS & derived
    py::list speed_samples;
    py::list alt_samples;
    py::list gps_track;
    for (const auto& pt : res.gps) {
        double spd = (pt.speed3d > 1e-4) ? pt.speed3d : pt.speed2d;
        speed_samples.append(py::make_tuple(pt.timestamp, spd));
        alt_samples.append(py::make_tuple(pt.timestamp, pt.alt));
        gps_track.append(py::make_tuple(pt.timestamp, pt.lat, pt.lon));
    }
    out["speed_samples"] = speed_samples;
    out["alt_samples"] = alt_samples;
    out["gps_track"] = gps_track;

    py::list track_samples;
    for (const auto& s : res.cumulative_distance) {
        track_samples.append(py::make_tuple(s.timestamp, s.value));
    }
    out["track_samples"] = track_samples;

    py::list heading_samples;
    for (const auto& s : res.heading) {
        heading_samples.append(py::make_tuple(s.timestamp, s.value));
    }
    out["heading_samples"] = heading_samples;

    py::list slope_samples;
    for (const auto& s : res.slope) {
        slope_samples.append(py::make_tuple(s.timestamp, s.value));
    }
    out["slope_samples"] = slope_samples;

    // Motion vectors
    py::list accl_samples;
    for (const auto& v : res.accl) {
        accl_samples.append(py::make_tuple(v.timestamp, py::make_tuple(v.vec.x, v.vec.y, v.vec.z)));
    }
    out["accelerometer_samples"] = accl_samples;

    py::list gyro_samples;
    for (const auto& v : res.gyro) {
        gyro_samples.append(py::make_tuple(v.timestamp, py::make_tuple(v.vec.x, v.vec.y, v.vec.z)));
    }
    out["gyroscope_samples"] = gyro_samples;

    // Camera settings
    py::list iso_samples;
    for (const auto& s : res.isoe) {
        iso_samples.append(py::make_tuple(s.timestamp, s.value));
    }
    out["iso_samples"] = iso_samples;

    py::list exposure_samples;
    for (const auto& s : res.shut) {
        exposure_samples.append(py::make_tuple(s.timestamp, s.value));
    }
    out["exposure_samples"] = exposure_samples;

    py::list temp_samples;
    for (const auto& s : res.tmpc) {
        temp_samples.append(py::make_tuple(s.timestamp, s.value));
    }
    out["temperature_samples"] = temp_samples;
    out["raw_accl_tmpc"] = res.raw_accl_tmpc;
    out["raw_gyro_tmpc"] = res.raw_gyro_tmpc;

    return out;
}

PYBIND11_MODULE(telem_gpmf_native, m) {
    m.doc() = "High-performance native C++ GPMF parser for TeleM";

    py::class_<GpsPoint>(m, "GpsPoint")
        .def_readonly("timestamp", &GpsPoint::timestamp)
        .def_readonly("lat", &GpsPoint::lat)
        .def_readonly("lon", &GpsPoint::lon)
        .def_readonly("alt", &GpsPoint::alt)
        .def_readonly("speed2d", &GpsPoint::speed2d)
        .def_readonly("speed3d", &GpsPoint::speed3d)
        .def_readonly("dop", &GpsPoint::dop)
        .def_readonly("fix", &GpsPoint::fix);

    py::class_<Vector3>(m, "Vector3")
        .def_readonly("x", &Vector3::x)
        .def_readonly("y", &Vector3::y)
        .def_readonly("z", &Vector3::z);

    py::class_<TimedVector3>(m, "TimedVector3")
        .def_readonly("timestamp", &TimedVector3::timestamp)
        .def_readonly("vec", &TimedVector3::vec);

    py::class_<TimedDouble>(m, "TimedDouble")
        .def_readonly("timestamp", &TimedDouble::timestamp)
        .def_readonly("value", &TimedDouble::value);

    py::class_<TimedInt>(m, "TimedInt")
        .def_readonly("timestamp", &TimedInt::timestamp)
        .def_readonly("value", &TimedInt::value);

    py::class_<GpmfResult>(m, "GpmfResult")
        .def_readonly("gps", &GpmfResult::gps)
        .def_readonly("cumulative_distance", &GpmfResult::cumulative_distance)
        .def_readonly("heading", &GpmfResult::heading)
        .def_readonly("slope", &GpmfResult::slope)
        .def_readonly("accl", &GpmfResult::accl)
        .def_readonly("gyro", &GpmfResult::gyro)
        .def_readonly("grav", &GpmfResult::grav)
        .def_readonly("cori", &GpmfResult::cori)
        .def_readonly("isoe", &GpmfResult::isoe)
        .def_readonly("shut", &GpmfResult::shut)
        .def_readonly("tmpc", &GpmfResult::tmpc)
        .def_readonly("raw_accl_tmpc", &GpmfResult::raw_accl_tmpc)
        .def_readonly("raw_gyro_tmpc", &GpmfResult::raw_gyro_tmpc)
        .def_readonly("start_dt_utc", &GpmfResult::start_dt_utc)
        .def_readonly("start_dt_str", &GpmfResult::start_dt_str)
        .def_readonly("camera_model", &GpmfResult::camera_model)
        .def_readonly("duration_sec", &GpmfResult::duration_sec)
        .def_readonly("payload_count", &GpmfResult::payload_count)
        .def_readonly("success", &GpmfResult::success)
        .def_readonly("error_message", &GpmfResult::error_message);

    m.def("extract_gpmf_data", &ExtractGpmfData, "Extract raw typed GPMF data structures from MP4", py::arg("mp4_path"));
    m.def("extract_gpmf_dict", &ExtractGpmfDict, "Extract canonical TeleM telemetry dict from MP4", py::arg("mp4_path"));
}
