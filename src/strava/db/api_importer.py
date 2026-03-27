"""Strava API data importer with parallel stream fetching."""

import threading
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, Any, Callable, List, Optional, Tuple

import pandas as pd

from strava.db.db_manager import DatabaseManager
from strava.utils.strava_api import StravaAPI

# Max parallel workers for API requests.
_MAX_WORKERS = 3

# Conservative rate limit: 150 requests per 15 min, well below Strava's 200/15 min cap.
# The remaining budget is reserved for activity-list pagination calls.
_RATE_LIMIT_CALLS = 150
_RATE_LIMIT_PERIOD = 900  # 15 minutes in seconds

# Default lookback when the database is empty (first-time import).
_DEFAULT_LOOKBACK_MONTHS = 3


class _RateLimiter:  # pylint: disable=too-few-public-methods
    """Sliding-window rate limiter shared across worker threads.

    Tracks timestamps of recent API calls within a rolling window and blocks
    callers until a slot is available, preventing bursts that exceed the limit.
    """

    def __init__(self, max_calls: int, period_seconds: float) -> None:
        self._max = max_calls
        self._period = period_seconds
        self._timestamps: deque = deque()
        self._lock = threading.Lock()

    def acquire(self) -> None:
        """Block until a request slot becomes available."""
        while True:
            with self._lock:
                now = time.time()
                cutoff = now - self._period
                # Prune expired timestamps from the left end.
                while self._timestamps and self._timestamps[0] < cutoff:
                    self._timestamps.popleft()
                if len(self._timestamps) < self._max:
                    self._timestamps.append(now)
                    return
                # Sleep until the oldest call exits the window.
                sleep_for = self._timestamps[0] + self._period - now + 0.05
            time.sleep(max(0.0, sleep_for))


