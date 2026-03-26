"""Strava API data importer with parallel stream fetching."""

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, Any, Callable, List, Optional, Tuple

import pandas as pd

from strava.db.db_manager import DatabaseManager
from strava.utils.strava_api import StravaAPI

# Max parallel workers for API requests.
# Strava rate-limit: 100 req/15 min -> reduce to 3 workers with moderate throttling.
_MAX_WORKERS = 3


class StravaImporter:  # pylint: disable=too-few-public-methods
    """Imports Strava activities and streams into the local database."""

    def __init__(self, db_manager: DatabaseManager, api_client: StravaAPI):
        self.db = db_manager
        self.api = api_client

    # ── Public API ──────────────────────────────────────────────────

    def import_all_data(
        self, progress_callback: Optional[Callable[[str, float], None]] = None
    ) -> int:
        """Import all activities and streams from Strava API.

        Uses a ThreadPoolExecutor to parallelise stream + detail fetches,
        then inserts results sequentially to avoid SQLite write conflicts.

        Args:
            progress_callback: Function accepting (status_message, percent_complete)

        Returns:
            int: Number of activities imported.
        """
        _cb = progress_callback or (lambda msg, pct: None)

        _cb("Checking for new activities...", 0.0)
        db_latest = self.db.get_latest_activity_timestamp()

        # If DB is empty, default to the last 1 year to avoid massive rate limits
        one_year_ago = int(time.time() - (365 * 24 * 60 * 60))
        fetch_after = db_latest if db_latest is not None else one_year_ago

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

        # ── Phase 3: Parallel stream + detail fetch ────────────────
        results: List[Tuple[int, str, Dict, Optional[float]]] = []
        completed_count = 0

        with ThreadPoolExecutor(max_workers=_MAX_WORKERS) as executor:
            future_to_activity = {
                executor.submit(self._fetch_activity_data, act): act for act in activities
            }

            for future in as_completed(future_to_activity):
                completed_count += 1
                pct = 0.15 + (0.80 * completed_count / total)
                _cb(f"Fetched streams: {completed_count}/{total}", pct)

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

        Returns:
            (activity_id, start_date_str, streams_dict, perceived_exertion_or_None)
        """
        activity_id = activity["id"]
        start_date = activity["start_date"]

        # Small sleep to stay well within Strava rate limits and avoid burst 429s
        time.sleep(0.5)

        streams = {}
        try:
            streams = self.api.get_activity_streams(activity_id) or {}
        except Exception as exc:  # pylint: disable=broad-exception-caught
            print(f"Stream fetch failed for {activity_id}: {exc}")

        perceived_exertion = None
        try:
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
