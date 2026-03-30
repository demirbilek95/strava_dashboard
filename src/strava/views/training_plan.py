"""AI Coach Training Plan view — feedback, sync, and main page entry point."""

import datetime
import re
from typing import Optional

import pandas as pd
import streamlit as st

from strava.constants import COMPLETION_MIN_DISTANCE_RATIO, WORKOUT_TYPE_COMPATIBLE
from strava.db.db_manager import DatabaseManager
from strava.views._training_plan_calendar import _tab_calendar
from strava.views._training_plan_generate import _get_coach, _tab_generate_plan

# Strava workout_type codes
_WT_RACE = 1
_WT_WORKOUT = 3
_LONG_RUN_THRESHOLD_M = 15_000


# -- Athlete snapshot --


def _render_athlete_snapshot(database: DatabaseManager) -> None:
    """Auto-load and render the coach's brief once per session."""
    if "coach_snapshot" not in st.session_state:
        with st.spinner("Your coach is reviewing your data\u2026"):
            try:
                st.session_state["coach_snapshot"] = _get_coach(database).athlete_snapshot()
            except Exception:  # pylint: disable=broad-exception-caught
                st.session_state["coach_snapshot"] = ""

    snapshot = st.session_state.get("coach_snapshot", "")
    if not snapshot:
        return

    with st.expander("\U0001f4cb Coach\u2019s Brief \u2014 click to expand", expanded=True):
        st.markdown(snapshot)

    if st.button("\U0001f504 Refresh Brief", key="refresh_snapshot_btn"):
        del st.session_state["coach_snapshot"]
        st.rerun()

    st.divider()


# -- Tab 3: Feedback & Chat --


def _render_plan_summary(plan: dict) -> None:
    """Render the active plan summary expander."""
    with st.expander("\U0001f4cb Active Training Plan \u2014 click to view", expanded=False):
        st.markdown(f"**Goal:** {plan['goal']}")
        st.markdown(
            f"**Period:** {plan['start_date']} \u2192 "
            f"{plan.get('end_date', 'ongoing')} "
            f"| **{len(plan['workouts'])} workouts total**"
        )
        today_str = datetime.date.today().isoformat()
        upcoming = [
            w
            for w in plan["workouts"]
            if w["workout_date"] >= today_str and w["workout_type"] != "rest"
        ][:5]
        if upcoming:
            st.markdown("**Next workouts:**")
            for w in upcoming:
                dist = f" \u00b7 {w['target_distance_km']}km" if w.get("target_distance_km") else ""
                st.markdown(
                    f"- `{w['workout_date']}` "
                    f"{w['workout_type'].replace('_', ' ').title()}"
                    f"{dist} \u2014 {w.get('description', '')}"
                )
        st.caption(
            "To modify your plan, go to **Create / Adapt Plan** "
            "\u2192 **\U0001f504 Adapt Current Plan**."
        )


def _render_adherence_section(database: DatabaseManager) -> None:
    """Render the plan adherence analysis section."""
    st.markdown("### \U0001f4c8 Plan Adherence Analysis")
    if st.button("\U0001f50d Analyse My Week", type="primary", key="analyze_btn"):
        with st.spinner("\U0001f916 Coach is reviewing your training data..."):
            coach = _get_coach(database)
            analysis = coach.analyze_adherence()
            st.session_state["adherence_analysis"] = analysis
    if "adherence_analysis" in st.session_state:
        st.markdown(st.session_state["adherence_analysis"])


