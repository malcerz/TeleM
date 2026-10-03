"""Strava activity provider for BikeRideHUD using OAuth 2.0 and activity streams."""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from http.server import HTTPServer, BaseHTTPRequestHandler
import json
from pathlib import Path
import threading
import time
from typing import Any, Optional
import urllib.parse
import webbrowser

import requests

from src.integrations.activity_provider import ActivityCandidate, ActivityProvider
from src.integrations import credential_store

STRAVA_AUTH_URL = "https://www.strava.com/oauth/authorize"
STRAVA_TOKEN_URL = "https://www.strava.com/oauth/token"
STRAVA_API_BASE = "https://www.strava.com/api/v3"
DEFAULT_TIMEOUT = (5.0, 15.0)  # (connect_timeout, read_timeout)


class _OAuthCallbackHandler(BaseHTTPRequestHandler):
    auth_code: Optional[str] = None
    auth_error: Optional[str] = None

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)

        if "code" in params:
            _OAuthCallbackHandler.auth_code = params["code"][0]
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            html = """<html><body style="font-family: sans-serif; text-align: center; padding: 40px;">
                <h2 style="color: #2e7d32;">Autoryzacja Strava zakończona sukcesem!</h2>
                <p>Możesz zamknąć to okno przeglądarki i wrócić do BikeRideHUD.</p>
            </body></html>"""
            self.wfile.write(html.encode("utf-8"))
        elif "error" in params:
            _OAuthCallbackHandler.auth_error = params["error"][0]
            self.send_response(400)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            html = f"""<html><body style="font-family: sans-serif; text-align: center; padding: 40px;">
                <h2 style="color: #c62828;">Błąd autoryzacji Strava</h2>
                <p>{params['error'][0]}</p>
            </body></html>"""
            self.wfile.write(html.encode("utf-8"))
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format: str, *args: Any) -> None:
        # Suppress standard HTTP server console logging
        pass


def run_strava_oauth_flow(
    client_id: str,
    client_secret: str,
    port: int = 8765,
    timeout_seconds: int = 120,
) -> tuple[bool, str]:
    """Execute interactive OAuth 2.0 flow via local redirect listener."""
    if not client_id or not client_secret:
        return False, "Wymagane są Client ID oraz Client Secret."

    _OAuthCallbackHandler.auth_code = None
    _OAuthCallbackHandler.auth_error = None

    redirect_uri = f"http://localhost:{port}/callback"
    auth_url = (
        f"{STRAVA_AUTH_URL}?"
        f"client_id={urllib.parse.quote(client_id)}&"
        f"response_type=code&"
        f"redirect_uri={urllib.parse.quote(redirect_uri)}&"
        f"approval_prompt=auto&"
        f"scope=read,activity:read_all"
    )

    try:
        server = HTTPServer(("localhost", port), _OAuthCallbackHandler)
        server.timeout = 2.0
    except Exception as exc:
        return False, f"Nie można uruchomić lokalnego serwera na porcie {port}: {exc}"

    print(f"[Strava] Otwieranie przeglądarki do autoryzacji: {redirect_uri}", flush=True)
    webbrowser.open(auth_url)

    start_wait = time.time()
    try:
        while time.time() - start_wait < timeout_seconds:
            server.handle_request()
            if _OAuthCallbackHandler.auth_code or _OAuthCallbackHandler.auth_error:
                break
    finally:
        server.server_close()

    code = _OAuthCallbackHandler.auth_code
    if not code:
        err = _OAuthCallbackHandler.auth_error or "Przekroczono limit czasu oczekiwania na autoryzację."
        return False, err

    # Exchange code for access & refresh tokens
    try:
        resp = requests.post(
            STRAVA_TOKEN_URL,
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "code": code,
                "grant_type": "authorization_code",
            },
            timeout=DEFAULT_TIMEOUT,
        )
        if resp.status_code != 200:
            return False, f"Błąd wymiany tokenu (HTTP {resp.status_code}): {resp.text}"

        data = resp.json()
        credential_store.save_strava_client_secret(client_secret)
        credential_store.save_strava_tokens(data)

        athlete = data.get("athlete", {})
        first = athlete.get("firstname", "")
        last = athlete.get("lastname", "")
        name = f"{first} {last}".strip() or "Użytkownik Strava"
        print(f"[Strava] Autoryzacja udana: {name}", flush=True)
        return True, name
    except Exception as exc:
        return False, f"Błąd komunikacji z API Strava: {exc}"


