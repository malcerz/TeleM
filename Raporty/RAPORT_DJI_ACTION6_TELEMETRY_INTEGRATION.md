# DJI Action 6 telemetry integration — incomplete IMU source

## Task, initial state and implementation

TeleM previously loaded GoPro GPMF and activity FIT/GPX, but had no DJI `djmd` path. At task start `main` was `1ecc2fc6c87d04e87fbcf8a7e3c830f24ac9f935`, equal to `origin/main`. Pre-existing unrelated deleted/untracked files were preserved.

Added `src/telemetry_dji.py` to detect `djmd` by MP4 stream tag and `CAM meta`/`DJI meta` handler, load the pinned Rust parser from the application folder, map any normalized gyro from degrees/s into TeleM radians/s and accel in m/s², retain any quaternion, and cache canonical camera arrays in the existing central cache. It does not add GPS, speed, heading or altitude. `TelemetryDataManager.load_dji_telemetry()` fills its existing IMU fields without touching FIT/GPX. The project loader branches on stream metadata before its GoPro GPMF path; multi-clip merging includes quaternion samples. The CPython 3.14 Windows x64 runtime, upstream license files, attribution and deliberate rebuild script are bundled. No native renderer DLL was rebuilt or changed.

The current upstream DJI MP4 parser source inserts `Quaternion` and camera/lens metadata; it does **not** insert `Gyroscope` or `Accelerometer` groups for DJI MP4. Consequently `normalized_imu()` cannot supply those channels for this format at the pinned commit. The provided 2.496 s file contains 74 `djmd` packets, but only its first telemetry group has a camera header; the other 73 groups are empty. Its normalized IMU and quaternion collections are empty. The adapter intentionally does not fabricate camera motion from other fields. A longer genuine Action 6 file with motion metadata and/or an upstream parser capability change is needed to meet the requested IMU acceptance gates.

HEAD=1ecc2fc6c87d04e87fbcf8a7e3c830f24ac9f935 (initial)
DJI_TEST_FILE=C:\_DEV\BikeRideHUD-main\Video\DJI_20260928071657_0002_D.MP4
UPSTREAM_REPO=https://github.com/AdrianEddy/telemetry-parser
UPSTREAM_COMMIT=d45ebf2afce85fa691838fd32b3da8ae2fcac773
UPSTREAM_LICENSE=MIT OR Apache-2.0
BUNDLED_LICENSE_FILE=runtime/telemetry_parser/LICENSE-MIT and LICENSE-APACHE
PYTHON_VERSION=CPython 3.14.7, Windows x64
DJI_PARSER_BUILD_METHOD=Rust 1.98.1 + maturin 1.15.0, release build with `PYO3_USE_ABI3_FORWARD_COMPATIBILITY=1` because pinned PyO3 0.21 supports through Python 3.12 by default
DJI_PARSER_RUNTIME_PATH=runtime/telemetry_parser/telemetry_parser/telemetry_parser.cp314-win_amd64.pyd (5,854,720 bytes; SHA-256 `32E8A0A21489BF325284469C46A8BBA1561AD1FF98058AE18BF18B6639F2CBF2`)
DJI_PARSER_OPEN_PASS=YES
DJI_CAMERA=DJI
DJI_MODEL=OsmoAction6
ACTION6_AUTO_DETECT_PASS=YES (`djmd` plus `CAM meta`, independent of filename)
TELEMETRY_SAMPLE_GROUPS=74, one nonempty camera metadata header
NORMALIZED_IMU_AVAILABLE=NO for supplied file

## Actual source inventory

| Channel | Available | Count | First TS | Last TS | Rate Hz | Units |
| --- | --- | ---: | --- | --- | ---: | --- |
| Gyroscope | No | 0 | — | — | — | normalized parser would use deg/s; TeleM mapping is rad/s |
| Accelerometer | No | 0 | — | — | — | normalized parser uses m/s² |
| Quaternion/orientation | No | 0 | — | — | — | unit quaternion |
| GPS | No | 0 | — | — | — | intentionally unused |
| Camera header | Yes | 1 | first metadata packet | first metadata packet | — | protobuf metadata |
| Exposure | No | 0 | — | — | — | — |
| Sensor FPS | No | 0 | — | — | — | header value `null` |
| IMU sample rate | No | 0 | — | — | — | header value `null` |
| Focal length | No | 0 | — | — | — | header value `null` |
| Sensor readout time | No | 0 | — | — | — | header value `null` |
| Distortion coefficients | No | 0 | — | — | — | header value `null` |

Header evidence: `proto_file_name=dvtm_ac206.proto`, `product_name=DJI OsmoAction6`, firmware `10.00.36.61`, EIS status `4`. MP4 has 74 video frames, 74 `djmd` packets, AAC audio and duration 2.496 s. Parser open + telemetry + normalized-IMU inspection took about 0.027 s. Source size is 13,893,586 bytes.

