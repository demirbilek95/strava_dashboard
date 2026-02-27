"""Tests for AI Coach plan parsing and conversion logic."""

import pytest
from strava.utils.ai_coach import AICoach


def test_parse_plan_json_valid():
    """Parse a valid JSON plan block from LLM response."""
    text = """Here's your plan!

```json
{
  "start_date": "2026-03-02",
  "end_date": "2026-03-15",
  "weeks": [
    {
      "week_number": 1,
      "workouts": [
        {
          "day": "Monday",
          "date": "2026-03-02",
          "type": "easy_run",
          "description": "Easy recovery run",
          "distance_km": 6.0,
          "duration_min": 36,
          "pace_min_km": 6.0,
          "hr_zone": "Zone 2"
        },
        {
          "day": "Tuesday",
          "date": "2026-03-03",
          "type": "rest",
          "description": "Rest day",
          "distance_km": 0,
          "duration_min": 0,
          "pace_min_km": null,
          "hr_zone": ""
        }
      ]
    }
  ]
}
```

Let me know if you'd like adjustments!"""

    result = AICoach.parse_plan_json(text)
    assert result is not None
    assert result["start_date"] == "2026-03-02"
    assert result["end_date"] == "2026-03-15"
    assert len(result["weeks"]) == 1
    assert len(result["weeks"][0]["workouts"]) == 2
    assert result["weeks"][0]["workouts"][0]["type"] == "easy_run"


def test_parse_plan_json_no_block():
    """Return None when no JSON block is found."""
    text = "Here's a text-only plan with no JSON."
    result = AICoach.parse_plan_json(text)
    assert result is None


def test_parse_plan_json_invalid_json():
    """Return None when JSON is malformed."""
    text = """```json
    { invalid json here }
    ```"""
    result = AICoach.parse_plan_json(text)
    assert result is None


def test_plan_json_to_workouts():
    """Convert a parsed plan JSON to DB workout records."""
    plan_json = {
        "start_date": "2026-03-02",
        "end_date": "2026-03-08",
        "weeks": [
            {
                "week_number": 1,
                "workouts": [
                    {
                        "day": "Monday",
                        "date": "2026-03-02",
                        "type": "easy_run",
                        "description": "Easy run",
                        "distance_km": 6.0,
                        "duration_min": 36,
                        "pace_min_km": 6.0,
                        "hr_zone": "Zone 2",
                    },
                    {
                        "day": "Tuesday",
                        "date": "2026-03-03",
                        "type": "rest",
                        "description": "Rest",
                        "distance_km": 0,
                        "duration_min": 0,
                        "pace_min_km": None,
                        "hr_zone": "",
                    },
                    {
                        "day": "Wednesday",
                        "date": "2026-03-04",
                        "type": "tempo",
                        "description": "Tempo run",
                        "distance_km": 8.0,
                        "duration_min": 40,
                        "pace_min_km": 5.0,
                        "hr_zone": "Zone 3",
                    },
                ],
            }
        ],
    }

    workouts = AICoach.plan_json_to_workouts(plan_id=42, plan_json=plan_json)

    assert len(workouts) == 3
    assert all(w["plan_id"] == 42 for w in workouts)

    # First workout
    assert workouts[0]["workout_date"] == "2026-03-02"
    assert workouts[0]["workout_type"] == "easy_run"
    assert workouts[0]["target_distance_km"] == 6.0
    assert workouts[0]["target_pace_min_km"] == 6.0

    # Rest day
    assert workouts[1]["workout_type"] == "rest"
    assert workouts[1]["target_distance_km"] == 0

    # Tempo
    assert workouts[2]["workout_type"] == "tempo"
    assert workouts[2]["target_hr_zone"] == "Zone 3"


def test_plan_json_to_workouts_empty():
    """Handle empty plan JSON gracefully."""
    workouts = AICoach.plan_json_to_workouts(plan_id=1, plan_json={})
    assert workouts == []

    workouts = AICoach.plan_json_to_workouts(plan_id=1, plan_json={"weeks": []})
    assert workouts == []
