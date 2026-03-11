"""AI Coach Training Plan view with Calendar and Feedback tabs."""

import calendar
import datetime
from typing import Optional, Dict, Any

import streamlit as st
import pandas as pd

from strava.utils.ai_coach import AICoach
from strava.db.db_manager import DatabaseManager


# ── Color scheme for workout types ──────────────────────────────────

WORKOUT_COLORS = {
    "easy_run": "#4CAF50",
    "recovery": "#66BB6A",
    "tempo": "#FF9800",
    "intervals": "#F44336",
    "long_run": "#2196F3",
    "rest": "#9E9E9E",
    "cross_training": "#9C27B0",
}

STATUS_COLORS = {
    "completed": "#4CAF50",
    "missed": "#F44336",
    "upcoming": "#2196F3",
    "rest": "#9E9E9E",
}


def _get_workout_color(workout_type: str) -> str:
    return WORKOUT_COLORS.get(workout_type, "#607D8B")


def _get_status(workout: Dict[str, Any]) -> str:
    today = datetime.date.today().isoformat()
    if workout.get("completed"):
        return "completed"
    if workout["workout_type"] == "rest":
        return "rest"
    if workout["workout_date"] < today:
        return "missed"
    return "upcoming"


def _get_coach(database: DatabaseManager) -> AICoach:
    """Helper to initialize AICoach with global HR zones."""
    zones = [
        st.session_state.get("global_z1", 145),
        st.session_state.get("global_z2", 164),
        st.session_state.get("global_z3", 174),
        st.session_state.get("global_z4", 188),
    ]
    return AICoach(database, hr_zones=zones)


# ── Calendar rendering ──────────────────────────────────────────────


