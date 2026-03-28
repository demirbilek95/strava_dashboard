"""Calendar rendering helpers and Calendar tab for the AI Coach Training Plan."""

import calendar
import datetime
from typing import Any, Dict

import pandas as pd
import streamlit as st

from strava.constants import ACTIVITY_TYPE_COLORS, WORKOUT_COLORS
from strava.utils.ai_coach import AICoach

_CALENDAR_CSS = """
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
.cal-day.today { border: 2px solid #88B4E7; }
.cal-day.empty { background: transparent; border: none; min-height: 0; }
.cal-day-num { font-weight: 600; margin-bottom: 4px; color: #ddd; }
.cal-workout {
    font-size: 11px; padding: 3px 6px; border-radius: 4px;
    margin-bottom: 2px; color: #fff; line-height: 1.3;
}
.cal-actual {
    font-size: 10px; padding: 2px 5px; border-radius: 3px;
    background: rgba(255,255,255,0.1); color: #aaa;
    margin-top: 2px; border-left: 2px solid #B8E0B8;
}
.cal-detail {
    font-size: 10px; color: #bbb; padding: 1px 6px;
    line-height: 1.3; margin-bottom: 2px;
}
</style>
"""

_ACTIVITY_EMOJI: Dict[str, str] = {
    "Run": "\U0001f3c3",
    "Ride": "\U0001f6b4",
    "Swim": "\U0001f3ca",
    "Walk": "\U0001f6b6",
    "Hike": "\U0001f9d7",
    "Workout": "\U0001f4aa",
    "WeightTraining": "\U0001f4aa",
    "Yoga": "\U0001f9d8",
    "Pilates": "\U0001f9d8",
    "Crossfit": "\U0001f4aa",
    "Rowing": "\U0001f6a3",
    "Soccer": "\u26bd",
    "Tennis": "\U0001f3be",
}

_ICON_MAP: Dict[str, str] = {
    "completed": "\u2705",
    "missed": "\u274c",
    "upcoming": "\U0001f4cb",
    "rest": "\U0001f634",
}

_INVALID_STR_VALUES = frozenset(("n/a", "none", "null", ""))


def _get_workout_color(workout_type: str) -> str:
    return WORKOUT_COLORS.get(workout_type, ACTIVITY_TYPE_COLORS.get(workout_type, "#CFCFCF"))


def _get_status(workout: Dict[str, Any]) -> str:
    today = datetime.date.today().isoformat()
    if workout.get("completed"):
        return "completed"
    if workout["workout_type"] == "rest":
        return "rest"
    if workout["workout_date"] < today:
        return "missed"
    return "upcoming"


def _build_workout_html(w: Dict[str, Any]) -> str:
    """Build HTML for a single planned workout cell entry."""
    color = _get_workout_color(w["workout_type"])
    status = _get_status(w)
    opacity = "0.5" if status == "missed" else "1.0"
    label = w["workout_type"].replace("_", " ").title()

    stats_parts = []
    dist = w.get("target_distance_km")
    if dist and str(dist).lower() not in _INVALID_STR_VALUES:
        stats_parts.append(f"{dist}km")
    pace_val = w.get("target_pace_min_km")
    if pace_val and str(pace_val).lower() not in _INVALID_STR_VALUES:
        try:
            pv = float(pace_val)
            mins, secs = int(pv), int((pv - int(pv)) * 60)
            stats_parts.append(f"{mins}:{secs:02d}/km")
        except ValueError:
            stats_parts.append(f"{pace_val}/km")
    sep = " \u00b7 "
    stats_str = (sep + sep.join(stats_parts)) if stats_parts else ""

    html = (
        f'<div class="cal-workout" style="background:{color};opacity:{opacity}">'
        f"{_ICON_MAP.get(status, '')} {label}{stats_str}</div>"
    )
    details = []
    if w.get("description") and w["workout_type"] != "rest":
        details.append(w["description"])
    hr_zone = w.get("target_hr_zone")
    if hr_zone and str(hr_zone).lower() not in _INVALID_STR_VALUES:
        details.append(hr_zone)
    if details:
        html += f'<div class="cal-detail">{sep.join(details)}</div>'
    return html


def _build_activity_html(act) -> str:
    """Build HTML for a single actual activity cell entry."""
    a_type = act.get("activity_type", "")
    emoji = _ACTIVITY_EMOJI.get(a_type, "\U0001f4ca")
    name = act.get("activity_name", a_type or "Activity")
    raw_dist = act.get("distance", 0)
    dist_str = f"{raw_dist:.1f}k" if pd.notnull(raw_dist) and raw_dist >= 0.1 else ""
    pace = ""
    if dist_str and pd.notnull(act.get("moving_time")) and act["moving_time"] > 0:
        pace_dec = (act["moving_time"] / 60) / raw_dist
        mins, secs = int(pace_dec), int((pace_dec - int(pace_dec)) * 60)
        pace = f"{mins}:{secs:02d}/k"
    hr_val = act.get("average_heart_rate")
    hr = f"{int(hr_val)}bpm" if pd.notnull(hr_val) and hr_val else ""
    stats = " \u00b7 ".join(d for d in [dist_str, pace, hr] if d)
    label = stats if stats else name
    return f'<div class="cal-actual" title="{name}">{emoji} {label}</div>'


