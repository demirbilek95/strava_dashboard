"""Database manager for Strava activity data."""

import sqlite3
from pathlib import Path
from contextlib import contextmanager
from typing import Optional, List, Dict, Any


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

        with open(query_path, "r") as f:
            return f.read()

    def create_tables(self):
        """Create database tables from the schema definition."""
        schema_sql = self.load_query("create_schema")

        with self.get_connection() as conn:
            conn.executescript(schema_sql)

        print(f"✓ Database tables created at {self.db_path}")

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

    def get_database_stats(self) -> Dict[str, Any]:
        """Get summary statistics about the database."""
        stats = {}

        # Total activities
        stats["total_activities"] = self.get_activity_count()

        # Activities with streams
        stats["activities_with_streams"] = self.get_activities_with_streams_count()

        # Total stream records
        result = self.execute_query("SELECT COUNT(*) as count FROM activity_streams")
        stats["total_stream_records"] = result[0]["count"] if result else 0

        # Date range
        result = self.execute_query(
            "SELECT MIN(activity_date) as min_date, MAX(activity_date) as max_date FROM activities"
        )
        if result and result[0]["min_date"]:
            stats["date_range"] = {"start": result[0]["min_date"], "end": result[0]["max_date"]}

        # Activity types
        result = self.execute_query(
            """SELECT activity_type, COUNT(*) as count 
               FROM activities 
               WHERE activity_type IS NOT NULL
               GROUP BY activity_type 
               ORDER BY count DESC"""
        )
        stats["activity_types"] = {row["activity_type"]: row["count"] for row in result}

        # Database size
        stats["database_size_mb"] = (
            self.db_path.stat().st_size / (1024 * 1024) if self.db_path.exists() else 0
        )

        return stats
