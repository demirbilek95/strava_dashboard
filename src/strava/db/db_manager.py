"""Database manager for Strava activity data."""

import sqlite3
from pathlib import Path
from contextlib import contextmanager
from typing import Optional, List, Dict, Any
import pandas as pd


class DatabaseManager:
    """Manages SQLite database connections and operations for Strava data."""

    def __init__(self, db_path: Optional[str] = None):
        """
        Initialize database manager.

        Args:
            db_path: Path to SQLite database file. If None, uses default location.
        """
        if db_path is None:
            # Default to data/strava.db
            current_dir = Path(__file__).parent
            project_root = current_dir.parent.parent.parent
            db_path = project_root / "data" / "strava.db"

        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        # Ensure schema is up to date
        if self.db_path.exists():
            self._migrate_schema()

    @contextmanager
    def get_connection(self):
        """
        Context manager for database connections.

        Yields:
            sqlite3.Connection: Database connection
        """
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row  # Enable column access by name
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def load_query(self, query_name: str) -> str:
        """
        Load a SQL query from a file in the queries directory.

        Args:
            query_name: Name of the query file (without .sql extension)

        Returns:
            SQL query string
        """
        queries_dir = Path(__file__).parent / "queries"
        query_path = queries_dir / f"{query_name}.sql"

        if not query_path.exists():
            raise FileNotFoundError(f"Query file not found: {query_path}")

        with open(query_path, "r", encoding="utf-8") as f:
            return f.read()

    def create_tables(self):
        """Create database tables from the schema definition."""
        schema_sql = self.load_query("create_schema")

        with self.get_connection() as conn:
            conn.executescript(schema_sql)

        # Removed redundant print statement
        self._migrate_schema()

    def _migrate_schema(self):
        """Apply migrations to existing tables."""
        try:
            # Check if activities table exists before migrating
            table_check = self.execute_query(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='activities'"
            )
            if not table_check:
                return

            columns = self.execute_query("PRAGMA table_info(activities)")
            column_names = [col["name"] for col in columns]

            new_columns = [
                ("workout_type", "INTEGER"),
                ("trainer", "BOOLEAN DEFAULT 0"),
                ("suffer_score", "INTEGER"),
                ("sport_type", "TEXT"),
                ("pr_count", "INTEGER"),
                ("achievement_count", "INTEGER"),
                ("kudos_count", "INTEGER"),
                ("has_kudoed", "BOOLEAN DEFAULT 0"),
                ("perceived_exertion", "REAL"),
            ]

            with self.get_connection() as conn:
                for col_name, col_def in new_columns:
                    if col_name not in column_names:
                        conn.execute(f"ALTER TABLE activities ADD COLUMN {col_name} {col_def}")
                        print(f"✓ Added {col_name} column to activities table")

        except Exception as exc:  # pylint: disable=broad-exception-caught
            print(f"! Migration check failed: {exc}")

    def execute_query(self, query: str, params: tuple = ()) -> List[sqlite3.Row]:
        """
        Execute a SELECT query and return results.

        Args:
            query: SQL query string
            params: Query parameters

        Returns:
            List of result rows
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, params)
            return cursor.fetchall()

    def execute_many(self, query: str, params_list: List[tuple]):
        """
        Execute a query with multiple parameter sets.

        Args:
            query: SQL query string
            params_list: List of parameter tuples
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.executemany(query, params_list)

    def insert_activity(self, activity_data: Dict[str, Any]) -> int:
        """
        Insert or replace an activity record.

        Args:
            activity_data: Dictionary of activity fields

        Returns:
            Activity ID
        """
        columns = ", ".join(activity_data.keys())
        placeholders = ", ".join(["?" for _ in activity_data])
        query = f"INSERT OR REPLACE INTO activities ({columns}) VALUES ({placeholders})"

        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, tuple(activity_data.values()))
            return activity_data.get("activity_id", cursor.lastrowid)

    def insert_stream_batch(self, stream_records: List[Dict[str, Any]]):
        """
        Insert multiple stream records in batch.

        Args:
            stream_records: List of stream record dictionaries
        """
        if not stream_records:
            return

        # Get columns from first record
        columns = list(stream_records[0].keys())
        columns_str = ", ".join(columns)
        placeholders = ", ".join(["?" for _ in columns])
        query = f"INSERT INTO activity_streams ({columns_str}) VALUES ({placeholders})"

        # Convert to list of tuples
        params_list = [tuple(record[col] for col in columns) for record in stream_records]

        self.execute_many(query, params_list)

    def get_activity_count(self) -> int:
        """Get total number of activities."""
        result = self.execute_query("SELECT COUNT(*) as count FROM activities")
        return result[0]["count"] if result else 0

    def get_activities_with_streams_count(self) -> int:
        """Get number of activities that have stream data."""
        result = self.execute_query(
            "SELECT COUNT(DISTINCT activity_id) as count FROM activity_streams"
        )
        return result[0]["count"] if result else 0

    def activity_has_streams(self, activity_id: int) -> bool:
        """Check if an activity already has stream data."""
        result = self.execute_query(
            "SELECT 1 FROM activity_streams WHERE activity_id = ? LIMIT 1", (activity_id,)
        )
        return len(result) > 0

    def get_latest_activity_timestamp(self) -> Optional[int]:
        """
        Get the timestamp of the latest activity in the database.

        Returns:
            Unix timestamp (int) or None if no activities exist.
        """
        result = self.execute_query("SELECT MAX(activity_date) as latest FROM activities")
        if result and result[0]["latest"]:
            try:
                # Strava dates are ISO strings, e.g., "2018-02-16T14:52:54Z"
                dt = pd.to_datetime(result[0]["latest"])
                return int(dt.timestamp())
            except Exception:  # pylint: disable=broad-exception-caught
                return None
        return None

    def get_activity_stream(self, activity_id: int) -> List[Dict[str, Any]]:
        """
        Get all stream records for an activity.

        Args:
            activity_id: Activity ID

        Returns:
            List of stream records as dictionaries
        """
        query = self.load_query("get_activity_stream")
        rows = self.execute_query(query, (activity_id,))
        return [dict(row) for row in rows]

    def delete_activity_streams(self, activity_id: int):
        """Delete all stream records for an activity."""
        with self.get_connection() as conn:
            conn.execute("DELETE FROM activity_streams WHERE activity_id = ?", (activity_id,))

    # ── Training Plan Methods ──────────────────────────────────────────

    def insert_training_plan(self, plan_data: Dict[str, Any]) -> int:
        """Insert a training plan and return its plan_id."""
        columns = ", ".join(plan_data.keys())
        placeholders = ", ".join(["?" for _ in plan_data])
        query = f"INSERT INTO training_plans ({columns}) VALUES ({placeholders})"

        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(query, tuple(plan_data.values()))
            return cursor.lastrowid

    def insert_planned_workouts(self, workouts: List[Dict[str, Any]]):
        """Batch insert planned workout records."""
        if not workouts:
            return

        columns = list(workouts[0].keys())
        columns_str = ", ".join(columns)
        placeholders = ", ".join(["?" for _ in columns])
        query = f"INSERT INTO planned_workouts ({columns_str}) VALUES ({placeholders})"

        params_list = [tuple(w[col] for col in columns) for w in workouts]
        self.execute_many(query, params_list)

    def get_active_plan(self) -> Optional[Dict[str, Any]]:
        """Get the current active training plan with its workouts."""
        query = self.load_query("get_active_plan")
        rows = self.execute_query(query)

        if not rows:
            return None

        plan = {
            "plan_id": rows[0]["plan_id"],
            "goal": rows[0]["goal"],
            "start_date": rows[0]["start_date"],
            "end_date": rows[0]["end_date"],
            "status": rows[0]["status"],
            "created_at": rows[0]["created_at"],
            "raw_llm_response": rows[0]["raw_llm_response"],
            "workouts": [],
        }

        for row in rows:
            if row["workout_id"] is not None:
                plan["workouts"].append(
                    {
                        "workout_id": row["workout_id"],
                        "workout_date": row["workout_date"],
                        "workout_type": row["workout_type"],
                        "description": row["description"],
                        "target_distance_km": row["target_distance_km"],
                        "target_duration_min": row["target_duration_min"],
                        "target_pace_min_km": row["target_pace_min_km"],
                        "target_hr_zone": row["target_hr_zone"],
                        "completed": row["completed"],
                        "matched_activity_id": row["matched_activity_id"],
                        "feedback": row["feedback"],
                    }
                )

        return plan

    def get_planned_workouts(self, plan_id: int) -> List[Dict[str, Any]]:
        """Get all planned workouts for a plan, with matched activity data."""
        query = self.load_query("get_planned_workouts")
        rows = self.execute_query(query, (plan_id,))
        return [dict(row) for row in rows]

    def update_workout_completion(self, workout_id: int, activity_id: int, feedback: str):
        """Mark a workout as completed and attach matched activity + feedback."""
        query = """
            UPDATE planned_workouts
            SET completed = 1,
                matched_activity_id = ?,
                feedback = ?
            WHERE workout_id = ?
        """
        with self.get_connection() as conn:
            conn.execute(query, (activity_id, feedback, workout_id))

    def archive_plan(self, plan_id: int):
        """Archive a training plan (set status to 'archived')."""
        query = """
            UPDATE training_plans
            SET status = 'archived', updated_at = CURRENT_TIMESTAMP
            WHERE plan_id = ?
        """
        with self.get_connection() as conn:
            conn.execute(query, (plan_id,))

    def get_plan_history(self) -> List[Dict[str, Any]]:
        """Return all training plans (active + archived) ordered by creation date."""
        rows = self.execute_query(
            """
            SELECT plan_id, goal, start_date, end_date, status, created_at,
                   (SELECT COUNT(*) FROM planned_workouts WHERE plan_id = tp.plan_id) AS workout_count,
                   (SELECT COUNT(*) FROM planned_workouts
                    WHERE plan_id = tp.plan_id AND completed = 1) AS completed_count
            FROM training_plans tp
            ORDER BY created_at DESC
            """
        )
        return [dict(row) for row in rows]
