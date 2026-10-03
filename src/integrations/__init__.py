"""Remote telemetry integrations package for BikeRideHUD."""

from src.integrations.activity_provider import ActivityCandidate, ActivityProvider
from src.integrations.activity_matcher import (
    AUTO_MATCH_THRESHOLD,
    SELECTION_THRESHOLD,
    score_candidate,
    rank_and_evaluate_candidates,
)
from src.integrations.garmin_connect import GarminProvider
from src.integrations.strava import StravaProvider, run_strava_oauth_flow
from src.integrations.coordinator import resolve_remote_activity
from src.integrations import credential_store, remote_cache

__all__ = [
    "ActivityCandidate",
    "ActivityProvider",
    "GarminProvider",
    "StravaProvider",
    "run_strava_oauth_flow",
    "resolve_remote_activity",
    "credential_store",
    "remote_cache",
    "AUTO_MATCH_THRESHOLD",
    "SELECTION_THRESHOLD",
    "score_candidate",
    "rank_and_evaluate_candidates",
]