def _render_calendar(  # pylint: disable=too-many-locals
    year: int, month: int, workouts: list, activities_df: pd.DataFrame
):
    """Render a monthly calendar with planned workouts and actual activities."""
    cal = calendar.Calendar(firstweekday=0)
    month_days = cal.monthdayscalendar(year, month)
    month_name = calendar.month_name[month]

    # Index workouts by date (handle multiple workouts per day)
    workout_by_date = {}
    for w in workouts:
        date_key = w["workout_date"]
        if date_key not in workout_by_date:
            workout_by_date[date_key] = []
        workout_by_date[date_key].append(w)

    # Index actual activities by date
    activity_by_date = {}
    if not activities_df.empty and "activity_date" in activities_df.columns:
        for _, row in activities_df.iterrows():
            date_key = row["activity_date"].strftime("%Y-%m-%d")
            if date_key not in activity_by_date:
                activity_by_date[date_key] = []
            activity_by_date[date_key].append(row)

    today = datetime.date.today()

    css = """
    <style>
    .cal-grid {
        display: grid; grid-template-columns: repeat(7, 1fr);
        gap: 4px; font-family: 'Inter', sans-serif; font-size: 13px;
    }
    .cal-header {
        text-align: center; font-weight: 700; padding: 8px 4px;
        color: #888; font-size: 12px; text-transform: uppercase;
    }
    .cal-day {
        min-height: 110px; border-radius: 8px; padding: 6px 8px;
        background: rgba(255,255,255,0.04); border: 1px solid rgba(255,255,255,0.08);
        position: relative; display: flex; flex-direction: column; gap: 2px;
    }
    .cal-day.today { border: 2px solid #2196F3; }
    .cal-day.empty { background: transparent; border: none; min-height: 0; }
    .cal-day-num { font-weight: 600; margin-bottom: 4px; color: #ddd; }
    .cal-workout {
        font-size: 11px; padding: 3px 6px; border-radius: 4px;
        margin-bottom: 2px; color: #fff; line-height: 1.3;
    }
    .cal-actual {
        font-size: 10px; padding: 2px 5px; border-radius: 3px;
        background: rgba(255,255,255,0.1); color: #aaa;
        margin-top: 2px; border-left: 2px solid #4CAF50;
    }
    .cal-detail {
        font-size: 10px; color: #bbb; padding: 1px 6px;
        line-height: 1.3; margin-bottom: 2px;
    }
    </style>
    """

    html = css + f'<h3 style="text-align:center;color:#ddd;">{month_name} {year}</h3>'
    html += '<div class="cal-grid">'

    # Headers
    for day_name in ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]:
        html += f'<div class="cal-header">{day_name}</div>'

    # Days
    for week in month_days:
        for day in week:
            if day == 0:
                html += '<div class="cal-day empty"></div>'
                continue

            date_obj = datetime.date(year, month, day)
            date_str = date_obj.isoformat()
            is_today = date_obj == today
            classes = "cal-day" + (" today" if is_today else "")

            html += f'<div class="{classes}">'
            html += f'<div class="cal-day-num">{day}</div>'

            # Planned workouts
            if date_str in workout_by_date:
                for w in workout_by_date[date_str]:
                    color = _get_workout_color(w["workout_type"])
                    status = _get_status(w)
                    opacity = "0.5" if status == "missed" else "1.0"
                    icon = {"completed": "✅", "missed": "❌", "upcoming": "📋", "rest": "😴"}
                    label = w["workout_type"].replace("_", " ").title()

                    # Build prominent stats: distance + pace
                    stats_parts = []
                    dist = w.get("target_distance_km")
                    if dist and str(dist).lower() not in ("n/a", "none", "null", ""):
                        stats_parts.append(f"{dist}km")
                    
                    pace_val = w.get("target_pace_min_km")
                    if pace_val and str(pace_val).lower() not in ("n/a", "none", "null", ""):
                        try:
                            pace_val = float(pace_val)
                            mins = int(pace_val)
                            secs = int((pace_val - mins) * 60)
                            stats_parts.append(f"{mins}:{secs:02d}/km")
                        except ValueError:
                            stats_parts.append(f"{pace_val}/km")
                    
                    stats_str = f" · {' · '.join(stats_parts)}" if stats_parts else ""

                    html += (
                        f'<div class="cal-workout" style="background:{color};opacity:{opacity}">'
                        f"{icon.get(status, '')} {label}{stats_str}</div>"
                    )
                    # Secondary detail line: description and HR zone
                    details = []
                    if w.get("description") and w["workout_type"] != "rest":
                        details.append(w["description"])
                    if w.get("target_hr_zone"):
                        details.append(w["target_hr_zone"])
                    if details:
                        detail_str = " · ".join(details)
                        html += f'<div class="cal-detail">{detail_str}</div>'

            # Actual activity
            if date_str in activity_by_date:
                ACTIVITY_EMOJI = {
                    "Run": "🏃",
                    "Ride": "🚴",
                    "Swim": "🏊",
                    "Walk": "🚶",
                    "Hike": "🧗",
                    "Workout": "💪",
                    "WeightTraining": "💪",
                    "Yoga": "🧘",
                    "Pilates": "🧘",
                    "Crossfit": "💪",
                    "Rowing": "🚣",
                    "Soccer": "⚽",
                    "Tennis": "🎾",
                }
                for act in activity_by_date[date_str][:4]:
                    a_type = act.get("activity_type", "")
                    emoji = ACTIVITY_EMOJI.get(a_type, "📊")
                    name = act.get("activity_name", a_type or "Activity")
                    
                    raw_dist = act.get("distance", 0)
                    # distance column is already in km (converted by SQL)
                    dist = f"{raw_dist:.1f}k" if pd.notnull(raw_dist) and raw_dist >= 0.1 else ""
                    
                    # Pace: only for distance-based activities
                    pace = ""
                    if dist and pd.notnull(act.get("moving_time")) and act["moving_time"] > 0:
                        pace_dec = (act["moving_time"] / 60) / raw_dist
                        mins = int(pace_dec)
                        secs = int((pace_dec - mins) * 60)
                        pace = f"{mins}:{secs:02d}/k"
                    
                    hr_val = act.get("average_heart_rate")
                    hr = f"{int(hr_val)}bpm" if pd.notnull(hr_val) and hr_val else ""
                    
                    stats = " · ".join([d for d in [dist, pace, hr] if d])
                    label = stats if stats else name
                    html += f'<div class="cal-actual" title="{name}">{emoji} {label}</div>'

            html += "</div>"

    html += "</div>"
    st.markdown(html, unsafe_allow_html=True)