def _build_activity_feedback_prompt(
    activity_id: int, activity_label: str, dataframe: pd.DataFrame
) -> str:
    """Build a context-aware coaching feedback prompt based on the run type."""
    activity_row = None
    if not dataframe.empty and "activity_id" in dataframe.columns:
        matches = dataframe[dataframe["activity_id"] == activity_id]
        if not matches.empty:
            activity_row = matches.iloc[0]

    workout_type = int(activity_row.get("workout_type") or 0) if activity_row is not None else 0
    distance_m = float(activity_row.get("distance") or 0) if activity_row is not None else 0

    is_race = workout_type == _WT_RACE
    is_interval = workout_type == _WT_WORKOUT
    is_long_run = not is_race and not is_interval and distance_m >= _LONG_RUN_THRESHOLD_M

    base = (
        f"Give me detailed coaching feedback on this activity: {activity_label}.\n"
        "CRITICAL: Every number you cite must come directly from a tool result "
        "— no hallucination.\n"
        "First call is_indoor_activity to check if this was indoors "
        "(indoor data may be unreliable).\n\n"
    )

    if is_race:
        return base + (
            "This was a RACE.\n"
            "Call get_km_splits to analyse the pacing strategy (positive or negative split?).\n"
            "Call get_best_efforts to compare this result to all-time PRs at this distance.\n"
            "Call get_activity_details for HR data and aerobic decoupling.\n"
            "Assess: Was the pacing smart? How does this compare to their PR? "
            "What does this performance tell us about current fitness and readiness?"
        )

    if is_interval:
        return base + (
            "This was a STRUCTURED WORKOUT (intervals or tempo).\n"
            "Call get_activity_laps to analyse each lap — did they hit target paces? "
            "Did effort drop off in later reps?\n"
            "Call get_km_splits for the km-level breakdown.\n"
            "Call get_activity_details for HR zone distribution.\n"
            "Assess: Were the work intervals executed at Zone 4/5? "
            "Were rest periods adequate? Name specific laps that were strong or poor."
        )

    if is_long_run:
        return base + (
            "This was a LONG RUN.\n"
            "Call get_activity_details for aerobic decoupling (cardiac drift).\n"
            "Call get_km_splits to see if pace or HR drifted in the second half.\n"
            "Assess: Did they stay in Zone 2 throughout? "
            "Was cardiac drift > 5% (concerning)? Did they start too fast? "
            "How sustainable was the effort over the full distance?"
        )

    return base + (
        "This was likely an EASY or RECOVERY RUN.\n"
        "Call get_activity_details to check HR zone distribution — was this truly Zone 2?\n"
        "Call get_km_splits to check pace consistency.\n"
        "Assess: Did they stay disciplined in Zone 2, or did HR creep into Zone 3/4? "
        "Was the pace appropriate for the HR? Any concerning drift towards the end?"
    )


def _render_activity_selector(dataframe: pd.DataFrame) -> None:
    """Render activity selector for detailed per-activity coaching feedback."""
    st.markdown("### \U0001f50d Activity Feedback")
    st.caption("Get detailed, data-driven coaching feedback on a recent activity.")
    if "activity_date" not in dataframe.columns:
        return
    recent = dataframe.sort_values(by="activity_date", ascending=False).head(20)
    options = []
    for _, row in recent.iterrows():
        act_name = row.get("activity_name", "Activity")
        act_id = row["activity_id"]
        if pd.notnull(row["activity_date"]):
            label = f"{row['activity_date'].strftime('%Y-%m-%d')} - {act_name} (ID: {act_id})"
        else:
            label = f"Unknown date - {act_name} (ID: {act_id})"
        options.append(label)
    selected_activity = st.selectbox("Choose Activity:", [""] + options)
    if selected_activity:
        match = re.search(r"\(ID: (\d+)\)$", selected_activity)
        if match and st.button("Get Coaching Feedback", key="detailed_feedback_btn"):
            activity_id = int(match.group(1))
            st.session_state["pending_feedback_prompt"] = _build_activity_feedback_prompt(
                activity_id, selected_activity, dataframe
            )


def _render_coaching_chat(database: DatabaseManager) -> None:
    """Render the coaching chat interface."""
    st.markdown("### \U0001f4ac Ask Your Coach")
    st.caption(
        "Chat about any aspect of your training. "
        "To adjust your plan, go to "
        "**Create / Adapt Plan \u2192 \U0001f504 Adapt Current Plan**."
    )
    st.session_state.setdefault("feedback_chat", None)
    st.session_state.setdefault("feedback_history", [])

    chat_container = st.container()
    with chat_container:
        for msg in st.session_state["feedback_history"]:
            with st.chat_message(msg["role"]):
                st.markdown(msg["content"])

    prompt = st.chat_input("Ask your coach anything...", key="feedback_chat_input")
    if st.session_state.get("pending_feedback_prompt"):
        prompt = st.session_state.pop("pending_feedback_prompt")

    if prompt:
        st.session_state["feedback_history"].append({"role": "user", "content": prompt})
        with chat_container:
            with st.chat_message("user"):
                st.markdown(prompt)
            with st.chat_message("assistant"):
                with st.spinner("Thinking..."):
                    coach = _get_coach(database)
                    if not st.session_state["feedback_chat"]:
                        st.session_state["feedback_chat"] = coach._make_chat()
                    reply = coach.chat(st.session_state["feedback_chat"], prompt)
                    st.markdown(reply)
                    st.session_state["feedback_history"].append(
                        {"role": "assistant", "content": reply}
                    )
                    st.rerun()


