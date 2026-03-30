"""Plan generation and adaptation tab for the AI Coach Training Plan."""

import datetime
import json
import re
from typing import Optional

import pandas as pd
import streamlit as st

from strava.db.db_manager import DatabaseManager
from strava.utils.ai_coach import AICoach
from strava.views._training_plan_calendar import _render_month_nav, _render_calendar


def _set_draft_plan_state(plan_text: str, chat, goal: str) -> None:
    """Persist a freshly generated or adapted plan into Streamlit session state."""
    st.session_state["draft_plan_text"] = plan_text
    st.session_state["draft_plan_json"] = AICoach.parse_plan_json(plan_text)
    st.session_state["gemini_chat"] = chat
    st.session_state["user_goal"] = goal
    st.session_state["chat_history"] = [{"role": "assistant", "content": plan_text}]


def _get_coach(database: DatabaseManager) -> AICoach:
    """Return a cached AICoach, recreating it only when HR zones change.

    Caching the instance across Streamlit reruns keeps the underlying
    genai.Client alive so stored chat sessions remain usable for follow-up
    messages without triggering 'client has been closed' errors.
    """
    zones = [
        st.session_state.get("global_z1", 145),
        st.session_state.get("global_z2", 164),
        st.session_state.get("global_z3", 174),
        st.session_state.get("global_z4", 188),
    ]
    cached: Optional[AICoach] = st.session_state.get("_coach_instance")
    if cached is not None and cached.hr_zones == zones:
        return cached
    coach = AICoach(database, hr_zones=zones)
    st.session_state["_coach_instance"] = coach
    return coach


def _show_active_plan(database: DatabaseManager, active_plan: dict) -> None:
    """Show existing active plan with option to archive and create new."""
    st.success(f"\u2705 Active plan: **{active_plan['goal']}**")
    st.info(
        f"\U0001f4c5 {active_plan['start_date']} \u2192 "
        f"{active_plan.get('end_date', 'ongoing')} | "
        f"{len(active_plan['workouts'])} workouts"
    )
    if active_plan.get("raw_llm_response"):
        with st.expander("\U0001f4d6 View full plan details"):
            st.markdown(active_plan["raw_llm_response"])

    col1, col2 = st.columns(2)
    with col1:
        if st.button("\U0001f4dd Create New Plan (archives current)", key="new_plan_btn"):
            database.archive_plan(active_plan["plan_id"])
            st.rerun()
    with col2:
        if st.button("\U0001f504 Adapt Current Plan", key="adapt_plan_btn"):
            st.session_state["is_adapting"] = True
            st.rerun()


def _show_adapt_input(database: DatabaseManager, active_plan: dict) -> None:
    """Show input form for adapting an existing plan."""
    st.markdown("### \U0001f504 Adapt Your Plan")
    st.info(
        "Tell the AI Coach what changed \u2014 e.g. 'I missed my long run Sunday, "
        "move it to Tuesday' or 'add an extra rest day this week'."
    )
    adapt_request = st.text_area("What would you like to change?", key="adapt_input")

    col1, col2 = st.columns(2)
    with col1:
        if st.button("\U0001f680 Adapt Plan", type="primary"):
            if not adapt_request:
                st.error("Please enter your request first.")
                return
            with st.spinner("\U0001f916 AI Coach is analysing and adapting your plan..."):
                coach = _get_coach(database)
                chat, plan_text = coach.adapt_plan(adapt_request)

            if chat and plan_text:
                _set_draft_plan_state(plan_text, chat, active_plan["goal"])
                st.session_state["is_adapting"] = False
                st.session_state["adapting_plan_id"] = active_plan["plan_id"]
                st.session_state["nav_target"] = "\U0001f4dd Create / Adapt Plan"
                st.rerun()
            else:
                st.error(plan_text)
    with col2:
        if st.button("Cancel"):
            st.session_state["is_adapting"] = False
            st.rerun()


def _show_goal_input(database: DatabaseManager) -> None:
    """Show goal input form and handle plan generation."""
    user_goal = st.text_area(
        "What is your running goal?",
        height=100,
        placeholder=(
            "e.g. I want to run a sub-4 hour marathon in 3 months. " "I train 4 times a week."
        ),
        key="goal_input",
    )

    if st.button("\U0001f680 Generate Training Plan", type="primary"):
        if not user_goal:
            st.error("Please enter a goal first.")
            return
        with st.spinner("\U0001f916 AI Coach is analysing your data and building a plan..."):
            coach = _get_coach(database)
            chat, plan_text = coach.generate_plan(user_goal)

        if chat and plan_text:
            _set_draft_plan_state(plan_text, chat, user_goal)
            st.rerun()
        else:
            st.error(plan_text)