# ── Tab 1: Generate Plan ────────────────────────────────────────────


def _show_active_plan(database: DatabaseManager, active_plan: dict):
    """Show existing active plan with option to archive and create new."""
    st.success(f"✅ Active plan: **{active_plan['goal']}**")
    st.info(
        f"📅 {active_plan['start_date']} → {active_plan.get('end_date', 'ongoing')} | "
        f"{len(active_plan['workouts'])} workouts"
    )
    if active_plan.get("raw_llm_response"):
        with st.expander("View full plan"):
            st.markdown(active_plan["raw_llm_response"])
            
    col1, col2 = st.columns(2)
    with col1:
        if st.button("📝 Create New Plan (archives current)", key="new_plan_btn"):
            database.archive_plan(active_plan["plan_id"])
            st.rerun()
    with col2:
        if st.button("🔄 Adapt Plan", key="adapt_plan_btn"):
            st.session_state.is_adapting = True
            st.rerun()

def _show_adapt_input(database: DatabaseManager, active_plan: dict):
    """Show input form for adapting an existing plan."""
    st.markdown("### 🔄 Adapt Your Plan")
    st.info("Tell the AI Coach what changed. For example: 'I missed my long run on Sunday, can we move it to Tuesday?'")
    adapt_request = st.text_area("What would you like to change?", key="adapt_input")
    
    col1, col2 = st.columns(2)
    with col1:
        if st.button("🚀 Adapt Plan", type="primary"):
            if not adapt_request:
                st.error("Please enter your request first.")
                return

            with st.spinner("🤖 AI Coach is analyzing and adapting your plan..."):
                coach = _get_coach(database)
                chat, plan_text = coach.adapt_plan(adapt_request)

                if chat and plan_text:
                    st.session_state.draft_plan_text = plan_text
                    st.session_state.draft_plan_json = AICoach.parse_plan_json(plan_text)
                    st.session_state.gemini_chat = chat
                    st.session_state.user_goal = active_plan["goal"]
                    st.session_state.chat_history = [{"role": "assistant", "content": plan_text}]
                    st.session_state.is_adapting = False
                    st.session_state.adapting_plan_id = active_plan["plan_id"]
                    st.rerun()
                else:
                    st.error(plan_text)
    with col2:
        if st.button("Cancel"):
            st.session_state.is_adapting = False
            st.rerun()


def _show_goal_input(database: DatabaseManager):
    """Show goal input form and handle plan generation."""
    user_goal = st.text_area(
        "What is your running goal?",
        height=100,
        placeholder=(
            "e.g. I want to run a sub-4 hour marathon in 3 months. " + "I train 4 times a week."
        ),
        key="goal_input",
    )

    if st.button("🚀 Generate Training Plan", type="primary"):
        if not user_goal:
            st.error("Please enter a goal first.")
            return

        with st.spinner("🤖 AI Coach is analyzing your data and building a plan..."):
            coach = _get_coach(database)
            chat, plan_text = coach.generate_plan(user_goal)

            if chat and plan_text:
                st.session_state.draft_plan_text = plan_text
                st.session_state.draft_plan_json = AICoach.parse_plan_json(plan_text)
                st.session_state.gemini_chat = chat
                st.session_state.user_goal = user_goal
                st.session_state.chat_history = [{"role": "assistant", "content": plan_text}]
                st.rerun()
            else:
                st.error(plan_text)


