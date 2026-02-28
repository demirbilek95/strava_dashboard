"""Agentic AI Coach using Gemini function-calling for Strava training plans."""

import os
import json
import datetime
import re
from typing import Optional, Dict, Any, Tuple

import pandas as pd
from google import genai
from google.genai import types
from dotenv import load_dotenv

from strava.db.db_manager import DatabaseManager


# ── Tool function declarations for google-genai ───────────────────────

COACH_TOOLS = [
    types.Tool(
        function_declarations=[
            types.FunctionDeclaration(
                name="get_recent_activities",
                description=(
                    "Query the athlete's recent activities from the database. "
                    "Returns a summary of each activity including date, type, "
                    "distance, pace, heart rate, and elevation."
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
                    "Get weekly mileage, total time, and average pace aggregates "
                    "for the last N weeks."
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
                    "time in heart rate zones, aerobic decoupling, and interval analysis."
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
        ]
    )
]


class AICoach:  # pylint: disable=too-few-public-methods
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
        # "gemini-latest" is not a valid API alias, mapping to the actual latest model
        self.model_id = "gemini-2.5-flash"
        self.db = database or DatabaseManager()
        
        if not hr_zones or len(hr_zones) != 4:
            raise ValueError("hr_zones must be a list of 4 heart rate zone limits.")
        self.hr_zones = hr_zones
        
        self._activities_df = None
        self.tools = COACH_TOOLS

    @property
    def activities_df(self) -> pd.DataFrame:
        """Lazy-load activities dataframe."""
        if self._activities_df is None:
            rows = self.db.execute_query("SELECT * FROM activities ORDER BY activity_date DESC")
            self._activities_df = pd.DataFrame([dict(r) for r in rows])
            if "activity_date" in self._activities_df.columns:
                self._activities_df["activity_date"] = pd.to_datetime(
                    self._activities_df["activity_date"]
                )
        return self._activities_df

    # ── Tool implementations ────────────────────────────────────────

    def _tool_get_recent_activities(self, days: int = 28) -> str:
        df = self.activities_df
        if df.empty:
            return "No activities found."

        cutoff = pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=days)
        recent = df[df["activity_date"] >= cutoff].sort_values("activity_date", ascending=True)

        if recent.empty:
            return f"No activities in the last {days} days."

        lines = [f"Activities in last {days} days ({len(recent)} total):"]
        for _, row in recent.iterrows():
            date_str = row["activity_date"].strftime("%Y-%m-%d")
            dist = f"{row['distance'] / 1000:.2f}km" if pd.notnull(row.get("distance")) else "N/A"
            pace = "N/A"
            if (
                pd.notnull(row.get("moving_time"))
                and pd.notnull(row.get("distance"))
                and row["distance"] > 0
            ):
                pace_dec = (row["moving_time"] / 60) / (row["distance"] / 1000)
                mins = int(pace_dec)
                secs = int((pace_dec - mins) * 60)
                pace = f"{mins}:{secs:02d}/km"

            hr = (
                f"{int(row['average_heart_rate'])}bpm"
                if pd.notnull(row.get("average_heart_rate"))
                else ""
            )
            workout_type = row.get("activity_type", "Run")
            name = row.get("activity_name", "")
            is_indoor = " [INDOOR]" if row.get("trainer") else ""
            activity_id = row.get("activity_id", "N/A")
            lines.append(
                f"- ID:{activity_id} | {date_str}: {workout_type} '{name}'{is_indoor} "
                f"| {dist} | {pace} | {hr}"
            )
        return "\n".join(lines)

    def _tool_is_indoor_activity(self, activity_id: int) -> str:
        df = self.activities_df
        activity = df[df["activity_id"] == activity_id]
        if activity.empty:
            return f"Activity ID {activity_id} not found."

        is_trainer = activity.iloc[0].get("trainer", False)
        return "Yes, this was an indoor activity (trainer)." if is_trainer else "No, this was an outdoor activity."

    def _tool_get_activity_details(self, activity_id: int) -> str:
        """Retrieve and analyze second-by-second stream data for an activity."""
        # 1. Get Activity Summary
        df = self.activities_df
        activity = df[df["activity_id"] == activity_id]
        if activity.empty:
            return f"Activity ID {activity_id} not found."
        
        summ = activity.iloc[0]
        is_indoor = bool(summ.get("trainer", False))
        
        # 2. Get Streams
        streams = self.db.get_activity_stream(activity_id)
        if not streams:
            return f"Detailed stream data (GPS/HR) not found for activity {activity_id}."
        
        sdf = pd.DataFrame(streams)
        
        # 3. Time in HR Zones
        z1, z2, z3, z4 = self.hr_zones
        counts = {
            "Z1 (Recovery)": len(sdf[sdf["heart_rate"] <= z1]),
            "Z2 (Aerobic)": len(sdf[(sdf["heart_rate"] > z1) & (sdf["heart_rate"] <= z2)]),
            "Z3 (Tempo)": len(sdf[(sdf["heart_rate"] > z2) & (sdf["heart_rate"] <= z3)]),
            "Z4 (Threshold)": len(sdf[(sdf["heart_rate"] > z3) & (sdf["heart_rate"] <= z4)]),
            "Z5 (Red Line)": len(sdf[sdf["heart_rate"] > z4]),
        }
        total = sum(counts.values())
        if total == 0:
            hr_analysis = "No heart rate data available in streams."
        else:
            hr_parts = []
            for zone, count in counts.items():
                pct = (count / total) * 100
                hr_parts.append(f"{zone}: {pct:.1f}%")
            hr_analysis = " | ".join(hr_parts)

        # 4. Aerobic Decoupling (First half vs Second half)
        half = len(sdf) // 2
        fhalf = sdf.iloc[:half]
        shalf = sdf.iloc[half:]
        
        def get_efficiency(chunk):
            valid_hr = chunk[chunk["heart_rate"] > 0]
            valid_speed = chunk[chunk["speed"] > 0]
            if valid_hr.empty or valid_speed.empty:
                return None
            return valid_speed["speed"].mean() / valid_hr["heart_rate"].mean()

        eff1 = get_efficiency(fhalf)
        eff2 = get_efficiency(shalf)
        
        decoupling = "N/A"
        if eff1 and eff2:
            drop = ((eff1 - eff2) / eff1) * 100
            decoupling = f"{drop:.1f}% (positive % means efficiency dropped)"

        analysis = [
            f"Details for Activity {activity_id} ({summ.get('activity_name', 'Run')}):",
            f"Indoor: {'Yes' if is_indoor else 'No'}",
            f"Intensity (Time in Zones): {hr_analysis}",
            f"Aerobic Decoupling (Cardiac Drift): {decoupling}",
            "Coach's Tip: If you pushed too hard on an easy run, your time in Z3/Z4 will be high."
        ]
        
        return "\n".join(analysis)

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

    def _tool_get_weekly_summary(self, weeks: int = 4) -> str:
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
            total_dist = group["distance"].sum() / 1000
            total_time = group["moving_time"].sum() / 60
            n_activities = len(group)
            avg_hr = group["average_heart_rate"].mean()
            hr_str = f"{avg_hr:.0f}bpm" if pd.notnull(avg_hr) else "N/A"
            lines.append(
                f"- W{week}/{year}: {n_activities} runs, "
                f"{total_dist:.1f}km, {total_time:.0f}min, avg HR {hr_str}"
            )
        return "\n".join(lines)

    def _tool_get_race_history(self) -> str:
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
            name = row.get("activity_name", "Race")
            dist = f"{row['distance'] / 1000:.2f}km" if pd.notnull(row.get("distance")) else "N/A"
            time_str = "N/A"
            if pd.notnull(row.get("elapsed_time")):
                total_s = int(row["elapsed_time"])
                h, m, s = total_s // 3600, (total_s % 3600) // 60, total_s % 60
                time_str = f"{h}:{m:02d}:{s:02d}"
            lines.append(f"- {date_str}: {name} | {dist} | {time_str}")
        return "\n".join(lines)

    def _tool_get_current_plan(self) -> str:
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

        # Get actual activities for the same period
        df = self.activities_df
        if not df.empty:
            actual = df[
                (df["activity_date"].dt.date >= week_start)
                & (df["activity_date"].dt.date <= week_end)
            ]
        else:
            actual = pd.DataFrame()

        lines = [f"Plan vs Actual for week of {week_start}:"]
        done = 0
        for w in planned:
            status = "✅ Done" if w["completed"] else "❌ Missed"
            if w["completed"]:
                done += 1
            lines.append(
                f"- {w['workout_date']} ({w['workout_type']}): {status} "
                f"| Target: {w.get('target_distance_km', '?')}km"
            )

        lines.append(f"\nAdherence: {done}/{len(planned)} planned workouts done")
        if not actual.empty:
            extra = len(actual) - done
            if extra > 0:
                lines.append(f"Extra (unplanned) activities: {extra}")
        return "\n".join(lines)

    def _dispatch_tool_call(self, function_call) -> str:
        """Execute a tool function call from Gemini and return the result."""
        name = function_call.name
        args = dict(function_call.args) if function_call.args else {}

        dispatch = {
            "get_recent_activities": self._tool_get_recent_activities,
            "get_weekly_summary": self._tool_get_weekly_summary,
            "get_race_history": self._tool_get_race_history,
            "get_current_plan": self._tool_get_current_plan,
            "compare_plan_vs_actual": self._tool_compare_plan_vs_actual,
            "is_indoor_activity": self._tool_is_indoor_activity,
            "get_activity_details": self._tool_get_activity_details,
            "deduce_performance_zones": self._tool_deduce_performance_zones,
        }

        handler = dispatch.get(name)
        if not handler:
            return f"Unknown tool: {name}"
        return handler(**args)

    # ── Public methods ──────────────────────────────────────────────

    def generate_plan(self, user_goal: str) -> Tuple[Optional[object], str]:
        """Generate a structured training plan.

        Returns (chat_session, plan_text).
        The plan text includes a JSON block that can be parsed for DB storage.
        """
        current_date = datetime.date.today().strftime("%Y-%m-%d")

        system_prompt = f"""You are an expert running coach. Today is {current_date}.

Your Mission:
- Use the available tools to analyze the athlete's data BEFORE generating a plan.
- Call get_recent_activities and get_weekly_summary to understand their current fitness.
- Call get_race_history to understand their race performance.
- Use is_indoor_activity if you suspect an activity data might be inaccurate or missing GPS.
- Use get_activity_details to analyze specific sessions, especially for "easy run discipline".
- Create a personalized, realistic training plan.
- Be honest about goal feasibility.

PRO COACHING GUIDELINES:
1. Easy Run Discipline: The athlete struggles with keeping their heart rate low on easy/recovery runs. Monitor this closely using get_activity_details. For indoor runs, prioritize HR data over pace.
2. Aerobic Decoupling: If HR rises significantly for the same pace in the second half of a run, identify it as a sign of poor aerobic base or fatigue.
3. Race Deduction: Use race data to validate their intensity zones.

The athlete's goal: {user_goal}

IMPORTANT: After your analysis, provide the training plan in TWO parts:
1. A human-readable explanation (your coaching analysis and plan overview).
2. A JSON block wrapped in ```json ... ``` containing the structured plan in this format:
```json
{{
  "start_date": "YYYY-MM-DD",
  "end_date": "YYYY-MM-DD",
  "weeks": [
    {{
      "week_number": 1,
      "workouts": [
        {{
          "day": "Monday",
          "date": "YYYY-MM-DD",
          "type": "easy_run|tempo|intervals|long_run|rest|cross_training|recovery",
          "description": "Easy recovery run, Zone 2",
          "distance_km": 6.0,
          "duration_min": 36,
          "pace_min_km": 6.0,
          "hr_zone": "Zone 2"
        }}
      ]
    }}
  ]
}}
```
Include ALL days (including rest days with type "rest").
Derive paces and heart rate zones from their ACTUAL data, not generic tables."""

        chat = self.client.chats.create(model=self.model_id, config={"tools": self.tools})

        try:
            response = chat.send_message(system_prompt)

            # Handle tool calls in a loop
            response, final_text = self._handle_tool_loop(chat, response)
            return chat, final_text

        except Exception as exc:  # pylint: disable=broad-exception-caught
            return None, f"Error generating plan: {str(exc)}"

    def adapt_plan(self, user_request: str) -> Tuple[Optional[object], str]:
        """Adapt the existing training plan based on user request.
        
        Returns (chat_session, plan_text).
        """
        current_date = datetime.date.today().strftime("%Y-%m-%d")

        system_prompt = f"""You are an expert running coach. Today is {current_date}.

Your Mission:
- The athlete already has an active training plan. 
- Use the get_current_plan tool to see their current plan.
- Use get_recent_activities to see what they have actually done recently.
- They are asking to change or adapt their plan: "{user_request}"
- Analyze their progress and provide an updated, adapted plan.

IMPORTANT: After your analysis, provide the updated training plan in TWO parts:
1. A human-readable explanation (what you changed and why).
2. A JSON block wrapped in ```json ... ``` containing the NEW structured plan (including both past completed workouts as they were, and the new future workouts) in this exact format:
```json
{{
  "start_date": "YYYY-MM-DD",
  "end_date": "YYYY-MM-DD",
  "weeks": [
    {{
      "week_number": 1,
      "workouts": [
        {{
          "day": "Monday",
          "date": "YYYY-MM-DD",
          "type": "easy_run|tempo|intervals|long_run|rest|cross_training|recovery",
          "description": "Easy recovery run, Zone 2",
          "distance_km": 6.0,
          "duration_min": 36,
          "pace_min_km": 6.0,
          "hr_zone": "Zone 2"
        }}
      ]
    }}
  ]
}}
```
Ensure you keep the workouts from the past unmodified (unless the user explicitly asks to change historical data) and only shift/adapt the future workouts. Include ALL days."""

        chat = self.client.chats.create(model=self.model_id, config={"tools": self.tools})

        try:
            response = chat.send_message(system_prompt)
            response, final_text = self._handle_tool_loop(chat, response)
            return chat, final_text

        except Exception as exc:  # pylint: disable=broad-exception-caught
            return None, f"Error adapting plan: {str(exc)}"

    def chat(self, chat_session: object, message: str) -> str:
        """Send a follow-up message in an existing chat session.

        The coach can use tools to answer data-driven questions.
        """
        try:
            response = chat_session.send_message(message)
            _, final_text = self._handle_tool_loop(chat_session, response)
            return final_text
        except Exception as exc:  # pylint: disable=broad-exception-caught
            return f"Error: {str(exc)}"

    def analyze_adherence(self) -> str:
        """Autonomously analyze plan adherence for the current week."""
        chat = self.client.chats.create(model=self.model_id, config={"tools": self.tools})
        prompt = """You are an expert running coach reviewing plan adherence.
Use tools to: 1. get_current_plan, 2. compare_plan_vs_actual(week_offset=0), 3. get_recent_activities(days=7).
Provide concise feedback, zone check, and next steps."""

        try:
            response = chat.send_message(prompt)
            _, final_text = self._handle_tool_loop(chat, response)
            return final_text
        except Exception as exc:  # pylint: disable=broad-exception-caught
            return f"Error analyzing adherence: {str(exc)}"

    def _handle_tool_loop(
        self, chat_session, response, max_iterations: int = 10
    ) -> Tuple[object, str]:
        """Handle Gemini function-calling loop until text response."""
        iteration = 0
        while iteration < max_iterations:
            if not response.candidates:
                return response, "Error: No response candidates returned by the model."
                
            candidate = response.candidates[0]
            if not candidate.content or not candidate.content.parts:
                return response, "Error: Model returned an empty response or was blocked."
                
            parts = candidate.content.parts

            function_calls = [p for p in parts if p.function_call]
            if not function_calls:
                # No more tool calls — extract text
                text_parts = [p.text for p in parts if p.text]
                return response, "\n".join(text_parts)

            # Execute each function call and send results back
            tool_responses = []
            for part in function_calls:
                result = self._dispatch_tool_call(part.function_call)
                tool_responses.append(
                    types.Part(
                        function_response=types.FunctionResponse(
                            name=part.function_call.name,
                            response={"result": result},
                        )
                    )
                )

            response = chat_session.send_message(
                types.Content(parts=tool_responses),
            )
            iteration += 1

        # Fallback if max iterations reached
        if response.candidates and response.candidates[0].content and response.candidates[0].content.parts:
            text_parts = [p.text for p in response.candidates[0].content.parts if p.text]
            return response, "\n".join(text_parts) if text_parts else "Plan generation timed out."
        return response, "Plan generation timed out (empty response)."

    @staticmethod
    def parse_plan_json(plan_text: str) -> Optional[Dict[str, Any]]:
        """Extract and parse the JSON plan block from LLM response text."""
        # Look for ```json ... ``` block
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
        workouts = []
        for week in plan_json.get("weeks", []):
            for w in week.get("workouts", []):
                workouts.append(
                    {
                        "plan_id": plan_id,
                        "workout_date": w.get("date", ""),
                        "workout_type": w.get("type", "rest"),
                        "description": w.get("description", ""),
                        "target_distance_km": w.get("distance_km"),
                        "target_duration_min": w.get("duration_min"),
                        "target_pace_min_km": w.get("pace_min_km"),
                        "target_hr_zone": w.get("hr_zone", ""),
                    }
                )
        return workouts
