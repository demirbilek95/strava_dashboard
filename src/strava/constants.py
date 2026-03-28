"""Shared constants for the Strava Analytics dashboard.

Centralises colour palettes so all views use the same colours for zones
and workout types, keeping the UI consistent.
"""

from typing import Dict

# ── Heart Rate Zone Colours ────────────────────────────────────────────
# Z1 = Recovery (light blue), Z2 = Aerobic (green), Z3 = Tempo (yellow),
# Z4 = Threshold (orange), Z5 = Max effort (red)

ZONE_COLORS: Dict[str, str] = {
    "Z1": "#A8D8EA",  # Pastel blue     – Recovery
    "Z2": "#B8E0B8",  # Pastel green    – Aerobic / fat-burning
    "Z3": "#F9F1A5",  # Pastel yellow   – Tempo
    "Z4": "#FAC898",  # Pastel orange   – Threshold
    "Z5": "#F4A0A0",  # Pastel red      – VO2 max / Red line
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

# Ordered list of zone colors matching ZONE_ORDER
ZONE_COLORS_LIST = [ZONE_COLORS[z] for z in ZONE_ORDER]

# ── Strava Activity Type Colours ───────────────────────────────────────
# Fixed mapping so colors never shift when the date range changes.
# Unknown types fall back to ACTIVITY_TYPE_DEFAULT_COLOR.

ACTIVITY_TYPE_COLORS: Dict[str, str] = {
    # Running – pastel blue
    "Run": "#88B4E7",
    "TrailRun": "#5A90D0",
    "VirtualRun": "#B8D4F0",
    # Cycling – warm peach pastel
    "Ride": "#F4A261",
    "VirtualRide": "#F9C9A3",
    "MountainBikeRide": "#E76F51",
    "GravelRide": "#F4B483",
    "EBikeRide": "#FAD7BD",
    # Walking & hiking – soft green pastel
    "Walk": "#A8C5A0",
    "Hike": "#7DAF74",
    # Water – light blue pastel
    "Swim": "#A8D8EA",
    "Rowing": "#7BBFDA",
    "Kayaking": "#9DCFE0",
    "StandUpPaddling": "#6BB5D0",
    "Surfing": "#B8E0EE",
    # Winter – pale lavender
    "AlpineSki": "#C9C9E3",
    "BackcountrySki": "#AEAED4",
    "NordicSki": "#D9D9EF",
    "Snowboard": "#B8B8D8",
    "IceSkate": "#E8E8F5",
    # Gym & fitness
    "WeightTraining": "#ED6A5A",  # coral-red pastel
    "Yoga": "#F4F1BB",  # pale yellow pastel
    "Pilates": "#F9F5D0",  # lighter yellow
    "Workout": "#F2A59D",  # light coral
    "CrossFit": "#E8857A",  # medium coral
    "Elliptical": "#D4EDDA",  # pale mint
    "StairStepper": "#C8E6C9",  # soft green
    # Other
    "RockClimbing": "#C4A882",
    "Golf": "#B5D5A0",
    "Soccer": "#A8D5A2",
    "Tennis": "#E8EFB0",
    "InlineSkate": "#FAE0B0",
    "Skateboard": "#D5C5B5",
}

ACTIVITY_TYPE_DEFAULT_COLOR = "#CFCFCF"  # light grey – fallback for unknown types


def classify_zone(hr: float, zones: tuple) -> str:
    """Classify a heart rate value into a zone string (Z1–Z5)."""
    z1, z2, z3, z4 = zones
    if hr <= z1:
        return "Z1"
    if hr <= z2:
        return "Z2"
    if hr <= z3:
        return "Z3"
    if hr <= z4:
        return "Z4"
    return "Z5"
