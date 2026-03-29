import time
from typing import Optional

import pandas as pd
import streamlit as st

from strava.constants import BEST_EFFORT_NAMES, classify_zone
from strava.db.db_manager import DatabaseManager
from strava.utils.activity_processing import fmt_duration, fmt_pace


def _get_race_categories():
    return {
        "5K": (4.5, 5.5),
        "10K": (9.5, 10.6),
        "Half Marathon": (20.5, 22.0),
        "Marathon": (41.5, 43.5),
    }


def _time_col(df):
    return "elapsed_time" if "elapsed_time" in df.columns else "moving_time"


def _calculate_metrics(row, zones):
    col = "elapsed_time" if "elapsed_time" in row else "moving_time"
    seconds = row[col]
    dist = row["distance"]

    hr_val = row.get("average_heart_rate")
    if pd.isna(hr_val):
        hr_val = None

    max_hr = row.get("max_heart_rate")

    return {
        "activity_id": row["activity_id"],
        "time_str": fmt_duration(seconds),
        "pace_str": fmt_pace((seconds / 60) / dist, " /km") if dist > 0 else "N/A",
        "avg_hr_str": f"{int(hr_val)} bpm" if hr_val else "N/A",
        "max_hr_str": f"{int(max_hr)} bpm" if not pd.isna(max_hr) else "N/A",
        "zone_str": classify_zone(hr_val, zones) if hr_val else "N/A",
        "date_str": row["activity_date"].strftime("%Y-%m-%d"),
        "name": row.get("activity_name", "Run"),
        "dist": dist,
    }


def _display_performance_card(m, category, rank=None, is_latest=False):
    if rank:
        title = f"#{rank}: {m['time_str']} — {m['name']} ({m['date_str']})"
    elif is_latest:
        title = f"Latest: {m['time_str']} — {m['name']} ({m['date_str']})"
    else:
        title = f"{m['name']} ({m['date_str']})"

    with st.expander(title, expanded=(rank == 1 or is_latest)):
        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("Time", m["time_str"])
        c2.metric("Pace", m["pace_str"])
        c3.metric("Avg HR", m["avg_hr_str"])
        c4.metric("Max HR", m["max_hr_str"])
        c5.metric("Zone", m["zone_str"])

        col_dist, col_btn = st.columns([4, 1])
        col_dist.caption(f"Exact distance: {m['dist']:.2f} km")
        btn_key = f"btn_{category.lower().replace(' ', '_')}_{m['activity_id']}"
        if col_btn.button("🔍 Deep Dive", key=btn_key):
            st.session_state["selected_activity_id"] = m["activity_id"]
            st.session_state["requested_page"] = "Deep Dive"
            st.rerun()


# ── Races tab ──────────────────────────────────────────────────────────────────


