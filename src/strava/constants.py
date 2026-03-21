"""Shared constants for the Strava Analytics dashboard.

Centralises colour palettes so all views use the same colours for zones
and workout types, keeping the UI consistent.
"""

from typing import Dict

# ── Heart Rate Zone Colours ────────────────────────────────────────────
# Z1 = Recovery (light blue), Z2 = Aerobic (green), Z3 = Tempo (yellow),
# Z4 = Threshold (orange), Z5 = Max effort (red)

ZONE_COLORS: Dict[str, str] = {
    "Z1": "#64B5F6",  # Light blue  – Recovery
    "Z2": "#66BB6A",  # Green       – Aerobic / fat-burning
    "Z3": "#FFEE58",  # Yellow      – Tempo
    "Z4": "#FFA726",  # Orange      – Threshold
    "Z5": "#EF5350",  # Red         – VO2 max / Red line
}

# Ordered list for legend/category display
ZONE_ORDER = ["Z1", "Z2", "Z3", "Z4", "Z5"]

ZONE_LABELS: Dict[str, str] = {
    "Z1": "Z1 – Recovery",
    "Z2": "Z2 – Aerobic",
    "Z3": "Z3 – Tempo",
    "Z4": "Z4 – Threshold",
    "Z5": "Z5 – Red Line",
}

# ── Workout Type Colours (Training Plan Calendar) ─────────────────────
# Used in training_plan.py for the monthly calendar cells.

WORKOUT_COLORS: Dict[str, str] = {
    "easy_run": "#66BB6A",  # Green  – mirrors Z2 aerobic
    "recovery": "#64B5F6",  # Light blue – mirrors Z1 recovery
    "tempo": "#FFA726",  # Orange – mirrors Z4 threshold
    "intervals": "#EF5350",  # Red    – mirrors Z5 max effort
    "long_run": "#42A5F5",  # Mid blue – aerobic long
    "rest": "#9E9E9E",  # Grey   – rest
    "cross_training": "#AB47BC",  # Purple – cross training
}

STATUS_COLORS: Dict[str, str] = {
    "completed": "#66BB6A",  # Green
    "missed": "#EF5350",  # Red
    "upcoming": "#42A5F5",  # Blue
    "rest": "#9E9E9E",  # Grey
}

# ── Workout Type Compatibility for Completion Matching ────────────────
# Maps planned workout type → set of activity types that count as completing it.
# activity_type values from Strava: "Run", "Ride", "Walk", "Swim", etc.
# workout_type values from the plan: "easy_run", "tempo", "intervals", etc.

WORKOUT_TYPE_COMPATIBLE: Dict[str, set] = {
    "easy_run": {"easy_run", "recovery", "Run", "Walk"},
    "recovery": {"recovery", "easy_run", "Run", "Walk"},
    "tempo": {"tempo", "intervals", "long_run", "Run"},
    "intervals": {"intervals", "tempo", "Run"},  # Strict: must be hard
    "long_run": {"long_run", "Run"},  # Must be long distance
    "rest": {"rest"},  # Rest is always rest
    "cross_training": {"cross_training", "Ride", "Swim", "Walk", "Hike", "Yoga"},
}

# Minimum distance ratio: actual distance / planned distance must exceed this
COMPLETION_MIN_DISTANCE_RATIO = 0.70

# For interval workouts, minimum % of stream time in Z4/Z5 to count as "hard"
INTERVAL_MIN_HARD_ZONE_PCT = 0.10
