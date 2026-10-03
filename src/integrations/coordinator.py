"""Remote activity coordinator for automatic telemetry fetching."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Optional

from src.integrations.activity_provider import ActivityCandidate, ActivityProvider
from src.integrations.activity_matcher import rank_and_evaluate_candidates
from src.integrations.garmin_connect import GarminProvider
from src.integrations.strava import StravaProvider
from src.integrations import remote_cache


def resolve_remote_activity(
    video_paths: list[Path | str],
    project_start_dt: datetime,
    project_end_dt: datetime,
    project_duration_s: float,
    config: dict[str, Any],
    video_gps_point: Optional[tuple[float, float]] = None,
    on_progress: Optional[Callable[[str], None]] = None,
    on_select_activity: Optional[Callable[[list[tuple[ActivityCandidate, float]]], Optional[ActivityCandidate]]] = None,
    provider_override: Optional[ActivityProvider] = None,
) -> Optional[Path]:
    """Resolve and download remote telemetry matching the video timeline.

    Returns the Path to the local .fit or .gpx file, or None if:
    - Auto-activity source is 'none'
    - No matching activity is found
    - Service is offline / authentication failed
    - User cancelled ambiguous candidate selection
    """
    source = str(config.get("auto_activity_source", "none") or "none").lower()
    if source in ("none", "", "nic"):
        return None

    # 1. Check local cache first (Requirement 15: ZERO remote download on cache hit)
    cached = remote_cache.find_cached_video_telemetry(video_paths)
    if cached is not None:
        prov, act_id, path = cached
        print(
            f"[REMOTE ACTIVITY] REMOTE_CACHE_HIT=YES provider={prov} "
            f"activity_id={act_id} path={path.name}",
            flush=True,
        )
        return path

    print(
        f"[REMOTE ACTIVITY] REMOTE_CACHE_HIT=NO provider={source} "
        f"video_start={project_start_dt.isoformat()} duration={project_duration_s:.1f}s",
        flush=True,
    )

    # 2. Instantiate provider
    provider: ActivityProvider
    if provider_override is not None:
        provider = provider_override
    elif source == "garmin":
        username = config.get("garmin_username", "")
        if not username:
            print("[REMOTE ACTIVITY] Brak loginu Garmin Connect w konfiguracji.", flush=True)
            return None
        provider = GarminProvider(username=username)
    elif source == "strava":
        client_id = config.get("strava_client_id", "")
        if not client_id:
            print("[REMOTE ACTIVITY] Brak Client ID Strava w konfiguracji.", flush=True)
            return None
        provider = StravaProvider(client_id=client_id)
    else:
        return None

    # 3. Query activities within search window: [video_start - 2h, video_end + 2h]
    window_start = project_start_dt - timedelta(hours=2)
    window_end = project_end_dt + timedelta(hours=2)

    try:
        if on_progress:
            on_progress(f"Szukanie aktywności {source.capitalize()}...")

        candidates = provider.list_activities(window_start, window_end)
        if not candidates:
            print(f"[REMOTE ACTIVITY] provider={source} brak aktywności w oknie czasowym", flush=True)
            return None

        # 4. Rank candidates using multi-factor matcher
        decision, ranked = rank_and_evaluate_candidates(
            candidates,
            project_start_dt,
            project_end_dt,
            video_gps_point=video_gps_point,
        )

        if not ranked:
            return None

        best_cand, best_score = ranked[0]
        selected_candidate: Optional[ActivityCandidate] = None

        if decision == "AUTO_ACCEPT":
            print(
                f"[REMOTE ACTIVITY] provider={source} activity_id={best_cand.activity_id} "
                f"match_score={best_score:.2f} decision=AUTO_ACCEPT",
                flush=True,
            )
            selected_candidate = best_cand
        elif decision == "NEEDS_SELECTION":
            print(
                f"[REMOTE ACTIVITY] provider={source} activity_id={best_cand.activity_id} "
                f"match_score={best_score:.2f} decision=NEEDS_SELECTION (kandydatów: {len(ranked)})",
                flush=True,
            )
            if on_select_activity is not None:
                selected_candidate = on_select_activity(ranked)
                if selected_candidate is None:
                    print("[REMOTE ACTIVITY] Użytkownik pominął wybór aktywności.", flush=True)
                    return None
            else:
                # In headless / test mode without UI dialog, take best candidate if >= 0.70
                if best_score >= 0.70:
                    selected_candidate = best_cand
                else:
                    return None
        else:
            print(
                f"[REMOTE ACTIVITY] provider={source} brak pasującej aktywności (najlepszy score: {best_score:.2f})",
                flush=True,
            )
            return None

        if selected_candidate is None:
            return None

        # 5. Download telemetry
        if on_progress:
            on_progress(f"Pobieranie telemetrii {source.capitalize()} ({selected_candidate.activity_id})...")

        dest_dir = remote_cache.get_provider_cache_dir(source)
        downloaded_file = provider.download_telemetry(selected_candidate.activity_id, dest_dir)

        # 6. Save in cache and record video linkage
        remote_cache.save_cached_video_telemetry(
            video_paths,
            source,
            selected_candidate.activity_id,
            downloaded_file,
            metadata={
                "name": selected_candidate.name,
                "sport_type": selected_candidate.sport_type,
                "duration_s": selected_candidate.duration_s,
                "match_score": best_score,
                "start_dt": selected_candidate.start_dt.isoformat(),
            },
        )

        return downloaded_file

    except Exception as exc:
        print(f"[REMOTE ACTIVITY] Błąd pobierania zdalnej telemetrii (offline / błąd API): {exc}", flush=True)
        return None
