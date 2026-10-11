"""Automatic telemetry preflight searching local directory and remote providers immediately on MP4 selection."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import math
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
    on_needs_selection: Optional[Callable[[list[tuple[Any, float]]], Any]] = None,
) -> tuple[Optional[Path], dict[str, Any]]:
    """Rank local FIT/GPX candidates and refuse weak or ambiguous auto-match."""
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
    if not norm_intervals:
        return None, {"status": "no_intervals", "reason": "No video intervals provided"}

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

        # Time-only matches must overlap or fall within the configured window.
        # A same-basename label is useful for ranking, but cannot make a stale
        # or clock-reset timestamp acceptable by itself.
        is_acceptable = False
        dist_m = None
        gps_lat = gps_lon = None
        gps_duration_ratio = 0.0

        if total_overlap > 0.0:
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
                        gps_lat, gps_lon = float(first_pt[1]), float(first_pt[2])
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

        scored_candidates.append({
            "path": p,
            "telem_start": telem_start,
            "telem_end": telem_end,
            "telem_dur": telem_dur,
            "total_overlap": total_overlap,
            "coverage": coverage,
            "start_diff": start_diff,
            "has_exact_name": has_exact_name,
            "dist_m": dist_m,
            "gps_lat": gps_lat,
            "gps_lon": gps_lon,
        })

    if not scored_candidates:
        return None, {"status": "no_match", "reason": "No local candidates met time criteria"}

    from src.integrations.activity_matcher import rank_and_evaluate_candidates
    gps_fallback_rows = [row for row in scored_candidates if row.get("dist_m") is not None]
    ranking_rows = gps_fallback_rows or scored_candidates
    candidates: list[ActivityCandidate] = []
    for row in ranking_rows:
        p = row["path"]
        candidates.append(ActivityCandidate(
            activity_id=str(p.resolve()), provider="local", name=p.name,
            sport_type="FIT" if p.suffix.lower() == ".fit" else "GPX",
            start_dt=row["telem_start"], end_dt=row["telem_end"],
            duration_s=float(row["telem_dur"]),
            start_lat=row.get("gps_lat"), start_lon=row.get("gps_lon"),
            raw_data={"path": str(p.resolve()), **row},
        ))

    # Broken/naive camera time and filesystem mtime are suggestion anchors only.
    low_confidence_time = any(
        len(item) > 3 and str(item[3]).lower() not in ("exact", "estimated")
        for item in intervals
    )
    decision, ranked = rank_and_evaluate_candidates(
        candidates, video_earliest, video_latest,
        video_gps_point=video_gps_point,
        ignore_time_match=bool(gps_fallback_rows),
    )
    if not ranked or decision == "NO_MATCH":
        return None, {"status": "no_match", "reason": "No local candidates met safe match criteria"}

    if low_confidence_time or decision == "NEEDS_SELECTION":
        selected = on_needs_selection(ranked) if on_needs_selection else None
        if selected is not None:
            selected_path = Path(selected.raw_data.get("path", ""))
            if selected_path in [Path(candidate.raw_data["path"]) for candidate, _score in ranked]:
                return selected_path, {"status": "selected", "ranked": ranked}
        return None, {
            "status": "selection_cancelled" if on_needs_selection else "needs_selection",
            "ranked": ranked,
            "reason": "Low-confidence video time" if low_confidence_time else "Close local candidates",
        }

    best, best_score = ranked[0]
    return Path(best.raw_data["path"]), {
        "status": "matched", "path": Path(best.raw_data["path"]),
        "score": best_score, "candidates_count": len(ranked),
        "ranked": ranked,
    }


def resolve_local_fit(
    video_paths: list[Path | str],
    intervals: Optional[list[tuple[datetime, datetime, float, str]]] = None,
    directory: Path | str | None = None,
    on_status: Optional[Callable[[str, str], None]] = None,
    on_needs_selection: Optional[Callable[[list[tuple[Any, float]]], Any]] = None,
    video_gps_point: Optional[tuple[float, float]] = None,
    return_diagnostics: bool = False,
) -> Path | None | tuple[Path | None, dict[str, Any]]:
    """Resolve local telemetry through the existing matcher (non-recursive).

    When no directory is supplied, only the source MP4 parent directory is
    searched. The preflight coordinator calls this for each already-approved
    local search directory, keeping configured/Garmin folder policy centralized.
    """
    from src.multifile import probe_clip_time_interval
    paths = [Path(p) for p in video_paths]
    if intervals is None:
        intervals = []
        for path in paths:
            start, end, duration, confidence = probe_clip_time_interval(path)
            if start is not None:
                intervals.append((start, end or start + timedelta(seconds=duration or 600), duration, confidence))
    if not paths:
        result = (None, {"status": "no_video"})
        return result if return_diagnostics else None
    search_dir = Path(directory) if directory is not None else paths[0].parent
    result = scan_and_match_local_telemetry(
        paths, intervals, search_dir, on_status=on_status,
        video_gps_point=video_gps_point,
        on_needs_selection=on_needs_selection,
    )
    return result if return_diagnostics else result[0]


def run_auto_telemetry_preflight(
    video_paths: list[Path | str],
    config: dict[str, Any],
    on_status: Callable[[str, str, Optional[str]], None],
    on_needs_selection: Optional[Callable[[list[tuple[Any, float]]], Any]] = None,
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
            from src.telemetry_native_gpmf import get_gpmf_light_metadata
            light_meta = get_gpmf_light_metadata(video_paths[0])
            if light_meta and light_meta.get("first_gps"):
                video_gps_point = light_meta["first_gps"]
                print(f"[AutoPreflight] Extracted video GPS point: {video_gps_point}", flush=True)
        except Exception as e:
            print(f"[AutoPreflight] Could not extract video GPS: {e}", flush=True)

    if video_gps_point is not None:
        try:
            lat, lon = float(video_gps_point[0]), float(video_gps_point[1])
            if not (math.isfinite(lat) and math.isfinite(lon) and -90 <= lat <= 90 and -180 <= lon <= 180):
                video_gps_point = None
            else:
                video_gps_point = (lat, lon)
        except (TypeError, ValueError, IndexError):
            video_gps_point = None

    if is_cancelled():
        return None

    # 2. Local search in configured and video folders
    parent_dir = Path(video_paths[0]).parent
    
    search_dirs = [parent_dir]
    
    cfg_tel_dir = config.get("telemetry_dir")
    if cfg_tel_dir:
        p = Path(cfg_tel_dir)
        if p.exists() and p.is_dir() and p not in search_dirs:
            search_dirs.append(p)

    # Previously downloaded provider activities are valid local candidates too;
    # rank them by the same timestamp rules rather than requiring an old
    # video-to-cache association to exist.
    for provider_name in ("garmin", "strava"):
        try:
            cached_dir = remote_cache.get_provider_cache_dir(provider_name)
        except Exception:
            continue
        if cached_dir.is_dir() and cached_dir not in search_dirs:
            search_dirs.append(cached_dir)
            
    import psutil
    for part in psutil.disk_partitions(all=False):
        if 'cdrom' in part.opts or part.fstype == '':
            continue
        p1 = Path(part.mountpoint) / "Garmin" / "Activities"
        if p1.exists() and p1.is_dir() and p1 not in search_dirs:
            search_dirs.append(p1)
        p2 = Path(part.mountpoint) / "Garmin" / "Activity"
        if p2.exists() and p2.is_dir() and p2 not in search_dirs:
            search_dirs.append(p2)
            
    local_ranked: list[tuple[ActivityCandidate, float]] = []
    for search_dir in search_dirs:
        if is_cancelled():
            return None
            
        on_status(f"Wyszukiwanie lokalnych plików FIT/GPX...", f"Przeszukiwanie: {search_dir}...", None)
        
        local_result = resolve_local_fit(
            video_paths=video_paths,
            intervals=intervals,
            directory=search_dir,
            on_status=lambda st, lg: on_status(st, lg, None),
            video_gps_point=video_gps_point,
            return_diagnostics=True,
        )
        # Keep test/plugin monkeypatch compatibility with callers that replace
        # the path-only public resolver.
        m_loc, m_diag = local_result if isinstance(local_result, tuple) else (local_result, {})
        local_ranked.extend(m_diag.get("ranked") or [])
        # A path-only replacement resolver is retained for integrations/tests.
        if m_loc is not None and not m_diag.get("ranked"):
            p = Path(m_loc)
            try:
                start, end, duration = probe_fit_time_range(p)
            except Exception:
                start = end = None
                duration = 0.0
            if start is not None and end is not None:
                local_ranked.append((ActivityCandidate(
                    activity_id=str(p.resolve()), provider="local", name=p.name,
                    sport_type=p.suffix.lstrip(".").upper(), start_dt=start,
                    end_dt=end, duration_s=float(duration), raw_data={"path": str(p.resolve())},
                ), 1.0))

    # Deduplicate paths found through overlapping configured/Garmin locations,
    # then arbitrate across all locations rather than accepting the first one.
    unique_local: dict[str, ActivityCandidate] = {}
    for candidate, _score in local_ranked:
        candidate_path = str(Path(candidate.raw_data.get("path", "")).resolve())
        if candidate_path:
            unique_local.setdefault(candidate_path, candidate)

    if unique_local and intervals:
        v_start = min(s for s, _, _, _ in intervals)
        v_end = max(e for _, e, _, _ in intervals)
        local_decision, all_local_ranked = rank_and_evaluate_candidates(
            list(unique_local.values()), v_start, v_end, video_gps_point=video_gps_point,
        )
        if all_local_ranked and local_decision != "NO_MATCH":
            force_selection = local_decision == "NEEDS_SELECTION" or any(
                confidence not in ("exact", "estimated")
                for _, _, _, confidence in intervals
            )
            selected_pair = None
            if force_selection:
                chosen = on_needs_selection(all_local_ranked) if on_needs_selection else None
                selected_pair = next(
                    ((c, score) for c, score in all_local_ranked
                     if chosen is not None and c.activity_id == getattr(chosen, "activity_id", None)),
                    None,
                )
                if selected_pair is None:
                    on_status(
                        "Wymaga wyboru aktywności",
                        "Dopasowanie jest niejednoznaczne lub czas filmu ma niską wiarygodność. Wybierz aktywność ręcznie.",
                        None,
                    )
                    return None
            else:
                selected_pair = all_local_ranked[0]

            matched_local = Path(selected_pair[0].raw_data["path"])
            diag = {"status": "selected" if force_selection else "matched",
                    "score": selected_pair[1], "ranked": all_local_ranked}
            on_status(f"Znaleziono dopasowaną aktywność: {matched_local.name}", f"Znaleziono dopasowaną aktywność: {matched_local.name}", str(matched_local))
            print(f"[AutoPreflight] Local telemetry matched: {matched_local.name} (score: {diag.get('score', 0)})", flush=True)
            return matched_local

    # Without a usable video date, time-only remote searches are not safe.
    # Do not search an arbitrary current/recent window or associate by filename.
    if not intervals:
        on_status(
            "Brak wiarygodnego czasu filmu",
            "Nie można bezpiecznie dopasować aktywności bez czasu nagrania. Wybierz FIT/GPX ręcznie.",
            None,
        )
        return None

    low_confidence_time = any(confidence not in ("exact", "estimated") for _, _, _, confidence in intervals)

    # 3. Local search miss -> Check Remote Provider
    source = str(config.get("auto_activity_source", "none") or "none").lower()

    if source in ("none", "", "nic"):
        on_status("Nie znaleziono lokalnego FIT/GPX", "Nie znaleziono lokalnych plików, a wyszukiwanie online jest wyłączone.", None)
        print("[AutoPreflight] Source=none -> No remote search performed.", flush=True)
        return None

    # Check remote cache before any remote network call
    cached = remote_cache.find_cached_video_telemetry(video_paths)
    if cached is not None:
        provider_name, _act_id, cached_path = cached
        provider_label = {"garmin": "Garmin Connect", "strava": "Strava"}.get(
            str(provider_name).lower(), "aktywność online",
        )
        message = f"Znaleziono dopasowaną aktywność {provider_label}: {cached_path.name}"
        on_status(f"{message} ✓", message, str(cached_path))
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
        try:
            on_status("Wyszukiwanie aktywności w Garmin Connect...", "Wyszukiwanie aktywności w Garmin Connect...", None)
            window_start = v_start - timedelta(hours=2)
            window_end = v_end + timedelta(hours=2)
            candidates = provider.list_activities(window_start, window_end)
            
            ignore_time_match = False
            
            if not candidates and video_gps_point is not None:
                # Fallback: maybe GoPro clock is completely wrong. Let's search recent 45 days.
                on_status("Wyszukiwanie aktywności w Garmin Connect...", "Garmin Connect: szukanie awaryjne (nieprawidłowy zegar kamery)...", None)
                now = datetime.now(timezone.utc)
                fallback_start = now - timedelta(days=45)
                fallback_end = now + timedelta(days=1)
                candidates = provider.list_activities(fallback_start, fallback_end)
                ignore_time_match = True

            if is_cancelled():
                return None

            if not candidates:
                on_status("Nie znaleziono pasującego pliku FIT/GPX.", "Nie znaleziono pasującego pliku FIT/GPX.", None)
                return None

            print(f"[AutoFIT] Znaleziono {len(candidates)} aktywności.", flush=True)
            decision, ranked = rank_and_evaluate_candidates(
                candidates,
                v_start,
                v_end,
                video_gps_point=video_gps_point,
                ignore_time_match=ignore_time_match,
            )

            for cand, score in ranked:
                print(f"[AutoFIT]  - Kandydat {cand.activity_id} ({cand.sport_type}): score={score:.2f}", flush=True)

            if not ranked or decision == "NO_MATCH":
                on_status("Nie znaleziono pasujacego pliku FIT/GPX.", "Znaleziono aktywnosci, ale zadna nie pasuje do nagrania.", None)
                return None
                
            best_cand = None
            best_score = 0.0
            if decision == "NEEDS_SELECTION" or low_confidence_time:
                if on_needs_selection:
                    best_cand = on_needs_selection(ranked)
                if not best_cand:
                    on_status("Nie znaleziono pasującego pliku FIT/GPX.", "Znaleziono kilka aktywności (dopasowanie niejednoznaczne). Wybierz ręcznie.", None)
                    return None
                if not any(c.activity_id == best_cand.activity_id for c, _ in ranked):
                    on_status("Wymaga wyboru aktywności", "Wybrana aktywność nie należy do aktualnych wyników.", None)
                    return None
                for c, s in ranked:
                    if c.activity_id == getattr(best_cand, "activity_id", None):
                        best_score = s
                        break
            else:
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

            if not ranked or decision == "NO_MATCH":
                on_status("Strava: brak pasującej aktywności", "Strava: brak pasującej aktywności.", None)
                return None

            if decision == "NEEDS_SELECTION" or low_confidence_time:
                best_cand = on_needs_selection(ranked) if on_needs_selection else None
                if best_cand is None:
                    on_status("Wymaga wyboru aktywności", "Dopasowanie Strava jest niejednoznaczne; niczego nie pobrano.", None)
                    return None
                pair = next(((candidate, score) for candidate, score in ranked
                             if candidate.activity_id == best_cand.activity_id), None)
                if pair is None:
                    on_status("Wymaga wyboru aktywności", "Wybrana aktywność nie należy do aktualnych wyników.", None)
                    return None
                best_cand, best_score = pair
            else:
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

    elif source == "none" or not source:
        on_status("Nie znaleziono pasującego pliku FIT/GPX.", "Nie znaleziono lokalnych plików, a wyszukiwanie online jest wyłączone.", None)
        return None
        
    return None