def _handle_accept(database: DatabaseManager) -> None:
    """Handle the Accept Plan button click."""
    plan_json = st.session_state.get("draft_plan_json")
    if not plan_json:
        st.error("Could not parse the plan structure. Ask the coach to regenerate the JSON block.")
        return

    with st.spinner("Saving plan to database..."):
        if st.session_state.get("adapting_plan_id"):
            database.archive_plan(st.session_state["adapting_plan_id"])
            st.session_state["adapting_plan_id"] = None

        plan_id = database.insert_training_plan(
            {
                "goal": st.session_state["user_goal"],
                "start_date": plan_json.get("start_date", datetime.date.today().isoformat()),
                "end_date": plan_json.get("end_date"),
                "status": "active",
                "raw_llm_response": st.session_state["draft_plan_text"],
            }
        )
        workout_records = AICoach.plan_json_to_workouts(plan_id, plan_json)
        database.insert_planned_workouts(workout_records)

    st.session_state["draft_plan_text"] = None
    st.session_state["draft_plan_json"] = None
    st.session_state["gemini_chat"] = None
    st.session_state["chat_history"] = []
    st.session_state["plan_accepted"] = False
    st.session_state.pop("coach_snapshot", None)
    st.success("\u2705 Plan saved! Check the **Calendar** tab.")
    st.session_state["nav_target"] = "\U0001f4c5 Calendar"
    st.rerun()


def _render_draft_plan_preview(plan_json: Optional[dict], dataframe: pd.DataFrame) -> None:
    """Render calendar preview for a draft plan, with month navigation."""
    if not (plan_json and "weeks" in plan_json):
        return
    workouts = AICoach.plan_json_to_workouts(0, plan_json)
    if not workouts:
        return

    today = datetime.date.today()
    default_year, default_month = today.year, today.month
    valid_dates = [w["workout_date"] for w in workouts if w.get("workout_date")]
    if valid_dates:
        try:
            dt = datetime.date.fromisoformat(min(valid_dates))
            default_year, default_month = dt.year, dt.month
        except ValueError:
            pass

    _render_month_nav("draft_cal", default_month, default_year)
    year = st.session_state.get("draft_cal_year", default_year)
    month = st.session_state.get("draft_cal_month", default_month)
    _render_calendar(year, month, workouts, dataframe)
    st.divider()


def _render_draft_chat(database: DatabaseManager) -> None:
    """Render draft plan chat history and handle follow-up inputs."""
    chat_container = st.container()
    with chat_container:
        for msg in st.session_state.get("chat_history", []):
            with st.chat_message(msg["role"]):
                content = re.sub(r"```json\s*.*?\s*```", "", msg["content"], flags=re.DOTALL)
                if content.strip():
                    st.markdown(content.strip())

    if prompt := st.chat_input("Ask a follow-up or request changes..."):
        st.session_state["chat_history"].append({"role": "user", "content": prompt})
        with chat_container:
            with st.chat_message("user"):
                st.markdown(prompt)
            with st.chat_message("assistant"):
                with st.spinner("Thinking..."):
                    coach = _get_coach(database)
                    chat = st.session_state.get("gemini_chat")
                    if chat:
                        reply = coach.chat(chat, prompt)
                        st.markdown(reply)
                        st.session_state["chat_history"].append(
                            {"role": "assistant", "content": reply}
                        )
                        new_json = AICoach.parse_plan_json(reply)
                        if new_json:
                            st.session_state["draft_plan_text"] = reply
                            st.session_state["draft_plan_json"] = new_json
                            for key in (
                                "draft_cal_month",
                                "draft_cal_year",
                                "cal_month",
                                "cal_year",
                            ):
                                st.session_state.pop(key, None)
                        st.rerun()
                    else:
                        st.error("Chat session lost. Please regenerate.")


def _show_draft_review(database: DatabaseManager, dataframe: pd.DataFrame) -> None:
    """Show draft plan preview with chat and accept/regenerate buttons."""
    st.markdown("### \U0001f4cb Draft Training Plan")
    st.caption(
        "Review the plan below. Ask follow-up questions or request changes before accepting."
    )

    _render_draft_plan_preview(st.session_state.get("draft_plan_json"), dataframe)
    _render_draft_chat(database)

    if st.session_state.get("draft_plan_json"):
        with st.expander("\U0001f50d View Raw Plan JSON (for debugging)", expanded=False):
            st.code(
                json.dumps(st.session_state.get("draft_plan_json"), indent=2),
                language="json",
            )

    col1, col2 = st.columns(2)
    with col1:
        if st.button("\u2705 Accept Plan", type="primary", key="accept_btn"):
            _handle_accept(database)
    with col2:
        if st.button("\U0001f504 Start Over", key="regenerate_btn"):
            for key in ("draft_plan_text", "draft_plan_json", "gemini_chat"):
                st.session_state[key] = None
            st.session_state["chat_history"] = []
            st.rerun()


def _tab_generate_plan(database: DatabaseManager, dataframe: pd.DataFrame) -> None:
    """Plan generation tab with preview -> accept flow."""
    for key, default in [
        ("draft_plan_text", None),
        ("draft_plan_json", None),
        ("gemini_chat", None),
        ("chat_history", []),
        ("plan_accepted", False),
        ("user_goal", ""),
    ]:
        st.session_state.setdefault(key, default)

    active_plan = database.get_active_plan()

    if active_plan and not st.session_state.get("draft_plan_text"):
        if st.session_state.get("is_adapting"):
            _show_adapt_input(database, active_plan)
        else:
            _show_active_plan(database, active_plan)
        return

    if not st.session_state.get("draft_plan_text"):
        _show_goal_input(database)
        return

    _show_draft_review(database, dataframe)
