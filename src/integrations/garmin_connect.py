"""Garmin Connect activity provider for SportCamHUD."""

from __future__ import annotations

import io
from datetime import datetime, timezone
from pathlib import Path
import zipfile

from src.integrations.activity_provider import ActivityCandidate, ActivityProvider
from src.integrations.garmin_auth import GarminAuthClient, GarminAuthError


class GarminProvider(ActivityProvider):
    """ActivityProvider implementation for Garmin Connect."""

    provider_name: str = "garmin"

    auth_mode = "SSO_BROWSER"

    def __init__(self, username: str = "", timeout: float = 20.0, auth=None) -> None:
        # username retained only for compatibility with older callers; not used.
        self.auth = auth if auth is not None else GarminAuthClient(timeout=timeout)
        self.last_error = ""

    def connect(self) -> bool:
        """Restore/refresh the DI session. Never opens a browser automatically."""
        try:
            self.auth.valid_access_token()
            self.last_error = ""
            return True
        except GarminAuthError as exc:
            self.last_error = str(exc)
            return False

    def test_connection(self) -> tuple[bool, str]:
        """Validate the session using the social profile endpoint."""
        try:
            if not self.connect():
                return False, self.last_error
            profile = self.auth.api_get("/userprofile-service/socialProfile").json()
            if not isinstance(profile, dict):
                return False, "Garmin Connect: nieprawidłowa odpowiedź profilu."
            name = profile.get("fullName") or profile.get("displayName") or "Garmin Connect"
            print("[GarminConnect] GARMIN_AUTH=CONNECTED", flush=True)
            return True, str(name)
        except GarminAuthError as exc:
            return False, str(exc)
        except (ValueError, TypeError):
            return False, "Garmin Connect: nieprawidłowa odpowiedź profilu."

    def list_activities(
        self,
        start_dt: datetime,
        end_dt: datetime,
    ) -> list[ActivityCandidate]:
        """Fetch activities in Garmin Connect between start_dt and end_dt."""
        if not self.connect():
            raise GarminAuthError(self.last_error)

        # Format dates as YYYY-MM-DD
        start_str = start_dt.strftime("%Y-%m-%d")
        end_str = end_dt.strftime("%Y-%m-%d")

        raw_activities = []
        # Preserve the date query, but bound pagination to this small time window.
        for offset in range(0, 1000, 100):
            try:
                page = self.auth.api_get("/activitylist-service/activities/search/activities", params={
                    "startDate": start_str, "endDate": end_str,
                    "start": str(offset), "limit": "100",
                }).json()
            except ValueError:
                raise GarminAuthError("Garmin Connect: nieprawidłowa lista aktywności.") from None
            if not isinstance(page, list):
                raise GarminAuthError("Garmin Connect: nieprawidłowa lista aktywności.")
            raw_activities.extend(page)
            if len(page) < 100:
                break
        else:
            raise GarminAuthError("Garmin Connect: zbyt wiele aktywności w wybranym zakresie.")

        if not raw_activities or not isinstance(raw_activities, list):
            return []

        candidates: list[ActivityCandidate] = []
        for item in raw_activities:
            try:
                act_id = str(item.get("activityId", ""))
                if not act_id:
                    continue
                name = item.get("activityName", "Aktywność Garmin")
                sport = item.get("activityType", {}).get("typeKey", "cycling")
                duration = float(item.get("duration", 0.0) or item.get("elapsedDuration", 0.0))
                distance = float(item.get("distance", 0.0) or 0.0)

                # Parse start time (Garmin gives 'startTimeGMT', e.g. '2026-10-02 06:26:47')
                start_raw = item.get("startTimeGMT")
                if not start_raw:
                    continue

                act_start = datetime.fromisoformat(start_raw.strip().replace("Z", "+00:00"))
                if act_start.tzinfo is None:
                    act_start = act_start.replace(tzinfo=timezone.utc)
                act_start = act_start.astimezone(timezone.utc)
                act_end = datetime.fromtimestamp(act_start.timestamp() + duration, tz=timezone.utc)

                lat = item.get("startLatitude")
                lon = item.get("startLongitude")
                start_lat = float(lat) if lat is not None else None
                start_lon = float(lon) if lon is not None else None

                candidates.append(
                    ActivityCandidate(
                        activity_id=act_id,
                        provider="garmin",
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
            except (ValueError, TypeError, AttributeError, OverflowError):
                print("[GarminConnect] Pominięto nieprawidłową pozycję aktywności.", flush=True)
                continue

        print(f"[GarminConnect] GARMIN_ACTIVITY_COUNT={len(candidates)}", flush=True)
        return candidates

    def download_telemetry(self, activity_id: str, dest_dir: Path) -> Path:
        """Download original FIT file from Garmin Connect."""
        if not str(activity_id).isdigit() or int(activity_id) <= 0:
            raise GarminAuthError("Nieprawidłowy identyfikator aktywności Garmin.")
        if not self.connect():
            raise GarminAuthError(self.last_error)

        dest_dir.mkdir(parents=True, exist_ok=True)
        fit_target = dest_dir / f"{activity_id}.fit"

        print(f"[GarminConnect] Pobieranie pliku FIT dla aktywności {activity_id}...", flush=True)
        raw_bytes = self.auth.api_get(f"/download-service/files/activity/{activity_id}").content

        if not raw_bytes:
            raise RuntimeError(f"Pusty plik pobrany z Garmin dla aktywności {activity_id}")

        # Check if the download is a ZIP container
        if raw_bytes.startswith(b"PK\x03\x04"):
            with zipfile.ZipFile(io.BytesIO(raw_bytes)) as zf:
                fit_name = None
                for n in zf.namelist():
                    if n.lower().endswith(".fit"):
                        fit_name = n
                        break
                if not fit_name:
                    raise RuntimeError("W archiwum ZIP z Garmin nie znaleziono pliku .fit")
                fit_content = zf.read(fit_name)
        else:
            # Raw FIT file
            fit_content = raw_bytes

        if len(fit_content) < 12 or fit_content[8:12] != b".FIT":
            raise GarminAuthError("Garmin Connect: pobrany plik nie jest plikiem FIT.")
        fit_target.write_bytes(fit_content)

        print(f"[GarminConnect] Zapisano plik FIT: {fit_target} ({fit_target.stat().st_size} bajtów)", flush=True)
        return fit_target

    def refresh_auth(self) -> bool:
        try:
            self.auth.valid_access_token(force_refresh=True)
            return True
        except GarminAuthError as exc:
            self.last_error = str(exc)
            return False