class StravaProvider(ActivityProvider):
    """ActivityProvider implementation for Strava."""

    provider_name: str = "strava"

    def __init__(self, client_id: str = "") -> None:
        self.client_id = client_id

    def _get_valid_token(self) -> Optional[str]:
        tokens = credential_store.get_strava_tokens()
        if not tokens:
            return None

        access_token = tokens.get("access_token")
        refresh_token = tokens.get("refresh_token")
        expires_at = tokens.get("expires_at", 0)

        # If token expires in less than 5 minutes, refresh it
        now = time.time()
        if now >= (expires_at - 300):
            if not refresh_token:
                return None
            client_secret = credential_store.get_strava_client_secret()
            if not client_secret or not self.client_id:
                return None
            try:
                resp = requests.post(
                    STRAVA_TOKEN_URL,
                    data={
                        "client_id": self.client_id,
                        "client_secret": client_secret,
                        "grant_type": "refresh_token",
                        "refresh_token": refresh_token,
                    },
                    timeout=DEFAULT_TIMEOUT,
                )
                if resp.status_code == 200:
                    new_tokens = resp.json()
                    # Preserve athlete info if present
                    if "athlete" not in new_tokens and "athlete" in tokens:
                        new_tokens["athlete"] = tokens["athlete"]
                    credential_store.save_strava_tokens(new_tokens)
                    return new_tokens.get("access_token")
                else:
                    print(f"[Strava] Token refresh failed: HTTP {resp.status_code}", flush=True)
                    return None
            except Exception as exc:
                print(f"[Strava] Token refresh exception: {exc}", flush=True)
                return None

        return access_token

    def connect(self) -> bool:
        return self._get_valid_token() is not None

    def refresh_auth(self) -> bool:
        token = self._get_valid_token()
        return token is not None

    def test_connection(self) -> tuple[bool, str]:
        token = self._get_valid_token()
        if not token:
            return False, "Brak ważnego tokenu autoryzacji Strava (wymagane [Połącz ze Strava])."

        try:
            resp = requests.get(
                f"{STRAVA_API_BASE}/athlete",
                headers={"Authorization": f"Bearer {token}"},
                timeout=DEFAULT_TIMEOUT,
            )
            if resp.status_code == 200:
                ath = resp.json()
                name = f"{ath.get('firstname', '')} {ath.get('lastname', '')}".strip() or "Użytkownik Strava"
                return True, name
            return False, f"Błąd API Strava (HTTP {resp.status_code})"
        except Exception as exc:
            return False, f"Błąd połączenia: {exc}"

    def list_activities(
        self,
        start_dt: datetime,
        end_dt: datetime,
    ) -> list[ActivityCandidate]:
        token = self._get_valid_token()
        if not token:
            return []

        after = int(start_dt.timestamp())
        before = int(end_dt.timestamp())

        try:
            resp = requests.get(
                f"{STRAVA_API_BASE}/athlete/activities",
                headers={"Authorization": f"Bearer {token}"},
                params={"after": after, "before": before, "per_page": 30},
                timeout=DEFAULT_TIMEOUT,
            )
            if resp.status_code != 200:
                print(f"[Strava] List activities failed: HTTP {resp.status_code}", flush=True)
                return []
            items = resp.json()
        except Exception as exc:
            print(f"[Strava] List activities exception: {exc}", flush=True)
            return []

        candidates: list[ActivityCandidate] = []
        for item in items:
            try:
                act_id = str(item.get("id", ""))
                name = item.get("name", "Aktywność Strava")
                sport = item.get("sport_type") or item.get("type", "Ride")
                duration = float(item.get("elapsed_time", 0.0) or item.get("moving_time", 0.0))
                distance = float(item.get("distance", 0.0) or 0.0)

                start_date_str = item.get("start_date", "")
                if not start_date_str:
                    continue

                # Parse ISO date '2026-10-02T06:26:47Z'
                if start_date_str.endswith("Z"):
                    start_date_str = start_date_str[:-1] + "+00:00"
                act_start = datetime.fromisoformat(start_date_str).astimezone(timezone.utc)
                act_end = datetime.fromtimestamp(act_start.timestamp() + duration, tz=timezone.utc)

                start_lat = None
                start_lon = None
                latlng = item.get("start_latlng")
                if latlng and isinstance(latlng, (list, tuple)) and len(latlng) >= 2:
                    start_lat = float(latlng[0])
                    start_lon = float(latlng[1])

                candidates.append(
                    ActivityCandidate(
                        activity_id=act_id,
                        provider="strava",
                        name=name,
                        sport_type=sport,
                        start_dt=act_start,
                        end_dt=act_end,
                        duration_s=duration,
                        distance_m=distance,
                        start_lat=start_lat,
                        start_lon=start_lon,
                        raw_data=item,
                    )
                )
            except Exception as exc:
                print(f"[Strava] Parse candidate error: {exc}", flush=True)
                continue

        return candidates

    def download_telemetry(self, activity_id: str, dest_dir: Path) -> Path:
        """Download Strava streams and generate a GPX file."""
        token = self._get_valid_token()
        if not token:
            raise RuntimeError("Brak autoryzacji Strava.")

        dest_dir.mkdir(parents=True, exist_ok=True)
        gpx_target = dest_dir / f"{activity_id}.gpx"
        json_target = dest_dir / f"{activity_id}.json"

        # 1. Fetch activity details for exact start timestamp
        act_resp = requests.get(
            f"{STRAVA_API_BASE}/activities/{activity_id}",
            headers={"Authorization": f"Bearer {token}"},
            timeout=DEFAULT_TIMEOUT,
        )
        if act_resp.status_code != 200:
            raise RuntimeError(f"Nie udało się pobrać szczegółów aktywności Strava {activity_id} (HTTP {act_resp.status_code})")
        act_info = act_resp.json()

        start_date_str = act_info.get("start_date", "")
        if start_date_str.endswith("Z"):
            start_date_str = start_date_str[:-1] + "+00:00"
        act_start = datetime.fromisoformat(start_date_str).astimezone(timezone.utc)

        # 2. Fetch streams
        stream_keys = "time,latlng,distance,altitude,velocity_smooth,heartrate,cadence,watts,temp,moving"
        streams_resp = requests.get(
            f"{STRAVA_API_BASE}/activities/{activity_id}/streams",
            headers={"Authorization": f"Bearer {token}"},
            params={"keys": stream_keys, "key_by_type": "true"},
            timeout=DEFAULT_TIMEOUT,
        )
        if streams_resp.status_code != 200:
            raise RuntimeError(f"Nie udało się pobrać strumieni Strava dla aktywności {activity_id} (HTTP {streams_resp.status_code})")
        streams_data = streams_resp.json()

        # Cache raw streams JSON
        try:
            json_target.write_text(json.dumps(streams_data, indent=2), encoding="utf-8")
        except Exception:
            pass

        # 3. Generate GPX file from streams
        gpx_content = _convert_strava_streams_to_gpx(act_start, streams_data)
        gpx_target.write_text(gpx_content, encoding="utf-8")
        print(f"[Strava] Zapisano GPX z aktywności Strava: {gpx_target}", flush=True)

        return gpx_target


