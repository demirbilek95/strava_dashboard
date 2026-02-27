"""Agentic AI Coach using Gemini function-calling for Strava training plans."""

import os
import json
import datetime
import re
from typing import Optional, Dict, Any, Tuple

import pandas as pd
import google.generativeai as genai
from dotenv import load_dotenv

from strava.db.db_manager import DatabaseManager


# ── Tool function declarations for Gemini ──────────────────────────────

COACH_TOOLS = [
    genai.protos.Tool(
        function_declarations=[
            genai.protos.FunctionDeclaration(
                name="get_recent_activities",
                description=(
                    "Query the athlete's recent activities from the database. "
                    "Returns a summary of each activity including date, type, "
                    "distance, pace, heart rate, and elevation."
                ),
                parameters=genai.protos.Schema(
                    type=genai.protos.Type.OBJECT,
                    properties={
                        "days": genai.protos.Schema(
                            type=genai.protos.Type.INTEGER,
                            description="Number of days to look back (default 28)",
                        ),
                    },
                ),
            ),
            genai.protos.FunctionDeclaration(
                name="get_weekly_summary",
                description=(
                    "Get weekly mileage, total time, and average pace aggregates "
                    "for the last N weeks."
                ),
                parameters=genai.protos.Schema(
                    type=genai.protos.Type.OBJECT,
                    properties={
                        "weeks": genai.protos.Schema(
                            type=genai.protos.Type.INTEGER,
                            description="Number of weeks to summarize (default 4)",
                        ),
                    },
                ),
            ),
            genai.protos.FunctionDeclaration(
                name="get_race_history",
                description=(
                    "Fetch the athlete's race results (workout_type=1 or 'race' in name). "
                    "Returns up to the last 10 races."
                ),
                parameters=genai.protos.Schema(
                    type=genai.protos.Type.OBJECT,
                    properties={},
                ),
            ),
            genai.protos.FunctionDeclaration(
                name="get_current_plan",
                description="Retrieve the currently active training plan from the database.",
                parameters=genai.protos.Schema(
                    type=genai.protos.Type.OBJECT,
                    properties={},
                ),
            ),
            genai.protos.FunctionDeclaration(
                name="compare_plan_vs_actual",
                description=(
                    "Compare planned workouts against actual activities for a "
                    "given week offset (0 = current week, 1 = last week, etc.)."
                ),
                parameters=genai.protos.Schema(
                    type=genai.protos.Type.OBJECT,
                    properties={
                        "week_offset": genai.protos.Schema(
                            type=genai.protos.Type.INTEGER,
                            description="0 for current week, 1 for last week, etc.",
                        ),
                    },
                ),
            ),
        ]
    )
]


class AICoach:  # pylint: disable=too-few-public-methods
    """Agentic AI running coach with database tool access."""

    def __init__(self, database: Optional[DatabaseManager] = None):
        load_dotenv()
        api_key = os.getenv("GOOGLE_API_KEY")
        if not api_key:
            raise ValueError("GOOGLE_API_KEY not found in environment variables.")

        genai.configure(api_key=api_key)
        self.model = genai.GenerativeModel("gemini-flash-latest")
        self.db = database or DatabaseManager()
        self._activities_df = None

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
            lines.append(f"- {date_str}: {workout_type} '{name}' | {dist} | {pace} | {hr}")
        return "\n".join(lines)

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
- Create a personalized, realistic training plan.
- Be honest about goal feasibility.

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

        chat = self.model.start_chat(history=[])

        try:
            response = chat.send_message(
                system_prompt,
                tools=COACH_TOOLS,
            )

            # Handle tool calls in a loop
            response, final_text = self._handle_tool_loop(chat, response)
            return chat, final_text

        except Exception as exc:  # pylint: disable=broad-exception-caught
            return None, f"Error generating plan: {str(exc)}"

    def chat(self, chat_session: object, message: str) -> str:
        """Send a follow-up message in an existing chat session.

        The coach can use tools to answer data-driven questions.
        """
        try:
            response = chat_session.send_message(
                message,
                tools=COACH_TOOLS,
            )
            _, final_text = self._handle_tool_loop(chat_session, response)
            return final_text
        except Exception as exc:  # pylint: disable=broad-exception-caught
            return f"Error: {str(exc)}"

    def analyze_adherence(self) -> str:
        """Autonomously analyze plan adherence for the current week."""
        chat = self.model.start_chat(history=[])

        prompt = """You are an expert running coach reviewing plan adherence.

Use the available tools to:
1. Call get_current_plan to see the active training plan
2. Call compare_plan_vs_actual with week_offset=0 for this week
3. Call get_recent_activities with days=7 for the latest activities

Then provide:
- A summary of adherence (what was done vs planned)
- Specific feedback on each completed workout (pace, distance, HR vs targets)
- Suggestions for remaining workouts this week
- Any plan adjustments if needed

Be supportive but honest. Use actual numbers from the data."""

        try:
            response = chat.send_message(prompt, tools=COACH_TOOLS)
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
            # Check if the response has function calls
            candidate = response.candidates[0]
            parts = candidate.content.parts

            function_calls = [p for p in parts if p.function_call.name]
            if not function_calls:
                # No more tool calls — extract text
                text_parts = [p.text for p in parts if p.text]
                return response, "\n".join(text_parts)

            # Execute each function call and send results back
            tool_responses = []
            for part in function_calls:
                result = self._dispatch_tool_call(part.function_call)
                tool_responses.append(
                    genai.protos.Part(
                        function_response=genai.protos.FunctionResponse(
                            name=part.function_call.name,
                            response={"result": result},
                        )
                    )
                )

            response = chat_session.send_message(
                genai.protos.Content(parts=tool_responses),
                tools=COACH_TOOLS,
            )
            iteration += 1

        # Fallback if max iterations reached
        text_parts = [p.text for p in response.candidates[0].content.parts if p.text]
        return response, "\n".join(text_parts) if text_parts else "Plan generation timed out."

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
