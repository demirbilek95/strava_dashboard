"""Agentic AI Coach using Gemini function-calling for Strava training plans."""

# pylint: disable=too-many-lines

import os
import json
import datetime
import re
from collections import defaultdict
from typing import Optional, Dict, Any, List, Tuple

import pandas as pd
from google import genai
from google.genai import types
from dotenv import load_dotenv

from strava.constants import INVALID_STR_VALUES
from strava.db.db_manager import DatabaseManager


# ── Shared formatting helpers ──────────────────────────────────────────


def _fmt_pace(pace_dec_min_per_km: float) -> str:
    """Format a decimal pace (min/km) as MM:SS/km."""
    mins = int(pace_dec_min_per_km)
    secs = int((pace_dec_min_per_km - mins) * 60)
    return f"{mins}:{secs:02d}/km"


def _pace_from_speed_ms(speed_ms: float) -> str:
    """Convert m/s speed to formatted pace string."""
    if speed_ms <= 0:
        return "N/A"
    return _fmt_pace((1 / speed_ms) * 1000 / 60)


def _pace_from_time_dist(time_s: float, dist_m: float) -> str:
    """Compute pace from elapsed time (seconds) and distance (metres)."""
    if dist_m <= 0 or time_s <= 0:
        return "N/A"
    return _fmt_pace((time_s / 60) / (dist_m / 1000))


