import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.gui.telemetry_manager import TelemetryDataManager
from src.ffmpeg.worker_cache import _resolve_cache_value, init_worker, WORKER_CACHE

VIDEO = Path("Video/GX010115.MP4")
FIT = Path("Video/Jazda_na_rowerze_w_porze_lunchu.fit")

telemetry = TelemetryDataManager()
telemetry.load_gpmf_from_exiftool(VIDEO)
telemetry.load_fit(VIDEO, telemetry.start_dt_utc, manual_path=FIT)

print(f"telemetry.heading_samples count: {len(telemetry.heading_samples if hasattr(telemetry, 'heading_samples') else [])}")
print(f"telemetry.fit_data keys: {list(telemetry.fit_data.keys())}")
if "heading" in telemetry.fit_data:
    print(f"fit_data['heading'][0..5]: {telemetry.fit_data['heading'][:5]}")