def _handle_accept(database: DatabaseManager):
    """Handle the Accept Plan button click."""
    plan_json = st.session_state.draft_plan_json
    if not plan_json:
        st.error(
            "Could not parse the plan structure. " + "Ask the coach to regenerate the JSON block."
        )
        return

    with st.spinner("Saving plan to database..."):
        if st.session_state.get("adapting_plan_id"):
            database.archive_plan(st.session_state.adapting_plan_id)
            st.session_state.adapting_plan_id = None
            
        plan_id = database.insert_training_plan(
            {
                "goal": st.session_state.user_goal,
                "start_date": plan_json.get("start_date", datetime.date.today().isoformat()),
                "end_date": plan_json.get("end_date"),
                "status": "active",
                "raw_llm_response": st.session_state.draft_plan_text,
            }
        )

        workout_records = AICoach.plan_json_to_workouts(plan_id, plan_json)
        database.insert_planned_workouts(workout_records)

    st.session_state.draft_plan_text = None
    st.session_state.draft_plan_json = None
    st.session_state.gemini_chat = None
    st.session_state.chat_history = []
    st.session_state.plan_accepted = False
    st.success("✅ Plan saved! Check the Calendar tab.")
    st.session_state.main_nav_radio = "📅 Calendar"
    st.rerun()


def _show_draft_review(database: DatabaseManager, dataframe: pd.DataFrame):
    """Show draft plan preview with chat and accept/regenerate buttons."""
    st.markdown("### 📋 Draft Training Plan")
    st.caption("Review the plan below. You can ask follow-up questions or request changes.")

    # Show Calendar of the current draft
    plan_json = st.session_state.draft_plan_json
    if plan_json and "weeks" in plan_json:
        workouts = AICoach.plan_json_to_workouts(0, plan_json)
        
        today = datetime.date.today()
        default_year, default_month = today.year, today.month
        if workouts:
            valid_dates = [w["workout_date"] for w in workouts if w.get("workout_date")]
            if valid_dates:
                first_date = min(valid_dates)
                try:
                    dt = datetime.date.fromisoformat(first_date)
                    default_year, default_month = dt.year, dt.month
                except ValueError:
                    pass
            
        col1, _, col3 = st.columns([1, 2, 1])
        with col1:
            if st.button("◀ Previous", key="draft_cal_prev"):
                if "draft_cal_month" not in st.session_state:
                    st.session_state.draft_cal_month = default_month
                    st.session_state.draft_cal_year = default_year
                st.session_state.draft_cal_month -= 1
                if st.session_state.draft_cal_month < 1:
                    st.session_state.draft_cal_month = 12
                    st.session_state.draft_cal_year -= 1
                st.rerun()
        with col3:
            if st.button("Next ▶", key="draft_cal_next"):
                if "draft_cal_month" not in st.session_state:
                    st.session_state.draft_cal_month = default_month
                    st.session_state.draft_cal_year = default_year
                st.session_state.draft_cal_month += 1
                if st.session_state.draft_cal_month > 12:
                    st.session_state.draft_cal_month = 1
                    st.session_state.draft_cal_year += 1
                st.rerun()

        year = st.session_state.get("draft_cal_year", default_year)
        month = st.session_state.get("draft_cal_month", default_month)
        
        _render_calendar(year, month, workouts, dataframe)
        st.divider()

    # Display chat history
    chat_container = st.container()
    import re
    with chat_container:
        for msg in st.session_state.chat_history:
            with st.chat_message(msg["role"]):
                # Hide the JSON block from the output text
                content = re.sub(r'```json\s*.*?\s*```', '', msg["content"], flags=re.DOTALL)
                if content.strip():
                    st.markdown(content.strip())

    # Chat input for follow-ups
    if prompt := st.chat_input("Ask a follow-up or request changes..."):
        st.session_state.chat_history.append({"role": "user", "content": prompt})
        with chat_container:
            with st.chat_message("user"):
                st.markdown(prompt)

            with st.chat_message("assistant"):
                with st.spinner("Thinking..."):
                    coach = _get_coach(database)
                    chat = st.session_state.gemini_chat
                    if chat:
                        reply = coach.chat(chat, prompt)
                        st.markdown(reply)
                        st.session_state.chat_history.append({"role": "assistant", "content": reply})
                        # Update draft if new JSON is in the reply
                        new_json = AICoach.parse_plan_json(reply)
                        if new_json:
                            st.session_state.draft_plan_text = reply
                            st.session_state.draft_plan_json = new_json
                            # Reset the draft calendar view to show the new plan's start month
                            if "draft_cal_month" in st.session_state:
                                del st.session_state.draft_cal_month
                            if "draft_cal_year" in st.session_state:
                                del st.session_state.draft_cal_year
                            # Also reset the main Calendar tab view
                            if "cal_month" in st.session_state:
                                del st.session_state.cal_month
                            if "cal_year" in st.session_state:
                                del st.session_state.cal_year
                        st.rerun()
                    else:
                        st.error("Chat session lost. Please regenerate.")

    # JSON debug expander
    import json as _json
    if st.session_state.get("draft_plan_json"):
        with st.expander("🔍 View Raw Plan JSON (for debugging)", expanded=False):
            st.code(
                _json.dumps(st.session_state.draft_plan_json, indent=2),
                language="json",
            )

    # Accept / Regenerate buttons
    col1, col2 = st.columns(2)
    with col1:
        if st.button("✅ Accept Plan", type="primary", key="accept_btn"):
            _handle_accept(database)

    with col2:
        if st.button("🔄 Start Over", key="regenerate_btn"):
            st.session_state.draft_plan_text = None
            st.session_state.draft_plan_json = None
            st.session_state.gemini_chat = None
            st.session_state.chat_history = []
            st.rerun()