DJI_GYRO_AVAILABLE=NO
DJI_GYRO_COUNT=0
DJI_GYRO_RATE_HZ=NOT AVAILABLE
DJI_ACCEL_AVAILABLE=NO
DJI_ACCEL_COUNT=0
DJI_ACCEL_RATE_HZ=NOT AVAILABLE
DJI_QUATERNION_AVAILABLE=NO
DJI_QUATERNION_COUNT=0
DJI_GPS_AVAILABLE=NO
DJI_TIMELINE_MAPPING=upstream `timestamp_ms` divided by 1000 and anchored to MP4 UTC `creation_time`; first sample is not forcibly shifted to zero. Synthetic fractional-offset and two-clip monotonic tests pass; actual beginning/middle/end alignment is NOT TESTED because there are no samples.
DJI_GYRO_CANONICAL_PASS=synthetic adapter test only; real file NOT PROVEN
DJI_ACCEL_CANONICAL_PASS=synthetic adapter test only; real file NOT PROVEN
DJI_QUATERNION_CANONICAL_PASS=synthetic adapter test only; real file NOT PROVEN
DJI_PLUS_FIT_SOURCE_RESOLUTION_PASS=synthetic manager test: FIT speed/GPS retained; real DJI+FIT GUI combination NOT TESTED
DJI_MULTIFILE_GYRO_PASS=synthetic two-clip timestamp test; real clips NOT TESTED
DJI_MULTIFILE_ACCEL_PASS=synthetic two-clip timestamp test; real clips NOT TESTED

## Cache, deployment, application and regression evidence

DJI_COLD_LOAD_SECONDS=0.0228 after process startup on the supplied 13.9 MB file
DJI_WARM_LOAD_SECONDS=0.0103
DJI_WARM_CACHE_PASS=YES; central cache path under `%LOCALAPPDATA%/BikeRideHUD/cache/media/.../dji_imu.npz` (1,254 bytes). Key includes resolved path, file size, mtime, schema and upstream commit. No MP4 sidecar was written.
DJI_PARSER_OFFLINE_RUNTIME_PASS=YES; `python -S` loaded the bundled package without site packages
GUI_DJI_LOAD_PASS=NOT TESTED; computer-control runtime failed to initialize
GUI_DJI_TELEMETRY_PASS=NOT TESTED; project loader method parsed the real file, but GUI and real IMU samples were unavailable
DJI_IMU_PREVIEW_PASS=NOT TESTED; zero source samples
DJI_IMU_RENDER_PASS=NOT TESTED; zero source samples
PREVIEW_RENDER_PARITY_PASS=NOT TESTED
REAL_AMD_DJI_RENDER_PASS=YES for video path only: real D3D11/AMF export rendered 74/74 frames to 1080p, 11,561,044-byte MP4 in 2.265 s; camera IMU indicator proof is NOT PROVEN
GOPRO_GPMF_LOAD_PASS=YES, real GX010298.MP4 detected as `gopro_gpmf` and existing native parser returned samples
GOPRO_GYRO_PASS=YES, 277,943 native samples
GOPRO_ACCEL_PASS=YES, 277,943 native samples
AMD_DLL_SHA256_BEFORE=90BE5AF56BB56A73CDC161A0508B0D6A2C71987BE44A565712C37AA5B5D66647
AMD_DLL_SHA256_AFTER=90BE5AF56BB56A73CDC161A0508B0D6A2C71987BE44A565712C37AA5B5D66647
AMD_DLL_UNCHANGED=YES

TESTS=57 passed, 1 skipped across DJI, telemetry-manager, central-cache and native-GPMF regressions; real DJI project-loader opt-in test included. `compileall` and `git diff --check` passed. A separate pre-existing `test_gpmf_stream_first_sample_availability.py::test_final_frame_renderer_honours_first_sample_boundary` fails even in isolation (temperature at frame 0 is 20 rather than expected None); no touched code is in that renderer path.
NEW_REGRESSIONS=metadata-based detection; synthetic gyro/accel/quaternion mapping and cache; FIT preservation; two-clip timestamp order; missing parser; real Action 6 project-loader dispatch; GoPro detection priority
REGRESSIONS_OR_RISKS=actual DJI IMU is absent, parser upstream does not expose DJI gyro/accel, no GUI preview or IMU render proof, compiled extension is CPython 3.14-specific. The copied application folder includes the binary and licenses; rebuilding for another Python ABI uses the pinned build script.
COMMIT=353df3d (source, tests, runtime and build script); report committed separately
PUSH_RESULT=source commit pushed normally to origin/main; report push is the follow-up commit
FINAL_STATUS=DJI_ACTION6_TELEMETRY_INCOMPLETE (required real gyro/accel preview and render gates cannot be met with the supplied file and pinned upstream parser)