def _render_races(df_runs, zones):  # pylint: disable=too-many-branches,too-many-statements
    st.caption(
        "All-time race results (activities flagged as races in Strava), "
        "regardless of the sidebar period."
    )
    race_cats = _get_race_categories()
    has_workout_type = "workout_type" in df_runs.columns
    tcol = _time_col(df_runs)

    # Keep only actual races (workout_type == 1)
    if has_workout_type:
        races_only = df_runs[df_runs["workout_type"] == 1].copy()
    else:
        races_only = pd.DataFrame()

    # ── Overview row ───────────────────────────────────────────────
    cols = st.columns(4)
    for idx, (cat_name, (min_d, max_d)) in enumerate(race_cats.items()):
        with cols[idx]:
            if races_only.empty:
                st.metric(cat_name, "—")
                st.caption("No races")
                continue
            matches = races_only[
                (races_only["distance"] >= min_d) & (races_only["distance"] <= max_d)
            ].sort_values(by=tcol)
            if matches.empty:
                st.metric(cat_name, "—")
                st.caption("No races")
            else:
                best = matches.iloc[0]
                m = _calculate_metrics(best, zones)
                count = len(matches)
                st.metric(cat_name, m["time_str"])
                st.caption(
                    f"{m['date_str']} · {m['pace_str']} · {count} race{'s' if count != 1 else ''}"
                )

    st.markdown("---")

    if races_only.empty:
        st.info(
            "No activities flagged as races found. "
            "Mark an activity as a race in Strava to see it here."
        )
        return

    # ── Detailed breakdown (top 3 per distance) ────────────────────
    any_races = False
    for cat_name, (min_d, max_d) in race_cats.items():
        matches = races_only[
            (races_only["distance"] >= min_d) & (races_only["distance"] <= max_d)
        ].sort_values(by=tcol)

        if matches.empty:
            continue

        any_races = True
        best = matches.iloc[0]
        m = _calculate_metrics(best, zones)
        count = len(matches)
        label = (
            f"**{cat_name}** — Best: {m['time_str']}  ·  {count} race{'s' if count != 1 else ''}"
        )

        with st.expander(label, expanded=True):
            c1, c2, c3, c4, c5 = st.columns(5)
            c1.metric("Best Time", m["time_str"])
            c2.metric("Pace", m["pace_str"])
            c3.metric("Avg HR", m["avg_hr_str"])
            c4.metric("Max HR", m["max_hr_str"])
            c5.metric("Distance", f"{m['dist']:.2f} km")

            col_date, col_btn = st.columns([4, 1])
            col_date.caption(f"{m['name']} · {m['date_str']}")
            k = f"btn_best_{cat_name.lower().replace(' ', '_')}_{m['activity_id']}"
            if col_btn.button("🔍 Deep Dive", key=k):
                st.session_state["selected_activity_id"] = m["activity_id"]
                st.session_state["requested_page"] = "Deep Dive"
                st.rerun()

            # Show remaining races (best is already shown above)
            rest = matches.iloc[1:3]  # up to 2 more = top 3 total
            if not rest.empty:
                st.markdown("**Other top races:**")
                for _, row in rest.iterrows():
                    rm = _calculate_metrics(row, zones)
                    rk = f"btn_race_{cat_name.lower().replace(' ', '_')}_{rm['activity_id']}"
                    rcol1, rcol2 = st.columns([5, 1])
                    rcol1.write(
                        f"· {rm['date_str']} — **{rm['time_str']}**"
                        f" · {rm['pace_str']} · {rm['avg_hr_str']} · {rm['name']}"
                    )
                    if rcol2.button("🔍", key=rk):
                        st.session_state["selected_activity_id"] = rm["activity_id"]
                        st.session_state["requested_page"] = "Deep Dive"
                        st.rerun()

    if not any_races:
        st.info("No races found at standard distances (5K / 10K / Half / Full Marathon).")


# ── Personal Records tab ───────────────────────────────────────────────────────


