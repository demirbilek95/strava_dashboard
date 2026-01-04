import unittest
from unittest.mock import patch, MagicMock
from pathlib import Path
from strava.utils.strava_api import StravaAPI


class TestStravaOAuth(unittest.TestCase):
    def setUp(self):
        # Create a dummy .env file for testing
        self.env_path = Path(".env.test")
        with open(self.env_path, "w") as f:
            f.write("STRAVA_CLIENT_ID=test_id\n")
            f.write("STRAVA_CLIENT_SECRET=test_secret\n")
            f.write("STRAVA_ACCESS_TOKEN=old_access\n")
            f.write("STRAVA_REFRESH_TOKEN=old_refresh\n")

        # Patch Path.exists and Path to point to our test env
        self.exists_patcher = patch.object(Path, "exists", return_value=True)
        self.exists_patcher.start()

        # Reference to real open
        self.real_open = open

        # Patch open
        self.open_patcher = patch("builtins.open", side_effect=self.mock_open)
        self.open_patcher.start()

        # Patch os.getenv
        self.getenv_patcher = patch("os.getenv", side_effect=self.mock_getenv)
        self.getenv_patcher.start()

    def tearDown(self):
        self.exists_patcher.stop()
        self.open_patcher.stop()
        self.getenv_patcher.stop()
        if self.env_path.exists():
            self.env_path.unlink()

    def mock_open(self, path, mode="r", *args, **kwargs):
        if str(path) == ".env":
            return self.real_open(self.env_path, mode, *args, **kwargs)
        return self.real_open(path, mode, *args, **kwargs)

    def mock_getenv(self, key, default=None):
        env = {
            "STRAVA_CLIENT_ID": "test_id",
            "STRAVA_CLIENT_SECRET": "test_secret",
            "STRAVA_ACCESS_TOKEN": "old_access",
            "STRAVA_REFRESH_TOKEN": "old_refresh",
        }
        return env.get(key, default)

    @patch("requests.post")
    def test_exchange_code_for_tokens(self, mock_post):
        # Mock successful response
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "access_token": "new_access",
            "refresh_token": "new_refresh",
            "expires_at": 123456789,
        }
        mock_response.status_code = 200
        mock_post.return_value = mock_response

        api = StravaAPI(access_token="old_access")
        api.exchange_code_for_tokens("test_code")

        # Verify API state updated
        self.assertEqual(api.access_token, "new_access")
        self.assertEqual(api.refresh_token, "new_refresh")

        # Verify .env.test was updated
        with open(self.env_path, "r") as f:
            content = f.read()
            self.assertIn("STRAVA_ACCESS_TOKEN=new_access", content)
            self.assertIn("STRAVA_REFRESH_TOKEN=new_refresh", content)

    def test_get_authorization_url(self):
        api = StravaAPI(access_token="old_access")
        url = api.get_authorization_url()
        self.assertIn("client_id=test_id", url)
        # Check for encoded scope
        self.assertIn("scope=read%2Cactivity%3Aread%2Cactivity%3Aread_all", url)
        self.assertIn("response_type=code", url)


if __name__ == "__main__":
    unittest.main()
