"""Tests for training plan database operations."""

import os
import tempfile
import pytest
from strava.db.db_manager import DatabaseManager

# pylint: disable=redefined-outer-name


@pytest.fixture
def temp_db_path():
    """Create a temporary database file."""
    temp_dir = tempfile.mkdtemp()
    db_path = os.path.join(temp_dir, "test_strava.db")
    yield db_path

    if os.path.exists(db_path):
        os.remove(db_path)
    if os.path.exists(temp_dir):
        os.rmdir(temp_dir)


@pytest.fixture
def db(temp_db_path):
    """Create a DatabaseManager with training plan tables."""
    manager = DatabaseManager(temp_db_path)
    manager.create_tables()
    return manager


def test_create_training_plan_tables(temp_db_path):
    """Verify training plan tables are created."""
    import sqlite3

    manager = DatabaseManager(temp_db_path)
    manager.create_tables()

    with sqlite3.connect(temp_db_path) as conn:
        cursor = conn.cursor()

        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='training_plans'"
        )
        assert cursor.fetchone() is not None

        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='planned_workouts'"
        )
        assert cursor.fetchone() is not None


def test_insert_and_get_plan(db):
    """Insert a plan and verify retrieval."""
    plan_id = db.insert_training_plan({
        "goal": "Sub-4 marathon",
        "start_date": "2026-03-01",
        "end_date": "2026-05-01",
        "status": "active",
        "raw_llm_response": "Test plan text",
    })

    assert plan_id is not None
    assert plan_id > 0

    plan = db.get_active_plan()
    assert plan is not None
    assert plan["goal"] == "Sub-4 marathon"
    assert plan["start_date"] == "2026-03-01"
    assert plan["end_date"] == "2026-05-01"


def test_insert_planned_workouts(db):
    """Insert workouts and verify they are linked to the plan."""
    plan_id = db.insert_training_plan({
        "goal": "5K improvement",
        "start_date": "2026-03-01",
        "status": "active",
    })

    workouts = [
        {
            "plan_id": plan_id,
            "workout_date": "2026-03-02",
            "workout_type": "easy_run",
            "description": "Easy run, Zone 2",
            "target_distance_km": 6.0,
            "target_duration_min": 36,
            "target_pace_min_km": 6.0,
            "target_hr_zone": "Zone 2",
        },
        {
            "plan_id": plan_id,
            "workout_date": "2026-03-03",
            "workout_type": "rest",
            "description": "Rest day",
            "target_distance_km": None,
            "target_duration_min": None,
            "target_pace_min_km": None,
            "target_hr_zone": "",
        },
        {
            "plan_id": plan_id,
            "workout_date": "2026-03-04",
            "workout_type": "tempo",
            "description": "Tempo run",
            "target_distance_km": 8.0,
            "target_duration_min": 40,
            "target_pace_min_km": 5.0,
            "target_hr_zone": "Zone 3",
        },
    ]

    db.insert_planned_workouts(workouts)

    plan = db.get_active_plan()
    assert len(plan["workouts"]) == 3
    assert plan["workouts"][0]["workout_type"] == "easy_run"
    assert plan["workouts"][0]["target_distance_km"] == 6.0
    assert plan["workouts"][1]["workout_type"] == "rest"
    assert plan["workouts"][2]["workout_type"] == "tempo"


def test_get_planned_workouts_with_activity_join(db):
    """Test fetching planned workouts with matched activity data."""
    # Insert an activity first
    db.insert_activity({
        "activity_id": 99999,
        "activity_name": "Morning Run",
        "activity_type": "Run",
        "distance": 6200.0,
        "moving_time": 2100,
        "activity_date": "2026-03-02T08:00:00Z",
    })

    plan_id = db.insert_training_plan({
        "goal": "Test goal",
        "start_date": "2026-03-02",
        "status": "active",
    })

    db.insert_planned_workouts([{
        "plan_id": plan_id,
        "workout_date": "2026-03-02",
        "workout_type": "easy_run",
        "description": "Easy run",
        "target_distance_km": 6.0,
        "target_duration_min": 36,
        "target_pace_min_km": 6.0,
        "target_hr_zone": "Zone 2",
    }])

    workouts = db.get_planned_workouts(plan_id)
    assert len(workouts) == 1
    # No match yet
    assert workouts[0]["matched_activity_id"] is None


def test_update_workout_completion(db):
    """Mark a workout as done and verify matched activity + feedback."""
    db.insert_activity({
        "activity_id": 88888,
        "activity_name": "Tempo Session",
        "activity_type": "Run",
        "distance": 8100.0,
        "moving_time": 2400,
        "activity_date": "2026-03-04T07:00:00Z",
    })

    plan_id = db.insert_training_plan({
        "goal": "Test",
        "start_date": "2026-03-04",
        "status": "active",
    })

    db.insert_planned_workouts([{
        "plan_id": plan_id,
        "workout_date": "2026-03-04",
        "workout_type": "tempo",
        "description": "Tempo run",
        "target_distance_km": 8.0,
        "target_duration_min": 40,
        "target_pace_min_km": 5.0,
        "target_hr_zone": "Zone 3",
    }])

    plan = db.get_active_plan()
    workout_id = plan["workouts"][0]["workout_id"]

    db.update_workout_completion(
        workout_id, activity_id=88888, feedback="Great tempo session!"
    )

    updated_plan = db.get_active_plan()
    w = updated_plan["workouts"][0]
    assert w["completed"] == 1
    assert w["matched_activity_id"] == 88888
    assert w["feedback"] == "Great tempo session!"


def test_get_active_plan_returns_only_active(db):
    """Verify only the active plan is returned."""
    db.insert_training_plan({
        "goal": "Old plan",
        "start_date": "2026-01-01",
        "status": "archived",
    })
    db.insert_training_plan({
        "goal": "Current plan",
        "start_date": "2026-03-01",
        "status": "active",
    })

    plan = db.get_active_plan()
    assert plan is not None
    assert plan["goal"] == "Current plan"


def test_archive_plan(db):
    """Verify archiving a plan removes it from active results."""
    plan_id = db.insert_training_plan({
        "goal": "To be archived",
        "start_date": "2026-03-01",
        "status": "active",
    })

    plan = db.get_active_plan()
    assert plan is not None

    db.archive_plan(plan_id)

    plan = db.get_active_plan()
    assert plan is None
