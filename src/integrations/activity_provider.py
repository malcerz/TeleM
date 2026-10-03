"""Activity provider base interface and data models for remote telemetry integrations."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional


@dataclass
class ActivityCandidate:
    """Represents a remote activity candidate found in Garmin Connect or Strava."""
    activity_id: str
    provider: str
    name: str
    sport_type: str
    start_dt: datetime
    end_dt: datetime
    duration_s: float
    distance_m: float = 0.0
    start_lat: Optional[float] = None
    start_lon: Optional[float] = None
    raw_data: dict = field(default_factory=dict)

    def display_str(self, score: float = 0.0) -> str:
        time_str = self.start_dt.strftime("%H:%M")
        mins = int(self.duration_s // 60)
        secs = int(self.duration_s % 60)
        dur_str = f"{mins:02d}:{secs:02d}"
        pct_str = f"{int(round(score * 100))}%"
        sport = self.sport_type or "Aktywność"
        return f"{time_str} {sport} ({self.name}) — {dur_str} — {pct_str}"


class ActivityProvider(ABC):
    """Abstract interface for activity providers (Garmin Connect, Strava)."""

    provider_name: str = ""

    @abstractmethod
    def connect(self) -> bool:
        """Establish connection or validate credentials/tokens."""
        pass

    @abstractmethod
    def test_connection(self) -> tuple[bool, str]:
        """Test connection and return (success, message_or_user_name)."""
        pass

    @abstractmethod
    def list_activities(
        self,
        start_dt: datetime,
        end_dt: datetime,
    ) -> list[ActivityCandidate]:
        """Query activities overlapping or near the specified time window."""
        pass

    @abstractmethod
    def download_telemetry(
        self,
        activity_id: str,
        dest_dir: Path,
    ) -> Path:
        """Download telemetry data (FIT or GPX) and return the local Path."""
        pass

    @abstractmethod
    def refresh_auth(self) -> bool:
        """Refresh expired access token or session."""
        pass