def _tab_generate_plan(database: DatabaseManager, dataframe: pd.DataFrame):
    """Plan generation tab with preview → accept flow."""
    # Session state init
    for key, default in [
        ("draft_plan_text", None),
        ("draft_plan_json", None),
        ("gemini_chat", None),
        ("chat_history", []),
        ("plan_accepted", False),
        ("user_goal", ""),
    ]:
        if key not in st.session_state:
            st.session_state[key] = default

    active_plan = database.get_active_plan()

    # If there's already an accepted plan in the DB
    if active_plan and not st.session_state.draft_plan_text:
        if st.session_state.get("is_adapting"):
            _show_adapt_input(database, active_plan)
        else:
            _show_active_plan(database, active_plan)
        return

    # No draft yet — show goal input
    if not st.session_state.draft_plan_text:
        _show_goal_input(database)
        return

    # Draft exists — show preview + chat + accept/regenerate
    _show_draft_review(database, dataframe)


# ── Tab 2: Calendar View ────────────────────────────────────────────


def _tab_calendar(database: DatabaseManager, dataframe: pd.DataFrame):
    """Calendar tab showing planned workouts and actual activities."""
    plan = database.get_active_plan()

    # Fall back to draft plan in session state if no accepted plan yet
    using_draft = False
    if not plan:
        draft_json = st.session_state.get("draft_plan_json")
        draft_goal = st.session_state.get("user_goal", "Draft Plan")
        if draft_json:
            workouts = AICoach.plan_json_to_workouts(0, draft_json)
            plan = {
                "goal": draft_goal,
                "start_date": draft_json.get("start_date", ""),
                "end_date": draft_json.get("end_date", ""),
                "workouts": workouts,
            }
            using_draft = True

    if not plan:
        st.info("No active training plan. Generate one in the **Generate Plan** tab.")
        return

    if using_draft:
        st.warning("📋 Showing **draft plan** — accept it in the Generate Plan tab to save it.")
    st.markdown(f"**Goal:** {plan['goal']}")

    today = datetime.date.today()

    # Month navigation
    col1, _, col3 = st.columns([1, 2, 1])
    with col1:
        if st.button("◀ Previous", key="cal_prev"):
            if "cal_month" not in st.session_state:
                st.session_state.cal_month = today.month
                st.session_state.cal_year = today.year
            st.session_state.cal_month -= 1
            if st.session_state.cal_month < 1:
                st.session_state.cal_month = 12
                st.session_state.cal_year -= 1
            st.rerun()
    with col3:
        if st.button("Next ▶", key="cal_next"):
            if "cal_month" not in st.session_state:
                st.session_state.cal_month = today.month
                st.session_state.cal_year = today.year
            st.session_state.cal_month += 1
            if st.session_state.cal_month > 12:
                st.session_state.cal_month = 1
                st.session_state.cal_year += 1
            st.rerun()

    # Default to the plan's start month instead of today
    default_year, default_month = today.year, today.month
    if plan.get("start_date"):
        try:
            start = datetime.date.fromisoformat(plan["start_date"])
            default_year, default_month = start.year, start.month
        except ValueError:
            pass

    year = st.session_state.get("cal_year", default_year)
    month = st.session_state.get("cal_month", default_month)

    _render_calendar(year, month, plan["workouts"], dataframe)

    # Legend
    st.markdown("---")
    legend_items = [
        ("🟢 Easy Run", "#4CAF50"),
        ("🔵 Long Run", "#2196F3"),
        ("🟠 Tempo", "#FF9800"),
        ("🔴 Intervals", "#F44336"),
        ("🟣 Cross Training", "#9C27B0"),
        ("⚪ Rest", "#9E9E9E"),
    ]
    cols = st.columns(len(legend_items))
    for col, (label, color) in zip(cols, legend_items):
        col.markdown(
            f'<span style="color:{color};font-size:12px">{label}</span>',
            unsafe_allow_html=True,
        )

    # Weekly summary below calendar
    st.markdown("### 📊 Weekly Breakdown")
    workouts = plan["workouts"]
    if workouts:
        wdf = pd.DataFrame(workouts)
        wdf["workout_date"] = pd.to_datetime(wdf["workout_date"])
        wdf["week"] = wdf["workout_date"].dt.isocalendar().week

        for week_num, group in wdf.groupby("week"):
            total_dist = group["target_distance_km"].sum() if "target_distance_km" in wdf.columns else 0
            n_workouts = len(group[group["workout_type"] != "rest"])
            completed = group["completed"].sum() if "completed" in wdf.columns else 0
            dist_str = f"{total_dist:.1f}km planned, " if pd.notnull(total_dist) and total_dist > 0 else ""
            st.markdown(
                f"**Week {week_num}**: {n_workouts} workouts, "
                f"{dist_str}{int(completed)} completed"
            )


