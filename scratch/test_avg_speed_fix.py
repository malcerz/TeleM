import os, sys
os.add_dll_directory(r'C:\_DEV\TeleM-integration')
os.add_dll_directory(r'C:\_DEV\TeleM')
os.environ['PATH'] = r'C:\_DEV\TeleM-integration;' + r'C:\_DEV\TeleM;' + os.environ.get('PATH', '')
sys.path.insert(0, r'C:\_DEV\TeleM-integration')

from src.gui.qt.controller import AppController
from src.indicators.frame_data import prepare_overlay_frame_data
from src.telemetry_precompute import build_telemetry_cache
from src.multifile import build_timeline_from_paths
import json

ctrl = AppController()
v14 = r'C:\_DEV\TeleM\Video\GX010114.MP4'
v15 = r'C:\_DEV\TeleM\Video\GX010115.MP4'
v16 = r'C:\_DEV\TeleM\Video\GX010116.MP4'
fit = r'C:\_DEV\TeleM\Video\GX010114_116.fit'

ctrl.telemetry.load_fit(fit)
timeline = build_timeline_from_paths([v14, v15, v16], base_dt=ctrl.telemetry.start_dt_utc)
with open(r'C:\_DEV\TeleM\def_layout.json', 'r', encoding='utf-8') as f:
    layout = json.load(f)

print('=== 1. POINT FROM USER SCREENSHOT (GX010115 ~26s) ===')
g_t_26 = timeline.clips[1].global_start_s + 26.0
abs_dt_26 = timeline.global_to_absolute(g_t_26, base_dt=ctrl.telemetry.start_dt_utc)
idx_26, loc_26 = timeline.global_to_clip(g_t_26)

# Frame data overlay
data_26 = prepare_overlay_frame_data(
    layout=layout,
    target_dt=abs_dt_26,
    tz_offset_hours=2,
    start_dt_utc=ctrl.telemetry.start_dt_utc,
    speed_samples=ctrl.telemetry.speed_samples or [],
    track_samples=ctrl.telemetry.track_samples or [],
    alt_samples=ctrl.telemetry.alt_samples or [],
    fit_data=ctrl.telemetry.fit_data,
    gps_track=ctrl.telemetry.get_gps_track_for_source('fit'),
    total_frames=max(1, int(timeline.project_duration_s)),
    current_index=int(g_t_26),
    resolve_cache_value=lambda k, src, dt, indicator_key=None: ctrl.telemetry.resolve_value(
        k, dt, source=src, indicator_key=indicator_key
    ),
)

dist_26 = data_26["distance_m"]
avg_26 = data_26["avg_speed_kmh"]
fit_start = ctrl.telemetry.fit_data['distance'][0][0]
act_el = (abs_dt_26.replace(tzinfo=None) - fit_start.replace(tzinfo=None)).total_seconds()

print(f'Absolute timestamp:    {abs_dt_26}')
print(f'Clip local time:       {loc_26:.1f} s (Czas display: {int(loc_26//60):02d}:{int(loc_26%60):02d})')
print(f'Cumulative distance:   {dist_26:.2f} m ({dist_26/1000.0:.2f} km)')
print(f'Activity elapsed time: {act_el:.1f} s ({int(act_el//60):02d}:{int(act_el%60):02d})')
print(f'Average speed (BEFORE / BUG): {(dist_26 / 26.0) * 3.6:.1f} km/h')
print(f'Average speed (AFTER / FIX):  {avg_26:.1f} km/h')

print('\n=== 2. TRANSITIONS & BOUNDARIES ===')
points = [
    ('014 start', 0.0),
    ('014 end', timeline.clips[0].duration_s - 0.5),
    ('015 start', timeline.clips[1].global_start_s + 0.5),
    ('015 local 26s', g_t_26),
    ('015 end', timeline.clips[1].global_end_s - 0.5),
    ('016 start', timeline.clips[2].global_start_s + 0.5),
    ('016 end', timeline.clips[2].global_end_s - 0.5),
]

