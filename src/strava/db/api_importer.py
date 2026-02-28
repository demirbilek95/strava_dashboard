from typing import Dict, Any, Callable, Optional
import pandas as pd

from strava.db.db_manager import DatabaseManager
from strava.utils.strava_api import StravaAPI


class StravaImporter:  # pylint: disable=too-few-public-methods
    def __init__(self, db_manager: DatabaseManager, api_client: StravaAPI):
        self.db = db_manager
        self.api = api_client

    def import_all_data(
        self, progress_callback: Optional[Callable[[str, float], None]] = None
    ) -> int:
        """
        Import all activities and streams from Strava API.

        Args:
            progress_callback: Function accepting (status_message, percent_complete)

        Returns:
            int: Number of activities imported.
        """
        if progress_callback:
            progress_callback("Checking for new activities...", 0.0)

        # Get latest activity timestamp from DB for incremental fetch
        latest_timestamp = self.db.get_latest_activity_timestamp()

        # 1. Fetch Activities (incremental if latest_timestamp exists)
        activities = self.api.get_all_activities(after=latest_timestamp)
        total_activities = len(activities)

        if total_activities == 0:
            if progress_callback:
                status = "Data is up to date." if latest_timestamp else "No activities found."
                progress_callback(status, 1.0)
            return 0

        if progress_callback:
            msg = (
                f"Found {total_activities} new activities. Starting import..."
                if latest_timestamp
                else f"Found {total_activities} activities. Starting import..."
            )
            progress_callback(msg, 0.1)

        # 2. Insert Activities and Fetch Streams
        for i, activity in enumerate(activities):
            # Map activity data to DB schema
            db_activity = self._map_activity(activity)
            self.db.insert_activity(db_activity)

            # Fetch and insert streams
            try:
                streams = self.api.get_activity_streams(activity["id"])
                if streams:
                    self._process_and_insert_streams(
                        activity["id"], activity["start_date"], streams
                    )
            except Exception as exc:  # pylint: disable=broad-exception-caught
                print(f"Failed to fetch/insert streams for activity {activity['id']}: {exc}")

            if progress_callback:
                percent = 0.1 + (0.9 * (i + 1) / total_activities)
                progress_callback(f"Processed {i+1}/{total_activities} activities", percent)

        if progress_callback:
            progress_callback("Import complete!", 1.0)

        return total_activities

    def _map_activity(self, api_data: Dict[str, Any]) -> Dict[str, Any]:
        """Map Strava API activity object to DB keys."""
        return {
            "activity_id": api_data.get("id"),
            "activity_date": api_data.get("start_date"),
            "activity_name": api_data.get("name"),
            "activity_type": api_data.get("type"),
            "activity_description": api_data.get("description"),
            "elapsed_time": api_data.get("elapsed_time"),
            "moving_time": api_data.get("moving_time"),
            "distance": api_data.get("distance"),
            "max_speed": api_data.get("max_speed"),
            "average_speed": api_data.get("average_speed"),
            "elevation_gain": api_data.get("total_elevation_gain"),
            "elevation_loss": api_data.get("elev_low", 0),  # Not directly provided usually?
            "elevation_low": api_data.get("elev_low"),
            "elevation_high": api_data.get("elev_high"),
            # Strava might not provide detailed grade info in summary, maybe in detail?
            # Keeping it simple for now
            "max_heart_rate": api_data.get("max_heartrate"),
            "average_heart_rate": api_data.get("average_heartrate"),
            "average_cadence": api_data.get("average_cadence"),  # Run cadence?
            "max_watts": api_data.get("max_watts"),
            "average_watts": api_data.get("average_watts"),
            "weighted_average_power": api_data.get("weighted_average_watts"),
            "calories": api_data.get("calories")
            or api_data.get("kilojoules"),  # calories for Run, kilojoules for Bike
            "workout_type": api_data.get("workout_type"),
            "commute": api_data.get("commute"),
            "trainer": api_data.get("trainer"),
            "gear": api_data.get("gear_id"),
            # Fields not in summary or requiring calculation
            # "filename": "strava_api"
        }

    def _process_and_insert_streams(
        self, activity_id: int, start_date_str: str, streams: Dict[str, Any]
    ):
        """Process stream data and insert into DB."""
        # Convert streams dict to list of records
        # All streams (time, distance, etc.) should be same length

        # Check if we have 'time' stream
        if "time" not in streams:
            return

        size = len(streams["time"]["data"])
        records = []

        start_date = pd.to_datetime(start_date_str)

        # Helper to get data safely
        def get_val(stream_name, index, default=None):
            if stream_name in streams and index < len(streams[stream_name]["data"]):
                return streams[stream_name]["data"][index]
            return default

        for i in range(size):
            elapsed_seconds = get_val("time", i)
            # Calculate absolute timestamp
            timestamp = start_date + pd.Timedelta(seconds=elapsed_seconds)

            record = {
                "activity_id": activity_id,
                "timestamp": timestamp.isoformat(),
                "elapsed_seconds": elapsed_seconds,
                "latitude": None,  # latlng is [lat, lng]
                "longitude": None,
                "distance": get_val("distance", i),
                "speed": get_val("velocity_smooth", i),
                "pace": None,  # Calculate later or during view
                "heart_rate": get_val("heartrate", i),
                "cadence": get_val("cadence", i),
                "altitude": get_val("altitude", i),
                "power": get_val("watts", i),
                "temperature": get_val("temp", i),
                "source_type": "API",
            }

            latlng = get_val("latlng", i)
            if latlng and len(latlng) == 2:
                record["latitude"] = latlng[0]
                record["longitude"] = latlng[1]

            records.append(record)

        # Batch insert
        # To avoid massive memory usage, maybe batch in chunks?
        # But SQLite execute_many is reasonably efficient.

        # However, we should delete existing streams first to avoid duplication
        self.db.delete_activity_streams(activity_id)
        self.db.insert_stream_batch(records)