class StravaImporter:  # pylint: disable=too-few-public-methods
    """Imports Strava activities and streams into the local database."""

    def __init__(self, db_manager: DatabaseManager, api_client: StravaAPI):
        self.db = db_manager
        self.api = api_client
        self._rate_limiter = _RateLimiter(_RATE_LIMIT_CALLS, _RATE_LIMIT_PERIOD)

    # ── Public API ──────────────────────────────────────────────────

    def import_all_data(
        self,
        progress_callback: Optional[Callable[[str, float], None]] = None,
        lookback_months: Optional[int] = _DEFAULT_LOOKBACK_MONTHS,
    ) -> int:
        """Import activities and streams from Strava API.

        On a fresh database, only fetches the last *lookback_months* months to
        avoid exhausting Strava's rate limits on large accounts.  Pass
        ``lookback_months=None`` to fetch the full history.  When the database
        already contains activities the import is always incremental (new
        activities only), regardless of *lookback_months*.

        Uses a ThreadPoolExecutor to parallelise stream + detail fetches, then
        inserts results sequentially to avoid SQLite write conflicts.

        Args:
            progress_callback: Function accepting (status_message, percent_complete).
            lookback_months: How many months back to fetch on a fresh DB.
                             ``None`` fetches all-time history.

        Returns:
            int: Number of activities imported.
        """
        _cb = progress_callback or (lambda msg, pct: None)

        db_latest = self.db.get_latest_activity_timestamp()

        # Determine the ``after`` timestamp for the API call.
        if db_latest is not None:
            # Incremental sync — always use the DB watermark, ignore lookback_months.
            fetch_after: Optional[int] = db_latest
            _cb("Checking for new activities...", 0.0)
        elif lookback_months is not None:
            seconds_back = int(lookback_months * 30 * 24 * 60 * 60)
            fetch_after = int(time.time() - seconds_back)
            _cb(f"Fetching last {lookback_months} months of activities...", 0.0)
        else:
            fetch_after = None  # All-time history
            _cb("Fetching full activity history (this may take a while)...", 0.0)

        # ── Phase 1: Fetch activity summaries (fast, paginated) ────
        activities = self.api.get_all_activities(after=fetch_after)
        total = len(activities)

        if total == 0:
            status = "Data is already up to date." if db_latest else "No activities found."
            _cb(status, 1.0)
            return 0

        label = "new " if db_latest else ""
        _cb(f"Found {total} {label}activities. Fetching details in parallel...", 0.05)

        # ── Phase 2: Insert activity summaries (lightweight, sequential) ──
        for activity in activities:
            self.db.insert_activity(self._map_activity(activity))

        _cb(f"Saved {total} activity summaries. Fetching streams & detail...", 0.15)

        # ── Phase 3: Parallel stream + detail fetch (rate-limited) ─
        results: List[Tuple[int, str, Dict, Optional[float]]] = []
        completed_count = 0

        with ThreadPoolExecutor(max_workers=_MAX_WORKERS) as executor:
            future_to_activity = {
                executor.submit(self._fetch_activity_data, act): act for act in activities
            }

            for future in as_completed(future_to_activity):
                completed_count += 1
                pct = 0.15 + (0.80 * completed_count / total)
                _cb(
                    f"Fetching streams & detail [rate-limited]: {completed_count}/{total}",
                    pct,
                )

                try:
                    result = future.result()
                    if result:
                        results.append(result)
                except Exception as exc:  # pylint: disable=broad-exception-caught
                    act = future_to_activity[future]
                    print(f"Failed to fetch data for activity {act['id']}: {exc}")

        # ── Phase 4: Sequential DB inserts ─────────────────────────
        _cb("Saving stream data to database...", 0.95)
        for activity_id, start_date, streams, perceived_exertion in results:
            if streams:
                self._process_and_insert_streams(activity_id, start_date, streams)
            if perceived_exertion is not None:
                self._update_perceived_exertion(activity_id, perceived_exertion)

        _cb("Import complete!", 1.0)
        return total

    # ── Private helpers ────────────────────────────────────────────

    def _fetch_activity_data(
        self, activity: Dict[str, Any]
    ) -> Optional[Tuple[int, str, Dict, Optional[float]]]:
        """Fetch streams + optional detail for one activity.

        Each API call is gated by the shared rate limiter to stay within
        Strava's 200 requests/15 min cap.

        Returns:
            (activity_id, start_date_str, streams_dict, perceived_exertion_or_None)
        """
        activity_id = activity["id"]
        start_date = activity["start_date"]

        streams = {}
        try:
            self._rate_limiter.acquire()
            streams = self.api.get_activity_streams(activity_id) or {}
        except Exception as exc:  # pylint: disable=broad-exception-caught
            print(f"Stream fetch failed for {activity_id}: {exc}")

        perceived_exertion = None
        try:
            self._rate_limiter.acquire()
            detail = self.api.get_activity_detail(activity_id)
            perceived_exertion = detail.get("perceived_exertion")
        except Exception as exc:  # pylint: disable=broad-exception-caught
            print(f"Detail fetch failed for {activity_id}: {exc}")

        return (activity_id, start_date, streams, perceived_exertion)

    def _update_perceived_exertion(self, activity_id: int, value: float):
        """Persist perceived_exertion for an already-inserted activity."""
        with self.db.get_connection() as conn:
            conn.execute(
                "UPDATE activities SET perceived_exertion = ? WHERE activity_id = ?",
                (value, activity_id),
            )

    def _map_activity(self, api_data: Dict[str, Any]) -> Dict[str, Any]:
        """Map Strava API activity summary object to DB column names."""
        return {
            "activity_id": api_data.get("id"),
            "activity_date": api_data.get("start_date"),
            "activity_name": api_data.get("name"),
            "activity_type": api_data.get("type"),
            "sport_type": api_data.get("sport_type"),
            "activity_description": api_data.get("description"),
            "elapsed_time": api_data.get("elapsed_time"),
            "moving_time": api_data.get("moving_time"),
            "distance": api_data.get("distance"),
            "max_speed": api_data.get("max_speed"),
            "average_speed": api_data.get("average_speed"),
            "elevation_gain": api_data.get("total_elevation_gain"),
            "elevation_loss": api_data.get("elev_low", 0),
            "elevation_low": api_data.get("elev_low"),
            "elevation_high": api_data.get("elev_high"),
            "max_heart_rate": api_data.get("max_heartrate"),
            "average_heart_rate": api_data.get("average_heartrate"),
            "average_cadence": api_data.get("average_cadence"),
            "max_watts": api_data.get("max_watts"),
            "average_watts": api_data.get("average_watts"),
            "weighted_average_power": api_data.get("weighted_average_watts"),
            "calories": api_data.get("calories") or api_data.get("kilojoules"),
            "workout_type": api_data.get("workout_type"),
            "commute": api_data.get("commute"),
            "trainer": api_data.get("trainer"),
            "gear": api_data.get("gear_id"),
            # New engagement / effort fields
            "suffer_score": api_data.get("suffer_score"),
            "pr_count": api_data.get("pr_count"),
            "achievement_count": api_data.get("achievement_count"),
            "kudos_count": api_data.get("kudos_count"),
            "has_kudoed": api_data.get("has_kudoed"),
        }

    def _process_and_insert_streams(
        self, activity_id: int, start_date_str: str, streams: Dict[str, Any]
    ):
        """Convert raw Strava stream dict into records and upsert into DB."""
        if "time" not in streams:
            return

        size = len(streams["time"]["data"])
        start_date = pd.to_datetime(start_date_str)

        def get_val(stream_name, index, default=None):
            if stream_name in streams and index < len(streams[stream_name]["data"]):
                return streams[stream_name]["data"][index]
            return default

        records = []
        for i in range(size):
            elapsed_seconds = get_val("time", i)
            timestamp = start_date + pd.Timedelta(seconds=elapsed_seconds)
            latlng = get_val("latlng", i)

            record = {
                "activity_id": activity_id,
                "timestamp": timestamp.isoformat(),
                "elapsed_seconds": elapsed_seconds,
                "latitude": latlng[0] if latlng and len(latlng) == 2 else None,
                "longitude": latlng[1] if latlng and len(latlng) == 2 else None,
                "distance": get_val("distance", i),
                "speed": get_val("velocity_smooth", i),
                "pace": None,
                "heart_rate": get_val("heartrate", i),
                "cadence": get_val("cadence", i),
                "altitude": get_val("altitude", i),
                "power": get_val("watts", i),
                "temperature": get_val("temp", i),
                "source_type": "API",
            }
            records.append(record)

        self.db.delete_activity_streams(activity_id)
        self.db.insert_stream_batch(records)
