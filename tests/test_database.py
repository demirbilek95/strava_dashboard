import pytest
import sqlite3
import tempfile
import os

from strava.db.db_manager import DatabaseManager


@pytest.fixture
def temp_db_path():
    """Create a temporary database file."""
    # Create a temporary directory
    temp_dir = tempfile.mkdtemp()
    db_path = os.path.join(temp_dir, "test_strava.db")
    yield db_path

    # Cleanup
    if os.path.exists(db_path):
        os.remove(db_path)
    if os.path.exists(temp_dir):
        os.rmdir(temp_dir)


@pytest.fixture
def db_manager(temp_db_path):
    """Create a DatabaseManager instance with a temporary database."""
    manager = DatabaseManager(temp_db_path)
    # Ensure schema is created
    manager.create_tables()
    return manager


def test_create_tables(temp_db_path):
    """Test that tables are successfully created."""
    manager = DatabaseManager(temp_db_path)
    manager.create_tables()

    with sqlite3.connect(temp_db_path) as conn:
        cursor = conn.cursor()

        # Check for activities table
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='activities'")
        assert cursor.fetchone() is not None

        # Check for activity_streams table
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='activity_streams'"
        )
        assert cursor.fetchone() is not None


def test_insert_and_get_activity(db_manager):
    """Test inserting and retrieving an activity."""
    activity_data = {
        "activity_id": 12345,
        "activity_name": "Test Run",
        "activity_type": "Run",
        "distance": 5000.0,
        "moving_time": 1800,
        "elapsed_time": 1900,
        "elevation_gain": 100.0,
        "activity_date": "2023-01-01T10:00:00Z",
        "commute": 0,
    }

    # Insert
    db_manager.insert_activity(activity_data)

    # Verify via direct query
    result = db_manager.execute_query("SELECT * FROM activities WHERE activity_id = ?", (12345,))
    assert len(result) == 1
    row = result[0]
    assert row["activity_name"] == "Test Run"
    assert row["distance"] == 5000.0


def test_insert_streams(db_manager):
    """Test inserting and retrieving streams."""
    activity_id = 12345
    # First insert parent activity (foreign key constraint might not be enforced by default in sqlite python but good practice)
    db_manager.insert_activity(
        {
            "activity_id": activity_id,
            "activity_name": "Test Run",
            "activity_date": "2023-01-01T10:00:00Z",
        }
    )

    streams = [
        {
            "activity_id": activity_id,
            "elapsed_seconds": 0,
            "heart_rate": 140,
            "speed": 2.5,
            "timestamp": "2023-01-01T10:00:00Z",
        },
        {
            "activity_id": activity_id,
            "elapsed_seconds": 1,
            "heart_rate": 142,
            "speed": 2.6,
            "timestamp": "2023-01-01T10:00:01Z",
        },
        {
            "activity_id": activity_id,
            "elapsed_seconds": 2,
            "heart_rate": 145,
            "speed": 2.7,
            "timestamp": "2023-01-01T10:00:02Z",
        },
    ]

    db_manager.insert_stream_batch(streams)

    # Verify
    fetched_streams = db_manager.get_activity_stream(activity_id)
    assert len(fetched_streams) == 3
    assert fetched_streams[0]["heart_rate"] == 140
    assert fetched_streams[2]["speed"] == 2.7

    # Verify has_streams check
    assert db_manager.activity_has_streams(activity_id) is True


def test_database_stats(db_manager):
    """Test get_database_stats."""
    # Insert some data
    db_manager.insert_activity(
        {
            "activity_id": 1,
            "activity_name": "Run 1",
            "activity_type": "Run",
            "activity_date": "2023-01-01",
        }
    )
    db_manager.insert_activity(
        {
            "activity_id": 2,
            "activity_name": "Ride 1",
            "activity_type": "Ride",
            "activity_date": "2023-01-02",
        }
    )

    stats = db_manager.get_database_stats()

    assert stats["total_activities"] == 2
    assert "Run" in stats["activity_types"]
    assert "Ride" in stats["activity_types"]
