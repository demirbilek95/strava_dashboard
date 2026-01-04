import os
import requests
import dotenv
from typing import List, Dict, Any, Optional

# Load environment variables
dotenv.load_dotenv()


class StravaAPI:
    """Client for Strava API interaction."""

    BASE_URL = "https://www.strava.com/api/v3"

    def __init__(self, access_token: Optional[str] = None):
        """
        Initialize Strava API client.

        Args:
            access_token: Strava access token. If None, reads from env.
        """
        self.access_token = access_token or os.getenv("STRAVA_ACCESS_TOKEN")
        if not self.access_token:
            raise ValueError("Strava access token is required")

        self.session = requests.Session()
        self.session.headers.update({"Authorization": f"Bearer {self.access_token}"})

    def get_athlete(self) -> Dict[str, Any]:
        """Fetch current authenticated athlete."""
        response = self.session.get(f"{self.BASE_URL}/athlete")
        response.raise_for_status()
        return response.json()

    def get_activities(
        self,
        before: Optional[int] = None,
        after: Optional[int] = None,
        page: int = 1,
        per_page: int = 200,
    ) -> List[Dict[str, Any]]:
        """
        Fetch athlete activities.

        Args:
            before: Unix timestamp
            after: Unix timestamp
            page: Page number
            per_page: Items per page (max 200)

        Returns:
            List of activity summary objects
        """
        params = {"page": page, "per_page": per_page}
        if before:
            params["before"] = before
        if after:
            params["after"] = after

        response = self.session.get(f"{self.BASE_URL}/athlete/activities", params=params)
        response.raise_for_status()
        return response.json()

    def get_activity_streams(
        self, activity_id: int, keys: List[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Fetch activity streams.

        Args:
            activity_id: The activity ID
            keys: List of stream types to fetch (e.g. ['time', 'latlng', 'distance', 'altitude', 'velocity_smooth', 'heartrate', 'cadence', 'watts', 'temp', 'moving'])

        Returns:
            List of stream objects or Dictionary depending on keys resolution
            Actually Strava returns a list of stream objects.
        """
        # Default keys if not provided
        if not keys:
            keys = [
                "time",
                "latlng",
                "distance",
                "altitude",
                "velocity_smooth",
                "heartrate",
                "cadence",
                "watts",
                "temp",
                "moving",
            ]

        keys_str = ",".join(keys)
        # key_by_type=true makes it return a dict keyed by stream type, which is easier to handle
        params = {"keys": keys_str, "key_by_type": "true"}

        response = self.session.get(
            f"{self.BASE_URL}/activities/{activity_id}/streams", params=params
        )
        if response.status_code == 404:
            return {}
        response.raise_for_status()
        return response.json()

    def get_all_activities(self) -> List[Dict[str, Any]]:
        """Fetch ALL activities using pagination."""
        all_activities = []
        page = 1
        while True:
            activities = self.get_activities(page=page, per_page=200)
            if not activities:
                break
            all_activities.extend(activities)
            page += 1
        return all_activities