# ── Tab 3: Feedback & Chat ──────────────────────────────────────────


def _tab_feedback(database: DatabaseManager, _dataframe: pd.DataFrame):
    """Feedback tab with adherence analysis and coaching chat."""
    plan = database.get_active_plan()

    if not plan:
        st.info("No active training plan. Generate one in the **Generate Plan** tab.")
        return

    # Adherence analysis
    st.markdown("### 📈 Plan Adherence Analysis")

    if st.button("🔍 Analyze My Week", type="primary", key="analyze_btn"):
        with st.spinner("🤖 Coach is reviewing your training data..."):
            coach = _get_coach(database)
            analysis = coach.analyze_adherence()
            st.session_state["adherence_analysis"] = analysis

    if "adherence_analysis" in st.session_state:
        st.markdown(st.session_state["adherence_analysis"])

    st.divider()

    # Detailed Activity Feedback
    st.markdown("### 🔍 Detailed Activity Feedback")
    st.caption("Select a recent activity to get AI coach feedback.")
    if "activity_date" in _dataframe.columns:
        recent_activities = _dataframe.sort_values(by="activity_date", ascending=False).head(20)
        options = []
        for _, row in recent_activities.iterrows():
            date_str = row["activity_date"].strftime("%Y-%m-%d") if pd.notnull(row["activity_date"]) else ""
            name = row.get("activity_name", "Activity")
            options.append(f"{date_str} - {name} (ID: {row['activity_id']})")
        
        selected_activity = st.selectbox("Choose Activity:", [""] + options)
        if selected_activity:
            import re
            match = re.search(r"\(ID: (\d+)\)$", selected_activity)
            if match and st.button("Get Feedback", key="detailed_feedback_btn"):
                st.session_state.pending_feedback_prompt = f"Can you give me detailed feedback on the activity: {selected_activity}?"

    st.divider()

    # Coaching chat
    col1, col2 = st.columns([3, 1])
    with col1:
        st.markdown("### 💬 Ask Your Coach")
    with col2:
        if st.button("🔄 Adapt Plan", key="shortcut_adapt_btn", help="Takes you to Plan Generation to adapt your active plan."):
            st.session_state.is_adapting = True
            st.session_state.main_nav_radio = "📝 Generate Plan"
            st.rerun()

    if "feedback_chat" not in st.session_state:
        st.session_state.feedback_chat = None
    if "feedback_history" not in st.session_state:
        st.session_state.feedback_history = []

    chat_container = st.container()
    with chat_container:
        for msg in st.session_state.feedback_history:
            with st.chat_message(msg["role"]):
                st.markdown(msg["content"])

    prompt = st.chat_input("Ask your coach anything...", key="feedback_chat_input")
    
    # Override prompt if a UI button populated the pending request
    if st.session_state.get("pending_feedback_prompt"):
        prompt = st.session_state.pop("pending_feedback_prompt")

    if prompt:
        st.session_state.feedback_history.append({"role": "user", "content": prompt})
        with chat_container:
            with st.chat_message("user"):
                st.markdown(prompt)

            with st.chat_message("assistant"):
                with st.spinner("Thinking..."):
                    coach = _get_coach(database)
                    if not st.session_state.feedback_chat:
                        import google.genai.types as types
                        chat = coach.client.chats.create(
                            model=coach.model_id, 
                            config=types.GenerateContentConfig(
                                system_instruction=coach._coach_system_instruction,
                                tools=coach.tools
                            )
                        )
                        st.session_state.feedback_chat = chat

                    reply = coach.chat(st.session_state.feedback_chat, prompt)
                    st.markdown(reply)
                    st.session_state.feedback_history.append({"role": "assistant", "content": reply})
                    st.rerun()


