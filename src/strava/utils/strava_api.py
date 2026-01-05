import os
import requests
import dotenv
from typing import List, Dict, Any, Optional
from pathlib import Path


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
        # Load environment variables (done at module level but reload to be safe)
        dotenv.load_dotenv()

        self.client_id = os.getenv("STRAVA_CLIENT_ID")
        self.client_secret = os.getenv("STRAVA_CLIENT_SECRET")
        self.refresh_token = os.getenv("STRAVA_REFRESH_TOKEN")

        self.access_token = access_token or os.getenv("STRAVA_ACCESS_TOKEN")
        if not self.access_token:
            raise ValueError("Strava access token is required")

        self.session = requests.Session()
        self._update_session_header()

    def _update_session_header(self):
        """Update the session header with the current access token."""
        self.session.headers.update({"Authorization": f"Bearer {self.access_token}"})

    def _refresh_access_token(self):
        """Refresh the Strava access token using the refresh token."""
        if not all([self.client_id, self.client_secret, self.refresh_token]):
            raise ValueError("Missing Strava credentials for token refresh")

        refresh_url = "https://www.strava.com/oauth/token"
        payload = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "grant_type": "refresh_token",
            "refresh_token": self.refresh_token,
        }

        response = requests.post(refresh_url, data=payload)
        response.raise_for_status()
        data = response.json()

        self.access_token = data["access_token"]
        self.refresh_token = data.get("refresh_token", self.refresh_token)
        self._update_session_header()

        # Update .env file
        self._update_env_file(self.access_token, self.refresh_token)

    def get_authorization_url(self) -> str:
        """Generate the authorization URL for Strava OAuth."""
        if not self.client_id:
            raise ValueError("STRAVA_CLIENT_ID is not set")

        base_url = "https://www.strava.com/oauth/authorize"
        params = {
            "client_id": self.client_id,
            "redirect_uri": "http://localhost",  # Default redirect URI
            "response_type": "code",
            "approval_prompt": "force",
            "scope": "read,activity:read,activity:read_all",
        }

        from urllib.parse import urlencode

        return f"{base_url}?{urlencode(params)}"

    def exchange_code_for_tokens(self, authorization_code: str):
        """Exchange authorization code for access and refresh tokens."""
        if not all([self.client_id, self.client_secret]):
            raise ValueError("Missing Strava credentials for token exchange")

        token_url = "https://www.strava.com/oauth/token"
        payload = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "code": authorization_code,
            "grant_type": "authorization_code",
        }

        response = requests.post(token_url, data=payload)
        response.raise_for_status()
        data = response.json()

        self.access_token = data["access_token"]
        self.refresh_token = data["refresh_token"]
        self._update_session_header()

        # Update .env file
        self._update_env_file(self.access_token, self.refresh_token)
        return data

    def _update_env_file(self, access_token: str, refresh_token: str):
        """Update the .env file with new tokens."""
        env_path = Path(".env")
        lines = []
        if env_path.exists():
            with open(env_path, "r") as f:
                lines = f.readlines()

        new_lines = []
        updated_access = False
        updated_refresh = False

        for line in lines:
            if line.startswith("STRAVA_ACCESS_TOKEN="):
                new_lines.append(f"STRAVA_ACCESS_TOKEN={access_token}\n")
                updated_access = True
            elif line.startswith("STRAVA_REFRESH_TOKEN="):
                new_lines.append(f"STRAVA_REFRESH_TOKEN={refresh_token}\n")
                updated_refresh = True
            else:
                new_lines.append(line)

        if not updated_access:
            new_lines.append(f"STRAVA_ACCESS_TOKEN={access_token}\n")
        if not updated_refresh:
            new_lines.append(f"STRAVA_REFRESH_TOKEN={refresh_token}\n")

        with open(env_path, "w") as f:
            f.writelines(new_lines)

    def _request(self, method: str, url: str, **kwargs) -> requests.Response:
        """Make an authenticated request with automatic token refresh."""
        response = self.session.request(method, url, **kwargs)

        if response.status_code == 401:
            # Check if it's a scope issue vs expired token
            try:
                error_data = response.json()
                if any(err.get("code") == "missing" for err in error_data.get("errors", [])):
                    # This is a scope issue, refreshing won't help if the grant is limited
                    return response
            except Exception:  # pylint: disable=broad-exception-caught
                pass

            try:
                self._refresh_access_token()
                # Retry once
                response = self.session.request(method, url, **kwargs)
            except Exception as exc:  # pylint: disable=broad-exception-caught
                print(f"Token refresh failed: {exc}")

        return response

    def get_athlete(self) -> Dict[str, Any]:
        """Fetch current authenticated athlete."""
        response = self._request("GET", f"{self.BASE_URL}/athlete")
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

        response = self._request("GET", f"{self.BASE_URL}/athlete/activities", params=params)
        response.raise_for_status()
        return response.json()

    def get_activity_streams(
        self, activity_id: int, keys: List[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Fetch activity streams.

        Args:
            activity_id: The activity ID
            keys: List of stream types to fetch
        """
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
        params = {"keys": keys_str, "key_by_type": "true"}

        response = self._request(
            "GET", f"{self.BASE_URL}/activities/{activity_id}/streams", params=params
        )
        if response.status_code == 404:
            return {}
        response.raise_for_status()
        return response.json()

    def get_all_activities(self, after: Optional[int] = None) -> List[Dict[str, Any]]:
        """
        Fetch ALL activities using pagination.

        Args:
            after: Optional Unix timestamp for fetching activities after this date.
        """
        all_activities = []
        page = 1
        while True:
            activities = self.get_activities(page=page, per_page=200, after=after)
            if not activities:
                break
            all_activities.extend(activities)
            page += 1
        return all_activities