def _render_month_nav(key_prefix: str, default_month: int, default_year: int) -> None:
    """Render previous/next month navigation buttons and update session state.

    Session state keys are derived from ``key_prefix``:
    ``{key_prefix}_month``, ``{key_prefix}_year``.
    """
    month_key = f"{key_prefix}_month"
    year_key = f"{key_prefix}_year"
    st.session_state.setdefault(month_key, default_month)
    st.session_state.setdefault(year_key, default_year)
    col1, _, col3 = st.columns([1, 2, 1])
    with col1:
        if st.button("\u25c4 Previous", key=f"{key_prefix}_prev"):
            new_month = st.session_state[month_key] - 1
            if new_month < 1:
                st.session_state[month_key] = 12
                st.session_state[year_key] -= 1
            else:
                st.session_state[month_key] = new_month
            st.rerun()
    with col3:
        if st.button("Next \u25ba", key=f"{key_prefix}_next"):
            new_month = st.session_state[month_key] + 1
            if new_month > 12:
                st.session_state[month_key] = 1
                st.session_state[year_key] += 1
            else:
                st.session_state[month_key] = new_month
            st.rerun()


def _render_calendar(year: int, month: int, workouts: list, activities_df: pd.DataFrame) -> None:
    """Render a monthly calendar with planned workouts and actual activities."""
    cal = calendar.Calendar(firstweekday=0)
    month_days = cal.monthdayscalendar(year, month)
    month_name = calendar.month_name[month]

    workout_by_date: Dict[str, list] = {}
    for w in workouts:
        workout_by_date.setdefault(w["workout_date"], []).append(w)

    activity_by_date: Dict[str, list] = {}
    if not activities_df.empty and "activity_date" in activities_df.columns:
        for _, row in activities_df.iterrows():
            date_key = row["activity_date"].strftime("%Y-%m-%d")
            activity_by_date.setdefault(date_key, []).append(row)

    today = datetime.date.today()
    html = _CALENDAR_CSS + f'<h3 style="text-align:center;color:#ddd;">{month_name} {year}</h3>'
    html += '<div class="cal-grid">'
    for day_name in ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]:
        html += f'<div class="cal-header">{day_name}</div>'

    for week in month_days:
        for day in week:
            if day == 0:
                html += '<div class="cal-day empty"></div>'
                continue
            date_obj = datetime.date(year, month, day)
            date_str = date_obj.isoformat()
            classes = "cal-day" + (" today" if date_obj == today else "")
            html += f'<div class="{classes}"><div class="cal-day-num">{day}</div>'
            for w in workout_by_date.get(date_str, []):
                html += _build_workout_html(w)
            for act in activity_by_date.get(date_str, [])[:4]:
                html += _build_activity_html(act)
            html += "</div>"

    html += "</div>"
    st.markdown(html, unsafe_allow_html=True)


def _render_weekly_breakdown(workouts: list) -> None:
    """Render weekly training breakdown below the calendar."""
    st.markdown("### \U0001f4ca Weekly Breakdown")
    if not workouts:
        return
    wdf = pd.DataFrame(workouts)
    wdf["workout_date"] = pd.to_datetime(wdf["workout_date"])
    wdf["week"] = wdf["workout_date"].dt.isocalendar().week
    for week_num, group in wdf.groupby("week"):
        total_dist = group["target_distance_km"].sum() if "target_distance_km" in wdf.columns else 0
        n_workouts = len(group[group["workout_type"] != "rest"])
        completed = group["completed"].sum() if "completed" in wdf.columns else 0
        dist_str = (
            f"{total_dist:.1f}km planned, " if pd.notnull(total_dist) and total_dist > 0 else ""
        )
        st.markdown(
            f"**Week {week_num}**: {n_workouts} workouts, " f"{dist_str}{int(completed)} completed"
        )


def _tab_calendar(database, dataframe: pd.DataFrame) -> None:
    """Calendar tab showing planned workouts and actual activities."""
    plan = database.get_active_plan()
    using_draft = False
    if not plan:
        draft_json = st.session_state.get("draft_plan_json")
        if draft_json:
            workouts = AICoach.plan_json_to_workouts(0, draft_json)
            plan = {
                "goal": st.session_state.get("user_goal", "Draft Plan"),
                "start_date": draft_json.get("start_date", ""),
                "end_date": draft_json.get("end_date", ""),
                "workouts": workouts,
            }
            using_draft = True

    if not plan:
        st.info("No active training plan. Generate one in the **Generate Plan** tab.")
        return

    if using_draft:
        st.warning(
            "\U0001f4cb Showing **draft plan** "
            "\u2014 accept it in the Generate Plan tab to save it."
        )
    st.markdown(f"**Goal:** {plan['goal']}")

    today = datetime.date.today()
    default_year, default_month = today.year, today.month
    if plan.get("start_date"):
        try:
            start = datetime.date.fromisoformat(plan["start_date"])
            default_year, default_month = start.year, start.month
        except ValueError:
            pass

    _render_month_nav("cal", default_month, default_year)
    year = st.session_state.get("cal_year", default_year)
    month = st.session_state.get("cal_month", default_month)
    _render_calendar(year, month, plan["workouts"], dataframe)

    st.markdown("---")
    legend_items = [
        ("● Easy Run", WORKOUT_COLORS["easy_run"]),
        ("● Long Run", WORKOUT_COLORS["long_run"]),
        ("● Tempo", WORKOUT_COLORS["tempo"]),
        ("● Intervals", WORKOUT_COLORS["intervals"]),
        ("● Cross Training", WORKOUT_COLORS["cross_training"]),
        ("● Rest", WORKOUT_COLORS["rest"]),
    ]
    for col, (label, color) in zip(st.columns(len(legend_items)), legend_items):
        col.markdown(
            f'<span style="color:{color};font-size:12px">{label}</span>',
            unsafe_allow_html=True,
        )
    _render_weekly_breakdown(plan["workouts"])