for label, g_t in points:
    idx, l_t = timeline.global_to_clip(g_t)
    target_dt = timeline.global_to_absolute(g_t, base_dt=ctrl.telemetry.start_dt_utc)
    res = prepare_overlay_frame_data(
        layout=layout,
        target_dt=target_dt,
        tz_offset_hours=2,
        start_dt_utc=ctrl.telemetry.start_dt_utc,
        speed_samples=ctrl.telemetry.speed_samples or [],
        track_samples=ctrl.telemetry.track_samples or [],
        alt_samples=ctrl.telemetry.alt_samples or [],
        fit_data=ctrl.telemetry.fit_data,
        gps_track=ctrl.telemetry.get_gps_track_for_source('fit'),
        total_frames=max(1, int(timeline.project_duration_s)),
        current_index=int(g_t),
        resolve_cache_value=lambda k, src, dt, indicator_key=None: ctrl.telemetry.resolve_value(
            k, dt, source=src, indicator_key=indicator_key
        ),
    )
    dist_km = (res['distance_m'] or 0.0) / 1000.0
    abs_s = target_dt.strftime('%H:%M:%S')
    print(f'{label:15s} | clip={idx} local={l_t:6.1f}s | abs={abs_s} | dist={dist_km:5.2f}km | avg_speed={res["avg_speed_kmh"]:5.1f} km/h')

print('\n=== 3. SINGLE-FILE REGRESSION TEST (GX020079) ===')
ctrl_single = AppController()
ctrl_single.telemetry.load_fit(r'C:\_DEV\TeleM\Video\GX020079.fit')
abs_s0 = ctrl_single.telemetry.start_dt_utc
data_s0 = prepare_overlay_frame_data(
    layout=layout,
    target_dt=abs_s0,
    tz_offset_hours=2,
    start_dt_utc=abs_s0,
    speed_samples=ctrl_single.telemetry.speed_samples or [],
    track_samples=ctrl_single.telemetry.track_samples or [],
    alt_samples=ctrl_single.telemetry.alt_samples or [],
    fit_data=ctrl_single.telemetry.fit_data,
    gps_track=ctrl_single.telemetry.get_gps_track_for_source('fit'),
    total_frames=1131,
    current_index=0,
    resolve_cache_value=lambda k, src, dt, indicator_key=None: ctrl_single.telemetry.resolve_value(
        k, dt, source=src, indicator_key=indicator_key
    ),
)
from datetime import timedelta
abs_s100 = abs_s0 + timedelta(seconds=18.85) # frame 1131 at 60fps ~ 18.85s
data_s100 = prepare_overlay_frame_data(
    layout=layout,
    target_dt=abs_s100,
    tz_offset_hours=2,
    start_dt_utc=abs_s0,
    speed_samples=ctrl_single.telemetry.speed_samples or [],
    track_samples=ctrl_single.telemetry.track_samples or [],
    alt_samples=ctrl_single.telemetry.alt_samples or [],
    fit_data=ctrl_single.telemetry.fit_data,
    gps_track=ctrl_single.telemetry.get_gps_track_for_source('fit'),
    total_frames=1131,
    current_index=1130,
    resolve_cache_value=lambda k, src, dt, indicator_key=None: ctrl_single.telemetry.resolve_value(
        k, dt, source=src, indicator_key=indicator_key
    ),
)
print(f'Single file start: dist={(data_s0["distance_m"] or 0)/1000.0:.3f} km, avg_speed={data_s0["avg_speed_kmh"]:.1f} km/h')
print(f'Single file end:   dist={(data_s100["distance_m"] or 0)/1000.0:.3f} km, avg_speed={data_s100["avg_speed_kmh"]:.1f} km/h')

print('\n=== 4. PRECOMPUTE PARITY TEST (MULTI-FILE) ===')
cache = build_telemetry_cache(
    layout=layout,
    base_dt=ctrl.telemetry.start_dt_utc,
    start_dt_utc=ctrl.telemetry.start_dt_utc,
    tz_offset_hours=2,
    speed_samples=ctrl.telemetry.speed_samples or [],
    track_samples=ctrl.telemetry.track_samples or [],
    alt_samples=ctrl.telemetry.alt_samples or [],
    fit_data=ctrl.telemetry.fit_data,
    gps_track=ctrl.telemetry.get_gps_track_for_source('fit'),
    total_frames=100,
    target_fps=29.97,
    video_timeline=timeline,
    resolve_cache_value=lambda k, src, dt, indicator_key=None: ctrl.telemetry.resolve_value(
        k, dt, source=src, indicator_key=indicator_key
    ),
)

rec_0 = cache.lookup(0)
rec_50 = cache.lookup(50)
print(f'Precompute frame 0: dist={rec_0["distance_m"]/1000.0:.3f}km, avg_spd={rec_0["avg_speed_kmh"]:.1f} km/h')
print(f'Precompute frame 50: dist={rec_50["distance_m"]/1000.0:.3f}km, avg_spd={rec_50["avg_speed_kmh"]:.1f} km/h')


print('\nALL TESTS EXECUTED SUCCESSFULLY.')