def _render_personal_records(  # pylint: disable=too-many-branches,too-many-statements
    df_runs, zones, start_date
):
    race_cats = _get_race_categories()
    tcol = _time_col(df_runs)

    # Period label + filtered slice
    if start_date is not None:
        period_label = start_date.strftime("%b %d, %Y")
        period_runs = df_runs[df_runs["activity_date"].dt.date >= start_date].copy()
    else:
        period_label = "All Time"
        period_runs = df_runs.copy()

    st.caption(
        f"Period: **Since {period_label}** · Change via the sidebar Period selector."
        if start_date
        else "Period: **All Time** · Change via the sidebar Period selector."
    )

    # All-time bests for delta calculation
    alltime_best_s: dict = {}
    for cat_name, (min_d, max_d) in race_cats.items():
        matches = df_runs[(df_runs["distance"] >= min_d) & (df_runs["distance"] <= max_d)]
        if not matches.empty:
            alltime_best_s[cat_name] = int(matches.sort_values(by=tcol).iloc[0][tcol])

    # ── Overview row ───────────────────────────────────────────────
    cols = st.columns(4)
    for idx, (cat_name, (min_d, max_d)) in enumerate(race_cats.items()):
        with cols[idx]:
            matches = period_runs[
                (period_runs["distance"] >= min_d) & (period_runs["distance"] <= max_d)
            ]
            if matches.empty:
                st.metric(cat_name, "—")
                st.caption("No runs this period")
                continue

            best = matches.sort_values(by=tcol).iloc[0]
            m = _calculate_metrics(best, zones)
            best_s = int(best[tcol])

            if cat_name in alltime_best_s:
                delta_s = best_s - alltime_best_s[cat_name]
                if abs(delta_s) <= 1:
                    delta_str, delta_color = "All-Time Best 🏆", "off"
                else:
                    mins, secs = divmod(abs(delta_s), 60)
                    sign = "+" if delta_s > 0 else "−"
                    delta_str = f"{sign}{mins}:{secs:02d}"
                    delta_color = "inverse"  # lower is better: negative→green, positive→red
            else:
                delta_str, delta_color = None, "off"

            st.metric(cat_name, m["time_str"], delta=delta_str, delta_color=delta_color)
            st.caption(f"{m['date_str']} · {m['pace_str']}")

    st.markdown("---")

    # ── Detailed breakdown ─────────────────────────────────────────
    any_data = False
    for cat_name, (min_d, max_d) in race_cats.items():
        matches = period_runs[
            (period_runs["distance"] >= min_d) & (period_runs["distance"] <= max_d)
        ].sort_values(by=tcol)

        if matches.empty:
            continue

        any_data = True
        count = len(matches)
        best = matches.iloc[0]
        m = _calculate_metrics(best, zones)

        label = (
            f"**{cat_name}** — Best: {m['time_str']}"
            f"  ·  {count} run{'s' if count > 1 else ''} this period"
        )
        with st.expander(label, expanded=True):
            c1, c2, c3, c4, c5 = st.columns(5)
            c1.metric("Time", m["time_str"])
            c2.metric("Pace", m["pace_str"])
            c3.metric("Avg HR", m["avg_hr_str"])
            c4.metric("Max HR", m["max_hr_str"])
            c5.metric("Distance", f"{m['dist']:.2f} km")

            col_date, col_btn = st.columns([4, 1])
            col_date.caption(f"{m['name']} · {m['date_str']}")
            k = f"pr_dive_{cat_name.lower().replace(' ', '_')}_{m['activity_id']}"
            if col_btn.button("🔍 Deep Dive", key=k):
                st.session_state["selected_activity_id"] = m["activity_id"]
                st.session_state["requested_page"] = "Deep Dive"
                st.rerun()

            if count > 1:
                st.markdown("**All runs this period:**")
                for _, row in matches.iterrows():
                    rm = _calculate_metrics(row, zones)
                    st.write(
                        f"· {rm['date_str']} — **{rm['time_str']}**"
                        f" · {rm['pace_str']} · {rm['avg_hr_str']} · {rm['name']}"
                    )

    if not any_data:
        st.info(
            "No runs at standard distances found for this period. "
            "Try a longer period in the sidebar."
        )


# ── Best Efforts tab ───────────────────────────────────────────────────────────

# Strava workout_type=3 means "Workout" (intervals/tempo) — flag these
# in the UI so users know the PR may have come from a structured session.
_WORKOUT_LABEL = {3: "Workout/Intervals"}


def _effort_source_label(workout_type) -> str:
    """Return a short label if the effort came from a structured workout."""
    return _WORKOUT_LABEL.get(workout_type, "")


