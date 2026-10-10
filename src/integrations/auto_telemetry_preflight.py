"""Automatic telemetry preflight searching local directory and remote providers immediately on MP4 selection."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import threading
from typing import Any, Callable, Optional
import xml.etree.ElementTree as ET

from src.integrations.activity_provider import ActivityCandidate, ActivityProvider
from src.integrations.activity_matcher import rank_and_evaluate_candidates
from src.integrations.garmin_connect import GarminProvider
from src.integrations.strava import StravaProvider
from src.integrations import credential_store, remote_cache
from telemetry_fit import probe_fit_time_range


_GPX_PROBE_CACHE: dict[tuple[str, int, float], tuple[datetime, datetime, float]] = {}


def probe_gpx_time_range(gpx_path: Path | str) -> tuple[datetime, datetime, float] | None:
    """Fast probe of start_time, end_time, and duration for a GPX file."""
    p = Path(gpx_path)
    if not p.is_file():
        return None
    try:
        st = p.stat()
        cache_key = (str(p.resolve()), st.st_size, st.st_mtime)
        if cache_key in _GPX_PROBE_CACHE:
            return _GPX_PROBE_CACHE[cache_key]
    except Exception:
        cache_key = None

    try:
        first_dt: datetime | None = None
        last_dt: datetime | None = None
        # Parse XML stream to find first and last <time> timestamps
        for _event, elem in ET.iterparse(str(p), events=("end",)):
            tag = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag
            if tag == "time" and elem.text:
                txt = elem.text.strip()
                try:
                    dt = datetime.fromisoformat(txt.replace("Z", "+00:00"))
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    else:
                        dt = dt.astimezone(timezone.utc)
                    if first_dt is None:
                        first_dt = dt
                    last_dt = dt
                except Exception:
                    pass
            elem.clear()

        if first_dt is not None and last_dt is not None:
            dur = max(0.0, (last_dt - first_dt).total_seconds())
            res = (first_dt, last_dt, dur)
            if cache_key is not None:
                _GPX_PROBE_CACHE[cache_key] = res
            return res
    except Exception:
        pass
    return None


def scan_and_match_local_telemetry(
    video_paths: list[Path | str],
    intervals: list[tuple[datetime, datetime, float, str]],
    directory: Path | str,
    on_status: Optional[Callable[[str, str], None]] = None,
    max_tolerance_s: float = 1800.0,
    video_gps_point: Optional[tuple[float, float]] = None,
) -> tuple[Optional[Path], dict[str, Any]]:
    """Scan local directory for matching .fit and .gpx files based on time overlap and basename priority.

    Returns:
        (matched_path, diagnostics_dict)
    """
    dir_path = Path(directory)
    if not intervals:
        return None, {"status": "no_intervals", "reason": "No video intervals provided"}

    norm_intervals: list[tuple[datetime, datetime]] = []
    for item in intervals:
        s = item[0]
        e = item[1] if len(item) > 1 and item[1] is not None else s + timedelta(seconds=600)
        s_utc = s if s.tzinfo is not None else s.replace(tzinfo=timezone.utc)
        e_utc = e if e.tzinfo is not None else e.replace(tzinfo=timezone.utc)
        norm_intervals.append((s_utc, e_utc))

    # 1. Try find_best_fit_match first (preserves test patches and standard FIT matching)
    try:
        from telemetry_fit import find_best_fit_match
        matched_fit, diag_fit = find_best_fit_match(
            [(s, e) for s, e in norm_intervals],
            dir_path,
            max_tolerance_s=max_tolerance_s,
        )
        if matched_fit is not None:
            chosen = Path(matched_fit)
            return chosen, {"status": "matched", "path": chosen, "diag": diag_fit}
    except Exception:
        pass

    if not dir_path.is_dir():
        return None, {"status": "no_dir", "reason": f"Directory not found: {directory}"}

    video_earliest = min(s for s, _ in norm_intervals)
    video_latest = max(e for _, e in norm_intervals)
    total_video_duration = sum(max(0.0, (e - s).total_seconds()) for s, e in norm_intervals)

    # Collect unique .fit and .gpx candidates in directory
    fit_candidates = sorted(dir_path.glob("*.fit")) + sorted(dir_path.glob("*.FIT"))
    gpx_candidates = sorted(dir_path.glob("*.gpx")) + sorted(dir_path.glob("*.GPX"))

    seen_paths: set[str] = set()
    unique_candidates: list[Path] = []
    for cand in fit_candidates + gpx_candidates:
        can = str(cand.resolve())
        if can not in seen_paths and cand.is_file():
            seen_paths.add(can)
            unique_candidates.append(cand)

    if not unique_candidates:
        return None, {"status": "no_local_files", "reason": "No FIT/GPX files found in directory"}

    cand_count = len(unique_candidates)
    if on_status:
        # Polish plural form
        if cand_count == 1:
            cnt_str = "1 plik"
        elif cand_count in (2, 3, 4) or (cand_count > 20 and cand_count % 10 in (2, 3, 4)):
            cnt_str = f"{cand_count} pliki"
        else:
            cnt_str = f"{cand_count} plików"
        on_status(f"Sprawdzam {cnt_str} FIT/GPX...", f"Sprawdzam {cnt_str} FIT/GPX w katalogu filmu...")

    video_stems = {Path(p).stem.lower() for p in video_paths}
    scored_candidates: list[dict[str, Any]] = []

    for p in unique_candidates:
        ext = p.suffix.lower()
        probe: tuple[datetime, datetime, float] | None = None
        if ext == ".fit":
            probe = probe_fit_time_range(p)
        elif ext == ".gpx":
            probe = probe_gpx_time_range(p)

        if probe is None:
            continue

        telem_start, telem_end, telem_dur = probe
        # Ensure UTC timezone awareness
        if telem_start.tzinfo is None:
            telem_start = telem_start.replace(tzinfo=timezone.utc)
        if telem_end.tzinfo is None:
            telem_end = telem_end.replace(tzinfo=timezone.utc)

        total_overlap = 0.0
        for c_start, c_end in norm_intervals:
            ov = (min(c_end, telem_end) - max(c_start, telem_start)).total_seconds()
            if ov > 0:
                total_overlap += ov

        start_diff = abs((video_earliest - telem_start).total_seconds())
        has_exact_name = p.stem.lower() in video_stems

        # Time validation:
        # 1. Any positive overlap is acceptable.
        # 2. If exact name match, allow tolerance within same day / reasonable window (<= 86400s or overlap).
        # 3. For general candidates, allow start_diff within max_tolerance_s or overlapping range.
        is_acceptable = False
        dist_m = None
        gps_duration_ratio = 0.0

        if total_overlap > 0.0:
            is_acceptable = True
        elif has_exact_name and start_diff <= 86400.0:
            is_acceptable = True
        elif start_diff <= max_tolerance_s:
            if telem_start <= video_latest and telem_end >= video_earliest:
                is_acceptable = True
            elif telem_start > video_latest and (telem_start - video_latest).total_seconds() <= max_tolerance_s:
                is_acceptable = True
            elif video_earliest > telem_end and (video_earliest - telem_end).total_seconds() <= max_tolerance_s:
                is_acceptable = True

        # Fallback to GPS distance if time is completely off (e.g., GoPro clock reset)
        if not is_acceptable and video_gps_point is not None:
            try:
                from telemetry_fit import parse_fit, _haversine
                if ext == ".fit":
                    fit_rec = parse_fit(p)
                    if fit_rec and fit_rec.gps_track:
                        first_pt = fit_rec.gps_track[0]
                        dist_m = _haversine(video_gps_point[0], video_gps_point[1], first_pt[1], first_pt[2])
                        fit_dur = (fit_rec.gps_track[-1][0] - fit_rec.gps_track[0][0]).total_seconds()
                        
                        if total_video_duration > 0 and fit_dur > 0:
                            gps_duration_ratio = min(total_video_duration, fit_dur) / max(total_video_duration, fit_dur)
                        
                        # Fix Priority 3: Do not accept ONLY based on dist < 3000.
                        # Require duration ratio >= 0.7 or length >= video
                        if dist_m < 3000.0:
                            if fit_dur >= total_video_duration * 0.7:
                                is_acceptable = True
                                print(f"[AutoPreflight] Accepted {p.name} on GPS distance: {dist_m:.1f}m, dur_ratio: {gps_duration_ratio:.2f}", flush=True)
            except Exception as exc:
                print(f"[AutoPreflight] GPS check failed for {p.name}: {exc}", flush=True)

        if not is_acceptable:
            continue

        coverage = total_overlap / total_video_duration if total_video_duration > 0 else 0.0

        score = 0.0
        if has_exact_name:
            score += 10000.0
        if total_overlap > 0.0:
            score += 5000.0 + (coverage * 1000.0)
            score -= (start_diff / 60.0)
        elif dist_m is not None:
            # Strong GPS match but broken time
            score += 2000.0 - (dist_m / 10.0) + (gps_duration_ratio * 100.0)
        else:
            score -= (start_diff / 60.0)

        scored_candidates.append({
            "path": p,
            "telem_start": telem_start,
            "telem_end": telem_end,
            "telem_dur": telem_dur,
            "total_overlap": total_overlap,
            "coverage": coverage,
            "start_diff": start_diff,
            "has_exact_name": has_exact_name,
            "score": score,
            "dist_m": dist_m,
        })

    if not scored_candidates:
        return None, {"status": "no_match", "reason": "No local candidates met time criteria"}

    # Sort descending by score
    scored_candidates.sort(key=lambda c: c["score"], reverse=True)
    best = scored_candidates[0]

    return best["path"], {
        "status": "matched",
        "path": best["path"],
        "score": best["score"],
        "has_exact_name": best["has_exact_name"],
        "total_overlap": best["total_overlap"],
        "candidates_count": len(scored_candidates),
    }


def run_auto_telemetry_preflight(
    video_paths: list[Path | str],
    config: dict[str, Any],
    on_status: Callable[[str, str, Optional[str]], None],
    cancel_event: Optional[threading.Event] = None,
    provider_override: Optional[ActivityProvider] = None,
    video_gps_point: Optional[tuple[float, float]] = None,
) -> Optional[Path]:
    """Execute complete auto telemetry preflight:
    1. Probe video timeline
    2. Search local directory for matching FIT/GPX
    3. If local found -> return it immediately (ZERO remote network requests)
    4. If local not found -> check remote cache / query configured remote provider
    """
    if not video_paths:
        return None

    def is_cancelled() -> bool:
        return cancel_event is not None and cancel_event.is_set()

    if is_cancelled():
        return None

    on_status("Wyszukiwanie lokalnych plików FIT/GPX...", "Wyszukiwanie lokalnych plików FIT/GPX...", None)

    # 1. Lightweight video intervals probing
    from src.multifile import probe_clip_time_interval
    intervals: list[tuple[datetime, datetime, float, str]] = []
    for p_str in video_paths:
        if is_cancelled():
            return None
        p = Path(p_str)
        try:
            s_dt, e_dt, dur_s, conf = probe_clip_time_interval(p)
            if s_dt is not None:
                intervals.append((s_dt, e_dt or (s_dt + timedelta(seconds=dur_s or 600.0)), dur_s, conf))
        except Exception as exc:
            print(f"[AutoPreflight] Error probing video {p.name}: {exc}", flush=True)

    if is_cancelled():
        return None

    # Try to extract video GPS point for matching if not provided
    if video_gps_point is None:
        try:
            from src.telemetry_native_gpmf import extract_gpmf_native
            ndata = extract_gpmf_native(video_paths[0])
            if ndata and ndata.get("gps_track"):
                pt = ndata["gps_track"][0]
                video_gps_point = (pt[1], pt[2])
                print(f"[AutoPreflight] Extracted video GPS point: {video_gps_point}", flush=True)
        except Exception as e:
            print(f"[AutoPreflight] Could not extract video GPS: {e}", flush=True)

    if is_cancelled():
        return None

    # 2. Local search in video folder
    parent_dir = Path(video_paths[0]).parent
    matched_local, diag = scan_and_match_local_telemetry(
        video_paths=video_paths,
        intervals=intervals,
        directory=parent_dir,
        on_status=lambda field_st, row_st: on_status(field_st, row_st, None),
        video_gps_point=video_gps_point,
    )

    if is_cancelled():
        return None

    if matched_local is not None:
        on_status(f"Znaleziono dopasowaną aktywność: {matched_local.name}", f"Znaleziono dopasowaną aktywność: {matched_local.name}", str(matched_local))
        print(f"[AutoPreflight] Local telemetry matched: {matched_local.name} (score: {diag.get('score', 0)})", flush=True)
        return matched_local

    # 3. Local search miss -> Check Remote Provider
    source = str(config.get("auto_activity_source", "none") or "none").lower()

    if source in ("none", "", "nic"):
        on_status("Nie znaleziono pasującego pliku FIT/GPX.", "Nie znaleziono pasującego pliku FIT/GPX.", None)
        print("[AutoPreflight] Source=none -> No remote search performed.", flush=True)
        return None

    # Check remote cache before any remote network call
    cached = remote_cache.find_cached_video_telemetry(video_paths)
    if cached is not None:
        _prov, _act_id, cached_path = cached
        on_status(f"Znaleziono dopasowaną aktywność: {cached_path.name}", f"Znaleziono dopasowaną aktywność: {cached_path.name}", str(cached_path))
        print(f"[AutoPreflight] Remote cache hit: {cached_path.name}", flush=True)
        return cached_path

    if is_cancelled():
        return None

    # Remote provider flow
    if source == "garmin":
        on_status("Wyszukiwanie aktywności w Garmin Connect...", "Wyszukiwanie aktywności w Garmin Connect...", None)
        provider: ActivityProvider
        if provider_override is not None:
            provider = provider_override
        else:
            provider = GarminProvider()

        # Check session / connection without popping up UI
        try:
            connected = provider.connect()
        except Exception:
            connected = False

        if not connected:
            on_status("Brak autoryzacji (Garmin Connect)", "Brak autoryzacji. Zaloguj się w ustawieniach Garmin Connect.", None)
            return None

        if is_cancelled():
            return None

        on_status("Wyszukiwanie aktywności w Garmin Connect...", "Wyszukiwanie aktywności w Garmin Connect...", None)

        if not intervals:
            on_status("Nie znaleziono pasującego pliku FIT/GPX.", "Nie znaleziono pasującego pliku FIT/GPX.", None)
            return None

        v_start = min(s for s, _, _, _ in intervals)
        v_end = max(e for _, e, _, _ in intervals)
        v_dur = sum(d for _, _, d, _ in intervals)

        try:
            on_status("Wyszukiwanie aktywności w Garmin Connect...", "Wyszukiwanie aktywności w Garmin Connect...", None)
            window_start = v_start - timedelta(hours=2)
            window_end = v_end + timedelta(hours=2)
            candidates = provider.list_activities(window_start, window_end)

            if is_cancelled():
                return None

            if not candidates:
                on_status("Nie znaleziono pasującego pliku FIT/GPX.", "Nie znaleziono pasującego pliku FIT/GPX.", None)
                return None

            decision, ranked = rank_and_evaluate_candidates(
                candidates,
                v_start,
                v_end,
                video_gps_point=video_gps_point,
            )

            if not ranked:
                on_status("Nie znaleziono pasującego pliku FIT/GPX.", "Nie znaleziono pasującego pliku FIT/GPX.", None)
                return None

            best_cand, best_score = ranked[0]
            if is_cancelled():
                return None

            on_status("Pobieranie aktywności z Garmin Connect...", "Pobieranie aktywności z Garmin Connect...", None)
            dest_dir = remote_cache.get_provider_cache_dir("garmin")
            downloaded_file = provider.download_telemetry(best_cand.activity_id, dest_dir)

            if is_cancelled():
                return None

            remote_cache.save_cached_video_telemetry(
                video_paths,
                "garmin",
                best_cand.activity_id,
                downloaded_file,
                metadata={
                    "name": best_cand.name,
                    "sport_type": best_cand.sport_type,
                    "duration_s": best_cand.duration_s,
                    "match_score": best_score,
                    "start_dt": best_cand.start_dt.isoformat(),
                },
            )

            on_status(f"Znaleziono dopasowaną aktywność: {downloaded_file.name}", f"Znaleziono dopasowaną aktywność: {downloaded_file.name}", str(downloaded_file))
            print(f"[AutoPreflight] Garmin FIT downloaded successfully: {downloaded_file.name}", flush=True)
            return downloaded_file

        except Exception as exc:
            err_str = str(exc).lower()
            if "połączen" in err_str or "connection" in err_str or "timeout" in err_str or "offline" in err_str:
                on_status("Błąd sieci (Garmin Connect)", "Błąd sieci. Sprawdź połączenie z internetem.", None)
            elif "sesj" in err_str or "auth" in err_str or "zaloguj" in err_str:
                on_status("Brak autoryzacji (Garmin Connect)", "Brak autoryzacji. Zaloguj się w ustawieniach Garmin Connect.", None)
            else:
                on_status("Błąd pobierania (Garmin Connect)", "Garmin Connect: Błąd dostępu do usługi lub pobierania telemetrii.", None)
            print(f"[AutoPreflight] Garmin fetch failed: {exc}", flush=True)
            return None

    elif source == "strava":
        on_status("Brak lokalnej telemetrii — sprawdzam Strava...", "Brak lokalnego FIT/GPX — sprawdzanie Strava...", None)
        client_id = config.get("strava_client_id", "")
        if not client_id and provider_override is None:
            on_status("Strava: autoryzacja wygasła", "Strava: brak Client ID w Ustawieniach.", None)
            return None

        if provider_override is not None:
            provider = provider_override
        else:
            provider = StravaProvider(client_id=client_id)

        try:
            connected = provider.connect()
        except Exception:
            connected = False

        if not connected:
            on_status("Strava: autoryzacja wygasła", "Strava: brak autoryzacji lub wygasły token (zaloguj się w Ustawieniach).", None)
            return None

        if is_cancelled():
            return None

        if not intervals:
            on_status("Strava: brak pasującej aktywności", "Strava: nie udało się ustalić czasu filmu.", None)
            return None

        v_start = min(s for s, _, _, _ in intervals)
        v_end = max(e for _, e, _, _ in intervals)

        try:
            on_status("Szukam aktywności Strava...", "Strava: szukanie aktywności w oknie czasowym filmu…", None)
            window_start = v_start - timedelta(hours=2)
            window_end = v_end + timedelta(hours=2)
            candidates = provider.list_activities(window_start, window_end)

            if is_cancelled():
                return None

            if not candidates:
                on_status("Strava: brak pasującej aktywności", "Strava: nie znaleziono aktywności w oknie ±2h.", None)
                return None

            decision, ranked = rank_and_evaluate_candidates(
                candidates,
                v_start,
                v_end,
                video_gps_point=video_gps_point,
            )

            if not ranked:
                on_status("Strava: brak pasującej aktywności", "Strava: brak pasującej aktywności.", None)
                return None

            best_cand, best_score = ranked[0]
            if is_cancelled():
                return None

            on_status("Znaleziono aktywność — pobieram dane...", f"Pobieranie aktywności Strava {best_cand.activity_id}...", None)
            on_status("Przetwarzam dane Strava...", "Przetwarzanie strumieni danych Strava do GPX…", None)

            dest_dir = remote_cache.get_provider_cache_dir("strava")
            downloaded_file = provider.download_telemetry(best_cand.activity_id, dest_dir)

            if is_cancelled():
                return None

            remote_cache.save_cached_video_telemetry(
                video_paths,
                "strava",
                best_cand.activity_id,
                downloaded_file,
                metadata={
                    "name": best_cand.name,
                    "sport_type": best_cand.sport_type,
                    "duration_s": best_cand.duration_s,
                    "match_score": best_score,
                    "start_dt": best_cand.start_dt.isoformat(),
                },
            )

            on_status("Strava GPX gotowy ✓", f"Gotowe — {downloaded_file.name}", str(downloaded_file))
            print(f"[AutoPreflight] Strava GPX created successfully: {downloaded_file.name}", flush=True)
            return downloaded_file

        except Exception as exc:
            err_str = str(exc).lower()
            if "połączen" in err_str or "connection" in err_str or "timeout" in err_str:
                on_status("Strava: brak połączenia", "Strava: brak połączenia z siecią.", None)
            elif "auth" in err_str or "token" in err_str:
                on_status("Strava: autoryzacja wygasła", "Strava: autoryzacja wygasła.", None)
            else:
                on_status("Nie znaleziono telemetrii", "Strava: błąd pobierania telemetrii.", None)
            print(f"[AutoPreflight] Strava fetch failed: {exc}", flush=True)
            return None

    return None