def _convert_strava_streams_to_gpx(act_start: datetime, streams: dict[str, Any]) -> str:
    """Convert Strava stream arrays to a standard GPX file string."""
    time_stream = streams.get("time", {}).get("data", [])
    latlng_stream = streams.get("latlng", {}).get("data", [])
    alt_stream = streams.get("altitude", {}).get("data", [])
    hr_stream = streams.get("heartrate", {}).get("data", [])
    cad_stream = streams.get("cadence", {}).get("data", [])
    watts_stream = streams.get("watts", {}).get("data", [])
    temp_stream = streams.get("temp", {}).get("data", [])
    vel_stream = streams.get("velocity_smooth", {}).get("data", [])

    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<gpx version="1.1" creator="BikeRideHUD Strava Sync" xmlns="http://www.topografix.com/GPX/1/1"',
        '     xmlns:gpxtpx="http://www.garmin.com/xmlschemas/TrackPointExtension/v1">',
        '  <trk>',
        '    <trkseg>',
    ]

    n_points = len(time_stream)
    for i in range(n_points):
        rel_s = time_stream[i]
        pt_dt = act_start + timedelta(seconds=float(rel_s))
        iso_time = pt_dt.strftime("%Y-%m-%dT%H:%M:%SZ")

        lat = 0.0
        lon = 0.0
        if i < len(latlng_stream) and latlng_stream[i] and len(latlng_stream[i]) >= 2:
            lat = float(latlng_stream[i][0])
            lon = float(latlng_stream[i][1])

        ele_str = ""
        if i < len(alt_stream) and alt_stream[i] is not None:
            ele_str = f"      <ele>{float(alt_stream[i]):.1f}</ele>\n"

        ext_parts = []
        gpxtpx_parts = []

        if i < len(hr_stream) and hr_stream[i] is not None:
            gpxtpx_parts.append(f"<gpxtpx:hr>{int(round(hr_stream[i]))}</gpxtpx:hr>")
        if i < len(cad_stream) and cad_stream[i] is not None:
            gpxtpx_parts.append(f"<gpxtpx:cad>{int(round(cad_stream[i]))}</gpxtpx:cad>")
        if i < len(vel_stream) and vel_stream[i] is not None:
            gpxtpx_parts.append(f"<gpxtpx:speed>{float(vel_stream[i]):.2f}</gpxtpx:speed>")
        if i < len(temp_stream) and temp_stream[i] is not None:
            gpxtpx_parts.append(f"<gpxtpx:atemp>{float(temp_stream[i]):.1f}</gpxtpx:atemp>")

        if gpxtpx_parts:
            ext_parts.append(f"        <gpxtpx:TrackPointExtension>{''.join(gpxtpx_parts)}</gpxtpx:TrackPointExtension>")

        if i < len(watts_stream) and watts_stream[i] is not None:
            ext_parts.append(f"        <power>{int(round(watts_stream[i]))}</power>")

        extensions_xml = ""
        if ext_parts:
            extensions_xml = "      <extensions>\n" + "\n".join(ext_parts) + "\n      </extensions>\n"

        pt_xml = (
            f'    <trkpt lat="{lat:.7f}" lon="{lon:.7f}">\n'
            f'{ele_str}'
            f'      <time>{iso_time}</time>\n'
            f'{extensions_xml}'
            f'    </trkpt>'
        )
        lines.append(pt_xml)

    lines.append('    </trkseg>')
    lines.append('  </trk>')
    lines.append('</gpx>')

    return "\n".join(lines)