def _render_best_efforts(database: DatabaseManager, zones):
    st.caption(
        "Strava-verified segment PRs from every run — including mid-run efforts "
        "(e.g. a 5k PR set inside a longer run). Only rank-1 (gold) PRs are shown. "
        "Entries marked **Workout/Intervals** may reflect interval-session paces."
    )

    prs = database.get_pr_summary()

    if not prs:
        st.info(
            "No best effort data yet. Sync your activities (or re-sync) "
            "to populate this section."
        )
        return

    # Index by effort name for ordered display
    pr_map = {row["effort_name"]: row for row in prs}
    ordered = [name for name in BEST_EFFORT_NAMES if name in pr_map]

    if not ordered:
        st.info("No best efforts found.")
        return

    # ── Overview grid (4 per row) ───────────────────────────────────
    cols_per_row = 4
    for row_start in range(0, len(ordered), cols_per_row):
        chunk = ordered[row_start : row_start + cols_per_row]
        cols = st.columns(cols_per_row)
        for col, effort_name in zip(cols, chunk):
            row = pr_map[effort_name]
            t = row["elapsed_time"] or row["moving_time"]
            dist_m = row["distance"]
            pace = fmt_pace((t / 60) / (dist_m / 1000)) if t and dist_m else "N/A"
            date_str = pd.to_datetime(row["activity_date"]).strftime("%Y-%m-%d")
            with col:
                st.metric(effort_name, fmt_duration(t) if t else "N/A")
                st.caption(f"{pace} /km · {date_str}")

    st.markdown("---")

    # ── Detail expanders ────────────────────────────────────────────
    for effort_name in ordered:
        row = pr_map[effort_name]
        t = row["elapsed_time"] or row["moving_time"]
        dist_m = row["distance"]
        pace = fmt_pace((t / 60) / (dist_m / 1000)) if t and dist_m else "N/A"
        date_str = pd.to_datetime(row["activity_date"]).strftime("%Y-%m-%d")
        hr_val = row.get("average_heartrate")
        max_hr = row.get("max_heartrate")
        source = _effort_source_label(row.get("workout_type"))

        label = f"**{effort_name}** — {fmt_duration(t) if t else '?'} · {pace} /km"
        if source:
            label += f" · ⚠️ {source}"
        with st.expander(label):
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Time", fmt_duration(t) if t else "N/A")
            c2.metric("Pace", f"{pace} /km")
            c3.metric("Avg HR", f"{int(hr_val)} bpm" if hr_val else "N/A")
            c4.metric("Zone", classify_zone(hr_val, zones) if hr_val else "N/A")

            col_info, col_btn = st.columns([4, 1])
            caption = f"{row.get('activity_name', 'Run')} · {date_str}"
            if max_hr:
                caption += f" · Max HR: {int(max_hr)} bpm"
            if source:
                caption += f" · {source}"
            col_info.caption(caption)
            btn_key = f"be_dive_{effort_name}_{row['activity_id']}"
            if col_btn.button("🔍 Deep Dive", key=btn_key):
                st.session_state["selected_activity_id"] = row["activity_id"]
                st.session_state["requested_page"] = "Deep Dive"
                st.rerun()


# ── Entry point ────────────────────────────────────────────────────────────────

_RACES_IMPORTED_KEY = "races_imported_at"


def _auto_fetch_races(database: DatabaseManager) -> None:
    from strava.db.api_importer import StravaImporter  # pylint: disable=import-outside-toplevel
    from strava.utils.strava_api import StravaAPI  # pylint: disable=import-outside-toplevel

    try:
        api = StravaAPI()
        importer = StravaImporter(database, api)
        progress_bar = st.progress(0)
        status_text = st.empty()

        def _cb(msg, pct):
            status_text.text(msg)
            progress_bar.progress(pct)

        count = importer.import_races(progress_callback=_cb)
        database.set_setting(_RACES_IMPORTED_KEY, str(int(time.time())))
        if count:
            st.cache_data.clear()
            st.rerun()
        else:
            status_text.empty()
            progress_bar.empty()
    except Exception as exc:  # pylint: disable=broad-exception-caught
        st.warning(f"Could not load race history: {exc}")


def page_races(df, zones, database: Optional[DatabaseManager] = None, start_date=None):
    st.header("Races & Personal Running Records")

    if database is not None and database.get_setting(_RACES_IMPORTED_KEY) is None:
        _auto_fetch_races(database)

    if "activity_type" in df.columns:
        df_runs = df[df["activity_type"] == "Run"].copy()
    else:
        df_runs = df.copy()

    if df_runs.empty:
        st.warning("No running activities found.")
        return

    tab_races, tab_prs, tab_be = st.tabs(["🏁 Races", "🏆 Running PRs", "⚡ Best Efforts"])

    with tab_races:
        _render_races(df_runs, zones)

    with tab_prs:
        _render_personal_records(df_runs, zones, start_date)

    with tab_be:
        if database is not None:
            _render_best_efforts(database, zones)
        else:
            st.info("Database connection required to display best efforts.")
