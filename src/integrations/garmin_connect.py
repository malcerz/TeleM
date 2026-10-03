"""Garmin Connect activity provider for BikeRideHUD."""

from __future__ import annotations

import io
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
import zipfile

from src.integrations.activity_provider import ActivityCandidate, ActivityProvider
from src.integrations import credential_store

try:
    import garminconnect
    _GARMINCONNECT_AVAILABLE = True
except ImportError:
    garminconnect = None
    _GARMINCONNECT_AVAILABLE = False


class GarminProvider(ActivityProvider):
    """ActivityProvider implementation for Garmin Connect."""

    provider_name: str = "garmin"

    def __init__(self, username: str = "", timeout: float = 15.0) -> None:
        self.username = username
        self.timeout = timeout
        self.client: Any = None

    def _init_client(self) -> Any:
        if not _GARMINCONNECT_AVAILABLE or garminconnect is None:
            raise RuntimeError("Biblioteka 'garminconnect' nie jest zainstalowana.")
        return garminconnect.Garmin(self.username, "")

    def connect(self) -> bool:
        """Authenticate with Garmin Connect using cached session or stored password."""
        if not self.username:
            return False

        if not _GARMINCONNECT_AVAILABLE or garminconnect is None:
            return False

        client = self._init_client()
        session_token = credential_store.get_garmin_session()
        logged_in = False

        # 1. Try resuming existing session token
        if session_token:
            try:
                client.login(tokenstore=session_token)
                logged_in = True
            except Exception:
                logged_in = False

        # 2. If token expired or absent, login with username & stored password
        if not logged_in:
            password = credential_store.get_garmin_password()
            if not password:
                return False
            client.password = password
            try:
                client.login()
                logged_in = True
                # Persist new session token if available
                try:
                    if hasattr(client, "client") and hasattr(client.client, "dumps"):
                        token_str = client.client.dumps()
                        if token_str:
                            credential_store.save_garmin_session(token_str)
                except Exception:
                    pass
            except Exception as exc:
                print(f"[GarminConnect] Login failed: {exc}", flush=True)
                return False

        self.client = client
        return True

    def test_connection(self) -> tuple[bool, str]:
        """Test authentication and fetch user full name."""
        try:
            if not self.connect():
                return False, "Nie udało się zalogować do Garmin Connect (sprawdź login i hasło)."
            full_name = self.client.get_full_name() or self.username
            return True, full_name
        except Exception as exc:
            return False, f"Błąd połączenia z Garmin Connect: {exc}"

    def list_activities(
        self,
        start_dt: datetime,
        end_dt: datetime,
    ) -> list[ActivityCandidate]:
        """Fetch activities in Garmin Connect between start_dt and end_dt."""
        if self.client is None and not self.connect():
            return []

        # Format dates as YYYY-MM-DD
        start_str = start_dt.strftime("%Y-%m-%d")
        end_str = end_dt.strftime("%Y-%m-%d")

        try:
            raw_activities = self.client.get_activities_by_date(start_str, end_str)
        except Exception as exc:
            print(f"[GarminConnect] Failed to list activities: {exc}", flush=True)
            return []

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
                start_raw = item.get("startTimeGMT") or item.get("startTimeLocal")
                if not start_raw:
                    continue

                act_start = datetime.strptime(start_raw.strip(), "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
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
            except Exception as exc:
                print(f"[GarminConnect] Failed to parse activity item: {exc}", flush=True)
                continue

        return candidates

    def download_telemetry(self, activity_id: str, dest_dir: Path) -> Path:
        """Download original FIT file from Garmin Connect."""
        if self.client is None and not self.connect():
            raise RuntimeError("Brak połączenia z Garmin Connect.")

        dest_dir.mkdir(parents=True, exist_ok=True)
        fit_target = dest_dir / f"{activity_id}.fit"

        print(f"[GarminConnect] Pobieranie pliku FIT dla aktywności {activity_id}...", flush=True)
        raw_bytes = self.client.download_activity(
            activity_id,
            dl_fmt=garminconnect.Garmin.ActivityDownloadFormat.ORIGINAL,
        )

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
                fit_target.write_bytes(fit_content)
        else:
            # Raw FIT file
            fit_target.write_bytes(raw_bytes)

        print(f"[GarminConnect] Zapisano plik FIT: {fit_target} ({fit_target.stat().st_size} bajtów)", flush=True)
        return fit_target

    def refresh_auth(self) -> bool:
        return self.connect()