def _fmt_duration(total_seconds: float) -> str:
    """Format seconds as H:MM:SS or M:SS."""
    total_s = int(total_seconds)
    h, remainder = divmod(total_s, 3600)
    m, s = divmod(remainder, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def _fmt_dist_km(dist_m) -> str:
    """Format a distance in metres as km string, or 'N/A'."""
    if dist_m is None or not pd.notnull(dist_m):
        return "N/A"
    return f"{float(dist_m) / 1000:.2f}km"


def _fmt_hr(hr) -> str:
    """Format a heart-rate value as 'NNNbpm', or 'N/A'."""
    if hr is None or not pd.notnull(hr):
        return "N/A"
    return f"{int(hr)}bpm"


# ── Tool function declarations for google-genai ───────────────────────

COACH_TOOLS = [
    types.Tool(
        function_declarations=[
            types.FunctionDeclaration(
                name="get_recent_activities",
                description=(
                    "Query the athlete's recent activities from the database. "
                    "Returns a summary of each activity including date, type, "
                    "distance, pace, heart rate, suffer_score (training load), and elevation. "
                    "NOTE: distance is in metres, pace is derived from moving_time."
                ),
                parameters={
                    "type": "OBJECT",
                    "properties": {
                        "days": {
                            "type": "INTEGER",
                            "description": "Number of days to look back (default 28)",
                        },
                    },
                },
            ),
            types.FunctionDeclaration(
                name="get_weekly_summary",
                description=(
                    "Get weekly mileage, total time, total suffer_score (training load), "
                    "and average pace aggregates for the last N weeks."
                ),
                parameters={
                    "type": "OBJECT",
                    "properties": {
                        "weeks": {
                            "type": "INTEGER",
                            "description": "Number of weeks to summarize (default 4)",
                        },
                    },
                },
            ),
            types.FunctionDeclaration(
                name="get_race_history",
                description=(
                    "Fetch the athlete's race results (workout_type=1 or 'race' in name). "
                    "Returns up to the last 10 races."
                ),
                parameters={"type": "OBJECT", "properties": {}},
            ),
            types.FunctionDeclaration(
                name="get_race_performances",
                description=(
                    "Fetch detailed performance metrics for the athlete's most recent races. "
                    "Returns distance, moving time, pace, heart rate, and training load "
                    "for up to the last 5 races."
                ),
                parameters={
                    "type": "OBJECT",
                    "properties": {
                        "limit": {
                            "type": "INTEGER",
                            "description": "Number of recent races to retrieve (default 5, max 10).",  # pylint: disable=line-too-long
                        }
                    },
                },
            ),
            types.FunctionDeclaration(
                name="get_current_plan",
                description="Retrieve the currently active training plan from the database.",
                parameters={"type": "OBJECT", "properties": {}},
            ),
            types.FunctionDeclaration(
                name="compare_plan_vs_actual",
                description=(
                    "Compare planned workouts against actual activities for a "
                    "given week offset (0 = current week, 1 = last week, etc.)."
                ),
                parameters={
                    "type": "OBJECT",
                    "properties": {
                        "week_offset": {
                            "type": "INTEGER",
                            "description": "0 for current week, 1 for last week, etc.",
                        },
                    },
                },
            ),
            types.FunctionDeclaration(
                name="is_indoor_activity",
                description=(
                    "Check if a specific activity was performed indoors (on a trainer/treadmill). "
                    "This is important because indoor data (like GPS) may be missing or inaccurate."
                ),
                parameters={
                    "type": "OBJECT",
                    "properties": {
                        "activity_id": {
                            "type": "INTEGER",
                            "description": "The ID of the activity to check.",
                        },
                    },
                    "required": ["activity_id"],
                },
            ),
            types.FunctionDeclaration(
                name="get_activity_details",
                description=(
                    "Get second-by-second analytics for a specific activity, including "
                    "time in heart rate zones, aerobic decoupling, elevation gain, "
                    "and interval analysis."
                ),
                parameters={
                    "type": "OBJECT",
                    "properties": {
                        "activity_id": {
                            "type": "INTEGER",
                            "description": "The ID of the activity to analyze.",
                        },
                    },
                    "required": ["activity_id"],
                },
            ),
            types.FunctionDeclaration(
                name="deduce_performance_zones",
                description=(
                    "Analyze recent race history to deduce your actual heart rate zones "
                    "and performance limits."
                ),
                parameters={"type": "OBJECT", "properties": {}},
            ),
            types.FunctionDeclaration(
                name="get_km_splits",
                description=(
                    "Get accurate per-kilometre split data for a specific activity: "
                    "pace (derived from elapsed time, NOT instantaneous speed), heart rate, "
                    "cadence, and elevation change per km. Detects pacing errors, cardiac "
                    "drift, or late-run fatigue."
                ),
                parameters={
                    "type": "OBJECT",
                    "properties": {
                        "activity_id": {
                            "type": "INTEGER",
                            "description": "The ID of the activity to analyse.",
                        },
                    },
                    "required": ["activity_id"],
                },
            ),
            types.FunctionDeclaration(
                name="get_training_load_trend",
                description=(
                    "Compute a rolling training load trend using suffer_score / relative_effort "
                    "from the database. Returns 7-day and 28-day cumulative loads and their "
                    "ratio (acute:chronic) to assess fatigue vs fitness balance. "
                    "ALWAYS call this before generating a new plan."
                ),
                parameters={"type": "OBJECT", "properties": {}},
            ),
            types.FunctionDeclaration(
                name="get_plan_history",
                description=(
                    "Retrieve all past training plans (active and archived). "
                    "Use this to avoid repeating a previous plan and to understand "
                    "the athlete's long-term training history. "
                    "ALWAYS call this before generating a new plan."
                ),
                parameters={"type": "OBJECT", "properties": {}},
            ),
            types.FunctionDeclaration(
                name="get_best_efforts",
                description=(
                    "Fetch the athlete's all-time personal records (PRs) at standard "
                    "distances: 400m, 1km, 1 mile, 5K, 10K, Half-Marathon, Marathon. "
                    "Returns time, pace, and average HR for each PR. "
                    "ALWAYS call this before generating a plan or giving race/workout feedback — "
                    "use these paces to set realistic training targets."
                ),
                parameters={"type": "OBJECT", "properties": {}},
            ),
            types.FunctionDeclaration(
                name="get_activity_laps",
                description=(
                    "Get lap-by-lap breakdown for a specific activity: distance, time, "
                    "pace, heart rate, and cadence per lap. Essential for analysing "
                    "structured workouts and interval sessions — did the athlete hit "
                    "target paces? Did effort drop off in later intervals?"
                ),
                parameters={
                    "type": "OBJECT",
                    "properties": {
                        "activity_id": {
                            "type": "INTEGER",
                            "description": "The ID of the activity to analyse.",
                        },
                    },
                    "required": ["activity_id"],
                },
            ),
            types.FunctionDeclaration(
                name="get_fitness_trend",
                description=(
                    "Compute monthly volume, activity count, average HR, and training "
                    "load for the last 12 weeks. Shows whether the athlete is building, "
                    "stable, or declining in fitness. "
                    "ALWAYS call this before generating a plan."
                ),
                parameters={"type": "OBJECT", "properties": {}},
            ),
            types.FunctionDeclaration(
                name="get_plan_adherence",
                description=(
                    "Return training plan adherence broken down by workout type "
                    "(e.g. easy_run: 12/15, intervals: 3/8). Covers the active plan "
                    "and up to 2 recent archived plans. "
                    "ALWAYS call this before generating or adapting a plan — use it to "
                    "understand which session types the athlete consistently skips."
                ),
                parameters={"type": "OBJECT", "properties": {}},
            ),
        ]
    )
]


class AICoach:
    """Agentic AI running coach with database tool access."""

    def __init__(
        self,
        database: Optional[DatabaseManager] = None,
        hr_zones: Optional[list] = None,
        api_key: Optional[str] = None,
    ):
        """Initialize the AI Coach."""
        load_dotenv()
        api_key = api_key or os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        if not api_key:
            raise ValueError("No Gemini API key found.")

        self.api_key = api_key
        self.client = genai.Client(api_key=api_key)
        self.model_id = "gemini-2.5-flash"
        self.db = database or DatabaseManager()

        if not hr_zones or len(hr_zones) != 4:
            raise ValueError("hr_zones must be a list of 4 heart rate zone limits.")
        self.hr_zones = hr_zones

        self._activities_df: Optional[pd.DataFrame] = None
        self.tools = COACH_TOOLS

    @property
    def activities_df(self) -> pd.DataFrame:
        """Lazy-load activities dataframe (distance in raw metres from DB)."""
        if self._activities_df is None:
            rows = self.db.execute_query("SELECT * FROM activities ORDER BY activity_date DESC")
            self._activities_df = pd.DataFrame([dict(r) for r in rows])
            if "activity_date" in self._activities_df.columns:
                self._activities_df["activity_date"] = pd.to_datetime(
                    self._activities_df["activity_date"]
                )
        return self._activities_df

    @property
    def _coach_system_instruction(self) -> str:
        """System instruction for a data-driven, direct coach persona."""
        return (
            "You are a data-driven running coach with full access to the athlete's training "
            "database via tools. Your job is to give direct, specific, actionable coaching — "
            "not generic advice.\n\n"
            "COACHING VOICE:\n"
            "- Speak like a real coach: direct, honest, and motivating. Use 'we' framing "
            "('we need to build your aerobic base before adding intensity').\n"
            "- Name patterns honestly — if the athlete skips hard sessions, say so.\n"
            "- Acknowledge what is working, not just what needs fixing.\n"
            "- Push back on unrealistic goals with data: 'Your current 5K pace is X, "
            "which makes Y goal very tight in this timeframe.'\n"
            "- Never add unnecessary hedges or medical disclaimers.\n\n"
            "DATA RULES (non-negotiable):\n"
            "1. Only state facts derived directly from tool results. "
            "Never invent paces, distances, heart rates, or dates.\n"
            "2. If a tool returns no data, say so clearly — do not substitute invented values.\n"
            "3. Always call the relevant tools before giving advice. "
            "Advice without data is just guessing.\n"
            "4. Use get_best_efforts paces to anchor all target paces — never make them up."
        )

    # ── Private helpers ─────────────────────────────────────────────

    def _get_activity_row(self, activity_id: int) -> Optional[pd.Series]:
        """Return the activities_df row for a given activity_id, or None."""
        df = self.activities_df
        if df.empty or "activity_id" not in df.columns:
            return None
        match = df[df["activity_id"] == activity_id]
        return match.iloc[0] if not match.empty else None

    def _get_stream_df(self, activity_id: int) -> Optional[pd.DataFrame]:
        """Fetch stream data for an activity as a DataFrame, or None if empty."""
        streams = self.db.get_activity_stream(activity_id)
        if not streams:
            return None
        sdf = pd.DataFrame(streams)
        sdf = sdf.sort_values("elapsed_seconds").reset_index(drop=True)
        return sdf

    def _hr_zone_breakdown(self, sdf: pd.DataFrame) -> str:
        """Compute time-in-HR-zone percentages from a stream DataFrame.

        Uses elapsed-time weighting (seconds between rows) and exclusive upper
        boundaries to match the Deep Dive view exactly.
        """
        if "heart_rate" not in sdf.columns or sdf["heart_rate"].isnull().all():
            return "No heart rate data available."
        if "elapsed_seconds" not in sdf.columns:
            return "No elapsed time data available."

        z1, z2, z3, z4 = self.hr_zones
        df = sdf[["elapsed_seconds", "heart_rate"]].dropna().copy()
        if df.empty:
            return "No heart rate data available."

        df["time_diff"] = df["elapsed_seconds"].diff().fillna(0).clip(lower=0)
        total_time = df["time_diff"].sum()
        if total_time <= 0:
            return "No heart rate data available."

        def _zone_idx(h: float) -> int:
            if h < z1:
                return 0
            if h < z2:
                return 1
            if h < z3:
                return 2
            if h < z4:
                return 3
            return 4

        df["zone"] = df["heart_rate"].apply(_zone_idx)
        zone_labels = [
            "Z1 (Recovery)",
            "Z2 (Aerobic)",
            "Z3 (Tempo)",
            "Z4 (Threshold)",
            "Z5 (Red Line)",
        ]
        parts = []
        for i, label in enumerate(zone_labels):
            zone_time = df[df["zone"] == i]["time_diff"].sum()
            parts.append(f"{label}: {zone_time / total_time * 100:.1f}%")
        return " | ".join(parts)

    @staticmethod
    def _km_bucket_stats(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Split stream rows into 1-km buckets and compute per-km stats.

        Pace is derived from (elapsed_seconds delta / distance delta) for
        accuracy — NOT from instantaneous speed averages, which are noisy.

        Returns a list of dicts with keys: km, pace, time_s, dist_m,
        avg_hr, avg_cadence, elev_delta.
        """
        buckets: Dict[int, List[Dict[str, Any]]] = defaultdict(list)
        for row in rows:
            dist = row.get("distance") or 0
            buckets[int(dist // 1000)].append(row)

        results = []
        for km in sorted(buckets.keys()):
            seg = buckets[km]

            # Time: elapsed_seconds spread within this bucket
            times = [r["elapsed_seconds"] for r in seg if r.get("elapsed_seconds") is not None]
            dists = [r["distance"] for r in seg if r.get("distance") is not None]
            seg_time_s = max(times) - min(times) if len(times) > 1 else 0
            seg_dist_m = max(dists) - min(dists) if dists else 0

            pace = _pace_from_time_dist(seg_time_s, seg_dist_m)

            hr_vals = [r["heart_rate"] for r in seg if r.get("heart_rate") and r["heart_rate"] > 0]
            avg_hr = sum(hr_vals) / len(hr_vals) if hr_vals else None

            cad_vals = [r["cadence"] for r in seg if r.get("cadence") and r["cadence"] > 0]
            avg_cadence = sum(cad_vals) / len(cad_vals) if cad_vals else None

            alt_col = "enhanced_altitude" if seg[0].get("enhanced_altitude") else "altitude"
            alt_vals = [r.get(alt_col) for r in seg if r.get(alt_col) is not None]
            elev_delta = (alt_vals[-1] - alt_vals[0]) if len(alt_vals) >= 2 else None

            results.append(
                {
                    "km": km + 1,
                    "pace": pace,
                    "time_s": seg_time_s,
                    "dist_m": seg_dist_m,
                    "avg_hr": avg_hr,
                    "avg_cadence": avg_cadence,
                    "elev_delta": elev_delta,
                    "is_partial": seg_dist_m < 800,
                }
            )
        return results

    # ── Tool implementations ────────────────────────────────────────

    def _tool_get_recent_activities(self, days: int = 28) -> str:
        """Return a text summary of recent activities."""
        df = self.activities_df
        if df.empty:
            return "No activities found."

        cutoff = pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=days)
        recent = df[df["activity_date"] >= cutoff].sort_values("activity_date")

        if recent.empty:
            return f"No activities in the last {days} days."

        lines = [f"Activities in last {days} days ({len(recent)} total):"]
        for _, row in recent.iterrows():
            date_str = row["activity_date"].strftime("%Y-%m-%d")
            dist_m = row.get("distance")
            dist = _fmt_dist_km(dist_m)

            pace = (
                _pace_from_time_dist(row["moving_time"], dist_m)
                if pd.notnull(row.get("moving_time")) and pd.notnull(dist_m) and dist_m > 0
                else "N/A"
            )
            duration = (
                _fmt_duration(row["moving_time"]) if pd.notnull(row.get("moving_time")) else "N/A"
            )
            hr = (
                _fmt_hr(row.get("average_heart_rate"))
                if pd.notnull(row.get("average_heart_rate"))
                else ""
            )
            is_indoor = " [INDOOR]" if row.get("trainer") else ""
            elev = (
                f"| Elev: {row['elevation_gain']}m" if pd.notnull(row.get("elevation_gain")) else ""
            )
            score = (
                f"| Load: {int(row['suffer_score'])}" if pd.notnull(row.get("suffer_score")) else ""
            )
            lines.append(
                f"- ID:{row.get('activity_id', 'N/A')} | {date_str}: "
                f"{row.get('activity_type', 'Run')} '{row.get('activity_name', '')}'"
                f"{is_indoor} | {dist} | {pace} | {duration} {hr} {score} {elev}"
            )
        return "\n".join(lines)

    def _tool_is_indoor_activity(self, activity_id: int) -> str:
        """Check whether an activity was done indoors."""
        row = self._get_activity_row(activity_id)
        if row is None:
            return f"Activity ID {activity_id} not found."
        return (
            "Yes, this was an indoor activity (trainer)."
            if row.get("trainer")
            else "No, this was an outdoor activity."
        )

    def _tool_get_activity_details(self, activity_id: int) -> str:
        """Retrieve HR-zone breakdown and aerobic decoupling for an activity."""
        row = self._get_activity_row(activity_id)
        if row is None:
            return f"Activity ID {activity_id} not found."

        sdf = self._get_stream_df(activity_id)
        if sdf is None:
            return f"Detailed stream data not found for activity {activity_id}."

        hr_analysis = self._hr_zone_breakdown(sdf)

        # Aerobic decoupling (first half vs second half efficiency)
        half = len(sdf) // 2
        decoupling = "N/A"

        def _efficiency(chunk: pd.DataFrame) -> Optional[float]:
            valid_hr = (
                chunk[chunk["heart_rate"] > 0]["heart_rate"]
                if "heart_rate" in chunk
                else pd.Series(dtype=float)
            )
            valid_sp = (
                chunk[chunk["speed"] > 0]["speed"] if "speed" in chunk else pd.Series(dtype=float)
            )
            if valid_hr.empty or valid_sp.empty:
                return None
            return float(valid_sp.mean() / valid_hr.mean())

        eff1 = _efficiency(sdf.iloc[:half])
        eff2 = _efficiency(sdf.iloc[half:])
        if eff1 and eff2:
            drop = (eff1 - eff2) / eff1 * 100
            decoupling = f"{drop:.1f}% (positive = efficiency dropped)"

        elev = f"{row.get('elevation_gain')}m" if pd.notnull(row.get("elevation_gain")) else "N/A"
        dist_m = row.get("distance")
        duration = (
            _fmt_duration(row["moving_time"]) if pd.notnull(row.get("moving_time")) else "N/A"
        )
        overall_pace = (
            _pace_from_time_dist(row["moving_time"], dist_m)
            if pd.notnull(row.get("moving_time")) and pd.notnull(dist_m) and dist_m > 0
            else "N/A"
        )

        return "\n".join(
            [
                f"Details for Activity {activity_id} ({row.get('activity_name', 'Run')}):",
                f"  Distance: {_fmt_dist_km(dist_m)}",
                f"  Duration (moving): {duration}",
                f"  Overall Pace: {overall_pace}",
                f"  Indoor: {'Yes' if row.get('trainer') else 'No'}",
                f"  Elevation Gain: {elev}",
                f"  Avg HR: {_fmt_hr(row.get('average_heart_rate'))}",
                f"  Intensity (Time in Zones): {hr_analysis}",
                f"  Aerobic Decoupling (Cardiac Drift): {decoupling}",
                (
                    f"  Relative Score (Suffer Score): {int(row['suffer_score'])}"
                    if pd.notnull(row.get("suffer_score"))
                    else "  Relative Score: N/A"
                ),
            ]
        )

    def _tool_deduce_performance_zones(self) -> str:
        """Report the user's configured HR zones and cross-check against race HR data."""
        z1, z2, z3, z4 = self.hr_zones
        lines = [
            "Athlete's configured HR zones (set in the sidebar):",
            f"  Z1 Recovery:  < {z1} bpm",
            f"  Z2 Aerobic:   {z1} – {z2 - 1} bpm",
            f"  Z3 Tempo:     {z2} – {z3 - 1} bpm",
            f"  Z4 Threshold: {z3} – {z4 - 1} bpm",
            f"  Z5 Red Line:  ≥ {z4} bpm",
        ]

        # Cross-check against best effort HR data if available
        prs = self.db.get_pr_summary()
        reference_efforts = [
            e for e in prs if e.get("effort_name") in ("5k", "10k") and e.get("average_heartrate")
        ]
        if reference_efforts:
            lines.append("")
            lines.append("Race HR reference (from best efforts):")
            for effort in reference_efforts:
                hr = int(effort["average_heartrate"])
                name = effort["effort_name"]
                # 5K avg HR ≈ slightly above threshold; 10K avg HR ≈ threshold
                note = "≈ slightly above threshold" if name == "5k" else "≈ threshold"
                lines.append(f"  {name} best effort avg HR: {hr} bpm ({note})")
            hrs = [int(e["average_heartrate"]) for e in reference_efforts]
            suggested = sum(hrs) // len(hrs)
            if suggested < z3 or suggested > z4:
                lines.append(
                    f"  ⚠️  Race data suggests threshold HR around {suggested} bpm, "
                    f"but your Z4 is set to {z3}–{z4 - 1} bpm. "
                    "Consider adjusting your zones in the sidebar."
                )
            else:
                lines.append(
                    f"  ✅ Race data ({suggested} bpm) is consistent with your Z4 setting."
                )
        else:
            lines.append("")
            lines.append(
                "No 5K/10K best effort HR data available to cross-check zones. "
                "Zone settings are taken as configured."
            )

        return "\n".join(lines)

    def _tool_get_km_splits(self, activity_id: int) -> str:
        """
        Compute per-km split stats using elapsed_seconds delta (NOT speed average).

        Speed averaging is unreliable due to GPS noise and acceleration spikes.
        Instead, pace = (time at end of km – time at start of km) / distance covered.
        """
        row = self._get_activity_row(activity_id)
        if row is None:
            return f"Activity ID {activity_id} not found."

        sdf = self._get_stream_df(activity_id)
        if sdf is None:
            return f"No stream data found for activity {activity_id}."

        if "distance" not in sdf.columns or sdf["distance"].isnull().all():
            return "No distance data in streams — cannot compute km splits."
        if "elapsed_seconds" not in sdf.columns or sdf["elapsed_seconds"].isnull().all():
            return "No elapsed_seconds data in streams — cannot compute km splits."

        total_m = float(sdf["distance"].max())
        if total_m < 500:
            return f"Activity too short ({total_m:.0f}m) to compute km splits."

        dist_m = row.get("distance") or total_m
        moving_time = row.get("moving_time")
        overall_pace = (
            _pace_from_time_dist(moving_time, dist_m) if moving_time and dist_m else "N/A"
        )
        duration = _fmt_duration(moving_time) if moving_time else "N/A"

        splits = self._km_bucket_stats(sdf.to_dict("records"))

        lines = [
            f"Km-by-km splits for Activity {activity_id} " f"({row.get('activity_name', 'Run')}):",
            f"  Total: {_fmt_dist_km(dist_m)} | Moving time: {duration} "
            f"| Overall pace: {overall_pace}",
            "",
        ]
        for split in splits:
            label = f"Km {split['km']}"
            if split["is_partial"]:
                label += f" (partial {split['dist_m']:.0f}m)"

            hr_str = f"{split['avg_hr']:.0f}bpm" if split["avg_hr"] else "N/A"
            cad_str = f" | Cadence: {split['avg_cadence']:.0f}spm" if split["avg_cadence"] else ""
            if split["elev_delta"] is not None:
                sign = "+" if split["elev_delta"] >= 0 else ""
                elev_str = f" | Elev: {sign}{split['elev_delta']:.0f}m"
            else:
                elev_str = ""

            lines.append(f"  {label}: {split['pace']} | HR: {hr_str}{cad_str}{elev_str}")
        return "\n".join(lines)

    def _tool_get_weekly_summary(self, weeks: int = 4) -> str:
        """Return aggregate weekly stats (distance, time, HR)."""
        df = self.activities_df
        if df.empty:
            return "No activities found."

        cutoff = pd.Timestamp.now(tz="UTC") - pd.Timedelta(weeks=weeks)
        recent = df[df["activity_date"] >= cutoff].copy()

        if recent.empty:
            return f"No activities in the last {weeks} weeks."

        recent["week"] = recent["activity_date"].dt.isocalendar().week
        recent["year"] = recent["activity_date"].dt.isocalendar().year

        today = pd.Timestamp.now(tz="UTC")
        cur_iso = today.isocalendar()
        current_week_key = (cur_iso[0], cur_iso[1])
        days_elapsed = today.weekday() + 1  # Mon=1 … Sun=7

        lines = [f"Weekly summary (last {weeks} weeks):"]
        for (year, week), group in recent.groupby(["year", "week"]):
            total_dist_km = group["distance"].sum() / 1000
            total_time_s = group["moving_time"].sum()
            n_runs = len(group)
            avg_hr = group["average_heart_rate"].mean()
            hr_str = f"{avg_hr:.0f}bpm" if pd.notnull(avg_hr) else "N/A"
            total_load = group["suffer_score"].sum()
            if (year, week) == current_week_key:
                suffix = (
                    f" ← IN PROGRESS ({days_elapsed}/7 days elapsed; "
                    "do NOT compare mileage or load to completed weeks)"
                )
            else:
                suffix = ""
            lines.append(
                f"- W{week}/{year}: {n_runs} runs, "
                f"{total_dist_km:.1f}km, {_fmt_duration(total_time_s)}, "
                f"Load: {total_load:.0f}, avg HR {hr_str}{suffix}"
            )
        return "\n".join(lines)

    def _tool_get_race_history(self) -> str:
        """Fetch and format the last 10 race results."""
        df = self.activities_df
        if df.empty:
            return "No activities found."

        races = pd.DataFrame()
        if "workout_type" in df.columns:
            races = df[df["workout_type"] == 1]
        if races.empty:
            races = df[df["activity_name"].str.contains("race", case=False, na=False)]
        if races.empty:
            return "No races found."

        lines = ["Race history (most recent first):"]
        for _, row in races.head(10).iterrows():
            date_str = row["activity_date"].strftime("%Y-%m-%d")
            dist_m = row.get("distance")
            time_str = (
                _fmt_duration(row["elapsed_time"]) if pd.notnull(row.get("elapsed_time")) else "N/A"
            )
            lines.append(
                f"- {date_str}: {row.get('activity_name', 'Race')} "
                f"| {_fmt_dist_km(dist_m)} | {time_str}"
            )
        return "\n".join(lines)

    def _tool_get_race_performances(self, limit: int = 5) -> str:
        """Fetch detailed analytics for the latest races."""
        df = self.activities_df
        if df.empty:
            return "No activities found."

        races = pd.DataFrame()
        if "workout_type" in df.columns:
            races = df[df["workout_type"] == 1]
        if races.empty:
            races = df[df["activity_name"].str.contains("race", case=False, na=False)]

        if races.empty:
            return "No races found."

        limit = min(limit, 10)
        lines = [f"Detailed race performances (last {limit} races):"]
        for _, row in races.head(limit).iterrows():
            date_str = row["activity_date"].strftime("%Y-%m-%d")
            name = row.get("activity_name", "Race")

            dist_m = row.get("distance")
            time_str = (
                _fmt_duration(row["moving_time"]) if pd.notnull(row.get("moving_time")) else "N/A"
            )

            pace = (
                _pace_from_time_dist(row["moving_time"], dist_m)
                if pd.notnull(row.get("moving_time")) and pd.notnull(dist_m) and dist_m > 0
                else "N/A"
            )
            hr = _fmt_hr(row.get("average_heart_rate"))

            score_col = (
                "suffer_score"
                if "suffer_score" in row and pd.notnull(row["suffer_score"])
                else "relative_effort"
            )
            score = (
                int(row[score_col])
                if score_col in row and pd.notnull(row.get(score_col))
                else "N/A"
            )
            elev = (
                f"{row.get('elevation_gain')}m" if pd.notnull(row.get("elevation_gain")) else "N/A"
            )

            lines.append(
                f"- {date_str} '{name}' | Dist: {_fmt_dist_km(dist_m)} | Time: {time_str} | "
                f"Pace: {pace} | HR: {hr} | Elev: {elev} | Load: {score}"
            )
        return "\n".join(lines)

    def _tool_get_current_plan(self) -> str:
        """Retrieve and format the currently active training plan."""
        plan = self.db.get_active_plan()
        if not plan:
            return "No active training plan found."

        lines = [
            f"Active Plan: {plan['goal']}",
            f"Period: {plan['start_date']} to {plan.get('end_date', 'ongoing')}",
            f"Workouts ({len(plan['workouts'])} total):",
        ]
        for w in plan["workouts"]:
            status = "✅" if w["completed"] else "⬜"
            dist = f"{w['target_distance_km']}km" if w.get("target_distance_km") else ""
            lines.append(
                f"- {status} {w['workout_date']}: {w['workout_type']} "
                f"- {w.get('description', '')} {dist}"
            )
        return "\n".join(lines)

    def _tool_compare_plan_vs_actual(self, week_offset: int = 0) -> str:
        """Compare planned vs actual workouts for a given week."""
        plan = self.db.get_active_plan()
        if not plan:
            return "No active plan to compare against."

        today = datetime.date.today()
        week_start = today - datetime.timedelta(days=today.weekday() + 7 * week_offset)
        week_end = week_start + datetime.timedelta(days=6)

        planned = [
            w
            for w in plan["workouts"]
            if week_start.isoformat() <= w["workout_date"] <= week_end.isoformat()
        ]
        if not planned:
            return f"No workouts planned for the week of {week_start}."

        df = self.activities_df
        actual = (
            df[
                (df["activity_date"].dt.date >= week_start)
                & (df["activity_date"].dt.date <= week_end)
            ]
            if not df.empty
            else pd.DataFrame()
        )

        lines = [f"Plan vs Actual for week of {week_start}:"]
        done = sum(1 for w in planned if w["completed"])
        for w in planned:
            status = "✅ Done" if w["completed"] else "❌ Missed"
            lines.append(
                f"- {w['workout_date']} ({w['workout_type']}): {status} "
                f"| Target: {w.get('target_distance_km', '?')}km"
            )

        lines.append(f"\nAdherence: {done}/{len(planned)} planned workouts done")
        extra = len(actual) - done if not actual.empty else 0
        if extra > 0:
            lines.append(f"Extra (unplanned) activities: {extra}")
        return "\n".join(lines)

    def _tool_get_training_load_trend(self) -> str:
        """Compute acute (7-day) and chronic (28-day) training load from suffer_score."""
        df = self.activities_df
        if df.empty:
            return "No activities available for load trend."

        now = pd.Timestamp.now(tz="UTC")
        w7 = now - pd.Timedelta(days=7)
        w28 = now - pd.Timedelta(days=28)

        score_col = None
        for candidate in ("suffer_score", "relative_effort"):
            if candidate in df.columns and df[candidate].notna().any():
                score_col = candidate
                break

        if score_col is None:
            # fallback: estimate from moving_time * avg_hr proxy
            if "moving_time" in df.columns and "average_heart_rate" in df.columns:
                df = df.copy()
                df["_effort"] = (
                    df["moving_time"].fillna(0) / 60 * df["average_heart_rate"].fillna(0) / 100
                )
                score_col = "_effort"
            else:
                return "No suffer_score or HR data available for load trend."

        acute = df[df["activity_date"] >= w7][score_col].sum()
        chronic = df[df["activity_date"] >= w28][score_col].mean() * 7  # weekly avg
        ratio = acute / chronic if chronic > 0 else None

        assessment = ""
        if ratio is not None:
            if ratio < 0.8:
                assessment = "Low load — athlete may be undertraining or tapering."
            elif ratio <= 1.3:
                assessment = "Optimal load — good balance of stress and recovery."
            else:
                assessment = (
                    "HIGH load — acute stress significantly exceeds chronic base. "
                    "Risk of overtraining. Recommend recovery week."
                )

        return "\n".join(
            [
                f"Training Load Trend (based on {score_col}):",
                f"  7-day acute load: {acute:.0f}",
                f"  28-day chronic load (weekly avg): {chronic:.0f}",
                f"  Acute:Chronic ratio: {ratio:.2f}" if ratio else "  Ratio: N/A",
                f"  Assessment: {assessment}" if assessment else "",
            ]
        )

    def _tool_get_plan_history(self) -> str:
        """Return a summary of all past training plans."""
        plans = self.db.get_plan_history()
        if not plans:
            return "No training plan history found. This will be the athlete's first plan."

        lines = [f"Training plan history ({len(plans)} plan(s)):\n"]
        for p in plans:
            adherence = ""
            if p.get("workout_count") and p["workout_count"] > 0:
                pct = int(p["completed_count"] / p["workout_count"] * 100)
                adherence = f" | Adherence: {pct}% ({p['completed_count']}/{p['workout_count']})"
            lines.append(
                f"- [{p['status'].upper()}] {p['start_date']} → {p.get('end_date', 'N/A')}: "
                f"{p['goal']}{adherence}"
            )
        return "\n".join(lines)

    def _tool_get_best_efforts(self) -> str:
        """Return all-time PRs for standard distances from the best_efforts table."""
        prs = self.db.get_pr_summary()
        if not prs:
            return "No best effort data found. Athlete may not have Strava-calculated segments."

        lines = ["All-time personal records (PRs):"]
        for pr in prs:
            elapsed = pr.get("elapsed_time") or pr.get("moving_time")
            dist = pr.get("distance") or 0
            time_str = _fmt_duration(elapsed) if elapsed else "N/A"
            pace = _pace_from_time_dist(elapsed, dist) if elapsed and dist > 0 else "N/A"
            date_str = str(pr.get("activity_date", ""))[:10] or "N/A"
            hr_str = (
                f" | Avg HR: {int(pr['average_heartrate'])}bpm"
                if pr.get("average_heartrate")
                else ""
            )
            lines.append(f"  {pr['effort_name']}: {time_str} ({pace}) — {date_str}{hr_str}")
        return "\n".join(lines)

    def _tool_get_activity_laps(self, activity_id: int) -> str:
        """Return lap-by-lap data for a specific activity."""
        row = self._get_activity_row(activity_id)
        if row is None:
            return f"Activity ID {activity_id} not found."

        laps = self.db.get_activity_laps(activity_id)
        if not laps:
            return (
                f"No lap data found for activity {activity_id}. "
                "This activity may not have been recorded with lap markers."
            )

        lines = [
            f"Laps for Activity {activity_id} ({row.get('activity_name', 'Run')}):",
            f"  {len(laps)} lap(s) total",
            "",
        ]
        for lap in laps:
            dist_m = lap.get("distance") or 0
            moving = lap.get("moving_time")
            pace = _pace_from_time_dist(moving, dist_m) if moving and dist_m > 0 else "N/A"
            duration = _fmt_duration(moving) if moving else "N/A"
            hr = f" | HR: {lap['average_heartrate']:.0f}bpm" if lap.get("average_heartrate") else ""
            cad = f" | Cad: {lap['average_cadence']:.0f}spm" if lap.get("average_cadence") else ""
            lines.append(
                f"  Lap {lap['lap_index'] + 1}: "
                f"{_fmt_dist_km(dist_m)} | {duration} | {pace}{hr}{cad}"
            )
        return "\n".join(lines)

    def _tool_get_fitness_trend(self) -> str:
        """Compute monthly volume and load for the last 12 weeks."""
        df = self.activities_df
        if df.empty:
            return "No activities available for fitness trend."

        cutoff = pd.Timestamp.now(tz="UTC") - pd.Timedelta(weeks=12)
        recent = df[df["activity_date"] >= cutoff].copy()
        if recent.empty:
            return "No activities in the last 12 weeks."

        recent["month_key"] = recent["activity_date"].dt.strftime("%Y-%m")
        lines = ["Monthly fitness trend (last ~12 weeks):"]
        monthly_kms: List[float] = []

        for month_key, group in recent.groupby("month_key"):
            total_km = group["distance"].sum() / 1000
            monthly_kms.append(total_km)
            n = len(group)
            avg_hr = group["average_heart_rate"].mean()
            hr_str = f"{avg_hr:.0f}bpm" if pd.notnull(avg_hr) else "N/A"
            load_col = next(
                (
                    c
                    for c in ("suffer_score", "relative_effort")
                    if c in group.columns and group[c].notna().any()
                ),
                None,
            )
            load = group[load_col].sum() if load_col else 0
            lines.append(
                f"  {month_key}: {n} activities, {total_km:.1f}km, "
                f"avg HR {hr_str}, load {load:.0f}"
            )

        if len(monthly_kms) >= 2:
            if monthly_kms[-1] > monthly_kms[-2] * 1.1:
                lines.append("  Overall trend: BUILDING ↑")
            elif monthly_kms[-1] < monthly_kms[-2] * 0.9:
                lines.append("  Overall trend: DECLINING ↓")
            else:
                lines.append("  Overall trend: STABLE →")

        return "\n".join(lines)

    def _tool_get_plan_adherence(self) -> str:
        """Return per-workout-type adherence for the active plan and recent archived plans."""
        plans = self.db.get_plan_history()
        if not plans:
            return "No training plans found. This athlete has not used a structured plan yet."

        lines = ["Training plan adherence by workout type (past workouts only):"]
        for plan in plans[:3]:
            plan_id = plan["plan_id"]
            status = plan["status"].upper()
            by_type = self.db.get_adherence_by_workout_type(plan_id)
            # Derive overall from past-only rows so future workouts don't deflate the score.
            past_total = sum(r["total"] for r in by_type)
            past_done = sum(r["completed"] for r in by_type)
            if past_total == 0:
                overall_str = "Plan just started — no past workouts to assess yet."
            else:
                overall_pct = int(past_done / past_total * 100)
                overall_str = f"Overall: {overall_pct}% ({past_done}/{past_total} past workouts)"
            lines.append(
                f"\n[{status}] \"{plan['goal']}\" "
                f"({plan['start_date']} → {plan.get('end_date', 'ongoing')}) "
                f"— {overall_str}"
            )
            if by_type:
                for row in by_type:
                    pct = int(row["completed"] / row["total"] * 100) if row["total"] > 0 else 0
                    status_icon = "✅" if pct >= 75 else ("⚠️" if pct >= 40 else "❌")
                    lines.append(
                        f"  {status_icon} {row['workout_type'].replace('_', ' ').title()}: "
                        f"{row['completed']}/{row['total']} ({pct}%)"
                    )

        return "\n".join(lines)

    def _dispatch_tool_call(self, function_call) -> str:
        """Execute a tool function call from Gemini and return the result."""
        name = function_call.name
        args = dict(function_call.args) if function_call.args else {}

        dispatch = {
            "get_recent_activities": self._tool_get_recent_activities,
            "get_weekly_summary": self._tool_get_weekly_summary,
            "get_race_history": self._tool_get_race_history,
            "get_race_performances": self._tool_get_race_performances,
            "get_current_plan": self._tool_get_current_plan,
            "compare_plan_vs_actual": self._tool_compare_plan_vs_actual,
            "is_indoor_activity": self._tool_is_indoor_activity,
            "get_activity_details": self._tool_get_activity_details,
            "deduce_performance_zones": self._tool_deduce_performance_zones,
            "get_km_splits": self._tool_get_km_splits,
            "get_training_load_trend": self._tool_get_training_load_trend,
            "get_plan_history": self._tool_get_plan_history,
            "get_best_efforts": self._tool_get_best_efforts,
            "get_activity_laps": self._tool_get_activity_laps,
            "get_fitness_trend": self._tool_get_fitness_trend,
            "get_plan_adherence": self._tool_get_plan_adherence,
        }

        handler = dispatch.get(name)
        if not handler:
            return f"Unknown tool: {name}"
        return handler(**args)

    # ── Public methods ──────────────────────────────────────────────

    def _make_chat(self) -> object:
        """Create a fresh Gemini chat session configured with tools."""
        return self.client.chats.create(
            model=self.model_id,
            config=types.GenerateContentConfig(
                system_instruction=self._coach_system_instruction,
                tools=self.tools,
            ),
        )

    def generate_plan(self, user_goal: str) -> Tuple[Optional[object], str]:
        """Generate a structured training plan.

        Returns (chat_session, plan_text).
        The plan text includes a JSON block that can be parsed for DB storage.
        """
        current_date = datetime.date.today().strftime("%Y-%m-%d")
        system_prompt = f"""You are an expert running coach. Today is {current_date}.

DATA GATHERING (complete ALL steps before writing a single workout):
- STEP 1: Call get_plan_adherence AND get_plan_history — understand what the athlete has
  historically completed vs skipped. If interval adherence is low, plan fewer hard sessions.
  If easy run adherence is high, build on that strength.
- STEP 2: Call get_training_load_trend — if acute:chronic > 1.3, the first week MUST be
  a recovery week, not a build.
- STEP 3: Call get_recent_activities, get_weekly_summary, AND get_fitness_trend — understand
  current form and whether fitness is building, stable, or declining.
- STEP 4: Call get_race_performances AND get_best_efforts — these are your only source of
  truth for target paces. NEVER invent paces. Derive all training paces from actual PR data.
- STEP 5 (optional): Use get_activity_details or get_km_splits to dig into key recent sessions.

PLAN DURATION:
- Default to an 8-week plan unless the athlete specifies otherwise or has a race < 3 weeks away.
- Plans shorter than 4 weeks must be explicitly justified.

COACHING GUIDELINES:
1. Pace targets: Use get_best_efforts to derive easy, tempo, and interval paces. Never invent them.
2. Adherence-aware load: If the athlete's historical hard-session adherence is below 50%, start
   with one quality session per week and build from there. Name this decision explicitly.
3. 80/20 rule: 80% of weekly volume should be Zone 2 / easy effort.
4. Load management: Keep week-over-week volume increases under 10% unless coming off a taper.
5. Phased structure: Base → Build → Peak → (Taper if race). Label each week's phase.
6. Plan continuity: Build on previous plans — do not repeat a structure with poor adherence.

The athlete's goal: {user_goal}

After your analysis, provide the plan in TWO parts:
1. Coaching analysis (what the data shows, what the plan addresses, and why).
2. A JSON block wrapped in ```json ... ``` with the full structured plan.

CRITICAL: Text and JSON must be 100% consistent. ALWAYS include the full JSON block.
{self._plan_json_schema()}
Include ALL days (including rest days with type "rest").
For empty numeric fields use null. Never use 'N/A' or 'None' as a value.
All paces must be decimal min/km derived from get_best_efforts data.
If a day has multiple sessions, output SEPARATE workout objects with the same "date".
"""
        chat = self._make_chat()
        try:
            response = chat.send_message(system_prompt)
            _, final_text = self._handle_tool_loop(chat, response)
            return chat, final_text
        except Exception as exc:  # pylint: disable=broad-exception-caught
            return None, f"Error generating plan: {exc}"

    def adapt_plan(self, user_request: str) -> Tuple[Optional[object], str]:
        """Adapt the existing training plan based on user request."""
        current_date = datetime.date.today().strftime("%Y-%m-%d")
        plan = self.db.get_active_plan()
        if not plan:
            return None, "No active plan found to adapt."

        current_plan_json = self._plan_to_json_str(plan)

        system_prompt = f"""You are an expert running coach. Today is {current_date}.

DATA GATHERING (complete before making any changes):
- STEP 1: Call get_plan_adherence — understand which session types the athlete is
  completing vs skipping. Use this to inform the adaptation.
- STEP 2: Call get_training_load_trend and get_weekly_summary — check current fatigue
  before adding or moving sessions.
- STEP 3: Use compare_plan_vs_actual and get_recent_activities as needed.
- STEP 4: Call get_best_efforts if the adaptation involves changing pace targets.

ADAPTATION RULES:
- Do NOT modify already-completed workouts.
- Be objective: push back on requests that risk injury or ignore fatigue data.
- If the athlete wants to add a hard session but the load trend is already high (ratio > 1.3),
  say so and suggest a safer alternative.
- If adherence to a certain workout type is low, flag it: adapting a plan to add more of
  something the athlete already avoids rarely works.

The athlete's request: "{user_request}"

Current plan (JSON):
```json
{current_plan_json}
```

Provide the adaptation in TWO parts:
1. Explanation: what changed, why, and any coaching observations about the request.
2. A JSON block wrapped in ```json ... ``` with the FULL updated plan.

CRITICAL: Text and JSON must be 100% consistent. ALWAYS include the full JSON block.
{self._plan_json_schema()}
Past completed workouts must remain unchanged. Include ALL days.
If a day has multiple sessions, output SEPARATE workout objects with the same "date".
"""
        chat = self._make_chat()
        try:
            response = chat.send_message(system_prompt)
            _, final_text = self._handle_tool_loop(chat, response)
            return chat, final_text
        except Exception as exc:  # pylint: disable=broad-exception-caught
            return None, f"Error adapting plan: {exc}"

    def chat(self, chat_session: object, message: str) -> str:
        """Send a follow-up message in an existing chat session."""
        try:
            response = chat_session.send_message(message)
            _, final_text = self._handle_tool_loop(chat_session, response)
            return final_text
        except Exception as exc:  # pylint: disable=broad-exception-caught
            return f"Error: {exc}"

    def analyze_adherence(self) -> str:
        """Autonomously analyze plan adherence for the current week."""
        chat = self._make_chat()
        prompt = (
            "You are an expert running coach reviewing the athlete's plan adherence for this week. "
            "Your feedback MUST NOT be generic. It must be highly specific to the "
            "*types* of runs planned vs executed.\n\n"
            "STEP 1: Call get_current_plan, compare_plan_vs_actual(week_offset=0), "
            "and get_recent_activities(days=7).\n"
            "STEP 2: For each completed run, analyze the execution. "
            "Did they hit the intended HR zone? "
            "For easy runs, was the HR low enough (Zone 2)? "
            "For intervals/tempo, did they hit Zone 4/5? Was the distance correct?\n"
            "STEP 3: Provide a compelling, objective coaching analysis. "
            "Point out specific wins and specific areas for improvement with exact numbers.\n"
            "STEP 4: State clear next steps for the upcoming week based on this week's "
            "fatigue and execution.\n\n"
            "CRITICAL: Do NOT hallucinate data. "
            "Only cite paces, HRs, and distances returned by your tools."
        )
        try:
            response = chat.send_message(prompt)
            _, final_text = self._handle_tool_loop(chat, response)
            return final_text
        except Exception as exc:  # pylint: disable=broad-exception-caught
            return f"Error analyzing adherence: {exc}"

    def athlete_snapshot(self) -> str:
        """Generate a concise coach's brief of the athlete's current state.

        Calls multiple tools automatically and returns a structured summary
        covering recent form, load status, key PRs, adherence pattern, and
        recommended focus areas.
        """
        chat = self._make_chat()
        today = datetime.date.today().strftime("%Y-%m-%d")
        prompt = (
            f"Today is {today}. Give me a brief, direct coach's summary of this athlete's "
            "current training state.\n\n"
            "Call these tools first (in order):\n"
            "1. get_recent_activities (days=14)\n"
            "2. get_weekly_summary (weeks=4)\n"
            "3. get_training_load_trend\n"
            "4. get_best_efforts\n"
            "5. get_fitness_trend\n"
            "6. get_plan_adherence\n\n"
            "Structure your response with these exact headings:\n"
            "**Current Form** — 2-3 sentences on the quality of recent training.\n"
            "**Load Status** — 1 sentence interpreting the acute:chronic ratio in plain language.\n"
            "**Key PRs** — bullet list of the 3 most relevant best efforts with times and paces.\n"
            "**Adherence Pattern** — 1-2 sentences on plan adherence history. Be honest: "
            "name which session types get skipped if there is a pattern.\n"
            "**Recommended Focus** — 2 specific, actionable things to work on right now, "
            "grounded in the data above.\n\n"
            "Keep the total under 300 words. Every number you cite must come from a tool result."
        )
        try:
            response = chat.send_message(prompt)
            _, final_text = self._handle_tool_loop(chat, response)
            return final_text
        except Exception as exc:  # pylint: disable=broad-exception-caught
            return f"Could not generate snapshot: {exc}"

    def _handle_tool_loop(
        self, chat_session, response, max_iterations: int = 10
    ) -> Tuple[object, str]:
        """Handle Gemini function-calling loop until a text response is returned."""
        for _ in range(max_iterations):
            if not response.candidates:
                return response, "Error: No response candidates returned by the model."

            candidate = response.candidates[0]
            if not candidate.content or not candidate.content.parts:
                return response, "Error: Model returned an empty response or was blocked."

            parts = candidate.content.parts
            function_calls = [p for p in parts if p.function_call]

            if not function_calls:
                text_parts = [p.text for p in parts if p.text]
                return response, "\n".join(text_parts)

            tool_responses = [
                types.Part(
                    function_response=types.FunctionResponse(
                        name=part.function_call.name,
                        response={"result": self._dispatch_tool_call(part.function_call)},
                    )
                )
                for part in function_calls
            ]
            response = chat_session.send_message(tool_responses)

        # Fallback if max iterations reached
        if (
            response.candidates
            and response.candidates[0].content
            and response.candidates[0].content.parts
        ):
            text_parts = [p.text for p in response.candidates[0].content.parts if p.text]
            if text_parts:
                return response, "\n".join(text_parts)
        return response, "Plan generation timed out."

    # ── Static helpers ──────────────────────────────────────────────

    @staticmethod
    def _plan_json_schema() -> str:
        """Return the JSON schema block used in both generate and adapt prompts."""
        return """```json
{
  "start_date": "YYYY-MM-DD",
  "end_date": "YYYY-MM-DD",
  "weeks": [
    {
      "week_number": 1,
      "workouts": [
        {
          "day": "Monday",
          "date": "YYYY-MM-DD",
          "type": "easy_run|tempo|intervals|long_run|rest|cross_training|recovery",
          "description": "Easy recovery run, Zone 2",
          "distance_km": 6.0,
          "duration_min": 36,
          "pace_min_km": 6.0,
          "hr_zone": "Zone 2"
        }
      ]
    }
  ]
}
```"""

    @staticmethod
    def _plan_to_json_str(plan: Dict[str, Any]) -> str:
        """Convert an active plan dict (from DB) into a JSON string for prompts."""
        workouts_by_week: Dict[tuple, list] = defaultdict(list)
        for w in plan.get("workouts", []):
            w_date = w.get("workout_date")
            if not w_date:
                continue
            try:
                dt = datetime.date.fromisoformat(w_date)
                iso = dt.isocalendar()
                workouts_by_week[(iso[0], iso[1])].append(
                    w
                )  # (year, week) preserves cross-year order
            except ValueError:
                pass

        weeks_list = [
            {
                "week_number": i + 1,
                "workouts": [
                    {
                        "date": w.get("workout_date"),
                        "type": w.get("workout_type"),
                        "description": w.get("description"),
                        "distance_km": w.get("target_distance_km"),
                        "duration_min": w.get("target_duration_min"),
                        "pace_min_km": w.get("target_pace_min_km"),
                        "hr_zone": w.get("target_hr_zone"),
                    }
                    for w in w_list
                ],
            }
            for i, (_, w_list) in enumerate(sorted(workouts_by_week.items()))
        ]
        return json.dumps(
            {
                "start_date": plan.get("start_date", ""),
                "end_date": plan.get("end_date", ""),
                "weeks": weeks_list,
            },
            indent=2,
        )

    @staticmethod
    def parse_plan_json(plan_text: str) -> Optional[Dict[str, Any]]:
        """Extract and parse the JSON plan block from LLM response text."""
        pattern = r"```json\s*(.*?)\s*```"
        match = re.search(pattern, plan_text, re.DOTALL)
        if not match:
            return None
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            return None

    @staticmethod
    def plan_json_to_workouts(plan_id: int, plan_json: Dict[str, Any]) -> list:
        """Convert parsed plan JSON to a list of workout dicts for DB insertion."""

        def _parse_num(val):
            if val is None or str(val).lower() in INVALID_STR_VALUES:
                return None
            try:
                return float(val)
            except (ValueError, TypeError):
                return None

        workouts = []
        for week in plan_json.get("weeks", []):
            for w in week.get("workouts", []):
                hr_zone = w.get("hr_zone", "")
                if str(hr_zone).lower() in INVALID_STR_VALUES:
                    hr_zone = None
                workouts.append(
                    {
                        "plan_id": plan_id,
                        "workout_date": w.get("date", ""),
                        "workout_type": w.get("type", "rest"),
                        "description": w.get("description", ""),
                        "target_distance_km": _parse_num(w.get("distance_km")),
                        "target_duration_min": _parse_num(w.get("duration_min")),
                        "target_pace_min_km": _parse_num(w.get("pace_min_km")),
                        "target_hr_zone": hr_zone,
                    }
                )
        return workouts
