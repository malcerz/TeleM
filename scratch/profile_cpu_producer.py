import sys, os, time, json
from pathlib import Path
_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

import numpy as np
from PIL import Image
from telemetry_fit import process_fit
from src.gui.layout_manager import normalize_layout
from src.telemetry_gpmf_new import gpmf_to_exiftool_json
from src.telemetry_extract import (
    extract_speed_samples, extract_altitude_samples, extract_track_samples,
    extract_iso_samples, extract_exposure_samples, extract_temperature_samples,
    find_gps_anchor
)
from src.indicators.frame_data import prepare_overlay_frame_data
from src.indicators.compositor import compose_overlay
from src.indicators.time_block import render_time_block
from src.indicators.dispatcher import render_value_indicator
from src.indicators.chart import render_chart_indicator
from src.indicators.gauge import _render_gauge_indicator
from src.indicators.map import _render_map_indicator
from src.indicators.bar import _render_bar_indicator
from src.indicators.rotated_paste import rotated_paste
from src.ffmpeg.command_builder import get_layout_hud_regions

print("Profiling test environment ready.")