def _tab_feedback(database: DatabaseManager, dataframe: pd.DataFrame) -> None:
    """Feedback tab with adherence analysis and coaching chat."""
    plan = database.get_active_plan()
    if plan:
        _render_plan_summary(plan)
        st.divider()
        _render_adherence_section(database)
        st.divider()
    else:
        st.info(
            "No active training plan \u2014 plan-specific analysis is unavailable. "
            "Generate one in the **Create / Adapt Plan** tab."
        )
    _render_activity_selector(dataframe)
    st.divider()
    _render_coaching_chat(database)


# -- Workout sync --


def _sync_planned_workouts_with_activities(database: DatabaseManager, df: pd.DataFrame) -> None:
    """Auto-match activities to incomplete planned workouts.

    Matching rules (all must pass):
    1. Same date as the planned workout.
    2. Activity type is compatible with the planned workout type.
    3. Actual distance >= planned distance * COMPLETION_MIN_DISTANCE_RATIO.
    """
    plan = database.get_active_plan()
    if not plan or df.empty:
        return

    today_str = datetime.date.today().isoformat()
    incomplete = [
        w
        for w in plan.get("workouts", [])
        if (
            w["workout_date"] <= today_str
            and w["workout_type"] != "rest"
            and not w.get("completed")
        )
    ]

    for w in incomplete:
        if "activity_date" not in df.columns:
            break

        day_activities = df[df["activity_date"].dt.strftime("%Y-%m-%d") == w["workout_date"]].copy()

        if day_activities.empty:
            continue

        planned_type = w["workout_type"]
        compatible_types = WORKOUT_TYPE_COMPATIBLE.get(planned_type, set())
        type_match = day_activities[day_activities["activity_type"].isin(compatible_types)]

        if type_match.empty:
            continue

        planned_km = w.get("target_distance_km")
        if planned_km and planned_km > 0:
            min_dist_km = planned_km * COMPLETION_MIN_DISTANCE_RATIO
            type_match = type_match[type_match["distance"] >= min_dist_km]

        if type_match.empty:
            continue

        best = type_match.sort_values(by="distance", ascending=False).iloc[0]
        database.update_workout_completion(
            workout_id=w["workout_id"],
            activity_id=int(best["activity_id"]),
            feedback="Auto-matched: type-compatible activity on same date",
        )


# -- Main page --


def page_ai_training_plan(dataframe: pd.DataFrame, database: Optional[DatabaseManager] = None):
    """AI Coach Training Plan page with 3 tabs."""
    st.header("\U0001f916 AI Coach")
    st.markdown(
        "Your personal AI running coach \u2014 powered by Gemini. "
        "Generate a plan, track it on the calendar, and get data-driven feedback."
    )

    if database is None:
        database = DatabaseManager()

    database.create_tables()
    _sync_planned_workouts_with_activities(database, dataframe)
    _render_athlete_snapshot(database)

    tab_names = [
        "\U0001f4dd Create / Adapt Plan",
        "\U0001f4c5 Calendar",
        "\U0001f4ac Feedback & Chat",
    ]

    st.session_state.setdefault("main_nav_radio", tab_names[0])

    if "nav_target" in st.session_state:
        target = st.session_state.pop("nav_target")
        if target in tab_names:
            st.session_state["main_nav_radio"] = target

    st.markdown(
        """
        <style>
        div[data-testid="stMainBlockContainer"] div[role='radiogroup'] {
            flex-direction: row;
            gap: 20px;
            padding: 10px 0 20px 0;
            border-bottom: 2px solid rgba(255,255,255,0.1);
            margin-bottom: 20px;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    nav_selection = st.radio(
        "Navigation",
        tab_names,
        key="main_nav_radio",
        label_visibility="collapsed",
    )

    if nav_selection == tab_names[0]:
        _tab_generate_plan(database, dataframe)
    elif nav_selection == tab_names[1]:
        _tab_calendar(database, dataframe)
    else:
        _tab_feedback(database, dataframe)