def _sync_planned_workouts_with_activities(database: DatabaseManager, df: pd.DataFrame):
    """Auto-match activities in the dataframe to incomplete planned workouts."""
    plan = database.get_active_plan()
    if not plan or df.empty:
        return

    today_str = datetime.date.today().isoformat()
    workouts = plan.get("workouts", [])
    
    # Process only past/present workouts that aren't completed and aren't rest days
    incomplete_workouts = [
        w for w in workouts
        if w["workout_date"] <= today_str
        and w["workout_type"] != "rest"
        and not w.get("completed")
    ]

    for w in incomplete_workouts:
        w_date_str = w["workout_date"]
        
        # Look for activities on this date
        if "activity_date" in df.columns:
            day_activities = df[df["activity_date"].dt.strftime('%Y-%m-%d') == w_date_str]
            
            if not day_activities.empty:
                # Simple matching: pick the longest activity of the day
                best_match = day_activities.sort_values(by="distance", ascending=False).iloc[0]
                
                database.update_workout_completion(
                    workout_id=w["workout_id"],
                    activity_id=int(best_match["activity_id"]),
                    feedback="Auto-matched via Strava sync"
                )


# ── Main page ────────────────────────────────────────────────────────


def page_ai_training_plan(dataframe: pd.DataFrame, database: Optional[DatabaseManager] = None):
    """AI Coach Training Plan page with 3 tabs."""
    st.header("🤖 AI Coach")
    st.markdown(
        "Your personal AI running coach — powered by Gemini. "
        "Generate a plan, track it on the calendar, and get data-driven feedback."
    )

    if database is None:
        database = DatabaseManager()

    # Ensure new tables exist
    database.create_tables()

    _sync_planned_workouts_with_activities(database, dataframe)

    tab_names = ["📝 Generate Plan", "📅 Calendar", "💬 Feedback & Chat"]
    
    if "main_nav_radio" not in st.session_state:
        st.session_state.main_nav_radio = tab_names[0]

    st.markdown("""
        <style>
        div[role='radiogroup'] {
            flex-direction: row;
            gap: 20px;
            padding: 10px 0 20px 0;
            border-bottom: 2px solid rgba(255,255,255,0.1);
            margin-bottom: 20px;
        }
        </style>
    """, unsafe_allow_html=True)

    nav_selection = st.radio(
        "Navigation", 
        tab_names, 
        key="main_nav_radio",
        label_visibility="collapsed"
    )

    if nav_selection == tab_names[0]:
        _tab_generate_plan(database, dataframe)
    elif nav_selection == tab_names[1]:
        _tab_calendar(database, dataframe)
    else:
        _tab_feedback(database, dataframe)
