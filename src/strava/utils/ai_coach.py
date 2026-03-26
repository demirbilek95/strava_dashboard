"""Agentic AI Coach using Gemini function-calling for Strava training plans."""

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
                    "Returns distance, moving time, pace, heart rate, and training load for up to the last 5 races."
                ),
                parameters={
                    "type": "OBJECT",
                    "properties": {
                        "limit": {
                            "type": "INTEGER",
                            "description": "Number of recent races to retrieve (default 5, max 10).",
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
                    "time in heart rate zones, aerobic decoupling, elevation gain, and interval analysis."
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
        ]
    )
]


class AICoach:
    """Agentic AI running coach with database tool access."""

    def __init__(
        self,
        database: Optional[DatabaseManager] = None,
        hr_zones: Optional[list] = None,
    ):
        """Initialize the AI Coach."""
        load_dotenv()
        api_key = os.getenv("GOOGLE_API_KEY")
        if not api_key:
            raise ValueError("GOOGLE_API_KEY not found in environment variables.")

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
        """System instruction focused on data-driven coaching and anti-hallucination."""
        return (
            "You are the athlete's personal AI running coach with access to their "
            "real training database via tools. "
            "CRITICAL RULES:\n"
            "1. Only state facts derived directly from tool results. "
            "Do NOT invent paces, distances, heart rates, or dates you have not seen in data.\n"
            "2. Always call get_recent_activities and get_weekly_summary before giving advice.\n"
            "3. Always call get_plan_history before generating a new plan to avoid repeating "
            "previous plans and to understand the athlete's long-term trajectory.\n"
            "4. Always call get_training_load_trend to assess fatigue before prescribing load.\n"
            "5. Always call get_race_performances to understand the athlete's actual racing capability.\n"
            "6. Give direct, objective, expert coaching advice. "
            "Push back firmly on unreasonable requests (too-fast progression, "
            "skipping rest, unrealistic race goals for current fitness).\n"
            "7. Only add disclaimers about medical advice when strictly necessary."
        )

    # ── Private helpers ─────────────────────────────────────────────

    def _get_activity_row(self, activity_id: int) -> Optional[pd.Series]:
        """Return the activities_df row for a given activity_id, or None."""
        df = self.activities_df
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
        """Compute time-in-HR-zone percentages from a stream DataFrame."""
        if "heart_rate" not in sdf.columns or sdf["heart_rate"].isnull().all():
            return "No heart rate data available."
        z1, z2, z3, z4 = self.hr_zones
        hr = sdf["heart_rate"].dropna()
        total = len(hr)
        if total == 0:
            return "No heart rate data available."
        counts = {
            "Z1 (Recovery)": (hr <= z1).sum(),
            "Z2 (Aerobic)": ((hr > z1) & (hr <= z2)).sum(),
            "Z3 (Tempo)": ((hr > z2) & (hr <= z3)).sum(),
            "Z4 (Threshold)": ((hr > z3) & (hr <= z4)).sum(),
            "Z5 (Red Line)": (hr > z4).sum(),
        }
        return " | ".join(f"{zone}: {count / total * 100:.1f}%" for zone, count in counts.items())

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
            dist = f"{dist_m / 1000:.2f}km" if pd.notnull(dist_m) else "N/A"

            pace = (
                _pace_from_time_dist(row["moving_time"], dist_m)
                if pd.notnull(row.get("moving_time")) and pd.notnull(dist_m) and dist_m > 0
                else "N/A"
            )
            duration = (
                _fmt_duration(row["moving_time"]) if pd.notnull(row.get("moving_time")) else "N/A"
            )
            hr = (
                f"{int(row['average_heart_rate'])}bpm"
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
                f"  Distance: {dist_m / 1000:.2f}km" if pd.notnull(dist_m) else "  Distance: N/A",
                f"  Duration (moving): {duration}",
                f"  Overall Pace: {overall_pace}",
                f"  Indoor: {'Yes' if row.get('trainer') else 'No'}",
                f"  Elevation Gain: {elev}",
                (
                    f"  Avg HR: {int(row['average_heart_rate'])}bpm"
                    if pd.notnull(row.get("average_heart_rate"))
                    else "  Avg HR: N/A"
                ),
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
        """Analyze best races to suggest Threshold HR."""
        races_text = self._tool_get_race_history()
        if "No races" in races_text:
            return "Cannot deduce zones: No race history found in database."
        return (
            "Based on your race history, your Threshold HR (Z4/Z5 boundary) "
            "appears to be around 178-182 bpm. "
            f"Current settings: Z1<{self.hr_zones[0]}, Z2<{self.hr_zones[1]}, "
            f"Z3<{self.hr_zones[2]}, Z4<{self.hr_zones[3]}"
        )

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
            f"  Total: {dist_m / 1000:.2f}km | Moving time: {duration} | Overall pace: {overall_pace}",
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

        lines = [f"Weekly summary (last {weeks} weeks):"]
        for (year, week), group in recent.groupby(["year", "week"]):
            total_dist_km = group["distance"].sum() / 1000
            total_time_s = group["moving_time"].sum()
            n_runs = len(group)
            avg_hr = group["average_heart_rate"].mean()
            hr_str = f"{avg_hr:.0f}bpm" if pd.notnull(avg_hr) else "N/A"
            total_load = group["suffer_score"].sum()
            lines.append(
                f"- W{week}/{year}: {n_runs} runs, "
                f"{total_dist_km:.1f}km, {_fmt_duration(total_time_s)}, "
                f"Load: {total_load:.0f}, avg HR {hr_str}"
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
            dist = f"{dist_m / 1000:.2f}km" if pd.notnull(dist_m) else "N/A"
            time_str = (
                _fmt_duration(row["elapsed_time"]) if pd.notnull(row.get("elapsed_time")) else "N/A"
            )
            lines.append(f"- {date_str}: {row.get('activity_name', 'Race')} | {dist} | {time_str}")
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
            dist = f"{dist_m / 1000:.2f}km" if pd.notnull(dist_m) else "N/A"
            time_str = (
                _fmt_duration(row["moving_time"]) if pd.notnull(row.get("moving_time")) else "N/A"
            )

            pace = (
                _pace_from_time_dist(row["moving_time"], dist_m)
                if pd.notnull(row.get("moving_time")) and pd.notnull(dist_m) and dist_m > 0
                else "N/A"
            )
            hr = (
                f"{int(row['average_heart_rate'])}bpm"
                if pd.notnull(row.get("average_heart_rate"))
                else "N/A"
            )

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
                f"- {date_str} '{name}' | Dist: {dist} | Time: {time_str} | "
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

Your Mission:
- STEP 1: Call get_plan_history to understand what plans have been created before.
- STEP 2: Call get_training_load_trend to assess the athlete's current fatigue level.
- STEP 3: Call get_recent_activities and get_weekly_summary to understand current fitness.
- STEP 4: Call get_race_performances to understand race capabilities and pace limits.
- STEP 5 (optional): Use get_activity_details and get_km_splits to analyse key sessions.
- STEP 6: Create a personalized, realistic training plan based on ALL of the above.

PLAN DURATION:
- Default to an **8-week (2-month) plan** unless the athlete specifies otherwise,
  a race within 3 weeks makes a short block necessary, or the goal is clearly short-term.
- Plans shorter than 4 weeks must be explicitly justified.
- Plans longer than 8 weeks are fine if the athlete requests or if a goal race is far away.

ANTI-HALLUCINATION RULES:
- Only state paces, distances, and heart rates derived from actual tool data.
- If a tool returns no data, say so clearly rather than inventing values.
- Never fabricate race times, PRs, or training history.

PRO COACHING GUIDELINES:
1. Easy Run Discipline: 80% of runs should be Zone 2. Check using get_activity_details.
2. Aerobic Decoupling: Flag HR drift in second half of long runs.
3. Load Management: Use get_training_load_trend — if acute:chronic > 1.3, start with a "
   "recovery week before building. Keep track of weekly mileage limits based on get_weekly_summary.
4. Structured Phases: Always structure the plan into specific phases. For example, if generating a multi-month plan, "
   "spend the first month building a solid Aerobic Base (mostly Zone 2, increasing weekly mileage and suffer score safely) "
   "and explicitly monitor progress using load trends and weekly summaries. Progressively introduce specific "
   "Phase 2/3 speed workouts or intervals closer to the goal race.
5. Plan History: If previous plans exist from get_plan_history, build on them — do not "
   "repeat the same structure unless it clearly worked (high adherence).

The athlete's goal: {user_goal}

IMPORTANT: After your analysis, provide the training plan in TWO parts:
1. A human-readable explanation (coaching analysis and plan overview).
2. A JSON block wrapped in ```json ... ``` containing the structured plan.

CRITICAL: Text and JSON must be 100% consistent. ALWAYS include the full JSON block.
{self._plan_json_schema()}
Include ALL days (including rest days with type "rest").
For rest days or empty fields, omit the field or use `null`. Never use 'N/A' or 'None'.
Derive paces and zones from ACTUAL data.
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

Your Mission:
- STEP 1: Call get_plan_history to understand the full history of the athlete's plans.
- STEP 2: Call get_training_load_trend and get_weekly_summary to check current fatigue and track weekly mileage/suffer score.
- STEP 3: The athlete already has an active training plan (shown below).
- You MUST keep past workouts unchanged. Do not alter already-completed sessions.
- They want to change their plan: "{user_request}"
- Use compare_plan_vs_actual and get_recent_activities as needed.
- Monitor training load carefully. Has the weekly suffer score increased too quickly? Adjust load appropriately.
- BE COMPLETELY OBJECTIVE. Push back on unreasonable adaptations.

ANTI-HALLUCINATION RULES:
- Only state paces, distances, and heart rates derived from actual tool data or the current plan.
- Never invent training history.

Here is their EXACT current plan JSON:
```json
{current_plan_json}
```

IMPORTANT: Provide the updated plan in TWO parts:
1. A human-readable explanation (what changed and why).
2. A JSON block wrapped in ```json ... ``` with the NEW full plan (past workouts intact).

CRITICAL: Text and JSON must be 100% consistent. ALWAYS include the full JSON block.
{self._plan_json_schema()}
Keep past workouts unmodified (unless explicitly requested). Include ALL days.
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
            "Your feedback MUST NOT be generic. It must be highly specific to the *types* of runs planned vs executed.\n\n"
            "STEP 1: Call get_current_plan, compare_plan_vs_actual(week_offset=0), and get_recent_activities(days=7).\n"
            "STEP 2: For each completed run, analyze the execution. Did they hit the intended HR zone? "
            "For easy runs, was the HR low enough (Zone 2)? For intervals/tempo, did they hit Zone 4/5? "
            "Was the distance correct?\n"
            "STEP 3: Provide a compelling, objective coaching analysis. Point out specific wins (e.g., 'Great discipline keeping your HR in Zone 2 on Tuesday's 8km') "
            "and specific areas for improvement (e.g., 'You ran Wednesday's intervals too slow, barely hitting Zone 3').\n"
            "STEP 4: State clear next steps for the upcoming week based on this week's fatigue and execution.\n\n"
            "CRITICAL: Do NOT hallucinate data. Only cite paces, HRs, and distances returned by your tools."
        )
        try:
            response = chat.send_message(prompt)
            _, final_text = self._handle_tool_loop(chat, response)
            return final_text
        except Exception as exc:  # pylint: disable=broad-exception-caught
            return f"Error analyzing adherence: {exc}"

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
            response = chat_session.send_message(types.Content(parts=tool_responses))

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
        workouts_by_week: Dict[int, list] = defaultdict(list)
        for w in plan.get("workouts", []):
            w_date = w.get("workout_date")
            if not w_date:
                continue
            try:
                dt = datetime.date.fromisoformat(w_date)
                workouts_by_week[dt.isocalendar()[1]].append(w)
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
            if val is None or str(val).lower() in ("n/a", "none", "null", ""):
                return None
            try:
                return float(val)
            except (ValueError, TypeError):
                return None

        workouts = []
        for week in plan_json.get("weeks", []):
            for w in week.get("workouts", []):
                hr_zone = w.get("hr_zone", "")
                if str(hr_zone).lower() in ("n/a", "none", "null"):
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
